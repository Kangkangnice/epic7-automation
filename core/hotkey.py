"""Windows global stop hotkey used by live automation."""

import ctypes
import time
from typing import Callable

#: 全局停止键：**长按 P**。
#
# 这个键位只有这一处定义。2026-11-09 起「实用工具 · 连点器」的急停也用同一个键
# （见 ``core/autoclicker.py``）—— 两者永远不会同时运行（界面互斥），所以不冲突，
# 而且对用户是同一句口诀：**长按 P 就停**（避免平时打字误触）。
STOP_KEY_VK = 0x50
STOP_HOLD_SECONDS = 0.8


class WindowsPStopHotkey:
    """Report once when the global P key is held for at least ``hold_seconds``."""

    _VK_P = STOP_KEY_VK

    def __init__(
        self,
        get_key_state: Callable[[int], int] | None = None,
        *,
        hold_seconds: float = STOP_HOLD_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_key_state = get_key_state or ctypes.windll.user32.GetAsyncKeyState
        self._hold_seconds = max(0.0, float(hold_seconds))
        self._monotonic = monotonic
        self._pressed_since: float | None = None
        self._fired = False

    def pressed(self) -> bool:
        is_down = bool(self._get_key_state(self._VK_P) & 0x8000)
        if not is_down:
            self._pressed_since = None
            self._fired = False
            return False
        now = self._monotonic()
        if self._pressed_since is None:
            self._pressed_since = now
            if self._hold_seconds > 0.0:
                return False
        if self._fired:
            return False
        if now - self._pressed_since >= self._hold_seconds:
            self._fired = True
            return True
        return False
