from enum import Enum

import cv2
import numpy as np


class BattleControls(Enum):
    AUTO_CONTROLS = "auto_controls"
    MANUAL_CONTROLS = "manual_controls"
    TRANSITION = "transition"


_REFERENCE_SIZE = (1982, 1132)
_CONTROL_ROI = (1400, 940, 520, 192)
_AUTO_CONTROL_CENTERS = (1505, 1623, 1740, 1858)
_MANUAL_CONTROL_CENTERS = (1534, 1683, 1834)


def observe_battle_controls(screen: np.ndarray) -> BattleControls:
    """Classify stable lower-right battle controls, ignoring scene artwork."""
    if screen.shape[:2] != (_REFERENCE_SIZE[1], _REFERENCE_SIZE[0]):
        frame = cv2.resize(screen, _REFERENCE_SIZE, interpolation=cv2.INTER_AREA)
    else:
        frame = screen

    roi_x, roi_y, roi_width, roi_height = _CONTROL_ROI
    roi = frame[roi_y : roi_y + roi_height, roi_x : roi_x + roi_width]
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 1)
    detected = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=80,
        param1=120,
        param2=40,
        minRadius=40,
        maxRadius=82,
    )
    circles: list[tuple[int, int, int]] = []
    if detected is not None:
        circles = [
            (int(round(x)) + roi_x, int(round(y)) + roi_y, int(round(radius)))
            for x, y, radius in detected[0]
        ]
    if len(circles) > 8:
        return BattleControls.TRANSITION

    def aligned_count(
        expected_xs: tuple[int, ...],
        expected_y: int,
        radius_range: tuple[int, int],
        tolerance: int,
    ) -> int:
        return sum(
            1
            for expected_x in expected_xs
            if any(
                abs(x - expected_x) <= tolerance
                and abs(y - expected_y) <= tolerance
                and radius_range[0] <= radius <= radius_range[1]
                for x, y, radius in circles
            )
        )

    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    auto_bases = []
    for center_x in _AUTO_CONTROL_CENTERS:
        slot = hsv[1060:1132, center_x - 50 : center_x + 50]
        blue = (
            (slot[:, :, 0] >= 85)
            & (slot[:, :, 0] <= 135)
            & (slot[:, :, 1] >= 100)
            & (slot[:, :, 2] >= 70)
        )
        red = (
            ((slot[:, :, 0] <= 10) | (slot[:, :, 0] >= 170))
            & (slot[:, :, 1] >= 100)
            & (slot[:, :, 2] >= 45)
        )
        auto_bases.append(
            float(np.mean(blue)) >= 0.40 or float(np.mean(red)) >= 0.25
        )

    if all(auto_bases) and aligned_count(
        _AUTO_CONTROL_CENTERS, 1047, (40, 60), 30
    ) >= 3:
        return BattleControls.AUTO_CONTROLS

    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
    manual_borders = []
    for center_x in _MANUAL_CONTROL_CENTERS:
        distance_squared = (xx - center_x) ** 2 + (yy - 1040) ** 2
        border = (distance_squared >= 55 ** 2) & (distance_squared <= 75 ** 2)
        manual_borders.append(float(np.mean(hsv[:, :, 2][border] > 120)) >= 0.35)
    if all(manual_borders) and aligned_count(
        _MANUAL_CONTROL_CENTERS, 1040, (55, 82), 38
    ) == len(_MANUAL_CONTROL_CENTERS):
        return BattleControls.MANUAL_CONTROLS
    return BattleControls.TRANSITION
