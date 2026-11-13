from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    ShopItemKind,
    ShopObservation,
    ShopPage,
    ShopRowObservation,
    build_shop_refresh_observer,
)
from auto_game_unified.games.epic7.shop_refresh import (
    COVENANT_PRICE,
    FRIENDSHIP_PURCHASE_LIMIT,
    MYSTIC_PRICE,
    ShopPhase,
    ShopRefreshRunner,
    ShopRefreshStateMachine,
    ShopRunStats,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_shop_refresh"


def _fixture(name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


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
    def __init__(
        self,
        observations: dict[int, ShopObservation],
        *,
        live_transactions_verified: bool = True,
    ) -> None:
        self.observations = observations
        self.live_transactions_verified = live_transactions_verified

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


def test_shop_stability_signature_does_not_use_exact_animated_fingerprint():
    first = ShopObservation(page=ShopPage.SHOP, list_fingerprint="0000000000000000")
    second = ShopObservation(page=ShopPage.SHOP, list_fingerprint="0000000000000003")

    assert (
        ShopRefreshRunner._observation_signature(first)
        == ShopRefreshRunner._observation_signature(second)
    )


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


def test_bookmark_note_adds_initial_and_refreshed_purchases():
    """结算里「买到几张」要把开局那批和刷新后买的加起来，不能只报一半。"""
    stats = ShopRunStats(
        target_refreshes=2,
        initial_covenant=2, paid_covenant=1,
        initial_mystic=1, paid_mystic=1,
    )

    assert stats.bookmark_note() == "买到 5 张书签（誓约 3 / 神秘 2）"


def test_bookmark_note_when_nothing_was_bought():
    stats = ShopRunStats(target_refreshes=0)

    assert stats.bookmark_note() == "这轮没买到书签"


def test_bookmark_note_never_reports_gold_or_skystone():
    """结算只报收获；金币、天空石、刷新次数留在过程日志里。"""
    stats = ShopRunStats(
        target_refreshes=3,
        initial_covenant=1,
        covenant_gold=COVENANT_PRICE,
        completed_refreshes=3,
    )

    note = stats.bookmark_note()

    assert "金币" not in note
    assert "钻石" not in note
    assert "刷新" not in note


def test_route_note_stays_empty_on_a_dry_run():
    """干跑没碰游戏，结算里不该冒出「这轮没买到书签」这种假消息。"""
    from types import SimpleNamespace

    runner = object.__new__(ShopRefreshRunner)
    runner.runtime = SimpleNamespace(dry_run=True)

    assert runner.route_note() == ""


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
    sold_row = ShopRowObservation(
        kind=ShopItemKind.COVENANT,
        item_center=(850, 305),
        buy_point=None,
        item_score=0.91,
        alternate_score=0.20,
        row_key="row-sold",
    )
    returned = ShopObservation(
        page=ShopPage.SHOP,
        rows=(sold_row,),
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
    assert runner._is_known_sold(sold_row)


def test_current_mystic_purchase_fixtures_complete_one_real_transaction():
    observer = build_shop_refresh_observer(TEMPLATES)
    source_screen = _fixture("mystic_row_live_20260831")
    popup_screen = _fixture("mystic_purchase_confirm_live_20260831")
    sold_screen = _fixture("mystic_purchased_row_live_20260831")
    source = observer.observe(source_screen)
    row = next(row for row in source.rows if row.kind is ShopItemKind.MYSTIC)
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        ShopRefreshStateMachine(1),
        _runtime(
            [popup_screen, popup_screen, sold_screen, sold_screen],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=observer,
        sleep=clock.sleep,
        poll_seconds=0.1,
    )

    runner._purchase_transaction(row, source, source_screen=source_screen)

    actions = [action for _point, action in clicks]
    assert actions.count("open_purchase_confirm") == 1
    assert actions.count("confirm_purchase") == 1
    assert runner.machine.stats.initial_mystic == 1
    sold = observer.observe(sold_screen)
    sold_row = next(row for row in sold.rows if row.kind is ShopItemKind.MYSTIC)
    assert runner._is_known_sold(sold_row)


def test_current_covenant_purchase_fixtures_complete_one_real_transaction():
    observer = build_shop_refresh_observer(TEMPLATES)
    source_screen = _fixture("covenant_row_live_20260831")
    popup_screen = _fixture("covenant_purchase_confirm_live_20260831")
    sold_screen = _fixture("covenant_purchased_row_live_20260831")
    source = observer.observe(source_screen)
    row = next(row for row in source.rows if row.kind is ShopItemKind.COVENANT)
    clock = _Clock()
    clicks: list[tuple[tuple[int, int], str]] = []
    runner = ShopRefreshRunner(
        ShopRefreshStateMachine(1),
        _runtime(
            [popup_screen, popup_screen, sold_screen, sold_screen],
            clock=clock,
            clicks=clicks,
            swipes=[],
            logs=[],
        ),
        observer=observer,
        sleep=clock.sleep,
        poll_seconds=0.1,
    )

    runner._purchase_transaction(row, source, source_screen=source_screen)

    actions = [action for _point, action in clicks]
    assert actions.count("open_purchase_confirm") == 1
    assert actions.count("confirm_purchase") == 1
    assert runner.machine.stats.initial_covenant == 1
    sold = observer.observe(sold_screen)
    sold_row = next(row for row in sold.rows if row.kind is ShopItemKind.COVENANT)
    assert runner._is_known_sold(sold_row)


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


def test_refresh_popup_itself_is_not_counted_as_list_motion():
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
            [_frame(1), _frame(1), _frame(1), _frame(1)]
            + [_frame(10)] * 20,
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

    assert machine.stats.completed_refreshes == 0
    assert [action for _point, action in clicks].count("confirm_refresh") == 1


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


def test_runner_scans_initial_and_last_refreshed_batch_end_to_end():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    logs: list[str] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=logs,
        ),
        observer=_Observer({}),
        sleep=clock.sleep,
    )
    observations = iter(
        [
            (_frame(10), ShopObservation(page=ShopPage.SHOP, list_fingerprint="initial-top")),
            (
                _frame(20),
                ShopObservation(
                    page=ShopPage.SHOP,
                    list_fingerprint="initial-bottom",
                    refresh_point=(330, 1045),
                    refresh_price=3,
                ),
            ),
            (_frame(30), ShopObservation(page=ShopPage.SHOP, list_fingerprint="paid-top")),
            (_frame(40), ShopObservation(page=ShopPage.SHOP, list_fingerprint="paid-bottom")),
        ]
    )
    calls = {"stable": 0, "scroll": 0, "refresh": 0}

    def stable_shop():
        calls["stable"] += 1
        return next(observations)

    def scroll_to_bottom(_screen, _observation):
        calls["scroll"] += 1
        machine.complete_scroll()

    def refresh_transaction(_screen, observation):
        calls["refresh"] += 1
        machine.begin_refresh(
            source_price=observation.refresh_price,
            source_fingerprint=observation.list_fingerprint,
        )
        assert machine.mark_refresh_confirm_clicked()
        machine.complete_refresh()

    runner._stable_shop = stable_shop
    runner._scroll_to_bottom = scroll_to_bottom
    runner._refresh_transaction = refresh_transaction

    assert runner.run(max_cycles=1) == 1
    assert calls == {"stable": 4, "scroll": 2, "refresh": 1}
    assert machine.phase is ShopPhase.COMPLETE
    assert any("本轮汇总" in log for log in logs)


def test_state_machine_accepts_zero_refreshes_but_not_negative():
    """0 是合法目标（只扫不刷新）；负数才是坏值。

    用户 2026-09-29 拍板：秘密商店自己会随时间自动刷新 ⇒ 默认 0 次。
    """
    machine = ShopRefreshStateMachine(0)

    assert machine.stats.target_refreshes == 0
    assert machine.phase is ShopPhase.SCAN_TOP

    with pytest.raises(ValueError, match="负数"):
        ShopRefreshStateMachine(-1)


def test_zero_refresh_run_scans_the_initial_list_and_never_refreshes():
    """0 次 = 照常进店、从上到下扫一遍、把想要的买掉，**一次都不付费刷新**。

    这是默认档位的可测形式：主循环必须走到 COMPLETE 就收工，而不是转成
    ``READY_REFRESH`` 去点那个花天空石的「立即更新」。
    """
    machine = ShopRefreshStateMachine(0)
    clock = _Clock()
    logs: list[str] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime([], clock=clock, clicks=[], swipes=[], logs=logs),
        observer=_Observer({}),
        sleep=clock.sleep,
    )
    observations = iter(
        [
            (
                _frame(10),
                ShopObservation(page=ShopPage.SHOP, list_fingerprint="initial-top"),
            ),
            (
                _frame(20),
                ShopObservation(
                    page=ShopPage.SHOP,
                    list_fingerprint="initial-bottom",
                    refresh_point=(330, 1045),
                    refresh_price=3,
                ),
            ),
        ]
    )
    calls = {"stable": 0, "scroll": 0}

    def stable_shop():
        calls["stable"] += 1
        return next(observations)

    def scroll_to_bottom(_screen, _observation):
        calls["scroll"] += 1
        machine.complete_scroll()

    def refresh_transaction(_screen, _observation):
        raise AssertionError("0 次不该走到付费刷新 —— 这一步会花天空石")

    runner._stable_shop = stable_shop
    runner._scroll_to_bottom = scroll_to_bottom
    runner._refresh_transaction = refresh_transaction

    assert runner.run(max_cycles=0) == 0

    # 顶部一次 + 底部一次；付费刷新一次都没有。
    assert calls == {"stable": 2, "scroll": 1}
    assert machine.phase is ShopPhase.COMPLETE
    assert machine.stats.target_refreshes == 0
    assert machine.stats.completed_refreshes == 0
    assert machine.stats.skystone_spent == 0
    assert "刷新=0/0" in logs[-1]
    # 0 次不是「没本钱了」—— 它是一个正常完成的结论，退出码不该变 2。
    assert runner.resource_exhausted is False


