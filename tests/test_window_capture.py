import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import subprocess
import tracemalloc

import numpy as np
import pygetwindow

from auto_game_unified.core.window import (
    Epic7Window,
    WindowRect,
    WindowViewport,
    render_is_usable,
)


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

    def test_render_tap_surfaces_a_dead_adb_channel(self):
        """ldconsole 在设备离线时**退出码仍然是 0**，失败只写在输出里。

        不检查输出的话，一次根本没送达的点击会被当成发送成功：上层只能看到
        「点击验收无效」，白烧掉重试次数后报一个与真因无关的「导航转场失败」，
        既不告警也不切通道（2026-09-24 实机就是这么静默失效的）。
        """
        for stream, payload in (
            ("stdout", b"adb.exe: device offline\n"),
            ("stderr", b"error: device not found\n"),
        ):
            with self.subTest(stream=stream):
                game = Epic7Window()
                result = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"", stderr=b""
                )
                setattr(result, stream, payload)
                with (
                    patch.object(
                        game,
                        "_instance_channel",
                        return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
                    ),
                    patch(
                        "auto_game_unified.core.window.subprocess.run",
                        return_value=result,
                    ),
                    self.assertRaisesRegex(RuntimeError, "输入通道不可用"),
                ):
                    game._send_render_tap((1790, 274))

    def test_render_tap_accepts_a_healthy_adb_channel(self):
        """通道正常时输出为空，不能被上面的检查误伤。"""
        game = Epic7Window()
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch("auto_game_unified.core.window.subprocess.run", return_value=result),
        ):
            game._send_render_tap((1790, 274))

    def test_input_channel_probe_accepts_a_healthy_channel(self):
        """通道本来就通时只探一次，绝不能顺手去 kill/start adb 服务。"""
        game = Epic7Window()
        calls: list[list[str]] = []

        def run(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"ping\n", stderr=b""
            )

        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch("auto_game_unified.core.window.subprocess.run", side_effect=run),
            patch("auto_game_unified.core.window.sleep"),
        ):
            game.ensure_input_channel()

        self.assertEqual(
            [
                [
                    "D:\\epic7\\ldconsole.exe",
                    "adb",
                    "--index",
                    "0",
                    "--command",
                    "shell echo ping",
                ]
            ],
            calls,
        )

    def test_input_channel_rebuilds_adb_when_the_device_is_offline(self):
        """设备 offline 时 `ldconsole` 的退出码仍是 0，失败只写在输出里。

        自检必须①认得这种失败 ②用 `adb kill-server` → `start-server` 重建
        ③**重建之后再探一次**，而不是修完就假定好了。
        （2026-09-24、2026-09-28 两次实机都是这两条命令一步到位。）
        """
        game = Epic7Window()
        calls: list[list[str]] = []
        probes = [b"adb.exe: device offline\n", b"ping\n"]

        def run(args, **_kwargs):
            calls.append(list(args))
            if "--command" in args:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=probes.pop(0), stderr=b""
                )
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"", stderr=b""
            )

        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch.object(Path, "exists", return_value=True),
            patch("auto_game_unified.core.window.subprocess.run", side_effect=run),
            patch("auto_game_unified.core.window.sleep"),
        ):
            game.ensure_input_channel()

        adb = str(Path("D:/epic7/adb.exe"))
        self.assertIn([adb, "kill-server"], calls)
        self.assertIn([adb, "start-server"], calls)
        self.assertEqual([], probes, "重建后必须再探一次通道")
        self.assertEqual(2, sum(1 for call in calls if "--command" in call))

    def test_input_channel_fails_loudly_when_adb_never_recovers(self):
        """重建也救不回来时必须显式失败，而不是放行让第一条路线默默打挂。"""
        game = Epic7Window()

        def run(args, **_kwargs):
            if "--command" in args:
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=b"adb.exe: device offline\n",
                    stderr=b"",
                )
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"", stderr=b""
            )

        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch.object(Path, "exists", return_value=True),
            patch("auto_game_unified.core.window.subprocess.run", side_effect=run),
            patch("auto_game_unified.core.window.sleep"),
            self.assertRaisesRegex(RuntimeError, "自动重建 adb 服务 3 次仍未恢复"),
        ):
            game.ensure_input_channel()

    def test_legacy_swipe_is_converted_and_sent_through_indexed_adb(self):
        game = Epic7Window()
        with (
            patch.object(
                game,
                "_instance_channel",
                return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
            ),
            patch("auto_game_unified.core.window.subprocess.run") as run,
        ):
            game.swipe((1300, 850), (1300, 220), 500)

        run.assert_called_once_with(
            [
                "D:\\epic7\\ldconsole.exe",
                "adb",
                "--index",
                "0",
                "--command",
                "shell input swipe 1300 798 1300 168 500",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_legacy_swipe_rejects_chrome_coordinates(self):
        game = Epic7Window()

        with self.assertRaisesRegex(RuntimeError, "渲染区外滑动"):
            game.swipe((1300, 20), (1300, 220), 500)

    def test_legacy_swipe_surfaces_a_dead_adb_channel(self):
        """滑动和点击共用同一条 adb 通道，失败可见性必须一致。

        两处是同一份 `subprocess.run(check=True, capture_output=True)` 的复制，
        只修点击会让「右侧滑动」重复点击踩过的坑。
        """
        for stream, payload in (
            ("stdout", b"adb.exe: device offline\n"),
            ("stderr", b"error: device not found\n"),
        ):
            with self.subTest(stream=stream):
                game = Epic7Window()
                result = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"", stderr=b""
                )
                setattr(result, stream, payload)
                with (
                    patch.object(
                        game,
                        "_instance_channel",
                        return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
                    ),
                    patch(
                        "auto_game_unified.core.window.subprocess.run",
                        return_value=result,
                    ),
                    self.assertRaisesRegex(RuntimeError, "输入通道不可用"),
                ):
                    game._send_render_swipe((1300, 798), (1300, 168), 500)

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

    def test_android_back_surfaces_a_dead_console(self):
        """返回键走 ldconsole 实例通道（不是 adb），但它出错时**同样返回 0**。

        2026-09-24 实机实测，四条都返回退出码 0：
          `adb --index 9 ...`                  -> `adb.exe: device 'emulator-5572' not found`
          `adb --index 0 ...`（设备离线）       -> `adb.exe: device offline`
          `action --index 9 --key ... --value back` -> `player don't exist!`
          `action --index 0`（漏参数）          -> 整篇 usage 文本
        ⇒ 不检查输出的话，`back()` 的 activate-重试分支同样永不触发。
        好在 navigation 层对返回另有**画面级验收**（`返回验收=无效`、
        `受控返回8次后仍未回到大厅`），所以它的后果比点击轻；
        但「出错却报成功」本身仍该修掉 —— 用户的要求是「所有按键都不能坏」。
        """
        for payload in (
            b"player don't exist!",
            b"adb.exe: device offline\n",
            b"dnplayer v14.0.22.0\r\nUsage:\r\n\r\nldconsole <command>\r\n",
        ):
            with self.subTest(payload=payload):
                game = Epic7Window()
                result = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=payload, stderr=b""
                )
                with (
                    patch.object(
                        game,
                        "_instance_channel",
                        return_value=(Path("D:/epic7/ldconsole.exe"), "0", 456),
                    ),
                    patch(
                        "auto_game_unified.core.window.subprocess.run",
                        return_value=result,
                    ),
                    self.assertRaisesRegex(RuntimeError, "输入通道不可用"),
                ):
                    game._send_android_back()

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


