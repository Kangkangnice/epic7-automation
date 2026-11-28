"""竞技场购票「已发出、读回执时截图超时」的收口回归（2026-11-26 三次退回后的追加项）。

## 现场

2026-11-25 第二轮实跑（``runtime_logs/epic7_arena.log:7220``）：购买点击已经发出，
随后 ``adb exec-out screencap`` 超时 20 秒 ⇒ ``subprocess.TimeoutExpired``。

## 旧代码为什么失控

``TimeoutExpired`` 是 ``SubprocessError``，**不是** ``RuntimeError``：

* 不进 ``ArenaRunner.run()`` 的 ``except RuntimeError``（页面超时/未识别那一条）；
* 也不带任何「购买已提交」语义（转场执行器只把 ``irreversible`` 用在**重试**上，
  没用在**读回执**上）；
* 于是一路冒到 ``main.run_mode`` 的通用异常分支 ⇒ ``_try_return_home_after_failure``
  ⇒ **回大厅**。日志只剩 ``异常收尾=回首页失败``，看不出「购买已经发出去一次」。

## 守什么

1. 购买恰好提交 **1 次**；
2. 抛 ``PurchaseReceiptUnclear``，且 ``__cause__`` 是可追溯的 ``TimeoutExpired``；
3. **不点取消、不回大厅、不记资源耗尽、不跑下一条、不巡检**；
4. 现场证据：日志写动作名、原异常、最后一张可用画面。

## 为什么必须让真代码走到超时

直接让替身抛 ``PurchaseReceiptUnclear`` 只能测接收方，覆盖不了「为什么绕过了护栏」。
所以这里用真 ``ArenaRunner`` + 真 ``Runtime`` + 假窗口：截图器在购票点击发生后
**第一次**取图就抛 ``subprocess.TimeoutExpired``。
"""

import contextlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from auto_game_unified import main as main_module
from auto_game_unified.core import matcher
from auto_game_unified.core.runtime import PurchaseReceiptUnclear, Runtime
from auto_game_unified.games.epic7.arena import (
    Action,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.daily_tasks import run_daily_tasks
from auto_game_unified.games.epic7.modes import get_mode


ROOT = Path(__file__).resolve().parents[1]
ARENA_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
TEMPLATES = ROOT / "games" / "epic7" / "templates"

# 购买按钮在友情点报价弹窗上的落点 —— 探针实测 ``next_action`` 给的就是它。
PURCHASE_POINT = (1126, 883)


def canvas(path: Path) -> np.ndarray:
    """读一张帧并按项目口径归一化到基准画布（1982×1132）。"""
    raw = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert raw is not None, f"读不到帧 {path}"
    rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    if rgb.shape[:2] == (1132, 1982):
        return rgb
    assert rgb.shape[:2] == (1080, 1920), f"未知尺寸 {rgb.shape}"
    out = np.zeros((1132, 1982, 3), dtype=np.uint8)
    out[52:, :1920] = rgb
    return out


class _Clock:
    """单调递增的假时钟：``sleep`` 被换掉之后真时钟几乎不动，超时判据要靠它推进。"""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 0.05
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class _ReceiptTimeoutWindow:
    """假窗口：购票点击发出之后，**第一次**取图就抛截图超时。

    点击之前照常回放报价弹窗帧（识别要连续两帧稳定）；点击之后第一拍立刻超时 ——
    这正是 2026-11-25 实跑的顺序：点击成功返回 → 读回执 → adb 超时。

    ⚠️ 这里**不抛** ``PurchaseReceiptUnclear``：那只能测「接收方」，
    覆盖不了「读帧边界没有把截图超时当回执未明」这个真原因。
    """

    _CMD = ["adb", "-s", "emulator-5554", "exec-out", "screencap", "-p"]
    TIMEOUT = 20.0

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame
        self.clicks: list[tuple[int, int]] = []
        self.captures = 0
        self.timed_out = False

    def capture(self) -> np.ndarray:
        self.captures += 1
        if self.clicks:
            self.timed_out = True
            raise subprocess.TimeoutExpired(self._CMD, self.TIMEOUT)
        return self._frame

    def click(self, point: tuple[int, int]) -> None:
        self.clicks.append(point)


class _PassThroughGuard:
    """直通守卫：这一层与购票回执无关，且它对夹具帧的任何动作都会污染点击计数。"""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __call__(self, runtime, screen):
        return screen, False


@contextlib.contextmanager
def _window_layer_replaced(*, runtime: Runtime, home_return: mock.MagicMock):
    """只替换窗口层装配，``run_mode`` 的业务代码全用真的。"""
    with (
        mock.patch.object(main_module, "_build_runtime", return_value=runtime),
        mock.patch.object(main_module, "Epic7GlobalPopupGuard", _PassThroughGuard),
        mock.patch.object(
            main_module, "install_pc_only_popups", lambda guard, _dir: guard
        ),
        mock.patch.object(main_module, "Epic7Navigator"),
        mock.patch.object(main_module, "HomeReturn", return_value=home_return),
        mock.patch.object(main_module, "_enter_mode"),
    ):
        yield


class PurchaseReceiptCaptureTimeoutTests(unittest.TestCase):
    """截图超时不得被当成「页面超时」继续跑，也不得回大厅抹掉对账现场。"""

    def setUp(self) -> None:
        self._backend = matcher.ACTIVE_BACKEND

    def tearDown(self) -> None:
        matcher.set_active_backend(self._backend)

    def _scene(self):
        popup = canvas(ARENA_FIXTURES / "friendship_ticket_offer_live_20260826.png")
        window = _ReceiptTimeoutWindow(popup)
        logs: list[str] = []
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runtime = Runtime(
            window.capture,
            window.click,
            emit=logs.append,
            diagnostic_dir=Path(directory.name),
            monotonic=_Clock(),
        )
        return window, runtime, logs, Path(directory.name)

    def test_single_route_keeps_scene_after_receipt_capture_timeout(self):
        """经 ``main.run_mode``：购买 1 次、抛对账异常、不回大厅、不留取消动作。"""
        window, runtime, logs, diagnostic_dir = self._scene()
        home_return = mock.MagicMock()

        with self.assertRaises(PurchaseReceiptUnclear) as caught:
            with _window_layer_replaced(runtime=runtime, home_return=home_return):
                main_module.run_mode(
                    spec=get_mode("arena"),
                    dry_run=False,
                    max_cycles=1,
                    start_state=ArenaState.BATTLE.value,
                    window_backend="emulator",
                )

        error = caught.exception
        self.assertIsInstance(
            error.__cause__,
            subprocess.TimeoutExpired,
            f"必须用异常链保留原始截图超时，实际 cause={error.__cause__!r}",
        )
        self.assertTrue(window.timed_out, "假窗口根本没超时 —— 用例没走到读回执那一步")
        self.assertEqual(
            [PURCHASE_POINT],
            window.clicks,
            f"购买只能提交一次、且不许点取消：{window.clicks}",
        )
        home_return.assert_not_called()

        joined = "\n".join(logs)
        self.assertIn("purchase-friendship-ticket", joined, joined)
        self.assertIn("TimeoutExpired", joined, joined)
        self.assertIn("对账", joined, joined)
        self.assertNotIn("dismiss-purchase", joined, joined)
        self.assertNotIn("资源耗尽", joined, joined)

        shots = sorted(path.name for path in diagnostic_dir.glob("*.png"))
        self.assertTrue(
            any("receipt_timeout" in name for name in shots),
            f"超时现场必须留一张可用证据：{shots}",
        )

    def test_daily_batch_stops_and_keeps_scene_after_receipt_capture_timeout(self):
        """经每日编排：记 failed、停整轮、不段间回大厅、不跑下一条、不巡检。

        ⚠️ 两条注入都是为了让用例**对准现场**，不改变被测行为：

        * ``start_state`` 固定到 ``battle``（编排层默认从列表页起）—— 现场就是
          「人停在战斗前的购买弹窗上、点击购买之后读回执」，从列表页起是另一条流程；
        * 第二条路线用 ``story_star``：它是 ``PC_ONLY_ROUTES``，模拟器口径下编排层
          直接记 ``not_supported`` 并跳过、**不碰游戏**，这样「有没有跑下一条」
          能被断言看见（旧代码会追加一条 ``story_star``），又不用真跑一条路线。
        """
        window, runtime, logs, _directory = self._scene()
        home_return = mock.MagicMock()
        inspected: list[bool] = []

        def arena_from_purchase_popup(**kwargs):
            """把起点定在购票弹窗那一页，其余全部走真的 ``main.run_mode``。"""
            kwargs["start_state"] = ArenaState.BATTLE.value
            return main_module.run_mode(**kwargs)

        with _window_layer_replaced(runtime=runtime, home_return=home_return):
            report = run_daily_tasks(
                selected=["arena", "story_star"],
                cycles_override={"arena": 1},
                dry_run=False,
                run_mode=arena_from_purchase_popup,
                inspect=lambda: inspected.append(True),
            )

        self.assertEqual(
            ["arena"],
            [outcome.mode for outcome in report.outcomes],
            f"回执未明必须停整轮，不许跑下一条：{[o.mode for o in report.outcomes]}",
        )
        outcome = report.outcomes[0]
        self.assertEqual("failed", outcome.status)
        self.assertIn("PurchaseReceiptUnclear", outcome.detail, outcome.detail)
        self.assertIn("对账", outcome.detail, outcome.detail)
        self.assertFalse(report.stopped_by_user, "这不是用户取消")
        self.assertIn("对账现场", report.aborted_reason, report.aborted_reason)
        self.assertEqual([], inspected, "收尾巡检会移动现场，必须跳过")
        home_return.assert_not_called()
        self.assertEqual([PURCHASE_POINT], window.clicks, window.clicks)


class NormalReceiptStillProceedsTests(unittest.TestCase):
    """对照组：回执正常（弹窗消失 → 队伍页连续两帧）时，转场照旧 commit 前进。"""

    def setUp(self) -> None:
        self._backend = matcher.ACTIVE_BACKEND
        matcher.set_active_backend("emulator")

    def tearDown(self) -> None:
        matcher.set_active_backend(self._backend)

    def test_normal_receipt_commits_and_does_not_raise(self):
        popup = canvas(ARENA_FIXTURES / "friendship_ticket_offer_live_20260826.png")
        team = canvas(ARENA_FIXTURES / "team.png")
        frames = [popup, team, team]
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        clock = _Clock()

        def capture() -> np.ndarray:
            return frames.pop(0) if len(frames) > 1 else frames[0]

        runtime = Runtime(
            capture,
            clicks.append,
            emit=logs.append,
            monotonic=clock,
        )
        machine = ArenaStateMachine(
            build_templates(TEMPLATES), initial_state=ArenaState.BATTLE
        )
        runner = ArenaRunner(machine, runtime, sleep=clock.advance)

        action = Action(
            name="purchase-friendship-ticket",
            point=PURCHASE_POINT,
            source_state=ArenaState.BATTLE,
            target_states=(ArenaState.TEAM,),
            irreversible=True,
        )

        runner._current_action = action
        runner._execute_transition(action)

        self.assertEqual(ArenaState.TEAM, machine.state, "目标页两帧稳定后必须 commit")
        self.assertEqual([PURCHASE_POINT], clicks, clicks)
        self.assertIn("转场确认", "\n".join(logs), logs)


if __name__ == "__main__":
    unittest.main()
