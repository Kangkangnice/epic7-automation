import unittest
from unittest.mock import patch

import cv2
import numpy as np

from auto_game_unified.core.matcher import find_all_templates, find_template


class ScaledTemplateMatchingTests(unittest.TestCase):
    def test_reference_resolution_does_not_resize_the_template(self):
        rng = np.random.default_rng(5)
        screen = rng.integers(0, 256, size=(24, 40, 3), dtype=np.uint8)
        template = screen[3:8, 7:12].copy()
        with patch.object(cv2, "resize", wraps=cv2.resize) as resize:
            best = find_template(screen, template, threshold=0.99, reference_size=(40, 24))
            all_hits = find_all_templates(screen, template, threshold=0.99, reference_size=(40, 24))

        resize.assert_not_called()
        self.assertEqual((9, 5), best.center)
        self.assertEqual([(9, 5)], [hit.center for hit in all_hits])

    def test_reference_resolution_accepts_an_opencv_mat_template(self):
        rng = np.random.default_rng(5)
        screen = rng.integers(0, 256, size=(24, 40, 3), dtype=np.uint8)
        template = cv2.Mat(screen[3:8, 7:12].copy(), wrap_channels=True)
        best = find_template(screen, template, threshold=0.99, reference_size=(40, 24))
        self.assertEqual((9, 5), best.center)

    def test_matches_template_at_half_the_reference_resolution(self):
        template = np.array(
            [[[0, 0, 255], [0, 255, 0]], [[255, 0, 0], [255, 255, 0]]], dtype=np.uint8
        )
        scaled_template = cv2.resize(template, (4, 4), interpolation=cv2.INTER_CUBIC)
        screen = np.zeros((30, 40, 3), dtype=np.uint8)
        screen[10:14, 20:24] = scaled_template

        match = find_template(
            screen,
            template,
            threshold=0.99,
            reference_size=(20, 15),
        )

        self.assertIsNotNone(match)
        self.assertEqual((22, 12), match.center)


if __name__ == "__main__":
    unittest.main()