def test_runner_stops_when_unbought_target_has_no_same_row_buy_button():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=[],
        ),
        observer=_Observer({}),
        sleep=clock.sleep,
    )
    unavailable = ShopRowObservation(
        kind=ShopItemKind.COVENANT,
        item_center=(850, 305),
        buy_point=None,
        item_score=0.91,
        alternate_score=0.20,
        row_key="unavailable",
    )
    observation = ShopObservation(
        page=ShopPage.SHOP,
        rows=(unavailable,),
        list_fingerprint="source",
    )
    runner._stable_shop = lambda: (_frame(10), observation)

    with pytest.raises(RuntimeError, match="目标商品缺少同行购买按钮"):
        runner.run(max_cycles=1)

    assert machine.phase is ShopPhase.STOPPED
    assert "目标商品缺少同行购买按钮" in machine.stats.stop_reason


def test_known_sold_row_remains_known_after_scrolling_to_a_new_y_position():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=[],
        ),
        observer=_Observer({}),
        sleep=clock.sleep,
    )
    original = ShopRowObservation(
        kind=ShopItemKind.COVENANT,
        item_center=(850, 705),
        buy_point=None,
        item_score=0.91,
        alternate_score=0.20,
        row_key="same-item-content",
    )
    runner._remember_sold(original, ShopObservation(page=ShopPage.SHOP, rows=(original,)))
    machine.complete_top_scan()
    machine.complete_scroll()
    moved = ShopRowObservation(
        kind=ShopItemKind.COVENANT,
        item_center=(850, 305),
        buy_point=None,
        item_score=0.91,
        alternate_score=0.20,
        row_key="same-item-content",
    )

    assert runner._is_known_sold(moved)


