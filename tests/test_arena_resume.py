"""竞技场「接力」：开局不无脑回大厅，停在竞技场某一步就从那一步接着往下跑。

背景：原来的实跑入口一律「回大厅 → 重新导航进竞技场」。用户如果已经人工把游戏推到
「准备战斗」「对手详情」或者「竞技场模式选择」，这套流程会把它一路退回到对手列表
从第 1 步重来（模式选择页甚至会退回大厅）。

整个竞技场一环里的页面与接力策略：

| 页面 | 识别方式 | 接力落点 |
| --- | --- | --- |
| 大厅 | `observe()`=lobby | 不接力，走老流程 |
| 竞技场模式选择 | `observe()`=arena_mode | `entry="arena_mode"`，继续导航进新手竞技场 |
| 对手列表 | `list_ready` | 状态机 `list`，已在业务入口，不导航 |
| 对手详情 | `challenge` 反超 `list_ready` | 状态机 `selected` |
| 准备战斗 | 战前页证据 | 状态机 `team` |
| 战斗中 | `battle_scene_visible` | 状态机 `battle`，交战斗监督等结算 |
| 战斗结果 | `confirm` | **不接力**：锚点与远征结果页共用，无排他证据 |
| 结果确认中 | 无锚点 | 不接力 |
| 段位晋升弹窗 | `observe()`=arena_rank_promotion | 不接力；老流程会先关掉它，再在列表页接力 |

安全边界（认错的代价必须小于收益）：
- 买票弹窗压住的队伍页不接力（接力过去会点到弹窗上）。
- 接力进去的那半轮不算已完成轮次。
- 认不出来一律回退到老流程，行为与加这个功能之前完全一致。
"""

from pathlib import Path
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified import main as main_module
from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import (
    ARENA_ENTRY_PAGE,
    ArenaRunner,
    ArenaState,
    ArenaStateMachine,
    build_templates,
    detect_resume_point,
    detect_resume_state,
    find_rank_promotion_confirm,
)
from auto_game_unified.games.epic7.modes import (
    _probe_arena_resume,
    get_mode,
)
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
ARENA_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
EXPEDITION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_expedition"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"

# 「结果确认中」= 段位提升弹窗，两张夹具是同一弹窗的不同段位文案。
RANK_PROMOTION_FIXTURES = ("rank_confirm", "rank_promotion_master")

# 局内实时帧：识别方式与是否可辨识各不相同，但都不该被当成「对战那几步」。
WATCH_BATTLE_FIXTURES = (
    "battle_auto_off_enemy_turn_live_20260826",
    "battle_skill_animation_live_20260825",
    "battle_auto_dead_one_live_20260814",
    "battle_auto_dead_three_live_20260814",
    "battle_manual_stuck_live_20260814",
)


def _load(directory: Path, name: str) -> np.ndarray:
    image = np.asarray(Image.open(directory / f"{name}.png").convert("RGB"))
    return image[:1132, :1982]


def arena_fixture(name: str) -> np.ndarray:
    return _load(ARENA_FIXTURES, name)


def navigation_fixture(name: str) -> np.ndarray:
    return _load(NAVIGATION_FIXTURES, name)


def expedition_fixture(name: str) -> np.ndarray:
    return _load(EXPEDITION_FIXTURES, name)


def new_machine() -> ArenaStateMachine:
    return ArenaStateMachine(build_templates(TEMPLATES))


def real_navigator() -> Epic7Navigator:
    """只用来跑 observe() 的真导航器（capture 不会被调用）。"""
    return Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: np.zeros((1132, 1982, 3), np.uint8), lambda _point: None),
    )


