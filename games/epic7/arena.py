from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import date
from time import monotonic, sleep as default_sleep
from typing import Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation, meaningful_change


_RANK_PROMOTION_REFERENCE_SIZE = (1982, 1132)
_RANK_PROMOTION_ARROW_REGION = (850, 760, 280, 170)
_RANK_PROMOTION_CONFIRM_REGION = (700, 930, 520, 202)


def find_rank_promotion_confirm(
    screen: np.ndarray,
    arrow_template: np.ndarray,
    confirm_template: np.ndarray,
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
            0.90,
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


class ArenaState(Enum):
    LIST = "list"
    SELECTED = "selected"
    TEAM = "team"
    BATTLE = "battle"
    RESULT = "result"
    CONFIRMING = "confirming"


class TicketExhausted(RuntimeError):
    """The game presented its ticket-purchase popup instead of entering battle."""


@dataclass(frozen=True)
class Action:
    name: str
    point: tuple[int, int]


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
    threshold: float = 0.98


def build_templates(template_dir: Path) -> ArenaTemplates:
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
    )


class ArenaStateMachine:
    """Arena cycle in the game window's local coordinate space.

    Only the first-opponent row lacks its own template; its click point is derived as a
    fixed pixel offset from the live ``list_ready`` anchor (stable at unchanged resolution),
    which preserves location independence without a new asset.
    """

    # Per-template match thresholds. The shared default (templates.threshold) is 0.98;
    # arena UI animates/drifts like story, so the dynamic screens are relaxed here.
    _THRESHOLDS = {
        "list_ready": 0.88,
        "challenge": 0.90,
        "battle_start": 0.90,
        "auto_off": 0.85,
        "confirm": 0.90,
        "no_ticket": 0.90,
        "friendship_ticket_offer": 0.92,
        "ticket_purchase_button": 0.92,
    }

    _REFERENCE_SIZE = (1982, 1132)
    _REGIONS = {
        "list_ready": (700, 900, 520, 250),
        "challenge": (700, 930, 520, 202),
        "battle_start": (900, 930, 550, 202),
        "auto_off": (1550, 0, 300, 220),
        "confirm": (1500, 930, 420, 202),
        "no_ticket": (700, 150, 700, 300),
        "friendship_ticket_offer": (600, 450, 800, 360),
        "ticket_purchase_button": (900, 760, 500, 260),
    }

    # First opponent row click point relative to the live ``list_ready`` anchor center.
    # Derived from the original hard-coded coordinates (anchor center ~ (960, 1025),
    # first opponent ~ (750, 386) -> offset (-210, -639)).
    _FIRST_OPPONENT_OFFSET = (-210, -639)

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
        ArenaState.LIST: "select-first-row",
        ArenaState.SELECTED: "challenge",
        ArenaState.TEAM: "battle-start",
        ArenaState.BATTLE: "enable-auto",
        ArenaState.RESULT: "confirm-result",
    }

    def __init__(self, templates: ArenaTemplates, *, initial_state: ArenaState = ArenaState.LIST) -> None:
        self.templates = templates
        self.state = initial_state
        self.completed_cycles = 0

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

    def is_in_state(self, screen: np.ndarray, state: "ArenaState") -> bool:
        """True when the screen has actually settled into ``state``.

        SELECTED is special: the ``challenge`` button is visible in both LIST and
        SELECTED, but only becomes the dominant (active) button after an opponent is
        selected. We treat SELECTED as reached once ``challenge`` out-scores
        ``list_ready``, which is the reliable signal that the selection registered.
        """
        if state == ArenaState.SELECTED:
            challenge = self._locate(screen, "challenge")
            if challenge is None:
                return False
            list_ready = self._locate(screen, "list_ready")
            if list_ready is None:
                return True
            return challenge.score >= list_ready.score
        return self._visible(screen, self._STATE_TEMPLATE[state])

    def _first_opponent_point(self, screen: np.ndarray) -> tuple[int, int]:
        anchor = self._locate(screen, "list_ready")
        if anchor is None:
            raise RuntimeError("list_ready anchor lost while selecting first opponent")
        return (
            anchor.center[0] + self._FIRST_OPPONENT_OFFSET[0],
            anchor.center[1] + self._FIRST_OPPONENT_OFFSET[1],
        )

    def next_action(self, screen: np.ndarray) -> Action:
        if self.state == ArenaState.BATTLE and self._visible(screen, "no_ticket"):
            offer = self._locate(screen, "friendship_ticket_offer")
            purchase = self._locate(screen, "ticket_purchase_button")
            if offer is None or purchase is None:
                raise TicketExhausted(
                    "ticket popup did not match the friendship 30 -> flags 5 offer"
                )
            self.state = ArenaState.TEAM
            return Action("purchase-friendship-ticket", purchase.center)

        if self.state == ArenaState.CONFIRMING:
            if self._visible(screen, "list_ready"):
                self.completed_cycles += 1
                self.state = ArenaState.SELECTED
                return Action("select-first-row", self._first_opponent_point(screen))
            if self._visible(screen, "confirm"):
                return Action("confirm-result", self._locate(screen, "confirm").center)
            rank_confirm = find_rank_promotion_confirm(
                screen,
                self.templates.rank_promotion_arrow,
                self.templates.rank_confirm,
            )
            if rank_confirm is not None:
                return Action("confirm-rank", rank_confirm.center)
            raise RuntimeError("expected result confirmation to close into list")

        if self.state == ArenaState.SELECTED and not self.is_in_state(screen, ArenaState.SELECTED):
            return Action("select-first-row", self._first_opponent_point(screen))

        template_name = self._STATE_TEMPLATE[self.state]
        match = self._locate(screen, template_name)
        if match is None:
            raise RuntimeError(f"expected {self.state.value} screen was not recognized")

        if self.state == ArenaState.LIST:
            action = Action("select-first-row", self._first_opponent_point(screen))
            self.state = self._NEXT_STATE[self.state]
            return action

        name = self._ACTION_NAME[self.state]
        previous_state = self.state
        self.state = ArenaState.CONFIRMING if previous_state == ArenaState.RESULT else self._NEXT_STATE[self.state]
        return Action(name, match.center)

    def preview(self, screen: np.ndarray):
        snapshot = self.state, self.completed_cycles
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            self.state, self.completed_cycles = snapshot


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
        purchase_stamp_path: Path | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.recovery = recovery
        self.purchase_stamp_path = purchase_stamp_path
        self.resource_exhausted = False

    def run(self, max_cycles: int | None = None) -> int:
        state_started = monotonic()
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
                timeout = self._TIMEOUT_SECONDS[self.machine.state]
                if monotonic() - state_started >= timeout:
                    if self.recovery is not None and not recovered:
                        recovered = True
                        self.runtime.log(
                            f"模式=竞技场 页面={self.machine.state.value} 恢复=回大厅重新导航"
                        )
                        self.recovery()
                        self.machine.state = ArenaState.LIST
                        state_started = monotonic()
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
                    )
                    self.runtime.log(f"timeout state={self.machine.state.value} diagnostic={diagnostic}")
                    raise RuntimeError(f"{error}; stopped safely, saved {diagnostic}") from error
                self.sleep(self.poll_seconds)
                continue

            if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
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
                f"页面={state_before.value} 动作={action.name}"
            )
            self.runtime.click(action.point, action.name)
            if self.runtime.dry_run:
                return self.machine.completed_cycles

            # Verify the click actually advanced the screen. Without this the machine
            # blindly advances state on every click; a click that lands during an
            # animation (e.g. challenge, right after opponent selection) is silently
            # swallowed and the run later times out at the wrong screen.
            new_state = self.machine.state
            if new_state != ArenaState.CONFIRMING and not self._wait_until_in_state(new_state):
                diagnostic = self.runtime.save_diagnostic(
                    f"no_transition_{state_before.value}_to_{new_state.value}", screen
                )
                self.runtime.log(
                    f"transition failed {state_before.value} -> {new_state.value} diagnostic={diagnostic}"
                )
                raise RuntimeError(
                    f"clicked {action.name} but screen did not advance to {new_state.value}; saved {diagnostic}"
                )
            if action.name == "purchase-friendship-ticket":
                self._record_purchase_today()

            if self.machine.state != state_before:
                state_started = monotonic()
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles

    def _wait_until_in_state(self, state: ArenaState) -> bool:
        """Poll until the screen settles into ``state``; return False on timeout.

        Uses the per-state timeout as the deadline so a legitimately slow transition
        (loading/animation) is still caught, while a click that did nothing fails
        clearly instead of cascading into a wrong state.
        """
        self.sleep(self._SETTLE_SECONDS)
        started = monotonic()
        last_progress = started
        last_heartbeat = started
        previous: Optional[np.ndarray] = None
        absolute = 900 if state == ArenaState.RESULT else min(180, self._TIMEOUT_SECONDS[state])
        no_progress = 180 if state == ArenaState.RESULT else min(45, self._TIMEOUT_SECONDS[state])
        while monotonic() - started < absolute:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            if self.machine.is_in_state(screen, state):
                return True
            if meaningful_change(previous, screen):
                last_progress = monotonic()
            previous = screen
            if state == ArenaState.RESULT and monotonic() - last_heartbeat >= 30:
                self.runtime.log("模式=竞技场 页面=战斗中 状态=心跳")
                last_heartbeat = monotonic()
            if monotonic() - last_progress >= no_progress:
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
            raise RuntimeError("purchase stamp path is not configured")
        self.purchase_stamp_path.parent.mkdir(parents=True, exist_ok=True)
        self.purchase_stamp_path.write_text(date.today().isoformat(), encoding="utf-8")