def test_explicit_zero_of_one_row_is_known_sold_before_this_run():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=[],
        ),
        observer=_Observer({}),
        sleep=clock.sleep,
    )
    sold = ShopRowObservation(
        kind=ShopItemKind.COVENANT,
        item_center=(850, 705),
        buy_point=None,
        item_score=0.95,
        alternate_score=0.20,
        row_key="preexisting-sold",
        sold_out=True,
    )

    assert runner._is_known_sold(sold)


def test_scroll_does_not_accept_motion_that_returns_to_the_same_top_list():
    machine = ShopRefreshStateMachine(1)
    machine.complete_top_scan()
    top = ShopObservation(page=ShopPage.SHOP, list_fingerprint="top")
    clock = _Clock()
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(70), _frame(10), _frame(10)] * 8,
            clock=clock,
            clicks=[],
            swipes=[],
            logs=[],
        ),
        observer=_Observer({70: top, 10: top}),
        sleep=clock.sleep,
        poll_seconds=1.0,
        transaction_timeout=5.0,
    )

    with pytest.raises(RuntimeError, match="滚动到底部结果不明确"):
        runner._scroll_to_bottom(_frame(10), top)

    assert machine.phase is ShopPhase.STOPPED
    assert "来源指纹=top" in machine.stats.stop_reason


def test_live_run_is_blocked_until_current_target_evidence_is_verified():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    logs: list[str] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=logs,
        ),
        observer=_Observer({}, live_transactions_verified=False),
        sleep=clock.sleep,
    )

    with pytest.raises(RuntimeError, match="当前客户端实证"):
        runner.run(max_cycles=1)

    assert machine.phase is ShopPhase.STOPPED
    assert "当前客户端实证" in machine.stats.stop_reason
    assert any("停止原因=目标商品和购买价格尚未通过当前客户端实证" in log for log in logs)


