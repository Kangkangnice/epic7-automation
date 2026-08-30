from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState
from auto_game_unified.games.epic7.expedition import ExpeditionRunner, ExpeditionState
from auto_game_unified.games.epic7.fodder import FodderRunner, FodderState
from auto_game_unified.games.epic7.story import StoryRunner, StoryState
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


def static_game_screen() -> np.ndarray:
    gradient = np.linspace(20, 180, 1982, dtype=np.uint8)
    gray = np.repeat(gradient[np.newaxis, :], 1132, axis=0)
    screen = np.repeat(gray[:, :, np.newaxis], 3, axis=2)
    screen[:52] = 0
    screen[:, 1920:] = 0
    return screen


@pytest.mark.parametrize(
    ("runner_type", "state", "timeout_name"),
    [
        (StoryRunner, StoryState.STAGE, "_TIMEOUT_SECONDS"),
        (ArenaRunner, ArenaState.LIST, "_TIMEOUT_SECONDS"),
        (ExpeditionRunner, ExpeditionState.HOME, "_STATE_TIMEOUT_SECONDS"),
        (FodderRunner, FodderState.STAGE, "_TIMEOUT_SECONDS"),
    ],
)
def test_every_live_runner_wakes_static_unknown_four_times_before_safe_failure(
    runner_type, state, timeout_name
):
    screen = static_game_screen()
    clicks: list[tuple[int, int]] = []
    machine = MagicMock()
    machine.state = state
    machine.completed_cycles = 0
    machine.preview.side_effect = UnrecognizedScreen("unknown page")
    runtime = Runtime(lambda: screen, clicks.append, emit=lambda _: None)
    runner = runner_type(machine, runtime, sleep=lambda _: None)
    if timeout_name == "_STATE_TIMEOUT_SECONDS":
        runner._STATE_TIMEOUT_SECONDS = 0
    else:
        runner._TIMEOUT_SECONDS = {state: 0}

    with patch.object(
        runtime,
        "save_diagnostic",
        return_value=Path("unknown.png"),
    ):
        with pytest.raises(RuntimeError, match="unknown page"):
            runner.run(max_cycles=1)

    assert clicks == [(991, 566), (991, 566), (991, 566), (991, 566)]
