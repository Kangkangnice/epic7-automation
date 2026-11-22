"""主线「剧情过场」状态：点完跳过确认之后的那段无 UI 演出。

合成帧口径：全黑 1982×1132 = 画面上没有任何可识别 UI；在 skip 搜索区内贴上
``templates/story/skip.png`` = 演出中跳过按钮重新出现。两种帧都不改任何阈值。
"""
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7 import activity_story, side_story, story_star
from auto_game_unified.games.epic7.story import (
    StoryRunner,
    StoryState,
    StoryStateMachine,
    build_story_templates,
    state_label,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"
REFERENCE_SIZE = (1982, 1132)
SKIP_PASTE_POINT = (1720, 20)  # 落在 STORY_SKIP_REGION=(1700,0,240,200) 内


def blank_frame() -> np.ndarray:
    return np.zeros((REFERENCE_SIZE[1], REFERENCE_SIZE[0], 3), dtype=np.uint8)


def skip_frame() -> np.ndarray:
    frame = blank_frame()
    template = np.asarray(Image.open(TEMPLATES / "skip.png").convert("RGB"))
    x, y = SKIP_PASTE_POINT
    height, width = template.shape[:2]
    frame[y : y + height, x : x + width] = template
    return frame


def make_machine(*, story_cutscene: bool) -> StoryStateMachine:
    return StoryStateMachine(
        build_story_templates(TEMPLATES),
        initial_state=StoryState.WAIT_SKIP_CONFIRM,
        story_cutscene=story_cutscene,
    )


class StoryCutsceneTests(unittest.TestCase):
    def test_enabled_machine_waits_in_cutscene_without_action(self):
        machine = make_machine(story_cutscene=True)

        action = machine.next_action(blank_frame())

        self.assertIsNone(action)
        self.assertIs(machine.state, StoryState.STORY_CUTSCENE)
        self.assertEqual(state_label(machine.state), "剧情过场")

    def test_skip_reappearing_during_cutscene_goes_back_to_active(self):
        machine = make_machine(story_cutscene=True)
        self.assertIsNone(machine.next_action(blank_frame()))

        action = machine.next_action(skip_frame())

        self.assertIsNotNone(action)
        self.assertEqual(action.name, "skip")
        self.assertIs(machine.state, StoryState.ACTIVE)

    def test_disabled_machine_still_rejects_the_same_frame(self):
        machine = make_machine(story_cutscene=False)

        with self.assertRaises(UnrecognizedScreen):
            machine.next_action(blank_frame())
        self.assertIs(machine.state, StoryState.WAIT_SKIP_CONFIRM)

    def test_story_timeout_table_keeps_all_previous_values(self):
        expected = {
            StoryState.STAGE: 45,
            StoryState.TEAM: 45,
            StoryState.WAIT_SKIP_CONFIRM: 45,
            StoryState.STORY_CUTSCENE: 180,
            StoryState.WAIT_BATTLE: 60,
            StoryState.ACTIVE: 120,
            StoryState.WAIT_RESULTS: 45,
            StoryState.WAIT_COMPLETE: 45,
            StoryState.WAIT_NEXT_STAGE: 45,
        }
        self.assertEqual(StoryRunner._TIMEOUT_SECONDS, expected)

    def test_all_four_timeout_tables_include_cutscene(self):
        tables = (
            StoryRunner._TIMEOUT_SECONDS,
            story_star.StoryStarRunner._TIMEOUT_SECONDS,
            activity_story.ActivityStoryRunner._TIMEOUT_SECONDS,
            side_story.SideStoryRunner._TIMEOUT_SECONDS,
        )
        for table in tables:
            self.assertEqual(table[StoryState.STORY_CUTSCENE], 180)

    def test_preview_rolls_the_cutscene_state_back(self):
        machine = make_machine(story_cutscene=True)

        action, outcome = machine.preview(blank_frame())

        self.assertIsNone(action)
        self.assertIs(outcome[0], StoryState.STORY_CUTSCENE)
        self.assertIs(machine.state, StoryState.WAIT_SKIP_CONFIRM)


if __name__ == "__main__":
    unittest.main()
