# -*- coding: utf-8 -*-
"""骑士团捐赠在 PC 客户端上的判据护栏（2026-11-08 修）。

## 这一组测试守的是哪一次事故

2026-11-08 10:26 每日任务连打，骑士团捐赠这一步报
``页面无进展：骑士团捐赠画面[骑士团活动·资源支援]未识别``，整批以退出码 1 结束。

真因不在「弹窗没打开」，而在**模板把会变的数字焊进了图里**：
``pc/flower_cell.png`` / ``pc/flower_cell_selected.png`` 采图那天那格是「363」，
11-08 现场那格是「1321」⇒ 原样比只有 **0.8426**（阈 0.88）⇒
``request_popup`` 页面组合（``popup_title`` + 花朵格子任一态）不成立 ⇒
``observe_page`` 返回 None ⇒ ``UnrecognizedScreen``。

修法：把两张 PC 图各裁到高 130（数字行去掉，花朵 / 绿勾 / 金框都还在），判据与阈值一字未改。

## 为什么用 ``_locate`` 而不是模块级函数

和 ``test_epic7_story_pc.py`` 同一个理由：``_locate`` 分派了白掩膜 / 低通兜底 / 缩放，
只有调它才是**与实跑同一把尺**。测试要回答的是「这一帧上这颗判据到底认不认得出」。
"""

from pathlib import Path
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified.core.matcher import find_template
from auto_game_unified.games.epic7.global_popups import (
    find_reward_notice_close,
    load_reward_notice_templates,
)
from auto_game_unified.games.epic7.knights_donation import (
    KnightsDonationState,
    KnightsDonationStateMachine,
)
from auto_game_unified.games.epic7.knights_support_digits import RowNumbers
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation"
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation_pc"
GLOBAL_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_global"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "knights_donation"
GLOBAL_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"


