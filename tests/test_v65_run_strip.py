"""Runtime presentation and interaction through the native companion."""

import os

import pytest


ROUTES = (("arena", "竞技场"), ("world_boss", "世界首领战"))


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_compact_strip_shows_current_status_and_processed_routes(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QProgressBar

    from auto_game_unified.desktop_qt.floating import FloatingRunner
    from auto_game_unified.desktop_qt.mascot import ArkyMascot

    runner = FloatingRunner()
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        qt_app.processEvents()
        panel = runner.panel
        available = qt_app.primaryScreen().availableGeometry()
        assert panel.size().toTuple() == (126, 128)
        assert panel.frameGeometry().bottomRight().toTuple() == (
            available.right() - 88, available.bottom() - 26,
        )
        flags = panel.windowFlags()
        assert flags & Qt.WindowStaysOnTopHint
        assert flags & Qt.WindowDoesNotAcceptFocus
        assert panel.windowType() == Qt.Tool
        assert panel.testAttribute(Qt.WA_ShowWithoutActivating)

        runner.note_line("每日任务进度：arena failed")
        runner.note_line("2026-11-26 10:01:04 模式=world_boss 状态=进入路线")
        assert runner.status_text == "执行中 · 世界首领战"
        assert panel.findChild(ArkyMascot).animation is runner.animation
        title = panel.findChild(QLabel, "runStripTitle")
        emblem = panel.findChild(QLabel, "runStripIcon")
        assert title.text() == "世界首领战"
        assert emblem.property("routeMode") == "world_boss"
        assert not emblem.pixmap().isNull()
        assert panel.findChild(QLabel, "runStripCount") is None
        bar = panel.findChild(QProgressBar, "runStripProgress")
        assert bar.size().toTuple() == (57, 10)
        assert bar.value() == 50
        runner.note_line("每日任务汇总：竞技场 ✗[运行异常] / 世界首领战 ✓")
        runner.finish(1)
        assert runner.progress.completed_count == 1
        assert runner.status_text == "任务失败"
        assert title.text() == "任务失败"
        assert panel.findChild(QLabel, "runStripPercent").text() == "100%"
        assert bar.value() == 100
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_companion_actions_appear_on_hover_and_drag_persists(qt_app, monkeypatch):
    from PySide6.QtCore import QPoint, QRect, QSize, Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton, QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    screen = qt_app.primaryScreen().availableGeometry()
    origin = screen.topLeft() + QPoint(30, 60)
    if QRect(origin, QSize(126, 128)).contains(QCursor.pos()):
        origin += QPoint(160, 0)
    runner = FloatingRunner(origin.toTuple())
    actions = []
    runner.stop_clicked.connect(lambda: actions.append("stop"))
    runner.open_main_requested.connect(lambda: actions.append("restore"))
    runner.position_changed.connect(lambda position: actions.append(position))
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        qt_app.processEvents()
        panel = runner.panel
        bubble = panel.findChild(QWidget, "runStripBubble")
        button = panel.findChild(QPushButton, "runStripStop")
        assert button.focusPolicy() == Qt.NoFocus
        assert not bubble.isVisible()
        assert not button.isVisible()

        QTest.mouseMove(panel, QPoint(63, 40))
        qt_app.processEvents()
        assert bubble.isVisible()
        assert button.isVisible()
        assert bubble.pos() == origin + QPoint(106, -18)
        QTest.mouseMove(bubble, QPoint(30, 26))
        QTest.qWait(200)
        assert bubble.isVisible()

        QTest.mouseClick(button, Qt.LeftButton)
        assert actions == ["stop"]
        runner.stop_requested()
        assert runner.status_text == "正在安全停止"
        assert not button.isEnabled()
        QTest.mouseClick(button, Qt.LeftButton)
        assert actions == ["stop"]

        restore = panel.findChild(QPushButton, "runStripRestore")
        QTest.mouseClick(restore, Qt.LeftButton)
        assert actions == ["stop", "restore"]

        start, end = QPoint(18, 16), QPoint(76, 70)
        QTest.mousePress(panel, Qt.LeftButton, pos=start)
        QTest.mouseMove(panel, end)
        QTest.mouseRelease(panel, Qt.LeftButton, pos=start)
        assert actions == ["stop", "restore", panel.pos().toTuple()]
        assert panel.pos() == origin + (end - start)
        runner.hide_all()
        runner.show_strip()
        assert panel.pos().toTuple() == actions[-1]
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_strip_revalidates_offscreen_session_position(qt_app):
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    runner = FloatingRunner((-100000, -100000))
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        qt_app.processEvents()
        assert qt_app.primaryScreen().availableGeometry().contains(runner.panel.frameGeometry())
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_drag_clamps_to_the_target_screens_work_area(qt_app, monkeypatch):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication

    from auto_game_unified.desktop_qt.floating import FloatingRunner

    class SecondaryScreen:
        def availableGeometry(self):
            return QRect(-900, 20, 900, 460)

    screen = SecondaryScreen()
    primary = qt_app.primaryScreen()
    monkeypatch.setattr(QApplication, "screenAt", lambda point: screen if point.x() < 0 else primary)
    runner = FloatingRunner()
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        runner.panel.drag_moved.emit(QPoint(-100, 440), QPoint(-25, 450))
        runner.panel.drag_finished.emit()
        assert runner.panel.pos() == QPoint(-126, 352)
        assert screen.availableGeometry().contains(runner.panel.frameGeometry())

        runner.hide_all()
        runner.show_strip()
        assert runner.panel.pos() == QPoint(-126, 352)
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_shared_animation_follows_worker_outcome_across_hide_and_restart(qt_app, monkeypatch):
    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner
    from auto_game_unified.desktop_qt.mascot import ArkyAnimation

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    animation = ArkyAnimation()
    runner = FloatingRunner(animation=animation)
    try:
        assert runner.animation is animation
        runner.start_run(ROUTES)
        runner.show_strip()
        runner.hide_all()
        assert animation.state == "running"
        assert animation.is_animating
        runner.show_strip()
        runner.note_line("每日任务汇总：竞技场 ✓ / 世界首领战 ✓")
        assert animation.state == "running"

        runner.finish(0)
        assert runner.outcome == animation.state == "success"
        assert runner.panel.isVisible()
        runner.start_run(ROUTES)
        runner.finish(0)
        assert runner.outcome == "awaiting_confirmation"
        assert animation.state == "idle"

        runner.start_run(ROUTES)
        runner.note_line("每日任务汇总：竞技场 ✗[运行异常]")
        runner.finish(1)
        assert runner.outcome == animation.state == "failure"

        runner.start_run(ROUTES)
        runner.stop_requested()
        runner.finish(1)
        assert runner.outcome == animation.state == "stopped"
        assert not animation.is_animating
        runner.finish(1)
        assert runner.outcome == "stopped"
    finally:
        runner.hide_all()
        animation.stop()


def test_hover_bubble_falls_back_inside_the_available_screen(qt_app, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    available = qt_app.primaryScreen().availableGeometry()
    position = QPoint(available.right() - 125, available.top())
    runner = FloatingRunner(position.toTuple())
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        qt_app.processEvents()
        QTest.mouseMove(runner.panel, QPoint(60, 40))
        bubble = runner.panel.findChild(QWidget, "runStripBubble")
        assert bubble is not None and bubble.isVisible()
        assert bubble.pos() == position + QPoint(-76, 7)
        assert available.contains(bubble.frameGeometry())
        runner.hide_all()
        assert not bubble.isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_mascot_outcome_art_can_extend_above_the_plaque(qt_app, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    start = qt_app.primaryScreen().availableGeometry().topLeft() + QPoint(90, 100)
    runner = FloatingRunner(start.toTuple())
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        runner.finish(1)
        qt_app.processEvents()
        overhang = runner.panel.findChild(QWidget, "runStripMascotOverhang")
        assert overhang is not None and overhang.isVisible()
        assert overhang.windowFlags() & Qt.WindowTransparentForInput
        assert overhang.frameGeometry().bottom() == runner.panel.frameGeometry().top() - 1
        pixels = overhang.grab().toImage()
        assert any(pixels.pixelColor(x, y).alpha() for x in range(pixels.width()) for y in range(pixels.height()))
        runner.hide_all()
        assert not overhang.isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_bubble_dismissal_waits_for_the_pointer_to_leave_the_bridge(qt_app, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    start = qt_app.primaryScreen().availableGeometry().topLeft() + QPoint(30, 60)
    runner = FloatingRunner(start.toTuple())
    try:
        runner.start_run(ROUTES)
        runner.append_log("10:20:30 进入路线")
        runner.show_strip()
        qt_app.processEvents()
        QTest.mouseMove(runner.panel, QPoint(60, 40))
        bubble = runner.panel.findChild(QWidget, "runStripBubble")
        log_bubble = runner.panel.findChild(QWidget, "runStripLogBubble")
        log_line = log_bubble.findChild(QLabel, "runStripLogLine")
        assert bubble is not None and bubble.isVisible()
        assert log_bubble.isVisible() and not log_line.isVisible()
        QTest.qWait(390)
        assert log_line.isVisible() and log_line.text() == "10:20:30  进入路线"
        assert log_bubble.grab().toImage().pixelColor(log_bubble.rect().center()).alpha() > 0
        QCursor.setPos(bubble.frameGeometry().topLeft() - QPoint(3, 3))
        qt_app.sendEvent(runner.panel, QEvent(QEvent.Leave))
        QTest.qWait(180)
        assert bubble.isVisible() and log_bubble.isVisible()
        QCursor.setPos(start - QPoint(20, 40))
        QTest.qWait(175)
        assert bubble.isVisible() and log_bubble.isVisible()
        QTest.qWait(250)
        assert not bubble.isVisible() and not log_bubble.isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_hover_log_shows_only_the_last_five_received_lines_and_resets(qt_app, monkeypatch):
    import re

    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    start = qt_app.primaryScreen().availableGeometry().topLeft() + QPoint(240, 100)
    runner = FloatingRunner(start.toTuple())
    try:
        runner.start_run(ROUTES)
        for number in range(1, 7):
            runner.append_log(f"2026-11-26 10:01:0{number} 运行日志 {number}")
        runner.note_line("每日任务汇总：竞技场 ✓ / 世界首领战 ✓")
        runner.append_log(" \n \t")
        runner.show_strip()
        QTest.mouseMove(runner.panel, QPoint(61, 44))
        actions = runner.panel.findChild(QWidget, "runStripBubble")
        logs = runner.panel.findChild(QWidget, "runStripLogBubble")
        assert actions.isVisible() and logs.isVisible()
        rows = logs.findChildren(QLabel, "runStripLogLine")
        assert [row.text() for row in rows] == [
            f"10:01:0{number}  运行日志 {number}" for number in range(2, 7)
        ]
        runner.append_log("<运行结束>\n11:15:09 最后一条")
        assert rows[-1].text() == "11:15:09  最后一条"
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}  <运行结束>", rows[-2].text())
        assert rows[0].text() == "10:01:04  运行日志 4"

        runner.start_run(ROUTES)
        assert all(not row.text() for row in rows)
        runner.hide_all()
        assert not actions.isVisible() and not logs.isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


@pytest.mark.parametrize("name", ("runStripBubble", "runStripLogBubble"))
def test_reentering_a_bubble_during_retraction_reopens_both(qt_app, monkeypatch, name):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    origin = qt_app.primaryScreen().availableGeometry().topLeft() + QPoint(220, 110)
    runner = FloatingRunner(origin.toTuple())
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        runner.panel._show_actions()
        QTest.qWait(400)
        runner.panel._dismiss_bubbles()
        target = runner.panel.findChild(QWidget, name)
        assert target.isVisible()
        local = target.rect().center()
        qt_app.sendEvent(target, QEnterEvent(QPointF(local), QPointF(local), QPointF(target.mapToGlobal(local))))
        QTest.qWait(410)
        for widget_name in ("runStripBubble", "runStripLogBubble"):
            assert runner.panel.findChild(QWidget, widget_name).isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


@pytest.mark.parametrize("placement", ("below", "above", "side"))
def test_hover_log_fits_by_the_plaque_and_stays_open_across_the_gap(qt_app, monkeypatch, placement):
    from PySide6.QtCore import QEvent, QPoint, QRect
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    available = qt_app.primaryScreen().availableGeometry()
    if placement == "side":
        available = QRect(available.topLeft(), available.size())
        available.setHeight(260)

        class ShortScreen:
            def availableGeometry(self):
                return available

        screen = ShortScreen()
        monkeypatch.setattr(QApplication, "screenAt", lambda point: screen)
        start = available.topLeft() + QPoint(available.width() // 2 - 63, 66)
    elif placement == "above":
        start = available.bottomRight() - QPoint(125, 127)
    else:
        start = available.topLeft() + QPoint(18, 62)
    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    runner = FloatingRunner(start.toTuple())
    try:
        runner.start_run(ROUTES)
        runner.show_strip()
        QTest.mouseMove(runner.panel, QPoint(60, 40))
        actions = runner.panel.findChild(QWidget, "runStripBubble")
        logs = runner.panel.findChild(QWidget, "runStripLogBubble")
        assert actions.isVisible() and logs.isVisible()
        plaque, action, log = (widget.frameGeometry() for widget in (runner.panel, actions, logs))
        assert available.contains(log)
        assert not log.intersects(plaque)
        assert not log.intersects(action)
        if placement == "below":
            assert log.top() > plaque.bottom()
            gap = QPoint(plaque.center().x(), plaque.bottom() + 2)
        elif placement == "above":
            assert log.bottom() < plaque.top()
            gap = QPoint(plaque.center().x(), plaque.top() - 2)
        else:
            assert log.right() < plaque.left() or log.left() > plaque.right()
            gap = QPoint(
                plaque.left() - 2 if log.right() < plaque.left() else plaque.right() + 2,
                plaque.center().y(),
            )

        QCursor.setPos(gap)
        qt_app.sendEvent(runner.panel, QEvent(QEvent.Leave))
        QTest.qWait(180)
        assert actions.isVisible() and logs.isVisible()
        QTest.mouseMove(logs, logs.rect().center())
        QTest.qWait(180)
        assert actions.isVisible() and logs.isVisible()
        QTest.mouseMove(actions, QPoint(40, 20))
        QTest.qWait(180)
        assert actions.isVisible() and logs.isVisible()
        QCursor.setPos(available.topLeft() + QPoint(1, 1))
        qt_app.sendEvent(actions, QEvent(QEvent.Leave))
        QTest.qWait(180)
        assert not actions.isVisible() and not logs.isVisible()
    finally:
        runner.hide_all()
        runner.animation.stop()


def test_hover_log_wraps_long_lines_in_full(qt_app, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QWidget

    from auto_game_unified.desktop_qt import brand
    from auto_game_unified.desktop_qt.floating import FloatingRunner

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    start = qt_app.primaryScreen().availableGeometry().topLeft() + QPoint(240, 100)
    runner = FloatingRunner(start.toTuple())
    long_line = "12:00:00  " + "路线设置保存成功并且日志很长" * 4
    try:
        runner.start_run(ROUTES)
        runner.append_log(long_line)
        runner.show_strip()
        QTest.mouseMove(runner.panel, QPoint(61, 44))
        qt_app.processEvents()
        logs = runner.panel.findChild(QWidget, "runStripLogBubble")
        row = logs.findChild(QLabel, "runStripLogLine")
        assert logs.isVisible()
        assert row.wordWrap()
        assert row.text() == long_line
        assert "…" not in row.text()
        assert logs.height() > 132
        assert row.height() > 16
    finally:
        runner.hide_all()
        runner.animation.stop()
