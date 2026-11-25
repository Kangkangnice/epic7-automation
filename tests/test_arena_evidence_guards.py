"""竞技场判据证据的全库护栏。

这些用例不新增判据，也不改阈值：它们守住既有证据边界，
让「真机输局仍在兜底锚点阈下」「非结算夹具不触发兜底」「周奖励红点两态可分」
在后续补图时不会被悄悄破坏。
"""

import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    Action,
    ArenaOutcome,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import (
    WEEKLY_REWARD_DOT_MIN_PIXELS,
    weekly_reward_dot_pixels,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class ArenaEvidenceGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = ArenaStateMachine(build_templates(TEMPLATES))

    def test_real_defeat_frame_keeps_the_fallback_anchor_below_threshold(self):
        screen = fixture("result_defeat_live_20260925")
        threshold = self.machine._THRESHOLDS["result_rating"]

        self.assertLess(self.machine.outcome_scores(screen)["result_rating"], threshold)
        self.assertIs(ArenaOutcome.LOSE, self.machine.observe_outcome(screen))

    def test_no_non_result_fixture_fires_the_fallback_anchor(self):
        threshold = self.machine._THRESHOLDS["result_rating"]
        offenders: list[str] = []
        for path in sorted(FIXTURES.glob("*.png")):
            screen = fixture(path.stem)
            scores = self.machine.outcome_scores(screen)
            if scores["result_rating"] < threshold:
                continue
            has_banner = self.machine._visible(
                screen, "result_victory"
            ) or self.machine._visible(screen, "result_defeat")
            if not has_banner:
                offenders.append(path.name)

        self.assertEqual([], offenders)

    def test_weekly_reward_dot_fixtures_stay_on_opposite_sides(self):
        claimable = fixture("weekly_reward_claimable_live_20261117")
        claimed = fixture("weekly_reward_claimed_live_20261117")

        self.assertGreaterEqual(
            weekly_reward_dot_pixels(claimable), WEEKLY_REWARD_DOT_MIN_PIXELS
        )
        self.assertLess(
            weekly_reward_dot_pixels(claimed), WEEKLY_REWARD_DOT_MIN_PIXELS
        )

    def test_a_dimmed_frame_reads_as_already_claimed_known_defect(self):
        """**已知缺陷的现状快照**：遮罩把红点压暗后，读数与「已领完」无法区分。

        2026-11-18 08:43 真机踩中：点每周对战奖励后 3.5 秒弹出「与服务器的连接已中断」
        全屏遮罩，红点像素读数变成 0，等待器据此置「本轮已检查」；实际奖励并未入账
        （09:11 复测才真正领到）。遮罩帧整屏均亮约 14，同页正常列表 45~63。

        这里没有那份遮罩真机帧（见 `.workbuddy/memory/竞技场收口交接_20261125.md`
        的采集清单），所以按同一亮度档把 11-17 的可领帧压到 0.3 倍来表达机制：
        HSV 的 V 掉到 140 以下，红点掩膜颗粒无收。**这是现状，不是期望行为**；
        修复（加整屏亮度或遮罩第二维）后本测试必须同步改成「不得判已领完」。
        """
        claimable = fixture("weekly_reward_claimable_live_20261117")
        self.assertGreaterEqual(
            weekly_reward_dot_pixels(claimable), WEEKLY_REWARD_DOT_MIN_PIXELS
        )

        masked = np.clip(claimable.astype(np.float32) * 0.3, 0, 255).astype(np.uint8)
        self.assertLess(
            weekly_reward_dot_pixels(masked), WEEKLY_REWARD_DOT_MIN_PIXELS
        )

        # 危险的不是「读数 0」本身，而是同一帧仍满足列表判据 ⇒ 等待器直接收下
        # 「已领完」。两件事同时成立才构成那次误判。
        self.assertTrue(self.machine.is_in_state(masked, ArenaState.LIST))
        runner = ArenaRunner(
            self.machine,
            Runtime(
                lambda: masked,
                lambda point: None,
                emit=lambda line: None,
            ),
            sleep=lambda seconds: None,
        )
        self.assertTrue(
            runner._wait_until_weekly_reward_claimed(
                Action("claim-weekly-reward", (245, 696))
            ),
            "现状：压暗帧被等待器当成「红点已消失」",
        )


if __name__ == "__main__":
    unittest.main()
