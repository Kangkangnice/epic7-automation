"""发布 ZIP 前的内容门禁：多一个文件、改一个字节都不许产出新包。

另有一组守着**公开候选**（``--without-e7auto``）：那份产物要求
``vendor/e7auto`` 成员数为 0，同时必须带发行版标记 —— 少了标记，
界面和自检就分不出「声明不含」和「该有却漏了」。
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import zipfile

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
    vendor = dist / "ArkyAssistant" / "_internal" / "vendor" / "e7auto"
    for name, data in payload.items():
        target = vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if extra:
        (vendor / "src" / "e7auto" / "extra.py").write_bytes(b"x")
    if mutate:
        (vendor / "src" / "e7auto" / "__init__.py").write_bytes(b"VALUE = 2\n")
    (dist / "ArkyAssistant" / "ArkyAssistant.exe").write_bytes(b"exe")
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
    assert not (dist / "亚卡助手-免安装版-9.9.9.zip").exists()


def test_changed_vendor_byte_blocks_the_zip(tmp_path: Path):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build, mutate=True)

    with pytest.raises(SystemExit, match="摘要不符"):
        build.make_zip("9.9.9", vendor.load_lock())
    assert not (dist / "亚卡助手-免安装版-9.9.9.zip").exists()


def test_no_build_path_also_runs_the_gate(tmp_path: Path, monkeypatch):
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build, extra=True)
    monkeypatch.setattr(build, "_vendor_module", lambda: vendor)
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-build"])

    with pytest.raises(SystemExit, match="多出"):
        build.main()
    assert not (dist / "亚卡助手-免安装版-0.1.0.zip").exists()


def test_only_latest_artifacts_survive(tmp_path: Path, monkeypatch):
    """每次打包成功后，旧版本 ZIP / 安装包清掉，验证证据保留。"""
    build = _load_build()
    dist, vendor = _prepare(tmp_path, build)

    stale_zip = dist / "亚卡助手-免安装版-0.0.1.zip"
    stale_installer = dist / "亚卡助手-安装版-0.0.1.exe"
    evidence = dist / "release-evidence" / "manifest.json"
    for path in (stale_zip, stale_installer, evidence):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")

    monkeypatch.setattr(build, "_vendor_module", lambda: vendor)
    monkeypatch.setattr(build, "build_installer", lambda version: None)
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-build"])

    assert build.main() == 0

    assert (dist / "亚卡助手-免安装版-0.1.0.zip").is_file()
    assert not stale_zip.exists()
    assert not stale_installer.exists()
    assert evidence.read_bytes() == b"old"


def _prepare_absent(
    tmp_path: Path, build, *, marker: bool = True, leftover: bool = False
) -> Path:
    """摆一份「声明不含次元探查」的产物目录。"""
    dist = tmp_path / "dist"
    vendor_dir = dist / "ArkyAssistant" / "_internal" / "vendor"
    vendor_dir.mkdir(parents=True)
    if marker:
        (vendor_dir / build._absent_marker_name()).write_bytes(b"marker")
    if leftover:
        stale = vendor_dir / "e7auto" / "src" / "e7auto" / "__init__.py"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"VALUE = 1\n")
    (dist / "ArkyAssistant" / "ArkyAssistant.exe").write_bytes(b"exe")
    build.DIST = dist
    return dist


def test_public_candidate_zip_has_no_vendor_members(tmp_path: Path):
    build = _load_build()
    dist = _prepare_absent(tmp_path, build)

    archive = build.make_zip("9.9.9", None, without_e7auto=True)

    assert archive.name == f"亚卡助手-免安装版-9.9.9{build.WITHOUT_E7AUTO_SUFFIX}.zip"
    assert archive.parent == dist
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert [name for name in names if build.ZIP_VENDOR_PREFIX in name] == []
    # 标记必须真的进包：界面与自检都靠它。
    assert any(name.endswith(build._absent_marker_name()) for name in names)


def test_public_candidate_refuses_leftover_vendor_code(tmp_path: Path):
    """漏拷的第三方代码留在产物里 ⇒ 不许出公开包（那等于无授权分发）。"""
    build = _load_build()
    dist = _prepare_absent(tmp_path, build, leftover=True)

    with pytest.raises(SystemExit, match="却有"):
        build.make_zip("9.9.9", None, without_e7auto=True)
    assert list(dist.glob("*无次元探查*.zip")) == []


def test_public_candidate_refuses_a_payload_without_the_marker(tmp_path: Path):
    build = _load_build()
    _prepare_absent(tmp_path, build, marker=False)

    with pytest.raises(SystemExit, match="发行版标记"):
        build.make_zip("9.9.9", None, without_e7auto=True)


def test_release_marker_file_keeps_the_name_the_code_looks_for():
    """标记文件的**文件名**是契约：``datas`` 只认源文件 basename。

    产物里找不到它这件事由上面的 payload 门禁兜住（真的打包时会当场停下），
    这条只守仓库里那个文件别被改名或删掉。
    """
    build = _load_build()
    assert (REPO / "packaging" / build._absent_marker_name()).is_file()


def test_full_build_refuses_a_zip_without_vendor_code(tmp_path: Path):
    """完整版打出一个没有 vendor 成员的 ZIP ⇒ 说明 spec 漏收了，不许出包。"""
    build = _load_build()
    dist = tmp_path / "dist"
    vendor = dist / "ArkyAssistant" / "_internal" / "vendor" / "e7auto"
    vendor.mkdir(parents=True)
    (dist / "ArkyAssistant" / "ArkyAssistant.exe").write_bytes(b"exe")
    build.DIST = dist

    with pytest.raises(SystemExit, match="没有 vendor/e7auto"):
        build.make_zip("9.9.9", {"files": {}})


def test_run_pyinstaller_sets_and_clears_the_switch(tmp_path: Path, monkeypatch):
    """完整构建要主动清掉这个变量：父 shell 残留会让「完整版」悄悄变成不含版。"""
    build = _load_build()
    dist = tmp_path / "dist"
    build.DIST = dist
    build.BUILD = tmp_path / "build"
    seen: dict[str, str | None] = {}

    def fake_run(command, cwd=None, check=None, env=None):
        seen.clear()
        seen.update(env or {})
        exe = dist / build.APP_NAME / f"{build.APP_NAME}.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"exe")

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    monkeypatch.setenv("ARKY_WITHOUT_E7AUTO", "1")

    build.run_pyinstaller(False)
    assert "ARKY_WITHOUT_E7AUTO" not in seen

    build.run_pyinstaller(True)
    assert seen["ARKY_WITHOUT_E7AUTO"] == "1"
