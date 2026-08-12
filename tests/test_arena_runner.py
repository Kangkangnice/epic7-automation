from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaStateMachine, build_templates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class ArenaRunnerTests(unittest.TestCase):
    def test_one_recorded_cycle_clicks_each_action_once(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        # Map each state to the fixture that represents its settled screen. The
        # runner now captures once per decision and again per transition check, so
        # the capture must reflect the machine's current state rather than a fixed
        # sequence.
        screen_for_state = {
            "list": "list",
            "selected": "selected",
            "team": "team",
            "battle": "battle",
            "result": "result",
            "confirming": "list",
        }
        clicks: list[tuple[int, int]] = []
        runtime = Runtime(lambda: fixture(screen_for_state[machine.state.value]), clicks.append)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual(
            [(750, 406), (960, 1045), (1257, 1040), (1692, 90), (1747, 1045)],
            clicks,
        )


if __name__ == "__main__":
    unittest.main()
