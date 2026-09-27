import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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
        return self.next_action(_screen), (self.state, self.completed_cycles)

    def next_action(self, _screen):
        if self.state is ExpeditionState.POSTERS:
            return None
        return ExpeditionAction(
            "test-action", (10, 20), source_state=ExpeditionState.HOME,
            target_states=(ExpeditionState.POSTERS,), source_page="测试来源",
            target_pages=("测试目标",),
        )

    def is_in_state(self, _screen, _state):
        return self.transition

    def action_source_visible(self, _screen, _action):
        return not self.transition

    def action_target_state(self, _screen, action):
        return ExpeditionState.POSTERS if self.transition else None

    def commit(self, _action, target):
        self.state = target
        self.completed_cycles = 1


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
        return self.next_action(_screen), (self.state, 0)

    def next_action(self, _screen):
        return ExpeditionAction(
            "battle-start", (10, 20), source_state=ExpeditionState.TEAM,
            target_states=(ExpeditionState.BATTLE,), source_page="队伍选择",
            target_pages=("战斗中",),
        )

    def is_in_state(self, _screen, _state):
        return False

    def action_source_visible(self, _screen, _action):
        return True

    def action_target_state(self, _screen, _action):
        return None

    def commit(self, _action, target):
        self.state = target


class PrepareBattleDirectMachine:
    """「准备战斗」点下去**直接**落到战斗页（游戏跳过队伍选择）。

    契约里必须允许「战斗中」，否则状态机转场白等 45 秒后抛错；落到战斗后还必须
    把这一局交给战斗监督 —— 少了这一步，状态会卡在 BATTLE 没人驱动。
    """

    def __init__(self):
        self.state = ExpeditionState.READY
        self.completed_cycles = 0

    def preview(self, _screen):
        return self.next_action(_screen), (self.state, self.completed_cycles)

    def next_action(self, _screen):
        if self.completed_cycles:
            return None
        return ExpeditionAction(
            "prepare-battle", (10, 20), source_state=ExpeditionState.READY,
            target_states=(ExpeditionState.TEAM, ExpeditionState.BATTLE),
            source_page="准备战斗", target_pages=("队伍选择", "战斗中"),
        )

    def is_in_state(self, _screen, _state):
        return False

    def action_source_visible(self, _screen, _action):
        return True

    def action_target_state(self, _screen, _action):
        return ExpeditionState.BATTLE

    def commit(self, _action, target):
        self.state = target
        self.completed_cycles = 1


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

    def test_prepare_battle_that_lands_on_battle_hands_off_to_supervisor(self):
        clock = Clock()
        logs = []
        machine = PrepareBattleDirectMachine()
        machine.observe_battle = MagicMock()
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = ExpeditionRunner(
            machine,
            Runtime(
                lambda: np.zeros((120, 200, 3), dtype=np.uint8),
                lambda _: None,
                emit=logs.append,
            ),
            sleep=clock.sleep,
            poll_seconds=1,
            now=clock.now,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        # 轮次号由 fake machine 的 commit 决定，不是这条用例要守的点；关键是**移交了**。
        supervisor.run.assert_called_once()
        self.assertEqual(ExpeditionState.RESULT, machine.state)
        self.assertTrue(
            any("到=战斗中" in line for line in logs),
            f"日志里没有「到=战斗中」：{logs}",
        )
        self.assertTrue(
            any("移交战斗监督" in line for line in logs),
            f"日志里没有「移交战斗监督」：{logs}",
        )

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

        with TemporaryDirectory() as directory:
            runner = ExpeditionRunner(
                machine,
                Runtime(capture, clicks.append, diagnostic_dir=Path(directory)),
                sleep=clock.sleep,
                poll_seconds=1,
                now=clock.now,
            )

            with self.assertRaisesRegex(RuntimeError, "未稳定进入"):
                runner.run(max_cycles=1)

            self.assertEqual(4, len(clicks))

    def test_failed_battle_start_never_returns_to_lobby(self):
        clock = Clock()
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
            battle_supervisor=supervisor,
        )

        with self.assertRaisesRegex(RuntimeError, "未稳定进入"):
            runner.run(max_cycles=1)

        # ⚠️ 这里原先是 `self.assertEqual([], recoveries)`（「一次恢复都没调」）。
        # 2026-09-26 起那条通道整段删除 ⇒ 只剩「抛错结束」这一个断言，
        # 而「有没有退路」由 test_story_runner 与 test_battle_safety_invariants 守。

    def test_failed_transition_clicks_four_times_then_stops(self):
        """海报页卡住 ⇒ 点 4 次就**收工**，不换别的办法、更不回大厅重来。

        ⚠️ 这里原本还有一条 ``test_failed_transition_uses_only_one_recovery_for_a_poster``
        （「同一张海报最多只恢复一次」）。2026-09-26 恢复通道整段删除 ⇒ 那条用例
        与这条完全等价，已合并进来。
        """
        clock = Clock()
        clicks = []
        machine = ActionMachine(transition=False)
        with TemporaryDirectory() as directory:
            runner = ExpeditionRunner(
                machine,
                Runtime(
                    lambda: np.zeros((60, 100, 3), dtype=np.uint8),
                    clicks.append,
                    diagnostic_dir=Path(directory),
                ),
                sleep=clock.sleep,
                poll_seconds=1,
                now=clock.now,
            )

            with self.assertRaisesRegex(RuntimeError, "未稳定进入"):
                runner.run(max_cycles=1)

            self.assertEqual(4, len(clicks))

    def test_recorded_poster_page_emits_departure_retries_without_unknown_wake(self):
        clock = Clock()
        clicks = []
        screen = cv2.cvtColor(
            cv2.imread(str(
                ROOT / "tests" / "fixtures" / "epic7_expedition" / "posters.png"
            )),
            cv2.COLOR_BGR2RGB,
        )
        machine = ExpeditionStateMachine(
            build_expedition_templates(
                ROOT / "games" / "epic7" / "templates" / "expedition"
            ),
            initial_state=ExpeditionState.POSTERS,
        )
        runner = ExpeditionRunner(
            machine,
            Runtime(lambda: screen, clicks.append),
            sleep=clock.sleep,
            poll_seconds=1,
            now=clock.now,
        )
        action = machine.next_action(screen)

        with self.assertRaisesRegex(RuntimeError, "未稳定进入"):
            runner._execute_transition(action)

        self.assertEqual("select-first-poster", action.name)
        self.assertEqual(4, len(clicks))
        self.assertEqual(ExpeditionState.POSTERS, machine.state)


if __name__ == "__main__":
    unittest.main()
