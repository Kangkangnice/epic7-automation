import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import subprocess

import numpy as np
import pygetwindow

from auto_game_unified.core.window import Epic7Window, WindowRect, WindowViewport


class WindowViewportTests(unittest.TestCase):
    def test_updated_ldplayer_title_is_accepted_only_for_dnplayer(self):
        game = Epic7Window()
        window = MagicMock()
        window.title = "雷电模拟器"
        window.isMinimized = False
        window._hWnd = 123

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=[window],
            ),
            patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
        ):
            self.assertIs(window, game._window())

    def test_updated_ldplayer_title_rejects_a_non_ldplayer_process(self):
        game = Epic7Window()
        window = MagicMock()
        window.title = "雷电模拟器"
        window.isMinimized = False
        window._hWnd = 123

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=[window],
            ),
            patch.object(game, "_window_process_name", return_value="notepad.exe"),
        ):
            with self.assertRaisesRegex(RuntimeError, "应恰好找到一个支持的雷电模拟器窗口"):
                game._window()

    def test_multiple_supported_ldplayer_windows_are_rejected(self):
        game = Epic7Window()
        windows = []
        for handle in (123, 456):
            window = MagicMock()
            window.title = "雷电模拟器"
            window.isMinimized = False
            window._hWnd = handle
            windows.append(window)

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=windows,
            ),
            patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
        ):
            with self.assertRaisesRegex(RuntimeError, "应恰好找到一个支持的雷电模拟器窗口"):
                game._window()

    def test_activate_does_not_reactivate_an_already_active_game_window(self):
        game = Epic7Window()
        window = MagicMock()
        window.isActive = True

        with (
            patch.object(game, "_window", return_value=window),
            patch("auto_game_unified.core.window.sleep") as wait,
        ):
            game.activate()

        window.activate.assert_not_called()
        wait.assert_not_called()

    def test_activate_accepts_pygetwindow_false_error_if_window_gained_focus(self):
        game = Epic7Window()
        window = MagicMock()
        window.isActive = False
        window._hWnd = 123
        window.activate.side_effect = pygetwindow.PyGetWindowException(
            "Error code from Windows: 0"
        )

        with (
            patch.object(game, "_window", return_value=window),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.GetForegroundWindow",
                return_value=123,
            ),
            patch("auto_game_unified.core.window.sleep") as wait,
        ):
            game.activate()

        window.activate.assert_called_once_with()
        wait.assert_called_once_with(0.3)

    def test_activate_waits_for_delayed_foreground_confirmation(self):
        game = Epic7Window()
        window = MagicMock()
        window.isActive = False
        window._hWnd = 123
        window.activate.side_effect = pygetwindow.PyGetWindowException(
            "Error code from Windows: 0"
        )

        with (
            patch.object(game, "_window", return_value=window),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.GetForegroundWindow",
                side_effect=[999, 999, 123],
            ),
            patch("auto_game_unified.core.window.sleep") as wait,
        ):
            game.activate()

        window.activate.assert_called_once_with()
        self.assertEqual([0.05, 0.05, 0.3], [call.args[0] for call in wait.call_args_list])

    def test_capture_crops_only_the_game_window(self):
        desktop = np.zeros((10, 16, 3), dtype=np.uint8)
        desktop[3:7, 4:9] = 127
        viewport = WindowViewport(lambda: WindowRect(4, 3, 5, 4))

        captured = viewport.crop(desktop)

        self.assertEqual((4, 5, 3), captured.shape)
        self.assertTrue(np.all(captured == 127))

    def test_click_coordinate_is_translated_back_to_desktop(self):
        viewport = WindowViewport(lambda: WindowRect(40, 30, 991, 566))

        self.assertEqual((140, 230), viewport.to_desktop((100, 200)))

    def test_scale_is_relative_to_the_template_capture_size(self):
        viewport = WindowViewport(lambda: WindowRect(40, 30, 991, 566))

        self.assertEqual((0.5, 0.5), viewport.scale_for((1982, 1132)))

    def test_rejects_a_window_with_a_different_aspect_ratio(self):
        viewport = WindowViewport(lambda: WindowRect(40, 30, 900, 900))

        with self.assertRaisesRegex(RuntimeError, "游戏窗口宽高比发生变化"):
            viewport.scale_for((1982, 1132))

    def test_live_capture_prefers_window_level_print(self):
        game = Epic7Window()
        render = np.full((1080, 1920, 3), 127, dtype=np.uint8)

        with (
            patch.object(game, "activate") as activate,
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch.object(game, "_print_window_render", return_value=render) as print_window,
            patch("auto_game_unified.core.window.pyautogui.screenshot") as screenshot,
        ):
            captured = game.capture()

        print_window.assert_called_once_with(456)
        activate.assert_not_called()
        screenshot.assert_not_called()
        self.assertEqual((1132, 1982, 3), captured.shape)
        self.assertTrue(np.all(captured[52:, :1920] == 127))

    def test_live_capture_falls_back_to_screen_capture_when_print_fails(self):
        game = Epic7Window()
        calls: list[str] = []
        fake_image = np.full((1080, 1920, 3), 127, dtype=np.uint8)

        with (
            patch.object(game, "activate", side_effect=lambda: calls.append("activate")),
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch.object(game, "_print_window_render", return_value=None),
            patch.object(
                game,
                "_window_rect_from_handle",
                return_value=WindowRect(5, 80, 1920, 1080),
            ),
            patch("auto_game_unified.core.window.pyautogui.screenshot") as screenshot,
        ):
            screenshot.side_effect = lambda **_: calls.append("screenshot") or _FakeImage(fake_image)
            captured = game.capture()

        self.assertEqual(["activate", "screenshot"], calls)
        screenshot.assert_called_once_with(region=(5, 80, 1920, 1080))
        self.assertEqual((1132, 1982, 3), captured.shape)
        self.assertTrue(np.all(captured[52:, :1920] == 127))

    def test_render_frame_is_embedded_in_the_legacy_canvas(self):
        render = np.full((1080, 1920, 3), 127, dtype=np.uint8)

        canvas = Epic7Window._legacy_canvas(render)

        self.assertEqual((1132, 1982, 3), canvas.shape)
        self.assertTrue(np.all(canvas[52:, :1920] == 127))
        self.assertTrue(np.all(canvas[:52] == 0))
        self.assertTrue(np.all(canvas[:, 1920:] == 0))

    def test_render_frame_rejects_an_unexpected_size(self):
        with self.assertRaisesRegex(RuntimeError, "1920x1080"):
            Epic7Window._legacy_canvas(np.zeros((720, 1280, 3), dtype=np.uint8))

    def test_back_uses_instance_command_without_foreground_activation(self):
        game = Epic7Window()
        calls: list[str] = []

        with (
            patch.object(
                game,
                "activate",
                side_effect=AssertionError("back must not wait for foreground focus"),
            ),
            patch.object(game, "_send_android_back", side_effect=lambda: calls.append("android-back")),
        ):
            game.back()

        self.assertEqual(["android-back"], calls)

    def test_back_activates_only_when_instance_command_fails(self):
        game = Epic7Window()
        calls: list[str] = []

        def send_back() -> None:
            if calls.count("back-attempt") == 0:
                calls.append("back-attempt")
                raise RuntimeError("back unavailable")
            calls.append("android-back")

        with (
            patch.object(game, "activate", side_effect=lambda: calls.append("activate")),
            patch.object(game, "_send_android_back", side_effect=send_back),
        ):
            game.back()

        self.assertEqual(["back-attempt", "activate", "android-back"], calls)

    def test_click_uses_instance_tap_without_foreground_activation(self):
        game = Epic7Window()
        calls: list[object] = []
        with (
            patch.object(
                game,
                "activate",
                side_effect=AssertionError("click must not wait for foreground focus"),
            ),
            patch.object(game, "_click_legacy", side_effect=calls.append),
        ):
            game.click((1689, 1060))

        self.assertEqual([(1689, 1060)], calls)

    def test_click_activates_only_when_instance_tap_fails(self):
        game = Epic7Window()
        calls: list[object] = []

        def click_legacy(point: tuple[int, int]) -> None:
            if not calls or calls[-1] != "activate":
                raise RuntimeError("tap unavailable")
            calls.append(point)

        with (
            patch.object(game, "activate", side_effect=lambda: calls.append("activate")),
            patch.object(game, "_click_legacy", side_effect=click_legacy),
        ):
            game.click((1689, 1060))

        self.assertEqual(["activate", (1689, 1060)], calls)

    def test_legacy_click_is_converted_to_render_coordinates(self):
        game = Epic7Window()

        with patch.object(game, "_send_render_tap") as tap:
            game._click_legacy((1790, 326))

        tap.assert_called_once_with((1790, 274))

    def test_legacy_click_rejects_chrome_coordinates(self):
        game = Epic7Window()

        for point in ((10, 20), (1950, 500)):
            with self.subTest(point=point):
                with self.assertRaisesRegex(RuntimeError, "渲染区外点击"):
                    game._click_legacy(point)

    def test_render_tap_uses_indexed_adb_input(self):
        game = Epic7Window()
        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch("auto_game_unified.core.window.subprocess.run") as run,
        ):
            game._send_render_tap((1790, 274))

        run.assert_called_once_with(
            [
                "D:\\epic7\\ldconsole.exe",
                "adb",
                "--index",
                "0",
                "--command",
                "shell input tap 1790 274",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_instance_lookup_hides_ldconsole_window(self):
        game = Epic7Window()
        window = MagicMock()
        window._hWnd = 123

        def set_process_id(_handle, process_id):
            process_id._obj.value = 789

        process = MagicMock()
        process.exe.return_value = "D:/epic7/dnplayer.exe"
        completed = MagicMock(stdout="0,name,top,456,unused,789\n")
        with (
            patch.object(game, "_window", return_value=window),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.GetWindowThreadProcessId",
                side_effect=set_process_id,
            ),
            patch("auto_game_unified.core.window.psutil.Process", return_value=process),
            patch("auto_game_unified.core.window.Path.exists", return_value=True),
            patch(
                "auto_game_unified.core.window.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            result = game._instance_channel()

        assert result == (Path("D:/epic7/ldconsole.exe"), "0", 456)
        run.assert_called_once_with(
            ["D:\\epic7\\ldconsole.exe", "list2"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_android_back_hides_ldconsole_window(self):
        game = Epic7Window()
        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch("auto_game_unified.core.window.subprocess.run") as run,
        ):
            game._send_android_back()

        run.assert_called_once_with(
            [
                "D:\\epic7\\ldconsole.exe",
                "action",
                "--index",
                "0",
                "--key",
                "call.keyboard",
                "--value",
                "back",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_campfire_wake_uses_a_real_desktop_mouse_click(self):
        game = Epic7Window()

        with (
            patch.object(game, "activate"),
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch.object(
                game,
                "_window_rect_from_handle",
                return_value=WindowRect(100, 200, 1920, 1080),
            ),
            patch("auto_game_unified.core.window.pyautogui.click") as click,
            patch.object(game, "_send_render_tap") as render_tap,
        ):
            game.wake((1000, 600))

        click.assert_called_once_with(1100, 748)
        render_tap.assert_not_called()


class _FakeImage:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array

    def convert(self, _: str) -> "_FakeImage":
        return self

    def __array__(self, dtype=None):
        return self.array.astype(dtype) if dtype is not None else self.array


if __name__ == "__main__":
    unittest.main()
