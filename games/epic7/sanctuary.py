"""圣域「收菜」一次性路线（每天跑一次）。

## 业务闭环（用户 2026-09-29 口述，实机走查确认）

```
大厅
  └ 左侧竖排菜单最上面那个「圣域」入口（在「光辉里程碑」上方）
圣域主页（右侧三行：精灵之森 / 欧勒毕斯之心 / 炼金术师之塔）
  └ 本轮只做最上面那一行「精灵之森」
精灵之森（三行材料：企鹅巢穴 / 精灵之泉 / 魔罗戈拉种植地）
  ├ 可领的行：蓝底白边在闪、左上角红点、中间「领取奖励」
  │     → 点一下 ⇒ 弹出「…成长完成!」弹窗 ⇒ 点弹窗底部「点击关闭」
  │     → 回到本页，该行变成倒计时
  └ 三行都没有「领取奖励」了 ⇒ 本轮收工 ⇒ 回家
```

用户原话：「每天这个圣域里面会定时刷新一些材料，然后我们需要定时去把它给点掉……
你去收菜就很简单把它点掉。」「目前的话只有部分刷新的，我们先把部分的这些流程给走通。」

## 判据与阈值

**唯一判据 = 「领取奖励」四个字命中**（为什么不用红点 / 闪烁 → 见
``evidence/sanctuary.py`` 的模块 docstring，那里有实测数字与取舍理由）。
阈值 0.80：正例最低 0.9744、负例最高 0.5498 ⇒ 双向余量 0.17 / 0.25，
**不是「一次失败就降阈值」调出来的**。

## ⚠️ 弹窗不会自己消失（与用户口述不符，实测为准）

用户说「点完之后它就是一个很小的弹窗，**也不需要你点**」。实测：等了 6 秒，
整幅平均亮度仍是 20.0（与刚弹出时一模一样），弹窗底部明写「点击关闭」+ 一个 ▼。
⇒ 路线必须自己点掉它（``dismiss-claim``），不能等。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``）

每个动作都声明「从哪来 + 到哪去 / 页内验收依据」。逐条对账表：

| 动作 | source_page | 出口验收 |
|---|---|---|
| ``open-forest`` | 圣域主页 | ``target_pages`` = 精灵之森 |
| ``claim-row`` | 精灵之森 | ``target_pages`` = 领取完成弹窗 |
| ``dismiss-claim`` | 领取完成弹窗 | ``target_pages`` = 精灵之森 |

⚠️ **``claim-row`` 用 ``target_pages`` 而不是 ``in_page_evidence``**，是刻意的：
弹窗**确实会弹**（两次实点都弹了，且不会自动消失）⇒ 「弹窗出现」是一个可靠的
出口证据；而 ``runner_base`` 的账本要求「目标页出现」才算这次动作完成，
**这正是我们想要的**：万一某次点击没生效，「领取完成弹窗」不出现，
主循环会在 8 秒后用**同一个坐标**再点一次（最多 4 次），然后**响亮地失败**
（留诊断 + 退出码 1），而不是悄悄跳到下一行 —— 参考 ``labyrinth_stone`` 的教训：
「没看见某个东西」永远不能当放弃的理由，但「点了 4 次都没生效」是**看得见的事实**，
就该报错。

## ⚠️ 这一轮**不做**的东西（写在这里，别装作不存在）

- **只做「精灵之森」这一行**。圣域主页另外两行（欧勒毕斯之心 / 炼金术师之塔）
  本轮完全不碰 —— 它们的页面长什么样我一次都没采过。后续要么各开一条路线，
  要么把本路线扩成「三行依次进」。
- **不读金额 / 数量**。领到几个材料不解析（与骑士团捐赠的取舍一致：用户当场拍板
  「先不读金额」），只在日志里写「点掉了哪一行」。
- **不点「照料(1/3)」**（魔罗戈拉种植地那一行的按钮）。它可能是要花资源的操作，
  没有正例说明它安全；本轮连它在哪里都不依靠。
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, NamedTuple, Optional

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.sanctuary import (
    REFERENCE_SIZE,
    build_sanctuary_evidence,
    claim_row_label,
    claimable_rows,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.template_paths import is_template_root
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class SanctuaryState(Enum):
    HOME = "home"
    FOREST = "forest"
    CLAIM_POPUP = "claim_popup"
    FINISHED = "finished"


# 日志用画面名（``source_page`` / ``target_pages`` 全部从它派生）。
STATE_LABELS = {
    SanctuaryState.HOME: "圣域主页",
    SanctuaryState.FOREST: "精灵之森",
    SanctuaryState.CLAIM_POPUP: "领取完成弹窗",
    SanctuaryState.FINISHED: "本轮已结束",
}

# evidence 页面键 -> 状态。判定顺序就是这个元组的顺序（**弹窗优先**）。
#
# ⚠️ 弹窗必须排在 forest 之前：它盖在精灵之森页上、只把底页压暗，
# 而实测 ``forest_title`` 在弹窗下仍然 0.9998（≥0.80）⇒ 顺序反了会把弹窗那一帧
# 判成精灵之森页，于是状态机对着一页盖着弹窗的画面去点「领取奖励」。
# 判据本体与实测见 ``evidence/sanctuary.py`` 的模块 docstring。
_PAGE_STATES = (
    ("sanctuary.claim_popup", SanctuaryState.CLAIM_POPUP),
    ("sanctuary.forest", SanctuaryState.FOREST),
    ("sanctuary.home", SanctuaryState.HOME),
)

# 圣域主页在**导航链**上的页面名（= ``Epic7Navigator.observe().name``）。
# 站在这一页说明已经在圣域里了，只差「点精灵之森」一步 —— 从这里接着导航
# 能省掉「回大厅 → 再进圣域」那一趟。
SANCTUARY_HOME_PAGE = "sanctuary_home"

# 开局接力能落脚的页面。
#
# ``claim_popup``（领取完成弹窗）**刻意不接力**，理由不是危险、而是没必要：
# 它的动作只有「点一下『点击关闭』」这一个，而人在那一页上开局时，
# 探针返回 None 走的是老流程（一路返回 → 回大厅 → 重新导航），
# 一路上的 ESC 本来就会先把这个弹窗关掉 —— 效果一样，不必为它单开一个落点。
# （这条与 ``knights_donation`` 对弹窗的取舍同源，但那边是因为弹窗**不可逆**。）
_RESUMABLE_STATES = (
    SanctuaryState.HOME,
    SanctuaryState.FOREST,
)


@dataclass(frozen=True)
class SanctuaryAction:
    """一个动作，**必须声明出处与出口验收**（新路线准入，见模块 docstring 对账表）。

    ``target_pages``（换页动作）与 ``in_page_evidence``（同页动作）**至少填一个**，
    两个都空会被 ``ModeRunnerBase._require_transition_contract`` 直接拒发。
    """

    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    in_page_evidence: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SanctuaryTemplates:
    # 圣域主页右侧第一行「精灵之森」：页面判据 + 点击目标（身兼两职）。
    forest_row: np.ndarray
    # 精灵之森页左上标题。
    forest_title: np.ndarray
    # 「领取奖励」四个字（三行共用一张模板，靠区域分别命中）。
    claim_text: np.ndarray
    # 领取完成弹窗底部「点击关闭」。
    popup_close: np.ndarray
    evidence: object = None


def build_sanctuary_templates(template_dir: Path) -> SanctuaryTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return SanctuaryTemplates(
        forest_row=load("forest_row"),
        forest_title=load("forest_title"),
        claim_text=load("claim_text"),
        popup_close=load("popup_close"),
        evidence=build_sanctuary_evidence(template_dir),
    )


def state_label(state: SanctuaryState) -> str:
    return STATE_LABELS.get(state, state.value)


class SanctuaryStateMachine:
    """圣域收菜一轮的纯视觉决策。

    **每一帧都从画面重新判页面**（判据是纯锚点组合，不依赖上下文），
    所以状态不会「拨错之后卡到超时」—— 唯一的业务进度是 ``completed_cycles``
    与 ``finish_reason``。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    def __init__(
        self,
        templates: SanctuaryTemplates | Path,
        *,
        initial_state: SanctuaryState = SanctuaryState.HOME,
    ) -> None:
        self.templates = (
            build_sanctuary_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        # 收工理由（写进运行日志的「结论=」）。
        self.finish_reason = ""
        # 本帧看到的可领行数（只为了日志里说清楚「还剩几行」）。
        self.claimable_count = 0
        self._confirmed_page = ""

    # ---- 视觉判据 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        return find_template(
            screen,
            getattr(self.templates, name),
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        """拿不到就失败关闭：**绝不猜坐标**。"""
        match = self._locate(screen, name)
        if match is None:
            raise UnrecognizedScreen(
                f"圣域收菜画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[SanctuaryState]:
        """按 evidence 页面组合认出当前是哪一页；认不出返回 None。

        判定顺序即 ``_PAGE_STATES``（弹窗在前，理由见那里的注释）。
        """
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    def _claimable(self, screen: np.ndarray) -> list[Match]:
        return claimable_rows(
            screen,
            self.templates.claim_text,
            reference_size=self._REFERENCE_SIZE,
        )

    # ---- 动作构造 ----

    def _confirm_page(self, page: str) -> None:
        """登记「视觉确认我现在站在哪一页」，供主循环对账转场契约。

        ⚠️ **只在 ``next_action`` 开头、按 ``observe_page`` 的结果写**，
        不在动作构造里写。区别在「本帧没有动作」的分支上（精灵之森已经没得领了
        → 直接收工）：那种分支不会构造动作，靠它来写就会让页面标识**停在上一页**，
        主循环于是认为「上一个转场没成功」、把同一个动作再点一遍。
        """
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        *,
        point: tuple[int, int],
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
    ) -> SanctuaryAction:
        return SanctuaryAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    # ---- 各页决策 ----

    def _at_home(self, screen: np.ndarray):
        row = self._required(screen, "forest_row")
        return self._action(
            "open-forest",
            point=row.center,
            source_page=state_label(SanctuaryState.HOME),
            target_pages=(state_label(SanctuaryState.FOREST),),
            reason=f"圣域主页右侧第一行「精灵之森」（@{row.center}）",
        )

    def _at_forest(self, screen: np.ndarray):
        rows = self._claimable(screen)
        self.claimable_count = len(rows)
        if not rows:
            self._finish("精灵之森里已经没有「领取奖励」了（三行都在倒计时）")
            return None
        # ⚠️ 从上到下取第一行（``claimable_rows`` 已按 y 排序）：凭分数挑会在
        # 两行之间来回跳 —— 实测两行的分数只差 0.001~0.01 且帧间会互相反超。
        target = rows[0]
        others = "、".join(claim_row_label(m.center[1]) for m in rows[1:]) or "无"
        return self._action(
            "claim-row",
            point=target.center,
            source_page=state_label(SanctuaryState.FOREST),
            target_pages=(state_label(SanctuaryState.CLAIM_POPUP),),
            reason=(
                f"可领 {len(rows)} 行，先点最上面那行（{claim_row_label(target.center[1])}"
                f"@{target.center} 得分 {target.score:.4f}）；其余待领={others}"
            ),
        )

    def _at_claim_popup(self, screen: np.ndarray):
        close = self._required(screen, "popup_close")
        return self._action(
            "dismiss-claim",
            point=close.center,
            source_page=state_label(SanctuaryState.CLAIM_POPUP),
            target_pages=(state_label(SanctuaryState.FOREST),),
            reason=(
                f"领取完成弹窗底部的「点击关闭」@{close.center}"
                "（弹窗标题与物品图标每次都不一样，只有这四个字与 ▼ 是固定的）"
            ),
        )

    def _finish(self, reason: str) -> None:
        """一轮走完：轮次 +1，主循环据此在 ``max_cycles`` 满足时收工。"""
        self.state = SanctuaryState.FINISHED
        self.completed_cycles += 1
        self.finish_reason = reason

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[SanctuaryAction]:
        page = self.observe_page(screen)
        if page is None:
            # 认不出就不点：把「已确认页面」作废，免得主循环拿过期页面去对账转场契约。
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                f"圣域收菜画面[{state_label(self.state)}]未识别"
            )
        self.state = page
        self._confirm_page(state_label(page))
        handler = {
            SanctuaryState.HOME: self._at_home,
            SanctuaryState.FOREST: self._at_forest,
            SanctuaryState.CLAIM_POPUP: self._at_claim_popup,
        }[page]
        return handler(screen)

    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        ``next_action`` 会推进 ``completed_cycles`` / ``finish_reason``，
        主循环每帧都会先调 preview 做两帧稳定确认，不还原就会把「一次点击」
        记成两次、甚至把「收工」提前一帧宣布。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self.finish_reason,
            self.claimable_count,
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
                self.claimable_count,
                self._confirmed_page,
            ) = snapshot


