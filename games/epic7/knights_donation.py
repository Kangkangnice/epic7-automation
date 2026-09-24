"""骑士团「捐赠」一次性路线（每天跑一次）。

## 业务闭环（用户 2026-09-24 口述，实机走查确认）

```
骑士团主页
  └ 左侧「骑士团活动」图标 → **直接点进去**（有没有红点都进）
骑士团活动（左栏三个页签：资源支援 / 团员商店 / 每周任务 —— **只做 1 和 3**）
  ├ 资源支援页
  │   ├ 右上「请求支援」→ 弹窗选「下级精灵之花」→ 底部「请求支援」 （**每天只能请求一次**）
  │   └ 列表里每行右侧的绿色「支援1个」依次点完：
  │       ├ 有的行直接弹「获得奖励（30，今日支援上限 x/200）」→ 关掉再找下一行
  │       └ 有的行**先**弹「支援资源 / 确定要支援以下的资源吗?」确认框 → 点它里面的「支援1个」
  └ 每周任务页
      ├ 骑士团点数进度条上可领的档位（图标左上角带亮点）
      └ 每行右侧的绿色「领取」
```

## ⚠️ 「这一行到底支援成功没有」只能靠**有没有弹获得奖励**判断（2026-09-24 实跑发现）

实跑第一次就卡在这里：点列表里的「支援1个」之后不是马上支援，**先弹了一个确认框**
（我采图那天没遇到，所以第一版不认识它、整条路线中止）。更关键的是第二次实测：
团员要的材料我**持有 0** 时，确认框里点「支援1个」**毫无变化** —— 行不消失、
「今日支援上限」也不涨（对照实验：换成持有充足的那一行，点完立刻弹「获得奖励」、
上限从 30/200 变成 60/200，该行按钮变成灰勾）。

所以判据不能是「点过了就算支援了」，只能是「**有没有看到获得奖励弹窗**」：

- 挑行时记下按钮中心 y 到 ``pending_support_y``；
- 看到「获得奖励」⇒ 作数，清空待结算；
- **回到列表页而没看到奖励** ⇒ 这一行吃不下，把它的 y 记进 ``skipped_rows``，
  下一轮挑**别的**绿按钮；
- ⚠️ 跳过表的键是**绝对 y**，只在「列表没动过」时有效：支援成功（列表重排）与
  下滑（整列位移）都会让旧 y 指到别人头上 ⇒ 这两种情况一发生就**清空**跳过表。

没有这一步的话，`find_best_template` 每轮都会挑回同一个按钮，在那行上白转 4 次
然后整条路线中止 —— 永远轮不到下面那个真的能支援的人。所以挑行用的是
``find_all_templates``（整列找**所有**绿按钮）而不是只找最高分那个。

## ⚠️ 两个「不能按固定坐标点」的实测事实

1. **支援列表每支援一次就重排**（2026-09-24 实测：``Lo3w`` 被支援后从第 2 行掉到
   第 3 行，``广东瀚鹏`` 升上来）。所以「支援1个」按钮**每轮都要重新认**，
   点击点取模板匹配的中心，不查表。
2. **每周任务的行会随完成情况增删**（领完一行之后它从列表消失、下面补一行上来），
   「领取」按钮同理每轮重新认。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``，本路线是第一条开的）

新路线准入要求每个动作都声明「从哪来 + 到哪去 / 页内验收依据」。逐条对账表：

| 动作 | source_page | 出口验收 |
|---|---|---|
| ``open-activity`` | 骑士团主页 | ``target_pages`` = 资源支援 / 每周任务 / 活动界面兜底（**三个都是合法落点**） |
| ``open-resource-tab`` | 活动界面兜底 | ``target_pages`` = 资源支援 |
| ``request-support`` | 资源支援 | ``target_pages`` = 请求支援弹窗 |
| ``select-flower`` | 请求支援弹窗 | ``in_page_evidence`` = 该格出现金色选中框（``flower_cell_selected`` 命中） |
| ``confirm-request`` | 请求支援弹窗 | ``target_pages`` = 资源支援 / 获得奖励弹窗 |
| ``support-one`` | 资源支援 | ``target_pages`` = 支援资源确认框 / 获得奖励弹窗（**两种落点都真实存在**） |
| ``confirm-support`` | 支援资源确认框 | ``target_pages`` = 获得奖励弹窗（生效）/ 资源支援（**没生效**，由跳过表接手） |
| ``scroll-support`` | 资源支援 | ``in_page_evidence`` = 列表整体上移（按钮行的 y 变小 / 出现新行） |
| ``open-weekly-tab`` | 资源支援 | ``target_pages`` = 每周任务 |
| ``dismiss-reward`` | 获得奖励弹窗 | ``target_pages`` = 资源支援 / 每周任务（取决于从哪来） |
| ``claim-milestone`` | 每周任务 | ``in_page_evidence`` = 该档位角标消失（图标变绿勾） |
| ``claim-task`` | 每周任务 | ``target_pages`` = 获得奖励弹窗 |

⚠️ **``in_page_evidence`` 是真验收、不是装饰**：本状态机**每帧都从画面重新判**，
例：``select-flower`` 的下一帧如果还看到「未选中」的花格子，就说明这一下没生效，
状态机仍会返回 ``select-flower``（按短窗口重试）；看到选中态才返回 ``confirm-request``。
``claim-milestone`` 同理：角标还在就再点，角标没了才往下走。

### 为什么不写 ``target_pages=(本页,)``

``runner_base._transition_completed`` 只要求「已确认页面 ∈ target_pages」。
把本页写进去 ⇒ 点完永远验收通过 ⇒ 分不出「点了没生效」和「点了生效了」。
所以同页动作（``select-flower`` / ``scroll-support`` / ``claim-milestone``）
一律走 ``in_page_evidence``，靠「下一帧画面变了没有」验收。

## ⚠️ 这一条路线**只有负样本是全的**

本路线只用**一处**角标判据：每周任务页那两颗蓝角标（``points_label`` 可领档位 +
「每周任务」页签，正向样本 ``weekly_tasks_claimable.png``）。
骑士团主页那颗橙红角标**不参与任何决策** —— 用户 2026-09-24 更正：有没有红点都要进去
（原先按红点决定进不进，已拿掉）。``guild_home_with_dot.png`` 仍然留着，用途变成
``activity_entry`` 余量最薄的回归依据（红点盖住图标左上角 ⇒ 0.9259）。

**没跑过「支援到 200 点上限」**那一路 —— 用户描述到上限时会浮出一行「已经到了资源上限」
的字。本模块**不依赖**那行字：上限一旦到达，列表里的绿色按钮会自己变灰（同一玩家一天
只能支援一次），状态机找不到绿按钮就自然收尾。
**换客户端（PC）或换分辨率时，角标判据必须重采正向样本**。
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import (
    Match,
    find_all_templates,
    find_template,
    load_template,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.knights_donation import (
    REFERENCE_SIZE,
    build_knights_donation_evidence,
    find_dot,
    milestone_claim_point,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class KnightsDonationState(Enum):
    GUILD_HOME = "guild_home"
    ACTIVITY_PANEL = "activity_panel"
    RESOURCE_SUPPORT = "resource_support"
    REQUEST_POPUP = "request_popup"
    SUPPORT_CONFIRM = "support_confirm"
    REWARD_POPUP = "reward_popup"
    WEEKLY_TASKS = "weekly_tasks"
    FINISHED = "finished"


# 日志用画面名
STATE_LABELS = {
    KnightsDonationState.GUILD_HOME: "骑士团主页",
    KnightsDonationState.ACTIVITY_PANEL: "骑士团活动（页签未识别）",
    KnightsDonationState.RESOURCE_SUPPORT: "骑士团活动·资源支援",
    KnightsDonationState.REQUEST_POPUP: "请求支援弹窗",
    KnightsDonationState.SUPPORT_CONFIRM: "支援资源确认框",
    KnightsDonationState.REWARD_POPUP: "获得奖励弹窗",
    KnightsDonationState.WEEKLY_TASKS: "骑士团活动·每周任务",
    KnightsDonationState.FINISHED: "本轮已结束",
}

# evidence 页面键 -> 状态。判定顺序就是这个元组的顺序（弹窗优先）。
_PAGE_STATES = (
    ("knights_donation.reward_popup", KnightsDonationState.REWARD_POPUP),
    ("knights_donation.request_popup", KnightsDonationState.REQUEST_POPUP),
    # 确认框盖在资源支援列表上 ⇒ 必须排在 resource_support 之前，否则会被当成列表页。
    ("knights_donation.support_confirm", KnightsDonationState.SUPPORT_CONFIRM),
    ("knights_donation.resource_support", KnightsDonationState.RESOURCE_SUPPORT),
    ("knights_donation.weekly_tasks", KnightsDonationState.WEEKLY_TASKS),
    ("knights_donation.activity_panel", KnightsDonationState.ACTIVITY_PANEL),
    ("knights_donation.guild_home", KnightsDonationState.GUILD_HOME),
)

# 支援列表「一屏放不下」时的下滑手势（实机验证过会产生位移）。
SUPPORT_SWIPE_START = (1036, 900)
SUPPORT_SWIPE_END = (1036, 600)
SUPPORT_SWIPE_DURATION_MS = 400
# 下滑次数上限。列表把「还能支援的人」排在前面（实测：被支援过的人会往下沉），
# 所以正常一次都不用滑；留 2 次只为了兜「一屏真的放不下」。
MAX_SUPPORT_SCROLLS = 2

# 每周任务里「可领档位」的点击点已经由 evidence 模块的实测偏移给出，
# 这里只放关闭「获得奖励」弹窗时的纵向偏移（弹窗任意位置都能关，取标题下方一点）。
REWARD_DISMISS_DY = 120

# 支援列表一屏可能有多个「支援1个」：找全部匹配时的非极大值抑制半径。
# 实测行距约 195、按钮自身 266×70 ⇒ 60 既不会把同一按钮报两次，也不会把相邻行并成一个。
SUPPORT_PEAK_MIN_GAP = 60
# 「已经被判定吃不下的行」的纵向匹配容差：新挑到的按钮中心离它这么近就视为同一行。
SUPPORT_ROW_SKIP_TOLERANCE = 40


def state_label(state: KnightsDonationState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class KnightsDonationAction:
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
class KnightsDonationTemplates:
    activity_entry: np.ndarray
    panel_title: np.ndarray
    tab_resource_support: np.ndarray
    tab_weekly_tasks: np.ndarray
    request_support_button: np.ndarray
    support_one_button: np.ndarray
    points_label: np.ndarray
    claim_button: np.ndarray
    popup_title: np.ndarray
    flower_cell: np.ndarray
    flower_cell_selected: np.ndarray
    popup_confirm: np.ndarray
    reward_title: np.ndarray
    support_confirm_title: np.ndarray
    support_confirm_button: np.ndarray
    evidence: object = None


def build_knights_donation_templates(template_dir: Path) -> KnightsDonationTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return KnightsDonationTemplates(
        activity_entry=load("activity_entry"),
        panel_title=load("panel_title"),
        tab_resource_support=load("tab_resource_support"),
        tab_weekly_tasks=load("tab_weekly_tasks"),
        request_support_button=load("request_support_button"),
        support_one_button=load("support_one_button"),
        points_label=load("points_label"),
        claim_button=load("claim_button"),
        popup_title=load("popup_title"),
        flower_cell=load("flower_cell"),
        flower_cell_selected=load("flower_cell_selected"),
        popup_confirm=load("popup_confirm"),
        reward_title=load("reward_title"),
        support_confirm_title=load("support_confirm_title"),
        support_confirm_button=load("support_confirm_button"),
        evidence=build_knights_donation_evidence(template_dir),
    )


class KnightsDonationStateMachine:
    """骑士团捐赠一轮的纯视觉决策。

    与 world_boss 同构：页面识别统一走 ``evidence/knights_donation.py`` 的页面组合，
    状态机不自己写「靠上下文猜这是哪一页」的判据。**每一帧都重新判页面**，
    所以状态不会「拨错之后卡到超时」—— 唯一的例外是 ``_request_done`` /
    ``_support_scrolls`` 两个业务进度标志，它们表达的是「这一次进程里做过什么」，
    画面里看不出来。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    def __init__(
        self,
        templates: KnightsDonationTemplates | Path,
        *,
        initial_state: KnightsDonationState = KnightsDonationState.RESOURCE_SUPPORT,
        backend: str = "emulator",
    ) -> None:
        self.backend = backend
        self.templates = (
            build_knights_donation_templates(templates)
            if isinstance(templates, Path)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        # 「今天这一次请求支援已经发出去了」。每天只能请求一次 ⇒ 同一次运行里只做一次。
        self.request_done = False
        # 支援列表下滑次数账本（每支援成功一次清零）。
        self.support_scrolls = 0
        # ⚠️ 「已经试过、但确认之后毫无变化」的行（记按钮中心的 y）。
        # 实测：团员要的材料我持有 0 时，确认框点完行不会消失、点数也不涨 ⇒
        # 必须记住这一行、下一次挑**别的**绿按钮，否则会一直挑到同一行、
        # 四次之后整条路线中止，永远轮不到下面那个能支援的人。
        # ⚠️ **键是绝对 y、只在「列表没动过」时才有效**：支援成功会重排、下滑会
        # 整体移位 —— 这两种情况一发生，旧的 y 就指到**别人**头上了，必须清空
        # （见 ``_at_reward_popup`` 与 `_at_resource_support` 的第 3 步）。
        self.skipped_rows: set[int] = set()
        # 本轮已经点下去、还在等结果的支援（按钮中心的 y）。它表达的是
        # 「这一下到底生效没有」的待结算状态，画面里看不出来。
        self.pending_support_y: Optional[int] = None
        # 收工理由（写进运行日志的「结论=」，认页面时不出来，只在 _finish 里写）。
        self.finish_reason = ""
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
                f"骑士团捐赠画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[KnightsDonationState]:
        """按 evidence 页面组合认出当前是哪一页；认不出返回 None。

        判定顺序即 ``_PAGE_STATES``（弹窗在前）。互斥性实测表见
        ``evidence/knights_donation.py`` 的模块 docstring。
        """
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    # ---- 动作构造 ----

    def _confirm_page(self, page: str) -> None:
        """登记「视觉确认我现在站在哪一页」，供主循环对账转场契约。

        ⚠️ **只在 ``next_action`` 开头、按 ``observe_page`` 的结果写**，
        不在 ``_action`` 里写。区别在「本帧没有动作」的分支上（例：每周任务
        已经没得领了 → 直接收工）。那种分支不会调用 ``_action``，如果靠
        ``_action`` 来写，页面标识就会**停在上一个动作的来源页**，主循环于是
        认为「上一个转场没成功」，把同一个动作再点一遍。
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
    ) -> KnightsDonationAction:
        return KnightsDonationAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    # ---- 各页决策 ----

    def _at_guild_home(self, screen: np.ndarray):
        # ⚠️ **不看红点**（用户 2026-09-24 更正）：有没有红点都进。
        # 原先这里以「图标有没有红点」决定进不进、没红点就整条路线结束 —— 已拿掉。
        # 于是「今天其实没事可做」这天也会整条走完：请求支援（若当天还没发）、
        # 支援列表找不到人、下滑两轮、切到每周任务发现没得领，然后正常收工。
        entry = self._required(screen, "activity_entry")
        return self._action(
            "open-activity",
            point=entry.center,
            source_page=state_label(KnightsDonationState.GUILD_HOME),
            # 三个落点都是合法的：活动界面上次停在哪一页，这次就还停在哪一页。
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.WEEKLY_TASKS),
                state_label(KnightsDonationState.ACTIVITY_PANEL),
            ),
            reason=f"骑士团主页「骑士团活动」图标（中心={entry.center}），有没有红点都进去",
        )

    def _at_activity_panel(self, screen: np.ndarray):
        tab = self._required(screen, "tab_resource_support")
        return self._action(
            "open-resource-tab",
            point=tab.center,
            source_page=state_label(KnightsDonationState.ACTIVITY_PANEL),
            target_pages=(state_label(KnightsDonationState.RESOURCE_SUPPORT),),
            reason="在骑士团活动界面但页签没认出来，先切到「资源支援」",
        )

    def _support_candidates(self, screen: np.ndarray) -> list[Match]:
        """整列里**所有**绿色「支援1个」按钮，按分数从高到低。

        为什么不能只取最高分那个：一屏可能有多个一模一样的按钮，而业务要逐个点过去。
        """
        atom = self.templates.evidence.atom("support_one_button")
        return find_all_templates(
            screen,
            self.templates.support_one_button,
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
            min_gap=SUPPORT_PEAK_MIN_GAP,
        )

    def _is_skipped(self, y: int) -> bool:
        return any(
            abs(y - skipped) <= SUPPORT_ROW_SKIP_TOLERANCE for skipped in self.skipped_rows
        )

    def _at_resource_support(self, screen: np.ndarray):
        # 0) 先结算上一轮：**回到列表页就说明没等到「获得奖励」** ⇒ 那一下没生效，
        #    把那一行记进跳过表（实测：团员要的材料我持有 0 时，确认框点完毫无变化）。
        #    代价说明：万一那一下是**点击丢了**（不是吃不下），也会被记进跳过表 ⇒
        #    这一次运行会漏掉这个团员。宁可漏一个人，也不要在一行上白转 4 次
        #    让整条路线中止 —— 而误判在一次成功的支援之后就会自动失效（列表重排 ⇒ 清空）。
        if self.pending_support_y is not None:
            self.skipped_rows.add(self.pending_support_y)
            self.pending_support_y = None
        # 1) 每天一次的「请求支援」。同一次运行里只做一次。
        if not self.request_done:
            button = self._locate(screen, "request_support_button")
            if button is not None:
                return self._action(
                    "request-support",
                    point=button.center,
                    source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                    target_pages=(state_label(KnightsDonationState.REQUEST_POPUP),),
                    reason="资源支援页右上角「请求支援」，每天只能发一次",
                )
        # 2) 支援别人。列表会重排，所以每轮都在整列里重新认绿色按钮；
        #    已经判定「吃不下」的行跳过，去点下一个。
        for candidate in self._support_candidates(screen):
            if self._is_skipped(candidate.center[1]):
                continue
            self.pending_support_y = candidate.center[1]
            return self._action(
                "support-one",
                point=candidate.center,
                source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                # 两种落点都合法：有的行直接弹「获得奖励」，有的行先弹确认框。
                target_pages=(
                    state_label(KnightsDonationState.SUPPORT_CONFIRM),
                    state_label(KnightsDonationState.REWARD_POPUP),
                ),
                reason=f"列表里有可支援的成员（绿色按钮@{candidate.center}）",
            )
        # 3) 视口内没有可点的 ⇒ 可能一屏放不下，下滑再看（有界）。
        if self.support_scrolls < MAX_SUPPORT_SCROLLS:
            self.support_scrolls += 1
            # 滑动手势会让整列位移 ⇒ 跳过表里的 y 键失效，必须清空（否则会误跳过
            # 刚滑上来的那几行）。
            self.skipped_rows.clear()
            tab = self._required(screen, "tab_resource_support")
            return self._action(
                "scroll-support",
                # ⚠️ 这个坐标是**空点**：主循环只认「点击」，滑动由 Runner 的
                # `_after_action_click` 补发。点在「当前已选中的资源支援页签」上，
                # 是这一页里唯一一个点下去一定没有副作用的落点。
                point=tab.center,
                source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                in_page_evidence="列表整体上移（按钮行的 y 坐标变小 / 出现此前不可见的新行）",
                reason=f"视口内没有可支援的成员，下滑第 {self.support_scrolls}/{MAX_SUPPORT_SCROLLS} 次",
            )
        # 4) 支援收尾 ⇒ 去做每周任务。
        tab = self._required(screen, "tab_weekly_tasks")
        return self._action(
            "open-weekly-tab",
            point=tab.center,
            source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
            target_pages=(state_label(KnightsDonationState.WEEKLY_TASKS),),
            reason="已经没有可支援的成员了，切到「每周任务」",
        )

    def _at_support_confirm(self, screen: np.ndarray):
        """「支援资源 / 确定要支援以下的资源吗?」确认框：点它里面的「支援1个」。

        ⚠️ 这里**不做「按钮是不是灰的」判断**（没有可靠判据）：确认之后到底生效没有，
        靠**有没有弹「获得奖励」**来结算 —— 没弹就说明这一行吃不下，
        ``_at_resource_support`` 的第 0 步会把它记进跳过表。
        所以 ``target_pages`` 两个落点都写上了，它们都真实存在。
        """
        button = self._required(screen, "support_confirm_button")
        return self._action(
            "confirm-support",
            point=button.center,
            source_page=state_label(KnightsDonationState.SUPPORT_CONFIRM),
            target_pages=(
                state_label(KnightsDonationState.REWARD_POPUP),
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
            ),
            reason="「支援资源」确认框里的「支援1个」，点完才算真的支援",
        )

    def _at_request_popup(self, screen: np.ndarray):
        if self._locate(screen, "flower_cell_selected") is None:
            flower = self._required(screen, "flower_cell")
            return self._action(
                "select-flower",
                point=flower.center,
                source_page=state_label(KnightsDonationState.REQUEST_POPUP),
                in_page_evidence="该格变成金色选中框（flower_cell_selected 由不命中变命中）",
                reason="在弹窗里选「下级精灵之花」（每天固定选它，永远不会缺）",
            )
        confirm = self._required(screen, "popup_confirm")
        self.request_done = True
        return self._action(
            "confirm-request",
            point=confirm.center,
            source_page=state_label(KnightsDonationState.REQUEST_POPUP),
            # 正常关窗回资源支援页；万一游戏顺手弹了「获得奖励」，也算合法落点。
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.REWARD_POPUP),
            ),
            reason="弹窗底部「请求支援」，发出即消耗今天的唯一一次额度",
        )

    def _at_reward_popup(self, screen: np.ndarray):
        title = self._required(screen, "reward_title")
        # 支援链路完成一次 ⇒ 下滑次数账本清零（下一段还能重新往下找）。
        self.support_scrolls = 0
        # 看到「获得奖励」就说明刚才那一下**真的生效了** ⇒ 待结算的支援作数，
        # 不要把它记进跳过表（第 0 步只在「回到列表且没弹奖励」时才会记）。
        self.pending_support_y = None
        # 支持成功 ⇒ 这个团员在列表里变成灰勾、整列**重排**（实测）⇒ 跳过表里
        # 那些按 y 记的键全都指到别人头上了，必须清空，否则会误跳过能支援的人。
        self.skipped_rows.clear()
        return self._action(
            "dismiss-reward",
            point=(title.center[0], title.center[1] + REWARD_DISMISS_DY),
            source_page=state_label(KnightsDonationState.REWARD_POPUP),
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.WEEKLY_TASKS),
            ),
            reason="「获得奖励」弹窗（实机确认点弹窗内任意位置都能关）",
        )

    def _at_weekly_tasks(self, screen: np.ndarray):
        dot = find_dot(screen, "milestone", reference_size=self._REFERENCE_SIZE)
        if dot is not None:
            point = milestone_claim_point(dot)
            return self._action(
                "claim-milestone",
                point=point,
                source_page=state_label(KnightsDonationState.WEEKLY_TASKS),
                in_page_evidence="该档位的角标消失（图标原地变成绿勾，弹窗不出现）",
                reason=f"骑士团点数有可领档位（角标中心={dot}，图标中心={point}）",
            )
        claim = self._locate(screen, "claim_button")
        if claim is not None:
            return self._action(
                "claim-task",
                point=claim.center,
                source_page=state_label(KnightsDonationState.WEEKLY_TASKS),
                target_pages=(state_label(KnightsDonationState.REWARD_POPUP),),
                reason=f"有已完成的每周任务可领（绿色「领取」@{claim.center}）",
            )
        self._finish("每周任务已经没有可领的点数档位和可领的任务了")
        return None

    def _finish(self, reason: str) -> None:
        """一轮走完：轮次 +1，主循环据此在 ``max_cycles`` 满足时收工。"""
        self.state = KnightsDonationState.FINISHED
        self.completed_cycles += 1
        self.finish_reason = reason

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[KnightsDonationAction]:
        page = self.observe_page(screen)
        if page is None:
            # 认不出就不点：把「已确认页面」作废，免得主循环拿过期页面去对账转场契约。
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                f"骑士团捐赠画面[{state_label(self.state)}]未识别"
            )
        self.state = page
        # 「视觉确认我现在站在哪一页」——每帧重写一次（理由见 _confirm_page 的 docstring）。
        self._confirm_page(state_label(page))
        handler = {
            KnightsDonationState.GUILD_HOME: self._at_guild_home,
            KnightsDonationState.ACTIVITY_PANEL: self._at_activity_panel,
            KnightsDonationState.RESOURCE_SUPPORT: self._at_resource_support,
            KnightsDonationState.REQUEST_POPUP: self._at_request_popup,
            KnightsDonationState.SUPPORT_CONFIRM: self._at_support_confirm,
            KnightsDonationState.REWARD_POPUP: self._at_reward_popup,
            KnightsDonationState.WEEKLY_TASKS: self._at_weekly_tasks,
        }[page]
        return handler(screen)

    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        ``next_action`` 会推进 ``request_done`` / ``support_scrolls`` / ``completed_cycles``，
        主循环每帧都会先调 preview 做两帧稳定确认，不还原就会把「一次点击」记成两次。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self.request_done,
            self.support_scrolls,
            self.finish_reason,
            self._confirmed_page,
            set(self.skipped_rows),
            self.pending_support_y,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.request_done,
                self.support_scrolls,
                self.finish_reason,
                self._confirmed_page,
                self.skipped_rows,
                self.pending_support_y,
            ) = snapshot


class KnightsDonationRunner(ModeRunnerBase):
    """骑士团捐赠一次性 Runner（主循环协议见 ``ModeRunnerBase``）。

    ⚠️ 本路线是**第一条**打开 ``_REQUIRE_TRANSITION_CONTRACT`` 的路线：每个动作
    都必须在发出前通过「source_page + 出口验收」的机器校验。
    """

    _MODE_LABEL = "骑士团捐赠"
    # 新路线准入：动作缺声明直接拒发（含空跑）。
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        KnightsDonationState.GUILD_HOME: 45,
        KnightsDonationState.ACTIVITY_PANEL: 45,
        KnightsDonationState.RESOURCE_SUPPORT: 60,
        KnightsDonationState.REQUEST_POPUP: 45,
        KnightsDonationState.SUPPORT_CONFIRM: 45,
        KnightsDonationState.REWARD_POPUP: 45,
        KnightsDonationState.WEEKLY_TASKS: 60,
        KnightsDonationState.FINISHED: 45,
    }
    # 这条路线不打架，没有「已承诺战斗」环节。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 动作重试窗口。默认 45 秒是给「换页」定的；本路线这几个动作要么是**弹窗内的一步**
    # （点完立刻能看出生效没有），要么是**同页领奖**（点完原地变灰），
    # 用 45 秒纯属白等 —— 这正是 world_boss 记过的「领奖干等 40 多秒」那一类。
    _SHORT_RETRY_ACTIONS = frozenset(
        {
            "select-flower",
            "confirm-request",
            "support-one",
            "confirm-support",
            "claim-milestone",
            "claim-task",
            # 下滑是**同一个动作名连发两次**（账本上限 2 次），第二次点击会走「同名动作
            # 等待重试窗口」那条路；用默认 45 秒就是白等 45 秒。它没有「点了没生效」
            # 的补救动作（滑不动也会照账本往下走），所以短窗口没有副作用。
            "scroll-support",
        }
    )
    _SHORT_RETRY_SECONDS = 8.0

    def __init__(
        self,
        machine: KnightsDonationStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery=recovery,
            recovery_gate=recovery_gate,
        )

    def _state_label(self, state: KnightsDonationState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _after_action_click(self, action: KnightsDonationAction) -> None:
        """``scroll-support`` 的点击是**空点**，真正的下滑在这里补发。

        为什么不让状态机直接滑：主循环的动作通道只有 ``runtime.click``，
        状态机里做 I/O 又会被 ``preview()`` 每帧重放一遍（滑动会连发几十次）。
        所以走「动作带一个没有副作用的落点 + 这里补手势」。
        """
        if action.name != "scroll-support":
            return
        self.runtime.swipe(
            SUPPORT_SWIPE_START,
            SUPPORT_SWIPE_END,
            SUPPORT_SWIPE_DURATION_MS,
            "knights-support-scroll",
        )

    def _apply_recovery_state(self) -> None:
        # 恢复导航的落点就是「骑士团主页」（``navigate("knights_donation")`` 只走
        # 大厅 → 骑士团这一级），所以状态回到 GUILD_HOME、与落点一致。
        self.machine.state = KnightsDonationState.GUILD_HOME
        # 恢复导航已经把画面换掉了，旧的「已确认页面」作废（story / world_boss 同样清空）。
        self.machine._confirmed_page = ""
        # 正在等结果的那次支援作废（点了没点完，画面已经换掉了）。
        self.machine.pending_support_y = None
        # ⚠️ 刻意**不重置** skipped_rows：那是「这一行吃不下」的事实，恢复不改变它；
        # 重置会导致恢复后在同一行上再白转一轮。
        # 「今天这一次请求支援已经发出去了」是**跨帧进度**，恢复后画面里看不出来；
        # 但恢复只发生在页面没进展时，此时请求支援那一支早已走完 —— 保留原值即可。
        # 这里刻意不重置 request_done：重置会导致恢复后重复请求（一天只能一次）。

    def _on_action_exhausted(self, action: KnightsDonationAction, screen) -> bool:
        """点 4 次都推不动 ⇒ 明确失败，记日志 + 留诊断后正常停止。

        绝不无限重试：支撑到上限时列表里的绿按钮会自己变灰（同一玩家一天只能支援
        一次），所以「绿色按钮一直点不动」不是「到上限」，而是真的出了问题。
        """
        diagnostic = self.runtime.save_diagnostic(f"knights_{action.name}_stuck", screen)
        self._save_failure_diagnostic(
            diagnostic,
            screen,
            action=action,
            attempt=4,
            conclusion=f"动作 {action.name} 连续 4 次未能看到出口证据",
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 停止=动作[{action.name}]连续 4 次未生效 "
            f"现场={diagnostic}"
        )
        return True

    def _log_cycle_completed(self) -> None:
        reason = getattr(self.machine, "finish_reason", "")
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} 结论={reason or '已走完出口'}"
        )

    def _decision_hint(self, action_name: str, state: KnightsDonationState) -> str:
        return ""
