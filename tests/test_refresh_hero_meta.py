"""A custom hero library keeps its own metadata when refreshed."""

import json

from auto_game_unified.tools import refresh_hero_meta as refresh


def test_custom_refresh_only_reads_and_writes_its_own_metadata(tmp_path, monkeypatch):
    main_metadata = tmp_path / "meta.json"
    main_metadata.write_text('{"heroes": {"默认库": {}}, "count": 1}', encoding="utf-8")
    custom = tmp_path / "custom"
    custom.mkdir()
    custom_metadata = custom / "meta.json"
    custom_metadata.write_text('{"heroes": {"自选库": {}}, "count": 1}', encoding="utf-8")
    hero = {"name": "Alpha", "job": "战士", "element": "火", "stars": 5}
    monkeypatch.setattr(refresh, "meta_path", lambda: main_metadata, raising=False)
    monkeypatch.setattr(refresh, "default_library_dir", lambda: tmp_path)
    monkeypatch.setattr(refresh, "fetch_catalog", lambda _: [hero])
    monkeypatch.setattr(refresh, "download_avatars", lambda _: {})
    monkeypatch.setattr(refresh, "Matcher", lambda *_: None)
    monkeypatch.setattr(refresh, "build_table", lambda *_: {"新增": {}})
    monkeypatch.setattr("sys.argv", ["refresh_hero_meta", "--write", "--library", str(custom)])

    assert refresh.main() == 0
    assert json.loads(custom_metadata.read_text(encoding="utf-8"))["heroes"] == {
        "自选库": {}, "新增": {},
    }
    assert main_metadata.read_text(encoding="utf-8") == '{"heroes": {"默认库": {}}, "count": 1}'
