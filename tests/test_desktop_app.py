from pathlib import Path
import sys

import pytest
import tkinter as tk
from unittest.mock import patch

from auto_game_unified.desktop import app as app_module
from auto_game_unified.desktop.app import DesktopApp, DesktopController, fit_window_size
from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus


class FakeWorker:
    def __init__(self):
        self.running = False
        self.request = None
        self.stopped = False

    def start(self, request):
        self.request = request
        self.running = True

    def request_stop(self):
        self.stopped = True

    def drain_events(self):
        return []


class ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


def passed_preflight(window_backend="emulator"):
    return PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132))


def blocked_preflight(window_backend="emulator"):
    return PreflightReport(PreflightStatus.BLOCK, "没有找到雷电窗口")


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tk_window(tk_root):
    existing_callbacks = set(tk_root.tk.call("after", "info"))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    yield window
    callbacks = set(tk_root.tk.call("after", "info")) - existing_callbacks
    for callback in callbacks:
        tk_root.tk.call("after", "cancel", callback)
    window.destroy()


def test_startup_order_mentions_emulator_before_assistant():
    hint = getattr(app_module, "STARTUP_ORDER_HINT", "")

    assert "先启动雷电模拟器" in hint
    assert "进入《第七史诗》" in hint


def test_controller_requires_successful_preflight_before_start():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")

    assert controller.can_start is False

    controller.apply_preflight(passed_preflight())
    assert controller.can_start is True


def test_controller_forces_hero_synthesis_to_one_cycle():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("hero_synthesis")
    controller.set_cycles(99)
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.cycles == 1


def test_experimental_route_requires_confirmation():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("fodder")
    controller.apply_preflight(passed_preflight())

    assert controller.needs_experimental_confirmation is True


def test_selecting_another_route_preserves_successful_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_route("arena")

    assert controller.can_start is True


def test_switching_backend_invalidates_previous_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_backend("pc")

    assert controller.selected_backend == "pc"
    assert controller.can_start is False


def test_controller_passes_selected_backend_to_worker():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.backend == "pc"


def test_controller_rejects_unknown_backend():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.select_backend("console")


def test_controller_rejects_backend_switch_while_running():
    worker = FakeWorker()
    worker.running = True
    controller = DesktopController(worker=worker)

    with pytest.raises(RuntimeError):
        controller.select_backend("pc")


def test_controller_rejects_non_positive_cycles():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")

    with pytest.raises(ValueError, match="正整数"):
        controller.set_cycles(0)


def test_window_size_expands_for_high_dpi_requested_content():
    assert fit_window_size(
        requested=(1613, 1208),
        screen=(3200, 2000),
    ) == (1653, 1248)


def test_window_size_stays_inside_a_small_screen():
    assert fit_window_size(
        requested=(1500, 1100),
        screen=(1366, 768),
    ) == (1286, 688)


def test_desktop_app_initial_window_contains_its_requested_content(tmp_path, tk_window):
    DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()
    geometry = tk_window.winfo_geometry().split("+")[0]
    width, height = (int(value) for value in geometry.split("x"))
    assert width >= tk_window.winfo_reqwidth()
    assert height >= tk_window.winfo_reqheight()


def test_start_recheck_failure_does_not_start_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    validated_routes = []
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=blocked_preflight,
        route_validator=lambda mode, template_root: validated_routes.append(mode),
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert validated_routes == []
    assert app.environment_var.get() == "没有找到雷电窗口"


def test_start_rechecks_environment_and_validates_selected_route(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("arena")
    controller.apply_preflight(passed_preflight())
    calls = []
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=lambda window_backend: calls.append(
            ("preflight", window_backend)
        )
        or passed_preflight(),
        route_validator=lambda mode, template_root: calls.append(
            (mode, template_root)
        ),
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start()
    tk_window.update()

    assert calls == [("preflight", "emulator"), ("arena", app.template_root)]
    assert worker.request.mode == "arena"


def test_route_template_failure_does_not_start_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=passed_preflight,
        route_validator=lambda mode, template_root: (_ for _ in ()).throw(
            RuntimeError("缺少模板")
        ),
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert "路线资源检查失败：缺少模板" == app.environment_var.get()


def test_hidden_launcher_sends_both_streams_to_its_log(tmp_path, monkeypatch):
    """桌面图标走的是无窗口入口，标准流必须**在导入助手之前**落到日志上。

    双击启动时 ``sys.stdout`` 可能是 ``None``，任何一处不小心往里写都会直接抛异常；
    这个入口的全部价值就是把两个流换成真文件，所以这里钉死「换成了什么」和
    「返回码原样透传」（吞掉退出码会把启动失败伪装成成功）。
    """
    from auto_game_unified.desktop import launch_hidden

    log_path = tmp_path / "nested" / "desktop_launch.log"
    monkeypatch.setattr(launch_hidden, "LOG_PATH", log_path)
    # main() 会直接改写 sys.stdout / sys.stderr，交给 monkeypatch 负责还原
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    with patch("auto_game_unified.desktop.app.main", return_value=7) as run:
        assert launch_hidden.main() == 7

    run.assert_called_once_with()
    assert sys.stdout is sys.stderr, "两个流应指向同一个日志文件"
    assert Path(sys.stdout.name) == log_path
    try:
        sys.stderr.write("启动检查\n")
        sys.stderr.flush()
    finally:
        sys.stderr.close()
    assert "启动检查" in log_path.read_text(encoding="utf-8")


def test_hidden_launcher_writes_a_startup_failure_into_the_log(tmp_path, monkeypatch):
    """启动就崩的时候无窗口下没人看得到，必须落进日志并返回非零。

    没有这条，故障表现就是「双击图标没反应」，连查都没法查。
    """
    from auto_game_unified.desktop import launch_hidden

    log_path = tmp_path / "desktop_launch.log"
    monkeypatch.setattr(launch_hidden, "LOG_PATH", log_path)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    with patch(
        "auto_game_unified.desktop.app.main",
        side_effect=RuntimeError("模板目录缺失"),
    ):
        assert launch_hidden.main() == 1

    text = log_path.read_text(encoding="utf-8")
    sys.stderr.close()
    assert "模板目录缺失" in text
    assert "Traceback" in text
