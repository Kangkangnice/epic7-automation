"""英雄合成模式：页面判定、动作决策、安全护栏与完整流程测试。"""

import ast
import inspect
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np
from auto_game_unified.core.matcher import Match, find_template, load_template
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
from auto_game_unified.games.epic7.evidence.hero_synthesis import build_hero_evidence
from auto_game_unified.games.epic7.modes import get_mode
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
                in_page_evidence=identity,
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
                in_page_evidence=runner.machine._hero_identity_fingerprint(base),
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
            in_page_evidence="old",
            transition_kind="card_change",
        )
        changed = HeroAction(
            "next_card_new",
            (0, 0),
            in_page_evidence="new",
        )
        same = HeroAction(
            "next_card_same",
            (0, 0),
            in_page_evidence="old",
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
            in_page_evidence="same-copy",
            transition_kind="card_change",
        )
        runner.machine._last_screen = base

        runner._after_action_click(action)

        self.assertTrue(runner._card_transition_completed(action, action))

    def test_confirmed_sss_card_switch_arms_context_for_the_next_card(self):
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
            "next_card_sss",
            (1800, 591),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            reason="当前英雄为SSS，跳过",
            in_page_evidence="hero-abc",
            transition_kind="card_change",
        )
        runner.machine._last_screen = base

        runner._after_action_click(action)

        self.assertEqual(
            ("hero-abc", SafetyClass.SSS),
            runner.machine._previous_card_context,
        )

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
            in_page_evidence="old",
            transition_kind="card_change",
        )
        current = HeroAction(
            "next_card_new",
            (0, 0),
            source_page="英雄列表",
            in_page_evidence="new",
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
            in_page_evidence="original",
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
            in_page_evidence="hero-a",
        )
        new = HeroAction(
            "next_card_new",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=new",
            in_page_evidence="hero-a",
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
            in_page_evidence="hero-a",
        )
        hero_b = HeroAction(
            "next_card_b",
            (1800, 591),
            source_page="英雄列表",
            reason="当前英雄为SSS，跳过，详情指纹=b",
            in_page_evidence="hero-b",
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
            in_page_evidence="slots=0;rows=450,600",
            transition_kind="material_change",
        )
        unchanged = HeroAction(
            "add_material_0_2",
            (0, 0),
            in_page_evidence="slots=0;rows=450,600",
        )
        changed = HeroAction(
            "add_material_1_1",
            (0, 0),
            in_page_evidence="slots=1;rows=600",
        )

        self.assertFalse(
            runner._material_transition_completed(previous, unchanged)
        )
        self.assertTrue(
            runner._material_transition_completed(previous, changed)
        )

    def test_material_transition_survives_a_silent_next_frame(self):
        """判据沉默（这一帧生不出动作）时，转场仍要能判出成功。

        复刻 2026-10-04 07:22 的卡死形态：点完材料后，下一页 SSS 徽记落进死区
        ⇒ `next_action` 返回 None ⇒ 原来从动作对象取观察值取不到 ⇒ 转场**永远**
        判不出成功，一路重试到超时。修法 = 机器每帧现算的
        `_current_material_observation` 兜底。
        """
        m = machine()
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        previous = HeroAction(
            "add_material_0_2",
            (0, 0),
            in_page_evidence="slots=0;rows=450,600",
            transition_kind="material_change",
        )

        # ① 现算值也没算出来（还没进过刻印页）⇒ 判不出成功，不许瞎认。
        m._current_material_observation = None
        self.assertFalse(runner._material_transition_completed(previous, None))

        # ② 槽位从 0 变 1 ⇒ 必须判成功，**哪怕 current_action 是 None**。
        m._current_material_observation = "slots=1;rows=600"
        self.assertTrue(runner._material_transition_completed(previous, None))

        # ③ 槽位没变、旧材料行还在 ⇒ 判不出（防止「有值就算成功」的过度放宽）。
        m._current_material_observation = "slots=0;rows=450,600"
        self.assertFalse(runner._material_transition_completed(previous, None))

        # ④ 旧材料行消失也算成功（与原口径一致）。
        m._current_material_observation = "slots=0;rows=600"
        self.assertTrue(runner._material_transition_completed(previous, None))

    def test_material_transition_does_not_downgrade_when_action_is_present(self):
        """动作对象在时**仍以它为准** —— 新兜底不许改变正常路径的口径。"""
        m = machine()
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )
        previous = HeroAction(
            "add_material_0_2",
            (0, 0),
            in_page_evidence="slots=0;rows=450,600",
            transition_kind="material_change",
        )
        unchanged = HeroAction(
            "add_material_0_2",
            (0, 0),
            in_page_evidence="slots=0;rows=450,600",
        )

        # 现算值说「变了」，但动作对象说「没变」⇒ 必须以动作对象为准，判不出。
        m._current_material_observation = "slots=1;rows=600"
        self.assertFalse(runner._material_transition_completed(previous, unchanged))


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

    def test_sss_abort_after_selection_is_a_valid_selection_outcome(self):
        """选卡后若安全检查要求退出，Runner 必须执行退出而非卡在旧选卡契约。"""
        runner = HeroSynthRunner(
            machine(verify_filter=True), Runtime(lambda: None, lambda *_: None)
        )
        selected = HeroAction(
            "select_transmit_card_502",
            (1720, 502),
            source_page="传送选择",
            target_pages=("传送选择",),
            in_page_evidence="grid=0",
            transition_kind="transmit_selection",
        )
        abort = HeroAction(
            "abort_transmit_sss_target",
            (30, 92),
            source_page="传送选择",
            target_pages=("英雄列表",),
        )

        self.assertTrue(runner._transition_completed(selected, abort, "传送选择"))

    def test_a_broken_picture_never_clears_the_unfinished_transmit_target(self):
        """画面在传送途中被换掉（连续性断了）⇒ **一个键都不许点**，但目标也不许清掉。

        ⚠️ 这条原来叫 ``test_recovery_does_not_clear_unfinished_transmit_target``：
        那时靠 ``_apply_recovery_state``（随恢复导航一起删除）把
        ``transmit_continuity_intact`` 置假。现在连续性由状态机自己守
        （``transmit_continuity_intact`` 默认假、只有本进程真的走到那一步才置真），
        所以这里**直接**把它置假 —— 这正是「换了进程 / 画面被换掉」的真实状态。

        清掉目标＝把玩家那一次没做完的传送忘掉，下一次会拿别的卡当目标重传；
        所以「拒绝点击」与「目标还在」必须在同一条用例里一起守。
        """
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING
        m.transmit_target_observation = "card-copy-7"
        m.transmit_continuity_intact = False

        self.assertIsNone(m.next_action(fixture("transmit_confirm")))
        self.assertIs(m.transmit_phase, TransmitPhase.CONFIRMING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_a_pending_transmit_without_continuity_is_fail_closed(self):
        """待完成的传送 + 连续性断了 ⇒ 英雄列表页也不许动手（先去把目标找回来）。"""
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = m._hero_identity_fingerprint(
            fixture("list_reddot")
        )
        m.transmit_continuity_intact = False

        self.assertIsNone(m.next_action(fixture("list_reddot")))

    def test_a_broken_picture_blocks_transmit_selection_and_confirmation(self):
        """连续性断了 ⇒ 传送选择页 / 确认页上的每一处副作用都不许发生。"""
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
                m.transmit_continuity_intact = False

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

    def test_transmit_highlight_tolerates_short_gap_from_hero_art(self):
        m = machine(verify_filter=True)
        interrupted = fixture("transmit_select").copy()
        x, y, w, _ = m._TRANSMIT_HIGHLIGHT_ZONE
        interrupted[y + 295 : y + 300, x : x + w] = 0

        self.assertIsNotNone(m._transmit_target_card(interrupted))
        self.assertTrue(m._transmit_page_ready(interrupted))

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
    def test_template_builder_has_no_legacy_pc_directory_switch(self):
        source = inspect.getsource(build_hero_templates)

        self.assertNotIn("templates" + "_pc", source)

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
        # 「SSS 材料」徽记两张候选：前排展开的大卡按 100% 画、后排被压暗的小卡约 90%。
        self.assertEqual((38, 64), templates.sss_material[0].shape[:2])
        self.assertEqual((34, 58), templates.sss_material[1].shape[:2])
        machine_value = HeroSynthStateMachine(templates)
        self.assertGreaterEqual(machine_value._RATING_SSS_MIN, 0.90)
        self.assertEqual(0.80, machine_value._SSS_MATERIAL_MIN)

    def test_sss_material_candidates_match_the_evidence_profile(self):
        """候选模板必须与证据画像**逐条对得上**（数量 + 文件名 + 像素）。

        防的是「画像说有两张、加载器只读一张」这种口径漂移 —— 本路线踩过同类坑
        （`_OPTIONAL_TEMPLATES` 与加载器并行维护）。路径只留证据画像一个来源。
        """
        templates = build_hero_templates(TEMPLATES)
        atom = build_hero_evidence(TEMPLATES).atom("sss_material")
        declared = (atom.template_path, *atom.alt_template_paths)

        self.assertEqual(len(declared), len(templates.sss_material))
        for relative, loaded in zip(
            declared, templates.sss_material, strict=True
        ):
            self.assertTrue((TEMPLATES / relative).is_file(), relative)
            self.assertTrue(
                np.array_equal(loaded, load_template(str(TEMPLATES / relative))),
                relative,
            )

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
    def test_current_hero_threshold_policy(self):
        """英雄合成门槛只有模拟器基线一档。

        以前这里还对比一份「PC 专用」证据档案（filter 类锚点整体放低 0.10）。
        那套放宽是拿模拟器图认 PC 画面的止痛药；平台差异现在由
        ``templates/hero/pc/*.png`` 承担，所以只剩这一档。
        """
        profile = build_hero_evidence(TEMPLATES)

        self.assertEqual(
            0.75, profile.atom("filter_level_label").threshold
        )
        self.assertEqual(
            0.75, profile.atom("filter_attribute_label").threshold
        )
        self.assertEqual(0.86, profile.atom("filter_star3_unselected").threshold)
        self.assertEqual(0.90, profile.atom("rating_sss").threshold)
        self.assertEqual(0.80, profile.atom("sss_material").threshold)
        self.assertEqual(0.90, profile.atom("transmit_reward_title").threshold)

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
        self.assertTrue(action.reason.startswith("英雄信息页已确认，打开三星筛选；"))
        self.assertIn("级别=", action.reason)
        self.assertIn("属性=", action.reason)

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

    def test_adjacent_same_name_sss_then_no_dot_opens_transmit(self):
        """同名 3S 本体后的无红点副本必须走传送，而非普通跳过。"""
        m = machine(verify_filter=True)
        m._previous_card_context = ("hero-abc", SafetyClass.SSS)
        with (
            patch.object(m, "_hero_identity_fingerprint", return_value="hero-abc"),
            patch.object(m, "_classify_current_hero", return_value=SafetyClass.NON_SSS),
            patch.object(m, "_red_dot_present", return_value=False),
        ):
            action = m.next_action(fixture("list_no_reddot"))

        self.assertEqual("open_transmit_for_current_card", action.name)
        self.assertIs(m.transmit_phase, TransmitPhase.OPENING)
        self.assertEqual("hero-abc", m.transmit_target_observation)

    def test_adjacent_same_name_transmit_reason_records_business_evidence(self):
        m = machine(verify_filter=True)
        m._previous_card_context = ("hero-abc", SafetyClass.SSS)
        with (
            patch.object(m, "_hero_identity_fingerprint", return_value="hero-abc"),
            patch.object(m, "_classify_current_hero", return_value=SafetyClass.NON_SSS),
            patch.object(m, "_red_dot_present", return_value=False),
        ):
            action = m.next_action(fixture("list_no_reddot"))

        self.assertIn("上一张=SSS", action.reason)
        self.assertIn("同名=是", action.reason)
        self.assertIn("当前无红点副本", action.reason)

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

    def test_sss_card_does_not_record_context_before_card_switch_is_confirmed(self):
        m = machine(verify_filter=True)
        with patch.object(m, "_hero_identity_fingerprint", return_value="hero-abc"):
            settled_next(m, fixture("list_grey_3s"))

        self.assertIsNone(m._previous_card_context)

    def test_different_name_consumes_sss_context_before_later_cards(self):
        m = machine(verify_filter=True)
        m._previous_card_context = ("hero-abc", SafetyClass.SSS)
        with (
            patch.object(m, "_hero_identity_fingerprint", return_value="hero-def"),
            patch.object(m, "_classify_current_hero", return_value=SafetyClass.NON_SSS),
            patch.object(m, "_red_dot_present", return_value=False),
        ):
            action = m.next_action(fixture("list_no_reddot"))

        self.assertTrue(action.name.startswith("next_card"))
        self.assertIsNone(m._previous_card_context)

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
        match = find_template(
            screen,
            m.templates.sss_material[0],
            -1.0,
            region=m._MATERIAL_SSS_REGION,
            reference_size=m._REFERENCE_SIZE,
        )
        self.assertIsNotNone(match)
        height, width = m.templates.sss_material[0].shape[:2]
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

        self.assertEqual(m._hero_identity_fingerprint(screen), action.in_page_evidence)
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
        self.assertEqual(first.in_page_evidence, second.in_page_evidence)

    def test_confirmed_motion_is_consumed_after_switch(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True), Runtime(lambda: None, lambda *_: None)
        )
        previous = HeroAction(
            "next_card_old",
            (0, 0),
            in_page_evidence="name=A|selected_row=1",
        )
        current = HeroAction(
            "next_card_new",
            (0, 0),
            in_page_evidence="name=A|selected_row=1",
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
            in_page_evidence="name=A|selected_row=1",
        )
        current = HeroAction(
            "next_card_old",
            (0, 0),
            in_page_evidence="name=A|selected_row=1",
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
    def test_live_equipment_subpage_switches_to_hero_information(self):
        screen = fixture("live_equipment_subpage_20260825")
        m = machine()

        self.assertTrue(m._equipment_tab_selected(screen))
        self.assertFalse(m._hero_info_tab_selected(screen))

        action = m.next_action(screen)

        self.assertIsNotNone(action)
        self.assertEqual("select_hero_info_tab", action.name)
        self.assertIn("先切回英雄信息页", action.reason)

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

    def test_orange_hero_art_without_material_card_is_not_an_up_material(self):
        """英雄武器扫过 Up 区时，没有右侧卡片轮廓就不能点击。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_added").copy()
        x, y, w, h = m._MATERIAL_CARD_ZONE
        screen[y : y + h, x : x + w] = 0
        badge_source = fixture("imprint_up_cards_no_sss")
        x, y, w, h = m._UP_BADGE_ZONE
        screen[y : y + h, x : x + w] = badge_source[y : y + h, x : x + w]

        self.assertTrue(m._up_badge_rows(screen))
        self.assertIsNone(m._find_visible_material_card(screen))
        self.assertIsNone(m._find_up_card(screen))

        self.assertIsNone(m.next_action(screen))
        action = m.next_action(screen)
        self.assertEqual("start_synthesis", action.name)

    def test_initial_ordinary_card_without_up_badge_is_still_added(self):
        """初始空槽时，Up 动画漏识别不能把可用普通材料当成空页。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        x, y, w, h = m._UP_BADGE_ZONE
        screen[y : y + h, x : x + w] = 0

        action = m.next_action(screen)

        self.assertIsNotNone(action)
        self.assertTrue(action.name.startswith("add_material_"))
        self.assertEqual("刻印加材料", action.source_page)
        self.assertIn("普通材料卡", action.reason)

    def test_initial_unknown_material_never_clicks_or_returns(self):
        """有卡但 SSS 评级处在不确定区时只能等待，不能点击或退出。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        x, y, w, h = m._UP_BADGE_ZONE
        screen[y : y + h, x : x + w] = 0

        with patch.object(
            m, "_classify_material_page", return_value=SafetyClass.UNKNOWN
        ):
            for _ in range(4):
                self.assertIsNone(m.next_action(screen))

        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_zero_slots_and_zero_cost_without_a_card_never_means_empty_page(self):
        """空槽和费用 0 不是材料列表为空的证据，连续观察也不得返回。"""
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        screen[390:990, 1370:1982] = 0

        for _ in range(4):
            self.assertIsNone(m.next_action(screen))

        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_sss_material_aborts_imprint_before_clicking_material(self):
        m = machine()
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD
        action = m.next_action(sss_only_material_page())
        self.assertEqual("abort_imprint_to_transmit", action.name)

    def test_sss_material_still_aborts_when_up_badge_is_not_visible(self):
        """SSS 检测独立于 Up 标记，不能落入普通卡轮廓兜底。"""
        m = machine()
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_sss_material").copy()
        x, y, w, h = m._UP_BADGE_ZONE
        screen[y : y + h, x : x + w] = 0

        action = m.next_action(screen)

        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertFalse(action.name.startswith("add_material_"))

    def test_behind_card_sss_material_is_recognized_by_its_own_candidate(self):
        """「后排小卡」上的 SSS 徽记只有前排的 ~90%，必须照样认出来。

        现场（夹具 ``imprint_sss_material_behind_card_20261004``，2026-10-04 07:22
        转场超时那一刻）：前排展开的大卡是普通材料，**SSS 徽记盖在它后面那张被压暗
        的小卡上**，整体比前排小约 10%。

        只按前排剪的那张模板在这一帧只量到 **0.5957** —— 高于「明确排除」线 0.55、
        低于 SSS 门槛 0.80，正好落进 0.55~0.80 的不确定带。后果不是「点错」而是
        「沉默」：`next_action()` 直接返回 None，不打分、不报警；转场验收要靠
        「下一个动作」的观察值来比对，拿不到 ⇒ 90 秒转场超时 ⇒ 回大厅又认不出页面
        ⇒ 整条流程停在刻印页直到人手动停。同形态在 2026-09-03 14:05 就有，跨了一个月。

        ⚠️ 断言必须写到**依据**（分数 / 分类），只断言「动作对不对」抓不住判据失效：
        这条路径在降级时**照样能返回 None 而不报错**。

        ⚠️ 模板与夹具刻意**跨帧**：候选模板从 ``..._behind_card_20261003`` 上剪，
        这条断言用 ``..._20261004`` 验收（两帧是不同次抓屏，逐像素并不相同）。
        """
        screen = fixture("imprint_sss_material_behind_card_20261004")
        m = machine()
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD

        score = m._material_page_sss_score(screen)

        self.assertGreaterEqual(
            score, m._SSS_MATERIAL_MIN, f"整页 SSS 分数 {score:.4f} 未过阈"
        )
        self.assertIs(m._classify_material_page(screen), SafetyClass.SSS)
        action = m.next_action(screen)
        self.assertIsNotNone(action, "判出 SSS 之后仍然不出手")
        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertFalse(action.name.startswith("add_material_"))
        self.assertEqual("刻印SSS材料", m._confirmed_page)

    def test_ordinary_material_pages_stay_out_of_sss_after_adding_candidate(self):
        """加了「后排小卡」候选之后，普通材料页一张都不许被误判成 SSS。

        只证明「认得准」不够：候选模板比原来那张小 10%，越小越容易误伤。
        这里锁住的是**负样本的判定结果**（不是分数高低）。
        """
        m = machine()

        for name in (
            "imprint_up_cards_no_sss",
            "imprint_up_one_card_no_sss",
            "imprint_added",
            "imprint_after_synth",
        ):
            with self.subTest(fixture=name):
                screen = fixture(name)
                self.assertIs(
                    m._classify_material_page(screen),
                    SafetyClass.NON_SSS,
                    f"{name} 被误判为 SSS 或落入不确定带",
                )

    def test_small_card_sss_material_is_recognized_by_multiscale(self):
        """徽记被画到**比模板小 20%** 时也必须认出来（2026-10-04 08:36 现场）。

        现场：进「刻印加材料」页后右侧三张材料卡，SSS 徽记在**最下面那张被压暗的
        小卡**上 —— 整张卡连徽记只有模板的约 **80%**（核心宽 45，模板 56）。
        只按原尺寸匹配量到 **0.5928**，落进 0.55~0.80 死区 ⇒ ``next_action()``
        返回 None、日志一行不出、刻印页干等 90 秒超时（``timeout_imprint_add``）。

        为什么不能靠「再补一张模板」解决：同一枚徽记已实测到核心宽 **56 / 50 / 45**
        三档，画多大取决于它排在材料列表第几位，而列表里有几张材料是动态的
        ⇒ 档位补不完。这里锁的是**多尺度扫描**这条路。

        ⚠️ 断言写到**依据**：除了断言判成 SSS，还断言「只按 1.00 倍确实量不到」——
        否则把多尺度退化回单尺度时，这条测试会照样绿（正是上次没抓到的原因）。
        """
        screen = fixture("imprint_sss_material_small_card_20261004")
        m = machine()
        m._active_card_observation = "test-card"
        m.state = HeroSynthState.IMPRINT_ADD

        inset = m._SSS_TEMPLATE_INSET
        region = m._region("sss_material")
        single_scale = max(
            match.score
            for candidate in m.templates.sss_material
            if (
                match := find_template(
                    screen,
                    candidate[inset:-inset, inset:-inset],
                    -1.0,
                    region=region,
                    reference_size=m._REFERENCE_SIZE,
                )
            )
            is not None
        )
        score = m._material_page_sss_score(screen)

        self.assertLess(
            single_scale,
            m._SSS_MATERIAL_MIN,
            f"1.00 倍档竟然量到 {single_scale:.4f}，这条夹具已经不是小卡现场了",
        )
        self.assertGreaterEqual(
            score, m._SSS_MATERIAL_MIN, f"多尺度 SSS 分数 {score:.4f} 仍未过阈"
        )
        self.assertIs(m._classify_material_page(screen), SafetyClass.SSS)
        action = m.next_action(screen)
        self.assertIsNotNone(action, "判出 SSS 之后仍然不出手")
        self.assertEqual("abort_imprint_to_transmit", action.name)
        self.assertFalse(action.name.startswith("add_material_"))

    def test_every_known_badge_size_is_recognized(self):
        """已实测到的每一档徽记尺寸都要认出来：核心宽 56 / 50 / 45。

        这不是「三种长相」而是**同一枚徽记被画成多大**。档位随它在材料列表里排
        第几位变化，所以「有几种」由页面当时有几张材料决定 —— 这条测试是拿全部
        已知档位一起兜底，新增一档就补一条 ``subTest``。
        """
        m = machine()
        cases = (
            ("imprint_sss_material", "核心宽 56：展开的大卡，模板原尺寸"),
            ("imprint_sss_material_behind_card_20261003", "核心宽 50：后排被压暗的小卡"),
            ("imprint_sss_material_behind_card_20261004", "核心宽 50：同上，另一次抓屏"),
            ("imprint_sss_material_small_card_20261004", "核心宽 45：列表第三张，最小"),
        )

        for name, why in cases:
            with self.subTest(fixture=name, why=why):
                screen = fixture(name)
                score = m._material_page_sss_score(screen)
                self.assertGreaterEqual(
                    score, m._SSS_MATERIAL_MIN, f"{name}（{why}）只量到 {score:.4f}"
                )
                self.assertIs(
                    m._classify_material_page(screen), SafetyClass.SSS, name
                )

    def test_multiscale_does_not_push_negative_pages_into_sss(self):
        """多尺度放大了判据的宽容度，但一张负样本都不许被推进 SSS。

        尺度越小越容易在随机纹理上蹭出高分，所以要同时锁住两处：
        ① 材料页负样本；② **传送页** —— 传送页调用的是同一个打分函数（只是区域
        不同），历史上是最容易被误伤的地方（``transmit_selected`` 换个区域就能
        蹭到 0.96）。

        ⚠️ 传送页必须走**生产口径**（``_transmit_target_card`` 定出的真实卡片 y），
        不能自己穷举 y 去量 —— 穷举会把区域挪到能蹭到别处内容的位置，量出假误判。
        """
        m = machine()

        for name in (
            "imprint_up_cards_no_sss",
            "imprint_up_one_card_no_sss",
            "imprint_added",
            "imprint_after_synth",
            "imprint_sss_warning_popup",
            "imprint_result_popup",
        ):
            with self.subTest(fixture=name):
                self.assertIs(
                    m._classify_material_page(fixture(name)),
                    SafetyClass.NON_SSS,
                    f"{name} 被多尺度推进了 SSS 或不确定带",
                )

        for name in ("transmit_select", "transmit_selected"):
            with self.subTest(fixture=name):
                screen = fixture(name)
                card = m._transmit_target_card(screen)
                self.assertIsNotNone(card, f"{name} 定位不到高亮卡")
                self.assertIs(
                    m._classify_transmit_target(screen, card),
                    SafetyClass.NON_SSS,
                    f"{name} 被多尺度推进了 SSS",
                )

    def test_missing_sss_template_is_refused_at_construction(self):
        """失去 SSS 检测能力的状态**根本构造不出来**，不是「降级成未知继续跑」。

        2026-10-03 起 `sss_material` 是必需模板：缺了在构造期就 `ValueError`。
        它以前是可选的，缺了就静静判 `UNKNOWN` —— 判据没了却不报错，
        正是「判据静默降级」这一类（同一天装备子页就是这么丢了半年）。
        """
        templates = replace(build_hero_templates(TEMPLATES), sss_material=None)

        with self.assertRaises(ValueError) as caught:
            HeroSynthStateMachine(templates)

        self.assertIn("sss_material", str(caught.exception))

    def test_unmeasurable_sss_score_is_unknown_not_non_sss(self):
        """量不到 SSS 分数（哨兵值 -1.0）时必须判未知，不能当成「非 SSS」放行。

        这是上面那条的**运行时**孪生兄弟：模板都在，但这一帧一个候选位置都没匹配上。
        「模板缺失」已经在构造期被拦了，这里守的是「量到了、但没量着」。
        """
        m = machine()
        screen = fixture("imprint_sss_material")

        with patch.object(m, "_material_page_sss_score", return_value=-1.0):
            self.assertIs(m._classify_material_page(screen), SafetyClass.UNKNOWN)

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

    def test_pending_transmit_uses_continuous_return_when_identity_differs(self):
        m = machine(verify_filter=True)
        m.pending_transmit_target = True
        m.transmit_target_observation = "identity-before-imprint"

        action = m.next_action(fixture("list_reddot"))

        self.assertEqual("open_transmit_for_current_card", action.name)
        self.assertIn("连续返回", action.reason)
        self.assertIn("保存身份=identity-before-imprint", action.reason)
        self.assertIn("当前身份=", action.reason)

    def test_abort_return_ignores_green_false_positive_on_ready_hero_list(self):
        m = machine(verify_filter=True)
        m.pending_transmit_target = True
        m.transmit_target_observation = "identity-before-imprint"
        m.state = HeroSynthState.IMPRINT_ABORTING

        with (
            patch.object(m, "_green_button_present", return_value=True),
            patch.object(m, "_imprint_slots_present", return_value=False),
        ):
            action = m.next_action(fixture("list_reddot"))

        self.assertEqual("open_transmit_for_current_card", action.name)
        self.assertEqual("英雄列表", m._confirmed_page)

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
                ("合成后刻印页", "英雄列表"),
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

    def test_close_result_transition_accepts_direct_hero_list(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_CONFIRM
        previous = m.next_action(fixture("imprint_result_popup"))

        current = m.next_action(fixture("list_no_reddot"))

        runner = HeroSynthRunner(
            m, Runtime(lambda: None, lambda *_: None), sleep=lambda _: None
        )
        self.assertIs(m.state, HeroSynthState.HERO_LIST)
        self.assertEqual("英雄列表", m._confirmed_page)
        self.assertTrue(
            runner._transition_completed(previous, current, "英雄列表")
        )

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

    def test_transmit_refuses_highlighted_sss_card_when_grid_is_empty(self):
        screen = fixture("transmit_select")
        # 右侧第二格是空槽；用它覆盖第一格，构造“尚未选入材料”的画面。
        screen[370:490, 110:530] = screen[370:490, 530:950]
        sss = cv2.imread(
            str(TEMPLATES / "hero" / "sss_material.png"), cv2.IMREAD_COLOR
        )
        sss = cv2.cvtColor(sss, cv2.COLOR_BGR2RGB)
        screen[480:518, 1750:1814] = sss
        m = machine()
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True
        self.assertFalse(m._transmit_grid_filled(screen))
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

    def test_filled_transmit_grid_ignores_next_highlighted_sss_card(self):
        """选中目标后高亮跳到下一张 SSS 时，必须继续传送已入格副本。"""
        m = machine()
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True

        with patch.object(
            m, "_classify_transmit_target", return_value=SafetyClass.SSS
        ):
            action = m.next_action(fixture("transmit_selected"))

        self.assertEqual("start_transmit", action.name)
        self.assertEqual("grid=1", action.in_page_evidence)

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

    def test_visible_transmit_confirm_popup_can_be_clicked_again(self):
        """首次确认点击未生效时，弹窗仍在就必须允许安全重试。"""
        m = machine()
        m.state = HeroSynthState.TRANSMIT_CONFIRM
        m.transmit_phase = TransmitPhase.CONFIRMING
        m.transmit_target_observation = "saved-card"
        m.transmit_continuity_intact = True

        action = m.next_action(fixture("transmit_confirm"))

        self.assertEqual("confirm_transmit", action.name)

    def test_transmit_confirm_retry_interval_is_five_seconds(self):
        runner = HeroSynthRunner(
            machine(), Runtime(lambda: None, lambda *_: None)
        )

        self.assertEqual(5, runner._action_retry_seconds("confirm_transmit"))

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


def _is_empty_literal(node: ast.AST) -> bool:
    """静态判断一个表达式是不是「空」（``""`` / ``()`` / ``[]``）。

    只认字面量：透传点（``_simulator_transition_action``）把契约当**必填关键字**
    收下来再转手，用的是变量，静态看不出空不空 —— 但那里没有默认值，传不进来
    就 ``TypeError``，所以不需要静态兜。
    """
    if isinstance(node, ast.Constant):
        return not node.value
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return not node.elts
    return False


def hero_action_contract_violations(source: str) -> list[tuple[int, str]]:
    """列出源码里缺转场契约的 ``HeroAction(...)`` 构造点（行号 + 缺什么）。

    契约口径同 ``runner_base._require_transition_contract``：``source_page`` 非空，
    且 ``target_pages`` / ``in_page_evidence`` 至少一个非空。
    """
    violations: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "HeroAction"):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        problems = []
        source_page = keywords.get("source_page")
        if source_page is None or _is_empty_literal(source_page):
            problems.append("source_page")
        targets = keywords.get("target_pages")
        evidence = keywords.get("in_page_evidence")
        if not (
            (targets is not None and not _is_empty_literal(targets))
            or (evidence is not None and not _is_empty_literal(evidence))
        ):
            problems.append("target_pages/in_page_evidence")
        if problems:
            violations.append((node.lineno, "、".join(problems)))
    return violations


class TransitionContractSwitchTests(unittest.TestCase):
    """转场契约开关已打开（2026-10-04），且同页动作**真的有**验收依据。"""

    def test_switch_is_on_and_the_route_left_the_exempt_list(self):
        from auto_game_unified.games.epic7.modes import TRANSITION_EXEMPT

        self.assertIs(True, HeroSynthRunner._REQUIRE_TRANSITION_CONTRACT)
        self.assertNotIn(
            "hero_synthesis",
            TRANSITION_EXEMPT,
            "开关开了就不该再挂在豁免名单里（二选一，不能两边都占）",
        )

    def test_switch_rejects_actions_without_a_contract(self):
        """反向喂违规动作：缺哪样点名哪样，不许静默放行。"""
        runner = HeroSynthRunner(
            machine(),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )

        with self.assertRaisesRegex(RuntimeError, "source_page"):
            runner._require_transition_contract(
                HeroAction("x", (0, 0), source_page="", target_pages=("英雄列表",))
            )
        with self.assertRaisesRegex(RuntimeError, "in_page_evidence"):
            runner._require_transition_contract(
                HeroAction("y", (0, 0), source_page="刻印加材料", target_pages=())
            )
        # 同页动作**带证据**才算合法 —— 这正是本次对齐要解决的问题：
        # 以前它们靠 target_pages 里塞当前页过检查，契约形同虚设。
        runner._require_transition_contract(
            HeroAction(
                "z",
                (0, 0),
                source_page="刻印加材料",
                target_pages=(),
                in_page_evidence="slots=1;rows=600",
            )
        )

    def test_material_actions_now_carry_in_page_evidence_on_real_fixtures(self):
        """真夹具上：``material_change`` 动作必须带 ``in_page_evidence``。

        这是「契约真管到那 12 个同页动作」的现场证据 —— 只断言开关值是抓不住的，
        得看到证据串真的填进去了。
        """
        found = 0
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "epic7_hero"
        for path in sorted(fixture_dir.glob("*.png")):
            screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            for state in HeroSynthState:
                probe = machine()
                probe.state = state
                try:
                    action = probe.next_action(screen)
                except RuntimeError:
                    continue
                if action is None or action.transition_kind != "material_change":
                    continue
                found += 1
                with self.subTest(fixture=path.name, state=state.value):
                    self.assertTrue(
                        action.in_page_evidence,
                        f"{action.name} 是同页动作却没有 in_page_evidence",
                    )

        self.assertGreater(found, 0, "没有扫到任何 material_change 动作，素材或状态改过了")


class GuardTests(unittest.TestCase):
    def test_hero_identity_ignores_animation_to_the_right_of_name(self):
        original = fixture("list_no_reddot")
        animated = original.copy()
        animated[165:310, 425:575] = np.roll(
            animated[165:310, 425:575], 24, axis=0
        )
        m = machine(verify_filter=True)

        self.assertEqual(
            m._hero_identity_fingerprint(original),
            m._hero_identity_fingerprint(animated),
        )

    def test_narrow_hero_identity_still_distinguishes_recorded_heroes(self):
        m = machine(verify_filter=True)

        self.assertNotEqual(
            m._hero_identity_fingerprint(fixture("list_no_reddot")),
            m._hero_identity_fingerprint(fixture("list_grey_3s")),
        )

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

    def test_every_hero_action_construction_declares_its_transition_contract(self):
        """每个 ``HeroAction`` 构造点都必须带转场契约（来源页 + 到哪去）。

        为什么用静态检查而不是跑一遍夹具：跑夹具只覆盖**采样得到**的分支 ——
        2026-10-03 审计发现的那 3 个缺契约动作（两处 ``open_filter``、刻印页那个
        裸 ``return back``）跑遍 25 张夹具 × 全部状态都进不去，它们要特定的内部
        上下文才触发。真出问题的恰恰是这些跑不到的角落。
        """
        source = (ROOT / "games" / "epic7" / "hero_synthesis.py").read_text(
            encoding="utf-8"
        )

        # 先确认确实扫到了构造点，免得正则/AST 失配后「零违规」变成假绿。
        self.assertGreaterEqual(source.count("HeroAction("), 6)
        self.assertEqual([], hero_action_contract_violations(source))

    def test_the_contract_checker_flags_a_blind_action(self):
        """反向：违规定义喂给检查器必须被点名，否则上面那条测试是假绿。"""
        source = (
            "def f():\n"
            "    return HeroAction('x', (1, 2), source_page='', target_pages=())\n"
        )

        violations = hero_action_contract_violations(source)

        self.assertEqual(
            [(2, "source_page、target_pages/in_page_evidence")], violations
        )

    def test_every_judgement_anchor_refuses_a_missing_template(self):
        """每个判据锚点缺模板都必须在**构造期**报错，且错误消息点名是哪个。

        反向输入：把每个锚点轮流置 ``None`` —— 就是旧代码里 ``if path.exists() else
        None`` 在模板被删时给出的结果。名册取 ``evidence.atoms``（区域表/阈值表
        的权威来源）。

        为什么值得守：这 9 张里最危险的三组是覆盖层判据
        （``sss_material_warning_*`` / ``imprint_result_*`` / ``transmit_reward_*``），
        缺了会让「覆盖层必须先关掉」**静默失效**、点到覆盖层底下 —— 而合成
        消耗材料，不可逆。跑夹具几乎看不出来，所以必须在这里拦。
        """
        templates = build_hero_templates(TEMPLATES)

        for anchor in templates.evidence.atoms:
            with self.assertRaises(ValueError, msg=anchor) as caught:
                HeroSynthStateMachine(replace(templates, **{anchor: None}))
            self.assertIn(anchor, str(caught.exception))

    def test_sss_material_candidate_group_refuses_an_empty_tuple(self):
        """候选模板**整组为空**也算「判据不存在」，同样要在构造期报错。

        一个锚点现在可能登记多张候选模板（元组）。只写 ``value is None`` 拦不住
        空元组 —— 那会让判据以「一张候选都没有」的形态静默消失，正是这一类缺陷。
        """
        templates = build_hero_templates(TEMPLATES)

        with self.assertRaises(ValueError) as caught:
            HeroSynthStateMachine(replace(templates, sss_material=()))

        self.assertIn("sss_material", str(caught.exception))

    def test_an_emptied_scale_set_stops_recognizing_the_small_badge(self):
        """把尺度档位收成只剩 1.00 ⇒ 最小那一档**立刻认不出来**。

        这不是重复 `test_small_card_...`：那条证明「现在能认」，这条证明
        「能认**是因为**多尺度」—— 把尺度集合退化掉，它必须变红。
        """
        screen = fixture("imprint_sss_material_small_card_20261004")
        m = machine()
        m._SSS_TEMPLATE_SCALES = (1.00,)

        score = m._material_page_sss_score(screen)

        self.assertLess(
            score,
            m._SSS_MATERIAL_MIN,
            f"尺度集合只剩 1.00 还量到 {score:.4f}，这条夹具已不能再证明多尺度有用",
        )

    def test_sss_template_scales_cover_the_base_size_and_stay_in_range(self):
        """尺度档位：非空、含 1.00、落在 (0, 1]、从大到小。

        空档位 == 多尺度整个消失，判据退回「只按原尺寸量」（08:36 的故障形态）；
        丢掉 1.00 == 模板原尺寸那一档没人覆盖。两条都只能靠人记得，所以要钉住。
        """
        scales = HeroSynthStateMachine._SSS_TEMPLATE_SCALES

        self.assertTrue(scales, "SSS 尺度档位为空，多尺度扫描等于没有")
        self.assertIn(1.00, scales, "尺度档位里没有 1.00，模板原尺寸那一档没人覆盖")
        self.assertTrue(
            all(0.0 < scale <= 1.0 for scale in scales),
            f"尺度档位必须落在 (0, 1]，实际 {scales}",
        )
        self.assertEqual(
            tuple(sorted(scales, reverse=True)), scales, "尺度档位应当从大到小"
        )

    def test_back_arrow_lookup_returns_a_point_and_not_an_action(self):
        """返回箭头只给坐标：契约必须由调用方声明，不能自带一个裸动作。

        历史上它返回一个裸 ``HeroAction``，于是有个调用点顺手 ``return back`` ——
        那个「返回」点完不回头看，没生效也没人知道。
        """
        m = machine(verify_filter=True)

        point = m._back_point(fixture("imprint_after_synth"))

        self.assertIsInstance(point, tuple)
        self.assertEqual(2, len(point))


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
    def test_unconfirmed_hero_subpage_logs_tab_evidence_without_flooding(self):
        screen = fixture("live_equipment_subpage_20260825").copy()
        m = machine()
        for x, y, w, h in (m._HERO_INFO_TAB_ZONE, m._EQUIPMENT_TAB_ZONE):
            screen[y : y + h, x : x + w] = 0
        clock = FakeClock()
        logs = []
        runner = HeroSynthRunner(
            m,
            Runtime(
                lambda: screen,
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )
        stable = StableObservation(required=2)

        self.assertIs(runner._stable_next_action(screen, stable), NOT_STABLE)
        self.assertIsNone(runner._stable_next_action(screen, stable))
        self.assertIsNone(runner._stable_next_action(screen, stable))
        clock.sleep(10)
        self.assertIsNone(runner._stable_next_action(screen, stable))

        evidence = [log for log in logs if "英雄子页等待" in log]
        self.assertEqual(2, len(evidence))
        self.assertIn(
            "当前子页=未确认 英雄信息蓝色像素=0 装备蓝色像素=0",
            evidence[0],
        )

    def test_imprint_timeout_logs_material_detector_evidence(self):
        logs = []
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        screen = fixture("imprint_up_cards_no_sss").copy()
        screen[390:990, 1370:1465] = 0
        x, y, w, h = m._UP_STRIP_ZONE
        screen[y : y + h, x : x + w] = 0
        m._last_screen = screen
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: screen, lambda _: None, emit=logs.append),
            sleep=lambda _: None,
        )

        runner._log_settled_timeout(HeroSynthState.IMPRINT_ADD, "diagnostic.png")

        joined = "\n".join(logs)
        self.assertIn(
            "刻印页超时 诊断=diagnostic.png 完整页面=1 绿色按钮=1 "
            "槽位结构=1 已填槽位=0 费用非零=0 Up材料=未识别",
            joined,
        )
        self.assertIn("材料卡=card", joined)
        self.assertIn("SSS页评级=non_sss", joined)
        self.assertIn("SSS最高分=", joined)
        self.assertIn("未知Up材料=0", joined)

    def test_imprint_add_wait_emits_a_ten_second_heartbeat(self):
        """「刻印加材料」页判不出结果时，日志必须**当场出声**，不能空等 90 秒。

        2026-10-04 08:36 现场：08:34:30 进页 → 08:36:02 超时，中间**一行日志都没有** ——
        判据落进死区后 `next_action()` 直接返回 None（不出手、不打分、不报警），
        人只能事后翻现场帧才知道卡在哪一档。这条心跳把「卡住」变成立刻可见。

        复现方式：把尺度档位收成 `(1.00,)`，那张 45 档现场帧就落回 0.55~0.80 死区 ——
        和 08:36 卡死时**同一个形态**（`SSS页评级=unknown`、`SSS最高分≈0.59`、无动作）。

        ⚠️ 断言写到**依据**（评级 / 分数确实进了日志），不是「有没有日志」——
        心跳打出来但内容是空的，等于没打。
        """
        clock = FakeClock()
        logs = []
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        m._SSS_TEMPLATE_SCALES = (1.00,)
        screen = fixture("imprint_sss_material_small_card_20261004")
        runner = HeroSynthRunner(
            m,
            Runtime(
                lambda: screen,
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )
        stable = StableObservation(required=2)

        # 首帧只记基线（返回 NOT_STABLE），第二帧才是「稳定但没动作」。
        runner._stable_next_action(screen, stable)
        self.assertIsNone(
            runner._stable_next_action(screen, stable),
            "这张画面本该判不出结果（死区），素材已经不是卡死形态了",
        )

        heartbeat = [log for log in logs if "刻印页等待" in log]
        self.assertTrue(heartbeat, "\n".join(logs))
        self.assertIn("SSS页评级=unknown", heartbeat[0])
        self.assertIn("SSS最高分=0.59", heartbeat[0])
        self.assertIn("槽位结构=1", heartbeat[0])

        settled = len(heartbeat)
        runner._stable_next_action(screen, stable)
        self.assertEqual(
            settled,
            len([log for log in logs if "刻印页等待" in log]),
            "10 秒内重复打了心跳",
        )

        clock.sleep(10)
        runner._stable_next_action(screen, stable)
        self.assertEqual(
            settled + 1,
            len([log for log in logs if "刻印页等待" in log]),
            "过了 10 秒却不再打心跳",
        )

    def test_silent_wait_saves_a_frame_once_and_survives_a_disk_failure(self):
        """等判据出货时留一张现场帧；只留首帧；存不下来也不许炸。

        判据沉默的形态是「什么都不做」⇒ 不会走到超时分支 ⇒ 一张图都不会留。
        2026-10-04 那次能挖出 0.593 纯属侥幸（它恰好超时了）；沉默若发生在转场
        验收里（走「重试 4 次」的正常路径），就彻底盲了。
        """
        from pathlib import Path as _Path
        import tempfile

        clock = FakeClock()
        logs = []
        m = machine()
        m.state = HeroSynthState.IMPRINT_ADD
        m._SSS_TEMPLATE_SCALES = (1.00,)
        screen = fixture("imprint_sss_material_small_card_20261004")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: screen,
                lambda _: None,
                emit=logs.append,
                monotonic=clock,
                diagnostic_dir=_Path(tmp),
            )
            runner = HeroSynthRunner(m, runtime, sleep=clock.sleep)
            stable = StableObservation(required=2)

            runner._stable_next_action(screen, stable)
            runner._stable_next_action(screen, stable)
            # 再等两轮（跨过 10 秒节流），帧仍然只该有一张。
            clock.sleep(10)
            runner._stable_next_action(screen, stable)
            clock.sleep(10)
            runner._stable_next_action(screen, stable)

            saved = sorted(_Path(tmp).glob("*judgement_silent*.png"))
            self.assertEqual(
                1, len(saved), f"应当只留首帧，实际 {[p.name for p in saved]}"
            )

        # ② 诊断目录没配 ⇒ 静默跳过，不许打断主循环。
        no_dir_logs = []
        m2 = machine()
        m2.state = HeroSynthState.IMPRINT_ADD
        m2._SSS_TEMPLATE_SCALES = (1.00,)
        runner2 = HeroSynthRunner(
            m2,
            Runtime(
                lambda: screen,
                lambda _: None,
                emit=no_dir_logs.append,
                monotonic=clock,
            ),
            sleep=clock.sleep,
        )
        stable2 = StableObservation(required=2)
        runner2._stable_next_action(screen, stable2)
        self.assertIsNone(runner2._stable_next_action(screen, stable2))

    def test_transition_timeout_reports_expected_page_and_detector_evidence(self):
        clock = FakeClock()
        source = fixture("list_reddot")
        incomplete_target = fixture("transmit_select").copy()
        x, y, w, _ = HeroSynthStateMachine._TRANSMIT_HIGHLIGHT_ZONE
        incomplete_target[y + 285 : y + 310, x : x + w] = 0
        captures = iter([source, source])
        logs = []
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = m._hero_identity_fingerprint(source)
        m.transmit_continuity_intact = True
        with TemporaryDirectory() as tmp:
            runtime = Runtime(
                lambda: next(captures, incomplete_target),
                lambda _: None,
                emit=logs.append,
                diagnostic_dir=Path(tmp),
                monotonic=clock,
            )
            runner = HeroSynthRunner(m, runtime, sleep=clock.sleep)
            runner._TIMEOUT_SECONDS = {state: 3 for state in HeroSynthState}

            with self.assertRaisesRegex(
                RuntimeError,
                r"等待动作\[open_transmit_for_current_card\]目标画面\[传送选择\]超时",
            ):
                runner.run(max_cycles=1)

        output = "\n".join(logs)
        self.assertIn(
            "转场超时 动作=open_transmit_for_current_card 原页面=英雄列表 "
            "期望页面=传送选择 当前已确认页面=无",
            output,
        )
        self.assertIn(
            "传送页证据 自动选择=1.000 高亮卡=未识别 格子=1 绿色按钮=1",
            output,
        )

    def test_successful_card_transitions_do_not_arm_loop_recovery(self):
        """连续 16 次成功的同动作转场不许被当成「原地打转」。

        ⚠️ 2026-09-26 起这条不再靠「看 recovery 有没有被调」来断言 ——
        回大厅恢复那条通道整段删除了。现在只看两条：**抛的是什么错**
        （这里是测试自己喂完 preview 触发的 ``StopIteration``，不是循环检测）与
        **日志里有没有循环检测**。
        """
        clock = FakeClock()
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
        )
        runner.machine._confirmed_page = "英雄列表"
        actions = [
            HeroAction(
                f"next_card_{index}",
                (1800, 591),
                source_page="英雄列表",
                target_pages=("英雄列表",),
                in_page_evidence=f"hero-{index}",
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

    def test_transition_retry_requires_same_in_page_evidence(self):
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: None, lambda *_: None),
        )
        previous = HeroAction(
            "open_imprint",
            (0, 0),
            source_page="英雄列表",
            in_page_evidence="hero-a",
        )
        current = HeroAction(
            "open_imprint",
            (0, 0),
            source_page="英雄列表",
            in_page_evidence="hero-b",
        )

        self.assertFalse(runner._in_page_evidence_matches(previous, current))

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

    def test_abort_imprint_retries_before_its_state_timeout(self):
        runner = HeroSynthRunner(
            HeroSynthStateMachine(build_hero_templates(TEMPLATES)),
            Runtime(lambda: None, lambda *_: None),
            sleep=lambda _: None,
        )

        self.assertEqual(
            12,
            runner._action_retry_seconds("abort_imprint_to_transmit"),
        )
        self.assertEqual(90, runner._timeout_for(HeroSynthState.IMPRINT_ABORTING))

    def test_abort_imprint_evidence_log_explains_current_screen(self):
        logs = []
        m = machine(verify_filter=True)
        m.pending_transmit_target = True
        m.transmit_target_observation = "saved-card"
        runner = HeroSynthRunner(
            m,
            Runtime(lambda: None, lambda *_: None, emit=logs.append),
            sleep=lambda _: None,
        )

        runner._log_imprint_abort_evidence(
            fixture("list_reddot"), prefix="中止返回等待"
        )

        output = "\n".join(logs)
        self.assertIn("英雄列表就绪=1", output)
        self.assertIn("当前身份=", output)
        self.assertIn("保存身份=saved-card", output)
        self.assertIn("传送阶段=pending", output)
        self.assertIn("连续性=1", output)

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
    def runner(self, *, runtime=None, clock=None):
        runtime = runtime or Runtime(lambda: None, lambda _: None)
        return HeroSynthRunner(
            machine(),
            runtime,
            sleep=(clock.sleep if clock is not None else (lambda _: None)),
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
            runner = self.runner(runtime=runtime, clock=clock)
            runner._TIMEOUT_SECONDS = {
                state: 5 for state in HeroSynthState
            }

            with self.assertRaisesRegex(RuntimeError, "黑屏时间过长（60秒）"):
                runner.run(max_cycles=1)

            self.assertTrue(list(Path(tmp).glob("*_black_screen_timeout.png")))
        self.assertEqual([], clicks)
        self.assertEqual([], wakes)
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
