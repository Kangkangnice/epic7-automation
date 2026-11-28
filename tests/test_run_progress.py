"""运行进度状态机：只给悬浮窄条展示，认错也不许影响业务。

验证已观察到的执行顺序、终态汇总与未执行路线。
"""

import pytest

from auto_game_unified.desktop.run_progress import (
    DONE,
    PENDING,
    RUNNING,
    RunProgress,
    elapsed_of,
    extract_run_result,
    parse_result_details,
    parse_result_line,
)

ROUTES = (
    ("world_boss", "世界首领战"),
    ("shop_refresh", "刷书签"),
    ("arena", "竞技场"),
)


def _statuses(progress: RunProgress) -> list[str]:
    return [item.status for item in progress.items]


def test_first_route_is_running_at_start() -> None:
    progress = RunProgress(ROUTES)
    assert _statuses(progress) == [RUNNING, PENDING, PENDING]
    assert progress.active_label == "世界首领战"
    assert progress.finished is False


def test_mode_line_advances_one_route_at_a_time() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=world_boss 状态=导航完成")
    progress.note_line("2026-11-11 19:00:00 模式=shop_refresh 状态=导航完成")
    assert _statuses(progress) == [DONE, RUNNING, PENDING]
    assert progress.active_label == "刷书签"


def test_mode_line_can_skip_ahead_but_never_backwards() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=arena 状态=进入路线")
    assert _statuses(progress) == [PENDING, PENDING, RUNNING]
    progress.note_line("模式=world_boss 状态=开局")
    assert _statuses(progress) == [PENDING, PENDING, RUNNING]


def test_chinese_label_in_mode_line_also_advances() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=竞技场 状态=导航完成")
    assert _statuses(progress) == [PENDING, PENDING, RUNNING]


def test_unrelated_lines_are_ignored() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("已启动：世界首领战、刷书签、竞技场")
    progress.note_line("环境检测：可以实跑")
    assert _statuses(progress) == [RUNNING, PENDING, PENDING]


def test_summary_line_marks_every_route_done() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("每日任务汇总：世界首领战 ✓ / 刷书签 ✓ / 竞技场 ✗")
    assert _statuses(progress) == [DONE, DONE, DONE]


@pytest.mark.parametrize(
    "summary",
    [
        "世界首领战 ✓[收尾待确认] / 刷书签 — ｜ 已中止：无法回到首页",
        "世界首领战 ✓(无剩余内容) / 刷书签 —(当前环境不支持)",
        "世界首领战 ✗[页面识别失败]",
    ],
)
def test_partial_summary_leaves_skipped_and_absent_routes_pending(summary: str) -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=arena 状态=执行前检查")
    progress.note_line(f"每日任务汇总：{summary}")
    progress.finish()

    assert _statuses(progress) == [DONE, PENDING, PENDING]
    assert progress.active_label == ""


def test_finish_marks_current_done_and_keeps_unreached_pending() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=world_boss 状态=导航完成")
    progress.finish()
    assert _statuses(progress) == [DONE, PENDING, PENDING]
    assert progress.finished is True
    assert progress.active_label == ""


def test_lines_after_finish_do_not_change_anything() -> None:
    progress = RunProgress(ROUTES)
    progress.finish()
    progress.note_line("模式=arena 状态=收尾")
    assert _statuses(progress) == [PENDING, PENDING, PENDING]


def test_empty_plan_is_safe() -> None:
    progress = RunProgress(())
    progress.note_line("模式=arena 状态=随便")
    progress.finish()
    assert progress.items == ()
    assert progress.active_label == ""


def test_extract_run_result_takes_only_the_latest_summary_block() -> None:
    lines = [
        "每日任务汇总：旧的一次",
        "每日任务结果：旧明细，不该被读到",
        "模式=arena 状态=收尾",
        "每日任务汇总：竞技场 ✓",
        "每日任务结果：共 1 条 · 做完 1 条 · 用时 2分10秒",
        "每日任务结果：竞技场 · 完成 · 10/10 轮 · 胜 7 / 负 3",
    ]

    summary, details = extract_run_result(lines)

    assert summary == "竞技场 ✓"
    assert details == (
        "共 1 条 · 做完 1 条 · 用时 2分10秒",
        "竞技场 · 完成 · 10/10 轮 · 胜 7 / 负 3",
    )


# ── 明细行拆分：结果卡排版用，拆不出来必须返回 None 让界面回落 ──────────────


