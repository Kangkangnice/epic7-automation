"""模拟器权限比助手高时的提示（UIPI 会静默拦掉点击）。

分两层：
- `core/elevation.py` 的判定逻辑（不碰 Win32，全部注入替身）；
- `run_preflight` 会不会把提示带出来（且**不影响** `can_start`）。

⚠️ 2026-11-09 删掉 Tk 界面时，「那一行会不会显示」的那条测试随之删除 ——
它测的是 `DesktopApp`，那个类已经不存在。提示本身的产生逻辑（上面两层）没动。
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from auto_game_unified.core import elevation
from auto_game_unified.core.elevation import (
    ELEVATION_WARNING,
    privilege_warning_for,
    window_process_id,
)
from auto_game_unified.desktop import preflight as preflight_module
from auto_game_unified.desktop.preflight import PreflightStatus


class Target:
    """只有一个 PID 的假窗口。"""

    def __init__(self, pid: int) -> None:
        self._pid = pid

    def process_id(self) -> int:
        return self._pid


def screen_frame():
    screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
    screen[100:300, 200:500] = 255
    return screen


# --------------------------------------------------------------------------
# 判定逻辑
# --------------------------------------------------------------------------


def test_warns_when_the_emulator_is_elevated_and_we_are_not():
    warning = privilege_warning_for(
        Target(4242),
        self_elevated=lambda: False,
        target_elevated=lambda pid: True,
    )

    assert warning == ELEVATION_WARNING


def test_silent_when_we_are_elevated_too():
    """同级别之间不拦，没什么好提示的。"""
    warning = privilege_warning_for(
        Target(4242),
        self_elevated=lambda: True,
        target_elevated=lambda pid: True,
    )

    assert warning is None


def test_silent_when_the_emulator_is_not_elevated():
    warning = privilege_warning_for(
        Target(4242),
        self_elevated=lambda: False,
        target_elevated=lambda pid: False,
    )

    assert warning is None


def test_silent_when_the_target_state_cannot_be_read():
    """查不到**不许猜** True —— 一次误报就会让以后这句话没人当回事。"""
    warning = privilege_warning_for(
        Target(4242),
        self_elevated=lambda: False,
        target_elevated=lambda pid: None,
    )

    assert warning is None


def test_silent_when_the_window_has_no_process_id():
    class Nameless:
        pass

    assert window_process_id(Nameless()) is None
    assert (
        privilege_warning_for(
            Nameless(),
            self_elevated=lambda: False,
            target_elevated=lambda pid: True,
        )
        is None
    )


def test_a_closed_window_does_not_break_the_check():
    class Closed:
        def process_id(self) -> int:
            raise OSError("窗口已经没了")

    assert window_process_id(Closed()) is None


def test_a_failing_lookup_does_not_break_the_check():
    def boom(_pid):
        raise OSError("查询被拒绝")

    assert (
        privilege_warning_for(Target(4242), self_elevated=lambda: False, target_elevated=boom)
        is None
    )


@pytest.mark.parametrize("pid", [0, -1])
def test_a_nonsense_pid_is_ignored(pid):
    assert (
        privilege_warning_for(
            Target(pid),
            self_elevated=lambda: False,
            target_elevated=lambda value: True,
        )
        is None
    )


def test_real_readers_return_something_sane():
    """真调一次 Win32：本进程的提权状态必须是个 bool，不能是 None 或抛异常。"""
    assert isinstance(elevation.current_process_elevated(), bool)
    assert isinstance(elevation.process_elevated(os.getpid()), (bool, type(None)))


# --------------------------------------------------------------------------
# 预检：提示带得出来，但不该把「通过」变成「阻止」
# --------------------------------------------------------------------------


class WindowWithPid:
    def process_id(self) -> int:
        return 4242

    def capture(self):
        return screen_frame()


def test_preflight_carries_the_warning_without_blocking(monkeypatch):
    monkeypatch.setattr(
        preflight_module, "privilege_warning_for", lambda _window: ELEVATION_WARNING
    )

    report = preflight_module.run_preflight(
        window_factory=WindowWithPid, platform_name="Windows"
    )

    assert report.status is PreflightStatus.PASS
    assert report.can_start is True  # 检测是成功的，只是提醒一句
    assert report.warning == ELEVATION_WARNING


def test_preflight_has_no_warning_when_the_window_is_anonymous():
    """普通窗口（拿不到 PID）不该凭空多出一行提示。"""
    report = preflight_module.run_preflight(
        window_factory=_AnonymousWindow, platform_name="Windows"
    )

    assert report.warning is None


class _AnonymousWindow:
    def capture(self):
        return screen_frame()


