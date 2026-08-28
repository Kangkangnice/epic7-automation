from pathlib import Path

import cv2

from auto_game_unified.core.evidence_diagnostics import inspect_profile
from auto_game_unified.games.epic7.arena import (
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import (
    REFERENCE_SIZE,
    build_arena_evidence,
    classify_arena_selected_scores,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState, validate_profile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"


def _screen(name: str):
    bgr = cv2.imread(str(FIXTURES / name), cv2.IMREAD_COLOR)
    assert bgr is not None
    screen = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    width, height = REFERENCE_SIZE
    if screen.shape[1] >= width and screen.shape[0] >= height:
        screen = screen[:height, :width]
    return screen


def test_arena_profile_declares_existing_templates_and_current_thresholds():
    profile = build_arena_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("list_ready").threshold == 0.88
    assert profile.atom("battle_start").region == (900, 930, 550, 202)
    assert profile.atom("list_ready").reference_size == REFERENCE_SIZE


def test_arena_team_page_rejects_ticket_popup_as_unsafe():
    profile = build_arena_evidence(TEMPLATES)
    page = profile.page("arena.team")

    assert page.evaluate({"battle_start": True}) is EvidenceState.SAFE
    assert (
        page.evaluate({"battle_start": True, "no_ticket": True})
        is EvidenceState.UNSAFE
    )


def test_arena_selected_page_compares_active_and_list_button_scores():
    assert classify_arena_selected_scores(1.0, 0.95) is EvidenceState.SAFE
    assert classify_arena_selected_scores(0.90, 0.95) is EvidenceState.UNKNOWN


def test_selected_fixture_matches_runtime_and_profile_page_state():
    screen = _screen("selected.png")
    profile = build_arena_evidence(TEMPLATES)
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    report = inspect_profile(screen, profile, TEMPLATES)

    assert machine.is_in_state(screen, ArenaState.SELECTED)
    assert report.pages["arena.selected"] is EvidenceState.SAFE


def test_quick_battle_fixture_matches_runtime_and_profile_team_state():
    screen = _screen("quick_battle_selected_live_20260826.png")
    profile = build_arena_evidence(TEMPLATES)
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    report = inspect_profile(screen, profile, TEMPLATES)

    assert machine.is_in_state(screen, ArenaState.TEAM)
    assert report.pages["arena.team"] is EvidenceState.SAFE
