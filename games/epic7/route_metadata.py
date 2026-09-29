"""路线「元数据多处一致」的加载期自查。

## 为什么要单独立这么一份

「一条路线」这件事被拆成好几份事实，散在不同层。它们服务不同界面，形状本来就
不一样，所以**刻意保留各自的副本**（不是复制粘贴的偷懒，是各入口的展示需要在
不同数据结构里）：

| 副本 | 服务什么 | 覆盖范围 |
| --- | --- | --- |
| ``modes.MODE_SPECS`` | 路线**是什么**（状态机、Runner、起始状态、接力探针）—— 权威清单 | 10 条 |
| 各 Runner 的 ``_MODE_LABEL`` | 运行日志里那个中文名 | 只有继承 ``ModeRunnerBase`` / ``TransactionalRunnerBase`` 的 8 条 |
| ``main.MODE_LABELS`` | CLI 输出与 QQ 通知里的中文名 | 10 条 |
| ``navigation.MODE_LABELS`` | 导航完成日志里的中文名 | 只有 ``needs_navigation=True`` 的 9 条 |
| ``desktop.catalog.ROUTES`` | 桌面助手的中文名 | 10 条 |

由此带来一类**没有任何机制能发现**的错。2026-09-27 审查时实测到一个活例子：
**模式中文名漂移**：``main.MODE_LABELS`` 有 ``survivor: "幸存者"``，
而 ``navigation.MODE_LABELS`` **整条漏了 survivor** ⇒
``MODE_LABELS.get(mode, mode)`` 悄悄退化成英文名。因为 survivor
``needs_navigation=False`` 走不到那条日志，所以一直没人发现。

⇒ 本模块把「同一事实的多处副本必须一致」变成 **import 阶段报错**。

## ⚠️ 批次 2 之后本模块的重心变了（2026-09-27）

审查报告的 **批次 2**（A1 + B1）已经把**次数**收敛成单一来源：固定次数现在只在
``ModeSpec.default_cycles`` 里定义，``main.py`` / ``desktop/catalog.py``
全部从它读 —— **没有副本了**。

所以 ``default_cycles_consistency_errors`` 不再是「多处比对」，改成**防回潮**：
``main.py`` 的源码里不该再冒出写死的次数（有人从旧代码抄回来就会跟
``MODE_SPECS`` 各说各话）。

**中文名**则仍有真副本 —— 上面那几张表现在都是**从 ``MODE_SPECS.label`` 派生**的，
比对它们等于「验证派生链没被谁改成写死的」。各 Runner 的 ``_MODE_LABEL`` 是唯一
无法派生的（Runner 不能 import ``modes``，会成环），必须靠本模块盯着。

## 第三块：``main.py`` 里不许再出现路线特判（批次 3，2026-09-27）

审查报告的 **批次 3**（C1）把 ``main.run_mode`` 里仅有的两处路线特判
（``if spec.name == "shop_refresh"`` 的实跑闸门、``if spec.name == "arena"`` 的
落盘参数）挪进了 ``ModeSpec.preflight`` / ``ModeSpec.runner_options``。
那两处本来就违反 ``docs/EXTENDING.md`` 的「不要在 ``main.py`` 添加新的条件分支」，
而且会随路线数量线性膨胀。

挪完之后加这道**防回潮**（同 ``default_cycles`` 那条的思路）：``main.py`` 里再出现
拿 ``spec.name`` 跟具体路线名比的分支就报错，逼作者改走注册钩子。

## 边界（刻意不做的）

- **只查一致性，不查对不对**：不判断「世界首领战该 2 次还是 3 次」，
  只判断「各处说的是不是同一个数」。业务判断归人。
- **不查判据准不准**：同 ``modes._assert_resume_declared`` 的定位。
- **不要求「所有副本覆盖所有路线」**：每个副本各有各的正当覆盖范围
  （见上表），硬要求全覆盖会把「刻意不登记」误报成漏改。
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "label_consistency_errors",
    "default_cycles_consistency_errors",
    "assert_route_metadata_consistent",
]

# ---- 中文名一致性 ---------------------------------------------------------


def label_consistency_errors(
    *,
    authoritative: dict[str, str],
    copies: dict[str, dict[str, str]],
    required_in: dict[str, frozenset[str]],
) -> list[str]:
    """校验「模式中文名」的各处副本；返回错误文案列表（空 = 全一致）。

    抽成**纯函数**（不 import 任何业务模块、不碰磁盘）是为了可测：
    测试可以直接喂字典验判据，不必改磁盘源码再重载模块。

    参数说明：

    - ``authoritative``：以哪本账为准（本模块传 ``main.MODE_LABELS``，
      它是覆盖面最全的一份：10 条路线全在）。
    - ``copies``：``{副本显示名: {模式: 中文名}}``。只比对**该副本自己登记了**
      的路线，不要求它登记全部 —— 覆盖范围由 ``required_in`` 单独管。
    - ``required_in``：``{副本显示名: 该副本必须覆盖的模式集合}``。
      没列进来的副本视为「不需要覆盖任何特定路线」（有几个算几个）。

    规则三条：

    1. **该覆盖的必须覆盖**：``required_in[副本]`` 里的模式，副本里不能缺
       （survivor 漏在 navigation 里就是这条抓的）；
    2. **值必须与 authoritative 相同**：同一路线在不同界面显示两个名字，
       用户会以为选择没生效；
    3. **不能出现不存在的路线名**：副本里写了 ``MODE_SPECS`` 里没有的键
       ⇒ 那条路线的名字根本没人会读到，是改漏后的残留。
    """
    errors: list[str] = []

    for copy_name, table in copies.items():
        missing = sorted(required_in.get(copy_name, frozenset()) - set(table))
        if missing:
            errors.append(
                f"{copy_name} 缺这些路线的中文名：{missing}（新增路线时漏改了这里）"
            )

    for copy_name, table in copies.items():
        stale = sorted(set(table) - set(authoritative))
        if stale:
            errors.append(
                f"{copy_name} 里有 {stale}，但它们不是已登记的路线"
                "（可能是删路线时漏删，或模式名拼错）"
            )

    for copy_name, table in copies.items():
        for mode in sorted(set(table) & set(authoritative)):
            if table[mode] != authoritative[mode]:
                errors.append(
                    f"{copy_name} 里 {mode} 的中文名是 {table[mode]!r}，"
                    f"而 main.MODE_LABELS 里是 {authoritative[mode]!r}；"
                    "同一路线的名字应当一致（否则日志与界面会出现两个名字）"
                )
    return errors


# ---- 默认轮次一致性 -------------------------------------------------------


def default_cycles_consistency_errors(*, main_defaults: dict[str, int]) -> list[str]:
    """校验「``main.py`` 里**没有**写死的固定次数」；返回错误文案（空 = 干净）。

    ⚠️ 2026-09-27 起，固定次数只由 ``modes.MODE_SPECS`` 定义一次，
    ``main.py`` / ``desktop/catalog.py`` 全部从它读。
    所以本判据**不再是「多处比对」**（没有副本了），而是**防回潮**：
    源码里不该再出现 ``if <mode> == "...": ... = <次数>`` 这种硬编码 ——
    一旦出现，说明有人从旧代码/旧注释里抄回来了，那就会与 ``MODE_SPECS`` 各说各话。

    **写死就报错，哪怕值与 spec 恰好相同** —— 那是一份会漂移的副本，
    留着它等于把刚拆掉的坑重新挖开。要固定次数请改 ``ModeSpec.default_cycles``。

    读源码而不是读运行时值，是因为要抓的正是「源码里写死了什么」。
    """
    errors: list[str] = []
    for mode in sorted(main_defaults):
        errors.append(
            f"main.py 里给 {mode} 写死了 {main_defaults[mode]} 次；"
            "固定次数现在只在 MODE_SPECS 的 default_cycles 里定义一次，"
            "请改回从那里读（要调次数就改那个字段）。"
        )
    return errors


# ---- 加载期自查入口 -------------------------------------------------------


def assert_route_metadata_consistent() -> None:
    """加载期自查入口：两块一致性都过才放行（fail-closed）。

    ⚠️ **延迟 import 是刻意的**：本模块会被 ``main`` 一侧引用，而这里要读
    ``desktop.catalog`` / ``navigation`` —— 顶层 import 会成环。
    项目里 ``finish_home`` / ``public_flow_verification`` 用的是同一招。

    ⚠️ 触发点在 ``main._install_finish_home``（与另外几道自查同一位置）：
    这样它跑在**生产路径**上，不只是测试里跑。
    """
    from auto_game_unified.desktop import catalog
    from auto_game_unified.games.epic7 import modes, navigation
    from auto_game_unified.main import MODE_LABELS as main_labels

    mode_specs = modes.MODE_SPECS
    needs_navigation = frozenset(
        name for name, spec in mode_specs.items() if spec.needs_navigation
    )

    # 各副本「该覆盖哪些」的划定 —— 每一条都对应一个真实现象，不是拍脑袋：
    #
    # ⚠️ 批次 2 之后，下面这几份里除 Runner 的 ``_MODE_LABEL`` 外**都是派生的**
    # （``main`` / ``navigation`` / ``catalog`` 统统读 ``MODE_SPECS.label``）。
    # 比对它们不再是为了「发现漂移」，而是**验证派生链没被谁改回写死的** ——
    # 例如有人把 ``catalog.RouteInfo.label`` 从 property 改回一个字面量字段，
    # 只要值改了这里就报错。``_MODE_LABEL`` 是唯一真副本（Runner 不能 import
    # ``modes``，会成环）。
    #
    # - navigation：只服务导航完成的日志，needs_navigation=False 的路线
    #   （survivor）连导航器都不构建 ⇒ 不要求它。（survivor 那条漂移就是
    #   因为过去没这条规矩才没人发现；见模块开头。）
    # - Runner 的 _MODE_LABEL：只有继承基类的路线才有这个类属性；
    #   shop_refresh / survivor 是裸主循环 ⇒ 只要求「有 _MODE_LABEL 的
    #   必须与 spec.label 一致」，不要求都有。
    # - catalog：桌面助手是唯一的路线总览面板 ⇒ 要求全覆盖（含 survivor）。
    runner_labels = {
        name: label
        for name, spec in mode_specs.items()
        if (label := getattr(spec.runner_type, "_MODE_LABEL", ""))
    }
    catalog_labels = {route.mode: route.label for route in catalog.ROUTES}

    errors = label_consistency_errors(
        authoritative=dict(main_labels),
        copies={
            "各 Runner 的 _MODE_LABEL": runner_labels,
            "navigation.MODE_LABELS": dict(navigation.MODE_LABELS),
            "desktop.catalog.ROUTES": catalog_labels,
        },
        required_in={
            # main 是权威账本，不要求它比 MODE_SPECS 多；但它必须全覆盖。
            "navigation.MODE_LABELS": needs_navigation,
            "desktop.catalog.ROUTES": frozenset(mode_specs),
        },
    )
    # main.MODE_LABELS 自己必须覆盖全部路线（它没有 needs_navigation 之分）。
    missing_in_main = sorted(frozenset(mode_specs) - set(main_labels))
    if missing_in_main:
        errors.append(
            f"main.MODE_LABELS 缺这些路线：{missing_in_main}；"
            "它是 CLI 输出与 QQ 通知的中文名来源"
        )

    errors += default_cycles_consistency_errors(
        main_defaults=_main_fixed_cycles(),
    )

    special_cases = _main_route_special_cases()
    if special_cases:
        errors.append(
            f"main.py 里又出现了拿 spec.name 跟具体路线名比的分支：{special_cases}；"
            "路线专属的校验请写进 modes.MODE_SPECS 的 preflight，"
            "路线专属的构造参数请写进 runner_options —— "
            "不要在 main.py 里加条件分支（docs/EXTENDING.md 明写）。"
        )

    if errors:
        raise RuntimeError(
            "路线元数据不一致（同一事实抄在多处、只改了一部分）：\n  - "
            + "\n  - ".join(errors)
            + "\n\n新增/改动路线时请把这些副本一起改。背景与后续的「单一事实源」"
            "方案见 docs/maintenance/route_extensibility_review.md。"
        )


def _main_fixed_cycles() -> dict[str, int]:
    """``main.py`` 源码里写死的固定次数 → {模式: 次数}。

    正常情况**应当返回空字典**（次数从 ``MODE_SPECS`` 读）。返回非空只有两种可能：
    有人把次数硬编码抄回来了，或者扫描器把无关的 ``if args.mode == "x": n = 1``
    误认成了次数 —— 两种都该看一眼。

    ⚠️ **用 AST 解析源码，不用运行 ``main()``**：这里要的是「源码里写了什么」，
    不是「这次调用会得到什么」（那取决于命令行参数）。
    """
    return _fixed_cycles_from_source(_MAIN_PATH, _MAIN_ARG_ATTR)


def _main_route_special_cases() -> list[str]:
    """``main.py`` 里拿 ``spec.name`` 跟具体路线名比的分支（正常应为**空列表**）。

    路线专属的校验与构造参数现在都在 ``MODE_SPECS`` 注册项旁边
    （``ModeSpec.preflight`` / ``ModeSpec.runner_options``）。这里返回非空，
    说明有人又在 ``main.py`` 里写了 ``if spec.name == "某路线"`` ——
    那会让 ``main.py`` 随路线数量线性膨胀，且新增路线的人不会想到要来这儿改。

    ⚠️ **用 AST，不用文本匹配**：本模块的 docstring、``docs/EXTENDING.md`` 和
    审查报告里都写着 ``if spec.name == "shop_refresh"`` 这种示例，字面量匹配会把
    注释和文档里的示例当成真代码，护栏立刻变成误报机器。
    """
    return _route_special_cases_from_source(_MAIN_PATH)


# ---- AST 解析实现 ---------------------------------------------------------

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PATH = _PACKAGE_ROOT / "main.py"
# main.py 里比较的是 ``args.mode``（参数对象属性）。
_MAIN_ARG_ATTR = ("args", "mode")
# 路线特判认的是 ``spec.name``（``run_mode`` 拿到的那份路线注册项）。
_ROUTE_HANDLE = ("spec", "name")
# 次数赋值的目标名：``main.py`` 里是 ``args.max_cycles``。
_CYCLE_TARGET_NAMES = frozenset({"max_cycles", "cycles"})


def _fixed_cycles_from_source(path: Path, subject: tuple[str, ...]) -> dict[str, int]:
    """从一份 py 源码里刮出「写死的固定次数」→ {模式: 次数}。

    要抓的就是这种（2026-09-27 批次 2 之前 ``main.py`` 里真实存在过、
    后来改成从 ``MODE_SPECS`` 读了）：

    ```python
    # main.py
    if args.mode == "world_boss" and args.max_cycles is None:
        args.max_cycles = 2
    if args.mode in ("knights_donation", "labyrinth_stone") and args.max_cycles is None:
        args.max_cycles = 1
    ```

    ⚠️ **只认赋给 ``max_cycles`` / ``cycles`` 的整数常量**（见
    ``_assigned_int_constant``）—— 否则 ``if args.mode == "story": retries = 3``
    会被误报成「写死了 story 跑 3 次」。

    ⚠️ 刮不到就返回空字典（``OSError`` / ``SyntaxError`` 也吞）：这里要的是
    「源码里写死了什么」，程序**正常状态下就该是空的**。解析失败不该升级成
    「程序起不来」—— 真出了问题，``main`` 自己的行为会先露馅。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}

    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        matched = _matched_modes(node.test, subject)
        if not matched:
            continue
        value = _assigned_int_constant(node.body)
        if value is None:
            continue
        for mode in matched:
            found[mode] = value
    return found


