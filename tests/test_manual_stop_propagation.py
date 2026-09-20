"""P 键 / 桌面界面「安全停止」必须真的停下来。

## 这个文件守的是什么

2026-09-17 用户反馈：「为什么我竞技场停止之后，它一直在什么诊断、然后存图片？感觉要爆内存」。
日志里是这个样子（每秒两行，持续到该状态超时）：

```
23:31:20 用户按下 P，正在中断自动化
23:31:20 已保存诊断 ..._manual_stop.png
23:31:21 用户按下 P，正在中断自动化
23:31:21 已保存诊断 ..._manual_stop.png
...（列表页超时 40 秒，战斗监督里最长 900 秒）
```

根因有两条，缺一不可：

1. **``ManualStop`` 是 ``RuntimeError`` 的子类，被各 Runner 的 ``except RuntimeError`` 吞掉了。**
   那条分支本来是兜「页面没认出来」的：``sleep`` 一轮再 ``continue``。主循环回头
   ``capture()`` 又抛一次，于是按轮询频率刷屏 + 每秒写一张全屏诊断图，
   一直磨到当前状态的超时才做恢复。停止请求**完全没有生效**。
2. **``Runtime._stop_if_requested`` 每次都重新报告。** P 键是边沿触发（只报一次），
   但桌面界面的 ``stop.signal`` 文件是**电平**信号（一旦写出就一直在），
   于是每次调用都记日志 + 存图。

所以本文件断言两件事：
- 停止请求从各 Runner 的主循环/空跑路径**原样抛出**（不被包装成运行失败、不被吞掉）；
- 电平停止信号下，日志与 ``manual_stop`` 诊断图**只出现一次**，且一轮 ``sleep`` 都没发生。

测试都用「先把开关关着跑一帧（真实场景里循环已经跑了一会儿），再扳上开关」的方式，
因为 ``_last_screen`` 为空时本来就不该存图。
"""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7.arena import (
    ArenaRunner,
    ArenaStateMachine,
    build_templates,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"

STOP_MESSAGE = "用户按下 P，正在中断自动化"


class _StopSwitch:
    """可随时扳动的停止信号；``latched=True`` 就是桌面界面那种电平信号。"""

    def __init__(self) -> None:
        self.latched = False

    def __call__(self) -> bool:
        return self.latched


class _ProbeMachine:
    """能跑通 ``ModeRunnerBase`` 的最小状态机替身。"""

    def __init__(self, error: Exception) -> None:
        self.state = SimpleNamespace(value="probe")
        self.completed_cycles = 0
        self._error = error

    def next_action(self, _screen):
        raise self._error


class _ProbeRunner(ModeRunnerBase):
    """只为跑通 `ModeRunnerBase` 主循环的最小实现（story/fodder/hero 共用它）。"""

    _MODE_LABEL = "探针"


def _runtime(directory: Path, switch: _StopSwitch, *, dry_run: bool = False) -> Runtime:
    return Runtime(
        lambda: np.full((8, 8, 3), 127, dtype=np.uint8),
        lambda _point: None,
        dry_run=dry_run,
        diagnostic_dir=directory,
        emit=lambda _line: None,
        stop_requested=switch,
    )


def _manual_stop_images(directory: Path) -> list[Path]:
    return list(directory.glob("*_manual_stop.png"))


class LatchedStopReportingTests(unittest.TestCase):
    """电平停止信号只报告一次（P 键那种边沿信号本来就只报一次）。"""

    def test_a_latched_stop_request_reports_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            switch = _StopSwitch()
            seen: list[str] = []
            runtime = Runtime(
                lambda: np.full((8, 8, 3), 127, dtype=np.uint8),
                lambda _point: None,
                diagnostic_dir=root,
                emit=seen.append,
                stop_requested=switch,
            )

            runtime.capture()  # 开关还关着：正常跑一帧，让 _last_screen 有内容
            switch.latched = True
            for _ in range(5):
                with self.assertRaises(ManualStop):
                    runtime.click((10, 10), "must-not-click")

            self.assertEqual(1, len(_manual_stop_images(root)), "电平停止信号不该每次都存图")
            self.assertEqual(
                1,
                sum(STOP_MESSAGE in line for line in seen),
                "电平停止信号不该每次都刷日志",
            )

    def test_reporting_once_does_not_mean_stopping_once(self):
        """「只报告一次」不能退化成「只生效一次」：报告过之后仍然要抛。"""
        with tempfile.TemporaryDirectory() as directory:
            switch = _StopSwitch()
            runtime = _runtime(Path(directory), switch)
            runtime.capture()
            switch.latched = True

            for _ in range(3):
                with self.assertRaises(ManualStop):
                    runtime.capture()


class RunnerManualStopPropagationTests(unittest.TestCase):
    """停止请求不能被 Runner 主循环当成「页面没认出来」吞掉。"""

    def test_the_arena_runner_stops_without_spinning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            switch = _StopSwitch()
            runtime = _runtime(root, switch)
            runtime.capture()  # 关着开关跑一帧，对齐「循环已经跑了一会儿才按停止」
            switch.latched = True
            sleeps: list[float] = []
            runner = ArenaRunner(
                ArenaStateMachine(build_templates(TEMPLATES)),
                runtime,
                sleep=sleeps.append,
            )

            with self.assertRaises(ManualStop):
                runner.run(max_cycles=None)

            self.assertEqual(
                [],
                sleeps,
                "停止请求命中后不该再 sleep 重试 —— 那正是「一直在存图片」的来源",
            )
            self.assertEqual(1, len(_manual_stop_images(root)), "一次停止只该留一张现场图")

    def test_the_shared_runner_base_stops_without_spinning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            switch = _StopSwitch()
            runtime = _runtime(root, switch)
            runtime.capture()
            switch.latched = True
            sleeps: list[float] = []
            runner = _ProbeRunner(MagicMock(), runtime, sleep=sleeps.append)

            with self.assertRaises(ManualStop):
                runner.run(max_cycles=None)

            self.assertEqual([], sleeps)
            self.assertEqual(1, len(_manual_stop_images(root)))

    def test_a_dry_run_stop_is_not_rewrapped_into_a_runtime_failure(self):
        """空跑也要能被停止打断，且不能被「包装成运行失败」那条分支吃掉。"""
        with tempfile.TemporaryDirectory() as directory:
            switch = _StopSwitch()
            runtime = _runtime(Path(directory), switch, dry_run=True)
            runner = _ProbeRunner(_ProbeMachine(ManualStop(STOP_MESSAGE)), runtime)

            with self.assertRaises(ManualStop):
                runner.run()

    def test_a_dry_run_unrecognised_page_is_still_a_runtime_error(self):
        """对照组：真正的「空跑没认出来」仍然按运行失败报错，别把判据一起改宽。"""
        with tempfile.TemporaryDirectory() as directory:
            switch = _StopSwitch()
            runtime = _runtime(Path(directory), switch, dry_run=True)
            runner = _ProbeRunner(_ProbeMachine(RuntimeError("画面未识别")), runtime)

            with self.assertRaises(RuntimeError) as caught:
                runner.run()

            self.assertNotIsInstance(caught.exception, ManualStop)
            self.assertIn("空跑未识别画面", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
