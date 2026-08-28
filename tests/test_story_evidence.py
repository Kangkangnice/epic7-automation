from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.story import build_story_evidence


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def test_story_profile_uses_current_templates_and_regions():
    profile = build_story_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("skip").threshold == 0.65
    assert profile.atom("skip").region == (1700, 0, 240, 200)
    assert profile.page("story.team").required == ("select_team",)
