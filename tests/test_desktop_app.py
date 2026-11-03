from pathlib import Path
import sys

import pytest

pytest.importorskip("tkinter")
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from auto_game_unified.desktop import app as app_module
from auto_game_unified.desktop import theme
from auto_game_unified.desktop.app import DesktopApp, DesktopController, fit_window_size
from auto_game_unified.desktop.catalog import (
    ROUTES,
    group_description,
    grouped_routes,
    route_by_name,
    routes_in_group,
)
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
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        # 环境级偶发：一次进程里建第二个 Tk 根时，偶尔会报
        # "Can't find a usable init.tcl"（全量 2026-10-20 撞过一次，单跑这个文件不复现）。
        # 跳过而不是整轮变红 —— 目录、Tcl 本身都好好的，换个进程就能起。
        pytest.skip(f"Tk 起不来：{exc}")
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
    # ⚠️ 竞技场默认 **10 次**（用户 2026-10-18 拍板）—— 原来是 1，等于
    # 「点开只打一场就走」。见 `modes.MODE_SPECS["arena"]` 那里的注释。
    assert controller.cycles["arena"] == 10
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
    controller.toggle("arena", True)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert worker.request.backend == "pc"


def test_the_pc_backend_refuses_routes_without_pc_acceptance():
    """PC 后端露面了，但**没验收的路线**不许在界面上跑 —— 那是一次必然失败的实跑。

    样本用 ``world_boss``：它在 PC 上还没打通（点「世界首领战」徽章四次都没反应，
    见 ``.workbuddy/memory/2026-11-02.md`` 的 10:10 一节）。挑样本时别用已经放行的
    路线（``catalog.PC_READY_ROUTES``），那会把这条断言变成永假。
    ``tower`` 曾经是这里的样本，2026-11-03 已放行，所以换掉了。
    """
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("world_boss", True)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    with pytest.raises(RuntimeError) as caught:
        controller.start()

    assert "还没有在 PC 客户端上通过验收" in str(caught.value)


def test_the_pc_backend_allows_the_verified_arena_route():
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("arena", True)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert controller.worker.request.modes == ("arena",)


def test_the_pc_backend_allows_the_verified_story_route():
    """主线 2026-11-01 放行：一轮完整实跑通过，第二轮由用户在界面自测。"""
    controller = DesktopController(worker=FakeWorker())
    controller.toggle("story", True)
    controller.select_backend("pc")
    controller.apply_preflight(passed_preflight())

    controller.start()

    assert controller.worker.request.modes == ("story",)


def test_the_ui_shows_the_pc_backend_button(tk_window, tmp_path):
    """PC 按钮要真的画出来 —— 否则「支持 PC」只是命令行里的一句空话。"""
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )

    assert len(app._backend_buttons) == 2
    labels = [button.cget("text") for button in app._backend_buttons]
    assert labels == ["模拟器（雷电）", "PC 客户端"]
    assert app.backend_var.get() == "emulator"


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


def test_window_size_keeps_content_but_does_not_fill_the_screen():
    """⚠️ 2026-10-09 用户反馈：窗口「太大了」、日志看不清。

    旧版把宽度顶到 ``屏幕-80``、再用同一尺寸做 ``minsize`` ⇒ 铺满屏幕且拖不小。
    现在**初始尺寸不该超过屏幕的 85%**，也不该超过 ``INITIAL_MAX_WIDTH``。
    """
    width, height = fit_window_size(
        requested=(1613, 1208),
        screen=(3200, 2000),
    )

    assert width <= 3200 * 0.85
    assert width <= 1280
    assert height <= 2000 * 0.85


def test_window_size_stays_inside_a_small_screen():
    width, height = fit_window_size(
        requested=(1500, 1100),
        screen=(1366, 768),
    )

    assert width <= 1366
    assert height <= 768
    # 屏幕小到放不下内容时，也得退到「最小可用尺寸」而不是崩掉或给负数。
    assert width >= 900
    assert height >= 600


