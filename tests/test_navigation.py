from dataclasses import replace
from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.core import matcher
from auto_game_unified.core.matcher import find_best_template, find_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7 import story as story_module
from auto_game_unified.games.epic7.activity_column import ACTIVITY_SCROLL_STEP
from auto_game_unified.games.epic7.navigation import (
    REFERENCE_SIZE,
    Epic7Navigator,
    build_navigation_templates,
    load_template,
)
from auto_game_unified.games.epic7.navigation_plan import QUICK_MENU_PAGE


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


def tower_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_tower" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def hero_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_hero" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def labyrinth_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def labyrinth_pc_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone_pc" / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def moonlight_pc_fixture(name: str):
    path = ROOT / "tests" / "fixtures" / "epic7_moonlight_theater_pc" / f"{name}.png"
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

    def test_shop_navigation_accepts_entry_with_unread_badge(self):
        """回归守卫（2026-09-27 每日任务实跑）：大厅「秘密商店」入口会挂「未读新内容」的
        红 N 角标，那一帧上主模板只有 **0.8098**（门槛 0.82，差 0.01）⇒ 曾经被判
        「缺少导航锚点 lobby_shop_entry」，整条 shop_refresh 在每日任务里静默 ✗。

        该锚点登记第二张「带角标」候选模板后，同一帧应当**第一下就命中**——不再依赖
        「重等稳定来源页」那种等不到东西的重试。夹具就是当天那张真实失败帧。
        """
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        navigator = self.navigator(
            [shop_fixture("shop_top_live"), shop_fixture("shop_top_live")],
            clicks=clicks,
            logs=logs,
        )

        navigator.navigate(
            "shop_refresh",
            lobby_screen=shop_fixture("lobby_shop_entry_notified_20260927"),
        )

        self.assertEqual(1, len(clicks))
        self.assertTrue(40 <= clicks[0][0] <= 150)
        self.assertTrue(480 <= clicks[0][1] <= 610)
        self.assertTrue(any("模式=刷书签 状态=导航完成" in log for log in logs))
        self.assertFalse(
            any("重试=重新等待稳定来源页" in log for log in logs),
            "角标帧应当直接被第二张候选模板认出来，而不是去等角标消失",
        )

    def test_shop_entry_candidates_cover_clean_and_badged_lobby(self):
        """两颗候选模板必须**互补**：干净大厅靠主模板过阈、带角标大厅靠第二张过阈，
        且各自在对方的状态下都不过阈。少了任何一半，这条判据就是摆设。"""
        base, badged = build_navigation_templates(TEMPLATES).lobby_shop_entry
        region = (0, 430, 220, 230)
        threshold = 0.82

        def best(image, template) -> float:
            return find_best_template(
                image, template, region=region, reference_size=REFERENCE_SIZE
            ).score

        clean = shop_fixture("lobby_shop_entry_low_score_20260831")
        badged_frame = shop_fixture("lobby_shop_entry_notified_20260927")

        self.assertGreaterEqual(best(clean, base), threshold)
        self.assertLess(best(clean, badged), threshold)
        self.assertLess(best(badged_frame, base), threshold)
        self.assertGreaterEqual(best(badged_frame, badged), threshold)

    def test_arena_entry_candidate_ignores_the_changing_upper_half(self):
        """回归守卫（2026-10-05 每日任务实跑 ✗）：这颗入口按钮的**上半截会变** ——
        赛季刚开始时是「城堡图标 ＋ 全新赛季已开启」，之后换成「段位徽章 ＋ 段位字」
        （段位字还随段位变）。曾经把**整钮**裁进模板，于是那半截一变就对不上
        （真机只到 **0.7786** < 0.82）⇒ 整页认不出、导航与接力一起失效。

        因此模板只裁**底部那行固定标题的字形**。这条测试钉住两件事：
        ① 它在「赛季刚开始」与「显示段位」两种长相上**都过阈**；
        ② 两者分数**基本一致**（差别极小）—— 一旦有人把会变的上半截再裁回去，
           这两张帧的分数就会明显拉开，②会立刻红。
        """
        _novice, regular = build_navigation_templates(TEMPLATES).novice_arena
        region = (400, 780, 650, 352)
        threshold = 0.82

        def best(image) -> float:
            return find_best_template(
                image, regular, region=region, reference_size=REFERENCE_SIZE
            ).score

        # 上半截：城堡图标 +「全新赛季已开启」（用户 2026-10-05 00:42 截图）
        season_start = best(fixture("arena_mode_regular_20261005"))
        # 上半截：段位徽章 +「挑战者V」（同日 15:02 真机帧，就是那次失败的现场）
        rank_shown = best(fixture("arena_mode_regular_rank_20261005"))

        self.assertGreaterEqual(season_start, threshold)
        self.assertGreaterEqual(rank_shown, threshold)
        self.assertLess(
            abs(season_start - rank_shown),
            0.05,
            "模板不该依赖按钮上半截——两种长相上的分数必须基本一致",
        )

    def test_arena_novice_entry_candidate_still_matches_the_novice_look(self):
        """新手期那张候选模板不能因为改版而失效（账号一旦回到新手期还得认）。

        注：新的纯字形候选在新手帧上也会命中（`竞技场` 是 `新手竞技场` 的后缀），
        这**无害** —— 同一颗按钮、同一个点击目标；这里只钉住旧候选本身还成立。
        """
        novice, _regular = build_navigation_templates(TEMPLATES).novice_arena
        score = find_best_template(
            fixture("arena_mode"),
            novice,
            region=(400, 780, 650, 352),
            reference_size=REFERENCE_SIZE,
        ).score
        self.assertGreaterEqual(score, 0.82)

    def test_battle_entry_ignores_the_event_badge_hanging_over_another_row(self):
        """回归守卫（2026-10-19 08:14 每日任务实跑 ✗ 迷宫强化石）：「战斗」入口的模板
        以前把**上方那条 EVENT 标**一起裁了进去（旧图 165x87，标占 y 1~24）。

        那条标是**活动期才挂、而且会挂到不同入口上**的：10-19 那天它挂在「竞技场」
        上方（现场帧 `lobby_battle_badge_on_arena_live_20261019`）⇒ 模板里那一格空着
        ⇒ 全区域最高只有 **0.6749**（阈 0.82）⇒ `页面[大厅]缺少导航锚点 lobby_battle`
        ⇒ 迷宫强化石这条路**连点都没点**就失败关闭。

        所以模板改成只裁「战斗」二字。这条测试钉的三件事**都是依据**：
        ① 标挂在「竞技场」上的真帧要过阈（就是这次失败的现场）；
        ② 标挂在「战斗」上的真帧也要过阈，且两者分数接近
           —— 谁把那条标裁回去，①② 立刻红；
        ③ 模板里不许再出现那条蓝标（EVENT 标是纯蓝底，白字只有 r≈g≈b）。
        """
        template = build_navigation_templates(TEMPLATES).lobby_battle
        region = (1650, 430, 332, 220)
        threshold = 0.82

        def best(image) -> float:
            return find_best_template(
                image, template, region=region, reference_size=REFERENCE_SIZE
            ).score

        badge_on_arena = best(
            labyrinth_fixture("lobby_battle_badge_on_arena_live_20261019")
        )
        badge_on_battle = best(shop_fixture("current_probe"))

        self.assertGreaterEqual(
            badge_on_arena, threshold, "标挂在「竞技场」上时又认不出「战斗」了"
        )
        self.assertGreaterEqual(
            badge_on_battle, threshold, "标挂在「战斗」上时反而认不出了"
        )
        self.assertLess(
            abs(badge_on_arena - badge_on_battle),
            0.05,
            "两种挂法分数被拉开了，说明模板里又混进了会变的东西",
        )
        blue_over_red = int(
            np.max(template[:, :, 2].astype(int) - template[:, :, 0].astype(int))
        )
        self.assertLess(
            blue_over_red,
            40,
            "模板把那条 EVENT 蓝标裁进去了（它挂在哪个入口上是会变的）",
        )

    def test_the_battle_entry_step_clicks_on_the_frame_that_failed(self):
        """端到端：就那一步（大厅 → 战斗菜单）在 10-19 的现场帧上要真点得下去。

        只断言模板分数不够 —— 生产路径是 `_transition` 里「认页 → 定位锚点 → 点击」，
        锚点定位失败那一层就是 `RuntimeError: 页面[大厅]缺少导航锚点 lobby_battle`。
        """
        clicks: list[tuple[int, int]] = []
        failed = labyrinth_fixture("lobby_battle_badge_on_arena_live_20261019")
        navigator = self.navigator(
            [failed, failed, labyrinth_fixture("battle_menu"), labyrinth_fixture("battle_menu")],
            clicks=clicks,
        )

        navigator._transition(
            "lobby", ("battle_menu",), "lobby_battle", "进入战斗菜单"
        )

        self.assertEqual(1, len(clicks), "这一步该点且只点一下")
        x, y = clicks[0]
        # 「战斗」那一条按钮的底纹实测约 x 1770~1885 / y 512~575：落点必须还在里面，
        # 不能因为换裁剪把点击点带偏到「竞技场」那一条上去。
        self.assertTrue(1770 <= x <= 1885 and 512 <= y <= 575, f"落点跑出按钮：{clicks[0]}")

    def test_battle_entry_floor_stays_far_from_the_threshold(self):
        """全库地板：真大厅帧上「战斗」锚点最低多少分，和 0.82 的门槛隔多远。

        ⚠️ 这里同时把**唯一那个例外**写在代码里：`lobby_animated_updated`（录屏压过的
        帧，字形被压粗、底纹被压暗）只到 **0.5790**，过不了阈。它不参与地板计算，
        但必须继续被 `observe()` 认成大厅 —— 那一天的身份由 `lobby_arena`（0.8483）
        与 `lobby_story`（0.8646）那两条锚点担着。**谁要是把 `lobby_arena` 再裁窄，
        这一页就会整页认不出**，这条断言会把那件事暴露出来。
        """
        navigator = self.navigator([])
        template = build_navigation_templates(TEMPLATES).lobby_battle
        region = navigator._REGIONS["lobby_battle"]

        def best(image) -> float:
            return find_best_template(
                image, template, region=region, reference_size=REFERENCE_SIZE
            ).score

        real_frames = [
            fixture("lobby"),
            fixture("lobby_fodder"),
            world_boss_fixture("lobby_with_knights"),
            fixture("lobby_activity_entry_live_20261006"),
            shop_fixture("current_probe"),
            labyrinth_fixture("lobby_battle_badge_on_arena_live_20261019"),
        ]
        floor = min(best(image) for image in real_frames)
        self.assertGreaterEqual(
            floor, 0.95, "真大厅帧的地板掉到 0.95 以下了，离 0.82 的门槛不够远"
        )
        self.assertGreater(
            floor - 0.82, 0.13, "地板与门槛的间隔不足 —— 换句话说门槛卡在分布里"
        )

        recorded = fixture("lobby_animated_updated")
        with self.subTest(case="录屏帧：锚点不过阈，但页面身份不能丢"):
            self.assertLess(best(recorded), 0.82)
            self.assertEqual("lobby", navigator.observe(recorded).name)

    def test_arena_mode_page_is_recognised_in_every_known_entry_look(self):
        """端到端：**每一种已知的入口长相**都要能把这一页认成 `arena_mode`。

        只断言锚点分数不够 —— `observe()` 还要左上角标题一起成立才算数，
        任何一半缺席都会让整页认不出来（这正是 2026-10-05 那次失败的形态）。
        夹具刻意覆盖「那内容会怎么变」：新手期 / 赛季刚开始 / 显示段位，三种都上。
        """
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(lambda: None, lambda point: None),
            sleep=lambda _: None,
        )

        for name in (
            "arena_mode",  # 新手期：「新手竞技场」
            "arena_mode_regular_20261005",  # 脱离新手期·赛季刚开始
            "arena_mode_regular_rank_20261005",  # 脱离新手期·显示段位
        ):
            with self.subTest(fixture=name):
                self.assertEqual("arena_mode", navigator.observe(fixture(name)).name)

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

    def test_navigator_uses_the_single_emulator_baseline_thresholds(self):
        """导航阈值只剩模拟器基线一套 —— 平台差异改由图片承担。

        以前导航器内部按平台挑两张门槛表（PC 整体放宽一档），那是拿模拟器图
        去认 PC 画面的止痛药。现在没有第二张表可挑，这里钉死「只有一套」。
        """
        runtime = Runtime(lambda: fixture("lobby"), lambda _point: None)
        navigator = Epic7Navigator(build_navigation_templates(TEMPLATES), runtime)

        self.assertEqual(0.65, navigator._story_thresholds["skip"])
        self.assertEqual(0.88, navigator._arena_thresholds["list_ready"])

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

    def test_classifies_arena_rank_reward_popup(self):
        """「段位升级奖励」—— 段位提升的**下一层**（2026-10-20 接）。

        2026-10-20 08:02 那次竞技场 ✗ 的现场帧。它必须**排在**
        ``arena_rank_promotion`` 之前判：这一页上「确认」按钮还在（实测 0.999，
        只是被弹窗压暗了），段位提升那条判据要「箭头 + 确认」两个都中，箭头已经
        消失 ⇒ 本来也不会串味；但先报出更具体的一页，日志里就不会只剩「页面=unknown」。
        """
        navigator = self.navigator([])

        observation = navigator.observe(
            global_fixture("arena_rank_reward_live_20261020")
        )

        self.assertEqual("arena_rank_reward_popup", observation.name)

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

    def test_equipment_subpage_is_recognized_by_its_own_template(self):
        """装备子页必须靠「装备图标选中态」模板认出，不能只靠刻印按钮的近似结构。

        为什么单独守这一条：上面那条用例只断言「认得对」，不管「靠什么认出来」。
        2026-08-29 的「移除旧 PC 模板镜像」把这个模板删掉后，模拟器侧没有副本，
        判据被 ``if exists() else None`` 静默跳过、转为靠「管理装备」按钮撞上刻印
        按钮的结构（0.50 阈值）才勉强认得出 —— 结果上面那条用例照样是绿的。
        2026-10-03 真机换了底部按钮样式，装备子页直接掉成 unknown，
        导航就停在英雄列表门口。所以这里连「依据」一起断言。
        """
        self.assertTrue(
            (TEMPLATES / "navigation" / "hero_equipment_tab_active.png").exists(),
            "模拟器侧缺少装备子页模板；模板不存在时该判据会被静默跳过",
        )
        navigator = self.navigator([])

        observation = navigator.observe(
            hero_fixture("live_equipment_subpage_20260825")
        )

        self.assertEqual("hero_equipment", observation.name)
        # 只有走对该模板才会这么高；退化路径（灰按钮结构 0.50）大约 0.6。
        self.assertGreaterEqual(observation.confidence, 0.95)

    def test_live_equipment_subpage_20261003_fixture_is_recognized(self):
        """2026-10-03 真机现场：装备子页被认成 ``unknown``，导航停在英雄列表门口。

        这是那次故障的**现场夹具**（用户截图）。两点说明：

        - 客户区 1920×1080 贴在 1982×1132 画布的 (0, 52)，右侧多出的一列是占位黑边；
          判据区域在 x 0~155，不受影响。
        - 原图上**用户标的红圈**已用 inpaint 抹掉（红圈压住模板约 12% 像素，留着会把
          分数从 0.976 拉到 0.767、低于 0.85 门槛）。抹除后实测 0.9759，与同场景干净
          夹具的 1.0000 只差填充插值的误差。

        修复前（模板缺失）这里返回 ``unknown``：这正是「判据静默降级」的现场。
        """
        navigator = self.navigator([])

        observation = navigator.observe(
            hero_fixture("live_equipment_subpage_20261003")
        )

        self.assertEqual("hero_equipment", observation.name)
        self.assertGreaterEqual(observation.confidence, 0.85)

    def test_anchor_template_missing_fails_at_construction(self):
        """判据锚点缺模板必须在**构造期**报错，不许静默降级成「判据不存在」。

        反向输入喂的是旧代码在模板被删时给出的那个结果（``None``），以及候选图
        一张都不剩的空元组。

        为什么单独守这一条：2026-08-29 那次模板误删之所以一直没暴露，就是因为
        缺模板时判据**悄悄不生效** —— 页面靠退化的结构匹配照样认得出，
        所有既有用例都是绿的。所以这里必须证明「缺模板 = 起不来」。
        """
        templates = build_navigation_templates(TEMPLATES)
        # 正向：真实模板根构建出来的锚点都在，构造成功。
        self.navigator([])

        with self.assertRaises(ValueError) as caught:
            Epic7Navigator(
                replace(templates, hero_equipment_tab_active=None),
                Runtime(lambda: None, lambda *_: None),
            )
        self.assertIn("hero_equipment_tab_active", str(caught.exception))

        # 空候选序列同样是「判据不存在」，不能只挡 None。
        with self.assertRaises(ValueError) as caught:
            Epic7Navigator(
                replace(templates, lobby_shop_entry=()),
                Runtime(lambda: None, lambda *_: None),
            )
        self.assertIn("lobby_shop_entry", str(caught.exception))

    # ---- 快捷菜单改道（2026-10-04）------------------------------------------------

    def test_quick_menu_page_is_recognized_and_never_reads_as_lobby(self):
        """快捷菜单开着时，必须报 ``quick_menu``。

        菜单是**盖在底页上的浮层**。在这张夹具上（``quick_menu_over_lobby``，底页是大厅）
        实测大厅锚点被压到 ``lobby_story 0.0343 / lobby_arena 0.3025 / lobby_battle 0.4160``
        —— 这一帧本身也过不了「双锚点」的大厅判据（会掉到 ``unknown``）。
        但**顺序仍必须是 ``quick_menu`` 在前**：迷宫那边记着「菜单展开时大厅右侧那套
        Episode 菜单照样可见」的形态，压暗程度随底页而变，排在后面就有被判成「已在大厅」
        提前收工的风险（那会让导航链直接跳过菜单这一步）。

        这一条同时钉住「页面名 == ``QUICK_MENU_PAGE`` 常量」——
        常量与 ``PAGE_LABELS`` 分了家就会在这里红。
        """
        navigator = self.navigator([])

        for name in ("quick_menu_over_lobby",):
            with self.subTest(fixture=name):
                observation = navigator.observe(fixture(name))
                self.assertEqual(QUICK_MENU_PAGE, observation.name)
                self.assertNotEqual("lobby", observation.name)

    def test_quick_menu_survives_a_holiday_overlay_on_the_menu_area(self):
        """菜单判据必须**扛得住「底页不同 + 节日装饰浮层」**。

        这是判据选型的**唯一依据**：大网格 ``quick_menu_grid_top`` 罩住整片菜单底图，
        在 ``epic7_global/pet_gift_live_20260928`` 这张帧上只有 **0.7987**
        （菜单区上盖着一份节日礼物装饰）—— 掉在 0.82 门槛之下，**那一帧就认不出菜单**。
        改成「两个入口图标同时命中」后，同样三张帧最低 **0.997**。

        这一条同时是**反向验证的靶子**：把判据换回网格的做法，它立刻红在 0.7987。
        """
        navigator = self.navigator([])

        for path in (
            ROOT / "tests" / "fixtures" / "epic7_labyrinth_stone" / "quick_menu.png",
            FIXTURES / "quick_menu_over_lobby.png",
            ROOT / "tests" / "fixtures" / "epic7_global" / "pet_gift_live_20260928.png",
        ):
            with self.subTest(frame=path.name):
                screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
                observation = navigator.observe(screen)
                self.assertEqual(QUICK_MENU_PAGE, observation.name)
                self.assertGreaterEqual(observation.confidence, 0.9)

    def test_lobby_quick_menu_button_matches_clean_and_badged_frames(self):
        """开菜单那颗蓝四格会挂**橙色未读角标**（角标里还可能带数字）。

        角标是**可变内容**，绝不能裁进模板 ⇒ 模板刻意只取「四格的下 3/4」
        （从角标下方起裁）。这一条证明该裁法**对有无角标都成立**：
        干净帧与带角标帧都要过阈，且落点一致（±2px）。
        """
        navigator = self.navigator([])
        templates = navigator.templates

        clean = world_boss_fixture("lobby_with_knights")   # 无角标
        dotted = fixture("lobby")                          # 有橙色角标
        centers = []
        for name, screen in (("clean", clean), ("dotted", dotted)):
            with self.subTest(frame=name):
                match = find_template(
                    screen,
                    templates.lobby_quick_menu_button,
                    0.82,
                    region=Epic7Navigator._REGIONS["lobby_quick_menu_button"],
                    reference_size=(1982, 1132),
                )
                self.assertIsNotNone(match, f"{name} 帧上蓝四格没过阈")
                centers.append(match.center)
                self.assertGreaterEqual(match.score, 0.82)

        self.assertLessEqual(abs(centers[0][0] - centers[1][0]), 2)
        self.assertLessEqual(abs(centers[0][1] - centers[1][1]), 2)

    def test_quick_menu_entry_templates_do_not_collide_with_the_bottom_bar(self):
        """菜单里的「英雄」/「骑士团」与大厅底部那条横排的图**不是同一张**。

        这是本次改道的**前提**：如果两者能互相匹配，就没必要新裁模板了。
        实测旧模板在菜单帧上只有 0.63 / 0.67（不过阈）。这一条把它钉死 ——
        哪天游戏把两处画成一样了，这里会红，提示「可以合并模板」；
        反过来若有人误把菜单锚点接到大厅底部模板上，也会红。
        """
        navigator = self.navigator([])
        templates = navigator.templates
        menu = fixture("quick_menu_over_lobby")

        for label, old_template, region in (
            ("英雄", templates.lobby_hero, (1400, 980, 180, 130)),
            ("骑士团", templates.lobby_knights, (1150, 960, 420, 150)),
        ):
            with self.subTest(entry=label):
                match = find_template(
                    menu,
                    old_template,
                    0.0,
                    region=region,
                    reference_size=(1982, 1132),
                )
                self.assertIsNotNone(match)
                self.assertLess(match.score, 0.82)

    def test_quick_menu_page_name_matches_the_page_labels_table(self):
        """``QUICK_MENU_PAGE`` 与 ``navigation.PAGE_LABELS`` 的键必须一致。

        两者分家会出现「认得出页面、日志却印英文名」这种**不报错的退化**
        （``page_label`` 有默认值兜底），所以用测试挡。
        """
        from auto_game_unified.games.epic7.navigation import PAGE_LABELS
        from auto_game_unified.games.epic7.navigation_plan import QUICK_MENU_PAGE

        self.assertIn(QUICK_MENU_PAGE, PAGE_LABELS)

    def test_quick_menu_identity_requires_both_entry_icons(self):
        """``observe()`` 判快捷菜单时**必须同时**要两个入口图标，缺一不可。

        为什么这条要用 AST 静态守、而不是跑夹具：**三张菜单帧上两个图标都在**，
        所以「只用一个图标」在夹具上与「两个都要」**完全等价** —— 夹具分辨不出来
        （实测：把判据改成只用 ``quick_menu_hero``，``-k quick_menu`` 照样全绿）。
        但生产里两个图标**会各自单独消失**（某一个入口因账号进度/活动被隐藏），
        那时「只用一个」就会把一个**不是菜单**的画面认成菜单，导航链据此跳过
        「打开菜单」那一步，直接去点菜单里的图标 —— 点在底页上，跑飞。

        反向验证：把源码里的 ``if menu_hero and menu_knights:`` 改成
        ``if menu_hero:``，这一条立刻红并点名缺了哪个。
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "games" / "epic7" / "navigation.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # 先找 ``if <变量名> and <变量名>:`` 形状的判据，变量名以 menu_ 开头。
        candidate: ast.BoolOp | None = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.And):
                continue
            names = [v.id for v in test.values if isinstance(v, ast.Name)]
            if names and all(name.startswith("menu_") for name in names):
                candidate = test
                break
        self.assertIsNotNone(candidate, "observe() 里没找到快捷菜单的双图标判据")
        assert candidate is not None

        # 判据里要求的变量，必须在同函数内被赋成 ``self._locate(screen, "<锚点>")``。
        wanted = {v.id for v in candidate.values if isinstance(v, ast.Name)}
        located: dict[str, str] = {}
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
            ):
                continue
            call = node.value
            if getattr(call.func, "attr", None) != "_locate":
                continue
            anchor = next(
                (
                    arg.value
                    for arg in call.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ),
                None,
            )
            if anchor:
                located[node.targets[0].id] = anchor

        self.assertEqual(
            {"quick_menu_hero", "quick_menu_knights"},
            {located.get(name) for name in wanted},
            "快捷菜单判据必须同时要求 quick_menu_hero 与 quick_menu_knights",
        )

    def test_hero_navigation_retries_when_equipment_tab_does_not_exit(self):
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = [0.0]
        menu = fixture("quick_menu_over_lobby")
        equipment = hero_fixture("live_equipment_subpage_20260825")
        information = hero_fixture("list_unfiltered")

        def capture():
            # 2026-10-04 起英雄合成走「大厅点右上蓝四格 → 快捷菜单 → 点菜单里的英雄」，
            # 所以导航期间会有两下点击：第 1 下开菜单、第 2 下进英雄列表。
            # `clicks` 到 1 时菜单已展开 ⇒ 先给菜单帧，让第 2 步点得下去。
            if len(clicks) < 1:
                return fixture("lobby_animated_updated")
            if len(clicks) < 2:
                return menu
            # 之后进入英雄列表：第一次切换标签后仍返回装备页，模拟点击被吞；
            # 第二次点击后才返回英雄信息页。
            return equipment if len(clicks) < 4 else information

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

        # 第 0 下是「打开快捷菜单」，第 1 下才是「进入英雄列表」；
        # 之后两下是英雄信息/装备标签来回切。
        self.assertEqual([(65, 200), (65, 200)], clicks[2:])
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
        menu = fixture("quick_menu_over_lobby")
        equipment = hero_fixture("live_equipment_subpage_20260825")

        def capture():
            # 与上一条同理：第 1 下开菜单 ⇒ 给菜单帧；之后恒为装备子页。
            if len(clicks) < 1:
                return fixture("lobby_animated_updated")
            if len(clicks) < 2:
                return menu
            return equipment

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
            transition_frames=48,
        )

        with self.assertRaisesRegex(RuntimeError, "点击4次后仍未离开"):
            navigator.navigate(
                "hero_synthesis", lobby_screen=fixture("lobby_animated_updated")
            )

        # 第 0 下开菜单、第 1 下进英雄列表，之后 4 下是英雄信息/装备标签来回切。
        self.assertEqual([(65, 200)] * 4, clicks[2:])
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

    # ---- 社区签到路线：横屏段四个锚点（2026-10-06）----
    #
    # ⚠️ 这组用例的重点**不是**「四个页面认对了」，而是**判据的依据成立**：
    # ① 每个锚点在**自己那帧**上过阈，② 在**另外三帧**上都不许过阈（互斥）。
    # 只断言页面名抓不住「锚点退化成大厅常驻控件」这类降级 —— 那时四个页面
    # 会被同一个锚点全判成一种，页面名仍然「有个结果」，日志上看不出异常。

    def test_classifies_community_activity_pages(self):
        navigator = self.navigator([])

        cases = [
            ("lobby_activity_entry_live_20261006", "lobby"),
            ("activity_menu_live_20261006", "activity_menu"),
            # 2026-10-07 真机：同一个活动页，但左列表**顶部多了两行**（「助继承者
            # 重启冒险」×2，一个回归活动），把「更多精彩活动」从 y=460 挤到 y=686。
            # 那天社区路线就死在这一步（模板还在 0.9145，框空了 ⇒ 整页 unknown）。
            ("activity_menu_shifted_live_20261007", "activity_menu"),
            # 2026-10-18 真机：同一个活动页，这次是**往上漂** —— 列表顶部换成了
            # 「网页活动入口」分组标题，且它前面没有别的活动排着 ⇒「更多精彩活动」
            # 落到 **y=258**，比当时定的上界 300 还高 42px ⇒ 模板 0.9959 却判
            # unknown ⇒ 社区签到重试 4 次全失败。这条夹具是「上界必须罩住整列、
            # 不只是往下罩」的唯一证据，`test_the_raised_row_is_invisible_to_the_old_band`
            # 专门钉住它为什么进不来。
            ("activity_menu_raised_live_20261018", "activity_menu"),
            ("activity_web_promo_live_20261006", "activity_web_promo"),
            # 2026-10-07 真机：列表更长 ⇒ 「更多精彩活动」选中态那一行落在 y=726
            # （10-06 那张是 y=443，**相差 283px**）。这张是「新判据跨天复验」的
            # 唯一证据 —— 没有它，改完判据只在自己裁模板的那天成立。
            ("activity_web_promo_shifted_live_20261007", "activity_web_promo"),
            # 2026-10-07 10:50:52：**转场动画中**那一帧（「前往活动页」的光球滑到
            # 别的位置、整颗按钮掉到 0.7282）。这一帧当年正是把整页判成 unknown 的
            # 元凶。留着它当夹具，是为了让「光球滑动」这件事**有图可查**，
            # 而不是只活在注释里。
            ("activity_web_promo_glow_moved_live_20261007", "activity_web_promo"),
            ("web_activity_list_live_20261006", "web_activity_list"),
        ]
        for name, expected in cases:
            with self.subTest(fixture=name):
                observation = navigator.observe(fixture(name))
                self.assertEqual(expected, observation.name)
                self.assertGreater(observation.confidence, 0.82)

    def test_community_activity_anchors_are_mutually_exclusive(self):
        """四个锚点必须「各认各的」：在大厅帧上只有 ``lobby_activity`` 过阈。

        ``lobby_activity`` 是**大厅常驻控件**（左侧竖排最后一个入口），实测在
        220 张同尺寸夹具里有 12 张过阈、**全是大厅类帧**。所以它只能当点击目标，
        判页必须靠另外三个 —— 这条用例就是钉住这个分工：
        另外三帧（活动页 / 推广态 / 网页活动列表）上它**不许**过阈。

        ⚠️ 2026-10-07 换掉了选中态的判据：``web_activity_gate`` 降级成**纯点击
        目标**（它上面有会滑动的光球，同一位置跨帧 1.0000→0.7282），
        选中态改由 ``activity_more_selected``（那一行的白字）认。

        ⚠️ ``web_activity_gate`` **故意不在这张互斥表里**：它本就该在选中态帧上
        命中（导航第 3 步要按那颗按钮），只是**不许参与判页**。判页不许碰它这件事
        由下面那条用例钉。
        """
        navigator = self.navigator([])
        anchors = (
            "lobby_activity",
            "activity_more",
            "activity_more_selected",
            "web_community",
        )
        expected_owner = {
            "lobby_activity_entry_live_20261006": "lobby_activity",
            # 2026-11-05 真机：入口挂了 N 角标、整列上移，改由第二张候选认出。
            # 这两帧仍是**大厅**，活动页那三颗锚点照样不许命中。
            "lobby_activity_updated_live_20261105_1909": "lobby_activity",
            "lobby_activity_updated_live_20261105_1942": "lobby_activity",
            "activity_menu_live_20261006": "activity_more",
            "activity_menu_shifted_live_20261007": "activity_more",
            # 2026-10-18：这一行往上漂到 y=258 的那一帧，判页仍必须归 ``activity_more``。
            "activity_menu_raised_live_20261018": "activity_more",
            "activity_web_promo_live_20261006": "activity_more_selected",
            "activity_web_promo_shifted_live_20261007": "activity_more_selected",
            "web_activity_list_live_20261006": "web_community",
        }

        for name, owner in expected_owner.items():
            screen = fixture(name)
            for anchor in anchors:
                match = navigator._locate(screen, anchor)
                if anchor == owner:
                    self.assertIsNotNone(
                        match, f"{name} 上本该命中 {anchor} 却没过阈"
                    )
                else:
                    self.assertIsNone(
                        match,
                        f"{name} 上 {anchor} 不该命中（页面会互相串味）",
                    )

    def test_updated_lobby_activity_entry_keeps_the_old_frame_unchanged(self):
        """2026-11-05 真机：大厅「活动」入口挂角标后，社区签到连着三次进不去。

        原图在这两帧上只有 0.7956 / 0.8049（门槛 0.82），日志报
        「页面[大厅]缺少导航锚点 lobby_activity」。补的第二张只裁「活动」二字，
        两帧 1.0000 / 0.9972；旧版大厅帧仍由原图拿 1.0000、落点还是 (85,797)。

        先钉住「只留原图时这两帧确实认不出」，免得夹具过期后这条用例绿着
        却什么也没守住（2026-10-30 的教训）。
        """
        navigator = self.navigator([])
        templates = build_navigation_templates(TEMPLATES)
        self.assertEqual(2, len(templates.lobby_activity))
        region = navigator._REGIONS["lobby_activity"]

        for name in (
            "lobby_activity_updated_live_20261105_1909",
            "lobby_activity_updated_live_20261105_1942",
        ):
            screen = fixture(name)
            with self.subTest(frame=name):
                old_only = matcher.locate_with_fallback(
                    "lobby_activity",
                    screen,
                    templates.lobby_activity[0],
                    0.0,
                    region=region,
                    reference_size=REFERENCE_SIZE,
                )
                self.assertIsNotNone(old_only)
                self.assertLess(old_only.score, 0.82)

                match = navigator._locate(screen, "lobby_activity")
                self.assertIsNotNone(match)
                self.assertGreaterEqual(match.score, 0.90)
                # 点击点取命中框中心，必须还落在这一格入口里。
                self.assertLess(abs(match.center[0] - 85), 6)
                self.assertLess(abs(match.center[1] - 796), 6)

        old = fixture("lobby_activity_entry_live_20261006")
        match = navigator._locate(old, "lobby_activity")
        self.assertIsNotNone(match)
        self.assertAlmostEqual(match.score, 1.0, places=4)
        self.assertEqual(match.center, (85, 797))

    def test_the_raised_row_is_invisible_to_the_old_band(self):
        """上界收回 300 时，2026-10-18 那帧**判不出来** —— 这是那次失败的复现。

        为什么要单独钉这一条（而不是只靠上面那条页面名断言）：

        - 页面名断言证明的是「**现在的**区域判得出」，它抓不住「区域被人改窄回去」——
          因为一旦改窄，那一帧会掉进 ``unknown``，而 ``unknown`` **这条用例本来就会红**……
          但它红的方式是「和另外十几条用例混在一起红」，看日志的人分不清是哪一处退化。
        - 这里用**最原始的像素事实**说话：拿模板去裁 ``y 300~1150``（旧区域）比一次，
          分数**必须低于阈值**；再拿现在的区域比一次，分数**必须高于阈值**。
          两个数一起看，就证明了「改的正是这里，而且确实管用」。

        ⚠️ 别把这条改成「调 `navigator._locate` 看返不返回 None」：那等于让被测函数
        自己证明自己。这里直接 `cv2.matchTemplate` 裁区域算，中间不经过任何项目代码。
        """
        navigator = self.navigator([])
        screen = fixture("activity_menu_raised_live_20261018")
        template = cv2.imread(
            str(
                Path(__file__).resolve().parents[1]
                / "games"
                / "epic7"
                / "templates"
                / "navigation"
                / "activity_more.png"
            )
        )
        self.assertIsNotNone(template, "activity_more 模板缺失")

        def score(region: tuple[int, int, int, int]) -> tuple[float, int]:
            x, y, w, h = region
            roi = screen[y : y + h, x : x + w]
            result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _, best, _, location = cv2.minMaxLoc(result)
            return float(best), y + location[1]

        old_score, _ = score((0, 300, 420, 850))
        new_score, new_y = score((0, 150, 420, 1000))

        # ① 旧区域（上界 300）**够不着**这一行 —— 这就是 12:17 那次判 unknown 的原因。
        self.assertLess(
            old_score,
            0.80,
            f"旧区域居然还能命中（{old_score:.4f}）：夹具或区域有一个已经不是当年的样子了",
        )
        # ② 现区域既能命中、分数也远高于阈值。
        self.assertGreater(new_score, 0.95)
        # ③ 命中位置确实在旧上界**上方** —— 把「往上漂」这个事实钉成数字。
        self.assertLess(new_y, 300, f"这一行应该落在旧上界上方，实测 y={new_y}")
        # ④ 实现里那块区域的上界**也必须罩得住**这个命中点。
        # ⚠️ 少了这一条，「有人把区域改回 300」时本用例仍然会绿 —— 因为上面三处
        # 断言用的都是**测试自己写死的坐标**，跟实现没关系。这一条是把测试和实现
        # 拴在一起的那颗钉子：区域上界一旦高于命中位置，这里立刻红。
        band = type(navigator)._REGIONS["activity_more"]
        self.assertLessEqual(
            band[1],
            new_y,
            f"实现的 activity_more 区域上界 y={band[1]} 罩不住这一行（命中在 y={new_y}）",
        )

    def test_selected_state_judgement_survives_the_sliding_glow_orb(self):
        """选中态判据**不许**再依赖那颗会滑动的光球。

        ⚠️ 这条是 2026-10-07 那次实跑失败的**直接原因**（用户原话：「点完之后，
        它是这橙色的选中状态，你就识别不出来了」）：选中态原来靠
        ``web_activity_gate``（「前往活动页」按钮）认，那颗按钮上有一颗会滑动的
        光球 —— 10-06 光球罩住「活动」得 1.0000，10-07 滑到右边罩住「动页」，
        **同一位置 (1690,968) 掉到 0.7282**，过不了阈 ⇒ 整页判 ``unknown``。

        所以这里钉两件事：
        ① 光球那块**不再参与判页**（``observe`` 里压根不查它）；
        ② 新判据 ``activity_more_selected`` 在**两天两帧**上都过阈。
        """
        navigator = self.navigator([])

        # ⓪ 结构性守卫：**判页函数里不许出现这颗按钮的锚点名**。
        # ⚠️ 为什么要用 AST 而不是「跑一遍看结果」：跑一遍只能证明「今天这几帧
        # 判对了」，而**证明不了「它没参与判页」** —— 某天它在别的帧上恰好与
        # 正确判据同分，测试照样绿，人却已经把它当判据用着了。
        # 这正是记忆里那条教训：「护栏测试要防跑不到的分支，结构性规矩改用 AST 静守」。
        import ast
        import inspect

        import auto_game_unified.games.epic7.navigation as nav_module

        tree = ast.parse(inspect.getsource(nav_module))
        forbidden = "web_activity_gate"
        for node in ast.walk(tree):
            # 只看「函数体」（判页发生在函数里），跳过类属性与注释
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != "observe":
                continue
            literals = [
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            ]
            self.assertNotIn(
                forbidden,
                literals,
                f"observe() 里又出现了 {forbidden} —— 它只能当点击目标，"
                "光球会滑动、当判据必炸（2026-10-07 实跑事故）",
            )

        # ① 光球不再决定页面身份
        for name, expected in (
            ("activity_web_promo_live_20261006", "activity_web_promo"),
            ("activity_web_promo_shifted_live_20261007", "activity_web_promo"),
            ("activity_menu_live_20261006", "activity_menu"),
            ("activity_menu_shifted_live_20261007", "activity_menu"),
        ):
            with self.subTest(fixture=name):
                self.assertEqual(expected, navigator.observe(fixture(name)).name)

        # ② 光球那块本身在**同一位置**跨帧分数不一致（这就是它不能当判据的证据）。
        #    三张帧都是「更多精彩活动已选中」的同一页，只有光球位置不同：
        #      10-06 稳定态          → 1.0000
        #      10-07 稳定态          → 0.9716
        #      10-07 光球滑到别处   → **0.7282**（过不了 0.82 ⇒ 当判据必炸）
        #    留着这条断言是为了哪天有人想把它捡回判页时，测试立刻响。
        scores = {}
        for name in (
            "activity_web_promo_live_20261006",
            "activity_web_promo_shifted_live_20261007",
            "activity_web_promo_glow_moved_live_20261007",
        ):
            match = navigator._locate(fixture(name), "web_activity_gate")
            # 光球滑开那帧会返回 None（过不了阈）—— 那正是它不能当判据的原因，
            # 记成 0.0 好让下面的极差断言有个数。
            scores[name] = 0.0 if match is None else match.score
        self.assertGreater(
            max(scores.values()) - min(scores.values()),
            0.20,
            f"「前往活动页」按钮的分数在几帧间几乎没差 {scores} —— "
            "若真如此，说明光球那天恰好没滑动，这条用例的依据需要重新采集",
        )
        # 最关键的一条：光球滑开那一帧**真的过不了阈**。
        self.assertIsNone(
            navigator._locate(
                fixture("activity_web_promo_glow_moved_live_20261007"),
                "web_activity_gate",
            ),
            "光球滑开那帧上 web_activity_gate 竟然过了阈 —— "
            "说明这颗光球已经不再滑动，web_activity_gate 可以捡回判页（"
            "那时请把本测试与 observe() 里的注释一起更新）",
        )

        # 新判据在**三张**选中态帧上都过阈（含转场动画中那帧），未选中帧绝不过阈。
        for name in (
            "activity_web_promo_live_20261006",
            "activity_web_promo_shifted_live_20261007",
            "activity_web_promo_glow_moved_live_20261007",
        ):
            match = navigator._locate(fixture(name), "activity_more_selected")
            self.assertIsNotNone(match, f"{name} 上选中态判据没过阈")
            self.assertGreater(match.score, 0.82)
        for name in (
            "activity_menu_live_20261006",
            "activity_menu_shifted_live_20261007",
        ):
            self.assertIsNone(
                navigator._locate(fixture(name), "activity_more_selected"),
                f"{name} 是未选中态，不该命中选中态判据",
            )

    def test_the_community_plan_stops_hunting_the_activity_row(self):
        """社区签到**不再找左列那一行**，直接点右侧「前往活动页」。

        2026-10-30 改。原来的第 2 步是「选中『更多精彩活动』」，锚点 ``activity_more``
        是**旧版**活动页上那一行的样子 —— 新版页面上只有 **0.4024**（阈 0.82）
        ⇒ 根本认不出 ⇒ 上下扫满 9 屏全是白扫。用户看到的就是
        「一进去往上滑一下、然后一直往下滑」，而那一行明明就在画面里。

        而右侧那颗「前往活动页」按钮在两个新版页面上位置**一模一样**
        （``web_activity_gate`` 0.9673 @ (1722,985)），与左侧选中哪个活动无关
        ⇒ 直接点它。左列怎么变、选中哪个、滚到哪儿，一律不影响。

        ⚠️ 断言的是 ``NavigationPlan`` 里的**声明**（数据）：一旦有人把「先选中那一行」
        加回来，这条立刻红 —— 那个写法在当前版本上必然失败，而且是用 9 次滑动换来的。
        """
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        steps = MODE_SPECS["community"].navigation_plan.steps
        self.assertNotIn(
            "activity_more",
            [step.anchor for step in steps],
            "第 2 步又回去找左列那一行了 —— 那个模板在新版页面上只有 0.40，认不出",
        )
        gate = next(step for step in steps if step.anchor == "web_activity_gate")
        self.assertEqual((1722, 985), gate.fixed_point)
        self.assertIn("web_activity_list", gate.targets)
        self.assertIsNone(
            gate.scroll_before_retry,
            "直接点按钮那一步不需要滚动兜底（右侧按钮本来就在画面里）",
        )

    def test_the_gate_step_declares_a_fixed_point_instead_of_hunting_the_glow(self):
        """导航第 3 步必须用**固定坐标**点「前往活动页」，不许再靠模板定位。

        那颗按钮上有一团**会滑动的光球**：10-06 罩住「活动」二字 ⇒ 1.0000；
        10-07 滑到右边 ⇒ 同一位置掉到 0.7282 ⇒ 过不了 0.82 ⇒ 抛「缺少导航锚点」
        ⇒ **连点都没点**，整条社区路线进不去（13:37 / 14:55 两次实跑）。
        钉的是 ``NavigationPlan`` 里的**声明**（数据）：声明一没，就地失守。
        """
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        steps = MODE_SPECS["community"].navigation_plan.steps
        gate = next(step for step in steps if step.anchor == "web_activity_gate")
        self.assertIsNotNone(
            gate.fixed_point,
            "光球会滑，模板定位跨天必挂；这一步必须声明固定坐标",
        )

    def test_a_fixed_point_step_clicks_it_without_the_template(self):
        """给了固定坐标 ⇒ 光球滑到哪都点得下去，且点的就是声明的那个点。

        断言两件事，**都是「依据」而不是「结果」**：
        ① 光球滑走那一帧上**不给**固定坐标会抛「缺少导航锚点」（复现真机事故）；
        ② 给了固定坐标就点得下去，且落点 == 声明值（``_click_offset`` 对非
           ``lobby_story`` 的锚点返回 (0,0)，所以落点就是声明的那一对数）。
        """
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        gate = next(
            step
            for step in MODE_SPECS["community"].navigation_plan.steps
            if step.anchor == "web_activity_gate"
        )
        slid = fixture("activity_web_promo_glow_moved_live_20261007")

        with self.subTest(case="没有固定坐标 ⇒ 在这次真机事故帧上模板定位必挂"):
            navigator = self.navigator([slid])
            with self.assertRaisesRegex(RuntimeError, "web_activity_gate"):
                navigator._transition(
                    "activity_web_promo",
                    ("web_activity_list",),
                    "web_activity_gate",
                    "打开网页活动列表",
                    source_screen=slid,
                )

        with self.subTest(case="给了固定坐标 ⇒ 点得下去，落点就是声明值"):
            clicks: list[tuple[int, int]] = []
            navigator = self.navigator(
                [fixture("web_activity_list_live_20261006")] * 4, clicks=clicks
            )
            navigator._transition(
                "activity_web_promo",
                ("web_activity_list",),
                "web_activity_gate",
                "打开网页活动列表",
                source_screen=slid,
                fixed_point=gate.fixed_point,
            )
            self.assertEqual([gate.fixed_point], clicks)

    def test_activity_menu_row_is_tracked_wherever_the_menu_grows(self):
        """「更多精彩活动」那一行**会随上方活动行数上下漂**，区域必须罩住整列。

        ⚠️ 这条用例记的是 2026-10-07 社区路线**第一步就失败**的那次真机事故：
        活动页左列表顶部临时多出两行（「助继承者重启冒险」×2，一个回归活动），
        那一行从 y=460 挪到 y=686（+226px）。区域当时只框 y 400~580 ⇒
        模板明明还在（0.9145）却框不到 ⇒ 整页判 ``unknown`` ⇒ 导航超时失败关闭。

        所以这里断言两件事，**都是「依据」而不是「结果」**：
        ① 两个不同日期、不同行数的帧**都**判成 ``activity_menu``；
        ② 命中框中心**跟着那一行走**（两天差 200 多像素）——
           ②才是「点击点没被区域改动带偏」的证据。
        """
        navigator = self.navigator([])
        region = navigator._REGIONS["activity_more"]

        old = navigator._locate(fixture("activity_menu_live_20261006"), "activity_more")
        new = navigator._locate(
            fixture("activity_menu_shifted_live_20261007"), "activity_more"
        )
        self.assertIsNotNone(old)
        self.assertIsNotNone(new)
        # 区域必须同时罩住两个落点（上沿 ≤ 460、下沿 ≥ 686+48）。
        _, ry, _, rh = region
        self.assertLessEqual(ry, 460, "区域上沿太高，罩不住 10-06 那一行的位置")
        self.assertGreaterEqual(ry + rh, 686 + 48, "区域下沿太低，罩不住 10-07 那一行")
        # 点击点跟着行走（不是被区域固定住）。
        self.assertNotEqual(old.center[1], new.center[1])
        self.assertGreater(new.center[1] - old.center[1], 150)

    def test_the_declared_scan_hook_actually_exists_on_the_navigator(self):
        """计划里声明的每个 ``scroll_before_retry`` 名字，导航器上都要有对应搜索器。

        ⚠️ 名字写错（或方法改名）时，执行器会在锚点找不到的那一刻抛
        ``RuntimeError``——**在真机上、在已经跑了一半的时候**。
        这里在构造期就把这条对账做掉：名字 ↔ 方法名必须一一对上。

        ⚠️ 2026-10-18：钩子从 ``_scroll_<名字>`` 改名为 ``_scan_<名字>``。
        语义跟着变了 —— 以前是「滚一屏」，现在是「在一个页面里上下扫、每扫一屏
        重新认一次」，所以一个只会滚、不会认的方法已经不够用了。
        """
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        for mode, spec in MODE_SPECS.items():
            plan = spec.navigation_plan
            if plan is None:
                continue
            for step in plan.steps:
                if step.scroll_before_retry is None:
                    continue
                with self.subTest(mode=mode, anchor=step.anchor):
                    self.assertTrue(
                        hasattr(Epic7Navigator, f"_scan_{step.scroll_before_retry}"),
                        f"路线 {mode} 的 [{step.anchor}] 步声明了 "
                        f"scroll_before_retry={step.scroll_before_retry!r}，"
                        f"但 Epic7Navigator 上没有 _scan_{step.scroll_before_retry}",
                    )

    # ---- 活动页左列：页内扫描（2026-10-18 重写）----
    #
    # 这四条用例原来是「滚一屏能不能把那一行拉回来」。那个前提在 2026-10-18 被
    # 用户推翻了：「这个活动我点进去，它可能在任何位置都有可能……可能还要上滑下滑」。
    # 位置**没有上界**，所以判据不能再是位置，只能是扫描。用例也跟着换：
    # 现在钉的是「扫得完、扫得有界、扫不到不瞎点、页面在行不在时还认得出」。

    def _list_with_row_scrolled_away(self, offset: int = 520):
        """合成一帧「列表滚到下面、那一行跑到屏幕上方之外」。

        ⚠️ **只滚列表区**（``ACTIVITY_COLUMN_Y0``~``Y1``），**不滚顶栏**。
        旧用例把整条左列（y 0~1132）一起 ``np.roll``，那等于把「‹ 活动」横幅
        也一起滚了 —— 真机上列表滚动时顶栏一动不动，那种画面**不存在**。
        而新的页面判据（``activity_page_shell``）就在顶栏里，所以这一条细节
        决定了用例到底在测真机还是测幻觉。
        """
        from auto_game_unified.games.epic7.activity_column import (
            ACTIVITY_COLUMN_Y0,
            ACTIVITY_COLUMN_Y1,
        )

        frame = fixture("activity_menu_raised_live_20261018").copy()
        band = frame[ACTIVITY_COLUMN_Y0:ACTIVITY_COLUMN_Y1, 0:430].copy()
        # ⚠️ **不能用 ``np.roll``**（原来那两条用例就是栽在这儿的）：``roll`` 会把
        # 顶上被推出画面的那些行**从底部卷回来**，于是「已经滚走的行」在合成帧上
        # 又出现在 y≈702 ⇒ 用例自以为复现了事故，其实那一行一直在画面里，
        # 断言就变成了一句空话。这里改成「整体上移 + 底部补最后一行」。
        shifted = np.empty_like(band)
        shifted[:-offset] = band[offset:]
        shifted[-offset:] = band[-1]
        frame[ACTIVITY_COLUMN_Y0:ACTIVITY_COLUMN_Y1, 0:430] = shifted
        return frame

    def _scan_navigator(self, screens, swipes, clicks, logs, backs=None):
        """喂序列 + 记录滑动/点击。序列喂完就回放最后一帧（同 ``self.navigator``）。

        ``backs`` 给了就记录「按了几次返回」—— 2026-10-30 起，扫完仍找不到时会
        先退一层再判一次（见 ``_transition`` 那段）。不传就是空操作，多数用例
        只关心滑动和点击。
        """
        images = list(screens)
        sent: list = []

        def capture():
            if images:
                sent.append(images.pop(0))
            return sent[-1]

        runtime = Runtime(
            capture,
            clicks.append,
            emit=logs.append,
            back=(lambda: backs.append(1)) if backs is not None else (lambda: None),
            swipe=lambda *args, **kwargs: swipes.append((args, kwargs)),
        )
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=6,
        )

    def test_the_row_off_the_top_is_still_the_activity_page(self):
        """⚠️ **这一版的地基**：那一行滚出画面之后，页面**仍然认得出是活动页**。

        为什么这是地基：只要判页还挂在那一行上，「页面认得出、入口找不到」这个
        状态就**在代码里不存在** —— 整页直接判 ``unknown`` ⇒ ``_wait_for_page``
        在拿到帧之前就抛了 ⇒ 页内扫描那一支**永远走不到**。
        这正是 10-08 踩过的「判据写好了、生产走不到」，也是这次换判据的全部理由。

        断言三件事（用裸 matcher 与 ``observe()`` 各算一遍，不互为依据）：
          ① 这一帧上 ``activity_more`` 确实找不着（事故场景复现了）；
          ② ``observe()`` 仍然判 ``activity_menu``（靠的是页面骨架）；
          ③ 骨架的分数离阈值有余量（不是压线过的）。
        """
        frame = self._list_with_row_scrolled_away()
        navigator = self.navigator([])

        row = navigator._locate(frame, "activity_more")
        self.assertIsNone(
            row, "这一帧上居然还找得到那一行 —— 用例没复现出事故场景"
        )

        observation = navigator.observe(frame)
        self.assertEqual(
            "activity_menu",
            observation.name,
            "那一行滚出视野后整页判成了别的 —— 页内扫描在生产上永远走不到",
        )
        self.assertGreaterEqual(
            observation.confidence,
            0.90,
            f"骨架分数只到 {observation.confidence:.4f}，贴着阈值过的不算稳",
        )

    def test_the_shell_anchor_tells_the_activity_page_apart(self):
        """骨架锚点必须**只在**活动页过阈 —— 它是判页的唯一依据，不能含糊。

        正样本：三张活动页（含 10-18 漂移帧、10-07 下移帧）；
        负样本：大厅 / 赛季页 / 竞技场 / 战斗第三页 —— 这些页面上都有左上角
        返回箭头，所以**箭头本身不能当判据**（全库实测那里全是 1.0000）。
        """
        navigator = self.navigator([])
        positive = {
            "activity_menu_live_20261006": 0.90,
            "activity_menu_shifted_live_20261007": 0.90,
            "activity_menu_raised_live_20261018": 0.90,
        }
        for name, threshold in positive.items():
            frame = fixture(name)
            with self.subTest(case=f"活动页 {name}"):
                match = navigator._locate(frame, "activity_page_shell", threshold)
                self.assertIsNotNone(match, f"{name} 上骨架没过阈")
                self.assertEqual(
                    "activity_menu",
                    navigator.observe(frame).name,
                    f"{name} 没被判成活动页",
                )

        for name in ("lobby", "expedition_season_menu", "arena_mode",
                     "battle_menu_third_tab_20261012"):
            frame = fixture(name)
            with self.subTest(case=f"其它页 {name}"):
                match = navigator._locate(frame, "activity_page_shell", 0.90)
                self.assertIsNone(
                    match,
                    f"{name} 上骨架也过了阈，会把别的页面判成活动页",
                )

    def test_the_blue_ui_activity_page_is_recognized_too(self):
        """活动页换成蓝底面板之后**仍然认得出** —— 靠的是第二个候选，不是运气。

        现场（``epic7_community.log``）：10-29 19:18 与 10-30 08:23 两次社区签到 ✗。
        点进活动页后判「画面已静止但仍认不出是哪一页」，干等 2 分钟、重试一次仍认不出，
        最后报「导航开始前应处于[大厅]」—— 它压根还停在活动页里。**每次都必然发生。**

        根因：旧骨架取的是米黄横幅那一条，新版页面根本没有那块 ⇒ 实测 0.6063（阈 0.90）。

        ⚠️ 前提断言（少了它这条会变成假绿）：旧模板在这张帧上**确实**不过阈。
        否则「加第二个候选」就是没必要的冗余，这张帧也证明不了那次事故。
        """
        frame = fixture("activity_menu_blue_ui_live_20261030")
        navigator = self.navigator([])

        self.assertIsNone(
            find_template(
                frame,
                navigator.templates.activity_page_shell[0],
                0.90,
                region=navigator._REGIONS["activity_page_shell"],
                reference_size=REFERENCE_SIZE,
            ),
            "前提变了：旧骨架在新版活动页上已经过阈，这条测试证明不了「必须加候选」",
        )

        observation = navigator.observe(frame)
        self.assertEqual(
            "activity_menu",
            observation.name,
            f"新版活动页没被判成活动页（判成了 {observation.name}）",
        )
        self.assertGreaterEqual(
            observation.confidence,
            0.90,
            f"新版骨架分数只到 {observation.confidence:.4f}，贴着阈值过的不算稳",
        )

    def test_the_page_scan_is_bounded_and_never_guesses(self):
        """上下扫满预算仍然找不到 ⇒ **报错收手**：不许无限扫，更不许蒙着点。

        断言的是**依据**：① 滑动次数正好等于声明预算（每方向
        ``ACTIVITY_SCROLL_LIMIT_PER_DIRECTION``，反方向双倍）；
        ② 一下都没点；③ 抛出的文案里点名了扫过几屏。
        """
        from auto_game_unified.games.epic7.activity_column import (
            ACTIVITY_SCROLL_LIMIT_PER_DIRECTION,
        )

        logs: list[str] = []
        swipes: list[tuple] = []
        clicks: list[tuple] = []
        backs: list[int] = []
        # 每一帧都是「那一行在画面之上」⇒ 扫多少次都不会出现。
        stuck = self._list_with_row_scrolled_away()
        navigator = self._scan_navigator(
            [stuck] * 60, swipes, clicks, logs, backs
        )
        budget = ACTIVITY_SCROLL_LIMIT_PER_DIRECTION * 3

        with self.assertRaisesRegex(RuntimeError, "缺少导航锚点") as ctx:
            # ⚠️ **不传 source_screen** —— 生产路径就是这样调的。
            navigator._transition(
                "activity_menu",
                ("activity_web_promo",),
                "activity_more",
                "选中「更多精彩活动」",
                scroll_before_retry="activity_column",
            )

        self.assertEqual(
            [], clicks, "扫不到的时候居然还点下去了 —— 这是最危险的一种「成功」"
        )
        self.assertEqual(
            budget,
            len(swipes),
            f"滑动次数不是声明的预算 {budget}（两个方向各计入）",
        )
        self.assertEqual(
            1,
            len(backs),
            f"扫完仍找不到时应当**只**退一层，实际按了 {len(backs)} 次返回",
        )
        self.assertIn(
            f"{budget} 屏",
            str(ctx.exception),
            f"报错文案没说扫过几屏，事后查不到底：{ctx.exception}",
        )

    def test_a_detail_page_backs_off_once_and_names_where_it_landed(self):
        """活动页停在**某个活动的详情页**上时：扫完必须退一层，并说清落到了哪一页。

        现场（2026-10-30 21:03，`community` 记的那次 ✗）：游戏记得上次点了「梅铃」
        ⇒ 点「活动」进来**直接落在梅铃详情页**，左侧整列都是它的子项
        （梅铃 / 与梅铃一起吧！/ 修行者兑换所 …），**没有「更多精彩活动」那一行**。

        判页只靠「‹ 活动」标题条（两页都有）⇒ 判成活动页 ⇒ 代码以为那一行只是
        滚出了视野 ⇒ 上下扫满 9 屏 ⇒ 报「这一页很可能确实没有这个入口」，
        用户完全看不出它其实是卡在某个活动的详情页里。

        改法：扫完先按一次返回，**退完当场看页面身份**，落到别的页就立刻点名报错，
        不白等 ``_wait_for_page`` 的超时（那会让失败原因再次失传）。

        钉三件事：① 只退一层；② 报错点名落到了哪一页；③ 一下都没点。
        """
        detail = fixture("activity_menu_detail_live_20261030")
        lobby = fixture("lobby")
        # 前 12 帧是详情页（扫描期间画面不会动），退完之后变成大厅。
        swipes: list[tuple] = []
        clicks: list[tuple] = []
        logs: list[str] = []
        backs: list[int] = []
        navigator = self._scan_navigator(
            [detail] * 12 + [lobby] * 12, swipes, clicks, logs, backs
        )

        with self.assertRaises(RuntimeError) as caught:
            navigator._transition(
                "activity_menu",
                ("activity_web_promo",),
                "activity_more",
                "选中「更多精彩活动」",
                source_screen=detail,
                scroll_before_retry="activity_column",
            )

        self.assertEqual(1, len(backs), f"应当只退一层，实际按了 {len(backs)} 次返回")
        self.assertEqual([], clicks, "退一层之前不该点任何地方")
        self.assertIn(
            "退到了[大厅]",
            str(caught.exception),
            f"报错没点名退到了哪一页，事后查不到底：{caught.exception}",
        )

    def test_the_scan_finds_the_row_after_one_scroll(self):
        """扫描**真的有用**：那一行不在画面里时，滑一屏就能把它找回来。

        构造：先给 8 帧「那一行在画面之上」的合成帧 —— 前 4 帧会被两次
        ``_wait_for_page``（各要「连续 2 帧稳定」）吃掉，剩下的才是扫描的取景；
        之后一直给**原始**那帧（= 滚回列表头之后它又出现在画面里）。

        断言的都是**依据**：① 确实滑过；② 点击落点**在原始帧那一行上**
        （期望值用裸 matcher 独立算，不调被测函数）。
        不断言「转场成功」：假帧不会因为点了一下就真换页。
        """
        logs: list[str] = []
        swipes: list[tuple] = []
        clicks: list[tuple] = []
        away = self._list_with_row_scrolled_away()
        revealed = fixture("activity_menu_raised_live_20261018")
        navigator = self._scan_navigator(
            [away] * 8 + [revealed] * 60, swipes, clicks, logs
        )

        try:
            navigator._transition(
                "activity_menu",
                ("activity_web_promo",),
                "activity_more",
                "选中「更多精彩活动」",
                scroll_before_retry="activity_column",
            )
        except RuntimeError:
            pass  # 假帧不换页 ⇒ 最终失败是模型偏差，扫描该做的已经做完了

        self.assertGreaterEqual(len(swipes), 1, "压根没滑：扫描没接到线上")
        self.assertTrue(
            any("上下扫" in line for line in logs),
            f"日志里没有扫描的记账行；实际：{logs}",
        )
        self.assertGreaterEqual(len(clicks), 1, "扫完之后没有再去找：扫描没把路接上")

        expected = find_template(
            revealed,
            load_template(str(TEMPLATES / "navigation" / "activity_more.png")),
            0.82,
            region=(0, 150, 420, 1000),
        )
        self.assertIsNotNone(expected, "恢复帧本身就没过阈，用例前提不成立")
        self.assertEqual(
            expected.center,
            clicks[0],
            f"点歪了：落点 {clicks[0]} 不在恢复后那一行 {expected.center} 上",
        )

    def test_the_scan_skips_the_click_when_the_row_is_already_selected(self):
        """扫描看到的是**选中态**那一行 ⇒ 目标态已经达成 ⇒ **绝不点**。

        ⚠️ 这一条是**新判据带来的新风险**的护栏：页面骨架分不出「未选中 / 选中」
        两个态（同一块横幅），而列表滚走时行模板也看不见 ⇒ 唯一能分辨的机会
        就在扫描里。如果扫描只会找 ``activity_more``，那「已经是选中态」会被
        判成「找不到」⇒ 整条路线失败；如果收手时不加判断就点，**点一下会把选中
        取消掉** —— 两种都错，所以这里把「认出选中态 ⇒ 跳过点击」钉死。
        """
        logs: list[str] = []
        swipes: list[tuple] = []
        clicks: list[tuple] = []
        # 10-06 的选中态帧：那一行是橙底白字 ⇒ ``activity_more`` 只有 0.25~0.34。
        selected = fixture("activity_web_promo_live_20261006")
        navigator = self._scan_navigator(
            [selected] * 30, swipes, clicks, logs
        )

        screen, match, reached = navigator._scan_activity_column(
            "activity_more", ("activity_web_promo",), "activity_menu", "选中"
        )
        self.assertTrue(reached, "认出选中态时没报「目标态已达成」")
        self.assertIsNone(match)
        self.assertIsNotNone(screen)

        # 同样的画面，但这一趟要去的不是那一态 ⇒ 不许谎报「已达成」。
        _screen, _match, reached_other = navigator._scan_activity_column(
            "activity_more", ("web_activity_list",), "activity_menu", "选中"
        )
        self.assertFalse(
            reached_other, "目标里没有那个态，却报了「已达成」—— 会被当成成功跳过"
        )

    def test_the_activity_scroll_gestures_stay_inside_the_column(self):
        """两个方向的滑动都必须落在**左列文字**上、且在列表可见区内。

        ⚠️ 与竖屏信息流那条护栏（``SCROLL_GUTTER_X``）取向**不同**：左列**没有**
        一条干净的白边可躲 —— 实测 x=15/30/60/90/120 的彩色占比都是 0.17~0.24，
        整列橙底加装饰。所以这里的选择不是「躲到干净的地方」，而是**退化成点击时
        点到什么**：落在活动名那行文字上只会切换选中项（无害可恢复），落在右侧
        就会打开别的东西。

        断言：① x 在左列内、贴住文字列（30~200）；② 两个方向的 y 都在列表可见区
        （``ACTIVITY_COLUMN_Y0``~``Y1``）里 —— 滑到顶栏或屏幕边缘外会让手势落空；
        ③ 两个方向**相反**（同向等于只扫了一半，另一半永远到不了）。
        """
        from auto_game_unified.games.epic7.activity_column import (
            ACTIVITY_COLUMN_X1,
            ACTIVITY_COLUMN_Y0,
            ACTIVITY_COLUMN_Y1,
            ACTIVITY_SCROLL_END_Y,
            ACTIVITY_SCROLL_START_Y,
            ACTIVITY_SCROLL_TAIL_END_Y,
            ACTIVITY_SCROLL_TAIL_START_Y,
            ACTIVITY_SCROLL_X,
        )

        self.assertGreaterEqual(ACTIVITY_SCROLL_X, 30, "起点跑到最左边那条装饰带上了")
        self.assertLessEqual(
            ACTIVITY_SCROLL_X,
            200,
            "起点跑到左列外面了 —— 退化成点击时会点到右侧内容",
        )
        self.assertLess(ACTIVITY_SCROLL_X, ACTIVITY_COLUMN_X1, "起点没落在左列范围里")

        for label, start_y, end_y in (
            ("回列表头", ACTIVITY_SCROLL_START_Y, ACTIVITY_SCROLL_END_Y),
            ("往列表尾部", ACTIVITY_SCROLL_TAIL_START_Y, ACTIVITY_SCROLL_TAIL_END_Y),
        ):
            with self.subTest(direction=label):
                for y in (start_y, end_y):
                    self.assertGreaterEqual(
                        y, ACTIVITY_COLUMN_Y0, f"{label} 的 y={y} 滑到顶栏上去了"
                    )
                    self.assertLessEqual(
                        y, ACTIVITY_COLUMN_Y1, f"{label} 的 y={y} 滑出屏幕了"
                    )
                self.assertNotEqual(
                    start_y, end_y, f"{label} 的起终点相同，这一下什么都不做"
                )

        self.assertLess(
            ACTIVITY_SCROLL_START_Y,
            ACTIVITY_SCROLL_END_Y,
            "回列表头那一下的方向应该是「手指往下拖」（内容下移，露出上面的行）",
        )
        self.assertGreater(
            ACTIVITY_SCROLL_TAIL_START_Y,
            ACTIVITY_SCROLL_TAIL_END_Y,
            "两个方向必须相反，否则等于只扫了一半",
        )

        # ⚠️ 这套扫描**唯一**的硬几何约束：步长必须**小于**搜索带高度。
        # 否则会造出「漏行」—— 某一行正好从带子上沿被滑过去，前后两次取景都没罩住它，
        # 而在真机上「漏行」的表现和「入口不见了」一模一样，查起来极难。
        # 现在 940 的带高配 400 的步长，相邻两次取景重叠 540px，怎么滑都漏不掉。
        self.assertLess(
            ACTIVITY_SCROLL_STEP,
            ACTIVITY_COLUMN_Y1 - ACTIVITY_COLUMN_Y0,
            "步长不能大于等于搜索带高度，否则会漏行：某一行正好从带上沿滑过去，两次取景都没看见",
        )


    def test_missing_community_anchor_fails_closed(self):
        """判据锚点缺模板必须在**构造期**炸，不许悄悄降级成「画面认不出」。

        锚点模板缺失时 ``_locate()`` 与「画面本来就没这控件」无法区分，判据会
        静默消失（2026-10-03 装备子页就这么丢过一次）。这条用例把五个新锚点
        逐个抹掉，断言构造期报错文案里**点名**了缺的那个。
        """
        from dataclasses import replace

        for anchor in (
            "lobby_activity",
            "activity_more",
            "activity_more_selected",
            "web_activity_gate",
            "web_community",
        ):
            with self.subTest(anchor=anchor):
                broken = replace(
                    build_navigation_templates(TEMPLATES), **{anchor: None}
                )
                runtime = Runtime(lambda: fixture("lobby"), lambda _: None)
                with self.assertRaisesRegex(ValueError, anchor):
                    Epic7Navigator(broken, runtime, sleep=lambda _: None)

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

    def test_repeated_ineffective_clicks_probe_the_input_channel_once(self):
        """连点两次都纹丝不动 ⇒ 补一次模拟器输入通道自检，且**只补一次**。

        2026-10-03 实测：远征与英雄合成各连点 4 次无效，诊断图却是完好的大厅画面，
        光看日志**分不清「通道断了」还是「游戏没响应」**。通道自检此前只在开跑前跑
        一次（``main._build_runtime``），跑到一半坏掉就再没人查 —— 这条用例盯的就是
        「连续无效时补一次自检」，位置在第 2 次重试，不是每次重试都补。
        """
        clicks: list[tuple[int, int]] = []
        probes: list[int] = []
        logs: list[str] = []
        clock = [0.0]

        def sleep(seconds: float):
            clock[0] += seconds

        lobby = fixture("lobby")
        runtime = Runtime(
            lambda: lobby,  # 画面永远不动：怎么点都停在原页
            clicks.append,
            back=lambda: None,
            emit=logs.append,
            monotonic=lambda: clock[0],
            input_channel_probe=lambda: probes.append(1),
        )
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=sleep,
            poll_seconds=0.5,
            transition_frames=48,
        )

        with self.assertRaisesRegex(RuntimeError, "导航转场"):
            navigator.navigate("arena", lobby_screen=lobby)

        self.assertTrue(any("点击验收=无效" in log for log in logs))
        self.assertEqual(1, len(probes), f"通道自检应只补一次，实际 {len(probes)} 次")

    def test_absent_input_channel_probe_is_silently_skipped(self):
        """没装配探针时（干跑 / 测试替身）自检静默跳过，不抛错、不改变行为。"""
        screen = fixture("lobby")
        runtime = Runtime(
            lambda: screen,
            lambda point: None,
            dry_run=True,
        )

        runtime.ensure_input_channel()  # 不抛异常即通过

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

    def test_the_smooth_fallback_stays_an_audited_allowlist(self):
        """低通兜底**只能按名单开**，且名单里的锚点必须事先登记过搜索区域。

        名单写死在这条测试里 ⇒ 以后想给别的锚点开，必须回来改这里，也就逼着自己
        先跑一遍全库扫描证明「不漏真页、不放冒牌」（2026-11-01：``lobby_battle``
        就是因为「退出确认弹窗」被抬到 0.843 而被拒之门外的）。
        """
        self.assertEqual(
            frozenset(
                {
                    "lobby_arena",
                    "arena_ready",
                    "list_ready",
                    "challenge",
                    "battle_start",
                    "confirm",
                }
            ),
            matcher.SMOOTH_FALLBACK_ANCHORS,
        )
        for anchor in matcher.SMOOTH_FALLBACK_ANCHORS:
            if anchor in Epic7Navigator._REGIONS:
                continue
            # 其余名字属于路线层的判据（与导航共用同一张图、同一套名单），
            # 必须能在竞技场证据里找得到，否则就是写错了名字。
            self.assertIn(
                anchor,
                build_arena_evidence(TEMPLATES).atoms,
                f"名单里的 {anchor} 在导航与竞技场证据里都不存在",
            )

    def test_the_smooth_fallback_never_rescues_a_page_where_the_button_is_absent(self):
        """兜底是「换把尺子」，不是「放宽判定」：按钮不在的页面照样认不出来。"""
        navigator = self.navigator([])

        self.assertIsNotNone(
            navigator._locate(fixture("lobby"), "lobby_arena"),
            "模拟器大厅：原样就认得出，兜底不该改变这个结论",
        )
        self.assertIsNotNone(
            navigator._locate(fixture("arena_list"), "arena_ready"),
            "模拟器对手列表：原样就认得出，兜底不该改变这个结论",
        )
        self.assertIsNone(
            navigator._locate(fixture("arena_list"), "lobby_arena"),
            "大厅那颗按钮不在对手列表页上 —— 兜底把它救回来就是放进冒牌货",
        )

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

    def test_community_navigation_goes_straight_to_the_web_activity_gate(self):
        """常规情形：进活动页后**直接点右侧「前往活动页」**，不再经过「更多精彩活动」。

        2026-10-30 改：原来的第二步是「选中『更多精彩活动』」，锚点 ``activity_more``
        是**旧版**活动页上那一行的样子 —— 新版页面上它只有 **0.4024**（阈 0.82）
        ⇒ 根本认不出 ⇒ 上下扫满 9 屏全是白扫（用户看到的就是「一进去往上滑一下、
        然后一直往下滑」，而那一行明明就在画面里）。

        而右侧那颗「前往活动页」按钮在两个新版页面上位置**一模一样**
        （实测 ``web_activity_gate`` 0.9673 @ (1722,985)），根本不需要先选中什么
        —— 它说的是右侧那块固定的网页活动宣传位，与左侧选了哪个活动无关。

        ⇒ 现在只有两步：大厅点「活动」→ 活动页点「前往活动页」。
        """
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                fixture("activity_menu_shifted_live_20261007"),
                fixture("activity_menu_shifted_live_20261007"),
                fixture("web_activity_list_live_20261006"),
                fixture("web_activity_list_live_20261006"),
            ],
            clicks=clicks,
        )

        navigator.navigate("community", lobby_screen=fixture("lobby"))

        self.assertEqual(
            2,
            len(clicks),
            f"应当只点两下（进入活动 + 前往活动页），实际点了 {clicks}",
        )

    def test_community_navigation_works_when_the_row_is_already_selected(self):
        """⚠️ 进活动页时那一行**已经是选中态** ⇒ 一样要走通。

        ⚠️⚠️ 这是 2026-10-07 用户实跑发现的（12:44 那次测试）：
        「如果我一点到活动就在那个更多精彩里面，它就识别不到了，
        就是他一定得说我一开始不在这一个更多精彩活动」。

        真因：游戏**记得**上次在活动页上选没选「更多精彩活动」⇒ 点进来的画面
        可能直接是选中态（那一行已经变橙）。而导航链第一步原来只声明
        ``("activity_menu",)``（**只有未选中态**）⇒ ``_wait_for_page`` 会一直等
        一个**永远不会出现**的页面直到超时。

        ⇒ 现在第一步的出口是**两个态**。这条用例喂「进页面就是选中态」的帧序，
        断言**只点两下**（跳过「选中」那一步）。
        """
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"), fixture("lobby"),
                # 进来就已经是选中态 —— 「更多精彩活动」那一行是橙的。
                fixture("activity_web_promo_shifted_live_20261007"),
                fixture("activity_web_promo_shifted_live_20261007"),
                fixture("web_activity_list_live_20261006"),
                fixture("web_activity_list_live_20261006"),
            ],
            clicks=clicks,
        )

        navigator.navigate("community", lobby_screen=fixture("lobby"))

        self.assertEqual(
            2,
            len(clicks),
            f"已是选中态时只该点「进入活动」+「打开网页活动列表」两下，实际 {clicks}",
        )

    def test_community_first_step_accepts_both_states_as_its_exit(self):
        """钉住**声明**本身：第一步的出口必须是两个态。

        ⚠️ 为什么要钉数据而不是只靠上面那两条端到端用例：端到端用例走的是
        「帧序刚好对」的路径；有人把 ``targets`` 改回单态、同时把某张夹具
        换成能蒙对的样子，用例仍可能绿。这里直接断言链条声明。
        """
        from auto_game_unified.games.epic7.modes import MODE_SPECS

        steps = MODE_SPECS["community"].navigation_plan.steps
        self.assertEqual(
            ("activity_menu", "activity_web_promo"),
            tuple(steps[0].targets),
            "导航第一步的出口必须同时包含选中/未选中两态 —— "
            "游戏记得上次选没选，进页面可能就是选中态（2026-10-07 实跑事故）",
        )

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

        self.assertEqual([(1819, 537), (465, 220), (1080, 357)], clicks)

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
        self.assertEqual([(1819, 537), (1080, 357)], clicks)

    def test_labyrinth_navigation_switches_back_from_the_remembered_season_tab(self):
        """游戏记住上次停在哪一栏：跑过远征之后，迷宫进战斗页会直接落在赛季页。

        2026-10-04 每日任务**卡死在这里** —— 迷宫的链当时只认 battle_menu，落到
        season_menu 之后没有下一步可走，干等约 92 秒报「导航开始前应处于[大厅]」，
        当天强化石一根都没买。夹具 ``season_menu_general_tab_20261004`` 就是那次
        失败的实机卡帧（runtime_diagnostics/epic7_labyrinth_stone/20261004_081751）。
        """
        clicks: list[tuple[int, int]] = []
        stuck_frame = fixture("season_menu_general_tab_20261004")
        navigator = self.navigator(
            [
                fixture("lobby"),
                fixture("lobby"),
                stuck_frame,
                stuck_frame,
                labyrinth_fixture("battle_menu"),
                labyrinth_fixture("battle_menu"),
            ],
            clicks=clicks,
        )

        navigator.navigate("labyrinth_stone")

        # 第二下点的是「一般」标签条的中心 —— 它必须有，否则赛季页出不去。
        self.assertEqual([(1819, 537), (225, 220)], clicks)

    def test_labyrinth_navigation_leaves_the_general_tab_alone_when_already_on_it(self):
        """已经站在「一般」页就别再点那一栏（点了没坏处，但会拖慢、也徒增点击）。"""
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("lobby"),
                fixture("lobby"),
                labyrinth_fixture("battle_menu"),
                labyrinth_fixture("battle_menu"),
            ],
            clicks=clicks,
        )

        navigator.navigate("labyrinth_stone")

        self.assertEqual([(1819, 537)], clicks)

    def test_general_tab_candidates_cover_both_source_pages(self):
        """「一般」标签是**两张候选图**，各管一个来源页 —— 缺一张那一步就点不下去。

        这一步（``modes.py`` 迷宫链的「切回一般页」）的来源页有两个：赛季页与第三页，
        而「一般」标签在两者上的底纹不同。同框 (105,175,240,90) 实测（246 张全扫）：

            截自赛季页的那张：赛季页 0.8668 / 第三页 **0.8185**（差 0.0015 不到 0.82）
            截自第三页的那张：第三页 1.0000 / 赛季页 0.7154

        只留第一张时，第三页上 ``_locate`` 返回 None ⇒ ``_transition`` 抛
        「缺少导航锚点」，连点都点不下去 —— 这是 2026-10-12 那次失败的第二个成因
        （现场帧 ``tests/fixtures/epic7_navigation/battle_menu_third_tab_20261012.png``）。

        ⚠️ 敢用「哪张胜出都行」是因为**命中中心恒在同一格**：锚点区域
        (100,165,250,105) 只比模板大 10x15 像素 ⇒ 中心必在 (225±5, 222±3) 之内，
        两张候选都落在「一般」标签那一格里。所以这一步不需要固定坐标。
        """
        navigator = self.navigator([])
        season_page = fixture("season_menu_general_tab_20261004")
        third_page = fixture("battle_menu_third_tab_20261012")
        general_page = labyrinth_fixture("battle_menu")

        on_season = navigator._locate(season_page, "battle_general_tab")
        on_third = navigator._locate(third_page, "battle_general_tab")

        # 两个来源页都必须定位得到。
        self.assertIsNotNone(on_season)
        self.assertIsNotNone(on_third)
        # 落点都在「一般」标签这一格里（区域只比模板大 10x15，中心不可能跑远）。
        for match in (on_season, on_third):
            self.assertLessEqual(abs(match.center[0] - 225), 5)
            self.assertLessEqual(abs(match.center[1] - 220), 3)
        # 一般页上它不该乱命中（这一步在一般页本来就该被 skip_if_observed 跳过）。
        self.assertIsNone(navigator._locate(general_page, "battle_general_tab"))

    def test_pc_battle_general_tab_locates_on_pc_season_menu_and_rejects_selected_tab(self):
        """PC 移植回归（2026-11-04 每日任务实跑）：PC 客户端的「一般」标签底纹与模拟器不同，
        原模拟器模板在 PC 赛季页帧上只有 **0.4643** < 0.82 ⇒ 迷宫「切回一般页」那一步在
        PC 上点不下去，强化石一根都买不到。

        修复：新增 ``templates/navigation/pc/battle_general_tab.png``（96×54，只截未选中的
        灰色「一般」标签，避开「赛季」蓝标与橙点），并把搜索区 (100,165,250,105) 留足余量
        （比模板大 154×51）让模板能滑到真中心。该 PC 帧上实测 1.0000 @ (208,241)。

        这条测试钉住两件事（与 ``test_general_tab_candidates_cover_both_source_pages`` 口径一致）：
        ① PC 赛季页帧必须能 ``_locate`` 过 0.82；
        ② 在「一般」标签**被选中**的页（模拟器 ``battle_menu`` 帧）上不得过阈 ——
           否则会误点已经停在那里的标签、把状态机带偏（排他性）。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        pc_season = labyrinth_pc_fixture("season_menu_pc_20261104")
        general_selected = labyrinth_fixture("battle_menu")

        match = navigator._locate(pc_season, "battle_general_tab")
        self.assertIsNotNone(match, "PC 赛季页帧必须能认出未选中的「一般」标签")
        self.assertGreaterEqual(match.score, 0.82)
        # 排他性：选中的「一般」标签（蓝/橙高亮）不该被未选中灰标模板命中。
        self.assertIsNone(
            navigator._locate(general_selected, "battle_general_tab"),
            "选中的「一般」标签页上，未选中灰标模板不得乱命中",
        )

    def test_pc_fodder_side_story_is_recognized_on_pc_side_story_page(self):
        """PC 移植回归（2026-11-04 每日任务实跑）：导航 大厅 → fodder_side_story 失败，
        根因是 ``side_story_special_book`` 的 PC 覆盖图 385×110 与搜索区 (1520,900,385,110)
        **等大**，模板只能摆一次、中心被锁死在 (1712,955)，而真机按钮中心在 (1694,946)，
        偏 (-18,-9) ⇒ 分数从 0.7176 塌到 0.1781（阈 0.82）⇒ 导航永远以为还在转场。

        修复：把 PC 覆盖图重裁成只含「特别的时间之书」文字的 196×68（远小于区域），
        能在区域里滑到真中心，该 PC 帧上实测 1.0000。全库 476 张夹具扫描**仅**两张
        支线故事真机帧命中、零误报（含月光剧场主页）。

        这条测试钉住：PC 支线故事真机帧必须 ``observe() == "fodder_side_story"``。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        pc_side_story = moonlight_pc_fixture("side_story_page_pc_20261104_072717")

        observation = navigator.observe(pc_side_story)
        self.assertEqual("fodder_side_story", observation.name)

    def test_pc_side_story_special_book_covers_both_renderings(self):
        """P3 续（2026-11-04 14:19 实跑）：早上重裁的 PC 图只认 07:27 那批帧。
        下午同一颗「特别的时间之书」按钮换了另一套渲染，互比只有 **0.7720**
        （阈 0.82）⇒ 第一跳判 unknown ⇒ 重试再点，落进月光剧场主页。

        两张图互为候选（任一张过阈即命中、取最高分），阈值与区域都不变。
        全库 517 帧扫描：除支线故事页外最高 0.6024，零冒牌。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        for name in (
            "side_story_page_pc_20261104_072717",
            "side_story_page_pc_20261104_141910",
        ):
            with self.subTest(frame=name):
                observation = navigator.observe(moonlight_pc_fixture(name))
                self.assertEqual("fodder_side_story", observation.name)

    def test_pc_story_ready_covers_both_button_renderings(self):
        """P4 续（2026-11-04 14:25 / 14:44 实跑）：导航 大厅 → story_ready 失败，
        日志写「画面已静止但仍认不出是哪一页」。白掩膜口径下两张旧模板在下午帧
        分别只有 0.7378 / 0.8515（阈 0.90）；而 01:59 那批帧用旧图是 1.0000。
        ⇒ 两套渲染都得留着，补第三张候选、阈值不动。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        for name in (
            "story_ready_pc_20261104_015956",
            "story_ready_pc_20261104_142538",
            # 14:53 主线「等待通关」超时那一帧：点掉完成弹窗后回到关卡详情页，
            # 导航层必须同样认出 story_ready（实测 1.0000），否则回家/衔接会歪。
            "wait_complete_after_close_pc_20261104",
        ):
            path = ROOT / "tests" / "fixtures" / "epic7_story_pc" / f"{name}.png"
            frame = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            with self.subTest(frame=name):
                self.assertEqual("story_ready", navigator.observe(frame).name)

    def test_pc_moonlight_theater_home_is_not_fodder_side_story(self):
        """排他性回归（2026-11-04）：月光剧场**主页**上没有「特别的时间之书」按钮，
        所以绝不能被 ``side_story_special_book`` 认成支线故事页。全库扫描已确认该主页帧
        对 ``side_story_special_book`` 不过阈。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        theater_home = moonlight_pc_fixture("theater_home_pc_20261104_073014")

        observation = navigator.observe(theater_home)
        self.assertNotEqual("fodder_side_story", observation.name)

    def test_pc_moonlight_theater_home_is_not_tower_home(self):
        """PC 移植回归（2026-11-04 每日任务实跑）：月光剧场主页右下角也有一枚**同款绿色
        「入场」按钮**，把 ``tower_home`` 的 ``home_enter`` 锚点高分吃下
        （月光剧场主页帧 0.9266 @ (1693,1008) 落在 region 内）⇒ 月光剧场主页被误判成月塔主页，
        导航转场合同彻底走偏。

        修复：给 ``tower_home`` 判定加第二维证伪 —— 月塔主页**专有**的左上角标题
        「欧多马顿塔」(``tower_home_title``)。两枚锚点同时过阈才认月塔主页。全库扫描确认
        真实月塔主页帧仍过阈、月光剧场主页帧（无此标题）不过阈。

        这条测试钉住：月光剧场主页帧 ``observe()`` 绝不能是 ``"tower_home"``。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        theater_home = moonlight_pc_fixture("theater_home_pc_20261104_073014")

        observation = navigator.observe(theater_home)
        self.assertNotEqual("tower_home", observation.name)

    def test_pc_tower_home_requires_both_enter_and_title_on_real_tower_home(self):
        """对称回归：真实月塔主页帧，``home_enter`` + ``tower_home_title`` 两维都过阈，
        ``observe()`` 必须是 ``"tower_home"`` —— 证明这枚证伪第二维没有把真月塔主页一起误杀
        （修复 tower_home 冒牌时最容易犯的错就是「调阈值把真月塔页也弄丢」）。
        """
        from auto_game_unified.games.epic7.template_paths import resolve_template_dir

        navigator = Epic7Navigator(
            build_navigation_templates(resolve_template_dir(TEMPLATES, "pc")),
            Runtime(lambda: None, lambda *_: None, back=lambda: None, emit=lambda *_: None),
            sleep=lambda _: None,
        )
        tower_home = tower_fixture("home")

        observation = navigator.observe(tower_home)
        self.assertEqual("tower_home", observation.name)

    def test_battle_menu_identity_is_decided_by_which_tab_is_selected(self):
        """同一屏按「哪个标签被选中」分成三页，五张真机帧各归各的。

        旧口径是「顶栏标题 + 『赛季』**未**选中」—— 一般页与第三页都满足它，
        于是第三页被当成一般页（2026-10-12 迷宫失败的根因）。
        """
        navigator = self.navigator([])
        cases = (
            (labyrinth_fixture("battle_menu"), "battle_menu"),
            (fixture("expedition_battle_menu"), "battle_menu"),
            (fixture("season_menu_general_tab_20261004"), "season_menu"),
            (fixture("expedition_season_menu_live_20260917"), "season_menu"),
            (fixture("battle_menu_third_tab_20261012"), "battle_other_menu"),
        )

        for frame, expected in cases:
            with self.subTest(expected=expected):
                observation = navigator.observe(frame)
                self.assertEqual(expected, observation.name)
                self.assertGreaterEqual(observation.confidence, 0.95)

    def test_the_old_season_tab_judgement_would_have_mistaken_the_third_page(self):
        """把「旧口径为什么错」钉死，顺带钉住**三条判据的先后顺序**是判据的一部分。

        机制本身：旧代码问「顶栏标题在 **且** 『赛季』没被选中」，第三页答「是」
        ⇒ ``observe()`` 报 ``battle_menu`` ⇒ ``skip_if_observed`` 把「切回一般页」
        跳过 ⇒ 迷宫路线在第三页上找不到一般页那四张卡片 ⇒ 判「认不出」干等超时。

        所以这里同时钉两件事：第三页上「赛季未选中」**过阈**（旧口径的错因），
        而「一般选中」**不过阈**（新口径的依据）；再加一条顺序约束 ——
        「赛季未选中」在**一般页**上也过阈，所以第三页那一条必须排在
        ``battle_menu`` 之后，挪到前面就会把一般页抢走。
        """
        navigator = self.navigator([])
        third_page = fixture("battle_menu_third_tab_20261012")
        general_page = labyrinth_fixture("battle_menu")

        def season_tab_score(screen):
            return find_best_template(
                screen,
                navigator.templates.expedition_season_tab,
                reference_size=REFERENCE_SIZE,
            ).score

        # 旧口径在第三页上是「成立」的 —— 这就是当年误判成一般页的机制。
        self.assertGreaterEqual(season_tab_score(third_page), 0.82)
        # 同样在一般页上也过阈 ⇒ 第三页那一条只能排在 battle_menu 后面。
        self.assertGreaterEqual(season_tab_score(general_page), 0.82)
        # 新口径真正区分一般页的那枚锚点，在第三页上必须不过阈。
        self.assertLess(
            find_best_template(
                third_page,
                navigator.templates.battle_general_active,
                region=navigator._REGIONS["battle_general_active"],
                reference_size=REFERENCE_SIZE,
            ).score,
            0.82,
        )

    def test_labyrinth_navigation_switches_back_from_the_remembered_third_tab(self):
        """游戏记住的是**第三个**标签页时，迷宫也要能自己切回「一般」页。

        2026-10-12 每日任务卡死在这里：那天落点是第三页（当天写着「事件」），
        旧口径把它当成一般页 ⇒ 这一步被 ``skip_if_observed`` 跳过 ⇒ 迷宫路线接手后
        在第三页上找不到一般页那四张卡片 ⇒ 判「认不出」⇒ 干等 60 秒超时
        （runtime_diagnostics/epic7_labyrinth_stone/20261012_230202_433099）。
        """
        clicks: list[tuple[int, int]] = []
        third_frame = fixture("battle_menu_third_tab_20261012")
        navigator = self.navigator(
            [
                fixture("lobby"),
                fixture("lobby"),
                third_frame,
                third_frame,
                labyrinth_fixture("battle_menu"),
                labyrinth_fixture("battle_menu"),
            ],
            clicks=clicks,
        )

        navigator.navigate("labyrinth_stone")

        # 第二下点的还是「一般」标签条的中心 —— 第三页上必须点得下去。
        self.assertEqual([(1819, 537), (225, 220)], clicks)

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

    def test_season_menu_page_judgement_does_not_depend_on_the_expedition_card(self):
        """赛季页判据**不许**掺卡片内容：卡片换季也不能让整页认不出来（10-08）。

        实机背景：跑月塔时点完「战斗」落在赛季页，导航器却报 ``unknown`` ⇒ 干等
        20 秒、重试 2 轮 ⇒ ``RuntimeError: 导航开始前应处于[大厅]``。根因是页面判据
        里塞了 ``expedition_entry``（「远征队」三字），而当季卡片换成了「暗影情报
        商人委托」，该模板只有 0.4734。

        这条护栏的判据是**两件事同时成立**：① 卡片锚点在帧上确实认不出来；
        ② 整页**仍然**认得出。只看 ② 是抓不住回归的 —— 把卡片重新绑回判据时，
        只要那一帧恰好卡片没换季也照样过。
        """
        navigator = self.navigator([])
        screen = fixture("expedition_season_menu_live_20260917")

        # ① 卡片锚点在**本帧**认得出（本帧卡片没换季）——先证明锚点本身是好的。
        card = find_best_template(
            screen,
            navigator.templates.expedition_entry,
            region=(400, 240, 1580, 260),
            reference_size=REFERENCE_SIZE,
        )
        self.assertIsNotNone(card)
        self.assertGreaterEqual(card.score, 0.90)

        observation = navigator.observe(screen)
        self.assertEqual("season_menu", observation.name)
        self.assertGreaterEqual(observation.confidence, 0.95)

    def test_season_menu_is_still_recognised_when_the_expedition_card_looks_nothing_alike(self):
        """真机现场的赛季页：当期远征卡片已换成「暗影情报商人委托」。

        夹具取自月塔那次的实机帧（``tests/fixtures/epic7_tower/season.png`` /
        ``season_2.png``，与 ``runtime_diagnostics/epic7_tower/20261008_2259*`` 同批）。
        这两张帧的硬依据：

        * ``expedition_entry``（「远征队」三字）→ **0.4734**，认不出来；
        * 月塔自己的 ``season_tower_title`` → **1.0000**（它没坏，是导航器拦住了它）；
        * 现在 ``observe()`` 必须报 ``season_menu`` 且分数 ≥ 0.95。

        这三条断言把「页面判据与卡片内容解耦」钉死：谁把 ``expedition_entry`` 重新
        塞回 ``observe()`` 的 ``season_menu`` 分支，这两张帧立刻回到 ``unknown``。
        """
        navigator = self.navigator([])

        for name in ("season", "season_2"):
            with self.subTest(fixture=name):
                screen = tower_fixture(name)

                # ① 卡片锚点认不出来 —— 这是本帧的客观事实，不是我们造出来的。
                card = find_best_template(
                    screen,
                    navigator.templates.expedition_entry,
                    region=(400, 240, 1580, 260),
                    reference_size=REFERENCE_SIZE,
                )
                card_score = card.score if card is not None else 0.0
                self.assertLess(card_score, 0.60)

                # ② 整页仍然认得出。
                observation = navigator.observe(screen)
                self.assertEqual("season_menu", observation.name)
                self.assertGreaterEqual(observation.confidence, 0.95)

    def test_season_menu_page_anchors_survive_the_card_row_being_erased(self):
        """页面判据用的两个锚点必须落在**卡片行之外**：整排卡片涂掉也照样满分。

        锚点名与区域**独立写死**（不遍历 ``_TEMPLATE_NAMES``、不从被测模块导入），
        所以把卡片内容混进判据时会红。
        """
        navigator = self.navigator([])
        screen = fixture("expedition_season_menu_live_20260917").copy()
        # 只涂**卡片主体**（y 345 起）——标签条区域跨到 y 340，涂低了会误伤「赛季」高亮。
        screen[345:560, 400:1980] = 0

        title = find_best_template(
            screen,
            navigator.templates.expedition_battle_title,
            region=(0, 35, 350, 180),
            reference_size=REFERENCE_SIZE,
        )
        season_active = find_best_template(
            screen,
            navigator.templates.expedition_season_active,
            region=(250, 140, 500, 200),
            reference_size=REFERENCE_SIZE,
        )

        self.assertIsNotNone(title)
        self.assertIsNotNone(season_active)
        self.assertGreaterEqual(title.score, 0.95)
        self.assertGreaterEqual(season_active.score, 0.95)

    def test_expedition_entry_still_exists_as_a_click_target(self):
        """``expedition_entry`` 只是**降级**，不是删除：点击链必须还在。

        它现在的唯一使用方是 ``modes.py`` 里 ``NavigationStep(anchor="expedition_entry")``
        —— 那一跳靠模板定位出卡片中心再点。模板与区域都必须在，否则远征进不去。
        """
        navigator = self.navigator([])

        self.assertIsNotNone(navigator.templates.expedition_entry)
        self.assertIn("expedition_entry", navigator._REGIONS)

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

        self.assertEqual([(1819, 537), (465, 220), (1540, 357)], clicks)

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

    def test_world_boss_home_manage_support_team_variant_is_recognized(self):
        """未开放/次数用完时右下角换成「管理辅助队伍」，导航仍要认出这一页。

        前提断言：旧的单张「选择队伍」图在这一帧上确实不成立（实测 0.5107 < 0.82），
        否则夹具过期后这条测试会绿着却什么也没守（2026-10-30 的教训）。
        """
        navigator = self.navigator([])
        frame = world_boss_fixture("worldboss_home_manage_support_team")
        old = matcher.load_template(
            str(TEMPLATES / "world_boss" / "select_team_button.png")
        )
        old_match = find_template(
            frame,
            old,
            0.0,
            region=(1450, 990, 532, 130),
            reference_size=(1982, 1132),
        )
        assert old_match is not None and old_match.score < 0.82

        self.assertEqual("worldboss_home", navigator.observe(frame).name)

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

    def test_knights_weekly_reward_popup_is_reported_instead_of_unknown(self):
        """每周一骑士团点数结算弹窗（标题「获得每周骑士团点数奖励」）。

        与签到/支援弹窗同理：盖在骑士团主页上、压暗底页锚点，弹窗期间认不出底页。
        observe 必须先报出「这是周结算奖励弹窗」，交给全局弹窗守卫点掉；
        否则会掉到「未知画面」→ 连点中央 4 次都唤醒失败（2026-09-28 实跑就是这样卡住的）。
        """
        navigator = self.navigator([])

        popup = navigator.observe(world_boss_fixture("knights_weekly_reward_popup"))

        self.assertEqual("knights_weekly_reward_popup", popup.name)
        self.assertNotEqual("unknown", popup.name)

    def test_worldboss_support_reward_popup_is_reported_instead_of_unknown(self):
        """「世界首领辅助队伍奖励」弹窗必须被单独报出来，而不是掉进「未知画面」。

        ⚠️ 2026-10-19 08:11 每日任务「世界首领战 ✗」的现场：同僚团员借了辅助队伍
        并拿到奖励，进世界首领战主页时弹这层。它把底页压暗（右下角「选择队伍」直接
        认不出来）⇒ ``observe()`` 报 unknown ⇒ 导航转场
        `骑士团主页 → worldboss_home` 一路等到 08:12:44 失败。

        报出页名是为了让 ``Epic7GlobalPopupGuard``（装在 ``runtime.capture`` 上）点掉它。
        """
        navigator = self.navigator([])

        popup = navigator.observe(world_boss_fixture("worldboss_support_reward_live_20261019"))

        self.assertEqual("worldboss_support_reward_popup", popup.name)
        self.assertNotEqual("unknown", popup.name)

    def test_worldboss_home_is_reached_after_the_support_reward_popup_is_closed(self):
        """端到端：那一步转场（骑士团主页 → 世界首领战主页）带着弹窗也要走得通。

        这条钉的是**整条链**：守卫在 `runtime.capture` 里点掉弹窗 → 下一帧
        `observe()` 认出 `worldboss_home` == 本步 ``targets`` → 转场确认。
        只钉判据分数是不够的 —— 生产路径是「转场循环等目标页」。
        """
        from auto_game_unified.games.epic7.global_popups import (
            Epic7GlobalPopupGuard,
            load_network_reconnect_templates,
            load_worldboss_support_reward_templates,
        )

        popup = world_boss_fixture("worldboss_support_reward_live_20261019")
        home = world_boss_fixture("worldboss_home_chest_claimable")
        knights = world_boss_fixture("knights_home")
        pending = [popup, popup, popup, home, home, home]
        last = [home]

        def capture():
            if pending:
                last[0] = pending.pop(0)
            return last[0]

        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = Runtime(capture, clicks.append, emit=logs.append)
        runtime.set_capture_guard(
            Epic7GlobalPopupGuard(
                load_network_reconnect_templates(
                    ROOT / "games" / "epic7" / "templates" / "global"
                ),
                worldboss_support_reward_templates=(
                    load_worldboss_support_reward_templates(
                        ROOT / "games" / "epic7" / "templates" / "navigation"
                    )
                ),
                sleep=lambda _: None,
                now=lambda: 0.0,
            )
        )
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            runtime,
            sleep=lambda _: None,
            transition_frames=12,
        )

        final = navigator._transition(
            "knights_home",
            ("worldboss_home",),
            "worldboss_entry",
            "进入世界首领战",
            source_screen=knights,
        )

        self.assertEqual("worldboss_home", navigator.observe(final).name)
        self.assertTrue(
            any("close-worldboss-support-reward" in line for line in logs),
            "弹窗没被点掉（那一步又会等到超时）",
        )
        self.assertTrue(
            any("页面=世界首领战主页" in line and "转场确认" in line for line in logs),
            "转场没确认到目标页",
        )

    def test_knights_home_is_recognized_again_once_the_signin_popup_is_closed(self):
        """弹窗点掉之后必须能正常认出骑士团主页（别把「压暗」当永久状态）。"""
        navigator = self.navigator([])

        after = navigator.observe(world_boss_fixture("knights_home_after_popup"))

        self.assertEqual("knights_home", after.name)

    def test_navigation_walks_lobby_then_knights_then_world_boss(self):
        """2026-10-04 起：大厅不再点右下角那条横排（那是账号自定义的快捷栏），
        改成「点右上蓝四格开菜单 → 点菜单里的骑士团 → 点世界首领战入口」三下。
        """
        clicks: list[tuple[int, int]] = []
        navigator = self.navigator(
            [
                fixture("quick_menu_over_lobby"),
                fixture("quick_menu_over_lobby"),
                world_boss_fixture("knights_home"),
                world_boss_fixture("knights_home"),
                world_boss_fixture("worldboss_home"),
                world_boss_fixture("worldboss_home"),
            ],
            clicks=clicks,
        )

        navigator.navigate("world_boss", lobby_screen=world_boss_fixture("lobby_with_knights"))

        self.assertEqual(3, len(clicks))
        # ① 大厅右上蓝四格（避开橙角标那张模板）命中中心；
        # ② 快捷菜单里「骑士团」命中中心；③ 骑士团主页「世界首领战」入口命中中心。
        self.assertEqual((1862, 106), clicks[0])
        self.assertEqual((1617, 611), clicks[1])
        self.assertEqual((449, 693), clicks[2])

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
