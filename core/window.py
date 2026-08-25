"""Window-local capture and input for the Epic Seven emulator."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
from dataclasses import dataclass
from time import sleep
from typing import Callable

# pyautogui captures in physical pixels.  Set DPI awareness before importing it
# so the window rectangle and click coordinates use that exact same space.
ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
import psutil
import pyautogui
import pygetwindow


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 1),
    ]


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    width: int
    height: int


class WindowViewport:
    """Translate between desktop pixels and one game's local pixel space."""

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
    """Capture and click only the uniquely titled Epic Seven window."""

    _UPDATED_TITLE = "\u96f7\u7535\u6a21\u62df\u5668"
    _RENDER_SIZE = (1920, 1080)
    _LEGACY_SIZE = (1982, 1132)
    _LEGACY_TOP = 52
    _PW_RENDERFULLCONTENT = 0x00000002  # PrintWindow：含 DirectX 渲染内容

    def __init__(self, title: str = "第七史诗") -> None:
        self.title = title
        self.viewport = WindowViewport(self._rect)

    def _window(self):
        supported_titles = {self.title, self._UPDATED_TITLE}
        windows = [
            window
            for window in pygetwindow.getAllWindows()
            if window.title in supported_titles
            and self._window_process_name(window) == "dnplayer.exe"
        ]
        if len(windows) != 1:
            raise RuntimeError(f"应恰好找到一个支持的雷电模拟器窗口，实际找到 {len(windows)} 个")
        window = windows[0]
        if window.isMinimized:
            raise RuntimeError(f"窗口 {window.title} 处于最小化状态")
        return window

    @staticmethod
    def _window_process_name(window) -> str:
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(window._hWnd, ctypes.byref(process_id))
        return psutil.Process(process_id.value).name().lower()

    def _rect(self) -> WindowRect:
        window = self._window()
        return WindowRect(window.left, window.top, window.width, window.height)

    def activate(self) -> None:
        window = self._window()
        if window.isActive:
            return
        try:
            window.activate()
        except pygetwindow.PyGetWindowException:
            # pygetwindow's SetForegroundWindow can fail with a Windows
            # focus-lock error even when the window is visible. Taps go through
            # LDPlayer's instance channel (ldconsole) by index, so foreground
            # focus is not required for input — fall back instead of crashing.
            self._best_effort_activate(window._hWnd)
        if not self._wait_until_foreground(window._hWnd):
            self._best_effort_activate(window._hWnd)
        sleep(0.3)

    @staticmethod
    def _best_effort_activate(handle: int) -> None:
        try:
            ctypes.windll.user32.ShowWindow(handle, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(handle)
        except Exception:
            pass

    @staticmethod
    def _wait_until_foreground(handle: int, attempts: int = 10) -> bool:
        for _ in range(attempts):
            if ctypes.windll.user32.GetForegroundWindow() == handle:
                return True
            sleep(0.05)
        return False

    @staticmethod
    def _legacy_canvas(render: np.ndarray) -> np.ndarray:
        if render.shape[:2] != (1080, 1920):
            raise RuntimeError(
                f"LDPlayer render size changed: {render.shape[1]}x{render.shape[0]}; "
                "expected 1920x1080"
            )
        canvas = np.zeros((1132, 1982, 3), dtype=np.uint8)
        canvas[52:, :1920] = render
        return canvas

    def capture(self) -> np.ndarray:
        _, _, bind_handle = self._instance_channel()
        render = self._print_window_render(bind_handle)
        if render is not None:
            return self._legacy_canvas(render)
        # 窗口级截图不可用（老系统/驱动不支持）时回退屏幕截图，
        # 该路径要求模拟器置前，被遮挡会截到其他窗口内容。
        self.activate()
        rect = self._window_rect_from_handle(bind_handle)
        image = pyautogui.screenshot(region=(rect.left, rect.top, rect.width, rect.height))
        return self._legacy_canvas(np.asarray(image.convert("RGB")))

    def _print_window_render(self, handle: int) -> np.ndarray | None:
        """窗口级截图：模拟器被遮挡/失焦时仍能取到正确画面。

        返回 None 表示窗口级截图不可用（失败或全黑），调用方回退屏幕截图。
        """
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        rect = wintypes.RECT()
        if not user32.GetClientRect(handle, ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if (width, height) != self._RENDER_SIZE:
            return None
        hwnd_dc = user32.GetDC(handle)
        if not hwnd_dc:
            return None
        try:
            mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
            if not mem_dc:
                return None
            try:
                bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
                if not bitmap:
                    return None
                try:
                    gdi32.SelectObject(mem_dc, bitmap)
                    if not user32.PrintWindow(handle, mem_dc, self._PW_RENDERFULLCONTENT):
                        return None
                    info = _BITMAPINFO()
                    info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                    info.bmiHeader.biWidth = width
                    info.bmiHeader.biHeight = -height  # top-down
                    info.bmiHeader.biPlanes = 1
                    info.bmiHeader.biBitCount = 32
                    buffer = ctypes.create_string_buffer(width * height * 4)
                    if not gdi32.GetDIBits(
                        mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
                    ):
                        return None
                finally:
                    gdi32.DeleteObject(bitmap)
            finally:
                gdi32.DeleteDC(mem_dc)
        finally:
            user32.ReleaseDC(handle, hwnd_dc)
        render = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
        rgb = np.ascontiguousarray(render[:, :, :3][:, :, ::-1])
        if rgb.std() < 1.0:  # 全黑/纯色画面：PrintWindow 对该窗口无效
            return None
        return rgb

    def click(self, point: tuple[int, int]) -> None:
        # ld.exe 通过实例通道发送点击，不依赖前台焦点；先直接发送，避免
        # Windows 焦点锁导致 activate 长时间卡住。只有实例通道失败时才尝试激活。
        try:
            self._click_legacy(point)
        except (RuntimeError, subprocess.SubprocessError):
            self.activate()
            self._click_legacy(point)

    def wake(self, point: tuple[int, int]) -> None:
        """Wake LDPlayer's campfire idle layer with a real desktop mouse event."""

        self.activate()
        _, _, bind_handle = self._instance_channel()
        rect = self._window_rect_from_handle(bind_handle)
        render_point = point[0], point[1] - self._LEGACY_TOP
        if not (
            0 <= render_point[0] < self._RENDER_SIZE[0]
            and 0 <= render_point[1] < self._RENDER_SIZE[1]
        ):
            raise RuntimeError(f"拒绝在安卓渲染区外唤醒：{point}")
        pyautogui.click(rect.left + render_point[0], rect.top + render_point[1])

    def _click_legacy(self, point: tuple[int, int]) -> None:
        render_point = point[0], point[1] - self._LEGACY_TOP
        if not (
            0 <= render_point[0] < self._RENDER_SIZE[0]
            and 0 <= render_point[1] < self._RENDER_SIZE[1]
        ):
            raise RuntimeError(f"拒绝在安卓渲染区外点击：{point}")
        self._send_render_tap(render_point)

    def _send_render_tap(self, point: tuple[int, int]) -> None:
        console_path, instance_index, _ = self._instance_channel()
        subprocess.run(
            [
                str(console_path),
                "adb", "--index", instance_index,
                "--command", f"shell input tap {point[0]} {point[1]}",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @staticmethod
    def _window_rect_from_handle(handle: int) -> WindowRect:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise RuntimeError(f"无法读取雷电模拟器渲染窗口 {handle}")
        return WindowRect(
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        )

    def _instance_channel(self) -> tuple[Path, str, int]:
        window = self._window()
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(window._hWnd, ctypes.byref(process_id))
        player_path = Path(psutil.Process(process_id.value).exe())
        console_path = player_path.with_name("ldconsole.exe")
        if not console_path.exists():
            raise RuntimeError(f"未在 {player_path} 旁找到雷电模拟器控制台")
        listed = subprocess.run(
            [str(console_path), "list2"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        for line in listed.splitlines():
            fields = line.split(",")
            if len(fields) > 5 and fields[5].strip() == str(process_id.value):
                return console_path, fields[0].strip(), int(fields[3].strip())
        raise RuntimeError(f"无法将雷电模拟器进程 {process_id.value} 对应到实例")

    def back(self) -> None:
        try:
            self._send_android_back()
        except (RuntimeError, subprocess.SubprocessError):
            self.activate()
            self._send_android_back()

    def _send_android_back(self) -> None:
        """Use LDPlayer's instance channel; keyboard Esc can be stolen by keymaps."""

        console_path, instance_index, _ = self._instance_channel()
        subprocess.run(
            [
                str(console_path), "action", "--index", instance_index,
                "--key", "call.keyboard", "--value", "back",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
