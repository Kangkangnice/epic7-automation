from pathlib import Path
import unittest

import cv2

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7 import story as story_module
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB)


def story_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_story" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


class NavigationTests(unittest.TestCase):
    def test_classifies_friendship_points_popup(self):
        navigator = self.navigator([])

        observation = navigator.observe(story_fixture("friendship_points_popup"))

        self.assertEqual("friendship_points_popup", observation.name)

    def test_return_home_closes_friendship_points_popup_before_confirming_lobby(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [popup, popup, fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(1, len(clicks))
        self.assertTrue(870 <= clicks[0][0] <= 1050)
        self.assertTrue(885 <= clicks[0][1] <= 1010)
        self.assertEqual([], backs)

    def test_story_transition_closes_friendship_points_popup_before_destination(self):
        clicks: list[tuple[int, int]] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [popup, popup, fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby"))

        self.assertEqual(2, len(clicks))
        self.assertEqual((1790, 326), clicks[0])
        self.assertTrue(870 <= clicks[1][0] <= 1050)
        self.assertTrue(885 <= clicks[1][1] <= 1010)

    def test_wait_for_lobby_closes_friendship_points_popup(self):
        clicks: list[tuple[int, int]] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [
                popup,
                popup,
                fixture("lobby"),
                fixture("lobby"),
                fixture("story_stage"),
                fixture("story_stage"),
            ],
            clicks=clicks,
        )

        navigator.navigate("story")

        self.assertEqual(2, len(clicks))
        self.assertTrue(870 <= clicks[0][0] <= 1050)
        self.assertTrue(885 <= clicks[0][1] <= 1010)
        self.assertEqual((1790, 326), clicks[1])

    def test_classifies_arena_rank_promotion_popup(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_arena"
                    / "rank_promotion_master.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("arena_rank_promotion", navigator.observe(screen).name)

    def test_return_home_closes_arena_rank_promotion_before_confirming_lobby(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        rank_popup = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_arena"
                    / "rank_promotion_master.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )
        navigator = self.navigator(
            [rank_popup, rank_popup, fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(1, len(clicks))
        self.assertTrue(700 <= clicks[0][0] <= 1220)
        self.assertTrue(930 <= clicks[0][1] <= 1132)
        self.assertEqual([], backs)

    def navigator(self, screens, clicks=None, backs=None, logs=None):
        images = iter(screens)
        runtime = Runtime(
            lambda: next(images),
            (clicks if clicks is not None else []).append,
            back=lambda: (backs if backs is not None else []).append(True),
            emit=(logs if logs is not None else []).append,
        )
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

    def test_classifies_recorded_pages_with_required_anchors(self):
        navigator = self.navigator([])

        self.assertEqual("lobby", navigator.observe(fixture("lobby")).name)
        self.assertEqual("lobby", navigator.observe(fixture("lobby_animated_updated")).name)
        self.assertEqual("exit_dialog", navigator.observe(fixture("exit_dialog")).name)
        self.assertEqual("exit_dialog", navigator.observe(fixture("exit_dialog_updated")).name)
        self.assertEqual("story_ready", navigator.observe(fixture("story_stage")).name)
        self.assertEqual("arena_mode", navigator.observe(fixture("arena_mode")).name)
        self.assertEqual("arena_ready", navigator.observe(fixture("arena_list")).name)
        self.assertEqual(
            "battle_menu", navigator.observe(fixture("expedition_battle_menu")).name
        )
        self.assertEqual(
            "season_menu", navigator.observe(fixture("expedition_season_menu")).name
        )
        self.assertEqual(
            "expedition_home", navigator.observe(fixture("expedition_home")).name
        )

    def test_classifies_a_story_only_stage_as_story_ready(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "story_watch_ready_live_20260810.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_classifies_latest_episode4_story_page_as_story_ready(self):
        navigator = self.navigator([])

        observation = navigator.observe(fixture("story_watch_ep4"))

        self.assertEqual("story_ready", observation.name)

    def test_classifies_live_story_playback_during_startup_recovery(self):
        navigator = self.navigator([])

        observation = navigator.observe(fixture("story_playing_live_20260813"))

        self.assertEqual("story_playing", observation.name)

    def test_classifies_live_story_skip_confirmation_as_story_not_exit(self):
        navigator = self.navigator([])

        observation = navigator.observe(
            story_fixture("skip_confirm_persisted_live_20260813")
        )

        self.assertEqual("story_skip_confirm", observation.name)

    def test_return_home_finishes_story_skip_before_using_game_back(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        playing = fixture("story_playing_live_20260813")
        confirm = story_fixture("skip_confirm_persisted_live_20260813")
        navigator = self.navigator(
            [
                playing,
                playing,
                confirm,
                confirm,
                fixture("story_stage"),
                fixture("story_stage"),
                fixture("lobby"),
                fixture("lobby"),
            ],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(3, len(clicks))
        self.assertGreater(clicks[0][0], 1700)
        self.assertGreater(clicks[1][0], 850)
        self.assertLess(clicks[2][0], 120)
        self.assertEqual([], backs)

    def test_story_navigation_confirms_latest_episode4_destination(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("story_watch_ep4")] * 12,
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby"))

        self.assertEqual([(1790, 326)], clicks)

    def test_navigation_uses_the_shared_story_watch_score(self):
        navigator = self.navigator([])
        screen = fixture("story_watch_ep4")

        shared = story_module.find_watch_story_button(
            screen, navigator.templates.story_watch
        )
        observation = navigator.observe(screen)

        self.assertIsNotNone(shared)
        self.assertAlmostEqual(shared.score, observation.confidence, places=6)

    def test_classifies_the_updated_battle_stage_as_story_ready(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "stage_battle_ready_updated.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_classifies_episode5_prepare_battle_without_background(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "stage_prepare_battle_ep5.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_lobby_classification_does_not_depend_on_dynamic_profile_progress(self):
        navigator = self.navigator([])
        lobby = fixture("lobby").copy()
        lobby[35:200, 0:500] = 0

        self.assertEqual("lobby", navigator.observe(lobby).name)

    def test_return_home_cancels_visible_exit_dialog_after_two_frames(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("exit_dialog"), fixture("exit_dialog"), fixture("lobby"), fixture("lobby")],
            clicks=clicks,
        )

        navigator.return_home()

        self.assertEqual([(800, 740)], clicks)

    def test_return_home_cancels_updated_exit_dialog_after_two_frames(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("exit_dialog_updated"),
                fixture("exit_dialog_updated"),
                fixture("lobby"),
                fixture("lobby"),
            ],
            clicks=clicks,
        )

        navigator.return_home()

        self.assertEqual([(798, 741)], clicks)

    def test_cancelled_exit_dialog_waits_for_lobby_without_another_back(self):
        backs: list[bool] = []
        unknown = fixture("story_stage").copy()
        unknown[930:1132, 1450:1920] = 0
        navigator = self.navigator(
            [
                fixture("exit_dialog_updated"),
                fixture("exit_dialog_updated"),
                unknown,
                unknown,
                fixture("lobby"),
                fixture("lobby"),
            ],
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual([], backs)

    def test_unknown_page_uses_controlled_back_then_confirms_lobby(self):
        backs: list[bool] = []
        unknown = fixture("story_stage").copy()
        # Remove the known stage button so this remains a valid but unknown game frame.
        unknown[930:1132, 1450:1920] = 0
        navigator = self.navigator(
            [unknown, unknown, fixture("lobby"), fixture("lobby")],
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual([True], backs)

    def test_story_ready_uses_the_visible_game_back_button(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        navigator = self.navigator(
            [
                fixture("story_stage"), fixture("story_stage"),
                fixture("lobby"), fixture("lobby"),
            ],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual([(57, 97)], clicks)
        self.assertEqual([], backs)

    def test_delayed_story_back_transition_does_not_repeat_the_click(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        navigator = self.navigator(
            [fixture("story_stage")] * 8 + [fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual([(57, 97)], clicks)
        self.assertEqual([], backs)

    def test_story_navigation_confirms_destination_before_returning(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("lobby"), fixture("lobby"), fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story")

        self.assertEqual([(1790, 326)], clicks)

    def test_story_navigation_accepts_the_animated_updated_lobby_anchor(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby_animated_updated"))

        self.assertEqual(1, len(clicks))

    def test_arena_navigation_uses_mode_selection_page(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("arena_mode"), fixture("arena_mode"),
                fixture("arena_list"), fixture("arena_list"),
            ],
            clicks=clicks,
        )

        navigator.navigate("arena")

        self.assertEqual([(1795, 635), (710, 995)], clicks)

    def test_expedition_navigation_uses_verified_three_step_route(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("expedition_battle_menu"), fixture("expedition_battle_menu"),
                fixture("expedition_season_menu"), fixture("expedition_season_menu"),
                fixture("expedition_home"), fixture("expedition_home"),
            ],
            clicks=clicks,
        )

        navigator.navigate("expedition")

        self.assertEqual([(1827, 531), (465, 220), (1080, 357)], clicks)

    def test_expedition_navigation_accepts_remembered_season_tab(self):
        clicks: list[tuple[int, int]] = []

        def capture():
            if len(clicks) == 1:
                return fixture("expedition_season_menu")
            return fixture("expedition_home")

        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(capture, clicks.append),
            sleep=lambda _: None,
            transition_frames=12,
        )

        error = None
        try:
            navigator.navigate("expedition", lobby_screen=fixture("lobby"))
        except RuntimeError as caught:
            error = caught

        self.assertIsNone(error)
        self.assertEqual([(1827, 531), (1080, 357)], clicks)

    def test_black_frames_never_trigger_click_or_back(self):
        import numpy as np

        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        navigator = self.navigator([np.zeros((1132, 1982, 3), dtype=np.uint8)] * 12, clicks, backs)

        with self.assertRaisesRegex(RuntimeError, "black or non-game"):
            navigator.return_home()

        self.assertEqual([], clicks)
        self.assertEqual([], backs)


if __name__ == "__main__":
    unittest.main()