class SanctuaryRunner(ModeRunnerBase):
    """圣域收菜一次性 Runner（主循环协议见 ``ModeRunnerBase``）。

    ⚠️ 打开 ``_REQUIRE_TRANSITION_CONTRACT``：每个动作都必须在发出前通过
    「source_page + 出口验收」的机器校验（含空跑）。

    ## 刻意**不**覆写 ``_on_action_exhausted``

    骑士团捐赠那张「跳过表」（``support-one`` 推不动 ⇒ 换去做每周任务）是**它特有**的：
    那边存在「今日支援上限已满」这种**合理**的点不动，放弃这一节还有别的事可做。
    圣域这边没有这种情形 ——「领取奖励」四个字在画面上清清楚楚，点 4 次推不动就是
    真出了问题，没有「换一件该干的事」可言。

    所以这里保持基类默认（返回 ``False``），让 ``runner_base`` 那套机器照常跑：

    1. 给**一次**「换个办法」的机会（``_self_heal_used``）—— 主循环原地重新决策一次。
       对这条路线这是有用的：万一第一下点击其实生效了、只是那一帧没看清，
       重新决策会看到弹窗并转成 ``dismiss-claim``，属于正常纠偏；
    2. 还是同一个动作 ⇒ 留诊断 + ``RuntimeError`` ⇒ **退出码 1 + 失败通知**。

    ⚠️ 这里曾经写成「自己留诊断、``return True``」，那是**错的**：``True`` 的语义是
    「已优雅收尾」，主循环会 ``_close_out()`` 然后正常返回 ⇒ 退出码 **0**、通知写
    「已完成」—— 用户看到「任务完成」而实际上一个材料都没领到。**「响亮地失败」
    要说出来，就不能走优雅收尾那条路。**
    """

    _MODE_LABEL = "圣域收菜"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        SanctuaryState.HOME: 45,
        SanctuaryState.FOREST: 60,
        SanctuaryState.CLAIM_POPUP: 45,
        SanctuaryState.FINISHED: 45,
    }
    # 这条路线不打架，没有「已承诺战斗」环节。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 动作重试窗口：默认 45 秒是给「换页」定的，而这两个动作点完**立刻**能看出
    # 生效没有（弹窗弹出来 / 弹窗关掉）。用 45 秒纯属白等 —— 正是 world_boss 记过的
    # 「领奖干等 40 多秒」那一类。8 秒 = 实机一次点击到弹窗出现（约 1 秒）的 8 倍余量。
    _SHORT_RETRY_ACTIONS = frozenset({"claim-row", "dismiss-claim"})
    _SHORT_RETRY_SECONDS = 8.0

    def __init__(
        self,
        machine: SanctuaryStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )

    def _state_label(self, state: SanctuaryState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _log_cycle_completed(self) -> None:
        reason = getattr(self.machine, "finish_reason", "")
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} 结论={reason or '已走完出口'}"
        )

    def _decision_hint(self, action_name: str, state: SanctuaryState) -> str:
        if action_name == "claim-row":
            return f"本帧还有 {getattr(self.machine, 'claimable_count', 0)} 行可领"
        return ""


