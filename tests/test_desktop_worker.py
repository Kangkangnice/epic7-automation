import threading

import pytest

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


class StuckProcess:
    """卡在一次底层调用里、**读不到停止信号**的进程（2026-09-28 实机现场）。

    ``BlockingOutput`` 让读输出的线程一起卡住 —— 真实的卡死正是这个形态：进程不退、
    管道那头也不吐字，界面于是既等不到 ``事件=结束``、又等不到新日志。
    """

    def __init__(self, *, release, pid=8224):
        self.stdout = BlockingOutput(release)
        self.returncode = None
        self.killed = False
        self.pid = pid

    def wait(self):
        self.returncode = 130
        return 130

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_worker_builds_existing_live_cli_and_streams_logs(tmp_path):
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs))
        or FakeProcess(),
    )

    worker.start(RunRequest("story", 3))
    worker.join_reader()

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
    worker.join_reader()

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
    worker.join_reader()
    assert worker.drain_events()[-1] == WorkerEvent(
        "finished", "用户停止", exit_code=130
    )


def test_force_stop_is_a_noop_when_nothing_is_running(tmp_path):
    worker = WorkerController(repo_parent=tmp_path)

    assert worker.force_stop() is False


def test_force_stop_kills_a_worker_that_never_reads_the_stop_signal(tmp_path):
    """2026-09-28 实机：卡在一次 adb 点击里的进程，停止信号永远读不到。

    ``request_stop`` 只把 ``stop.signal`` 写下去，那条信号要等下一次「动作之间」才被
    读到；卡在调用内部的进程轮不到那一步 ⇒ 只能强行结束，而且必须**立刻**见效：
    界面靠 ``running`` 变 False 解锁，等不到 ``事件=结束``。
    """
    release = threading.Event()
    process = StuckProcess(release=release, pid=8224)
    log_path = tmp_path / "desktop_worker.log"
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: process,
        log_path=log_path,
    )
    worker.start(RunRequest("world_boss", 2))

    worker.request_stop()

    assert worker.stop_file is not None and worker.stop_file.exists()
    assert worker.running is True, "写了停止信号不等于进程会退"
    assert worker.force_stop() is True
    assert process.killed is True
    assert worker.running is False, "强行结束后界面必须能立刻解锁"
    assert "事件=强行结束 PID=8224" in log_path.read_text(encoding="utf-8")

    release.set()
    worker.join_reader()

    # 强行结束用的是 TerminateProcess，退出码 1 与「运行失败」同码 ⇒ 靠标记区分开，
    # 否则界面上会一边说「已强行结束」、一边报「运行失败」。
    assert worker.drain_events()[-1] == WorkerEvent(
        "finished", "已强行结束", exit_code=130
    )
    assert "强行结束=是" in log_path.read_text(encoding="utf-8")


def test_worker_persists_process_exit_evidence(tmp_path):
    log_path = tmp_path / "desktop_worker.log"
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: FakeProcess(pid=2468),
        log_path=log_path,
    )

    worker.start(RunRequest("arena", 5, "pc"))
    worker.join_reader()

    evidence = log_path.read_text(encoding="utf-8")
    assert "事件=启动 模式=arena 后端=pc PID=2468" in evidence
    # 「强行结束」必须**显式记否** —— 只有「是」而没有「否」的话，排查时读不出
    # 这一条到底带没带这个字段。
    assert (
        "事件=结束 PID=2468 退出码=0 停止请求=否 强行结束=否 最后输出=第二行"
        in evidence
    )


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
    worker.join_reader()

    assert worker.drain_events()[-1] == WorkerEvent(
        "finished", "工作进程异常结束（退出码 23）", exit_code=23
    )
    evidence = log_path.read_text(encoding="utf-8")
    assert "事件=子进程输出 PID=1357 内容=第一行" in evidence
    assert "事件=子进程输出 PID=1357 内容=第二行" in evidence
    assert (
        "事件=结束 PID=1357 退出码=23 停止请求=否 强行结束=否 最后输出=第二行"
        in evidence
    )
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


