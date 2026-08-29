"""Window capture and input for the Epic Seven PC client (GLFW/OpenGL).

The business layer uses the emulator's legacy 1982x1132 coordinate space.  The
real game content is 1920x1080 at x=0, y=52 inside that canvas; this backend
preserves those pixels without interpolation and translates clicks back to the
real client area.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
from dataclasses import dataclass
from time import sleep

import numpy as np
import psutil
import pyautogui


RENDER_SIZE = (1920, 1080)
REFERENCE_SIZE = (1982, 1132)
LEGACY_TOP = 52
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouse_data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mouse", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", _InputUnion)]


def _is_process_elevated(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    process = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        raise RuntimeError(f"无法检查进程 {pid} 的权限级别")
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            raise RuntimeError(f"无法读取进程 {pid} 的权限令牌")
        try:
            elevated = wintypes.DWORD()
            returned = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                token,
                _TOKEN_ELEVATION,
                ctypes.byref(elevated),
                ctypes.sizeof(elevated),
                ctypes.byref(returned),
            ):
                raise RuntimeError(f"无法读取进程 {pid} 的提升状态")
            return bool(elevated.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    width: int
    height: int


class Epic7PcWindow:
    """Capture and click the uniquely titled Epic Seven PC client window."""

    _TITLE = "第七史诗"
    _PROCESS_NAME = "epicseven.exe"
    # Sub-windows owned by the engine that must NOT be treated as the game canvas.
    _SUBWINDOW_MARKERS = ("_thread_", "GLFW message window", "GDI+ Window")

    def __init__(
        self,
        reference_size: tuple[int, int] = REFERENCE_SIZE,
    ) -> None:
        self.reference_size = reference_size
        self._user32 = ctypes.windll.user32

    # ---- window discovery -------------------------------------------------

    def _all_windows(self):
        owner = self._user32
        results = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _lparam):
            if not owner.IsWindowVisible(hwnd):
                return True
            length = owner.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                owner.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
            pid = ctypes.c_ulong()
            owner.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                name = psutil.Process(pid.value).name().lower()
            except Exception:
                name = ""
            results.append((hwnd, title, name))
            return True

        owner.EnumWindows(enum_cb, 0)
        return results

    def _find_window(self):
        matches = []
        for hwnd, title, name in self._all_windows():
            if name != self._PROCESS_NAME:
                continue
            if title != self._TITLE:
                continue
            if any(marker in title for marker in self._SUBWINDOW_MARKERS):
                continue
            matches.append(hwnd)
        if len(matches) != 1:
            raise RuntimeError(
                f"应恰好找到一个 Epic Seven PC 窗口，实际找到 {len(matches)} 个"
            )
        return matches[0]

    # ---- geometry ---------------------------------------------------------

    def _rect(self, hwnd=None) -> WindowRect:
        """Return the window's *client* area (game canvas only, no title bar).

        The emulator backend captures the Android render area without any OS chrome;
        we must match that convention so templates line up pixel-for-pixel.
        """
        if hwnd is None:
            hwnd = self._find_window()
        client = wintypes.RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(client)):
            raise RuntimeError("无法读取 Epic Seven PC 窗口客户区")
        point = wintypes.POINT(client.left, client.top)
        self._user32.ClientToScreen(hwnd, ctypes.byref(point))
        return WindowRect(
            point.x,
            point.y,
            client.right - client.left,
            client.bottom - client.top,
        )

    def activate(self):
        hwnd = self._find_window()
        if self._user32.GetForegroundWindow() == hwnd:
            return hwnd
        self._user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        self._user32.SetForegroundWindow(hwnd)
        for _ in range(10):
            if self._user32.GetForegroundWindow() == hwnd:
                return hwnd
            sleep(0.05)
        raise RuntimeError("PC 游戏窗口未能置前，已拒绝截图或输入")

    def _validated_rect(self, hwnd) -> WindowRect:
        rect = self._rect(hwnd)
        if rect.width <= 0 or rect.height <= 0:
            raise RuntimeError(f"PC 游戏窗口客户区无效：{rect.width}x{rect.height}")
        if (rect.width, rect.height) != RENDER_SIZE:
            raise RuntimeError(
                f"PC 游戏窗口客户区尺寸为 {rect.width}x{rect.height}；"
                f"预期 {RENDER_SIZE[0]}x{RENDER_SIZE[1]}，已拒绝截图或输入"
            )
        return rect

    def _ensure_input_allowed(self, hwnd) -> None:
        pid = ctypes.c_ulong()
        if not self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            raise RuntimeError("无法读取 PC 游戏窗口的进程标识")
        if _is_process_elevated(pid.value) and not _is_process_elevated(os.getpid()):
            raise RuntimeError(
                "PC 客户端以管理员权限运行，而当前自动化未提升权限；"
                "Windows 会拦截键鼠输入。请以相同权限级别重新启动两者。"
            )

    # ---- capture / input --------------------------------------------------

    @staticmethod
    def _legacy_canvas(render: np.ndarray) -> np.ndarray:
        if render.shape[:2] != (RENDER_SIZE[1], RENDER_SIZE[0]):
            raise RuntimeError(
                f"PC 游戏截图尺寸异常：{render.shape[1]}x{render.shape[0]}；"
                f"预期 {RENDER_SIZE[0]}x{RENDER_SIZE[1]}"
            )
        canvas = np.zeros(
            (REFERENCE_SIZE[1], REFERENCE_SIZE[0], 3), dtype=np.uint8
        )
        canvas[LEGACY_TOP:, : RENDER_SIZE[0]] = render
        return canvas

    def capture(self) -> np.ndarray:
        rect = self._validated_rect(self.activate())
        image = pyautogui.screenshot(
            region=(rect.left, rect.top, rect.width, rect.height)
        )
        frame = np.asarray(image.convert("RGB"))
        return self._legacy_canvas(frame)

    def click(self, point: tuple[int, int]) -> None:
        hwnd = self.activate()
        self._ensure_input_allowed(hwnd)
        rect = self._validated_rect(hwnd)
        render_point = point[0], point[1] - LEGACY_TOP
        if not (
            0 <= render_point[0] < RENDER_SIZE[0]
            and 0 <= render_point[1] < RENDER_SIZE[1]
        ):
            raise RuntimeError(f"拒绝在 PC 游戏渲染区外点击：{point}")
        self._send_click((rect.left + render_point[0], rect.top + render_point[1]))

    def _send_click(self, point: tuple[int, int]) -> None:
        """用 SendInput 注入 PC 点击，避免 mouse_event 在高 DPI 客户端错位。"""
        desktop_width = self._user32.GetSystemMetrics(0)
        desktop_height = self._user32.GetSystemMetrics(1)
        x, y = point
        move = _MouseInput(
            round(x * 65535 / (desktop_width - 1)),
            round(y * 65535 / (desktop_height - 1)),
            0,
            _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE,
            0,
            0,
        )
        down = _MouseInput(0, 0, 0, _MOUSEEVENTF_LEFTDOWN, 0, 0)
        up = _MouseInput(0, 0, 0, _MOUSEEVENTF_LEFTUP, 0, 0)
        inputs = (_Input * 3)(
            _Input(0, _InputUnion(mouse=move)),
            _Input(0, _InputUnion(mouse=down)),
            _Input(0, _InputUnion(mouse=up)),
        )
        if self._user32.SendInput(3, inputs, ctypes.sizeof(_Input)) != 3:
            raise ctypes.WinError(ctypes.get_last_error())

    def wake(self, point: tuple[int, int]) -> None:
        # PC client has no separate idle layer; a normal click dispatches through
        # the desktop mouse stack the same way.
        self.click(point)

    def back(self) -> None:
        hwnd = self.activate()
        self._ensure_input_allowed(hwnd)
        pyautogui.press("esc")
