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
from auto_game_unified.core.matcher import (
    MATCH_MODE_WHITE_MASK,
    Match,
    find_template,
    load_template,
    locate_with_fallback,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
    resolve_auto_state,
)
from auto_game_unified.games.epic7.pre_battle import (
    PreBattleMode,
    QuickBattleDetector,
    load_simulator_quick_battle_detector,
    observe_pre_battle,
)
# 友情点数弹窗识别已迁至全局弹窗守卫（global_popups），此处**保留导出以兼容旧引用**
# （tests/test_epic7_story.py 就是按 ``story_module.find_friendship_points_popup_close``
# 取的）⇒ 它在本模块里「没人用」是**故意的**，别让 ruff 的 F401 把它删掉。
# 2026-09-30 实测被删过一次：那条自动修复把这行注释上方的导入一起删了，
# 于是注释悬空、测试当场红（自动修复不认识「再导出」这种用法）。
from auto_game_unified.games.epic7.global_popups import (  # noqa: F401
    find_friendship_points_popup_close,
)
from auto_game_unified.games.epic7.stamina import (
    load_stamina_templates,
    next_stamina_decision,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.story import (
    BATTLE_GUIDE_DONT_SHOW_REGION,
    BATTLE_GUIDE_TITLE_REGION,
    REFERENCE_SIZE as STORY_REFERENCE_SIZE,
    REGIONS as STORY_REGIONS,
    THRESHOLDS as STORY_THRESHOLDS,
    STORY_SKIP_CONFIRM_REGION,
    STORY_SKIP_REGION,
    WATCH_STORY_REGION,
    build_story_evidence,
)


_WATCH_STORY_REFERENCE_SIZE = STORY_REFERENCE_SIZE
_WATCH_STORY_REGION = WATCH_STORY_REGION
_STORY_SKIP_REGION = STORY_SKIP_REGION
_STORY_SKIP_CONFIRM_REGION = STORY_SKIP_CONFIRM_REGION
_BATTLE_GUIDE_TITLE_REGION = BATTLE_GUIDE_TITLE_REGION
_BATTLE_GUIDE_DONT_SHOW_REGION = BATTLE_GUIDE_DONT_SHOW_REGION

# 布局判据 → 自动战斗状态。2026-11-07 抽成模块级常量：PC 分支要用「图标合并后」
# 的那份控制值再查一次表，两处查同一张，避免长出第二份复制粘贴。
_AUTO_STATE_BY_CONTROLS = {
    BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
    BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
    BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
}


def find_battle_guide_dont_show(
    screen: np.ndarray,
    title_template: np.ndarray,
    dont_show_template: np.ndarray,
    threshold: float = 0.85,
) -> Optional[Match]:
    """Return Don't Show only when both battle-guide anchors exist."""
    lower = np.array([0, 0, 150])
    upper = np.array([179, 100, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
        ref_x, ref_y, ref_width, ref_height = region
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
        )
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            threshold,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(title_template, _BATTLE_GUIDE_TITLE_REGION)
    dont_show = locate(dont_show_template, _BATTLE_GUIDE_DONT_SHOW_REGION)
    if title is None or dont_show is None:
        return None
    return Match(dont_show.center, min(title.score, dont_show.score))


def find_watch_story_button(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.72,
) -> Optional[Match]:
    """Find the white watch-story glyph without depending on stage artwork."""
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    x, y, width, height = _WATCH_STORY_REGION
    x, y, width, height = (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
    lower = np.array([0, 0, 150])
    upper = np.array([179, 90, 255])
    match = find_template(
        cv2.inRange(search_hsv, lower, upper),
        cv2.inRange(template_hsv, lower, upper),
        threshold,
        reference_size=(_WATCH_STORY_REGION[2], _WATCH_STORY_REGION[3]),
    )
    if match is None:
        return None
    return Match((x + match.center[0], y + match.center[1]), match.score)


def find_prepare_battle_button(
    screen: np.ndarray,
    primary_template: np.ndarray,
    updated_template: np.ndarray | tuple[np.ndarray, ...],
    threshold: float = 0.90,
) -> Optional[Match]:
    """Find the stable white button glyph without depending on stage artwork.

    ``updated_template`` 允许是一组候选：PC 客户端把同一颗「准备战斗」按钮画成过
    两套外观（2026-11-04 实测同一帧上甲图 1.0000 / 乙图 0.8515，换一批帧反过来），
    单一模板必然在其中一批帧上掉到 0.90 以下。任一候选过阈即命中，取最高分；
    阈值与「白掩膜口径」都不变。
    """
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    x, y, width, height = _WATCH_STORY_REGION
    x, y, width, height = (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    lower = np.array([0, 0, 150])
    upper = np.array([179, 90, 255])
    search_mask = cv2.inRange(search_hsv, lower, upper)
    updated = (
        (updated_template,)
        if isinstance(updated_template, np.ndarray)
        else tuple(updated_template)
    )
    matches = []
    for template in (primary_template, *updated):
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            search_mask,
            cv2.inRange(template_hsv, lower, upper),
            threshold,
            reference_size=(_WATCH_STORY_REGION[2], _WATCH_STORY_REGION[3]),
        )
        if match is not None:
            matches.append(match)
    if not matches:
        return None
    best = max(matches, key=lambda candidate: candidate.score)
    return Match((x + best.center[0], y + best.center[1]), best.score)


def find_start_mission_button(
    screen: np.ndarray,
    primary_template: np.ndarray,
    updated_template: np.ndarray,
    threshold: float,
    region: tuple[int, int, int, int],
    reference_size: tuple[int, int],
) -> Optional[Match]:
    """队伍准备页那颗开始按钮换过皮，两个模板都试，取分高的那个。

    旧皮是橙底「进行任务」（`start_mission.png`），2026-09-17 起是绿底「战斗开始」
    （`start_mission_updated.png`）——旧模板在新画面上只有 0.36。两个模板**共用
    start_mission 的阈值**，不许给新模板单独放宽，否则等于偷偷降低判据。
    """
    matches = []
    for template in (primary_template, updated_template):
        match = find_template(
            screen, template, threshold, region=region, reference_size=reference_size
        )
        if match is not None:
            matches.append(match)
    if not matches:
        return None
    return max(matches, key=lambda candidate: candidate.score)


def find_story_skip_button(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.65,
) -> Optional[Match]:
    """Find the bright skip glyph without depending on story artwork."""
    scale_x = screen.shape[1] / _WATCH_STORY_REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / _WATCH_STORY_REFERENCE_SIZE[1]
    ref_x, ref_y, ref_width, ref_height = _STORY_SKIP_REGION
    x, y, width, height = (
        round(ref_x * scale_x),
        round(ref_y * scale_y),
        round(ref_width * scale_x),
        round(ref_height * scale_y),
    )
    search_hsv = cv2.cvtColor(
        screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
    )
    template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
    lower = np.array([0, 0, 120])
    upper = np.array([179, 70, 255])
    match = find_template(
        cv2.inRange(search_hsv, lower, upper),
        cv2.inRange(template_hsv, lower, upper),
        threshold,
        reference_size=(ref_width, ref_height),
    )
    if match is None:
        return None
    return Match((x + match.center[0], y + match.center[1]), match.score)


def find_story_skip_confirm(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.80,
) -> Optional[Match]:
    """Find the explicit story-skip confirmation button."""
    return find_template(
        screen,
        template,
        threshold,
        region=_STORY_SKIP_CONFIRM_REGION,
        reference_size=_WATCH_STORY_REFERENCE_SIZE,
    )


class StoryState(Enum):
    STAGE = "stage"
    TEAM = "team"
    WAIT_SKIP_CONFIRM = "wait_skip_confirm"
    WAIT_BATTLE = "wait_battle"
    ACTIVE = "active"
    WAIT_RESULTS = "wait_results"
    WAIT_COMPLETE = "wait_complete"
    WAIT_NEXT_STAGE = "wait_next_stage"


class StageTooHard(StaminaExhausted):
    """这一关打不过（战斗 FAILED 结算页）= **正常业务退出**，不是故障。

    与月塔 ``FloorTooHard`` 同一口径：继承 ``StaminaExhausted`` 借退出码 2，
    不点「重新进行 / 继续战斗」重打、不点大厅，收尾照常回首页衔接下一条路线。
    2026-11-06 17:15 主线实跑把这个页面报成 ``battle_unrecognized`` 故障，
    根因是战斗监督的 ``result_visible`` 三选一里没有战败结算页。
    """

    stop_label = "主线这一关打不过"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    StoryState.STAGE: "关卡入口",
    StoryState.TEAM: "队伍选择",
    StoryState.WAIT_SKIP_CONFIRM: "跳过确认",
    StoryState.WAIT_BATTLE: "等待战斗",
    StoryState.ACTIVE: "战斗进行中",
    StoryState.WAIT_RESULTS: "等待结算",
    StoryState.WAIT_COMPLETE: "等待通关",
    StoryState.WAIT_NEXT_STAGE: "等待下一关",
}


def state_label(state: StoryState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class StoryAction(RouteAction):
    """主线的一个动作。

    ``source_page`` / ``target_pages`` 是**无默认值的必填参数**（在 ``_action()`` 里统一构造），
    所以这条路线不需要打开 ``_REQUIRE_TRANSITION_CONTRACT`` —— 漏填直接 ``TypeError``，
    比开关更硬（见 ``modes.TRANSITION_EXEMPT``）。
    """

    source_state: StoryState | None = None
    target_states: tuple[StoryState, ...] = ()


@dataclass(frozen=True)
class StoryTemplates:
    battle_guide_title: np.ndarray
    battle_guide_dont_show: np.ndarray
    watch_story: np.ndarray
    prepare_battle: np.ndarray
    # 「准备战斗」按钮的换皮版。PC 客户端还有第二套渲染（2026-11-04 下午那批帧），
    # 两张互为候选：甲图在上午帧 1.0000 / 下午帧 0.8515，乙图正好反过来。
    # 阈值与白掩膜口径一律不变，只是让任一套外观都能过阈。
    # ⚠️ 第一张永远存在（模拟器和 PC 都有），第二张只在 PC 放图时才追加，
    # 所以这不是「可选判据」，判据不会静默降级。
    prepare_battle_updated: tuple[np.ndarray, ...]
    select_team: np.ndarray
    start_mission: np.ndarray
    # 2026-09-17 游戏把这颗按钮换了皮（橙「进行任务」→ 绿「战斗开始」），
    # 旧模板在新画面上只有 0.36。两个都留着，命中哪个用哪个。
    start_mission_updated: np.ndarray
    skip: np.ndarray
    skip_confirm: np.ndarray
    auto_off: np.ndarray
    auto_on: np.ndarray
    reward: np.ndarray
    clear: np.ndarray
    results_confirm: np.ndarray
    complete: np.ndarray
    bonus_reward: np.ndarray
    next_stage: np.ndarray
    # 「重复打同一关」那页的右下角按钮（「无法前往下一个关卡，请选择下方按钮」）。
    retry_stage: np.ndarray
    # 2026-11-04 加：PC 端「完成故事」弹窗的底部「点击关闭」标签。**只作点击目标、
    # 不参与判据**（判据只看 ``complete`` 文案）。PC 端弹窗布局与模拟器不同，``complete``
    # 模板中心落在奖励图标上、点了没反应；改用这枚标签的真实位置才点得动。
    # ⚠️ 可选：模拟器没有这枚 PC 覆盖图 ⇒ 载入为 ``None``，``_action_point`` 原样回落
    # ``match.center``（模拟器零改动）。
    complete_close: Optional[np.ndarray] = None
    # 战斗 FAILED 结算页判据。**PC-only，且复用月塔那张图**（同一套战败 UI，
    # 不另存第二份）。模拟器为 None ⇒ 整条 FAILED 分支不启用，行为零改动。
    # 只用于「打不过就正常收工」，不参与任何点击点。
    battle_failed: Optional[np.ndarray] = None
    threshold: float = 0.80
    stamina_popup: Optional[np.ndarray] = None
    stamina_material: Optional[np.ndarray] = None
    stamina_confirm: Optional[np.ndarray] = None
    quick_battle: QuickBattleDetector | None = None
    evidence: EvidenceProfile | None = None


def _load_prepare_battle_updated(template_dir) -> tuple[np.ndarray, ...]:
    """「准备战斗」按钮：主图必载，PC 的第二套渲染图存在才追加为候选。

    放在 ``pc/`` 子目录里，模拟器解析到的是共享路径下不存在的同名文件，
    ``is_file()`` 为假 ⇒ 只有主图一张，行为与改动前逐字节一致。
    """
    primary = load_template(str(template_dir / "prepare_battle_updated.png"))
    alt = template_dir / "prepare_battle_updated_alt.png"
    if not Path(alt).is_file():
        return (primary,)
    return (primary, load_template(str(alt)))


def _load_complete_close(template_dir) -> Optional[np.ndarray]:
    """PC 端「点击关闭」标签：覆盖图存在才载入，否则返回 ``None``。

    模拟器没有这枚 PC 覆盖图，于是 ``complete`` 动作的点击点原样回落
    ``match.center``（模拟器零改动）。``template_dir`` 可能是 ``TemplateDir``
    （PC 后端会指到 ``story/pc/complete_close.png``），``.is_file()`` 两种都适用。
    """
    candidate = template_dir / "complete_close.png"
    if not Path(candidate).is_file():
        return None
    return load_template(str(candidate))


def _load_battle_failed(template_dir) -> Optional[np.ndarray]:
    """PC 主线的战败结算页判据：**复用月塔那张 ``tower/battle_failed.png``**。

    月塔 2026-10-31 就为同一套「FAILED 大字 + 上下装饰线」建了这张图，
    白掩膜口径在别处最高 0.22。主线 2026-11-06 17:15 的 FAILED 帧上实测
    0.9811，全库 386 张夹具反例最高 0.2748、主线 38 张战斗/诊断帧除正例外
    最高 0.1888 —— 这是**同一个游戏 UI**，没必要再存一份需要同步的副本。

    ⚠️ 只在 PC 后端加载：模拟器拿普通 ``Path`` / ``backend=emulator``，
    ``is_pc`` 为假 ⇒ 返回 None ⇒ ``_battle_failed()`` 恒为 None ⇒
    ``observe_battle`` / ``next_action`` / 接力三处全部原样，零改动。
    """
    from auto_game_unified.games.epic7.template_paths import is_pc

    if not is_pc(template_dir):
        return None
    candidate = template_dir.parent / "tower" / "battle_failed.png"
    if not Path(candidate).is_file():
        return None
    return load_template(str(candidate))


def build_story_templates(template_dir: Path) -> StoryTemplates:
    """主线模板。阈值只有模拟器基线一套；平台差异收敛到图片。"""
    evidence = build_story_evidence(template_dir)
    return StoryTemplates(
        battle_guide_title=load_template(str(template_dir / "battle_guide_title.png")),
        battle_guide_dont_show=load_template(
            str(template_dir / "battle_guide_dont_show.png")
        ),
        watch_story=load_template(str(template_dir / "watch_story.png")),
        prepare_battle=load_template(str(template_dir / "prepare_battle.png")),
        prepare_battle_updated=_load_prepare_battle_updated(template_dir),
        select_team=load_template(str(template_dir / "select_team.png")),
        start_mission=load_template(str(template_dir / "start_mission.png")),
        start_mission_updated=load_template(
            str(template_dir / "start_mission_updated.png")
        ),
        skip=load_template(str(template_dir / "skip.png")),
        skip_confirm=load_template(str(template_dir / "skip_confirm.png")),
        auto_off=load_template(str(template_dir / "auto_off.png")),
        auto_on=load_template(str(template_dir / "auto_on.png")),
        reward=load_template(str(template_dir / "reward.png")),
        clear=load_template(str(template_dir / "clear.png")),
        results_confirm=load_template(str(template_dir / "results_confirm.png")),
        complete=load_template(str(template_dir / "complete.png")),
        bonus_reward=load_template(str(template_dir / "bonus_reward.png")),
        next_stage=load_template(str(template_dir / "next_stage.png")),
        retry_stage=load_template(str(template_dir / "retry_stage.png")),
        # 「点击关闭」标签：PC 覆盖图存在才载入，否则 ``None``（模拟器回落旧点）。
        complete_close=_load_complete_close(template_dir),
        # 战败结算页：PC 复用月塔的 FAILED 图；模拟器为 None，整条分支不启用。
        battle_failed=_load_battle_failed(template_dir),
        **asdict(load_stamina_templates(template_dir)),
        quick_battle=load_simulator_quick_battle_detector(template_dir),
        threshold=evidence.atom("start_mission").threshold,
        evidence=evidence,
    )


class StoryStateMachine:
    """Story workflow in the game window's local coordinate space."""

    _THRESHOLDS = STORY_THRESHOLDS
    _REFERENCE_SIZE = STORY_REFERENCE_SIZE
    _REGIONS = STORY_REGIONS
    _BONUS_REWARD_CLOSE_OFFSET = (0, 312)
    _AUTO_CLICK_POINT = (1690, 96)
    # PC「完成故事」弹窗底部「点击关闭」标签的搜索区。模板 150×50，区域留足
    # 余量让它在 (965,770) 附近滑到真中心；实测该帧 1.0000 @ (965,770)。
    _COMPLETE_CLOSE_REGION = (820, 700, 270, 140)
    # 战斗 FAILED 结算页：居中的「FAILED」大字 + 上下装饰线，与月塔是同一套 UI。
    # region / 阈值 / 白掩膜口径三项必须与 evidence/tower.py::battle_failed 一致，
    # 否则「同一张图在两条路线上两个结论」。
    _BATTLE_FAILED_REGION = (950, 180, 700, 220)
    _BATTLE_FAILED_THRESHOLD = 0.88

    def __init__(
        self,
        templates: StoryTemplates,
        initial_state: StoryState = StoryState.STAGE,
        *,
        pc_rules: bool = False,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        # PC 专属规则开关：由装配点（``modes.py::_build_story``）按模板目录注入。
        #
        # 默认 **False** ⇒ 模拟器走 2026-11-07 之前的原代码路径，行为一个字节不变。
        # 只有改成 True 的三处（自动战斗判定 / 点击点 / 「点自动」的页面名）走新逻辑。
        #
        # ⚠️ 为什么用开关而不是补图：这三处**没有图可补** —— 前两处是判据合并策略、
        # 第三处是程序内部的字符串常量，跟"认不认得出"无关。而项目 `§4.2` 禁止的是
        # 「散落各处的阈值分叉」（七个 evidence 各一张表那种），这里是**单点注入的
        # 一个开关**，装配点只有 `modes.py` 一处，与既有的
        # 「`complete_close` 只有 PC 载到才动 `_REGIONS`」是同一类受控例外。
        #
        # ⚠️ 继承本类的 `ActivityStoryStateMachine` / `SideStoryStateMachine`
        # **暂未接入**（它们的 `build_*_machine` 没传这个参数 ⇒ 恒为 False ⇒
        # PC 上也走原逻辑）。那两条路线 2026-11-07 没有报错证据，按「精准修改」
        # 不做超范围改动；将来它们真在 PC 上撞到同一个坑，只需在各自的
        # `build_*_machine` 里补一行 `pc_rules=is_pc(template_dir)`。
        self._pc_rules = pc_rules
        if templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in templates.evidence.atoms.items()
            }
            self._THRESHOLDS = {
                key: atom.threshold for key, atom in templates.evidence.atoms.items()
            }
        # 「点击关闭」是**纯点击目标**，不是证据原子（不参与判据），所以不能从
        # evidence 里取它的搜索区，要单独登记。
        # ⚠️ 只有 PC 真的载到这枚覆盖图时才动 ``self._REGIONS``：模拟器保持改动前
        # 的字典（类属性 STORY_REGIONS / evidence 生成的那份）一个字节不变，
        # 连多一个 key 都不行 —— 这是「完全不碰模拟器」的口径。
        if templates.complete_close is not None:
            self._REGIONS = dict(self._REGIONS)
            self._REGIONS["complete_close"] = self._COMPLETE_CLOSE_REGION
        self.auto_enabled = False
        self.auto_click_attempted = False
        self.battle_controls = BattleControls.TRANSITION
        self.completed_cycles = 0
        self.stamina_replenished = 0
        self.stamina_replenish_max: int | None = None
        self._stamina_material_clicked = False
        self._stamina_purchase_pending = False
        self._confirmed_page = ""
        # 「接力」进来的落点；None = 本轮是正常从关卡入口开始的。Runner 靠它判断
        # 「局内接力」要不要跳过状态机直接把这一局交给战斗监督。
        self.resumed_from: Optional[StoryState] = None

    def resume_from(self, state: StoryState) -> None:
        """拨到用户停下的那一步，原样接管进度继续往下跑。

        与「从头再来」的区别：接力是「保留当前进度」—— 比如停在通关提示就继续收奖励，
        而不是退回大厅把这一局的结算丢掉。（2026-09-26 之前另有一条「恢复导航」通道
        专门做「退回关卡入口重开一轮」，随用户「回家就是结束」的拍板整段删除。）

        战斗相关的标志一并复位：接力进来的这一局不是本进程点开的，
        ``battle_controls`` 要从 TRANSITION 重新观测，``auto_click_attempted``
        也不能带着上一局的账本（否则第一次观察就会跳过自动战斗点击）。
        """
        self.state = state
        self.resumed_from = state
        self.auto_enabled = False
        self.auto_click_attempted = False
        self.battle_controls = BattleControls.TRANSITION
        self._confirmed_page = ""

    def _confirm_page(self, page: str) -> None:
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_pages: tuple[str, ...],
        reason: str,
        target_states: tuple[StoryState, ...] = (),
    ) -> StoryAction:
        self._confirm_page(source_page)
        return StoryAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            reason=reason,
            source_state=self.state,
            target_states=target_states,
        )

    def commit(self, action: StoryAction, target: StoryState) -> None:
        """Commit a declared target only after the runner has observed it stable."""
        if action.source_state is not None and action.source_state is not self.state:
            raise RuntimeError("主线转场来源状态已变化，拒绝提交旧动作")
        if target not in action.target_states:
            raise RuntimeError("主线转场目标不在动作契约中")
        self.state = target

    def action_clicked(self, action: StoryAction) -> None:
        """Record click-side effects that must not happen during action preview."""
        if action.name == "stamina_material":
            self._stamina_material_clicked = True
        elif action.name == "stamina_confirm":
            self._stamina_material_clicked = False
            self._stamina_purchase_pending = True

    def _locate(self, screen: np.ndarray, name: str):
        """Match only the expected local UI region; never the desktop."""
        if name == "watch_story":
            return find_watch_story_button(
                screen,
                self.templates.watch_story,
                self._THRESHOLDS["watch_story"],
            )
        if name == "prepare_battle":
            return find_prepare_battle_button(
                screen,
                self.templates.prepare_battle,
                self.templates.prepare_battle_updated,
                self._THRESHOLDS["prepare_battle"],
            )
        if name == "start_mission":
            return find_start_mission_button(
                screen,
                self.templates.start_mission,
                self.templates.start_mission_updated,
                self._THRESHOLDS.get(name, self.templates.threshold),
                self._REGIONS[name],
                self._REFERENCE_SIZE,
            )
        if name == "skip":
            return find_story_skip_button(
                screen,
                self.templates.skip,
                self._THRESHOLDS["skip"],
            )
        if name == "skip_confirm":
            return find_story_skip_confirm(
                screen,
                self.templates.skip_confirm,
                self._THRESHOLDS["skip_confirm"],
            )
        if name in ("auto_off", "auto_on"):
            white = (np.array([180, 180, 180]), np.array([255, 255, 255]))
            x, y, width, height = self._scaled_region(screen, name)
            search_mask = cv2.inRange(screen[y : y + height, x : x + width], *white)
            template_mask = cv2.inRange(getattr(self.templates, name), *white)
            match = find_template(
                search_mask,
                template_mask,
                self._THRESHOLDS[name],
                reference_size=(self._REGIONS[name][2], self._REGIONS[name][3]),
            )
            if match is None:
                return None
            return Match((x + match.center[0], y + match.center[1]), match.score)
        # 走 ``locate_with_fallback``（与导航层、视觉诊断**同一把尺子**）：原样先比，
        # 不过阈才按 ``SMOOTH_FALLBACK_ANCHORS`` / ``SCALE_FALLBACK_ANCHORS`` 补一次。
        # 名字不在任何名单里时，这里的判定与从前逐字节一致。
        #
        # ⚠️ 2026-11-04：不改这一处的话，主线那两颗登记进缩放兜底名单的锚点
        # （``next_stage`` / ``stamina_material``）**根本走不到兜底** —— 名单是个开关，
        # 开关装在 `matcher` 上，而电流得从路线自己的定位入口流进去。
        # 名单里挂了名字却没人走这条路，症状就是「加了白名单还是认不出」，极难查。
        return locate_with_fallback(
            name,
            screen,
            getattr(self.templates, name),
            self._THRESHOLDS.get(name, self.templates.threshold),
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _scaled_region(self, screen: np.ndarray, name: str) -> tuple[int, int, int, int]:
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = self._REGIONS[name]
        return (
            round(x * scale_x), round(y * scale_y),
            round(width * scale_x), round(height * scale_y),
        )

    def _scaled_point(
        self, screen: np.ndarray, point: tuple[int, int]
    ) -> tuple[int, int]:
        return (
            round(point[0] * screen.shape[1] / self._REFERENCE_SIZE[0]),
            round(point[1] * screen.shape[0] / self._REFERENCE_SIZE[1]),
        )

    def observe_battle_controls(self, screen: np.ndarray) -> BattleControls:
        return observe_battle_controls(screen)

    def _battle_failed(self, screen: np.ndarray) -> Optional[Match]:
        """战败结算页判据。**只有一份实现**，监督 / 状态机 / 接力三处共用。

        PC 才载到模板；模拟器 ``battle_failed is None`` ⇒ 恒返回 None，
        三处消费方逐字节保持改动前的行为。
        """
        template = self.templates.battle_failed
        if template is None:
            return None
        return locate_with_fallback(
            "battle_failed",
            screen,
            template,
            self._BATTLE_FAILED_THRESHOLD,
            region=self._BATTLE_FAILED_REGION,
            reference_size=self._REFERENCE_SIZE,
            mode=MATCH_MODE_WHITE_MASK,
        )

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        controls = self.observe_battle_controls(screen)
        auto_match = self._locate(screen, "auto_off")
        auto_score = "无" if auto_match is None else f"{auto_match.score:.4f}"
        auto_state = _AUTO_STATE_BY_CONTROLS[controls]
        auto_evidence = f"布局={controls.value} 自动关图标={auto_score}"
        if self._pc_rules:
            # PC：图标（弱证据）只在布局看不出长相时才作数 —— 与月塔 / 远征 / 竞技场
            # 同一条规则（``resolve_auto_state`` 的 docstring，2026-10-09 月塔事故）。
            #
            # 2026-11-07 08:55 真机：布局明明判出 ``auto_controls``（四格底座全亮 =
            # 自动确实开着），图标却擦着阈值命中 0.8268 ⇒ 旧写法改判手动、同一分钟
            # 点了两次开关。PC 上这个图标比模拟器容易误命中：模拟器「自动开」帧实测
            # 0.0000，同一张共享模板在 PC 战斗帧上能到 0.80~0.93（全库 343 张
            # 「布局=自动开着」的帧里，出现这种组合的 15 张**全是 PC**）。
            resolved = resolve_auto_state(controls, auto_match is not None)
            auto_state = _AUTO_STATE_BY_CONTROLS[resolved]
            if resolved is not controls:
                auto_evidence += " 来源=右上角自动关闭图标"
        else:
            # 模拟器：保持 2026-11-07 之前的原逻辑（图标命中即改判手动）。
            if auto_match is not None:
                auto_state = AutoBattleState.MANUAL
                auto_evidence += " 来源=右上角自动关闭图标"
        stamina_popup = (
            self._locate(screen, "stamina_popup")
            if self.templates.stamina_popup is not None
            else None
        )
        start = self._locate(screen, "start_mission")
        pre_battle = observe_pre_battle(
            self.templates.quick_battle,
            screen,
            normal_start=start,
        )
        battle_guide = find_battle_guide_dont_show(
            screen,
            self.templates.battle_guide_title,
            self.templates.battle_guide_dont_show,
            self._THRESHOLDS["battle_guide_title"],
        )
        allowed_action = (
            ("dismiss-battle-guide-warning", battle_guide.center)
            if battle_guide is not None
            else None
        )
        if allowed_action is None:
            for action_name in ("skip_confirm", "skip", "watch_story"):
                match = self._locate(screen, action_name)
                if match is not None:
                    allowed_action = (action_name, match.center)
                    break
        if allowed_action is None:
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                allowed_action = (
                    "switch-to-normal-battle",
                    pre_battle.switch_point,
                )
            elif pre_battle.mode is PreBattleMode.NORMAL and start is not None:
                allowed_action = ("start_mission", start.center)
        progressing = (
            auto_state is AutoBattleState.AUTO
            and meaningful_change(previous_screen, screen)
        )
        battle_visible = battle_scene_visible(screen)
        result_visible = any(
            self._locate(screen, name) is not None
            for name in ("reward", "clear", "results_confirm")
        )
        if not result_visible and not battle_visible:
            # 战败结算页（FAILED）：画面已不是战斗场景，三选一结算锚点也全不命中
            # ⇒ 五项观察全假 ⇒ 监督干等 45 秒报 battle_unrecognized，把「打不过」
            # 这个正常业务退出写成故障（2026-11-06 17:15 主线实跑即此死法）。
            # 只在两项都假时补判：真战斗画面上一帧额外判据都不跑。
            result_visible = self._battle_failed(screen) is not None
        if self._pc_rules:
            # PC：**只有判成「手动」才需要点**，也才该给坐标 —— 与月塔 / 远征同一条
            # 口径（`tower.py` / `expedition.py` 的 `auto_point` 都带这个条件）。
            # 原先无条件给点：08:55 那帧已判成 AUTO，却仍带着 (1650,90)，
            # 一旦有消费方不看 auto_state 直接用坐标，就是又点了一下开关。
            auto_point = (
                (
                    auto_match.center
                    if auto_match is not None
                    else self._scaled_point(screen, self._AUTO_CLICK_POINT)
                )
                if auto_state is AutoBattleState.MANUAL
                else None
            )
        else:
            # 模拟器：保持 2026-11-07 之前的原写法（不看 auto_state，图标命中就给点）。
            auto_point = (
                auto_match.center
                if auto_match is not None
                else self._scaled_point(screen, self._AUTO_CLICK_POINT)
                if auto_state is AutoBattleState.MANUAL
                else None
            )
        return BattleObservation(
            pre_battle_visible=pre_battle.mode is not PreBattleMode.UNKNOWN,
            battle_visible=battle_visible,
            result_visible=result_visible,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=auto_point,
            business_progress=progressing,
            allowed_action=allowed_action,
            pre_battle_business_visible=stamina_popup is not None,
            auto_evidence=auto_evidence,
        )

    def _action_point(self, screen: np.ndarray, name: str, match: Match) -> tuple[int, int]:
        # 2026-11-04 PC 主线修复：``complete`` 判据（通关提示文案）过了，但点在
        # ``complete`` 模板中心（奖励图标）上，PC 客户端不认这一下，连点 4 次不推进。
        # 改为优先点弹窗底部「点击关闭」标签的真实位置；这枚标签**只决定点哪，
        # 不参与判据**（判据仍只看 ``complete``），与 global_popups 的既有模式一致。
        # 找不到标签（或模拟器没有 PC 覆盖图）就原样回落 ``match.center`` ——
        # 模拟器行为零改动。
        if name == "complete" and self.templates.complete_close is not None:
            close = self._locate(screen, "complete_close")
            if close is not None:
                return close.center
        if name != "bonus_reward":
            return match.center
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        return match.center[0], match.center[1] + round(self._BONUS_REWARD_CLOSE_OFFSET[1] * scale_y)

    def _handle_stamina(self, screen: np.ndarray) -> Optional[StoryAction]:
        """体力不足时用生命之叶补充；达到上限后抛 StaminaExhausted 干净收尾。

        与狗粮共用两段式决策（stamina.py），主线独有：
        补充次数上限、确认按钮未渲染时等待（返回 None）而非报错。
        """
        if self.templates.stamina_popup is None:
            return None
        if self._locate(screen, "stamina_popup") is None:
            self._stamina_material_clicked = False
            if self._stamina_purchase_pending:
                self.stamina_replenished += 1
                self._stamina_purchase_pending = False
            return None
        if (
            self.stamina_replenish_max is not None
            and self.stamina_replenished >= self.stamina_replenish_max
        ):
            raise StaminaExhausted(
                f"生命之叶已补充{self.stamina_replenished}次"
                f"（上限{self.stamina_replenish_max}次），停止运行"
            )
        if (
            self.templates.stamina_material is None
            or self.templates.stamina_confirm is None
        ):
            raise RuntimeError("体力弹窗已出现但缺少生命之叶补充模板")
        decision = next_stamina_decision(
            screen, self._locate, material_clicked=self._stamina_material_clicked
        )
        if decision.status == "material":
            return self._action(
                "stamina_material",
                decision.point,
                source_page="体力弹窗",
                target_pages=("体力弹窗（生命之叶已选中）",),
                reason="体力弹窗与生命之叶选项已识别",
            )
        if decision.status == "waiting":
            return None
        return self._action(
            "stamina_confirm",
            decision.point,
            source_page="体力弹窗（生命之叶已选中）",
            target_pages=("队伍准备", "快速战斗", "战斗中"),
            reason="生命之叶选中且购买确认按钮已识别",
        )

    def next_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        # 战败结算页**优先于一切状态分派**（2026-11-06 接线）：它既不是任何一关的
        # 前进页，也没有可以安全点的按钮 —— 右下「重新进行 / 继续战斗」都会重打
        # 这一关，点了就是无限循环白耗体力。监督收手把状态拨到 WAIT_RESULTS 后，
        # 这里直接按「打不过」正常收工（退出码 2、不重打、收尾照常回首页）。
        # 与月塔 CARD 分支先判 FAILED 同一纪律：孤儿页排在业务页前面。
        if self._battle_failed(screen) is not None:
            raise StageTooHard("主线这一关打不过（战斗 FAILED 结算页）")
        stamina_action = self._handle_stamina(screen)
        if stamina_action is not None:
            return stamina_action

        if self.state is StoryState.TEAM:
            pre_battle = observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=self._locate(screen, "start_mission"),
            )
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                return self._action(
                    "switch_to_normal_battle",
                    pre_battle.switch_point,
                    source_page="快速战斗",
                    target_pages=("队伍准备",),
                    reason="快速战斗按钮与切换按钮同时成立",
                    target_states=(StoryState.TEAM,),
                )

        checks = [
            (
                "reward",
                "奖励结算",
                # ⚠️「剧情播放」是 2026-11-01 22:55 实跑撞出来的落点：点完领奖，
                # 剧情关卡会接着放**战后过场**（不是直接进战果），原名单没有它 ⇒
                # 主循环判「没点成功」→ 丢掉动作 → 干等 45 秒 → 整轮失败。
                # 同一类的「通关结算 / 结算确认」也补了它：这三下都在战果链上，
                # 点完接一段过场是同一个游戏行为（日志里那次 skip-confirm 超时也是这套）。
                #
                ("剧情播放", "通关结算", "结算确认"),
                StoryState.WAIT_RESULTS,
                (StoryState.WAIT_RESULTS, StoryState.ACTIVE),
                "奖励按钮位于结算页",
            ),
            (
                "clear",
                "通关结算",
                ("剧情播放", "结算确认", "通关提示"),
                StoryState.WAIT_RESULTS,
                (StoryState.WAIT_RESULTS, StoryState.WAIT_COMPLETE, StoryState.ACTIVE),
                "通关结算主体已识别",
            ),
            (
                "results_confirm",
                "结算确认",
                # ⚠️ 「无法前往下一关」是**第四种**落点（2026-10-18 21:14 实跑）。
                #
                # 结算确认点完，游戏可能直接给「无法前往下一关，请选择下方按钮」
                # （重复打同一关时的常态）。漏声明的后果**不是「认不出这一页」那么简单**：
                # 主循环发现「新页面不在转场目标里」，会判定这一下没点成功，
                # 于是把状态机刚给出的 `retry_stage` 动作**整个丢掉**（runner_base 里
                # 那个 `action = last_transition_action if confirmed_page == source_page else None`），
                # 干等 45 秒后报「转场超时」。日志表现完全像「点了没反应」，
                # 但根因是**契约漏了一个落点**。
                ("剧情播放", "通关提示", "额外奖励", "下一关入口", "无法前往下一关"),
                StoryState.WAIT_RESULTS,
                (StoryState.WAIT_COMPLETE, StoryState.WAIT_NEXT_STAGE, StoryState.ACTIVE),
                "结算确认按钮位于底部确认区",
            ),
            (
                "complete",
                "通关提示",
                ("额外奖励", "下一关入口", "关卡入口", "剧情关卡入口"),
                StoryState.WAIT_COMPLETE,
                (StoryState.WAIT_NEXT_STAGE, StoryState.STAGE),
                "通关提示主体已识别",
            ),
            (
                "bonus_reward",
                "额外奖励",
                ("下一关入口", "关卡入口", "剧情关卡入口"),
                StoryState.WAIT_NEXT_STAGE,
                (StoryState.WAIT_NEXT_STAGE, StoryState.STAGE),
                "额外奖励弹窗已识别",
            ),
            # 2026-09-18 两次实跑（14:14:07、14:47:46）卡在同一处：把最后一段剧情
            # 跳掉后游戏不回到剧情播放，而是直接给「通关提示」——原来这里没声明它，
            # 于是转场契约永远不成立、干等 45 秒后整条路线以退出码 1 收场
            # （证据包 complete=0.996 / next_stage=0.954，其余模板全部未命中）。
            # 通关提示本来就是正牌前进页（`complete` 动作专门处理它），补进契约。
            #
            # 2026-11-01 一晚两次，同一个动作、不同落点：21:21 落到「结算确认」、
            # 22:02 落到「通关结算」。两次都是主循环判「没点成功」→ 丢掉动作 →
            # 干等 45 秒 → 收尾回首页在结算页按 ESC 无效 → 退出码 1。
            # 这不是判据问题，是**落点名单漏了**（与 09-18 漏「通关提示」同一类）。
            (
                "skip_confirm",
                "跳过确认",
                (
                    "剧情播放",
                    "战斗中",
                    "关卡入口",
                    "剧情关卡入口",
                    "通关提示",
                    "通关结算",
                    "结算确认",
                ),
                StoryState.WAIT_SKIP_CONFIRM,
                (
                    StoryState.ACTIVE,
                    StoryState.STAGE,
                    StoryState.WAIT_COMPLETE,
                    StoryState.WAIT_RESULTS,
                ),
                "跳过确认按钮已识别",
            ),
            (
                "skip",
                "剧情播放",
                ("跳过确认", "战斗中", "关卡入口", "剧情关卡入口"),
                StoryState.ACTIVE,
                (StoryState.WAIT_SKIP_CONFIRM, StoryState.ACTIVE, StoryState.STAGE),
                "剧情右上角跳过按钮已识别",
            ),
            (
                "watch_story",
                "剧情关卡入口",
                ("剧情播放", "跳过确认", "关卡入口", "战斗中"),
                StoryState.STAGE,
                (StoryState.WAIT_SKIP_CONFIRM, StoryState.ACTIVE, StoryState.STAGE),
                "关卡入口的观看剧情按钮已识别",
            ),
            (
                "select_team",
                "助手选择",
                ("队伍准备", "快速战斗"),
                StoryState.TEAM,
                (StoryState.TEAM,),
                "助手选择页的确认按钮已识别",
            ),
            (
                "start_mission",
                "队伍准备",
                ("战斗中", "体力弹窗"),
                StoryState.TEAM,
                (StoryState.WAIT_BATTLE,),
                "普通战斗开始按钮已识别",
            ),
        ]
        for name, source_page, targets, source_state, target_states, reason in checks:
            match = self._locate(screen, name)
            if match is not None:
                previous_state = self.state
                if (
                    name == "watch_story"
                    and previous_state
                    in (StoryState.WAIT_COMPLETE, StoryState.WAIT_NEXT_STAGE)
                ):
                    self.completed_cycles += 1
                self.state = source_state
                if name in ("select_team", "start_mission", "watch_story"):
                    self.auto_enabled = False
                if name == "start_mission":
                    self.auto_click_attempted = False
                    self.battle_controls = BattleControls.TRANSITION
                return self._action(
                    name,
                    self._action_point(screen, name, match),
                    source_page=source_page,
                    target_pages=targets,
                    reason=reason,
                    target_states=target_states,
                )
        match = self._locate(screen, "prepare_battle")
        if match is not None:
            if self.state in (StoryState.WAIT_COMPLETE, StoryState.WAIT_NEXT_STAGE):
                self._confirm_page("关卡入口")
                self.completed_cycles += 1
                self.state = StoryState.STAGE
                return None
            self.state = StoryState.STAGE
            self.auto_enabled = False
            self.auto_click_attempted = False
            self.battle_controls = BattleControls.TRANSITION
            return self._action(
                "prepare_battle",
                match.center,
                source_page="关卡入口",
                target_pages=("助手选择", "队伍准备", "快速战斗", "剧情播放", "战斗中"),
                reason="关卡入口的准备战斗按钮已识别",
                target_states=(StoryState.TEAM,),
            )
        if self.state in (
            StoryState.WAIT_SKIP_CONFIRM,
            StoryState.WAIT_BATTLE,
            StoryState.ACTIVE,
        ):
            self.battle_controls = self.observe_battle_controls(screen)
            if self.battle_controls == BattleControls.AUTO_CONTROLS:
                self.state = StoryState.ACTIVE
                self.auto_enabled = True
                self._confirm_page("战斗中")
                return None
            if self.battle_controls == BattleControls.MANUAL_CONTROLS:
                self.state = StoryState.WAIT_BATTLE
                self.auto_enabled = False
                match = self._locate(screen, "auto_off")
                point = (
                    match.center
                    if match is not None
                    else self._scaled_point(screen, self._AUTO_CLICK_POINT)
                )
                return self._action(
                    "enable_auto",
                    point,
                    # ⚠️ 页面名会被 ``_action`` → ``_confirm_page()`` 写成「当前已确认
                    # 页面」，主循环拿它去比对上一个动作的 ``target_pages``；两边必须
                    # 一字不差，否则刚给出的动作被置 None、状态机失声。
                    #
                    # 2026-11-07 08:10 真机：剧情跳过确认点完后进入**自动战斗关着**的
                    # 战斗画面，旧名「战斗中（自动关闭）」跟 ``skip_confirm.target_pages``
                    # 里的「战斗中」对不上 ⇒ ``enable_auto`` 一次都没发出去过 ⇒
                    # 干等 60 秒报「转场超时 动作=skip_confirm」。
                    #
                    # PC 上用规范名「战斗中」（全仓没有任何名单把带后缀的那个当目标，
                    # 所以只会增加匹配、不会减少）；模拟器保留原名，行为零改动。
                    # 「自动是关的」这条信息由下面的 ``reason`` 承担，不写进页面名。
                    source_page="战斗中" if self._pc_rules else "战斗中（自动关闭）",
                    target_pages=("战斗中",),
                    reason="战斗头像布局与自动关闭图标已识别",
                    target_states=(StoryState.ACTIVE,),
                )
        if self.state == StoryState.WAIT_NEXT_STAGE:
            match = self._locate(screen, "bonus_reward")
            if match is not None:
                return self._action(
                    "bonus_reward",
                    self._action_point(screen, "bonus_reward", match),
                    source_page="额外奖励",
                    target_pages=("下一关入口", "关卡入口", "剧情关卡入口"),
                    reason="额外奖励弹窗已识别",
                    target_states=(StoryState.WAIT_NEXT_STAGE, StoryState.STAGE),
                )
            match = self._locate(screen, "next_stage")
            if match is not None:
                self._confirm_page("下一关入口")
                self.completed_cycles += 1
                self.state = StoryState.STAGE
                return None

        if self.state == StoryState.WAIT_COMPLETE:
            # Recovery: the screen may have already advanced to the map or is
            # showing a bonus popup. Try forward templates instead of dead-
            # ending on the (possibly stale) complete button.
            match = self._locate(screen, "bonus_reward")
            if match is not None:
                self.state = StoryState.WAIT_NEXT_STAGE
                return self._action(
                    "bonus_reward",
                    self._action_point(screen, "bonus_reward", match),
                    source_page="额外奖励",
                    target_pages=("下一关入口", "关卡入口", "剧情关卡入口"),
                    reason="通关后的额外奖励弹窗已识别",
                    target_states=(StoryState.WAIT_NEXT_STAGE, StoryState.STAGE),
                )
            match = self._locate(screen, "next_stage")
            if match is not None:
                self._confirm_page("下一关入口")
                self.completed_cycles += 1
                self.state = StoryState.STAGE
                return None
            match = self._locate(screen, "prepare_battle")
            if match is not None:
                self._confirm_page("关卡入口")
                self.state = StoryState.TEAM
                self.auto_enabled = False
                return self._action(
                    "prepare_battle",
                    match.center,
                    source_page="关卡入口",
                    target_pages=("助手选择", "队伍准备", "快速战斗", "剧情播放", "战斗中"),
                    reason="通关后已回到下一关入口",
                    target_states=(StoryState.TEAM,),
                )

        # ── 「重复打同一关」那一页（2026-10-18 立）─────────────────────────────
        #
        # 现场：10-18 19:50（第 3 章·白色悬崖森林）与 10-14 18:42（另一关）两次同形 ——
        # 结算确认点完，游戏给的是「无法前往下一个关卡，请选择下方按钮」，
        # 左下角「离开 / 大厅」、右下角「S 体力/上限 + 重新进行」。
        # 这一页**原来一个锚点都没有** ⇒ 认不出 ⇒ 静默干等 45 秒 ⇒ 退出码 1。
        #
        # 放在**所有前进判据之后**，就是用户要的优先级：
        # 能「进行下一个关卡」就先走它（`complete` / `next_stage` / `prepare_battle`
        # 都在上面已经判过），只有都认不到时才重打同一关。
        #
        # 落点依据不是猜的：狗粮路线 2026-09-13 的实跑日志里，
        # 点 `replay` 之后 4 秒落到「准备战斗」页（`select_team` 那一屏），
        # 再选队、开战 —— 所以这里按「回到关卡入口 / 助手选择」声明契约。
        match = self._locate(screen, "retry_stage")
        if match is not None:
            if self._confirmed_page != "无法前往下一关":
                # 这一屏本身 = 一局刚打完。只记一次：点歪重试（尝试 2/4、3/4）
                # 时同一屏还会再判一次，不许把一轮算成两轮。
                self.completed_cycles += 1
            return self._action(
                "retry_stage",
                match.center,
                source_page="无法前往下一关",
                # 落点：`助手选择`（实测狗粮 replay 后到的那一页）/ `队伍准备`（万一直接跳过选助手）。
                # `关卡入口 / 剧情关卡入口` 保留 —— 有的关卡重打会先回地图。
                # ⚠️ 这四个都是「下一轮开头」的页面，不是随便凑的；
                # 多写一个错页面 = 转场验收形同虚设。
                target_pages=("关卡入口", "剧情关卡入口", "助手选择", "队伍准备"),
                reason="「重新进行」已识别（本关没有下一关可去，重打同一关）",
                target_states=(StoryState.STAGE, StoryState.TEAM),
            )

        self._confirmed_page = ""
        raise UnrecognizedScreen(
            f"主线画面[{state_label(self.state)}]未识别"
        )

    def preview(self, screen: np.ndarray):
        """Observe a frame without committing optimistic state changes."""

        snapshot = (
            self.state,
            self.auto_enabled,
            self.auto_click_attempted,
            self.battle_controls,
            self.completed_cycles,
            self.stamina_replenished,
            self._stamina_material_clicked,
            self._stamina_purchase_pending,
            self._confirmed_page,
        )
        try:
            action = self.next_action(screen)
            outcome = (self.state, self.completed_cycles)
            return action, outcome
        finally:
            (
                self.state,
                self.auto_enabled,
                self.auto_click_attempted,
                self.battle_controls,
                self.completed_cycles,
                self.stamina_replenished,
                self._stamina_material_clicked,
                self._stamina_purchase_pending,
                self._confirmed_page,
            ) = snapshot


# 导航页面名「主线入口」（= `navigation.page_label("story_ready")`）。
# 站在这一页上说明已经在主线里了，只差「准备战斗」一步，不用再回大厅重进。
STORY_ENTRY_PAGE = "story_ready"





# 「接力」探测顺序 —— **顺序即优先级**，不能改。每项是（锚点名, 落点状态, 中文页面名）。
#
# 三条铁律都是夹具实测逼出来的：
#
# 1. **局内排第一**（它不走锚点，看 `battle_scene_visible`）：已经在打的那一局必须最先
#    接手。战斗画面里 `auto_off` 能到 0.9857（`battle_variant`）、结算类锚点也会零星命中，
#    先认锚点就可能把「已经在打」错认成某个结算页。反过来万一某个结算帧被认成局内也不亏：
#    战斗监督进循环第一件事就是连续两帧判 `result_visible`，认出来直接以 RESULT_REACHED
#    收尾，奖励不会丢。
# 2. **关卡入口（`prepare_battle` / `watch_story`）排在 `next_stage` 前面**：
#    两者会**同时出现在关卡入口页**上（实测 `next_stage.png` 上 prepare_battle=0.9793、
#    `stage.png` 上 next_stage=0.9352）。若先判 next_stage，关卡入口会被拨成
#    「等待下一关」—— 而 `next_action` 在 WAIT_NEXT_STAGE 下碰到 `prepare_battle`
#    只记轮次、**不点击**（见 next_action 里那段 recovery 分支），结果是原地干等到
#    45 秒超时再触发回大厅。先判关卡入口就落成 STAGE，正常点准备战斗。
# 3. **`complete` 排在 `next_stage` 前面**：通关提示页上两者同时可见
#    （实测 complete=1.0000、next_stage=0.9780），先判 complete 才会拨成 WAIT_COMPLETE。
#
# 其余各项在夹具上互斥，相对顺序不影响结果；按「流程先后」排只是方便读。
_STORY_RESUME_ORDER: tuple[tuple[str, StoryState, str], ...] = (
    ("prepare_battle", StoryState.STAGE, "关卡入口"),
    ("watch_story", StoryState.STAGE, "剧情关卡入口"),
    ("start_mission", StoryState.TEAM, "队伍准备"),
    ("select_team", StoryState.TEAM, "助手选择"),
    ("skip_confirm", StoryState.WAIT_SKIP_CONFIRM, "跳过确认"),
    ("skip", StoryState.ACTIVE, "剧情播放"),
    ("complete", StoryState.WAIT_COMPLETE, "通关提示"),
    ("bonus_reward", StoryState.WAIT_NEXT_STAGE, "额外奖励"),
    ("results_confirm", StoryState.WAIT_RESULTS, "结算确认"),
    ("clear", StoryState.WAIT_RESULTS, "通关结算"),
    ("reward", StoryState.WAIT_RESULTS, "奖励结算"),
    ("next_stage", StoryState.WAIT_NEXT_STAGE, "下一关入口"),
    # 「无法前往下一个关卡」那一页，**故意排最后**：它是「前进无路可走时的兜底」，
    # 不是比 `next_stage` 更优先的落点。实测这一页上 `next_stage` 只有 0.1411，
    # 排在前后都不影响结果；排最后只是把「优先级」写成可读的顺序。
    ("retry_stage", StoryState.WAIT_RESULTS, "重新进行"),
)


def detect_resume_point(
    machine: "StoryStateMachine",
    screen: np.ndarray,
    *,
    observed_page: Optional[str] = None,
) -> Optional[ResumePoint]:
    """主线开局接力：认出用户停在主线一环里的哪一页。

    识别不到返回 None，调用方回退到「回大厅 → 从主线入口重新导航」（失败关闭，
    行为与加这个功能之前一致）。

    ``observed_page`` 传导航器认出来的页面名（``Epic7Navigator.observe().name``）。
    主线里只有 ``story_ready`` 这一个导航链上的页面需要它，其余页面状态机自己认，
    所以这个参数可以省略（导航器拿不到观察结果时传 None）。

    **落点状态是必需的，不是顺手记的**：主线 ``next_action`` 虽然能从锚点自己推出
    页面（``reward``→WAIT_RESULTS 之类），但有两条支路**依赖进来时的状态**才肯点击 ——
    ``prepare_battle`` 在 WAIT_COMPLETE/WAIT_NEXT_STAGE 下只记轮次不点击，
    ``observe_battle_controls`` 那一支只在 WAIT_SKIP_CONFIRM/WAIT_BATTLE/ACTIVE 下才跑。
    所以接力必须先把状态拨对，不能指望第一帧自己纠正。
    """
    if battle_scene_visible(screen):
        return ResumePoint("战斗中", StoryState.WAIT_BATTLE)
    # 战败结算页：这一帧 ``_STORY_RESUME_ORDER`` 的 12 颗锚点**一颗都不命中**
    # （2026-11-06 17:15 真机帧实测），必须在状态循环之前显式判，否则开局
    # 停在 FAILED 页会被当成「认不出」→ 回大厅重走一遍 → 又打一遍同一关。
    if machine._battle_failed(screen) is not None:
        return ResumePoint("战斗失败结算", StoryState.WAIT_RESULTS)
    if observed_page is not None and observed_page == STORY_ENTRY_PAGE:
        # 导航器认出来就直接落 STAGE + 导航接力点，不再重复跑锚点。
        return ResumePoint("关卡入口", StoryState.STAGE, STORY_ENTRY_PAGE)
    for name, state, label in _STORY_RESUME_ORDER:
        if machine._locate(screen, name) is None:
            continue
        entry = STORY_ENTRY_PAGE if name in ("prepare_battle", "watch_story") else None
        return ResumePoint(label, state, entry)
    return None


class StoryRunner(ModeRunnerBase):
    """主线短轮询、失败即停 Runner（主循环协议见 ModeRunnerBase）。"""

    _MODE_LABEL = "主线"
    _TIMEOUT_SECONDS = {
        StoryState.STAGE: 45,
        StoryState.TEAM: 45,
        StoryState.WAIT_SKIP_CONFIRM: 45,
        StoryState.WAIT_BATTLE: 60,
        StoryState.ACTIVE: 120,
        StoryState.WAIT_RESULTS: 45,
        StoryState.WAIT_COMPLETE: 45,
        StoryState.WAIT_NEXT_STAGE: 45,
    }
    _BATTLE_ENTRY_ACTION = "start_mission"
    _ALLOW_UNKNOWN_SCREEN_WAKE = False

    def __init__(
        self,
        machine: StoryStateMachine,
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
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="story", mode_label="主线"),
            now=self.now,
            sleep=sleep,
        )

    def run(self, max_cycles: int | None = None) -> int:
        # 接力落在局内：先把这一局监督完再进主循环。空跑不碰战斗监督（干跑只观察）。
        # 用 getattr 而不是直接取属性：主循环协议里的状态机是鸭子类型
        # （测试里的 FakeMachine 只实现 preview/next_action），缺这个标记时按「没接力」处理。
        if (
            not self.runtime.dry_run
            and getattr(self.machine, "resumed_from", None) is StoryState.WAIT_BATTLE
        ):
            self._resume_into_committed_battle()
        return super().run(max_cycles=max_cycles)

    def _resume_into_committed_battle(self) -> None:
        """接力直接落在局内：这一局不是本进程点开的，但已经打起来了。

        不能走 ``next_action`` 那条路：战斗分支只在
        WAIT_SKIP_CONFIRM/WAIT_BATTLE/ACTIVE 下才跑，而且它靠 ``auto_off`` 图标定位，
        而**自动战斗开着时这个图标根本不可见**；就算认出来也要等主循环那一套状态超时。
        更关键的是开局落在局内时**绝不能按 Back 回大厅** —— 那是「已承诺战斗」的禁区，
        会把这一局白打。所以直接交给战斗监督等结算，跟点完 start_mission 之后一样。

        代价：这个判据分不出「这是哪条路线的战斗」，停在别的路线战斗里启动主线也会
        先把这一局监督完再回大厅重新导航。这仍比老流程好：老流程在局内会一直卡在
        「未知画面等待唤醒」直到返回大厅预算耗尽，然后退出码 1。
        """
        self.runtime.log(
            "模式=主线 开局=接力 页面=战斗中 "
            "动作=交由战斗监督等待结算 状态=不按Back不重新导航"
        )
        self._run_committed_battle(cycle=self.machine.completed_cycles + 1)

    def _state_label(self, state: StoryState) -> str:
        return state_label(state)

    def _after_action_click(self, action: StoryAction) -> None:
        record_click = getattr(self.machine, "action_clicked", None)
        if record_click is not None:
            record_click(action)

    def _transition_success_detail(
        self, previous_action: StoryAction, current_action: StoryAction | None
    ) -> str:
        return (
            f"从={previous_action.source_page} "
            f"依据={previous_action.reason} 目标连续=2"
        )

    def _transition_retry_reason(
        self, previous_action: StoryAction, current_action: StoryAction | None
    ) -> str:
        return f"来源页面={previous_action.source_page}仍在，目标未稳定"

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = StoryState.WAIT_BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"主线战斗出现意外结果：{outcome.value}")
        self.machine.state = StoryState.WAIT_RESULTS

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式=主线 状态=完成一轮 累计完成={self.machine.completed_cycles}轮"
        )

    def _log_state_timeout(self, state: StoryState, elapsed: float, diagnostic) -> None:
        self.runtime.log(
            f"模式=主线 页面={state_label(state)} "
            f"状态=超时无进展 已耗时={elapsed:.1f}秒 诊断={diagnostic}"
        )

    def _log_settled_timeout(self, state: StoryState, diagnostic) -> None:
        self.runtime.log(
            f"模式=主线 页面={state_label(state)} "
            f"状态=等待超时无进展 诊断={diagnostic}"
        )

