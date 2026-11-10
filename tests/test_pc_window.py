import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from auto_game_unified.core import pc_window
from auto_game_unified.core.pc_window import Epic7PcWindow, WindowRect
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)

ROOT = Path(__file__).resolve().parents[1]
SHARED_TEMPLATES = ROOT / "games" / "epic7" / "templates"


class PcWindowSafetyTests(unittest.TestCase):
    def setUp(self):
        self.game = Epic7PcWindow()
        # 本类守的是**前台通道**的安全语义（点前必须置前、点完不还原、权限不够绝不点）。
        # 2026-11-09 起窗口层默认改走后台通道，所以这里显式声明测哪一条 ——
        # 默认值本身由 test_pc_window_background.py 守，不在这里重复测。
        self.game.set_input_mode(pc_window.PC_INPUT_FOREGROUND)

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

        # 有界重试：拿不到就再试几次，但**绝不**退化成「前置截图」或桌面截图
        # （2026-11-01：偶发失败实测存在，所以从「只试一次」改成 3 次）。
        self.assertEqual(pc_window.CAPTURE_ATTEMPTS, bitblt.call_count)
        activate.assert_not_called()
        screenshot.assert_not_called()
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

    def test_click_never_hands_focus_back_after_input(self):
        """点完就完事，**不碰**原来的前台窗口（2026-11-01 用户拍板：来回切会闪）。

        这条钉的是「不许再偷偷加回还原逻辑」：一旦有人加回去，画面又开始闪。
        """
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

        self.assertEqual([("click", (1001, 534))], calls)

    def test_click_reports_the_game_staying_in_front(self):
        events = []
        game = Epic7PcWindow(event_sink=events.append)
        game.set_input_mode(pc_window.PC_INPUT_FOREGROUND)
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
        self.assertIn("保持在前台=是", events[-1])

    def test_click_keeps_the_game_in_front_instead_of_flipping_windows(self):
        """点完**不还原**原来的窗口：来回切会让画面一闪一闪（2026-11-01 用户拍板）。

        助手被游戏盖住不影响任何事 —— 日志照常落盘。
        """
        events = []
        game = Epic7PcWindow(event_sink=events.append)
        game.set_input_mode(pc_window.PC_INPUT_FOREGROUND)
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
            patch.object(game, "_restore_foreground") as restore,
        ):
            game.click((991, 566))

        self.assertIn("类型=点击", events[-1])
        self.assertIn("保持在前台=是", events[-1])
        restore.assert_not_called()

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

    def test_back_never_hands_focus_back_after_escape(self):
        """与点击同口径：返回键按完也不还原前台窗口。"""
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

        self.assertEqual([("press", "esc")], calls)

    def test_back_reports_the_game_staying_in_front(self):
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
        self.assertIn("保持在前台=是", events[-1])

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


class PcSharedNavigationContractTests(unittest.TestCase):
    """PC 与模拟器共用同一套模板与几何：页面判定和坐标都不许按平台分叉。

    2026-09-28：原 ``test_pc_shared_navigation.py`` 里依赖 PC 专属夹具（随 PC 素材全删）
    的两条用例被移除；下面两条是**框架级**断言，不依赖任何素材，迁到本文件保留。
    """

    def test_navigation_builder_has_no_legacy_pc_directory_switch(self):
        self.assertNotIn(
            "templates" + "_pc",
            inspect.getsource(build_navigation_templates),
        )

    def test_black_pc_frame_is_not_recognized_as_lobby(self):
        screen = Epic7PcWindow._legacy_canvas(
            np.zeros((1080, 1920, 3), dtype=np.uint8)
        )
        navigator = Epic7Navigator(
            build_navigation_templates(SHARED_TEMPLATES),
            Runtime(lambda: screen, lambda _point: None),
        )
        self.assertEqual(navigator.observe(screen).name, "invalid")


