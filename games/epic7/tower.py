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
| RESULT | 结算页 | 点右下角按钮 | **TEAM**（下一层，闭环）／**CONQUERED**（打满了） |
| CONQUERED | 「征服欧多马顿塔」 | **不点任何东西**（终点） | 收工 |

⚠️ **`RESULT` 有两个出口，靠「点完之后落到哪」自己分**：第 N（<25）层点下去
约 7 秒落到准备战斗页（`TEAM`，继续下一层）；第 25 层点下去弹出
「征服欧多马顿塔」叙述屏（`CONQUERED`，整条路线到此结束）。

> **「征服」这一屏 = 整条月塔路线的终点**（用户 2026-10-09 实机拍板）：
> 「一碰到这个界面就代表要结束了，就是整个环节的最终的一个终点」。
> 认出它立刻走 `FloorsConquered`（退出码 2，文案「月塔层数已打满」），
> **一个按钮都不点**，随后按统一的收尾机制回大厅。
>
> ⚠️ 别把这一屏当「过场页」去点它底部的「点击关闭」：点了会回到月塔主页
> （实测），而那时**进度已经清空**（主页显示「已占领层 并领取了奖励」）——
> 再往下走既没有业务，又可能误开新的一轮。终点就该收手。

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
from auto_game_unified.core.matcher import (
    MATCH_MODE_RAW,
    Match,
    find_template,
    load_template,
)
from auto_game_unified.core.runtime import StaminaExhausted
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
    resolve_auto_state,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile
