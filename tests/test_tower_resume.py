"""月塔「接力」：开局不无脑回大厅，停在月塔某一步就从那一步接着往下跑。

背景与远征同源（见 `test_expedition_resume.py`）：实跑入口原本一律
「回大厅 → 战斗菜单 → 赛季菜单 → 月塔主页」。用户如果已经人工把游戏推到
「准备战斗」「三选一」「结算页」，那套流程会把它一路退回月塔主页从第 1 步重来；
停在**三选一页**上更亏 —— 那一层的装置还没决定，退回去等于白打一层。

月塔一环里的页面与接力策略：

| 页面 | 识别方式 | 接力落点 |
| --- | --- | --- |
| 大厅 / 其它路线 | `observe()`=lobby / 认不出 | 不接力，走老流程 |
| 战斗菜单 | `observe()`=battle_menu | `entry="battle_menu"`，从这里继续导航 |
| 赛季菜单 | `observe()`=season_menu | `entry="season_menu"`（与远征共用这一屏） |
| 月塔主页 | `home_enter` | 状态机 `home`，`entry="tower_home"` |
| 楼层列表 | `floor_select_team` | 状态机 `floor_list` |
| 准备战斗 | `team_battle_start` + `prepare_title` | 状态机 `team` |
| 三选一（未选卡 / 已选卡） | `card_decide` + `card_hint` | 状态机 `card_confirm`（见下） |
| 月塔结算 | `result_clear` | 状态机 `result` |

安全边界（认错的代价必须小于收益）：
- 认不出来一律回退到老流程，行为与加这个功能之前完全一致。
- 接力进去的那半层不算已完成层数。
- 月塔 ``next_action`` 是**纯状态驱动**的，所以接力必须把状态拨准，不能只认页面。

⚠️ ``CARD`` / ``CARD_CONFIRM`` **机器分不开**（同一组判据），一律落
``CARD_CONFIRM``：那一步的动作是直接点「决定装置」，卡其实没选的话那一下打在
暗按钮上、点了无效（失败可见）；反过来先认 ``CARD`` 会**重复点一次卡**，
把用户已经选好的换成中间那张。
"""

from pathlib import Path
import unittest
from unittest import mock

import cv2
import numpy as np

from auto_game_unified import main as main_module
from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)
from auto_game_unified.games.epic7.tower import (
    TOWER_BATTLE_MENU_PAGE,
    TOWER_ENTRY_PAGE,
    TOWER_RESUME_PAGES,
    TOWER_SEASON_PAGE,
    TowerRunner,
    TowerState,
    TowerStateMachine,
    detect_resume_point,
)


ROOT = Path(__file__).resolve().parents[1]
TOWER_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_tower"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
TOWER_TEMPLATES = TEMPLATES / "tower"

# 月塔夹具 -> 期望落点（页面名, 状态）。None 表示期望认不出来。
# `season*.png` 是**还没进月塔**的赛季页：月塔的判据一个都不该在那上面命中
# （fail-closed，回退老流程）。
EXPECTED_RESUME_POINTS: dict[str, tuple[str, TowerState] | None] = {
    "home.png": ("月塔主页", TowerState.HOME),
    "home_2.png": ("月塔主页", TowerState.HOME),
    "home_alt.png": ("月塔主页", TowerState.HOME),
    "floor_list.png": ("楼层列表", TowerState.FLOOR_LIST),
    "floor_list_2.png": ("楼层列表", TowerState.FLOOR_LIST),
    "floor_list_alt.png": ("楼层列表", TowerState.FLOOR_LIST),
    "team.png": ("准备战斗", TowerState.TEAM),
    "team_next_floor.png": ("准备战斗", TowerState.TEAM),
    "card.png": ("选择装置确认", TowerState.CARD_CONFIRM),
    "card_selected.png": ("选择装置确认", TowerState.CARD_CONFIRM),
    "card_unselected.png": ("选择装置确认", TowerState.CARD_CONFIRM),
    "result.png": ("月塔结算", TowerState.RESULT),
    "season.png": None,
    "season_2.png": None,
}

# 接力后第一帧该做什么 —— 「认得出页面」和「接得上」是两回事。
EXPECTED_FIRST_ACTION = {
    "home.png": "enter-tower",
    "floor_list.png": "select-team",
    "team.png": "battle-start",
    "card_selected.png": "decide-device",
    "result.png": "next-floor",
}


