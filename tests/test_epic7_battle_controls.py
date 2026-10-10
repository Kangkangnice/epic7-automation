from pathlib import Path
import unittest

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
    resolve_auto_state,
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

    def test_single_lit_base_still_reads_as_auto_layout(self):
        """实跑回归：竞技场剩 1 个活人时，阵亡底座变红变黑、往下沉、颜色失效，
        底座排上只剩 1 格蓝的（活人）—— 此时必须仍判为自动战斗。

        底座颜色语义：**蓝 = 活着，红 = 阵亡**。
        真实素材 `battle_auto_dead_three_live_20260814` 就是「活 1 亡 3、底座环 4 个」，
        老逻辑「亮 >= 3 格」之所以还撑得住，只是因为它把 3 个红（阵亡）也算成了亮。
        这里把那 3 个阵亡底座刷成中性灰（模拟它们暗到认不出来），
        于是「亮」只剩 1 格 —— 老逻辑在此判 transition，新逻辑靠底座环仍认出战斗。
        """
        screen = load_fixture(
            "epic7_arena", "battle_auto_dead_three_live_20260814"
        ).copy()
        # 这帧里下标 0/1/3 是红的（阵亡），下标 2 是蓝的（活人）。
        # 把 3 个阵亡底座刷成中性灰 = 模拟它们暗到认不出来、颜色证据失效。
        for index in (0, 1, 3):
            center_x = battle_controls_module._AUTO_CONTROL_CENTERS[index]
            screen[1060:1132, center_x - 50 : center_x + 50] = 60

        self.assertEqual(
            BattleControls.AUTO_CONTROLS,
            observe_battle_controls(screen),
        )
        self.assertTrue(battle_controls_module.battle_scene_visible(screen))

    def test_low_survivor_arena_frame_counts_one_alive_base(self):
        """钉住底座颜色语义：蓝 = 活着，红 = 阵亡。

        真实竞技场帧 `battle_auto_dead_three_live_20260814` 是「活 1 亡 3」——
        4 格底座里只有 1 格是蓝的（活人），另外 3 格是红的（阵亡）。
        这曾经是判不出自动战斗的隐患：只要红色识别不到，「亮」就塌成 1 格。
        """
        screen = load_fixture("epic7_arena", "battle_auto_dead_three_live_20260814")
        frame = battle_controls_module._reference_frame(screen)
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

        alive = dead = 0
        for center_x in battle_controls_module._AUTO_CONTROL_CENTERS:
            slot = hsv[1060:1132, center_x - 50 : center_x + 50]
            blue = (
                (slot[:, :, 0] >= 85)
                & (slot[:, :, 0] <= 135)
                & (slot[:, :, 1] >= 100)
                & (slot[:, :, 2] >= 70)
            )
            red = (
                ((slot[:, :, 0] <= 10) | (slot[:, :, 0] >= 170))
                & (slot[:, :, 1] >= 100)
                & (slot[:, :, 2] >= 45)
            )
            alive += int(float(np.mean(blue)) >= 0.40)
            dead += int(float(np.mean(red)) >= 0.25)

        self.assertEqual(1, alive, "这帧应当只有 1 个活人底座（蓝色）")
        self.assertEqual(3, dead, "这帧应当有 3 个阵亡底座（红色）")
        self.assertEqual(
            BattleControls.AUTO_CONTROLS, observe_battle_controls(screen)
        )

    def test_single_lit_base_needs_the_full_base_row(self):
        """守住另一头：「有 1 格活人底座」不能变成「有 1 格就无脑算自动」。

        底座排没被确认（对齐圆不足 3 个）时，仍然要求颜色命中 >= 3 格。
        epic7_fodder/special_book.png 是实测的反例：活 1 且只有 2 个对齐圆，
        它是支线/活动书页面，不是战斗画面。
        """
        self.assertNotEqual(
            BattleControls.AUTO_CONTROLS,
            observe_battle_controls(load_fixture("epic7_fodder", "special_book")),
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


class ResolveAutoStateTests(unittest.TestCase):
    """布局（强证据）与右上角图标（弱证据）的合并规则（2026-10-09 月塔事故）。

    事故现场：同一场战斗（自动其实一直开着）在 23 秒里翻了三次判定 ——

        13:59:13  布局=auto_controls 图标=None    -> AUTO   「已开启」  ✅ 对的
        13:59:29  布局=auto_controls 图标=0.8055  -> MANUAL 「点一下」  ❌ 余量 0.0055
        13:59:30  图标掉下阈                      -> UNKNOWN
        13:59:43  布局=manual_controls 图标=None  -> MANUAL 无坐标 -> 判死

    旧写法 `if auto is not None: auto_state = MANUAL` **无条件信弱证据**，
    于是 13:59:29 无中生有地点了一次开关，还把坐标弄丢了。

    ⚠️ 这组断言**独立写死**期望值，不调用被测函数去算「该判什么」。
    """

    def test_strong_layout_evidence_is_not_overruled_by_the_icon(self):
        """★ 核心断言：布局明说自动开着时，图标擦阈命中不得改判。"""
        self.assertEqual(
            BattleControls.AUTO_CONTROLS,
            resolve_auto_state(BattleControls.AUTO_CONTROLS, True),
        )

    def test_strong_layout_evidence_holds_without_the_icon(self):
        """成对：图标没命中时，布局结论同样不变。"""
        self.assertEqual(
            BattleControls.AUTO_CONTROLS,
            resolve_auto_state(BattleControls.AUTO_CONTROLS, False),
        )

    def test_manual_layout_is_kept_regardless_of_the_icon(self):
        for hit in (True, False):
            with self.subTest(icon_hit=hit):
                self.assertEqual(
                    BattleControls.MANUAL_CONTROLS,
                    resolve_auto_state(BattleControls.MANUAL_CONTROLS, hit),
                )

    def test_icon_still_rescues_a_transition_frame(self):
        """★ 兜底必须还在：transition 时图标是唯一线索，不许一起收掉。

        没有这一条，把上面三条全"修"成「永远返回布局判定」也照样绿 ——
        而那样会让 transition 帧永远停在「未知」，而「未知」按安全设计
        不许点自动，战斗只能干等到超时。
        """
        self.assertEqual(
            BattleControls.MANUAL_CONTROLS,
            resolve_auto_state(BattleControls.TRANSITION, True),
        )

    def test_transition_stays_transition_when_the_icon_misses(self):
        self.assertEqual(
            BattleControls.TRANSITION,
            resolve_auto_state(BattleControls.TRANSITION, False),
        )

    def test_the_live_tower_incident_frame_is_manual(self):
        """真机事故帧：布局判 manual、图标 0.7704（低于 0.80 阈值）。

        这条锁的是**真实素材**：把那张诊断帧当夹具，保证「判成手动且拿不到
        坐标」这个组合在代码里仍然可复现 —— 它是 `auto_point_grace_seconds`
        有界等待存在的理由。
        """
        screen = load_fixture("epic7_tower", "battle_manual_auto_icon_dead_zone")
        controls = observe_battle_controls(screen)
        self.assertEqual(BattleControls.MANUAL_CONTROLS, controls)
        self.assertEqual(
            BattleControls.MANUAL_CONTROLS, resolve_auto_state(controls, False)
        )


if __name__ == "__main__":
    unittest.main()
