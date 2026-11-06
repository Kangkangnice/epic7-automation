from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    LIST_FINGERPRINT_CHANGE_BITS,
    LIVE_TRANSACTIONS_VERIFIED,
    PURCHASE_PRICES,
    ShopItemKind,
    ShopPage,
    build_shop_refresh_evidence,
    build_shop_refresh_observer,
    classify_item_scores,
    same_shop_row,
    shop_fingerprint_distance,
)
from auto_game_unified.games.epic7.template_paths import resolve_template_dir


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_shop_refresh"
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_shop_refresh_pc"


def _screen(name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _template(name: str) -> np.ndarray:
    bgr = cv2.imread(
        str(TEMPLATES / "shop_refresh" / f"{name}.png"),
        cv2.IMREAD_COLOR,
    )
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def test_profile_declares_existing_current_client_templates():
    profile = build_shop_refresh_evidence(TEMPLATES)

    assert validate_profile(profile, TEMPLATES) == []
    assert profile.atom("shop_title").reference_size == (1982, 1132)
    assert profile.atom("refresh_button_3").threshold >= 0.80


def test_current_shop_top_and_bottom_are_safe_shop_pages():
    observer = build_shop_refresh_observer(TEMPLATES)

    assert observer.observe(_screen("shop_top_live")).page is ShopPage.SHOP
    assert observer.observe(_screen("shop_bottom_live")).page is ShopPage.SHOP


def test_pc_secret_shop_page_is_recognized_with_pc_templates():
    """P1 修复回归（2026-11-04）。

    PC 端秘密商店商品页此前三颗判据图全认不出：shop_title 0.8709（阈 0.88，差 0.01）、
    buy_button 0.7886（阈 0.86）、refresh_button_3 0.7505（阈 0.82）。导航器要求三颗
    同时过阈才报 SHOP，于是「点了进入商店、目标页其实已到」被当成「仍在转场」，
    整条刷书签 ✗。补 PC 覆盖图（只含稳定文字/按钮，剔除会变的数量字）后三颗应同时过阈。

    用 PC 模板根构建观察器（与 PC 实跑同一套模板解析），喂三张 PC 现场帧。
    """
    observer = build_shop_refresh_observer(resolve_template_dir(TEMPLATES, "pc"))

    for name in (
        "secret_shop_page_pc_20261104_072013",
        "secret_shop_page_pc_20261104_072146",
        "secret_shop_page_pc_20261104_072304",
    ):
        bgr = cv2.imread(str(PC_FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
        assert bgr is not None, name
        screen = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        result = observer.observe(screen)

        assert result.page is ShopPage.SHOP, (
            f"{name}: 期望 SHOP，实际 {result.page.value}；"
            f"分数 shop_title={result.scores['shop_title']:.4f} "
            f"refresh_button_3={result.scores['refresh_button_3']:.4f} "
            f"buy_button={result.scores['buy_button']:.4f}"
        )
        assert result.scores["shop_title"] >= 0.88
        assert result.scores["refresh_button_3"] >= 0.82
        assert result.scores["buy_button"] >= 0.86


def test_shop_fingerprint_ignores_small_animation_but_separates_scroll_position():
    observer = build_shop_refresh_observer(TEMPLATES)
    top = _screen("shop_top_live")
    animated = top.copy()
    animated[300:330, 1200:1230] = np.clip(
        animated[300:330, 1200:1230].astype(np.int16) + 12,
        0,
        255,
    ).astype(np.uint8)
    top_fingerprint = observer.observe(top).list_fingerprint
    animated_fingerprint = observer.observe(animated).list_fingerprint
    bottom_fingerprint = observer.observe(_screen("shop_bottom_live")).list_fingerprint

    assert shop_fingerprint_distance(top_fingerprint, animated_fingerprint) < (
        LIST_FINGERPRINT_CHANGE_BITS
    )
    assert shop_fingerprint_distance(top_fingerprint, bottom_fingerprint) >= (
        LIST_FINGERPRINT_CHANGE_BITS
    )


def test_fingerprint_confirms_real_scroll_bottom_frames():
    """2026-09-14 三次实跑都栽在滚动到底部：指纹距离 6~8 低于阈值被判「未改变」。"""

    observer = build_shop_refresh_observer(TEMPLATES)

    for suffix in ("a", "b", "c"):
        top = observer.observe(
            _screen(f"shop_scroll_top_live_20260914_{suffix}")
        ).list_fingerprint
        peak = observer.observe(
            _screen(f"shop_scroll_peak_live_20260914_{suffix}")
        ).list_fingerprint
        bottom = observer.observe(
            _screen(f"shop_scroll_bottom_live_20260914_{suffix}")
        ).list_fingerprint

        scrolled = shop_fingerprint_distance(top, bottom)
        assert scrolled >= LIST_FINGERPRINT_CHANGE_BITS, (
            f"{suffix}: 顶部→底部距离 {scrolled} 低于阈值 "
            f"{LIST_FINGERPRINT_CHANGE_BITS}，滚动会被误判为未发生"
        )
        settled = shop_fingerprint_distance(peak, bottom)
        assert settled < LIST_FINGERPRINT_CHANGE_BITS, (
            f"{suffix}: 同一底部列表的静帧距离 {settled} 达到阈值 "
            f"{LIST_FINGERPRINT_CHANGE_BITS}，噪声会伪装成列表变化"
        )


def test_fingerprint_keeps_sold_row_in_the_same_batch_as_unchanged():
    """同批买掉一行不是换批次，不能触发「列表已改变」。"""

    observer = build_shop_refresh_observer(TEMPLATES)

    for kind in ("mystic", "covenant"):
        before = observer.observe(_screen(f"{kind}_row_live_20260831")).list_fingerprint
        after = observer.observe(
            _screen(f"{kind}_purchased_row_live_20260831")
        ).list_fingerprint

        distance = shop_fingerprint_distance(before, after)
        assert distance < LIST_FINGERPRINT_CHANGE_BITS, (
            f"{kind}: 同批内买掉一行距离 {distance} 达到阈值 "
            f"{LIST_FINGERPRINT_CHANGE_BITS}，会被误判为换了一批商品"
        )


def test_refresh_confirmation_requires_current_prompt_and_both_buttons():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("refresh_confirm_live"))

    assert result.page is ShopPage.REFRESH_CONFIRM
    assert result.confirm_point is not None
    assert result.cancel_point is not None


def test_other_purchase_popup_is_not_misclassified_as_a_bookmark():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("purchase_confirm_other_live"))

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.OTHER


def test_unverified_target_popup_does_not_invent_a_visual_price():
    screen = _screen("purchase_confirm_other_live").copy()
    covenant = _template("covenant_candidate")
    height, width = covenant.shape[:2]
    x, y = 760, 500
    screen[y : y + height, x : x + width] = covenant
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(screen)

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.COVENANT
    assert result.purchase_price is None


def test_current_client_mystic_row_is_actionable():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("mystic_row_live_20260831"))

    mystic_rows = [row for row in result.rows if row.kind is ShopItemKind.MYSTIC]
    assert len(mystic_rows) == 1
    assert mystic_rows[0].item_score >= 0.90
    assert mystic_rows[0].buy_point is not None


