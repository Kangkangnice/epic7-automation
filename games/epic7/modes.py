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


MachineFactory = Callable[[Path, str], Any]


@dataclass(frozen=True)
class ModeSpec:
    name: str
    default_state: str
    states: frozenset[str]
    build_machine: MachineFactory
    runner_type: type

    def resolve_state(self, requested: str | None) -> str:
        state = requested or self.default_state
        if state not in self.states:
            choices = ", ".join(sorted(self.states))
            raise ValueError(f"start state {state!r} is not valid for {self.name}; choose: {choices}")
        return state


def _build_arena(template_root: Path, state: str) -> ArenaStateMachine:
    return ArenaStateMachine(
        build_templates(template_root), initial_state=ArenaState(state)
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
}


def get_mode(name: str) -> ModeSpec:
    return MODE_SPECS[name]
