"""Expedition route visual evidence profile."""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
REGIONS = {
    "home": (1350, 850, 632, 282),
    "poster_embark": (250, 280, 1400, 570),
    "empty_posters": (550, 250, 900, 550),
    "difficulty_title": (650, 120, 700, 300),
    "difficulty_3_selected": (900, 580, 450, 300),
    "difficulty_confirm": (800, 780, 500, 300),
    "prepare_battle": (1450, 850, 532, 282),
    "battle_start": (1300, 900, 682, 232),
    "auto_off": (1550, 0, 300, 200),
    "battle_anchor": (1400, 0, 582, 320),
    "result_confirm": (1450, 850, 532, 282),
    "victory_title": (750, 250, 500, 250),
    "victory_close": (700, 650, 600, 300),
    "defeated_confirm": (650, 700, 700, 432),
    "public_recruit": (800, 900, 500, 232),
    "public_title": (700, 250, 600, 300),
    "public_confirm": (650, 650, 700, 482),
    "public_recruited": (750, 850, 650, 282),
    "campfire_idle": (650, 80, 700, 420),
    "expedition_list": (1100, 100, 500, 260),
    "back": (0, 0, 220, 230),
}

THRESHOLDS = {"campfire_idle": 0.82, "auto_off": 0.80, "public_recruit": 0.85}

_TEMPLATE_NAMES = (
    "home",
    "poster_embark",
    "empty_posters",
    "difficulty_title",
    "difficulty_3_selected",
    "difficulty_confirm",
    "prepare_battle",
    "battle_start",
    "battle_anchor",
    "result_confirm",
    "victory_title",
    "victory_close",
    "defeated_confirm",
    "public_recruit",
    "public_title",
    "public_confirm",
    "public_recruited",
    "campfire_idle",
    "expedition_list",
    "back",
)

_OPTIONAL_TEMPLATES = {"empty_posters", "defeated_confirm"}


def build_expedition_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        name: AtomEvidence(
            key=name,
            template_path=f"{name}.png",
            region=REGIONS[name],
            threshold=THRESHOLDS.get(name, 0.88),
            required=name not in _OPTIONAL_TEMPLATES,
            reference_size=REFERENCE_SIZE,
        )
        for name in _TEMPLATE_NAMES
    }
    auto_off = AtomEvidence(
        key="auto_off",
        template_path="../story/auto_off.png",
        region=REGIONS["auto_off"],
        threshold=THRESHOLDS["auto_off"],
        reference_size=REFERENCE_SIZE,
    )
    atoms["auto_off"] = auto_off
    return EvidenceProfile(
        atoms=atoms,
        pages=(
            PageEvidence("expedition.home", required=("home",)),
            PageEvidence("expedition.posters", required=("poster_embark",)),
            PageEvidence(
                "expedition.posters_fallback",
                required=("expedition_list", "back"),
            ),
            PageEvidence(
                "expedition.difficulty",
                required=("difficulty_title", "difficulty_confirm"),
            ),
            PageEvidence("expedition.prepare", required=("prepare_battle",)),
            PageEvidence("expedition.team", required=("battle_start",)),
            PageEvidence("expedition.battle", required=("auto_off",)),
            PageEvidence("expedition.result", required=("result_confirm",)),
            PageEvidence(
                "expedition.public_recruit",
                required=("public_title", "public_confirm"),
            ),
            PageEvidence("expedition.campfire", required=("campfire_idle",)),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
