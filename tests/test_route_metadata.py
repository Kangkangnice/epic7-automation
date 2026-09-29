"""路线「元数据多处一致」自查机制的护栏测试。

## 这个文件守什么

`games/epic7/route_metadata.py` 把「同一事实抄在多处、只改了一部分」变成
import 阶段报错。它盯两块：

1. **模式中文名** —— ``main`` / ``navigation`` / ``desktop`` 那几张表
   在 2026-09-27 批次 2 之后都**派生自** ``modes.MODE_SPECS.label``；比对它们等于
   验证「派生链没被谁改回写死的」。各 Runner 的 ``_MODE_LABEL`` 是唯一无法派生的
   真副本（Runner 不能 import ``modes``，会成环）。
2. **固定次数** —— 批次 2 之后只在 ``ModeSpec.default_cycles`` 定义一次，
   所以判据从「多处比对」变成**防回潮**：``main.py`` 源码里
   再有写死的次数就报错。

这两类错在 2026-09-27 审查时都**实测到活的**：``survivor`` 一个名字在界面叫
「活动」、在命令行通知里叫「幸存者」；``shop_refresh`` 在每日任务里叫「商店刷新」、
别处叫「刷书签」；默认轮次那三处注释都写着「被测试钉住」，**实际只钉住了 catalog**。

本文件守五件事：

- 判据本身在各种错误形态下都报错（缺条目 / 值不一致 / 多出幽灵路线 / 写死次数）；
- **当前仓库是合规的**（基线）；
- 自查**真的被生产代码调用**（不是只在测试里跑的摆设 —— 这个坑项目里踩过）；
- AST 刮源码那部分**真的能刮到写死的次数**、且不把无关的整数赋值误报；
- 同一套 AST 刮法**真的能刮到 ``main.py`` 里的路线特判**、且不把属性读取误报。
"""

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from auto_game_unified.games.epic7 import route_metadata as rm


PACKAGE_DIR = Path(rm.__file__).resolve().parent


class LabelConsistencyTests(unittest.TestCase):
    """中文名判据：四种错误形态都要抓到。"""

    def test_the_real_repository_is_consistent(self):
        """基线：当前仓库必须一致（否则护栏一接上就 import 失败）。"""
        rm.assert_route_metadata_consistent()

    def test_a_copy_missing_a_required_route_is_rejected(self):
        """某副本缺一条**它必须覆盖**的路线 ⇒ 报错。"""
        errors = rm.label_consistency_errors(
            authoritative={"a": "甲", "b": "乙"},
            copies={"某副本": {"a": "甲"}},
            required_in={"某副本": frozenset({"a", "b"})},
        )
        self.assertEqual(1, len(errors))
        self.assertIn("b", errors[0])

    def test_a_copy_not_required_to_cover_is_left_alone(self):
        """副本没被告知要覆盖 ⇒ 有几个算几个，**不报缺**。

        这是给 ``navigation``（不覆盖 needs_navigation=False 的路线）留的口子 ——
        它是「刻意不登记」，不是漏改。若这条判据不成立，那些刻意缺项会被误报成漏改。
        """
        self.assertEqual(
            [],
            rm.label_consistency_errors(
                authoritative={"a": "甲", "b": "乙"},
                copies={"某副本": {"a": "甲"}},
                required_in={},
            ),
        )

    def test_a_copy_with_a_different_name_is_rejected(self):
        """同一路线在副本里的名字与权威账本不同 ⇒ 报错。"""
        errors = rm.label_consistency_errors(
            authoritative={"a": "甲"},
            copies={"某副本": {"a": "假"}},
            required_in={},
        )
        self.assertEqual(1, len(errors))
        self.assertIn("'假'", errors[0])
        self.assertIn("'甲'", errors[0])

    def test_a_copy_naming_a_phantom_route_is_rejected(self):
        """副本里有 ``MODE_SPECS`` 不认识的键 ⇒ 报错（删路线漏删 / 拼错）。"""
        errors = rm.label_consistency_errors(
            authoritative={"a": "甲"},
            copies={"某副本": {"a": "甲", "ghost": "鬼"}},
            required_in={},
        )
        self.assertEqual(1, len(errors))
        self.assertIn("ghost", errors[0])


