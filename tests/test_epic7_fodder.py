from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.core.runtime import StaminaExhausted
from auto_game_unified.games.epic7.fodder import (
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_fodder"
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "fodder"


def fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


def story_fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(STORY_FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


class FodderStateMachineTests(unittest.TestCase):
    def machine(self):
        return FodderStateMachine(build_fodder_templates(TEMPLATES))

    def test_recorded_first_cycle_has_the_expected_actions(self):
        machine = self.machine()

        actions = [
            machine.next_action(fixture("stage_3_7")),
            machine.next_action(fixture("assistant")),
            machine.next_action(fixture("team")),
            machine.next_action(fixture("clear")),
            machine.next_action(fixture("results")),
            machine.next_action(fixture("replay")),
        ]

        self.assertEqual(
            [
                "prepare_battle",
                "select_team",
                "start_battle",
                "dismiss_clear",
                "confirm_results",
                "replay",
            ],
            [action.name for action in actions],
        )
        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(FodderState.ASSISTANT, machine.state)

    def test_replay_returns_to_the_same_assistant_team_battle_chain(self):
        machine = self.machine()
        machine.state = FodderState.ASSISTANT

        actions = [
            machine.next_action(fixture("replay_assistant")),
            machine.next_action(fixture("team")),
        ]

        self.assertEqual(["select_team", "start_battle"], [item.name for item in actions])
        self.assertEqual(FodderState.BATTLE, machine.state)

    def test_preview_does_not_commit_cycle_or_state(self):
        machine = self.machine()
        machine.state = FodderState.REPLAY

        action, outcome = machine.preview(fixture("replay"))

        self.assertEqual("replay", action.name)
        self.assertEqual((FodderState.ASSISTANT, 1), outcome)
        self.assertEqual(FodderState.REPLAY, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_battle_observation_reuses_shared_auto_controls_and_result_anchor(self):
        machine = self.machine()

        battle = machine.observe_battle(fixture("battle"), None)
        clear = machine.observe_battle(fixture("clear"), fixture("battle"))

        self.assertEqual(AutoBattleState.AUTO, battle.auto_state)
        self.assertTrue(battle.battle_visible)
        self.assertFalse(battle.result_visible)
        self.assertTrue(clear.result_visible)

    def test_stamina_popup_only_selects_leaf_then_confirms(self):
        machine = self.machine()
        popup = story_fixture("stamina_popup_live_20260809")

        first = machine.next_action(popup)
        second = machine.next_action(popup)

        self.assertEqual("stamina_material", first.name)
        self.assertEqual("stamina_confirm", second.name)
        self.assertLess(first.point[0], 1000)
        self.assertGreater(second.point[0], 900)
        self.assertEqual(1, machine.stamina_replenished)

    def test_missing_leaf_offer_is_resource_exhaustion_not_a_sky_stone_click(self):
        machine = self.machine()
        popup = story_fixture("stamina_popup_live_20260809").copy()
        popup[480:720, 450:950] = 0

        with self.assertRaises(StaminaExhausted):
            machine.next_action(popup)

    def test_shared_assistant_popups_are_closed_before_the_cycle_continues(self):
        machine = self.machine()

        friendship = machine.next_action(story_fixture("friendship_points_popup"))
        friend_request = machine.next_action(story_fixture("friend_request"))

        self.assertEqual("close_friendship_points_popup", friendship.name)
        self.assertEqual("cancel_friend_request", friend_request.name)

    def test_black_and_wrong_stage_never_produce_an_action(self):
        machine = self.machine()
        black = np.zeros_like(fixture("stage_3_7"))

        with self.assertRaises(RuntimeError):
            machine.next_action(black)
        with self.assertRaises(RuntimeError):
            machine.next_action(story_fixture("stage"))


if __name__ == "__main__":
    unittest.main()
