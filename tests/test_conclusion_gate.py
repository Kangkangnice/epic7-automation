"""「结论门槛」护栏：**不许拿一帧下结论**。

背景（2026-09-25 实跑，用户当场抓到两条）：

- 世界首领战：``next_action`` 里「今天没场次了」的异常从 ``preview()`` **直接穿到
  主循环**，早于两帧稳定确认 ⇒ 一帧就宣布整条路线收工，宝箱还没看就说打完了；
- 通用：``UnrecognizedScreen`` 同样一帧穿出去 ⇒ 一帧没认出画面就去点屏幕中间。

动作要连续两帧一致才敢点，这条规矩早就有了；结论却一直只要一帧 —— 门只掩了一半，
而真正会终止路线的恰恰是这些结论。本文件守三件事：

① ``ConclusionGate`` 本身的判定（几帧放行、换结论要不要重新数、停止键豁免）；
② **跑真主循环**验证：单帧收工 / 单帧认不出画面都不许生效；
③ 路线准入：每条路线要么走基类门槛、要么登记自己靠什么达标，漏了报错
   （``modes._assert_conclusion_gate_declared``），并且这条自查本身也有测试。

规矩的定义与填写方式见 ``docs/TRANSITION_CONTRACTS.md``「结论门槛（全局强制）」。
"""

import contextlib
import unittest
import unittest.mock

import numpy as np

from auto_game_unified.core.runtime import ManualStop, ResourceExhausted
from auto_game_unified.core.supervisor import ConclusionGate
from auto_game_unified.games.epic7 import modes
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState, TicketExhausted
from auto_game_unified.games.epic7.expedition import (
    ExpeditionRunner,
    ExpeditionState,
    PostersExhausted,
)
from auto_game_unified.games.epic7.runner_base import (
    NOT_STABLE,
    ConclusionGateBypassed,
    ModeRunnerBase,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

FAKE_SCREEN = np.zeros((8, 8, 3), dtype=np.uint8)


class _LoopStop(BaseException):
    """让主循环停下来的哨兵。

    故意不继承 ``RuntimeError`` —— 主循环里有 ``except RuntimeError`` 的
    「页面识别超时」分支，继承了会被它吞掉（这条注释抄自
    ``test_transition_contracts.py``，同一个坑）。
    """


class _FakeExhausted(ResourceExhausted):
    stop_label = "假的没本钱了"


class _OtherExhausted(ResourceExhausted):
    """与上面同类型、但缺的东西不一样 ⇒ 签名不同，不该互相背书。"""

    stop_label = "另一种没本钱了"


class FakeRuntime:
    diagnostic_dir = None
    dry_run = False

    def __init__(self) -> None:
        self.clicks: list = []
        self.messages: list[str] = []
        self.now_value = 0.0

    def now(self) -> float:
        return self.now_value

    def capture(self):
        return FAKE_SCREEN

    def click(self, point, name) -> None:
        self.clicks.append((point, name))

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label, screen):
        return label


class ScriptedMachine:
    """按脚本应答 ``preview``：脚本项可以是异常（抛出）或动作（返回）。

    ``next_action`` 一旦被调用就停下主循环 —— **走到它说明结论没被采信**，
    正好是「单帧不下结论」想要的效果；若结论被提前采信，主循环根本到不了这里。
    """

    def __init__(self, script, *, state="fake.page") -> None:
        self._script = list(script)
        self.state = state
        self.completed_cycles = 0

    def preview(self, screen):
        if not self._script:
            raise _LoopStop
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item, None

    def next_action(self, screen):
        raise _LoopStop


class _GateRunner(ModeRunnerBase):
    """最小可用的基类 Runner：只为把主循环跑起来，不引入任何路线判据。"""

    _MODE_LABEL = "门槛测试"

    def _timeout_for(self, state) -> float:
        return 1e9


class _ResubmitsRejectedConclusion(ModeRunnerBase):
    """复现审查 C 的反例：基类第一帧拒绝后，子类把 NOT_STABLE 换成结论再抛。"""

    _MODE_LABEL = "假路线"

    def _timeout_for(self, state) -> float:
        return 1e9

    def _stable_next_action(self, screen, stable):
        result = super()._stable_next_action(screen, stable)
        if result is NOT_STABLE:
            raise _FakeExhausted()
        return result


