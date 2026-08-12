from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from auto_game_unified.core.matcher import Match
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.story import StoryAction, StoryRunner, StoryState, StoryStateMachine, build_story_templates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def fixture(name: str) -> np.ndarray:
    image = np.asarray(Image.open(FIXTURES / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


class StoryRunnerTests(unittest.TestCase):
    def test_recovery_resets_only_when_completed_cycle_count_increases(self):
        class FakeMachine:
            def __init__(self, next_cycles: int) -> None:
                self.state = StoryState.STAGE
                self.completed_cycles = 0
                self.auto_enabled = False
                self.auto_click_attempted = False
                self.phase = "stuck"
                self.next_cycles = next_cycles

            def preview(self, _screen):
                if self.phase == "complete_first":
                    return None, (StoryState.STAGE, self.next_cycles)
                return StoryAction("stuck", (1, 1)), (
                    StoryState.STAGE,
                    self.completed_cycles,
                )

            def next_action(self, _screen):
                if self.phase == "complete_first":
                    self.completed_cycles = self.next_cycles
                    self.phase = "stuck"
                    return None
                return StoryAction("stuck", (1, 1))

        for next_cycles, expected_recoveries in ((1, [0, 1]), (-1, [0])):
            with self.subTest(next_cycles=next_cycles):
                machine = FakeMachine(next_cycles)
                recoveries: list[int] = []

                def recover() -> None:
                    recoveries.append(machine.completed_cycles)
                    if machine.completed_cycles == 0:
                        machine.phase = "complete_first"

                runtime = Runtime(
                    lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                    lambda _: None,
                    emit=lambda _: None,
                )
                runner = StoryRunner(
                    machine, runtime, sleep=lambda _: None, recovery=recover
                )
                runner._ACTION_RETRY_SECONDS = 0

                with patch.object(
                    runtime, "save_diagnostic", return_value=Path("diagnostic.png")
                ):
                    with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
                        runner.run(max_cycles=2)

                self.assertEqual(expected_recoveries, recoveries)

    def test_updated_battle_stage_uses_prepare_battle_action(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(fixture("stage_battle_ready_updated"))

        self.assertEqual("prepare_battle", action.name)
        self.assertEqual(StoryState.TEAM, machine.state)

    def test_delayed_stage_transition_does_not_repeat_the_click(self):
        names = (
            ["stage"] * 8
            + [name for name in [
                "assistant", "team", "story", "skip_confirm",
                "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
                "reward", "clear", "results", "complete", "next_stage",
            ] for _ in range(2)]
        )
        screens = iter(fixture(name) for name in names)
        logs: list[str] = []
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: next(screens),
                lambda _: None,
                diagnostic_dir=Path(directory),
                emit=logs.append,
            )
            runner = StoryRunner(
                StoryStateMachine(build_story_templates(TEMPLATES)),
                runtime,
                sleep=lambda _: None,
            )

            completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual(1, sum("action=prepare_battle point=" in event for event in logs))

    def test_retry_click_gets_a_fresh_transition_timeout(self):
        names = [
            "assistant", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
            "reward", "clear", "results", "complete", "next_stage",
        ]
        screens = iter(
            [fixture("stage")] * 6
            + [np.zeros((1132, 1982, 3), dtype=np.uint8)]
            + [fixture(name) for name in names for _ in range(2)]
        )
        now = [0.0]

        def wait(_: float) -> None:
            now[0] += 20.0

        def unexpected_recovery() -> None:
            raise AssertionError("retry inherited the first click's expired timeout")

        runner = StoryRunner(
            StoryStateMachine(build_story_templates(TEMPLATES)),
            Runtime(lambda: next(screens), lambda _: None, emit=lambda _: None),
            sleep=wait,
            recovery=unexpected_recovery,
        )

        with patch(
            "auto_game_unified.games.epic7.story.monotonic",
            side_effect=lambda: now[0],
        ):
            completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)

    def test_dry_run_rejects_unknown_screen_without_polling(self):
        sleeps: list[float] = []
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: np.zeros((2000, 3200, 3), dtype=np.uint8),
                lambda _: None,
                dry_run=True,
                diagnostic_dir=Path(directory),
            )
            runner = StoryRunner(
                StoryStateMachine(build_story_templates(TEMPLATES)), runtime, sleep=sleeps.append
            )

            with self.assertRaisesRegex(RuntimeError, "dry-run"):
                runner.run(max_cycles=1)

        self.assertEqual([], sleeps)

    def test_two_cycles_complete_and_enable_auto_once_per_cycle(self):
        names = [
            "stage", "assistant", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
            "story", "skip_confirm", "battle_auto_on_live_20260809",
            "reward", "clear", "friend_request", "results", "complete", "next_stage",
            "stage", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
            "reward", "clear", "friend_request", "results", "complete", "bonus_reward", "story_watch_next_ep4",
        ]
        screens = iter(fixture(name) for name in names for _ in range(2))
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = Runtime(lambda: next(screens), clicks.append, emit=logs.append)
        runner = StoryRunner(
            StoryStateMachine(build_story_templates(TEMPLATES)), runtime, sleep=lambda _: None
        )

        completed = runner.run(max_cycles=2)

        self.assertEqual(2, completed)
        self.assertEqual(2, sum("action=enable_auto" in event for event in logs))
        self.assertEqual(2, sum("action=cancel_friend_request" in event for event in logs))
        self.assertEqual(2, sum("自动战斗=已确认" in event for event in logs))
        self.assertEqual(24, len(clicks))

    def test_story_next_stage_at_target_is_counted_without_clicking_it(self):
        screens = iter(
            fixture("story_watch_next_ep4") for _ in range(2)
        )
        clicks: list[tuple[int, int]] = []
        runner = StoryRunner(
            StoryStateMachine(
                build_story_templates(TEMPLATES),
                initial_state=StoryState.WAIT_NEXT_STAGE,
            ),
            Runtime(lambda: next(screens), clicks.append, emit=lambda _: None),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual([], clicks)

    def test_auto_visible_without_any_progress_still_times_out(self):
        screens = iter([
            fixture("battle_auto_on_live_20260809"),
            fixture("battle_auto_on_live_20260809"),
            np.zeros((1132, 1982, 3), dtype=np.uint8),
        ])
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: next(screens),
                lambda _: None,
                diagnostic_dir=Path(directory),
            )
            runner = StoryRunner(
                StoryStateMachine(build_story_templates(TEMPLATES), initial_state=StoryState.WAIT_BATTLE),
                runtime,
                sleep=lambda _: None,
            )
            runner._TIMEOUT_SECONDS = {**runner._TIMEOUT_SECONDS, StoryState.ACTIVE: 0}

            with self.assertRaisesRegex(RuntimeError, "no progress"):
                runner.run(max_cycles=1)

    def test_active_progress_ignores_static_controls_but_sees_battle_animation(self):
        runner = StoryRunner(StoryStateMachine(build_story_templates(TEMPLATES)), Runtime(
            lambda: np.zeros((1132, 1982, 3), dtype=np.uint8), lambda _: None
        ))
        before = np.zeros((1132, 1982, 3), dtype=np.uint8)
        after = before.copy()
        after[300:700, 500:1300] = 30

        self.assertFalse(runner._has_active_progress(before, before))
        self.assertTrue(runner._has_active_progress(before, after))

    def test_same_action_stops_after_two_failed_clicks(self):
        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: fixture("stage"),
                clicks.append,
                diagnostic_dir=Path(directory),
                emit=lambda _: None,
            )
            runner = StoryRunner(
                StoryStateMachine(build_story_templates(TEMPLATES)),
                runtime,
                sleep=lambda _: None,
            )
            runner._ACTION_RETRY_SECONDS = 0

            with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
                runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))

    def test_unconfirmed_auto_click_stops_without_recovery_or_second_click(self):
        now = [0.0]
        clicks: list[tuple[int, int]] = []
        recoveries: list[str] = []

        def wait(_: float) -> None:
            now[0] += 5.0

        with TemporaryDirectory() as directory:
            runner = StoryRunner(
                StoryStateMachine(
                    build_story_templates(TEMPLATES),
                    initial_state=StoryState.WAIT_BATTLE,
                ),
                Runtime(
                    lambda: fixture("battle_auto_off_live_20260809"),
                    clicks.append,
                    diagnostic_dir=Path(directory),
                    emit=lambda _: None,
                ),
                sleep=wait,
                recovery=lambda: recoveries.append("called"),
            )
            runner._AUTO_CONFIRM_SECONDS = 10

            with patch(
                "auto_game_unified.games.epic7.story.monotonic",
                side_effect=lambda: now[0],
            ):
                with self.assertRaisesRegex(RuntimeError, "auto battle was not confirmed"):
                    runner.run(max_cycles=1)

        self.assertEqual(1, len(clicks))
        self.assertEqual([], recoveries)

    def test_long_battle_does_not_consume_results_absolute_timeout(self):
        names = ["reward", "clear", "results", "complete", "next_stage"]
        screens = iter(fixture(name) for name in names for _ in range(2))
        machine = StoryStateMachine(
            build_story_templates(TEMPLATES), initial_state=StoryState.ACTIVE
        )
        machine.auto_enabled = True
        times = iter([0.0] + [200.0] * 100)

        with TemporaryDirectory() as directory:
            runner = StoryRunner(
                machine,
                Runtime(
                    lambda: next(screens),
                    lambda _: None,
                    diagnostic_dir=Path(directory),
                    emit=lambda _: None,
                ),
                sleep=lambda _: None,
            )
            with patch(
                "auto_game_unified.games.epic7.story.monotonic",
                side_effect=lambda: next(times),
            ):
                completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)

    def test_complete_screen_takes_priority_over_a_false_skip_match(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        def locate(_screen, name):
            if name in {"skip", "complete"}:
                return Match((1000, 500), 0.90)
            return None

        with patch.object(machine, "_locate", side_effect=locate):
            action = machine.next_action(np.zeros((1132, 1982, 3), dtype=np.uint8))

        self.assertEqual("complete", action.name)
        self.assertEqual(StoryState.WAIT_NEXT_STAGE, machine.state)


if __name__ == "__main__":
    unittest.main()
