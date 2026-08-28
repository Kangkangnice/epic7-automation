"""Arena visual evidence profile.

This module is intentionally limited to assets, regions and page evidence. Arena
business decisions remain in ``games.epic7.arena``.
"""

from pathlib import Path

from .common import AtomEvidence, EvidenceProfile, PageEvidence


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
}


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
        pages=(
            PageEvidence("arena.list", required=("list_ready",)),
            PageEvidence(
                "arena.selected",
                required=("challenge",),
                forbidden=("list_ready",),
            ),
            PageEvidence(
                "arena.team",
                required=("battle_start",),
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
        ),
    )
