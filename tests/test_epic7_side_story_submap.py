"""跨小地图（大地图里的第二张小地图）回归测试。

2026-11-27 用户新增的场景：①段走到**当前这张**小地图的底部时，场景页一样没有
「下一关」箭头，但地图上还有一颗跨图传送门（绿圆盘 + 深绿箭头，下方挂「前往X入口」）。
点它进下一张小地图，从那里继续打普通关卡；地图上没有门，才轮到 ② 据点段。

三条硬约束（都在下面有用例钉住）：

1. 门**常显**（这一层没打完时也在地图上）⇒ 只有「刚点完离开」的窗口里才许读它，
   否则会把角色从半路拽到另一张图；
2. 回地图第一帧可能还在淡入 ⇒ 第一帧没看到门先等一帧，连查两帧没有才判「没有门」；
3. 跨图次数有上限 ⇒ 绝不允许两张小地图之间来回跳。
"""

from pathlib import Path
import unittest

import numpy as np

from auto_game_unified.games.epic7.side_story import (
    _SEG_OUTPOST_1,
    _SUBMAP_ARRIVE_GRACE,
    _SUBMAP_JUMP_LIMIT,
    _map_changed,
    _map_grid,
    build_side_story_machine,
    build_side_story_templates,
)
from auto_game_unified.tests.fixture_images import read_rgb_fixture

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_side_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "side_story"


def fixture(name: str) -> np.ndarray:
    return read_rgb_fixture(FIXTURES / f"{name}.png", crop_to_reference=False)


def map_with_portal(name: str = "map_default_view", at=(420, 560)) -> np.ndarray:
    """把传送门模板贴到地图夹具上，合成「这一层还有下一张小地图」的画面。"""

    frame = fixture(name).copy()
    portal = build_side_story_templates(TEMPLATES).submap_portal
    x, y = at
    frame[y : y + portal.shape[0], x : x + portal.shape[1]] = portal
    return frame


class MapIdentityTests(unittest.TestCase):
    """地图缩略图只用来回答「是不是换了一张图」，门槛按实测定。"""

    def test_same_map_variants_are_not_a_change(self):
        # 同一张图、只是角色光标不同（差≥2 的格子实测 0%）。
        self.assertFalse(
            _map_changed(
                _map_grid(fixture("map_default_view")),
                _map_grid(fixture("map_no_cursor")),
            )
        )

    def test_two_different_maps_are_a_change(self):
        # 两张不同的小地图（差≥2 的格子实测 58%）。
        self.assertTrue(
            _map_changed(
                _map_grid(fixture("map_default_view")),
                _map_grid(fixture("map")),
            )
        )


class SubMapPortalTests(unittest.TestCase):
    def machine(self):
        return build_side_story_machine(TEMPLATES)

    def test_without_the_pending_check_the_portal_is_ignored(self):
        """门是常显的 ⇒ 不在「刚离开」的窗口里，它不该引起任何跨图动作。"""

        machine = self.machine()

        action = machine.next_action(map_with_portal())

        self.assertNotEqual("enter_next_submap", getattr(action, "name", ""))
        self.assertEqual(0, machine._submap_jumps)

    def test_portal_after_leaving_enters_the_next_submap(self):
        machine = self.machine()
        machine._pending_submap = True

        action = machine.next_action(map_with_portal())

        self.assertIsNotNone(action)
        self.assertEqual("enter_next_submap", action.name)
        self.assertEqual(1, machine._submap_jumps)
        self.assertTrue(machine._submap_wait_reload)

    def test_no_portal_after_leaving_hands_over_to_the_map_bubbles(self):
        """没有跨图门 ⇒ ①段到此为止；下一段**由地图上的 0/1 气泡决定**，不写死②。

        这张夹具（`map`）一个「入场限制 0/1」都没有 ⇒ 下一段是 ②摩罗戈拉。
        """

        machine = self.machine()
        machine._pending_submap = True

        first = machine.next_action(fixture("map"))
        self.assertIsNone(first)
        self.assertTrue(machine._pending_submap)

        machine.next_action(fixture("map"))
        self.assertFalse(machine._pending_submap)
        self.assertTrue(machine._recheck_segment)

        # 重判要看两帧（等地图淡入），第三帧才落段落。
        machine.next_action(fixture("map"))
        machine.next_action(fixture("map"))
        self.assertEqual(_SEG_OUTPOST_1, machine._segment)

    def test_the_jump_is_capped_so_two_submaps_cannot_bounce_forever(self):
        machine = self.machine()
        machine._pending_submap = True
        machine.next_action(map_with_portal())
        self.assertEqual(_SUBMAP_JUMP_LIMIT, machine._submap_jumps)

        # 场景模拟：在第二张小地图上又点了一次「离开」，再次回到地图。
        machine._pending_submap = True
        machine._submap_wait_reload = False
        machine.next_action(map_with_portal())
        machine.next_action(map_with_portal())

        # 跨图封顶 ⇒ 不再点门，段落交给地图气泡重判。
        self.assertEqual(_SUBMAP_JUMP_LIMIT, machine._submap_jumps)
        self.assertTrue(machine._recheck_segment)

    def test_after_arriving_it_clicks_the_stage_node_not_prepare_battle(self):
        """新地图上要先点关卡节点 ——「准备战斗」在没选关之前按了没反应（用户实跑）。"""

        machine = self.machine()
        machine._submap_arrived = True

        action = machine.next_action(fixture("map"))

        self.assertIsNotNone(action)
        self.assertEqual("pick_stage", action.name)
        self.assertEqual((1180, 605), action.point)  # 关卡光标下移固定像素，不是右下按钮

    def test_arriving_new_map_waits_instead_of_clicking_prepare_when_no_cursor(self):
        """刚进地图、节点还没画出来：前几帧等着，绝不按「准备战斗」。"""

        machine = self.machine()
        machine._submap_arrived = True
        machine._submap_arrive_frames = 0

        for _ in range(_SUBMAP_ARRIVE_GRACE):
            self.assertIsNone(machine.next_action(fixture("map_no_cursor")))

        # 宽限用完才按老路兜底（那时说明这张图确实没有光标判据）。
        action = machine.next_action(fixture("map_no_cursor"))
        self.assertEqual("pick_stage", action.name)

    def test_arriving_on_the_new_map_reports_the_page_and_waits_for_a_stage_pick(self):
        """跨图之后不能立刻再点门：先认出地图，再由「准备战斗」进第一个关卡。"""

        machine = self.machine()
        machine._pending_submap = True
        machine.next_action(map_with_portal())
        self.assertTrue(machine._submap_wait_reload)

        # 地图换成另一张（用另一张夹具地图冒充新小地图）。
        action = machine.next_action(fixture("map"))

        self.assertIsNone(action)
        self.assertFalse(machine._pending_submap)
        self.assertTrue(machine._submap_arrived)
