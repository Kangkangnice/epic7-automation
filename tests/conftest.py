"""测试夹具解码缓存（只影响测试运行速度，生产代码完全不经过这里）。

问题：全量跑里同一张截图夹具会被反复**完整解码**。实测最热的一张
（`epic7_hero/list_no_reddot.png`）被 `cv2.imread` 读了 73 次，
`epic7_story/stage.png` 被 PIL 打开 38 次，而 `tests/fixtures` 下的截图单张就有 4~5MB。
整轮下来光这一步：cv2 侧约 36 秒 + PIL 侧约 45 秒 ≈ 全量的 19%。

做法：按「路径 + 读图参数 + 文件 (mtime, 大小)」缓存解码结果，并且
**每次调用都返回一份副本**。调用方拿到的仍然是一个独立、可以随便修改的对象，
跟每次真读盘的可观察行为一致（谁改了数组都不会串到别人）；文件被改写
（mtime 或大小变化）会自动重新解码，不会读到旧内容。

为什么不会改变测试结果：`cv2.imread` 本来每次就返回一个新数组、
`Image.open` 本来每次就返回一个新对象；这里只是把「解码」这一步省掉，
返回值仍是新对象。解码失败时原样退回真实调用，报错的时机与类型都不变。

内存：用 `lru_cache(maxsize=...)` 只留最近用过的若干张（每张约 6.7MB），
不会把整个 fixtures 目录（216 张 / 453MB）都常驻。

排查用：设 ``EPIC7_TEST_FIXTURE_CACHE=0`` 即可关掉，恢复成每次真读盘。

同一套理由还用在**模板匹配的结果**上（核心开关在 ``core/matcher.py`` 的
``MATCH_CACHE_ENABLED``）：全量测试里「同一块画面 + 同一个模板」会被重复匹配上千次
（实测重复率 88%~94%），打开后 ``test_navigation.py`` 从 122.7 s 降到 67.7 s。
它默认关闭、由本文件打开；排查用 ``EPIC7_MATCH_CACHE=0`` 关掉，回到「每次都真算」。
"""

from __future__ import annotations

import os
from functools import lru_cache

import cv2
from PIL import Image

# ⚠️ 这里要 import 项目模块：匹配结果缓存的核心开关在 core/matcher.py（见文件末尾）。
from auto_game_unified.core import matcher

# 每张整屏夹具解码后约 6.7MB，这里按张数封顶（两个通道合计约 0.5GB 上限）。
_CACHE_ENTRIES = 40

_REAL_IMREAD = cv2.imread
_REAL_OPEN = Image.open


def _stamp(path) -> tuple[int, int] | None:
    """文件的 (mtime_ns, 大小)；不是真实文件（如 BytesIO）返回 None 表示不缓存。"""
    try:
        info = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=_CACHE_ENTRIES)
def _decode_bgr(path: str, flags: int, stamp) -> object:
    # stamp 只作为缓存键的一部分参与：文件一变就换成另一条，旧条目由 LRU 淘汰。
    return _REAL_IMREAD(path, flags)


@lru_cache(maxsize=_CACHE_ENTRIES)
def _open_loaded(path: str, stamp) -> Image.Image:
    image = _REAL_OPEN(path)
    image.load()  # 立刻解码，这样缓存下来的是像素而不只是文件头
    return image


def cached_imread(path, flags=cv2.IMREAD_COLOR):
    stamp = _stamp(path)
    if stamp is None:
        return _REAL_IMREAD(path, flags)
    image = _decode_bgr(os.fspath(path), int(flags), stamp)
    return None if image is None else image.copy()


def cached_open(path, mode="r"):
    stamp = _stamp(path)
    if stamp is None:
        return _REAL_OPEN(path, mode)
    try:
        return _open_loaded(os.fspath(path), stamp).copy()
    except Exception:
        # 解码失败：退回真实调用，让报错发生在原来那个时机。
        return _REAL_OPEN(path, mode)


if os.environ.get("EPIC7_TEST_FIXTURE_CACHE", "1") != "0":
    cv2.imread = cached_imread
    Image.open = cached_open

# 匹配结果缓存：只影响测试进程，生产实跑不经过这里（见 core/matcher.py 的注释）。
if os.environ.get("EPIC7_MATCH_CACHE", "1") != "0":
    matcher.MATCH_CACHE_ENABLED = True
