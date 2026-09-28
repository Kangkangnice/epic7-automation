"""主线「接力」：开局不无脑回大厅，停在主线某一步就从那一步接着往下跑。

背景：原来的实跑入口一律「回大厅 → 从主线入口重新导航」。用户如果已经人工把游戏推到
队伍准备/剧情播放/结算/通关提示，这套流程会把当前这一局的进度整段丢掉 —— 最亏的是停在
**结算页**：那一步的奖励还没点，回大厅等于白打一场。

主线一环里的页面与接力策略：

| 页面 | 识别方式 | 接力落点 |
| --- | --- | --- |
| 大厅 | `observe()`=lobby | 不接力，走老流程 |
| 关卡入口 / 剧情关卡入口 | `observe()`=story_ready 或 `prepare_battle`/`watch_story` | `stage`，`entry="story_ready"`（已在导航链终点，不重进） |
| 队伍准备 | `start_mission` | `team` |
| 助手选择 | `select_team` | `team` |
| 跳过确认 | `skip_confirm` | `wait_skip_confirm` |
| 剧情播放 | `skip` | `active` |
| 战斗中 | `battle_scene_visible` | `wait_battle`，交战斗监督等结算（**不按 Back**） |
| 奖励结算 / 通关结算 | `reward` / `clear` | `wait_results` |
| 结算确认 | `results_confirm` | `wait_results` |
| 通关提示 | `complete` | `wait_complete` |
| 额外奖励 | `bonus_reward` | `wait_next_stage` |
| 下一关入口 | `next_stage` | `wait_next_stage` |
| 战斗指南弹窗 / 体力弹窗 / 无关弹窗 | 无锚点 | 不接力；弹窗交给全局弹窗守卫 |

安全边界（认错的代价必须小于收益）：
- 认不出来一律回退到老流程，行为与加这个功能之前完全一致。
- 接力进去的那半轮不算已完成轮次。
- 局内接力不分路线，停在别的路线战斗里也会先把这一局监督完再回大厅。
"""

from pathlib import Path
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified import main as main_module
from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.modes import get_mode
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)
from auto_game_unified.games.epic7.story import (
    STORY_ENTRY_PAGE,
    StoryRunner,
    StoryState,
    StoryStateMachine,
    build_story_templates,
    detect_resume_point,
)


ROOT = Path(__file__).resolve().parents[1]
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
NAVIGATION_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
STORY_TEMPLATES = TEMPLATES / "story"

# 夹具 -> 期望落点（页面名, 状态）。None 表示期望认不出来。
EXPECTED_RESUME_POINTS: dict[str, tuple[str, StoryState] | None] = {
    "assistant.png": ("助手选择", StoryState.TEAM),
    "assistant_live_20260809.png": ("助手选择", StoryState.TEAM),
    "battle.png": ("战斗中", StoryState.WAIT_BATTLE),
    "battle_auto_off_live_20260809.png": ("战斗中", StoryState.WAIT_BATTLE),
    "battle_auto_on_live_20260809.png": ("战斗中", StoryState.WAIT_BATTLE),
    "battle_auto_skill_cooldown_live_20260818.png": ("战斗中", StoryState.WAIT_BATTLE),
    "battle_guide_warning_live_20260815.png": None,
    "battle_manual_skill_variant_live_20260815.png": ("战斗中", StoryState.WAIT_BATTLE),
    "battle_variant.png": None,
    "bonus_reward.png": ("额外奖励", StoryState.WAIT_NEXT_STAGE),
    "clear.png": ("通关结算", StoryState.WAIT_RESULTS),
    "complete.png": ("通关提示", StoryState.WAIT_COMPLETE),
    "friend_request.png": None,
    "friendship_points_popup.png": None,
    "next_stage.png": ("关卡入口", StoryState.STAGE),
    "results.png": ("结算确认", StoryState.WAIT_RESULTS),
    "reward.png": ("奖励结算", StoryState.WAIT_RESULTS),
    "skill_animation_live_20260813.png": ("战斗中", StoryState.WAIT_BATTLE),
    "skip_confirm.png": ("跳过确认", StoryState.WAIT_SKIP_CONFIRM),
    "skip_confirm_persisted_live_20260813.png": ("跳过确认", StoryState.WAIT_SKIP_CONFIRM),
    "stage.png": ("关卡入口", StoryState.STAGE),
    "stage_battle_ready_updated.png": ("关卡入口", StoryState.STAGE),
    "stage_prepare_battle_ep5.png": ("关卡入口", StoryState.STAGE),
    "stage_variant.png": ("关卡入口", StoryState.STAGE),
    "stamina_popup_after_start_live_20260815.png": None,
    "stamina_popup_live_20260809.png": None,
    "story.png": ("剧情播放", StoryState.ACTIVE),
    "story_variant.png": ("剧情播放", StoryState.ACTIVE),
    "story_watch_next_ep4.png": ("剧情关卡入口", StoryState.STAGE),
    "story_watch_ready_live_20260810.png": ("剧情关卡入口", StoryState.STAGE),
    "team.png": ("队伍准备", StoryState.TEAM),
    "team_live_20260809.png": ("队伍准备", StoryState.TEAM),
    # 换皮后的队伍准备页（绿「战斗开始」）同样要能接力，别只顾着运行期。
    "team_live_20260917.png": ("队伍准备", StoryState.TEAM),
}

