"""运行进度状态机：只给悬浮窄条展示，认错也不许影响业务。

钉住三件事：只前进不回退、汇总行一次补齐、手动停止时没轮到的仍是「待跑」。
"""

from auto_game_unified.desktop.run_progress import (
    DONE,
    PENDING,
    RUNNING,
    RunProgress,
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
