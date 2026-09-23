"""骑士团「世界首领战」自动循环。

## 一轮循环（2026-09-21 实机走通，坐标均为画布坐标 1982×1132）

```
HOME            世界首领战主页 →「选择队伍」(1781,1052)
TEAM_SELECT     选择辅助队伍页 →「组成战斗队伍」(1631,1038)
TEAM_CONFIG     配置队伍页（**分两阶段，靠「自动配置」按钮色相区分**）
                  ├ 按钮橙 = 尚未配置 →「自动配置」(246,1034)
                  └ 按钮蓝 = 已配置   →「战斗开始」(1376,1036)
  ↓（体力不足 → stamina.py：点生命之叶 → 点购买）
BATTLE          已承诺战斗，移交战斗监督
                  └ 认到战斗画面 ⇒ 点右上角「跳过」(1631,97)，很快衔接到结算
  ↓
RESULT          结算页 →「确认」(1730,1036) → 弹出「战斗级别奖励」
LEVEL_REWARD    「全部开启」(961,994) → 同一按钮变「确认」(959,994)
  ↓
RESULT_CONFIRM  回结算页 →「确认」(1730,1036)
  ↓
  └→ 回 HOME，次数 -1，循环
```

## ⚠️ 每个动作都必须声明出处与去处（2026-09-22 修正）

这个模块原先的 ``WorldBossAction`` 只有 ``name`` + ``point``，主循环**点完不回头验收**，
于是 2026-09-22 首次实跑出现「进配置队伍页的同一秒直接点战斗开始」——
漏掉了「自动配置」这一步，队伍是空的就开打，一路蒙到战斗画面认不出才被兜住。

现在对齐 story / expedition 的转场契约：

- ``WorldBossAction`` 带 ``source_page``（我现在站在哪一页）/ ``target_pages``（点完该到哪一页）。
- 所有动作统一经 ``_action()`` 构造，它会 ``_confirm_page(source_page)`` 写 ``_confirmed_page``
  —— 这个字段之前**从未被赋值过**，导致 ``runner_base._transition_completed`` 全程空转。
- 「点自动配置」这类**不换页**的动作 ``target_pages`` **留空**。⚠️ 别写 ``(本页,)``：
  本页永远在集合里 ⇒ 验收永远通过 ⇒ 又退化成秒点。不声明就不进转场账本，
  验收交给**页面内状态证据**（按钮橙→蓝），没变就按重试窗口有界重试。

## 页面识别（模板匹配）与点击点（实测固定坐标）分开

- **页面识别**用 ``evidence/world_boss.py`` 的六个锚点（已做全库 185 张排他性扫描）。
- **点击点**用上表这几个实机走查时验证过的固定坐标，不再为按钮单独裁模板：
  这些按钮在页内位置固定，且实机帧上逐个点过、确认有效（见 ``docs/WORLD_BOSS_DESIGN.md`` 第二节）。
  少裁 6 个模板 = 少 6 处会随版本漂移的东西。

## ⚠️ 战斗页面：`battle_scene_visible` **认不出这一屏**（2026-09-22 实跑报错的根因）

世界首领战的战斗画面**不是**竞技场/远征那套「右下 4 格底座 + 左侧行动顺序」布局，
而是「左上 boss 名 + 血条、右上 跳过/聊天/暂停、右侧 12 人分数列」的团本布局。
实测 `battle_scene_visible` 在它上面**恒为 False**（圆只检到 2 个、行动顺序白占比 0.0466）
⇒ 监督的 `recognized` 连续 45 秒为假 ⇒ `battle_unrecognized` 安全停止。
2026-09-22 20:57 那次实跑就是这么停的（报错帧其实已经是结算页在淡入，只差一两秒）。

### 修法：右上角「跳过 」既是识别锚点，也是推进动作

用户实拍确认：战斗画面右上角有「跳过 」，**点它才衔接到结算页**。
画布实测（用户 1920×1080 截图按 `window.py::_legacy_canvas` 的 (0,+52) 偏移还原）：

| 项 | 值 |
|---|---|
| 亮像素包围盒 | x=[1581,1682] y=[81,113]（102×33） |
| 点击中心 | **(1631, 97)** |
| 模板 | `templates/world_boss/battle_skip.png`（117×48，含 8px 余量） |
| 搜索区 | `BATTLE_SKIP_REGION=(1500,55,260,110)` |
| 阈值 | **0.80** |

- **识别**：`battle_scene_visible` **或**「跳过」命中 ⇒ 判定「在战斗中」。
- **推进**：命中时把 `("skip-battle", match.center)` 放进
  `BattleObservation.allowed_action`，由监督点掉；点完进结算页。

⚠️ 两个必读要点：

1. **boss 技能演出会整块隐藏 UI**（「跳过」也一起消失，顶部血条、右侧分数列全没）。
   那种帧认不出来是正常的 —— 一次演出只有几秒，下一帧 UI 回来就重新认到，
   45 秒看门狗靠这个复位。所以不要试图给演出帧单独做锚点。
2. **搜索窗口宽度就是锚点的一部分**：同一张「跳过 」图形在剧情播放页也有，
   但两页里它出现的位置不同（本路线 x≈1581~1682，剧情页 x≈1769~1886）。
   窗口收到 `x < 1760` 之后，剧情页从 0.8585 掉到 0.2803，而真实战斗帧仍有 0.9086。
   把窗口放宽回整条右上角，间距就只剩 0.05 —— 那时锚点会变成「在不在剧情页」的赌注。
   实测表见 `runtime_logs/_wb_battle_anchor_probe.py` 的输出。

⚠️ 骑士团入口图标热区小：点图标**中心** (1235,1020) 才进得去，点边缘或文字都没反应。
导航层用模板匹配取中心点，天然满足这条。

## 次数判据：看「选择队伍」按钮亮/灰（**不用 OCR**）

2026-09-21 用户确认用按钮亮/灰，不在运行期引入 OCR。实测按钮底板那条绿色高亮带：

| 状态 | 显示 | 绿像素占比 |
|---|---|---|
| 还能打 | `1/2` | **59.2%** |
| 打完了 | `0/2` | **0.0%** |

阈值 10% 落在两者之间，离两边都很远。口径仍是「看游戏给的次数」而不是「看进程跑了几轮」，
且**不硬编码上限 2** —— 本判据只回答「按钮还亮不亮」。

## 体力：零改动复用 ``stamina.py``

行动力不足弹窗的三个模板在本路线实测 0.9999 / 0.9895 / 1.0000，与 story 同一套控件。
只用**生命之叶**买（1 片 → 80 体力），**绝不用钻石**；树叶耗尽 ``StaminaExhausted`` → 退出码 2。
"""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

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
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.world_boss import (
    REFERENCE_SIZE as WORLD_BOSS_REFERENCE_SIZE,
    build_world_boss_evidence,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.stamina import (
    STAMINA_REGIONS,
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class WorldBossState(Enum):
    HOME = "home"
    TEAM_SELECT = "team_select"
    TEAM_CONFIG = "team_config"
    BATTLE = "battle"
    RESULT = "result"
    LEVEL_REWARD = "level_reward"
    RESULT_CONFIRM = "result_confirm"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    WorldBossState.HOME: "世界首领战主页",
    WorldBossState.TEAM_SELECT: "选择辅助队伍",
    WorldBossState.TEAM_CONFIG: "配置队伍",
    WorldBossState.BATTLE: "战斗中",
    WorldBossState.RESULT: "战斗结算",
    WorldBossState.LEVEL_REWARD: "战斗级别奖励",
    WorldBossState.RESULT_CONFIRM: "结算确认",
}


def state_label(state: WorldBossState) -> str:
    return STATE_LABELS.get(state, state.value)


# 实机走查验证过的点击点（画布坐标），随步骤推进逐个使用。
CLICK_POINTS = {
    "open-team-select": (1781, 1052),   # 主页「选择队伍」
    "build-team": (1631, 1038),         # 选择辅助队伍页「组成战斗队伍」
    "auto-configure": (246, 1034),      # 配置队伍页「自动配置」
    "battle-start": (1376, 1036),       # 配置队伍页「战斗开始」
    "open-level-reward": (1730, 1036),  # 结算页「确认」→ 弹奖励
    "open-all-chests": (961, 994),      # 奖励弹窗「全部开启」
    "confirm-level-reward": (959, 994), # 奖励弹窗「确认」（同一按钮换字）
    "confirm-result": (1730, 1036),     # 结算页「确认」→ 回主页
}

# 「选择队伍」按钮底板那条绿色高亮带（基准画布坐标）。
# 2026-09-21 自 worldboss_home.png 的绿色连通块实测：(1550,1066)-(1894,1099)。
SELECT_TEAM_BAR = (1550, 1066, 344, 33)

# 绿条判据：绿色像素占比低于此值即认为按钮已变灰（= 今天打完了）。
SELECT_TEAM_ENABLED_GREEN_RATIO = 0.10

# HSV 绿色范围，与 fodder 判「亮色按钮」用的是同一套。
_GREEN_LOWER = np.array([35, 80, 90])
_GREEN_UPPER = np.array([90, 255, 255])


def select_team_green_ratio(screen: np.ndarray, *, reference_size=WORLD_BOSS_REFERENCE_SIZE) -> float:
    """量「选择队伍」按钮底板的绿色像素占比（0.0~1.0）。"""
    x, y, width, height = SELECT_TEAM_BAR
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    x, y = round(x * scale_x), round(y * scale_y)
    width, height = round(width * scale_x), round(height * scale_y)
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return 0.0
    mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_RGB2HSV), _GREEN_LOWER, _GREEN_UPPER)
    return float(mask.mean()) / 255.0


