import pytest
import tkinter as tk
from unittest.mock import patch

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


def passed_preflight():
    return PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132))


def blocked_preflight():
    return PreflightReport(PreflightStatus.BLOCK, "没有找到雷电窗口")


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
    controller.select_route("story")
    controller.apply_preflight(passed_preflight())

    assert controller.needs_experimental_confirmation is True


def test_selecting_another_route_preserves_successful_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_route("arena")

    assert controller.can_start is True


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


def test_desktop_app_initial_window_contains_its_requested_content(tmp_path):
    root = tk.Tk()
    root.withdraw()
    try:
        DesktopApp(
            root,
            controller=DesktopController(worker=FakeWorker()),
            project_root=tmp_path,
        )
        root.update_idletasks()
        geometry = root.winfo_geometry().split("+")[0]
        width, height = (int(value) for value in geometry.split("x"))
        assert width >= root.winfo_reqwidth()
        assert height >= root.winfo_reqheight()
    finally:
        root.destroy()


def test_start_recheck_failure_does_not_start_worker(tmp_path):
    root = tk.Tk()
    root.withdraw()
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    validated_routes = []
    try:
        app = DesktopApp(
            root,
            controller=controller,
            project_root=tmp_path,
            preflight_runner=blocked_preflight,
            route_validator=lambda mode, template_root: validated_routes.append(mode),
            thread_factory=ImmediateThread,
        )

        app._start()
        root.update()

        assert worker.request is None
        assert validated_routes == []
        assert app.environment_var.get() == "没有找到雷电窗口"
    finally:
        root.destroy()


def test_start_rechecks_environment_and_validates_selected_route(tmp_path):
    root = tk.Tk()
    root.withdraw()
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("arena")
    controller.apply_preflight(passed_preflight())
    calls = []
    try:
        app = DesktopApp(
            root,
            controller=controller,
            project_root=tmp_path,
            preflight_runner=lambda: calls.append("preflight") or passed_preflight(),
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
        root.update()

        assert calls == ["preflight", ("arena", app.template_root)]
        assert worker.request.mode == "arena"
    finally:
        root.destroy()


def test_route_template_failure_does_not_start_worker(tmp_path):
    root = tk.Tk()
    root.withdraw()
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    try:
        app = DesktopApp(
            root,
            controller=controller,
            project_root=tmp_path,
            preflight_runner=passed_preflight,
            route_validator=lambda mode, template_root: (_ for _ in ()).throw(
                RuntimeError("缺少模板")
            ),
            thread_factory=ImmediateThread,
        )

        app._start()
        root.update()

        assert worker.request is None
        assert "路线资源检查失败：缺少模板" == app.environment_var.get()
    finally:
        root.destroy()
