"""配置离线回放的图像缓存、OpenCV 线程数和用例隔离。"""

from __future__ import annotations

import os

import cv2
import pytest
from PIL import Image

from auto_game_unified.core import matcher
from auto_game_unified.core import account
from auto_game_unified.tests.fixture_images import fixture_image_cache


if fixture_image_cache.budget_bytes:
    cv2.imread = fixture_image_cache.imread
    Image.open = fixture_image_cache.open

# 测试入口已经能并行 pytest 进程。每个进程内的小块匹配用单线程更快。
cv2.setNumThreads(1)

# 匹配结果缓存：只影响测试进程，生产实跑不经过这里（见 core/matcher.py 的注释）。
if os.environ.get("EPIC7_MATCH_CACHE", "1") != "0":
    matcher.MATCH_CACHE_ENABLED = True


@pytest.fixture(autouse=True)
def _isolate_account_env(monkeypatch):
    """账号是**进程级**环境变量，用例之间必须清干净。

    否则：某个用例走了一遍「整轮开跑顺手读账号」（``main._build_daily_probe_reading_account``），
    读到的昵称留在 ``os.environ`` 里；后面所有 ``save_countdown()`` 就会写到
    ``accounts/<那个名字>/`` 去 —— 单跑全绿、全量挂一片，典型的顺序依赖。
    ``monkeypatch`` 会在用例结束时把这两项恢复成「未设置」。
    """

    monkeypatch.delenv(account.ACCOUNT_ENV, raising=False)
    monkeypatch.delenv(account.ACCOUNT_RANK_ENV, raising=False)


@pytest.fixture(autouse=True)
def _isolate_matcher_backend():
    """每个用例都从「未经声明」的干净状态开始，把后端开关污染锁在用例内部。

    ``core/matcher.py::ACTIVE_BACKEND`` 是**进程级**开关：生产由
    ``main.py::run_mode()`` 在启动时按 ``window_backend`` 声明一次，单进程只服务
    一个后端。但集成用例（``test_main_story.py`` 等）会直接调 ``run_mode()``，
    默认 ``window_backend="emulator"`` 就把这个全局量留在 ``"emulator"`` 上；
    排在后面的 PC 专属用例（月塔扫尺寸兜底那两条）依赖默认 ``"pc"``，于是
    **单跑全绿、全量挂两条**。实测复现：``test_main_story.py +
    test_tower_evidence.py`` ⇒ 2 failed；中间夹一个会把开关重置回 ``"pc"`` 的
    ``test_matcher.py`` ⇒ 全绿 —— 典型的顺序依赖。

    所以每个用例前后都拨回默认 ``"pc"``（用例内部仍然可以随意调
    ``set_active_backend()`` 验证两种后端）。生产代码不受影响：本文件只在
    pytest 进程里加载。
    """
    matcher.set_active_backend("pc")
    try:
        yield
    finally:
        matcher.set_active_backend("pc")
