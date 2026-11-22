"""Story route visual evidence profile."""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
WATCH_STORY_REGION = (1450, 930, 470, 202)
STORY_SKIP_REGION = (1700, 0, 240, 200)
STORY_SKIP_CONFIRM_REGION = (850, 600, 600, 300)
BATTLE_GUIDE_TITLE_REGION = (780, 250, 420, 180)
BATTLE_GUIDE_DONT_SHOW_REGION = (1080, 760, 420, 190)
# 队伍准备页「配队」三件套（2026-11-22，用户实跑口径）：
#   team_manage      左下角「管理队伍」，进编队的入口
#   team_list_plus   右侧英雄列表**最顶端**的蓝底黄十字，点它才进入「可放置」状态
#   team_slot_plus   空位上的紫底黄十字，点它把当前选中的英雄放上去
# 三个都是**判据型**：缺图必须当场报错，不许静默退化成「这一页认不出」。
TEAM_MANAGE_REGION = (0, 960, 260, 120)
TEAM_LIST_PLUS_REGION = (1300, 350, 400, 260)
TEAM_SLOT_PLUS_REGION = (150, 150, 800, 800)
# 黄圈判据的统计区：只看阵型区，避开按钮与列表。
TEAM_RING_REGION = (150, 150, 800, 800)
# 黄色高亮像素占比阈值（实测：3 空位 3.35% / 2 空位 2.66% / 1 空位 1.37% /
# 满员全蓝圈 0.18%）。0.8% 卡在满员与最稀疏空位之间，两侧余量都超过 50%。
TEAM_RING_MIN_RATIO = 0.008


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
    # 与 `games/epic7/stamina.py` 的 STAMINA_REGIONS 必须一致：三按钮改版后
    # 购买按钮落到 x=807~1105，旧框 (850,...) 摆不下模板（见那里的注释）。
    "stamina_confirm": (760, 750, 740, 250),
    "team_manage": TEAM_MANAGE_REGION,
    "team_list_plus": TEAM_LIST_PLUS_REGION,
    "team_slot_plus": TEAM_SLOT_PLUS_REGION,
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
    # 配队三件套共用 0.80：实测正例 0.984~0.999，反例最高 0.53（紫加号）/
    # 0.27（顶端加号），分离充分。
    "team_manage": 0.80,
    "team_list_plus": 0.80,
    "team_slot_plus": 0.80,
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
    "stamina_popup",
    "stamina_material",
    "stamina_confirm",
    "team_manage",
    "team_list_plus",
    "team_slot_plus",
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
            PageEvidence(
                "story.stamina",
                required=("stamina_popup",),
                any_of=(("stamina_material", "stamina_confirm"),),
            ),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
