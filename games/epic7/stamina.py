"""体力不足弹窗的共享处理：先点生命之叶素材，再点确认购买。

主线和狗粮复用同一套模板、搜索区域与两段式决策；
补充次数记账与上限策略由各模式自行维护。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, load_template
from auto_game_unified.core.runtime import StaminaExhausted


# 体力三件套的搜索区域（基准分辨率 1982x1132 下的坐标）
#
# ⚠️ `stamina_confirm` 的搜索框 2026-11-01 从 (850, 750, 650, 250) **左扩到 760**：
# 这版弹窗底部是**三颗按钮**（取消 / 购买 / 礼包），购买按钮被挤到 x=807~1105，
# 而旧框从 850 起 —— 模板（325 宽）在框内根本摆不到按钮真正的落点上，
# 实跑表现是「弹窗认出来了、素材也点了，然后就一直等确认」，最后超时。
# 全库 312 张夹具审计：新框 0 新增、0 漏掉（过阈集合与旧框完全一致）。
# 注：老夹具 `stamina_popup_live_20260809` 里是**两按钮**版本（购买在 x=972），
# 说明这是**游戏 UI 改版**、不是 PC/模拟器差异 —— 两端都会遇到。
STAMINA_REGIONS = {
    "stamina_popup": (400, 200, 1200, 700),
    "stamina_material": (400, 200, 700, 700),
    "stamina_confirm": (760, 750, 740, 250),
}


@dataclass(frozen=True)
class StaminaTemplates:
    stamina_popup: Optional[np.ndarray]
    stamina_material: Optional[np.ndarray]
    stamina_confirm: Optional[np.ndarray]


def load_stamina_templates(story_template_dir: Path) -> StaminaTemplates:
    """加载体力三件套模板；文件缺失时对应项为 None（该线即不具备补体力能力）。"""

    def load_optional(name: str) -> Optional[np.ndarray]:
        path = story_template_dir / f"{name}.png"
        return load_template(str(path)) if path.exists() else None

    return StaminaTemplates(
        stamina_popup=load_optional("stamina_popup"),
        stamina_material=load_optional("stamina_material"),
        stamina_confirm=load_optional("stamina_confirm"),
    )


@dataclass(frozen=True)
class StaminaDecision:
    """体力弹窗决策结果，由各模式解释为点击或等待。

    status 含义：
    - "idle"：画面上没有体力弹窗（调用方据此重置/记账）
    - "material"：应点击生命之叶素材
    - "confirm"：应点击确认购买
    - "waiting"：素材已点但确认按钮尚未渲染（等待下一帧）
    """

    status: str
    point: Optional[tuple[int, int]] = None


def next_stamina_decision(
    screen: np.ndarray,
    locate: Callable[[np.ndarray, str], Optional[Match]],
    *,
    material_clicked: bool,
) -> StaminaDecision:
    """纯决策函数：弹窗在屏时依次产出素材/确认点击点，不持有任何状态。"""
    popup = locate(screen, "stamina_popup")
    if popup is None:
        return StaminaDecision("idle")

    material = locate(screen, "stamina_material")
    if material is None:
        raise StaminaExhausted("生命之叶已耗尽或生命之叶选项不可用")
    if not material_clicked:
        return StaminaDecision("material", material.center)

    confirm = locate(screen, "stamina_confirm")
    if confirm is None:
        return StaminaDecision("waiting")
    return StaminaDecision("confirm", confirm.center)