from auto_game_unified.games.epic7.evidence.tower import (
    MATCH_MODES as TOWER_MATCH_MODES,
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
    # 打满 25 层后弹出的「征服欧多马顿塔」叙述屏 —— **整条路线的终点**。
    # 认出它 ⇒ 立刻收工（``FloorsConquered``，退出码 2），**不点任何东西**。
    CONQUERED = "conquered"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    TowerState.HOME: "月塔主页",
    TowerState.FLOOR_LIST: "楼层列表",
    TowerState.TEAM: "准备战斗",
    TowerState.BATTLE: "战斗中",
    TowerState.CARD: "选择装置",
    TowerState.CARD_CONFIRM: "选择装置确认",
    TowerState.RESULT: "月塔结算",
    TowerState.CONQUERED: "月塔已征服",
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
    # 「确定要从选择的阶段开始吗？」确认框的**固定文案**（不含阶段号）。
    # 点入场后、所选阶段已征服时弹出；点「确认」= 重置从第 1 层开始（用户 2026-10-30 确认）。
    reset_confirm_title: np.ndarray
    floor_select_team: np.ndarray
    team_battle_start: np.ndarray
    prepare_title: np.ndarray
    card_decide: np.ndarray
    card_hint: np.ndarray
    result_clear: np.ndarray
    conquer_title: np.ndarray
    # 战斗里「自动战斗关着」的图标 —— 复用 story 的那一张，不另做。
    auto_off: np.ndarray
    evidence: EvidenceProfile | None = None


def build_tower_templates(template_dir: Path) -> TowerTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return TowerTemplates(
        season_tower_title=load("season_tower_title"),
        home_enter=load("home_enter"),
        reset_confirm_title=load("reset_confirm_title"),
        floor_select_team=load("floor_select_team"),
        team_battle_start=load("team_battle_start"),
        prepare_title=load("prepare_title"),
        card_decide=load("card_decide"),
        card_hint=load("card_hint"),
        result_clear=load("result_clear"),
        conquer_title=load("conquer_title"),
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
    # 判据 -> 比对口径。与 `_THRESHOLDS` / `_REGIONS` 同一套纪律：类常量
    # **镜像证据画像**，再由 `__init__` 用真实画像覆盖（见那里）。
    _MATCH_MODES = TOWER_MATCH_MODES

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
    # 「确认重置阶段」弹窗里的「确认」按钮（2026-10-30 实测：文字 x 1094~1149 / y 794）。
    # 它就在弹窗正中偏右，位置由弹窗布局决定、不随阶段变。
    _POINT_RESET_CONFIRM = (1122, 794)
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
            self._MATCH_MODES = {
                key: atom.match_mode
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
            # 比对口径由证据画像声明（`auto_off` 是背景无关的白掩膜，其余是原样 RGB）。
            # 这里**只转发**，不在路线里复刻预处理 —— 复刻就是把同一个判据抄成两份。
            mode=self._MATCH_MODES.get(name, MATCH_MODE_RAW),
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
        if state == TowerState.CONQUERED:
            # 打满后的终点屏。⚠️ 它**也**要排除 `result_clear`：那一屏是半透明
            # 弹窗叠在结算页上，但实测 `result_clear` 掉到 0.3141（不过阈），
            # 所以只靠标题一条就够，这里不必再加排除条件。
            return self._locate(screen, "conquer_title") is not None
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
        auto = self._locate(screen, "auto_off")
        auto_score = "无" if auto is None else f"{auto.score:.4f}"
        # 布局（强证据）与图标（弱证据）的合并规则见 `resolve_auto_state` 的 docstring
        # ——2026-10-09 月塔事故就是旧写法「无条件信图标」导致的。
        resolved = resolve_auto_state(controls, auto is not None)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[resolved]
        auto_evidence = f"布局={controls.value} 自动关图标={auto_score}"
        if resolved is not controls:
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
            # ⚠️⚠️ **先看是不是「确认重置阶段」弹窗**（2026-10-30）。
            #
            # 点「入场」后，如果所选阶段**已经征服**，游戏会弹这一层：
            # 「确定要从选择的阶段开始吗？……重置阶段后，将从1层开始进行。」
            # 用户 2026-10-30 拍板：**就是要从头开始打，点确认没问题**。
            #
            # 之前没有这条判据：导航以为还停在月塔主页（弹窗把页面压暗，但
            # ``home_enter`` 照样认得出），于是连点 4 次入场 ⇒ 报
            # 「动作[enter-tower]未稳定进入[楼层列表]」。
            #
            # ⚠️ 必须排在 ``_required(home_enter)`` **之前** —— 弹窗盖住主页时
            # 两颗锚点同时成立，先判弹窗才能走上正确的分支。
            if self._locate(screen, "reset_confirm_title") is not None:
                return self._action(
                    "confirm-reset", self._POINT_RESET_CONFIRM,
                    source_page="确认重置阶段",
                    target_states=(TowerState.FLOOR_LIST,),
                    reason="所选阶段已征服，确认重置后从第1层开始打",
                )
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
            # ⚠️ 终点屏也可能在这里撞上（监督按 `result_visible` 收手时画面已经翻到
            # 征服弹窗）：**立刻按打满收工**，别掉进下面的 `UnrecognizedScreen`
            # （那会变成「月塔战斗画面未识别」超时 —— 把正常打满报成故障）。
            if self.is_in_state(screen, TowerState.CONQUERED):
                raise FloorsConquered("月塔第 25 层已征服（「征服欧多马顿塔」）")
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
                # **准备战斗页**，不是直接开打。所以正常那一条边是 RESULT -> TEAM。
                #
                # ⚠️⚠️ **但第 25 层是另一条边**（2026-10-09 实机）：打满时右下角那个
                # 槽位的文字从「下一层」变成「征服」，点下去弹出「征服欧多马顿塔」
                # 叙述屏 ⇒ 落到 CONQUERED，整条路线到此结束。
                #
                # 两个目标都写进 ``target_states``，靠「点完之后哪一屏先出现」自己分。
                # **不需要**为「征服」另做一枚按钮判据 —— 那一屏不遮住这个按钮，
                # 同一枚模板会同时命中两屏（实测间距 +0.0003，等于没有）；而且两个
                # 文字本就在**同一个按钮槽**（绿底 bbox 逐像素一致），点谁都一样。
                # 详见 ``evidence/tower.py`` 的「conquer_button 刻意不存在」。
                #
                # ⚠️ 顺序有意义：`CONQUERED` 排在 `TEAM` 前面。两页实测互斥
                # （征服屏上 `team_battle_start` 只有 0.4323），这里的顺序只是
                # 「万一同时成立时先认终点」—— 宁可早收工，不可把终点当成下一层。
                target_states=(TowerState.CONQUERED, TowerState.TEAM),
                reason="识别到月塔结算，点击右下角按钮（下一层／打满征服）",
            )

        if self.state == TowerState.CONQUERED:
            # ⚠️⚠️ **整条路线的终点**（用户 2026-10-09 拍板）：认出这一屏 ⇒ 立刻收工。
            #
            # 抛 `FloorsConquered` 而不是返回 None：返回 None 只会让主循环每拍
            # `sleep(poll_seconds)` 空转，直到 60 秒状态超时——那是**假故障**
            # （走 `RuntimeError`、退出码 1），而这里分明是「正常打满了」（退出码 2）。
            # 走 `ResourceExhausted` 那条通道，收尾也会照常回家（见基类 `_close_out`）。
            #
            # ⚠️ 抛之前**先确认这一屏还在**：主循环的结论门槛要求连续两帧一致，
            # 这里 `_required` 失败会抛 `UnrecognizedScreen`（不采信结论），
            # 正是我们想要的 —— 单帧抖动不该宣布「打满了」。
            self._required(screen, "conquer_title")
            raise FloorsConquered("月塔第 25 层已征服（「征服欧多马顿塔」）")

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
# - **CONQUERED 必须排最前**：它是**整条路线的终点**（打满 25 层的征服弹窗）。
#   排在 HOME 前面有两个理由：① 语义上「认出终点」应当压过一切别的判断；
#   ② 那一屏是半透明弹窗叠在结算页上，页面上**同时残留着**别的页面的元素，
#   只是实测都不过阈（`home_enter` 0.5780 / `result_clear` 0.3141 /
#   `team_battle_start` 0.4323）—— 但顺序上先认它，将来判据漂移也不会误接力。
# - **HOME 排第二**：`home_enter` 是月塔主页独有判据（实测他页最高 0.430），
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
    TowerState.CONQUERED,
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
        # ⚠️ 只有 HOME 给 ``entry``（月塔主页那一页名）。
        # ``CONQUERED`` 排在最前但**不给 entry**：它不是「可以从这一页接着跑」的
        # 业务页，而是终点 —— 接力认出它，下一步就是抛 ``FloorsConquered`` 收工。
        # 给它一个 entry 会让导航器先跑一趟主页，白折腾还多一次误点风险。
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

    # ⚠️⚠️ 月塔右下角是**同一个绿色按钮槽**，转场后换按钮 ⇒ 「原地重按」那一手
    # 会被游戏**攒着**、等下一屏出来时一次性兑现（2026-10-09 两次实跑，诊断帧都是
    # 战斗进行中的画面）。所以月塔开启基类的「画面冻住就不补点」闸门 ——
    # 判据、依据与量化见 ``transactional_runner_base._retry_block_reason``。
    #
    # ⚠️ **第一版是列动作名单**（``_RETRY_UNSAFE_ACTIONS = {"select-team"}``），
    # 已废弃，两处都错：
    #
    #   1. **落点重叠是布局的普遍属性，不是那一个槽位的特例**。实测
    #      （``.workbuddy/_retry_overlap.py``，按钮本体宽 231~242px）：
    #
    #      ==============  ===============  ================  =======
    #      动作             落点             下一屏的按钮      偏差
    #      ==============  ===============  ================  =======
    #      ``enter-tower`` (1640, 1055)     ``select-team``  59 px
    #      ``select-team`` (1698, 1044)     ``battle-start`` 28 px
    #      ``next-floor``  (1787, 1041)     ``battle-start`` 61 px
    #      ``battle-start``(1726, 1040)     （下一屏是战斗）   无害
    #      ==============  ===============  ================  =======
    #
    #      四条里三条压住下一屏的按钮，名单只列了一条。旧注释还写着
    #      「``enter-tower`` / ``battle-start`` / ``next-floor`` 的落点与别的按钮离得远、
    #      重按无害」——**这句是错的**，别照抄。
    #   2. **名单的尺子本身就不好定**：第一版拿「两点距离 <= 40px」当判据，只抓到
    #      28px 那条，59px / 61px 两条全部漏掉。而且用户明确否掉了「一律禁止重试」：
    #      那会把「真的没点到」也一起禁掉。
    #
    # ⇒ 改问**当下这一下的危险程度**：画面还在动 = 真没点到，允许补点；画面完全冻结
    # = 游戏正忙、这一下会被攒着，只等。
    #
    # ⚠️ 判据必须落在**现象**上，不能退回成名单 —— 名单的失效方式是「漏」，而漏的那
    # 一次恰恰是把战斗误开起来的那一次。
    _RETRY_REQUIRES_MOTION = True

    # 点完先静置再截第一帧。默认 ``None`` ⇒ 退化成 ``poll_seconds``（1.0 秒）。
    # ⚠️ 这个值**不承担安全职责**（那是上面 ``_RETRY_REQUIRES_MOTION`` 的活），
    # 它只是让第一帧尽量落在转场窗口之外、少空转几帧。取 3.0 的参照是竞技场（1.5）
    # —— 月塔转场更慢；再大意义有限，反而会拖慢「真·点击失效」的发现。
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
