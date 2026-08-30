import unittest

import cv2
import numpy as np

from auto_game_unified.core.matcher import find_template


class ScaledTemplateMatchingTests(unittest.TestCase):
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
