from pathlib import Path

import numpy as np

from auto_game_unified.core.pc_window import (
    WindowCalibration,
    WindowRect,
)
from auto_game_unified.desktop import preflight as preflight_module
from auto_game_unified.desktop.preflight import (
    PreflightStatus,
    run_preflight,
    template_root_for_backend,
    validate_route_templates,
)
from auto_game_unified.games.epic7.template_paths import is_pc


class FakeWindow:
    def capture(self):
        screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
        screen[100:300, 200:500] = 255
        return screen


class FakePcWindow:
    def __init__(self, *, calibration=None, screen=None, ensure_error=None):
        self._calibration = calibration or WindowCalibration(
            WindowRect(0, 0, 1920, 1080), WindowRect(0, 0, 1920, 1080), False
        )
        self._screen = screen
        self._ensure_error = ensure_error

    def ensure_render_size(self):
        if self._ensure_error is not None:
            raise RuntimeError(self._ensure_error)
        return self._calibration

    def capture(self):
        if self._screen is not None:
            return self._screen
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


def test_pc_preflight_passes_for_calibrated_client_and_compatible_canvas():
    report = run_preflight(
        window_backend="pc",
        pc_window_factory=FakePcWindow,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.PASS
    assert report.can_start is True
    assert report.screen_size == (1982, 1132)
    assert "PC 客户端检查通过" in report.message


def test_pc_preflight_blocks_when_game_runs_elevated_but_assistant_does_not():
    def elevated_mismatch():
        return FakePcWindow(
            ensure_error=(
                "PC 客户端以管理员权限运行，而当前自动化未提升权限；"
                "Windows 会拦截键鼠输入。请以相同权限级别重新启动两者。"
            )
        )

    report = run_preflight(
        window_backend="pc",
        pc_window_factory=elevated_mismatch,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.BLOCK
    assert report.can_start is False
    assert "管理员" in report.message


def test_pc_preflight_blocks_black_frames():
    def black_frame():
        return FakePcWindow(screen=np.zeros((1132, 1982, 3), dtype=np.uint8))

    report = run_preflight(
        window_backend="pc",
        pc_window_factory=black_frame,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.BLOCK
    assert "黑屏或纯色画面" in report.message


def test_pc_preflight_blocks_unexpected_canvas_size():
    def wrong_canvas():
        return FakePcWindow(screen=np.full((720, 1280, 3), 200, dtype=np.uint8))

    report = run_preflight(
        window_backend="pc",
        pc_window_factory=wrong_canvas,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.BLOCK
    assert "1982x1132" in report.message


def test_pc_preflight_blocks_when_game_window_is_missing():
    def missing_window():
        return FakePcWindow(
            ensure_error="应恰好找到一个 Epic Seven PC 窗口，实际找到 0 个"
        )

    report = run_preflight(
        window_backend="pc",
        pc_window_factory=missing_window,
        platform_name="Windows",
    )

    assert report.status is PreflightStatus.BLOCK
    assert report.can_start is False
    assert "0 个" in report.message


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


# 复检的模板根必须与实跑同源：成就领取是第一条只有 pc/ 素材的路线，
# 普通 Path 会去找 templates/achievement/claim_all.png 并误报缺图。
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "games" / "epic7" / "templates"


def test_pc_preflight_template_root_loads_pc_only_achievement():
    root = template_root_for_backend(TEMPLATE_ROOT, "pc")
    assert is_pc(root) is True
    validate_route_templates("achievement", root)  # 不抛 = pc/ 下的图找得到


def test_emulator_preflight_template_root_loads_achievement_too():
    """2026-11-09：模拟器侧补齐 5 张页面图 + 导航入口图后，两边都能过复检。

    这条原来断言的是「模拟器必须报缺图」（当时成就只有 PC 素材）。
    现在方向反过来了：它保护的是共享层这 5 张图别被谁删掉 —— 删了模拟器就没法跑。
    """
    root = template_root_for_backend(TEMPLATE_ROOT, "emulator")
    assert is_pc(root) is False
    validate_route_templates("achievement", root)  # 不抛 = 共享层 5 张图都在


def test_emulator_preflight_template_root_stays_plain_path():
    assert template_root_for_backend(TEMPLATE_ROOT, "emulator") == TEMPLATE_ROOT
