"""支线 ③ 据点：连打链路下的据点模式状态制。

关键结论（2026-11-01 收口；同日傍晚升级为连打链路）：
- 据点场景页与普通①「打完」场景页**长得一模一样**（都有离开/大厅/重新进行、
  都没箭头、都没「下一个难度」）—— 纯页面识别分不出两者。
- ⇒ ③ 必须走**状态制**：据点队伍页的「可完成1次。」(`outpost_team`) 置位
  ``_in_outpost``；置位后场景页改点「离开」(`outpost_leave`) 回地图，而不是走①的
  箭头收工逻辑。
- 连打链路下（用户明确要求 ①→②→③ 一条龙）：
  * 据点①（哥布林）点完「离开」⇒ 段落切到 `_SEG_OUTPOST_2`，地图导航去摩罗戈拉；
  * 据点②（摩罗戈拉）点完「离开」⇒ `_final_leave`，回地图即抛 ``SideStoryCleared``。

本文件钉四件事：
1. 据点队伍页 `outpost_team` 能置位 `_in_outpost`，且对①队伍页不误报；
2. 据点模式里场景页改点「离开」、并推进段落（③a→③b / ③b→收工标记）；
3. **没有**据点模式时，据点场景页被当成①（走 replay/箭头逻辑），绝不误点「离开」；
4. 最后一个据点离开 → 地图页收工；正常地图页重置据点模式、不收工。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7.side_story import (
    SideStoryCleared,
    build_side_story_machine,
)
from auto_game_unified.games.epic7.side_story import (
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


def outpost_team() -> np.ndarray:
    # 哥布林据点队伍页（03_team_ready）：含「1/1 可完成1次。」白气泡 + 「战斗开始」。
    return _load(FIXTURES / "epic7_side_story" / "outpost_team.png")


def outpost_scene() -> np.ndarray:
    # 哥布林据点打完确认后的据点场景页（05_after_confirm）：离开/大厅/重新进行，无箭头。
    return _load(FIXTURES / "epic7_side_story" / "outpost_scene.png")


def normal_team() -> np.ndarray:
    # ① 普通主线队伍页（team.png）：「进行任务」，无「可完成1次」。
    return _load(FIXTURES / "epic7_side_story" / "team.png")


def map_page() -> np.ndarray:
    # 关卡地图（map.png）。
    return _load(FIXTURES / "epic7_side_story" / "map.png")


def exhausted_prep() -> np.ndarray:
    # 「S.摩罗戈拉生长地」0/1 队伍准备页：含「可入场次数已全部耗尽。」
    return _load(FIXTURES / "epic7_side_story" / "exhausted_prep.png")


def results_page() -> np.ndarray:
    # 战斗结算确认页（results.png）：底部确认按钮。
    return _load(FIXTURES / "epic7_side_story" / "results.png")


class OutpostTests(unittest.TestCase):
    def test_outpost_team_detection_sets_mode(self):
        """据点队伍页命中 `outpost_team` ⇒ 置位 `_in_outpost`（副作用）。"""

        machine = build_side_story_machine(TEMPLATES)
        self.assertFalse(machine._in_outpost)

        handled, _action = machine._side_decision(outpost_team())

        # 队伍页本身交给主线处理（不归支线独有判据管），但模式位已置。
        self.assertFalse(handled)
        self.assertTrue(machine._in_outpost)

    def test_outpost_team_is_specific_to_outpost(self):
        """① 普通队伍页不得命中 `outpost_team`（否则①会被误判成据点）。"""

        machine = build_side_story_machine(TEMPLATES)
        self.assertIsNone(machine._locate(normal_team(), "outpost_team"))

    def test_outpost1_scene_clicks_leave_and_advances_segment(self):
        """据点①模式里，据点场景页点「离开」，段落推进到 `_SEG_OUTPOST_2`。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._in_outpost = True
        machine._segment = _SEG_OUTPOST_1

        action = machine.next_action(outpost_scene())

        self.assertIsNotNone(action)
        self.assertEqual("outpost_leave", action.name)
        self.assertEqual(_SEG_OUTPOST_2, machine._segment)
        self.assertTrue(machine._leaving)
        self.assertFalse(machine._final_leave)

    def test_outpost2_scene_clicks_leave_switches_to_boss(self):
        """据点②（哥布林）场景页点「离开」⇒ 段落切 ④BOSS（**不再收工**）。

        ⚠️ 2026-11-12 顺序订正：BOSS 是最后一段，哥布林之后还有一个目标。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._in_outpost = True
        machine._segment = _SEG_OUTPOST_2

        action = machine.next_action(outpost_scene())

        self.assertIsNotNone(action)
        self.assertEqual("outpost_leave", action.name)
        self.assertTrue(machine._leaving)
        self.assertEqual(_SEG_BOSS, machine._segment)
        self.assertFalse(machine._final_leave)

    def test_outpost_scene_no_leave_without_mode(self):
        """**没有**据点模式时，据点场景页被当成①（箭头缺失→等待/收工逻辑），绝不误点「离开」。

        这正是状态制的意义：纯页面识别分不出据点场景页与①「打完」场景页，
        所以必须靠 `_in_outpost` 门控，不能让 `outpost_leave` 在①上乱触发。
        ① 在「无箭头场景页」上的行为是返回 None（累计缺失帧，凑满门槛才接力），
        关键是它**绝不**返回 ``"outpost_leave"``。
        """

        machine = build_side_story_machine(TEMPLATES)
        self.assertFalse(machine._in_outpost)

        action = machine.next_action(outpost_scene())

        self.assertIsNone(action)  # ① 的等待逻辑，不是「离开」
        self.assertFalse(machine._leaving)
        self.assertFalse(machine._final_leave)
        self.assertFalse(machine._in_outpost)

    def test_outpost2_leave_then_map_navigates_boss(self):
        """据点②（哥布林）离开回地图 ⇒ 不收工，切 ④BOSS 去找骷髅。

        ⚠️ 2026-11-12 顺序订正：BOSS 是最后一段，所以这里还**不该**收工。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._in_outpost = True
        machine._segment = _SEG_OUTPOST_2
        machine.next_action(outpost_scene())  # 点「离开」，段落切 ④

        try:
            action = machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("哥布林离开回地图不应收工（后面还有 BOSS）")
        self.assertIsNotNone(action)
        self.assertTrue(action.name.startswith(("pick_node_boss_node", "pan_map_")))

    def test_outpost1_leave_then_map_navigates_next_outpost(self):
        """据点①离开回地图 ⇒ 不收工，导航去下一个据点（连打链路核心语义）。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._in_outpost = True
        machine._segment = _SEG_OUTPOST_1
        machine.next_action(outpost_scene())  # 点「离开」，段落已切 ③哥布林

        # 回到地图：段落是 _SEG_OUTPOST_2 ⇒ 应去找哥布林节点，而不是收工。
        # map.png 这张夹具里找不到目标节点 ⇒ 走有界平移扫寻（也不收工）。
        try:
            action = machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("据点①离开回地图不应触发收工")
        self.assertIsNotNone(action)
        self.assertTrue(action.name.startswith(("pick_node_goblin_node", "pan_map_")))

    def test_normal_map_resets_outpost_mode_without_terminating(self):
        """正常地图页（未离开）重置 `_in_outpost`、不收工。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._in_outpost = True
        machine._final_leave = False

        # 不应抛收工；模式位应被重置。
        try:
            machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("正常地图页不应触发收工")
        self.assertFalse(machine._in_outpost)

    def test_boss_segment_never_enters_outpost_mode(self):
        """④ BOSS 段即使队伍页有次数气泡，也**不许**置「据点模式」。

        2026-11-12 22:11 实跑：地狱级队伍页也有次数气泡（那一档要打 5 次），
        `outpost_team` 照样命中 ⇒ 打完一把落回场景页被当成「据点打完」直接点「离开」
        回地图 —— 本该「重新进行」把 5 次打满。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        machine.next_action(outpost_team())

        self.assertFalse(machine._in_outpost)

    def test_results_confirm_accepts_side_scene_pages(self):
        """结算确认的落点白名单必须含本路线自有场景页（据点/地狱级）。

        2026-11-12 20:38 实跑：摩罗戈拉打完落回据点场景页（只剩「离开/大厅/重新进行」），
        这一页不在主线那五个落点里 ⇒ 主循环判「没点成功」⇒ 状态机刚给出的「离开」被
        整个丢掉 ⇒ 干等 45 秒、退出码 1。漏声明的代价与主线 11-01 那两次同类。
        """

        machine = build_side_story_machine(TEMPLATES)

        action = machine.next_action(results_page())

        self.assertIsNotNone(action)
        self.assertEqual("results_confirm", action.name)
        self.assertIn("据点场景页", action.target_pages)
        self.assertIn("地狱级场景页", action.target_pages)
        # 2026-11-12 21:43 实跑：打完上级落回「难度场景页」（有「下一个难度」的那一屏），
        # 前两版名单漏了它 ⇒ 同样干等 45 秒。三个自有场景页一个都不能少。
        self.assertIn("难度场景页", action.target_pages)


class OutpostExhaustedTests(unittest.TestCase):
    """据点次数用尽：**退场接下一段**，不就地收工。

    旧行为在这里直接 ``SideStoryCleared``：中途重跑、据点①已用尽时，据点②会被
    静默跳过 —— 代码里曾把这条写成「已知局限」。新语义是点「返回」退场，回地图后
    由地图分支推进（据点① → 据点②，据点② → 收工）。
    """

    def test_outpost1_exhausted_backs_out_and_advances_to_outpost2(self):
        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_1

        action = machine.next_action(exhausted_prep())

        self.assertIsNotNone(action)
        self.assertEqual("outpost_done_back", action.name)
        self.assertTrue(machine._outpost_done)
        self.assertFalse(machine._final_leave)

        # 「返回」直接落回地图：推进到据点②，且**不**收工。
        try:
            machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("据点①次数用尽后退场回地图不应收工（会跳过据点②）")
        self.assertEqual(_SEG_OUTPOST_2, machine._segment)
        self.assertFalse(machine._final_leave)

    def test_outpost2_exhausted_backs_out_then_map_switches_to_boss(self):
        """据点②（哥布林）次数用尽退场回地图 ⇒ 切 ④BOSS，**不收工**。

        ⚠️ 2026-11-12 顺序订正：哥布林不是最后一段，后面还有骷髅阶梯。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_2

        action = machine.next_action(exhausted_prep())
        self.assertEqual("outpost_done_back", action.name)
        self.assertTrue(machine._outpost_done)

        try:
            machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("哥布林用尽后退场回地图不应收工（后面还有 BOSS）")
        self.assertEqual(_SEG_BOSS, machine._segment)
        self.assertFalse(machine._final_leave)

    def test_outpost_scene_after_exhaustion_advances_only_once(self):
        """「返回」落回据点场景页时，段落只推进一次（否则据点②会被跳过）。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_OUTPOST_1
        machine._in_outpost = True
        machine.next_action(exhausted_prep())

        action = machine.next_action(outpost_scene())

        self.assertEqual("outpost_leave", action.name)
        self.assertEqual(_SEG_OUTPOST_2, machine._segment)
        self.assertFalse(machine._outpost_done)  # 场景页那条路已经消化掉退场标记

        try:
            machine.next_action(map_page())
        except SideStoryCleared:
            self.fail("据点①退场回地图不应收工")
        self.assertEqual(_SEG_OUTPOST_2, machine._segment)


if __name__ == "__main__":
    unittest.main()