class ArenaResumeDetectionTests(unittest.TestCase):
    """认出用户停在对战的那几步。"""

    def setUp(self) -> None:
        self.machine = new_machine()

    def detect(self, name: str):
        return detect_resume_state(self.machine, arena_fixture(name))

    def test_detects_the_opponent_detail_page(self):
        self.assertEqual((ArenaState.SELECTED, "对手详情"), self.detect("selected"))

    def test_opponent_detail_wins_over_the_opponent_list(self):
        """选中对手后列表锚点仍然可见，必须优先判详情页，否则又退回列表重选一次。"""
        screen = arena_fixture("selected")

        self.assertTrue(self.machine.is_in_state(screen, ArenaState.LIST))
        self.assertEqual(ArenaState.SELECTED, self.detect("selected")[0])

    def test_detects_the_opponent_list_page(self):
        self.assertEqual((ArenaState.LIST, "对手列表"), self.detect("list"))

    def test_detects_the_team_page(self):
        for name in (
            "normal_battle_ready_live_20260826",
            "quick_battle_selected_live_20260826",
        ):
            with self.subTest(fixture=name):
                self.assertEqual((ArenaState.TEAM, "队伍选择"), self.detect(name))

    def test_ticket_purchase_popup_is_never_resumed_as_the_team_page(self):
        """买票弹窗压在队伍页上，自动战斗锚点仍可见；接力过去会直接点到弹窗上。"""
        screen = arena_fixture("friendship_ticket_offer_live_20260826")

        self.assertTrue(self.machine.is_in_state(screen, ArenaState.TEAM))
        self.assertIsNone(self.detect("friendship_ticket_offer_live_20260826"))

    def test_watch_battle_frames_are_never_mistaken_for_the_pre_battle_steps(self):
        for name in WATCH_BATTLE_FIXTURES:
            with self.subTest(fixture=name):
                self.assertIsNone(self.detect(name))

    def test_detects_the_battle_result_page(self):
        """结算页本身靠「确认」按钮 + 一个竞技场专有内容锚点共同认定。"""
        self.assertEqual((ArenaState.RESULT, "战斗结果"), self.detect("result"))

    def test_detects_the_rank_promotion_popup_as_confirming(self):
        for name in RANK_PROMOTION_FIXTURES:
            with self.subTest(fixture=name):
                self.assertEqual(
                    (ArenaState.CONFIRMING, "结果确认中"), self.detect(name)
                )

    def test_result_page_needs_the_arena_exclusive_anchor(self):
        """「确认」按钮是竞技场和远征共用的结算条，光有它不足以认定竞技场结算页。

        远征 ``result.png`` 上 ``confirm`` 实测 0.9448（高过 0.90 阈值），而两个
        竞技场专有锚点在那里分别是负相关和 0.1151。少了排他锚点就会在远征结算页上
        点确认、把远征的结算当成竞技场的接着跑。
        """
        screen = expedition_fixture("result")

        self.assertTrue(self.machine._visible(screen, "confirm"))
        self.assertFalse(self.machine._visible(screen, "result_rating"))
        self.assertFalse(self.machine._visible(screen, "result_victory"))
        self.assertIsNone(detect_resume_state(self.machine, screen))

    def test_result_anchors_are_not_visible_on_the_rank_promotion_popup(self):
        """两步互斥：段位弹窗上结算锚点不可见，结算页上晋级箭头不可见。"""
        for name in RANK_PROMOTION_FIXTURES:
            with self.subTest(fixture=name):
                screen = arena_fixture(name)
                self.assertFalse(self.machine._visible(screen, "confirm"))
                self.assertFalse(self.machine._visible(screen, "result_rating"))
                self.assertFalse(self.machine._visible(screen, "result_victory"))

        result = arena_fixture("result")
        self.assertIsNone(
            find_rank_promotion_confirm(
                result,
                self.machine.templates.rank_promotion_arrow,
                self.machine.templates.rank_confirm,
                self.machine._THRESHOLDS["rank_promotion_arrow"],
            )
        )

    def test_later_steps_never_shadow_the_earlier_ones(self):
        """新加的结果页/段位弹窗排在列表之后，但前三页锚点在这两页上都不可见。"""
        for name in ("result",) + RANK_PROMOTION_FIXTURES:
            with self.subTest(fixture=name):
                screen = arena_fixture(name)
                for state in (
                    ArenaState.LIST,
                    ArenaState.SELECTED,
                    ArenaState.TEAM,
                ):
                    self.assertFalse(self.machine.is_in_state(screen, state))


