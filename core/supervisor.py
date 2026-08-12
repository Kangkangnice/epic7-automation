"""Small observation helpers shared by live game runners."""

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Optional

import numpy as np


@dataclass
class StableObservation:
    """Accept a page/action only after it is seen in consecutive frames."""

    required: int = 2
    _value: Optional[str] = field(default=None, init=False)
    _count: int = field(default=0, init=False)

    def update(self, value: str) -> bool:
        if value != self._value:
            self._value = value
            self._count = 1
            return self.required <= 1
        self._count += 1
        return self._count >= self.required

    def reset(self) -> None:
        self._value = None
        self._count = 0


@dataclass
class Watchdog:
    """Track both a no-progress timeout and an absolute operation deadline."""

    no_progress_seconds: float
    absolute_seconds: float
    now: Callable[[], float] = monotonic
    _started: float = field(init=False)
    _progressed: float = field(init=False)

    def __post_init__(self) -> None:
        self._started = self._progressed = self.now()

    def progress(self) -> None:
        self._progressed = self.now()

    def expired_reason(self) -> Optional[str]:
        current = self.now()
        if current - self._started >= self.absolute_seconds:
            return "absolute"
        if current - self._progressed >= self.no_progress_seconds:
            return "no_progress"
        return None


def meaningful_change(before: Optional[np.ndarray], after: np.ndarray) -> bool:
    """Detect useful animation/loading progress while ignoring the static HUD."""

    if before is None or before.shape != after.shape:
        return False
    height, width = after.shape[:2]
    y1, y2 = round(height * 0.16), round(height * 0.78)
    x1, x2 = round(width * 0.06), round(width * 0.94)
    previous = before[y1:y2, x1:x2]
    current = after[y1:y2, x1:x2]
    difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
    return float(np.mean(difference)) >= 2.0
