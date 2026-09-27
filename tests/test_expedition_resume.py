"""远征「接力」：开局不无脑回大厅，停在远征某一步就从那一步接着往下跑。

背景：原来的实跑入口一律「回大厅 → 战斗菜单 → 赛季菜单 → 远征主页」。用户如果已经人工
把游戏推到「准备战斗」「战斗结果」「公开招募结果」，这套流程会把它一路退回到远征主页
从第 1 步重来；停在**公开招募结果**上更亏 —— 那一步的招募还没领，回主页等于白打一场。

远征一览里的页面与接力策略：

| 页面 | 识别方式 | 接力落点 |
| --- | --- | --- |
| 大厅 / 其它路线 | `observe()`=lobby / 认不出 | 不接力，走老流程 |
| 战斗菜单 | `observe()`=battle_menu | `entry="battle_menu"`，从这里继续导航 |
| 赛季菜单 | `observe()`=season_menu | `entry="season_menu"` |
| 远征主页 | `observe()`=expedition_home 或 `home` 锚点 | 状态机 `home`，`entry="expedition_home"` |
| 通缉传单列表 | `poster_embark` | 状态机 `posters` |
| 难度选择 / 难度确认 | `difficulty_title` / `+difficulty_3_selected` | 状态机 `difficulty` / `difficulty_confirm` |
| 准备战斗（营火页） | `prepare_battle` | 状态机 `ready` |
| 队伍选择 | `battle_start` | 状态机 `team` |
| 战斗中 | `battle_scene_visible` | 状态机 `battle`，交战斗监督等结算（**不按 Back**） |
| 战斗结果 | `result_confirm` | 状态机 `result` |
| 公开招募结果 / 胜利结算 / 营地待机 | `public_recruit` / `victory_*` / `campfire_idle` | 状态机 `outcome` |
| 招募确认 | `public_title`+`public_confirm` | 状态机 `recruit_confirm` |
| 招募后返回 / 远征列表 | `public_recruited`+`back` | 状态机 `recruit_return` / `returning` |

安全边界（认错的代价必须小于收益）：
- 认不出来一律回退到老流程，行为与加这个功能之前完全一致。
- 接力进去的那半轮不算已完成轮次。
- 远征 ``next_action`` 是**纯状态驱动**的，所以接力必须把状态拨准，不能只认页面。
"""

from pathlib import Path
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified import main as main_module
from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.expedition import (
    EXPEDITION_BATTLE_MENU_PAGE,
    EXPEDITION_ENTRY_PAGE,
    EXPEDITION_SEASON_PAGE,
    ExpeditionRunner,
    ExpeditionState,
    ExpeditionStateMachine,
    detect_resume_point,
)
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
EXPEDITION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_expedition"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
EXPEDITION_TEMPLATES = TEMPLATES / "expedition"

# 远征一环夹具 -> 期望落点（页面名, 状态）。None 表示期望认不出来。
# `recruited` 与 `ready` 是同一张营火页（锚点集合完全相同），统一落 READY，见下面
# `ExpeditionResumeAmbiguityTests`。
EXPECTED_RESUME_POINTS: dict[str, tuple[str, ExpeditionState] | None] = {
    "battle.png": ("战斗中", ExpeditionState.BATTLE),
    "battle_manual_waiting_live.png": ("战斗中", ExpeditionState.BATTLE),
    "campfire_idle.png": ("公开招募结果", ExpeditionState.OUTCOME),
    "difficulty_3_selected.png": ("难度确认", ExpeditionState.DIFFICULTY_CONFIRM),
    "expedition_list.png": ("返回主页", ExpeditionState.RETURNING),
    "home.png": ("远征主页", ExpeditionState.HOME),
    "home_changed_badge.png": ("远征主页", ExpeditionState.HOME),
    "outcome_public.png": ("公开招募结果", ExpeditionState.OUTCOME),
    "outcome_public_highlighted.png": ("公开招募结果", ExpeditionState.OUTCOME),
    "posters.png": ("通缉传单列表", ExpeditionState.POSTERS),
    "public_confirm.png": ("招募确认", ExpeditionState.RECRUIT_CONFIRM),
    "ready.png": ("准备战斗", ExpeditionState.READY),
    "recruited.png": ("准备战斗", ExpeditionState.READY),
    "result.png": ("战斗结果", ExpeditionState.RESULT),
    "team.png": ("队伍选择", ExpeditionState.TEAM),
    "victory_popup_live.png": ("公开招募结果", ExpeditionState.OUTCOME),
}

