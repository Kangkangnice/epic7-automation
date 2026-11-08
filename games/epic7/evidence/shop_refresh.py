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

# ── 「按行」的指纹：整块 DCT 会把几行的差异**平均掉** ───────────────────────
#
# 2026-11-06 22:21 真机（PC）：整批商品**全换了**，整块指纹却只有 **60 位**
# （阈 64，差 4 位）⇒ 判「刷新结果不明确，禁止重复确认」当场停住。
# 病根不是 PC：这一批 5 行里有 4 行是「4 星英雄 + 29,000 金币」，图标/价格/按钮
# 位置全一样，低频分量抓不到细节差别（同一帧的整块画面差只有 6.68，比「买掉一行」
# 的 7.10 还小 —— 色块变化比内容变化更显著，所以画面差这条路也走不通）。
#
# 按行切就分得开（每行单独 64x64 → DCT 低 16x16 = 256 位）：
#
#   ==================  ============================================  ==========
#   样本                 逐行距离（7 行）                                判定
#   ==================  ============================================  ==========
#   同列表静帧           4    4    0    4    4    6   16                未变
#   买入一行（誓约书签）  26   12    4   44   28    2   22                未变
#   买入一行（神秘奖牌）  24    4   34   28    6    4    6                未变
#   **整批换（本次真机）** 56   28   76   34   50   56   40               **换了**
#   ==================  ============================================  ==========
#
# ⇒ 判据取「距离 ≥ 48 的行数 ≥ 3」**且**「总和 ≥ 240」。
#   买入那两档最多 44 位、总和 138 / 106；整批换是 4 行过 48、总和 340。
#   双条件是为了防「一次买掉两三行」被误当成刷新 —— 那会**多花 3 钻**。
LIST_ROW_COUNT = 7
# 只取「图标 + 商品名」那一段（x 650~1500），右侧的价格/按钮列不进来：
# 买入时那一列会从绿变灰，把它算进来反而会抬高「买掉一行」的分数。
LIST_ROW_REGION = (650, 140, 850, 940)  # x, y, 宽, 高
ROW_FINGERPRINT_RESOLUTION = 64
ROW_FINGERPRINT_BLOCK = 16
ROW_FINGERPRINT_BITS = ROW_FINGERPRINT_BLOCK * ROW_FINGERPRINT_BLOCK
ROW_FINGERPRINT_CHANGE_BITS = 48
ROW_FINGERPRINT_CHANGED_ROWS = 3
ROW_FINGERPRINT_TOTAL_BITS = 240
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


# 秘密商店里三种书签的标价。游戏里这些是**固定价**（不随刷新浮动），所以常量成立。
# ⚠️ 单一来源：runner 层（``shop_refresh.py``）的 ``*_PRICE`` 从这里取，别再抄第二份 ——
# 观察器用它把「弹窗上那个价格条」翻译成数字，runner 用它记账，两边必须同一个值，
# 否则会复演 2026-10-31 那次事故（商品认对了、价格取不到 ⇒ 判定 UNKNOWN、拒绝购买）。
PURCHASE_PRICES: dict[ShopItemKind, int] = {
    ShopItemKind.COVENANT: 184_000,
    ShopItemKind.MYSTIC: 280_000,
    ShopItemKind.FRIENDSHIP: 18_000,
}

# 每个商品种类对应的「价格条」证据原子：弹窗上先认出商品图标，再用价格条确认一次，
# 两个都对得上才敢点确认（真实花钱，不许只凭图标）。
_PRICE_ATOM_BY_KIND: dict[ShopItemKind, str] = {
    ShopItemKind.COVENANT: "covenant_price_current",
    ShopItemKind.MYSTIC: "mystic_price_current",
    ShopItemKind.FRIENDSHIP: "friendship_price_current",
}


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
    # 逐行指纹（见 ``shop_row_fingerprints``）：整块指纹在「同一版面换一批商品」时会
    # 被平均掉（2026-11-06 真机只有 60 位），这一组是补它的盲区。
    row_fingerprints: tuple[str, ...] = ()
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
    # 「友情点数」的价格条（2026-10-31 加）：与另外两种共用同一个金币图标、位置一样，
    # 差别只在数字（18,000 比 184,000 少一位）⇒ 搜索区与它们对齐。
    "friendship_price_current": (850, 720, 400, 180),
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
    "friendship_price_current": 0.92,
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


