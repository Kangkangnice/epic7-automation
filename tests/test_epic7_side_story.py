"""支线故事状态机回归测试。

夹具是 2026-10-15 人工走查 5 关的实拍帧（`runtime_logs/_side_story/` 的副本，
逐张 md5 对得上）。状态机是**状态驱动**的，所以帧顺序必须照现场顺序喂 ——
本文件的序列就是那次走查的顺序。

覆盖四件事：

1. **完整一期**：4 关 × 两种 CLEAR × 两种蓝箭头落点，动作名序列与轮次；
2. **终点**：场景页连续看不到蓝箭头 ⇒ ``SideStoryCleared``（``StaminaExhausted``
   那一族，退出码 2 + 基类顺手回首页）；
3. **两处「不能写死位置」的判据**确实靠画面定位（地图光标、场景页箭头），
   且**不在别的页面上误命中**；
4. **每条本路线动作都带转场契约** —— 这条路打开了
   ``_REQUIRE_TRANSITION_CONTRACT``，漏填就是「点了不回头看」。
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.core.matcher import (
    MATCH_MODE_RAW,
    find_best_template,
    find_template,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS
from auto_game_unified.games.epic7.side_story import (
    _ARROW_MISS_LIMIT,
    _ARROW_PIXELS_MIN,
    _SEG_BOSS,
    _SIDE_MATCH_MODES,
    SideStoryRunner,
    SideStoryStateMachine,
    build_side_story_machine,
    build_side_story_templates,
)
from auto_game_unified.games.epic7.story import StoryState
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_side_story"
# 主线夹具：借它当「真实战斗画面」的反例（跨路线同长相；狗粮测试同样跨引，
# 见 `test_epic7_fodder.py` 的 `STORY_FIXTURES`）。
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "side_story"

# 「一期循环」的现场顺序。夹具 → 源帧的对应（md5 核对）：
# side_story=02 / episode_detail=04 / map=06 / helper_select=08 / team=09 /
# battle_clear=30 / complete_popup=23 / results=24b / scene=33 /
# team_direct=17b / story_skip=18b / skip_confirm=19b / story_clear=22
#
# 这一串覆盖了走查实测到的**四种循环形态**：
#   第 1 关 战斗关 + 先选辅助英雄（helper_select → team）
#   第 2 关 剧情关 + 点完箭头直接进队伍准备（team_direct）
#   第 3/4 关 战斗关 + 先选辅助英雄
PERIOD = (
    "side_story",
    "episode_detail",
    "map",
    "helper_select",
    "team",
    "battle_clear",
    "complete_popup",
    "results",
    "scene",
    "team_direct",
    "story_skip",
    "skip_confirm",
    "story_clear",
    "complete_popup",
    "results",
    "scene",
    "helper_select",
    "team",
    "battle_clear",
    "complete_popup",
    "results",
    "scene",
    "helper_select",
    "team",
    "battle_clear",
    "complete_popup",
    "results",
    "scene",
)

PERIOD_ACTIONS = (
    "enter_quick_entry",
    "enter_adventure",
    "pick_stage",
    "select_team",
    "start_mission",
    "dismiss_battle_clear",
    "close_complete_popup",
    "results_confirm",
    "advance_stage",
    "start_mission",
    "skip",
    "skip_confirm",
    "dismiss_story_clear",
    "close_complete_popup",
    "results_confirm",
    "advance_stage",
    "select_team",
    "start_mission",
    "dismiss_battle_clear",
    "close_complete_popup",
    "results_confirm",
    "advance_stage",
    "select_team",
    "start_mission",
    "dismiss_battle_clear",
    "close_complete_popup",
    "results_confirm",
    "advance_stage",
)

# 本路线自己的动作名（其余是 `super().next_action` 委托给主线的）。
SIDE_ACTIONS = frozenset(
    {
        "enter_quick_entry",
        "enter_adventure",
        "pick_stage",
        "dismiss_battle_clear",
        "dismiss_story_clear",
        "close_complete_popup",
        "advance_stage",
    }
)

# 模板加载（主线那 20 多张 + `quick_battle` 检测器）是整个文件最贵的一步，
# 且与机器实例无关 ⇒ 只加载一次、每帧只解码一次。
_TEMPLATES = None
_FRAMES: dict[str, np.ndarray] = {}


def templates():
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = build_side_story_templates(TEMPLATES)
    return _TEMPLATES


def fixture(name: str) -> np.ndarray:
    if name not in _FRAMES:
        raw = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
        assert raw is not None, f"缺夹具 {name}.png"
        _FRAMES[name] = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    return _FRAMES[name]


class SideStoryPeriodTests(unittest.TestCase):
    """完整一期：走查的现场顺序跑一遍。"""

    def test_the_recorded_period_produces_the_expected_action_sequence(self):
        machine = SideStoryStateMachine(templates())

        actions = [machine.next_action(fixture(name)) for name in PERIOD]

        self.assertEqual(
            list(PERIOD_ACTIONS), [action.name for action in actions]
        )
        # 4 关打完 ⇒ 轮次 4。轮次只在**场景页**上记一次（用状态做闸门），
        # 所以同一页停留多帧不会重复计数 —— 下面这条专测它。
        self.assertEqual(4, machine.completed_cycles)
        self.assertEqual(StoryState.WAIT_NEXT_STAGE, machine.state)

    def test_the_arrow_click_lands_on_the_recorded_spot_in_every_scene(self):
        machine = SideStoryStateMachine(templates())

        points = []
        for name in PERIOD:
            action = machine.next_action(fixture(name))
            if action is not None and action.name == "advance_stage":
                points.append(action.point)

        # 实测四张场景页（16 / 25 / 33 / 41）的箭头都在同一带，点它的中心。
        self.assertEqual([(1820, 750)] * 4, points)

    def test_the_stage_pick_uses_the_cursor_position_not_a_hardcoded_one(self):
        """地图布局每期都变 ⇒ 位置必须来自画面（青色菱形往下固定像素）。"""

        machine = SideStoryStateMachine(templates())

        action = machine.next_action(fixture("map"))

        self.assertEqual("pick_stage", action.name)
        # 实测 06_map_wait.png：菱形中心 (1180,489)、紫剑中心 (1182,605)。
        self.assertEqual((1180, 605), action.point)

    def test_staying_on_the_scene_page_does_not_double_count_the_cycle(self):
        machine = SideStoryStateMachine(templates())
        scene = fixture("scene")

        first = machine.next_action(scene)
        second = machine.next_action(scene)
        third = machine.next_action(scene)

        self.assertEqual(
            ["advance_stage"] * 3, [item.name for item in (first, second, third)]
        )
        self.assertEqual(1, machine.completed_cycles)


class SideStoryClearVariantTests(unittest.TestCase):
    """两种 CLEAR：战斗关的与剧情关的。判据两套、契约一套。"""

    def test_both_clear_variants_are_handled_by_this_route(self):
        machine = SideStoryStateMachine(templates())

        battle = machine.next_action(fixture("battle_clear"))
        story = machine.next_action(fixture("story_clear"))

        # 战斗关 CLEAR 走本路线自己的模板（主线的 clear 在这页上不过阈）。
        self.assertEqual("dismiss_battle_clear", battle.name)
        self.assertIn(battle.name, SIDE_ACTIONS)
        # 剧情关 CLEAR 的**判据**整个复用主线（`story_clear` 别名 → 主线的 `clear`），
        # 但动作是这条路自己的 —— 因为契约要含「完成故事」这个中间落点。
        self.assertEqual("dismiss_story_clear", story.name)
        self.assertIn(story.name, SIDE_ACTIONS)
        # 两者点的是同一个位置：命中中心（实测 (951,503)）。
        self.assertEqual(battle.point[0], 1820)
        self.assertEqual(story.point, (951, 503))

    def test_both_clear_actions_declare_the_complete_popup_as_a_landing_page(self):
        """⚠️ 实跑回归（2026-10-15）：漏了这一个落点，整条路线会在第一关挂死。

        打完一关先弹「完成故事」再进结算页 ⇒ 转场验收（白名单）必须认它。
        不认的话主循环会把「去关弹窗」这个动作整个置成 None 丢掉，
        弹窗认出来了却没人点，一路等到 45 秒超时报错。
        """

        machine = SideStoryStateMachine(templates())

        for name in ("battle_clear", "story_clear"):
            action = machine.next_action(fixture(name))
            self.assertIn(
                "完成故事",
                action.target_pages,
                f"{action.name} 的契约漏了「完成故事」，实跑会卡死在弹窗上",
            )
            self.assertIn("结算确认", action.target_pages)

    def test_the_story_clear_judgement_is_the_main_line_one(self):
        """复用而非重抄：区域与阈值必须与主线 `clear` 同源，不能在本地再抄一份。"""

        machine = SideStoryStateMachine(templates())

        alias = machine._locate(fixture("story_clear"), "story_clear")
        mainline = machine._locate(fixture("story_clear"), "clear")

        self.assertIsNotNone(alias)
        self.assertEqual(mainline.score, alias.score)
        self.assertEqual(mainline.center, alias.center)
        # 它不该占用本路线自己的区域 / 阈值表（那是抄一份 = 两个数源）。
        self.assertNotIn("story_clear", machine._REGIONS)
        self.assertNotIn("story_clear", machine._THRESHOLDS)

    def test_the_battle_clear_template_does_not_fire_on_the_scene_page(self):
        """场景页不命中 —— 旧口径下它曾在这张模板上拿 0.8429，那时靠**位置过滤**排除。

        换成字标带 + 白掩膜之后它只剩 0.2586（阈值 0.80 自己就挡住了），但
        `_LOCATE_MIN_X` 仍然留着当第二道（理由见那里的注释）。
        """

        machine = SideStoryStateMachine(templates())

        self.assertIsNone(machine._locate(fixture("scene"), "battle_clear"))
        # 真 CLEAR 页必须仍然命中。
        self.assertIsNotNone(machine._locate(fixture("battle_clear"), "battle_clear"))

    def test_the_two_clear_judgements_do_not_cross_fire(self):
        machine = SideStoryStateMachine(templates())

        self.assertIsNone(machine._locate(fixture("battle_clear"), "story_clear"))
        self.assertIsNone(machine._locate(fixture("story_clear"), "battle_clear"))


class SideStoryBattleObservationTests(unittest.TestCase):
    """战斗监督那五项判据，在本路线会被它看到的每一屏上都必须有一项为真。

    ⚠️ **2026-10-15 第二次实跑就死在这里。** 形状是「同一张画面，一个消费方
    认识了、另一个没认识」：状态机认得战斗关 CLEAR（`dismiss_battle_clear`，
    实测 0.9304），监督却认不得 —— 它的 `result_visible` 名单里只有**剧情关**的
    `clear` 模板。于是那一屏五项全 False ⇒ 判成「未知画面」⇒ 干等 45 秒报
    `battle_unrecognized` ⇒ 退出码 1，**状态机连上场的机会都没有**。

    `SideStoryClearVariantTests` 那几条只管状态机侧（`next_action`）——
    监督侧（`observe_battle`）在这次故障之前是**零覆盖**，所以连
    「`battle_clear` 夹具上就是 False」都没人问过。
    """

    def _observation(self, directory: Path, name: str):
        raw = cv2.imread(str(directory / f"{name}.png"), cv2.IMREAD_COLOR)
        self.assertIsNotNone(raw, f"缺夹具 {directory / name}.png")
        screen = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
        return SideStoryStateMachine(templates()).observe_battle(screen, screen)

    @staticmethod
    def _recognized(observation) -> bool:
        """`core/battle_supervisor.py` 里那五项，缺一不可。"""

        return bool(
            observation.pre_battle_visible
            or observation.battle_visible
            or observation.result_visible
            or observation.allowed_action is not None
            or observation.pre_battle_business_visible
        )

    def test_the_supervisor_recognizes_the_battle_clear_page(self):
        """核心回归：监督不认这一页，就永远不把控制权交回状态机。"""

        observation = self._observation(FIXTURES, "battle_clear")

        self.assertTrue(observation.result_visible)
        self.assertTrue(self._recognized(observation))

    def test_the_other_landing_pages_stay_recognized(self):
        """完成故事弹窗与结算页本来就认得（主线判据给的），修复不该碰坏它们。"""

        for name in ("complete_popup", "results"):
            with self.subTest(name=name):
                self.assertTrue(
                    self._recognized(self._observation(FIXTURES, name)),
                    f"{name} 这一屏既认不出、也没在战斗，监督会静默干等到超时",
                )

    def test_the_battle_clear_judgement_never_fires_on_a_real_battle_frame(self):
        """反向护栏：真实战斗画面绝不能被判成「战斗结束」。

        误判的代价比原故障更大 —— 监督会在**战斗中途**收手，状态机随即在战斗
        画面上点 (1820,750)。

        ⚠️ 除了「都不是 True」，还要把**分数有多低**钉住：只看 False 的话，把阈值
        抬到 0.99 也能全绿 —— 那是拿漏判换误判，正是 0.92 那次的错法。
        """

        machine = SideStoryStateMachine(templates())
        kwargs = {
            "region": machine._REGIONS["battle_clear"],
            "reference_size": machine._REFERENCE_SIZE,
        }
        scores: dict[str, float] = {}

        for name in (
            "battle_auto_off_live_20260809",
            "battle_auto_on_live_20260809",
            "battle_manual_skill_variant_live_20260815",
            "skill_animation_live_20260813",
        ):
            with self.subTest(name=name):
                observation = self._observation(STORY_FIXTURES, name)

                self.assertFalse(
                    observation.result_visible,
                    f"{name} 是真实战斗帧，监督不该在这一帧收手",
                )
                # 而且要**照旧认作战斗中**，不能掉进「未知画面」。
                self.assertTrue(
                    observation.battle_visible,
                    f"{name} 应该仍在「战斗中」，否则监督会一路磨到绝对超时",
                )
                raw = cv2.imread(str(STORY_FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
                screen = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                scores[name] = find_best_template(
                    screen, machine.side.battle_clear, mode="white_mask", **kwargs
                ).score

        highest = max(scores.values())
        self.assertLess(
            highest,
            machine._THRESHOLDS["battle_clear"] - 0.20,
            f"真实战斗帧上这张模板的分太高了："
            f"{max(scores, key=scores.get)}={highest:.4f}（阈值 "
            f"{machine._THRESHOLDS['battle_clear']}）",
        )


class SideStoryClearRulerTests(unittest.TestCase):
    """战斗关 CLEAR 的**尺子本身** —— 2026-10-15 第三次实跑修的就是它。

    形状是「同一屏，第二次实跑认得、第三次认不出」。那一轮我把 CLEAR 接进了
    战斗监督的名单（对，但不够）—— 坏的是尺子：

      * 模板裁的是横幅的**发光区**，而发光是**脉冲动画**；口径是**原样 RGB**，
        把场景底图也一起算进相似度 ⇒ 同一页在同一台机器上分数在 0.9115~1.0000
        之间漂，而阈值恰好是 **0.92**；
      * 更要命的是那张模板**分不开剧情关 CLEAR**：白掩膜下真 CLEAR 0.9975、
        剧情 CLEAR 0.9531 —— 只差 **0.044**（`test_the_old_glow_template_...`）。

    ⇒ 换成「CLEAR **字标带**」（装饰线 + 两端小菱形 + 五个字母）+ **白掩膜口径**
    （`_SIDE_MATCH_MODES`）。字标才是横幅唯一的静态语义标识。

    本类钉住三件事：

      1. 第三次实跑那张诊断帧（已固化成夹具）必须被**两个消费方**都认出来；
      2. 拉开余量的是**尺子**而不是阈值 —— 谁把口径摘了，最难受那帧的余量
         立刻从 0.175 塌回 0.020；
      3. 剧情关 CLEAR 必须被挡在很外面（旧模板做不到，见下）。
    """

    #: 第三次实跑的诊断帧 —— `epic7_side_story.log` 2026-10-15 22:12:38
    #: 「安全停止：战斗画面持续无法识别超时」。诊断目录按路线滚动清理，所以固化成夹具。
    FAILURE = "battle_clear_live_20261015"
    #: 走查第 4 关的 CLEAR（`38_battle4b`）。旧设计里**最难受的一帧**：原样 RGB 只有
    #: 0.8223，当年专门为它加了第二张候选 `battle_clear_alt` 来「管另一个发光相位」。
    DIM_PHASE = "battle_clear_dim_20261015"

    #: 两张真 CLEAR 在新尺子上的实测分。
    FAILURE_SCORE = 0.9794
    DIM_PHASE_SCORE = 0.9754
    #: 新模板的命中点（字标带中心）。旧模板是 (830,410)，两者不同 —— 这也是
    #: `_LOCATE_MIN_X` 仍然拦得住旧口径旁命中的原因之一。
    CLEAR_CENTER = (967, 480)
    #: 剧情关 CLEAR 在新尺子上的实测分（旧尺子 0.9531）。
    STORY_CLEAR_SCORE = 0.2138
    #: 旧模板 = 从 `battle_clear` 夹具上裁下来的那团**发光**，330x100 @(665,360)。
    GLOW_CROP = (665, 360, 995, 460)  # (x0, y0, x1, y1)
    #: 旧尺子的两个数（白掩膜口径）：真 CLEAR / 剧情 CLEAR，只差 0.0444。
    OLD_REAL_SCORE = 0.9975
    OLD_STORY_SCORE = 0.9531
    #: 旧尺子配**原样 RGB** 时，第三次实跑那一帧的实测分 —— 比当年的阈值 0.92 还低。
    OLD_RAW_FAILURE_SCORE = 0.9116
    OLD_THRESHOLD = 0.92

    def _machine(self) -> SideStoryStateMachine:
        return SideStoryStateMachine(templates())

    def test_the_failure_frame_is_recognized_by_both_consumers(self):
        """核心回归：那一帧上**状态机与战斗监督都要认得**。

        ⚠️ 两个消费方**都要断言**。第二次实跑的死法正是「状态机认得、监督不认得」，
        所以只验一边等于没验 —— 这正是「一张画面有多个消费方」那条教训。
        """
        machine = self._machine()
        screen = fixture(self.FAILURE)

        found = machine._locate(screen, "battle_clear")
        self.assertIsNotNone(found, "第三次实跑的那一帧又认不出来了")
        # 断言写到「依据」：多高就是多高，不是「只要不是 None 就算过」。
        self.assertAlmostEqual(self.FAILURE_SCORE, found.score, places=3)
        self.assertEqual(self.CLEAR_CENTER, found.center)

        # 消费方 ①：状态机 → 必须给出「点右下角箭头」这个动作。
        self.assertEqual("dismiss_battle_clear", machine.next_action(screen).name)

        # 消费方 ②：战斗监督 → 必须认作「战斗结束」，否则控制权永远交不回状态机。
        self.assertTrue(
            machine.observe_battle(screen, screen).result_visible,
            "监督不认这一页，就会干等到 45 秒 battle_unrecognized",
        )

    def test_the_dim_phase_frame_is_also_recognized(self):
        """走查第 4 关那张（旧设计里最难受的一帧）现在也必须稳稳过阈。

        ⚠️ 这一条同时是**口径的护栏**：原样 RGB 下它在同一张模板上只有 **0.8197**
        —— 离 0.80 只差 0.020。谁把 `_SIDE_MATCH_MODES` 摘了，这里的
        `threshold + 0.10` 立刻不成立。
        """
        machine = self._machine()
        screen = fixture(self.DIM_PHASE)

        found = machine._locate(screen, "battle_clear")

        self.assertIsNotNone(found)
        self.assertAlmostEqual(self.DIM_PHASE_SCORE, found.score, places=3)
        self.assertGreater(
            found.score,
            machine._THRESHOLDS["battle_clear"] + 0.10,
            "余量太薄 —— 擦着阈值过等于下次换个发光相位又失效",
        )

    def test_the_route_actually_uses_the_white_mask_ruler(self):
        """生产路径必须**真的**走白掩膜，而不是只有那张表写着 white_mask。

        ⚠️ 名字表对不等于 `_locate` 真的转发了它。这里用同一帧、同一区域、同一
        模板，把「显式白掩膜」与「显式原样 RGB」各算一遍，钉住生产分等于前者。
        """
        machine = self._machine()
        screen = fixture(self.FAILURE)
        kwargs = {
            "region": machine._REGIONS["battle_clear"],
            "reference_size": machine._REFERENCE_SIZE,
        }

        route = machine._locate(screen, "battle_clear")
        masked = find_template(
            screen, machine.side.battle_clear, 0.0, mode="white_mask", **kwargs
        )
        raw = find_best_template(screen, machine.side.battle_clear, mode="raw", **kwargs)

        self.assertAlmostEqual(masked.score, route.score, places=6)
        self.assertNotAlmostEqual(raw.score, route.score, places=3)

        # 口径是**逐锚点**声明的：只有这一条例外，其余五条仍是原样 RGB。
        modes = machine._MATCH_MODES
        self.assertIs(_SIDE_MATCH_MODES, modes, "类常量与模块表必须同一份对象")
        self.assertEqual("white_mask", modes["battle_clear"])
        for name in ("quick_entry", "adventure", "map_panel", "replay", "complete_popup"):
            with self.subTest(judge=name):
                self.assertEqual(MATCH_MODE_RAW, modes.get(name, MATCH_MODE_RAW))

    def test_the_old_glow_template_could_not_be_separated_by_any_threshold(self):
        """旧模板（横幅发光区）**换口径也救不回来** —— 这才是「换模板」的依据。

        同一张旧模板、同一口径（白掩膜）：

        | 帧 | 实测 |
        |---|---|
        | 真·战斗关 CLEAR（第三次实跑那张） | 0.9975 |
        | **剧情关 CLEAR**（必须挡住） | **0.9531 @(716,633)** |

        只差 **0.044**，而且那处命中在 x=716 —— **`_LOCATE_MIN_X` 也拦不住**。
        ⇒ 任何 ≤0.9531 的阈值都会把剧情关 CLEAR 判成战斗关 CLEAR（决策顺序里
        `battle_clear` 排在 `story_clear` 前面），任何 ≥0.9975 的阈值又会擦着真阳性过。
        """
        machine = self._machine()
        x0, y0, x1, y1 = self.GLOW_CROP
        old_template = np.ascontiguousarray(fixture("battle_clear")[y0:y1, x0:x1])
        kwargs = {
            "region": machine._REGIONS["battle_clear"],
            "reference_size": machine._REFERENCE_SIZE,
        }

        real = find_template(
            fixture(self.FAILURE), old_template, 0.0, mode="white_mask", **kwargs
        )
        story = find_best_template(
            fixture("story_clear"), old_template, mode="white_mask", **kwargs
        )

        self.assertAlmostEqual(self.OLD_REAL_SCORE, real.score, places=3)
        self.assertAlmostEqual(self.OLD_STORY_SCORE, story.score, places=3)
        self.assertGreater(
            story.center[0],
            700,
            "旧模板那处旁命中居然落在位置过滤之外：上面的论证前提不成立，先查夹具",
        )
        # 真阳性地板与「必须挡住的那一页」之间的间隔。
        self.assertLess(real.score - story.score, 0.05, "旧模板居然分得开？先查夹具")

        # 同一张旧模板、**原样 RGB** 口径：第三次实跑那帧低于当年的阈值 ⇒ 复现事故。
        old_raw = find_best_template(
            fixture(self.FAILURE), old_template, mode="raw", **kwargs
        )
        self.assertAlmostEqual(self.OLD_RAW_FAILURE_SCORE, old_raw.score, places=3)
        self.assertLess(old_raw.score, self.OLD_THRESHOLD, "事故前提不成立，先查夹具")

    def test_the_new_ruler_keeps_the_story_clear_page_far_away(self):
        """新尺子下，剧情关 CLEAR 离阈值很远 —— 两页不再靠分数勉强分开。"""
        machine = self._machine()
        screen = fixture("story_clear")

        self.assertIsNone(machine._locate(screen, "battle_clear"))
        # 真 CLEAR 与它的间隔：新尺子 0.77，旧尺子 0.044。
        self.assertGreater(
            self.FAILURE_SCORE - self.STORY_CLEAR_SCORE,
            0.50,
            "剧情关 CLEAR 又被拉近了 —— 换回发光区当模板了吗",
        )
        # 剧情关 CLEAR 仍然由它自己那条判据接住（复用主线的 `clear`）。
        self.assertEqual("dismiss_story_clear", machine.next_action(screen).name)

    def test_the_template_is_the_wordmark_band_cut_from_the_fixture(self):
        """模板的**出处**：`battle_clear` 夹具上的「CLEAR 字标带」，不是那团发光。

        ⚠️ 换模板来源 = 改这条用例，并**重算**上面那张实测表与 `_SIDE_THRESHOLDS`
        里那一档 —— 别只把断言改绿。
        """
        x0, x1 = 795, 1140
        y0, y1 = 440, 520
        expected = np.ascontiguousarray(fixture("battle_clear")[y0:y1, x0:x1])

        template = SideStoryStateMachine(templates()).side.battle_clear

        self.assertEqual((y1 - y0, x1 - x0), template.shape[:2])
        np.testing.assert_array_equal(expected, template)


class SideStoryArrowLandingTests(unittest.TestCase):
    """点完蓝箭头有两种落点，都必须接得住。"""

    def test_arrow_can_land_on_either_the_helper_select_or_the_team_page(self):
        helper = SideStoryStateMachine(templates())
        direct = SideStoryStateMachine(templates())

        # 形态一：先到助手选择。
        self.assertEqual(
            "advance_stage", helper.next_action(fixture("scene")).name
        )
        self.assertEqual(
            "select_team", helper.next_action(fixture("helper_select")).name
        )
        self.assertEqual(StoryState.TEAM, helper.state)

        # 形态二：直接到队伍准备。
        self.assertEqual(
            "advance_stage", direct.next_action(fixture("scene")).name
        )
        self.assertEqual(
            "start_mission", direct.next_action(fixture("team_direct")).name
        )
        self.assertEqual(StoryState.TEAM, direct.state)


class SideStoryTerminalTests(unittest.TestCase):
    """终点：场景页上再也看不到蓝色三箭头。"""

    def terminal_frame(self) -> np.ndarray:
        """场景页**抹掉右下三箭头**后的帧（`scene_without_arrow.png`，**合成图**）。

        合成方式：拿 `33_after_confirm3.png`（= `scene.png`），把右下箭头那块区域
        `[600:940, 1600:1982]` 用同场景的地面 `[260:600, 1600:1982]` 覆盖掉
        （整块上移 340 像素，接缝落在场景地面渐变里，其余像素一字未动）。

        它只用来验证**纯逻辑**（「看不见箭头」这条判据怎么收尾），**不代表真实的
        终点画面** —— 真终点长什么样这次走查没走到（打到第 5 关就停了）。
        ⇒ 这里顺手用判据自查一次：在它上面箭头像素必须是 0、在原帧上必须过阈。
        """

        frame = fixture("scene_without_arrow")

        machine = SideStoryStateMachine(templates())
        self.assertEqual(0, machine._arrow_pixels(frame))
        self.assertGreater(
            machine._arrow_pixels(fixture("scene")), _ARROW_PIXELS_MIN
        )
        return frame

    def test_a_single_arrowless_frame_is_not_a_conclusion(self):
        """箭头是**闪烁**的 ⇒ 单帧看不见只当「等一下」，绝不收工、也绝不报「认不出」。"""

        machine = SideStoryStateMachine(templates())

        for _ in range(_ARROW_MISS_LIMIT - 1):
            self.assertIsNone(machine.next_action(self.terminal_frame()))

        self.assertEqual(0, machine.completed_cycles)

    def test_consecutive_arrowless_frames_chain_into_boss_segment(self):
        """① 打完（连续无箭头）⇒ **不再收工**（2026-11-01 语义更改）：点「离开」接力去 ②。

        旧断言是「抛 SideStoryCleared 收工」；连打链路下（用户明确要求 ①→②→③
        一条龙）改为点「离开」回地图、段落切到 `_SEG_BOSS`。新的收工点只剩
        「最后一个据点点完离开回地图」与「③ 段次数用尽」。
        """

        machine = SideStoryStateMachine(templates())
        frame = self.terminal_frame()

        # 第 `_ARROW_MISS_LIMIT` 次调用产出「离开」；之后的帧进入「等回地图」返回 None
        # （与旧语义「抛异常终止循环」不同，现在是「动作发出后原地等待」）。
        action = None
        for _ in range(_ARROW_MISS_LIMIT):
            action = machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("scene_leave", action.name)
        self.assertEqual(_SEG_BOSS, machine._segment)
        self.assertTrue(machine._leaving)

    def test_the_arrowless_scene_page_is_not_reported_as_an_unknown_screen(self):
        """这一页是**认出过的**场景页 ⇒ 不能掉进「认不出画面」那条路。

        当年若把「认识但这一帧没动作」当成「不是我的页面」去委托主线，
        `super().next_action` 会抛 `UnrecognizedScreen`：日志会刷「结论待确认」、
        一旦唤醒开关打开还会去点屏幕中间，真终点也要拖到状态超时才报。
        """

        machine = SideStoryStateMachine(templates())
        frame = self.terminal_frame()

        try:
            action = machine.next_action(frame)
        except UnrecognizedScreen as error:  # pragma: no cover - 回归护栏
            self.fail(f"场景页被当成未知画面了：{error}")

        self.assertIsNone(action)

    def test_the_miss_counter_resets_as_soon_as_the_arrow_comes_back(self):
        machine = SideStoryStateMachine(templates())
        terminal = self.terminal_frame()

        for _ in range(_ARROW_MISS_LIMIT - 1):
            machine.next_action(terminal)
        # 箭头回来了一帧 ⇒ 这笔「连续缺失」的账清零，重新数。
        self.assertEqual("advance_stage", machine.next_action(fixture("scene")).name)

        for _ in range(_ARROW_MISS_LIMIT - 1):
            self.assertIsNone(machine.next_action(terminal))


class SideStoryBookingTests(unittest.TestCase):
    """``preview`` 不许留下痕迹（含本路线自己的账本）。"""

    def test_preview_does_not_commit_cycles_state_or_the_miss_counter(self):
        machine = SideStoryStateMachine(templates())

        action, outcome = machine.preview(fixture("scene"))

        self.assertEqual("advance_stage", action.name)
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual(0, machine._arrow_misses)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(StoryState.WAIT_NEXT_STAGE, outcome[0])

    def test_preview_does_not_advance_the_arrow_miss_counter(self):
        """主循环每轮先 `preview` 再决定是否提交；不还原就会把 12 帧门槛砍成 6 秒。"""

        machine = SideStoryStateMachine(templates())
        frame = fixture("scene_without_arrow")

        for _ in range(_ARROW_MISS_LIMIT * 3):
            machine.preview(frame)

        self.assertEqual(0, machine._arrow_misses)


class SideStoryJudgementTests(unittest.TestCase):
    """判据的边界 —— 这里断言的是**别的页面锚点是排他的**，不是「判据处处为 0」。

    ⚠️ 两个颜色判据**本身并不排他**（实测）：

    | 判据 | 唯一的非目标命中 | 为什么无害 |
    |---|---|---|
    | `_arrow_pixels` | 支线故事列表页 1190 像素（阈值 3500 的 1/3） | 它只在**「重新进行」命中**时才被读（`_scene_action`） |
    | `_cursor_point` | 场景页能选出个 (366,892) | 它只在**关卡地图面板命中**时才被读 |

    所以真正的护栏是「`replay` / `map_panel` 两个页面锚点各自排他」＋「决策顺序
    先判 `replay` 再判 `map_panel`」。下面就把这两条钉住 —— 只断言「处处为 0」
    会因为无关页面上一点同色像素就红，反而掩盖了真实的安全论证。
    """

    NON_SCENE_PAGES = (
        "side_story",
        "episode_detail",
        "map",
        "helper_select",
        "team",
        "team_direct",
        "story_skip",
        "skip_confirm",
        "battle_clear",
        "story_clear",
        "complete_popup",
        "results",
    )

    def test_the_page_anchors_are_exclusive(self):
        machine = SideStoryStateMachine(templates())

        # 「重新进行」只在场景页上命中 —— 它是箭头判据与时序账本的开关。
        self.assertIsNotNone(machine._locate(fixture("scene"), "replay"))
        # 关卡地图面板只在关卡地图上命中 —— 它是光标判据的开关。
        self.assertIsNotNone(machine._locate(fixture("map"), "map_panel"))

        for name in self.NON_SCENE_PAGES:
            frame = fixture(name)
            if name != "scene":
                self.assertIsNone(
                    machine._locate(frame, "replay"), f"{name} 上误命中场景页锚点"
                )
            if name != "map":
                self.assertIsNone(
                    machine._locate(frame, "map_panel"), f"{name} 上误命中地图面板锚点"
                )

    def test_the_arrow_count_stays_under_threshold_off_the_scene_page(self):
        machine = SideStoryStateMachine(templates())

        for name in self.NON_SCENE_PAGES:
            pixels = machine._arrow_pixels(fixture(name))
            self.assertLess(
                pixels, _ARROW_PIXELS_MIN, f"{name} 上的青色像素会翻过箭头阈值"
            )

    def test_the_stage_map_wins_over_the_cursor_coincidence_on_the_scene_page(self):
        """场景页上光标判据也会命中一点东西 ⇒ 必须靠**决策顺序**把它挡在门外。

        若哪天有人把 `map_panel` 那一段提到 `replay` 前面，场景页会被判成
        「关卡地图」、去点一个根本不存在的关卡入口 —— 这条断言就是那道门。
        """

        machine = SideStoryStateMachine(templates())
        scene = fixture("scene")

        # 现状：光标判据在场景页上确实会命中（记录下来，免得以后被当成「不该发生」）。
        self.assertIsNotNone(machine._cursor_point(scene))
        # 但决策顺序保证了它不会被采纳。
        self.assertIsNone(machine._locate(scene, "map_panel"))
        self.assertEqual("advance_stage", machine.next_action(scene).name)

    def test_the_cursor_judgement_lands_below_the_current_node(self):
        """用户口径：认的是**黄色外圈 + 中间蓝色闪光的光标**，点它**下方**。

        实测 06_map_wait.png：青色菱形中心 (1180,489)、紫剑 (1182,605) ——
        往下固定像素，**不依赖紫色图标是否存在**（用户 2026-10-15 明确要求忽略它）。
        """

        machine = SideStoryStateMachine(templates())

        self.assertEqual((1180, 605), machine._cursor_point(fixture("map")))

    def test_the_arrow_judgement_only_fires_off_the_clean_scene_page(self):
        machine = SideStoryStateMachine(templates())

        self.assertGreater(
            machine._arrow_pixels(fixture("scene")), _ARROW_PIXELS_MIN
        )
        self.assertEqual(0, machine._arrow_pixels(fixture("scene_without_arrow")))

    def test_the_complete_popup_wins_over_everything_it_covers(self):
        """「完成故事」是模态遮罩：不先点掉它，底下每条判据都会被压低。"""

        machine = SideStoryStateMachine(templates())

        self.assertEqual(
            "close_complete_popup",
            machine.next_action(fixture("complete_popup")).name,
        )

    def test_an_unrelated_screen_is_still_reported_as_unrecognized(self):
        machine = SideStoryStateMachine(templates())
        black = np.zeros((1132, 1982, 3), dtype=np.uint8)

        with self.assertRaisesRegex(UnrecognizedScreen, "支线故事画面"):
            machine.next_action(black)


class SideStoryContractTests(unittest.TestCase):
    """准入与契约：新建路线必须自己站住的那几道关。"""

    def test_every_side_action_carries_a_transition_contract(self):
        """这条路开了 `_REQUIRE_TRANSITION_CONTRACT` ⇒ 每个动作都要有出口验收。"""

        machine = SideStoryStateMachine(templates())
        seen = []
        for name in PERIOD:
            action = machine.next_action(fixture(name))
            if action is not None and action.name in SIDE_ACTIONS:
                seen.append(action)

        self.assertTrue(seen, "一条本路线动作都没发出来，这条断言等于没跑")
        self.assertEqual(
            set(SIDE_ACTIONS), {action.name for action in seen}
        )
        for action in seen:
            self.assertTrue(action.source_page, f"{action.name} 缺 source_page")
            self.assertTrue(action.target_pages, f"{action.name} 缺 target_pages")

    def test_the_runner_opens_the_transition_contract_switch(self):
        self.assertTrue(SideStoryRunner._REQUIRE_TRANSITION_CONTRACT)

    def test_the_route_is_registered_with_its_own_runner_and_no_cycle_picker(self):
        spec = MODE_SPECS["side_story"]

        self.assertIs(SideStoryRunner, spec.runner_type)
        self.assertEqual("支线故事", spec.label)
        self.assertEqual(StoryState.STAGE.value, spec.default_state)
        self.assertFalse(spec.cycles_editable)

    def test_the_navigation_is_the_same_first_hop_as_the_fodder_route(self):
        """复用优先：两支线共用大厅那个入口页 ⇒ 导航第一跳逐字相同。"""

        side = MODE_SPECS["side_story"].navigation_plan.steps
        fodder = MODE_SPECS["fodder"].navigation_plan.steps

        self.assertEqual(1, len(side))
        self.assertEqual(fodder[0].anchor, side[0].anchor)
        self.assertEqual(fodder[0].targets, side[0].targets)

    def test_the_machine_keeps_its_own_regions_and_thresholds_after_construction(self):
        """回归：主线 `__init__` 会把两张表换成**实例属性** ⇒ 少合并一次就 KeyError。"""

        machine = build_side_story_machine(TEMPLATES)

        for name in ("complete_popup", "replay", "battle_clear", "quick_entry"):
            self.assertIn(name, machine._REGIONS, f"{name} 的区域在构造后丢了")
            self.assertIn(name, machine._THRESHOLDS, f"{name} 的阈值在构造后丢了")


if __name__ == "__main__":
    unittest.main()
