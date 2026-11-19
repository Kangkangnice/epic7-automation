"""core 不许反向依赖具体游戏/桌面层（审查 D）。"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = ("auto_game_unified.games", "auto_game_unified.desktop")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_core_has_no_imports_from_games_or_desktop():
    offenders: list[str] = []
    for path in sorted((REPO / "core").glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith(FORBIDDEN):
                offenders.append(f"{path.name} -> {module}")
    assert offenders == [], "core 反向依赖了上层：" + "；".join(offenders)