class PcCaptureRetryTests(unittest.TestCase):
    """后台抓帧会**偶发**失败：2026-11-01 实测 40 拍挂 2 次，且当时游戏就在前台。

    一次 hiccup 不该把整条路线掐断（那天竞技场就是死在这一下），
    但试满仍然拿不到就必须照旧抛错 —— 该 fail-closed 的性质一点都不能松。
    """

    def setUp(self):
        self.game = Epic7PcWindow()
        self.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.frame[100:300, 100:300] = 255

    def _patch(self, bitblt):
        return (
            patch.object(self.game, "_find_window", return_value=1),
            patch.object(self.game, "_validated_rect"),
            patch.object(self.game, "_capture_client_bitblt", side_effect=bitblt),
            patch.object(self.game, "_sleep"),
        )

    def test_one_hiccup_is_retried_instead_of_killing_the_route(self):
        calls = {"count": 0}

        def flaky(_hwnd):
            calls["count"] += 1
            return None if calls["count"] == 1 else self.frame

        find, rect, bitblt, sleep = self._patch(flaky)
        with find, rect, bitblt, sleep:
            result = self.game.capture()

        self.assertEqual(2, calls["count"])
        self.assertEqual((1132, 1982, 3), result.shape)

    def test_it_still_fails_closed_when_every_attempt_misses(self):
        calls = {"count": 0}

        def always_miss(_hwnd):
            calls["count"] += 1
            return None

        find, rect, bitblt, sleep = self._patch(always_miss)
        with find, rect, bitblt, sleep:
            # 断言里引用常量而不是写死「3 次」：重试预算随实测调过（3→6），
            # 这条测的是「试满就报错」，不是「试几次」。
            with self.assertRaisesRegex(
                RuntimeError, f"已重试 {pc_window.CAPTURE_ATTEMPTS} 次"
            ):
                self.game.capture()

        self.assertEqual(pc_window.CAPTURE_ATTEMPTS, calls["count"])

    def test_the_retry_budget_grows_enough_to_survive_a_reconnect_blackout(self):
        """线路重连会把画面打成黑屏十几秒：固定 0.3 秒 × 10 次（3 秒）撑不住。

        2026-11-08 竞技场跑到第 6 轮时网络断开，十次重试在两秒多里就打光，
        紧接着「回首页」也跟着失败。光加次数治不了这一类 —— 黑屏时长取决于
        「重连要多久」，不是「抖一下」。

        这条锁的是**退避形状**，不写死具体数值：
        ① 首次等待仍是原来的短延迟（偶发重绘失败的代价不能变大）；
        ② 总预算必须够到十秒以上；
        ③ 单跳不得超过上限（仍然有界）。
        """
        find = patch.object(self.game, "_find_window", return_value=1)
        rect = patch.object(self.game, "_validated_rect")
        bitblt = patch.object(self.game, "_capture_client_bitblt", return_value=None)
        with find, rect, bitblt, patch.object(self.game, "_sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "PC 后台截图失败"):
                self.game.capture()

        waits = [call.args[0] for call in sleep.call_args_list]
        self.assertTrue(waits, "一次等待都没有，退避根本没生效")
        self.assertEqual(pc_window.CAPTURE_RETRY_DELAY, waits[0])
        self.assertGreaterEqual(sum(waits), 10.0)
        self.assertLessEqual(max(waits), pc_window.CAPTURE_MAX_DELAY)


if __name__ == "__main__":
    unittest.main()


class Epic7PcWindowSwipeTests(unittest.TestCase):
    """PC 端滑动的窗口层契约（2026-11-02 新增：此前 swipe 传 None，四条路线卡在这）。"""

    def setUp(self):
        self.game = Epic7PcWindow()

    def test_swipe_translates_both_endpoints_into_client_coordinates(self):
        """画布坐标 → 客户区要减 LEGACY_TOP(52)，再叠加窗口左上角。"""
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(self.game, "_send_swipe", create=True) as send,
        ):
            self.game.swipe((400, 800), (400, 200), 300)

        send.assert_called_once_with((410, 768), (410, 168), 300)

    def test_swipe_rejects_a_point_in_the_top_padding(self):
        """落在顶部黑边（0..51）的坐标一律拒绝 —— 那是补边，不是游戏渲染区。"""
        with (
            patch.object(self.game, "activate", return_value=123),
            patch.object(self.game, "_ensure_input_allowed"),
            patch.object(
                self.game,
                "_validated_rect",
                return_value=WindowRect(10, 20, 1920, 1080),
            ),
            patch.object(self.game, "_send_swipe", create=True) as send,
        ):
            with self.assertRaises(RuntimeError):
                self.game.swipe((400, 800), (400, 10), 300)

        send.assert_not_called()

    def test_send_swipe_holds_the_button_until_the_end(self):
        """轨迹必须是「按下 → 多次移动 → 抬起」，中途不抬键（抬手就成点击了）。"""
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

        game._send_swipe((100, 900), (100, 300), 160)

        flags = [batch[0] for batch in batches]
        self.assertEqual(pc_window._MOUSEEVENTF_LEFTDOWN, flags[1])
        self.assertEqual(pc_window._MOUSEEVENTF_LEFTUP, flags[-1])
        self.assertNotIn(pc_window._MOUSEEVENTF_LEFTUP, flags[1:-1])
        self.assertTrue(
            all(
                flag == pc_window._MOUSEEVENTF_MOVE | pc_window._MOUSEEVENTF_ABSOLUTE
                for flag in [flags[0], *flags[2:-1]]
            )
        )
        # 160ms 按 16ms 一步 ⇒ 10 步，每步一次 sleep
        self.assertEqual(10, len(delays))