def test_window_size_never_goes_below_the_minimum_on_a_tiny_screen():
    width, height = fit_window_size(
        requested=(600, 400),
        screen=(800, 480),
    )

    assert (width, height) == (900, 600)


def test_initial_window_is_smaller_than_the_screen_and_shrinkable(tmp_path, tk_window):
    """初始尺寸要留出屏幕空间，**且**最小尺寸必须**小于**初始尺寸（能缩小）。

    这条守的是用户那句「不能自由地调节这个分辨率，拖动现在太大了」：
    只要 ``minsize`` 还等于初始尺寸，窗口就一点拖不动。
    """
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    initial_width, initial_height = (
        int(value) for value in tk_window.winfo_geometry().split("+")[0].split("x")
    )
    min_width, min_height = (int(value) for value in tk_window.wm_minsize())

    assert min_width < initial_width, "最小宽度必须小于初始宽度，否则窗口拖不小"
    assert min_height < initial_height, "最小高度必须小于初始高度，否则窗口拖不小"

    # 最小尺寸 = ``MIN_WINDOW_*`` 逻辑像素经 ``theme.px`` 换算 ——
    # ⚠️ 断言走**换算关系**而不是写死数字（测试机缩放因子不固定）。
    assert (min_width, min_height) == (
        app.theme.px(900),
        app.theme.px(600),
    )


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

    # ⚠️ 这里断言的是**集合相同 + 顺序 = 分组顺序**，不是 `ROUTES` 的书写顺序：
    # 分组改版后（2026-10-08 三组，2026-10-18 拆成四组），面板按
    # 「每日 / 按需 / 赛季 / 活动」四段渲染，所以控件是按**分组顺序**建出来的
    # （「按需」那几条被挪到「每日」全组之后）。断言 `ROUTES` 顺序
    # 会把「分组生效了」这件正事判成失败。
    assert set(app._route_buttons) == {route.mode for route in ROUTES}
    assert list(app._route_buttons) == [
        route.mode for _group, routes in grouped_routes() for route in routes
    ]
    assert list(app.cycle_vars) == list(app._route_buttons)
    # 每一组内部的顺序必须保持 `ROUTES` 的书写顺序（组内不许被打乱）。
    for _group, routes in grouped_routes():
        expected = [route.mode for route in routes]
        actual = [mode for mode in app._route_buttons if mode in set(expected)]
        assert actual == expected
    assert all(var.get() is False for var in app.route_vars.values())
    assert app.cycle_vars["world_boss"].get() == "2"
    # 竞技场默认 10 次（用户 2026-10-18 拍板，原来是 1）。
    assert app.cycle_vars["arena"].get() == "10"
    # 「刷书签」默认 **0 次**（只扫不刷新，用户 2026-09-29 拍板）——
    # 次数框必须能显示 0，且箭头下限跟着路线走，否则会出现
    # 「框里写着 0、按一下上去就再也回不到 0」的僵尸状态。
    assert app.cycle_vars["shop_refresh"].get() == "0"
    # ⚠️ 2026-10-22：次数框从 Spinbox 换成 Entry（Spinbox 在 Windows 上输入区永远是
    # 系统白，暗色主题吃不进去），**「箭头下限」这个保护点随之消失** —— 0 是否合法
    # 改由 ``ModeSpec.min_cycles`` + ``DesktopController.set_cycles`` 守。
    assert str(app._cycle_inputs["world_boss"].cget("state")) == "disabled"
    assert str(app._cycle_inputs["arena"].cget("state")) == "normal"


