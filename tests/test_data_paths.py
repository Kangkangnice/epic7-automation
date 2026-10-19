"""运行产物根目录：源码 / 打包 / 显式覆盖三条路，各有各的去处。

这条规则存在的唯一理由：装进 ``Program Files`` 的版本不能往安装目录写日志，
否则第一次启动就是 ``PermissionError``，而用户看到的现象只是「双击没反应」。
"""

from __future__ import annotations

import sys

from auto_game_unified.core import data_paths


def _source_mode(monkeypatch) -> None:
    monkeypatch.delenv(data_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_source_run_keeps_artifacts_inside_the_package(monkeypatch):
    _source_mode(monkeypatch)

    assert data_paths.data_root() == data_paths.package_root()
    assert data_paths.data_root().name == "auto_game_unified"


def test_packaged_run_writes_under_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv(data_paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert data_paths.data_root() == tmp_path / "Epic7AutoAssistant"


def test_explicit_data_dir_wins_over_both(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "ignored"))
    monkeypatch.setenv(data_paths.DATA_DIR_ENV, str(tmp_path / "chosen"))

    assert data_paths.data_root() == tmp_path / "chosen"
