import unittest
from unittest.mock import MagicMock, patch

import numpy as np

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

    def test_capture_does_not_screenshot_when_foreground_confirmation_fails(self):
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
            patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
        ):
            screenshot.return_value = _FakeImage(
                np.full((1132, 1982, 3), 127, dtype=np.uint8)
            )
            with self.assertRaisesRegex(RuntimeError, "未能置前"):
                self.game.capture()

        screenshot.assert_not_called()

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

    def test_click_uses_send_input_at_the_mapped_desktop_point(self):
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(
                self.game,
                "_ensure_input_allowed",
            ),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1982, 1132),
            ),
            patch.object(self.game, "_send_click", create=True) as click,
        ):
            self.game.click((991, 566))

        click.assert_called_once_with((1001, 586))

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

    def test_capture_rejects_an_incompatible_client_aspect_ratio(self):
        with (
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
            with self.assertRaisesRegex(RuntimeError, "宽高比"):
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
