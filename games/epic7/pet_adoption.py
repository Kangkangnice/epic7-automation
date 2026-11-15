# -*- coding: utf-8 -*-
"""宠物领养（每日一次免费领养 + 宠物商店用品可选购入）。

## 业务闭环（用户 2026-11-15 口述，本机实机逐页走查确认）

```
大厅 → 右上角蓝四格 → 快捷菜单第 2 行中间「宠物小屋」
宠物小屋
  ├ 底部绿色「领养」 → 领养宠物弹窗
  │    ├ 有「免费」标记 → 点免费领养 → 弹出领养结果（宠物）→ 点掉 → 回小屋
  │    └ 左按钮是券图标 + 数量（今日免费已用完）→ 点「点击关闭」→ 回小屋
  └ 左下蓝色「宠物商店」 → 商店
       ├ 上半部：宠物领养券（金币 / 天空石购入）→ 一律不买
       └ 滑到底：一般饲料（一周 3 次）、宠物玩具（一周 1 次）×2
            ├ 默认：都不买
            └ 可选项开启时：灰态 / 「N小时后可购买」的行跳过，亮态才买
一轮 = 领养段走完 + 商店段走完，收工回大厅。
```

## ⚠️ 免费领养与「领养券」的分界（用户反复强调）

领养弹窗左边那颗按钮**两态长得很像**，但语义完全相反：

* 免费态：按钮写「免费」，不花任何资源，每天一次 —— 这是路线要点的。
* 付费态：按钮上是紫色券图标 + 数量，点下去会**消耗宠物领养券**。

今天采集时用户当天已领过，画面停在付费态，所以免费态的模板尚未采到。
按项目「判据不许静默降级」的口径，本路线**不靠「没找到付费态」反推免费态**：

* 认出付费态（券图标命中）→ 明确记「今日免费已用完」，关弹窗走商店。
* 认不出付费态 → 视为陌生页，**安全停止并留证**，绝不点任何领养按钮。

明天补一张免费态模板后，在 ``_at_adopt_popup`` 加一个正向分支即可，
现有「付费态」判据一行都不用改。这是刻意留的缺口，不是降级。

同理，商店三件用品的「亮态可购买」今天也没采到（本周额度已用完，三行全灰）。
两个购入选项默认关闭；开启后若看到亮态，同样安全停止留证，不猜坐标、不盲点。

## 判据为什么这么设计

* 页面判据用**固定文字标题 + 底部控件**，不用会变的背景（小屋背景每人不同）。
* 领养弹窗是半透明遮罩，底下小屋标题仍能匹配 0.9996 ⇒ 弹窗优先判定。
* 「点击关闭」是全游戏通用控件，跨页同形分数可到 0.9971 ⇒ 只在已确认
  领养弹窗页才用它定位，不拿它判页。
* 商店滑到底的判据是「一般饲料」那行固定文字出现，不是滑动次数。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``）

| 动作 | 来源页 | 出口验收 |
|---|---|---|
| ``open-adopt`` | 宠物小屋 | ``target_pages`` = 领养弹窗 |
| ``close-adopt`` | 领养弹窗 | ``target_pages`` = 宠物小屋 |
| ``dismiss-result`` | 领养结果 | ``target_pages`` = 宠物小屋 |
| ``open-shop`` | 宠物小屋 | ``target_pages`` = 宠物商店 |
| ``scroll-shop`` | 宠物商店 | ``in_page_evidence`` = 三件宠物用品进入视口 |
| ``buy-supply`` | 宠物商店 | ``in_page_evidence`` = 该行转为已购入 / 次数减一 |

``close-adopt`` 用 ``target_pages`` 而不是 ``in_page_evidence``：弹窗关掉是
一个可靠的换页证据。若某次点击没生效，弹窗不消失，主循环会用同一坐标重试
（最多 4 次）后响亮失败，不会悄悄跳到商店。

## 业务流程必须落成代码动作

用户口述「关闭宠物弹窗回到小屋 → 点左下宠物商店 → 往下滑到底」是流程，
不是建议。所以即使两个购入选项默认关闭，路线也照样进商店、滑到底、
确认三件用品状态，再收工 —— 不因为「今天不买」就跳过整段。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, load_template, locate_with_fallback
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.pet_adoption import (
    COOLDOWN_ROW_COUNT,
    REFERENCE_SIZE,
    build_pet_adoption_evidence,
    cooldown_rows,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint, observe_page_probe
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.template_paths import is_pc, is_template_root
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class PetAdoptionState(Enum):
    HOUSE = "house"
    ADOPT_POPUP = "adopt_popup"
    SHOP = "shop"
    FINISHED = "finished"


STATE_LABELS = {
    PetAdoptionState.HOUSE: "宠物小屋",
    PetAdoptionState.ADOPT_POPUP: "领养宠物",
    PetAdoptionState.SHOP: "宠物商店",
    PetAdoptionState.FINISHED: "本轮已结束",
}

# 导航链终点页（= Epic7Navigator.observe().name，见 navigation.py）。
PET_HOUSE_PAGE = "pet_house"

# evidence 页面键 -> 状态。弹窗必须排在小屋前面（半透明遮罩，见模块 docstring）。
_PAGE_STATES = (
    ("pet_adoption.adopt_popup", PetAdoptionState.ADOPT_POPUP),
    ("pet_adoption.shop_bottom", PetAdoptionState.SHOP),
    ("pet_adoption.shop_top", PetAdoptionState.SHOP),
    ("pet_adoption.house", PetAdoptionState.HOUSE),
)

# 开局接力可落脚的页面。终态 FINISHED 不是画面，不在名单里。
_RESUMABLE_STATES = frozenset(
    {PetAdoptionState.HOUSE, PetAdoptionState.ADOPT_POPUP, PetAdoptionState.SHOP}
)

# 商店下滑手势（实机验证：一次 500px 就能从上半部滑到底）。
SHOP_SCROLL_START = (1400, 900)
SHOP_SCROLL_END = (1400, 400)
SHOP_SCROLL_DURATION_MS = 600
MAX_SHOP_SCROLLS = 3


@dataclass(frozen=True)
class PetAdoptionAction(RouteAction):
    """动作字段与全局契约一致，只额外带一句给人看的判断依据。"""

    reason: str = ""


@dataclass(frozen=True)
class PetAdoptionTemplates:
    house_title: np.ndarray
    house_adopt_button: np.ndarray
    house_shop_button: np.ndarray
    adopt_modal_title: np.ndarray
    paid_ticket_icon: np.ndarray
    adopt_modal_close: np.ndarray
    shop_title: np.ndarray
    shop_supplies_section: np.ndarray
    shop_cooldown: np.ndarray
    evidence: object = None
    pc: bool = False


def build_pet_adoption_templates(template_root: Path) -> PetAdoptionTemplates:
    """缺一张判据图就直接抛错，绝不带着半套判据上真机。"""
    folder = template_root / "pet_adoption"

    def one(name: str) -> np.ndarray:
        return load_template(str(folder / f"{name}.png"))

    return PetAdoptionTemplates(
        house_title=one("house_title"),
        house_adopt_button=one("house_adopt_button"),
        house_shop_button=one("house_shop_button"),
        adopt_modal_title=one("adopt_modal_title"),
        paid_ticket_icon=one("paid_ticket_icon"),
        adopt_modal_close=one("adopt_modal_close"),
        shop_title=one("shop_title"),
        shop_supplies_section=one("shop_supplies_section"),
        shop_cooldown=one("shop_cooldown"),
        evidence=build_pet_adoption_evidence(folder),
        pc=is_pc(template_root),
    )


def state_label(state: PetAdoptionState) -> str:
    return STATE_LABELS.get(state, state.value)


class PetAdoptionStateMachine:
    """纯视觉决策：给一帧，回答「下一步点哪里」或「已经做完了」。

    每帧都从画面重新判页面；业务进度（领养段 / 商店段是否处理过、
    滑了几次）单独记，并在 ``preview`` 里原样还原，避免主循环两帧稳定确认
    把一次点击记成两次。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    def __init__(
        self,
        templates: PetAdoptionTemplates | Path,
        *,
        initial_state: PetAdoptionState = PetAdoptionState.HOUSE,
        buy_food: bool = False,
        buy_toys: bool = False,
    ) -> None:
        self.templates = (
            build_pet_adoption_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        self.buy_food = buy_food
        self.buy_toys = buy_toys
        self.completed_cycles = 0
        self.finish_reason = ""
        self.adopt_checked = False
        self.shop_scrolls = 0
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
                f"宠物领养画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[PetAdoptionState]:
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    def _at_shop_bottom(self, screen: np.ndarray) -> bool:
        return self._locate(screen, "shop_supplies_section") is not None

    def _cooldowns(self, screen: np.ndarray) -> list[Match]:
        return cooldown_rows(
            screen,
            self.templates.shop_cooldown,
            reference_size=self._REFERENCE_SIZE,
        )

    # ---- 动作构造 ----

    def _action(
        self,
        name: str,
        *,
        point: tuple[int, int],
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
    ) -> PetAdoptionAction:
        return PetAdoptionAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    # ---- 各页决策 ----

    def _at_house(self, screen: np.ndarray):
        if not self.adopt_checked:
            button = self._required(screen, "house_adopt_button")
            return self._action(
                "open-adopt",
                point=button.center,
                source_page=state_label(PetAdoptionState.HOUSE),
                target_pages=(state_label(PetAdoptionState.ADOPT_POPUP),),
                reason=f"宠物小屋底部绿色「领养」@{button.center}，进去确认今日免费额度",
            )
        shop = self._required(screen, "house_shop_button")
        return self._action(
            "open-shop",
            point=shop.center,
            source_page=state_label(PetAdoptionState.HOUSE),
            target_pages=(state_label(PetAdoptionState.SHOP),),
            reason=f"左下蓝色「宠物商店」@{shop.center}，检查三件宠物用品",
        )

    def _at_adopt_popup(self, screen: np.ndarray):
        paid = self._locate(screen, "paid_ticket_icon")
        if paid is None:
            # 免费态模板尚未采集。绝不靠「没看见券图标」反推可领 —— 那颗按钮
            # 在付费态就是要花券的。安全停止并留证，等补图后加正向分支。
            raise UnrecognizedScreen(
                "领养弹窗里既没认出「免费」标记、也没认出付费券图标；"
                "免费领养判据尚未登记，为避免消耗宠物领养券已安全停止"
            )
        close = self._required(screen, "adopt_modal_close")
        self.adopt_checked = True
        return self._action(
            "close-adopt",
            point=close.center,
            source_page=state_label(PetAdoptionState.ADOPT_POPUP),
            target_pages=(state_label(PetAdoptionState.HOUSE),),
            reason=(
                f"左按钮是付费券领养@{paid.center}，今日免费额度已用完；"
                f"只点底部「点击关闭」@{close.center}，不碰任何领养按钮"
            ),
        )

    def _at_shop(self, screen: np.ndarray):
        if not self._at_shop_bottom(screen):
            if self.shop_scrolls >= MAX_SHOP_SCROLLS:
                raise UnrecognizedScreen(
                    f"宠物商店下滑 {self.shop_scrolls} 次后仍未看到三件宠物用品，"
                    "为避免对未知位置操作已安全停止"
                )
            self.shop_scrolls += 1
            return self._action(
                "scroll-shop",
                # 空点：落在商店左下的说明文字上，不压任何「购买」按钮。
                point=(700, 1030),
                source_page=state_label(PetAdoptionState.SHOP),
                in_page_evidence="列表整体上移，三件宠物用品进入视口",
                reason=(
                    f"上半部是宠物领养券，一律不买；下滑第 "
                    f"{self.shop_scrolls}/{MAX_SHOP_SCROLLS} 次去看底部用品"
                ),
            )

        cooldowns = self._cooldowns(screen)
        all_grey = len(cooldowns) >= COOLDOWN_ROW_COUNT
        wanted = []
        if self.buy_food:
            wanted.append("一般饲料")
        if self.buy_toys:
            wanted.append("宠物玩具")
        if wanted and not all_grey:
            # 亮态「可购买」判据尚未采集：不猜、不点，留证等补图。
            raise UnrecognizedScreen(
                f"已开启购入（{'、'.join(wanted)}），但宠物用品出现可购买状态 "
                f"（认出 {len(cooldowns)}/{COOLDOWN_ROW_COUNT} 行冷却）；"
                "亮态购买判据尚未登记，为避免误购已安全停止"
            )
        self._finish(self._shop_done_reason(cooldowns, wanted))
        return None

    @staticmethod
    def _shop_done_reason(cooldowns: list[Match], wanted: list[str]) -> str:
        if not wanted:
            tail = "饲料与玩具购入均未开启，本轮只确认状态、不购买"
        else:
            tail = f"{'、'.join(wanted)}本轮无可购买项"
        return (
            f"三件宠物用品中 {len(cooldowns)}/{COOLDOWN_ROW_COUNT} 行在冷却或本周已购入，"
            + tail
        )

    def _finish(self, reason: str) -> None:
        """收工：轮次 +1，主循环据此在 max_cycles 满足时收工。

        ⚠️ 这里**不加「本轮已收工」的永久锁**：主循环每帧先调 ``preview``
        做两帧稳定确认（它会把进度原样还原），一轮循环只会真正提交一次，
        所以不会重复计数。加了锁反而会让 ``--max-cycles 2`` 的第二轮
        等不到轮次递增、干等到状态超时（2026-11-15 实跑复现）。
        """
        self.state = PetAdoptionState.FINISHED
        self.completed_cycles += 1
        self.finish_reason = reason

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[PetAdoptionAction]:
        page = self.observe_page(screen)
        if page is None:
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                f"宠物领养画面[{state_label(self.state)}]未识别；"
                "未登记页面已安全停止并留证，不猜测坐标"
            )
        self.state = page
        self._confirmed_page = state_label(page)
        handler = {
            PetAdoptionState.HOUSE: self._at_house,
            PetAdoptionState.ADOPT_POPUP: self._at_adopt_popup,
            PetAdoptionState.SHOP: self._at_shop,
        }[page]
        return handler(screen)

    def preview(self, screen: np.ndarray):
        """两帧稳定确认的试算入口：算完把业务进度原样还回去。"""
        snapshot = (
            self.state,
            self.completed_cycles,
            self.finish_reason,
            self.adopt_checked,
            self.shop_scrolls,
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
                self.adopt_checked,
                self.shop_scrolls,
                self._confirmed_page,
            ) = snapshot


