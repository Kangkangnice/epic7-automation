"""世界首领战 Runner 的回归测试。

守四类事：
1. 战斗移交后的状态落点（结算 / 体力弹窗退回配置页）。
2. **次数耗尽时不再开下一局** —— 这是这条路线最重要的安全边界。
3. 生命之叶耗尽走资源退出，不是故障。
4. **战斗画面认得出、右上角「跳过」点得掉** —— 2026-09-22 实跑报错
   「战斗画面持续无法识别 45 秒」的回归（见 ``WorldBossBattleScreenTests``）。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.world_boss import (
    BATTLE_SKIP_REGION,
    BATTLE_SKIP_THRESHOLD,
    CLICK_POINTS,
    SELECT_TEAM_ENABLED_GREEN_RATIO,
    WorldBossAction,
    WorldBossRunner,
    WorldBossState,
    WorldBossStateMachine,
    find_world_boss_skip,
    team_configured,
    select_team_enabled,
    select_team_green_ratio,
    state_label,
    world_boss_battle_visible,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_world_boss"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "world_boss"


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert image is not None, f"读不到夹具 {name}"
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def blank() -> np.ndarray:
    return np.zeros((1132, 1982, 3), dtype=np.uint8)


class WorldBossCountTests(unittest.TestCase):
    """次数口径：看「选择队伍」按钮亮不亮，不看进程跑了几轮。"""

    def test_actionable_home_has_a_bright_green_button(self):
        screen = fixture("worldboss_home")

        ratio = select_team_green_ratio(screen)

        self.assertGreater(ratio, SELECT_TEAM_ENABLED_GREEN_RATIO)
        self.assertTrue(select_team_enabled(screen))

    def test_exhausted_home_has_a_grey_button(self):
        screen = fixture("worldboss_home_exhausted")

        ratio = select_team_green_ratio(screen)

        self.assertEqual(0.0, ratio)
        self.assertFalse(select_team_enabled(screen))

    def test_exhausted_home_still_identifies_as_the_home_page(self):
        """按钮变灰只是「没次数了」，页面本身还是主页 —— 不能认成未知画面。

        认不出来会落到「未知画面唤醒」点屏幕中央，而那里正好是队伍卡片。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        self.assertIs(
            WorldBossState.HOME, machine.observe_page(fixture("worldboss_home_exhausted"))
        )


