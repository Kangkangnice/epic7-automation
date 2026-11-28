"""发布 ZIP 的通用门禁：每次构建只保留最新产物，验证证据不被清掉。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "packaging_build_under_test", REPO / "packaging" / "build.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_only_latest_artifacts_survive(tmp_path: Path, monkeypatch):
    """每次打包成功后，旧版本 ZIP / 安装包清掉，验证证据保留。"""
    build = _load_build()
    dist = tmp_path / "dist"
    (dist / build.APP_NAME).mkdir(parents=True)
    (dist / build.APP_NAME / f"{build.APP_NAME}.exe").write_bytes(b"exe")
    build.DIST = dist

    stale_zip = dist / "亚卡助手-免安装版-0.0.1.zip"
    stale_installer = dist / "亚卡助手-安装版-0.0.1.exe"
    evidence = dist / "release-evidence" / "manifest.json"
    for path in (stale_zip, stale_installer, evidence):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")

    monkeypatch.setattr(build, "build_installer", lambda version: None)
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-build"])

    assert build.main() == 0

    assert (dist / "亚卡助手-免安装版-0.1.0.zip").is_file()
    assert not stale_zip.exists()
    assert not stale_installer.exists()
    assert evidence.read_bytes() == b"old"
