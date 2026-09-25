"""竞技场「战绩」：每局判出胜负、累计、留证据、并汇报。

背景：用户要「赢了几把、输了几把」。之前只汇报「完成轮数 + 耗时」，胜负没记。

⚠️ **两个判据现在都有实测正例，测试里不能含糊**：

- 「胜」← ``result_victory``（屏幕上的「VICTORY」大字）：``epic7_arena/result.png`` 上
  1.0000，其余 438 张图最高只有 0.2724。``test_the_victory_anchor_actually_fires_on_a_win``
  守它 —— 这条以前是缺的：既有测试只断言「``rating`` **或** ``victory`` 命中其一」，
  所以 VICTORY 模板坏掉也没人知道。
- 「负」← ``result_defeat``（屏幕上的「DEFEAT」大字）：2026-09-25 补上，正例就是那天
  实跑留下的真机输局帧 ``epic7_arena/result_defeat_live_20260925.png``。
  **在这之前「负」是推理判据**（「积分面板在、VICTORY 不在」），而那份推理的兜底锚点
  ``result_rating`` 在真机上只有 0.38 ⇒ 实际效果是**输局全被判成「未知」**
  （当天实跑 5 局：3 胜 2 输，报出来是「胜 3（未知 2）」）。
- 因此下面那个**合成**的输局用例，现在守的是 ``result_rating`` 那条**兜底路径**
  （横幅还在淡入的那几帧），不再是「判负」的主依据。
- 认不出的画面（远征结算页、空白帧）仍然单列 ``UNKNOWN``，**绝不并入「负」**。
"""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified import main as main_module
from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.games.epic7.arena import (
    ArenaOutcome,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    OUTCOME_FRAME_KEEP,
    build_templates,
)
from auto_game_unified.games.epic7.evidence.arena import ARENA_RESULT_VICTORY_REGION
from auto_game_unified.main import RunResult

ROOT = Path(__file__).resolve().parents[1]
ARENA_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
EXPEDITION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_expedition"
TEMPLATES = ROOT / "games" / "epic7" / "templates"

# 「负」的第一个真帧正例：2026-09-25 实跑时被记成「未知」的那两张输局之一。
DEFEAT_FIXTURE = "result_defeat_live_20260925"

# 擦掉 VICTORY 横幅用的随机种子：固定住，失败时能原样复现。
_ERASE_SEED = 20260925


