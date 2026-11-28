"""Native, non-activating companion for the current desktop run."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable, Sequence

from PySide6.QtCore import (
    QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTime, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QCursor, QPainter, QScreen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QWidget

from auto_game_unified.desktop.run_progress import (
    FAILURE,
    IDLE,
    OUTCOME_LABELS,
    RUNNING,
    STOPPED,
    STOPPING,
    SUCCESS,
    RunProgress,
)
from auto_game_unified.desktop_qt import brand
from auto_game_unified.desktop_qt.mascot import ArkyAnimation, ArkyMascot

STRIP_WIDTH = 126
STRIP_HEIGHT = 128
_RIGHT_GAP = 88
_BOTTOM_GAP = 26
_BUBBLE_WIDTH = 96
_BUBBLE_HEIGHT = 76
_LOG_WIDTH = 328
# 最小高度：5 行各占一行时的高度（28 标题区 + 5×16 行 + 12 内边距 + 12 尖角）。
# 日志换行后按实际内容增高，不再截断。
_LOG_HEIGHT = 132
_LOG_TAIL = 12
_LOG_GAP = 6
_LOG_ROWS = 5
_LOG_TIMESTAMP = re.compile(r"^(?:\d{4}-\d{2}-\d{2}[ T])?(\d{2}:\d{2}:\d{2})\s+(.+)$")
_ART_SIZE = 122
_ART_TOP = -24
_ART_LIFT = 6
_ART_X = (STRIP_WIDTH - _ART_SIZE) // 2
_WINDOW_FLAGS = (
    Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
)

_DEFAULT_PALETTE = ("#81a8d0", "#eac272", "#f3f6ff", "#e2b964", "#ffe4a1")
_PALETTES = {
    SUCCESS: ("#84b995", "#a8db9e", "#a4e3a4", "#79c77c", "#c6efb7"),
    FAILURE: ("#b77c87", "#daa1a2", "#f4aaa4", "#bc6975", "#bc6975"),
    STOPPED: ("#b2917b", "#e4b485", "#f0bd88", "#d4a569", "#ffe1aa"),
}

# The embedded outlines use the approved prototype's coordinates and layered pixel edges.
_PLAQUE_ART = """
<path fill="#09172b" d="M29 3H97V7H105V12H113V18H119V26H124V71H119V79H113V85H105V90H97V93H29V90H21V85H13V79H7V71H2V26H7V18H13V12H21V7H29Z"/>
<path fill="#09182f" d="M29 0H97V4H105V9H113V15H119V23H124V68H119V76H113V82H105V87H97V90H29V87H21V82H13V76H7V68H2V23H7V15H13V9H21V4H29Z"/>
<path fill="{rim}" d="M29 2H97V6H105V11H112V17H117V25H122V66H117V74H112V80H104V85H97V88H29V85H22V80H14V74H9V66H4V25H9V17H14V11H22V6H29Z"/>
<path fill="#375a84" d="M30 5H96V9H104V14H110V20H115V27H119V65H115V72H110V78H103V83H96V86H30V83H23V78H16V72H11V65H7V27H11V20H16V14H23V9H30Z"/>
<path fill="#1a3052" d="M31 8H95V12H103V17H108V23H112V29H116V64H112V71H107V76H102V80H95V83H31V80H24V76H19V71H14V64H10V29H14V23H18V17H24V12H31Z"/>
<path fill="{accent}" d="M9 23H13V30H9ZM113 23H117V30H113ZM9 64H13V70H17V75H23V78H17V76H13V72H9ZM113 64H117V72H113V76H109V78H103V75H109V70H113Z"/>
<path fill="#ffdf9b" d="M10 24H12V28H10ZM114 24H116V28H114ZM10 65H12V70H10ZM114 65H116V70H114Z"/>
"""
_BUBBLE_ART = """
<path fill="#0a192e" d="M29 0H70V3H79V7H85V13H90V21H94V50H90V58H85V64H79V69H70V72H29V69H22V65H16V59H12V48L0 37L12 27V15H16V9H22V4H29Z"/>
<path fill="#91b4d4" d="M29 2H70V5H78V9H83V15H88V22H92V49H88V57H83V62H78V67H70V70H29V67H23V63H18V57H14V47L3 37L14 28V16H18V11H23V6H29Z"/>
<path fill="#40658a" d="M30 5H69V8H77V12H81V17H85V24H89V48H85V55H81V60H76V64H69V67H30V64H24V61H21V55H17V46L7 37L17 29V18H21V13H24V9H30Z"/>
<path fill="#213b60" d="M31 8H68V11H76V15H79V20H82V26H86V47H82V53H79V58H75V61H68V64H31V61H26V58H23V53H20V45L11 37L20 31V20H23V16H26V12H31Z"/>
"""
_BUBBLE_QSS = """
QPushButton {
    background: #e3b866; color: #182a45; border: 1px solid;
    border-color: #ffe2a0 #9b7438 #9b7438 #ffe2a0;
    border-radius: 6px; padding: 0; font-size: 10px; font-weight: 600;
}
QPushButton:hover { background: #ffe3a4; border-color: #fff0bf; }
QPushButton#runStripStop {
    background: #9a5a60; color: #fff0e6;
    border-color: #e0a2a0 #6b3948 #6b3948 #e0a2a0;
}
QPushButton#runStripStop:hover:enabled { background: #bd6b70; }
QPushButton#runStripStop:disabled {
    background: #544354; color: #a38c94; border-color: #6c5769 #403548 #403548 #6c5769;
}
"""


def _svg(view_box: str, paths: str) -> QSvgRenderer:
    return QSvgRenderer(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">{paths}</svg>'.encode()
    )


def _prepare_window(widget: QWidget) -> None:
    widget.setAttribute(Qt.WA_TranslucentBackground)
    widget.setAttribute(Qt.WA_ShowWithoutActivating)
    widget.setFocusPolicy(Qt.NoFocus)


class _HoverBubble(QWidget):
    """A transient tool window keeps the companion's position and hit area stable."""

    pointer_entered = Signal()
    pointer_left = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, _WINDOW_FLAGS)
        _prepare_window(self)
        self._opening = False
        self._frame = QRectF(1, 1, 0, 0)
        self._settled = QRectF(0, 0, 1, 1)
        self._animation = QVariantAnimation(self)
        self._animation.valueChanged.connect(self._set_frame)
        self._animation.finished.connect(self._finish_motion)

    def open(self) -> bool:
        if self._opening:
            return False
        start_frame = self._frame if self.isVisible() else None
        self._opening = True
        self.show()
        self._play_motion(start_frame)
        return True

    def dismiss(self, *, immediate: bool = False) -> None:
        if immediate:
            self._opening = False
            self._animation.stop()
            self.hide()
        elif self._opening:
            self._opening = False
            self._play_motion()

    def _play_motion(self, start_frame: QRectF | None = None) -> None:
        self._animation.stop()
        if not brand.motion_enabled():
            self._finish_motion()
            return
        self._animation.setDuration(370 if self._opening else 190)
        self._show_content(0)
        if self._opening:
            frames = [
                (0.0, start_frame if start_frame is not None else QRectF(0, 9, .10, .24)),
                (.37, QRectF(0, -2, 1.10, .86)),
                (.62, QRectF(0, 1, .96, 1.08)),
                (.82, QRectF(0, 0, 1.025, .98)),
                (1.0, self._settled),
            ]
        else:
            frames = [(0.0, self._frame), (1.0, QRectF(-8, 9, .15, .28))]
        self._animation.setKeyValues(frames)
        self._animation.setCurrentTime(0)
        self._frame = frames[0][1]
        self._animation.start()

    def _set_frame(self, frame: QRectF) -> None:
        self._frame = frame
        if self._opening:
            self._show_content(self._animation.currentTime())
        self.update()

    def _finish_motion(self) -> None:
        if self._opening:
            self._frame = self._settled
            self._show_content(370)
            self.update()
        else:
            self.hide()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.pointer_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.pointer_left.emit()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._animation.state() == QVariantAnimation.Running:
            elapsed = self._animation.currentTime()
            opacity = min(1.0, elapsed / 120) if self._opening else max(0.0, 1 - elapsed / 140)
            painter.setOpacity(opacity)
        self._paint_frame(painter, self._frame)

    @staticmethod
    def _scale_frame(painter: QPainter, frame: QRectF, anchor: QPointF) -> None:
        painter.translate(anchor + frame.topLeft())
        painter.scale(frame.width(), frame.height())
        painter.translate(-anchor)


