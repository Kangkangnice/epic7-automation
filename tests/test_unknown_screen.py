from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.unknown_screen import (
    UnknownScreenWake,
    UnknownWakeResult,
)


ROOT = Path(__file__).resolve().parents[1]


def static_game_screen() -> np.ndarray:
    gradient = np.linspace(20, 180, 1982, dtype=np.uint8)
    gray = np.repeat(gradient[np.newaxis, :], 1132, axis=0)
    screen = np.repeat(gray[:, :, np.newaxis], 3, axis=2)
    screen[:52] = 0
    screen[:, 1920:] = 0
    return screen


def battle_screen() -> np.ndarray:
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "epic7_story"
        / "battle_auto_on_live_20260809.png"
    )
    return np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]


def test_static_unknown_clicks_center_four_times_then_exhausts_with_diagnostics():
    screen = static_game_screen()
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    with TemporaryDirectory() as directory:
        runtime = Runtime(
            lambda: screen,
            clicks.append,
            diagnostic_dir=Path(directory),
            emit=logs.append,
        )
        wake = UnknownScreenWake(runtime)

        results = [wake.handle(screen, context="story:results") for _ in range(10)]

        diagnostics = sorted(path.name for path in Path(directory).glob("*.png"))

    assert results == [
        UnknownWakeResult.WAITING,
        UnknownWakeResult.CLICKED,
        UnknownWakeResult.WAITING,
        UnknownWakeResult.CLICKED,
        UnknownWakeResult.WAITING,
        UnknownWakeResult.CLICKED,
        UnknownWakeResult.WAITING,
        UnknownWakeResult.CLICKED,
        UnknownWakeResult.WAITING,
        UnknownWakeResult.EXHAUSTED,
    ]
    assert clicks == [(991, 566), (991, 566), (991, 566), (991, 566)]
    assert any(name.endswith("_unknown_before_wake.png") for name in diagnostics)
    assert any(name.endswith("_unknown_after_wake_failed.png") for name in diagnostics)
    assert sum("动作=wake-unknown-screen 坐标=" in line for line in logs) == 4


def test_animated_unknown_page_stops_waiting_after_frame_limit():
    """带动画的未知画面（如英雄详情立绘）不能无限等待唤醒。"""
    base = static_game_screen()
    frames = []
    for i in range(20):
        frame = base.copy()
        frame[300:800, 300:1600] = 50 + i * 10
        frames.append(frame)
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    with TemporaryDirectory() as directory:
        runtime = Runtime(
            lambda: frames[0],
            clicks.append,
            diagnostic_dir=Path(directory),
            emit=logs.append,
        )
        wake = UnknownScreenWake(runtime)

        results = [wake.handle(frame, context="hero:英雄列表") for frame in frames]

        diagnostics = sorted(path.name for path in Path(directory).glob("*.png"))

    # 画面始终在变：从未稳定，因此不应触发任何唤醒点击
    # 第 max_waiting_frames 帧起持续 EXHAUSTED
    waiting_count = sum(1 for r in results if r is UnknownWakeResult.WAITING)
    exhausted_count = sum(1 for r in results if r is UnknownWakeResult.EXHAUSTED)
    assert waiting_count == 14
    assert exhausted_count == 6
    assert waiting_count + exhausted_count == len(frames)
    assert clicks == []
    assert any(name.endswith("_unknown_animated_page.png") for name in diagnostics)
    assert any("画面持续变化" in line for line in logs)


def test_black_dynamic_and_battle_frames_are_never_clicked():
    static = static_game_screen()
    dynamic = static.copy()
    dynamic[200:850, 200:1700] = 240
    clicks: list[tuple[int, int]] = []
    wake = UnknownScreenWake(Runtime(lambda: static, clicks.append, emit=lambda _: None))

    assert wake.handle(np.zeros_like(static), context="story:results") is UnknownWakeResult.SKIPPED
    assert wake.handle(static, context="story:results") is UnknownWakeResult.WAITING
    assert wake.handle(dynamic, context="story:results") is UnknownWakeResult.WAITING
    assert wake.handle(battle_screen(), context="story:results") is UnknownWakeResult.SKIPPED
    assert clicks == []


def test_colorful_non_game_frame_without_render_borders_is_never_clicked():
    desktop = static_game_screen()
    desktop[:52] = 80
    desktop[:, 1920:] = 80
    clicks: list[tuple[int, int]] = []
    wake = UnknownScreenWake(Runtime(lambda: desktop, clicks.append, emit=lambda _: None))

    assert wake.handle(desktop, context="story:results") is UnknownWakeResult.SKIPPED
    assert wake.handle(desktop, context="story:results") is UnknownWakeResult.SKIPPED
    assert clicks == []


def test_locked_recovery_and_dry_run_never_click():
    screen = static_game_screen()
    clicks: list[tuple[int, int]] = []
    gate = RecoveryGate(None)
    gate.lock(mode="story", cycle=1)
    live = UnknownScreenWake(
        Runtime(lambda: screen, clicks.append, emit=lambda _: None),
        recovery_gate=gate,
    )
    dry = UnknownScreenWake(
        Runtime(
            lambda: screen,
            clicks.append,
            dry_run=True,
            emit=lambda _: None,
        )
    )

    assert live.handle(screen, context="story:results") is UnknownWakeResult.SKIPPED
    assert dry.handle(screen, context="story:results") is UnknownWakeResult.SKIPPED
    assert clicks == []


def test_reset_restores_two_click_budget_for_a_new_unknown_page():
    screen = static_game_screen()
    clicks: list[tuple[int, int]] = []
    wake = UnknownScreenWake(Runtime(lambda: screen, clicks.append, emit=lambda _: None))

    assert wake.handle(screen, context="arena:list") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="arena:list") is UnknownWakeResult.CLICKED
    wake.reset()
    assert wake.handle(screen, context="arena:list") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="arena:list") is UnknownWakeResult.CLICKED

    assert clicks == [(991, 566), (991, 566)]


def test_unsafe_intermediate_frame_does_not_restore_click_budget():
    screen = static_game_screen()
    clicks: list[tuple[int, int]] = []
    wake = UnknownScreenWake(Runtime(lambda: screen, clicks.append, emit=lambda _: None))

    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.CLICKED
    assert wake.handle(np.zeros_like(screen), context="fodder:results") is UnknownWakeResult.SKIPPED
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.CLICKED
    assert wake.handle(battle_screen(), context="fodder:results") is UnknownWakeResult.SKIPPED
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.CLICKED
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.CLICKED
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.WAITING
    assert wake.handle(screen, context="fodder:results") is UnknownWakeResult.EXHAUSTED

    assert clicks == [(991, 566), (991, 566), (991, 566), (991, 566)]
