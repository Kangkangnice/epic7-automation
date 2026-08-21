import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from auto_game_unified import main as main_module
from auto_game_unified.core.pushplus import TOKEN_ENV
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.main import RunResult
from auto_game_unified.games.epic7.modes import get_mode


class MainStoryTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict(os.environ, {TOKEN_ENV: ""}, clear=False)
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def test_live_modes_install_one_global_popup_guard_before_navigation(self):
        for mode in ("story", "arena", "expedition", "fodder"):
            with self.subTest(mode=mode):
                runtime = unittest.mock.MagicMock()
                runner_type = unittest.mock.MagicMock()
                runner_type.return_value.run.return_value = 0
                spec = replace(get_mode(mode), runner_type=runner_type)
                events = []
                network_templates = object()
                intimacy_templates = object()
                friendship_templates = object()
                friend_request_templates = object()
                runtime.set_capture_guard.side_effect = lambda guard: events.append(
                    "guard"
                )

                with (
                    patch.object(main_module, "_build_runtime", return_value=runtime),
                    patch.object(main_module, "Epic7GlobalPopupGuard") as guard_type,
                    patch.object(
                        main_module,
                        "load_network_reconnect_templates",
                        return_value=network_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_intimacy_level_up_templates",
                        return_value=intimacy_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_friendship_points_templates",
                        return_value=friendship_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_friend_request_templates",
                        return_value=friend_request_templates,
                    ),
                    patch.object(main_module, "Epic7Navigator") as navigator_type,
                ):
                    navigator_type.return_value.return_home.side_effect = lambda: (
                        events.append("navigation") or object()
                    )
                    main_module.run_mode(
                        spec=spec,
                        dry_run=False,
                        max_cycles=1,
                        start_state=spec.default_state,
                    )

                runtime.set_capture_guard.assert_called_once_with(
                    guard_type.return_value
                )
                guard_type.assert_called_once_with(
                    network_templates,
                    intimacy_templates=intimacy_templates,
                    friendship_templates=friendship_templates,
                    friend_request_templates=friend_request_templates,
                )
                self.assertEqual(["guard", "navigation"], events)

    def test_dry_run_does_not_install_global_popup_guard(self):
        runtime = unittest.mock.MagicMock()
        runner_type = unittest.mock.MagicMock()
        runner_type.return_value.run.return_value = 0
        spec = replace(get_mode("story"), runner_type=runner_type)

        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7GlobalPopupGuard") as guard_type,
        ):
            main_module.run_mode(
                spec=spec,
                dry_run=True,
                max_cycles=1,
                start_state=spec.default_state,
            )

        runtime.set_capture_guard.assert_not_called()
        guard_type.assert_not_called()

    def test_live_run_passes_one_recovery_gate_to_the_runner(self):
        runtime = unittest.mock.MagicMock()
        runner_type = unittest.mock.MagicMock()
        runner_type.return_value.run.return_value = 0
        spec = replace(get_mode("story"), runner_type=runner_type)

        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7Navigator"),
        ):
            main_module.run_mode(
                spec=spec,
                dry_run=False,
                max_cycles=1,
                start_state="stage",
            )

        options = runner_type.call_args.kwargs
        self.assertIsInstance(options["recovery_gate"], RecoveryGate)
        self.assertEqual(options["recovery"], options["recovery_gate"].recover)

    def test_runtime_routes_only_campfire_wake_to_the_window_wake_channel(self):
        window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=window):
            runtime = main_module._build_runtime("expedition", dry_run=False)

        runtime.click((1000, 600), "wake-campfire-ui")
        runtime.click((1062, 1045), "public-recruit")

        window.wake.assert_called_once_with((1000, 600))
        window.click.assert_called_once_with((1062, 1045))

    def test_live_run_returns_home_and_navigates_before_runner(self):
        runtime = unittest.mock.MagicMock()
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

    def test_fodder_mode_dispatches_to_fodder_runner(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(0)) as run_fodder:
            exit_code = main_module.main(["--mode", "fodder", "--max-cycles", "2"])

        call = run_fodder.call_args
        self.assertEqual(0, exit_code)
        self.assertEqual("fodder", call.kwargs["spec"].name)
        self.assertTrue(call.kwargs["dry_run"])
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
        with self.assertRaisesRegex(SystemExit, "不适用于模式 story"):
            main_module.main(["--mode", "story", "--start-state", "list"])

    def test_live_run_requires_a_positive_cycle_limit(self):
        for arguments in (
            ["--mode", "story", "--live", "--confirm", "RUN"],
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "0"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(SystemExit, "--max-cycles 为正数"):
                    main_module.main(arguments)

    def test_live_run_rejects_manual_start_state(self):
        with self.assertRaisesRegex(SystemExit, "空跑诊断模式"):
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

    def test_live_success_sends_one_completion_notification(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(2)),
            patch.object(main_module, "send_pushplus") as send,
            patch.object(main_module.time, "monotonic", side_effect=[100.0, 165.0]),
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "2",
                ]
            )

        self.assertEqual(0, exit_code)
        title, content = send.call_args.args
        self.assertIn("主线已完成", title)
        self.assertIn("完成轮数：2/2", content)
        self.assertIn("耗时：65 秒", content)

    def test_live_resource_stop_sends_one_resource_notification(self):
        with (
            patch.object(
                main_module,
                "run_mode",
                return_value=RunResult(3, resource_exhausted=True),
            ),
            patch.object(main_module, "send_pushplus") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "5",
                ]
            )

        self.assertEqual(2, exit_code)
        title, content = send.call_args.args
        self.assertIn("资源不足", title)
        self.assertIn("完成轮数：3/5", content)

    def test_live_runtime_failure_sends_one_failure_notification(self):
        with (
            patch.object(
                main_module, "run_mode", side_effect=RuntimeError("unknown page")
            ),
            patch.object(main_module, "send_pushplus") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "arena",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(1, exit_code)
        title, content = send.call_args.args
        self.assertIn("竞技场运行失败", title)
        self.assertIn("unknown page", content)
        self.assertIn("runtime_diagnostics", content)

    def test_unexpected_live_exception_notifies_then_preserves_exception(self):
        with (
            patch.object(main_module, "run_mode", side_effect=ValueError("bad state")),
            patch.object(main_module, "send_pushplus") as send,
            self.assertRaisesRegex(ValueError, "bad state"),
        ):
            main_module.main(
                [
                    "--mode",
                    "fodder",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        send.assert_called_once()

    def test_manual_stop_does_not_notify(self):
        with (
            patch.object(main_module, "run_mode", side_effect=ManualStop("P")),
            patch.object(main_module, "send_pushplus") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(130, exit_code)
        send.assert_not_called()

    def test_dry_run_does_not_notify(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(1)),
            patch.object(main_module, "send_pushplus") as send,
        ):
            exit_code = main_module.main(
                ["--mode", "story", "--max-cycles", "1"]
            )

        self.assertEqual(0, exit_code)
        send.assert_not_called()

    def test_notification_bug_does_not_change_success_exit_code(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(1)),
            patch.object(
                main_module,
                "send_pushplus",
                side_effect=RuntimeError("notify bug"),
            ),
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "expedition",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(0, exit_code)


if __name__ == "__main__":
    unittest.main()
