"""Shared visual classification for normal and quick pre-battle pages."""

from enum import Enum


class PreBattleEvidenceState(Enum):
    NORMAL = "normal"
    QUICK = "quick"
    UNKNOWN = "unknown"


REFERENCE_SIZE = (1982, 1132)
REGION = (900, 900, 1050, 232)
QUICK_BUTTON_THRESHOLD = 0.88
QUICK_SWITCH_THRESHOLD = 0.90


def classify_pre_battle_evidence(
    *,
    normal_observed: bool,
    quick_observed: bool,
    switch_observed: bool,
) -> PreBattleEvidenceState:
    """把预战斗页判成普通 / 快速 / 未知。

    2026-09-18 起「快速战斗按钮」不再是判 QUICK 的必需品：主线队伍准备页的**宽**按钮
    对竞技场版 `quick_battle_button` 模板只有 0.7341（门槛 0.88），同一帧的**切换控件**
    却有 0.9883 —— 切换控件才是这一页的排他证据（全库 51 张夹具上，非快速页的切换控件
    最高只有 0.5577，零误报）。按钮模板留着做冗余确认；它单独成立时不判 QUICK，因为
    所有调用方都假设「判 QUICK 就一定拿得到切换点」。
    """
    quick_signal = quick_observed or switch_observed
    if normal_observed and not quick_signal:
        return PreBattleEvidenceState.NORMAL
    if not normal_observed and switch_observed:
        return PreBattleEvidenceState.QUICK
    return PreBattleEvidenceState.UNKNOWN
