from pathlib import Path
import sys

import pytest
import tkinter as tk
from unittest.mock import patch

from auto_game_unified.desktop import app as app_module
from auto_game_unified.desktop import theme
from auto_game_unified.desktop.app import DesktopApp, DesktopController, fit_window_size
from auto_game_unified.desktop.catalog import ROUTES
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


# --------------------------------------------------------------------------
# 状态层：勾选（有序）+ 次数
# --------------------------------------------------------------------------


def test_controller_requires_successful_preflight_before_start():
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("story", True)

    assert controller.can_start is False

    controller.apply_preflight(passed_preflight())
    assert controller.can_start is True


def test_controller_starts_with_nothing_ticked():
    """用户 2026-09-29 拍板：打开时一条都不勾 —— 每次自己挑。

    顺带当一道「点开始前先想一下」的确认：世界首领战会花体力、刷书签会花天空石。
    """
    controller = DesktopController(worker=FakeWorker())

    assert controller.selection == []
    assert controller.ready is False


def test_controller_cycles_default_to_each_route_own_default():
    controller = DesktopController(worker=FakeWorker())

    assert list(controller.cycles) == [route.mode for route in ROUTES]
    assert controller.cycles["world_boss"] == 2
    assert controller.cycles["hero_synthesis"] == 1
    assert controller.cycles["arena"] == 1
    assert controller.cycles["survivor"] == 3


def test_controller_records_the_ticking_order():
    """勾选先后就是执行顺序 —— 先勾的排前面（用户 2026-09-29 拍板）。"""
    controller = DesktopController(worker=FakeWorker())

    controller.toggle("arena", True)
    controller.toggle("knights_donation", True)

    assert controller.selection == ["arena", "knights_donation"]


def test_unticking_then_ticking_again_moves_it_to_the_end():
    """取消再重新勾 = 排到最后（序号会跟着变，界面上看得见）。"""
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("arena", True)
    controller.toggle("knights_donation", True)

    controller.toggle("arena", False)
    controller.toggle("arena", True)

    assert controller.selection == ["knights_donation", "arena"]


def test_controller_rejects_unknown_route():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.toggle("nope", True)


def test_ready_needs_at_least_one_tick():
    controller = DesktopController(worker=FakeWorker())

    controller.toggle("arena", True)
    assert controller.ready is True

    controller.toggle("arena", False)
    assert controller.ready is False


def test_survivor_cannot_be_chained_with_other_routes():
    """「活动」要人工把游戏停在选卡页、跑起来也不回家 ⇒ 与其它路线互斥。

    用户 2026-09-29 拍板：勾它就清掉别的（会提示），勾别的就清掉它。两个方向都要拦。
    """
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("arena", True)

    controller.toggle("survivor", True)
    assert controller.selection == ["survivor"]

    controller.toggle("story", True)
    assert controller.selection == ["story"]


def test_controller_forces_hero_synthesis_to_one_cycle():
    """英雄合成跑完一遍列表就结束 ⇒ 界面给多少都打回 1 次。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.toggle("hero_synthesis", True)
    controller.set_cycles("hero_synthesis", 99)
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.cycles == {"hero_synthesis": 1}


def test_edited_cycle_reaches_the_worker():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    controller.toggle("arena", True)
    controller.set_cycles("arena", 4)

    controller.start()

    assert worker.request.modes == ("arena",)
    assert worker.request.cycles == {"arena": 4}


def test_cycle_of_a_capped_route_is_snapped_back_to_its_default():
    """世界首领战每天就 2 次、骑士团捐赠就 1 次 ⇒ 界面给多少都打回默认值。"""
    controller = DesktopController(worker=FakeWorker())

    controller.set_cycles("world_boss", 9)
    controller.set_cycles("knights_donation", 9)

    assert controller.cycles["world_boss"] == 2
    assert controller.cycles["knights_donation"] == 1


def test_cycle_must_be_a_positive_integer():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError, match="正整数"):
        controller.set_cycles("arena", 0)


def test_shop_refresh_accepts_zero_cycles_and_keeps_it():
    """「刷书签」是唯一允许 0 次的路线（用户 2026-09-29 拍板）。

    0 次 = 照常进店扫一遍、把自动刷新出来的买掉，但一次都不付费刷新。
    界面必须能收下这个 0 并原样传给子进程，否则默认那一档根本点不动。
    """
    worker = FakeWorker()
    controller = DesktopController(worker=worker)

    controller.toggle("shop_refresh", True)
    controller.set_cycles("shop_refresh", 0)
    controller.apply_preflight(passed_preflight())
    controller.start()

    assert controller.cycles["shop_refresh"] == 0
    assert worker.request.cycles == {"shop_refresh": 0}


def test_shop_refresh_still_rejects_negative_cycles():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError, match="负数"):
        controller.set_cycles("shop_refresh", -1)


def test_other_routes_keep_rejecting_zero_cycles():
    """「0 次」这条口子只开给刷书签 —— 别的路线多加一条就是语义泄漏。

    只挑 ``cycles_editable=True`` 的路线：固定次数那几条（世界首领战 / 骑士团捐赠 /
    迷宫强化石 / 英雄合成）会把输入直接打回默认值、根本走不到校验那一步。
    """
    controller = DesktopController(worker=FakeWorker())

    for mode in ("arena", "story", "expedition", "fodder"):
        with pytest.raises(ValueError, match="正整数"):
            controller.set_cycles(mode, 0)


def test_cycle_rejects_unknown_route():
    controller = DesktopController(worker=FakeWorker())

    with pytest.raises(ValueError):
        controller.set_cycles("nope", 3)


def test_experimental_route_requires_confirmation():
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("fodder", True)
    controller.apply_preflight(passed_preflight())

    assert controller.needs_experimental_confirmation is True


def test_ticking_another_route_preserves_successful_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.toggle("arena", True)

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
    controller.toggle("story", True)
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


def test_controller_refuses_start_with_empty_selection():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())

    with pytest.raises(RuntimeError, match="至少"):
        controller.start()


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
    controller.toggle("story", True)
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


def test_start_rechecks_environment_and_validates_every_ticked_route(
    tmp_path, tk_window
):
    """勾了几条就查几套模板 —— 提前发现比跑到一半才失败好。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.toggle("arena", True)
    controller.toggle("story", True)
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

    app._start()
    tk_window.update()

    assert calls == [
        ("preflight", "emulator"),
        ("arena", app.template_root),
        ("story", app.template_root),
    ]
    assert worker.request.modes == ("arena", "story")


