import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from auto_game_unified.core import pc_window
from auto_game_unified.core.pc_window import Epic7PcWindow, WindowRect


class PcWindowSafetyTests(unittest.TestCase):
    def setUp(self):
        self.game = Epic7PcWindow()

    def test_activate_rejects_a_window_that_does_not_become_foreground(self):
        self.game._user32 = MagicMock()
        self.game._user32.GetForegroundWindow.return_value = 999

        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch("auto_game_unified.core.pc_window.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "未能置前"):
                self.game.activate()

    def test_ensure_render_size_skips_activation_when_client_is_already_exact(self):
        exact = WindowRect(10, 20, 1920, 1080)
        self.game._user32 = MagicMock()
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "activate") as activate,
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_rect", return_value=exact),
        ):
            result = self.game.ensure_render_size()

        self.assertEqual(pc_window.WindowCalibration(exact, exact, False), result)
        activate.assert_not_called()
        self.game._user32.SetWindowPos.assert_not_called()

    def test_ensure_render_size_resizes_outer_window_and_verifies_client(self):
        before = WindowRect(152, 294, 1280, 720)
        after = WindowRect(152, 294, 1920, 1080)
        outer = WindowRect(139, 236, 1306, 791)
        self.game._user32 = MagicMock()
        self.game._user32.SetWindowPos.return_value = 1
        self.game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "activate", return_value=123) as activate,
            patch.object(
                self.game, "_restore_foreground", return_value=True
            ) as restore,
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_rect", side_effect=[before, after]),
            patch.object(self.game, "_outer_rect", return_value=outer, create=True),
            patch("auto_game_unified.core.pc_window.sleep"),
        ):
            result = self.game.ensure_render_size()

        self.assertEqual(pc_window.WindowCalibration(before, after, True), result)
        activate.assert_called_once_with()
        restore.assert_called_once_with(999, 123)
        self.game._user32.SetWindowPos.assert_called_once_with(
            123, 0, 139, 236, 1946, 1151, 0x0014
        )

    def test_ensure_render_size_stops_when_resize_does_not_reach_target(self):
        before = WindowRect(152, 294, 1280, 720)
        self.game._user32 = MagicMock()
        self.game._user32.SetWindowPos.return_value = 1
        self.game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "activate", return_value=123) as activate,
            patch.object(
                self.game, "_restore_foreground", return_value=True
            ) as restore,
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_rect", side_effect=[before] * 12),
            patch.object(
                self.game,
                "_outer_rect",
                return_value=WindowRect(139, 236, 1306, 791),
                create=True,
            ),
            patch("auto_game_unified.core.pc_window.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "调整后实际仍为 1280x720"):
                self.game.ensure_render_size()
        activate.assert_called_once_with()
        restore.assert_called_once_with(999, 123)

    def test_ensure_render_size_reports_win32_error_when_resize_is_denied(self):
        before = WindowRect(152, 294, 1280, 720)
        self.game._user32 = MagicMock()
        self.game._user32.SetWindowPos.return_value = 0
        self.game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "activate", return_value=123) as activate,
            patch.object(
                self.game, "_restore_foreground", return_value=True
            ) as restore,
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_rect", return_value=before),
            patch.object(
                self.game,
                "_outer_rect",
                return_value=WindowRect(139, 236, 1306, 791),
                create=True,
            ),
            patch("auto_game_unified.core.pc_window.ctypes.get_last_error", return_value=5),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "当前=1280x720.*目标=1920x1080.*Win32错误码=5",
            ):
                self.game.ensure_render_size()
        activate.assert_called_once_with()
        restore.assert_called_once_with(999, 123)

    def test_click_does_not_send_desktop_input_when_foreground_confirmation_fails(self):
        with (
            patch.object(
                self.game,
                "activate",
                side_effect=RuntimeError("PC 游戏窗口未能置前"),
            ),
            patch.object(
                self.game,
                "_rect",
                return_value=WindowRect(10, 20, 1982, 1132),
            ),
            patch("auto_game_unified.core.pc_window.pyautogui.click") as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "未能置前"):
                self.game.click((991, 566))

        click.assert_not_called()

    def test_click_rejects_when_game_is_elevated_but_automation_is_not(self):
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(
                self.game,
                "_ensure_input_allowed",
                side_effect=RuntimeError("客户端以管理员权限运行"),
            ),
            patch("auto_game_unified.core.pc_window.pyautogui.click") as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "管理员权限"):
                self.game.click((991, 566))

        click.assert_not_called()

    def test_capture_places_1920x1080_pixels_on_legacy_canvas_without_resizing(self):
        source = np.arange(1080 * 1920 * 3, dtype=np.uint8).reshape(
            1080, 1920, 3
        )
        canvas = self.game._legacy_canvas(source)

        self.assertEqual((1132, 1982, 3), canvas.shape)
        np.testing.assert_array_equal(source, canvas[52:, :1920])
        self.assertFalse(canvas[:52].any())
        self.assertFalse(canvas[:, 1920:].any())

    def test_capture_uses_background_bitblt_without_activation(self):
        source = np.full((1080, 1920, 3), 127, dtype=np.uint8)
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(
                self.game,
                "_capture_client_bitblt",
                return_value=source,
                create=True,
            ),
            patch.object(self.game, "activate") as activate,
            patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
        ):
            canvas = self.game.capture()

        activate.assert_not_called()
        screenshot.assert_not_called()
        np.testing.assert_array_equal(source, canvas[52:, :1920])

    def test_capture_stops_without_activation_when_bitblt_fails(self):
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(
                self.game,
                "_capture_client_bitblt",
                return_value=None,
                create=True,
            ) as bitblt,
            patch.object(self.game, "activate") as activate,
            patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
        ):
            with self.assertRaisesRegex(RuntimeError, "PC 后台截图失败"):
                self.game.capture()

        bitblt.assert_called_once_with(123)
        activate.assert_not_called()
        screenshot.assert_not_called()

    def test_click_subtracts_legacy_top_padding_before_sending_input(self):
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(
                self.game,
                "_ensure_input_allowed",
            ),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(self.game, "_send_click", create=True) as click,
        ):
            self.game.click((991, 566))

        click.assert_called_once_with((1001, 534))

    def test_click_restores_the_previous_foreground_window_after_input(self):
        calls = []
        self.game._user32 = MagicMock()
        self.game._user32.GetForegroundWindow.return_value = 999
        self.game._user32.IsWindow.return_value = 1
        self.game._user32.SetForegroundWindow.side_effect = (
            lambda hwnd: calls.append(("restore", hwnd)) or 1
        )
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(
                self.game,
                "_send_click",
                side_effect=lambda point: calls.append(("click", point)),
            ),
        ):
            self.game.click((991, 566))

        self.assertEqual([("click", (1001, 534)), ("restore", 999)], calls)

    def test_click_logs_successful_focus_restore(self):
        events = []
        game = Epic7PcWindow(event_sink=events.append)
        game._user32 = MagicMock()
        game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(game, "_find_window", return_value=123),
            patch.object(game, "activate", return_value=123),
            patch.object(game, "_ensure_input_allowed"),
            patch.object(
                game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(game, "_send_click"),
            patch.object(game, "_restore_foreground", return_value=True),
        ):
            game.click((991, 566))

        self.assertIn("类型=点击", events[-1])
        self.assertIn("前置=成功", events[-1])
        self.assertIn("恢复原窗口=成功", events[-1])

    def test_click_logs_failed_focus_restore(self):
        events = []
        game = Epic7PcWindow(event_sink=events.append)
        game._user32 = MagicMock()
        game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(game, "_find_window", return_value=123),
            patch.object(game, "activate", return_value=123),
            patch.object(game, "_ensure_input_allowed"),
            patch.object(
                game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(game, "_send_click"),
            patch.object(game, "_restore_foreground", return_value=False),
        ):
            game.click((991, 566))

        self.assertIn("类型=点击", events[-1])
        self.assertIn("恢复原窗口=失败", events[-1])

    def test_restore_foreground_reports_failure_when_focus_does_not_return(self):
        delays = []
        game = Epic7PcWindow(sleep_fn=delays.append)
        game._user32 = MagicMock()
        game._user32.IsWindow.return_value = 1
        game._user32.SetForegroundWindow.return_value = 1
        game._user32.GetForegroundWindow.return_value = 123

        restored = game._restore_foreground(999, 123)

        self.assertFalse(restored)
        self.assertEqual([0.05] * 10, delays)

    def test_click_keeps_game_foreground_when_it_was_already_foreground(self):
        self.game._user32 = MagicMock()
        self.game._user32.GetForegroundWindow.return_value = 123
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(self.game, "_send_click"),
        ):
            self.game.click((991, 566))

        self.game._user32.SetForegroundWindow.assert_not_called()

    def test_send_click_holds_the_button_before_releasing(self):
        delays = []
        game = Epic7PcWindow(sleep_fn=delays.append)
        game._user32 = MagicMock()
        game._user32.GetSystemMetrics.side_effect = lambda metric: {
            0: 3200,
            1: 2000,
        }[metric]
        batches = []

        def send_input(count, inputs, _size):
            batches.append(
                [inputs[index].data.mouse.flags for index in range(count)]
            )
            return count

        game._user32.SendInput.side_effect = send_input

        game._send_click((1073, 1087))

        self.assertEqual(
            [
                [pc_window._MOUSEEVENTF_MOVE | pc_window._MOUSEEVENTF_ABSOLUTE],
                [pc_window._MOUSEEVENTF_LEFTDOWN],
                [pc_window._MOUSEEVENTF_LEFTUP],
            ],
            batches,
        )
        self.assertEqual([0.08], delays)

    def test_click_rejects_a_point_in_the_top_padding(self):
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(self.game, "_send_click", create=True) as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "PC 游戏渲染区外"):
                self.game.click((100, 51))

        click.assert_not_called()

    def test_back_does_not_send_escape_when_foreground_confirmation_fails(self):
        with (
            patch.object(
                self.game,
                "activate",
                side_effect=RuntimeError("PC 游戏窗口未能置前"),
            ),
            patch("auto_game_unified.core.pc_window.pyautogui.press") as press,
        ):
            with self.assertRaisesRegex(RuntimeError, "未能置前"):
                self.game.back()

        press.assert_not_called()

    def test_back_restores_the_previous_foreground_window_after_escape(self):
        calls = []
        self.game._user32 = MagicMock()
        self.game._user32.GetForegroundWindow.return_value = 999
        self.game._user32.IsWindow.return_value = 1
        self.game._user32.SetForegroundWindow.side_effect = (
            lambda hwnd: calls.append(("restore", hwnd)) or 1
        )
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch(
                "auto_game_unified.core.pc_window.pyautogui.press",
                side_effect=lambda key: calls.append(("press", key)),
            ),
        ):
            self.game.back()

        self.assertEqual([("press", "esc"), ("restore", 999)], calls)

    def test_back_logs_successful_focus_restore(self):
        events = []
        game = Epic7PcWindow(event_sink=events.append)
        game._user32 = MagicMock()
        game._user32.GetForegroundWindow.return_value = 999
        with (
            patch.object(game, "_find_window", return_value=123),
            patch.object(game, "activate", return_value=123),
            patch.object(game, "_ensure_input_allowed"),
            patch.object(game, "_restore_foreground", return_value=True),
            patch("auto_game_unified.core.pc_window.pyautogui.press"),
        ):
            game.back()

        self.assertIn("类型=返回", events[-1])
        self.assertIn("恢复原窗口=成功", events[-1])

    def test_capture_rejects_a_client_that_is_not_exact_render_size(self):
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "activate"),
            patch.object(
                self.game,
                "_rect",
                return_value=WindowRect(10, 20, 1000, 1000),
            ),
            patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
        ):
            screenshot.return_value = _FakeImage(
                np.full((1000, 1000, 3), 127, dtype=np.uint8)
            )
            with self.assertRaisesRegex(RuntimeError, "客户区尺寸.*1920x1080"):
                self.game.capture()

        screenshot.assert_not_called()


class _FakeImage:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array

    def convert(self, _: str) -> "_FakeImage":
        return self

    def __array__(self, dtype=None):
        return self.array.astype(dtype) if dtype is not None else self.array


if __name__ == "__main__":
    unittest.main()
