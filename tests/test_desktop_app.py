from pathlib import Path
import sys

import pytest
import tkinter as tk
from unittest.mock import patch

from auto_game_unified.desktop import app as app_module
from auto_game_unified.desktop.app import DesktopApp, DesktopController, fit_window_size
from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus


class FakeWorker:
    def __init__(self):
        self.running = False
        self.request = None
        self.stopped = False
        self.force_stopped = False

    def start(self, request):
        self.request = request
        self.running = True

    def request_stop(self):
        self.stopped = True

    def force_stop(self):
        self.force_stopped = True
        self.running = False
        return True

    def drain_events(self):
        return []


class FakeClock:
    """假时钟：``sleep`` 直接把时间往前推，测试里不用真的等满宽限期。"""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


def passed_preflight(window_backend="emulator"):
    return PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132))


def blocked_preflight(window_backend="emulator"):
    return PreflightReport(PreflightStatus.BLOCK, "没有找到雷电窗口")


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tk_window(tk_root):
    existing_callbacks = set(tk_root.tk.call("after", "info"))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    yield window
    callbacks = set(tk_root.tk.call("after", "info")) - existing_callbacks
    for callback in callbacks:
        tk_root.tk.call("after", "cancel", callback)
    window.destroy()


def test_startup_order_mentions_emulator_before_assistant():
    hint = getattr(app_module, "STARTUP_ORDER_HINT", "")

    assert "先启动雷电模拟器" in hint
    assert "进入《第七史诗》" in hint


def test_controller_requires_successful_preflight_before_start():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")

    assert controller.can_start is False

    controller.apply_preflight(passed_preflight())
    assert controller.can_start is True


def test_controller_forces_hero_synthesis_to_one_cycle():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("hero_synthesis")
    controller.set_cycles(99)
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.cycles == 1


def test_experimental_route_requires_confirmation():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("fodder")
    controller.apply_preflight(passed_preflight())

    assert controller.needs_experimental_confirmation is True


def test_selecting_another_route_preserves_successful_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_route("arena")

    assert controller.can_start is True


def test_switching_backend_invalidates_previous_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_backend("pc")

    assert controller.selected_backend == "pc"
    assert controller.can_start is False


def test_controller_passes_selected_backend_to_worker():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.backend == "pc"


def test_controller_rejects_unknown_backend():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.select_backend("console")


def test_controller_rejects_backend_switch_while_running():
    worker = FakeWorker()
    worker.running = True
    controller = DesktopController(worker=worker)

    with pytest.raises(RuntimeError):
        controller.select_backend("pc")


def test_controller_rejects_non_positive_cycles():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")

    with pytest.raises(ValueError, match="正整数"):
        controller.set_cycles(0)


def test_window_size_expands_for_high_dpi_requested_content():
    assert fit_window_size(
        requested=(1613, 1208),
        screen=(3200, 2000),
    ) == (1653, 1248)


def test_window_size_stays_inside_a_small_screen():
    assert fit_window_size(
        requested=(1500, 1100),
        screen=(1366, 768),
    ) == (1286, 688)


def test_desktop_app_initial_window_contains_its_requested_content(tmp_path, tk_window):
    DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()
    geometry = tk_window.winfo_geometry().split("+")[0]
    width, height = (int(value) for value in geometry.split("x"))
    assert width >= tk_window.winfo_reqwidth()
    assert height >= tk_window.winfo_reqheight()


def test_start_recheck_failure_does_not_start_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    validated_routes = []
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=blocked_preflight,
        route_validator=lambda mode, template_root: validated_routes.append(mode),
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert validated_routes == []
    assert app.environment_var.get() == "没有找到雷电窗口"


