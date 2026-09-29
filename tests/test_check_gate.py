"""验证门槛（`tools/check.py`）的护栏。

守的是 2026-09-25 定的规矩：**改多少验多少，小改动不许白跑全量**。

门槛本身会按改动范围选测试，但日常爱敲的 `check.py --vs HEAD` 取的是「工作区相对 HEAD 的
**全部**改动」⇒ 上一轮没提交的共享模块会把判定永久拖成全量（2026-09-25 实测：只想验一行
改动，连跑两次全量 408s / 457s，而局部只要 28.7 秒）。

所以这里守住两件事：

1. 判成全量时**一定会**喊话（为什么全量 + 怎么改成定向）—— 让「白跑 7 分钟」在屏幕上
   变得刺眼；
2. 暂存区为空、退化成「整个工作区判定」时**一定会**提醒 —— 这是白跑的头号成因。

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
