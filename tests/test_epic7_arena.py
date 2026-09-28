from pathlib import Path
import unittest

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.arena import (
    ArenaState,
    ArenaStateMachine,
    TicketExhausted,
    build_templates,
)
from auto_game_unified.games.epic7 import arena as arena_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
GLOBAL_TEMPLATES = TEMPLATES / "global"


def load_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


def make_all_failed_screen(machine: ArenaStateMachine) -> np.ndarray:
    screen = load_fixture("failed_first_opponent").copy()
    first_x, first_y, first_width, first_height = machine._scaled_region(
        screen,
        machine._OPPONENT_STATUS_REGIONS[0],
    )
    failed = screen[
        first_y : first_y + first_height,
        first_x : first_x + first_width,
    ].copy()
    for region in machine._OPPONENT_STATUS_REGIONS[1:]:
        x, y, width, height = machine._scaled_region(screen, region)
        screen[y : y + height, x : x + width] = cv2.resize(
            failed,
            (width, height),
        )
    return screen


class Epic7ArenaStateMachineTests(unittest.TestCase):
    def test_team_page_uses_the_emulator_baseline_threshold(self):
        """竞技场结果页门槛只有模拟器基线一档（0.90）。

        以前这里还有一档「PC 专用 0.70」，那是拿模拟器图去认 PC 按钮的止痛药；
        平台差异现在由 ``templates/arena/pc/*.png`` 承担，门槛不再分平台。
        """
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        self.assertEqual(0.90, machine._THRESHOLDS["battle_start"])
        self.assertEqual(
            0.90,
            machine.templates.evidence.atom("battle_start").threshold,
        )

    def test_free_refresh_confirmation_requires_title_free_offer_and_button(self):
        screen = load_fixture("free_refresh_confirm_live_20260814")
        title = screen[335:415, 800:1140].copy()
        free_offer = screen[770:830, 970:1090].copy()
        confirm = screen[770:830, 1160:1300].copy()
        match = arena_module.find_free_refresh_confirm(
            screen, title, free_offer, confirm
        )

        self.assertIsNotNone(match)
        self.assertTrue(1160 <= match.center[0] <= 1300)
        self.assertTrue(770 <= match.center[1] <= 830)

        for region in (
            (800, 335, 340, 80),
            (970, 770, 120, 60),
            (1160, 770, 140, 60),
        ):
            without_anchor = screen.copy()
            x, y, width, height = region
            without_anchor[y : y + height, x : x + width] = 0
            self.assertIsNone(
                arena_module.find_free_refresh_confirm(
                    without_anchor, title, free_offer, confirm
                )
            )

    def test_machine_recognizes_live_free_refresh_confirmation(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        match = machine.free_refresh_confirm(
            load_fixture("free_refresh_confirm_live_20260814")
        )

        self.assertIsNotNone(match)
        self.assertTrue(1160 <= match.center[0] <= 1300)

    def test_failed_row_classifier_uses_background_color_only(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        failed = machine.opponent_availability(
            load_fixture("failed_first_opponent")
        )
        normal = machine.opponent_availability(load_fixture("list"))

        self.assertEqual((False, True, True), failed)
        self.assertEqual((True, True, True), normal)

    def test_ambiguous_row_is_not_exposed_as_a_safe_opponent(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        screen = load_fixture("list").copy()
        x, y, width, height = machine._scaled_region(
            screen,
            machine._OPPONENT_STATUS_REGIONS[1],
        )
        failed_screen = load_fixture("failed_first_opponent")
        failed_x, failed_y, failed_width, failed_height = machine._scaled_region(
            failed_screen,
            machine._OPPONENT_STATUS_REGIONS[0],
        )
        failed = failed_screen[
            failed_y : failed_y + failed_height,
            failed_x : failed_x + failed_width,
        ]
        screen[y : y + height // 4, x : x + width] = cv2.resize(
            failed,
            (width, height // 4),
        )

        availability = machine.opponent_availability(screen)

        self.assertIsNone(availability[1])

    def test_failed_first_opponent_selects_from_the_other_two(self):
        choices = []
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            choose_opponent=lambda safe: choices.append(tuple(safe)) or safe[-1],
        )
        screen = load_fixture("failed_first_opponent")

        action = machine.next_action(screen)

        self.assertEqual("select-opponent", action.name)
        self.assertEqual((1, 2), choices[0])
        self.assertEqual(machine._opponent_point(screen, 2), action.point)
        self.assertEqual(ArenaState.LIST, machine.state)
        self.assertEqual(ArenaState.LIST, action.source_state)
        self.assertEqual((ArenaState.SELECTED,), action.target_states)

        machine.commit(action, ArenaState.SELECTED)

        self.assertEqual(ArenaState.SELECTED, machine.state)

    def test_challenge_state_is_committed_only_after_target_evidence(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.SELECTED,
        )

        action = machine.next_action(load_fixture("selected"))

        self.assertEqual("challenge", action.name)
        self.assertEqual(ArenaState.SELECTED, machine.state)
        self.assertEqual(ArenaState.SELECTED, action.source_state)
        self.assertEqual((ArenaState.TEAM,), action.target_states)

        machine.commit(action, ArenaState.TEAM)

        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_selected_state_retries_same_opponent_when_list_is_still_visible(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.SELECTED,
            choose_opponent=lambda safe: self.fail("不应重新随机选择对手"),
        )
        machine._selected_opponent = 1
        screen = load_fixture("list")

        action = machine.next_action(screen)

        self.assertEqual(ArenaState.LIST, machine.state)
        self.assertEqual("select-opponent", action.name)
        self.assertEqual(ArenaState.LIST, action.source_state)
        self.assertEqual(machine._opponent_point(screen, 1), action.point)

    def test_result_and_rank_actions_do_not_advance_without_commit(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.RESULT,
        )

        result_action = machine.next_action(load_fixture("result"))

        self.assertEqual(ArenaState.RESULT, machine.state)
        self.assertEqual(
            (ArenaState.CONFIRMING, ArenaState.LIST),
            result_action.target_states,
        )

        machine.commit(result_action, ArenaState.CONFIRMING)
        rank_action = machine.next_action(load_fixture("rank_promotion_master"))

        self.assertEqual(ArenaState.CONFIRMING, machine.state)
        self.assertEqual(ArenaState.CONFIRMING, rank_action.source_state)
        self.assertEqual((ArenaState.LIST,), rank_action.target_states)

    def test_ticket_purchase_state_is_committed_only_after_team_returns(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.BATTLE,
        )

        action = machine.next_action(
            load_fixture("friendship_ticket_offer_live_20260826")
        )

        self.assertEqual(ArenaState.BATTLE, machine.state)
        self.assertEqual(ArenaState.BATTLE, action.source_state)
        self.assertEqual((ArenaState.TEAM,), action.target_states)

        machine.commit(action, ArenaState.TEAM)

        self.assertEqual(ArenaState.TEAM, machine.state)

    def test_all_failed_opponents_trigger_refresh_without_advancing_state(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        action = machine.next_action(make_all_failed_screen(machine))

        self.assertEqual("refresh-opponents", action.name)
        self.assertEqual(ArenaState.LIST, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_selected_opponent_retry_uses_the_same_row(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            choose_opponent=lambda safe: safe[1],
        )
        screen = load_fixture("list")
        first = machine.next_action(screen)

        retry = machine.next_action(screen)

        self.assertEqual("select-opponent", retry.name)
        self.assertEqual(first.point, retry.point)

    def test_challenge_commit_releases_the_row_for_the_next_cycle(self):
        choices = iter([0, 1])
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            choose_opponent=lambda safe: next(choices),
        )
        first = machine.next_action(load_fixture("list"))
        machine.commit(first, ArenaState.SELECTED)
        challenge = machine.next_action(load_fixture("selected"))
        machine.commit(challenge, ArenaState.TEAM)
        machine.state = ArenaState.LIST

        second = machine.next_action(load_fixture("list"))

        self.assertNotEqual(first.point, second.point)

    def test_confirmed_result_counts_once_before_refresh_decision(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.CONFIRMING,
        )

        action = machine.next_action(make_all_failed_screen(machine))

        self.assertEqual("refresh-opponents", action.name)
        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(ArenaState.LIST, machine.state)

    def test_battle_adapter_maps_team_manual_and_result(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.TEAM,
        )

        team = machine.observe_battle(load_fixture("team"), None)
        manual = machine.observe_battle(load_fixture("battle"), None)
        result = machine.observe_battle(load_fixture("result"), None)

        self.assertTrue(team.pre_battle_visible)
        self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
        self.assertIsNotNone(manual.auto_point)
        self.assertTrue(result.result_visible)

    def test_live_manual_battle_uses_controls_when_top_template_misses(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        screen = load_fixture("battle_manual_stuck_live_20260814")

        observation = machine.observe_battle(screen, None)

        self.assertIsNone(machine._locate(screen, "auto_off"))
        self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
        self.assertEqual(machine._AUTO_CLICK_POINT, observation.auto_point)

    def test_enemy_turn_auto_off_icon_is_manual_source_before_skills_are_available(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))
        screen = load_fixture("battle_auto_off_enemy_turn_live_20260826")

        observation = machine.observe_battle(screen, None)

        self.assertEqual(BattleControls.TRANSITION, observe_battle_controls(screen))
        self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
        self.assertEqual((1693, 93), observation.auto_point)

    def test_ticket_popup_is_returned_as_pre_battle_business(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            initial_state=ArenaState.BATTLE,
        )

        observation = machine.observe_battle(load_fixture("no_ticket"), None)

        self.assertTrue(observation.pre_battle_business_visible)
        self.assertEqual(AutoBattleState.UNKNOWN, observation.auto_state)
        self.assertIsNone(observation.auto_point)

    def test_rank_promotion_requires_arrow_and_confirm_anchor(self):
        screen = load_fixture("rank_promotion_master")
        arrow = np.asarray(
            Image.open(GLOBAL_TEMPLATES / "arena_rank_promotion_arrow.png").convert(
                "RGB"
            )
        )
        confirm = np.asarray(Image.open(TEMPLATES / "rank_confirm.png").convert("RGB"))
        without_arrow = screen.copy()
        without_arrow[760:930, 850:1130] = 0
        without_confirm = screen.copy()
        without_confirm[930:1132, 700:1220] = 0

        self.assertIsNotNone(
            arena_module.find_rank_promotion_confirm(screen, arrow, confirm)
        )
        self.assertIsNone(
            arena_module.find_rank_promotion_confirm(without_arrow, arrow, confirm)
        )
        self.assertIsNone(
            arena_module.find_rank_promotion_confirm(without_confirm, arrow, confirm)
        )

    def test_latest_rank_promotion_is_acknowledged(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES), initial_state=ArenaState.CONFIRMING
        )

        action = machine.next_action(load_fixture("rank_promotion_master"))

        self.assertEqual("confirm-rank", action.name)

    def test_confirm_button_without_rank_arrow_is_rejected(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES), initial_state=ArenaState.CONFIRMING
        )
        screen = load_fixture("rank_promotion_master").copy()
        screen[760:930, 850:1130] = 0

        with self.assertRaisesRegex(RuntimeError, "结果确认后应回到对手列表"):
            machine.next_action(screen)

    def test_current_recorded_flow_has_only_expected_actions(self):
        machine = ArenaStateMachine(
            build_templates(TEMPLATES),
            choose_opponent=lambda safe: safe[0],
        )

        observed = []
        for fixture_name, target in (
            ("list", ArenaState.SELECTED),
            ("selected", ArenaState.TEAM),
            ("team", ArenaState.BATTLE),
            ("battle", ArenaState.RESULT),
            ("result", ArenaState.CONFIRMING),
            ("result", ArenaState.CONFIRMING),
        ):
            action = machine.next_action(load_fixture(fixture_name))
            observed.append(action)
            machine.commit(action, target)
        observed.append(machine.next_action(load_fixture("list")))

        self.assertEqual(
            [
                "select-opponent",
                "challenge",
                "battle-start",
                "enable-auto",
                "confirm-result",
                "confirm-result",
                "select-opponent",
            ],
            [action.name for action in observed],
        )
        self.assertEqual((750, 406), observed[0].point)
        self.assertEqual((1747, 1045), observed[-2].point)
        self.assertEqual(1, machine.completed_cycles)

    def test_unknown_image_is_rejected_before_any_click(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        with self.assertRaisesRegex(RuntimeError, r"竞技场画面\[对手列表\]未识别"):
            machine.next_action(np.zeros((1132, 1982, 3), dtype=np.uint8))

    def test_can_resume_from_a_confirmed_team_screen(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.TEAM)

        action = machine.next_action(load_fixture("team"))

        self.assertEqual("battle-start", action.name)

    def test_rank_change_confirmation_is_acknowledged_before_returning_to_list(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.CONFIRMING)

        action = machine.next_action(load_fixture("rank_confirm"))
        follow_up = machine.next_action(load_fixture("list"))

        self.assertEqual("confirm-rank", action.name)
        self.assertEqual("select-opponent", follow_up.name)
        self.assertEqual(1, machine.completed_cycles)

    def test_committed_selected_state_returns_to_list_on_regressed_list(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.SELECTED)

        action = machine.next_action(load_fixture("list"))

        self.assertEqual(ArenaState.LIST, machine.state)
        self.assertEqual("select-opponent", action.name)

    def test_ticket_purchase_accepts_selected_friendship_offer(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)

        action = machine.next_action(load_fixture("friendship_ticket_offer_live_20260826"))

        self.assertEqual("purchase-friendship-ticket", action.name)
        self.assertIn(
            "资源=友情点 报价=100 获得旗帜=5 选择=左侧已确认",
            action.reason,
        )
        self.assertIn("报价匹配=", action.reason)
        self.assertIn("购买按钮匹配=", action.reason)

    def test_ticket_popup_suppresses_background_battle_start_action(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        observation = machine.observe_battle(
            load_fixture("friendship_ticket_offer_live_20260826"),
            None,
        )

        self.assertTrue(observation.pre_battle_business_visible)
        self.assertIsNone(observation.allowed_action)

    def test_ticket_purchase_does_not_depend_on_dynamic_friendship_balance(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)
        screen = load_fixture("friendship_ticket_offer_live_20260826").copy()
        screen[660:715, 620:920] = 0

        action = machine.next_action(screen)

        self.assertEqual("purchase-friendship-ticket", action.name)

    def test_ticket_purchase_rejects_selected_sky_stone_offer(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)

        with self.assertRaisesRegex(TicketExhausted, "100 friendship points"):
            machine.next_action(load_fixture("no_ticket"))

    def test_ticket_purchase_rejects_missing_fixed_friendship_offer_evidence(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)
        screen = load_fixture("friendship_ticket_offer_live_20260826").copy()
        screen[508:660, 568:920] = 0

        with self.assertRaises(TicketExhausted):
            machine.next_action(screen)


if __name__ == "__main__":
    unittest.main()