def test_result_line_splits_reason_off_the_end() -> None:
    parsed = parse_result_line(
        "迷宫强化石 · 未执行 · 43秒 · 上一段之后回不到首页，为避免连锁失败未执行"
    )

    assert parsed is not None
    assert parsed.label == "迷宫强化石"
    assert parsed.status == "未执行"
    assert parsed.meta == "43秒"
    assert parsed.reason == "上一段之后回不到首页，为避免连锁失败未执行"


def test_result_line_keeps_closeout_warning_out_of_the_meta() -> None:
    parsed = parse_result_line(
        "骑士团捐赠 · 完成 · 1/1 轮 · 下级精灵之花已请求；逐行支援与每周任务奖励已处理 · "
        "收尾待确认（网络连接中断，已自动重试 2 次，需恢复网络后重新运行） · 4分40秒"
    )

    assert parsed is not None
    assert parsed.status == "完成"
    assert parsed.note.startswith("收尾待确认")
    # 轮次与用时留在 meta（要能对成列），成句的说明走第二行。
    assert parsed.meta == "1/1 轮 · 4分40秒"
    assert parsed.text == "下级精灵之花已请求；逐行支援与每周任务奖励已处理"
    assert parsed.reason == ""


def test_result_line_without_a_status_word_is_not_parsed() -> None:
    # 旧存档里可能是别的一句话：宁可返回 None 回落成整段文本，也不许猜。
    assert parse_result_line("共 1 条 · 做完 1 条 · 用时 2分10秒") is None
    assert parse_result_line("竞技场") is None


def test_result_details_keep_headline_and_account_lines_out_of_the_rows() -> None:
    lines = [
        "亚卡",
        "等级 71",
        "任务 2 项 · 完成 1 项 · 失败 1 项 · 总用时 14分20秒",
        "竞技场 · 完成 · 10/10 轮 · 胜 7 / 负 3 · 4分20秒",
        "世界首领战 · 失败 · 0/2 轮 · 2分10秒 · 入口按钮连点 3 次仍无响应",
    ]

    rows, headline, extra = parse_result_details(lines)

    assert [row.label for row in rows] == ["竞技场", "世界首领战"]
    assert "总用时" in headline
    assert elapsed_of(headline) == "14分20秒"
    assert extra == ("亚卡", "等级 71")
    assert rows[1].reason == "入口按钮连点 3 次仍无响应"


def test_elapsed_of_is_empty_when_the_headline_has_no_duration() -> None:
    assert elapsed_of("任务 2 项 · 完成 2 项") == ""



def test_extract_run_result_without_a_summary_is_empty() -> None:
    assert extract_run_result(["模式=arena 状态=收尾"]) == (None, ())


def test_extract_run_result_tolerates_a_summary_without_details() -> None:
    """旧版子进程 / 干跑异常时只有那一行汇总，界面回落成一行即可。"""
    assert extract_run_result(["每日任务汇总：竞技场 ✓"]) == ("竞技场 ✓", ())


def test_handoff_and_zero_exit_do_not_verify_completion() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=world_boss 状态=导航完成")
    progress.note_line("模式=world_boss 收尾=已回到首页 状态=可以衔接下一个任务")
    progress.note_line("模式=shop_refresh 状态=导航完成")

    assert progress.items[0].status == DONE
    assert progress.result_items[0].status == "awaiting_confirmation"
    assert progress.completed_count == 0
    assert progress.total_count == 3
    assert progress.active_mode == "shop_refresh"
    assert progress.outcome(0) == "awaiting_confirmation"


