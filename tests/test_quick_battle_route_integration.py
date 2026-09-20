from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState

from auto_game_unified.games.epic7.arena import (
    ArenaState,
    ArenaStateMachine,
    build_templates,
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


def test_story_wide_quick_page_switches_back_to_normal_battle():
    """主线队伍准备页（PC）的快速战斗版：宽按钮 0.7341 过不了阈，只有右侧切换控件
    0.9883 能认出来。这条守住「主线遇到它就跟竞技场一样切回普通战斗」——
    2026-09-18 15:34 实跑就是在这里把开始按钮连点 4 次、无进展后安全停止的。
    """
    quick = fixture("epic7_story", "team_quick_battle_live_20260918")
    machine = StoryStateMachine(
        build_story_templates(TEMPLATES / "story"), initial_state=StoryState.TEAM
    )

    observation = machine.observe_battle(quick, None)
    assert observation.pre_battle_visible is True
    assert observation.allowed_action is not None
    assert observation.allowed_action[0] == "switch-to-normal-battle"
    switch_x, switch_y = observation.allowed_action[1]
    assert 1800 <= switch_x <= 1930
    assert 995 <= switch_y <= 1100

    action = machine.next_action(quick)
    assert action is not None
    assert action.name == "switch_to_normal_battle"
    assert action.point == observation.allowed_action[1]
    assert machine.state is StoryState.TEAM
    assert action.target_states == (StoryState.TEAM,)


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
            "switch_to_normal_battle",
            StoryState.TEAM,
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
            assert action.target_states
        elif isinstance(machine, ExpeditionStateMachine):
            assert machine.state is ExpeditionState.TEAM
            assert action.target_states == (ExpeditionState.BATTLE,)
        elif isinstance(machine, StoryStateMachine):
            assert machine.state is StoryState.TEAM
            assert action.target_states == (StoryState.TEAM,)
        else:
            assert machine.state is target_state


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
    machine = StoryStateMachine(
        build_story_templates(TEMPLATES / "story", backend="pc"),
        backend="pc",
    )
    observation = machine.observe_battle(
        fixture(
            "epic7_arena",
            "battle_auto_off_enemy_turn_live_20260826",
        ),
        None,
    )

    assert observation.auto_state is AutoBattleState.UNKNOWN


def test_pc_arena_and_expedition_do_not_enable_simulator_auto_off_source_rule():
    screen = fixture(
        "epic7_arena",
        "battle_auto_off_enemy_turn_live_20260826",
    )
    machines = (
        ArenaStateMachine(
            build_templates(TEMPLATES, backend="pc"),
            backend="pc",
        ),
        ExpeditionStateMachine(
            TEMPLATES / "expedition",
            backend="pc",
        ),
    )

    for machine in machines:
        observation = machine.observe_battle(screen, None)
        assert observation.auto_state is AutoBattleState.UNKNOWN
