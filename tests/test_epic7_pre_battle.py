from importlib import import_module
from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.core.matcher import Match


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"


def fixture(name: str) -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))[
        :1132, :1982
    ]


def detector_api():
    module = import_module("auto_game_unified.games.epic7.pre_battle")
    return (
        module.PreBattleMode,
        module.QuickBattleDetector,
        module.load_quick_battle_templates,
    )


def test_live_quick_page_requires_button_and_white_switch():
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))

    observation = detector.observe(
        fixture("quick_battle_selected_live_20260826"),
        normal_start=None,
    )

    assert observation.mode is mode.QUICK
    assert observation.switch_point is not None
    assert 1380 <= observation.switch_point[0] <= 1490
    assert 995 <= observation.switch_point[1] <= 1100


def test_live_normal_page_uses_route_start_anchor():
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))

    observation = detector.observe(
        fixture("normal_battle_ready_live_20260826"),
        normal_start=Match((1258, 1043), 1.0),
    )

    assert observation.mode is mode.NORMAL
    assert observation.normal_score == 1.0
    assert observation.switch_point is None


def test_switch_control_alone_identifies_the_quick_page():
    """2026-09-18 起判定不再要求按钮锚点单独成立。

    主线队伍准备页的宽「快速战斗」按钮对竞技场版模板只有 0.7341（门槛 0.88），
    而同一帧右侧切换控件 0.9883。按钮过不了阈也必须能判出快速战斗页——否则主线
    会照普通页去点开始按钮的位置，连点 4 次无进展后安全停止（2026-09-18 15:34 实跑）。
    """
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))
    screen = fixture("quick_battle_selected_live_20260826").copy()
    screen[995:1105, 1000:1380] = 0

    observation = detector.observe(screen, normal_start=None)

    assert observation.mode is mode.QUICK
    assert observation.quick_score == 0.0
    assert observation.switch_point is not None
    assert 1380 <= observation.switch_point[0] <= 1490


def test_story_wide_quick_button_is_identified_by_its_switch_control():
    """真实现场（PC 主线队伍准备页）：宽按钮 0.7341 < 0.88，切换控件 0.9883。"""
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "epic7_story"
        / "team_quick_battle_live_20260918.png"
    )
    screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]

    observation = detector.observe(screen, normal_start=None)

    assert observation.mode is mode.QUICK
    assert observation.quick_score < 0.88
    assert observation.switch_score > 0.95
    assert observation.switch_point is not None
    assert 1800 <= observation.switch_point[0] <= 1930
    assert 995 <= observation.switch_point[1] <= 1100


def test_quick_source_is_unknown_when_switch_anchor_is_removed():
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))
    screen = fixture("quick_battle_selected_live_20260826").copy()
    screen[995:1105, 1380:1490] = 0

    observation = detector.observe(screen, normal_start=None)

    assert observation.mode is mode.UNKNOWN
    assert observation.switch_point is None


def test_conflicting_quick_and_normal_evidence_is_unknown():
    mode, detector_type, load_templates = detector_api()
    detector = detector_type(load_templates(TEMPLATES))

    observation = detector.observe(
        fixture("quick_battle_selected_live_20260826"),
        normal_start=Match((1258, 1043), 0.95),
    )

    assert observation.mode is mode.UNKNOWN
    assert observation.switch_point is None