class RenderIsUsableTests(unittest.TestCase):
    """判「这一帧是不是纯色」必须走 uint8 极差，不能退化成 np.std。

    背景：np.std 按 float64 累加，1920×1080×3 每帧多分配约 47.5 MiB，
    与模拟器抢内存时会出现 _ArrayMemoryError。极差法每帧只多分配几十字节。
    """

    def test_uniform_frame_is_rejected(self):
        rgb = np.full((1080, 1920, 3), 17, dtype=np.uint8)
        self.assertFalse(render_is_usable(rgb))

    def test_black_frame_is_rejected(self):
        rgb = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertFalse(render_is_usable(rgb))

    def test_one_level_spread_is_still_rejected(self):
        # max-min == 1 视为纯色：单级量化噪声不足以说明画面画出来了
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        rgb[0, 0, 0] = 1
        self.assertFalse(render_is_usable(rgb))

    def test_two_level_spread_is_accepted(self):
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        rgb[0, 0, 0] = 2
        self.assertTrue(render_is_usable(rgb))

    def test_normal_picture_is_accepted(self):
        rgb = np.arange(1080 * 1920 * 3, dtype=np.uint8).reshape(1080, 1920, 3)
        self.assertTrue(render_is_usable(rgb))

    def test_does_not_allocate_a_float64_copy_of_the_frame(self):
        """守住内存回归：极差法不该像 np.std 那样按 float64 复制整帧。"""
        rgb = np.random.default_rng(0).integers(
            0, 256, size=(1080, 1920, 3), dtype=np.uint8
        )
        tracemalloc.start()
        try:
            render_is_usable(rgb)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # 极差法实测峰值 ~0.01 MiB；np.std 路线是 47.5 MiB，留足余量仍能抓住回归
        self.assertLess(peak, 8 * 1024 * 1024, f"峰值 {peak / 1024 / 1024:.2f} MiB")


