import unittest
from unittest.mock import patch

from auto_game_unified import main as main_module
from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.main import RunResult
from auto_game_unified.games.epic7.modes import get_mode


class MainStoryTests(unittest.TestCase):
    def test_live_run_returns_home_and_navigates_before_runner(self):
        runtime = object()
        lobby = object()
        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7Navigator") as navigator_type,
            patch("auto_game_unified.games.epic7.story.StoryRunner.run", return_value=1),
        ):
            navigator_type.return_value.return_home.return_value = lobby
            result = main_module.run_mode(
                spec=get_mode("story"), dry_run=False, max_cycles=1, start_state="stage"
            )

        self.assertEqual(1, result.completed_cycles)
        navigator_type.return_value.return_home.assert_called_once_with()
        navigator_type.return_value.navigate.assert_called_once_with("story", lobby_screen=lobby)

    def test_story_mode_dispatches_to_story_runner(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(0)) as run_story:
            exit_code = main_module.main(["--mode", "story", "--max-cycles", "2"])

        call = run_story.call_args
        self.assertEqual(0, exit_code)
        self.assertEqual("story", call.kwargs["spec"].name)
        self.assertEqual(True, call.kwargs["dry_run"])
        self.assertEqual(2, call.kwargs["max_cycles"])
        self.assertEqual("stage", call.kwargs["start_state"])

    def test_expedition_has_no_difficulty_command_line_option(self):
        with self.assertRaises(SystemExit):
            main_module.parse_args(
                ["--mode", "expedition", "--difficulty", "2"]
            )

    def test_expedition_parser_does_not_expose_a_difficulty_value(self):
        args = main_module.parse_args(["--mode", "expedition"])

        self.assertFalse(hasattr(args, "difficulty"))

    def test_story_rejects_an_arena_resume_state(self):
        with self.assertRaisesRegex(SystemExit, "not valid for story"):
            main_module.main(["--mode", "story", "--start-state", "list"])

    def test_live_run_requires_a_positive_cycle_limit(self):
        for arguments in (
            ["--mode", "story", "--live", "--confirm", "RUN"],
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "0"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(SystemExit, "positive --max-cycles"):
                    main_module.main(arguments)

    def test_live_run_rejects_manual_start_state(self):
        with self.assertRaisesRegex(SystemExit, "dry-run diagnostics"):
            main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                    "--start-state",
                    "active",
                ]
            )

    def test_resource_stop_returns_exit_code_two(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(3, resource_exhausted=True)):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "5"]
            )

        self.assertEqual(2, exit_code)

    def test_runtime_failure_returns_exit_code_one(self):
        with patch.object(main_module, "run_mode", side_effect=RuntimeError("unknown page")):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "1"]
            )

        self.assertEqual(1, exit_code)

    def test_manual_p_stop_returns_exit_code_130(self):
        with patch.object(main_module, "run_mode", side_effect=ManualStop("P")):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "1"]
            )

        self.assertEqual(130, exit_code)


if __name__ == "__main__":
    unittest.main()
