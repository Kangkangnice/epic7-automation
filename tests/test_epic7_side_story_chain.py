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
    _PAN_SAFE,
    _PAN_START,
    _PAN_SWEEPS,
    _SEG_BOSS,
    _SEG_OUTPOST_1,
    _SEG_OUTPOST_2,
    _pan_endpoint,
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


def map_without_any_node() -> np.ndarray:
    # map.png：三个节点模板**都不命中**的一张地图帧 —— 钉「有界平移扫寻」用它。
    # ⚠️ 别用 map_default_view：2026-11-12 补了「S.哥布林据点」名条模板后，
    # 那张图上哥布林也能识别（0.856），平移分支根本走不到。
    return _load(FIXTURES / "epic7_side_story" / "map.png")


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
    def test_normal_done_clicks_leave_and_switches_to_first_outpost(self):
        """① 场景页连续 12 帧无箭头 ⇒ 点「离开」（不再抛收工），段落切 ②摩罗戈拉。

        ⚠️ 2026-11-12 顺序订正：②是摩罗戈拉据点（旧版是 BOSS 段）。
        """

        machine = build_side_story_machine(TEMPLATES)
        action = None
        for _ in range(12):
            action = machine.next_action(scene_without_arrow())
        self.assertIsNotNone(action)
        self.assertEqual("scene_leave", action.name)
        self.assertEqual(_SEG_OUTPOST_1, machine._segment)
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
        """目标节点不在视野 ⇒ 有界平移扫寻。

        ⚠️ 2026-11-12 顺序订正：③哥布林是 `_SEG_OUTPOST_2`（旧版是 `_SEG_OUTPOST_1`）。
        用的帧换成 `map.png`（三个节点模板都不命中）；`map_default_view` 现在能认出哥布林。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_2  # 找哥布林，map.png 上没有

        names = []
        first_point = None
        for _ in range(_PAN_LIMIT):
            action = machine.next_action(map_without_any_node())
            self.assertIsNotNone(action)
            self.assertTrue(action.name.startswith("pan_map_"), action.name)
            if first_point is None:
                first_point = action.point
            names.append(action.name)
        # 第一次平移 = 扫寻序列第 1 步（往下拖 340）：point = 起点 + 增量
        # （终点语义，由 Runner 的 _perform_action 换发成 swipe）。
        self.assertEqual((_PAN_START[0], _PAN_START[1] + 340), first_point)
        # 超过上限 ⇒ 返回 None（原地等状态超时兜底，绝不瞎点）。
        self.assertIsNone(machine.next_action(map_without_any_node()))
        self.assertEqual(len(set(names)), _PAN_LIMIT)  # 每次动作名都不同，防重发

    def test_panned_map_picks_goblin_when_visible(self):
        """哥布林在视野内时（01_selected），③③段直接点中它。

        ⚠️ 2026-11-12 顺序订正：③哥布林是 `_SEG_OUTPOST_2`。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_2

        action = machine.next_action(map_goblin_selected())

        self.assertIsNotNone(action)
        self.assertEqual("pick_node_goblin_node", action.name)
        self.assertEqual((717, 357), action.point)


