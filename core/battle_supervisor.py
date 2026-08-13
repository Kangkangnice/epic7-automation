from dataclasses import dataclass
from enum import Enum
from time import monotonic, sleep as default_sleep
from typing import Callable

import numpy as np

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation, meaningful_change


class AutoBattleState(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class BattleOutcome(Enum):
    RESULT_REACHED = "result_reached"
    PRE_BATTLE_BUSINESS = "pre_battle_business"


@dataclass(frozen=True)
class BattleObservation:
    pre_battle_visible: bool
    battle_visible: bool
    result_visible: bool
    frame_valid: bool
    auto_state: AutoBattleState
    auto_point: tuple[int, int] | None = None
    business_progress: bool = False
    allowed_action: tuple[str, tuple[int, int]] | None = None
    pre_battle_business_visible: bool = False


@dataclass(frozen=True)
class BattleConfig:
    mode: str
    poll_seconds: float = 1.0
    entry_absolute_seconds: float = 180
    no_activity_seconds: float = 180
    no_business_progress_seconds: float = 900
    absolute_seconds: float = 900
    unrecognized_seconds: float = 45
    black_seconds: float = 45
    auto_confirm_seconds: float = 15
    heartbeat_seconds: float = 30


BattleObserver = Callable[[np.ndarray, np.ndarray | None], BattleObservation]


def valid_game_frame(screen: np.ndarray) -> bool:
    content = screen[
        round(screen.shape[0] * 0.05) :,
        : round(screen.shape[1] * 0.97),
    ]
    return float(np.mean(content)) >= 3.0 and float(np.std(content)) >= 5.0


class BattleSupervisor:
    def __init__(
        self,
        runtime: Runtime,
        gate: RecoveryGate,
        config: BattleConfig,
        *,
        now: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self.runtime = runtime
        self.gate = gate
        self.config = config
        self.now = now
        self.sleep = sleep

    def _fail(self, label: str, message: str, screen: np.ndarray) -> None:
        path = (
            self.runtime.save_diagnostic(label, screen)
            if self.runtime.diagnostic_dir is not None
            else "not-configured"
        )
        self.runtime.log(
            f"mode={self.config.mode} phase=battle status=safe-stop "
            f"reason={message} diagnostic={path}"
        )
        raise RuntimeError(f"{message}; saved {path}")

    def run(self, observe: BattleObserver, *, cycle: int) -> BattleOutcome:
        self.gate.lock(mode=self.config.mode, cycle=cycle)
        started = active_at = business_at = heartbeat = self.now()
        invalid_since = black_since = auto_wait_since = None
        previous = None
        auto_clicked = False
        last_allowed_action = None
        entry_confirmed = False
        auto_confirmed = False
        battle_stable = StableObservation(required=2)
        auto_stable = StableObservation(required=2)
        allowed_stable = StableObservation(required=2)
        business_stable = StableObservation(required=2)
        result_stable = StableObservation(required=2)
        try:
            while True:
                screen = self.runtime.capture()
                if self.runtime.diagnostic_dir is not None:
                    self.runtime.save_current_frame(screen)
                observation = observe(screen, previous)
                current = self.now()

                result_signature = "result" if observation.result_visible else "other"
                if (
                    result_stable.update(result_signature)
                    and observation.result_visible
                ):
                    self.runtime.log(
                        f"mode={self.config.mode} cycle={cycle} "
                        "phase=result status=confirmed"
                    )
                    return BattleOutcome.RESULT_REACHED

                business_signature = (
                    "business"
                    if observation.pre_battle_business_visible
                    else "other"
                )
                if (
                    business_stable.update(business_signature)
                    and observation.pre_battle_business_visible
                    and not entry_confirmed
                ):
                    self.runtime.log(
                        f"mode={self.config.mode} cycle={cycle} "
                        "phase=pre-battle status=business-handoff"
                    )
                    return BattleOutcome.PRE_BATTLE_BUSINESS

                entered = observation.battle_visible or (
                    not observation.pre_battle_visible
                    and observation.allowed_action is None
                    and observation.frame_valid
                    and meaningful_change(previous, screen)
                )
                if (
                    battle_stable.update("battle" if entered else "other")
                    and entered
                    and not entry_confirmed
                ):
                    entry_confirmed = True
                    self.runtime.log(
                        f"mode={self.config.mode} cycle={cycle} "
                        "phase=battle status=entry-confirmed"
                    )

                if meaningful_change(previous, screen):
                    active_at = current
                if observation.business_progress:
                    business_at = current

                if not observation.frame_valid:
                    black_since = current if black_since is None else black_since
                    if current - black_since >= self.config.black_seconds:
                        self._fail(
                            "battle_black_timeout", "black frame timeout", screen
                        )
                else:
                    black_since = None

                recognized = (
                    observation.pre_battle_visible
                    or observation.battle_visible
                    or observation.result_visible
                    or observation.allowed_action is not None
                    or observation.pre_battle_business_visible
                )
                if observation.frame_valid and not recognized:
                    invalid_since = current if invalid_since is None else invalid_since
                    if current - invalid_since >= self.config.unrecognized_seconds:
                        self._fail(
                            "battle_unrecognized",
                            "unrecognized battle frame timeout",
                            screen,
                        )
                else:
                    invalid_since = None

                stable_auto = auto_stable.update(observation.auto_state.value)
                allowed_signature = (
                    "none"
                    if observation.allowed_action is None
                    else (
                        f"{observation.allowed_action[0]}:"
                        f"{observation.allowed_action[1]}"
                    )
                )
                allowed_confirmed = allowed_stable.update(allowed_signature)
                if observation.allowed_action is None:
                    last_allowed_action = None
                elif (
                    allowed_confirmed
                    and observation.allowed_action != last_allowed_action
                ):
                    action_name, action_point = observation.allowed_action
                    self.runtime.click(action_point, action_name)
                    last_allowed_action = observation.allowed_action
                    business_at = current

                if (
                    stable_auto
                    and observation.auto_state is AutoBattleState.MANUAL
                    and not auto_clicked
                ):
                    if observation.auto_point is None:
                        self._fail(
                            "auto_point_missing",
                            "manual state had no auto point",
                            screen,
                        )
                    self.runtime.click(
                        observation.auto_point, "enable-auto-battle"
                    )
                    auto_clicked = True
                    auto_wait_since = current
                    auto_stable.reset()
                elif (
                    stable_auto
                    and observation.auto_state is AutoBattleState.AUTO
                ) or observation.business_progress:
                    auto_wait_since = None
                    if not auto_confirmed:
                        auto_confirmed = True
                        self.runtime.log(
                            f"mode={self.config.mode} cycle={cycle} "
                            "phase=battle status=auto-confirmed"
                        )
                elif (
                    entry_confirmed
                    and not auto_confirmed
                    and auto_wait_since is None
                    and observation.battle_visible
                ):
                    auto_wait_since = current

                if (
                    auto_wait_since is not None
                    and current - auto_wait_since
                    >= self.config.auto_confirm_seconds
                ):
                    self._fail(
                        "auto_not_confirmed",
                        "auto battle was not confirmed",
                        screen,
                    )
                if (
                    not entry_confirmed
                    and current - started >= self.config.entry_absolute_seconds
                ):
                    self._fail(
                        "battle_entry_timeout",
                        "battle entry was not confirmed",
                        screen,
                    )
                if current - active_at >= self.config.no_activity_seconds:
                    self._fail(
                        "battle_no_activity",
                        "battle screen had no activity",
                        screen,
                    )
                if (
                    current - business_at
                    >= self.config.no_business_progress_seconds
                ):
                    self._fail(
                        "battle_no_business_progress",
                        "battle made no business progress",
                        screen,
                    )
                if current - started >= self.config.absolute_seconds:
                    self._fail(
                        "battle_absolute_timeout",
                        "battle absolute timeout",
                        screen,
                    )
                if current - heartbeat >= self.config.heartbeat_seconds:
                    self.runtime.log(
                        f"mode={self.config.mode} cycle={cycle} "
                        "phase=battle status=heartbeat "
                        f"elapsed={current - started:.0f}s "
                        f"activity_age={current - active_at:.0f}s "
                        f"business_age={current - business_at:.0f}s"
                    )
                    heartbeat = current

                previous = screen
                self.sleep(self.config.poll_seconds)
        finally:
            self.gate.unlock()
