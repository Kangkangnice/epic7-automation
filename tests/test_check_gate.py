"""验证门槛（`tools/check.py`）的护栏。

守的是 2026-09-25 定的规矩：**改多少验多少，小改动不许白跑全量**。

门槛本身会按改动范围选测试，但日常爱敲的 `check.py --vs HEAD` 取的是「工作区相对 HEAD 的
**全部**改动」⇒ 上一轮没提交的共享模块会把判定永久拖成全量（2026-09-25 实测：只想验一行
改动，连跑两次全量 408s / 457s，而局部只要 28.7 秒）。

所以这里守住三件事：

1. 判成全量时**一定会**喊话（为什么全量 + 怎么改成定向）—— 让「白跑 7 分钟」在屏幕上
   变得刺眼；
2. 暂存区为空、退化成「整个工作区判定」时**一定会**提醒 —— 这是白跑的头号成因；
3. **默认不再自动跑全量**（2026-10-25 用户拍板）：共享模块按文件名定向，映射不到
   只提示；全量是 `--full` 的显式选项。

⚠️ 项目里的经验：**没护栏的规矩守不住**（唯一从来没被违反的规矩都带护栏测试）。
下面这些断言针对的是「提示还在、还接在门槛上」，不是措辞本身 —— 措辞可以改，
但别让提示悄悄消失、或者留着函数却把调用删了。
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest import mock

from auto_game_unified.tools import check as check_module
from auto_game_unified.tools.check import (
    WORKSPACE_MODE_NOTICE,
    full_run_notice,
)

CHECK_SOURCE = (Path(__file__).resolve().parents[1] / "tools" / "check.py").read_text(
    encoding="utf-8"
)


class FullRunNoticeTests(unittest.TestCase):
    """判成全量时的喊话。"""

    def test_it_says_why_the_gate_decided_on_a_full_run(self):
        reason = "改了共享模块 main.py"
        self.assertIn(reason, full_run_notice(reason, ["main.py", "tests/test_a.py"]))

    def test_it_offers_the_narrow_command_with_the_changed_files(self):
        notice = full_run_notice("改了共享模块", ["games/epic7/arena.py", "tests/test_a.py"])
        self.assertIn("--files", notice)
        self.assertIn("games/epic7/arena.py", notice)
        self.assertIn("tests/test_a.py", notice)

    def test_it_points_at_the_staged_alternative(self):
        # 「先 git add 再不带参数跑」是挡住并发会话 / 旧改动污染的唯一姿势，必须写进提示。
        self.assertIn("git add", full_run_notice("改了共享模块", ["main.py"]))

    def test_it_stays_useful_when_there_is_nothing_to_name(self):
        notice = full_run_notice("认不出归属", [])
        self.assertIn("--files", notice)
        self.assertIn("<改到的文件>", notice)

    def test_the_notice_is_actually_printed_by_the_gate(self):
        # 只断言「函数还在」不够 —— 留着函数却删掉调用，提示一样不会出现在屏幕上。
        self.assertIn("print(full_run_notice(", CHECK_SOURCE)


class TargetedSelectionTests(unittest.TestCase):
    """共享模块按文件名定向，映射不到只提示 —— **默认不再自动跑全量**。"""

    ALL_TESTS = [
        "test_daily_tasks.py",
        "test_desktop_worker.py",
        "test_modes.py",
        "test_moonlight_theater.py",
        "test_project_layout.py",
    ]

    def test_shared_module_maps_to_its_own_test(self):
        picked, reason, warnings = check_module.plan_tests(
            ["games/epic7/daily_tasks.py"], self.ALL_TESTS
        )
        self.assertIn("test_daily_tasks.py", picked)
        self.assertIn("test_desktop_worker.py", picked)
        self.assertNotIn("test_moonlight_theater.py", picked)
        self.assertEqual([], warnings)
        self.assertIn("daily_tasks", reason)

    def test_core_module_maps_by_stem(self):
        self.assertIn("matcher", check_module.test_keywords("core/matcher.py"))
        picked, _reason, _warnings = check_module.plan_tests(
            ["core/matcher.py"], ["test_matcher.py", "test_modes.py"]
        )
        self.assertEqual(["test_matcher.py"], picked)

    def test_unknown_module_warns_instead_of_running_everything(self):
        picked, _reason, warnings = check_module.plan_tests(
            ["games/epic7/no_such_module.py"], self.ALL_TESTS
        )
        self.assertEqual([], picked)
        self.assertTrue(any("no_such_module" in warning for warning in warnings))

    def test_conftest_is_warn_only(self):
        picked, _reason, warnings = check_module.plan_tests(
            ["tests/conftest.py"], self.ALL_TESTS
        )
        self.assertEqual([], picked)
        self.assertTrue(any("conftest" in warning for warning in warnings))

    def test_the_gate_no_longer_has_a_force_full_shared_list(self):
        self.assertIn("TEST_KEYWORD_OVERRIDES", CHECK_SOURCE)
        self.assertIn("plan_tests(", CHECK_SOURCE)
        self.assertNotIn("SHARED_PATHS", CHECK_SOURCE)
        self.assertNotIn("SHARED_PREFIXES", CHECK_SOURCE)

    def test_assets_still_pull_in_the_layout_test(self):
        picked, _reason, _warnings = check_module.plan_tests(
            ["tests/fixtures/epic7_moonlight_theater/story_dim.png"],
            self.ALL_TESTS,
        )
        self.assertIn("test_project_layout.py", picked)

    def test_portrait_change_hits_catalog_and_arena_without_hero_synthesis(self):
        all_tests = [
            *self.ALL_TESTS, "test_hero_catalog.py", "test_arena_hero_lists.py",
            "test_hero_roster_check.py", "test_add_hero.py", "test_hero_synthesis.py",
        ]
        picked, _reason, _warnings = check_module.plan_tests(
            ["games/epic7/templates/arena/heroes_pokedex/英雄.png"], all_tests,
        )
        self.assertEqual([
            "test_add_hero.py", "test_arena_hero_lists.py", "test_hero_catalog.py",
            "test_hero_roster_check.py", "test_project_layout.py",
        ], picked)

    def test_shared_story_templates_include_their_consuming_routes(self):
        all_tests = [
            *self.ALL_TESTS, "test_story.py", "test_fodder.py",
            "test_story_star.py", "test_navigation.py",
        ]
        picked, _reason, _warnings = check_module.plan_tests(
            ["games/epic7/templates/story/pc/auto_off.png"], all_tests,
        )
        self.assertTrue({"test_fodder.py", "test_story_star.py", "test_navigation.py"}.issubset(picked))

    def test_tool_and_spec_overrides_are_reachable(self):
        picked, _reason, _warnings = check_module.plan_tests(
            ["tools/add_hero.py", "packaging/epic7_auto_assistant.spec"],
            [*self.ALL_TESTS, "test_add_hero.py", "test_release_packaging.py"],
        )
        self.assertEqual(["test_add_hero.py", "test_release_packaging.py"], picked)

    def test_fixture_folder_prefers_the_most_specific_route(self):
        picked, _reason, _warnings = check_module.plan_tests(
            ["tests/fixtures/epic7_story_star_pc/lobby.png"],
            [*self.ALL_TESTS, "test_main_story.py", "test_story_star.py"],
        )
        self.assertEqual(["test_project_layout.py", "test_story_star.py"], picked)

    def test_shared_fixtures_select_consumers_outside_their_folder(self):
        all_tests = [*self.ALL_TESTS, "test_navigation.py", "test_hero_synthesis.py"]
        for folder in ("epic7_global", "epic7_navigation"):
            with self.subTest(folder=folder):
                picked, _reason, _warnings = check_module.plan_tests(
                    [f"tests/fixtures/{folder}/popup.png"], all_tests,
                )
                self.assertIn("test_hero_synthesis.py", picked)
                self.assertIn("test_navigation.py", picked)

    def test_navigation_reuses_route_and_legacy_root_assets(self):
        all_tests = [*self.ALL_TESTS, "test_navigation.py"]
        for path in (
            "games/epic7/templates/tower/pc/tower_home.png",
            "games/epic7/evidence/world_boss.py",
            "games/epic7/templates/list_ready.png",
        ):
            with self.subTest(path=path):
                picked, _reason, _warnings = check_module.plan_tests([path], all_tests)
                self.assertIn("test_navigation.py", picked)

    def test_diff_preserves_unicode_and_reports_both_paths_of_a_move(self):
        old = "games/epic7/templates/arena/heroes_pokedex/旧名.png"
        new = "games/epic7/templates/arena/heroes_pokedex/新名.png"
        result = mock.Mock(returncode=0, stdout=f"{old}\0{new}\0".encode())
        with mock.patch.object(check_module.subprocess, "run", return_value=result) as run:
            self.assertEqual([old, new], check_module.git("--cached"))
        self.assertIn("-z", run.call_args.args[0])
        self.assertIn("--no-renames", run.call_args.args[0])

    def test_plan_prints_targets_without_compiling_or_executing(self):
        argv = ["check.py", "--plan", "--files", "games/epic7/templates/tower/pc/card.png"]
        with (
            mock.patch.object(check_module.sys, "argv", argv),
            mock.patch.object(check_module, "run") as execute,
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(0, check_module.main())
        execute.assert_not_called()
        self.assertTrue(any("test_tower" in str(call) for call in output.call_args_list))


class TestLayerSelection(unittest.TestCase):
    def test_mapped_change_does_not_hide_an_unmapped_python_file(self):
        for unknown in ("core/unknown_dependency.py", "tools/new_helper.py", "tests/shared_factory.py"):
            with self.subTest(unknown=unknown):
                picked, _, warnings = check_module.plan_tests(
                    ["games/epic7/craft_equipment.py", unknown], ["test_epic7_craft_equipment.py"]
                )
                self.assertEqual(["test_epic7_craft_equipment.py"], picked)
                self.assertIn(unknown, " ".join(warnings))

    def test_pet_runner_fixture_and_shared_title_have_different_consumers(self):
        tests = ["test_pet_adoption.py", "test_navigation.py", "test_safety_fail_closed.py"]
        for path in ("games/epic7/pet_adoption.py", "tests/fixtures/epic7_pet_adoption/house.png"):
            picked, _, _ = check_module.plan_tests([path], tests)
            self.assertIn("test_pet_adoption.py", picked)
            self.assertNotIn("test_navigation.py", picked)
        picked, _, _ = check_module.plan_tests(["games/epic7/pet_adoption.py"], tests)
        self.assertIn("test_safety_fail_closed.py", picked)
        picked, _, _ = check_module.plan_tests(["games/epic7/templates/pet_adoption/house_title.png"], tests)
        self.assertIn("test_navigation.py", picked)

    def test_pr_can_bound_docs_roster_and_route_replay_together(self):
        from auto_game_unified.tools.pr_tests import plan_pr

        files = [
            "docs/RESUME_COVERAGE.md", "docs/TRANSITION_CONTRACTS.md",
            "docs/README.md", "games/epic7/templates/arena/heroes_pokedex/meta.json",
            "tests/fixtures/epic7_craft_equipment/frame.png", "tests/test_epic7_craft_equipment.py",
        ]
        picked, _ = plan_pr(files)
        self.assertIsNotNone(picked)
        for name in ("test_resume_contracts.py", "test_transition_contracts.py", "test_ui_copy_style.py",
                     "test_hero_catalog.py", "test_arena_hero_lists.py", "test_epic7_craft_equipment.py"):
            self.assertIn(name, picked)
        self.assertNotIn("test_navigation.py", picked)

    def test_pr_defaults_to_full_for_unbounded_or_mixed_changes(self):
        from auto_game_unified.tools.pr_tests import plan_pr

        self.assertIsNone(plan_pr([])[0])
        for path in ("core/matcher.py", "games/epic7/pet_adoption.py",
                     "tests/conftest.py", "tests/fixtures/epic7_navigation/frame.png",
                     "tools/new_helper.py", ".github/workflows/tests.yml",
                     "requirements.txt", "docs/manual_review/knights_donation/list.png",
                     "games/epic7/templates/arena/heroes_pokedex/new_config.json"):
            with self.subTest(path=path):
                picked, reason = plan_pr(["README.md", path])
                self.assertIsNone(picked)
                self.assertIn(path, reason)

    def test_pr_uses_tree_diff_and_propagates_pytest_failure_on_fallback(self):
        from auto_game_unified.tools import pr_tests

        with (
            mock.patch.object(pr_tests.sys, "argv", ["pr_tests", "--base", "HEAD^1"]),
            mock.patch.object(check_module, "git", side_effect=RuntimeError("shallow")) as diff,
            mock.patch.object(pr_tests.subprocess, "run", return_value=mock.Mock(returncode=2)) as run,
        ):
            self.assertEqual(2, pr_tests.main())
        diff.assert_called_once_with("HEAD^1", "HEAD")
        self.assertEqual("auto_game_unified/tests", run.call_args.args[0][-1])


class WorkspaceModeNoticeTests(unittest.TestCase):
    """暂存区为空、退化成「整个工作区判定」时的提醒。"""

    def test_it_says_the_whole_workspace_is_being_judged(self):
        self.assertIn("整个工作区", WORKSPACE_MODE_NOTICE)

    def test_it_offers_both_ways_out(self):
        self.assertIn("git add", WORKSPACE_MODE_NOTICE)
        self.assertIn("--files", WORKSPACE_MODE_NOTICE)

    def test_the_notice_is_actually_printed_by_the_gate(self):
        self.assertIn("print(WORKSPACE_MODE_NOTICE", CHECK_SOURCE)


#: 会走到控制台/报告里的调用名 —— 只有这些位置上的字符串才受编码约束。
#  - print / *.log：Runtime.log 的默认出口就是 print；
#  - assert*：pytest 把断言消息原样打印出来（GBK 控制台上会抛 UnicodeEncodeError）；
#  - raise：异常消息进 traceback（stderr）。
# ⚠️ 「任意调用」不行：像 `PublicFlowVerification(mechanism="…⚠️…")` 那种是**文档数据**，
#    还有 `report_workspace_tidy.add("| **⚠️ 别删** | …")` 是**写进 UTF-8 文件**的表格 ——
#    它们根本不会被编码到控制台，按「任意调用」判会把它们全部误报（第一版就是这样）。
_CONSOLE_CALL_NAMES = ("print", "log")


def _console_bound_strings(path: Path) -> list[tuple[int, str]]:
    """文件里**真的会进控制台或断言报告**的字符串字面量 -> [(行号, 内容)]。

    走 AST 而不是按行扫：注释与 docstring 里的 "⇒" 完全无害，按行扫会把它们一起判违规
    —— 包括本文件自己要举例说明这件事的那句 docstring（2026-09-30 第一版就是这么自己
    撞自己的）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []

    def collect(node: ast.AST) -> None:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                found.append((inner.lineno, inner.value))

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            collect(node.exc)
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None) or ""
        if name in _CONSOLE_CALL_NAMES or name.startswith("assert"):
            collect(node)
    return found


