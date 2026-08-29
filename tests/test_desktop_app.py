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
