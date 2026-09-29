"""「每日任务」编排层的测试。

这里守的是「编排」而不是「路线」：路线本身各有自己的测试，本模块只负责
**按次序调它们、失败跳过、段间回大厅、最后汇总**。

⚠️ 与路线测试同一条教训（2026-09-25 两次事故都发生在状态机与主循环**之间**）：
判据再好，没接进循环就等于没写。所以这里的重点用例全部走 ``run_daily_tasks``
这个真入口，而不是单独测小函数。
"""

from __future__ import annotations

import pytest

from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.games.epic7 import daily_tasks
from auto_game_unified.games.epic7.daily_tasks import (
    DAILY_TASKS,
    DailyOutcome,
    DailyReport,
    ensure_at_lobby,
    normalize_selection,
    run_daily_tasks,
)


# --------------------------------------------------------------------------
# 清单本身
# --------------------------------------------------------------------------


def test_daily_list_keeps_the_agreed_order():
    """``DAILY_TASKS`` 是**默认清单**（命令行不带 ``--daily-tasks`` 时按它跑）。

    界面不读它 —— 界面把用户勾的那几条按勾选先后传下来。次序本身仍有讲究：
    世界首领战与骑士团捐赠都从骑士团进，放一起省一趟导航。
    """
    assert [task.mode for task in DAILY_TASKS] == [
        "world_boss",
        "knights_donation",
        "sanctuary",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    ]
    # 名字从 ``modes.MODE_SPECS.label`` 派生 —— 这里改叫「刷书签」是用户
    # 2026-09-27 拍板的（原先是「商店刷新」，与别处的「刷书签」不一致）。
    assert [task.label for task in DAILY_TASKS] == [
        "世界首领战",
        "骑士团捐赠",
        "圣域收菜",
        "刷书签",
        "迷宫强化石",
        "竞技场",
    ]


def test_daily_task_labels_come_from_mode_specs():
    """名字与次数都派生自 ``MODE_SPECS``，本模块不再自己留一份。

    这条防「又抄回去」：如果哪天有人给 ``DailyTask`` 加回 ``label`` / ``cycles``
    字段，这条会立刻发现。
    """
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    for task in DAILY_TASKS:
        spec = MODE_SPECS[task.mode]
        assert task.label == spec.label
        assert task.cycles == spec.default_cycles


def test_every_daily_mode_exists_in_mode_specs():
    """清单里的模式名必须是**真路线**，否则跑起来才发现是接线错误。

    这条同时也是「每日任务不是新路线」的护栏：它只引用已有路线。
    """
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    missing = sorted({task.mode for task in DAILY_TASKS} - set(MODE_SPECS))
    assert missing == [], f"每日任务引用了不存在的路线：{missing}"


def test_daily_cycles_meet_each_route_floor_and_match_known_daily_limits():
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    # 次数下限由路线自己定（``ModeSpec.min_cycles``）：常规路线是 1，
    # 「刷书签」是 0 —— 用户 2026-09-29 拍板：0 次 = 照常进店扫一遍、把自动
    # 刷新出来的买掉，但**一次都不付费刷新**（秘密商店自己会随时间刷新）。
    assert all(
        task.cycles >= MODE_SPECS[task.mode].min_cycles for task in DAILY_TASKS
    )
    # 世界首领战每天固定 2 次；骑士团捐赠请求支援一天一次；
    # 刷书签默认 0 次付费刷新（花天空石那一步不做；界面可改）；
    # 迷宫强化石 / 圣域收菜都是跑一遍。
    limits = {task.mode: task.cycles for task in DAILY_TASKS}
    assert limits["world_boss"] == 2
    assert limits["knights_donation"] == 1
    assert limits["shop_refresh"] == 0
    assert limits["labyrinth_stone"] == 1
    assert limits["sanctuary"] == 1
    # 「0 次」这条口子只开给刷书签：别的路线一旦变成 0 就是接错线了。
    assert [
        task.mode for task in DAILY_TASKS if task.cycles == 0
    ] == ["shop_refresh"]


def test_only_shop_refresh_allows_zero_cycles():
    """``min_cycles=0`` 是**唯一**例外 —— 多开一条就是「次数可以是 0」的语义泄漏。"""
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    zero_routes = [
        name for name, spec in MODE_SPECS.items() if spec.min_cycles == 0
    ]
    assert zero_routes == ["shop_refresh"]
    assert MODE_SPECS["shop_refresh"].min_cycles == 0
    assert MODE_SPECS["shop_refresh"].default_cycles == 0
    # 其余路线的下限仍是 1（不许被顺手改成 0）。
    for name, spec in MODE_SPECS.items():
        if name != "shop_refresh":
            assert spec.min_cycles == 1, f"{name} 的次数下限不该被改动"


