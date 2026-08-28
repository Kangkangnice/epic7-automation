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
    quick_complete = quick_observed and switch_observed
    quick_partial = quick_observed or switch_observed
    if normal_observed and not quick_partial:
        return PreBattleEvidenceState.NORMAL
    if not normal_observed and quick_complete:
        return PreBattleEvidenceState.QUICK
    return PreBattleEvidenceState.UNKNOWN