def select_team_enabled(screen: np.ndarray) -> bool:
    """主页「选择队伍」按钮是否还可点（= 今天还有次数）。"""
    return select_team_green_ratio(screen) >= SELECT_TEAM_ENABLED_GREEN_RATIO


# 配置队伍页的「三队槽位区」（基准画布坐标）：1/2/3 队的底座与战斗力数字。
TEAM_SLOTS_ROI = (30, 660, 1450, 900)

# 三队**是否真的配好了**，靠槽位区的**画面细节量**（拉普拉斯方差）判断：
# 空槽位只有暗背景 + 一组细描边，画面平滑；配好后是英雄头像，细节密集。
#
# 2026-09-22 实测（画布 1982x1132）：
# | 画面 | 细节量 |
# |---|---|
# | 空队伍（`team_config.png`、实跑失败帧） | 347 ~ 451 |
# | 点过「自动配置」后（`team_config_configured.png`，三队各 5 人，战斗力 58~67 万） | **1181** |
#
# ⇒ 阈值 700 落在两簇正中，两侧余量 249 / 481，非常宽。
#
# ⚠️⚠️ **别再拿「自动配置」按钮的颜色当判据**（2026-09-22 实跑踩过）：
# 那颗按钮（连同三个队伍底座的描边）会在**橙 / 蓝之间整体翻转**
# （同一块区域橙色像素 784 对蓝色像素 16767，两帧完全对称互换），
# 但**与「队伍配没配」毫无关系** —— 同一个「三队全空、战斗力 0」的页面，
# 15:04 抓到的是蓝色、15:11 抓到的是橙色；9 秒内连抓 9 帧颜色不变，
# 说明也不是动画。
# 之前误把「蓝色」读成「已配置」（还把实跑失败帧当成了正样本），
# 于是**跳过了自动配置**，直接去点一个打不起来的「战斗开始」，
# 白等 45 秒后安全停止。**判据要落在「队伍真的被填上了」这件事上。**
TEAM_CONFIGURED_DETAIL = 700.0


