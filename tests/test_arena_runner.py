from pathlib import Path
import unittest
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class ArenaRunnerTests(unittest.TestCase):
    def test_committed_battle_returns_control_to_result_state(self):
        machine = MagicMock()
        machine.state = ArenaState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: np.zeros((60, 100, 3), dtype=np.uint8),
                lambda point: None,
            ),
            battle_supervisor=supervisor,
            sleep=lambda seconds: None,
        )

        runner._run_committed_battle(cycle=1)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
        self.assertEqual(ArenaState.RESULT, machine.state)

    def test_pre_battle_business_handoff_keeps_battle_state_for_ticket_handling(self):
        machine = MagicMock()
        machine.state = ArenaState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.PRE_BATTLE_BUSINESS
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: np.zeros((60, 100, 3), dtype=np.uint8),
                lambda point: None,
            ),
            battle_supervisor=supervisor,
            sleep=lambda seconds: None,
        )

        runner._run_committed_battle(cycle=1)

        self.assertEqual(ArenaState.BATTLE, machine.state)

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
        auto_clicked = False

        def capture():
            if machine.state == ArenaState.BATTLE and auto_clicked:
                return fixture("result")
            return fixture(screen_for_state[machine.state.value])

        def click(point):
            nonlocal auto_clicked
            clicks.append(point)
            if point == (1692, 90):
                auto_clicked = True

        runtime = Runtime(capture, click)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual(
            [(750, 406), (960, 1045), (1257, 1040), (1692, 90), (1747, 1045)],
            clicks,
        )


if __name__ == "__main__":
    unittest.main()
