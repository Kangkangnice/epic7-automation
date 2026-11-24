"""契约机制的接线测试：必须扫真实 MODE_SPECS，不许用 mock 顶替。"""

import ast
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.route_contract import RouteContract

MODES_SOURCE = (Path(modes.__file__)).read_text(encoding="utf-8")
LEGACY_ROUTES = frozenset()
# 收尾不回大厅的两条，必须写清合法终点理由。
NOT_AT_HOME = frozenset({"survivor", "activity_story"})
# 已落地的逐条声明值；改了必须同时改声明依据（各路线手册与 route_finish_points）。
DECLARED_ROUTES = {
    # 第一批
    "arena": ("list", frozenset({"weekly_rank_start", "weekly_rank_select",
                                 "arena_rank_reward", "battle_record", "network"})),
    "story": ("stage", frozenset({"uncontrollable", "tutorial_unlock",
                                  "friend_request", "side_story_notice",
                                  "reward_notice", "network"})),
    "hero_synthesis": ("hero_list", frozenset({"reward_notice", "network"})),
    # 第二批
    "shop_refresh": ("scan_top", frozenset()),
    "labyrinth_stone": ("labyrinth_detail", frozenset({"equipment_bag_full"})),
    "expedition": ("home", frozenset()),
    # 第三批
    "world_boss": ("home", frozenset({"worldboss_support_reward", "knights_signin",
                                      "gift_support", "gift_claim",
                                      "knights_weekly_reward",
                                      "knights_growth_rank"})),
    "knights_donation": ("weekly_tasks", frozenset({"reward_notice", "knights_signin",
                                                    "gift_support", "gift_claim",
                                                    "knights_weekly_reward",
                                                    "knights_growth_rank"})),
    "tower": ("conquered", frozenset()),
    "side_story": ("stage", frozenset()),
    "moonlight_theater": ("list", frozenset({"reward_notice"})),
    # 第四批
    "fodder": ("assistant", frozenset()),
    "survivor": ("card", frozenset()),
    "activity_story": ("stage", frozenset()),
    "sanctuary": ("forest", frozenset()),
    "achievement": ("page", frozenset()),
    "story_star": ("episode", frozenset()),
    "pet_adoption": ("shop", frozenset()),
    "penguin_purchase": ("成长祭坛", frozenset()),
    "craft_equipment": ("制作结果页", frozenset({"equipment_bag_full"})),
    "community": ("closing", frozenset({"web_network_error"})),
}


def valid_contract(mode: str) -> RouteContract:
    spec = modes.MODE_SPECS[mode]
    return RouteContract(
        mode=mode,
        terminal=sorted(spec.states)[0],
        finish_at_home=True,
        overlays=frozenset(),
        empty_states=(),
        action_evidence="transition_contract",
    )


class RouteContractWiringTests(unittest.TestCase):
    def test_every_real_route_has_contract_or_backlog(self):
        self.assertEqual(21, len(modes.MODE_SPECS))
        for name, spec in modes.MODE_SPECS.items():
            with self.subTest(route=name):
                self.assertEqual(
                    spec.contract is None, name in modes.CONTRACT_BACKLOG,
                    "有契约就别留在欠债名单，没契约就必须在名单里",
                )

    def test_backlog_has_only_legacy_routes(self):
        self.assertEqual(LEGACY_ROUTES, set(modes.CONTRACT_BACKLOG))

    def test_declared_contracts_match_cases(self):
        for name, (terminal, overlays) in DECLARED_ROUTES.items():
            with self.subTest(route=name):
                contract = modes.MODE_SPECS[name].contract
                self.assertIsNotNone(contract)
                self.assertEqual(name, contract.mode)
                self.assertEqual(terminal, contract.terminal)
                self.assertEqual(overlays, contract.overlays)
                self.assertEqual(name in NOT_AT_HOME, not contract.finish_at_home)
                if name in NOT_AT_HOME:
                    self.assertTrue(contract.finish_note.strip())
                self.assertNotIn(name, modes.CONTRACT_BACKLOG)
        self.assertEqual(
            ("posters",), modes.MODE_SPECS["expedition"].contract.empty_states
        )
        for name in DECLARED_ROUTES:
            if name != "expedition":
                with self.subTest(route=name, field="empty_states"):
                    self.assertEqual((), modes.MODE_SPECS[name].contract.empty_states)

    def test_route_without_contract_or_backlog_fails(self):
        fake = "fake_route_for_contract_test"
        spec = replace(modes.MODE_SPECS["arena"], name=fake, contract=None)
        with mock.patch.dict(modes.MODE_SPECS, {fake: spec}):
            with self.assertRaisesRegex(RuntimeError, "既没有 contract"):
                modes._assert_route_contract_declared()

    def test_invalid_terminal_and_overlay_fail(self):
        contract = valid_contract("arena")
        for field, value in (
            ("terminal", "NO_SUCH_STATE"),
            ("overlays", frozenset({"not_a_popup"})),
        ):
            with self.subTest(field=field):
                broken = replace(contract, **{field: value})
                spec = replace(modes.MODE_SPECS["arena"], contract=broken)
                backlog = {
                    name: reason
                    for name, reason in modes.CONTRACT_BACKLOG.items()
                    if name != "arena"
                }
                with mock.patch.dict(modes.MODE_SPECS, {"arena": spec}), mock.patch.dict(
                    modes.CONTRACT_BACKLOG, backlog, clear=True
                ):
                    with self.assertRaisesRegex(RuntimeError, field):
                        modes._assert_route_contract_declared()

    def test_contract_mode_must_match_registration_name(self):
        spec = replace(modes.MODE_SPECS["arena"], contract=valid_contract("story"))
        backlog = {
            name: reason
            for name, reason in modes.CONTRACT_BACKLOG.items()
            if name != "arena"
        }
        with mock.patch.dict(modes.MODE_SPECS, {"arena": spec}), mock.patch.dict(
            modes.CONTRACT_BACKLOG, backlog, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "contract.mode"):
                modes._assert_route_contract_declared()

    def test_check_runs_on_import(self):
        tree = ast.parse(MODES_SOURCE)
        runner = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_run_load_time_checks"
        )
        body = ast.get_source_segment(MODES_SOURCE, runner) or ""
        self.assertIn("_assert_route_contract_declared()", body)
        self.assertTrue(
            any(
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == "_run_load_time_checks"
                for node in tree.body
            )
        )


if __name__ == "__main__":
    unittest.main()
