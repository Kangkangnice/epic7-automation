"""「收尾回首页」的契约测试（10 条路线，豁免 1 条）。

用户 2026-09-25 的诉求：一条路线跑完之后，游戏要**自己退回首页**，
这样后面串多个任务时才能衔接得上（此前 10 条路线**一条都没有**这个动作，
跑完就停在当时那一页）。

守五件事：

1. **路线真的会调用收尾钩子** —— 用真 Runner + 可控状态机跑完，断言钩子被调。
   只断言「main 里装了钩子」是不够的：装了没人调，静态看一切正常，
   只有跑一遍才现形（`_ResumeWatch.asked` 那个接线检查就是同一个道理）。
2. **三类退出各自接不接** —— 正常完成、资源耗尽（退出码 2）要接；
   手动停（130）与异常（1）**不接**。后者是安全的：跑到一半挂了还去按 Back，
   可能把已承诺的战斗弄丢。
3. **收尾失败绝不改退出码** —— 任务本身已经成功了，不能因为「没走回家」就报失败。
4. **竞技场的接力开局不该被送回家** —— 人本来就停在半路，我们只补完这一局。
5. **加载期自查真的接上了** —— 新路线漏做收尾要在 import 阶段就被拦住。

⚠️ 路线分两族，退出路径**形状完全不同**，下面分段写，别照抄：
- **继承 `ModeRunnerBase` 的 6 条**（story / fodder / hero_synthesis / world_boss /
  knights_donation / 迷宫强化石）：收尾在基类 `run()` 里统一接了。
- **自带独立主循环的 3 条**（arena / expedition / shop_refresh）：各自声明
  `_close_out()`、各自接退出口。
- **1 条豁免**（survivor）：见 `finish_home.FINISH_HOME_EXEMPT`。
"""

import inspect
import unittest
from unittest.mock import MagicMock

import numpy as np

