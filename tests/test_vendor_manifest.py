"""第三方代码清单：固定来源/版本，缺文件、摘要不符、清单外文件都要报出来。"""

from __future__ import annotations

from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from auto_game_unified.tools import fetch_vendor

REPO = Path(__file__).resolve().parents[1]


def test_lock_pins_an_upstream_commit_and_only_distributable_directories():
    lock = fetch_vendor.load_lock()

    assert lock["upstream"] == "https://github.com/Ricardo1503449/E7auto.git"
    assert re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
    assert lock["include"] == ["src", "config", "assets/templates"]
    assert lock["files"], "清单不能是空的"
    assert all(
        name.startswith(("src/", "config/", "assets/templates/"))
        for name in lock["files"]
    )
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in lock["files"])


def _make_tree(root: Path) -> Path:
    (root / "src" / "e7auto").mkdir(parents=True)
    (root / "src" / "e7auto" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "internal.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (root / "assets" / "templates").mkdir(parents=True)
    (root / "assets" / "templates" / "x.txt").write_text("x", encoding="utf-8")
    # 上游还有这些目录，但它们不该进清单。
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("doc", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return root


def _lock_for(root: Path) -> dict:
    return {"include": list(fetch_vendor.INCLUDE), "files": fetch_vendor.inventory(root)}


def test_verify_accepts_an_exact_tree_and_reports_each_kind_of_drift(tmp_path: Path):
    tree = _make_tree(tmp_path / "vendor")
    lock = _lock_for(tree)
    assert fetch_vendor.verify(tree, lock) == []

    (tree / "src" / "e7auto" / "extra.py").write_text("x", encoding="utf-8")
    assert any("清单外文件" in item for item in fetch_vendor.verify(tree, lock))
    (tree / "src" / "e7auto" / "extra.py").unlink()

    (tree / "config" / "internal.yaml").write_text("changed\n", encoding="utf-8")
    assert any("摘要不符" in item for item in fetch_vendor.verify(tree, lock))

    shutil.rmtree(tree / "assets")
    assert any("缺少文件" in item for item in fetch_vendor.verify(tree, lock))


def test_verify_reports_a_missing_vendor_directory(tmp_path: Path):
    problems = fetch_vendor.verify(tmp_path / "absent", {"include": ["src"], "files": {}})
    assert problems and "先运行 python tools/fetch_vendor.py" in problems[0]


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_fetch_clones_the_pinned_commit_from_a_mirror(tmp_path: Path):
    upstream = _make_tree(tmp_path / "upstream")
    subprocess.run(["git", "init", "--quiet"], cwd=upstream, check=True)
    subprocess.run(["git", "add", "."], cwd=upstream, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "commit", "--quiet", "-m", "fixture"],
        cwd=upstream,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=upstream, check=True, text=True,
        capture_output=True,
    ).stdout.strip()
    lock = {"commit": commit, "include": list(fetch_vendor.INCLUDE),
            "files": fetch_vendor.inventory(upstream)}

    dest = tmp_path / "workspace" / "vendor" / "e7auto"
    fetch_vendor.fetch(lock, str(upstream), dest=dest)

    assert fetch_vendor.verify(dest, lock) == []
    assert not (dest / ".git").exists()


def test_spec_ships_only_the_runtime_subdirectories_of_the_vendor(tmp_path: Path):
    packaging = REPO / "packaging"
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda name: []
    hooks.collect_submodules = lambda name: []
    monkey_hooks = {"PyInstaller.utils.hooks": hooks}
    saved = {name: sys.modules.get(name) for name in monkey_hooks}
    sys.modules.update(monkey_hooks)
    datas: list[tuple[str, str]] = []

    def analysis(*args, **kwargs):
        datas.extend(kwargs["datas"])
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    try:
        runpy.run_path(
            str(packaging / "epic7_auto_assistant.spec"),
            init_globals={
                "SPECPATH": str(packaging),
                "Analysis": analysis,
                "PYZ": lambda pure: None,
                "EXE": lambda *a, **kw: None,
                "COLLECT": lambda *a, **kw: None,
            },
        )
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    vendor_sources = {source for source, target in datas if target.startswith("vendor/")}
    workspace = REPO.parent
    assert vendor_sources == {
        str(workspace / "vendor" / "e7auto" / "src"),
        str(workspace / "vendor" / "e7auto" / "config"),
        str(workspace / "vendor" / "e7auto" / "assets" / "templates"),
    }
