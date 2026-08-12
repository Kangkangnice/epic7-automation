import unittest

import numpy as np

from auto_game_unified.core.supervisor import StableObservation, Watchdog, meaningful_change


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


if __name__ == "__main__":
    unittest.main()