def test_current_client_mystic_popup_proves_price_280000():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("mystic_purchase_confirm_live_20260831"))

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.MYSTIC
    assert result.purchase_price == 280_000
    assert result.confirm_point is not None
    assert result.cancel_point is not None


def test_current_client_purchased_mystic_row_is_not_actionable():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("mystic_purchased_row_live_20260831"))

    mystic_rows = [row for row in result.rows if row.kind is ShopItemKind.MYSTIC]
    assert len(mystic_rows) == 1
    assert mystic_rows[0].buy_point is None
    assert mystic_rows[0].sold_out


def test_current_client_covenant_row_is_actionable():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("covenant_row_live_20260831"))

    rows = [row for row in result.rows if row.kind is ShopItemKind.COVENANT]
    assert len(rows) == 1
    assert rows[0].item_score >= 0.90
    assert rows[0].buy_point is not None


def test_current_client_friendship_row_is_actionable():
    """2026-10-31 真机帧：第一行是「货币 · 友情点数」18,000 ⇒ 认成 friendship 且可买。

    用户当天要求把友情点数也加进购买候选（原话：「我发现这个材料我也缺了」）。
    这一屏另外 4 行是英雄/装备（泰拉纳德巡逻兵、史嘉雷小恶魔、寒气碎片、
    蜥蜴勇士的戒指）—— 它们**一个都不能**被认成三种书签之一，
    所以顺便钉住「第三张候选没有把别的商品吸进来」。
    """
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("friendship_row_live_20261031"))

    rows = [row for row in result.rows if row.kind is ShopItemKind.FRIENDSHIP]
    assert len(rows) == 1
    assert rows[0].item_score >= 0.95
    assert rows[0].buy_point is not None
    assert not rows[0].sold_out
    # 非目标商品不该被吸进来（这一帧上除了友情点数，其余都不是书签）
    assert len(result.rows) == 1


