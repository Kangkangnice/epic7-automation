"""Hero synthesis visual evidence profile.

Business safety decisions remain in ``hero_synthesis.py``; this file only owns
template paths, search regions and thresholds that are likely to change with UI.
"""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
REGIONS = {
    "filter_button": (1450, 160, 200, 60),
    "filter_level_label": (600, 500, 200, 120),
    "filter_attribute_label": (630, 250, 220, 90),
    "filter_star3_selected": (1050, 590, 180, 90),
    "filter_star3_unselected": (1050, 590, 180, 90),
    "auto_select_label": (780, 990, 260, 100),
    "story_back": (0, 40, 120, 160),
    "imprint_button": (1000, 900, 250, 200),
    "rating_sss": (130, 435, 180, 130),
    "sss_material": (1750, 350, 230, 650),
    "sss_material_warning_title": (500, 420, 1000, 250),
    "sss_material_warning_close": (700, 650, 550, 220),
    "imprint_result_title": (650, 180, 700, 300),
    "imprint_result_close": (650, 730, 700, 300),
    "transmit_reward_title": (760, 220, 460, 170),
    "transmit_reward_close": (760, 740, 460, 230),
}

THRESHOLDS = {
    "filter_attribute_label": 0.82,
    "filter_star3_unselected": 0.80,
    "sss_material": 0.80,
    "rating_sss": 0.90,
}

_TEMPLATE_PATHS = {
    "filter_button": "hero/filter_button.png",
    "filter_level_label": "hero/filter_level_label.png",
    "filter_star3_selected": "hero/filter_star3_selected.png",
    "imprint_normal": "hero/imprint_button_normal.png",
    "imprint_grey": "hero/imprint_button_grey.png",
    "auto_select_label": "hero/auto_select_label.png",
    "story_back": "navigation/story_back.png",
    "rating_sss": "hero/rating_sss.png",
    "filter_attribute_label": "hero/filter_attribute_label.png",
    "filter_star3_unselected": "hero/filter_star3_unselected.png",
    "sss_material": "hero/sss_material.png",
    "sss_material_warning_title": "hero/sss_material_warning_title.png",
    "sss_material_warning_close": "hero/sss_material_warning_close.png",
    "imprint_result_title": "hero/imprint_result_title.png",
    "imprint_result_close": "hero/imprint_result_close.png",
    "transmit_reward_title": "hero/transmit_reward_title.png",
    "transmit_reward_close": "hero/transmit_reward_close.png",
}

_REGION_FOR_TEMPLATE = {
    "imprint_normal": "imprint_button",
    "imprint_grey": "imprint_button",
}

_OPTIONAL_TEMPLATES = {
    "filter_attribute_label",
    "filter_star3_unselected",
    "sss_material",
    "sss_material_warning_title",
    "sss_material_warning_close",
    "imprint_result_title",
    "imprint_result_close",
    "transmit_reward_title",
    "transmit_reward_close",
}


def build_hero_evidence(template_root: Path) -> EvidenceProfile:
    atoms: dict[str, AtomEvidence] = {}
    for key, relative_path in _TEMPLATE_PATHS.items():
        region_key = _REGION_FOR_TEMPLATE.get(key, key)
        atoms[key] = AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[region_key],
            threshold=THRESHOLDS.get(key, 0.80),
            required=key not in _OPTIONAL_TEMPLATES,
            reference_size=REFERENCE_SIZE,
        )
    return EvidenceProfile(
        atoms=atoms,
        pages=(
            PageEvidence("hero.list", required=("filter_button",)),
            PageEvidence(
                "hero.detail",
                required=("rating_sss",),
                any_of=(("imprint_normal", "imprint_grey"),),
            ),
            PageEvidence("hero.synthesis_result", required=("imprint_result_title",)),
            PageEvidence("hero.transmit_result", required=("transmit_reward_title",)),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_root,
    )
