import os
import tempfile
import unittest

import cv2
import numpy as np

from auto_game_unified.core.matcher import find_best_template, find_template, load_template


class TemplateMatchingTests(unittest.TestCase):
    def setUp(self):
        self.screen = np.zeros((80, 100, 3), dtype=np.uint8)
        self.template = np.array(
            [
                [[0, 0, 255], [0, 255, 0], [255, 0, 0]],
                [[255, 255, 0], [0, 255, 255], [255, 0, 255]],
            ],
            dtype=np.uint8,
        )
        self.screen[20:22, 40:43] = self.template

    def test_returns_global_center_and_score(self):
        match = find_template(self.screen, self.template, threshold=0.99)

        self.assertIsNotNone(match)
        self.assertEqual((41, 21), match.center)
        self.assertGreaterEqual(match.score, 0.99)

    def test_respects_search_region(self):
        match = find_template(
            self.screen,
            self.template,
            threshold=0.99,
            region=(0, 0, 30, 30),
        )

        self.assertIsNone(match)

    def test_best_match_keeps_score_below_business_threshold(self):
        rng = np.random.default_rng(7)
        template = rng.integers(0, 256, size=(10, 10, 3), dtype=np.uint8)
        changed = template.copy()
        changed[:3, :3] = 0
        screen = np.zeros((40, 40, 3), dtype=np.uint8)
        screen[12:22, 14:24] = changed

        best = find_best_template(screen, template, region=(0, 0, 40, 40))

        self.assertIsNotNone(best)
        self.assertLess(best.score, 0.999)
        self.assertIsNone(
            find_template(screen, template, 0.999, region=(0, 0, 40, 40))
        )


class TemplateLoadingTests(unittest.TestCase):
    """load_template 会缓存解码结果，缓存不能改变「读到的内容」。"""

    def test_matches_a_direct_decode_on_every_call(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "t.png")
            cv2.imwrite(path, np.array([[[0, 0, 255], [0, 255, 0]]], dtype=np.uint8))

            for _ in range(3):
                expected = cv2.cvtColor(
                    cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
                )
                np.testing.assert_array_equal(expected, load_template(path))

    def test_reloads_when_the_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "t.png")
            cv2.imwrite(path, np.full((2, 2, 3), 10, dtype=np.uint8))
            self.assertEqual((2, 2, 3), load_template(path).shape)

            cv2.imwrite(path, np.full((5, 5, 3), 200, dtype=np.uint8))
            np.testing.assert_array_equal(
                np.full((5, 5, 3), 200, dtype=np.uint8), load_template(path)
            )

    def test_missing_file_still_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                load_template(os.path.join(folder, "missing.png"))


if __name__ == "__main__":
    unittest.main()
