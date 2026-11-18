"""装备制作路线的夹具驱动测试（2026-11-17 模拟器真机帧）。

口径与其余路线一致：用**完整截图**按真实顺序驱动状态机，断言动作名与坐标，
而不是拿局部模板互相打。夹具全部来自当日实机，见
``tests/fixtures/epic7_craft_equipment/``。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.craft_equipment import (
    CraftEquipmentStateMachine,
    CraftPage,
    CraftPlan,
    build_craft_equipment_templates,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_craft_equipment"


def frame(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    if image is None:
        raise AssertionError(f"夹具缺失：{name}.png")
    return image


class CraftEquipmentMachineTest(unittest.TestCase):
    def machine(self, **kwargs) -> CraftEquipmentStateMachine:
        plan = CraftPlan(**kwargs)
        return CraftEquipmentStateMachine(
            build_craft_equipment_templates(TEMPLATES), plan=plan
        )

    def test_page_recognition_covers_every_stable_page(self) -> None:
        cases = {
            "home": CraftPage.HOME,
            "qty_1": CraftPage.SELECTED,
            "qty_10": CraftPage.SELECTED,
            "confirm": CraftPage.CONFIRM,
            "confirm_from_result": CraftPage.CONFIRM,
            "confirm_from_tidy": CraftPage.CONFIRM,
            "result": CraftPage.RESULT,
            "tidy": CraftPage.TIDY,
            "quick_selected": CraftPage.TIDY,
            "after_sell": CraftPage.TIDY,
            "sell_confirm": CraftPage.SELL_CONFIRM,
            "extract_confirm": CraftPage.EXTRACT_CONFIRM,
        }
        machine = self.machine()
        for name, expected in cases.items():
            with self.subTest(fixture=name):
                self.assertIs(machine.observe_page(frame(name)), expected)

    def test_dark_frame_is_not_a_click(self) -> None:
        machine = self.machine()
        with self.assertRaises(UnrecognizedScreen):
            machine.next_action(np.zeros((1132, 1982, 3), dtype=np.uint8))

    def test_two_rounds_without_tidy(self) -> None:
        machine = self.machine(cycles=2, tidy="none")

        first = machine.next_action(frame("home"))
        self.assertEqual(first.name, "select-hunt")
        self.assertEqual(first.point, (297, 215))

        second = machine.next_action(frame("home"))
        self.assertEqual(second.name, "select-slot")
        self.assertEqual(second.point, (762, 379))

        # 档位是 1：必须先点「10」，不许直接制作。
        quantity = machine.next_action(frame("qty_1"))
        self.assertEqual(quantity.name, "set-quantity-10")

        confirm = machine.next_action(frame("qty_10"))
        self.assertEqual(confirm.name, "open-confirm")

        craft = machine.next_action(frame("confirm"))
        self.assertEqual(craft.name, "confirm-craft")
        self.assertEqual(machine.completed_cycles, 0)

        # 结果页出现才算一炉做成。
        again = machine.next_action(frame("result"))
        self.assertEqual(again.name, "again")
        self.assertEqual(machine.completed_cycles, 1)

        machine.next_action(frame("confirm_from_result"))
        done = machine.next_action(frame("result"))
        self.assertIsNone(done)
        self.assertEqual(machine.completed_cycles, 2)

    def test_sell_path_needs_quick_select_before_selling(self) -> None:
        machine = self.machine(cycles=3, tidy="sell")
        machine.next_action(frame("home"))
        machine.next_action(frame("home"))
        machine.next_action(frame("qty_10"))
        machine.next_action(frame("confirm"))
        self.assertEqual(machine.next_action(frame("result")).name, "open-tidy")

        tidy = machine.next_action(frame("tidy"))
        self.assertEqual(tidy.name, "quick-select")

        sell = machine.next_action(frame("quick_selected"))
        self.assertEqual(sell.name, "sell")

        confirm = machine.next_action(frame("sell_confirm"))
        self.assertEqual(confirm.name, "confirm-sell")

        again = machine.next_action(frame("after_sell"))
        self.assertEqual(again.name, "again-from-tidy")

    def test_extract_path_recognises_its_own_popup(self) -> None:
        machine = self.machine(cycles=3, tidy="extract")
        machine.next_action(frame("home"))
        machine.next_action(frame("home"))
        machine.next_action(frame("qty_10"))
        machine.next_action(frame("confirm"))
        machine.next_action(frame("result"))
        machine.next_action(frame("tidy"))
        self.assertEqual(machine.next_action(frame("quick_selected")).name, "extract")
        self.assertEqual(
            machine.next_action(frame("extract_confirm")).name, "confirm-extract"
        )

    def test_export_names_follow_the_game(self) -> None:
        plan = CraftPlan(hunt="banshee", slot="ring", tidy="none", cycles=1)
        self.assertEqual(plan.hunt_title, "报丧妖")
        self.assertEqual(plan.slot_title, "戒指")
        self.assertEqual(plan.total_items, 10)


if __name__ == "__main__":
    unittest.main()
