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
        # 周的存量内容，但用户 2026-10-17 拍板放进日常：每天顺手看一眼，
        # 没额度时三秒收工（resource，不是失败），有额度时才是长流程。
        "moonlight_theater",
        # 成就领取（2026-11-08）：有就领、没有就走，几秒收工 ⇒ 排最后。
        "achievement",
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
        "月光剧场",
        "成就领取",
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
        "moonlight_theater",
        "achievement",
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


def test_a_failed_task_carries_its_reason_into_the_summary():
    """失败的条目必须带一句原因 —— 只打一个 ✗ 等于把真因藏起来。

    2026-10-24 月光剧场连挂三次，日志里只有 ``月光剧场 ✗``，一份原因都没有，
    只能去翻子进程的原始输出猜。``detail`` 早就记下来了，没打而已。
    """
    report = DailyReport(
        outcomes=[
            DailyOutcome(
                "moonlight_theater",
                "月光剧场",
                "failed",
                "RuntimeError: 应恰好找到一个支持的雷电模拟器窗口，实际找到 0 个",
            )
        ]
    )

    line = report.summary_line()
    assert "月光剧场 ✗" in line
    assert "雷电模拟器窗口" in line, "失败原因必须进汇总行"


def test_the_summary_drops_the_long_diagnostics_path():
    """诊断路径对「为什么失败」没有信息量，还会把日志/手机通知撑爆。"""
    report = DailyReport(
        outcomes=[
            DailyOutcome(
                "moonlight_theater",
                "月光剧场",
                "failed",
                "RuntimeError: 返回首页失败：连按 2 次 ESC 页面都没有变化（停在页面=unknown）"
                "；已保存诊断 D:\\AI\\codex\\auto_game\\auto_game_unified\\runtime_diagnostics"
                "\\epic7_moonlight_theater\\20261024_155157_650123_return_home_v2_esc_no_effect.png",
            )
        ]
    )

    line = report.summary_line()
    assert "连按 2 次 ESC" in line
    assert "runtime_diagnostics" not in line
    assert ".png" not in line


# --------------------------------------------------------------------------
# 结算明细（2026-11-12 用户要求：别只报「完成没完成」）
#
# 这里只守「把已经记录下来的事实摆出来」：做了几轮、用了多久、为什么没做成。
# 不新增任何路线判据，也不统计花了多少资源 / 拿到多少奖励。
# --------------------------------------------------------------------------


def _mixed_report() -> DailyReport:
    return DailyReport(
        outcomes=[
            DailyOutcome(
                "arena", "竞技场", "completed",
                cycles=10, target_cycles=10, elapsed_seconds=130,
                outcome_summary="胜 7 / 负 3",
            ),
            DailyOutcome(
                "shop_refresh", "刷书签", "resource",
                cycles=1, target_cycles=1, elapsed_seconds=42,
            ),
            DailyOutcome(
                "sanctuary", "圣域收菜", "failed",
                "RuntimeError: 认不出页面", elapsed_seconds=63,
            ),
            DailyOutcome("achievement", "成就领取", "not_supported"),
            DailyOutcome("tower", "月塔", "skipped", "上一段之后回不到首页"),
        ],
        elapsed_seconds=372,
    )


def test_result_lines_put_the_totals_first():
    lines = _mixed_report().result_lines()
    assert "共 5 条" in lines[0]
    assert "做完 1 条" in lines[0]
    assert "没得做 1 条" in lines[0]
    assert "失败 1 条" in lines[0]
    assert "本环境跑不了 1 条" in lines[0]
    assert "没跑 1 条" in lines[0]
    assert "6分12秒" in lines[0]


def test_result_lines_show_what_each_route_actually_did():
    text = "\n".join(_mixed_report().result_lines())
    assert "竞技场 · 完成 · 10/10 轮 · 胜 7 / 负 3 · 2分10秒" in text
    assert "刷书签 · 没得做了 · 1/1 轮 · 42秒" in text
    assert "圣域收菜 · 失败 · 1分03秒 · 认不出页面" in text
    assert "成就领取 · 本环境跑不了" in text
    assert "月塔 · 没跑 · 上一段之后回不到首页" in text


