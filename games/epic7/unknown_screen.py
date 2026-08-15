from enum import Enum

import numpy as np

from auto_game_unified.core.battle_supervisor import valid_game_frame
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)


_CANVAS_SIZE = (1132, 1982)
_RENDER_TOP = 52
_RENDER_RIGHT = 1920


def _valid_render_canvas(screen: np.ndarray) -> bool:
    if screen.shape[:2] != _CANVAS_SIZE:
        return False
    return (
        float(np.mean(screen[:_RENDER_TOP])) <= 2.0
        and float(np.mean(screen[:, _RENDER_RIGHT:])) <= 2.0
    )


class UnrecognizedScreen(RuntimeError):
    """The current mode cannot recognize the page required by its state."""


class UnknownWakeResult(Enum):
    WAITING = "waiting"
    CLICKED = "clicked"
    SKIPPED = "skipped"
    EXHAUSTED = "exhausted"


class UnknownScreenWake:
    """Safely try to dismiss a static, non-battle unknown game overlay."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        recovery_gate: RecoveryGate | None = None,
        max_clicks: int = 2,
    ) -> None:
        self.runtime = runtime
        self.recovery_gate = recovery_gate
        self.max_clicks = max_clicks
        self.reset()

    def reset(self) -> None:
        self._context: str | None = None
        self._previous: np.ndarray | None = None
        self._clicks = 0
        self._exhausted_reported = False

    def handle(self, screen: np.ndarray, *, context: str) -> UnknownWakeResult:
        if context != self._context:
            self.reset()
            self._context = context

        if (
            self.runtime.dry_run
            or (self.recovery_gate is not None and self.recovery_gate.locked)
            or not _valid_render_canvas(screen)
            or not valid_game_frame(screen)
            or observe_battle_controls(screen) is not BattleControls.TRANSITION
        ):
            self._previous = None
            return UnknownWakeResult.SKIPPED

        if self._previous is None:
            self._previous = screen.copy()
            return UnknownWakeResult.WAITING

        if self._previous.shape != screen.shape or meaningful_change(
            self._previous, screen
        ):
            self._previous = screen.copy()
            return UnknownWakeResult.WAITING

        self._previous = None
        if self._clicks >= self.max_clicks:
            if not self._exhausted_reported:
                self._save_diagnostic("unknown_after_wake_failed", screen)
                self.runtime.log(
                    f"页面={context} 未知画面唤醒失败={self._clicks}/{self.max_clicks} "
                    "后续=进入原有安全恢复"
                )
                self._exhausted_reported = True
            return UnknownWakeResult.EXHAUSTED

        if self._clicks == 0:
            self._save_diagnostic("unknown_before_wake", screen)
        self._clicks += 1
        point = screen.shape[1] // 2, screen.shape[0] // 2
        self.runtime.log(
            f"页面={context} 动作=点击未知画面中央 "
            f"尝试={self._clicks}/{self.max_clicks}"
        )
        self.runtime.click(point, "wake-unknown-screen")
        return UnknownWakeResult.CLICKED

    def _save_diagnostic(self, label: str, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_diagnostic(label, screen)
