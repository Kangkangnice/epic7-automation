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


# 2026-10-03 起英雄合成**没有「可选模板」**。这 9 张曾经可选，缺一张的后果分三档：
#   - sss_material：判 UNKNOWN、不点任何卡（还有救）
#   - filter_attribute_label / filter_star3_unselected：筛选面板认不出、反复点漏斗直到超时
#   - sss_material_warning_* / imprint_result_* / transmit_reward_*：**fail-open** ——
#     覆盖层判据缺失时 `_xxx_present()` 返回 False，于是「覆盖层必须先关掉」静默失效，
#     可能点到覆盖层底下的材料卡（合成消耗材料，不可逆）
# 所以它们全部改成 required，空目录里必须一条不落地报出来。
_FORMERLY_OPTIONAL_TEMPLATES = (
    "filter_attribute_label",
    "filter_star3_unselected",
    "sss_material",
    "sss_material_warning_title",
    "sss_material_warning_close",
    "imprint_result_title",
    "imprint_result_close",
    "transmit_reward_title",
    "transmit_reward_close",
)


def test_hero_profile_has_no_optional_templates(tmp_path):
    """曾经的 9 张「可选模板」现在全部必需：空目录里一张都不许被放过。

    反向输入就是空目录本身（模板全缺）。旧代码走这条路径时只会报必需的那批，
    这 9 张被静默跳过 —— 而它们缺了正是「判据静默降级」的源头。
    """
    errors = validate_profile(build_hero_evidence(tmp_path), tmp_path)

    for name in _FORMERLY_OPTIONAL_TEMPLATES:
        assert any(f"{name}.png" in error for error in errors), name


def test_hero_profile_reports_a_missing_candidate_template(tmp_path):
    """候选模板（`alt_template_paths`）缺了也必须报出来。

    「SSS 材料」徽记有两种长相（前排展开的大卡 100%、后排被压暗的小卡 ~90%），
    主模板 + 候选模板**同等必需**。以前 `validate_profile()` 只查主模板：候选模板
    被删时它一声不吭，判据就少一档长相而静默降级（加载器最后会 FileNotFoundError，
    但那是开跑前才炸，工具/测试侧兜不住）。
    """
    profile = build_hero_evidence(tmp_path)
    errors = validate_profile(profile, tmp_path)
    atom = profile.atom("sss_material")

    assert atom.alt_template_paths, "sss_material 应当登记「后排小卡」候选模板"
    for relative in atom.alt_template_paths:
        name = relative.rsplit("/", 1)[-1]
        assert any(
            name in error and "候选模板不存在" in error for error in errors
        ), relative
