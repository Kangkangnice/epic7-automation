"""跑完自动关机：只验「到底发了哪条命令」，绝不真的关机。"""

from pathlib import Path
from types import SimpleNamespace

from auto_game_unified.desktop.shutdown import (
    SHUTDOWN_DELAY_SECONDS,
    ShutdownScheduler,
    shutdown_exe,
)


class RecordingRun:
    """替身：记下每一次命令行，不真的执行。"""

    def __init__(self, returncode: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        return SimpleNamespace(returncode=self.returncode)


def test_schedule_asks_windows_for_a_delayed_shutdown(tmp_path):
    run = RecordingRun()
    exe = str(tmp_path / "shutdown.exe")
    scheduler = ShutdownScheduler(run=run, exe=exe)

    assert scheduler.schedule() is True
    # 延时必须是那个常量 —— 少写 /t 就是立刻关机，这是最不能出错的一位。
    assert run.commands == [[exe, "/s", "/t", str(SHUTDOWN_DELAY_SECONDS)]]
    assert scheduler.scheduled is True


def test_cancel_sends_the_abort_switch(tmp_path):
    run = RecordingRun()
    exe = str(tmp_path / "shutdown.exe")
    scheduler = ShutdownScheduler(run=run, exe=exe)
    scheduler.schedule()

    assert scheduler.cancel() is True
    assert run.commands[-1] == [exe, "/a"]
    assert scheduler.scheduled is False


def test_failed_command_reports_false_instead_of_raising(tmp_path):
    """被组策略拦下 / 没有权限：只返回 False，并且不许认为「已排定」。"""
    run = RecordingRun(returncode=1116)
    scheduler = ShutdownScheduler(run=run, exe=str(tmp_path / "shutdown.exe"))

    assert scheduler.schedule() is False
    assert scheduler.scheduled is False


def test_missing_executable_reports_false(tmp_path):
    def boom(command, **kwargs):
        raise FileNotFoundError(command[0])

    scheduler = ShutdownScheduler(run=boom, exe=str(tmp_path / "shutdown.exe"))

    assert scheduler.schedule() is False
    assert scheduler.cancel() is False


def test_shutdown_exe_is_an_absolute_path():
    """打包成免安装版之后 PATH 不一定带 System32，必须走绝对路径。"""
    path = Path(shutdown_exe())
    assert path.is_absolute()
    assert path.name.lower() == "shutdown.exe"
