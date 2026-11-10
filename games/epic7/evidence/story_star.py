# -*- coding: utf-8 -*-
"""主线补星的视觉证据（2026-11-09 真机验证后新建）。

## 这条路线为什么只有 PC 图

用户口径：素材只有 PC 端有，逻辑与模拟器共通，所以先按 PC 开发；模拟器以后
要用再补同名图。业务状态机（``games/epic7/story_star.py``）**不含平台分支**。

## 两个判据的来历（都是 2026-11-09 在同一批真机帧上量的）

### 1. 篇章卡片「是否满星」：比左右两串数字的形状，不识别具体数值

卡片左上角是 ``23/30`` 这种「已获得/总数」。满星的星标与未满的**外观完全一样**
（放大六倍对比过：颜色、亮度、形状都没有区别），唯一可用的是数字。

但不需要认识数字：**满星必然写成 ``A/A``，斜杠左右是同一串字形**。
于是按列投影切成字符块、取中间那块当斜杠、逐块比形状即可。

实测分布（同一帧六张卡片 + 另一帧五张）：

* 满星：0.987 / 0.988 / 0.963 / 0.982 / 1.000 / 0.829
* 未满：0.322 / 0.418 / 0.137 / 0.761

⇒ 阈值取 ``DIGIT_SIMILARITY_MIN = 0.75``：满星最低 0.829、未满最高 0.761，
两侧各留 0.06~0.08。**块数不是奇数直接判未满**（位数不同 ⇒ A≠B，不用比形状）。

⚠️ 必须先按行投影取「最长的连续非零行段」再切块。少了这一步时卡片下方的高光
会被算进最右那个字符、把它撑宽带歪，同一字形的相似度从 0.99 掉到 0.59
（切块宽度 13 而不是 10），实测踩过一次。

### 2. 小节「是否满星」：徽章右下角的绿色小勾

满星命中 1.0000，未满徽章最高 0.5376（同一区域、同一帧），阈值 0.80 很宽裕。

⚠️ 别把「有勾」理解成「已通关」：2026-11-09 真打了一关（星数 23→24、只加 1 星），
勾照样出现 —— 说明那一关原本是 2 星、打完补满 3 星。**勾就是满 3 星**
（与该关总星数 +1 并不矛盾）。这条当时差点被误读成「勾=通关」，靠算星数才纠正。
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
    # 左上「选取Episode」六字标题 —— Episode 面板的标识。
    "episode_title": (60, 60, 420, 110),
    # 左上那颗圆形「?」帮助按钮 —— 关卡列表页的标识（Episode 编号会变，它不变）。
    "stage_help": (340, 60, 120, 90),
    # 底部左起第三个图标（蓝色树状）—— 从关卡页打开时间轴面板的入口。
    "timeline_icon": (1355, 1005, 110, 90),
    # 队伍页右下「战斗开始」。⚠️ 与关卡页的「准备战斗」同一位置、只差文字，
    # 主线的 ``start_mission_updated`` 在这页只有 0.8011（阈 0.80，擦边）——
    # 所以补星自带一张 PC 覆盖图，实测 1.0000，关卡页最高 0.5842。
    "battle_start": (1500, 950, 420, 180),
    # 战斗画面右上角的固定 HUD（? / 倍速 / 自动 / 暂停）。裁图框是
    # (1370,55,250,95)，这里的搜索区四周各留 30~60 px，容纳客户端把 UI 画小
    # 约 3% 时的位移。只在共享战斗判据失手时用它补一句「这确实是战斗画面」。
    "battle_hud": (1310, 25, 370, 165),
}

THRESHOLDS = {
    "episode_title": 0.85,
    # Episode 1 的关卡页上实测 0.9687（换 Episode 会有细微渲染差），0.90 仍有余量。
    "stage_help": 0.90,
    "timeline_icon": 0.90,
    # 自身 1.0000 / 关卡页最高 0.5842。
    "battle_start": 0.85,
    # 白掩膜 + 尺寸扫描：真战斗帧最低 0.9596，补星链路的非战斗页最高 0.3137，
    # 全库 410 张可比夹具审计零冒牌（命中的都是同样带这组 HUD 的战斗/场景页）。
    "battle_hud": 0.85,
}

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

_PAGES = (
    # Episode 面板与关卡页是两页不同的东西：前者按篇章排版，后者按小节排版。
    PageEvidence("story_star.episode", required=("episode_title",)),
    PageEvidence(
        "story_star.stage_list", required=("stage_help", "timeline_icon")
    ),
)

# ---- 篇章卡片：星标定位 + 数字区形状比对 -----------------------------------
#
# 星标（卡片左上角的金色菱形）用模板定位，实测六张卡片全部 1.0000、
# 其他位置最高 0.738。数字区 = 星标中心 + 下面这组偏移（从真机帧量的）。
STAR_MARKER_OFFSET = (14, -16, 70, 38)  # (dx, dy, 宽, 高)
# 二值化门槛：数字是纯白（>=200），背景是深色半透明（<=120）。
DIGIT_BINARY_MIN = 190
# 切成字符块时，一列至少要有这么多白点才算「有内容」——抗锯齿会在字缝里留下
# 1 像素的噪声列，不滤掉会把同一字形切出不同宽度。
DIGIT_COLUMN_MIN_PIXELS = 2
# 字符块的合理尺寸（基准画布像素）：数字 7~13 宽、16~17 高；斜杠 7 宽、20 高。
DIGIT_BLOCK_WIDTH = (4, 14)
DIGIT_BLOCK_HEIGHT = (12, 26)
# 两个同字形块归一化互相关的下限。满星最低 0.829、未满最高 0.761（见模块 docstring）。
DIGIT_SIMILARITY_MIN = 0.75
# 块内归一化到多大再比：够大能保留笔画差异，又不至于对 1 像素抖动过敏。
DIGIT_SIGNATURE_SIZE = (20, 32)

# ---- 小节徽章的绿勾 ---------------------------------------------------------
# ⚠️ **勾有两种大小**：同一页里第 1 行那颗（被选中的行）明显大一圈，
# 其余行小一圈。单一模板只能覆盖其中一种 —— 2026-11-09 用大勾模板在
# 「4 个小节全满」的页面上只能找到 1 个勾，漏掉另外 3 个。所以两张候选模板
# 都要扫，任一命中即算「这一行满星」。
STAGE_CHECK_THRESHOLD = 0.85
# 两张候选互不命中：大勾在小勾页 0.50、小勾在大勾页 0.48，同为 1.0 只能命中自己那种。
STAGE_CHECK_TEMPLATES = ("stage_check", "stage_check_small")
# 两个候选点相距小于这个值就当同一个勾（去重用）。
STAGE_CHECK_MERGE_GAP = 24
# 小节列表区域：左侧一列徽章 + 右侧文字，只关心徽章那一竖条。
# 收窄到 x 95~150 是为了把「右侧故事栏的绿色元素」挡在外面（实测放宽会误命中）。
STAGE_LIST_REGION = (95, 330, 60, 690)
# 勾的搜索半径：同一行相邻小节竖直间距 150 px，取一半以下避免串行。
STAGE_ROW_MIN_GAP = 70
# 行网格：首行勾在 y=432、行距 150（04 图与 13 图实测一致，与「这一章几个小节」无关）。
STAGE_ROW_FIRST_FALLBACK = 432
STAGE_ROW_PITCH = 150
# 一行判定为「已满」的 y 容差。行距 150、行高约 100，给 45 足够容住自适应误差。
STAGE_ROW_TOLERANCE = 45


def build_story_star_evidence(template_dir: Path) -> EvidenceProfile:
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


def _scale_region(
    screen: np.ndarray,
    box: tuple[int, int, int, int],
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> tuple[int, int, int, int]:
    x, y, width, height = box
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    return (
        round(x * scale_x),
        round(y * scale_y),
        max(1, round(width * scale_x)),
        max(1, round(height * scale_y)),
    )


def _blocks(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """按列投影切出字符块 -> ``[(x1, x2, y1, y2), ...]``（相对传入的 band）。"""
    columns = (binary > 0).sum(axis=0)
    active = columns >= DIGIT_COLUMN_MIN_PIXELS
    spans: list[tuple[int, int]] = []
    inside = False
    start = 0
    for index, value in enumerate(active):
        if value and not inside:
            inside = True
            start = index
        elif not value and inside:
            inside = False
            spans.append((start, index))
    if inside:
        spans.append((start, len(columns)))

    result: list[tuple[int, int, int, int]] = []
    for start, end in spans:
        patch = binary[:, start:end]
        rows = (patch > 0).sum(axis=1)
        nz = np.nonzero(rows)[0]
        if len(nz) == 0:
            continue
        result.append((start, end, int(nz[0]), int(nz[-1]) + 1))
    return result


def _signature(band: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    start, end, top, bottom = box
    patch = band[top:bottom, start:end]
    resized = cv2.resize(
        patch, DIGIT_SIGNATURE_SIZE, interpolation=cv2.INTER_AREA
    )
    return (resized > 110).astype(np.float32)


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关 —— 比「像素一致率」宽容，单像素抗锯齿差异不会把同字形判成不同。"""
    value = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
    return max(0.0, value)


