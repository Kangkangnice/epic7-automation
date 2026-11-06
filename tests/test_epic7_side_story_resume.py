"""支线故事开局接力：落点判定 + **顺序陷阱** + 接线 + PC 期次主页中间层。

用户 2026-10-31 的要求：有活动的时候大厅那颗入口会被活动顶替，导航进不去 ⇒
他会自己把故事点进去、停在准备战斗之类的地方再启动，路线要能从那里接着跑。

这条路线原先在 `RESUME_EXEMPT` 里，理由是「场景页会被 `battle_scene_visible` 判成局内，
接力会跳过状态机、直接把这一局交给战斗监督」。解法不是改那个判据（会影响 14 条路线），
而是**把场景页排在局内判据之前** —— 本文件第二条用例专门钉这件事。

2026-11-06 补「期次主页」：PC 的「快速入场」比模拟器多一层中间页，12:59 真机
在这一页 `UnrecognizedScreen` 干等 60 秒超时，而且它也不在接力落点里。
下面 `SideStoryEventHomeResumeTests` 用 **PC 模板根**造状态机（`pc_machine()`），
因为这两颗判据图只放 `templates/side_story/pc/`，模拟器侧必须是空元组。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.modes import MODE_SPECS, RESUME_EXEMPT
from auto_game_unified.games.epic7.side_story import detect_resume_point
from auto_game_unified.games.epic7.story import StoryState
from auto_game_unified.games.epic7.template_paths import resolve_template_dir
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


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
    """模拟器：普通 `Path` 就是模拟器口径（`template_paths.is_pc` 明确认这一条）。"""
    spec = MODE_SPECS["side_story"]
    return spec.build_machine(TEMPLATE_ROOT, spec.default_state)


def pc_machine():
    """PC 模板根：只有它才会把 `templates/side_story/pc/*.png` 解析进来。

    ⚠️ 光调 `matcher.set_active_backend("pc")` 没用 —— 决定「去哪个目录取图」的是
    `TemplateDir` 上的 backend，不是匹配器那个全局量。
    """
    spec = MODE_SPECS["side_story"]
    return spec.build_machine(
        resolve_template_dir(TEMPLATE_ROOT, "pc"), spec.default_state
    )


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


class SideStoryEventHomeResumeTests(unittest.TestCase):
    """PC 独有的一层中间页：期次主页（「故事 / 奖励 / PV」）。

    2026-11-06 12:58 真机日志：`enter_quick_entry` 点完预期落
    `Episode详情/关卡地图`，实际落到这里，14 个旧原子全 `None` ⇒
    12:59 干等 60 秒 `timeout_stage`。补齐后它既是接力落点、也要有运行期动作。
    """

    def test_the_event_home_is_a_resume_point_on_pc(self):
        point = detect_resume_point(pc_machine(), frame("event_home"))

        self.assertIsNotNone(point)
        self.assertEqual("期次主页", point.page)
        self.assertEqual(StoryState.STAGE, point.state)
        self.assertIsNone(point.entry, "期次主页不在导航链上，不许假装已经到过某一级")

    def test_both_tabs_are_independent_anchors_for_the_same_page(self):
        """两颗标签各自都能独立把这一页认出来（跨期换皮时的冗余）。"""
        screen = frame("event_home")
        probe = pc_machine()

        for name in ("event_home_reward", "event_home_pv"):
            with self.subTest(anchor=name):
                match = probe._locate(screen, name)
                self.assertIsNotNone(match, name)
                self.assertGreaterEqual(match.score, 0.99)

        self.assertEqual("期次主页", detect_resume_point(probe, screen).page)

    def test_the_same_period_hub_page_is_not_mistaken_for_the_event_home(self):
        """⚠️ 最硬的负例：同一期美术、同一套立绘，右侧却是「支线故事」菜单。

        如果判据是靠本期背景/角色命中的，这张会一起翻车 —— 那正是
        「模板不许含会变内容」要拦的东西。实测两颗锚点在 hub 页都 < 0.41。
        """
        screen = frame("event_home_hub")
        probe = pc_machine()

        for name in ("event_home_reward", "event_home_pv"):
            with self.subTest(anchor=name):
                self.assertIsNone(probe._locate(screen, name))

        point = detect_resume_point(probe, screen)
        self.assertIsNotNone(point)
        self.assertEqual("支线故事", point.page, "hub 页该落回「支线故事」，不是「期次主页」")

    def test_the_anchors_are_pc_only_and_the_emulator_behaves_as_before(self):
        """模拟器侧两张图都缺席 ⇒ 原子空元组 ⇒ 判据与动作整体不启用。

        这是 PC/模拟器隔离铁律的直接检验：不是「模拟器上分数低一点」，
        而是压根没有这个原子。
        """
        screen = frame("event_home")
        probe = machine()

        self.assertEqual((), probe.side.event_home_reward)
        self.assertEqual((), probe.side.event_home_pv)
        self.assertIsNone(probe._locate(screen, "event_home_reward"))
        self.assertIsNone(probe._locate(screen, "event_home_pv"))
        self.assertIsNone(detect_resume_point(probe, screen))
        with self.assertRaises(UnrecognizedScreen):
            probe.next_action(screen)

    def test_the_runner_leaves_the_event_home_instead_of_timing_out(self):
        """光认出还不够：状态机必须给出「点故事」这个前进动作。"""
        action = pc_machine().next_action(frame("event_home"))

        self.assertIsNotNone(action)
        self.assertEqual("enter_event_story", action.name)
        self.assertEqual((1710, 440), action.point)
        self.assertEqual("期次主页", action.source_page)
        self.assertIn("Episode详情", action.target_pages)
        self.assertIn("关卡地图", action.target_pages)
        # 含这两项会分别造成「静默降级」与「期次主页↔hub 无限来回点」。
        self.assertNotIn("期次主页", action.target_pages)
        self.assertNotIn("支线故事", action.target_pages)

    def test_quick_entry_accepts_the_event_home_as_a_landing_page(self):
        """另一半契约：`快速入场` 点完**本来就会**落到这一页。

        少了这个落点，页面认得再准也会被转场验收判成「目标页面未出现」。
        """
        action = pc_machine().next_action(frame("event_home_hub"))

        self.assertIsNotNone(action)
        self.assertEqual("enter_quick_entry", action.name)
        self.assertIn("期次主页", action.target_pages)


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
