"""统一 ADB 模拟器后端的离线验收（不碰真机，全部注入假 runner）。

这个后端不认模拟器品牌：雷电 / MuMu / 夜神走同一套逻辑。
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from auto_game_unified.core.emulator_adb import (
    GAME_PACKAGE,
    AdbDeviceSpec,
    AdbEmulatorClient,
    EmulatorNotFound,
    discover_game_device,
    find_adb,
)
from auto_game_unified.core.window import Epic7Window


def _result(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _png_bytes(width: int = 1920, height: int = 1080) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".png", np.full((height, width, 3), 120, dtype=np.uint8))
    assert ok
    return buffer.tobytes()


class FindAdbTests(unittest.TestCase):
    """找 adb.exe：先 PATH，兜底从运行中进程/安装目录反推，不认品牌。"""

    def test_path_takes_priority(self):
        with patch(
            "auto_game_unified.core.emulator_adb.shutil.which",
            return_value=r"C:\tools\adb.exe",
        ):
            found = find_adb()
        self.assertEqual(Path(r"C:\tools\adb.exe"), found)

    def test_reports_clearly_when_no_adb_anywhere(self):
        import auto_game_unified.core.emulator_adb as mod

        with (
            patch.object(mod.shutil, "which", return_value=None),
            patch.object(mod.psutil, "process_iter", return_value=[]),
            patch.object(mod, "_ADB_SEARCH_ROOTS", ()),
        ):
            with self.assertRaisesRegex(EmulatorNotFound, "未找到 adb.exe"):
                find_adb()


class DiscoverGameDeviceTests(unittest.TestCase):
    """按游戏 PID 去重：一个模拟器的多端口 = 一个实例；多 PID = 多开。"""

    def test_multiple_ports_same_pid_collapse_to_one_device(self):
        listed = _result(
            b"List of devices attached\n"
            b"127.0.0.1:16384\tdevice\n"
            b"127.0.0.1:7555\tdevice\n"
            b"emulator-5554\tdevice\n"
        )

        def runner(_adb, args, **_kwargs):
            if args == ["devices"]:
                return listed
            return _result(b"3286\n")

        device = discover_game_device(Path("adb.exe"), runner=runner)
        self.assertEqual(3286, device.game_pid)
        self.assertEqual("127.0.0.1:16384", device.serial)

    def test_only_devices_running_the_game_are_considered(self):
        listed = _result(b"List of devices attached\nno-game\tdevice\nhas-game\tdevice\n")

        def runner(_adb, args, **_kwargs):
            if args == ["devices"]:
                return listed
            serial = args[args.index("-s") + 1]
            return _result(b"999\n" if serial == "has-game" else b"")

        device = discover_game_device(Path("adb.exe"), runner=runner)
        self.assertEqual("has-game", device.serial)
        self.assertEqual(999, device.game_pid)

    def test_two_distinct_game_pids_raise_for_multi_instance(self):
        listed = _result(b"List of devices attached\na\tdevice\nb\tdevice\n")

        def runner(_adb, args, **_kwargs):
            if args == ["devices"]:
                return listed
            serial = args[args.index("-s") + 1]
            return _result(b"111\n" if serial == "a" else b"222\n")

        with self.assertRaisesRegex(EmulatorNotFound, "多个正在运行第七史诗"):
            discover_game_device(Path("adb.exe"), runner=runner)

    def test_no_game_running_raises_with_actionable_message(self):
        with self.assertRaisesRegex(EmulatorNotFound, "未找到正在运行第七史诗"):
            discover_game_device(Path("adb.exe"), runner=lambda _a, _args, **_kw: _result(b"List of devices attached\n"))

    def test_offline_device_is_repaired_automatically(self):
        steps = [
            (["devices"], _result(b"List of devices attached\nemulator-5554\toffline\n")),
            (["reconnect", "offline"], _result()),
            (["devices"], _result(b"List of devices attached\n")),
            (["kill-server"], _result()),
            (["start-server"], _result(stdout=b"* daemon started successfully\n")),
            (["devices"], _result(b"List of devices attached\nemulator-5554\tdevice\n")),
            (["-s", "emulator-5554", "shell", "pidof", GAME_PACKAGE], _result(b"2247\n")),
        ]
        calls: list[list[str]] = []

        def runner(_adb, args, **_kwargs):
            expected, result = steps.pop(0)
            self.assertEqual(expected, args)
            calls.append(args)
            return result

        device = discover_game_device(Path("adb.exe"), runner=runner)
        self.assertEqual(AdbDeviceSpec(serial="emulator-5554", game_pid=2247), device)
        self.assertEqual([], steps)
        self.assertIn(["reconnect", "offline"], calls)
        self.assertIn(["kill-server"], calls)
        self.assertIn(["start-server"], calls)

    def test_repaired_online_device_without_game_does_not_restart_adb_service(self):
        calls: list[list[str]] = []

        def runner(_adb, args, **_kwargs):
            calls.append(args)
            if args == ["devices"]:
                offline = b"List of devices attached\nemulator-5554\toffline\n"
                online = b"List of devices attached\nemulator-5554\tdevice\n"
                return _result(offline if calls.count(["devices"]) == 1 else online)
            return _result()

        with self.assertRaisesRegex(EmulatorNotFound, "未找到正在运行第七史诗"):
            discover_game_device(Path("adb.exe"), runner=runner)
        self.assertIn(["reconnect", "offline"], calls)
        self.assertNotIn(["kill-server"], calls)
        self.assertNotIn(["start-server"], calls)

    def test_empty_device_list_does_not_touch_adb_service(self):
        calls: list[list[str]] = []

        def runner(_adb, args, **_kwargs):
            calls.append(args)
            return _result(b"List of devices attached\n")

        with self.assertRaisesRegex(EmulatorNotFound, "未找到正在运行第七史诗"):
            discover_game_device(Path("adb.exe"), runner=runner)
        self.assertEqual([["devices"]], calls)

    def test_offline_devices_get_specific_hint(self):
        calls: list[list[str]] = []

        def runner(_adb, args, **_kwargs):
            calls.append(args)
            return _result(b"List of devices attached\nemulator-5554\toffline\n")

        with self.assertRaisesRegex(EmulatorNotFound, "offline") as caught:
            discover_game_device(Path("adb.exe"), runner=runner)
        self.assertIn("自动修复 ADB 连接 2 次仍未恢复", str(caught.exception))
        self.assertIn(["reconnect", "offline"], calls)
        self.assertIn(["kill-server"], calls)


class AdbEmulatorClientTests(unittest.TestCase):
    """命令构造与失败可见性 —— 全是标准 adb 命令，与品牌无关。"""

    def setUp(self):
        self.device = AdbDeviceSpec(serial="127.0.0.1:7555", game_pid=42)
        self.calls: list[list[str]] = []

    def _client(self, runner):
        return AdbEmulatorClient(
            Path("adb.exe"), self.device, runner=runner, sleep_fn=lambda _: None
        )

    def test_tap_uses_serial_and_render_coordinates(self):
        def runner(_adb, args, **_kwargs):
            self.calls.append(args)
            return _result()

        self._client(runner).tap(1790, 274)
        self.assertEqual(
            ["-s", "127.0.0.1:7555", "shell", "input", "tap", "1790", "274"],
            self.calls[0],
        )

    def test_swipe_and_back_use_standard_adb(self):
        def runner(_adb, args, **_kwargs):
            self.calls.append(args)
            return _result()

        client = self._client(runner)
        client.swipe(1300, 798, 1300, 168, 500)
        client.back()
        self.assertEqual(
            ["-s", "127.0.0.1:7555", "shell", "input", "swipe", "1300", "798", "1300", "168", "500"],
            self.calls[0],
        )
        self.assertEqual(
            ["-s", "127.0.0.1:7555", "shell", "input", "keyevent", "4"],
            self.calls[1],
        )

    def test_tap_surfaces_dead_channel_even_with_zero_exit_code(self):
        def runner(_adb, args, **_kwargs):
            return _result(stdout=b"adb.exe: device offline\n", returncode=0)

        with self.assertRaisesRegex(RuntimeError, "未送达游戏"):
            self._client(runner).tap(100, 100)

    def test_healthy_channel_is_not_false_positive(self):
        self._client(lambda _adb, _args, **_kw: _result()).tap(100, 100)

    def test_capture_retries_then_succeeds(self):
        good = _png_bytes()
        responses = [_result(stdout=b"bad"), _result(stdout=good)]

        def runner(_adb, args, **_kwargs):
            return responses.pop(0)

        frame = self._client(runner).screencap_bgr()
        self.assertEqual((1080, 1920, 3), frame.shape)

    def test_capture_fails_loudly_after_all_attempts(self):
        with self.assertRaisesRegex(RuntimeError, "连续 3 次取不到画面"):
            self._client(lambda _a, _args, **_kw: _result(stdout=b"bad")).screencap_bgr()

    def test_raw_command_supports_pull_for_portrait_channel(self):
        def runner(_adb, args, **_kwargs):
            self.calls.append(args)
            return _result()

        self._client(runner).run_raw("pull /sdcard/a.png C:/tmp/a.png")
        self.assertEqual(
            ["-s", "127.0.0.1:7555", "pull", "/sdcard/a.png", "C:/tmp/a.png"],
            self.calls[0],
        )


class UnifiedWindowTests(unittest.TestCase):
    """Epic7Window 就是统一后端：画布、坐标、接口与历史完全一致。"""

    def setUp(self):
        self.device = AdbDeviceSpec(serial="s", game_pid=1)
        self.client = AdbEmulatorClient(
            Path("adb.exe"),
            self.device,
            runner=lambda _adb, _args, **_kw: _result(stdout=_png_bytes()),
            sleep_fn=lambda _: None,
        )
        self.window = Epic7Window(client=self.client)

    def test_canvas_is_1982x1132_with_52px_top_margin(self):
        frame = np.full((1080, 1920, 3), 130, dtype=np.uint8)
        with patch.object(self.client, "capture_render", return_value=frame):
            canvas = self.window.capture()
        self.assertEqual((1132, 1982, 3), canvas.shape)
        self.assertTrue(np.all(canvas[:52] == 0))

    def test_click_subtracts_legacy_top(self):
        with patch.object(self.client, "tap") as tap:
            self.window.click((1790, 326))
        tap.assert_called_once_with(1790, 274)

    def test_click_rejects_chrome_coordinates(self):
        with self.assertRaisesRegex(RuntimeError, "渲染区外"):
            self.window.click((10, 20))

    def test_swipe_subtracts_legacy_top(self):
        with patch.object(self.client, "swipe") as swipe:
            self.window.swipe((1300, 850), (1300, 220), 500)
        swipe.assert_called_once_with(1300, 798, 1300, 168, 500)

    def test_process_id_is_the_game_pid(self):
        self.assertEqual(1, self.window.process_id())

    def test_activate_is_a_no_op(self):
        # ADB 注入不需要前台焦点 —— 所有模拟器一视同仁。
        self.assertIsNone(self.window.activate())


if __name__ == "__main__":
    unittest.main()
