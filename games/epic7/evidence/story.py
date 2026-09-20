"""Story route visual evidence profile."""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
WATCH_STORY_REGION = (1450, 930, 470, 202)
STORY_SKIP_REGION = (1700, 0, 240, 200)
STORY_SKIP_CONFIRM_REGION = (850, 600, 600, 300)
BATTLE_GUIDE_TITLE_REGION = (780, 250, 420, 180)
BATTLE_GUIDE_DONT_SHOW_REGION = (1080, 760, 420, 190)

REGIONS = {
    "watch_story": WATCH_STORY_REGION,
    "prepare_battle": WATCH_STORY_REGION,
    "prepare_battle_updated": WATCH_STORY_REGION,
    "select_team": (1400, 930, 520, 202),
    "start_mission": (1400, 930, 520, 202),
    "start_mission_updated": (1400, 930, 520, 202),
    "skip": STORY_SKIP_REGION,
    "skip_confirm": STORY_SKIP_CONFIRM_REGION,
    "auto_off": (1550, 0, 300, 200),
    "auto_on": (1550, 0, 300, 200),
    "reward": (700, 400, 650, 400),
    "clear": (500, 150, 900, 700),
    "results_confirm": (1500, 930, 420, 202),
    "complete": (650, 150, 700, 700),
    "bonus_reward": (350, 150, 1200, 850),
    "next_stage": (1450, 930, 470, 202),
    "battle_guide_title": BATTLE_GUIDE_TITLE_REGION,
    "battle_guide_dont_show": BATTLE_GUIDE_DONT_SHOW_REGION,
    "stamina_popup": (400, 200, 1200, 700),
    "stamina_material": (400, 200, 700, 700),
    "stamina_confirm": (850, 750, 650, 250),
}

THRESHOLDS = {
    "watch_story": 0.72,
    "prepare_battle": 0.90,
    "skip": 0.65,
    "skip_confirm": 0.80,
    "battle_guide_title": 0.85,
    "battle_guide_dont_show": 0.85,
    "auto_off": 0.80,
    "auto_on": 0.80,
    "select_team": 0.75,
}

PC_THRESHOLD_OVERRIDES = {
    # PC 客户端的文字渲染与模拟器不同；平台覆盖不得改写模拟器基线。
    "watch_story": 0.70,
    "prepare_battle": 0.80,
    "skip": 0.55,
    "skip_confirm": 0.70,
    "battle_guide_title": 0.75,
    "battle_guide_dont_show": 0.75,
    "auto_off": 0.70,
    "auto_on": 0.70,
    "select_team": 0.65,
}

DEFAULT_THRESHOLD = 0.80
PC_DEFAULT_THRESHOLD = 0.70

_TEMPLATE_NAMES = (
    "battle_guide_title",
    "battle_guide_dont_show",
    "watch_story",
    "prepare_battle",
    "prepare_battle_updated",
    "select_team",
    "start_mission",
    "start_mission_updated",
    "skip",
    "skip_confirm",
    "auto_off",
    "auto_on",
    "reward",
    "clear",
    "results_confirm",
    "complete",
    "bonus_reward",
    "next_stage",
    "stamina_popup",
    "stamina_material",
    "stamina_confirm",
)

_OPTIONAL_TEMPLATES = {"stamina_popup", "stamina_material", "stamina_confirm"}


def thresholds_for(backend: str) -> dict[str, float]:
    thresholds = dict(THRESHOLDS)
    if backend == "pc":
        thresholds.update(PC_THRESHOLD_OVERRIDES)
    return thresholds


def build_story_evidence(
    template_dir: Path,
    *,
    backend: str = "emulator",
) -> EvidenceProfile:
    thresholds = thresholds_for(backend)
    default_threshold = (
        PC_DEFAULT_THRESHOLD if backend == "pc" else DEFAULT_THRESHOLD
    )
    atoms = {
        name: AtomEvidence(
            key=name,
            template_path=f"{name}.png",
            region=REGIONS[name],
            threshold=thresholds.get(name, default_threshold),
            required=name not in _OPTIONAL_TEMPLATES,
            reference_size=REFERENCE_SIZE,
        )
        for name in _TEMPLATE_NAMES
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=(
            PageEvidence("story.stage", required=("start_mission",)),
            PageEvidence("story.team", required=("select_team",)),
            PageEvidence("story.skip_confirm", required=("skip_confirm",)),
            PageEvidence("story.battle", required=("auto_on",)),
            PageEvidence("story.results", required=("results_confirm",)),
            PageEvidence("story.complete", required=("complete",)),
            PageEvidence("story.next_stage", required=("next_stage",)),
            PageEvidence(
                "story.stamina",
                required=("stamina_popup",),
                any_of=(("stamina_material", "stamina_confirm"),),
            ),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
