import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.games.epic7.expedition import (
    ExpeditionAction,
    ExpeditionState,
    ExpeditionStateMachine,
    ExpeditionTemplates,
    PostersExhausted,
    build_expedition_templates,
)


SIZE = (1132, 1982, 3)
ROOT = Path(__file__).resolve().parents[1]


def pattern(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (24, 48, 3), dtype=np.uint8)


TEMPLATES = ExpeditionTemplates(
    home=pattern(1),
    poster_embark=pattern(2),
    empty_posters=pattern(3),
    difficulty_title=pattern(4),
    difficulty_3_selected=pattern(5),
    difficulty_confirm=pattern(6),
    prepare_battle=pattern(7),
    battle_start=pattern(8),
    auto_off=pattern(19),
    battle_anchor=pattern(9),
    result_confirm=pattern(10),
    victory_title=pattern(20),
    victory_close=pattern(21),
    defeated_confirm=pattern(11),
    public_recruit=pattern(12),
    public_title=pattern(13),
    public_confirm=pattern(14),
    public_recruited=pattern(15),
    campfire_idle=pattern(16),
    expedition_list=pattern(17),
    back=pattern(18),
)


def screen_with(*items: tuple[np.ndarray, tuple[int, int]]) -> np.ndarray:
    screen = np.zeros(SIZE, dtype=np.uint8)
    for template, (x, y) in items:
        height, width = template.shape[:2]
        screen[y : y + height, x : x + width] = template
    return screen


def recorded_screen(name: str) -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / "epic7_expedition" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


