"""社区 H5（竖屏）的**页面判据**：把一帧竖屏画面判成「在哪一页」。

这条路线走的是 ``core/portrait.py`` 那条独立竖屏链路（1080x1920），
与横屏的 ``navigation.py`` 完全隔离，所以判据也单独一份，不要合并。

## ⚠️ 先读这段：社区 H5 是「叠层」的

实测（2026-10-06，真机帧池）兑换流程是这样叠上去的：

```
商品详情（栈根）
  └─ 订单确认页：几乎盖住整屏，只露底部一条**被压暗**的上一页
       └─ 兑换成功弹窗：x 260..820, y 731..997
```

**下层元素在上层依然可见（只是压暗），而 ``TM_CCOEFF_NORMED`` 对整体压暗几乎免疫**
（项目里早有记录：「×0.45 只掉到 0.9987」）。真机实测：

| 判据 | 来源页 | 在下层暴露处 |
| --- | --- | --- |
| 底部「立即兑换」按钮 | 1.0000 | **0.9587**（订单确认页 / 成功弹窗页） |
| 弹窗内「确认兑换」按钮 | 1.0000 | **1.0000**（成功弹窗页，它就在下面） |

⇒ **「立即兑换 / 确认兑换」这类只差两个字的同形按钮，怎么调阈值都落在死区，
不能当判据。** 正确做法是**只取「上层会盖住」的那块区域**：

- ``order_confirm`` —— 取成功弹窗未来会出现的位置（那里是**固定免责提示文字**）；
- ``redeem_done`` —— 取弹窗本体。

两者**同一块坐标、内容完全不同**，所以天然互斥（实测来源帧 1.0000、对手 0.23~0.41）。

## ⚠️ 两个「栈根页」没有专有正向特征 ⇒ 只能做兜底态

- ``feed_home``（首页列表）：底栏四格导航、左上角放大镜**都是共享控件**
  （放大镜实测 6 页里 5 页逐像素完全相同）；底栏「首页」的青绿激活态判的是
  **「在首页这个 Tab 的导航栈里」**，帖子详情页底下那个页签也还在。
- ``item_detail``（商品详情）：被订单确认页盖得只剩底部那条被压暗的按钮。

⇒ 这两页**不设正向锚点**，由 ``resolve_stack_root()`` 用「栈根判据 + 未检出任何盖层」
兜底。**不要**为了「有个正向判据」去调阈值硬凑 —— 那正是 2026-10-05 竞技场入口事故的形状。

## 已验证结果（全库 105 张竖屏帧 → 42 类唯一页面）

9 个锚点全部零可疑命中，明细见 ``runtime_logs/_make_community_anchors.py`` 的报告。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

import numpy as np

from auto_game_unified.core.matcher import best_match, load_template
from auto_game_unified.core.portrait import PORTRAIT_CANVAS
from auto_game_unified.games.epic7.community_numbers import PORTRAIT_SIZE

# 门槛与项目其它锚点同口径。9 个锚点实测在来源帧上都是 1.0000、对手 ≤0.41，
# 0.82 处在很宽的空档里。
THRESHOLD = 0.82

PAGES_DIRNAME = "pages"

# 日志用中文画面名。
PAGE_LABELS = {
    "feed_home": "社区首页（帖子列表）",
    "exchange_center": "兑换中心",
    "exchange_empty": "兑换中心（空列表，要重试）",
    "tasks_page": "我的任务",
    "item_detail": "商品详情",
    "order_confirm": "订单确认",
    "redeem_done": "兑换成功",
    "share_sheet": "分享面板",
    "post_detail": "帖子详情",
    "network_error": "网络连接异常（H5 已死）",
    "image_viewer": "图片查看器（帖子里的图片被放大到全屏）",
    "signin_done": "签到成功弹窗",
    "task_todo": "任务行·去完成",
    "task_done": "任务行·已完成",
    "unknown": "认不出的画面",
}


@dataclass(frozen=True)
class PageAnchor:
    """一个页面判据锚点。

    ``region`` 是**竖屏标准画布坐标** ``(x, y, w, h)``；模板只从来源帧的这一块裁，
    匹配时也**只在同一块区域搜**（区域限定，与横屏那套一致：比全屏搜快一个数量级，
    也天然挡掉「别处也有个长得像的东西」）。
    """

    name: str
    region: tuple[int, int, int, int]
    note: str


@dataclass(frozen=True)
class TaskRow:
    """「我的任务」页里的一行任务。

    ``band`` 是这一行**按钮的搜索带**（不是页面区域）：同一对按钮模板要在这条带里
    各判一次，才能得出「这一行做没做」。
    """

    key: str
    label: str
    band: tuple[int, int, int, int]


@dataclass(frozen=True)
class TaskRowState:
    """一行任务的读数。``state`` 取 ``"todo"`` / ``"done"`` / ``"unknown"``。

    ⚠️ ``"unknown"`` 是**必须存在**的第三态：两个按钮都没过阈时**不许猜**是哪一种 ——
    猜错会让路线「以为做完了」而漏掉任务，或者「以为没做」而反复点同一个按钮。
    """

    key: str
    label: str
    state: str
    confidence: float

    @property
    def is_todo(self) -> bool:
        return self.state == "todo"

    @property
    def is_done(self) -> bool:
        return self.state == "done"

    def describe(self) -> str:
        text = {"todo": "未完成", "done": "已完成", "unknown": "认不出"}[self.state]
        return f"{self.label}={text}" + (f"({self.confidence:.4f})" if self.state != "unknown" else "")


# ── 锚点表 ────────────────────────────────────────────────────────────────────
#
# ⚠️ 加锚点前先问两件事（这两条各让一个候选作废过）：
#   ① 这块内容是**该页专有**的吗？（共享控件不行：底栏四格、左上角放大镜）
#   ② 这块内容**会不会变**？（数值/名字/倒计时/轮播横幅不行）
ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor("feed_home", (125, 1738, 65, 100), "底栏「首页」页签激活态（青绿）"),
    PageAnchor("exchange_center", (410, 96, 260, 68), "居中标题「兑换中心」"),
    # 空列表态（偶发，记忆里点名的隐患）：认不出来就会对着空白页反复点商品卡。
    # 文案是浅灰细字，位置实测 x 375..666 / y 1237..1270。
    PageAnchor("exchange_empty", (360, 1220, 320, 70), "「暂时还没有商品哦」"),
    PageAnchor("tasks_page", (390, 96, 190, 68), "居中标题「我的任务」"),
    PageAnchor("item_detail", (140, 1730, 800, 110), "底部「立即兑换」（叠层，见模块头）"),
    PageAnchor("order_confirm", (270, 745, 540, 240), "订单确认页·固定免责提示"),
    PageAnchor("redeem_done", (265, 736, 550, 256), "「兑换成功」弹窗本体"),
    PageAnchor("share_sheet", (330, 1570, 420, 220), "分享面板「复制链接」"),
    # ⚠️ 2026-10-07 改裁：原区域 (560,1790,440,90) 把**评论数**也罩进去了，
    # 而评论数逐帖不同（实测 10-06 那帖「221」、10-07 那帖「165」）⇒ 在今天的帧上
    # 只拿到 **0.7706**，落在死区里判不出「帖子详情」，于是整页读成 unknown。
    # 新区域只取右侧那颗**分享箭头**（↗）—— 字形固定、逐帖一模一样。
    # 全库 54 张唯一竖屏帧扫描：13 张帖子详情帧全是 1.0000，其余最高 0.3x，零误命中。
    PageAnchor("post_detail", (790, 1790, 110, 85), "帖子底部操作栏·分享箭头（不含评论数）"),
    # 「签到成功！」弹窗的**表头**（✅ 图标 + 那行字）——弹窗本体里「获得 行动力*50 /
    # 同时经验+55」逐次不同，只有表头是固定的。实测在弹窗帧上 1.0000，
    # 全库次高分只有 0.1419，是一道很宽的空档。
    PageAnchor("signin_done", (271, 628, 539, 103), "「签到成功！」弹窗表头"),
    PageAnchor("network_error", (280, 880, 520, 260), "「网络连接异常，下拉刷新」"),
)

# 「我的任务」页三行任务的按钮**长相**模板。
#
# ⚠️ 这两个**不是页面判据**（所以不在 ``ANCHORS`` 里）：它们表达的是「这一行做没做」，
# 而且同一帧上会**同时出现两种**（实测 `tasks_one_browse_done` 上第 1、3 行是绿
# 「去完成」、第 2 行是灰「已完成」）。当页面判据用会导致「一帧命中两个锚点」。
# 正确用法是 ``observe_task_rows()``：在**每一行的搜索带**里各判一次。
TASK_BUTTON_ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor("task_todo", (927, 1178, 121, 55), "任务行绿底「去完成」"),
    PageAnchor("task_done", (944, 1191, 88, 27), "任务行灰底「已完成」"),
)

TASK_ROW_ANCHORS = tuple(anchor.name for anchor in TASK_BUTTON_ANCHORS)

# 三行任务的**按钮搜索带**。实测按钮都是 x 927..1049、高 55，三行 y = 1178 / 1322 / 1466
# （行距 144）。带子给到宽 180、高 90，两边都留了余量。
TASK_ROWS: tuple["TaskRow", ...] = (
    TaskRow("browse", "浏览帖子", (900, 1160, 180, 90)),
    TaskRow("like", "点赞帖子", (900, 1304, 180, 90)),
    TaskRow("share", "分享帖子", (900, 1448, 180, 90)),
)

# ── 信息流卡片上那颗 👍 ───────────────────────────────────────────────────────
#
# ⚠️ 也是**不是页面判据**（同 ``TASK_BUTTON_ANCHORS`` 的理由）：一帧上同时有好几颗
# （每张卡片一颗），当页面判据用会「一帧命中多个锚点」。
#
# ## 为什么必须「找」而不能钉一个坐标（2026-10-07 血泪，用户拍板的 C 方案）
#
# 老写法是 ``FEED_CARD_LIKE = (911, 735)`` + 固定读色框 ``(880, 700, 70, 70)``。
# 真机复量（2026-10-07 19:39 现场帧）发现**两件事都错**：
#
# 1. **那块是白底 + tab 栏「骑士团」三个字**，根本不是 👍。盘上三张信息流夹具
#    （``feed_before_signin`` / ``feed_after_signin`` / ``feed_list``）那一块实测
#    都是 rgb(243.9, 244.2, 245.4) 的纯白 —— 也就是说「点赞前先读颜色」这道预检
#    **从来没读到过 👍**，``card_like_is_on()`` 恒返回 ``False``（=「没点过」），
#    闸门形同不存在。
# 2. **y 会随卡片高度漂**：卡片高度由正文长短决定，实测同一帧里两张卡的 👍 分别在
#    y 756 和 y 1314（差 558px）。钉死 y=735 只在那一次测量的那一屏上成立。
#
# ## 量出来的事实（6 张现场帧，见 ``.workbuddy/_probe_thumb_boxes.py``）
#
# - **x 恒定**：空心 👍 的外接框在全部 6 帧里都是 ``x 883..925``（43 宽）。
# - **y 漂**：出现过的 y 有 330 / 490 / 863 / 1143 / 1314 / 1523 / 1674。
# - **点过的与没点过的长得不一样**：没点过是**空心描边**（深灰细线 + 白心），
#   点过是**实心青绿**（露出白竖线）。本模板只收空心那种 ⇒
#   「模板命中」本身就是「这颗还没点过」的证据，不需要再补一道读色闸门。
#   实测已点过那颗在本模板下最高只到 **0.43**（见 ``test_community_pages.py`` 的分离度用例）。
CARD_LIKE_ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor("card_like_off", (881, 1312, 47, 43), "信息流卡片右下角**未点赞**的空心 👍"),
)

CARD_LIKE_NAMES = tuple(anchor.name for anchor in CARD_LIKE_ANCHORS)

#: 找 👍 的**搜索带**。x 收得很窄（👍 只在 883..925），y 铺满卡片区 ——
#: 搜索面小 ⇒ 单帧一次全带搜索只要约 11ms，且全库竖屏帧零误报。
#: y 从 240 起：再往上就是顶部横幅/图标行与 tab 栏，卡片基本不会露到那儿。
CARD_LIKE_STRIP = (860, 240, 120, 1520)

#: 读「这颗 👍 变成实心绿了没有」的那个框的**边长**（宽、高）。
#: 与模板同尺寸，且以点击点为**中心**读数 —— 对称取值，读数框不会因为裁剪而偏移
#: （模板纪律：裁剪会带动点击点，要保点不变就对称取）。
CARD_LIKE_READ_SIZE = (47, 43)

# ── 信息流里「可以点开一篇帖子」的那条横带（2026-10-08 立）────────────────────
#
# ⚠️⚠️ **不能再钉一个坐标。** 脚本里的 ``FEED_FIRST_POST = (400, 1450)`` 在
# 2026-10-08 **连续两次真机实跑**都点在了**帖子里的图片**上，图片被放大成全屏
# 「图片查看器」⇒ 画面认不出 ⇒ 整条路线卡死（诊断帧
# ``runtime_diagnostics/epic7_community/current.png``，就是那张「欧勒毕斯·冒险手册」大图）。
#
# 而且**同一个坑 2026-10-07 20:39 已经咬过一次**了 —— 那次是回程点「兑换」图标
# 那个坐标（见 ``FEED_ICON_ANCHORS`` 上方那段）。两次都是「盲坐标 + 滚动过的信息流」。
#
# 根因不是「这次点歪了」，是**这套用法本身不成立**：卡片高度由正文长短决定，
# 滚动之后同一个 y 落在哪张卡的哪一块纯属抽签 —— 而这一屏里**唯一不能点的东西**
# 恰好就是图片（点它 = 打开查看器）。
#
# ⇒ 改成**现找**：不是换一个坐标，是换判据。
#
# ## 实测分离度（5 张真机信息流帧 × y 250~1750 逐 12px 扫，共 125 条带）
#
# | 类别                       | 行内彩色像素占比  | 行内暗像素占比      | 行内纯白占比  |
# | -------------------------- | ----------------- | ------------------- | ------------- |
# | 正文带（**判定可点**）     | **0.000 ~ 0.098** | **0.030 ~ 0.239**   | **0.655 ~ 0.960** |
# | 帖子图片（**判定不可点**） | **≥ 0.147**       | 0.020 ~ 0.13        | 0.22 ~ 0.67   |
# | 卡片之间的白缝             | ~0.00             | **~0.00（没字）**   | ~1.0          |
#
# 三条判据就坐在上面那两个区间之间：彩色 ≤0.12（夹在 0.098 与 0.147 的正中）、
# 暗 ≥0.03（挡白缝）、白 ≥0.65（挡**黑白照片** —— 那种图彩色占比也低，只看第一条会漏）。
#
# ## 为什么**不做**「要求连续两块都通过」的加固
#
# 量过：``feed_cards_mixed`` 上真正该点的 ``y=1330`` 恰恰是**孤立单块**
# （上下相邻块都不过）⇒ 加这条会把合法候选删掉，把搜索推到别处、甚至推成 ``None``
# （``None`` 的后果是**本遍任务作废**）。收益不确定、代价确定，所以不做。
# 真正的兜底在下面两层：① 只在 ``hint_y`` 附近**先往上**找；② 万一还是点开了查看器，
# ``detect_image_viewer`` 认得出来并按返回键（``CommunityAction.press_back``）。
#
# ⚠️ 这一条**只管「找一条能点的带」**，不判「这是不是信息流页」。判页是 ``judge_page``
# 的职责，调用方（``_drive_task``）在进来之前已经核过 ``page.name == "feed_home"`` 了。

#: 找正文带的搜索区 ``(x, y, w, h)``。**x 铺满整行**（判据与上面那张表同口径）；
#: y 从 250 起 —— 再往上就是顶部搜索栏与 **tab 行（那行有字）**，会被误当成正文带；
#: 到 1750 止 —— 再往下是底部四格导航栏（同样有字）。
#: ⚠️ 这个框只用来**找**带子；最终 x 取调用方给的 ``hint`` 的 x（见 ``locate_feed_post_tap``）。
FEED_TAP_STRIP = (0, 250, 1080, 1500)

#: 一行里「彩色像素」（``max-min`` 超过 ``FEED_TAP_SATURATION``）占比的上限。
#: 真机帧上正文带 ≤0.017、图片 ≥0.24 ⇒ 0.12 坐在一个很宽的空档里。
FEED_TAP_COLORFUL_MAX = 0.12

#: 一行里「暗像素」（``max < 128``）占比的下限 = 「这一行确实有字」。
FEED_TAP_INK_MIN = 0.03

#: 一行里「纯白像素」（``min > 235``）占比的下限 = 「这是白底卡片，不是照片」。
FEED_TAP_WHITE_MIN = 0.65

#: 判「彩色」的饱和度阈值（与量分离度那一版同口径）。
FEED_TAP_SATURATION = 35

#: 逐行扫的**步长**，也是返回点所在带的**高度**。取 12 而不是 1：
#: 单像素行太噪，一条 12px 的带已经足够窄（正文行高约 40px，不会跨到图片上去）。
FEED_TAP_SLAB = 12

# ── 信息流顶部的「兑换」图标（2026-10-07 立）─────────────────────────────────
#
# 为什么需要它：回「我的任务」那条路是**信息流 → 兑换图标 → 兑换中心 → 获取积分卡**，
# 而那个「兑换」图标长在**信息流顶部的四宫格**里（每日签到 / 兑换 / 周年福利 /
# 战绩查询）。只要往下滑过 —— 而点赞要下滑找 👍、浏览要点开帖子 —— 整行四宫格
# 就**滚出视野**了。
#
# ⚠️ 2026-10-07 真机实跑抓到的 P0：回程把点击点写死成 ``FEED_ICON_EXCHANGE``，
# 滚动之后那个位置已经是**帖子里的图片** ⇒ 点下去打开了图片查看器（现场帧
# ``runtime_diagnostics/epic7_community/20261007_203930_662457_timeout_feed.png``
# 就是那张「平衡性调整公告」大图）⇒ 画面认不出，整条路线卡到超时失败。
#
# 所以这个锚点只回答一个问题：**那颗图标还在不在这一屏**。
# ⚠️ 它**不产出点击点** —— 点击点仍旧用实测有效的 ``FEED_ICON_EXCHANGE``，
# 这样裁剪不会带动点击点（模板纪律：裁剪会带动 ``match.center``）。
FEED_ICON_ANCHORS: tuple[PageAnchor, ...] = (
    PageAnchor(
        "feed_icon_exchange",
        (386, 485, 80, 94),
        "信息流顶部四宫格里的「兑换」钱袋图标（只判在不在，不当点击点）",
    ),
)

FEED_ICON_NAMES = tuple(anchor.name for anchor in FEED_ICON_ANCHORS)

#: 找「兑换」图标的**搜索带**：``(x, y, w, h)`` ⇒ x 330~530、y 200~700。
#:
#: ⚠️ **2026-10-09 修**：原来是 ``(360, 380, 160, 300)``（y 380~680），它把
#: 「四宫格只在**未滚动**那个高度」写死了 —— 而实测四宫格有**两个**落点：
#:
#: - y=**532**：正常进入信息流（``feed_list`` / ``feed_before_signin`` …）⇒ 1.0000
#: - y=**275**：往回滚到**真正的顶部**之后（10-09 实跑现场帧）⇒ 1.0000
#:
#: 老带子的上沿 380 比 275 低 105px ⇒ 图标明明在屏幕上、分数却是 0.0 ⇒
#: ``feed_exchange_icon_visible()`` 恒返回 ``False`` ⇒ 往回滚 3 次全白滚、
#: 最后报 ``CommunityDataMissing`` 收手（用户 10-09 报的「兑换按钮滑下去了找不着」）。
#: **滚回来是对的，是「看不看得见」那把尺子错了。**
#:
#: 新带子的分离度（全部夹具 + 真机诊断帧实测）：
#: 正向（四宫格在视野里，含 y=275 那帧）0.9998~1.0000；负向最大 0.7080
#: （``feed_cards_mixed``，四宫格真滚走了）；两张「真看不见」的现场帧 0.0000。
#: ⇒ 0.82 稳落在空档里。
FEED_ICON_STRIP = (330, 200, 200, 500)

# 兜底态：没有专有正向特征，只能由「栈根判据 + 未检出盖层」推出来。
STACK_ROOT_FALLBACKS = {
    "feed_home": ("feed_home",),            # 栈根判据就是它自己那个青绿页签
    "item_detail": ("exchange_center",),    # 兑换流程的栈根判据是兑换中心标题
}

# 每个栈里「会盖住栈根」的页。栈根兜底时必须这些**都没命中**。
STACK_OVERLAYS = {
    "feed_home": ("post_detail", "signin_done", "network_error", "image_viewer"),
    "item_detail": ("order_confirm", "redeem_done", "network_error"),
}

# 页面属于哪个「栈」。
#
# 同栈内的下层锚点在栈内其它页面上命中是**正常**的（弹窗是叠上去的、下层还在，
# 见模块头），跨栈命中才是事故 —— 那说明用的是共享控件，不是页面专有判据
# （2026-10-05 竞技场入口就是这么炸的）。判据验收时按这条来分「可接受」和「可疑」。
PAGE_STACKS = {
    "feed_home": "feed",
    "post_detail": "feed",
    "share_sheet": "feed",
    "signin_done": "feed",
    "tasks_page": "tasks",
    "exchange_center": "exchange",
    "exchange_empty": "exchange",
    "item_detail": "exchange",
    "order_confirm": "exchange",
    "redeem_done": "exchange",
    # 它会把整个 H5 弄死，不属于任何一条业务栈，必须能独立认出来。
    "network_error": "global",
    # 它把**整屏**都盖住（底下那层连一个像素都露不出来），同样独立成栈。
    "image_viewer": "global",
}

# 叠层优先级：数字越小越靠上。同一次观察里有多个命中时，取最靠上的那个当当前页。
# 依据就是模块头那张叠层图 —— 成功弹窗在订单确认页之上，订单确认页在商品详情之上。
LAYER_ORDER = {
    # 查看器盖住**整屏**（实测上下两条全黑带占 83%），底下那层一个像素都露不出来
    # ⇒ 比「网络异常」还靠上。判它走的是**结构性判据**（不是模板），见
    # ``detect_image_viewer``；给 -1 是为了不动其余各档的相对次序。
    "image_viewer": -1,
    "network_error": 0,   # 它会把整个 H5 弄死，优先级最高，必须先认出来退出重进
    "redeem_done": 1,
    "order_confirm": 2,
    "share_sheet": 3,
    # 签到成功弹窗是**盖在信息流上**的模态层，必须比 feed_home（6）靠上，
    # 否则会把弹窗那一帧判成「就在信息流」⇒ 路线去点被弹窗挡住的地方，白等到超时
    # （2026-10-07 实测：弹窗帧判成 feed_home 0.9999，随后点的两下全被弹窗吃掉了）。
    "signin_done": 2,
    "post_detail": 4,
    # 空列表是兑换中心的**子状态**（标题还在），比「兑换中心」本身更具体 ⇒ 排在它上面，
    # 否则空列表会被判成「正常兑换中心」，路线就会去点不存在的商品卡。
    "exchange_empty": 5,
    "exchange_center": 6,
    "tasks_page": 6,
    "feed_home": 6,
    "item_detail": 7,
}


@dataclass(frozen=True)
class TemplateRoot:
    """模板根目录（``templates/community``）。"""

    path: Path

    def page_path(self, name: str) -> Path:
        return self.path / PAGES_DIRNAME / f"{name}.png"


def build_page_templates(template_root: Union[str, Path]) -> dict[str, np.ndarray]:
    """把 9 个页面判据 + 2 个任务按钮 + 1 颗卡片 👍 模板全部读出来（共 12 张）。

    ⚠️ **fail closed**：任何一个缺失都当场抛 ``FileNotFoundError``，不做
    ``if exists() else None``。判据型模板静默降级过一次就走了整整一个月的弯路
    （2026-10-03 血泪：PC 镜像文件被删 → 判据悄悄消失），这里不再重演。
    """
    root = TemplateRoot(Path(template_root))
    templates: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for anchor in (
        *ANCHORS,
        *TASK_BUTTON_ANCHORS,
        *CARD_LIKE_ANCHORS,
        *FEED_ICON_ANCHORS,
    ):
        path = root.page_path(anchor.name)
        if not path.is_file():
            missing.append(f"{anchor.name}（{path}）")
            continue
        templates[anchor.name] = load_template(str(path))
    if missing:
        raise FileNotFoundError(
            "缺社区页面判据模板：" + "、".join(missing) + "；判据型模板不许缺，缺失必须在这里报错"
        )
    return templates


def _assert_portrait(screen: np.ndarray) -> None:
    if screen.shape[0] != PORTRAIT_CANVAS[1] or screen.shape[1] != PORTRAIT_CANVAS[0]:
        raise ValueError(
            f"社区页面判据只吃竖屏 {PORTRAIT_CANVAS[0]}x{PORTRAIT_CANVAS[1]}，"
            f"拿到 {screen.shape[1]}x{screen.shape[0]}；"
            "横屏帧喂进来会判出莫名其妙的结果"
        )


@dataclass(frozen=True)
class Observation:
    name: str
    confidence: float
    region: tuple[int, int, int, int]

    def describe(self) -> str:
        label = PAGE_LABELS.get(self.name, self.name)
        return f"{label} {self.confidence:.4f}"


@dataclass(frozen=True)
class PageJudgement:
    """判页结论。

    ``fallback=True`` 表示**没有任何正向判据命中**，名字是「栈根兜底」推出来的
    （见 ``STACK_ROOT_FALLBACKS``）。业务上要用它时请明确知道这一点，
    别把它当成一个正向判据来用。
    """

    name: str
    confidence: float
    observations: tuple[Observation, ...]
    fallback: bool = False

    @property
    def label(self) -> str:
        return PAGE_LABELS.get(self.name, self.name)

    def describe(self) -> str:
        if self.fallback:
            return f"{self.label}（兜底，无正向判据命中）"
        return f"{self.label} {self.confidence:.4f}"


def observe_pages(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
    names: Optional[Iterable[str]] = None,
) -> tuple[Observation, ...]:
    """在**各锚点自己的限定区域内**搜模板，返回所有过阈的观察，按分数从高到低。

    区域限定是刻意的：与横屏那套一致，既快，也天然挡掉「别处也有个长得像的东西」。
    """
    _assert_portrait(screen)
    wanted = set(names) if names is not None else None
    found: list[Observation] = []
    for anchor in ANCHORS:
        if wanted is not None and anchor.name not in wanted:
            continue
        template = templates.get(anchor.name)
        if template is None:
            raise KeyError(f"锚点 {anchor.name} 没有模板；build_page_templates() 是 fail-closed 的，不该走到这里")
        x, y, w, h = anchor.region
        patch = screen[y : y + h, x : x + w]
        if patch.shape[0] != h or patch.shape[1] != w:
            continue
        score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
        if np.isfinite(score) and score >= threshold:
            found.append(Observation(anchor.name, float(score), (x, y, w, h)))
    found.sort(key=lambda item: (-item.confidence, LAYER_ORDER.get(item.name, 99)))
    return tuple(found)


def top_page(observations: Iterable[Observation]) -> Optional[Observation]:
    """从观察里挑「当前页」：**先看叠层优先级，再看分数**。

    ⚠️ 不能只按分数挑：下层页面在上层被压暗后照样能拿高分（模块头那张表），
    只有叠层次序才说得清谁盖着谁。
    """
    candidates = [item for item in observations if item.name not in TASK_ROW_ANCHORS]
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (LAYER_ORDER.get(item.name, 99), -item.confidence))
    return best


# ── 「图片查看器」的结构性判据（**不是模板**，2026-10-08 立）──────────────────
#
# 为什么没有模板：那一屏上**只有一张帖子里的图片**和它周围的纯黑，而图片逐帖不同
# ⇒ **没有任何「每次一模一样」的内容**可以裁成模板。硬裁一张 = 模板纪律里
# 「模板不许含会变的内容」，下次换一张图就失效。
#
# 但它的**结构**是恒定的：上、下两条全黑带 + 中间一条内容带，且内容带不贴上下边缘。
#
# 实测（1080x1920）：4 张真机查看器帧的全黑行占比是 **0.828 ~ 0.837**
# （内容带 y 795~1125 / 803~1115）；而**其余全部竖屏帧都是 0.000**
# （``tests/fixtures`` + ``runtime_diagnostics`` 里 34 张 1080x1920 帧逐张量过）
# ⇒ 0.60 这道阈值坐在一个 0.8 宽的空档正中间，两边都不沾。
#
# ⚠️ 为什么值得单独立一档（而不是「认不出就报错」）：**这个坑一天咬了两次**
# （2026-10-08 18:58 / 19:10，外加 10-07 20:39 同形），每一次的代价都是
# **整条路线卡死 + 收尾连社区都关不掉**。认出来 ⇒ 按一下返回键就接着走。
IMAGE_VIEWER_BLACK_MAX_CHANNEL = 40
IMAGE_VIEWER_BLACK_ROW_FRACTION = 0.98
IMAGE_VIEWER_MIN_BLACK_FRACTION = 0.60
IMAGE_VIEWER_MIN_BAND_HEIGHT = 60


@dataclass(frozen=True)
class ImageViewerFrame:
    """帖子图片被放大成全屏时的画面结构。``band`` 是中间那条内容带的 y 起止。"""

    band: tuple[int, int]

    @property
    def center(self) -> tuple[int, int]:
        """点击点：内容带正中。

        ⚠️ 这条判据的动作本意是**按返回键**（``CommunityAction.press_back``），
        这个点只是「万一返回键那一路没被认出来」时的兜底：落在图片上，
        比落在 ``(0, 0)`` 强得多（点 (0,0) 是最难查的那种失败）。
        """
        return (PORTRAIT_CANVAS[0] // 2, (self.band[0] + self.band[1]) // 2)


def detect_image_viewer(screen: np.ndarray) -> Optional[ImageViewerFrame]:
    """认「有人把帖子里的图片点开放大了」。认不出返回 ``None``。

    三步全是**结构**，与图片内容无关：

    1. 一行里 ≥98% 的像素「近乎全黑」（``max(r,g,b) < 40``）⇒ 这一行算**黑行**；
    2. 黑行占比 ≥ ``IMAGE_VIEWER_MIN_BLACK_FRACTION``；
    3. 剩下的非黑行连成一条带，且**不贴上下边缘**、高度 ≥ ``IMAGE_VIEWER_MIN_BAND_HEIGHT``。

    第 3 条是防「整屏纯黑」（加载中的黑屏之类）被误认成查看器。
    """
    _assert_portrait(screen)
    # ⚠️ 不开 ``.astype(np.int16)``：uint8 直接跟 40 比就够，而那次转型要给
    # 1920x1080x3 的帧再开一份 12MB 的临时数组（实测这一条占了本判据大半时间，
    # 而它在**每一帧**上都要跑）。省掉它，结果逐位不变。
    black_rows = (screen.max(axis=2) < IMAGE_VIEWER_BLACK_MAX_CHANNEL).mean(
        axis=1
    ) >= IMAGE_VIEWER_BLACK_ROW_FRACTION
    if float(black_rows.mean()) < IMAGE_VIEWER_MIN_BLACK_FRACTION:
        return None
    content = np.flatnonzero(~black_rows)
    if content.size == 0:
        return None
    top, bottom = int(content[0]), int(content[-1])
    if top <= 0 or bottom >= screen.shape[0] - 1:
        return None
    if bottom - top + 1 < IMAGE_VIEWER_MIN_BAND_HEIGHT:
        return None
    return ImageViewerFrame((top, bottom))


def judge_page(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> PageJudgement:
    """判页。认不出来就返回 ``unknown`` —— **绝不猜**（认错比认不出更糟）。

    ⚠️ 有一档判据**不是模板**：``image_viewer``（见 ``detect_image_viewer``）。
    它把**整屏**盖住（实测上下两条黑带占 83%），所以**先判它、命中即短路**，
    连模板都不必再看 —— 看了也只是在纯黑与一张图上瞎比。

    ⚠️⚠️ **生产路径唯一入口就是这里。** 2026-10-08 踩到过：状态机里另抄了一份
    ``observe_pages → top_page → 栈根兜底``，于是这里新加的判据**真机根本走不到**
    —— 单元测试调本函数全绿、实跑照旧认不出查看器。现在 ``CommunityStateMachine.observe``
    只委托本函数（``test_community.py`` 有一条用例逐帧核两边结论一致）。

    三步的顺序就是优先级：**查看器 → 正向判据（按叠层次序）→ 栈根兜底 → unknown**。
    """
    observations = observe_pages(screen, templates, threshold=threshold)
    viewer = detect_image_viewer(screen)
    if viewer is not None:
        band = (  # 区域只用于诊断展示：内容带那一条
            0,
            viewer.band[0],
            PORTRAIT_CANVAS[0],
            viewer.band[1] - viewer.band[0] + 1,
        )
        return PageJudgement(
            "image_viewer",
            1.0,
            (Observation("image_viewer", 1.0, band), *observations),
        )
    top = top_page(observations)
    if top is not None:
        return PageJudgement(top.name, top.confidence, observations)
    # 栈内没有盖层 ⇒ 试栈根兜底（首页列表 / 商品详情这两页没有专有判据）。
    # 次序就是 ``STACK_ROOT_FALLBACKS`` 的插入序（feed_home 在前），别再抄一份元组。
    for root in STACK_ROOT_FALLBACKS:
        resolved = resolve_stack_root(observations, root)
        if resolved is not None:
            return resolved
    return PageJudgement("unknown", 0.0, observations)


def observe_task_rows(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> tuple[TaskRowState, ...]:
    """读「我的任务」页三行各自做没做。

    在**每一行自己的搜索带**里各判一次「去完成」与「已完成」，取分高者；
    两个都没过阈 ⇒ ``unknown``。

    ⚠️ 三态是刻意的：认不出时返回 ``unknown`` 而不是默认成某一种 ——
    「以为做完了」会漏任务，「以为没做」会对着同一个按钮反复点。
    """
    _assert_portrait(screen)
    out: list[TaskRowState] = []
    for row in TASK_ROWS:
        x, y, w, h = row.band
        patch = screen[y : y + h, x : x + w]
        if patch.shape[0] != h or patch.shape[1] != w:
            out.append(TaskRowState(row.key, row.label, "unknown", 0.0))
            continue
        scores: dict[str, float] = {}
        for name in TASK_ROW_ANCHORS:
            template = templates.get(name)
            if template is None:
                raise KeyError(f"任务按钮锚点 {name} 没有模板；build_page_templates() 是 fail-closed 的")
            score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
            scores[name] = float(score) if np.isfinite(score) else 0.0
        best = max(scores, key=lambda key: scores[key])
        if scores[best] < threshold:
            out.append(TaskRowState(row.key, row.label, "unknown", scores[best]))
            continue
        out.append(
            TaskRowState(
                row.key,
                row.label,
                "todo" if best == "task_todo" else "done",
                scores[best],
            )
        )
    return tuple(out)


def locate_card_like(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> Optional[tuple[int, int]]:
    """在信息流卡片区里**找**一颗「还没点过」的 👍 ⇒ 返回它的点击点。

    找不到就返回 ``None``（画面里没有卡片、或这一屏的卡片**全都点过了**）。
    ⚠️ ``None`` 是「没找到」，**不是**「可以点一个默认位置」—— 调用方拿到 ``None``
    的正确反应是**往下滑一屏再找**（用户 2026-10-07 拍板的 C 方案），
    绝不是退回某个钉死的坐标：那颗 👍 是**开关**，点错一颗会把别人的赞取消掉。

    ## 为什么是「找」而不是「钉坐标」

    见 ``CARD_LIKE_ANCHORS`` 上方那段：钉死的 y 只在那一次测量的那一屏上成立，
    卡片高度由正文长短决定 ⇒ 同一帧里两张卡的 👍 实测能差 558px。

    ## 为什么用同一套打分函数

    走 ``core.matcher.best_match``（= ``TM_CCOEFF_NORMED``），和 ``observe_task_rows``
    同一个口径。⚠️ 别在这里另写一份打分 —— 共享打分函数换个调用方必须**走生产口径**
    （2026-10-04 在多尺度模板上踩过：穷举位置量出来的是假误判）。

    ## 实测分离度（2026-10-07，``tests/fixtures/epic7_community`` 全部竖屏帧）

    - 真命中（6 张现场帧里的空心 👍）：**1.0000**
    - 已点过的实心绿 👍：**0.43**
    - 空信息流帧 / 其余页面：**≤0.40**，全库 **0 张**过阈
    ⇒ 0.82 落在很宽的空档里。
    """
    _assert_portrait(screen)
    template = templates.get("card_like_off")
    if template is None:
        raise KeyError(
            "卡片 👍 锚点 card_like_off 没有模板；build_page_templates() 是 fail-closed 的"
        )
    x, y, w, h = CARD_LIKE_STRIP
    patch = screen[y : y + h, x : x + w]
    if patch.shape[0] != h or patch.shape[1] != w:
        # 出界 ⇒ 这一帧不是标准竖屏画布，交给上层当「没找到」处理。
        return None
    score, offset = best_match(patch.astype(np.float32), template.astype(np.float32))
    if not np.isfinite(score) or float(score) < threshold:
        return None
    height, width = template.shape[0], template.shape[1]
    return (x + offset[0] + width // 2, y + offset[1] + height // 2)


def card_like_reading_box(point: tuple[int, int]) -> tuple[int, int, int, int]:
    """给一个 👍 的点击点，返回**读它颜色**的那个框（以该点为中心，对称取）。

    ⚠️ 必须以**点出来的那个点**为中心读数：老写法读的是一个写死的框
    ``(880, 700, 70, 70)``，而那一块实际是 tab 栏「骑士团」三个字（纯白）⇒
    「点完了变绿了没有」这道验收**永远读成「没变」**，每遍都会走到超时作废。
    """
    width, height = CARD_LIKE_READ_SIZE
    return (point[0] - width // 2, point[1] - height // 2, width, height)


def feed_tap_band_is_text(screen: np.ndarray, top: int, height: int) -> bool:
    """``[top, top+height)`` 这几行是不是「白底 + 有字 + **不是图片**」。

    三个条件**必须同时**成立，缺一不可（分离度见 ``FEED_TAP_STRIP`` 上方那张表）：

    1. **不是图片**：彩色像素（``max-min > FEED_TAP_SATURATION``）占比 ≤ ``FEED_TAP_COLORFUL_MAX``；
    2. **确实有字**：暗像素（``max < 128``）占比 ≥ ``FEED_TAP_INK_MIN``
       —— 拿它挡掉卡片之间的浅灰缝和只有一颗标签的行；
    3. **白底**：纯白像素（``min > 235``）占比 ≥ ``FEED_TAP_WHITE_MIN``
       —— 拿它挡掉**黑白照片**（那种图彩色占比同样低，只看第 1 条会漏）。

    用 ``max``/``min`` 跨通道取，所以**与色彩口径（RGB/BGR）无关**，
    不会重演「两边不同口径量出假分数」那一课。
    """
    band = screen[top : top + height].astype(np.int16)
    if band.size == 0:
        return False
    pixels = band.reshape(-1, band.shape[-1])
    high = pixels.max(axis=1)
    low = pixels.min(axis=1)
    colorful = float(((high - low) > FEED_TAP_SATURATION).mean())
    ink = float((high < 128).mean())
    white = float((low > 235).mean())
    return (
        colorful <= FEED_TAP_COLORFUL_MAX
        and ink >= FEED_TAP_INK_MIN
        and white >= FEED_TAP_WHITE_MIN
    )


def feed_band_tops(
    screen: np.ndarray,
    *,
    strip: tuple[int, int, int, int] = FEED_TAP_STRIP,
    slab: int = FEED_TAP_SLAB,
) -> list[int]:
    """信息流里**全部**「可点正文带」的上沿 y，从小到大。

    用途（2026-10-09）：给滑动手势当「**页面真的滚动过了**」的结构证据——
    滚动会整体改变这张表；而头像、动图之类的局部动画不会。
    状态机拿它对账「上一次发出的滑动手势到底执行了没有」，
    因为主循环对同名动作有重试节流，**按帧记账会几秒就烧穿**（见
    ``community.SWIPE_UNEXECUTED_FRAME_LIMIT`` 那段）。

    与 ``locate_feed_post_tap`` 用**同一套**判据（``feed_tap_band_is_text``），
    判据只有这一份实现。
    """
    _assert_portrait(screen)
    y0 = strip[1]
    bottom = min(y0 + strip[3], screen.shape[0])
    return [
        top
        for top in range(y0, bottom - slab + 1, slab)
        if feed_tap_band_is_text(screen, top, slab)
    ]


def locate_feed_post_tap(
    screen: np.ndarray,
    hint: tuple[int, int],
    *,
    strip: tuple[int, int, int, int] = FEED_TAP_STRIP,
    slab: int = FEED_TAP_SLAB,
) -> Optional[tuple[int, int]]:
    """在信息流里**找**一条「可以点开帖子」的正文带 ⇒ 返回点击点；找不到返回 ``None``。

    ``hint`` 是脚本里钉着的那个盲坐标（``community.FEED_FIRST_POST``）。以它的 **y**
    为中心**先往上、再往下**找最近的那条正文带；**x 原样沿用 hint 的 x**。

    ## 为什么只纠正 y、不动 x

    出事的是 y：卡片高度由正文长短决定，滚动之后同一个 y 落在哪张卡的哪一块是抽签。
    x 从来没有出过问题（每张卡都是通栏白底），而且「点得对的时候行为完全不变」这件事
    只有把 x 原样传下去才成立（实测 10-07 19:10 那次 ``(400, 1450)`` 落在正文上 ⇒
    这里原样返回它）。

    ## 为什么「往上找」是对的

    卡片结构是「头像行 → 标题/正文 → **图片** → 标签行」。所以一条图片带**上面**
    紧邻的一定是这篇的正文，点上去就是**打开这篇**——正是我们要的动作。
    往下找只在整屏都没有正文带时才用得到（例如一屏全是图）。

    ## ``None`` 的语义

    ``None`` = 「这一屏找不到可以安全点开的地方」⇒ 调用方**只许报错收手**，
    **绝不许退回 ``hint`` 硬点** —— 那正是 2026-10-08 两次实跑卡死的原因。
    """
    _assert_portrait(screen)
    y0 = strip[1]
    height = strip[3]
    bottom = min(y0 + height, screen.shape[0])
    if bottom - slab < y0:
        return None
    tops = list(range(y0, bottom - slab + 1, slab))
    if not tops:
        return None
    # 离 ``hint[1]`` 最近的那条带当起点，然后先往上、再往下。
    begin = min(
        range(len(tops)), key=lambda index: abs(tops[index] + slab // 2 - hint[1])
    )
    order = [*range(begin, -1, -1), *range(begin + 1, len(tops))]
    for index in order:
        top = tops[index]
        if feed_tap_band_is_text(screen, top, slab):
            return (hint[0], top + slab // 2)
    return None


def feed_exchange_icon_visible(
    screen: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    threshold: float = THRESHOLD,
) -> bool:
    """信息流顶部那颗「兑换」图标**还在这一屏**吗。

    只回答「在不在」—— **不产出点击点**。点击点仍旧用 ``FEED_ICON_EXCHANGE``
    （那个坐标在未滚动的信息流上实测点得进兑换中心），这样裁剪就不会带动点击点。

    ## 它挡的是哪一类事故

    回「我的任务」要经「兑换图标 → 兑换中心」。往下滑过之后四宫格滚出视野，
    钉死的那个坐标底下变成了**帖子图片** —— 直接点下去会打开图片查看器，
    整条路线卡到超时（2026-10-07 20:39 实跑，现场帧见 ``FEED_ICON_ANCHORS``）。

    ⇒ 调用方拿到 ``False`` 的正确反应是**往回滚一屏再问一次**（滚到顶四宫格
    自然露出来），而不是照旧点下去。

    ## 实测分离度（2026-10-07 立，2026-10-09 重测）

    - 四宫格在视野里（含 y=532 与 y=275 两个落点）：**0.9998~1.0000**
    - 四宫格真被滚走（``feed_cards_mixed``）：**0.7080**，不过阈
    - 其余竖屏页（兑换中心 / 帖子详情 / 分享面板 …）：**≤0.6056**，全部不过阈
    - 两张「真看不见」的现场帧（10-07 / 10-08 的 ``timeout_feed``）：**0.0000**
    ⇒ 0.82 落在空档里。唯一「过阈」的是 ``signin_success``（0.9998）——
      那是**签到成功弹窗盖在信息流上**、四宫格作为背景仍在，语义上确实在；
      而那条路会先被 ``signin_done`` 判据接走，走不到这里。

    ⚠️ **搜索带必须同时罩住 y=532 和 y=275 两个落点**（10-09 的教训）：
    只认「未滚动」那个高度，就会在「滚回顶部」这一屏上恒判「看不见」。
    """
    _assert_portrait(screen)
    template = templates.get("feed_icon_exchange")
    if template is None:
        raise KeyError(
            "「兑换」图标锚点 feed_icon_exchange 没有模板；"
            "build_page_templates() 是 fail-closed 的"
        )
    x, y, w, h = FEED_ICON_STRIP
    patch = screen[y : y + h, x : x + w]
    if patch.shape[0] != h or patch.shape[1] != w:
        # 出界 ⇒ 不是标准竖屏画布，当「看不见」处理（调用方会往回滚）。
        return False
    score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
    return bool(np.isfinite(score) and float(score) >= threshold)


def resolve_stack_root(
    observations: Iterable[Observation],
    root: str,
    *,
    threshold: float = THRESHOLD,
) -> Optional[PageJudgement]:
    """栈根兜底：``root`` 的栈根判据命中、且**该栈的盖层一个都没命中** ⇒ 就是 ``root``。

    用法（业务侧）::

        # 首页列表：底栏「首页」青绿页签还在，且没看到帖子详情
        resolve_stack_root(obs, "feed_home")

        # 商品详情：兑换流程里，没收看到订单确认页 / 成功弹窗
        resolve_stack_root(obs, "item_detail")

    ⚠️ 这是**兜底**，不是正向判据：``PageJudgement.fallback`` 为 True，
    日志里必须写清楚（``describe()`` 已经带了「兜底」字样）。
    """
    items = list(observations)
    hit = {item.name for item in items}
    stack_anchor = STACK_ROOT_FALLBACKS.get(root)
    if stack_anchor is None:
        raise KeyError(f"{root} 不是栈根兜底态；可用的有 {sorted(STACK_ROOT_FALLBACKS)}")
    if not any(name in hit for name in stack_anchor):
        return None
    if any(name in hit for name in STACK_OVERLAYS.get(root, ())):
        return None
    base = next((item for item in items if item.name in stack_anchor), None)
    return PageJudgement(root, base.confidence if base else 0.0, tuple(items), fallback=True)


def assert_anchor_regions_inside_canvas() -> None:
    """构造期自检：每个锚点区域都必须落在竖屏画布内、尺寸为正。

    与横屏 ``Epic7Navigator._assert_anchor_templates()`` 同一个用意 ——
    区域写错了（负数、越界）会让匹配悄悄退化成「什么都搜不到」，
    在这里喊出来比在真机上查便宜得多。
    """
    width, height = PORTRAIT_CANVAS
    for anchor in ANCHORS:
        x, y, w, h = anchor.region
        if w <= 0 or h <= 0:
            raise ValueError(f"锚点 {anchor.name} 区域尺寸非正：{anchor.region}")
        if x < 0 or y < 0 or x + w > width or y + h > height:
            raise ValueError(
                f"锚点 {anchor.name} 区域 {anchor.region} 越出竖屏画布 {width}x{height}"
            )


assert_anchor_regions_inside_canvas()
assert PORTRAIT_SIZE == PORTRAIT_CANVAS, "community_numbers 与 portrait 的画布口径必须一致"