# 接力后第一帧必须有动作的页面（局内走战斗监督，不走 next_action）。
EXPECTED_FIRST_ACTION = {
    "assistant_live_20260809.png": "select_team",
    "bonus_reward.png": "bonus_reward",
    "clear.png": "clear",
    "complete.png": "complete",
    "next_stage.png": "prepare_battle",
    "results.png": "results_confirm",
    "reward.png": "reward",
    "skip_confirm.png": "skip_confirm",
    "stage.png": "prepare_battle",
    "story.png": "skip",
    "story_watch_ready_live_20260810.png": "watch_story",
    "team_live_20260809.png": "start_mission",
    "team_live_20260917.png": "start_mission",
}


def _load(directory: Path, name: str) -> np.ndarray:
    # 兼容带不带 .png 后缀的两种写法；旧基准 3200x2000 的夹具裁左上角当基准帧。
    image = np.asarray(
        Image.open(directory / f"{Path(name).stem}.png").convert("RGB")
    )
    return image[:1132, :1982]


def story_fixture(name: str) -> np.ndarray:
    return _load(STORY_FIXTURES, name)


def navigation_fixture(name: str) -> np.ndarray:
    return _load(NAVIGATION_FIXTURES, name)


def new_machine() -> StoryStateMachine:
    return StoryStateMachine(
        build_story_templates(STORY_TEMPLATES)
    )


def real_navigator() -> Epic7Navigator:
    """只用来跑 observe() 的真导航器（capture 不会被调用）。"""
    return Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: np.zeros((1132, 1982, 3), np.uint8), lambda _point: None),
    )


class StoryResumeDetectionTests(unittest.TestCase):
    """全部主线夹具都要落到预期接力点（正例认得出、负例不误认）。"""

    def test_every_story_fixture_lands_on_its_expected_resume_point(self):
        for name, expected in sorted(EXPECTED_RESUME_POINTS.items()):
            with self.subTest(fixture=name):
                machine = new_machine()
                point = detect_resume_point(machine, story_fixture(name))
                if expected is None:
                    self.assertIsNone(point)
                    continue
                self.assertIsNotNone(point)
                self.assertEqual(expected, (point.page, point.state))

    def test_lobby_is_not_a_resume_point(self):
        for name in ("lobby", "lobby_animated_updated"):
            with self.subTest(fixture=name):
                self.assertIsNone(
                    detect_resume_point(self.machine(), navigation_fixture(name))
                )

    @staticmethod
    def machine() -> StoryStateMachine:
        return new_machine()

    def test_entry_page_is_resumed_from_the_story_ready_page(self):
        """关卡入口和剧情关卡入口是同一张图上的两个按钮，都落在 STORY_ENTRY_PAGE。"""
        for name, label in (
            ("stage", "关卡入口"),
            ("stage_battle_ready_updated", "关卡入口"),
            ("story_watch_ready_live_20260810", "剧情关卡入口"),
            ("story_watch_next_ep4", "剧情关卡入口"),
        ):
            with self.subTest(fixture=name):
                point = detect_resume_point(self.machine(), story_fixture(name))

                self.assertEqual(label, point.page)
                self.assertEqual(STORY_ENTRY_PAGE, point.entry)

    def test_steps_past_the_entry_page_need_no_navigation(self):
        for name in ("team_live_20260809", "results", "reward", "complete"):
            with self.subTest(fixture=name):
                point = detect_resume_point(self.machine(), story_fixture(name))

                self.assertIsNone(point.entry)


