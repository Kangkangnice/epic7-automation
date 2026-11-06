"""主线在 PC 客户端上的判据护栏（2026-11-01 移植）。

为什么这条测试用 ``_locate``（内部方法）而不是模块级函数：主线的每颗判据都走
``StoryStateMachine._locate`` 分派（白掩膜 / 双模板择优 / 缩放区域都在里面），
只有调它才是**与实跑同一把尺**。测试要问的是「这一帧上这颗锚点到底认不认得出」，
用别的入口量出来的分数不能作数。
"""

import dataclasses
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.global_popups import (
    find_friend_request_cancel,
    load_friend_request_templates,
)
from auto_game_unified.games.epic7.story import (
    StageTooHard,
    StoryState,
    StoryStateMachine,
    build_story_templates,
    detect_resume_point,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.template_paths import TemplateDir

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
# PC 帧单独放 ``*_pc`` 目录（2026-11-04 P4 起）：``FIXTURES`` 是模拟器基线，
# 混进 PC 帧会撞「全库排他性」那类护栏，只能靠放宽门槛过测试。
PC_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story_pc"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def load_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


def load_pc_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(PC_FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class Epic7StoryPcTests(unittest.TestCase):
    def setUp(self):
        self.machine = StoryStateMachine(
            build_story_templates(TemplateDir(TEMPLATES, "pc"))
        )

    def test_pc_stage_page_is_recognized_by_shared_templates(self):
        """PC 真机「关卡入口」帧：准备战斗按钮必须过阈（实测 1.0000 / 0.9997）。

        这条是本路线**不需要补 PC 专属图**的证据：按钮判据是白掩膜找形状，
        与背景无关，所以同一个客户端换了渲染方式也照认。

        ⚠️ 这条测的是**共享（模拟器）模板**能不能认 PC 帧（名字就写着 shared），
        所以必须用 emulator 后端建模板，不能跟 ``setUp`` 那台 PC 机器混用：
        2026-11-04 另一次真机修复给 ``prepare_battle_updated`` 补了 PC 覆盖图
        （针对**更新后的 PC 客户端**渲染），它在这张 11-01 的旧 PC 帧上反而不过阈
        （共享图 1.0000 / PC 覆盖图 None）。夹具比客户端旧，不是判据退化。
        """
        frame = load_fixture("stage_pc_live_20261101")
        shared_machine = StoryStateMachine(
            build_story_templates(TemplateDir(TEMPLATES, "emulator"))
        )

        match = shared_machine._locate(frame, "prepare_battle")

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score, 0.90)
        # 落点必须压在右下角那颗按钮上，不是画面别处
        self.assertTrue(1600 <= match.center[0] <= 1900)
        self.assertTrue(980 <= match.center[1] <= 1120)

    def test_pc_stage_page_does_not_trigger_later_pages(self):
        """反例方向：关卡入口这一帧上，后续页面的锚点一律不得命中。

        「准备战斗」认出来就够把页面判成关卡入口；若结算/通关/重试那几颗也命中，
        状态机会在关卡入口直接点走，链路就串页了。
        """
        frame = load_fixture("stage_pc_live_20261101")

        for name in (
            "results_confirm",
            "clear",
            "complete",
            "retry_stage",
            "skip_confirm",
            "watch_story",
        ):
            with self.subTest(atom=name):
                self.assertIsNone(self.machine._locate(frame, name))

    def test_pc_stamina_popup_is_fully_actionable(self):
        """PC 上「行动力不足」弹窗必须三件套都认得出，否则路线会空转到超时。

        2026-11-01 21:23 实跑就是这样：弹窗只认出素材（0.9997），标题差一点
        （0.7623 < 0.80）⇒ `next_stamina_decision` 判成"没有弹窗"⇒ 回头继续点
        「战斗开始」⇒ 连点 4 次、干等到用户手动停。

        两处根因、两种修法（都在设计内）：
        1. 标题：PC 把同一句话渲染得略大（白字 bbox 229x45 对模板 221x43）
           ⇒ `templates/story/pc/stamina_popup.png` 覆盖图（代码零改动）；
        2. 购买按钮：这版弹窗改成**三颗按钮**（取消/购买/礼包），购买被挤到
           x=807~1105，旧搜索框从 850 起摆不下模板 ⇒ 搜索框左扩到 760。
        """
        frame = load_fixture("stamina_popup_pc_live_20261101")

        for name in ("stamina_popup", "stamina_material", "stamina_confirm"):
            with self.subTest(atom=name):
                match = self.machine._locate(frame, name)
                self.assertIsNotNone(match, name)
                self.assertGreaterEqual(match.score, 0.80, name)

        # 购买按钮必须落在真正的按钮上（不是礼包、不是取消）
        confirm = self.machine._locate(frame, "stamina_confirm")
        self.assertTrue(880 <= confirm.center[0] <= 1030, confirm.center)
        self.assertTrue(820 <= confirm.center[1] <= 930, confirm.center)

    def test_pc_story_page_does_not_trigger_the_stamina_popup(self):
        """反例：关卡入口那一帧上，体力三件套一律不得命中。"""
        frame = load_fixture("stage_pc_live_20261101")

        for name in ("stamina_popup", "stamina_material", "stamina_confirm"):
            with self.subTest(atom=name):
                self.assertIsNone(self.machine._locate(frame, name))

    def test_pc_friend_request_popup_is_recognized(self):
        """战后「给予协助的朋友」弹窗：PC 上标题差一点，整个弹窗就关不掉。

        2026-11-01 21:21 那次超时的现场帧其实是**结算页 + 好友申请弹窗**：
        标题 0.6084（阈 0.82，PC 把同一句标题渲染得略大：白字 328×45 / 模板 314×44）
        ⇒ `find_friend_request_cancel` 要求标题与取消**同时**命中 ⇒ 守卫不认 ⇒
        弹窗一直压着，收尾"回首页"按 ESC 也照样无效。
        """
        frame = load_fixture("friend_request_pc_live_20261101")
        pc_templates = load_friend_request_templates(TemplateDir(TEMPLATES, "pc"))
        emulator_templates = load_friend_request_templates(
            TemplateDir(TEMPLATES, "emulator")
        )

        match = find_friend_request_cancel(
            frame, pc_templates.title, pc_templates.cancel
        )

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score, 0.82)
        # 点的是「取消」，不是「申请」
        self.assertTrue(760 <= match.center[0] <= 840, match.center)
        # 模拟器口径仍然解析到共享模板 —— 那份判据必须一个字都不变
        self.assertIsNone(
            find_friend_request_cancel(
                frame, emulator_templates.title, emulator_templates.cancel
            )
        )

    def test_pc_overrides_are_only_what_the_pc_really_needs(self):
        """PC 覆盖图只允许放**真的认不出 / 真的点不动**的那几张，加一张就得回来改这条。

        判据类（都是「PC 把同一句中文渲染得略大 / 按钮换了皮」）：
        - `stamina_popup`（行动力不足）；
        - `friend_request_title`（给予协助的朋友）；
        - `complete`（「完成故事」弹窗 —— PC 上 0.7996 / 阈 0.80，差 0.0004
          ⇒ 主线 5 次卡在「等待结算」45 秒超时）；
        - `prepare_battle_updated`（2026-11-04 另一次真机修复，针对更新后的 PC
          客户端按钮渲染；共享图在 11-01 旧帧上仍 1.0000，见上面的用例说明）。
        - `prepare_battle`（2026-11-06 活动剧情的战斗关进的是**另一种**「准备战斗」
          版面：主线 `select_team` / `prepare_battle` / `prepare_battle_updated`
          三套判据全不认，整条路线在「等待结算」上超时。共用图不能动（模拟器
          行为零改动），所以只给 PC 补一张同尺寸覆盖图，走
          ``find_prepare_battle_button`` 的双候选 + 白掩膜，实跑帧 1.0000；
          主线仍由 `prepare_battle_updated` 兜底，两条路互不干扰）。

        点击目标类（不参与判据，只决定点哪）：
        - `complete_close`（2026-11-04 P4：「完成故事」弹窗底部「点击关闭」标签，
          PC 上 ``complete`` 模板中心落在奖励图标、点了没反应，连点 4 次不推进）。

        主线其余判据全是白掩膜 / 几何，PC 上本来就过阈 —— 不许顺手加图。
        """
        overrides = {path.name for path in (TEMPLATES / "pc").glob("*.png")}
        self.assertEqual(
            {
                "stamina_popup.png",
                "friend_request_title.png",
                "complete.png",
                "prepare_battle_updated.png",
                "prepare_battle_updated_alt.png",
                "prepare_battle.png",
                "complete_close.png",
            },
            overrides,
        )

    def test_pc_complete_popup_clicks_the_close_label_not_the_title(self):
        """P4 回归（2026-11-04 每日任务实跑）：主线走到通关提示，``complete`` 判据
        **过了**（证据包 0.8236 > 0.80），但 ``操作=complete 坐标=(1001,395)`` 连点 4 次
        「来源页面=通关提示仍在」，最后 ``四次点击未转场``，整条路线 ✗。

        定性：**不是识别问题，是点击点问题**。``complete`` 模板裁的是弹窗标题+奖励区
        （537×254），中心 (1001,395) 落在奖励图标上；PC 客户端的「完成故事」弹窗要
        点底部「点击关闭」才关得掉（实测中心 (965,770)）。

        修法：新增 ``templates/story/pc/complete_close.png``（只裁「点击关闭」4 个字，
        150×50），``_action_point`` 在 ``complete`` 且命中该标签时返回标签中心；
        标签**只决定点哪，不参与判据**，判据仍只看 ``complete`` 文案。
        该 PC 帧上标签实测 1.0000 @ (965,770)。不许调阈值、不许改目标连续次数。
        """
        frame = load_pc_fixture("complete_popup_live_20261104")

        action = self.machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("complete", action.name)
        # 「点击关闭」实测中心 (965, 770)；给 ±12 余量，别把一次重采样写死。
        self.assertAlmostEqual(965, action.point[0], delta=12)
        self.assertAlmostEqual(770, action.point[1], delta=12)
        # 反向：绝不能还是标题中心 —— 那就是这次报错的原样行为。
        self.assertNotEqual((1001, 395), tuple(action.point))

    def test_without_the_pc_close_template_the_old_point_is_kept(self):
        """对称回归：拿掉 ``complete_close``（模拟器口径 / 找不到按钮）时**原样回落**
        ``match.center`` = (1001,395)，模拟器行为一个字都不改。

        这条钉住 P4 最容易犯的错：把点击点改动做成无条件覆盖，把模拟器也带偏。
        """
        frame = load_pc_fixture("complete_popup_live_20261104")
        templates = dataclasses.replace(self.machine.templates, complete_close=None)
        machine = StoryStateMachine(templates)

        action = machine.next_action(frame)

        self.assertIsNotNone(action)
        self.assertEqual("complete", action.name)
        self.assertEqual((1001, 395), tuple(action.point))

    def test_wait_complete_recognizes_stage_entry_on_both_pc_renderings(self):
        """P4 续（2026-11-04 14:53 实跑）：点掉「完成故事」弹窗后回到关卡详情页，
        程序在「等待通关」状态下连续 45 秒认不出这一页，最后安全停止、主线记 ✗。

        定性：`_locate("prepare_battle")` 走白掩膜，PC 的两套按钮渲染都只有
        **0.8515**（阈 0.90）⇒ 状态机 WAIT_COMPLETE 分支的三个前进判据全落空。
        补第二张 PC 候选图后同一把尺子量出 **1.0000**，直接落回「关卡入口」。
        这里用真状态机跑 WAIT_COMPLETE：按既有设计，通关后回到关卡入口是
        **记一轮收工、不发动作**（`next_action` 返回 None、`completed_cycles` +1、
        状态拨回 STAGE），所以断言的是这三者，而不是「返回一个动作」。
        """
        cases = (
            ("story_ready_pc_20261104_142538", load_pc_fixture),
            ("story_ready_pc_20261104_015956", load_pc_fixture),
            # 14:53:49 真机超时那一帧（点掉「完成故事」弹窗后回到关卡详情页）。
            # 当时 evidence.json 里 ``prepare_battle_updated`` 只有 0.8926，
            # 45 秒后报「主线画面[等待通关]未识别」；补的第二套渲染候选在
            # 这一帧上是 1.0000，而旧图仍是 None。
            ("wait_complete_after_close_pc_20261104", load_pc_fixture),
            ("stage_pc_live_20261101", load_fixture),
        )
        for name, loader in cases:
            with self.subTest(frame=name):
                machine = StoryStateMachine(
                    build_story_templates(TemplateDir(TEMPLATES, "pc"))
                )
                machine.state = StoryState.WAIT_COMPLETE

                action = machine.next_action(loader(name))

                self.assertIsNone(action, name)
                self.assertEqual(1, machine.completed_cycles, name)
                self.assertEqual(StoryState.STAGE, machine.state, name)


