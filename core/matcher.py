import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    center: tuple[int, int]
    score: float


# 模板在进程内不会变，但同一个文件会被反复解码：全量测试里最热的
# 一张小图被加载上千次，每次都要重新读盘 + BGR->RGB。
# 用 (mtime_ns, size) 当版本号，文件被替换时会自动重新解码，
# 不会读到旧内容；模板总量很小（几十张、几 MB），缓存代价可忽略。
_TEMPLATE_CACHE: dict[str, tuple[tuple[int, int], np.ndarray]] = {}


def load_template(path: str) -> np.ndarray:
    """Load an image in RGB, matching PyAutoGUI screenshot arrays."""
    stamp: Optional[tuple[int, int]]
    try:
        info = os.stat(path)
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        stamp = None
    if stamp is not None:
        cached = _TEMPLATE_CACHE.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if stamp is not None:
        _TEMPLATE_CACHE[path] = (stamp, image)
    return image


def find_best_template(
    screen: np.ndarray,
    template: np.ndarray,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
) -> Optional[Match]:
    """Return the highest-scoring template position without applying a threshold.

    ``reference_size`` is the image size used to create the template.  When the
    emulator window is displayed at another uniform scale, both its templates
    and search region are scaled to the live capture before matching.
    """
    if reference_size is not None:
        scale_x = screen.shape[1] / reference_size[0]
        scale_y = screen.shape[0] / reference_size[1]
        if abs(scale_x - scale_y) > 0.02:
            raise RuntimeError("画面宽高比与模板基准不一致")
        target_width = max(1, round(template.shape[1] * scale_x))
        target_height = max(1, round(template.shape[0] * scale_y))
        interpolation = cv2.INTER_AREA if scale_x < 1 else cv2.INTER_CUBIC
        template = cv2.resize(template, (target_width, target_height), interpolation=interpolation)
        if region is not None:
            region = (
                round(region[0] * scale_x),
                round(region[1] * scale_y),
                round(region[2] * scale_x),
                round(region[3] * scale_y),
            )
    offset_x = offset_y = 0
    search = screen
    if region is not None:
        offset_x, offset_y, width, height = region
        search = screen[offset_y : offset_y + height, offset_x : offset_x + width]

    height, width = template.shape[:2]
    if search.shape[0] < height or search.shape[1] < width:
        return None

    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    return Match(
        center=(offset_x + location[0] + width // 2, offset_y + location[1] + height // 2),
        score=float(score),
    )


def find_template(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
) -> Optional[Match]:
    """Find a template when its highest score reaches ``threshold``."""
    best = find_best_template(
        screen,
        template,
        region=region,
        reference_size=reference_size,
    )
    if best is None or best.score < threshold:
        return None
    return best
