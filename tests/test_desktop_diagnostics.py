import json
from zipfile import ZipFile

from auto_game_unified.desktop.diagnostics import export_diagnostics


def test_export_contains_selected_mode_only_and_redacts_home(tmp_path):
    root = tmp_path / "repo"
    (root / "runtime_logs").mkdir(parents=True)
    diagnostic_dir = root / "runtime_diagnostics" / "epic7_story"
    diagnostic_dir.mkdir(parents=True)
    home = tmp_path / "User Name"
    (root / "runtime_logs" / "epic7_story.log").write_text(
        f"诊断={home / 'secret.png'}\n",
        encoding="utf-8",
    )
    (root / "runtime_logs" / "epic7_arena.log").write_text(
        "other",
        encoding="utf-8",
    )
    (diagnostic_dir / "current.png").write_bytes(b"png")

    output = export_diagnostics(
        "story",
        root=root,
        output_dir=tmp_path / "exports",
        user_home=home,
    )

    with ZipFile(output) as archive:
        names = archive.namelist()
        assert "logs/epic7_story.log" in names
        assert "diagnostics/current.png" in names
        assert all("arena" not in name for name in names)
        assert "%USERPROFILE%" in archive.read(
            "logs/epic7_story.log"
        ).decode("utf-8")
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["mode"] == "story"


def test_export_without_runtime_files_still_contains_metadata(tmp_path):
    output = export_diagnostics(
        "hero_synthesis",
        root=tmp_path / "empty",
        output_dir=tmp_path / "exports",
        user_home=tmp_path,
    )

    with ZipFile(output) as archive:
        assert archive.namelist() == ["metadata.json"]