class ExpeditionStateMachineTests(unittest.TestCase):
    def machine(self, state=ExpeditionState.HOME):
        return ExpeditionStateMachine(
            TEMPLATES,
            initial_state=state,
        )

    def test_battle_adapter_maps_team_manual_and_result(self):
        machine = ExpeditionStateMachine(
            build_expedition_templates(
                ROOT / "games" / "epic7" / "templates" / "expedition"
            ),
            initial_state=ExpeditionState.TEAM,
        )

        team = machine.observe_battle(recorded_screen("team"), None)
        manual = machine.observe_battle(
            recorded_screen("battle_manual_waiting_live"), None
        )
        result = machine.observe_battle(recorded_screen("result"), None)

        self.assertTrue(team.pre_battle_visible)
        self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
        self.assertIsNotNone(manual.auto_point)
        self.assertTrue(result.result_visible)

    def test_battle_adapter_treats_dynamic_valid_frames_as_progress_without_hud(self):
        machine = self.machine(ExpeditionState.BATTLE)
        before = np.random.default_rng(1).integers(
            0, 256, SIZE, dtype=np.uint8
        )
        after = np.random.default_rng(2).integers(
            0, 256, SIZE, dtype=np.uint8
        )

        observation = machine.observe_battle(after, before)

        self.assertTrue(observation.battle_visible)
        self.assertTrue(observation.business_progress)
        self.assertEqual(AutoBattleState.AUTO, observation.auto_state)

    def test_home_opens_my_wanted_posters(self):
        machine = self.machine()

        action = machine.next_action(screen_with((TEMPLATES.home, (1600, 980))))

        self.assertEqual("open-my-posters", action.name)
        self.assertEqual(ExpeditionState.POSTERS, machine.state)

    def test_poster_list_selects_first_card_button_top_to_bottom(self):
        machine = self.machine(ExpeditionState.POSTERS)
        screen = screen_with(
            (TEMPLATES.poster_embark, (1050, 620)),
            (TEMPLATES.poster_embark, (1050, 280)),
        )

        action = machine.next_action(screen)

        self.assertEqual("select-first-poster", action.name)
        self.assertEqual((1074, 292), action.point)

    def test_bottom_right_global_embark_is_never_a_poster(self):
        machine = self.machine(ExpeditionState.POSTERS)
        screen = screen_with((TEMPLATES.poster_embark, (1760, 1010)))

        with self.assertRaisesRegex(RuntimeError, "card area"):
            machine.next_action(screen)

    def test_empty_poster_list_is_resource_exhaustion(self):
        machine = self.machine(ExpeditionState.POSTERS)

        with self.assertRaises(PostersExhausted):
            machine.next_action(screen_with((TEMPLATES.empty_posters, (850, 480))))

    def test_difficulty_is_fixed_to_stage_three_then_confirmed(self):
        machine = self.machine(ExpeditionState.DIFFICULTY)
        screen = screen_with((TEMPLATES.difficulty_title, (800, 210)))

        action = machine.next_action(screen)

        self.assertEqual("select-difficulty-3", action.name)
        self.assertEqual(ExpeditionState.DIFFICULTY_CONFIRM, machine.state)

        confirm = machine.next_action(
            screen_with(
                (TEMPLATES.difficulty_3_selected, (1060, 690)),
                (TEMPLATES.difficulty_confirm, (980, 900)),
            )
        )
        self.assertEqual("confirm-difficulty-3", confirm.name)
        self.assertEqual(ExpeditionState.READY, machine.state)

    def test_one_public_recruit_cycle_counts_only_after_return_home(self):
        machine = self.machine(ExpeditionState.READY)

        self.assertEqual(
            "prepare-battle",
            machine.next_action(screen_with((TEMPLATES.prepare_battle, (1650, 980)))).name,
        )
        self.assertEqual(
            "battle-start",
            machine.next_action(screen_with((TEMPLATES.battle_start, (1400, 980)))).name,
        )
        self.assertIsNone(
            machine.next_action(screen_with((TEMPLATES.battle_anchor, (1650, 100))))
        )
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual(
            "confirm-result",
            machine.next_action(screen_with((TEMPLATES.result_confirm, (1700, 980)))).name,
        )
        self.assertEqual(
            "public-recruit",
            machine.next_action(screen_with((TEMPLATES.public_recruit, (900, 980)))).name,
        )
        self.assertEqual(
            "confirm-public-recruit",
            machine.next_action(
                screen_with(
                    (TEMPLATES.public_title, (850, 350)),
                    (TEMPLATES.public_confirm, (930, 800)),
                )
            ).name,
        )
        self.assertEqual(
            "return-from-expedition",
            machine.next_action(
                screen_with(
                    (TEMPLATES.public_recruited, (950, 1000)),
                    (TEMPLATES.back, (45, 70)),
                )
            ).name,
        )
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual(
            "return-to-expedition-home",
            machine.next_action(
                screen_with(
                    (TEMPLATES.expedition_list, (1250, 180)),
                    (TEMPLATES.back, (45, 70)),
                )
            ).name,
        )
        self.assertEqual(0, machine.completed_cycles)

        self.assertIsNone(machine.next_action(screen_with((TEMPLATES.home, (1600, 980)))))
        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(ExpeditionState.HOME, machine.state)

    def test_defeated_popup_skips_public_recruitment(self):
        machine = self.machine(ExpeditionState.OUTCOME)

        action = machine.next_action(
            screen_with((TEMPLATES.defeated_confirm, (930, 850)))
        )

        self.assertEqual("confirm-defeated", action.name)
        self.assertEqual(ExpeditionState.RETURNING, machine.state)

    def test_campfire_idle_is_woken_without_advancing_outcome_state(self):
        machine = self.machine(ExpeditionState.OUTCOME)

        action = machine.next_action(
            screen_with((TEMPLATES.campfire_idle, (800, 150)))
        )

        self.assertEqual("wake-campfire-ui", action.name)
        self.assertEqual((1000, 600), action.point)
        self.assertEqual(ExpeditionState.OUTCOME, machine.state)
        self.assertTrue(machine.is_in_state(
            screen_with((TEMPLATES.campfire_idle, (800, 150))),
            ExpeditionState.OUTCOME,
        ))

    def test_campfire_idle_is_woken_before_returning_from_recruitment(self):
        machine = self.machine(ExpeditionState.RECRUIT_RETURN)

        action = machine.next_action(
            screen_with((TEMPLATES.campfire_idle, (800, 150)))
        )

        self.assertEqual("wake-campfire-ui", action.name)
        self.assertEqual((1000, 600), action.point)
        self.assertEqual(ExpeditionState.RECRUIT_RETURN, machine.state)
        self.assertTrue(machine.is_in_state(
            screen_with((TEMPLATES.campfire_idle, (800, 150))),
            ExpeditionState.RECRUIT_RETURN,
        ))

    def test_defeated_popup_can_interrupt_public_confirmation(self):
        machine = self.machine(ExpeditionState.RECRUIT_CONFIRM)

        action = machine.next_action(
            screen_with((TEMPLATES.defeated_confirm, (930, 850)))
        )

        self.assertEqual("confirm-defeated", action.name)
        self.assertEqual(ExpeditionState.RETURNING, machine.state)

    def test_preview_does_not_mutate_state_or_count(self):
        machine = self.machine()

        action, outcome = machine.preview(screen_with((TEMPLATES.home, (1600, 980))))

        self.assertEqual("open-my-posters", action.name)
        self.assertEqual((ExpeditionState.POSTERS, 0), outcome)
        self.assertEqual(ExpeditionState.HOME, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_current_templates_load_without_uncaptured_optional_branches(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )

        self.assertIsNone(templates.empty_posters)
        self.assertIsNone(templates.defeated_confirm)

    def test_home_recognition_ignores_changed_wanted_poster_badge(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.RETURNING
        )
        path = (
            ROOT
            / "tests"
            / "fixtures"
            / "epic7_expedition"
            / "home_changed_badge.png"
        )
        screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)

        self.assertIsNone(machine.next_action(screen))
        self.assertEqual(1, machine.completed_cycles)

    def test_recorded_current_client_pages_match_their_states(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(templates)

        cases = (
            ("home", ExpeditionState.HOME),
            ("posters", ExpeditionState.POSTERS),
            ("difficulty_3_selected", ExpeditionState.DIFFICULTY_CONFIRM),
            ("ready", ExpeditionState.READY),
            ("team", ExpeditionState.TEAM),
            ("battle", ExpeditionState.BATTLE),
            ("result", ExpeditionState.RESULT),
            ("outcome_public", ExpeditionState.OUTCOME),
            ("public_confirm", ExpeditionState.RECRUIT_CONFIRM),
            ("recruited", ExpeditionState.RECRUIT_RETURN),
            ("expedition_list", ExpeditionState.RETURNING),
        )
        for fixture_name, state in cases:
            with self.subTest(fixture=fixture_name, state=state):
                self.assertTrue(machine.is_in_state(recorded_screen(fixture_name), state))

    def test_recorded_campfire_idle_produces_only_the_safe_wake_click(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.RECRUIT_RETURN
        )

        action = machine.next_action(recorded_screen("campfire_idle"))

        self.assertEqual(ExpeditionAction("wake-campfire-ui", (1000, 600)), action)

    def test_current_highlighted_public_recruit_button_is_recognized(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.OUTCOME
        )

        action = machine.next_action(recorded_screen("outcome_public_highlighted"))

        self.assertEqual("public-recruit", action.name)
        self.assertEqual(ExpeditionState.RECRUIT_CONFIRM, machine.state)

    def test_manual_expedition_battle_enables_auto_once(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.BATTLE
        )

        action = machine.next_action(recorded_screen("battle_manual_waiting_live"))

        self.assertEqual("enable-auto-battle", action.name)
        self.assertTrue(1660 <= action.point[0] <= 1720)
        self.assertTrue(70 <= action.point[1] <= 125)
        self.assertIsNone(
            machine.next_action(recorded_screen("battle_manual_waiting_live"))
        )

    def test_preview_does_not_consume_auto_battle_click(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.BATTLE
        )
        screen = recorded_screen("battle_manual_waiting_live")

        preview, _ = machine.preview(screen)
        action = machine.next_action(screen)

        self.assertEqual("enable-auto-battle", preview.name)
        self.assertEqual("enable-auto-battle", action.name)

    def test_victory_popup_skips_public_recruitment(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.OUTCOME
        )

        action = machine.next_action(recorded_screen("victory_popup_live"))

        self.assertEqual("close-expedition-victory", action.name)
        self.assertEqual(ExpeditionState.RETURNING, machine.state)


if __name__ == "__main__":
    unittest.main()
