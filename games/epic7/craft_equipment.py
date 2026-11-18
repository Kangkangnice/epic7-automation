"""装备制作（``craft_equipment``）的循环决策层。

业务流程（2026-11-17 用户口述 + 当日模拟器实机走查定稿）：

    大厅 → 右上角蓝四格 → 快捷菜单第 3 行第 3 列「钢铁工坊」
    → 左侧第 1 个图标「制作装备」→ 选讨伐 → 选部位
    → 确认「制作次数」为 10 →「制作」→ 确认弹窗「制作装备10次」→「制作」
    → 制作动画 → 结果页「制作完毕」
    → 不整理：直接「重新制作」；整理：整理 → 快速选择 → 出售/萃取 → 确认 →「重新制作」
    → 回到确认弹窗，下一轮

一轮 = 制作 10 件。用户口径「打 20 次」= 20 轮 = 200 件。

## ⚠️ 两处实测与口述不同的地方

1. **「整理」不是新页面**：它把结果页底部换成工具栏（快速选择 / 出售 / 萃取 /
   确认 / 重新制作 / 取消），标题仍是「制作完毕」。所以「结果页」与「整理态」
   靠工具栏判据区分，不靠标题。
2. **档位默认不是 10**：进页面时「1」是选中态，只是材料数字按上一轮的 10 件显示。
   每一轮都必须用 ``qty_10_selected`` 确认白底在「10」上。

## 危险动作的边界

「制作」与「出售/萃取」都不可撤销（前者扣材料与金币，后者销毁装备）。
本模块的约束是：
- 确认弹窗必须同时有正文锚点与绿色按钮才出手（``craft_equipment.confirm``）；
- 出售/萃取只在「快速选择已勾选」之后点，且二次确认弹窗必须认出对应正文；
- 未登记页面一律安全停止，不猜坐标。

## 已知缺口

金币不足 / 材料不足 / 背包已满三种弹窗没有真机帧。前两种按「未登记页面」停止；
背包已满走全局弹窗通道（``global_popups``），命中即资源耗尽收工。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, load_template, locate_with_fallback
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.craft_equipment import (
    build_craft_equipment_evidence,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint, observe_page_probe
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.template_paths import is_pc, is_template_root
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


DEFAULT_CYCLES = 20
ITEMS_PER_CYCLE = 10

# 五个讨伐：游戏内名称 + 用户习惯叫法 + 顶部 tab 的画布坐标。
# ⚠️ 名字以**界面原文**为准（2026-11-17 逐张点开核对）：国服写「报丧妖」「阿吉玛纳克」
# 「卡戴斯」，不是攻略站的「女妖」「阿兹马纳克」「凯德斯」。
HUNT_TABS: tuple[tuple[str, str, str, int], ...] = (
    ("dragon", "双足飞龙", "龙讨伐", 297),
    ("golem", "魔像", "木讨伐", 451),
    ("banshee", "报丧妖", "水讨伐", 601),
    ("azimanak", "阿吉玛纳克", "暗讨伐", 751),
    ("caides", "卡戴斯", "光讨伐", 901),
)
HUNT_TAB_Y = 215

# 六个部位：上方武器 → 顺时针 项链 / 戒指 → 下方鞋子 → 铠甲 → 头盔。
SLOT_POINTS: tuple[tuple[str, str, int, int], ...] = (
    ("weapon", "武器", 762, 379),
    ("helmet", "头盔", 521, 506),
    ("armor", "铠甲", 527, 763),
    ("necklace", "项链", 982, 506),
    ("ring", "戒指", 982, 758),
    ("boots", "鞋子", 749, 897),
)

# 「制作次数」里的「10」。控件位置固定，用固定坐标（来源页身份由页面判据把关）。
QTY_10_POINT = (1857, 797)

TIDY_MODES = ("none", "sell", "extract")

# 导航页名（与 ``navigation.PAGE_LABELS`` 的键一致，``tests/test_navigation.py`` 有护栏）。
CRAFT_HOME_PAGE = "craft_home"


class CraftPage(Enum):
    """证据层能确认的页面。这一层不认图，只消费页面名。"""

    HOME = "制作页（未选部位）"
    SELECTED = "制作页（已选部位）"
    CONFIRM = "制作确认弹窗"
    RESULT = "制作结果页"
    TIDY = "结果页整理态"
    SELL_CONFIRM = "出售确认弹窗"
    EXTRACT_CONFIRM = "萃取确认弹窗"
    UNKNOWN = "未登记页面"


def state_label(state: CraftPage) -> str:
    return state.value


@dataclass(frozen=True)
class CraftPlan:
    """一次运行要做什么：一个讨伐 × 一个部位 × 一种整理方式。"""

    hunt: str = "dragon"
    slot: str = "weapon"
    tidy: str = "none"
    cycles: int = DEFAULT_CYCLES

    def __post_init__(self) -> None:
        if self.hunt not in {key for key, *_ in HUNT_TABS}:
            raise ValueError(f"未知讨伐：{self.hunt}")
        if self.slot not in {key for key, *_ in SLOT_POINTS}:
            raise ValueError(f"未知部位：{self.slot}")
        if self.tidy not in TIDY_MODES:
            raise ValueError(f"未知整理方式：{self.tidy}")
        if self.cycles < 1:
            raise ValueError("轮数至少为 1")

    @property
    def hunt_title(self) -> str:
        for key, name, _alias, _x in HUNT_TABS:
            if key == self.hunt:
                return name
        return ""

    @property
    def slot_title(self) -> str:
        for key, name, _x, _y in SLOT_POINTS:
            if key == self.slot:
                return name
        return ""

    @property
    def total_items(self) -> int:
        return self.cycles * ITEMS_PER_CYCLE


@dataclass(frozen=True)
class Observation:
    """一帧画面能确认的事实。"""

    page: CraftPage
    quantity_is_ten: bool = False


class CraftEquipmentMachine:
    """每帧重判页面的循环决策；业务进度只由 ``commit`` 推进。

    ``mark_issued`` 在动作发出瞬间调用，锁住不可逆动作；``commit`` 只在
    「结果页第一帧」调用，用来推进轮数。两者分开，避免「点被吞掉」被算成做成一炉。
    """

    def __init__(self, plan: CraftPlan) -> None:
        self.plan = plan
        self.completed_cycles = 0
        self.finish_reason = ""
        # 本轮是否已点过确认弹窗的「制作」——只有它为真时，结果页才算「这一炉成了」。
        self._craft_issued = False
        # 开局第一次进对应页面时才点的动作。
        self._hunt_selected = False
        self._slot_selected = False
        # 整理流的三段闩锁。
        self._quick_selected = False
        self._tidy_action_issued = False

    @property
    def total_items(self) -> int:
        return self.completed_cycles * ITEMS_PER_CYCLE

    def _finish(self) -> Optional[str]:
        if self.finish_reason:
            return None
        if self.completed_cycles >= self.plan.cycles:
            self.finish_reason = "finish"
            return None
        return ""

    def next_step(self, obs: Observation) -> Optional[str]:
        """返回动作名；``None`` = 收工；空串 = 这一帧不动手。"""
        if self.finish_reason:
            return None
        page = obs.page
        if page is CraftPage.UNKNOWN:
            return "stop-unknown"
        if page in (CraftPage.RESULT, CraftPage.TIDY) and self._craft_issued:
            self.completed_cycles += 1
            self._craft_issued = False
            self._quick_selected = False
            self._tidy_action_issued = False
        done = self._finish()
        if done is None:
            return None
        if self.completed_cycles >= self.plan.cycles:
            return None

        if page is CraftPage.HOME:
            if not self._hunt_selected:
                return "select-hunt"
            if not self._slot_selected:
                return "select-slot"
            return ""
        if page is CraftPage.SELECTED:
            # 游戏会记住上次选中的部位 ⇒ 进页面时先点一次目标部位（幂等），
            # 否则会按上一次的部位做错。
            if not self._slot_selected:
                return "select-slot"
            if not obs.quantity_is_ten:
                return "set-quantity-10"
            return "open-confirm"
        if page is CraftPage.CONFIRM:
            return "confirm-craft"
        if page is CraftPage.RESULT:
            if self.plan.tidy == "none":
                return "again"
            return "open-tidy"
        if page is CraftPage.TIDY:
            if not self._quick_selected:
                return "quick-select"
            if not self._tidy_action_issued:
                return "sell" if self.plan.tidy == "sell" else "extract"
            return "again-from-tidy"
        if page is CraftPage.SELL_CONFIRM:
            return "confirm-sell"
        if page is CraftPage.EXTRACT_CONFIRM:
            return "confirm-extract"
        return ""

    def mark_issued(self, name: str) -> None:
        """Runner 发出动作后登记：不可逆动作只发一次，停止类立即收工。"""
        if name == "select-hunt":
            self._hunt_selected = True
        elif name == "select-slot":
            self._slot_selected = True
        elif name == "confirm-craft":
            self._craft_issued = True
        elif name == "quick-select":
            self._quick_selected = True
        elif name in ("sell", "extract"):
            self._tidy_action_issued = True
        elif name == "finish":
            self.finish_reason = "finish"
        elif name.startswith("stop-"):
            self.finish_reason = name


# ---- 视觉层：把真机帧变成 Observation，再把动作变成带落点的 RouteAction ----------------

@dataclass(frozen=True)
class CraftEquipmentTemplates:
    home_hint: np.ndarray
    craft_button: np.ndarray
    qty_10_selected: np.ndarray
    confirm_hint: np.ndarray
    confirm_craft_button: np.ndarray
    result_title: np.ndarray
    again_button_plain: np.ndarray
    tidy_button: np.ndarray
    quick_select_button: np.ndarray
    sell_button: np.ndarray
    extract_button: np.ndarray
    again_button_tidy: np.ndarray
    sell_confirm_hint: np.ndarray
    extract_confirm_hint: np.ndarray
    popup_confirm_button: np.ndarray
    extract_confirm_button: np.ndarray
    evidence: object = None
    pc: bool = False


def build_craft_equipment_templates(
    template_root: Path,
) -> CraftEquipmentTemplates:
    """缺一张判据图就直接抛错，绝不带着半套判据上真机。"""
    folder = template_root / "craft_equipment"

    def one(name: str) -> np.ndarray:
        return load_template(str(folder / f"{name}.png"))

    return CraftEquipmentTemplates(
        home_hint=one("home_hint"),
        craft_button=one("craft_button"),
        qty_10_selected=one("qty_10_selected"),
        confirm_hint=one("confirm_hint"),
        confirm_craft_button=one("confirm_craft_button"),
        result_title=one("result_title"),
        again_button_plain=one("again_button_plain"),
        tidy_button=one("tidy_button"),
        quick_select_button=one("quick_select_button"),
        sell_button=one("sell_button"),
        extract_button=one("extract_button"),
        again_button_tidy=one("again_button_tidy"),
        sell_confirm_hint=one("sell_confirm_hint"),
        extract_confirm_hint=one("extract_confirm_hint"),
        popup_confirm_button=one("popup_confirm_button"),
        extract_confirm_button=one("extract_confirm_button"),
        evidence=build_craft_equipment_evidence(folder),
        pc=is_pc(template_root),
    )


# evidence 页面键 -> 决策层页面。顺序即判定顺序（弹窗压暗底页，见 evidence 模块）。
_PAGE_STATES = (
    ("craft_equipment.sell_confirm", CraftPage.SELL_CONFIRM),
    ("craft_equipment.extract_confirm", CraftPage.EXTRACT_CONFIRM),
    ("craft_equipment.confirm", CraftPage.CONFIRM),
    ("craft_equipment.tidy", CraftPage.TIDY),
    ("craft_equipment.result", CraftPage.RESULT),
    ("craft_equipment.selected", CraftPage.SELECTED),
    ("craft_equipment.home", CraftPage.HOME),
)


class CraftEquipmentStateMachine(CraftEquipmentMachine):
    """每帧重判页面的视觉状态机；业务进度只由 ``next_step`` 里的 commit 段推进。"""

    def __init__(
        self,
        templates: CraftEquipmentTemplates | Path,
        *,
        plan: CraftPlan | None = None,
    ) -> None:
        super().__init__(plan or CraftPlan())
        self.templates = (
            build_craft_equipment_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = CraftPage.HOME
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
                f"装备制作画面里找不到锚点 {name}；为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[CraftPage]:
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, page in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return page
        return None

    def observation(self, screen: np.ndarray) -> Observation:
        page = self.observe_page(screen) or CraftPage.UNKNOWN
        if page is not CraftPage.SELECTED:
            return Observation(page)
        return Observation(
            page,
            quantity_is_ten=self._locate(screen, "qty_10_selected") is not None,
        )

    # ---- 动作构造 ----

    def _action(
        self,
        name: str,
        point: tuple[int, int],
        *,
        source_page: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
        reason: str = "",
    ) -> RouteAction:
        return RouteAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    def _by_template(
        self,
        screen: np.ndarray,
        name: str,
        anchor: str,
        *,
        source_page: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
        reason: str = "",
    ) -> RouteAction:
        match = self._required(screen, anchor)
        return self._action(
            name,
            match.center,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason or f"{anchor}@{match.center}",
        )

    # ---- 主循环接口 ----

    def preview(self, screen: np.ndarray):
        """两帧稳定确认的试算入口：算完把业务进度原样还回去。"""
        snapshot = (
            self.state,
            self.completed_cycles,
            self.finish_reason,
            self._craft_issued,
            self._hunt_selected,
            self._slot_selected,
            self._quick_selected,
            self._tidy_action_issued,
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
                self._craft_issued,
                self._hunt_selected,
                self._slot_selected,
                self._quick_selected,
                self._tidy_action_issued,
                self._confirmed_page,
            ) = snapshot

    def next_action(self, screen: np.ndarray) -> Optional[RouteAction]:
        page = self.observe_page(screen)
        if page is None:
            self.state = CraftPage.UNKNOWN
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                "装备制作画面未识别；未登记页面已安全停止并留证，不猜测坐标"
            )
        self.state = page
        self._confirmed_page = page.value

        step = self.next_step(self.observation(screen))
        if step is None:
            return None
        if step == "":
            raise UnrecognizedScreen(
                f"装备制作在「{page.value}」没有可执行的动作；已安全停止并留证"
            )
        if step.startswith("stop-"):
            self.mark_issued(step)
            raise UnrecognizedScreen(
                f"装备制作已安全停止：「{page.value}」不在本路线的处理范围内"
            )

        plan = self.plan
        if step == "select-hunt":
            self.mark_issued(step)
            x = next(x for key, _n, _a, x in HUNT_TABS if key == plan.hunt)
            return self._action(
                step,
                (x, HUNT_TAB_Y),
                source_page=page.value,
                in_page_evidence=f"顶部第 {_hunt_index(plan.hunt)} 个讨伐变高亮",
                reason=f"选「{plan.hunt_title}」讨伐（顶部 {_hunt_index(plan.hunt)}/5）",
            )
        if step == "select-slot":
            self.mark_issued(step)
            x, y = next(
                (x, y) for key, _n, x, y in SLOT_POINTS if key == plan.slot
            )
            return self._action(
                step,
                (x, y),
                source_page=page.value,
                target_pages=(CraftPage.SELECTED.value,),
                reason=f"选「{plan.slot_title}」；选中后右侧出现制作次数与「制作」",
            )
        if step == "set-quantity-10":
            return self._action(
                step,
                QTY_10_POINT,
                source_page=page.value,
                in_page_evidence="「制作次数」的白底从 1 移到 10，材料数字变为 10 件量",
                reason="档位不是 10，先点「10」再制作",
            )
        if step == "open-confirm":
            return self._by_template(
                screen,
                step,
                "craft_button",
                source_page=page.value,
                target_pages=(CraftPage.CONFIRM.value,),
                reason="点右下绿色「制作」，进入次数确认弹窗",
            )
        if step == "confirm-craft":
            self.mark_issued(step)
            return self._by_template(
                screen,
                step,
                "confirm_craft_button",
                source_page=page.value,
                target_pages=(CraftPage.RESULT.value,),
                reason="确认弹窗点「制作」，本轮开始消耗材料",
            )
        if step == "open-tidy":
            return self._by_template(
                screen,
                step,
                "tidy_button",
                source_page=page.value,
                target_pages=(CraftPage.TIDY.value,),
                reason="点结果页右侧「整理」，底部换成整理工具栏",
            )
        if step == "quick-select":
            self.mark_issued(step)
            return self._by_template(
                screen,
                step,
                "quick_select_button",
                source_page=page.value,
                in_page_evidence="装备被批量勾选，「已选择N个」不再为 0，出售/萃取变亮",
                reason="点「快速选择」按游戏内预设勾选待处理装备",
            )
        if step == "sell":
            self.mark_issued(step)
            return self._by_template(
                screen,
                step,
                "sell_button",
                source_page=page.value,
                target_pages=(CraftPage.SELL_CONFIRM.value,),
                reason="点「出售」，进入出售确认弹窗",
            )
        if step == "extract":
            self.mark_issued(step)
            return self._by_template(
                screen,
                step,
                "extract_button",
                source_page=page.value,
                target_pages=(CraftPage.EXTRACT_CONFIRM.value,),
                reason="点「萃取」，进入萃取确认弹窗",
            )
        if step == "confirm-sell":
            return self._by_template(
                screen,
                step,
                "popup_confirm_button",
                source_page=page.value,
                target_pages=(CraftPage.TIDY.value,),
                reason="出售确认弹窗点「确认」，装备不可恢复",
            )
        if step == "confirm-extract":
            return self._by_template(
                screen,
                step,
                "extract_confirm_button",
                source_page=page.value,
                target_pages=(CraftPage.TIDY.value,),
                reason="萃取确认弹窗点「萃取」，装备不可恢复",
            )
        if step == "again":
            return self._by_template(
                screen,
                step,
                "again_button_plain",
                source_page=page.value,
                target_pages=(CraftPage.CONFIRM.value,),
                reason="结果页点「重新制作」，直接弹回次数确认",
            )
        if step == "again-from-tidy":
            return self._by_template(
                screen,
                step,
                "again_button_tidy",
                source_page=page.value,
                target_pages=(CraftPage.CONFIRM.value,),
                reason="整理完成后点「重新制作」，直接弹回次数确认",
            )
        raise UnrecognizedScreen(f"装备制作遇到未登记的动作 {step}；已安全停止")


def _hunt_index(key: str) -> int:
    for index, (name, *_rest) in enumerate(HUNT_TABS, start=1):
        if name == key:
            return index
    return 0


def detect_resume_point(
    machine: "CraftEquipmentStateMachine",
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """开局接力：只接制作页上的两种静态状态。

    确认弹窗、结果页与出售/萃取弹窗都紧邻不可逆动作（或是它们的产物），
    刻意不接力 —— 与企鹅批量购买「数量弹窗不接力」同源。
    """
    return observe_page_probe(
        machine,
        screen,
        resumable=frozenset({CraftPage.HOME, CraftPage.SELECTED}),
        label=state_label,
        entry_page=CraftPage.HOME,
        entry="",
    )


class CraftEquipmentRunner(ModeRunnerBase):
    """装备制作 Runner。主循环协议见 ``ModeRunnerBase``。"""

    _MODE_LABEL = "装备制作"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {page: 60 for page in CraftPage}
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 这些动作点完一两秒就能看出生效，不给 60 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset(
        {
            "select-hunt",
            "select-slot",
            "set-quantity-10",
            "open-confirm",
            "open-tidy",
            "quick-select",
            "sell",
            "extract",
            "confirm-sell",
            "confirm-extract",
            "again",
            "again-from-tidy",
        }
    )
    _SHORT_RETRY_SECONDS = 10.0

    def __init__(
        self,
        machine: "CraftEquipmentStateMachine",
        runtime,
        *,
        plan: CraftPlan | None = None,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate=None,
    ) -> None:
        # 选项由 ``modes._craft_equipment_runner_options`` 注入；没给就用默认计划。
        if plan is not None:
            machine.plan = plan
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )

    def run(self, max_cycles: Optional[int] = None) -> int:
        """界面次数框是唯一的轮数上限，开跑前同步给状态机。

        与企鹅批量购买 2026-11-15 的事故同源：次数填 20、状态机按默认 10 轮收工，
        主循环还在等 20 轮 ⇒ 停在结果页干等 60 秒后报状态超时。
        """
        if max_cycles is not None:
            self.machine.plan = replace(self.machine.plan, cycles=max_cycles)
        return super().run(max_cycles=max_cycles)

    def route_note(self) -> str:
        if self.runtime.dry_run or self.machine.completed_cycles < 1:
            return ""
        plan = self.machine.plan
        tidy = {"none": "不整理", "sell": "出售", "extract": "萃取"}[plan.tidy]
        return (
            f"已制作 {self.machine.total_items} 件{plan.hunt_title}·{plan.slot_title}，"
            f"共 {self.machine.completed_cycles} 轮，整理方式={tidy}"
        )

    def _state_label(self, state: CraftPage) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} "
            f"件数={self.machine.total_items}"
        )
