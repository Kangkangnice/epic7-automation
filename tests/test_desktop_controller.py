"""桌面控制器：勾选顺序、活动互斥、次数规则与 PC 输入通道。

2026-11-09 补建。``DesktopController`` 原来**唯一**的测试在 ``test_desktop_app.py``
里，删 Tk 界面时那个文件被整个带走，于是「构造时少导一个常量」这种错一路漏到桌面
图标：``pythonw`` 下没有控制台，用户看到的就是「双击没反应」。本文件只守业务规则，
不碰 Qt，也不真的开界面。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from auto_game_unified.core.pc_window import (
    PC_INPUT_BACKGROUND,
    PC_INPUT_FOREGROUND,
)
from auto_game_unified.desktop.catalog import route_by_name
from auto_game_unified.desktop.controller import DesktopController
from auto_game_unified.desktop.worker import WorkerController


class _RecordingWorker:
    """只记录 `notice` / `start`，不真的开子进程。"""

    def __init__(self) -> None:
        self.running = False
        self.requests: list[object] = []
        self.notices: list[str] = []

    def notice(self, message: str) -> None:
        self.notices.append(message)

    def start(self, request: object) -> None:
        self.requests.append(request)


class DesktopControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # 只构造、不 start，所以默认的 subprocess.Popen 一次也不会被调用。
        self.controller = DesktopController(
            worker=WorkerController(repo_parent=Path(tmp.name))
        )

    def test_constructs_with_the_documented_defaults(self) -> None:
        """守住事故点：默认输入通道是「后台」，且构造过程本身不抛异常。"""
        c = self.controller
        self.assertEqual(c.selected_backend, "emulator")
        self.assertEqual(c.pc_input_mode, PC_INPUT_BACKGROUND)
        # 默认一条都不勾（用户 2026-09-29 拍板），次数取各路线自己的默认值。
        self.assertEqual(c.selection, [])
        self.assertEqual(
            c.cycles["story"], route_by_name("story").default_cycles
        )
        # 没做环境检测前不能开跑。
        self.assertFalse(c.can_start)
        self.assertFalse(c.ready)

    def test_toggle_keeps_the_click_order(self) -> None:
        c = self.controller
        c.toggle("arena", True)
        c.toggle("story", True)
        self.assertEqual(c.selection, ["arena", "story"])
        self.assertEqual(
            c.plan(),
            (
                ("arena", route_by_name("arena").default_cycles),
                ("story", route_by_name("story").default_cycles),
            ),
        )

    def test_event_route_is_exclusive_in_both_directions(self) -> None:
        """活动小游戏只能单独跑：起点是人工摆好的选卡页，串在后面会被破坏。"""
        c = self.controller
        c.toggle("story", True)
        c.toggle("survivor", True)
        self.assertEqual(c.selection, ["survivor"])

        c.toggle("story", True)
        self.assertEqual(c.selection, ["story"])

    def test_fixed_cycle_route_ignores_user_input(self) -> None:
        c = self.controller
        default = route_by_name("world_boss").default_cycles
        c.set_cycles("world_boss", 99)
        self.assertEqual(c.cycles["world_boss"], default)

    def test_cycles_below_minimum_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.controller.set_cycles("story", 0)

    def test_pc_input_mode_switch_rejects_unknown_values(self) -> None:
        c = self.controller
        c.select_pc_input_mode(PC_INPUT_FOREGROUND)
        self.assertEqual(c.pc_input_mode, PC_INPUT_FOREGROUND)
        with self.assertRaises(ValueError):
            c.select_pc_input_mode("whatever")

    def test_emulator_skips_only_pc_only_routes_and_runs_the_rest(self) -> None:
        """新路线只影响它自己：模拟器下补星缺图，老路线必须照常跑。"""
        worker = _RecordingWorker()
        c = DesktopController(worker=worker)
        c.toggle("story", True)
        c.toggle("story_star", True)  # 只有 PC 素材
        c.preflight_report = SimpleNamespace(can_start=True)

        c.start()

        # 勾选顺序不变，只把不可用的那条剔掉。
        self.assertEqual(worker.requests[0].modes, ("story",))
        self.assertEqual(
            dict(worker.requests[0].cycles),
            {"story": route_by_name("story").default_cycles},
        )
        self.assertEqual(len(worker.notices), 1)
        self.assertIn("主线补星", worker.notices[0])
        self.assertIn("已跳过", worker.notices[0])

    def test_pc_skips_unapproved_routes_but_runs_the_rest(self) -> None:
        worker = _RecordingWorker()
        c = DesktopController(worker=worker)
        c.select_backend("pc")
        c.toggle("story", True)  # 已放行
        c.toggle("expedition", True)  # 未在 PC 放行
        c.preflight_report = SimpleNamespace(can_start=True)

        c.start()

        self.assertEqual(worker.requests[0].modes, ("story",))
        self.assertIn("远征", worker.notices[0])

    def test_all_unsupported_routes_still_raise_instead_of_silently_doing_nothing(self) -> None:
        worker = _RecordingWorker()
        c = DesktopController(worker=worker)
        c.toggle("story_star", True)
        c.preflight_report = SimpleNamespace(can_start=True)

        with self.assertRaises(RuntimeError) as caught:
            c.start()

        self.assertIn("都不可用", str(caught.exception))
        self.assertEqual(worker.requests, [])


if __name__ == "__main__":
    unittest.main()