# ---- 开局接力 ----
# 契约与三道卡点见 docs/TRANSITION_CONTRACTS.md「接力契约」那一节。


class SanctuaryResumePoint(NamedTuple):
    """圣域收菜开局接力的落点（``modes.ResumePoint`` 的路线本地版）。"""

    page: str                       # 中文页面名，给日志和诊断看
    state: Optional[str] = None     # 恒为 None：本路线每帧重判页面，不需要拨状态
    entry: Optional[str] = None     # 非空 = 已经在导航链的某一级上，从这里接着导航


def detect_resume_point(
    machine: "SanctuaryStateMachine",
    screen: np.ndarray,
) -> Optional[SanctuaryResumePoint]:
    """圣域收菜开局接力：认出人停在哪一页就就地接管。

    **判据与运行期同源** —— 直接调状态机自己的 ``observe_page``，不另定一套阈值、
    不加新锚点。本路线的页面识别是**纯锚点**（不依赖状态机上下文），所以开局
    只有一帧也判得出来。

    **不拨状态**（``state`` 恒为 None，照 ``shop_refresh`` / ``knights_donation``
    的做法）：本状态机**每一帧都从画面重判页面**，拨了下一帧就被覆盖，
    留着只会制造「日志说拨到了 A、实际画面是 B」的假象。

    落在**圣域主页**时额外给 ``entry``：那一页在导航链上（大厅 → 圣域主页），
    从这里接着导航能省掉一次「进圣域」的点击。

    ⚠️ 人停在**大厅**上时返回 None（``forest_row`` 在大厅上不成立，实测 0.2411）
    ⇒ 照旧走「回大厅 → 进圣域」，与接力挂上之前的行为完全一致。
    """
    page = machine.observe_page(screen)
    if page is None:
        return None
    if page is SanctuaryState.HOME:
        return SanctuaryResumePoint(
            page=state_label(page),
            entry=SANCTUARY_HOME_PAGE,
        )
    if page in _RESUMABLE_STATES:
        return SanctuaryResumePoint(page=state_label(page))
    return None