@pytest.mark.parametrize(
    ("summary", "exit_code", "statuses", "completed", "outcome"),
    [
        ("世界首领战 ✓ / 刷书签 ✓ / 竞技场 ✓", 0,
         ("success", "success", "success"), 3, "success"),
        ("世界首领战 ✓ / 刷书签 ✗[失败 / 保存诊断] / 竞技场 ✓", 0,
         ("success", "failure", "success"), 2, "failure"),
        ("世界首领战 ✓ / 刷书签 ✓(无剩余内容) / 竞技场 ✓", 0,
         ("success", "resource_exhausted", "success"), 2, "resource_exhausted"),
        ("世界首领战 ✓ / 刷书签 ✓ / 竞技场 ✓[收尾待确认]", 0,
         ("success", "success", "awaiting_confirmation"), 2, "awaiting_confirmation"),
        ("世界首领战 ✓ / 刷书签 — / 竞技场 —(当前环境不支持)", 0,
         ("success", "skipped", "skipped"), 1, "skipped"),
        ("世界首领战 ✓ / 刷书签 — ｜ 已中止：无法回到首页", 1,
         ("success", "skipped", "pending"), 1, "failure"),
        ("世界首领战 ✓ / 刷书签 —", 130,
         ("success", "skipped", "pending"), 1, "stopped"),
        ("世界首领战 ✓", 0,
         ("success", "pending", "pending"), 1, "awaiting_confirmation"),
    ],
)
def test_verified_counts_and_route_outcomes_follow_worker_summary(
    summary, exit_code, statuses, completed, outcome,
) -> None:
    progress = RunProgress(ROUTES)
    progress.note_line(f"每日任务汇总：{summary}")
    progress.finish()

    assert tuple(item.status for item in progress.result_items) == statuses
    assert progress.completed_count == completed
    assert progress.total_count == len(ROUTES)
    assert progress.outcome(exit_code) == outcome


def test_preflight_filtered_routes_do_not_enter_the_denominator() -> None:
    progress = RunProgress(ROUTES[:1])
    progress.note_line("每日任务汇总：世界首领战 ✓ / 刷书签 —(当前环境不支持)")

    assert progress.completed_count == progress.total_count == 1
    assert progress.outcome(0) == "success"


def test_exit_overrides_report_success_when_process_did_not_complete() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("每日任务汇总：世界首领战 ✓ / 刷书签 ✓ / 竞技场 ✓")

    assert progress.outcome(2) == "resource_exhausted"
    assert progress.outcome(130) == "stopped"
    assert progress.outcome(1) == "failure"


def test_processed_progress_advances_at_each_real_outcome_including_a_failure() -> None:
    from types import SimpleNamespace

    from auto_game_unified.games.epic7.daily_tasks import run_daily_tasks

    progress = RunProgress(ROUTES)
    observed = []

    def run_mode(*, spec, **_kwargs):
        observed.append(progress.processed_count)
        if spec.label == "刷书签":
            raise ValueError("验证单条失败后继续执行")
        return SimpleNamespace(completed_cycles=1)

    def deliver(outcome):
        progress.note_line(outcome.progress_line())

    report = run_daily_tasks(
        selected=tuple(mode for mode, _label in ROUTES), dry_run=True,
        run_mode=run_mode, on_outcome=deliver,
    )
    assert observed == [0, 1, 2]
    assert progress.processed_count == 3
    assert progress.completed_count == 2
    assert not progress.finished
    progress.note_line(f"每日任务汇总：{report.summary_line()}")
    assert progress.processed_count == 3
    assert progress.outcome(1) == "failure"


def test_unattempted_and_duplicate_results_do_not_advance_processed_count() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("每日任务进度：world_boss failed")
    progress.note_line("每日任务进度：world_boss failed")
    progress.note_line("每日任务进度：shop_refresh skipped")
    progress.note_line("每日任务进度：unplanned completed")
    assert progress.processed_count == 1
    assert progress.completed_count == 0


def test_settled_route_is_not_shown_as_active_during_closeout_inspection() -> None:
    progress = RunProgress((("side_story", "支线故事"),))
    progress.note_line("模式=side_story 状态=进行中")
    progress.note_line("每日任务进度：side_story completed")
    assert progress.active_mode == ""
    progress.note_line("模式=side_story 状态=收尾巡检")
    assert progress.active_label == ""
    assert progress.processed_count == 1


def test_desktop_worker_command_emits_the_settlement_before_the_next_route(monkeypatch, capsys, tmp_path):
    from types import SimpleNamespace

    from auto_game_unified import main

    def run_mode(*, spec, **_kwargs):
        print(f"开始路线：{spec.label}")
        if spec.label == "世界首领战":
            raise ValueError("测试中记录的失败")
        return SimpleNamespace(completed_cycles=1)

    monkeypatch.setattr(main, "run_mode", run_mode)
    monkeypatch.setattr(main, "_notify_daily", lambda **_kwargs: None)
    args = main.parse_args([
        "--daily", "--daily-tasks", "world_boss,arena", "--stop-file", str(tmp_path / "stop"),
    ])
    assert main._run_daily(args) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines.index("每日任务进度：world_boss failed") < lines.index("开始路线：竞技场")
    assert "每日任务进度：arena completed" in lines
