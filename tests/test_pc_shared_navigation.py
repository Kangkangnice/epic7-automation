import inspect
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.pc_window import Epic7PcWindow
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
SHARED_TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "epic7_pc_navigation"
    / "lobby_1920x1080.png"
)
ARENA_LIST_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "epic7_pc_navigation"
    / "arena_list_legacy_20260830.png"
)


def _load_raw_pc_lobby() -> np.ndarray:
    image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert image is not None
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _navigator(screen: np.ndarray) -> Epic7Navigator:
    return Epic7Navigator(
        build_navigation_templates(SHARED_TEMPLATES),
        Runtime(lambda: screen, lambda _point: None),
        backend="pc",
    )


def test_real_pc_lobby_is_recognized_with_shared_emulator_templates():
    screen = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())

    observation = _navigator(screen).observe(screen)

    assert observation.name == "lobby"
    assert observation.confidence >= 0.82


def test_real_pc_arena_list_confirms_navigation_destination():
    image = cv2.imread(str(ARENA_LIST_FIXTURE), cv2.IMREAD_COLOR)
    assert image is not None
    screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    observation = _navigator(screen).observe(screen)

    assert observation.name == "arena_ready"
    assert observation.confidence >= 0.75


def test_real_pc_arena_navigation_reaches_the_recorded_list_without_wake_clicks():
    lobby = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())
    arena_mode_bgr = cv2.imread(
        str(ROOT / "tests" / "fixtures" / "epic7_navigation" / "arena_mode.png"),
        cv2.IMREAD_COLOR,
    )
    arena_list_bgr = cv2.imread(str(ARENA_LIST_FIXTURE), cv2.IMREAD_COLOR)
    assert arena_mode_bgr is not None
    assert arena_list_bgr is not None
    arena_mode = cv2.cvtColor(arena_mode_bgr, cv2.COLOR_BGR2RGB)
    arena_list = cv2.cvtColor(arena_list_bgr, cv2.COLOR_BGR2RGB)
    screens = iter((arena_mode, arena_mode, arena_list, arena_list))
    clicks: list[tuple[int, int]] = []
    navigator = Epic7Navigator(
        build_navigation_templates(SHARED_TEMPLATES),
        Runtime(lambda: next(screens), clicks.append),
        backend="pc",
        sleep=lambda _seconds: None,
        transition_frames=4,
    )

    navigator.navigate("arena", lobby_screen=lobby)

    assert clicks == [(1793, 636), (710, 995)]


def test_navigation_builder_has_no_legacy_pc_directory_switch():
    assert "templates" + "_pc" not in inspect.getsource(build_navigation_templates)


def test_real_pc_lobby_shared_anchor_centers_keep_emulator_geometry():
    screen = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())
    navigator = _navigator(screen)
    expected = {
        "lobby_story": (1724, 316),
        "lobby_arena": (1793, 636),
        "lobby_battle": (1826, 532),
        "lobby_hero": (1475, 1037),
    }

    for name, center in expected.items():
        match = navigator._locate(screen, name, 0.80)
        assert match is not None, name
        assert match.center == center


def test_black_pc_frame_is_not_recognized_as_lobby():
    screen = Epic7PcWindow._legacy_canvas(
        np.zeros((1080, 1920, 3), dtype=np.uint8)
    )

    assert _navigator(screen).observe(screen).name == "invalid"
