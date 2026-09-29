import hashlib
import os
from collections import OrderedDict
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


# ── 匹配结果缓存 ───────────────────────────────────────────────────────────────
#
# 「同一块搜索区 + 同一个模板」的匹配结果是**纯函数**：重复问一次不必再算一次。
#
# 为什么需要它（2026-09-30 实测，不是估算）：
#   * 单次匹配 1982x1132 要 102 ms；同一个模板限制在 400x200 的区域里只要 3.2 ms；
#   * 全量测试的墙钟时间里匹配占大头，而**同一查询的重复率高达 88%~94%** ——
#     ``tests/test_navigation.py`` 一个文件 18,575 次调用里只有 1,141 次是新的；
#   * 打开本缓存后该文件 122.7 s -> 67.7 s，命中率 93.9%，真正落回匹配引擎只剩 4.7 s；
#   * 取指纹的开销只有匹配的 **8%~12%**（整屏 11 ms 对 102 ms，小区域同样比例），
#     所以**不设面积门槛** —— 小到字形、大到整屏，缓存都是净赚。
#
# ⚠️ 两个刻意的设计，别改：
#   1. **默认关闭**，由 ``tests/conftest.py`` 打开（那里也写明了理由）。实跑时画面每帧
#      都在变，缓存几乎不会命中，只会白付指纹钱；收益全在离线测试那边。
#      这与 ``conftest`` 里那个截图解码缓存是同一套理由。
#   2. 只缓存 ``(分数, 位置)`` 这两个**极小**的值，**绝不**缓存 ``cv2.matchTemplate`` 的
#      返回数组 —— 那是 float32 结果图，整屏一次 8.5 MB。实测缓存它会让进程内存从
#      961 MB 涨到 4.1 GB、全量跑到一半开始换页，比不加缓存还慢（2026-09-30 踩过）。
MATCH_CACHE_ENABLED = False
MATCH_CACHE_SIZE = 20000
_MATCH_CACHE: "OrderedDict[bytes, tuple[float, tuple[int, int]]]" = OrderedDict()


def _match_key(search: np.ndarray, template: np.ndarray) -> bytes:
    """``(搜索区, 模板)`` 的内容指纹。

    ⚠️ 形状与 dtype 必须一起进指纹：只喂 ``tobytes()`` 的话，2x3 与 3x2 会撞成同一个键。
    ⚠️ 不要用 ``memoryview(...).cast()`` 这类只接受连续内存的写法 —— 搜索区往往是
    ``screen[y:y+h, x:x+w]`` 这样的**视图**（未必连续），``tobytes()`` 才是通用的。
    """
    digest = hashlib.blake2b(digest_size=16)
    digest.update(
        f"{search.shape}|{search.dtype.str}|{template.shape}|{template.dtype.str}".encode()
    )
    digest.update(search.tobytes())
    digest.update(template.tobytes())
    return digest.digest()


def best_match(search: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int]]:
    """在 ``search`` 里找 ``template`` 的最佳匹配 -> ``(score, (x, y))``，结果按内容缓存。

    ``search`` 必须是**已经裁好、已经按基准尺寸缩放好**的那一块；返回的坐标相对于
    ``search`` 的左上角，偏移由调用方自己加。
    """
    key: bytes | None = None
    if MATCH_CACHE_ENABLED:
        key = _match_key(search, template)
        cached = _MATCH_CACHE.get(key)
        if cached is not None:
            _MATCH_CACHE.move_to_end(key)
            return cached
    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    value = (float(score), (int(location[0]), int(location[1])))
    if key is not None:
        _MATCH_CACHE[key] = value
        if len(_MATCH_CACHE) > MATCH_CACHE_SIZE:
            _MATCH_CACHE.popitem(last=False)
    return value


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

    score, location = best_match(search, template)
    return Match(
        center=(offset_x + location[0] + width // 2, offset_y + location[1] + height // 2),
        score=score,
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


def find_all_templates(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float,
    *,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
    min_gap: int = 40,
) -> list[Match]:
    """找出区域内**所有**过阈的匹配，按分数从高到低返回。

    用途是「同一个模板在一屏里出现多次」的场合（例：骑士团捐赠的支援列表 ——
    每一行右侧都有一个一模一样的绿色「支援1个」按钮，而业务需要**逐个**点过去）。
    只拿 ``find_best_template`` 的话永远只能看到分数最高的那一个。

    ``min_gap`` 是非极大值抑制半径（基准画布像素）：与已选中的点距离小于它的
    候选会被丢掉，避免同一个按钮被沿边缘重复报出来。取值应当**小于两个真实
    实例的间距、大于模板自身尺寸**，否则会把相邻的两个真实实例误当同一个。
    """
    if reference_size is not None:
        scale_x = screen.shape[1] / reference_size[0]
        scale_y = screen.shape[0] / reference_size[1]
        if abs(scale_x - scale_y) > 0.02:
            raise RuntimeError("画面宽高比与模板基准不一致")
        template = cv2.resize(
            template,
            (
                max(1, round(template.shape[1] * scale_x)),
                max(1, round(template.shape[0] * scale_y)),
            ),
            interpolation=cv2.INTER_AREA if scale_x < 1 else cv2.INTER_CUBIC,
        )
        if region is not None:
            region = (
                round(region[0] * scale_x),
                round(region[1] * scale_y),
                round(region[2] * scale_x),
                round(region[3] * scale_y),
            )
        gap = max(1, round(min_gap * scale_x))
    else:
        gap = min_gap

    offset_x = offset_y = 0
    search = screen
    if region is not None:
        offset_x, offset_y, width, height = region
        search = screen[offset_y : offset_y + height, offset_x : offset_x + width]

    height, width = template.shape[:2]
    if search.shape[0] < height or search.shape[1] < width:
        return []

    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    work = result.copy()
    found: list[Match] = []
    while True:
        _, score, _, location = cv2.minMaxLoc(work)
        if score < threshold:
            break
        column, row = location
        found.append(
            Match(
                center=(offset_x + column + width // 2, offset_y + row + height // 2),
                score=float(score),
            )
        )
        work[
            max(0, row - gap) : row + gap,
            max(0, column - gap) : column + gap,
        ] = -1.0
    return found
