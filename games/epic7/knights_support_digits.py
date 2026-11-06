"""骑士团「资源支援」列表：读每行的「持有：N」和按钮上的「支援 M 个」。

## 为什么需要它（2026-09-25 实跑事故）

材料不够时，那一行的绿色「支援1个」按钮**不会变灰**：点下去什么都不发生
（游戏只在下方闪一行小字「材料不足」，一闪就没）。主循环看到「点完页面没变」，
判定成「没点到」，于是对**同一格**连点 4 次，最后以
`停止=动作[support-one]连续 4 次未生效` **把整条路线提前收工**
（后面的每周任务领奖也没做）。

路线里本来就有「这一格吃不下就换下一格」的跳过表，但它**从来没生效过** ——
主循环的转场重试会把它新挑的那一行顶替回旧坐标（详见
``runner_base.py`` 第 539~562 行）。所以正确的做法是**点之前就知道能不能点**：
读「持有」与「需求」，不足就直接跳过，连点都不用点。

## 判据只能读数字，颜色这条路实测走不通

两张实拍帧对照（``support_page_two_buttons.png`` 与实跑诊断帧）：

| 行 | 持有 | 按钮 | 「持有：N」的文字颜色 |
| --- | --- | --- | --- |
| 湾9 / Alefa | 0 / 1（**不足**） | 绿、能点 | **绿色** |
| 广东瀚鹏 / Cattails | 5,133 / 225（够） | 绿、能点 | **绿色（同一个绿）** |
| Lo3w / 飛鳥湊 | 5,133 / 1 | 灰、灰勾 | 灰（= 已经支援过） |

像素采样：不足那一行 BGR=(98,174,27)，够的那一行 (98,175,27) ⇒ **颜色分不出来**；
灰色只代表「已支援」，与「不足」无关。

## 为什么不用 OCR

`pytesseract` 装了但 **tesseract 引擎没装**（`TesseractNotFoundError`），
`easyocr` / `paddleocr` 要拖 torch / paddle 那一整套。而这里的字是**位图字体、
大小固定**，切出来的字形又干净——用**字形模板**（本项目一直在用的手法）就够了，
零新依赖、结果确定、可复核。

## 判据的三态（关键：认不出必须说「不知道」）

``RowNumbers.verdict`` 返回三态：

- ``True``（材料不足）：**持有与需求两边都读得出**，且 持有 < 需求；
- ``False``（够）：同上，且 持有 ≥ 需求；
- ``None``（不知道）：只要有一边读不出（字形不在字模里、区域没框到、字形个数不合理），
  就一律不作判断 —— 调用方**照旧去点**，也就是**退回今天的行为**。

⚠️ **认错比认不出更糟**：把能支援的行读成「不足」会白丢积分，所以宁可返回
``None``。反过来，读不出只会让这一格回到「点一次、没反应就重试」的老路，
不会比现在更坏。

## 字模的覆盖范围（说清楚，别当成万能）

字模目前有 **0~5** 六个（来源与样本数见 ``docs/maintenance/knights_donation.md``）。
于是能判出来的「不足」只覆盖 **需求 ∈ 1~5 且 持有 ∈ 0~4** 这一段 ——
实测需求只有 1~4（`支援1个/2个/4个`），所以这一段已经盖住现实里会遇到的格子。
需求 6 以上读不出 ⇒ 返回 ``None`` ⇒ 照旧点（等于现状）。

## 字形怎么切

- 搜索带都是**相对按钮匹配中心**的偏移（行会随列表重排上下移动，写绝对坐标没用）；
- 「持有：N」整串是**以按钮为中心居中**的，所以左右各留 175 px；
  「持有」两个字宽 23~24，数字宽 8~14 ⇒ 用「宽 ≤ 20」把标签剔掉，剩下的就是数字；
- 冒号与千分位逗号会被「高 ≥ 15」滤掉（它们只有 3~8 px 高），所以
  `持有 5,133` 读出来是 `5133` —— 比较大小不受影响。
- 归一化：按**字形高度**缩放到 24 px 再水平居中放进 18×24 画布。
  按高度归一化顺带把「绿色 22px / 白色 26px」两个样式统一了，所以字模只存**一套**
  （实测跨样式互认通过：留一验证 17/17，整行重读 5/5）。
- ⚠️ **判据只在基准画布上生效**：实测把基准帧放大到 2 倍之后绿色那一侧就读不出来了
  （重采样把字缘色相拉走、掩膜碎掉），而项目里**没有**别的分辨率的真帧可验 ⇒
  尺寸偏离基准超过 ``SIZE_TOLERANCE`` 时**整条判据弃权**（照旧点）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from auto_game_unified.core.matcher import best_match, load_template

# 与 matcher 同口径的基准画布（所有区域常量都按这个口径量）。
REFERENCE_SIZE = (1982, 1132)

# 「持有：N」文字带：**相对按钮匹配中心**的偏移。
# 实测（基准口径）：字形顶边在 中心-101、高 21~24 ⇒ 占 中心-101 .. 中心-79。
HOLDINGS_DY = (-118, -58)
HOLDINGS_DX = (-175, 175)

# 按钮内文字「支援 M 个」：实测字形顶边在 中心-39、高 25~26 ⇒ 占 中心-39 .. 中心-13。
REQUIRED_DY = (-58, 14)
REQUIRED_DX = (-140, 140)

# 字形掩膜：只看「高饱和 + 够亮」的绿色文字（色相限在绿段，避免把白字/灰字算进来）。
GREEN_HUE_MIN = 30
GREEN_HUE_MAX = 80
GREEN_SATURATION_MIN = 120
GREEN_VALUE_MIN = 140
# 按钮上的白字：低饱和 + 很亮。
WHITE_SATURATION_MAX = 60
WHITE_VALUE_MIN = 200

# 连通域筛成「一个数字字形」的条件（基准口径，会按画面缩放）：
# - 宽 4~20：剔掉「持有」两个字（宽 23~24）与「支援」（宽 29~30）；
# - 高 ≥ 15：剔掉冒号、千分位逗号（高 3~8）与「个」的碎块（高 9~12）；
#   同时把「个」的竖笔（宽 3）也剔掉。
GLYPH_MIN_WIDTH = 4
GLYPH_MAX_WIDTH = 20
GLYPH_MIN_HEIGHT = 15
GLYPH_MIN_AREA = 30
# 一行最多认几个字形（持有 5 位数 + 余量）；超过就说明切歪了，直接判「不知道」。
GLYPH_MAX_COUNT = 6

# 归一化画布（宽 x 高）。
GLYPH_CANVAS = (18, 24)
# 匹配分数下限。实测同一数字的正确匹配 ≥ 0.83；最容易混的一对是 2/3
# （正确 0.87~0.92、错配 0.57~0.63），而实心色块那种「根本不是数字」的形状最高 0.35
# ⇒ 0.70 左右两边都留了余量。
GLYPH_MATCH_MIN_SCORE = 0.70

# ⚠️ **判据只在基准画布（1982x1132）上生效**。实测把基准帧放大到 2 倍之后，
# 绿色文字那一侧就读不出来了（重采样把字缘的色相拉走、掩膜碎掉），
# 而项目里**没有**其它分辨率的真帧可以验证。与其发布一条没验证过的缩放逻辑
# （读错比读不出更糟），不如在别的尺寸上**整条判据弃权** ⇒ 调用方照旧去点。
# 这也与模块 docstring 的口径一致：换客户端/换分辨率时判据必须重采。
SIZE_TOLERANCE = 0.02

# 必须齐备的字模。缺一个就在**构建期**报错：宁可加载不动，也不要安静地退回「照旧点」。
REQUIRED_DIGITS = (0, 1, 2, 3, 4, 5)
DIGITS_DIRNAME = "digits"


@dataclass(frozen=True)
class RowNumbers:
    """一行的「持有 N」与「需求 M」。读不出来的那一侧是 ``None``。"""

    holdings: Optional[int]
    required: Optional[int]

    @property
    def verdict(self) -> Optional[bool]:
        """``True`` = 材料不足；``False`` = 够；``None`` = 读不全，**别据此下判断**。"""
        if self.holdings is None or self.required is None:
            return None
        return self.holdings < self.required

    def describe(self) -> str:
        holdings = "?" if self.holdings is None else str(self.holdings)
        required = "?" if self.required is None else str(self.required)
        return f"持有 {holdings} / 需求 {required}"


def load_digit_glyphs(template_dir: Path) -> dict[int, np.ndarray]:
    """读 ``<template_dir>/digits/<数字>.png`` 里的字模（单通道二值，18x24）。

    ``template_dir`` 是路线模板根（``templates/knights_donation``）。
    缺文件直接抛：字模是判据的一部分，缺了会让「不足就跳过」安静地失效。
    """
    directory = template_dir / DIGITS_DIRNAME
    glyphs: dict[int, np.ndarray] = {}
    for digit in REQUIRED_DIGITS:
        path = directory / f"{digit}.png"
        if not path.exists():
            raise FileNotFoundError(
                f"缺数字字模 {path}；骑士团支援列表的「材料不足就跳过」判据依赖它，"
                "请按 docs/maintenance/knights_donation.md 重新生成"
            )
        image = load_template(str(path))
        glyphs[digit] = (_to_gray(image) >= 128).astype(np.uint8) * 255
    return glyphs


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return image[:, :, 0]
    return image


def green_mask(patch: np.ndarray) -> np.ndarray:
    """「持有：N」那种绿色文字的掩膜（``patch`` 必须与画面同口径 = RGB）。"""
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    return (
        (hsv[:, :, 0] >= GREEN_HUE_MIN)
        & (hsv[:, :, 0] <= GREEN_HUE_MAX)
        & (hsv[:, :, 1] >= GREEN_SATURATION_MIN)
        & (hsv[:, :, 2] >= GREEN_VALUE_MIN)
    )


def white_mask(patch: np.ndarray) -> np.ndarray:
    """按钮上「支援 M 个」那种白字的掩膜。"""
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    return (hsv[:, :, 1] <= WHITE_SATURATION_MAX) & (hsv[:, :, 2] >= WHITE_VALUE_MIN)


def glyph_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """把掩膜里像「一个数字」的连通域挑出来，按 x 排序。

    两个样式共用同一套筛子（实测量到的边界见常量注释）。只在基准画布上调用 ——
    别的分辨率由 ``read_row_numbers`` 提前弃权，所以这里不需要缩放。
    """
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    found = [
        (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if GLYPH_MIN_WIDTH <= stats[i, 2] <= GLYPH_MAX_WIDTH
        and stats[i, 3] >= GLYPH_MIN_HEIGHT
        and stats[i, 4] >= GLYPH_MIN_AREA
    ]
    found.sort()
    return found


def normalize_glyph(mask: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """裁出字形、按高度缩放到 ``GLYPH_CANVAS``、水平居中放进固定画布（二值 0/255）。"""
    x, y, width, height = box
    crop = mask[y : y + height, x : x + width]
    canvas_width, canvas_height = GLYPH_CANVAS
    scaled_width = max(1, int(round(width * canvas_height / height)))
    resized = cv2.resize(
        crop.astype(np.uint8) * 255,
        (scaled_width, canvas_height),
        interpolation=cv2.INTER_NEAREST,
    )
    canvas = np.zeros((canvas_height, canvas_width), np.uint8)
    if scaled_width >= canvas_width:
        canvas[:, :] = resized[:, :canvas_width]
        return canvas
    left = (canvas_width - scaled_width) // 2
    canvas[:, left : left + scaled_width] = resized
    return canvas


def glyph_score(glyph: np.ndarray, template: np.ndarray) -> float:
    """同尺寸两图的归一化互相关（与 ``cv2.TM_CCOEFF_NORMED`` 同义）。"""
    # 走共享的 best_match 而不是直接调 cv2：同一个字形会被反复比对（数字 0~9 × 多套
    # 模板），离线测试里重复率很高。语义不变 —— 结果图是 1x1 时 minMaxLoc 的最大值
    # 就是原来那个 result[0, 0]。
    score, _location = best_match(
        glyph.astype(np.float32), template.astype(np.float32)
    )
    value = float(score)
    if not np.isfinite(value):
        return 0.0
    return value


def _read_digits(mask: np.ndarray, glyphs: dict[int, np.ndarray]) -> Optional[int]:
    """把掩膜里的数字读成整数；任何一个字形认不出就返回 None。"""
    boxes = glyph_boxes(mask)
    if not boxes or len(boxes) > GLYPH_MAX_COUNT:
        return None
    text = ""
    for box in boxes:
        glyph = normalize_glyph(mask, box)
        best_digit, best_score = None, -1.0
        for digit, template in glyphs.items():
            score = glyph_score(glyph, template)
            if score > best_score:
                best_digit, best_score = digit, score
        if best_digit is None or best_score < GLYPH_MATCH_MIN_SCORE:
            return None
        text += str(best_digit)
    return int(text)


def _read_digits_pc(mask: np.ndarray, glyphs: dict[int, np.ndarray]) -> Optional[int]:
    """PC 客户端专用：把掩膜里的数字读成整数；读不出返回 None。

    ## 从**最右边**往左取一段连续的通过项（2026-11-03 PC 实测改）

    原来从左往右读、**任何一个字形认不出就整侧返回 None**。PC 上实测（11-02 23:01 现场帧）：
    「持有：1」的绿字掩膜被切成 3 个过筛连通域 —— 宽 8、宽 15 是「持有」两个字的碎片
    （宽 8/15 都 ≤ ``GLYPH_MAX_WIDTH``，混进了数字筛子），最右那个宽 8 高 21 才是数字「1」。
    匹配分：碎片 0.324 / 0.324，数字 **0.980**。
    ⇒ 一个碎片认不出就把整侧拖成 None，白丢「材料不足就跳过」这道前置判据。

    改成**从右往左、遇到第一个认不出的就停**：
    - 「持有：1」⇒ 数字 1 通过、再往左是碎片 0.32 失败 ⇒ 读 `1` ✅
    - 「持有：5,133」⇒ 3/3/1/5 都通过，再往左是标签 ⇒ 读 `5133` ✅
    - 中间某一位真认不出 ⇒ 截断成偏小的数 ⇒ 调用方判「不足」而跳过该格，
      属于 fail-safe 方向（少支援一次，不会点错人）。

    ## 字模按「原版 / 加粗 / 细化」三个变体取最高分（同一次实测）

    需求侧「支援2个」的「2」在 PC 上原样只有 **0.698**（阈 0.70，差 0.002）。
    把字模做一次 2x2 膨胀/腐蚀后再比，最高到 **0.738** ⇒ 过阈。
    这是**吸收渲染粗细差异**，不是放宽阈值 —— ``GLYPH_MATCH_MIN_SCORE`` 一个字没动。
    """
    boxes = glyph_boxes(mask)
    if not boxes or len(boxes) > GLYPH_MAX_COUNT:
        return None
    kernel = np.ones((2, 2), np.uint8)
    text = ""
    for box in reversed(boxes):
        glyph = normalize_glyph(mask, box)
        best_score = -1.0
        best_digit: Optional[int] = None
        for digit, template in glyphs.items():
            for variant in (
                template,
                cv2.dilate(template, kernel, iterations=1),
                cv2.erode(template, kernel, iterations=1),
            ):
                score = glyph_score(glyph, variant)
                if score > best_score:
                    best_digit, best_score = digit, score
        if best_digit is None or best_score < GLYPH_MATCH_MIN_SCORE:
            break
        text = str(best_digit) + text
    if not text:
        return None
    return int(text)


def _patches(
    screen: np.ndarray,
    button_center: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """按按钮中心裁出「持有」文字带与按钮文字盒。"""
    bx, by = button_center

    def crop(dy: tuple[int, int], dx: tuple[int, int]) -> np.ndarray:
        return screen[by + dy[0] : by + dy[1], bx + dx[0] : bx + dx[1]]

    return crop(HOLDINGS_DY, HOLDINGS_DX), crop(REQUIRED_DY, REQUIRED_DX)


def read_row_numbers(
    screen: np.ndarray,
    button_center: tuple[int, int],
    glyphs: dict[int, np.ndarray],
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    pc: bool = False,
) -> RowNumbers:
    """读一行「持有：N」与按钮「支援 M 个」。

    ``screen`` 必须是 RGB（与 ``runtime.capture()`` / ``load_template`` 同口径）。

    ⚠️ 只能在基准画布上判：``screen`` 尺寸偏离 ``reference_size`` 超过
    ``SIZE_TOLERANCE`` 时**整条判据弃权**（返回两侧都是 ``None``）——
    理由见 ``SIZE_TOLERANCE`` 的注释。
    """
    if abs(screen.shape[1] / reference_size[0] - 1) > SIZE_TOLERANCE or abs(
        screen.shape[0] / reference_size[1] - 1
    ) > SIZE_TOLERANCE:
        return RowNumbers(None, None)
    holdings_patch, required_patch = _patches(screen, button_center)
    if holdings_patch.size == 0 or required_patch.size == 0:
        return RowNumbers(None, None)
    reader = _read_digits_pc if pc else _read_digits
    return RowNumbers(
        reader(green_mask(holdings_patch), glyphs),
        reader(white_mask(required_patch), glyphs),
    )
