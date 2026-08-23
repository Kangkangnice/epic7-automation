"""英雄合成模式：页面判定、动作决策、安全护栏与完整流程测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np
from auto_game_unified.core.matcher import Match
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation
from auto_game_unified.games.epic7.hero_synthesis import (
    FilterObservation,
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    UnrecognizedScreen,
    build_hero_templates,
    state_label,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS, get_mode
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)
from auto_game_unified.games.epic7.runner_base import NOT_STABLE


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_hero"
NAV_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str):
    return cv2.cvtColor(
        cv2.imread(str(FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
    )


def machine(verify_filter: bool = False) -> HeroSynthStateMachine:
    m = HeroSynthStateMachine(build_hero_templates(TEMPLATES))
    m.filter_verified = verify_filter
    return m


def settled_next(m: HeroSynthStateMachine, screen):
    """模拟动画稳定：连续两次签名相同才返回动作；首次返回 None 用于首帧记录。"""
    first = m.next_action(screen)
    if first is not None:
        return first
    return m.next_action(screen)


def imprint_one_remaining_after_add():
    """一张材料已入槽、右侧还剩一张 Up 的过渡画面。"""
    screen = fixture("imprint_up_cards_no_sss").copy()
    added = fixture("imprint_added")
    x, y, w, h = HeroSynthStateMachine._IMPRINT_SLOT_ZONES[0]
    screen[y : y + h, x : x + w] = added[y : y + h, x : x + w]
    x, y, w, h = HeroSynthStateMachine._IMPRINT_COST_ZONE
    screen[y : y + h, x : x + w] = added[y : y + h, x : x + w]
    screen[530:650, 1370:1465] = 0
    return screen


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class TemplateTests(unittest.TestCase):
    def test_all_templates_load(self):
        templates = build_hero_templates(TEMPLATES)
        for name in (
            "filter_button",
            "filter_level_label",
            "filter_star3_selected",
            "imprint_normal",
            "imprint_grey",
            "auto_select_label",
            "story_back",
            "sss_material",
        ):
            self.assertIsNotNone(getattr(templates, name))
        self.assertIsNotNone(templates.imprint_result_title)
        self.assertIsNotNone(templates.imprint_result_close)

    def test_sss_templates_use_tight_user_crops_and_strict_rating_threshold(self):
        templates = build_hero_templates(TEMPLATES)
        self.assertEqual((90, 124), templates.rating_sss.shape[:2])
        self.assertEqual((38, 64), templates.sss_material.shape[:2])
        machine_value = HeroSynthStateMachine(templates)
        self.assertGreaterEqual(machine_value._RATING_SSS_MIN, 0.90)
        self.assertEqual(0.80, machine_value._SSS_MATERIAL_MIN)

    def test_filter_templates_are_tight_control_only_crops(self):
        templates = build_hero_templates(TEMPLATES)
        self.assertEqual((48, 90), templates.filter_attribute_label.shape[:2])
        self.assertEqual((72, 76), templates.filter_star3_selected.shape[:2])
        self.assertEqual((72, 76), templates.filter_star3_unselected.shape[:2])

    def test_selected_and_unselected_templates_do_not_cross_match(self):
        m = machine()
        selected = fixture("filter_open")
        unselected = fixture("filter_open_star3_unselected")

        self.assertIsNotNone(m._locate(selected, "filter_star3_selected", 0.90))
        self.assertIsNone(m._locate(selected, "filter_star3_unselected", 0.90))
        self.assertIsNotNone(
            m._locate(unselected, "filter_star3_unselected", 0.90)
        )
        self.assertIsNone(m._locate(unselected, "filter_star3_selected", 0.90))


class FilterObservationTests(unittest.TestCase):
    def test_closed_hero_list_requires_list_anchors_and_no_panel_anchors(self):
        m = machine()
        self.assertIs(
            FilterObservation.HERO_LIST_FILTER_CLOSED,
            m._observe_filter(fixture("list_unfiltered")),
        )

    def test_real_selected_panel_is_selected(self):
        m = machine()
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            m._observe_filter(fixture("filter_open")),
        )

    def test_real_unselected_panel_is_unselected(self):
        m = machine()
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
            m._observe_filter(fixture("filter_open_star3_unselected")),
        )

    def test_scaled_selected_panel_preserves_selected_state(self):
        m = machine()
        screen = cv2.resize(
            fixture("filter_open"), (991, 566), interpolation=cv2.INTER_AREA
        )
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            m._observe_filter(screen),
        )

    def test_scaled_unselected_panel_preserves_unselected_state(self):
        m = machine()
        screen = cv2.resize(
            fixture("filter_open_star3_unselected"),
            (991, 566),
            interpolation=cv2.INTER_AREA,
        )
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
            m._observe_filter(screen),
        )

    def test_panel_missing_either_permanent_anchor_is_unknown(self):
        m = machine()
        for anchor in ("filter_level_label", "filter_attribute_label"):
            with self.subTest(anchor=anchor):
                screen = fixture("filter_open_star3_unselected").copy()
                x, y, w, h = m._REGIONS[anchor]
                screen[y : y + h, x : x + w] = 0
                self.assertIs(FilterObservation.UNKNOWN, m._observe_filter(screen))

    def test_only_filter_fixtures_are_classified_as_open_panel(self):
        m = machine()
        open_observations = {
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
        }
        expected = {"filter_open.png", "filter_open_star3_unselected.png"}
        actual = {
            path.name
            for path in FIXTURES.glob("*.png")
            if m._observe_filter(fixture(path.stem)) in open_observations
        }
        self.assertEqual(expected, actual)

    def test_only_scaled_filter_fixtures_are_classified_as_open_panel(self):
        m = machine()
        open_observations = {
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
        }
        expected = {"filter_open.png", "filter_open_star3_unselected.png"}
        actual = {
            path.name
            for path in FIXTURES.glob("*.png")
            if m._observe_filter(
                cv2.resize(
                    fixture(path.stem), (991, 566), interpolation=cv2.INTER_AREA
                )
            )
            in open_observations
        }
        self.assertEqual(expected, actual)


class HeroListDecisionTests(unittest.TestCase):
    def test_red_dot_zone_matches_tight_user_marked_region(self):
        m = machine()
        self.assertEqual((1030, 942, 32, 35), m._REDDOT_ZONE)

    def test_red_dot_ignores_unrelated_orange_pixels_in_navigation_screens(self):
        m = machine()
        for name in ("lobby", "story_stage"):
            screen = cv2.cvtColor(
                cv2.imread(str(NAV_FIXTURES / f"{name}.png")), cv2.COLOR_BGR2RGB
            )
            self.assertFalse(m._red_dot_present(screen), name)

    def test_red_dot_survives_brown_character_background(self):
        m = machine()
        screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
        screen[942:977, 1030:1062] = (116, 92, 72)
        cv2.circle(screen, (1047, 959), 9, (219, 85, 11), -1)
        self.assertTrue(m._red_dot_present(screen))

    def test_list_first_visit_opens_filter(self):
        m = machine()
        action = m.next_action(fixture("list_reddot"))
        self.assertEqual("open_filter", action.name)
        self.assertEqual((1540, 191), action.point)

    def test_list_reddot_opens_imprint(self):
        m = machine(verify_filter=True)
        action = m.next_action(fixture("list_reddot"))
        self.assertEqual("open_imprint", action.name)
        self.assertLess(abs(action.point[0] - 1098), 8)
        self.assertLess(abs(action.point[1] - 995), 8)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_list_no_reddot_advances(self):
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_no_reddot"))
        self.assertTrue(action.name.startswith("next_card"))
        self.assertEqual((1559, 591), action.point)

    def test_list_no_reddot_with_live_button_score_advances(self):
        """模拟器按钮轻微变体得分 0.537 时仍应按无红点卡跳过。"""
        m = machine(verify_filter=True)
        low_score = Match(center=(1098, 995), score=0.537)
        with patch.object(m, "_locate_button", return_value=low_score):
            action = m.next_action(fixture("list_no_reddot"))
        self.assertTrue(action.name.startswith("next_card"))

    def test_list_grey_3s_advances_and_sets_guard(self):
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_grey_3s"))
        self.assertTrue(action.name.startswith("next_card"))
        self.assertTrue(m.prev_card_grey)

    def test_list_grey_3s_with_red_dot_advances(self):
        """3S 灰钮带红点（有冗余副本）也必须识别为置灰并跳过。"""
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_grey_3s_reddot"))
        self.assertTrue(action.name.startswith("next_card"))
        self.assertTrue(m.prev_card_grey)

    def test_list_grey_3s_light_shade_advances(self):
        """3S 浅亮灰钮（与深暗灰深浅不同）也必须识别为置灰并跳过。"""
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_grey_3s_light"))
        self.assertTrue(action.name.startswith("next_card"))
        self.assertTrue(m.prev_card_grey)

    def test_list_reddot_with_sub_max_rating_opens_imprint(self):
        """非满级 + 红点 → 进入刻印合成（无论上一张是什么）。"""
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_reddot"))
        self.assertEqual("open_imprint", action.name)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_list_max_rating_with_reddot_still_skips(self):
        """满级 SSS + 红点（兄弟副本）也必须跳过，浪费材料。"""
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_grey_3s_reddot"))
        self.assertTrue(action.name.startswith("next_card"))

    def test_end_of_cards_completes_cycle(self):
        m = machine(verify_filter=True)
        first = fixture("list_end_of_cards").copy()
        first[350:650, 150:700] = 0
        self.assertIsNone(m.next_action(first))
        self.assertIsNone(m.next_action(fixture("list_end_of_cards")))
        self.assertEqual(0, m.completed_cycles)
        self.assertIsNone(m.next_action(fixture("list_end_of_cards")))
        self.assertEqual(1, m.completed_cycles)
        self.assertFalse(m.filter_verified)


class FilterDecisionTests(unittest.TestCase):
    def test_filter_open_with_star3_selected_closes(self):
        m = machine()
        action = m.next_action(fixture("filter_open"))
        self.assertEqual("close_filter", action.name)
        self.assertEqual((1540, 191), action.point)
        self.assertFalse(m.filter_verified)

    def test_filter_open_without_selection_selects_star3(self):
        m = machine()
        action = m.next_action(fixture("filter_open_star3_unselected"))
        self.assertEqual("select_star3", action.name)
        self.assertEqual((1110, 636), action.point)
        self.assertFalse(m.filter_verified)

    def test_open_filter_keeps_same_action_when_click_is_swallowed(self):
        m = machine()
        first = m.next_action(fixture("list_unfiltered"))
        second = m.next_action(fixture("list_unfiltered"))
        self.assertEqual("open_filter", first.name)
        self.assertEqual("open_filter", second.name)
        self.assertFalse(m.filter_verified)

    def test_partial_panel_after_open_waits_without_another_action(self):
        m = machine()
        action = m.next_action(fixture("list_unfiltered"))
        partial = fixture("filter_open_star3_unselected").copy()
        x, y, w, h = m._REGIONS["filter_attribute_label"]
        partial[y : y + h, x : x + w] = 0

        self.assertEqual("open_filter", action.name)
        self.assertIs(m.state, HeroSynthState.FILTER)
        self.assertIsNone(m.next_action(partial))
        self.assertFalse(m.filter_verified)

    def test_select_star3_keeps_same_action_when_click_is_swallowed(self):
        m = machine()
        first = m.next_action(fixture("filter_open_star3_unselected"))
        second = m.next_action(fixture("filter_open_star3_unselected"))
        self.assertEqual("select_star3", first.name)
        self.assertEqual("select_star3", second.name)
        self.assertFalse(m.filter_verified)

    def test_close_filter_keeps_same_action_when_click_is_swallowed(self):
        m = machine()
        first = m.next_action(fixture("filter_open"))
        second = m.next_action(fixture("filter_open"))
        self.assertEqual("close_filter", first.name)
        self.assertEqual("close_filter", second.name)
        self.assertFalse(m.filter_verified)

    def test_filter_is_committed_only_after_closed_list_target_is_seen(self):
        m = machine()
        m.next_action(fixture("filter_open"))

        preview, outcome = m.preview(fixture("list_unfiltered"))

        self.assertIsNone(preview)
        self.assertIs(outcome[0], HeroSynthState.HERO_LIST)
        self.assertFalse(m.filter_verified)
        committed = m.next_action(fixture("list_unfiltered"))
        self.assertIsNone(committed)
        self.assertTrue(m.filter_verified)


class ImprintDecisionTests(unittest.TestCase):
    def test_imprint_loading_frame_waits_without_falling_back_to_list(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        loading = np.zeros_like(fixture("imprint_added"))

        self.assertIsNone(m.next_action(loading))
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_imprint_empty_materials_need_consecutive_confirmation(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_added")

        self.assertIsNone(m.next_action(screen))
        action = m.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("start_synthesis", action.name)

    def test_imprint_button_without_material_slots_never_starts_synthesis(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        loading = fixture("imprint_added").copy()
        for x, y, w, h in m._IMPRINT_SLOT_ZONES:
            loading[y : y + h, x : x + w] = 0

        self.assertIsNone(m.next_action(loading))
        self.assertIsNone(m.next_action(loading))
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_up_badge_still_locates_card_when_right_edge_is_covered(self):
        """角色立绘遮住卡片最右边时，仍应根据左侧 Up! 标记点材料。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        x, y, w, h = m._UP_STRIP_ZONE
        screen[y : y + h, x : x + w] = 0

        action = m.next_action(screen)

        self.assertIsNotNone(action)
        self.assertTrue(action.name.startswith("add_material"))

    def test_empty_slots_and_zero_cost_never_start_synthesis(self):
        """即使漏掉 Up!，没有材料入槽、费用仍为 0 时也必须一直等待。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        screen[390:990, 1370:1465] = 0
        x, y, w, h = m._UP_STRIP_ZONE
        screen[y : y + h, x : x + w] = 0

        for _ in range(3):
            self.assertIsNone(m.next_action(screen))
            self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_sss_material_aborts_imprint_before_clicking_material(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        action = m.next_action(fixture("imprint_sss_material"))
        self.assertEqual("abort_imprint_to_transmit", action.name)

    def test_pending_transmit_opens_transmit_for_current_card(self):
        m = machine(verify_filter=True)
        m.pending_transmit_target = True
        action = m.next_action(fixture("list_reddot"))
        self.assertEqual("open_transmit_for_current_card", action.name)
        self.assertEqual((1735, 1060), action.point)

    def test_sss_material_branch_enters_existing_transmit_flow(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        m.next_action(fixture("imprint_sss_material"))
        self.assertTrue(m.pending_transmit_target)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ABORTING)
        self.assertIsNone(m.next_action(fixture("imprint_up_cards_no_sss")))
        self.assertEqual(
            "open_transmit_for_current_card",
            m.next_action(fixture("list_reddot")).name,
        )
        self.assertEqual("start_transmit", m.next_action(fixture("transmit_select")).name)
        self.assertFalse(m.pending_transmit_target)

    def test_preview_restores_pending_transmit_context(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        action, _ = m.preview(fixture("imprint_sss_material"))
        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)
        self.assertFalse(m.pending_transmit_target)

    def test_imprint_with_up_cards_adds_topmost(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        action = m.next_action(fixture("imprint_up_cards_no_sss"))
        self.assertTrue(action.name.startswith("add_material"))
        self.assertEqual(1710, action.point[0])
        self.assertLess(abs(action.point[1] - 451), 15)

    def test_imprint_without_up_starts_synthesis(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        self.assertIsNone(m.next_action(fixture("imprint_added")))
        action = m.next_action(fixture("imprint_added"))
        self.assertEqual("start_synthesis", action.name)
        self.assertEqual((1149, 1078), action.point)
        self.assertIs(m.state, HeroSynthState.IMPRINT_CONFIRM)

    def test_imprint_after_synth_backs_to_list(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_REWARD
        action = m.next_action(fixture("imprint_after_synth"))
        self.assertEqual("back_to_list", action.name)
        self.assertLess(abs(action.point[0] - 30), 20)
        self.assertLess(abs(action.point[1] - 92), 20)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

    def test_imprint_result_state_backs_to_list_after_popup_is_closed(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_REWARD
        action = m.next_action(fixture("imprint_after_synth"))
        self.assertEqual("back_to_list", action.name)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

    def test_incomplete_result_popup_never_clicks_underlying_back_arrow(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_CONFIRM
        screen = fixture("imprint_result_popup").copy()
        screen[180:480, 650:1350] = 0
        screen[1020:1110, 900:1400] = fixture("imprint_added")[1020:1110, 900:1400]
        with self.assertRaises(UnrecognizedScreen):
            m.next_action(screen)

    def test_synth_confirm_popup_clicked(self):
        m = machine()
        action = m.next_action(fixture("synth_confirm"))
        self.assertEqual("confirm_synthesis", action.name)
        self.assertLess(abs(action.point[0] - 1121), 15)
        self.assertLess(abs(action.point[1] - 775), 20)
        self.assertIs(m.state, HeroSynthState.IMPRINT_CONFIRM)

    def test_imprint_result_popup_closes_before_returning_to_list(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_CONFIRM
        action = m.next_action(fixture("imprint_result_popup"))
        self.assertEqual("close_imprint_result", action.name)
        self.assertLess(abs(action.point[0] - 991), 20)
        self.assertLess(abs(action.point[1] - 850), 20)
        self.assertIs(m.state, HeroSynthState.IMPRINT_REWARD)

    def test_blue_band_without_gold_is_not_confirm(self):
        """只有蓝色带（如列表动画误现）而无金色取消带时不得当作确认弹窗。"""
        img = cv2.imread(str(FIXTURES / "list_reddot.png"))
        img[760:790, 980:1262] = (255, 110, 50)  # BGR 蓝
        m = machine(verify_filter=True)
        action = m.next_action(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        self.assertEqual("open_imprint", action.name)


class TransmitDecisionTests(unittest.TestCase):
    def test_transmit_missing_highlight_waits_before_returning(self):
        m = machine()
        with patch.object(m, "_transmit_target_card", return_value=None), patch.object(
            m, "_transmit_green_present", return_value=False
        ):
            self.assertIsNone(m.next_action(fixture("transmit_select")))
            self.assertIsNone(m.next_action(fixture("transmit_select")))

        self.assertIs(m.state, HeroSynthState.TRANSMIT_SELECT)

    def test_transmit_strip_locator_clicks_inside_highlighted_card(self):
        m = machine()
        card = m._transmit_target_card(fixture("transmit_select"))
        self.assertIsNotNone(card)
        _, y, _ = card
        self.assertGreaterEqual(y, 460)
        self.assertLessEqual(y, 520)
        self.assertNotEqual(393, y)

    def test_transmit_refuses_highlighted_sss_card(self):
        screen = fixture("transmit_select")
        sss = cv2.imread(
            str(TEMPLATES / "hero" / "sss_material.png"), cv2.IMREAD_COLOR
        )
        sss = cv2.cvtColor(sss, cv2.COLOR_BGR2RGB)
        screen[480:518, 1750:1814] = sss
        m = machine()
        action = m.next_action(screen)
        self.assertEqual("abort_transmit_sss_target", action.name)
        self.assertIs(m.state, HeroSynthState.TRANSMIT_RETURNING)

    def test_transmit_with_card_selected_starts_transmit(self):
        m = machine()
        action = m.next_action(fixture("transmit_select"))
        self.assertEqual("start_transmit", action.name)
        self.assertEqual((1203, 1057), action.point)

    def test_transmit_strip_locator_finds_card(self):
        m = machine()
        card = m._transmit_target_card(fixture("transmit_select"))
        self.assertIsNotNone(card)
        x, y, _ = card
        self.assertEqual(1720, x)

    def test_transmit_selected_starts_transmit(self):
        m = machine()
        action = m.next_action(fixture("transmit_selected"))
        self.assertEqual("start_transmit", action.name)
        self.assertEqual((1203, 1057), action.point)

    def test_transmit_confirm_popup_clicked(self):
        m = machine()
        m.state = HeroSynthState.TRANSMIT_CONFIRM
        action = m.next_action(fixture("transmit_confirm"))
        self.assertEqual("confirm_transmit", action.name)

    def test_reward_popup_closed_in_transmit_context(self):
        m = machine()
        m.state = HeroSynthState.TRANSMIT_CONFIRM
        action = m.next_action(fixture("reward_popup"))
        self.assertEqual("close_reward", action.name)
        self.assertEqual((960, 843), action.point)
        self.assertIs(m.state, HeroSynthState.TRANSMIT_RETURNING)

    def test_transmit_reward_returns_to_list_instead_of_transmitting_again(self):
        m = machine()
        m.state = HeroSynthState.TRANSMIT_RETURNING
        action = m.next_action(fixture("transmit_select"))
        self.assertEqual("back_to_list", action.name)

    def test_reward_strip_ignored_outside_transmit(self):
        m = machine()
        m.state = HeroSynthState.HERO_LIST
        # 奖励条只在传送上下文处理；列表画面应走列表分支而不是 close_reward
        action = m.next_action(fixture("list_reddot"))
        self.assertNotEqual("close_reward", action.name)


class GuardTests(unittest.TestCase):
    def test_card_fingerprint_distinguishes_recorded_cards(self):
        m = machine(verify_filter=True)
        first = m._detail_fingerprint(fixture("list_reddot"))
        second = m._detail_fingerprint(fixture("list_grey_3s"))
        self.assertNotEqual(first, second)

    def test_card_fingerprint_ignores_detail_animation_noise(self):
        m = machine(verify_filter=True)
        screen = fixture("list_reddot")
        animated = screen.copy()
        animated[350:650, 150:700] = cv2.GaussianBlur(
            animated[350:650, 150:700], (3, 3), 0
        )
        self.assertEqual(
            m._detail_fingerprint(screen),
            m._detail_fingerprint(animated),
        )

    def test_preview_restores_snapshot(self):
        m = machine(verify_filter=True)
        screen = fixture("list_reddot")
        action, outcome = m.preview(screen)
        self.assertEqual("open_imprint", action.name)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertEqual(0, m.completed_cycles)
        self.assertTrue(m.filter_verified)

    def test_scaled_window_keeps_actions_and_points(self):
        m = machine(verify_filter=True)
        scaled = cv2.resize(
            fixture("list_reddot"), (991, 566), interpolation=cv2.INTER_AREA
        )
        action = m.next_action(scaled)
        self.assertEqual("open_imprint", action.name)
        self.assertEqual((549, 498), action.point)
        m2 = machine()
        action2 = m2.next_action(scaled)
        self.assertEqual("open_filter", action2.name)
        self.assertEqual((770, 96), action2.point)


class ModeRegistrationTests(unittest.TestCase):
    def test_mode_registered(self):
        spec = get_mode("hero_synthesis")
        self.assertEqual(HeroSynthRunner, spec.runner_type)
        self.assertEqual("hero_list", spec.default_state)
        self.assertIn("imprint_add", spec.states)

    def test_resolve_state_rejects_unknown(self):
        spec = get_mode("hero_synthesis")
        with self.assertRaises(ValueError):
            spec.resolve_state("battle")

    def test_state_labels_are_chinese(self):
        self.assertEqual("英雄列表", state_label(HeroSynthState.HERO_LIST))
        self.assertEqual("合成确认", state_label(HeroSynthState.IMPRINT_CONFIRM))


class NavigationTests(unittest.TestCase):
    def navigator(self) -> Epic7Navigator:
        runtime = Runtime(lambda: None, lambda *_: None)
        return Epic7Navigator(
            build_navigation_templates(TEMPLATES), runtime, sleep=lambda _: None
        )

    def test_hero_list_page_recognized(self):
        observation = self.navigator().observe(fixture("list_reddot"))
        self.assertEqual("hero_list", observation.name)

    def test_lobby_stays_lobby(self):
        lobby = cv2.cvtColor(
            cv2.imread(str(NAV_FIXTURES / "lobby.png")), cv2.COLOR_BGR2RGB
        )
        observation = self.navigator().observe(lobby)
        self.assertEqual("lobby", observation.name)


class RunnerFlowTests(unittest.TestCase):
    def test_close_filter_uses_normal_stability_path(self):
        clicks = []
        runner = HeroSynthRunner(
            machine(),
            Runtime(lambda: fixture("filter_open"), clicks.append),
            sleep=lambda _: None,
        )
        stable = StableObservation(required=2)

        first = runner._stable_next_action(fixture("filter_open"), stable)
        second = runner._stable_next_action(fixture("filter_open"), stable)

        self.assertIs(first, NOT_STABLE)
        self.assertEqual("close_filter", second.name)
        self.assertEqual([], clicks)

    def test_filter_retry_interval_is_five_seconds(self):
        runner = HeroSynthRunner(
            machine(),
            Runtime(lambda: fixture("list_unfiltered"), lambda _: None),
            sleep=lambda _: None,
        )
        for name in ("open_filter", "select_star3", "close_filter"):
            self.assertEqual(5, runner._action_retry_seconds(name))

    def test_partial_panel_does_not_retry_until_closed_source_returns(self):
        clock = FakeClock()
        m = machine()
        partial = fixture("filter_open_star3_unselected").copy()
        x, y, w, h = m._REGIONS["filter_attribute_label"]
        partial[y : y + h, x : x + w] = 0
        screens = iter(
            [fixture("list_unfiltered")] * 2
            + [partial] * 8
            + [fixture("list_unfiltered")] * 4
        )
        clicks = []
        logs = []
        runner = HeroSynthRunner(
            m,
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))
        self.assertIn(
            "重试=open_filter 原因=原页面仍存在且目标页面未出现",
            "\n".join(logs),
        )

    def test_unchanged_selected_panel_clicks_close_exactly_four_times(self):
        clock = FakeClock()
        clicks = []
        screens = iter([fixture("filter_open")] * 50)
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: next(screens),
                lambda point: clicks.append(point),
                emit=lambda _: None,
                diagnostic_dir=Path(tmp),
                monotonic=clock,
            )
            runner = HeroSynthRunner(machine(), runtime, sleep=clock.sleep)
            with self.assertRaisesRegex(RuntimeError, "点击4次"):
                runner.run(max_cycles=1)
        self.assertEqual(4, len(clicks))

    def test_filter_logs_source_target_retry_and_completion(self):
        clock = FakeClock()
        screens = iter(
            [
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("filter_open"),
                fixture("list_unfiltered"),
                fixture("list_unfiltered"),
            ]
        )
        logs = []
        runner = HeroSynthRunner(
            machine(),
            Runtime(
                lambda: next(screens),
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        output = "\n".join(logs)
        self.assertIn("当前页面=筛选面板（三星已选中）", output)
        self.assertIn("目标页面=英雄列表", output)
        self.assertIn(
            "重试=close_filter 原因=原页面仍存在且目标页面未出现",
            output,
        )
        self.assertIn("完成=close_filter 目标页面=英雄列表", output)

    def test_transient_unknown_frame_keeps_filter_retry_attempt_count(self):
        clock = FakeClock()
        unknown = np.full_like(fixture("filter_open"), 30)
        screens = iter(
            [fixture("filter_open")] * 2
            + [unknown] * 2
            + [fixture("filter_open")] * 8
        )
        logs = []
        runner = HeroSynthRunner(
            machine(),
            Runtime(
                lambda: next(screens),
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        output = "\n".join(logs)
        self.assertEqual(1, output.count("动作=close_filter 尝试=1/4"))
        self.assertIn("动作=close_filter 尝试=2/4", output)

    def test_action_without_transition_metadata_keeps_existing_wait_log(self):
        clock = FakeClock()
        screens = iter([fixture("imprint_up_cards_no_sss")] * 4)
        logs = []
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        runner = HeroSynthRunner(
            m,
            Runtime(
                lambda: next(screens),
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        output = "\n".join(logs)
        self.assertIn("等待=点击后确认转场", output)
        self.assertNotIn("目标页面=?", output)

    def test_next_card_retry_window_is_short(self):
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        self.assertEqual(10, runner._action_retry_seconds("next_card_test"))

    def test_material_click_retry_window_is_short(self):
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        self.assertEqual(5, runner._action_retry_seconds("add_material_0_2"))

    def test_multi_card_sequence_completes_one_simulator_cycle(self):
        sequence = [
            fixture("list_reddot"),          # 首次进列表 → 打开筛选
            fixture("filter_open"),          # 三星已选 → 关闭筛选
            fixture("list_grey_3s"),         # 筛选关闭目标 + SSS 卡 → 跳过
            fixture("list_no_reddot"),       # 普通卡 → 跳过
            fixture("list_reddot"),          # 非 SSS 红点卡 → 进入刻印
            fixture("imprint_up_cards_no_sss"),  # 加材料1
            imprint_one_remaining_after_add(),    # 已入槽1张，还剩1张Up
            fixture("imprint_added"),        # 材料就位 → 开始合成
            fixture("synth_confirm"),        # 确认合成
            fixture("imprint_result_popup"), # 关闭结果覆盖层
            fixture("imprint_after_synth"),  # 返回英雄列表
            fixture("list_end_of_cards"),    # 无更多卡 → 完成一轮
        ]
        screens = iter(
            screen
            for index, screen in enumerate(sequence)
            for _ in range(4 if index in {2, 7, 11} else 2)
        )
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=1)

        names = [
            line.split("动作=")[1].split()[0]
            for line in logs
            if "执行点击" in line and "动作=" in line
        ]
        self.assertEqual(1, completed)
        self.assertEqual("open_filter", names[0])
        self.assertEqual("close_filter", names[1])
        self.assertTrue(names[2].startswith("next_card_"), names)
        self.assertTrue(names[3].startswith("next_card_"))
        self.assertEqual(
            [
                "open_imprint",
                "add_material_0_2",
                "add_material_1_1",
                "start_synthesis",
                "confirm_synthesis",
                "close_imprint_result",
                "back_to_list",
            ],
            names[4:],
        )

    def test_full_synthesis_flow(self):
        sequence = [
            fixture("list_reddot"),       # 首次进列表 → 打开筛选
            fixture("filter_open"),       # 3星已选 → 关闭筛选（验证完成）
            fixture("list_reddot"),       # 红点 → 打开刻印
            fixture("imprint_up_cards_no_sss"),  # 加材料1（两张Up）
            imprint_one_remaining_after_add(),    # 已入槽1张，还剩1张Up
            fixture("imprint_added"),     # 无Up → 点绿色合成
            fixture("synth_confirm"),     # 确认弹窗
            fixture("imprint_result_popup"),  # 关闭合成结果覆盖层
            fixture("imprint_after_synth"),  # 返回列表
            fixture("list_end_of_cards"),  # 无更多卡 → 完成一轮
        ]
        screens = iter(
            screen
            for index, screen in enumerate(sequence)
            for _ in range(4 if index in {2, 5, 9} else 2)
        )
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )
        completed = runner.run(max_cycles=1)
        self.assertEqual(1, completed)
        names = [
            line.split("动作=")[1].split()[0]
            for line in logs
            if "执行点击" in line and "动作=" in line
        ]
        self.assertEqual(
            [
                "open_filter",
                "close_filter",
                "open_imprint",
                "add_material_0_2",
                "add_material_1_1",
                "start_synthesis",
                "confirm_synthesis",
                "close_imprint_result",
                "back_to_list",
            ],
            names,
        )

    def test_recovery_resets_to_hero_list(self):
        m = HeroSynthStateMachine(build_hero_templates(TEMPLATES))
        m.state = HeroSynthState.IMPRINT_CONFIRM
        m.prev_card_grey = True
        m.filter_verified = True
        m._filter_close_pending = True
        m._confirmed_page = "筛选面板（三星已选中）"
        runtime = Runtime(lambda: None, lambda *_: None)
        runner = HeroSynthRunner(m, runtime, sleep=lambda _: None)
        runner._apply_recovery_state()
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertFalse(m.filter_verified)
        self.assertFalse(m.prev_card_grey)
        self.assertFalse(m._filter_close_pending)
        self.assertEqual("", m._confirmed_page)

    def test_changing_unknown_screen_times_out_instead_of_hanging(self):
        """持续变化的未识别画面（如带动画的列表）不能无限等待。"""
        import itertools

        nav = ROOT / "tests" / "fixtures" / "epic7_navigation"
        screens = itertools.cycle(
            cv2.cvtColor(cv2.imread(str(nav / name)), cv2.COLOR_BGR2RGB)
            for name in ("lobby.png", "story_stage.png")
        )
        clock = itertools.count(1, 10)  # 每次 now() 前进 10 秒
        machine_ = HeroSynthStateMachine(build_hero_templates(TEMPLATES))
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: next(screens),
                lambda *_: None,
                emit=lambda _: None,
                diagnostic_dir=Path(tmp),
                monotonic=lambda: next(clock),
            )
            runner = HeroSynthRunner(machine_, runtime, sleep=lambda _: None)
            with self.assertRaisesRegex(RuntimeError, "未知画面|无进展"):
                runner.run(max_cycles=1)


class BlackScreenTests(unittest.TestCase):
    def runner(self, *, runtime=None, clock=None, recovery=None):
        runtime = runtime or Runtime(lambda: None, lambda _: None)
        return HeroSynthRunner(
            machine(),
            runtime,
            sleep=(clock.sleep if clock is not None else (lambda _: None)),
            recovery=recovery,
        )

    def test_simulator_black_classifier_ignores_legacy_top_padding(self):
        runner = self.runner()
        black = np.zeros((1132, 1982, 3), dtype=np.uint8)
        self.assertTrue(runner._is_black_screen(black))

    def test_every_recorded_hero_fixture_is_not_black(self):
        runner = self.runner()
        for path in FIXTURES.glob("*.png"):
            self.assertFalse(runner._is_black_screen(fixture(path.stem)), path.name)

    def test_black_screen_stops_at_sixty_seconds_without_input_or_recovery(self):
        clock = FakeClock()
        black = np.zeros((1132, 1982, 3), dtype=np.uint8)
        clicks = []
        wakes = []
        recoveries = []
        logs = []
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: black,
                clicks.append,
                wake=wakes.append,
                emit=logs.append,
                diagnostic_dir=Path(tmp),
                monotonic=clock,
            )
            runner = self.runner(
                runtime=runtime,
                clock=clock,
                recovery=lambda: recoveries.append("recovered"),
            )
            runner._TIMEOUT_SECONDS = {
                state: 5 for state in HeroSynthState
            }

            with self.assertRaisesRegex(RuntimeError, "黑屏时间过长（60秒）"):
                runner.run(max_cycles=1)

            self.assertTrue(list(Path(tmp).glob("*_black_screen_timeout.png")))
        self.assertEqual([], clicks)
        self.assertEqual([], wakes)
        self.assertEqual([], recoveries)
        self.assertIn("最长等待=60秒", "\n".join(logs))

    def test_recovered_black_time_does_not_trigger_filter_retry(self):
        clock = FakeClock()
        black = np.zeros((1132, 1982, 3), dtype=np.uint8)
        screens = iter(
            [fixture("filter_open")] * 2
            + [black] * 10
            + [fixture("filter_open")] * 2
        )
        clicks = []
        wakes = []
        logs = []
        runtime = Runtime(
            lambda: next(screens),
            clicks.append,
            wake=wakes.append,
            emit=logs.append,
            monotonic=clock,
        )
        runner = self.runner(runtime=runtime, clock=clock)

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        self.assertEqual(1, len(clicks))
        self.assertEqual([], wakes)
        self.assertIn(
            "最后确认页面=筛选面板（三星已选中）",
            "\n".join(logs),
        )
        self.assertIn("黑屏已恢复", "\n".join(logs))