def test_manual_stop_is_not_summarized_as_normal_completion():
    machine = ShopRefreshStateMachine(1)
    clock = _Clock()
    logs: list[str] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [],
            clock=clock,
            clicks=[],
            swipes=[],
            logs=logs,
        ),
        observer=_Observer({}),
        sleep=clock.sleep,
    )

    def manual_stop():
        raise ManualStop("用户按下 P，正在中断自动化")

    runner._stable_shop = manual_stop

    with pytest.raises(ManualStop):
        runner.run(max_cycles=1)

    assert machine.phase is ShopPhase.STOPPED
    assert machine.stats.stop_reason == "用户手动停止"
    assert any("停止原因=用户手动停止" in log for log in logs)


def _drivable_resumed_runner(
    *,
    resumed: bool,
    observations: list[tuple[np.ndarray, ShopObservation]],
    frames: list[np.ndarray],
):
    """搭一个能跑完一轮的 Runner，记录「第一次扫描时已经滑过几次」。"""

    machine = ShopRefreshStateMachine(1)
    if resumed:
        machine.mark_resumed_at_shop()
    clock = _Clock()
    logs: list[str] = []
    swipes: list[tuple[tuple[int, int], tuple[int, int], int]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(frames, clock=clock, clicks=[], swipes=swipes, logs=logs),
        observer=_Observer({1: observations[0][1]}),
        sleep=clock.sleep,
    )
    pending = iter(observations)
    scans: list[int] = []

    def stable_shop():
        scans.append(len(swipes))
        return next(pending)

    def scroll_to_bottom(_screen, _observation):
        machine.complete_scroll()

    def refresh_transaction(_screen, observation):
        machine.begin_refresh(
            source_price=observation.refresh_price,
            source_fingerprint=observation.list_fingerprint,
        )
        assert machine.mark_refresh_confirm_clicked()
        machine.complete_refresh()

    runner._stable_shop = stable_shop
    runner._scroll_to_bottom = scroll_to_bottom
    runner._refresh_transaction = refresh_transaction
    return runner, machine, swipes, scans, logs


def _drive_observations():
    return [
        (
            _frame(10),
            ShopObservation(page=ShopPage.SHOP, list_fingerprint="initial-top"),
        ),
        (
            _frame(20),
            ShopObservation(
                page=ShopPage.SHOP,
                list_fingerprint="initial-bottom",
                refresh_point=(330, 1045),
                refresh_price=3,
            ),
        ),
        (
            _frame(30),
            ShopObservation(page=ShopPage.SHOP, list_fingerprint="paid-top"),
        ),
        (
            _frame(40),
            ShopObservation(page=ShopPage.SHOP, list_fingerprint="paid-bottom"),
        ),
    ]


def test_resumed_run_returns_the_list_to_the_top_before_scanning():
    """人停在列表半截时，接力要先回顶再按「顶部批次」扫，否则滚不动会整轮失败。"""

    runner, machine, swipes, scans, logs = _drivable_resumed_runner(
        resumed=True,
        observations=_drive_observations(),
        frames=[_frame(1)] * 4,
    )

    assert runner.run(max_cycles=1) == 1
    assert swipes == [((1300, 220), (1300, 850), 500)], "回顶只滑一次，方向是往下拖"
    assert scans and scans[0] == 1, "第一次扫描时回顶滑动必须已经发生过"
    assert machine.resumed_at_shop
    assert any("接力准备=列表回到顶部" in log for log in logs)
    assert any("接力准备=列表已静止" in log for log in logs)


def test_plain_run_does_not_scroll_to_the_top():
    """没打接力记号时不许多滑那一下（正常开局本来就停在列表顶部）。"""

    runner, _machine, swipes, _scans, logs = _drivable_resumed_runner(
        resumed=False,
        observations=_drive_observations(),
        frames=[_frame(1)] * 4,
    )

    assert runner.run(max_cycles=1) == 1
    assert swipes == []
    assert not any("接力准备" in log for log in logs)


class _ForeverMovingObserver:
    """永远在变的列表：模拟「回顶后还在滚」。"""

    live_transactions_verified = True

    def __init__(self) -> None:
        self.count = 0

    def observe(self, _screen: np.ndarray) -> ShopObservation:
        self.count += 1
        return ShopObservation(
            page=ShopPage.SHOP,
            list_fingerprint=f"moving-{self.count}",
        )


