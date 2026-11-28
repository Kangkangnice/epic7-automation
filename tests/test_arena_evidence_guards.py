"""竞技场判据证据的全库护栏。

这些用例守住既有证据边界：真机输局仍在兜底锚点阈下、非结算夹具不触发兜底、
周奖励红点两态可分，以及判奖护栏的「标题白字 / 断网文案」两维不串味。
后续补图与阈值调整不得悄悄破坏这些分立。
"""

import unittest
from pathlib import Path
from unittest.mock import patch

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
    WEEKLY_REWARD_TITLE_MIN_BRIGHT_PIXELS,
    weekly_reward_dot_pixels,
    weekly_reward_title_bright_pixels,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


GLOBAL_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_global"


def fixture(name: str, *, family: str = "arena") -> np.ndarray:
    base = GLOBAL_FIXTURES if family == "global" else FIXTURES
    image = np.asarray(Image.open(base / f"{name}.png").convert("RGB"))
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

    def test_missing_network_variant_template_fails_at_build_time(self):
        """判奖依赖的断网变体模板缺失必须在装配期炸掉，不能静默带着半套判据启动。

        验收退回项：删掉 `network_disconnected_message.png` 后，全局守卫仍能靠另一张
        文案启动，而 11-18 遮罩帧恰恰只命中这张变体（0.9992，另一张 None）⇒ 判奖
        护栏失效、误判重现。缺这张 = 判据缺证，必须 fail closed。
        """
        from auto_game_unified.games.epic7 import arena as arena_module
        from auto_game_unified.games.epic7.global_popups import (
            NetworkReconnectTemplates,
            load_network_reconnect_templates,
        )

        real_loader = load_network_reconnect_templates

        def loader_without_variant(directory: Path) -> NetworkReconnectTemplates:
            templates = real_loader(directory)
            return NetworkReconnectTemplates(
                message=templates.message,
                message_alt=None,
                retry_button=templates.retry_button,
                message_reconnect=templates.message_reconnect,
            )

        # 先证明这张变体确实是唯一判据：缺了它，等价现场帧的断网文案读数为 None。
        from auto_game_unified.games.epic7.global_popups import find_network_retry

        claimable = fixture("weekly_reward_claimable_live_20261117")
        network = fixture("network_disconnected_live_20261004", family="global")
        overlay = claimable.copy()
        overlay[450 : 450 + 180, 700 : 700 + 600] = network[450 : 450 + 180, 700 : 700 + 600]
        full = real_loader(TEMPLATES / "global")
        without = loader_without_variant(TEMPLATES / "global")
        self.assertIsNotNone(find_network_retry(overlay, full), "完好装配应认出断网文案")
        self.assertIsNone(
            find_network_retry(overlay, without),
            "缺变体模板时同一帧认不出 —— 这正是必须装配期拦住的原因",
        )

        with patch.object(arena_module, "load_network_reconnect_templates", loader_without_variant):
            with self.assertRaises(FileNotFoundError) as caught:
                arena_module.build_templates(TEMPLATES)
        self.assertIn("network_disconnected_message", str(caught.exception))

    def test_title_brightness_separates_readable_from_masked_frames(self):
        """判据可证伪：标题白字在正常领奖两态与压暗/断网两态之间不重叠。"""
        for name in ("weekly_reward_claimable_live_20261117", "weekly_reward_claimed_live_20261117"):
            self.assertGreaterEqual(
                weekly_reward_title_bright_pixels(fixture(name)),
                WEEKLY_REWARD_TITLE_MIN_BRIGHT_PIXELS,
                name,
            )
        dimmed = np.clip(
            fixture("weekly_reward_claimable_live_20261117").astype(np.float32) * 0.3,
            0,
            255,
        ).astype(np.uint8)
        self.assertLess(
            weekly_reward_title_bright_pixels(dimmed),
            WEEKLY_REWARD_TITLE_MIN_BRIGHT_PIXELS,
        )
        self.assertLess(
            weekly_reward_title_bright_pixels(
                fixture("network_disconnected_live_20261004", family="global")
            ),
            WEEKLY_REWARD_TITLE_MIN_BRIGHT_PIXELS,
        )

    def test_dimmed_frame_is_not_accepted_as_claimed(self):
        """压暗把红点读成 0，但同一帧也压掉了标题白字 ⇒ 不得判「已领完」。

        2026-11-18 08:43 真机踩中：点每周对战奖励后 3.5 秒弹出全屏断网遮罩，
        红点像素读数变成 0，等待器据此置「本轮已检查」；奖励实际未入账。
        原用例把这一误判当现状快照钉住，修复后必须反过来钉「不得判已领」。

        等价帧：把 11-17 可领帧整体压到 0.3 倍（与真机遮罩整屏均亮约 14 同一档）。
        """
        claimable = fixture("weekly_reward_claimable_live_20261117")
        self.assertGreaterEqual(
            weekly_reward_dot_pixels(claimable), WEEKLY_REWARD_DOT_MIN_PIXELS
        )

        masked = np.clip(claimable.astype(np.float32) * 0.3, 0, 255).astype(np.uint8)
        self.assertLess(
            weekly_reward_dot_pixels(masked), WEEKLY_REWARD_DOT_MIN_PIXELS
        )
        # 两件事同时成立才构成那次误判：红点读 0 + 列表页判据仍成立。
        self.assertTrue(self.machine.is_in_state(masked, ArenaState.LIST))

        self.assertFalse(
            self._claim_waits(masked),
            "压暗帧不得被当成「红点已消失」",
        )

    def test_network_overlay_over_claimable_list_is_not_accepted(self):
        """11-18 等价现场帧：对手列表 + 红点被压暗 + 断网文案在场。

        真实断网帧 `network_disconnected_live_20261004.png` 本身是队伍页（LIST=False），
        不能单独触发误判。这里把它 (700,450,600,180) 的文案区叠到「局部压暗红点」
        的可领列表帧上，得到同时满足 LIST=True、红点读 0、断网文案 0.9992 的帧 ——
        这正是 11-18 的现场机制。旧等待器只看前两条，会误判已领。
        """
        claimable = fixture("weekly_reward_claimable_live_20261117")
        network = fixture("network_disconnected_live_20261004", family="global")

        red = claimable.copy()
        x, y, w, h = 265, 644, 45, 40
        red[y : y + h, x : x + w] = np.clip(
            red[y : y + h, x : x + w].astype(np.float32) * 0.3, 0, 255
        ).astype(np.uint8)
        mx, my, mw, mh = 700, 450, 600, 180
        red[my : my + mh, mx : mx + mw] = network[my : my + mh, mx : mx + mw]

        self.assertTrue(self.machine.is_in_state(red, ArenaState.LIST))
        self.assertLess(
            weekly_reward_dot_pixels(red), WEEKLY_REWARD_DOT_MIN_PIXELS
        )
        self.assertFalse(
            self._claim_waits(red),
            "断网遮罩在场时红点读数 0 不得当作已领",
        )

    def test_normal_claimed_frame_still_accepted(self):
        """反向护栏：正常已领帧必须照旧判已领，修复不得把真领奖判成失败。"""
        claimed = fixture("weekly_reward_claimed_live_20261117")
        self.assertTrue(self.machine.is_in_state(claimed, ArenaState.LIST))
        self.assertLess(
            weekly_reward_dot_pixels(claimed), WEEKLY_REWARD_DOT_MIN_PIXELS
        )
        self.assertTrue(self._claim_waits(claimed))

    def _claim_waits(self, screen: np.ndarray) -> bool:
        """用递晋升钟跑等待器，避免超时用例真的等 30 秒。"""
        ticks = iter(range(0, 100))

        def monotonic() -> float:
            return next(ticks, 99) * 2.0

        runner = ArenaRunner(
            self.machine,
            Runtime(
                lambda: screen,
                lambda point: None,
                emit=lambda line: None,
                monotonic=monotonic,
            ),
            sleep=lambda seconds: None,
        )
        return runner._wait_until_weekly_reward_claimed(
            Action("claim-weekly-reward", (245, 696))
        )


if __name__ == "__main__":
    unittest.main()
