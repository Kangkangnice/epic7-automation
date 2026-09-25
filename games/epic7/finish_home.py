"""「收尾回首页」的豁免名单 + 加载期自查（路线准入的第三半）。

用户 2026-09-25 的诉求：后续要把多个任务**串起来**跑，所以每条路线做完都得停在
首页上，下一个任务才接得上。此前 10 条路线**一条都没有**这个动作。

本文件回答的是「这条路线跑完之后，要不要退回首页」。它与另外两张表形状刻意做成
一样的（一份表 + 一句理由 + 加载期自查），因为问的是同一类问题：
「这条路线有没有对某件事表过态」：

- ``modes.RESUME_EXEMPT`` 管「开局停在半路，做不做接力」；
- ``modes.TRANSITION_EXEMPT`` 管「跑起来之后，动作的出口验收靠什么」；
- **本文件**管「跑完之后，要不要退回首页」。

⚠️ 为什么单独成文件、而不留在 ``modes.py``：2026-09-25 这个文件与另一条新路线的
登记（``labyrinth_stone``）挤在 ``modes.py`` 里，按 hunk 切不干净（并发会话）。
独立出来既好切，也让「收尾回首页」的全部规矩集中在一处，不必翻 ``modes.py``。

判定规则见 ``_assert_finish_home_declared``：**实现方调了 `_close_out()`、或进本名单，
二选一**。漏了在 **import 阶段**就报错，不会等到串任务时才发现接不上。
注入钩子在 ``main._install_finish_home``。
"""

from __future__ import annotations

import ast
from typing import Optional

from auto_game_unified.games.epic7.modes import MODE_SPECS
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase


FINISH_HOME_EXEMPT = {
    "survivor": (
        "本路线 ``needs_navigation=False`` —— 起点是用户**人工**把游戏推进到活动小游戏"
        "内部再启动，连导航器都不会构建（``run_mode`` 里 navigator 恒为 None）。"
        "而且整轮都在小游戏内部，`survivor.py` 写死了「任何 Back 都可能退回活动主页"
        "那个未知状态」⇒ 强行回首页要从**从没勘探过**的页面里摸路，风险大于收益。"
        "**这是刻意例外，不是漏做**（用户 2026-09-25 拍板）。"
        "串任务时把 survivor 放最后一个，或它后面接的任务需要人工先回一下首页。"
    ),
}


def _finish_home_verdict(
    name: str,
    *,
    inherits_base: bool,
    exempt: bool,
    own_source: Optional[str],
    own_run_source: Optional[str],
) -> Optional[str]:
    """判一条路线「收尾回首页」的表态是否合法；返回错误文案，合法返回 None。

    抽成纯函数（不碰文件系统、不 import）是为了**可测**：加载期自查只负责
    收集源码，判据本身可以直接喂输入验，不必在测试里改磁盘上的源码再重载模块
    （那种写法在中途失败时会留下损坏的 .py，代价太大）。

    ``None``（源码取不到）一律**放过** —— 动态定义的对象（替身、REPL 里造的类）
    没有源码，不该把「读不到」升级成「程序起不来」。真实路线都是磁盘上的文件。
    """
    if inherits_base:
        # 基类路线：`ModeRunnerBase.run()` 统一收尾。**但它可能自己覆写 run()
        # 后忘了调 super()** —— 那就等于把收尾丢了，必须查出来。
        if own_run_source is not None and "super().run(" not in own_run_source:
            return (
                f"路线 {name} 继承了 ModeRunnerBase，但自己覆写了 run() "
                "却没在里面调 super().run() ⇒ 基类的收尾逻辑（`_close_out`）"
                "被整个跳过了，跑完不会回首页。要么别覆写 run()、要么记得调 super()。"
            )
        return None
    if own_source is None:
        return None
    calls_close_out = _calls_close_out(own_source)
    if calls_close_out and exempt:
        return (
            f"路线 {name} 既调了 `_close_out()`（已经会收尾回首页）、"
            "又躺在 FINISH_HOME_EXEMPT 里；两边只能写一边（接了就把豁免那条划掉）。"
        )
    if not calls_close_out and not exempt:
        return (
            f"路线 {name} 既不收尾回首页、也不在 FINISH_HOME_EXEMPT 里。"
            "要么在它的正常退出口前面调 `_close_out()`"
            "（裸定义路线自己声明一份，语义照 ModeRunnerBase._close_out），"
            "要么在 FINISH_HOME_EXEMPT 里写明为什么不做；"
            "规矩见 main._install_finish_home。"
        )
    return None


