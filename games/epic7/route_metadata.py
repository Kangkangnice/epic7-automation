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
| ``launcher.MENU_OPTIONS`` | 交互菜单的编号 → 中文名 | 只有能从菜单进的 9 条 |
| ``desktop.catalog.ROUTES`` | 桌面助手的中文名、默认次数、是否可编辑 | 10 条 |
| ``main.py`` / ``launcher.py`` / ``catalog.py`` | 固定次数路线的默认轮次 | 只有 4 条「每天固定 N 次」的 |

由此带来一类**没有任何机制能发现**的错。2026-09-27 审查时实测到两个活例子：

1. **模式中文名漂移**：``main.MODE_LABELS`` 有 ``survivor: "幸存者"``，
   而 ``navigation.MODE_LABELS`` **整条漏了 survivor** ⇒
   ``MODE_LABELS.get(mode, mode)`` 悄悄退化成英文名。因为 survivor
   ``needs_navigation=False`` 走不到那条日志，所以一直没人发现。
2. **默认轮次三处不一致**：``main.py`` / ``launcher.py`` / ``desktop/catalog.py``
   三处注释都写着「与另外两处保持一致（都被测试钉住）」，但**实测只钉住了 catalog**
   —— 另两处没有任何交叉校验。

⇒ 本模块把「同一事实的多处副本必须一致」变成 **import 阶段报错**。

## 边界（刻意不做的）

- **只查一致性，不查对不对**：不判断「世界首领战该 2 次还是 3 次」，
  只判断「三个地方说的是不是同一个数」。业务判断归人。
- **不做单一事实源重构**：那是审查报告里的 A1/B1 方案。
  本模块是它之前的「先让漏改报错」这一步。
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


def default_cycles_consistency_errors(
    *,
    main_defaults: dict[str, int],
    launcher_defaults: dict[str, int],
    catalog_defaults: dict[str, int],
) -> list[str]:
    """校验「固定次数路线的默认轮次」在三处一致；返回错误文案（空 = 全一致）。

    三处副本服务不同入口：

    - ``main.py``：命令行 ``--max-cycles`` 的兜底；
    - ``launcher.py``：交互菜单不问次数时的取值；
    - ``desktop/catalog.py``：桌面助手界面里那个（置灰的）次数框。

    ⚠️ 三处**只登记「不受用户控制的固定次数」路线**
    （hero_synthesis / world_boss / knights_donation / labyrinth_stone）。
    用户可自由填次数的路线（arena 等）不进来 —— 那些没有「默认值」这件事，
    各入口都是问用户/弹输入框，不构成需要一致的事实。

    规则两条：**键集合必须相同**（一处登记、另一处漏登记 = 漏改）；
    **值必须相同**（同一个数抄在三处，要一起改）。
    """
    errors: list[str] = []
    keys = set(main_defaults) | set(launcher_defaults) | set(catalog_defaults)
    for mode in sorted(keys):
        values = {
            "main.py": main_defaults.get(mode),
            "launcher.py": launcher_defaults.get(mode),
            "desktop/catalog.py": catalog_defaults.get(mode),
        }
        missing = sorted(name for name, value in values.items() if value is None)
        if missing:
            errors.append(
                f"固定次数路线 {mode} 在 {missing} 里没有登记（其他入口登记了）；"
                "漏登记会让该入口拿到一个错的（或没有）默认次数"
            )
            continue
        if len(set(values.values())) != 1:
            errors.append(
                f"固定次数路线 {mode} 三处的默认次数不一致：{values}；"
                "同一个数抄在三处，必须一起改"
            )
    return errors


# ---- 加载期自查入口 -------------------------------------------------------