def _load(directory: Path, name: str) -> np.ndarray:
    return cv2.cvtColor(
        cv2.imread(str(directory / f"{Path(name).stem}.png")), cv2.COLOR_BGR2RGB
    )


def tower_fixture(name: str) -> np.ndarray:
    return _load(TOWER_FIXTURES, name)


def navigation_fixture(name: str) -> np.ndarray:
    return _load(NAVIGATION_FIXTURES, name)


def new_machine(state: TowerState = TowerState.HOME) -> TowerStateMachine:
    return TowerStateMachine(TOWER_TEMPLATES, initial_state=state)


class _Clock:
    """假时钟：`now()` 只随 `sleep()` 前进，让超时判定可复现。

    ⚠️ 别拿 `MagicMock` 当 `Runtime` 转给 Runner：`runtime.now` 会变成
    MagicMock，`now() - state_started < timeout` 直接 `TypeError`。
    """

    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def real_navigator() -> Epic7Navigator:
    """只用来跑 observe() 的真导航器（capture 不会被调用）。"""
    return Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: np.zeros((1132, 1982, 3), np.uint8), lambda _point: None),
    )


class TowerResumeDetectionTests(unittest.TestCase):
    """全部月塔夹具都要落到预期接力点。"""

    def test_every_tower_fixture_lands_on_its_expected_resume_point(self):
        for name, expected in sorted(EXPECTED_RESUME_POINTS.items()):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), tower_fixture(name))
                if expected is None:
                    self.assertIsNone(point)
                    continue
                self.assertIsNotNone(point)
                self.assertEqual(expected, (point.page, point.state))

    def test_only_the_navigation_chain_pages_come_from_the_navigator(self):
        """战斗菜单 / 赛季菜单不在月塔状态机里，只有导航器认得出来。"""
        navigator = real_navigator()
        for name, page in (
            ("expedition_battle_menu", "战斗菜单"),
            ("expedition_season_menu", "赛季菜单"),
        ):
            with self.subTest(fixture=name):
                screen = navigation_fixture(name)
                observed = navigator.observe(screen).name

                point = detect_resume_point(
                    new_machine(), screen, observed_page=observed
                )

                self.assertEqual(page, point.page)
                self.assertEqual(observed, point.entry)
                self.assertIsNone(point.state)

    def test_navigation_chain_pages_need_the_navigator_hint(self):
        """不给导航器提示时，战斗菜单/赛季菜单认不出来（失败关闭，落回老流程）。"""
        for name in ("expedition_battle_menu", "expedition_season_menu"):
            with self.subTest(fixture=name):
                self.assertIsNone(
                    detect_resume_point(new_machine(), navigation_fixture(name))
                )

    def test_foreign_pages_are_not_resume_points(self):
        for name in ("lobby", "arena_list", "story_stage"):
            with self.subTest(fixture=name):
                self.assertIsNone(
                    detect_resume_point(new_machine(), navigation_fixture(name))
                )

    def test_tower_home_carries_the_navigation_entry_point(self):
        point = detect_resume_point(new_machine(), tower_fixture("home"))

        self.assertIs(TowerState.HOME, point.state)
        self.assertEqual(TOWER_ENTRY_PAGE, point.entry)

    def test_other_steps_need_no_navigation(self):
        for name in ("floor_list", "team", "card_selected", "result"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), tower_fixture(name))

                self.assertIsNone(point.entry)


class TowerResumePriorityTests(unittest.TestCase):
    """顺序即优先级；拨错状态就会点错按钮。"""

    def test_home_wins_before_anything_else(self):
        """月塔主页上有「入场」，而 `home` 排第一位。"""
        machine = new_machine()
        screen = tower_fixture("home")

        point = detect_resume_point(machine, screen)

        self.assertEqual("月塔主页", point.page)
        self.assertIs(TowerState.HOME, point.state)

    def test_team_beats_floor_list_on_the_team_page(self):
        """准备战斗页上两枚判据都成立的可能：先认 TEAM，才符合「接着打这一层」。"""
        machine = new_machine()
        screen = tower_fixture("team")

        self.assertTrue(machine.is_in_state(screen, TowerState.TEAM))

        point = detect_resume_point(machine, screen)

        self.assertIs(TowerState.TEAM, point.state)

    def test_result_beats_battle_on_the_result_page(self):
        """结算页上 `battle_visible` 也可能为真（背景仍是战场），先认结算页。"""
        machine = new_machine()
        screen = tower_fixture("result")

        self.assertTrue(machine.is_in_state(screen, TowerState.BATTLE))

        point = detect_resume_point(machine, screen)

        self.assertEqual("月塔结算", point.page)
        self.assertIs(TowerState.RESULT, point.state)

    def test_card_confirm_beats_plain_card_on_every_card_frame(self):
        """三张卡页（未选 / 已选 / 第三张）判据完全相同 ⇒ 一律落 CARD_CONFIRM。"""
        for name in ("card", "card_unselected", "card_selected"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), tower_fixture(name))

                self.assertIs(TowerState.CARD_CONFIRM, point.state)