def shop_row_fingerprints(screen: np.ndarray) -> tuple[str, ...]:
    """把商品列表按固定行数切开，每行单独取一个 DCT 指纹。

    为什么整块指纹不够用、为什么阈值取这两个数，全写在 ``LIST_ROW_COUNT`` 上面
    那张实测表里。这里只强调一点：**行切分必须与抓帧时的滚动位置无关地保持稳定** ——
    判的是「同一轮刷新前后」两张图，滚动位置本来就不变，所以固定网格够用。
    """
    x, y, width, height = LIST_ROW_REGION
    crop = screen[y : y + height, x : x + width]
    if crop.size == 0:
        return ()
    step = crop.shape[0] // LIST_ROW_COUNT
    if step <= 0:
        return ()
    fingerprints: list[str] = []
    for index in range(LIST_ROW_COUNT):
        band = crop[index * step : (index + 1) * step]
        gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        reduced = cv2.resize(
            gray,
            (ROW_FINGERPRINT_RESOLUTION, ROW_FINGERPRINT_RESOLUTION),
            interpolation=cv2.INTER_AREA,
        )
        coefficients = cv2.dct(reduced.astype(np.float32))[
            :ROW_FINGERPRINT_BLOCK, :ROW_FINGERPRINT_BLOCK
        ].flatten()
        median = float(np.median(coefficients[1:]))
        bits = (coefficients > median).astype(np.uint8)
        fingerprints.append(np.packbits(bits).tobytes().hex())
    return tuple(fingerprints)


def changed_shop_rows(
    left: tuple[str, ...], right: tuple[str, ...]
) -> tuple[int, int]:
    """返回（「变了」的行数, 各行距离的总和）。

    拿不到成对的逐行指纹（缺帧、长度不一致）时返回 ``(0, 0)`` ——
    这条只是**附加证据**，取不到就退回原来的整块指纹，不许凭它单方面宣布「换了」。
    """
    if not left or not right or len(left) != len(right):
        return 0, 0
    distances = [
        (int(first, 16) ^ int(second, 16)).bit_count()
        for first, second in zip(left, right, strict=False)
    ]
    return (
        sum(1 for value in distances if value >= ROW_FINGERPRINT_CHANGE_BITS),
        sum(distances),
    )


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
        # 2026-11-06：PC 上同一颗「购买」按钮在**不同行**的长相有细微差别 ——
        # 实测同一帧里 y=626 那行独占 0.9013，而最底那行只有 0.6718（阈 0.86）；
        # 用最底那行重裁一张则反过来（最底 1.0000、y=399 那行只有 0.5227）。
        # 单张盖不住，所以加一张备选，**两取最高**。
        # ⚠️ 只有 pc/ 里有这张图 ⇒ 模拟器 `_buy_alt` 是 None ⇒ 退回单模板，行为不变。
        # ⚠️ 必须带上 ``shop_refresh/`` 前缀：生产传进来的 template_root 是
        # ``templates/`` 根（TemplateDir），atom 路径同样是 ``shop_refresh/xxx.png``。
        # 早先写成 ``template_root / "buy_button_alt.png"``，PC 下解析成
        # ``templates/pc/buy_button_alt.png`` —— 文件其实在
        # ``templates/shop_refresh/pc/``，于是备选图**从未被加载**（双候选形同虚设）。
        # 2026-11-06 19:07 实跑再次报「目标商品缺少同行购买按钮」：主图在圣约书签行
        # 只有 0.4195（阈 0.86），而这张备选图是 0.9715 @ (1729,842)。
        buy_alt_path = template_root / "shop_refresh" / "buy_button_alt.png"
        self._buy_alt = (
            load_template(str(buy_alt_path)) if buy_alt_path.is_file() else None
        )
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
        best = None
        for template in self._buy_candidates():
            match = find_best_template(
                screen,
                template,
                region=row_region,
                reference_size=REFERENCE_SIZE,
            )
            if match is not None and (best is None or match.score > best.score):
                best = match
        if best is None or best.score < atom.threshold:
            return None
        return best.center if same_shop_row(item_y, best.center[1]) else None

    def _buy_candidates(self) -> tuple[np.ndarray, ...]:
        """「购买」按钮的候选图：主图 + PC 备选（模拟器没有备选，就只有主图）。"""
        primary = self.templates["buy_button"]
        if self._buy_alt is None:
            return (primary,)
        return (primary, self._buy_alt)

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
            "friendship_price_current",
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
            # 价格条要对得上才认：认出「友情点数」图标、但价格条不是那一条 ⇒ 仍然是
            # ``None``（fail-closed），runner 会拒绝购买而不是硬着头皮确认。
            price_atom = _PRICE_ATOM_BY_KIND.get(purchase_kind)
            purchase_price = (
                PURCHASE_PRICES[purchase_kind]
                if price_atom is not None and seen(price_atom)
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
                row_fingerprints=shop_row_fingerprints(screen),
                scores=scores,
            )
        return ShopObservation(page=ShopPage.UNKNOWN, scores=scores)


def build_shop_refresh_observer(template_root: Path) -> ShopRefreshObserver:
    profile = build_shop_refresh_evidence(template_root)
    return ShopRefreshObserver(profile, template_root)
