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
        (
            ExpeditionRunner,
            ExpeditionState.HOME,
            "_STATE_TIMEOUT_SECONDS",
        ),
        (FodderRunner, FodderState.STAGE, "_TIMEOUT_SECONDS"),
    ],
)
def test_live_runner_never_clicks_an_unknown_screen(
    runner_type, state, timeout_name
):
    """认不出画面的页面上，**任何一条路线都不许点屏幕中央**。

    ⚠️ 2026-09-26 翻过来的用例：以前竞技场 / 远征 / 狗粮三条都预期「点中央 4 次」。
    用户实跑原话「眼睛瞎了一直点中间」—— 那是事故。现在统一为「只等、只报、
    不动手」，超时后由主循环报错收尾。
    """
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

    assert clicks == [], f"认不出的页面上动手了：{clicks}"
