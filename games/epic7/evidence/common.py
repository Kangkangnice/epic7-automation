"""Compatibility imports for existing Epic Seven evidence profiles."""

from auto_game_unified.core.matcher import MATCH_MODE_RAW, MATCH_MODES
from auto_game_unified.core.visual_evidence import (
    AtomEvidence,
    AtomObservation,
    EvidenceProfile,
    EvidenceState,
    PageEvidence,
    validate_profile,
)

__all__ = [
    "AtomEvidence",
    "AtomObservation",
    "EvidenceProfile",
    "EvidenceState",
    "MATCH_MODE_RAW",
    "MATCH_MODES",
    "PageEvidence",
    "validate_profile",
]
