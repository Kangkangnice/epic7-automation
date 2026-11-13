"""运行进度状态机：只给悬浮窄条展示，认错也不许影响业务。

钉住三件事：只前进不回退、汇总行一次补齐、手动停止时没轮到的仍是「待跑」。
"""

from auto_game_unified.desktop.run_progress import (
    DONE,
    PENDING,
    RUNNING,
    RunProgress,
    extract_run_result,
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
    progress.note_line("2026-11-11 19:00:00 模式=shop_refresh 状态=导航完成")
    assert _statuses(progress) == [DONE, RUNNING, PENDING]
    assert progress.active_label == "刷书签"


def test_mode_line_can_skip_ahead_but_never_backwards() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=arena 状态=进入路线")
    assert _statuses(progress) == [DONE, DONE, RUNNING]
    progress.note_line("模式=world_boss 状态=开局")
    assert _statuses(progress) == [DONE, DONE, RUNNING]


def test_chinese_label_in_mode_line_also_advances() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("模式=竞技场 状态=导航完成")
    assert _statuses(progress) == [DONE, DONE, RUNNING]


def test_unrelated_lines_are_ignored() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("已启动：世界首领战、刷书签、竞技场")
    progress.note_line("环境检测：可以实跑")
    assert _statuses(progress) == [RUNNING, PENDING, PENDING]


def test_summary_line_marks_every_route_done() -> None:
    progress = RunProgress(ROUTES)
    progress.note_line("每日任务汇总：世界首领战 ✓ / 刷书签 ✓ / 竞技场 ✗")
    assert _statuses(progress) == [DONE, DONE, DONE]


def test_finish_marks_current_done_and_keeps_unreached_pending() -> None:
    progress = RunProgress(ROUTES)
    progress.finish()
    assert _statuses(progress) == [DONE, PENDING, PENDING]
    assert progress.finished is True
    assert progress.active_label == ""


def test_lines_after_finish_do_not_change_anything() -> None:
    progress = RunProgress(ROUTES)
    progress.finish()
    progress.note_line("模式=arena 状态=收尾")
    assert _statuses(progress) == [DONE, PENDING, PENDING]


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


def test_extract_run_result_without_a_summary_is_empty() -> None:
    assert extract_run_result(["模式=arena 状态=收尾"]) == (None, ())


def test_extract_run_result_tolerates_a_summary_without_details() -> None:
    """旧版子进程 / 干跑异常时只有那一行汇总，界面回落成一行即可。"""
    assert extract_run_result(["每日任务汇总：竞技场 ✓"]) == ("竞技场 ✓", ())