def _matched_modes(test: ast.expr, subject: tuple[str, ...]) -> list[str]:
    """这个条件表达式里有没有 ``<subject> == "xxx"`` / ``<subject> in ("a", "b")``。

    返回它命中的模式名列表（没有就返回空列表）。

    ``and`` / ``or`` 链会**逐项看**，不只看最左边那个 —— 项目里的常见写法是
    ``if args.mode == "world_boss" and args.max_cycles is None:``（模式在左边），
    但 ``if not dry_run and args.mode == "arena":`` 这种反过来的也要认。
    """
    if isinstance(test, ast.BoolOp):
        candidates = list(test.values)
    else:
        candidates = [test]

    for candidate in candidates:
        if not isinstance(candidate, ast.Compare) or len(candidate.ops) != 1:
            continue
        if not _is_subject(candidate.left, subject):
            continue
        comparator = candidate.comparators[0]
        op = candidate.ops[0]
        if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
            if isinstance(comparator.value, str):
                return [comparator.value]
        if isinstance(op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List)):
            return [
                element.value
                for element in comparator.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            ]
    return []


def _is_subject(node: ast.expr, subject: tuple[str, ...]) -> bool:
    """``node`` 是不是 ``args.mode``（元组长度 2）或 ``mode``（长度 1）。"""

    if len(subject) == 2:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == subject[1]
            and isinstance(node.value, ast.Name)
            and node.value.id == subject[0]
        )
    return isinstance(node, ast.Name) and node.id == subject[0]


