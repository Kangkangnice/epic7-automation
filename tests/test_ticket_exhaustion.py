from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState, ArenaStateMachine, build_templates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


class TicketExhaustionTests(unittest.TestCase):
    def test_runner_ends_without_purchase_when_it_was_already_used_today(self):
        screen = np.asarray(Image.open(FIXTURES / "no_ticket.png").convert("RGB"))[:1132, :1982]
        clicks: list[tuple[int, int]] = []
        runtime = Runtime(lambda: screen, clicks.append)
        with TemporaryDirectory() as directory:
            stamp = Path(directory) / "arena_purchase.txt"
            from datetime import date
            stamp.write_text(date.today().isoformat(), encoding="utf-8")
            runner = ArenaRunner(
                ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE),
                runtime,
                sleep=lambda _: None,
                purchase_stamp_path=stamp,
            )

            self.assertEqual(0, runner.run())
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual([], clicks)


if __name__ == "__main__":
    unittest.main()
