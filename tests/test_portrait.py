"""竖屏通道（``core/portrait.py``）的离线验收。

## 为什么要有这个文件（2026-10-07）

这条通道此前**零测试覆盖** —— 而真机实跑在它上面崩了两次：

- 10:51 抛裸 ``RuntimeError``（上层兜底只接 ``OrientationError``）⇒ 整条路线崩；
- 12:45「窗口已转竖屏、但安卓侧画面还没切成 1080x1920」被当成异常 ⇒ 上层
  「退回横屏」⇒ 拿竖屏图撞横屏模板 ⇒ 主循环 3 秒后进失败收尾，
  **把刚打开的社区又关掉了**（日志 12:45:02 点入口 → 12:45:05 收尾）。

两件事都不是「业务判据」的问题，而是**通道层的时序**，所以只能在这一层测。
"""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from auto_game_unified.core import portrait as portrait_module
from auto_game_unified.core.portrait import (
    PORTRAIT_CANVAS,
    OrientationError,
    PortraitChannel,
)


class _FakeWindow:
    """只提供 ``instance_channel``（``PortraitChannel`` 唯一用到的窗口能力）。"""

    def __init__(self) -> None:
        self.channel = ("C:/ldconsole.exe", "0", 12345)

    def instance_channel(self):
        return self.channel


def _bgr(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), 90, np.uint8)


class _SizedPortrait(PortraitChannel):
    """只按预设序列回答 ``client_size`` 的替身（绕开 ``__init__``，不碰 Win32）。"""

    def __init__(self, sizes) -> None:
        self._window = None
        self._sleep = lambda _: None
        self._orientation_timeout = 0.0
        self._sizes = list(sizes)
        self._emit = lambda _: None
        self.probes = 0

    def client_size(self):
        self.probes += 1
        return self._sizes.pop(0) if len(self._sizes) > 1 else self._sizes[0]


class _PortraitShapes(PortraitChannel):
    """把 ``_screencap`` 换成「按预设序列吐不同画幅」的替身。

    ⚠️ 方向（``client_size``）与画幅（``_screencap``）**分开替换**是刻意的：
    这两件事在真机上就是**两步**，12:45 那次崩的正是它们的**错位窗口**
    （方向已竖、画面还是横）。测试必须能造出这个错位，否则测不到真 bug。
    """

    def __init__(self, *, sizes, sleep=None) -> None:
        self._window = _FakeWindow()
        self._sleep = sleep if sleep is not None else (lambda _: None)
        self._adb_timeout = 20.0
        self._orientation_timeout = 20.0
        self._shot_path = Path("unused.png")
        self._event_sink = None
        self._shots: list[np.ndarray] = [_bgr(w, h) for w, h in sizes]
        self.screencaps = 0

    def client_size(self):
        return PORTRAIT_CANVAS  # 方向永远已经对：这里只测画幅那一段

    def _screencap(self):
        self.screencaps += 1
        return self._shots.pop(0) if len(self._shots) > 1 else self._shots[0]


class PortraitCanvasSettleTests(unittest.TestCase):
    """「方向已转、画幅未跟上」必须**继续等**，不能报错。"""

    def make_channel(self, *, sizes, sleep=None) -> _PortraitShapes:
        """``sizes`` 是每次取图返回的 ``(宽, 高)`` 序列（用完重复最后一个）。"""
        channel = _PortraitShapes(sizes=sizes, sleep=sleep)
        self.emitted: list[str] = []
        channel._emit = self.emitted.append
        return channel

    def test_waits_for_the_canvas_instead_of_failing_at_once(self):
        """⚠️ 这是 12:45 那次实跑失败的**原样复现**。

        窗口已转成竖屏（``wait_for_portrait`` 秒过），但安卓侧画面还没切完
        —— 第一次取图仍是 1920x1080。旧代码直接抛异常，上层兜底「退回横屏」，
        而那一刻窗口**已经是竖屏**了 ⇒ 主循环判不出页面 ⇒ 3 秒后收尾 ⇒
        **把刚打开的社区关掉**。
        """
        channel = self.make_channel(sizes=[(1920, 1080), (1080, 1920)])
        frame = channel.capture()
        self.assertEqual(
            (PORTRAIT_CANVAS[1], PORTRAIT_CANVAS[0], 3),
            tuple(frame.shape),
            "画幅跟上之后应当返回 1080x1920",
        )
        self.assertTrue(
            any("画幅还没跟上" in line for line in self.emitted),
            f"应当记一笔「画幅还没跟上、等」：{self.emitted}",
        )

    def test_survives_several_stale_frames(self):
        """连着几帧都是旧画幅也要熬过去（转屏动画可能比一帧长）。"""
        channel = self.make_channel(
            sizes=[(1920, 1080), (1920, 1080), (1920, 1080), (1080, 1920)]
        )
        frame = channel.capture()
        self.assertEqual((PORTRAIT_CANVAS[1], PORTRAIT_CANVAS[0], 3), tuple(frame.shape))

    def test_reports_orientation_error_after_the_settle_budget_is_spent(self):
        """熬完仍不对 ⇒ 抛 ``OrientationError``（**不是**裸 RuntimeError）。

        ⚠️ 类型必须对：上层 ``attach_dual_channel`` 的兜底与那条
        ``test_portrait_capture_reports_a_wrong_size_as_an_orientation_error``
        都只接这一种。
        """
        channel = self.make_channel(sizes=[(1920, 1080)])
        with self.assertRaises(OrientationError) as ctx:
            channel.capture()
        self.assertIn("1080x1920", str(ctx.exception))

    def test_a_picture_that_is_neither_landscape_nor_portrait_also_reports_orientation(self):
        """别的尺寸（社区页关掉、方向又转回去）走同一条路，不静默返回错帧。"""
        channel = self.make_channel(sizes=[(720, 1280)])
        with self.assertRaises(OrientationError):
            channel.capture()

    def test_settle_budget_is_bounded(self):
        """等待预算是**常量且有限**的 —— 不是死循环。"""
        self.assertGreater(portrait_module._CANVAS_SETTLE_ATTEMPTS, 0)
        self.assertLessEqual(
            portrait_module._CANVAS_SETTLE_ATTEMPTS * portrait_module._CANVAS_SETTLE_SECONDS,
            10.0,
            "画幅等待预算超过 10 秒会把「转屏慢」拖成「路线卡住」",
        )

    def test_a_frame_that_is_never_ready_stops_pulling_at_the_budget(self):
        """熬完预算 ⇒ **停止取图**（别在坏状态里无限 screencap）。"""
        channel = self.make_channel(sizes=[(1920, 1080)])
        with self.assertRaises(OrientationError):
            channel.capture()
        self.assertEqual(
            portrait_module._CANVAS_SETTLE_ATTEMPTS,
            channel.screencaps,
            "取图次数必须正好等于预算，最后一次不该再睡",
        )