def test_result_lines_do_not_count_non_success_as_done():
    report = _mixed_report()
    assert report.any_failed is True
    assert "做完 1 条" in report.result_lines()[0]


def test_brief_lines_drop_per_route_time_but_keep_the_failure_reason():
    brief = "\n".join(_mixed_report().brief_lines())
    assert "6分12秒" in brief
    assert "2分10秒" not in brief, "通知是精简版，不带分项耗时"
    assert "1分03秒" not in brief
    assert "认不出页面" in brief, "失败原因必须留着"
    assert "竞技场 完成 10/10轮" in brief


def test_notify_daily_sends_the_brief_version(monkeypatch):
    from auto_game_unified import main as main_module

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_module, "send_qqbot_c2c",
        lambda title, body: sent.append((title, body)),
    )

    main_module._notify_daily(
        live=True, report=_mixed_report(), elapsed_seconds=372
    )

    assert len(sent) == 1
    title, body = sent[0]
    assert "有失败" in title
    assert "竞技场 完成" in body
    assert "2分10秒" not in body


def test_result_lines_show_what_the_shop_bought():
    """刷书签的全部意义就是买到书签，只报「完成 1 轮」等于没说。"""
    report = DailyReport(
        outcomes=[
            DailyOutcome(
                "shop_refresh", "刷书签", "completed",
                cycles=1, target_cycles=1, elapsed_seconds=42,
                note="买到 5 张书签（誓约 3 / 神秘 2）",
            )
        ],
        elapsed_seconds=42,
    )

    line = report.result_lines()[1]
    assert "买到 5 张书签（誓约 3 / 神秘 2）" in line
    assert "42秒" in line


def test_brief_lines_also_show_what_the_shop_bought():
    """通知是精简版，但「买到了什么」是这条路线的结果，不能省掉。"""
    report = DailyReport(
        outcomes=[
            DailyOutcome(
                "shop_refresh", "刷书签", "completed",
                note="买到 5 张书签（誓约 3 / 神秘 2）",
            )
        ]
    )

    assert "买到 5 张书签" in "\n".join(report.brief_lines())


def test_run_daily_tasks_carries_the_route_note_through():
    class FakeResult:
        completed_cycles = 1
        resource_exhausted = False
        outcome_summary = None
        note = "买到 5 张书签（誓约 3 / 神秘 2）"

    report = run_daily_tasks(
        selected=("shop_refresh",),
        dry_run=True,
        run_mode=lambda **kwargs: FakeResult(),
    )

    assert report.outcomes[0].note == "买到 5 张书签（誓约 3 / 神秘 2）"


def test_run_daily_tasks_fills_cycles_time_and_outcome():
    class FakeResult:
        completed_cycles = 3
        resource_exhausted = False
        outcome_summary = "胜 2 / 负 1"

    report = run_daily_tasks(
        selected=("arena",),
        cycles_override={"arena": 3},
        dry_run=True,
        run_mode=lambda **kwargs: FakeResult(),
    )

    outcome = report.outcomes[0]
    assert outcome.status == "completed"
    assert outcome.cycles == 3
    assert outcome.target_cycles == 3
    assert outcome.outcome_summary == "胜 2 / 负 1"
    assert outcome.elapsed_seconds is not None


def test_failed_route_also_records_how_long_it_was_stuck():
    def boom(**kwargs):
        raise RuntimeError("认不出页面")

    report = run_daily_tasks(
        selected=("arena",), dry_run=True, run_mode=boom
    )

    outcome = report.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.elapsed_seconds is not None


def test_run_daily_prints_result_lines(monkeypatch, capsys):
    from auto_game_unified import main as main_module

    monkeypatch.setattr(
        main_module, "run_daily_tasks", lambda **kwargs: _mixed_report()
    )
    monkeypatch.setattr(main_module, "_notify_daily", lambda **kwargs: None)

    code = main_module._run_daily(main_module.parse_args(["--daily"]))
    out = capsys.readouterr().out

    assert "每日任务汇总：" in out, "进度条还靠这一行收尾，不能删"
    assert "每日任务结果：共 5 条" in out
    assert "每日任务结果：竞技场 · 完成" in out
    assert code == 1


