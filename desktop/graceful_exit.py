"""关机前先请模拟器自己退出。

## 为什么必须有这一层（2026-11-14 实机事故）

「跑完自动关机」上线后，11-13、11-14 两次都是任务一结束就调 ``shutdown /s``。
系统日志记着关机那一刻：``dnplayer.exe`` 延迟 5 秒、``Ld9BoxHeadless.exe`` 延迟 11 秒
才被强行结束；而这两次的次日早上，Windows 都进了「启动修复」（``SrtTrail.txt``，
根本原因数 0 —— 系统文件、注册表、SSD 全都没毛病，只是启动流程被打断）。
用户手动关机从没出过事，因为他会**先关模拟器**。

⇒ 关电脑之前必须先让模拟器**自己退出**，等它退干净，再交给 ``shutdown``。
「直接杀进程」救不了这件事：强杀正是留下坏状态的那个动作。

## 一条硬约定

**等不到也要收场**：模拟器 60 秒还不退，仍然允许关机（日志写明「这次可能不干净」）。
否则用户睡前挂机一整晚，第二天发现电脑根本没关，比不干净更糟。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

#: 雷电每个实例的主进程。它一退，``Ld9BoxHeadless`` 这些容器进程也会跟着退。
EMULATOR_PROCESS = "dnplayer.exe"
#: 给它 60 秒自己退 —— 正常只要 5~15 秒，这个上限只用来兜住卡死的实例。
EMULATOR_QUIT_TIMEOUT_SECONDS = 60.0


def emulator_player_paths() -> tuple[Path, ...]:
    """正在运行的雷电实例可执行文件路径；空 = 没开模拟器。

    从进程路径（而不是写死 ``D:\\leidian\\...``）反推安装目录，用户换盘、装两份都能用。
    """
    import psutil

    paths: list[Path] = []
    for process in psutil.process_iter(["name", "exe"]):
        try:
            info = process.info
            name = (info.get("name") or "").lower()
            exe = info.get("exe")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name == EMULATOR_PROCESS and exe:
            paths.append(Path(exe))
    return tuple(paths)


def emulator_running() -> bool:
    return bool(emulator_player_paths())


def request_quit_all(
    console: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """调雷电控制台的 ``quitall``，请**所有**实例自己退出。

    用 ``quitall`` 而不是 ``quit --index N``：用户开几个实例、开的是哪个都不用我们猜。
    """
    try:
        completed = run(
            [str(console), "quitall"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def quit_running_emulators(
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """对每个安装目录各喊一次 ``quitall``；返回是否至少喊成了一次。"""
    consoles = {
        player.with_name("ldconsole.exe")
        for player in emulator_player_paths()
        if player.with_name("ldconsole.exe").exists()
    }
    requested = False
    for console in consoles:
        if request_quit_all(console, run=run):
            requested = True
    return requested


class EmulatorQuitGate:
    """「等模拟器退干净」的状态机；界面只负责每秒问一次，不用自己算时间。

    ``begin()`` 三种结果对应界面三条日志，不要合并成一个布尔 ——
    「本来就没开模拟器」和「请它退出失败」在日志里是两件事。
    """

    def __init__(
        self,
        *,
        is_running: Callable[[], bool] = emulator_running,
        quit_all: Callable[[], bool] = quit_running_emulators,
        timeout_seconds: float = EMULATOR_QUIT_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._is_running = is_running
        self._quit_all = quit_all
        self.timeout_seconds = timeout_seconds
        self._clock = clock
        self._deadline = 0.0
        self.state = "idle"

    def begin(self) -> str:
        """``'no_emulator'`` / ``'quit_failed'`` / ``'waiting'``。"""
        if not self._is_running():
            self.state = "done"
            return "no_emulator"
        if not self._quit_all():
            # 找不到控制台 / 命令失败：不装死，按原来的流程关机（日志会写明）。
            self.state = "done"
            return "quit_failed"
        self._deadline = self._clock() + self.timeout_seconds
        self.state = "waiting"
        return "waiting"

    def poll(self) -> str:
        """``'waiting'`` 继续等 / ``'done'`` 可以关机 / ``'timeout'`` 等超时了（也关机）。"""
        if self.state != "waiting":
            return "done"
        if not self._is_running():
            self.state = "done"
            return "done"
        if self._clock() >= self._deadline:
            self.state = "timeout"
            return "timeout"
        return "waiting"
