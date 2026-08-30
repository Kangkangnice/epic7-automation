import itertools
import unittest
import unittest.mock
from pathlib import Path

import cv2

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.games.epic7.assist_auto import (
    AssistAutoAction,
    AssistAutoRunner,
    AssistAutoState,
    AssistAutoStateMachine,
    build_assist_auto_templates,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS, get_mode


TEMPLATE_ROOT = (
    Path(__file__).resolve().parent.parent
    / "games"
    / "epic7"
    / "templates"
    / "assist_auto"
)
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


class AssistAutoStructureTests(unittest.TestCase):
    def test_registry_includes_assist_auto(self):
        self.assertIn("assist_auto", MODE_SPECS)

    def test_assist_auto_does_not_need_navigation(self):
        self.assertFalse(get_mode("assist_auto").needs_navigation)

    def test_other_modes_still_need_navigation(self):
        for name in ("arena", "story", "expedition", "fodder"):
            self.assertTrue(get_mode(name).needs_navigation, name)

    def test_default_state_is_team(self):
        self.assertEqual("team", get_mode("assist_auto").default_state)

    def test_states_cover_full_cycle(self):
        states = {s.value for s in AssistAutoState}
        self.assertEqual(
            {"team", "battle", "stopped", "prologue", "assistant"}, states
        )

    def test_resolve_state_validates_assist_auto_states(self):
        self.assertEqual("team", get_mode("assist_auto").resolve_state("team"))
        self.assertEqual("team", get_mode("assist_auto").resolve_state(None))
        with self.assertRaisesRegex(ValueError, "不适用于模式 assist_auto"):
            get_mode("assist_auto").resolve_state("list")


class AssistAutoTemplateTests(unittest.TestCase):
    def test_build_templates_loads_all_assets(self):
        if not TEMPLATE_ROOT.exists():
            self.skipTest("assist_auto templates not yet captured")
        templates = build_assist_auto_templates(TEMPLATE_ROOT)
        for name in (
            "auto_stopped",
            "replay",
            "victory_confirm",
            "auto_switch",
            "auto_repeat_active",
            "select_team",
            "battle_start",
            "stamina_popup",
            "stamina_material",
            "stamina_confirm",
            "results_confirm",
        ):
            attr = getattr(templates, name)
            self.assertIsNotNone(attr, name)
            self.assertEqual(3, attr.ndim, name)


class AssistAutoStateMachineTests(unittest.TestCase):
    def setUp(self):
        if not TEMPLATE_ROOT.exists():
            self.skipTest("assist_auto templates not yet captured")
        self.templates = build_assist_auto_templates(TEMPLATE_ROOT)

    def test_machine_starts_at_team_with_zero_cycles(self):
        machine = AssistAutoStateMachine(self.templates)
        self.assertEqual(AssistAutoState.TEAM, machine.state)
        self.assertEqual(0, machine.completed_cycles)

    def test_machine_accepts_custom_initial_state(self):
        machine = AssistAutoStateMachine(
            self.templates, initial_state=AssistAutoState.STOPPED
        )
        self.assertEqual(AssistAutoState.STOPPED, machine.state)

    def test_runner_constructs_without_recovery(self):
        runtime = unittest.mock.MagicMock()
        machine = AssistAutoStateMachine(self.templates)
        runner = AssistAutoRunner(machine, runtime)
        self.assertIsNone(runner.recovery)
        self.assertFalse(runner.resource_exhausted)


class AssistAutoMonitorTests(unittest.TestCase):
    def setUp(self):
        if not TEMPLATE_ROOT.exists():
            self.skipTest("assist_auto templates not yet captured")
        self.templates = build_assist_auto_templates(TEMPLATE_ROOT)

    def _load(self, rel: str):
        image = cv2.imread(str(FIXTURE_ROOT / rel))
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def test_monitor_counts_cycle_when_team_screen_returns(self):
        battle = self._load("epic7_fodder/battle.png")
        team = self._load("epic7_fodder/team.png")
        machine = AssistAutoStateMachine(self.templates)
        runtime = unittest.mock.MagicMock()
        runtime.dry_run = False
        runtime.diagnostic_dir = None
        runtime.capture.side_effect = [battle, battle, team, team, team]
        runtime.now.side_effect = itertools.count().__next__
        runner = AssistAutoRunner(
            machine,
            runtime,
            sleep=lambda seconds: None,
            recovery_gate=RecoveryGate(None),
        )
        runner._monitor_auto_repeat(cycle=1)
        self.assertEqual(1, machine.completed_cycles)
        self.assertIs(AssistAutoState.TEAM, machine.state)

    def test_monitor_ignores_team_residue_before_battle_starts(self):
        team = self._load("epic7_fodder/team.png")
        battle = self._load("epic7_fodder/battle.png")
        machine = AssistAutoStateMachine(self.templates)
        runtime = unittest.mock.MagicMock()
        runtime.dry_run = False
        runtime.diagnostic_dir = None
        # 点完"战斗开始"后队伍界面残留两帧，随后真正进入战斗；
        # 残留不得被当成"回到队伍界面"提前结束监控。
        frames = [team, team, battle, battle, battle, battle]
        runtime.capture.side_effect = frames
        runtime.now.side_effect = itertools.count(start=0, step=1).__next__
        runner = AssistAutoRunner(
            machine,
            runtime,
            sleep=lambda seconds: None,
            recovery_gate=RecoveryGate(None),
        )
        with self.assertRaises(StopIteration):
            # 帧耗尽仍无出口 → 模拟持续战斗直到测试帧用尽报错
            runner._monitor_auto_repeat(cycle=1)
        self.assertEqual(0, machine.completed_cycles)


if __name__ == "__main__":
    unittest.main()
