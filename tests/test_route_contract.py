import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from auto_game_unified.games.epic7.global_popups import POPUP_KINDS
from auto_game_unified.games.epic7.route_contract import (
    RouteContract,
    validate_contract,
)


STATES = ("HOME", "LIST", "DONE", "OUT_OF_TICKETS")
POPUPS = frozenset({"reward_notice", "stamina"})
EXEMPT = frozenset({"legacy_route"})


def make_contract(**overrides) -> RouteContract:
    values = dict(
        mode="test_route",
        terminal="DONE",
        finish_at_home=True,
        overlays=POPUPS,
        empty_states=("OUT_OF_TICKETS",),
        action_evidence="transition_contract",
    )
    values.update(overrides)
    return RouteContract(**values)


class RouteContractValidationTests(unittest.TestCase):
    def test_terminal_in_states_passes(self):
        self.assertEqual([], validate_contract(make_contract(), STATES, POPUPS, EXEMPT))

    def test_finish_note_when_not_at_home_passes(self):
        contract = make_contract(
            finish_at_home=False, finish_note="结算页无返回入口，停在领奖页"
        )
        self.assertEqual([], validate_contract(contract, STATES, POPUPS, EXEMPT))

    def test_known_and_explicitly_empty_overlays_pass(self):
        for overlays in (POPUPS, frozenset()):
            with self.subTest(overlays=overlays):
                contract = make_contract(overlays=overlays)
                self.assertEqual([], validate_contract(contract, STATES, POPUPS, EXEMPT))

    def test_known_and_explicitly_empty_states_pass(self):
        for empty_states in (("OUT_OF_TICKETS",), ()):
            with self.subTest(empty_states=empty_states):
                contract = make_contract(empty_states=empty_states)
                self.assertEqual([], validate_contract(contract, STATES, POPUPS, EXEMPT))

    def test_action_evidence_two_ways_pass(self):
        by_transition = make_contract()
        by_exempt = make_contract(
            mode="legacy_route", action_evidence="自己的稳定帧等待"
        )
        for contract in (by_transition, by_exempt):
            with self.subTest(contract=contract):
                self.assertEqual(
                    [], validate_contract(contract, STATES, POPUPS, EXEMPT)
                )

    def test_contract_is_frozen_and_cannot_be_empty(self):
        contract = make_contract()
        with self.assertRaises(FrozenInstanceError):
            contract.terminal = "HOME"
        with self.assertRaises(TypeError):
            RouteContract()


class RouteContractRejectionTests(unittest.TestCase):
    """五条规则各一条反例：把校验删掉，这些用例必须变红。"""

    def assert_rejected(self, fragment: str, **overrides) -> None:
        problems = validate_contract(make_contract(**overrides), STATES, POPUPS, EXEMPT)
        self.assertTrue(any(fragment in problem for problem in problems), problems)

    def test_unknown_terminal_rejected(self):
        self.assert_rejected("terminal", terminal="NO_SUCH_STATE")

    def test_missing_finish_note_rejected(self):
        self.assert_rejected("finish_note", finish_at_home=False, finish_note="   ")

    def test_unregistered_overlay_rejected(self):
        self.assert_rejected("overlays", overlays=frozenset({"not_a_popup"}))

    def test_unknown_empty_state_rejected(self):
        self.assert_rejected("empty_states", empty_states=("NO_SUCH_STATE",))

    def test_evidence_outside_both_ways_rejected(self):
        self.assert_rejected("TRANSITION_EXEMPT", action_evidence="自创回执")

    def test_blank_evidence_in_exempt_list_rejected(self):
        self.assert_rejected("action_evidence", mode="legacy_route", action_evidence="  ")


class PopupKindRegistryTests(unittest.TestCase):
    def test_registry_matches_guard_identifiers(self):
        """守卫新增弹窗却忘了登记类别时，这里必须红。"""
        source = (
            Path(__file__).resolve().parents[1]
            / "games"
            / "epic7"
            / "global_popups.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        finder = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_find_popup"
        )
        identifiers = {
            item.elts[1].value
            for item in ast.walk(finder)
            if isinstance(item, ast.Tuple)
            and len(item.elts) >= 2
            and isinstance(item.elts[1], ast.Constant)
            and isinstance(item.elts[1].value, str)
        }
        self.assertEqual(POPUP_KINDS, identifiers)