class WorldBossStateMachineTests(unittest.TestCase):
    def test_full_cycle_walks_every_page_in_order(self):
        machine = WorldBossStateMachine(TEMPLATES)
        expected = [
            ("worldboss_home", WorldBossState.HOME, "open-team-select"),
            ("team_select", WorldBossState.TEAM_SELECT, "build-team"),
            # 配置队伍页分两阶段：按钮还是橙色 ⇒ 先自动配置，不点战斗开始。
            ("team_config", WorldBossState.TEAM_CONFIG, "auto-configure"),
            # 按钮转蓝 ⇒ 自动配置已生效，这一步才点战斗开始。
            ("team_config_configured", WorldBossState.TEAM_CONFIG, "battle-start"),
            ("stamina_popup", WorldBossState.TEAM_CONFIG, "stamina_material"),
            ("battle_result", WorldBossState.RESULT, "open-level-reward"),
            ("level_reward", WorldBossState.LEVEL_REWARD, "open-all-chests"),
            # 从奖励弹窗回到结算页：同一个页面，这一步要做的是「回主页」。
            ("battle_result", WorldBossState.RESULT_CONFIRM, "confirm-result"),
        ]

        for name, state, action_name in expected:
            with self.subTest(page=name):
                action = machine.next_action(fixture(name))
                self.assertEqual(state, machine.state)
                self.assertEqual(action_name, action.name)

    def test_team_config_is_recognised_without_walking_through_team_select(self):
        """配置队伍页有自己的排他锚点，不依赖「上一帧在哪」。

        靠上下文猜的判据在状态拨错时不会自愈，只会卡到超时 —— 这里守住它不会退回去。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("team_config"))

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)
        self.assertEqual("auto-configure", action.name)
        self.assertEqual(CLICK_POINTS["auto-configure"], action.point)

    def test_auto_configure_is_skipped_once_teams_are_filled(self):
        """队伍配好后不能重复点「自动配置」，必须直接点「战斗开始」。

        判据是**三队槽位里有没有英雄**（画面细节量），不是按钮颜色 ——
        两张 fixture 的按钮配色可以一样，但一个槽位空、一个槽位满：

        - ``team_config.png``：三队槽位空、战斗力 0（细节量 ≈ 451）
        - ``team_config_configured.png``：三队各 5 人、战斗力 58~67 万（细节量 ≈ 1182）

        ⚠️ 2026-09-22 曾经拿「自动配置」按钮的橙/蓝色相当判据，实跑直接翻车：
        那颗按钮的配色与「队伍配没配」无关，同一个空队伍页面几分钟内就会由蓝转橙。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        self.assertFalse(team_configured(fixture("team_config")))
        self.assertTrue(team_configured(fixture("team_config_configured")))

        action = machine.next_action(fixture("team_config_configured"))

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)
        self.assertEqual("battle-start", action.name)
        self.assertEqual(CLICK_POINTS["battle-start"], action.point)

    def test_team_config_with_empty_slots_asks_for_auto_configure(self):
        """三队槽位还是空的 ⇒ 必须先点「自动配置」，不能直接开战。

        这正是 2026-09-22 实跑失败的根因：判据误判成「已配置」，
        跳过了自动配置，去点一个打不起来的「战斗开始」。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("team_config"))

        self.assertEqual("auto-configure", action.name)
        self.assertEqual(CLICK_POINTS["auto-configure"], action.point)

    def test_stamina_popup_does_not_click_the_button_behind_it(self):
        """体力弹窗期间只能买树叶，绝不能点弹窗背后的「战斗开始」。"""

        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("stamina_popup"))

        self.assertIn(action.name, {"stamina_material", "stamina_confirm"})
        self.assertNotEqual(CLICK_POINTS["battle-start"], action.point)

    def test_every_action_declares_its_source_page(self):
        """每个动作都必须声明出处，换页的动作还要声明去处（转场契约）。

        2026-09-22 首次实跑就是栽在这上面：动作只有 name+point，主循环没有任何依据
        判断「这一步该不该做」「做了到底生效没有」，于是在进配置队伍页的同一秒
        直接点了战斗开始，漏掉自动配置，队伍空着就开打。

        **同页动作**（点自动配置 / 买树叶）只声明 ``source_page``，不声明
        ``target_pages`` —— 目标页写本页的话，转场验收会永远通过，「验收」形同虚设。
        """
        machine = WorldBossStateMachine(TEMPLATES)
        expected = [
            ("worldboss_home", "世界首领战主页", ("选择辅助队伍",)),
            ("team_select", "选择辅助队伍", ("配置队伍",)),
            # 自动配置不换页：不声明 target_pages，验收靠按钮由橙转蓝。
            ("team_config", "配置队伍", ()),
            ("team_config_configured", "配置队伍", ("战斗中",)),
            ("battle_result", "战斗结算", ("战斗级别奖励",)),
            # 「全部开启」是同一按钮换字，同样不换页。
            ("level_reward", "战斗级别奖励", ()),
        ]

        for name, source_page, target_pages in expected:
            with self.subTest(page=name):
                action = machine.next_action(fixture(name))
                self.assertEqual(source_page, action.source_page)
                self.assertEqual(target_pages, action.target_pages)
                self.assertTrue(action.reason)
                # 契约要对账，靠的是状态机在发动作时写下「我站在这页」。
                self.assertEqual(source_page, machine._confirmed_page)

    def test_stamina_actions_declare_the_popup_as_source_page(self):
        machine = WorldBossStateMachine(TEMPLATES)

        action = machine.next_action(fixture("stamina_popup"))

        self.assertEqual("行动力不足弹窗", action.source_page)
        # 弹窗内不换页 ⇒ 不声明 target_pages。
        self.assertEqual((), action.target_pages)
        self.assertEqual("行动力不足弹窗", machine._confirmed_page)

    def test_unrecognized_screen_clears_the_confirmed_page(self):
        """认不出画面时必须清掉对账依据，不能拿旧页面去比对下一帧。"""

        machine = WorldBossStateMachine(TEMPLATES)
        machine.next_action(fixture("worldboss_home"))
        self.assertEqual("世界首领战主页", machine._confirmed_page)

        with self.assertRaises(UnrecognizedScreen):
            machine.next_action(blank())

        self.assertEqual("", machine._confirmed_page)


class WorldBossRunnerTests(unittest.TestCase):
    def test_committed_battle_returns_control_to_result_state(self):
        machine = MagicMock()
        machine.state = WorldBossState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

        runner._run_committed_battle(cycle=1)

        supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
        self.assertEqual(WorldBossState.RESULT, machine.state)

    def test_stamina_popup_during_battle_hands_back_to_team_config(self):
        machine = MagicMock()
        machine.state = WorldBossState.BATTLE
        supervisor = MagicMock()
        supervisor.run.return_value = BattleOutcome.PRE_BATTLE_BUSINESS
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None),
            sleep=lambda _: None,
            battle_supervisor=supervisor,
        )

        runner._run_committed_battle(cycle=1)

        self.assertEqual(WorldBossState.TEAM_CONFIG, machine.state)

    def test_stamina_exhaustion_is_a_normal_resource_stop(self):
        machine = MagicMock()
        machine.state = WorldBossState.TEAM_CONFIG
        machine.completed_cycles = 0
        machine.preview.side_effect = StaminaExhausted("no leaves")
        runner = WorldBossRunner(
            machine,
            Runtime(blank, lambda _: None, emit=lambda _: None),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=3)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)

    def test_failing_stamina_confirm_after_four_clicks_stops_as_resource_exhaustion(self):
        machine = MagicMock()
        machine.state = WorldBossState.TEAM_CONFIG
        machine.completed_cycles = 0
        action = WorldBossAction("stamina_confirm", (1, 1))
        machine.preview.return_value = (action, (WorldBossState.TEAM_CONFIG, 0))
        machine.next_action.return_value = action
        clicks = []
        runner = WorldBossRunner(
            machine,
            Runtime(blank, clicks.append, emit=lambda _: None),
            sleep=lambda _: None,
        )
        runner._ACTION_RETRY_SECONDS = 0

        completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertTrue(runner.resource_exhausted)
        self.assertEqual(4, len(clicks))

    def test_dry_run_on_home_reports_the_open_team_select_action(self):
        """空跑只拍一帧、只做一次识别，不进入轮询。

        空跑**不会真的点击**（``Runtime.click`` 在 dry_run 下只记日志），
        所以这里断言日志里的动作名，而不是点击回调。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        clicks: list[tuple[int, int]] = []
        logs: list[str] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                lambda: fixture("worldboss_home"),
                clicks.append,
                dry_run=True,
                emit=logs.append,
            ),
            sleep=lambda _: None,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(0, completed)
        self.assertEqual(WorldBossState.HOME, machine.state)
        self.assertEqual([], clicks)
        self.assertTrue(
            any("动作=open-team-select" in line for line in logs),
            f"空跑日志里应报出 open-team-select，实际 {logs}",
        )

    def test_dry_run_rejects_an_unrecognised_screen_without_polling(self):
        sleeps: list[float] = []
        with TemporaryDirectory() as directory:
            runner = WorldBossRunner(
                WorldBossStateMachine(TEMPLATES),
                Runtime(
                    blank,
                    lambda _: None,
                    dry_run=True,
                    diagnostic_dir=Path(directory),
                ),
                sleep=sleeps.append,
            )

            with self.assertRaisesRegex(RuntimeError, r"空跑未识别画面\[世界首领战主页\]"):
                runner.run(max_cycles=1)

        self.assertEqual([], sleeps)


