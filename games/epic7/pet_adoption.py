# -*- coding: utf-8 -*-
"""宠物领养（每日一次免费领养 + 宠物商店用品可选购入）。

## 业务闭环（用户 2026-11-15 口述，本机实机逐页走查确认）

```
大厅 → 右上角蓝四格 → 快捷菜单第 2 行中间「宠物小屋」
宠物小屋
  ├ 底部绿色「领养」 → 领养宠物弹窗
  │    ├ 「免费」二字 + 「可免费领养！」→ 点免费领养 → 领养结果 → 点掉 → 回弹窗
  │    │      → 弹窗此时已变成券态 → 「点击关闭」→ 回小屋
  │    └ 只剩券图标 + 数量（今日免费已用完）→ 点「点击关闭」→ 回小屋
  └ 左下蓝色「宠物商店」 → 商店
       ├ 上半部：宠物领养券（金币 / 天空石购入）→ 一律不买
       └ 滑到底：一般饲料（一周 3 次）、宠物玩具（一周 1 次）×2
            ├ 默认：都不买
            └ 可选项开启时：灰态 / 「N小时后可购买」或「N天后可购买」的行跳过，亮态才买
一轮 = 领养段走完 + 商店段走完，收工回大厅。
```

## ⚠️ 免费领养与「领养券」的分界（用户反复强调）

领养弹窗左边那颗按钮**两态长得很像**，但语义完全相反：

* 免费态：按钮写「免费」，不花任何资源，每天一次 —— 这是路线要点的。
* 付费态：按钮上是紫色券图标 + 数量，点下去会**消耗宠物领养券**。

**⚠️ 券图标不是「已领完」的证据**（2026-11-16 更正）。两态左按钮上都有那张紫色券：

* 付费态：`[券] 1 领养` —— 券 + 数量。
* 免费态：`[券] 免费 领养`，按钮上方还有绿色气泡「1/1可免费领养！」。

2026-11-15 首版拿券图标当「今日已用完」的正向证据，11-16 免费额度刷新当天就把
免费窗口判成已用完、**白丢一次领养**。现在的三条判据（`_at_adopt_popup`）：

* 「免费」二字 **且** 「可免费领养！」提示条同时命中 → 点免费领养（不花任何资源）；
* 两条都不命中、只剩券图标 → 今日已领完，只点「点击关闭」；
* 其余组合 → 证据矛盾，**安全停止留证**，一个领养按钮都不点。

两条免费证据的余量（2026-11-16 全库审计）：「免费」二字在免费帧 1.0000、付费帧
0.6490；「可免费领养！」提示条 1.0000、全库其它帧最高 0.5912。所以**要求两条同时成立**，
单条掉下去只会变成"安全停止"，不会误点付费按钮。

关掉结果弹窗露出的是**下面的领养弹窗**（不是小屋）：结果页是盖在弹窗上的第二层，
`dismiss-result` 的出口因此写「领养宠物」，再由它走 `close-adopt` 回小屋。

同理，商店三件用品的「亮态可购买」到 2026-11-15 还没采到（本周额度已用完，
三行全灰）。2026-11-16 早晨额度刷新后已补采，见下面「亮态购入」。

## 亮态购入（2026-11-16 采集后接线）

点某一行「购买」会先弹「购买商品」确认框（物品名 + 剩余次数 + 数量滑杆 +
取消/购买两颗按钮）。所以购入是**两步**：``open-purchase`` 开框，
``confirm-purchase`` 点框里的绿「购买」。三条硬规矩：

* **商品名定位，不用「购买」二字**：上面两行宠物领养券也有「购买」，
  拿它定位会误点到 500 天空石的礼包。
* **一行一单、一类一轮最多一件**：饲料一周 3 次、玩具一周 1 次，买完那一行
  仍是亮态，不设上限就会在同一行反复回购，把一周额度一口气花光。
* **确认框只认自己发起的那一单**：``pending_buy`` 为空时出现确认框，
  说明是上次中断留下的，两颗按钮都不点，安全停止留证。

判定「这一行能不能买」不用 OCR 读 ``N/N``：同一行里**没有**冷却文字
就是亮态（灰态那行必然带「后可购买」，实测 1.000/0.995/0.956）。
⚠️ 冷却文案有两态：日刷新「N小时后可购买」、周额度用尽「N天后可购买」；
模板只裁共有的「后可购买」四字，一张覆盖两态（2026-11-19 实跑定稿）。

## 判据为什么这么设计

* 页面判据用**固定文字标题 + 底部控件**，不用会变的背景（小屋背景每人不同）。
* 领养弹窗是半透明遮罩，底下小屋标题仍能匹配 0.9996 ⇒ 弹窗优先判定。
* 「点击关闭」是全游戏通用控件，跨页同形分数可到 0.9971 ⇒ 只在已确认
  领养弹窗页才用它定位，不拿它判页。
* 商店滑到底的判据是「一般饲料」那行固定文字出现，不是滑动次数。
* 购买确认框是**全游戏通用**的（企鹅批量购买同一个）⇒ 页面组合加一条
  「底页还得是宠物商店」（遮罩下商店标题 0.9998，别的路线底页不是商店）。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``）

| 动作 | 来源页 | 出口验收 |
|---|---|---|
| ``open-adopt`` | 宠物小屋 | ``target_pages`` = 领养弹窗 |
| ``adopt-free`` | 领养弹窗 | ``target_pages`` = 领养结果 |
| ``close-adopt`` | 领养弹窗 | ``target_pages`` = 宠物小屋 |
| ``dismiss-result`` | 领养结果 | ``target_pages`` = 领养弹窗 |
| ``open-shop`` | 宠物小屋 | ``target_pages`` = 宠物商店 |
| ``scroll-shop`` | 宠物商店 | ``in_page_evidence`` = 三件宠物用品进入视口 |
| ``open-purchase`` | 宠物商店 | ``target_pages`` = 购买确认 |
| ``confirm-purchase`` | 购买确认 | ``target_pages`` = 宠物商店 |

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

from auto_game_unified.core.matcher import (
    Match,
    find_all_templates,
    load_template,
    locate_with_fallback,
)
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
    ADOPT_RESULT = "adopt_result"
    SHOP = "shop"
    PURCHASE = "purchase"
    FINISHED = "finished"


STATE_LABELS = {
    PetAdoptionState.HOUSE: "宠物小屋",
    PetAdoptionState.ADOPT_POPUP: "领养宠物",
    PetAdoptionState.ADOPT_RESULT: "领养结果",
    PetAdoptionState.SHOP: "宠物商店",
    PetAdoptionState.PURCHASE: "购买确认",
    PetAdoptionState.FINISHED: "本轮已结束",
}

# 导航链终点页（= Epic7Navigator.observe().name，见 navigation.py）。
PET_HOUSE_PAGE = "pet_house"

# evidence 页面键 -> 状态。弹窗必须排在小屋前面（半透明遮罩，见模块 docstring）。
_PAGE_STATES = (
    ("pet_adoption.adopt_result", PetAdoptionState.ADOPT_RESULT),
    ("pet_adoption.purchase", PetAdoptionState.PURCHASE),
    ("pet_adoption.adopt_popup", PetAdoptionState.ADOPT_POPUP),
    ("pet_adoption.shop_bottom", PetAdoptionState.SHOP),
    ("pet_adoption.shop_top", PetAdoptionState.SHOP),
    ("pet_adoption.house", PetAdoptionState.HOUSE),
)

# 开局接力可落脚的页面。终态 FINISHED 不是画面，不在名单里。
_RESUMABLE_STATES = frozenset(
    {
        PetAdoptionState.HOUSE,
        PetAdoptionState.ADOPT_POPUP,
        # 结果弹窗只点「点击关闭」，不花钱 ⇒ 接力过去是安全的，还能省掉重进小屋。
        PetAdoptionState.ADOPT_RESULT,
        PetAdoptionState.SHOP,
    }
)

# 商店下滑手势（实机验证：一次 500px 就能从上半部滑到底）。
SHOP_SCROLL_START = (1400, 900)
SHOP_SCROLL_END = (1400, 400)
SHOP_SCROLL_DURATION_MS = 600
MAX_SHOP_SCROLLS = 3

# 商品名中心 -> 该行绿色「购买」按钮的偏移（2026-11-16 亮态帧实测三行）：
# (1115,587)->(1647,627)、(1119,804)->(1647,844)、(1114,1022)->(1647,1062)，
# 三行一致的 (531, 40)，纵向抖动 ±1。
SHOP_BUY_DX = 531
SHOP_BUY_DY = 40
# 同一行「名字」与冷却文字「后可购买」的纵向容差：行距 217，取 90 既不会跨行，
# 也容得下滚动落点差几十像素。
SHOP_ROW_TOLERANCE = 90


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
    free_adopt_text: np.ndarray
    free_adopt_hint: np.ndarray
    adopt_result_title: np.ndarray
    shop_title: np.ndarray
    shop_supplies_section: np.ndarray
    shop_cooldown: np.ndarray
    supply_food_name: np.ndarray
    supply_toy_name: np.ndarray
    confirm_title: np.ndarray
    confirm_question: np.ndarray
    confirm_buy: np.ndarray
    # 2026-11-23 弹窗改版的第二长相；由证据层的 alt_template_paths 声明，
    # 这里只负责把图装上，判页/取坐标仍走同一个 `_locate`。
    confirm_title_v2: np.ndarray
    confirm_question_v2: np.ndarray
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
        free_adopt_text=one("free_adopt_text"),
        free_adopt_hint=one("free_adopt_hint"),
        adopt_result_title=one("adopt_result_title"),
        shop_title=one("shop_title"),
        shop_supplies_section=one("shop_supplies_section"),
        shop_cooldown=one("shop_cooldown"),
        supply_food_name=one("supply_food_name"),
        supply_toy_name=one("supply_toy_name"),
        # 购买确认框从 2026-11-17 实跑诊断帧自采：原先借企鹅那条路线的数量弹窗图，
        # 分数只有 0.27 / 0.00 ⇒ 认不出，卡到超时。按钮模板只裁「购买」二字，
        # 不含会变的金额 500 / 3 / 1000。
        confirm_title=one("confirm_title"),
        confirm_question=one("confirm_question"),
        confirm_buy=one("confirm_buy"),
        confirm_title_v2=one("confirm_title_v2"),
        confirm_question_v2=one("confirm_question_v2"),
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
        # 本轮已经买过的**行**：``(品类键, 商品名中心 y)``。为什么要记到行：
        # 饲料一周 3 次，买一次只是 3/3 → 2/3，那一行**仍然是亮态**，
        # 不按行记账就会在同一行上反复回购，把一周额度一口气花光；
        # 玩具一周 1 次，买完那一行自己会变灰，另一行照常买 —— 所以上限落在「行」上，
        # 不落在「品类」上（宠物玩具有两行，两种都要买）。
        self.bought_rows: list[tuple[str, int]] = []
        # 点了某行「购买」之后记下``(品类, 行 y)``。确认框那一帧靠它回答
        # 「这一单是不是本路线自己发起的」—— 不是我发起的就绝不动那颗绿按钮。
        self.pending_buy: Optional[tuple[str, int]] = None
        self._confirmed_page = ""

    # ---- 视觉判据 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)

        def probe(template: np.ndarray) -> Optional[Match]:
            return locate_with_fallback(
                name,
                screen,
                template,
                atom.threshold,
                region=atom.region,
                reference_size=atom.reference_size,
                mode=atom.match_mode,
            )

        match = probe(getattr(self.templates, name))
        if match is not None:
            return match
        # 同一控件的第二长相（2026-11-23 弹窗改版）：声明在证据层、图装在模板层。
        # 原样先走，没过阈才补候选 ⇒ 老帧判定逐字节不变；候选名取不到就当场炸，
        # 不许静默降级成「认不出」。
        for relative in atom.alt_template_paths:
            candidate = probe(getattr(self.templates, Path(relative).stem))
            if candidate is not None:
                return candidate
        return None

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
        """领养弹窗：**免费优先**，认不准就停。

        ⚠️ 券图标两态都有（付费态是「券 + 数字」，免费态是「券 + 免费」），
        所以它只能证明"这是个领养弹窗"，**不能证明"今日已领完"**。
        2026-11-15 版拿券图标当"已用完"的正向证据，2026-11-16 免费额度刷新当天
        就把免费窗口判成了已用完、白丢一次领养 —— 判据已按下面三条重写：

        * 「免费」二字 + 「可免费领养！」提示条**同时命中** ⇒ 点免费领养；
        * 两条都不命中、券图标命中 ⇒ 今日已领完，只点「点击关闭」；
        * 其余组合（只中一条 / 一条都不中）⇒ 证据互相矛盾，安全停止留证。
        """

        free_text = self._locate(screen, "free_adopt_text")
        free_hint = self._locate(screen, "free_adopt_hint")
        paid = self._locate(screen, "paid_ticket_icon")

        if free_text is not None and free_hint is not None:
            self.adopt_checked = True
            return self._action(
                "adopt-free",
                point=free_text.center,
                source_page=state_label(PetAdoptionState.ADOPT_POPUP),
                target_pages=(state_label(PetAdoptionState.ADOPT_RESULT),),
                reason=(
                    f"左按钮写「免费」@{free_text.center}、上方有「可免费领养！」"
                    f"@{free_hint.center} ⇒ 点免费领养，不消耗任何券"
                ),
            )
        if free_text is None and free_hint is None and paid is not None:
            close = self._required(screen, "adopt_modal_close")
            self.adopt_checked = True
            return self._action(
                "close-adopt",
                point=close.center,
                source_page=state_label(PetAdoptionState.ADOPT_POPUP),
                target_pages=(state_label(PetAdoptionState.HOUSE),),
                reason=(
                    f"免费标记与免费提示都没出现、只剩付费券@{paid.center}，"
                    f"今日免费额度已用完；只点底部「点击关闭」@{close.center}"
                ),
            )
        raise UnrecognizedScreen(
            "领养弹窗的三条证据对不上（免费二字 / 可免费领养提示 / 付费券图标）："
            f"免费={free_text is not None}、提示={free_hint is not None}、"
            f"券={paid is not None}；为避免消耗宠物领养券已安全停止"
        )

    def _at_adopt_result(self, screen: np.ndarray):
        """领养结果弹窗：只点底部「点击关闭」。

        ⚠️ 右下那颗「再领养一次 · 1」会**消耗 1 张宠物领养券**，绝不当成"继续"。
        """

        close = self._required(screen, "adopt_modal_close")
        return self._action(
            "dismiss-result",
            point=close.center,
            source_page=state_label(PetAdoptionState.ADOPT_RESULT),
            # ⚠️ 关掉结果弹窗露出的是**下面的领养弹窗**，不是小屋（2026-11-16 08:24
            # 实跑实测：期望小屋、实际停在「领养宠物」，转场超时）。结果页是盖在
            # 领养弹窗上的第二层，所以出口写「领养宠物」，再由它走 close-adopt 回小屋。
            target_pages=(state_label(PetAdoptionState.ADOPT_POPUP),),
            reason=(
                f"领养结果已出，点底部「点击关闭」@{close.center} 回到领养弹窗；"
                "右下「再领养一次」要花券，不碰"
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
        wanted = self._wanted_items()
        pick = self._pick_bright_item(screen, cooldowns, wanted)
        if pick is not None:
            key, label, row_y, point = pick
            self.pending_buy = (key, row_y)
            return self._action(
                "open-purchase",
                point=point,
                source_page=state_label(PetAdoptionState.SHOP),
                target_pages=(state_label(PetAdoptionState.PURCHASE),),
                reason=(
                    f"「{label}」这一行可购买（{len(cooldowns)}/{COOLDOWN_ROW_COUNT} 行在冷却），"
                    f"点该行的「购买」@ {point}"
                ),
            )
        self._finish(self._shop_done_reason(cooldowns, wanted))
        return None

    def _wanted_items(self) -> list[tuple[str, str, str]]:
        """这一轮想买的品类：``(品类键, 中文名, 名字锚点)``。两个开关默认都关。"""

        wanted: list[tuple[str, str, str]] = []
        if self.buy_food:
            wanted.append(("food", "一般饲料", "supply_food_name"))
        if self.buy_toys:
            wanted.append(("toys", "宠物玩具", "supply_toy_name"))
        return wanted

    def _pick_bright_item(
        self,
        screen: np.ndarray,
        cooldowns: list[Match],
        wanted: list[tuple[str, str, str]],
    ) -> Optional[tuple[str, str, int, tuple[int, int]]]:
        """挑一行「可购买」的用品，返回 ``(品类键, 中文名, 名字中心 y, 点击点)``。

        三条判据缺一不可：

        1. **商品名先命中** —— 上面两行领养券也有「购买」，只有商品名能把
           用品行与券行分开（误点就是 500 天空石）。
        2. 这一行**没有**「后可购买」冷却文字（日刷新「N小时后」/ 周用尽「N天后」
           两态共用）—— 冷却文字与名字同一行（±90 px）。
        3. 算出来的按钮落点**必须在画布内** —— 越界点击在窗口层是致命错误。
        """

        height, width = screen.shape[:2]
        for key, label, atom in wanted:
            evidence = self.templates.evidence.atom(atom)
            for name_match in find_all_templates(
                screen,
                getattr(self.templates, atom),
                evidence.threshold,
                region=evidence.region,
                reference_size=self._REFERENCE_SIZE,
                min_gap=SHOP_ROW_TOLERANCE,
            ):
                if any(
                    abs(name_match.center[1] - row.center[1]) < SHOP_ROW_TOLERANCE
                    for row in cooldowns
                ):
                    continue
                if any(
                    kind == key
                    and abs(name_match.center[1] - bought_y) < SHOP_ROW_TOLERANCE
                    for kind, bought_y in self.bought_rows
                ):
                    continue
                point = (
                    name_match.center[0] + SHOP_BUY_DX,
                    name_match.center[1] + SHOP_BUY_DY,
                )
                if not (0 <= point[0] < width and 0 <= point[1] < height):
                    continue
                return key, label, name_match.center[1], point
        return None

    def _at_purchase(self, screen: np.ndarray):
        """购买确认框：先确认这一单是自己发起的，再点右下绿色「购买」。"""

        if self.pending_buy is None:
            raise UnrecognizedScreen(
                "屏幕上出现了「购买商品」确认框，但本轮并没有发起购买"
                "（多半是上次中断留下的）；确认与取消都不点，安全停止留证"
            )
        buy = self._required(screen, "confirm_buy")
        key, row_y = self.pending_buy
        label = "一般饲料" if key == "food" else "宠物玩具"
        self.bought_rows.append((key, row_y))
        self.pending_buy = None
        return self._action(
            "confirm-purchase",
            point=buy.center,
            source_page=state_label(PetAdoptionState.PURCHASE),
            target_pages=(state_label(PetAdoptionState.SHOP),),
            reason=f"确认框里点绿色「购买」@ {buy.center}，购入「{label}」1 件",
        )

    def _shop_done_reason(
        self, cooldowns: list[Match], wanted: list[tuple[str, str, str]]
    ) -> str:
        if self.bought_rows:
            food = sum(1 for key, _y in self.bought_rows if key == "food")
            toys = sum(1 for key, _y in self.bought_rows if key == "toys")
            parts = []
            if food:
                parts.append(f"一般饲料 {food} 件")
            if toys:
                parts.append(f"宠物玩具 {toys} 件")
            tail = f"本轮已购入 {'、'.join(parts)}（同一行一轮只买一次）"
        elif not wanted:
            tail = "饲料与玩具购入均未开启，本轮只确认状态、不购买"
        else:
            tail = f"{'、'.join(label for _key, label, _atom in wanted)}本轮无可购买项"
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
            PetAdoptionState.ADOPT_RESULT: self._at_adopt_result,
            PetAdoptionState.SHOP: self._at_shop,
            PetAdoptionState.PURCHASE: self._at_purchase,
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
            # ⚠️ ``bought_rows`` 必须**拷一份**再还原：试算里那句 ``append`` 会改到
            # 同一个 list 上，不拷贝就等于试算把"已购买"提前记上，真跑时反而不买了。
            list(self.bought_rows),
            self.pending_buy,
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
                self.bought_rows,
                self.pending_buy,
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
        PetAdoptionState.ADOPT_RESULT: 45,
        PetAdoptionState.SHOP: 60,
        PetAdoptionState.PURCHASE: 45,
        PetAdoptionState.FINISHED: 45,
    }
    # 这条路线不打架。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 这几个动作点完一两秒就能看出生效，不给 45 秒白等。
    _SHORT_RETRY_ACTIONS = frozenset(
        {
            "open-adopt",
            "adopt-free",
            "dismiss-result",
            "close-adopt",
            "open-shop",
            "scroll-shop",
            "open-purchase",
            "confirm-purchase",
        }
    )
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
