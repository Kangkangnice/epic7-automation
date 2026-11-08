from pathlib import Path
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    Action,
    ArenaOutcome,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class ArenaRunnerTests(unittest.TestCase):
    def test_challenge_retries_same_click_when_selected_source_remains(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.SELECTED,
        )
        action = machine.next_action(fixture("selected"))
        screens = iter(
            [fixture("selected"), fixture("selected"), fixture("team"), fixture("team")]
        )
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        runner._execute_transition(action)

        self.assertEqual([action.point, action.point], clicks)
        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_challenge_does_not_reclick_after_selected_source_disappears(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.SELECTED,
        )
        action = machine.next_action(fixture("selected"))
        loading = np.zeros_like(fixture("selected"))
        screens = iter([loading, loading, fixture("team"), fixture("team")])
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        runner._execute_transition(action)

        self.assertEqual([action.point], clicks)
        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_challenge_requires_two_consecutive_target_frames_before_commit(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.SELECTED,
        )
        action = machine.next_action(fixture("selected"))
        loading = np.zeros_like(fixture("selected"))
        screens = iter(
            [fixture("team"), loading, fixture("team"), fixture("team")]
        )
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), lambda point: None, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        runner._execute_transition(action)

        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_result_confirmation_retries_and_counts_after_stable_list(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.RESULT,
        )
        action = machine.next_action(fixture("result"))
        screens = iter(
            [fixture("result"), fixture("result"), fixture("list"), fixture("list")]
        )
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        runner._execute_transition(action)

        self.assertEqual([action.point, action.point], clicks)
        self.assertEqual(ArenaState.LIST, machine.state)
        self.assertEqual(1, machine.completed_cycles)

    def test_ticket_purchase_retries_only_while_purchase_popup_remains(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.BATTLE,
        )
        action = machine.next_action(fixture("friendship_ticket_offer_live_20260826"))
        screens = iter(
            [
                fixture("friendship_ticket_offer_live_20260826"),
                fixture("friendship_ticket_offer_live_20260826"),
                fixture("team"),
                fixture("team"),
            ]
        )
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        runner._execute_transition(action)

        self.assertEqual([action.point, action.point], clicks)
        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_refresh_retries_initial_click_and_requires_stable_safe_list(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        failed = fixture("failed_first_opponent").copy()
        first_x, first_y, first_width, first_height = machine._scaled_region(
            failed,
            machine._OPPONENT_STATUS_REGIONS[0],
        )
        failed_row = failed[
            first_y : first_y + first_height,
            first_x : first_x + first_width,
        ].copy()
        for region in machine._OPPONENT_STATUS_REGIONS[1:]:
            x, y, width, height = machine._scaled_region(failed, region)
            failed[y : y + height, x : x + width] = cv2.resize(
                failed_row,
                (width, height),
            )
        action = machine.next_action(failed)
        screens = iter([failed, failed, fixture("list"), fixture("list")])
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )
        runner.runtime.click(action.point, action.name)

        self.assertTrue(runner._wait_until_safe_list(action))
        self.assertEqual([action.point, action.point], clicks)

    def test_committed_battle_returns_control_to_result_state(self):
        machine = MagicMock()
        machine.state = ArenaState.BATTLE
        # 结算页的胜负判读是这一趟的副作用（见 ArenaRunner._record_outcome）；
        # 本用例只关心状态回到 RESULT，所以给替身一个明确的「认不出」。
        machine.observe_outcome.return_value = ArenaOutcome.UNKNOWN
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
        visual_state = "list"
        clicks: list[tuple[int, int]] = []

        def capture():
            return fixture(visual_state)

        def click(point):
            nonlocal visual_state
            clicks.append(point)
            visual_state = {
                (750, 406): "selected",
                (960, 1045): "team",
                (1257, 1040): "battle",
                (1692, 90): "result",
                (1747, 1045): "list",
            }.get(point, visual_state)

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

        def refreshed(action: Action) -> bool:
            machine.completed_cycles = 1
            return True

        runner._wait_until_safe_list = MagicMock(side_effect=refreshed)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual([(1344, 225)], clicks)
        runner._wait_until_safe_list.assert_called_once_with(refresh)
        self.assertEqual(ArenaState.LIST, machine.state)

    def test_safe_list_waiter_requires_both_list_and_available_opponent(self):
        machine = MagicMock()
        machine.is_in_state.return_value = True
        machine.has_safe_opponent.side_effect = [False, True, True]
        machine.free_refresh_confirm.return_value = None
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
        self.assertEqual(3, machine.has_safe_opponent.call_count)

    def test_safe_list_waiter_confirms_free_refresh_then_accepts_new_list(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        confirmation = fixture("free_refresh_confirm_live_20260814")
        screens = iter([confirmation, confirmation, fixture("list"), fixture("list")])
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

    def test_safe_list_waiter_rejects_list_hidden_under_free_refresh_popup(self):
        """弹窗在场时不许判「刷新成功」—— 半透明遮罩会让红色状态判据反转。

        2026-11-07 07:55 的事故链：点刷新 → 弹「更新交战对手」→ 遮罩把三名
        「不可挑战」对手的红色压掉（实测占比 0.0000/0.0000/0.0387，阈值 ≤0.05
        即判可挑战）→ ``has_safe_opponent`` 返回 True → 3 秒内判「含安全对手的
        列表」→ 去点对手（点在弹窗上无效）→ 重试 4 次后记 ✗。
        """
        machine = ArenaStateMachine(
            build_templates(TemplateDir(TEMPLATES, "pc")), pc_rules=True
        )
        frame = fixture("free_refresh_confirm_pc_live_20261107")

        # 前提：这一帧上「裸判」会成立 —— 正是事故根因，不是测试假设错了。
        self.assertTrue(machine.has_safe_opponent(frame))
        self.assertIsNotNone(machine.free_refresh_confirm(frame))

        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(lambda: frame, clicks.append, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        self.assertFalse(runner._wait_until_safe_list())
        # 点的是弹窗「确认」，不是对手行；最多 4 次后放弃（与既有预算一致）。
        self.assertEqual(4, len(clicks))
        for point in clicks:
            self.assertTrue(1150 <= point[0] <= 1310)
            self.assertTrue(760 <= point[1] <= 840)

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
