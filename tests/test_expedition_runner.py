import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7.expedition import (
    ExpeditionAction,
    ExpeditionRunner,
    ExpeditionState,
    ExpeditionStateMachine,
    PostersExhausted,
    build_expedition_templates,
)


ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class ActionMachine:
    def __init__(self, transition=True):
        self.state = ExpeditionState.HOME
        self.completed_cycles = 0
        self.transition = transition

    def preview(self, _screen):
        if self.state == ExpeditionState.POSTERS and self.transition:
            return None, (ExpeditionState.HOME, 1)
        return ExpeditionAction("test-action", (10, 20)), (ExpeditionState.POSTERS, 0)

    def next_action(self, _screen):
        if self.state == ExpeditionState.POSTERS and self.transition:
            self.state = ExpeditionState.HOME
            self.completed_cycles = 1
            return None
        self.state = ExpeditionState.POSTERS
        return ExpeditionAction("test-action", (10, 20))

    def is_in_state(self, _screen, _state):
        return self.transition


class BattleMachine:
    def __init__(self):
        self.state = ExpeditionState.BATTLE
        self.completed_cycles = 0

    def preview(self, _screen):
        return None, (ExpeditionState.BATTLE, 0)

    def next_action(self, _screen):
        return None


class EmptyMachine(BattleMachine):
    def preview(self, _screen):
        raise PostersExhausted("empty")


class BattleStartMachine:
    def __init__(self):
        self.state = ExpeditionState.TEAM
        self.completed_cycles = 0

    def preview(self, _screen):
        return ExpeditionAction("battle-start", (10, 20)), (ExpeditionState.BATTLE, 0)

    def next_action(self, _screen):
        self.state = ExpeditionState.BATTLE
        return ExpeditionAction("battle-start", (10, 20))

    def is_in_state(self, _screen, _state):
        return False


class ExpeditionRunnerTests(unittest.TestCase):
    def test_battle_start_delegates_to_supervisor_and_returns_to_result_handling(self):
        machine = MagicMock()
        machine.state = ExpeditionState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = ExpeditionRunner(
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
        self.assertEqual(ExpeditionState.RESULT, machine.state)

    def test_action_requires_two_equal_observations_before_click(self):
        clock = Clock()
        clicks = []
        machine = ActionMachine()
        runtime = Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), clicks.append)
        runner = ExpeditionRunner(machine, runtime, sleep=clock.sleep, now=clock.now)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual([(10, 20)], clicks)

    def test_empty_posters_stops_as_resource_exhaustion(self):
        clock = Clock()
        runtime = Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), lambda _: None)
        runner = ExpeditionRunner(EmptyMachine(), runtime, sleep=clock.sleep, now=clock.now)

        completed = runner.run(max_cycles=4)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)

    def test_default_supervisor_keeps_expedition_twenty_minute_limit(self):
        runner = ExpeditionRunner(
            BattleMachine(),
            Runtime(
                lambda: np.zeros((120, 200, 3), dtype=np.uint8),
                lambda point: None,
            ),
        )

        self.assertEqual(20 * 60, runner.battle_supervisor.config.absolute_seconds)
        self.assertEqual(
            20 * 60,
            runner.battle_supervisor.config.no_business_progress_seconds,
        )
        self.assertIs(runner.recovery_gate, runner.battle_supervisor.gate)

    def test_persistent_campfire_does_not_count_as_a_successful_wake(self):
        clock = Clock()
        clicks = []
        captures = 0
        fixture_path = (
            ROOT / "tests" / "fixtures" / "epic7_expedition" / "campfire_idle.png"
        )
        screen = cv2.cvtColor(cv2.imread(str(fixture_path)), cv2.COLOR_BGR2RGB)
        machine = ExpeditionStateMachine(
            build_expedition_templates(
                ROOT / "games" / "epic7" / "templates" / "expedition"
            ),
            initial_state=ExpeditionState.OUTCOME,
        )

        def capture():
            nonlocal captures
            captures += 1
            if captures > 60:
                raise ManualStop("wake was incorrectly accepted forever")
            return screen

        runner = ExpeditionRunner(
            machine,
            Runtime(capture, clicks.append),
            sleep=clock.sleep,
            poll_seconds=20,
            now=clock.now,
        )

        with self.assertRaisesRegex(RuntimeError, "点击4次后画面未推进"):
            runner.run(max_cycles=1)

        self.assertEqual(4, len(clicks))

    def test_failed_battle_start_never_returns_to_lobby(self):
        clock = Clock()
        recoveries = []
        machine = BattleStartMachine()
        machine.observe_battle = MagicMock()
        supervisor = MagicMock()
        supervisor.run.side_effect = RuntimeError("battle entry was not confirmed")
        runner = ExpeditionRunner(
            machine,
            Runtime(
                lambda: np.full((120, 200, 3), 30, dtype=np.uint8),
                lambda _: None,
            ),
            sleep=clock.sleep,
            poll_seconds=60,
            now=clock.now,
            recovery=lambda: recoveries.append(True),
            battle_supervisor=supervisor,
        )

        with self.assertRaisesRegex(RuntimeError, "battle entry was not confirmed"):
            runner.run(max_cycles=1)

        self.assertEqual([], recoveries)

    def test_failed_transition_clicks_four_times_then_stops(self):
        clock = Clock()
        clicks = []
        machine = ActionMachine(transition=False)
        runner = ExpeditionRunner(
            machine,
            Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), clicks.append),
            sleep=clock.sleep,
            poll_seconds=20,
            now=clock.now,
        )

        with self.assertRaisesRegex(RuntimeError, "点击4次后画面未推进"):
            runner.run(max_cycles=1)

        self.assertEqual(4, len(clicks))

    def test_failed_transition_uses_only_one_recovery_for_a_poster(self):
        clock = Clock()
        recoveries = []
        machine = ActionMachine(transition=False)
        runner = ExpeditionRunner(
            machine,
            Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), lambda _: None),
            sleep=clock.sleep,
            poll_seconds=20,
            now=clock.now,
            recovery=lambda: recoveries.append(True),
        )

        with self.assertRaisesRegex(RuntimeError, "点击4次后画面未推进"):
            runner.run(max_cycles=1)

        self.assertEqual([True], recoveries)


if __name__ == "__main__":
    unittest.main()