def test_start_rechecks_environment_and_validates_selected_route(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("arena")
    controller.apply_preflight(passed_preflight())
    calls = []
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=lambda window_backend: calls.append(
            ("preflight", window_backend)
        )
        or passed_preflight(),
        route_validator=lambda mode, template_root: calls.append(
            (mode, template_root)
        ),
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start()
    tk_window.update()

    assert calls == [("preflight", "emulator"), ("arena", app.template_root)]
    assert worker.request.mode == "arena"


def test_route_template_failure_does_not_start_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=passed_preflight,
        route_validator=lambda mode, template_root: (_ for _ in ()).throw(
            RuntimeError("缺少模板")
        ),
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert "路线资源检查失败：缺少模板" == app.environment_var.get()


def test_hidden_launcher_sends_both_streams_to_its_log(tmp_path, monkeypatch):
    """桌面图标走的是无窗口入口，标准流必须**在导入助手之前**落到日志上。

    双击启动时 ``sys.stdout`` 可能是 ``None``，任何一处不小心往里写都会直接抛异常；
    这个入口的全部价值就是把两个流换成真文件，所以这里钉死「换成了什么」和
    「返回码原样透传」（吞掉退出码会把启动失败伪装成成功）。
    """
    from auto_game_unified.desktop import launch_hidden

    log_path = tmp_path / "nested" / "desktop_launch.log"
    monkeypatch.setattr(launch_hidden, "LOG_PATH", log_path)
    # main() 会直接改写 sys.stdout / sys.stderr，交给 monkeypatch 负责还原
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    with patch("auto_game_unified.desktop.app.main", return_value=7) as run:
        assert launch_hidden.main() == 7

    run.assert_called_once_with()
    assert sys.stdout is sys.stderr, "两个流应指向同一个日志文件"
    assert Path(sys.stdout.name) == log_path
    try:
        sys.stderr.write("启动检查\n")
        sys.stderr.flush()
    finally:
        sys.stderr.close()
    assert "启动检查" in log_path.read_text(encoding="utf-8")


def test_hidden_launcher_writes_a_startup_failure_into_the_log(tmp_path, monkeypatch):
    """启动就崩的时候无窗口下没人看得到，必须落进日志并返回非零。

    没有这条，故障表现就是「双击图标没反应」，连查都没法查。
    """
    from auto_game_unified.desktop import launch_hidden

    log_path = tmp_path / "desktop_launch.log"
    monkeypatch.setattr(launch_hidden, "LOG_PATH", log_path)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    with patch(
        "auto_game_unified.desktop.app.main",
        side_effect=RuntimeError("模板目录缺失"),
    ):
        assert launch_hidden.main() == 1

    text = log_path.read_text(encoding="utf-8")
    sys.stderr.close()
    assert "模板目录缺失" in text
    assert "Traceback" in text


# --------------------------------------------------------------------------
# 「每日任务」界面区块
# --------------------------------------------------------------------------


def test_controller_defaults_to_all_daily_tasks_ticked():
    controller = DesktopController(worker=FakeWorker())

    from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS

    assert controller.daily_selection == [task.mode for task in DAILY_TASKS]
    assert controller.daily_ready is True


def test_controller_daily_ready_needs_at_least_one_tick():
    controller = DesktopController(worker=FakeWorker())

    for mode in list(controller.daily_selection):
        controller.toggle_daily_item(mode, False)

    assert controller.daily_selection == []
    assert controller.daily_ready is False


def test_controller_rejects_unknown_daily_mode():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.toggle_daily_item("nope", True)


def test_daily_cycles_default_to_each_route_daily_count():
    controller = DesktopController(worker=FakeWorker())

    assert controller.daily_cycles == {
        "world_boss": 2,
        "knights_donation": 1,
        "shop_refresh": 1,
        "labyrinth_stone": 1,
        "arena": 1,
    }


def test_edited_daily_cycle_reaches_the_worker():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())

    controller.set_daily_cycles("arena", 4)
    controller.start_daily()

    assert worker.request.daily_tasks == (
        "world_boss",
        "knights_donation",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    )
    assert worker.request.daily_cycles == {
        "world_boss": 2,
        "knights_donation": 1,
        "shop_refresh": 1,
        "labyrinth_stone": 1,
        "arena": 4,
    }


def test_daily_cycle_of_a_capped_route_is_snapped_back_to_its_default():
    """世界首领战每天就 2 次、骑士团捐赠就 1 次 ⇒ 界面给多少都打回默认值。"""
    controller = DesktopController(worker=FakeWorker())

    controller.set_daily_cycles("world_boss", 9)
    controller.set_daily_cycles("knights_donation", 9)

    assert controller.daily_cycles["world_boss"] == 2
    assert controller.daily_cycles["knights_donation"] == 1


def test_daily_cycle_must_be_a_positive_integer():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError, match="正整数"):
        controller.set_daily_cycles("arena", 0)


