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
from auto_game_unified.games.epic7.world_boss import (
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    detect_resume_point as detect_world_boss_resume_point,
)


MachineFactory = Callable[[Path, str, str], Any]


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


@dataclass(frozen=True)
class ModeSpec:
    name: str
    default_state: str
    states: frozenset[str]
    build_machine: MachineFactory
    runner_type: type
    needs_navigation: bool = True
    supported_backends: frozenset[str] = frozenset({"emulator", "pc"})
    resume_probe: Optional[ResumeProbe] = None

    def resolve_state(self, requested: str | None) -> str:
        state = requested or self.default_state
        if state not in self.states:
            choices = ", ".join(sorted(self.states))
            raise ValueError(f"起始状态 {state!r} 不适用于模式 {self.name}；可选：{choices}")
        return state

    def validate_backend(self, backend: str) -> None:
        if backend in self.supported_backends:
            return
        if self.name == "shop_refresh":
            raise ValueError("刷书签当前仅支持模拟器")
        raise ValueError(f"模式 {self.name} 不支持后端 {backend}")


def _build_arena(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> ArenaStateMachine:
    return ArenaStateMachine(
        build_templates(template_root, backend=backend),
        initial_state=ArenaState(state),
        backend=backend,
    )


def _build_story(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> StoryStateMachine:
    return StoryStateMachine(
        build_story_templates(template_root / "story", backend=backend),
        initial_state=StoryState(state),
        backend=backend,
    )


def _build_expedition(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> ExpeditionStateMachine:
    return ExpeditionStateMachine(
        template_root / "expedition",
        initial_state=ExpeditionState(state),
        backend=backend,
    )


def _build_fodder(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> FodderStateMachine:
    return FodderStateMachine(
        build_fodder_templates(template_root / "fodder"),
        initial_state=FodderState(state),
    )


def _build_hero_synthesis(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> HeroSynthStateMachine:
    return HeroSynthStateMachine(
        build_hero_templates(template_root, backend=backend),
        initial_state=HeroSynthState(state),
        backend=backend,
    )


def _build_shop_refresh(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> ShopRefreshStateMachine:
    if state != ShopPhase.SCAN_TOP.value:
        raise ValueError(f"刷书签起始阶段无效：{state}")
    if backend != "emulator":
        raise ValueError("刷书签当前仅支持模拟器")
    return ShopRefreshStateMachine(
        1,
        observer=build_shop_refresh_observer(template_root),
    )


def _probe_arena_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """竞技场接力探针：认出用户停在哪一步就返回落点（并把状态机拨过去）。

    命中即接管 —— 调用方看到非 None 就不再执行「回大厅 → 按路线导航」，
    直接让状态机从这一步接着往下跑（停在准备战斗就直接打，不再退回列表重选）。
    认不出来返回 None，调用方原样走老的导航流程（失败关闭）。
    """
    observed = navigator.observe(screen).name if navigator is not None else None
    found = detect_resume_point(machine, screen, observed_page=observed)
    if found is None:
        return None
    if found.state is not None:
        machine.resume_from(found.state)
    return ResumePoint(
        page=found.page,
        state=found.state.value if found.state is not None else None,
        entry=found.entry,
    )


def _probe_story_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """主线接力探针：认出用户停在哪一步就返回落点（并把状态机拨过去）。

    主线几乎每一页（关卡入口/队伍准备/助手选择/剧情播放/跳过确认/结算/通关提示/
    额外奖励）都有可确认的锚点，所以能接力的点比竞技场多得多；局内走
    ``battle_scene_visible``。

    与竞技场的唯一差别：这里**必须**先把状态拨对。主线 ``next_action`` 里有两支
    依赖进来时的状态才肯点击（``prepare_battle`` 在 WAIT_COMPLETE/WAIT_NEXT_STAGE
    下只记轮次不点；战斗控件分支只在 WAIT_SKIP_CONFIRM/WAIT_BATTLE/ACTIVE 下跑），
    拨错会让 Runner 原地干等到超时，而不是自愈。
    """
    observed = navigator.observe(screen).name if navigator is not None else None
    found = detect_story_resume_point(machine, screen, observed_page=observed)
    if found is None:
        return None
    if found.state is not None:
        machine.resume_from(found.state)
    return ResumePoint(
        page=found.page,
        state=found.state.value if found.state is not None else None,
        entry=found.entry,
    )


def _probe_expedition_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """远征接力探针：认出用户停在哪一步就返回落点（并把状态机拨过去）。

    远征的 ``next_action`` 是纯状态驱动的，状态拨错不会自愈（会走到 ``_required``
    失败或点错按钮），所以这里命中即接管、必须把状态一起拨好。
    """
    observed = navigator.observe(screen).name if navigator is not None else None
    found = detect_expedition_resume_point(machine, screen, observed_page=observed)
    if found is None:
        return None
    if found.state is not None:
        machine.resume_from(found.state)
    return ResumePoint(
        page=found.page,
        state=found.state.value if found.state is not None else None,
        entry=found.entry,
    )


def _probe_shop_refresh_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """刷书签接力探针：认出「人已经停在秘密商店页」就就地接管。

    这条路线的可停靠画面只有一张 —— 整轮都待在同一张秘密商店页上刷，所以探针
    命中后**不拨状态**（phase 是内部阶段，起始恒为 SCAN_TOP），只给状态机打个
    ``mark_resumed_at_shop()`` 记号：Runner 据此先把列表拨回顶部再开扫，免得人
    停在列表半截时被当成「顶部批次」。

    判据自带走观察器（与导航器的「秘密商店」页面识别同源），所以用不到导航器。
    """
    del navigator
    found = detect_shop_resume_point(machine, screen)
    if found is None:
        return None
    machine.mark_resumed_at_shop()
    return ResumePoint(page=found.page, state=found.state, entry=found.entry)


def _probe_knights_donation_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """骑士团捐赠接力探针：认出人停在骑士团哪一页就就地接管。

    判据直接用状态机自己的 ``observe_page`` —— 与运行期**同源**，不另定阈值、不加新锚点。
    停在大厅时认不出（``activity_entry`` 在骑士团主页上，大厅上不成立）⇒ 返回 None，
    照旧走「回大厅 → 进骑士团」。

    能落脚的只有三页（骑士团主页 / 资源支援 / 每周任务），**三个弹窗与活动界面兜底页
    刻意不接**，理由写在 ``knights_donation._RESUMABLE_STATES`` 上方。
    """
    del navigator
    found = detect_knights_donation_resume_point(machine, screen)
    if found is None:
        return None
    return ResumePoint(page=found.page, state=found.state, entry=found.entry)


def _probe_world_boss_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """世界首领战接力探针：认出人停在世界首领战哪一页就就地接管。

    判据直接用状态机自己的 ``observe_page`` —— 与运行期**同源**，不另定阈值、不加新锚点。
    停在大厅 / 别的路线上认不出 ⇒ 返回 None，照旧走「回大厅 → 进骑士团 → 世界首领战」。

    能落脚的页面（主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励 / 战斗中），
    以及骑士团主页这个**导航链中间站**，都由 ``detect_resume_point`` 定；
    结算页的歧义与三个不接力的理由写在那边。

    命中后必须把状态拨过去 —— 不是为了让页面判得准（``next_action`` 每页都会现判），
    而是为了让 ``WorldBossRunner`` 拿到 ``resumed_from``：停在局内时要靠它跳过状态机、
    直接把这一局交给战斗监督，不能按 Back 回大厅。
    """
    del navigator
    found = detect_world_boss_resume_point(machine, screen)
    if found is None:
        return None
    if found.state is not None:
        machine.resume_from(found.state)
    return ResumePoint(
        page=found.page,
        state=found.state.value if found.state is not None else None,
        entry=found.entry,
    )


def _build_survivor(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> SurvivorStateMachine:
    # 整轮循环都在活动小游戏内部，起点固定是用户人工停好的「选第一张卡」页，
    # 所以只允许这一个起始状态。
    if state != SurvivorState.CARD.value:
        raise ValueError(f"幸存者起始状态无效：{state}")
    if backend != "emulator":
        raise ValueError("幸存者当前仅支持模拟器")
    return SurvivorStateMachine(
        observer=build_survivor_observer(template_root),
    )


def _probe_labyrinth_stone_resume(
    machine: Any,
    screen: np.ndarray,
    navigator: Any,
) -> Optional[ResumePoint]:
    """迷宫强化石接力探针：认出人停在哪一页就就地接管。

    判据直接用状态机自己的 ``observe_page`` —— 与运行期**同源**。
    停在「已经进过迷宫」的那几页时，``detect_resume_point`` 会顺手把
    ``entered`` 拨对（否则回到详情页会被当成还没进场、又点一次「选择队伍」）。
    停在大厅上返回 None —— 那是这条路线的**终点**，认不出才对。
    """
    del navigator
    found = detect_labyrinth_stone_resume_point(machine, screen)
    if found is None:
        return None
    return ResumePoint(page=found.page, state=found.state, entry=found.entry)


def _build_world_boss(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> WorldBossStateMachine:
    return WorldBossStateMachine(
        template_root / "world_boss",
        initial_state=WorldBossState(state),
        backend=backend,
    )


def _build_labyrinth_stone(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> LabyrinthStoneStateMachine:
    # 模板子目录是 templates/labyrinth_stone；工厂必须把它当根，不能当 templates 根。
    return LabyrinthStoneStateMachine(
        template_root / "labyrinth_stone",
        initial_state=LabyrinthStoneState(state),
        backend=backend,
    )


def _build_knights_donation(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> KnightsDonationStateMachine:
    # 模板子目录是 templates/knights_donation；工厂必须把它当根，不能当 templates 根。
    return KnightsDonationStateMachine(
        template_root / "knights_donation",
        initial_state=KnightsDonationState(state),
        backend=backend,
    )


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
        default_state=ArenaState.LIST.value,
        states=frozenset(state.value for state in ArenaState),
        build_machine=_build_arena,
        runner_type=ArenaRunner,
        # 开局不无脑回大厅：先看一眼停在哪一步，停在对战详情/准备战斗/对手列表
        # 就直接从那一步接着跑；停在别的支线页面才退回原来的「一直返回」流程。
        resume_probe=_probe_arena_resume,
    ),
    "story": ModeSpec(
        name="story",
        default_state=StoryState.STAGE.value,
        states=frozenset(state.value for state in StoryState),
        build_machine=_build_story,
        runner_type=StoryRunner,
        # 开局不无脑回大厅：先看停在主线哪一步。关卡入口直接接管，队伍准备/战斗中
        # 就接着打，结算/通关提示/额外奖励就接着收奖励（这几页回大厅会白丢奖励）。
        resume_probe=_probe_story_resume,
    ),
    "expedition": ModeSpec(
        name="expedition",
        default_state=ExpeditionState.HOME.value,
        states=frozenset(state.value for state in ExpeditionState),
        build_machine=_build_expedition,
        runner_type=ExpeditionRunner,
        # 开局不无脑回大厅：导航链四级（战斗菜单/赛季菜单/远征主页）都开放接力，
        # 业务页从通缉传单一路到公开招募也都接得住。
        resume_probe=_probe_expedition_resume,
    ),
    "fodder": ModeSpec(
        name="fodder",
        default_state=FodderState.STAGE.value,
        states=frozenset(state.value for state in FodderState),
        build_machine=_build_fodder,
        runner_type=FodderRunner,
    ),
    "hero_synthesis": ModeSpec(
        name="hero_synthesis",
        default_state=HeroSynthState.HERO_LIST.value,
        states=frozenset(state.value for state in HeroSynthState),
        build_machine=_build_hero_synthesis,
        runner_type=HeroSynthRunner,
    ),
    "shop_refresh": ModeSpec(
        name="shop_refresh",
        default_state=ShopPhase.SCAN_TOP.value,
        states=frozenset({ShopPhase.SCAN_TOP.value}),
        build_machine=_build_shop_refresh,
        runner_type=ShopRefreshRunner,
        # 开局不无脑回大厅：先看一眼是不是已经站在秘密商店页上 —— 是的话就地接管
        # （回大厅会白走一趟「大厅 → 秘密商店」导航，中间还可能被别的弹窗截住）。
        # 判据是三个锚点（商店标题 + 立即更新 + 购买按钮）同时过阈，不是「像商店」。
        resume_probe=_probe_shop_refresh_resume,
        supported_backends=frozenset({"emulator"}),
    ),
    "survivor": ModeSpec(
        name="survivor",
        default_state=SurvivorState.CARD.value,
        states=frozenset({SurvivorState.CARD.value}),
        build_machine=_build_survivor,
        runner_type=SurvivorRunner,
        # 起点是用户人工推进到的活动小游戏内部页面，不需要从大厅导航过来，
        # 出问题时也不做任何「回大厅」动作（Back 会退回活动主页那个未知状态）。
        needs_navigation=False,
        supported_backends=frozenset({"emulator"}),
    ),
    "world_boss": ModeSpec(
        name="world_boss",
        default_state=WorldBossState.HOME.value,
        states=frozenset(state.value for state in WorldBossState),
        build_machine=_build_world_boss,
        runner_type=WorldBossRunner,
        # 开局不无脑回大厅：主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励
        # 就地从那一步接着跑，停在局内则把这一局打完再说。骑士团主页这个导航链
        # 中间站也接（省掉「回大厅 → 进骑士团」两级）。
        resume_probe=_probe_world_boss_resume,
    ),
    "knights_donation": ModeSpec(
        name="knights_donation",
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
        # 开局不无脑回大厅：停在骑士团主页 / 资源支援列表 / 每周任务上就地接管。
        # 三个弹窗与活动界面兜底页不接（不可逆 / 判据不排他 / 无正例），
        # 见 knights_donation._RESUMABLE_STATES 上方的理由。
        resume_probe=_probe_knights_donation_resume,
    ),
    "labyrinth_stone": ModeSpec(
        name="labyrinth_stone",
        # 导航把画面停在战斗菜单（「一般」页），第一步就是点迷宫卡片。
        default_state=LabyrinthStoneState.BATTLE_MENU.value,
        states=frozenset(
            state.value
            for state in LabyrinthStoneState
            if state is not LabyrinthStoneState.FINISHED
        ),
        build_machine=_build_labyrinth_stone,
        runner_type=LabyrinthStoneRunner,
        # 开局不无脑回大厅：停在战斗菜单 / 迷宫列表 / 详情页 / 准备战斗页时接着往里走，
        # 停在迷宫里 / 暂停菜单 / 放弃确认框 / 快捷菜单时接着往外走。
        resume_probe=_probe_labyrinth_stone_resume,
    ),
}


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
