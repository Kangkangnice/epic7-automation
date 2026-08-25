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
    HeroAction,
    HeroSynthRunner,
    HeroSynthState,
    HeroSynthStateMachine,
    TransmitPhase,
    UnrecognizedScreen,
    build_hero_templates,
    state_label,
)
from auto_game_unified.games.epic7.hero_transition import (
    CardSwitchMotionObserver,
    MotionPhase,
    SafetyClass,
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


def sss_only_material_page():
    """从 SSS 材料实拍页移除普通材料的 Up! 标记，模拟只剩 SSS 材料。"""
    screen = fixture("imprint_sss_material").copy()
    x, y, w, h = HeroSynthStateMachine._UP_BADGE_ZONE
    screen[y + 140 : y + 230, x : x + w] = 0
    return screen


def shifted_list(screen, pixels):
    shifted = screen.copy()
    x, y, w, h = HeroSynthStateMachine._LIST_FP_ZONE
    shifted[y : y + h, x : x + w] = np.roll(
        screen[y : y + h, x : x + w], pixels, axis=0
    )
    return shifted


class CardSwitchMotionObserverTests(unittest.TestCase):
    def test_motion_observer_records_decision_metrics_and_key_frames(self):
        base = fixture("list_reddot")
        moved = shifted_list(base, -16)
        observer = CardSwitchMotionObserver(base)

        self.assertFalse(observer.update(moved))
        for _ in range(3):
            observer.update(moved.copy())

        sample = observer.samples[0]
        self.assertEqual(1, sample.frame)
        self.assertIs(sample.phase_before, MotionPhase.WAITING_DEPARTURE)
        self.assertIs(sample.phase_after, MotionPhase.MOVING)
        self.assertGreaterEqual(abs(sample.dy), observer.min_vertical_shift)
        self.assertGreater(sample.baseline_difference, 0)
        self.assertIsNotNone(observer.departure_screen)
        self.assertIsNotNone(observer.peak_screen)
        self.assertTrue(np.array_equal(moved, observer.last_screen))

    def test_vertical_list_motion_then_settling_confirms_switch(self):
        base = fixture("list_reddot")
        observer = CardSwitchMotionObserver(base)
        moving_1 = np.roll(base, -8, axis=0)
        moving_2 = np.roll(base, -16, axis=0)

        self.assertFalse(observer.update(moving_1))
        self.assertFalse(observer.update(moving_2))
        self.assertFalse(observer.update(moving_2.copy()))
        self.assertFalse(observer.update(moving_2.copy()))
        self.assertTrue(observer.update(moving_2.copy()))
        self.assertIs(observer.phase, MotionPhase.SETTLED)

    def test_static_identical_copy_never_confirms_switch(self):
        base = fixture("list_reddot")
        observer = CardSwitchMotionObserver(base)

        for _ in range(6):
            self.assertFalse(observer.update(base.copy()))

        self.assertIs(observer.phase, MotionPhase.WAITING_DEPARTURE)

    def test_center_anchored_list_replacement_then_settling_confirms_switch(self):
        base = fixture("list_reddot")
        changed = fixture("list_no_reddot")
        observer = CardSwitchMotionObserver(base)

        self.assertFalse(observer.update(changed))
        self.assertFalse(observer.update(changed.copy()))
        self.assertFalse(observer.update(changed.copy()))
        self.assertTrue(observer.update(changed.copy()))
        self.assertIs(observer.phase, MotionPhase.SETTLED)

    def test_motion_then_identical_final_frame_confirms_same_copy_switch(self):
        base = fixture("list_reddot")
        moving = shifted_list(base, -16)
        observer = CardSwitchMotionObserver(base)

        self.assertFalse(observer.update(moving))
        self.assertFalse(observer.update(base.copy()))
        self.assertFalse(observer.update(base.copy()))
        self.assertFalse(observer.update(base.copy()))
        self.assertTrue(observer.update(base.copy()))
        self.assertIs(observer.phase, MotionPhase.SETTLED)

    def test_content_flash_returning_to_original_does_not_confirm_switch(self):
        base = fixture("list_reddot")
        changed = fixture("list_no_reddot")
        observer = CardSwitchMotionObserver(base)

        self.assertFalse(observer.update(changed))
        for _ in range(4):
            self.assertFalse(observer.update(base.copy()))

        self.assertIsNot(observer.phase, MotionPhase.SETTLED)

    def test_two_pixel_jitter_returning_to_original_does_not_confirm_switch(self):
        base = fixture("list_reddot")
        jitter = shifted_list(base, -2)
        observer = CardSwitchMotionObserver(base)

        self.assertFalse(observer.update(jitter))
        for _ in range(4):
            self.assertFalse(observer.update(base.copy()))

        self.assertIsNot(observer.phase, MotionPhase.SETTLED)

    def test_central_portrait_animation_is_outside_motion_roi(self):
        base = fixture("list_reddot")
        animated = base.copy()
        animated[250:900, 650:1350] = np.roll(
            animated[250:900, 650:1350], 20, axis=0
        )
        observer = CardSwitchMotionObserver(base)

        for _ in range(6):
            self.assertFalse(observer.update(animated))

        self.assertIs(observer.phase, MotionPhase.WAITING_DEPARTURE)


class CardSwitchRunnerTests(unittest.TestCase):
    def test_same_identity_motion_saves_detailed_switch_evidence(self):
        base = fixture("list_reddot")
        moving = shifted_list(base, -16)
        frames = iter([moving] + [base.copy()] * 4)
        logs = []
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: next(frames),
                lambda *_: None,
                diagnostic_dir=Path(tmp),
                emit=logs.append,
            )
            runner = HeroSynthRunner(
                machine(verify_filter=True), runtime, sleep=lambda _: None
            )
            identity = runner.machine._hero_identity_fingerprint(base)
            action = HeroAction(
                "next_card_same",
                (1800, 591),
                source_page="英雄列表",
                target_pages=("英雄列表",),
                source_observation=identity,
                transition_kind="card_change",
            )
            runner.machine._last_screen = base

            runner._after_action_click(action)

            output = "\n".join(logs)
            self.assertIn("切换开始", output)
            self.assertIn("动态证据=候选", output)
            self.assertIn("静态身份=未变化", output)
            self.assertIn("切换证据帧=1", output)
            self.assertIn("frame_diff=", output)
            self.assertNotIn("结果=已确认", output)
            self.assertNotIn("切换成功", output)
            self.assertEqual(4, len(list(Path(tmp).glob("*switch_*.png"))))

    def test_changed_identity_motion_keeps_only_summary(self):
        base = fixture("list_reddot")
        changed = base.copy()
        x, y, w, h = HeroSynthStateMachine._HERO_IDENTITY_ZONE
        changed[y : y + h, x : x + w] = 0
        moving = shifted_list(base, -16)
        frames = iter([moving] + [changed.copy()] * 4)
        logs = []
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: next(frames),
                lambda *_: None,
                diagnostic_dir=Path(tmp),
                emit=logs.append,
            )
            runner = HeroSynthRunner(
                machine(verify_filter=True), runtime, sleep=lambda _: None
            )
            action = HeroAction(
                "next_card_changed",
                (1800, 591),
                source_page="英雄列表",
                target_pages=("英雄列表",),
                source_observation=runner.machine._hero_identity_fingerprint(base),
                transition_kind="card_change",
            )
            runner.machine._last_screen = base

            runner._after_action_click(action)

            output = "\n".join(logs)
            self.assertIn("动态证据=候选", output)
            self.assertIn("静态身份=已变化", output)
            self.assertNotIn("切换证据帧=", output)
            self.assertEqual([], list(Path(tmp).glob("*switch_*.png")))

    def test_transition_success_detail_distinguishes_static_identity(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True), Runtime(lambda: None, lambda *_: None)
        )
        previous = HeroAction(
            "next_card_old",
            (0, 0),
            source_observation="old",
            transition_kind="card_change",
        )
        changed = HeroAction(
            "next_card_new",
            (0, 0),
            source_observation="new",
        )
        same = HeroAction(
            "next_card_same",
            (0, 0),
            source_observation="old",
        )

        changed_detail = runner._transition_success_detail(previous, changed)
        same_detail = runner._transition_success_detail(previous, same)

        self.assertEqual(
            "业务切换成功 证据=静态身份变化并连续稳定；"
            "旧身份=old 新身份=new",
            changed_detail,
        )
        self.assertEqual(
            "业务切换成功 证据=静态身份相同，仅由动态证据确认；"
            "旧身份=old 新身份=old",
            same_detail,
        )

    def test_identical_final_card_completes_after_motion_sequence(self):
        base = fixture("list_reddot")
        frames = iter(
            [shifted_list(base, -8), shifted_list(base, -16)]
            + [shifted_list(base, -16)] * 3
        )
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: next(frames), lambda *_: None),
            sleep=lambda _: None,
        )
        action = HeroAction(
            "next_card_same",
            (1800, 591),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            source_observation="same-copy",
            transition_kind="card_change",
        )
        runner.machine._last_screen = base

        runner._after_action_click(action)

        self.assertTrue(runner._card_transition_completed(action, action))

    def test_identity_change_completes_when_motion_observation_is_missed(self):
        base = fixture("list_reddot")
        frames = iter([base.copy()] * 36)
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: next(frames), lambda *_: None),
            sleep=lambda _: None,
        )
        previous = HeroAction(
            "next_card_old",
            (0, 0),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            source_observation="old",
            transition_kind="card_change",
        )
        current = HeroAction(
            "next_card_new",
            (0, 0),
            source_page="英雄列表",
            source_observation="new",
        )
        runner.machine._last_screen = base

        runner._after_action_click(previous)

        self.assertTrue(
            runner._transition_completed(previous, current, "英雄列表")
        )

    def test_unconfirmed_switch_still_observes_current_frame(self):
        base = fixture("list_reddot")
        frames = iter([base.copy()] * 36)
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: next(frames), lambda *_: None),
            sleep=lambda _: None,
        )
        original = HeroAction(
            "next_card_original",
            (1800, 591),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            source_observation="original",
            transition_kind="card_change",
        )
        runner.machine._last_screen = base
        runner._after_action_click(original)

        with patch.object(runner.machine, "preview") as preview:
            preview.return_value = (
                None,
                (HeroSynthState.HERO_LIST, 0),
            )
            action = runner._stable_next_action(
                fixture("list_no_reddot"), StableObservation(required=1)
            )

        self.assertIsNot(action, original)
        preview.assert_called_once()

    def test_next_card_stability_ignores_idle_fingerprint_jitter(self):
        m = machine(verify_filter=True)
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        old = HeroAction(
            "next_card_old",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=old",
            source_observation="hero-a",
        )
        new = HeroAction(
            "next_card_new",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=new",
            source_observation="hero-a",
        )
        stable = StableObservation(required=2)
        outcome = (HeroSynthState.HERO_LIST, 0)

        with patch.object(m, "preview", side_effect=((old, outcome), (new, outcome))):
            with patch.object(m, "next_action", return_value=new):
                first = runner._stable_next_action(
                    fixture("list_no_reddot"), stable
                )
                second = runner._stable_next_action(
                    fixture("list_no_reddot"), stable
                )

        self.assertIs(first, NOT_STABLE)
        self.assertIs(second, new)

    def test_next_card_requires_same_identity_for_two_stable_frames(self):
        m = machine(verify_filter=True)
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        hero_a = HeroAction(
            "next_card_a",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄为SSS，跳过，详情指纹=a",
            source_observation="hero-a",
        )
        hero_b = HeroAction(
            "next_card_b",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄为SSS，跳过，详情指纹=b",
            source_observation="hero-b",
        )
        stable = StableObservation(required=2)
        outcome = (HeroSynthState.HERO_LIST, 0)

        with patch.object(
            m,
            "preview",
            side_effect=((hero_a, outcome), (hero_b, outcome), (hero_b, outcome)),
        ):
            with patch.object(m, "next_action", return_value=hero_b):
                first = runner._stable_next_action(
                    fixture("list_no_reddot"), stable
                )
                second = runner._stable_next_action(
                    fixture("list_no_reddot"), stable
                )
                third = runner._stable_next_action(
                    fixture("list_no_reddot"), stable
                )

        self.assertIs(first, NOT_STABLE)
        self.assertIs(second, NOT_STABLE)
        self.assertIs(third, hero_b)