class DefaultCyclesTests(unittest.TestCase):
    """固定次数判据（批次 2 之后）：``main.py`` 里**不许**再写死次数。

    批次 2 把次数收敛进 ``ModeSpec.default_cycles``，副本没了 ⇒ 判据从
    「多处比对」变成「防回潮」：源码里再冒出写死的次数就报错。
    """

    def test_the_repository_hardcodes_no_cycles(self):
        """基线：``main.py`` 里已经没有写死的次数。

        这条同时是扫描器的**反向确认** —— 它得先能刮到东西，才谈得上「刮不到」。
        （刮到东西的能力由 ``SourceScanTests`` 用假源码验证。）
        """
        self.assertEqual({}, rm._main_fixed_cycles())
        self.assertEqual(
            [],
            rm.default_cycles_consistency_errors(
                main_defaults=rm._main_fixed_cycles(),
            ),
        )

    def test_a_hardcoded_main_cycle_is_rejected(self):
        errors = rm.default_cycles_consistency_errors(
            main_defaults={"world_boss": 2}
        )
        self.assertEqual(1, len(errors))
        self.assertIn("main.py", errors[0])
        self.assertIn("world_boss", errors[0])


class SourceScanTests(unittest.TestCase):
    """AST 刮源码：要真刮到写死的次数，且不误抓无关代码。"""

    def _scan(self, source: str, subject: tuple[str, ...] = rm._MAIN_ARG_ATTR):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "sample.py"
        path.write_text(source, encoding="utf-8")
        try:
            return rm._fixed_cycles_from_source(path, subject)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_the_scanner_finds_hardcoded_cycles_in_both_shapes(self):
        """项目历史上真实出现过的两种写法都要刮到（``==`` 与 ``in`` 元组）。

        这条是「判据恒过」的反向确认：若扫描器退回空字典，
        ``DefaultCyclesTests`` 那条基线会**恒过**（空表当然干净），
        整个防回潮就失效了。
        """
        source = (
            "def main(args):\n"
            '    if args.mode == "world_boss" and args.max_cycles is None:\n'
            "        args.max_cycles = 2\n"
            "    if args.mode in (\"knights_donation\", \"labyrinth_stone\"):\n"
            "        args.max_cycles = 1\n"
        )
        self.assertEqual(
            {"world_boss": 2, "knights_donation": 1, "labyrinth_stone": 1},
            self._scan(source),
        )

    def test_the_scanner_ignores_unrelated_integer_assignments(self):
        """``if args.mode == "story": retries = 3`` 不是「写死了次数」。

        护栏误报会逼人绕过它（``--no-verify``），那就白做了 —— 所以扫描器
        必须认赋值目标名。
        """
        source = (
            "def main(args):\n"
            '    if args.mode == "story":\n'
            "        retries = 3\n"
            "        workers = 8\n"
        )
        self.assertEqual({}, self._scan(source))

    def test_the_scanner_reads_ast_not_text(self):
        """扫描必须用 AST —— 否则文档里写一句 ``if args.mode == "x"`` 就误报。

        本模块自己的 docstring 里就写着那几行示例代码，字符串匹配会把它们
        当成真的固定次数。
        """
        self.assertEqual(
            {}, rm._fixed_cycles_from_source(Path(rm.__file__), rm._MAIN_ARG_ATTR)
        )

    def test_a_missing_file_yields_nothing_rather_than_raising(self):
        """文件读不到 ⇒ 返回空表放过，**不升级成启动失败**。

        设计取舍：解析不到不该让程序起不来。
        """
        self.assertEqual(
            {},
            rm._fixed_cycles_from_source(
                PACKAGE_DIR / "本文件不存在.py", rm._MAIN_ARG_ATTR
            ),
        )