class StoryResumePriorityTests(unittest.TestCase):
    """顺序即优先级，这三条边界一旦排错就会退化成「原地干等到超时」。"""

    def test_stage_entry_wins_over_next_stage(self):
        """`next_stage` 和 `prepare_battle` 同时出现在关卡入口页上。

        实测 `next_stage.png` 上 prepare_battle=0.9793、`stage.png` 上 next_stage=0.9352。
        若先判 next_stage 就会落成 wait_next_stage，而 `next_action` 在 WAIT_NEXT_STAGE
        下碰到 `prepare_battle` 只记轮次不点击。
        """
        machine = new_machine()
        screen = story_fixture("stage")

        self.assertIsNotNone(machine._locate(screen, "next_stage"))
        self.assertIsNotNone(machine._locate(screen, "prepare_battle"))

        point = detect_resume_point(machine, screen)

        self.assertEqual("关卡入口", point.page)
        self.assertIs(StoryState.STAGE, point.state)

    def test_complete_wins_over_next_stage(self):
        """通关提示页上两者同时可见（完整实测 1.0000 / 0.9780）。"""
        machine = new_machine()
        screen = story_fixture("complete")

        self.assertIsNotNone(machine._locate(screen, "next_stage"))

        point = detect_resume_point(machine, screen)

        self.assertEqual("通关提示", point.page)
        self.assertIs(StoryState.WAIT_COMPLETE, point.state)

    def test_battle_frame_wins_over_the_auto_off_icon(self):
        """局内 `auto_off` 能到 0.9857（`battle_variant`），必须先判局内。"""
        for name in ("battle_auto_off_live_20260809", "battle_manual_skill_variant_live_20260815"):
            with self.subTest(fixture=name):
                machine = new_machine()
                screen = story_fixture(name)

                self.assertIsNotNone(machine._locate(screen, "auto_off"))
                point = detect_resume_point(machine, screen)

                self.assertEqual("战斗中", point.page)
                self.assertIs(StoryState.WAIT_BATTLE, point.state)


class StoryResumeProbeTests(unittest.TestCase):
    """探针一旦命中就把状态机拨到那一步，调用方才能「接着往下跑」。"""

    def setUp(self) -> None:
        self.navigator = real_navigator()

    def test_matching_frame_moves_the_machine_onto_that_step(self):
        machine = new_machine()

        point = get_mode("story").resume_probe(
            machine, story_fixture("team_live_20260809"), self.navigator
        )

        self.assertEqual("队伍准备", point.page)
        self.assertEqual(StoryState.TEAM.value, point.state)
        self.assertIs(StoryState.TEAM, machine.state)
        self.assertIs(StoryState.TEAM, machine.resumed_from)

    def test_entry_page_moves_the_machine_to_the_stage_state(self):
        machine = new_machine()

        point = get_mode("story").resume_probe(
            machine, story_fixture("stage"), self.navigator
        )

        self.assertEqual(STORY_ENTRY_PAGE, point.entry)
        self.assertIs(StoryState.STAGE, machine.state)

    def test_unrecognised_frame_leaves_the_machine_untouched(self):
        machine = new_machine()

        self.assertIsNone(
            get_mode("story").resume_probe(
                machine, navigation_fixture("lobby"), self.navigator
            )
        )

        self.assertIs(StoryState.STAGE, machine.state)
        self.assertIsNone(machine.resumed_from)

    def test_probe_survives_without_a_navigator(self):
        """导航器缺席时不该崩：锚点那部分自己就能认。"""
        machine = new_machine()

        point = get_mode("story").resume_probe(machine, story_fixture("reward"), None)

        self.assertEqual("奖励结算", point.page)

    def test_resumed_cycle_is_not_counted_before_it_actually_finishes(self):
        machine = new_machine()

        get_mode("story").resume_probe(machine, story_fixture("results"), self.navigator)

        self.assertEqual(0, machine.completed_cycles)

    def test_only_arena_story_and_expedition_expose_a_probe(self):
        # 探针 2026-09-27 起由工厂 ``modes._resume_probe`` 在注册处现造 ⇒
        # 断言「注册的那个是用**本路线的判据**造的」。
        self.assertIs(detect_resume_point, get_mode("story").resume_probe.__wrapped__)
        self.assertIsNotNone(get_mode("arena").resume_probe)
        self.assertIsNotNone(get_mode("expedition").resume_probe)
        for name in ("fodder", "hero_synthesis", "survivor"):
            with self.subTest(mode=name):
                self.assertIsNone(get_mode(name).resume_probe)


