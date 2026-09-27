from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import date, datetime
import random
from time import sleep as default_sleep
from typing import Any, Callable, NamedTuple, Optional, Sequence

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.supervisor import (
    ConclusionGate,
    StableObservation,
    meaningful_change,
)
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    battle_scene_visible,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.pre_battle import (
    PreBattleMode,
    QuickBattleDetector,
    load_simulator_quick_battle_detector,
    observe_pre_battle,
)
from auto_game_unified.games.epic7.transactional_runner_base import (
    TransactionalRunnerBase,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownWakeResult,
)
from auto_game_unified.games.epic7.evidence.arena import (
    FREE_REFRESH_CONFIRM_REGION,
    FREE_REFRESH_OFFER_REGION,
    FREE_REFRESH_TITLE_REGION,
    RANK_PROMOTION_ARROW_REGION,
    RANK_PROMOTION_CONFIRM_REGION,
    REFERENCE_SIZE as ARENA_REFERENCE_SIZE,
    REGIONS as ARENA_REGIONS,
    THRESHOLDS as ARENA_THRESHOLDS,
    build_arena_evidence,
    classify_arena_selected_scores,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceProfile, EvidenceState


_RANK_PROMOTION_REFERENCE_SIZE = ARENA_REFERENCE_SIZE
_RANK_PROMOTION_ARROW_REGION = RANK_PROMOTION_ARROW_REGION
_RANK_PROMOTION_CONFIRM_REGION = RANK_PROMOTION_CONFIRM_REGION
_FREE_REFRESH_TITLE_REGION = FREE_REFRESH_TITLE_REGION
_FREE_REFRESH_OFFER_REGION = FREE_REFRESH_OFFER_REGION
_FREE_REFRESH_CONFIRM_REGION = FREE_REFRESH_CONFIRM_REGION


def find_rank_promotion_confirm(
    screen: np.ndarray,
    arrow_template: np.ndarray,
    confirm_template: np.ndarray,
    threshold: float = 0.90,
) -> Optional[Match]:
    """Return Confirm only when the promotion arrow and button are both visible."""

    def locate(
        template: np.ndarray,
        region: tuple[int, int, int, int],
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> Optional[Match]:
        scale_x = screen.shape[1] / _RANK_PROMOTION_REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _RANK_PROMOTION_REFERENCE_SIZE[1]
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

    arrow = locate(
        arrow_template,
        _RANK_PROMOTION_ARROW_REGION,
        np.array([35, 80, 70]),
        np.array([100, 255, 255]),
    )
    confirm = locate(
        confirm_template,
        _RANK_PROMOTION_CONFIRM_REGION,
        np.array([0, 0, 140]),
        np.array([179, 110, 255]),
    )
    if arrow is None or confirm is None:
        return None
    return Match(confirm.center, min(arrow.score, confirm.score))


def find_free_refresh_confirm(
    screen: np.ndarray,
    title_template: np.ndarray,
    free_template: np.ndarray,
    confirm_template: np.ndarray,
    threshold: float = 0.90,
) -> Optional[Match]:
    """Return Confirm only for the explicit free opponent-refresh offer."""

    def locate(
        template: np.ndarray,
        region: tuple[int, int, int, int],
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> Optional[Match]:
        scale_x = screen.shape[1] / _RANK_PROMOTION_REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _RANK_PROMOTION_REFERENCE_SIZE[1]
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

    white_lower = np.array([0, 0, 140])
    white_upper = np.array([179, 110, 255])
    title = locate(
        title_template,
        _FREE_REFRESH_TITLE_REGION,
        white_lower,
        white_upper,
    )
    free_offer = locate(
        free_template,
        _FREE_REFRESH_OFFER_REGION,
        np.array([15, 80, 100]),
        np.array([45, 255, 255]),
    )
    confirm = locate(
        confirm_template,
        _FREE_REFRESH_CONFIRM_REGION,
        white_lower,
        white_upper,
    )
    if title is None or free_offer is None or confirm is None:
        return None
    return Match(
        confirm.center,
        min(title.score, free_offer.score, confirm.score),
    )


class ArenaState(Enum):
    LIST = "list"
    SELECTED = "selected"
    TEAM = "team"
    BATTLE = "battle"
    RESULT = "result"
    CONFIRMING = "confirming"


# 日志用画面名：state.value -> 中文画面描述
STATE_LABELS = {
    ArenaState.LIST: "对手列表",
    ArenaState.SELECTED: "对手详情",
    ArenaState.TEAM: "队伍选择",
    ArenaState.BATTLE: "战斗中",
    ArenaState.RESULT: "战斗结果",
    ArenaState.CONFIRMING: "结果确认中",
}


def state_label(state: ArenaState) -> str:
    return STATE_LABELS.get(state, state.value)


class ArenaOutcome(Enum):
    """一局竞技场的结算结果。

    两个判据现在**都有实测正例**（2026-09-25 起）：

    - ``WIN`` ← ``result_victory``（屏幕上的「VICTORY」大字）：真机赢局帧 0.8761~0.8816，
      全库 227 张夹具里除结果页外最高 0.2724。
    - ``LOSE`` ← ``result_defeat``（屏幕上的「DEFEAT」大字）：真机输局帧 0.9871~1.0000，
      **赢局帧只有 0.1090~0.1129**，全库夹具里最高 0.3828。

    ⚠️ 在这之前 ``LOSE`` 是**推理判据**（「积分面板在、VICTORY 不在」），而那份推理的
    兜底锚点 ``result_rating`` 在真机上只有 0.38 ⇒ 实际效果是**输局全被判成 ``UNKNOWN``**
    （2026-09-25 实跑 5 局：3 胜 2 输，报出来是「胜 3（未知 2）」，那两张输局帧现在
    就是新锚点的素材来源）。

    认不出（两个横幅都没有、画面还不是结算页）仍然单列 ``UNKNOWN``，**绝不并入「负」**：
    宁可显示「未知 1」，也不能报一个没把握的比分。
    """

    WIN = "win"
    LOSE = "lose"
    UNKNOWN = "unknown"


OUTCOME_LABELS = {
    ArenaOutcome.WIN: "胜",
    ArenaOutcome.LOSE: "负",
    ArenaOutcome.UNKNOWN: "未知",
}

# 结算画面只留最近这么多张。落盘目录是**仓库内**的 ``docs/manual_review/arena/``
# （会被 git 跟踪），一张全屏 PNG 1~3 MB，无限攒会把仓库撑大；留 10 张足够回看最近一轮。
OUTCOME_FRAME_KEEP = 10


class TicketExhausted(RuntimeError):
    """The game presented its ticket-purchase popup instead of entering battle."""


@dataclass(frozen=True)
class Action:
    name: str
    point: tuple[int, int]
    source_state: ArenaState | None = None
    target_states: tuple[ArenaState, ...] = ()
    reason: str = ""
    irreversible: bool = False


@dataclass(frozen=True)
class ArenaTemplates:
    rank_promotion_arrow: np.ndarray
    list_ready: np.ndarray
    challenge: np.ndarray
    battle_start: np.ndarray
    auto_off: np.ndarray
    confirm: np.ndarray
    rank_confirm: np.ndarray
    no_ticket: np.ndarray
    friendship_ticket_offer: np.ndarray
    ticket_purchase_button: np.ndarray
    # 「购买旗帜」弹窗的双锚点。票耗尽时人**停在浮层里**，必须先点「取消」
    # 退回对手列表，再从那里回家（终点必须在非浮层页上，见
    # docs/maintenance/route_finish_points.md 注①）。
    purchase_title: np.ndarray
    purchase_cancel: np.ndarray
    refresh_title: np.ndarray
    refresh_free: np.ndarray
    refresh_confirm: np.ndarray
    # 结果页的**竞技场专有**内容锚点（见 evidence/arena.py 里的说明）。
    result_rating: np.ndarray
    result_victory: np.ndarray
    result_defeat: np.ndarray
    threshold: float = 0.98
    quick_battle: QuickBattleDetector | None = None
    evidence: EvidenceProfile | None = None


def build_templates(
    template_dir: Path,
    *,
    backend: str = "emulator",
) -> ArenaTemplates:
    evidence = build_arena_evidence(template_dir, backend=backend)
    return ArenaTemplates(
        rank_promotion_arrow=load_template(
            str(template_dir / "global" / "arena_rank_promotion_arrow.png")
        ),
        list_ready=load_template(str(template_dir / "list_ready.png")),
        challenge=load_template(str(template_dir / "challenge.png")),
        battle_start=load_template(str(template_dir / "battle_start.png")),
        auto_off=load_template(str(template_dir / "auto_off.png")),
        confirm=load_template(str(template_dir / "confirm.png")),
        rank_confirm=load_template(str(template_dir / "rank_confirm.png")),
        no_ticket=load_template(str(template_dir / "no_ticket.png")),
        friendship_ticket_offer=load_template(str(template_dir / "friendship_ticket_offer.png")),
        ticket_purchase_button=load_template(str(template_dir / "ticket_purchase_button.png")),
        purchase_title=load_template(str(template_dir / "arena_purchase_title.png")),
        purchase_cancel=load_template(str(template_dir / "arena_purchase_cancel.png")),
        refresh_title=load_template(str(template_dir / "arena_refresh_title.png")),
        refresh_free=load_template(str(template_dir / "arena_refresh_free.png")),
        refresh_confirm=load_template(str(template_dir / "arena_refresh_confirm.png")),
        result_rating=load_template(str(template_dir / "arena_result_rating.png")),
        result_victory=load_template(str(template_dir / "arena_result_victory.png")),
        result_defeat=load_template(str(template_dir / "arena_result_defeat.png")),
        quick_battle=load_simulator_quick_battle_detector(template_dir),
        threshold=0.93 if backend == "pc" else 0.98,
        evidence=evidence,
    )


class ArenaStateMachine:
    """Arena cycle in the game window's local coordinate space.

    Only the first-opponent row lacks its own template; its click point is derived as a
    fixed pixel offset from the live ``list_ready`` anchor (stable at unchanged resolution),
    which preserves location independence without a new asset.
    """

    # Per-template match thresholds. The shared default (templates.threshold) is 0.98;
    # arena UI animates/drifts like story, so the dynamic screens are relaxed here.
    _THRESHOLDS = ARENA_THRESHOLDS

    _REFERENCE_SIZE = (1982, 1132)
    _AUTO_CLICK_POINT = (1690, 96)
    _OPPONENT_STATUS_REGIONS = (
        (600, 320, 220, 135),
        (600, 510, 220, 140),
        (600, 705, 220, 140),
    )
    _FAILED_RED_MIN_RATIO = 0.50
    _AVAILABLE_RED_MAX_RATIO = 0.05
    _REGIONS = ARENA_REGIONS

    _OPPONENT_OFFSETS = (
        (-210, -639),
        (-210, -448),
        (-210, -256),
    )
    _REFRESH_OFFSET = (383, -823)

    _NEXT_STATE = {
        ArenaState.LIST: ArenaState.SELECTED,
        ArenaState.SELECTED: ArenaState.TEAM,
        ArenaState.TEAM: ArenaState.BATTLE,
        ArenaState.BATTLE: ArenaState.RESULT,
    }
    _STATE_TEMPLATE = {
        ArenaState.LIST: "list_ready",
        ArenaState.SELECTED: "challenge",
        ArenaState.TEAM: "battle_start",
        ArenaState.BATTLE: "auto_off",
        ArenaState.RESULT: "confirm",
    }
    _ACTION_NAME = {
        ArenaState.SELECTED: "challenge",
        ArenaState.TEAM: "battle-start",
        ArenaState.BATTLE: "enable-auto",
        ArenaState.RESULT: "confirm-result",
    }

    def __init__(
        self,
        templates: ArenaTemplates,
        *,
        initial_state: ArenaState = ArenaState.LIST,
        choose_opponent: Callable[[Sequence[int]], int] = random.choice,
        backend: str = "emulator",
    ) -> None:
        self.templates = templates
        self.backend = backend
        self.state = initial_state
        self.completed_cycles = 0
        self.choose_opponent = choose_opponent
        if templates.evidence is not None:
            self._REGIONS = {
                key: atom.region for key, atom in templates.evidence.atoms.items()
            }
            self._THRESHOLDS = {
                key: atom.threshold for key, atom in templates.evidence.atoms.items()
            }
        self._selected_opponent: int | None = None
        self._cycle_pending = initial_state == ArenaState.CONFIRMING
        # 「接力」进来的落点；None = 本轮是正常从入口开始的。Runner 靠它判断
        # 「局内接力」要不要跳过状态机直接把这一局交给战斗监督。
        self.resumed_from: Optional[ArenaState] = None

    def commit(self, action: Action, target: ArenaState) -> None:
        if action.source_state is not self.state:
            raise RuntimeError("竞技场动作来源状态与当前状态不一致")
        if target not in action.target_states:
            raise RuntimeError("竞技场动作目标状态不在合同中")
        if action.name == "confirm-result":
            self._cycle_pending = True
        self.state = target
        if action.name == "challenge" and target is ArenaState.TEAM:
            self._selected_opponent = None
        if (
            target is ArenaState.LIST
            and self._cycle_pending
            and action.name in {"confirm-result", "confirm-rank"}
        ):
            self.completed_cycles += 1
            self._cycle_pending = False

    def resume_from(self, state: ArenaState) -> None:
        """拨到用户停下的那一步，原样接管进度继续往下跑。

        语义是「**保留当前进度**」—— 比如停在对手详情页就继续点挑战，而不是退回列表
        重选对手。（2026-09-26 之前另有一个 ``reset_after_recovery`` 做「退回列表重开
        一轮」，随用户「回家就是结束」的拍板一起删除。）

        落在 RESULT / CONFIRMING 时的计数口径：这两页都已经在「这一局打完」之后
        （RESULT 是结算页、还没点确认；CONFIRMING 是确认之后、段位弹窗那一步）。
        所以 ``_cycle_pending`` 只在 CONFIRMING 置真 —— 用户手动打完并确认过的这一局
        算作已完成的一轮，回到列表时 +1，跟本进程自己打完一局的口径完全一致；
        落在 RESULT 时置假，因为这一次的确认还得由本进程去点，那一轮会照常走完再 +1。
        两种落点都只 +1 一次，不会重复计数（``commit("confirm-result")`` 之后
        CONFIRMING 分支会立刻把 pending 清掉）。

        ``resumed_from`` 记下落点，Runner 用它区分「接力落在局内」和「正常从入口开始」。
        """
        self.state = state
        self.resumed_from = state
        self._selected_opponent = None
        self._cycle_pending = state is ArenaState.CONFIRMING

    def _locate(self, screen: np.ndarray, template_name: str) -> Optional[Match]:
        threshold = self._THRESHOLDS.get(template_name, self.templates.threshold)
        return find_template(
            screen,
            getattr(self.templates, template_name),
            threshold,
            region=self._REGIONS[template_name],
            reference_size=self._REFERENCE_SIZE,
        )

    def _visible(self, screen: np.ndarray, template_name: str) -> bool:
        return self._locate(screen, template_name) is not None

    def observe_outcome(self, screen: np.ndarray) -> ArenaOutcome:
        """读出这一局是赢、输，还是认不出。

        判据**与接力同源**（同一对结果页模板、同一组阈值，见 ``detect_resume_state``），
        不另定一套口径 —— 否则就会长出「接力认得出、跑起来认不出」的第二种说法。

        顺序不能颠倒：先看 ``result_victory``（只有赢才有），再看 ``result_defeat``
        （只有输才有）。``result_rating`` 留在最后兜底 —— 它只在旧基准夹具上有效、
        真机上只有 0.38（见 ``evidence/arena.py``），留着是为了「横幅还在淡入」的那几帧
        还有个依据，不是主判据。三个都不在，说明画面还不是结算页（多半停在结算动画里），
        返回 ``UNKNOWN`` 而不是硬算成输。
        """
        if self._visible(screen, "result_victory"):
            return ArenaOutcome.WIN
        if self._visible(screen, "result_defeat"):
            return ArenaOutcome.LOSE
        if self._visible(screen, "result_rating"):
            return ArenaOutcome.LOSE
        return ArenaOutcome.UNKNOWN

    @classmethod
    def _scaled_region(
        cls,
        screen: np.ndarray,
        region: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        scale_x = screen.shape[1] / cls._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / cls._REFERENCE_SIZE[1]
        x, y, width, height = region
        return (
            round(x * scale_x),
            round(y * scale_y),
            round(width * scale_x),
            round(height * scale_y),
        )

    def opponent_availability(
        self,
        screen: np.ndarray,
    ) -> tuple[bool | None, bool | None, bool | None]:
        availability: list[bool | None] = []
        hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
        for region in self._OPPONENT_STATUS_REGIONS:
            x, y, width, height = self._scaled_region(screen, region)
            roi = hsv[y : y + height, x : x + width]
            red = (
                ((roi[:, :, 0] <= 10) | (roi[:, :, 0] >= 170))
                & (roi[:, :, 1] >= 60)
                & (roi[:, :, 2] >= 35)
            )
            ratio = float(np.mean(red))
            availability.append(
                False
                if ratio >= self._FAILED_RED_MIN_RATIO
                else True
                if ratio <= self._AVAILABLE_RED_MAX_RATIO
                else None
            )
        return tuple(availability)

    def has_safe_opponent(self, screen: np.ndarray) -> bool:
        return any(value is True for value in self.opponent_availability(screen))

    def free_refresh_confirm(self, screen: np.ndarray) -> Optional[Match]:
        return find_free_refresh_confirm(
            screen,
            self.templates.refresh_title,
            self.templates.refresh_free,
            self.templates.refresh_confirm,
            self._THRESHOLDS["refresh_confirm"],
        )

    def is_in_state(self, screen: np.ndarray, state: "ArenaState") -> bool:
        """True when the screen has actually settled into ``state``.

        SELECTED is special: the ``challenge`` button is visible in both LIST and
        SELECTED, but only becomes the dominant (active) button after an opponent is
        selected. We treat SELECTED as reached once ``challenge`` out-scores
        ``list_ready``, which is the reliable signal that the selection registered.
        """
        if state == ArenaState.SELECTED:
            challenge = self._locate(screen, "challenge")
            list_ready = self._locate(screen, "list_ready")
            return classify_arena_selected_scores(
                challenge.score if challenge is not None else None,
                list_ready.score if list_ready is not None else None,
            ) is EvidenceState.SAFE
        if state == ArenaState.TEAM:
            normal_start = self._locate(screen, "battle_start")
            return observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=normal_start,
            ).mode is not PreBattleMode.UNKNOWN
        return self._visible(screen, self._STATE_TEMPLATE[state])

    def action_source_visible(self, screen: np.ndarray, action: Action) -> bool:
        if action.name == "purchase-friendship-ticket":
            return (
                self._visible(screen, "no_ticket")
                and self._visible(screen, "friendship_ticket_offer")
                and self._visible(screen, "ticket_purchase_button")
            )
        if action.name == "refresh-opponents":
            return self.is_in_state(screen, ArenaState.LIST) and all(
                value is False for value in self.opponent_availability(screen)
            )
        if action.name == "confirm-result":
            return self._visible(screen, "confirm")
        if action.name == "confirm-rank":
            return find_rank_promotion_confirm(
                screen,
                self.templates.rank_promotion_arrow,
                self.templates.rank_confirm,
                self._THRESHOLDS["rank_promotion_arrow"],
            ) is not None
        if action.source_state is None:
            return False
        return self.is_in_state(screen, action.source_state)

    def action_target_state(
        self,
        screen: np.ndarray,
        action: Action,
    ) -> ArenaState | None:
        if (
            action.name == "purchase-friendship-ticket"
            and self.action_source_visible(screen, action)
        ):
            return None
        if action.name == "confirm-result":
            if self.is_in_state(screen, ArenaState.LIST):
                return ArenaState.LIST
            if find_rank_promotion_confirm(
                screen,
                self.templates.rank_promotion_arrow,
                self.templates.rank_confirm,
                self._THRESHOLDS["rank_promotion_arrow"],
            ) is not None:
                return ArenaState.CONFIRMING
            return None
        if action.name == "confirm-rank":
            return (
                ArenaState.LIST
                if self.is_in_state(screen, ArenaState.LIST)
                else None
            )
        for target in action.target_states:
            if self.is_in_state(screen, target):
                return target
        return None

    def _opponent_point(
        self,
        screen: np.ndarray,
        index: int,
    ) -> tuple[int, int]:
        anchor = self._locate(screen, "list_ready")
        if anchor is None:
            raise RuntimeError("选择对手时对手列表锚点丢失")
        offset = self._OPPONENT_OFFSETS[index]
        return (
            anchor.center[0] + offset[0],
            anchor.center[1] + offset[1],
        )

    def _refresh_point(self, screen: np.ndarray) -> tuple[int, int]:
        anchor = self._locate(screen, "list_ready")
        if anchor is None:
            raise RuntimeError("刷新对手时对手列表锚点丢失")
        return (
            anchor.center[0] + self._REFRESH_OFFSET[0],
            anchor.center[1] + self._REFRESH_OFFSET[1],
        )

    def _list_action(self, screen: np.ndarray) -> Action:
        availability = self.opponent_availability(screen)
        safe = [index for index, value in enumerate(availability) if value is True]
        if safe:
            if self._selected_opponent not in safe:
                self._selected_opponent = self.choose_opponent(safe)
            return Action(
                "select-opponent",
                self._opponent_point(screen, self._selected_opponent),
                ArenaState.LIST,
                (ArenaState.SELECTED,),
                "安全对手行已确认，等待对手详情页",
            )
        if all(value is False for value in availability):
            self._selected_opponent = None
            return Action(
                "refresh-opponents",
                self._refresh_point(screen),
                ArenaState.LIST,
                (ArenaState.LIST,),
                "三名对手均不可挑战，等待刷新后的安全列表",
            )
        raise RuntimeError("竞技场对手行无法安全分类")

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        start = self._locate(screen, "battle_start")
        pre_battle = observe_pre_battle(
            self.templates.quick_battle,
            screen,
            normal_start=start,
        )
        controls = observe_battle_controls(screen)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        auto_match = self._locate(screen, "auto_off")
        auto_score = "无" if auto_match is None else f"{auto_match.score:.4f}"
        auto_evidence = f"布局={controls.value} 自动关图标={auto_score}"
        if auto_match is not None and self.backend == "emulator":
            auto_state = AutoBattleState.MANUAL
            auto_evidence += " 来源=右上角自动关闭图标"
        result = self._locate(screen, "confirm")
        no_ticket = self._locate(screen, "no_ticket")
        progressing = (
            auto_state is AutoBattleState.AUTO
            and valid_game_frame(screen)
            and meaningful_change(previous_screen, screen)
        )
        return BattleObservation(
            pre_battle_visible=pre_battle.mode is not PreBattleMode.UNKNOWN,
            battle_visible=battle_scene_visible(screen),
            result_visible=result is not None,
            frame_valid=valid_game_frame(screen),
            auto_state=auto_state,
            auto_point=(
                auto_match.center
                if auto_match is not None
                else (
                    round(
                        self._AUTO_CLICK_POINT[0]
                        * screen.shape[1]
                        / self._REFERENCE_SIZE[0]
                    ),
                    round(
                        self._AUTO_CLICK_POINT[1]
                        * screen.shape[0]
                        / self._REFERENCE_SIZE[1]
                    ),
                )
                if auto_state is AutoBattleState.MANUAL
                else None
            ),
            business_progress=progressing,
            allowed_action=(
                None
                if no_ticket is not None
                else ("switch-to-normal-battle", pre_battle.switch_point)
                if pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
                else ("battle-start", start.center)
                if pre_battle.mode is PreBattleMode.NORMAL and start is not None
                else None
            ),
            pre_battle_business_visible=no_ticket is not None,
            auto_evidence=auto_evidence,
        )

    def next_action(self, screen: np.ndarray) -> Action:
        if self.state == ArenaState.BATTLE and self._visible(screen, "no_ticket"):
            offer = self._locate(screen, "friendship_ticket_offer")
            purchase = self._locate(screen, "ticket_purchase_button")
            if offer is None or purchase is None:
                raise TicketExhausted(
                    "ticket popup did not match the selected "
                    "100 friendship points -> 5 flags offer"
                )
            return Action(
                "purchase-friendship-ticket",
                purchase.center,
                ArenaState.BATTLE,
                (ArenaState.TEAM,),
                "资源=友情点 报价=100 获得旗帜=5 选择=左侧已确认 "
                f"报价匹配={offer.score:.3f} 购买按钮匹配={purchase.score:.3f}",
                irreversible=True,
            )

        if self.state == ArenaState.CONFIRMING:
            if self._visible(screen, "list_ready"):
                if self._cycle_pending:
                    self.completed_cycles += 1
                    self._cycle_pending = False
                self.state = ArenaState.LIST
                return self._list_action(screen)
            if self._visible(screen, "confirm"):
                return Action(
                    "confirm-result",
                    self._locate(screen, "confirm").center,
                    ArenaState.CONFIRMING,
                    (ArenaState.CONFIRMING, ArenaState.LIST),
                    "结果确认按钮仍在，等待列表或段位弹窗",
                )
            rank_confirm = find_rank_promotion_confirm(
                screen,
                self.templates.rank_promotion_arrow,
                self.templates.rank_confirm,
                self._THRESHOLDS["rank_promotion_arrow"],
            )
            if rank_confirm is not None:
                return Action(
                    "confirm-rank",
                    rank_confirm.center,
                    ArenaState.CONFIRMING,
                    (ArenaState.LIST,),
                    "段位提升弹窗证据完整，等待返回列表",
                )
            raise RuntimeError("结果确认后应回到对手列表")

        if self.state == ArenaState.TEAM:
            pre_battle = observe_pre_battle(
                self.templates.quick_battle,
                screen,
                normal_start=self._locate(screen, "battle_start"),
            )
            if (
                pre_battle.mode is PreBattleMode.QUICK
                and pre_battle.switch_point is not None
            ):
                return Action(
                    "battle-start",
                    pre_battle.switch_point,
                    ArenaState.TEAM,
                    (ArenaState.BATTLE,),
                    "快速战斗覆盖普通按钮，交由战斗监督切换",
                )

        if (
            self.state == ArenaState.SELECTED
            and not self.is_in_state(screen, ArenaState.SELECTED)
            and self.is_in_state(screen, ArenaState.LIST)
        ):
            self.state = ArenaState.LIST
            return self._list_action(screen)

        if not self.is_in_state(screen, self.state):
            raise UnrecognizedScreen(
                f"竞技场画面[{state_label(self.state)}]未识别"
            )

        template_name = self._STATE_TEMPLATE[self.state]
        match = self._locate(screen, template_name)
        if match is None:
            raise UnrecognizedScreen(
                f"竞技场画面[{state_label(self.state)}]未识别"
            )

        if self.state == ArenaState.LIST:
            return self._list_action(screen)

        name = self._ACTION_NAME[self.state]
        target = (
            ArenaState.CONFIRMING
            if self.state == ArenaState.RESULT
            else self._NEXT_STATE[self.state]
        )
        target_states = (
            (ArenaState.CONFIRMING, ArenaState.LIST)
            if name == "confirm-result"
            else (target,)
        )
        return Action(
            name,
            match.center,
            self.state,
            target_states,
            f"来源画面[{state_label(self.state)}]锚点已确认",
        )

    def preview(self, screen: np.ndarray):
        snapshot = (
            self.state,
            self.completed_cycles,
            self._selected_opponent,
            self._cycle_pending,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self._selected_opponent,
            self._cycle_pending,
        ) = snapshot


# 「接力」探测顺序 —— **顺序即优先级**，不能改。
# SELECTED 必须排在 LIST 前面：选中对手时 list_ready 仍然可见（实测 selected.png 上
# list_ready=0.9553 而 challenge=1.0000），只有 challenge 反超才能区分出「已选中」。
# 若先判 LIST 就会把「已选好对手、停在详情页」误当列表，退回去重点一次对手。
_ARENA_RESUME_ORDER = (ArenaState.SELECTED, ArenaState.TEAM, ArenaState.LIST)

# 「结果确认中」的判据页：段位提升弹窗（arrow + rank_confirm 双锚点，HSV 过滤）。
_ARENA_RESULT_CONFIRMING_PAGE = "arena.rank_promotion"

# 「战斗结果」的排他判据页：confirm + 竞技场专有内容锚点。
_ARENA_RESULT_PAGE = "arena.result_arena"


def _rank_promotion_visible(
    machine: "ArenaStateMachine",
    screen: np.ndarray,
) -> bool:
    """接力专用：段位提升弹窗是否成立（走 HSV 双锚点那条既有判据）。

    两个锚点必须**同时**命中才算，单看任一锚点会被别处的高分骗到
    （`rank_confirm` 按钮本身在 `selected.png` 上就有 0.7048）。
    """
    return (
        find_rank_promotion_confirm(
            screen,
            machine.templates.rank_promotion_arrow,
            machine.templates.rank_confirm,
            machine._THRESHOLDS["rank_promotion_arrow"],
        )
        is not None
    )


def _resume_evidence_flags(
    machine: "ArenaStateMachine",
    screen: np.ndarray,
) -> dict[str, bool]:
    """接力专用：把结果页 / 段位弹窗相关锚点的可见性算成布尔 flags。

    段位弹窗那两项用 `find_rank_promotion_confirm` 的整体结论一起置位 ——
    这条判据带 HSV 颜色过滤，不是两个独立模板命中的简单与。
    """
    promotion = _rank_promotion_visible(machine, screen)
    return {
        "confirm": machine._locate(screen, "confirm") is not None,
        "result_rating": machine._locate(screen, "result_rating") is not None,
        "result_victory": machine._locate(screen, "result_victory") is not None,
        "result_defeat": machine._locate(screen, "result_defeat") is not None,
        "rank_promotion_arrow": promotion,
        "rank_confirm": promotion,
    }


def detect_resume_state(
    machine: "ArenaStateMachine",
    screen: np.ndarray,
) -> Optional[tuple[ArenaState, str]]:
    """判断启动前用户把游戏停在了竞技场的哪一步，用于「接着往下跑」。

    返回 `(状态, 中文页面名)`；识别不到返回 None，调用方回退到原来的
    「回大厅 → 按路线导航」（失败关闭，行为与加这个功能之前一致）。

    竞技场一环共六步（列表 → 详情 → 队伍 → 战斗 → 结果 → 确认中），这里认其中五步，
    顺序即优先级：对手详情 → 队伍选择（准备战斗）→ 对手列表 → 战斗结果 → 结果确认中。
    剩下的「战斗中」不在这个函数里认，由 `detect_resume_point` 用
    `battle_scene_visible` 兜住（见下）。

    **故意不认的两种画面**（认错的代价大于收益）：
    - **局内**：实测 4 张局内实时帧只有 1 张能靠 `auto_off` 认出 battle
      （技能动画 `battle_skill_animation_live_20260825`、角色阵亡
      `battle_auto_dead_*_live_20260814`、卡住 `battle_manual_stuck_live_20260814` 三张都认不出）。
      而认错的代价是在战斗里按 Back 回大厅 —— 正是「已承诺战斗」要禁止的事。
      局内交给 `detect_resume_point` 用 `battle_scene_visible` 兜住，不走这里。
    - **买票弹窗压住的队伍页**：`battle_start` 仍然可见（实测 0.9996），会被误判成 team，
      接力过去就直接点到弹窗上，故用 `no_ticket` 显式排除。

    后两步（结果页 / 段位弹窗）**与前三页锚点互斥**，所以追加在循环后面不会互相遮蔽：
    实测结果页上 list_ready=0.2722、challenge=0.2624、battle_start=0.2302（阈值 0.88/0.90），
    段位弹窗上 list_ready=0.6425、challenge=0.6857（同样在阈值下）。
    这两步之间也互斥：结果页 confirm=1.0000 而晋级箭头完全不可见，
    段位弹窗上箭头=0.9993 而 confirm=0.1484。顺序按流程先后排（结果页在前）。
    """
    for state in _ARENA_RESUME_ORDER:
        if not machine.is_in_state(screen, state):
            continue
        if state is ArenaState.TEAM and machine._visible(screen, "no_ticket"):
            continue
        return state, state_label(state)

    profile = machine.templates.evidence
    flags = _resume_evidence_flags(machine, screen)

    if profile is not None:
        if (
            profile.page(_ARENA_RESULT_PAGE).evaluate(flags)
            is EvidenceState.SAFE
        ):
            return ArenaState.RESULT, state_label(ArenaState.RESULT)
        if (
            profile.page(_ARENA_RESULT_CONFIRMING_PAGE).evaluate(flags)
            is EvidenceState.SAFE
        ):
            return ArenaState.CONFIRMING, state_label(ArenaState.CONFIRMING)
        return None

    # 没有证据档案时的兜底（只在手工拼 ArenaTemplates 的测试里出现）：
    # 判据与上面两个页面保持一致，避免两处语义漂移。
    if flags["confirm"] and (
        flags["result_rating"] or flags["result_victory"] or flags["result_defeat"]
    ):
        return ArenaState.RESULT, state_label(ArenaState.RESULT)
    if flags["rank_promotion_arrow"] and flags["rank_confirm"]:
        return ArenaState.CONFIRMING, state_label(ArenaState.CONFIRMING)
    return None


# 导航页面名「竞技场模式选择」（= `navigation.page_label("arena_mode")`）。
# 站在这一页上说明已经在竞技场支线里了，只差「进新手竞技场」一步。
ARENA_ENTRY_PAGE = "arena_mode"


class ArenaResumePoint(NamedTuple):
    """竞技场开局接力的落点。"""

    page: str                       # 中文页面名，给日志和诊断看
    state: Optional[ArenaState]     # 要拨过去的状态机状态；None = 不动状态机
    entry: Optional[str] = None     # 已经在导航链的这个页面上，从这里接着导航


def detect_resume_point(
    machine: "ArenaStateMachine",
    screen: np.ndarray,
    *,
    observed_page: Optional[str] = None,
) -> Optional[ArenaResumePoint]:
    """竞技场开局接力：认出用户停在竞技场一环里的哪一页。

    ``observed_page`` 传导航器的页面名（``Epic7Navigator.observe().name``）。
    竞技场状态机只认对战那几步，**模式选择页只有导航器认得出来**，所以要多带一个信息。

    优先级 = 「还没做任何不可逆动作」在前、「已经在打」在后：
    模式选择 → 对手详情 → 准备战斗 → 对手列表 → 战斗结果 → 结果确认中 → 战斗中。

    **战斗结果 / 结果确认中这两页曾经不可接力，2026-09-16 补齐**：

    - **战斗结果**卡在「没有排他证据」：识别它的 ``confirm`` 锚点是**和远征结果页共用**的
      （实测远征 ``result.png`` 也拿 0.9448，高过 0.90 阈值）。现在加了两个竞技场专有内容
      锚点（``result_rating``=「积分」面板标题，胜负都在；``result_victory``=「VICTORY」横幅），
      在 ``arena.result_arena`` 页里与 ``confirm`` 组成合取判据。
    - **结果确认中**其实是段位提升弹窗，`find_rank_promotion_confirm` 早就认得出
      （双锚点实测 0.9993 / 1.0000），此前只是没接进接力链。

    **局内**用 ``battle_scene_visible`` 认（实测 197 张夹具命中 20 张：19 张是真局内，
    含主线/远征/狗粮；1 张误报 ``epic7_fodder/replay.png`` —— 战后结算页走兜底分支被判成
    局内。它不影响已接力的四条路线，但做狗粮接力前必须先解决）。注意这个判据分不出
    「这是哪条路线的战斗」—— 停在别的路线战斗里启动竞技场，也会先把这一局监督完
    **再原地接着往下走**（2026-09-26 之前是「监督完再回大厅重新导航」，那条恢复通道
    已随用户「回家就是结束」的拍板整段删除）；这比老流程好：老流程在局内会一直卡在
    「未知画面等待唤醒」直到返回大厅预算耗尽，然后退出码 1。
    """
    if observed_page == ARENA_ENTRY_PAGE:
        return ArenaResumePoint("竞技场模式选择", None, ARENA_ENTRY_PAGE)
    found = detect_resume_state(machine, screen)
    if found is not None:
        state, label = found
        return ArenaResumePoint(label, state)
    if battle_scene_visible(screen):
        return ArenaResumePoint("战斗中", ArenaState.BATTLE)
    return None


class ArenaRunner(TransactionalRunnerBase):
    """竞技场 Runner。

    ⚠️ 2026-09-26 起它是 ``TransactionalRunnerBase`` 的子类，但**保留自己的
    ``run()``** —— 这是评估后的取舍，不是漏改：

    与远征共享的是**机制**（转场的两帧验收 + 四次重试、失败诊断证据包、
    战斗看护移交、收尾回首页骨架、逐帧存图）。**循环策略不共享**，因为两边
    真的不一样，硬合要把基类变成一张十几个开关的配置表：
    竞技场有「开局接手一局已经在打的战斗」「每轮重置未知画面唤醒器」
    「两个动作走自家验收（开始战斗直接交看护 / 刷新对手等含安全对手的列表）」
    「买票前拦停 + 买完记账」「干跑是真点一下」「票耗尽自成一类异常」这些做法，
    远征一条都没有；反过来远征「每一步都判状态超时」的兜底竞技场也没有。
    ⇒ 在这里，「抽公共基类」的含义是**只抽掉逐字相同的部分**。
    """

    _MODE_LABEL = "竞技场"

    _TIMEOUT_SECONDS = {
        ArenaState.LIST: 40,
        ArenaState.SELECTED: 40,
        ArenaState.TEAM: 60,
        ArenaState.BATTLE: 60,
        ArenaState.RESULT: 120,
        ArenaState.CONFIRMING: 45,
    }

    # Wait this long after a click before polling, to skip the post-click animation
    # frame where the next screen has not rendered yet.
    _SETTLE_SECONDS = 1.5

    # 战斗看护的落点，基类 ``_run_committed_battle`` 读这两个。
    _BATTLE_STATE = ArenaState.BATTLE
    _RESULT_STATE = ArenaState.RESULT

    def __init__(
        self,
        machine: ArenaStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
        purchase_stamp_path: Path | None = None,
        outcome_frame_dir: Path | None = None,
    ) -> None:
        # ⚠️ ``now`` / ``recovery_gate`` / ``unknown_screen_wake`` /
        # ``battle_supervisor`` / ``resource_exhausted`` / ``finish_home`` 全部由基类
        # 建好，这里一个都不重复（重复就会有两份、迟早各改各的）。
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
            battle_supervisor=battle_supervisor,
        )
        self.purchase_stamp_path = purchase_stamp_path
        # 每局结算画面的落盘目录（实跑由 main.py 注入 docs/manual_review/arena/）。
        # **默认 None = 不落盘**：测试里绝不能顺手往仓库里写图。
        self.outcome_frame_dir = outcome_frame_dir
        # 本进程的战绩：胜 / 负 / 认不出。「认不出」单列，不并入负（见 ArenaOutcome）。
        self.outcome_tally = {outcome: 0 for outcome in ArenaOutcome}

    # ---- 基类钩子：竞技场口径 ----

    def _battle_config(self) -> BattleConfig:
        return BattleConfig(mode="arena", mode_label="竞技场")

    def _state_label(self, state: Optional[ArenaState]) -> str:
        return state_label(state)

    def _transition_budget(self, action: Action) -> tuple[float, float]:
        """转场验收的两条时限 —— 竞技场按**目标页面的**超时算，不是当前页面。

        取目标里最宽的那一档、再夹到 180 秒；「画面多久没动」固定夹到 45 秒。
        ⚠️ 与远征的差别（那边是「当前状态超时」两档相等、45 秒一刀切）是**真差别**，
        抽取时原样保留：远征的路线节拍与竞技场不是一回事。
        """
        absolute = min(
            180,
            max(self._TIMEOUT_SECONDS[target] for target in action.target_states),
        )
        return absolute, min(45, absolute)

    def _transition_diagnostic_label(self, action: Action) -> str:
        """按**页面**命名诊断图（``no_transition_<来源>_to_<目标…>``）。

        ⚠️ 与远征的 ``no_transition_<动作名>`` 不同是**刻意保留**的：
        仓库里现存的竞技场现场诊断图就是按这个格式命名的，改名会让
        「照着日志去找那张图」的操作失效。
        """
        return (
            f"no_transition_{action.source_state.value}_to_"
            f"{'_or_'.join(target.value for target in action.target_states)}"
        )

    def _log_transition_start(self, action: Action) -> None:
        """不记：竞技场在自己的主循环里已经每轮记过「轮次/页面/动作候选/依据」。"""
        del action

    def _log_transition_failed(
        self, action: Action, attempts: int, diagnostic: Any
    ) -> None:
        self.runtime.log(
            f"模式=竞技场 状态=转场失败 动作={action.name} "
            f"从={state_label(action.source_state)} "
            f"到={'/'.join(state_label(target) for target in action.target_states)} "
            f"尝试={attempts}/4 诊断={diagnostic}"
        )

    def _transition_failure_message(
        self, action: Action, attempts: int, diagnostic: Any
    ) -> Optional[str]:
        del attempts
        return (
            f"点击 {action.name} 后画面未稳定进入"
            f"[{'/'.join(state_label(target) for target in action.target_states)}]；"
            f"已保存诊断 {diagnostic}"
        )

    def _dismiss_purchase_popup(self) -> bool:
        """票耗尽时人停在「购买旗帜」弹窗里 —— 先点「取消」退回对手列表。

        **为什么要这一步**（2026-09-25 定，见 docs/maintenance/route_finish_points.md 注①）：
        路线终点必须落在**非浮层页**上，回家流程才能安全起手（浮层里右上角那颗蓝色
        四格是灰的、点不动，但模板匹配照样认得，回家流程会去点它）。
        实机日志证明票耗尽时画面正是这颗弹窗（现场帧
        ``runtime_diagnostics/epic7_arena/20260925_081722_997139_ticket_exhausted.png``）。

        **判据是双锚点**（``purchase_title`` + ``purchase_cancel``）：
        单靠「取消」两个字会串门 —— 实测迷宫的「购买确认」「放弃确认」都能命中
        （0.9757 / 0.9758），它们**不该**被这里点掉。

        返回 True 表示「确实关掉了」（弹窗在、点了、画面已离开弹窗）；
        False 表示「本来就没弹窗」或「认不出 / 点了没反应」。
        **不抛异常**：这是收尾的最后一步，失败不该改退出码，交给上层记日志。
        """
        try:
            screen = self.runtime.capture()
        except Exception:  # noqa: BLE001 —— 收尾阶段不因读不到画面而中断
            return False
        if not self._purchase_popup_visible(screen):
            return False
        try:
            cancel = find_template(
                screen,
                self.machine.templates.purchase_cancel,
                ARENA_THRESHOLDS["purchase_cancel"],
                region=ARENA_REGIONS["purchase_cancel"],
                reference_size=ARENA_REFERENCE_SIZE,
            )
        except (AttributeError, TypeError):  # 打桩环境（MagicMock）下的兜底
            return False
        if cancel is None:  # 理论上不可达（刚判过双锚点），防御性兜底
            return False
        self.runtime.log(
            f"模式=竞技场 收尾=关闭购买弹窗 动作=dismiss-purchase "
            f"坐标={cancel.center} 目标页面=对手列表"
        )
        self.runtime.click(cancel.center, "dismiss-purchase")
        # 等画面真的离开弹窗（最多 5 秒）：关掉了才算终点已下移。
        # 关不掉也不硬来 —— 返回 False，让上层照旧收尾并把这个事实记进日志。
        for _ in range(10):
            self.sleep(self.poll_seconds)
            try:
                screen = self.runtime.capture()
            except Exception:  # noqa: BLE001
                return False
            if not self._purchase_popup_visible(screen):
                self.runtime.log("模式=竞技场 收尾=购买弹窗已关闭 状态=人已退回对手列表")
                return True
        self.runtime.log(
            "模式=竞技场 收尾=购买弹窗未关闭 处理=照旧收尾（终点可能仍在浮层里）"
        )
        return False

    def _purchase_popup_visible(self, screen: np.ndarray) -> bool:
        """「购买旗帜」弹窗在不在 —— **双锚点**，且**不经过状态机的 ``_visible``**。

        ⚠️ 为什么自己调 matcher 而不走 ``machine._visible``：收尾路径会被各种测试
        用 ``MagicMock()`` 当状态机跑（``test_arena_runner`` 里有好几个），
        那时 ``machine._visible`` 返回的是 MagicMock 对象、**真值为真** ⇒
        会凭空多出一次「取消」点击，把那些测试全打红。
        这里要的是「这一帧上有没有这两样东西」，与状态机状态无关，自己量更准。

        ⚠️ 任何取不到模板 / 量不出来的情况一律**当成「不在弹窗上」**（fail-closed）：
        这是收尾阶段的加分动作，判不出来就老老实实什么都不做。
        """
        try:
            templates = self.machine.templates
            title = templates.purchase_title
            cancel = templates.purchase_cancel
        except AttributeError:
            return False
        # ⚠️ 三个输入都必须是真数组才能量：测试里常把 runtime / machine 打成
        # ``MagicMock``，那时 ``capture()`` 返回的也是 MagicMock，直接喂给
        # ``find_template`` 会在 ``abs(scale_x - scale_y)`` 上抛 TypeError。
        # 收尾是加分动作，量不出来就当「不在弹窗上」，绝不能让它把收尾整个炸掉。
        if not isinstance(screen, np.ndarray):
            return False
        if not isinstance(title, np.ndarray) or not isinstance(cancel, np.ndarray):
            return False
        return bool(
            find_template(
                screen,
                title,
                ARENA_THRESHOLDS["purchase_title"],
                region=ARENA_REGIONS["purchase_title"],
                reference_size=ARENA_REFERENCE_SIZE,
            )
            is not None
            and find_template(
                screen,
                cancel,
                ARENA_THRESHOLDS["purchase_cancel"],
                region=ARENA_REGIONS["purchase_cancel"],
                reference_size=ARENA_REFERENCE_SIZE,
            )
            is not None
        )

    def _close_out(self) -> None:
        """收尾回首页 —— 比基类多一步前置动作（关购买弹窗），其余交给基类。

        ⚠️ 与基类的关系（2026-09-26）：正文（读哪个钩子、什么时候调、失败怎么办）
        **全在** ``TransactionalRunnerBase._close_out`` 里，这里只加前置动作、
        不重写一遍 —— 重写就会有两份，迟早各改各的。
        
        ⚠️ 两类退出**刻意不接**：``ManualStop``（用户喊停）与异常（跑到一半挂了，
        硬按 Back 有丢局风险）—— 两者都在 ``run()`` 里直接 raise，走不到这里。

        ⚠️ **接力开局照样收尾**：人停在半路被接力接管、补完这一局之后，本进程的
        任务已经做完了，按用户 2026-09-25 的诉求就该回首页（后面要串下一个任务）。
        「接力只补一局、不擅自回家」听起来更保守，但那样接力启动会留下**唯一一个
        做完不回首页**的口子，串任务时正好卡在那儿。

        ⚠️ **先把「购买旗帜」弹窗关掉**（``_dismiss_purchase_popup``）：
        票耗尽那条路是停在弹窗里的，不关掉的话终点就落在浮层上，回家流程会撞灰按钮。
        放在这里而不是各个调用点，是为了让**所有**收尾出口都统一经过这一步。
        """
        self._dismiss_purchase_popup()
        super()._close_out()

    def _after_result_state(self, *, cycle: int) -> None:
        """战斗打到结算页、状态已拨到 ``_RESULT_STATE`` 之后 ⇒ 记下这一局的胜负。

        基类 ``_run_committed_battle`` 正常打完时调这里（竞技场口径的落点）。
        """
        self._record_outcome(cycle=cycle)

    def _record_outcome(self, *, cycle: int) -> None:
        """结算页刚确认，就地记下这一局的胜负。

        **每局恰好走一次**：调用点只有 ``_after_result_state``（由基类
        ``_run_committed_battle`` 在正常打到结算页时调，每局一次），
        不像 ``next_action`` 那样每帧都会被问、也不会被 ``preview`` 的空跑回滚。

        判定复用 ``machine.observe_outcome``（与接力同源）。认不出照样入账，进 ``未知``
        那一格，绝不硬塞给「负」—— 战绩要能反映「我不知道」，而不是给个好看的数字。
        """
        screen = self.runtime.capture()
        result = self.machine.observe_outcome(screen)
        self.outcome_tally[result] += 1
        frame = self._save_outcome_frame(screen, result, cycle=cycle)
        self.runtime.log(
            f"模式=竞技场 轮次={cycle} 战绩={OUTCOME_LABELS[result]} "
            f"结算图={frame if frame is not None else '未落盘'}"
        )

    def _save_outcome_frame(
        self,
        screen: np.ndarray,
        result: ArenaOutcome,
        *,
        cycle: int,
    ) -> Path | None:
        """把这一局的结算画面留一张盘，作为「胜负判得对不对」的第一手证据。

        「胜」的判据已经实测过，但「负」这一侧至今**没有真帧**（全库唯一那张结算图
        是赢的）—— 这张图就是补给它的素材：打完回看一眼就知道判得对不对。

        ⚠️ 文件名**保持 ASCII**（``win`` / ``lose`` / ``unknown``）：``cv2.imwrite`` /
        ``imread`` 走不了中文路径，写「胜/负」会变成一张读不回来的图。
        """
        if self.outcome_frame_dir is None:
            return None
        self.outcome_frame_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.outcome_frame_dir / f"{stamp}_{result.value}_r{cycle}.png"
        image = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"结算画面保存失败：{path}")
        self._prune_outcome_frames()
        return path

    def _prune_outcome_frames(self) -> None:
        """只留最近 ``OUTCOME_FRAME_KEEP`` 张结算图，多出来的从**最旧**开始删。

        ⚠️ 排序靠**文件名**，不靠文件时间：命名以 ``%Y%m%d_%H%M%S`` 开头 ⇒ 字典序就是
        时间序，而 mtime 会被复制/同步改掉、名字不会。改文件名格式时这里要一起看。

        删不掉（用户在看图、文件被占用）就跳过：**留一张旧图不值得中断跑图**，
        下一次结算再收。
        """
        if self.outcome_frame_dir is None:
            return
        frames = sorted(self.outcome_frame_dir.glob("*.png"), key=lambda path: path.name)
        for stale in frames[: -OUTCOME_FRAME_KEEP]:
            try:
                stale.unlink()
            except OSError:
                continue

    def outcome_summary(self) -> str:
        """给通知与控制台用的一行战绩：``胜 2 / 负 1``（认不出时补 ``（未知 1）``）。"""
        parts = [
            f"{OUTCOME_LABELS[outcome]} {self.outcome_tally[outcome]}"
            for outcome in (ArenaOutcome.WIN, ArenaOutcome.LOSE)
        ]
        unknown = self.outcome_tally[ArenaOutcome.UNKNOWN]
        text = " / ".join(parts)
        if unknown:
            text += f"（未知 {unknown}）"
        return text

    # ``_save_failure_diagnostic`` 不再自己实现：基类那份是**本族口径**（收 label、
    # 自己落盘、没配诊断目录就返回 ``"not-configured"``）。刻意没有像
    # ``ModeRunnerBase`` 那一支那样改成「收已存好的路径」—— 两条路线都只需要一个
    # 入口，多一种签名就多一个能把路径当标签用错的口子（2026-09-26 抽取时定的）。

    def _resume_into_committed_battle(self) -> None:
        """接力直接落在局内：这一局不是本进程点开的，但已经打起来了。

        不能走 ``next_action(BATTLE)`` —— 那条路靠 ``auto_off`` 图标定位，而**自动战斗开着
        时这个图标根本不可见** → 抛未识别 → 60 秒后安全停止，
        等于在已经承诺的战斗里按 Back。这里直接交给战斗监督等结算：
        它自己会在明确 ``MANUAL`` 时点自动，并用心跳和多重超时兜底。
        """
        self.runtime.log(
            "模式=竞技场 开局=接力 页面=战斗中 "
            "动作=交由战斗监督等待结算 说明=本局非本进程开启"
        )
        self._run_committed_battle(cycle=self.machine.completed_cycles + 1)

    def run(self, max_cycles: int | None = None) -> int:
        state_started = self.now()
        stable = StableObservation(required=2)
        conclusion_gate = ConclusionGate()
        if self.machine.resumed_from is ArenaState.BATTLE:
            # 先把这一局监督完，再把 state_started 拨到「当前」，否则后面判结果页超时
            # 会拿一个陈旧的起点，一进 RESULT 就直接判超时。
            self._resume_into_committed_battle()
            state_started = self.now()
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            state_before = self.machine.state
            try:
                screen = self.runtime.capture()
                if self.runtime.diagnostic_dir is not None:
                    self.runtime.save_current_frame(screen)
                try:
                    preview_action, _ = self.machine.preview(screen)
                except RuntimeError as error:
                    # 结论也要两帧：单帧就宣布「票没了 / 认不出画面」会提前结束整轮。
                    if not conclusion_gate.admit(error):
                        self.runtime.log(
                            f"模式=竞技场 结论待确认={type(error).__name__} "
                            f"依据=需连续两帧一致才采信 详情={error}"
                        )
                        self.sleep(self.poll_seconds)
                        continue
                    raise
                if not stable.update(preview_action.name):
                    self.sleep(self.poll_seconds)
                    continue
                action = self.machine.next_action(screen)
                stable.reset()
                conclusion_gate.reset()
            except TicketExhausted as error:
                diagnostic = None
                if self.runtime.diagnostic_dir is not None:
                    diagnostic = self.runtime.save_diagnostic("ticket_exhausted", screen)
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式=竞技场 停止=旗帜资源不可安全购买 详情={error} "
                    f"已完成={self.machine.completed_cycles} 现场={diagnostic}"
                )
                self._close_out()
                return self.machine.completed_cycles
            except ManualStop:
                # ⚠️ 必须排在 `except RuntimeError` 前面。`ManualStop` 是 `RuntimeError`
                # 的子类，掉进下面那条分支会被当成「页面没认出来」：sleep 一轮再
                # continue，主循环回头 `capture()` 又抛一次 —— 一次停止会变成按轮询
                # 频率刷屏 + 每秒一张全屏诊断图，直到该状态超时（列表页 40 秒）才做
                # 恢复，用户看到的就是「按了停止它却一直在存图片」。
                raise
            except RuntimeError as error:
                if isinstance(error, UnrecognizedScreen):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"竞技场:{state_label(self.machine.state)}",
                    )
                    if wake_result is UnknownWakeResult.WAITING:
                        self.sleep(self.poll_seconds)
                        continue
                timeout = self._TIMEOUT_SECONDS[self.machine.state]
                if self.now() - state_started >= timeout:
                    # 认不出这一页、等到超时 ⇒ **结束这一轮**（回家由 main 收尾）。
                    # ⚠️ 2026-09-26：以前这里是「回大厅重新导航、然后接着跑」，
                    # 用户拍板「回家就是结束，不可能再回来」。
                    diagnostic = self._save_failure_diagnostic(
                        f"timeout_{self.machine.state.value}",
                        screen,
                        action=None,
                        attempt=1,
                        conclusion=f"页面识别超时：{error}",
                    )
                    self.runtime.log(
                        f"模式=竞技场 页面={state_label(self.machine.state)} "
                        f"状态=超时无进展 诊断={diagnostic}"
                    )
                    raise RuntimeError(
                        f"页面无进展：{error}；已安全停止并保存诊断 {diagnostic}"
                    ) from error
                self.sleep(self.poll_seconds)
                continue

            self.unknown_screen_wake.reset()
            if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                self.runtime.log(
                    f"模式=竞技场 轮次={self.machine.completed_cycles} "
                    "业务完成=结算返回对手列表 目标连续=2"
                )
                self._close_out()
                return self.machine.completed_cycles
            if action.name == "purchase-friendship-ticket" and not self._purchase_allowed_today():
                self.machine.state = ArenaState.BATTLE
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式=竞技场 停止=今日友情点旗帜已购买 已完成={self.machine.completed_cycles}"
                )
                self._close_out()
                return self.machine.completed_cycles
            self.runtime.log(
                f"模式=竞技场 轮次={self.machine.completed_cycles + 1}/{max_cycles or '?'} "
                f"页面={state_label(state_before)} 动作候选={action.name} "
                f"依据={action.reason or '测试动作'}"
            )
            cycles_before = self.machine.completed_cycles
            if self.runtime.dry_run:
                self.runtime.click(action.point, action.name)
                return self.machine.completed_cycles

            if action.name == "battle-start":
                self.runtime.click(action.point, action.name)
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1,
                )
                state_started = self.now()
                stable.reset()
                conclusion_gate.reset()
                continue

            if action.name == "refresh-opponents":
                self.runtime.click(action.point, action.name)
                if not self._wait_until_safe_list(action):
                    failure_screen = self.runtime.capture()
                    diagnostic = self._save_failure_diagnostic(
                        "refresh_opponents_failed",
                        failure_screen,
                        action=action,
                        attempt=1,
                        conclusion="刷新后未出现可安全挑战的对手列表",
                    )
                    self.runtime.log(
                        "模式=竞技场 页面=对手列表 动作=刷新对手 "
                        f"停止=刷新后没有安全对手 现场={diagnostic}"
                    )
                    raise RuntimeError(
                        f"刷新对手后未出现安全对手列表；已保存诊断 {diagnostic}"
                    )
                self.machine.state = ArenaState.LIST
                state_started = self.now()
                stable.reset()
                conclusion_gate.reset()
                continue

            self._execute_transition(action)
            if action.name == "purchase-friendship-ticket":
                self._record_purchase_today()
            if self.machine.completed_cycles > cycles_before:
                self.runtime.log(
                    f"模式=竞技场 轮次={self.machine.completed_cycles} "
                    "业务完成=结算返回对手列表 目标连续=2"
                )

            if self.machine.state != state_before:
                state_started = self.now()
            self.sleep(self.poll_seconds)

        self._close_out()
        return self.machine.completed_cycles

    # ``_execute_transition`` 与 ``_save_frame`` 不再自己实现 —— 基类那两份就是本族
    # 口径（目标页连续两帧才 commit、源页还在最多重试 4 次、失败诊断落盘、逐帧存图）。
    # 竞技场的差异全部通过钩子注入，注入点见本类上半部分的「基类钩子」一节。
    # 删除前逐条对过：重构后竞技场在转场这一段的行为与 2026-09-26 之前**逐字一致**
    # （含日志文案），只有两处刻意保留的小差异，理由都写在钩子那边。

    def _wait_until_safe_list(self, action: Action | None = None) -> bool:
        self.sleep(self._SETTLE_SECONDS)
        started = self.now()
        last_progress = started
        previous: Optional[np.ndarray] = None
        absolute = min(180, self._TIMEOUT_SECONDS[ArenaState.LIST])
        no_progress = min(45, self._TIMEOUT_SECONDS[ArenaState.LIST])
        safe_list_stable = StableObservation(required=2)
        failed_list_stable = StableObservation(required=2)
        refresh_confirm_stable = StableObservation(required=2)
        refresh_confirm_clicks = 0
        refresh_attempts = 1 if action is not None else 0
        source_has_gone = False
        while self.now() - started < absolute:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            safe_list = (
                self.machine.is_in_state(screen, ArenaState.LIST)
                and self.machine.has_safe_opponent(screen)
            )
            if safe_list_stable.update("safe" if safe_list else "other") and safe_list:
                if action is not None:
                    self.machine.commit(action, ArenaState.LIST)
                self.runtime.log(
                    "模式=竞技场 转场确认 动作=refresh-opponents "
                    "目标=含安全对手的列表 目标连续=2"
                )
                return True

            failed_source = (
                action is not None
                and self.machine.action_source_visible(screen, action)
            )
            if not failed_source and action is not None:
                source_has_gone = True
            if (
                action is not None
                and failed_list_stable.update(
                    "failed-list" if failed_source else "other"
                )
                and failed_source
                and not source_has_gone
                and refresh_attempts < 4
            ):
                refresh_attempts += 1
                self.runtime.log(
                    "模式=竞技场 转场重试 动作=refresh-opponents "
                    f"来源=失败对手列表仍在 尝试={refresh_attempts}/4 "
                    f"坐标={action.point}"
                )
                self.runtime.click(action.point, action.name)
                failed_list_stable.reset()
                self.sleep(self._SETTLE_SECONDS)
                continue
            refresh_confirm = self.machine.free_refresh_confirm(screen)
            signature = "free-refresh" if refresh_confirm is not None else "other"
            if refresh_confirm_stable.update(signature) and refresh_confirm is not None:
                if refresh_confirm_clicks >= 4:
                    return False
                refresh_confirm_clicks += 1
                self.runtime.log(
                    "模式=竞技场 页面=免费刷新确认 "
                    f"动作=confirm-free-refresh 尝试={refresh_confirm_clicks}/4 "
                    f"置信度={refresh_confirm.score:.3f}"
                )
                self.runtime.click(
                    refresh_confirm.center,
                    "confirm-free-refresh",
                )
                refresh_confirm_stable.reset()
                self.sleep(self._SETTLE_SECONDS)
                continue
            if meaningful_change(previous, screen):
                last_progress = self.now()
            previous = screen
            if self.now() - last_progress >= no_progress:
                return False
            self.sleep(self.poll_seconds)
        return False

    def _purchase_allowed_today(self) -> bool:
        if self.purchase_stamp_path is None:
            return False
        if not self.purchase_stamp_path.exists():
            return True
        return self.purchase_stamp_path.read_text(encoding="utf-8").strip() != date.today().isoformat()

    def _record_purchase_today(self) -> None:
        if self.purchase_stamp_path is None:
            raise RuntimeError("旗帜购买记录路径未配置")
        self.purchase_stamp_path.parent.mkdir(parents=True, exist_ok=True)
        self.purchase_stamp_path.write_text(date.today().isoformat(), encoding="utf-8")
