from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.story import (
    StoryRunner,
    StoryState,
    StoryStateMachine,
    build_story_templates,
)
from auto_game_unified.games.epic7.expedition import (
    ExpeditionRunner,
    ExpeditionState,
    ExpeditionStateMachine,
)
from auto_game_unified.games.epic7.fodder import (
    FodderRunner,
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)
from auto_game_unified.games.epic7.assist_auto import (
    AssistAutoRunner,
    AssistAutoState,
    AssistAutoStateMachine,
    build_assist_auto_templates,
)
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)


MachineFactory = Callable[[Path, str, str], Any]


@dataclass(frozen=True)
class ModeSpec:
    name: str
    default_state: str
    states: frozenset[str]
    build_machine: MachineFactory
    runner_type: type
    needs_navigation: bool = True

    def resolve_state(self, requested: str | None) -> str:
        state = requested or self.default_state
        if state not in self.states:
            choices = ", ".join(sorted(self.states))
            raise ValueError(f"起始状态 {state!r} 不适用于模式 {self.name}；可选：{choices}")
        return state


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


def _build_assist_auto(
    template_root: Path,
    state: str,
    backend: str = "emulator",
) -> AssistAutoStateMachine:
    return AssistAutoStateMachine(
        build_assist_auto_templates(template_root / "assist_auto"),
        initial_state=AssistAutoState(state),
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


MODE_SPECS = {
    "arena": ModeSpec(
        name="arena",
        default_state=ArenaState.LIST.value,
        states=frozenset(state.value for state in ArenaState),
        build_machine=_build_arena,
        runner_type=ArenaRunner,
    ),
    "story": ModeSpec(
        name="story",
        default_state=StoryState.STAGE.value,
        states=frozenset(state.value for state in StoryState),
        build_machine=_build_story,
        runner_type=StoryRunner,
    ),
    "expedition": ModeSpec(
        name="expedition",
        default_state=ExpeditionState.HOME.value,
        states=frozenset(state.value for state in ExpeditionState),
        build_machine=_build_expedition,
        runner_type=ExpeditionRunner,
    ),
    "fodder": ModeSpec(
        name="fodder",
        default_state=FodderState.STAGE.value,
        states=frozenset(state.value for state in FodderState),
        build_machine=_build_fodder,
        runner_type=FodderRunner,
    ),
    "assist_auto": ModeSpec(
        name="assist_auto",
        default_state=AssistAutoState.TEAM.value,
        states=frozenset(state.value for state in AssistAutoState),
        build_machine=_build_assist_auto,
        runner_type=AssistAutoRunner,
        needs_navigation=False,
    ),
    "hero_synthesis": ModeSpec(
        name="hero_synthesis",
        default_state=HeroSynthState.HERO_LIST.value,
        states=frozenset(state.value for state in HeroSynthState),
        build_machine=_build_hero_synthesis,
        runner_type=HeroSynthRunner,
    ),
}


def get_mode(name: str) -> ModeSpec:
    return MODE_SPECS[name]
