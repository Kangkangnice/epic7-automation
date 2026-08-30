from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from auto_game_unified.core.runtime import Runtime


class RuntimeLoggingTests(unittest.TestCase):
    def test_writes_and_streams_timestamped_log_entries(self):
        with TemporaryDirectory() as directory:
            log_path = Path(directory) / "arena.log"
            messages: list[str] = []
            runtime = Runtime(
                lambda: np.zeros((2, 2, 3), dtype=np.uint8),
                lambda _: None,
                log_path=log_path,
                emit=messages.append,
            )

            runtime.log("state=team action=battle-start")

            self.assertIn("state=team action=battle-start", log_path.read_text(encoding="utf-8"))
            self.assertTrue(any("state=team action=battle-start" in message for message in messages))

    def test_rotates_logs_at_the_configured_size(self):
        with TemporaryDirectory() as directory:
            log_path = Path(directory) / "story.log"
            runtime = Runtime(
                lambda: np.zeros((2, 2, 3), dtype=np.uint8),
                lambda _: None,
                log_path=log_path,
                max_log_bytes=80,
                log_backups=2,
                emit=lambda _: None,
            )

            for index in range(12):
                runtime.log(f"message-{index}-" + "x" * 30)

            self.assertTrue(log_path.exists())
            self.assertTrue(Path(f"{log_path}.1").exists())
            self.assertLessEqual(len(list(Path(directory).glob("story.log*"))), 3)


if __name__ == "__main__":
    unittest.main()
