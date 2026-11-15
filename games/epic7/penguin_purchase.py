"""企鹅批量购买（``penguin_purchase``）的循环决策层。

业务流程（2026-11-15 用户口述定稿）：

    大厅 → 圣域 → 精灵之森（前半段完全沿用「圣域收菜」的导航链）
    → 右下角「成长祭坛」→ 左侧「企鹅巢穴」→ 绿色「购买」
    → 数量弹窗（不是 50/50 就点「最多」补齐）→「购买」
    → 关「企鹅成长完成」弹窗 → 下一轮

一轮 = 购入 50 只企鹅；默认 10 轮，可调；10 轮合计 500 只，不是 10 只。
消耗红叶，购入不可撤销；跑完按现有路线惯例返回大厅。

本模块只回答「当前确认到哪一页，下一步该发什么动作」，不加载模板、
不写点击坐标、不认图。页面证据由 evidence 层在真机帧采到之后接入，
点击坐标由 Runner 按模板落点给出。未采到的页面一律安全停止，
不猜坐标、不盲点、不重复发购买。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

from auto_game_unified.core.matcher import Match, load_template, locate_with_fallback
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.penguin_purchase import (
    build_penguin_purchase_evidence,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint, observe_page_probe
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.sanctuary import SANCTUARY_HOME_PAGE
from auto_game_unified.games.epic7.template_paths import is_pc, is_template_root
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


DEFAULT_CYCLES = 10
PENGUINS_PER_CYCLE = 50
# 「最多」是幂等按钮，但补点后仍不到 50/50 不许无限重试。
_MAX_RETRIES = 3


class PenguinPage(Enum):
    """证据层能确认的页面。这一层不认图，只消费页面名。"""

    HOME = "圣域主页"
    FOREST = "精灵之森"
    ALTAR = "成长祭坛"
    NEST = "企鹅巢穴"
    QUANTITY = "数量弹窗"
    COMPLETE = "企鹅成长完成"
    LOBBY = "大厅"
    CURRENCY_SHORT = "红叶不足"
    UNKNOWN = "未登记页面"


@dataclass(frozen=True)
class Observation:
    """一帧画面能确认的事实。价格与数量两项由购买判据分别给出。"""

    page: PenguinPage
    quantity_is_max: bool = False
    max_button_visible: bool = False
    price_is_expected: bool = False


@dataclass(frozen=True)
class Decision:
    """下一步动作。坐标与转场验收由 Runner 在采帧后补齐。"""

    name: str
    reason: str


class PenguinPurchaseMachine:
    """每帧重判页面的循环决策；业务进度只由 ``commit`` 推进。

    ``mark_issued`` 在动作发出瞬间调用，用来锁住不可逆动作；
    ``commit`` 在动作验收成功后调用，用来推进轮数。两者分开，
    避免「点被吞掉」被算成买成了一轮。
    """

    def __init__(self, cycles: int = DEFAULT_CYCLES) -> None:
        if cycles < 1:
            raise ValueError("轮数至少为 1")
        self.cycles = cycles
        self.completed_cycles = 0
        self.finish_reason = ""
        self._buy_issued = False
        self._close_issued = False
        self._max_attempts = 0

    @property
    def total_penguins(self) -> int:
        """已购入的企鹅只数。一轮 50 只，不是一只。"""
        return self.completed_cycles * PENGUINS_PER_CYCLE

    def next_action(self, obs: Observation) -> Decision | None:
        if self.finish_reason:
            return None
        if self.completed_cycles >= self.cycles:
            return Decision("finish", f"已完成 {self.completed_cycles} 轮，按惯例返回大厅")

        page = obs.page
        if page is PenguinPage.UNKNOWN:
            return Decision("stop-unknown", "当前页面未登记，安全停止并留诊断")
        if page is PenguinPage.CURRENCY_SHORT:
            return Decision("stop-currency", "红叶不足或出现购买货币提示，不购入零散数量")
        if page is PenguinPage.COMPLETE:
            if self._buy_issued and not self._close_issued:
                return Decision("close-complete", "企鹅成长完成弹窗出现，关闭后结束一轮")
            return None
        if page is PenguinPage.QUANTITY:
            if not obs.price_is_expected:
                return Decision("stop-price", "报价与企鹅固定报价不符，停止购买")
            if obs.quantity_is_max:
                if not self._buy_issued:
                    return Decision("buy", "数量已为 50/50 且报价匹配，本轮执行一次购买")
                return None
            if obs.max_button_visible and self._max_attempts < _MAX_RETRIES:
                return Decision("set-max", "数量不是 50/50，点「最多」补齐")
            return Decision("stop-quantity", "补点「最多」后数量仍不到 50/50，停止购买")
        if page is PenguinPage.NEST:
            return Decision("open-quantity", "企鹅巢穴页，点绿色「购买」进入数量弹窗")
        if page is PenguinPage.ALTAR:
            return Decision("select-nest", "成长祭坛弹窗，选左侧「企鹅巢穴」")
        if page is PenguinPage.FOREST:
            return Decision("open-altar", "精灵之森页，点右下角「成长祭坛」")
        if page is PenguinPage.LOBBY:
            return Decision("navigate-sanctuary", "从大厅沿用圣域收菜的导航链进入精灵之森")
        return Decision("stop-unknown", "当前页面未登记，安全停止并留诊断")

    def mark_issued(self, name: str) -> None:
        """Runner 发出动作后登记：购买只发一次，停止类动作立即收工。"""
        if name == "buy":
            self._buy_issued = True
        elif name == "set-max":
            self._max_attempts += 1
        elif name == "close-complete":
            self._close_issued = True
        elif name == "finish":
            self.finish_reason = "finish"
        elif name.startswith("stop-"):
            self.finish_reason = name

    def commit(self, name: str) -> None:
        """动作验收成功后推进业务进度，并重置本轮的不可逆标记。"""
        if name == "close-complete" and self._buy_issued:
            self.completed_cycles += 1
            self._buy_issued = False
            self._close_issued = False
            self._max_attempts = 0


# ---- 视觉层：把真机帧变成 Observation，再把决策变成带落点的动作 ----------------

@dataclass(frozen=True)
class PenguinPurchaseTemplates:
    sanctuary_home_row: np.ndarray
    forest_title: np.ndarray
    altar_button: np.ndarray
    altar_title: np.ndarray
    nest_tab_label: np.ndarray
    nest_buy_button: np.ndarray
    quantity_title: np.ndarray
    nest_item_name: np.ndarray
    max_button: np.ndarray
    quantity_50_50: np.ndarray
    full_price: np.ndarray
    unit_price: np.ndarray
    quantity_buy_text: np.ndarray
    complete_title: np.ndarray
    complete_close: np.ndarray
    evidence: object = None
    pc: bool = False


def build_penguin_purchase_templates(template_root: Path) -> PenguinPurchaseTemplates:
    """缺一张判据图就直接抛错，绝不带着半套判据上真机。"""
    folder = template_root / "penguin_purchase"

    def one(name: str) -> np.ndarray:
        return load_template(str(folder / f"{name}.png"))

    return PenguinPurchaseTemplates(
        sanctuary_home_row=load_template(
            str(template_root / "sanctuary" / "forest_row.png")
        ),
        forest_title=one("forest_title"),
        altar_button=one("altar_button"),
        altar_title=one("altar_title"),
        nest_tab_label=one("nest_tab_label"),
        nest_buy_button=one("nest_buy_button"),
        quantity_title=one("quantity_title"),
        nest_item_name=one("nest_item_name"),
        max_button=one("max_button"),
        quantity_50_50=one("quantity_50_50"),
        full_price=one("full_price"),
        unit_price=one("unit_price"),
        quantity_buy_text=one("quantity_buy_text"),
        complete_title=one("complete_title"),
        complete_close=one("complete_close"),
        evidence=build_penguin_purchase_evidence(folder),
        pc=is_pc(template_root),
    )


# evidence 页面键 -> 决策层页面。顺序即判定顺序（弹窗压暗底页，见 evidence 模块）。
_PAGE_STATES = (
    ("penguin_purchase.complete", PenguinPage.COMPLETE),
    ("penguin_purchase.quantity", PenguinPage.QUANTITY),
    ("penguin_purchase.altar", PenguinPage.ALTAR),
    ("penguin_purchase.forest", PenguinPage.FOREST),
    ("penguin_purchase.home", PenguinPage.HOME),
)


class PenguinPurchaseStateMachine(PenguinPurchaseMachine):
    """每帧重判页面的视觉状态机；业务进度只由 ``commit`` 推进。

    继承循环决策层：动作选择、购买闩锁、轮数累计都走同一份业务规则；
    本层只负责「认页面 → 组装 Observation → 给动作加坐标与转场契约」。
    """

    def __init__(
        self,
        templates: PenguinPurchaseTemplates | Path,
        *,
        cycles: int = DEFAULT_CYCLES,
    ) -> None:
        super().__init__(cycles=cycles)
        self.templates = (
            build_penguin_purchase_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = PenguinPage.HOME
        self._confirmed_page = ""

    # ---- 视觉判据 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        return locate_with_fallback(
            name,
            screen,
            getattr(self.templates, name),
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
            mode=atom.match_mode,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        match = self._locate(screen, name)
        if match is None:
            raise UnrecognizedScreen(
                f"企鹅批量购买画面里找不到锚点 {name}；为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[PenguinPage]:
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, page in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return page
        return None

    def observation(self, screen: np.ndarray) -> Observation:
        """页面 + 数量/报价状态。价格必须与数量配对，不能只认「有价格」。"""
        page = self.observe_page(screen) or PenguinPage.UNKNOWN
        if page is not PenguinPage.QUANTITY:
            return Observation(page)
        quantity_full = self._locate(screen, "quantity_50_50") is not None
        price_anchor = "full_price" if quantity_full else "unit_price"
        return Observation(
            page,
            quantity_is_max=quantity_full,
            max_button_visible=self._locate(screen, "max_button") is not None,
            price_is_expected=self._locate(screen, price_anchor) is not None,
        )

    # ---- 动作构造 ----

    def _action(
        self,
        name: str,
        screen: np.ndarray,
        anchor: str,
        *,
        source_page: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
        reason: str = "",
    ) -> RouteAction:
        match = self._required(screen, anchor)
        return RouteAction(
            name=name,
            point=match.center,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason or f"{anchor}@{match.center}",
        )

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        page = self.observe_page(screen)
        if page is None:
            self.state = PenguinPage.UNKNOWN
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                "企鹅批量购买画面未识别；未登记页面已安全停止并留证，不猜测坐标"
            )
        self.state = page
        self._confirmed_page = page.value

        # 导航链终点：沿用收菜路线的「精灵之森」入口，不另造导航。
        if page is PenguinPage.HOME:
            return self._action(
                "open-forest",
                screen,
                "sanctuary_home_row",
                source_page=page.value,
                target_pages=(PenguinPage.FOREST.value,),
                reason="圣域主页右侧第一行「精灵之森」，沿用圣域收菜的导航链",
            )

        # 完成弹窗关掉、画面回到成长祭坛，才把这一轮记成买成了。
        if page is PenguinPage.ALTAR and self._buy_issued and self._close_issued:
            self.commit("close-complete")

        decision = super().next_action(self.observation(screen))
        if decision is None or decision.name == "finish":
            return None
        name = decision.name
        if name.startswith("stop-"):
            self.mark_issued(name)
            raise UnrecognizedScreen(f"企鹅批量购买已安全停止：{decision.reason}")
        if name == "navigate-sanctuary":
            raise UnrecognizedScreen(
                "站在大厅，导航尚未把画面送到圣域主页；已安全停止并留证"
            )
        if name in ("select-nest", "open-quantity"):
            # 实测：顶部「企鹅巢穴」是分组标签，点它不换页。选范围的动作由
            # 页面判据（分组标签 + 第一列 102 红叶报价）落实，落点直接给第一列购买。
            return self._action(
                "open-quantity",
                screen,
                "nest_buy_button",
                source_page=page.value,
                target_pages=(PenguinPage.QUANTITY.value,),
                reason=(
                    "已确认「企鹅巢穴」分组与第一列 102 红叶报价；"
                    "点第一列购买进入数量弹窗，后三列商品不在搜索区域内"
                ),
            )
        if name == "set-max":
            self.mark_issued(name)
            return self._action(
                "set-max",
                screen,
                "max_button",
                source_page=page.value,
                in_page_evidence="数量显示由 1/50 变为 50/50，总价由 102 变为 5,100",
                reason=f"数量不是 50/50，点「最多」补齐（第 {self._max_attempts}/3 次）",
            )
        if name == "buy":
            self.mark_issued(name)
            return self._action(
                "buy",
                screen,
                "quantity_buy_text",
                source_page=page.value,
                target_pages=(PenguinPage.COMPLETE.value,),
                reason="数量 50/50 且报价 5,100 匹配，本轮执行一次购入，绝不重复点击",
            )
        if name == "close-complete":
            self.mark_issued(name)
            return self._action(
                "close-complete",
                screen,
                "complete_close",
                source_page=page.value,
                target_pages=(PenguinPage.ALTAR.value,),
                reason="「企鹅成长完成！」弹窗底部「点击关闭」，关闭后结束一轮",
            )
        if name == "open-altar":
            return self._action(
                "open-altar",
                screen,
                "altar_button",
                source_page=page.value,
                target_pages=(PenguinPage.ALTAR.value,),
                reason="精灵之森右下角「成长祭坛」",
            )
        raise UnrecognizedScreen(f"未登记的动作 {name}；已安全停止并留证")

    def preview(self, screen: np.ndarray):
        """两帧稳定确认的试算入口：算完把业务进度原样还回去。"""
        snapshot = (
            self.state,
            self.completed_cycles,
            self.finish_reason,
            self._buy_issued,
            self._close_issued,
            self._max_attempts,
            self._confirmed_page,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.finish_reason,
                self._buy_issued,
                self._close_issued,
                self._max_attempts,
                self._confirmed_page,
            ) = snapshot


def state_label(state: PenguinPage) -> str:
    return state.value


def detect_resume_point(
    machine: "PenguinPurchaseStateMachine",
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """开局接力：只接不会扣费的页面。

    数量弹窗与完成弹窗都紧邻扣费动作，刻意不接力；认不出就照旧走
    「回大厅 → 进圣域 → 精灵之森」，与补星路线「准备/结算页不接力」同源。
    """
    return observe_page_probe(
        machine,
        screen,
        resumable=frozenset({PenguinPage.HOME, PenguinPage.FOREST, PenguinPage.ALTAR}),
        label=state_label,
        entry_page=PenguinPage.HOME,
        entry=SANCTUARY_HOME_PAGE,
    )


class PenguinPurchaseRunner(ModeRunnerBase):
    """企鹅批量购买 Runner。主循环协议见 ``ModeRunnerBase``。"""

    _MODE_LABEL = "企鹅批量购买"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {page: 45 for page in PenguinPage}
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 这些动作点完一两秒就能看出生效，不给 45 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset(
        {"open-forest", "open-altar", "open-quantity", "set-max", "buy", "close-complete"}
    )
    _SHORT_RETRY_SECONDS = 8.0

    def run(self, max_cycles: Optional[int] = None) -> int:
        """界面次数框是唯一的轮数上限，开跑前同步给状态机。

        2026-11-15 实跑：次数填 20，状态机仍按装配时的默认 10 轮判定，
        第 10 轮后返回「收工」，主循环还在等 20 轮，画面停在成长祭坛
        干等 45 秒后报状态超时。各入口都把填写值作为 ``max_cycles`` 传入。
        """
        if max_cycles is not None:
            self.machine.cycles = max_cycles
        return super().run(max_cycles=max_cycles)

    def route_note(self) -> str:
        if self.runtime.dry_run or self.machine.completed_cycles < 1:
            return ""
        return (
            f"已购入 {self.machine.total_penguins} 只企鹅，"
            f"共 {self.machine.completed_cycles} 轮"
        )

    def _state_label(self, state: PenguinPage) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} "
            f"企鹅={self.machine.total_penguins}"
        )
