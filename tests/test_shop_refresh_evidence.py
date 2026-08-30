from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    ShopItemKind,
    ShopPage,
    build_shop_refresh_evidence,
    build_shop_refresh_observer,
    classify_item_scores,
    same_shop_row,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_shop_refresh"


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


def test_target_without_same_row_buy_button_is_unknown():
    screen = _screen("shop_top_live").copy()
    covenant = _template("covenant_candidate")
    height, width = covenant.shape[:2]
    x, y = 842, 420
    screen[y : y + height, x : x + width] = covenant
    screen[380:575, 1540:1920] = 0
    observer = build_shop_refresh_observer(TEMPLATES)

    result = observer.observe(screen)

    assert all(row.kind is not ShopItemKind.COVENANT for row in result.rows)
