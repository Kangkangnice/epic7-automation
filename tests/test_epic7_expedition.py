import dataclasses
import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.core.matcher import find_best_template
from auto_game_unified.games.epic7.expedition import (
    ExpeditionState,
    ExpeditionStateMachine,
    ExpeditionTemplates,
    PostersExhausted,
    build_expedition_templates,
)
from auto_game_unified.games.epic7.evidence.expedition import (
    build_expedition_evidence,
)


SIZE = (1132, 1982, 3)
ROOT = Path(__file__).resolve().parents[1]


def test_expedition_profile_declares_current_thresholds():
    """远征门槛只有一档（模拟器基线）—— 以前这里还对比过一份「PC 同样值」的
    证据档案，用来证明 PC 没被门槛表放松。门槛表删掉之后，那份对比也没了。"""
    template_dir = ROOT / "games" / "epic7" / "templates" / "expedition"
    profile = build_expedition_evidence(template_dir)

    assert profile.atom("campfire_idle").threshold == 0.82
    assert profile.atom("battle_start").threshold == 0.88


def pattern(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (24, 48, 3), dtype=np.uint8)


TEMPLATES = ExpeditionTemplates(
    home=pattern(1),
    poster_embark=pattern(2),
    empty_posters=pattern(3),
    difficulty_title=pattern(4),
    difficulty_3_selected=pattern(5),
    difficulty_confirm=pattern(6),
    prepare_battle=pattern(7),
    battle_start=pattern(8),
    auto_off=pattern(19),
    battle_anchor=pattern(9),
    result_confirm=pattern(10),
    victory_title=pattern(20),
    victory_close=pattern(21),
    public_recruit=pattern(12),
    public_title=pattern(13),
    public_confirm=pattern(14),
    public_recruited=pattern(15),
    campfire_idle=pattern(16),
    expedition_list=pattern(17),
    back=pattern(18),
)


def screen_with(*items: tuple[np.ndarray, tuple[int, int]]) -> np.ndarray:
    screen = np.zeros(SIZE, dtype=np.uint8)
    for template, (x, y) in items:
        height, width = template.shape[:2]
        screen[y : y + height, x : x + width] = template
    return screen


def recorded_screen(name: str, group: str = "epic7_expedition") -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / group / f"{name}.png"
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def real_machine(state=ExpeditionState.HOME) -> ExpeditionStateMachine:
    return ExpeditionStateMachine(
        build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        ),
        initial_state=state,
    )