# --------------------------------------------------------------------------
# 勾选规整
# --------------------------------------------------------------------------


def test_no_selection_means_the_default_list():
    """``None``（命令行没写 ``--daily-tasks``）⇒ 按默认清单全跑。"""
    assert normalize_selection(None) == (
        "world_boss",
        "knights_donation",
        "sanctuary",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    )


def test_selection_keeps_the_given_order():
    """用户 2026-09-29 拍板：**勾选先后就是执行顺序**，不许再按清单重排。"""
    assert normalize_selection(["arena", "world_boss"]) == ("arena", "world_boss")
    assert normalize_selection(
        ["arena", "labyrinth_stone", "world_boss", "shop_refresh", "knights_donation"]
    ) == (
        "arena",
        "labyrinth_stone",
        "world_boss",
        "shop_refresh",
        "knights_donation",
    )


def test_any_known_route_can_be_selected():
    """能勾的不再限于默认清单那五条 —— 除了「活动」，其余九条都能串。"""
    assert normalize_selection(["story", "arena"]) == ("story", "arena")
    assert normalize_selection(["survivor"]) == ("survivor",)


def test_duplicate_selection_keeps_the_first_position():
    """同一个模式名写两遍只算第一次出现的位置（后面那次不再重排）。"""
    assert normalize_selection(["arena", "story", "arena"]) == ("arena", "story")


def test_single_selection_is_kept():
    assert normalize_selection(["knights_donation"]) == ("knights_donation",)


def test_empty_selection_is_rejected():
    with pytest.raises(ValueError, match="至少"):
        normalize_selection([])


def test_unknown_selection_fails_closed():
    with pytest.raises(ValueError, match="nope"):
        normalize_selection(["arena", "nope"])


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------


def test_summary_line_reports_each_task_and_abort_reason():
    report = DailyReport(
        outcomes=[
            DailyOutcome("world_boss", "世界首领战", "completed"),
            DailyOutcome("knights_donation", "骑士团捐赠", "failed"),
            DailyOutcome("arena", "竞技场", "skipped"),
        ],
        aborted_reason="竞技场 之前无法回到首页（RuntimeError: boom）",
    )

    line = report.summary_line()

    assert "世界首领战 ✓" in line
    assert "骑士团捐赠 ✗" in line
    assert "竞技场 —" in line
    assert "已中止" in line


def test_resource_exhausted_counts_as_ok():
    report = DailyReport(
        outcomes=[DailyOutcome("arena", "竞技场", "resource", "轮次=1")]
    )

    assert report.any_failed is False
    assert "✓" in report.summary_line()


# --------------------------------------------------------------------------
# 执行器：真入口
# --------------------------------------------------------------------------


class FakeRuntime:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.captures = 0

    def capture(self):
        self.captures += 1
        return object()

    def log(self, message: str) -> None:
        self.lines.append(message)

    def log_line(self, message: str) -> None:  # 兼容别的调用习惯
        self.lines.append(message)


class FakeObservation:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeNavigator:
    def __init__(self, *, lobby: bool = True, return_home_error: Exception | None = None):
        self._lobby = lobby
        self._error = return_home_error
        self.return_calls = 0

    def observe(self, _screen):
        return FakeObservation("lobby" if self._lobby else "battle")

    def return_home(self):
        self.return_calls += 1
        if self._error is not None:
            raise self._error
        self._lobby = True


class FakeResult:
    def __init__(self, *, resource_exhausted: bool = False, completed: int = 1):
        self.resource_exhausted = resource_exhausted
        self.completed_cycles = completed


def test_runs_each_selected_mode_once_in_order():
    calls = []

    def run_mode(**kwargs):
        calls.append(kwargs["spec"].name)
        return FakeResult()

    report = run_daily_tasks(
        selected=None,
        dry_run=True,
        run_mode=run_mode,
    )

    assert calls == [
        "world_boss",
        "knights_donation",
        "sanctuary",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    ]
    assert [o.status for o in report.outcomes] == ["completed"] * 6
    assert report.any_failed is False
    assert report.aborted_reason is None


def test_subset_runs_in_the_given_order():
    """勾选的子集按**给定次序**跑，不再是默认清单的次序。"""
    calls = []

    def run_mode(**kwargs):
        calls.append(kwargs["spec"].name)
        return FakeResult()

    report = run_daily_tasks(
        selected=["arena", "knights_donation"],
        dry_run=True,
        run_mode=run_mode,
    )

    assert calls == ["arena", "knights_donation"]
    assert [o.label for o in report.outcomes] == ["竞技场", "骑士团捐赠"]