# --------------------------------------------------------------------------
# 各路线「这条干成了什么」的一句话（2026-11-12 补齐每天会跑的 7 条）
#
# 用空壳 Runner 测：route_note() 只读状态机上的现成字段，不跑主循环、不碰判据。
# --------------------------------------------------------------------------


NOTE_RUNNERS = {
    "achievement": "AchievementRunner",
    "labyrinth_stone": "LabyrinthStoneRunner",
    "moonlight_theater": "MoonlightRunner",
    "story_star": "StoryStarRunner",
    "world_boss": "WorldBossRunner",
    "knights_donation": "KnightsDonationRunner",
    "sanctuary": "SanctuaryRunner",
}


def _note_runner(module_name: str, *, dry_run: bool = False, **machine):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module(
        f"auto_game_unified.games.epic7.{module_name}"
    )
    runner = object.__new__(getattr(module, NOTE_RUNNERS[module_name]))
    runner.runtime = SimpleNamespace(dry_run=dry_run)
    runner.machine = SimpleNamespace(**machine)
    return runner


@pytest.mark.parametrize("route", tuple(NOTE_RUNNERS))
def test_every_daily_route_exposes_a_note_hook(route):
    import importlib

    module = importlib.import_module(
        f"auto_game_unified.games.epic7.{route}"
    )
    assert callable(getattr(getattr(module, NOTE_RUNNERS[route]), "route_note", None))


@pytest.mark.parametrize("route", tuple(NOTE_RUNNERS))
def test_note_is_empty_on_a_dry_run(route):
    """干跑没碰游戏，不该冒出「领了 N 次 / 打了 N 场」这种假消息。"""
    assert _note_runner(route, dry_run=True, completed_cycles=0).route_note() == ""


def test_achievement_note_reports_claims_and_effects():
    runner = _note_runner("achievement", _claims=5, _effects=1)
    assert runner.route_note() == "全部领取 5 次，持续效果升级 1 次"


def test_achievement_note_when_nothing_new():
    runner = _note_runner("achievement", _claims=0, _effects=0)
    assert "没有新成就" in runner.route_note()


def test_labyrinth_note_reports_what_was_bought():
    runner = _note_runner(
        "labyrinth_stone", already_explored=False, bought=3,
        purchase_rows=[1, 3, 5],
    )
    assert runner.route_note() == (
        "买到 3 件目标商品（强化石 / 友情点数 / 书签，第 1 行、第 3 行、第 5 行）"
    )


def test_labyrinth_note_distinguishes_already_explored():
    runner = _note_runner(
        "labyrinth_stone", already_explored=True, bought=0, purchase_rows=[]
    )
    assert "今天已经探险过" in runner.route_note()


def test_moonlight_note_reports_acts():
    assert _note_runner("moonlight_theater", completed_cycles=4).route_note() == "看了 4 幕"


def test_moonlight_note_when_no_new_act():
    runner = _note_runner("moonlight_theater", completed_cycles=0)
    assert "没有新看的幕" in runner.route_note()


def test_story_star_note_never_claims_star_counts():
    """代码只能证明「打完一个未满星小节」，不能证明补成了星，别写「补了 N 颗」。"""
    runner = _note_runner("story_star", completed_cycles=1)
    runner._stages_fought = 3
    text = runner.route_note()
    assert "打了 3 个未满星小节" in text
    assert "颗星" not in text


def test_world_boss_note_reports_battles_not_cycles():
    """这条路线 completed_cycles 恒为 0，场次得用另记的 battles_done。"""
    runner = _note_runner("world_boss", completed_cycles=0)
    runner.battles_done = 2
    assert runner.route_note() == "打了 2 场"


