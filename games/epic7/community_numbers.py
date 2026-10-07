"""社区 H5（竖屏）页面上的数字读数 —— 字形模板 + 整串模板。

## 为什么不用 OCR

与 ``knights_support_digits.py`` 同一条理由：项目只依赖 6 个包（numpy / opencv /
Pillow / PyAutoGUI / PyGetWindow / psutil），不引 OCR 引擎。社区页上的数字来自**固定
字体的网页文本**，字形模板足够用，而且**离线可复核**（模板是文件，变了看得见）。

## 画布

竖屏 **1080x1920**。横屏那条链路（1982x1132）与本模块无关，由
``core/portrait.PortraitChannel`` 负责把帧切成这个口径。

## 读法（用户 2026-10-06 二次拍板：统一走字形）

| 位置 | 取值 | 读法 |
| --- | --- | --- |
| 积分余额 | 开放（任何非负整数） | 字形逐字（``read_digits``） |
| 任务进度 ``x/3`` ``x/1`` | 封闭 | 字形逐字（``read_pair``，认第 1、第 3 个组件） |
| 每日限购 ``x/y`` | 封闭 | 同上 |

**为什么最后没用「整串模板」**（原方案是用整串读 x/y，实测后改掉）：

整串模板是「把 ``3/3`` 整串裁一张原尺寸小图，在区域里逐像素比」。问题是社区页面
本质是网页，**同一串字在不同帧里会因为排版位置的半像素差异被重新栅格化** ——
实测同一串 ``3/3`` 在 A 帧 0.97~1.00、在 B 帧只有 0.74~0.80，跨帧 11/13 挂 2 个。
而字形读法先按**高度归一化**再比，天然免疫，同一批样本 19/19 全中。

整串那套（``read_string`` / ``load_string_templates`` + ``templates/community/strings/``）
**保留但不在生产路径上**。

## 三态，绝不猜

读不出就返回 ``None``（"不知道"），**不返回一个猜的值**。理由同骑士团那套：
「认错比认不出更糟」—— 认错的数字会直接变成业务动作（兑错东西 / 少兑一件），
认不出只是这一轮不报数。

## 极性

三处数字都是「文字比底暗」（绿字白底 / 灰字白底 / 青绿字薄荷底），所以统一
灰度 + Otsu 反相即可，**不需要按颜色分 HSV 通道**（2026-10-06 实测三处灰度范围
142/132/124 ~ 255，Otsu 切得干干净净）。留给 ``light_on_dark`` 参数是为了将来
遇到白字彩底（如「1255/1500」那种进度条上的白字）时不必改签名。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from auto_game_unified.core.matcher import best_match, load_template

# 竖屏基准画布（宽, 高）—— 与 ``core.portrait.PORTRAIT_CANVAS`` 同值。
# 不直接 import 是为了让本模块能脱离模拟器环境单独测试；改一处要改两处，
# 所以下面有一条守卫测试钉着等值关系。
PORTRAIT_SIZE = (1080, 1920)

# 字形归一化画布（宽, 高）。与 ``knights_support_digits.GLYPH_CANVAS`` 规格不同，
# 但**不能共用模板文件**：两边字体不同（游戏内 vs 网页），实测跨用分数极低。
#
# ⚠️ 高度必须 **≥ 源字高**。社区数字最大 26px，早期用 24 高（=下采样）时
# 同一串字在跨帧匹配上只有 0.60~0.70；改成 30 高（=上采样）后同批样本全部 ≥0.73。
# 下采样会把笔画宽度的亚像素差异放大成整像素差异，跨帧就不认了。
GLYPH_CANVAS = (22, 30)

# 连通域筛子。实测三处数字：余额/进度 17x25~26，限购角标 6x16~11x17。
# 高度下限取 12（罩住最小的角标数字），上限 34（把两侧的括号 h=39 挡在外面 ——
# 放进来会让「切出 3 个」变成「切出 5 个」，读数直接弃权）。
GLYPH_MIN_HEIGHT = 12
GLYPH_MAX_HEIGHT = 34
# 宽度上限：挡住「每日限购」四个汉字（21x21 见方）。
GLYPH_MAX_WIDTH = 30
GLYPH_MIN_AREA = 20
GLYPH_MAX_COUNT = 12

# 单字命中门槛。0.70 与骑士团那套同值；画布 22x30 下实测最优组的命中余量都在
# 0.73 以上，所以这个门槛留了余量又不至于放进「像但不对」的字形。
GLYPH_MATCH_MIN_SCORE = 0.70

# 整串命中门槛与领先优势。整串之间**前缀高度重合**（``0/1`` 与 ``0/2`` 只差最后一位），
# 所以除了绝对分，还要看**和次高分的差**，否则「0/1」的模板能在「0/2」的图上拿到
# 不低的分。两个数都由 ``_probe_community_numbers.py`` 在真机帧上实测得出。
STRING_MIN_SCORE = 0.90
STRING_MIN_MARGIN = 0.04

REQUIRED_DIGITS = tuple(range(10))
DIGITS_DIRNAME = "digits"
STRINGS_DIRNAME = "strings"


@dataclass(frozen=True)
class Readout:
    """一次读数结果。``value is None`` 表示**认不出**，不是 0。"""

    value: Optional[object]
    score: float
    source: str

    def describe(self) -> str:
        if self.value is None:
            return f"读不出（{self.source}，最高分 {self.score:.3f}）"
        return f"{self.value}（{self.source}，{self.score:.3f}）"


# ---------------------------------------------------------------- 掩膜与字形


def binarize(patch: np.ndarray, *, light_on_dark: bool = False) -> np.ndarray:
    """灰度 + Otsu 二值化，输出 0/255 的单通道掩膜（文字为 255）。

    ``light_on_dark=False``（默认）表示**文字比底暗** —— 社区三处数字都是这一种。
    """
    gray = patch
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    mode = cv2.THRESH_BINARY if light_on_dark else cv2.THRESH_BINARY_INV
    _, mask = cv2.threshold(gray, 0, 255, mode + cv2.THRESH_OTSU)
    return mask


def glyph_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """把掩膜里「像一个字符」的连通域挑出来，按 x 从左到右排序。"""
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    found = [
        (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3]))
        for i in range(1, count)
        if GLYPH_MIN_HEIGHT <= stats[i, 3] <= GLYPH_MAX_HEIGHT
        and stats[i, 2] <= GLYPH_MAX_WIDTH
        and stats[i, 4] >= GLYPH_MIN_AREA
    ]
    found.sort()
    return found


def normalize_glyph(mask: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """裁出字形、按高度缩放到 ``GLYPH_CANVAS``、水平居中放进固定画布（0/255）。

    高度归一让**同一字体的不同字号**共用一套模板 —— 社区页上余额是 26px、限购角标
    是 16px，切出来都进同一张 18x24 画布。
    """
    x, y, width, height = box
    crop = mask[y : y + height, x : x + width]
    canvas_width, canvas_height = GLYPH_CANVAS
    scaled_width = max(1, int(round(width * canvas_height / height)))
    # ⚠️ **INTER_AREA，不是 INTER_NEAREST**（骑士团那套用的是 NEAREST，别照抄）。
    # 这里的画布高度(30)大于源字高(16~26)，是**上采样**；最近邻会把笔画边缘的
    # 半像素差异放大成整像素台阶，跨帧同一串字只有 0.60~0.66。换成 INTER_AREA
    # 后同批样本升到 0.73~0.82（2026-10-06 实测，19 个验证点全部命中）。
    resized = cv2.resize(
        crop.astype(np.uint8),
        (scaled_width, canvas_height),
        interpolation=cv2.INTER_AREA,
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
    score, _location = best_match(
        glyph.astype(np.float32), template.astype(np.float32)
    )
    value = float(score)
    if not np.isfinite(value):
        return 0.0
    return value


def load_digit_glyphs(template_dir: Path) -> dict[int, np.ndarray]:
    """读 ``<template_dir>/digits/<0-9>.png`` 的字模（单通道二值，18x24）。

    缺文件**直接抛**：字模是判据的一部分，缺了会让「积分够不够」安静地失效
    （2026-10-03 判据静默降级的同款教训）。
    """
    directory = template_dir / DIGITS_DIRNAME
    glyphs: dict[int, np.ndarray] = {}
    for digit in REQUIRED_DIGITS:
        path = directory / f"{digit}.png"
        if not path.exists():
            raise FileNotFoundError(
                f"缺社区数字字模 {path}；积分余额读数依赖它，"
                "请按 docs/maintenance/community_checkin.md 重新生成"
            )
        image = load_template(str(path))
        if image.ndim == 3:
            image = image[:, :, 0]
        glyphs[digit] = (image >= 128).astype(np.uint8) * 255
    return glyphs


def load_string_templates(template_dir: Path, group: str) -> dict[str, np.ndarray]:
    """读 ``<template_dir>/strings/<group>/<名字>.png`` 的整串模板。

    文件名 = 该串本身（``1/2`` 写成 ``1_2.png``，因为 ``/`` 不能做文件名），
    下划线还原成斜杠。

    ⚠️ ``group`` 是**必需的**，不是可选：整串模板走**原尺寸**比对（不做高度归一），
    所以 26px 的任务进度字与 16px 的限购角标字**不能混在一个目录里** ——
    混了就会拿错尺子去量（实测两档差 1.6 倍，分数会掉到 0.5 上下）。
    """
    directory = template_dir / STRINGS_DIRNAME / group
    templates: dict[str, np.ndarray] = {}
    if not directory.is_dir():
        return templates
    for path in sorted(directory.glob("*.png")):
        text = path.stem.replace("_", "/")
        image = load_template(str(path))
        if image.ndim == 3:
            image = image[:, :, 0]
        templates[text] = (image >= 128).astype(np.uint8) * 255
    return templates


# ---------------------------------------------------------------- 读数


def read_digits(
    screen: np.ndarray,
    box: tuple[int, int, int, int],
    glyphs: dict[int, np.ndarray],
    *,
    light_on_dark: bool = False,
    min_score: float = GLYPH_MATCH_MIN_SCORE,
) -> Readout:
    """在 ``box`` 里逐字识别一个非负整数；任一位认不出就整串弃权。

    ``box`` 是 ``(x, y, w, h)``，用**竖屏 1080x1920** 口径。
    """
    x, y, width, height = box
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return Readout(None, 0.0, "空区域")

    mask = binarize(patch, light_on_dark=light_on_dark)
    found = glyph_boxes(mask)
    if not found:
        return Readout(None, 0.0, "没切到字形")
    if len(found) > GLYPH_MAX_COUNT:
        return Readout(None, 0.0, f"字形过多({len(found)})")

    text = ""
    worst = 1.0
    for glyph_box in found:
        glyph = normalize_glyph(mask, glyph_box)
        best_digit, best_score = None, -1.0
        for digit, template in glyphs.items():
            score = glyph_score(glyph, template)
            if score > best_score:
                best_digit, best_score = digit, score
        if best_digit is None or best_score < min_score:
            return Readout(None, max(best_score, 0.0), f"第{len(text) + 1}位认不出")
        text += str(best_digit)
        worst = min(worst, best_score)

    return Readout(int(text), worst, f"{len(found)} 位")


def read_pair(
    screen: np.ndarray,
    region: tuple[int, int, int, int],
    glyphs: dict[int, np.ndarray],
    *,
    light_on_dark: bool = False,
    min_score: float = GLYPH_MATCH_MIN_SCORE,
) -> Readout:
    """读 ``x/y`` 这种分数，返回 ``(x, y)``；读不出返回 ``None``。

    做法：区域内应当切出**恰好 3 个**组件（数字、斜杠、数字），认第 1 和第 3 个，
    **中间的斜杠按位置跳过**（它本来也不是数字，不必去认）。

    ⚠️ 曾经走的是「整串模板」（把 ``3/3`` 整串裁一张原尺寸小图逐像素比）。
    2026-10-06 在全部真机帧上实测：**整串 11/13、字形 19/19**，挂掉的两例都是
    「同一串字 A 帧认得出、B 帧认不出」—— 网页对不同排版位置会重新栅格化，
    原尺寸比对这个亚像素差异很敏感，而高度归一化的字形读法天然免疫。
    用户当天拍板改用字形读法。整串那套代码与模板仍保留（``read_string`` /
    ``load_string_templates``），但**不在生产路径上**。
    """
    x, y, width, height = region
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return Readout(None, 0.0, "空区域")

    mask = binarize(patch, light_on_dark=light_on_dark)
    found = glyph_boxes(mask)
    if len(found) != 3:
        return Readout(None, 0.0, f"应当切出 3 个组件，实际 {len(found)} 个")

    digits: list[int] = []
    worst = 1.0
    for index, glyph_box in enumerate((found[0], found[2])):
        glyph = normalize_glyph(mask, glyph_box)
        best_digit, best_score = None, -1.0
        for digit, template in glyphs.items():
            score = glyph_score(glyph, template)
            if score > best_score:
                best_digit, best_score = digit, score
        if best_digit is None or best_score < min_score:
            return Readout(
                None,
                max(best_score, 0.0),
                f"{'前' if index == 0 else '后'}一个数字认不出（{best_score:.3f}）",
            )
        digits.append(best_digit)
        worst = min(worst, best_score)

    return Readout((digits[0], digits[1]), worst, "字形×2")


def read_string(
    screen: np.ndarray,
    region: tuple[int, int, int, int],
    templates: dict[str, np.ndarray],
    *,
    light_on_dark: bool = False,
    min_score: float = STRING_MIN_SCORE,
    min_margin: float = STRING_MIN_MARGIN,
) -> Readout:
    """**备用路径**（不在生产上）：在 ``region`` 里找**整串**模板（如 ``1/2``、``3/3``）。

    取「最高分且过阈、且比次高分领先 ``min_margin``」的那一串；否则弃权。
    ⚠️ 领先优势是必需的：``0/1`` 与 ``0/2`` 只差最后一位，光看绝对分两者都会过阈。

    ⚠️ 之所以闲置：原尺寸逐像素比对对**网页重新栅格化**（排版位置的半像素差异）
    很敏感，跨帧实测 11/13。它唯一的长处是**不需要字模**，所以保留 —— 万一将来
    某个页面出现「排版完全固定、连续多帧一模一样」的场景，它可以顶上。
    """
    if not templates:
        return Readout(None, 0.0, "没有整串模板")

    x, y, width, height = region
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return Readout(None, 0.0, "空区域")
    mask = binarize(patch, light_on_dark=light_on_dark).astype(np.float32)

    scored: list[tuple[float, str]] = []
    for text, template in templates.items():
        if template.shape[0] > mask.shape[0] or template.shape[1] > mask.shape[1]:
            continue
        score, _location = best_match(mask, template.astype(np.float32))
        value = float(score)
        if np.isfinite(value):
            scored.append((value, text))
    if not scored:
        return Readout(None, 0.0, "模板比区域还大")

    scored.sort(reverse=True)
    best_score, best_text = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < min_score:
        return Readout(None, best_score, "最高分没过阈")
    if best_score - runner_up < min_margin:
        return Readout(None, best_score, f"和次高「{scored[1][1]}」分不开")
    return Readout(best_text, best_score, f"整串(次高 {runner_up:.3f})")
