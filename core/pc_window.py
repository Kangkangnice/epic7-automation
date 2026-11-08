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
from typing import Callable

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
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SRCCOPY = 0x00CC0020
_CAPTUREBLT = 0x40000000
# 后台抓帧的重试次数与间隔（见 ``capture``：偶发失败，重试一次基本就好）。
#
# 原为 3 次 × 0.2 秒（最坏 0.4 秒）。2026-11-01 移植主线时实测不够：
# 「大厅 → 主线入口」这种**带加载的转场**里，客户端有约 0.6~0.8 秒拿不到可 BitBlt
# 的画面，两轮实跑一共失手 3 次，其中一次连试 3 次全败 ⇒ 整轮以
# 「PC 后台截图失败」中止（不是认不出页面，纯粹是抓不到帧）。
# 改成 6 次 × 0.3 秒 = 1.8 秒上限：仍是有界的，且只在**真的抓不到**时才等这么久。
#
# 2026-11-02 又加到 10 次（= 3.0 秒）：点「进入骑士团」后，骑士团主页加载期间
# 连续 6 次抓到的都是黑帧（``capture`` 对 std<1.0 返回 None）⇒ 世界首领战直接
# 以「PC 后台截图失败」中止。加载类转场比页面切换更久，预算必须留够。
#
# ⚠️ 2026-11-08 第三次撞上，这次是**线路重连**：竞技场跑到第 6 轮时网络断开，
# 游戏整块黑屏重连，10 次 × 0.3 秒 = 3.0 秒在**两秒多**里就打光了
# （``epic7_arena.log`` 00:38:55~00:38:58 十连败），随后的「回首页」也跟着失败。
# 光加**次数**治不了这一类：黑屏的时长是「重连要多久」，不是「抖一下」。
# 所以从这一版起改为**指数退避**：
#   首次仍只等 0.3 秒（偶发一次重绘失败的代价不变）
#   之后每跳 ×1.5，封顶 2.5 秒 ⇒ 总预算约 **13.7 秒**，够覆盖一次线路重连
# 仍然是有界的，试满照旧抛错（fail-closed 性质不变）。
CAPTURE_ATTEMPTS = 10
CAPTURE_RETRY_DELAY = 0.3
# 退避倍率与单跳上限：只在这两个数上做文章，不要再去加 ``CAPTURE_ATTEMPTS``。
CAPTURE_BACKOFF_FACTOR = 1.5
CAPTURE_MAX_DELAY = 2.5
# 置前同样有界重试（见 ``activate``）。
ACTIVATE_ATTEMPTS = 3
# ---- 输入通道 ---------------------------------------------------------------
#
# ``foreground``：SetForegroundWindow + SendInput —— 一直以来的做法，**必须抢前台**。
# ``background``：SetCursorPos + WM_ACTIVATE + PostMessage —— 不抢前台。
#
# ⚠️ 只发消息一定不生效：本客户端是 GLFW（导入表里有 GetCursorPos / SetCursorPos /
# RegisterRawInputDevices / GetRawInputData），它的 UI 每帧读的是**真实光标位置**，
# 不是消息参数。所以必须先把系统光标挪过去（SetCursorPos 不需要前台），
# 再投递消息 —— 两者缺一都表现为「点了没反应」。
#
# ⚠️ 键盘没有后台方案（游戏走 GetAsyncKeyState / Raw Input），``back()`` 在后台通道下
# 会自动改走前台并记一行日志，不做静默降级。
PC_INPUT_FOREGROUND = "foreground"
PC_INPUT_BACKGROUND = "background"
PC_INPUT_MODES = (PC_INPUT_FOREGROUND, PC_INPUT_BACKGROUND)
# 输入通道是**进程级能力**（这台机器能不能后台点），不是路线参数。走环境变量是为了
# 不把它塞进 ``_build_runtime`` → ``_run_mode`` → ``_build_daily_probe`` 这条链的
# 每个签名里；与 ``EPIC7_DATA_DIR`` 同一套做法（见 core/data_paths.py）。
PC_INPUT_ENV = "EPIC7_PC_INPUT_MODE"
_WM_ACTIVATE = 0x0006
_WA_ACTIVE = 0x0001
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_MK_LBUTTON = 0x0001


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD),
        ("x_pixels_per_meter", wintypes.LONG),
        ("y_pixels_per_meter", wintypes.LONG),
        ("colors_used", wintypes.DWORD),
        ("colors_important", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("header", _BitmapInfoHeader),
        ("colors", wintypes.DWORD * 1),
    ]


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


