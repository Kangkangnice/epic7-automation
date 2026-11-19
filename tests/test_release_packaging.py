"""Release inputs can be checked without building an executable."""

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import zipfile

import pytest

from auto_game_unified.packaging import build, entry


@pytest.mark.parametrize("desktop_available", [True, False])
def test_self_check_reports_desktop_dependencies_in_configured_data_directory(
    tmp_path: Path, monkeypatch, desktop_available: bool
) -> None:
    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["entry.py", "--self-check"])
    if not desktop_available:
        monkeypatch.setitem(sys.modules, "auto_game_unified.desktop_qt.app", None)

    assert entry.main() == (0 if desktop_available else 1)
    report = (tmp_path / "runtime_logs" / "self_check.txt").read_text(encoding="utf-8")
    assert ("[通过] 桌面入口" if desktop_available else "[失败] 桌面入口") in report
    assert ("结果：通过" if desktop_available else "结果：1 项失败") in report


def test_spec_collects_from_a_clean_checkout(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "auto_game_unified"
    (repo / "packaging").mkdir(parents=True)
    (repo / "games" / "epic7" / "templates").mkdir(parents=True)

    hooks = ModuleType("PyInstaller.utils.hooks")
    monkeypatch.setattr(hooks, "collect_data_files", lambda package: [], raising=False)
    monkeypatch.setattr(hooks, "collect_submodules", lambda package: [], raising=False)
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)

    def analysis(_scripts, *, datas, excludes, **_options):
        for source, _destination in datas:
            assert Path(source).exists(), source
        assert "e7auto" in excludes
        binaries = [
            (name, str(repo / name), "BINARY")
            for name in ("ICUUC.dll", "icuin.dll", "icu.dll", "icuuc78.dll")
        ]
        return SimpleNamespace(binaries=binaries, datas=[], pure=[], scripts=[])

    def ignore_target(*_args, **_kwargs):
        pass

    def collect(_exe, binaries, _datas, **_options):
        assert [binary[0] for binary in binaries] == ["icuuc78.dll"]

    runpy.run_path(
        str(build.SPEC),
        init_globals={
            "SPECPATH": str(repo / "packaging"),
            "Analysis": analysis,
            "PYZ": ignore_target,
            "EXE": ignore_target,
            "COLLECT": collect,
        },
    )


@pytest.fixture
def onedir(tmp_path: Path, monkeypatch) -> Path:
    app = tmp_path / build.APP_NAME
    app.mkdir()
    (app / f"{build.APP_NAME}.exe").write_bytes(b"exe")
    monkeypatch.setattr(build, "DIST", tmp_path)
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-build", "--installer"])
    return app


@pytest.mark.parametrize("blocked_path", [
    "vendor/e7auto/src/private.py",
    "_internal/vendor/E7Auto/config/internal.yaml",
    ".git",
    "_internal/.github/workflows/tests.yml",
    "_internal/ICUUC.dll",
])
def test_no_build_rejects_contaminated_dist(onedir: Path, blocked_path: str, monkeypatch):
    blocked = onedir / blocked_path
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_bytes(b"private")
    monkeypatch.setattr(build, "build_installer", lambda version: pytest.fail("installer ran"))

    with pytest.raises(SystemExit) as error:
        build.main()

    assert str(error.value).lower().splitlines()[0].endswith(
        next(part for part in blocked.parts if part.lower() in {
            "e7auto", ".git", ".github", "icuuc.dll"
        }).lower()
    )
    assert not list(onedir.parent.glob("*.zip"))
    assert not (onedir.parent / "SHA256SUMS.txt").exists()


def test_no_build_includes_project_notices_in_zip_and_installer_input(onedir: Path, monkeypatch):
    notices = {name: (build.REPO / name).read_bytes() for name in ("LICENSE", "NOTICE.md")}
    installer_inputs = []

    def installer(_version):
        installer_inputs.append({name: (onedir / name).read_bytes() for name in notices})

    monkeypatch.setattr(build, "build_installer", installer)

    assert build.main() == 0
    assert installer_inputs == [notices]
    assert f'Source: "dist\\{build.APP_NAME}\\*"; DestDir: "{{app}}"' in (
        build.INSTALLER.read_text(encoding="utf-8-sig")
    )
    (portable_zip,) = onedir.parent.glob("*.zip")
    with zipfile.ZipFile(portable_zip) as archive:
        for name, contents in notices.items():
            assert archive.read(f"{build.APP_NAME}/{name}") == contents
