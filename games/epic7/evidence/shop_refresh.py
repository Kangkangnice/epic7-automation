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


def _peaks_key(
    search: np.ndarray,
    covenant: np.ndarray,
    mystic: np.ndarray,
    friendship: np.ndarray,
) -> bytes:
    """(搜索区, 三个候选模板) 的内容指纹，只给 ``_target_peaks`` 的缓存用。

    ⚠️ 形状必须一起进指纹：只喂 ``tobytes()`` 的话 2x3 与 3x2 会撞成同一个键。
    ⚠️ **每个模板都要进指纹**：少喂一张，换掉那张图之后缓存不会失效 ——
    会拿旧模板算出来的峰值当新结果用（静默用错判据）。
    """
    digest = sha1()
    digest.update(
        f"{search.shape}|{covenant.shape}|{mystic.shape}|{friendship.shape}".encode()
    )
    digest.update(search.tobytes())
    digest.update(covenant.tobytes())
    digest.update(mystic.tobytes())
    digest.update(friendship.tobytes())
    return digest.digest()
ITEM_SCORE_MARGIN = 0.05
# 列表指纹用 64x64 的 DCT 低 16x16 系数，共 256 位。原先只取 32x32 的低 8x8
# 系数（64 位），低频分量对「同一面板换了一批商品」几乎不敏感：2026-09-14 三次
# 实跑顶部→底部只有 6~8 位差异，而 2026-08-31 fixture 同批内买掉一行却有 12~16
# 位差异，两类样本分布重叠，任何阈值都会同时出现漏判和误判。
LIST_FINGERPRINT_RESOLUTION = 64
LIST_FINGERPRINT_BLOCK = 16
LIST_FINGERPRINT_BITS = LIST_FINGERPRINT_BLOCK * LIST_FINGERPRINT_BLOCK
# 实测换列表 100~132 位（39%~52%），同列表静帧 8~26 位、同批买掉一行 40~42 位。
# 取 25% 作为阈值，两侧各留约 1.5 倍余量。
LIST_FINGERPRINT_CHANGE_BITS = LIST_FINGERPRINT_BITS // 4
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
    # 「友情点数」（绿心图标）—— 2026-10-31 用户要求加进购买候选。
    # 它同时出现在**秘密商店**和**迷宫流浪商人**两处，图标完全一样
    # （同一张模板在两处实测 1.0000 / 0.9966）⇒ 两处共用这一张图。
    FRIENDSHIP = "friendship"
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
    "friendship_candidate": (650, 140, 380, 992),
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
    "friendship_candidate": ITEM_THRESHOLD,
    "mystic_price_current": 0.92,
    "covenant_price_current": 0.92,
    "sold_out_0_of_1_current": 0.92,
}


# 大厅「秘密商店」入口是全项目**唯一会挂通知角标**的导航入口：商店有未读内容 /
# 有免费刷新时，一块红 N 会盖在入口图标上。实测（1982x1132，门槛 0.82）：
#   干净帧：主模板 0.9642~1.0000（余量充足）
#   带角标帧：主模板 0.8097~0.8098（**差 0.01 不过阈**）⇒ 被当成「锚点缺失」，
#   而该 raise 发生在 main.run_mode 的 try 之外，每日任务只收到一个无声的 ✗。
# 证据帧：runtime_diagnostics/epic7_shop_refresh/20260927_173023_003603_enter_mode_failed_shop_refresh.png
#   （已存档为 tests/fixtures/epic7_shop_refresh/lobby_shop_entry_notified_20260927.png）
# 故这颗锚点登记第二张「带角标」候选模板；两张实测互补（各自在对方的状态下都 <0.82）。
LOBBY_SHOP_ENTRY_ALT_TEMPLATES = ("shop_refresh/lobby_shop_entry_notified.png",)


def build_shop_refresh_evidence(template_root: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=f"shop_refresh/{key}.png",
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
            alt_template_paths=(
                LOBBY_SHOP_ENTRY_ALT_TEMPLATES if key == "lobby_shop_entry" else ()
            ),
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
    friendship_score: float = 0.0,
    *,
    threshold: float = ITEM_THRESHOLD,
    margin: float = ITEM_SCORE_MARGIN,
) -> ShopItemKind:
    """三个候选里挑最高分那个；最高分不够、或冠军与亚军太近 ⇒ 不认。

    ⚠️ ``friendship_score`` 有默认值：老调用方（测试里的两两比较）不用改。
    但**生产路径必须传**，否则友情点数会被当成"两个都不像"的 ``OTHER``。
    """
    scores = {
        ShopItemKind.COVENANT: covenant_score,
        ShopItemKind.MYSTIC: mystic_score,
        ShopItemKind.FRIENDSHIP: friendship_score,
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best_kind, best), (_, second) = ranked[0], ranked[1]
    if best < threshold:
        return ShopItemKind.OTHER
    if best - second < margin:
        return ShopItemKind.UNKNOWN
    return best_kind


