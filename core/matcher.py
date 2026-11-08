import hashlib
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


# 本进程服务的窗口后端。生产由 ``main.py`` 在启动时按 ``--window-backend``
# 声明一次；未经声明时保持 "pc"，让既有离线工具与测试沿用原来的兜底行为。
# PC 专属的识别兜底（低通 / 扫尺寸）只在 PC 下启用，模拟器一律走原样口径。
ACTIVE_BACKEND = "pc"


def set_active_backend(backend: str) -> None:
    """声明本进程服务哪个后端；模拟器下关闭全部 PC 专属识别兜底。"""
    global ACTIVE_BACKEND
    ACTIVE_BACKEND = backend


@dataclass(frozen=True)
class Match:
    center: tuple[int, int]
    score: float
    # 命中所用的模板缩放比例（1.0 = 原尺寸）。诊断要能说清「是在哪一档尺子上
    # 认出来的」—— 只报分数的话，「分数=0.94」到底是画面变了还是尺子换了，
    # 事后完全看不出来。
    scale: float = 1.0


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
# ── 「同一块 UI 被另一个客户端换个画法」的兜底口径 ─────────────────────────────
#
# PC 客户端与模拟器里的画面**位置一致、尺寸一致**（实测落点差 1~2 像素），
# 但同一颗按钮的**像素级刻画方式**不同（抗锯齿 / 栅格化取整），差异全部挤在
# 文字笔画那一圈薄边上 —— 那圈边只占 1%~13% 的像素，其中约一半差得很大。
# 于是同一张模板在 PC 上会从 1.000 掉到 0.58~0.84（2026-11-01 实测）。
#
# 两端同时轻微低通（高斯）能把这些高频差别抹平，分数显著回升，
# 这也是自动化圈里成熟的做法（「给模板做 0.5~1 像素模糊以模拟抗锯齿」）。
#
# ⚠️ **不要把它当成默认口径**：模糊会同时抬高「冒牌货」的分数
# （实测「退出确认弹窗」被抬到 0.843，比 PC 真机的 0.839 还高）。
# 所以它只能**逐锚点、且以「原样不过阈才补一次」的方式**启用，
# 启用前必须跑全库夹具扫描确认「漏掉真页 / 放进冒牌」都是 0。
MATCH_MODE_SMOOTH = "smooth"
MATCH_MODES = (MATCH_MODE_RAW, MATCH_MODE_WHITE_MASK, MATCH_MODE_SMOOTH)
WHITE_PIXEL_THRESHOLD = 200
# 为什么是 **2.0**（2026-11-01 逐档实测，真值 = 308 张夹具上原样口径的结论）：
#   * 1.3 时「开始战斗」只有 0.879（阈 0.90）—— 救不动；
#   * 2.0 时它到 **0.939**，且**翻转数 0**；
#   * **2.5 起就有翻转**（「选择队伍」那两张会被误放进来），3.0 更是放到 14 张。
# ⇒ 2.0 是唯一「既够用又零翻转」的档位，**别再往上调**。
SMOOTH_SIGMA = 2.0


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


# ── 「原样不过阈，才用低通补一次」的锚点名单（**分层共用同一把尺子**）──────────
#
# 名单里的名字是**锚点名**，不是模板名：导航层叫 ``arena_ready``、竞技场路线叫
# ``list_ready``，指的都是同一张图，所以两个名字都要在（差一个就会长出
# 「导航认得出、跑起来认不出」的第二种说法 —— 2026-11-01 真踩过）。
#
# ⚠️ 想加名字进来，必须先用全库夹具证明「漏掉真页 = 0、放进冒牌 = 0」，
#   并把护栏测试里的名单一起改掉（见 ``tests/test_navigation.py``）。
#
# 现有五颗的实测依据（308 张夹具，真值 = 原样口径的判定结果，**σ=2.0**）：
#   ``lobby_arena`` 0.794→0.872（阈 0.82）· ``arena_ready``/``list_ready`` 0.841→0.977（阈 0.88）
#   ``challenge``  0.877→0.939（阈 0.90）· ``battle_start`` 0.711→0.939（阈 0.90）
#   —— 五颗**翻转数都是 0**；``lobby_battle`` 仍是反例，不许加。
#
# ``confirm``（2026-11-01 补入，PC 实跑两次都卡在它）：
#   PC 结算帧原样 0.864 / 0.871（阈 0.90）→ σ=2.0 下 0.970 / 0.976。
#   全库审计（12 条路线里 confirm 原子仅此一颗；308 张夹具，find_best_template
#   权威口径）：漏掉真页 0；唯一升过阈的是 ``epic7_fodder/results.png``
#   （0.8955→0.9073），它是粮坑路线**自己的战斗结算页**、右下角是同一个
#   「确认」按钮 —— 与**原样口径下本来就过阈**的 ``epic7_side_story/results.png``
#   （0.9138）同类，且 ``arena.py`` 头注早有先例（「远征结算页也会命中这一条，
#   但不影响运行」）。故这 1 次数值翻转是**同类页面并入**，不是放进冒牌。
SMOOTH_FALLBACK_ANCHORS: frozenset[str] = frozenset(
    {
        "lobby_arena",   # 判大厅
        "arena_ready",   # 导航层对「对手列表」的叫法
        "list_ready",    # 竞技场路线对同一张图的叫法
        "challenge",     # 已选中对手（阈 0.90，PC 原样 0.877）
        "battle_start",  # 队伍选择页的「开始战斗」（阈 0.90，PC 原样 0.711）
        "confirm",       # 结算页「确认」（阈 0.90，PC 原样 0.864/0.871，σ=2.0 → 0.97+）
    }
)


