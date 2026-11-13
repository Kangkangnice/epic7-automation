"""跑完自动关机：把「到点关电脑」这件事从界面里拆出来。

## 为什么要单独一层

界面里直接写一行 ``subprocess.run(["shutdown", ...])`` 也能用，但那样：
命令拼错 / 没有权限时只会静默失败，界面拿不到「到底排上了没有」；
测试也没法验「究竟发了哪条命令」。所以这里只做两件事 —— **排定**与**撤销**，
命令执行可注入（与 ``desktop/worker.py`` 的 ``popen`` 同一个理由）。

## 三条硬约定

1. **只做「关机」这一件事**：排定是 ``shutdown /s /t 60``，撤销是 ``shutdown /a``。
   不睡眠、不注销、不关机箱盖 —— 用户要的是把机器关掉。
2. **失败不抛异常**：命令不存在 / 权限不足 / 被策略拦下，一律返回 ``False``，
   由调用方写一行日志了事。关不掉不该把界面弄崩。
3. **撤销一律清掉本地状态**：``shutdown /a`` 说「没有排定的关机」也算处理完了，
   再喊一次不会有别的结果。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Sequence

# 60 秒是给「人还在电脑前」留的后悔时间。任务一结束就黑屏是最难解释的意外，
# 而真躺下睡了的人也不差这一分钟。
SHUTDOWN_DELAY_SECONDS = 60


def shutdown_exe() -> str:
    """``shutdown.exe`` 的绝对路径。

    打包成免安装版之后 PATH 不一定带 System32，靠 PATH 找会变成「静默不关机」。
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return str(Path(root) / "System32" / "shutdown.exe")


class ShutdownScheduler:
    """排定 / 撤销一次延时关机。``scheduled`` 是「本程序认为已经排定了」。"""

    def __init__(
        self,
        *,
        delay_seconds: int = SHUTDOWN_DELAY_SECONDS,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        exe: str | None = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self._run = run
        self._exe = exe or shutdown_exe()
        self.scheduled = False

    def schedule(self) -> bool:
        """排定一次延时关机；返回是否真的排上了。"""
        if not self._call([self._exe, "/s", "/t", str(self.delay_seconds)]):
            return False
        self.scheduled = True
        return True

    def cancel(self) -> bool:
        """撤销已排定的关机；返回命令是否执行成功。"""
        cancelled = self._call([self._exe, "/a"])
        self.scheduled = False
        return cancelled

    def _call(self, command: Sequence[str]) -> bool:
        try:
            completed = self._run(
                list(command),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                # 免安装版是窗口程序，不加这个每次关机都会在屏幕上闪一个黑框。
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0
