import numpy as np
import pytest

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    ShopItemKind,
    ShopObservation,
    ShopPage,
    ShopRowObservation,
)
from auto_game_unified.games.epic7.shop_refresh import (
    COVENANT_PRICE,
    MYSTIC_PRICE,
    ShopPhase,
    ShopRefreshRunner,
    ShopRefreshStateMachine,
    ShopRunStats,
)


def _row(kind: ShopItemKind, row_key: str = "row-a") -> ShopRowObservation:
    return ShopRowObservation(
        kind=kind,
        item_center=(850, 300),
        buy_point=(1770, 300),
        item_score=0.92,
        alternate_score=0.20,
        row_key=row_key,
    )


def _frame(value: int) -> np.ndarray:
    return np.full((120, 200, 3), value, dtype=np.uint8)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Observer:
    def __init__(self, observations: dict[int, ShopObservation]) -> None:
        self.observations = observations

    def observe(self, screen: np.ndarray) -> ShopObservation:
        return self.observations[int(screen[0, 0, 0])]


def _runtime(
    screens: list[np.ndarray],
    *,
    clock: _Clock,
    clicks: list[tuple[tuple[int, int], str]],
    swipes: list[tuple[tuple[int, int], tuple[int, int], int]],
    logs: list[str],
) -> Runtime:
    frames = iter(screens)
    runtime = Runtime(
        lambda: next(frames),
        lambda point: clicks.append((point, "backend")),
        swipe=lambda start, end, duration: swipes.append((start, end, duration)),
        emit=logs.append,
        monotonic=clock.now,
    )
    original_click = runtime.click

    def named_click(point: tuple[int, int], action: str) -> None:
        clicks.append((point, action))
        original_click(point, action)

    runtime.click = named_click
    return runtime


def test_initial_purchases_do_not_enter_paid_hit_rate():
    stats = ShopRunStats(target_refreshes=2)

    stats.commit_purchase(ShopItemKind.COVENANT)

    assert stats.initial_covenant == 1
    assert stats.paid_covenant == 0
    assert stats.covenant_hit_rate == 0.0
    assert stats.covenant_gold == COVENANT_PRICE


def test_paid_covenant_and_mystic_are_counted_separately():
    stats = ShopRunStats(target_refreshes=2)
    stats.commit_refresh()

    stats.commit_purchase(ShopItemKind.COVENANT)
    stats.commit_purchase(ShopItemKind.MYSTIC)

    assert (stats.paid_covenant, stats.paid_mystic) == (1, 1)
    assert stats.covenant_hit_rate == 1.0
    assert stats.mystic_hit_rate == 1.0
    assert (stats.covenant_gold, stats.mystic_gold) == (
        COVENANT_PRICE,
        MYSTIC_PRICE,
    )
    assert stats.total_gold == COVENANT_PRICE + MYSTIC_PRICE
    assert stats.skystone_spent == 3


def test_same_paid_batch_can_count_two_same_type_purchases():
    stats = ShopRunStats(target_refreshes=1)
    stats.commit_refresh()

    stats.commit_purchase(ShopItemKind.COVENANT)
    stats.commit_purchase(ShopItemKind.COVENANT)

    assert stats.paid_covenant == 2
    assert stats.covenant_hit_rate == 2.0


def test_refresh_is_committed_only_after_business_completion():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()

    machine.begin_refresh(source_price=3, source_fingerprint="old-list")

    assert machine.stats.completed_refreshes == 0
    assert machine.phase is ShopPhase.WAIT_REFRESH_CONFIRM
    machine.mark_refresh_confirm_clicked()
    assert machine.stats.completed_refreshes == 0
    machine.complete_refresh()
    assert machine.stats.completed_refreshes == 1
    assert machine.phase is ShopPhase.SCAN_TOP


def test_last_refreshed_batch_is_scanned_before_completion():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()
    machine.begin_refresh(source_price=3, source_fingerprint="old-list")
    machine.mark_refresh_confirm_clicked()
    machine.complete_refresh()

    assert machine.phase is ShopPhase.SCAN_TOP
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()

    assert machine.phase is ShopPhase.COMPLETE
    assert machine.stats.completed_refreshes == 1


def test_purchase_popup_must_match_pending_item_and_price():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(_row(ShopItemKind.COVENANT))

    assert machine.validate_purchase_popup(ShopItemKind.COVENANT, COVENANT_PRICE)
    assert not machine.validate_purchase_popup(ShopItemKind.MYSTIC, MYSTIC_PRICE)
    assert not machine.validate_purchase_popup(ShopItemKind.COVENANT, MYSTIC_PRICE)


