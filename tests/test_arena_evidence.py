from pathlib import Path

from auto_game_unified.games.epic7.evidence.arena import (
    REFERENCE_SIZE,
    build_arena_evidence,
)
from auto_game_unified.games.epic7.evidence.common import EvidenceState, validate_profile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"


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


def test_arena_selected_page_does_not_accept_list_page_as_selected():
    profile = build_arena_evidence(TEMPLATES)
    page = profile.page("arena.selected")

    assert page.evaluate({"challenge": True}) is EvidenceState.SAFE
    assert (
        page.evaluate({"challenge": True, "list_ready": True})
        is EvidenceState.UNSAFE
    )
