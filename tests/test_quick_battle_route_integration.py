from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState

from auto_game_unified.games.epic7.arena import (
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.assist_auto import (
    AssistAutoState,
    AssistAutoStateMachine,
    build_assist_auto_templates,
)
from auto_game_unified.games.epic7.expedition import (
    ExpeditionState,
    ExpeditionStateMachine,
)
from auto_game_unified.games.epic7.fodder import (
    FodderState,
    FodderStateMachine,
    build_fodder_templates,
)
from auto_game_unified.games.epic7.story import (
    StoryState,
    StoryStateMachine,
    build_story_templates,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(group: str, name: str) -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / group / f"{name}.png"
    return np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]


def test_quick_page_is_a_shared_pre_battle_action_for_supervised_routes():
    quick = fixture("epic7_arena", "quick_battle_selected_live_20260826")
    machines = (
        ArenaStateMachine(build_templates(TEMPLATES)),
        StoryStateMachine(build_story_templates(TEMPLATES / "story")),
        FodderStateMachine(build_fodder_templates(TEMPLATES / "fodder")),
        ExpeditionStateMachine(TEMPLATES / "expedition"),
    )

    for machine in machines:
        observation = machine.observe_battle(quick, None)
        assert observation.pre_battle_visible is True
        assert observation.allowed_action is not None
        assert observation.allowed_action[0] == "switch-to-normal-battle"
        x, y = observation.allowed_action[1]
        assert 1380 <= x <= 1490
        assert 995 <= y <= 1100


def test_normal_pages_keep_each_route_start_action():
    cases = (
        (
            ArenaStateMachine(build_templates(TEMPLATES)),
            fixture("epic7_arena", "normal_battle_ready_live_20260826"),
            "battle-start",
        ),
        (
            StoryStateMachine(build_story_templates(TEMPLATES / "story")),
            fixture("epic7_story", "team"),
            "start_mission",
        ),
        (
            FodderStateMachine(build_fodder_templates(TEMPLATES / "fodder")),
            fixture("epic7_fodder", "team"),
            "start_battle",
        ),
        (
            ExpeditionStateMachine(TEMPLATES / "expedition"),
            fixture("epic7_expedition", "team"),
            "battle-start",
        ),
    )

    for machine, screen, action_name in cases:
        observation = machine.observe_battle(screen, None)
        assert observation.pre_battle_visible is True
        assert observation.allowed_action is not None
        assert observation.allowed_action[0] == action_name


def test_supervised_route_state_machines_enter_supervision_from_quick_page():
    quick = fixture("epic7_arena", "quick_battle_selected_live_20260826")
    cases = (
        (
            ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.TEAM),
            "battle-start",
            ArenaState.BATTLE,
        ),
        (
            StoryStateMachine(
                build_story_templates(TEMPLATES / "story"),
                initial_state=StoryState.TEAM,
            ),
            "start_mission",
            StoryState.WAIT_BATTLE,
        ),
        (
            FodderStateMachine(
                build_fodder_templates(TEMPLATES / "fodder"),
                initial_state=FodderState.TEAM,
            ),
            "start_battle",
            FodderState.BATTLE,
        ),
        (
            ExpeditionStateMachine(
                TEMPLATES / "expedition",
                initial_state=ExpeditionState.TEAM,
            ),
            "battle-start",
            ExpeditionState.BATTLE,
        ),
    )

    for machine, action_name, target_state in cases:
        action = machine.next_action(quick)
        assert action is not None
        assert action.name == action_name
        if isinstance(machine, ArenaStateMachine):
            assert machine.state is ArenaState.TEAM
            assert action.target_states == (ArenaState.BATTLE,)
        else:
            assert machine.state is target_state


def test_assist_auto_switches_quick_mode_without_advancing_team_state():
    machine = AssistAutoStateMachine(
        build_assist_auto_templates(TEMPLATES / "assist_auto")
    )

    action = machine.next_action(
        fixture("epic7_arena", "quick_battle_selected_live_20260826")
    )

    assert action.name == "switch-to-normal-battle"
    assert machine.state is AssistAutoState.TEAM


def test_simulator_routes_use_auto_off_icon_before_player_skill_turn():
    screen = fixture(
        "epic7_arena",
        "battle_auto_off_enemy_turn_live_20260826",
    )
    machines = (
        ArenaStateMachine(build_templates(TEMPLATES)),
        StoryStateMachine(build_story_templates(TEMPLATES / "story")),
        ExpeditionStateMachine(TEMPLATES / "expedition"),
    )

    for machine in machines:
        observation = machine.observe_battle(screen, None)
        assert observation.auto_state is AutoBattleState.MANUAL
        assert observation.auto_point is not None


def test_pc_story_does_not_enable_simulator_auto_off_source_rule():
    simulator_templates = build_story_templates(TEMPLATES / "story")
    machine = StoryStateMachine(
        replace(simulator_templates, quick_battle=None)
    )
    observation = machine.observe_battle(
        fixture(
            "epic7_arena",
            "battle_auto_off_enemy_turn_live_20260826",
        ),
        None,
    )

    assert observation.auto_state is AutoBattleState.UNKNOWN