def test_task_panel_columns_are_derived_from_the_screen_budget(tmp_path, tk_window):
    """路线摊成几列由 `theme.route_columns` 算，**不许写死**。

    用户 2026-09-25 与 2026-09-29 两次要求「别太长」，又明说「以后还有很多路线」
    ⇒ 行数封顶 `ROUTE_ROWS_TARGET`，多出来的用**加列**解决。这条测试钉住这两件事：
    退回两列（10 条要排 5 行）会失败，把列数写死成别的值也会失败。

    ⚠️ 2026-10-08 分组改版后**每一组还额外占一行标题**，所以格子不再从第 1 行
    连续排到底 —— 这里的行号必须连同「标题占位」一起算，否则会误判成「行数超标」。
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

    cells = {
        mode: (
            int(button.master.grid_info()["row"]),
            int(button.master.grid_info()["column"]),
        )
        for mode, button in app._route_buttons.items()
    }
    # 一条路线一「格」（勾选框 / 次数框 / 「次」在格**内部**贴着排），
    # 所以这里问的是格子本身落在第几行第几列。
    assert {column for _, column in cells.values()} == set(range(columns))

    # 逐组核对：标题占 1 行，然后该组的格子按 `columns` 折行接着往下排。
    # 用 `grouped_routes()` 走真实分组（面板渲染的就是它），但**行号从 0 起算**
    # 是这里独立写死的 —— 不是问实现「你觉得该从第几行开始」。
    # ⚠️ 2026-10-18 起是 **0** 而不是 1：卡头那一条（「每日任务」+ 操作说明）
    # 已经整块删掉，第一组标题直接坐在第 0 行。
    for route in ROUTES:
        assert route.mode in cells, f"{route.mode} 这一行没画出来"
    # 最后一行 = 最后一个分组的最后一行格子。独立算一遍：
    last_group_routes = grouped_routes()[-1][1]
    grids_above = sum(
        -(-len(routes) // columns) for _g, routes in grouped_routes()[:-1]
    )
    # 起始行 0 + 前面各组(标题1行 + 格子若干行) + 本组标题1行 + 本组格子若干行
    last_row = 0 + (len(grouped_routes()) - 1 + grids_above) + -(
        -len(last_group_routes) // columns
    )
    actual_rows = {row for row, _ in cells.values()}
    assert max(actual_rows) == last_row
    # 屏幕装得下满配列数时，**每组**的行数必须封在上限内 —— 这就是「别太长」的量化。
    if int(screen_logical_width // theme.CELL_MIN_WIDTH) >= theme.ROUTE_COLUMNS_MAX:
        for _group, routes in grouped_routes():
            assert -(-len(routes) // columns) <= theme.ROUTE_ROWS_TARGET


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
    # 填坏了要**回显成原值**（竞技场的默认值是 10，见 `modes.MODE_SPECS`）。
    assert app.cycle_vars["arena"].get() == "10"


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


def test_formerly_experimental_route_starts_without_asking_again(tmp_path, tk_window):
    """路线分级取消后，原先标「实验」的路线也要一问不问就开跑。

    2026-10-20 用户拍板：十五条路线他都实机验证过了，界面上不再有正式 / 实验之分，
    启动前那道「实验功能提醒」也一起删掉。这条断言 askyesno **一次都没被调用**
    —— 不是「调了但回 True」，否则那道确认只是变了个说法。
    """
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

    with patch("auto_game_unified.desktop.app.messagebox.askyesno") as confirm:
        app._start()
    tk_window.update()

    assert not confirm.called
    assert worker.request is not None


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


# --------------------------------------------------------------------------
# 四分组渲染 + 组标题上的整组勾选（用户 2026-10-18 改版）
#
# ⚠️ 2026-10-18 之前这里测的是卡头右侧那三颗「全选 / 全选（不含活动）/ 取消全选」
# 按钮。用户当天把它们整排撤掉，改成**每组标题自己就是勾选框**（点一下整组勾上、
# 再点一下整组取消）。所以这批用例测的是组勾选框，不是按钮。
# --------------------------------------------------------------------------


def test_task_panel_renders_a_group_header_per_group(tmp_path, tk_window):
    """面板按「每日 / 按需 / 赛季 / 活动」分四段，每段标题**本身就是勾选框**。

    ⚠️ 标题文案与顺序**写死**在断言里 —— 不许调 `catalog.GROUPS` 来比对，
    那等于问实现「你自己觉得该显示啥」。
    ⚠️ 顺序按 **grid 行号**排，不按遍历顺序：`_task_panel_descendants()` 是深度
    不限的遍历，兄弟控件的先后取决于遍历策略（栈是后进先出），拿它当「视觉顺序」
    是错的。屏幕上从上到下 = grid 行号从小到大。
    """
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    group_names = ("每日", "按需", "赛季", "活动")
    headers = [
        widget
        for widget in app._task_panel_descendants()
        if isinstance(widget, ttk.Checkbutton) and widget.cget("text") in group_names
    ]
    headers.sort(key=lambda box: int(box.grid_info()["row"]))

    assert [box.cget("text") for box in headers] == list(group_names)

    rows = [int(box.grid_info()["row"]) for box in headers]
    assert rows == sorted(rows) and len(set(rows)) == 4, f"标题行号不正常：{rows}"

    # 每个分组标题必须排在**它那一组的第一条路线**之前（否则标题挂在人家下面）。
    for header, (group, routes) in zip(headers, grouped_routes(), strict=True):
        title_row = int(header.grid_info()["row"])
        for route in routes:
            cell_row = int(app._route_buttons[route.mode].master.grid_info()["row"])
            assert title_row < cell_row, (
                f"「{group}」的标题（第 {title_row} 行）没排在 "
                f"{route.label}（第 {cell_row} 行）前面"
            )


def test_the_old_bulk_buttons_are_gone(tmp_path, tk_window):
    """卡头那三颗批量按钮必须**真的没了**（用户 2026-10-18：「这一行全部去掉」）。

    留着它们不只是多余 —— 它们占着卡头右侧的宽度，说明文字被挤得折更多行，
    而那正是用户要腾出来的高度。
    """
    app = DesktopApp(
        tk_window,
        controller=DesktopController(worker=FakeWorker()),
        project_root=tmp_path,
    )
    tk_window.update_idletasks()

    texts = {
        widget.cget("text")
        for widget in app._task_panel_descendants()
        if isinstance(widget, ttk.Button)
    }
    assert not ({"全选", "全选（不含活动）", "取消全选"} & texts), texts


def test_a_group_header_ticks_the_whole_group(tmp_path, tk_window):
    """点「每日」⇒ 那 7 条全勾上，**别的组一条都不动**。"""
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    tk_window.update_idletasks()

    expected = [route.mode for route in routes_in_group("每日")]
    assert controller.selection == expected
    # 真值表独立算一遍（不拿 `routes_in_group` 自证条数）。
    assert expected == [
        "arena",
        "shop_refresh",
        "world_boss",
        "knights_donation",
        "labyrinth_stone",
        "sanctuary",
        "community",
    ]
    for mode in expected:
        assert app.route_vars[mode].get() is True, mode
    # 别的组一条都没被勾上。
    assert app.route_vars["story"].get() is False
    assert app.route_vars["tower"].get() is False
    assert app._group_vars["按需"].get() is False


def test_a_group_header_untickes_the_whole_group_and_leaves_others_alone(
    tmp_path, tk_window
):
    """再点一下「每日」⇒ 整组取消，**别的组保留**。

    这正是用户要的「取消全选某一类」—— 旧的「取消全选」会把所有组一起清空，
    做不到「只清这一类」。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    app._group_vars["按需"].set(True)
    app._on_group_toggle("按需")
    assert len(controller.selection) == 12, controller.selection

    app._group_vars["每日"].set(False)
    app._on_group_toggle("每日")
    tk_window.update_idletasks()

    assert controller.selection == [
        route.mode for route in routes_in_group("按需")
    ]
    for mode in ("arena", "shop_refresh", "world_boss"):
        assert app.route_vars[mode].get() is False, mode
    assert app.route_vars["story"].get() is True
    # 底部说明不许被清空 —— 它读的是「最后勾的那条」，按需那组还在。
    assert app.route_description_var.get() != ""


