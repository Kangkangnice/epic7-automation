"""企鹅批量购买循环决策的判据测试（离线，不依赖真机帧）。

这些用例钉死的是业务口径：一轮 50 只、默认 10 轮共 500 只、
不是 50/50 就点「最多」补、每轮只买一次、跑完回大厅。
页面证据与点击坐标由采帧后的 evidence 层接入，不在本文件范围内。
"""

from __future__ import annotations

import unittest

from auto_game_unified.games.epic7.penguin_purchase import (
    DEFAULT_CYCLES,
    PENGUINS_PER_CYCLE,
    Observation,
    PenguinPage,
    PenguinPurchaseMachine,
)


def _drive(machine: PenguinPurchaseMachine, observations):
    """喂一帧、发一个动作、登记并验收，返回每帧的动作名。"""
    names = []
    for obs in observations:
        decision = machine.next_action(obs)
        if decision is None:
            names.append(None)
            continue
        names.append(decision.name)
        machine.mark_issued(decision.name)
        machine.commit(decision.name)
    return names


def _quantity_full():
    return Observation(
        PenguinPage.QUANTITY, quantity_is_max=True, price_is_expected=True
    )


def _one_round(machine: PenguinPurchaseMachine, quantity_already_max: bool = True):
    """走完一轮：数量弹窗 → 购买 → 完成弹窗 → 关闭。"""
    frames = []
    if not quantity_already_max:
        frames.append(
            Observation(
                PenguinPage.QUANTITY, max_button_visible=True, price_is_expected=True
            )
        )
    frames.extend([_quantity_full(), Observation(PenguinPage.COMPLETE)])
    return _drive(machine, frames)


class PenguinPurchaseDecisionTests(unittest.TestCase):
    def test_default_is_ten_rounds_of_fifty_penguins_each(self):
        machine = PenguinPurchaseMachine()
        self.assertEqual(DEFAULT_CYCLES, 10)
        self.assertEqual(PENGUINS_PER_CYCLE, 50)
        self.assertEqual(machine.cycles, 10)
        self.assertEqual(machine.total_penguins, 0)

    def test_one_round_buys_fifty_penguins_and_needs_max_on_first_time(self):
        machine = PenguinPurchaseMachine()
        names = _one_round(machine, quantity_already_max=False)
        self.assertEqual(
            names, ["set-max", "buy", "close-complete"]
        )
        self.assertEqual(machine.completed_cycles, 1)
        self.assertEqual(machine.total_penguins, 50)

    def test_second_round_skips_max_when_quantity_stays_at_fifty(self):
        machine = PenguinPurchaseMachine()
        _one_round(machine, quantity_already_max=False)
        names = _one_round(machine, quantity_already_max=True)
        self.assertEqual(names, ["buy", "close-complete"])
        self.assertEqual(machine.total_penguins, 100)

    def test_ten_rounds_buy_five_hundred_penguins_not_ten(self):
        machine = PenguinPurchaseMachine()
        for _ in range(DEFAULT_CYCLES):
            _one_round(machine)
        self.assertEqual(machine.completed_cycles, 10)
        self.assertEqual(machine.total_penguins, 500)
        self.assertEqual(
            machine.next_action(Observation(PenguinPage.FOREST)).name, "finish"
        )

    def test_cycles_are_adjustable(self):
        machine = PenguinPurchaseMachine(cycles=3)
        for _ in range(3):
            _one_round(machine)
        self.assertEqual(machine.total_penguins, 150)
        self.assertEqual(
            machine.next_action(Observation(PenguinPage.ALTAR)).name, "finish"
        )

    def test_buy_is_issued_only_once_per_round(self):
        machine = PenguinPurchaseMachine()
        names = _drive(machine, [_quantity_full(), _quantity_full()])
        self.assertEqual(names, ["buy", None])

    def test_quantity_below_fifty_never_buys_before_max(self):
        machine = PenguinPurchaseMachine()
        names = _drive(
            machine,
            [
                Observation(
                    PenguinPage.QUANTITY,
                    max_button_visible=True,
                    price_is_expected=True,
                )
            ],
        )
        self.assertEqual(names, ["set-max"])
        self.assertEqual(machine.completed_cycles, 0)

    def test_max_is_bounded_and_stops_when_quantity_never_reaches_fifty(self):
        machine = PenguinPurchaseMachine()
        names = _drive(
            machine,
            [
                Observation(
                    PenguinPage.QUANTITY,
                    max_button_visible=True,
                    price_is_expected=True,
                )
            ]
            * 4,
        )
        self.assertEqual(names[:3], ["set-max"] * 3)
        self.assertEqual(names[3], "stop-quantity")

    def test_wrong_price_stops_instead_of_buying(self):
        machine = PenguinPurchaseMachine()
        names = _drive(
            machine,
            [Observation(PenguinPage.QUANTITY, quantity_is_max=True, price_is_expected=False)],
        )
        self.assertEqual(names, ["stop-price"])
        self.assertEqual(machine.completed_cycles, 0)

    def test_insufficient_red_leaves_stops_without_partial_purchase(self):
        machine = PenguinPurchaseMachine()
        names = _drive(machine, [Observation(PenguinPage.CURRENCY_SHORT)])
        self.assertEqual(names, ["stop-currency"])
        self.assertEqual(machine.total_penguins, 0)

    def test_unknown_page_stops_bounded_instead_of_waiting_for_timeout(self):
        machine = PenguinPurchaseMachine()
        names = _drive(machine, [Observation(PenguinPage.UNKNOWN)])
        self.assertEqual(names, ["stop-unknown"])
        self.assertEqual(machine.finish_reason, "stop-unknown")
        self.assertIsNone(machine.next_action(Observation(PenguinPage.UNKNOWN)))

    def test_complete_popup_without_a_purchase_is_not_counted(self):
        machine = PenguinPurchaseMachine()
        names = _drive(machine, [Observation(PenguinPage.COMPLETE)])
        self.assertEqual(names, [None])
        self.assertEqual(machine.completed_cycles, 0)

    def test_complete_popup_close_is_issued_only_once(self):
        machine = PenguinPurchaseMachine()
        names = _drive(
            machine,
            [
                _quantity_full(),
                Observation(PenguinPage.COMPLETE),
                Observation(PenguinPage.COMPLETE),
            ],
        )
        self.assertEqual(names, ["buy", "close-complete", None])

    def test_navigation_reuses_the_sanctuary_chain(self):
        machine = PenguinPurchaseMachine()
        names = _drive(
            machine,
            [
                Observation(PenguinPage.LOBBY),
                Observation(PenguinPage.FOREST),
                Observation(PenguinPage.ALTAR),
                Observation(PenguinPage.NEST),
            ],
        )
        self.assertEqual(
            names,
            ["navigate-sanctuary", "open-altar", "select-nest", "open-quantity"],
        )

    def test_cycles_must_be_at_least_one(self):
        with self.assertRaises(ValueError):
            PenguinPurchaseMachine(cycles=0)


if __name__ == "__main__":
    unittest.main()