def test_knights_note_reports_the_request():
    runner = _note_runner(
        "knights_donation", completed_cycles=1, request_done=True
    )
    assert "已请求" in runner.route_note()


def test_sanctuary_note_only_after_a_finished_round():
    runner = _note_runner("sanctuary", completed_cycles=0)
    assert runner.route_note() == ""
    runner.machine.completed_cycles = 1
    assert "三行都收完了" in runner.route_note()


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
        "moonlight_theater",
        "achievement",
    ]
    # 2026-11-09 起「成就领取」两边都能跑：模拟器图补齐后模拟器也会真的派发它，
    # 不再记 ``not_supported``。
    assert [o.status for o in report.outcomes] == ["completed"] * 8
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
        # 竞技场默认 10 次（用户 2026-10-18 拍板，原来是 1）。
        ("arena", 10),
        ("moonlight_theater", 99),
        ("achievement", 1),
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
        ("moonlight_theater", 99),
        ("achievement", 1),
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

    # 2026-11-09 起「成就领取」也会被派发（模拟器图已补齐）。
    assert calls == [
        "world_boss",
        "knights_donation",
        "sanctuary",
        "shop_refresh",
        "labyrinth_stone",
        "arena",
        "moonlight_theater",
        "achievement",
    ]
    assert [o.status for o in report.outcomes] == [
        "completed",
        "failed",
        "completed",
        "completed",
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


def test_manual_stop_does_not_send_a_notification(monkeypatch):
    """用户手动按停止 ⇒ **不发通知**（2026-10-30 用户要求）。

    人就在电脑前面，再推一条「已手动停止」纯属打扰。通知只留给**程序自己跑出来的
    结论**（失败 / 中途停止 / 完成）—— 也就是他不在看着的时候才需要手机响一下。
    单路线那边早就是这个口径（``ManualStop`` 直接返回 130、不通知），整轮这边漏了。

    变异验证：删掉 ``_notify_daily`` 里的 ``if report.stopped_by_user: return``
    ⇒ 立刻红（会推出一条「每日任务已手动停止」）。
    """
    from auto_game_unified import main as main_module
    from auto_game_unified.games.epic7.daily_tasks import DailyReport

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_module,
        "send_qqbot_c2c",
        lambda title, body: sent.append((title, body)),
    )

    main_module._notify_daily(
        live=True,
        report=DailyReport(stopped_by_user=True),
        elapsed_seconds=12,
    )

    assert sent == [], f"手动停止不该发通知，实际发了：{sent}"


# --------------------------------------------------------------------------
# 收尾巡检（2026-11-12 用户要求）
#
# 「所有路线跑完的最后，额外跑一次这个支线路线，把刷新倒计时读下来」。
# 它是**收尾动作**，不是一条路线 ⇒ 不进 ``outcomes``、不参与成功/失败判定，
# 读数只落在 ``countdown_note`` 那一行上（界面把它挂在待办下面）。
# --------------------------------------------------------------------------


def _ok_result():
    class FakeResult:
        completed_cycles = 1
        resource_exhausted = False
        outcome_summary = None
        note = None

    return FakeResult()


class _LobbyProbe:
    """「段间检查」的替身：永远答"人在大厅"。

    真 probe 是 ``(runtime, navigator)``：前者要 ``capture()``、后者要 ``observe()``。
    这里同一个对象两件事都能干，省掉一层嵌套。
    """

    class _Observation:
        name = "lobby"

    def capture(self):
        return None

    def observe(self, screen):  # noqa: ARG002 - 契约形参
        return self._Observation()

    def log(self, line: str) -> None:  # noqa: ARG002 - 契约形参
        return None


class _BrokenProbe:
    """取不到图（窗口被关掉之类）⇒ 段间检查必然失败 ⇒ 整轮中止。"""

    def capture(self):
        raise RuntimeError("窗口没了")

    def observe(self, screen):  # pragma: no cover - 走不到
        raise RuntimeError("窗口没了")


