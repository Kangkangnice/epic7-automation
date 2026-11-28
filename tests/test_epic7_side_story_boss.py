"""支线 BOSS 阶梯：场景页的「下一个难度」判据。

2026-11-01 实打中级取证：打完落在**同一个场景页**上，那一页同时有「重新进行」、
且蓝箭头为 0 —— 先判 `replay` 会在 12 帧后抛 `SideStoryCleared`，整条路线当场收工。
所以「下一个难度」必须排在 `replay` 之前，本文件就钉这件事。
"""

from pathlib import Path
import unittest

import numpy as np

from auto_game_unified.games.epic7.side_story import (
    _SEG_BOSS,
    _SEG_NORMAL,
    build_side_story_machine,
)
from auto_game_unified.tests.fixture_images import read_rgb_fixture as _load


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "side_story"
def boss_scene() -> np.ndarray:
    return _load(FIXTURES / "epic7_side_story_boss" / "boss_scene.png")


def normal_scene() -> np.ndarray:
    return _load(FIXTURES / "epic7_side_story" / "scene.png")


def boss_difficulty_list() -> np.ndarray:
    # 辅助英雄**已选**的难度列表页（04_difficulty）：右下是「选择队伍」。
    return _load(
        FIXTURES / "epic7_side_story" / "boss_difficulty_list.png"
    )


def empty_helper_difficulty() -> np.ndarray:
    # 辅助英雄**空着**的难度列表页（2026-11-28 07:16 实拍）：右下是「选择辅助英雄」。
    return _load(
        FIXTURES / "epic7_side_story" / "boss_difficulty_empty_helper.png"
    )


def helper_list() -> np.ndarray:
    # 助手列表页：右下已是「选择队伍」，由主线 `select_team` 接管。
    return _load(FIXTURES / "epic7_side_story" / "helper_select.png")


