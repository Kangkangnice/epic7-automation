"""支线 BOSS 阶梯：档位推进 + 「次数用尽」终点。

2026-11-01 用户补的终点：地狱级 5 次打满后，队伍准备页出现「可入场次数已全部耗尽。」
（气泡中心画布 (1672,930)）。②③ 据点次数用尽与 ④ BOSS 地狱级打满**共用这一句**；
顺序订正后（2026-11-12）只有 ④ 打满才收工，②③ 打满只推进下一段。

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
    _SEG_BOSS,
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
        """BOSS 场景页（中级打完）→ 点「下一个难度」，**点出去之后**档位 +1。

        前置：这一页只在 ④ 段出现，单页用例要自己把 `_segment` 摆到 BOSS 段
        （真实链路由哥布林据点「离开」回地图时推进）。

        ⚠️ 2026-11-12 21:21：记账从 `next_action` 挪到 `action_clicked` ——
        决策路径会被主循环空转重复调用（上一动作未验收时动作被丢掉），
        在那里自增会让「没点」也算推过一档。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS
        self.assertEqual(0, machine._boss_advances)

        action = machine.next_action(boss_scene())

        self.assertIsNotNone(action)
        self.assertEqual("next_difficulty", action.name)
        self.assertEqual(0, machine._boss_advances)  # 还没点出去，不算

        machine.action_clicked(action)
        self.assertEqual(1, machine._boss_advances)  # 真的点了，才记一档（中级）

        # 第二档：中级 → 上级
        action = machine.next_action(boss_scene())
        machine.action_clicked(action)
        self.assertEqual(2, machine._boss_advances)

        # 第三档：上级 → 地狱级
        action = machine.next_action(boss_scene())
        machine.action_clicked(action)
        self.assertEqual(3, machine._boss_advances)

        # 到顶（地狱级 = 3）⇒ 改走「重新进行」（终点由 entry_exhausted 判定）
        action = machine.next_action(boss_scene())
        self.assertIsNotNone(action)
        self.assertEqual("replay", action.name)

    def test_idle_decisions_do_not_advance_tier(self):
        """转场等待期的空转决策**不许**推档（2026-11-12「一直打中级」的真因）。

        主循环在「上一动作还没验收通过」时仍每帧调一次 `next_action`，算出来的动作
        被整个丢掉；若在这里 `+= 1`，点完结算确认等场景页的那几秒就会把档位顶到 2，
        之后一路「重新进行」，中级打了一遍又一遍。
        """

        machine = build_side_story_machine(TEMPLATES)
        machine._segment = _SEG_BOSS

        for _ in range(5):
            action = machine.next_action(boss_scene())
            self.assertIsNotNone(action)
            self.assertEqual("next_difficulty", action.name)

        self.assertEqual(0, machine._boss_advances)

    def test_at_hell_tier_next_difficulty_is_not_clicked(self):
        """已推满到地狱级（advances==2）：BOSS 场景页改走「重新进行」，不点「下一个难度」。"""

        machine = build_side_story_machine(TEMPLATES)
        machine._boss_advances = 3  # 已站上地狱级（档位序号 3）

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
