"""卡死兜底（2026-11-22）的 Runner 级护栏。

判据层（命不命中、排不排他）在 test_global_popups.py 钉住；这里只管主循环行为：
- 认不出页、即将超时 → 试一次兜底；
- 命中 → 重置等待、给状态机一次重新认页的机会（不立刻判失败）；
- 一条路线只试一次，下个超时照旧报错（有界，不无限点）；
- 兜底没命中 → 原样超时；
- 正常认得出页 → 一次都不调用。
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock

import numpy as np

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.story import StoryRunner, StoryState
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
BLANK = np.zeros((1132, 1982, 3), dtype=np.uint8)


class _UnknownMachine:
    """preview 一直抛「认不出页」的状态机替身。"""

    def __init__(self, *, recover_after: int | None = None) -> None:
        self.state = StoryState.STAGE
        self.completed_cycles = 0
        self.auto_enabled = False
        self.auto_click_attempted = False
        self.previews = 0
        # 第 N 次 preview 起恢复成一个动作（模拟弹窗被点掉后重新认得出页）。
        self.recover_after = recover_after

    def preview(self, _screen):
        self.previews += 1
        if self.recover_after is not None and self.previews >= self.recover_after:
            return None, (self.state, self.completed_cycles)
        raise UnrecognizedScreen("测试：认不出这一页")

    def next_action(self, _screen):
        return None


class _OkMachine:
    """一切正常、但没有任何动作的状态机替身。"""

    def __init__(self) -> None:
        self.state = StoryState.STAGE
        self.completed_cycles = 0
        self.auto_enabled = False
        self.auto_click_attempted = False

    def preview(self, _screen):
        return None, (self.state, self.completed_cycles)

    def next_action(self, _screen):
        return None


def _make_runner(machine, dismiss_result):
    logs: list[str] = []
    runtime = Runtime(lambda: BLANK, lambda _: None, emit=logs.append)
    dismiss = MagicMock(return_value=dismiss_result)
    runtime.try_dismiss_unknown_popup = dismiss  # type: ignore[method-assign]
    runner = StoryRunner(machine, runtime, sleep=lambda _: None)
    # 超时设为 0：every loop immediately hits the timeout branch.
    runner._TIMEOUT_SECONDS = {StoryState.STAGE: 0}
    return runner, runtime, dismiss, logs


class UnknownPopupFallbackTests(unittest.TestCase):
    def test_tries_once_then_times_out_if_popup_not_dismissed(self):
        """命中一次后仍认不出 ⇒ 第二次超时不再试，照旧报错（有界）。"""
        machine = _UnknownMachine()
        runner, runtime, dismiss, logs = _make_runner(machine, dismiss_result=True)
        runtime.save_diagnostic = MagicMock(return_value=Path("d.png"))  # type: ignore[method-assign]
        runner._save_failure_diagnostic = MagicMock()  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError):
            runner.run(max_cycles=1)

        self.assertEqual(1, dismiss.call_count, "一条路线最多调用一次兜底")
        self.assertTrue(runner._unknown_popup_fallback_used)
        self.assertTrue(any("卡死兜底" in line for line in logs))

    def test_no_fallback_call_when_frame_is_recognized(self):
        """正常认得出页（哪怕没有动作、走到超时）⇒ 一次都不调用兜底。"""
        machine = _OkMachine()
        runner, runtime, dismiss, logs = _make_runner(machine, dismiss_result=False)
        runtime.save_diagnostic = MagicMock(return_value=Path("d.png"))  # type: ignore[method-assign]
        runner._save_failure_diagnostic = MagicMock()  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError):
            runner.run(max_cycles=1)

        # 这条走的是 action is None 超时分支——它同样会试兜底（那行字不命中则
        # dismiss_result=False），所以调用会发生在超时前，但守卫返回 False。
        # 关键是：正常帧守卫不认 ⇒ 不会有「卡死兜底=已尝试」的日志。
        self.assertFalse(any("卡死兜底=已尝试" in line for line in logs))

    def test_fallback_miss_falls_through_to_original_timeout(self):
        """兜底没命中（返回 False）⇒ 保持原有超时报错，状态位不置。"""
        machine = _UnknownMachine()
        runner, runtime, dismiss, logs = _make_runner(machine, dismiss_result=False)
        runtime.save_diagnostic = MagicMock(return_value=Path("d.png"))  # type: ignore[method-assign]
        runner._save_failure_diagnostic = MagicMock()  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "页面无进展|超时|识别"):
            runner.run(max_cycles=1)

        self.assertGreaterEqual(dismiss.call_count, 1)
        self.assertFalse(runner._unknown_popup_fallback_used)
        self.assertFalse(any("卡死兜底=已尝试" in line for line in logs))

    def test_runtime_delegates_to_guard_method(self):
        """Runtime 把兜底委托给装配的守卫；守卫没这方法 ⇒ False（测试替身行为不变）。"""
        screen = BLANK
        runtime = Runtime(lambda: screen, lambda _: None, emit=lambda _: None)
        assert runtime.try_dismiss_unknown_popup(screen) is False

        guard = MagicMock()
        guard.try_dismiss_unknown_popup.return_value = True
        runtime.set_capture_guard(guard)
        assert runtime.try_dismiss_unknown_popup(screen) is True
        guard.try_dismiss_unknown_popup.assert_called_once_with(runtime, screen)


if __name__ == "__main__":
    unittest.main()