def test_cycles_are_passed_from_the_daily_list():
    seen = []

    def run_mode(**kwargs):
        seen.append((kwargs["spec"].name, kwargs["max_cycles"]))
        return FakeResult()

    run_daily_tasks(selected=None, dry_run=True, run_mode=run_mode)

    assert seen == [
        ("world_boss", 2),
        ("knights_donation", 1),
        ("sanctuary", 1),
        ("shop_refresh", 0),
        ("labyrinth_stone", 1),
        ("arena", 1),
    ]


def test_cycles_override_replaces_only_the_named_modes():
    """界面上改过的次数要真的传进 ``run_mode``；没改的仍用默认值。

    这张表是**稀疏覆盖**（不是必须齐全的对照表），所以这里只给 arena 一条。
    """
    seen = []

    def run_mode(**kwargs):
        seen.append((kwargs["spec"].name, kwargs["max_cycles"]))
        return FakeResult()

    run_daily_tasks(
        selected=None,
        dry_run=True,
        run_mode=run_mode,
        cycles_override={"arena": 5},
    )

    assert seen == [
        ("world_boss", 2),
        ("knights_donation", 1),
        ("sanctuary", 1),
        ("shop_refresh", 0),
        ("labyrinth_stone", 1),
        ("arena", 5),
    ]


def test_cycles_override_is_ignored_for_unselected_modes():
    """覆盖表里有没勾的路线 ⇒ 不跑它，也就不该有任何副作用。"""
    seen = []

    def run_mode(**kwargs):
        seen.append(kwargs["spec"].name)
        return FakeResult()

    report = run_daily_tasks(
        selected=["arena"],
        dry_run=True,
        run_mode=run_mode,
        cycles_override={"arena": 2, "world_boss": 9},
    )

    assert seen == ["arena"]
    assert [o.label for o in report.outcomes] == ["竞技场"]


def test_a_failing_task_is_skipped_and_the_rest_still_run():
    """失败策略：跳过继续，最后汇总 —— 一条挂了不能带崩整轮。"""
    calls = []

    def run_mode(**kwargs):
        mode = kwargs["spec"].name
        calls.append(mode)
        if mode == "knights_donation":
            raise RuntimeError("模板缺失")
        return FakeResult()

    report = run_daily_tasks(selected=None, dry_run=True, run_mode=run_mode)

    assert calls == [
        "world_boss",
        "knights_donation",
        "sanctuary",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
    ]
    assert [o.status for o in report.outcomes] == [
        "completed",
        "failed",
        "completed",
        "completed",
        "completed",
        "completed",
    ]
    assert report.any_failed is True
    assert "模板缺失" in report.outcomes[1].detail


def test_resource_exhaustion_is_recorded_but_not_a_failure():
    def run_mode(**kwargs):
        if kwargs["spec"].name == "world_boss":
            return FakeResult(resource_exhausted=True)
        return FakeResult()

    report = run_daily_tasks(selected=None, dry_run=True, run_mode=run_mode)

    assert report.outcomes[0].status == "resource"
    assert report.any_failed is False


def test_manual_stop_ends_the_round_and_keeps_earlier_results():
    calls = []

    def run_mode(**kwargs):
        mode = kwargs["spec"].name
        calls.append(mode)
        if mode == "knights_donation":
            raise ManualStop("用户按了 P")
        return FakeResult()

    report = run_daily_tasks(selected=None, dry_run=True, run_mode=run_mode)

    # 第三条没跑（用户要求停），前两条的结论保留。
    assert calls == ["world_boss", "knights_donation"]
    assert report.stopped_by_user is True
    assert report.outcomes[0].status == "completed"
    assert report.outcomes[1].status == "skipped"


# --------------------------------------------------------------------------
# 段间「确保在首页」
# --------------------------------------------------------------------------


def test_dry_run_never_builds_a_probe():
    """干跑不碰游戏，也就不该去连窗口 —— 建 probe 会让干跑假报「回不了家」。"""
    built = []

    def build_probe():
        built.append(True)
        return FakeRuntime(), FakeNavigator()

    def run_mode(**kwargs):
        return FakeResult()

    run_daily_tasks(
        selected=None,
        dry_run=True,
        run_mode=run_mode,
        build_probe=build_probe,
    )

    assert built == []


