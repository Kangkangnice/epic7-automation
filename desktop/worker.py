"""Run the existing CLI in a child process and stream its output to the GUI."""

from dataclasses import dataclass
from datetime import datetime
from collections import deque
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Callable, Mapping


@dataclass(frozen=True)
class RunRequest:
    """一次「每日任务」：跑哪几条路线、每条几次。

    ⚠️ ``modes`` 的**次序就是执行顺序**（勾选先后由界面记着，这里不再重排）。
    勾一条也走这一套 —— 界面上不再有「单路线运行」那条独立通道，两条路合一之后
    「勾一条 = 跑一条」，行为与以前逐字相同。
    """

    modes: tuple[str, ...]
    # 每条路线跑几次。**只带勾选的那几条**（界面看到什么就传什么）；没进来的
    # 路线按该路线自己的默认值跑 —— 命令行 ``--daily`` 就是这种用法。
    cycles: Mapping[str, int]
    backend: str = "emulator"


@dataclass(frozen=True)
class WorkerEvent:
    kind: str
    message: str
    exit_code: int | None = None


class WorkerController:
    def __init__(
        self,
        *,
        repo_parent: Path,
        data_root: Path | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        log_path: Path | None = None,
        max_log_bytes: int = 5 * 1024 * 1024,
        log_backups: int = 4,
        snapshot_limit: int = 30,
    ) -> None:
        self.repo_parent = repo_parent
        # 运行产物（工作进程日志、失败快照）的根目录。打包安装后由 app 传入
        # %LOCALAPPDATA%\Epic7AutoAssistant；源码运行时退回包目录，与原来一致。
        self.data_root = data_root or (repo_parent / "auto_game_unified")
        self._popen = popen
        self.log_path = log_path or (
            self.data_root / "runtime_logs" / "desktop_worker.log"
        )
        self.max_log_bytes = max_log_bytes
        self.log_backups = log_backups
        self.snapshot_limit = snapshot_limit
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._events: queue.Queue[WorkerEvent] = queue.Queue()
        self._evidence_lock = threading.Lock()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.stop_file: Path | None = None
        self._last_output = "-"
        self._recent_output: deque[str] = deque(maxlen=50)
        self._stop_requested = False
        self._force_stopped = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, request: RunRequest) -> None:
        if self.running:
            raise RuntimeError("已有自动化任务正在运行")
        if not request.modes:
            raise ValueError("至少要勾选一条路线")
        # 次数下限由路线的 ``ModeSpec.min_cycles`` 决定（正常是 1；「刷书签」是 0
        # —— 只扫一遍、不付费刷新）。延迟 import 避免 desktop ⇄ games 模块成环。
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        for mode in request.modes:
            minimum = MODE_SPECS[mode].min_cycles
            if request.cycles.get(mode, 1) < minimum:
                raise ValueError(
                    "运行次数不能为负数" if minimum == 0 else "运行次数必须是正整数"
                )

        self._temporary = tempfile.TemporaryDirectory(
            prefix="epic7-auto-assistant-"
        )
        self.stop_file = Path(self._temporary.name) / "stop.signal"
        self._last_output = "-"
        self._recent_output.clear()
        self._stop_requested = False
        self._force_stopped = False
        # 次数写在 ``--daily-tasks`` 里（``世界首领战:2,竞技场:3``）；界面每次都把
        # 勾选那几条的次数原样传下来 ⇒ 命令行里写的就是界面上看到的。
        # 界面**没有**传次的路线（命令行 ``--daily`` 的用法）就用该路线自己的默认值。
        # ``Joinable``：``modes`` 是已校验的模式名，不会有逗号或冒号。
        daily_arg = ",".join(
            f"{mode}:{request.cycles[mode]}" if mode in request.cycles else mode
            for mode in request.modes
        )
        command = [
            sys.executable,
            "-u",
            "-m",
            "auto_game_unified.main",
            "--daily",
            "--daily-tasks",
            daily_arg,
            "--window-backend",
            request.backend,
            "--live",
            "--confirm",
            "RUN",
            "--stop-file",
            str(self.stop_file),
        ]
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            self._process = self._popen(
                command,
                cwd=str(self.repo_parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            self._cleanup_temporary()
            raise

        started_label = "每日任务(" + ",".join(request.modes) + ")"
        self._write_evidence(
            f"事件=启动 模式={started_label} 后端={request.backend} "
            f"PID={getattr(self._process, 'pid', '-')}"
        )
        self._events.put(WorkerEvent("started", "自动化已启动"))
        self._reader = threading.Thread(
            target=self._read_output,
            name="epic7-worker-output",
            daemon=True,
        )
        self._reader.start()

    def request_stop(self) -> None:
        if not self.running or self.stop_file is None:
            return
        self._stop_requested = True
        self.stop_file.write_text("stop\n", encoding="utf-8")
        self._write_evidence(
            f"事件=停止请求 PID={getattr(self._process, 'pid', '-')}"
        )
        self._events.put(WorkerEvent("stopping", "正在安全停止"))

    def force_stop(self) -> bool:
        """**强行**结束工作进程 —— 停止信号喊不动时的兜底，不是常规路径。

        只有一种情况会走到这里：工作进程卡在**某次底层调用的内部**，永远轮不到
        「动作之间查停止信号」那一步（2026-09-28 实机取证：`epic7_world_boss.log`
        停在 `执行点击 动作=进入骑士团`、进程 CPU 差值为 0、`stop.signal` 已写出）。
        那时界面会一直等，而它永远不会自己退 —— 只能直接结束它。

        ⚠️ **不等它收尾**：卡住的进程不可能再自己退出，也别指望 ``事件=结束``
        一定会写出来（读输出的线程可能正卡在那条阻塞的管道上）。
        ⇒ 所以调用方必须**自己**把界面状态收回来，不能等 ``finished`` 事件。

        ⚠️ 它派生的孙进程（``ldconsole.exe`` 拉起的 ``adb.exe``）**不会跟着结束**，
        会变成孤儿挂着；这不影响界面解锁，也不影响下次运行。

        返回是否真的结束了进程（没在跑就返回 ``False``）。
        """
        if not self.running:
            return False
        process = self._process
        assert process is not None
        pid = getattr(process, "pid", "-")
        # 标记要在 kill **之前**设：读输出的线程会在子进程一死就被唤醒，它靠这个标记
        # 把「被强行结束」和自己的退出码区分开（见 ``_read_output``）。
        self._force_stopped = True
        try:
            process.kill()
        except OSError as error:
            self._force_stopped = False
            self._write_evidence(f"事件=强行结束失败 PID={pid} 原因={error}")
            return False
        self._write_evidence(f"事件=强行结束 PID={pid}")
        return True

    def drain_events(self) -> list[WorkerEvent]:
        events: list[WorkerEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def join_reader(self, timeout: float | None = None) -> None:
        if self._reader is not None:
            self._reader.join(timeout)

    def _read_output(self) -> None:
        assert self._process is not None
        try:
            if self._process.stdout is not None:
                for raw_line in self._process.stdout:
                    message = raw_line.rstrip("\r\n")
                    if message:
                        self._last_output = message
                        self._recent_output.append(message)
                        self._events.put(WorkerEvent("log", message))
            exit_code = self._process.wait()
            messages = {
                0: "运行完成",
                1: "运行失败",
                2: "资源耗尽",
                130: "用户停止",
            }
            if self._force_stopped:
                # 强行结束走的是 TerminateProcess，退出码是 **1** —— 与「运行失败」同码。
                # 不看这个标记就会把「用户点了停止、助手替它收尾」报成「运行失败」，
                # 跟界面上的「已强行结束」自相矛盾。
                message = "已强行结束"
            else:
                message = messages.get(
                    exit_code,
                    f"工作进程异常结束（退出码 {exit_code}）",
                )
            snapshot = self._snapshot_current_frame(exit_code)
            if exit_code not in {0, 2, 130}:
                for output in self._recent_output:
                    self._write_evidence(
                        f"事件=子进程输出 "
                        f"PID={getattr(self._process, 'pid', '-')} 内容={output}"
                    )
            self._write_evidence(
                f"事件=结束 PID={getattr(self._process, 'pid', '-')} "
                f"退出码={exit_code} "
                f"停止请求={'是' if self._stop_requested else '否'} "
                f"强行结束={'是' if self._force_stopped else '否'} "
                f"最后输出={self._last_output} "
                f"现场={snapshot if snapshot is not None else '-'}"
            )
            self._events.put(
                WorkerEvent(
                    "finished",
                    message,
                    exit_code=exit_code,
                )
            )
        finally:
            self._cleanup_temporary()

    def _write_evidence(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} {message}\n"
        with self._evidence_lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if (
                self.log_path.exists()
                and self.log_path.stat().st_size + len(line.encode("utf-8"))
                > self.max_log_bytes
            ):
                self._rotate_evidence_logs()
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line)

    def _rotate_evidence_logs(self) -> None:
        oldest = Path(f"{self.log_path}.{self.log_backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.log_backups - 1, 0, -1):
            source = Path(f"{self.log_path}.{index}")
            if source.exists():
                source.replace(Path(f"{self.log_path}.{index + 1}"))
        if self.log_path.exists():
            self.log_path.replace(Path(f"{self.log_path}.1"))

    def _snapshot_current_frame(self, exit_code: int) -> Path | None:
        if exit_code in {0, 2, 130}:
            return None
        root = self.data_root
        # 一次可能跑了好几条路线，每条各写各的 ``epic7_<模式>/current.png``。
        # 出问题的那条一定是刚写过的那条 ⇒ 取**最新**的一张存下来，
        # 不去猜「是哪条路线挂的」（猜错会把别的路线的旧帧当成现场）。
        candidates = list(
            (root / "runtime_diagnostics").glob("epic7_*/current.png")
        )
        if not candidates:
            return None
        try:
            source = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        except OSError:
            return None
        destination_dir = root / "runtime_diagnostics" / "desktop_worker"
        destination_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        route = source.parent.name.removeprefix("epic7_")
        destination = destination_dir / f"{timestamp}_{route}_exit_{exit_code}.png"
        shutil.copy2(source, destination)
        self._prune_failure_snapshots(destination_dir)
        return destination

    def _prune_failure_snapshots(self, destination_dir: Path) -> None:
        if self.snapshot_limit < 1:
            return
        snapshots = sorted(
            destination_dir.glob("*.png"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in snapshots[: -self.snapshot_limit]:
            path.unlink()

    def _cleanup_temporary(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