class ArenaResumePointTests(unittest.TestCase):
    """完整的接力落点：模式选择页 / 对战那几步 / 局内。"""

    def setUp(self) -> None:
        self.machine = new_machine()
        self.navigator = real_navigator()

    def detect(self, directory: Path, name: str):
        screen = _load(directory, name)
        observed = self.navigator.observe(screen).name
        return detect_resume_point(self.machine, screen, observed_page=observed)

    def test_mode_select_page_is_an_entry_resume_point(self):
        point = self.detect(NAVIGATION_FIXTURES, "arena_mode")

        self.assertEqual("竞技场模式选择", point.page)
        self.assertEqual(ARENA_ENTRY_PAGE, point.entry)
        self.assertIsNone(point.state)
        self.assertIs(ArenaState.LIST, self.machine.state)

    def test_opponent_detail_page_resumes_the_state_machine(self):
        point = self.detect(ARENA_FIXTURES, "selected")

        self.assertEqual("对手详情", point.page)
        self.assertIs(ArenaState.SELECTED, point.state)
        self.assertIsNone(point.entry)

    def test_opponent_list_page_needs_no_navigation(self):
        point = self.detect(ARENA_FIXTURES, "list")

        self.assertIs(ArenaState.LIST, point.state)
        self.assertIsNone(point.entry)

    def test_watch_battle_resumes_the_state_machine(self):
        for name in WATCH_BATTLE_FIXTURES:
            with self.subTest(fixture=name):
                self.machine = new_machine()
                point = self.detect(ARENA_FIXTURES, name)

                self.assertEqual("战斗中", point.page)
                self.assertIs(ArenaState.BATTLE, point.state)

    def test_result_page_resumes_the_state_machine(self):
        """结算页 2026-09-16 起可接力：补了竞技场专有锚点，不怕认成远征结算页。

        （此前这里断言的是 ``assertIsNone`` —— 当时 ``confirm`` 是唯一判据，
        而它和远征结算页共用，所以只能拒绝接力。）
        """
        point = self.detect(ARENA_FIXTURES, "result")

        self.assertEqual("战斗结果", point.page)
        self.assertIs(ArenaState.RESULT, point.state)
        self.assertIsNone(point.entry)

    def test_rank_promotion_popup_resumes_the_state_machine(self):
        for name in RANK_PROMOTION_FIXTURES:
            with self.subTest(fixture=name):
                self.machine = new_machine()
                point = self.detect(ARENA_FIXTURES, name)

                self.assertEqual("结果确认中", point.page)
                self.assertIs(ArenaState.CONFIRMING, point.state)
                self.assertIsNone(point.entry)

    def test_expedition_result_page_is_never_an_arena_resume_point(self):
        """跨路线回归：远征结算页的 ``confirm`` 命中竞技场阈值，必须靠排他锚点挡住。"""
        screen = expedition_fixture("result")

        self.assertIsNone(detect_resume_point(self.machine, screen))

    def test_other_routes_are_never_mistaken_for_the_arena_later_steps(self):
        """只看竞技场自己的锚点就能挡住跨路线误判，不依赖 observed_page 帮忙。"""
        for directory, names in (
            (
                EXPEDITION_FIXTURES,
                # victory_popup_live 尤其要守住：远征自己的胜利弹窗上也有大字 VICTORY，
                # 是最容易撞上竞技场 result_victory 锚点的一张。
                ("result", "outcome_public", "ready", "victory_popup_live"),
            ),
            (
                NAVIGATION_FIXTURES,
                ("lobby", "lobby_animated_updated", "story_stage"),
            ),
        ):
            for name in names:
                with self.subTest(fixture=f"{directory.name}/{name}"):
                    self.assertIsNone(
                        detect_resume_point(self.machine, _load(directory, name))
                    )

    def test_lobby_and_other_routes_are_not_resume_points(self):
        for name in ("lobby", "lobby_animated_updated", "story_stage"):
            with self.subTest(fixture=name):
                self.assertIsNone(self.detect(NAVIGATION_FIXTURES, name))