class TowerResumeAmbiguityTests(unittest.TestCase):
    """记录一处**机器分不开**的页面，说明为什么统一按 CARD_CONFIRM 落点。"""

    def test_card_and_card_confirm_are_the_same_page(self):
        unselected = tower_fixture("card_unselected")
        selected = tower_fixture("card_selected")
        machine = new_machine()

        # 两张图不是同一份文件（哈希不同），但锚点可见性完全一致 → 判据无法区分。
        self.assertFalse(np.array_equal(unselected, selected))
        for state in (TowerState.CARD, TowerState.CARD_CONFIRM):
            with self.subTest(state=state):
                self.assertTrue(machine.is_in_state(unselected, state))
                self.assertTrue(machine.is_in_state(selected, state))

        # 统一落 CARD_CONFIRM：动作是直接点「决定装置」。卡其实没选的话那一下
        # 打在暗按钮上、点了无效（失败可见），比「重复点卡把已选的换掉」安全。
        for name in ("card", "card_unselected", "card_selected"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), tower_fixture(name))

                self.assertIs(TowerState.CARD_CONFIRM, point.state)


class TowerResumeProbeTests(unittest.TestCase):
    """探针一旦命中就把状态机拨到那一步，调用方才能「接着往下跑」。"""

    def setUp(self) -> None:
        self.navigator = real_navigator()

    def test_matching_frame_moves_the_machine_onto_that_step(self):
        machine = new_machine()

        point = get_mode("tower").resume_probe(
            machine, tower_fixture("team"), self.navigator
        )

        self.assertEqual("准备战斗", point.page)
        self.assertEqual(TowerState.TEAM.value, point.state)
        self.assertIs(TowerState.TEAM, machine.state)
        self.assertIs(TowerState.TEAM, machine.resumed_from)

    def test_entry_page_moves_the_machine_onto_the_home_state(self):
        machine = new_machine(TowerState.FLOOR_LIST)

        point = get_mode("tower").resume_probe(
            machine, tower_fixture("home"), self.navigator
        )

        self.assertEqual(TOWER_ENTRY_PAGE, point.entry)
        self.assertIs(TowerState.HOME, machine.state)

    def test_unrecognised_frame_leaves_the_machine_untouched(self):
        machine = new_machine()

        self.assertIsNone(
            get_mode("tower").resume_probe(
                machine, navigation_fixture("lobby"), self.navigator
            )
        )

        self.assertIs(TowerState.HOME, machine.state)
        self.assertIsNone(machine.resumed_from)

    def test_probe_survives_without_a_navigator(self):
        """导航器缺席时不该崩：业务页那部分自己就能认。"""
        machine = new_machine()

        point = get_mode("tower").resume_probe(
            machine, tower_fixture("floor_list"), None
        )

        self.assertEqual("楼层列表", point.page)

    def test_resume_from_clears_the_per_floor_bookkeeping(self):
        """不复位就会跳过「点中间卡」那一次点击 —— 落在三选一页上会一直不动。"""
        machine = new_machine()
        machine.auto_click_attempted = True
        machine.card_picked = True

        machine.resume_from(TowerState.CARD_CONFIRM)

        self.assertFalse(machine.auto_click_attempted)
        self.assertFalse(machine.card_picked)
        self.assertEqual("", machine._confirmed_page)
        self.assertIs(TowerState.CARD_CONFIRM, machine.resumed_from)

    def test_resumed_floor_is_not_counted_before_it_actually_finishes(self):
        machine = new_machine()

        get_mode("tower").resume_probe(
            machine, tower_fixture("result"), self.navigator
        )

        self.assertEqual(0, machine.completed_cycles)

    def test_the_probe_is_built_from_this_route_own_judge(self):
        # 探针由工厂 ``modes._resume_probe`` 在注册处现造 ⇒
        # 断言「注册的那个是用**本路线的判据**造的」。
        self.assertIs(
            detect_resume_point, get_mode("tower").resume_probe.__wrapped__
        )


