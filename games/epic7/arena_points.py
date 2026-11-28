"""竞技场对手行「积分」的读数，供「对手偏好」排序使用（2026-11-15）。

## 为什么读积分

对手行上能读的东西只有四类：头像与名字、积分、四名英雄的头像与等级角标、
可挑战状态。名字没有业务含义；英雄头像要一整座图鉴库才能认（见
``docs/TODO.md`` 的登记）；这一页**没有总战力**，对手详情页也没有。
⇒ 积分是唯一既读得出、又直接对应玩家决策的字段：赢积分高的对手得更多。

## 口径（两张真帧实测）

- 三行「积分N」在画布上是**同一列**，行距 **192 px**，文字基线 y = 419 / 611 / 803。
- 整列一条区域 `(560, 396, 260, 440)` 一次 OCR 就能拿三行（约 **0.35~0.45 秒**）；
  分三块单独 OCR 反而更慢（约 1.5 秒）且第三行会被切成两段。
- 放大 **2 倍**再喂 OCR：原尺寸只有约 20 px 高，召回率低。
  实测两张真帧六个数字全对：`list.png` → 0 / 102 / 154；`selected.png` → 50 / 75 / 998。
- 只认**以「积分」开头**的框（``匹配`` 而非 ``搜索``）：玩家昵称里也可能出现「积分」，
  再叠加「垂直位置必须贴近某一行的基线（±40 px）」这一条，昵称整行都会被排除。

## 三态

读不出的那一行返回 ``None``，**不拿 0 顶替**。调用方按「这一行不参与排序」处理；
三行都读不出时整条偏好本轮不生效，并在动作依据里写明原因。
非可选：OCR 是可选依赖（``rapidocr-onnxruntime``），没装就整段返回 ``None``，
主流程一个字节都不受影响 —— 与支线倒计时（``side_story.read_period_countdown``）
同一套写法。
"""

from __future__ import annotations

import re
from typing import Any, Optional

import cv2
import numpy as np


# 整列一条：三行「积分N」都在这一条里，一次 OCR 拿全。
_POINTS_STRIP = (560, 396, 260, 440)
# 各行「积分」文字的实测基线 y（画布 1982x1132）。行距 192。
_ROW_BASELINES = (419, 611, 803)
# 匹配时允许的垂直偏差。取 40：不到半个行距，昵称行（约 +130）进不来。
_ROW_TOLERANCE = 40
# 放大倍数。2 倍实测够用；再大只是更慢。
_SCALE = 2
# ⚠️ ``match`` 不是 ``search``：只认以「积分」开头的框，昵称里的「积分」不算。
_PATTERN = re.compile(r"积分\s*([0-9]{1,6})")
_OCR_ENGINE: Any = None


def _ocr_engine() -> Any:
    """懒加载 OCR 引擎（首次建模型约 1~2 秒，之后复用同一实例）。

    可选依赖：没装 ``rapidocr-onnxruntime`` 就返回 None，调用方按「这次读不到」处理。
    """
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:  # noqa: BLE001 - 可选依赖，缺了就退化成「读不到」
            return None
        # 调用方已放大积分裁片。避免检测器按短边再次放大整块画面。
        # RapidOCR 1.2.3 要求检测器参数同时指定模型路径，None 表示用内置模型。
        _OCR_ENGINE = RapidOCR(det_limit_type="max", det_model_path=None)
    return _OCR_ENGINE


def _scaled_strip(
    screen: np.ndarray, reference_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    """把画布坐标的区域按实际帧尺寸缩放（运行期恒为 1982x1132，测试会喂其它尺寸）。"""
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    x, y, width, height = _POINTS_STRIP
    return (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )


def read_opponent_points(
    screen: np.ndarray,
    reference_size: tuple[int, int] = (1982, 1132),
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """读出三行对手的积分；读不出的位置为 ``None``。

    返回顺序与 ``ArenaStateMachine.opponent_availability`` 一致（第 0 行在最上）。
    """
    engine = _ocr_engine()
    if engine is None or screen is None or screen.size == 0:
        return (None, None, None)
    x, y, width, height = _scaled_strip(screen, reference_size)
    crop = screen[y : y + height, x : x + width]
    if crop.size == 0:
        return (None, None, None)
    crop = cv2.resize(
        crop, (width * _SCALE, height * _SCALE), interpolation=cv2.INTER_CUBIC
    )
    try:
        result, _elapse = engine(crop)
    except Exception:  # noqa: BLE001 - OCR 内部错误不该把整条路线打挂
        return (None, None, None)

    scale_y = screen.shape[0] / reference_size[1]
    baselines = [round(value * scale_y) for value in _ROW_BASELINES]
    tolerance = round(_ROW_TOLERANCE * scale_y)
    found: dict[int, tuple[int, int]] = {}
    for item in result or []:
        text = str(item[1]).strip()
        match = _PATTERN.match(text)
        if match is None:
            continue
        top = min(point[1] for point in item[0]) / _SCALE + y
        row = min(
            range(len(baselines)),
            key=lambda index: abs(baselines[index] - top),
        )
        if abs(baselines[row] - top) > tolerance:
            continue
        offset = abs(baselines[row] - top)
        # 同一行出现两个候选时取更靠近基线的那个（另一条多半是昵称里的「积分」）。
        if row not in found or offset < found[row][0]:
            found[row] = (offset, int(match.group(1)))
    return tuple(found[row][1] if row in found else None for row in range(3))