def test_route_template_failure_does_not_start_worker(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.toggle("story", True)
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
    assert "路线资源检查失败" in app.environment_var.get()
    assert "主线" in app.environment_var.get()


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
# 「每日任务」界面区块：勾选 + 序号 + 次数
# --------------------------------------------------------------------------


def test_task_panel_renders_a_checkbox_and_a_cycle_input_per_route(
    tmp_path, tk_window
):
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    assert list(app._route_buttons) == [route.mode for route in ROUTES]
    assert list(app.cycle_vars) == [route.mode for route in ROUTES]
    assert all(var.get() is False for var in app.route_vars.values())
    assert app.cycle_vars["world_boss"].get() == "2"
    assert app.cycle_vars["arena"].get() == "1"
    # 「刷书签」默认 **0 次**（只扫不刷新，用户 2026-09-29 拍板）——
    # 次数框必须能显示 0，且箭头下限跟着路线走，否则会出现
    # 「框里写着 0、按一下上去就再也回不到 0」的僵尸状态。
    assert app.cycle_vars["shop_refresh"].get() == "0"
    assert int(app._cycle_inputs["shop_refresh"].cget("from")) == 0
    assert int(app._cycle_inputs["arena"].cget("from")) == 1
    assert str(app._cycle_inputs["world_boss"].cget("state")) == "disabled"
    assert str(app._cycle_inputs["arena"].cget("state")) == "normal"


def test_task_panel_columns_are_derived_from_the_screen_budget(tmp_path, tk_window):
    """路线摊成几列由 `theme.route_columns` 算，**不许写死**。

    用户 2026-09-25 与 2026-09-29 两次要求「别太长」，又明说「以后还有很多路线」
    ⇒ 行数封顶 `ROUTE_ROWS_TARGET`，多出来的用**加列**解决。这条测试钉住这两件事：
    退回两列（10 条要排 5 行）会失败，把列数写死成别的值也会失败。
    """
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    screen_logical_width = tk_window.winfo_screenwidth() / app.theme.scale
    columns = theme.route_columns(
        route_count=len(ROUTES), screen_logical_width=screen_logical_width
    )
    assert app._route_columns_count == columns

    cells = [
        (
            int(button.master.grid_info()["row"]),
            int(button.master.grid_info()["column"]),
        )
        for button in app._route_buttons.values()
    ]
    # 一条路线一「格」（勾选框 / 次数框 / 「次」在格**内部**贴着排），
    # 所以这里问的是格子本身落在第几行第几列。
    assert {column for _, column in cells} == set(range(columns))
    rows = -(-len(ROUTES) // columns)
    assert max(row for row, _ in cells) == rows
    # 屏幕装得下满配列数时，行数必须封在上限内 —— 这就是「别太长」的量化。
    if int(screen_logical_width // theme.CELL_MIN_WIDTH) >= theme.ROUTE_COLUMNS_MAX:
        assert rows <= theme.ROUTE_ROWS_TARGET


def test_ticking_a_route_shows_its_position_in_the_label(tmp_path, tk_window):
    """序号就是执行位次：勾了才出现，取消之后后面的人自动顺移。"""
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app.route_vars["arena"].set(True)
    app._on_toggle("arena")
    app.route_vars["story"].set(True)
    app._on_toggle("story")

    assert app._route_buttons["arena"].cget("text").startswith("①")
    assert app._route_buttons["story"].cget("text").startswith("②")

    app.route_vars["arena"].set(False)
    app._on_toggle("arena")

    assert app._route_buttons["story"].cget("text").startswith("①")


def test_ticking_survivor_clears_the_others_on_screen(tmp_path, tk_window):
    """互斥必须反映到界面上 —— controller 清了、勾选框还亮着就是骗人。"""
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()
    app.route_vars["arena"].set(True)
    app._on_toggle("arena")

    app.route_vars["survivor"].set(True)
    app._on_toggle("survivor")

    assert controller.selection == ["survivor"]
    assert app.route_vars["arena"].get() is False


def test_a_capped_cycle_typed_in_the_panel_is_snapped_back(tmp_path, tk_window):
    """框是灰的也拦不住有人往里塞字符 ⇒ 收的时候打回默认值并回显。"""
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()
    app.route_vars["world_boss"].set(True)
    app._on_toggle("world_boss")
    app.cycle_vars["world_boss"].set("9")

    assert app._collect_cycles() is True
    assert app.cycle_vars["world_boss"].get() == "2"


def test_an_invalid_cycle_blocks_the_start(tmp_path, tk_window):
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
    app.route_vars["arena"].set(True)
    app._on_toggle("arena")
    app.cycle_vars["arena"].set("0")

    with patch(
        "auto_game_unified.desktop.app.messagebox.showerror"
    ) as showerror:
        app._start()
    tk_window.update()

    assert worker.request is None
    assert showerror.called
    assert app.cycle_vars["arena"].get() == "1"


def test_start_uses_the_edited_panel_cycle(tmp_path, tk_window):
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
    app.route_vars["arena"].set(True)
    app._on_toggle("arena")
    app.cycle_vars["arena"].set("4")

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=True,
    ):
        app._start()
    tk_window.update()

    assert worker.request.cycles["arena"] == 4


def test_start_runs_preflight_then_starts_worker(tmp_path, tk_window):
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
    tk_window.update_idletasks()
    app.route_vars["arena"].set(True)
    app._on_toggle("arena")

    app._start()
    tk_window.update()

    assert calls == ["emulator"]
    assert worker.request.modes == ("arena",)


def test_start_warns_when_nothing_is_ticked(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    with patch(
        "auto_game_unified.desktop.app.messagebox.showwarning"
    ) as showwarning:
        app._start()

    assert worker.request is None
    assert showwarning.called


def test_start_aborts_when_preflight_blocks(tmp_path, tk_window):
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=blocked_preflight,
        thread_factory=ImmediateThread,
    )
    tk_window.update_idletasks()
    app.route_vars["arena"].set(True)
    app._on_toggle("arena")

    app._start()
    tk_window.update()

    assert worker.request is None
    assert app.environment_var.get() == "没有找到雷电窗口"


def test_start_cancelled_when_selection_changes_mid_check(tmp_path, tk_window):
    """复检期间用户改了勾选 ⇒ 取消启动（免得跑的不是他看到的那套）。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    controller.toggle("arena", True)

    def preflight_and_flip(window_backend):
        # 复检跑在后台线程里；用户此时又动了勾选。
        controller.toggle("arena", False)
        return passed_preflight()

    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=preflight_and_flip,
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert "已变化" in app.environment_var.get()


def test_start_cancelled_when_cycles_change_mid_check(tmp_path, tk_window):
    """次数也是「他看到的那一套」的一部分 ⇒ 复检期间改了同样要作废。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    controller.toggle("arena", True)

    def preflight_and_edit(window_backend):
        controller.set_cycles("arena", 6)
        return passed_preflight()

    app = DesktopApp(
        tk_window,
        controller=controller,
        project_root=tmp_path,
        preflight_runner=preflight_and_edit,
        thread_factory=ImmediateThread,
    )

    app._start()
    tk_window.update()

    assert worker.request is None
    assert "已变化" in app.environment_var.get()


def test_declining_experimental_warning_does_not_start(tmp_path, tk_window):
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
    app.route_vars["fodder"].set(True)
    app._on_toggle("fodder")

    with patch(
        "auto_game_unified.desktop.app.messagebox.askyesno",
        return_value=False,
    ):
        app._start()
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
    clock = FakeClock()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    # 勾选要在「运行中」之前做 —— 运行期间本来就不许改勾选（见 toggle 的守卫）。
    controller.toggle("arena", True)
    worker.running = True
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
