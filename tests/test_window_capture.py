"""模拟器窗口层验收（统一 ADB 后端）。

2026-11-21：后端从「雷电专属 ldconsole + PrintWindow」改为「统一 ADB，不认品牌」。
本文件保留两类测试：
1. 与后端无关的几何契约（WindowViewport / 画布合成 / 坐标换算）；
2. 关键安全不变量（失败必须可见、坐标越界拒绝、通道自检显式报错）。

被删掉的是「钉住雷电私有命令格式」的旧测试 —— 它们测的实现（ldconsole 命令、
PrintWindow、reboot 实例、最小化真窗口还原）在统一后端里已不存在；这些实现的等价
新测试在 test_emulator_adb.py。安全不变量一条不少地保留下来。
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from auto_game_unified.core.window import (
    Epic7Window,
    WindowRect,
    WindowViewport,
)


def _client(adb_path="D:/epic7/adb.exe", serial="emulator-5554", pid=4321):
    """造一个假 ADB client，让窗口层测试不碰真机。"""
    from auto_game_unified.core.emulator_adb import AdbDeviceSpec, AdbEmulatorClient

    device = AdbDeviceSpec(serial=serial, game_pid=pid)
    client = AdbEmulatorClient(
        Path(adb_path), device,
        runner=lambda *_a, **_kw: None,
        sleep_fn=lambda _: None,
    )
    return client


class WindowGeometryTests(unittest.TestCase):
    """纯几何换算，与后端无关。"""

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


class WindowInputSafetyTests(unittest.TestCase):
    """坐标越界必须拒绝 —— 这条不变量与品牌无关，任何后端都要守住。"""

    def setUp(self):
        self.client = _client()
        self.window = Epic7Window(client=self.client)

    def test_click_subtracts_the_52px_top_margin(self):
        with patch.object(self.client, "tap") as tap:
            self.window.click((1790, 326))
        tap.assert_called_once_with(1790, 274)

    def test_click_rejects_coordinates_outside_render_area(self):
        for point in ((10, 20), (1950, 500)):
            with self.subTest(point=point):
                with self.assertRaisesRegex(RuntimeError, "渲染区外点击"):
                    self.window.click(point)

    def test_swipe_is_converted_and_rejects_chrome_coordinates(self):
        with patch.object(self.client, "swipe") as swipe:
            self.window.swipe((1300, 850), (1300, 220), 500)
        swipe.assert_called_once_with(1300, 798, 1300, 168, 500)
        with self.assertRaisesRegex(RuntimeError, "渲染区外滑动"):
            self.window.swipe((1300, 20), (1300, 220), 500)

    def test_back_never_waits_for_foreground_focus(self):
        # ADB 注入不依赖前台；activate 是空操作，返回键不受焦点影响。
        with (
            patch.object(self.window, "activate", side_effect=AssertionError("must not activate")),
            patch.object(self.client, "back") as back,
        ):
            self.window.back()
        back.assert_called_once_with()

    def test_click_does_not_activate_the_window(self):
        with (
            patch.object(self.window, "activate", side_effect=AssertionError("must not activate")),
            patch.object(self.client, "tap"),
        ):
            self.window.click((1000, 600))

    def test_wake_is_a_plain_click(self):
        with patch.object(self.client, "tap") as tap:
            self.window.wake((1000, 600))
        tap.assert_called_once_with(1000, 548)


class WindowCaptureTests(unittest.TestCase):
    """抓图：黑屏是正常画面；调用失败重试后仍失败必须显式报错。"""

    def setUp(self):
        self.client = _client()
        self.window = Epic7Window(client=self.client)

    def test_black_frame_is_returned_not_treated_as_failure(self):
        black = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch.object(self.client, "capture_render", return_value=black) as capture:
            canvas = self.window.capture()
        capture.assert_called_once_with()
        self.assertEqual((1132, 1982, 3), canvas.shape)
        self.assertTrue(np.all(canvas == 0))

    def test_capture_returns_rgb_not_bgr(self):
        """画布必须是 **RGB**，不是 ADB 解码出来的 BGR。

        模板（`load_template` 转 RGB）、诊断存盘（`save_diagnostic` 按 RGB 转 BGR）
        与全库模板都是 RGB 口径。2026-11-22 这次直接透传 BGR，代价是原样匹配整体掉分：
        橙金「进行任务」0.7516 不过 0.80 阈值，主线在队伍页干等 45 秒后退出；
        同时诊断图被写成反色，看上去像「游戏换了配色」——查了半天才发现是这里。
        竖屏通道 `portrait.py` 早就有这一次转换，横屏这条与它对齐。
        """
        render = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # 按 ADB 的 BGR 含义摆：B=10、G=20、R=30
        render[:, :] = (10, 20, 30)
        with patch.object(self.client, "capture_render", return_value=render):
            canvas = self.window.capture()
        # 换回 RGB 之后，画布上这一点的三元组应为 (R, G, B) = (30, 20, 10)
        self.assertEqual((30, 20, 10), tuple(int(channel) for channel in canvas[100, 100]))

    def test_capture_surfaces_failure_instead_of_guessing(self):
        with (
            patch.object(
                self.client,
                "capture_render",
                side_effect=RuntimeError("连续 3 次取不到画面"),
            ),
            self.assertRaisesRegex(RuntimeError, "连续 3 次取不到画面"),
        ):
            self.window.capture()


class InputChannelSelfCheckTests(unittest.TestCase):
    """通道自检：正常只探一次；失败重建后必须再探；修不好显式报错并给指引。"""

    def setUp(self):
        self.client = _client()

    def test_healthy_channel_probes_once_without_rebuilding(self):
        calls = []
        with (
            patch.object(self.client, "probe", side_effect=lambda: calls.append("probe")),
            patch(
                "auto_game_unified.core.window.subprocess_run",
                side_effect=AssertionError("must not rebuild"),
            ),
        ):
            Epic7Window(client=self.client).ensure_input_channel()
        self.assertEqual(["probe"], calls)

    def test_offline_channel_is_rebuilt_and_reprobed(self):
        calls = []
        probes = [RuntimeError("device offline"), None]

        def probe():
            result = probes.pop(0)
            calls.append("probe")
            if result is not None:
                raise result

        with (
            patch.object(self.client, "probe", side_effect=probe),
            patch(
                "auto_game_unified.core.window.subprocess_run",
                side_effect=lambda _adb, cmd: calls.append(" ".join(cmd)),
            ),
        ):
            Epic7Window(client=self.client).ensure_input_channel()
        self.assertEqual(["probe", "kill-server", "start-server", "probe"], calls)

    def test_unrecoverable_channel_fails_loudly_with_next_step(self):
        messages = []
        window = Epic7Window(client=self.client)
        window.set_event_sink(messages.append)
        with (
            patch.object(self.client, "probe", side_effect=RuntimeError("offline")),
            patch("auto_game_unified.core.window.subprocess_run"),
            self.assertRaisesRegex(RuntimeError, "重新打开"),
        ):
            window.ensure_input_channel()
        joined = "\n".join(messages)
        self.assertIn("重建连接服务", joined)


if __name__ == "__main__":
    unittest.main()