from auto_game_unified.core.runtime import ManualStop, Runtime, StaminaExhausted
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState
from auto_game_unified.games.epic7.expedition import ExpeditionRunner, ExpeditionState
from auto_game_unified.games.epic7.knights_donation import (
    KnightsDonationRunner,
    KnightsDonationState,
)
from auto_game_unified.games.epic7.finish_home import (
    FINISH_HOME_EXEMPT,
    _assert_finish_home_declared,
    _finish_home_verdict,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.shop_refresh import ShopRefreshRunner
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
        import auto_game_unified.main as main_module

        source = inspect.getsource(main_module.run_mode)
        self.assertIn("_install_finish_home(runner", source)
        self.assertLess(
            source.index("_install_finish_home(runner"),
            source.index("runner.run("),
            "必须先装钩子再跑 —— 顺序反了钩子等于没装",
        )


class ExpeditionFinishHomeTests(unittest.TestCase):
    """远征自带独立主循环，3 个正常退出口都得自己接。"""

    def _runner(self):
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ExpeditionState.HOME
        machine.completed_cycles = 0
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        # `now` 必须显式传：远征的 run() 用 `self.now()` 也直接用它当假时钟。
        runner = ExpeditionRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)
        return runner, hook, machine

    def test_running_out_of_tickets_returns_home(self):
        """通缉传单耗尽 ⇒ 资源耗尽退出，同样要回家。"""
        runner, hook, machine = self._runner()
        machine.preview.side_effect = StaminaExhausted("测试：传单用光了")

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(1, hook.calls, "远征资源耗尽没收尾回首页")

    def test_a_failed_wrap_up_never_changes_the_result(self):
        runner, hook, machine = self._runner()
        hook.failure = "受控返回8次后仍未回到大厅"
        machine.preview.side_effect = StaminaExhausted("测试：传单用光了")

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed, "收尾失败不该改轮次")
        self.assertTrue(runner.resource_exhausted, "收尾失败不该改掉资源耗尽的结论")
        self.assertEqual(1, hook.calls)

    def test_dry_run_does_not_wrap_up(self):
        """干跑是「只观察一帧」的诊断路径，不该动游戏。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.state = ExpeditionState.HOME
        machine.completed_cycles = 0
        machine.next_action.return_value = None
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None, dry_run=True)
        runner = ExpeditionRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)

        runner.run(max_cycles=3)

        self.assertEqual(0, hook.calls, "干跑不该去动游戏")


class ShopRefreshFinishHomeTests(unittest.TestCase):
    """刷书签自带独立主循环，正常退出口是 try 块里那一个 `return`。"""

    def _runner(self):
        hook = _Hooked()
        machine = MagicMock()
        machine.completed_cycles = 0
        machine.resumed_at_shop = False
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None)
        runner = ShopRefreshRunner(machine, runtime, sleep=lambda _: None)
        hook.install(runner)
        return runner, hook, machine

    def test_a_completed_run_returns_home(self):
        """刷满轮次（phase 走到 COMPLETE）⇒ 正常完成，要回家。"""
        runner, hook, machine = self._runner()

        # 让 observer 认为「实跑已验收」，否则 run() 会在开头直接抛错。
        observer = MagicMock()
        observer.live_transactions_verified = True
        runner.observer = observer
        # 简单起见：直接让 while 条件一开始就成立（phase 已是 COMPLETE）。
        from auto_game_unified.games.epic7.shop_refresh import ShopPhase

        machine.phase = ShopPhase.COMPLETE

        completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertEqual(1, hook.calls, "刷书签正常跑完没收尾回首页")

    def test_dry_run_does_not_wrap_up(self):
        """干跑在 try 里就 return 了，不该动游戏。"""
        hook = _Hooked()
        machine = MagicMock()
        machine.completed_cycles = 0
        machine.resumed_at_shop = False
        observer = MagicMock()
        observer.observe.return_value = MagicMock(page=MagicMock(value="shop"), rows=[])
        runtime = Runtime(blank, lambda _: None, emit=lambda _: None, dry_run=True)
        runner = ShopRefreshRunner(machine, runtime, observer=observer, sleep=lambda _: None)
        hook.install(runner)

        runner.run(max_cycles=1)

        self.assertEqual(0, hook.calls, "干跑不该去动游戏")


class FinishHomeDeclarationTests(unittest.TestCase):
    """加载期自查（`finish_home._assert_finish_home_declared`）真的接上了吗。

    这条自查是**开发者护栏**：新路线漏做收尾时，要在 import 阶段就报错，
    而不是等串任务时才发现接不上。没有它，十条路线里漏一条不会有任何人发现。
    """

    def test_the_check_is_wired_into_main(self):
        import auto_game_unified.main as main_module

        source = inspect.getsource(main_module)
        # 规矩本体住在 games/epic7/finish_home.py（好切、集中），但**必须有人调用**。
        # 只定义不调用等于没有 —— 由 main._install_finish_home 在装钩子时触发。
        self.assertIn("_assert_finish_home_declared()", source)
        self.assertIn(
            "from auto_game_unified.games.epic7.finish_home import "
            "_assert_finish_home_declared",
            source,
        )

    def test_the_check_is_not_orphaned_in_modes(self):
        """modes.py 不该再引用自查（表与函数都已挪走）。"""
        import auto_game_unified.games.epic7.modes as modes_module

        source = inspect.getsource(modes_module)
        self.assertNotIn("_assert_finish_home_declared()", source)
        self.assertNotIn("FINISH_HOME_EXEMPT", source.replace("已挪到", ""))

    def test_every_route_declares_its_stance(self):
        """当前 10 条路线：9 条接了收尾、1 条豁免（survivor）。"""
        self.assertSetEqual({"survivor"}, set(FINISH_HOME_EXEMPT))
        # 跑一遍不抛错 = 全员表过态。
        _assert_finish_home_declared()

    def test_mocking_a_runner_run_does_not_break_the_check(self):
        """⚠️ 回归：测试里给 `run()` 打桩，不该把自查骗成「漏收尾」。

        这本来是**真实事故**（2026-09-25）：自查原来读的是
        ``runner_type.__dict__["run"]``，而 `test_story_resume.py` 会
        ``mock.patch.object(StoryRunner, "run", fake_run)`` —— 那是个**当地方**，
        没有 ``super().run()`` ⇒ 自查误报「story 漏收尾」，6 条接力用例一起变红。
        现在改为按**磁盘源码**判，打桩不影响。
        """
        from unittest import mock

        from auto_game_unified.games.epic7.story import StoryRunner

        def fake_run(self, max_cycles=None):  # pragma: no cover - 只为打桩
            return 1

        with mock.patch.object(StoryRunner, "run", fake_run):
            _assert_finish_home_declared()  # 不抛错即通过

    def test_the_exempt_reason_says_why(self):
        """豁免必须写明理由，不能留个空壳。"""
        reason = FINISH_HOME_EXEMPT["survivor"]
        self.assertGreater(len(reason), 60, "豁免理由太短，等于没写")
        self.assertIn("刻意例外", reason)

    def test_a_bare_runner_without_close_out_is_rejected(self):
        """反证：裸定义且不调 `_close_out()` 的路线必须被拦住。

        这是这条自查存在的**唯一理由** —— 不拦的话它就是个摆设。
        直接喂判据（``_finish_home_verdict`` 是纯函数），
        **不在测试里改磁盘上的源码再重载模块** —— 那种写法中途失败会留下损坏的 .py。
        """
        error = _finish_home_verdict(
            "fake_bare",
            inherits_base=False,
            exempt=False,
            own_source="class FakeBareRunner:\n    def run(self):\n        return 0\n",
            own_run_source=None,
        )
        self.assertIsNotNone(error, "裸定义且不调 _close_out() 的路线没被拦住")
        self.assertIn("既不收尾回首页", error)

    def test_a_bare_runner_that_calls_close_out_passes(self):
        good = "class R:\n    def run(self):\n        self._close_out()\n        return 0\n"
        error = _finish_home_verdict(
            "fake_good",
            inherits_base=False,
            exempt=False,
            own_source=good,
            own_run_source=None,
        )
        self.assertIsNone(error)

    def test_commented_out_close_out_does_not_count(self):
        """⚠️ 回归：**注释掉的** `_close_out()` 不算接上。

        这本来是 ``"_close_out()" in source`` 的漏洞：把一条路线的调用全注释掉，
        字符串匹配照样放行 —— 实测过，expedition 三处注释掉之后自查没拦住。
        改用 ast 之后必须能认出来。
        """
        commented = (
            "class R:\n"
            "    def run(self):\n"
            "        # self._close_out()   ← 注释掉的不算\n"
            "        return 0\n"
        )
        error = _finish_home_verdict(
            "fake_commented",
            inherits_base=False,
            exempt=False,
            own_source=commented,
            own_run_source=None,
        )
        self.assertIsNotNone(error, "注释掉的 _close_out() 被当成接上了")

    def test_close_out_mention_in_a_docstring_does_not_count(self):
        """同理：文档串里举例提到 ``self._close_out()`` 也不算接上。"""
        documented = (
            "class R:\n"
            '    """收尾：调用 self._close_out() 回首页。"""\n'
            "    def run(self):\n"
            "        return 0\n"
        )
        error = _finish_home_verdict(
            "fake_doc",
            inherits_base=False,
            exempt=False,
            own_source=documented,
            own_run_source=None,
        )
        self.assertIsNotNone(error, "文档串里的 _close_out() 被当成接上了")

    def test_a_bare_runner_that_both_implements_and_is_exempt_is_rejected(self):
        """接了收尾却还躺在豁免名单里 ⇒ 报错（两边只能写一边）。"""
        error = _finish_home_verdict(
            "fake_both",
            inherits_base=False,
            exempt=True,
            own_source="class R:\n    def run(self):\n        self._close_out()\n",
            own_run_source=None,
        )
        self.assertIsNotNone(error)
        self.assertIn("两边只能写一边", error)

    def test_a_base_runner_that_overrides_run_without_super_is_rejected(self):
        """基类路线覆写了 run() 却忘了调 super() ⇒ 收尾被整个跳过，必须拦住。"""
        error = _finish_home_verdict(
            "fake_override",
            inherits_base=True,
            exempt=False,
            own_source=None,
            own_run_source="def run(self, max_cycles=None):\n    return 0\n",
        )
        self.assertIsNotNone(error)
        self.assertIn("super().run()", error)

    def test_a_base_runner_that_calls_super_passes(self):
        error = _finish_home_verdict(
            "fake_super",
            inherits_base=True,
            exempt=False,
            own_source=None,
            own_run_source="def run(self, max_cycles=None):\n    return super().run(max_cycles)\n",
        )
        self.assertIsNone(error)

    def test_missing_source_is_fail_open(self):
        """取不到源码（替身 / REPL 造的类）⇒ 放过，别让 import 崩掉。"""
        error = _finish_home_verdict(
            "fake_no_source",
            inherits_base=False,
            exempt=False,
            own_source=None,
            own_run_source=None,
        )
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