def test_live_run_checks_lobby_between_tasks_and_skips_when_already_there():
    """段间已在首页 ⇒ 不用 return_home（省一趟，且零点击）。"""
    runtime = FakeRuntime()
    navigator = FakeNavigator(lobby=True)
    order = []

    def run_mode(**kwargs):
        order.append(("run", kwargs["spec"].name))
        # 每跑完一条就「离开大厅」，逼下一条做检查
        navigator._lobby = False
        return FakeResult()

    def build_probe():
        order.append(("probe",))
        return runtime, navigator

    report = run_daily_tasks(
        selected=["world_boss", "knights_donation"],
        dry_run=False,
        run_mode=run_mode,
        build_probe=build_probe,
    )

    # probe 只建一次（复用），且第一条之前**不**检查。
    assert [item[0] for item in order].count("probe") == 1
    assert order[0] == ("run", "world_boss")
    assert navigator.return_calls == 1  # 只在第二条之前拉了一次
    assert [o.status for o in report.outcomes] == ["completed", "completed"]


def test_live_run_aborts_the_rest_when_it_cannot_get_back_home():
    """回不了首页 ⇒ 放弃剩余任务并写清原因，而不是让下一条去撞同一堵墙。"""
    runtime = FakeRuntime()
    navigator = FakeNavigator(
        lobby=False, return_home_error=RuntimeError("点了 8 次返回还在战斗页")
    )
    calls = []

    def run_mode(**kwargs):
        calls.append(kwargs["spec"].name)
        return FakeResult()

    report = run_daily_tasks(
        selected=None,
        dry_run=False,
        run_mode=run_mode,
        build_probe=lambda: (runtime, navigator),
    )

    assert calls == ["world_boss"]  # 第二条起全部放弃
    assert report.aborted_reason is not None
    assert "骑士团捐赠" in report.aborted_reason
    assert report.outcomes[-1].status == "skipped"
    assert report.any_failed is True


def test_ensure_at_lobby_never_raises():
    """契约：绝不外抛 —— 失败用返回值表达（与路线收尾的约定一致）。"""

    class ExplodingRuntime(FakeRuntime):
        def capture(self):
            raise OSError("窗口没了")

    reason = ensure_at_lobby(
        navigator=FakeNavigator(),
        runtime=ExplodingRuntime(),
        mode_label="竞技场",
    )

    assert reason is not None
    assert "OSError" in reason


def test_ensure_at_lobby_skips_return_home_when_already_in_lobby():
    navigator = FakeNavigator(lobby=True)

    assert ensure_at_lobby(
        navigator=navigator, runtime=FakeRuntime(), mode_label="竞技场"
    ) is None
    assert navigator.return_calls == 0


def test_ensure_at_lobby_logs_which_branch_it_took():
    runtime = FakeRuntime()
    ensure_at_lobby(
        navigator=FakeNavigator(lobby=True), runtime=runtime, mode_label="竞技场"
    )

    assert any("已在首页" in line for line in runtime.lines)


# --------------------------------------------------------------------------
# 与真 main.run_mode 的接线
# --------------------------------------------------------------------------


def test_main_daily_selection_parser_defaults_to_the_default_list():
    from auto_game_unified.main import _parse_daily_selection

    assert _parse_daily_selection("") == [task.mode for task in DAILY_TASKS]
    assert _parse_daily_selection("  ") == [task.mode for task in DAILY_TASKS]
    assert _parse_daily_selection("arena, knights_donation") == [
        "arena",
        "knights_donation",
    ]


def test_main_daily_selection_parser_strips_the_cycle_suffix():
    """``arena:3`` 里的次数不归它管，名字要干净地切出来。"""
    from auto_game_unified.main import _parse_daily_selection

    assert _parse_daily_selection("arena:3") == ["arena"]
    assert _parse_daily_selection("arena:3, knights_donation") == [
        "arena",
        "knights_donation",
    ]


def test_main_daily_cycles_parser_takes_only_the_explicit_ones():
    """没写次数的路线不出现在结果里 ⇒ 执行器照用默认次数。"""
    from auto_game_unified.main import _parse_daily_cycles

    assert _parse_daily_cycles("world_boss,arena:3") == {"arena": 3}
    assert _parse_daily_cycles("") == {}


def test_main_daily_cycles_parser_fails_closed_on_bad_numbers():
    """命令行入口写错了就报错 —— 静默退回默认值等于把「我写了 3」吞掉。"""
    from auto_game_unified.main import _parse_daily_cycles

    with pytest.raises(SystemExit, match="整数"):
        _parse_daily_cycles("arena:三")
    # 下限按路线走：一般路线 0 就是坏值……
    with pytest.raises(SystemExit, match="正整数"):
        _parse_daily_cycles("arena:0")
    with pytest.raises(SystemExit, match="正整数"):
        _parse_daily_cycles("knights_donation:0")
    # ……负数更不行。
    with pytest.raises(SystemExit, match="正整数"):
        _parse_daily_cycles("arena:-1")


