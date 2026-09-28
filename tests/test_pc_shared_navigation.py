"""PC 客户端与模拟器共用一套模板：页面判定与坐标几何都不许按平台分叉。

⚠️ 2026-09-28：竞技场列表那两条 PC 用例**已删除**。它们当初能过，靠的是
「PC 专用门槛表」（list_ready 0.75 而不是模拟器基线的 0.88）—— 实测那张 PC
帧在模拟器基线下只有 <0.88，也就是说**它不是靠共享图认出来的，是靠放水**。
门槛表删掉之后这两条必然红，留着只会骗人。将来真要做 PC 竞技场，往
``games/epic7/templates/arena/pc/`` 放 PC 截图即可（机制见
``games/epic7/template_paths.py``），那时再把这两条用例加回来。
"""

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


def _load_raw_pc_lobby() -> np.ndarray:
    image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert image is not None
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _navigator(screen: np.ndarray) -> Epic7Navigator:
    return Epic7Navigator(
        build_navigation_templates(SHARED_TEMPLATES),
        Runtime(lambda: screen, lambda _point: None),
    )


def test_real_pc_lobby_is_recognized_with_shared_emulator_templates():
    screen = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())

    observation = _navigator(screen).observe(screen)

    assert observation.name == "lobby"
    assert observation.confidence >= 0.82


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
