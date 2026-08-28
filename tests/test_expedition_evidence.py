from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.expedition import (
    build_expedition_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "expedition"


def test_expedition_profile_uses_current_templates_and_special_threshold():
    profile = build_expedition_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("campfire_idle").threshold == 0.82
    assert profile.atom("difficulty_3_selected").region == (900, 580, 450, 300)
    assert profile.page("expedition.difficulty").required == (
        "difficulty_title",
        "difficulty_confirm",
    )