class MinimizedWindowRestoreTests(unittest.TestCase):
    """窗口被最小化（含误触）时应当自动还原，而不是立刻报错终止整条路线。"""

    def _minimized_game(self):
        game = Epic7Window()
        window = MagicMock()
        window.title = "雷电模拟器"
        window.isMinimized = True
        window._hWnd = 123
        return game, window

    def test_minimized_window_is_restored_without_stealing_the_foreground(self):
        game, window = self._minimized_game()
        messages: list[str] = []
        game.set_event_sink(messages.append)

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=[window],
            ),
            patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.ShowWindow"
            ) as show_window,
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.IsIconic",
                return_value=0,
            ) as is_iconic,
            patch("auto_game_unified.core.window.sleep") as wait,
        ):
            self.assertIs(window, game._window())

        show_window.assert_called_once_with(123, Epic7Window._SW_SHOWNOACTIVATE)
        is_iconic.assert_called_once_with(123)
        wait.assert_called_once_with(Epic7Window._RESTORE_SETTLE_SECONDS)
        self.assertTrue(any("最小化已自动还原" in message for message in messages))

    def test_minimized_window_escalates_to_a_foreground_restore_when_needed(self):
        game, window = self._minimized_game()

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=[window],
            ),
            patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.ShowWindow"
            ) as show_window,
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.IsIconic",
                side_effect=[1] * 21 + [0],
            ),
            patch("auto_game_unified.core.window.sleep"),
        ):
            game._window()

        self.assertEqual(
            [call.args for call in show_window.call_args_list],
            [(123, Epic7Window._SW_SHOWNOACTIVATE), (123, Epic7Window._SW_RESTORE)],
        )

    def test_window_that_stays_minimized_still_fails_instead_of_running_blind(self):
        game, window = self._minimized_game()

        with (
            patch(
                "auto_game_unified.core.window.pygetwindow.getAllWindows",
                return_value=[window],
            ),
            patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
            patch("auto_game_unified.core.window.ctypes.windll.user32.ShowWindow"),
            patch(
                "auto_game_unified.core.window.ctypes.windll.user32.IsIconic",
                return_value=1,
            ),
            patch("auto_game_unified.core.window.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "自动还原未生效"):
                game._window()


class _FakeImage:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array

    def convert(self, _: str) -> "_FakeImage":
        return self

    def __array__(self, dtype=None):
        return self.array.astype(dtype) if dtype is not None else self.array


if __name__ == "__main__":
    unittest.main()