def test_open_purchase_retry_requires_original_row_to_remain():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    original = _row(ShopItemKind.COVENANT, "row-a")
    machine.begin_purchase(original)

    assert machine.can_retry_open_purchase(original)
    assert not machine.can_retry_open_purchase(
        _row(ShopItemKind.COVENANT, "row-b")
    )


def test_purchase_confirm_latch_can_only_be_armed_once():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(_row(ShopItemKind.MYSTIC))

    assert machine.mark_purchase_confirm_clicked()
    assert not machine.mark_purchase_confirm_clicked()


def test_popup_exit_without_target_disappearance_does_not_commit():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(_row(ShopItemKind.COVENANT))
    machine.mark_purchase_confirm_clicked()

    assert not machine.complete_purchase(target_row_still_visible=True)
    assert machine.stats.initial_covenant == 0
    assert machine.phase is ShopPhase.WAIT_PURCHASE_RESULT


def test_purchase_commits_only_after_target_disappears():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(_row(ShopItemKind.MYSTIC))
    machine.mark_purchase_confirm_clicked()

    assert machine.complete_purchase(target_row_still_visible=False)

    assert machine.stats.initial_mystic == 1
    assert machine.phase is ShopPhase.SCAN_TOP


def test_refresh_confirm_latch_can_only_be_armed_once():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()
    machine.begin_refresh(source_price=3, source_fingerprint="old-list")

    assert machine.mark_refresh_confirm_clicked()
    assert not machine.mark_refresh_confirm_clicked()


def test_refresh_popup_cannot_be_confirmed_without_price_three_source():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()

    machine.begin_refresh(source_price=None, source_fingerprint="old-list")

    assert not machine.can_confirm_refresh


def test_stop_reason_is_preserved_for_summary():
    machine = ShopRefreshStateMachine(target_refreshes=5)

    machine.stop("金币不足")

    assert machine.phase is ShopPhase.STOPPED
    assert machine.stats.stop_reason == "金币不足"
    assert "金币不足" in machine.stats.summary()


def test_purchase_transaction_confirms_once_and_commits_after_shop_returns():
    row = _row(ShopItemKind.COVENANT)
    source = ShopObservation(
        page=ShopPage.SHOP,
        rows=(row,),
        refresh_point=(330, 1045),
        list_fingerprint="source",
    )
    confirm = ShopObservation(
        page=ShopPage.PURCHASE_CONFIRM,
        confirm_point=(1220, 815),
        cancel_point=(720, 815),
        purchase_kind=ShopItemKind.COVENANT,
        purchase_price=COVENANT_PRICE,
    )
    returned = ShopObservation(
        page=ShopPage.SHOP,
        rows=(),
        refresh_point=(330, 1045),
        list_fingerprint="sold",
    )
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        ShopRefreshStateMachine(1),
        _runtime(
            [_frame(1), _frame(1), _frame(2), _frame(2)],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: confirm, 2: returned}),
        sleep=clock.sleep,
        poll_seconds=0.1,
    )

    runner._purchase_transaction(row, source)

    actions = [action for _point, action in clicks]
    assert actions.count("open_purchase_confirm") == 1
    assert actions.count("confirm_purchase") == 1
    assert runner.machine.stats.initial_covenant == 1


def test_purchase_result_unknown_never_repeats_irreversible_confirm():
    row = _row(ShopItemKind.MYSTIC)
    source = ShopObservation(page=ShopPage.SHOP, rows=(row,))
    confirm = ShopObservation(
        page=ShopPage.PURCHASE_CONFIRM,
        confirm_point=(1220, 815),
        cancel_point=(720, 815),
        purchase_kind=ShopItemKind.MYSTIC,
        purchase_price=MYSTIC_PRICE,
    )
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        ShopRefreshStateMachine(1),
        _runtime(
            [_frame(1)] * 40,
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: confirm}),
        sleep=clock.sleep,
        poll_seconds=1.0,
        transaction_timeout=5.0,
    )

    with pytest.raises(RuntimeError, match="购买结果不明确"):
        runner._purchase_transaction(row, source)

    actions = [action for _point, action in clicks]
    assert actions.count("confirm_purchase") == 1
    assert runner.machine.stats.initial_mystic == 0


