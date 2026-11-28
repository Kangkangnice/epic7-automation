"""The native task plan and run strip share the real desktop controls."""

import os

import pytest


@pytest.fixture
def desktop_window(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    pytest.importorskip("PySide6")
    pytest.importorskip("qfluentwidgets")
    from PySide6.QtWidgets import QApplication

    from auto_game_unified.desktop.controller import DesktopController
    from auto_game_unified.desktop.worker import WorkerController
    from auto_game_unified.desktop_qt.app import QtDesktopWindow, apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    monkeypatch.setattr(QtDesktopWindow, "_ensure_consent", lambda self: None)
    monkeypatch.setattr(QtDesktopWindow, "_start_update_check", lambda self: None)
    worker = WorkerController(repo_parent=tmp_path, data_root=tmp_path)
    window = QtDesktopWindow(
        controller=DesktopController(worker=worker), worker=worker,
        data_root=tmp_path, template_root=tmp_path,
    )
    window.show()
    app.processEvents()
    try:
        yield window
    finally:
        window.close()


def test_card_list_and_selection_filter_share_the_actual_run_plan(desktop_window):
    window = desktop_window
    window._route_checks["arena"].click()
    window._route_checks["world_boss"].click()
    assert window.plan_list.count() == 2
    assert "竞技场" in window.plan_list.item(0).text()
    assert "世界首领战" in window.plan_list.item(1).text()
    window.layout_button.click()
    window.only_selected.click()
    assert window._route_tiles["arena"].isVisible()
    assert not window._route_tiles["sanctuary"].isVisible()
    window.clear_plan_button.click()
    assert window.plan_list.count() == 0
    assert window.controller.plan() == ()


def test_task_list_is_default_and_keeps_the_settings_column_aligned(desktop_window):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QLineEdit

    window = desktop_window
    window.resize(1180, 800)
    QApplication.processEvents()
    assert window.layout_button.text() == "卡片视图"
    settings_buttons = [window._route_option_buttons[mode] for mode in ("arena", "shop_refresh", "world_boss")]
    assert all(button.text() == "设置" for button in settings_buttons)
    assert len({button.mapTo(window, QPoint()).x() for button in settings_buttons}) == 1
    for mode in ("arena", "shop_refresh"):
        editor = window._route_spins[mode].findChild(QLineEdit)
        assert editor.width() >= 24
        assert editor.text().isdigit()
    window.layout_button.click()
    assert window.layout_button.text() == "列表视图"


def test_log_has_two_independent_vertical_scroll_regions(desktop_window):
    from PySide6.QtWidgets import QApplication, QListWidgetItem

    window = desktop_window
    window.resize(860, 560)
    window.switchTo(window.log_page)
    for index in range(50):
        window.run_routes.addItem(QListWidgetItem(f"任务 {index}"))
        window._append_log(f"记录 {index}")
    QApplication.processEvents()
    result_bottom = window.run_routes.mapTo(window, window.run_routes.rect().bottomRight()).y()
    log_top = window.log_text.mapTo(window, window.log_text.rect().topLeft()).y()
    assert result_bottom < log_top
    result_bar, log_bar = window.run_routes.verticalScrollBar(), window.log_text.verticalScrollBar()
    assert result_bar.maximum() and log_bar.maximum()
    log_bar.setValue(0)
    result_bar.setValue(result_bar.maximum())
    assert log_bar.value() == 0


def test_community_disappears_from_the_pc_cards_list_details_and_plan(desktop_window):
    window = desktop_window
    card = window._route_tiles["community"]
    assert card.isVisible()
    assert window._route_checks["community"].accessibleName() == "社区签到（国服）"
    window._route_checks["community"].click()
    assert "社区签到（国服）" in window.detail_title.text()
    window.backend_combo.setCurrentIndex(window.backend_combo.findData("pc"))
    assert not card.isVisible()
    assert "社区签到" not in window.detail_title.text()
    assert "社区签到" not in window.detail_body.text()
    assert window.plan_list.count() == 0
    window._group_checks["每日"].click()
    assert "community" not in dict(window.controller.plan())
    assert window._group_checks["每日"].isChecked()
    window.layout_button.click()
    assert not card.isVisible()
    window.backend_combo.setCurrentIndex(window.backend_combo.findData("emulator"))
    assert card.isVisible()
    assert not window._route_checks["community"].isChecked()
    assert "社区签到（国服）" in window.detail_body.text()


def test_list_and_cards_use_the_same_parameter_cells_and_keep_plan_counts(desktop_window):
    from PySide6.QtWidgets import QApplication, QLabel
    from qfluentwidgets import SegmentedWidget

    window = desktop_window
    window.resize(1180, 800)
    QApplication.processEvents()
    for header in window._list_heads:
        assert "#" not in [label.text() for label in header.findChildren(QLabel)]
    for mode in ("arena", "shop_refresh", "world_boss"):
        checkbox = window._route_checks[mode]
        icon = window._route_tile_controls[mode][0]
        assert icon.x() - (checkbox.x() + checkbox.width()) <= 6

    window._route_checks["world_boss"].click()
    window._route_checks["shop_refresh"].click()
    window.findChild(SegmentedWidget).widget("按需").click()
    window._route_checks["side_story"].click()
    assert "固定 2 次" in window.plan_list.item(0).text()
    assert "只扫不刷新" in window.plan_list.item(1).text()
    assert "自动跑完" in window.plan_list.item(2).text()
    assert window.plan_list.item(0).text().startswith("1.")
    assert tuple(window.controller.plan())[:2] == (("world_boss", 2), ("shop_refresh", 0))
    assert "side_story" not in window._route_spins
    assert "world_boss" not in window._route_spins
    for _ in range(2):
        QApplication.processEvents()
        auto_labels = [window._route_tile_controls[mode][2] for mode in ("world_boss", "side_story")]
        assert all(label.text() == "自动执行" for label in auto_labels)
        assert auto_labels[0].styleSheet() == auto_labels[1].styleSheet()
        assert {label.size().toTuple() for label in auto_labels} == {(64, 24)}
        assert window._route_tile_controls["arena"][2].text() == "次"
        assert window._route_tile_controls["shop_refresh"][2].text() == "刷新"
        window.layout_button.click()


def test_penguin_name_matches_plan_details_results_and_old_saved_logs(desktop_window, monkeypatch):
    from auto_game_unified.desktop.worker import WorkerEvent
    from auto_game_unified.desktop_qt.route_options_dialog import RouteOptionsDialog

    window = desktop_window
    mode = "penguin_purchase"
    window._show_run_result("", "", "企鹅批量购买 · 完成 · 1 轮", 0)
    restored = window.run_routes.item(0).text()
    assert "企鹅购买" in restored and "企鹅批量购买" not in restored
    assert window._route_checks[mode].accessibleName() == "企鹅购买"
    window._route_checks[mode].click()
    assert "企鹅购买" in window.plan_list.item(0).text()
    window._show_route_detail(mode)
    assert window.detail_title.text() == "企鹅购买"
    names = []
    monkeypatch.setitem(window.controller.options, mode, {})
    monkeypatch.setattr(RouteOptionsDialog, "exec", lambda dialog: names.append(dialog.windowTitle()))
    window._on_route_options_clicked(mode)
    assert "企鹅购买" in names[0]
    assert "企鹅批量购买" not in names[0]
    window._enter_floating_mode(((mode, "企鹅购买"),))
    assert "企鹅购买" in window.floating.status_text
    events = iter((
        WorkerEvent("started", "自动化已启动"),
        WorkerEvent("log", "企鹅购买开始"),
        WorkerEvent("log", "每日任务汇总：企鹅购买 ✓"),
        WorkerEvent("finished", "运行完成", 0),
    ))
    monkeypatch.setattr(window.worker, "drain_events", lambda: events)
    window._poll_worker()
    assert "企鹅购买" in window.run_routes.item(0).text()
    assert "企鹅购买开始" in window.log_text.toPlainText()
    window._show_run_result("", "每日任务汇总：企鹅批量购买 ✓", "")
    assert "企鹅购买" in window.result_text.text()
    assert "企鹅批量购买" not in window.result_text.text()


def test_finished_run_shows_one_row_per_route_and_puts_the_reason_on_top(desktop_window):
    window = desktop_window
    window._enter_floating_mode((("arena", "竞技场"), ("world_boss", "世界首领战")))
    details = "\n".join(
        (
            "亚卡",
            "等级 71",
            "任务 2 项 · 完成 1 项 · 失败 1 项 · 总用时 6分30秒",
            "竞技场 · 完成 · 10/10 轮 · 胜 7 / 负 3 · 4分20秒",
            "世界首领战 · 失败 · 0/2 轮 · 2分10秒 · 入口按钮连点 3 次仍无响应",
        )
    )

    window._show_run_result("2026-11-28 12:01", "竞技场 ✓ / 世界首领战 ✗", details, 1)

    # 一条路线一行，名称与状态都要落在行上；不再是一段话。
    assert window.run_routes.count() == 2
    assert "竞技场" in window.run_routes.item(0).text()
    assert "失败" in window.run_routes.item(1).text()
    # 统计口径闭合：完成 1 + 失败 1 = 2 项。
    metrics = window.result_metrics.text()
    assert "完成" in metrics and "失败" in metrics
    # 结论带直接给出第一处卡点，读者不用往下找。
    assert window.run_reason.text() == "世界首领战：入口按钮连点 3 次仍无响应"
    assert "用时 6分30秒" in window.run_meta.text()
    # 解析成功时不该再出现整段文本。
    assert window.result_scroll.isHidden()


def test_finished_run_collapses_the_log_and_the_next_start_expands_it(desktop_window):
    window = desktop_window
    assert not window.log_text.isHidden()
    window._show_run_result(
        "2026-11-28 12:01", "竞技场 ✓", "竞技场 · 完成 · 1/1 轮 · 4分20秒", 0
    )
    assert window._log_expanded is False
    assert window.log_text.isHidden()
    assert window.log_toggle_button.text() == "展开"
    window._set_log_expanded(True)
    assert window._log_expanded is True
    assert not window.log_text.isHidden()
    assert window.log_toggle_button.text() == "收起"


def test_failure_report_strip_shows_the_archive_name_and_code(desktop_window):
    window = desktop_window
    window._show_report_card("D:/tmp/reports/E7-20261128-1201-9D38.zip")
    assert window.report_file.text() == "E7-20261128-1201-9D38.zip"
    assert window.report_code.text() == "短码 9D38"
    assert not window.report_strip.isHidden()


def test_worker_finishing_keeps_the_strip_until_user_restores_log(desktop_window, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from auto_game_unified.desktop.worker import WorkerEvent

    window = desktop_window
    window._enter_floating_mode((("arena", "竞技场"),))
    assert window.floating.panel.isVisible() and not window.isVisible()
    events = iter((
        WorkerEvent("log", "每日任务汇总：竞技场 ✓"),
        WorkerEvent("finished", "运行完成", 0),
    ))
    monkeypatch.setattr(window.worker, "drain_events", lambda: events)
    window._poll_worker()
    assert window.floating.panel.isVisible() and not window.isVisible()
    rows = window.floating.panel.findChildren(QLabel, "runStripLogLine")
    assert sum("每日任务汇总：竞技场" in row.accessibleName() for row in rows) == 1
    assert any("运行结束（退出码 0）" in row.accessibleName() for row in rows)
    window.floating.open_main_requested.emit()
    assert window.isVisible() and not window.floating.panel.isVisible()
    assert window.stackedWidget.currentWidget() is window.log_page


def test_task_actions_fit_the_compact_window_after_one_resize(desktop_window):
    from PySide6.QtTest import QTest

    window = desktop_window
    window.resize(1440, 900)
    QTest.qWait(40)
    window.resize(860, 560)
    QTest.qWait(40)
    assert window.size().toTuple() == (860, 560)
    assert not window.task_banner.isVisible()
    assert window.start_button.mapTo(window, window.start_button.rect().bottomRight()).y() < 560


def test_plan_and_result_rows_wrap_long_display_text(desktop_window):
    from PySide6.QtWidgets import QListWidgetItem

    window = desktop_window
    window.resize(860, 560)
    window._route_checks["arena"].click()
    text = "任务名称和运行结果应在格子内完整换行显示。" * 7
    for widget in (window.plan_list, window.run_routes):
        if widget is window.run_routes:
            window.switchTo(window.log_page)
        item = QListWidgetItem(text)
        widget.addItem(item)
        widget.doItemsLayout()
        assert widget.wordWrap()
        assert widget.visualItemRect(item).height() > widget.fontMetrics().height() * 2


def test_log_progress_counts_failures_but_keeps_the_route_result(desktop_window):
    window = desktop_window
    window._enter_floating_mode((("arena", "竞技场"), ("sanctuary", "圣域收菜")))
    window.floating.note_line("每日任务进度：arena failed")
    assert window.run_progress_bar.value() == 50
    assert "已处理 1 / 2" in window.run_count.text()
    assert "失败" in window.run_routes.item(0).text()


def test_verified_plan_starts_without_a_second_dialog(desktop_window, monkeypatch):
    from qfluentwidgets import MessageBox

    from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus

    window = desktop_window
    window._route_checks["arena"].click()
    requests = []
    monkeypatch.setattr(MessageBox, "exec", lambda _box: pytest.fail("unexpected second confirmation"))
    monkeypatch.setattr(window.worker, "start", requests.append)
    window._on_start_done(PreflightReport(PreflightStatus.PASS, "检测通过"), None)
    assert requests[0].modes == ("arena",)
    assert window.floating.panel.isVisible() and not window.isVisible()


def test_preflight_keeps_the_autoclicker_and_worker_exclusive(desktop_window, monkeypatch):
    from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus

    window = desktop_window
    window._route_checks["arena"].click()
    monkeypatch.setattr(type(window.autoclicker), "running", property(lambda _clicker: True))
    monkeypatch.setattr(window.worker, "start", lambda _request: pytest.fail("worker must stay idle"))

    window._checking = True
    assert window._autoclick_block_reason()
    window._on_start_done(PreflightReport(PreflightStatus.PASS, "检测通过"), None)
    assert not window._checking and window.isVisible()


def test_task_environment_uses_fixed_background_and_simple_select_all(desktop_window):
    from PySide6.QtWidgets import QWidget

    window = desktop_window
    assert not any(widget.accessibleName() == "不占用前台" for widget in window.findChildren(QWidget))
    assert {box.text() for box in window._group_checks.values()} == {"全选"}
    window.backend_combo.setCurrentIndex(window.backend_combo.findData("pc"))
    assert "以管理员身份启动本助手" not in window.hint_label.text()


def test_opted_in_shutdown_is_visible_on_strip_and_can_be_cancelled_from_logs(desktop_window, monkeypatch):
    from PySide6.QtWidgets import QLabel

    window = desktop_window
    window._enter_floating_mode((("arena", "竞技场"),))
    window.floating.finish(1)
    # No actual shutdown commands are executed in the UI regression.
    def schedule():
        window.shutdown.scheduled = True
        return True

    def cancel():
        window.shutdown.scheduled = False
        return True

    monkeypatch.setattr(window.shutdown, "schedule", schedule)
    monkeypatch.setattr(window.shutdown, "cancel", cancel)
    window._schedule_shutdown_now()
    assert "关机" in window.floating.status_text
    title = window.floating.panel.findChild(QLabel, "runStripTitle")
    assert "关机" in title.text()
    window._return_to_main_window()
    assert window.log_cancel_shutdown_button.isVisible()
    window.log_cancel_shutdown_button.click()
    assert not window.shutdown.scheduled
    assert not window.log_cancel_shutdown_button.isVisible()


def test_arena_npc_keeps_refresh_and_flag_options_at_the_top(desktop_window):
    from auto_game_unified.desktop_qt.route_options_dialog import RouteOptionsDialog

    dialog = RouteOptionsDialog(desktop_window, "arena", "竞技场", {}, lambda *_: None)
    source = dialog._controls["opponent_source"]
    try:
        assert tuple(option.key for option in dialog._options[:4]) == (
            "refresh_mode", "max_gold_refreshes", "ticket_mode", "max_skystone_purchases",
        )

        source.setCurrentIndex(source.findData("npc"))
        # 对话框本身没 show()，所以要用 isHidden() 判断是否被主动隐藏；
        # isVisible() 在父窗口未显示时对所有子控件都返回 False。
        for key in (
            "refresh_mode", "max_gold_refreshes", "ticket_mode",
            "max_skystone_purchases", "weekly_reward", "opponent_source",
        ):
            assert not dialog._rows[key].isHidden(), key
        for key in (
            "opponent_preference", "hero_blacklist", "hero_whitelist",
            "hero_list_conflict",
        ):
            assert dialog._rows[key].isHidden(), key
            assert dialog._dividers[key].isHidden(), key

        source.setCurrentIndex(source.findData("player"))
        for key in (
            "opponent_preference", "hero_blacklist", "hero_whitelist",
            "hero_list_conflict", "refresh_mode", "ticket_mode",
        ):
            assert not dialog._rows[key].isHidden(), key
        assert not dialog._rows["weekly_reward"].isHidden()
    finally:
        dialog.close()


def test_tower_shows_auto_execute_without_cycle_field(desktop_window):
    window = desktop_window
    assert "tower" not in window._route_spins
    assert window._route_tile_controls["tower"][2].text() == "自动执行"
    window._route_checks["tower"].click()
    assert window.controller.plan() == (("tower", 25),)
