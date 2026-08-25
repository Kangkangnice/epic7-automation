import threading

from auto_game_unified.desktop.worker import (
    RunRequest,
    WorkerController,
    WorkerEvent,
)


class FakeProcess:
    def __init__(self):
        self.stdout = iter(["第一行\n", "第二行\n"])
        self.returncode = None

    def wait(self):
        self.returncode = 0
        return 0

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
