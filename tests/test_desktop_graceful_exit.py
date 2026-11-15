"""关机前请模拟器退出：只验命令与等待逻辑，绝不真的关模拟器、也绝不真的关机。"""

from types import SimpleNamespace

from auto_game_unified.desktop.graceful_exit import (
    EmulatorQuitGate,
    request_quit_all,
)


class RecordingRun:
    """替身：记下每一次命令行，不真的执行。"""

    def __init__(self, returncode: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        return SimpleNamespace(returncode=self.returncode)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_request_quit_all_asks_the_console_to_quit_every_instance(tmp_path):
    run = RecordingRun()
    console = tmp_path / "ldconsole.exe"

    assert request_quit_all(console, run=run) is True
    # 用 quitall 而不是 quit --index N：开几个实例、开的是哪个都不该由我们猜。
    assert run.commands == [[str(console), "quitall"]]


def test_request_quit_all_reports_false_when_the_command_fails(tmp_path):
    run = RecordingRun(returncode=1)
    assert request_quit_all(tmp_path / "ldconsole.exe", run=run) is False


def test_request_quit_all_never_raises_when_console_is_missing(tmp_path):
    def boom(command, **kwargs):
        raise FileNotFoundError(command[0])

    assert request_quit_all(tmp_path / "ldconsole.exe", run=boom) is False


def test_gate_skips_when_no_emulator_is_running():
    """没开模拟器：直接放行，不该给用户留一分钟的空等。"""
    gate = EmulatorQuitGate(is_running=lambda: False, quit_all=lambda: True)

    assert gate.begin() == "no_emulator"
    assert gate.poll() == "done"


def test_gate_waits_until_the_emulator_is_gone():
    running = {"value": True}
    clock = FakeClock()
    gate = EmulatorQuitGate(
        is_running=lambda: running["value"],
        quit_all=lambda: True,
        timeout_seconds=60,
        clock=clock,
    )

    assert gate.begin() == "waiting"
    clock.now = 5
    assert gate.poll() == "waiting"
    running["value"] = False
    assert gate.poll() == "done"


def test_gate_gives_up_after_the_timeout_but_still_allows_shutdown():
    """等不到也要收场：用户睡前挂机，不能因为模拟器卡住就永远不关。"""
    clock = FakeClock()
    gate = EmulatorQuitGate(
        is_running=lambda: True,
        quit_all=lambda: True,
        timeout_seconds=60,
        clock=clock,
    )

    assert gate.begin() == "waiting"
    clock.now = 61
    assert gate.poll() == "timeout"
    # 超时之后再问也不会反复触发关机动作。
    assert gate.poll() == "done"


def test_gate_reports_quit_failure_separately_from_no_emulator():
    """「本来没开」和「请它退出失败」是两件事，日志要能分开说。"""
    gate = EmulatorQuitGate(is_running=lambda: True, quit_all=lambda: False)

    assert gate.begin() == "quit_failed"
    assert gate.poll() == "done"


def test_gate_can_be_reused_for_the_next_run():
    running = {"value": True}
    clock = FakeClock()
    gate = EmulatorQuitGate(
        is_running=lambda: running["value"],
        quit_all=lambda: True,
        timeout_seconds=60,
        clock=clock,
    )
    gate.begin()
    running["value"] = False
    gate.poll()

    # 上一轮等完了，下一轮要重新开始等，不能沿用上一轮的死线。
    running["value"] = True
    clock.now = 999
    assert gate.begin() == "waiting"
    assert gate.poll() == "waiting"
