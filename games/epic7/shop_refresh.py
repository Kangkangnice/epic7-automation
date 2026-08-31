"""Simulator-only secret-shop refresh state and transaction runner."""

from dataclasses import dataclass
from enum import Enum
from time import sleep as default_sleep
from typing import Callable

import cv2
import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.supervisor import StableObservation

from auto_game_unified.games.epic7.evidence.shop_refresh import (
    LIST_FINGERPRINT_CHANGE_BITS,
    ShopItemKind,
    ShopObservation,
    ShopPage,
    ShopRefreshObserver,
    ShopRowObservation,
    shop_fingerprint_distance,
)


COVENANT_PRICE = 184_000
MYSTIC_PRICE = 280_000
REFRESH_PRICE = 3


class ShopPhase(Enum):
    SCAN_TOP = "scan_top"
    WAIT_SCROLL_RESULT = "wait_scroll_result"
    SCAN_BOTTOM = "scan_bottom"
    WAIT_PURCHASE_CONFIRM = "wait_purchase_confirm"
    WAIT_PURCHASE_RESULT = "wait_purchase_result"
    READY_REFRESH = "ready_refresh"
    WAIT_REFRESH_CONFIRM = "wait_refresh_confirm"
    WAIT_REFRESH_RESULT = "wait_refresh_result"
    COMPLETE = "complete"
    STOPPED = "stopped"


@dataclass
class ShopRunStats:
    target_refreshes: int
    completed_refreshes: int = 0
    initial_covenant: int = 0
    initial_mystic: int = 0
    paid_covenant: int = 0
    paid_mystic: int = 0
    covenant_gold: int = 0
    mystic_gold: int = 0
    stop_reason: str = ""

    @property
    def skystone_spent(self) -> int:
        return self.completed_refreshes * REFRESH_PRICE

    @property
    def total_gold(self) -> int:
        return self.covenant_gold + self.mystic_gold

    @property
    def covenant_hit_rate(self) -> float:
        if self.completed_refreshes == 0:
            return 0.0
        return self.paid_covenant / self.completed_refreshes

    @property
    def mystic_hit_rate(self) -> float:
        if self.completed_refreshes == 0:
            return 0.0
        return self.paid_mystic / self.completed_refreshes

    def commit_purchase(self, kind: ShopItemKind) -> None:
        if kind is ShopItemKind.COVENANT:
            if self.completed_refreshes == 0:
                self.initial_covenant += 1
            else:
                self.paid_covenant += 1
            self.covenant_gold += COVENANT_PRICE
            return
        if kind is ShopItemKind.MYSTIC:
            if self.completed_refreshes == 0:
                self.initial_mystic += 1
            else:
                self.paid_mystic += 1
            self.mystic_gold += MYSTIC_PRICE
            return
        raise ValueError(f"不能提交非目标商品：{kind.value}")

    def commit_refresh(self) -> None:
        if self.completed_refreshes >= self.target_refreshes:
            raise RuntimeError("付费刷新次数已达到目标")
        self.completed_refreshes += 1

    def summary(self) -> str:
        reason = self.stop_reason or "正常完成"
        return (
            f"刷新={self.completed_refreshes}/{self.target_refreshes} "
            f"钻石={self.skystone_spent} "
            f"初始誓约={self.initial_covenant} 初始神秘={self.initial_mystic} "
            f"付费誓约={self.paid_covenant} "
            f"誓约命中={self.covenant_hit_rate * 100:.2f}% "
            f"付费神秘={self.paid_mystic} "
            f"神秘命中={self.mystic_hit_rate * 100:.2f}% "
            f"誓约金币={self.covenant_gold} 神秘金币={self.mystic_gold} "
            f"总金币={self.total_gold} 停止原因={reason}"
        )


@dataclass
class PendingPurchase:
    row: ShopRowObservation
    resume_phase: ShopPhase
    confirm_clicked: bool = False

    @property
    def price(self) -> int:
        if self.row.kind is ShopItemKind.COVENANT:
            return COVENANT_PRICE
        if self.row.kind is ShopItemKind.MYSTIC:
            return MYSTIC_PRICE
        raise ValueError(f"非目标商品不能购买：{self.row.kind.value}")


