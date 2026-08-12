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
                f"game window aspect ratio changed: {rect.width}x{rect.height}; "
                f"expected the {reference_size[0]}x{reference_size[1]} template ratio"
            )
        return round(scale[0], 6), round(scale[1], 6)


class Epic7Window:
    """Capture and click only the uniquely titled Epic Seven window."""

    _UPDATED_TITLE = "\u96f7\u7535\u6a21\u62df\u5668"
    _RENDER_SIZE = (1920, 1080)
    _LEGACY_SIZE = (1982, 1132)
    _LEGACY_TOP = 52

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
            raise RuntimeError(f"expected one supported LDPlayer window, found {len(windows)}")
        window = windows[0]
        if window.isMinimized:
            raise RuntimeError(f"{window.title} window is minimized")
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
            if not self._wait_until_foreground(window._hWnd):
                raise
        else:
            if not self._wait_until_foreground(window._hWnd):
                raise RuntimeError(f"could not activate {window.title}")
        sleep(0.3)

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
        self.activate()
        _, _, bind_handle = self._instance_channel()
        rect = self._window_rect_from_handle(bind_handle)
        image = pyautogui.screenshot(region=(rect.left, rect.top, rect.width, rect.height))
        return self._legacy_canvas(np.asarray(image.convert("RGB")))

    def click(self, point: tuple[int, int]) -> None:
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
            raise RuntimeError(f"refusing wake outside Android render area: {point}")
        pyautogui.click(rect.left + render_point[0], rect.top + render_point[1])

    def _click_legacy(self, point: tuple[int, int]) -> None:
        render_point = point[0], point[1] - self._LEGACY_TOP
        if not (
            0 <= render_point[0] < self._RENDER_SIZE[0]
            and 0 <= render_point[1] < self._RENDER_SIZE[1]
        ):
            raise RuntimeError(f"refusing click outside Android render area: {point}")
        self._send_render_tap(render_point)

    def _send_render_tap(self, point: tuple[int, int]) -> None:
        console_path, _, _ = self._instance_channel()
        subprocess.run(
            [
                str(console_path.with_name("ld.exe")),
                "input", "tap", str(point[0]), str(point[1]),
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )

    @staticmethod
    def _window_rect_from_handle(handle: int) -> WindowRect:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise RuntimeError(f"could not read LDPlayer render window {handle}")
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
            raise RuntimeError(f"LDPlayer console not found next to {player_path}")
        listed = subprocess.run(
            [str(console_path), "list2"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        ).stdout
        for line in listed.splitlines():
            fields = line.split(",")
            if len(fields) > 5 and fields[5].strip() == str(process_id.value):
                return console_path, fields[0].strip(), int(fields[3].strip())
        raise RuntimeError(f"could not map LDPlayer PID {process_id.value} to an instance")

    def back(self) -> None:
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
        )
