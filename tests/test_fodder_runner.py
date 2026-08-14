from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.games.epic7.fodder import (
    FodderRunner,
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_fodder"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "fodder"


def fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


class FodderRunnerTests(unittest.TestCase):
    def runner_for(self, names, *, clicks, supervisor, logs=None):
        screens = iter(fixture(name) for name in names for _ in range(2))
        return FodderRunner(
            FodderStateMachine(build_fodder_templates(TEMPLATES)),
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=(logs if logs is not None else []).append,
            ),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

    def test_committed_battle_returns_control_to_results_state(self):
        machine = MagicMock()
        machine.state = FodderState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = FodderRunner(
            machine,
            Runtime(
                lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                lambda _: None,
            ),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

        runner._run_committed_battle(cycle=1)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
        self.assertEqual(FodderState.RESULTS, machine.state)

    def test_target_cycle_is_counted_without_clicking_replay(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = self.runner_for(
            ["stage_3_7", "assistant", "team", "clear", "results", "replay"],
            clicks=clicks,
            supervisor=supervisor,
            logs=logs,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual(5, len(clicks))
        self.assertFalse(any("action=replay point=" in line for line in logs))
        supervisor.run.assert_called_once()

    def test_two_cycles_click_replay_once_then_continue(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = self.runner_for(
            [
                "stage_3_7", "assistant", "team", "clear", "results", "replay",
                "replay_assistant", "team", "clear", "results", "replay",
            ],
            clicks=clicks,
            supervisor=supervisor,
            logs=logs,
        )

        completed = runner.run(max_cycles=2)

        self.assertEqual(2, completed)
        self.assertEqual(10, len(clicks))
        self.assertEqual(1, sum("action=replay point=" in line for line in logs))
        self.assertEqual(2, supervisor.run.call_count)

    def test_stamina_exhaustion_is_a_normal_resource_stop(self):
        machine = MagicMock()
        machine.state = FodderState.TEAM
        machine.completed_cycles = 0
        machine.preview.side_effect = StaminaExhausted("no leaves")
        runner = FodderRunner(
            machine,
            Runtime(
                lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                lambda _: None,
                emit=lambda _: None,
            ),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)

    def test_dry_run_rejects_unknown_screen_without_polling(self):
        sleeps: list[float] = []
        with TemporaryDirectory() as directory:
            runner = FodderRunner(
                FodderStateMachine(build_fodder_templates(TEMPLATES)),
                Runtime(
                    lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                    lambda _: None,
                    dry_run=True,
                    diagnostic_dir=Path(directory),
                ),
                sleep=sleeps.append,
            )

            with self.assertRaisesRegex(RuntimeError, "dry-run"):
                runner.run(max_cycles=1)

        self.assertEqual([], sleeps)


if __name__ == "__main__":
    unittest.main()
