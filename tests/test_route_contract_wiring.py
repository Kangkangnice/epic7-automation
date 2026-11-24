"""契约机制的接线测试：必须扫真实 MODE_SPECS，不许用 mock 顶替。"""

import ast
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.route_contract import RouteContract

MODES_SOURCE = (Path(modes.__file__)).read_text(encoding="utf-8")
LEGACY_ROUTES = frozenset(
    {
        "arena", "story", "expedition", "fodder", "hero_synthesis", "shop_refresh",
        "survivor", "world_boss", "knights_donation", "labyrinth_stone", "sanctuary",
        "community", "tower", "side_story", "moonlight_theater", "activity_story",
        "achievement", "story_star", "pet_adoption", "penguin_purchase",
        "craft_equipment",
    }
)


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
