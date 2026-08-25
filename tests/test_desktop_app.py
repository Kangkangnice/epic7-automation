import pytest

from auto_game_unified.desktop.app import DesktopController
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


def passed_preflight():
    return PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132))


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


def test_selecting_another_route_invalidates_previous_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_route("arena")

    assert controller.can_start is False


def test_controller_rejects_non_positive_cycles():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")

    with pytest.raises(ValueError, match="正整数"):
        controller.set_cycles(0)
