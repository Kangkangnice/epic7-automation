"""Arena visual evidence profile.

This module is intentionally limited to assets, regions and page evidence. Arena
business decisions remain in ``games.epic7.arena``.
"""

from pathlib import Path
from typing import Mapping

from .common import (
    AtomEvidence,
    AtomObservation,
    EvidenceProfile,
    EvidenceState,
    PageEvidence,
)
from .pre_battle import (
    QUICK_BUTTON_THRESHOLD,
    QUICK_SWITCH_THRESHOLD,
    REGION as PRE_BATTLE_REGION,
    classify_pre_battle_evidence,
    PreBattleEvidenceState,
)


REFERENCE_SIZE = (1982, 1132)
RANK_PROMOTION_ARROW_REGION = (850, 760, 280, 170)
RANK_PROMOTION_CONFIRM_REGION = (700, 930, 520, 202)
FREE_REFRESH_TITLE_REGION = (700, 300, 550, 160)
FREE_REFRESH_OFFER_REGION = (850, 700, 350, 180)
FREE_REFRESH_CONFIRM_REGION = (1050, 700, 400, 180)

REGIONS = {
    "list_ready": (700, 900, 520, 250),
    "challenge": (700, 930, 520, 202),
    "battle_start": (900, 930, 550, 202),
    "auto_off": (1550, 0, 300, 220),
    "confirm": (1500, 930, 420, 202),
    "no_ticket": (700, 150, 700, 300),
    "friendship_ticket_offer": (540, 470, 440, 230),
    "ticket_purchase_button": (900, 760, 500, 260),
    "rank_promotion_arrow": RANK_PROMOTION_ARROW_REGION,
    "rank_confirm": RANK_PROMOTION_CONFIRM_REGION,
    "refresh_title": FREE_REFRESH_TITLE_REGION,
    "refresh_free": FREE_REFRESH_OFFER_REGION,
    "refresh_confirm": FREE_REFRESH_CONFIRM_REGION,
    "quick_battle_button": PRE_BATTLE_REGION,
    "quick_battle_switch": PRE_BATTLE_REGION,
}

THRESHOLDS = {
    "list_ready": 0.88,
    "challenge": 0.90,
    "battle_start": 0.90,
    "auto_off": 0.85,
    "confirm": 0.90,
    "no_ticket": 0.90,
    "friendship_ticket_offer": 0.92,
    "ticket_purchase_button": 0.92,
    "quick_battle_button": QUICK_BUTTON_THRESHOLD,
    "quick_battle_switch": QUICK_SWITCH_THRESHOLD,
}

_TEMPLATE_PATHS = {
    "rank_promotion_arrow": "global/arena_rank_promotion_arrow.png",
    "list_ready": "list_ready.png",
    "challenge": "challenge.png",
    "battle_start": "battle_start.png",
    "auto_off": "auto_off.png",
    "confirm": "confirm.png",
    "rank_confirm": "rank_confirm.png",
    "no_ticket": "no_ticket.png",
    "friendship_ticket_offer": "friendship_ticket_offer.png",
    "ticket_purchase_button": "ticket_purchase_button.png",
    "refresh_title": "arena_refresh_title.png",
    "refresh_free": "arena_refresh_free.png",
    "refresh_confirm": "arena_refresh_confirm.png",
    "quick_battle_button": "global/quick_battle_button.png",
    "quick_battle_switch": "global/quick_battle_switch.png",
}


def classify_arena_selected_scores(
    challenge_score: float | None,
    list_ready_score: float | None,
) -> EvidenceState:
    if challenge_score is None:
        return EvidenceState.UNKNOWN
    if list_ready_score is None or challenge_score >= list_ready_score:
        return EvidenceState.SAFE
    return EvidenceState.UNKNOWN


def evaluate_arena_pages(
    observations: Mapping[str, AtomObservation],
) -> Mapping[str, EvidenceState]:
    flags = {key: item.observed for key, item in observations.items()}

    def score(key: str) -> float | None:
        item = observations.get(key)
        return item.score if item is not None and item.observed else None

    states = {
        page.key: page.evaluate(flags)
        for page in _PAGES
    }
    states["arena.selected"] = classify_arena_selected_scores(
        score("challenge"), score("list_ready")
    )
    pre_battle = classify_pre_battle_evidence(
        normal_observed=flags.get("battle_start", False),
        quick_observed=flags.get("quick_battle_button", False),
        switch_observed=flags.get("quick_battle_switch", False),
    )
    states["arena.team"] = (
        EvidenceState.UNSAFE
        if flags.get("no_ticket", False)
        else EvidenceState.SAFE
        if pre_battle is not PreBattleEvidenceState.UNKNOWN
        else EvidenceState.UNKNOWN
    )
    return states


_PAGES = (
    PageEvidence("arena.list", required=("list_ready",)),
    PageEvidence("arena.selected", required=("challenge",)),
    PageEvidence(
        "arena.team",
        any_of=(("battle_start", "quick_battle_button"),),
        forbidden=("no_ticket",),
    ),
    PageEvidence("arena.battle", required=("auto_off",)),
    PageEvidence("arena.result", required=("confirm",)),
    PageEvidence(
        "arena.rank_promotion",
        required=("rank_promotion_arrow", "rank_confirm"),
    ),
    PageEvidence(
        "arena.friendship_ticket_offer",
        required=("friendship_ticket_offer", "ticket_purchase_button"),
    ),
    PageEvidence(
        "arena.refresh_confirmation",
        required=("refresh_title", "refresh_free", "refresh_confirm"),
    ),
)


def build_arena_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=THRESHOLDS.get(key, 0.90),
            reference_size=REFERENCE_SIZE,
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        page_evaluator=evaluate_arena_pages,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )
