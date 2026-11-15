# -*- coding: utf-8 -*-
"""企鹅批量购买的视觉证据（2026-11-15 模拟器实机帧采集）。

## 实测页面结构与交接单的两处差异

``forest_with_altar.png`` 右下角「成长祭坛」点开后，不是「左侧分类列表 → 企鹅巢穴购买页」
两级页面，而是**同一张弹窗**里并排四列商品：企鹅蛋 102 红叶、下级精灵之花 170、
上级 850、最上级 4,250；顶部「企鹅巢穴」「精灵之泉」是两个分组标签，实点不换页
（``altar_popup.png`` 与 ``negative_other_prices.png`` 逐像素同构）。

因此「先选企鹅巢穴」由**页面判据**落实：必须同时认出分组标签「企鹅巢穴」和第一列
那颗带 102 红叶报价的购买按钮，且后者的搜索区域只罩第一列（后三列不在区域内）。
不给一个点了不换页的标签单发动作，否则主循环会把它当「没转场」反复点击。

## 数量与报价：两颗状态锚点互为印证

数量弹窗（``quantity_initial.png`` / ``quantity_max.png``）：

* 1/50：数量显示 ``1/50``，底部购买按钮显示 **102**（单价）。
* 点「最多」后 50/50：数量显示 ``50/50``，底部购买按钮显示 **5,100**（50 × 102）。

购入后红叶余额 1,966,173 → 1,961,073，正好 5,100；第二轮打开数量弹窗仍是
50/50、5,100（``quantity_second_round.png``），证实游戏记住上一轮数量。

``quantity_50_50`` 与 ``full_price`` 是**状态判据**，不是页面锚点：它们只在
「购买商品」弹窗已确认之后使用，数字本身就是待判的状态，两态互为反例
（1/50 帧分别 0.6913 / 0.7520，阈值 0.85）。页面标题、物品名、「最多」按钮、
确认按钮「购买」都不含会变内容。若游戏改价，两颗锚点会同时认不出 ⇒ 报价不符
安全停止，绝不会按零散数量购入。

## 购买四锚点（TEMPLATE_CAPTURE.md）

点「购买」前必须同帧具备：弹窗标题「购买商品」、资源类型（红叶图标）、
固定报价（5,100）、确认按钮（购买），外加数量 50/50。任一缺失即安全停止。
``nest_buy_button`` 整颗按钮含红叶图标 + 102 + 「购买」，只用于从成长祭坛
进入数量弹窗，不用于扣费。

## 全库反向验证（121 张帧，0.80 / 0.85 门槛）

| 锚点 | 正例 | 最高反例 | 说明 |
|---|---|---|---|
| ``quantity_title`` | 1.0000 | 0.5352 | 「购买商品」只在本弹窗出现 |
| ``nest_item_name`` | 1.0000 | 0.4742 | 白字「企鹅巢穴」，不与森林三行同名行串 |
| ``nest_buy_button`` | 1.0000 | 0.3118 | 区域只罩第一列，排除 170/850/4,250 |
| ``quantity_50_50`` | 1.0000 | 0.6913 | 反例是 1/50 态 |
| ``full_price`` | 1.0000 | 0.7520 | 反例是 102 报价态 |
| ``complete_title`` | 1.0000 | 0.4218 | 「企鹅成长完成！」 |
| ``complete_close`` | 1.0000 | 0.9876 | 通用「点击关闭」跨页同形，**只作点击目标，不判页** |

半透明遮罩会让底页锚点继续命中：数量弹窗帧上 ``altar_title`` 0.91、完成弹窗帧上
0.86，成长祭坛弹窗帧上 ``forest_title`` 0.83。所以页面组合不能只靠单颗标题，
并且判定顺序必须是 **完成弹窗 → 数量弹窗 → 成长祭坛 → 精灵之森 → 圣域主页**。

## 已知缺口（不静默降级）

红叶不足 / 「购买货币」按钮没有真机帧（余额 196 万，采不到）。证据层不产出
``CURRENCY_SHORT`` 页面；遇到它一律按未登记页面安全停止并留诊断，不猜、不点。
"""
from __future__ import annotations