def team_detail(
    screen: np.ndarray, *, reference_size=WORLD_BOSS_REFERENCE_SIZE
) -> float:
    """量队伍槽位区的画面细节量（拉普拉斯方差；越大越像「有头像」）。"""
    x0, y0, x1, y1 = TEAM_SLOTS_ROI
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    patch = screen[
        round(y0 * scale_y) : round(y1 * scale_y),
        round(x0 * scale_x) : round(x1 * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def team_configured(screen: np.ndarray) -> bool:
    """三队是否**真的**已经配好（槽位里有英雄，而不是空描边）。

    这是配置队伍页的**验收依据**：点了「自动配置」之后，只有当它变 True
    才允许推进到「战斗开始」—— 也就是「按一次、验收一次」。
    """
    return team_detail(screen) >= TEAM_CONFIGURED_DETAIL


# 战斗画面右上角「跳过 」的搜索区（画布坐标）。
# ⚠️ 这个**窗口宽度就是锚点的一部分**，别放大成整条右上角：
# 「跳过」这个图形与剧情播放页的跳过是同一个，但两页里它出现的位置不同
# （世界首领战 x≈1581~1682，剧情播放页 x≈1769~1886）。窗口收到 x<1760 之后，
# 剧情页从 0.8585 掉到 0.2803，而真实战斗帧仍是 0.9086 —— 间距 0.63。
BATTLE_SKIP_REGION = (1500, 55, 260, 110)

# 「跳过」阈值。全库 192 张夹具实测（`runtime_logs/_wb_battle_anchor_probe.py`）：
# 真实战斗帧 0.9086、boss 技能演出帧 0.2529（UI 整块隐藏，预期不命中）、
# 本路线其它页最高 0.3607（knights_signin_popup）、跨路线最高 0.3815。
# ⇒ 0.80 下方余量 0.44，上方余量 0.11。
BATTLE_SKIP_THRESHOLD = 0.80


def find_world_boss_skip(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
) -> Optional[Match]:
    """在战斗画面右上角找「跳过 」。命中返回 Match（中心即点击点），否则 None。"""
    return find_template(
        screen,
        template,
        BATTLE_SKIP_THRESHOLD,
        region=BATTLE_SKIP_REGION,
        reference_size=reference_size,
    )


def world_boss_battle_visible(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size=WORLD_BOSS_REFERENCE_SIZE,
) -> bool:
    """这一帧是不是「世界首领战的战斗画面」。

    两条独立判据取或：

    - ``battle_scene_visible``：竞技场/远征那套「4 格底座 + 左侧行动顺序」布局
      （世界首领战的某种演出帧会命中这里）；
    - 右上角「跳过 」命中：世界首领战团本布局的**唯一稳定锚点**
      （`battle_scene_visible` 在这种帧上恒为 False，见模块 docstring）。
    技能演出帧两条都不命中是**预期行为**：那种帧 UI 整块隐藏，靠下一帧复位看门狗。
    """
    if battle_scene_visible(screen):
        return True
    return find_world_boss_skip(screen, template) is not None


@dataclass(frozen=True)
class WorldBossAction:
    """世界首领战的一个动作，**必须声明出处与去处**。

    ``source_page`` / ``target_pages`` 是主循环的转场契约（见
    ``runner_base.ModeRunnerBase._transition_completed``）：发出动作 = 声明
    「我现在确认站在 source_page，点完之后应该到 target_pages」，
    下一帧主循环拿 ``machine._confirmed_page`` 与它对账。

    ⚠️ 2026-09-22 之前这个类只有 ``name`` + ``point``，于是主循环**点完不回头验收**，
    表现就是「进入配置队伍页的同一秒直接点战斗开始」——中间该不该先点自动配置、
    点了到底生效没有，程序毫无概念，一路蒙到战斗画面认不出才被兜住。
    """

    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class WorldBossTemplates:
    knights_title: np.ndarray
    worldboss_title: np.ndarray
    select_team_button: np.ndarray
    team_select_title: np.ndarray
    team_config_auto: np.ndarray
    level_reward_title: np.ndarray
    result_title: np.ndarray
    # 战斗画面右上角的「跳过 」（点它衔接到结算页，也是战斗画面的识别锚点）。
    battle_skip: np.ndarray
    stamina_popup: np.ndarray
    stamina_material: np.ndarray
    stamina_confirm: np.ndarray
    threshold: float = 0.80
    evidence: object = None


def build_world_boss_templates(
    template_dir: Path,
    *,
    backend: str = "emulator",
) -> WorldBossTemplates:
    template_root = template_dir.parent

    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return WorldBossTemplates(
        knights_title=load("knights_title"),
        worldboss_title=load("worldboss_title"),
        select_team_button=load("select_team_button"),
        team_select_title=load("team_select_title"),
        team_config_auto=load("team_config_auto"),
        level_reward_title=load("level_reward_title"),
        result_title=load("result_title"),
        battle_skip=load("battle_skip"),
        **asdict(load_stamina_templates(template_root / "story")),
        evidence=build_world_boss_evidence(template_dir),
    )


# evidence 页面键 -> 状态机状态。判定顺序就是这个元组的顺序。
_PAGE_STATES = (
    ("world_boss.level_reward", WorldBossState.LEVEL_REWARD),
    ("world_boss.result", WorldBossState.RESULT),
    ("world_boss.team_select", WorldBossState.TEAM_SELECT),
    ("world_boss.team_config", WorldBossState.TEAM_CONFIG),
    ("world_boss.home", WorldBossState.HOME),
)


class WorldBossStateMachine:
    """世界首领战一轮循环的纯视觉决策。

    页面识别统一走 ``evidence/world_boss.py`` 的页面组合（六个锚点已做过全库排他性
    扫描），状态机不再自己写「靠上下文猜这是哪一页」的判据 —— 那种判据在
    「状态拨错」时不会自愈，只会卡到超时。
    """

    _REFERENCE_SIZE = WORLD_BOSS_REFERENCE_SIZE
    _THRESHOLD = 0.80
    _REGIONS = {
        "knights_title": (0, 30, 500, 180),
        "worldboss_title": (0, 30, 500, 180),
        "select_team_button": (1450, 990, 532, 130),
        "team_select_title": (0, 140, 520, 140),
        "team_config_auto": (100, 1000, 300, 110),
        "level_reward_title": (600, 120, 800, 160),
        "result_title": (1400, 50, 400, 110),
        **STAMINA_REGIONS,
    }

    def __init__(
        self,
        templates: WorldBossTemplates | Path,
        *,
        initial_state: WorldBossState = WorldBossState.HOME,
        backend: str = "emulator",
    ) -> None:
        self.backend = backend
        self.templates = (
            build_world_boss_templates(templates, backend=backend)
            if isinstance(templates, Path)
            else templates
        )
        self.state = initial_state
        if self.templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in self.templates.evidence.atoms.items()
            }
            self._REGIONS.update(STAMINA_REGIONS)
            self._THRESHOLD = min(
                atom.threshold for atom in self.templates.evidence.atoms.values()
            )
        self.completed_cycles = 0
        self.stamina_replenished = 0
        self.auto_click_attempted = False
        self._confirmed_page = ""
        self._stamina_material_clicked = False

    def _confirm_page(self, page: str) -> None:
        """记下「我发出这个动作时确认站在哪一页」。

        主循环 ``runner_base`` 靠这个字段对账转场契约：``_transition_completed``
        要求 ``_confirmed_page ∈ action.target_pages``。不写这个字段，
        所有 ``target_pages`` 都是空转（2026-09-22 之前就是这个状态）。
        """
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        *,
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        point: tuple[int, int] | None = None,
    ) -> WorldBossAction:
        """构造动作并登记出处，确保转场契约有对账依据。

        ``target_pages`` 默认空 = 「这个动作不换页」。⚠️ 同页动作**不要**写
        ``target_pages=(本页,)``：那样 ``_transition_completed`` 永远返回 True，
        验收形同虚设，分不出「点了没生效」和「点了生效了」。

        ``point`` 为 None 时按 ``CLICK_POINTS`` 查表；调用方也可显式传坐标
        （体力弹窗的两个步骤的坐标是运行期算出来的，不在表里）。
        """
        self._confirm_page(source_page)
        return WorldBossAction(
            name=name,
            point=point if point is not None else CLICK_POINTS[name],
            source_page=source_page,
            target_pages=target_pages,
            reason=reason,
        )

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        template = getattr(self.templates, name, None)
        if template is None:
            return None
        return find_template(
            screen,
            template,
            self._THRESHOLD,
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def battle_visible(self, screen: np.ndarray) -> bool:
        """这一帧是不是世界首领战的战斗画面（含右上角「跳过」锚点）。"""
        return world_boss_battle_visible(screen, self.templates.battle_skip)

    def observe_page(self, screen: np.ndarray) -> Optional[WorldBossState]:
        """按 evidence 页面组合认出当前是哪一页，认不出返回 None。

        判定顺序即 ``_PAGE_STATES`` 的顺序：先判弹窗（奖励 / 结算，它们会盖住底页），
        再判业务页。页面组合之间已经实测互斥（见 ``evidence/world_boss.py``）。

        ⚠️ **战斗页不是模板页，是算出来的**：战斗演出没有稳定标题可裁模板，靠
        ``battle_controls.battle_scene_visible``（右上控制区 + 左侧行动顺序两条
        独立锚点）判断。它必须排在最前 —— 战斗画面上残留的上一页 UI 不该赢过它。
        没有这一步，「战斗开始」的转场契约（target=战斗中）**永远等不到目标**，
        主循环只能靠 45 秒超时收场，表现就是「点完不看结果、盲目重试」。

        ⚠️ 2026-09-22 起再加一条判据：右上角「跳过」。世界首领战的战斗画面是团本
        布局，``battle_scene_visible`` 在它上面恒为 False —— 只靠它的话，整场战斗
        都认不出来，监督会以「战斗画面持续无法识别 45 秒」安全停止（实跑踩过）。
        """
        if self.battle_visible(screen):
            return WorldBossState.BATTLE

        profile = getattr(self.templates, "evidence", None)
        if profile is None:
            return None
        flags = {
            key: self._locate(screen, key) is not None for key in profile.atoms
        }
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    def _handle_stamina(self, screen: np.ndarray) -> Optional[WorldBossAction]:
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "idle":
            if self._stamina_material_clicked:
                self.stamina_replenished += 1
                self._stamina_material_clicked = False
            return None
        # 体力弹窗的两个步骤都在弹窗内完成、**不换页**，所以不声明 target_pages：
        # 同页契约会永远验收通过（见 TEAM_CONFIG 分支的说明），形同虚设。
        # 验收依据是**弹窗自身的锚点**：弹窗还在 ⇒ next_action 继续返回该动作，
        # 按 45 秒窗口有界重试；弹窗消失 ⇒ 自然回到原页继续。
        if decision.status == "material":
            self._stamina_material_clicked = True
            return self._action(
                "stamina_material",
                point=decision.point,
                source_page="行动力不足弹窗",
                reason="选生命之叶卡片",
            )
        if decision.status == "waiting":
            raise StaminaExhausted("生命之叶购买按钮不可用")
        return self._action(
            "stamina_confirm",
            point=decision.point,
            source_page="行动力不足弹窗",
            reason="点确认购买生命之叶",
        )

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = observe_battle_controls(screen)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        result_visible = (
            self._locate(screen, "result_title") is not None
            and self._locate(screen, "level_reward_title") is None
        )
        # 右上角「跳过」：既是「我在战斗画面」的锚点，也是把这一局推向结算的动作。
        # 交给监督去点（``allowed_action``），而不是在观察函数里直接点 ——
        # 监督有「点 4 次没进展就算失败」的有界重试账本，观察函数没有。
        skip = find_world_boss_skip(screen, self.templates.battle_skip)
        return BattleObservation(
            pre_battle_visible=self._locate(screen, "team_select_title") is not None,
            battle_visible=battle_scene_visible(screen) or skip is not None,
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_evidence=f"布局={controls.value} 自动关图标=未使用(世界首领战默认自动)",
            auto_point=None,
            business_progress=(
                auto_state is AutoBattleState.AUTO
                and meaningful_change(previous_screen, screen)
            ),
            allowed_action=None if skip is None else ("skip-battle", skip.center),
            pre_battle_business_visible=self._locate(screen, "stamina_popup") is not None,
        )

    def next_action(self, screen: np.ndarray) -> Optional[WorldBossAction]:
        stamina = self._handle_stamina(screen)
        if stamina is not None:
            return stamina

        page = self.observe_page(screen)

        if page is WorldBossState.LEVEL_REWARD:
            self.state = WorldBossState.LEVEL_REWARD
            # 「全部开启」点完按钮原地换成「确认」，**不换页** ⇒ 不声明 target_pages
            # （同页契约会永远验收通过）。此处实际由 Runner 的奖励弹窗流程接管
            # 那两次点击，状态机只负责报出「现在是奖励弹窗」。
            return self._action(
                "open-all-chests",
                source_page=state_label(WorldBossState.LEVEL_REWARD),
                reason="奖励弹窗「全部开启」",
            )

        if page is WorldBossState.RESULT:
            # 同一个「战斗结果」页，进来一次与从奖励弹窗回来一次要做的事不同：
            # 前者是「点确认弹奖励」，后者是「点确认回主页」。
            if self.state is WorldBossState.LEVEL_REWARD:
                self.state = WorldBossState.RESULT_CONFIRM
                return self._action(
                    "confirm-result",
                    source_page=state_label(WorldBossState.RESULT),
                    target_pages=(state_label(WorldBossState.HOME),),
                    reason="奖励已领完，回结算页点确认回主页",
                )
            self.state = WorldBossState.RESULT
            return self._action(
                "open-level-reward",
                source_page=state_label(WorldBossState.RESULT),
                target_pages=(state_label(WorldBossState.LEVEL_REWARD),),
                reason="结算页点确认弹出奖励",
            )

        if page is WorldBossState.TEAM_SELECT:
            self.state = WorldBossState.TEAM_SELECT
            return self._action(
                "build-team",
                source_page=state_label(WorldBossState.TEAM_SELECT),
                target_pages=(state_label(WorldBossState.TEAM_CONFIG),),
                reason="辅助队伍页点「组成战斗队伍」进配置队伍页",
            )

        if page is WorldBossState.TEAM_CONFIG:
            # 这一页要分两个阶段走，**不能进页就点战斗开始**：
            # ① 三队槽位还是空的 ⇒ 先点「自动配置」；
            # ② 槽位里已经有英雄了 ⇒ 才点「战斗开始」。
            #
            # 为什么只靠「槽位细节量」、不给 auto-configure 声明 target_pages：
            # 这一步**不换页**，目标页写本页的话，主循环的转场验收会永远通过
            # （confirmed_page 一直是「配置队伍」，落在 target_pages 里），
            # 「验收」就形同虚设 —— 分不出「点了没生效」与「点了生效了」。
            # 而**槽位被填上英雄**本身就是最直接的验收证据（画面状态）：
            # 还是空的 ⇒ next_action 仍返回 auto-configure，主循环按
            # ``_ACTION_RETRY_SECONDS``（45 秒）窗口有界重试；填满了就自然推进到
            # battle-start。这正是「按一次、验收一次」的落地方式。
            #
            # ⚠️ **判据必须落在「队伍真的被填上了」**，不能看按钮颜色 ——
            # 那颗按钮的橙/蓝与队伍配没配无关（2026-09-22 实跑踩坑，详见
            # ``TEAM_CONFIGURED_DETAIL`` 的注释）。
            self.state = WorldBossState.TEAM_CONFIG
            if not team_configured(screen):
                return self._action(
                    "auto-configure",
                    source_page=state_label(WorldBossState.TEAM_CONFIG),
                    reason="三队槽位为空=尚未自动配置",
                )
            return self._action(
                "battle-start",
                source_page=state_label(WorldBossState.TEAM_CONFIG),
                target_pages=(state_label(WorldBossState.BATTLE),),
                reason="三队槽位已填满=可以开战",
            )

        if page is WorldBossState.BATTLE:
            # 战斗画面 —— 这是「战斗开始」这个动作的**出口标志**（``target_pages`` 里
            # 写的「战斗中」），主循环 ``_transition_completed`` 靠它验收转场。
            #
            # ⚠️ **必须 ``_confirm_page``**：主循环是在**拍完这一帧、调 next_action
            # 之前**读 ``_confirmed_page`` 的，所以「我现在站在战斗中」这件事要被写下来，
            # 下一帧才能被读成「已到达目标页」。不写的话 target_pages 永远匹配不上
            # （``_confirmed_page`` 一直停在上一个动作的 source_page）⇒ 契约空转、
            # 45 秒后走「转场超时」。这正是 2026-09-22 之前 story 死过的那个坑。
            self.state = WorldBossState.BATTLE
            self._confirm_page(state_label(WorldBossState.BATTLE))
            return None

        if page is WorldBossState.HOME:
            self.state = WorldBossState.HOME
            return self._action(
                "open-team-select",
                source_page=state_label(WorldBossState.HOME),
                target_pages=(state_label(WorldBossState.TEAM_SELECT),),
                reason="主页点「选择队伍」进辅助队伍页",
            )

        # 战斗演出/过场：画面既不匹配任何已知页面，也不该乱点，等下一帧。
        if self.state is WorldBossState.BATTLE:
            return None
        # 认不出画面时清空对账依据：下一帧站在哪一页是未知的，拿旧页面去比对
        # 只会产生假契约（story 同样是清空后抛）。
        self._confirmed_page = ""
        raise UnrecognizedScreen(f"世界首领战画面[{state_label(self.state)}]未识别")

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self.stamina_replenished,
            self.auto_click_attempted,
            self._confirmed_page,
            self._stamina_material_clicked,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.stamina_replenished,
                self.auto_click_attempted,
                self._confirmed_page,
                self._stamina_material_clicked,
            ) = snapshot