def test_daily_cycle_rejects_unknown_route():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.set_daily_cycles("nope", 3)


def test_controller_starts_daily_worker_with_the_selection():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    controller.toggle_daily_item("arena", False)

    controller.start_daily()

    assert worker.request.is_daily is True
    assert worker.request.daily_tasks == (
        "world_boss",
        "knights_donation",
        "shop_refresh",
        "labyrinth_stone",
    )


def test_controller_refuses_daily_start_with_empty_selection():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    for mode in list(controller.daily_selection):
        controller.toggle_daily_item(mode, False)

    with pytest.raises(RuntimeError, match="至少"):
        controller.start_daily()


def test_daily_panel_renders_a_checkbox_per_task(tmp_path, tk_window):
    from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS

    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    assert list(app.daily_vars) == [task.mode for task in DAILY_TASKS]
    assert len(app._daily_buttons) == len(DAILY_TASKS)
    assert all(var.get() for var in app.daily_vars.values())


def test_route_panel_uses_two_columns_to_keep_the_window_short(tmp_path, tk_window):
    """用户 2026-09-25 反馈「UI 有点太长了」⇒ 路线列表摊成两列，用宽度换高度。"""
    from auto_game_unified.desktop.catalog import ROUTES

    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    cells = [
        (
            int(button.grid_info()["row"]),
            int(button.grid_info()["column"]),
        )
        for button in app._route_buttons
    ]
    assert {column for _, column in cells} == {0, 1}
    assert max(row for row, _ in cells) == -(-len(ROUTES) // 2)


def test_daily_panel_offers_a_cycle_input_per_task(tmp_path, tk_window):
    """每条日常后面那个次数框：默认值来自各路线，有每日上限的置灰。"""
    from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS

    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    assert list(app.daily_cycle_vars) == [task.mode for task in DAILY_TASKS]
    assert app.daily_cycle_vars["world_boss"].get() == "2"
    assert app.daily_cycle_vars["arena"].get() == "1"
    assert str(app._daily_cycle_inputs["world_boss"].cget("state")) == "disabled"
    assert str(app._daily_cycle_inputs["arena"].cget("state")) == "normal"


def test_a_capped_daily_cycle_typed_in_the_panel_is_snapped_back(tmp_path, tk_window):
    """框是灰的也拦不住有人往里塞字符 ⇒ 收的时候打回默认值并回显。"""
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    app.daily_cycle_vars["world_boss"].set("9")

    assert app._collect_daily_cycles() is True
    assert app.daily_cycle_vars["world_boss"].get() == "2"


def test_an_invalid_daily_cycle_blocks_the_start(tmp_path, tk_window):
    """填坏了就当场拦下，别带着一个看不懂的次数开跑。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=passed_preflight,
        thread_factory=ImmediateThread,
    )
    tk_window.update_idletasks()
    app.daily_cycle_vars["arena"].set("0")

    with patch(
        "auto_game_unified.desktop.app.messagebox.showerror"
    ) as showerror:
        app._start_daily()
    tk_window.update()

    assert worker.request is None
    assert showerror.called
    assert app.daily_cycle_vars["arena"].get() == "1"


def test_daily_start_uses_the_edited_panel_cycle(tmp_path, tk_window):
    """从界面一路走到 worker 命令：填了 4 场就得是 4 场。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=passed_preflight,
        thread_factory=ImmediateThread,
    )
    tk_window.update_idletasks()
    app.daily_cycle_vars["arena"].set("4")

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start_daily()
    tk_window.update()

    assert worker.request.daily_cycles["arena"] == 4


def test_unchecking_a_daily_task_updates_the_controller(tmp_path, tk_window):
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app.daily_vars["arena"].set(False)
    app._on_daily_toggle("arena")

    assert controller.daily_selection == [
        "world_boss",
        "knights_donation",
        "shop_refresh",
        "labyrinth_stone",
    ]
    assert app.daily_vars["arena"].get() is False


def test_daily_start_runs_preflight_then_starts_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    calls = []
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=lambda window_backend: calls.append(window_backend)
        or passed_preflight(),
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start_daily()
    tk_window.update()

    assert calls == ["emulator"]
    assert worker.request is not None
    assert worker.request.daily_tasks == (
        "world_boss",
        "knights_donation",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    )