# 接力后第一帧的动作（局内走战斗监督那条支路，不在这里断言）。
EXPECTED_FIRST_ACTION = {
    "battle_manual_waiting_live.png": "enable-auto-battle",
    "campfire_idle.png": "wake-campfire-ui",
    "difficulty_3_selected.png": "confirm-difficulty-3",
    "expedition_list.png": "return-to-expedition-home",
    "home.png": "open-my-posters",
    "outcome_public.png": "public-recruit",
    "posters.png": "select-first-poster",
    "public_confirm.png": "confirm-public-recruit",
    "ready.png": "prepare-battle",
    "result.png": "confirm-result",
    "team.png": "battle-start",
    "victory_popup_live.png": "close-expedition-victory",
}


def _load(directory: Path, name: str) -> np.ndarray:
    image = np.asarray(
        Image.open(directory / f"{Path(name).stem}.png").convert("RGB")
    )
    return image[:1132, :1982]


def expedition_fixture(name: str) -> np.ndarray:
    return _load(EXPEDITION_FIXTURES, name)


def navigation_fixture(name: str) -> np.ndarray:
    return _load(NAVIGATION_FIXTURES, name)


def new_machine(state: ExpeditionState = ExpeditionState.HOME) -> ExpeditionStateMachine:
    return ExpeditionStateMachine(EXPEDITION_TEMPLATES, initial_state=state)


def real_navigator() -> Epic7Navigator:
    """只用来跑 observe() 的真导航器（capture 不会被调用）。"""
    return Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: np.zeros((1132, 1982, 3), np.uint8), lambda _point: None),
    )


class ExpeditionResumeDetectionTests(unittest.TestCase):
    """全部远征夹具都要落到预期接力点。"""

    def test_every_expedition_fixture_lands_on_its_expected_resume_point(self):
        for name, expected in sorted(EXPECTED_RESUME_POINTS.items()):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), expedition_fixture(name))
                if expected is None:
                    self.assertIsNone(point)
                    continue
                self.assertIsNotNone(point)
                self.assertEqual(expected, (point.page, point.state))

    def test_only_the_navigation_chain_pages_come_from_the_navigator(self):
        """战斗菜单 / 赛季菜单不在远征状态机里，只有导航器认得出来。"""
        navigator = real_navigator()
        for name, page in (
            ("expedition_battle_menu", "战斗菜单"),
            ("expedition_season_menu", "赛季菜单"),
        ):
            with self.subTest(fixture=name):
                screen = navigation_fixture(name)
                observed = navigator.observe(screen).name

                point = detect_resume_point(new_machine(), screen, observed_page=observed)

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

    def test_expedition_home_carries_the_navigation_entry_point(self):
        for name in ("expedition_home",):
            with self.subTest(fixture=name):
                point = detect_resume_point(
                    new_machine(), navigation_fixture(name)
                )

                self.assertIs(ExpeditionState.HOME, point.state)
                self.assertEqual(EXPEDITION_ENTRY_PAGE, point.entry)

    def test_other_steps_need_no_navigation(self):
        for name in ("posters", "team", "result", "public_confirm"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), expedition_fixture(name))

                self.assertIsNone(point.entry)


class ExpeditionResumePriorityTests(unittest.TestCase):
    """顺序即优先级；远征的判据互相包含得厉害，排错就会拨到错状态。"""

    def test_outcome_beats_ready_on_the_public_recruit_page(self):
        """公开招募结果页上 `prepare_battle` 竟然也可见，READY 判据同时成立。

        先判 READY 会去点「准备战斗」，把还没领取的公开招募白扔掉。
        """
        machine = new_machine()
        screen = expedition_fixture("outcome_public")

        self.assertTrue(machine.is_in_state(screen, ExpeditionState.READY))

        point = detect_resume_point(machine, screen)

        self.assertEqual("公开招募结果", point.page)
        self.assertIs(ExpeditionState.OUTCOME, point.state)

    def test_home_beats_returning_on_the_expedition_home_page(self):
        """RETURNING 的判据第一项就是「远征主页可见」，反过来不成立。"""
        machine = new_machine()
        screen = expedition_fixture("home")

        self.assertTrue(machine.is_in_state(screen, ExpeditionState.RETURNING))

        point = detect_resume_point(machine, screen)

        self.assertEqual("远征主页", point.page)
        self.assertIs(ExpeditionState.HOME, point.state)

    def test_difficulty_confirm_beats_plain_difficulty(self):
        """`difficulty_3_selected.png` 两个判据同时成立，按项目登记表落 DIFFICULTY_CONFIRM。"""
        machine = new_machine()
        screen = expedition_fixture("difficulty_3_selected")

        self.assertTrue(machine.is_in_state(screen, ExpeditionState.DIFFICULTY))

        point = detect_resume_point(machine, screen)

        self.assertIs(ExpeditionState.DIFFICULTY_CONFIRM, point.state)

    def test_battle_frame_beats_the_result_anchor(self):
        """局内优先：`is_in_state(BATTLE)` 也吃 result_confirm，先判局内才不会被结果页抢走。"""
        for name in ("battle", "battle_manual_waiting_live"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), expedition_fixture(name))

                self.assertEqual("战斗中", point.page)
                self.assertIs(ExpeditionState.BATTLE, point.state)


