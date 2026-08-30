from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.story import build_story_evidence


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def test_story_profile_uses_current_templates_and_regions():
    profile = build_story_evidence(TEMPLATES)
    pc_profile = build_story_evidence(TEMPLATES, backend="pc")

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("skip").threshold == 0.65
    assert pc_profile.atom("skip").threshold == 0.55
    assert profile.atom("select_team").threshold == 0.75
    assert pc_profile.atom("select_team").threshold == 0.65
    assert profile.atom("skip").region == (1700, 0, 240, 200)
    assert profile.page("story.team").required == ("select_team",)


def test_story_profile_reports_required_template_missing_from_empty_directory(tmp_path):
    profile = build_story_evidence(tmp_path)

    assert "skip" in profile.atoms
    errors = validate_profile(profile, tmp_path)
    assert any("skip.png" in error and "模板不存在" in error for error in errors)
    assert not any("stamina_popup.png" in error for error in errors)
