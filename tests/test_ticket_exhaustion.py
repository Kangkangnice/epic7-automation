"""购买旗帜：回执未明时怎么收口。

## 语义沿革

- 2026-11-23（用户拍板删本机日期锁）：不再用本机零点猜「今天能不能买」，改为
  真的点一次购买、由游戏决定是否接受。
- 2026-11-26（独立验收退回）：「弹窗不关」只证明**回执未明**，不是游戏明确拒绝。
  购买是不可逆动作，只提交一次；回执未明即抛 `PurchaseReceiptUnclear` 停下对账，
  不重发、不点取消、不按资源耗尽收工。只有拿到明确拒绝证据才可按资源耗尽收尾。

本用例钉住：确实点了一次购买按钮，其余动作都不发生，且停下对账。
"""

from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    PurchaseReceiptUnclear,
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import REGIONS


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


class TicketExhaustionTests(unittest.TestCase):
    def test_purchase_receipt_unclear_stops_for_reconciliation(self):
        # 一整帧都是「购买旗帜」弹窗：点购买后画面不变，只说明回执未明，不是拒绝证据。
        screen = np.asarray(
            Image.open(
                FIXTURES / "friendship_ticket_offer_live_20260826.png"
            ).convert("RGB")
        )[:1132, :1982]
        clicks: list[tuple[int, int]] = []
        elapsed = 0.0

        def sleep(seconds: float) -> None:
            nonlocal elapsed
            elapsed += seconds

        runtime = Runtime(lambda: screen, clicks.append, monotonic=lambda: elapsed)
        runner = ArenaRunner(
            ArenaStateMachine(
                build_templates(TEMPLATES), initial_state=ArenaState.BATTLE
            ),
            runtime,
            sleep=sleep,
        )

        # 回执未明 -> 停下对账，不按资源耗尽正常收工。
        with self.assertRaises(PurchaseReceiptUnclear):
            runner.run()
        self.assertFalse(runner.resource_exhausted)

        # 不可逆购买只提交一次：确实点过购买按钮，且只有这一次。
        left, top, width, height = REGIONS["ticket_purchase_button"]
        purchase_clicks = [
            point
            for point in clicks
            if left <= point[0] < left + width and top <= point[1] < top + height
        ]
        self.assertEqual(
            1, len(purchase_clicks), f"购买只提交一次，实际点击 {clicks}"
        )


if __name__ == "__main__":
    unittest.main()
