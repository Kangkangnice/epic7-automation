"""连点器的单元测试（只测业务层，不碰 Qt 与真实鼠标）。

真正点出去的那两个 Win32 调用是在 ``main`` 里用的默认值，测试里全部走注入 ——
跑测试时不该动用户的鼠标。
"""

from __future__ import annotations

import time
from typing import Callable

import pytest

from auto_game_unified.core.autoclicker import (
    MAX_INTERVAL_MS,
    MIN_INTERVAL_MS,
    AutoClicker,
    ClickPlan,
)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _never_pressed() -> bool:
    return False


def test_click_plan_rejects_interval_outside_range() -> None:
    for bad in (0, MIN_INTERVAL_MS - 1, MAX_INTERVAL_MS + 1):
        with pytest.raises(ValueError):
            ClickPlan(0, 0, bad)


def test_clicks_the_same_point_until_stopped() -> None:
    clicks: list[tuple[int, int]] = []
    clicker = AutoClicker(
        click=lambda x, y: clicks.append((x, y)),
        hotkey=_never_pressed,
    )
    clicker.start(ClickPlan(120, 340, MIN_INTERVAL_MS))
    try:
        assert _wait_until(lambda: clicker.count >= 3), "连点器没有点出去"
    finally:
        clicker.stop()
    assert _wait_until(lambda: not clicker.running)
    # 每一次都必须落在同一个点上 —— 「固定位置」是这个工具的全部定义。
    assert set(clicks) == {(120, 340)}
    assert clicker.last_error is None


def test_emergency_hotkey_stops_even_with_a_long_interval() -> None:
    """间隔填成 1 分钟时，按 P 也必须立刻停 —— 靠的是 50 毫秒切片等待。"""
    pressed = {"on": False}
    clicker = AutoClicker(click=lambda x, y: None, hotkey=lambda: pressed["on"])
    clicker.start(ClickPlan(0, 0, 60_000))
    try:
        assert _wait_until(lambda: clicker.count >= 1)
        pressed["on"] = True
        started = time.monotonic()
        assert _wait_until(lambda: not clicker.running, timeout=1.0)
        assert time.monotonic() - started < 0.5
    finally:
        clicker.stop()


def test_second_start_is_rejected_while_running() -> None:
    clicker = AutoClicker(click=lambda x, y: None, hotkey=_never_pressed)
    clicker.start(ClickPlan(0, 0, 60_000))
    try:
        with pytest.raises(RuntimeError):
            clicker.start(ClickPlan(0, 0, 60_000))
    finally:
        clicker.stop()
        _wait_until(lambda: not clicker.running)


def test_click_failure_stops_the_thread_and_is_reported() -> None:
    """点不出去就该停下来并说明原因，不能界面显示「正在连点」而屏幕没反应。"""

    def boom(_x: int, _y: int) -> None:
        raise OSError("桌面被锁了")

    clicker = AutoClicker(click=boom, hotkey=_never_pressed)
    clicker.start(ClickPlan(0, 0, MIN_INTERVAL_MS))
    assert _wait_until(lambda: not clicker.running)
    assert clicker.last_error == "桌面被锁了"