class ExpeditionStateMachineTests(unittest.TestCase):
    def machine(self, state=ExpeditionState.HOME):
        return ExpeditionStateMachine(
            TEMPLATES,
            initial_state=state,
        )

    def test_battle_adapter_maps_team_manual_and_result(self):
        machine = ExpeditionStateMachine(
            build_expedition_templates(
                ROOT / "games" / "epic7" / "templates" / "expedition"
            ),
            initial_state=ExpeditionState.TEAM,
        )

        team = machine.observe_battle(recorded_screen("team"), None)
        manual = machine.observe_battle(
            recorded_screen("battle_manual_waiting_live"), None
        )
        automatic = machine.observe_battle(recorded_screen("battle"), None)
        result = machine.observe_battle(recorded_screen("result"), None)

        self.assertTrue(team.pre_battle_visible)
        self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
        self.assertIsNotNone(manual.auto_point)
        self.assertEqual(AutoBattleState.AUTO, automatic.auto_state)
        self.assertTrue(automatic.battle_visible)
        self.assertTrue(result.result_visible)

    def test_battle_adapter_treats_dynamic_valid_frames_as_progress_without_hud(self):
        machine = self.machine(ExpeditionState.BATTLE)
        before = np.random.default_rng(1).integers(
            0, 256, SIZE, dtype=np.uint8
        )
        after = np.random.default_rng(2).integers(
            0, 256, SIZE, dtype=np.uint8
        )

        observation = machine.observe_battle(after, before)

        self.assertFalse(observation.battle_visible)
        self.assertTrue(observation.business_progress)
        self.assertEqual(AutoBattleState.UNKNOWN, observation.auto_state)

    def test_home_opens_my_wanted_posters(self):
        machine = self.machine()

        action = machine.next_action(screen_with((TEMPLATES.home, (1600, 980))))

        self.assertEqual("open-my-posters", action.name)
        self.assertEqual(ExpeditionState.HOME, machine.state)

    def test_poster_list_selects_first_card_button_top_to_bottom(self):
        machine = self.machine(ExpeditionState.POSTERS)
        screen = screen_with(
            (TEMPLATES.poster_embark, (1050, 620)),
            (TEMPLATES.poster_embark, (1050, 280)),
        )

        action = machine.next_action(screen)

        self.assertEqual("select-first-poster", action.name)
        self.assertEqual((1074, 292), action.point)

    def test_bottom_right_global_embark_is_never_a_poster(self):
        machine = self.machine(ExpeditionState.POSTERS)
        screen = screen_with((TEMPLATES.poster_embark, (1760, 1010)))

        with self.assertRaisesRegex(RuntimeError, "传单卡片区域内未找到远征队出发按钮"):
            machine.next_action(screen)

    def test_empty_poster_list_is_resource_exhaustion(self):
        machine = self.machine(ExpeditionState.POSTERS)

        with self.assertRaises(PostersExhausted):
            machine.next_action(screen_with((TEMPLATES.empty_posters, (850, 480))))

    def test_home_recognizes_posters_list_when_home_button_absent(self):
        # 实机：状态仍是主页，但画面已是通缉传单列表（返回落点偏差/转场动画），
        # 主页锚点缺失。修复前会误判为未知画面进入唤醒死循环。
        machine = self.machine(ExpeditionState.HOME)
        screen = screen_with(
            (TEMPLATES.poster_embark, (517, 750)),
            (TEMPLATES.back, (0, 0)),
        )

        action = machine.next_action(screen)

        self.assertEqual("select-first-poster", action.name)
        self.assertEqual(ExpeditionState.POSTERS, machine.state)

    def test_posters_list_during_embark_animation_returns_none(self):
        # 实机帧 20260826_081147：列表标题+返回键已就位（~0.99），但“出发”
        # 按钮仍在滑入动画中未命中。修复前会抛 RuntimeError，导致转场失败。
        machine = self.machine(ExpeditionState.POSTERS)
        screen = screen_with(
            (TEMPLATES.expedition_list, (1100, 100)),
            (TEMPLATES.back, (0, 0)),
        )

        self.assertIsNone(machine.next_action(screen))

    def test_campfire_idle_relaxed_threshold_matches_real_drift_frame(self):
        # 实机帧 20260826_081022 中营地待机锚点仅 ~0.835，旧阈值 0.88 漏识。
        path = (
            ROOT
            / "runtime_diagnostics"
            / "epic7_expedition"
            / "20260826_081022_069178_unknown_before_wake.png"
        )
        if not path.exists():
            self.skipTest("real drift frame not available")
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(templates, initial_state=ExpeditionState.OUTCOME)
        screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)

        self.assertIsNotNone(machine._locate(screen, "campfire_idle"))

    def test_difficulty_is_fixed_to_stage_three_then_confirmed(self):
        machine = self.machine(ExpeditionState.DIFFICULTY)
        screen = screen_with((TEMPLATES.difficulty_title, (800, 210)))

        action = machine.next_action(screen)

        self.assertEqual("select-difficulty-3", action.name)
        self.assertEqual(ExpeditionState.DIFFICULTY, machine.state)
        machine.commit(action, ExpeditionState.DIFFICULTY_CONFIRM)

        confirm = machine.next_action(
            screen_with(
                (TEMPLATES.difficulty_3_selected, (1060, 690)),
                (TEMPLATES.difficulty_confirm, (980, 900)),
            )
        )
        self.assertEqual("confirm-difficulty-3", confirm.name)
        self.assertEqual(ExpeditionState.DIFFICULTY_CONFIRM, machine.state)

    def test_selected_stage_three_confirms_without_toggling(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.DIFFICULTY
        )

        action = machine.next_action(recorded_screen("difficulty_3_selected"))

        self.assertEqual("confirm-difficulty-3", action.name)
        self.assertEqual(ExpeditionState.DIFFICULTY, machine.state)

    def test_departure_action_does_not_advance_before_target_is_confirmed(self):
        machine = self.machine(ExpeditionState.POSTERS)

        action = machine.next_action(
            screen_with((TEMPLATES.poster_embark, (517, 750)))
        )

        self.assertEqual("select-first-poster", action.name)
        self.assertEqual(ExpeditionState.POSTERS, machine.state)

    def test_one_public_recruit_cycle_counts_only_after_return_home(self):
        machine = self.machine(ExpeditionState.READY)

        def act(screen, target):
            action = machine.next_action(screen)
            machine.commit(action, target)
            return action.name

        self.assertEqual("prepare-battle", act(
            screen_with((TEMPLATES.prepare_battle, (1650, 980))), ExpeditionState.TEAM
        ))
        self.assertEqual("battle-start", act(
            screen_with((TEMPLATES.battle_start, (1400, 980))), ExpeditionState.BATTLE
        ))
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual("confirm-result", act(
            screen_with((TEMPLATES.result_confirm, (1700, 980))), ExpeditionState.OUTCOME
        ))
        self.assertEqual("public-recruit", act(
            screen_with((TEMPLATES.public_recruit, (900, 980))), ExpeditionState.RECRUIT_CONFIRM
        ))
        self.assertEqual("confirm-public-recruit", act(screen_with(
            (TEMPLATES.public_title, (850, 350)),
            (TEMPLATES.public_confirm, (930, 800)),
        ), ExpeditionState.RECRUIT_RETURN))
        self.assertEqual("return-from-expedition", act(screen_with(
            (TEMPLATES.public_recruited, (950, 1000)),
            (TEMPLATES.back, (45, 70)),
        ), ExpeditionState.RETURNING))
        self.assertEqual(0, machine.completed_cycles)
        self.assertEqual("return-to-expedition-home", act(screen_with(
            (TEMPLATES.expedition_list, (1250, 180)),
            (TEMPLATES.back, (45, 70)),
        ), ExpeditionState.HOME))
        self.assertEqual(1, machine.completed_cycles)
        self.assertEqual(ExpeditionState.HOME, machine.state)

    def test_prepare_battle_may_land_directly_on_the_battle_page(self):
        """2026-09-18：点完「准备战斗」游戏**可能直接进战斗**（队伍已保存时跳过队伍选择）。

        四张失败收尾帧（09-17 23:39 / 09-18 19:42、20:00、20:16）全是局内，
        且 `battle_scene_visible=True` 在四帧上都成立 —— 判据认得出战斗页，
        是转场契约只写了「队伍选择」，于是白等 45 秒后抛错退出（退出码 1）。
        """
        machine = real_machine(ExpeditionState.READY)
        action = machine.next_action(recorded_screen("ready"))

        self.assertEqual("prepare-battle", action.name)
        self.assertEqual(
            (ExpeditionState.TEAM, ExpeditionState.BATTLE),
            action.target_states,
        )

        # 队伍页仍优先判 TEAM（走原来的流程）
        self.assertEqual(
            ExpeditionState.TEAM,
            machine.action_target_state(recorded_screen("team"), action),
        )
        # 战斗页判 BATTLE
        self.assertEqual(
            ExpeditionState.BATTLE,
            machine.action_target_state(recorded_screen("battle"), action),
        )
        machine.commit(action, ExpeditionState.BATTLE)
        self.assertEqual(ExpeditionState.BATTLE, machine.state)
        self.assertFalse(machine.auto_click_attempted)

    def test_quick_team_page_is_recognized_by_its_switch_control(self):
        """队伍页的快速战斗变体：`battle_start` 只剩 0.1378，靠切换控件才认得出来。

        全库 197 张夹具里切换控件过阈的只有 2 张（0.9883 / 1.0000），其余最高 0.5577。
        认不出这一页，`next_action` 里已有的「切回普通战斗」分支就永远走不到。
        """
        machine = real_machine(ExpeditionState.TEAM)
        quick = recorded_screen("team_quick_battle_live_20260918", "epic7_story")

        self.assertIsNone(machine._locate(quick, "battle_start"))
        self.assertTrue(machine.is_quick_battle_team_page(quick))
        self.assertTrue(machine.is_in_state(quick, ExpeditionState.TEAM))

        action = machine.next_action(quick)
        self.assertEqual("battle-start", action.name)
        self.assertEqual((ExpeditionState.BATTLE,), action.target_states)

        # 反例：远征自己的准备战斗 / 队伍选择两页不得误判成快速页
        for name in ("ready", "team"):
            with self.subTest(fixture=name):
                self.assertFalse(
                    machine.is_quick_battle_team_page(recorded_screen(name))
                )

    def test_campfire_idle_is_woken_without_advancing_outcome_state(self):
        machine = self.machine(ExpeditionState.OUTCOME)

        action = machine.next_action(
            screen_with((TEMPLATES.campfire_idle, (800, 150)))
        )

        self.assertEqual("wake-campfire-ui", action.name)
        self.assertEqual((1000, 600), action.point)
        self.assertEqual(ExpeditionState.OUTCOME, machine.state)
        self.assertTrue(machine.is_in_state(
            screen_with((TEMPLATES.campfire_idle, (800, 150))),
            ExpeditionState.OUTCOME,
        ))

    def test_campfire_idle_is_woken_before_returning_from_recruitment(self):
        machine = self.machine(ExpeditionState.RECRUIT_RETURN)

        action = machine.next_action(
            screen_with((TEMPLATES.campfire_idle, (800, 150)))
        )

        self.assertEqual("wake-campfire-ui", action.name)
        self.assertEqual((1000, 600), action.point)
        self.assertEqual(ExpeditionState.RECRUIT_RETURN, machine.state)
        self.assertTrue(machine.is_in_state(
            screen_with((TEMPLATES.campfire_idle, (800, 150))),
            ExpeditionState.RECRUIT_RETURN,
        ))

    def test_preview_does_not_mutate_state_or_count(self):
        machine = self.machine()

        action, outcome = machine.preview(screen_with((TEMPLATES.home, (1600, 980))))

        self.assertEqual("open-my-posters", action.name)
        self.assertEqual((ExpeditionState.HOME, 0), outcome)
        self.assertEqual(ExpeditionState.HOME, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_current_templates_load_without_uncaptured_optional_branches(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )

        # ⚠️ 2026-10-04 前这里断言 `empty_posters is None` —— 那是把**缺陷**当预期
        # 写进了测试：模板文件不存在，收工判据静默失效，实机空等超时 6 次
        # （2026-09-19~10-03）。现已补模板并改为必需，这里断言它**存在**。
        #
        # ⚠️ 同日稍后：唯一还在「可选」名单里的战败确认也整个删掉了 —— 远征没有
        # 「输」这回事（打完伤害直接进结算，只有一种结局），不存在需要单独认的页面。
        # 现在本路线**一张模板都不许缺席**，`_OPTIONAL_TEMPLATES` 已清空。
        self.assertIsNotNone(templates.empty_posters)
        self.assertEqual(frozenset(), ExpeditionStateMachine._OPTIONAL_TEMPLATES)

    def test_empty_posters_matches_the_live_empty_list_and_nothing_else(self):
        """「未持有通缉传单」判据：现场帧命中，其余全部夹具零误报。

        正样本 `empty_posters_live.png` 取自 2026-10-03 那次超时诊断图
        （`20261003_193135_215503_no_transition_open-my-posters`）—— 那次正是这个
        判据失灵导致的空等。模板从它裁出，但**分离度由负样本那一半证明**：
        有传单的 `posters.png` 必须不命中，否则模板根本没在区分两种状态。
        """
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(templates)
        region = machine._REGIONS["empty_posters"]

        fixture_dir = ROOT / "tests" / "fixtures" / "epic7_expedition"
        positive = fixture_dir / "empty_posters_live.png"
        screen = cv2.cvtColor(cv2.imread(str(positive)), cv2.COLOR_BGR2RGB)
        match = find_best_template(
            screen, templates.empty_posters, region=region, reference_size=(1982, 1132)
        )
        self.assertIsNotNone(match)
        self.assertGreater(match.score, 0.88)

        for path in sorted(fixture_dir.glob("*.png")):
            if path == positive:
                continue
            with self.subTest(fixture=path.name):
                other = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
                best = find_best_template(
                    other, templates.empty_posters, region=region, reference_size=(1982, 1132)
                )
                self.assertLess(best.score, 0.88)

    def test_empty_poster_list_stops_as_resource_exhaustion_on_the_live_frame(self):
        """端到端：现场帧上的 `next_action` 必须抛出 `PostersExhausted`。

        ⚠️ 断言到「依据」而不只是「抛没抛」：判据失灵时这里**不会报错**，
        只会返回 None 继续空等 —— 那正是实机发生的形态。所以额外断言机器
        确实认到了这个锚点。
        """
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(templates, initial_state=ExpeditionState.POSTERS)
        screen = cv2.cvtColor(
            cv2.imread(
                str(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "epic7_expedition"
                    / "empty_posters_live.png"
                )
            ),
            cv2.COLOR_BGR2RGB,
        )

        self.assertIsNotNone(machine._locate(screen, "empty_posters"))
        with self.assertRaises(PostersExhausted):
            machine.next_action(screen)

    def test_home_recognition_ignores_changed_wanted_poster_badge(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.RETURNING
        )
        path = (
            ROOT
            / "tests"
            / "fixtures"
            / "epic7_expedition"
            / "home_changed_badge.png"
        )
        screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)

        self.assertTrue(machine.is_in_state(screen, ExpeditionState.HOME))
        self.assertEqual(0, machine.completed_cycles)

    def test_recorded_current_client_pages_match_their_states(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(templates)

        cases = (
            ("home", ExpeditionState.HOME),
            ("posters", ExpeditionState.POSTERS),
            ("difficulty_3_selected", ExpeditionState.DIFFICULTY_CONFIRM),
            ("ready", ExpeditionState.READY),
            ("team", ExpeditionState.TEAM),
            ("battle", ExpeditionState.BATTLE),
            ("result", ExpeditionState.RESULT),
            ("outcome_public", ExpeditionState.OUTCOME),
            ("public_confirm", ExpeditionState.RECRUIT_CONFIRM),
            ("recruited", ExpeditionState.RECRUIT_RETURN),
            ("expedition_list", ExpeditionState.RETURNING),
        )
        for fixture_name, state in cases:
            with self.subTest(fixture=fixture_name, state=state):
                self.assertTrue(machine.is_in_state(recorded_screen(fixture_name), state))

    def test_recorded_campfire_idle_produces_only_the_safe_wake_click(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.RECRUIT_RETURN
        )

        action = machine.next_action(recorded_screen("campfire_idle"))

        self.assertEqual("wake-campfire-ui", action.name)
        self.assertEqual((1000, 600), action.point)

    def test_current_highlighted_public_recruit_button_is_recognized(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.OUTCOME
        )

        action = machine.next_action(recorded_screen("outcome_public_highlighted"))

        self.assertEqual("public-recruit", action.name)
        self.assertEqual(ExpeditionState.OUTCOME, machine.state)

    def test_manual_expedition_battle_enables_auto_once(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.BATTLE
        )

        action = machine.next_action(recorded_screen("battle_manual_waiting_live"))

        self.assertEqual("enable-auto-battle", action.name)
        self.assertTrue(1660 <= action.point[0] <= 1720)
        self.assertTrue(70 <= action.point[1] <= 125)
        self.assertIsNone(
            machine.next_action(recorded_screen("battle_manual_waiting_live"))
        )

    def test_preview_does_not_consume_auto_battle_click(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.BATTLE
        )
        screen = recorded_screen("battle_manual_waiting_live")

        preview, _ = machine.preview(screen)
        action = machine.next_action(screen)

        self.assertEqual("enable-auto-battle", preview.name)
        self.assertEqual("enable-auto-battle", action.name)

    def test_victory_popup_skips_public_recruitment(self):
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        machine = ExpeditionStateMachine(
            templates, initial_state=ExpeditionState.OUTCOME
        )

        action = machine.next_action(recorded_screen("victory_popup_live"))

        self.assertEqual("close-expedition-victory", action.name)
        self.assertEqual(ExpeditionState.OUTCOME, machine.state)


class OptionalTemplateGuardTests(unittest.TestCase):
    """把「静默降级」钉死在代码门槛上（2026-10-04）。

    `empty_posters` 的教训：模板文件不存在 ⇒ `_locate()` 静默返回 None ⇒
    「模板没了」伪装成「画面上没这个控件」⇒ 收工判据失灵、空等超时 6 次。
    """

    def test_locator_refuses_a_missing_template_that_is_not_whitelisted(self):
        """未登记为可选的模板若为 None，`_locate` 必须**报错点名**，不许静默。

        反向喂违规：把 `empty_posters` 粗暴置 None（模拟模板被删）⇒ 必须红。
        """
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        broken = dataclasses.replace(templates, empty_posters=None)
        machine = ExpeditionStateMachine(broken)

        with self.assertRaisesRegex(RuntimeError, "empty_posters"):
            machine._locate(np.zeros(SIZE, dtype=np.uint8), "empty_posters")

    def test_every_template_is_now_required(self):
        """白名单已清空 ⇒ **任何**模板缺席都必须报错点名，没有例外。

        背景：原先唯一在册的战败确认已删除（远征没有「输」这回事）。这条测试钉住
        「不能悄悄再往白名单里塞东西」—— 谁想加，必须先想清楚为什么这里允许少一张图。
        """
        templates = build_expedition_templates(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        self.assertEqual(frozenset(), ExpeditionStateMachine._OPTIONAL_TEMPLATES)

        # 逐个把模板置 None，`_locate` 都必须报错（拿两个不同锚点演示）。
        for name in ("empty_posters", "victory_title", "campfire_idle"):
            with self.subTest(anchor=name):
                broken = dataclasses.replace(templates, **{name: None})
                machine = ExpeditionStateMachine(broken)
                with self.assertRaisesRegex(RuntimeError, name):
                    machine._locate(np.zeros(SIZE, dtype=np.uint8), name)

    def test_whitelist_matches_the_evidence_profile(self):
        """`_OPTIONAL_TEMPLATES` 必须与证据画像的 `required` 逐字一致。

        两处各写一份是刻意的（一个管加载、一个管校验），但没有钉子就会漂移。
        """
        profile = build_expedition_evidence(
            ROOT / "games" / "epic7" / "templates" / "expedition"
        )
        from_evidence = {
            name for name, atom in profile.atoms.items() if not atom.required
        }

        self.assertEqual(
            from_evidence, set(ExpeditionStateMachine._OPTIONAL_TEMPLATES)
        )


if __name__ == "__main__":
    unittest.main()