class AdaptiveWorkerCountTests(unittest.TestCase):
    """并行度必须**按当下的可用内存**决定，不能写死。

    两条实测教训（都在这台机器上量过）：
      * 恒定 4 路 —— 内存吃紧时 4 片耗时之和 382 秒 -> 502 秒（开始换页），比单进程还慢；
      * 恒定 1 路 —— 把空闲时的收益一起丢掉了（空闲 4 路 382 秒 -> 191 秒）。
    ⇒ 所以这里守的是「看内存决定」，两条边界都要有用例。
    """

    def _with_memory(self, gigabytes):
        return mock.patch.object(
            check_module, "available_memory_gb", return_value=gigabytes
        )

    def test_plenty_of_memory_means_parallel(self):
        with self._with_memory(16.0):
            self.assertEqual(4, check_module.choose_workers(70))

    def test_room_for_exactly_two(self):
        with self._with_memory(check_module.PARALLEL_RESERVE_GB + 1.2 * 2):
            self.assertEqual(2, check_module.choose_workers(70))

    def test_tight_memory_falls_back_to_one_process(self):
        with self._with_memory(check_module.PARALLEL_RESERVE_GB + 0.9):
            self.assertEqual(1, check_module.choose_workers(70))

    def test_unknown_memory_falls_back_to_one_process(self):
        with self._with_memory(None):
            self.assertEqual(1, check_module.choose_workers(70))

    def test_never_more_workers_than_targets(self):
        with self._with_memory(64.0):
            self.assertEqual(2, check_module.choose_workers(2))
            self.assertEqual(1, check_module.choose_workers(1))

    def test_the_env_override_wins_and_is_clamped(self):
        with mock.patch.dict(os.environ, {"EPIC7_CHECK_WORKERS": "3"}):
            self.assertEqual(3, check_module.choose_workers(70))
        with mock.patch.dict(os.environ, {"EPIC7_CHECK_WORKERS": "99"}):
            self.assertEqual(
                check_module.PARALLEL_MAX_WORKERS, check_module.choose_workers(70)
            )
        with mock.patch.dict(os.environ, {"EPIC7_CHECK_WORKERS": "0"}):
            self.assertEqual(1, check_module.choose_workers(70))
        # 写坏了就当没写，回到按内存判断 —— 不能因为一个环境变量把门禁搞挂。
        with mock.patch.dict(os.environ, {"EPIC7_CHECK_WORKERS": "不是数字"}):
            with self._with_memory(64.0):
                self.assertEqual(4, check_module.choose_workers(70))

    def test_run_tests_actually_uses_it(self):
        # 留着新函数却还在用旧常量 = 等于没改。
        self.assertIn("workers = choose_workers(", CHECK_SOURCE)
        self.assertNotIn("min(PARALLEL_WORKERS", CHECK_SOURCE)


