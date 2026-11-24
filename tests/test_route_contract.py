import unittest
from dataclasses import FrozenInstanceError

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