class WorldBossRunner(ModeRunnerBase):
    """世界首领战固定循环 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "世界首领战"
    _TIMEOUT_SECONDS = {
        WorldBossState.HOME: 45,
        WorldBossState.TEAM_SELECT: 45,
        WorldBossState.TEAM_CONFIG: 45,
        WorldBossState.BATTLE: 120,
        WorldBossState.RESULT: 45,
        WorldBossState.LEVEL_REWARD: 45,
        WorldBossState.RESULT_CONFIRM: 45,
    }
    # 战斗入口与竞技场同构（``ArenaRunner`` 也是 ``_BATTLE_ENTRY_ACTION="battle-start"``
    # + ``_CLICK_BEFORE_BATTLE`` 默认 True）：
    # 主循环点「战斗开始」→ 立刻把这一局交给战斗监督，由监督一路跟到结算页。
    # 监督内部用 ``observe_battle`` 判「战斗已进入 / 已到结算」，不需要主循环
    # 再额外报一个「我看到战斗画面了」的动作 —— 那会把控制权在**战斗已开打之后**
    # 才交给监督，而监督要靠结算页才能正常退出，等于让它在一个看不到终点的
    # 画面上空转到超时（2026-09-22 实测）。
    _BATTLE_ENTRY_ACTION = "battle-start"
    _CLICK_BEFORE_BATTLE = True
    _SETTLED_BATTLE_STATE = None  # 战斗入口靠上面两条，不走「无动作直接移交」
    # 同一个配置队伍页上，打不起来的战斗**最多重来这么多次**，超过就安全停止。
    # 2 次足够覆盖真实场景（体力弹窗交还一次后，补叶、再点就能开打）。
    _MAX_BATTLE_ATTEMPTS = 2

    def __init__(
        self,
        machine: WorldBossStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery=recovery,
            recovery_gate=recovery_gate,
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(
                mode="world_boss",
                mode_label="世界首领战",
                # 「跳过」是**战斗内**动作，用的是 ``allowed_action`` 这条通道。
                # 默认那把尺子（3 秒重试 / 15 秒判失败）是给战前弹窗定的：真点下去
                # 一次没用就 15 秒收场，会把一场好端端的战斗判成失败。
                # 这里给足时间 —— 战斗本来就要几十秒，结算页才是真正的终点，
                # 跳过只是加速；即使跳过一直不生效，也要能自然等到结算页。
                allowed_action_retry_seconds=5,
                allowed_action_failure_seconds=90,
            ),
            now=self.now,
            sleep=sleep,
        )
        self._battle_attempts = 0

    def _state_label(self, state: WorldBossState) -> str:
        return state_label(state)

    def _apply_recovery_state(self) -> None:
        self.machine.state = WorldBossState.HOME
        # 恢复导航已经把画面换掉了，旧的「已确认页面」作废 —— 留着会让主循环
        # 拿过期页面去对账转场契约（story 的 _apply_recovery_state 同样清空）。
        self.machine._confirmed_page = ""

    def _run_committed_battle(self, *, cycle: int) -> BattleOutcome:
        """把已确认开打的这一局交给战斗监督，直到结算。

        返回 ``BattleOutcome`` 供主循环判断：``PRE_BATTLE_BUSINESS`` 表示战斗
        **没打起来**（又冒出战前业务弹窗，通常是体力不足），主循环会走有界重试。
        """
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = WorldBossState.TEAM_CONFIG
            return outcome
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"世界首领战战斗出现意外结果：{outcome.value}")
        self.machine.state = WorldBossState.RESULT
        return outcome

    def _on_battle_handoff_failed(self, action: WorldBossAction, screen) -> bool:
        """「战斗开始」点了却没进战斗 ⇒ 有界重试，超限则安全停止。

        与竞技场 / 主线一致：打不起来**不是**「页面没认出来」，而是一个明确的
        业务失败 —— 记日志、留诊断、正常停止，绝不无限重交。
        """
        self._battle_attempts += 1
        if self._battle_attempts <= self._MAX_BATTLE_ATTEMPTS:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 战斗未开启 "
                f"尝试={self._battle_attempts}/{self._MAX_BATTLE_ATTEMPTS} "
                "判断依据=点「战斗开始」后战斗画面未出现 "
                "动作=回配置队伍页重新确认队伍"
            )
            # 回到配置队伍页重新走一遍（两阶段判定会再验一次按钮颜色）。
            self.machine.state = WorldBossState.TEAM_CONFIG
            self.machine._confirmed_page = ""
            return False
        diagnostic = self.runtime.save_diagnostic("battle_start_never_entered", screen)
        self._save_failure_diagnostic(
            diagnostic,
            screen,
            action=action,
            attempt=self._battle_attempts,
            conclusion="多次点击战斗开始后战斗画面始终未出现",
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 停止=战斗始终未开启 "
            f"尝试={self._battle_attempts}次 现场={diagnostic}"
        )
        raise RuntimeError(
            f"点「战斗开始」{self._battle_attempts} 次仍未进入战斗；"
            f"已安全停止并保存诊断 {diagnostic}"
        )

    def _on_battle_started(self) -> None:
        """这一局真的打起来了 ⇒ 重试账本清零（下一局重新计数）。"""
        self._battle_attempts = 0

    def _on_action_exhausted(self, action: WorldBossAction, screen) -> bool:
        if action.name == "stamina_confirm":
            self.resource_exhausted = True
            self.runtime.log("模式=世界首领战 停止=生命之叶确认多次未生效")
            return True
        return False
