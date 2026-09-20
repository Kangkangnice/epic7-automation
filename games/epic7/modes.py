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
        # 也不做回大厅恢复（Back 会退回活动主页那个未知状态）。
        needs_navigation=False,
        supported_backends=frozenset({"emulator"}),
    ),
}


def get_mode(name: str) -> ModeSpec:
    return MODE_SPECS[name]