class StoryResumeFirstActionTests(unittest.TestCase):
    """「认得出页面」和「接得上」是两回事：拨错状态时 next_action 会返回 None。"""

    def test_every_resume_point_has_something_to_do_on_the_first_frame(self):
        for name, expected in sorted(EXPECTED_FIRST_ACTION.items()):
            with self.subTest(fixture=name):
                machine = new_machine()
                point = detect_resume_point(machine, story_fixture(name))
                machine.resume_from(point.state)

                action = machine.next_action(story_fixture(name))

                self.assertIsNotNone(action)
                self.assertEqual(expected, action.name)

    def test_resume_from_clears_the_previous_battle_bookkeeping(self):
        machine = new_machine()
        machine.auto_click_attempted = True
        machine.auto_enabled = True

        machine.resume_from(StoryState.WAIT_RESULTS)

        self.assertIs(StoryState.WAIT_RESULTS, machine.state)
        self.assertIs(StoryState.WAIT_RESULTS, machine.resumed_from)
        self.assertFalse(machine.auto_click_attempted)
        self.assertFalse(machine.auto_enabled)
        self.assertEqual("", machine._confirmed_page)


class StoryResumedBattleTests(unittest.TestCase):
    """接力直接落在局内时，必须先交给战斗监督，不能走 next_action。"""

    def make_runtime(self) -> mock.MagicMock:
        runtime = mock.MagicMock()
        runtime.dry_run = False
        return runtime

    def test_runner_hands_a_resumed_battle_to_the_supervisor(self):
        machine = new_machine()
        machine.resume_from(StoryState.WAIT_BATTLE)
        runtime = self.make_runtime()
        supervisor = mock.MagicMock()
        supervisor.run.return_value = BattleOutcome.RESULT_REACHED
        runner = StoryRunner(
            machine,
            runtime,
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=0)

        self.assertEqual(0, completed)
        supervisor.run.assert_called_once()
        self.assertIs(StoryState.WAIT_RESULTS, machine.state)
        self.assertTrue(
            any(
                "交由战斗监督等待结算" in str(call)
                for call in runtime.log.call_args_list
            )
        )

    def test_runner_keeps_the_pre_battle_business_loop_when_the_supervisor_bounces_back(self):
        """体力弹窗这类战前业务：监督交还业务，状态回到 wait_battle，不结束整轮。"""
        machine = new_machine()
        machine.resume_from(StoryState.WAIT_BATTLE)
        supervisor = mock.MagicMock()
        supervisor.run.return_value = BattleOutcome.PRE_BATTLE_BUSINESS
        runner = StoryRunner(
            machine,
            self.make_runtime(),
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        runner.run(max_cycles=0)

        self.assertIs(StoryState.WAIT_BATTLE, machine.state)

    def test_runner_does_not_touch_the_supervisor_for_a_normal_start(self):
        machine = new_machine()
        supervisor = mock.MagicMock()
        runner = StoryRunner(
            machine,
            self.make_runtime(),
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        runner.run(max_cycles=0)

        supervisor.run.assert_not_called()

    def test_dry_run_never_runs_the_battle_supervisor(self):
        """空跑只观察：就算状态机带着「局内接力」的标记，也不许真的去监督战斗。"""
        machine = new_machine()
        machine.resume_from(StoryState.WAIT_BATTLE)
        runtime = self.make_runtime()
        runtime.dry_run = True
        runtime.capture.return_value = story_fixture("team_live_20260809")
        supervisor = mock.MagicMock()
        runner = StoryRunner(
            machine,
            runtime,
            sleep=lambda _seconds: None,
            battle_supervisor=supervisor,
        )

        completed = runner.run(max_cycles=0)

        self.assertEqual(0, completed)
        supervisor.run.assert_not_called()


class StoryResumeEntryTests(unittest.TestCase):
    """开局入口：接力命中就跳过「回大厅 → 从主线入口重新导航」。"""

    def run_story(self, screens: list[np.ndarray]):
        runtime = mock.MagicMock()
        captured: dict[str, StoryStateMachine] = {}
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
            mock.patch.object(StoryRunner, "run", fake_run),
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home
            navigator_type.return_value.observe.side_effect = observer.observe
            result = main_module.run_mode(
                spec=get_mode("story"),
                dry_run=False,
                max_cycles=1,
                start_state=get_mode("story").default_state,
            )

        return result, navigator_type.return_value, captured["machine"], runtime

    def test_stage_entry_resumes_without_re_entering_the_story_menu(self):
        screen = story_fixture("stage_battle_ready_updated")

        _result, navigator, machine, runtime = self.run_story([screen])

        navigator.navigate.assert_called_once_with(
            "story", lobby_screen=screen, already_at=STORY_ENTRY_PAGE
        )
        self.assertIs(StoryState.STAGE, machine.state)
        runtime.save_diagnostic.assert_called_once()

    def test_team_page_resumes_straight_into_the_committed_battle(self):
        _result, navigator, machine, _runtime = self.run_story(
            [story_fixture("team_live_20260809")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(StoryState.TEAM, machine.state)

    def test_result_page_resumes_instead_of_throwing_the_rewards_away(self):
        """停在结算页时回大厅等于白打一场：奖励还没点。"""
        _result, navigator, machine, _runtime = self.run_story([story_fixture("results")])

        navigator.navigate.assert_not_called()
        self.assertIs(StoryState.WAIT_RESULTS, machine.state)

    def test_watch_battle_frame_resumes_instead_of_retreating_home(self):
        """老流程在局内会一直卡在「未知画面等待唤醒」直到返回大厅预算耗尽，退出码 1。"""
        _result, navigator, machine, _runtime = self.run_story(
            [story_fixture("battle_auto_on_live_20260809")]
        )

        navigator.navigate.assert_not_called()
        self.assertIs(StoryState.WAIT_BATTLE, machine.state)

    def test_lobby_still_returns_home_and_navigates(self):
        lobby = navigation_fixture("lobby")

        _result, navigator, machine, runtime = self.run_story([lobby])

        navigator.navigate.assert_called_once_with("story", lobby_screen=lobby)
        self.assertIs(StoryState.STAGE, machine.state)
        runtime.save_diagnostic.assert_not_called()

    def test_other_route_page_keeps_returning_until_a_story_page_shows_up(self):
        """停在别的支线页面：照旧一路返回，中途扫到主线页面就地接管。"""
        _result, navigator, machine, _runtime = self.run_story(
            [
                navigation_fixture("arena_list"),
                story_fixture("stage"),
            ]
        )

        self.assertIs(StoryState.STAGE, machine.state)
        self.assertEqual(1, navigator.navigate.call_count)

    def test_routes_without_a_probe_call_the_same_return_home(self):
        """⚠️ 2026-09-26 翻转：**所有路线走同一套回家流程**，没有「带探针 / 不带探针」两档。

        以前这里是「非竞技场路线保持无参调用」——那是**白名单两套并存**时代的契约
        （用户 2026-09-26 拍板删掉）。现在 ``HomeReturn`` 是纯转发，没接力的路线
        传 ``stop_probe=None``，走的是同一个 v2 流程。
        """
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

        navigator_type.return_value.return_home.assert_called_once_with(stop_probe=None)
        navigator_type.return_value.navigate.assert_called_once_with(
            "fodder", lobby_screen=lobby
        )


class StoryResumeNavigationGuardTests(unittest.TestCase):
    """`navigate(already_at=...)` 只认本模式声明过的接力页，不做静默降级。"""

    def test_story_accepts_its_own_entry_page_without_clicking_anything(self):
        """已经在关卡入口上：一次点击都不该有，尤其不能发 Back。"""
        clicks: list[tuple[int, int]] = []
        navigator = Epic7Navigator(
            build_navigation_templates(TEMPLATES),
            Runtime(
                lambda: story_fixture("stage_battle_ready_updated"),
                clicks.append,
            ),
            sleep=lambda _seconds: None,
            transition_frames=8,
        )

        navigator.navigate(
            "story",
            lobby_screen=story_fixture("stage_battle_ready_updated"),
            already_at=STORY_ENTRY_PAGE,
        )

        self.assertEqual([], clicks)

    def test_other_modes_reject_a_resume_page(self):
        for mode, page in (
            ("arena", STORY_ENTRY_PAGE),
            ("story", "arena_mode"),
            # 远征现在接得住自己导航链上的三级；拿主线的入口页去试探才算越界。
            ("expedition", STORY_ENTRY_PAGE),
        ):
            with self.subTest(mode=mode, page=page):
                navigator = real_navigator()

                with self.assertRaisesRegex(ValueError, "不支持从页面"):
                    navigator.navigate(mode, already_at=page)


if __name__ == "__main__":
    unittest.main()