def _assigned_int_constant(body: list[ast.stmt]) -> int | None:
    """这个 ``if`` 体里有没有 ``<次数目标> = <整数常量>``；有就返回那个整数。

    ⚠️ **要认赋值目标名**（``max_cycles`` / ``cycles``），不能「体里出现任何整数赋值
    就算」—— 否则 ``if args.mode == "story": retries = 3`` 这种无关代码会被误报成
    「写死了 story 跑 3 次」。护栏误报会逼人绕过它，那就白做了。
    """
    for statement in body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Name):
            name = target.id
        else:
            continue
        if name not in _CYCLE_TARGET_NAMES:
            continue
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
    return None


def _route_special_cases_from_source(path: Path) -> list[str]:
    """刮出一份 py 源码里「拿 ``spec.name`` 跟路线名比」的位置，形如 ``main.py:385``。

    认四种比较：``==`` / ``!=`` / ``in`` / ``not in``。
    **不认属性读取**（``f"模式={spec.name}"``、``HomeReturn(mode=spec.name)``、
    ``spec.name`` 当参数传下去）—— 那些是正常用法，判据只针对「按路线名分叉」。

    与 ``_fixed_cycles_from_source`` 同一套取舍：读不到 / 解析失败就返回空列表，
    **不升级成启动失败**（程序正常状态下这里就该是空的）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []

    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not _is_subject(node.left, _ROUTE_HANDLE):
            continue
        if any(
            isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops
        ):
            found.append(node.lineno)
    # 按行号排序再出文案：``ast.walk`` 是广度优先，出参顺序**不是**源码顺序
    # （嵌套深的那个反而排在后面），报错时读起来会莫名其妙。
    return [f"{path.name}:{lineno}" for lineno in sorted(found)]
