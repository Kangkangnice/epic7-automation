"""支线故事开局接力：落点判定 + **顺序陷阱** + 接线。

用户 2026-10-31 的要求：有活动的时候大厅那颗入口会被活动顶替，导航进不去 ⇒
他会自己把故事点进去、停在准备战斗之类的地方再启动，路线要能从那里接着跑。

这条路线原先在 `RESUME_EXEMPT` 里，理由是「场景页会被 `battle_scene_visible` 判成局内，
接力会跳过状态机、直接把这一局交给战斗监督」。解法不是改那个判据（会影响 14 条路线），
而是**把场景页排在局内判据之前** —— 本文件第二条用例专门钉这件事。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.modes import MODE_SPECS, RESUME_EXEMPT
from auto_game_unified.games.epic7.side_story import detect_resume_point
from auto_game_unified.games.epic7.story import StoryState


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"

REFERENCE_WIDTH, REFERENCE_HEIGHT = 1982, 1132
_CACHE: dict[str, np.ndarray] = {}


def _load(path: Path) -> np.ndarray:
    key = str(path)
    if key not in _CACHE:
        raw = cv2.imread(key, cv2.IMREAD_COLOR)
        assert raw is not None, f"缺夹具 {path}"
        # 夹具多是 3200×2000，必须裁到基准；匹配层会按宽高比直接拒绝别的尺寸。
        _CACHE[key] = cv2.cvtColor(
            raw[:REFERENCE_HEIGHT, :REFERENCE_WIDTH], cv2.COLOR_BGR2RGB
        )
    return _CACHE[key]


def frame(name: str) -> np.ndarray:
    return _load(FIXTURES / "epic7_side_story" / f"{name}.png")


def other_route_frame(group: str, name: str) -> np.ndarray:
    return _load(FIXTURES / f"epic7_{group}" / f"{name}.png")


def machine():
    spec = MODE_SPECS["side_story"]
    return spec.build_machine(TEMPLATE_ROOT, spec.default_state)


class SideStoryResumePointTests(unittest.TestCase):
    def test_each_recorded_page_lands_on_the_right_state(self):
        """十四个可停靠画面各落一颗钉子。

        落点状态不是顺手记的：主线那两支动作（`prepare_battle` / 战斗控件观测）
        依赖进来时的状态才肯点，拨错就是原地干等到超时。
        """

        cases = {
            "complete_popup": ("完成故事", StoryState.WAIT_RESULTS),
            "scene": ("场景页", StoryState.STAGE),
            "scene_without_arrow": ("场景页", StoryState.STAGE),
            "battle_clear": ("通关结算", StoryState.WAIT_RESULTS),
            "story_clear": ("通关结算", StoryState.WAIT_RESULTS),
            "map": ("关卡地图", StoryState.STAGE),
            "episode_detail": ("Episode详情", StoryState.STAGE),
            "side_story": ("支线故事", StoryState.STAGE),
            "team": ("队伍准备", StoryState.TEAM),
            "team_direct": ("队伍准备", StoryState.TEAM),
            "helper_select": ("助手选择", StoryState.TEAM),
            "skip_confirm": ("跳过确认", StoryState.WAIT_SKIP_CONFIRM),
            "story_skip": ("剧情播放", StoryState.ACTIVE),
            "results": ("结算确认", StoryState.WAIT_RESULTS),
        }
        for name, (page, state) in cases.items():
            with self.subTest(page=name):
                point = detect_resume_point(machine(), frame(name))

                self.assertIsNotNone(point, name)
                self.assertEqual(page, point.page)
                self.assertEqual(state, point.state)

    def test_the_scene_page_is_not_mistaken_for_a_battle(self):
        """⚠️ 这条就是当年「支线不能接力」的全部理由，别改成先判局内。

        前提还在：场景页 `battle_scene_visible` 仍然是 `True`（白色结构撞判据）。
        但 `replay` 排在它前面 ⇒ 落点是场景页 / STAGE；排反了就会被当成
        「已承诺战斗」交给战斗监督，停在场景页启动会一路磨到绝对超时。
        """

        for name in ("scene", "scene_without_arrow"):
            with self.subTest(page=name):
                screen = frame(name)

                self.assertTrue(battle_scene_visible(screen))

                point = detect_resume_point(machine(), screen)

                self.assertEqual("场景页", point.page)
                self.assertEqual(StoryState.STAGE, point.state)

    def test_a_real_battle_frame_is_still_a_battle(self):
        """反向条：真打斗那一帧十二个锚点全不命中，必须落到「战斗中」。

        用户也可以停在战斗里启动 —— 那一支交给战斗监督（同主线）。
        """

        point = detect_resume_point(
            machine(), other_route_frame("story", "battle_auto_on_live_20260809")
        )

        self.assertIsNotNone(point)
        self.assertEqual("战斗中", point.page)
        self.assertEqual(StoryState.WAIT_BATTLE, point.state)

    def test_the_complete_popup_wins_over_the_pages_it_covers(self):
        """弹窗是模态遮罩：同一帧上 `results_confirm` / `complete` 也命中。

        它必须最先判 —— 实测被遮住的结算页 `results_confirm` 从 0.9786 掉到 0.4857，
        顺序反了会拿一帧「认不准的结算页」去拨状态。
        """

        screen = frame("complete_popup")
        probe = machine()

        self.assertIsNotNone(probe._locate(screen, "results_confirm"))
        self.assertEqual("完成故事", detect_resume_point(probe, screen).page)

    def test_an_unrelated_page_is_not_a_resume_point(self):
        """别的路线的页面认不出 ⇒ 回退到「回大厅重新导航」，与加接力前一致。"""

        self.assertIsNone(
            detect_resume_point(machine(), other_route_frame("navigation", "arena_list"))
        )


class SideStoryResumeWiringTests(unittest.TestCase):
    def test_the_probe_is_wired_and_the_exemption_is_gone(self):
        spec = MODE_SPECS["side_story"]

        self.assertIsNotNone(spec.resume_probe)
        self.assertNotIn("side_story", RESUME_EXEMPT)

    def test_the_probe_actually_moves_the_state_machine(self):
        """接线不只「挂上了」：真探针跑一帧，状态机必须被拨到报出来的那个状态。

        漏 `machine.resume_from(...)` 时接力看起来是命中的（日志照打「开局=接力」），
        状态机却没动 —— 这条是 `modes._resume_probe` 那个工厂的第二道护栏。
        """

        spec = MODE_SPECS["side_story"]
        probe = spec.build_machine(TEMPLATE_ROOT, spec.default_state)

        point = spec.resume_probe(probe, frame("map"), None)

        self.assertEqual("关卡地图", point.page)
        self.assertEqual(StoryState.STAGE.value, point.state)
        self.assertEqual(StoryState.STAGE, probe.state)
        self.assertEqual(StoryState.STAGE, probe.resumed_from)


if __name__ == "__main__":
    unittest.main()