def chapter_is_full(
    screen: np.ndarray,
    marker_center: tuple[int, int],
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> tuple[bool, str]:
    """这张篇章卡片是否满星。返回 ``(是否满星, 说明)``。

    ``marker_center`` 是左上角星标的中心（画布坐标）。
    """
    dx, dy, width, height = STAR_MARKER_OFFSET
    box = _scale_region(
        screen,
        (marker_center[0] + dx, marker_center[1] + dy, width, height),
        reference_size,
    )
    x, y, w, h = box
    if x < 0 or y < 0 or x + w > screen.shape[1] or y + h > screen.shape[0]:
        return False, "数字区越界"
    patch = screen[y : y + h, x : x + w]
    if patch.size == 0:
        return False, "数字区为空"
    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, DIGIT_BINARY_MIN, 255, cv2.THRESH_BINARY)

    # 先取「最长的连续非零行段」= 数字所在那一行。不这么做时卡片下方的高光会被
    # 算进最右那个字符（见模块 docstring 的实测）。
    rows = (binary > 0).sum(axis=1)
    segments: list[tuple[int, int]] = []
    inside = False
    start = 0
    for index, value in enumerate(rows):
        if value > 0 and not inside:
            inside = True
            start = index
        elif value == 0 and inside:
            inside = False
            segments.append((start, index))
    if inside:
        segments.append((start, len(rows)))
    if not segments:
        return False, "数字区一片空白"
    top, bottom = max(segments, key=lambda item: item[1] - item[0])
    band = binary[top:bottom, :]

    raw = _blocks(band)
    blocks = [
        block
        for block in raw
        if DIGIT_BLOCK_WIDTH[0] <= block[1] - block[0] <= DIGIT_BLOCK_WIDTH[1]
        and DIGIT_BLOCK_HEIGHT[0] <= block[3] - block[2] <= DIGIT_BLOCK_HEIGHT[1]
    ]
    if len(blocks) < 3:
        return False, f"切不出足够字符块（原 {len(raw)}）"
    if len(blocks) % 2 == 0:
        # 位数不同 ⇒ 必然写不成 A/A ⇒ 一定不满，不用再比形状。
        return False, f"左右位数不同（{len(blocks)} 块）"

    half = (len(blocks) - 1) // 2
    scores = [
        _similarity(_signature(band, left), _signature(band, right))
        for left, right in zip(blocks[:half], blocks[half + 1 :], strict=False)
    ]
    worst = min(scores)
    detail = " ".join(f"{value:.3f}" for value in scores)
    if worst >= DIGIT_SIMILARITY_MIN:
        return True, f"满星 相似度={detail}"
    return False, f"未满 相似度={detail}"


def stage_is_full(
    screen: np.ndarray,
    check_points: list[tuple[int, int]],
    row_y: int,
    *,
    row_tolerance: int = 30,
) -> bool:
    """第 ``row_y`` 这一行的小节是否满星。

    ``check_points`` 是这一屏所有绿勾的中心（``find_all_templates`` 的结果），
    只要有一个落在这一行的 ``row_tolerance`` 范围内就算满。
    """
    for _x, y in check_points:
        if abs(y - row_y) <= row_tolerance:
            return True
    return False
