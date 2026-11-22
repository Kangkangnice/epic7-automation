from dataclasses import replace
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


def _npc_machine() -> ArenaStateMachine:
    return ArenaStateMachine(build_templates(TEMPLATES))


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


class ArenaWeeklyRewardRunnerTests(unittest.TestCase):
    """周奖励领取不换页，靠红点消失证伪；失败留诊断，不猜着连点。"""

    def test_claim_sets_the_one_shot_flag_after_red_dot_clears(self):
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        machine.weekly_reward_checked = False
        claim = Action("claim-weekly-reward", (245, 696))
        machine.preview.return_value = (claim, None)
        machine.next_action.return_value = claim
        clicks: list[tuple[int, int]] = []
        runner = ArenaRunner(
            machine,
            Runtime(
                lambda: np.full((60, 100, 3), 30, dtype=np.uint8),
                clicks.append,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )

        def claimed(action: Action) -> bool:
            machine.completed_cycles = 1
            return True

        runner._wait_until_weekly_reward_claimed = MagicMock(side_effect=claimed)

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual([(245, 696)], clicks)
        self.assertTrue(machine.weekly_reward_checked)
        runner._wait_until_weekly_reward_claimed.assert_called_once_with(claim)

    def test_waiter_requires_two_stable_frames_without_the_red_dot(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        action = Action("claim-weekly-reward", (245, 696))
        claimed = fixture("weekly_reward_claimed_live_20261117")
        screens = iter([claimed, claimed])
        runner = ArenaRunner(
            machine,
            Runtime(lambda: next(screens), lambda point: None, emit=lambda line: None),
            sleep=lambda seconds: None,
        )

        self.assertTrue(runner._wait_until_weekly_reward_claimed(action))

    def test_waiter_rejects_a_persistent_red_dot(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        action = Action("claim-weekly-reward", (245, 696))
        claimable = fixture("weekly_reward_claimable_live_20261117")
        runner = ArenaRunner(
            machine,
            Runtime(lambda: claimable, lambda point: None, emit=lambda line: None),
            sleep=lambda seconds: None,
        )
        runner._TIMEOUT_SECONDS = {**runner._TIMEOUT_SECONDS, ArenaState.LIST: 0}

        self.assertFalse(runner._wait_until_weekly_reward_claimed(action))
        self.assertFalse(machine.weekly_reward_checked)

    def test_claim_that_never_clears_stops_with_a_diagnostic(self):
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        machine.weekly_reward_checked = False
        claim = Action("claim-weekly-reward", (245, 696))
        machine.preview.return_value = (claim, None)
        machine.next_action.return_value = claim
        runtime = MagicMock()
        runtime.dry_run = False
        runtime.diagnostic_dir = Path("diagnostics")
        runtime.capture.return_value = np.full((60, 100, 3), 30, dtype=np.uint8)
        runtime.save_diagnostic.return_value = Path("claim.png")
        runner = ArenaRunner(machine, runtime, sleep=lambda seconds: None)
        runner._TIMEOUT_SECONDS = {**runner._TIMEOUT_SECONDS, ArenaState.LIST: 0}
        runner._wait_until_weekly_reward_claimed = MagicMock(return_value=False)

        with self.assertRaisesRegex(RuntimeError, "领取每周对战奖励后红点未消失"):
            runner.run(max_cycles=1)

        runtime.save_diagnostic.assert_called_once()
        self.assertFalse(machine.weekly_reward_checked)


if __name__ == "__main__":
    unittest.main()


class NpcTabTests(unittest.TestCase):
    """「交战对手」与「NPC对战」是同一页的两个页签，只差入口那一下点击。

    2026-11-16 用户口径：结算日「交战对手」页签变灰点不动，那就退回 NPC 对战；
    两者后面的选行 / 挑战 / 队伍选择 / 结算完全一样（实机逐帧核对过）。
    """

    def test_npc_tab_is_switched_back_to_challenge_first(self):
        machine = _npc_machine()
        action = machine.next_action(fixture("npc_list"))

        self.assertEqual("switch-to-challenge-tab", action.name)
        # 右菜单「交战对手」页签的落点（2026-11-16 实测 1661,228）。
        self.assertEqual((1661, 228), action.point)
        # 目标仍写列表：NPC 页也满足这条判据 ⇒ 点不动时转场照样成立，不报超时。
        self.assertEqual((ArenaState.LIST,), action.target_states)

    def test_after_the_tab_check_the_npc_page_plays_like_a_normal_list(self):
        """切不过去（结算日变灰）时，第二次问就该按 NPC 页直接选行。"""
        machine = _npc_machine()
        machine.next_action(fixture("npc_list"))
        action = machine.next_action(fixture("npc_list"))

        self.assertEqual("select-opponent", action.name)
        self.assertEqual(ArenaState.LIST, action.source_state)

    def test_a_normal_list_never_triggers_the_tab_switch(self):
        machine = _npc_machine()
        action = machine.next_action(fixture("list"))

        self.assertEqual("select-opponent", action.name)

    def test_preview_does_not_consume_the_one_shot_tab_check(self):
        machine = _npc_machine()
        machine.preview(fixture("npc_list"))

        self.assertFalse(machine._npc_tab_checked)
        self.assertEqual(
            "switch-to-challenge-tab", machine.next_action(fixture("npc_list")).name
        )

    def test_the_machine_records_which_tab_the_round_came_from(self):
        """结算行要写清打的是玩家还是 NPC（用户 2026-11-16 要求）。"""
        npc_machine = _npc_machine()
        npc_machine.next_action(fixture("npc_list"))          # 先试切页签
        npc_machine.next_action(fixture("npc_list"))          # 切不过去 ⇒ 按 NPC 页选行

        normal_machine = _npc_machine()
        normal_machine.next_action(fixture("list"))

        self.assertEqual({"npc"}, npc_machine.battle_kinds)
        self.assertEqual({"player"}, normal_machine.battle_kinds)

    def test_preview_does_not_pollute_the_battle_kinds(self):
        machine = _npc_machine()
        machine.preview(fixture("list"))

        self.assertEqual(set(), machine.battle_kinds)

    def test_choosing_npc_switches_a_player_list_over_to_the_npc_tab(self):
        """设置里选「NPC 对战」后，停在交战对手页要先点「NPC对战」页签。"""
        machine = _npc_machine()
        machine.opponent_source = "npc"
        action = machine.next_action(fixture("list"))

        self.assertEqual("switch-to-npc-tab", action.name)
        # 右菜单「NPC对战」页签的落点（2026-11-21 从 npc_list.png 实测 1661,378）。
        self.assertEqual((1661, 378), action.point)
        self.assertEqual((ArenaState.LIST,), action.target_states)

    def test_choosing_npc_leaves_an_already_npc_page_alone(self):
        machine = _npc_machine()
        machine.opponent_source = "npc"
        action = machine.next_action(fixture("npc_list"))

        self.assertEqual("select-opponent", action.name)

    def test_the_tab_alignment_is_attempted_once_per_round(self):
        """点一次切不过去就按当前页签打，不许每帧都点。"""
        machine = _npc_machine()
        machine.opponent_source = "npc"
        machine.next_action(fixture("list"))
        action = machine.next_action(fixture("list"))

        self.assertEqual("select-opponent", action.name)

    def test_the_tab_is_never_touched_after_the_list_is_left(self):
        """队伍选择页上「不在 NPC 页」恒成立，不许因此去点右菜单。

        2026-11-21 实跑：选完对手进队伍选择后又点「NPC对战」，
        画面被点乱、转场超时，整条路线失败。
        """
        for source in ("npc", "player"):
            with self.subTest(source=source):
                machine = _npc_machine()
                machine.opponent_source = source
                machine.state = ArenaState.TEAM

                action = machine.next_action(fixture("team"))

                self.assertNotEqual("switch-to-npc-tab", action.name)
                self.assertNotEqual("switch-to-challenge-tab", action.name)

    def test_missing_template_keeps_the_old_behaviour(self):
        """没采到 NPC 标题图时恒当「不在 NPC 页」，行为与旧版一致。"""
        templates = build_templates(TEMPLATES)
        without = replace(templates, npc_title=None)
        machine = ArenaStateMachine(without)

        action = machine.next_action(fixture("npc_list"))

        self.assertEqual("select-opponent", action.name)
