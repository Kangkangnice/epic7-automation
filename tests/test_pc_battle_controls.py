from pathlib import Path

import cv2

from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7.story import (
    StoryState,
    StoryStateMachine,
    build_story_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "epic7_pc_story" / "battle_auto_on.png"
SKILL_ANIMATION = (
    ROOT / "tests" / "fixtures" / "epic7_pc_story" / "battle_skill_animation.png"
)
MANUAL_BATTLE = ROOT / "tests" / "fixtures" / "epic7_pc_story" / "battle_manual.png"
PC_STORY_TEMPLATES = ROOT / "games" / "epic7" / "templates_pc" / "story"


def test_pc_auto_battle_hud_is_recognized():
    image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert image is not None
    screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    assert observe_battle_controls(screen) is BattleControls.AUTO_CONTROLS


def test_pc_skill_animation_is_not_mistaken_for_stable_auto_battle():
    image = cv2.imread(str(SKILL_ANIMATION), cv2.IMREAD_COLOR)
    assert image is not None
    screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    assert observe_battle_controls(screen) is BattleControls.TRANSITION


def test_pc_manual_battle_hud_is_recognized():
    image = cv2.imread(str(MANUAL_BATTLE), cv2.IMREAD_COLOR)
    assert image is not None
    screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    assert observe_battle_controls(screen) is BattleControls.MANUAL_CONTROLS


def test_pc_manual_battle_enables_auto_from_the_auto_icon():
    image = cv2.imread(str(MANUAL_BATTLE), cv2.IMREAD_COLOR)
    assert image is not None
    screen = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    machine = StoryStateMachine(
        build_story_templates(PC_STORY_TEMPLATES),
        initial_state=StoryState.WAIT_BATTLE,
    )

    action = machine.next_action(screen)

    assert action.name == "enable_auto"
    assert action.point == (1745, 50)


def test_pc_auto_battle_confirmation_does_not_click_auto_twice():
    manual_image = cv2.imread(str(MANUAL_BATTLE), cv2.IMREAD_COLOR)
    auto_image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert manual_image is not None
    assert auto_image is not None
    manual_screen = cv2.cvtColor(manual_image, cv2.COLOR_BGR2RGB)
    auto_screen = cv2.cvtColor(auto_image, cv2.COLOR_BGR2RGB)
    machine = StoryStateMachine(
        build_story_templates(PC_STORY_TEMPLATES),
        initial_state=StoryState.WAIT_BATTLE,
    )

    first = machine.next_action(manual_screen)
    second = machine.next_action(auto_screen)

    assert first.name == "enable_auto"
    assert second is None
    assert machine.auto_enabled is True
