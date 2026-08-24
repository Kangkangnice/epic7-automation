"""Pure visual evidence helpers for simulator hero synthesis."""

from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np


class MotionPhase(Enum):
    WAITING_DEPARTURE = "waiting_departure"
    MOVING = "moving"
    SETTLING = "settling"
    SETTLED = "settled"


class SafetyClass(Enum):
    SSS = "sss"
    NON_SSS = "non_sss"
    UNKNOWN = "unknown"


@dataclass
class CardSwitchMotionObserver:
    first_screen: np.ndarray
    min_vertical_shift: float = 1.5
    min_phase_response: float = 0.08
    min_accumulated_shift: float = 8.0
    settle_difference: float = 2.5
    required_settle_frames: int = 3

    _LIST_ZONE = (1450, 200, 532, 780)
    _REFERENCE_SIZE = (1982, 1132)

    def __post_init__(self) -> None:
        self.phase = MotionPhase.WAITING_DEPARTURE
        self.accumulated_shift = 0.0
        self.settle_frames = 0
        self.previous = self._gray(self.first_screen)

    def _gray(self, screen: np.ndarray) -> np.ndarray:
        x, y, w, h = self._LIST_ZONE
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, w, h = (
            round(x * scale_x),
            round(y * scale_y),
            round(w * scale_x),
            round(h * scale_y),
        )
        crop = screen[y : y + h, x : x + w]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def update(self, screen: np.ndarray) -> bool:
        current = self._gray(screen)
        (dx, dy), response = cv2.phaseCorrelate(
            self.previous.astype(np.float32), current.astype(np.float32)
        )
        difference = float(cv2.absdiff(self.previous, current).mean())
        vertical = (
            response >= self.min_phase_response
            and abs(dy) >= self.min_vertical_shift
            and abs(dy) > abs(dx) * 1.5
        )

        if vertical:
            self.phase = MotionPhase.MOVING
            self.accumulated_shift += abs(dy)
            self.settle_frames = 0
        elif self.phase in (MotionPhase.MOVING, MotionPhase.SETTLING):
            self.phase = MotionPhase.SETTLING
            self.settle_frames = (
                self.settle_frames + 1
                if difference <= self.settle_difference
                else 0
            )
            if (
                self.accumulated_shift >= self.min_accumulated_shift
                and self.settle_frames >= self.required_settle_frames
            ):
                self.phase = MotionPhase.SETTLED
                self.previous = current
                return True

        self.previous = current
        return False
