"""PC 后台输入通道（SetCursorPos + WM_ACTIVATE + PostMessage）的行为测试。

只测「消息序列与坐标换算」这一层：真实的游戏是否响应，必须用
``tools/probe_background_input.py`` 在真机上量，测不出来不算通过。
"""

import ctypes
from ctypes import wintypes
import os
import unittest
from unittest.mock import MagicMock, patch

from auto_game_unified.core.pc_window import (
    LEGACY_TOP,
    PC_INPUT_BACKGROUND,
    PC_INPUT_ENV,
    PC_INPUT_FOREGROUND,
    PC_INPUT_MODES,
    Epic7PcWindow,
    WindowRect,
    _MK_LBUTTON,
    _WA_ACTIVE,
    _WM_ACTIVATE,
    _WM_LBUTTONDOWN,
    _WM_LBUTTONUP,
    _WM_MOUSEMOVE,
)
from auto_game_unified import main as main_module


class InputModeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.game = Epic7PcWindow()

    def test_default_is_background(self):
        # 2026-11-09 用户拍板：后台点击已多次实跑正常，默认就是后台。
        # 拖拽 / ESC 不受影响，它们各自强制前台（见 swipe / back 的说明）。
        self.assertEqual(self.game.input_mode, PC_INPUT_BACKGROUND)

    def test_unknown_mode_is_rejected_instead_of_silently_falling_back(self):
        with self.assertRaisesRegex(ValueError, "未知的 PC 输入通道"):
            self.game.set_input_mode("backgroundd")

    def test_switching_to_background_is_reported(self):
        messages: list[str] = []
        self.game.set_event_sink(messages.append)
        self.game.set_input_mode(PC_INPUT_BACKGROUND)
        self.assertEqual(self.game.input_mode, PC_INPUT_BACKGROUND)
        self.assertTrue(any("通道=background" in line for line in messages))

    def test_minimized_window_is_restored_before_touching_it(self):
        """最小化是**唯一**真正取不到画面的情况：客户区变成 0×0，必须先还原。

        （遮挡不影响 —— 2026-11-08 实测把游戏整个盖住，BitBlt 仍返回完整画面。）
        照 ``core/window.py`` 的口径：先 ``SW_SHOWNOACTIVATE``（还原但不抢焦点），
        不生效才 ``SW_RESTORE``。
        """
        messages: list[str] = []
        self.game.set_event_sink(messages.append)
        self.game._user32 = MagicMock()
        states = [True, False]  # 第一次问：最小化；ShowWindow 之后再问：已还原

        def iconic(_hwnd):
            return states.pop(0) if states else False

        self.game._user32.IsIconic.side_effect = iconic

        self.game._restore_if_minimized(123)

        self.game._user32.ShowWindow.assert_called_once_with(123, 0x0004)
        self.assertTrue(any("已最小化" in line for line in messages))

    def test_click_dispatches_to_background_when_selected(self):
        self.game.set_input_mode(PC_INPUT_BACKGROUND)
        with patch.object(self.game, "_background_click") as background:
            self.game.click((900, 1000))
        background.assert_called_once_with((900, 1000))


