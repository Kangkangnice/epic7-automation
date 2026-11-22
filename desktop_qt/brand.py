"""Shared Arky identity and artwork for the Qt windows."""

from __future__ import annotations

import ctypes
from functools import cache
from pathlib import Path
import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import FluentIcon

APP_NAME = "亚卡助手"
APP_SUBTITLE = "《第七史诗》任务自动化"
ASSETS = Path(__file__).with_name("assets")
HERO_ART = ASSETS / "arky-ready.png"
COMPLETE_ART = ASSETS / "arky-complete.png"
BADGE_ART = ASSETS / "arky-badge.png"
APP_ICON = Path(__file__).with_name("app.ico")

BLUE = "#21577E"
INK = "#172F46"
MUTED = "#516779"
ROUTE_ICONS = {
    "arena": FluentIcon.GAME,
    "shop_refresh": FluentIcon.TAG,
    "world_boss": FluentIcon.GLOBE,
    "knights_donation": FluentIcon.SEND,
    "labyrinth_stone": FluentIcon.IOT,
    "sanctuary": FluentIcon.LEAF,
    "community": FluentIcon.CALENDAR,
    "achievement": FluentIcon.CERTIFICATE,
    "pet_adoption": FluentIcon.HEART,
    "hero_synthesis": FluentIcon.PEOPLE,
    "story": FluentIcon.DICTIONARY,
    "fodder": FluentIcon.SYNC,
    "side_story": FluentIcon.LIBRARY,
    "moonlight_theater": FluentIcon.QUIET_HOURS,
    "story_star": FluentIcon.ASTERISK,
    "penguin_purchase": FluentIcon.SHOPPING_CART,
    "craft_equipment": FluentIcon.DEVELOPER_TOOLS,
    "expedition": FluentIcon.FLAG,
    "tower": FluentIcon.APPLICATION,
    "survivor": FluentIcon.STOP_WATCH,
    "activity_story": FluentIcon.SCROLL,
}


@cache
def artwork(path: Path) -> QPixmap:
    return QPixmap(str(path))


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON))


def motion_enabled() -> bool:
    """Respect the current Windows system preference for UI animation."""
    if sys.platform != "win32":
        return True
    enabled = ctypes.c_int()
    result = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    return not result or bool(enabled.value)


@cache
def _route_pixmap(mode: str) -> QPixmap:
    icon = ROUTE_ICONS.get(mode, FluentIcon.DOCUMENT)
    return icon.icon(color=QColor(BLUE)).pixmap(QSize(17, 17), 2.0)


def route_emblem(mode: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("routeEmblem")
    label.setProperty("routeMode", mode)
    label.setPixmap(_route_pixmap(mode))
    return label
