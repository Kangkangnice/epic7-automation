"""「收尾回首页」的契约测试（arena / world_boss / knights_donation）。

用户 2026-09-25 的诉求：一条路线跑完之后，游戏要**自己退回首页**，
这样后面串多个任务时才能衔接得上（此前 9 条路线**一条都没有**这个动作，
跑完就停在当时那一页）。

守四件事：

1. **三条路线真的会调用收尾钩子** —— 用真 Runner + 可控状态机跑完，断言钩子被调。
   只断言「main 里装了钩子」是不够的：装了没人调，静态看一切正常，
   只有跑一遍才现形（`_ResumeWatch.asked` 那个接线检查就是同一个道理）。
2. **三类退出各自接不接** —— 正常完成、资源耗尽（退出码 2）要接；
   手动停（130）与异常（1）**不接**。后者是安全的：跑到一半挂了还去按 Back，
   可能把已承诺的战斗弄丢。
3. **收尾失败绝不改退出码** —— 任务本身已经成功了，不能因为「没走回家」就报失败。
4. **竞技场的接力开局不该被送回家** —— 人本来就停在半路，我们只补完这一局。

⚠️ 这三条路线的退出路径**形状完全不同**（arena 是自带独立主循环的裸定义，
另外两条走 `ModeRunnerBase.run`），所以下面分成三段写，别照抄。
"""

import unittest
from unittest.mock import MagicMock

