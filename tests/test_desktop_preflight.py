import numpy as np

from auto_game_unified.desktop import preflight as preflight_module
from auto_game_unified.desktop.preflight import PreflightStatus, run_preflight


class FakeWindow:
    def capture(self):
        screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
        screen[100:300, 200:500] = 255
        return screen


def test_preflight_passes_for_valid_capture_without_route_templates():
    report = run_preflight(
        window_factory=FakeWindow,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.PASS
    assert report.can_start is True
    assert report.screen_size == (1982, 1132)


def test_preflight_blocks_when_window_capture_fails():
    def broken_window():
        raise RuntimeError("应恰好找到一个支持的雷电模拟器窗口，实际找到 0 个")

    report = run_preflight(
        window_factory=broken_window,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.BLOCK
    assert report.can_start is False
    assert "雷电" in report.message


def test_preflight_blocks_non_windows_without_touching_window():
    report = run_preflight(
        window_factory=lambda: (_ for _ in ()).throw(
            AssertionError("must not run")
        ),
        platform_name="Linux",
    )

    assert report.status is PreflightStatus.BLOCK
    assert "Windows" in report.message


def test_route_template_validation_uses_selected_mode(tmp_path):
    validate = getattr(preflight_module, "validate_route_templates", None)
    assert callable(validate)
    calls = []

    validate(
        "arena",
        tmp_path,
        template_probe=lambda mode, root: calls.append((mode, root)),
    )

    assert calls == [("arena", tmp_path)]
