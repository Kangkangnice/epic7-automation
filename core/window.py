"""模拟器窗口：统一 ADB 后端，不认品牌。

## 一个后端适配所有安卓模拟器（2026-11-21 定案）

雷电、MuMu、夜神、BlueStacks……底层都是安卓，都讲标准 ADB。这里只有一条通道：
用 ADB 找出「正在跑第七史诗的那个设备」，抓图与输入全走 ADB。**代码里没有模拟器品牌
的概念** —— 新增任何模拟器都无需改代码，只要它是标准 ADB 的安卓模拟器。

对外接口（``capture / click / swipe / wake / back / activate / process_id /
ensure_input_channel / set_event_sink``）与改造前完全一致，上层（Runtime、导航、各路线、
竖屏通道、预检）一行都不用改。

画布与坐标沿用历史基准：抓 1920x1080 渲染帧，合成 1982x1132 画布（顶栏 52px 黑边），
点击时减掉这 52px。这样全库模板、判据、坐标都不用动。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from auto_game_unified.core.emulator_adb import (
    AdbDeviceSpec,
    AdbEmulatorClient,
    EmulatorNotFound,
    find_adb,
    discover_game_device,
)


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    width: int
    height: int


class WindowViewport:
    """桌面像素与游戏局部坐标的换算（保留给历史调用方）。"""

    def __init__(self, rect_provider: Callable[[], WindowRect]) -> None:
        self._rect_provider = rect_provider

    def rect(self) -> WindowRect:
        return self._rect_provider()

    def crop(self, desktop: np.ndarray) -> np.ndarray:
        rect = self.rect()
        return desktop[rect.top : rect.top + rect.height, rect.left : rect.left + rect.width].copy()

    def to_desktop(self, point: tuple[int, int]) -> tuple[int, int]:
        rect = self.rect()
        return rect.left + point[0], rect.top + point[1]

    def scale_for(self, reference_size: tuple[int, int]) -> tuple[float, float]:
        rect = self.rect()
        scale = rect.width / reference_size[0], rect.height / reference_size[1]
        if abs(scale[0] - scale[1]) > 0.02:
            raise RuntimeError(
                f"游戏窗口宽高比发生变化：{rect.width}x{rect.height}；"
                f"模板基准为 {reference_size[0]}x{reference_size[1]}"
            )
        return round(scale[0], 6), round(scale[1], 6)


class Epic7Window:
    """所有安卓模拟器的统一窗口对象（ADB 通道）。

    找设备、抓图、点击全走 ADB；不读窗口标题、不看进程名、不碰私有控制台。
    """

    _RENDER_SIZE = (1920, 1080)
    _LEGACY_SIZE = (1982, 1132)
    _LEGACY_TOP = 52

    def __init__(
        self,
        title: str = "第七史诗",
        *,
        adb_path: Path | None = None,
        device: AdbDeviceSpec | None = None,
        client: AdbEmulatorClient | None = None,
    ) -> None:
        # title 只为兼容历史调用签名保留，不参与任何判断。
        self.title = title
        self.viewport = WindowViewport(self._rect)
        if client is not None:
            self._client = client
        else:
            adb = adb_path or find_adb()
            chosen = device or discover_game_device(adb)
            self._client = AdbEmulatorClient(adb, chosen)
        self._event_sink: Callable[[str], None] | None = None

    def set_event_sink(self, sink: Callable[[str], None] | None) -> None:
        self._event_sink = sink

    def _emit(self, message: str) -> None:
        if self._event_sink is not None:
            self._event_sink(message)

    @property
    def adb_client(self) -> AdbEmulatorClient:
        """竖屏通道 ``PortraitChannel`` 用它执行 adb 命令。"""
        return self._client

    def description(self) -> str:
        return self._client.description()

    # ── 抓图 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _legacy_canvas(render: np.ndarray) -> np.ndarray:
        """把 1920x1080 渲染帧合成 1982x1132 画布（与历史完全一致）。"""
        if render.shape[:2] != (1080, 1920):
            raise RuntimeError(
                f"模拟器画面尺寸异常：{render.shape[1]}x{render.shape[0]}；应为 1920x1080"
            )
        canvas = np.zeros((1132, 1982, 3), dtype=np.uint8)
        canvas[52:, :1920] = render
        return canvas

    def capture(self) -> np.ndarray:
        # ⚠️ ADB 解码出来是 **BGR**（``capture_render`` 的 docstring 写明了），
        # 而本模块对外的画面契约是 **RGB**：``load_template`` 把模板转成 RGB、
        # ``Runtime.save_diagnostic`` 按 RGB→BGR 存盘、全库模板也都是同一口径。
        # 2026-11-22：直接透传 BGR 时，原样匹配整体掉分（橙金「进行任务」0.75 不过 0.80），
        # 同时诊断图被写反色 —— 看上去像「游戏换了配色」，实际是这里漏了一次转换。
        # 竖屏通道 ``portrait.py`` 早就转了（BGR2RGB），横屏这条与它对齐。
        render = cv2.cvtColor(self._client.capture_render(), cv2.COLOR_BGR2RGB)
        return self._legacy_canvas(render)

    def _rect(self) -> WindowRect:
        """渲染区矩形（ADB 后端不依赖桌面窗口位置）。"""
        return WindowRect(0, 0, self._RENDER_SIZE[0], self._RENDER_SIZE[1])

    # ── 输入 ────────────────────────────────────────────────────────────────

    def _to_render(self, point: tuple[int, int], action: str) -> tuple[int, int]:
        render_point = point[0], point[1] - self._LEGACY_TOP
        if not (
            0 <= render_point[0] < self._RENDER_SIZE[0]
            and 0 <= render_point[1] < self._RENDER_SIZE[1]
        ):
            raise RuntimeError(f"拒绝在安卓渲染区外{action}：{point}")
        return render_point

    def click(self, point: tuple[int, int]) -> None:
        x, y = self._to_render(point, "点击")
        self._client.tap(x, y)

    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        x1, y1 = self._to_render(start, "滑动")
        x2, y2 = self._to_render(end, "滑动")
        if duration_ms <= 0:
            raise ValueError("滑动时长必须大于 0")
        self._client.swipe(x1, y1, x2, y2, duration_ms)

    def wake(self, point: tuple[int, int]) -> None:
        """ADB 注入不需要真鼠标唤醒界面层，点击即可。"""
        self.click(point)

    def back(self) -> None:
        """安卓标准返回键。"""
        self._client.back()

    def activate(self) -> None:
        """ADB 是安卓内部注入，不依赖前台焦点，无需激活窗口。"""
        return None

    # ── 提权 / 自检 ─────────────────────────────────────────────────────────

    def process_id(self) -> int:
        """游戏进程 PID（提权提示用；ADB 注入不受 UIPI 限制，仅作信息）。"""
        return self._client.device.game_pid

    def ensure_input_channel(self) -> None:
        """探测输入通道，坏了重建 adb 服务再探；仍不通则显式报错。"""
        try:
            self._client.probe()
            self._emit("模拟器通道 状态=可用")
            return
        except (RuntimeError, OSError) as error:
            self._emit(f"模拟器通道 状态=探测失败 原因={error} 动作=重建连接服务")

        adb = self._client.adb
        for command in (["kill-server"], ["start-server"]):
            subprocess_run(adb, command)
        try:
            self._client.probe()
            self._emit("模拟器通道 状态=已恢复 动作=重建连接服务")
        except (RuntimeError, OSError) as error:
            raise RuntimeError(
                "模拟器输入通道一直没恢复：已尝试重建连接服务仍无响应。"
                "请关闭模拟器重新打开，等游戏回到大厅后重新开始"
                f"（底层信息：{error}）"
            ) from error


def subprocess_run(adb: Path, command: list[str]) -> None:
    """重建 adb 服务用：检查=False，失败由随后的一次探测判定。"""
    import subprocess

    subprocess.run(
        [str(adb), *command],
        check=False,
        capture_output=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


__all__ = [
    "EmulatorNotFound",
    "Epic7Window",
    "WindowRect",
    "WindowViewport",
]
