from pathlib import Path

import cv2

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation
from auto_game_unified.games.epic7.hero_synthesis import (
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    build_hero_templates,
)
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
PC_TEMPLATES = ROOT / "games" / "epic7" / "templates_pc"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_pc_hero"


def fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


def machine(*, filter_verified=False, state=HeroSynthState.HERO_LIST):
    value = HeroSynthStateMachine(build_hero_templates(PC_TEMPLATES), state)
    value.filter_verified = filter_verified
    return value


def settled_next(value, screen):
    return value.next_action(screen) or value.next_action(screen)


def test_pc_filter_open_selects_star3():
    action = machine().next_action(fixture("03_filter_open"))
    assert (action.name, action.point) == ("select_star3", (1148, 613))


def test_pc_filter_with_star3_selected_closes():
    action = machine().next_action(fixture("04_filter_star3_selected"))
    assert (action.name, action.point) == ("close_filter", (1612, 141))


def test_pc_filter_with_current_selected_star3_evidence_closes():
    action = machine().next_action(
        fixture("21_live_filter_star3_selected_confirmed")
    )
    assert (action.name, action.point) == ("close_filter", (1612, 141))


def test_pc_filter_does_not_reopen_before_star3_selection_is_confirmed():
    value = machine()
    assert value.next_action(fixture("03_filter_open")).name == "select_star3"

    assert value.next_action(fixture("05_star3_list")) is None


def test_pc_preview_does_not_commit_star3_selection_request():
    value = machine()

    action, _ = value.preview(fixture("03_filter_open"))

    assert action.name == "select_star3"
    assert value._awaiting_star3_confirmation is False


def test_pc_selected_star3_closes_when_level_anchor_is_missed():
    screen = fixture("17_live_filter_star3_selected")
    screen[522:564, 676:748] = 0
    action = machine().next_action(screen)
    assert (action.name, action.point) == ("close_filter", (1612, 141))


def test_pc_list_without_red_dot_advances():
    action = settled_next(machine(filter_verified=True), fixture("05_star3_list"))
    assert action.name.startswith("next_card_")
    assert action.point == (1710, 570)


def test_pc_runner_commits_next_card_after_two_matching_previews():
    runner = HeroSynthRunner(
        machine(filter_verified=True),
        Runtime(lambda: fixture("05_star3_list"), lambda _: None),
        sleep=lambda _: None,
    )
    runner._needs_navigation_settle = False
    stable = StableObservation(required=2)

    first = runner._stable_next_action(fixture("05_star3_list"), stable)
    second = runner._stable_next_action(fixture("05_star3_list"), stable)

    assert first.__class__.__name__ == "_NotStable"
    assert second.name.startswith("next_card_")
    assert second.point == (1710, 570)


def test_pc_list_red_dot_opens_imprint():
    action = machine(filter_verified=True).next_action(fixture("06_next_card_01"))
    assert (action.name, action.point) == ("open_imprint", (1115, 990))


def test_pc_imprint_without_up_starts_synthesis_at_button_center():
    value = machine(filter_verified=True, state=HeroSynthState.IMPRINT_ADD)
    action = value.next_action(fixture("09_imprint_all_materials"))
    assert (action.name, action.point) == ("start_synthesis", (1200, 1041))


def test_pc_confirmation_click_is_inside_live_confirm_button():
    action = machine().next_action(fixture("10_synthesis_confirm"))
    assert action.name == "confirm_synthesis"
    assert 1005 <= action.point[0] <= 1311
    assert 676 <= action.point[1] <= 771


def test_pc_completed_imprint_uses_live_back_arrow_center():
    value = machine(filter_verified=True, state=HeroSynthState.IMPRINT_CONFIRM)
    action = value.next_action(fixture("13_imprint_result_closed"))
    assert (action.name, action.point) == ("back_to_list", (66, 50))


def test_pc_navigation_recognizes_live_hero_list():
    navigator = Epic7Navigator(
        build_navigation_templates(PC_TEMPLATES), Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )
    observation = navigator.observe(fixture("05_star3_list"))
    assert observation.name == "hero_list"
    assert observation.confidence >= 0.80


def test_pc_navigation_recognizes_current_lobby_with_battle_anchor():
    navigator = Epic7Navigator(
        build_navigation_templates(PC_TEMPLATES), Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )

    observation = navigator.observe(fixture("29_live_lobby_before_hero_run"))

    assert observation.name == "lobby"
    assert observation.confidence >= 0.80


def test_pc_navigation_recognizes_hero_equipment_subpage():
    navigator = Epic7Navigator(
        build_navigation_templates(PC_TEMPLATES), Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )

    observation = navigator.observe(fixture("32_live_hero_equipment_tab"))

    assert observation.name == "hero_equipment"
    assert observation.confidence >= 0.80


def test_pc_navigation_switches_hero_equipment_subpage_to_hero_list():
    screens = iter(
        [
            fixture("32_live_hero_equipment_tab"),
            fixture("32_live_hero_equipment_tab"),
            fixture("33_hero_detail_tab_after_switch"),
            fixture("33_hero_detail_tab_after_switch"),
        ]
    )
    clicks = []
    navigator = Epic7Navigator(
        build_navigation_templates(PC_TEMPLATES),
        Runtime(lambda: next(screens), clicks.append),
        sleep=lambda _: None,
        transition_frames=4,
    )

    navigator.navigate("hero_synthesis", lobby_screen=fixture("29_live_lobby_before_hero_run"))

    assert clicks == [(1490, 1045), (65, 150)]


def test_pc_runner_waits_before_its_first_hero_action():
    waits = []
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: fixture("05_star3_list"), lambda _: None),
        sleep=waits.append,
    )

    runner._stable_next_action(
        fixture("05_star3_list"), StableObservation(required=1)
    )

    assert waits == [3]