class _FakeClock:
    """假时钟 + 帧游标：**一次 ``sleep`` = 前进一帧**（等价于一个轮询周期）。

    这样「画面随时间推进」和「时钟随时间推进」是同一个动作，符合真机语义：
    轮询一圈、拍一张新图。

    ``hold={下标: 次数}`` 让某个画面**多停留几个轮询周期** —— 主循环的同页
    重试窗口是 45 秒（``poll_seconds=1.0`` ⇒ 45 个周期），要让「重试一次」真的发生，
    当前画面就必须至少停留那么久。不写 ``hold`` 时每个画面只占一个周期。
    """

    def __init__(
        self, frames: list[np.ndarray], *, hold: dict[int, int] | None = None
    ) -> None:
        self.frames = frames
        self.hold = hold or {}
        self.now = 0.0
        self.index = 0
        self.remaining = self.hold.get(0, 1)

    @property
    def frame(self) -> int:
        return min(self.index, len(self.frames) - 1)

    def capture(self) -> np.ndarray:
        return self.frames[self.frame]

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)
        self.advance()

    def advance(self, frames: int = 1) -> None:
        for _ in range(frames):
            self.remaining -= 1
            if self.remaining > 0:
                continue
            self.index = min(self.index + 1, len(self.frames) - 1)
            self.remaining = self.hold.get(self.index, 1)


