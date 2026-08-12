"""Windows global stop hotkey used by live automation."""

import ctypes
from typing import Callable


class WindowsPStopHotkey:
    """Report each up-to-down edge of the global P key once."""

    _VK_P = 0x50

    def __init__(self, get_key_state: Callable[[int], int] | None = None) -> None:
        self._get_key_state = get_key_state or ctypes.windll.user32.GetAsyncKeyState
        self._was_down = False

    def pressed(self) -> bool:
        is_down = bool(self._get_key_state(self._VK_P) & 0x8000)
        pressed = is_down and not self._was_down
        self._was_down = is_down
        return pressed
