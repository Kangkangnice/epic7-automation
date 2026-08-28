from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.hero_synthesis import (
    build_hero_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def test_hero_profile_uses_current_simulator_templates_and_regions():
    profile = build_hero_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("filter_button").region == (1450, 160, 200, 60)
    assert profile.atom("rating_sss").region == (130, 435, 180, 130)
    assert profile.page("hero.list").required == ("filter_button",)


def test_hero_profile_reports_required_template_missing_from_empty_directory(tmp_path):
    profile = build_hero_evidence(tmp_path)

    assert "rating_sss" in profile.atoms
    errors = validate_profile(profile, tmp_path)
    assert any(
        "rating_sss.png" in error and "模板不存在" in error
        for error in errors
    )
    assert not any("sss_material.png" in error for error in errors)
