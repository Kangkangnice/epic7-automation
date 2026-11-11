"""开始任务后收成右上角悬浮球；点开是半屏高的窄条便签。

三段内容：三条今日目标（可改、自动存）· 本次运行进度（条数多时分两列）· 最近三行日志。

⚠️ 这里只做展示，不改任何判据、阈值、业务规则。窗口定位走 Qt 的逻辑坐标
（点击坐标才是 Win32 物理像素，两者别混）；两个窗口都不主动抢前台，
避免和正在跑的自动化抢焦点。
"""

from __future__ import annotations

from math import sin, pi
from typing import Sequence

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from auto_game_unified.desktop.run_progress import (
    DONE,
    PENDING,
    RUNNING,
    STATUS_LABELS,
    RunProgress,
    RouteProgress,
)

BALL_SIZE = 56
PANEL_MIN_WIDTH = 280
PANEL_MAX_WIDTH = 340
PANEL_MAX_HEIGHT = 540
PANEL_HEIGHT_RATIO = 0.5
EDGE_GAP = 12
PULSE_TICK_MS = 50
PULSE_PERIOD_MS = 2000
AUTO_COLLAPSE_MS = 15_000
AFTER_EDIT_COLLAPSE_MS = 2000
PROGRESS_COLUMN_THRESHOLD = 6
LOG_LINES = 3

BLUE = "#0078D7"
MUTED = "#5F6B7A"
TEXT = "#1A1A1A"

_PANEL_QSS = f"""
QWidget#runPanel {{
    background-color: #FFFFFF;
    border: 1px solid #C9D2DC;
    border-radius: 12px;
}}
QLabel {{ color: {TEXT}; font-size: 13px; }}
QLabel#panelTitle {{ font-size: 14px; font-weight: 500; }}
QLabel#statePill {{
    color: #FFFFFF; background-color: {BLUE};
    border-radius: 10px; padding: 2px 10px; font-size: 12px;
}}
QLabel#statePillIdle {{ color: #FFFFFF; background-color: {MUTED};
    border-radius: 10px; padding: 2px 10px; font-size: 12px; }}
QLabel#divider {{ background-color: #E3E8EE; max-height: 1px; border: none; }}
QLabel#slotNumber {{ color: {MUTED}; }}
QLabel#legendText {{ color: {MUTED}; font-size: 12px; }}
QLabel#logLine {{ color: {MUTED}; font-size: 12px; }}
QLabel#statusDone {{ color: {BLUE}; }}
QLabel#statusRunning {{ color: {BLUE}; }}
QLabel#statusPending {{ color: #8A8A8A; }}
QLabel#dotDone {{ background-color: {BLUE}; color: #FFFFFF; font-size: 11px; border-radius: 7px; }}
QLabel#dotRunning {{ background-color: #B5D4F4; border: 1px solid {BLUE}; border-radius: 6px; }}
QLabel#dotPending {{ background-color: #FFFFFF; border: 1px solid #B4B2A9; border-radius: 6px; }}
QLineEdit {{
    color: {TEXT}; background-color: #F7F9FB; border: 1px solid #D8DEE6;
    border-radius: 6px; padding: 4px 8px; font-size: 13px;
}}
QLineEdit:focus {{ border: 2px solid {BLUE}; }}
QPushButton {{
    color: {TEXT}; background-color: #F3F6F9; border: 1px solid #D8DEE6;
    border-radius: 6px; padding: 4px 10px; font-size: 12px;
}}
QPushButton:hover {{ background-color: #E8EFF6; }}
QScrollArea {{ border: none; background: transparent; }}
"""


def _window_flags() -> Qt.WindowFlags:
    return Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