class StoryBattleFailedTests(unittest.TestCase):
    """2026-11-06 17:15 主线第 13 轮打输：把「打不过」报成 ``battle_unrecognized``。

    现场帧是 FAILED 战败结算页（欧勒毕斯指南 / 离开 / 大厅 / 继续战斗 / 重新进行）。
    ``battle_scene_visible`` 为 False、``reward/clear/results_confirm`` 三选一全 None
    ⇒ 战斗监督五项观察全假 ⇒ 干等 45 秒安全停止，主线记 ✗。

    修法抄月塔 2026-11-01 的 ``FloorTooHard``：**复用** ``tower/battle_failed.png``
    （同一套 FAILED UI，白掩膜），不另存第二份图、不碰共享模板。四处接线：
    监督 ``result_visible``、状态机 ``next_action``、开局接力 ``detect_resume_point``、
    以及 PC-only 的模板加载。模拟器载不到图 ⇒ 四处全部原样。

    ⚠️ 真机证据：17:15:51 那轮 ``battle_unrecognized`` 之后收尾 ESC → 快捷菜单 →
    酒馆 → 大厅成功（17:16:08「异常收尾=已回到首页」），所以改成正常收工不会
    中断整条每日任务链。
    """

    def setUp(self):
        self.pc_machine = StoryStateMachine(
            build_story_templates(TemplateDir(TEMPLATES, "pc"))
        )
        self.emulator_machine = StoryStateMachine(
            build_story_templates(TemplateDir(TEMPLATES, "emulator"))
        )
        self.frame = load_pc_fixture("story_failed_pc_live_20261106")

    def test_the_failed_page_is_visible_to_the_battle_supervisor_on_pc(self):
        hit = self.pc_machine._battle_failed(self.frame)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.88)
        observation = self.pc_machine.observe_battle(self.frame, None)
        self.assertTrue(observation.result_visible)
        self.assertFalse(observation.battle_visible)

    def test_the_failed_page_stops_cleanly_instead_of_timing_out(self):
        with self.assertRaises(StageTooHard) as caught:
            self.pc_machine.next_action(self.frame)
        self.assertIn("打不过", str(caught.exception))
        self.assertEqual("主线这一关打不过", StageTooHard.stop_label)

    def test_the_failed_page_is_an_opening_resume_point(self):
        point = detect_resume_point(self.pc_machine, self.frame)
        self.assertIsNotNone(point)
        self.assertEqual("战斗失败结算", point.page)
        self.assertEqual(StoryState.WAIT_RESULTS, point.state)

    def test_the_emulator_behaviour_is_byte_for_byte_unchanged(self):
        self.assertIsNone(self.emulator_machine.templates.battle_failed)
        self.assertIsNone(self.emulator_machine._battle_failed(self.frame))
        observation = self.emulator_machine.observe_battle(self.frame, None)
        self.assertFalse(observation.result_visible)
        with self.assertRaises(UnrecognizedScreen):
            self.emulator_machine.next_action(self.frame)
        self.assertIsNone(
            detect_resume_point(self.emulator_machine, self.frame)
        )

    def test_real_battle_frames_never_trigger_the_failed_conclusion(self):
        """反向：真战斗 / 技能演出帧上一律不许宣布「打不过」。

        误收手的代价是战斗中途被切走，比漏判严重得多。全库 386 张夹具
        反例最高 0.2748、主线 38 张战斗/诊断帧除正例外最高 0.1888（阈 0.88）。
        """
        for name in (
            "battle",
            "battle_auto_off_live_20260809",
            "battle_auto_on_live_20260809",
            "battle_auto_skill_cooldown_live_20260818",
            "battle_guide_warning_live_20260815",
            "battle_manual_skill_variant_live_20260815",
            "battle_variant",
            "skill_animation_live_20260813",
            "stage_battle_ready_updated",
        ):
            with self.subTest(frame=name):
                self.assertIsNone(
                    self.pc_machine._battle_failed(load_fixture(name)), name
                )


if __name__ == "__main__":
    unittest.main()
