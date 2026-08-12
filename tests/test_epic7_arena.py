from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
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


class Epic7ArenaStateMachineTests(unittest.TestCase):
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

        with self.assertRaisesRegex(RuntimeError, "result confirmation"):
            machine.next_action(screen)

    def test_current_recorded_flow_has_only_expected_actions(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        observed = [
            machine.next_action(load_fixture("list")),
            machine.next_action(load_fixture("selected")),
            machine.next_action(load_fixture("team")),
            machine.next_action(load_fixture("battle")),
            machine.next_action(load_fixture("result")),
            machine.next_action(load_fixture("result")),
            machine.next_action(load_fixture("list")),
        ]

        self.assertEqual(
            [
                "select-first-row",
                "challenge",
                "battle-start",
                "enable-auto",
                "confirm-result",
                "confirm-result",
                "select-first-row",
            ],
            [action.name for action in observed],
        )
        self.assertEqual((750, 406), observed[0].point)
        self.assertEqual((1747, 1045), observed[-2].point)
        self.assertEqual(1, machine.completed_cycles)

    def test_unknown_image_is_rejected_before_any_click(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES))

        with self.assertRaisesRegex(RuntimeError, "expected list"):
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
        self.assertEqual("select-first-row", follow_up.name)
        self.assertEqual(1, machine.completed_cycles)

    def test_retries_safe_row_click_when_list_is_still_visible(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.SELECTED)

        retry = machine.next_action(load_fixture("list"))
        next_action = machine.next_action(load_fixture("selected"))

        self.assertEqual("select-first-row", retry.name)
        self.assertEqual("challenge", next_action.name)

    def test_ticket_purchase_requires_title_offer_and_button(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)

        action = machine.next_action(load_fixture("no_ticket"))

        self.assertEqual("purchase-friendship-ticket", action.name)

    def test_ticket_purchase_rejects_a_non_friendship_offer(self):
        machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)
        screen = load_fixture("no_ticket").copy()
        screen[500:760, 650:1350] = 0

        with self.assertRaises(TicketExhausted):
            machine.next_action(screen)


if __name__ == "__main__":
    unittest.main()
