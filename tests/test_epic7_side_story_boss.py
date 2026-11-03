"""支线 BOSS 阶梯：场景页的「下一个难度」判据。

2026-11-01 实打中级取证：打完落在**同一个场景页**上，那一页同时有「重新进行」、
且蓝箭头为 0 —— 先判 `replay` 会在 12 帧后抛 `SideStoryCleared`，整条路线当场收工。
所以「下一个难度」必须排在 `replay` 之前，本文件就钉这件事。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7.side_story import build_side_story_machine


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "side_story"
_CACHE: dict[str, np.ndarray] = {}


def _load(path: Path) -> np.ndarray:
    key = str(path)
    if key not in _CACHE:
        raw = cv2.imread(key, cv2.IMREAD_COLOR)
        assert raw is not None, f"缺夹具 {path}"
        _CACHE[key] = cv2.cvtColor(raw[:1132, :1982], cv2.COLOR_BGR2RGB)
    return _CACHE[key]


def boss_scene() -> np.ndarray:
    return _load(FIXTURES / "epic7_side_story_boss" / "boss_scene.png")


def normal_scene() -> np.ndarray:
    return _load(FIXTURES / "epic7_side_story" / "scene.png")


class BossSceneTests(unittest.TestCase):
    def test_the_next_difficulty_button_wins_over_replay(self):
        """同一帧上两个判据都成立，顺序决定生死。"""

        machine = build_side_story_machine(TEMPLATES)
        screen = boss_scene()

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("next_difficulty", action.name)
        # 前置事实：这一页上 replay 真的命中、蓝箭头真的是 0（否则这条用例没意义）。
        self.assertIsNotNone(machine._locate(screen, "replay"))
        self.assertEqual(0, machine._arrow_pixels(screen))

    def test_a_normal_scene_page_is_not_the_boss_scene(self):
        """普通关卡打完的场景页不许命中「下一个难度」—— 那条路要照旧点蓝箭头。"""

        machine = build_side_story_machine(TEMPLATES)

        self.assertIsNone(machine._locate(normal_scene(), "next_difficulty"))

    def test_the_action_carries_a_transition_contract(self):
        """本路线开了强制转场契约：动作必须带来源页与落点。"""

        action = build_side_story_machine(TEMPLATES).next_action(boss_scene())

        self.assertEqual("难度场景页", action.source_page)
        self.assertIn("队伍准备", action.target_pages)


if __name__ == "__main__":
    unittest.main()
