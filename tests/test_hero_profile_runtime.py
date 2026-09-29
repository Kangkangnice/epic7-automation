from dataclasses import replace
from pathlib import Path

import numpy as np

# ⚠️ 这两条 patch 目标必须是 `hero_vision` 而不是 `hero_synthesis`：
# 2026-09-30 把「只看画面」的那 50 个方法抽到 `hero_vision.HeroVisionMixin` 之后，
# `_is_max_rating` / `_classify_material_page` 调的是 **hero_vision 里的** `find_template`。
# 若图省事在 hero_synthesis 上再导出一次、继续 patch 那边，测试会**照样通过但什么也没验到**
# （patch 到了一个没人调的名）。patch 目标要跟着代码走。
import auto_game_unified.games.epic7.hero_vision as vision_module
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthStateMachine,
    build_hero_templates,
)
from auto_game_unified.games.epic7.hero_transition import SafetyClass


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def _machine_with_atom(**atom_changes):
    templates = build_hero_templates(TEMPLATES)
    profile = templates.evidence
    assert profile is not None
    atoms = dict(profile.atoms)
    key = atom_changes.pop("key")
    atoms[key] = replace(atoms[key], **atom_changes)
    return HeroSynthStateMachine(
        replace(templates, evidence=replace(profile, atoms=atoms))
    )


def test_rating_sss_match_uses_profile_region_and_threshold(monkeypatch):
    expected_region = (11, 22, 33, 44)
    machine = _machine_with_atom(
        key="rating_sss", region=expected_region, threshold=0.73
    )
    observed = {}

    def fake_find_template(screen, template, threshold, *, region, reference_size):
        observed.update(threshold=threshold, region=region)
        return None

    monkeypatch.setattr(vision_module, "find_template", fake_find_template)

    machine._is_max_rating(np.zeros((1132, 1982, 3), dtype=np.uint8))

    assert observed == {"threshold": 0.73, "region": expected_region}


def test_material_sss_classification_uses_profile_threshold_and_region(monkeypatch):
    expected_region = (21, 32, 43, 54)
    machine = _machine_with_atom(
        key="sss_material", region=expected_region, threshold=0.61
    )
    observed = {}

    def fake_find_template(screen, template, threshold, *, region, reference_size):
        observed.update(region=region)
        return replace(vision_module.Match((1, 1), 0.62), score=0.62)

    monkeypatch.setattr(vision_module, "find_template", fake_find_template)
    screen = np.zeros((1132, 1982, 3), dtype=np.uint8)

    assert machine._classify_material_page(screen) is SafetyClass.SSS
    assert observed["region"] == expected_region
