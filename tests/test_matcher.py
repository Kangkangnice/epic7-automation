import os
import tempfile
import unittest

import cv2
import numpy as np

from auto_game_unified.core.matcher import (
    find_all_templates,
    find_best_template,
    find_template,
    load_template,
)


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


class FindAllTemplatesTests(unittest.TestCase):
    """``find_all_templates``：同一个模板在一屏里出现多次时，**全部**都要拿到。

    实际用途就是骑士团捐赠的支援列表 —— 每一行右侧都有一个一模一样的绿色「支援1个」，
    而业务要逐个点过去；``find_best_template`` 永远只给最高分那一个，会死磕同一行。
    """

    #: 四个矩形的**左上角**（彼此相距 120 以上，远大于下面用的 min_gap）。
    CORNERS = ((20, 30), (140, 30), (260, 30), (20, 200))

    def _four_instances(self) -> tuple[np.ndarray, np.ndarray, set[tuple[int, int]]]:
        rng = np.random.default_rng(11)
        template = rng.integers(0, 256, size=(20, 20, 3), dtype=np.uint8)
        screen = np.zeros((300, 340, 3), dtype=np.uint8)
        for x, y in self.CORNERS:
            screen[y : y + 20, x : x + 20] = template
        return screen, template, {(x + 10, y + 10) for x, y in self.CORNERS}

    def test_returns_every_instance_instead_of_only_the_best(self):
        screen, template, expected = self._four_instances()

        found = find_all_templates(screen, template, 0.95, min_gap=40)

        self.assertEqual(4, len(found))
        self.assertEqual(expected, {match.center for match in found})
        # 分数降序 —— 调用方按「先点最有把握那个」的顺序取。
        self.assertEqual(
            sorted((match.score for match in found), reverse=True),
            [match.score for match in found],
        )

    def test_the_same_instance_is_not_reported_twice(self):
        """非极大值抑制半径之内只留一个峰（否则同一个按钮会被沿边缘报两次）。"""
        screen, template, _ = self._four_instances()

        tight = find_all_templates(screen, template, 0.95, min_gap=40)
        loose = find_all_templates(screen, template, 0.95, min_gap=400)

        self.assertEqual(4, len(tight))
        self.assertEqual(1, len(loose))

    def test_threshold_and_region_both_apply(self):
        screen, template, _ = self._four_instances()

        self.assertEqual([], find_all_templates(screen, template, 1.01, min_gap=40))
        in_region = find_all_templates(
            screen, template, 0.95, region=(130, 0, 60, 80), min_gap=40
        )

        self.assertEqual([(150, 40)], [match.center for match in in_region])

    def test_scaled_screen_keeps_the_aspect_ratio_contract(self):
        """``reference_size`` 与画面不一致时按比例缩放；宽高比不符就抛错。"""
        screen, template, expected = self._four_instances()
        scaled = cv2.resize(screen, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

        found = find_all_templates(
            scaled, template, 0.90, reference_size=(340, 300), min_gap=40
        )

        self.assertEqual(
            {(x // 2, y // 2) for x, y in expected},
            {match.center for match in found},
        )

        with self.assertRaises(RuntimeError):
            find_all_templates(
                scaled, template, 0.90, reference_size=(340, 200), min_gap=40
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
