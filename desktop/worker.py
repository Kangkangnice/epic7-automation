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
from typing import Callable


@dataclass(frozen=True)
class RunRequest:
    mode: str
    cycles: int
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
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        log_path: Path | None = None,
        max_log_bytes: int = 5 * 1024 * 1024,
        log_backups: int = 4,
        snapshot_limit: int = 30,
    ) -> None:
        self.repo_parent = repo_parent
        self._popen = popen
        self.log_path = log_path or (
            repo_parent / "auto_game_unified" / "runtime_logs" / "desktop_worker.log"
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
        self._request: RunRequest | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, request: RunRequest) -> None:
        if self.running:
            raise RuntimeError("已有自动化任务正在运行")
        if request.cycles <= 0:
            raise ValueError("运行次数必须是正整数")

        self._temporary = tempfile.TemporaryDirectory(
            prefix="epic7-auto-assistant-"
        )
        self.stop_file = Path(self._temporary.name) / "stop.signal"
        self._last_output = "-"
        self._recent_output.clear()
        self._stop_requested = False
        self._request = request
        command = [
            sys.executable,
            "-u",
            "-m",
            "auto_game_unified.main",
            "--mode",
            request.mode,
            "--window-backend",
            request.backend,
            "--max-cycles",
            str(request.cycles),
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

        self._write_evidence(
            f"事件=启动 模式={request.mode} 后端={request.backend} "
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
        if exit_code in {0, 2, 130} or self._request is None:
            return None
        project_root = self.repo_parent / "auto_game_unified"
        source = (
            project_root
            / "runtime_diagnostics"
            / f"epic7_{self._request.mode}"
            / "current.png"
        )
        if not source.exists():
            return None
        destination_dir = project_root / "runtime_diagnostics" / "desktop_worker"
        destination_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = (
            destination_dir
            / f"{timestamp}_{self._request.mode}_exit_{exit_code}.png"
        )
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