class ArenaResumeProbeTests(unittest.TestCase):
    """探针一旦命中就把状态机拨到那一步，调用方才能「接着往下跑」。"""

    def setUp(self) -> None:
        self.navigator = real_navigator()

    def probe(self, machine, directory: Path, name: str):
        screen = _load(directory, name)
        return _probe_arena_resume(machine, screen, self.navigator)

    def test_matching_frame_moves_the_machine_onto_that_step(self):
        machine = new_machine()

        point = self.probe(machine, ARENA_FIXTURES, "selected")

        self.assertEqual("对手详情", point.page)
        self.assertIs(ArenaState.SELECTED, machine.state)
        self.assertFalse(machine._cycle_pending)

    def test_entry_page_leaves_the_machine_at_the_opponent_list(self):
        machine = new_machine()

        point = self.probe(machine, NAVIGATION_FIXTURES, "arena_mode")

        self.assertEqual(ARENA_ENTRY_PAGE, point.entry)
        self.assertIs(ArenaState.LIST, machine.state)

    def test_resumed_cycle_is_not_counted_before_it_actually_finishes(self):
        machine = new_machine()

        self.probe(machine, ARENA_FIXTURES, "list")

        self.assertEqual(0, machine.completed_cycles)

    def test_result_page_probe_keeps_the_cycle_pending_for_this_run(self):
        """落在结算页：确认还没点，这一轮由本进程走完，不能提前记成已完成。"""
        machine = new_machine()

        point = self.probe(machine, ARENA_FIXTURES, "result")

        self.assertEqual("战斗结果", point.page)
        self.assertIs(ArenaState.RESULT, machine.state)
        self.assertFalse(machine._cycle_pending)
        self.assertEqual(0, machine.completed_cycles)

    def test_confirming_page_probe_credits_the_cycle_the_user_already_finished(self):
        """落在结果确认中：用户已经打完并点过确认，这一轮算完成、回到列表时 +1。"""
        machine = new_machine()

        point = self.probe(machine, ARENA_FIXTURES, "rank_confirm")

        self.assertEqual("结果确认中", point.page)
        self.assertIs(ArenaState.CONFIRMING, machine.state)
        self.assertTrue(machine._cycle_pending)
        self.assertEqual(0, machine.completed_cycles)

    def test_resuming_at_confirming_counts_exactly_one_cycle(self):
        """接力落在结果确认中、回到列表时只 +1，不会把用户那半轮算两次。"""
        machine = new_machine()
        machine.resume_from(ArenaState.CONFIRMING)

        machine.next_action(arena_fixture("list"))

        self.assertEqual(1, machine.completed_cycles)
        self.assertFalse(machine._cycle_pending)
        self.assertIs(ArenaState.LIST, machine.state)

    def test_resuming_at_the_result_page_counts_the_cycle_after_its_own_confirm(self):
        """接力落在结算页：本进程点确认 → 确认中 → 列表，这一轮同样只 +1。"""
        machine = new_machine()
        machine.resume_from(ArenaState.RESULT)

        action = machine.next_action(arena_fixture("result"))
        self.assertEqual("confirm-result", action.name)
        self.assertEqual(0, machine.completed_cycles)

        machine.commit(action, ArenaState.CONFIRMING)
        self.assertTrue(machine._cycle_pending)
        machine.next_action(arena_fixture("list"))

        self.assertEqual(1, machine.completed_cycles)
        self.assertFalse(machine._cycle_pending)

    def test_unrecognised_frame_leaves_the_machine_untouched(self):
        machine = new_machine()

        self.assertIsNone(self.probe(machine, NAVIGATION_FIXTURES, "lobby"))

        self.assertIs(ArenaState.LIST, machine.state)
        self.assertFalse(machine._cycle_pending)
        self.assertEqual(0, machine.completed_cycles)

    def test_resume_enabled_routes_expose_a_probe(self):
        """竞技场/主线/远征/刷书签各有一个接力探针，其余路线保持「一律回大厅」不变。"""
        self.assertIs(_probe_arena_resume, get_mode("arena").resume_probe)
        self.assertIsNotNone(get_mode("story").resume_probe)
        self.assertIsNotNone(get_mode("expedition").resume_probe)
        self.assertIsNotNone(get_mode("shop_refresh").resume_probe)
        for name in (
            "fodder",
            "hero_synthesis",
            "survivor",
        ):
            with self.subTest(mode=name):
                self.assertIsNone(get_mode(name).resume_probe)