class _ActionBubble(_HoverBubble):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("runStripBubble")
        self.setFixedSize(_BUBBLE_WIDTH, _BUBBLE_HEIGHT)
        self.setStyleSheet(_BUBBLE_QSS)
        self._art = _svg("0 0 94 72", _BUBBLE_ART)
        self._left = False
        self.restore_button = self._button("runStripRestore", "回到主页", "nav-logs")
        self.stop_button = self._button("runStripStop", "安全停止", "stop")

    def _button(self, name: str, label: str, icon: str) -> QPushButton:
        button = QPushButton(brand.icon(icon, 12), label, self)
        button.setObjectName(name)
        button.setFocusPolicy(Qt.NoFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setIconSize(QSize(12, 12))
        return button

    def open_at(self, plaque: QRect, area: QRect) -> bool:
        left = plaque.x() + plaque.width() - 20
        self._left = left + self.width() > area.right() + 1
        if self._left:
            left = plaque.x() - self.width() + 20
        top = plaque.y() + (-18 if plaque.y() - area.top() >= 26 else 7)
        self.move(
            max(area.left(), min(left, area.right() - self.width() + 1)),
            max(area.top(), min(top, area.bottom() - self.height() + 1)),
        )
        return self.open()

    def _show_content(self, elapsed: int) -> None:
        x = 10 if self._left else 18
        self.restore_button.setGeometry(x, 11, 68, 25)
        self.stop_button.setGeometry(x, 40, 68, 25)
        self.restore_button.setVisible(elapsed >= 120)
        self.stop_button.setVisible(elapsed >= 170)

    def _paint_frame(self, painter: QPainter, frame: QRectF) -> None:
        if self._left:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        self._scale_frame(painter, frame, QPointF(8, self.height() * .48))
        self._art.render(painter, QRectF(0, 0, self.width(), self.height()))


def _log_outline(body: QRect, side: str, tail: int) -> str:
    layers = []
    for inset, color in ((0, "#0a192e"), (2, "#91b4d4"), (5, "#40658a"), (8, "#213b60")):
        inner = body.adjusted(inset, inset, -inset, -inset)
        left, top, right, bottom = inner.getCoords()
        depth, half = _LOG_TAIL - inset, 15 - inset
        tips = {
            "top": ((tail - half, top), (tail, top - depth), (tail + half, top)),
            "right": ((right, tail - half), (right + depth, tail), (right, tail + half)),
            "bottom": ((tail + half, bottom), (tail, bottom + depth), (tail - half, bottom)),
            "left": ((left, tail + half), (left - depth, tail), (left, tail - half)),
        }
        points = (
            (left + 16, top), *(tips["top"] if side == "top" else ()),
            (right - 16, top), (right - 16, top + 3), (right - 9, top + 3),
            (right - 9, top + 7), (right - 4, top + 7), (right - 4, top + 13),
            (right, top + 13),
            *(tips["right"] if side == "right" else ()),
            (right, bottom - 13), (right - 4, bottom - 13), (right - 4, bottom - 7),
            (right - 9, bottom - 7), (right - 9, bottom - 3), (right - 16, bottom - 3),
            (right - 16, bottom),
            *(tips["bottom"] if side == "bottom" else ()),
            (left + 16, bottom), (left + 16, bottom - 3), (left + 9, bottom - 3),
            (left + 9, bottom - 7), (left + 4, bottom - 7), (left + 4, bottom - 13),
            (left, bottom - 13),
            *(tips["left"] if side == "left" else ()),
            (left, top + 13), (left + 4, top + 13), (left + 4, top + 7),
            (left + 9, top + 7), (left + 9, top + 3), (left + 16, top + 3),
        )
        outline = " ".join(f"{x},{y}" for x, y in points)
        layers.append(f'<polygon fill="{color}" points="{outline}"/>')
    return "".join(layers)


class _LogBubble(_HoverBubble):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("runStripLogBubble")
        self.setAccessibleName("实时日志")
        self._heading = QLabel("实时日志", self)
        self._heading.setStyleSheet("color: #ffe2a0; font-size: 12px; font-weight: 700;")
        self._rows = [
            QLabel(self, objectName="runStripLogLine", textFormat=Qt.PlainText)
            for _ in range(_LOG_ROWS)
        ]
        for label in (self._heading, *self._rows):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        for label in self._rows:
            label.setStyleSheet("color: #eef4ff; font-size: 11px;")
            # 长日志按气泡宽度折行显示完整内容，不再用 elidedText 截成省略号。
            label.setWordWrap(True)
        self._lines: tuple[str, ...] = ()
        self._shape: tuple[str, int, int, int] | None = None
        self._placement: tuple[QRect, QRect, QRect, QRect] | None = None

    def _row_heights(self, width: int) -> list[int]:
        """每条日志折行后的像素高度；行不够五个时按空行补齐。"""
        metrics = self._rows[0].fontMetrics()
        # 两侧边框、尖角与内边距都占掉可用宽度，留得比 QLabel 实际稍窄一点，
        # 保证测出来的行数不少于界面上的行数（宁可高一点，也不把字裁掉）。
        text_width = max(1, width - 32 - _LOG_TAIL)
        heights: list[int] = []
        for index in range(_LOG_ROWS):
            line = self._lines[index] if index < len(self._lines) else ""
            parts = line.split("\n") or [""]
            heights.append(
                max(
                    16,
                    sum(
                        metrics.boundingRect(0, 0, text_width, 0, Qt.TextWordWrap, part).height()
                        for part in parts
                    ),
                )
            )
        return heights

    def _height_for(self, width: int) -> int:
        """标题区 + 全部折行后的行高 + 下内边距 + 尖角。"""
        return _LOG_TAIL + 28 + sum(self._row_heights(width)) + 12

    def open_at(self, plaque: QRect, overhang: QRect, action: QRect, area: QRect) -> None:
        self._placement = (plaque, overhang, action, area)
        width = min(_LOG_WIDTH, area.width())
        x = max(area.left(), min(plaque.center().x() - width // 2, area.right() - width + 1))
        above = overhang.top() if overhang.isValid() else plaque.top()
        left = plaque.left() - _LOG_GAP
        right = plaque.right() + _LOG_GAP + 1
        left_width = min(width, left - area.left())
        right_width = min(width, area.right() - right + 1)
        top_height = self._height_for(width)
        left_height = self._height_for(left_width)
        right_height = self._height_for(right_width)
        center_y = plaque.center().y()
        candidates = (
            ("top", QRect(x, plaque.bottom() + _LOG_GAP + 1, width, top_height)),
            ("bottom", QRect(x, above - _LOG_GAP - top_height, width, top_height)),
            ("right", QRect(left - left_width, center_y - left_height // 2, left_width, left_height)),
            ("left", QRect(right, center_y - right_height // 2, right_width, right_height)),
        )
        for side, bounds in candidates:
            if bounds.width() < 148 or not area.contains(bounds) or bounds.intersects(action):
                continue
            vertical = side in {"top", "bottom"}
            if vertical:
                tail = plaque.center().x() - bounds.x()
            else:
                tail = center_y - bounds.y()
            tail = max(34, min(tail, (bounds.width() if vertical else bounds.height()) - 34))
            self._place(bounds, side, tail)
            self.open()
            return
        self.dismiss(immediate=True)

    def _place(self, bounds: QRect, side: str, tail: int) -> None:
        shape = (side, tail, bounds.width(), bounds.height())
        changed = shape != self._shape
        self.setGeometry(bounds)
        self._shape = shape
        if not changed:
            return
        body = self.rect().adjusted(
            _LOG_TAIL if side == "left" else 0,
            _LOG_TAIL if side == "top" else 0,
            -_LOG_TAIL if side == "right" else 0,
            -_LOG_TAIL if side == "bottom" else 0,
        )
        self._art = _svg(f"0 0 {self.width()} {self.height()}", _log_outline(body, side, tail))
        self._anchor = {
            "top": QPointF(tail, 5),
            "bottom": QPointF(tail, self.height() - 6),
            "left": QPointF(5, tail),
            "right": QPointF(self.width() - 6, tail),
        }[side]
        self._heading.setGeometry(body.x() + 16, body.y() + 10, body.width() - 32, 17)
        self._layout_rows()

    def _layout_rows(self) -> None:
        if self._shape is None:
            return
        side = self._shape[0]
        body = self.rect().adjusted(
            _LOG_TAIL if side == "left" else 0,
            _LOG_TAIL if side == "top" else 0,
            -_LOG_TAIL if side == "right" else 0,
            -_LOG_TAIL if side == "bottom" else 0,
        )
        y = body.y() + 28
        for row, height in zip(self._rows, self._row_heights(self.width()), strict=True):
            row.setGeometry(body.x() + 16, y, body.width() - 32, height)
            y += height

    def set_lines(self, lines: Iterable[str]) -> None:
        self._lines = tuple(lines)
        for index, row in enumerate(self._rows):
            line = self._lines[index] if index < len(self._lines) else ""
            row.setAccessibleName(line)
            row.setText(line)
        if self._shape is None:
            return
        self._layout_rows()
        side, tail, width, height = self._shape
        wanted = self._height_for(width)
        if wanted != height:
            self.setGeometry(self.x(), self.y(), width, wanted)
            if self.isVisible() and self._placement is not None:
                self.open_at(*self._placement)

    def _show_content(self, elapsed: int) -> None:
        visible = elapsed >= 170
        self._heading.setVisible(visible)
        for row in self._rows:
            row.setVisible(visible)

    def _paint_frame(self, painter: QPainter, frame: QRectF) -> None:
        self._scale_frame(painter, frame, self._anchor)
        self._art.render(painter, QRectF(self.rect()))


class _MascotOverhang(QWidget):
    """Complete the sprite above the plaque while leaving desktop input untouched."""

    def __init__(self, parent: QWidget, animation: ArkyAnimation) -> None:
        super().__init__(parent, _WINDOW_FLAGS | Qt.WindowTransparentForInput)
        _prepare_window(self)
        self.setObjectName("runStripMascotOverhang")
        self._animation = animation
        self._sprite_top = _ART_TOP
        animation.frame_changed.connect(self.update)

    def set_sprite_top(self, top: int) -> None:
        self._sprite_top = top
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        art = self._animation.pixmap()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        target = QRectF(0, self.height() + self._sprite_top, _ART_SIZE, _ART_SIZE)
        painter.drawPixmap(target, art, QRectF(art.rect()))


class RunPanel(QWidget):
    """Always-on-top plaque with a shared mascot, route progress and hover bubbles."""

    open_main_requested = Signal()
    stop_clicked = Signal()
    drag_moved = Signal(QPoint, QPoint)
    drag_finished = Signal()

    def __init__(self, animation: ArkyAnimation) -> None:
        super().__init__(None, _WINDOW_FLAGS)
        _prepare_window(self)
        self.setObjectName("runStrip")
        self.setAccessibleName("任务运行浮窗")
        self.setAccessibleDescription("悬停展开操作和实时日志，拖动调整位置")
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedSize(STRIP_WIDTH, STRIP_HEIGHT)
        self._press: QPoint | None = None
        self._offset = QPoint()
        self._dragged = False
        self._route_mode = "pending"
        self._outcome = IDLE
        self._palette = None
        self._plaque = QSvgRenderer(self)
        self._spark = _svg(
            "0 0 12 12", '<path fill="#eac272" d="M1 1H3V5H1ZM6 2H8V4H6V6H4V4H6ZM8 8H12V10H8Z"/>'
        )
        self._hover_motion = QVariantAnimation(self, duration=550, startValue=0.0, endValue=1.0)
        self._hover_motion.valueChanged.connect(self._animate_mascot)
        self._close_timer = QTimer(self, interval=160, singleShot=True)
        self._close_timer.timeout.connect(self._dismiss_when_clear)

        self._mascot = ArkyMascot(self, height=_ART_SIZE, animation=animation)
        self._mascot.setGeometry(_ART_X, _ART_TOP, _ART_SIZE, _ART_SIZE)
        self._overhang = _MascotOverhang(self, animation)
        self._icon = QLabel(self, objectName="runStripIcon")
        self._icon.setFixedSize(22, 22)
        self._title = QLabel(self, objectName="runStripTitle", textFormat=Qt.PlainText)
        self._percent = QLabel(self, objectName="runStripPercent")
        self._percent.setGeometry(81, 98, 27, 17)
        self._percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._bar = QProgressBar(self, objectName="runStripProgress", textVisible=False)
        self._bar.setGeometry(19, 103, 57, 10)
        self._bar.setAccessibleName("路线处理进度")
        for widget in (self._mascot, self._icon, self._title, self._percent, self._bar):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._bubble = _ActionBubble(self)
        self._bubble.pointer_entered.connect(self._show_actions)
        self._bubble.pointer_left.connect(self._close_timer.start)
        self._bubble.restore_button.clicked.connect(self.open_main_requested.emit)
        self._bubble.stop_button.clicked.connect(self.stop_clicked.emit)
        self._log_bubble = _LogBubble(self)
        self._log_bubble.pointer_entered.connect(self._show_actions)
        self._log_bubble.pointer_left.connect(self._close_timer.start)

    def set_presentation(self, progress: RunProgress, outcome: str, notice: str = "") -> None:
        self._outcome = outcome
        palette = _PALETTES.get(STOPPED if outcome == STOPPING else outcome, _DEFAULT_PALETTE)
        rim, accent, title, bar, highlight = palette
        if palette != self._palette:
            self._palette = palette
            paths = _PLAQUE_ART.format(rim=rim, accent=accent)
            self._plaque = _svg("0 0 126 93", paths)
            self._title.setStyleSheet(f"color: {title}; font-size: 12px; font-weight: 700;")
            self._percent.setStyleSheet(f"color: {title}; font-size: 11px; font-weight: 700;")
            self._bar.setStyleSheet(
                "QProgressBar { background: #101e34; border: 1px solid #7199bc; "
                "border-radius: 3px; padding: 1px; } "
                f"QProgressBar::chunk {{ background: {bar}; border-top: 1px solid {highlight}; }}"
            )

        if progress.active_mode:
            self._route_mode = progress.active_mode
        elif not progress.total_count:
            self._route_mode = "pending"
        self._icon.setProperty("routeMode", self._route_mode)
        self._icon.setPixmap(
            brand.icon_pixmap(self._route_mode, 22, device_pixel_ratio=self.devicePixelRatioF())
        )
        line = notice or (progress.active_label if outcome == RUNNING else "") or OUTCOME_LABELS[outcome]
        self._title.setAccessibleName(line)
        self._title.setToolTip(notice)
        self._icon.setVisible(not notice)
        icon_width = 0 if notice else 26
        line = self._title.fontMetrics().elidedText(line, Qt.ElideLeft if notice else Qt.ElideRight, 108 - icon_width)
        label_width = self._title.fontMetrics().horizontalAdvance(line)
        x = (STRIP_WIDTH - icon_width - label_width) // 2
        self._icon.move(x, 76)
        self._title.setGeometry(x + icon_width, 76, label_width + 2, 22)
        self._title.setText(line)
        count, total = progress.processed_count, progress.total_count
        percent = round(count * 100 / total) if total else 0
        self._percent.setText(f"{percent}%")
        self._bar.setValue(percent)
        self._bubble.stop_button.setEnabled(outcome == RUNNING)
        self.update()

    def set_log_lines(self, lines: Iterable[str]) -> None:
        self._log_bubble.set_lines(lines)

    def _show_actions(self) -> None:
        if self._press is None and self.isVisible():
            self._close_timer.stop()
            plaque = self.frameGeometry()
            screen = QApplication.screenAt(plaque.center()) or self.screen()
            area = screen.availableGeometry()
            opened = self._bubble.open_at(plaque, area)
            overhang = self._overhang.frameGeometry() if self._overhang.isVisible() else QRect()
            self._log_bubble.open_at(plaque, overhang, self._bubble.frameGeometry(), area)
            if opened and brand.motion_enabled():
                self._hover_motion.start()

    def _dismiss_when_clear(self) -> None:
        if not self._bubble.isVisible():
            return
        pointer = QCursor.pos()
        # The expanded edges cover the gaps between the plaque and the tails.
        if any(
            widget.isVisible() and widget.frameGeometry().adjusted(-8, -8, 8, 8).contains(pointer)
            for widget in (self, self._bubble, self._log_bubble, self._overhang)
        ):
            self._close_timer.start()
        else:
            self._dismiss_bubbles()

    def _dismiss_bubbles(self, *, immediate: bool = False) -> None:
        self._bubble.dismiss(immediate=immediate)
        self._log_bubble.dismiss(immediate=immediate)

    def _animate_mascot(self, value: float) -> None:
        step = min(5, int(value * 550 / 68))
        top = _ART_TOP + (0, -3, -_ART_LIFT, -2, 1, 0)[step]
        self._mascot.move(_ART_X, top)
        self._overhang.set_sprite_top(top)
        self.update()

    def _place_overhang(self) -> None:
        bounds = self.frameGeometry()
        screen = QApplication.screenAt(bounds.center()) or self.screen()
        height = min(-_ART_TOP + _ART_LIFT, bounds.top() - screen.availableGeometry().top())
        if height <= 0:
            self._overhang.hide()
            return
        self._overhang.setGeometry(bounds.x() + _ART_X, bounds.y() - height, _ART_SIZE, height)
        self._overhang.show()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._plaque.render(painter, QRectF(0, 32, self.width(), 99))
        if self._outcome == RUNNING and self._hover_motion.state() == QVariantAnimation.Running:
            phase = self._hover_motion.currentTime() / self._hover_motion.duration()
            painter.setOpacity(min(phase / .35, 1, (1 - phase) / .25))
            x = 11 if self._bubble._left else self.width() - 23
            self._spark.render(painter, QRectF(x, 5 - phase * 3, 12, 12))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._show_actions()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._bubble.isVisible():
            self._close_timer.start()
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._place_overhang()
        super().showEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        if self.isVisible():
            self._place_overhang()
        super().moveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._dismiss_bubbles(immediate=True)
        self._overhang.hide()
        self._close_timer.stop()
        self._hover_motion.stop()
        self._animate_mascot(1.0)
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._press = event.globalPosition().toPoint()
        self._offset = self._press - self.pos()
        self._dragged = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            self._show_actions()
            super().mouseMoveEvent(event)
            return
        point = event.globalPosition().toPoint()
        if not self._dragged and (point - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._dragged = True
            self._dismiss_bubbles(immediate=True)
            self._close_timer.stop()
            self._hover_motion.stop()
            self._animate_mascot(1.0)
        if self._dragged:
            self.drag_moved.emit(point - self._offset, point)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._press is None:
            super().mouseReleaseEvent(event)
            return
        self._press = None
        if self._dragged:
            self.drag_finished.emit()
        if self.rect().contains(event.position().toPoint()):
            self._show_actions()
        event.accept()


class FloatingRunner(QObject):
    """Own the shared run presentation and companion placement."""

    presentation_changed = Signal()
    stop_clicked = Signal()
    open_main_requested = Signal()
    position_changed = Signal(object)

    def __init__(
        self,
        position: tuple[int, int] | None = None,
        *,
        animation: ArkyAnimation | None = None,
    ) -> None:
        super().__init__()
        self.animation = animation if animation is not None else ArkyAnimation(self)
        self.panel = RunPanel(self.animation)
        self.panel.open_main_requested.connect(self.open_main_requested.emit)
        self.panel.stop_clicked.connect(self.stop_clicked.emit)
        self.panel.drag_moved.connect(self._move_on_drag)
        self.panel.drag_finished.connect(self._remember_position)
        self._position = position
        self._progress = RunProgress(())
        self._log_lines: deque[str] = deque(maxlen=_LOG_ROWS)
        self._outcome = IDLE
        self._notice = ""
        self._refresh()

    @property
    def progress(self) -> RunProgress:
        return self._progress

    @property
    def outcome(self) -> str:
        return self._outcome

    @property
    def status_text(self) -> str:
        if self._notice:
            return self._notice
        if self.outcome == RUNNING:
            if self.progress.active_label:
                return f"执行中 · {self.progress.active_label}"
            return "正在确认运行结果"
        return OUTCOME_LABELS[self.outcome]

    def start_run(self, routes: Sequence[tuple[str, str]]) -> None:
        self._progress = RunProgress(routes)
        self._log_lines.clear()
        self.panel.set_log_lines(self._log_lines)
        self._notice = ""
        self.animation.set_state(IDLE)
        self._outcome = RUNNING if routes else IDLE
        self._refresh()

    def note_line(self, line: str) -> None:
        self._progress.note_line(line)
        self._refresh()

    def append_log(self, line: str) -> None:
        for received in line.splitlines():
            received = received.strip()
            if not received:
                continue
            timestamped = _LOG_TIMESTAMP.match(received)
            if timestamped:
                stamp, message = timestamped.groups()
            else:
                stamp, message = QTime.currentTime().toString("HH:mm:ss"), received
            self._log_lines.append(f"{stamp}  {message}")
        self.panel.set_log_lines(self._log_lines)

    def finish(self, exit_code: int | None = 0) -> None:
        stopped = self.outcome in {STOPPING, STOPPED} or exit_code == 130
        self._progress.finish(complete_current=not stopped and exit_code == 0)
        self._outcome = STOPPED if stopped else self._progress.outcome(exit_code)
        self._refresh()

    def stop_requested(self) -> None:
        if self.outcome == RUNNING:
            self._outcome = STOPPING
            self._refresh()

    def set_status_notice(self, text: str) -> None:
        self._notice = text
        self._refresh()

    def show_strip(self) -> None:
        position = QPoint(*self._position) if self._position is not None else None
        screen = None
        if position is not None:
            center = position + QPoint(STRIP_WIDTH // 2, STRIP_HEIGHT // 2)
            screen = QApplication.screenAt(center) or QApplication.screenAt(position)
        self._place(position, screen or QApplication.primaryScreen())
        if self._position is not None and self.panel.pos().toTuple() != self._position:
            self._remember_position()
        self.panel.show()

    def hide_all(self) -> None:
        self.panel.hide()

    def _refresh(self) -> None:
        animation_state = {
            RUNNING: RUNNING,
            SUCCESS: SUCCESS,
            FAILURE: FAILURE,
            STOPPING: STOPPED,
            STOPPED: STOPPED,
        }.get(self.outcome, IDLE)
        self.animation.set_state(animation_state)
        self.panel.set_presentation(self.progress, self.outcome, self._notice)
        self.presentation_changed.emit()

    def _move_on_drag(self, position: QPoint, pointer: QPoint) -> None:
        screen = QApplication.screenAt(pointer) or self.panel.screen()
        self._place(position, screen)

    def _place(self, position: QPoint | None, screen: QScreen | None) -> None:
        if screen is None:
            return
        area = screen.availableGeometry()
        max_x = max(area.left(), area.right() - self.panel.width() + 1)
        max_y = max(area.top(), area.bottom() - self.panel.height() + 1)
        if position is None:
            position = QPoint(max_x - _RIGHT_GAP, max_y - _BOTTOM_GAP)
        x = max(area.left(), min(position.x(), max_x))
        y = max(area.top(), min(position.y(), max_y))
        self.panel.move(x, y)

    def _remember_position(self) -> None:
        self._position = self.panel.pos().toTuple()
        self.position_changed.emit(self._position)