class BossNodeTemplateTests(unittest.TestCase):
    """骷髅模板只裁**骷髅本体**，一张图通吃各期（2026-11-27 定案）。

    以前几版把底座/外圈/旁边图标一起裁进来，跨期掉到 0.69~0.73（门槛 0.80）——
    看着像「每期换皮」，实际变的是背景与裁框。按最大白块紧裁后，同一张模板在三期
    地图上都有 0.95 上下，所以这里钉的就是「模板只含骷髅本体」这件事。
    """

    def test_the_template_is_only_the_skull_body(self):
        machine = build_side_story_machine(TEMPLATES)
        template = machine.side.boss_node

        self.assertEqual((40, 40), template.shape[:2])

    def test_the_skull_template_is_found_by_locate(self):
        machine = build_side_story_machine(TEMPLATES)
        template = machine.side.boss_node
        frame = np.zeros((1132, 1982, 3), dtype=np.uint8)
        x, y = 700, 300
        frame[y : y + template.shape[0], x : x + template.shape[1]] = template

        hit = machine._locate(frame, "boss_node")

        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.80)
        self.assertAlmostEqual(hit.center[0], x + template.shape[1] // 2, delta=12)
        self.assertAlmostEqual(hit.center[1], y + template.shape[0] // 2, delta=12)


class BossEntryButtonTests(unittest.TestCase):
    """难度页右下那颗绿胶囊有**两种文案**，两种都必须能推进。

    辅助英雄位已选 ⇒「选择队伍」；还空着 ⇒「选择辅助英雄」（先进助手列表，那一页的
    确认键仍是「选择队伍」）。2026-11-28 07:16 实跑是空位态：档位点对了，程序却
    只认「选择队伍」，停在难度页干等到超时。
    """

    def _machine(self):
        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        machine._boss_row_clicked = True  # 档位已点过，这一拍该点确认键
        return machine

    def test_the_empty_helper_slot_opens_the_helper_list(self):
        machine = self._machine()
        screen = empty_helper_difficulty()

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("boss_open_helper", action.name)
        self.assertEqual("选择难度", action.source_page)
        # 落点是「选择辅助英雄」这颗按钮的中心（同一颗绿胶囊的位置）。
        self.assertEqual((1621, 1034), action.point)
        # 下一页是助手列表；那一页由主线接（`select_team`），必须写进落点名单。
        self.assertIn("助手选择", action.target_pages)
        self.assertTrue(machine._boss_entered)

    def test_the_filled_helper_slot_goes_straight_to_the_team(self):
        machine = self._machine()
        screen = boss_difficulty_list()

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("boss_confirm_team", action.name)
        self.assertEqual((1695, 1070), action.point)

    def test_the_two_labels_do_not_cross_match(self):
        """两种文案互不命中 —— 分开两张模板靠的是文字，不是位置。"""

        machine = build_side_story_machine(TEMPLATES)
        empty = empty_helper_difficulty()
        filled = boss_difficulty_list()

        self.assertIsNotNone(machine._locate(empty, "boss_select_helper"))
        self.assertIsNone(machine._locate(empty, "boss_select_team"))
        self.assertIsNotNone(machine._locate(filled, "boss_select_team"))
        self.assertIsNone(machine._locate(filled, "boss_select_helper"))

    def test_the_helper_list_hands_over_to_the_main_line(self):
        """进了助手列表就把手交回主线：那一页的「选择队伍」由 `select_team` 点。"""

        machine = self._machine()
        machine._boss_entered = True  # 上一步 `boss_open_helper` 已经置位

        action = machine.next_action(helper_list())

        self.assertIsNotNone(action)
        self.assertEqual("select_team", action.name)
        self.assertEqual("助手选择", action.source_page)
        self.assertIn("队伍准备", action.target_pages)


class BossSceneTests(unittest.TestCase):
    def test_the_next_difficulty_button_wins_over_replay(self):
        """同一帧上两个判据都成立，顺序决定生死。

        前置：BOSS 场景页只在 ② 段出现 —— 真实链路里 `_segment` 由①段「离开」
        回地图时推进（`_scene_action`），单页用例必须自己摆好这一位。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        screen = boss_scene()

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("next_difficulty", action.name)
        # 前置事实：这一页上 replay 真的命中、蓝箭头真的是 0（否则这条用例没意义）。
        self.assertIsNotNone(machine._locate(screen, "replay"))
        self.assertEqual(0, machine._arrow_pixels(screen))

    def test_segment_normal_scene_with_next_difficulty_is_not_pushed(self):
        """①段遇到同一张「下一个难度」页 ⇒ 让路给箭头，绝不推难度。

        2026-11-12 实跑实锤：①段**最后一关**打完后，那一页同时有「下一个难度」
        + 闪烁蓝箭头 + 重新进行。旧判据没有段位门禁，抢在箭头前面点了难度，
        身份报「难度场景页」；而 `results_confirm` 的落点白名单里没有它 ⇒ 转场
        验收不过 ⇒ 干等 45 秒，整条路线以退出码 1 收场（8 分 31 秒那次）。
        """

        machine = build_side_story_machine(TEMPLATES)
        self.assertEqual(_SEG_NORMAL, machine._segment)

        action = machine.next_action(boss_scene())

        # 箭头为 0 的这一帧只记账（等满 12 帧才点「离开」），难度档位一动不动。
        self.assertIsNone(action)
        self.assertEqual(0, machine._boss_advances)
        self.assertEqual(1, machine._arrow_misses)

    def test_a_normal_scene_page_is_not_the_boss_scene(self):
        """普通关卡打完的场景页不许命中「下一个难度」—— 那条路要照旧点蓝箭头。"""

        machine = build_side_story_machine(TEMPLATES)

        self.assertIsNone(machine._locate(normal_scene(), "next_difficulty"))

    def test_the_action_carries_a_transition_contract(self):
        """本路线开了强制转场契约：动作必须带来源页与落点。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        action = machine.next_action(boss_scene())

        self.assertEqual("难度场景页", action.source_page)
        self.assertIn("队伍准备", action.target_pages)


if __name__ == "__main__":
    unittest.main()
