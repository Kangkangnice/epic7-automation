"""固定位置连点器：鼠标停在一个点上，按固定间隔一直点。

## 它不是什么

它**不是**一条自动化路线：不认识画面、不判断点到了什么、不做事后校验。
你给它一个屏幕坐标和一个间隔，它就在那里点，直到按 P 或者点界面上的「停止」。
所以「点错地方」这件事它自己防不住 —— 这是它和 ``games/epic7/`` 里那些路线的
本质区别，也是它被放在「实用工具」而不是「每日任务」里的原因。

## 为什么直接调 Win32，不用 pyautogui

两个理由：

1. **坐标口径只能有一套**。Qt 6 的 ``QCursor.pos()`` 给的是**逻辑像素**
   （受系统缩放影响），而 ``SetCursorPos`` / ``GetCursorPos`` 要的是**物理像素**。
   125% 缩放的机器上两者差 1.25 倍，表现就是「拾取的是这里、点的是那里」。
   这里取点与点击都走 Win32，同一套坐标，不经过 Qt 也不经过 pyautogui。
2. pyautogui 自带全局 ``PAUSE``（默认 0.1 秒）与额外的状态检查。连点器要的是
   「间隔由用户定、不许偷偷加料」。

## 安全设计（改这个文件前必读）

* **P 是急停，只在运行中有效**。连点一开，鼠标就被按在目标点上，用户点不到
  界面上的「停止」—— 所以必须有一个不依赖鼠标的出口。反过来，P **不能**用来
  启动：那样在别的页面误按一下就会开始在屏幕上乱点。
* **停止必须在 50 毫秒内生效**。等待不是一整段 ``sleep(间隔)``，而是 50 毫秒
  一片地等 —— 用户把间隔填成 30 秒时，按 P 也要立刻停。
* **点击抛异常就让线程退出，并把原因留下来**。静默继续点比停下来更糟：
  界面会显示「正在连点」，而屏幕上其实什么都没发生。

## P 的代价

这里用 ``GetAsyncKeyState`` 轮询，**不注册**全局热键。注册会把 P 从系统层面
吞掉（别处就按不到了），注册失败还得另设一条退路；轮询没有任何失败模式。
代价有两个：运行中按 P，游戏也会收到这个键；而且 P 是普通字母键，连点期间
你在别处打字打到 P 也会立刻停住 —— 后者其实正合急停的本意，不用管。
"""

from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass
from typing import Callable

from auto_game_unified.core.hotkey import STOP_KEY_VK

# 间隔的可用范围。下限 50 毫秒（每秒 20 次）是刻意留的：
# 再快就轮到游戏掉帧、点击被消息队列合并，用户看到的是「点了但没生效」。
MIN_INTERVAL_MS = 50
# 上限一小时。这不是「精度上限」，只是别让手滑输入一个天文数字后等一年。
MAX_INTERVAL_MS = 3_600_000

# winuser.h
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

# 等待切片长度：决定「按下 P 之后最多多久停」。
_SLICE_SECONDS = 0.05

_user32_cache: object | None = None


def _user32():
    """懒加载 user32 并一次性设好签名。

    **不在模块顶层加载**：这个模块的测试可以在任何平台上 import（点击函数是
    注入的），顶层加载会让非 Windows 环境连 import 都失败。
    签名必须显式写：64 位下 ``GetCursorPos`` 的指针参数用默认的 ``c_int`` 会被
    截断成 32 位，表现是偶发的「取点取到一个奇怪的坐标」。
    """
    global _user32_cache
    if _user32_cache is not None:
        return _user32_cache

    from ctypes import wintypes

    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    lib.GetCursorPos.restype = wintypes.BOOL
    lib.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.SetCursorPos.restype = wintypes.BOOL
    lib.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    lib.mouse_event.restype = None
    lib.GetAsyncKeyState.argtypes = [ctypes.c_int]
    lib.GetAsyncKeyState.restype = ctypes.c_short
    _user32_cache = lib
    return lib


def cursor_position() -> tuple[int, int]:
    """当前光标的坐标 —— **物理像素**，虚拟桌面坐标系（副屏可以是负数）。"""
    from ctypes import wintypes

    point = wintypes.POINT()
    if not _user32().GetCursorPos(ctypes.byref(point)):
        raise OSError("读不到鼠标位置（GetCursorPos 失败）")
    return int(point.x), int(point.y)


def click_at(x: int, y: int) -> None:
    """把光标挪到 (x, y) 并左键单击一次。

    先 ``SetCursorPos`` 再发按键：这样无论用户刚才把鼠标挪到哪，点击都落在
    同一个点上。副作用是运行期间鼠标会被「拽住」—— 这正是固定点连点的定义。
    """
    user32 = _user32()
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def emergency_hotkey_pressed() -> bool:
    """急停键（P）是否**正被按住**。只在连点线程里调用 —— 别接到常驻循环上。

    键位与自动化的全局停止键是同一个（``core/hotkey.py::STOP_KEY_VK``）：
    对用户就一句口诀「按 P 就停」，两种运行不会同时存在（界面互斥）。
    """
    return bool(_user32().GetAsyncKeyState(STOP_KEY_VK) & 0x8000)


@dataclass(frozen=True)
class ClickPlan:
    """一次连点任务的全部参数。校验放在这里：界面、脚本、测试都走同一个入口。"""

    x: int
    y: int
    interval_ms: int

    def __post_init__(self) -> None:
        if not MIN_INTERVAL_MS <= int(self.interval_ms) <= MAX_INTERVAL_MS:
            raise ValueError(
                f"间隔要在 {MIN_INTERVAL_MS}~{MAX_INTERVAL_MS} 毫秒之间，"
                f"收到 {self.interval_ms}"
            )


class AutoClicker:
    """一个可以反复启停的连点线程。**同一时刻只允许一个**。"""

    def __init__(
        self,
        *,
        click: Callable[[int, int], None] = click_at,
        hotkey: Callable[[], bool] = emergency_hotkey_pressed,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._click = click
        self._hotkey = hotkey
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._count = 0
        self._error: str | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def count(self) -> int:
        """已经点出去的次数。只有一个写者（连点线程），读到旧值不影响使用。"""
        return self._count

    @property
    def last_error(self) -> str | None:
        """上一次运行异常退出的原因；正常停止或没跑过是 ``None``。"""
        return self._error

    def start(self, plan: ClickPlan) -> None:
        if self.running:
            raise RuntimeError("连点器已经在运行了")
        self._stop.clear()
        self._count = 0
        self._error = None
        self._thread = threading.Thread(
            target=self._loop,
            args=(plan,),
            name="epic7-autoclicker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """请求停止。真正的退出在下一个 50 毫秒切片内发生。"""
        self._stop.set()

    def _loop(self, plan: ClickPlan) -> None:
        interval = plan.interval_ms / 1000.0
        deadline = self._clock()
        try:
            while not self._stop.is_set():
                if self._hotkey():
                    break
                self._click(plan.x, plan.y)
                self._count += 1
                deadline += interval
                now = self._clock()
                if deadline < now:
                    # 落后超过一个间隔（机器卡了一下）：从现在重新起算，
                    # 不要为了"补进度"连点一串 —— 那会让间隔突然变得很密。
                    deadline = now
                while not self._stop.is_set():
                    now = self._clock()
                    if now >= deadline:
                        break
                    if self._stop.wait(min(_SLICE_SECONDS, deadline - now)):
                        break
                    if self._hotkey():
                        self._stop.set()
                        break
        except Exception as error:  # noqa: BLE001 —— 记下来给界面，别让线程无声死掉
            self._error = str(error) or error.__class__.__name__
