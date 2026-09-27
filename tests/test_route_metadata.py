"""路线「元数据多处一致」自查机制的护栏测试。

## 这个文件守什么

`games/epic7/route_metadata.py` 把两类「同一事实抄在多处」变成 import 阶段报错：

1. **模式中文名**（抄在 Runner 的 ``_MODE_LABEL`` / ``main.MODE_LABELS`` /
   ``navigation.MODE_LABELS`` / ``launcher.MENU_OPTIONS`` / ``desktop.catalog.ROUTES``）；
2. **固定次数路线的默认轮次**（抄在 ``main.py`` / ``launcher.py`` / ``catalog.py``）。

这两类错在 2026-09-27 审查时都**实测到活的**：``survivor`` 一个名字在界面叫
「活动」、在命令行通知里叫「幸存者」；默认轮次那三处注释都写着「被测试钉住」，
**实际只钉住了 catalog**。

本文件守四件事：

- 判据本身在四种错误形态下都报错（缺条目 / 值不一致 / 多出幽灵路线 / 次数不一致）；
- **当前仓库是合规的**（基线，改完 survivor 名字之后必须能过）；
- 自查**真的被生产代码调用**（不是只在测试里跑的摆设 —— 这个坑项目里踩过）；
- AST 刮源码那部分**真的能刮到东西**，且不会把 ``main.py`` 里
  别的整数赋值误当成固定次数。
"""

import ast
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

        这是给 ``navigation``（不覆盖 needs_navigation=False 的路线）与
        ``launcher``（不列 survivor）留的口子 —— 它们是「刻意不登记」，
        不是漏改。若这条判据不成立，那些刻意缺项会被误报成漏改。
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
    """默认轮次判据：三处必须键集合相同、值相同。"""

    def test_the_current_fixed_cycles_agree(self):
        """基线：当前三处刮出来的固定次数必须一致。"""
        main = rm._main_fixed_cycles()
        launcher = rm._launcher_fixed_cycles()
        self.assertEqual(
            [],
            rm.default_cycles_consistency_errors(
                main_defaults=main,
                launcher_defaults=launcher,
                catalog_defaults=main,
            ),
        )

    def test_disagreeing_cycles_are_rejected(self):
        errors = rm.default_cycles_consistency_errors(
            main_defaults={"x": 2},
            launcher_defaults={"x": 3},
            catalog_defaults={"x": 2},
        )
        self.assertEqual(1, len(errors))
        self.assertIn("不一致", errors[0])

    def test_a_route_registered_in_only_one_place_is_rejected(self):
        """一处登记、另一处漏登记 ⇒ 报错（这比「值不同」更隐蔽）。"""
        errors = rm.default_cycles_consistency_errors(
            main_defaults={"x": 2},
            launcher_defaults={},
            catalog_defaults={"x": 2},
        )
        self.assertEqual(1, len(errors))
        self.assertIn("launcher.py", errors[0])


class SourceScanTests(unittest.TestCase):
    """AST 刮源码：要真刮到，且不误抓。"""

    def test_the_scanner_finds_the_real_fixed_cycle_routes(self):
        """四个「每天固定 N 次」的路线必须被刮出来，次数正确。

        这不是冗余 —— 它是 ``default_cycles_consistency_errors`` 的输入。
        扫描器若退回空字典，那条判据会**恒过**（三份空表当然一致），
        等于整个 B2 护栏失效。
        """
        self.assertEqual(
            {
                "hero_synthesis": 1,
                "world_boss": 2,
                "knights_donation": 1,
                "labyrinth_stone": 1,
            },
            rm._main_fixed_cycles(),
        )
        # launcher 用的是变量 ``mode`` 而不是 ``args.mode``，两条路径都要能刮。
        self.assertEqual(
            {
                "hero_synthesis": 1,
                "world_boss": 2,
                "knights_donation": 1,
                "labyrinth_stone": 1,
            },
            rm._launcher_fixed_cycles(),
        )

    def test_the_scanner_reads_ast_not_text(self):
        """扫描必须用 AST —— 否则文档里写一句 ``if args.mode == "x"`` 就误报。

        本模块自己的 docstring 里就写着那几行示例代码，字符串匹配会把它们
        当成真的固定次数。
        """
        self.assertEqual({}, rm._fixed_cycles_from_source(
            Path(rm.__file__), rm._MAIN_ARG_ATTR
        ))

    def test_a_missing_file_yields_nothing_rather_than_raising(self):
        """文件读不到 ⇒ 返回空表放过，**不升级成启动失败**。

        设计取舍：解析不到不该让程序起不来（真正的兜底是键集合比对 ——
        少登记会让另一处多出来的键被抓到）。
        """
        self.assertEqual(
            {}, rm._fixed_cycles_from_source(
                PACKAGE_DIR / "本文件不存在.py", rm._MAIN_ARG_ATTR
            )
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
