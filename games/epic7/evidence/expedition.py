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
    "public_recruit",
    "public_title",
    "public_confirm",
    "public_recruited",
    "campfire_idle",
    "expedition_list",
    "back",
)

# ⚠️ `empty_posters` 曾是可选模板，而模板文件**根本不存在** —— 后果不是「少认一
# 种画面」，是**这条路线上的收工判据整个失效**：传单用完时 `_posters_action()`
# 认不出「没有可用的通缉传单」，于是继续去找那个永远不出现的出发按钮，一路等到
# 超时。2026-09-19 ~ 2026-10-03 实测发生 **6 次**同样超时，每次都存了诊断图
# （`..._no_transition_open-my-posters.png`），画面明写「未持有通缉传单 / 持有 0/10」
# —— 判据就在眼前却认不出来。现已补模板并改为必需（缺文件 `FileNotFoundError`）。
#
# ✅ **2026-10-04 本名单清空**：原先唯一的在册项 `defeated_confirm`（战败确认）已整个
# 删除 —— **远征没有「输」这回事**（用户 2026-10-04 说明）：打完伤害就直接进结算，
# 只有一种结局、一条路径，不存在需要单独认的「战败页」。那个模板本来就没做过，
# 对应动作在真机日志里也一次都没执行过（8/30~10/04，3868 行）。
#
# ⇒ 从今往后远征**一张模板都不许缺席**：少一张图就是配置错误，加载期
# `FileNotFoundError` 直接拦。新增锚点必须同时补模板文件，别指望「先可选、以后再补」
# —— `empty_posters` 就是那样丢掉的。
_OPTIONAL_TEMPLATES: frozenset[str] = frozenset()


def build_expedition_evidence(template_dir: Path) -> EvidenceProfile:
    """远征证据画像。阈值只有模拟器基线一套；平台差异收敛到图片。"""
    thresholds = THRESHOLDS
    atoms = {
        name: AtomEvidence(
            key=name,
            template_path=f"{name}.png",
            region=REGIONS[name],
            threshold=thresholds.get(name, 0.88),
            required=name not in _OPTIONAL_TEMPLATES,
            reference_size=REFERENCE_SIZE,
        )
        for name in _TEMPLATE_NAMES
    }
    auto_off = AtomEvidence(
        key="auto_off",
        template_path="../story/auto_off.png",
        region=REGIONS["auto_off"],
        threshold=thresholds["auto_off"],
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
