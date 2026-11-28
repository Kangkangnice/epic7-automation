"""Shared Arky identity and artwork for the Qt windows."""

from __future__ import annotations

import ctypes
from functools import cache
from pathlib import Path
import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

APP_NAME = "亚卡助手"
APP_SUBTITLE = "《第七史诗》任务自动化"
ASSETS = Path(__file__).with_name("assets")
ICONS = ASSETS / "icons"
MASCOT_ART = ASSETS / "mascot"
HERO_ART = MASCOT_ART / "idle.png"
COMPLETE_ART = MASCOT_ART / "success" / "03.png"
BADGE_ART = HERO_ART
LANDSCAPE_ART = ASSETS / "backgrounds" / "adventure-v67.png"
APP_ICON = Path(__file__).with_name("app.ico")
BRAND_ART = ASSETS / "brand"
LOGO_256 = BRAND_ART / "arky-logo-256.png"
LOGO_64 = BRAND_ART / "arky-logo-64.png"

BLUE = "#3979b6"
INK = "#f1f5ff"
MUTED = "#adbed4"
ROUTE_ICONS = {
    mode: ICONS / f"{mode}.png"
    for mode in (
        "arena", "shop_refresh", "world_boss", "knights_donation", "labyrinth_stone",
        "sanctuary", "community", "achievement", "pet_adoption", "hero_synthesis",
        "story", "fodder", "side_story", "moonlight_theater", "story_star",
        "penguin_purchase", "craft_equipment", "expedition", "tower", "survivor",
        "activity_story",
    )
}


@cache
def artwork(path: Path) -> QPixmap:
    return QPixmap(str(path))


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON))


@cache
def logo_pixmap(size: int = 64) -> QPixmap:
    """品牌 Logo 原样等比缩放，不裁切、不加边框或留白。"""
    source = LOGO_64 if size <= 64 else LOGO_256
    return artwork(source).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)


def motion_enabled() -> bool:
    """Respect the current Windows system preference for UI animation."""
    if sys.platform != "win32":
        return True
    enabled = ctypes.c_int()
    result = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    return not result or bool(enabled.value)


@cache
def icon_pixmap(name: str, size: int = 24, *, device_pixel_ratio: float = 1.0) -> QPixmap:
    """Scale approved pixel art into the control's device pixels."""
    path = ICONS / f"{name}.png"
    pixmap = artwork(path if path.is_file() else ICONS / "pending.png")
    pixels = round(size * device_pixel_ratio)
    scaled = pixmap.scaled(pixels, pixels, Qt.KeepAspectRatio, Qt.FastTransformation)
    scaled.setDevicePixelRatio(device_pixel_ratio)
    return scaled


@cache
def icon(name: str, size: int = 24) -> QIcon:
    result = QIcon()
    for ratio in (1.0, 1.25, 1.5, 2.0):
        result.addPixmap(icon_pixmap(name, size, device_pixel_ratio=ratio))
    return result


class _RouteEmblem(QLabel):
    def __init__(self, mode: str, size: int, parent: QWidget) -> None:
        super().__init__(parent)
        self._mode = mode
        self.setObjectName("routeEmblem")
        self.setProperty("routeMode", mode)
        self.setAlignment(Qt.AlignCenter)
        self.set_icon_size(size)

    def set_icon_size(self, size: int) -> None:
        self._size = size
        self.setFixedSize(size, size)
        self._update_pixmap()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._update_pixmap()
        return super().event(event)

    def _update_pixmap(self) -> None:
        self.setPixmap(icon_pixmap(self._mode, self._size, device_pixel_ratio=self.devicePixelRatioF()))


def route_emblem(mode: str, parent: QWidget, *, size: int = 24) -> _RouteEmblem:
    return _RouteEmblem(mode, size, parent)
