"""购买旗帜：游戏拒绝时怎么收工。

## 2026-11-23 的改动（用户拍板删锁）

以前程序自己在 ``runtime_logs/arena_ticket_purchase.txt`` 里记一个日期，判断
「今天已经买过了」，命中就直接收工、一次都不点。这个做法有两个站不住的假设：

1. **本机零点 = 游戏每日重置点**。国服/亚服/美服/欧服的刷新时刻并不相同，
   玩家在国内玩美服时，本机日期与游戏「今天」必然错位；
2. **我们比游戏更清楚还能不能买**。同一个号第二次来买，游戏自己就会拒绝，
   这件事只有游戏知道。

现在改成「点下去，看游戏接不接受」：弹窗关掉 = 买成功；弹窗不关 = 游戏拒绝 ⇒
按资源耗尽正常收工（``TicketExhausted``，退出码仍为 0）。

这个测试就是把那条路钉住：**必须真的尝试过购买**，然后干净地结束。
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
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import REGIONS


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


class TicketExhaustionTests(unittest.TestCase):
    def test_runner_gives_up_cleanly_when_the_game_refuses_the_purchase(self):
        # 一整帧都是「购买旗帜」弹窗：点购买之后画面不会变，等同游戏拒绝了这次购买。
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

        # 收工必须是正常结束：弹窗关不掉属于业务结论，不是故障。
        self.assertEqual(0, runner.run())
        self.assertTrue(runner.resource_exhausted)

        # ⚠️ 这一条是删锁之后的核心行为：程序**会**去点一次购买。
        # 将来谁把「按本地日期提前判死」加回来，这里会立刻失败 —— 那正是要防的。
        left, top, width, height = REGIONS["ticket_purchase_button"]
        self.assertTrue(
            any(
                left <= x < left + width and top <= y < top + height
                for x, y in clicks
            ),
            f"应当尝试过购买按钮再收工，实际点击 {clicks}",
        )


if __name__ == "__main__":
    unittest.main()