class ConsoleEncodingTests(unittest.TestCase):
    """控制台编码兜底：编不出的字符只能变成 "?"，不能把门禁或实跑打死。

    实测（2026-09-30）：本机控制台是 GBK，`print("⇒")` 抛 UnicodeEncodeError。
    在门禁里那是「提交失败但看不出原因」；在实跑里那是**整条路线报失败**
    （异常从 runtime.log 里穿出来）。所以有两道防线，各钉一条。
    """

    def test_the_gate_hardens_its_stdout(self):
        self.assertIn('reconfigure(errors="replace")', CHECK_SOURCE)

    def test_the_cli_entry_hardens_its_stdout(self):
        main_source = (
            Path(__file__).resolve().parents[1] / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn('reconfigure(errors="replace")', main_source)

    def test_no_printable_string_carries_a_non_console_character(self):
        """源码里随便用 ⇒ / ⚠️；但**会被打印或抛出**的字符串里不许有。

        ⚠️ 判据必须走 AST，不能按行扫：注释和 docstring 里写 "⇒" 完全无害，而按行扫会
        把**本用例自己的 docstring**（它要举例说明这件事）当成违规 —— 2026-09-30 第一版
        就是这么自己撞自己的。AST 天然分得清「字符串常量」与「注释」。

        这个审计写成用例，是为了让新加的日志自己撞上来 —— 人工 review 抓不住。
        """
        offenders: list[str] = []
        root = Path(__file__).resolve().parents[1]
        for path in sorted(root.rglob("*.py")):
            parts = set(path.parts)
            if "__pycache__" in parts or "runtime_logs" in parts:
                continue
            for number, text in _console_bound_strings(path):
                if "⇒" in text or "⚠️" in text:
                    offenders.append(f"{path.name}:{number}: {text[:60]}")
        self.assertEqual([], offenders, "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
