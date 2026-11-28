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
        assert QImage(str(brand.HERO_ART)).size().toTuple() == (384, 384)
        assert QImage(str(brand.COMPLETE_ART)).size().toTuple() == (384, 384)
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
        assert window.plan_list.count() == 2
        assert "竞技场" in window.plan_list.item(0).text()
        assert "世界首领战" in window.plan_list.item(1).text()
        desktop_nav = window.navigationInterface.widget("taskView")
        assert desktop_nav.mapTo(window, desktop_nav.rect().topLeft()).y() >= window.titleBar.height()

        window._enter_floating_mode((("arena", "竞技场"), ("world_boss", "世界首领战")))
        window._return_to_main_window()
        summary = "每日任务汇总：竞技场 ✓ / 世界首领战 ✓"
        monkeypatch.setattr(WorkerController, "recent_output", property(lambda self: (summary,)))
        monkeypatch.setattr(worker, "drain_events", lambda: (
            WorkerEvent("log", summary), WorkerEvent("finished", "运行完成", 0),
        ))
        window._poll_worker()
        qt_app.processEvents()
        assert window.result_mascot.isVisible()
        assert window.run_animation.state == "success"
        assert window.run_progress_bar.value() == 100
    finally:
        window.close()


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
