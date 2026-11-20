"""新增英雄工具：slug 候选、图标转换、分类表合并。全部离线，不依赖网络。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from auto_game_unified.tools import add_hero
from auto_game_unified.tools.add_hero import (
    _read_payload,
    _slug_candidates,
    _to_icon,
    _validate,
    merge_entry,
)


def _png_bytes(image: np.ndarray) -> bytes:
    return cv2.imencode(".png", image)[1].tobytes()


class SlugCandidateTests(unittest.TestCase):
    def test_single_word_lowercases(self):
        self.assertEqual(["renoa"], _slug_candidates("Renoa"))

    def test_spaces_become_dashes_with_a_joined_variant(self):
        self.assertEqual(
            ["aubade-ludwig", "aubadeludwig"], _slug_candidates("Aubade Ludwig")
        )

    def test_ampersand_reads_as_and(self):
        self.assertIn("baal-and-sezan", _slug_candidates("Baal & Sezan"))

    def test_apostrophe_and_period_are_dropped(self):
        self.assertEqual("sir-arthur", _slug_candidates("Sir Arthur.")[0])

    def test_empty_name_has_no_candidate(self):
        self.assertEqual([], _slug_candidates("   "))


class IconConversionTests(unittest.TestCase):
    def test_transparent_corners_become_black_like_the_library(self):
        image = np.zeros((112, 112, 4), dtype=np.uint8)
        image[:, :] = (200, 120, 60, 255)
        image[:8, :8] = (0, 255, 0, 0)  # 透明角落，RGB 是随意的绿
        edge = image[56, 0]
        edge[3] = 128
        icon = _to_icon(_png_bytes(image))
        self.assertEqual((112, 112, 3), icon.shape)
        self.assertEqual([0, 0, 0], icon[0, 0].tolist())

    def test_small_source_is_rejected(self):
        with self.assertRaises(ValueError):
            _to_icon(_png_bytes(np.zeros((64, 64, 3), dtype=np.uint8)))

    def test_square_source_is_resized_to_the_library_size(self):
        icon = _to_icon(_png_bytes(np.full((200, 200, 3), 90, dtype=np.uint8)))
        self.assertEqual((112, 112, 3), icon.shape)


class MergeEntryTests(unittest.TestCase):
    def payload(self):
        return {
            "source": "测试",
            "count": 2,
            "heroes": {
                "甲": {"en": "Alpha", "job": "战士", "element": "火", "stars": 5},
                "乙": {"en": "Beta", "job": "骑士", "element": "水", "stars": 4},
            },
        }

    def test_new_entry_is_added_and_count_follows(self):
        updated, notes = merge_entry(
            self.payload(),
            zh="丙",
            en="Gamma",
            job="射手",
            element="木",
            stars=3,
            force=False,
        )
        self.assertEqual(3, updated["count"])
        self.assertEqual(
            {"en": "Gamma", "job": "射手", "element": "木", "stars": 3},
            updated["heroes"]["丙"],
        )
        self.assertEqual([], notes)

    def test_entries_stay_sorted_by_name(self):
        updated, _ = merge_entry(
            self.payload(), zh="丙", en="Gamma", job="射手", element="木", stars=3, force=False
        )
        self.assertEqual(["丙", "乙", "甲"], list(updated["heroes"]))

    def test_identical_entry_is_a_no_op(self):
        updated, notes = merge_entry(
            self.payload(),
            zh="甲",
            en="Alpha",
            job="战士",
            element="火",
            stars=5,
            force=False,
        )
        self.assertEqual(self.payload()["heroes"]["甲"], updated["heroes"]["甲"])
        self.assertTrue(any("一致" in note for note in notes))

    def test_conflicting_classification_needs_force(self):
        with self.assertRaises(ValueError):
            merge_entry(
                self.payload(),
                zh="甲",
                en="Alpha",
                job="射手",
                element="暗",
                stars=3,
                force=False,
            )
        updated, notes = merge_entry(
            self.payload(),
            zh="甲",
            en="Alpha",
            job="射手",
            element="暗",
            stars=3,
            force=True,
        )
        self.assertEqual("射手", updated["heroes"]["甲"]["job"])
        self.assertTrue(any("覆盖" in note for note in notes))

    def test_english_name_under_another_name_needs_force(self):
        with self.assertRaises(ValueError):
            merge_entry(
                self.payload(),
                zh="丙",
                en="alpha",
                job="战士",
                element="火",
                stars=5,
                force=False,
            )
        updated, notes = merge_entry(
            self.payload(),
            zh="丙",
            en="Alpha",
            job="战士",
            element="火",
            stars=5,
            force=True,
        )
        self.assertIn("丙", updated["heroes"])
        self.assertTrue(any("Alpha" in note for note in notes))


class ReadPayloadTests(unittest.TestCase):
    def test_missing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                _read_payload(Path(folder) / "meta.json")

    def test_payload_without_heroes_is_rejected(self):
        """缺 heroes 表的文件上写入等于把整张表覆盖成一条，必须拒绝。"""

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "meta.json"
            path.write_text('{"count": 3}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_payload(path)


class ValidationTests(unittest.TestCase):
    def test_accepts_declared_values(self):
        _validate("射手", "暗", 5)

    def test_rejects_unknown_job_element_or_stars(self):
        for job, element, stars in (
            ("弓手", "暗", 5),
            ("射手", "雷", 5),
            ("射手", "暗", 6),
        ):
            with self.subTest(job=job, element=element, stars=stars):
                with self.assertRaises(ValueError):
                    _validate(job, element, stars)


def test_conflicting_metadata_leaves_no_orphan_portrait(tmp_path, monkeypatch):
    metadata = tmp_path / "meta.json"
    original = {"heroes": {"旧英雄": {"en": "Alpha", "job": "战士", "element": "火", "stars": 5}}}
    metadata.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(add_hero, "default_library_dir", lambda: tmp_path)
    monkeypatch.setattr(add_hero, "meta_path", lambda: metadata)
    monkeypatch.setattr(
        "sys.argv",
        ["add_hero", "--zh", "新英雄", "--en", "Alpha", "--job", "战士", "--element", "火", "--stars", "5"],
    )
    with patch.object(add_hero, "_download_avatar", return_value=(
        _png_bytes(np.zeros((112, 112, 3), dtype=np.uint8)), "fixture",
    )) as download:
        assert add_hero.main() == 1
    assert not (tmp_path / "新英雄.png").exists()
    assert json.loads(metadata.read_text(encoding="utf-8")) == original
    download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