def test_unticking_one_route_drops_the_group_box(tmp_path, tk_window):
    """手动取消组内一条 ⇒ 组标题的勾**自动消失**（= 这一组只是部分选中）。

    ⚠️ 这条守的是「界面不许自相矛盾」：组标题还打着勾、里面却有一条没勾，
    会让人以为点一下能把那条补上，实际点下去是整组**重勾**。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    assert app._group_vars["每日"].get() is True

    # 手动取消其中一条（走单条那条路，和真实点击一致）。
    app.route_vars["arena"].set(False)
    app._on_toggle("arena")
    tk_window.update_idletasks()

    assert app._group_vars["每日"].get() is False
    # 其余六条仍然勾着 —— 组标题不勾 ≠ 整组被清空。
    assert len(controller.selection) == 6, controller.selection
    # 再点一下组标题 = 整组**重新勾上**（把 arena 补回末尾）。
    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    assert len(controller.selection) == 7
    assert controller.selection[-1] == "arena"


def test_the_group_box_explains_the_group_not_a_route(tmp_path, tk_window):
    """点分组前面的框 ⇒ 说明区讲的是**这一组是什么**，不是组里最后那条路线。

    用户原话（2026-10-20）：「每日 / 按需 / 赛季 前面的框，点击的时候是对他们
    三个的说明，不是里面的路线说明」。整组勾完 `selection[-1]` 是组里最后一条，
    光读 selection 会以为「圣域收菜」的说明就是「每日」的说明。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    tk_window.update_idletasks()

    text = app.route_description_var.get()
    assert text == f"【每日】\n{group_description('每日')}"
    # 组里任何一条路线的说明都不能混进来（它们都以「跑一轮 / 跑一遍」分段）。
    for route in routes_in_group("每日"):
        assert route.description not in text, route.mode