class ExpeditionResumeAmbiguityTests(unittest.TestCase):
    """记录一处**机器分不开**的页面，说明为什么统一按 READY 落点。"""

    def test_ready_and_recruited_are_the_same_campfire_page(self):
        ready = expedition_fixture("ready")
        recruited = expedition_fixture("recruited")
        machine = new_machine()

        # 两张图不是同一份文件（哈希不同），但锚点可见性完全一致 → 判据无法区分。
        self.assertFalse(np.array_equal(ready, recruited))
        for state in (ExpeditionState.READY, ExpeditionState.RECRUIT_RETURN):
            with self.subTest(state=state):
                self.assertTrue(machine.is_in_state(ready, state))
                self.assertTrue(machine.is_in_state(recruited, state))

        # 统一落 READY：跟竞技场「停在准备战斗就直接打、不退回重选」同一条口径。
        # 认错也只是多打一局，不会丢奖励、不会按错 Back。
        for name in ("ready", "recruited"):
            with self.subTest(fixture=name):
                point = detect_resume_point(new_machine(), expedition_fixture(name))

                self.assertIs(ExpeditionState.READY, point.state)


class ExpeditionResumeProbeTests(unittest.TestCase):
    """探针一旦命中就把状态机拨到那一步，调用方才能「接着往下跑」。"""

    def setUp(self) -> None:
        self.navigator = real_navigator()

    def test_matching_frame_moves_the_machine_onto_that_step(self):
        machine = new_machine()

        point = get_mode("expedition").resume_probe(
            machine, expedition_fixture("team"), self.navigator
        )

        self.assertEqual("队伍选择", point.page)
        self.assertEqual(ExpeditionState.TEAM.value, point.state)
        self.assertIs(ExpeditionState.TEAM, machine.state)
        self.assertIs(ExpeditionState.TEAM, machine.resumed_from)

    def test_entry_page_moves_the_machine_onto_the_home_state(self):
        machine = new_machine(ExpeditionState.POSTERS)

        point = get_mode("expedition").resume_probe(
            machine, navigation_fixture("expedition_home"), self.navigator
        )

        self.assertEqual(EXPEDITION_ENTRY_PAGE, point.entry)
        self.assertIs(ExpeditionState.HOME, machine.state)

    def test_unrecognised_frame_leaves_the_machine_untouched(self):
        machine = new_machine()

        self.assertIsNone(
            get_mode("expedition").resume_probe(
                machine, navigation_fixture("lobby"), self.navigator
            )
        )

        self.assertIs(ExpeditionState.HOME, machine.state)
        self.assertIsNone(machine.resumed_from)

    def test_probe_survives_without_a_navigator(self):
        """导航器缺席时不该崩：业务页那部分自己就能认。"""
        machine = new_machine()

        point = get_mode("expedition").resume_probe(
            machine, expedition_fixture("posters"), None
        )

        self.assertEqual("通缉传单列表", point.page)

    def test_resume_from_clears_the_auto_click_bookkeeping(self):
        """不复位就会跳过「开自动战斗」那一次点击，手动战斗里接力过去会一直不动。"""
        machine = new_machine()
        machine.auto_click_attempted = True

        machine.resume_from(ExpeditionState.BATTLE)

        self.assertFalse(machine.auto_click_attempted)
        self.assertEqual("", machine._confirmed_page)
        self.assertIs(ExpeditionState.BATTLE, machine.resumed_from)

    def test_resumed_cycle_is_not_counted_before_it_actually_finishes(self):
        machine = new_machine()

        get_mode("expedition").resume_probe(
            machine, expedition_fixture("result"), self.navigator
        )

        self.assertEqual(0, machine.completed_cycles)

    def test_the_three_resume_enabled_routes_expose_a_probe(self):
        # 探针 2026-09-27 起由工厂 ``modes._resume_probe`` 在注册处现造 ⇒
        # 断言「注册的那个是用**本路线的判据**造的」。
        self.assertIs(
            detect_resume_point, get_mode("expedition").resume_probe.__wrapped__
        )
        self.assertIsNotNone(get_mode("arena").resume_probe)
        self.assertIsNotNone(get_mode("story").resume_probe)
        for name in ("fodder", "hero_synthesis", "survivor"):
            with self.subTest(mode=name):
                self.assertIsNone(get_mode(name).resume_probe)