def assert_route_metadata_consistent() -> None:
    """加载期自查入口：两块一致性都过才放行（fail-closed）。

    ⚠️ **延迟 import 是刻意的**：本模块会被 ``main`` 一侧引用，而这里要读
    ``launcher`` / ``desktop.catalog`` / ``navigation`` —— 顶层 import 会成环。
    项目里 ``finish_home`` / ``public_flow_verification`` 用的是同一招。

    ⚠️ 触发点在 ``main._install_finish_home``（与另外几道自查同一位置）：
    这样它跑在**生产路径**上，不只是测试里跑。
    """
    from auto_game_unified import launcher
    from auto_game_unified.desktop import catalog
    from auto_game_unified.games.epic7 import modes, navigation
    from auto_game_unified.main import MODE_LABELS as main_labels

    mode_specs = modes.MODE_SPECS
    needs_navigation = frozenset(
        name for name, spec in mode_specs.items() if spec.needs_navigation
    )

    # 各副本「该覆盖哪些」的划定 —— 每一条都对应一个真实现象，不是拍脑袋：
    #
    # - navigation：只服务导航完成的日志，needs_navigation=False 的路线
    #   （survivor）连导航器都不构建 ⇒ 不要求它。（survivor 那条漂移就是
    #   因为过去没这条规矩才没人发现；见模块开头。）
    # - launcher：只列能从交互菜单进的路线；survivor 要人工把游戏停在
    #   小游戏里才能跑，刻意不进菜单 ⇒ 不要求它。
    # - Runner 的 _MODE_LABEL：只有继承基类的路线才有这个类属性；
    #   shop_refresh / survivor 是裸主循环 ⇒ 只要求「有 _MODE_LABEL 的
    #   必须与 main 一致」，不要求都有。
    # - catalog：桌面助手是唯一的路线总览面板 ⇒ 要求全覆盖（含 survivor）。
    runner_labels = {
        name: label
        for name, spec in mode_specs.items()
        if (label := getattr(spec.runner_type, "_MODE_LABEL", ""))
    }
    launcher_labels = {
        mode: label
        for label, mode in launcher.MENU_OPTIONS.values()
        if mode != launcher.DAILY_MENU_ID
    }
    catalog_labels = {route.mode: route.label for route in catalog.ROUTES}

    errors = label_consistency_errors(
        authoritative=dict(main_labels),
        copies={
            "各 Runner 的 _MODE_LABEL": runner_labels,
            "navigation.MODE_LABELS": dict(navigation.MODE_LABELS),
            "launcher.MENU_OPTIONS": launcher_labels,
            "desktop.catalog.ROUTES": catalog_labels,
        },
        required_in={
            # main 是权威账本，不要求它比 MODE_SPECS 多；但它必须全覆盖。
            "navigation.MODE_LABELS": needs_navigation,
            "launcher.MENU_OPTIONS": needs_navigation,
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
        launcher_defaults=_launcher_fixed_cycles(),
        catalog_defaults={
            route.mode: route.default_cycles
            for route in catalog.ROUTES
            if not route.cycles_editable
        },
    )

    if errors:
        raise RuntimeError(
            "路线元数据不一致（同一事实抄在多处、只改了一部分）：\n  - "
            + "\n  - ".join(errors)
            + "\n\n新增/改动路线时请把这些副本一起改。背景与后续的「单一事实源」"
            "方案见 docs/maintenance/route_extensibility_review.md。"
        )


def _main_fixed_cycles() -> dict[str, int]:
    """``main.py`` 里那串 ``if args.mode == ...`` 兜底 → {模式: 固定次数}。

    ⚠️ **用 AST 解析源码，不用运行 ``main()``**：这里要的是「源码里写了什么」，
    不是「这次调用会得到什么」（那取决于命令行参数）。
    """
    return _fixed_cycles_from_source(_MAIN_PATH, _MAIN_ARG_ATTR)


def _launcher_fixed_cycles() -> dict[str, int]:
    """``launcher.py`` 里 ``if mode == ...: cycles = N`` 那串 → {模式: 次数}。

    ⚠️ ``elif mode in ("a", "b"): cycles = 1`` 这种**元组形式**也要认，
    否则「迷宫强化石」会漏掉（它跟 knights_donation 合并写在一行里）。
    """
    return _fixed_cycles_from_source(_LAUNCHER_PATH, _LAUNCHER_VAR)


# ---- AST 解析实现 ---------------------------------------------------------

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PATH = _PACKAGE_ROOT / "main.py"
_LAUNCHER_PATH = _PACKAGE_ROOT / "launcher.py"
# main.py 里比较的是 ``args.mode``（参数对象属性）；launcher.py 里是局部变量 ``mode``。
_MAIN_ARG_ATTR = ("args", "mode")
_LAUNCHER_VAR = ("mode",)


def _fixed_cycles_from_source(path: Path, subject: tuple[str, ...]) -> dict[str, int]:
    """从一份 py 源码里刮出「固定次数」映射。

    认这三种写法（项目里现存的就这三种）：

    ```python
    # main.py
    if args.mode == "world_boss" and args.max_cycles is None:
        args.max_cycles = 2
    if args.mode in ("knights_donation", "labyrinth_stone") and args.max_cycles is None:
        args.max_cycles = 1

    # launcher.py
    elif mode == "world_boss":
        cycles = 2
    elif mode in ("knights_donation", "labyrinth_stone"):
        cycles = 1
    ```

    ⚠️ 只认 ``if/elif`` 那一层，**不递归进函数体深处** —— 这里要的是「入口处的
    固定次数表」，不是任何地方出现的赋值。刮到无法识别的形态就跳过（放过），
    因为「解析不到」不该升级成「程序起不来」；真正的兜底是
    ``default_cycles_consistency_errors`` 的键集合比对（少登记会报错）。
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
    """这个条件表达式是不是 ``<subject> == "xxx"`` / ``<subject> in ("a", "b")``。

    返回它命中的模式名列表（不是就返回空列表）。
    """
    # 去掉 ``and args.max_cycles is None`` 那种尾巴，只看最左边那一项。
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and test.values:
        candidate = test.values[0]
    else:
        candidate = test

    if not isinstance(candidate, ast.Compare) or len(candidate.ops) != 1:
        return []
    if not _is_subject(candidate.left, subject):
        return []
    comparator = candidate.comparators[0]
    op = candidate.ops[0]
    if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
        if isinstance(comparator.value, str):
            return [comparator.value]
    if isinstance(op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List)):
        return [
            element.value
            for element in comparator.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
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
    """这个 ``if`` 体里有没有 ``<某个目标> = <整数常量>``；有就返回那个整数。

    ⚠️ 目标名不强求 —— ``main.py`` 赋给 ``args.max_cycles``、``launcher.py``
    赋给 ``cycles``。这里只要「体里有一个整数常量赋值」就认，因为
    这两种入口的 if 体里本来就只有那一个赋值。
    """
    for statement in body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
    return None
