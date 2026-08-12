import unittest

import numpy as np

from auto_game_unified.core.matcher import find_template


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


if __name__ == "__main__":
    unittest.main()