class ExpeditionResumeFirstActionTests(unittest.TestCase):
    """「认得出页面」和「接得上」是两回事：远征状态拨错时 next_action 会抛错或返回 None。"""

    def test_every_resume_point_has_something_to_do_on_the_first_frame(self):
        for name, expected in sorted(EXPECTED_FIRST_ACTION.items()):
            with self.subTest(fixture=name):
                machine = new_machine()
                screen = expedition_fixture(name)
                point = detect_resume_point(machine, screen)
                machine.resume_from(point.state)

                action = machine.next_action(screen)

                self.assertIsNotNone(action)
                self.assertEqual(expected, action.name)


class ExpeditionResumedBattleTests(unittest.TestCase):
    """接力落在局内时，Runner 现有的「无动作 + BATTLE → 交战斗监督」支路必须接住。"""

    def test_resumed_battle_is_handed_to_the_supervisor(self):
        machine = new_machine(ExpeditionState.BATTLE)
        machine.resumed_from = ExpeditionState.BATTLE
        runtime = mock.MagicMock()
        runtime.dry_run = False
        runtime.capture.return_value = expedition_fixture("battle")
        supervisor = mock.MagicMock()

        def fake_run(_observe, *, cycle):
            # 模拟监督跑完一局：轮次 +1，落回结果页。
            machine.completed_cycles = 1
            return BattleOutcome.RESULT_REACHED

        supervisor.run.side_effect = fake_run
        runner = ExpeditionRunner(
            machine,
            runtime,
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=1)

        self.assertEqual(1, completed)
        supervisor.run.assert_called_once()
        self.assertEqual(1, supervisor.run.call_args.kwargs["cycle"])
        self.assertIs(ExpeditionState.RESULT, machine.state)

    def test_a_non_battle_resume_point_never_reaches_the_supervisor(self):
        """接力落在业务页（不是局内）时，第一帧拿到的是普通动作，不该交战斗监督。"""
        for name in ("home", "posters", "team", "result"):
            with self.subTest(fixture=name):
                machine = new_machine()
                screen = expedition_fixture(name)
                point = detect_resume_point(machine, screen)
                machine.resume_from(point.state)

                action = machine.next_action(screen)

                self.assertIsNotNone(action)
                self.assertIsNot(ExpeditionState.BATTLE, machine.state)


