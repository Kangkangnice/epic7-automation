from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import date
import random
from time import sleep as default_sleep
from typing import Callable, Optional, Sequence

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
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import (
    StableObservation,
    meaningful_change,
)
from auto_game_unified.core.evidence_diagnostics import (
    save_runtime_evidence_diagnostic,
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
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
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
    refresh_title: np.ndarray
    refresh_free: np.ndarray
    refresh_confirm: np.ndarray
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
        refresh_title=load_template(str(template_dir / "arena_refresh_title.png")),
        refresh_free=load_template(str(template_dir / "arena_refresh_free.png")),
        refresh_confirm=load_template(str(template_dir / "arena_refresh_confirm.png")),
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

    def reset_after_recovery(self) -> None:
        self.state = ArenaState.LIST
        self._selected_opponent = None
        self._cycle_pending = False

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
        if auto_match is not None and self.backend == "emulator":
            auto_state = AutoBattleState.MANUAL
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


class ArenaRunner:
    """Execute the state machine, stopping with a screenshot on UI drift or timeout."""

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

    def __init__(
        self,
        machine: ArenaStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
        purchase_stamp_path: Path | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.recovery_gate = recovery_gate or RecoveryGate(recovery)
        self.recovery = self.recovery_gate.recover if recovery is not None else None
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            BattleConfig(mode="arena", mode_label="竞技场"),
            now=self.now,
            sleep=sleep,
        )
        self.unknown_screen_wake = UnknownScreenWake(
            runtime,
            recovery_gate=self.recovery_gate,
        )
        self.purchase_stamp_path = purchase_stamp_path
        self.resource_exhausted = False

    def _run_committed_battle(self, *, cycle: int) -> None:
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = ArenaState.BATTLE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"竞技场战斗出现意外结果：{outcome.value}")
        self.machine.state = ArenaState.RESULT

    def _save_failure_diagnostic(
        self,
        legacy_path: Path,
        screen: np.ndarray,
        *,
        action: Action | None,
        attempt: int,
        conclusion: str,
    ):
        templates = getattr(self.machine, "templates", None)
        return save_runtime_evidence_diagnostic(
            self.runtime,
            screen,
            getattr(templates, "evidence", None),
            legacy_path=legacy_path,
            mode="竞技场",
            action=action.name if action is not None else "observe",
            source=(
                state_label(action.source_state)
                if action is not None and action.source_state is not None
                else state_label(self.machine.state)
            ),
            targets=(
                tuple(state_label(state) for state in action.target_states)
                if action is not None
                else ()
            ),
            attempt=attempt,
            conclusion=conclusion,
        )

    def run(self, max_cycles: int | None = None) -> int:
        state_started = self.now()
        stable = StableObservation(required=2)
        recovered = False
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            state_before = self.machine.state
            try:
                screen = self.runtime.capture()
                if self.runtime.diagnostic_dir is not None:
                    self.runtime.save_current_frame(screen)
                preview_action, _ = self.machine.preview(screen)
                if not stable.update(preview_action.name):
                    self.sleep(self.poll_seconds)
                    continue
                action = self.machine.next_action(screen)
                stable.reset()
            except TicketExhausted as error:
                diagnostic = None
                if self.runtime.diagnostic_dir is not None:
                    diagnostic = self.runtime.save_diagnostic("ticket_exhausted", screen)
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式=竞技场 停止=旗帜资源不可安全购买 详情={error} "
                    f"已完成={self.machine.completed_cycles} 现场={diagnostic}"
                )
                return self.machine.completed_cycles
            except RuntimeError as error:
                if isinstance(error, UnrecognizedScreen):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"竞技场:{state_label(self.machine.state)}",
                    )
                    if wake_result in {
                        UnknownWakeResult.WAITING,
                        UnknownWakeResult.CLICKED,
                    }:
                        if wake_result is UnknownWakeResult.CLICKED:
                            state_started = self.now()
                        self.sleep(self.poll_seconds)
                        continue
                timeout = self._TIMEOUT_SECONDS[self.machine.state]
                if self.now() - state_started >= timeout:
                    if self.recovery is not None and not recovered:
                        recovered = True
                        self.runtime.log(
                            f"模式=竞技场 页面={state_label(self.machine.state)} 恢复=回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.reset_after_recovery()
                        state_started = self.now()
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
                    )
                    self._save_failure_diagnostic(
                        diagnostic,
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
                recovered = False
                self.runtime.log(
                    f"模式=竞技场 轮次={self.machine.completed_cycles} "
                    "业务完成=结算返回对手列表 目标连续=2"
                )
                return self.machine.completed_cycles
            if action.name == "purchase-friendship-ticket" and not self._purchase_allowed_today():
                self.machine.state = ArenaState.BATTLE
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式=竞技场 停止=今日友情点旗帜已购买 已完成={self.machine.completed_cycles}"
                )
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
                continue

            if action.name == "refresh-opponents":
                self.runtime.click(action.point, action.name)
                if not self._wait_until_safe_list(action):
                    failure_screen = self.runtime.capture()
                    diagnostic = self.runtime.save_diagnostic(
                        "refresh_opponents_failed",
                        failure_screen,
                    )
                    self._save_failure_diagnostic(
                        diagnostic,
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
                continue

            self._execute_transition(action)
            if action.name == "purchase-friendship-ticket":
                self._record_purchase_today()
            if self.machine.completed_cycles > cycles_before:
                recovered = False
                self.runtime.log(
                    f"模式=竞技场 轮次={self.machine.completed_cycles} "
                    "业务完成=结算返回对手列表 目标连续=2"
                )

            if self.machine.state != state_before:
                state_started = self.now()
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles

    def _execute_transition(self, action: Action) -> None:
        """Click and commit only after the declared target is stable for two frames."""
        if action.source_state is None or not action.target_states:
            raise RuntimeError(f"竞技场动作[{action.name}]缺少来源/目标合同")
        attempts = 1
        self.runtime.click(action.point, action.name)
        self.sleep(self._SETTLE_SECONDS)
        started = progressed = self.now()
        previous: Optional[np.ndarray] = None
        source_stable = StableObservation(required=2)
        target_stable = StableObservation(required=2)
        source_gone_logged = False
        source_has_gone = False
        absolute = min(
            180,
            max(self._TIMEOUT_SECONDS[target] for target in action.target_states),
        )
        no_progress = min(45, absolute)

        while self.now() - started < absolute:
            screen = self.runtime.capture()
            self._save_frame(screen)
            target = self.machine.action_target_state(screen, action)
            target_visible = target is not None
            source_visible = self.machine.action_source_visible(screen, action)

            target_key = target.value if target is not None else "other"
            if target_stable.update(target_key) and target is not None:
                self.machine.commit(action, target)
                self.runtime.log(
                    f"模式=竞技场 转场确认 动作={action.name} "
                    f"从={state_label(action.source_state)} 到={state_label(target)} "
                    "目标连续=2"
                )
                return

            if source_stable.update("source" if source_visible else "other") and source_visible:
                if not source_has_gone and attempts < 4:
                    attempts += 1
                    self.runtime.log(
                        f"模式=竞技场 转场重试 动作={action.name} "
                        f"来源={state_label(action.source_state)}仍在 "
                        f"尝试={attempts}/4 坐标={action.point}"
                    )
                    self.runtime.click(action.point, action.name)
                    source_stable.reset()
                    self.sleep(self._SETTLE_SECONDS)
                    continue
            elif not source_visible:
                source_has_gone = True
                if not source_gone_logged:
                    source_gone_logged = True
                    targets = "/".join(
                        state_label(item) for item in action.target_states
                    )
                    self.runtime.log(
                        f"模式=竞技场 等待转场 动作={action.name} "
                        f"来源={state_label(action.source_state)}已离开 目标={targets}待稳定"
                    )

            if meaningful_change(previous, screen):
                progressed = self.now()
            previous = screen
            if self.now() - progressed >= no_progress:
                break
            self.sleep(self.poll_seconds)

        diagnostic = None
        if self.runtime.diagnostic_dir is not None:
            diagnostic = self.runtime.save_diagnostic(
                f"no_transition_{action.source_state.value}_to_"
                f"{'_or_'.join(target.value for target in action.target_states)}",
                screen,
            )
            self._save_failure_diagnostic(
                diagnostic,
                screen,
                action=action,
                attempt=attempts,
                conclusion="来源页面已离开或点击耗尽，但目标页面未稳定出现",
            )
        self.runtime.log(
            f"模式=竞技场 状态=转场失败 动作={action.name} "
            f"从={state_label(action.source_state)} "
            f"到={'/'.join(state_label(target) for target in action.target_states)} "
            f"尝试={attempts}/4 诊断={diagnostic}"
        )
        raise RuntimeError(
            f"点击 {action.name} 后画面未稳定进入"
            f"[{'/'.join(state_label(target) for target in action.target_states)}]；"
            f"已保存诊断 {diagnostic}"
        )

    def _save_frame(self, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_current_frame(screen)

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