def load_pc_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(PC_FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


def load_global_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(GLOBAL_FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class KnightsDonationPcTests(unittest.TestCase):
    """PC 版花朵格判据：正例要够高、反例要够低、页面要认得出。"""

    def setUp(self):
        self.machine = KnightsDonationStateMachine(
            TemplateDir(TEMPLATES, "pc")
        )

    def test_the_request_popup_frame_is_recognised_at_all(self):
        """11-08 的故障帧：必须先能判成「请求支援弹窗」。

        这是那次事故最直接的回归护栏 —— 这条断言红，说明整条路线会在同一步
        重新崩成 ``UnrecognizedScreen``。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        self.assertIs(
            self.machine.observe_page(frame),
            KnightsDonationState.REQUEST_POPUP,
        )

    def test_the_flower_cell_anchor_survives_a_different_holding_count(self):
        """花朵格正例：那格写的是 1321（模板采的是 363），仍须高分命中。

        ⚠️ 这条断言就是「模板不含会变内容」这条纪律的落地检查：
        数字一进模板，这张图上只有 0.8426。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        match = self.machine._locate(frame, "flower_cell")

        self.assertIsNotNone(match)
        # 纪律门槛：正例 ≥ 0.94
        self.assertGreaterEqual(match.score, 0.94)
        # 落点必须压在花朵那一格里，不能跑到画面上别处
        x, y, width, height = self.machine.templates.evidence.atom("flower_cell").region
        self.assertTrue(x <= match.center[0] <= x + width)
        self.assertTrue(y <= match.center[1] <= y + height)

    def test_the_selected_state_does_not_fire_on_an_unselected_cell(self):
        """花朵格反例：这一格**没被选中**，选中态判据必须冷着。

        纪律门槛：反例 ≤ 0.70。它红了意味着「没选中也会被当成选中」，
        那一步就会跳过选花、直接按下确认 —— 请求出去的就不是下级精灵之花。
        """
        frame = load_pc_fixture("request_popup_pc_live_20261108")
        match = self.machine._locate(frame, "flower_cell_selected")

        self.assertIsNone(match)
        # 「不过阈」还不够 —— 要量出真实分数，确认间隔是**分数**给的，不是阈值擦边。
        atom = self.machine.templates.evidence.atom("flower_cell_selected")
        scored = find_template(
            frame,
            self.machine.templates.flower_cell_selected,
            0.0,
            region=atom.region,
            reference_size=atom.reference_size,
        )
        self.assertIsNotNone(scored)
        self.assertLessEqual(scored.score, 0.70)

    def test_the_template_no_longer_carries_the_holding_count(self):
        """结构性护栏：花朵格模板不得再包住下面那行数字。

        原图 184 高，底部约 30~54 行是「持有数量」——**每天都不一样**。
        裁到 130 后数字行落在模板之外。谁要是重新采一张带数字的图进来，
        高度会立刻超过这里的上限，测试当场变红。
        """
        for name in ("flower_cell", "flower_cell_selected"):
            with self.subTest(template=name):
                image = Image.open(TEMPLATES / "pc" / f"{name}.png")
                self.assertLessEqual(
                    image.size[1],
                    140,
                    f"pc/{name}.png 高 {image.size[1]}，已经把会变的数字行包回来了",
                )

    def test_the_resource_support_page_never_reads_as_the_popup(self):
        """反例方向：资源支援页那一帧上，花朵格判据不得命中。

        两者背景相近（弹窗是压在这张列表页上的）。若列表页也能命中花朵格，
        程序会在列表页上点一下「选花」——那个坐标上是别人的行。
        """
        frame = load_pc_fixture("resource_support_pc_live_20261102")

        self.assertIs(
            self.machine.observe_page(frame),
            KnightsDonationState.RESOURCE_SUPPORT,
        )
        self.assertIsNone(self.machine._locate(frame, "flower_cell"))
        self.assertIsNone(self.machine._locate(frame, "flower_cell_selected"))


    def test_a_member_whose_holding_count_is_unreadable_is_still_supported(self):
        """别人那一行「持有」读不出时**必须照旧去点**，不能当成自己那一行跳过。

        2026-11-08 21:12 实跑事故：PC 分支拿「持有读不出」当「本人行」的代理，
        结果把别人要的材料一起跳过了 —— 日志写「没有可支援的成员」，
        用户看到的是「别人要什么我并没有给」。

        真正的本人行判据是「按钮上没有『支援 N 个』」⇒ ``required is None``。
        这一帧三个候选都是别人行（持有 2 / 需求 2），下面把第一行伪造成
        「本人行」（需求也读不出）、后两行伪造成「持有读不出」，
        正确行为是跳过第一行、点第二行。
        """
        frame = load_pc_fixture("resource_support_pc_live_20261102")

        def fake_numbers(_screen, center):
            if center[1] < 600:  # 最上面那一行 = 自己（「本人」按钮，需求读不出）
                return RowNumbers(None, None)
            return RowNumbers(None, 2)  # 别人的行：只有「持有」读不出

        with mock.patch.object(
            self.machine, "_row_numbers", side_effect=fake_numbers
        ):
            action = self.machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("support-one", action.name)
        self.assertGreaterEqual(action.point[1], 600)

    def test_a_whole_screen_of_unreadable_numbers_falls_back_to_clicking(self):
        """整屏都读不出 ⇒ 退回「照旧点」，不许把能支援的人全跳掉。

        字模整体失效时（换字体、换分辨率），一条判据都立不住；
        这时宁可点一次看结果，也不能判定「没人需要支援」直接收工。
        """
        frame = load_pc_fixture("resource_support_pc_live_20261102")

        with mock.patch.object(
            self.machine, "_row_numbers", return_value=RowNumbers(None, None)
        ):
            action = self.machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("support-one", action.name)


class KnightsRewardNoticeGuardTests(unittest.TestCase):
    """2026-11-08 23:23 实跑回归：支援成功的「获得奖励」层不再被全局守卫抢关。

    ## 用户看到的症状

    「别人要什么，我并没有给」。现场帧 ``runtime_logs/_knights_live.png`` 里
    七黑之牙、七月十九两行仍是**绿色「支援1个」**（持有 1,887，材料充足），
    而日志里程序对着 ``(1680, 939)`` 连点 4 次后判定「支援这一节收工」，
    直接跳去每周任务。右上角今日支援上限才 ``30/200``，远没到顶。

    ## 真因：全局守卫把状态机的目标页点掉了

    23:23:37 第一次 ``support-one`` 其实**生效了**：23:23:41 日志出现
    ``执行点击 动作=dismiss-reward-notice 坐标=(960, 843)`` —— 那就是支援成功后
    弹出的「获得奖励」层，被全局守卫抢在状态机前面关掉。于是
    ``support-one`` 的 ``target_pages=(支援资源确认框, 获得奖励弹窗)``
    **一帧都没成立过** ⇒ 主循环按「原页面仍存在且目标页面未出现」用旧坐标重试 4 次
    ⇒ ``_on_action_exhausted`` 置上 ``support_closed`` ⇒ 整节支援收工。
    列表重排后本该走的 ``_at_reward_popup``（清跳过表、清零下滑账本）一次都没跑到。

    这和 ``hero_synthesis`` 2026-11-06 的事故是同一个：模拟器没有这组 PC 专属
    「获得奖励」全局守卫模板，PC 上多出来的守卫**改了业务逻辑**。
    关掉它 = 恢复模拟器语义，符合「PC 端不改业务逻辑」这条原则。
    """

    @staticmethod
    def reward_frame() -> np.ndarray:
        return load_global_fixture("reward_notice_pc_live_20261101")

    def test_the_guard_and_the_route_recognise_the_same_popup(self):
        """因果证据：同一张 PC 真帧上两把尺都满分命中 ⇒ 守卫必然抢先。

        实测：骑士团 ``reward_title`` **0.99999 @(960,302)**，全局守卫关闭按钮
        **1.0000 @(960,843)**（正是日志里 ``dismiss-reward-notice`` 的坐标）。
        这条断言红了，说明两把尺不再指向同一个控件，修复的前提就不成立了。
        """
        frame = self.reward_frame()
        machine = KnightsDonationStateMachine(TemplateDir(TEMPLATES, "pc"))
        self.assertIs(
            machine.observe_page(frame),
            KnightsDonationState.REWARD_POPUP,
        )

        templates = load_reward_notice_templates(TemplateDir(GLOBAL_TEMPLATES, "pc"))
        self.assertIsNotNone(templates)
        close = find_reward_notice_close(frame, templates)
        self.assertIsNotNone(close)
        self.assertGreaterEqual(close.score, 0.90)

    def test_reward_notice_guard_is_disabled_for_knights_donation(self):
        """骑士团必须自己结算支援奖励，不许守卫代劳。"""
        self.assertFalse(get_mode("knights_donation").reward_notice_guard)

    def test_hero_synthesis_guard_is_still_disabled(self):
        """同类修复不能被顺手改回去（两种模式共用同一个开关字段）。"""
        self.assertFalse(get_mode("hero_synthesis").reward_notice_guard)

    def test_other_modes_keep_the_guard(self):
        """护栏：只关该关的两条路线，别把守卫全局撤掉。"""
        for name in ("shop_refresh", "achievement", "arena"):
            with self.subTest(mode=name):
                self.assertTrue(get_mode(name).reward_notice_guard)


if __name__ == "__main__":
    unittest.main()