def state_label_of(state: PetAdoptionState) -> str:
    return state_label(state)


def detect_resume_point(
    machine: "PetAdoptionStateMachine",
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """开局接力：停在宠物小屋 / 领养弹窗 / 宠物商店都能就地接管。

    判据与运行期同源（直接调状态机自己的 ``observe_page``），不另定阈值。
    本状态机每帧重判页面，拨状态下一帧就被覆盖，所以 ``state`` 恒为 None。
    """
    return observe_page_probe(
        machine,
        screen,
        resumable=_RESUMABLE_STATES,
        label=state_label,
        entry_page=PetAdoptionState.HOUSE,
        entry=PET_HOUSE_PAGE,
    )


class PetAdoptionRunner(ModeRunnerBase):
    """宠物领养 Runner。主循环协议见 ``ModeRunnerBase``。"""

    _MODE_LABEL = "宠物领养"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        PetAdoptionState.HOUSE: 45,
        PetAdoptionState.ADOPT_POPUP: 45,
        PetAdoptionState.SHOP: 60,
        PetAdoptionState.FINISHED: 45,
    }
    # 这条路线不打架。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 这几个动作点完一两秒就能看出生效，不给 45 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset({"open-adopt", "close-adopt", "open-shop", "scroll-shop"})
    _SHORT_RETRY_SECONDS = 8.0

    def __init__(
        self,
        machine: PetAdoptionStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        buy_food: bool = False,
        buy_toys: bool = False,
    ) -> None:
        # 两个购入开关默认关闭，与「上线前不买任何商店用品」的口径一致。
        # 与 labyrinth_stone 同一套注入方式：选项装到 Runner、由它写进状态机。
        machine.buy_food = buy_food
        machine.buy_toys = buy_toys
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )

    def route_note(self) -> str:
        if self.runtime.dry_run or self.machine.completed_cycles < 1:
            return ""
        return self.machine.finish_reason or "宠物领养与商店用品均已处理"

    def _state_label(self, state: PetAdoptionState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _after_action_click(self, action: PetAdoptionAction) -> None:
        """``scroll-shop`` 的点击是空点，真正的下滑手势在这里补发。

        主循环的动作通道只有点击；状态机里做滑动会被 ``preview`` 每帧重放。
        """
        if action.name == "scroll-shop":
            self.runtime.swipe(
                SHOP_SCROLL_START,
                SHOP_SCROLL_END,
                SHOP_SCROLL_DURATION_MS,
                "pet-shop-scroll",
            )

    def _log_cycle_completed(self) -> None:
        reason = getattr(self.machine, "finish_reason", "")
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} 结论={reason or '已走完出口'}"
        )
