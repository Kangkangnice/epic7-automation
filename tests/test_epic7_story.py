from pathlib import Path
import unittest

import cv2
import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.games.epic7 import story as story_module
from auto_game_unified.games.epic7.story import StoryState, StoryStateMachine, build_story_templates


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


if __name__ == "__main__":
    unittest.main()
