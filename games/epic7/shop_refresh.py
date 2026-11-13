"""Simulator-only secret-shop refresh state and transaction runner."""

from dataclasses import dataclass
from enum import Enum
from time import sleep as default_sleep
from typing import Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.supervisor import StableObservation

from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    LIST_FINGERPRINT_CHANGE_BITS,
    PURCHASE_PRICES,
    ROW_FINGERPRINT_CHANGED_ROWS,
    ROW_FINGERPRINT_TOTAL_BITS,
    ShopItemKind,
    ShopObservation,
    ShopPage,
    ShopRefreshObserver,
    ShopRowObservation,
    changed_shop_rows,
    shop_fingerprint_distance,
)


# 与观察器共用 ``PURCHASE_PRICES``：记账的单价和「弹窗价格条」证明的单价必须一致。
COVENANT_PRICE = PURCHASE_PRICES[ShopItemKind.COVENANT]
MYSTIC_PRICE = PURCHASE_PRICES[ShopItemKind.MYSTIC]
FRIENDSHIP_PRICE = PURCHASE_PRICES[ShopItemKind.FRIENDSHIP]
REFRESH_PRICE = 3

# 一轮最多买多少个友情点数（用户 2026-11-01 要求）。
#
# 原话：「友情点数一次最多买 10 个，它出现得比较频繁，目前不是很缺。我刷 100 次
# 它会出现很多次，但我不需要那么多 ⇒ 无论刷多少次，友情点数最多买 10 个」。
#
# ⚠️ 上限按**整轮**算（初始那一批 + 后面刷出来的都计入），不是「每次刷新最多 10 个」。
# 计数口径见 `ShopRunStats.friendship_bought`。
FRIENDSHIP_PURCHASE_LIMIT = 10


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
    initial_friendship: int = 0
    paid_covenant: int = 0
    paid_mystic: int = 0
    paid_friendship: int = 0
    covenant_gold: int = 0
    mystic_gold: int = 0
    friendship_gold: int = 0
    stop_reason: str = ""

    @property
    def skystone_spent(self) -> int:
        return self.completed_refreshes * REFRESH_PRICE

    @property
    def total_gold(self) -> int:
        return self.covenant_gold + self.mystic_gold + self.friendship_gold

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

    @property
    def friendship_bought(self) -> int:
        """本轮已买的友情点数总数：初始那一批 + 刷出来的都算。

        ⚠️ 不能只看 ``paid_friendship``：开局第一次扫描（还没刷新过）买的那几个
        记在 ``initial_friendship`` 上，漏了它上限就会多出开局那几个。
        """
        return self.initial_friendship + self.paid_friendship

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
        if kind is ShopItemKind.FRIENDSHIP:
            if self.completed_refreshes == 0:
                self.initial_friendship += 1
            else:
                self.paid_friendship += 1
            self.friendship_gold += FRIENDSHIP_PRICE
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
            f"初始友情={self.initial_friendship} "
            f"付费誓约={self.paid_covenant} "
            f"誓约命中={self.covenant_hit_rate * 100:.2f}% "
            f"付费神秘={self.paid_mystic} "
            f"神秘命中={self.mystic_hit_rate * 100:.2f}% "
            f"付费友情={self.paid_friendship} "
            f"誓约金币={self.covenant_gold} 神秘金币={self.mystic_gold} "
            f"友情金币={self.friendship_gold} "
            f"总金币={self.total_gold} 停止原因={reason}"
        )

    def bookmark_note(self) -> str:
        """给结算用的一句话收获：买到哪两类书签、各几张。

        只报收获。金币 / 天空石 / 刷新次数 / 命中率留在 ``summary()`` 的过程日志里，
        不进每日任务结算（2026-11-12 用户口径：结算不做收支账）。
        开局那一批和刷新后买的要**加起来**，否则只报了一半。
        """
        covenant = self.initial_covenant + self.paid_covenant
        mystic = self.initial_mystic + self.paid_mystic
        total = covenant + mystic
        if not total:
            return "本轮未购入书签"
        return f"购入书签 {total} 张（誓约 {covenant} / 神秘 {mystic}）"


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
        if self.row.kind is ShopItemKind.FRIENDSHIP:
            return FRIENDSHIP_PRICE
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
        # 0 是**合法**目标：照常进商店、从上到下扫一遍、把想要的买掉，但一次都不
        # 付费刷新（秘密商店自己会随时间自动刷新，0 次不花天空石 —— 见
        # ``ModeSpec.min_cycles`` 与 ``modes.py::_build_shop_refresh``）。
        # ``complete_bottom_scan()`` 用 ``completed_refreshes >= target_refreshes``
        # 收尾，目标为 0 时扫完底部直接进 COMPLETE，``_refresh_transaction`` 不会触发；
        # 此时买到的商品全部计入 ``initial_*``（``commit_purchase`` 按
        # ``completed_refreshes == 0`` 分流）。
        if target_refreshes < 0:
            raise ValueError("付费刷新次数不能为负数（0 = 只扫一遍、不刷新）")
        self.stats = ShopRunStats(target_refreshes=target_refreshes)
        self.phase = ShopPhase.SCAN_TOP
        self.pending_purchase: PendingPurchase | None = None
        self.pending_refresh: PendingRefresh | None = None
        self.observer = observer
        # 接力记号：探针认出「人已经把游戏停在商店页」时置位。Runner 看到它就先把
        # 列表拨回顶部再开扫（人停下时列表可能停在半截甚至底部）。
        self.resumed_at_shop = False

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
        if row.kind not in {
            ShopItemKind.COVENANT,
            ShopItemKind.MYSTIC,
            ShopItemKind.FRIENDSHIP,
        }:
            raise ValueError("只允许购买誓约书签、神秘书签或友情点数")
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

    def mark_resumed_at_shop(self) -> None:
        """记号：本轮是「人已经停在秘密商店页」接上来的。

        这条路线的 phase 是内部阶段、不是页面，所以接力**不拨 phase**（起始恒为
        SCAN_TOP）；这个记号只让 Runner 多做一次「列表回到顶部」的准备动作。
        """
        self.resumed_at_shop = True





