import threading

from auto_game_unified.desktop.worker import (
    RunRequest,
    WorkerController,
    WorkerEvent,
)


class FakeProcess:
    def __init__(self, exit_code=0, pid=4321):
        self.stdout = iter(["第一行\n", "第二行\n"])
        self.returncode = None
        self.exit_code = exit_code
        self.pid = pid

    def wait(self):
        self.returncode = self.exit_code
        return self.exit_code

    def poll(self):
        return self.returncode


class BlockingOutput:
    def __init__(self, release):
        self.release = release

    def __iter__(self):
        return self

    def __next__(self):
        self.release.wait(timeout=2)
        raise StopIteration


class BlockingProcess:
    def __init__(self, release):
        self.stdout = BlockingOutput(release)
        self.returncode = None

    def wait(self):
        self.returncode = 130
        return 130

    def poll(self):
        return self.returncode


def test_worker_builds_existing_live_cli_and_streams_logs(tmp_path):
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs))
        or FakeProcess(),
    )

    worker.start(RunRequest("story", 3))
    worker.join_reader(timeout=1)

    command, options = calls[0]
    assert command[1:4] == ["-u", "-m", "auto_game_unified.main"]
    assert command[command.index("--mode") + 1] == "story"
    assert command[command.index("--max-cycles") + 1] == "3"
    assert options["cwd"] == str(tmp_path)
    events = worker.drain_events()
    assert [event.message for event in events if event.kind == "log"] == [
        "第一行",
        "第二行",
    ]
    assert events[-1] == WorkerEvent("finished", "运行完成", exit_code=0)


def test_worker_forwards_selected_window_backend(tmp_path):
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs))
        or FakeProcess(),
    )

    worker.start(RunRequest("story", 1, "pc"))
    worker.join_reader(timeout=1)

    command = calls[0][0]
    assert command[command.index("--window-backend") + 1] == "pc"


def test_worker_stop_creates_signal_file_before_process_exits(tmp_path):
    release = threading.Event()
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: BlockingProcess(release),
    )
    worker.start(RunRequest("hero_synthesis", 1))

    worker.request_stop()

    assert worker.stop_file is not None
    assert worker.stop_file.exists()
    release.set()
    worker.join_reader(timeout=1)
    assert worker.drain_events()[-1] == WorkerEvent(
        "finished", "用户停止", exit_code=130
    )


def test_worker_persists_process_exit_evidence(tmp_path):
    log_path = tmp_path / "desktop_worker.log"
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: FakeProcess(pid=2468),
        log_path=log_path,
    )

    worker.start(RunRequest("arena", 5, "pc"))
    worker.join_reader(timeout=1)

    evidence = log_path.read_text(encoding="utf-8")
    assert "事件=启动 模式=arena 后端=pc PID=2468" in evidence
    assert "事件=结束 PID=2468 退出码=0 停止请求=否 最后输出=第二行" in evidence


def test_worker_reports_and_persists_abnormal_exit_code(tmp_path):
    log_path = tmp_path / "desktop_worker.log"
    current = (
        tmp_path
        / "auto_game_unified"
        / "runtime_diagnostics"
        / "epic7_arena"
        / "current.png"
    )
    current.parent.mkdir(parents=True)
    current.write_bytes(b"latest arena frame")
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: FakeProcess(exit_code=23, pid=1357),
        log_path=log_path,
    )

    worker.start(RunRequest("arena", 1, "pc"))
    worker.join_reader(timeout=1)

    assert worker.drain_events()[-1] == WorkerEvent(
        "finished", "工作进程异常结束（退出码 23）", exit_code=23
    )
    evidence = log_path.read_text(encoding="utf-8")
    assert "事件=子进程输出 PID=1357 内容=第一行" in evidence
    assert "事件=子进程输出 PID=1357 内容=第二行" in evidence
    assert "事件=结束 PID=1357 退出码=23 停止请求=否 最后输出=第二行" in evidence
    snapshots = list(
        (
            tmp_path
            / "auto_game_unified"
            / "runtime_diagnostics"
            / "desktop_worker"
        ).glob("*_arena_exit_23.png")
    )
    assert len(snapshots) == 1
    assert snapshots[0].read_bytes() == b"latest arena frame"
    assert f"现场={snapshots[0]}" in evidence
