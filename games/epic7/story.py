from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
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
    find_all_templates,
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
    StaminaBudget,
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
    TEAM_RING_MIN_RATIO,
    TEAM_RING_REGION,
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

    2026-11-22 补第三套外观：**点「管理队伍」进编队后，按钮变成绿底「进行任务」**。
    它既不是旧皮的橙金、也不是新皮的「战斗开始」文案，原样匹配只有 0.625~0.743。
    这里不补第三张图，原因有二：
      * 真正稳定的是**白字「进行任务」**：同一张 `start_mission.png` 走白掩膜，
        橙底帧 0.919 / 编队绿底帧 0.897 / 满员帧 0.898，而关卡入口页只有 0.523；
      * 以后游戏再换底色，白掩膜仍然认得出，补图则要一张一张追。
    白掩膜是**兜底口径、不是放宽**：它用 0.85 的更高阈值，且只在原样两套都不过
    时才启用。原样能过的帧，分数与改动前逐字节一致。
    """
    matches = []
    for template in (primary_template, updated_template):
        match = find_template(
            screen, template, threshold, region=region, reference_size=reference_size
        )
        if match is not None:
            matches.append(match)
    if matches:
        return max(matches, key=lambda candidate: candidate.score)
    for template in (primary_template, updated_template):
        match = find_template(
            screen,
            template,
            0.85,
            region=region,
            reference_size=reference_size,
            mode=MATCH_MODE_WHITE_MASK,
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
    STORY_CUTSCENE = "story_cutscene"
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
    StoryState.STORY_CUTSCENE: "剧情过场",
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
    # ── 队伍页「有空位就补人」（2026-11-22，用户实跑口径）────────────────────
    # 故事关卡会给一支**不满员**的预设队伍：1 个剧情角色 + 3 个黄色空位光圈。
    # 这种页面上点「进行任务」游戏不给反应（实测连点 4 次画面不动），必须先补人。
    #
    # 判据链条（缺一不可，任何一环认不出就不动手）：
    #   1. 阵型区黄色高亮像素占比 ≥ TEAM_RING_MIN_RATIO ⇒ 确实还有空位（黄圈在闪）；
    #   2. 左下角「管理队伍」⇒ 进编队的入口；
    #   3. 右侧列表顶端「蓝底黄十字」⇒ 进入「可放置」状态，空位才会浮出紫加号；
    #   4. 空位上的「紫底黄十字」⇒ 点它是**唯一**把英雄放上去的动作。
    #
    # ⚠️ 只按次数循环、不看黄圈是错的：配满后黄圈全变蓝圈，再点加号只会得到
    #    「已配置的英雄」（那句话的意思是"这个英雄已上阵"，不是"队伍满了"）。
    # ⚠️ 对同一颗加号连点而不换英雄，紫加号不会重现 —— 每配一人必须把列表下移一格。
    team_manage: np.ndarray
    team_list_plus: np.ndarray
    team_slot_plus: np.ndarray
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
        team_manage=load_template(str(template_dir / "team_manage.png")),
        team_list_plus=load_template(str(template_dir / "team_list_plus.png")),
        team_slot_plus=load_template(str(template_dir / "team_slot_plus.png")),
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
        story_cutscene: bool = False,
    ) -> None:
        self.templates = templates
        self.state = initial_state
        # 主线专属：点完跳过确认之后、战斗出现之前的那段纯演出没有任何可点锚点，
        # 认不出就停在 WAIT_SKIP_CONFIRM 干等到超时。开启后由 next_action 兜底拨到
        # STORY_CUTSCENE，交给主循环的状态超时表接管。默认 False ⇒ 其余复用主线的
        # 路线（补星 / 活动 / 支线）行为逐字节不变。
        self.story_cutscene = story_cutscene
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
        # 体力预算由 Runner 按路线选项注入；默认「使用、不限」= 改动前行为。
        self.stamina_budget = StaminaBudget()
        self._stamina_material_clicked = False
        self._stamina_purchase_pending = False
        self._confirmed_page = ""
        # 「接力」进来的落点；None = 本轮是正常从关卡入口开始的。Runner 靠它判断
        # 「局内接力」要不要跳过状态机直接把这一局交给战斗监督。
        self.resumed_from: Optional[StoryState] = None
        # ── 队伍页补人（2026-11-22）──────────────────────────────────────────
        # 已经放上去的人数；只在「点完紫加号、紫加号确实消失」时 +1。
        self._team_placements = 0
        # 点过几次列表顶端加号（= 向游戏问过几次「还有没有空位」）。
        self._team_asked = 0
        # 连续几次「问了却没有紫加号」。换过英雄后仍是 0 出 ⇒ 判定满员。
        self._team_empty_asks = 0
        # 放行「进行任务」的依据。**必须写进日志**，不许静默放行。
        self._team_release_reason = ""
        # 滑动前记下的英雄列表指纹；滑完拿它确认列表到底动没动（照搬英雄合成口径）。
        self._team_list_fp: Optional[str] = None
        # 上一个真正发出去的动作名，用来判断"刚放完一个人，该换英雄了"。
        self._team_last_action = ""
        # 同名配队动作连续发了几次；连续 2 次说明这一支在这页上行不通，放弃配队。
        self._team_same_count = 0

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
        elif action.name.startswith("team_"):
            # 配队是**多步点击**，每一步都要看上一脚踩在哪：同名连续出现说明
            # 这一支在这页上行不通（加号点了不冒紫加号 / 管理队伍点了不进编队）。
            if action.name == self._team_last_action:
                self._team_same_count += 1
            else:
                self._team_same_count = 0
            self._team_last_action = action.name

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

    # ── 队伍页补人（2026-11-22）────────────────────────────────────────────
    # 用户口径：故事关卡会给一支不满员的预设队伍（1 个剧情角色 + 若干**黄色空位光圈**）。
    # 空位上是会闪的黄色光圈，满员后全部变蓝圈 —— 这是「还需要补人」的唯一外观依据。
    # 页面上直接点「进行任务」不会推进（实测连点 4 次画面不动），必须先把空位补上。
    _TEAM_MAX_PLACEMENTS = 4
    _TEAM_SCROLL_POINT = (1550, 640)
    # 英雄列表指纹区（参考画布坐标）。取列表主体，避开顶部滚动公告与底部按钮。
    _TEAM_LIST_FP_ZONE = (1420, 220, 430, 560)
    # 「问了没紫加号」连续几次就判定满员。第一次允许是判据抖动（加号点了画面还没刷），
    # 换过英雄（滚动一格）之后再一次仍没有，才算真的没位置。
    _TEAM_EMPTY_ASKS_TO_STOP = 2

    def _team_ring_ratio(self, screen: np.ndarray) -> float:
        """阵型区「黄色高亮」像素占比。

        实测（1982×1132）：3 个空位 3.35% / 2 个 2.66% / 1 个 1.37% /
        满员全蓝圈 0.18%。阈值 0.8% 卡在满员与最稀疏空位之间。
        """
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = TEAM_RING_REGION
        x, y = round(x * scale_x), round(y * scale_y)
        width, height = round(width * scale_x), round(height * scale_y)
        area = screen[y : y + height, x : x + width]
        if area.size == 0:
            return 0.0
        r = area[:, :, 0].astype(np.int16)
        g = area[:, :, 1].astype(np.int16)
        b = area[:, :, 2].astype(np.int16)
        mask = (r > 190) & (g > 160) & (b < 150) & (r - b > 70)
        return float(mask.mean())

    def _team_slot_point(self, screen: np.ndarray) -> Optional[tuple[int, int]]:
        """空位上最早（最靠上）的那颗紫加号。用户口径：从上到下依次放人。"""
        matches = find_all_templates(
            screen,
            self.templates.team_slot_plus,
            self._THRESHOLDS.get("team_slot_plus", self.templates.threshold),
            region=self._REGIONS["team_slot_plus"],
            reference_size=self._REFERENCE_SIZE,
            min_gap=80,
        )
        if not matches:
            return None
        top = min(matches, key=lambda m: m.center[1])
        return top.center

    def _team_guard_blocked(self, name: str) -> bool:
        """同一个配队动作连续第 3 次被要求发出 ⇒ 这一支在这页上行不通。

        正常节奏是「点一下 → 下一帧画面就变，动作名跟着变」，所以同名连续出现
        只可能是：加号点了不出现紫加号（本关不允许配队）、管理队伍点了不进编队。
        与其等满无进展看门狗，不如当场放弃补人、直接把「进行任务」原样发出去。
        """
        if name != self._team_last_action:
            return False
        return self._team_same_count >= 2

    def _team_action(
        self, name: str, point: tuple[int, int], reason: str
    ) -> Optional[StoryAction]:
        """配队动作统一走这里：不换页，出口仍是「队伍准备」。"""
        if self._team_guard_blocked(name):
            return None
        return self._action(
            name,
            point,
            source_page="队伍准备",
            target_pages=("队伍准备",),
            reason=reason,
        )

    def _team_list_fingerprint(self, screen: np.ndarray) -> str:
        """英雄列表的灰度指纹：滑动之后用它确认列表**真的动了**。

        口径照搬 ``hero_synthesis._detail_fingerprint`` —— 那里已经用「高斯模糊压掉
        立绘动画与粒子噪点 + 缩略图量化 + sha1 前 8 位」稳定判断过「确实翻到了下一张」。
        配队原来那版是**盲滑**：滑一下就当换人了，根本不知道列表动没动，于是滚到底之后
        还在对着列表顶端那颗加号反复点。同一套问题，用同一套办法。
        """
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, width, height = self._TEAM_LIST_FP_ZONE
        x, y = round(x * scale_x), round(y * scale_y)
        width, height = round(width * scale_x), round(height * scale_y)
        zone = screen[y : y + height, x : x + width]
        if zone.size == 0:
            return ""
        gray = cv2.cvtColor(zone, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (11, 11), 0)
        small = cv2.resize(gray, (8, 12), interpolation=cv2.INTER_AREA)
        return hashlib.sha1((small // 32).astype(np.uint8).tobytes()).hexdigest()[:8]

    def _team_ready(self, reason: str) -> None:
        """判定这一队可以开打：记下依据并清账，供下一关重新从零问起。"""
        self._team_release_reason = reason
        self._team_placements = 0
        self._team_asked = 0
        self._team_empty_asks = 0
        self._team_last_action = ""
        self._team_list_fp = None

    def _team_scroll_action(
        self, screen: np.ndarray, reason: str
    ) -> Optional[StoryAction]:
        """发一次「换下一个英雄」：动作发出前先记下列表指纹，滑完用它验收。"""
        action = self._team_action("team_scroll", self._TEAM_SCROLL_POINT, reason)
        if action is not None:
            self._team_list_fp = self._team_list_fingerprint(screen)
        return action

    def _configure_team(self, screen: np.ndarray) -> Optional[StoryAction]:
        """队伍页补人：**黄圈在场就不能开打**，配到游戏说「没位置了」为止。

        返回 ``None`` 表示放行「进行任务」（调用方把 ``_team_release_reason`` 写进日志）。

        判据优先级（用户 2026-11-22 口径）：
          1. **紫加号 > 黄圈**。只要空位上浮出紫加号，就说明还有位置，必须放人，
             不管黄圈占比算出来多少；
          2. 黄圈只做「要不要进编队问一次」的前置。闪烁让占比在 1.3%~5.3% 之间跳，
             拿它当满员证据会把"只配了 1 个人"当成满员放行（09:15 实跑就是这么错的）；
          3. 真正的满员证据：**换过英雄之后，点顶端加号仍不出紫加号**；
          4. 每放一个人必须先把列表下移一格换英雄 —— 对同一颗加号连点只会得到
             「已配置的英雄」（那句话的意思是"这个英雄已上阵"，不是"队伍满了"）。
        """
        # PC 队伍页布局未实跑验证，这一支只在模拟器启用（模拟器行为新增，PC 零改动）。
        if self._pc_rules:
            return None
        self._team_release_reason = ""

        # ① 紫加号在：一定有位置，先放人（这一条压过黄圈占比）
        slot = self._team_slot_point(screen)
        if slot is not None:
            self._team_empty_asks = 0
            self._team_list_fp = None
            ratio = self._team_ring_ratio(screen)
            return self._team_action(
                "team_slot_plus",
                slot,
                f"空位紫加号已出现（黄圈占比 {ratio:.2%}），放第 "
                f"{self._team_placements + 1} 个英雄",
            )

        # ② 黄圈全部消失 = 满员终态，立刻放行，**不管问过几次加号**。
        #
        # ⚠️ 2026-11-22 10:15 实跑教训：这里原来多写了一个 `and self._team_asked == 0`，
        # 本意是「只认进场那一眼」，结果补到第 3 个人时占比已经掉到 0.17%（全蓝），
        # 却因为「已经问过 3 次加号」而不放行，继续去点第 4 次、第 5 次。
        # 黄圈归零就是用户口径的满员终态，这一条必须无条件生效。
        ratio = self._team_ring_ratio(screen)
        if ratio < TEAM_RING_MIN_RATIO:
            if self._team_asked == 0:
                self._team_ready(f"进场时阵型区没有黄圈（占比 {ratio:.2%}）")
            else:
                self._team_ready(
                    f"补完 {self._team_placements} 人后黄圈已全部消失"
                    f"（占比 {ratio:.2%}）"
                )
            return None

        # ①.5 刚跑完一次滑动：先确认列表**真的动了**（口径同英雄合成的翻卡确认）。
        # 指纹没变 = 滚不动/已到底，换不出新英雄，再点加号也只是原地打转。
        if self._team_list_fp is not None:
            moved = self._team_list_fingerprint(screen) != self._team_list_fp
            self._team_list_fp = None
            if not moved:
                self._team_ready(
                    "滑动后列表指纹未变化（已到底），但阵型区仍有黄圈，"
                    "没有更多英雄可换，拒绝开打"
                )
                return None

        # ② 刚点完顶端加号却没有紫加号 ⇒ 这个英雄已经在队伍里，换人再问
        if self._team_last_action == "team_list_plus":
            self._team_empty_asks += 1
            if self._team_empty_asks >= self._TEAM_EMPTY_ASKS_TO_STOP:
                self._team_ready(
                    f"换过英雄后顶端加号仍不出紫加号（连续 "
                    f"{self._team_empty_asks} 次），判定没有空位"
                )
                return None
            return self._team_scroll_action(
                screen,
                f"第 {self._team_empty_asks} 次问询没有紫加号，下移一格换下一个英雄",
            )

        # ③ 刚放上去一个：先换英雄，否则同一颗加号不会再出紫加号
        if self._team_last_action == "team_slot_plus":
            self._team_placements += 1
            return self._team_scroll_action(
                screen,
                f"已补 {self._team_placements} 人，下移一格换下一个英雄",
            )

        if self._team_placements >= self._TEAM_MAX_PLACEMENTS:
            self._team_ready(f"已补 {self._team_placements} 人，达到硬上限")
            return None

        plus = self._locate(screen, "team_list_plus")
        if plus is not None:
            self._team_asked += 1
            return self._team_action(
                "team_list_plus",
                plus.center,
                f"第 {self._team_asked} 次点顶端加号（黄圈占比 {ratio:.2%}），"
                "确认还有没有空位",
            )

        manage = self._locate(screen, "team_manage")
        if manage is not None:
            return self._team_action(
                "team_manage",
                manage.center,
                "左下角「管理队伍」已识别，进入编队",
            )

        self._team_ready("队伍页上没有可用的配队入口（管理队伍与顶端加号都不在）")
        return None

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
                self.stamina_budget.consume()
                self._stamina_purchase_pending = False
            return None
        if self.stamina_budget.exhausted:
            raise StaminaExhausted(
                f"生命之叶已补充{self.stamina_replenished}次，按设置停止运行"
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
                ("剧情播放", "通关提示", "额外奖励", "下一关入口"),
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
                    # 进「进行任务」之前先确认队伍有没有空位：故事关卡会给一支
                    # 不满员的预设队伍，空位上是会闪的黄色光圈；这种页面上直接点
                    # 「进行任务」游戏不给反应（实测连点 4 次画面不动）。
                    team_action = self._configure_team(screen)
                    if team_action is not None:
                        return team_action
                    if self._team_release_reason:
                        # 放行必须留痕：凭什么认定这一队可以开打，写进同一行日志。
                        reason = (
                            f"{reason}；队伍放行依据={self._team_release_reason}"
                        )
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

        self._confirmed_page = ""
        if self.story_cutscene and self.state in (
            StoryState.WAIT_SKIP_CONFIRM,
            StoryState.STORY_CUTSCENE,
        ):
            self.state = StoryState.STORY_CUTSCENE
            return None
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
            # ⚠️ 配队这几个计数**必须一起回滚**。2026-11-22 10:00 实跑：
            # 预览先跑一遍 next_action（_configure_team 在这里推进了计数、
            # 还可能调 _team_ready 把 _team_last_action 清空），而快照没盖住这几个
            # 字段 ⇒ 副作用泄漏到正式那一遍：
            #   * 「第 3 次点顶端加号」下一帧变「第 6 次」（每帧翻倍）；
            #   * _team_last_action 被清成空串 ⇒ 永远走「点顶端加号」分支，
            #     再也不会滚动换英雄，对着列表顶端那颗加号连点到 4 次未转场。
            self._team_placements,
            self._team_asked,
            self._team_empty_asks,
            self._team_last_action,
            self._team_same_count,
            self._team_release_reason,
            self._team_list_fp,
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
                self._team_placements,
                self._team_asked,
                self._team_empty_asks,
                self._team_last_action,
                self._team_same_count,
                self._team_release_reason,
                self._team_list_fp,
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
        StoryState.STORY_CUTSCENE: 180,
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
        stamina_enabled: bool = True,
        stamina_limit: int | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        # 路线选项注入状态机：默认值与改动前完全一致。
        machine.stamina_budget = StaminaBudget(
            enabled=stamina_enabled, limit=stamina_limit
        )
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(
                mode="story",
                mode_label="主线",
                # 剧情过场（演出在播、无 HUD、无战前按钮、无可点动作）不许再被
                # 当成「战斗画面无法识别」误杀。启用后：认不出但画面在动就继续等，
                # 连续 180 秒一直在动仍认不出才报 scene_unrecognized。
                # ⚠️ 只给主线开：其余路线保持 0（= 45 秒硬判，行为不变）。
                unrecognized_motion_grace_seconds=180,
            ),
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

    def _perform_action(self, action: StoryAction) -> None:
        """配队要「上滑换英雄」，这是主循环唯一的非点击动作。"""
        if action.name == "team_scroll":
            start = action.point
            self.runtime.swipe(
                start, (start[0], start[1] - 120), 400, action.name
            )
            return
        self.runtime.click(action.point, action.name)

    def _action_retry_seconds(self, action_name: str) -> float:
        """配队是一串「点一下、看一帧」的短动作，不能按 45 秒重试。

        45 秒是给「换页动作没反应」留的观察窗；配队动作不换页，按 45 秒重试
        会让补一个人卡半分钟。1.5 秒足够让画面刷出紫加号/列表位移。
        """
        if action_name.startswith("team_"):
            return 1.5
        return super()._action_retry_seconds(action_name)

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

