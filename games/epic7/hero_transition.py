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


@dataclass(frozen=True)
class MotionSample:
    frame: int
    phase_before: MotionPhase
    phase_after: MotionPhase
    dx: float
    dy: float
    response: float
    difference: float
    baseline_difference: float
    accumulated_shift: float
    settle_frames: int
    vertical: bool
    departed: bool


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
        self.samples: list[MotionSample] = []
        self.departure_screen: np.ndarray | None = None
        self.peak_screen: np.ndarray | None = None
        self.last_screen: np.ndarray | None = None
        self._peak_score = -1.0

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
        phase_before = self.phase
        (dx, dy), response = cv2.phaseCorrelate(
            self.previous.astype(np.float32), current.astype(np.float32)
        )
        difference = float(cv2.absdiff(self.previous, current).mean())
        baseline_difference = float(cv2.absdiff(self.baseline, current).mean())
        vertical = (
            response >= self.min_phase_response
            and abs(dy) >= self.min_vertical_shift
            and abs(dy) > abs(dx) * 1.5
        )

        departed = vertical or difference >= self.departure_difference
        if self.phase is MotionPhase.WAITING_DEPARTURE and departed:
            self.phase = MotionPhase.MOVING
            self.departure_screen = screen.copy()
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

        score = max(
            abs(dy) / self.min_vertical_shift,
            difference / self.departure_difference,
        )
        if score > self._peak_score:
            self._peak_score = score
            self.peak_screen = screen.copy()
        self.last_screen = screen.copy()
        self.samples.append(
            MotionSample(
                frame=len(self.samples) + 1,
                phase_before=phase_before,
                phase_after=self.phase,
                dx=float(dx),
                dy=float(dy),
                response=float(response),
                difference=difference,
                baseline_difference=baseline_difference,
                accumulated_shift=self.accumulated_shift,
                settle_frames=self.settle_frames,
                vertical=vertical,
                departed=departed,
            )
        )

        self.previous = current
        return self.phase is MotionPhase.SETTLED
