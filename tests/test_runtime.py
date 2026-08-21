from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime


class RuntimeTests(unittest.TestCase):
    def test_capture_guard_time_is_excluded_from_runtime_clock(self):
        clock = [10.0]
        guarded = np.full((3, 4, 3), 127, dtype=np.uint8)
        runtime = Runtime(
            lambda: guarded,
            lambda _: None,
            monotonic=lambda: clock[0],
        )

        def guard(runtime, screen):
            clock[0] += 7.0
            return screen, True

        runtime.set_capture_guard(guard)
        before = runtime.now()

        assert np.array_equal(runtime.capture(), guarded)
        assert runtime.now() == before

    def test_p_stop_saves_last_frame_and_prevents_the_next_click(self):
        stop_states = iter([False, True])
        clicks: list[tuple[int, int]] = []
        lines: list[str] = []
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: np.full((3, 4, 3), 127, dtype=np.uint8),
                clicks.append,
                diagnostic_dir=Path(directory),
                emit=lines.append,
                stop_requested=lambda: next(stop_states),
            )

            runtime.capture()
            with self.assertRaises(ManualStop):
                runtime.click((12, 34), "must-not-click")

            diagnostics = list(Path(directory).glob("*_manual_stop.png"))

        self.assertEqual([], clicks)
        self.assertEqual(1, len(diagnostics))
        self.assertEqual(
            1,
            sum("用户按下 P，正在中断自动化" in line for line in lines),
        )

    def test_back_is_logged_and_not_sent_in_dry_run(self):
        backs: list[bool] = []
        lines: list[str] = []
        runtime = Runtime(
            lambda: np.zeros((10, 10, 3), dtype=np.uint8),
            lambda _: None,
            back=lambda: backs.append(True),
            dry_run=True,
            emit=lines.append,
        )

        runtime.back("return-home")

        self.assertEqual([], backs)
        self.assertTrue(any("执行返回 动作=return-home" in line for line in lines))

    def test_dry_run_streams_but_does_not_click(self):
        clicks: list[tuple[int, int]] = []
        messages: list[str] = []
        runtime = Runtime(
            lambda: np.zeros((3, 4, 3), dtype=np.uint8),
            clicks.append,
            dry_run=True,
            emit=messages.append,
        )

        runtime.click((12, 34), "select-first-row")

        self.assertEqual([], clicks)
        self.assertTrue(any("空跑" in message and "动作=select-first-row" in message for message in messages))

    def test_live_run_clicks_and_diagnostic_is_saved(self):
        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: np.full((3, 4, 3), 127, dtype=np.uint8),
                clicks.append,
                diagnostic_dir=Path(directory),
            )

            runtime.click((12, 34), "challenge")
            path = runtime.save_diagnostic("unknown")

            self.assertEqual([(12, 34)], clicks)
            self.assertTrue(path.exists())
            self.assertTrue(path.name.endswith("_unknown.png"))

    def test_diagnostics_keep_only_the_newest_limit(self):
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: np.full((3, 4, 3), 127, dtype=np.uint8),
                lambda _: None,
                diagnostic_dir=Path(directory),
                diagnostic_limit=2,
                emit=lambda _: None,
            )

            runtime.save_diagnostic("first")
            runtime.save_diagnostic("second")
            runtime.save_diagnostic("third")

            diagnostics = list(Path(directory).glob("*_*.png"))
            self.assertEqual(2, len(diagnostics))
            self.assertFalse(any("first" in path.name for path in diagnostics))

    def test_current_frame_is_overwritten_instead_of_accumulated(self):
        frames = iter(
            [
                np.zeros((3, 4, 3), dtype=np.uint8),
                np.full((3, 4, 3), 255, dtype=np.uint8),
            ]
        )
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: next(frames),
                lambda _: None,
                diagnostic_dir=Path(directory),
                emit=lambda _: None,
            )

            first = runtime.save_current_frame()
            second = runtime.save_current_frame()

            self.assertEqual(first, second)
            self.assertEqual("current.png", second.name)
            self.assertEqual(1, len(list(Path(directory).glob("current*.png"))))


if __name__ == "__main__":
    unittest.main()
