"""主线补星篇章卡片的候选选择与画布坐标。"""

from collections.abc import Callable, Iterable

import numpy as np

# 点篇章卡片正文的落点偏移（相对星标）。卡片是「星标在左上、正文在右下」。
# ⚠️ 右边缘的卡片常常只露出星标，卡片大半在画布外 ⇒ 落点会越界：
# 2026-11-10 12:21 实跑就是这么死的（星标 (1909,505) ⇒ 落点 (2059,595)，
# 被窗口层「拒绝在 PC 游戏渲染区外点击」判成致命错误，整条路线带走）。
# 落点越界的卡片**不许点**：它的满星判据区域也被画面裁掉了，读数不可信 ——
# 先右滚把它整张露出来，再判再点（见 `_episode_action`）。
CHAPTER_CLICK_DX = 150
CHAPTER_CLICK_DY = 90
# 滚到头仍只露出半张卡时的兜底落点：贴着画布内侧，落在卡片看得见的那部分上。
EDGE_CLICK_MARGIN = 20


def chapter_click_point(center: tuple[int, int]) -> tuple[int, int]:
    """星标中心 → 卡片正文的点击落点。"""
    return (center[0] + CHAPTER_CLICK_DX, center[1] + CHAPTER_CLICK_DY)


def point_in_screen(point: tuple[int, int], screen: np.ndarray) -> bool:
    """落点是否在画布内。

    窗口层对越界点击是**致命错误**（``拒绝在 PC/安卓渲染区外点击``），
    所以路线必须在**决策阶段**就把这种点排除掉，不能拿护栏当兜底。
    """
    height, width = screen.shape[:2]
    return 0 <= point[0] < width and 0 <= point[1] < height


def clamped_click_point(point: tuple[int, int], screen: np.ndarray) -> tuple[int, int]:
    """把越界落点贴回画布内侧（只用于「滚到头也只有半张卡」的兜底）。"""
    height, width = screen.shape[:2]
    x = min(max(point[0], EDGE_CLICK_MARGIN), width - 1 - EDGE_CLICK_MARGIN)
    y = min(max(point[1], EDGE_CLICK_MARGIN), height - 1 - EDGE_CLICK_MARGIN)
    return (x, y)


def choose_chapter_center(
    screen: np.ndarray,
    centers: Iterable[tuple[int, int]],
    checked: set[tuple[int, int]],
    is_full: Callable[[np.ndarray, tuple[int, int]], tuple[bool, str]],
) -> tuple[int, int] | None:
    """优先取首张可见未满卡；只剩裁边卡时记下最后一张，供调用方滚动复核。"""
    edge = None
    for center in centers:
        if center in checked:
            continue
        if not point_in_screen(chapter_click_point(center), screen):
            edge = center
            continue
        full, _ = is_full(screen, center)
        if not full:
            return center
    return edge
