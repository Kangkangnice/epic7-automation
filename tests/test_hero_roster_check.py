"""The packaged hero roster is a matching catalog and image set."""

import json
from pathlib import Path

from PIL import Image

from auto_game_unified.games.epic7.hero_match import default_library_dir
from auto_game_unified.tools.check_hero_roster import inspect_roster


def test_tracked_hero_roster_is_complete() -> None:
    assert inspect_roster(default_library_dir()) == []


def test_reports_missing_portraits_entries_and_count(tmp_path: Path) -> None:
    Image.new("RGB", (112, 112)).save(tmp_path / "只有头像.png")
    payload = {
        "count": 2,
        "heroes": {"只有分类": {"en": "Example", "job": "战士", "element": "火", "stars": 5}},
    }
    (tmp_path / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    errors = inspect_roster(tmp_path)

    assert any("只有头像" in error and "分类" in error for error in errors)
    assert any("只有分类" in error and "头像" in error for error in errors)
    assert any("count" in error for error in errors)


def test_reports_invalid_classification_and_bad_images(tmp_path: Path) -> None:
    Image.new("RGB", (112, 110)).save(tmp_path / "尺寸不对.png")
    (tmp_path / "无法解码.png").write_bytes(b"not a PNG")
    payload = {
        "count": 2,
        "heroes": {
            "尺寸不对": {"en": "One", "job": "战士", "element": "火", "stars": True},
            "无法解码": {"en": "Two", "job": "战士", "element": "火", "stars": 5},
        },
    }
    (tmp_path / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    errors = inspect_roster(tmp_path)

    assert any("尺寸不对" in error and "分类" in error for error in errors)
    assert any("尺寸不对" in error and "112" in error for error in errors)
    assert any("无法解码" in error for error in errors)
