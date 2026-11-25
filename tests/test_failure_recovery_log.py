"""异常收尾日志的原始异常字段。

回归目标：异常已经把游戏带回大厅时，运行日志仍要能按首个故障归类。
只加观测字段，不改回家动作、退出码与异常传播。
"""

import unittest
from unittest.mock import Mock

from auto_game_unified import main as main_module


class _LogCollector:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, line: str) -> None:
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class FailureRecoveryLogTests(unittest.TestCase):
    def test_success_branch_records_the_original_exception(self):
        runtime = _LogCollector()
        cause = RuntimeError("首个故障：列表锚点丢失")

        main_module._try_return_home_after_failure(
            Mock(), runtime, mode="arena", cause=cause
        )

        self.assertIn("异常收尾=已回到首页", runtime.text)
        self.assertIn("原异常类型=RuntimeError", runtime.text)
        self.assertIn("原异常摘要=首个故障：列表锚点丢失", runtime.text)

    def test_home_failure_branch_records_both_the_home_error_and_the_cause(self):
        runtime = _LogCollector()
        home_return = Mock(side_effect=OSError("回首页超时"))
        cause = RuntimeError("首个故障：结算锚点认不出")

        main_module._try_return_home_after_failure(
            home_return, runtime, mode="arena", cause=cause
        )

        self.assertIn("回首页失败", runtime.text)
        self.assertIn("原因=OSError: 回首页超时", runtime.text)
        self.assertIn("原异常类型=RuntimeError", runtime.text)
        self.assertIn("原异常摘要=首个故障：结算锚点认不出", runtime.text)

    def test_manual_stop_branch_records_the_original_exception(self):
        runtime = _LogCollector()
        cause = RuntimeError("首个故障：周奖励红点未消失")

        main_module._try_return_home_after_failure(
            Mock(side_effect=main_module.ManualStop()),
            runtime,
            mode="arena",
            cause=cause,
        )

        self.assertIn("回首页被手动停止", runtime.text)
        self.assertIn("原异常类型=RuntimeError", runtime.text)
        self.assertIn("原异常摘要=首个故障：周奖励红点未消失", runtime.text)

    def test_missing_cause_keeps_the_legacy_log(self):
        runtime = _LogCollector()

        main_module._try_return_home_after_failure(Mock(), runtime, mode="arena")

        self.assertIn("异常收尾=已回到首页", runtime.text)
        self.assertNotIn("原异常类型=", runtime.text)

    def test_multiline_cause_is_recorded_as_one_summary_line(self):
        runtime = _LogCollector()
        cause = RuntimeError("第一行\n第二行")

        main_module._try_return_home_after_failure(
            Mock(), runtime, mode="arena", cause=cause
        )

        self.assertIn("原异常摘要=第一行 第二行", runtime.text)
        self.assertEqual(1, len(runtime.lines))


if __name__ == "__main__":
    unittest.main()
