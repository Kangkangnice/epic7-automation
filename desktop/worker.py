"""Run the existing CLI in a child process and stream its output to the GUI."""

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from typing import Callable


@dataclass(frozen=True)
class RunRequest:
    mode: str
    cycles: int


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
    ) -> None:
        self.repo_parent = repo_parent
        self._popen = popen
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._events: queue.Queue[WorkerEvent] = queue.Queue()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.stop_file: Path | None = None

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
        command = [
            sys.executable,
            "-u",
            "-m",
            "auto_game_unified.main",
            "--mode",
            request.mode,
            "--window-backend",
            "emulator",
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
        self.stop_file.write_text("stop\n", encoding="utf-8")
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
                        self._events.put(WorkerEvent("log", message))
            exit_code = self._process.wait()
            messages = {
                0: "运行完成",
                1: "运行失败",
                2: "资源耗尽",
                130: "用户停止",
            }
            self._events.put(
                WorkerEvent(
                    "finished",
                    messages.get(exit_code, "工作进程异常结束"),
                    exit_code=exit_code,
                )
            )
        finally:
            self._cleanup_temporary()

    def _cleanup_temporary(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