def test_clicking_one_route_takes_the_description_back(tmp_path, tk_window):
    """整组勾完再去点具体某一条 ⇒ 说明区切回那条路线。

    ⚠️ 这里必须点一条**当时没勾的**路线：勾一条已经勾着的，`controller.toggle`
    只会把它留在原位，不会是「最后勾的那条」，断言就测不到这次切换。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["按需"].set(True)
    app._on_group_toggle("按需")
    assert app.route_description_var.get().startswith("【按需】")

    app.route_vars["arena"].set(True)
    app._on_toggle("arena")
    tk_window.update_idletasks()

    arena = route_by_name("arena")
    assert app.route_description_var.get() == f"【{arena.label}】\n{arena.description}"


def test_unticking_the_group_drops_the_group_explanation(tmp_path, tk_window):
    """整组取消 ⇒ 说明区留空，不许挂着一段已经不成立的说明。"""
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["赛季"].set(True)
    app._on_group_toggle("赛季")
    app._group_vars["赛季"].set(False)
    app._on_group_toggle("赛季")
    tk_window.update_idletasks()

    assert app.route_description_var.get() == ""
    assert app._detail_group is None


def test_a_stale_group_explanation_falls_back_to_the_routes(tmp_path, tk_window):
    """那一组被别处清空了，说明区要退回「最后勾的那条」，不能继续讲那一组。

    目前唯一的来路是「活动」互斥（勾它会清掉别的组）。这里直接把状态摆成
    「停在每日的分组说明上、每日却一条都没勾」，守住 `_refresh_route_details`
    里那道回退 —— 少了它，界面会显示一段与勾选对不上的文字。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    controller.toggle("tower", True)
    controller.clear_group("每日")
    app._refresh_route_details()
    tk_window.update_idletasks()

    tower = route_by_name("tower")
    assert app.route_description_var.get() == f"【{tower.label}】\n{tower.description}"
    assert app._detail_group is None


