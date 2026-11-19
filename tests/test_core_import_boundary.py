"""core 不许反向依赖具体游戏/桌面层（审查 D）。

审查复验发现两个漏口：只扫 ``core`` 第一层、只认绝对导入写法。
这里把扫描改成递归，并按 Python 的导入语义把相对导入与
``from 包 import 子模块`` 都还原成绝对模块名再判。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _package_of(path: Path, package_root: Path) -> str:
    """文件所在包的全名（``core/sub/x.py`` ⇒ ``auto_game_unified.core.sub``）。"""

    parts = list(path.relative_to(package_root).with_suffix("").parts[:-1])
    return ".".join([package_root.name, *parts])


def _imported_modules(path: Path, package_root: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path, package_root)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # 相对导入：``from ..games.epic7 import modes`` 要从当前包往上退。
                base = package.split(".") if package else []
                up = node.level - 1
                if up:
                    base = base[: len(base) - up] if up <= len(base) else []
                module = ".".join(
                    part for part in (*base, node.module or "") if part
                )
            else:
                module = node.module or ""
            if module:
                modules.add(module)
                # ``from auto_game_unified import games``：被导入的名字本身是子模块。
                modules.update(
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _scan(package_root: Path) -> list[str]:
    """递归扫描 ``<package_root>/core``，返回违规的 ``文件 -> 模块``。"""

    forbidden = (
        f"{package_root.name}.games",
        f"{package_root.name}.desktop",
        f"{package_root.name}.desktop_qt",
    )
    offenders: list[str] = []
    for path in sorted((package_root / "core").rglob("*.py")):
        for module in sorted(_imported_modules(path, package_root)):
            if any(
                module == bad or module.startswith(f"{bad}.")
                for bad in forbidden
            ):
                offenders.append(f"{path.relative_to(package_root)} -> {module}")
    return offenders


def test_core_has_no_imports_from_games_or_desktop():
    offenders = _scan(REPO)
    assert offenders == [], "core 反向依赖了上层：" + "；".join(offenders)


def test_the_scan_flags_relative_and_package_imports(tmp_path):
    """两条反例必须报红：``from ..games`` 与 ``from 包 import games``。

    同时覆盖 ``core`` 子目录：只扫第一层会让子目录里的违规漏过去。
    """

    root = tmp_path / "auto_game_unified"
    core = root / "core"
    (core / "sub").mkdir(parents=True)
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (core / "bad_relative.py").write_text(
        "from ..games.epic7 import modes\n", encoding="utf-8"
    )
    (core / "bad_package.py").write_text(
        "from auto_game_unified import games\n", encoding="utf-8"
    )
    (core / "sub" / "bad_deep.py").write_text(
        "from ...desktop import preflight\n", encoding="utf-8"
    )
    # Qt 桌面层同样是上层，禁的是「core 反向依赖界面」，不只 ``desktop``。
    (core / "bad_desktop_qt.py").write_text(
        "from ..desktop_qt import app\n", encoding="utf-8"
    )
    # 合法的相对导入不许误报。
    (core / "ok.py").write_text(
        "from . import supervisor\nfrom ..core import runtime\n",
        encoding="utf-8",
    )

    offenders = _scan(root)

    flagged = {item.split(" -> ")[0].replace("\\", "/") for item in offenders}
    assert flagged == {
        "core/bad_relative.py",
        "core/bad_package.py",
        "core/sub/bad_deep.py",
        "core/bad_desktop_qt.py",
    }, offenders
