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
    wait_until_target,
)
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)


_RANK_PROMOTION_REFERENCE_SIZE = (1982, 1132)
_RANK_PROMOTION_ARROW_REGION = (850, 760, 280, 170)
_RANK_PROMOTION_CONFIRM_REGION = (700, 930, 520, 202)
_FREE_REFRESH_TITLE_REGION = (700, 300, 550, 160)
_FREE_REFRESH_OFFER_REGION = (850, 700, 350, 180)
_FREE_REFRESH_CONFIRM_REGION = (1050, 700, 400, 180)


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


def find_free_refresh_confirm(
    screen: np.ndarray,
    title_template: np.ndarray,
    free_template: np.ndarray,
    confirm_template: np.ndarray,
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
            0.90,
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
        refresh_title=load_template(str(template_dir / "arena_refresh_title.png")),
        refresh_free=load_template(str(template_dir / "arena_refresh_free.png")),
        refresh_confirm=load_template(str(template_dir / "arena_refresh_confirm.png")),
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
    _AUTO_CLICK_POINT = (1690, 96)
    _OPPONENT_STATUS_REGIONS = (
        (600, 320, 220, 135),
        (600, 510, 220, 140),
        (600, 705, 220, 140),
    )
    _FAILED_RED_MIN_RATIO = 0.50
    _AVAILABLE_RED_MAX_RATIO = 0.05
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
    ) -> None:
        self.templates = templates
        self.state = initial_state
        self.completed_cycles = 0
        self.choose_opponent = choose_opponent
        self._selected_opponent: int | None = None

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
            if challenge is None:
                return False
            list_ready = self._locate(screen, "list_ready")
            if list_ready is None:
                return True
            return challenge.score >= list_ready.score
        return self._visible(screen, self._STATE_TEMPLATE[state])

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
            self._selected_opponent = self.choose_opponent(safe)
            self.state = ArenaState.SELECTED
            return Action(
                "select-opponent",
                self._opponent_point(screen, self._selected_opponent),
            )
        if all(value is False for value in availability):
            self._selected_opponent = None
            return Action("refresh-opponents", self._refresh_point(screen))
        raise RuntimeError("竞技场对手行无法安全分类")

    def observe_battle(
        self,
        screen: np.ndarray,
        previous_screen: np.ndarray | None,
    ) -> BattleObservation:
        start = self._locate(screen, "battle_start")
        controls = observe_battle_controls(screen)
        auto_state = {
            BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
            BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
            BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
        }[controls]
        auto_match = self._locate(screen, "auto_off")
        result = self._locate(screen, "confirm")
        no_ticket = self._locate(screen, "no_ticket")
        progressing = (
            auto_state is AutoBattleState.AUTO
            and valid_game_frame(screen)
            and meaningful_change(previous_screen, screen)
        )
        return BattleObservation(
            pre_battle_visible=start is not None,
            battle_visible=controls is not BattleControls.TRANSITION,
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
            pre_battle_business_visible=no_ticket is not None,
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
                self.state = ArenaState.LIST
                return self._list_action(screen)
            if self._visible(screen, "confirm"):
                return Action("confirm-result", self._locate(screen, "confirm").center)
            rank_confirm = find_rank_promotion_confirm(
                screen,
                self.templates.rank_promotion_arrow,
                self.templates.rank_confirm,
            )
            if rank_confirm is not None:
                return Action("confirm-rank", rank_confirm.center)
            raise RuntimeError("结果确认后应回到对手列表")

        if self.state == ArenaState.SELECTED and not self.is_in_state(screen, ArenaState.SELECTED):
            if self._selected_opponent is None:
                self.state = ArenaState.LIST
                return self._list_action(screen)
            return Action(
                "select-opponent",
                self._opponent_point(screen, self._selected_opponent),
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
        previous_state = self.state
        self.state = ArenaState.CONFIRMING if previous_state == ArenaState.RESULT else self._NEXT_STATE[self.state]
        return Action(name, match.center)

    def preview(self, screen: np.ndarray):
        snapshot = self.state, self.completed_cycles, self._selected_opponent
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            self.state, self.completed_cycles, self._selected_opponent = snapshot


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
                        self.machine.state = ArenaState.LIST
                        state_started = self.now()
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
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
                f"页面={state_label(state_before)} 动作={action.name}"
            )
            self.runtime.click(action.point, action.name)
            if self.runtime.dry_run:
                return self.machine.completed_cycles

            if action.name == "battle-start":
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1,
                )
                state_started = self.now()
                stable.reset()
                continue

            if action.name == "refresh-opponents":
                if not self._wait_until_safe_list():
                    diagnostic = self.runtime.save_diagnostic(
                        "refresh_opponents_failed",
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
                    f"模式=竞技场 状态=转场失败 "
                    f"从={state_label(state_before)} 到={state_label(new_state)} "
                    f"诊断={diagnostic}"
                )
                raise RuntimeError(
                    f"点击 {action.name} 后画面未推进到"
                    f"[{state_label(new_state)}]；已保存诊断 {diagnostic}"
                )
            if action.name == "purchase-friendship-ticket":
                self._record_purchase_today()

            if self.machine.state != state_before:
                state_started = self.now()
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles

    def _wait_until_in_state(self, state: ArenaState) -> bool:
        """轮询直到画面进入目标状态；单帧命中即确认，超时返回 False。

        以各状态超时表推算绝对/无进展上限：合法的慢转场（加载/动画）
        仍可被捕获，而无效点击则清晰地失败而非级联进入错误状态。
        """
        return wait_until_target(
            capture=self.runtime.capture,
            save_frame=self._save_frame,
            is_target=lambda screen: self.machine.is_in_state(screen, state),
            absolute_seconds=min(180, self._TIMEOUT_SECONDS[state]),
            no_progress_seconds=min(45, self._TIMEOUT_SECONDS[state]),
            poll_seconds=self.poll_seconds,
            sleep=self.sleep,
            now=self.now,
            settle_seconds=self._SETTLE_SECONDS,
        )

    def _save_frame(self, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_current_frame(screen)

    def _wait_until_safe_list(self) -> bool:
        self.sleep(self._SETTLE_SECONDS)
        started = self.now()
        last_progress = started
        previous: Optional[np.ndarray] = None
        absolute = min(180, self._TIMEOUT_SECONDS[ArenaState.LIST])
        no_progress = min(45, self._TIMEOUT_SECONDS[ArenaState.LIST])
        refresh_confirm_stable = StableObservation(required=2)
        refresh_confirm_clicks = 0
        while self.now() - started < absolute:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            if (
                self.machine.is_in_state(screen, ArenaState.LIST)
                and self.machine.has_safe_opponent(screen)
            ):
                return True
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
