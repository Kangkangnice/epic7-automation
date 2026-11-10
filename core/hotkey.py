"""Windows global stop hotkey used by live automation."""

import ctypes
from typing import Callable

#: 全局停止键：**P**。
#
# 这个键位只有这一处定义。2026-11-09 起「实用工具 · 连点器」的急停也用同一个键
# （见 ``core/autoclicker.py``）—— 两者永远不会同时运行（界面互斥），所以不冲突，
# 而且对用户是同一句口诀：**按 P 就停**。
STOP_KEY_VK = 0x50


class WindowsPStopHotkey:
    """Report each up-to-down edge of the global P key once."""

    _VK_P = STOP_KEY_VK

    def __init__(self, get_key_state: Callable[[int], int] | None = None) -> None:
        self._get_key_state = get_key_state or ctypes.windll.user32.GetAsyncKeyState
        self._was_down = False

    def pressed(self) -> bool:
        is_down = bool(self._get_key_state(self._VK_P) & 0x8000)
        pressed = is_down and not self._was_down
        self._was_down = is_down
        return pressed
