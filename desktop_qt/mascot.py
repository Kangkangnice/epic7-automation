"""Approved Arky sprites with one animation clock for the Qt run views."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from auto_game_unified.desktop_qt import brand

_MANIFEST = json.loads((brand.MASCOT_ART / "animation.json").read_text(encoding="utf-8"))
_ANIMATIONS = _MANIFEST["states"]
_PHASE_TO_STATE = {"launch": "running", "handoff": "running", "complete": "success"}


class ArkyAnimation(QObject):
    """Own the frame index and timer so every attached view displays the same sprite."""

    frame_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._frame_index = 0
        self._timer = QTimer(self, singleShot=True, timerType=Qt.PreciseTimer)
        self._timer.timeout.connect(self._advance)

    @property
    def state(self) -> str:
        return self._state

    @property
    def frame_index(self) -> int:
        return self._frame_index

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        if state not in _ANIMATIONS and state not in ("idle", "stopped"):
            raise ValueError(f"Unknown Arky animation state: {state}")

        self.stop()
        self._state = state
        self._frame_index = 0
        animation = _ANIMATIONS.get(state)
        if animation is not None:
            if brand.motion_enabled():
                self._timer.start(animation["duration_ms"][0])
            else:
                self._frame_index = animation.get("hold_frame", 0)
        self.frame_changed.emit()

    def pixmap(self) -> QPixmap:
        animation = _ANIMATIONS.get(self.state)
        path = animation["frames"][self.frame_index] if animation else _MANIFEST[self.state]
        return brand.artwork(brand.MASCOT_ART / path)

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        animation = _ANIMATIONS[self.state]
        next_index = self.frame_index + 1
        frame_count = len(animation["frames"])
        if not brand.motion_enabled() or (next_index == frame_count and not animation["loop"]):
            self._frame_index = animation.get("hold_frame", 0)
        else:
            self._frame_index = next_index % frame_count
            self._timer.start(animation["duration_ms"][self.frame_index])
        self.frame_changed.emit()


class ArkyMascot(QWidget):
    """Paint the current transparent frame over the parent's artwork."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        height: int = 124,
        animation: ArkyAnimation | None = None,
        pose: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("arkyMascot")
        self.setAccessibleName("亚卡")
        self.setFixedHeight(height)
        self._pose = brand.MASCOT_ART / f"{pose}.png" if pose else None
        self.animation = animation if animation is not None else ArkyAnimation(self)
        self.animation.frame_changed.connect(self.update)
        self._phase = "idle"

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def animation_running(self) -> bool:
        return self.isVisible() and self.animation.is_animating

    def set_phase(self, phase: str) -> None:
        """Support phase names used by the earlier desktop views."""
        self.animation.set_state(_PHASE_TO_STATE.get(phase, phase))
        self._phase = phase

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pose is not None and self.animation.state in ("idle", "stopped"):
            art = brand.artwork(self._pose)
        else:
            art = self.animation.pixmap()
        size = min(self.width(), self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        target = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        painter.drawPixmap(target, art, QRectF(art.rect()))
