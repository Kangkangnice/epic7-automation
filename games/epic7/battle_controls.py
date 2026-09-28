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

# ⚠️ 这里**只有一套布局**：模拟器与 PC 客户端通用。
#
# 曾经存在过一套「PC 专用坐标」（自动 1553/1674/1795/1918、手动 1599/1737/1885），
# 2026-09-28 已删除。它**不是平台差异** —— 那几个数字恰好等于上面这套坐标乘
# 1982/1920（=1.0323），是当初量在一张**被整帧拉伸过的老口径 PC 截图**上写下来的。
# 截图口径已于 2026-08-29 改为「客户区 1920×1080 原样贴入画布」，两边坐标逐像素一致
# （实测：同一模板在两个客户端的战斗帧上落点相差 1 像素）。
#
# ⇒ 不要因为「PC 上认不出」就往这里加第二套坐标。先按
# `docs/PC_TEMPLATE_MIGRATION.md` 第 1.2 节确认你手上的帧是不是老口径。


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

    def has_auto_layout(expected_xs: tuple[int, ...], expected_y: int) -> bool:
        """自动布局 = 底座排确实存在 + 至少 1 格底座是**蓝色（有活人）**。

        底座颜色的语义（2026-09-20 用户澄清，别记错）：
        - **蓝色 = 这个英雄还活着**；
        - **红色 = 这个英雄已经阵亡**（底座变红变黑往下沉）。

        所以「亮」本身分两层，可靠度完全不同：
        - 蓝色（活人）才是「这局还在打」的证据；
        - 红色（阵亡）只说明「这是战斗里的底座排、有伤亡」，不能当活人算。

        而低存活局面的关键在**底座环**：阵亡后底座颜色失效，但底座的位置圈还在，
        所以「底座排是否存在」必须靠对齐圆判断，不能靠颜色数。
        2026-09-20 竞技场实测：`battle_auto_dead_three_live` 就是**活 1 亡 3、圆 4**
        —— 老逻辑「亮 >= 3 格」能撑住，只是因为把 3 个**红（阵亡）也算成了亮**；
        一旦红底座暗到认不出来（底座沉下去），就塌成「亮 1 格」→ 判不出自动战斗
        （详见 memory/topics/battle_auto_flip.md）。

        两道门槛取或：
        - `活 >= 1 且 圆 >= 3`：4 格底座环都在 ⇒ 必然是战斗画面，此时有 1 个活人就成立。
        - `亮 >= 3 且 圆 >= 2`：保留原判据兜底 —— 红底灵魂技/暗冷却槽上的图标会让霍夫圆
          漏检（实测 story/battle_auto_skill_cooldown 只剩 2 个圆），那种帧只能靠颜色数，
          这里红色必须照算（它证明的是「底座排在这」，不是「还有活人」）。
        """
        alive_bases, lit_bases = 0, 0
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
            blue_hit = float(np.mean(blue)) >= 0.40
            red_hit = float(np.mean(red)) >= 0.25
            alive_bases += int(blue_hit)
            lit_bases += int(blue_hit or red_hit)
        aligned_rings = aligned_count(expected_xs, expected_y, (40, 60), 30)
        return (alive_bases >= 1 and aligned_rings >= 3) or (
            lit_bases >= 3 and aligned_rings >= 2
        )

    # 「圆 >= 3」本身就是手动布局的排他证据：手动 3 钮在 x 1440~1982 上最多
    # 只能擦到 2 个自动槽位（1534→1505、1834→1858，另有 2 个按钮落在槽位窗口外），
    # 所以放宽「亮 >= 1」不会被手动布局误命中；全库 176 张夹具 + 187 张实跑
    # 诊断图上，「圆 >= 3」只出现在真实战斗画面里。
    if has_auto_layout(_AUTO_CONTROL_CENTERS, 1047):
        return BattleControls.AUTO_CONTROLS

    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]

    def manual_borders(expected_xs: tuple[int, ...]) -> list[bool]:
        borders = []
        for center_x in expected_xs:
            distance_squared = (xx - center_x) ** 2 + (yy - 1040) ** 2
            border = (distance_squared >= 55 ** 2) & (distance_squared <= 75 ** 2)
            borders.append(float(np.mean(hsv[:, :, 2][border] > 120)) >= 0.35)
        return borders

    manual_border_hits = manual_borders(_MANUAL_CONTROL_CENTERS)
    manual_circle_count = aligned_count(
        _MANUAL_CONTROL_CENTERS, 1040, (55, 82), 38
    )
    legacy_canvas = not frame[:52].any() and not frame[:, 1920:].any()
    if manual_circle_count == len(_MANUAL_CONTROL_CENTERS) and (
        all(manual_border_hits) or legacy_canvas
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

    pause_controls = white_ratio((1780, 45, 1920, 165))
    if controls is BattleControls.AUTO_CONTROLS:
        # 自动布局偶尔会在暗色技能特效下让左侧行动顺序栏几乎不可见；
        # 此时以右上战斗控制区作为独立的第二锚点，不能把有效战斗误判为未知。
        return 0.08 <= pause_controls <= 0.85

    turn_order = white_ratio((0, 120, 140, 900))
    if turn_order < 0.12:
        return False

    # 技能演出会暂时盖住底部技能槽，但右上战斗控制区和左侧行动顺序
    # 仍保留高亮结构。上限排除纯白加载帧和整块白色非战斗面板。
    return 0.08 <= pause_controls <= 0.85 and turn_order >= 0.12
