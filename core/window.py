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


def render_is_usable(rgb: np.ndarray) -> bool:
    """窗口级截图（PrintWindow）拿到的画面是否可用。

    全黑或纯色的画面说明 PrintWindow 对这个窗口无效，调用方要回退屏幕截图。

    判据用 uint8 上的极差 `max() - min()`，**不要用 `rgb.std()`**：
    两者对整数像素几乎等价（std < 1 意味着所有取值与均值相差不到 1，
    也就是极差 <= 1 左右），但 `np.std` 会按 float64 累加，
    在 1920×1080×3 上每帧多分配约 47.5 MiB ——
    实跑与测试并发时曾因此报 `_ArrayMemoryError: Unable to allocate 47.5 MiB`。
    极差判据略严于 std（极差 2 但分布极度偏斜的帧会被判不可用），
    这时走屏幕截图回退路径，比冒险用一张近乎纯色的帧更安全。
    """
    return int(rgb.max()) - int(rgb.min()) > 1


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
    _SW_SHOWNOACTIVATE = 4  # 还原但不抢前台：用户可能正在别的窗口里做事
    _SW_RESTORE = 9  # 还原并置前，仅在不抢前台的还原没生效时用
    # 还原后等窗口真的退出最小化状态：每次 0.05s，最多约 1s。
    _RESTORE_WAIT_ATTEMPTS = 20
    _RESTORE_SETTLE_SECONDS = 0.4  # 还原动画期间画面还没回来，别立刻截图
    # 雷电控制台**所有**出错情况都返回退出码 0，只把错误打印到 stdout。
    # 2026-09-24 实测四条：`adb --index 9` → `adb.exe: device 'emulator-5572' not found`、
    # `adb --index 0`（设备离线）→ `adb.exe: device offline`、
    # `action --index 9` → `player don't exist!`、`action`（漏参数）→ 整篇 usage。
    # ⇒ `check=True` 对它完全无效，必须显式看输出（详见 `_ensure_input_delivered`）。
    _INPUT_FAILURE_MARKERS = (
        b"adb.exe:",  # adb 客户端自己的错误前缀：offline / not found / unauthorized…
        b"device offline",  # 兜底：万一某版本不带前缀
        b"player don't exist",  # ldconsole：实例不存在
        b"error:",
        b"usage:",  # ldconsole 参数写错时打印整篇帮助，退出码仍是 0
    )

    def __init__(self, title: str = "第七史诗") -> None:
        self.title = title
        self.viewport = WindowViewport(self._rect)
        self._event_sink: Callable[[str], None] | None = None

    def set_event_sink(self, sink: Callable[[str], None] | None) -> None:
        self._event_sink = sink

    def _emit(self, message: str) -> None:
        if self._event_sink is not None:
            self._event_sink(message)

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
            # 最小化是用户的正常操作（切去看别的、误触最小化按钮），不是故障：
            # 先把它还原回桌面继续跑，实在还原不了才当作故障抛错。
            self._restore_window(window)
        return window

    def _restore_window(self, window) -> None:
        """把最小化的模拟器窗口还原回桌面。

        优先用「不抢前台」的还原，免得用户正在别的窗口里打字时被抢走焦点；
        只有这种方式没生效时才退化成会置前的还原。
        """
        handle = window._hWnd
        self._emit(f"窗口最小化已自动还原 标题={window.title}")
        ctypes.windll.user32.ShowWindow(handle, self._SW_SHOWNOACTIVATE)
        for _ in range(self._RESTORE_WAIT_ATTEMPTS):
            if not ctypes.windll.user32.IsIconic(handle):
                sleep(self._RESTORE_SETTLE_SECONDS)
                return
            sleep(0.05)
        # 不抢前台的还原对个别窗口无效，再试一次会置前的还原。
        ctypes.windll.user32.ShowWindow(handle, self._SW_RESTORE)
        for _ in range(self._RESTORE_WAIT_ATTEMPTS):
            if not ctypes.windll.user32.IsIconic(handle):
                sleep(self._RESTORE_SETTLE_SECONDS)
                return
            sleep(0.05)
        raise RuntimeError(f"窗口 {window.title} 处于最小化状态，且自动还原未生效")

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
            ctypes.windll.user32.ShowWindow(handle, self._SW_RESTORE)
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
        if not render_is_usable(rgb):
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

    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        render_start, render_end = self._swipe_render_points(
            start, end, duration_ms
        )
        try:
            self._send_render_swipe(render_start, render_end, duration_ms)
        except (RuntimeError, subprocess.SubprocessError):
            self.activate()
            self._send_render_swipe(render_start, render_end, duration_ms)

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

    def _swipe_render_points(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        render_start = start[0], start[1] - self._LEGACY_TOP
        render_end = end[0], end[1] - self._LEGACY_TOP
        for point in (render_start, render_end):
            if not (
                0 <= point[0] < self._RENDER_SIZE[0]
                and 0 <= point[1] < self._RENDER_SIZE[1]
            ):
                raise RuntimeError(f"拒绝在安卓渲染区外滑动：{start}->{end}")
        if duration_ms <= 0:
            raise ValueError("滑动时长必须大于 0")
        return render_start, render_end

    @classmethod
    def _ensure_input_delivered(cls, result: subprocess.CompletedProcess) -> None:
        """把「控制台回了退出码 0、指令其实没送达」转成显式失败。

        2026-09-24 实机：adb 设备处于 offline，`ldconsole adb` 把
        `adb.exe: device offline` 写进输出，退出码却是 0。于是点击被当成发送成功，
        上层只看到「点击验收无效」，重试 4 次后报「导航转场失败」—— 表现是
        「点不动，但程序不报错、不告警、也不切通道」。

        抛出 RuntimeError 后 `click()` 既有的 activate-重试分支才会真正生效；
        重试仍失败则明确失败，而不是继续假装成功。
        """
        output = b"".join(
            bytes(stream)
            for stream in (result.stdout, result.stderr)
            if isinstance(stream, (bytes, bytearray))
        )
        lowered = output.lower()
        if any(marker in lowered for marker in cls._INPUT_FAILURE_MARKERS):
            raise RuntimeError(
                "模拟器输入通道不可用，指令未送达："
                + output.decode("utf-8", "replace").strip()
            )

    # 探测点击通道用的无害命令：走的是和真实点击**同一条** `ldconsole adb` 链路，
    # 但只在设备里执行 `echo`，不碰游戏画面。通道通时必须回显 `ping`
    # （2026-09-24 实测：成功时 `ldconsole adb` 的输出为空，所以这里用 echo 造回显）。
    _INPUT_PROBE_COMMAND = "shell echo ping"
    # 通道不可用时重建 adb 服务的两次操作。⚠️ 只用这两条：
    # `adb reconnect offline` / `adb connect 127.0.0.1:5555` 两次实测都**无效**，
    # 别往这里加（详见 .workbuddy/memory/topics/click_channel.md）。
    _ADB_REBUILD_COMMANDS = (("kill-server",), ("start-server",))

    def ensure_input_channel(self, attempts: int = 3, settle_seconds: float = 2.0) -> None:
        """开跑前自检模拟器输入通道（点击/滑动/返回），坏了就用代码把它拉起来。

        背景：host 侧 adb server 是**长驻进程**，模拟器重启后若连接没重建，设备就停在
        `offline`，`ldconsole adb` 会回 `adb.exe: device offline`（退出码却仍是 0）——
        表现是「画面看得见、点不动」。2026-09-24 与 2026-09-28 各实测一次，
        **两次都是 adb server 比模拟器早起十几小时**，两次都是
        `adb kill-server` → `start-server` 一步到位。

        只在实跑前调用（`main._build_runtime` 的 `not dry_run` 分支）：
        干跑不点击，不该去动 adb 服务。窗口本身不存在时 `_window()` 会先抛错，
        所以不会引入新的失败模式。
        """
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._probe_input_channel()
            except (RuntimeError, subprocess.SubprocessError, OSError) as error:
                last_error = error
                self._emit(
                    f"模拟器通道 状态=不可用 尝试={attempt}/{attempts} 动作=重启adb服务"
                )
                self._restart_adb_server()
                sleep(settle_seconds)
                continue
            self._emit(
                "模拟器通道 状态=可用"
                if attempt == 1
                else f"模拟器通道 状态=已恢复 尝试={attempt}/{attempts}"
            )
            return
        raise RuntimeError(
            f"模拟器输入通道不可用，自动重建 adb 服务 {attempts} 次仍未恢复：{last_error}"
        )

    def _probe_input_channel(self) -> None:
        """走真实点击那条 `ldconsole adb` 链路发一条无害命令，确认有回显。"""
        console_path, instance_index, _ = self._instance_channel()
        result = subprocess.run(
            [
                str(console_path),
                "adb",
                "--index",
                instance_index,
                "--command",
                self._INPUT_PROBE_COMMAND,
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # 设备 offline 时 ldconsole 的退出码仍是 0，失败只写在输出里 ⇒ 必须看内容。
        self._ensure_input_delivered(result)
        output = b"".join(
            bytes(stream)
            for stream in (result.stdout, result.stderr)
            if isinstance(stream, (bytes, bytearray))
        )
        if b"ping" not in output.lower():
            raise RuntimeError(
                "模拟器输入通道探测无回显："
                + output.decode("utf-8", "replace").strip()
            )

    def _restart_adb_server(self) -> None:
        """`adb kill-server` → `start-server`，只重建 host 侧 adb 服务。

        **不动模拟器、不重启游戏**（两次实测都是一步到位）。
        这里刻意 `check=False`：server 没在跑时 `kill-server` 也可能给非 0，
        真正的判据是重建之后再探一次通道有没有回显。
        """
        console_path, _, _ = self._instance_channel()
        adb_path = console_path.with_name("adb.exe")
        if not adb_path.exists():
            raise RuntimeError(f"未在 {console_path.parent} 找到 adb.exe，无法重建输入通道")
        for arguments in self._ADB_REBUILD_COMMANDS:
            subprocess.run(
                [str(adb_path), *arguments],
                check=False,
                capture_output=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def _send_render_tap(self, point: tuple[int, int]) -> None:
        console_path, instance_index, _ = self._instance_channel()
        result = subprocess.run(
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
        self._ensure_input_delivered(result)

    def _send_render_swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
    ) -> None:
        console_path, instance_index, _ = self._instance_channel()
        result = subprocess.run(
            [
                str(console_path),
                "adb",
                "--index",
                instance_index,
                "--command",
                (
                    f"shell input swipe {start[0]} {start[1]} "
                    f"{end[0]} {end[1]} {duration_ms}"
                ),
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._ensure_input_delivered(result)

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
        result = subprocess.run(
            [
                str(console_path), "action", "--index", instance_index,
                "--key", "call.keyboard", "--value", "back",
            ],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._ensure_input_delivered(result)