def _calls_close_out(source: str) -> bool:
    """源码里**真的**调用了 ``self._close_out()`` 吗（注释/字符串/文档串不算）。

    ⚠️ 为什么要解析而不是 ``"_close_out()" in source``：字符串匹配会把
    **注释掉的调用**（``# self._close_out()``）、以及**文档串里的举例**
    （本文件自己的 docstring 就写着 ``self._close_out()``）也算成「接了」。
    实测过：把一条路线的三处调用全注释掉，字符串匹配照样放行 —— 那这自查就是
    个摆设。改用 ``ast`` 看**真实语法树里有没有这个 Call 节点**。

    解析失败（源码片段不完整等）时退回字符串匹配，宁严勿松。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "_close_out()" in source
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "_close_out":
            return True
        if isinstance(func, ast.Name) and func.id == "_close_out":
            return True
    return False


def _assert_finish_home_declared() -> None:
    """加载期自查：每条路线都必须对「收尾回首页」表态。

    两种合法表态，二选一，**不能两边都写、也不能两边都不写**：

    - 实现了收尾（源码里能查到 ``_close_out()`` 的调用）；
    - 进 ``FINISH_HOME_EXEMPT`` 并写明理由（不做收尾）。

    ⚠️ **判据是「源码里真的调了 `_close_out()`」，不是「有没有那个方法」**：
    继承 ``ModeRunnerBase`` 的路线**天然有** ``_close_out``（基类定义），
    光看 ``hasattr`` 十条路线全过 —— 等于这条自查白写。真正的分界是
    「它的退出口前面有没有调用」，而这只有源码能回答。**而且必须是真调用**：
    注释掉的、文档串里举例提到的都不算（``_calls_close_out`` 用 ast 判定）。

    ⚠️ 因此本判据**只对裸定义（自带独立主循环）的路线有区分力**：基类路线的
    ``_close_out`` 调用在 ``ModeRunnerBase.run()`` 里，不在自己文件里。
    对它们改查「覆写了 run() 却没调 super() 吗」—— 那才是基类路线真会踩的坑。

    ⚠️ **查的是「源码文件里怎么写的」，不是「此刻对象上挂着什么」**：测试里常有
    ``mock.patch.object(StoryRunner, "run", fake_run)``，这时 ``StoryRunner.__dict__["run"]``
    已经是那个当地方了 —— 它当然没有 ``super().run()``，会把自查骗成「路线漏收尾」
    （2026-09-25 实测 6 条 story 接力用例因此变红）。所以这里**按类所在文件 + 类名**
    去磁盘源码里找，运行期被替换/打桩一概不影响判定。

    判据本体在 ``_finish_home_verdict``（纯函数，可单测）。只查结构，不跑行为
    —— 「收尾真的点了回大厅」由 ``tests/test_finish_at_home.py`` 用真 Runner 守住。
    """
    import inspect

    def _source_of(obj) -> Optional[str]:
        """取源码；取不到返回 None（fail-open，见 ``_finish_home_verdict``）。"""
        try:
            return inspect.getsource(obj)
        except (OSError, TypeError):
            return None

    def _class_source_on_disk(cls) -> Optional[str]:
        """从**源码文件**取 ``cls`` 的类体源码（绕过运行期打桩）。

        先拿类的定义文件，再在 AST 里按类名（含嵌套类名）定位，取那一段源码。
        取不到（动态类、内建、源码不存在）返回 None —— 交由判据 fail-open。
        """
        try:
            path = inspect.getsourcefile(cls)
            if path is None:
                return None
            with open(path, encoding="utf-8") as handle:
                file_source = handle.read()
            tree = ast.parse(file_source)
        except (OSError, TypeError, SyntaxError, ValueError):
            return None

        # 逐级按 __qualname__（Outer.Inner）在 AST 里找 ClassDef。
        # ⚠️ 起点是模块体的**语句列表**（tree.body），不是 Module 节点本身。
        names = cls.__qualname__.split(".")
        scope = list(tree.body)
        target = None
        for want in names:
            target = None
            for node in scope:
                if isinstance(node, ast.ClassDef) and node.name == want:
                    target = node
                    break
            if target is None:
                return None
            scope = list(target.body)
        try:
            return ast.get_source_segment(file_source, target)
        except (TypeError, ValueError):
            return None

    def _own_run_source_on_disk(cls) -> Optional[str]:
        """从源码文件里取 ``cls`` **自己写的** ``run`` 方法（没有则 None）。

        同样绕开运行期打桩：只要磁盘上那一段定义在，就算此刻被 mock 掉了也照查。
        """
        class_source = _class_source_on_disk(cls)
        if class_source is None:
            return None
        try:
            class_tree = ast.parse(class_source)
        except SyntaxError:
            return None
        if not class_tree.body or not isinstance(class_tree.body[0], ast.ClassDef):
            return None
        for node in class_tree.body[0].body:
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                try:
                    return ast.get_source_segment(class_source, node)
                except (TypeError, ValueError):
                    return None
        return None

    for name, spec in MODE_SPECS.items():
        runner_type = spec.runner_type
        inherits_base = issubclass(runner_type, ModeRunnerBase)
        if inherits_base:
            # ⚠️ 不再用 runner_type.__dict__.get("run")：那会被 mock 掉（见 docstring）。
            own_run_source = _own_run_source_on_disk(runner_type)
            own_source = None
        else:
            own_run_source = None
            # 裸定义路线同样按磁盘源码判「有没有真调 `_close_out()`」——
            # 这样测试里给 run() 打桩也不会把「已接上」骗成「没接」。
            own_source = _class_source_on_disk(runner_type)
            if own_source is None:
                own_source = _source_of(runner_type)
        error = _finish_home_verdict(
            name,
            inherits_base=inherits_base,
            exempt=name in FINISH_HOME_EXEMPT,
            own_source=own_source,
            own_run_source=own_run_source,
        )
        if error is not None:
            raise RuntimeError(error)
