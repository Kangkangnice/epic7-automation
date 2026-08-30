from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)
from auto_game_unified.games.epic7 import battle_controls as battle_controls_module


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(group: str, name: str) -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / group / f"{name}.png"
    return np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]


class SharedBattleControlsTests(unittest.TestCase):
    def test_auto_battle_with_dark_turn_order_keeps_battle_scene_visible(self):
        """实跑回归：行动顺序栏在暗色特效下不应否定已识别的自动战斗。"""
        screen = load_fixture("epic7_story", "battle_auto_on_live_20260809").copy()
        # 2026-08-27 实机诊断中，左侧行动顺序栏只有约 7% 的白色像素，
        # 但右上战斗控件仍清晰可见。构造同一视觉条件，避免依赖运行时诊断文件。
        screen[120:900, :140] = 0
        screen[120:175, :140] = 255

        self.assertEqual(BattleControls.AUTO_CONTROLS, observe_battle_controls(screen))
        self.assertTrue(battle_controls_module.battle_scene_visible(screen))

    def test_live_arena_skill_animation_keeps_battle_scene_visible(self):
        screen = load_fixture(
            "epic7_arena", "battle_skill_animation_live_20260825"
        )

        self.assertEqual(
            BattleControls.TRANSITION,
            observe_battle_controls(screen),
        )
        self.assertTrue(battle_controls_module.battle_scene_visible(screen))

    def test_each_mode_stable_battle_has_shared_scene_evidence(self):
        for group, name in (
            ("epic7_story", "battle_auto_on_live_20260809"),
            ("epic7_arena", "battle"),
            ("epic7_expedition", "battle"),
            ("epic7_fodder", "battle"),
        ):
            with self.subTest(group=group, name=name):
                self.assertTrue(
                    battle_controls_module.battle_scene_visible(
                        load_fixture(group, name)
                    )
                )

    def test_pre_battle_and_result_pages_are_not_battle_scenes(self):
        for group, name in (
            ("epic7_arena", "normal_battle_ready_live_20260826"),
            ("epic7_arena", "quick_battle_selected_live_20260826"),
            ("epic7_arena", "result"),
            ("epic7_story", "team"),
            ("epic7_fodder", "team"),
            ("epic7_expedition", "team"),
        ):
            with self.subTest(group=group, name=name):
                self.assertFalse(
                    battle_controls_module.battle_scene_visible(
                        load_fixture(group, name)
                    )
                )

    def test_blue_red_mixed_auto_controls_remain_auto(self):
        for name in (
            "battle_auto_dead_one_live_20260814",
            "battle_auto_dead_three_live_20260814",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    BattleControls.AUTO_CONTROLS,
                    observe_battle_controls(load_fixture("epic7_arena", name)),
                )

    def test_skill_animation_is_not_inferred_as_auto(self):
        self.assertEqual(
            BattleControls.TRANSITION,
            observe_battle_controls(
                load_fixture("epic7_story", "skill_animation_live_20260813")
            ),
        )

    def test_existing_story_and_expedition_auto_controls_remain_auto(self):
        for group, name in (
            ("epic7_story", "battle_auto_on_live_20260809"),
            ("epic7_expedition", "battle"),
        ):
            with self.subTest(group=group, name=name):
                self.assertEqual(
                    BattleControls.AUTO_CONTROLS,
                    observe_battle_controls(load_fixture(group, name)),
                )

    def test_auto_with_dark_cooldown_slot_and_soul_skill_is_auto(self):
        """实跑回归：AUTO 开启后出现 1 暗(冷却)+1 红(灵魂技) 技能槽，
        霍夫圆漏检 1 颗时仍应识别为自动布局（2026-08-18 主线实机熔断）。"""
        self.assertEqual(
            BattleControls.AUTO_CONTROLS,
            observe_battle_controls(
                load_fixture("epic7_story", "battle_auto_skill_cooldown_live_20260818")
            ),
        )

    def test_each_mode_manual_controls_remain_manual(self):
        for group, name in (
            ("epic7_story", "battle_auto_off_live_20260809"),
            ("epic7_story", "battle_manual_skill_variant_live_20260815"),
            ("epic7_arena", "battle_manual_stuck_live_20260814"),
            ("epic7_expedition", "battle_manual_waiting_live"),
        ):
            with self.subTest(group=group, name=name):
                self.assertEqual(
                    BattleControls.MANUAL_CONTROLS,
                    observe_battle_controls(load_fixture(group, name)),
                )


if __name__ == "__main__":
    unittest.main()
