"""竞技场判据证据的全库护栏。

这些用例不新增判据，也不改阈值：它们守住既有证据边界，
让「真机输局仍在兜底锚点阈下」「非结算夹具不触发兜底」「周奖励红点两态可分」
在后续补图时不会被悄悄破坏。
"""

import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.arena import (
    ArenaOutcome,
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


if __name__ == "__main__":
    unittest.main()
