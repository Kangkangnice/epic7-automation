"""The portable Qt distribution must include the brand artwork."""

from pathlib import Path
import runpy
from types import SimpleNamespace


def test_portable_spec_includes_arky_artwork_and_exe_icon(monkeypatch):
    import sys
    from types import ModuleType

    packaging = Path(__file__).resolve().parents[1] / "packaging"
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda name: []
    hooks.collect_submodules = lambda name: []
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)

    targets = {}

    def analysis(*args, **kwargs):
        targets["datas"] = kwargs["datas"]
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    def executable(*args, **kwargs):
        targets["icon"] = kwargs.get("icon")

    runpy.run_path(str(packaging / "epic7_auto_assistant.spec"), init_globals={
        "SPECPATH": str(packaging), "Analysis": analysis,
        "PYZ": lambda pure: None, "EXE": executable, "COLLECT": lambda *a, **kw: None,
    })
    desktop = packaging.parent / "desktop_qt"
    assert (str(desktop / "assets"), "auto_game_unified/desktop_qt/assets") in targets["datas"]
    assert (str(desktop / "app.ico"), "auto_game_unified/desktop_qt") in targets["datas"]
    assert targets["icon"] == str(desktop / "app.ico")