class WorldBossTeamConfigTwoStageTests(unittest.TestCase):
    """配置队伍页必须走「先自动配置、验收通过、再战斗开始」。

    2026-09-22 首次实跑就是在这里栽的：进页同一秒直接点了战斗开始。
    下面用**真状态机 + 真 Runner**跑一遍完整流程，守住这个顺序。

    战斗入口与竞技场同构（``ArenaRunner`` 也是 ``_BATTLE_ENTRY_ACTION="battle-start"``
    + 默认 ``_CLICK_BEFORE_BATTLE=True``）：主循环点「战斗开始」，点完**立刻**
    把这一局交给 ``BattleSupervisor``，由监督一路跟到结算页。
    转场契约（``target_pages=(战斗中,)``）保证「点了没生效」能被看出来。
    """

    @staticmethod
    def _runner_with_frames(
        frames: list[np.ndarray],
        clicks: list[tuple[int, int]],
        *,
        diagnostics: str | None = None,
        supervisor_outcome: BattleOutcome = BattleOutcome.RESULT_REACHED,
        hold: dict[int, int] | None = None,
    ) -> tuple[WorldBossRunner, MagicMock, _FakeClock]:
        """真状态机 + 真 Runner，按帧序列喂画面；监督由 MagicMock 记录其点击后放行。

        监督的 ``run`` 直接返回 ``supervisor_outcome`` —— 默认 ``RESULT_REACHED``
        表示这一局正常打到结算；``PRE_BATTLE_BUSINESS`` 表示监督发现战前业务页
        （体力弹窗）开着、把控制权交还业务状态机。

        ⚠️ **必须喂假时钟**：Runner 的 ``self.now`` 是 ``runtime.now``（默认
        ``time.monotonic``）。如果让时钟走真时间，测试里 ``sleep`` 只是瞬间推进
        帧下标、真时间几乎不动，于是「同页重试窗口 45 秒」和「状态超时 45 秒」
        都永远到不了 —— 帧序列取完后 ``capture`` 一帧帧地喂同一张图，
        主循环会**无限循环**（2026-09-22 的死循环就是这么在测试里挂住的）。
        （同类写法见 ``test_navigation.py::clocked_navigator``。）
        """

        clock = _FakeClock(frames, hold=hold)
        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG
        supervisor = MagicMock()
        supervisor.run.side_effect = lambda *_, **__: supervisor_outcome
        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                clicks.append,
                emit=lambda _: None,
                diagnostic_dir=Path(diagnostics) if diagnostics else None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
            battle_supervisor=supervisor,
        )
        # ⚠️ 重试窗口**不能**清零：被清零时「同页动作的重试间隔」恒为 0，
        # 4 次尝试会在 4 帧内烧光，等不到「画面第三次变蓝」——那正是本组要验的行为。
        # 用真实窗口（45 秒）+ `poll_seconds=1.0`，等于「每 45 帧才允许重试一次」，
        # 帧序列按这个节奏排即可（见各用例的注释）。
        return runner, supervisor, clock

    @classmethod
    def _run_until_handoff(
        cls, frames: list[np.ndarray], clicks: list[tuple[int, int]], **kwargs
    ) -> tuple[WorldBossRunner, list[int], _FakeClock]:
        """喂到「控制权刚交给战斗监督」为止就停 —— 不把监督那一段跑下去。

        做法：监督的 ``run`` **只记录调用、不返回**，直接抛一个哨兵异常把
        ``runner.run()`` 掀掉。这样主循环不会越过移交点继续跑
        （否则 mock 的立即返回会让状态机把「结算」当既成事实，
        接着又拿配置页的帧去重判，产生一串假的 ``battle-start`` 点击）。
        终局行为交给专门的用例去测。

        返回的第二个值是「移交次数」列表（长度为 1 表示恰好移交一次）。
        """

        class _HandedOff(Exception):
            """内部哨兵：控制权已到监督手里。"""

        runner, supervisor, clock = cls._runner_with_frames(frames, clicks, **kwargs)
        handoffs: list[int] = []

        def _hand_off(*_args, **_kw):
            handoffs.append(1)
            raise _HandedOff

        supervisor.run.side_effect = _hand_off
        try:
            runner.run(max_cycles=1)
        except _HandedOff:
            pass
        else:
            raise AssertionError("帧序列已喂完但战斗监督始终没被移交")
        return runner, handoffs, clock

    def test_auto_configure_runs_before_battle_start(self):
        """橙帧 → 必须先点自动配置；转蓝后点战斗开始；点完即移交监督。

        帧序列按「一次 sleep = 一帧」排，并用 ``hold`` 让橙色页停留足够久
        （超过一个 45 秒重试窗口，所以自动配置会被点两次 —— 这正是
        「按一次、验收一次」：还是橙就再来一次）：
        橙①（点自动配置 ×2）→ 蓝②（两帧稳定 → 点战斗开始）→ 战斗③（移交监督）。
        """

        clicks: list[tuple[int, int]] = []
        frames = [
            fixture("team_config"),  # ① 橙：还没配
            fixture("team_config_configured"),  # ② 蓝：配完了
            fixture("battle"),  # ③ 战斗画面 = 出口标志
        ]
        with TemporaryDirectory() as directory:
            runner, handoffs, _ = self._run_until_handoff(
                frames, clicks, diagnostics=directory, hold={0: 60, 1: 4, 2: 2}
            )

        auto_point = CLICK_POINTS["auto-configure"]
        battle_point = CLICK_POINTS["battle-start"]
        self.assertEqual(
            [auto_point, auto_point, battle_point],
            clicks,
            f"必须「先自动配置（未生效就重试）、再战斗开始」，实际点击 {clicks}",
        )
        self.assertEqual(1, len(handoffs), "战斗监督应恰好被移交一次")

    def test_battle_start_declares_the_battle_page_as_its_target(self):
        """「战斗开始」必须声明 ``target_pages=(战斗中,)`` —— 出口标志。

        没有它，主循环点完就盲目往下走，分不出「点了没生效」和「点了生效了」。
        同时也是 ``observe_page`` 必须能认出战斗画面的理由
        （目标页要真认得出来，这个契约才有意义）。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG

        action = machine.preview(fixture("team_config_configured"))[0]

        self.assertEqual("battle-start", action.name)
        self.assertEqual(
            (state_label(WorldBossState.BATTLE),),
            action.target_pages,
            "「战斗开始」必须声明落点是战斗中，否则转场验收无从谈起",
        )
        # 落点必须真认得出：拿战斗画面过一遍状态机，得判成 BATTLE。
        self.assertEqual(
            WorldBossState.BATTLE,
            machine.observe_page(fixture("battle")),
            "战斗画面必须被识别成 BATTLE，否则 target_pages 是空头支票",
        )

    def test_battle_page_confirms_itself_so_the_transition_can_close(self):
        """认出战斗画面时必须 ``_confirm_page`` —— 否则 ``target_pages`` 永远匹配不上。

        主循环是在**拍完这一帧、调 next_action 之前**读 ``_confirmed_page`` 的，
        所以「我现在站在战斗中」必须被这一帧写下来，下一帧才读得到「已到达目标页」。
        不写的话 ``_confirmed_page`` 一直停在上一个动作的 source_page（配置队伍）
        ⇒ 契约空转 ⇒ 45 秒后走「转场超时」。

        ⚠️ 只断言 ``target_pages`` 里写了「战斗中」是不够的（见上一个用例）——
        那只能证明**声明**了落点，证明不了落点**真会被确认**。这个用例补的就是后者。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.TEAM_CONFIG

        action = machine.next_action(fixture("team_config_configured"))
        self.assertEqual("battle-start", action.name)
        self.assertNotIn(
            state_label(WorldBossState.BATTLE),
            (machine._confirmed_page,),
            "还没看到战斗画面，不该已经确认成战斗中",
        )

        # 游戏推进到战斗画面：这一帧必须把「战斗中」写成已确认页面。
        machine.next_action(fixture("battle"))
        self.assertEqual(
            state_label(WorldBossState.BATTLE),
            machine._confirmed_page,
            "认出战斗画面后必须 _confirm_page(战斗中)，否则转场契约永远不成立",
        )
        self.assertIn(
            machine._confirmed_page,
            action.target_pages,
            "已确认页面必须落在 battle-start 声明的 target_pages 里，契约才闭合",
        )

    def test_blue_button_never_clicks_auto_configure_again(self):
        """按钮已转蓝时不许重复点自动配置（避免无意义的重复动作）。"""

        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runner, handoffs, _ = self._run_until_handoff(
                [fixture("team_config_configured"), fixture("battle")],
                clicks,
                diagnostics=directory,
                hold={0: 4, 1: 2},
            )

        self.assertNotIn(CLICK_POINTS["auto-configure"], clicks)
        self.assertIn(CLICK_POINTS["battle-start"], clicks)
        self.assertEqual(1, len(handoffs))

    def test_orange_button_retries_auto_configure_until_it_turns_blue(self):
        """自动配置**按一次验收一次**：还是橙就重试，转蓝才推进。

        橙色页停满**两个**重试窗口 ⇒ 自动配置要被点两次；画面转蓝后不再点它，
        只点战斗开始。这守住「不换页动作靠按钮颜色验收」，而不是靠 target_pages 空转。
        """

        clicks: list[tuple[int, int]] = []
        frames = [
            fixture("team_config"),  # 持续为橙 —— 需要反复重试
            fixture("team_config_configured"),  # 终于转蓝
            fixture("battle"),
        ]
        with TemporaryDirectory() as directory:
            runner, handoffs, clock = self._run_until_handoff(
                frames, clicks, diagnostics=directory, hold={0: 60, 1: 4, 2: 2}
            )

        auto_point = CLICK_POINTS["auto-configure"]
        battle_point = CLICK_POINTS["battle-start"]
        # 橙色期间至少重试过一次自动配置；转蓝后**不再**点自动配置，只点战斗开始。
        self.assertGreaterEqual(clicks.count(auto_point), 2, f"实际点击 {clicks}")
        self.assertIn(battle_point, clicks, f"实际点击 {clicks}")
        last_auto = len(clicks) - 1 - clicks[::-1].index(auto_point)
        self.assertLess(
            last_auto,
            clicks.index(battle_point),
            f"自动配置的重试必须都发生在点战斗开始之前，实际点击 {clicks}",
        )
        # 假时钟真的被推进过：说明「重试窗口」是靠时间等出来的，
        # 而不是靠帧下标碰巧走到（那样测试会假绿）。
        self.assertGreater(clock.now, 0.0)
        self.assertEqual(1, len(handoffs))

    def test_battle_start_without_battle_screen_stops_after_bounded_retries(self):
        """点了战斗开始但战斗画面始终不出现 ⇒ 有界重试后安全停止，**绝不无限重交**。

        这是 2026-09-22 的死循环回归：修复前监督交还 → 主循环又移交，
        实测交了 199 次都停不下来。现在必须有**明确上限**并走安全停止。

        帧序列一直停在「蓝按钮的配置队伍页」= 点了战斗开始但画面毫无变化
        （战斗监督发现打不起来、把控制权交还，回到配置队伍页），如此循环。
        """

        clicks: list[tuple[int, int]] = []
        with TemporaryDirectory() as directory:
            runner, supervisor, clock = self._runner_with_frames(
                [fixture("team_config_configured")] * 40,
                clicks,
                diagnostics=directory,
                supervisor_outcome=BattleOutcome.PRE_BATTLE_BUSINESS,
            )
            with self.assertRaises(RuntimeError) as caught:
                runner.run(max_cycles=1)

        message = str(caught.exception)
        # 终局必须是「点了几次都没进战斗」这个业务结论，而不是「点击 4 次没转场」
        # 这种兜底错误 —— 前者说明程序知道自己在等什么。
        self.assertIn("仍未进入战斗", message)
        # 关键断言：移交次数必须被**上限**截住，而不是无限循环。
        self.assertLessEqual(
            supervisor.run.call_count,
            runner._MAX_BATTLE_ATTEMPTS + 1,
            f"战斗监督最多被移交 {runner._MAX_BATTLE_ATTEMPTS + 1} 次，"
            f"实际 {supervisor.run.call_count} 次（说明仍在无限重交）",
        )
        self.assertGreater(clock.now, 0.0)