# ── 「同一块 UI 画小了一点点」的兜底：模板缩放扫描 ─────────────────────────────
#
# 与上面的低通口径**是两回事**，别混：低通修的是「同一尺寸、像素刻画不同」；
# 这里修的是「整块 UI 的物理尺寸就不一样」。
#
# 2026-11-04 彻夜实跑踩到：PC 客户端**两次启动之间**，同一颗按钮的像素尺寸会变
# （`战斗开始` 476x69 → 461x67，即 ×0.9685）。`TM_CCOEFF_NORMED` 归一化的是
# 亮度均值，**不归一化尺度** —— 差 2% 就能把 1.0000 打到 0.6448。
# 实测（模板按下面每一步重采样，同一帧同一区域）：
#
#   锚点                真值档  ×1.00    ×0.99    ×0.98    备注
#   ----------------    ------   ------   ------   ------
#   ``card_hint``       1.00     0.9998   0.8576   0.6661   23:44 帧
#   ``card_hint``       0.98     0.6448   0.7738   0.9404   00:12 帧 ← 同一锚点两档真值
#   ``card_decide``     1.00     1.0000   0.9618   0.9391
#   ``card_decide``     0.98     0.8974   0.9563   0.9808
#
# ⇒ **没有任何单一缩放能同时服务两档**（`card_hint` 在 0.99 上是 0.8576/0.7738，
# 两边都不过阈）。所以只能「原样先比，不过阈才扫一遍尺寸，取最高分」。
#
# ⚠️ 与低通一样，扫尺寸也会抬高**冒牌货**的分数（多试几个假设，总有蒙对一点的）。
# 因此名单**必须逐锚点登记**，加名字前必须先用全库夹具证明
# 「漏掉真页 = 0、放进冒牌 = 0」，并把护栏测试（``tests/test_navigation.py``）
# 里的名单一起改掉。
SCALE_FALLBACK_ANCHORS: frozenset[str] = frozenset(
    {
        # ── 月塔 ────────────────────────────────────────────────────────────
        # 「准备战斗」页。2026-11-04 00:05 实跑卡在这两颗上。
        "team_battle_start",
        "prepare_title",
        # 「三选一装置」页。2026-11-03 23:44 / 11-04 00:12 两档真值。
        "card_hint",
        "card_decide",
        # 战斗失败页 / 打满 25 层的终点屏 / 赛季入口标题：三颗都是纯文字模板，
        # 平台半宽只有 ±0.00~0.01（`tools/report_scale_margin.py`）。
        "battle_failed",
        "conquer_title",
        "season_tower_title",
        # ── 主线 ────────────────────────────────────────────────────────────
        "stamina_material",  # ±0.01
        "next_stage",        # ±0.02
        # ── 迷宫 ────────────────────────────────────────────────────────────
        "battle_turn_bar",     # ±0.01
        "lobby_episode_menu",  # ±0.02
        # ── 月光剧场 ────────────────────────────────────────────────────────
        "battle_clear",        # ±0.01
        "entry_card",          # ±0.02
        "reward_popup_close",  # ±0.02
        # 「进行观览」（分集页唯一的页面判据）。2026-11-06 21:42 真机：
        # PC 上原样 white_mask **0.7658**（阈 0.80，差 0.034）⇒ 分集页认不出 ⇒
        # 点「入场」后转场永不成立、重试 4 次失败。同一帧 ×1.02 → **0.8504**。
        # 白字包围盒实测 123x30 vs 模板 120x29（×1.025/×1.035）—— 正是「同一块 UI
        # 画大了一点点」，与 ``card_hint`` 那两颗同一种病。
        # ⚠️ 不能改走 raw：raw 在这帧 0.8636 能过，但它在「观览指南 / 购买门票 /
        # 获得奖励」三张压暗弹窗帧上是 0.974~1.000 ⇒ 页面排他性当场破掉。
        # 反例：同一颗在模拟器 ``episode_fresh`` 上 ×1.02 只有 0.5859，不放冒牌。
        "watch_button",        # ±0.03
        # ── 世界首领战 ──────────────────────────────────────────────────────
        "result_title",       # ±0.02
        "team_select_title",  # ±0.02
        "worldboss_title",    # ±0.02
        # ── 跨路线共用 ──────────────────────────────────────────────────────
        # 右上角「自动战斗已关闭」：月塔 / 竞技场 / 主线三处共用同一张图、同一套
        # 判据。它只有 0.9214 对阈 0.85（余量 0.07），平台半宽 ±0.02 —— 三处里
        # 任何一处漂移都会让「自动战斗没开」判不出来，进而**整场战斗不点自动**。
        "auto_off",
        # ── 导航层：大厅主锚点（「Episode / 支线故事」那条横幅）──────────────
        #
        # ⚠️ 这颗不是「可选优化」，它是 **2026-11-04 00:09 那场 120 秒超时的正主**。
        # 真实事故链：PC 上这颗只有 **0.7937**（阈 0.80，差 **0.0063**）⇒
        # `navigator.observe()` 报 `unknown` 而不是 `lobby` ⇒ 回家流程认不出到家了
        # ⇒ 去点右上蓝四格 ⇒ 菜单打开后判 `quick_menu`、但找不到酒馆 ⇒ 按 ESC 关菜单
        # ⇒ 又是 `unknown` ⇒ 再点四格 …… 死循环烧完 120 秒预算，报
        # 「返回首页失败」，**整条每日任务从这里中止，后面 8 条路线一条都没跑**。
        # 扫尺寸后同一帧 ×0.97 = **0.8718**，`observe` 直接报 `lobby`。
        # 全库审计（335 张夹具）：原样过阈 13 张，被扫尺寸抬过阈 **0 张**。
        "lobby_story",
    }
)
# 扫描档位（**不含 1.00** —— 原尺寸由常规路径先比掉了）。
# 步长取 0.01 而不是 0.02：上面那张表已经证明 0.02 的偏差足以把分数打到阈下，
# 粗一档就等于扫了个寂寞。范围取 **±3%**：实测漂移最大的一处是 476x69 → 461x67，
# 即 ×0.9685（−3.15%）—— 只扫 ±2% 会在最坏那一档上刚好扫不到。
SCALE_FALLBACK_STEPS: tuple[float, ...] = (0.97, 0.98, 0.99, 1.01, 1.02, 1.03)



