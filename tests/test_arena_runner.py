from pathlib import Path
import unittest
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    Action,
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
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            choose_opponent=lambda safe: safe[0],
        )
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

    def test_refresh_waits_for_a_list_with_a_safe_opponent(self):
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        refresh = Action("refresh-opponents", (1344, 225))
        machine.preview.return_value = (refresh, None)
        machine.next_action.return_value = refresh
        machine.is_in_state.return_value = False
        clicks = []
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: np.full((60, 100, 3), 30, dtype=np.uint8),
                clicks.append,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )

        def refreshed() -> bool:
            machine.completed_cycles = 1
            return True

        runner._wait_until_safe_list = MagicMock(side_effect=refreshed)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual([(1344, 225)], clicks)
        runner._wait_until_safe_list.assert_called_once_with()
        self.assertEqual(ArenaState.LIST, machine.state)

    def test_safe_list_waiter_requires_both_list_and_available_opponent(self):
        machine = MagicMock()
        machine.is_in_state.return_value = True
        machine.has_safe_opponent.side_effect = [False, True]
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: np.full((60, 100, 3), 30, dtype=np.uint8),
                lambda point: None,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )

        self.assertTrue(runner._wait_until_safe_list())
        self.assertEqual(2, machine.has_safe_opponent.call_count)

    def test_safe_list_waiter_confirms_free_refresh_then_accepts_new_list(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        confirmation = fixture("free_refresh_confirm_live_20260814")
        screens = iter([confirmation, confirmation, fixture("list")])
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )

        self.assertTrue(runner._wait_until_safe_list())
        self.assertEqual(1, len(clicks))
        self.assertTrue(1160 <= clicks[0][0] <= 1300)
        self.assertTrue(770 <= clicks[0][1] <= 830)

    def test_safe_list_waiter_clicks_persisted_free_confirmation_at_most_four_times(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        confirmation = fixture("free_refresh_confirm_live_20260814")
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: confirmation,
                clicks.append,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )

        self.assertFalse(runner._wait_until_safe_list())
        self.assertEqual(4, len(clicks))

    def test_refresh_that_never_produces_a_safe_opponent_stops_with_diagnostic(self):
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        refresh = Action("refresh-opponents", (1344, 225))
        machine.preview.return_value = (refresh, None)
        machine.next_action.return_value = refresh
        machine.is_in_state.return_value = False
        runtime = MagicMock()
        runtime.dry_run = False
        runtime.diagnostic_dir = Path("diagnostics")
        runtime.capture.return_value = np.full((60, 100, 3), 30, dtype=np.uint8)
        runtime.save_diagnostic.return_value = Path("refresh.png")
        runner = ArenaRunner(machine, runtime, sleep=lambda seconds: None)
        runner._TIMEOUT_SECONDS = {**runner._TIMEOUT_SECONDS, ArenaState.LIST: 0}
        runner._wait_until_safe_list = MagicMock(return_value=False)

        with self.assertRaisesRegex(RuntimeError, "刷新对手后未出现安全对手列表"):
            runner.run(max_cycles=1)

        runtime.save_diagnostic.assert_called_once()


if __name__ == "__main__":
    unittest.main()
