"""公共流程「动作验收」表态机制的护栏测试。

## 为什么要这套东西

2026-09-25 实跑翻车暴露一个盲区：项目早有「每个动作都要长眼睛」的硬规矩，
但它的检查点是**路线 Runner 经 `machine.next_action()` 发的动作**
（`runner_base._require_transition_contract`）。而
`navigation` / `home_return` / `global_popups` 这些
**公共流程**同样在发动作，却**不经过任何路线的状态机** ⇒ 完全在管辖外。

（`unknown_screen` 当时也在这一串里：它靠「点屏幕中央」唤醒，那一下没有判据，
只能给它开豁免。2026-09-26 把「点中央」整段删掉之后它已经不发动作了 ——
它从清单和表态表里都划掉，豁免名单因此变成空的，见本文件末尾那条测试。）

`return_home_v2` 重写时把老实现的验收整段丢了，实跑出现「同一层连按两次 ESC」，
**没有任何机制拦下这个改动**。

`games/epic7/public_flow_verification.py` 就是补这个洞：给公共流程建一张
「表态表 + 加载期自查」，与 `modes.RESUME_EXEMPT` / `TRANSITION_EXEMPT` 同构。

## 这个文件守什么

1. **表态机制本身能发现漏**：漏登记、漏表态、表态不合规，都要报错。
2. **反向护栏**：源码里实际带动作的模块必须都在清单里 ——
   防「新写了公共流程忘了登记」，那种漏**不会让任何测试变红**。
3. **清单不能是摆设**：每个模块的表态内容要能对上真实的代码
   （比如声称用某个判据，那个判据就得真在代码里）。
"""

import ast
import collections
import unittest
from pathlib import Path

from auto_game_unified.games.epic7 import public_flow_verification as pfv


PACKAGE_DIR = Path(pfv.__file__).resolve().parent


