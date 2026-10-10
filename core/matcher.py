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


# ── 匹配模式：把「控件」从「背景」里抠出来 ──────────────────────────────────────
#
# ``TM_CCOEFF_NORMED`` 把模板的**背景**也一起算进相似度。同一个控件画在不同的
# 场景底图上，分数会掉到阈值以下 —— 判据「看着好好的」，其实已经失效，而且
# 失效方式很隐蔽：分数只是「低了一点」，不是报错。
#
# 实测（2026-10-09，`story/auto_off.png` 叠在月塔的深色书架底图上）：
#
#   ==========================  ==============  =============
#   同一帧 / 同一区域            原样比（raw）   白像素掩膜
#   ==========================  ==============  =============
#   月塔实跑事故帧 19:34          0.7492          0.9214
#   月塔实跑事故帧 13:59          0.7704          0.9214
#   月塔真机夹具                  0.7704          0.9214
#   竞技场真机帧（auto 关）        0.7953          0.9280
#   ==========================  ==============  =============
#
# 为什么「白色像素」是对的：右上那排图标（倍速 / 自动 / 聊天）是**纯白矢量图**，
# 背景是照片或渐变。把两侧都压成「哪些像素是白的」之后，留下的只有**控件形状**，
# 底图被抹平 ⇒ 判据与背景无关，同一条路线换场景、或新路线复用同一张模板都不必重裁。
#
# ⚠️ 白色下界取 200，**不要退回 180**。180 会把「亮灰底图」整片算成白色：
# 实测 `epic7_expedition/battle.png`（浅灰天空）同一帧 180 只剩 0.4085、
# 200 有 0.8347 —— 掩膜糊成一整块白，图标反而认不出来。亮场景下 180 等于瞎。
#
# ⚠️ 换口径**必须同时重定阈值**：两种口径的分数不在同一个量纲上（raw 的真阳性
# 可以低到 0.44，白掩膜的真阳性最低 0.92）。沿用旧门槛不是「保守」，是让判据
# 变成永假或永真。
MATCH_MODE_RAW = "raw"
MATCH_MODE_WHITE_MASK = "white_mask"
MATCH_MODES = (MATCH_MODE_RAW, MATCH_MODE_WHITE_MASK)
WHITE_PIXEL_THRESHOLD = 200


def white_mask(
    image: np.ndarray, threshold: int = WHITE_PIXEL_THRESHOLD
) -> np.ndarray:
    """把「近乎纯白的像素」抠成 0/255 单通道掩膜。

    三通道**都**要 >= ``threshold`` 才算白，而不是「灰度 > threshold」：亮但
    带色的像素（图标旁边的高光、浅色插画）不该混进形状里，否则掩膜会把底图
    的一部分也算成控件。

    返回单通道（``uint8``）—— 与输入的三通道 RGB 形状不同，所以两种口径的
    缓存指纹天然不会撞。
    """
    if image.ndim == 2:
        bright = image >= threshold
    else:
        bright = np.all(image[:, :, :3] >= threshold, axis=2)
    return bright.astype(np.uint8) * 255


def _prepare(image: np.ndarray, mode: str) -> np.ndarray:
    """按 ``mode`` 把图像变成可比对的形态。

    ⚠️ 未登记的模式**直接抛错**，不许静默退回原样：那等于判据悄悄换了口径而
    阈值没跟着改，是本项目最忌讳的那类「静默降级」。
    """
    if mode == MATCH_MODE_RAW:
        return image
    if mode == MATCH_MODE_WHITE_MASK:
        return white_mask(image)
    raise ValueError(
        f"未知的匹配模式: {mode!r}；可用: {', '.join(MATCH_MODES)}"
    )


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


def best_match(
    search: np.ndarray,
    template: np.ndarray,
    *,
    mode: str = MATCH_MODE_RAW,
) -> tuple[float, tuple[int, int]]:
    """在 ``search`` 里找 ``template`` 的最佳匹配 -> ``(score, (x, y))``，结果按内容缓存。

    ``search`` 必须是**已经裁好、已经按基准尺寸缩放好**的那一块；返回的坐标相对于
    ``search`` 的左上角，偏移由调用方自己加。

    ``mode`` 见模块顶部的常量注释；默认 ``raw`` ⇒ 既有调用方一个字节的行为都不变。
    二值化**发生在缩放与裁剪之后**：反过来先二值化、再让 ``INTER_AREA`` 缩放会把
    0/255 插值回灰阶，掩膜就糊了。
    """
    if mode != MATCH_MODE_RAW:
        search = _prepare(search, mode)
        template = _prepare(template, mode)
    key: bytes | None = None
    if MATCH_CACHE_ENABLED:
        key = _match_key(search, template)
        cached = _MATCH_CACHE.get(key)
        if cached is not None:
            _MATCH_CACHE.move_to_end(key)
            return cached
    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    if mode != MATCH_MODE_RAW:
        # 掩膜里「整块全黑」的窗口会让归一化分母为 0（0/0）⇒ OpenCV 给出 nan，
        # 而 nan 会把 minMaxLoc 整个带偏。二值口径下这种窗口的语义很明确：
        # 「一块白都没有」= 负样本，压到 -1.0。
        # 只在非原始口径上加这一步：raw 路径保持与原实现逐字节一致。
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
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
    *,
    mode: str = MATCH_MODE_RAW,
) -> Optional[Match]:
    """Return the highest-scoring template position without applying a threshold.

    ``reference_size`` is the image size used to create the template.  When the
    emulator window is displayed at another uniform scale, both its templates
    and search region are scaled to the live capture before matching.

    ``mode`` selects the comparison domain (see ``MATCH_MODE_*``); it is applied
    to the already-cropped, already-resized pair.
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

    score, location = best_match(search, template, mode=mode)
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
    *,
    mode: str = MATCH_MODE_RAW,
) -> Optional[Match]:
    """Find a template when its highest score reaches ``threshold``."""
    best = find_best_template(
        screen,
        template,
        region=region,
        reference_size=reference_size,
        mode=mode,
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
