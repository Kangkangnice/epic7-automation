"""Approved C1 pixel artwork, shared mascot animation, and Qt controls."""

import os

import pytest


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    pytest.importorskip("PySide6")
    pytest.importorskip("qfluentwidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_approved_static_art_and_pixel_route_emblems(qt_app):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QWidget

    from auto_game_unified.desktop.catalog import ROUTES
    from auto_game_unified.desktop_qt import brand

    assert QImage(str(brand.HERO_ART)).size().toTuple() == (384, 384)
    assert QImage(str(brand.COMPLETE_ART)).size().toTuple() == (384, 384)
    assert not brand.app_icon().isNull()
    assert set(brand.ROUTE_ICONS) == {route.mode for route in ROUTES}
    parent = QWidget()
    for route in ROUTES:
        icon = brand.route_emblem(route.mode, parent, size=48)
        assert icon.property("routeMode") == route.mode
        assert not icon.pixmap().isNull()
        assert icon.size().toTuple() == (48, 48)
        assert icon.pixmap().size().toTuple() == (round(48 * icon.devicePixelRatioF()),) * 2
        icon.set_icon_size(27)
        assert icon.size().toTuple() == (27, 27)
        assert icon.pixmap().size().toTuple() == (round(27 * icon.devicePixelRatioF()),) * 2
    assert not brand.icon("nav-tasks").isNull()


def test_c1_icons_are_distinct_transparent_sprites_at_their_approved_sizes(qt_app):
    from PySide6.QtGui import QImage

    from auto_game_unified.desktop_qt import brand

    paths = list(brand.ICONS.glob("*.png"))
    assert len({path.read_bytes() for path in paths}) == 49
    for path in paths:
        image = QImage(str(path))
        side = 40 if path.stem in brand.ROUTE_ICONS else 32
        assert image.size().toTuple() == (side, side)
        assert image.hasAlphaChannel()
        assert image.pixelColor(0, 0).alpha() == 0


def test_repeat_state_does_not_restart_a_shared_animation(qt_app, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    from auto_game_unified.desktop_qt import brand, mascot

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    assert hasattr(mascot, "ArkyAnimation")
    animation = mascot.ArkyAnimation()
    first = mascot.ArkyMascot(animation=animation, height=80)
    second = mascot.ArkyMascot(animation=animation, height=100)
    frames = QSignalSpy(animation.frame_changed)
    try:
        animation.set_state("running")
        assert animation.frame_index == 0
        assert frames.wait(500)
        assert animation.frame_index == 1
        assert first.animation is second.animation is animation
        assert animation.pixmap().cacheKey() == brand.artwork(
            brand.ASSETS / "mascot" / "running" / "01.png"
        ).cacheKey()
        animation.set_state("running")
        assert animation.frame_index == 1
        assert frames.count() == 2
        animation.set_state("idle")
        animation.set_state("running")
        assert animation.frame_index == 0
    finally:
        animation.stop()


@pytest.mark.parametrize(("state", "duration", "hold"), [("success", 160, 3), ("failure", 650, 5)])
def test_terminal_animation_shows_all_frames_then_holds_the_approved_pose(
    qt_app, monkeypatch, state, duration, hold
):
    from PySide6.QtTest import QSignalSpy

    from auto_game_unified.desktop_qt import brand, mascot

    monkeypatch.setattr(brand, "motion_enabled", lambda: True)
    assert hasattr(mascot, "ArkyAnimation")
    animation = mascot.ArkyAnimation()
    frames = QSignalSpy(animation.frame_changed)
    animation.set_state(state)
    try:
        shown = [animation.frame_index]
        for _ in range(6):
            assert frames.wait(duration + 300)
            shown.append(animation.frame_index)
        assert shown == [0, 1, 2, 3, 4, 5, hold]
        assert animation.state == state
        assert not frames.wait(duration + 100)
    finally:
        animation.stop()


def test_reduced_motion_shows_approved_key_frames(qt_app, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    from auto_game_unified.desktop_qt import brand, mascot

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    assert hasattr(mascot, "ArkyAnimation")
    animation = mascot.ArkyAnimation()
    frames = QSignalSpy(animation.frame_changed)
    idle_key = animation.pixmap().cacheKey()
    animation.set_state("running")
    assert animation.frame_index == 0
    animation.set_state("failure")
    assert animation.frame_index == 5
    assert not frames.wait(260)
    animation.set_state("stopped")
    assert animation.pixmap().cacheKey() == idle_key


def test_static_poses_and_running_frames_share_the_same_canvas(qt_app, monkeypatch):
    from PySide6.QtGui import QImage

    from auto_game_unified.desktop_qt import brand, mascot

    monkeypatch.setattr(brand, "motion_enabled", lambda: False)
    poses = ("waiting", "reading", "tools", "about", "settings", "travel")
    paths = [brand.MASCOT_ART / f"{pose}.png" for pose in poses]
    assert len({path.read_bytes() for path in paths}) == len(poses)
    assert all(QImage(str(path)).size().toTuple() == (384, 384) for path in paths[:-1])
    assert QImage(str(paths[-1])).size().toTuple() == (96, 96)
    animation = mascot.ArkyAnimation()
    plain = mascot.ArkyMascot(height=96, animation=animation)
    travel = mascot.ArkyMascot(height=96, animation=animation, pose="travel")
    plain.resize(96, 96)
    travel.resize(96, 96)
    idle = travel.grab().toImage()
    assert idle != plain.grab().toImage()
    animation.set_state("running")
    assert travel.grab().toImage() == plain.grab().toImage()
    animation.set_state("stopped")
    assert travel.grab().toImage() == idle


def test_settings_button_and_checkbox_render_and_keep_their_actions(qt_app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import ToolButton

    from auto_game_unified.desktop_qt import brand, style

    root = QWidget()
    button = ToolButton(brand.icon("settings"), root)
    button.setProperty("pixelRole", "settings")
    button.resize(40, 26)
    button.move(0, 0)
    check = style.PixelCheckBox("运行", root)
    check.move(0, 35)
    root.resize(120, 86)
    style.apply_pixel_style(root)
    root.show()
    QTest.mouseMove(root, QPoint(100, 75))
    qt_app.processEvents()

    clicked = QSignalSpy(button.clicked)
    button.click()
    assert clicked.count() == 1
    image = button.grab().toImage()
    ratio = image.devicePixelRatio()
    assert image.pixelColor(round(5 * ratio), round(13 * ratio)).name() == "#e2b75f"

    unchecked = check.grab().toImage()
    check.click()
    assert check.checkState() == Qt.Checked
    checked = check.grab().toImage()
    assert unchecked != checked
    assert any(checked.pixelColor(x, y).name() == style.GOLD for x in range(17) for y in range(20))


def test_pixel_components_render_frame_palette_and_scene(qt_app):
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QLabel, QProgressBar, QScrollArea, QWidget
    from qfluentwidgets import PushButton

    from auto_game_unified.desktop_qt import style

    assert hasattr(style, "apply_pixel_style")
    root = QWidget()
    panel = style.PixelPanel(root)
    panel.resize(100, 40)
    scene = style.PixelBackground("banner", root)
    scene.resize(200, 80)
    scene.move(0, 60)
    label = QLabel("失败", panel)
    label.setStyleSheet("color: #f4aaa4")
    scroll = QScrollArea(root)
    scroll.setWidget(QWidget())
    scroll.move(210, 0)
    progress = QProgressBar(root)
    progress.setValue(50)
    progress.setTextVisible(False)
    progress.resize(110, 14)
    progress.move(110, 150)
    control = PushButton("路线名称", root)
    control.setStyleSheet("PushButton { background: transparent; border: 0; padding: 1px; }")
    style.apply_pixel_style(root)
    root.show()
    qt_app.processEvents()
    image = panel.grab().toImage()
    scene_image = scene.grab().toImage()
    ratio = image.devicePixelRatio()
    assert image.pixelColor(round(50 * ratio), round(24 * ratio)).name() == "#213b60"
    assert image.pixelColor(round(50 * ratio), 0).name() == "#0c172a"
    assert scene_image.pixelColor(round(60 * ratio), round(30 * ratio)) != (
        scene_image.pixelColor(round(60 * ratio), round(60 * ratio))
    )
    assert label.palette().color(QPalette.ColorRole.WindowText) == QColor("#f4aaa4")
    assert not scroll.viewport().autoFillBackground()
    assert not scroll.widget().autoFillBackground()
    assert progress.grab().toImage().pixelColor(round(10 * ratio), round(7 * ratio)).name() == "#79c17d"
    assert "background: transparent; border: 0; padding: 1px" in control.styleSheet()


def test_fluent_sidebar_uses_pixel_selection_and_preserves_navigation(qt_app):
    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import NavigationInterface

    from auto_game_unified.desktop_qt import brand, style

    root = QWidget()
    navigation = NavigationInterface(root)
    navigation.addItem("tasks", brand.icon("nav-tasks"), "任务中心")
    navigation.addItem("logs", brand.icon("nav-logs"), "运行日志")
    style.apply_pixel_style(root)
    navigation.setCurrentItem("logs")
    root.show()
    qt_app.processEvents()
    assert navigation.widget("logs").isSelected
    assert not navigation.widget("tasks").isSelected
    selected = navigation.widget("logs").itemWidget.grab().toImage()
    inactive = navigation.widget("tasks").itemWidget.grab().toImage()
    ratio = selected.devicePixelRatio()
    assert selected.pixelColor(round(3 * ratio), round(5 * ratio)).name() == "#e0b45e"
    assert inactive.pixelColor(round(3 * ratio), round(5 * ratio)).name() == "#213e63"