class DeclarationGateTests(unittest.TestCase):
    """表态机制本身：漏了必须报错（fail-closed）。"""

    def test_the_real_repository_satisfies_both_checks(self):
        """当前仓库状态必须是合规的 —— 这是基线。"""
        pfv.assert_module_inventory_matches(PACKAGE_DIR)
        pfv.assert_public_flow_verification_declared()

    def test_the_load_time_check_is_wired_into_production_code(self):
        """加载期自查必须**真的被生产代码调用** —— 只在测试里跑等于没做。

        ⚠️ 这条守的是一个**已经真的发生过**的坑：项目里
        ``modes._assert_resume_declared()`` 与 ``_assert_transition_stance_declared()``
        **生产代码一处都没调**，只在测试里跑 —— 于是文档承诺的「import 阶段就报错」
        是一句空话（2026-09-25 核对发现）。

        所以本模块的自查**必须**接进 ``main._install_finish_home``，
        与既有的 ``_assert_finish_home_declared()`` 并排。
        这条测试就是钉住那个接线：谁把它删了，这里立刻红。

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
            "assert_public_flow_verification_declared",
            called,
            "公共流程的表态自查必须被生产代码真正调用，"
            "否则它和 modes._assert_resume_declared 一样只是摆设",
        )

        # 蹭车确认：它应当跟 `_assert_finish_home_declared()` 在同一个函数里，
        # 而不是散落在某个不相干的位置（那样会在错误的时机触发或永不触发）。
        installers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_install_finish_home"
        ]
        self.assertTrue(installers, "找不到 _install_finish_home")
        install_src = ast.get_source_segment(source, installers[0]) or ""
        self.assertIn(
            "_assert_finish_home_declared",
            install_src,
            "两个加载期自查应当并排放在一起，便于对照维护",
        )

    def test_a_missing_declaration_is_rejected(self):
        """模块带动作却不在清单里 ⇒ 报错（**这条就是抓 `return_home_v2` 那种漏**）。"""
        original = pfv.ACTION_BEARING_MODULES
        pfv.ACTION_BEARING_MODULES = frozenset(set(original) - {"home_return.py"})
        try:
            with self.assertRaises(RuntimeError) as caught:
                pfv.assert_module_inventory_matches(PACKAGE_DIR)
            self.assertIn("home_return.py", str(caught.exception))
        finally:
            pfv.ACTION_BEARING_MODULES = original

    def test_a_module_without_a_stance_is_rejected(self):
        """在清单里、却不在表态表里 ⇒ 报错。"""
        original = dict(pfv.PUBLIC_FLOW_VERIFICATION)
        try:
            del pfv.PUBLIC_FLOW_VERIFICATION["home_return.py"]
            with self.assertRaises(RuntimeError) as caught:
                pfv.assert_public_flow_verification_declared()
            self.assertIn("home_return.py", str(caught.exception))
        finally:
            pfv.PUBLIC_FLOW_VERIFICATION.clear()
            pfv.PUBLIC_FLOW_VERIFICATION.update(original)

    def test_a_stance_cannot_be_both_ways(self):
        """``mechanism`` 与 ``exempt_reason`` **都写** ⇒ 报错（只能二选一）。"""
        original = pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"]
        try:
            pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"] = (
                pfv.PublicFlowVerification(
                    module="navigation.py",
                    mechanism="有机制",
                    exempt_reason="又说不必",
                )
            )
            with self.assertRaises(RuntimeError):
                pfv.assert_public_flow_verification_declared()
        finally:
            pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"] = original

    def test_a_stance_cannot_be_neither(self):
        """两边**都不写** ⇒ 报错（不许用空白充数）。"""
        original = pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"]
        try:
            pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"] = (
                pfv.PublicFlowVerification(module="navigation.py")
            )
            with self.assertRaises(RuntimeError):
                pfv.assert_public_flow_verification_declared()
        finally:
            pfv.PUBLIC_FLOW_VERIFICATION["navigation.py"] = original

    def test_the_table_and_the_inventory_must_agree(self):
        """表态表里有、清单里没有 ⇒ 报错（两边必须一致）。"""
        original = pfv.ACTION_BEARING_MODULES
        pfv.ACTION_BEARING_MODULES = frozenset(set(original) - {"navigation.py"})
        try:
            with self.assertRaises(RuntimeError) as caught:
                pfv.assert_public_flow_verification_declared()
            self.assertIn("navigation.py", str(caught.exception))
        finally:
            pfv.ACTION_BEARING_MODULES = original


class InventoryMatchesSourceTests(unittest.TestCase):
    """反向护栏：清单必须与真实源码一致（防「新模块忘了登记」）。"""

    def test_every_action_bearing_module_is_declared(self):
        """源码里所有真正调用 ``X.click/back/swipe`` 的公共流程模块都要在清单里。"""
        # ⚠️ **读生产代码里那个派生函数**，不再在本用例里抄一份路线清单：
        # 抄一份的后果是「路线清单改了、这里没跟上」，而那时本用例会**误报**
        # 新路线模块「带动作但没登记」（2026-10-06 社区签到就撞过一次）。
        routes = pfv.route_module_names()
        # 与 ``pfv.assert_module_inventory_matches`` 的 skip 保持一致：两个 Runner
        # 基类都是「路线 Runner 的骨架」，由路线级的三张表管，不算公共流程。
        skip = {
            "modes.py",
            "runner_base.py",
            "transactional_runner_base.py",
            "__init__.py",
            "public_flow_verification.py",
        }

        for path in sorted(PACKAGE_DIR.glob("*.py")):
            name = path.name
            if name.startswith("_") or name in skip or name in routes:
                continue
            has_action = pfv._calls_runtime_action(
                path, {"click", "back", "swipe"}
            )
            if has_action:
                self.assertIn(
                    name,
                    pfv.ACTION_BEARING_MODULES,
                    f"{name} 带动作但没登记进 ACTION_BEARING_MODULES",
                )

    def test_the_scanner_ignores_mentions_in_text(self):
        """扫描必须用 AST、不能看字符串 —— 否则文档里提一句 `runtime.click(` 就误报。

        这条不是假想：``public_flow_verification.py`` 自己的 docstring 里就写着
        ``runtime.click(``，字符串匹配会把它当成「带动作的模块」。
        """
        self.assertFalse(
            pfv._calls_runtime_action(Path(pfv.__file__), {"click", "back", "swipe"}),
            "本模块只在文档里提到动作，不该被判成带动作的模块",
        )

    def test_the_scanner_does_find_real_calls(self):
        """反向确认扫描不是「恒为 False」——那会让上一条变成空测试。"""
        self.assertTrue(
            pfv._calls_runtime_action(
                PACKAGE_DIR / "home_return.py", {"click", "back", "swipe"}
            )
        )


class StanceContentTests(unittest.TestCase):
    """表态的内容要能对上真实代码，不能是空话。"""

    def test_home_return_declares_the_observe_mechanism(self):
        """``home_return.py`` 的表态声称用「页面身份」验收 ⇒ 代码里必须真有这条链路。

        这条守的是 2026-09-25 的教训：**判据对了、但没接进主循环 = 白做**。
        光在表态表里写「我有机制」不算数，得真在代码里找得到。

        ⚠️ **断言的是真实符号和真实调用形状与次数，不是关键词**。第一版写的是
        ``assertIn("_verify_action", source)`` —— 结果它在**注释里**就能满足，
        而当时真正的类叫 ``_ActionVerifier``，代码一行验收都没有。
        关键词断言会被注释骗过去，等于没测。

        第二版改成「收集 ``verifier.X`` 的**方法名集合**」，仍然被变异逃掉了：
        拿掉一处 ``verifier.act(...)`` 之后，集合还是 ``{"act", "press_esc"}``，
        少的那一次没被看见。**所以现在数的是调用次数。**

        三条一起才成立：

        1. ``_ActionVerifier`` 这个类真的存在；
        2. 4 处点击**逐个**都经过 ``act``（少一处就红）；
        3. 2 处 ESC **逐个**都经过 ``press_esc``（少一处就红）；
        4. 4 处点击**逐个**都先查一次 ``is_retired``（少一处就红）；
        5. ``observe`` 真的是函数的形参（而不是写在文档里的词）。

        ⚠️ 第 4 条是 2026-10-19 事故之后加的闸门：**光验收不够，还得能换招**。
        那次商店页上「打开快捷菜单」每轮都被判「无效」，但主循环下一轮又选中它，
        重复 8 次、空耗 120 秒。``is_retired`` 就是那个「别再选它」的开关 ——
        哪一天有人新加一个点击分支却忘了查它，这条会红。
        """
        source = (PACKAGE_DIR / "home_return.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        classes = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        self.assertIn(
            "_ActionVerifier", classes, "v2 的验收器必须是个真实的类"
        )

        calls = collections.Counter(
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "verifier"
        )
        # 5 处点击：点酒馆 / 打开快捷菜单 / 放弃战斗 / 结束 / 关闭骑士团活动
        # （最后一条是 2026-11-06 加的：骑士团活动整屏页 PC 上 ESC 关不掉。
        #  ⚠️ 它只在 pc/ 有图时才会命中，但**调用点是静态存在的**，所以这里数 5。
        #  模拟器行为不受影响 —— 模板为 None 时 `_activity_close_point` 直接返回 None。）
        self.assertEqual(
            5,
            calls["act"],
            f"应当有 5 处点击经过验收，实际 {calls['act']} 处（少一处就是丢了眼睛）",
        )
        # 2 处 ESC：局内 / 兜底
        self.assertEqual(
            2,
            calls["press_esc"],
            f"应当有 2 处 ESC 经过验收，实际 {calls['press_esc']} 处",
        )
        # 5 道「这一招在这个页面上还有没有用」的闸门，与 5 处点击一一对应：
        # 只要有分支能点，它就得能被停用（见上面的第 4 条）。
        self.assertEqual(
            5,
            calls["is_retired"],
            f"5 个点击分支都该先查停用表，实际 {calls['is_retired']} 处",
        )
        self.assertEqual(
            {"act", "press_esc", "is_retired"},
            set(calls),
            "验收器上不该出现计划外的调用入口",
        )

        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "return_home_v2"
        }
        self.assertIn("return_home_v2", functions)
        arguments = {
            arg.arg
            for arg in (
                functions["return_home_v2"].args.args
                + functions["return_home_v2"].args.kwonlyargs
            )
        }
        self.assertIn("observe", arguments, "页面识别必须是真形参")

    def test_no_public_flow_module_is_exempt_from_the_rule(self):
        """豁免名单必须是**空的** —— 「未知画面」那条豁免已经随着「点屏幕中央」一起删掉。

        ⚠️ 这里原来断言「**唯一**豁免是 ``unknown_screen.py``」：它当时会「点屏幕中央
        唤醒」，那一下没有判据（中央常常落在列表空白处），所以只能给它开豁免。
        2026-09-26 用户抓包「眼睛瞎了一直点中间」⇒ 那段整段删掉，它现在**不发任何
        动作**（只观察、记诊断、交还上层）⇒ ``ACTION_BEARING_MODULES`` 与表态表里
        都划掉 ⇒ 豁免名单必须空着。

        这条防「豁免被偷着加回来」：以后想拿像素兜底，必须显式改表态表、
        被这条测试看见。
        """
        exempt = {
            name
            for name, entry in pfv.PUBLIC_FLOW_VERIFICATION.items()
            if entry.exempt_reason
        }
        self.assertEqual(set(), exempt)


if __name__ == "__main__":
    unittest.main()
