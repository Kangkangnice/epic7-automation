"""Visual evidence for the simulator secret-shop refresh route."""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha1
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np

from auto_game_unified.core.matcher import Match, find_best_template, load_template

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)
ITEM_THRESHOLD = 0.75
ITEM_SCORE_MARGIN = 0.05
LIST_FINGERPRINT_CHANGE_BITS = 10
# Live spending stays disabled until both target types have current-client row
# and purchase-price fixtures. Both target transactions are now verified.
MYSTIC_TRANSACTION_VERIFIED = True
COVENANT_TRANSACTION_VERIFIED = True
LIVE_TRANSACTIONS_VERIFIED = bool(
    MYSTIC_TRANSACTION_VERIFIED and COVENANT_TRANSACTION_VERIFIED
)


class ShopItemKind(Enum):
    COVENANT = "covenant"
    MYSTIC = "mystic"
    OTHER = "other"
    UNKNOWN = "unknown"


class ShopPage(Enum):
    SHOP = "shop"
    PURCHASE_CONFIRM = "purchase_confirm"
    REFRESH_CONFIRM = "refresh_confirm"
    GOLD_SHORTAGE = "gold_shortage"
    SKYSTONE_SHORTAGE = "skystone_shortage"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ShopRowObservation:
    kind: ShopItemKind
    item_center: tuple[int, int]
    buy_point: tuple[int, int] | None
    item_score: float
    alternate_score: float
    row_key: str
    sold_out: bool = False


@dataclass(frozen=True)
class ShopObservation:
    page: ShopPage
    rows: tuple[ShopRowObservation, ...] = ()
    refresh_point: tuple[int, int] | None = None
    confirm_point: tuple[int, int] | None = None
    cancel_point: tuple[int, int] | None = None
    purchase_kind: ShopItemKind = ShopItemKind.UNKNOWN
    purchase_price: int | None = None
    refresh_price: int | None = None
    list_fingerprint: str = ""
    scores: Mapping[str, float] | None = None


REGIONS = {
    "lobby_shop_entry": (0, 430, 220, 230),
    "shop_title": (0, 52, 500, 130),
    "refresh_button_3": (0, 930, 650, 202),
    "buy_button": (1500, 140, 420, 992),
    "purchase_title": (700, 210, 600, 180),
    "purchase_cancel": (500, 690, 500, 250),
    "purchase_action": (1000, 690, 500, 250),
    "refresh_prompt": (650, 430, 700, 230),
    "refresh_cancel": (500, 650, 550, 260),
    "refresh_confirm": (900, 650, 550, 260),
    "covenant_candidate": (650, 140, 380, 992),
    "mystic_candidate": (650, 140, 380, 992),
    "mystic_price_current": (850, 720, 400, 180),
    "covenant_price_current": (850, 720, 400, 180),
    "sold_out_0_of_1_current": (1500, 140, 420, 992),
}

THRESHOLDS = {
    "lobby_shop_entry": 0.82,
    "shop_title": 0.88,
    "refresh_button_3": 0.82,
    "buy_button": 0.86,
    "purchase_title": 0.90,
    "purchase_cancel": 0.88,
    "purchase_action": 0.88,
    "refresh_prompt": 0.90,
    "refresh_cancel": 0.88,
    "refresh_confirm": 0.88,
    "covenant_candidate": ITEM_THRESHOLD,
    "mystic_candidate": ITEM_THRESHOLD,
    "mystic_price_current": 0.92,
    "covenant_price_current": 0.92,
    "sold_out_0_of_1_current": 0.92,
}


def build_shop_refresh_evidence(template_root: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=f"shop_refresh/{key}.png",
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
        )
        for key in REGIONS
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=(
            PageEvidence(
                "shop_refresh.shop",
                required=("shop_title", "refresh_button_3", "buy_button"),
                forbidden=("purchase_title", "refresh_prompt"),
            ),
            PageEvidence(
                "shop_refresh.purchase_confirm",
                required=("purchase_title", "purchase_cancel", "purchase_action"),
            ),
            PageEvidence(
                "shop_refresh.refresh_confirm",
                required=("refresh_prompt", "refresh_cancel", "refresh_confirm"),
            ),
        ),
        config_path=str(Path(__file__).resolve()),
        template_root=template_root,
    )


