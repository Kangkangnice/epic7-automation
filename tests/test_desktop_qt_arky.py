"""Qt brand and animation wiring, with a worker that only emits test events."""

import os

import pytest


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    pytest.importorskip("PySide6")
    pytest.importorskip("qfluentwidgets")
    from PySide6.QtWidgets import QApplication

    from auto_game_unified.desktop_qt.app import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def test_task_page_shows_brand_art_and_every_route_icon(qt_app, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QLabel
    from qfluentwidgets import SegmentedWidget

    from auto_game_unified.desktop.catalog import ROUTES, grouped_routes
    from auto_game_unified.desktop.controller import DesktopController
    from auto_game_unified.desktop.worker import WorkerController, WorkerEvent
    from auto_game_unified.desktop_qt.app import QtDesktopWindow
    from auto_game_unified.desktop_qt import brand

    monkeypatch.setattr(QtDesktopWindow, "_ensure_consent", lambda self: None)
    monkeypatch.setattr(QtDesktopWindow, "_start_update_check", lambda self: None)
    worker = WorkerController(repo_parent=tmp_path, data_root=tmp_path)
    window = QtDesktopWindow(
        controller=DesktopController(worker=worker),
        worker=worker,
        data_root=tmp_path,
        template_root=tmp_path,
    )
    try:
        window.show()
        qt_app.processEvents()
        assert window.windowTitle().startswith("亚卡助手")
        assert not window.windowIcon().isNull()
        assert QImage(str(brand.HERO_ART)).size().toTuple() == (512, 512)
        assert QImage(str(brand.COMPLETE_ART)).size().toTuple() == (512, 512)
        assert not QImage(str(brand.BADGE_ART)).isNull()
        icons = window.findChildren(QLabel, "routeEmblem")
        assert {icon.property("routeMode") for icon in icons} == {route.mode for route in ROUTES}
        assert set(brand.ROUTE_ICONS) == {route.mode for route in ROUTES}
        assert len(set(brand.ROUTE_ICONS.values())) == len(ROUTES)
        assert len({icon.pixmap().cacheKey() for icon in icons}) == len(ROUTES)
        assert all(not icon.pixmap().isNull() for icon in icons)
        tabs = window.findChild(SegmentedWidget)
        for group, routes in grouped_routes():
            tabs.widget(group).click()
            assert {icon.property("routeMode") for icon in icons if icon.isVisible()} == {
                route.mode for route in routes
            }
        tabs.widget(grouped_routes()[0][0]).click()
        window._route_checks["arena"].click()
        window._route_checks["world_boss"].click()
        assert window.selection_summary.text() == "执行顺序 · 竞技场 → 世界首领战"
        desktop_nav = window.navigationInterface.widget("taskView")
        assert desktop_nav.mapTo(window, desktop_nav.rect().topLeft()).y() >= window.titleBar.height()

        monkeypatch.setattr(
            WorkerController, "recent_output",
            property(lambda self: ("每日任务汇总：完成 2 项",)),
        )
        monkeypatch.setattr(worker, "drain_events", lambda: (WorkerEvent("finished", "", 0),))
        window._poll_worker()
        qt_app.processEvents()
        assert window.result_mascot.isVisible()
        assert window.result_mascot.phase == "complete"

        window._stop_requested_by_user = True
        window._poll_worker()
        assert not window.result_mascot.isVisible()
    finally:
        window.close()


def test_arky_motion_follows_run_events_and_respects_reduced_motion(qt_app, monkeypatch):
    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    runner = FloatingRunner(())
    try:
        runner.start_run((
            ("arena", "竞技场"), ("world_boss", "世界首领战"), ("knights_donation", "骑士团捐赠"),
        ))
        runner.expand()
        assert runner.panel.mascot.phase == "launch"
        runner.note_line("模式=world_boss")
        assert runner.panel.mascot.phase == "handoff"
        assert runner.panel.mascot.animation_running
        runner.stop_requested()
        runner.note_line("模式=knights_donation")
        assert runner.panel._state.text() == "正在安全停止"
        assert not runner.panel.mascot.animation_running
        runner.finish(130)
        assert runner.panel.mascot.phase == "stopped"
        assert runner.panel._state.text() == "已停止"
        assert not runner.panel.mascot.animation_running
        assert runner._progress.items[-1].status != "done"

        runner.start_run((("arena", "竞技场"),))
        runner.expand()
        runner.finish(0)
        assert runner.panel.mascot.phase == "complete"
        assert runner.panel.mascot.animation_running
        runner.hide_all()
        assert not runner.panel.mascot.animation_running

        monkeypatch.setattr(brand, "motion_enabled", lambda: False)
        runner.start_run((("arena", "竞技场"),))
        runner.expand()
        assert runner.panel.mascot.phase == "launch"
        assert not runner.panel.mascot.animation_running
    finally:
        runner.hide_all()


def test_floating_log_wraps_instead_of_eliding_and_keeps_the_latest_visible(qt_app):
    """窄条日志必须换行显示全文，不再 elidedText 截断；三条折行后都能读到。"""

    from PySide6.QtWidgets import QLabel

    from auto_game_unified.desktop_qt.floating import (
        LOG_LINES,
        LOG_PANEL_MAX_HEIGHT,
        LOG_PANEL_MIN_HEIGHT,
        RunPanel,
    )

    panel = RunPanel(())
    panel.resize(300, 520)
    panel.show()
    qt_app.processEvents()
    long_line = "模式=主线 状态=完成一遍 阶段=关卡入口 动作=跳过剧情与战斗动画 结论=通关 战绩=胜 1"
    panel.set_log_lines([
        "第一条旧日志",
        "第二条旧日志",
        long_line,
    ])
    qt_app.processEvents()

    labels = panel.findChildren(QLabel, "logLine")
    assert len(labels) == LOG_LINES
    assert labels[-1].text() == long_line
    assert all(label.wordWrap() for label in labels)
    # 关键回归：过去这里 elidedText 会把长行截短并以「…」结尾。
    assert "…" not in labels[-1].text()
    # 布局后长行确实折成多行（高于单行短日志），不是只有 wordWrap 属性。
    assert labels[-1].height() > labels[0].height()
    # 日志区有保底最小高度（进度区 stretch 会抢高度，只设上限会被压到 55px），
    # 三条折行日志装得下、不用滚动顶掉最上面那条。
    assert LOG_PANEL_MAX_HEIGHT >= 180
    assert LOG_PANEL_MIN_HEIGHT >= 96
    assert panel._log_scroll.minimumHeight() == LOG_PANEL_MIN_HEIGHT
    assert panel._log_scroll.maximumHeight() == LOG_PANEL_MAX_HEIGHT
    assert panel._log_scroll.height() >= LOG_PANEL_MIN_HEIGHT
    assert sum(label.height() for label in labels) <= panel._log_scroll.height()
    assert panel._log_scroll.verticalScrollBar().maximum() == 0


def test_floating_panel_has_exactly_one_todo_slot(qt_app):
    """今日便签只留一条：旧版三条界面的残留不该再出现。"""

    from PySide6.QtWidgets import QLineEdit

    from auto_game_unified.desktop_qt.floating import RunPanel

    panel = RunPanel(("只记这一条",))
    editors = panel.findChildren(QLineEdit)
    assert len(editors) == 1
    assert editors[0].text() == "只记这一条"


def test_the_window_title_and_the_packaged_product_share_one_name():
    """界面标题与自检、安装包用的产品名必须是同一个。

    两处常量（``desktop_qt/brand.py`` 与 ``desktop/catalog.py``）分属界面层与业务层，
    不能互相 import；只能靠这条用例钉住，避免改名只改一半。
    """
    # brand 顶层 import Qt；无 GUI 依赖的解释器（如钩子选中的 Anaconda）跳过，
    # 与本文件其他用例口径一致。正式环境（.venv 带 PySide6）会真正执行。
    pytest.importorskip("PySide6")
    pytest.importorskip("qfluentwidgets")
    from auto_game_unified.desktop.catalog import PRODUCT_NAME
    from auto_game_unified.desktop_qt import brand

    assert brand.APP_NAME == PRODUCT_NAME == "亚卡助手"
