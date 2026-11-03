"""活动剧情回归测试。

夹具只有一张 —— 「还有没看的故事」那一态（2026-10-31 从模拟器直接截的全屏帧）。
别的页面全部**跨路线借**：剧情 / 战斗 / 结算本来就与主线同页，拿主线的夹具就是
最真实的输入；支线场景页则是最重要的**反例**（它右下角那颗「重新进行」按钮左边
是同一枚马头徽章）。

覆盖五件事：

1. 观看故事页**认得出**，别的路线页面**认不出**；
2. 点的是右下角那颗按钮，且动作带全转场契约；
3. 两条终点判据都能收工（`ticket_free` 模板 / 按钮区没变化）；
4. 主线那三个「可能回观看故事页」的动作、以及「跳过 / 跳过确认」，
   落点白名单被补上了 —— 漏了会干等超时；
5. 黑图 / 陌生页不产生点击。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7.activity_story import (
    _PROGRESS_CHANGED_PIXELS,
    _PROGRESS_MISS_LIMIT,
    _SELECT_PAGE,
    ActivityStoryCleared,
    ActivityStoryRunner,
    ActivityStoryStateMachine,
    build_activity_story_machine,
    build_activity_story_templates,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS
from auto_game_unified.games.epic7.story import StoryState
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_activity_story"
SIDE_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_side_story"
# 真机战斗帧借主线的（1982×1132 那批）；3200×2000 的老截图宽高比不对，不能用。
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "activity_story"

_TEMPLATES = None
_FRAMES: dict[str, np.ndarray] = {}


def templates():
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = build_activity_story_templates(TEMPLATES)
    return _TEMPLATES


def _load(path: Path) -> np.ndarray:
    key = str(path)
    if key not in _FRAMES:
        raw = cv2.imread(key, cv2.IMREAD_COLOR)
        assert raw is not None, f"缺夹具 {path}"
        _FRAMES[key] = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    return _FRAMES[key]


def fixture(name: str) -> np.ndarray:
    return _load(FIXTURES / f"{name}.png")


def side_frame(name: str) -> np.ndarray:
    return _load(SIDE_FIXTURES / f"{name}.png")


def black_frame() -> np.ndarray:
    return np.zeros((1132, 1982, 3), dtype=np.uint8)


def with_changed_ticket(screen: np.ndarray) -> np.ndarray:
    """同一页、票数变了 —— 模拟「这一段真的消耗了票」。"""

    changed = screen.copy()
    changed[1030:1070, 1520:1620] = 255
    return changed


class _Runtime:
    """够 `ActivityStoryRunner` 构造用的最小替身。

    本文件只在**转场判定**这一层用它（`_transition_completed` 不碰 runtime），
    不跑主循环，所以不需要点击 / 抓帧 / 诊断那几件本事。
    """

    diagnostic_dir = None
    dry_run = False

    def now(self) -> float:
        return 0.0


class ActivityStoryFixtureTests(unittest.TestCase):
    def test_fixture_set_is_exactly_the_recorded_one(self):
        """三张，各有不能删的理由：

        - `select_pending`：观看故事页「还有没看的故事」那一态的唯一正样本；
        - `battle_clear_live_20261031`：**战斗关 CLEAR**（2026-10-31 19:42 的失败现场）。
          它是这条路线唯一一张「打完战斗停在哪」的证据 —— 删了它，「主线那张
          `clear` 认不出这一页」就再也复现不了。
        - `stamina_popup_live_20261031`：**行动力不足弹窗**（2026-10-31 20:20 的失败现场）。
          票不够时点「观看」就停在这一屏，删了它，「落点清单漏了弹窗 ⇒ 树叶点不到」
          这条就复现不了。
        """

        self.assertEqual(
            {
                "select_pending.png",
                "battle_clear_live_20261031.png",
                "stamina_popup_live_20261031.png",
            },
            {path.name for path in FIXTURES.glob("*.png")},
        )

    def test_templates_exist(self):
        self.assertEqual(
            {"watch_story_title.png", "ticket_cost.png"},
            {path.name for path in TEMPLATES.glob("*.png")},
        )


class ActivityStoryJudgementTests(unittest.TestCase):
    def test_the_watch_page_is_recognised(self):
        machine = ActivityStoryStateMachine(templates())

        match = machine._locate(fixture("select_pending"), "watch_story_title")

        self.assertIsNotNone(match)
        # 白掩膜下本页 1.0000；阈值 0.85 留了 0.15 的余量。
        self.assertGreaterEqual(match.score, 0.85)

    def test_other_routes_pages_are_not_the_watch_page(self):
        """全库天花板 0.6710 的那几屏必须认不出 —— 否则会去点别人的按钮。

        ⚠️ 只借 **1982×1132** 的帧：`epic7_story` 里有一批 3200×2000 的老截图，
        宽高比与模板基准差 10%，`find_best_template` 会直接抛「宽高比不一致」。
        """

        machine = ActivityStoryStateMachine(templates())
        for name in (
            SIDE_FIXTURES / "episode_detail.png",
            SIDE_FIXTURES / "scene.png",
            SIDE_FIXTURES / "side_story.png",
        ):
            with self.subTest(page=name.name):
                self.assertIsNone(
                    machine._locate(_load(name), "watch_story_title")
                )

    def test_the_ticket_badge_is_held_back_on_someone_elses_button(self):
        """支线场景页的「重新进行」按钮左边是**同一枚马头徽章**（白掩膜 0.8801）。

        ⇒ 徽章只能当辅助信号，阈值 0.90 刻意压在那一档上面。这条用例钉住
        「它不排他」这个事实：哪天有人把阈值降到 0.85，这里先红。
        """

        machine = ActivityStoryStateMachine(templates())
        scene = side_frame("scene")

        self.assertIsNone(machine._locate(scene, "ticket_cost"))
        self.assertIsNone(machine._locate(scene, "watch_story_title"))

    def test_a_frame_with_the_title_hidden_only_waits(self):
        """标题没认出来、徽章还在（淡入 / 压缩帧）⇒ 只等，不把页面交给主线。

        主线在这一屏会去认「准备战斗 / 观看故事」那些按钮，位置正压在右下角
        这颗按钮上 —— 点歪了就是一次无谓的转场。
        """

        machine = ActivityStoryStateMachine(templates())
        masked = fixture("select_pending").copy()
        masked[55:145, 60:480] = 0

        self.assertIsNone(machine._locate(masked, "watch_story_title"))
        self.assertIsNotNone(machine._locate(masked, "ticket_cost"))
        self.assertIsNone(machine.next_action(masked))

    def test_a_black_frame_never_produces_a_click(self):
        machine = ActivityStoryStateMachine(templates())

        with self.assertRaises(UnrecognizedScreen):
            machine.next_action(black_frame())


class ActivityStoryActionTests(unittest.TestCase):
    def test_the_watch_page_clicks_the_bottom_right_button(self):
        machine = ActivityStoryStateMachine(templates())

        action = machine.next_action(fixture("select_pending"))

        self.assertIsNotNone(action)
        self.assertEqual("start_activity_story", action.name)
        # 按钮胶囊实测横跨 x≈1452~1860、y≈1000~1095，取中心偏左。
        self.assertEqual((1656, 1047), action.point)
        self.assertEqual(_SELECT_PAGE, action.source_page)
        # 这条路打开了 `_REQUIRE_TRANSITION_CONTRACT`：落点一个都不能少。
        self.assertTrue(action.target_pages)
        self.assertIn("剧情播放", action.target_pages)
        self.assertIn("队伍准备", action.target_pages)
        self.assertIn("战斗中", action.target_pages)

    def test_a_new_segment_is_counted_only_when_coming_back_from_a_page(self):
        """轮次用状态做闸门：同一页连点不算两段，从剧情回来才算。"""

        machine = ActivityStoryStateMachine(templates())
        machine.next_action(fixture("select_pending"))

        # 进剧情（主线那一套：右上角跳过）。
        skip_action = machine.next_action(side_frame("story_skip"))
        self.assertEqual("skip", skip_action.name)
        self.assertNotEqual(StoryState.STAGE, machine.state)

        # 回到本页，票数变了 ⇒ 还有下一段。
        machine.next_action(with_changed_ticket(fixture("select_pending")))

        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(StoryState.STAGE, machine.state)


class ActivityStoryFinishTests(unittest.TestCase):
    def test_a_click_that_has_not_left_the_page_never_stops_the_route(self):
        """⚠️ 2026-10-31 实跑事故的回归钉。

        点「准备战斗」之后游戏要加载几秒，中间那几帧**还是本页**。
        旧判据拿「按钮区没变化」直接收工 ⇒ 整期只跑了一关。
        ⇒ 没离开过本页时，绝不允许下「已看完」的结论。
        """

        machine = ActivityStoryStateMachine(templates())
        machine.next_action(fixture("select_pending"))

        # 点完立刻又是同一帧（游戏还在加载）。
        action = machine.next_action(fixture("select_pending"))

        self.assertIsNotNone(action)
        self.assertEqual("start_activity_story", action.name)
        self.assertEqual(0, machine._progress_misses)

    def test_two_misses_after_leaving_the_page_stop_the_route(self):
        """真的离开过、回来画面又没往前走 ⇒ 连续两次才收工。"""

        machine = ActivityStoryStateMachine(templates())
        select = fixture("select_pending")
        story = side_frame("story_skip")

        # 「连续两次」这件事本身也是判据的一部分：一次太急（加载帧），三次太钝。
        self.assertEqual(2, _PROGRESS_MISS_LIMIT)
        machine.next_action(select)      # 点第 1 段
        machine.next_action(story)       # 离开本页（剧情播放）
        machine.next_action(select)      # 回来，画面没变 ⇒ 第 1 次 miss，继续点
        self.assertEqual(1, machine._progress_misses)
        machine.next_action(story)       # 又离开
        with self.assertRaises(ActivityStoryCleared):
            machine.next_action(select)  # 第 2 次 miss ⇒ 收工

    def test_a_changed_page_keeps_going(self):
        machine = ActivityStoryStateMachine(templates())
        select = fixture("select_pending")

        machine.next_action(select)
        machine.next_action(side_frame("story_skip"))
        action = machine.next_action(with_changed_ticket(select))

        self.assertEqual("start_activity_story", action.name)
        self.assertEqual(0, machine._progress_misses)

    def test_the_finish_verdict_is_a_stamina_exhausted_family_exit(self):
        """退出码 2「干完了但没得干了」，与支线 / 月塔同族。"""

        from auto_game_unified.core.runtime import StaminaExhausted

        self.assertTrue(issubclass(ActivityStoryCleared, StaminaExhausted))

    def test_the_finish_label_does_not_say_stamina(self):
        """收工文案不许说成「生命之叶耗尽」—— 那会让用户跑去买叶子。"""

        self.assertEqual("本期活动剧情已看完", ActivityStoryCleared.stop_label)

    def test_the_progress_threshold_sits_above_static_noise(self):
        """静止页面（实测按钮区 0、列表区 0~473 变化像素）必须判成「没往前走」。"""

        machine = ActivityStoryStateMachine(templates())
        frame = fixture("select_pending")
        changed, pixels = machine._progress_changed(frame)

        # 没记录过基线 ⇒ 当作「有变化」，不参与判收工。
        self.assertTrue(changed)
        self.assertEqual(-1, pixels)

        machine._last_progress = machine._progress_snapshot(frame)
        changed, pixels = machine._progress_changed(frame)
        self.assertFalse(changed)
        self.assertEqual(0, pixels)
        self.assertLess(pixels, _PROGRESS_CHANGED_PIXELS)


class ActivityStoryBattleClearTests(unittest.TestCase):
    """战斗关 CLEAR —— 2026-10-31 19:42 那次 215 秒没认出来的现场。

    主线那张 `clear` 是**剧情关** CLEAR，这一页是另一张（橙菱形 + CLEAR 字标带）。
    判据复用支线的 `battle_clear.png`（白掩膜，阈 0.80）。
    """

    def test_the_battle_clear_banner_is_recognised(self):
        machine = ActivityStoryStateMachine(templates())

        match = machine._locate(
            fixture("battle_clear_live_20261031"), "battle_clear"
        )

        self.assertIsNotNone(match)
        # 实测 0.9787；离阈值 0.80 有 0.18 的余量。
        self.assertGreaterEqual(match.score, 0.95)
        self.assertEqual((967, 480), match.center)

    def test_it_is_neither_the_watch_page_nor_the_story_clear(self):
        """两个必须分得开的方向：本页不能误判成 CLEAR，剧情关 CLEAR 也不能。"""

        machine = ActivityStoryStateMachine(templates())

        self.assertIsNone(
            machine._locate(fixture("select_pending"), "battle_clear")
        )
        self.assertIsNone(machine._locate(side_frame("story_clear"), "battle_clear"))

    def test_the_clear_page_turns_into_a_dismiss_action(self):
        machine = ActivityStoryStateMachine(templates())

        action = machine.next_action(fixture("battle_clear_live_20261031"))

        self.assertIsNotNone(action)
        self.assertEqual("dismiss_battle_clear", action.name)
        # 点 CLEAR 字标中心（与主线剧情关 CLEAR 同一手法：全屏过场点它继续）。
        self.assertEqual((967, 480), action.point)
        # 打完可能先结算、也可能直接回观看故事页 —— 两个落点都得写。
        self.assertIn(_SELECT_PAGE, action.target_pages)
        self.assertIn("结算确认", action.target_pages)

    def test_the_battle_supervisor_sees_the_result_on_that_page(self):
        """不接进 `result_visible`，监督会判「未知画面」干等 215 秒。"""

        machine = ActivityStoryStateMachine(templates())

        observation = machine.observe_battle(
            fixture("battle_clear_live_20261031"), None
        )

        self.assertTrue(observation.result_visible)

    def test_a_real_battle_frame_is_not_a_result(self):
        """反向条：真打斗那一帧不许被判成「战斗结束」。"""

        machine = ActivityStoryStateMachine(templates())
        frame = _load(STORY_FIXTURES / "battle_auto_on_live_20260809.png")

        observation = machine.observe_battle(frame, None)

        self.assertFalse(observation.result_visible)
        self.assertTrue(observation.battle_visible)


class ActivityStoryStaminaTests(unittest.TestCase):
    """票 / 行动力不够 —— 2026-10-31 20:20 那次「弹窗出来了却不去点树叶」的现场。

    判据一直是好的（同一帧 弹窗 1.0000 / 生命之叶 1.0000 / 购买 0.9998）；
    坏的是「点完观看允许落到哪」这张清单里没有弹窗 ⇒ 主循环判点击没生效，
    把 `stamina_material` 丢掉，干等 45 秒超时。
    """

    def test_the_watch_click_can_land_on_the_stamina_popup(self):
        machine = ActivityStoryStateMachine(templates())

        action = machine.next_action(fixture("select_pending"))

        self.assertIn("体力弹窗", action.target_pages)

    def test_the_popup_completes_the_click_that_opened_it(self):
        """落点对上 = 转场完成，状态机下一步才有机会说话。"""

        machine = ActivityStoryStateMachine(templates())
        start = machine.next_action(fixture("select_pending"))
        leaf = machine.next_action(fixture("stamina_popup_live_20261031"))
        runner = ActivityStoryRunner(
            machine, _Runtime(), sleep=lambda _: None, poll_seconds=0.0
        )

        self.assertEqual("stamina_material", leaf.name)
        self.assertEqual("体力弹窗", machine._confirmed_page)
        self.assertTrue(
            runner._transition_completed(start, leaf, machine._confirmed_page)
        )

    def test_the_leaf_is_picked_first_and_then_the_buy_button(self):
        """两段式：先点生命之叶（左边那颗树叶），再点购买。

        坐标取自弹窗实测：叶子块中心 (741,582)、绿色「购买」按钮 (1121,876)。
        """

        machine = ActivityStoryStateMachine(templates())
        popup = fixture("stamina_popup_live_20261031")

        leaf = machine.next_action(popup)
        self.assertEqual("stamina_material", leaf.name)
        self.assertEqual((741, 582), leaf.point)
        self.assertEqual("体力弹窗", leaf.source_page)

        # 「叶子点过了」这一笔只在**真点下去之后**记（`action_clicked`），
        # 观察帧（preview）不记 —— 否则预览一次就跳过第一步，树叶永远点不到。
        machine.action_clicked(leaf)

        buy = machine.next_action(popup)
        self.assertEqual("stamina_confirm", buy.name)
        self.assertEqual((1121, 876), buy.point)
        # 买完回的是**本页**（2026-10-31 20:26 实跑：体力 17 → 98，页面回到观看故事页），
        # 主线以为的队伍页 / 战斗中反而看不到 ⇒ 三个落点都得在名单里。
        self.assertIn(_SELECT_PAGE, buy.target_pages)
        self.assertIn("队伍准备", buy.target_pages)
        self.assertIn("战斗中", buy.target_pages)

    def test_a_refill_is_not_counted_as_a_stage_without_progress(self):
        """补一次行动力，不许被记成「点完没往前走」。

        ⚠️ 不挡会怎样：买完回到本页时故事列表当然没动 ⇒ 记一次 miss；
        一颗叶子不够、连着补两次就凑满 `_PROGRESS_MISS_LIMIT` ⇒ 误判「本期已看完」，
        整期只看了几段就收工。
        """

        machine = ActivityStoryStateMachine(templates())
        select = fixture("select_pending")

        machine.next_action(select)
        leaf = machine.next_action(fixture("stamina_popup_live_20261031"))
        self.assertEqual("stamina_material", leaf.name)
        # 弹窗那几帧认不出本页，实跑里会把「离开过」记上 —— 这里照实模拟。
        machine._left_page = True

        machine.next_action(select)

        self.assertEqual(0, machine._progress_misses)

    def test_the_popup_never_falls_through_to_the_watch_page_click(self):
        """弹窗必须**先于**本页决策判掉，否则会再去点「观看」（点在弹窗上，白点）。"""

        machine = ActivityStoryStateMachine(templates())

        action = machine.next_action(fixture("stamina_popup_live_20261031"))

        self.assertNotEqual("start_activity_story", action.name)


class ActivityStoryTransitionTests(unittest.TestCase):
    def test_clear_battle_and_completion_can_land_back_on_the_watch_page(self):
        """主线的三个出口动作都要把「观看故事页」算进落点白名单。

        漏了会怎样：主循环判「转场没完成」，把刚认出来的动作整个丢掉，干等 45 秒。
        `clear` / `results_confirm` 拿真实夹具验；`complete`（通关提示）没有 1982×1132
        的现成帧，用合成动作验纯函数那一层。
        """

        for name, expected in (
            ("story_clear", "clear"),
            ("results", "results_confirm"),
        ):
            with self.subTest(page=name):
                machine = ActivityStoryStateMachine(templates())
                machine.state = StoryState.WAIT_RESULTS

                action = machine.next_action(side_frame(name))

                self.assertIsNotNone(action, name)
                self.assertEqual(expected, action.name)
                self.assertIn(_SELECT_PAGE, action.target_pages)

        machine = ActivityStoryStateMachine(templates())
        from auto_game_unified.games.epic7.story import StoryAction

        synthetic = StoryAction(
            name="complete",
            point=(960, 1000),
            source_page="通关提示",
            target_pages=("额外奖励", "下一关入口"),
        )
        patched = machine._with_return_target(synthetic)

        self.assertEqual(
            ("额外奖励", "下一关入口", _SELECT_PAGE), patched.target_pages
        )
        # 点击点与来源页一个都不许动。
        self.assertEqual(synthetic.point, patched.point)
        self.assertEqual(synthetic.source_page, patched.source_page)

    def test_the_last_story_frame_can_end_right_back_on_the_watch_page(self):
        """纯剧情那一段的最后一屏：点完跳过确认，游戏不经过结算、**直接回本页**。

        ⚠️ 2026-10-31 19:53 实跑死在这：`skip` / `skip_confirm` 的落点白名单里没有
        「观看故事页」⇒ 主循环判「转场没完成」，把已经认出来的 `start_activity_story`
        整个丢掉，干等 45 秒报 `timeout_transition_skip_confirm`（退出码 1）。
        而现场帧其实是**已经回到本页、列表已往前一格**（上一项补了绿勾）。
        """

        for name, expected in (
            ("story_skip", "skip"),
            ("skip_confirm", "skip_confirm"),
        ):
            with self.subTest(page=name):
                machine = ActivityStoryStateMachine(templates())

                action = machine.next_action(side_frame(name))

                self.assertIsNotNone(action, name)
                self.assertEqual(expected, action.name)
                self.assertIn(_SELECT_PAGE, action.target_pages)

    def test_returning_to_the_watch_page_really_finishes_the_transition(self):
        """落点写进白名单只是第一步，主循环认不认才是死活。

        反向条一起钉住：**还停在跳过确认页**时不许算完成 —— 否则点击没生效、
        页面根本没动，也会被当成「转场成功」继续往前跑。
        """

        machine = ActivityStoryStateMachine(templates())
        skip_confirm = machine.next_action(side_frame("skip_confirm"))
        coming_back = machine.next_action(
            with_changed_ticket(fixture("select_pending"))
        )
        runner = ActivityStoryRunner(
            machine, _Runtime(), sleep=lambda _: None, poll_seconds=0.0
        )

        self.assertTrue(
            runner._transition_completed(skip_confirm, coming_back, _SELECT_PAGE)
        )
        self.assertFalse(
            runner._transition_completed(skip_confirm, skip_confirm, "跳过确认")
        )

    def test_non_exit_actions_are_not_touched(self):
        machine = ActivityStoryStateMachine(templates())

        action = machine.next_action(side_frame("team"))

        self.assertEqual("start_mission", action.name)
        self.assertNotIn(_SELECT_PAGE, action.target_pages)


class ActivityStoryPreviewTests(unittest.TestCase):
    def test_preview_leaves_the_progress_ledger_untouched(self):
        """主循环每轮先 preview 再决定是否提交；不还原就等于同一帧记两次账。"""

        machine = ActivityStoryStateMachine(templates())
        before = machine.next_action(fixture("select_pending"))
        self.assertEqual("start_activity_story", before.name)

        snapshot = (
            machine._last_progress,
            machine._awaiting_return,
            machine._left_page,
            machine._progress_misses,
        )
        machine.preview(fixture("select_pending"))

        self.assertIs(snapshot[0], machine._last_progress)
        self.assertEqual(snapshot[1], machine._awaiting_return)
        self.assertEqual(snapshot[2], machine._left_page)
        self.assertEqual(snapshot[3], machine._progress_misses)

    def test_preview_of_another_page_does_not_count_as_leaving(self):
        """`preview` 看到剧情页时不许把「离开过本页」这本账记上。

        ⚠️ 记上了会怎样：主循环每轮先 preview、再提交，而提交那一帧可能还是本页
        ⇒ 回来时直接拿「没变化」收工 —— 又是 2026-10-31 那个事故的变种。
        """

        machine = ActivityStoryStateMachine(templates())
        machine.next_action(fixture("select_pending"))

        machine.preview(side_frame("story_skip"))

        self.assertFalse(machine._left_page)
        self.assertTrue(machine._awaiting_return)


class ActivityStoryRegistrationTests(unittest.TestCase):
    def test_mode_spec_is_registered_as_an_event_route(self):
        spec = MODE_SPECS["activity_story"]

        self.assertEqual("活动剧情", spec.label)
        self.assertIs(ActivityStoryRunner, spec.runner_type)
        # 起点人工摆好 ⇒ 不导航、只能单独跑、跑完不回家。
        self.assertFalse(spec.needs_navigation)
        self.assertIsNone(spec.navigation_plan)
        # 「一次把本期看完」⇒ 次数不给用户选，99 只是兜底上限。
        self.assertFalse(spec.cycles_editable)
        self.assertEqual(99, spec.default_cycles)

    def test_the_builder_reads_the_route_template_directory(self):
        machine = build_activity_story_machine(TEMPLATES)

        self.assertIsInstance(machine, ActivityStoryStateMachine)
        self.assertEqual(StoryState.STAGE, machine.state)

    def test_desktop_catalog_puts_it_in_the_event_group(self):
        from auto_game_unified.desktop.catalog import GROUP_EVENT, route_by_name

        route = route_by_name("activity_story")

        self.assertEqual(GROUP_EVENT, route.group)
        # 派生自 needs_navigation=False：界面上只能单独勾。
        self.assertTrue(route.standalone_only)


if __name__ == "__main__":
    unittest.main()
