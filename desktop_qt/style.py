"""V6.14 C1 metallic palette and pixel controls for Qt windows."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionButton,
    QWidget,
)
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    LineEdit,
    NavigationPanel,
    NavigationTreeWidget,
    PushButton,
    ToolButton,
    setCustomStyleSheet,
)

from auto_game_unified.desktop_qt import brand

BG = "#152640"
DEEP = "#101e34"
PANEL = "#213b60"
LINE = "#6586aa"
LIGHT = "#a7c4e2"
INK = brand.INK
MUTED = brand.MUTED
GOLD = "#f3c86d"
HEADING = "#f8deb0"
GREEN = "#8edb89"
RED = "#f4aaa4"
TILE = "#2b496f"
NAVIGATION_BG = "#172e4b"
PRIMARY = "#297b49"
DANGER = "#87464d"
SELECTED = "#e0b45e"
_SELECTED_INK = "#172842"
_SELECTED_LIGHT = "#ffe6a3"
_SELECTED_SHADOW = "#926a30"
_DISABLED = "#263b55"
_DISABLED_INK = "#8ea2bb"

_BUTTON_QSS = f"""
QPushButton, QToolButton, SegmentedItem {{
    color: {INK};
    background-color: #315577;
    border: 2px solid #6e95b8;
    border-right-color: #162c49;
    border-bottom-color: #162c49;
    border-radius: 0;
    padding: 4px 8px;
}}
QPushButton:hover, QToolButton:hover, SegmentedItem:hover {{
    background-color: #41698f;
    border-color: {LIGHT};
}}
QPushButton:pressed, QToolButton:pressed {{ background-color: #223e61; }}
PrimaryPushButton, PrimaryToolButton, QPushButton[pixelRole="primary"] {{
    background-color: {PRIMARY};
    border-color: #79b886;
    border-right-color: #16482d;
    border-bottom-color: #16482d;
}}
PrimaryPushButton:hover, PrimaryToolButton:hover, QPushButton[pixelRole="primary"]:hover {{
    background-color: #36965b;
}}
QPushButton[pixelRole="danger"], QToolButton[pixelRole="danger"] {{
    background-color: {DANGER};
    border-color: #c1878b;
    border-right-color: #502b36;
    border-bottom-color: #502b36;
}}
QPushButton[pixelRole="danger"]:hover, QToolButton[pixelRole="danger"]:hover {{
    background-color: #a45158;
}}
QPushButton[pixelRole="settings"]:enabled, QToolButton[pixelRole="settings"]:enabled {{
    background-color: #e2b75f;
    color: #182840;
    border-color: #ffdfa0 #906531 #906531 #ffdfa0;
    padding: 2px 3px;
    font-size: 12px;
}}
QPushButton[pixelRole="settings"]:hover:enabled, QToolButton[pixelRole="settings"]:hover:enabled {{
    background-color: #efc674;
}}
QPushButton[pixelRole="nav"] {{
    background-color: #213e63;
    border-color: #41628a;
    border-right-color: #14253e;
    border-bottom-color: #14253e;
    text-align: left;
}}
QPushButton[pixelRole="nav"]:hover {{ background-color: #2a5077; }}
QPushButton[pixelRole="nav"]:checked, QPushButton[pixelRole="nav"][pixelSelected="true"],
SegmentedItem[isSelected="true"] {{
    background-color: {SELECTED};
    color: {_SELECTED_INK};
    border-color: {_SELECTED_LIGHT} {_SELECTED_SHADOW} {_SELECTED_SHADOW} {_SELECTED_LIGHT};
}}
QPushButton:focus, QToolButton:focus,
QPushButton[pixelRole]:focus:enabled, QToolButton[pixelRole]:focus:enabled {{ border-color: {GOLD}; }}
QPushButton:disabled, QToolButton:disabled,
QPushButton[pixelRole]:disabled, QToolButton[pixelRole]:disabled {{
    background-color: {_DISABLED};
    color: {_DISABLED_INK};
    border-color: #415a76;
}}
"""
_FIELD_QSS = f"""
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QAbstractItemView, ComboBox, PixelComboBox {{
    color: {INK};
    background-color: {DEEP};
    border: 1px solid #6687aa;
    border-top-color: #3e5878;
    border-left-color: #3e5878;
    border-radius: 0;
    selection-color: {DEEP};
    selection-background-color: {SELECTED};
}}
ComboBox, PixelComboBox {{ text-align: left; padding: 4px 26px 4px 7px; }}
ComboBox:hover, PixelComboBox:hover {{ border-color: {LIGHT}; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus,
ComboBox:focus, PixelComboBox:focus {{
    border-color: {GOLD};
}}
QLineEdit:disabled, QComboBox:disabled, ComboBox:disabled, PixelComboBox:disabled {{
    color: {_DISABLED_INK};
    background-color: {_DISABLED};
}}
"""
_CHECK_QSS = f"""
QCheckBox, CheckBox, PixelCheckBox {{
    color: {INK};
    spacing: 7px;
    background: transparent;
}}
QCheckBox::indicator, CheckBox::indicator, PixelCheckBox::indicator {{
    image: none;
    width: 13px;
    height: 13px;
    border: 2px solid #88a9c8;
    border-radius: 0;
    background: {DEEP};
}}
PixelCheckBox::indicator:hover, PixelCheckBox::indicator:focus {{ border-color: {LIGHT}; }}
PixelCheckBox::indicator:checked {{
    background: {GOLD};
    border-color: #ffe4a1 #997038 #997038 #ffe4a1;
}}
PixelCheckBox:disabled {{ color: {_DISABLED_INK}; }}
PixelCheckBox::indicator:disabled {{ border-color: #415a76; }}
"""
_NAVIGATION_QSS = f"""
NavigationPanel {{ background: {NAVIGATION_BG}; border: 0; border-right: 2px solid #3a5878; }}
"""
_PIXEL_QSS = f"""
QScrollArea {{ background-color: transparent; border: 0; }}
QScrollBar:vertical {{ width: 9px; }}
QScrollBar:horizontal {{ height: 9px; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background: #12253c; border: 0; }}
QScrollBar::handle {{ background: #7699bb; border: 2px solid #244566; min-width: 15px; min-height: 15px; }}
QScrollBar::handle:hover {{ background: {LIGHT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ color: {INK}; background-color: {DEEP}; border: 1px solid {LINE}; }}
QProgressBar {{
    color: {INK};
    background-color: #0d1b30;
    border: 1px solid #92b0cc;
    border-radius: 0;
    padding: 1px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, x2:1, stop:0 #79c17d, stop:0.83 #79c17d, stop:0.84 #4d9461, stop:1 #4d9461);
    width: 12px;
}}
{_BUTTON_QSS}
{_FIELD_QSS}
{_CHECK_QSS}
"""


def apply_pixel_style(widget: QWidget) -> None:
    """Apply the palette to one window, with local styles for Fluent overrides."""
    palette = widget.palette()
    role = QPalette.ColorRole
    for name, color in (
        (role.Window, BG), (role.Base, DEEP), (role.AlternateBase, PANEL),
        (role.Button, TILE), (role.WindowText, INK), (role.Text, INK), (role.ButtonText, INK),
        (role.Highlight, SELECTED), (role.HighlightedText, DEEP),
        (role.ToolTipBase, DEEP), (role.ToolTipText, INK),
    ):
        palette.setColor(name, QColor(color))
    for name in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, name, QColor(MUTED))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)
    if not widget.property("arkyPixelStyle"):
        widget.setStyleSheet(_PIXEL_QSS + widget.styleSheet())
        widget.setProperty("arkyPixelStyle", True)

    for area in widget.findChildren(QScrollArea):
        area.viewport().setAutoFillBackground(False)
        if area.widget() is not None:
            area.widget().setAutoFillBackground(False)
    for panel in widget.findChildren(NavigationPanel):
        setCustomStyleSheet(panel, _NAVIGATION_QSS, _NAVIGATION_QSS)
    for item in widget.findChildren(NavigationTreeWidget):
        if item.isLeaf() and not item.property("arkyPixelNavigation"):
            item.itemWidget.installEventFilter(_PixelNavigation(item.itemWidget))
            item.setProperty("arkyPixelNavigation", True)
    for control in widget.findChildren(QWidget):
        if isinstance(control, (PushButton, ToolButton, ComboBox, LineEdit, PixelCheckBox)) and not (
            control.property("arkyPixelControl")
        ):
            if isinstance(control, PixelCheckBox):
                qss = _CHECK_QSS
            elif isinstance(control, (ComboBox, LineEdit)):
                qss = _FIELD_QSS
            else:
                qss = _BUTTON_QSS
            local_qss = control.styleSheet().strip()
            setCustomStyleSheet(control, qss, qss)
            if local_qss and not control.styleSheet().strip().startswith(local_qss):
                # Fluent rebuilds its registered rules and can drop a direct setStyleSheet call.
                qss = f"{qss}\n{local_qss}"
                setCustomStyleSheet(control, qss, qss)
            control.setProperty("arkyPixelControl", True)


class PixelCheckBox(CheckBox):
    """Keep the Fluent checkbox interaction and paint a square indicator."""

    def paintEvent(self, event) -> None:  # noqa: N802
        QCheckBox.paintEvent(self, event)
        state = self.checkState()
        if state == Qt.Unchecked:
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        center = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self).center()
        painter = QPainter(self)
        painter.translate(center)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        if state == Qt.PartiallyChecked:
            painter.fillRect(-4, -1, 9, 3, QColor(GOLD))
        else:
            ink = QColor("#182a44")
            for x, y in ((-4, 0), (-2, 2), (0, 0), (2, -2), (4, -4)):
                painter.fillRect(x, y, 2, 2, ink)


class PixelComboBox(ComboBox):
    """Use the supplied pixel arrow with the existing selection menu."""

    def paintEvent(self, event) -> None:  # noqa: N802
        QPushButton.paintEvent(self, event)
        painter = QPainter(self)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        art = brand.icon_pixmap("chevron", 14, device_pixel_ratio=self.devicePixelRatioF())
        painter.drawPixmap(self.width() - 20, (self.height() - 14) // 2, art)

    def _createComboMenu(self):
        menu = super()._createComboMenu()
        qss = f"""
        #comboListWidget {{
            background-color: {DEEP}; color: {INK}; border: 1px solid {LINE}; border-radius: 0;
        }}
        #comboListWidget::item {{ border-radius: 0; }}
        #comboListWidget::item:selected {{ background: #2c496b; color: {INK}; }}
        """
        setCustomStyleSheet(menu, qss, qss)
        return menu


class _PixelNavigation(QObject):
    """Paint Fluent's leaf navigation items using their existing interaction state."""

    def eventFilter(self, item, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Paint:
            return False

        selected = item.parent().isSelected
        if selected:
            background, light, shadow = SELECTED, _SELECTED_LIGHT, _SELECTED_SHADOW
        else:
            background = "#2a5077" if item.isEnter else "#213e63"
            light, shadow = "#41628a", "#14253e"

        painter = QPainter(item)
        if item.isPressed or not item.isEnabled():
            painter.setOpacity(0.65)
        width, height = item.width(), item.height()
        painter.fillRect(item.rect(), QColor(background))
        painter.fillRect(0, 0, width, 2, QColor(light))
        painter.fillRect(0, 2, 2, height - 2, QColor(light))
        painter.fillRect(2, height - 2, width - 2, 2, QColor(shadow))
        painter.fillRect(width - 2, 2, 2, height - 2, QColor(shadow))

        size = 27
        x = (width - size) // 2 if item.isCompacted else 9
        y = (height - size) // 2
        icon = item.icon().pixmap(QSize(size, size), item.devicePixelRatioF())
        painter.drawPixmap(x, y, icon)
        if not item.isCompacted:
            painter.setPen(QColor(_SELECTED_INK if selected else INK))
            font = item.font()
            font.setBold(True)
            painter.setFont(font)
            text_rect = QRect(x + size + 9, 0, width - size - 2 * x - 9, height)
            text = item.fontMetrics().elidedText(item.text(), Qt.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        return True


def _paint_frame(painter: QPainter, bounds: QRect) -> None:
    """Draw the 8px slices around the panel without resampling its center."""
    frame = brand.artwork(brand.ASSETS / "frame.png")
    x = (0, 8, bounds.width() - 8, bounds.width())
    y = (0, 8, bounds.height() - 8, bounds.height())
    for row in range(3):
        for column in range(3):
            if row == column == 1:
                continue
            target = QRect(x[column], y[row], x[column + 1] - x[column], y[row + 1] - y[row])
            painter.drawPixmap(target, frame, QRect(8 * column, 8 * row, 8, 8))


_TILE_TONES = {
    "tile": (TILE, "#1b3453", "#577da2", "#1b3453"),
    "deep": (DEEP, "#10213a", LINE, "#0c172a"),
    "selected": ("#304d70", "#e9c47b", "#ffebaa", "#9d783d"),
}
_ROW_TONES = {
    "listrow": ("#213d60", "#3f6286", "#698eb3"),
    "listrow-alt": ("#29486c", "#3f6286", "#698eb3"),
    "listrow-selected": ("#2c496b", "#d9b05e", "#d9b05e"),
}


class PixelPanel(QWidget):
    """Paint one framed panel or stepped card, with transparent child widgets."""

    def __init__(self, parent: QWidget | None = None, *, tone: str = "panel") -> None:
        super().__init__(parent)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._tone == "panel":
            painter.fillRect(self.rect().adjusted(4, 4, -4, -4), QColor(PANEL))
            _paint_frame(painter, self.rect())
            return

        if self._tone in _ROW_TONES:
            base, border, light = (QColor(color) for color in _ROW_TONES[self._tone])
            painter.fillRect(self.rect(), border)
            painter.fillRect(self.rect().adjusted(2, 1, -1, -1), base)
            painter.fillRect(0, 0, 2, self.height(), light)
            return

        base, border, light, shadow = (QColor(color) for color in _TILE_TONES[self._tone])
        width, height = self.width(), self.height()
        painter.fillRect(4, 0, width - 8, height, border)
        painter.fillRect(0, 4, width, height - 8, border)
        painter.fillRect(4, 2, width - 8, height - 4, base)
        painter.fillRect(2, 4, width - 4, height - 8, base)
        painter.fillRect(4, 2, width - 8, 2, light)
        painter.fillRect(2, 4, 2, height - 8, light)
        painter.fillRect(4, height - 4, width - 8, 2, shadow)
        painter.fillRect(width - 4, 4, 2, height - 8, shadow)


class PixelBackground(QWidget):
    """Crop the approved adventure scene to fit each display surface."""

    def __init__(self, scene: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = scene

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        art = brand.artwork(brand.LANDSCAPE_ART)
        scale = max(self.width() / art.width(), self.height() / art.height())
        width, height = round(self.width() / scale), round(self.height() / scale)
        horizontal = 0.76 if self._scene == "sidebar" else 0.5
        vertical = 0.58 if self._scene == "banner" else 0.55
        source = QRect(
            round((art.width() - width) * horizontal),
            round((art.height() - height) * vertical),
            width,
            height,
        )
        painter.drawPixmap(self.rect(), art, source)
        painter.setPen(QColor("#4b6f95"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self._scene != "sidebar":
            painter.fillRect(0, 0, self.width(), 1, QColor(LIGHT))


# PySide6 6.12 clips the text in the Fluent SpinBox's inner editor.
# Style the native QSpinBox while retaining its spin and keyboard behavior.
SPIN_BOX_QSS = f"""
QSpinBox {{
    color: {INK};
    background-color: {DEEP};
    border: 1px solid #6687aa;
    border-top-color: #3e5878;
    border-left-color: #3e5878;
    border-radius: 0;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 14px;
}}
QSpinBox QLineEdit {{ color: {INK}; background: transparent; border: 0; padding: 0; }}
QSpinBox:disabled QLineEdit {{ color: {_DISABLED_INK}; }}
QSpinBox:focus {{ border-color: {GOLD}; }}
QSpinBox:disabled {{ color: {_DISABLED_INK}; background-color: {_DISABLED}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 20px; border: none; background: transparent;
}}
"""
