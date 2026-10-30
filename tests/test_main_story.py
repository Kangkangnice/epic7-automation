import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from auto_game_unified import main as main_module
from auto_game_unified.core.qqbot import APP_ID_ENV, CLIENT_SECRET_ENV, USER_OPENID_ENV
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.main import RunResult
from auto_game_unified.games.epic7 import modes as modes_module
from auto_game_unified.games.epic7.evidence import shop_refresh as shop_refresh_evidence
from auto_game_unified.games.epic7.modes import get_mode


class _NeverBuiltRunner:
    """假 Runner：被 ``preflight`` 拦下的路线根本不该走到构造它的那一步。"""

    def __init__(self, *_args, **_kwargs):
        raise AssertionError("闸门拦下之后不该再去构造 Runner")


def fake_return_home(*, returns=None, on_call=None):
    """替身 navigator 的 ``return_home``：**必须转发 ``stop_probe``**。

    ``main._enter_mode`` 会核对「接力探针到底被问过没有」——问都没问过就是接线断了，
    直接抛错（见 ``docs/TRANSITION_CONTRACTS.md``「接力契约」卡点②）。所以一个
    不转发 ``stop_probe`` 的替身已经不忠实于 ``Epic7Navigator`` 的接口了：
    它表面上「回大厅成功」，实际上把接力钩子吃掉了。

    转发时给一帧**空白图**：认不出任何页面 ⇒ 探针返回 None ⇒ 走原本的
    「回大厅 → 按路线导航」流程，这些用例关心的东西全都不受影响。代价约 0.2 秒。
    """

    def return_home(**kwargs):
        if on_call is not None:
            on_call()
        probe = kwargs.get("stop_probe")
        if probe is not None:
            probe(np.zeros((1132, 1982, 3), dtype=np.uint8))
        return returns

    return return_home


class MainStoryTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.dict(
            os.environ,
            {APP_ID_ENV: "", CLIENT_SECRET_ENV: "", USER_OPENID_ENV: ""},
            clear=False,
        )
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def test_live_modes_install_one_global_popup_guard_before_navigation(self):
        for mode in ("story", "arena", "expedition", "fodder"):
            with self.subTest(mode=mode):
                runtime = unittest.mock.MagicMock()
                runner_type = unittest.mock.MagicMock()
                runner_type.return_value.run.return_value = 0
                spec = replace(get_mode(mode), runner_type=runner_type)
                events = []
                network_templates = object()
                intimacy_templates = object()
                friendship_templates = object()
                friend_request_templates = object()
                knights_signin_templates = object()
                gift_support_templates = object()
                knights_weekly_reward_templates = object()
                pet_gift_templates = object()
                web_network_error_templates = object()
                worldboss_support_reward_templates = object()
                # 「段位升级奖励」弹窗（2026-10-20 接，第 11 个全局弹窗）。
                arena_rank_reward_templates = object()
                # 「战斗记录」弹窗（2026-10-30 接，第 12 个全局弹窗）。
                battle_record_templates = object()
                # 「骑士团成长Rank提升」弹窗（2026-10-30 接，第 13 个）。
                knights_growth_rank_templates = object()
                # ⚠️ 本文件三处 B023 抑制标记都是误报：events 虽然在外层循环里被重新赋值，
                # 但这些 side_effect / on_call 都是**当轮同步调用**的（mock 在被调用的那一刻
                # 就执行它），取不到下一轮的值。ruff 只看语法，看不出调用时机。
                runtime.set_capture_guard.side_effect = lambda guard: (
                    events.append("guard")  # noqa: B023
                )

                with (
                    patch.object(main_module, "_build_runtime", return_value=runtime),
                    patch.object(main_module, "Epic7GlobalPopupGuard") as guard_type,
                    patch.object(
                        main_module,
                        "load_network_reconnect_templates",
                        return_value=network_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_intimacy_level_up_templates",
                        return_value=intimacy_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_friendship_points_templates",
                        return_value=friendship_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_friend_request_templates",
                        return_value=friend_request_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_knights_signin_templates",
                        return_value=knights_signin_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_knights_weekly_reward_templates",
                        return_value=knights_weekly_reward_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_gift_support_templates",
                        return_value=gift_support_templates,
                    ),
                    patch.object(
                        main_module,
                        "load_pet_gift_templates",
                        return_value=pet_gift_templates,
                    ),
                    # 网页「网络错误」长条（2026-10-07 接，第 9 个全局弹窗）。
                    # ⚠️ 这个 patch 与被写死的 kwargs 断言**必须同进同出** ——
                    # 少一个，加载期就会真的去读模板目录，在没模板的环境里直接报错。
                    patch.object(
                        main_module,
                        "load_web_network_error_templates",
                        return_value=web_network_error_templates,
                    ),
                    # 「世界首领辅助队伍奖励」弹窗（2026-10-19 接，第 10 个全局弹窗）。
                    # 同一条规矩：这个 patch 与被写死的 kwargs 断言必须同进同出。
                    patch.object(
                        main_module,
                        "load_worldboss_support_reward_templates",
                        return_value=worldboss_support_reward_templates,
                    ),
                    # 「段位升级奖励」弹窗：只在首次升至某段位时出现一次，
                    # 2026-10-20 08:02 那次竞技场 ✗ 就是它（上面那条规矩同样适用）。
                    patch.object(
                        main_module,
                        "load_arena_rank_reward_templates",
                        return_value=arena_rank_reward_templates,
                    ),
                    # 「战斗记录」弹窗：进竞技场时就弹的防守战报，2026-10-30 接。
                    patch.object(
                        main_module,
                        "load_battle_record_templates",
                        return_value=battle_record_templates,
                    ),
                    # 「骑士团成长Rank提升」弹窗：只在骑士团成长等级提升时出现。
                    patch.object(
                        main_module,
                        "load_knights_growth_rank_templates",
                        return_value=knights_growth_rank_templates,
                    ),
                    patch.object(main_module, "Epic7Navigator") as navigator_type,
                    patch.object(main_module, "HomeReturn") as home_return_type,
                ):
                    # 竞技场/主线/远征会带 stop_probe（接力观察窗）进来，狗粮不带；
                    # 两条路径都必须发生在弹窗守卫装好之后，所以这里二者都接受。
                    # 带 stop_probe 时替身必须转发它，否则 `_enter_mode` 会判定接线断了。
                    #
                    # ⚠️ 2026-09-25：竞技场切到「回大厅」新流程（v2）之后，这里替换的
                    # 对象从 `navigator.return_home` 改成了 `main.HomeReturn` ——
                    # 白名单路线走 v2、压根不碰导航器那个方法，再替换它记不到事件。
                    navigator_type.return_value.return_home.side_effect = (
                        fake_return_home(
                            on_call=lambda: events.append("navigation")  # noqa: B023
                        )
                    )
                    home_return_type.return_value.side_effect = (
                        fake_return_home(
                            on_call=lambda: events.append("navigation")  # noqa: B023
                        )
                    )
                    main_module.run_mode(
                        spec=spec,
                        dry_run=False,
                        max_cycles=1,
                        start_state=spec.default_state,
                    )

                runtime.set_capture_guard.assert_called_once_with(
                    guard_type.return_value
                )
                guard_type.assert_called_once_with(
                    network_templates,
                    intimacy_templates=intimacy_templates,
                    friendship_templates=friendship_templates,
                    friend_request_templates=friend_request_templates,
                    knights_signin_templates=knights_signin_templates,
                    gift_support_templates=gift_support_templates,
                    knights_weekly_reward_templates=knights_weekly_reward_templates,
                    pet_gift_templates=pet_gift_templates,
                    web_network_error_templates=web_network_error_templates,
                    worldboss_support_reward_templates=(
                        worldboss_support_reward_templates
                    ),
                    arena_rank_reward_templates=arena_rank_reward_templates,
                    battle_record_templates=battle_record_templates,
                    knights_growth_rank_templates=knights_growth_rank_templates,
                )
                self.assertEqual(["guard", "navigation"], events)

    def test_dry_run_does_not_install_global_popup_guard(self):
        runtime = unittest.mock.MagicMock()
        runner_type = unittest.mock.MagicMock()
        runner_type.return_value.run.return_value = 0
        spec = replace(get_mode("story"), runner_type=runner_type)

        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7GlobalPopupGuard") as guard_type,
        ):
            main_module.run_mode(
                spec=spec,
                dry_run=True,
                max_cycles=1,
                start_state=spec.default_state,
            )

        runtime.set_capture_guard.assert_not_called()
        guard_type.assert_not_called()

    def test_live_run_passes_one_recovery_gate_to_the_runner(self):
        runtime = unittest.mock.MagicMock()
        runner_type = unittest.mock.MagicMock()
        runner_type.return_value.run.return_value = 0
        spec = replace(get_mode("story"), runner_type=runner_type)

        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7Navigator") as navigator_type,
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home()
            main_module.run_mode(
                spec=spec,
                dry_run=False,
                max_cycles=1,
                start_state="stage",
            )

        options = runner_type.call_args.kwargs
        self.assertIsInstance(options["recovery_gate"], RecoveryGate)
        # ⚠️ 只给闸门，**不给**任何「恢复」回调：那条通道 2026-09-26 整段删除
        # （用户拍板「回家就是结束」）。谁把它加回来，这里立刻红。
        self.assertNotIn("recovery", options)

    def test_runtime_routes_only_campfire_wake_to_the_window_wake_channel(self):
        window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=window):
            runtime = main_module._build_runtime("expedition", dry_run=False)

        runtime.click((1000, 600), "wake-campfire-ui")
        runtime.click((1062, 1045), "public-recruit")

        window.wake.assert_called_once_with((1000, 600))
        window.click.assert_called_once_with((1062, 1045))

    def test_runtime_checks_the_emulator_input_channel_only_when_live(self):
        """干跑不点击，不该去动 adb 服务；实跑必须先自检一次通道。

        背景：模拟器重启后 host 侧 adb server 常还挂在旧连接上（设备 offline），
        表现是「画面看得见、点不动」，上层只看到「点击验收无效」。
        2026-09-24 / 2026-09-28 各实机踩过一次。
        """
        dry_window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=dry_window):
            main_module._build_runtime("story", dry_run=True)
        dry_window.ensure_input_channel.assert_not_called()

        live_window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=live_window):
            main_module._build_runtime("story", dry_run=False)
        live_window.ensure_input_channel.assert_called_once_with()

    def test_emulator_runtime_routes_swipe_to_the_ldplayer_channel(self):
        window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=window):
            runtime = main_module._build_runtime("shop_refresh", dry_run=False)

        runtime.swipe(
            (1300, 850),
            (1300, 220),
            500,
            "shop-scroll-bottom",
        )

        window.swipe.assert_called_once_with((1300, 850), (1300, 220), 500)

    def test_shop_refresh_live_is_blocked_before_runtime_until_current_evidence_exists(self):
        # ⚠️ 打到 ``evidence.shop_refresh`` 的模块属性上，不是 ``main_module`` 上：
        # 这条闸门 2026-09-27 起由 ``modes._preflight_shop_refresh`` 在**调用时**读那个
        # 模块属性（路线级钩子，见 ``modes.ModeSpec.preflight``）。以前它读的是
        # ``main`` 里 import 的那份名字，所以打到 ``main_module`` 上；现在打那边不再生效。
        with (
            patch.object(shop_refresh_evidence, "LIVE_TRANSACTIONS_VERIFIED", False),
            patch.object(main_module, "_build_runtime") as build_runtime,
        ):
            with self.assertRaisesRegex(RuntimeError, "当前客户端实证"):
                main_module.run_mode(
                    spec=get_mode("shop_refresh"),
                    dry_run=False,
                    max_cycles=1,
                    start_state="scan_top",
                    window_backend="emulator",
                )

        build_runtime.assert_not_called()

    def test_the_preflight_hook_stops_the_route_before_any_runtime_exists(self):
        """通用接线：``run_mode`` 认的是「注册项上有没有钩子」，不认具名路线。

        ⚠️ 为什么要单独钉一条：钩子写进注册项、却忘了在 ``run_mode`` 里取用，
        **一点症状都没有** —— 路线照跑，只是闸门不生效。上面那条刷书签的用例
        只能证明「这条路线被拦住了」，证明不了「拦它的是钩子机制」。
        """
        spec = modes_module.ModeSpec(
            name="fake_hook_route",
            label="假路线",
            default_state="x",
            states=frozenset({"x"}),
            build_machine=lambda *_a, **_k: None,
            runner_type=_NeverBuiltRunner,
            preflight=lambda mode, dry_run: f"闸门拦下了 {mode}",
        )

        with patch.object(main_module, "_build_runtime") as build_runtime:
            with self.assertRaisesRegex(RuntimeError, "闸门拦下了 fake_hook_route"):
                main_module.run_mode(
                    spec=spec,
                    dry_run=False,
                    max_cycles=1,
                    start_state="x",
                    window_backend="emulator",
                )

        # 闸门必须在建 runtime **之前**生效（拦下的路线不该先开个窗口）。
        build_runtime.assert_not_called()

    def test_the_runner_options_hook_reaches_the_runner_constructor(self):
        """通用接线：``runner_options`` 的返回值要合进 Runner 的构造参数。

        竞技场的两个落盘位置就是从 ``if spec.name == "arena"`` 挪到这条钩子上的；
        钩子不生效的症状是「不落盘」，只在需要复盘胜负时才看得出来。
        """
        seen: dict = {}

        class _SpyRunner:
            def __init__(self, machine, runtime, **options):
                seen.update(options)

            def run(self, max_cycles=None):
                seen["cycles"] = max_cycles
                return 1

        spec = modes_module.ModeSpec(
            name="fake_hook_route",
            label="假路线",
            default_state="x",
            states=frozenset({"x"}),
            build_machine=lambda *_a, **_k: object(),
            runner_type=_SpyRunner,
            # 钩子拿到的必须是**主线的运行时产物根**，不是 modes 自己猜的一个。
            # 源码运行时它就是包目录；打包安装后是 %LOCALAPPDATA%\Epic7AutoAssistant
            # （竞技场的买票印记 ``arena_ticket_purchase.txt`` 落在它的 runtime_logs 下）。
            runner_options=lambda root, dry_run, params: {
                "收到的根": root,
                "干跑": dry_run,
                # 第三个入参是界面传来的路线参数（2026-10-22 开的通道）。
                "收到的参数": params,
            },
        )

        with (
            patch.object(main_module, "_build_runtime"),
            patch.object(main_module, "_install_finish_home"),
        ):
            result = main_module.run_mode(
                spec=spec,
                dry_run=True,
                max_cycles=1,
                start_state="x",
                window_backend="emulator",
                params={"打不打NPC": True},
            )

        self.assertEqual(main_module.DATA_ROOT, seen["收到的根"])
        self.assertIs(True, seen["干跑"])
        # 参数原样到钩子手里，主入口不解释内容。
        self.assertEqual({"打不打NPC": True}, seen["收到的参数"])
        # recovery_gate 由 run_mode 自己给，不该被路线钩子挤掉。
        self.assertIn("recovery_gate", seen)
        self.assertEqual(1, seen["cycles"])
        self.assertEqual(1, result.completed_cycles)

    def test_pc_runtime_calibrates_window_and_logs_actual_geometry(self):
        window = unittest.mock.MagicMock()
        window.ensure_render_size.return_value = unittest.mock.MagicMock(
            before=unittest.mock.MagicMock(width=1280, height=720),
            after=unittest.mock.MagicMock(width=1920, height=1080),
            adjusted=True,
        )
        output = io.StringIO()
        with (
            patch.object(main_module, "Epic7PcWindow", return_value=window),
            redirect_stdout(output),
        ):
            runtime = main_module._build_runtime(
                "story", dry_run=True, window_backend="pc"
            )

        window.ensure_render_size.assert_called_once_with()
        window.set_event_sink.assert_called_once_with(runtime.log)
        self.assertIs(runtime._capture, window.capture)
        self.assertIn("调整前=1280x720", output.getvalue())
        self.assertIn("调整后=1920x1080", output.getvalue())
        # 文案 2026-09-28 改过：PC 现在可以往 templates/<路线>/pc/ 放专属图，
        # 不再是「一律用共享模拟器模板」。
        self.assertIn(
            "模板来源=templates（PC 专属图优先，缺图回落共享图）", output.getvalue()
        )

    def test_pc_run_uses_shared_template_root(self):
        runtime = unittest.mock.MagicMock()
        machine = object()
        build_machine = unittest.mock.MagicMock(return_value=machine)
        runner_type = unittest.mock.MagicMock()
        runner_type.return_value.run.return_value = 0
        spec = replace(
            get_mode("story"),
            build_machine=build_machine,
            runner_type=runner_type,
        )
        with patch.object(main_module, "_build_runtime", return_value=runtime):
            main_module.run_mode(
                spec=spec,
                dry_run=True,
                max_cycles=1,
                start_state=spec.default_state,
                window_backend="pc",
            )

        template_root = build_machine.call_args.args[0]
        self.assertEqual("templates", template_root.name)
        # 平台差异只在「模板根」这一个对象里：跑 PC 时它会自动去
        # ``templates/**/pc/`` 找专属图，找不到就退回模拟器图。工厂不再收平台参数。
        self.assertEqual("pc", template_root.backend)

    def test_parser_accepts_internal_stop_file(self):
        args = main_module.parse_args(["--stop-file", r"D:\temp\stop.signal"])

        self.assertEqual(r"D:\temp\stop.signal", args.stop_file)

    def test_build_runtime_stops_when_gui_stop_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            stop_file = Path(directory) / "stop.signal"
            stop_file.touch()
            window = unittest.mock.MagicMock()
            with patch.object(main_module, "Epic7Window", return_value=window):
                runtime = main_module._build_runtime(
                    "story", dry_run=False, stop_file=stop_file
                )

            with self.assertRaises(ManualStop):
                runtime.capture()
            window.capture.assert_not_called()

    def test_live_run_returns_home_and_navigates_before_runner(self):
        runtime = unittest.mock.MagicMock()
        lobby = object()
        with (
            patch.object(main_module, "_build_runtime", return_value=runtime),
            patch.object(main_module, "Epic7Navigator") as navigator_type,
            patch("auto_game_unified.games.epic7.story.StoryRunner.run", return_value=1),
        ):
            navigator_type.return_value.return_home.side_effect = fake_return_home(
                returns=lobby
            )
            result = main_module.run_mode(
                spec=get_mode("story"), dry_run=False, max_cycles=1, start_state="stage"
            )

        self.assertEqual(1, result.completed_cycles)
        # 主线带接力探针：回大厅时每确认一帧稳定画面就问一次探针，所以必须传 stop_probe。
        navigator_type.return_value.return_home.assert_called_once()
        self.assertTrue(
            callable(
                navigator_type.return_value.return_home.call_args.kwargs["stop_probe"]
            )
        )
        navigator_type.return_value.navigate.assert_called_once_with("story", lobby_screen=lobby)

    def test_story_mode_dispatches_to_story_runner(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(0)) as run_story:
            exit_code = main_module.main(["--mode", "story", "--max-cycles", "2"])

        call = run_story.call_args
        self.assertEqual(0, exit_code)
        self.assertEqual("story", call.kwargs["spec"].name)
        self.assertEqual(True, call.kwargs["dry_run"])
        self.assertEqual(2, call.kwargs["max_cycles"])
        self.assertEqual("stage", call.kwargs["start_state"])

    def test_fodder_mode_dispatches_to_fodder_runner(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(0)) as run_fodder:
            exit_code = main_module.main(["--mode", "fodder", "--max-cycles", "2"])

        call = run_fodder.call_args
        self.assertEqual(0, exit_code)
        self.assertEqual("fodder", call.kwargs["spec"].name)
        self.assertTrue(call.kwargs["dry_run"])
        self.assertEqual(2, call.kwargs["max_cycles"])
        self.assertEqual("stage", call.kwargs["start_state"])

    def test_world_boss_defaults_to_two_cycles_without_the_flag(self):
        """世界首领战每天固定 2 次：不给 --max-cycles 也能跑，而不是报错。"""
        with patch.object(
            main_module, "run_mode", return_value=RunResult(0)
        ) as run_world_boss:
            exit_code = main_module.main(["--mode", "world_boss"])

        call = run_world_boss.call_args
        self.assertEqual(0, exit_code)
        self.assertEqual("world_boss", call.kwargs["spec"].name)
        self.assertTrue(call.kwargs["dry_run"])
        self.assertEqual(2, call.kwargs["max_cycles"])

    def test_expedition_has_no_difficulty_command_line_option(self):
        with self.assertRaises(SystemExit):
            main_module.parse_args(
                ["--mode", "expedition", "--difficulty", "2"]
            )

    def test_expedition_parser_does_not_expose_a_difficulty_value(self):
        args = main_module.parse_args(["--mode", "expedition"])

        self.assertFalse(hasattr(args, "difficulty"))

    def test_story_rejects_an_arena_resume_state(self):
        with self.assertRaisesRegex(SystemExit, "不适用于模式 story"):
            main_module.main(["--mode", "story", "--start-state", "list"])

    def test_live_run_requires_a_positive_cycle_limit(self):
        for arguments in (
            ["--mode", "story", "--live", "--confirm", "RUN"],
            ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "0"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(SystemExit, "--max-cycles 为正数"):
                    main_module.main(arguments)

    def test_live_run_rejects_manual_start_state(self):
        with self.assertRaisesRegex(SystemExit, "空跑诊断模式"):
            main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                    "--start-state",
                    "active",
                ]
            )

    def test_resource_stop_returns_exit_code_two(self):
        with patch.object(main_module, "run_mode", return_value=RunResult(3, resource_exhausted=True)):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "5"]
            )

        self.assertEqual(2, exit_code)

    def test_runtime_failure_returns_exit_code_one(self):
        with patch.object(main_module, "run_mode", side_effect=RuntimeError("unknown page")):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "1"]
            )

        self.assertEqual(1, exit_code)

    def test_manual_p_stop_returns_exit_code_130(self):
        with patch.object(main_module, "run_mode", side_effect=ManualStop("P")):
            exit_code = main_module.main(
                ["--mode", "story", "--live", "--confirm", "RUN", "--max-cycles", "1"]
            )

        self.assertEqual(130, exit_code)

    def test_live_success_sends_one_completion_notification(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(2)),
            patch.object(main_module, "send_qqbot_c2c") as send,
            patch.object(main_module.time, "monotonic", side_effect=[100.0, 165.0]),
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "2",
                ]
            )

        self.assertEqual(0, exit_code)
        title, content = send.call_args.args
        self.assertIn("主线已完成", title)
        self.assertIn("完成轮数：2/2", content)
        self.assertIn("耗时：65 秒", content)
        send.assert_called_once_with(title, content)

    def test_live_resource_stop_sends_one_resource_notification(self):
        with (
            patch.object(
                main_module,
                "run_mode",
                return_value=RunResult(3, resource_exhausted=True),
            ),
            patch.object(main_module, "send_qqbot_c2c") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "5",
                ]
            )

        self.assertEqual(2, exit_code)
        title, content = send.call_args.args
        self.assertIn("资源不足", title)
        self.assertIn("完成轮数：3/5", content)
        send.assert_called_once_with(title, content)

    def test_live_runtime_failure_sends_one_failure_notification(self):
        with (
            patch.object(
                main_module, "run_mode", side_effect=RuntimeError("unknown page")
            ),
            patch.object(main_module, "send_qqbot_c2c") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "arena",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(1, exit_code)
        title, content = send.call_args.args
        self.assertIn("竞技场运行失败", title)
        self.assertIn("unknown page", content)
        self.assertIn("runtime_diagnostics", content)
        # 跑挂了要推到 QQ：这正是「有问题就报错」那条路径。
        send.assert_called_once_with(title, content)

    def test_unexpected_live_exception_notifies_then_preserves_exception(self):
        with (
            patch.object(main_module, "run_mode", side_effect=ValueError("bad state")),
            patch.object(main_module, "send_qqbot_c2c") as send,
            self.assertRaisesRegex(ValueError, "bad state"),
        ):
            main_module.main(
                [
                    "--mode",
                    "fodder",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        send.assert_called_once()

    def test_manual_stop_does_not_notify(self):
        with (
            patch.object(main_module, "run_mode", side_effect=ManualStop("P")),
            patch.object(main_module, "send_qqbot_c2c") as send,
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "story",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(130, exit_code)
        send.assert_not_called()

    def test_dry_run_does_not_notify(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(1)),
            patch.object(main_module, "send_qqbot_c2c") as send,
        ):
            exit_code = main_module.main(
                ["--mode", "story", "--max-cycles", "1"]
            )

        self.assertEqual(0, exit_code)
        send.assert_not_called()

    def test_notification_bug_does_not_change_success_exit_code(self):
        with (
            patch.object(main_module, "run_mode", return_value=RunResult(1)),
            patch.object(
                main_module,
                "send_qqbot_c2c",
                side_effect=RuntimeError("notify bug"),
            ),
        ):
            exit_code = main_module.main(
                [
                    "--mode",
                    "expedition",
                    "--live",
                    "--confirm",
                    "RUN",
                    "--max-cycles",
                    "1",
                ]
            )

        self.assertEqual(0, exit_code)


if __name__ == "__main__":
    unittest.main()