def best_match_with_fallback(
    name: str,
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
    *,
    mode: str = MATCH_MODE_RAW,
) -> Optional[Match]:
    """按上面的口径取**最高分**（不按阈值过滤）—— 诊断要看真实分数时用这个。

    ⚠️ 诊断包里若把「没过阈」写成 ``score=None``，会被误读成「模板文件不见了」
    （本项目里 ``score=None`` 就是这个含义），所以诊断必须拿得到分数。

    ``mode`` 是**首选**口径（默认原样）。兜底只在这条首选口径不过阈时才追加：
    先按 `SMOOTH_FALLBACK_ANCHORS` 换口径，再按 `SCALE_FALLBACK_ANCHORS` 扫尺寸。
    两个名单都不含的锚点 ⇒ 这里退化成「一次原样匹配」，与从前逐字节一致。
    """
    best = find_best_template(
        screen,
        template,
        region=region,
        reference_size=reference_size,
        mode=mode,
    )
    # 过了阈就收工：热路径（绝大多数帧）仍然只有一次匹配，兜底不付钱。
    if best is not None and best.score >= threshold:
        return best

    pc = ACTIVE_BACKEND == "pc"
    smooth = pc and name in SMOOTH_FALLBACK_ANCHORS
    scales = (
        SCALE_FALLBACK_STEPS
        if pc and name in SCALE_FALLBACK_ANCHORS
        else ()
    )
    retries: list[tuple[str, float]] = []
    if smooth:
        retries.append((MATCH_MODE_SMOOTH, 1.0))
    if scales:
        # 尺寸与口径是**两个正交维度**：同一个口径下换个尺子，和换个口径量同一把尺子，
        # 都要试。两维同时登记时把组合补齐，别只试一半。
        for scale in scales:
            retries.append((mode, scale))
            if smooth:
                retries.append((MATCH_MODE_SMOOTH, scale))
    for retry_mode, scale in retries:
        candidate = find_best_template(
            screen,
            template,
            region=region,
            reference_size=reference_size,
            mode=retry_mode,
            template_scale=scale,
        )
        if candidate is not None and (best is None or candidate.score > best.score):
            best = candidate
    return best


