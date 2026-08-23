"""英雄合成模式：页面判定、动作决策、安全护栏与完整流程测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2

from auto_game_unified.core.matcher import Match
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.hero_synthesis import (
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


class HeroListDecisionTests(unittest.TestCase):
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
        self.assertEqual((1710, 570), action.point)

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
        self.assertIsNone(m.next_action(fixture("list_end_of_cards")))
        self.assertEqual(1, m.completed_cycles)
        self.assertFalse(m.filter_verified)


class FilterDecisionTests(unittest.TestCase):
    def test_filter_open_with_star3_selected_closes(self):
        m = machine()
        action = m.next_action(fixture("filter_open"))
        self.assertEqual("close_filter", action.name)
        self.assertEqual((1540, 191), action.point)
        self.assertTrue(m.filter_verified)

    def test_filter_open_without_selection_selects_star3(self):
        img = fixture("filter_open")
        img[590:682, 1050:1170] = 0  # 抹掉已选3星钮
        m = machine()
        action = m.next_action(img)
        self.assertEqual("select_star3", action.name)
        self.assertEqual((1110, 636), action.point)
        self.assertFalse(m.filter_verified)


class ImprintDecisionTests(unittest.TestCase):
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
    def test_multi_card_sequence_completes_one_simulator_cycle(self):
        sequence = [
            "list_reddot",          # 首次进列表 → 打开筛选
            "filter_open",          # 三星已选 → 关闭筛选
            "list_no_reddot",       # 普通卡 → 跳过
            "list_grey_3s",         # SSS 卡 → 跳过
            "list_reddot",          # 非 SSS 红点卡 → 进入刻印
            "imprint_up_cards_no_sss",     # 加材料1
            "imprint_up_one_card_no_sss",  # 加材料2
            "imprint_added",        # 材料就位 → 开始合成
            "synth_confirm",        # 确认合成
            "imprint_result_popup", # 关闭结果覆盖层
            "imprint_after_synth",  # 返回英雄列表
            "list_end_of_cards",    # 无更多卡 → 完成一轮
        ]
        screens = iter(fixture(name) for name in sequence for _ in range(2))
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
        self.assertTrue(names[2].startswith("next_card_"))
        self.assertTrue(names[3].startswith("next_card_"))
        self.assertEqual(
            [
                "open_imprint",
                "add_material_2",
                "add_material_1",
                "start_synthesis",
                "confirm_synthesis",
                "close_imprint_result",
                "back_to_list",
            ],
            names[4:],
        )

    def test_full_synthesis_flow(self):
        sequence = [
            "list_reddot",       # 首次进列表 → 打开筛选
            "filter_open",       # 3星已选 → 关闭筛选（验证完成）
            "list_reddot",       # 红点 → 打开刻印
            "imprint_up_cards_no_sss",  # 加材料1（两张Up）
            "imprint_up_one_card_no_sss",  # 加材料2（剩一张Up）
            "imprint_added",     # 无Up → 点绿色合成
            "synth_confirm",     # 确认弹窗
            "imprint_result_popup",  # 关闭合成结果覆盖层
            "imprint_after_synth",  # 返回列表
            "list_end_of_cards",  # 无更多卡 → 完成一轮
        ]
        screens = iter(fixture(name) for name in sequence for _ in range(2))
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
                "add_material_2",
                "add_material_1",
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
        runtime = Runtime(lambda: None, lambda *_: None)
        runner = HeroSynthRunner(m, runtime, sleep=lambda _: None)
        runner._apply_recovery_state()
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertFalse(m.filter_verified)
        self.assertFalse(m.prev_card_grey)

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
