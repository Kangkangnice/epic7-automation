"""通用 ADB 模拟器后端：不认品牌，只认「正在跑第七史诗的安卓设备」。

## 为什么需要它（2026-11-21）

``core/window.py::Epic7Window`` 把雷电写死在两处：窗口发现只认 ``dnplayer.exe``
进程 + 「雷电模拟器」标题，输入走 ``ldconsole.exe`` 私有控制台。MuMu 的进程是
``MuMuNxDevice.exe``、没有 ldconsole，于是程序在窗口发现阶段就报「找不到模拟器」，
根本走不到识别画面 —— 这是用户「MuMu 打开却识别不到」的根因。

所有安卓模拟器（雷电 / MuMu / 夜神 / BlueStacks…）都讲 ADB 这门通用语言，所以
``Epic7Window`` 统一改为：**用标准 adb 发现设备、抓图、注入输入**，与品牌无关。
新增模拟器无需改代码。

## 已实测（本机 MuMu 12，2026-11-21）

- MuMu 自带 adb.exe（``nx_main/adb.exe``），不依赖 PATH；雷电的 adb 也能连 MuMu。
- MuMu 横屏游戏画面 = 1920x1080，与雷电渲染区一致 ⇒ 复用 ``_legacy_canvas`` 即可。
- ``adb shell input tap`` 的坐标系与 screencap 一致（点返回箭头准确回到大厅）。
- MuMu 一个实例会监听 7555 / 16384 / 5555 等多个端口 ⇒ ``adb devices`` 列出多个
  设备号，但 ``pidof`` 游戏包名返回同一个 PID ⇒ 按游戏 PID 去重即可锁定唯一实例。
- ``screencap`` 约 1.1 秒/帧（比雷电 PrintWindow 慢），是当前通道的已知取舍。

## 契约

- 只支持**单开**：按游戏 PID 去重后若仍有多个实例，明确报错，不猜。
- 画布、点击坐标与 ``Epic7Window`` 完全一致（1982x1132 画布 / 减 52 顶栏），
  因为两者面向同一个游戏、同一套模板。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Callable

import cv2
import numpy as np
import psutil

#: 第七史诗包名，用来从众多 adb 设备里认出「真正在跑游戏的那一个」。
GAME_PACKAGE = "com.zlongame.cn.epicseven"

#: 在哪里找 adb.exe —— **不认任何模拟器品牌**。
#: 各模拟器都自带 adb.exe，且都装在「程序安装目录」下。这里扫描常见的程序安装根目录，
#: 在有限深度内找任意 adb.exe；新增模拟器无需改这里。顺序：先 PATH，再这些根目录。
_ADB_SEARCH_ROOTS = (
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"D:\Program Files",
    r"D:\Program Files (x86)",
)

#: 只在安装根的浅层找（够覆盖各模拟器布局，又不至于扫爆整个盘）。
_ADB_SCAN_DEPTH = 5

#: adb 取图/指令超时（秒）。screencap 实测约 1.1s，留足余量。
_ADB_TIMEOUT = 20.0

#: 截图调用失败重试次数（调用失败≠黑屏；黑屏是正常画面，原样交判据）。
_CAPTURE_ATTEMPTS = 3
_CAPTURE_RETRY_SECONDS = 0.12

_RENDER_SIZE = (1920, 1080)
_LEGACY_TOP = 52
_LEGACY_SIZE = (1982, 1132)

#: 输入失败标记：模拟器控制台/adbd 出错时**退出码仍是 0**，失败只写在输出里。
_INPUT_FAILURE_MARKERS = (
    b"adb.exe:",
    b"device offline",
    b"device not found",
    b"error:",
    b"no devices/emulators found",
    b"closed",
)

#: adb 服务冷启动时``devices``会夹带这两行提示，首批设备状态可能仍是 offline。
_DAEMON_START_MARKERS = ("daemon not running", "daemon started successfully")


class EmulatorNotFound(RuntimeError):
    """找不到正在运行第七史诗的安卓模拟器。"""


def _run(
    adb: Path,
    args: list[str],
    *,
    timeout: float = _ADB_TIMEOUT,
) -> subprocess.CompletedProcess:
    """统一执行 adb 命令，屏蔽窗口。

    超时做成关键字参数，测试里用二参数替身时也能接住 ``capture_render`` 的调用。
    """
    return subprocess.run(
        [str(adb), *args],
        check=False,
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _output_bytes(result: subprocess.CompletedProcess) -> bytes:
    return b"".join(
        bytes(stream)
        for stream in (result.stdout, result.stderr)
        if isinstance(stream, (bytes, bytearray))
    )


def _raise_on_adb_error(result: subprocess.CompletedProcess, action: str) -> None:
    """把「退出码 0、指令其实没送达」转成显式失败。"""
    output = _output_bytes(result)
    lowered = output.lower()
    if result.returncode != 0 or any(marker in lowered for marker in _INPUT_FAILURE_MARKERS):
        detail = output.decode("utf-8", "replace").strip().replace("\n", " ")
        if len(detail) > 100:
            detail = detail[:99] + "…"
        raise RuntimeError(
            f"模拟器连接已断开，本次{action}未送达游戏。"
            "请确认模拟器仍在运行、游戏停在大厅后重新开始"
            f"（底层信息：{detail}）"
        )


def find_adb() -> Path:
    """找一个可用的 adb.exe —— **不认任何模拟器品牌**。

    顺序：PATH → 从运行中的模拟器进程反推 → 扫描常见程序安装目录。
    所有安卓模拟器的 adb 协议一致（各自带的 adb 都能连别家模拟器，本机实测），
    找到任意一个即可。找不到时抛 ``EmulatorNotFound``。
    """
    on_path = shutil.which("adb")
    if on_path:
        return Path(on_path)

    # 从正在运行的模拟器进程反推：adb.exe 通常就在这个进程 exe 的目录树下。
    # 不认进程名，而是扫所有进程的 exe 路径里带 adb.exe 的同级/子目录。
    try:
        seen_roots: set[Path] = set()
        for process in psutil.process_iter(["exe"]):
            exe = process.info.get("exe")
            if not exe:
                continue
            directory = Path(exe).parent
            if directory in seen_roots:
                continue
            seen_roots.add(directory)
            found = _find_adb_near(directory)
            if found is not None:
                return found
    except Exception:  # noqa: BLE001 —— psutil 失败不该挡住后续兜底
        pass

    # 兜底：扫描常见程序安装根目录（有限深度，找到即停，不认品牌）。
    for root in _ADB_SEARCH_ROOTS:
        if not Path(root).is_dir():
            continue
        found = _find_adb_near(Path(root), max_depth=_ADB_SCAN_DEPTH)
        if found is not None:
            return found

    raise EmulatorNotFound(
        "未找到 adb.exe：请把 adb.exe 所在目录加入系统 PATH 后重试。"
        "（各安卓模拟器都自带 adb.exe）"
    )


def _find_adb_near(directory: Path, *, max_depth: int = 2) -> Path | None:
    """在 ``directory`` 下有限深度内找 adb.exe，找到第一个就返回。"""
    try:
        for depth, (current, dirs, files) in enumerate(os.walk(directory)):
            if "adb.exe" in files:
                return Path(current) / "adb.exe"
            if depth >= max_depth:
                dirs[:] = []
    except OSError:
        return None
    return None


@dataclass(frozen=True)
class AdbDeviceSpec:
    """一个 adb 设备号 + 它所属的游戏进程 PID。"""

    serial: str
    game_pid: int


def _probe_devices(
    adb: Path,
    game_package: str,
    runner: Callable[[Path, list[str]], subprocess.CompletedProcess],
) -> tuple[dict[int, str], list[str], str, list[str]]:
    """列一次设备，返回（游戏进程→设备号, offline设备, 原始输出, 在线设备）。"""
    listed = runner(adb, ["devices"])
    _raise_on_adb_error(listed, "设备发现")
    output = _output_bytes(listed).decode("utf-8", "replace")

    by_pid: dict[int, str] = {}
    offline: list[str] = []
    online: list[str] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        serial, state = fields[0], fields[1]
        if state == "offline":
            offline.append(serial)
            continue
        if state != "device":
            continue
        online.append(serial)
        pid_result = runner(adb, ["-s", serial, "shell", "pidof", game_package])
        pid_text = _output_bytes(pid_result).decode("utf-8", "replace").strip()
        # pidof 可能返回多个 PID（多进程游戏），取第一个非数字过滤后的值。
        pids = [int(token) for token in pid_text.split() if token.isdigit()]
        if pids and pids[0] not in by_pid:
            by_pid[pids[0]] = serial
    return by_pid, offline, output, online


def _repair_adb(
    adb: Path,
    runner: Callable[[Path, list[str]], subprocess.CompletedProcess],
    commands: tuple[list[str], ...],
) -> None:
    """有界修复 ADB 连接；修没修好由随后那次``devices``复查判定，不在这里猜。"""
    for command in commands:
        try:
            runner(adb, command)
        except (OSError, subprocess.SubprocessError, RuntimeError):
            pass


def discover_game_device(
    adb: Path,
    *,
    game_package: str = GAME_PACKAGE,
    runner: Callable[[Path, list[str]], subprocess.CompletedProcess] = _run,
) -> AdbDeviceSpec:
    """找到唯一一个「正在跑第七史诗」的 adb 设备。

    MuMu 单实例会监听多个端口（7555 / 16384 / 5555 / emulator-5554），
    ``adb devices`` 因此列出多个设备号；它们指向同一个游戏进程（pidof 同 PID）。
    这里按游戏 PID 去重，只保留每个 PID 的第一个设备号。

    设备 offline 或 adb 服务刚冷启动时，先有界自修连接（重连 → 重建服务）再判定；
    两步都修不回来仍明确报错。只支持单开：去重后仍多于一个实例 ⇒ 明确报错，不猜用哪个。
    """
    by_pid, offline, output, online = _probe_devices(adb, game_package, runner)
    repairs = 0

    if not by_pid and (
        offline or any(marker in output.lower() for marker in _DAEMON_START_MARKERS)
    ):
        _repair_adb(adb, runner, (["reconnect", "offline"],))
        repairs = 1
        by_pid, offline, output, online = _probe_devices(adb, game_package, runner)

        # 重连后设备已在线却没游戏进程 ⇒ 是「游戏没开」，不是连接故障，不再折腾服务。
        if not by_pid and (not online or offline):
            _repair_adb(adb, runner, (["kill-server"], ["start-server"]))
            repairs = 2
            by_pid, offline, output, online = _probe_devices(adb, game_package, runner)

    if len(by_pid) > 1:
        devices = ", ".join(sorted(by_pid.values()))
        raise EmulatorNotFound(
            "检测到多个正在运行第七史诗的模拟器实例，当前只支持单开。"
            f"请只保留一个（在线设备：{devices}）后重试"
        )
    if not by_pid:
        hint = ""
        if offline:
            hint = f"（设备 {', '.join(offline)} 处于 offline，请重启模拟器）"
        repaired = f"；已自动修复 ADB 连接 {repairs} 次仍未恢复" if repairs else ""
        raise EmulatorNotFound(
            "未找到正在运行第七史诗的安卓模拟器。"
            "请先打开模拟器并让游戏停在大厅，再开始任务" + hint + repaired
        )
    pid, serial = next(iter(by_pid.items()))
    return AdbDeviceSpec(serial=serial, game_pid=pid)


class AdbEmulatorClient:
    """封装单个 adb 设备的抓图与输入。仅负责 I/O，不碰任何游戏判据。"""

    def __init__(
        self,
        adb: Path,
        device: AdbDeviceSpec,
        *,
        emit: Callable[[str], None] | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = _run,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.adb = adb
        self.device = device
        self._emit = emit or (lambda _message: None)
        self._runner = runner
        self._sleep = sleep_fn

    def _base(self) -> list[str]:
        return ["-s", self.device.serial]

    def run_raw(self, command: str, *, timeout: float = _ADB_TIMEOUT) -> bytes:
        """执行一条原始 adb 命令（如 ``shell input tap 1 2`` / ``pull a b``）。

        竖屏通道 ``PortraitChannel`` 的命令正是这种形式（``shell input tap …``），
        复用它就能让竖屏段不用再拼 ldconsole 私有格式。

        ⚠️⚠️ **参数用 ``shlex.split`` 按 POSIX 规则切分：Windows 路径里的反斜杠会被
        当转义符吃掉**（``D:\\Cache\\Temp\\x.png`` → ``D:CacheTempx.png``，落到当前目录）。
        2026-11-24 的竖屏截图就是这么坏了整整三天：``pull`` 写到别处、读的却是旧文件，
        adb 还返回 0。⇒ **带本地路径的命令一律别走这里**；要么用 ``screencap_bgr`` 这类
        已经成形的方法，要么把路径写成 ``/`` 分隔（``C:/tmp/x.png``）。
        """
        args = shlex.split(command)
        result = self._runner(self.adb, [*self._base(), *args], timeout=timeout)
        _raise_on_adb_error(result, "指令")
        return _output_bytes(result)

    def run_shell(self, command: str) -> bytes:
        """执行 ``adb shell <command>``，返回原始输出字节。"""
        result = self._runner(self.adb, [*self._base(), "shell", command])
        _raise_on_adb_error(result, "指令")
        return _output_bytes(result)

    def screencap_bgr(self) -> np.ndarray:
        """抓一帧 BGR 画面（任意尺寸，供竖屏方向判定用）。调用失败重试。"""
        last_error: RuntimeError | None = None
        for attempt in range(_CAPTURE_ATTEMPTS):
            result = self._runner(
                self.adb,
                [*self._base(), "exec-out", "screencap", "-p"],
                timeout=_ADB_TIMEOUT,
            )
            if result.returncode == 0:
                data = bytes(result.stdout)
                # ⚠️ 用原始字节直接解码：本机实测 exec-out 出来的 PNG 头是合法的
                # \x89PNG\r\n\x1a\n，做 \r\n→\n 替换反而会破坏它（2026-11-21 踩过）。
                try:
                    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                except Exception:  # noqa: BLE001 —— 解码失败按「调用失败」重试
                    frame = None
                if frame is not None:
                    return frame
                last_error = RuntimeError("模拟器截图解码失败")
            else:
                last_error = RuntimeError(
                    f"模拟器截图调用失败：{_output_bytes(result).decode('utf-8', 'replace')[:100]}"
                )
            if attempt + 1 < _CAPTURE_ATTEMPTS:
                self._sleep(_CAPTURE_RETRY_SECONDS)
        raise RuntimeError(
            f"模拟器窗口截图调用失败（连续 {_CAPTURE_ATTEMPTS} 次取不到画面）：{last_error}"
        )

    def capture_render(self) -> np.ndarray:
        """抓一帧 1920x1080 的 BGR 渲染画面（横屏段用；尺寸不对明确报错）。"""
        frame = self.screencap_bgr()
        if tuple(frame.shape[1::-1]) != _RENDER_SIZE:
            raise RuntimeError(
                f"模拟器画面尺寸异常：{frame.shape[1]}x{frame.shape[0]}，"
                f"应为 {_RENDER_SIZE[0]}x{_RENDER_SIZE[1]}；"
                "请在模拟器设置里把分辨率调为 1920x1080（横屏）"
            )
        return frame

    def tap(self, x: int, y: int) -> None:
        result = self._runner(self.adb, [*self._base(), "shell", "input", "tap", str(x), str(y)])
        _raise_on_adb_error(result, "点击")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        result = self._runner(
            self.adb,
            [
                *self._base(), "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration_ms),
            ],
        )
        _raise_on_adb_error(result, "滑动")

    def back(self) -> None:
        result = self._runner(self.adb, [*self._base(), "shell", "input", "keyevent", "4"])
        _raise_on_adb_error(result, "返回")

    def probe(self) -> None:
        result = self._runner(self.adb, [*self._base(), "shell", "echo", "ping"])
        _raise_on_adb_error(result, "通道探测")
        if b"ping" not in _output_bytes(result).lower():
            raise RuntimeError("模拟器输入通道探测无回显")

    def description(self) -> str:
        return f"ADB 设备 {self.device.serial}（游戏进程 {self.device.game_pid}）"


__all__ = [
    "AdbDeviceSpec",
    "AdbEmulatorClient",
    "EmulatorNotFound",
    "GAME_PACKAGE",
    "discover_game_device",
    "find_adb",
]