def test_current_client_friendship_popup_proves_price_18000():
    """2026-10-31 真机事故帧：友情点数购买确认弹窗必须能证明单价 18,000。

    事故经过：当天先给秘密商店和迷宫加了「友情点数」这个**商品**候选，但漏了
    **价格条**那一维 ⇒ 弹窗上商品认对了（kind=friendship）、价格取不到
    （price=None）⇒ 与待买记录的 18,000 对不上 ⇒ 判 UNKNOWN 并拒绝购买。
    （程序拒绝是对的，真实花钱的地方必须 fail-closed。）

    本用例钉住：认出友情图标之后，价格条也要对得上，且数值来自
    ``PURCHASE_PRICES`` 这个**单一来源**（与 runner 记账用同一个常量）。
    """
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(
        _screen("friendship_purchase_confirm_live_20261031")
    )

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.FRIENDSHIP
    assert result.purchase_price == PURCHASE_PRICES[ShopItemKind.FRIENDSHIP]
    assert result.purchase_price == 18_000
    assert result.confirm_point is not None
    assert result.cancel_point is not None


def test_other_purchase_popup_is_not_priced_as_friendship():
    """别的商品的价格条跟友情点数很像（0.9519，单独看会过阈）⇒ 不许给它定成 18,000。

    两者共用同一个金币图标，差别只在数字位数。所以价格条**不能单独当判据** ——
    必须商品图标（``_popup_kind``）先认出来，价格条只作第二道确认。
    这一帧上三种书签图标都不过阈 ⇒ 必须判 ``OTHER`` 且 ``price is None``。
    """
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("purchase_confirm_other_live"))

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.OTHER
    assert result.purchase_price is None


def test_current_client_covenant_popup_proves_price_184000():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("covenant_purchase_confirm_live_20260831"))

    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.COVENANT
    assert result.purchase_price == 184_000
    assert result.confirm_point is not None
    assert result.cancel_point is not None


def test_current_client_purchased_covenant_row_is_not_actionable():
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(_screen("covenant_purchased_row_live_20260831"))

    rows = [row for row in result.rows if row.kind is ShopItemKind.COVENANT]
    assert len(rows) == 1
    assert rows[0].buy_point is None
    assert rows[0].sold_out


def test_both_current_client_transactions_are_verified_for_live_runs():
    assert LIVE_TRANSACTIONS_VERIFIED


def test_close_target_scores_fail_closed():
    assert classify_item_scores(0.84, 0.82) is ShopItemKind.UNKNOWN
    assert classify_item_scores(0.83, 0.20) is ShopItemKind.COVENANT
    assert classify_item_scores(0.20, 0.83) is ShopItemKind.MYSTIC
    assert classify_item_scores(0.60, 0.20) is ShopItemKind.OTHER


def test_item_and_buy_button_must_be_in_the_same_row():
    assert same_shop_row(item_y=300, buy_y=320)
    assert not same_shop_row(item_y=300, buy_y=530)


def test_candidate_covenant_icon_is_bound_to_the_current_row_buy_button():
    screen = _screen("shop_top_live").copy()
    covenant = _template("covenant_candidate")
    height, width = covenant.shape[:2]
    x, y = 842, 420
    screen[y : y + height, x : x + width] = covenant
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(screen)

    covenant_rows = [row for row in result.rows if row.kind is ShopItemKind.COVENANT]
    assert len(covenant_rows) == 1
    assert covenant_rows[0].buy_point is not None
    assert abs(covenant_rows[0].buy_point[1] - covenant_rows[0].item_center[1]) <= 90


def test_target_without_same_row_buy_button_is_not_actionable():
    screen = _screen("shop_top_live").copy()
    covenant = _template("covenant_candidate")
    height, width = covenant.shape[:2]
    x, y = 842, 420
    screen[y : y + height, x : x + width] = covenant
    screen[380:575, 1540:1920] = 0
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(screen)

    covenant_rows = [row for row in result.rows if row.kind is ShopItemKind.COVENANT]
    assert len(covenant_rows) == 1
    assert covenant_rows[0].buy_point is None
