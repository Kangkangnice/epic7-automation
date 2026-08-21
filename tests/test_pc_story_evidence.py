from pathlib import Path

import cv2

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates
from auto_game_unified.games.epic7.story import (
    StoryState,
    StoryStateMachine,
    build_story_templates,
    find_prepare_battle_button,
)


ROOT = Path(__file__).resolve().parents[1]
PC_TEMPLATES = ROOT / "games" / "epic7" / "templates_pc" / "story"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_pc_story"


def _load_rgb(path: Path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None, path
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def test_pc_story_stage_entry_matches_prepare_battle_button():
    templates = build_story_templates(PC_TEMPLATES)

    match = find_prepare_battle_button(
        _load_rgb(FIXTURES / "stage_entry.png"),
        templates.prepare_battle,
        templates.prepare_battle_updated,
    )

    assert match is not None
    assert match.score >= 0.90


def test_pc_next_stage_matches_prepare_battle_button():
    templates = build_story_templates(PC_TEMPLATES)

    match = find_prepare_battle_button(
        _load_rgb(FIXTURES / "next_stage.png"),
        templates.prepare_battle,
        templates.prepare_battle_updated,
    )

    assert match is not None
    assert match.score >= 0.90


def test_pc_live_navigation_recovery_stage_matches_prepare_battle_button():
    templates = build_story_templates(PC_TEMPLATES)
    screen = _load_rgb(FIXTURES / "live_test_navigation_blocked.png")

    match = find_prepare_battle_button(
        screen,
        templates.prepare_battle,
        templates.prepare_battle_updated,
    )

    assert match is not None
    assert match.score >= 0.90
    navigator = Epic7Navigator(
        build_navigation_templates(ROOT / "games" / "epic7" / "templates_pc"),
        Runtime(lambda: screen, lambda _point: None),
    )
    assert navigator.observe(screen).name == "story_ready"
    story_back = navigator._locate(screen, "story_back", 0.90)
    assert story_back is not None
    assert story_back.center[1] <= 55


def test_pc_lobby_is_not_mistaken_for_prepare_battle():
    templates = build_story_templates(PC_TEMPLATES)

    match = find_prepare_battle_button(
        _load_rgb(FIXTURES / "lobby.png"),
        templates.prepare_battle,
        templates.prepare_battle_updated,
    )

    assert match is None


def test_pc_lobby_story_card_uses_the_verified_click_center():
    screen = _load_rgb(FIXTURES / "live_test_lobby_after_story_click.png")
    navigator = Epic7Navigator(
        build_navigation_templates(ROOT / "games" / "epic7" / "templates_pc"),
        Runtime(lambda: screen, lambda _point: None),
    )

    match = navigator._locate(screen, "lobby_story", 0.80)

    assert match is not None
    offset = navigator._click_offset("lobby_story")
    assert (match.center[0] + offset[0], match.center[1] + offset[1]) == (1810, 300)


def test_pc_story_stage_entry_is_recognized_by_navigation():
    screen = _load_rgb(FIXTURES / "stage_entry.png")
    runtime = Runtime(lambda: screen, lambda _point: None)
    navigator = Epic7Navigator(
        build_navigation_templates(ROOT / "games" / "epic7" / "templates_pc"),
        runtime,
    )

    observation = navigator.observe(screen)

    assert observation.name == "story_ready"
    assert observation.confidence >= 0.90


def test_pc_support_hero_page_advances_to_team_selection():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "team_select.png"))

    assert action.name == "select_team"
    assert action.point == (1680, 1032)


def test_pc_team_formation_page_starts_mission():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "team_formation.png"))

    assert action.name == "start_mission"
    assert action.point == (1770, 1038)


def test_pc_live_team_formation_matches_start_mission_despite_changed_stamina():
    machine = StoryStateMachine(
        build_story_templates(PC_TEMPLATES), initial_state=StoryState.TEAM
    )

    action = machine.next_action(_load_rgb(FIXTURES / "current_live_screen.png"))

    assert action.name == "start_mission"


def test_pc_story_page_requests_skip():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "story_skip.png"))

    assert action.name == "skip"
    assert action.point == (1875, 57)


def test_pc_live_story_skip_uses_the_verified_button_center():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "live_test_skip_failure.png"))

    assert action.name == "skip"
    assert action.point == (1875, 57)


def test_pc_story_skip_confirmation_is_accepted():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "skip_confirm.png"))

    assert action.name == "skip_confirm"
    assert action.point == (1150, 750)


def test_pc_clear_screen_advances_to_results():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "clear.png"))

    assert action.name == "clear"
    assert action.point == (995, 715)


def test_pc_results_page_confirms_rewards():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "results.png"))

    assert action.name == "results_confirm"
    assert action.point == (1750, 1050)


def test_pc_story_completion_popup_closes_from_its_close_hint():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "complete.png"))

    assert action.name == "complete"
    assert action.point == (990, 770)


def test_pc_bonus_reward_popup_closes_from_its_reward_anchor():
    machine = StoryStateMachine(build_story_templates(PC_TEMPLATES))

    action = machine.next_action(_load_rgb(FIXTURES / "next_state.png"))

    assert action.name == "bonus_reward"
    assert action.point == (990, 874)
