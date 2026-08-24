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
    departure_difference: float = 6.0
    settle_difference: float = 2.5
    required_settle_frames: int = 3

    _LIST_ZONE = (1450, 200, 532, 780)
    _REFERENCE_SIZE = (1982, 1132)

    def __post_init__(self) -> None:
        self.phase = MotionPhase.WAITING_DEPARTURE
        self.accumulated_shift = 0.0
        self.settle_frames = 0
        self.previous = self._gray(self.first_screen)
        self.baseline = self.previous.copy()
        self.observed_vertical_motion = False
        self.observed_structural_departure = False

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

        departed = vertical or difference >= self.departure_difference
        if self.phase is MotionPhase.WAITING_DEPARTURE and departed:
            self.phase = MotionPhase.MOVING
            self.observed_vertical_motion = vertical
            self.observed_structural_departure = not vertical
            self.accumulated_shift += abs(dy) if vertical else 0.0
            self.settle_frames = 0
        elif vertical:
            self.phase = MotionPhase.MOVING
            self.observed_vertical_motion = True
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
                self.settle_frames >= self.required_settle_frames
                and (
                    (
                        self.observed_vertical_motion
                        and self.accumulated_shift >= self.min_accumulated_shift
                    )
                    or (
                        self.observed_structural_departure
                        and float(cv2.absdiff(self.baseline, current).mean())
                        >= self.departure_difference
                    )
                )
            ):
                self.phase = MotionPhase.SETTLED
                self.previous = current
                return True

        self.previous = current
        return False