class ExpeditionResumeEntryTests(unittest.TestCase):
    """开局入口：接力命中就跳过「回大厅 → 战斗菜单 → 赛季菜单 → 远征主页」若干级。"""

    def run_expedition(self, screens: list[np.ndarray]):
        runtime = mock.MagicMock()
        captured: dict[str, ExpeditionStateMachine] = {}
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
            mock.patch.object(ExpeditionRunner, "run", fake_run),
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home
            navigator_type.return_value.observe.side_effect = observer.observe
            result = main_module.run_mode(
                spec=get_mode("expedition"),
                dry_run=False,
                max_cycles=1,
                start_state=get_mode("expedition").default_state,
            )

        return result, navigator_type.return_value, captured["machine"], runtime

    def test_expedition_home_resumes_without_re_walking_the_chain(self):
        screen = navigation_fixture("expedition_home")

        _result, navigator, machine, runtime = self.run_expedition([screen])

        navigator.navigate.assert_called_once_with(
            "expedition", lobby_screen=screen, already_at=EXPEDITION_ENTRY_PAGE
        )
        self.assertIs(ExpeditionState.HOME, machine.state)
        runtime.save_diagnostic.assert_called_once()

    def test_season_menu_resumes_from_that_step(self):
        screen = navigation_fixture("expedition_season_menu")

        _result, navigator, _machine, _runtime = self.run_expedition([screen])

        navigator.navigate.assert_called_once_with(
            "expedition", lobby_screen=screen, already_at=EXPEDITION_SEASON_PAGE
        )

    def test_battle_menu_resumes_from_that_step(self):
        screen = navigation_fixture("expedition_battle_menu")

        _result, navigator, _machine, _runtime = self.run_expedition([screen])

        navigator.navigate.assert_called_once_with(
            "expedition", lobby_screen=screen, already_at=EXPEDITION_BATTLE_MENU_PAGE
        )

    def test_public_recruit_page_resumes_instead_of_throwing_the_recruit_away(self):
        """停在公开招募结果时回主页是白打一场：招募还没领。"""
        _result, navigator, machine, _runtime = self.run_expedition(
            [expedition_fixture("public_confirm")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(ExpeditionState.RECRUIT_CONFIRM, machine.state)

    def test_watch_battle_frame_resumes_instead_of_retreating_home(self):
        _result, navigator, machine, _runtime = self.run_expedition(
            [expedition_fixture("battle_manual_waiting_live")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(ExpeditionState.BATTLE, machine.state)

    def test_lobby_still_returns_home_and_navigates(self):
        lobby = navigation_fixture("lobby")

        _result, navigator, machine, runtime = self.run_expedition([lobby])

        navigator.navigate.assert_called_once_with("expedition", lobby_screen=lobby)
        self.assertIs(ExpeditionState.HOME, machine.state)
        runtime.save_diagnostic.assert_not_called()

    def test_other_route_page_keeps_returning_until_an_expedition_page_shows_up(self):
        """停在别的支线页面：照旧一路返回，中途扫到远征页面就地接管。"""
        _result, navigator, machine, _runtime = self.run_expedition(
            [
                navigation_fixture("arena_list"),
                navigation_fixture("expedition_home"),
            ]
        )

        self.assertIs(ExpeditionState.HOME, machine.state)
        self.assertEqual(1, navigator.navigate.call_count)


class ExpeditionResumeNavigationTests(unittest.TestCase):
    """`navigate(already_at=...)` 的远征分支：只走剩下的那几级。"""

    def navigate_from(self, current: str, after: tuple[str, ...], page: str):
        """``current`` = 接力时**已经站在**的那一页；``after`` = 点击之后依次出现的帧。"""
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
        navigator.navigate(
            "expedition",
            lobby_screen=frames[0],
            already_at=page,
        )
        return clicks

    def test_expedition_home_needs_no_further_navigation(self):
        """已经在远征主页上：一次点击都不该有，尤其不能发 Back。"""
        clicks = self.navigate_from(
            "expedition_home", (), EXPEDITION_ENTRY_PAGE
        )

        self.assertEqual([], clicks)

    def test_season_menu_only_enters_the_expedition(self):
        """赛季菜单上只剩「进入远征队」一步：点一次就落到远征主页。"""
        clicks = self.navigate_from(
            "expedition_season_menu",
            ("expedition_home",) * 12,
            EXPEDITION_SEASON_PAGE,
        )

        self.assertEqual(1, len(clicks))

    def test_battle_menu_walks_the_remaining_two_steps(self):
        """战斗菜单上还有两步：先切赛季页签（赛季菜单稳定出现），再进远征队。"""
        clicks = self.navigate_from(
            "expedition_battle_menu",
            ("expedition_season_menu",) * 4 + ("expedition_home",) * 12,
            EXPEDITION_BATTLE_MENU_PAGE,
        )

        self.assertEqual(2, len(clicks))

    def test_other_modes_reject_an_expedition_resume_page(self):
        for mode in ("arena", "story", "fodder"):
            with self.subTest(mode=mode):
                navigator = real_navigator()

                with self.assertRaisesRegex(ValueError, "不支持从页面"):
                    navigator.navigate(mode, already_at=EXPEDITION_SEASON_PAGE)

    def test_expedition_rejects_a_page_outside_its_chain(self):
        navigator = real_navigator()

        with self.assertRaisesRegex(ValueError, "不支持从页面"):
            navigator.navigate("expedition", already_at="arena_mode")


if __name__ == "__main__":
    unittest.main()
