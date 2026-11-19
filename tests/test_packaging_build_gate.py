"""发布 ZIP 前的内容门禁：多一个文件、改一个字节都不许产出新包。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "packaging_build_under_test", REPO / "packaging" / "build.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeVendor:
    """把 build 对 fetch_vendor 的依赖压到一份最小清单上。"""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._lock = {"files": {name: _digest(data) for name, data in files.items()}}

    def load_lock(self) -> dict:
        return self._lock

    @staticmethod
    def sha256_file(path: Path) -> str:
        return _digest(path.read_bytes())


def _prepare(tmp_path: Path, build, *, extra: bool = False, mutate: bool = False):
    payload = {"src/e7auto/__init__.py": b"VALUE = 1\n"}
    dist = tmp_path / "dist"
    vendor = dist / "Epic7AutoAssistant" / "_internal" / "vendor" / "e7auto"
    for name, data in payload.items():
        target = vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if extra:
        (vendor / "src" / "e7auto" / "extra.py").write_bytes(b"x")
    if mutate:
        (vendor / "src" / "e7auto" / "__init__.py").write_bytes(b"VALUE = 2\n")
    (dist / "Epic7AutoAssistant" / "Epic7AutoAssistant.exe").write_bytes(b"exe")
    build.DIST = dist
    return dist, _FakeVendor(payload)


def test_matching_product_still_produces_the_zip(tmp_path: Path):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build)

    archive = build.make_zip("9.9.9", vendor.load_lock())

    assert archive.is_file()
    assert archive.parent == dist


def test_extra_vendor_file_blocks_the_zip(tmp_path: Path):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build, extra=True)

    with pytest.raises(SystemExit, match="多出"):
        build.make_zip("9.9.9", vendor.load_lock())
    assert not (dist / "第七史诗自动助手-免安装版-9.9.9.zip").exists()


def test_changed_vendor_byte_blocks_the_zip(tmp_path: Path):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build, mutate=True)

    with pytest.raises(SystemExit, match="摘要不符"):
        build.make_zip("9.9.9", vendor.load_lock())
    assert not (dist / "第七史诗自动助手-免安装版-9.9.9.zip").exists()


def test_no_build_path_also_runs_the_gate(tmp_path: Path, monkeypatch):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build, extra=True)
    monkeypatch.setattr(build, "_vendor_module", lambda: vendor)
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-build"])

    with pytest.raises(SystemExit, match="多出"):
        build.main()
    assert not (dist / "第七史诗自动助手-免安装版-0.1.0.zip").exists()
