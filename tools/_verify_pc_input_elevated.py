import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
from time import sleep

import cv2
import pyautogui

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pc_window import Epic7PcWindow


status = ROOT / "runtime_logs" / "hero_pc_step.txt"


def capture(window: Epic7PcWindow, name: str) -> None:
    image = window.capture()
    output = ROOT / "runtime_diagnostics" / "hero_capture" / name
    output.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(output), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))


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


def send_input_click(point: tuple[int, int]) -> None:
    user32 = ctypes.windll.user32
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    x, y = point
    move = _MouseInput(
        round(x * 65535 / (width - 1)),
        round(y * 65535 / (height - 1)),
        0,
        0x0001 | 0x8000,
        0,
        0,
    )
    down = _MouseInput(0, 0, 0, 0x0002, 0, 0)
    up = _MouseInput(0, 0, 0, 0x0004, 0, 0)
    inputs = (_Input * 3)(
        _Input(0, _InputUnion(mouse=move)),
        _Input(0, _InputUnion(mouse=down)),
        _Input(0, _InputUnion(mouse=up)),
    )
    if user32.SendInput(3, inputs, ctypes.sizeof(_Input)) != 3:
        raise ctypes.WinError(ctypes.get_last_error())


try:
    status.write_text("started\n", encoding="utf-8")
    window = Epic7PcWindow()
    window.click((1612, 141))
    sleep(4)
    capture(window, "23_live_filter_open_before_star3.png")
    status.write_text("filter_open_captured\n", encoding="utf-8")
    rect = window._rect()
    star_point = (
        rect.left + round(1148 * rect.width / window.reference_size[0]),
        rect.top + round(613 * rect.height / window.reference_size[1]),
    )
    send_input_click(star_point)
    with status.open("a", encoding="utf-8") as stream:
        stream.write(f"mouse_after_star3={pyautogui.position()} point={star_point}\n")
    sleep(0.2)
    capture(window, "24_live_star3_after_0_2s.png")
    sleep(0.8)
    capture(window, "25_live_star3_after_1s.png")
    sleep(2)
    capture(window, "26_live_star3_after_3s.png")
    with status.open("a", encoding="utf-8") as stream:
        stream.write("star3_click_captured\n")
except Exception as error:
    status.write_text(f"error={type(error).__name__}: {error}\n", encoding="utf-8")
    raise