def same_shop_row(item_y: int, buy_y: int, *, max_delta: int = 90) -> bool:
    return abs(item_y - buy_y) <= max_delta


def shop_fingerprint_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    try:
        if not left or len(left) != len(right):
            raise ValueError
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        # 无法比较时按「最大差异」处理：不可解释的指纹不得当成「列表没变」。
        return LIST_FINGERPRINT_BITS


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
        # 同一帧会被反复扫描（观察器等待时按轮询重看同一张画面），而 `_target_peaks`
        # 是本模块最重的一步。缓存只留**最近一帧**的派生结果，理由见 `_target_peaks`。
        self._peaks_key: bytes | None = None
        self._peaks_value: list[tuple[tuple[int, int], float, float]] = []

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
        reduced = cv2.resize(
            gray,
            (LIST_FINGERPRINT_RESOLUTION, LIST_FINGERPRINT_RESOLUTION),
            interpolation=cv2.INTER_AREA,
        )
        coefficients = cv2.dct(reduced.astype(np.float32))[
            :LIST_FINGERPRINT_BLOCK, :LIST_FINGERPRINT_BLOCK
        ].flatten()
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
    ) -> list[tuple[tuple[int, int], float, float, float]]:
        x, y, width, height = self._ITEM_REGION
        search = screen[y : y + height, x : x + width]
        covenant = self.templates["covenant_candidate"]
        mystic = self.templates["mystic_candidate"]
        # 「友情点数」（绿心）—— 2026-10-31 加的第三个候选。
        friendship = self.templates["friendship_candidate"]
        # ⚠️ 缓存的是**峰值列表**（几个小元组），**不是** cv2.matchTemplate 的分数图 ——
        # 这一块搜索区（380x992）的分数图就是约 1.5 MB，缓存它会重演 core/matcher.py 里
        # 记着的那次事故（进程内存 961 MB -> 4.1 GB、开始换页，比不缓存还慢）。
        # 成本对比：三次匹配约 30~60 ms，取指纹约 0.2 ms ⇒ 只要命中就是净赚。
        cache_key = _peaks_key(search, covenant, mystic, friendship)
        if cache_key == self._peaks_key:
            return self._peaks_value
        covenant_scores = cv2.matchTemplate(search, covenant, cv2.TM_CCOEFF_NORMED)
        mystic_scores = cv2.matchTemplate(search, mystic, cv2.TM_CCOEFF_NORMED)
        friendship_scores = cv2.matchTemplate(
            search, friendship, cv2.TM_CCOEFF_NORMED
        )
        score_height = min(
            covenant_scores.shape[0], mystic_scores.shape[0], friendship_scores.shape[0]
        )
        score_width = min(
            covenant_scores.shape[1], mystic_scores.shape[1], friendship_scores.shape[1]
        )
        covenant_scores = covenant_scores[:score_height, :score_width]
        mystic_scores = mystic_scores[:score_height, :score_width]
        friendship_scores = friendship_scores[:score_height, :score_width]
        combined = np.maximum(
            np.maximum(covenant_scores, mystic_scores), friendship_scores
        ).copy()
        peaks: list[tuple[tuple[int, int], float, float, float]] = []
        template_height, template_width = covenant.shape[:2]
        while True:
            _, score, _, location = cv2.minMaxLoc(combined)
            if score < ITEM_THRESHOLD:
                break
            left, top = location
            covenant_score = float(covenant_scores[top, left])
            mystic_score = float(mystic_scores[top, left])
            friendship_score = float(friendship_scores[top, left])
            peaks.append(
                (
                    (
                        x + left + template_width // 2,
                        y + top + template_height // 2,
                    ),
                    covenant_score,
                    mystic_score,
                    friendship_score,
                )
            )
            radius_x = max(20, template_width // 2)
            radius_y = max(20, template_height // 2)
            combined[
                max(0, top - radius_y) : min(combined.shape[0], top + radius_y),
                max(0, left - radius_x) : min(combined.shape[1], left + radius_x),
            ] = -1.0
        self._peaks_key = cache_key
        self._peaks_value = peaks
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
        for center, covenant_score, mystic_score, friendship_score in (
            self._target_peaks(screen)
        ):
            kind = classify_item_scores(
                covenant_score, mystic_score, friendship_score
            )
            sold_out = self._sold_for_row(screen, center[1])
            buy_point = (
                None if sold_out else self._buy_for_row(screen, center[1])
            )
            ranked = sorted(
                (covenant_score, mystic_score, friendship_score), reverse=True
            )
            rows.append(
                ShopRowObservation(
                    kind=kind,
                    item_center=center,
                    buy_point=buy_point,
                    item_score=ranked[0],
                    alternate_score=ranked[1],
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
        friendship = find_best_template(
            screen,
            self.templates["friendship_candidate"],
            region=region,
            reference_size=REFERENCE_SIZE,
        )
        return classify_item_scores(
            covenant.score if covenant is not None else -1.0,
            mystic.score if mystic is not None else -1.0,
            friendship.score if friendship is not None else -1.0,
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
