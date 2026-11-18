# -*- coding: utf-8 -*-
"""装备制作的视觉证据（2026-11-17 模拟器实机采帧）。

## 页面链路（实测）

大厅 →（右上角蓝四格）快捷菜单 → 第 3 行第 3 列「钢铁工坊」→ 左侧第 1 个图标
「制作装备」→ 顶行 5 个讨伐 → 中央 6 个部位 → 右侧「制作次数 1 / 10」+ 绿色「制作」
→ 确认弹窗「制作装备10次」→ 制作动画 → 结果页「制作完毕」。

⚠️ **「整理」不是另一个页面**：它把同一张结果页的底部换成工具栏
（快速选择 / 出售 / 萃取 / 确认 / 重新制作 / 取消），标题仍然是「制作完毕」。
所以「结果页」与「整理态」必须靠工具栏判据区分，不能靠标题。

## 判据为什么这么设计

``result_title``（「制作完毕」）在半透明遮罩下**仍然可见**：确认弹窗帧上是 0.9902。
⇒ 单靠它判不出「我在结果页而不是在弹窗底下」。页面组合里必须把
``confirm_hint`` / ``sell_confirm_hint`` / ``extract_confirm_hint`` 写进 forbidden，
并且判定顺序把三种弹窗排在前面。

``again_button_plain``（未整理态的「重新制作」）只在结果页出现；
``quick_select_button`` 只在整理态出现。两者互斥，是「整没整理」的唯一分界。

⚠️ **档位不是默认 10**：实机进入时「1」是选中态，材料按 400/210,000（10 件）显示
只是因为上一轮记忆。必须用 ``qty_10_selected`` 确认「10」是白底，没确认就点一下。
``qty_10_selected`` 这个 ROI 在结果页也能拿到 0.8468（装备网格的白块），
所以阈值取 0.90，两侧余量 ≥0.10。

## 已知缺口（不静默降级）

金币不足 / 材料不足 / 背包已满三种弹窗**没有采到帧**（余额充足，用户当天无法演示）。
遇到它们一律走「未登记页面」安全停止并留诊断，不猜坐标。
其中「装备背包已满」另有一条全局弹窗通道（见 ``global_popups``），
命中时按资源耗尽正常收工，不算故障。
"""
from __future__ import annotations

from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    PageEvidence,
)

REFERENCE_SIZE = (1982, 1132)
DEFAULT_THRESHOLD = 0.90

REGIONS: dict[str, tuple[int, int, int, int]] = {
    # 未选部位时底部的「请选择要制作的装备。」。选中部位后这行消失（0.1058），
    # 是「还没选部位」最干净的判据。
    "home_hint": (600, 980, 400, 90),
    # 右侧绿色「制作」按钮（随部位出现）。
    "craft_button": (1620, 1000, 330, 120),
    # 「制作次数」里的「10」白底选中态。反例：结果页同区域 0.8468。
    "qty_10_selected": (1790, 750, 110, 90),
    # 确认弹窗正文「要消耗下列制作材料」。
    "confirm_hint": (650, 410, 700, 80),
    # 确认弹窗里的绿色「制作」。
    "confirm_craft_button": (1130, 800, 190, 100),
    # 结果页标题「制作完毕」。
    "result_title": (820, 170, 280, 100),
    # 未整理态左下的「重新制作」。
    "again_button_plain": (1140, 990, 220, 90),
    # 结果页右中的「整理」按钮。
    "tidy_button": (1500, 860, 300, 100),
    # 整理态左下的「快速选择」。
    "quick_select_button": (100, 1000, 250, 100),
    # 整理态工具栏的「出售」「萃取」（只认可用态的亮字）。
    "sell_button": (520, 1000, 180, 90),
    "extract_button": (840, 1000, 180, 90),
    # 整理态的「重新制作」。
    "again_button_tidy": (1590, 1000, 220, 90),
    # 出售弹窗正文「确定要出售选中的」。
    "sell_confirm_hint": (740, 410, 320, 80),
    # 萃取弹窗正文「要萃取装备以获得装备根源吗?」。
    "extract_confirm_hint": (750, 410, 420, 80),
    # 两种确认弹窗里的右按钮（出售是蓝「确认」，萃取是绿「萃取」，同一位置）。
    "popup_confirm_button": (1030, 800, 180, 90),
    # 萃取弹窗的绿色「萃取」按钮（与出售弹窗的蓝「确认」同位置、不同控件）。
    "extract_confirm_button": (1030, 800, 180, 90),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

# 顺序即判定顺序：弹窗压暗底页，底页的 result_title / again_button 仍会高分命中。
_PAGES = (
    PageEvidence("craft_equipment.sell_confirm", required=("sell_confirm_hint",)),
    PageEvidence("craft_equipment.extract_confirm", required=("extract_confirm_hint",)),
    PageEvidence(
        "craft_equipment.confirm",
        required=("confirm_hint", "confirm_craft_button"),
    ),
    PageEvidence(
        "craft_equipment.tidy",
        required=("result_title", "quick_select_button"),
        forbidden=("confirm_hint", "sell_confirm_hint", "extract_confirm_hint"),
    ),
    PageEvidence(
        "craft_equipment.result",
        required=("result_title", "again_button_plain"),
        forbidden=(
            "quick_select_button",
            "confirm_hint",
            "sell_confirm_hint",
            "extract_confirm_hint",
        ),
    ),
    PageEvidence(
        "craft_equipment.selected",
        required=("craft_button",),
        forbidden=("home_hint", "result_title", "confirm_hint"),
    ),
    PageEvidence(
        "craft_equipment.home",
        required=("home_hint",),
        forbidden=("craft_button", "result_title"),
    ),
)


def build_craft_equipment_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
