import dataclasses
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


def test_only_the_shared_auto_off_judge_changes_its_match_mode():
    """`auto_off` 是本画像里**唯一**换比对口径的锚点，阈值也按新口径重定过。

    ⚠️ 名字与数字都独立写死，不遍历画像自己 —— 否则实现一改断言跟着改。
    """
    profile = build_tower_evidence(TEMPLATES)

    assert profile.atom("auto_off").match_mode == "white_mask"
    # 跨路线共享：三处（主线 / 远征 / 月塔）画的是同一个控件，所以复用同一张图。
    assert profile.atom("auto_off").template_path == "../story/auto_off.png"
    # 0.85 是在**新口径**上重扫全库定的，不是把旧口径的 0.80 搬过来：
    # 真阳性侧月塔三帧都是 0.9214，真阴性侧全库最高 0.6215。
    assert profile.atom("auto_off").threshold == 0.85
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
        assert profile.atom(name).match_mode == "raw", name


def test_a_typo_in_the_match_mode_is_reported_not_swallowed():
    """口径写错必须进 `validate_profile` 的错误列表。

    静默退回原样比的话，阈值还是新口径的数字，判据会**变成永假** ——
    正是「判据不许静默降级」要拦的那一类。
    """
    profile = build_tower_evidence(TEMPLATES)
    broken = dataclasses.replace(
        profile,
        atoms={
            **profile.atoms,
            "auto_off": dataclasses.replace(
                profile.atom("auto_off"), match_mode="white-mask"
            ),
        },
    )

    errors = validate_profile(broken, TEMPLATES)

    assert any(
        "未知的匹配口径" in error and "auto_off" in error for error in errors
    ), errors


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
