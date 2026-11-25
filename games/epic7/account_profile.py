"""从大厅画面读出「这次登录的是谁」。

## 位置与依据（2026-11-23 实测）

大厅左上角固定是「圆形头像 + 昵称 + 账号等级」两行字。拿本地 1982×1132 的整帧
截图裁剪 ``(150, 85, 470, 70)`` 放大 3 倍后交给 rapidocr，一次读回：

    康康626      置信度 0.814
    S.Rank.20    置信度 0.855

耗时约 0.66 秒（不含模型加载）。

## 判据为什么要求「两行都在」

只读到一行就采信，会把**别的页面左上角的文字**当成昵称 —— 那会凭空造出一个账号，
并且是静默的。所以这里用第二行当身份证：

- 等级行的格式是固定的 ``X.Rank.NN``，别处不会出现；
- 名字行必须是紧挨在等级行上方的那一条。

两行凑不齐就返回 ``None``，调用方按「未识别」处理（落共用账本）。**绝不猜。**

## 等级不参与分号

等级会随升级变化，所以它只用于显示，不进目录名、不进任何判据。
"""

from __future__ import annotations

import re
from typing import Any

import cv2

# 昵称与等级所在区域：左上角头像右边。宽度留到 470，够长昵称用；
# 再往右是「图表」按钮，不属于这一段。
_ACCOUNT_REGION = (150, 85, 470, 70)
_ZOOM = 3
# 实测值形如 ``S.Rank.20``；放宽到 1~3 个大写字母 + 1~3 位数字。
_RANK_PATTERN = re.compile(r"^[A-Z]{1,3}\.Rank\.\d{1,3}$", re.IGNORECASE)
_ENGINE: Any = None


def _engine() -> Any:
    """懒加载 OCR 引擎；没装 ``rapidocr-onnxruntime`` 返回 None（按读不到处理）。"""

    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:  # noqa: BLE001 - 可选依赖，缺了就退化成「读不到」
            return None
        _ENGINE = RapidOCR()
    return _ENGINE


def read_account(screen: Any) -> dict[str, str] | None:
    """读回 ``{"name": "康康626", "rank": "S.Rank.20"}``；认不出返回 ``None``。"""

    # 先判帧、后加载引擎：没画面时连模型都不该建（测试与失败路径都不必付这 1~2 秒）。
    if screen is None or getattr(screen, "size", 0) == 0:
        return None
    engine = _engine()
    if engine is None:
        return None
    x, y, width, height = _ACCOUNT_REGION
    if screen.shape[0] < y + height or screen.shape[1] < x + width:
        return None
    crop = screen[y : y + height, x : x + width]
    # 放大后再识别：这两行字在 1982 画布上只有 ~28px 高，原尺寸召回率低。
    crop = cv2.resize(crop, None, fx=_ZOOM, fy=_ZOOM, interpolation=cv2.INTER_CUBIC)
    try:
        result, _elapse = engine(crop)
    except Exception:  # noqa: BLE001 - OCR 内部错误不该把整轮任务打挂
        return None
    items = _ordered(result)
    if not items:
        return None

    # 情况一：两行分开（实测形态）。
    for index, (text, _top) in enumerate(items):
        if not _RANK_PATTERN.match(text):
            continue
        name = items[index - 1][0] if index > 0 else ""
        if _plausible_name(name):
            return {"name": name, "rank": text}

    # 情况二：OCR 把两行并成一条（不同字号/缩放下会这样）。只认「名字 + 空格 +
    # 等级」这一种切法，切出来的名字仍要过同一道校验。
    for text, _top in items:
        match = _RANK_PATTERN.search(text)
        if match is None:
            continue
        name = text[: match.start()].strip()
        if _plausible_name(name):
            return {"name": name, "rank": match.group(0)}
    return None


def _ordered(result: Any) -> list[tuple[str, float]]:
    """把 OCR 结果整理成「按纵向位置排序的（文本, 顶边 y）」，滤掉空串。"""

    items: list[tuple[str, float]] = []
    for item in result or []:
        text = str(item[1]).strip()
        if not text:
            continue
        box = item[0]
        try:
            top = float(box[0][1])
        except (IndexError, TypeError, ValueError):
            top = 0.0
        items.append((text, top))
    items.sort(key=lambda entry: entry[1])
    return items


def _plausible_name(text: str) -> bool:
    """名字的最低门槛：非空、不太长、不是纯符号、本身不是等级行。

    刻意**不**做「只允许中英文数字」这类白名单：玩家的昵称什么字符都可能有，
    收窄只会让正常账号读不出来。这里只排除明显不是昵称的形态。
    """

    if not text or len(text) > 32:
        return False
    if _RANK_PATTERN.match(text):
        return False
    return any(ch.isalnum() for ch in text)
