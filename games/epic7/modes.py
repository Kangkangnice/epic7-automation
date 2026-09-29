import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
    detect_resume_point,
)
from auto_game_unified.games.epic7.story import (
    StoryRunner,
    StoryState,
    StoryStateMachine,
    build_story_templates,
    detect_resume_point as detect_story_resume_point,
)
from auto_game_unified.games.epic7.expedition import (
    ExpeditionRunner,
    ExpeditionState,
    ExpeditionStateMachine,
    detect_resume_point as detect_expedition_resume_point,
)
from auto_game_unified.games.epic7.fodder import (
    FodderRunner,
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
# 以「模块对象」形式再导一次：``_preflight_shop_refresh`` 要在调用时读
# ``LIVE_TRANSACTIONS_VERIFIED``（理由见该函数），不能只在 import 期绑一份名字。
from auto_game_unified.games.epic7.evidence import shop_refresh as _shop_refresh_evidence
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    build_shop_refresh_observer,
)
from auto_game_unified.games.epic7.evidence.survivor import build_survivor_observer
from auto_game_unified.games.epic7.shop_refresh import (
    ShopPhase,
    ShopRefreshRunner,
    ShopRefreshStateMachine,
    detect_resume_point as detect_shop_resume_point,
)
from auto_game_unified.games.epic7.survivor import (
    SurvivorRunner,
    SurvivorState,
    SurvivorStateMachine,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.knights_donation import (
    KnightsDonationRunner,
    KnightsDonationState,
    KnightsDonationStateMachine,
    detect_resume_point as detect_knights_donation_resume_point,
)
from auto_game_unified.games.epic7.labyrinth_stone import (
    LabyrinthStoneRunner,
    LabyrinthStoneState,
    LabyrinthStoneStateMachine,
    detect_resume_point as detect_labyrinth_stone_resume_point,
)
from auto_game_unified.games.epic7.sanctuary import (
    SanctuaryRunner,
    SanctuaryState,
    SanctuaryStateMachine,
    detect_resume_point as detect_sanctuary_resume_point,
)
from auto_game_unified.games.epic7.world_boss import (
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    detect_resume_point as detect_world_boss_resume_point,
)


MachineFactory = Callable[[Path, str], Any]


@dataclass(frozen=True)
class ResumePoint:
    """开局接力的落点：认出停在哪儿之后，调用方据此决定「怎么接着往下跑」。"""

    page: str                       # 中文页面名，给日志和诊断看
    state: Optional[str] = None     # 要拨过去的状态机状态值；None = 不动状态机
    entry: Optional[str] = None     # 已经在导航链的这个页面上，从这里接着导航
                                    # （None = 已在业务入口，不需要导航）


# 「接力探针」：给 (状态机, 一帧画面, 导航器)，认出用户停在本路线的哪一步就返回落点，
# 认不出来返回 None。命中即接管，调用方跳过「回大厅 → 按路线导航」。
# 传导航器是因为有些页面（比如竞技场模式选择页）只有导航器认得出来。
ResumeProbe = Callable[[Any, np.ndarray, Any], Optional[ResumePoint]]

# 「运行前校验」：给 (本路线名, 是否干跑)，返回拒绝文案就拒绝运行（None = 放行）。
# 有些路线在「证据还没在**当前客户端**上实证过」之前不该实跑（比如刷书签会真花钱）。
# 这条闸门以前写成 ``main.run_mode`` 里的 ``if spec.name == "shop_refresh"``，
# 结果是每加一条这样的路线就要往 ``main.py`` 里再插一个 ``if`` —— 直接违背
# ``docs/EXTENDING.md`` 的「不要在 main.py 添加新的条件分支」。
Preflight = Callable[[str, bool], Optional[str]]

# 「路线级额外构造参数」：给 (仓库根, 是否干跑)，返回要转发给 Runner 构造函数的
# 关键字参数。像落盘位置这种「只有实跑才需要」的参数走这里，``main`` 不再认具名路线。
RunnerOptions = Callable[[Path, bool], dict[str, Any]]


@dataclass(frozen=True)
class ModeSpec:
    """一条路线的全部「事实」。同名信息（中文名、默认次数）**只在这里定义一次**。

    ⚠️ 中文名 ``label`` 与次数（``default_cycles`` / ``cycles_editable`` /
    ``min_cycles``）以前各自抄在 CLI / 交互菜单 / 桌面助手 / 每日任务好几处，
    改一处漏一处不会报错
    （实测出现过 ``survivor`` 在界面叫「活动」、在通知里叫「幸存者」；
    ``shop_refresh`` 在每日任务里叫「商店刷新」、别处叫「刷书签」）。
    2026-09-27 收敛到这里，其余入口一律从这里派生 —— 别再往别处抄一份。
    """

    name: str
    label: str
    default_state: str
    states: frozenset[str]
    build_machine: MachineFactory
    runner_type: type
    # 默认跑几次。``cycles_editable=False`` 表示这条路线的次数**由游戏规则决定、
    # 不给用户选**（每天上限固定，或跑一遍就结束）⇒ 各入口直接采用本值、不问用户。
    default_cycles: int = 1
    cycles_editable: bool = True
    # 允许填的最小次数。默认 1（次数必须是正整数）；只有「0 次本身就是一种有意义的
    # 业务模式」的路线才设成 0 —— 目前**只有** ``shop_refresh``：0 次 = 照常进商店、
    # 从上到下扫一遍、把想要的买掉，但**一次都不付费刷新**（秘密商店自己会随时间自动刷新）。
    # 各入口的「次数必须为正」校验一律以本字段为准
    # （``desktop/app.py`` / ``desktop/worker.py`` / ``main.py`` / ``shop_refresh.py``）。
    min_cycles: int = 1
    needs_navigation: bool = True
    resume_probe: Optional[ResumeProbe] = None
    # 路线级的运行前闸门与额外构造参数，见上面两个类型别名的说明。
    # ⚠️ 这两个钩子就是「新路线需要专属校验 / 专属参数」时的唯一入口 ——
    # 不要再回去 ``main.py`` 里加 ``if spec.name == ...``。
    preflight: Optional[Preflight] = None
    runner_options: Optional[RunnerOptions] = None

    def resolve_state(self, requested: str | None) -> str:
        state = requested or self.default_state
        if state not in self.states:
            choices = ", ".join(sorted(self.states))
            raise ValueError(f"起始状态 {state!r} 不适用于模式 {self.name}；可选：{choices}")
        return state

def _build_arena(template_root: Path, state: str) -> ArenaStateMachine:
    return ArenaStateMachine(
        build_templates(template_root),
        initial_state=ArenaState(state),
    )


def _build_story(template_root: Path, state: str) -> StoryStateMachine:
    return StoryStateMachine(
        build_story_templates(template_root / "story"),
        initial_state=StoryState(state),
    )


def _build_expedition(template_root: Path, state: str) -> ExpeditionStateMachine:
    return ExpeditionStateMachine(
        template_root / "expedition",
        initial_state=ExpeditionState(state),
    )


def _build_fodder(template_root: Path, state: str) -> FodderStateMachine:
    return FodderStateMachine(
        build_fodder_templates(template_root / "fodder"),
        initial_state=FodderState(state),
    )


def _build_hero_synthesis(template_root: Path, state: str) -> HeroSynthStateMachine:
    return HeroSynthStateMachine(
        build_hero_templates(template_root),
        initial_state=HeroSynthState(state),
    )


def _build_shop_refresh(template_root: Path, state: str) -> ShopRefreshStateMachine:
    if state != ShopPhase.SCAN_TOP.value:
        raise ValueError(f"刷书签起始阶段无效：{state}")
    return ShopRefreshStateMachine(
        1,
        observer=build_shop_refresh_observer(template_root),
    )


def _resume_probe(
    detect: Callable[..., Any],
    *,
    use_navigator: bool = False,
    on_hit: Optional[Callable[[Any], None]] = None,
) -> ResumeProbe:
    """接力探针工厂：把「认出落点 → 拨状态机 → 交回落点」这套固定流程写死一次。

    ⚠️ 它存在的理由是**一个真发生过的错**：手抄这段流程时最容易漏掉
    ``machine.resume_from(found.state)`` —— 漏了之后接力**看起来**是命中的
    （日志照打「开局=接力」），但状态机没拨过去，Runner 会原地干等到超时，而不是自愈。
    这个错当年**没有任何测试能发现**（见 ``docs/maintenance/route_extensibility_review.md``
    第四节）。⇒ 把那句话做成**代码**，新路线就不可能再漏。

    参数：

    - ``detect``：这条路线自己的 ``detect_resume_point``。
    - ``use_navigator``：判据要用导航器认出的页面名。**只有三条路线的判据接受
      ``observed_page=`` 参数**（arena / story / expedition —— 它们的接力点里有
      「导航链中间站」），所以这个开关同时决定「要不要问导航器」和「怎么调用判据」。
    - ``on_hit``：命中后的路线专属动作（目前只有刷书签用：打一个
      ``mark_resumed_at_shop()`` 记号，让 Runner 先把列表拨回顶部再开扫）。

    落点状态一律**归一成字符串**再放进 ``ResumePoint.state``（判据那边给的可能是 Enum）；
    ``state is None`` 表示「这个落点不需要拨状态」（如刷书签/骑士团捐赠/迷宫的落点）。
    """
    def probe(
        machine: Any,
        screen: np.ndarray,
        navigator: Any,
    ) -> Optional[ResumePoint]:
        if use_navigator:
            observed = (
                navigator.observe(screen).name if navigator is not None else None
            )
            found = detect(machine, screen, observed_page=observed)
        else:
            found = detect(machine, screen)
        if found is None:
            return None
        state = found.state
        if state is not None:
            # 命中即接管：必须把状态一起拨好，否则 Runner 会原地干等到超时。
            machine.resume_from(state)
        if on_hit is not None:
            on_hit(machine)
        return ResumePoint(
            page=found.page,
            # Enum ⇒ ``.value``；判据直接给字符串（或恒为 None）时原样带出。
            state=getattr(state, "value", state),
            entry=found.entry,
        )

    # 记下「这个探针是用哪条判据造的」（标准内省约定 ``__wrapped__``）。
    # 各路线自己的 ``tests/test_<路线>_resume.py`` 靠它断言「注册的探针确实是这条路线
    # 的判据造的」，而不是隔壁那条路线的 —— 抄注册行最容易犯的错就是漏改这个参数。
    probe.__wrapped__ = detect
    return probe


def _build_survivor(template_root: Path, state: str) -> SurvivorStateMachine:
    # 整轮循环都在活动小游戏内部，起点固定是用户人工停好的「选第一张卡」页，
    # 所以只允许这一个起始状态。
    if state != SurvivorState.CARD.value:
        raise ValueError(f"幸存者起始状态无效：{state}")
    return SurvivorStateMachine(
        observer=build_survivor_observer(template_root),
    )


def _build_world_boss(template_root: Path, state: str) -> WorldBossStateMachine:
    return WorldBossStateMachine(
        template_root / "world_boss",
        initial_state=WorldBossState(state),
    )


def _build_labyrinth_stone(template_root: Path, state: str) -> LabyrinthStoneStateMachine:
    # 模板子目录是 templates/labyrinth_stone；工厂必须把它当根，不能当 templates 根。
    return LabyrinthStoneStateMachine(
        template_root / "labyrinth_stone",
        initial_state=LabyrinthStoneState(state),
    )


def _build_knights_donation(template_root: Path, state: str) -> KnightsDonationStateMachine:
    # 模板子目录是 templates/knights_donation；工厂必须把它当根，不能当 templates 根。
    return KnightsDonationStateMachine(
        template_root / "knights_donation",
        initial_state=KnightsDonationState(state),
    )


def _build_sanctuary(template_root: Path, state: str) -> SanctuaryStateMachine:
    # 模板子目录是 templates/sanctuary；工厂必须把它当根，不能当 templates 根。
    return SanctuaryStateMachine(
        template_root / "sanctuary",
        initial_state=SanctuaryState(state),
    )


# ── 路线级钩子的实现（``ModeSpec.preflight`` / ``ModeSpec.runner_options``）─────────
# ⚠️ 这两个函数原先就活在 ``main.run_mode`` 里，只是当时写成了 ``if spec.name == ...``。
# 现在只是把它们搬回各自的路线旁边，**行为逐字不变**（包括报错文案与「在创建 runtime
# 之前就拦下」这个顺序 —— 有测试钉着 ``_build_runtime`` 不许被调用）。


def _preflight_shop_refresh(mode: str, dry_run: bool) -> Optional[str]:
    """刷书签的实跑闸门：目标商品与购买价格没在当前客户端实证过就不许实跑。"""
    # ⚠️ 标志位必须**在调用时**从 ``evidence.shop_refresh`` 的模块属性上读，不能
    # ``from ... import LIVE_TRANSACTIONS_VERIFIED`` 在 import 期绑一份到本模块 ——
    # 绑了之后测试改成 ``patch.object(evidence.shop_refresh, ...)`` 就拦不住它，
    # 这条闸门会悄悄退化成空转。
    if dry_run or _shop_refresh_evidence.LIVE_TRANSACTIONS_VERIFIED:
        return None
    return "刷书签目标商品和购买价格尚未通过当前客户端实证，当前只允许空跑采样"


def _arena_runner_options(root: Path, dry_run: bool) -> dict[str, Any]:
    """竞技场实跑才需要的两个落盘位置（干跑一个盘都不写）。"""
    if dry_run:
        return {}
    return {
        # 买票「今天买过没有」的记账文件。
        "purchase_stamp_path": root / "runtime_logs" / "arena_ticket_purchase.txt",
        # 每局结算画面留一张盘，给「胜负判得对不对」留可回看的证据（见 ArenaRunner）。
        "outcome_frame_dir": root / "docs" / "manual_review" / "arena",
    }


# 「接力」豁免名单：**必须写明理由**，才允许一条有导航的路线不挂 ``resume_probe``。
#
# 与转场契约的 ``_REQUIRE_TRANSITION_CONTRACT`` 是两件事：那个管「跑起来之后每个动作
# 有没有出口验收」，这个管「开局时人停在半路能不能接上」。一个是逐动作、一个是
# 开局一次性，所以卡法不同 —— 见 ``docs/TRANSITION_CONTRACTS.md``「接力契约」。
#
# 名单在模块加载时自查（见文件末尾 ``_assert_resume_declared``）：新路线漏了接力，
# **import 阶段就报错**，不会等到有人停在半路才发现自己白走一趟大厅。
#
# ``needs_navigation=False`` 的路线自动豁免，不用进这张表 —— 它的起点本来就是人工把
# 游戏推进到活动内部再启动，连「回大厅」这条路径都没有，谈不上接力。
RESUME_EXEMPT = {
    "fodder": (
        "锚点其实齐全，但有一个**做接力之前必须先解决**的坑：`fodder/replay.png`"
        "（「重新进行」那一页）会被 `battle_scene_visible` 误判成局内。照搬别人"
        "「先判局内」的顺序，停在结算页启动会被当成已承诺战斗去监督，而不是点"
        "「重新进行」—— 白打一局。先解决它再谈接力。"
    ),
    "hero_synthesis": (
        "缺的不是「顺序跑得动」的锚点，而是**排他**锚点：`auto_select_label` 在"
        "「传送选择 / 传送确认 / 传送奖励」三页上同时可见（实测都是 1.000）。"
        "运行期靠状态上下文分得开，**接力只有一帧、没有这个上下文** —— 把它误认成"
        "「传送选择」会重复点一次不可逆的传送确认。PC 端的英雄列表连锚点都没有。"
    ),
}


# 「动作验收方式」的豁免名单：**必须写清「用自己的什么机制验收」**，才允许一条路线
# 不打开基类的转场强制开关（``ModeRunnerBase._REQUIRE_TRANSITION_CONTRACT``）。
#
# 与上面的 ``RESUME_EXEMPT`` 是**路线准入的两半**，形状刻意做成一样的（一份表 + 一句理由 +
# 加载期自查），因为它们回答的是同一类问题：「这条路线有没有对某件事表过态」。
#   - ``RESUME_EXEMPT`` 管「开局停在半路，做不做接力」；
#   - ``TRANSITION_EXEMPT`` 管「跑起来之后，动作的出口验收靠什么」。
#
# 判定规则见 ``_assert_transition_stance_declared``：**打开开关、或进本名单，二选一**。
# 漏了在 **import 阶段**就报错，不会等到实跑才发现某个动作点了不回头。
#
# ⚠️ 名单里标着「**已知欠债**」的三条是真缺判据，不是「用了别的机制」——
# 把缺口写在明处，比假装它不存在强。它们各自的补法写在理由里。
TRANSITION_EXEMPT = {
    "arena": (
        "继承**事务型主循环基类** `TransactionalRunnerBase`，但**保留自己的 `run()`**"
        "（循环策略与远征不同，见 `arena.ArenaRunner` 的类 docstring）⇒ 这个开关的"
        "读取点在 `ModeRunnerBase.run()` 里，对它无效。转场那一段走基类的 "
        "`_execute_transition`：`Action.source_state` / `target_states` 缺任一"
        "**直接 raise**，且目标页要连续两帧才算转场成功 —— 比开关更严。"
    ),
    "expedition": (
        "继承**事务型主循环基类** `TransactionalRunnerBase`（2026-09-26 从裸定义搬过去的），"
        "**不是** `ModeRunnerBase` ⇒ 这个开关的读取点在基类 `run()` 里，对它一样无效。"
        "它走 `ExpeditionAction.source_page` / `target_pages` ＋ 基类 `_execute_transition`："
        "来源/目标合同缺任一**直接 raise**，且目标页要连续两帧才算转场成功。"
    ),
    "shop_refresh": (
        "自带独立主循环，验收靠自己的 `_wait_stable` / `_open_with_retry`："
        "每次购买或刷新都「点完等到目标页稳定」才放行，不经过基类的转场账本。"
    ),
    "survivor": (
        "自带独立主循环，用 `_observe_stable(page, timeout)` 验收。"
        "⚠️ **已知欠债**：出口验收确实缺 —— 点完不回头看，没生效只能靠"
        "`_BATTLE_TIMEOUT_SECONDS=1800` 兜（那是安全网，不是判据）。"
    ),
    "fodder": (
        "⚠️ **已知欠债**：走基类主循环，但 `FodderAction` 只有 `name` / `point` 两个字段，"
        "**完全没有判据** —— 漏写不会有任何报错。补法见 docs/TRANSITION_CONTRACTS.md。"
    ),
    "hero_synthesis": (
        "⚠️ **已知欠债**：走基类主循环，绝大多数动作有判据，但开关**打不开** —— "
        "PC 客户端分支有 3 处 `source_page=\"\"`、另有 1 处 `target_pages=()`，"
        "一开这些动作当场被拦。它的页内证据字段名是 `source_observation`，"
        "机器认的是 `in_page_evidence`，两者要先对齐。"
    ),
    "story": (
        "走基类主循环、未开开关，但**不需要**：`StoryAction` 全项目只有 1 个构造点"
        "（在 `_action()` 内），而它的 `source_page` / `target_pages` 是**无默认值的必填参数**"
        "⇒ 漏填直接 `TypeError`，比开关更硬。开它属于冗余。"
    ),
}


MODE_SPECS = {
    "arena": ModeSpec(
        name="arena",
        label="竞技场",
        default_state=ArenaState.LIST.value,
        states=frozenset(state.value for state in ArenaState),
        build_machine=_build_arena,
        runner_type=ArenaRunner,
        # 开局不无脑回大厅：先看一眼停在哪一步，停在对战详情/准备战斗/对手列表
        # 就直接从那一步接着跑；停在别的支线页面才退回原来的「一直返回」流程。
        # 判据要问导航器认出的页名 —— 接力点里有「竞技场模式选择页」这个导航链中间站。
        resume_probe=_resume_probe(detect_resume_point, use_navigator=True),
        # 实跑要落两个盘（买票记账 + 每局结算画面），路径只有主线装配层知道仓库根。
        runner_options=_arena_runner_options,
    ),
    "story": ModeSpec(
        name="story",
        label="主线",
        default_state=StoryState.STAGE.value,
        states=frozenset(state.value for state in StoryState),
        build_machine=_build_story,
        runner_type=StoryRunner,
        # 开局不无脑回大厅：先看停在主线哪一步。关卡入口直接接管，队伍准备/战斗中
        # 就接着打，结算/通关提示/额外奖励就接着收奖励（这几页回大厅会白丢奖励）。
        # ⚠️ 落点必须把状态拨对：``next_action`` 有两支依赖进来时的状态才肯点
        # （``prepare_battle`` 在 WAIT_COMPLETE/WAIT_NEXT_STAGE 下只记轮次不点；
        # 战斗控件分支只在 WAIT_SKIP_CONFIRM/WAIT_BATTLE/ACTIVE 下跑），
        # 拨错会让 Runner 原地干等到超时，而不是自愈。
        resume_probe=_resume_probe(detect_story_resume_point, use_navigator=True),
    ),
    "expedition": ModeSpec(
        name="expedition",
        label="远征",
        default_state=ExpeditionState.HOME.value,
        states=frozenset(state.value for state in ExpeditionState),
        build_machine=_build_expedition,
        runner_type=ExpeditionRunner,
        # 开局不无脑回大厅：导航链四级（战斗菜单/赛季菜单/远征主页）都开放接力，
        # 业务页从通缉传单一路到公开招募也都接得住。
        # ⚠️ 落点必须拨状态：``next_action`` 是纯状态驱动的，拨错**不会自愈**
        # （会走到 ``_required`` 失败或点错按钮）。
        resume_probe=_resume_probe(detect_expedition_resume_point, use_navigator=True),
    ),
    "fodder": ModeSpec(
        name="fodder",
        label="狗粮",
        default_state=FodderState.STAGE.value,
        states=frozenset(state.value for state in FodderState),
        build_machine=_build_fodder,
        runner_type=FodderRunner,
    ),
    "hero_synthesis": ModeSpec(
        name="hero_synthesis",
        label="英雄合成",
        default_state=HeroSynthState.HERO_LIST.value,
        states=frozenset(state.value for state in HeroSynthState),
        build_machine=_build_hero_synthesis,
        runner_type=HeroSynthRunner,
        # 英雄合成跑完一遍列表就结束，没有「跑几遍」这件事 ⇒ 不给用户选。
        cycles_editable=False,
    ),
    "shop_refresh": ModeSpec(
        name="shop_refresh",
        label="刷书签",
        default_state=ShopPhase.SCAN_TOP.value,
        states=frozenset({ShopPhase.SCAN_TOP.value}),
        build_machine=_build_shop_refresh,
        runner_type=ShopRefreshRunner,
        # 默认**不付费刷新**（0 次）：秘密商店自己会随时间自动刷新，每天进去扫一遍、
        # 把自动刷出来的目标商品买掉即可 —— 0 次不花天空石，所以是安全默认值。
        # ⚠️ 这也是唯一 ``min_cycles=0`` 的路线，见 ``ModeSpec.min_cycles``。
        default_cycles=0,
        min_cycles=0,
        # 开局不无脑回大厅：先看一眼是不是已经站在秘密商店页上 —— 是的话就地接管
        # （回大厅会白走一趟「大厅 → 秘密商店」导航，中间还可能被别的弹窗截住）。
        # 判据是三个锚点（商店标题 + 立即更新 + 购买按钮）同时过阈，不是「像商店」。
        # 落点**不拨状态**（phase 是内部阶段、起始恒为 SCAN_TOP），只打一个
        # ``mark_resumed_at_shop`` 记号：Runner 据此先把列表拨回顶部再开扫，
        # 免得人停在列表半截时被当成「顶部批次」。判据自带走观察器，用不到导航器。
        resume_probe=_resume_probe(
            detect_shop_resume_point,
            on_hit=lambda machine: machine.mark_resumed_at_shop(),
        ),
        # 这条路线会真花钱 ⇒ 目标商品与购买价格没在当前客户端实证过就不许实跑
        # （干跑不受影响）。闸门本体见 ``_preflight_shop_refresh``。
        preflight=_preflight_shop_refresh,
    ),
    "survivor": ModeSpec(
        name="survivor",
        label="活动",
        default_state=SurvivorState.CARD.value,
        states=frozenset({SurvivorState.CARD.value}),
        build_machine=_build_survivor,
        runner_type=SurvivorRunner,
        # 界面默认填 3 轮，但用户可以改（这条路线没有每日上限）。
        default_cycles=3,
        # 起点是用户人工推进到的活动小游戏内部页面，不需要从大厅导航过来，
        # 出问题时也不做任何「回大厅」动作（Back 会退回活动主页那个未知状态）。
        needs_navigation=False,
    ),
    "world_boss": ModeSpec(
        name="world_boss",
        label="世界首领战",
        default_state=WorldBossState.HOME.value,
        states=frozenset(state.value for state in WorldBossState),
        build_machine=_build_world_boss,
        runner_type=WorldBossRunner,
        # 每天固定 2 次（主页「剩余/上限」就是 2），用户明确要求「不要让我选择次数」。
        default_cycles=2,
        cycles_editable=False,
        # 开局不无脑回大厅：主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励
        # 就地从那一步接着跑，停在局内则把这一局打完再说。骑士团主页这个导航链
        # 中间站也接（省掉「回大厅 → 进骑士团」两级）。
        # ⚠️ 落点必须拨状态 —— 不是为了让页面判得准（``next_action`` 每页都现判），
        # 而是为了让 ``WorldBossRunner`` 拿到 ``resumed_from``：停在局内时要靠它跳过
        # 状态机、把这一局直接交给战斗监督，不能按 Back 回大厅。
        resume_probe=_resume_probe(detect_world_boss_resume_point),
    ),
    "knights_donation": ModeSpec(
        name="knights_donation",
        label="骑士团捐赠",
        # 路线从骑士团主页开始（导航把画面停在那儿），第一步就是点「骑士团活动」图标。
        default_state=KnightsDonationState.GUILD_HOME.value,
        # 终态 ``FINISHED`` 不给当起始状态：它不是一页画面，是「本轮已收工」的记号。
        states=frozenset(
            state.value
            for state in KnightsDonationState
            if state is not KnightsDonationState.FINISHED
        ),
        build_machine=_build_knights_donation,
        runner_type=KnightsDonationRunner,
        # 每天跑一遍就够：请求支援一天只能发一次、红点领完就没了 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在骑士团主页 / 资源支援列表 / 每周任务上就地接管。
        # 三个弹窗与活动界面兜底页不接（不可逆 / 判据不排他 / 无正例），
        # 见 knights_donation._RESUMABLE_STATES 上方的理由。
        # 落点状态恒为 None（本路线每帧重判页面，不需要拨状态）；停在大厅认不出
        # （``activity_entry`` 在骑士团主页上，大厅上不成立），照旧走「回大厅 → 进骑士团」。
        resume_probe=_resume_probe(detect_knights_donation_resume_point),
    ),
    "labyrinth_stone": ModeSpec(
        name="labyrinth_stone",
        label="迷宫强化石",
        # 导航把画面停在战斗菜单（「一般」页），第一步就是点迷宫卡片。
        default_state=LabyrinthStoneState.BATTLE_MENU.value,
        states=frozenset(
            state.value
            for state in LabyrinthStoneState
            if state is not LabyrinthStoneState.FINISHED
        ),
        build_machine=_build_labyrinth_stone,
        runner_type=LabyrinthStoneRunner,
        # 迷宫采购一天一次，跑一遍就结束 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在战斗菜单 / 迷宫列表 / 详情页 / 准备战斗页时接着往里走，
        # 停在迷宫里 / 暂停菜单 / 放弃确认框 / 快捷菜单时接着往外走。
        # 判据与运行期同源（状态机自己的 ``observe_page``）；停在「已经进过迷宫」的那几页
        # 时 ``detect_resume_point`` 会顺手把 ``entered`` 拨对，落点状态本身恒为 None。
        resume_probe=_resume_probe(detect_labyrinth_stone_resume_point),
    ),
    "sanctuary": ModeSpec(
        name="sanctuary",
        label="圣域收菜",
        # 导航把画面停在圣域主页（大厅左侧最上面那个入口进去），第一步就是点「精灵之森」。
        default_state=SanctuaryState.HOME.value,
        # 终态 ``FINISHED`` 不给当起始状态：它不是一页画面，是「本轮已收工」的记号。
        states=frozenset(
            state.value
            for state in SanctuaryState
            if state is not SanctuaryState.FINISHED
        ),
        build_machine=_build_sanctuary,
        runner_type=SanctuaryRunner,
        # 每天跑一遍就够：圣域材料按天刷新，收完就没有可领的了 ⇒ 不给用户选。
        cycles_editable=False,
        # 开局不无脑回大厅：停在圣域主页时就地接管（并且把落点 ``entry`` 交给导航，
        # 省掉「回大厅 → 再进圣域」那一趟）；停在精灵之森页也接得住。
        # 领取完成弹窗刻意不接（它的动作只有一个「点关闭」，而回大厅路上的 ESC
        # 本来就会把它关掉）；停在大厅认不出（``forest_row`` 在大厅上不成立），
        # 照旧走「回大厅 → 进圣域」。
        # 落点状态恒为 None（本路线每帧重判页面，不需要拨状态）。
        resume_probe=_resume_probe(detect_sanctuary_resume_point),
    ),
}

# 中文名的**唯一来源**。``main`` / ``navigation`` 直接用它；桌面助手的
# 菜单与面板也从这里取（见 ``desktop/catalog.py``）。⚠️ 别在别处再抄一份名字表 —— 抄了就会漂移，
# 因为没有任何机制会告诉你「另一处的名字没跟着改」。
MODE_LABELS = {name: spec.label for name, spec in MODE_SPECS.items()}


def get_mode(name: str) -> ModeSpec:
    return MODE_SPECS[name]


def _assert_resume_declared() -> None:
    """加载期自查：每条有导航的路线都必须对「接力」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 挂 ``resume_probe``（能接力）；
    - 进 ``RESUME_EXEMPT`` 并写明理由（不做接力）。

    只查结构，不跑判据 —— 判据准不准要靠拿真夹具跑一遍（
    ``tests/test_resume_contracts.py``），代码里看不出来。
    """
    for name, spec in MODE_SPECS.items():
        if not spec.needs_navigation:
            continue
        has_probe = spec.resume_probe is not None
        exempt = name in RESUME_EXEMPT
        if has_probe and exempt:
            raise RuntimeError(
                f"路线 {name} 既挂了接力探针、又躺在 RESUME_EXEMPT 里；"
                "两边只能写一边（挂了探针就把豁免那条划掉）。"
            )
        if not has_probe and not exempt:
            raise RuntimeError(
                f"路线 {name} 既没有 resume_probe，也不在 RESUME_EXEMPT 里。"
                "要么挂接力探针，要么在 RESUME_EXEMPT 里写明为什么不做接力；"
                "规矩见 docs/TRANSITION_CONTRACTS.md「接力契约」。"
            )


# 「结论门槛」的登记表：**必须写明这条路线靠什么保证「不一帧下结论」**。
#
# ⚠️ 背景（2026-09-25 实跑）：动作要连续两帧一致才敢点，这条规矩早就有了；但
# **收工 / 认不出画面这类终止性结论**是从 ``preview()`` 里直接抛到主循环的，
# 压根没过那道门槛 ⇒ 一帧就能宣布「今天打完了」、一帧没认出画面就去点屏幕中间。
# 动作要两帧、结论只要一帧，等于门只掩了一半。
#
# 判定规则（``_assert_conclusion_gate_declared``）：继承 ``ModeRunnerBase``、且没重写
# ``_stable_next_action`` 的路线自动达标（基类里已经接了 ``ConclusionGate``）；
# 其余（自带独立主循环的，以及 2026-09-26 起的 ``TransactionalRunnerBase`` 那一族）
# 必须在这张表里写明自己靠什么达标。
CONCLUSION_GATE_DECLARATION = {
    "arena": (
        "继承**事务型主循环基类** ``TransactionalRunnerBase``，但**保留自己的 "
        "``run()``**（循环策略与远征不同，见 ``arena.ArenaRunner`` 的类 docstring）。"
        "``ConclusionGate`` 接在它自己的 ``run()`` 里：``preview`` 抛出的终止性结论"
        "先过门槛、两帧一致才允许按结论处理。覆盖见 "
        "``tests/test_conclusion_gate.py::ArenaLoopConclusionTests``。"
    ),
    "expedition": (
        "继承**事务型主循环基类** ``TransactionalRunnerBase``（不是 ``ModeRunnerBase``）。"
        "``ConclusionGate`` 接在基类 ``run()`` 里：``preview`` 抛出的终止性结论先过门槛、"
        "两帧一致才允许按结论处理。覆盖见 "
        "``tests/test_conclusion_gate.py::ExpeditionLoopConclusionTests``。"
    ),
    "shop_refresh": (
        "不是「每帧下一结论」的形态：全程靠 ``_wait_stable`` / ``_observe_stable`` "
        "先等画面稳定再判定，认不出也只有**超时之后**才失败，不存在单帧收工。"
    ),
    "survivor": (
        "同上：靠 ``_observe_stable(page, timeout)`` 验收，``_failure`` 全部发生在"
        "「页面已稳定确认」或「超时」之后，不存在单帧收工。"
    ),
}


def _base_conclusion_gate_protected(runner_type: type) -> bool:
    """这条路线的 Runner 是否真的走得到基类那道结论门槛。

    重写 ``_stable_next_action`` **不等于绕过门槛** —— ``HeroSynthRunner`` 就重写了它
    （为了导航后先等画面稳一稳），但内部调了 ``super()``，门槛照样生效。所以判据是：
    没重写 = 达标；重写了 = 必须把基类的实现调回去（``super()._stable_next_action``）。
    """

    if not issubclass(runner_type, ModeRunnerBase):
        return False
    overridden = "_stable_next_action" in runner_type.__dict__
    if not overridden:
        return True
    return "super()._stable_next_action" in inspect.getsource(
        runner_type._stable_next_action
    )


def _assert_conclusion_gate_declared() -> None:
    """加载期自查：每条路线都必须对「不一帧下结论」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 走 ``ModeRunnerBase`` 主循环、且门槛没被自己绕过去（见
      ``_base_conclusion_gate_protected``）；
    - 进 ``CONCLUSION_GATE_DECLARATION`` 并写明「自己靠什么保证」。

    与 ``_assert_transition_stance_declared`` 是同一类护栏的两半：那个管「点了
    之后有没有回头看」，这个管「下结论之前有没有看够两帧」。
    """
    for name, spec in MODE_SPECS.items():
        runner_type = spec.runner_type
        guarded = _base_conclusion_gate_protected(runner_type)
        declared = name in CONCLUSION_GATE_DECLARATION
        if guarded and declared:
            raise RuntimeError(
                f"路线 {name} 走基类主循环、门槛已经生效，却又躺在 "
                "CONCLUSION_GATE_DECLARATION 里；两边只能写一边（走基类就把登记划掉）。"
            )
        if not guarded and not declared:
            raise RuntimeError(
                f"路线 {name} 既不在基类门槛的保护下、也没登记自己的结论门槛。"
                "要么别重写 _stable_next_action（让基类的 ConclusionGate 生效），"
                "要么在 CONCLUSION_GATE_DECLARATION 里写清「自己靠什么保证不一帧下结论」；"
                "规矩见 docs/TRANSITION_CONTRACTS.md「结论门槛（全局强制）」。"
            )


def _assert_transition_stance_declared() -> None:
    """加载期自查：每条路线都必须对「动作的出口验收」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 打开 ``_REQUIRE_TRANSITION_CONTRACT``（此后每个动作必须带 ``source_page`` +
      ``target_pages`` / ``in_page_evidence``）；
    - 进 ``TRANSITION_EXEMPT`` 并写清「用自己的什么机制验收」。

    ⚠️ **只认继承 ``ModeRunnerBase`` 的路线**（读开关的代码在那儿）。
    ``shop_refresh`` / ``survivor`` 是自带独立主循环的裸定义，连这个属性都没有；
    ``arena`` / ``expedition`` 继承的是 ``TransactionalRunnerBase``（另一族基类，
    2026-09-26 起）—— 四者的共同点是「属性设了也没人读」⇒ 必然落在豁免名单里，
    理由写「用自己的哪套机制」。别把「它的动作没有 ``target_pages``」直接推成
    「打开开关会抛错」—— 还要问一句「它的 runner 走得到那段代码吗」。

    只查结构，不跑判据 —— 判据准不准要靠拿真夹具跑一遍
    （``tests/test_transition_contracts.py`` 与各路线自己的 ``test_*_runner``）。
    """
    for name, spec in MODE_SPECS.items():
        enforced = (
            getattr(spec.runner_type, "_REQUIRE_TRANSITION_CONTRACT", False) is True
        )
        exempt = name in TRANSITION_EXEMPT
        if enforced and exempt:
            raise RuntimeError(
                f"路线 {name} 既打开了转场强制开关、又躺在 TRANSITION_EXEMPT 里；"
                "两边只能写一边（打开了就把豁免那条划掉）。"
            )
        if not enforced and not exempt:
            raise RuntimeError(
                f"路线 {name} 既没有打开 _REQUIRE_TRANSITION_CONTRACT，"
                "也不在 TRANSITION_EXEMPT 里。要么打开开关（此后每个动作必须带 "
                "source_page + target_pages / in_page_evidence），要么在 "
                "TRANSITION_EXEMPT 里写清「用自己的什么机制验收」；"
                "规矩见 docs/TRANSITION_CONTRACTS.md。"
            )
