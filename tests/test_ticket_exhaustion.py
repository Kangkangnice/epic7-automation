from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState, ArenaStateMachine, build_templates
from auto_game_unified.games.epic7.evidence.arena import REGIONS


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


class TicketExhaustionTests(unittest.TestCase):
    def test_runner_ends_without_purchase_when_it_was_already_used_today(self):
        screen = np.asarray(
            Image.open(
                FIXTURES / "friendship_ticket_offer_live_20260826.png"
            ).convert("RGB")
        )[:1132, :1982]
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
        # 票今天已用过 ⇒ 弹窗里**只能点「取消」**，绝不能落到「购买」那颗按钮上。
        # 2026-09-25：收尾新增「先关掉购买旗帜弹窗再回家」，所以这里不再断言
        # 「一次都不点」，而是断言「没有任何一次点击落在购买按钮区域内」。
        purchase_region = REGIONS["ticket_purchase_button"]
        left, top, width, height = purchase_region
        for x, y in clicks:
            self.assertFalse(
                left <= x < left + width and top <= y < top + height,
                f"不应点到购买按钮，实际点到 ({x}, {y})",
            )


if __name__ == "__main__":
    unittest.main()
