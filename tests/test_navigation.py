from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.core.matcher import find_best_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7 import story as story_module
from auto_game_unified.games.epic7.navigation import (
    REFERENCE_SIZE,
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
ARENA_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB)


def arena_fixture(name: str):
    image = cv2.cvtColor(
        cv2.imread(str(ARENA_FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )
    return image[:1132, :1982]


def story_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_story" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def fodder_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_fodder" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def hero_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_hero" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def global_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_global" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def shop_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_shop_refresh" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def world_boss_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_world_boss" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


class NavigationTests(unittest.TestCase):
    def test_classifies_current_secret_shop_page(self):
        navigator = self.navigator([])

        observation = navigator.observe(shop_fixture("shop_top_live"))

        self.assertEqual("shop_refresh", observation.name)

    def test_shop_navigation_retries_only_until_secret_shop_is_confirmed(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        navigator = self.navigator(
            [shop_fixture("shop_top_live"), shop_fixture("shop_top_live")],
            clicks=clicks,
            logs=logs,
        )

        navigator.navigate(
            "shop_refresh",
            lobby_screen=shop_fixture("lobby_shop_entry"),
        )

        self.assertEqual(1, len(clicks))
        self.assertTrue(40 <= clicks[0][0] <= 150)
        self.assertTrue(470 <= clicks[0][1] <= 610)
        self.assertTrue(any("模式=刷书签 状态=导航完成" in log for log in logs))

    def test_shop_navigation_accepts_animated_lobby_entry_low_score_frame(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [shop_fixture("shop_top_live"), shop_fixture("shop_top_live")],
            clicks=clicks,
        )

        navigator.navigate(
            "shop_refresh",
            lobby_screen=shop_fixture("lobby_shop_entry_low_score_20260831"),
        )

        self.assertEqual(1, len(clicks))
        self.assertTrue(35 <= clicks[0][0] <= 130)
        self.assertTrue(485 <= clicks[0][1] <= 555)

    def test_shop_navigation_recovers_from_transitional_lobby_frame(self):
        """回归守卫：home_return v2 是「第一帧认出大厅就返回」，偶尔会把一个还在动画的
        过渡大厅帧交进来；这种帧上 ``lobby_shop_entry``（大厅左侧入口）可能没过阈，
        曾经的表现是 ``_transition`` 直接抛「缺少导航锚点」、且因为发生在 ``_enter_mode``
        里、跑在 ``run_mode`` 的 try 之外，每日任务只收到一个无声的 ``✗``。

        修复后：传入帧锚点没命中时，先 ``_wait_for_page("lobby")`` 等一帧**稳定的**大厅
        再认一次，应当正常进店（2026-09-26 刷书签那次就是这么挂的）。
        """
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        # 过渡帧：大厅本体在，但左侧商店入口区域（evidence.shop_refresh.REGIONS
        # ["lobby_shop_entry"] = (0,430,220,230)）被涂掉，模拟「大厅还在动画、
        # 入口没渲染出来」的瞬间——这种帧上 lobby_shop_entry 锚点会没过阈。
        transitional = fixture("lobby").copy()
        transitional[430:660, 0:220] = 0
        navigator = self.navigator(
            [
                fixture("lobby"),
                fixture("lobby"),
                shop_fixture("shop_top_live"),
                shop_fixture("shop_top_live"),
                shop_fixture("shop_top_live"),
            ],
            clicks=clicks,
            logs=logs,
        )

        navigator.navigate("shop_refresh", lobby_screen=transitional)

        # 先在过渡帧上没认到锚点 → 重等稳定大厅 → 在稳定大厅帧上点到入口（只点一次）。
        self.assertEqual(1, len(clicks))
        self.assertTrue(
            any("重试=重新等待稳定来源页" in log for log in logs),
            "应当因过渡帧锚点缺失而触发『重等稳定来源页』",
        )
        self.assertTrue(
            any("模式=刷书签 状态=导航完成" in log for log in logs)
        )

    def test_navigator_selects_platform_thresholds_explicitly(self):
        runtime = Runtime(lambda: fixture("lobby"), lambda _point: None)
        emulator = Epic7Navigator(build_navigation_templates(TEMPLATES), runtime)
        pc = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            backend="pc",
        )

        self.assertEqual(0.65, emulator._story_thresholds["skip"])
        self.assertEqual(0.55, pc._story_thresholds["skip"])
        self.assertEqual(0.88, emulator._arena_thresholds["list_ready"])
        self.assertEqual(0.75, pc._arena_thresholds["list_ready"])

    def test_classifies_friendship_points_popup(self):
        navigator = self.navigator([])

        observation = navigator.observe(story_fixture("friendship_points_popup"))

        self.assertEqual("friendship_points_popup", observation.name)

    def test_return_home_closes_friendship_points_popup_before_confirming_lobby(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [popup, popup, fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(1, len(clicks))
        self.assertTrue(870 <= clicks[0][0] <= 1050)
        self.assertTrue(885 <= clicks[0][1] <= 1010)
        self.assertEqual([], backs)

    def test_return_home_closes_pc_friendship_points_popup_without_unknown_wake(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        popup = global_fixture("friendship_points_pc_20260830")
        navigator = self.navigator(
            [popup, popup, fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(1, len(clicks))
        self.assertTrue(900 <= clicks[0][0] <= 1020)
        self.assertTrue(900 <= clicks[0][1] <= 1000)
        self.assertEqual([], backs)

    def test_story_transition_closes_friendship_points_popup_before_destination(self):
        clicks: list[tuple[int, int]] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [popup, popup, fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby"))

        self.assertEqual(2, len(clicks))
        self.assertEqual((1790, 326), clicks[0])
        self.assertTrue(870 <= clicks[1][0] <= 1050)
        self.assertTrue(885 <= clicks[1][1] <= 1010)

    def test_wait_for_lobby_closes_friendship_points_popup(self):
        clicks: list[tuple[int, int]] = []
        popup = story_fixture("friendship_points_popup")
        navigator = self.navigator(
            [
                popup,
                popup,
                fixture("lobby"),
                fixture("lobby"),
                fixture("story_stage"),
                fixture("story_stage"),
            ],
            clicks=clicks,
        )

        navigator.navigate("story")

        self.assertEqual(2, len(clicks))
        self.assertTrue(870 <= clicks[0][0] <= 1050)
        self.assertTrue(885 <= clicks[0][1] <= 1010)
        self.assertEqual((1790, 326), clicks[1])

    def test_classifies_arena_rank_promotion_popup(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_arena"
                    / "rank_promotion_master.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("arena_rank_promotion", navigator.observe(screen).name)

    def test_return_home_closes_arena_rank_promotion_before_confirming_lobby(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        rank_popup = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_arena"
                    / "rank_promotion_master.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )
        navigator = self.navigator(
            [rank_popup, rank_popup, fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual(1, len(clicks))
        self.assertTrue(700 <= clicks[0][0] <= 1220)
        self.assertTrue(930 <= clicks[0][1] <= 1132)
        self.assertEqual([], backs)

    def test_return_home_stops_at_the_resume_point_without_pressing_back(self):
        """接力钩子命中就当场停住：一张 Back 都不发，把当前这一帧原样交还调用方。"""
        backs: list[bool] = []
        screens = [arena_fixture("selected"), arena_fixture("selected")]
        navigator = self.navigator(screens, backs=backs)
        probed: list[np.ndarray] = []

        def stop_probe(screen):
            probed.append(screen)
            return True

        screen = navigator.return_home(stop_probe=stop_probe)

        self.assertEqual([], backs)
        # 第一帧不算稳定帧，钩子只在第二帧被问过一次；交还的就是第二帧那个对象本身。
        self.assertEqual([screens[1]], probed)
        self.assertIs(screens[1], screen)

    def test_return_home_keeps_returning_while_the_resume_probe_misses(self):
        """没命中就照旧一路返回；每确认一页都会再问一次，直到回到大厅。"""
        backs: list[bool] = []
        navigator = self.navigator(
            [fixture("arena_mode"), fixture("arena_mode")] + [fixture("lobby")] * 2,
            backs=backs,
        )
        probed: list[np.ndarray] = []

        screen = navigator.return_home(
            stop_probe=lambda image: bool(probed.append(image)) or False
        )

        # 每一页都要再问一次（至少两帧：出发页 + 大厅），最后落在大厅。
        self.assertGreaterEqual(len(probed), 2)
        self.assertTrue(np.array_equal(fixture("lobby"), screen))

    def navigator(self, screens, clicks=None, backs=None, logs=None):
        # 假截图器：喂完序列后**回放最后一帧**（而不是抛 StopIteration）。
        # 真实环境里 ``capture()`` 每次都是新帧、永远不会「耗尽」——
        # 回家要「连续两帧稳定认出大厅」才返回，序列耗尽就抛是测试模型的偏差，
        # 不是业务 bug。回放最后一帧才符合「画面不动就一直停在那」的真实语义，
        # 也和 ``test_home_return_failure._sequence_runtime`` 同一个口径。
        images = list(screens)
        sent: list = []

        def capture():
            if images:
                sent.append(images.pop(0))
            return sent[-1]

        runtime = Runtime(
            capture,
            (clicks if clicks is not None else []).append,
            back=lambda: (backs if backs is not None else []).append(True),
            emit=(logs if logs is not None else []).append,
        )
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

    def clocked_navigator(self, capture, clicks=None, backs=None, logs=None):
        """返回大厅要「等满 15 秒转场窗口」才判定一次返回结束，验收相关用例
        必须让时钟真的往前走，否则永远等不到验收那一步。"""
        clock = [0.0]

        def sleep(seconds: float):
            clock[0] += seconds

        runtime = Runtime(
            capture,
            (clicks if clicks is not None else []).append,
            back=lambda: (backs if backs is not None else []).append(True),
            emit=(logs if logs is not None else []).append,
            monotonic=lambda: clock[0],
        )
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=sleep,
            poll_seconds=0.5,
            transition_frames=48,
        )

    def test_classifies_hero_list_with_grey_imprint_button(self):
        """选中 3S 满级英雄时刻印按钮置灰，英雄列表页仍须被识别。"""
        navigator = self.navigator([])
        hero_fixtures = ROOT / "tests" / "fixtures" / "epic7_hero"

        for name in ("list_grey_3s", "list_grey_3s_reddot", "list_grey_3s_light"):
            with self.subTest(fixture=name):
                screen = cv2.cvtColor(
                    cv2.imread(str(hero_fixtures / f"{name}.png")), cv2.COLOR_BGR2RGB
                )
                self.assertEqual("hero_list", navigator.observe(screen).name)

    def test_live_equipment_subpage_is_not_ready_hero_information(self):
        navigator = self.navigator([])

        observation = navigator.observe(
            hero_fixture("live_equipment_subpage_20260825")
        )

        self.assertEqual("hero_equipment", observation.name)

    def test_hero_navigation_retries_when_equipment_tab_does_not_exit(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = [0.0]
        equipment = hero_fixture("live_equipment_subpage_20260825")
        information = hero_fixture("list_unfiltered")

        def capture():
            # 进入英雄列表的大厅点击排在第一位。第一次切换标签后仍返回
            # 装备页，模拟点击被吞；第二次点击后才返回英雄信息页。
            return equipment if len(clicks) < 3 else information

        def sleep(seconds: float):
            clock[0] += seconds

        runtime = Runtime(
            capture,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock[0],
        )
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=sleep,
            poll_seconds=0.5,
            transition_frames=24,
        )

        navigator.navigate(
            "hero_synthesis", lobby_screen=fixture("lobby_animated_updated")
        )

        self.assertEqual([(65, 200), (65, 200)], clicks[1:])
        expected = [
            "进入标志=英雄装备已确认",
            "动作=切换英雄信息 尝试=1/4",
            "离开标志=未满足 当前子页=英雄装备",
            "动作=切换英雄信息 尝试=2/4",
            "离开标志=英雄装备已离开",
            "进入标志=英雄信息已到达",
            "模式=英雄合成 状态=导航完成 前提=英雄信息页已就绪",
        ]
        positions = [
            next(index for index, log in enumerate(logs) if text in log)
            for text in expected
        ]
        self.assertEqual(sorted(positions), positions)
        self.assertTrue(
            any("信息蓝=" in log and "装备蓝=" in log for log in logs)
        )

    def test_hero_navigation_stops_after_four_information_tab_clicks(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = [0.0]
        equipment = hero_fixture("live_equipment_subpage_20260825")

        def sleep(seconds: float):
            clock[0] += seconds

        runtime = Runtime(
            lambda: equipment,
            clicks.append,
            emit=logs.append,
            monotonic=lambda: clock[0],
        )
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=sleep,
            poll_seconds=0.5,
            transition_frames=48,
        )

        with self.assertRaisesRegex(RuntimeError, "点击4次后仍未离开"):
            navigator.navigate(
                "hero_synthesis", lobby_screen=fixture("lobby_animated_updated")
            )

        self.assertEqual([(65, 200)] * 4, clicks[1:])
        self.assertTrue(any("尝试=4/4" in log for log in logs))
        self.assertFalse(any("状态=导航完成" in log for log in logs))

    def test_classifies_recorded_pages_with_required_anchors(self):
        navigator = self.navigator([])

        self.assertEqual("lobby", navigator.observe(fixture("lobby")).name)
        self.assertEqual("lobby", navigator.observe(fixture("lobby_animated_updated")).name)
        self.assertEqual("exit_dialog", navigator.observe(fixture("exit_dialog")).name)
        self.assertEqual("exit_dialog", navigator.observe(fixture("exit_dialog_updated")).name)
        self.assertEqual("story_ready", navigator.observe(fixture("story_stage")).name)
        self.assertEqual("arena_mode", navigator.observe(fixture("arena_mode")).name)
        self.assertEqual("arena_ready", navigator.observe(fixture("arena_list")).name)
        self.assertEqual(
            "battle_menu", navigator.observe(fixture("expedition_battle_menu")).name
        )
        self.assertEqual(
            "season_menu", navigator.observe(fixture("expedition_season_menu")).name
        )
        self.assertEqual(
            "expedition_home", navigator.observe(fixture("expedition_home")).name
        )

    def test_classifies_a_story_only_stage_as_story_ready(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "story_watch_ready_live_20260810.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_classifies_latest_episode4_story_page_as_story_ready(self):
        navigator = self.navigator([])

        observation = navigator.observe(fixture("story_watch_ep4"))

        self.assertEqual("story_ready", observation.name)

    def test_classifies_live_story_playback_during_startup_recovery(self):
        navigator = self.navigator([])

        observation = navigator.observe(fixture("story_playing_live_20260813"))

        self.assertEqual("story_playing", observation.name)

    def test_classifies_live_story_skip_confirmation_as_story_not_exit(self):
        navigator = self.navigator([])

        observation = navigator.observe(
            story_fixture("skip_confirm_persisted_live_20260813")
        )

        self.assertEqual("story_skip_confirm", observation.name)

    def test_return_home_finishes_story_skip_before_using_game_back(self):
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        playing = fixture("story_playing_live_20260813")
        confirm = story_fixture("skip_confirm_persisted_live_20260813")
        navigator = self.navigator(
            [
                playing,
                playing,
                confirm,
                confirm,
                fixture("story_stage"),
                fixture("story_stage"),
                fixture("lobby"),
                fixture("lobby"),
            ],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        # 前两下是「跳过剧情」（跳过按钮 + 跳过确认）；**之后不许点页内返回箭头** ——
        # 一律按 ESC 是用户 2026-09-25 定的口径。
        self.assertGreaterEqual(len(clicks), 2)
        self.assertGreater(clicks[0][0], 1700)
        self.assertGreater(clicks[1][0], 850)
        self.assertFalse(
            any(x <= 120 and y <= 160 for x, y in clicks),
            f"跳完剧情又去点页内返回箭头了：{clicks}",
        )

    def test_story_navigation_confirms_latest_episode4_destination(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("story_watch_ep4")] * 12,
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby"))

        self.assertEqual([(1790, 326)], clicks)

    def test_navigation_uses_the_shared_story_watch_score(self):
        navigator = self.navigator([])
        screen = fixture("story_watch_ep4")

        shared = story_module.find_watch_story_button(
            screen, navigator.templates.story_watch
        )
        observation = navigator.observe(screen)

        self.assertIsNotNone(shared)
        self.assertAlmostEqual(shared.score, observation.confidence, places=6)

    def test_classifies_the_updated_battle_stage_as_story_ready(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "stage_battle_ready_updated.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_classifies_episode5_prepare_battle_without_background(self):
        navigator = self.navigator([])
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_story"
                    / "stage_prepare_battle_ep5.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertEqual("story_ready", navigator.observe(screen).name)

    def test_lobby_classification_does_not_depend_on_dynamic_profile_progress(self):
        navigator = self.navigator([])
        lobby = fixture("lobby").copy()
        lobby[35:200, 0:500] = 0

        self.assertEqual("lobby", navigator.observe(lobby).name)

    def test_return_home_cancels_visible_exit_dialog_after_two_frames(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("exit_dialog"), fixture("exit_dialog"), fixture("lobby"), fixture("lobby")],
            clicks=clicks,
        )

        navigator.return_home()

        self.assertEqual([(800, 740)], clicks)

    def test_return_home_cancels_updated_exit_dialog_after_two_frames(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("exit_dialog_updated"),
                fixture("exit_dialog_updated"),
                fixture("lobby"),
                fixture("lobby"),
            ],
            clicks=clicks,
        )

        navigator.return_home()

        self.assertEqual([(798, 741)], clicks)

    def test_cancelled_exit_dialog_waits_for_lobby_without_another_back(self):
        backs: list[bool] = []
        unknown = fixture("story_stage").copy()
        unknown[930:1132, 1450:1920] = 0
        navigator = self.navigator(
            [
                fixture("exit_dialog_updated"),
                fixture("exit_dialog_updated"),
                unknown,
                unknown,
                fixture("lobby"),
                fixture("lobby"),
            ],
            backs=backs,
        )

        navigator.return_home()

        self.assertEqual([], backs)

    def test_unknown_page_never_clicks_the_screen_centre(self):
        """认不出的页面**不许去点屏幕中央** —— 这是事故，不是功能。

        ⚠️ 这条用例 2026-09-26 整个翻过来了：它以前守的是「点中央唤醒 4 次」，
        那正是用户当场抓包的现象（「眼睛瞎了一直点中间」）。回家现在只有一套
        实现（v2），认不出就按 ESC 兜底 —— **屏幕中央一个点都不许落**。
        """
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        unknown = fixture("story_stage").copy()
        # Remove the known stage button so this remains a valid but unknown game frame.
        unknown[930:1132, 1450:1920] = 0
        unknown[:52] = 0
        unknown[:, 1920:] = 0
        navigator = self.navigator(
            [unknown] * 11 + [fixture("lobby"), fixture("lobby")],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertFalse(
            any(900 <= x <= 1100 and 500 <= y <= 650 for x, y in clicks),
            f"认不出的页面上点了屏幕中央：{clicks}",
        )

    def test_story_ready_does_not_click_the_in_page_back_arrow(self):
        """关卡页回家不点左上角那颗页内返回箭头 —— 一律按 ESC。

        用户 2026-09-25 定下的口径：「新开发的这个一定要都按 ESC 来」，
        点死坐标（页内箭头那颗）换分辨率 / UI 微调就崩。
        """
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        navigator = self.navigator(
            [
                fixture("story_stage"), fixture("story_stage"),
                fixture("lobby"), fixture("lobby"),
            ],
            clicks=clicks,
            backs=backs,
        )

        navigator.return_home()

        self.assertFalse(
            any(x <= 120 and y <= 160 for x, y in clicks),
            f"关卡页上点了页内返回箭头：{clicks}",
        )

    def test_a_stuck_page_stops_instead_of_pressing_esc_forever(self):
        """怎么退都退不动 ⇒ **报错收场**，不许把 ESC 按满预算还继续磨。

        这是老流程「返回无效就停」那条规矩的 v2 版本：老流程是「没有页内箭头就
        报错」，v2 一律按 ESC，所以判据变成「按了也没用 ⇒ 报错」。
        守的是同一件事 —— **别把一个没用的动作重复到上限**。
        """
        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        logs: list[str] = []
        stuck = fixture("expedition_battle_menu")
        navigator = self.clocked_navigator(
            lambda: stuck, clicks=clicks, backs=backs, logs=logs
        )

        with self.assertRaisesRegex(RuntimeError, "返回首页失败"):
            navigator.return_home()

        # 「按满 8 次」是上限，不是目标：这里必须**远小于** 8 就认输。
        self.assertLess(len(backs), 8, f"卡住的页面上把 ESC 按满了：{len(backs)} 次")

    def test_ineffective_navigation_click_is_retried_after_the_verify_window(self):
        """点了导航锚点但页面纹丝不动：验收窗口一到就提前重试。

        实机日志 epic7_shop_refresh.log 2026-09-10 里三次点同一个坐标 (82,521)，
        前两次各白等 92 秒才重试。这条用例盯的就是「第一次没生效到第二次点击之间
        只隔了验收窗口，而不是整个转场窗口（48 帧 ≈ 24 秒）」。
        """
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        click_times: list[float] = []
        clock = [0.0]

        def sleep(seconds: float):
            clock[0] += seconds

        def click(point):
            clicks.append(point)
            click_times.append(clock[0])

        lobby = fixture("lobby")
        arena_mode = fixture("arena_mode")
        arena_list = fixture("arena_list")

        def capture():
            if len(clicks) <= 1:
                return lobby  # 第一次点击之后：页面没动
            if len(clicks) == 2:
                return arena_mode  # 第二次点击才真的换了页
            return arena_list

        runtime = Runtime(
            capture,
            click,
            back=lambda: None,
            emit=logs.append,
            monotonic=lambda: clock[0],
        )
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=sleep,
            poll_seconds=0.5,
            transition_frames=48,
        )

        navigator.navigate("arena", lobby_screen=lobby)

        self.assertEqual(3, len(clicks))
        self.assertTrue(any("点击验收=无效" in log for log in logs))
        self.assertTrue(any("点击验收=生效" in log for log in logs))
        gap = click_times[1] - click_times[0]
        self.assertGreaterEqual(gap, Epic7Navigator._CLICK_VERIFY_SECONDS)
        self.assertLess(gap, 12.0)

    def test_story_navigation_confirms_destination_before_returning(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("lobby"), fixture("lobby"), fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story")

        self.assertEqual([(1790, 326)], clicks)

    def test_navigation_transition_never_clicks_a_static_unknown_screen(self):
        """转场里出现「静止但认不出」的画面：只等，不点（曾点屏幕中央 = 瞎猜）。

        ⚠️ 2026-09-26 翻转：以前这条守的是「点屏幕中央 (991, 566) 三次」，
        那正是用户抓包的「眼睛瞎了一直点中间」。点中央没有判据，现在只等画面自己变。
        """
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        unknown = fixture("story_stage").copy()
        unknown[930:1132, 1450:1920] = 0
        unknown[:52] = 0
        unknown[:, 1920:] = 0
        navigator = self.navigator(
            [unknown] * 7 + [fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
            logs=logs,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby"))

        self.assertEqual([(1790, 326)], clicks)
        self.assertTrue(any("不点任何地方" in log for log in logs))

    def test_story_navigation_accepts_the_animated_updated_lobby_anchor(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [fixture("story_stage"), fixture("story_stage")],
            clicks=clicks,
        )

        navigator.navigate("story", lobby_screen=fixture("lobby_animated_updated"))

        self.assertEqual(1, len(clicks))

    def test_arena_navigation_uses_mode_selection_page(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("arena_mode"), fixture("arena_mode"),
                fixture("arena_list"), fixture("arena_list"),
            ],
            clicks=clicks,
        )

        navigator.navigate("arena")

        self.assertEqual([(1795, 635), (710, 995)], clicks)

    def test_expedition_navigation_uses_verified_three_step_route(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("expedition_battle_menu"), fixture("expedition_battle_menu"),
                fixture("expedition_season_menu"), fixture("expedition_season_menu"),
                fixture("expedition_home"), fixture("expedition_home"),
            ],
            clicks=clicks,
        )

        navigator.navigate("expedition")

        self.assertEqual([(1827, 531), (465, 220), (1080, 357)], clicks)

    def test_expedition_navigation_accepts_remembered_season_tab(self):
        clicks: list[tuple[int, int]] = []

        def capture():
            if len(clicks) == 1:
                return fixture("expedition_season_menu")
            return fixture("expedition_home")

        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(capture, clicks.append),
            sleep=lambda _: None,
            transition_frames=12,
        )

        error = None
        try:
            navigator.navigate("expedition", lobby_screen=fixture("lobby"))
        except RuntimeError as caught:
            error = caught

        self.assertIsNone(error)
        self.assertEqual([(1827, 531), (1080, 357)], clicks)

    def test_classifies_season_menu_after_the_expedition_card_moved_to_the_right(self):
        """赛季轮换把「远征队」从中间挤到最右，赛季页仍须被识别。

        实机帧 runtime_diagnostics/epic7_expedition/20260917_185800：新赛季那排卡片
        是「战术档案/星座考验/远征队」（新增了星座考验），锚点搜索区域原先只罩中间
        那张卡 → 整页认不出来 → 落到未知画面唤醒点屏幕中央，表现成「点了中间那张卡」。
        """
        navigator = self.navigator([])

        observation = navigator.observe(
            fixture("expedition_season_menu_live_20260917")
        )

        self.assertEqual("season_menu", observation.name)
        self.assertGreaterEqual(observation.confidence, 0.82)

    def test_expedition_navigation_follows_the_card_after_season_rotation(self):
        """点「远征队」跟着名字走：上赛季在中间点 (1080,357)，这赛季在最右点 (1540,357)。"""
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("expedition_battle_menu"), fixture("expedition_battle_menu"),
                fixture("expedition_season_menu_live_20260917"),
                fixture("expedition_season_menu_live_20260917"),
                fixture("expedition_home"), fixture("expedition_home"),
            ],
            clicks=clicks,
        )

        navigator.navigate("expedition")

        self.assertEqual([(1827, 531), (465, 220), (1540, 357)], clicks)

    def test_season_menu_entry_anchor_only_matches_the_expedition_card(self):
        """区域放宽到整行后，匹配不能被旁边两张卡抢走。

        两个区域都是按新赛季实机帧量出来的卡片标题横带（画布 1982×1132）；
        夹具是冻结的，所以这些边界不会随着以后换赛季而失效。
        """
        navigator = self.navigator([])
        template = navigator.templates.expedition_entry
        screen = fixture("expedition_season_menu_live_20260917")

        own_card = find_best_template(
            screen,
            template,
            region=(1430, 300, 470, 115),  # 远征队（最右）
            reference_size=REFERENCE_SIZE,
        )
        other_cards = find_best_template(
            screen,
            template,
            region=(450, 300, 960, 115),  # 战术档案 + 星座考验
            reference_size=REFERENCE_SIZE,
        )

        self.assertIsNotNone(own_card)
        self.assertIsNotNone(other_cards)
        self.assertGreaterEqual(own_card.score, 0.90)
        self.assertLess(other_cards.score, 0.60)

    def test_classifies_recorded_fodder_navigation_pages(self):
        navigator = self.navigator([])

        self.assertEqual("lobby", navigator.observe(fixture("lobby_fodder")).name)
        self.assertEqual(
            "fodder_side_story", navigator.observe(fodder_fixture("side_story")).name
        )
        self.assertEqual(
            "fodder_special_book", navigator.observe(fodder_fixture("special_book")).name
        )
        self.assertEqual(
            "fodder_episode_detail",
            navigator.observe(fodder_fixture("episode_detail")).name,
        )
        self.assertEqual(
            "fodder_stage", navigator.observe(fodder_fixture("stage_3_7")).name
        )

    def test_fodder_stage_requires_both_3_7_title_and_prepare_button(self):
        navigator = self.navigator([])
        without_title = fodder_fixture("stage_3_7").copy()
        without_title[760:850, 850:1075] = 0

        self.assertNotEqual("fodder_stage", navigator.observe(without_title).name)

    def test_fodder_navigation_uses_verified_four_step_route(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fodder_fixture("side_story"), fodder_fixture("side_story"),
                fodder_fixture("special_book"), fodder_fixture("special_book"),
                fodder_fixture("episode_detail"), fodder_fixture("episode_detail"),
                fodder_fixture("stage_3_7"), fodder_fixture("stage_3_7"),
            ],
            clicks=clicks,
        )

        navigator.navigate("fodder", lobby_screen=fixture("lobby_fodder"))

        self.assertEqual(4, len(clicks))
        self.assertTrue(1700 <= clicks[0][0] <= 1915)
        self.assertTrue(380 <= clicks[0][1] <= 500)
        self.assertTrue(1520 <= clicks[1][0] <= 1905)
        self.assertTrue(900 <= clicks[1][1] <= 1010)
        self.assertTrue(790 <= clicks[2][0] <= 1290)
        self.assertTrue(995 <= clicks[2][1] <= 1105)
        self.assertTrue(1390 <= clicks[3][0] <= 1890)
        self.assertTrue(990 <= clicks[3][1] <= 1105)

    def test_black_frames_never_trigger_click_or_back(self):
        import numpy as np

        clicks: list[tuple[int, int]] = []
        backs: list[bool] = []
        navigator = self.navigator([np.zeros((1132, 1982, 3), dtype=np.uint8)] * 12, clicks, backs)

        with self.assertRaisesRegex(RuntimeError, "画面持续黑屏或非游戏帧"):
            navigator.return_home()

        self.assertEqual([], clicks)
        self.assertEqual([], backs)


if __name__ == "__main__":
    unittest.main()


class WorldBossNavigationTests(unittest.TestCase):
    """骑士团 → 世界首领战 导航链。

    这两页最容易出的错是「判成大厅」或「判成未知画面」：它们顶部保留了同一根
    「世界首领战」标题栏，底部又没有大厅那排图标，所以必须靠排他锚点单独认。
    """

    def navigator(self, screens, clicks=None):
        images = iter(screens)
        runtime = Runtime(lambda: next(images), (clicks if clicks is not None else []).append)
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

    def test_knights_home_and_world_boss_home_are_told_apart(self):
        navigator = self.navigator([])

        knights = navigator.observe(world_boss_fixture("knights_home"))
        home = navigator.observe(world_boss_fixture("worldboss_home"))
        exhausted = navigator.observe(world_boss_fixture("worldboss_home_exhausted"))

        self.assertEqual("knights_home", knights.name)
        self.assertEqual("worldboss_home", home.name)
        # 次数打完只是按钮变灰，页面本身还是同一页，导航链要照样能认出来。
        self.assertEqual("worldboss_home", exhausted.name)

    def test_lobby_with_knights_icon_is_still_the_lobby(self):
        """底部那枚骑士团盾牌图标是大厅常驻控件，不能拿它判「在骑士团页」。"""
        navigator = self.navigator([])

        observation = navigator.observe(world_boss_fixture("lobby_with_knights"))

        self.assertEqual("lobby", observation.name)

    def test_world_boss_pages_are_never_confused_with_lobby(self):
        navigator = self.navigator([])

        for name in ("knights_home", "worldboss_home", "worldboss_home_exhausted"):
            with self.subTest(fixture=name):
                self.assertNotEqual("lobby", navigator.observe(world_boss_fixture(name)).name)

    def test_knights_signin_popup_is_reported_instead_of_unknown(self):
        """每天第一次进骑士团会先弹签到达成度奖励弹窗。

        这个弹窗盖在骑士团主页上，实测把底页的 ``worldboss_entry`` 从 0.9890
        压到 **0.4477**（低于 0.85 门槛）—— 也就是说**弹窗期间认不出底页**。
        所以 observe 必须先报出「这是签到弹窗」，交给全局弹窗守卫点掉它；
        否则就会掉到「未知画面」，被拿去点屏幕中央（可能误点弹窗后面的东西）。
        """
        navigator = self.navigator([])

        popup = navigator.observe(world_boss_fixture("knights_signin_popup"))

        self.assertEqual("knights_signin_popup", popup.name)
        self.assertNotEqual("unknown", popup.name)

    def test_gift_support_popup_is_reported_instead_of_unknown(self):
        """进骑士团时团员赠送的支援资源到账弹窗（标题「领取支援物品」）。

        与签到弹窗同理：盖在骑士团主页上、压暗底页锚点，弹窗期间认不出底页。
        observe 必须先报出「这是领取支援弹窗」，交给全局弹窗守卫点掉；
        否则会掉到「未知画面」→ 连点中央 4 次都唤醒失败（2026-09-22 实跑就是这样卡住的）。
        """
        navigator = self.navigator([])

        popup = navigator.observe(world_boss_fixture("gift_support_popup"))

        self.assertEqual("gift_support_popup", popup.name)
        self.assertNotEqual("unknown", popup.name)

    def test_knights_home_is_recognized_again_once_the_signin_popup_is_closed(self):
        """弹窗点掉之后必须能正常认出骑士团主页（别把「压暗」当永久状态）。"""
        navigator = self.navigator([])

        after = navigator.observe(world_boss_fixture("knights_home_after_popup"))

        self.assertEqual("knights_home", after.name)

    def test_navigation_walks_lobby_then_knights_then_world_boss(self):
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                world_boss_fixture("knights_home"),
                world_boss_fixture("knights_home"),
                world_boss_fixture("worldboss_home"),
                world_boss_fixture("worldboss_home"),
            ],
            clicks=clicks,
        )

        navigator.navigate("world_boss", lobby_screen=world_boss_fixture("lobby_with_knights"))

        self.assertEqual(2, len(clicks))
        # 骑士团图标命中中心 + 世界首领战图标命中中心（都在画布坐标系里）。
        self.assertEqual((1215, 1027), clicks[0])
        self.assertEqual((449, 693), clicks[1])

    def test_resume_from_knights_home_skips_only_the_first_hop(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        images = iter(
            [world_boss_fixture("worldboss_home"), world_boss_fixture("worldboss_home")]
        )
        runtime = Runtime(lambda: next(images), clicks.append, emit=logs.append)
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

        navigator.navigate(
            "world_boss",
            already_at="knights_home",
            lobby_screen=world_boss_fixture("knights_home"),
        )

        self.assertEqual(1, len(clicks))
        self.assertEqual((449, 693), clicks[0])
        self.assertTrue(any("跳过回大厅与进入骑士团" in line for line in logs))

    def test_resume_from_world_boss_home_needs_no_navigation_at_all(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = Runtime(lambda: world_boss_fixture("worldboss_home"), clicks.append, emit=logs.append)
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

        navigator.navigate("world_boss", already_at="worldboss_home")

        self.assertEqual([], clicks)
        self.assertTrue(any("已在世界首领战主页" in line for line in logs))

    def test_resume_at_an_unlisted_page_is_rejected(self):
        navigator = self.navigator([])

        with self.assertRaisesRegex(ValueError, "导航不支持从页面"):
            navigator.navigate("world_boss", already_at="battle_menu")

    def test_other_routes_cannot_resume_into_world_boss_pages(self):
        navigator = self.navigator([])

        with self.assertRaisesRegex(ValueError, "导航不支持从页面"):
            navigator.navigate("story", already_at="worldboss_home")