class HeroSafetyClassificationTests(unittest.TestCase):
    def test_current_sss_is_positive_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_grey_3s")
            ),
            SafetyClass.SSS,
        )

    def test_blue_imprint_button_is_positive_non_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_reddot")
            ),
            SafetyClass.NON_SSS,
        )

    def test_no_reddot_blue_button_is_positive_non_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_no_reddot")
            ),
            SafetyClass.NON_SSS,
        )

    def test_ambiguous_grey_without_sss_is_unknown(self):
        m = machine(verify_filter=True)
        screen = fixture("list_grey_3s").copy()
        x, y, w, h = m._RATING_REGION
        screen[y : y + h, x : x + w] = 0

        self.assertIs(m._classify_current_hero(screen), SafetyClass.UNKNOWN)

    def test_material_score_margin_has_unknown_band(self):
        m = machine()
        row = m._up_badge_rows(fixture("imprint_up_cards_no_sss"))[0]
        with patch.object(m, "_material_sss_score", return_value=0.70):
            self.assertIs(
                m._classify_material_row(
                    fixture("imprint_up_cards_no_sss"), row
                ),
                SafetyClass.UNKNOWN,
            )

    def test_material_score_boundaries_are_fail_closed(self):
        m = machine()
        screen = fixture("imprint_up_cards_no_sss")
        row = m._up_badge_rows(screen)[0]
        cases = (
            (0.55, SafetyClass.NON_SSS),
            (0.5501, SafetyClass.UNKNOWN),
            (0.80, SafetyClass.SSS),
        )
        for score, expected in cases:
            with self.subTest(score=score), patch.object(
                m, "_material_sss_score", return_value=score
            ):
                self.assertIs(m._classify_material_row(screen, row), expected)

    def test_transmit_target_score_margin_has_unknown_band(self):
        m = machine()
        card = m._transmit_target_card(fixture("transmit_select"))
        with patch.object(m, "_material_sss_score", return_value=0.70):
            self.assertIs(
                m._classify_transmit_target(fixture("transmit_select"), card),
                SafetyClass.UNKNOWN,
            )

    def test_transmit_score_boundaries_are_fail_closed(self):
        m = machine()
        screen = fixture("transmit_select")
        card = m._transmit_target_card(screen)
        cases = (
            (0.55, SafetyClass.NON_SSS),
            (0.5501, SafetyClass.UNKNOWN),
            (0.80, SafetyClass.SSS),
        )
        for score, expected in cases:
            with self.subTest(score=score), patch.object(
                m, "_material_sss_score", return_value=score
            ):
                self.assertIs(
                    m._classify_transmit_target(screen, card), expected
                )

    def test_unknown_current_hero_does_not_click(self):
        m = machine(verify_filter=True)
        with patch.object(
            m, "_classify_current_hero", return_value=SafetyClass.UNKNOWN
        ):
            self.assertIsNone(m.next_action(fixture("list_reddot")))

    def test_unknown_material_row_does_not_click_or_start_synthesis(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        with patch.object(
            m, "_classify_material_row", return_value=SafetyClass.UNKNOWN
        ):
            self.assertIsNone(
                m.next_action(fixture("imprint_up_cards_no_sss"))
            )

    def test_unknown_transmit_target_does_not_click(self):
        m = machine()
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        with patch.object(
            m, "_classify_transmit_target", return_value=SafetyClass.UNKNOWN
        ):
            self.assertIsNone(m.next_action(fixture("transmit_select")))


class FrameScopedEvidenceTests(unittest.TestCase):
    def test_unknown_frame_clears_simulator_confirmed_page(self):
        m = machine(verify_filter=True)
        m._confirmed_page = "刻印加材料"
        unknown = np.full_like(fixture("imprint_added"), 30)

        self.assertIsNone(m.next_action(unknown))
        self.assertEqual("", m._confirmed_page)

    def test_material_action_requires_slot_or_row_change(self):
        runner = HeroSynthRunner(
            machine(),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        previous = HeroAction(
            "add_material_0_2",
            (0, 0),
            source_observation="slots=0;rows=450,600",
            transition_kind="material_change",
        )
        unchanged = HeroAction(
            "add_material_0_2",
            (0, 0),
            source_observation="slots=0;rows=450,600",
        )
        changed = HeroAction(
            "add_material_1_1",
            (0, 0),
            source_observation="slots=1;rows=600",
        )

        self.assertFalse(
            runner._material_transition_completed(previous, unchanged)
        )
        self.assertTrue(
            runner._material_transition_completed(previous, changed)
        )


class TransmitTransactionTests(unittest.TestCase):
    def test_target_persists_until_reward_is_confirmed(self):
        m = machine(verify_filter=True)
        m._active_card_observation = "card-copy-7"
        m.state = HeroSynthState.IMPRINT_ADD

        m.next_action(sss_only_material_page())
        self.assertIs(m.transmit_phase, TransmitPhase.PENDING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

        m.next_action(fixture("list_reddot"))
        m.next_action(fixture("transmit_select"))
        self.assertIsNot(m.transmit_phase, TransmitPhase.NONE)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_entering_transmit_page_does_not_mark_target_transmitted(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "card-copy-7"
        m.transmit_continuity_intact = True

        m.next_action(fixture("transmit_select"))

        self.assertIs(m.transmit_phase, TransmitPhase.SELECTING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_recovery_does_not_clear_unfinished_transmit_target(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING
        m.transmit_target_observation = "card-copy-7"
        runner = HeroSynthRunner(m, Runtime(lambda: None, lambda *_: None))

        runner._apply_recovery_state()

        self.assertIs(m.transmit_phase, TransmitPhase.CONFIRMING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_recovery_breaks_continuity_and_blocks_pending_transmit(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = m._hero_identity_fingerprint(
            fixture("list_reddot")
        )
        m.transmit_continuity_intact = True
        runner = HeroSynthRunner(m, Runtime(lambda: None, lambda *_: None))

        runner._apply_recovery_state()

        self.assertFalse(m.transmit_continuity_intact)
        self.assertIsNone(m.next_action(fixture("list_reddot")))

    def test_recovery_blocks_transmit_selection_and_confirmation_side_effects(self):
        cases = (
            (TransmitPhase.OPENING, fixture("transmit_select")),
            (TransmitPhase.SELECTING, fixture("transmit_confirm")),
            (TransmitPhase.CONFIRMING, fixture("transmit_confirm")),
        )
        for phase, screen in cases:
            with self.subTest(phase=phase):
                m = machine(verify_filter=True)
                m.transmit_phase = phase
                m.transmit_target_observation = "saved-card"
                m.transmit_continuity_intact = True
                runner = HeroSynthRunner(
                    m, Runtime(lambda: None, lambda *_: None)
                )

                runner._apply_recovery_state()

                self.assertIsNone(m.next_action(screen))

    def test_pending_transmit_without_saved_target_is_fail_closed(self):
        m = machine(verify_filter=True)
        m.pending_transmit_target = True

        self.assertIsNone(m.next_action(fixture("list_reddot")))

    def test_saved_target_must_still_be_selected_before_opening_transmit(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = "different-card"

        self.assertIsNone(m.next_action(fixture("list_reddot")))
        self.assertIs(m.transmit_phase, TransmitPhase.PENDING)

    def test_saved_target_identity_ignores_idle_list_animation(self):
        m = machine(verify_filter=True)
        original = fixture("list_reddot")
        animated = original.copy()
        animated[250:800, 1600:1900] = 255 - animated[250:800, 1600:1900]
        self.assertNotEqual(
            m._detail_fingerprint(original),
            m._detail_fingerprint(animated),
        )
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = m._hero_identity_fingerprint(original)
        m.transmit_continuity_intact = True

        action = m.next_action(animated)

        self.assertEqual("open_transmit_for_current_card", action.name)

    def test_auto_select_label_alone_is_not_complete_transmit_page(self):
        m = machine(verify_filter=True)
        incomplete = fixture("transmit_select").copy()
        x, y, w, h = m._TRANSMIT_GRID_ZONE
        incomplete[y : y + h, x : x + w] = 0

        self.assertFalse(m._transmit_page_ready(incomplete))

    def test_sss_material_without_saved_current_hero_stops(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD

        with self.assertRaises(UnrecognizedScreen):
            m.next_action(sss_only_material_page())

    def test_transmit_page_cannot_start_from_unbound_or_later_phases(self):
        for phase in (
            TransmitPhase.NONE,
            TransmitPhase.PENDING,
            TransmitPhase.CONFIRMING,
        ):
            with self.subTest(phase=phase):
                m = machine(verify_filter=True)
                m.transmit_phase = phase
                m.transmit_target_observation = (
                    None if phase is TransmitPhase.NONE else "saved-card"
                )

                self.assertIsNone(m.next_action(fixture("transmit_select")))
                self.assertIs(m.transmit_phase, phase)

    def test_confirm_popup_requires_selecting_phase(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"

        self.assertIsNone(m.next_action(fixture("transmit_confirm")))
        self.assertIs(m.transmit_phase, TransmitPhase.OPENING)


class TransmitRewardEvidenceTests(unittest.TestCase):
    def test_full_reward_popup_marks_transmitted(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING

        action = m.next_action(fixture("reward_popup"))

        self.assertEqual("close_reward", action.name)
        self.assertIs(m.transmit_phase, TransmitPhase.RETURNING)
        self.assertTrue(m._transmit_reward_confirmed)

    def test_bright_strip_without_title_items_and_close_hint_is_not_reward(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING
        weak = np.zeros_like(fixture("reward_popup"))
        x, y, w, h = m._REWARD_STRIP_ZONE
        weak[y : y + h, x : x + w] = 180

        self.assertIsNone(m.next_action(weak))
        self.assertFalse(m._transmit_reward_confirmed)

    def test_returning_phase_never_selects_or_transmits_again(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.RETURNING
        m._transmit_reward_confirmed = True

        action = m.next_action(fixture("transmit_select"))

        self.assertEqual("back_to_list", action.name)
        self.assertNotIn("transmit", action.name)

    def test_returned_hero_list_is_confirmed_without_filter_button_match(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.TRANSMIT_RETURNING
        m.transmit_phase = TransmitPhase.RETURNING
        m._transmit_reward_confirmed = True
        screen = fixture("list_reddot").copy()
        x, y, w, h = m._REGIONS["filter_button"]
        screen[y : y + h, x : x + w] = 0

        self.assertTrue(m._hero_list_ready(screen))
        self.assertIsNone(m._locate(screen, "filter_button", 0.80))

        m.next_action(screen)

        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertIs(m.transmit_phase, TransmitPhase.NONE)
        self.assertEqual("英雄列表", m._confirmed_page)


def test_sss_material_transmit_returns_once_and_continues_cycle():
    sequence = (
        [fixture("list_reddot")] * 2
        + [fixture("filter_open")] * 2
        + [fixture("list_reddot")] * 2
        + [sss_only_material_page()] * 2
        + [fixture("list_reddot")] * 2
        + [fixture("transmit_select")] * 2
        + [fixture("transmit_confirm")] * 2
        + [fixture("reward_popup")] * 2
        + [fixture("transmit_select")] * 2
        + [fixture("list_end_of_cards")] * 4
    )
    screens = iter(sequence)
    clicks = []
    logs = []
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: next(screens), clicks.append, emit=logs.append),
        sleep=lambda _: None,
    )

    completed = runner.run(max_cycles=1)

    names = [
        line.split("动作=")[1].split()[0]
        for line in logs
        if "执行点击" in line and "动作=" in line
    ]
    assert completed == 1
    assert names.count("confirm_transmit") == 1
    assert names.count("close_reward") == 1
    assert "back_to_list" in names

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
            "sss_material_warning_title",
            "sss_material_warning_close",
            "transmit_reward_title",
            "transmit_reward_close",
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

    def test_transmit_reward_templates_are_tight_and_do_not_cross_match(self):
        templates = build_hero_templates(TEMPLATES)
        self.assertEqual((90, 300), templates.transmit_reward_title.shape[:2])
        self.assertEqual((140, 300), templates.transmit_reward_close.shape[:2])
        m = HeroSynthStateMachine(templates)
        screen = fixture("reward_popup")

        self.assertIsNotNone(
            m._locate(
                screen,
                "transmit_reward_title",
                0.90,
                region_override=m._REWARD_TITLE_REGION,
            )
        )
        self.assertIsNotNone(
            m._locate(
                screen,
                "transmit_reward_close",
                0.92,
                region_override=m._REWARD_CLOSE_REGION,
            )
        )
        self.assertIsNone(
            m._locate(
                screen,
                "transmit_reward_title",
                0.90,
                region_override=m._REWARD_CLOSE_REGION,
            )
        )

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


class HeroPageEvidenceTests(unittest.TestCase):
    def test_imprint_material_page_sets_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD

        m.next_action(fixture("imprint_up_cards_no_sss"))

        self.assertEqual("刻印加材料", m._confirmed_page)

    def test_synthesis_confirm_sets_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD

        m.next_action(fixture("synth_confirm"))

        self.assertEqual("合成确认", m._confirmed_page)

    def test_imprint_result_sets_confirmed_page(self):
        m = machine(verify_filter=True)

        m.next_action(fixture("imprint_result_popup"))

        self.assertEqual("合成结果", m._confirmed_page)

    def test_transmit_pages_set_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.TRANSMIT_SELECT
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True

        m.next_action(fixture("transmit_select"))
        self.assertEqual("传送选择", m._confirmed_page)

        m.next_action(fixture("transmit_confirm"))
        self.assertEqual("传送确认", m._confirmed_page)

        m.next_action(fixture("reward_popup"))
        self.assertEqual("传送奖励", m._confirmed_page)

    def test_sss_material_page_takes_precedence(self):
        m = machine(verify_filter=True)
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD

        m.next_action(sss_only_material_page())

        self.assertEqual("刻印SSS材料", m._confirmed_page)

    def test_partial_imprint_page_does_not_set_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD
        m._confirmed_page = "筛选面板（三星已选中）"
        screen = fixture("imprint_up_cards_no_sss").copy()
        x, y, w, h = m._IMPRINT_SLOT_ZONES[0]
        screen[y : y + h, x : x + w] = 0

        m.next_action(screen)

        self.assertEqual("", m._confirmed_page)

    def test_unknown_filter_observation_preserves_non_filter_page_evidence(self):
        partial = fixture("filter_open_star3_unselected").copy()
        x, y, w, h = machine()._REGIONS["filter_attribute_label"]
        partial[y : y + h, x : x + w] = 0
        cases = (
            (HeroSynthState.IMPRINT_CONFIRM, "合成确认"),
            (HeroSynthState.TRANSMIT_SELECT, "传送选择"),
        )

        for state, label in cases:
            with self.subTest(state=state):
                m = machine(verify_filter=True)
                m.state = state
                m._confirmed_page = label

                handled, action = m._next_simulator_filter_action(partial)

                self.assertFalse(handled)
                self.assertIsNone(action)
                self.assertEqual(label, m._confirmed_page)


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
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

    def test_list_no_reddot_advances(self):
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_no_reddot"))
        self.assertTrue(action.name.startswith("next_card"))
        self.assertEqual((1800, 591), action.point)

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
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

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


class HeroListTransitionTests(unittest.TestCase):
    def test_open_imprint_retries_while_hero_list_remains(self):
        m = machine(verify_filter=True)

        first = m.next_action(fixture("list_reddot"))
        second = m.next_action(fixture("list_reddot"))

        self.assertIsNotNone(second)
        self.assertEqual("open_imprint", first.name)
        self.assertEqual("open_imprint", second.name)
        for action in (first, second):
            self.assertEqual("英雄列表", action.source_page)
            self.assertIn("刻印加材料", action.target_pages)
            self.assertIn("刻印SSS材料", action.target_pages)
            self.assertIn("当前英雄非SSS", action.reason)
            self.assertIn("红点存在", action.reason)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertEqual("英雄列表", m._confirmed_page)

    def test_fallback_open_imprint_has_transition_metadata(self):
        m = machine(verify_filter=True)

        with patch.object(m, "_locate_button", return_value=None):
            action = m.next_action(fixture("list_reddot"))

        self.assertEqual("open_imprint", action.name)
        self.assertEqual("英雄列表", action.source_page)
        self.assertEqual(("刻印加材料", "刻印SSS材料"), action.target_pages)
        self.assertIn("当前英雄非SSS", action.reason)
        self.assertIn("红点存在", action.reason)

    def test_open_imprint_commits_only_after_complete_imprint_page_appears(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

        action = m.next_action(fixture("imprint_up_cards_no_sss"))

        self.assertTrue(action.name.startswith("add_material_"))
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)
        self.assertEqual("刻印加材料", m._confirmed_page)

    def test_incomplete_imprint_slots_cannot_enter_material_processing(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))
        screen = fixture("imprint_up_cards_no_sss").copy()
        x, y, w, h = m._IMPRINT_SLOT_ZONES[0]
        screen[y : y + h, x : x + w] = 0

        self.assertTrue(m._green_button_present(screen))
        self.assertIsNotNone(m._find_up_card(screen))
        self.assertFalse(m._imprint_slots_present(screen))

        action = m.next_action(screen)

        self.assertIsNone(action)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertEqual("", m._confirmed_page)

    def test_immediate_sss_imprint_page_is_recognized_before_material_action(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

        action = m.next_action(sss_only_material_page())

        self.assertEqual("刻印SSS材料", m._confirmed_page)
        self.assertFalse(action.name.startswith("add_material_"))
        self.assertEqual("abort_imprint_to_transmit", action.name)

    def test_any_sss_material_aborts_before_ordinary_material(self):
        """同屏只要有 SSS，普通副本也不能再合进当前英雄。"""
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))

        action = m.next_action(fixture("imprint_up_cards"))

        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertEqual("刻印SSS材料", m._confirmed_page)

    def test_sss_detection_ignores_animated_card_background_border(self):
        """SSS 文字本身清晰时，卡片立绘变化不能让整页检测失效。"""
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))
        screen = fixture("imprint_up_cards").copy()
        match = m._locate(
            screen,
            "sss_material",
            -1.0,
            region_override=m._MATERIAL_SSS_REGION,
        )
        height, width = m.templates.sss_material.shape[:2]
        left = match.center[0] - width // 2
        top = match.center[1] - height // 2
        border = 4
        screen[top : top + border, left : left + width] = 0
        screen[top + height - border : top + height, left : left + width] = 0
        screen[top : top + height, left : left + border] = 0
        screen[top : top + height, left + width - border : left + width] = 0

        action = m.next_action(screen)

        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertEqual("刻印SSS材料", m._confirmed_page)

    def test_complete_imprint_page_matches_sss_material_once(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))

        with patch.object(
            m, "_sss_material_present", wraps=m._sss_material_present
        ) as sss_material_present:
            action = m.next_action(sss_only_material_page())

        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertEqual(1, sss_material_present.call_count)

    def test_next_card_actions_explain_each_skip_with_detail_fingerprint(self):
        cases = (
            ("list_no_reddot", "无红点"),
            ("list_grey_3s", "SSS"),
        )
        for fixture_name, skip_reason in cases:
            with self.subTest(fixture_name=fixture_name):
                m = machine(verify_filter=True)
                screen = fixture(fixture_name)
                fingerprint = m._detail_fingerprint(screen)

                action = settled_next(m, screen)

                self.assertTrue(action.name.startswith("next_card_"))
                self.assertEqual("英雄列表", action.source_page)
                self.assertEqual(("英雄列表",), action.target_pages)
                self.assertIn(fingerprint, action.reason)
                self.assertIn(skip_reason, action.reason)

    def test_next_card_identity_ignores_rating_jitter(self):
        m = machine(verify_filter=True)
        screen = fixture("list_no_reddot")

        with patch.object(m, "_is_max_rating", side_effect=(True, True, False, False)):
            first = m.next_action(screen)
            second = m.next_action(screen)

        self.assertEqual(first.name, second.name)
        self.assertIn("当前英雄为SSS", first.reason)
        self.assertIn("当前英雄非SSS但刻印按钮无红点", second.reason)

    def test_next_card_contract_carries_card_observation(self):
        m = machine(verify_filter=True)
        screen = fixture("list_no_reddot")

        action = settled_next(m, screen)

        self.assertEqual(m._hero_identity_fingerprint(screen), action.source_observation)
        self.assertEqual("card_change", action.transition_kind)

    def test_open_imprint_retry_identity_ignores_list_animation(self):
        original = fixture("list_reddot")
        animated = original.copy()
        animated[250:800, 1600:1900] = 255 - animated[250:800, 1600:1900]
        m = machine(verify_filter=True)

        first = m.next_action(original)
        second = m.next_action(animated)

        self.assertEqual("open_imprint", first.name)
        self.assertEqual("open_imprint", second.name)
        self.assertNotEqual(m._detail_fingerprint(original), m._detail_fingerprint(animated))
        self.assertEqual(first.source_observation, second.source_observation)

    def test_confirmed_motion_is_consumed_after_switch(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True), Runtime(lambda: None, lambda *_: None)
        )
        previous = HeroAction(
            "next_card_old",
            (0, 0),
            source_observation="name=A|selected_row=1",
        )
        current = HeroAction(
            "next_card_new",
            (0, 0),
            source_observation="name=A|selected_row=1",
        )
        runner._card_switch_motion_confirmed = True

        self.assertTrue(runner._card_transition_completed(previous, current))
        self.assertFalse(runner._card_transition_completed(previous, current))

    def test_same_card_observation_does_not_count_as_switch(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True), Runtime(lambda: None, lambda *_: None)
        )
        previous = HeroAction(
            "next_card_old",
            (0, 0),
            source_observation="name=A|selected_row=1",
        )
        current = HeroAction(
            "next_card_old",
            (0, 0),
            source_observation="name=A|selected_row=1",
        )

        self.assertFalse(runner._card_transition_completed(previous, current))

    def test_end_of_list_still_requires_two_stable_observations(self):
        m = machine(verify_filter=True)
        screen = fixture("list_end_of_cards")

        self.assertIsNone(m.next_action(screen))
        self.assertEqual(0, m.completed_cycles)
        self.assertIsNone(m.next_action(screen))
        self.assertEqual(1, m.completed_cycles)


class FilterDecisionTests(unittest.TestCase):
    def test_equipment_subtab_switches_to_hero_info_before_filtering(self):
        screen = fixture("list_unfiltered").copy()
        info = (0, 150, 127, 105)
        equip = (0, 255, 127, 105)
        ix, iy, iw, ih = info
        ex, ey, ew, eh = equip
        info_pixels = screen[iy : iy + ih, ix : ix + iw].copy()
        screen[iy : iy + ih, ix : ix + iw] = screen[
            ey : ey + eh, ex : ex + ew
        ]
        screen[ey : ey + eh, ex : ex + ew] = info_pixels
        for x, y, w, h in (
            HeroSynthStateMachine._BUTTON_ZONE,
            HeroSynthStateMachine._RATING_REGION,
            HeroSynthStateMachine._REDDOT_ZONE,
        ):
            screen[y : y + h, x : x + w] = 0

        action = machine().next_action(screen)

        self.assertEqual("select_hero_info_tab", action.name)
        self.assertEqual((65, 200), action.point)
        self.assertEqual("英雄装备页", action.source_page)
        self.assertEqual(("英雄列表",), action.target_pages)

    def test_unknown_left_tab_selection_blocks_hero_actions(self):
        m = machine(verify_filter=True)
        screen = fixture("list_reddot").copy()
        for x, y, w, h in (
            m._HERO_INFO_TAB_ZONE,
            m._EQUIPMENT_TAB_ZONE,
        ):
            screen[y : y + h, x : x + w] = 0

        self.assertIsNone(m.next_action(screen))

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
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD
        action = m.next_action(sss_only_material_page())
        self.assertEqual("abort_imprint_to_transmit", action.name)

    def test_sss_material_warning_is_closed_before_resuming_imprint(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        action = m.next_action(fixture("imprint_sss_warning_popup"))

        self.assertEqual("close_sss_material_warning", action.name)
        self.assertEqual("刻印SSS警告", action.source_page)
        self.assertEqual(("刻印加材料", "刻印SSS材料"), action.target_pages)
        self.assertIn("提示层标题与关闭控件", action.reason)

        repeated = m.next_action(fixture("imprint_sss_warning_popup"))
        self.assertEqual("close_sss_material_warning", repeated.name)

    def test_pending_transmit_opens_transmit_for_current_card(self):
        m = machine(verify_filter=True)
        m.pending_transmit_target = True
        m.transmit_target_observation = m._hero_identity_fingerprint(
            fixture("list_reddot")
        )
        action = m.next_action(fixture("list_reddot"))
        self.assertEqual("open_transmit_for_current_card", action.name)
        self.assertEqual((1735, 1060), action.point)

    def test_sss_material_branch_enters_existing_transmit_flow(self):
        m = machine()
        m._active_card_observation = m._hero_identity_fingerprint(
            fixture("list_reddot")
        )
        m.state = HeroSynthState.IMPRINT_ADD
        m.next_action(sss_only_material_page())
        self.assertTrue(m.pending_transmit_target)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ABORTING)
        self.assertIsNone(m.next_action(fixture("imprint_up_cards_no_sss")))
        self.assertEqual(
            "open_transmit_for_current_card",
            m.next_action(fixture("list_reddot")).name,
        )
        self.assertEqual("start_transmit", m.next_action(fixture("transmit_select")).name)
        self.assertTrue(m.pending_transmit_target)

    def test_preview_restores_pending_transmit_context(self):
        m = machine()
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD
        action, _ = m.preview(sss_only_material_page())
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

    def test_normal_synthesis_actions_publish_transition_contracts(self):
        cases = (
            (
                "imprint_up_cards_no_sss",
                HeroSynthState.IMPRINT_ADD,
                "add_material_0_2",
                "刻印加材料",
                ("刻印加材料", "刻印SSS材料"),
                "发现普通Up材料，已填槽位=0，目标=2",
            ),
            (
                "synth_confirm",
                HeroSynthState.IMPRINT_ADD,
                "confirm_synthesis",
                "合成确认",
                ("合成结果",),
                "蓝色确认按钮带与金色内容带同时存在",
            ),
            (
                "imprint_result_popup",
                HeroSynthState.IMPRINT_CONFIRM,
                "close_imprint_result",
                "合成结果",
                ("合成后刻印页",),
                "结果标题与关闭控件同时存在",
            ),
            (
                "imprint_after_synth",
                HeroSynthState.IMPRINT_REWARD,
                "back_to_list",
                "合成后刻印页",
                ("英雄列表",),
                "结果覆盖层消失且刻印页返回箭头存在",
            ),
        )
        for fixture_name, state, name, source, targets, reason in cases:
            with self.subTest(fixture=fixture_name):
                m = machine(verify_filter=True)
                m.state = state

                action = m.next_action(fixture(fixture_name))

                self.assertEqual(name, action.name)
                self.assertEqual(source, action.source_page)
                self.assertEqual(targets, action.target_pages)
                self.assertEqual(reason, action.reason)

    def test_imprint_without_up_starts_synthesis(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        self.assertIsNone(m.next_action(fixture("imprint_added")))
        action = m.next_action(fixture("imprint_added"))
        self.assertEqual("start_synthesis", action.name)
        self.assertEqual((1149, 1078), action.point)
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_start_synthesis_retries_while_ready_material_page_remains(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD
        ready = fixture("imprint_added")

        self.assertIsNone(m.next_action(ready))
        first = m.next_action(ready)
        second = m.next_action(ready)

        for action in (first, second):
            self.assertEqual("start_synthesis", action.name)
            self.assertEqual("刻印加材料", action.source_page)
            self.assertEqual(("合成确认", "合成结果"), action.target_pages)
            self.assertEqual(
                "Up材料已清空，已填槽位=1，费用非零，连续确认=2",
                action.reason,
            )
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)
        self.assertEqual(m._READINESS_OBSERVATIONS, m._imprint_empty_observations)

    def test_confirm_synthesis_retries_until_result_evidence_appears(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD
        m._imprint_empty_observations = m._READINESS_OBSERVATIONS
        confirm = fixture("synth_confirm")

        first = m.next_action(confirm)
        second = m.next_action(confirm)

        self.assertEqual("confirm_synthesis", first.name)
        self.assertEqual("confirm_synthesis", second.name)
        self.assertIs(m.state, HeroSynthState.IMPRINT_CONFIRM)
        self.assertEqual(0, m._imprint_empty_observations)

    def test_close_result_retries_until_post_result_page_appears(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_CONFIRM
        m._imprint_empty_observations = m._READINESS_OBSERVATIONS
        result = fixture("imprint_result_popup")

        first = m.next_action(result)
        second = m.next_action(result)

        self.assertEqual("close_imprint_result", first.name)
        self.assertEqual("close_imprint_result", second.name)
        self.assertIs(m.state, HeroSynthState.IMPRINT_REWARD)
        self.assertEqual(0, m._imprint_empty_observations)

    def test_imprint_after_synth_backs_to_list(self):
        m = machine()
        m.state = HeroSynthState.IMPRINT_REWARD
        action = m.next_action(fixture("imprint_after_synth"))
        self.assertEqual("back_to_list", action.name)
        self.assertLess(abs(action.point[0] - 30), 20)
        self.assertLess(abs(action.point[1] - 92), 20)
        self.assertIs(m.state, HeroSynthState.IMPRINT_REWARD)

    def test_back_to_list_retries_until_hero_list_evidence_appears(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_REWARD
        post_result = fixture("imprint_after_synth")

        first = m.next_action(post_result)
        second = m.next_action(post_result)

        self.assertEqual("back_to_list", first.name)
        self.assertEqual("back_to_list", second.name)
        self.assertIs(m.state, HeroSynthState.IMPRINT_REWARD)
        self.assertEqual("合成后刻印页", m._confirmed_page)

        m.next_action(fixture("list_reddot"))

        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertEqual("英雄列表", m._confirmed_page)

    def test_partial_imprint_pages_never_start_add_or_back(self):
        partial = fixture("imprint_after_synth").copy()
        x, y, w, h = machine()._IMPRINT_SLOT_ZONES[0]
        partial[y : y + h, x : x + w] = 0

        for state in (HeroSynthState.IMPRINT_ADD, HeroSynthState.IMPRINT_REWARD):
            with self.subTest(state=state):
                m = machine(verify_filter=True)
                m.state = state

                action = m.next_action(partial)

                self.assertIsNone(action)
                self.assertIs(m.state, state)

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
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
        with patch.object(m, "_transmit_target_card", return_value=None), patch.object(
            m, "_transmit_green_present", return_value=False
        ):
            self.assertIsNone(m.next_action(fixture("transmit_select")))
            self.assertIsNone(m.next_action(fixture("transmit_select")))

        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertIs(m.transmit_phase, TransmitPhase.OPENING)

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
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
        action = m.next_action(screen)
        self.assertEqual("abort_transmit_sss_target", action.name)
        self.assertIs(m.state, HeroSynthState.TRANSMIT_RETURNING)

    def test_transmit_with_card_selected_starts_transmit(self):
        m = machine()
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
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
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
        action = m.next_action(fixture("transmit_selected"))
        self.assertEqual("start_transmit", action.name)
        self.assertEqual((1203, 1057), action.point)

    def test_transmit_confirm_popup_clicked(self):
        m = machine()
        m.state = HeroSynthState.TRANSMIT_CONFIRM
        m.transmit_phase = TransmitPhase.SELECTING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
        action = m.next_action(fixture("transmit_confirm"))
        self.assertEqual("confirm_transmit", action.name)

    def test_reward_popup_closed_in_transmit_context(self):
        m = machine()
        m.state = HeroSynthState.TRANSMIT_CONFIRM
        m.transmit_phase = TransmitPhase.CONFIRMING
        m.transmit_target_observation = "saved-card"
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
    def test_successful_card_transitions_do_not_arm_loop_recovery(self):
        clock = FakeClock()
        recoveries = []
        logs = []
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(
                lambda: fixture("list_no_reddot"),
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
            recovery=lambda: recoveries.append("recovered"),
        )
        runner.machine._confirmed_page = "英雄列表"
        actions = [
            HeroAction(
                f"next_card_{index}",
                (1800, 591),
                source_page="英雄列表",
                target_pages=("英雄列表",),
                source_observation=f"hero-{index}",
                transition_kind="card_change",
            )
            for index in range(16)
        ]
        previews = actions + [NOT_STABLE] * 31

        def confirm_motion(_action):
            runner._card_switch_motion_confirmed = True

        with patch.object(
            runner, "_stable_next_action", side_effect=previews
        ), patch.object(runner, "_after_action_click", side_effect=confirm_motion):
            with self.assertRaises(StopIteration):
                runner.run(max_cycles=1)

        self.assertEqual([], recoveries)
        self.assertNotIn("循环检测=", "\n".join(logs))

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

    def test_open_imprint_contract_blocks_next_card_until_target_page(self):
        screens = iter(
            [fixture("list_reddot")] * 2
            + [fixture("list_no_reddot")] * 6
        )
        logs: list[str] = []
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(
                lambda: next(screens),
                lambda _: None,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        with self.assertRaises(StopIteration):
            runner.run(max_cycles=1)

        clicked = [
            line for line in logs if "执行点击" in line and "动作=" in line
        ]
        self.assertTrue(any("动作=open_imprint" in line for line in clicked))
        self.assertFalse(any("动作=next_card" in line for line in clicked))

    def test_transition_retry_requires_same_source_observation(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: None, lambda *_: None),
        )
        previous = HeroAction(
            "open_imprint",
            (0, 0),
            source_page="英雄列表",
            source_observation="hero-a",
        )
        current = HeroAction(
            "open_imprint",
            (0, 0),
            source_page="英雄列表",
            source_observation="hero-b",
        )

        self.assertFalse(runner._source_observation_matches(previous, current))

    def test_next_card_retry_window_is_short(self):
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        self.assertEqual(1, runner._action_retry_seconds("next_card_test"))

    def test_material_click_retry_window_is_short(self):
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        self.assertEqual(5, runner._action_retry_seconds("add_material_0_2"))

    def test_multi_card_sequence_completes_one_simulator_cycle(self):
        grey = fixture("list_grey_3s")
        no_reddot = fixture("list_no_reddot")
        screens = iter(
            [fixture("list_reddot")] * 2
            + [fixture("filter_open")] * 2
            + [grey] * 4
            + [shifted_list(grey, -8), shifted_list(grey, -16)]
            + [shifted_list(grey, -16)] * 3
            + [no_reddot] * 2
            + [shifted_list(no_reddot, -8), shifted_list(no_reddot, -16)]
            + [shifted_list(no_reddot, -16)] * 3
            + [fixture("list_reddot")] * 2
            + [fixture("imprint_up_cards_no_sss")] * 2
            + [imprint_one_remaining_after_add()] * 2
            + [fixture("imprint_added")] * 4
            + [fixture("synth_confirm")] * 2
            + [fixture("imprint_result_popup")] * 2
            + [fixture("imprint_after_synth")] * 2
            + [fixture("list_end_of_cards")] * 4
        )
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = FakeClock()
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(
                lambda: next(screens),
                clicks.append,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
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
        self.assertTrue(names[3].startswith("next_card_"), names)
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