@dataclass
class PendingRefresh:
    source_price: int | None
    source_fingerprint: str
    confirm_clicked: bool = False


class ShopRefreshStateMachine:
    def __init__(
        self,
        target_refreshes: int,
        *,
        observer: ShopRefreshObserver | None = None,
    ) -> None:
        if target_refreshes <= 0:
            raise ValueError("付费刷新次数必须为正数")
        self.stats = ShopRunStats(target_refreshes=target_refreshes)
        self.phase = ShopPhase.SCAN_TOP
        self.pending_purchase: PendingPurchase | None = None
        self.pending_refresh: PendingRefresh | None = None
        self.observer = observer

    @property
    def completed_cycles(self) -> int:
        return self.stats.completed_refreshes

    def _require(self, *phases: ShopPhase) -> None:
        if self.phase not in phases:
            expected = "/".join(phase.value for phase in phases)
            raise RuntimeError(
                f"阶段不允许：当前={self.phase.value} 期望={expected}"
            )

    def complete_top_scan(self) -> None:
        self._require(ShopPhase.SCAN_TOP)
        self.phase = ShopPhase.WAIT_SCROLL_RESULT

    def complete_scroll(self) -> None:
        self._require(ShopPhase.WAIT_SCROLL_RESULT)
        self.phase = ShopPhase.SCAN_BOTTOM

    def complete_bottom_scan(self) -> None:
        self._require(ShopPhase.SCAN_BOTTOM)
        self.phase = (
            ShopPhase.COMPLETE
            if self.stats.completed_refreshes >= self.stats.target_refreshes
            else ShopPhase.READY_REFRESH
        )

    def begin_purchase(self, row: ShopRowObservation) -> None:
        self._require(ShopPhase.SCAN_TOP, ShopPhase.SCAN_BOTTOM)
        if row.kind not in {ShopItemKind.COVENANT, ShopItemKind.MYSTIC}:
            raise ValueError("只允许购买誓约书签或神秘书签")
        if row.buy_point is None:
            raise ValueError("目标商品缺少同行购买按钮")
        self.pending_purchase = PendingPurchase(row=row, resume_phase=self.phase)
        self.phase = ShopPhase.WAIT_PURCHASE_CONFIRM

    def can_retry_open_purchase(self, visible_row: ShopRowObservation) -> bool:
        pending = self.pending_purchase
        return bool(
            self.phase is ShopPhase.WAIT_PURCHASE_CONFIRM
            and pending is not None
            and visible_row.row_key == pending.row.row_key
            and visible_row.kind is pending.row.kind
        )

    def validate_purchase_popup(
        self, kind: ShopItemKind, price: int | None
    ) -> bool:
        pending = self.pending_purchase
        return bool(
            self.phase is ShopPhase.WAIT_PURCHASE_CONFIRM
            and pending is not None
            and kind is pending.row.kind
            and price == pending.price
        )

    def mark_purchase_confirm_clicked(self) -> bool:
        pending = self.pending_purchase
        if pending is None or self.phase not in {
            ShopPhase.WAIT_PURCHASE_CONFIRM,
            ShopPhase.WAIT_PURCHASE_RESULT,
        }:
            return False
        if pending.confirm_clicked:
            return False
        pending.confirm_clicked = True
        self.phase = ShopPhase.WAIT_PURCHASE_RESULT
        return True

    def complete_purchase(self, *, target_row_still_visible: bool) -> bool:
        self._require(ShopPhase.WAIT_PURCHASE_RESULT)
        pending = self.pending_purchase
        if pending is None or not pending.confirm_clicked:
            return False
        if target_row_still_visible:
            return False
        self.stats.commit_purchase(pending.row.kind)
        self.phase = pending.resume_phase
        self.pending_purchase = None
        return True

    def begin_refresh(
        self, *, source_price: int | None, source_fingerprint: str
    ) -> None:
        self._require(ShopPhase.READY_REFRESH)
        self.pending_refresh = PendingRefresh(
            source_price=source_price,
            source_fingerprint=source_fingerprint,
        )
        self.phase = ShopPhase.WAIT_REFRESH_CONFIRM

    @property
    def can_confirm_refresh(self) -> bool:
        return bool(
            self.phase is ShopPhase.WAIT_REFRESH_CONFIRM
            and self.pending_refresh is not None
            and self.pending_refresh.source_price == REFRESH_PRICE
        )

    def mark_refresh_confirm_clicked(self) -> bool:
        pending = self.pending_refresh
        if pending is None or self.phase not in {
            ShopPhase.WAIT_REFRESH_CONFIRM,
            ShopPhase.WAIT_REFRESH_RESULT,
        }:
            return False
        if not self.can_confirm_refresh or pending.confirm_clicked:
            return False
        pending.confirm_clicked = True
        self.phase = ShopPhase.WAIT_REFRESH_RESULT
        return True

    def complete_refresh(self) -> None:
        self._require(ShopPhase.WAIT_REFRESH_RESULT)
        pending = self.pending_refresh
        if pending is None or not pending.confirm_clicked:
            raise RuntimeError("刷新确认尚未执行")
        self.stats.commit_refresh()
        self.pending_refresh = None
        self.phase = ShopPhase.SCAN_TOP

    def stop(self, reason: str) -> None:
        self.stats.stop_reason = reason
        self.phase = ShopPhase.STOPPED


