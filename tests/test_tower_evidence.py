from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.tower import build_tower_evidence


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "tower"


def test_tower_profile_uses_current_templates_and_regions():
    profile = build_tower_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("home_enter").region == (1400, 950, 582, 182)
    assert profile.atom("card_decide").region == (800, 950, 700, 182)
    assert profile.page("tower.team").required == ("team_battle_start", "prepare_title")
    assert profile.page("tower.card").required == ("card_decide", "card_hint")


def test_tower_profile_reports_required_template_missing_from_empty_directory(tmp_path):
    profile = build_tower_evidence(tmp_path)

    assert "home_enter" in profile.atoms
    errors = validate_profile(profile, tmp_path)
    # 月塔的白名单是空集（一张都不许缺席），所以**每个**锚点都必须在
    # 「模板不存在」错误里被点名 —— 这也是「判据不许静默降级」的钉子：
    # 谁把某张图改成可选，这里立刻变红。
    for name in (
        "season_tower_title",
        "home_enter",
        "floor_select_team",
        "team_battle_start",
        "prepare_title",
        "card_decide",
        "card_hint",
        "result_clear",
    ):
        assert any(
            f"{name}.png" in error and "模板不存在" in error for error in errors
        ), name
