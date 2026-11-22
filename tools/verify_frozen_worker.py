"""离线验证冻结版的 worker 交接：只起一个业务子进程，不开第二个界面。

它把当前进程伪装成「已打包的桌面端」：``sys.frozen = True``、``sys.executable``
指向真实产物，然后走桌面端**同一条** ``WorkerController.start()``。子进程跑的是
``--offline-probe``：只等停止信号，不装配路线、不截图、不点击 —— 即使游戏已经
打开、权限也匹配，这条路径也不会碰它。

验两件事：①探针到时正常结束（退出码 0）；②父进程写 stop.signal 后，子进程读到
并退出 130。

用法（工作目录随意，用装了 psutil 的解释器）::

    python tools/verify_frozen_worker.py --exe packaging/dist/ArkyAssistant/ArkyAssistant.exe
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

import psutil

REPO = Path(__file__).resolve().parents[1]
if str(REPO.parent) not in sys.path:
    sys.path.insert(0, str(REPO.parent))

from auto_game_unified.desktop.worker import RunRequest, WorkerController  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def visible_windows(pid: int) -> list[str]:
    """该进程当前拥有的可见顶层窗口标题。"""
    titles: list[str] = []
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
    )

    def callback(hwnd, _lparam):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            titles.append(buffer.value)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return titles


def children_of_this_process() -> list[psutil.Process]:
    return [child for child in psutil.Process().children(recursive=True)]


class Probe:
    """在后台记录子进程的映像名、命令行与窗口，直到父进程收尾。"""

    def __init__(self) -> None:
        self.processes: list[dict] = []
        self.windowed: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        seen: set[int] = set()
        while not self._stop.is_set():
            for child in children_of_this_process():
                try:
                    info = {
                        "pid": child.pid,
                        "name": child.name(),
                        "cmdline": child.cmdline(),
                    }
                    windows = visible_windows(child.pid)
                except (psutil.Error, OSError):
                    continue
                if child.pid not in seen:
                    seen.add(child.pid)
                    self.processes.append(info)
                if windows:
                    self.windowed.append({"pid": child.pid, "titles": windows})
            time.sleep(0.1)


def run_once(exe: Path, backend: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="arky-worker-") as data:
        os.environ["EPIC7_DATA_DIR"] = data
        probe = Probe()
        worker = WorkerController(repo_parent=exe.parent, data_root=Path(data))
        probe.start()
        worker.start(
            RunRequest(("arena",), {"arena": 1}, backend, offline_probe_seconds=2.0)
        )
        worker.join_reader(timeout=300)
        probe.stop()
        events = worker.drain_events()
        exit_codes = [event.exit_code for event in events if event.kind == "finished"]
        logs = [event.message for event in events if event.kind == "log"]
        return {
            "exit_code": exit_codes[-1] if exit_codes else None,
            "log_lines": logs,
            "processes": probe.processes,
            "windows": probe.windowed,
            "child_command": list(worker._process.args) if worker._process else [],  # noqa: SLF001
        }


def run_stop_probe(exe: Path, backend: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="arky-worker-stop-") as data:
        os.environ["EPIC7_DATA_DIR"] = data
        worker = WorkerController(repo_parent=exe.parent, data_root=Path(data))
        worker.start(
            RunRequest(("arena",), {"arena": 1}, backend, offline_probe_seconds=60.0)
        )
        was_running = worker.running
        worker.request_stop()
        stop_file = worker.stop_file
        stop_written = bool(stop_file and stop_file.exists())
        worker.join_reader(timeout=300)
        events = worker.drain_events()
        exit_codes = [event.exit_code for event in events if event.kind == "finished"]
        return {
            "was_running_when_requested": was_running,
            "stop_file": str(stop_file) if stop_file else None,
            "stop_file_written": stop_written,
            "exit_code": exit_codes[-1] if exit_codes else None,
            "messages": [event.message for event in events],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线验证冻结版 worker 交接")
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--backend", default="pc")
    parser.add_argument("--out", type=Path, help="把结果写成 JSON")
    args = parser.parse_args(argv)

    exe = args.exe.resolve()
    if not exe.is_file():
        raise SystemExit(f"找不到产物：{exe}")

    had_frozen = hasattr(sys, "frozen")
    saved_executable = sys.executable
    sys.frozen = True
    sys.executable = str(exe)
    try:
        handoff = run_once(exe, args.backend)
        stop = run_stop_probe(exe, args.backend)
    finally:
        if not had_frozen:
            del sys.frozen
        sys.executable = saved_executable

    payload = {
        "exe": str(exe),
        "sha256": sha256(exe),
        "python": sys.version.split()[0],
        "handoff": handoff,
        "stop": stop,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")

    problems: list[str] = []
    for process in handoff["processes"]:
        if "python" in process["name"].lower():
            problems.append(f"子进程用了系统解释器：{process}")
        if "--worker" not in process["cmdline"]:
            problems.append(f"子进程命令行没有 --worker：{process}")
        if "--offline-probe" not in process["cmdline"]:
            problems.append(f"子进程不是离线探针：{process}")
        if "--live" in process["cmdline"]:
            problems.append(f"离线探针不应带 --live：{process}")
        if "--offline-probe" not in process["cmdline"]:
            problems.append(f"子进程不是离线探针：{process}")
        if "--live" in process["cmdline"]:
            problems.append(f"离线探针不应带 --live：{process}")
    if handoff["windows"]:
        problems.append(f"子进程开了窗口（应为纯命令行）：{handoff['windows']}")
    if handoff["exit_code"] != 0:
        problems.append(f"正常结束的退出码不是 0：{handoff['exit_code']}")
    if not any("正常结束" in line for line in handoff["log_lines"]):
        problems.append("没有收到探针的正常结束输出")
    if not stop["stop_file_written"]:
        problems.append("停止请求没有写出 stop.signal")
    if stop["exit_code"] != 130:
        problems.append(f"停止后退出码不是 130：{stop['exit_code']}")
    if not any("收到停止请求" in message for message in stop["messages"]):
        problems.append("子进程没有消费停止请求")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