class TowerResumeFirstActionTests(unittest.TestCase):
    """「认得出页面」和「接得上」是两回事：状态拨错时 next_action 会抛错或返回 None。"""

    def test_every_resume_point_has_something_to_do_on_the_first_frame(self):
        for name, expected in sorted(EXPECTED_FIRST_ACTION.items()):
            with self.subTest(fixture=name):
                machine = new_machine()
                screen = tower_fixture(name)
                point = detect_resume_point(machine, screen)
                machine.resume_from(point.state)

                action = machine.next_action(screen)

                self.assertIsNotNone(action)
                self.assertEqual(expected, action.name)

    def test_resumed_card_confirm_page_goes_straight_to_decide(self):
        """⚠️ 落在三选一页时**不许**再点一次卡 —— 会覆盖用户已经选好的那张。"""
        machine = new_machine()
        screen = tower_fixture("card_selected")
        point = detect_resume_point(machine, screen)
        machine.resume_from(point.state)

        action = machine.next_action(screen)

        self.assertEqual("decide-device", action.name)
        self.assertEqual((1138, 1040), action.point)


class TowerResumedBattleTests(unittest.TestCase):
    """接力落在局内时，Runner 现有的「无动作 + BATTLE → 交战斗监督」支路必须接住。"""

    def test_resumed_battle_is_handed_to_the_supervisor(self):
        clock = _Clock()
        clicks: list[tuple[int, int]] = []
        machine = new_machine(TowerState.BATTLE)
        machine.resumed_from = TowerState.BATTLE
        supervisor = mock.MagicMock()

        def fake_run(_observe, *, cycle):
            # 模拟监督跑完一层：轮次 +1，落回三选一页。
            machine.completed_cycles = 1
            return BattleOutcome.RESULT_REACHED

        supervisor.run.side_effect = fake_run
        runner = TowerRunner(
            machine,
            Runtime(lambda: tower_fixture("card_unselected"), clicks.append),
            sleep=clock.sleep,
            poll_seconds=1,
            now=clock.now,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        supervisor.run.assert_called_once()
        self.assertEqual(1, supervisor.run.call_args.kwargs["cycle"])
        self.assertIs(TowerState.CARD, machine.state)


class TowerResumeEntryTests(unittest.TestCase):
    """开局入口：接力命中就跳过「回大厅 → 战斗菜单 → 赛季菜单 → 月塔主页」若干级。"""

    def run_tower(self, screens: list[np.ndarray]):
        runtime = mock.MagicMock()
        captured: dict[str, TowerStateMachine] = {}
        observer = real_navigator()

        def fake_return_home(*, stop_probe=None):
            """照 `Epic7Navigator.return_home` 的语义：每帧问一次，命中就停。"""
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
            mock.patch.object(TowerRunner, "run", fake_run),
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home
            navigator_type.return_value.observe.side_effect = observer.observe
            result = main_module.run_mode(
                spec=get_mode("tower"),
                dry_run=False,
                max_cycles=1,
                start_state=get_mode("tower").default_state,
            )

        return result, navigator_type.return_value, captured["machine"], runtime

    def test_tower_home_resumes_without_re_walking_the_chain(self):
        screen = tower_fixture("home")

        _result, navigator, machine, runtime = self.run_tower([screen])

        navigator.navigate.assert_called_once_with(
            "tower", lobby_screen=screen, already_at=TOWER_ENTRY_PAGE
        )
        self.assertIs(TowerState.HOME, machine.state)
        runtime.save_diagnostic.assert_called_once()

    def test_season_menu_resumes_from_that_step(self):
        screen = navigation_fixture("expedition_season_menu")

        _result, navigator, _machine, _runtime = self.run_tower([screen])

        navigator.navigate.assert_called_once_with(
            "tower", lobby_screen=screen, already_at=TOWER_SEASON_PAGE
        )

    def test_battle_menu_resumes_from_that_step(self):
        screen = navigation_fixture("expedition_battle_menu")

        _result, navigator, _machine, _runtime = self.run_tower([screen])

        navigator.navigate.assert_called_once_with(
            "tower", lobby_screen=screen, already_at=TOWER_BATTLE_MENU_PAGE
        )

    def test_card_page_resumes_instead_of_throwing_the_floor_away(self):
        """停在三选一页时回主页是白打一层：装置还没决定。"""
        _result, navigator, machine, _runtime = self.run_tower(
            [tower_fixture("card_selected")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(TowerState.CARD_CONFIRM, machine.state)

    def test_result_page_resumes_instead_of_retreating_home(self):
        _result, navigator, machine, _runtime = self.run_tower(
            [tower_fixture("result")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(TowerState.RESULT, machine.state)

    def test_lobby_still_returns_home_and_navigates(self):
        lobby = navigation_fixture("lobby")

        _result, navigator, machine, runtime = self.run_tower([lobby])

        navigator.navigate.assert_called_once_with("tower", lobby_screen=lobby)
        self.assertIs(TowerState.HOME, machine.state)
        runtime.save_diagnostic.assert_not_called()

    def test_other_route_page_keeps_returning_until_a_tower_page_shows_up(self):
        """停在别的支线页面：照旧一路返回，中途扫到月塔页面就地接管。

        ⚠️ 断言的是**结果**（状态拨到 TEAM、且没走完整导航）而不是
        ``navigate`` 的调用次数 —— 命中接力之后 `run_mode` 就不该再导航了，
        调用次数是 0，把 1 写死等于把「接力生效」当成失败。
        """
        _result, navigator, machine, _runtime = self.run_tower(
            [
                navigation_fixture("arena_list"),
                tower_fixture("team"),
            ]
        )

        self.assertIs(TowerState.TEAM, machine.state)
        navigator.navigate.assert_not_called()


class TowerResumeNavigationTests(unittest.TestCase):
    """`navigate(already_at=...)` 的月塔分支：只走剩下的那几级。"""

    def navigate_from(self, current: str, after: tuple[str, ...], page: str):
        """`current` = 接力时**已经站在**的那一页；`after` = 点击之后依次出现的帧。"""
        frames = [navigation_fixture(current)] + [
            navigation_fixture(name) for name in after
        ]
        clicks: list[tuple[int, int]] = []
        sequence = iter(frames)
        last: list[np.ndarray] = []

        def capture() -> np.ndarray:
            try:
                screen = next(sequence)
            except StopIteration:
                screen = last[-1]
            last.append(screen)
            return screen

        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(capture, clicks.append),
            sleep=lambda _seconds: None,
            transition_frames=8,
        )
        navigator.navigate("tower", lobby_screen=frames[0], already_at=page)
        return clicks

    def test_tower_home_needs_no_further_navigation(self):
        """已经在月塔主页上：一次点击都不该有，尤其不能发 Back。"""
        clicks = self.navigate_from("expedition_home", (), TOWER_ENTRY_PAGE)

        self.assertEqual([], clicks)

    def test_other_modes_reject_a_tower_resume_page(self):
        """别的路线不许借用月塔的接力白名单。

        ⚠️ `expedition` **不在**这个名单里：月塔与远征**共用赛季菜单**这一屏，
        所以 `season_menu` 对远征本来就是合法的接力点（它自己的链上也有一级）。
        真正专属月塔的是 `tower_home`。
        """
        for mode in ("arena", "story", "fodder"):
            with self.subTest(mode=mode):
                navigator = real_navigator()

                with self.assertRaisesRegex(ValueError, "不支持从页面"):
                    navigator.navigate(mode, already_at=TOWER_ENTRY_PAGE)

    def test_season_menu_is_legitimately_shared_with_expedition(self):
        """赛季菜单是**两条路线共用的**那一屏，两边都该接受它 —— 这不是泄漏。"""
        from auto_game_unified.games.epic7.expedition import EXPEDITION_RESUME_PAGES

        self.assertIn(TOWER_SEASON_PAGE, EXPEDITION_RESUME_PAGES)
        self.assertIn(TOWER_SEASON_PAGE, TOWER_RESUME_PAGES)
        # 而 `tower_home` 是月塔**专属**的，远征的白名单里不许有它。
        self.assertNotIn(TOWER_ENTRY_PAGE, EXPEDITION_RESUME_PAGES)

    def test_tower_rejects_a_page_outside_its_chain(self):
        navigator = real_navigator()

        with self.assertRaisesRegex(ValueError, "不支持从页面"):
            navigator.navigate("tower", already_at="arena_mode")


if __name__ == "__main__":
    unittest.main()