def detect_resume_point(
    machine: ShopRefreshStateMachine,
    screen: np.ndarray,
    *,
    observed_page: Optional[str] = None,
) -> Optional[ResumePoint]:
    """刷书签开局接力：认出「人已经把游戏停在秘密商店页」就就地接管。

    这条路线的 10 个 phase（SCAN_TOP / WAIT_SCROLL_RESULT / … / STOPPED）**不是
    10 个页面** —— 整轮都待在同一张秘密商店页上，它们是内部阶段、不是可停靠画面。
    所以接力的判据只有一个：**这一帧就是秘密商店**。

    判据与导航器的「秘密商店」页面识别**同源**：两边都调 `ShopRefreshObserver`，
    都要求「商店标题 + 立即更新(3 空窗) + 购买按钮」三个锚点同时过阈，所以不会各认
    一套、也不会出现「导航说在商店、接力说不在」。

    接力**不拨状态机状态**（返回的 ``state`` 恒为 None）：phase 没法从中间接，
    起始恒为 SCAN_TOP。命中后由调用方给状态机打 ``mark_resumed_at_shop()`` 记号，
    Runner 会把列表先拨回顶部 —— 人停下时列表可能停在半截，直接当「顶部批次」扫会
    因为滚不动而以「滚动到底部结果不明确」整轮失败。

    弹窗（刷新确认 / 购买确认）**故意不接力**：``return_home`` 的那一下 Back 会先把
    弹窗关掉，下一帧扫到商店页就地接管，没必要为弹窗单独建判据。

    ``observed_page`` 是导航器认出来的页面名；本路线判据自带观察器，用不上它，
    保留形参只为与其它路线的探针签名保持一致。
    """
    del observed_page
    observer = machine.observer
    if observer is None:
        return None
    if observer.observe(screen).page is not ShopPage.SHOP:
        return None
    return ResumePoint("秘密商店")


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
        recovery_gate=None,
    ) -> None:
        # 本路线没有战斗 ⇒ 用不上战斗锁；main 统一注入的选项在这里显式丢弃。
        del recovery_gate
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
        # 「收尾回首页」钩子：由 main.run_mode 在 runner.run() 正常返回后注入。
        # ⚠️ 本路线**自带独立主循环**（裸定义、`super()` 0 次），走不到基类
        # `ModeRunnerBase._close_out`，所以这里必须自己声明、自己调用。
        # 契约同基类：**绝不抛异常**，失败返回原因字符串（退出码不变）。
        self.finish_home: Callable[[], Optional[str]] | None = None

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
            f"模式=刷书签 执行动作={action} 尝试={attempts}/3"
        )
        self.runtime.click(point, action)
        clicked_at = self.now()
        deadline = clicked_at + self.transaction_timeout
        stable = StableObservation(required=2)
        last_screen: np.ndarray | None = None
        # 超时时把「这 20 秒里到底看到过哪些页面」写进日志。
        # 2026-11-06 23:19 那次就吃亏在这：日志只有「点了一下」和「21 秒后超时」，
        # 中间一帧都没留，只能靠猜。去重后保序，最多十几项。
        seen_pages: list[str] = []
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            if not seen_pages or seen_pages[-1] != observation.page.value:
                seen_pages.append(observation.page.value)
            signature = self._observation_signature(observation)
            if stable.update(signature) and observation.page is target_page:
                return screen, observation
            if (
                attempts < 3
                and source_still(observation)
                and self.now() - clicked_at >= self.open_retry_seconds
            ):
                attempts += 1
                self.runtime.log(
                    f"模式=刷书签 来源仍在 动作={action} 尝试={attempts}/3"
                )
                self.runtime.click(point, action)
                clicked_at = self.now()
                stable.reset()
            self.sleep(self.poll_seconds)
        raise self._failure(
            f"等待页面[{target_page.value}]超时，来源重试已耗尽 "
            f"点击={attempts}次 期间页面={'→'.join(seen_pages) or '无'}",
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
            # 「这一批商品换了」有两条路，满足任一条即可：
            # ① 整块指纹够远（历史 100~132 位，铁证）；
            # ② **逐行**指纹显示大多数行都变了。2026-11-06 22:21 那次整批换只差
            #    60 位（阈 64），刚好卡在阈下 —— 那批 5 行里 4 行都是
            #    「4 星英雄 + 29,000 金币」，版面结构一样、低频分量抓不到差别，
            #    整块指纹和画面差（6.68，比「买掉一行」的 7.10 还小）双双失效。
            # ⚠️ ② 走的是**双条件**（行数 + 距离总和），只满足一个不算：
            #    一次买掉两三行也能把「变了的行数」顶上去，那会误判成刷新、多花 3 钻。
            changed_rows, row_distance = changed_shop_rows(
                source.row_fingerprints, observation.row_fingerprints
            )
            rows_replaced = (
                observation.page is ShopPage.SHOP
                and changed_rows >= ROW_FINGERPRINT_CHANGED_ROWS
                and row_distance >= ROW_FINGERPRINT_TOTAL_BITS
            )
            fingerprint_changed = rows_replaced or bool(
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
                        f"钻石花费={self.machine.stats.skystone_spent} "
                        f"逐行变化={changed_rows}/{len(observation.row_fingerprints)} "
                        f"总和={row_distance}"
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

    def _reset_list_to_top_after_resume(self) -> None:
        """接力专用：先把列表拨回顶部，再按「顶部批次」开始扫描。

        人停在商店页时列表可能停在半截甚至底部。接力如果直接把当前视口当成顶部批次
        扫，接着的 `_scroll_to_bottom` 会发现列表根本没动，整轮以「滚动到底部结果
        不明确」失败 —— 所以接力开头补一次回顶滑动。

        这里**不判定滑动是否真的产生位移**：本来就在顶部时它是空操作，动没动都只等
        「列表静止」这一个条件 —— 要求**连续三帧列表指纹一致**（比主循环的两帧更保守，
        滑动的惯性尾巴会让指纹短暂停顿）。回顶方向与 `_SCROLL_*` 相反（往下拖＝回到顶部）。
        """
        self.runtime.log("模式=刷书签 接力准备=列表回到顶部")
        self.runtime.swipe(
            self._SCROLL_END,
            self._SCROLL_START,
            self._SCROLL_DURATION_MS,
            "shop-scroll-top",
        )
        deadline = self.now() + self.transaction_timeout
        previous: str | None = None
        settled = 0
        last_screen: np.ndarray | None = None
        while self.now() < deadline:
            screen = self.runtime.capture()
            last_screen = screen
            observation = self.observer.observe(screen)
            if observation.page is not ShopPage.SHOP:
                previous = None
                settled = 0
                self.sleep(self.poll_seconds)
                continue
            fingerprint = observation.list_fingerprint
            settled = settled + 1 if fingerprint and fingerprint == previous else 0
            previous = fingerprint
            if settled >= 2:
                self.runtime.log(
                    "模式=刷书签 接力准备=列表已静止 动作=从顶部批次开始扫描"
                )
                return
            self.sleep(self.poll_seconds)
        raise self._failure("接力回顶后商店列表未静止", last_screen)

    def _close_out(self) -> None:
        """收尾回首页（刷书签自己的那一份，语义同 ``ModeRunnerBase._close_out``）。

        ⚠️ 这里是 ``run()`` 里**唯一的正常退出口**，它同时覆盖两种结局：
        ``COMPLETE``（刷满轮次，正常完成）与 ``STOPPED``（金币/钻石不足等资源类
        主动收工）。两者都该回家。

        ⚠️ 走不到这里的三类：``ManualStop``（用户喊停）、``_failure()`` 抛出的异常、
        以及实跑未验收那条 ``RuntimeError`` —— 它们都在 ``run()`` 的 ``except``
        分支里直接 ``raise``。

        ⚠️ **干跑也不接**：干跑在 ``try`` 里第 877 行就 ``return 0`` 了，
        根本到不了这里（那是「只观察一帧」的诊断路径，不该动游戏）。
        """
        if self.finish_home is None:
            return
        failure = self.finish_home()
        if failure is not None:
            self.runtime.log(
                f"模式=刷书签 收尾=回首页失败 原因={failure} "
                "处理=已忽略（不影响本次运行结论）"
            )

    def route_note(self) -> str:
        """整条路线的一句话结果，供每日任务结算显示（与竞技场的「战绩」并列）。

        干跑不碰游戏、本来就买不到东西，这时候报「没买到书签」是假消息 ⇒ 留空，
        结算里就不显示这一句。
        """
        if self.runtime.dry_run:
            return ""
        return self.machine.stats.bookmark_note()

    def run(self, max_cycles: int | None = None) -> int:
        if max_cycles is None or max_cycles < 0:
            raise ValueError("刷书签的付费刷新次数不能为负数（0 = 只扫一遍、不刷新）")
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
            if self.machine.resumed_at_shop:
                self._reset_list_to_top_after_resume()
            friendship_cap_logged = False
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
                # 友情点数买到上限之后，**两种名单都不再收它**：
                # 收进 targets 会继续买；收进 unavailable_targets 会因为「目标商品
                # 缺少同行购买按钮」把整轮判死 —— 可我们已经不打算买它了。
                friendship_full = (
                    self.machine.stats.friendship_bought
                    >= FRIENDSHIP_PURCHASE_LIMIT
                )
                if friendship_full and not friendship_cap_logged:
                    self.runtime.log(
                        f"模式=刷书签 友情点数=达到上限"
                        f"（{FRIENDSHIP_PURCHASE_LIMIT} 个）本轮不再购买"
                    )
                    friendship_cap_logged = True
                targets = [
                    row for row in observation.rows
                    if row.kind
                    in {
                        ShopItemKind.COVENANT,
                        ShopItemKind.MYSTIC,
                        ShopItemKind.FRIENDSHIP,
                    }
                    and row.buy_point is not None
                    and not (
                        friendship_full and row.kind is ShopItemKind.FRIENDSHIP
                    )
                ]
                unavailable_targets = [
                    row
                    for row in observation.rows
                    if row.kind in {
                        ShopItemKind.COVENANT,
                        ShopItemKind.MYSTIC,
                        ShopItemKind.FRIENDSHIP,
                    }
                    and row.buy_point is None
                    and not self._is_known_sold(row)
                    and not (
                        friendship_full and row.kind is ShopItemKind.FRIENDSHIP
                    )
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
            self._close_out()
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