def _run_with_inspect(inspect, **overrides):
    options = dict(
        selected=("arena",),
        dry_run=False,
        build_probe=lambda: (_LobbyProbe(), _LobbyProbe()),
        run_mode=lambda **kwargs: _ok_result(),
        inspect=inspect,
    )
    options.update(overrides)
    return run_daily_tasks(**options)


def test_inspect_runs_once_after_the_routes_and_records_the_note():
    calls: list[int] = []

    def inspect():
        calls.append(1)
        return {"days": 13, "hours": 12, "raw": "剩余 13天 12小时"}

    report = _run_with_inspect(inspect)

    assert calls == [1], "收尾巡检必须跑且只跑一次"
    assert report.countdown_note == "支线刷新：剩余 13 天 12 小时"
    # 读数出现在明细里，但**不是一条任务** —— 总账那行仍然只数路线。
    lines = report.result_lines()
    assert lines[-1] == "支线刷新：剩余 13 天 12 小时"
    assert "共 1 条" in lines[0]
    assert all("支线刷新" not in line for line in lines[1:-1])


def test_inspect_is_skipped_on_a_dry_run():
    """干跑本来就没碰游戏，巡检要真点真读 —— 硬做只会假报一次失败。"""

    calls: list[int] = []
    report = _run_with_inspect(lambda: calls.append(1), dry_run=True)

    assert calls == []
    assert report.countdown_note is None


def test_inspect_is_skipped_when_the_user_pressed_stop():
    """按了 P 就是「别动了」，这时候再点进游戏是添乱。"""

    calls: list[int] = []

    def stop(**kwargs):
        raise ManualStop()

    report = _run_with_inspect(lambda: calls.append(1), run_mode=stop)

    assert report.stopped_by_user is True
    assert calls == []
    assert report.countdown_note is None


def test_inspect_is_skipped_when_the_run_aborted():
    """回不到首页（整轮中止）⇒ 巡检只会再撞同一堵墙。"""

    calls: list[int] = []

    report = run_daily_tasks(
        selected=("arena", "world_boss"),
        dry_run=False,
        # 第二条之前的段间检查取不到图 ⇒ 中止剩余任务（与真跑撞上「窗口没了」同一条路）。
        build_probe=lambda: (_BrokenProbe(), _BrokenProbe()),
        run_mode=lambda **kwargs: _ok_result(),
        inspect=lambda: calls.append(1),
    )

    assert report.aborted_reason is not None
    assert calls == []
    assert report.countdown_note is None


def test_a_failed_route_does_not_stop_the_inspect():
    """某条路线失败 ≠ 整轮中止：后面照跑，收尾巡检也照做。"""

    def boom_once(**kwargs):
        if not boom_once.called:
            boom_once.called = True
            raise RuntimeError("认不出页面")
        return _ok_result()

    boom_once.called = False

    report = run_daily_tasks(
        selected=("arena", "world_boss"),
        dry_run=False,
        build_probe=lambda: (_LobbyProbe(), _LobbyProbe()),
        run_mode=boom_once,
        inspect=lambda: {"days": 1, "hours": 2},
    )

    assert report.any_failed is True
    assert report.aborted_reason is None
    assert report.countdown_note == "支线刷新：剩余 1 天 2 小时"


def test_inspect_failure_never_turns_the_run_into_a_failure():
    """读不到就是「这次没读到」，不是「今天没做完」。"""

    def boom():
        raise RuntimeError("等待动作[enter_normal_sub_story]目标画面超时")

    report = _run_with_inspect(boom)

    assert report.any_failed is False, "巡检失败把整轮判成失败 → 通知里会误报"
    assert report.countdown_note is not None
    assert report.countdown_note.startswith("支线刷新：没读到")
    assert "等待动作" in report.countdown_note


def test_inspect_reporting_nothing_is_a_miss_not_a_zero():
    """OCR 没认出那一行字 ⇒ 说"没读到"，绝不写成「剩余 0 天 0 小时」。"""

    report = _run_with_inspect(lambda: None)

    assert report.countdown_note == "支线刷新：没读到（这一页的文字没认出来）"


