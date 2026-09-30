"""圣域收菜（``sanctuary``）路线的视觉证据档案。

本模块只放资源、区域、阈值和页面判据；业务决策在 ``games/epic7/sanctuary.py``。

## 这条路线要干什么（用户 2026-09-29 口述的业务流程）

```
大厅
  └ 左侧竖排菜单最上面那个「圣域」入口（在「光辉里程碑」上方，城墙堡垒图标）
      → 点进去
圣域主页（右侧三行入口：精灵之森 / 欧勒毕斯之心 / 炼金术师之塔）
  └ **本轮只做最上面那一行「精灵之森」**
精灵之森（三行材料：企鹅巢穴 / 精灵之泉 / 魔罗戈拉种植地）
  ├ 可领的行：整块是蓝的、白边框、在闪烁，左上角有红点，中间写着「领取奖励」
  │     → 点一下即领取完成，**弹出一个「…成长完成!」弹窗**（标题与物品图标每次都不一样）
  │     → 弹窗底部有「点击关闭」，点它关掉
  │     → 回到精灵之森，这一行变成倒计时（如 ``10:11:23``）、红点消失、整块变暗
  ├ 不可领的行：暗紫色、没有红点、中间是倒计时（如 ``96:08:55``）
  └ 领完所有可领的行 ⇒ 本轮收工 ⇒ 回家
```

用户原话（2026-09-29）：

> 「比如说我以这个企鹅巢穴为例，它的这个整个是蓝色的，然后白色的边框，然后有闪烁，
> 然后呢，左上角有红点，然后呢，中间有领取奖励4个字。那这样的时候，就说明是可以领取的。」

⚠️ 用户当时说「点完之后它就是一个很小的弹窗，**也不需要你点**」——
**实测与此不符**：弹窗不会自动消失（等了 6 秒亮度仍是 19.8/20.0），
底部明写「点击关闭」。所以路线必须自己把它点掉（``dismiss-claim``）。

## 判据为什么只用「领取奖励」四个字

用户列举的可领特征有五项（蓝底 / 白边框 / 闪烁 / 红点 / 领取奖励）。实测取舍：

- **闪烁**：12 帧连拍（间隔 0.4s）实测相邻帧差异 0.68~2.49、整幅亮度 53.29~54.86 脉动 ——
  它确实在闪，但**闪烁只把模板分数从 1.0000 压到 0.9744**（12 帧最低），代价可以接受，
  不需要为它做任何补偿。**那条「绝对阈值会被淡入骗」的教训在这里不适用**：
  模板匹配是零均值归一化的，闪的是底色亮度，不是形状。
- **红点**：是**通知角标**，与「能不能领」不是同一件事（玩家看过通知后它可能先消失，
  而「领取奖励」还在） ⇒ 拿它当**必需**条件会**漏领**。故只做**非必需**的旁证，
  不进任何判据。
- ⇒ 唯一判据 = 「领取奖励」四个字命中。**空档极大**：正例最低 0.9744、
  负例最高 0.5498（弹窗遮罩下、底下那行仍可领时）⇒ 阈值 0.80 双向余量 0.17 / 0.25。

⚠️ 模板**只截「领取奖励」四个字**，**不含两侧的 ✦ 星饰**（那对星饰是动态装饰，
截进来只会平白多一个变量）。

## 三行材料的位置（基准画布 1982×1132，实测）

药丸底 y 353..491 / 528..662 / 699..820，**行距 173**；「领取奖励」文字带：

| 行 | 材料 | 可用时文字带 (x, y) | 不可用时那一位写什么 |
|---|---|---|---|
| 1 | 企鹅巢穴 | 1505..1610, 430..461 | 倒计时（实测 ``10:11:23``） |
| 2 | 精灵之泉 | 1505..1610, 603..634 | 倒计时（实测 ``20:23:39``） |
| 3 | 魔罗戈拉种植地 | 1505..1610, 776..807 | 倒计时（实测 ``96:08:55``） |

⇒ 整条带子一次 ``find_all_templates`` 就能把「现在有几行可领」全找出来
（``claimable_rows``），行距 173 远大于非极大值抑制半径 60。

## 页面互斥的实测依据（本路线 30 张 1982×1132 真机帧 + 全库 275 张夹具扫描）

扫描工具：``runtime_logs/_sanctuary_cut_templates.py verify``（gitignore，需要时重建）。
⚠️ 它用 ``cv2.imread`` 读帧后**必须 BGR→RGB** 再喂 matcher —— 口径不一致会拿到假分数
（``load_template`` 返回 RGB，实测同类问题能把 1.0000 压到 0.87）。

| 锚点 | 区域（x,y,w,h） | 阈值 | 本路线正例最低 | 本路线负例最高 | **全库最高** |
|---|---|---|---|---|---|
| ``forest_row`` | (1650,280,280,70) | 0.80 | 0.9999 | 0.2411 | **0.3569** |
| ``forest_title`` | (60,55,300,95) | 0.80 | 1.0000 | 0.3806 | 0.6496 |
| ``claim_text`` | (1470,418,430,400) | 0.80 | **0.9744** | 0.5498 | 0.4157 |
| ``popup_close`` | (840,800,300,70) | 0.80 | 1.0000 | 0.2310 | ⚠️ **0.9999（不排他）** |

### ⚠️ ``sanctuary_title`` 被全库扫描否掉了（2026-09-29）

第一版把圣域主页的判据做成**左上角标题「圣域」**（76×60 的裁图）。全库扫描当场否掉：
``tests/fixtures/epic7_fodder/stage_3_7.png`` 那一页的标题叫「**圣域**最深处」，
前两个字**恰好就是「圣域」** ⇒ 2 字标题模板在那里得 **0.9784**（≥0.80）。

⇒ 换成 ``forest_row``（右侧第一行「精灵之森」的文字，129×36）：它只出现在这一页的这个
位置，全库最高 **0.3569**。**这条教训值得记住：短标题模板可能是别的标题的前缀。**
（标题类锚点要么带上足够的上下文，要么换成一个只此一处的控件。）

### ⚠️ ``popup_close`` 故意不排他：「点击关闭」是游戏通用控件

全库扫描里，``epic7_hero/reward_popup.png`` 与骑士团捐赠的两张「获得奖励」弹窗
都是 **0.9999** —— 它们是**同一个控件**（游戏的通用奖励弹窗底部固定写「点击关闭」）。

这不构成风险，理由与 ``knights_donation`` 的 ``reward_title`` 相同：
命中是**对的**（那确实是同一种控件），而且它的动作只是「把它点掉」，**无副作用**。
⇒ 它同时是「领取完成弹窗」这一页的判据与点击目标。

### 判定顺序：弹窗必须排在最前

弹窗**盖在**精灵之森页上、只是把底页压暗。实测弹窗开着时 ``forest_title`` 仍然
**0.9998**（≥0.80）—— 也就是说只靠 ``forest_title`` 分不出「弹窗开着」和「弹窗关着」。
所以 ``_PAGES`` 必须把 ``sanctuary.claim_popup`` 排在 ``sanctuary.forest`` **之前**
（真正的判定顺序在 ``games/epic7/sanctuary.py`` 的 ``_PAGE_STATES``，两处必须一致）。

⚠️ 顺带一个有用的副作用：弹窗开着时 ``claim_text`` 只有 **0.5498**（底页被压暗）
⇒ 即使顺序写错了、把弹窗判成精灵之森页，也不会误点「领取奖励」。

## 「照料」按钮（2026-09-30 新增，用户口述）

用户原话：

> 「第三行下面右下方有一个照料，照顾的意思，第三行的菜可以通过这个方法点击之后，
> 它可以加快它的生长，所以碰到这个量的话，跟其他一样，也点掉。他点的话，应该没有弹窗。」

实测位置：亮绿药丸 **x1604 y871 w247 h43**（中心 1727, 892），在第三行
「魔罗戈拉种植地」药丸下方偏右；**旁边（同一行左边）有一个计时器**：

| 帧 | 三行状态 | 计时器 | 照料按钮 |
|---|---|---|---|
| ``now0930``（2026-09-30 上午） | 三行全在倒计时 | ``00:00:00`` | **亮**（绿药丸 + 左上红点） |
| ``claim__00``（2026-09-29 晚） | 第 1/2 行可领 | ``00:22:10`` | 灰（暗药丸、无红点） |

⇒ 那是**冷却计时**：到 00:00:00 就是可照料。``(1/3)`` 数字**两态都是 1/3**
（实测），所以它**不是**可用信号 —— 也正因如此，模板按纪律把数字与红点**都切掉**。

### ⚠️ 「亮 / 灰」不能靠**绝对亮度**判（实测否掉）

第一版想用「按钮区域平均灰度 ≥ 阈值」：亮 **113.8** / 灰 **56.6**，看着能分。
但**这个差被背景污染**：圣域是 **3D 昼夜场景**，按钮药丸是**半透明**的
（放大对照可见灰态药丸能透出背后场景）。实测同一帧里拿一个**状态完全相同**的参照物
（第 3 行药丸，两帧都在倒计时）：它自己就差了 **+42.3** —— 也就是说那 57 点的差里，
**背景能解释 42 点**，只剩 15 点是按钮自己的状态。⇒ 白天冷却中的按钮可能量到 ~100，
**会被误判成「可点」**，而这是会真点下去的。**绝对阈值作废。**

### ✅ 改用「文字是不是白的」：模板匹配天生看不到，绝对亮度看得到

``TM_CCOEFF_NORMED`` 是**对比度归一化**的 ⇒ 对「形状一样、明度不同」的差别
**天然失明**（实测两态都 0.95~1.00，分不出来）。但文字**自身的颜色**是状态给的：

| 状态 | 「照料」文字峰值灰度 | 框内 >235 的像素占比 | 均值 |
|---|---|---|---|
| 亮（可照料） | **255**（纯白，饱和） | **15.92%** | 113.8 |
| 灰（冷却中） | **147**（灰） | **0.00%** | 56.6 |

⇒ 判据 = **框内近白像素占比**（``CARE_TEXT_WHITE_LEVEL`` / ``CARE_TEXT_WHITE_MIN_RATIO``）。
它与背景昼夜无关（说的是文字自己白不白），全库 293 张夹具扫下来**只有森林页亮态那一帧**
给出非零占比（其余 292 张全 0.00%）。

### ⚠️ 还没验证的两件事（写在这里，别装作不存在）

1. **「点一下没有弹窗」是用户的判断，我没有实点过**（用户 2026-09-30 明确
   「先别点，我自己来」）。所以动作的出口验收只能写「按钮由亮转灰」，而不是
   「弹窗出现/不出现」。**若实际会弹窗**，主循环会在 8 秒后用同一个坐标再点一次、
   最多 4 次，然后**响亮地失败**（留诊断 + 退出码 1）—— 不会悄悄跳过。
2. **亮态样本只有 1 帧**（``now0930``）。上表的 15.92% 是单点，没有方差数据；
   灰态有 10+ 帧（全 0.00%）。补法写在 ``docs/maintenance/sanctuary.md``。
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.matcher import Match, find_all_templates, find_template

from .common import AtomEvidence, EvidenceProfile, PageEvidence

REFERENCE_SIZE = (1982, 1132)

DEFAULT_THRESHOLD = 0.80

REGIONS = {
    # 圣域主页右侧第一行「精灵之森」。**身兼两职**：该页的页面判据 + 进入精灵之森页的点击目标。
    # ⚠️ 区域罩住三行入口的纵向范围（后续「欧勒毕斯之心」「炼金术师之塔」两条路线可复用本锚点，
    # 届时按各自的行再各裁一张）。本轮只认第一行，见 ``FOREST_ROW_Y``。
    "forest_row": (1650, 280, 280, 70),
    # 精灵之森页左上标题。
    "forest_title": (60, 55, 300, 95),
    # 三行材料「领取奖励」的整条带子。y 从 418 起（第 1 行文字带 430..461 之上留 12px），
    # 到 818 止（第 3 行文字带 776..807 之下留 11px）。
    "claim_text": (1470, 418, 430, 400),
    # 领取完成弹窗底部「点击关闭」。
    "popup_close": (840, 800, 300, 70),
    # 第三行「魔罗戈拉种植地」右下方的「照料」按钮：**区域罩住整颗药丸 + 余量**。
    # ⚠️ 它只当「这颗按钮在不在」的锚点；**「能不能点」另有一道判据**（近白占比），
    # 因为冷却中它仍然是同一颗按钮、只有变暗 —— 见 ``CARE_TEXT_WHITE_MIN_RATIO``。
    "care_text": (1540, 840, 400, 110),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

_PAGES = (
    # ⚠️ 弹窗必须排在 forest **之前**：它盖在精灵之森页上，而 forest_title 在弹窗下
    # 仍然命中（实测 0.9998），顺序反了会把弹窗那一帧判成精灵之森页。
    PageEvidence("sanctuary.claim_popup", required=("popup_close",)),
    PageEvidence("sanctuary.forest", required=("forest_title",)),
    # 圣域主页：**锚点在右侧第一行上，不在标题上**（标题「圣域」不排他，见模块 docstring）。
    PageEvidence("sanctuary.home", required=("forest_row",)),
)

# ⚠️ 这里**故意不放**「页面键 -> 中文名」的对照表：日志用的页面名由
# ``games/epic7/sanctuary.py::STATE_LABELS`` 独家所有，状态机的 ``source_page`` /
# ``target_pages`` 全部从它派生（``state_label``）。主循环的转场对账只做**字符串相等**，
# 两处各留一张表迟早会漂移 —— 漂移的表现是「转场永远验收不通过」而不是报错。

# ---- 三行材料的行中心（基准画布 y）------------------------------------------------
#
# 由「领取奖励」文字带的实测值推出（第 1/2/3 行文字带中心 445 / 618.5 / 791）。
#
# ⚠️ 这是**归行用的名义中心**，不是模板命中框中心的逐像素值：模板裁的是第 1 行
# 430..461 那 31px，命中框中心实测 445 / **619** / …（第 2 行比名义值多 1px，
# 是「文字带中心 618.5 取整方向」与「模板边框」的差异）。差 1px 无所谓，
# 因为归行容差是 80（见 ``CLAIM_ROW_TOLERANCE``），而**点击点一律用模板命中的
# ``match.center``，不用这里的值** —— 这里只服务于日志里的「第几行」。
#
# ⚠️ 这三行**位置固定、不会重排**（与骑士团捐赠的支援列表不同 —— 那个每支援一次
# 就重排、只能每轮重新认）。所以按 y 归行是安全的，日志里也据此写出「第 N 行」。
CLAIM_ROW_CENTERS = (445, 618, 791)
# 「这个命中属于哪一行」的纵向容差。取 80（< 行距 173 的一半 86.5），
# 既不会把相邻行并进来，也容得下模板自身的纵向浮动。
CLAIM_ROW_TOLERANCE = 80
# ``find_all_templates`` 的非极大值抑制半径（基准画布像素）。
# 模板 110×31、行距 173 ⇒ 60 既不会把同一次命中报两次，也不会把相邻两行并成一个。
CLAIM_MIN_GAP = 60

CLAIM_ROW_NAMES = ("第1行·企鹅巢穴", "第2行·精灵之泉", "第3行·魔罗戈拉种植地")

# ---- 「照料」按钮的可用判据 --------------------------------------------------------
#
# ⚠️ 为什么不用「按钮区域平均灰度 ≥ 某值」：实测亮 113.8 / 灰 56.6 看着能分，但圣域是
# 3D 昼夜场景、药丸半透明，同状态参照物（第 3 行药丸）自己就随背景差了 42.3 ⇒
# 那 57 点里背景能解释 42 点。**绝对亮度会把「白天 + 冷却中」误判成可点**，
# 而那是会真点下去的。完整推导见模块 docstring「照料按钮」一节。
#
# 改用「文字自己白不白」：亮态文字纯白（峰值 255，饱和），灰态是灰的（峰值 147）。
# 与 ``care_text`` 模板**同一块框**（x1622..1750 / y871..914，= x,y,w,h）；
# 模板切片见 ``runtime_logs/_sanctuary_cut_templates.py``。
CARE_BOX = (1622, 871, 128, 43)
CARE_TEXT_WHITE_LEVEL = 235
# 实测：亮 15.92% / 灰 0.00%（全库 293 张夹具里只有森林页亮态那一帧非零）。
CARE_TEXT_WHITE_MIN_RATIO = 0.02


def build_sanctuary_evidence(template_dir: Path) -> EvidenceProfile:
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


def claim_row_label(y: int) -> str:
    """把一个命中点 / 点击点的画布 y 归到「第几行」，用于日志。"""
    index = min(
        range(len(CLAIM_ROW_CENTERS)),
        key=lambda i: abs(CLAIM_ROW_CENTERS[i] - y),
    )
    return CLAIM_ROW_NAMES[index]


def claimable_rows(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    region: tuple[int, int, int, int] = REGIONS["claim_text"],
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Match]:
    """精灵之森页上**所有**还能领的行，按**从上到下**排序（业务上就是人点过去的顺序）。

    为什么不能只用 ``find_template``（永远只给最高分那一个）：
    一屏可能同时有两三行可领，而业务要一行一行点过去；而且各行的分数只差
    0.001~0.01、帧间还会抖动（实测第 1/2 行在 0.9733~1.0000 之间互相反超），
    按分数排会**在几行之间来回跳**。所以这里按 y 排序 —— 位置是恒定的。

    ⚠️ 返回的是**点击点**（模板命中框中心），直接可用于 ``runtime.click``。
    """
    hits = find_all_templates(
        screen,
        template,
        threshold,
        region=region,
        reference_size=reference_size,
        min_gap=CLAIM_MIN_GAP,
    )
    return sorted(hits, key=lambda match: (match.center[1], match.center[0]))


def find_claim_row(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    threshold: float = DEFAULT_THRESHOLD,
) -> Match | None:
    """只要**最上面那一行**可领的（``claimable_rows`` 的便捷包装）。"""
    rows = claimable_rows(
        screen,
        template,
        reference_size=reference_size,
        threshold=threshold,
    )
    return rows[0] if rows else None


def locate(
    screen: np.ndarray,
    template: np.ndarray,
    key: str,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    threshold: float | None = None,
) -> Match | None:
    """按 ``REGIONS[key]`` 定位一个单点锚点（页面判据 / 点击目标）。"""
    return find_template(
        screen,
        template,
        THRESHOLDS[key] if threshold is None else threshold,
        region=REGIONS[key],
        reference_size=reference_size,
    )


# ---- 「照料」按钮：在不在 + 能不能点 ------------------------------------------------


@dataclass(frozen=True)
class CareProbe:
    """某一帧上「照料」按钮的实测结果。

    ``match`` 是按钮的存在性（模板命中框，命中了就直接拿它的中心当点击点）；
    ``white_ratio`` 是「文字是不是白的」——**能不能点由它决定，不由模板分决定**
    （模板分是对比度归一化的，两态都 0.95~1.00，分不出来）。
    """

    match: Match | None
    white_ratio: float
    white_min: float = CARE_TEXT_WHITE_MIN_RATIO

    @property
    def present(self) -> bool:
        """按钮在不在（不看亮灰）。"""
        return self.match is not None

    @property
    def ready(self) -> bool:
        """能不能点：按钮在 **且** 文字是白的（不在冷却中）。"""
        return self.match is not None and self.white_ratio >= self.white_min


def _scale_region(
    region: tuple[int, int, int, int],
    screen: np.ndarray,
    reference_size: tuple[int, int] | None,
) -> tuple[int, int, int, int]:
    """把基准画布坐标的区域换算到实际画面上。

    ⚠️ 口径必须与 ``core.matcher`` 逐字一致（含宽高比校验），否则「模板在 A 处命中、
    亮度却在 B 处量」——那种错不会报错，只会让判据悄悄失准。
    """
    if reference_size is None:
        return region
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    if abs(scale_x - scale_y) > 0.02:
        raise RuntimeError("画面宽高比与模板基准不一致")
    return (
        round(region[0] * scale_x),
        round(region[1] * scale_y),
        round(region[2] * scale_x),
        round(region[3] * scale_y),
    )


def care_text_white_ratio(
    screen: np.ndarray,
    *,
    box: tuple[int, int, int, int] = CARE_BOX,
    level: int = CARE_TEXT_WHITE_LEVEL,
    reference_size: tuple[int, int] | None = REFERENCE_SIZE,
) -> float:
    """「照料」按钮框内**近白像素的占比**（0.0~1.0）。亮态 ≈0.16、冷却中 0.0。"""
    x, y, width, height = _scale_region(box, screen, reference_size)
    crop = screen[y : y + height, x : x + width]
    if crop.size == 0:
        return 0.0
    # ⚠️ 用 ``cv2.cvtColor`` 而不是手写加权：docstring 里那几个数（如峰值 255 / 147、
    # 占比 15.92%）就是用它量的，换算法等于换口径。
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    return float((gray > level).mean())


def probe_care(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    threshold: float = DEFAULT_THRESHOLD,
    white_min: float = CARE_TEXT_WHITE_MIN_RATIO,
    box: tuple[int, int, int, int] = CARE_BOX,
) -> CareProbe:
    """一帧上量全「照料」按钮：有没有 + 能不能点。"""
    match = find_template(
        screen,
        template,
        threshold,
        region=REGIONS["care_text"] if region is None else region,
        reference_size=reference_size,
    )
    ratio = care_text_white_ratio(
        screen,
        box=box,
        reference_size=reference_size,
    )
    return CareProbe(match=match, white_ratio=ratio, white_min=white_min)
