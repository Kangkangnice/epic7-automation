"""导航链「数据化」的护栏：链条是数据，执行器是代码，两边都不许偷偷漂。

守的是 2026-09-30 的改造：``navigation.Epic7Navigator.navigate()`` 以前是一张
``if mode == "story" / elif mode == "arena" / ...`` 的分派链（约 250 行），每加一条路线
都要回去改那个共享方法。现在链条声明在 ``modes.MODE_SPECS[...].navigation_plan`` 里，
``navigate()`` 只是执行器。

这里钉住四件事：

1. **表态完整**：有导航的路线必须有计划，没导航的路线不许有计划，``mode`` 要对得上；
2. **锚点真的存在**：每一步的 ``anchor`` 必须在 ``Epic7Navigator._REGIONS`` 与
   ``NavigationTemplates`` 上都有（不然是「声明了一条走不通的路」）；
3. **白名单是派生视图**：``navigation._RESUME_ENTRY_PAGES`` 只由计划派生，不许手抄；
4. **分派链不许长回来**：源码里再出现按 ``mode`` 分派的分支就红；
   顺手钉住那四个加载期自查**真的挂在模块加载上**（不是只在测试里跑）。
"""

from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.navigation import (
    _RESUME_ENTRY_PAGES,
    Epic7Navigator,
    build_navigation_templates,
)
from auto_game_unified.games.epic7.navigation_plan import (
    NavigationPlan,
    NavigationStep,
)

ROOT = Path(__file__).resolve().parents[1]
NAVIGATION_SOURCE = (ROOT / "games" / "epic7" / "navigation.py").read_text(
    encoding="utf-8"
)
MODES_SOURCE = (ROOT / "games" / "epic7" / "modes.py").read_text(encoding="utf-8")
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def plans():
    return [
        (name, spec.navigation_plan)
        for name, spec in modes.MODE_SPECS.items()
        if spec.navigation_plan is not None
    ]


class PlanDeclarationTests(unittest.TestCase):
    """每条路线对「有没有导航链」的表态必须完整且自洽。"""

    def test_every_navigating_route_declares_a_plan(self):
        for name, spec in modes.MODE_SPECS.items():
            if spec.needs_navigation:
                self.assertIsNotNone(spec.navigation_plan, f"{name} 缺 navigation_plan")
            else:
                self.assertIsNone(spec.navigation_plan, f"{name} 不该有 navigation_plan")

    def test_the_plan_mode_matches_its_registry_key(self):
        for name, plan in plans():
            self.assertEqual(name, plan.mode)

    def test_a_navigating_route_without_a_plan_is_rejected(self):
        broken = dataclasses.replace(modes.MODE_SPECS["story"], navigation_plan=None)
        with mock.patch.dict(modes.MODE_SPECS, {"story": broken}):
            with self.assertRaisesRegex(RuntimeError, "没有 navigation_plan"):
                modes._assert_navigation_declared()

    def test_a_plan_on_a_route_without_navigation_is_rejected(self):
        borrowed = modes.MODE_SPECS["story"].navigation_plan
        broken = dataclasses.replace(
            modes.MODE_SPECS["survivor"], navigation_plan=borrowed
        )
        with mock.patch.dict(modes.MODE_SPECS, {"survivor": broken}):
            with self.assertRaisesRegex(RuntimeError, "needs_navigation=False"):
                modes._assert_navigation_declared()

    def test_a_plan_whose_mode_disagrees_with_the_key_is_rejected(self):
        plan = modes.MODE_SPECS["story"].navigation_plan
        assert plan is not None
        wrong = dataclasses.replace(plan, mode="not_story")
        broken = dataclasses.replace(modes.MODE_SPECS["story"], navigation_plan=wrong)
        with mock.patch.dict(modes.MODE_SPECS, {"story": broken}):
            with self.assertRaisesRegex(RuntimeError, "对不上"):
                modes._assert_navigation_declared()