def locate_with_fallback(
    name: str,
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
    *,
    mode: str = MATCH_MODE_RAW,
) -> Optional[Match]:
    """定位一个锚点：**先按原样比，没过阈才用低通 / 扫尺寸补，取较高者**。

    为什么必须是「原样优先」而不是直接换口径：原样能认出来的那些画面，
    判定结果要与从前一字不差 —— 这是「模拟器零改动」的结构性保证。
    低通只是给「另一台客户端把同一块 UI 换了个画法」留的活口，
    扫尺寸是给「另一台客户端把同一块 UI 画小了一点点」留的活口。

    ⚠️ 三个打分入口（导航 / 路线 / 诊断）**必须都走这里**：只改一处就会出现
    「诊断报未命中、实跑却过了」或反之，日志自己跟自己打架。
    """
    match = best_match_with_fallback(
        name,
        screen,
        template,
        threshold,
        region=region,
        reference_size=reference_size,
        mode=mode,
    )
    # ⚠️ 与 ``find_template`` 同语义：**不过阈就是没有**，不许返回一个低分匹配回去
    # （否则 `_visible()` 这类只看「是不是 None」的调用会全部变成 True）。
    if match is None or match.score < threshold:
        return None
    return match


def _prepare(image: np.ndarray, mode: str) -> np.ndarray:
    """按 ``mode`` 把图像变成可比对的形态。

    ⚠️ 未登记的模式**直接抛错**，不许静默退回原样：那等于判据悄悄换了口径而
    阈值没跟着改，是本项目最忌讳的那类「静默降级」。
    """
    if mode == MATCH_MODE_RAW:
        return image
    if mode == MATCH_MODE_WHITE_MASK:
        return white_mask(image)
    if mode == MATCH_MODE_SMOOTH:
        return cv2.GaussianBlur(image, (0, 0), SMOOTH_SIGMA)
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
    template_scale: float = 1.0,
) -> Optional[Match]:
    """Return the highest-scoring template position without applying a threshold.

    ``reference_size`` is the image size used to create the template.  When the
    emulator window is displayed at another uniform scale, both its templates
    and search region are scaled to the live capture before matching.

    ``template_scale`` is an **extra** resampling of the
    template on top of that — it exists because the PC client draws the same
    widget at a slightly different physical size between sessions (see
    ``SCALE_FALLBACK_ANCHORS``).  Only the template is rescaled; ``region``
    is in canvas coordinates and must **not** follow it.

    ``mode`` selects the comparison domain (see ``MATCH_MODE_*``); it is applied
    to the already-cropped, already-resized pair.
    """
    scale_x = scale_y = float(template_scale)
    if reference_size is not None:
        canvas_x = screen.shape[1] / reference_size[0]
        canvas_y = screen.shape[0] / reference_size[1]
        if abs(canvas_x - canvas_y) > 0.02:
            raise RuntimeError("画面宽高比与模板基准不一致")
        scale_x *= canvas_x
        scale_y *= canvas_y
        if region is not None:
            region = (
                round(region[0] * canvas_x),
                round(region[1] * canvas_y),
                round(region[2] * canvas_x),
                round(region[3] * canvas_y),
            )
    # 一次重采样完成「基准换算 × 尺寸扫描」两个因子。
    # 分两步 resize 会把同一层插值糊两遍 —— 这几颗锚点全是细笔画文字，
    # 糊两遍正是它们最脆的地方。
    if reference_size is not None or scale_x != 1.0 or scale_y != 1.0:
        target_width = max(1, round(template.shape[1] * scale_x))
        target_height = max(1, round(template.shape[0] * scale_y))
        interpolation = cv2.INTER_AREA if scale_x < 1 else cv2.INTER_CUBIC
        template = cv2.resize(
            template, (target_width, target_height), interpolation=interpolation
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
        scale=float(template_scale),
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
