"""月光剧场（``moonlight_theater``）—— 把本周免费的观览奖励打完领完。

业务流程、页面判据的实测依据与安全约束见 ``evidence/moonlight_theater.py``
的模块 docstring（那里是唯一权威）。本模块只做**决策**：每帧看画面，给出唯一动作。

## 一句话模型

这是一条「**横向扫描 + 逐幕执行**」的路线，不是「跑 N 遍」：

```
支线故事页 ──[入口卡片有绿 F?]──否──→ 收工
     │是
     ▼
剧场选择页 ──[当前剧场有 Free?]──否──→ 点右边那张海报（右边没了就收工）
     │是                                    ▲
     ▼                                      │
  入场 → 分集页 → 进行观览 → 观览指南 → 剧情页（狂点字幕）⇄ 战斗
                                                    │
                                              CLEAR / 回到分集页
                                                    ▼
                                          领奖 → 关弹窗 → 左上返回 ──┘
```

## 三条与其它路线不同的地方

1. **剧情页没有 AUTO，必须自己点字幕。** 全项目只有本路线这么干（主线靠 auto 跳过）。
   所以剧情页的正向锚点是底部那枚 ▼（``story_continue``）——**没有 ▼ 就不点**。
   ⚠️ 「连着点同一个动作」撞主循环那本同名动作账（45 秒一次、4 次判死），
   解法见 ``_at_story`` / ``_stable_action_signature`` / ``_action_retry_seconds`` 三处注释。
2. **战斗是剧情自动触发的，没有开战按钮。** 走 ``_SETTLED_BATTLE_STATE``
   （停在该状态且本帧无动作 ⇒ 直接交战斗监督），而不是「点开战按钮再移交」。
3. **「进行观览」会通向花钱 —— 而且是两种钱。** 必须分清，两者处理相反：
   * **购买剧场门票**（500,000 **金币**）：用户明令不许买 ⇒ 只点取消，并且
     「取消之后这个剧场直接放弃」（``must_leave`` + ``_skip_posters``）——
     否则会「取消 → 又点观览 → 又弹购买」，或者在列表上「又入场」重来一遍。
   * **使用剧场门票**（消耗**已持有的券**）：用户 2026-10-17 拍板「花掉」⇒ 点确认继续。
   两个弹窗版式几乎一样 ⇒ **身份只能靠标题判，按钮只当点击锚点**（见 ``_at_use_ticket``）。
   另外，只有**确认当前剧场带 Free 角标**才允许点入场/观览，这是第一道闸门。
4. **CLEAR 过场必须点，不会自己消失。** 2026-10-17 真机在 CLEAR 上干等 60 秒
   报 ``timeout_clear``（退出码 1）。详见 ``_at_clear``：本路线的 CLEAR 上**没有**
   支线故事那对「»»」继续箭头，但这不影响「点一下就走」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import blake2b
from pathlib import Path
from time import monotonic, sleep as default_sleep
from typing import Any, Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.matcher import Match, load_template, locate_with_fallback
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ResourceExhausted, Runtime
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.moonlight_theater import (
    REFERENCE_SIZE,
    BATTLE_ANCHORS,
    BATTLE_ANCHOR_VOTES,
    MAX_SWEEP_LEFT_STEPS,
    REWARD_BUTTON_POINT,
    REWARD_DOT_MIN_ORANGE_PIXELS,
    REWARD_DOT_PIXEL_REGION,
    STORY_ARROW_EXCLUDE,
    STORY_CLICK_POINT,
    STORY_DARK_FRAME_MIN_DARK_RATIO,
    STORY_DARK_FRAME_MIN_SUBTITLE_WHITE,
    STORY_DARK_FRAME_SUBTITLE_REGION,
    THEATER_NEXT_POINT,
    THEATER_POSTER_REGION,
    THEATER_PREV_POINT,
    build_moonlight_evidence,
)
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.template_paths import is_pc, is_template_root
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class MoonlightCleared(ResourceExhausted):
    """本周能看的都看完了：免费额度扫完，手上有的剧场门票也花完。

    与支线故事的 ``SideStoryCleared``、月塔的 ``FloorsConquered`` 同族
    （继承 ``ResourceExhausted``，退出码 2「跑完了但没得跑了」）：对用户来说不是
    失败，是「本周已经清空」。走这条出口基类会顺手把游戏带回首页。
    """

    stop_label = "本周免费与门票都已处理完"


class MoonlightState(Enum):
    ENTRY = "entry"          # 支线故事页（月光剧场入口卡片）
    LIST = "list"            # 剧场选择页（横向海报）
    EPISODE = "episode"      # 分集页
    GUIDE = "guide"          # 观览指南弹窗
    STORY = "story"          # 剧情页（无 auto，点字幕）
    BATTLE = "battle"        # 战斗中（自动，交监督）
    CLEAR = "clear"          # CLEAR 过场
    REWARD = "reward"        # 「获得奖励」弹窗
    PURCHASE = "purchase"    # 购买门票弹窗（花金币 ⇒ 只点取消）
    USE_TICKET = "use_ticket"  # 使用剧场门票弹窗（花已持有券 ⇒ 确认，用户拍板）
    FINISHED = "finished"    # 本轮已结束


STATE_LABELS = {
    MoonlightState.ENTRY: "支线故事页",
    MoonlightState.LIST: "剧场选择页",
    MoonlightState.EPISODE: "分集页",
    MoonlightState.GUIDE: "观览指南弹窗",
    MoonlightState.STORY: "剧情页",
    MoonlightState.BATTLE: "战斗中",
    MoonlightState.CLEAR: "CLEAR 过场",
    MoonlightState.REWARD: "获得奖励弹窗",
    MoonlightState.PURCHASE: "购买门票弹窗",
    MoonlightState.USE_TICKET: "使用剧场门票弹窗",
    MoonlightState.FINISHED: "本轮已结束",
}

# evidence 页面键 -> 状态。判定顺序即元组顺序，硬约束见 evidence 模块的注释。
_PAGE_STATES = (
    ("moonlight.purchase", MoonlightState.PURCHASE),
    ("moonlight.use_ticket", MoonlightState.USE_TICKET),
    ("moonlight.guide", MoonlightState.GUIDE),
    ("moonlight.reward", MoonlightState.REWARD),
    ("moonlight.story", MoonlightState.STORY),
    ("moonlight.clear", MoonlightState.CLEAR),
    ("moonlight.episode", MoonlightState.EPISODE),
    ("moonlight.list", MoonlightState.LIST),
    ("moonlight.entry", MoonlightState.ENTRY),
)

#: 刚看完一幕、回到分集页之后，**等多少秒**才允许下「没有奖励可领」的结论。
#:
#: 理由（2026-10-17 用户拍板「漏领就是没闭环，不许当可接受风险」）：
#: 橙点是脉动的、奖励也可能晚一拍才到账，页面刚回来的第一帧常常「还没有橙点」；
#: 那时若直接撤，这一集的观览奖励就**永远漏了**（而它正是本路线的业务目标）。
#: 等满还是没有，才是「这个剧场的奖励之前已经领过」—— 那时候撤才是对的。
#:
#: ⚠️ 用**秒**不用帧：主循环的轮询间隔可以被调（``poll_seconds``，测试里还会用
#: 10 秒/帧的假时钟），按帧数等会在那些场合变成「等 160 秒」直接撞状态超时。
#: ⚠️ 这个值是「等多久」，不是「点几次」：期间**一个动作都不发**（返回 None），
#: 只让主循环下一帧再看一眼 —— 所以它不会撞「同名动作 4 次判死」那本账。
REWARD_GRACE_SECONDS = 8.0


@dataclass(frozen=True)
class MoonlightAction(RouteAction):
    """一个动作，**必须声明出处与出口验收**（本路线打开了转场契约开关）。"""


@dataclass(frozen=True)
class MoonlightTemplates:
    entry_card: np.ndarray
    entry_free: np.ndarray
    free_badge: np.ndarray
    enter_button: np.ndarray
    back_button: np.ndarray
    watch_button: np.ndarray
    reward_dot: np.ndarray
    guide_title: np.ndarray
    guide_confirm: np.ndarray
    purchase_title: np.ndarray
    purchase_cancel: np.ndarray
    use_ticket_title: np.ndarray
    ticket_confirm: np.ndarray
    ticket_cancel: np.ndarray
    story_continue: np.ndarray
    # 剧情页右上角那排图标里的「记录」——▼ 会闪、会消失，这一颗不会。
    story_hud: np.ndarray
    # 战斗画面自有的三枚（复用的 ``battle_scene_visible`` 在本路线认不出，见证据档案）
    battle_hp_bar: np.ndarray
    battle_avatar_axis: np.ndarray
    battle_round_buttons: np.ndarray
    battle_clear: np.ndarray
    reward_popup_close: np.ndarray
    evidence: object = None
    # PC 专属判据只在这项为真时启用；模拟器走改动前的判定路径。
    pc: bool = False


def build_moonlight_templates(template_dir: Path) -> MoonlightTemplates:
    evidence = build_moonlight_evidence(template_dir)

    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / evidence.atom(name).template_path))

    return MoonlightTemplates(
        **{name: load(name) for name in (
            "entry_card", "entry_free", "free_badge", "enter_button", "back_button",
            "watch_button", "reward_dot", "guide_title", "guide_confirm",
            "purchase_title", "purchase_cancel",
            "use_ticket_title", "ticket_confirm", "ticket_cancel",
            "story_continue", "story_hud",
            "battle_hp_bar", "battle_avatar_axis", "battle_round_buttons",
            "battle_clear", "reward_popup_close",
        )},
        evidence=evidence,
        pc=is_pc(template_dir),
    )


def state_label(state: MoonlightState) -> str:
    return STATE_LABELS.get(state, state.value)


class MoonlightStateMachine:
    """月光剧场一轮的纯视觉决策。

    **业务进度只有三样**：``completed_cycles``（完成了几个剧场）、
    ``finish_reason``（收工理由）、``watched_current``（这一个剧场是否已经看过一幕）。

    ``watched_current`` 是这条路线最要紧的一条记账，**在「看到剧情页」那一刻置位**
    （不是等领奖）。理由是实测过的：分集页在「刚入场」和「看完了」两种情况下
    **长得一模一样**（都是「观览按钮亮 + 没有橙点」），只靠画面分不开。
    只靠橙点置位的话，橙点一没认出来就判「没看过」⇒ 再点一次「进行观览」⇒
    白看一遍、把免费额度烧光（2026-10-17 真机就是这样连看两遍，最后撞上
    「使用剧场门票」卡死）。而进去过剧情 ＝ 这一集的额度**已经消耗**，不会退，
    所以「进剧情即记账」是能被画面证明的强证据，「橙点亮了」只是它的下游结果。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    # PC 专属的搜索区覆盖：**只放宽、不挪语义**。
    #
    # ``back_button``（左上返回箭头）在 PC 上整体往右下挪：模拟器箭头 bbox
    # x 35 / y 75 / 43×52，PC 是 x 57 / y 88 / 42×50（两张 PC 帧逐像素一致）。
    # 而证据画像里的 region 是 ``(0, 20, 180, 110)``（y 20~130）—— **切掉箭头下沿 8px**，
    # 白掩膜分数从 0.92 掉到 **0.2035**（2026-11-05 00:35 真机 `timeout_episode`）。
    #
    # 这不是「认不出控件」，是「没把控件给全」：同一枚模板在放宽后的区域里
    # 拿 0.8867（共享图）/ 1.0000（PC 覆盖图）。
    # ⚠️ 只对 PC 生效：模拟器侧那份 region 是按模拟器布局量出来的，2026-10-24 的
    # 事故（0.6046）是另一回事，已由「只截箭头本体 + 白掩膜」修好，别在这里连带改动。
    _PC_REGION_OVERRIDES: dict[str, tuple[int, int, int, int]] = {
        "back_button": (0, 40, 240, 160),
    }

    # 存样用：由 ``MoonlightRunner`` 在构造时注入。单元测试直接构造状态机时是
    # ``None`` ⇒ 存样安静跳过（存样只是附带动作，判据不许靠它）。
    runtime: Any = None

    def __init__(
        self,
        templates: MoonlightTemplates | Path,
        *,
        initial_state: MoonlightState = MoonlightState.ENTRY,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        # 「等够 8 秒没有橙点」用的时钟。默认单调时钟；主循环会把它换成 ``runtime.now``
        # （测试里那是假时钟）—— 这样「等了多久」跟主循环判超时用的是**同一个时间轴**。
        self._clock: Callable[[], float] = clock or monotonic
        self.templates = (
            build_moonlight_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        self.finish_reason = ""
        # 当前剧场是否已经看过一幕（决定分集页上「观览」还是「返回」）。
        # ⚠️ 只在「看到剧情页」时置位，不在「点了领奖」时置位 —— 理由见类 docstring。
        self.watched_current = False
        # 「这个剧场必须撤」——购买弹窗取消之后置位：那一刻亲眼看到「这一幕要花门票」，
        # 于是**绝不再点「进行观览」**，直接退回剧场选择页。
        self.must_leave = False
        # 这个剧场这一幕的奖励**已经领过了**（领奖弹窗关掉之后置位）。
        # 作用是让分集页别再为「橙点怎么还没亮」等下去 —— 领完就该直接撤。
        self.claimed_current = False
        # 「刚看完、还没看见橙点」是从什么时候开始等的（见 ``REWARD_GRACE_SECONDS``）。
        self._reward_wait_since: Optional[float] = None
        # 已经处理过的剧场（按海报指纹）。进去看过一幕、或者被购买弹窗劝退过，
        # 都记在这里 —— 光靠「Free 角标还在不在」挡不住重复入场：
        # 角标没消失时会出现「取消 → 退回列表 → 又入场 → 又弹购买」的死循环。
        self._skip_posters: set[str] = set()
        # 入场那一刻的海报指纹（离开时拿它登记到 ``_skip_posters``）。
        self._current_poster = ""
        # 上一帧「中间那张海报」的像素（用来判「点了右边之后选中项换了没有」）。
        self._poster_signature: Optional[np.ndarray] = None
        self._confirmed_page = ""
        # 本场战斗是否已经存过样张（每场只存一张，见 ``_snapshot_battle``）。
        self._battle_sampled = False
        # 剧场门票是不是已经确认用光。
        # 置位时机：看到「购买剧场门票」弹窗（那一刻游戏明确说「你没券了」），
        # 或者「使用剧场门票」弹窗上确认按钮已经点不动了。
        # 作用**只有一个**：没有 Free 的剧场不再进去探券 —— 否则每个剧场都会弹
        # 一次 500,000 金币的购买框。它**绝不拦有 Free 的剧场**：券花光了，剩下的
        # 免费额度照样要打完（2026-11-06 用户明确要求）。
        self._tickets_exhausted = False
        # 「往左归位」做了没有。从入口进列表页时置 False（见 ``_at_entry``），
        # 归位到最左端后置 True，此后一张列表页只在「往右扫」这一条路上决策。
        self._sweep_left_done = True
        self._sweep_left_steps = 0
        # 本帧的实测（只为日志说清楚凭什么）。
        self.has_free = False
        self.free_reason = ""

    # ---- 视觉判据 ----

    def clock(self) -> float:
        """当前时间（秒）。见 ``__init__`` 里 ``clock`` 那段。"""
        return self._clock()

    def set_clock(self, clock: Callable[[], float]) -> None:
        """由主循环注入自己的时间源（``runtime.now``）。"""
        self._clock = clock

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        # PC 的搜索区覆盖（见 ``_PC_REGION_OVERRIDES``）：证据画像里那套 region 是
        # 按模拟器布局量的，PC 上同一枚控件会整体往右下挪十几像素 —— 区域不跟着挪，
        # 模板就被**切掉一截**，分数从 0.92 掉到 0.20（不是「认不出控件」，是「没给全」）。
        region = atom.region
        if self.templates.pc:
            region = self._PC_REGION_OVERRIDES.get(name, region)
        # 走 ``locate_with_fallback``（与导航层、视觉诊断**同一把尺子**）：原样先比，
        # 不过阈才按 ``SMOOTH_FALLBACK_ANCHORS`` / ``SCALE_FALLBACK_ANCHORS`` 补一次。
        return locate_with_fallback(
            name,
            screen,
            getattr(self.templates, name),
            atom.threshold,
            region=region,
            reference_size=atom.reference_size,
            mode=atom.match_mode,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        """拿不到就失败关闭：**绝不猜坐标**。"""
        match = self._locate(screen, name)
        if match is None:
            raise UnrecognizedScreen(
                f"月光剧场画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[MoonlightState]:
        """按 evidence 页面组合认出当前是哪一页；认不出返回 None。

        「战斗中」单独判：它不在 evidence 的页面表里，因为没有稳定的静态锚点。
        判据是「**战斗 HUD 成立** 且 剧本箭头不在」（剧情页必然有 ▼）——
        那个「与」是必要的：亮色立绘帧能骗过 ``battle_scene_visible`` 单独一项。

        ⚠️ 「战斗 HUD 成立」**不能只靠** ``battle_scene_visible``：本路线实测
        左侧行动列是彩色圆头像（白占比只有 0.037），它一旦认不出 AUTO 就整场
        战斗都不算 BATTLE（2026-10-17 两次实跑日志里一个 ``阶段=战斗`` 都没有）。
        所以再加**本路线自有的三枚 HUD 锚点投票**（≥2 命中），数据见证据档案。
        """
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        # 剧情页有两个锚点：▼（``story_continue``）和右上角那排图标里的「记录」
        # （``story_hud``）。**▼ 会消失** —— 字幕逐字打出时没有、黑屏淡入时没有、
        # 它自己还在闪 ⇒ 只认 ▼ 会周期性掉线（2026-11-06 23:57 真机就是字幕完整
        # 显示、▼ 正好闪没，判成 None、180 秒绝对超时）。hud 那颗全程都在。
        if flags["story_continue"] or flags["story_hud"]:
            return MoonlightState.STORY
        # 剧情页的**黑屏 / 淡入帧**：字幕正在逐字打出，画面里连 ▼ 都还没有。
        # 2026-11-06 23:36 真机：花券确认后落的就是这一帧（整屏黑 + 一句字幕）
        # ⇒ page 判成 None ⇒ `accept-ticket` 的转场 60 秒不成立 ⇒ 整条路线 ✗。
        if self._looks_like_story_dark_frame(screen):
            return MoonlightState.STORY
        if battle_scene_visible(screen) or self._battle_anchor_votes(screen) >= BATTLE_ANCHOR_VOTES:
            return MoonlightState.BATTLE
        return None

    def _looks_like_story_dark_frame(self, screen: np.ndarray) -> bool:
        """剧情页的黑屏帧：整屏够暗 **且** 底部字幕条里有白字。

        两个量缺一不可：只看「暗」会把观览指南 / 门票弹窗（94~95%）一起收进来；
        只看「底部有白字」会把分集页（7.1%）收进来。实测表见
        ``STORY_DARK_FRAME_MIN_DARK_RATIO`` 上面那段。
        """
        gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)
        if float(np.mean(gray < 40)) < STORY_DARK_FRAME_MIN_DARK_RATIO:
            return False
        x, y, width, height = STORY_DARK_FRAME_SUBTITLE_REGION
        band = gray[y : y + height, x : x + width]
        if band.size == 0:
            return False
        return float(np.mean(band > 200)) >= STORY_DARK_FRAME_MIN_SUBTITLE_WHITE

    def _battle_anchor_votes(self, screen: np.ndarray) -> int:
        """本路线自有的战斗 HUD 锚点命中数（3 取 2 即为战斗）。"""
        return sum(
            1 for name in BATTLE_ANCHORS if self._locate(screen, name) is not None
        )

    def _has_reward_dot(self, screen: np.ndarray) -> bool:
        """分集页上「可领观览奖励」的判据：**模板或颜色，命中一个就算**。

        ## 为什么要加颜色兜底

        ``reward_dot.png`` 是 34×34 的小图标，而可领标记**是脉动的**：尺寸、亮度
        每帧都在变。模板比对在「可领」帧上 1.0000、脉动到最小/最淡时就会掉到 0.80
        阈值下 ⇒ 实机表现为「剧情看完了，却没看见橙点」⇒ **奖励漏领**
        （用户 2026-10-17 明确：漏领就是没闭环，不能当成「可接受风险」）。

        橙点的是**固定色相**的，缩放/明暗都不影响它的橙色像素数。实测这个小框里
        橙点数：可领帧 **262**、其余 13 帧（含已领帧）**全 0**。
        """
        if self._locate(screen, "reward_dot") is not None:
            return True
        return self._orange_pixels(screen) >= REWARD_DOT_MIN_ORANGE_PIXELS

    def _orange_pixels(self, screen: np.ndarray) -> int:
        roi = self._crop(screen, REWARD_DOT_PIXEL_REGION)
        if roi.size == 0:
            return 0
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
        mask = (
            (hsv[:, :, 0] >= 5)
            & (hsv[:, :, 0] <= 30)
            & (hsv[:, :, 1] > 120)
            & (hsv[:, :, 2] > 120)
        )
        return int(np.count_nonzero(mask))

    def _probe_free(self, screen: np.ndarray) -> bool:
        """当前剧场左上角有没有绿色 Free 全称角标。"""
        match = self._locate(screen, "free_badge")
        self.has_free = match is not None
        self.free_reason = (
            f"Free 角标 {match.score:.4f}" if match else "无 Free 角标"
        )
        return self.has_free

    def _entry_free(self, screen: np.ndarray) -> bool:
        match = self._locate(screen, "entry_free")
        self.has_free = match is not None
        self.free_reason = (
            f"入口 F 角标 {match.score:.4f}" if match else "入口无 F 角标"
        )
        return self.has_free

    # ---- 动作构造 ----

    def _scaled_box(
        self, screen: np.ndarray, box: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        """把基准画布上的矩形换算到当前画面（模拟器与 PC 兼容画布都是 1982x1132）。"""
        width, height = screen.shape[1], screen.shape[0]
        scale_x = width / self._REFERENCE_SIZE[0]
        scale_y = height / self._REFERENCE_SIZE[1]
        x, y, w, h = box
        return (
            round(x * scale_x),
            round(y * scale_y),
            round(w * scale_x),
            round(h * scale_y),
        )

    def _crop(self, screen: np.ndarray, box) -> np.ndarray:
        x, y, w, h = self._scaled_box(screen, box)
        return screen[y : y + h, x : x + w]

    def _story_fingerprint(self, screen: np.ndarray) -> str:
        """剧情页「这一下有没有推进」的画面指纹（挖掉会闪的 ▼，见证据档案）。"""
        height, width = screen.shape[:2]
        scale_x = width / self._REFERENCE_SIZE[0]
        scale_y = height / self._REFERENCE_SIZE[1]
        x, y, w, h = STORY_ARROW_EXCLUDE
        x0, x1 = round(x * scale_x), round((x + w) * scale_x)
        y0, y1 = round(y * scale_y), round((y + h) * scale_y)
        digest = blake2b(digest_size=3)
        digest.update(screen[:y0].tobytes())
        digest.update(screen[y0:y1, :x0].tobytes())
        digest.update(screen[y0:y1, x1:].tobytes())
        digest.update(screen[y1:].tobytes())
        return digest.hexdigest()

    def _poster_fingerprint(self, screen: np.ndarray) -> str:
        """剧场选择页「现在是哪一张海报」的画面指纹。"""
        digest = blake2b(digest_size=3)
        digest.update(self._crop(screen, THEATER_POSTER_REGION).tobytes())
        return digest.hexdigest()

    def _snapshot_theater(self, screen: np.ndarray, kind: str, key: str) -> None:
        """遇到没见过的剧场就存一张样张（同一剧场同一页只存一次）。

        **为什么要存**：这条路线有 7 个剧场，每个剧场的海报和分集页背景都不一样，
        而夹具只覆盖了 2 个 —— 2026-10-24 的两次事故（▼ 半透明、返回键撞亮底图）
        **都是「第一次撞上某个剧场」**。没有样本就无法验证判据改动，只能靠实跑撞。
        每次换剧场都存一张，跑几轮就能把 7 个剧场补齐。

        ⚠️ 存样是**附带动作**：没配诊断目录、或写盘失败，都只记一条日志，
        **绝不影响主线**（判据不许因为「记录不下来」而停）。
        ⚠️ 去重用「文件已存在就跳过」而不是内存集合：跨运行也不会重复存，而且
        ``preview()`` 探路时最多多写一张，不必为回滚再加一份状态。
        ⚠️ 这里跑在**状态机**上，而状态机是单元测试直接构造的（没有 ``runtime``）
        ⇒ 一律走 ``getattr`` 兜底，取不到就安静返回。
        """
        runtime = getattr(self, "runtime", None)
        directory = getattr(runtime, "diagnostic_dir", None)
        if runtime is None or directory is None or not key:
            return
        path = directory / "theater_samples" / f"{kind}_{key}.png"
        if path.exists():
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), cv2.cvtColor(screen, cv2.COLOR_RGB2BGR))
        except (OSError, cv2.error) as error:
            runtime.log(f"模式=月光剧场 存样失败={kind} 原因={error}")
            return
        runtime.log(f"模式=月光剧场 存样={kind} 剧场={key} 路径={path}")

    def _snapshot_battle(self, screen: np.ndarray) -> None:
        """每场战斗存一张样张（同一场只存一张）。

        **为什么要存**：战斗锚点里有两枚**含着会变的内容** ——
        ``battle_hp_bar`` 模板上是 ``12705/12705`` 的血量数字，``battle_avatar_axis``
        是具体角色的圆形头像。换队伍 / 换敌人就可能只剩一票（< ``BATTLE_ANCHOR_VOTES``
        = 2）⇒ 整场战斗认不出 ⇒ 主循环一个动作都不发 ⇒ 磨到 180 秒绝对超时。
        要验证它们到底靠不靠得住，只能拿**不同血量、不同队伍**的真实战斗帧来比。
        """
        if self._battle_sampled:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._snapshot_theater(
            screen, "battle", f"{stamp}_cycle{self.completed_cycles + 1}"
        )
        self._battle_sampled = True

    def _confirm_page(self, page: str) -> None:
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        *,
        point: tuple[int, int],
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
    ) -> MoonlightAction:
        return MoonlightAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    def _finish(self, reason: str) -> None:
        self.state = MoonlightState.FINISHED
        self.finish_reason = reason
        raise MoonlightCleared(reason)

    # ---- 各页决策 ----

    def _at_entry(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        """入口卡片：**有 F 没 F 都进去**（2026-11-06 用户拍板改的口径）。

        原来这里是「没有绿 F 就收工」，理由是这条路线只打免费。现在多了一条
        「免费打完了用门票接着打」，而门票够不够只有进了剧场、点到「进行观览」
        才知道（分集页那枚票数含义未实证，不能当判据）。所以「入口没有 F」只说明
        **免费额度没了**，不再等于「没得打」。

        仍然读一次 F 角标：只写日志，一眼看出这一趟是免费优先还是纯花券，
        读不到也不拦。
        """
        self._entry_free(screen)
        # 进了剧场选择页要先把选中项推到最左再往右扫 —— 游戏记住的是上次看的
        # 那个剧场，只往右会把左边的免费漏掉（见 ``_sweep_to_left_edge``）。
        self._sweep_left_done = False
        card = self._required(screen, "entry_card")
        return self._action(
            "open-theater",
            point=card.center,
            source_page=state_label(MoonlightState.ENTRY),
            target_pages=(state_label(MoonlightState.LIST),),
            reason="点进剧场选择页（有免费先打免费，没有就看看有没有门票）",
        )

    def _at_list(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        # 已经处理过的剧场不再进 —— 判据不只是「Free 角标还在不在」：
        # 角标没消失时（例如这个剧场还有别的免费集、或者那一集观赏后角标滞后）
        # 「入场 → 购买弹窗 → 取消 → 退回列表 → 又入场」会变成死循环。
        fingerprint = self._poster_fingerprint(screen)
        self._snapshot_theater(screen, "list", fingerprint)

        # 阶段 1：先把选中项推到最左边，再从最左往右扫一遍（见 ``_sweep_to_left_edge``）。
        if not self._sweep_left_done:
            action = self._sweep_to_left_edge(screen, fingerprint)
            if action is not None:
                return action
            # 已经到最左（或到了次数上界）⇒ **本帧直接接着处理当前剧场**，不空转。
            # ⚠️⚠️ 这里绝不能 ``return None``。主循环是先用 ``preview()`` 算稳定签名、
            # 再调 ``next_action()`` 提交的，而 ``preview()`` 会把 ``_sweep_left_done``
            # 一起回滚 —— 返回 None 会让「到最左」这一步每帧重复一次，真正该发的
            # 入场 / 往右动作永远轮不到（2026-11-06 改完实测就是这个形态：
            # 归位点了一帧之后整条路线停在列表页，一个动作都不再发）。

        # 阶段 2：从左往右逐个剧场处理。**免费优先**，门票只补没有免费的那些。
        if fingerprint not in self._skip_posters:
            if self._probe_free(screen):
                return self._enter_theater(
                    screen,
                    fingerprint,
                    f"当前剧场可免费观览（{self.free_reason}），入场",
                )
            # 没有免费额度 ⇒ 进去看看手上有没有剧场门票（2026-11-06 用户拍板）。
            # 只在还没确认「券用光」时探：确认用光之后再进去，只会让每个剧场都弹一次
            # 500,000 金币的购买框。⚠️ 这道标记**只拦「无 Free 的剧场」**，
            # 有 Free 的照进照打 —— 券花光了，剩下的免费额度一个都不许漏。
            if not self._tickets_exhausted:
                return self._enter_theater(
                    screen,
                    fingerprint,
                    "当前剧场没有免费额度，入场看看有没有剧场门票可用",
                )

        # 没有免费额度、门票也用光了（或这个剧场已经处理过）⇒ 往右换一张。
        # 右边已经没有了就收工。
        #
        # 「右边没有了」的判据是**点了之后中间那张海报一模一样** —— 不是「点不动」
        # （点哪张选哪张，最右端再点右边是纯粹的无效点击），也不是「整帧逐字节相同」
        # （版面还在动就不成立）。实测见 ``THEATER_POSTER_REGION`` 的表。
        # ⚠️ ``.copy()``：``_crop`` 返回的是**视图**，直接留着等于扣住整帧不放，
        # 而且一旦哪天有人就地改画面，这份「上一帧」会被一起改掉（判据静默失效）。
        poster = self._crop(screen, THEATER_POSTER_REGION).copy()
        if self._poster_signature is not None and not meaningful_change(
            self._poster_signature, poster
        ):
            self._poster_signature = None
            self._finish(
                "往右点了一下，中间那张海报没换（已到最右边那个剧场）；"
                "免费额度与手上的剧场门票都处理完了，本周结束"
            )

        self._poster_signature = poster
        return self._action(
            f"next-theater#{fingerprint}",
            point=self._scaled_point(screen, THEATER_NEXT_POINT),
            source_page=state_label(MoonlightState.LIST),
            in_page_evidence="下一张海报被选中（中间那张的画面必须变）",
            reason=(
                f"当前剧场没有可用的免费或门票（{self.free_reason}），往右换一个"
            ),
        )

    def _enter_theater(
        self, screen: np.ndarray, fingerprint: str, reason: str
    ) -> MoonlightAction:
        """从剧场选择页点「入场」，并把「这一个剧场」的业务记账清零。

        免费剧场和「探门票」的剧场走同一条入场动作，只是``reason``不同 ——
        两者进去之后分集页上的决策完全一样（点观览 ⇒ 指南/剧情/门票弹窗），
        所以没必要分成两个动作名（分成两个反而会让主循环的同名动作账各记一半）。
        """
        self._current_poster = fingerprint
        self._poster_signature = None
        # ⚠️ 「看过这一幕」的记账**只在这里清**（进新剧场 = 换了一集）。
        # 以前是「决定离开分集页时」就清 —— 2026-11-05 00:58 真机证明那样会**漏记账**：
        # 那次离开动作被主循环的转场重放吞掉（见 ``_at_episode`` 里 claim-reward
        # 的注释），机器已经把自己记成「没看过」，自救重决策时又对同一集点了
        # 「进行观览」⇒ 弹「使用剧场门票」⇒ **白花一张门票把同一幕又看了一遍**。
        self.watched_current = False
        self.claimed_current = False
        self._reward_wait_since = None
        button = self._required(screen, "enter_button")
        # ⚠️ 出口有**三个**：正常是分集页；「入场」本身也可能弹门票（用户原话
        # 「进行观览和入场都通向花钱」）⇒ 购买/使用门票两个弹窗都得认。
        # 少写一个的后果和 ``watch-episode`` 那次一样：主循环认为目标没来，
        # 把弹窗那一帧的动作整个吞掉，路线干等到状态超时。
        return self._action(
            "enter-theater",
            point=button.center,
            source_page=state_label(MoonlightState.LIST),
            target_pages=(
                state_label(MoonlightState.EPISODE),
                state_label(MoonlightState.PURCHASE),
                state_label(MoonlightState.USE_TICKET),
            ),
            reason=reason,
        )

    def _sweep_to_left_edge(
        self, screen: np.ndarray, fingerprint: str
    ) -> Optional[MoonlightAction]:
        """把选中的剧场一路推到**最左边**（返回 ``None`` 表示已经归位）。

        为什么要先归位：游戏记住的是「上次看的那个剧场」，它不一定是第一个。只往右
        扫会把左边那些还有免费额度的剧场整个漏掉 —— 而免费额度是本路线的第一目标。

        判「到最左」跟判「到最右」是同一把尺子：点完左边，**中间那张海报的画面**
        没变就是到头了（同一剧场两次差 0.000、换一张 64 以上，见
        ``THEATER_POSTER_REGION`` 的实测表）。
        """
        poster = self._crop(screen, THEATER_POSTER_REGION).copy()
        if self._poster_signature is not None and not meaningful_change(
            self._poster_signature, poster
        ):
            self._sweep_left_done = True
            self._poster_signature = None
            return None

        self._poster_signature = poster
        self._sweep_left_steps += 1
        if self._sweep_left_steps > MAX_SWEEP_LEFT_STEPS:
            # 有界兜底：万一「点左边有效、但海报区域判不出变化」来回打转，
            # 宁可少扫左边几个剧场，也不能一直点下去。接着走正常流程往右扫。
            self._sweep_left_done = True
            self._poster_signature = None
            return None

        return self._action(
            # 名字带海报指纹：连点左边时右边那张一直在换，指纹跟着换才不会撞上
            # 主循环那本「同名动作 45 秒一次、4 次判死」的账。
            f"prev-theater#{fingerprint}",
            point=self._scaled_point(screen, THEATER_PREV_POINT),
            source_page=state_label(MoonlightState.LIST),
            in_page_evidence="上一张海报被选中（中间那张的画面必须变）",
            reason="先把选中项推到最左边，避免漏掉左边的免费剧场",
        )

    def _at_episode(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        self._snapshot_theater(screen, "episode", self._current_poster)
        # 「能领奖」的证据是下载按钮左上角那枚**橙点**（可领才亮）。这里不用按钮本身
        # 当判据：按钮在「可领 / 已领」两种状态下**长得一样**，拿按钮判会反复领。
        # ⚠️ 判据是「模板 **或** 橙色像素数」，单靠模板会漏（橙点是脉动的，见
        # ``_has_reward_dot`` 的实测表）—— 漏认的代价是**奖励没领到**。
        if self._has_reward_dot(screen):
            self.watched_current = True
            self.claimed_current = True
            self._reward_wait_since = None
            return self._action(
                "claim-reward",
                point=self._scaled_point(screen, REWARD_BUTTON_POINT),
                source_page=state_label(MoonlightState.EPISODE),
                # ⚠️⚠️ **不写 target_pages，改走页内证据**。2026-11-05 00:58 真机实测：
                # 点完下载图标，游戏弹的那个「获得奖励」被**全局弹窗守卫**在 capture
                # 层就点掉了（日志 `动作=dismiss-reward-notice 坐标=(960,837)`，落在
                # 点击后 3 秒内），状态机**一帧都看不到**它 ⇒ 「目标页面=获得奖励弹窗」
                # 这条契约在真机上永远不可能成立。
                # 更糟的是它并非「安静地等」：主循环把带 target_pages 的动作记成
                # `last_transition_action`，契约不成立就按「原页面仍存在且目标页面
                # 未出现」把 claim-reward **原地重放** 4 次（每帧重算分、重新点击），
                # 期间状态机给出的**下一步正确决策（离开剧场）被整个丢弃** ——
                # 于是 3 分钟后走自救，落到「这一集还没进去过」那条路，白花一张门票。
                #
                # 这条动作的成功本来就是**页内变化**（橙点灭掉），不是换页，
                # 与 `next-theater` / `advance-story` 同类 ⇒ 按它们的写法用
                # `in_page_evidence`，不带 target_pages（没带契约的动作不会被重放，
                # 也不会吞掉下一帧的新决策）。
                # 不会因此静默降级：橙点还在 ⇒ 下一帧仍是同名 claim-reward ⇒
                # 主循环那本「同名动作 4 次不推进」的账照常生效，最后报错收尾。
                in_page_evidence="橙点仍在（这一集的观览奖励还没领掉）",
                reason="这一幕看完了，点下载图标领取观览奖励",
            )

        # ⚠️⚠️ **刚看完这一幕的「没有橙点」不能当成「没有奖励」**。
        #
        # 橙点是脉动动画、而且奖励可能晚一拍才到账。真机上 0.5 秒的轮询很容易
        # 在第一帧就看见「页面回来了、橙点还没亮」—— 于是判「没得领」直接撤，
        # **这一集的奖励就漏了**（用户 2026-10-17：漏领就是没闭环，不许当可接受风险）。
        #
        # 所以先等 ``REWARD_GRACE_FRAMES`` 帧（0.5 秒轮询 ≈ 8 秒）：
        # 本帧不下结论、不点任何东西，让主循环下一帧再看一眼橙点亮没亮。
        # 等满了还是没有 ⇒ 那是**真的没有可领**（这个剧场的奖励之前就领过了），才撤。
        if self.watched_current and not self.claimed_current and not self.must_leave:
            if self._reward_wait_since is None:
                self._reward_wait_since = self.clock()
            if self.clock() - self._reward_wait_since < REWARD_GRACE_SECONDS:
                return None

        # 走到这里说明分集页上确实没有橙点。**只要进去过剧情，就绝不再点「进行观览」**：
        # 那一集的额度已经花掉了，再点只会弹门票（花券/花金币），或者白看一遍。
        if self.watched_current or self.must_leave:
            # 两种「撤」：看完了（``watched_current``）与被购买弹窗劝退（``must_leave``）。
            # 只有前者算「完成一幕」，后者是「这个剧场要花门票，不干」。
            completed = self.watched_current
            back = self._required(screen, "back_button")
            # ⚠️⚠️ ``watched_current`` **不在这里清**（2026-11-05 00:58 真机）：
            # 这条「离开」动作有可能被主循环的转场重放吞掉（claim-reward 那条注释
            # 说的是同一个根因）。以前边决定边清账 ⇒ 吞掉之后机器已经忘了自己看过
            # 这一幕，自救重决策落到「这一集还没进去过」那条路 ⇒ 又点「进行观览」
            # ⇒ 弹「使用剧场门票」⇒ **白花一张门票看第二遍同一幕**。
            # 现在只在 ``_at_list`` 进新剧场时清（换了一集才算重新记账）。
            self.must_leave = False
            # ``claimed_current`` 同理**不在这里清**：清了会让下一帧又落进
            # 「看过了但还没领到，先等 8 秒橙点」的宽限分支，白等一轮；
            # 它同样只在 ``_at_list`` 进新剧场时清。
            #
            # ``_reward_wait_since`` 也**不清**：宽限的语义是「等够 8 秒还没橙点
            # 就撤」，等过一次就不该再等第二次 —— 清零等于每被重问一次就白等 8 秒。
            # 计数也要幂等：同一个剧场只可能「完成一幕」一次。``_skip_posters``
            # 在下面这行加进去，所以「已经加过」＝「这一幕已经记过一次账」。
            first_time = self._current_poster not in self._skip_posters
            self._skip_posters.add(self._current_poster)
            if completed and first_time:
                self.completed_cycles += 1
            return self._action(
                "leave-theater" if completed else "abandon-theater",
                point=back.center,
                source_page=state_label(MoonlightState.EPISODE),
                target_pages=(state_label(MoonlightState.LIST),),
                reason=(
                    "本剧场这一幕已看完并领奖，返回剧场选择页"
                    if completed
                    else "这一幕要花门票才让看，不花，退回剧场选择页换下一个"
                ),
            )

        # 只有「这一集还没进去过」才走到这儿 ⇒ 点观览是安全的。
        #
        # ⚠️ 出口有**三个**，必须写全：正常是「观览指南弹窗」；这一集的免费额度
        # 已经用掉时，同样的点击会弹「使用剧场门票」（花券）或「购买剧场门票」
        # （花金币）。少写一个的后果是实测过的（2026-10-17 14:47）：主循环认为
        # 「点了进行观览、目标观览指南一直没来」，于是把门票弹窗那一帧的动作整个
        # 吞掉（`_transition_completed` 不成立 ⇒ action 置 None），路线干等到超时。
        watch = self._required(screen, "watch_button")
        return self._action(
            "watch-episode",
            point=watch.center,
            source_page=state_label(MoonlightState.EPISODE),
            target_pages=(
                state_label(MoonlightState.GUIDE),
                state_label(MoonlightState.USE_TICKET),
                state_label(MoonlightState.PURCHASE),
                # 保险项：没有观览指南的关（纯战斗关 / 直接进剧情）也认得出。
                state_label(MoonlightState.BATTLE),
                state_label(MoonlightState.STORY),
            ),
            reason="点进行观览（若本集额度已用完，出口会是花券/买票确认弹窗）",
        )

    def _at_guide(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        confirm = self._required(screen, "guide_confirm")
        return self._action(
            "confirm-guide",
            point=confirm.center,
            source_page=state_label(MoonlightState.GUIDE),
            # ⚠️ 出口四个：绝大多数是剧情页；**纯战斗关**点完确认直接进战斗；
            # 战斗帧万一没认出来（``battle_scene_visible`` 不成立）时下一帧可能是
            # CLEAR 或已回到分集页 —— 这几种都算「确认生效了」，必须列全。
            # 只写剧情页时，这几种落点会让动作永久发不出去（目标一直不出现）。
            target_pages=(
                state_label(MoonlightState.STORY),
                state_label(MoonlightState.BATTLE),
                state_label(MoonlightState.CLEAR),
                state_label(MoonlightState.EPISODE),
            ),
            reason="观览指南提示不可跳过，点确认开始",
        )

    def _at_story(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        if (
            self._locate(screen, "story_continue") is None
            and self._locate(screen, "story_hud") is None
        ):
            # 黑屏 / 淡入帧：▼ 还没出来（字幕在逐字打）。这一帧**必须照点**，
            # 否则剧情停在第一句永远不动。推进点是固定常量 ``STORY_CLICK_POINT``
            # （(760,1000) 在分集页是空白、在剧情页落在字幕框内，见那里的注释），
            # 所以没有 ▼ 也知道该点哪儿。
            # ⚠️ 只有确认「整屏黑 + 底部有字幕白字」才走这条；别的画面照样失败关闭。
            if not self._looks_like_story_dark_frame(screen):
                self._required(screen, "story_continue")
        # ⚠️ **进剧情 ⇒ 这一集的观览额度已经消耗掉**。这是本路线最关键的一条记账，
        # 记晚了就是 2026-10-17 真机那场事故：
        #   剧情走完回分集页 → 橙点没认出来 → 判定「没看过」→ 又点「进行观览」→
        #   白看第二遍 → 免费额度用光 → 弹「使用剧场门票」→ 连点 4 次卡死。
        # 记账之后，分集页只可能走两条路：「有橙点就领奖」「没橙点就撤」，**永远
        # 不会再点第二次进行观览**。
        self.watched_current = True
        return self._action(
            f"advance-story#{self._story_fingerprint(screen)}",
            point=self._scaled_point(screen, STORY_CLICK_POINT),
            source_page=state_label(MoonlightState.STORY),
            in_page_evidence="字幕推进（下一帧的字幕/画面指纹必须变）",
            reason="剧情不可跳过，点字幕往下推",
        )

    def _at_reward(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        """「获得奖励」弹窗：点底部的「点击关闭」（复用圣域的通用关窗模板）。"""
        close = self._required(screen, "reward_popup_close")
        return self._action(
            "close-reward",
            point=close.center,
            source_page=state_label(MoonlightState.REWARD),
            # 关窗后正常回分集页；若这一集已经到头，也可能直接退回选择页。
            target_pages=(
                state_label(MoonlightState.EPISODE),
                state_label(MoonlightState.LIST),
            ),
            reason="关掉「获得奖励」弹窗，回到分集页",
        )

    def _at_purchase(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        """购买门票弹窗：**只点取消**，绝不点购买（用户明确不许花金币）。

        同时记三件事：①「这个剧场这个幕要花门票」⇒ 接下来在分集页**只许撤**
        （``must_leave``），否则会「取消 → 又点进行观览 → 又弹购买」；② 这个剧场
        拉进 ``_skip_posters``，退回列表后不再入场（角标没消失也挡得住）；
        ③ **门票确认用光**（``_tickets_exhausted``）—— 这一下等于游戏亲口说
        「你手上没有券了」，于是后面那些没有免费额度的剧场不必再一个一个进去探，
        否则每个都会弹一次这个 500,000 金币的框。
        """
        cancel = self._required(screen, "purchase_cancel")
        self.must_leave = True
        self._tickets_exhausted = True
        self._skip_posters.add(self._current_poster)
        return self._action(
            "cancel-purchase",
            point=cancel.center,
            source_page=state_label(MoonlightState.PURCHASE),
            # ⚠️ 出口两个：从分集页点「进行观览」弹出来 ⇒ 取消回分集页；
            # 从剧场选择页点「入场」弹出来 ⇒ 取消回**选择页**。只写分集页时，
            # 后一种会判「目标没来」并把动作吞掉，表现就是安静地干等。
            target_pages=(
                state_label(MoonlightState.EPISODE),
                state_label(MoonlightState.LIST),
            ),
            reason="门票不足弹出了购买确认，点取消（本路线永不花金币买门票）",
        )

    def _at_clear(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        """CLEAR 过场：**点一下**推进，绝不干等。

        ## 2026-10-17 真机事故（``timeout_clear``，退出码 1）

        原来的写法是「不点任何东西，等它自己过去」，真机上它**根本不会自己过去**：
        那一轮在 CLEAR 上干等了 60 秒，直到 ``_TIMEOUT_SECONDS[CLEAR]`` 到期，
        诊断图 ``20261017_135730_782835_timeout_clear.png`` 里 CLEAR 字标还挂在
        战斗画面上。而收尾阶段按 ESC 能弹出快捷菜单 ⇒ **游戏没死，就是在等你点**。

        ⚠️ 判「要不要点」时别拿支线故事的画面当参照：支线故事的战斗关 CLEAR 上
        右侧有一对「»»」继续箭头（``side_story._ARROW_CLICK_POINT = (1820,750)``
        点的就是它），**本路线的 CLEAR 上没有那对箭头**（同一位置是空白雪地，
        见证据档案的对照）。有没有箭头都不影响「点一下就走」——
        有箭头是提示你点，没箭头是照点不误。

        点哪儿：**复用 ``STORY_CLICK_POINT``**。CLEAR 之后落到的不是剧情页
        （继续点字幕）就是分集页（领奖），而这个点已经实测在分集页是空白区
        （``STORY_CLICK_POINT`` 的注释里有误触「进行观览」弹出购买门票的教训）、
        在剧情页能推进 —— 是这条路线里唯一一个「三种页面上都安全」的点。

        为什么不带指纹：CLEAR 是**一次性过场**，不带指纹才能让主循环那本
        「同名动作点 4 次还没换页就判死」的账照常生效 —— 反过来（静等）的代价
        就是这次事故：既不动、又不报错，白白烧掉 60 秒才失败。
        """
        return self._action(
            "advance-clear",
            point=self._scaled_point(screen, STORY_CLICK_POINT),
            source_page=state_label(MoonlightState.CLEAR),
            target_pages=(
                state_label(MoonlightState.STORY),
                state_label(MoonlightState.EPISODE),
                # 保险项：CLEAR 之后若还有一场战斗（连续战），也要认得出。
                state_label(MoonlightState.BATTLE),
            ),
            reason="CLEAR 不会自己消失，点一下推进（接着剧情或回分集页领奖）",
        )

    def _at_use_ticket(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        """「使用剧场门票」弹窗：**确认花掉一张券**继续观览（用户 2026-10-17 拍板「花掉」）。

        ## 与 ``_at_purchase`` 是两个相反的弹窗，别合并

        | 弹窗 | 花什么 | 处理 |
        |---|---|---|
        | 购买剧场门票 | **500,000 金币** | 只点取消（用户明令不许买） |
        | 使用剧场门票 | **已持有的 1 张券** | 点确认花掉（用户拍板） |

        两者版式几乎一样（标题 + 取消/确认），所以**身份只能靠标题判**，
        按钮只当点击锚点 —— 拿按钮判会把「花金币」和「花券」串掉。

        兜底：确认按钮定位不到（券用光后按钮会变灰，或者版式变了）⇒ 退回点取消、
        并把当前剧场记进 ``_skip_posters``；**看不清就不花**，绝不乱点。

        ⚠️ 一旦 ``must_leave`` 已经置位（上一帧点了取消但弹窗没关掉），**不许再走确认**：
        否则「放弃」会退化成「花掉」，方向正好反了。
        """
        if self.must_leave:
            return self._cancel_ticket(screen)
        confirm = self._locate(screen, "ticket_confirm")
        if confirm is not None:
            return self._action(
                "accept-ticket",
                point=confirm.center,
                source_page=state_label(MoonlightState.USE_TICKET),
                target_pages=(
                    state_label(MoonlightState.GUIDE),
                    state_label(MoonlightState.STORY),
                    # 保险项：没有观览指南的关（纯战斗关）会直接进战斗。
                    state_label(MoonlightState.BATTLE),
                ),
                reason="本集免费额度已用完，用户拍板花掉一张剧场门票继续观览",
            )
        return self._cancel_ticket(screen)

    def _cancel_ticket(self, screen: np.ndarray) -> MoonlightAction:
        """点「取消」并放弃这个剧场。**已经决定不花之后，任何情况下都走这条。**"""
        cancel = self._required(screen, "ticket_cancel")
        self.must_leave = True
        # 走到这里只有两种原因：①刚点过「购买」框的取消（那个框本身就说明没券）；
        # ②「使用门票」框上的确认按钮点不动（券用光后按钮会变灰）。
        # 两种都等于「手上没券了」⇒ 后面没有免费额度的剧场别再一个个进去探。
        self._tickets_exhausted = True
        self._skip_posters.add(self._current_poster)
        return self._action(
            "cancel-ticket",
            point=cancel.center,
            source_page=state_label(MoonlightState.USE_TICKET),
            # 同 ``cancel-purchase``：这个弹窗从分集页或选择页都能弹出来。
            target_pages=(
                state_label(MoonlightState.EPISODE),
                state_label(MoonlightState.LIST),
            ),
            reason="不花这张券，点取消并放弃这个剧场",
        )

    # ---- 主决策 ----

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        width, height = screen.shape[1], screen.shape[0]
        scale_x = width / self._REFERENCE_SIZE[0]
        scale_y = height / self._REFERENCE_SIZE[1]
        if abs(scale_x - scale_y) > 0.02:
            raise RuntimeError("画面宽高比与模板基准不一致")
        return (round(point[0] * scale_x), round(point[1] * scale_y))

    def next_action(self, screen: np.ndarray) -> Optional[MoonlightAction]:
        page = self.observe_page(screen)
        if page is None:
            # 认不出 = 正在转场。不出动作、不猜坐标，让主循环等下一帧。
            return None

        self.state = page
        self._confirm_page(state_label(page))

        if page is MoonlightState.ENTRY:
            return self._at_entry(screen)
        if page is MoonlightState.LIST:
            return self._at_list(screen)
        if page is MoonlightState.EPISODE:
            return self._at_episode(screen)
        if page is MoonlightState.GUIDE:
            return self._at_guide(screen)
        if page is MoonlightState.STORY:
            return self._at_story(screen)
        if page is MoonlightState.PURCHASE:
            return self._at_purchase(screen)
        if page is MoonlightState.USE_TICKET:
            return self._at_use_ticket(screen)
        if page is MoonlightState.REWARD:
            return self._at_reward(screen)
        if page is MoonlightState.CLEAR:
            return self._at_clear(screen)
        if page is MoonlightState.BATTLE:
            return None
        return None

    def preview(self, screen: np.ndarray):
        """试算一次决策，然后**把状态回滚**（主循环用它探路，不能留下副作用）。"""
        snapshot = (
            self.state,
            self.completed_cycles,
            self.watched_current,
            self.must_leave,
            self.claimed_current,
            self._reward_wait_since,
            set(self._skip_posters),
            self._current_poster,
            self._poster_signature,
            self._confirmed_page,
            self.finish_reason,
            self.has_free,
            self.free_reason,
            self._tickets_exhausted,
            self._sweep_left_done,
            self._sweep_left_steps,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.watched_current,
                self.must_leave,
                self.claimed_current,
                self._reward_wait_since,
                self._skip_posters,
                self._current_poster,
                self._poster_signature,
                self._confirmed_page,
                self.finish_reason,
                self.has_free,
                self.free_reason,
                self._tickets_exhausted,
                self._sweep_left_done,
                self._sweep_left_steps,
            ) = snapshot

    # ---- 战斗观察（交给 BattleSupervisor） ----

    _AUTO_CLICK_POINT = (1690, 96)

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        """战斗监督每帧来问一次；本路线的口径与刷图路线有两处不同。

        ## 一、「战斗结束」的名单里必须有**剧情页**

        剧情页的 ▼ 与分集页的「进行观览」都代表「战斗已经结束、该把控制权还给我」。
        漏了剧情页这一项，代价是实测过的：战斗打完回到剧情页，监督那五项判据**全 False**
        ⇒ 判成「未知画面」⇒ 干等 45 秒报 ``battle_unrecognized``、退出码 1
        （同 ``side_story.observe_battle`` 2026-10-15 那次事故）。

        ## 二、不在战斗画面时**不许**判「自动/手动」

        ``observe_battle_controls`` 只认底座颜色，剧情页右上角那三个灰掉的图标
        （回放 / 记录 / 暂停）凑得出「手动」的形状。真按 ``auto_point`` 点下去，
        点的是剧情页的暂停键 —— 剧情会当场卡住。所以非战斗帧一律报 ``UNKNOWN``
        （监督只在 ``MANUAL`` 时才动 ``auto_point``，见 ``BattleSupervisor``）。
        """
        controls = observe_battle_controls(screen)
        # 字幕箭头在 ⇒ 一定不是战斗画面（战斗界面没有剧情字幕框）。
        in_battle = (
            battle_scene_visible(screen)
            and self._locate(screen, "story_continue") is None
        )
        if in_battle:
            # 每场战斗存一张真机帧：战斗锚点里有两枚含「会变的内容」，需要新样本
            # 才能判断它们还靠不靠得住（见 ``_snapshot_battle``）。
            self._snapshot_battle(screen)
            auto_state = {
                BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
                BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
                BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
            }[controls]
            auto_evidence = f"布局={controls.value}"
            auto_point = self._scaled_point(screen, self._AUTO_CLICK_POINT)
        else:
            self._battle_sampled = False
            auto_state = AutoBattleState.UNKNOWN
            auto_evidence = "不在战斗画面（不判自动/手动、不给开关坐标）"
            auto_point = None
        # 战斗结束的判据：出现 CLEAR、回到剧情页、回到分集页。
        result_visible = any(
            self._locate(screen, key) is not None
            for key in ("battle_clear", "story_continue", "watch_button")
        )
        return BattleObservation(
            pre_battle_visible=False,
            battle_visible=in_battle,
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_evidence=auto_evidence,
            auto_point=auto_point,
        )


class MoonlightRunner(ModeRunnerBase):
    """月光剧场 Runner；主循环协议见 ``ModeRunnerBase``（本类只声明差异）。"""

    _MODE_LABEL = "月光剧场"
    _TIMEOUT_SECONDS = {
        MoonlightState.ENTRY: 45,
        MoonlightState.LIST: 45,
        MoonlightState.EPISODE: 45,
        MoonlightState.GUIDE: 30,
        # 一整集剧情可能要点几百次、跨几分钟 ⇒ 这个状态的超时要给足。
        MoonlightState.STORY: 1200,
        MoonlightState.BATTLE: 900,
        # CLEAR 有自己的动作（``advance-clear``）⇒ 这个超时只兜「点完之后画面一直
        # 认不出」的底；「停在 CLEAR 上不动」由主循环的 4 次点击判定接管。
        MoonlightState.CLEAR: 60,
        MoonlightState.REWARD: 30,
        MoonlightState.PURCHASE: 30,
        MoonlightState.USE_TICKET: 30,
        MoonlightState.FINISHED: 30,
    }
    # 战斗是剧情自动触发的（没有开战按钮）⇒ 停在战斗态且本帧无动作就交监督。
    _SETTLED_BATTLE_STATE = MoonlightState.BATTLE
    _BATTLE_ENTRY_ACTION = None
    # 认不出画面时**不要**去点屏幕中央：这条路线盲点过一次就买门票弹窗了。
    _ALLOW_UNKNOWN_SCREEN_WAKE = False
    _REQUIRE_TRANSITION_CONTRACT = True

    # CLEAR 过场的同名重试间隔（理由见 ``_action_retry_seconds``）。
    _CLEAR_RETRY_SECONDS = 2.5

    def __init__(
        self,
        machine: MoonlightStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        # 用户的口径是「字幕 0.5 秒点一次」⇒ 轮询就是 0.5 秒（默认 1.0 太慢）。
        poll_seconds: float = 0.5,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        # 「等橙点亮」和主循环的状态超时必须看同一块表，否则一个按真时间、一个按假时间。
        machine.set_clock(self.now)
        # 存样（没见过剧场的样张 / 战斗帧）需要诊断目录 ⇒ 把 runtime 交给状态机。
        # ⚠️ 只用于写文件，**不参与任何决策**。
        machine.runtime = runtime
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="moonlight_theater", mode_label="月光剧场"),
            now=self.now,
            sleep=sleep,
        )

    # ---- 同名重复动作的两个钩子（本路线必须覆盖，理由见下）----

    def _stable_action_signature(self, preview_action: Any, outcome: Any) -> str:
        """两帧确认只认**动作族**，不认指纹后缀。

        ``advance-story`` / ``next-theater`` 的动作名带画面指纹（``名#abc123``）——
        那是给主循环那本「同名动作重复几次」的账用的（画面一变就换名字，等于
        「真的在推进」）。指纹**不能**进稳定签名：剧情页的字幕是逐字打出来的，
        两帧的指纹天然不同，签名跟着变就永远凑不齐两帧一致 ⇒ 一次都点不下去。
        """
        name = getattr(preview_action, "name", "")
        if "#" in name:
            return name.split("#", 1)[0]
        return super()._stable_action_signature(preview_action, outcome)

    def _action_retry_seconds(self, action_name: str) -> float:
        """字幕点击 / CLEAR 过场的「同名重试窗口」都比默认短。

        默认 45 秒是给「点一下就该换页」的按钮用的；这两类画面都不是：
        * 字幕是**连着点**的 —— 45 秒一次等于剧情停在那里不动。压到 0.5 秒后：
          画面在变 ⇒ 名字（指纹）在变 ⇒ 根本走不到这个窗口；画面真的不动 ⇒
          4 次之后照常判死（安全边界不变）。
        * CLEAR 过场会**一直挂着**（2026-10-17 实测 60 秒都没走），45 秒后才补
          第二下太晚了；但也不能给 0.5 秒（过场动画要时间，0.5 秒点 4 下等于瞎戳）。
          2.5 秒 × 4 次 ≈ 10 秒还推不动 ⇒ 那是真的卡住了，报错让人来看。
        """
        if action_name.startswith("advance-story"):
            return self.poll_seconds
        if action_name.startswith("advance-clear"):
            return self._CLEAR_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _state_label(self, state: MoonlightState) -> str:
        return state_label(state)

    def _run_committed_battle(self, *, cycle: int) -> BattleOutcome:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = MoonlightState.EPISODE
            return outcome
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"月光剧场战斗出现意外结果：{outcome.value}")
        # 打完回到剧情页继续点字幕（剧情可能还在继续），状态机下一帧自己会判。
        self.machine.state = MoonlightState.STORY
        return outcome

    def route_note(self) -> str:
        """给每日任务结算用的一句话收获：复用现成、带幂等保护的「完成几幕」。"""
        if self.runtime.dry_run:
            return ""
        acts = self.machine.completed_cycles
        if not acts:
            return "本周免费观览与门票均已处理完毕"
        return f"完成观览 {acts} 幕"

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式=月光剧场 完成第 {self.machine.completed_cycles} 幕"
        )

    # ---- 收尾：先把剧情推完，再回家 ----

    #: 收尾推剧情的上限（每 ``poll_seconds`` 点一次，120 次 ≈ 1 分钟）。
    #: 不能给太大：收尾阶段用户可能已经在等着了；也不能太小：一集剧情要几百次点击。
    _LEAVE_STORY_MAX_CLICKS = 120

    def _close_out(self) -> None:
        """收尾回大厅之前，先把自己从剧情页里放出来。

        ⚠️ **月光剧场的剧情不能跳过**（观览指南原话「月光剧场的故事情无法跳过」），
        剧情页右上角只有「记录 / 暂停」两枚图标、**没有「跳过」**；而剧情页又不吃
        ESC ⇒ 停在这一页上收尾，导航层只能连按两次 ESC 后报「回首页失败」
        （2026-10-24 三次实跑都栽在这，`return_home_v2_esc_no_effect`）。

        ⚠️ 只处理**正常收尾**。异常退出走 ``main`` 那条路，那里拿不到本路线的
        状态机，管不了这件事（那一侧靠 ``_try_return_home_after_failure`` 吞异常）。
        """
        try:
            self._leave_story_before_home()
        except Exception as error:  # noqa: BLE001 —— 收尾绝不能再抛
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾前离开剧情页失败="
                f"{type(error).__name__}: {error} 处理=照常尝试回家"
            )
        super()._close_out()

    def _leave_story_before_home(self) -> None:
        """在剧情页上就把字幕点完（有界），离开后立刻返回。

        ⚠️ 前进条件只认 ``advance-story``：收尾阶段**绝不**在这里点别的动作
        （尤其「进行观览」，那会花掉额度；以及任何门票弹窗上的按钮）。
        """
        if self.machine.state is not MoonlightState.STORY:
            return
        for _ in range(self._LEAVE_STORY_MAX_CLICKS):
            screen = self.runtime.capture()
            if self.machine.observe_page(screen) is not MoonlightState.STORY:
                return
            action = self.machine.next_action(screen)
            if action is None or not action.name.startswith("advance-story"):
                return
            self.runtime.click(action.point, action.name)
            self.sleep(self.poll_seconds)
        self.runtime.log(
            f"模式={self._MODE_LABEL} 收尾前推剧情 达到上限="
            f"{self._LEAVE_STORY_MAX_CLICKS}次，放弃继续推"
        )