class PlanInvariantTests(unittest.TestCase):
    """计划自身的结构性约束（在 NavigationPlan.__post_init__ 里）。"""

    def test_a_resume_entry_outside_the_chain_is_rejected(self):
        # 「白名单里有、链条上没有」= 声明能从那一页接力，而导航压根到不了那里。
        with self.assertRaisesRegex(ValueError, "链条之外"):
            NavigationPlan(
                mode="x",
                steps=(NavigationStep("lobby", ("a",), "lobby_story", "进入"),),
                resume_entries=frozenset({"b"}),
                resume_action="跳过回大厅与进入 x",
                resume_state_done="已在 x",
            )

    def test_a_plan_without_steps_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "一步都没有"):
            NavigationPlan(mode="x", steps=())

    def test_a_resume_whitelist_without_log_wording_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "resume_action"):
            NavigationPlan(
                mode="x",
                steps=(NavigationStep("lobby", ("a",), "lobby_story", "进入"),),
                resume_entries=frozenset({"a"}),
            )


class PlanAnchorTests(unittest.TestCase):
    """每条链上的锚点都必须在执行器那边真的存在。"""

    def test_every_step_anchor_exists_on_the_navigator_and_its_templates(self):
        templates = build_navigation_templates(TEMPLATES)
        for name, plan in plans():
            for step in plan.steps:
                with self.subTest(route=name, anchor=step.anchor):
                    self.assertIn(step.anchor, Epic7Navigator._REGIONS)
                    self.assertTrue(
                        hasattr(templates, step.anchor),
                        f"{step.anchor} 不在 NavigationTemplates 上",
                    )

    def test_single_target_steps_still_compare_as_plain_strings(self):
        # ⚠️ _transition 里有 target == "hero_list" 这类身份比较，形状不能变。
        for name, plan in plans():
            for step in plan.steps:
                target = plan.transition_target(step)
                if len(step.targets) == 1:
                    self.assertIsInstance(target, str, name)
                else:
                    self.assertEqual(tuple(step.targets), target)


class ResumeWhitelistViewTests(unittest.TestCase):
    def test_the_view_is_derived_from_the_plans(self):
        expected = {name: plan.resume_entries for name, plan in plans()}
        self.assertEqual(expected, _RESUME_ENTRY_PAGES)

    def test_resuming_at_the_last_chain_page_clicks_nothing(self):
        """停在链条末端 = 导航已完成：一次都不该点（旧实现的行为，逐字保住）。"""
        templates = build_navigation_templates(TEMPLATES)
        checked = 0
        for name, plan in plans():
            terminal = plan.steps[-1].targets[0]
            if terminal not in plan.resume_entries:
                continue
            checked += 1
            clicks: list[tuple[int, int]] = []
            runtime = Runtime(
                lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                clicks.append,
                emit=lambda _: None,
            )
            navigator = Epic7Navigator(
                templates, runtime, sleep=lambda _: None, transition_frames=1
            )
            with self.subTest(route=name, page=terminal):
                navigator.navigate(
                    name,
                    lobby_screen=np.zeros((1132, 1982, 3), dtype=np.uint8),
                    already_at=terminal,
                )
                self.assertEqual([], clicks)
        self.assertGreaterEqual(checked, 4, "覆盖面太小，这条用例就没意义了")


class SourceGuardTests(unittest.TestCase):
    """「删掉的机制不许长回来」—— 源码级护栏。"""

    def test_the_navigator_no_longer_dispatches_on_route_names(self):
        tree = ast.parse(NAVIGATION_SOURCE)
        comparisons = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "mode"
        ]
        self.assertEqual(
            [],
            comparisons,
            "navigation.py 里又出现了按 mode 分派的分支；"
            "新增路线的导航链应当声明在 modes.MODE_SPECS 的 navigation_plan 里",
        )

    def test_all_four_declaration_checks_are_wired_together(self):
        tree = ast.parse(MODES_SOURCE)
        runner = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "_run_load_time_checks"
            ),
            None,
        )
        self.assertIsNotNone(runner, "找不到 _run_load_time_checks")
        body = ast.get_source_segment(MODES_SOURCE, runner) or ""
        for name in (
            "_assert_navigation_declared",
            "_assert_resume_declared",
            "_assert_transition_stance_declared",
            "_assert_conclusion_gate_declared",
        ):
            self.assertIn(name, body)

    def test_the_load_time_checks_really_run_on_import(self):
        """模块级的裸调用才算「import 阶段报错」；写在函数里只是摆设。"""
        tree = ast.parse(MODES_SOURCE)
        top_level = [
            node.value.func.id
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ]
        self.assertIn("_run_load_time_checks", top_level)


if __name__ == "__main__":
    unittest.main()
