# -*- coding: utf-8 -*-
"""成就领取的视觉证据（PC 端首条路线，2026-11-08）。

## 这条路线为什么只有 PC 图

用户口径：「逻辑业务逻辑是通用在什么地方点什么，但图片素材先放到 PC 端；
模拟器到目前还用不到，以后需要时再补图」。所以：

* 业务状态机（``games/epic7/achievement.py``）**不含任何平台分支**；
* 模板只放在 ``templates/achievement/pc/``，模拟器跑这条路线时会因为缺图在
  构造期直接报错（fail-closed），而不是带着半套判据跑到真机上。

## 页面顺序：弹窗必须排在成就页前面

奖励弹窗是**半透明遮罩**，底下的成就页元素照样能匹配到高分实测：
``page_title`` 在弹窗帧上 **0.9999**、``claim_all`` **0.9987**。
所以判定顺序只能是「先弹窗、后整页」，否则状态机会对着被盖住的按钮点。

## 「全部领取」不能靠模板分亮/灰

绿态与灰态**形状完全相同**，只差颜色与亮度，实测互相命中 0.96~1.00。
TM_CCOEFF_NORMED 是去均值归一化，本来就不看绝对亮度 ⇒ 两态必须用**颜色比例**
区分（`claim_all_green_ratio`），与骑士团「请求支援按钮灰/亮」同一套做法。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    PageEvidence,
)

REFERENCE_SIZE = (1982, 1132)
DEFAULT_THRESHOLD = 0.80

REGIONS: dict[str, tuple[int, int, int, int]] = {
    # 成就页左上「成就」两个字。
    "page_title": (55, 50, 210, 95),
    # 右下「全部领取」按钮（只用来定位与判在不在，亮/灰由颜色比例决定）。
    # ⚠️ 搜索区**紧贴按钮**（330x62）：放宽到 420x120 会把周围的暗背景算进分母，
    # 亮态占比从 0.2643 掉到 0.1427，阈值余量只剩 0.04 —— 那是自找的脆弱。
    "claim_all": (1548, 1022, 330, 62),
    # 左下「持续效果上升」金色按钮。
    "effect_upgrade": (555, 985, 360, 130),
    # 「获得成就奖励」六字标题。
    "reward_title": (760, 200, 460, 120),
    # 奖励弹窗底部「点击关闭」。
    "popup_close_reward": (860, 840, 280, 100),
    # 效果升级弹窗底部「点击关闭」（比奖励弹窗右移约 148px，实测两模板互不命中）。
    "popup_close_effect": (1010, 855, 280, 100),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

_PAGES = (
    # 弹窗在前：半透明遮罩下成就页元素仍是 0.99+（见模块 docstring）。
    PageEvidence("achievement.reward_popup", required=("reward_title",)),
    PageEvidence("achievement.effect_popup", required=("popup_close_effect",)),
    PageEvidence("achievement.page", required=("page_title",)),
)

# ---- 左列 4 个分类 ---------------------------------------------------------
#
# 成就页右栏是 5 个分类图标，只处理前 4 个（第 5 个要解锁、领取形式也不同）。
# 位置实测：第 1 个中心 y=220，其后每个 +120；图标中心 x=91。
# ⚠️ 分类名（记忆之根管理院 / 元老院 / …）**不参与识别** —— 全项目只按位置办事，
# 免得换个账号分类名不同就又认不出。
CLASS_COUNT = 4
CLASS_ICON_POINTS: tuple[tuple[int, int], ...] = (
    (91, 220),
    (91, 340),
    (91, 460),
    (91, 580),
)

# 每个分类图标**左上角角标**的搜索区（基准画布）。红点中心实测 (41, 图标y-30)。
CLASS_DOT_ZONES: tuple[tuple[int, int, int, int], ...] = tuple(
    (16, point[1] - 52, 54, 56) for point in CLASS_ICON_POINTS
)

# 角标 = 橙红实心圆。阈值取自实测：本页 3 颗红点面积 654~666 / 边长 31px；
# 卡片上的金色装饰饱和更低（hue 在 15~20 但 S<120），不会落进来。
DOT_HUE = (4, 30)
DOT_SAT_MIN = 130
DOT_VAL_MIN = 130
DOT_MIN_AREA = 200
DOT_MIN_FILL_RATIO = 0.55
DOT_SIZE_RANGE = (18, 46)

# 「全部领取」绿态/灰态的判据：按钮区里**够绿够亮**的像素占比。
# 实测（2026-11-08 四帧）：亮态 0.2643 / 灰态 0.0000 ⇒ 取 0.10，两侧余量各 0.16。
CLAIM_ALL_GREEN_MIN = 0.10
CLAIM_ALL_GREEN_HSV = ((35, 90, 90), (85, 255, 255))


def build_achievement_evidence(template_dir: Path) -> EvidenceProfile:
    atoms = {
        key: AtomEvidence(
            key=key,
            template_path=relative_path,
            region=REGIONS[key],
            threshold=THRESHOLDS[key],
            reference_size=REFERENCE_SIZE,
        )
        for key, relative_path in _TEMPLATE_PATHS.items()
    }
    return EvidenceProfile(
        atoms=atoms,
        pages=_PAGES,
        config_path=str(Path(__file__).resolve()),
        template_root=template_dir,
    )


def claim_all_green_ratio(
    screen: np.ndarray,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> float:
    """「全部领取」按钮区里够绿够亮的像素占比 —— 亮态 ≈0.26、灰态 ≈0.00。"""
    x, y, width, height = REGIONS["claim_all"]
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    patch = screen[
        round(y * scale_y) : round((y + height) * scale_y),
        round(x * scale_x) : round((x + width) * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    low, high = CLAIM_ALL_GREEN_HSV
    mask = cv2.inRange(hsv, np.array(low), np.array(high))
    return float(mask.sum()) / 255.0 / mask.size


def find_class_dot(
    screen: np.ndarray,
    index: int,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> tuple[int, int] | None:
    """第 ``index``（0 起）个分类图标左上角那颗橙红角标的中心；没有就返回 None。"""
    if not 0 <= index < CLASS_COUNT:
        raise ValueError(f"分类下标越界：{index}")
    x, y, width, height = CLASS_DOT_ZONES[index]
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    left = round(x * scale_x)
    top = round(y * scale_y)
    patch = screen[top : top + round(height * scale_y), left : left + round(width * scale_x)]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([DOT_HUE[0], DOT_SAT_MIN, DOT_VAL_MIN]),
        np.array([DOT_HUE[1], 255, 255]),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    for blob in range(1, count):
        blob_w, blob_h, area = stats[blob][2], stats[blob][3], stats[blob][4]
        if area < DOT_MIN_AREA:
            continue
        if not (
            DOT_SIZE_RANGE[0] <= blob_w <= DOT_SIZE_RANGE[1]
            and DOT_SIZE_RANGE[0] <= blob_h <= DOT_SIZE_RANGE[1]
        ):
            continue
        if area / float(blob_w * blob_h) < DOT_MIN_FILL_RATIO:
            continue
        return (
            round(left + centroids[blob][0]),
            round(top + centroids[blob][1]),
        )
    return None


def class_dots(
    screen: np.ndarray,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> dict[int, tuple[int, int]]:
    """4 个分类里哪些还挂着角标 -> ``{下标: 角标中心}``。"""
    found: dict[int, tuple[int, int]] = {}
    for index in range(CLASS_COUNT):
        dot = find_class_dot(screen, index, reference_size=reference_size)
        if dot is not None:
            found[index] = dot
    return found