def test_group_selection_appends_after_what_is_already_ticked(tmp_path, tk_window):
    """先把某几条勾上、再点整组 ⇒ 新来的**追加在末尾**，不抹掉原来的顺序。

    ⚠️ 这是「勾选先后就是执行顺序」那条语义在整组操作下的落点：点赞组的用户
    表达的是「现在开始跑这一组」，所以它们排在已勾内容之后。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app.route_vars["story"].set(True)
    app._on_toggle("story")
    app.route_vars["tower"].set(True)
    app._on_toggle("tower")

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")

    assert controller.selection[:2] == ["story", "tower"]
    assert controller.selection[2:] == [
        route.mode for route in routes_in_group("每日")
    ]


def test_the_event_group_replaces_other_selections(tmp_path, tk_window):
    """「活动」只能单独跑 ⇒ 勾上它就是**只剩活动组的一条**，其余全灭。

    活动组现在有两条（活动小游戏 + 活动剧情），两条都要求人先把游戏停在各自的
    页面 ⇒ **组内也只能留一条**，组勾选勾的是该组第一条；要跑另一条就单独点它。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    app._on_group_toggle("每日")
    assert controller.selection
    app._group_vars["活动"].set(True)
    app._on_group_toggle("活动")
    tk_window.update_idletasks()

    assert controller.selection == ["survivor"]
    assert app.route_vars["survivor"].get() is True
    assert app.route_vars["activity_story"].get() is False
    assert app.route_vars["arena"].get() is False

    # 单独勾「活动剧情」⇒ 反过来把「活动小游戏」清掉（`toggle` 那一支）。
    app.route_vars["activity_story"].set(True)
    app._on_toggle("activity_story")
    tk_window.update_idletasks()

    assert controller.selection == ["activity_story"]
    assert app.route_vars["survivor"].get() is False
    # 整组被清掉之后，那些组的勾选框也得跟着灭。
    assert app._group_vars["每日"].get() is False


def test_group_numbers_reflect_panel_order(tmp_path, tk_window):
    """整组勾完之后每行的序号（①②③…）必须按面板顺序发下去。

    ⚠️ 这里**独立**算前缀（头 10 位圈码、之后阿拉伯数字），不调
    `app._position_prefix` —— 拿被测函数去算「该显示什么」等于没断言。
    「每日」+「按需」= 12 条，会跨过第 10 位这个坎，正好覆盖曾经的 IndexError。
    """
    controller = DesktopController(worker=FakeWorker())
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    for group in ("每日", "按需"):
        app._group_vars[group].set(True)
        app._on_group_toggle(group)
    tk_window.update_idletasks()

    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    assert len(controller.selection) > len(circled), "要跨过圈码用尽的那一位才有意义"
    for index, mode in enumerate(controller.selection):
        expected = circled[index] if index < len(circled) else f"{index + 1}."
        assert app._route_buttons[mode].cget("text").startswith(expected), (
            f"{mode} 排第 {index + 1} 位，序号应为 {expected!r}"
        )


def test_group_toggle_is_refused_while_running(tmp_path, tk_window):
    """运行期间不许改勾选 —— 组标题这条入口也要守住（和单条 `toggle` 一样）。"""
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.apply_preflight(passed_preflight())
    worker.running = True
    app = DesktopApp(tk_window, controller=controller, project_root=tmp_path)
    tk_window.update_idletasks()

    app._group_vars["每日"].set(True)
    with patch.object(app_module.messagebox, "showwarning") as showwarning:
        app._on_group_toggle("每日")

    assert showwarning.called
    assert controller.selection == []
    # 被拒绝的那一次点击要**撤回去**：勾选框不许停在「已勾」上骗人。
    assert app._group_vars["每日"].get() is False