from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    PageEvidence,
)

REFERENCE_SIZE = (1982, 1132)
DEFAULT_THRESHOLD = 0.80

REGIONS: dict[str, tuple[int, int, int, int]] = {
    # 圣域主页右侧第一行「精灵之森」：复用收菜路线的图，只用于从导航终点进森林。
    "sanctuary_home_row": (1650, 280, 280, 70),
    # 精灵之森左上标题（避开返回箭头与 ? 按钮）。
    "forest_title": (60, 55, 260, 110),
    # 精灵之森右下角「成长祭坛」按钮文字。
    "altar_button": (1380, 960, 500, 120),
    # 成长祭坛弹窗左上标题。
    "altar_title": (60, 240, 260, 110),
    # 成长祭坛弹窗左分组标签「企鹅巢穴」。
    "nest_tab_label": (180, 340, 260, 90),
    # 第一列绿色购买按钮（红叶图标 + 102 + 购买）。区域只罩第一列，
    # 后三列 170/850/4,250 的同类按钮不在区域内。
    "nest_buy_button": (100, 790, 400, 130),
    # 数量弹窗标题「购买商品」。
    "quantity_title": (830, 180, 300, 110),
    # 数量弹窗里的物品名「企鹅巢穴」（白字，与分组标签不是同一处的字形）。
    "nest_item_name": (930, 470, 220, 100),
    # 「最多」按钮：数量不足 50/50 时的补点目标。
    "max_button": (1260, 690, 200, 130),
    # 「50/50」数量显示：满额状态判据。
    "quantity_50_50": (860, 640, 220, 110),
    # 「5,100」总价：满额且报价匹配的状态判据。
    "full_price": (950, 875, 260, 110),
    # 「102」单价：数量不足 50 时的报价证据。两颗价格锚点同区域、互斥，
    # 数量与报价必须配对，不能只认「有价格」就购买。
    "unit_price": (950, 875, 260, 110),
    # 数量弹窗底部绿色按钮上的「购买」两字：扣费动作的唯一落点。
    "quantity_buy_text": (1180, 880, 180, 110),
    # 完成弹窗标题「企鹅成长完成！」。
    "complete_title": (780, 250, 360, 110),
    # 完成弹窗底部「点击关闭」：通用控件，只作点击目标。
    "complete_close": (860, 790, 250, 110),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}
# 两颗数字状态判据的最高反例是同一弹窗的 1/50 态（0.6913 / 0.7520）。
# 0.85 让两侧余量分别达到 0.15 / 0.10 以上，正例恒为 1.0000。
THRESHOLDS["quantity_50_50"] = 0.85
THRESHOLDS["full_price"] = 0.85
# 「102」与「5,100」是同一处金色数字，互相最高 0.8248；0.90 保证满额帧
# 不会被当成「仍显示单价」。数量不足态的判定只取这颗锚点，正例恒 1.0000。
THRESHOLDS["unit_price"] = 0.90

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}
_TEMPLATE_PATHS["sanctuary_home_row"] = "../sanctuary/forest_row.png"

# 顺序即判定顺序：弹窗压暗底页，底页标题仍会高分命中（见模块 docstring）。
_PAGES = (
    PageEvidence("penguin_purchase.complete", required=("complete_title",)),
    PageEvidence(
        "penguin_purchase.quantity",
        required=("quantity_title", "nest_item_name", "max_button", "quantity_buy_text"),
    ),
    PageEvidence(
        "penguin_purchase.altar",
        required=("altar_title", "nest_tab_label", "nest_buy_button"),
        forbidden=("quantity_title",),
    ),
    PageEvidence(
        "penguin_purchase.forest",
        required=("forest_title", "altar_button"),
        forbidden=("altar_title", "nest_tab_label"),
    ),
    PageEvidence(
        "penguin_purchase.home",
        required=("sanctuary_home_row",),
        forbidden=("forest_title", "altar_title", "quantity_title", "complete_title"),
    ),
)


def build_penguin_purchase_evidence(template_dir: Path) -> EvidenceProfile:
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