def test_resumed_run_fails_closed_when_the_list_never_settles():
    """回顶后列表一直变（还在滚动）→ 失败关闭，不带着不确定的列表往下扫。"""

    machine = ShopRefreshStateMachine(1)
    machine.mark_resumed_at_shop()
    clock = _Clock()
    logs: list[str] = []
    swipes: list[tuple[tuple[int, int], tuple[int, int], int]] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime(
            [_frame(1)] * 100,
            clock=clock,
            clicks=[],
            swipes=swipes,
            logs=logs,
        ),
        observer=_ForeverMovingObserver(),
        sleep=clock.sleep,
    )

    def unexpected_scan():
        raise AssertionError("列表没静止就不该进入扫描")

    runner._stable_shop = unexpected_scan

    with pytest.raises(RuntimeError, match="接力回顶后商店列表未静止"):
        runner.run(max_cycles=1)

    assert len(swipes) == 1
    assert machine.phase is ShopPhase.STOPPED


def test_friendship_total_counts_the_initial_batch_as_well():
    """上限按**整轮**算：开局那一批 + 刷出来的都算进 `friendship_bought`。

    ⚠️ 只数 `paid_friendship` 会让开局买的那几个逃出上限 —— 它们记在
    `initial_friendship` 上（`commit_purchase` 按「刷新过没有」分账）。
    """

    stats = ShopRunStats(target_refreshes=1)

    stats.commit_purchase(ShopItemKind.FRIENDSHIP)
    assert stats.friendship_bought == 1

    stats.commit_refresh()
    stats.commit_purchase(ShopItemKind.FRIENDSHIP)
    assert stats.friendship_bought == 2


def test_friendship_purchases_stop_at_the_per_run_limit():
    """用户 2026-11-01：友情点数出现太频繁、目前不缺，一轮最多买 10 个。

    同一屏反复出现友情点数：前 10 次买、第 11 次跳过；跳过之后别的目标（誓约）
    照买，整轮还能正常收尾 —— 上限只针对友情点数，不许把路线判死。
    """

    machine = ShopRefreshStateMachine(0)
    clock = _Clock()
    logs: list[str] = []
    runner = ShopRefreshRunner(
        machine,
        _runtime([], clock=clock, clicks=[], swipes=[], logs=logs),
        observer=_Observer({}),
        sleep=clock.sleep,
    )

    friendship_only = ShopObservation(
        page=ShopPage.SHOP,
        list_fingerprint="same-list",
        rows=[_row(ShopItemKind.FRIENDSHIP)],
    )
    covenant_only = ShopObservation(
        page=ShopPage.SHOP,
        list_fingerprint="same-list",
        rows=[_row(ShopItemKind.COVENANT)],
    )
    empty = ShopObservation(page=ShopPage.SHOP, list_fingerprint="same-list")
    # ⚠️ 这里写死 11 而不是 ``FRIENDSHIP_PURCHASE_LIMIT + 1``：跟着常量走的话，
    # 常量改大测试也跟着改大，就永远「买满常量个」而不是「买满 10 个」——
    # 那是一条自己证明自己的假护栏。
    feed = iter(
        [friendship_only] * 11
        + [covenant_only]
        + [empty] * 2
    )
    runner._stable_shop = lambda: (_frame(10), next(feed))
    runner._scroll_to_bottom = lambda screen, observation: machine.complete_scroll()

    bought: list[ShopItemKind] = []

    def purchase(row, observation, *, source_screen):
        bought.append(row.kind)
        machine.begin_purchase(row)
        assert machine.mark_purchase_confirm_clicked()
        assert machine.complete_purchase(target_row_still_visible=False)

    runner._purchase_transaction = purchase

    runner.run(max_cycles=0)

    assert bought.count(ShopItemKind.FRIENDSHIP) == 10
    assert bought.count(ShopItemKind.COVENANT) == 1
    assert machine.phase is ShopPhase.COMPLETE
    assert any("友情点数=达到上限" in log for log in logs)


def test_the_friendship_limit_is_ten():
    """用户 2026-11-01 的口径：一轮最多买 10 个友情点数。

    常量是「改一个数字就生效」的那一处 —— 这条用例把那个数字钉住，
    免得有人顺手把它调大又不当回事。
    """

    assert FRIENDSHIP_PURCHASE_LIMIT == 10