def test_worker_rotates_evidence_log_and_discards_oldest_backup(tmp_path):
    log_path = tmp_path / "desktop_worker.log"
    worker = WorkerController(
        repo_parent=tmp_path,
        log_path=log_path,
        max_log_bytes=1,
        log_backups=2,
    )

    for message in ("第一条", "第二条", "第三条", "第四条"):
        worker._write_evidence(message)

    assert "第四条" in log_path.read_text(encoding="utf-8")
    assert "第三条" in (tmp_path / "desktop_worker.log.1").read_text(
        encoding="utf-8"
    )
    assert "第二条" in (tmp_path / "desktop_worker.log.2").read_text(
        encoding="utf-8"
    )
    assert not (tmp_path / "desktop_worker.log.3").exists()
    combined = "".join(
        path.read_text(encoding="utf-8")
        for path in (
            log_path,
            tmp_path / "desktop_worker.log.1",
            tmp_path / "desktop_worker.log.2",
        )
    )
    assert "第一条" not in combined


def test_worker_builds_daily_command_without_max_cycles(tmp_path):
    """每日任务走 ``--daily``，次数由各条路线自己的默认值定 ⇒ 不传 ``--max-cycles``。"""
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs))
        or FakeProcess(),
    )

    worker.start(
        RunRequest("arena", 1, daily_tasks=("world_boss", "knights_donation"))
    )
    worker.join_reader()

    command = calls[0][0]
    assert "--daily" in command
    assert command[command.index("--daily-tasks") + 1] == "world_boss,knights_donation"
    assert "--mode" not in command
    assert "--max-cycles" not in command
    assert command[command.index("--window-backend") + 1] == "emulator"
    assert "--live" in command
    assert command[command.index("--confirm") + 1] == "RUN"


def test_worker_writes_edited_daily_cycles_into_the_task_argument(tmp_path):
    """界面上改过的次数要跟着 ``--daily-tasks`` 走；没改的仍写成朴素的名字。

    两种写法并存是刻意的：命令行里写出来的就是「用户看到的那一套」，
    出问题照着日志能原样重跑；没改的那些保持短写，人看着不累。
    """
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    worker.start(
        RunRequest(
            "arena",
            1,
            daily_tasks=(
                "world_boss",
                "knights_donation",
                "shop_refresh",
                "labyrinth_stone",
                "arena",
            ),
            daily_cycles={"arena": 3},
        )
    )
    worker.join_reader()

    command = calls[0]
    assert command[command.index("--daily-tasks") + 1] == (
        "world_boss,knights_donation,shop_refresh,labyrinth_stone,arena:3"
    )
    assert "--max-cycles" not in command


def test_worker_rejects_daily_without_any_task(tmp_path):
    worker = WorkerController(repo_parent=tmp_path)

    with pytest.raises(ValueError, match="至少"):
        worker.start(RunRequest("arena", 1, daily_tasks=()))


def test_worker_rejects_non_positive_daily_cycles(tmp_path):
    worker = WorkerController(repo_parent=tmp_path)

    with pytest.raises(ValueError, match="正整数"):
        worker.start(
            RunRequest("arena", 1, daily_tasks=("arena",), daily_cycles={"arena": 0})
        )


def test_worker_evidence_labels_daily_runs(tmp_path):
    log_path = tmp_path / "desktop_worker.log"
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda *args, **kwargs: FakeProcess(pid=777),
        log_path=log_path,
    )

    worker.start(RunRequest("arena", 1, daily_tasks=("arena", "world_boss"), backend="pc"))
    worker.join_reader()

    evidence = log_path.read_text(encoding="utf-8")
    assert "事件=启动 模式=每日任务(arena,world_boss) 后端=pc PID=777" in evidence


def test_worker_keeps_only_latest_failure_snapshots(tmp_path):
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
        snapshot_limit=2,
    )
    worker._request = RunRequest("arena", 1, "pc")

    for exit_code in (21, 22, 23):
        worker._snapshot_current_frame(exit_code)

    snapshots = sorted(
        (
            tmp_path
            / "auto_game_unified"
            / "runtime_diagnostics"
            / "desktop_worker"
        ).glob("*.png")
    )
    assert len(snapshots) == 2
    assert snapshots[0].name.endswith("_arena_exit_22.png")
    assert snapshots[1].name.endswith("_arena_exit_23.png")
