"""路线可选项：声明、清洗、界面状态与运行请求的往返。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from auto_game_unified.desktop import session
from auto_game_unified.desktop.controller import DesktopController
from auto_game_unified.games.epic7.route_options import (
    ROUTE_OPTIONS,
    clean,
    clean_all,
    defaults_for,
    options_for,
)


class OptionDeclarationTests(unittest.TestCase):
    def test_defaults_keep_previous_behaviour(self):
        self.assertEqual(
            {
                # 2026-11-16 用户要求：周结算奖励可选，默认仍是钻石。
                "weekly_reward": "diamond",
                "opponent_preference": "none",
                # 两份名单默认为空 = 不筛选（改动前的行为）；冲突处置默认黑名单优先。
                "hero_blacklist": (),
                "hero_whitelist": (),
                "hero_list_conflict": "blacklist",
                "refresh_mode": "free",
                "max_gold_refreshes": 0,
                "ticket_mode": "friendship",
                "max_skystone_purchases": 0,
            },
            defaults_for("arena"),
        )

    def test_declared_routes(self):
        self.assertEqual(
            (
                "arena",
                "story",
                "story_star",
                "fodder",
                "world_boss",
                "side_story",
                "shop_refresh",
                "labyrinth_stone",
                "community",
                "tower",
                "pet_adoption",
            ),
            tuple(ROUTE_OPTIONS),
        )
        self.assertEqual((), options_for("expedition"))

    def test_invalid_values_fall_back_to_defaults(self):
        values = clean(
            "arena",
            {
                "refresh_mode": "unknown",
                "max_gold_refreshes": True,
                "ticket_mode": "skystone",
                "max_skystone_purchases": -1,
            },
        )
        self.assertEqual("free", values["refresh_mode"])
        self.assertEqual(0, values["max_gold_refreshes"])
        self.assertEqual(0, values["max_skystone_purchases"])

    def test_dependency_disabled_resets_count(self):
        values = clean("arena", {"refresh_mode": "free", "max_gold_refreshes": 5})
        self.assertEqual(0, values["max_gold_refreshes"])

    def test_count_is_clamped_to_declared_range(self):
        values = clean(
            "arena", {"refresh_mode": "gold", "max_gold_refreshes": 999}
        )
        self.assertEqual(30, values["max_gold_refreshes"])

    def test_old_session_without_params_gets_defaults(self):
        expected = {mode: defaults_for(mode) for mode in ROUTE_OPTIONS}
        self.assertEqual(expected, clean_all({}))
        self.assertEqual(expected, clean_all(None))

    def test_unknown_keys_are_dropped(self):
        self.assertEqual(defaults_for("arena"), clean("arena", {"only_npc": True}))

    def test_labels_and_notes_use_guide_style(self):
        forbidden = (
            "你", "您", "请", "别", "点一下", "就行", "吧", "啦", "呢", "啊", "嘛",
            "参数", "字段", "按钮", "阈值", "模板", "锚点", "坐标",
        )
        for options in ROUTE_OPTIONS.values():
            for option in options:
                texts = (option.label, option.note) + tuple(
                    choice[1] for choice in option.choices
                )
                for text in texts:
                    for word in forbidden:
                        self.assertNotIn(word, text, f"{option.key} 含禁用词 {word}")


class ControllerOptionTests(unittest.TestCase):
    def _controller(self):
        worker = Mock()
        worker.running = False
        return DesktopController(worker=worker), worker

    def test_session_roundtrip(self):
        controller, _ = self._controller()
        controller.set_options(
            "arena", {"refresh_mode": "gold", "max_gold_refreshes": 3}
        )
        state = session.SessionState(
            params={"arena": dict(controller.options["arena"])}
        )
        other, _ = self._controller()
        other.apply_session(state)
        self.assertEqual("gold", other.options["arena"]["refresh_mode"])
        self.assertEqual(3, other.options["arena"]["max_gold_refreshes"])

    def test_old_session_keeps_defaults(self):
        controller, _ = self._controller()
        controller.apply_session(session.SessionState())
        self.assertEqual(defaults_for("arena"), controller.options["arena"])

    def test_start_carries_options(self):
        controller, worker = self._controller()
        controller.selection = ["arena"]
        controller.preflight_report = Mock(can_start=True)
        controller.set_options(
            "arena", {"refresh_mode": "gold", "max_gold_refreshes": 2}
        )
        controller.start()
        request = worker.start.call_args[0][0]
        self.assertEqual("gold", request.params["arena"]["refresh_mode"])
        self.assertEqual(2, request.params["arena"]["max_gold_refreshes"])

    def test_unknown_route_rejected(self):
        controller, _ = self._controller()
        with self.assertRaises(ValueError):
            controller.set_options("expedition", {})


class OptionRoutingTests(unittest.TestCase):
    def test_stamina_routes_translate_options(self):
        from pathlib import Path

        from auto_game_unified.games.epic7.modes import get_mode

        for mode in ("story", "story_star", "fodder", "world_boss", "side_story", "tower"):
            spec = get_mode(mode)
            self.assertIsNotNone(spec.runner_options, f"{mode} 缺少选项翻译")
            options = spec.runner_options(
                Path("."), True, {"stamina_enabled": "no", "stamina_limit": 5}
            )
            self.assertFalse(options["stamina_enabled"])
            self.assertIsNone(options["stamina_limit"])

        story = get_mode("story").runner_options(
            Path("."), True, {"repeat_after_last": "no"}
        )
        self.assertFalse(story["repeat_after_last"])

    def test_shop_labyrinth_and_community_translate_options(self):
        from pathlib import Path

        from auto_game_unified.games.epic7.modes import get_mode

        shop = get_mode("shop_refresh").runner_options(
            Path("."),
            True,
            {"friendship_enabled": "no", "friendship_limit": 3},
        )
        self.assertFalse(shop["friendship_enabled"])
        # 依赖未满足时上限退回默认（10），与「关闭购买」的语义一致。
        self.assertEqual(10, shop["friendship_limit"])
        shop_on = get_mode("shop_refresh").runner_options(
            Path("."), True, {"friendship_enabled": "yes", "friendship_limit": 3}
        )
        self.assertEqual(3, shop_on["friendship_limit"])

        labyrinth = get_mode("labyrinth_stone").runner_options(
            Path("."), True, {"buy_friendship": "no"}
        )
        self.assertFalse(labyrinth["buy_friendship"])

        community = get_mode("community").runner_options(
            Path("."), True, {"redeem_energy": "no", "redeem_stone": "yes"}
        )
        self.assertFalse(community["redeem_energy"])
        self.assertTrue(community["redeem_stone"])

    def test_every_translated_option_is_a_real_runner_keyword(self):
        """声明出来的键必须真的能被 Runner 收下 —— 否则 Runtime 才炸。

        ``runner_options`` 的返回值是**直接**灌进构造函数的（``main.run_mode``：
        ``spec.runner_type(machine, runtime, **options)``）。声明加了一项、
        翻译函数加了那个键、Runner 却没这个关键字 ⇒ 实跑第一秒 ``TypeError``，
        而单元测试全绿（2026-11-15 月塔加 ``stamina_enabled`` 时正是这样：
        月塔 Runner 原先没有 ``__init__``，继承来的构造函数收不了新键）。
        """
        import numpy as np

        from pathlib import Path

        from auto_game_unified.core.runtime import Runtime
        from auto_game_unified.games.epic7.modes import MODE_SPECS, PC_ONLY_ROUTES
        from auto_game_unified.games.epic7.template_paths import TemplateDir

        root = Path(__file__).resolve().parents[1]
        templates = root / "games" / "epic7" / "templates"
        for mode in ROUTE_OPTIONS:
            spec = MODE_SPECS[mode]
            with self.subTest(mode=mode):
                template_root = (
                    TemplateDir(templates, "pc") if mode in PC_ONLY_ROUTES else templates
                )
                machine = spec.build_machine(template_root, spec.default_state)
                runtime = Runtime(
                    lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                    lambda point: None,
                    diagnostic_dir=None,
                    emit=lambda line: None,
                )
                options = spec.runner_options(root, True, {})
                runner = spec.runner_type(machine, runtime, **options)
                self.assertIs(runner.machine, machine)


class OptionalOfferEvidenceTests(unittest.TestCase):
    def test_missing_offer_templates_never_produce_a_click(self):
        """缺画面证据时，两个付费判据都不作数，不会落到猜测点击。"""
        from dataclasses import replace
        from pathlib import Path

        import numpy as np

        from auto_game_unified.games.epic7.arena import (
            ArenaStateMachine,
            build_templates,
            find_skystone_offer,
        )

        root = Path(__file__).resolve().parents[1]
        templates = build_templates(root / "games" / "epic7" / "templates")
        machine = ArenaStateMachine(
            replace(templates, refresh_gold=None, skystone_ticket_offer=None)
        )
        screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
        self.assertIsNone(machine.paid_refresh_confirm(screen))
        self.assertIsNone(machine.skystone_offer_selected(screen))
        self.assertIsNone(find_skystone_offer(screen, None))


if __name__ == "__main__":
    unittest.main()
