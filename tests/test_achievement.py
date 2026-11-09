# -*- coding: utf-8 -*-
"""成就领取路线（PC 端首条）的判据与决策护栏。

## 这组测试守什么

1. **弹窗优先于整页** —— 奖励弹窗是半透明遮罩，底下成就页元素实测仍有
   0.9999 / 0.9987。顺序反了就会对着被盖住的按钮点。
2. **「全部领取」的亮/灰靠颜色比例，不靠模板** —— 两态形状相同、互相命中 0.96~1.00。
3. **领取优先于效果升级** —— 用户口径「先把所有红点领完，再看效果升级」。
4. **4 个分类全无角标就是收工**，且只记一轮。

夹具全部是 2026-11-08 本机真机帧（识别画布 1982x1132），放在 ``*_pc`` 目录下。
"""

from pathlib import Path
import unittest
from unittest import mock

import numpy as np

from auto_game_unified.games.epic7.achievement import (
    AchievementState,
    AchievementStateMachine,
    build_achievement_templates,
    detect_achievement_resume_point,
)
from auto_game_unified.games.epic7.evidence.achievement import (
    CLAIM_ALL_GREEN_MIN,
    CLASS_COUNT,
    claim_all_green_ratio,
    class_dots,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_achievement_pc"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def load(name: str) -> np.ndarray:
    """读一张整屏夹具。

    ⚠️ 刻意走 ``cv2.imdecode`` 而不是 ``Image.open`` / ``cv2.imread``：
    ``tests/conftest.py`` 把那两个函数换成了 40 张封顶的 lru_cache（每张 6.7MB，
    两通道合计约 0.5GB）。这条路线有 7 张整屏帧，全占缓存位会把全量测试的内存
    峰值往上顶一截 —— 实测 2026-11-08 单进程全量跑到 20%（多线程的 worker 用例）
    时 GC 在子线程里崩过一次。``imdecode`` 不经过那层缓存，用完即可回收。
    """
    import cv2

    data = (PC_FIXTURES / f"{name}.png").read_bytes()
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return image[:1132, :1982]


class AchievementMachineTests(unittest.TestCase):
    def setUp(self):
        self.machine = AchievementStateMachine(
            build_achievement_templates(TemplateDir(TEMPLATES, "pc"))
        )

    # -- 页面身份 ---------------------------------------------------------
    def test_the_reward_popup_wins_over_the_page_it_covers(self):
        """弹窗帧必须判成弹窗，不能判成成就页（遮罩太薄，整页元素照样高分）。"""
        frame = load("reward_popup_pc_live_20261108")
        self.assertIs(self.machine.observe_page(frame), AchievementState.REWARD_POPUP)

    def test_the_effect_popup_is_told_apart_from_the_reward_popup(self):
        """两个弹窗都有「点击关闭」，但位置差 148px —— 必须各认各的。"""
        frame = load("effect_popup_pc_live_20261108")
        self.assertIs(self.machine.observe_page(frame), AchievementState.EFFECT_POPUP)

    def test_the_plain_page_is_recognised(self):
        frame = load("page_alive_pc_live_20261108")
        self.assertIs(self.machine.observe_page(frame), AchievementState.PAGE)

    def test_an_unknown_frame_fails_closed(self):
        """全黑帧不许产生任何点击。"""
        blank = np.zeros((1132, 1982, 3), dtype=np.uint8)
        self.assertIsNone(self.machine.observe_page(blank))
        with self.assertRaises(UnrecognizedScreen):
            self.machine.next_action(blank)

    # -- 动作 -------------------------------------------------------------
    def test_claim_all_when_the_button_is_green(self):
        frame = load("page_alive_pc_live_20261108")
        action = self.machine.next_action(frame)
        self.assertEqual("claim-all", action.name)
        self.assertIn("成就页", action.source_page)
        # 点的是那颗按钮，不是画面别处
        self.assertTrue(1600 <= action.point[0] <= 1800)
        self.assertTrue(1000 <= action.point[1] <= 1110)

    def test_claiming_comes_before_the_effect_upgrade(self):
        """这一帧上「全部领取」绿 + 「持续效果上升」都在 ⇒ 必须先领取。

        用户口径：「我们就把所有的有红点的都点完，然后呢，把它全部都领取完」，
        领完才轮到看效果升级。
        """
        frame = load("page_effect_button_pc_live_20261108")
        action = self.machine.next_action(frame)
        self.assertEqual("claim-all", action.name)

    def test_switch_class_when_nothing_is_claimable(self):
        """灰态那帧：本分类领完了，但别的分类还挂着角标 ⇒ 切过去。"""
        frame = load("page_grey_pc_live_20261108")
        self.assertLess(claim_all_green_ratio(frame), CLAIM_ALL_GREEN_MIN)
        action = self.machine.next_action(frame)
        self.assertEqual("switch-class", action.name)
        self.assertIn(action.point, [(91, 220), (91, 340), (91, 460), (91, 580)])

    def test_popup_close_points_differ_between_the_two_popups(self):
        reward = self.machine.next_action(load("reward_popup_pc_live_20261108"))
        effect_machine = AchievementStateMachine(
            build_achievement_templates(TemplateDir(TEMPLATES, "pc"))
        )
        effect = effect_machine.next_action(load("effect_popup_pc_live_20261108"))
        self.assertEqual("close-reward-popup", reward.name)
        self.assertEqual("close-effect-popup", effect.name)
        self.assertNotEqual(reward.point, effect.point)

    def test_story_pages_reuse_the_main_story_judgement(self):
        story = self.machine.next_action(load("story_pc_live_20261108"))
        self.assertEqual("skip-story", story.name)
        confirm_machine = AchievementStateMachine(
            build_achievement_templates(TemplateDir(TEMPLATES, "pc"))
        )
        confirm = confirm_machine.next_action(load("story_confirm_pc_live_20261108"))
        self.assertEqual("confirm-skip-story", confirm.name)

    # -- 收工 -------------------------------------------------------------
    def test_done_requires_all_four_classes_confirmed(self):
        """收工判据 = 4 个分类**逐个走进去看过**，不是「左边没有角标红点」。

        2026-11-08 实跑教训：红点只表示「这个分类有新达成的成就」，
        **不代表「没有奖励可领」**。现场帧 `page_alive_pc_live_20261108` 就是反例：
        当前分类图标上没有红点，但右下「全部领取」是亮的、列表四条都写着「领取」。
        所以这一帧即使把角标全抹掉（dots={}），也不许一帧就收工 —— 必须把 4 个分类
        逐个确认「全部领取灰 + 没有升级按钮」才允许 DONE。
        """
        frame = load("page_grey_pc_live_20261108")
        actions = []
        with mock.patch(
            "auto_game_unified.games.epic7.achievement.class_dots", return_value={}
        ):
            for step in range(40):
                # ⚠️ 每帧必须不一样：状态机对**同一帧**是幂等的（主循环等转场时会
                # 重复问，重复问不能推进进度）。真实场景里切分类后画面会变，
                # 这里改一个角落像素来模拟「画面变了」。
                tick = frame.copy()
                tick[0, 0, 0] = step % 256
                tick[1, 1, 1] = step % 256
                action = self.machine.next_action(tick)
                if action is None:
                    break
                actions.append(action.name)
        self.assertIs(self.machine.state, AchievementState.DONE)
        self.assertEqual(1, self.machine.completed_cycles)
        # 每切一次进一个分类；第 4 个进去那一帧直接收工（不再产生动作）
        # ⇒ 4 - 1 = 3 次动作。判据是「进去过」而不是「确认没东西」，
        # 因为主循环在等转场时会重复问决策，「确认」口径会被一帧记满（23:12 实跑打脸）。
        self.assertEqual(3, len(actions))

    def test_a_lit_claim_all_wins_over_missing_class_dots(self):
        """「全部领取」亮着就一定要领，哪怕左边一个红点都没有。

        现场帧 ``page_alive_pc_live_20261108`` 就是这个状态：当前分类图标上没有
        红点，但按钮亮着、列表四条都写着「领取」。旧实现只在「有红点」时才理会
        这个分类，正是这一帧说明了红点与「有没有奖励可领」不是一回事。
        """
        frame = load("page_alive_pc_live_20261108")
        with mock.patch(
            "auto_game_unified.games.epic7.achievement.class_dots", return_value={}
        ):
            action = self.machine.next_action(frame)
        self.assertEqual("claim-all", action.name)

    def test_no_dots_does_not_mean_done_on_the_very_first_frame(self):
        """反向护栏：一帧「没有角标」绝不允许直接宣布收工。

        这条钉的是 2026-11-08 那次「领了一半就打勾」的现场 ——
        旧实现在这一帧直接返回 None + completed_cycles=1。
        """
        frame = load("page_grey_pc_live_20261108")
        with mock.patch(
            "auto_game_unified.games.epic7.achievement.class_dots", return_value={}
        ):
            action = self.machine.next_action(frame)
        self.assertIsNotNone(action)
        self.assertIsNot(self.machine.state, AchievementState.DONE)
        self.assertEqual(0, self.machine.completed_cycles)

    def test_preview_never_advances_business_progress(self):
        """preview 是「试算」：算完必须把进度原样还回去。"""
        frame = load("page_grey_pc_live_20261108")
        with mock.patch(
            "auto_game_unified.games.epic7.achievement.class_dots", return_value={}
        ):
            action, _snapshot = self.machine.preview(frame)
        self.assertIsNotNone(action)
        self.assertEqual(0, self.machine.completed_cycles)
        self.assertIsNot(self.machine.state, AchievementState.DONE)
        # 业务计数器也要还原，否则每帧试算都会推进「已进入」进度
        self.assertEqual({0}, self.machine._visited)
        self.assertEqual(0, self.machine._current_class)

    def test_switching_is_bounded(self):
        """角标一直在但既不能领也不能升级时，最终要收敛到收工，不许无限切下去。"""
        frame = load("page_grey_pc_live_20261108")
        dots = {0: (41, 190), 1: (41, 310)}
        with mock.patch(
            "auto_game_unified.games.epic7.achievement.class_dots", return_value=dots
        ):
            for step in range(60):
                tick = frame.copy()
                tick[0, 0, 0] = step % 256
                tick[1, 1, 1] = step % 256
                if self.machine.next_action(tick) is None:
                    break
            else:
                self.fail("60 帧内没有收敛到收工")
        self.assertIs(self.machine.state, AchievementState.DONE)
        self.assertEqual(1, self.machine.completed_cycles)


class AchievementEvidenceTests(unittest.TestCase):
    def test_the_four_class_dots_are_read_from_the_real_frame(self):
        """分类 2/3/4 挂着角标、分类 1 没有 —— 与实机观察一致。"""
        frame = load("page_alive_pc_live_20261108")
        self.assertEqual({1, 2, 3}, set(class_dots(frame)))
        self.assertEqual(CLASS_COUNT, 4)

    def test_the_popup_frames_have_no_dots(self):
        """弹窗压暗整屏后角标读不到 —— 弹窗优先判定，所以不影响决策。"""
        self.assertEqual({}, class_dots(load("reward_popup_pc_live_20261108")))
        self.assertEqual({}, class_dots(load("effect_popup_pc_live_20261108")))

    def test_green_ratio_splits_alive_from_grey(self):
        """亮态 ≈0.26、灰态 0.00 —— 阈值 0.10 两侧都有余量。"""
        alive = claim_all_green_ratio(load("page_alive_pc_live_20261108"))
        grey = claim_all_green_ratio(load("page_grey_pc_live_20261108"))
        self.assertGreaterEqual(alive, 0.20)
        self.assertLessEqual(grey, 0.02)
        self.assertGreater(alive - CLAIM_ALL_GREEN_MIN, 0.09)
        self.assertGreater(CLAIM_ALL_GREEN_MIN - grey, 0.09)


class AchievementPlatformTests(unittest.TestCase):
    def test_both_platforms_have_their_own_templates_now(self):
        """2026-11-09 模拟器侧补齐后，两边都能装配（此前是「模拟器必须炸」）。

        这条原来断言 ``FileNotFoundError`` —— 当时只有 PC 素材。现在方向反过来：
        它保护的是**共享层那 5 张模拟器图别被删掉**，删了模拟器这条路线就跑不了。
        """
        emulator = build_achievement_templates(TemplateDir(TEMPLATES, "emulator"))
        pc = build_achievement_templates(TemplateDir(TEMPLATES, "pc"))

        self.assertIsNotNone(emulator)
        self.assertIsNotNone(pc)

    def test_the_two_platforms_do_not_share_the_same_pictures(self):
        """共享层必须是模拟器图、``pc/`` 下是 PC 图 —— 两边不许互相顶替。

        实测：同一个「成就」标题，模拟器版 124x60、PC 版 100x52；
        模拟器版打在模拟器帧上 1.0000、打在 PC 帧上会掉分，反之亦然。
        """
        emulator = build_achievement_templates(TemplateDir(TEMPLATES, "emulator"))
        pc = build_achievement_templates(TemplateDir(TEMPLATES, "pc"))

        self.assertNotEqual(emulator.page_title.shape, pc.page_title.shape)
        self.assertNotEqual(emulator.claim_all.shape, pc.claim_all.shape)


class AchievementNavigationTests(unittest.TestCase):
    """导航链与开局接力（2026-11-08 加：「从大厅自己走到成就页」）。

    ⚠️ 这里只用离线帧，不碰真机 —— 导航链的正确性靠 ``test_navigation_plans.py``
    那套通用护栏 + 本文件这两条「成就页认得出 / 接力落点对不对」。
    """

    def setUp(self):
        self.machine = AchievementStateMachine(
            build_achievement_templates(TemplateDir(TEMPLATES, "pc"))
        )

    def _navigator(self):
        import types

        from auto_game_unified.games.epic7.navigation import (
            Epic7Navigator,
            build_navigation_templates,
        )

        root = TemplateDir(TEMPLATES, "pc")
        return Epic7Navigator(
            build_navigation_templates(root),
            runtime=types.SimpleNamespace(now=lambda: 0.0),
            template_root=root,
        )

    def test_the_navigator_recognises_the_achievement_page(self):
        """导航器必须把成就页认出来，否则「进成就」这一步永远验收不通过。"""
        navigator = self._navigator()
        for fixture in (
            "page_alive_pc_live_20261108",
            "page_grey_pc_live_20261108",
            "page_effect_button_pc_live_20261108",
        ):
            with self.subTest(fixture=fixture):
                observation = navigator.observe(load(fixture))
                self.assertEqual("achievement", observation.name)
                self.assertGreaterEqual(observation.confidence, 0.90)

    def test_the_navigator_still_reads_the_pages_it_used_to(self):
        """加了成就页身份之后，快捷菜单与大厅的判定不许被挤掉。"""
        navigator = self._navigator()
        self.assertEqual(
            "quick_menu", navigator.observe(load("quick_menu_pc_live_20261108")).name
        )
        self.assertEqual(
            "lobby", navigator.observe(load("lobby_pc_live_20261108")).name
        )

    def test_resuming_on_the_page_hands_back_the_navigation_entry(self):
        """停在成就页：落点要带上 ``entry``，导航才能省掉「回大厅再走一遍」。"""
        point = detect_achievement_resume_point(
            self.machine, load("page_alive_pc_live_20261108")
        )
        self.assertIsNotNone(point)
        self.assertEqual("成就页", point.page)
        self.assertEqual("achievement", point.entry)

    def test_resuming_on_a_popup_takes_over_without_an_entry(self):
        """停在弹窗上：就地接管，但它不在导航链上，所以不给 ``entry``。"""
        for fixture in (
            "reward_popup_pc_live_20261108",
            "effect_popup_pc_live_20261108",
        ):
            with self.subTest(fixture=fixture):
                point = detect_achievement_resume_point(self.machine, load(fixture))
                self.assertIsNotNone(point)
                self.assertIsNone(point.entry)

    def test_an_unrelated_page_is_not_resumed(self):
        """认不出的帧不许被当成接力点（否则会从半路开始乱点）。"""
        blank = np.zeros((1132, 1982, 3), dtype=np.uint8)
        self.assertIsNone(detect_achievement_resume_point(self.machine, blank))


if __name__ == "__main__":
    unittest.main()