class _FailsBeforeCallingSuper(ModeRunnerBase):
    """复现审查 C 的第二个反例：截图失败发生在进基类之前。"""

    _MODE_LABEL = "假路线"

    def _timeout_for(self, state) -> float:
        return 1e9

    def _stable_next_action(self, screen, stable):
        raise OSError("截图通道挂了")


def _run_base(script) -> tuple[ModeRunnerBase, FakeRuntime]:
    runtime = FakeRuntime()
    runner = _GateRunner(
        ScriptedMachine(script), runtime, sleep=lambda _: None, poll_seconds=0.0
    )
    try:
        runner.run(max_cycles=1)
    except _LoopStop:
        pass
    return runner, runtime


class ConclusionGateTests(unittest.TestCase):
    """门槛本体：几帧才放行。"""

    def test_single_frame_conclusion_is_not_admitted(self):
        gate = ConclusionGate()
        self.assertFalse(gate.admit(_FakeExhausted()), "一帧不许下结论")

    def test_same_conclusion_twice_is_admitted(self):
        gate = ConclusionGate()
        gate.admit(_FakeExhausted())
        self.assertTrue(gate.admit(_FakeExhausted()))

    def test_a_different_conclusion_restarts_the_count(self):
        """换了结论还接着数 ⇒ 等于「两个不同结论各看一帧」就算数了。"""

        gate = ConclusionGate()
        gate.admit(_FakeExhausted())
        self.assertFalse(gate.admit(_OtherExhausted()))
        self.assertTrue(gate.admit(_OtherExhausted()))

    def test_manual_stop_is_admitted_immediately(self):
        """停止键是用户按的，不是程序下的结论 —— 等两帧会让停止变迟钝。"""

        gate = ConclusionGate()
        self.assertTrue(gate.admit(ManualStop()))

    def test_reset_clears_the_count(self):
        gate = ConclusionGate()
        gate.admit(_FakeExhausted())
        gate.reset()
        self.assertFalse(gate.admit(_FakeExhausted()))


class BaseLoopConclusionTests(unittest.TestCase):
    """走基类主循环的 7 条路线：结论必须连看两帧。"""

    def test_single_frame_resource_exhaustion_does_not_close_the_route(self):
        runner, runtime = _run_base([_FakeExhausted(), _LoopStop()])
        self.assertFalse(
            runner.resource_exhausted,
            "只看到一帧「没本钱了」就收工 —— 这正是 2026-09-25 的宝箱事故",
        )
        self.assertTrue(
            any("结论待确认" in line for line in runtime.messages),
            "被门槛拦下的结论必须写进日志，不许哑判",
        )

    def test_two_frames_of_resource_exhaustion_close_the_route(self):
        runner, _ = _run_base([_FakeExhausted(), _FakeExhausted()])
        self.assertTrue(runner.resource_exhausted, "连看两帧才允许收工")

    def test_conclusions_from_different_frames_do_not_add_up(self):
        """第一帧缺这个、第二帧缺那个 —— 那是两次误判，不是一次确认。"""

        runner, _ = _run_base(
            [_FakeExhausted(), _OtherExhausted(), _LoopStop()]
        )
        self.assertFalse(runner.resource_exhausted)

    def test_single_frame_unrecognized_screen_does_not_wake_click(self):
        """用户原话「眼睛瞎了一直点中间」：一帧没认出来不许去点屏幕中间。"""

        _, runtime = _run_base([UnrecognizedScreen("假页面"), _LoopStop()])
        self.assertEqual(
            [], runtime.clicks, "只认不出一帧就动手，唤醒点击必须先过门槛"
        )

    def test_manual_stop_still_stops_immediately(self):
        runtime = FakeRuntime()
        runner = _GateRunner(
            ScriptedMachine([ManualStop()]),
            runtime,
            sleep=lambda _: None,
            poll_seconds=0.0,
        )
        with self.assertRaises(ManualStop):
            runner.run(max_cycles=1)

    def test_a_rejected_first_frame_cannot_be_resubmitted_as_a_conclusion(self):
        """审查 C 反例：基类返回 NOT_STABLE 后，子类把它改成「资源耗尽」。

        改前：主循环先记「需连续两帧」，紧接着就在同一帧按资源耗尽收工 ——
        「进过基类」被当成了「结论过了门槛」。
        """

        runner = _ResubmitsRejectedConclusion(
            ScriptedMachine([_FakeExhausted(), _LoopStop()]),
            FakeRuntime(),
            sleep=lambda _: None,
            poll_seconds=0.0,
        )

        with self.assertRaisesRegex(ConclusionGateBypassed, "基类没有采信这个结论"):
            runner.run(max_cycles=1)

        self.assertFalse(
            runner.resource_exhausted,
            "第一帧被拒的结论不许在同一帧变成已确认结论",
        )

    def test_a_real_failure_before_the_gate_keeps_its_cause(self):
        """审查 C 反例：截图失败发生在进基类之前，不许改写成「没调 super」。"""

        runner = _FailsBeforeCallingSuper(
            ScriptedMachine([]),
            FakeRuntime(),
            sleep=lambda _: None,
            poll_seconds=0.0,
        )

        with self.assertRaises(OSError) as captured:
            runner.run(max_cycles=1)

        self.assertIn("截图通道挂了", str(captured.exception))


