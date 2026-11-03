"""支线 BOSS 阶梯：档位推进 + 「次数用尽」终点。

2026-11-01 用户补的终点：地狱级 5 次打满后，队伍准备页出现「可入场次数已全部耗尽。」
（气泡中心画布 (1672,930)）。这一句同时是 ② BOSS 终点与 ③ 据点终点 —— 出现即收工。

本文件钉三件事：
1. BOSS 场景页的「下一个难度」只推进 中级→上级→地狱级 两次，到地狱级后改走「重新进行」；
2. 地狱级场景页不再误点「下一个难度」空转；
3. 「可入场次数已全部耗尽。」出现即 ``SideStoryCleared``，且对可打态页面不误报。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np
import pytest

from auto_game_unified.games.epic7.side_story import (
    SideStoryCleared,
    build_side_story_machine,
)


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


def exhausted_prep() -> np.ndarray:
    # 「S.摩罗戈拉生长地」0/1 队伍准备页：含「可入场次数已全部耗尽。」
    return _load(FIXTURES / "epic7_side_story" / "exhausted_prep.png")


def ready_prep() -> np.ndarray:
    # 「S.哥布林据点」1/1 队伍准备页：可打态，不应命中 entry_exhausted。
    return _load(FIXTURES / "epic7_side_story" / "ready_prep.png")


class BossLadderTests(unittest.TestCase):
    def test_fresh_machine_advances_tier_on_boss_scene(self):
        """BOSS 场景页（中级打完）→ 点「下一个难度」，档位计数 +1。"""

        machine = build_side_story_machine(TEMPLATES)
        self.assertEqual(0, machine._boss_advances)

        action = machine.next_action(boss_scene())

        self.assertIsNotNone(action)
        self.assertEqual("next_difficulty", action.name)
        self.assertEqual(1, machine._boss_advances)

    def test_at_hell_tier_next_difficulty_is_not_clicked(self):
        """已推满到地狱级（advances==2）：BOSS 场景页改走「重新进行」，不点「下一个难度」。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._boss_advances = 2

        action = machine.next_action(boss_scene())

        self.assertIsNotNone(action)
        self.assertEqual("replay", action.name)  # 地狱级用「重新进行」打满
        # 「下一个难度」这一支必须被跳过，否则会空转（地狱级已是最高档）。

    def test_entry_exhausted_terminates_route(self):
        """「可入场次数已全部耗尽。」出现 ⇒ 路线收工（SideStoryCleared）。"""

        machine = build_side_story_machine(TEMPLATES)
        with pytest.raises(SideStoryCleared):
            machine.next_action(exhausted_prep())

    def test_entry_exhausted_is_specific_to_exhausted_prep(self):
        """可打态队伍准备页（1/1）不得命中 entry_exhausted。"""

        machine = build_side_story_machine(TEMPLATES)
        self.assertIsNone(machine._locate(ready_prep(), "entry_exhausted"))

    def test_entry_exhausted_checked_before_replay(self):
        """耗尽文案必须在 replay 之前判到 —— 否则耗尽页会被当成普通场景页空转。"""

        machine = build_side_story_machine(TEMPLATES)
        # 直接确认顺序：entry_exhausted 命中时，replay 也可能命中，但决策先抛收工。
        self.assertIsNotNone(machine._locate(exhausted_prep(), "entry_exhausted"))
        with pytest.raises(SideStoryCleared):
            machine.next_action(exhausted_prep())


if __name__ == "__main__":
    unittest.main()