class PanSweepGeometryTests(unittest.TestCase):
    """扫寻几何：每个拖动终点都必须落在画布安全区内。

    2026-11-05 PC 真机就死在这一条 —— `(0, -680)` / `(0, 680)` 配起点 y=560
    算出的终点是 **-120 / 1240**，后者越过画布底边 1132。拖动终点落到画面外，
    这一拖在游戏侧被吞掉（或只走半程），六次扫寻全空 ⇒ 地图上永远找不到 BOSS
    节点 ⇒ 干等状态超时。日志特征：`pan_map_1..6` 都发了，之后一条业务动作都没有。
    """

    def test_every_pan_endpoint_stays_inside_the_canvas(self):
        for index, delta in enumerate(_PAN_SWEEPS, start=1):
            with self.subTest(step=index, delta=delta):
                x, y = _pan_endpoint(delta)
                self.assertGreaterEqual(x, _PAN_SAFE[0])
                self.assertGreaterEqual(y, _PAN_SAFE[1])
                self.assertLessEqual(x, _PAN_SAFE[2])
                self.assertLessEqual(y, _PAN_SAFE[3])

    def test_every_pan_actually_moves_the_view(self):
        # 位移为 0 的「拖动」是空操作，白耗一次有界重试。
        for index, delta in enumerate(_PAN_SWEEPS, start=1):
            with self.subTest(step=index, delta=delta):
                self.assertNotEqual(_PAN_START, _pan_endpoint(delta))

    def test_the_configured_increments_are_legal_without_clamping(self):
        # 夹取是兜底，不是许可证：配置本身就必须让终点落在安全区里。
        # 这一条对旧配置（(0, -680) / (0, 680)）会直接变红 —— 它才是真正的回归护栏；
        # 上面那条 `stays_inside` 只证明「就算写错也不会送出去」。
        for index, delta in enumerate(_PAN_SWEEPS, start=1):
            with self.subTest(step=index, delta=delta):
                raw = (_PAN_START[0] + delta[0], _PAN_START[1] + delta[1])
                self.assertEqual(raw, _pan_endpoint(delta))

    def test_the_old_out_of_canvas_increments_are_clamped_not_sent_as_is(self):
        # 回归护栏：即便有人把旧增量写回去，夹取也必须把它们拉回安全区。
        self.assertEqual(_PAN_SAFE[1], _pan_endpoint((0, -680))[1])
        self.assertEqual(_PAN_SAFE[3], _pan_endpoint((0, 680))[1])

    def test_the_sweep_is_symmetric_in_y(self):
        # 扫完一轮 y 方向回到原点（注释里承诺过）：净位移必须为 0，
        # 否则每轮扫寻都会把视角往上/下推一截，越扫越偏。
        self.assertEqual(0, sum(delta[1] for delta in _PAN_SWEEPS))


class BossExhaustedChainTests(unittest.TestCase):
    def test_boss_exhausted_clicks_back_instead_of_stop(self):
        """② 段「次数用尽」⇒ 点「返回」退场接③（**不再就地收工**）。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        action = machine.next_action(exhausted_prep())

        self.assertIsNotNone(action)
        self.assertEqual("boss_done_back", action.name)
        self.assertTrue(machine._boss_done)

    def test_boss_done_scene_clicks_leave_and_terminates(self):
        """④ BOSS 打满退场（最后一段）：地狱级场景页点「离开」，回地图即收工。

        ⚠️ 2026-11-12 顺序订正：BOSS 从"第二段"改成"最后一段"，
        打满后不再切去据点（那是旧顺序的行为），而是置 `_final_leave`。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        machine._boss_advances = 3  # 已站上地狱级（档位序号 3）：⓪b 不再点「下一个难度」
        machine._boss_done = True

        action = machine.next_action(boss_scene())

        self.assertIsNotNone(action)
        self.assertEqual("boss_scene_leave", action.name)
        self.assertTrue(machine._final_leave)
        self.assertFalse(machine._boss_done)
        self.assertTrue(machine._leaving)

    def test_exhausted_outside_boss_segment_still_terminates(self):
        """非 ② 段（如③据点次数用尽/未知段）命中「次数用尽」仍收工（旧语义保留）。"""

        machine = build_side_story_machine(TEMPLATES)
        with pytest.raises(SideStoryCleared):
            machine.next_action(exhausted_prep())