class ArenaLoopConclusionTests(unittest.TestCase):
    """竞技场自带独立主循环，门槛必须自己接上。"""

    def _run(self, script) -> tuple[ArenaRunner, FakeRuntime]:
        runtime = FakeRuntime()
        machine = ScriptedMachine(script, state=ArenaState.LIST)
        machine.resumed_from = None
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        try:
            runner.run(1)
        except _LoopStop:
            pass
        return runner, runtime

    def test_single_frame_ticket_exhaustion_does_not_close_the_route(self):
        runner, _ = self._run([TicketExhausted(), _LoopStop()])
        self.assertFalse(runner.resource_exhausted, "一帧不许宣布票没了")

    def test_two_frames_of_ticket_exhaustion_close_the_route(self):
        runner, _ = self._run([TicketExhausted(), TicketExhausted()])
        self.assertTrue(runner.resource_exhausted)


class ExpeditionLoopConclusionTests(unittest.TestCase):
    """远征同样是独立主循环。"""

    def _run(self, script) -> tuple[ExpeditionRunner, FakeRuntime]:
        runtime = FakeRuntime()
        machine = ScriptedMachine(script, state=ExpeditionState.HOME)
        runner = ExpeditionRunner(machine, runtime, sleep=lambda _: None)
        try:
            runner.run(1)
        except _LoopStop:
            pass
        return runner, runtime

    def test_single_frame_stamina_exhaustion_does_not_close_the_route(self):
        runner, _ = self._run([PostersExhausted(), _LoopStop()])
        self.assertFalse(runner.resource_exhausted, "一帧不许宣布传单没了")

    def test_two_frames_of_stamina_exhaustion_close_the_route(self):
        runner, _ = self._run([PostersExhausted(), PostersExhausted()])
        self.assertTrue(runner.resource_exhausted)


