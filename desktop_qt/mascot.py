"""Paint the Arky illustration at the current screen's device pixel ratio."""

from __future__ import annotations

from math import pi, sin

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from auto_game_unified.desktop_qt import brand

_GESTURE_MS = {"launch": 650, "handoff": 480, "complete": 800}


def _star(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
    points = (
        (0, -1), (.22, -.22), (1, 0), (.22, .22),
        (0, 1), (-.22, .22), (-1, 0), (-.22, -.22),
    )
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([
        center + QPointF(x * radius, y * radius) for x, y in points
    ]))


class ArkyMascot(QWidget):
    """A small cloud stage driven by real run events."""

    def __init__(self, parent: QWidget | None = None, *, height: int = 124) -> None:
        super().__init__(parent)
        self.setObjectName("arkyMascot")
        self.setAccessibleName("亚卡")
        self.setFixedHeight(height)
        self.phase = "idle"
        self._direction = 1
        self._clock = QElapsedTimer()
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._advance)
        self._art = brand.artwork(brand.HERO_ART)
        self._scaled_art = self._art
        self._art_pixels = 0

    @property
    def animation_running(self) -> bool:
        return self._timer.isActive()

    def set_phase(self, phase: str) -> None:
        if phase == "launch":
            self._direction = 1
        elif phase == "handoff":
            self._direction *= -1
        # Keep the raw illustration across frames and resample only when its size or art changes.
        if (phase == "complete") != (self.phase == "complete"):
            self._art = brand.artwork(brand.COMPLETE_ART if phase == "complete" else brand.HERO_ART)
            self._art_pixels = 0
        self.phase = phase
        self._clock.start()
        self._sync_timer()
        self.update()

    def _advance(self) -> None:
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        active = self.phase in ("launch", "handoff")
        animating = self._clock.isValid() and self._clock.elapsed() < _GESTURE_MS.get(self.phase, 0)
        if self.isVisible() and brand.motion_enabled() and (active or animating):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        bounds = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        background = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        background.setColorAt(0, QColor("#F5FCFF"))
        background.setColorAt(1, QColor("#CAE9FA"))
        shape = QPainterPath()
        shape.addRoundedRect(bounds, 14, 14)
        painter.fillPath(shape, background)
        painter.strokePath(shape, QPen(QColor("#BFDFEF"), 1))
        painter.setClipPath(shape)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 158))
        for x, y, width, height in ((-.22, .76, .53, .46), (.71, .79, .53, .4)):
            painter.drawEllipse(QRectF(
                self.width() * x, self.height() * y,
                self.width() * width, self.height() * height,
            ))

        elapsed = self._clock.elapsed() if self.animation_running else 0
        duration = _GESTURE_MS.get(self.phase, 0)
        progress = min(elapsed / duration, 1) if duration and elapsed else 0
        jump = sin(pi * progress)
        center = bounds.center()
        x = 13 * self._direction * jump if self.phase == "handoff" else 0
        y = 3.0 if self.phase == "stopped" else 0.0
        if elapsed and self.phase in _GESTURE_MS:
            lift = 9 if self.phase == "handoff" else self.height() * .12
            y -= lift * jump
            if self.phase in ("launch", "handoff") and elapsed >= duration:
                y -= 2.5 * sin(2 * pi * (elapsed - duration) / 2800)
        size = min(self.width() * .48, self.height() * .77)
        painter.setBrush(QColor(66, 128, 165, int(43 - 19 * jump)))
        painter.drawEllipse(QRectF(center.x() - size * .22 + x, self.height() * .84, size * .44, 6))

        if self.phase == "complete" and progress:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(78, 146, 187, int(120 * (1 - progress))), 1.4))
            ripple_radius = 23 + 28 * progress
            painter.drawEllipse(QRectF(
                center.x() - ripple_radius, self.height() * .73, 2 * ripple_radius, 18,
            ))
            painter.setPen(Qt.NoPen)
        for side, height, radius in ((-1, -.16, 5), (1, .04, 3)):
            color = QColor("#DAA646" if self.phase == "complete" else "#5599C0")
            color.setAlpha(int(125 + 125 * jump))
            _star(painter, center + QPointF(side * size * (.65 + .12 * jump),
                                            size * height - 11 * jump), radius + 2 * jump, color)

        pixels = max(1, round(size * self.devicePixelRatioF()))
        if self._art_pixels != pixels:
            self._scaled_art = self._art.scaled(
                pixels, pixels, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self._art_pixels = pixels
        art = self._scaled_art
        painter.save()
        painter.translate(center + QPointF(x, y))
        painter.rotate(7 * self._direction * jump if self.phase == "handoff" else -5 * jump)
        painter.drawPixmap(QRectF(-size / 2, -size / 2, size, size), art, QRectF(art.rect()))
        painter.restore()
