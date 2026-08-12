import unittest
from pathlib import Path

import cv2
import numpy as np

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


class HiddenHudBattleMachine(BattleMachine):
    def preview(self, _screen):
        raise RuntimeError("battle HUD is hidden by a skill animation")


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

    def test_changing_battle_frames_emit_a_thirty_second_heartbeat(self):
        clock = Clock()
        logs = []
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            if captures > 40:
                raise ManualStop("stop test")
            return np.full((120, 200, 3), captures * 3 % 255, dtype=np.uint8)

        runner = ExpeditionRunner(
            BattleMachine(),
            Runtime(capture, lambda _: None, emit=logs.append),
            sleep=clock.sleep,
            now=clock.now,
        )

        with self.assertRaises(ManualStop):
            runner.run(max_cycles=1)

        self.assertTrue(any("心跳" in line and "战斗中" in line for line in logs))

    def test_changing_battle_frames_remain_progress_when_hud_is_hidden(self):
        clock = Clock()
        logs = []
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            if captures > 10:
                raise ManualStop("stop test")
            return np.random.default_rng(captures).integers(
                0, 256, (120, 200, 3), dtype=np.uint8
            )

        runner = ExpeditionRunner(
            HiddenHudBattleMachine(),
            Runtime(capture, lambda _: None, emit=logs.append),
            sleep=clock.sleep,
            poll_seconds=10,
            now=clock.now,
        )

        with self.assertRaises(ManualStop):
            runner.run(max_cycles=1)

        self.assertTrue(any("HUD暂时隐藏" in line for line in logs))

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
            if captures > 30:
                raise ManualStop("wake was incorrectly accepted forever")
            return screen

        runner = ExpeditionRunner(
            machine,
            Runtime(capture, clicks.append),
            sleep=clock.sleep,
            poll_seconds=20,
            now=clock.now,
        )

        with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
            runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))

    def test_brief_black_result_transition_is_timed_from_its_first_frame(self):
        clock = Clock()
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            if captures > 9:
                raise ManualStop("transition remained under its own timeout")
            if captures == 9:
                return np.zeros((120, 200, 3), dtype=np.uint8)
            return np.random.default_rng(captures).integers(
                0, 256, (120, 200, 3), dtype=np.uint8
            )

        runner = ExpeditionRunner(
            HiddenHudBattleMachine(),
            Runtime(capture, lambda _: None),
            sleep=clock.sleep,
            poll_seconds=10,
            now=clock.now,
        )

        with self.assertRaises(ManualStop):
            runner.run(max_cycles=1)

    def test_battle_start_accepts_changing_valid_frames_when_hud_is_hidden(self):
        clock = Clock()
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            return np.random.default_rng(captures).integers(
                0, 256, (120, 200, 3), dtype=np.uint8
            )

        runner = ExpeditionRunner(
            BattleStartMachine(),
            Runtime(capture, lambda _: None),
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertTrue(
            runner._wait_until_in_state(ExpeditionState.BATTLE, "battle-start")
        )

    def test_auto_enable_accepts_changing_battle_frames(self):
        clock = Clock()
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            return np.random.default_rng(captures).integers(
                0, 256, (120, 200, 3), dtype=np.uint8
            )

        runner = ExpeditionRunner(
            BattleStartMachine(),
            Runtime(capture, lambda _: None),
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertTrue(
            runner._wait_until_in_state(
                ExpeditionState.BATTLE, "enable-auto-battle"
            )
        )

    def test_failed_battle_start_never_returns_to_lobby(self):
        clock = Clock()
        recoveries = []
        machine = BattleStartMachine()
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
        )

        with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
            runner.run(max_cycles=1)

        self.assertEqual([], recoveries)

    def test_static_battle_fails_after_180_seconds_without_progress(self):
        clock = Clock()
        screen = np.full((120, 200, 3), 30, dtype=np.uint8)
        runner = ExpeditionRunner(
            BattleMachine(),
            Runtime(lambda: screen, lambda _: None),
            sleep=clock.sleep,
            poll_seconds=60,
            now=clock.now,
        )

        with self.assertRaisesRegex(RuntimeError, "no progress.*battle"):
            runner.run(max_cycles=1)

    def test_changing_battle_still_has_twenty_minute_absolute_limit(self):
        clock = Clock()
        captures = 0

        def capture():
            nonlocal captures
            captures += 1
            return np.full((120, 200, 3), captures * 7 % 255, dtype=np.uint8)

        runner = ExpeditionRunner(
            BattleMachine(),
            Runtime(capture, lambda _: None),
            sleep=clock.sleep,
            poll_seconds=300,
            now=clock.now,
        )

        with self.assertRaisesRegex(RuntimeError, "absolute timeout.*battle"):
            runner.run(max_cycles=1)

    def test_failed_transition_clicks_twice_then_stops(self):
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

        with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
            runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))

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

        with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
            runner.run(max_cycles=1)

        self.assertEqual([True], recoveries)


if __name__ == "__main__":
    unittest.main()