def test_open_purchase_retries_when_the_same_source_row_remains():
    row = _row(ShopItemKind.COVENANT)
    source = ShopObservation(page=ShopPage.SHOP, rows=(row,))
    confirm = ShopObservation(
        page=ShopPage.PURCHASE_CONFIRM,
        confirm_point=(1220, 815),
        cancel_point=(720, 815),
        purchase_kind=ShopItemKind.COVENANT,
        purchase_price=COVENANT_PRICE,
    )
    returned = ShopObservation(page=ShopPage.SHOP, rows=(), list_fingerprint="sold")
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        ShopRefreshStateMachine(1),
        _runtime(
            [_frame(1), _frame(1), _frame(2), _frame(2), _frame(3), _frame(3)],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: source, 2: confirm, 3: returned}),
        sleep=clock.sleep,
        poll_seconds=0.1,
        open_retry_seconds=0.1,
    )

    runner._purchase_transaction(row, source)

    actions = [action for _point, action in clicks]
    assert actions.count("open_purchase_confirm") == 2
    assert actions.count("confirm_purchase") == 1


def test_scroll_requires_motion_then_two_stable_shop_frames():
    machine = ShopRefreshStateMachine(1)
    machine.complete_top_scan()
    top = ShopObservation(page=ShopPage.SHOP, list_fingerprint="top")
    bottom = ShopObservation(page=ShopPage.SHOP, list_fingerprint="bottom")
    clock = _Clock()
    swipes: list[tuple[tuple[int, int], tuple[int, int], int]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(70), _frame(30), _frame(30)],
            clock=clock,
            clicks=[],
            swipes=swipes,
            logs=[],
        ),
        observer=_Observer({70: bottom, 30: bottom}),
        sleep=clock.sleep,
        poll_seconds=0.1,
    )

    runner._scroll_to_bottom(_frame(10), top)

    assert len(swipes) == 1
    assert machine.phase is ShopPhase.SCAN_BOTTOM


def test_refresh_transaction_confirms_once_after_dynamic_transition():
    machine = ShopRefreshStateMachine(1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()
    source = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="old",
        refresh_price=3,
    )
    confirm = ShopObservation(
        page=ShopPage.REFRESH_CONFIRM,
        confirm_point=(1120, 742),
        cancel_point=(800, 742),
    )
    unknown = ShopObservation(page=ShopPage.UNKNOWN)
    new_shop = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="new",
        refresh_price=3,
    )
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(1), _frame(1), _frame(90), _frame(20), _frame(20)],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: confirm, 90: unknown, 20: new_shop}),
        sleep=clock.sleep,
        poll_seconds=0.1,
    )

    runner._refresh_transaction(_frame(10), source)

    actions = [action for _point, action in clicks]
    assert actions.count("open_refresh_confirm") == 1
    assert actions.count("confirm_refresh") == 1
    assert machine.stats.completed_refreshes == 1
    assert machine.phase is ShopPhase.SCAN_TOP


def test_refresh_without_motion_or_fingerprint_change_stops_without_commit():
    machine = ShopRefreshStateMachine(1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()
    source = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="same",
        refresh_price=3,
    )
    confirm = ShopObservation(
        page=ShopPage.REFRESH_CONFIRM,
        confirm_point=(1120, 742),
        cancel_point=(800, 742),
    )
    unchanged = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="same",
        refresh_price=3,
    )
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(1), _frame(1)] + [_frame(10)] * 20,
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: confirm, 10: unchanged}),
        sleep=clock.sleep,
        poll_seconds=1.0,
        transaction_timeout=5.0,
    )

    with pytest.raises(RuntimeError, match="刷新结果不明确"):
        runner._refresh_transaction(_frame(10), source)

    actions = [action for _point, action in clicks]
    assert actions.count("confirm_refresh") == 1
    assert machine.stats.completed_refreshes == 0


def test_open_refresh_retries_when_the_shop_source_remains():
    machine = ShopRefreshStateMachine(1)
    machine.complete_top_scan()
    machine.complete_scroll()
    machine.complete_bottom_scan()
    source = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="old",
        refresh_price=3,
    )
    confirm = ShopObservation(
        page=ShopPage.REFRESH_CONFIRM,
        confirm_point=(1120, 742),
        cancel_point=(800, 742),
    )
    new_shop = ShopObservation(
        page=ShopPage.SHOP,
        refresh_point=(330, 1045),
        list_fingerprint="new",
        refresh_price=3,
    )
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(1), _frame(1), _frame(2), _frame(2), _frame(90), _frame(3), _frame(3)],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=_Observer({1: source, 2: confirm, 90: ShopObservation(page=ShopPage.UNKNOWN), 3: new_shop}),
        sleep=clock.sleep,
        poll_seconds=0.1,
        open_retry_seconds=0.1,
    )

    runner._refresh_transaction(_frame(10), source)

    actions = [action for _point, action in clicks]
    assert actions.count("open_refresh_confirm") == 2
    assert actions.count("confirm_refresh") == 1