@dataclass(frozen=True)
class WindowCalibration:
    before: WindowRect
    after: WindowRect
    adjusted: bool


class Epic7PcWindow:
    """Capture and click the uniquely titled Epic Seven PC client window."""

    _TITLE = "第七史诗"
    _PROCESS_NAME = "epicseven.exe"
    # Sub-windows owned by the engine that must NOT be treated as the game canvas.
    _SUBWINDOW_MARKERS = ("_thread_", "GLFW message window", "GDI+ Window")

    def __init__(
        self,
        reference_size: tuple[int, int] = REFERENCE_SIZE,
        sleep_fn: Callable[[float], None] = sleep,
        event_sink: Callable[[str], None] | None = None,
    ) -> None:
        self.reference_size = reference_size
        self._sleep = sleep_fn
        self._event_sink = event_sink
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        # 默认前台：后台通道是**逐机器实测**才敢开的（见模块顶部的通道说明），
        # 没验证过就默认后台会把「偶发点不动」变成默认故障。
        self._input_mode: str = PC_INPUT_FOREGROUND
        # 后台动作结束后光标停在哪个屏幕坐标；None = 还没发过后台动作。
        # 用来判断「用户是不是动过鼠标」，见 _background_cursor_begin()。
        self._cursor_anchor: tuple[int, int] | None = None

    def set_event_sink(self, sink: Callable[[str], None] | None) -> None:
        self._event_sink = sink

    def _emit(self, message: str) -> None:
        if self._event_sink is not None:
            self._event_sink(message)

    # ---- 输入通道 ---------------------------------------------------------

    @property
    def input_mode(self) -> str:
        return self._input_mode

    def set_input_mode(self, mode: str) -> None:
        """切换输入通道。未知取值直接报错，不静默退回前台。"""
        if mode not in PC_INPUT_MODES:
            raise ValueError(
                f"未知的 PC 输入通道: {mode!r}（可用: {', '.join(PC_INPUT_MODES)}）"
            )
        self._input_mode = mode
        self._emit(f"模式=PC输入 通道={mode}")

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

    def _outer_rect(self, hwnd) -> WindowRect:
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("无法读取 Epic Seven PC 窗口外框")
        return WindowRect(
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        )

    def activate(self):
        # ⚠️ ``SetForegroundWindow`` 也会**偶发**失败（2026-11-01 助手实跑时遇到过一次
        # 「游戏窗口=未知 前置=失败」）：Windows 不让一个不是前台的进程随便抢前台。
        # 与截图同理 —— 有界重试几轮，试满才报。
        hwnd = self._find_window()
        if self._user32.GetForegroundWindow() == hwnd:
            return hwnd
        for attempt in range(1, ACTIVATE_ATTEMPTS + 1):
            self._user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            self._nudge_foreground_permission()
            self._user32.SetForegroundWindow(hwnd)
            for _ in range(10):
                if self._user32.GetForegroundWindow() == hwnd:
                    return hwnd
                sleep(0.05)
            if attempt < ACTIVATE_ATTEMPTS:
                self._emit(
                    f"模式=PC输入 事件=窗口未置前 第={attempt}/{ACTIVATE_ATTEMPTS}次 "
                    "动作=稍后重试"
                )
                self._sleep(0.3)
        raise RuntimeError("PC 游戏窗口未能置前，已拒绝截图或输入")

    def _nudge_foreground_permission(self) -> None:
        """发一次「空 ALT」骗过 Windows 的前台限制。

        ``SetForegroundWindow`` 只在「调用进程是前台 / 刚收到用户输入」时才允许抢前台。
        自动化进程两条都不满足，所以只要用户把窗口切走（比如去看助手界面），
        置前就会连续失败 —— 2026-11-03 早上一小时内撞了 3 次，整套实跑直接退出。

        发一个**只有按下与抬起、不带任何其它键**的 ALT，会让系统把本进程当成
        「刚收到用户输入」，随后的 ``SetForegroundWindow`` 就能成功。
        这是 Win32 自动化的常规做法，不改变任何业务语义，也不留按键副作用
        （ALT 单独按下抬起不会触发菜单或快捷键）。
        """
        try:
            self._user32.keybd_event(0x12, 0, 0, 0)  # ALT down
            self._user32.keybd_event(0x12, 0, 2, 0)  # ALT up
        except Exception:
            # 骗不到就算了，后面 SetForegroundWindow 照旧尝试；失败仍然按老路报错。
            pass

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

    def ensure_render_size(self) -> WindowCalibration:
        hwnd = self._find_window()
        self._ensure_input_allowed(hwnd)
        before = self._rect(hwnd)
        if (before.width, before.height) == RENDER_SIZE:
            return WindowCalibration(before, before, False)

        previous_foreground = self._user32.GetForegroundWindow()
        try:
            hwnd = self.activate()
            outer = self._outer_rect(hwnd)
            target_outer_width = RENDER_SIZE[0] + outer.width - before.width
            target_outer_height = RENDER_SIZE[1] + outer.height - before.height
            if not self._user32.SetWindowPos(
                hwnd,
                0,
                outer.left,
                outer.top,
                target_outer_width,
                target_outer_height,
                _SWP_NOZORDER | _SWP_NOACTIVATE,
            ):
                error = ctypes.get_last_error()
                raise RuntimeError(
                    f"PC 游戏窗口调整失败：当前={before.width}x{before.height} "
                    f"目标={RENDER_SIZE[0]}x{RENDER_SIZE[1]} Win32错误码={error}"
                )

            after = before
            for _ in range(10):
                sleep(0.1)
                after = self._rect(hwnd)
                if (after.width, after.height) == RENDER_SIZE:
                    return WindowCalibration(before, after, True)
            raise RuntimeError(
                f"PC 游戏窗口调整未生效：调整前={before.width}x{before.height} "
                f"目标={RENDER_SIZE[0]}x{RENDER_SIZE[1]} "
                f"调整后实际仍为 {after.width}x{after.height}"
            )
        finally:
            self._restore_foreground(previous_foreground, hwnd)

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
        # ⚠️ 后台抓帧会**偶发**失败（2026-11-01 实测：40 拍里失败 2 次，
        # 而且当时游戏既没最小化、甚至就在前台）。原因不是前台，是客户端正在重绘时
        # 那一帧拿不到内容。它不是「游戏关了」，一次重试基本就能拿到。
        #
        # 所以这里**有界重试**，而不是把第一次失败直接抛给上层 —— 上层会当成致命错误，
        # 整条路线就此中断（实测竞技场就是死在这一下）。试满仍然失败才照旧抛错，
        # 该 fail-closed 的性质一点没变。
        hwnd = self._find_window()
        self._validated_rect(hwnd)
        delay = CAPTURE_RETRY_DELAY
        for attempt in range(1, CAPTURE_ATTEMPTS + 1):
            frame = self._capture_client_bitblt(hwnd)
            if frame is not None:
                return self._legacy_canvas(frame)
            if attempt < CAPTURE_ATTEMPTS:
                self._emit(
                    f"模式=PC截图 事件=后台抓帧失败 第={attempt}/{CAPTURE_ATTEMPTS}次 "
                    f"动作=稍后重试 等待={delay:.2f}秒"
                )
                self._sleep(delay)
                # 指数退避：第一次仍然只等 0.3 秒（偶发重绘失败照旧一等到位），
                # 后面每跳拉长，用于扛住「重连黑屏十几秒」这一类（见上方常量注释）。
                delay = min(delay * CAPTURE_BACKOFF_FACTOR, CAPTURE_MAX_DELAY)
        raise RuntimeError(
            "PC 后台截图失败；为避免抢占前台已安全停止。"
            f"已重试 {CAPTURE_ATTEMPTS} 次，请保持游戏窗口未最小化后重试"
        )

    def _capture_client_bitblt(self, hwnd) -> np.ndarray | None:
        """Capture the live client surface without bringing the game forward."""

        client = wintypes.RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(client)):
            return None
        width = client.right - client.left
        height = client.bottom - client.top
        if (width, height) != RENDER_SIZE:
            return None

        gdi32 = ctypes.windll.gdi32
        window_dc = self._user32.GetDC(hwnd)
        if not window_dc:
            return None
        try:
            memory_dc = gdi32.CreateCompatibleDC(window_dc)
            if not memory_dc:
                return None
            try:
                bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
                if not bitmap:
                    return None
                try:
                    previous = gdi32.SelectObject(memory_dc, bitmap)
                    try:
                        if not gdi32.BitBlt(
                            memory_dc,
                            0,
                            0,
                            width,
                            height,
                            window_dc,
                            0,
                            0,
                            _SRCCOPY | _CAPTUREBLT,
                        ):
                            return None
                        info = _BitmapInfo()
                        info.header.size = ctypes.sizeof(_BitmapInfoHeader)
                        info.header.width = width
                        info.header.height = -height
                        info.header.planes = 1
                        info.header.bit_count = 32
                        buffer = ctypes.create_string_buffer(width * height * 4)
                        if not gdi32.GetDIBits(
                            memory_dc,
                            bitmap,
                            0,
                            height,
                            buffer,
                            ctypes.byref(info),
                            0,
                        ):
                            return None
                    finally:
                        if previous:
                            gdi32.SelectObject(memory_dc, previous)
                finally:
                    gdi32.DeleteObject(bitmap)
            finally:
                gdi32.DeleteDC(memory_dc)
        finally:
            self._user32.ReleaseDC(hwnd, window_dc)

        # 同 core/window.py：np.frombuffer 的 stub 不接受 ctypes 数组，包一层 memoryview
        # （同一个缓冲区的视图，逐字节等价）。
        bgra = np.frombuffer(memoryview(buffer), dtype=np.uint8).reshape(
            height, width, 4
        )
        frame = np.ascontiguousarray(bgra[:, :, :3][:, :, ::-1])
        if float(frame.std()) < 1.0:
            return None
        return frame

    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        """用 SendInput 拖拽一次（画布坐标 → 客户区 → 桌面绝对坐标）。

        ⚠️ 2026-11-02 新增。此前 PC 端**没有**滑动实现，`main.py` 给 Runtime 传的
        ``swipe=None`` ⇒ 刷书签 / 骑士团捐赠 / 迷宫强化石 / 幸存者 这四条路线
        一走到滑动就抛「未配置滑动动作」。滑动属窗口 I/O，本层是 PC 与模拟器
        唯一被允许分叉的地方，所以补在这里，业务代码一行不动。

        与 ``click`` 同口径：点完不把焦点还回去（2026-11-01 用户拍板，避免窗口闪）。
        轨迹按 ``duration_ms`` 均分约 16ms 一步，中途不抬键 —— 抬手就成了点击。
        """
        if self._input_mode == PC_INPUT_BACKGROUND:
            # 参考项目 PcControllerBase._background_drag 同源的序列；
            # 2026-11-08 用户实测前这里是 fail-closed 抛错（拖拽序列当时没验过），
            # 结果刷书签等含滑动路线在后台通道下直接收工，现已补齐。
            self._background_swipe(start, end, duration_ms)
            return
        previous_foreground = self._user32.GetForegroundWindow()
        hwnd = None
        succeeded = False
        try:
            hwnd = self.activate()
            self._ensure_input_allowed(hwnd)
            rect = self._validated_rect(hwnd)
            points = []
            for point in (start, end):
                render_point = point[0], point[1] - LEGACY_TOP
                if not (
                    0 <= render_point[0] < RENDER_SIZE[0]
                    and 0 <= render_point[1] < RENDER_SIZE[1]
                ):
                    raise RuntimeError(f"拒绝在 PC 游戏渲染区外滑动：{point}")
                points.append(
                    (rect.left + render_point[0], rect.top + render_point[1])
                )
            self._send_swipe(points[0], points[1], duration_ms)
            succeeded = True
        finally:
            self._emit(
                f"模式=PC输入 类型=滑动 原前台={previous_foreground} "
                f"游戏窗口={hwnd if hwnd is not None else '未知'} "
                f"前置={'成功' if hwnd is not None else '失败'} "
                f"结果={'成功' if succeeded else '失败'} "
                f"起点={start} 终点={end} 时长={duration_ms}ms"
            )

    def _send_swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        """按下 → 分步移动 → 抬起。步数与间隔照 ``duration_ms`` 均分（约 16ms 一步）。"""
        desktop_width = self._user32.GetSystemMetrics(0)
        desktop_height = self._user32.GetSystemMetrics(1)
        total = max(int(duration_ms), 16)
        steps = max(int(total / 16), 2)
        delay = total / steps / 1000.0

        def absolute(point: tuple[int, int]) -> _MouseInput:
            x, y = point
            return _MouseInput(
                round(x * 65535 / (desktop_width - 1)),
                round(y * 65535 / (desktop_height - 1)),
                0,
                _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE,
                0,
                0,
            )

        self._send_mouse_input(absolute(start))
        self._send_mouse_input(_MouseInput(0, 0, 0, _MOUSEEVENTF_LEFTDOWN, 0, 0))
        try:
            for step in range(1, steps + 1):
                ratio = step / steps
                point = (
                    round(start[0] + (end[0] - start[0]) * ratio),
                    round(start[1] + (end[1] - start[1]) * ratio),
                )
                self._send_mouse_input(absolute(point))
                self._sleep(delay)
        finally:
            self._send_mouse_input(_MouseInput(0, 0, 0, _MOUSEEVENTF_LEFTUP, 0, 0))

    def click(self, point: tuple[int, int]) -> None:
        if self._input_mode == PC_INPUT_BACKGROUND:
            self._background_click(point)
            return
        # ⚠️ **点完不把焦点还回去**（2026-11-01 用户拍板）：原来每次点击都要
        # 「前置 → 注入 → 还原原来的窗口」，窗口来回切换会**一闪一闪**，很烦。
        # 助手被游戏盖住不影响任何事（日志照常落盘），所以就让游戏一直待在最前。
        #
        # 注意：这与「截图不前置」是两件事 —— 抓帧走 BitBlt，不需要窗口在最前；
        # 只有 SendInput 需要，所以只有点击/按键这两个入口才置前。
        previous_foreground = self._user32.GetForegroundWindow()
        hwnd = None
        succeeded = False
        try:
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
            succeeded = True
        finally:
            self._emit(
                f"模式=PC输入 类型=点击 原前台={previous_foreground} "
                f"游戏窗口={hwnd if hwnd is not None else '未知'} "
                f"前置={'成功' if hwnd is not None else '失败'} "
                f"结果={'成功' if succeeded else '失败'} "
                "保持在前台=是"
            )

    def _restore_foreground(self, previous_hwnd, game_hwnd) -> bool:
        if not previous_hwnd or previous_hwnd == game_hwnd:
            return True
        try:
            if not self._user32.IsWindow(previous_hwnd):
                return False
            if not self._user32.SetForegroundWindow(previous_hwnd):
                return False
            for _ in range(10):
                if self._user32.GetForegroundWindow() == previous_hwnd:
                    return True
                self._sleep(0.05)
        except Exception:
            return False
        return False

    def _background_cursor_begin(self) -> tuple[int, int] | None:
        """决定本次后台动作结束后要不要把光标还回去。

        本客户端是 GLFW，UI 每帧读**真实系统光标**（GetCursorPos），后台点击
        必须 SetCursorPos 到目标点 —— 参考项目 ``_background_click`` 也是这么做的。
        但参考项目**不还原**光标：绝区零锁鼠标、系统光标本来不可见；第七史诗
        PC 客户端能看见光标，原先「移过去 + 移回来」两次瞬移在密集点击时就
        成了用户反馈的「鼠标一直在抖」。

        折中：只有**用户动过鼠标**时才还原到他的新位置；若光标还停在我们
        上次放的地方，就只从上一个目标点移到下一个目标点（一次瞬移），
        不来回跳。用户任何时候动一下鼠标，下一次动作后会立刻把光标还给他。
        """
        current = wintypes.POINT()
        self._user32.GetCursorPos(ctypes.byref(current))
        now = (current.x, current.y)
        if self._cursor_anchor is None or now != self._cursor_anchor:
            return now
        return None

    def _background_cursor_end(
        self, restore_to: tuple[int, int] | None, last_point: tuple[int, int]
    ) -> None:
        if restore_to is not None:
            self._user32.SetCursorPos(restore_to[0], restore_to[1])
            self._cursor_anchor = restore_to
        else:
            self._cursor_anchor = last_point

    def _background_click(self, point: tuple[int, int]) -> None:
        """后台点击：SetCursorPos + WM_ACTIVATE + PostMessage。

        三段各管一件事：SetCursorPos 让 GLFW 读到目标位置、
        WM_ACTIVATE 骗出激活态、PostMessage 送移动/按下/抬起。
        坐标走客户区口径（0..1920 × 0..1080），不抢系统前台。
        """
        hwnd = self._find_window()
        self._ensure_input_allowed(hwnd)
        rect = self._validated_rect(hwnd)
        render_x, render_y = point[0], point[1] - LEGACY_TOP
        if not (0 <= render_x < RENDER_SIZE[0] and 0 <= render_y < RENDER_SIZE[1]):
            raise RuntimeError(f"拒绝在 PC 游戏渲染区外点击：{point}")

        screen_point = (rect.left + render_x, rect.top + render_y)
        lparam = (render_y << 16) | (render_x & 0xFFFF)
        previous_foreground = self._user32.GetForegroundWindow()
        restore_to = self._background_cursor_begin()
        succeeded = False
        try:
            self._user32.SetCursorPos(screen_point[0], screen_point[1])
            self._sleep(0.02)
            self._user32.SendMessageW(hwnd, _WM_ACTIVATE, _WA_ACTIVE, 0)
            self._sleep(0.01)
            self._user32.PostMessageW(hwnd, _WM_MOUSEMOVE, 0, lparam)
            self._sleep(0.01)
            self._user32.PostMessageW(hwnd, _WM_LBUTTONDOWN, _MK_LBUTTON, lparam)
            self._sleep(0.08)
            self._user32.PostMessageW(hwnd, _WM_LBUTTONUP, 0, lparam)
            succeeded = True
        finally:
            restored = restore_to is not None
            self._background_cursor_end(restore_to, screen_point)
            self._emit(
                f"模式=PC输入 类型=后台点击 画布={point} "
                f"客户区=({render_x},{render_y}) 屏幕={screen_point} "
                f"游戏窗口={hwnd} 原前台={previous_foreground} "
                f"结果={'成功' if succeeded else '失败'} "
                f"光标已还原={'是' if restored else '否(用户未动鼠标)'}"
            )

    def _background_swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        """后台滑动：照参考项目 ``PcControllerBase._background_drag`` 的序列。

        WM_ACTIVATE → SetCursorPos(起点) + LBUTTONDOWN → 分步 SetCursorPos 并送
        WM_MOUSEMOVE(MK_LBUTTON) → 终点定住消除惯性 → LBUTTONUP。
        参考项目只靠 SetCursorPos（GLFW 每帧读真实光标，不读消息参数），
        我们额外送 WM_MOUSEMOVE，让消息驱动的 UI 也能收到整段拖动轨迹。
        全程不抢系统前台；光标沿用 _background_cursor_begin/end 的智能还原。
        """
        hwnd = self._find_window()
        self._ensure_input_allowed(hwnd)
        rect = self._validated_rect(hwnd)
        points: list[tuple[int, int]] = []
        for point in (start, end):
            render_x, render_y = point[0], point[1] - LEGACY_TOP
            if not (
                0 <= render_x < RENDER_SIZE[0] and 0 <= render_y < RENDER_SIZE[1]
            ):
                raise RuntimeError(f"拒绝在 PC 游戏渲染区外滑动：{point}")
            points.append((rect.left + render_x, rect.top + render_y))
        (sx, sy), (ex, ey) = points

        def lparam(x: int, y: int) -> int:
            return ((y - rect.top) << 16) | ((x - rect.left) & 0xFFFF)

        previous_foreground = self._user32.GetForegroundWindow()
        restore_to = self._background_cursor_begin()
        succeeded = False
        try:
            self._user32.SendMessageW(hwnd, _WM_ACTIVATE, _WA_ACTIVE, 0)
            self._sleep(0.01)
            self._user32.SetCursorPos(sx, sy)
            self._sleep(0.01)
            self._user32.PostMessageW(
                hwnd, _WM_LBUTTONDOWN, _MK_LBUTTON, lparam(sx, sy)
            )
            self._sleep(0.02)
            steps = max(int(duration_ms / 16), 5)
            delay = max(duration_ms / 1000.0 / steps, 0.01)
            for index in range(1, steps + 1):
                x = int(sx + (ex - sx) * index / steps)
                y = int(sy + (ey - sy) * index / steps)
                self._user32.SetCursorPos(x, y)
                self._user32.PostMessageW(
                    hwnd, _WM_MOUSEMOVE, _MK_LBUTTON, lparam(x, y)
                )
                self._sleep(delay)
            self._sleep(0.05)  # 抬起前定住，消除滑动惯性（参考项目同款）
            self._user32.PostMessageW(hwnd, _WM_LBUTTONUP, 0, lparam(ex, ey))
            succeeded = True
        finally:
            restored = restore_to is not None
            self._background_cursor_end(restore_to, (ex, ey))
            self._emit(
                f"模式=PC输入 类型=后台滑动 起点={start} 终点={end} "
                f"时长={duration_ms}ms 游戏窗口={hwnd} "
                f"原前台={previous_foreground} "
                f"结果={'成功' if succeeded else '失败'} "
                f"光标已还原={'是' if restored else '否(用户未动鼠标)'}"
            )

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
        self._send_mouse_input(move)
        self._send_mouse_input(down)
        try:
            self._sleep(0.08)
        finally:
            self._send_mouse_input(up)

    def _send_mouse_input(self, mouse: _MouseInput) -> None:
        inputs = (_Input * 1)(_Input(0, _InputUnion(mouse=mouse)))
        if self._user32.SendInput(1, inputs, ctypes.sizeof(_Input)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    def wake(self, point: tuple[int, int]) -> None:
        # PC client has no separate idle layer; a normal click dispatches through
        # the desktop mouse stack the same way.
        self.click(point)

    def back(self) -> None:
        # 与 ``click`` 同口径：返回键点完**不把焦点还回去**，避免窗口来回闪。
        if self._input_mode == PC_INPUT_BACKGROUND:
            # Esc 走键盘，而键盘没有后台方案（游戏读 Raw Input）。这里**不静默降级**：
            # 明说「本次改走前台」，日志里能看见，用户才知道这一下会抢焦点。
            self._emit(
                "模式=PC输入 类型=返回 说明=后台通道不支持 Esc，本次自动改走前台"
            )
        previous_foreground = self._user32.GetForegroundWindow()
        hwnd = None
        succeeded = False
        try:
            hwnd = self.activate()
            self._ensure_input_allowed(hwnd)
            pyautogui.press("esc")
            succeeded = True
        finally:
            self._emit(
                f"模式=PC输入 类型=返回 原前台={previous_foreground} "
                f"游戏窗口={hwnd if hwnd is not None else '未知'} "
                f"前置={'成功' if hwnd is not None else '失败'} "
                f"结果={'成功' if succeeded else '失败'} "
                "保持在前台=是"
            )
