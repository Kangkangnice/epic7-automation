import unittest

import numpy as np

from auto_game_unified.core.supervisor import (
    StableObservation,
    Watchdog,
    left_page,
    meaningful_change,
    page_or_picture_changed,
)


class SupervisorTests(unittest.TestCase):
    def test_requires_two_consecutive_equal_observations(self):
        stable = StableObservation(required=2)

        self.assertFalse(stable.update("loading"))
        self.assertFalse(stable.update("stage"))
        self.assertTrue(stable.update("stage"))
        self.assertTrue(stable.update("stage"))
        self.assertFalse(stable.update("team"))

    def test_watchdog_tracks_progress_and_absolute_deadline(self):
        now = [0.0]
        watchdog = Watchdog(no_progress_seconds=45, absolute_seconds=180, now=lambda: now[0])
        now[0] = 40
        self.assertIsNone(watchdog.expired_reason())
        watchdog.progress()
        now[0] = 84
        self.assertIsNone(watchdog.expired_reason())
        now[0] = 86
        self.assertEqual("no_progress", watchdog.expired_reason())
        now[0] = 181
        self.assertEqual("absolute", watchdog.expired_reason())

    def test_meaningful_change_ignores_static_frame(self):
        before = np.zeros((720, 1280, 3), dtype=np.uint8)
        after = before.copy()
        after[150:500, 250:1000] = 20

        self.assertFalse(meaningful_change(before, before))
        self.assertTrue(meaningful_change(before, after))

    def test_left_page_only_accepts_a_real_page_change(self):
        """点击验收用**严格**判据：画面在动但没换页，不算这一下生效。

        实测（``runtime_logs/_probe_click_verify.py``）：同一页面的不同帧平均差
        11.10 / 12.95 / 45.03，而真实转场的相邻帧可以低到 **0.00** —— 两个区间完全
        重叠，画面差区分不了「原地在动」和「换页」。所以这条判据绝不能拿
        ``meaningful_change`` 兜底，否则大厅那种自带待机动画的页面上每一次点击
        都会被判成「生效」。
        """
        self.assertTrue(left_page("lobby", "arena_mode"))
        self.assertFalse(left_page("lobby", "lobby"))

    def test_page_or_picture_changed_accepts_animation_on_the_same_page(self):
        """返回验收用**宽松**判据：同一页但画面明显变化，也算生效。"""
        before = np.zeros((720, 1280, 3), dtype=np.uint8)
        animated = before.copy()
        animated[150:500, 250:1000] = 20

        self.assertTrue(page_or_picture_changed("lobby", before, "arena_mode", before))
        self.assertTrue(page_or_picture_changed("lobby", before, "lobby", animated))
        self.assertFalse(page_or_picture_changed("lobby", before, "lobby", before))


if __name__ == "__main__":
    unittest.main()
