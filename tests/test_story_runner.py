from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from auto_game_unified.core.battle_supervisor import BattleOutcome
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
    def test_committed_battle_returns_control_to_results_state(self):
        machine = MagicMock()
        machine.state = StoryState.WAIT_BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = StoryRunner(
            machine,
            Runtime(
                lambda: np.zeros((60, 100, 3), dtype=np.uint8),
                lambda point: None,
            ),
            battle_supervisor=supervisor,
            sleep=lambda seconds: None,
        )

        runner._run_committed_battle(cycle=1)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
        self.assertEqual(StoryState.WAIT_RESULTS, machine.state)

    def test_committed_battle_hands_stamina_popup_back_to_wait_battle(self):
        machine = MagicMock()
        machine.state = StoryState.WAIT_BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.PRE_BATTLE_BUSINESS
        runner = StoryRunner(
            machine,
            Runtime(
                lambda: np.zeros((60, 100, 3), dtype=np.uint8),
                lambda point: None,
            ),
            battle_supervisor=supervisor,
            sleep=lambda seconds: None,
        )

        runner._run_committed_battle(cycle=12)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=12)
        self.assertEqual(StoryState.WAIT_BATTLE, machine.state)

    def test_a_stuck_action_ends_the_route_without_any_way_back(self):
        """卡住就结束 —— 程序里**根本不存在**「回大厅重新导航然后接着跑」这条通道。

        用户 2026-09-26 拍板：「回家触发完之后，回到首页，说明这个就结束了，不可能会再
        回到这个任务」。以前这里的行为是「连点不动 ⇒ ``recovery()``（回大厅重新导航）
        ⇒ 接着跑」，实跑里的表现就是「又从头做了一遍」。

        两条一起守：① **行为上** —— 4 次点击之后直接抛错结束，一次都不多点
        （``test_same_action_stops_after_four_failed_clicks``）；
        ② **结构上** —— Runner 上连一个「恢复」入口都没有（这条）。
        谁把那条通道加回来，这里立刻红。
        """

        class FakeMachine:
            def __init__(self) -> None:
                self.state = StoryState.STAGE
                self.completed_cycles = 0
                self.auto_enabled = False
                self.auto_click_attempted = False

            def preview(self, _screen):
                return StoryAction("stuck", (1, 1)), (
                    StoryState.STAGE,
                    self.completed_cycles,
                )

            def next_action(self, _screen):
                return StoryAction("stuck", (1, 1))

        runtime = Runtime(
            lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
            lambda _: None,
            emit=lambda _: None,
        )
        machine = FakeMachine()
        runner = StoryRunner(machine, runtime, sleep=lambda _: None)
        runner._ACTION_RETRY_SECONDS = 0

        with patch.object(
            runtime, "save_diagnostic", return_value=Path("diagnostic.png")
        ):
            with self.assertRaisesRegex(
                RuntimeError, r"动作 stuck 点击4次后画面未推进"
            ):
                runner.run(max_cycles=2)

        self.assertEqual(0, machine.completed_cycles)
        for absent in ("recovery", "recover", "_apply_recovery_state"):
            self.assertFalse(
                hasattr(runner, absent), f"Runner 上又多了一条退路：{absent}"
            )

    def test_updated_battle_stage_uses_prepare_battle_action(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        action = machine.next_action(fixture("stage_battle_ready_updated"))

        self.assertEqual("prepare_battle", action.name)
        self.assertEqual(StoryState.STAGE, machine.state)

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
        self.assertEqual(
            1, sum("执行点击 动作=prepare_battle 坐标=" in event for event in logs)
        )

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

        runner = StoryRunner(
            StoryStateMachine(build_story_templates(TEMPLATES)),
            Runtime(
                lambda: next(screens),
                lambda _: None,
                emit=lambda _: None,
                monotonic=lambda: now[0],
            ),
            sleep=wait,
        )

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

            with self.assertRaisesRegex(RuntimeError, r"空跑未识别画面\[关卡入口\]"):
                runner.run(max_cycles=1)

        self.assertEqual([], sleeps)

    def test_two_cycles_complete_and_enable_auto_once_per_cycle(self):
        names = [
            "stage", "assistant", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
            "story", "skip_confirm", "battle_auto_on_live_20260809",
            "reward", "clear", "results", "complete", "next_stage",
            "stage", "team", "story", "skip_confirm",
            "battle_auto_off_live_20260809", "battle_auto_on_live_20260809",
            "reward", "clear", "results", "complete", "bonus_reward", "story_watch_next_ep4",
        ]
        screens = iter(
            fixture(name)
            for name in names
            for _ in range(4 if name == "reward" else 2)
        )
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runtime = Runtime(lambda: next(screens), clicks.append, emit=logs.append)
        runner = StoryRunner(
            StoryStateMachine(build_story_templates(TEMPLATES)), runtime, sleep=lambda _: None
        )

        completed = runner.run(max_cycles=2)

        self.assertEqual(2, completed)
        self.assertEqual(
            2,
            sum("执行点击 动作=enable-auto-battle 坐标=" in event for event in logs),
        )
        self.assertEqual(2, sum("执行点击 动作=reward 坐标=" in event for event in logs))
        self.assertEqual(2, sum("状态=自动战斗已开启" in event for event in logs))
        self.assertEqual(22, len(clicks))

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

    def test_same_action_stops_after_four_failed_clicks(self):
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

            with self.assertRaisesRegex(
                RuntimeError, r"动作 prepare_battle 点击4次后画面未推进"
            ):
                runner.run(max_cycles=1)

        self.assertEqual(4, len(clicks))

    def test_the_self_heal_lets_a_different_action_through(self):
        """卡住之后路线**换个办法** ⇒ 新动作照常点（自救没有被做成「直接放弃」）。

        与上面那条是一对：``test_same_action_stops_after_four_failed_clicks`` 守
        「换回来还是原样 ⇒ 立刻收手」，这条守「真换了办法 ⇒ 继续干活」。
        两条合起来才是自救的形状 —— **多给一次「换个办法」的机会，不是多给点击预算**。

        ⚠️ 为什么必须有这条：骑士团捐赠**就靠这个机制**活着 ——
        「支援连点 4 次推不动 ⇒ 原地切每周任务」（``support_closed``）。
        把自救整个删掉（第一次耗尽就直接收手）**不会让别的任何测试变红**，
        所以只能在这里钉住；少了它，那一天的每周任务领奖会整条丢掉。
        """

        class SwitchingRunner(StoryRunner):
            def _on_action_exhausted(self, action, screen) -> bool:
                # 学捐赠：推不动就置上「这一节收工」，交给主循环原地再决策一次。
                self.machine.switched = True
                return False

        class FakeMachine:
            """推不动就一直给 ``stuck``；自救之后改成 ``switched``（换了个办法）。

            换成的那个动作**先要被点**，点完这一轮才算做成 ⇒ 一路走完 ``completed_cycles``
            才会 +1（照捐赠「切到每周任务、把奖领了收工」的形状）。
            """

            def __init__(self) -> None:
                self.state = StoryState.STAGE
                self.completed_cycles = 0
                self.auto_enabled = False
                self.auto_click_attempted = False
                self.switched = False
                self.switched_clicked = False

            def preview(self, _screen):
                if self.switched and self.switched_clicked:
                    return None, (StoryState.STAGE, self.completed_cycles)
                name = "switched" if self.switched else "stuck"
                return StoryAction(name, (2, 2) if self.switched else (1, 1)), (
                    StoryState.STAGE,
                    self.completed_cycles,
                )

            def next_action(self, _screen):
                if not self.switched:
                    return StoryAction("stuck", (1, 1))
                if self.switched_clicked:
                    self.completed_cycles = 1  # 换个办法做成了 ⇒ 这一轮走完
                    return None
                return StoryAction("switched", (2, 2))

        machine = FakeMachine()
        clicks: list[tuple[int, int]] = []

        def click(point: tuple[int, int]) -> None:
            clicks.append(point)
            if point == (2, 2):
                machine.switched_clicked = True

        with TemporaryDirectory() as directory:
            # 给诊断目录：万一自救被删掉，这里会在**抛错**时把「动作 stuck …」
            # 带出来（比「未配置诊断截图目录」好读得多）。
            runtime = Runtime(
                lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
                click,
                diagnostic_dir=Path(directory),
                emit=lambda _: None,
            )
            runner = SwitchingRunner(machine, runtime, sleep=lambda _: None)
            runner._ACTION_RETRY_SECONDS = 0

            completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        self.assertEqual(
            [(1, 1)] * 4 + [(2, 2)],
            clicks,
            f"自救之后应该点新动作（(2,2)）而不是收手，实际={clicks}",
        )

    def test_source_departure_without_target_never_repeats_old_transition_click(self):
        screens = iter(
            [fixture("stage")] * 2
            + [np.zeros((1132, 1982, 3), dtype=np.uint8)] * 2
        )
        clicks: list[tuple[int, int]] = []
        now = [0.0]

        def wait(_: float) -> None:
            now[0] += 50.0

        with TemporaryDirectory() as directory:
            runtime = Runtime(
                lambda: next(screens),
                clicks.append,
                diagnostic_dir=Path(directory),
                emit=lambda _: None,
                monotonic=lambda: now[0],
            )
            runner = StoryRunner(
                StoryStateMachine(build_story_templates(TEMPLATES)),
                runtime,
                sleep=wait,
            )

            with self.assertRaisesRegex(RuntimeError, r"页面无进展"):
                runner.run(max_cycles=1)

        self.assertEqual(1, len(clicks))

    def test_skip_confirmation_can_return_to_story_for_another_skip_transaction(self):
        screens = iter(
            [fixture("skip_confirm")] * 2
            + [fixture("story")] * 2
            + [np.zeros((1132, 1982, 3), dtype=np.uint8)] * 4
        )
        clicks: list[tuple[int, int]] = []
        now = [0.0]

        def wait(_: float) -> None:
            now[0] += 50.0

        with TemporaryDirectory() as directory:
            runner = StoryRunner(
                StoryStateMachine(
                    build_story_templates(TEMPLATES),
                    initial_state=StoryState.WAIT_SKIP_CONFIRM,
                ),
                Runtime(
                    lambda: next(screens),
                    clicks.append,
                    diagnostic_dir=Path(directory),
                    emit=lambda _: None,
                    monotonic=lambda: now[0],
                ),
                sleep=wait,
            )

            with self.assertRaisesRegex(RuntimeError, r"页面无进展"):
                runner.run(max_cycles=1)

        self.assertEqual(2, len(clicks))

    def test_skip_confirmation_that_ends_the_story_lands_on_the_clear_prompt(self):
        """跳过最后一段剧情后游戏直接给「通关提示」，转场契约必须认它。

        2026-09-18 14:14:07 / 14:47:46 两次实跑就死在这里：skip_confirm 的
        target_pages 里没有「通关提示」，转场永远不成立 → 干等 45 秒 →
        「转场超时 动作=skip_confirm … 当前已确认页面=通关提示」→ 退出码 1。
        这条守住「通关提示也算 skip_confirm 的合法落点」，并且必须接着点
        complete 往下走，而不是超时。
        """
        screens = iter(
            [fixture("skip_confirm")] * 2
            + [fixture("complete")] * 2
            + [np.zeros((1132, 1982, 3), dtype=np.uint8)] * 8
        )
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        now = [0.0]

        def wait(_: float) -> None:
            now[0] += 50.0

        with TemporaryDirectory() as directory:
            runner = StoryRunner(
                StoryStateMachine(
                    build_story_templates(TEMPLATES),
                    initial_state=StoryState.WAIT_SKIP_CONFIRM,
                ),
                Runtime(
                    lambda: next(screens),
                    clicks.append,
                    diagnostic_dir=Path(directory),
                    emit=logs.append,
                    monotonic=lambda: now[0],
                ),
                sleep=wait,
            )

            with self.assertRaisesRegex(RuntimeError, r"无进展"):
                runner.run(max_cycles=1)

        # 先点跳过确认，再点通关提示——没有被超时打断
        self.assertEqual(2, len(clicks))
        self.assertTrue(
            any(
                "完成=skip_confirm" in line and "目标页面=通关提示" in line
                for line in logs
            ),
            logs,
        )
        self.assertTrue(any("操作=complete" in line for line in logs), logs)
        self.assertFalse(any("转场超时" in line for line in logs), logs)

    def test_complete_screen_takes_priority_over_a_false_skip_match(self):
        machine = StoryStateMachine(build_story_templates(TEMPLATES))

        def locate(_screen, name):
            if name in {"skip", "complete"}:
                return Match((1000, 500), 0.90)
            return None

        with patch.object(machine, "_locate", side_effect=locate):
            action = machine.next_action(np.zeros((1132, 1982, 3), dtype=np.uint8))

        self.assertEqual("complete", action.name)
        self.assertEqual(StoryState.WAIT_COMPLETE, machine.state)


if __name__ == "__main__":
    unittest.main()
