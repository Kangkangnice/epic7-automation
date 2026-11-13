"""判断「对方窗口的进程权限比本程序高」—— 那种情况下点击会被系统静默拦掉。

## 为什么需要它

Windows 的 UIPI（用户界面特权隔离）规定：**权限低的进程不能往权限高的窗口发输入**。
所以如果雷电模拟器是以管理员身份启动的、而助手不是，会出现一种很迷惑的现象 ——

    截图正常、识别正常、日志里每个动作都说「已点击」，但游戏一动不动。

排查这类问题过去要靠人猜（改分辨率？模板过期？点击坐标错了？），而真正的原因既
不在模板也不在坐标。与其让用户来问，不如在环境检测这一步就把它认出来并说清楚。

## 判据（不是「大概像」）

1. 拿目标窗口所属进程的 PID；
2. 读该进程令牌里的 `TokenElevation`（**不是**看进程名、也不是看用户名）；
3. 自己也是提权的 ⇒ 没问题（同级别之间不拦）；
4. 目标提权、自己没提权 ⇒ 报警。

第 2 步读不到令牌时**返回 `None` 而不是猜 `True`**：查不到可能是权限不够、也可能是
那个进程本身受保护（反作弊、系统进程）。宁可漏报一句提示，也不要对着正常环境喊狼来了 ——
一次误报就会让用户以后再看到这句话时不当事。

## 平台

只有 Windows 有这套概念。非 Windows 上这些函数一律返回「查不到」，调用方自然不提示。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

#: 只需要「查询」权限，不碰进程内存 —— 别为了探测去要 PROCESS_ALL_ACCESS。
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
#: TOKEN_INFORMATION_CLASS 里的 TokenElevation。用数字是因为 ctypes 没有现成常量。
TOKEN_ELEVATION = 20

#: 目标权限更高时给用户看的话。**要给出下一步动作**，不能只描述现象。
ELEVATION_WARNING = (
    "雷电模拟器以管理员权限运行，本助手未提升权限；这种情况下系统会拦掉模拟点击，"
    "表现为「日志显示已点击、游戏无响应」。需以管理员身份重新启动本助手。"
)


def _configure_prototypes() -> None:
    """把返回值类型写对。

    ⚠️ 不设 `restype` 时 ctypes 按 C `int`（32 位）返回句柄，64 位进程上会被截断 ——
    截断后的句柄不是 0，`if not handle` 看不出来，后面所有调用一起错。
    """
    if not hasattr(ctypes, "windll"):
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32 = ctypes.windll.advapi32
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]


def _token_is_elevated(token: ctypes.c_void_p) -> bool | None:
    """读一个令牌的提权状态。读不到返回 `None`。"""
    elevation = wintypes.DWORD()
    returned = wintypes.DWORD()
    ok = ctypes.windll.advapi32.GetTokenInformation(
        token,
        TOKEN_ELEVATION,
        ctypes.byref(elevation),
        ctypes.sizeof(elevation),
        ctypes.byref(returned),
    )
    if not ok:
        return None
    return bool(elevation.value)


def current_process_elevated() -> bool:
    """本进程是不是以管理员身份运行的。查不到一律当「不是」—— 这是保守的一侧。"""
    if not hasattr(ctypes, "windll"):
        return False
    _configure_prototypes()
    token = wintypes.HANDLE()
    if not ctypes.windll.advapi32.OpenProcessToken(
        ctypes.windll.kernel32.GetCurrentProcess(),
        TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return False
    try:
        return _token_is_elevated(token) is True
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def process_elevated(pid: int) -> bool | None:
    """另一个进程是不是提权的。**打不开或读不到都返回 `None`**，不要猜。"""
    if not hasattr(ctypes, "windll"):
        return None
    _configure_prototypes()
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None
    try:
        token = wintypes.HANDLE()
        if not ctypes.windll.advapi32.OpenProcessToken(
            handle, TOKEN_QUERY, ctypes.byref(token)
        ):
            return None
        try:
            return _token_is_elevated(token)
        finally:
            ctypes.windll.kernel32.CloseHandle(token)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def window_process_id(window: object) -> int | None:
    """取窗口对象所属进程的 PID。对象不认识就返回 `None`（不抛）。"""
    getter = getattr(window, "process_id", None)
    if not callable(getter):
        return None
    try:
        return int(getter())
    except Exception:  # noqa: BLE001 —— 窗口刚好被关掉是常态，不该让检测炸掉
        return None


def privilege_warning_for(
    window: object,
    *,
    self_elevated=current_process_elevated,
    target_elevated=process_elevated,
) -> str | None:
    """需要提示「请以管理员身份重启」时返回那句话，否则 `None`。"""
    pid = window_process_id(window)
    if pid is None or pid <= 0:
        return None
    try:
        if self_elevated():
            return None
        elevated = target_elevated(pid)
    except OSError:
        return None
    # 只在**确实读到 True** 时提示；None（查不到）保持沉默，见模块 docstring。
    return ELEVATION_WARNING if elevated is True else None


__all__ = [
    "ELEVATION_WARNING",
    "current_process_elevated",
    "privilege_warning_for",
    "process_elevated",
    "window_process_id",
]
