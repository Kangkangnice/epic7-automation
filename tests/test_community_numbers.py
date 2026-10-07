"""社区 H5 数字读数的离线验收。

判据是**读到的东西 == 肉眼读帧得到的值**，不是「能读出个数」—— 字模被污染时
照样读得出一个数，只是那个数是错的，而错的数字会直接变成业务动作。
"""

from __future__ import annotations

from pathlib import Path
import unittest

import cv2
import numpy as np

from auto_game_unified.games.epic7 import community_numbers as cn


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_community"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "community"

BALANCE_EXCHANGE = (160, 246, 92, 46)
BALANCE_TASKS = (166, 532, 76, 46)
TASK_ROWS = {
    1: (185, 1160, 96, 70),
    2: (185, 1302, 96, 70),
    3: (185, 1444, 96, 70),
}
LIMIT_SLOTS = {
    "card1": (382, 380, 40, 28),
    "card2": (921, 380, 40, 28),
    "card3": (382, 960, 40, 28),
    "card4": (921, 960, 40, 28),
}


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    if image is None:
        raise AssertionError(f"缺夹具 {name}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class CommunityNumberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glyphs = cn.load_digit_glyphs(TEMPLATES)

    # ---- 字模本身 ----

    def test_glyph_set_covers_all_ten_digits(self):
        self.assertEqual(sorted(self.glyphs), list(range(10)))
        for digit, template in self.glyphs.items():
            with self.subTest(digit=digit):
                self.assertEqual(template.shape, (cn.GLYPH_CANVAS[1], cn.GLYPH_CANVAS[0]))

    def test_missing_glyph_file_raises(self):
        """缺一张字模必须当场炸，不许「读不出来就跳过」式静默降级。"""
        with self.assertRaises(FileNotFoundError) as ctx:
            cn.load_digit_glyphs(ROOT / "tests" / "fixtures" / "_no_such_templates")
        self.assertIn("缺社区数字字模", str(ctx.exception))

    def test_canvas_is_tall_enough_for_the_source_glyphs(self):
        """画布高度必须 ≥ 源字高（26px）。

        下采样（画布高 24）会把笔画宽度的亚像素差异放大成整像素差异，
        跨帧同串只有 0.60~0.70；上采样（30）才对。这条钉住这个结论。
        """
        self.assertGreaterEqual(cn.GLYPH_CANVAS[1], 30)

    def test_portrait_size_matches_the_capture_channel(self):
        """本模块的基准画布必须和竖屏截图通道一致，不然所有区域坐标都是错的。"""
        from auto_game_unified.core.portrait import PORTRAIT_CANVAS

        self.assertEqual(cn.PORTRAIT_SIZE, PORTRAIT_CANVAS)

    # ---- 读数 ----

    def test_reads_points_balance(self):
        cases = [
            ("exchange_after_redeem_live_20261006", BALANCE_EXCHANGE, 880),
            ("tasks_all_done_live_20261006", BALANCE_TASKS, 880),
            ("tasks_one_browse_done_live_20261006", BALANCE_TASKS, 920),
        ]
        for name, region, expected in cases:
            with self.subTest(fixture=name, region=region):
                readout = cn.read_digits(fixture(name), region, self.glyphs)
                self.assertEqual(expected, readout.value, readout.describe())

    def test_reads_task_progress_on_every_layout(self):
        """同一串值在三种排版下都要读得出 —— 这是「跨帧」这条判据的核心。"""
        cases = [
            ("tasks_fresh_live_20261006", {1: (0, 3), 2: (3, 3), 3: (0, 1)}),
            ("tasks_one_browse_done_live_20261006", {1: (1, 3), 2: (3, 3), 3: (0, 1)}),
            ("tasks_all_done_live_20261006", {1: (3, 3), 2: (3, 3), 3: (1, 1)}),
        ]
        for name, rows in cases:
            screen = fixture(name)
            for index, expected in rows.items():
                with self.subTest(fixture=name, row=index):
                    readout = cn.read_pair(screen, TASK_ROWS[index], self.glyphs)
                    self.assertEqual(expected, readout.value, readout.describe())

    def test_reads_daily_purchase_limits(self):
        screen = fixture("exchange_after_redeem_live_20261006")
        cases = {"card1": (1, 2), "card2": (1, 1), "card3": (0, 1), "card4": (1, 1)}
        for card, expected in cases.items():
            with self.subTest(card=card):
                readout = cn.read_pair(screen, LIMIT_SLOTS[card], self.glyphs)
                self.assertEqual(expected, readout.value, readout.describe())

    # ---- 三态与边界 ----

    def test_abstains_instead_of_guessing(self):
        """切不出字形的区域必须弃权，**不许**返回 0 或任何猜测值。"""
        blank = np.full((1920, 1080, 3), 255, np.uint8)
        readout = cn.read_digits(blank, (100, 100, 80, 40), self.glyphs)
        self.assertIsNone(readout.value)

        pair = cn.read_pair(blank, (100, 100, 80, 40), self.glyphs)
        self.assertIsNone(pair.value)

    def test_pair_needs_exactly_three_components(self):
        """括号之类的多余组件会被高度上限挡掉，所以「切出 3 个」这条判据成立。

        任务进度的括号是 10x39；一旦放行，组件数就变成 5，读数直接弃权。
        """
        self.assertLess(cn.GLYPH_MAX_HEIGHT, 39)
        screen = fixture("tasks_all_done_live_20261006")
        mask = cn.binarize(screen[1160:1230, 185:281])
        found = cn.glyph_boxes(mask)
        self.assertEqual(3, len(found), f"切出的组件：{found}")


if __name__ == "__main__":
    unittest.main()
