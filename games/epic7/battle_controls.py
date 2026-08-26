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
_PC_AUTO_CONTROL_CENTERS = (1553, 1674, 1795, 1918)
_MANUAL_CONTROL_CENTERS = (1534, 1683, 1834)
_PC_MANUAL_CONTROL_CENTERS = (1599, 1737, 1885)


def _reference_frame(screen: np.ndarray) -> np.ndarray:
    if screen.shape[:2] == (_REFERENCE_SIZE[1], _REFERENCE_SIZE[0]):
        return screen
    return cv2.resize(screen, _REFERENCE_SIZE, interpolation=cv2.INTER_AREA)


def observe_battle_controls(screen: np.ndarray) -> BattleControls:
    """Classify stable lower-right battle controls, ignoring scene artwork."""
    frame = _reference_frame(screen)

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
    battle_canvas = cv2.cvtColor(frame[150:900, 100:1400], cv2.COLOR_RGB2GRAY)
    pc_skill_animation = (
        float(np.mean(battle_canvas < 30)) >= 0.90
        or float(np.mean(battle_canvas > 220)) >= 0.20
    )

    def has_auto_layout(expected_xs: tuple[int, ...], expected_y: int) -> bool:
        auto_bases = []
        for center_x in expected_xs:
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
        return sum(auto_bases) >= 3 and aligned_count(
            expected_xs, expected_y, (40, 60), 30
        ) >= 2

    # 底座颜色命中 >=3 槽即已排除手动布局（手动 3 钮最多擦到 2 个槽位）；
    # 对齐圆放宽到 >=2：红底灵魂技/暗冷却槽上的图标会让霍夫圆漏检。
    if has_auto_layout(_AUTO_CONTROL_CENTERS, 1047) or (
        not pc_skill_animation
        and has_auto_layout(_PC_AUTO_CONTROL_CENTERS, 1021)
    ):
        return BattleControls.AUTO_CONTROLS

    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]

    def manual_borders(expected_xs: tuple[int, ...]) -> list[bool]:
        borders = []
        for center_x in expected_xs:
            distance_squared = (xx - center_x) ** 2 + (yy - 1040) ** 2
            border = (distance_squared >= 55 ** 2) & (distance_squared <= 75 ** 2)
            borders.append(float(np.mean(hsv[:, :, 2][border] > 120)) >= 0.35)
        return borders

    emulator_manual_borders = manual_borders(_MANUAL_CONTROL_CENTERS)
    manual_circle_count = aligned_count(
        _MANUAL_CONTROL_CENTERS, 1040, (55, 82), 38
    )
    legacy_canvas = not frame[:52].any() and not frame[:, 1920:].any()
    if manual_circle_count == len(_MANUAL_CONTROL_CENTERS) and (
        all(emulator_manual_borders) or legacy_canvas
    ):
        return BattleControls.MANUAL_CONTROLS
    pc_manual_circle_count = aligned_count(
        _PC_MANUAL_CONTROL_CENTERS, 1040, (55, 82), 38
    )
    if pc_manual_circle_count == len(_PC_MANUAL_CONTROL_CENTERS) and all(
        manual_borders(_PC_MANUAL_CONTROL_CENTERS)
    ):
        return BattleControls.MANUAL_CONTROLS
    return BattleControls.TRANSITION


def battle_scene_visible(screen: np.ndarray) -> bool:
    """Keep battle presence separate from whether skill controls are operable."""
    frame = _reference_frame(screen)
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    controls = observe_battle_controls(screen)

    if controls is BattleControls.MANUAL_CONTROLS:
        return True

    def white_ratio(region: tuple[int, int, int, int]) -> float:
        x1, y1, x2, y2 = region
        roi = hsv[y1:y2, x1:x2]
        white = (roi[:, :, 1] <= 60) & (roi[:, :, 2] >= 160)
        return float(np.mean(white))

    turn_order = white_ratio((0, 120, 140, 900))
    if turn_order < 0.12:
        return False
    if controls is BattleControls.AUTO_CONTROLS:
        return True

    # 技能演出会暂时盖住底部技能槽，但右上战斗控制区和左侧行动顺序
    # 仍保留高亮结构。上限排除纯白加载帧和整块白色非战斗面板。
    pause_controls = white_ratio((1780, 45, 1920, 165))
    return 0.08 <= pause_controls <= 0.85 and turn_order >= 0.12
