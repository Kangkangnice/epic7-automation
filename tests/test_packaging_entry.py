"""打包入口的分流：``--worker`` 走业务 CLI，默认才进界面。

回归点（2026-11-19 审查 A1）：冻结版把 worker 参数送进 GUI，起第二个窗口。
"""

from __future__ import annotations

from pathlib import Path
import runpy
import sys
import types

import pytest

REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / "packaging" / "entry.py"


def _load_entry() -> dict[str, object]:
    return runpy.run_path(str(ENTRY), run_name="packaging_entry_under_test")


def _stub(monkeypatch, name: str, main) -> None:
    module = types.ModuleType(name)
    module.main = main
    monkeypatch.setitem(sys.modules, name, module)


def test_worker_flag_dispatches_to_the_cli_without_the_flag(monkeypatch):
    seen: dict[str, object] = {}

    def run_cli(argv=None) -> int:
        seen["argv"] = argv
        return 7

    _stub(monkeypatch, "auto_game_unified.main", run_cli)
    _stub(
        monkeypatch,
        "auto_game_unified.desktop_qt.app",
        lambda: pytest.fail("worker 模式不该导入界面"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ArkyAssistant.exe",
            "--worker",
            "--daily",
            "--daily-tasks",
            "arena:1",
        ],
    )

    assert _load_entry()["main"]() == 7
    assert seen["argv"] == ["--daily", "--daily-tasks", "arena:1"]


def test_default_entry_still_launches_the_gui(monkeypatch):
    called: list[str] = []

    def run_gui() -> int:
        called.append("gui")
        return 0

    _stub(monkeypatch, "auto_game_unified.main", lambda argv=None: 99)
    _stub(monkeypatch, "auto_game_unified.desktop_qt.app", run_gui)
    monkeypatch.setattr(sys, "argv", ["ArkyAssistant.exe"])

    assert _load_entry()["main"]() == 0
    assert called == ["gui"]


def test_frozen_entry_switches_stdio_to_utf8(monkeypatch):
    """冻结版不认 PYTHONIOENCODING：worker 分支必须自己把输出改成 UTF-8。

    否则父进程按 UTF-8 读到的会是系统代码页字节（2026-11-19 用真实产物复现：
    ``--self-check`` 输出只能按 GBK 解码）。
    """

    class Stream:
        def __init__(self) -> None:
            self.encodings: list[str] = []

        def reconfigure(self, encoding: str) -> None:
            self.encodings.append(encoding)

    out, err = Stream(), Stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _stub(monkeypatch, "auto_game_unified.main", lambda argv=None: 0)
    monkeypatch.setattr(sys, "argv", ["ArkyAssistant.exe", "--worker", "--daily"])

    assert _load_entry()["main"]() == 0
    assert out.encodings == ["utf-8"]
    assert err.encodings == ["utf-8"]