class PortraitWaitTests(unittest.TestCase):
    """方向判据本身：只看宽高比。"""

    def test_portrait_is_width_smaller_than_height(self):
        self.assertTrue(_SizedPortrait([(1103, 1899)]).is_portrait())

    def test_landscape_is_width_greater_than_height(self):
        self.assertFalse(_SizedPortrait([(1920, 1080)]).is_portrait())

    def test_wait_returns_at_once_when_already_there(self):
        """已经是对的方向 ⇒ **一帧都不等**（别白花 0.25 秒）。"""
        channel = _SizedPortrait([(1103, 1899)])
        channel.wait_for_portrait()
        self.assertEqual(1, channel.probes)

    def test_wait_gives_up_when_the_direction_never_flips(self):
        """方向一直不对 ⇒ 超时抛 ``OrientationError``，并带上实际尺寸。"""
        channel = _SizedPortrait([(1920, 1080)])
        channel._orientation_timeout = 0.5
        with self.assertRaises(OrientationError) as ctx:
            channel.wait_for_portrait()
        self.assertIn("1920x1080", str(ctx.exception))


class PortraitInputTests(unittest.TestCase):
    """点击坐标就是画布坐标，且画布外一律拒绝。"""

    def make(self):
        channel = PortraitChannel(window=_FakeWindow(), sleep=lambda _: None)
        sent: list[str] = []
        channel._run_adb = sent.append
        return channel, sent

    def test_click_uses_the_canvas_coordinates_directly(self):
        channel, sent = self.make()
        channel.click((539, 1665))
        self.assertEqual(["shell input tap 539 1665"], sent)

    def test_refuses_a_click_outside_the_canvas(self):
        """横屏坐标误传进来必须当场拒绝（竖屏画布只有 1080 宽）。"""
        channel, sent = self.make()
        with self.assertRaises(RuntimeError):
            channel.click((1740, 260))
        self.assertEqual([], sent, "越界点击不该发出去")


class _FakeAdbClient:
    """只提供 ``screencap_bgr``：**故意不给** ``run_raw``。

    回归用途（2026-11-24）：竖屏取图不许再回到
    「``shell screencap -p <设备路径>`` + ``pull <设备路径> <本地路径>``」那条老路 ——
    命令字符串由 ``run_raw`` 的 ``shlex.split`` 解析，反斜杠被当转义符吃掉
    （``D:\\Cache\\Temp\\x.png`` → ``D:CacheTempx.png``），``pull`` 把图写到别处，
    ``cv2.imread`` 读到的**永远是那份不再更新的旧文件**，且 adb 返回 0、一点错误都不报。
    实测后果：整条社区签到路线每一帧都判成同一张旧图（判页 1.0000、点击全按旧页算）。

    这里一旦有人改回老写法，本替身没有 ``run_raw`` ⇒ 当场 AttributeError。
    """

    def __init__(self, frame: np.ndarray) -> None:
        self.frame = frame
        self.calls = 0

    def screencap_bgr(self) -> np.ndarray:
        self.calls += 1
        return self.frame


class _FakeAdbWindow:
    def __init__(self, client: _FakeAdbClient) -> None:
        self.adb_client = client


class PortraitScreencapSourceTests(unittest.TestCase):
    """竖屏取图必须走 ``exec-out``，不许落设备文件。"""

    def test_screencap_comes_from_the_live_channel(self):
        frame = _bgr(*PORTRAIT_CANVAS)
        client = _FakeAdbClient(frame)
        channel = PortraitChannel(window=_FakeAdbWindow(client), sleep=lambda _: None)
        self.assertIs(channel._screencap(), frame)
        self.assertEqual(1, client.calls)


if __name__ == "__main__":
    unittest.main()