def test_inspect_pressing_stop_is_recorded_as_a_manual_stop():
    """巡检途中按 P 也算整轮手动停止（游戏已经被他撂在那儿了）。"""

    def stop():
        raise ManualStop()

    report = _run_with_inspect(stop)

    assert report.stopped_by_user is True
    assert report.countdown_note == "支线刷新：巡检被手动停止，这次没读"
    assert report.any_failed is False


# --------------------------------------------------------------------------
# 巡检的**接线**：`main.inspect_side_story_countdown`
#
# 它把「每日任务收尾」和「支线只读巡检」接起来：用改过的 ModeSpec 复用
# `run_mode`（导航链 / 弹窗守卫 / 收尾回首页全都不用另写一份），跑完把读数落盘。
# 这里不碰游戏窗口 —— `run_mode` 被替身顶掉，只验「拿到的 spec 对不对」。
# --------------------------------------------------------------------------


def test_countdown_inspect_reuses_the_side_story_spec_but_drops_resume(monkeypatch, tmp_path):
    from auto_game_unified import main as main_module
    from auto_game_unified.core import countdown as countdown_module
    from auto_game_unified.games.epic7 import modes as modes_module
    from auto_game_unified.games.epic7.side_story import SideStoryStateMachine

    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(countdown_module, "DATA_DIR_ENV", "EPIC7_DATA_DIR", raising=False)

    templates_root = main_module.ROOT / "games" / "epic7" / "templates"
    seen: dict[str, object] = {}

    def fake_run_mode(*, spec, start_state, max_cycles, **kwargs):
        machine = spec.build_machine(templates_root, start_state)
        seen["spec"] = spec
        seen["machine"] = machine
        seen["start_state"] = start_state
        seen["max_cycles"] = max_cycles
        seen["machine_countdown_only"] = machine._countdown_only
        # 真跑里这一步由状态机在 Episode 详情页完成；这里直接给答案。
        machine.countdown_read = {"days": 13, "hours": 12, "raw": "剩余 13天 12小时"}

        class _Result:
            completed_cycles = 0
            resource_exhausted = True
            outcome_summary = None
            note = None

        return _Result()

    monkeypatch.setattr(main_module, "run_mode", fake_run_mode)

    payload = main_module.inspect_side_story_countdown(
        window_backend="emulator", stop_file=None
    )

    spec = seen["spec"]
    assert spec.name == "side_story", (
        "模式名必须保持 side_story —— 导航链是按 MODE_SPECS[名字] 查的"
        "（navigation._plan_for），改名第一跳就抛「导航不支持的模式」"
    )
    assert spec.resume_probe is None, "巡检不做接力：半路接着跑会把读数变成打图"
    assert spec.navigation_plan is modes_module.MODE_SPECS["side_story"].navigation_plan
    assert seen["start_state"] == modes_module.MODE_SPECS["side_story"].default_state
    assert seen["max_cycles"] == 1
    assert isinstance(seen["machine"], SideStoryStateMachine)
    assert seen["machine_countdown_only"] is True, "装配时没打开只读开关"

    assert payload == {"days": 13, "hours": 12, "raw": "剩余 13天 12小时"}
    saved = countdown_module.load_countdown()
    assert (saved["days"], saved["hours"]) == (13, 12)


def test_countdown_inspect_returns_none_when_nothing_was_read(monkeypatch, tmp_path):
    """状态机没读到（OCR 没认出字 / 走岔了）⇒ 返回 None，**不写盘、不编一个 0**。"""

    from auto_game_unified import main as main_module
    from auto_game_unified.core import countdown as countdown_module

    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))

    def fake_run_mode(*, spec, start_state, **kwargs):
        spec.build_machine(
            main_module.ROOT / "games" / "epic7" / "templates", start_state
        )

        class _Result:
            completed_cycles = 0
            resource_exhausted = False

        return _Result()

    monkeypatch.setattr(main_module, "run_mode", fake_run_mode)

    assert (
        main_module.inspect_side_story_countdown(
            window_backend="emulator", stop_file=None
        )
        is None
    )
    assert countdown_module.load_countdown() is None