class FloatingBall(QWidget):
    """右上角一颗球：运行中慢呼吸 + 一圈淡蓝脉冲，跑完立刻静止。"""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("floatingBall")
        self.setFixedSize(BALL_SIZE, BALL_SIZE)
        self.setWindowFlags(_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._running = False
        self._caption = "已结束"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_running(self, running: bool) -> None:
        self._running = running
        self._caption = "进行中" if running else "已结束"
        if running:
            self._phase = 0.0
            self._timer.start(PULSE_TICK_MS)
        else:
            self._timer.stop()
        self.update()

    def hide_all(self) -> None:
        self._timer.stop()
        self._running = False
        self.hide()

    def _tick(self) -> None:
        self._phase = (self._phase + PULSE_TICK_MS / PULSE_PERIOD_MS) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 —— Qt 回调名
        center = QPointF(BALL_SIZE / 2, BALL_SIZE / 2)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._running:
            ring = (BALL_SIZE / 2 - 3) * (1 + 0.45 * self._phase)
            painter.setPen(QPen(QColor(0, 120, 215, int(130 * (1 - self._phase))), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, ring, ring)
            breath = 1 + 0.04 * sin(2 * pi * self._phase)
        else:
            breath = 1.0
        radius = (BALL_SIZE / 2 - 6) * breath
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(BLUE if self._running else MUTED))
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(self.rect(), Qt.AlignCenter, self._caption)

    def mousePressEvent(self, event) -> None:  # noqa: N802 —— Qt 回调名
        self.clicked.emit()


class RunPanel(QWidget):
    """半屏高的窄条：三条便签 + 两列进度 + 三行日志。"""

    todos_changed = Signal(object)
    collapse_requested = Signal()
    open_main_requested = Signal()

    def __init__(self, todos: Sequence[str]) -> None:
        super().__init__()
        self.setObjectName("runPanel")
        self.setWindowFlags(_window_flags())
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowOpacity(0.92)
        self.setStyleSheet(_PANEL_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("今日游戏便签", self)
        title.setObjectName("panelTitle")
        self._state = QLabel("任务进行中", self)
        self._state.setObjectName("statePill")
        collapse = QPushButton("收起", self)
        collapse.clicked.connect(self.collapse_requested.emit)
        main_window = QPushButton("主界面", self)
        main_window.clicked.connect(self.open_main_requested.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._state)
        header.addWidget(collapse)
        header.addWidget(main_window)
        layout.addLayout(header)

        self._todos: list[QLineEdit] = []
        for index in range(3):
            row = QHBoxLayout()
            number = QLabel(str(index + 1), self)
            number.setObjectName("slotNumber")
            number.setFixedWidth(14)
            editor = QLineEdit(self)
            editor.setPlaceholderText("点这里写今天想做的事")
            editor.setText(todos[index] if index < len(todos) else "")
            editor.editingFinished.connect(self._on_todo_edited)
            row.addWidget(number)
            row.addWidget(editor, 1)
            layout.addLayout(row)
            self._todos.append(editor)

        layout.addWidget(_divider(self))
        layout.addLayout(_legend(self))
        layout.addWidget(_divider(self))

        progress_title = QLabel("本次运行", self)
        progress_title.setObjectName("panelTitle")
        layout.addWidget(progress_title)
        self._items: tuple[RouteProgress, ...] = ()
        self._progress_host = QWidget(self)
        self._progress_grid = QGridLayout(self._progress_host)
        self._progress_grid.setContentsMargins(0, 0, 0, 0)
        self._progress_grid.setSpacing(4)
        scroller = QScrollArea(self)
        scroller.setWidgetResizable(True)
        scroller.setWidget(self._progress_host)
        layout.addWidget(scroller, 1)

        layout.addWidget(_divider(self))
        self._log_labels: list[QLabel] = []
        for _ in range(LOG_LINES):
            line = QLabel("", self)
            line.setObjectName("logLine")
            layout.addWidget(line)
            self._log_labels.append(line)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self.collapse_requested.emit)

    def set_running(self, running: bool) -> None:
        self._state.setText("任务进行中" if running else "本次运行已结束")
        self._state.setObjectName("statePill" if running else "statePillIdle")
        self.setStyleSheet(_PANEL_QSS)

    def set_progress(self, items: Sequence[RouteProgress]) -> None:
        self._items = tuple(items)
        self._rebuild_progress()

    def _rebuild_progress(self) -> None:
        while self._progress_grid.count():
            child = self._progress_grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        count = len(self._items)
        columns = 2 if count > PROGRESS_COLUMN_THRESHOLD else 1
        rows = max(1, (count + columns - 1) // columns)
        # 窄条里两列各约 150px：路线名超长要省略，状态字留固定宽，
        # 否则右列那几个「待跑」会被面板边缘裁掉（真机抓图抓到过）。
        column_width = max(100, (max(120, self._progress_host.width()) - 8) // columns)
        name_width = max(48, column_width - 78)
        metrics = QFontMetrics(self.font())
        for index, item in enumerate(self._items):
            row = index % rows
            column = index // rows
            self._progress_grid.addWidget(
                _progress_row(self._progress_host, item, name_width, metrics),
                row,
                column,
            )

    def resizeEvent(self, event) -> None:  # noqa: N802 —— Qt 回调名
        super().resizeEvent(event)
        if self._items:
            self._rebuild_progress()

    def set_log_lines(self, lines: Sequence[str]) -> None:
        recent = list(lines)[-LOG_LINES:]
        recent.extend([""] * (LOG_LINES - len(recent)))
        width = max(80, self.width() - 32)
        metrics = QFontMetrics(self.font())
        for label, line in zip(self._log_labels, recent, strict=True):
            label.setText(metrics.elidedText(line, Qt.ElideRight, width))

    def reset_collapse_timer(self, delay: int = AUTO_COLLAPSE_MS) -> None:
        self._collapse_timer.start(delay)

    def stop_collapse_timer(self) -> None:
        self._collapse_timer.stop()

    def _on_todo_edited(self) -> None:
        self.todos_changed.emit(tuple(editor.text() for editor in self._todos))
        # 改完就收回球，别让展开的面板一直盖在游戏右上角。
        self.reset_collapse_timer(AFTER_EDIT_COLLAPSE_MS)

    def enterEvent(self, event) -> None:  # noqa: N802 —— Qt 回调名
        self.reset_collapse_timer()
        super().enterEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 —— Qt 回调名
        self.stop_collapse_timer()
        super().hideEvent(event)


def _divider(parent: QWidget) -> QLabel:
    line = QLabel("", parent)
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def _legend(parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    for status, caption in ((DONE, "已完成"), (RUNNING, "进行中"), (PENDING, "未开始")):
        dot = QLabel("", parent)
        dot.setObjectName(f"dot{status.title()}")
        dot.setFixedSize(14, 14)
        dot.setAlignment(Qt.AlignCenter)
        if status == DONE:
            dot.setText("✓")
        text = QLabel(caption, parent)
        text.setObjectName("legendText")
        row.addWidget(dot)
        row.addWidget(text)
        row.addSpacing(10)
    row.addStretch(1)
    return row


def _progress_row(
    parent: QWidget,
    item: RouteProgress,
    name_width: int,
    metrics: QFontMetrics,
) -> QWidget:
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    dot = QLabel("", row)
    dot.setObjectName(
        {"done": "dotDone", "running": "dotRunning", "pending": "dotPending"}[item.status]
    )
    dot.setFixedSize(14, 14)
    dot.setAlignment(Qt.AlignCenter)
    if item.status == DONE:
        dot.setText("✓")
    name = QLabel(metrics.elidedText(item.label, Qt.ElideRight, name_width), row)
    state = QLabel(STATUS_LABELS[item.status], row)
    state.setFixedWidth(40)
    state.setObjectName(
        {"done": "statusDone", "running": "statusRunning", "pending": "statusPending"}[
            item.status
        ]
    )
    layout.addWidget(dot)
    layout.addWidget(name, 1)
    layout.addWidget(state)
    return row


class FloatingRunner(QObject):
    """把球、窄条、进度状态机串起来；主窗口的显示/隐藏由调用方决定。"""

    todos_changed = Signal(object)
    open_main_requested = Signal()

    def __init__(self, todos: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._progress = RunProgress(())
        self._log_lines: list[str] = []
        self.ball = FloatingBall()
        self.panel = RunPanel(todos)
        self.ball.clicked.connect(self.expand)
        self.panel.collapse_requested.connect(self.collapse)
        self.panel.open_main_requested.connect(self.open_main_requested.emit)
        self.panel.todos_changed.connect(self.todos_changed.emit)

    def start_run(self, routes: Sequence[tuple[str, str]]) -> None:
        self._progress = RunProgress(routes)
        self._log_lines = []
        self.panel.set_running(True)
        self.panel.set_progress(self._progress.items)
        self.panel.set_log_lines(())
        self._place()
        self.panel.hide()
        self.ball.set_running(True)
        self.ball.show()

    def expand(self) -> None:
        self.ball.hide()
        self._place()
        self.panel.show()
        # 展开后才有真实宽度：按两列的实际列宽重排一次，名字该省略就省略。
        self.panel.set_progress(self._progress.items)
        self.panel.set_log_lines(self._log_lines)
        self.panel.reset_collapse_timer()

    def collapse(self) -> None:
        self.panel.hide()
        self.ball.show()

    def note_line(self, line: str) -> None:
        before = self._progress.items
        self._progress.note_line(line)
        after = self._progress.items
        if after != before:
            self.panel.set_progress(after)
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-LOG_LINES:]
        self.panel.set_log_lines(self._log_lines)

    def finish(self) -> None:
        self._progress.finish()
        self.panel.set_progress(self._progress.items)
        self.panel.set_running(False)
        self.ball.set_running(False)

    def hide_all(self) -> None:
        self.panel.hide()
        self.ball.hide_all()

    def _place(self) -> None:
        """贴屏幕右上角。窗口定位用 Qt 逻辑坐标，Qt 自己处理缩放换算。"""
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None or available.isEmpty():
            return
        width = min(PANEL_MAX_WIDTH, max(PANEL_MIN_WIDTH, int(available.width() / 6)))
        height = min(PANEL_MAX_HEIGHT, int(available.height() * PANEL_HEIGHT_RATIO))
        x = available.right() - width - EDGE_GAP
        y = available.top() + EDGE_GAP
        self.panel.resize(width, height)
        self.panel.move(x, y)
        self.ball.move(x + width - BALL_SIZE, y)
