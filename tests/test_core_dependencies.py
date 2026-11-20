"""Keep the core independent of game and desktop modules."""

import ast
from importlib.util import resolve_name
from pathlib import Path


def test_core_does_not_import_game_or_desktop_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    upper_layers = {"games", "desktop", "desktop_qt"}
    violations = []

    for source in sorted((root / "core").rglob("*.py")):
        path = source.relative_to(root)
        package = ".".join(("auto_game_unified", *path.parts[:-1]))
        for node in ast.walk(ast.parse(source.read_bytes(), filename=str(path))):
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = resolve_name("." * node.level + (node.module or ""), package)
                names = (f"{module}.{alias.name}" for alias in node.names)
            else:
                continue

            for name in names:
                layer = name.removeprefix("auto_game_unified.").partition(".")[0]
                if layer in upper_layers:
                    violations.append(f"{path.as_posix()}:{node.lineno} -> {name}")

    assert not violations, "Core imports higher layers:\n" + "\n".join(violations)


def test_epic7_evidence_imports_keep_the_shared_type_identity() -> None:
    from auto_game_unified.core import visual_evidence
    from auto_game_unified.games.epic7.evidence import common

    for name in (
        "AtomEvidence",
        "AtomObservation",
        "EvidenceProfile",
        "EvidenceState",
        "PageEvidence",
        "validate_profile",
    ):
        assert getattr(common, name) is getattr(visual_evidence, name), name
