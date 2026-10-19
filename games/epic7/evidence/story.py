"""Story route visual evidence profile."""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
WATCH_STORY_REGION = (1450, 930, 470, 202)
STORY_SKIP_REGION = (1700, 0, 240, 200)
STORY_SKIP_CONFIRM_REGION = (850, 600, 600, 300)
BATTLE_GUIDE_TITLE_REGION = (780, 250, 420, 180)
BATTLE_GUIDE_DONT_SHOW_REGION = (1080, 760, 420, 190)
# 「重新进行」按钮（打完一关后「无法前往下一个关卡，请选择下方按钮」那一页）。
# 2026-10-18 立：这一页左下角是「离开 / 大厅」、右下角是「S 体力/上限 + 重新进行」。
# 搜索框只框**右下角那一颗**：一是别让「离开 / 大厅」被含进来（语义完全不同），
# 二是贴紧按钮可以把反例分差拉开（实测正例 1.0000 / 0.9870，全库最像的反例 0.5730）。
RETRY_STAGE_REGION = (1680, 1000, 200, 90)


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
    "retry_stage": RETRY_STAGE_REGION,
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

DEFAULT_THRESHOLD = 0.80

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
    # 2026-10-18：「重复打同一关」的闭环按钮。**判据型**（不在 _OPTIONAL_TEMPLATES），
    # 缺图就必须当场报错，不许静默退化成「这一页认不出」。
    "retry_stage",
    "stamina_popup",
    "stamina_material",
    "stamina_confirm",
)

_OPTIONAL_TEMPLATES = {"stamina_popup", "stamina_material", "stamina_confirm"}


def build_story_evidence(template_dir: Path) -> EvidenceProfile:
    """主线证据画像。

    ⚠️ 这里**只有一套阈值**，就是模拟器基线。以前有一张 `PC_THRESHOLD_OVERRIDES`
    给 PC 客户端单独降阈值，那是「拿模拟器的图去认 PC 的按钮」导致的补丁；
    现在平台差异收敛到图片本身（`templates/story/pc/*.png`），阈值不再分平台。
    """
    thresholds = THRESHOLDS
    default_threshold = DEFAULT_THRESHOLD
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
            # 「无法前往下一个关卡」那一页（重复打同一关）：它是**终点页**，
            # 不再往前推进，只认这一颗按钮。
            PageEvidence("story.retry", required=("retry_stage",)),
            PageEvidence(
                "story.stamina",
                required=("stamina_popup",),
                any_of=(("stamina_material", "stamina_confirm"),),
            ),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