class ShopRefreshRunner:
    _SCROLL_START = (1300, 850)
    _SCROLL_END = (1300, 220)
    _SCROLL_DURATION_MS = 500

    def __init__(
        self,
        machine: ShopRefreshStateMachine,
        runtime: Runtime,
        *,
        observer: ShopRefreshObserver | None = None,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 0.5,
        transaction_timeout: float = 20.0,
        open_retry_seconds: float = 2.0,
        recovery=None,
        recovery_gate=None,
    ) -> None:
        del recovery, recovery_gate
        self.machine = machine
        self.runtime = runtime
        self.observer = observer or machine.observer
        if self.observer is None:
            raise ValueError("ShopRefreshRunner 需要视觉观察器")
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.transaction_timeout = transaction_timeout
        self.open_retry_seconds = open_retry_seconds
        self.now = runtime.now
        self.resource_exhausted = False
        self._sold_slots: set[tuple[int, ShopPhase, ShopItemKind, int]] = set()
        self._sold_rows: set[tuple[int, ShopItemKind, str]] = set()

    @staticmethod
    def _observation_signature(observation: ShopObservation) -> str:
        if observation.page is ShopPage.SHOP:
            rows = ",".join(
                f"{row.kind.value}:{round(row.item_center[1] / 20)}:"
                f"{bool(row.buy_point)}:{row.sold_out}"
                for row in observation.rows
            )
            return f"shop:{rows}"
        if observation.page is ShopPage.PURCHASE_CONFIRM:
            return (
                f"purchase:{observation.purchase_kind.value}:"
                f"{observation.purchase_price}"
            )
        return observation.page.value

    @staticmethod
    def _visual_difference(before: np.ndarray, after: np.ndarray) -> float:
        if before.shape != after.shape:
            return float("inf")
        if before.shape[0] >= 900 and before.shape[1] >= 1500:
            before = before[140:1080, 650:1920]
            after = after[140:1080, 650:1920]
        difference = cv2.absdiff(before, after)
        return float(difference.mean())

    def _failure(
        self,
        message: str,
        screen: np.ndarray | None = None,
        *,
        evidence: dict[str, np.ndarray] | None = None,
    ) -> RuntimeError:
        self.machine.stop(message)
        if self.runtime.diagnostic_dir is not None:
            for label, evidence_screen in (evidence or {}).items():
                self.runtime.save_diagnostic(label, evidence_screen)
            diagnostic = self.runtime.save_diagnostic(
                "shop_refresh_unknown", screen
            )
            message = f"{message}；已保存诊断 {diagnostic}"
        self.runtime.log(f"模式=刷书签 结论=UNKNOWN 原因={message}")
        return RuntimeError(message)

    def _wait_stable(
        self,
        page: ShopPage,
        *,
        timeout: float | None = None,
    ) -> tuple[np.ndarray, ShopObservation]:
        deadline = self.now() + (timeout or self.transaction_timeout)
        stable = StableObservation(required=2)
        last_screen: np.ndarray | None = None
        last_observation: ShopObservation | None = None
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            last_observation = observation
            signature = self._observation_signature(observation)
            if stable.update(signature) and observation.page is page:
                return screen, observation
            self.sleep(self.poll_seconds)
        scores = dict(last_observation.scores or {}) if last_observation else {}
        raise self._failure(
            f"等待页面[{page.value}]超时 最终页="
            f"{last_observation.page.value if last_observation else 'none'} "
            f"分数={scores}",
            last_screen,
        )

    def _pending_row_visible(self, observation: ShopObservation) -> bool:
        pending = self.machine.pending_purchase
        if pending is None:
            return False
        return any(
            row.kind is pending.row.kind
            and row.buy_point is not None
            and abs(row.item_center[1] - pending.row.item_center[1]) <= 90
            for row in observation.rows
        )

    def _sold_slot_key(
        self, row: ShopRowObservation
    ) -> tuple[int, ShopPhase, ShopItemKind, int]:
        return (
            self.machine.completed_cycles,
            self.machine.phase,
            row.kind,
            round(row.item_center[1] / 60),
        )

    def _is_known_sold(self, row: ShopRowObservation) -> bool:
        row_identity = (
            self.machine.completed_cycles,
            row.kind,
            row.row_key,
        )
        return bool(
            row.sold_out
            or row_identity in self._sold_rows
            or self._sold_slot_key(row) in self._sold_slots
        )

    def _remember_sold(
        self,
        original: ShopRowObservation,
        observation: ShopObservation,
    ) -> None:
        candidates = [
            row
            for row in observation.rows
            if row.kind is original.kind
            and row.buy_point is None
            and abs(row.item_center[1] - original.item_center[1]) <= 90
        ]
        for row in (original, *candidates):
            self._sold_slots.add(self._sold_slot_key(row))
            self._sold_rows.add(
                (
                    self.machine.completed_cycles,
                    row.kind,
                    row.row_key,
                )
            )

    def _open_and_wait(
        self,
        *,
        point: tuple[int, int],
        action: str,
        target_page: ShopPage,
        source_still: Callable[[ShopObservation], bool],
    ) -> tuple[np.ndarray, ShopObservation]:
        attempts = 1
        self.runtime.log(
            f"模式=刷书签 执行动作={action} 尝试={attempts}/2"
        )
        self.runtime.click(point, action)
        clicked_at = self.now()
        deadline = clicked_at + self.transaction_timeout
        stable = StableObservation(required=2)
        last_screen: np.ndarray | None = None
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            signature = self._observation_signature(observation)
            if stable.update(signature) and observation.page is target_page:
                return screen, observation
            if (
                attempts < 2
                and source_still(observation)
                and self.now() - clicked_at >= self.open_retry_seconds
            ):
                attempts += 1
                self.runtime.log(
                    f"模式=刷书签 来源仍在 动作={action} 尝试={attempts}/2"
                )
                self.runtime.click(point, action)
                clicked_at = self.now()
                stable.reset()
            self.sleep(self.poll_seconds)
        raise self._failure(
            f"等待页面[{target_page.value}]超时，来源重试已耗尽",
            last_screen,
        )

    def _purchase_transaction(
        self,
        row: ShopRowObservation,
        source: ShopObservation,
        source_screen: np.ndarray | None = None,
    ) -> None:
        del source
        self.machine.begin_purchase(row)
        self.runtime.log(
            f"模式=刷书签 动作候选=purchase 目标={row.kind.value} "
            f"行={row.row_key} 分数={row.item_score:.3f} "
            f"备选分数={row.alternate_score:.3f}"
        )
        _popup_screen, popup = self._open_and_wait(
            point=row.buy_point,
            action="open_purchase_confirm",
            target_page=ShopPage.PURCHASE_CONFIRM,
            source_still=lambda observation: any(
                self.machine.can_retry_open_purchase(visible_row)
                for visible_row in observation.rows
            ),
        )
        if not self.machine.validate_purchase_popup(
            popup.purchase_kind, popup.purchase_price
        ):
            raise self._failure(
                "购买弹窗商品或价格与待购买目标不一致 "
                f"待购买={row.kind.value} "
                f"弹窗={popup.purchase_kind.value} "
                f"价格={popup.purchase_price}",
                _popup_screen,
                evidence=(
                    {"purchase_source": source_screen}
                    if source_screen is not None
                    else None
                ),
            )
        if popup.confirm_point is None:
            raise self._failure("购买弹窗缺少确认按钮", _popup_screen)
        if not self.machine.mark_purchase_confirm_clicked():
            raise self._failure("购买确认闩锁未能建立", _popup_screen)
        self.runtime.log(
            f"模式=刷书签 执行不可逆动作=confirm_purchase "
            f"目标={row.kind.value} 尝试=1/1 价格={popup.purchase_price}"
        )
        self.runtime.click(popup.confirm_point, "confirm_purchase")

        deadline = self.now() + self.transaction_timeout
        stable = StableObservation(required=2)
        last_screen: np.ndarray | None = None
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            if observation.page is ShopPage.GOLD_SHORTAGE:
                self.resource_exhausted = True
                self.machine.stop("金币不足")
                self.runtime.log("模式=刷书签 停止=金币不足")
                return
            if observation.page is ShopPage.SHOP:
                signature = self._observation_signature(observation)
                if stable.update(signature) and not self._pending_row_visible(
                    observation
                ):
                    self.machine.complete_purchase(
                        target_row_still_visible=False
                    )
                    self._remember_sold(row, observation)
                    self.runtime.log(
                        f"模式=刷书签 业务成功=购买 目标={row.kind.value} "
                        f"本轮统计={self.machine.stats.summary()}"
                    )
                    return
            else:
                stable.reset()
            self.sleep(self.poll_seconds)
        purchase_evidence = {"purchase_popup": _popup_screen}
        if source_screen is not None:
            purchase_evidence["purchase_source"] = source_screen
        raise self._failure(
            "购买结果不明确，禁止重复确认",
            last_screen,
            evidence=purchase_evidence,
        )

    def _scroll_to_bottom(
        self,
        source_screen: np.ndarray,
        source: ShopObservation,
    ) -> None:
        peak_screen = source_screen
        peak_difference = 0.0
        for attempt in range(1, 3):
            self.runtime.log(
                f"模式=刷书签 动作候选=scroll_bottom 尝试={attempt}/2"
            )
            self.runtime.swipe(
                self._SCROLL_START,
                self._SCROLL_END,
                self._SCROLL_DURATION_MS,
                "shop-scroll-bottom",
            )
            deadline = self.now() + self.transaction_timeout
            motion_seen = False
            stable = StableObservation(required=2)
            last_screen = source_screen
            while self.now() < deadline:
                screen = self.runtime.capture()
                last_screen = screen
                observation = self.observer.observe(screen)
                difference_from_source = self._visual_difference(
                    source_screen, screen
                )
                if difference_from_source > peak_difference:
                    peak_difference = difference_from_source
                    peak_screen = screen
                if difference_from_source >= 2.0:
                    motion_seen = True
                different_list = bool(
                    observation.page is ShopPage.SHOP
                    and observation.list_fingerprint
                    and shop_fingerprint_distance(
                        observation.list_fingerprint,
                        source.list_fingerprint,
                    )
                    >= LIST_FINGERPRINT_CHANGE_BITS
                )
                if motion_seen and different_list:
                    if stable.update(self._observation_signature(observation)):
                        self.machine.complete_scroll()
                        self.runtime.log(
                            "模式=刷书签 转场确认 动作=scroll_bottom "
                            f"目标=商店底部 画面差={difference_from_source:.3f}"
                        )
                        return
                else:
                    stable.reset()
                self.sleep(self.poll_seconds)
            final = self.observer.observe(last_screen)
            if attempt == 1:
                if (
                    final.page is ShopPage.SHOP
                    and shop_fingerprint_distance(
                        final.list_fingerprint,
                        source.list_fingerprint,
                    )
                    < LIST_FINGERPRINT_CHANGE_BITS
                ):
                    continue
            final_fingerprint = (
                final.list_fingerprint
                if final.page is ShopPage.SHOP
                else final.page.value
            )
            raise self._failure(
                "滚动到底部结果不明确 "
                f"来源指纹={source.list_fingerprint} "
                f"最终={final_fingerprint} "
                f"峰值画面差={peak_difference:.3f}",
                last_screen,
                evidence={
                    "scroll_source": source_screen,
                    "scroll_peak": peak_screen,
                },
            )

    def _refresh_transaction(
        self,
        source_screen: np.ndarray,
        source: ShopObservation,
    ) -> None:
        if source.refresh_point is None:
            raise self._failure("商店页缺少立即更新按钮", source_screen)
        self.machine.begin_refresh(
            source_price=source.refresh_price,
            source_fingerprint=source.list_fingerprint,
        )
        if not self.machine.can_confirm_refresh:
            raise self._failure("未确认立即更新价格为3天空石", source_screen)
        popup_screen, popup = self._open_and_wait(
            point=source.refresh_point,
            action="open_refresh_confirm",
            target_page=ShopPage.REFRESH_CONFIRM,
            source_still=lambda observation: bool(
                observation.page is ShopPage.SHOP
                and shop_fingerprint_distance(
                    observation.list_fingerprint,
                    source.list_fingerprint,
                )
                < LIST_FINGERPRINT_CHANGE_BITS
                and observation.refresh_price == REFRESH_PRICE
            ),
        )
        if popup.confirm_point is None:
            raise self._failure("刷新弹窗缺少确认按钮", popup_screen)
        if not self.machine.mark_refresh_confirm_clicked():
            raise self._failure("刷新确认闩锁未能建立", popup_screen)
        self.runtime.log(
            "模式=刷书签 执行不可逆动作=confirm_refresh 尝试=1/1 价格=3"
        )
        self.runtime.click(popup.confirm_point, "confirm_refresh")

        deadline = self.now() + self.transaction_timeout
        motion_seen = False
        popup_exited = False
        peak_screen = source_screen
        peak_difference = 0.0
        stable = StableObservation(required=2)
        last_screen: np.ndarray | None = None
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            if observation.page is ShopPage.REFRESH_CONFIRM:
                stable.reset()
                self.sleep(self.poll_seconds)
                continue
            popup_exited = True
            if observation.page is ShopPage.SKYSTONE_SHORTAGE:
                self.resource_exhausted = True
                self.machine.stop("钻石不足")
                self.runtime.log("模式=刷书签 停止=钻石不足")
                return
            difference = self._visual_difference(source_screen, screen)
            if difference > peak_difference:
                peak_difference = difference
                peak_screen = screen
            fingerprint_changed = bool(
                observation.page is ShopPage.SHOP
                and observation.list_fingerprint
                and shop_fingerprint_distance(
                    observation.list_fingerprint,
                    source.list_fingerprint,
                )
                >= LIST_FINGERPRINT_CHANGE_BITS
            )
            if popup_exited and (difference >= 2.0 or fingerprint_changed):
                motion_seen = True
            if (
                observation.page is ShopPage.SHOP
                and motion_seen
                and fingerprint_changed
            ):
                if stable.update(self._observation_signature(observation)):
                    self.machine.complete_refresh()
                    self.runtime.log(
                        "模式=刷书签 业务成功=刷新 "
                        f"已完成={self.machine.stats.completed_refreshes}/"
                        f"{self.machine.stats.target_refreshes} "
                        f"钻石花费={self.machine.stats.skystone_spent}"
                    )
                    return
            else:
                stable.reset()
            self.sleep(self.poll_seconds)
        final_observation = (
            self.observer.observe(last_screen)
            if last_screen is not None
            else None
        )
        final_fingerprint = (
            final_observation.list_fingerprint
            if final_observation is not None
            and final_observation.page is ShopPage.SHOP
            else final_observation.page.value
            if final_observation is not None
            else "none"
        )
        raise self._failure(
            "刷新结果不明确，禁止重复确认 "
            f"来源指纹={source.list_fingerprint} "
            f"最终={final_fingerprint} "
            f"峰值画面差={peak_difference:.3f}",
            last_screen,
            evidence={
                "refresh_source": source_screen,
                "refresh_popup": popup_screen,
                "refresh_peak": peak_screen,
            },
        )

    def _stable_shop(self) -> tuple[np.ndarray, ShopObservation]:
        return self._wait_stable(ShopPage.SHOP)

    def run(self, max_cycles: int | None = None) -> int:
        if max_cycles is None or max_cycles <= 0:
            raise ValueError("刷书签需要正数付费刷新次数")
        if self.machine.completed_cycles == 0:
            self.machine.stats.target_refreshes = max_cycles
        try:
            if self.runtime.dry_run:
                screen = self.runtime.capture()
                observation = self.observer.observe(screen)
                self.runtime.log(
                    f"模式=刷书签 空跑页面={observation.page.value} "
                    f"目标行数={len(observation.rows)}"
                )
                for row in observation.rows:
                    self.runtime.log(
                        f"模式=刷书签 空跑商品={row.kind.value} "
                        f"行={row.row_key} 分数={row.item_score:.3f} "
                        f"备选={row.alternate_score:.3f} "
                        f"同行购买按钮={'有' if row.buy_point else '无'}"
                    )
                return 0
            if not getattr(
                self.observer,
                "live_transactions_verified",
                False,
            ):
                reason = "目标商品和购买价格尚未通过当前客户端实证"
                self.machine.stop(reason)
                raise RuntimeError(
                    f"{reason}，已禁止实跑消费；请先完成誓约和神秘的当前客户端截图验收"
                )
            while self.machine.phase not in {
                ShopPhase.COMPLETE,
                ShopPhase.STOPPED,
            }:
                if self.machine.phase not in {
                    ShopPhase.SCAN_TOP,
                    ShopPhase.SCAN_BOTTOM,
                }:
                    raise self._failure(
                        f"主循环遇到未处理阶段={self.machine.phase.value}"
                    )
                screen, observation = self._stable_shop()
                uncertain = [
                    row for row in observation.rows
                    if row.kind is ShopItemKind.UNKNOWN
                ]
                if uncertain:
                    row = uncertain[0]
                    raise self._failure(
                        f"商品行证据冲突 行={row.row_key} "
                        f"分数={row.item_score:.3f} "
                        f"备选={row.alternate_score:.3f}",
                        screen,
                    )
                targets = [
                    row for row in observation.rows
                    if row.kind in {ShopItemKind.COVENANT, ShopItemKind.MYSTIC}
                    and row.buy_point is not None
                ]
                unavailable_targets = [
                    row
                    for row in observation.rows
                    if row.kind in {
                        ShopItemKind.COVENANT,
                        ShopItemKind.MYSTIC,
                    }
                    and row.buy_point is None
                    and not self._is_known_sold(row)
                ]
                if unavailable_targets:
                    row = unavailable_targets[0]
                    raise self._failure(
                        f"目标商品缺少同行购买按钮且并非本轮已购槽位 "
                        f"行={row.row_key} 目标={row.kind.value}",
                        screen,
                    )
                if targets:
                    self._purchase_transaction(
                        targets[0],
                        observation,
                        source_screen=screen,
                    )
                    continue
                if self.machine.phase is ShopPhase.SCAN_TOP:
                    self.runtime.log("模式=刷书签 批次顶部=扫描完成")
                    self.machine.complete_top_scan()
                    self._scroll_to_bottom(screen, observation)
                    continue
                self.runtime.log("模式=刷书签 批次底部=扫描完成")
                self.machine.complete_bottom_scan()
                if self.machine.phase is ShopPhase.COMPLETE:
                    break
                self._refresh_transaction(screen, observation)
            return self.machine.completed_cycles
        except ManualStop:
            if self.machine.phase not in {
                ShopPhase.COMPLETE,
                ShopPhase.STOPPED,
            }:
                self.machine.stop("用户手动停止")
            raise
        except Exception as error:
            if self.machine.phase not in {
                ShopPhase.COMPLETE,
                ShopPhase.STOPPED,
            }:
                self.machine.stop(str(error))
            raise
        finally:
            self.runtime.log(
                f"模式=刷书签 本轮汇总 {self.machine.stats.summary()}"
            )
