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
    "filter_button": 0.80,
    "filter_level_label": 0.75,
    "filter_attribute_label": 0.75,
    "filter_star3_selected": 0.90,
    "filter_star3_unselected": 0.86,
    "auto_select_label": 0.85,
    "story_back": 0.90,
    "sss_material": 0.80,
    "rating_sss": 0.90,
    "sss_material_warning_title": 0.82,
    "sss_material_warning_close": 0.82,
    "imprint_result_title": 0.82,
    "imprint_result_close": 0.78,
    "transmit_reward_title": 0.90,
    "transmit_reward_close": 0.92,
}

DEFAULT_THRESHOLD = 0.80
FILTER_ATTRIBUTE_SMALL_THRESHOLD = 0.75

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

# 「SSS 材料」徽记在材料页有**两种画法**，同屏可能同时出现：
#   - 前排那张展开的大卡：徽记按 100% 画  → ``hero/sss_material.png``
#   - 排在它后面、被压暗的小卡：整张卡连同徽记被缩到约 **90%**
#                                          → ``hero/sss_material_behind_card.png``
# 只登记前排那张时，徽记落在「后排小卡」上只量得到 **0.5957** —— 高于「明确排除」
# 线 0.55、低于门槛 0.80，正好掉进 0.55~0.80 的不确定带。后果不是「点错」而是
# 「沉默」：`next_action()` 直接返回 None，不打分、不报警；转场验收要靠「下一个
# 动作」的观察值比对，拿不到 ⇒ 90 秒转场超时 ⇒ 回大厅又认不出页面 ⇒ 整条流程停在
# 刻印页。2026-10-04 07:22 现场就是这个形态；同形态最早见 2026-09-03 14:05。
#
# 语义与大厅「秘密商店」入口一致：**任一候选过阈即算命中**，取过阈候选里的最高分。
# 候选模板与主模板**同等必需** —— 少一张同样是判据静默降级（三道关都盯它）。
SSS_MATERIAL_ALT_TEMPLATES = ("hero/sss_material_behind_card.png",)

# ⚠️ **这里不许再出现「可选模板」名单。**
# 本路线曾经有一份 `_OPTIONAL_TEMPLATES`（9 个），与 `hero_synthesis.build_hero_templates`
# 里那些 `if path.exists() else None` **并行维护**，两处都在说「这几张缺了也没关系」。
# 2026-10-03 结论：判据型模板缺一张就是配置故障，一律 `required=True`。
#   - 好处 1：`validate_profile()` 会把它报成 error（工具/测试侧兜住）
#   - 好处 2：`build_hero_templates()` 直接 `load_template`，缺文件当场 FileNotFoundError
#   - 好处 3：`HeroSynthStateMachine._assert_anchor_templates()` 在构造期再兜一层
# 三处口径一致，不会再出现「一处说可选、另一处说必需」的漂移。


def build_hero_evidence(template_root: Path) -> EvidenceProfile:
    """英雄合成证据画像。

    ⚠️ 阈值只有模拟器基线一套；平台差异收敛到图片（``templates/hero/pc/*.png``）。
    """
    thresholds = THRESHOLDS
    default_threshold = DEFAULT_THRESHOLD
    atoms: dict[str, AtomEvidence] = {}
    for key, relative_path in _TEMPLATE_PATHS.items():
        region_key = _REGION_FOR_TEMPLATE.get(key, key)
        atoms[key] = AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[region_key],
            threshold=thresholds.get(key, default_threshold),
            # 全部必需：判据型模板缺一张就不该悄悄跑（见上面那段说明）。
            required=True,
            reference_size=REFERENCE_SIZE,
            # 「SSS 材料」徽记还有「后排小卡」那种长相（约 90%），见上面那段说明。
            alt_template_paths=(
                SSS_MATERIAL_ALT_TEMPLATES if key == "sss_material" else ()
            ),
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