class ArenaResumedBattleTests(unittest.TestCase):
    """接力直接落在局内时，必须先交给战斗监督，不能走 next_action(BATTLE)。"""

    def test_runner_hands_a_resumed_battle_to_the_supervisor(self):
        machine = new_machine()
        machine.resume_from(ArenaState.BATTLE)
        runtime = mock.MagicMock()
        supervisor = mock.MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = ArenaRunner(
            machine,
            runtime,
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=0)

        self.assertEqual(0, completed)
        supervisor.run.assert_called_once()
        self.assertIs(ArenaState.RESULT, machine.state)
        self.assertTrue(
            any("交由战斗监督等待结算" in str(call) for call in runtime.log.call_args_list)
        )

    def test_runner_does_not_touch_the_supervisor_for_a_normal_start(self):
        machine = new_machine()
        supervisor = mock.MagicMock()
        runner = ArenaRunner(
            machine,
            mock.MagicMock(),
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        runner.run(max_cycles=0)

        supervisor.run.assert_not_called()


class ArenaResumeEntryTests(unittest.TestCase):
    """开局入口：接力命中就跳过「回大厅 → 按路线导航」。"""

    def run_arena(self, screens: list[np.ndarray]):
        runtime = mock.MagicMock()
        captured: dict[str, ArenaStateMachine] = {}
        observer = real_navigator()

        def fake_return_home(*, stop_probe=None):
            """照 ``Epic7Navigator.return_home`` 的语义：每帧问一次，命中就停。"""
            for screen in screens:
                if stop_probe is not None and stop_probe(screen):
                    return screen
            return screens[-1]

        def fake_run(self, max_cycles=None):
            captured["machine"] = self.machine
            return 1

        with (
            mock.patch.object(main_module, "_build_runtime", return_value=runtime),
            mock.patch.object(main_module, "Epic7Navigator") as navigator_type,
            mock.patch.object(ArenaRunner, "run", fake_run),
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home
            navigator_type.return_value.observe.side_effect = observer.observe
            result = main_module.run_mode(
                spec=get_mode("arena"),
                dry_run=False,
                max_cycles=1,
                start_state=get_mode("arena").default_state,
            )

        return result, navigator_type.return_value, captured["machine"], runtime

    def test_opponent_detail_page_resumes_where_the_user_stopped(self):
        result, navigator, machine, runtime = self.run_arena([arena_fixture("selected")])

        self.assertEqual(1, result.completed_cycles)
        navigator.navigate.assert_not_called()
        self.assertIs(ArenaState.SELECTED, machine.state)
        runtime.save_diagnostic.assert_called_once()

    def test_team_page_resumes_straight_into_the_committed_battle(self):
        _result, navigator, machine, _runtime = self.run_arena(
            [arena_fixture("normal_battle_ready_live_20260826")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(ArenaState.TEAM, machine.state)

    def test_watch_battle_frame_resumes_instead_of_retreating_home(self):
        """老流程在局内会一直卡在「未知画面等待唤醒」直到返回大厅预算耗尽，退出码 1。"""
        _result, navigator, machine, _runtime = self.run_arena(
            [arena_fixture("battle_skill_animation_live_20260825")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(ArenaState.BATTLE, machine.state)

    def test_mode_select_page_continues_navigation_from_there(self):
        screen = navigation_fixture("arena_mode")

        _result, navigator, machine, _runtime = self.run_arena([screen])

        self.assertIs(ArenaState.LIST, machine.state)
        navigator.navigate.assert_called_once_with(
            "arena", lobby_screen=screen, already_at=ARENA_ENTRY_PAGE
        )

    def test_lobby_still_returns_home_and_navigates(self):
        lobby = navigation_fixture("lobby")

        _result, navigator, machine, runtime = self.run_arena([lobby])

        navigator.navigate.assert_called_once_with("arena", lobby_screen=lobby)
        self.assertIs(ArenaState.LIST, machine.state)
        runtime.save_diagnostic.assert_not_called()

    def test_other_route_page_keeps_returning_until_an_arena_page_shows_up(self):
        """停在别的支线页面：照旧一路返回，中途扫到竞技场页面就地接管。"""
        _result, navigator, machine, _runtime = self.run_arena(
            [
                navigation_fixture("story_stage"),
                navigation_fixture("arena_mode"),
            ]
        )

        self.assertIs(ArenaState.LIST, machine.state)
        self.assertEqual(1, navigator.navigate.call_count)

    def test_non_arena_routes_keep_calling_return_home_without_a_probe(self):
        """没接力的路线调用签名不变，行为与加这个功能之前完全一致。"""
        spec = get_mode("fodder")
        runtime = mock.MagicMock()
        lobby = navigation_fixture("lobby")
        with (
            mock.patch.object(main_module, "_build_runtime", return_value=runtime),
            mock.patch.object(main_module, "Epic7Navigator") as navigator_type,
            mock.patch(
                "auto_game_unified.games.epic7.fodder.FodderRunner.run", return_value=1
            ),
        ):
            navigator_type.return_value.return_home.return_value = lobby
            main_module.run_mode(
                spec=spec,
                dry_run=False,
                max_cycles=1,
                start_state=spec.default_state,
            )

        navigator_type.return_value.return_home.assert_called_once_with()
        navigator_type.return_value.navigate.assert_called_once_with(
            "fodder", lobby_screen=lobby
        )


class ArenaResumeNavigationGuardTests(unittest.TestCase):
    """`navigate(already_at=...)` 只认本模式声明过的接力页，不做静默降级。"""

    def test_arena_accepts_its_own_entry_page(self):
        """从模式选择页接力时，直接点「新手竞技场」，跳过大厅那一步。"""
        clicks: list[tuple[int, int]] = []
        screens = iter([navigation_fixture("arena_list")] * 12)
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(lambda: next(screens), clicks.append),
            sleep=lambda _seconds: None,
            transition_frames=8,
        )

        navigator.navigate(
            "arena",
            lobby_screen=navigation_fixture("arena_mode"),
            already_at=ARENA_ENTRY_PAGE,
        )

        self.assertEqual(1, len(clicks))
        self.assertTrue(400 <= clicks[0][0] <= 1050)
        self.assertTrue(780 <= clicks[0][1] <= 1132)

    def test_other_modes_reject_a_resume_page(self):
        for mode, page in (
            ("story", ARENA_ENTRY_PAGE),
            ("fodder", "story_ready"),
            # 远征现在接得住自己导航链上的三级；拿竞技场的入口页去试探才算越界。
            ("expedition", ARENA_ENTRY_PAGE),
        ):
            with self.subTest(mode=mode, page=page):
                navigator = real_navigator()

                with self.assertRaisesRegex(ValueError, "不支持从页面"):
                    navigator.navigate(mode, already_at=page)


if __name__ == "__main__":
    unittest.main()
