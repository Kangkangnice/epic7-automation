from pathlib import Path
import unittest
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.games.epic7 import story as story_module
from auto_game_unified.games.epic7.story import (
    StoryState,
    StoryStateMachine,
    build_story_templates,
)
from auto_game_unified.games.epic7.template_paths import TemplateDir


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"
GLOBAL_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"


def load_fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class Epic7StoryStateMachineTests(unittest.TestCase):
    def test_battle_guide_warning_requires_title_and_dont_show_button(self):
        popup = load_fixture("battle_guide_warning_live_20260815")
        title = np.asarray(
            Image.open(TEMPLATES / "battle_guide_title.png").convert("RGB")
        )
        dont_show = np.asarray(
            Image.open(TEMPLATES / "battle_guide_dont_show.png").convert("RGB")
        )

        match = story_module.find_battle_guide_dont_show(
            popup, title, dont_show
        )
        without_title = popup.copy()
        without_title[250:430, 780:1200] = 0
        without_button = popup.copy()
        without_button[760:950, 1080:1500] = 0

        self.assertIsNotNone(match)
        self.assertTrue(1240 <= match.center[0] <= 1300)
        self.assertTrue(830 <= match.center[1] <= 880)
        self.assertIsNone(
            story_module.find_battle_guide_dont_show(
                without_title, title, dont_show
            )
        )
        self.assertIsNone(
            story_module.find_battle_guide_dont_show(
                without_button, title, dont_show
            )
        )
        for fixture in ("team", "battle_auto_on_live_20260809", "results"):
            with self.subTest(fixture=fixture):
                self.assertIsNone(
                    story_module.find_battle_guide_dont_show(
                        load_fixture(fixture), title, dont_show
                    )
                )

    def test_pc_backend_picks_up_battle_guide_pc_templates(self):
        """PC 真机上这层弹窗必须认得出（2026-11-07 主线卡在这一页）。

        共享模板（模拟器裁的）在 PC 帧上 title 只有 0.6681（阈 0.85）⇒ 双锚点整页
        返回 None ⇒ 战斗阶段只能干等，20 秒后「安全停止」。修法是
        ``templates/story/pc/battle_guide_{title,dont_show}.png`` 两张覆盖图。
        """
        popup = load_fixture("battle_guide_warning_pc_live_20261107")
        pc_templates = build_story_templates(TemplateDir(TEMPLATES, "pc"))

        match = story_module.find_battle_guide_dont_show(
            popup,
            pc_templates.battle_guide_title,
            pc_templates.battle_guide_dont_show,
        )
        self.assertIsNotNone(match)
        self.assertTrue(1240 <= match.center[0] <= 1310)
        self.assertTrue(825 <= match.center[1] <= 890)

        # 两锚点缺一不可：删掉任一区域都必须拒绝识别（与模拟器那套同一条纪律）。
        for region in ((780, 250, 420, 180), (1080, 760, 420, 190)):
            without_anchor = popup.copy()
            x, y, width, height = region
            without_anchor[y : y + height, x : x + width] = 0
            with self.subTest(region=region):
                self.assertIsNone(
                    story_module.find_battle_guide_dont_show(
                        without_anchor,
                        pc_templates.battle_guide_title,
                        pc_templates.battle_guide_dont_show,
                    )
                )

    def test_battle_adapter_exposes_battle_guide_dont_show_action(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        observation = machine.observe_battle(
            load_fixture("battle_guide_warning_live_20260815"), None
        )

        self.assertIsNotNone(observation.allowed_action)
        self.assertEqual(
            "dismiss-battle-guide-warning", observation.allowed_action[0]
        )
        self.assertTrue(1240 <= observation.allowed_action[1][0] <= 1300)
        self.assertTrue(830 <= observation.allowed_action[1][1] <= 880)
        self.assertFalse(observation.battle_visible)
        self.assertFalse(observation.result_visible)

    def test_battle_adapter_uses_background_independent_control_classifier(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        manual = machine.observe_battle(
            load_fixture("battle_auto_off_live_20260809"), None
        )
        auto = machine.observe_battle(
            load_fixture("battle_auto_on_live_20260809"), None
        )
        result = machine.observe_battle(load_fixture("results"), None)

        self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
        self.assertIsNotNone(manual.auto_point)
        self.assertEqual(AutoBattleState.AUTO, auto.auto_state)
        self.assertTrue(result.result_visible)

    def test_battle_adapter_reports_which_evidence_decided_auto_state(self):
        """排查「自动被反复关掉」时，日志里这一行必须说清到底是谁做的决定。"""
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        manual = machine.observe_battle(
            load_fixture("battle_auto_off_live_20260809"), None
        )
        auto = machine.observe_battle(
            load_fixture("battle_auto_on_live_20260809"), None
        )

        self.assertIn("布局=manual_controls", manual.auto_evidence)
        self.assertIn("来源=右上角自动关闭图标", manual.auto_evidence)
        self.assertIn("布局=auto_controls", auto.auto_evidence)
        self.assertNotIn("来源=", auto.auto_evidence)

    def test_auto_layout_is_not_overridden_by_a_stray_auto_off_icon(self):
        """布局=自动开着时，右上角图标擦线命中不许改判手动。

        2026-11-07 08:55 真机那场战斗的日志写的是
        「布局=auto_controls 自动关图标=0.8268 来源=右上角自动关闭图标」——
        四格底座全亮说明自动**确实开着**，却因为图标过了 0.80 就判手动、跑去点开关
        （同一分钟点了两次：08:55:08 / 08:55:14）。

        规则本身 2026-10-09 月塔事故后就定过：「图标只在布局看不出长相（transition）
        时才作数」，月塔 / 远征 / 竞技场三条都换成了 `resolve_auto_state`，
        **主线漏改**。这条用例把主线钉在同一条规则上。
        """
        machine = StoryStateMachine(build_story_templates(TEMPLATES), pc_rules=True)
        frame = load_fixture("battle_auto_on_live_20260809")

        # 伪造「图标擦线命中」：底下的布局仍是该帧真实的 auto_controls。
        real_locate = machine._locate

        def locate_with_stray_icon(screen, name):
            if name == "auto_off":
                return SimpleNamespace(score=0.8268, center=(1650, 90))
            return real_locate(screen, name)

        machine._locate = locate_with_stray_icon

        observation = machine.observe_battle(frame, None)

        self.assertEqual(AutoBattleState.AUTO, observation.auto_state)
        self.assertIsNone(observation.auto_point)
        self.assertIn("布局=auto_controls", observation.auto_evidence)
        self.assertIn("自动关图标=0.8268", observation.auto_evidence)
        # 日志里不该再说「是图标决定的」—— 那种说法正是旧写法留下的。
        self.assertNotIn("来源=右上角自动关闭图标", observation.auto_evidence)

    def test_battle_adapter_whitelists_post_start_story_actions(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        story = machine.observe_battle(load_fixture("story"), None)
        skip_confirm = machine.observe_battle(load_fixture("skip_confirm"), None)

        self.assertEqual("skip", story.allowed_action[0])
        self.assertEqual("skip_confirm", skip_confirm.allowed_action[0])

    def test_battle_adapter_recognizes_persisted_live_skip_confirmation(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        observation = machine.observe_battle(
            load_fixture("skip_confirm_persisted_live_20260813"), None
        )

        self.assertEqual("skip_confirm", observation.allowed_action[0])

    def test_friendship_points_popup_requires_title_and_close_anchor(self):
        popup = load_fixture("friendship_points_popup")
        title = np.asarray(
            Image.open(GLOBAL_TEMPLATES / "friendship_points_title.png").convert("RGB")
        )
        close = np.asarray(
            Image.open(GLOBAL_TEMPLATES / "friendship_points_close.png").convert("RGB")
        )
        without_title = popup.copy()
        without_title[150:330, 600:1400] = 0
        without_close = popup.copy()
        without_close[840:1030, 750:1200] = 0

        self.assertIsNotNone(
            story_module.find_friendship_points_popup_close(popup, title, close)
        )
        self.assertIsNone(
            story_module.find_friendship_points_popup_close(
                without_title, title, close
            )
        )
        self.assertIsNone(
            story_module.find_friendship_points_popup_close(
                without_close, title, close
            )
        )

    def test_lower_right_controls_distinguish_auto_manual_and_transition(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        self.assertEqual(
            story_module.BattleControls.AUTO_CONTROLS,
            machine.observe_battle_controls(
                load_fixture("battle_auto_on_live_20260809")
            ),
        )
        self.assertEqual(
            story_module.BattleControls.MANUAL_CONTROLS,
            machine.observe_battle_controls(
                load_fixture("battle_auto_off_live_20260809")
            ),
        )
        self.assertEqual(
            story_module.BattleControls.TRANSITION,
            machine.observe_battle_controls(
                np.zeros((1132, 1982, 3), dtype=np.uint8)
            ),
        )

    def test_manual_skill_variant_is_a_battle_and_requests_auto_enable(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        observation = machine.observe_battle(
            load_fixture("battle_manual_skill_variant_live_20260815"), None
        )

        self.assertTrue(observation.battle_visible)
        self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
        self.assertIsNotNone(observation.auto_point)

    def test_lower_right_control_classification_ignores_battle_background(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        auto = load_fixture("battle_auto_on_live_20260809")
        manual = load_fixture("battle_auto_off_live_20260809")
        gradient = np.zeros_like(auto)
        gradient[:, :, 0] = np.linspace(10, 170, auto.shape[1], dtype=np.uint8)
        gradient[:, :, 1] = np.linspace(160, 20, auto.shape[0], dtype=np.uint8)[:, None]
        gradient[:, :, 2] = 70

        yy, xx = np.ogrid[: auto.shape[0], : auto.shape[1]]
        auto_composite = gradient.copy()
        auto_mask = np.zeros(auto.shape[:2], dtype=bool)
        for center_x in (1505, 1623, 1740, 1858):
            auto_mask |= (xx - center_x) ** 2 + (yy - 1025) ** 2 <= 68 ** 2
            auto_mask |= (
                (xx >= center_x - 55)
                & (xx <= center_x + 55)
                & (yy >= 1025)
                & (yy < 1132)
            )
        auto_composite[auto_mask] = auto[auto_mask]

        manual_composite = gradient.copy()
        manual_mask = np.zeros(manual.shape[:2], dtype=bool)
        for center_x in (1534, 1683, 1834):
            manual_mask |= (xx - center_x) ** 2 + (yy - 1040) ** 2 <= 82 ** 2
        manual_composite[manual_mask] = manual[manual_mask]

        self.assertEqual(
            story_module.BattleControls.AUTO_CONTROLS,
            machine.observe_battle_controls(auto_composite),
        )
        self.assertEqual(
            story_module.BattleControls.MANUAL_CONTROLS,
            machine.observe_battle_controls(manual_composite),
        )

    def test_auto_controls_tolerate_one_portrait_obscured_by_battle_effect(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        screen = load_fixture("battle_auto_on_live_20260809").copy()
        screen[950:1058, 1440:1568] = [245, 245, 245]

        controls = machine.observe_battle_controls(screen)

        self.assertEqual(story_module.BattleControls.AUTO_CONTROLS, controls)

    def test_next_stage_variant_still_recognizes_prepare_battle(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("stage_variant"))

        self.assertEqual("prepare_battle", action.name)

    def test_prepare_battle_does_not_advance_until_target_is_committed(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("stage"))

        self.assertEqual("prepare_battle", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(StoryState.STAGE, action.source_state)
        self.assertEqual((StoryState.TEAM,), action.target_states)

        machine.commit(action, StoryState.TEAM)

        self.assertEqual(StoryState.TEAM, machine.state)

    def test_episode5_stage_recognizes_prepare_battle_without_background(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("stage_prepare_battle_ep5"))

        self.assertEqual("prepare_battle", action.name)

    def test_prepare_battle_glyph_does_not_match_other_bottom_right_actions(self):
        templates = build_story_templates(TEMPLATES)

        for name in ("story_watch_next_ep4", "assistant", "team", "results"):
            with self.subTest(name=name):
                match = story_module.find_prepare_battle_button(
                    load_fixture(name),
                    templates.prepare_battle,
                    templates.prepare_battle_updated,
                )
                self.assertIsNone(match)

    def test_optional_assistant_screen_selects_team_before_team_configuration(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        machine.next_action(load_fixture("stage_variant"))

        select_team = machine.next_action(load_fixture("assistant"))
        start_mission = machine.next_action(load_fixture("team"))

        self.assertEqual("select_team", select_team.name)
        self.assertEqual("start_mission", start_mission.name)

    def test_can_resume_directly_from_assistant_screen(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        select_team = machine.next_action(load_fixture("assistant"))
        start_mission = machine.next_action(load_fixture("team"))

        self.assertEqual("select_team", select_team.name)
        self.assertEqual("start_mission", start_mission.name)

    def test_current_live_assistant_and_team_pages_are_distinguished(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        select_team = machine.next_action(load_fixture("assistant_live_20260809"))
        start_mission = machine.next_action(load_fixture("team_live_20260809"))

        self.assertEqual("select_team", select_team.name)
        self.assertEqual("start_mission", start_mission.name)

    def test_team_page_survives_the_start_button_reskin(self):
        """2026-09-17 改版：按钮从橙底「进行任务」换成绿底「战斗开始」。

        旧模板在新画面上只有 0.36（门槛 0.80），实跑就卡在队伍准备页 46 秒后
        被超时恢复拖走。这条守住「换皮后的画面也必须认得出来」。
        """
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        start_mission = machine.next_action(load_fixture("team_live_20260917"))

        self.assertIsNotNone(start_mission)
        self.assertEqual("start_mission", start_mission.name)

    def test_both_start_button_skins_are_accepted(self):
        """两版皮肤都要认：加了新模板不能把老画面顶掉。"""
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        for name in ("team_live_20260809", "team_live_20260917"):
            with self.subTest(name=name):
                action = machine.next_action(load_fixture(name))
                self.assertIsNotNone(action)
                self.assertEqual("start_mission", action.name)

    def test_start_button_does_not_match_other_bottom_right_actions(self):
        templates = build_story_templates(TEMPLATES)

        for name in ("assistant_live_20260809", "stage_variant", "results"):
            with self.subTest(name=name):
                match = story_module.find_start_mission_button(
                    load_fixture(name),
                    templates.start_mission,
                    templates.start_mission_updated,
                    story_module.STORY_THRESHOLDS.get("start_mission", 0.80),
                    story_module.STORY_REGIONS["start_mission"],
                    story_module.STORY_REFERENCE_SIZE,
                )
                self.assertIsNone(match)

    def test_stamina_popup_selects_only_the_leaf_then_confirms_purchase(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        popup = load_fixture("stamina_popup_live_20260809")

        select_leaf = machine.next_action(popup)
        machine.action_clicked(select_leaf)
        confirm = machine.next_action(popup)

        self.assertEqual("stamina_material", select_leaf.name)
        self.assertLess(select_leaf.point[0], 960)
        self.assertEqual("stamina_confirm", confirm.name)

    def test_stamina_popup_after_start_is_handed_back_to_story_runner(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        observation = machine.observe_battle(
            load_fixture("stamina_popup_after_start_live_20260815"), None
        )

        self.assertTrue(observation.pre_battle_business_visible)
        self.assertIsNone(observation.allowed_action)

    def test_stamina_purchase_stops_if_the_selected_leaf_offer_is_not_visible(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        popup = load_fixture("stamina_popup_live_20260809")
        machine.action_clicked(machine.next_action(popup))
        without_leaf = popup.copy()
        without_leaf[480:730, 500:960] = 0

        with self.assertRaises(RuntimeError):
            machine.next_action(without_leaf)

    def test_stamina_purchase_count_waits_for_popup_to_leave_after_confirm_click(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        popup = load_fixture("stamina_popup_live_20260809")

        machine.action_clicked(machine.next_action(popup))
        confirm = machine.next_action(popup)
        machine.action_clicked(confirm)

        self.assertEqual(0, machine.stamina_replenished)
        machine.next_action(load_fixture("team"))
        self.assertEqual(1, machine.stamina_replenished)

    def test_story_background_variant_still_recognizes_skip(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("story_variant"))

        self.assertEqual("skip", action.name)

    def test_story_only_stage_starts_the_story(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("story_watch_ready_live_20260810"))

        self.assertEqual("watch_story", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)

    def test_episode4_story_next_stage_is_recognized_and_counts_previous_cycle(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_NEXT_STAGE,
        )

        action = machine.next_action(load_fixture("story_watch_next_ep4"))

        self.assertEqual("watch_story", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(1, machine.completed_cycles)

    def test_wait_complete_counts_cycle_when_next_battle_map_is_already_visible(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_COMPLETE,
        )

        action = machine.next_action(load_fixture("stage_prepare_battle_ep5"))

        self.assertIsNone(action)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(1, machine.completed_cycles)

    def test_wait_complete_counts_cycle_when_next_story_stage_is_already_visible(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_COMPLETE,
        )

        action = machine.next_action(load_fixture("story_watch_next_ep4"))

        self.assertEqual("watch_story", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(1, machine.completed_cycles)

    def test_episode4_story_stage_does_not_count_when_it_is_the_initial_page(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(load_fixture("story_watch_next_ep4"))

        self.assertEqual("watch_story", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_watch_story_glyph_does_not_match_other_bottom_right_actions(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        for name in [
            "stage_battle_ready_updated",
            "stage",
            "next_stage",
            "team",
            "results",
        ]:
            with self.subTest(name=name):
                self.assertIsNone(machine._locate(load_fixture(name), "watch_story"))
        self.assertIsNone(
            machine._locate(
                np.zeros((1132, 1982, 3), dtype=np.uint8), "watch_story"
            )
        )

    # ── 「重复打同一关」：点「重新进行」 ─────────────────────────────────────
    #
    # 2026-10-18 19:50 现场：结算确认点完，游戏给的是「无法前往下一个关卡，
    # 请选择下方按钮」，左下角「离开 / 大厅」、右下角「S 体力/上限 + 重新进行」。
    # 这一页原来一个锚点都没有 ⇒ 干等 45 秒 ⇒ 路线退出码 1。

    def test_the_replay_screen_is_clicked_instead_of_waiting_for_a_timeout(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_RESULTS
        )

        action = machine.next_action(load_fixture("retry_stage_live_20261018"))

        assert action is not None, "认不出这一页 ⇒ 又回到干等 45 秒"
        self.assertEqual("retry_stage", action.name)
        self.assertEqual(
            1, machine.completed_cycles, "这一屏 = 一局刚打完，必须记一轮"
        )
        # 必须落在右下角那颗：左下角是「离开 / 大厅」，点错就退出关卡了。
        self.assertTrue(
            1700 <= action.point[0] <= 1900,
            f"点到了左边（x={action.point[0]}）—— 那里是「离开 / 大厅」",
        )
        self.assertTrue(990 <= action.point[1] <= 1090)

    def test_the_replay_button_generalizes_to_another_stage(self):
        """10-14 那次是**另一关、另一套背景**，同一颗按钮必须照样认得出。

        只认 10-18 那一张就是「记住了一张图」，不是判据。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_RESULTS
        )

        action = machine.next_action(load_fixture("retry_stage_live_20261014"))

        assert action is not None
        self.assertEqual("retry_stage", action.name)

    def test_going_forward_always_wins_over_replaying(self):
        """两个都遇到时，先走「进行下一个关卡」—— 用户口径，不许反过来。

        这两个按钮在**同一个位置上**（右下角），所以造不出「同屏都有」的真实帧；
        这里用桩把**前进判据强行点亮**，验的是代码里的**优先级顺序**：
        只要 `complete` 命中，就绝不许落到 `retry_stage`。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_RESULTS
        )
        fake = story_module.Match((900, 500), 0.99)
        real_locate = machine._locate

        def locate(screen, name):
            if name in ("retry_stage", "complete"):
                return fake
            return real_locate(screen, name)

        machine._locate = locate

        action = machine.next_action(load_fixture("retry_stage_live_20261018"))

        assert action is not None
        self.assertEqual(
            "complete", action.name, "前进判据在的时候点了「重新进行」—— 优先级反了"
        )

    def test_a_failed_retry_click_does_not_count_the_cycle_twice(self):
        """点歪（尝试 2/4）时同一屏会再判一次，轮次不许跟着涨。

        涨了就直接吃满 max_cycles：用户要打 10 次，实际只打了 5 次就收工。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_RESULTS
        )
        frame = load_fixture("retry_stage_live_20261018")

        first = machine.next_action(frame)
        second = machine.next_action(frame)

        assert first is not None and second is not None
        self.assertEqual("retry_stage", second.name, "点歪之后必须能再点一次")
        self.assertEqual(1, machine.completed_cycles)

    def test_the_replay_glyph_does_not_match_other_screens(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        for name in [
            "stage",
            "stage_variant",
            "stage_battle_ready_updated",
            "stage_prepare_battle_ep5",
            "next_stage",
            "complete",
            "results",
            "reward",
            "clear",
            "team",
            "story",
            "bonus_reward",
        ]:
            with self.subTest(name=name):
                self.assertIsNone(machine._locate(load_fixture(name), "retry_stage"))

    def test_the_replay_threshold_sits_in_an_empty_gap(self):
        """门槛必须坐在空档里，而且两边都留得下余量。

        实测：两张正例 1.0000 / 0.9870；主线其余夹具最像的 0.5173。
        """
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        threshold = machine._THRESHOLDS["retry_stage"]

        positive = [
            machine._locate(load_fixture(name), "retry_stage")
            for name in ("retry_stage_live_20261018", "retry_stage_live_20261014")
        ]
        self.assertTrue(all(match is not None for match in positive))
        lowest_positive = min(match.score for match in positive if match is not None)

        highest_negative = 0.0
        for path in sorted(FIXTURES.glob("*.png")):
            if path.stem.startswith("retry_stage_live"):
                continue
            match = machine._locate(load_fixture(path.stem), "retry_stage")
            if match is not None:
                highest_negative = max(highest_negative, match.score)

        self.assertGreaterEqual(
            lowest_positive - threshold,
            0.10,
            "正例离门槛太近 —— 换个关卡就可能掉下去",
        )
        self.assertGreaterEqual(
            threshold - highest_negative,
            0.10,
            f"反例已经到 {highest_negative:.4f} —— 门槛没坐在空档里",
        )

    def test_resume_on_the_replay_screen_lands_on_the_retry_step(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        point = story_module.detect_resume_point(
            machine, load_fixture("retry_stage_live_20261018")
        )

        assert point is not None, "停在这一页启动，接力探针认不出来"
        self.assertEqual("重新进行", point.page)
        self.assertEqual(StoryState.WAIT_RESULTS, point.state)

    def test_skip_detection_ignores_the_changing_story_background(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.ACTIVE
        )
        story = load_fixture("story").copy()
        x, y, width, height = machine._scaled_region(story, "skip")
        area = story[y : y + height, x : x + width]
        hsv = cv2.cvtColor(area, cv2.COLOR_RGB2HSV)
        glyph = (hsv[:, :, 1] <= 70) & (hsv[:, :, 2] >= 120)
        area[~glyph] = [30, 180, 220]

        action = machine.next_action(story)

        self.assertEqual("skip", action.name)

    def test_desktop_contaminated_battle_frame_is_not_clicked(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.ACTIVE
        )

        controls = machine.observe_battle_controls(load_fixture("battle_variant"))

        self.assertEqual(story_module.BattleControls.TRANSITION, controls)

    def test_skill_animation_keeps_battle_present_while_controls_are_unknown(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.ACTIVE
        )

        observation = machine.observe_battle(
            load_fixture("skill_animation_live_20260813"), None
        )

        self.assertTrue(observation.frame_valid)
        self.assertEqual(AutoBattleState.UNKNOWN, observation.auto_state)
        self.assertTrue(observation.battle_visible)
        self.assertIsNone(observation.auto_point)

    def test_auto_off_click_is_not_treated_as_auto_enabled(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_BATTLE
        )

        action = machine.next_action(load_fixture("battle_auto_off_live_20260809"))

        self.assertEqual("enable_auto", action.name)
        self.assertFalse(machine.auto_enabled)

    def test_enable_auto_reports_the_plain_battle_page_name(self):
        """`enable_auto` 的 source_page 必须是「战斗中」，不许带修饰后缀。

        它经 `_action` → `_confirm_page(source_page)` **每帧**改写「当前已确认页面」，
        主循环再拿这个值比对上一个动作的 `target_pages`（`runner_base._transition_completed`）；
        对不上就把状态机刚给出的动作置 None —— 状态机彻底失声。

        2026-11-07 08:10 真机：这里原本写「战斗中（自动关闭）」，而
        `skip_confirm.target_pages` 里只有「战斗中」⇒ 两者对不上 ⇒ 转场永远不完成
        ⇒ `enable_auto` **一次都没发出去**（日志里完全没有这个动作）⇒ 干等到
        60 秒报「转场超时 动作=skip_confirm」，而截图里战斗早就开始了、只是自动没开。

        ⚠️ 期望值**独立写死**，不许读 `action.source_page` 自比（`topics/hazards.md`
        的「护栏别写空」）。「自动是关的」这条信息归 `reason`，不归页面名。

        ⚠️ 这条只在 **PC** 上成立：模拟器保留原名「战斗中（自动关闭）」，
        由 `test_simulator_keeps_the_legacy_auto_page_name` 钉住。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_BATTLE,
            pc_rules=True,
        )

        action = machine.next_action(load_fixture("battle_auto_off_live_20260809"))

        self.assertEqual("enable_auto", action.name)
        self.assertEqual("战斗中", action.source_page)
        self.assertIn(action.source_page, action.target_pages)
        # 也要能在「上一个动作」的目标名单里找到 —— 那才是它被采信的前提。
        skip_confirm = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_SKIP_CONFIRM,
            pc_rules=True,
        ).next_action(load_fixture("skip_confirm"))
        self.assertEqual("skip_confirm", skip_confirm.name)
        self.assertIn(action.source_page, skip_confirm.target_pages)

    def test_simulator_keeps_the_legacy_auto_page_name(self):
        """模拟器必须是原名 —— 这是「模拟器完全不动」的看门用例。

        2026-11-07 用户明确要求：所有改动只能落在 PC，模拟器一个字节都不许变。
        所以 `pc_rules` 默认 False，`enable_auto` 的 `source_page` 保持
        「战斗中（自动关闭）」（尽管它跟 `skip_confirm.target_pages` 对不上）。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_BATTLE
        )

        action = machine.next_action(load_fixture("battle_auto_off_live_20260809"))

        self.assertEqual("enable_auto", action.name)
        self.assertEqual("战斗中（自动关闭）", action.source_page)

    def test_simulator_keeps_trusting_the_auto_off_icon(self):
        """模拟器的自动战斗判定必须保持原样：图标命中即改判手动。

        这是 `resolve_auto_state` 只在 PC 生效的看门用例 —— 模拟器上哪怕布局
        明判「自动开着」，只要图标命中就仍然改判手动（旧行为，一字不改）。
        """
        machine = StoryStateMachine(build_story_templates(TEMPLATES))
        frame = load_fixture("battle_auto_on_live_20260809")

        real_locate = machine._locate

        def locate_with_stray_icon(screen, name):
            if name == "auto_off":
                return SimpleNamespace(score=0.8268, center=(1650, 90))
            return real_locate(screen, name)

        machine._locate = locate_with_stray_icon

        observation = machine.observe_battle(frame, None)

        self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
        self.assertIn("来源=右上角自动关闭图标", observation.auto_evidence)
        self.assertEqual((1650, 90), observation.auto_point)

    def test_auto_on_frame_confirms_enabled_without_another_click(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_BATTLE
        )

        action = machine.next_action(load_fixture("battle_auto_on_live_20260809"))

        self.assertIsNone(action)
        self.assertEqual(StoryState.ACTIVE, machine.state)
        self.assertTrue(machine.auto_enabled)

    def test_manual_controls_remain_an_enable_auto_candidate_until_confirmed(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_BATTLE
        )
        manual = load_fixture("battle_auto_off_live_20260809")

        first = machine.next_action(manual)
        second = machine.next_action(manual)

        self.assertEqual("enable_auto", first.name)
        self.assertEqual("enable_auto", second.name)

    def test_optional_bonus_reward_is_closed_before_next_stage_is_counted(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_NEXT_STAGE
        )

        close_reward = machine.next_action(load_fixture("bonus_reward"))
        machine.next_action(load_fixture("next_stage"))

        self.assertEqual("bonus_reward", close_reward.name)
        self.assertEqual((950, 887), close_reward.point)
        self.assertEqual(1, machine.completed_cycles)

    def test_recorded_stage_completes_with_one_auto_enable(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        actions = [
            machine.next_action(load_fixture("stage")),
            machine.next_action(load_fixture("team")),
            machine.next_action(load_fixture("story")),
            machine.next_action(load_fixture("skip_confirm")),
            machine.next_action(load_fixture("battle_auto_off_live_20260809")),
            machine.next_action(load_fixture("battle_auto_on_live_20260809")),
            machine.next_action(load_fixture("reward")),
            machine.next_action(load_fixture("clear")),
            machine.next_action(load_fixture("results")),
            machine.next_action(load_fixture("complete")),
            machine.next_action(load_fixture("next_stage")),
        ]

        self.assertEqual(
            [
                "prepare_battle",
                "start_mission",
                "skip",
                "skip_confirm",
                "enable_auto",
                "reward",
                "clear",
                "results_confirm",
                "complete",
            ],
            [action.name for action in actions if action is not None],
        )
        self.assertEqual(1, machine.completed_cycles)

    def test_mid_battle_story_is_skipped_without_toggling_auto_again(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        for name in [
            "stage", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
        ]:
            machine.next_action(load_fixture(name))
        skip = machine.next_action(load_fixture("story"))
        confirm = machine.next_action(load_fixture("skip_confirm"))
        resumed_battle = machine.next_action(load_fixture("battle_auto_on_live_20260809"))

        self.assertEqual("skip", skip.name)
        self.assertEqual("skip_confirm", confirm.name)
        self.assertIsNone(resumed_battle)

    def test_skip_confirmation_allows_the_next_story_segment_to_be_skipped(self):
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_SKIP_CONFIRM,
        )

        action = machine.next_action(load_fixture("skip_confirm"))

        self.assertEqual("skip_confirm", action.name)
        self.assertIn("剧情播放", action.target_pages)

    def test_skip_confirmation_may_end_the_story_on_the_clear_prompt(self):
        """跳过最后一段剧情后游戏直接给「通关提示」，不再回剧情播放。

        2026-09-18 两次实跑（14:14:07、14:47:46）都卡在这一步：转场契约里没有
        「通关提示」，于是干等 45 秒后整条路线以退出码 1 收场（证据包
        complete=0.996 / next_stage=0.954，其余模板全部未命中）。通关提示是正牌
        前进页，`complete` 动作专门处理它，必须算作 skip_confirm 的合法落点。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_SKIP_CONFIRM,
        )

        action = machine.next_action(load_fixture("skip_confirm"))

        self.assertEqual("skip_confirm", action.name)
        self.assertIn("通关提示", action.target_pages)
        self.assertIn(StoryState.WAIT_COMPLETE, action.target_states)

        endpoint = machine.next_action(load_fixture("complete"))

        self.assertEqual("complete", endpoint.name)
        self.assertEqual("通关提示", machine._confirmed_page)
        self.assertEqual(StoryState.WAIT_COMPLETE, machine.state)

    def test_skip_confirmation_may_end_the_story_on_the_results_page(self):
        """跳过**战后最后一段**剧情后，游戏直接给「结算确认」，不经过战斗中。

        2026-11-01 21:20 PC 实跑死在这（同一类契约漏落点的第五种形态）：
        点击 → 页面变「结算确认」→ 不在 ``target_pages`` 里 → 主循环判"没点成功"
        → 丢掉动作 → 干等 45 秒报 ``timeout_transition_skip_confirm`` → 收尾"回首页"
        在结算页连按 ESC 无效 → 退出码 1。
        证据包：``results_confirm=0.8600 observed=True``，其余锚点全部低于阈值。

        ⚠️ 症状（点了没反应 / 等 45 秒）看起来像判据问题，实际是契约少一个落点。
        分诊口诀：日志里 ``转场超时`` + ``当前已确认页面=X``，先去查上一个动作的
        ``target_pages`` 有没有 X。
        """
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES),
            initial_state=StoryState.WAIT_SKIP_CONFIRM,
        )

        action = machine.next_action(load_fixture("skip_confirm"))

        self.assertEqual("skip_confirm", action.name)
        self.assertIn("结算确认", action.target_pages)
        self.assertIn(StoryState.WAIT_RESULTS, action.target_states)

        # 落点真的能接着往下跑：结算确认页给出的下一动作是"确认"
        on_results = machine.next_action(load_fixture("results"))
        self.assertEqual("results_confirm", on_results.name)


    def test_results_actions_allow_a_post_battle_cutscene(self):
        """战果链上的三下点击都可能接一段**战后过场**，不是直接进战果。

        2026-11-01 22:55 实跑：点完「奖励结算」落到「剧情播放」，落点名单里没有它
        ⇒ 主循环判「没点成功」→ 丢掉动作 → 干等 45 秒 → 整轮失败。
        （同一类还撞过：跳过确认落到结算确认 / 通关结算，见上一条测试。）
        """
        for fixture, name in (
            ("reward", "reward"),
            ("clear", "clear"),
            ("results", "results_confirm"),
        ):
            with self.subTest(action=name):
                machine = StoryStateMachine(
                    build_story_templates(TEMPLATES),
                    initial_state=StoryState.WAIT_RESULTS,
                )
                action = machine.next_action(load_fixture(fixture))
                self.assertIsNotNone(action)
                self.assertEqual(name, action.name)
                self.assertIn("剧情播放", action.target_pages)


if __name__ == "__main__":
    unittest.main()
