"""活动剧情：把本期活动「观看故事」列表里的故事从头看到尾。

## 这条路线在做什么

活动剧情页（左上角一行「观看故事」标题）右侧是一列**故事条目**，右下角有一颗
**「观看 / 战斗」**按钮。点它 → 进剧情（右上角跳过）或进战斗（选队伍 → 打完 →
结算）→ 回到**同一个页面**，列表自动前进、解锁下一段。如此循环，直到右下角那颗
按钮变成**不消耗票**的状态 —— 那就是本期到头了（用户 2026-10-31 确认）。

它和「支线故事」不是一回事：支线有关卡地图、角色光标、场景页的蓝色三箭头；
这条路线**只有一页**反复点，中间的剧情 / 战斗 / 结算全部与主线同页同长相。

## 复用优先

剧情跳过 / 跳过确认 / 选队伍 / 战斗开始 / 自动战斗 / 结算 / 通关提示 / 体力弹窗
整段复用 `StoryStateMachine` 与 `StoryAction`（用户原话：「就走那个主线的剧情那一套」）。
本类只补两样它不认识的东西：**观看故事页的页面判据**，和**「这一期看完了」**。

## 独有判据

| 判据 | 模板 / 口径 | 实测（全库 685 张全屏帧） |
|---|---|---|
| 观看故事页 | `watch_story_title`（左上角白字）+ 白掩膜 | 本页 1.0000；其余天花板 0.6710（`epic7_side_story/episode_detail.png`）|
| 按钮上的票券徽章 | `ticket_cost` + 白掩膜 | 本页 1.0000；**支线场景页 0.8801** ⇒ 不排他，只作辅助 |
| 看完（不耗票） | `ticket_free`（等实机采集） | 暂无样本 |

⚠️ **徽章不排他**：支线故事的「重新进行」按钮左边是**同一个**马头图标（体力/票券
是通用图标，`epic7_side_story/scene.png` 上 raw 口径 0.9778、白掩膜 0.8801）。
所以它**不能单独当页面判据** —— 只在标题命中之后、或作为「认得出按钮但标题没认出来」
的辅助信号使用。

## 终点：主判据 + 一条踩过两次坑的兜底

用户确认：全部看完后按钮**还在、也不变灰**，只是**不再消耗票**（图标样子变了）。
所以终点是「按钮上那颗票券标记变样/消失」，不是「按钮消失」。

`ticket_free` 模板还没采到（要实机跑到「已看完」那一态），所以先留一条不依赖模板的
兜底：**点完、真的离开过本页、再回来时画面没有往前走** = 这一下没解锁新内容。

⚠️ 这条兜底被实跑改过两次，两个前提缺一不可：

1. **必须先离开过本页**（`_left_page`）。2026-10-31 第一次实跑就死在这：点「准备战斗」
   之后游戏要加载几秒，中间那几帧还是本页 ⇒ 立刻判「没变化」⇒ 只跑了一关就收工。
2. **比较的必须是「故事列表 + 按钮」两块**。票数是**持有/上限**、看剧情**不扣**
   （实测两次都是 20/xxx），而「观看 → 观看」两段之间按钮文案也一样 ⇒ 只看按钮区
   一个像素都不会变。真正会动的是右侧故事列表（高亮项下移 + 上一项补绿勾）。

还要**连续两次**没进展才收工（`_PROGRESS_MISS_LIMIT`）：加载 / 动画总会给出一帧
没变的画面，一次太急；两次的代价只是多看一眼（不耗票）。

⚠️ 也别每帧都拿相邻帧比 —— 这个页面是静止的（实测相邻帧差 0.000），那样第一秒
就会把自己判成「看完了」。

## 起点：不做导航

`needs_navigation=False`：用户先手动把游戏停到「观看故事」页再启动（与活动小游戏
同一种用法）。活动入口每期都会变，写死一条导航链反而是负担。也因为没有导航，
跑完不做任何「回大厅」动作（`home_return` 为 None ⇒ 收工就停在当前页）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.battle_supervisor import (
    BattleConfig,
    BattleObservation,
    BattleSupervisor,
)
from auto_game_unified.core.matcher import (
    MATCH_MODE_RAW,
    MATCH_MODE_WHITE_MASK,
    find_template,
    load_template,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.games.epic7.story import (
    StoryAction,
    StoryRunner,
    StoryState,
    StoryStateMachine,
    StoryTemplates,
    build_story_templates,
    state_label,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class ActivityStoryCleared(StaminaExhausted):
    """本期活动剧情已经全部看完。

    与支线故事的 ``SideStoryCleared``、月塔的 ``FloorsConquered`` 同族（都继承
    ``StaminaExhausted``，退出码 2「干完了、没得干了」）：对用户不是失败。

    ⚠️ ``stop_label`` 必须自己给：继承来的是「生命之叶耗尽」，用户看到会以为
    要去补叶子 —— 这里缺的**不是体力**，是「这一期没有没看过的故事了」。
    """

    stop_label = "本期活动剧情已看完"


# ── 观看故事页 ────────────────────────────────────────────────────────────────
# 左上角标题。区域刻意只罩住那一行：主线的关卡入口也有一颗白字「观看故事」按钮，
# 但它在右下角 (1450,930,470,202)，两边靠区域互不打扰。
_TITLE_REGION = (60, 55, 420, 90)

# 右下角那颗按钮（票券徽章 + 票数 + 观看/战斗）。整块用来做「点完有没有消耗」的指纹。
#
# ⚠️ 区域必须**盖住票数**（实测数字在 x≈1525~1615、y≈1032~1062）：票数减 1 是
# 「这一下真的消耗了票」的唯一直接物证。
_BUTTON_REGION = (1450, 995, 420, 108)
# 按钮中心。实测胶囊横跨 x≈1452~1860、y≈1000~1095，取中间偏左一点，
# 避开右侧「观看」二字的字形（点哪都有效，这里只是让日志里的坐标有出处）。
_BUTTON_POINT = (1656, 1047)

# ── 「这一段有没有往前走」的判据 ───────────────────────────────────────────────
#
# ⚠️ 只看按钮区是不够的（2026-10-31 第一次实跑就栽在这）：票数是**持有/上限**，
# 看剧情**不扣**（实测 19:07 与 19:29 两次都是 20/xxx），而「观看 → 观看」两段
# 之间按钮文案也一样 ⇒ **按钮区一个像素都不变**。真正会动的是右侧**故事列表**：
# 高亮项往下移一格、上一项补上绿勾。
#
# ⇒ 把「按钮区 + 列表区」一起比，取变化像素的较大者。
_LIST_REGION = (1400, 140, 520, 800)
# 实测（2026-10-31 19:30，同一页连截 3 帧）：按钮区 **0**、列表区 **0~473**。
# 阈值取 2000：离静止噪声 4 倍余量，而换一段故事时高亮块+文字至少几千像素。
_PROGRESS_CHANGED_PIXELS = 2000
# 连续多少次「点完回来、画面没往前走」才承认本期到头。
# 1 次太急（加载/动画会给出一帧没变的画面），2 次足够且代价只是多看一段。
_PROGRESS_MISS_LIMIT = 2

# 单个像素的差异幅度门槛：低于它算「同一颜色」的压缩噪声。
_BUTTON_PIXEL_DELTA = 24

# 本页的日志名。`STAGE` 这个状态被借来表示「观看故事页」，动作契约里也用它当页面名。
_SELECT_PAGE = "观看故事页"

_ACTIVITY_TEMPLATE_NAMES = ("watch_story_title", "ticket_cost", "ticket_free", "battle_clear")

# ── 战斗关的 CLEAR ─────────────────────────────────────────────────────────────
#
# 活动剧情里「观看」= 剧情关、「准备战斗」= 战斗关。战斗打完那一屏是**橙菱形 +
# CLEAR 字标带**，与支线故事那一页**逐字同款**（2026-10-31 19:42 的失败帧就是它）。
# 主线的 `clear` 是**剧情关**的 CLEAR（另一页、另一个位置）⇒ 认不出它，战斗监督
# 因此判「未知画面」，干等 215 秒报 `battle_unrecognized`。
#
# ⇒ 模板直接复用支线那一张，不复制一份：同一张图存两处 = 两个数源，改一处漏一处。
# 先例是月塔的 `battle_guide_title` 复用主线的（`evidence/tower.py::_TEMPLATE_PATHS`）。
_CLEAR_TEMPLATE = ("side_story", "battle_clear.png")
# 搜索区与口径照抄支线：判断「CLEAR 字标带」在不在，不看发光、不看底图。
_CLEAR_REGION = (400, 200, 1000, 500)
_CLEAR_THRESHOLD = 0.80
# 打完这一屏可能去哪：先结算 / 直接回观看故事页，两种都算正常落点。
# 少写一个，主循环就判「转场没完成」并把动作整个丢掉（支线 10-15 的死法）。
_CLEAR_TARGET_PAGES = ("结算确认", "通关提示", "奖励结算", _SELECT_PAGE)

_ACTIVITY_REGIONS = {
    "watch_story_title": _TITLE_REGION,
    "ticket_cost": _BUTTON_REGION,
    "ticket_free": _BUTTON_REGION,
    "battle_clear": _CLEAR_REGION,
}

_ACTIVITY_THRESHOLDS = {
    # 白掩膜口径实测：本页 1.0000，全库 685 张全屏帧的天花板 0.6710
    #（`epic7_side_story/episode_detail.png` 那一屏）。
    # 0.85 离天花板 0.179、离真阳性地板 0.15，两边都宽。
    "watch_story_title": 0.85,
    # 徽章**不排他**（支线场景页 0.8801），所以阈值刻意压在它上面一点；
    # 它只用来回答「这是不是那颗带票券标记的按钮」，不单独定义页面。
    "ticket_cost": 0.90,
    # 免费态模板还没采到。阈值先给 0.85，采到后按实测重定 —— 它将来是**主判据**，
    # 必须比现在这条兜底更早生效。
    "ticket_free": 0.85,
    # 与支线同一个阈值（2026-10-31 复扫 687 帧）：
    #   真·战斗 CLEAR（含本路线失败帧）…… 0.9787 ~ 1.0000
    #   本路线会遇到的其它页最高 ………… 0.2854（剧情播放）
    #   剧情关 CLEAR（必须挡住）………… 0.2138
    "battle_clear": _CLEAR_THRESHOLD,
}

# 判据 → 比对口径。三张都是白字 / 白色徽章，底图是会换的活动背景 ⇒ 全部走白掩膜。
_ACTIVITY_MATCH_MODES = {
    "watch_story_title": MATCH_MODE_WHITE_MASK,
    "ticket_cost": MATCH_MODE_WHITE_MASK,
    "ticket_free": MATCH_MODE_WHITE_MASK,
    "battle_clear": MATCH_MODE_WHITE_MASK,
}

# 点完「观看 / 战斗」可能落到哪些页面。这四个都是**真的可能**的落点：
# 剧情播放（跳过按钮在）、跳过确认（有的剧情直接弹确认）、选队伍、战斗已开始。
# ⚠️ 多写一个错页面 = 转场验收形同虚设，所以不往里凑。
#
# ⚠️ `体力弹窗` 必须在内（2026-10-31 20:20 实跑）：票 / 行动力不够时，点「观看」**不换页**，
# 而是在本页上盖一层「行动力不足」的购买弹窗（左：生命之叶 1 → 行动力 80，右：天空石）。
# 原来这里没有它 ⇒ 主循环判「点击没生效」⇒ 把状态机刚给出的 `stamina_material`
# （去点那颗树叶）整个丢掉 ⇒ 干等 45 秒报 `timeout_transition_start_activity_story`。
# 判据本身一直是好的：同一帧实测 弹窗 1.0000 / 生命之叶 1.0000 / 购买 0.9998。
_START_TARGET_PAGES = (
    "剧情播放",
    "跳过确认",
    "助手选择",
    "队伍准备",
    "战斗中",
    "体力弹窗",
)

# 主线里「可能直接回到观看故事页」的动作。它们的 `target_pages` 由主线写死成
# 「结算确认 / 通关提示 / 下一关入口」，而活动剧情的落点是**观看故事页** ——
# 不补这一个落点，主循环会判「转场没完成」并把刚认出来的动作整个丢掉，
# 一路干等到状态超时（与支线故事踩过的「完成故事弹窗」同一个机制）。
#
# 覆盖五个而不是一个：哪个动作最后一步，取决于这一关是纯剧情还是带战斗，
# 也取决于游戏版本把结算确认与通关提示合成几步 —— 全补上最省事也最安全。
#
# ⚠️ `skip` / `skip_confirm` 必须在内（2026-10-31 19:53 实跑）。**纯剧情那一段的最后一屏**
# 点完跳过确认，游戏不经过任何结算 / 通关提示，**直接回到观看故事页**；而主线这条白名单
# 只有「剧情播放 / 战斗中 / 关卡入口 / 剧情关卡入口 / 通关提示」⇒ 主循环判「转场没完成」
# ⇒ 把已经认出的 `start_activity_story` 丢掉 ⇒ 干等 45 秒报 `timeout_transition_skip_confirm`、
# 退出码 1。现场帧恰恰是**已经回到本页、列表已往前一格**（上一项补了绿勾）。
#
# ⚠️ `stamina_confirm` 也必须在内（2026-10-31 20:26 实跑）：买完行动力，游戏**回本页**
# 而不是进队伍页 ⇒ 主线那条「队伍准备 / 快速战斗 / 战斗中」一个都不成立 ⇒
# `timeout_transition_stamina_confirm`。现场证据：同一次运行里体力 17 → 98（真买到了）。
_RETURN_TO_SELECT_ACTIONS = (
    "clear",
    "results_confirm",
    "complete",
    "skip",
    "skip_confirm",
    "stamina_confirm",
)


@dataclass(frozen=True)
class ActivityStoryTemplates:
    """活动剧情模板：主线那一整套 + 本路线自己的三张。

    ⚠️ 主线模板**按对象复用**而不是重新加载一遍（同 `SideStoryTemplates`）：
    `StoryTemplates` 里带着快速战斗检测器与证据画像，重建一份等于重新预热一次，
    还可能悄悄分叉。
    """

    story: StoryTemplates
    # 左上角「观看故事」四字。白掩膜下形状最干净的一张：实测白像素占比 43%，
    # 其余全是背景高光 —— 换成别的活动背景也认得出来。
    watch_story_title: np.ndarray
    # 按钮左侧的票券徽章（马头 + 金色底座）。**不排他**，见模块头部。
    ticket_cost: np.ndarray
    # 「已看完」时的那颗标记。实机还没采到 ⇒ 允许缺席（缺席时靠按钮区指纹兜底）。
    ticket_free: Optional[np.ndarray]
    # 战斗关的「CLEAR 字标带」。**复用支线那一张**（见 `_CLEAR_TEMPLATE` 的说明），
    # 本路线自己的模板目录里没有这个文件。
    battle_clear: np.ndarray


def build_activity_story_templates(template_dir: Path) -> ActivityStoryTemplates:
    """构建活动剧情模板。``template_dir`` 是 ``templates/activity_story``。"""

    root = template_dir.parent
    free_path = template_dir / "ticket_free.png"
    sibling, name = _CLEAR_TEMPLATE
    return ActivityStoryTemplates(
        story=build_story_templates(root / "story"),
        watch_story_title=load_template(str(template_dir / "watch_story_title.png")),
        ticket_cost=load_template(str(template_dir / "ticket_cost.png")),
        # 可选：采到之前不加载，判据自动退化成按钮区指纹。
        ticket_free=load_template(str(free_path)) if free_path.is_file() else None,
        # ⚠️ 跨路线取图：战斗关 CLEAR 那一页与支线逐字同款，存两份迟早漂。
        battle_clear=load_template(str(root / sibling / name)),
    )


def _page_label(state: StoryState) -> str:
    """日志里的页面名。本路线把 `STAGE` 借来表示「观看故事页」。"""

    if state is StoryState.STAGE:
        return _SELECT_PAGE
    return state_label(state)


class ActivityStoryStateMachine(StoryStateMachine):
    """活动剧情：在主线状态机前面插一页「观看故事」，其余原样委托。"""

    # 主线的区域 / 阈值表 + 本路线自己的三条。类属性这份只为「类级别看一眼」，
    # 真正生效的是 ``__init__`` 里合并出来的实例属性（主线会按证据画像重建一份）。
    _REGIONS = {**StoryStateMachine._REGIONS, **_ACTIVITY_REGIONS}
    _THRESHOLDS = {**StoryStateMachine._THRESHOLDS, **_ACTIVITY_THRESHOLDS}
    _MATCH_MODES = _ACTIVITY_MATCH_MODES

    def __init__(
        self,
        templates: ActivityStoryTemplates,
        initial_state: StoryState = StoryState.STAGE,
    ) -> None:
        super().__init__(templates.story, initial_state=initial_state)
        self.activity = templates
        # 主线 `__init__` 会把这两张表换成实例属性（按证据画像重建）—— 类属性上
        # 合并进来的三条在实例上根本看不见，不在这里再合并一次就会 KeyError。
        self._REGIONS = {**self._REGIONS, **_ACTIVITY_REGIONS}
        self._THRESHOLDS = {**self._THRESHOLDS, **_ACTIVITY_THRESHOLDS}
        # 上一次「点按钮之前」的（列表区, 按钮区）快照。只用来回答一个问题：
        # 「点完之后回来，画面有没有往前走？」
        self._last_progress: Optional[tuple[np.ndarray, np.ndarray]] = None
        # True = 上一次决策发出的是「点按钮」，还没等到下一次回到本页。
        # ⚠️ 没有它就会每帧拿相邻帧比 —— 这个页面是静止的，第一秒就自己判收工。
        self._awaiting_return = False
        # True = 点完之后**确实看见过不是本页的画面**（剧情 / 战斗 / 准备战斗）。
        # ⚠️ 这是 2026-10-31 第一次实跑的教训：点「准备战斗」之后游戏要加载 2~10 秒，
        # 中间那几帧画面还是本页 ⇒ 拿它当「没进展」会立刻误判收工（实际只跑了一关）。
        # 只有离开过本页，回到本页时的比较才有意义。
        self._left_page = False
        # 连续多少次「点完回来、画面没往前走」。到 `_PROGRESS_MISS_LIMIT` 就收工。
        self._progress_misses = 0
        # 最近一次「点完回来」的变化像素数。只进日志，用来校准阈值。
        self._last_progress_delta = -1

    # ── 判据 ────────────────────────────────────────────────────────────────

    def _locate(self, screen: np.ndarray, name: str, threshold: float | None = None):
        """本路线三张模板走自己的表，其余原样交给主线。"""

        if name in _ACTIVITY_TEMPLATE_NAMES:
            template = getattr(self.activity, name, None)
            if template is None:
                # `ticket_free` 允许缺席（还没采到）。
                return None
            return find_template(
                screen,
                template,
                threshold or self._THRESHOLDS[name],
                region=self._REGIONS[name],
                reference_size=self._REFERENCE_SIZE,
                mode=self._MATCH_MODES.get(name, MATCH_MODE_RAW),
            )
        # ⚠️ 主线的 ``_locate`` 签名是 ``(screen, name)``，**没有** threshold 形参。
        # 多传一个会 TypeError，而那些帧正好是队伍 / 剧情 / 结算这些委托给主线的页面。
        return super()._locate(screen, name)

    # ── 战斗监督 ────────────────────────────────────────────────────────────

    def observe_battle(
        self, screen: np.ndarray, previous_screen: np.ndarray | None
    ) -> BattleObservation:
        """交给战斗监督的「这一屏我认得吗」—— 名单里**必须含战斗关 CLEAR**。

        ⚠️ 主线的 `result_visible` 名单是 `("reward", "clear", "results_confirm")`，
        其中 `clear` 是**剧情关** CLEAR。活动剧情里「准备战斗」打完后是**战斗关**
        CLEAR（橙菱形 + CLEAR 字标带），主线那五项判据**全 False** ⇒ 监督判成
        「未知画面」⇒ 干等 215 秒报 `battle_unrecognized`（2026-10-31 实测）。

        修法与狗粮 / 支线一致：把本路线自己的 `battle_clear` 并进 `result_visible`。
        两条**故意**的收紧（同支线）：`battle_visible` 为真时不补判；两项都假才跑匹配
        ⇒ 真实战斗画面上一帧额外判据都不跑。
        """

        observation = super().observe_battle(screen, previous_screen)
        if observation.result_visible or observation.battle_visible:
            return observation
        if self._locate(screen, "battle_clear") is None:
            return observation
        return replace(observation, result_visible=True)

    # ── 「有没有往前走」的判据 ───────────────────────────────────────────────

    def _region_crop(
        self, screen: np.ndarray, region: tuple[int, int, int, int]
    ) -> np.ndarray:
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = region
        return screen[
            round(y * scale_y) : round((y + height) * scale_y),
            round(x * scale_x) : round((x + width) * scale_x),
        ]

    def _progress_snapshot(
        self, screen: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        return (
            self._region_crop(screen, _LIST_REGION).copy(),
            self._region_crop(screen, _BUTTON_REGION).copy(),
        )

    def _progress_changed(self, screen: np.ndarray) -> tuple[bool, int]:
        """这一帧与「上次点击前」相比，**列表区或按钮区**变了多少个像素。

        取两者较大值：故事往前走时动的是列表（高亮项下移 + 补绿勾），
        而「观看 → 准备战斗」这类切换动的是按钮文案。

        返回 ``(是否算往前走, 变化像素数)``。像素数会进日志。
        """

        current = self._progress_snapshot(screen)
        previous = self._last_progress
        if previous is None:
            return True, -1
        pixels = 0
        for now, before in zip(current, previous, strict=True):
            if now.shape != before.shape:
                return True, -1
            difference = np.abs(
                now.astype(np.int16) - before.astype(np.int16)
            ).max(axis=2)
            pixels = max(pixels, int((difference > _BUTTON_PIXEL_DELTA).sum()))
        return pixels >= _PROGRESS_CHANGED_PIXELS, pixels

    # ── 决策 ────────────────────────────────────────────────────────────────

    def next_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        # ⚠️ 体力弹窗**必须先判**：主线的 `_handle_stamina` 是它整个 `next_action`
        # 的第一行，而本类在它前面插了自己的决策 —— 不显式提上来，战斗关体力不足时
        # 会先去点「准备战斗」而不是补叶子（用户 2026-10-31 明确要求「用叶子补」）。
        stamina_action = self._handle_stamina(screen)
        if stamina_action is not None:
            # 这一下被弹窗吃掉了：**没有真的开始看故事**。
            # 所以「点完等回本页」这笔账要撤掉 —— 否则买完行动力回到本页时，
            # 故事列表当然没动，会被记成一次「点完没往前走」；连着补两次
            # （一颗叶子不够时）就凑满上限、误判「本期已看完」收工。
            self._awaiting_return = False
            self._left_page = False
            # 「购买」这一步买完是**回到观看故事页**（2026-10-31 20:26 实跑），
            # 不是主线以为的队伍页 ⇒ 落点得按本路线补，否则又是干等 45 秒超时。
            return self._with_return_target(stamina_action)

        handled, action = self._activity_decision(screen)
        if handled:
            return action
        try:
            action = super().next_action(screen)
        except UnrecognizedScreen as error:
            raise UnrecognizedScreen(
                f"活动剧情画面[{_page_label(self.state)}]未识别"
            ) from error
        return self._with_return_target(action)

    def _with_return_target(
        self, action: Optional[StoryAction]
    ) -> Optional[StoryAction]:
        """把「可能回观看故事页」的主线动作补上这个落点。

        只补 `target_pages`，不改点击点、不改来源页 —— 转场验收仍然照常走白名单。
        """

        if action is None or action.name not in _RETURN_TO_SELECT_ACTIONS:
            return action
        if _SELECT_PAGE in action.target_pages:
            return action
        return replace(action, target_pages=action.target_pages + (_SELECT_PAGE,))

    def _activity_decision(
        self, screen: np.ndarray
    ) -> tuple[bool, Optional[StoryAction]]:
        """本页决策。返回 ``(是否归我管, 动作)``。

        ⚠️ 「认识但这一帧没有动作」必须返回 ``(True, None)``（主循环继续轮询），
        不能推给主线的 ``UnrecognizedScreen`` —— 那会让日志刷「结论待确认」，
        唤醒开关一开还会去点屏幕中间。
        """

        # ⓪ 战斗关的通关横幅。它**不在**观看故事页上（左上角标题已经消失），
        #    所以必须判在标题之前 —— 否则会掉进「委托主线」那一支，
        #    而主线没有这一页的判据，只能抛 UnrecognizedScreen。
        clear = self._locate(screen, "battle_clear")
        if clear is not None:
            return True, self._action(
                "dismiss_battle_clear",
                clear.center,
                source_page="通关结算",
                target_pages=_CLEAR_TARGET_PAGES,
                reason="战斗关的通关横幅（CLEAR 字标带）已识别",
                target_states=(StoryState.WAIT_RESULTS, StoryState.WAIT_COMPLETE),
            )

        title = self._locate(screen, "watch_story_title")
        if title is None:
            # 已经点过按钮、而这一帧不是本页 ⇒ 记一笔「确实离开过」。
            # 之后回到本页时的「有没有往前走」才允许下结论（见 `_left_page`）。
            if self._awaiting_return:
                self._left_page = True
            # 标题没认出来，但**票券徽章在** ⇒ 大概率是本页的淡入 / 压缩帧
            # （活动背景每期不同，白掩膜偶尔会掉到阈下）。这时只等，不把页面
            # 交给主线 —— 主线在这一屏会去认「准备战斗 / 观看故事」那些按钮，
            # 位置正好压在右下角这颗按钮上，点歪了就是一次无谓的转场。
            if self._locate(screen, "ticket_cost") is not None:
                return True, None
            return False, None

        # ① 「已看完」的主判据：按钮上的票券标记变成了不耗票的那一态。
        if self._locate(screen, "ticket_free") is not None:
            raise ActivityStoryCleared(
                "本期活动剧情已看完：右下角按钮已不再消耗票"
            )

        # ② 兜底：点完、**离开过本页**、再回来时画面没有往前走 ⇒ 这一下没有解锁
        #     新内容。连续 `_PROGRESS_MISS_LIMIT` 次才收工。
        #
        #     ⚠️ `_left_page` 这一条是必须的：点「准备战斗」之后游戏要加载几秒，
        #     中间那几帧还是本页，拿它当「没进展」会立刻误判收工（2026-10-31 实跑）。
        if self._awaiting_return and self._left_page:
            changed, pixels = self._progress_changed(screen)
            self._awaiting_return = False
            self._left_page = False
            self._last_progress_delta = pixels
            if changed:
                self._progress_misses = 0
            else:
                self._progress_misses += 1
                if self._progress_misses >= _PROGRESS_MISS_LIMIT:
                    raise ActivityStoryCleared(
                        "本期活动剧情已看完：连续"
                        f"{self._progress_misses} 次点完后画面没有往前走"
                        f"（变化像素={pixels}，阈值={_PROGRESS_CHANGED_PIXELS}）"
                    )

        # ③ 还能看：点它。
        self._last_progress = self._progress_snapshot(screen)
        self._awaiting_return = True
        self._left_page = False
        if self.state is not StoryState.STAGE:
            # 从剧情 / 战斗 / 结算回来 ⇒ 刚才那一段看完了。用状态做闸门，
            # 否则同一页停留几帧就会被重复计数（支线场景页同一手法）。
            self.completed_cycles += 1
        self.state = StoryState.STAGE
        return True, self._action(
            "start_activity_story",
            self._scaled_point(screen, _BUTTON_POINT),
            source_page=_SELECT_PAGE,
            target_pages=_START_TARGET_PAGES,
            reason="观看故事页的「观看 / 战斗」按钮已识别",
            target_states=(
                StoryState.WAIT_SKIP_CONFIRM,
                StoryState.ACTIVE,
                StoryState.TEAM,
                StoryState.WAIT_BATTLE,
            ),
        )

    def preview(self, screen: np.ndarray):
        """观察一帧但不留下痕迹（含本路线自己的四份账本）。"""

        progress = self._last_progress
        awaiting = self._awaiting_return
        left = self._left_page
        misses = self._progress_misses
        try:
            return super().preview(screen)
        finally:
            self._last_progress = progress
            self._awaiting_return = awaiting
            self._left_page = left
            self._progress_misses = misses


class ActivityStoryRunner(StoryRunner):
    """活动剧情 Runner：主循环协议与主线完全相同，只换名字与页面名。"""

    _MODE_LABEL = "活动剧情"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        StoryState.STAGE: 45,          # 观看故事页：等切换 / 列表滚动
        StoryState.TEAM: 45,
        StoryState.WAIT_SKIP_CONFIRM: 45,
        StoryState.WAIT_BATTLE: 60,
        StoryState.ACTIVE: 120,
        StoryState.WAIT_RESULTS: 45,
        StoryState.WAIT_COMPLETE: 45,
        StoryState.WAIT_NEXT_STAGE: 45,
    }

    def __init__(
        self,
        machine: ActivityStoryStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
            battle_supervisor=battle_supervisor,
        )
        if battle_supervisor is None:
            # 只换名字：兵线 / 自理逻辑原样用主线的。复用 `self.recovery_gate`，
            # 不另造一个 Gate（两个 gate 会让「自救预算」按两本账各记一遍）。
            self.battle_supervisor = BattleSupervisor(
                runtime,
                self.recovery_gate,
                BattleConfig(mode="activity_story", mode_label="活动剧情"),
                now=self.now,
                sleep=sleep,
            )

    def _state_label(self, state: StoryState) -> str:
        return _page_label(state)

    def run(self, max_cycles: int | None = None) -> int:
        """跑完（本期看完）时留一帧 —— 那是 `ticket_free` 唯一的样本来源。

        ⚠️ 不用 `try/finally` 包住整轮：只在**正常收工**这一条路上存图。
        异常退出时页面可能是任何东西，存下来只会污染模板候选。
        """

        try:
            return super().run(max_cycles=max_cycles)
        except ActivityStoryCleared:
            if not self.runtime.dry_run:
                # 「已看完」那一帧上按钮不再消耗票，而这颗标记**还没采到模板**。
                # 下次跑完本期时它会自己把样本留下来，直接裁 `ticket_free.png`。
                self.runtime.save_diagnostic("activity_story_finished")
            raise

    def _log_cycle_completed(self) -> None:
        delta = getattr(self.machine, "_last_progress_delta", -1)
        self.runtime.log(
            f"模式=活动剧情 状态=看完一段 累计="
            f"{self.machine.completed_cycles}段 画面变化={delta}"
        )

    def _log_state_timeout(self, state: StoryState, elapsed: float, diagnostic) -> None:
        self.runtime.log(
            f"模式=活动剧情 页面={_page_label(state)} "
            f"状态=超时无进展 已耗时={elapsed:.1f}秒 诊断={diagnostic}"
        )

    def _log_settled_timeout(self, state: StoryState, diagnostic) -> None:
        self.runtime.log(
            f"模式=活动剧情 页面={_page_label(state)} "
            f"状态=等待超时无进展 诊断={diagnostic}"
        )


def build_activity_story_machine(
    template_dir: Path,
    state: str = StoryState.STAGE.value,
) -> ActivityStoryStateMachine:
    """装配入口：``template_dir`` 是 ``templates/activity_story``。"""

    return ActivityStoryStateMachine(
        build_activity_story_templates(template_dir),
        initial_state=StoryState(state),
    )


# 供 ``modes.ModeSpec`` 与测试引用，避免两边各写一遍取值。
MODE_LABEL = "活动剧情"
DEFAULT_STATE = StoryState.STAGE.value