class ConclusionGateRegistryTests(unittest.TestCase):
    """路线准入：每条路线都得说清楚自己靠什么保证「不一帧下结论」。

    ⚠️ 为什么不能只靠加载期自查：自查可以被一次「顺手删掉那个调用」抹掉，
    而它抹掉之后**没有任何症状**（路线照跑）。测试是第二道。
    """

    FAKE = "fake_route_for_gate_test"

    @contextlib.contextmanager
    def _fake_route(self, runner_type):
        spec = modes.ModeSpec(
            name=self.FAKE,
            label="假路线",
            default_state="x",
            states=frozenset({"x"}),
            build_machine=lambda *_a, **_k: None,
            runner_type=runner_type,
        )
        modes.MODE_SPECS[self.FAKE] = spec
        try:
            yield spec
        finally:
            modes.MODE_SPECS.pop(self.FAKE, None)

    def test_every_current_route_passes_the_check(self):
        modes._assert_conclusion_gate_declared()

    def test_the_check_refuses_a_route_that_says_nothing(self):
        class _Plain:
            """既不是基类 Runner，也没登记 —— 谁也不知道它几帧下结论。"""

        with self._fake_route(_Plain):
            with self.assertRaisesRegex(RuntimeError, "CONCLUSION_GATE_DECLARATION"):
                modes._assert_conclusion_gate_declared()

    def test_a_route_that_bypasses_the_base_gate_fails_when_it_runs(self):
        """注册期不再猜源码；绕开基类的路线在**跑起来**的第一帧失败关闭。"""

        class _Overriding(ModeRunnerBase):
            """继承了基类却重写判定入口 —— 门槛被自己绕过去了。"""

            _MODE_LABEL = "假路线"

            def _timeout_for(self, state) -> float:
                return 1e9

            def _stable_next_action(self, screen, stable):
                return self.machine.next_action(screen)

        with self._fake_route(_Overriding):
            modes._assert_conclusion_gate_declared()  # 注册可以通过

        runner = _Overriding(
            ScriptedMachine([]), FakeRuntime(), sleep=lambda _: None, poll_seconds=0.0
        )
        with self.assertRaisesRegex(RuntimeError, "结论门槛被绕过"):
            runner.run(max_cycles=1)

    def test_a_comment_that_looks_like_delegation_does_not_count(self):
        """方法体里写一句 ``super()._stable_next_action`` 的注释，不算委托。

        审查 C：旧判据用 ``inspect.getsource`` 找这串文字 —— 注释能骗过它，
        真正委托的写法反而可能被误判。现在只看运行时有没有真的进基类。
        """

        class _CommentOnly(ModeRunnerBase):
            """只把委托写进注释，实际绕开基类门槛。"""

            _MODE_LABEL = "假路线"

            def _stable_next_action(self, screen, stable):
                # super()._stable_next_action(screen, stable)
                return self.machine.next_action(screen)

        with self._fake_route(_CommentOnly):
            modes._assert_conclusion_gate_declared()  # 注册不再读方法体

        runner = _CommentOnly(
            ScriptedMachine([]), FakeRuntime(), sleep=lambda _: None, poll_seconds=0.0
        )
        with self.assertRaisesRegex(RuntimeError, "结论门槛被绕过"):
            runner.run(max_cycles=1)

    def test_registry_loads_without_source_text(self):
        """拿不到源码文本时注册表仍可加载（判据不依赖 inspect）。"""

        def unavailable(*_args, **_kwargs):
            raise OSError("source not available")

        with unittest.mock.patch("inspect.getsource", unavailable):
            modes._assert_conclusion_gate_declared()

    def test_an_override_that_skips_super_fails_closed_at_runtime(self):
        """真实主循环里绕开基类 ⇒ 当场失败关闭，不带着未过门槛的结论继续跑。"""

        class _Bypass(ModeRunnerBase):
            _MODE_LABEL = "假路线"

            def _timeout_for(self, state) -> float:
                return 1e9

            def _stable_next_action(self, screen, stable):
                return self.machine.next_action(screen)

        runner = _Bypass(
            ScriptedMachine([]), FakeRuntime(), sleep=lambda _: None, poll_seconds=0.0
        )
        with self.assertRaisesRegex(RuntimeError, "结论门槛被绕过"):
            runner.run(max_cycles=1)

    def test_a_runner_that_rewrites_run_is_not_auto_protected(self):
        """审查 C：自己写 ``run()`` 的路线不能仅凭继承被认定「已保护」。

        继承只证明「类关系上属于基类」，不证明那次运行真的走过基类循环。
        重写 ``run()`` 的路线必须在表里写明自己的保证（现有 7 条都写了
        「只做前置/收尾，主循环转调 ``super().run()``」）。
        """

        class _OwnLoop(ModeRunnerBase):
            _MODE_LABEL = "假路线"

            def run(self, max_cycles=None) -> int:
                return 0

        with self._fake_route(_OwnLoop):
            with self.assertRaisesRegex(RuntimeError, "CONCLUSION_GATE_DECLARATION"):
                modes._assert_conclusion_gate_declared()
            modes.CONCLUSION_GATE_DECLARATION[self.FAKE] = "假理由：run 自己下结论"
            try:
                modes._assert_conclusion_gate_declared()
            finally:
                modes.CONCLUSION_GATE_DECLARATION.pop(self.FAKE, None)

    def test_the_check_refuses_saying_it_twice(self):
        with self._fake_route(_GateRunner):
            modes.CONCLUSION_GATE_DECLARATION[self.FAKE] = "假理由"
            try:
                with self.assertRaisesRegex(RuntimeError, "两边只能写一边"):
                    modes._assert_conclusion_gate_declared()
            finally:
                modes.CONCLUSION_GATE_DECLARATION.pop(self.FAKE, None)


if __name__ == "__main__":
    unittest.main()