def classify_item_scores(
    covenant_score: float,
    mystic_score: float,
    *,
    threshold: float = ITEM_THRESHOLD,
    margin: float = ITEM_SCORE_MARGIN,
) -> ShopItemKind:
    best = max(covenant_score, mystic_score)
    if best < threshold:
        return ShopItemKind.OTHER
    if abs(covenant_score - mystic_score) < margin:
        return ShopItemKind.UNKNOWN
    return (
        ShopItemKind.COVENANT
        if covenant_score > mystic_score
        else ShopItemKind.MYSTIC
    )


def same_shop_row(item_y: int, buy_y: int, *, max_delta: int = 90) -> bool:
    return abs(item_y - buy_y) <= max_delta


def shop_fingerprint_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    try:
        if len(left) != 16 or len(right) != 16:
            raise ValueError
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


class ShopRefreshObserver:
    _ITEM_REGION = (650, 140, 380, 992)
    _LIST_REGION = (650, 140, 1270, 992)

    def __init__(self, profile: EvidenceProfile, template_root: Path) -> None:
        self.profile = profile
        self.template_root = template_root
        self.live_transactions_verified = LIVE_TRANSACTIONS_VERIFIED
        self.templates = {
            key: load_template(str(template_root / atom.template_path))
            for key, atom in profile.atoms.items()
        }

    def _locate(self, screen: np.ndarray, key: str) -> Match | None:
        atom = self.profile.atom(key)
        return find_best_template(
            screen,
            self.templates[key],
            region=atom.region,
            reference_size=atom.reference_size,
        )

    def _visible(self, screen: np.ndarray, key: str) -> Match | None:
        match = self._locate(screen, key)
        if match is None or match.score < self.profile.atom(key).threshold:
            return None
        return match

    @staticmethod
    def _fingerprint(screen: np.ndarray) -> str:
        x, y, width, height = ShopRefreshObserver._LIST_REGION
        crop = screen[y : y + height, x : x + width]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        reduced = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
        coefficients = cv2.dct(reduced.astype(np.float32))[:8, :8].flatten()
        median = float(np.median(coefficients[1:]))
        bits = (coefficients > median).astype(np.uint8)
        return np.packbits(bits).tobytes().hex()

    @staticmethod
    def _row_key(screen: np.ndarray, center_y: int) -> str:
        y1 = max(140, center_y - 85)
        y2 = min(screen.shape[0], center_y + 85)
        crop = screen[y1:y2, 650:1500]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        reduced = cv2.resize(gray, (48, 12), interpolation=cv2.INTER_AREA)
        return sha1(reduced.tobytes()).hexdigest()[:12]

    def _target_peaks(
        self, screen: np.ndarray
    ) -> list[tuple[tuple[int, int], float, float]]:
        x, y, width, height = self._ITEM_REGION
        search = screen[y : y + height, x : x + width]
        covenant = self.templates["covenant_candidate"]
        mystic = self.templates["mystic_candidate"]
        covenant_scores = cv2.matchTemplate(search, covenant, cv2.TM_CCOEFF_NORMED)
        mystic_scores = cv2.matchTemplate(search, mystic, cv2.TM_CCOEFF_NORMED)
        score_height = min(covenant_scores.shape[0], mystic_scores.shape[0])
        score_width = min(covenant_scores.shape[1], mystic_scores.shape[1])
        covenant_scores = covenant_scores[:score_height, :score_width]
        mystic_scores = mystic_scores[:score_height, :score_width]
        combined = np.maximum(covenant_scores, mystic_scores).copy()
        peaks: list[tuple[tuple[int, int], float, float]] = []
        template_height, template_width = covenant.shape[:2]
        while True:
            _, score, _, location = cv2.minMaxLoc(combined)
            if score < ITEM_THRESHOLD:
                break
            left, top = location
            covenant_score = float(covenant_scores[top, left])
            mystic_score = float(mystic_scores[top, left])
            peaks.append(
                (
                    (
                        x + left + template_width // 2,
                        y + top + template_height // 2,
                    ),
                    covenant_score,
                    mystic_score,
                )
            )
            radius_x = max(20, template_width // 2)
            radius_y = max(20, template_height // 2)
            combined[
                max(0, top - radius_y) : min(combined.shape[0], top + radius_y),
                max(0, left - radius_x) : min(combined.shape[1], left + radius_x),
            ] = -1.0
        return peaks

    def _buy_for_row(
        self, screen: np.ndarray, item_y: int
    ) -> tuple[int, int] | None:
        atom = self.profile.atom("buy_button")
        row_region = (
            atom.region[0],
            max(atom.region[1], item_y - 95),
            atom.region[2],
            190,
        )
        match = find_best_template(
            screen,
            self.templates["buy_button"],
            region=row_region,
            reference_size=REFERENCE_SIZE,
        )
        if match is None or match.score < atom.threshold:
            return None
        return match.center if same_shop_row(item_y, match.center[1]) else None

    def _sold_for_row(self, screen: np.ndarray, item_y: int) -> bool:
        atom = self.profile.atom("sold_out_0_of_1_current")
        row_region = (
            atom.region[0],
            max(atom.region[1], item_y - 95),
            atom.region[2],
            190,
        )
        match = find_best_template(
            screen,
            self.templates["sold_out_0_of_1_current"],
            region=row_region,
            reference_size=REFERENCE_SIZE,
        )
        return bool(
            match is not None
            and match.score >= atom.threshold
            and same_shop_row(item_y, match.center[1])
        )

    def _rows(self, screen: np.ndarray) -> tuple[ShopRowObservation, ...]:
        rows: list[ShopRowObservation] = []
        for center, covenant_score, mystic_score in self._target_peaks(screen):
            kind = classify_item_scores(covenant_score, mystic_score)
            sold_out = self._sold_for_row(screen, center[1])
            buy_point = (
                None if sold_out else self._buy_for_row(screen, center[1])
            )
            rows.append(
                ShopRowObservation(
                    kind=kind,
                    item_center=center,
                    buy_point=buy_point,
                    item_score=max(covenant_score, mystic_score),
                    alternate_score=min(covenant_score, mystic_score),
                    row_key=self._row_key(screen, center[1]),
                    sold_out=sold_out,
                )
            )
        return tuple(sorted(rows, key=lambda row: row.item_center[1]))

    def _popup_kind(self, screen: np.ndarray) -> ShopItemKind:
        region = (650, 430, 380, 260)
        covenant = find_best_template(
            screen,
            self.templates["covenant_candidate"],
            region=region,
            reference_size=REFERENCE_SIZE,
        )
        mystic = find_best_template(
            screen,
            self.templates["mystic_candidate"],
            region=region,
            reference_size=REFERENCE_SIZE,
        )
        return classify_item_scores(
            covenant.score if covenant is not None else -1.0,
            mystic.score if mystic is not None else -1.0,
        )

    def observe(self, screen: np.ndarray) -> ShopObservation:
        scores: dict[str, float] = {}
        matches: dict[str, Match | None] = {}
        for key in (
            "refresh_prompt",
            "refresh_cancel",
            "refresh_confirm",
            "purchase_title",
            "purchase_cancel",
            "purchase_action",
            "mystic_price_current",
            "covenant_price_current",
            "shop_title",
            "refresh_button_3",
            "buy_button",
        ):
            match = self._locate(screen, key)
            matches[key] = match
            scores[key] = match.score if match is not None else -1.0

        def seen(key: str) -> bool:
            match = matches[key]
            return bool(
                match is not None
                and match.score >= self.profile.atom(key).threshold
            )

        if seen("refresh_prompt") and seen("refresh_cancel") and seen("refresh_confirm"):
            return ShopObservation(
                page=ShopPage.REFRESH_CONFIRM,
                confirm_point=matches["refresh_confirm"].center,
                cancel_point=matches["refresh_cancel"].center,
                scores=scores,
            )
        if seen("purchase_title") and seen("purchase_cancel") and seen("purchase_action"):
            purchase_kind = self._popup_kind(screen)
            purchase_price = (
                280_000
                if purchase_kind is ShopItemKind.MYSTIC
                and seen("mystic_price_current")
                else 184_000
                if purchase_kind is ShopItemKind.COVENANT
                and seen("covenant_price_current")
                else None
            )
            return ShopObservation(
                page=ShopPage.PURCHASE_CONFIRM,
                confirm_point=matches["purchase_action"].center,
                cancel_point=matches["purchase_cancel"].center,
                purchase_kind=purchase_kind,
                purchase_price=purchase_price,
                scores=scores,
            )
        if seen("shop_title") and seen("refresh_button_3") and seen("buy_button"):
            return ShopObservation(
                page=ShopPage.SHOP,
                rows=self._rows(screen),
                refresh_point=matches["refresh_button_3"].center,
                refresh_price=3,
                list_fingerprint=self._fingerprint(screen),
                scores=scores,
            )
        return ShopObservation(page=ShopPage.UNKNOWN, scores=scores)


def build_shop_refresh_observer(template_root: Path) -> ShopRefreshObserver:
    profile = build_shop_refresh_evidence(template_root)
    return ShopRefreshObserver(profile, template_root)