def _load(directory: Path, name: str) -> np.ndarray:
    """夹具读成 RGB 并裁到基准尺寸（旧基准 3200×2000 的图要裁左上角）。"""
    image = np.asarray(Image.open(directory / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


def arena_fixture(name: str) -> np.ndarray:
    return _load(ARENA_FIXTURES, name)


def expedition_fixture(name: str) -> np.ndarray:
    return _load(EXPEDITION_FIXTURES, name)


def new_machine() -> ArenaStateMachine:
    return ArenaStateMachine(build_templates(TEMPLATES))


def erase_victory_banner(screen: np.ndarray) -> np.ndarray:
    """合成一个「没有 VICTORY 横幅、只剩积分面板」的结算页。

    ⚠️ 这是**构造**出来的，不是真实输局画面（全库没有）。用途只有一个：验证
    「rating 在 + victory 不在 ⇒ 判负」这条推理判据的代码路径是通的。
    真机上到底长什么样，得靠实跑存下来的图来看。
    """
    screen = screen.copy()
    x, y, width, height = ARENA_RESULT_VICTORY_REGION
    rng = np.random.default_rng(_ERASE_SEED)
    # 用噪声而不是纯色：纯色区域方差为 0，归一化互相关会退化，分数没有意义。
    screen[y : y + height, x : x + width] = rng.integers(
        0, 255, (height, width, 3), dtype=np.uint8
    )
    return screen


def make_runner(
    frames: list[np.ndarray] | None = None,
    frame_dir: Path | None = None,
) -> tuple[ArenaRunner, mock.MagicMock, ArenaStateMachine]:
    """搭一个「战斗监督直接宣布到结算页」的 Runner。

    ``frames`` 按顺序喂给 ``runtime.capture``：``_record_outcome`` 每局读一帧。
    """
    runtime = mock.MagicMock()
    runtime.capture.side_effect = list(frames or [])
    machine = new_machine()
    supervisor = mock.MagicMock()
    supervisor.run.return_value = BattleOutcome.RESULT_REACHED
    runner = ArenaRunner(
        machine,
        runtime,
        sleep=lambda _seconds: None,
        battle_supervisor=supervisor,
        outcome_frame_dir=frame_dir,
    )
    return runner, runtime, machine


class OutcomeDetectionTests(unittest.TestCase):
    """一帧画面 → 赢 / 输 / 认不出。"""

    def setUp(self) -> None:
        self.machine = new_machine()

    def test_the_victory_anchor_actually_fires_on_a_win(self):
        """补上既有测试的缺口：结算页判据是「rating **或** victory」，所以单靠它
        分不出 victory 是好是坏 —— 战绩功能必须单独守住这个锚点。"""
        screen = arena_fixture("result")

        self.assertTrue(self.machine._visible(screen, "result_victory"))
        self.assertTrue(self.machine._visible(screen, "result_rating"))
        self.assertIs(ArenaOutcome.WIN, self.machine.observe_outcome(screen))

    def test_a_real_defeat_frame_reads_as_a_loss(self):
        """真机输局帧 ⇒ 判负。**「负」这一侧的第一个真帧正例**（2026-09-25 补）。

        在这之前「负」只有合成用例守着，而合成用例证明不了锚点在真机上准不准 ——
        事实也正是如此：那天的输局帧全被判成了「未知」。
        """
        screen = arena_fixture(DEFEAT_FIXTURE)

        self.assertTrue(self.machine._visible(screen, "result_defeat"))
        self.assertIs(ArenaOutcome.LOSE, self.machine.observe_outcome(screen))

    def test_the_two_banners_never_cross_fire(self):
        """胜负横幅**占同一块区域**，所以必须互不误命中，否则战绩会整体反向。

        实测间隔（``runtime_logs/_arena_defeat_probe.txt``）：赢帧上 defeat=0.1090~0.1129、
        输帧上 victory=0.1090~0.1164，离 0.80 阈值都很远。
        """
        win = arena_fixture("result")
        lose = arena_fixture(DEFEAT_FIXTURE)

        self.assertTrue(self.machine._visible(win, "result_victory"))
        self.assertFalse(self.machine._visible(win, "result_defeat"))
        self.assertTrue(self.machine._visible(lose, "result_defeat"))
        self.assertFalse(self.machine._visible(lose, "result_victory"))

        self.assertIs(ArenaOutcome.WIN, self.machine.observe_outcome(win))
        self.assertIs(ArenaOutcome.LOSE, self.machine.observe_outcome(lose))

    def test_a_result_page_without_the_victory_banner_reads_as_a_loss(self):
        """合成的「输」——见 ``erase_victory_banner`` 的依据说明。

        它现在守的是 ``result_rating`` 那条**兜底**路径（横幅还在淡入的那几帧），
        「判负」的主依据已经换成 ``result_defeat``。
        """
        screen = erase_victory_banner(arena_fixture("result"))

        self.assertFalse(self.machine._visible(screen, "result_victory"))
        self.assertFalse(self.machine._visible(screen, "result_defeat"))
        self.assertTrue(self.machine._visible(screen, "result_rating"))
        self.assertIs(ArenaOutcome.LOSE, self.machine.observe_outcome(screen))

    def test_an_expedition_result_page_is_unknown_not_a_loss(self):
        """远征结算页上三个竞技场锚点都不在 ⇒ 认不出，**绝不**并入「负」。

        认不出就报「未知」，而不是给一个看起来完整的假比分 —— 这是战绩能不能信的底线。
        """
        screen = expedition_fixture("result")

        self.assertIs(ArenaOutcome.UNKNOWN, self.machine.observe_outcome(screen))
        self.assertFalse(self.machine._visible(screen, "result_defeat"))
        self.assertFalse(self.machine._visible(screen, "result_victory"))

    def test_a_blank_screen_is_unknown(self):
        blank = np.zeros((1132, 1982, 3), np.uint8)

        self.assertIs(ArenaOutcome.UNKNOWN, self.machine.observe_outcome(blank))

    def test_detection_does_not_move_the_state_machine(self):
        """``observe_outcome`` 是纯读：接力确认过的落点不能被它改掉。"""
        self.machine.state = ArenaState.RESULT
        self.machine.observe_outcome(arena_fixture("result"))

        self.assertIs(ArenaState.RESULT, self.machine.state)


class OutcomeRecordingTests(unittest.TestCase):
    """累计与留证。"""

    def test_each_battle_records_exactly_one_outcome(self):
        """一局记一次：两次 ``_run_committed_battle`` 就是两局。"""
        win = arena_fixture("result")
        runner, _runtime, _machine = make_runner([win, win])

        runner._run_committed_battle(cycle=1)
        runner._run_committed_battle(cycle=2)

        self.assertEqual(2, runner.outcome_tally[ArenaOutcome.WIN])
        self.assertEqual(0, runner.outcome_tally[ArenaOutcome.LOSE])
        self.assertEqual(0, runner.outcome_tally[ArenaOutcome.UNKNOWN])

    def test_an_unknown_frame_still_lands_in_its_own_bucket(self):
        runner, _runtime, _machine = make_runner(
            [np.zeros((1132, 1982, 3), np.uint8)]
        )

        runner._run_committed_battle(cycle=1)

        self.assertEqual(0, runner.outcome_tally[ArenaOutcome.WIN])
        self.assertEqual(0, runner.outcome_tally[ArenaOutcome.LOSE])
        self.assertEqual(1, runner.outcome_tally[ArenaOutcome.UNKNOWN])

    def test_each_finished_game_leaves_a_frame_for_review(self):
        win = arena_fixture("result")
        with TemporaryDirectory() as directory:
            runner, _runtime, _machine = make_runner([win, win], Path(directory))

            runner._run_committed_battle(cycle=1)
            runner._run_committed_battle(cycle=2)

            saved = sorted(Path(directory).glob("*.png"))

        self.assertEqual(2, len(saved))
        # 文件名保持 ASCII（cv2 读写不了中文路径），且带判定结果与轮次。
        fields = [path.stem.split("_") for path in saved]
        self.assertEqual([["win", "r1"], ["win", "r2"]], [f[-2:] for f in fields])

    def test_only_the_latest_frames_are_kept(self):
        """落盘目录在**仓库里**、会被 git 跟踪 —— 只留最近 10 张，别把仓库撑大。"""
        with TemporaryDirectory() as directory:
            target = Path(directory)
            # 伪造一批：命名与真实落盘一致（时间戳开头）⇒ 字典序就是新旧序。
            for index in range(OUTCOME_FRAME_KEEP + 3):
                (target / f"20260925_0000{index:02d}_win_r1.png").touch()

            runner, _runtime, _machine = make_runner([], target)
            runner._prune_outcome_frames()

            kept = sorted(path.name for path in target.glob("*.png"))

        self.assertEqual(OUTCOME_FRAME_KEEP, len(kept))
        # 删的必须是最旧那几张，最新的要留着。
        self.assertNotIn("20260925_000000_win_r1.png", kept)
        self.assertNotIn("20260925_000002_win_r1.png", kept)
        self.assertIn("20260925_000003_win_r1.png", kept)
        self.assertIn("20260925_000012_win_r1.png", kept)

    def test_saving_a_new_frame_throws_away_the_oldest(self):
        win = arena_fixture("result")
        with TemporaryDirectory() as directory:
            target = Path(directory)
            for index in range(OUTCOME_FRAME_KEEP):
                (target / f"20260925_0000{index:02d}_win_r1.png").touch()

            runner, _runtime, _machine = make_runner([win], target)
            runner._run_committed_battle(cycle=99)

            kept = sorted(path.name for path in target.glob("*.png"))

        self.assertEqual(OUTCOME_FRAME_KEEP, len(kept))
        self.assertNotIn("20260925_000000_win_r1.png", kept)

    def test_a_frame_that_cannot_be_deleted_does_not_break_the_run(self):
        """目录是给人看的：用户正开着某张图时删不掉，不该把这一局搞崩。"""
        with TemporaryDirectory() as directory:
            target = Path(directory)
            for index in range(OUTCOME_FRAME_KEEP + 2):
                (target / f"20260925_0000{index:02d}_win_r1.png").touch()
            runner, _runtime, _machine = make_runner([], target)

            with mock.patch.object(Path, "unlink", side_effect=OSError("被占用")):
                runner._prune_outcome_frames()

            self.assertEqual(
                OUTCOME_FRAME_KEEP + 2, len(list(target.glob("*.png")))
            )

    def test_nothing_is_written_when_no_directory_is_injected(self):
        """默认不落盘：测试里绝不能顺手往仓库写图。"""
        win = arena_fixture("result")
        runner, _runtime, _machine = make_runner([win])

        runner._run_committed_battle(cycle=1)

        self.assertEqual(1, runner.outcome_tally[ArenaOutcome.WIN])
        self.assertIsNone(
            runner._save_outcome_frame(win, ArenaOutcome.WIN, cycle=1)
        )

    def test_the_record_is_logged_with_the_frame_path(self):
        win = arena_fixture("result")
        with TemporaryDirectory() as directory:
            runner, runtime, _machine = make_runner([win], Path(directory))

            runner._run_committed_battle(cycle=1)

        logged = [str(call) for call in runtime.log.call_args_list]
        self.assertTrue(
            any("轮次=1 战绩=胜" in line for line in logged),
            logged,
        )


class OutcomeSummaryTests(unittest.TestCase):
    """给通知/控制台用的那一行文案。"""

    def _runner(self) -> ArenaRunner:
        runner, _runtime, _machine = make_runner()
        return runner

    def test_a_clean_record_reads_plainly(self):
        runner = self._runner()
        runner.outcome_tally[ArenaOutcome.WIN] = 2
        runner.outcome_tally[ArenaOutcome.LOSE] = 1

        self.assertEqual("胜 2 / 负 1", runner.outcome_summary())

    def test_unknown_is_called_out_instead_of_being_dropped(self):
        """认不出的局必须留在数字里，否则「胜+负」会对不上「打了几把」。"""
        runner = self._runner()
        runner.outcome_tally[ArenaOutcome.WIN] = 1
        runner.outcome_tally[ArenaOutcome.UNKNOWN] = 2

        self.assertEqual("胜 1 / 负 0（未知 2）", runner.outcome_summary())

    def test_a_fresh_runner_reports_zeroes_not_nothing(self):
        self.assertEqual("胜 0 / 负 0", self._runner().outcome_summary())


class OutcomeNotificationTests(unittest.TestCase):
    """战绩要真的送到用户眼前：通知 + 控制台。"""

    def test_the_notification_lists_the_record_between_cycles_and_elapsed(self):
        with mock.patch.object(main_module, "send_qqbot_c2c") as send:
            main_module._notify_live(
                live=True,
                mode="arena",
                status="completed",
                elapsed_seconds=125,
                completed_cycles=3,
                target_cycles=3,
                outcome_summary="胜 2 / 负 1",
            )

        _title, content = send.call_args.args
        self.assertEqual(
            [
                "模式：竞技场",
                "完成轮数：3/3",
                "战绩：胜 2 / 负 1",
                "耗时：125 秒",
            ],
            content.split("\n"),
        )

    def test_routes_without_a_record_keep_their_old_notification(self):
        with mock.patch.object(main_module, "send_qqbot_c2c") as send:
            main_module._notify_live(
                live=True,
                mode="story",
                status="completed",
                elapsed_seconds=65,
                completed_cycles=2,
                target_cycles=2,
            )

        _title, content = send.call_args.args
        self.assertNotIn("战绩", content)
        self.assertEqual(
            ["模式：主线", "完成轮数：2/2", "耗时：65 秒"],
            content.split("\n"),
        )

    def test_run_result_defaults_to_no_record(self):
        """别的路线拿不到 outcome_summary，默认必须是 None（通知里不显示）。"""
        self.assertIsNone(RunResult(3).outcome_summary)

    def test_the_final_line_shows_the_record(self):
        buffer = io.StringIO()
        with mock.patch.object(
            main_module,
            "run_mode",
            return_value=RunResult(3, outcome_summary="胜 2 / 负 1"),
        ), mock.patch.object(main_module, "send_qqbot_c2c"), redirect_stdout(buffer):
            exit_code = main_module.main(
                ["--mode", "arena", "--max-cycles", "3"]
            )

        self.assertEqual(0, exit_code)
        self.assertIn(
            "完成 模式=arena 轮次=3 战绩=(胜 2 / 负 1)",
            buffer.getvalue(),
        )

    def test_the_final_line_is_unchanged_without_a_record(self):
        buffer = io.StringIO()
        with mock.patch.object(
            main_module, "run_mode", return_value=RunResult(2)
        ), mock.patch.object(main_module, "send_qqbot_c2c"), redirect_stdout(buffer):
            main_module.main(["--mode", "story", "--max-cycles", "2"])

        self.assertIn("完成 模式=story 轮次=2\n", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