import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime, StaminaExhausted
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState
from auto_game_unified.games.epic7.knights_donation import (
    KnightsDonationRunner,
    KnightsDonationState,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.world_boss import WorldBossRunner, WorldBossState


_BLANK_CACHE: np.ndarray | None = None


def blank() -> np.ndarray:
    """一帧全黑画面。

    ⚠️ **全局复用同一块内存**：本机内存紧张，每个测试各分配一张 1982×1132×3
    （6.4 MB）会在跑整套时偶发 ``MemoryError``（本仓库已知的环境 artifact）。
    这些测试只拿它当「一帧画面」，从来不改它，共享是安全的。
    """
    global _BLANK_CACHE
    if _BLANK_CACHE is None:
        _BLANK_CACHE = np.zeros((1132, 1982, 3), dtype=np.uint8)
    return _BLANK_CACHE


class _Hooked:
    """把「收尾钩子」装进 runner 并记下调用次数。

    两条路线的钩子**不在同一个地方**：基类路线读类属性 ``_finish_home``，
    竞技场读实例属性 ``finish_home``（它是裸定义、连这个属性都没有）。
    这里两个都设，与 ``main._install_finish_home`` 保持一致。
    """

    def __init__(self, failure: str | None = None) -> None:
        self.calls = 0
        self.failure = failure

    def install(self, runner) -> None:
        def hook() -> str | None:
            self.calls += 1
            return self.failure

        runner._finish_home = hook
        if hasattr(runner, "finish_home"):
            runner.finish_home = hook


class _OnceThenExhaustedMachine:
    """跑完一轮就报「没本钱了」的状态机替身（走基类主循环的路线用）。

    形状照着 ``ModeRunnerBase`` 的鸭子类型造：主循环只需要 ``state`` /
    ``completed_cycles`` / ``preview`` / ``next_action``。
    """

    def __init__(self, state, cycles: int = 0) -> None:
        self.state = state
        self.completed_cycles = cycles
        self._confirmed_page = ""
        self.preview_calls = 0

    def preview(self, screen):
        self.preview_calls += 1
        if self.preview_calls > 1:
            # 第二轮观察时「没本钱了」—— 这是**正常业务退出**（退出码 2），
            # 按设计要收尾回首页。
            raise StaminaExhausted("测试：叶子用光了")
        return None, (self.state, self.completed_cycles)

    def next_action(self, screen):
        return None


class BaseRunnerFinishHomeTests(unittest.TestCase):
    """走 ``ModeRunnerBase`` 的两条路线（world_boss / knights_donation）。"""

    def _run_to_resource_end(self, runner_type, state):
        hook = _Hooked()
        machine = _OnceThenExhaustedMachine(state)
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = runner_type(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        completed = runner.run(max_cycles=3)

        return runner, hook, completed

    def test_world_boss_returns_home_when_it_runs_out_of_attempts(self):
        runner, hook, completed = self._run_to_resource_end(
            WorldBossRunner, WorldBossState.HOME
        )

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(1, hook.calls, "资源耗尽退出没收尾回首页")

    def test_knights_donation_returns_home_when_it_runs_out_of_attempts(self):
        runner, hook, completed = self._run_to_resource_end(
            KnightsDonationRunner, KnightsDonationState.GUILD_HOME
        )

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(1, hook.calls, "资源耗尽退出没收尾回首页")

    def test_finishing_the_planned_cycles_returns_home(self):
        """跑满 ``max_cycles`` 走的是 ``while`` 条件自然结束那条出口。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.state = WorldBossState.HOME
        machine.completed_cycles = 3
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = WorldBossRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        completed = runner.run(max_cycles=3)

        self.assertEqual(3, completed)
        self.assertEqual(1, hook.calls, "跑满轮次退出没收尾回首页")

    def test_a_manual_stop_is_not_wrapped_up(self):
        """用户按 P 喊停 ⇒ **不**动游戏（退出码 130 那条路）。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.state = WorldBossState.HOME
        machine.completed_cycles = 0
        machine.preview.side_effect = ManualStop("用户按下 P")
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = WorldBossRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        with self.assertRaises(ManualStop):
            runner.run(max_cycles=3)

        self.assertEqual(0, hook.calls, "手动停不该去动游戏")

    def test_a_crash_is_not_wrapped_up(self):
        """跑到一半挂了 ⇒ **不**动游戏（退出码 1 那条路，硬按 Back 有丢局风险）。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.state = WorldBossState.HOME
        machine.completed_cycles = 0
        machine.preview.side_effect = RuntimeError("页面没认出来")
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = WorldBossRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        with self.assertRaises(RuntimeError):
            runner.run(max_cycles=3)

        self.assertEqual(0, hook.calls, "异常退出不该去动游戏")

    def test_a_failed_wrap_up_never_changes_the_result(self):
        """收尾失败 ⇒ 只记日志，退出码与轮次**一个都不变**。"""
        hook = _Hooked(failure="受控返回8次后仍未回到大厅")
        machine = MagicMock()
        machine.state = WorldBossState.HOME
        machine.completed_cycles = 3
        logs: list[str] = []
        runtime = Runtime(blank, lambda _: None, emit=logs.append)
        runner = WorldBossRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        completed = runner.run(max_cycles=3)

        self.assertEqual(3, completed, "收尾失败不该改轮次")
        self.assertFalse(runner.resource_exhausted, "收尾失败不该把结论改成资源耗尽")
        self.assertEqual(1, hook.calls)
        self.assertTrue(
            any("收尾=回首页失败" in line for line in logs),
            f"收尾失败必须在日志里看得见：{logs}",
        )


class ArenaFinishHomeTests(unittest.TestCase):
    """竞技场自带独立主循环（``ArenaRunner`` 是裸定义），收尾点得自己接。

    ⚠️ **接力开局照样收尾**：接力走的还是同一个 ``run()``，补完那一局后照样回首页。
    这是设计决定而不是巧合 —— 否则接力启动会留下唯一一个「做完不回首页」的口子，
    串任务时正好卡在那儿（见 ``ArenaRunner._close_out`` 的注释）。
    """

    def _runner(self, *, cycles: int, max_cycles: int):
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = cycles
        machine.resumed_from = None
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)
        return runner, hook

    def test_finishing_the_planned_cycles_returns_home(self):
        """达标那一刻的出口（``max_cycles is not None and 达标``）在循环**顶部**。"""
        runner, hook = self._runner(cycles=2, max_cycles=2)

        completed = runner.run(max_cycles=2)

        self.assertEqual(2, completed)
        self.assertEqual(1, hook.calls, "竞技场跑满轮次没收尾回首页")

    def test_running_out_of_tickets_returns_home(self):
        """买不到票 ⇒ 资源耗尽退出，同样要回家。

        ⚠️ 这个出口停在**购买弹窗那一页**上，正是「下一个任务衔接不上」的典型现场。
        """
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 1
        machine.resumed_from = None
        machine.preview.side_effect = __import__(
            "auto_game_unified.games.epic7.arena", fromlist=["TicketExhausted"]
        ).TicketExhausted("旗帜不够且今日不可购买")
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        completed = runner.run(max_cycles=5)

        self.assertEqual(1, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(1, hook.calls, "竞技场资源耗尽没收尾回首页")

    def test_a_manual_stop_is_not_wrapped_up(self):
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        machine.resumed_from = None
        machine.preview.side_effect = ManualStop("用户按下 P")
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        with self.assertRaises(ManualStop):
            runner.run(max_cycles=5)

        self.assertEqual(0, hook.calls, "手动停不该去动游戏")

    def test_a_crash_is_not_wrapped_up(self):
        """跑到一半挂了 ⇒ 不动游戏。竞技场停在对手列表/选人页时按 Back 是安全的，
        但「认不出画面」本来就可能停在任意一页（甚至战斗中），一律不碰最稳。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 0
        machine.resumed_from = None
        machine.preview.side_effect = RuntimeError("页面没认出来")
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        with self.assertRaises(RuntimeError):
            runner.run(max_cycles=5)

        self.assertEqual(0, hook.calls, "异常退出不该去动游戏")

    def test_a_failed_wrap_up_never_changes_the_result(self):
        hook = _Hooked(failure="页面[对手列表]返回无效")
        machine = MagicMock()
        machine.state = ArenaState.LIST
        machine.completed_cycles = 2
        machine.resumed_from = None
        logs: list[str] = []
        runtime = Runtime(blank, lambda _: None, emit=logs.append)
        runner = ArenaRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        completed = runner.run(max_cycles=2)

        self.assertEqual(2, completed)
        self.assertEqual(1, hook.calls)
        self.assertTrue(
            any("收尾=回首页失败" in line for line in logs),
            f"收尾失败必须在日志里看得见：{logs}",
        )


class FinishHomeWiringTests(unittest.TestCase):
    """钩子**真的接进装配**了吗（静态能查的那一半）。"""

    def test_the_base_runner_declares_the_hook_as_none_by_default(self):
        """默认 None = 零行为 ⇒ 没装钩子的路线（含所有单测）行为完全不变。"""
        self.assertIsNone(ModeRunnerBase._finish_home)

    def test_main_installs_the_hook_on_the_runner_it_builds(self):
        """``main.run_mode`` 必须在 ``runner.run()`` **之前**装钩子。

        用源码级断言而不是跑 ``run_mode``：真跑要起窗口、建模板，代价远大于收益，
        而这里要守的正是「有没有这一行」。
        """
        import inspect

        import auto_game_unified.main as main_module

        source = inspect.getsource(main_module.run_mode)
        self.assertIn("_install_finish_home(runner", source)
        self.assertLess(
            source.index("_install_finish_home(runner"),
            source.index("runner.run("),
            "必须先装钩子再跑 —— 顺序反了钩子等于没装",
        )


if __name__ == "__main__":
    unittest.main()