def test_daily_start_aborts_when_preflight_blocks(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=blocked_preflight,
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start_daily()
    tk_window.update()

    assert worker.request is None
    assert app.environment_var.get() == "没有找到雷电窗口"


def test_daily_start_cancelled_when_selection_changes_mid_check(tmp_path, tk_window):
    """复检期间用户改了勾选 ⇒ 取消启动（免得跑的不是他看到的那套）。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())

    def preflight_and_flip(window_backend):
        # 复检跑在后台线程里；用户此时又动了勾选。
        controller.toggle_daily_item("arena", False)
        return passed_preflight()

    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=preflight_and_flip,
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start_daily()
    tk_window.update()

    assert worker.request is None
    assert "已变化" in app.environment_var.get()


def test_daily_start_cancelled_when_cycles_change_mid_check(tmp_path, tk_window):
    """次数也是「他看到的那一套」的一部分 ⇒ 复检期间改了同样要作废。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())

    def preflight_and_edit(window_backend):
        controller.set_daily_cycles("arena", 6)
        return passed_preflight()

    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=preflight_and_edit,
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start_daily()
    tk_window.update()

    assert worker.request is None
    assert "已变化" in app.environment_var.get()


def test_declining_experimental_warning_does_not_start_daily(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=passed_preflight,
        thread_factory=ImmediateThread,
    )

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=False,
    ):
        app._start_daily()
    tk_window.update()

    assert worker.request is None


# --------------------------------------------------------------------------
# 「安全停止」的第二手兜底
# --------------------------------------------------------------------------


def test_stop_grace_is_orders_of_magnitude_above_a_normal_stop():
    """正常停止实测 1~2 秒（8-31~9-28 共 88 次退出码 130 的日志）⇒ 要留足余量；
    但也不能长到用户以为界面又卡住了。"""
    assert 10 <= app_module.STOP_GRACE_SECONDS <= 60


def test_stop_forces_the_worker_off_when_it_never_exits(tmp_path, tk_window):
    """2026-09-28 实机：卡住的运行读不到停止信号 ⇒ 干等没用，必须强行结束。

    「安全停止」写下的信号要等**两次动作之间**才被读到；卡在一次底层调用内部的进程
    永远轮不到那一步。这条钉住「等满宽限期就真的强行结束」。
    """
    worker = FakeWorker()
    worker.running = True
    clock = FakeClock()
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=worker),
        project_root=tmp_path,
        thread_factory=ImmediateThread,
        clock=clock,
        sleep=clock.sleep,
        stop_grace_seconds=30.0,
    )

    app._stop()
    tk_window.update()

    assert worker.stopped is True
    assert worker.force_stopped is True
    assert clock.now >= 30.0, "必须等满宽限期才动手"
    assert "强行结束" in app.log_text.get("1.0", tk.END)


def test_stop_leaves_a_worker_that_exits_within_the_grace_period_alone(
    tmp_path, tk_window
):
    """平时那 88 次：1~2 秒就退 ⇒ 绝不能把它也强行结束（会跳过回家流程）。"""
    worker = FakeWorker()
    worker.running = True
    clock = FakeClock()

    def sleep(seconds):
        clock.sleep(seconds)
        worker.running = False

    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=worker),
        project_root=tmp_path,
        thread_factory=ImmediateThread,
        clock=clock,
        sleep=sleep,
        stop_grace_seconds=30.0,
    )

    app._stop()
    tk_window.update()

    assert worker.force_stopped is False
    assert clock.now < 30.0
    assert "强行结束" not in app.log_text.get("1.0", tk.END)


def test_the_window_is_usable_again_after_a_forced_kill(tmp_path, tk_window):
    """强行结束的全部价值就在这里：界面必须**立刻**能继续用。

    卡死时读输出的线程还挂在阻塞的管道上，``finished`` 事件永远不会来 ⇒
    「重新可用」不能依赖那条事件，只能自己把状态收回来。
    """
    worker = FakeWorker()
    worker.running = True
    clock = FakeClock()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        thread_factory=ImmediateThread,
        clock=clock,
        sleep=clock.sleep,
    )
    tk_window.update_idletasks()

    app._stop()
    tk_window.update()

    assert str(app.stop_button.cget("state")) == "disabled"
    assert str(app.start_button.cget("state")) == "normal"
