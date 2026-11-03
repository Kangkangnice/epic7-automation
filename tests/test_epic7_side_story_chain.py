"""支线连打链路：①→②→③ 一条龙（2026-11-01，用户明确要求段间自动衔接）。

链路（每一步都由「有明确证据的动作」推进，不靠猜）：
    ① 场景页 12 帧无箭头（= ①打完）→ 点「离开」回地图，段落切 ②
    → 地图找骷髅节点 → 点它（角色走过去）→ 画面稳定后点「准备战斗」
    → BOSS 首进场三拍：变更 → 中级行 → 选择队伍
    → 阶梯（下一个难度 ×2 → 地狱级「重新进行」×5）
    → 「次数用尽」→ 点「返回」退场（**不再就地收工**）→ 地狱级场景页点「离开」
    → 段落切 ③ → 地图找哥布林据点 → … → 离开 → 地图找摩罗戈拉据点 → …
    → 离开 → 回地图 ⇒ SideStoryCleared 收工。

本文件钉的是**转场关节**：每一段的出口动作、段落推进、地图导航三步
（找节点 / 平移扫寻 / 稳定后点准备战斗），以及 BOSS 首进场三拍。
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
from auto_game_unified.games.epic7.side_story import (
    _PAN_LIMIT,
    _PAN_START,
    _SEG_BOSS,
    _SEG_OUTPOST_1,
    _SEG_OUTPOST_2,
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


def scene_without_arrow() -> np.ndarray:
    # ① 打完后的场景页：有「离开/大厅/重新进行」，无蓝箭头。
    return _load(FIXTURES / "epic7_side_story" / "scene_without_arrow.png")


def map_default_view() -> np.ndarray:
    # 默认视角地图（14_map）：骷髅 (1020,579)、摩罗戈拉 (165,308 雾态)、哥布林被顶栏挡住。
    return _load(FIXTURES / "epic7_side_story" / "map_default_view.png")


def map_boss_selected() -> np.ndarray:
    # 角色走到 BOSS 节点后的地图（02_map_boss）：骷髅 (1220,787)、「准备战斗」常显。
    return _load(FIXTURES / "epic7_side_story" / "map_boss_selected.png")


def map_goblin_selected() -> np.ndarray:
    # 哥布林节点在视野内的地图（01_selected）：goblin (717,357)。
    return _load(FIXTURES / "epic7_side_story" / "map_goblin_selected.png")


def boss_helper_page() -> np.ndarray:
    # 选择辅助英雄页（03_helper）：左下「变更」(155,1070) + 右下「选择队伍」。
    return _load(FIXTURES / "epic7_side_story" / "boss_helper_page.png")


def boss_difficulty_list() -> np.ndarray:
    # 难度列表页（04_difficulty）：中级行 (165,552) + 中下「变更」+ 右下「选择队伍」。
    return _load(FIXTURES / "epic7_side_story" / "boss_difficulty_list.png")


def exhausted_prep() -> np.ndarray:
    # 「可入场次数已全部耗尽。」队伍准备页（摩罗戈拉 0/1 同族页面）。
    return _load(FIXTURES / "epic7_side_story" / "exhausted_prep.png")


def boss_scene() -> np.ndarray:
    # BOSS 场景页（中级打完）：下一个难度 + 重新进行 + 离开/大厅。
    return _load(FIXTURES / "epic7_side_story_boss" / "boss_scene.png")


class NormalToBossChainTests(unittest.TestCase):
    def test_normal_done_clicks_leave_and_switches_to_boss(self):
        """① 场景页连续 12 帧无箭头 ⇒ 点「离开」（不再抛收工），段落切 ②。"""

        machine = build_side_story_machine(TEMPLATES)
        action = None
        for _ in range(12):
            action = machine.next_action(scene_without_arrow())
        self.assertIsNotNone(action)
        self.assertEqual("scene_leave", action.name)
        self.assertEqual(_SEG_BOSS, machine._segment)
        self.assertTrue(machine._leaving)

    def test_map_after_normal_done_picks_boss_node(self):
        """② 段地图：定位骷髅节点 → 点它，置 `_node_clicked`（等走路）。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        action = machine.next_action(map_default_view())

        self.assertIsNotNone(action)
        self.assertEqual("pick_node_boss_node", action.name)
        self.assertEqual((1020, 579), action.point)
        self.assertTrue(machine._node_clicked)

    def test_node_click_waits_for_settle_then_clicks_prepare(self):
        """点了节点之后：画面未稳定绝不点「准备战斗」；连续稳定 2 帧后才点。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        machine.next_action(map_default_view())  # pick_node，_prev_screen 已存副本
        self.assertTrue(machine._node_clicked)

        # 同一帧再喂：diff=0 → streak=1，还差一帧，必须等待。
        self.assertIsNone(machine.next_action(map_default_view()))
        # 再喂一帧：streak=2 ⇒ 稳定 ⇒ 「准备战斗」常显可见 ⇒ 点它。
        action = machine.next_action(map_default_view())
        self.assertIsNotNone(action)
        self.assertEqual("enter_selected_node", action.name)
        self.assertFalse(machine._node_clicked)

    def test_node_not_on_screen_pans_with_bounded_attempts(self):
        """目标节点不在视野（默认视角下 goblin 被顶栏挡住）⇒ 有界平移扫寻。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_1  # 找哥布林，map_default_view 上没有

        names = []
        first_point = None
        for _ in range(_PAN_LIMIT):
            action = machine.next_action(map_default_view())
            self.assertIsNotNone(action)
            self.assertTrue(action.name.startswith("pan_map_"), action.name)
            if first_point is None:
                first_point = action.point
            names.append(action.name)
        # 第一次平移 = 扫寻序列第 1 步（往下拖 340）：point = 起点 + 增量
        # （终点语义，由 Runner 的 _perform_action 换发成 swipe）。
        self.assertEqual((_PAN_START[0], _PAN_START[1] + 340), first_point)
        # 超过上限 ⇒ 返回 None（原地等状态超时兜底，绝不瞎点）。
        self.assertIsNone(machine.next_action(map_default_view()))
        self.assertEqual(len(set(names)), _PAN_LIMIT)  # 每次动作名都不同，防重发

    def test_panned_map_picks_goblin_when_visible(self):
        """哥布林在视野内时（01_selected），③a 段直接点中它。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_1

        action = machine.next_action(map_goblin_selected())

        self.assertIsNotNone(action)
        self.assertEqual("pick_node_goblin_node", action.name)
        self.assertEqual((717, 357), action.point)


class BossExhaustedChainTests(unittest.TestCase):
    def test_boss_exhausted_clicks_back_instead_of_stop(self):
        """② 段「次数用尽」⇒ 点「返回」退场接③（**不再就地收工**）。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        action = machine.next_action(exhausted_prep())

        self.assertIsNotNone(action)
        self.assertEqual("boss_done_back", action.name)
        self.assertTrue(machine._boss_done)

    def test_boss_done_scene_clicks_leave_and_switches_to_outpost(self):
        """② 打满退场：地狱级场景页点「离开」，段落切 ③a。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        machine._boss_advances = 2  # 地狱级：⓪b 不再点「下一个难度」
        machine._boss_done = True

        action = machine.next_action(boss_scene())

        self.assertIsNotNone(action)
        self.assertEqual("boss_scene_leave", action.name)
        self.assertEqual(_SEG_OUTPOST_1, machine._segment)
        self.assertFalse(machine._boss_done)
        self.assertTrue(machine._leaving)

    def test_exhausted_outside_boss_segment_still_terminates(self):
        """非 ② 段（如③据点次数用尽/未知段）命中「次数用尽」仍收工（旧语义保留）。"""

        machine = build_side_story_machine(TEMPLATES)
        with pytest.raises(SideStoryCleared):
            machine.next_action(exhausted_prep())


class BossFirstEntryTests(unittest.TestCase):
    def test_helper_page_clicks_change(self):
        """BOSS 首进场第一拍：helper 页点左下「变更」。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        action = machine.next_action(boss_helper_page())

        self.assertIsNotNone(action)
        self.assertEqual("boss_open_difficulty", action.name)
        self.assertFalse(machine._boss_entered)

    def test_difficulty_list_clicks_mid_row_then_confirm(self):
        """BOSS 首进场第二/三拍：列表页先点中级行（同页停留），下一拍点「选择队伍」。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        pick = machine.next_action(boss_difficulty_list())
        self.assertIsNotNone(pick)
        self.assertEqual("boss_pick_mid", pick.name)
        self.assertTrue(machine._boss_row_clicked)

        confirm = machine.next_action(boss_difficulty_list())
        self.assertIsNotNone(confirm)
        self.assertEqual("boss_confirm_team", confirm.name)
        self.assertTrue(machine._boss_entered)

    def test_first_entry_only_runs_in_boss_segment(self):
        """① 段的 helper 页（主线自己的「助手选择」）绝不触发首进场拦截。

        断言层级定在 ``_side_decision``：支线独有的判据都**不**接管这一页
        （交给主线），首进场三拍只在 `_SEG_BOSS` 段生效。
        """

        machine = build_side_story_machine(TEMPLATES)
        handled, action = machine._side_decision(boss_helper_page())
        self.assertFalse(handled)
        self.assertIsNone(action)


class LedgerHygieneTests(unittest.TestCase):
    def test_preview_does_not_mutate_ledger(self):
        """preview 只是观察：连打账本（段落/平移次数/稳定帧）必须原样还原。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_2

        machine.preview(map_default_view())

        self.assertEqual(_SEG_OUTPOST_2, machine._segment)
        self.assertEqual(0, machine._pan_attempts)
        self.assertFalse(machine._node_clicked)
        self.assertIsNone(machine._prev_screen)

    def test_map_boss_selected_picks_boss_node_at_panned_position(self):
        """平移后的地图帧（骷髅在 (1220,787)）同样能定位 —— 模板不依赖写死坐标。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        action = machine.next_action(map_boss_selected())

        self.assertIsNotNone(action)
        self.assertEqual("pick_node_boss_node", action.name)
        self.assertEqual((1220, 787), action.point)


if __name__ == "__main__":
    unittest.main()