class WorldBossBattleScreenTests(unittest.TestCase):
    """战斗画面识别 + 右上角「跳过」的回归测试。

    2026-09-22 20:57 实跑报错「战斗画面持续无法识别超时」的真因：世界首领战的战斗
    画面是**团本布局**（左上 boss 名 + 血条、右上 跳过/聊天/暂停、右侧 12 人分数列），
    旧判据 ``battle_controls.battle_scene_visible``（4 格底座 + 左侧行动顺序）在它上面
    **恒为 False** ⇒ 监督 ``recognized`` 连续 45 秒为假 ⇒ 安全停止。

    修法两条腿：① 右上角「跳过」当识别锚点；② 命中时把 ``("skip-battle", 点)``
    交给监督点掉，很快就衔接到结算页。
    """

    #: 「跳过 」的实测点击中心（画布坐标）。用户 1920×1080 实拍截图按
    #: ``core/window.py::_legacy_canvas`` 的 (0,+52) 偏移还原后量的亮像素包围盒中心。
    SKIP_POINT = (1631, 97)

    def test_live_battle_frame_is_recognised_as_the_battle_page(self):
        machine = WorldBossStateMachine(TEMPLATES)

        self.assertIs(
            WorldBossState.BATTLE, machine.observe_page(fixture("battle_live_skip"))
        )

    def test_old_detector_alone_misses_the_live_battle_frame(self):
        """守根因：**只看旧判据认不出这一屏** —— 这正是必须新增锚点的理由。

        哪天这个断言不再成立（``battle_scene_visible`` 变 True），说明底层判据被改过，
        上面那条「新增锚点」的注释与文档就得跟着复核。
        """

        template = WorldBossStateMachine(TEMPLATES).templates.battle_skip
        screen = fixture("battle_live_skip")

        self.assertFalse(
            battle_scene_visible(screen),
            "旧判据若能认出团本战斗画面，就不必新增「跳过」锚点了",
        )
        self.assertTrue(world_boss_battle_visible(screen, template))
        self.assertIsNotNone(find_world_boss_skip(screen, template))

    def test_skip_anchor_click_point_is_the_measured_button_centre(self):
        """命中点必须落在实测的那颗按钮上 —— 偏差大了就会点空。"""

        template = WorldBossStateMachine(TEMPLATES).templates.battle_skip
        match = find_world_boss_skip(fixture("battle_live_skip"), template)

        self.assertIsNotNone(match)
        self.assertLessEqual(abs(match.center[0] - self.SKIP_POINT[0]), 3)
        self.assertLessEqual(abs(match.center[1] - self.SKIP_POINT[1]), 3)
        self.assertGreater(match.score, BATTLE_SKIP_THRESHOLD)

    def test_observe_battle_offers_the_skip_action(self):
        """战斗帧上要把「跳过」作为允许动作报出去，监督才有得点。"""

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("battle_live_skip"), None)

        self.assertTrue(observation.battle_visible)
        self.assertIsNotNone(observation.allowed_action)
        name, point = observation.allowed_action
        self.assertEqual("skip-battle", name)
        self.assertLessEqual(abs(point[0] - self.SKIP_POINT[0]), 3)
        self.assertLessEqual(abs(point[1] - self.SKIP_POINT[1]), 3)

    def test_skill_animation_frame_is_deliberately_unrecognised(self):
        """boss 技能演出会整块隐藏 UI ⇒ 认不出是**预期行为**，不是漏判。

        演出只有几秒，下一帧 UI 回来就重新认到，45 秒看门狗靠这个复位。
        别为了让这张帧也认出来，去给演出画面单独做锚点 —— 那种锚点会咬到场景美术。
        """

        machine = WorldBossStateMachine(TEMPLATES)

        observation = machine.observe_battle(fixture("battle_skill_anim"), None)

        self.assertFalse(observation.battle_visible)
        self.assertIsNone(
            observation.allowed_action,
            "演出帧上不该报出跳过动作（这时候按钮根本不在画面上）",
        )

    def test_no_other_world_boss_page_is_mistaken_for_a_battle(self):
        """本路线其它页一张都不许被判成「战斗中」。

        误判的后果很重：监督会以为战斗已经开始，然后一路空等到 900 秒绝对超时。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        pages = (
            "worldboss_home",
            "worldboss_home_exhausted",
            "team_select",
            "team_config",
            "team_config_configured",
            "stamina_popup",
            "battle_result",
            "level_reward",
            "knights_home",
            "knights_home_after_popup",
            "knights_signin_popup",
            "gift_support_popup",
            "lobby_with_knights",
        )

        for name in pages:
            with self.subTest(page=name):
                self.assertFalse(
                    machine.battle_visible(fixture(name)),
                    f"{name} 被误判成战斗画面",
                )

    def test_supervisor_clicks_the_skip_button_then_returns_on_the_result(self):
        """「跳过」不能只报在观察结果里，必须由监督真的点出去。

        帧序列：战斗②帧（连续 2 帧稳定才允许点）→ 结算②帧（连续 2 帧才算到结算）。
        一次 ``sleep`` = 一帧。
        """

        machine = WorldBossStateMachine(TEMPLATES)
        machine.state = WorldBossState.BATTLE
        clock = _FakeClock(
            [
                fixture("battle_live_skip"),
                fixture("battle_live_skip"),
                fixture("battle_result"),
                fixture("battle_result"),
            ]
        )
        clicks: list[tuple[int, int]] = []
        runner = WorldBossRunner(
            machine,
            Runtime(
                clock.capture,
                clicks.append,
                emit=lambda _: None,
                monotonic=lambda: clock.now,
            ),
            sleep=clock.sleep,
        )

        outcome = runner._run_committed_battle(cycle=1)

        self.assertIs(BattleOutcome.RESULT_REACHED, outcome)
        self.assertEqual(
            [self.SKIP_POINT], clicks, f"应恰好点一次「跳过」，实际点击 {clicks}"
        )
        self.assertEqual(WorldBossState.RESULT, machine.state)

    def test_skip_anchor_window_stays_left_of_the_story_skip_button(self):
        """搜索窗口必须把剧情播放页的「跳过」挡在门外。

        同一个「跳过 」图形剧情播放页也有，只是位置更靠右（x≈1769~1886）。
        窗口一旦放宽到盖住那一带，锚点分就只剩 0.05 的间距（实测 0.9086 vs 0.8585），
        等于把「是不是战斗画面」变成赌注。
        """

        x, _, width, _ = BATTLE_SKIP_REGION
        half = WorldBossStateMachine(TEMPLATES).templates.battle_skip.shape[1] // 2

        self.assertLessEqual(x + width, 1760, "搜索区右边界要留在剧情页的跳过左侧")
        # 模板必须能整个放进窗口，且实测的那颗按钮在窗口正中一带：
        # 匹配器把模板完整放在窗口内，中心落在 [x+half, x+width-half]。
        self.assertLessEqual(x + half, self.SKIP_POINT[0])
        self.assertLessEqual(self.SKIP_POINT[0], x + width - half)


if __name__ == "__main__":
    unittest.main()
