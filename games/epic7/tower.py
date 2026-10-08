"""欧多马顿塔（月塔）的 fail-closed 自动化。

## 业务口径（用户 2026-10-08 拍板，全部有真机实测支撑）

- **一层的定义** = 「点战斗开始」→「结算页点下一层」。`completed_cycles` 在
  **点下一层**那一刻 +1。
- **每层耗 15 点体力**（实测 1318→1303→1288→1273，逐层 -15）。
- **共约 25 层**，默认打满 25 层 = 正常停止。
- **不允许补充体力**：体力不够时**只识别、不购买**（`StaminaExhausted`，
  退出码 2，正常业务退出）。月塔没有「叶子不够就买」这条路 —— 补充不值。
- **三选一固定选中间那张**（用户拍板）。
- **阶段选择弹窗**（首次进场、一赛季只出现一次）**暂不实装**：遇到这一屏会走
  「认不出画面」的安全路径，不误点。等哪个赛季再遇到时补。

## 状态机（一次完整循环）

| 状态 | 页面 | 动作 | 到哪 |
|---|---|---|---|
| HOME | 月塔主页 | 点「入场」 | FLOOR_LIST |
| FLOOR_LIST | 楼层列表 | 点「选择队伍」 | TEAM |
| TEAM | 准备战斗 | 点「战斗开始」 | BATTLE |
| BATTLE | 战斗中 | 等（交战斗监督） | CARD |
| CARD | 三选一 | 点中间卡 → 点「决定装置」 | CARD_CONFIRM |
| CARD_CONFIRM | 三选一（已选中） | 点「决定装置」 | RESULT |
| RESULT | 结算页 | 点「下一层」 | **TEAM**（下一层，闭环） |

## ⚠️ 两个必须记住的实测事实（2026-10-08）

1. **点「下一层」回到的是准备战斗页（TEAM），不是直接开打**。
   实测：点击后约 **7 秒**落到 TEAM（`team_battle_start = 0.95`），体力未扣。
   ⇒ 所以 `RESULT --下一层--> TEAM` 这条边是**闭环**，下一层**不必再点「选择队伍」**。
   （早先一次勘察误判成「直接开打」，是看帧时机太早；这次连拍 20 秒逐秒记录才坐实。）
2. **`CARD` 与 `CARD_CONFIRM` 是同一页的两态**：三张卡都未选中时
   「决定装置」是**暗态**（不可点，实测该区亮占比 0.000；点击无效）；
   点中间卡后该卡出现描边、按钮转亮（0.100）。
   ⇒ 拆成两个状态，**先点卡再点按钮**，避免在暗态上白点一次。
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    valid_game_frame,
)
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.runtime import StaminaExhausted
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.tower import (
    REFERENCE_SIZE as TOWER_REFERENCE_SIZE,
    REGIONS as TOWER_REGIONS,
    THRESHOLDS as TOWER_THRESHOLDS,
    build_tower_evidence,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.template_paths import is_template_root
from auto_game_unified.games.epic7.transactional_runner_base import (
    TransactionalRunnerBase,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class TowerState(Enum):
    HOME = "home"
    FLOOR_LIST = "floor_list"
    TEAM = "team"
    BATTLE = "battle"
    CARD = "card"
    CARD_CONFIRM = "card_confirm"
    RESULT = "result"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    TowerState.HOME: "月塔主页",
    TowerState.FLOOR_LIST: "楼层列表",
    TowerState.TEAM: "准备战斗",
    TowerState.BATTLE: "战斗中",
    TowerState.CARD: "选择装置",
    TowerState.CARD_CONFIRM: "选择装置确认",
    TowerState.RESULT: "月塔结算",
}


def state_label(state: TowerState) -> str:
    return STATE_LABELS.get(state, state.value)


class FloorsConquered(StaminaExhausted):
    """月塔层数打满（默认 25 层）。

    ⚠️ 与 ``PostersExhausted`` 同构：继承来的 ``stop_label`` 是「生命之叶耗尽」，
    但月塔打满时缺的**不是体力**，是「这一轮能打的层数」。主循环统一把
    ``停止=`` 后面的文案取异常自带的那一个（见 ``core.runtime.ResourceExhausted``），
    写错会把日志和通知带偏 —— 用户看到「生命之叶耗尽」会以为要去买叶子。
    """

    stop_label = "月塔层数已打满"


@dataclass(frozen=True)
class TowerAction(RouteAction):
    """月塔的一个动作。

    公共字段见 ``route_action.RouteAction``；``source_state`` / ``target_states`` 是
    事务型主循环（``TransactionalRunnerBase._execute_transition``）认的那一份契约。
    """

    source_state: TowerState | None = None
    target_states: tuple[TowerState, ...] = ()


@dataclass(frozen=True)
class TowerTemplates:
    season_tower_title: np.ndarray
    home_enter: np.ndarray
    floor_select_team: np.ndarray
    team_battle_start: np.ndarray
    prepare_title: np.ndarray
    card_decide: np.ndarray
    card_hint: np.ndarray
    result_clear: np.ndarray
    # 战斗里「自动战斗关着」的图标 —— 复用 story 的那一张，不另做。
    auto_off: np.ndarray
    evidence: EvidenceProfile | None = None


def build_tower_templates(template_dir: Path) -> TowerTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return TowerTemplates(
        season_tower_title=load("season_tower_title"),
        home_enter=load("home_enter"),
        floor_select_team=load("floor_select_team"),
        team_battle_start=load("team_battle_start"),
        prepare_title=load("prepare_title"),
        card_decide=load("card_decide"),
        card_hint=load("card_hint"),
        result_clear=load("result_clear"),
        # ⚠️ 复用 story 的自动战斗关闭图标（与远征/主线同一个控件、同一套渲染），
        # 不另裁一份 —— 同内容跨路线复用的前提是**同一个后端**（都是模拟器）。
        auto_off=load_template(str(template_dir.parent / "story" / "auto_off.png")),
        evidence=build_tower_evidence(template_dir),
    )


class TowerStateMachine:
    """月塔状态机：纯状态驱动（按 ``self.state`` 分派）。"""

    _REFERENCE_SIZE = TOWER_REFERENCE_SIZE
    _THRESHOLD = 0.88
    _THRESHOLDS = TOWER_THRESHOLDS
    _REGIONS = TOWER_REGIONS

    # 允许为 ``None`` 的模板 —— **月塔一个都不许**。
    #
    # 本集合与 `evidence/tower.py` 的 `_OPTIONAL_TEMPLATES` 必须**逐字一致**
    # （`test_whitelist_matches_the_evidence_profile` 钉住）。
    #
    # 为什么是空集：`_locate()` 对**任何** `None` 模板都静默返回 `None`，于是
    # 「模板文件缺失」与「画面上没这个控件」在代码里长得一模一样 —— 判据悄悄失效
    # 没人看得出来（远征 `empty_posters` 就这样丢了 6 次超时才被发现）。
    # 月塔起步就按远征 2026-10-04 之后的口径来：**少一张图 = 配置错误**。
    _OPTIONAL_TEMPLATES: frozenset[str] = frozenset()

    # ---- 点击点：**一律用常量**，不靠模板 center ----
    #
    # ⚠️ 项目纪律：裁剪会带动点击点。本路线的判据模板都是「按钮文字」，
    # 若拿 `match.center` 当点击点，将来任何一次重新裁模板都会**静默挪动**点击位置。
    # ⇒ 判据与点击点分离：模板只回答「在不在」，点在哪儿由下面的常量说了算。
    # 全部坐标来自 2026-10-08 实机测量（见 `_tower_stage/MEASUREMENTS.md`）。
    _POINT_ENTER = (1640, 1055)
    _POINT_SELECT_TEAM = (1698, 1044)
    _POINT_BATTLE_START = (1726, 1040)
    # 「三选一」固定选中间那张卡（用户拍板）。卡位实测 c=(958,300)（图标）/ 卡面到 y≈870。
    _POINT_MIDDLE_CARD = (958, 500)
    _POINT_DECIDE = (1138, 1040)
    _POINT_NEXT_FLOOR = (1787, 1041)

    def __init__(
        self,
        templates: TowerTemplates | Path,
        *,
        initial_state: TowerState = TowerState.HOME,
    ) -> None:
        self.templates = (
            build_tower_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        if self.templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in self.templates.evidence.atoms.items()
            }
            self._THRESHOLDS = {
                key: atom.threshold
                for key, atom in self.templates.evidence.atoms.items()
            }
        self.completed_cycles = 0
        # 本层「中间卡是否已点过」—— CARD -> CARD_CONFIRM 的一次性闸门。
        self.card_picked = False
        self.auto_click_attempted = False
        self._confirmed_page = ""
        # 「接力」进来的落点；None = 本轮是正常从月塔主页开始的。
        self.resumed_from: Optional[TowerState] = None

    def resume_from(self, state: TowerState) -> None:
        """拨到用户停下的那一步，原样接管进度继续往下跑。

        月塔的 ``next_action`` 是**纯状态驱动**的（按 ``self.state`` 分派），
        所以接力必须把状态拨准，否则第一帧就会走到 ``_required`` 失败或点错按钮。

        ``card_picked`` / ``auto_click_attempted`` 必须复位：接力进来的这一层
        不是本进程点开的，带着上一层的账本会让「点中间卡」这一步被跳过
        （卡没选、决定装置是暗的 ⇒ 白等到超时）。
        """
        self.state = state
        self.resumed_from = state
        self.card_picked = False
        self.auto_click_attempted = False
        self._confirmed_page = ""

    # ---- 基础工具 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        template = getattr(self.templates, name)
        if template is None:
            # 只有白名单里的模板才允许缺席；月塔白名单是空集 ⇒ 这里必然抛错。
            if name not in self._OPTIONAL_TEMPLATES:
                raise RuntimeError(
                    f"模板 {name} 缺失且未登记为可选：判据会静默失效。"
                    f"要么补上模板文件，要么把它加进 "
                    f"{type(self).__name__}._OPTIONAL_TEMPLATES 并说明理由"
                )
            return None
        return find_template(
            screen,
            template,
            self._THRESHOLDS.get(name, self._THRESHOLD),
            region=self._REGIONS[name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        match = self._locate(screen, name)
        if match is None:
            raise UnrecognizedScreen(f"月塔锚点 {name} 未识别")
        return match

    def is_in_state(self, screen: np.ndarray, state: TowerState) -> bool:
        if state == TowerState.HOME:
            return self._locate(screen, "home_enter") is not None
        if state == TowerState.FLOOR_LIST:
            return self._locate(screen, "floor_select_team") is not None
        if state == TowerState.TEAM:
            return (
                self._locate(screen, "team_battle_start") is not None
                and self._locate(screen, "prepare_title") is not None
            )
        if state == TowerState.BATTLE:
            # 局内：要么认得出结算页（最后一下打完了），要么场面判据成立。
            return (
                self._locate(screen, "result_clear") is not None
                or battle_scene_visible(screen)
            )
        if state in {TowerState.CARD, TowerState.CARD_CONFIRM}:
            return (
                self._locate(screen, "card_decide") is not None
                and self._locate(screen, "card_hint") is not None
            )
        if state == TowerState.RESULT:
            return self._locate(screen, "result_clear") is not None
        return False

    def _confirm_page(self, label: str) -> None:
        self._confirmed_page = label

    def _action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_states: tuple[TowerState, ...],
        reason: str,
    ) -> TowerAction:
        return TowerAction(
            name,
            point,
            source_page=source_page,
            target_pages=tuple(state_label(item) for item in target_states),
            reason=reason,
            source_state=self.state,
            target_states=target_states,
        )

    def commit(self, action: TowerAction, target: TowerState) -> None:
        if action.source_state is not self.state:
            raise RuntimeError("月塔动作来源状态与当前状态不一致")
        if target not in action.target_states:
            raise RuntimeError("月塔动作目标状态不在合同中")
        self.state = target
        # ⚠️ **一层的收尾是「结算页点下一层」**，不是「回主页」——
        # 月塔打完不回月塔主页，而是直接进下一层的准备战斗页（实测 2026-10-08）。
        # 所以计数的位置与远征不同，必须是这一条。
        if action.name == "next-floor" and target is TowerState.TEAM:
            self.completed_cycles += 1
        if target is TowerState.BATTLE:
            self.auto_click_attempted = False
        # 新的一层开始点卡：把本层的选卡闸门复位。
        if target is TowerState.CARD:
            self.card_picked = False

    def action_source_visible(self, screen: np.ndarray, action: TowerAction) -> bool:
        if action.name == "enable-auto-battle":
            return self._locate(screen, "auto_off") is not None
        return (
            action.source_state is not None
            and self.is_in_state(screen, action.source_state)
        )

    def action_target_state(
        self, screen: np.ndarray, action: TowerAction
    ) -> TowerState | None:
        if action.name == "enable-auto-battle":
            # 自动战斗开启后这个图标会消失；用「图标没了但仍在局内」判成功。
            if (
                self._locate(screen, "auto_off") is None
                and battle_scene_visible(screen)
            ):
                return TowerState.BATTLE
            return None
        for target in action.target_states:
            if self.is_in_state(screen, target):
                return target
        return None

    # ---- 战斗监督 ----

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
        auto = self._locate(screen, "auto_off")
        auto_score = "无" if auto is None else f"{auto.score:.4f}"
        auto_evidence = f"布局={controls.value} 自动关图标={auto_score}"
        # 「右上角关自动图标 ⇒ 判定为手动」：按钮布局判成 transition（看不出长相）
        # 时靠这个图标兜底 —— 否则那一帧会停在「未知」，而「未知」按安全设计是
        # 不许点自动的，战斗就会干等到超时。图标认不到就不覆盖上面的布局判定。
        if auto is not None:
            auto_state = AutoBattleState.MANUAL
            auto_evidence += " 来源=右上角自动关闭图标"
        progressing = valid_game_frame(screen) and meaningful_change(
            previous_screen, screen
        )
        return BattleObservation(
            # 月塔入口页（准备战斗）的判据就是「战斗开始」按钮，
            # 但本函数只在**已经移交战斗监督之后**被调用，所以这里恒为 False：
            # 真落到准备战斗页说明上一层的「下一层」没点成，那由状态超时兜。
            pre_battle_visible=False,
            battle_visible=(
                self._locate(screen, "card_decide") is None
                and self._locate(screen, "card_hint") is None
                and battle_scene_visible(screen)
            ),
            # ⚠️ 月塔的「打完」不是结算页 CLEAR —— 打完先进**三选一装置页**！
            # 把三选一页当作「结果页」交给监督收手，状态才拨得对（见 _RESULT_STATE）。
            result_visible=(
                self._locate(screen, "card_decide") is not None
                and self._locate(screen, "card_hint") is not None
            ),
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=(
                auto.center
                if auto is not None and auto_state is AutoBattleState.MANUAL
                else None
            ),
            business_progress=progressing,
            allowed_action=None,
            auto_evidence=auto_evidence,
        )

    # ---- 动作分派 ----

    def next_action(self, screen: np.ndarray) -> Optional[TowerAction]:
        if self.state == TowerState.HOME:
            self._required(screen, "home_enter")
            return self._action(
                "enter-tower", self._POINT_ENTER,
                source_page="月塔主页",
                target_states=(TowerState.FLOOR_LIST,),
                reason="识别到月塔主页，点击入场",
            )

        if self.state == TowerState.FLOOR_LIST:
            self._required(screen, "floor_select_team")
            return self._action(
                "select-team", self._POINT_SELECT_TEAM,
                source_page="楼层列表",
                target_states=(TowerState.TEAM,),
                reason="识别到楼层列表，点击选择队伍",
            )

        if self.state == TowerState.TEAM:
            self._required(screen, "team_battle_start")
            self._required(screen, "prepare_title")
            return self._action(
                "battle-start", self._POINT_BATTLE_START,
                source_page="准备战斗",
                target_states=(TowerState.BATTLE,),
                reason="识别到准备战斗，点击战斗开始",
            )

        if self.state == TowerState.BATTLE:
            # 局内：等战斗监督收手。这里只处理两件「局内还要点一下」的事。
            result = self._locate(screen, "result_clear")
            if result is not None:
                # 已经到结算页（极少数情况：监督没接住，主循环自己转到了这一页）
                return None
            # ⚠️ 三选一页同样**返回 None**，不许走到下面的 `UnrecognizedScreen`：
            # 那一页既没有 `result_clear` 也没有战斗场面，但它是「这一层收尾」
            # 的合法落点 —— 监督正要在这里收手。抛错会把整条路线打断
            # （实测：状态还停在 BATTLE、画面已经是三选一的那一帧）。
            if self.is_in_state(screen, TowerState.CARD):
                return None
            auto_off = self._locate(screen, "auto_off")
            if auto_off is not None:
                if self.auto_click_attempted:
                    return None
                self.auto_click_attempted = True
                return self._action(
                    "enable-auto-battle", auto_off.center,
                    source_page="战斗中",
                    target_states=(TowerState.BATTLE,),
                    reason="识别到自动战斗关闭，开启自动战斗",
                )
            if battle_scene_visible(screen):
                return None
            raise UnrecognizedScreen("月塔战斗画面未识别")

        if self.state == TowerState.CARD:
            self._required(screen, "card_decide")
            self._required(screen, "card_hint")
            if self.card_picked:
                # 本层已经点过卡（说明上一次转场没验收过），别再点 —— 直接进确认态。
                self.state = TowerState.CARD_CONFIRM
                return self._decide_action()
            self.card_picked = True
            return self._action(
                "pick-middle-card", self._POINT_MIDDLE_CARD,
                source_page="选择装置",
                target_states=(TowerState.CARD_CONFIRM,),
                reason="识别到三选一装置，点击中间那张卡",
            )

        if self.state == TowerState.CARD_CONFIRM:
            self._required(screen, "card_decide")
            self._required(screen, "card_hint")
            return self._decide_action()

        if self.state == TowerState.RESULT:
            self._required(screen, "result_clear")
            return self._action(
                "next-floor", self._POINT_NEXT_FLOOR,
                source_page="月塔结算",
                # ⚠️ 实测（2026-10-08，逐秒连拍 20 帧）：点「下一层」后约 7 秒落到
                # **准备战斗页**，不是直接开打。所以这条边是 RESULT -> TEAM。
                target_states=(TowerState.TEAM,),
                reason="识别到月塔结算，点击下一层",
            )

        raise RuntimeError(f"月塔状态机遇到不支持的状态：{self.state.value}")

    def _decide_action(self) -> TowerAction:
        return self._action(
            "decide-device", self._POINT_DECIDE,
            source_page="选择装置确认",
            target_states=(TowerState.RESULT,),
            reason="中间卡已选中，点击决定装置",
        )

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self.card_picked,
            self.auto_click_attempted,
            self._confirmed_page,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.card_picked,
                self.auto_click_attempted,
                self._confirmed_page,
            ) = snapshot


# 导航链上可以接力的页面（= `navigation.page_label()` 里的名字）。
# 月塔的导航是一条四级链：大厅 → 战斗菜单 → 赛季菜单 → 月塔主页。
# 与远征**共用前三级**（同一屏赛季页），只是最后一步点的是月塔卡片。
TOWER_BATTLE_MENU_PAGE = "battle_menu"
TOWER_SEASON_PAGE = "season_menu"
TOWER_ENTRY_PAGE = "tower_home"
TOWER_RESUME_PAGES = frozenset(
    {
        TOWER_BATTLE_MENU_PAGE,
        TOWER_SEASON_PAGE,
        TOWER_ENTRY_PAGE,
    }
)


# 「接力」探测顺序 —— **顺序即优先级**，不能改。
#
# - **HOME 必须排最前**：`home_enter` 是月塔主页独有判据（实测他页最高 0.430），
#   两页之间没有包含关系，但主页是「刚进场」的自然落点，优先认它。
# - **CARD_CONFIRM 排在 CARD 前面**：两态共用同一组判据（`card_decide` +
#   `card_hint` **同时成立**，实测都 1.000），机器分不出「卡选了没有」。
#   跟着 `CARD_CONFIRM` 那条「已经点过卡」的口径走更安全：它的动作是直接点
#   「决定装置」，而如果卡其实没选，那一下是暗按钮、点了无效 —— 失败可见，
#   不会误点。反过来若先认 CARD，会**重点一次卡**（把已选的换成中间那张）。
# - **TEAM 排在 FLOOR_LIST 前面**：`floor_select_team` 在准备战斗页上只有 0.558
#   （不到阈），两者实测不冲突；但准备战斗页是「一层进行中」的落点，
#   先认它更符合「从这一层接着打」的语义。
# - **RESULT 排在 BATTLE 前面**：结算页上 `battle_scene_visible` 也可能为真
#   （背景仍是战场），先认结算页才不会把奖励白扔掉。
_TOWER_RESUME_ORDER: tuple[TowerState, ...] = (
    TowerState.HOME,
    TowerState.CARD_CONFIRM,
    TowerState.RESULT,
    TowerState.TEAM,
    TowerState.FLOOR_LIST,
    TowerState.CARD,
    TowerState.BATTLE,
)


def detect_resume_point(
    machine: "TowerStateMachine",
    screen: np.ndarray,
    *,
    observed_page: Optional[str] = None,
) -> Optional[ResumePoint]:
    """月塔开局接力：认出用户停在月塔一环里的哪一页。

    识别不到返回 None，调用方回退到「回大厅 → 从战斗菜单重新导航」（失败关闭）。

    ``observed_page`` 传导航器认出来的页面名。战斗菜单 / 赛季菜单这两页
    **只有导航器认得出来**（它们不在月塔状态机里），所以这个参数对这两页是必需的。
    """
    if observed_page in (TOWER_BATTLE_MENU_PAGE, TOWER_SEASON_PAGE):
        return ResumePoint(
            "战斗菜单" if observed_page == TOWER_BATTLE_MENU_PAGE else "赛季菜单",
            None,
            observed_page,
        )
    for state in _TOWER_RESUME_ORDER:
        if not machine.is_in_state(screen, state):
            continue
        entry = TOWER_ENTRY_PAGE if state is TowerState.HOME else None
        return ResumePoint(state_label(state), state, entry)
    return None


class TowerRunner(TransactionalRunnerBase):
    """月塔 Runner：**事务型主循环**（见 ``transactional_runner_base``）。

    与远征同一族：状态驱动、``commit()`` 才前进、目标页连续两帧才算转场成功。

    ⚠️ **不是** ``ModeRunnerBase`` 的子类 —— 那是另一套主循环。理由与表态见
    ``modes.TRANSITION_EXEMPT`` / ``modes.CONCLUSION_GATE_DECLARATION``。
    """

    _MODE_LABEL = "月塔"

    # 月塔的转场比远征慢：实测「结算页 -> 准备战斗页」约 **7 秒**，
    # 而「战斗开始 -> 进战斗」还要转场动画。统一给 60 秒（比远征的 45 秒宽），
    # 仍远小于「一层打满」的量级，不会把真故障拖成假成功。
    _STATE_TIMEOUT_SECONDS = 60

    # 状态 → 状态机里的落点，供基类判「战斗有没有打起来」「有没有打到结算页」。
    _BATTLE_STATE = TowerState.BATTLE
    # ⚠️ 月塔的「打完」落脚点是**三选一装置页**，不是 CLEAR 结算页！
    # 把监督的收手点对到 CARD，主循环接下来才会去点卡、点决定装置，
    # 最后才走到 RESULT。写错会让状态卡在 CARD 没人驱动。
    _RESULT_STATE = TowerState.CARD
    # 停在局内、状态机又没有别的活要干 ⇒ 直接把这一层交给战斗监督等打完。
    _SETTLED_BATTLE_STATE = TowerState.BATTLE
    # 转场确认**落到战斗页** ⇒ 交战斗监督。
    _HANDOFF_AFTER_TRANSITION_ACTIONS = frozenset({"battle-start"})

    # ⚠️⚠️ **点完先静置 2.5 秒再截第一帧**（2026-10-09，实跑事故）。
    #
    # 默认值是 ``None`` ⇒ 退化成 ``poll_seconds``（1.0 秒），而月塔的转场实测要
    # **2~3 秒**（同一次日志里：大厅→赛季页 2.0 秒、赛季页→月塔主页 3.1 秒、
    # 月塔主页→楼层列表约 3 秒）。1 秒后截图，源页面**当然还在** ⇒ 基类按
    # 「源页连续 2 帧仍在 = 这一下没生效」重试 ⇒ **在转场动画中途又点了一下**。
    #
    # 为什么这一下是**致命**的（不是「多点是多点是」）：月塔右下角那个绿色按钮槽位
    # 是**同一个位置**放不同的按钮 ——
    #   ``_POINT_SELECT_TEAM``  = (1698, 1044)  「选择队伍」（楼层列表）
    #   ``_POINT_BATTLE_START`` = (1726, 1040)  「战斗开始」（准备战斗）
    # 两点相距只有 **28 px**。重试那一下正好落在**已经切过去的**「战斗开始」上
    # ⇒ **直接开打** ⇒ 状态机以为还在等「准备战斗」页，实际人已经在打架
    # ⇒ 那一层白等到 60 秒超时，日志报 ``no_transition_select-team``。
    #
    # ⚠️ 取值 3.0 秒的依据：要**不小于**实测转场时长的上界（同一次日志里
    # 大厅→赛季页 2.0 秒、赛季页→月塔主页 **3.1 秒**、月塔主页→楼层列表约 3 秒）。
    # 取 3.0 之后，第一帧截图就落在转场窗口之外，重试分支**根本不会触发**。
    # ⚠️ 别为了「更保险」一味加大：真「点击无效」时要等满 settle + 重试间隔才
    # 判出来，值太大就迟钝了；3.0 秒相对 60 秒状态超时仍然很小。
    # 竞技场同类问题覆写的是 ``1.5``；月塔转场更慢（多一段过场动画），所以取更大值。
    #
    # ⚠️ 光靠 settle 不够 —— 转场时长会随机器性能波动，所以**同时**在
    # ``action_source_visible`` 里加了第二道防线（见该方法内注释）。
    _SETTLE_SECONDS = 3.0

    def _battle_config(self) -> BattleConfig:
        """战斗看护的两条时限放宽到 20 分钟。

        月塔一层要打完一队怪（可能三波），比竞技场长得多；用 ``BattleConfig``
        的默认值会在打到一半时被判「无业务进展」而收手。
        """
        return BattleConfig(
            mode="tower",
            absolute_seconds=20 * 60,
            no_business_progress_seconds=20 * 60,
        )

    def _after_result_state(self, *, cycle: int) -> None:
        """监督打完一层、状态被拨到**三选一页**之后：把「本层已选卡」的闸门复位。

        ⚠️ 这里必须复位，不能只放在 `commit()` 里：基类是**直接**
        `self.machine.state = self._RESULT_STATE` 赋值的（见
        `transactional_runner_base._run_committed_battle`），**不走 `commit()`**。
        只在 `commit` 里复位的话，第 2 层开始闸门一直是 `True`
        ⇒ 「点中间卡」被整段跳过 ⇒ 卡没选、决定装置是暗的 ⇒ 白等到 60 秒超时。
        ⚠️ 闸门在**状态机**上（`machine.card_picked`），不是 Runner 的属性 ——
        写成 `self.card_picked = False` 会静默地在 Runner 上新建一个没人读的字段。
        """
        self.machine.card_picked = False

    def _state_label(self, state: TowerState) -> str:
        """用月塔自己的中文页面名，别退回枚举的 ``value``（日志和诊断都靠它）。"""
        return state_label(state)