class BackgroundClickMessageTests(unittest.TestCase):
    def setUp(self):
        self.game = Epic7PcWindow()
        self.game.set_input_mode(PC_INPUT_BACKGROUND)
        self.game._user32 = MagicMock()
        self.rect = WindowRect(100, 200, 1920, 1080)

    def _run(self, canvas_point):
        def fill_cursor(pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = 640, 480
            return 1

        self.game._user32.GetCursorPos.side_effect = fill_cursor
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_validated_rect", return_value=self.rect),
        ):
            self.game._background_click(canvas_point)
        return self.game._user32

    def test_canvas_point_is_converted_to_client_and_screen(self):
        user32 = self._run((900, 1000 + LEGACY_TOP))
        # 画布 y 减去顶部偏移后是客户区坐标；屏幕坐标 = 客户区原点 + 客户区坐标。
        self.assertEqual(user32.SetCursorPos.call_args_list[0].args, (1000, 1200))

    def test_message_sequence_moves_then_clicks(self):
        user32 = self._run((900, 1000 + LEGACY_TOP))
        expected_lparam = (1000 << 16) | 900
        posts = [call.args for call in user32.PostMessageW.call_args_list]
        self.assertEqual(
            posts,
            [
                (123, _WM_MOUSEMOVE, 0, expected_lparam),
                (123, _WM_LBUTTONDOWN, _MK_LBUTTON, expected_lparam),
                (123, _WM_LBUTTONUP, 0, expected_lparam),
            ],
        )
        user32.SendMessageW.assert_called_once_with(123, _WM_ACTIVATE, _WA_ACTIVE, 0)

    def test_cursor_is_moved_before_messages_and_restored_after(self):
        user32 = self._run((900, 1000 + LEGACY_TOP))
        moves = user32.SetCursorPos.call_args_list
        self.assertEqual(moves[0].args, (1000, 1200))
        self.assertEqual(moves[-1].args, (640, 480))

    def test_point_outside_render_area_is_rejected(self):
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_validated_rect", return_value=self.rect),
            self.assertRaisesRegex(RuntimeError, "渲染区外"),
        ):
            self.game._background_click((900, LEGACY_TOP - 1))

    def test_swipe_goes_foreground_even_in_background_mode(self):
        """滑动**没有**后台方案：Raw Input 只喂前台窗口。

        2026-11-08 实跑对照（同一客户端、同一条刷书签路线）：
        - 21:08 后台拖拽：消息全发出去了，列表一个像素没动
          （诊断图 ``scroll_source`` 与 ``scroll_peak`` 的商品行完全相同，
          那 25.8 的「画面差」全是商人对话气泡弹出又消失）；
        - 13:31 前台真鼠标拖拽：连续 5 次全部滚动成功，画面差 30~33。

        所以后台通道下也必须激活窗口走 SendInput，**不许再发 PostMessage 轨迹**。
        这条反向护栏钉的就是「别再退回后台拖拽」。
        """
        self.game.set_input_mode(PC_INPUT_BACKGROUND)
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_validated_rect", return_value=self.rect),
            patch.object(self.game, "activate", return_value=123) as activate,
            patch.object(self.game, "_send_swipe") as send_swipe,
            patch.object(self.game, "_restore_foreground", return_value=True) as restore,
        ):
            self.game.swipe((100, 100 + LEGACY_TOP), (200, 200 + LEGACY_TOP), 160)

        activate.assert_called_once()
        send_swipe.assert_called_once()
        # 滑完必须把前台还给用户原来的窗口（刷书签一轮滑 2 次，不还不行的）
        restore.assert_called_once()
        self.game._user32.PostMessageW.assert_not_called()
        self.game._user32.SetCursorPos.assert_not_called()

    def test_second_click_skips_restore_when_user_did_not_move_mouse(self):
        """连续点击只做一次瞬移（不来回还原），抖动砍半。"""
        self._run((900, 1000 + LEGACY_TOP))
        self.game._user32.reset_mock()
        self._run((900, 1000 + LEGACY_TOP))
        self.assertEqual(len(self.game._user32.SetCursorPos.call_args_list), 1)

    def test_cursor_is_restored_when_user_moves_mouse_between_clicks(self):
        """用户一动鼠标，下一次动作后就把光标还到他的新位置。"""
        self._run((900, 1000 + LEGACY_TOP))

        def moved(pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = 10, 20
            return 1

        self.game._user32.GetCursorPos.side_effect = moved
        self.game._user32.reset_mock()
        with (
            patch.object(self.game, "_find_window", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(self.game, "_validated_rect", return_value=self.rect),
        ):
            self.game._background_click((900, 1000 + LEGACY_TOP))
        self.assertEqual(
            self.game._user32.SetCursorPos.call_args_list[-1].args, (10, 20)
        )


class InputModeConstantsTests(unittest.TestCase):
    def test_only_two_modes_are_supported(self):
        self.assertEqual(PC_INPUT_MODES, (PC_INPUT_FOREGROUND, PC_INPUT_BACKGROUND))


class InputModeWiringTests(unittest.TestCase):
    """CLI ⇄ 环境变量 ⇄ 窗口 的接线。

    回归点：``main()`` 曾经无条件把 ``--pc-input-mode`` 的**默认值** foreground
    写进环境变量，导致桌面界面选的 background 在子进程里被悄悄抹掉
    （界面显示「不占用前台」，实际照旧抢前台）。
    """

    def test_cli_without_flag_does_not_claim_a_mode(self):
        self.assertIsNone(main_module.parse_args([]).pc_input_mode)

    def test_cli_accepts_explicit_background(self):
        args = main_module.parse_args(["--pc-input-mode", "background"])
        self.assertEqual(args.pc_input_mode, PC_INPUT_BACKGROUND)

    def test_env_background_survives_when_cli_is_silent(self):
        with (
            patch.dict(os.environ, {PC_INPUT_ENV: PC_INPUT_BACKGROUND}),
            patch.object(main_module, "_run_daily", return_value=0),
        ):
            code = main_module.main(["--daily", "--live", "--confirm", "RUN"])
            self.assertEqual(code, 0)
            self.assertEqual(os.environ[PC_INPUT_ENV], PC_INPUT_BACKGROUND)

    def test_explicit_cli_flag_overrides_env(self):
        with (
            patch.dict(os.environ, {PC_INPUT_ENV: PC_INPUT_BACKGROUND}),
            patch.object(main_module, "_run_daily", return_value=0),
        ):
            main_module.main(
                [
                    "--daily",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--pc-input-mode",
                    PC_INPUT_FOREGROUND,
                ]
            )
            self.assertEqual(os.environ[PC_INPUT_ENV], PC_INPUT_FOREGROUND)

    def test_build_runtime_hands_env_mode_to_pc_window(self):
        fake_window = MagicMock()
        with (
            patch.dict(os.environ, {PC_INPUT_ENV: PC_INPUT_BACKGROUND}),
            patch.object(main_module, "Epic7PcWindow", return_value=fake_window),
            patch.object(main_module, "Runtime"),
            patch.object(main_module, "WindowsPStopHotkey"),
        ):
            main_module._build_runtime(
                "arena", dry_run=False, window_backend="pc"
            )
        fake_window.set_input_mode.assert_called_once_with(PC_INPUT_BACKGROUND)

    def test_build_runtime_defaults_to_background_when_env_missing(self):
        """环境变量没设时必须落到后台。

        回归点：``main.py`` 里原先写死 ``PC_INPUT_FOREGROUND`` 兜底 —— 只改窗口层
        的类默认值会被它顶掉，这条钉子盯的就是那层兜底。
        """
        fake_window = MagicMock()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(main_module, "Epic7PcWindow", return_value=fake_window),
            patch.object(main_module, "Runtime"),
            patch.object(main_module, "WindowsPStopHotkey"),
        ):
            os.environ.pop(PC_INPUT_ENV, None)
            main_module._build_runtime("arena", dry_run=False, window_backend="pc")
        fake_window.set_input_mode.assert_called_once_with(PC_INPUT_BACKGROUND)


if __name__ == "__main__":
    unittest.main()