def test_main_daily_cycles_parser_allows_zero_for_shop_refresh():
    """界面所有启动都走 ``--daily --daily-tasks``（见 ``desktop/worker.py``）。

    刷书签的默认次数就是 0，界面会把 ``shop_refresh:0`` 原样传下来 ⇒ 这条解析
    必须放行，否则默认那一档一按「开始任务」就报「必须是正整数」。
    """
    from auto_game_unified.main import _parse_daily_cycles

    assert _parse_daily_cycles("shop_refresh:0") == {"shop_refresh": 0}
    assert _parse_daily_cycles("world_boss:2,shop_refresh:0") == {
        "world_boss": 2,
        "shop_refresh": 0,
    }
    # 只开给刷书签：别的路线跟着写 0 仍然报错（同一串里也不行）。
    with pytest.raises(SystemExit, match="正整数"):
        _parse_daily_cycles("shop_refresh:0,arena:0")
    # 刷书签自己也不能为负。
    with pytest.raises(SystemExit, match="不能为负数"):
        _parse_daily_cycles("shop_refresh:-1")


def test_main_run_daily_passes_the_edited_cycles(monkeypatch):
    """接线：``_run_daily`` 必须把解析出来的次数覆盖表传下去。"""
    from auto_game_unified.main import _run_daily, parse_args

    captured = {}

    def fake_run_daily_tasks(**kwargs):
        captured.update(kwargs)
        return DailyReport()

    monkeypatch.setattr("auto_game_unified.main.run_daily_tasks", fake_run_daily_tasks)
    monkeypatch.setattr("auto_game_unified.main._notify_daily", lambda **kwargs: None)

    _run_daily(
        parse_args(
            ["--daily", "--daily-tasks", "arena:4,world_boss", "--live", "--confirm", "RUN"]
        )
    )

    assert captured["selected"] == ["arena", "world_boss"]
    assert captured["cycles_override"] == {"arena": 4}


def test_main_run_daily_wires_the_real_run_mode(monkeypatch):
    """``_run_daily`` 必须把**真的** ``run_mode`` 传下去。

    这是「判据没接上」的典型位置：逻辑都对，但接了别的函数就白写了。
    """
    from auto_game_unified.main import _run_daily, parse_args

    captured = {}

    def fake_run_daily_tasks(**kwargs):
        captured.update(kwargs)
        return DailyReport()

    monkeypatch.setattr("auto_game_unified.main.run_daily_tasks", fake_run_daily_tasks)
    monkeypatch.setattr("auto_game_unified.main._notify_daily", lambda **kwargs: None)

    exit_code = _run_daily(
        parse_args(["--daily", "--daily-tasks", "arena", "--live", "--confirm", "RUN"])
    )

    from auto_game_unified.main import run_mode as real_run_mode

    assert captured["run_mode"] is real_run_mode
    assert captured["dry_run"] is False
    assert captured["selected"] == ["arena"]
    assert exit_code == 0


def test_run_daily_exit_codes(monkeypatch):
    from auto_game_unified import main as main_module

    monkeypatch.setattr(main_module, "_notify_daily", lambda **kwargs: None)

    cases = [
        (DailyReport(), 0),
        (
            DailyReport(
                outcomes=[DailyOutcome("arena", "竞技场", "failed", "boom")],
            ),
            1,
        ),
        (
            DailyReport(
                outcomes=[DailyOutcome("arena", "竞技场", "skipped", "用户手动停止")],
                stopped_by_user=True,
            ),
            130,
        ),
        (
            DailyReport(
                outcomes=[DailyOutcome("arena", "竞技场", "skipped", "回不去")],
                aborted_reason="骑士团捐赠 之前无法回到首页（boom）",
            ),
            1,
        ),
    ]
    for report, expected in cases:
        monkeypatch.setattr(
            main_module, "run_daily_tasks", lambda report=report, **kwargs: report
        )
        code = main_module._run_daily(
            main_module.parse_args(["--daily", "--live", "--confirm", "RUN"])
        )
        assert code == expected, report.summary_line()


def test_daily_requires_live_confirmation(monkeypatch):
    """实跑必须显式 --confirm RUN，与单路线同一道闸。"""
    from auto_game_unified import main as main_module

    monkeypatch.setattr(main_module, "_run_daily", lambda args: 0)

    with pytest.raises(SystemExit):
        main_module.main(["--daily", "--live"])