class RouteSpecialCaseTests(unittest.TestCase):
    """批次 3（C1）：``main.py`` 里不许再拿 ``spec.name`` 跟具体路线名分叉。

    那两处（刷书签实跑闸门、竞技场落盘参数）已经搬进 ``ModeSpec.preflight`` /
    ``ModeSpec.runner_options``。这条判据是**防回潮**：再写回去就报错。
    """

    def _scan(self, source: str):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "sample.py"
        path.write_text(source, encoding="utf-8")
        try:
            return rm._route_special_cases_from_source(path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_the_real_main_module_has_no_route_special_cases(self):
        """基线：``main.py`` 里已经没有路线特判（搬进注册钩子了）。

        这条同时是扫描器的**反向确认** —— 它得先能刮到东西，才谈得上「刮不到」。
        刮到的能力由下面两条用假源码验证。
        """
        self.assertEqual([], rm._main_route_special_cases())

    def test_the_scanner_finds_route_special_cases_in_all_shapes(self):
        """``==`` / ``!=`` / ``in`` 三种写法都要刮到（项目历史上出现过前两种）。"""
        source = (
            "def run_mode(spec, dry_run):\n"
            '    if spec.name == "shop_refresh" and not dry_run:\n'
            "        raise RuntimeError('停')\n"
            '    if spec.name in ("arena", "expedition"):\n'
            "        pass\n"
            '    if spec.name != "story":\n'
            "        pass\n"
        )
        self.assertEqual(
            ["sample.py:2", "sample.py:4", "sample.py:6"], self._scan(source)
        )

    def test_the_scanner_ignores_plain_attribute_reads(self):
        """``spec.name`` 当文案/参数用是正常写法，不是路线特判。

        误报会逼人绕过护栏（``--no-verify``），那就白做了 —— 所以判据只认
        **比较**（``Compare`` 节点），不认属性读取。
        """
        source = (
            "def run_mode(spec, dry_run):\n"
            '    runtime.log(f"模式={spec.name}")\n'
            "    runtime.save_diagnostic(f\"enter_mode_failed_{spec.name}\")\n"
            "    spec.resolve_state(args.start_state)\n"
            "    spec.name.upper()\n"
        )
        self.assertEqual([], self._scan(source))

    def test_the_scanner_reads_ast_not_text(self):
        """扫描必须用 AST —— 否则本模块 docstring 里的示例就被当成真代码。

        这条在本仓库是**真实风险**，不是假想：``route_metadata.py`` 与
        ``docs/EXTENDING.md`` 里都写着一模一样的 ``if spec.name == "shop_refresh"``。
        """
        self.assertEqual(
            [], rm._route_special_cases_from_source(Path(rm.__file__))
        )

    def test_a_missing_file_yields_nothing_rather_than_raising(self):
        """文件读不到 ⇒ 返回空列表放过，**不升级成启动失败**（同固定次数那条）。"""
        self.assertEqual(
            [],
            rm._route_special_cases_from_source(
                PACKAGE_DIR / "本文件不存在.py"
            ),
        )


class WiringTests(unittest.TestCase):
    """自查必须真的被生产代码调用，不能只在测试里跑。"""

    def test_the_load_time_check_is_wired_into_production_code(self):
        """``assert_route_metadata_consistent`` 必须被 ``main`` 真正调用。

        ⚠️ 这条守的是一个**已经真的发生过**的坑：项目里
        ``modes._assert_resume_declared()`` 一度**生产代码一处都没调**，
        只在测试里跑 ⇒ 文档承诺的「import 阶段报错」是空话。

        用 AST 查**调用**而不是文本查名字 —— 名字会出现在 import 行和注释里，
        文本匹配分不清「导入了」和「调用了」。
        """
        source = (PACKAGE_DIR.parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn(
            "assert_route_metadata_consistent",
            called,
            "路线元数据自查必须被生产代码真正调用，否则它只是摆设",
        )

        # 蹭车确认：应与另外几道加载期自查在同一个安装函数里。
        installers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_install_finish_home"
        ]
        self.assertTrue(installers, "找不到 _install_finish_home")
        install_src = ast.get_source_segment(source, installers[0]) or ""
        self.assertIn("_assert_finish_home_declared", install_src)
        self.assertIn("assert_public_flow_verification_declared", install_src)


if __name__ == "__main__":
    unittest.main()