class BossFirstEntryTests(unittest.TestCase):
    def test_helper_page_clicks_change(self):
        """BOSS 首进场第一拍：helper 页点左下「变更」。

        ⚠️ 2026-11-12 21:52 实跑：这一页是**慢转场**（页面滑入），必须等画面停稳再点，
        否则点到还没就位的按钮 ⇒ 落到「助手选择」⇒ 45 秒超时。
        所以第一帧只建稳定基准、不点；第二帧（同一画面）才点。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        frame = boss_helper_page()

        # 稳定判定要连续 2 帧一致（第一帧只建基准）⇒ 前两帧不点，第三帧才点。
        self.assertIsNone(machine.next_action(frame))
        self.assertIsNone(machine.next_action(frame))

        action = machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("boss_open_difficulty", action.name)
        self.assertFalse(machine._boss_entered)

    def test_difficulty_list_clicks_the_unchecked_tier_then_confirm(self):
        """BOSS 进场第二/三拍：列表页点**没打勾的那一档**，下一拍点「选择队伍」。

        ⚠️ 2026-11-12 用户口径：不再死点「中级行」，而是看勾 —— 夹具
        `boss_difficulty_list.png` 上初级/中级打勾、上级没勾，所以该点的是**上级**。
        中途从上级接力时计数器是 0（以为还在中级），但勾是游戏画的真相。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        pick = machine.next_action(boss_difficulty_list())
        self.assertIsNotNone(pick)
        self.assertEqual("boss_pick_tier", pick.name)
        self.assertIn("上级", pick.reason)
        self.assertTrue(machine._boss_row_clicked)

        confirm = machine.next_action(boss_difficulty_list())
        self.assertIsNotNone(confirm)
        self.assertEqual("boss_confirm_team", confirm.name)
        self.assertTrue(machine._boss_entered)

    def test_no_check_at_all_means_judgement_broken(self):
        """**一个勾都没有 ⇒ 判据失效，停手**（用户口径：初级一定是打勾的）。

        2026-11-12 22:10 用户纠正：这期活动初级打完就永远打勾，下次进来最少从中级开始，
        所以"四档全没勾"在实际游戏里不会出现 —— 只可能是勾模板失效（换皮/缩放/遮挡）。
        这种时候必须停在原地等超时，**绝不默认从初级打起**（白烧一整轮体力）。
        """

        machine = build_side_story_machine(TEMPLATES)
        screen = boss_difficulty_list().copy()
        bg = screen[300, 900].copy()  # 面板底色
        for y0 in (288, 505):        # 抹掉初级/中级那两颗勾
            screen[y0 - 8 : y0 + 40, 925:990] = bg

        self.assertIsNone(machine._first_unchecked_tier(screen))

    def test_helper_page_is_taken_over_without_segment_state(self):
        """接力/中途启动时 `_segment` 是普通段 —— 只要画面自证是 BOSS 进场页就接管。

        2026-11-12 22:19 用户拍板：「中断之后再往下走也要走得通」。
        旧写法要求 `_segment == _SEG_BOSS`，接力进来就漏接 ⇒ 主线把难度列表
        误认成「助手选择」⇒ 卡死。新契约：画面能证明身份，就不依赖状态位，并顺手把
        段位拨到 BOSS（自愈）。
        """

        machine = build_side_story_machine(TEMPLATES)
        self.assertNotEqual(_SEG_BOSS, machine._segment)  # 新机器默认是①段

        handled, _action = machine._side_decision(boss_helper_page())

        self.assertTrue(handled)
        self.assertEqual(_SEG_BOSS, machine._segment)  # 段位自愈


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


class MapEntryWithoutCursorTests(unittest.TestCase):
    """① 段从地图起步：本期不画青色菱形时，改点「准备战斗」。

    2026-11-07 真机（用户手动停在支线地图）实测：颜色区间里最大的青色候选
    面积只有 102，判据要求 ≥150 ⇒ 旧行为返回 None 干等状态超时。用户手动
    停在地图再启动是接力的典型落点，这一卡住看起来就是「三段没串起来」。
    """

    def test_map_without_cursor_clicks_prepare_battle(self):
        machine = build_side_story_machine(TEMPLATES)
        screen = _load(FIXTURES / "epic7_side_story" / "map_no_cursor.png")

        self.assertIsNone(machine._cursor_point(screen))
        prep = machine._locate(screen, "prepare_battle_map")
        self.assertIsNotNone(prep)

        action = machine.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("pick_stage", action.name)
        self.assertEqual(prep.center, action.point)

    def test_map_with_cursor_still_prefers_the_cursor(self):
        """有光标的旧帧不能被「准备战斗」抢走（原路径零改动）。"""

        machine = build_side_story_machine(TEMPLATES)
        screen = _load(FIXTURES / "epic7_side_story" / "map.png")

        action = machine.next_action(screen)

        self.assertEqual("pick_stage", action.name)
        self.assertEqual((1180, 605), action.point)


if __name__ == "__main__":
    unittest.main()
