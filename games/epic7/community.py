"""社区签到路线（竖屏 H5）的状态机。

这条路线横跨**两条通道**：从大厅走到网页活动列表是横屏（``Epic7Window``），
点进「游戏社区」之后模拟器整块转成竖屏，由 ``core/portrait.py`` 那条独立链路接管
（1080x1920，坐标就是点击坐标，不需要换算）。页面判据见 ``community_pages``，
数字读数见 ``community_numbers``。

## 坐标来源

下表**全部是真机实测量准**的（2026-10-06），不是估的。改之前先回真机重量。

| 页面 | 元素 | 坐标 |
| --- | --- | --- |
| 信息流 | 搜索 / 关闭 X | (181,92) / (937,92) |
| 信息流 | 图标行 y=538：签到 / 兑换 / 周年福利 / 战绩查询 | x = 240 / 438 / 638 / 838 |
| 信息流 | 底栏：首页 / 攻略 / 投稿 / 我的 | x = 157 / 414 / 670 / 925（y≈1790） |
| 兑换中心 | 左上「<」/ 积分卡 / 获取积分卡 | (36,121) / (240,270) / (800,270) |
| 兑换中心 | 商品卡（380x543） | 卡1(250,639) 卡2(789,639) 卡3(250,1219) 卡4(789,1219) |
| 商品详情 | 左上「<」/ 底部绿按钮 | (62,124) / **每帧现量** |
| 订单确认 | 底部绿按钮 | **每帧现量**（实测比商品详情页高 49px） |
| 兑换成功 | 橙字「确认」 | (539,952) |
| 我的任务 | 左上「<」/ 积分行「去兑换」 | (35,130) / (961,554) |
| 我的任务 | 三行按钮 | x=988，y = 1205 / 1349 / 1493（按钮框 y 1178/1322/1466 起） |
| 帖子详情 | 左上「<」/ 底栏分享 | (154,97) / (847,1832) |
| 分享面板 | 复制链接 / 取消 | (539,1650) / (539,1840) |

## ⚠️ 两个「必须每帧现量」的地方（踩过的坑）

1. **底部那颗大绿按钮**（立即兑换 / 确认兑换）—— 实测同一个控件在商品详情页 y 中心
   **1795**、在订单确认页 **1746**，**差 49px**。页面重排后沿用上一次的位置会点空、
   白等 40 秒才超时。⇒ ``locate_green_button()`` 按**颜色**每帧现找（与 ``fodder.py``
   里找「开始战斗」同一套路子）。
2. **订单确认页的按钮一开始是暗的**（点过之后变禁用色）—— 所以颜色定位在
   「已点过」的帧上会**找不到**，这正是我们要的：找不到就不许再点一次。

## ⚠️ 结果不是立刻出

点完「确认兑换」后按钮先不动，**>7 秒**（实测 3~40 秒区间）才弹结果
⇒ 必须**轮询**，不能固定 sleep。本模块只负责「下一步做什么」，
轮询由主循环的等待机制负责。⚠️ 那条等待**不出手、不打分、不报警**，
所以 `CommunityRunner` 给它配了一条 10 秒心跳（见类 docstring）——
否则从进页到超时之间日志是完全空白的。

## 这条路线横跨两条通道（见 `community.attach_dual_channel` / `ChannelSwitch`）

大厅 → 网页活动列表是**横屏**（`Epic7Window`）；点进「游戏社区」之后模拟器整块
转成竖屏，横屏那套 `capture()` 会直接抛「render size changed」，必须换
`core/portrait.py` 那条 adb 链路。主循环只认 `runtime.capture()/click()` 一套接口，
所以由 `attach_dual_channel()` 在中间垫一层按方向分派。

## 这一次的行动次序（2026-10-07 真机采齐后定的）

```
信息流 ──签到（未签才点）──> 我的任务 ──三条每日任务──> 去兑换 ──> 信息流 ──> 关社区
   ▲                              |                                        |
   └──── 经兑换中心 →「获取积分卡」 ┘（底栏那个「我的」不是我的任务）        └─ 转回横屏才收工
```

三条每日任务各自是一个**闭环**：点「去完成」→ 信息流 → 按脚本做动作 →
经兑换中心回「我的任务」→ **对账**（那一行的按钮有没有变成「已完成」；⚠️ 读的是
按钮长相，不是 ``x/3`` 那个数字）。
涨了算数、没涨再来一遍、连试 ``TASK_ATTEMPT_LIMIT`` 遍都不涨就记一笔「今天做不成」
并跳过它继续跑别的 —— **绝不死循环，也绝不无声跳过**（名字会写进收尾日志）。

## ⚠️ 还没被第二天复验过的地方（写在这里，别装作不存在）

- **三条任务的执行坐标只有单日样本**：``FEED_FIRST_POST``（信息流顶部第一张帖子卡）与
  ``FEED_CARD_LIKE``（卡片右下角 👍）都只在 2026-10-07 那一天的题字与滚动位置上量过。
  卡片高度由正文长短决定 ⇒ **换一天可能对不上**。兜底是「以页面计数为准 + 有上限的重试」，
  所以对不上只会让那条任务被记成「今天做不成」，**不会点坏东西**。
- ✅ **卡片 👍 是开关**（``card_like_is_on``）：已绿的再点会**取消**点赞。
  2026-10-07 已把这道预检接进脚本（``TASK_SCRIPT`` 里那一步的动作类型写成
  ``tap_like`` 就是为了让它被认出来）：**已经是绿的就先滑一次换一张卡片**，
  读不出颜色就**不点**，滑满 ``LIKE_RESWIPE_LIMIT`` 次就收手。
- **签到的弹窗延迟没有复查**：2026-10-07 实测点后 3 秒 / 9 秒看都没变化、
  74 秒后再看已经在了。到底是服务端慢、还是第一次那下其实没生效，
  **没有定论**。所以 ``_TIMEOUT_SECONDS[FEED]`` 给到 150 秒罩住它。
- **订单确认页按钮「禁用」与「不在」分不开**：两者在颜色定位里都是「找不到」，
  目前一律按「等结果」处理。
- ⚠️ **重试上限必须大于「任务要求的次数」**：浏览 / 点赞一天各要 3 次，而对账只在
  「这一行还没变成『已完成』」时才记一遍 ⇒ 上限等于 3 就**恰好要求每遍都成功**，
  点空一次就判死（哪怕计数已经 2/3）。现在 ``TASK_ATTEMPT_LIMIT = 6``（要求 3 + 容错 3），
  ``tests/test_community.py`` 里有两条用例钉住这件事。
- ⚠️ **对账读的是按钮长相，不是 ``x/3`` 那个数字**（``observe_task_rows`` 判的是
  ``task_todo`` / ``task_done``）。日志里**别写「计数没动」** —— 3 次制的计数每遍都在动，
  只是按钮要到第 3 遍才翻成「已完成」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Any, Callable, Optional, Sequence

import cv2
import numpy as np

from auto_game_unified.core.portrait import (
    PORTRAIT_CANVAS,
    OrientationError,
    PortraitChannel,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, ResourceExhausted, Runtime
from auto_game_unified.core.window import Epic7Window
from auto_game_unified.games.epic7 import community_pages as pages
from auto_game_unified.games.epic7.community_numbers import Readout, read_digits, read_pair
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import NOT_STABLE, ModeRunnerBase

# ── 竖屏坐标（全部实测，见模块头表） ──────────────────────────────────────────

FEED_SEARCH = (181, 92)
FEED_CLOSE = (937, 92)
FEED_ICON_Y = 538
FEED_ICON_SIGNIN = (240, FEED_ICON_Y)
FEED_ICON_EXCHANGE = (438, FEED_ICON_Y)
FEED_TAB_MINE = (925, 1790)

# ── 签到（2026-10-07 真机采到；这是这条路线进社区后的第一个动作） ──────────────

# 「每日签到」图标**本身就是签到入口**，点它即签到。
#
# ⚠️ 点完**不会立刻出弹窗**：2026-10-07 实测点后 3 秒、9 秒各抓一帧都没变化，
# 到 74 秒后再看，「签到成功！」弹窗已经在了（`_on_feed` 因此按「点了就等」处理，
# 等待上限由 `_TIMEOUT_SECONDS[FEED]` 罩住）。别把「没反应」当成「点空了」——
# 那天差点就这么误判，跑去改坐标。
FEED_SIGNIN_CLICK = (240, FEED_ICON_Y)

# 判「今天签没签」只看**这一块**：图标本体（避开右上角那个红点）。
#
# 判据是**颜色**，不是形状：未签到时图标是彩色的（黄色墨水瓶 + 棕色羽毛笔），
# 签到之后整块**变灰**。真机量到两态分得极开：
#
# | 状态 | 这一块的平均饱和度 |
# | --- | --- |
# | 未签到（今天，含红点） | **49.1** |
# | 已签到（10-06 帧 / 今天签完之后） | **0.0** |
#
# 阈值取 20 —— 落在 0 与 49 正中间，不是在死区里挑数。
SIGNIN_ICON_BOX = (190, 495, 90, 75)
SIGNIN_ICON_SATURATION = 20.0
# 这一块**太暗**就不敢下结论：签到成功弹窗的压暗背板会把整屏压黑，
# 那时彩色图标也会量出 0（2026-10-07 实测弹窗帧 S=0.0），照读会误判成「已签到」。
# 正常信息流这一块的 V 是 200+，压暗帧只有几十 ⇒ 留一道亮度闸门。
SIGNIN_ICON_MIN_VALUE = 120.0

# 「签到成功！」弹窗右上那颗绿「关闭」。
# ⚠️ 别照渲染图目测（我第一次目测成 (561,1283)，点了两下没反应）；
# 用颜色连通域量出来的中心才是 (539,1212)。
SIGNIN_POPUP_CLOSE = (539, 1212)

# ── 三条每日任务的执行段（2026-10-07 真机采到） ───────────────────────────────

# 点完「去完成」之后落在**信息流首页顶部**（10-07 四次实测都是同一帧 b33079c5）。
# 顶部布局固定 ⇒ 第一张帖子卡的位置也是固定的，点它即开帖。
FEED_FIRST_POST = (400, 1450)
# 卡片右下角那颗 👍。⚠️ **它是开关**：已经点过（绿底白手）时再点会**取消点赞**，
# 计数不涨反掉。10-07 实测 `act01` 就是把一张已绿的卡片点灰了 ⇒ 白花一次额度。
# 所以开点之前先看这块的颜色，**只点灰的**。
FEED_CARD_LIKE = (911, 735)
FEED_CARD_LIKE_BOX = (880, 700, 70, 70)
# 「去完成」→ 信息流之后走这一次滑动，把卡片 👍 带进上面那个位置（10-07 实测）。
FEED_TASK_SCROLL_START = (540, 1500)
FEED_TASK_SCROLL_END = (540, 700)
FEED_TASK_SCROLL_MS = 400

# 同一条任务最多试几遍。三遍还没让计数涨就是「这条今天做不成」，
# 记一笔、跳到下一条 —— **绝不死循环**（账本要记的是「做了几次」，
# 而不是「试到成功为止」，后者会在判据失灵时无声转到底）。
#
# ⚠️ ``TASK_SCRIPT`` / ``TASK_LABELS`` 排在**所有坐标都定义之后**（文件下面那一块）：
# 脚本里要按名字引用 `POST_BACK` / `POST_SHARE` / `SHARE_COPY_LINK`，
# 放在坐标区中间会 `NameError`（2026-10-07 踩过）。
# 一条任务最多试几遍。
#
# ⚠️ **这个数必须大于「任务要求的次数」，否则点空一次就等于判死**（2026-10-07 修）。
# 浏览 / 点赞都是 ``x/3``（一天要 3 次），而对账只在「那一行**还没变成**『已完成』」
# 时才记一遍 —— 于是上限等于 3 的时候，**恰好要求每一遍都成功**：
# 中间只要有一步点空（点歪、或者那颗 👍 本来就是绿的、点赞被取消），
# 第 3 次对账就撞上 ``attempts >= 3`` ⇒ 记「今天做不成」，
# **哪怕计数已经 2/3、再来一次就成了**。
# ⇒ 6 = 要求 3 次 + 3 次容错。分享只要 1 次，容错更宽。
TASK_ATTEMPT_LIMIT = 6
# 「那颗 👍 已经是绿的 ⇒ 再滑一次换一张卡片」的次数上限。
# ⚠️ 必须有上限，否则「一路都是已点过的卡片」会变成死循环（项目红线：绝不死循环）。
LIKE_RESWIPE_LIMIT = 3

# ⚠️ 这一个是**横屏**坐标（1982x1132 兼容画布），不是竖屏的 —— 入口那一下发生在
# 横屏链路上。它同时是 ``navigation`` 里 ``web_community`` 锚点 (1540,180,400,160)
# 的中心，改一处要两边一起改。
WEB_COMMUNITY_ENTRY = (1740, 260)

#: 竖屏通道等转屏的时长（与 ``core/portrait._DEFAULT_ORIENTATION_TIMEOUT`` 同口径）。
#: 入口重试的日志要引用这个数字，所以在这里显式写出来当**同一个事实的单一来源** ——
#: 抄两处就会漂（而这里漂了只会让人误判「等了多久算久」）。
_ENTRY_ROTATION_WAIT_SECONDS = 20.0

#: 收尾时等模拟器转回横屏的时长。比入口短：这一步是「已经在收尾」，
#: 页面马上要关，等满 20 秒还没有转回来的迹象就别再拖住整条收尾了。
#: 即便等不到也只是让基类那步失败并留下原因，**不影响退出码**。
_EXIT_ROTATION_WAIT_SECONDS = 8.0

EXCHANGE_BACK = (36, 121)
EXCHANGE_BALANCE_BOX = (160, 246, 92, 46)
EXCHANGE_GAIN_POINTS_CARD = (800, 270)

TASKS_BACK = (35, 130)
TASKS_GOTO_EXCHANGE = (961, 554)
TASKS_BUTTON_X = 988
TASK_BUTTON_Y = {"browse": 1205, "like": 1349, "share": 1493}

ITEM_BACK = (62, 124)
POST_BACK = (154, 97)
POST_SHARE = (847, 1832)
# 2026-10-07 真机复验：点 (539,1665) 才把分享面板收掉（10-06 量的 1650 也在按钮里，
# 但那天实际生效的是 1665，就按复验过的写）。
SHARE_COPY_LINK = (539, 1665)
SHARE_CANCEL = (539, 1840)
REDEEM_CONFIRM = (539, 952)

# 底部大绿按钮的搜索带。给足高度：实测按钮在 y 1695~1847 之间移动（差 103px 是按钮高，
# 位置差 49px），上沿留到 1600 是为了页面再重排一点也还罩得住。
GREEN_BUTTON_BAND = (0, 1600, 1080, 320)
GREEN_BUTTON_MIN_AREA = 3000

# 每张商品卡的：点开它的坐标 / 「每日限购 x/y」徽章的位置。
# 徽章都在卡片右上角（实测卡1 x 382..422 / 卡2 x 921..961，y 380..408 与 960..988）。
CARD_POINTS = {1: (250, 639), 2: (789, 639), 3: (250, 1219), 4: (789, 1219)}
CARD_LIMIT_BOXES = {
    1: (382, 380, 40, 28),
    2: (921, 380, 40, 28),
    3: (382, 960, 40, 28),
    4: (921, 960, 40, 28),
}

@dataclass(frozen=True)
class TaskStep:
    """一条任务脚本里的**一步**。

    ## ⚠️ 每一步都必须自带出口验收，两类二选一

    按 ``docs/TRANSITION_CONTRACTS.md``：点击不等于成功，动作要「长眼睛」。

    - **换页的一步** ⇒ 填 ``next_page``（这一步做完应该在**哪一页**）。
      ⚠️ **不许把本页写进目标集合** —— 本页永远在集合里 ⇒ 验收永远通过 ⇒
      分不出「点了没生效」和「点了生效了」。2026-10-07 就栽在这上面：
      「看完退回信息流」那一步把目标写成 ``post_detail``（=本页），于是
      **点空了也判完成**（白等 33 秒）；而真退回信息流时又因为目标集合里
      没有 ``feed_home``，被判成「转场超时」⇒ **任务明明做成了，整条路线却失败**。
    - **不换页的一步** ⇒ 填 ``evidence``（靠页面内的什么变化验收）+
      ``verify``（``_drive_task`` 真去读的那个检查项）。

      为什么要真的读：光填一句声明，机器只校验「填了没有」。而点赞那颗 👍
      **是开关**，点错了会把别人的赞取消掉；滑动不生效会让下一步点错位置。
      所以这两步**必须看到业务结果**才准推进 —— 判据见 ``_evidence_seen``。

    ## 为什么要写「必须发生在哪一页」

    这三条任务的动作横跨信息流 / 帖子详情 / 分享面板三页，脚本一旦和当前页对不上，
    说明中间某一下没点中 ⇒ 必须**停下重来**，不能拿着错页的坐标硬点
    （那是 2026-10-05 竞技场入口那种事故的形状）。
    """

    kind: str                       # tap / tap_like / swipe
    page: str                       # 这一步必须在哪一页动手
    point: tuple[int, int]          # 点击点；滑动时是**起点**
    note: str                       # 日志用的人话
    next_page: str = ""             # 换页：这一步做完应该在哪一页
    evidence: str = ""              # 不换页：靠页面内什么变化验收（给人 + 给契约看）
    verify: str = ""                # 不换页：``_evidence_seen`` 真去读的检查项
    end: tuple[int, int] = ()       # 滑动的终点（只有 ``swipe`` 用）


# 不换页那一步的验收检查项。值就是 ``TaskStep.verify`` 的取值。
_VERIFY_LIKE_ON = "like_on"        # 卡片 👍 由灰转绿

# 出手之后最多等几帧看业务结果（主循环约一秒一帧 ⇒ 这里约 8 秒）。
# ⚠️ 等不到就**作废本遍**，绝不重复出手 —— 那颗 👍 是开关，点第二次会把赞取消。
_VERIFY_FRAME_LIMIT = 8

TASK_SCRIPT: dict[str, tuple[TaskStep, ...]] = {
    "browse": (
        TaskStep("tap", "feed_home", FEED_FIRST_POST, "点开第一张帖子", next_page="post_detail"),
        TaskStep("tap", "post_detail", POST_BACK, "看完退回信息流", next_page="feed_home"),
    ),
    "like": (
        # ⚠️ 这一步**必须走滑动**，不能当点击发出：``FEED_TASK_SCROLL_START`` 是起点、
        # ``end`` 是终点；只给一个点会变成「在信息流中间点一下」⇒ 点开一张帖子，
        # 下一步就对不上页（2026-10-07 之前的写法正是这样，点赞任务三遍全废）。
        # 滑动本身可逆、没有业务代价，所以不设强制校验（``verify`` 留空），
        # 它的成败由下一步「读 👍 颜色」和对账兜住。
        TaskStep(
            "swipe",
            "feed_home",
            FEED_TASK_SCROLL_START,
            "往下滑一次，把卡片 👍 带进视野",
            evidence="信息流滚动了一屏（卡片位置变了，本页不变）",
            end=FEED_TASK_SCROLL_END,
        ),
        # ⚠️ 这一步写成 ``tap_like``（不是 ``tap``）**只为让 ``_drive_task`` 认出它**：
        # 点之前先读一次那颗 👍 的颜色（它是**开关**：已经绿的再点一下会把点赞
        # **取消**掉 —— 计数不涨、白费一遍，2026-10-07 实测 ``act01`` 就白掉过一次），
        # 点之后还要读到「变绿了」才准推进（``verify=_VERIFY_LIKE_ON``）。
        TaskStep(
            "tap_like",
            "feed_home",
            FEED_CARD_LIKE,
            "点卡片右下角的 👍",
            evidence="卡片右下角那颗 👍 由灰转绿（绿底白手）",
            verify=_VERIFY_LIKE_ON,
        ),
    ),
    "share": (
        TaskStep("tap", "feed_home", FEED_FIRST_POST, "点开第一张帖子", next_page="post_detail"),
        TaskStep("tap", "post_detail", POST_SHARE, "点帖子底部的分享", next_page="share_sheet"),
        TaskStep("tap", "share_sheet", SHARE_COPY_LINK, "点「复制链接」", next_page="post_detail"),
        TaskStep("tap", "post_detail", POST_BACK, "返回信息流", next_page="feed_home"),
    ),
}

# 任务 key → 中文名（日志用；与「我的任务」页面上的字一一对应）。
TASK_LABELS = {row.key: row.label for row in pages.TASK_ROWS}

# 「网络连接异常」页退出重进的**次数上限**。
#
# 为什么要有上限：这一页不会自愈，退出去重进是唯一办法；但重进之后如果还是这页
# （H5 真死了 / 网络真断了），那就是「点 X → 重进 → 又见异常页」的乒乓——
# 两边的动作名不同，主循环那本「同一动作 4 次」的账**记不到它**（每次都是新动作），
# 于是会一直转下去。所以自己记一笔账，转两次就停。
NETWORK_RETRY_LIMIT = 2


class CommunityDataMissing(RuntimeError):
    """这条路线要用到的真机数据还没采到。

    ⚠️ 专门开一个类型，是为了让「缺数据」与「画面认不出」在日志里**分得开**：
    前者要去补采，后者要看现场帧。合成一个会让人一直查错方向。
    """


class CommunityState(Enum):
    WEB_ENTRY = "web_entry"      # 横屏·网页活动列表，要点「游戏社区」
    ENTERING = "entering"        # 已点「游戏社区」，等模拟器转成竖屏
    FEED = "feed"                # 信息流（首页）
    SIGNIN_DONE = "signin_done"  # 「签到成功！」弹窗，要关掉
    POST_DETAIL = "post_detail"
    SHARE_SHEET = "share_sheet"
    TASKS = "tasks"              # 我的任务（任务枢纽）
    EXCHANGE = "exchange"        # 兑换中心
    ITEM_DETAIL = "item_detail"
    ORDER_CONFIRM = "order_confirm"
    REDEEM_DONE = "redeem_done"
    CLOSING = "closing"          # 已点「退出社区」，等模拟器转回横屏
    BLOCKED = "blocked"          # 网络异常，H5 已死，要退出重进
    DONE = "done"


STATE_LABELS = {
    CommunityState.WEB_ENTRY: "网页活动列表（入口）",
    CommunityState.ENTERING: "已点社区入口，等转竖屏",
    CommunityState.FEED: "社区信息流",
    CommunityState.SIGNIN_DONE: "签到成功弹窗",
    CommunityState.POST_DETAIL: "帖子详情",
    CommunityState.SHARE_SHEET: "分享面板",
    CommunityState.TASKS: "我的任务",
    CommunityState.EXCHANGE: "兑换中心",
    CommunityState.ITEM_DETAIL: "商品详情",
    CommunityState.ORDER_CONFIRM: "订单确认",
    CommunityState.REDEEM_DONE: "兑换成功",
    CommunityState.CLOSING: "已退出社区，等转回横屏",
    CommunityState.BLOCKED: "网络异常",
    CommunityState.DONE: "已收工",
}


def state_label(state: CommunityState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class CommunityAction(RouteAction):
    """社区路线的一次点击（或一次滑动）。

    ⚠️ ``swipe_end`` 非空表示这一步是**滑动**：``point`` 是起点、``swipe_end`` 是终点。
    为什么要单独一个字段而不是靠动作名猜：``runner_base`` 主循环只会 ``runtime.click``，
    没有滑动通道（其它要滑动的路线都是自己直接调 ``runtime.swipe`` 绕开动作循环）。
    而社区这几步是状态机产出的动作，绕不开 ⇒ 由 Runner 认这个字段换发滑动
    （见 ``CommunityRunner._perform_action``）。
    """

    point: tuple[int, int]
    swipe_end: tuple[int, int] = ()


# ── 固定兑换清单 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RedemptionTarget:
    """清单里的一件商品。

    ⚠️ ``daily_limit`` 是**每日限购上限**，也是这条路线要兑到的**目标次数** ——
    不是「各兑一次」。用户 2026-10-06 明确纠正过：行动力 1/2 说明**还差一次**，
    要兑到 2/2 才算完。
    """

    card: int
    name: str
    price: int
    daily_limit: int


# 用户指定的固定清单。金币卡（3 号，15 积分）**刻意不在清单里**。
REDEMPTION_PLAN: tuple[RedemptionTarget, ...] = (
    RedemptionTarget(1, "行动力*30", 20, 2),
    RedemptionTarget(2, "下级万能装备强化石", 50, 1),
    RedemptionTarget(4, "下级万能饰品强化石", 50, 1),
)


@dataclass(frozen=True)
class ExchangeReadout:
    """兑换中心一帧上读到的数。

    ``limits`` 里每张卡是 ``(已兑, 限购上限)``；读不出来的卡是 ``None``。
    **读不出就是 None，不填 0** —— 后者会让路线以为「一次都没兑过」而重复兑换。
    """

    balance: Optional[int]
    balance_score: float
    limits: dict[int, Optional[tuple[int, int]]]

    def describe(self) -> str:
        parts = [f"余额={self.balance if self.balance is not None else '读不出'}"]
        for card in sorted(self.limits):
            value = self.limits[card]
            parts.append(
                f"卡{card}={value[0]}/{value[1]}" if value is not None else f"卡{card}=读不出"
            )
        return " ".join(parts)


def read_exchange(screen: np.ndarray, glyphs: dict[int, np.ndarray]) -> ExchangeReadout:
    """读兑换中心：积分余额 + 四张卡各自的「每日限购 x/y」。"""
    balance = read_digits(screen, EXCHANGE_BALANCE_BOX, glyphs)
    limits: dict[int, Optional[tuple[int, int]]] = {}
    for card, box in CARD_LIMIT_BOXES.items():
        pair: Readout = read_pair(screen, box, glyphs)
        limits[card] = pair.value if isinstance(pair.value, tuple) else None
    return ExchangeReadout(
        balance=balance.value if isinstance(balance.value, int) else None,
        balance_score=balance.score,
        limits=limits,
    )


@dataclass(frozen=True)
class RedeemStep:
    """兑换中心上「下一步做什么」的结论。"""

    kind: str                       # open_card / retry_empty / insufficient / done / blocked
    card: Optional[int] = None
    point: Optional[tuple[int, int]] = None
    reason: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.kind in {"insufficient", "done", "blocked"}


def plan_redeem(
    readout: Optional[ExchangeReadout],
    *,
    plan: Sequence[RedemptionTarget] = REDEMPTION_PLAN,
) -> RedeemStep:
    """按固定清单决定下一件要兑的商品。

    规则（用户 2026-10-06 拍板）：
    - 逐件兑到**每日限购上限**为止（不是各兑一次）；
    - 余额不够下一件 ⇒ **停下来**（``insufficient``），不跳过去兑更便宜的；
    - 限购读不出来的卡 ⇒ **不算完成、也不去点**，报 ``blocked`` 让人来看
      （默认成「已兑满」会漏任务，默认成「没兑过」会重复兑换）。

    ⚠️ ``readout=None`` 表示这一帧没读到（空列表态等），返回 ``retry_empty``。
    """
    if readout is None:
        return RedeemStep("retry_empty", reason="兑换中心还没读到商品（多半是空列表态）")
    if readout.balance is None:
        return RedeemStep("blocked", reason="积分余额读不出来，不敢决定要不要花")
    for target in plan:
        current = readout.limits.get(target.card)
        if current is None:
            return RedeemStep(
                "blocked",
                card=target.card,
                reason=f"卡{target.card}（{target.name}）的每日限购读不出来",
            )
        already, limit = current
        if already >= target.daily_limit:
            continue
        if already >= limit:
            # 游戏侧限购比清单目标还小 ⇒ 清单或读数是错的，别硬点。
            return RedeemStep(
                "blocked",
                card=target.card,
                reason=(
                    f"卡{target.card}（{target.name}）游戏限购只有 {limit}，"
                    f"清单却要求 {target.daily_limit} —— 两边对不上"
                ),
            )
        if readout.balance < target.price:
            return RedeemStep(
                "insufficient",
                card=target.card,
                reason=(
                    f"余额 {readout.balance} 不够换「{target.name}」（要 {target.price} 积分）"
                ),
            )
        return RedeemStep(
            "open_card",
            card=target.card,
            point=CARD_POINTS[target.card],
            reason=(
                f"「{target.name}」已兑 {already}/{target.daily_limit}，"
                f"还差 {target.daily_limit - already} 次（每件 {target.price} 积分）"
            ),
        )
    return RedeemStep("done", reason="清单上每件都已兑到每日限购上限")


# ── 底部绿按钮：必须每帧现量 ──────────────────────────────────────────────────


def locate_green_button(
    screen: np.ndarray,
    *,
    band: tuple[int, int, int, int] = GREEN_BUTTON_BAND,
    min_area: int = GREEN_BUTTON_MIN_AREA,
) -> Optional[tuple[int, int]]:
    """在画面底部按**颜色**找那颗大绿按钮，返回中心点；找不到返回 ``None``。

    为什么不用模板：那颗按钮「立即兑换」与「确认兑换」只差两个字，模板分不开
    （见 ``community_pages`` 模块头）；而它的**位置还会随页面重排移动**
    （商品详情页 y 中心 1795 / 订单确认页 1746，差 49px）。按颜色找既避开了文字差异，
    也天然每帧现量。套路与 ``fodder.py`` 里找「开始战斗」一致。

    ⚠️ 「已点过、按钮变禁用暗绿」的帧上会**找不到** —— 这是特性不是缺陷：
    回到这里时不该再点第二次。
    """
    x, y, w, h = band
    patch = screen[y : y + h, x : x + w]
    if patch.size == 0:
        return None
    # 屏幕是 RGB（见 core/portrait.py 的 capture）。
    red, green, blue = patch[:, :, 0].astype(int), patch[:, :, 1].astype(int), patch[:, :, 2].astype(int)
    mask = ((green > 120) & (green - red > 25) & (green - blue > 10)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    best_area = 0
    best_center: Optional[tuple[int, int]] = None
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area <= min_area or area <= best_area:
            continue
        best_area = area
        center_x, center_y = centroids[index]
        best_center = (x + int(round(center_x)), y + int(round(center_y)))
    return best_center


def locate_bottom_green_button(screen: np.ndarray) -> tuple[int, int]:
    """同 ``locate_green_button``，但找不到就抛 —— 用于「非点不可」的场合。"""
    point = locate_green_button(screen)
    if point is None:
        raise RuntimeError(
            "底部绿按钮没找到（按颜色定位）；可能是这页根本不是商品详情/订单确认，"
            "也可能是按钮已被点过、处在禁用暗绿态"
        )
    return point


def is_portrait_frame(screen: np.ndarray) -> bool:
    """这一帧是不是竖屏段（1080x1920）。

    ⚠️ 只认**严格等于** ``PORTRAIT_CANVAS``：竖屏通道自己就承诺拿不到这个尺寸时
    当场报错（见 ``core/portrait.py``），所以这里看到别的尺寸只可能是「还在横屏」
    或「转屏动画的中间帧」—— 两种都该按「不是竖屏」处理（不点、等）。
    """
    return (
        screen.shape[0] == PORTRAIT_CANVAS[1] and screen.shape[1] == PORTRAIT_CANVAS[0]
    )


def _box_patch(screen: np.ndarray, box: tuple[int, int, int, int]) -> Optional[np.ndarray]:
    x, y, w, h = box
    if y < 0 or x < 0 or y + h > screen.shape[0] or x + w > screen.shape[1]:
        return None
    patch = screen[y : y + h, x : x + w]
    return patch if patch.size else None


def feed_signin_state(screen: np.ndarray) -> str:
    """信息流上「今天签没签」：``"todo"`` / ``"done"`` / ``"unknown"``。

    ## 判据是颜色，不是形状

    「每日签到」图标**未签到**时是彩色的（黄墨水瓶 + 棕羽毛笔，右上角还有红点），
    **签到之后整块变灰**。真机两态的平均饱和度是 49.1 与 0.0 —— 中间没有灰带。

    ## 三态，绝不猜

    ``"unknown"`` 有两种来路，都必须说不知道、不许往两头猜：

    1. 那一块**出界**（画面尺寸不对）；
    2. 那一块**太暗**（``SIGNIN_ICON_MIN_VALUE``）—— 弹窗的压暗背板会把彩色图标
       也压成 0 饱和度，照读会得出「已签到」这个**错结论**，于是当天漏签。

    ⚠️ 亮度闸门不是洁癖：2026-10-07 实测「签到成功」弹窗那一帧这一块 S=0.0、V 也低，
    而正常信息流这一块 V 是 200+。少了它，弹窗一出现就会被读成「已签到」。
    """
    patch = _box_patch(screen, SIGNIN_ICON_BOX)
    if patch is None:
        return "unknown"
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    saturation = float(hsv[:, :, 1].mean())
    value = float(hsv[:, :, 2].mean())
    if value < SIGNIN_ICON_MIN_VALUE:
        return "unknown"
    return "todo" if saturation >= SIGNIN_ICON_SATURATION else "done"


def card_like_is_on(screen: np.ndarray) -> Optional[bool]:
    """信息流卡片右下角那颗 👍 是不是**已经点过**（绿底白手）。

    读不出来（出界 / 画面尺寸不对）返回 ``None``。

    ⚠️ 为什么必须读一下再点：那颗 👍 是**开关**。已绿的再点一次会把点赞**取消**，
    计数不但不涨还会倒扣（2026-10-07 实测 `act01` 把一张已绿的卡片点灰、白花一次额度）。
    """
    patch = _box_patch(screen, FEED_CARD_LIKE_BOX)
    if patch is None:
        return None
    red, green, blue = (
        patch[:, :, 0].astype(int),
        patch[:, :, 1].astype(int),
        patch[:, :, 2].astype(int),
    )
    mask = (green > 120) & (green - red > 25) & (green - blue > 10)
    return bool(mask.mean() >= 0.08)


# ── 状态机 ────────────────────────────────────────────────────────────────────


@dataclass
class CommunityProgress:
    """这条路线跑到哪了。**只记事实**，不记推断。"""

    signed_in: Optional[bool] = None
    tasks: dict[str, str] = field(default_factory=dict)
    redeemed: dict[int, int] = field(default_factory=dict)
    balance: Optional[int] = None

    def tasks_all_done(self) -> bool:
        return bool(self.tasks) and all(state == "done" for state in self.tasks.values())


class CommunityStateMachine:
    """纯决策：给一帧竖屏画面，说下一步点哪。

    与项目其它状态机同构：只做判断，不碰 ``sleep`` / 不点、不认识 Runtime。
    """

    def __init__(
        self,
        templates: dict[str, np.ndarray],
        glyphs: dict[int, np.ndarray],
        *,
        plan: Sequence[RedemptionTarget] = REDEMPTION_PLAN,
        state: CommunityState = CommunityState.WEB_ENTRY,
    ) -> None:
        self.templates = templates
        self.glyphs = glyphs
        self.plan = tuple(plan)
        self.state = state
        # ⚠️ 主循环每轮都读它（`run()` 的循环条件、`_check_cycle_completed`），
        # 漏了就是实跑第一轮 AttributeError —— 单看状态机自己是发现不了的。
        self.completed_cycles = 0
        self.progress = CommunityProgress()
        self.last_redeem: Optional[RedeemStep] = None
        self.last_page: Optional[pages.PageJudgement] = None
        # 上一帧「为什么没出手 / 为什么这么出手」。给主循环的等待心跳用：
        # 判据沉默时日志不能是空的（2026-10-04 那次的坑）。
        self.last_reason = ""
        # 非空表示「要点码 2 退出」的原因（积分不够）。为什么用字段而不是直接抛：
        # 见 ``_on_exchange_center`` 的 insufficient 分支 —— 得先把社区关掉转回横屏。
        self.stop_reason = ""
        self._network_retries = 0
        self._confirmed_page = ""
        # 「每日签到」那一下点过没有。点过就一直等弹窗（实测可能等到一分多钟），
        # **不重复点** —— 重复点没有意义，只会把日志刷满。
        self.signin_clicked = False
        # 到兑换中心只是为了**路过**（去「我的任务」的必经之路：兑换中心 → 获取积分卡）。
        # 置位时 `_on_exchange_center` 只点「获取积分卡」，不做兑换决策。
        self.via_exchange = False
        # 正在跑哪条每日任务（`browse` / `like` / `share`），以及跑到脚本第几步。
        # 非空时信息流 / 帖子详情 / 分享面板三页都交给 `_drive_task` 推脚本。
        self.active_task: Optional[str] = None
        self.task_step = 0
        # 「已经出手、正在等业务结果」的检查项（``TaskStep.verify``），空表示不等。
        # 等不到就作废本遍，**绝不重复出手**（那颗 👍 是开关）。
        self.pending_verify = ""
        self._verify_frames = 0
        # 「点赞」那一步因为 👍 已经是绿的而**临时再滑一次**的次数（每次 attempt 重置）。
        # 没有它，一次「一路都是已点过的卡片」就能把主循环卡在信息流里空转。
        self.like_reswipes = 0
        # 每条任务试过几遍、哪几条已经判定「今天做不成」。
        self.task_attempts: dict[str, int] = {}
        self.stuck_tasks: set[str] = set()
        # 上一次在「我的任务」页读到的三行状态（用来判「刚跑完的那条涨没涨」）。
        self._tasks_before: dict[str, str] = {}

    # ---- 观察 ----

    def observe(self, screen: np.ndarray) -> pages.PageJudgement:
        """判当前在哪一页。认不出时**返回 unknown**，不抛（上层据此等待/告警）。"""
        observations = pages.observe_pages(screen, self.templates)
        top = pages.top_page(observations)
        if top is not None:
            return pages.PageJudgement(top.name, top.confidence, observations)
        # 栈内没有盖层 ⇒ 试栈根兜底（首页列表 / 商品详情这两页没有专有判据）。
        for root in ("feed_home", "item_detail"):
            resolved = pages.resolve_stack_root(observations, root)
            if resolved is not None:
                return resolved
        return pages.PageJudgement("unknown", 0.0, observations)

    # ---- 决策 ----

    def next_action(self, screen: np.ndarray) -> Optional[CommunityAction]:
        if self.state is CommunityState.DONE:
            self.last_reason = "已收工，不再出手"
            return None
        portrait = is_portrait_frame(screen)
        if self.state is CommunityState.CLOSING:
            # 已点「退出社区」⇒ 这段时间**不判页面**：页面正在消失、窗口正在旋转，
            # 拿一堆半截画面去认锚点只会认出一堆 `unknown` 并抛「认不出」。
            # 只看方向：转回横屏就收工，还在竖屏就等。
            if portrait:
                self.last_reason = "已点退出社区，等模拟器转回横屏"
                return None
            return self._finish_closing()
        if not portrait:
            return self._on_landscape(screen)
        page = self.observe(screen)
        self.last_page = page
        self._confirmed_page = page.name
        # ⚠️ **入口的出口标志：方向对了 ≠ 社区打开了**（2026-10-07 补）。
        #
        # 刚转进竖屏的那一两秒，H5 往往还在加载：拿到的是 1080x1920 的画面，
        # 但内容可能是一片白 / 半截骨架。此时 ``observe`` 判不出 ``feed_home``，
        # 下面就会抛「认不出画面」，主循环按**失败**收尾 —— 而它其实只是**还没到**。
        #
        # 规范里那一档叫「来源已离开、目标未稳 ⇒ 只等」。这里落地成：
        # **已点过入口、方向已转竖屏、但页面还认不出 ⇒ 返回 None（只等）**，
        # 由主循环的「认不出画面 → 等/唤醒」通道处理，够久才超时。
        # ⚠️ 只在 ``ENTERING`` 生效：竖屏段的其它状态认不出仍然是硬错误 ——
        #    那时页面早该在了，认不出就是真出问题了，不该拿「可能是加载中」当借口。
        if self.state is CommunityState.ENTERING and page.name == "unknown":
            self.last_reason = (
                "已转成竖屏但社区页面还没加载出来（转场中），只等不判失败"
            )
            return None
        handler = {
            "network_error": self._on_network_error,
            "redeem_done": self._on_redeem_done,
            "order_confirm": self._on_order_confirm,
            "item_detail": self._on_item_detail,
            "exchange_empty": self._on_exchange_empty,
            "exchange_center": self._on_exchange_center,
            "tasks_page": self._on_tasks,
            "share_sheet": self._on_share_sheet,
            "post_detail": self._on_post_detail,
            "signin_done": self._on_signin_done,
            "feed_home": self._on_feed,
        }.get(page.name)
        if handler is None:
            # 认不出画面：**不猜**。交给主循环的「认不出画面」通道处理（它会重试/告警）。
            self.last_reason = f"社区画面认不出（最高分 {page.confidence:.4f}）"
            raise UnrecognizedCommunityScreen(
                f"社区画面认不出（最高分 {page.confidence:.4f}）；"
                f"已知观察={[o.describe() for o in page.observations]}"
            )
        return handler(screen, page)

    def _finish_closing(self) -> None:
        """退出社区之后、画面已回到横屏 ⇒ 收工。

        到这一帧之前**一直不抛任何结论**，就是为了让「回大厅」那一步拿到横屏画面
        （见 ``_on_exchange_center`` 的 ``insufficient`` 分支）。
        """
        if self.stop_reason:
            self.state = CommunityState.DONE
            raise RedeemBudgetExhausted(self.stop_reason)
        self._finish("社区页已关闭、画面转回横屏" + self._stuck_note())
        return None

    def _on_landscape(self, screen: np.ndarray) -> Optional[CommunityAction]:
        """横屏帧上的决策。

        ⚠️ **入口那一下与退出那一下都发生在横屏**：从大厅走到网页活动列表走的是横屏
        链路，点完「游戏社区」模拟器才转成竖屏；退出社区之后又会转回来。
        所以这里不能一律「非竖屏就不动」—— 那样入口与收尾永远触发不了。

        ## 入口的出口标志（表 A / 表 B 的 N4）

        点「游戏社区」之后，**必须看到下面两样才算这一步走通**，缺一不可：

        1. **方向证据**：拿到一帧 ``1080x1920``（竖屏画布）。这是「转屏了」。
        2. **页面证据**：那一帧能判成 ``feed_home``（社区信息流，底栏「首页」激活）。

        ⚠️ 2026-10-07 修的就是这里：原来这个状态**只看方向**（还是横屏就再点一次），
        于是有两种失败都判成同一件事：
          - 10:51 点了 2 秒就判失败进收尾（方向变了但画布还是不对 ⇒ 崩）；
          - 10:52 等满 20 秒报「转屏超时」（方向压根没变 ⇒ 重点了 4 次）。
        现在方向之外还看画幅与页面，**判不出的那一刻不会说「没点中」**，
        只会说「还没打开、等」——「认不出」与「没点中」是两件事，混起来就是瞎重试。
        """
        if self.state is CommunityState.WEB_ENTRY:
            self.state = CommunityState.ENTERING
            self.last_reason = "网页活动列表上点「游戏社区」，之后模拟器会切成竖屏"
            return CommunityAction(
                "enter_community",
                WEB_COMMUNITY_ENTRY,
                source_page="web_activity_list",
                target_pages=("feed_home",),
                reason=self.last_reason,
            )
        if self.state is CommunityState.ENTERING:
            # ⚠️ 这里能收到横屏帧，只说明「**此刻**还没转过来」，
            # 不说明「那一下没点中」—— 转屏动画本身就要一两秒。所以重试的判据是
            # **有界等待**：竖屏通道自己会等 20 秒，进来这里说明那 20 秒已经耗尽了
            # （或者方向对了但画布还不对）。此时才允许再点一次。
            #
            # 次数与间隔由主循环给（``_action_retry_seconds("enter_community")``
            # 比 20 秒那段等待更长），4 次还不行就响亮失败 —— 不会无限点。
            self.last_reason = (
                "已点过入口但这一帧仍是横屏（竖屏通道已等满 "
                f"{_ENTRY_ROTATION_WAIT_SECONDS:.0f} 秒），重新点一次「游戏社区」"
            )
            return CommunityAction(
                "enter_community",
                WEB_COMMUNITY_ENTRY,
                source_page="web_activity_list",
                target_pages=("feed_home",),
                reason=self.last_reason,
            )
        # 别的状态拿到横屏帧：**不点**，等（多半是转屏动画期间）。
        self.last_reason = f"横屏帧，当前状态={state_label(self.state)}，等待画面转过去"
        return None

    def preview(self, screen: np.ndarray):
        snapshot = self._snapshot()
        try:
            action = self.next_action(screen)
            return action, (self.state, self._confirmed_page)
        finally:
            self._restore(snapshot)

    def _snapshot(self) -> tuple:
        """``preview`` 用的业务进度快照。

        ⚠️ 每加一个「``next_action`` 会改的字段」都要同时加到这里 —— 漏了就会把
        「一次点击」记成两次（这是项目里踩过的坑）。所以这里写成**显式元组**，
        而不是 ``__dict__`` 拷贝之类的聪明写法：漏了能一眼看出来。
        """
        return (
            self.state,
            dict(self.progress.tasks),
            dict(self.progress.redeemed),
            self.progress.balance,
            self.progress.signed_in,
            self.last_redeem,
            self.last_page,
            self.last_reason,
            self.stop_reason,
            self._network_retries,
            self._confirmed_page,
            self.signin_clicked,
            self.via_exchange,
            self.active_task,
            self.task_step,
            self.pending_verify,
            self._verify_frames,
            self.like_reswipes,
            dict(self.task_attempts),
            set(self.stuck_tasks),
            dict(self._tasks_before),
        )

    def _restore(self, snapshot: tuple) -> None:
        (
            self.state,
            self.progress.tasks,
            self.progress.redeemed,
            self.progress.balance,
            self.progress.signed_in,
            self.last_redeem,
            self.last_page,
            self.last_reason,
            self.stop_reason,
            self._network_retries,
            self._confirmed_page,
            self.signin_clicked,
            self.via_exchange,
            self.active_task,
            self.task_step,
            self.pending_verify,
            self._verify_frames,
            self.like_reswipes,
            self.task_attempts,
            self.stuck_tasks,
            self._tasks_before,
        ) = snapshot

    # ---- 各页的处理 ----

    def _on_network_error(self, screen: np.ndarray, page) -> CommunityAction:
        """H5 死了（「网络连接异常，下拉刷新」）。退出去重进 —— 这页不会自己恢复。

        ⚠️ 上限见 ``NETWORK_RETRY_LIMIT``：重进之后还是这页就是乒乓，转两次就停。
        """
        self._network_retries += 1
        if self._network_retries > NETWORK_RETRY_LIMIT:
            self.state = CommunityState.BLOCKED
            raise RuntimeError(
                f"社区网页连续 {self._network_retries} 次报网络异常，退出去重进没用；"
                "H5 起不来了（网络断了 / 活动页维护中），停止并留诊断"
            )
        # 退回网页活动列表：`_after_action_click` 会把通道切回横屏，而状态回到
        # ``WEB_ENTRY`` ⇒ 下一帧会自动重进一次。
        self.state = CommunityState.WEB_ENTRY
        return CommunityAction(
            "logout_community",
            FEED_CLOSE,
            source_page=page.name,
            target_pages=("web_activity_list",),
            reason=f"网络异常页不会自愈，关闭社区后重新进入（第 {self._network_retries} 次）",
        )

    def _on_redeem_done(self, screen: np.ndarray, page) -> CommunityAction:
        self.state = CommunityState.REDEEM_DONE
        return CommunityAction(
            "ack_redeem_done",
            REDEEM_CONFIRM,
            source_page=page.name,
            target_pages=("item_detail",),
            reason="兑换成功弹窗，点「确认」收起",
        )

    def _on_order_confirm(self, screen: np.ndarray, page) -> Optional[CommunityAction]:
        self.state = CommunityState.ORDER_CONFIRM
        point = locate_green_button(screen)
        if point is None:
            # ⚠️ 点过「确认兑换」之后按钮会变禁用暗绿（颜色定位找不到），而结果要
            # **>7 秒**（实测 3~40 秒）才弹。这**不是**故障，是正常的「等结果」——
            # 所以这里返回 None（不出手、等下一帧），**不要**报错：
            # 报错会被主循环当成「画面认不出」去重试，白等一轮还容易误判。
            # 状态超时（`_TIMEOUT_SECONDS` 里给得比最长等待更宽）才是这条等待的上限。
            self.last_reason = "订单确认页按钮已是禁用态，等兑换结果（实测 3~40 秒）"
            return None
        return CommunityAction(
            "confirm_redeem",
            point,
            source_page=page.name,
            target_pages=("redeem_done", "item_detail"),
            reason="订单确认页，点「确认兑换」（位置逐帧现量）",
        )

    def _on_item_detail(self, screen: np.ndarray, page) -> CommunityAction:
        self.state = CommunityState.ITEM_DETAIL
        point = locate_bottom_green_button(screen)
        return CommunityAction(
            "open_order_confirm",
            point,
            source_page=page.name,
            target_pages=("order_confirm",),
            reason="商品详情，点「立即兑换」进入订单确认（位置逐帧现量）",
        )

    def _on_exchange_empty(self, screen: np.ndarray, page) -> CommunityAction:
        """空列表态：退到信息流再进来一次。"""
        self.state = CommunityState.EXCHANGE
        return CommunityAction(
            "leave_empty_exchange",
            EXCHANGE_BACK,
            source_page=page.name,
            in_page_evidence="退出空列表的兑换中心，回信息流后重新进入",
            reason="兑换中心是空列表（偶发），退回去重进",
        )

    def _on_exchange_center(self, screen: np.ndarray, page) -> CommunityAction:
        self.state = CommunityState.EXCHANGE
        if self.via_exchange:
            # 只是路过：这条路线从信息流去「我的任务」的必经之路就是
            # 兑换中心 →「获取积分卡」（底栏那个「我的」是社区个人主页，不是我的任务，
            # 2026-10-07 实测点过去只得到一张认不出的页面）。
            self.via_exchange = False
            return CommunityAction(
                "goto_tasks_card",
                EXCHANGE_GAIN_POINTS_CARD,
                source_page=page.name,
                target_pages=("tasks_page",),
                reason="路过兑换中心，点「获取积分卡」进我的任务（这一帧不做兑换决策）",
            )
        readout = read_exchange(screen, self.glyphs)
        if readout.balance is not None:
            self.progress.balance = readout.balance
        for card, value in readout.limits.items():
            if value is not None:
                self.progress.redeemed[card] = value[0]
        step = plan_redeem(readout, plan=self.plan)
        self.last_redeem = step
        if step.kind == "open_card" and step.point is not None:
            return CommunityAction(
                "open_item",
                step.point,
                source_page=page.name,
                target_pages=("item_detail",),
                reason=f"卡{step.card}：{step.reason}",
            )
        if step.kind == "insufficient":
            # 余额不够 —— 这是**正常业务退出**（退出码 2），不是故障。
            #
            # ⚠️ 但**不在这里直接抛**：此刻人还停在社区的竖屏页面里，直接抛出去，
            # 收尾那步要拿横屏通道去取图，会抛「render size changed」——
            # 于是「资源耗尽」这条正常结论会变成一次看不懂的失败，
            # 而且模拟器被留在竖屏（下一个任务连大厅都回不去）。
            # 所以先按正常出口把社区关掉、等转回横屏，到横屏那一帧再抛。
            self.stop_reason = step.reason
            self.state = CommunityState.FEED
            return CommunityAction(
                "leave_exchange",
                EXCHANGE_BACK,
                source_page=page.name,
                target_pages=("feed_home",),
                reason=f"{step.reason}；先退回信息流准备退出社区",
            )
        if step.kind == "done":
            self.state = CommunityState.FEED
            return CommunityAction(
                "leave_exchange",
                EXCHANGE_BACK,
                source_page=page.name,
                target_pages=("feed_home",),
                reason="兑换清单已跑满，回信息流收工",
            )
        if step.kind == "retry_empty":
            return CommunityAction(
                "leave_empty_exchange",
                EXCHANGE_BACK,
                source_page=page.name,
                in_page_evidence="空列表态退回，准备重进",
                reason=step.reason,
            )
        raise CommunityDataMissing(f"兑换中心无法决策：{step.reason}")

    def _on_tasks(self, screen: np.ndarray, page) -> CommunityAction:
        """「我的任务」：三条每日任务 + 去兑换。

        ## 循环的骨架

        ```
        我的任务 --点「去完成」--> 信息流 --按脚本做完--> (兑换中心 → 获取积分卡)
             ^                                                        |
             +---------- 回来对账：那一行变成「已完成」了吗？ -----------+
        ```

        ⚠️ 为什么必须**回来对账**：这三条任务的成败只有页面上那个按钮说得准 ——
        脚本跑完不等于这一行变成「已完成」（2026-10-07 实测：同一套动作，一次涨、一次没涨）。
        「已完成」是唯一权威，脚本只是手段。所以每条任务「跑一遍 → 回来看这一行」，
        成了才算数，没成再来一遍，连着 ``TASK_ATTEMPT_LIMIT`` 遍都没成
        就**记一笔、跳过它继续跑别的**（绝不死循环，也绝不无声跳过）。

        ⚠️ **措辞纪律**：这里读的是**按钮长相**（``task_todo`` / ``task_done`` 两个锚点），
        **不是** ``x/3`` 那个数字。写日志时别再写「计数没动」——
        3 次制的任务里计数每遍都在动，只是按钮要到第 3 遍才翻成「已完成」；
        照「计数没动」的说法排错会被带偏（2026-10-07 修正）。
        """
        self.state = CommunityState.TASKS
        rows = pages.observe_task_rows(screen, self.templates)
        self.progress.tasks = {row.key: row.state for row in rows}
        unknown = [row.label for row in rows if row.state == "unknown"]
        if unknown:
            raise CommunityDataMissing(
                "「我的任务」有三行认不出做没做：" + "、".join(unknown)
            )
        if self.active_task is not None:
            script = TASK_SCRIPT.get(self.active_task, ())
            if self.task_step < len(script):
                # 脚本**一步都没走完**就回到了这一页 ⇒ 那一下「去完成」没点中。
                # 再点一次即可，**不记账** —— 一遍都没跑完就记一笔，会把三次机会
                # 白白烧在「点击没生效」上（2026-10-07 写这一版时踩过）。
                # 一直点不动由主循环那本「同一动作 4 次」的账兜住。
                return self._start_task(self.active_task, page)
            retry = self._reconcile_task(rows, page)
            if retry is not None:
                return retry
        pending = next(
            (row for row in rows if row.is_todo and row.key not in self.stuck_tasks),
            None,
        )
        if pending is not None:
            if pending.key in TASK_SCRIPT:
                return self._start_task(pending.key, page)
            # 页面上有这一行、却没有对应脚本 ⇒ 记一笔「今天做不成」，别在这儿空转。
            self.stuck_tasks.add(pending.key)
            self.last_reason = f"任务「{pending.label}」没有执行脚本，跳过它继续"
        if not self._redeem_finished():
            return CommunityAction(
                "goto_exchange",
                TASKS_GOTO_EXCHANGE,
                source_page=page.name,
                target_pages=("exchange_center", "exchange_empty"),
                reason="三条任务都有结论了，走「去兑换」进兑换中心",
            )
        # 任务与兑换都完成 ⇒ 回信息流（那里才有「退出社区」的 X），到那儿再收官。
        # ⚠️ 不在这里直接 `_finish()`：收工前必须把社区页关掉、让模拟器转回横屏，
        # 否则收尾「回大厅」那一步拿着横屏通道去取竖屏画面，会直接抛
        # 「render size changed」——任务明明做完了，却报一个看不懂的失败。
        self.state = CommunityState.FEED
        return CommunityAction(
            "leave_tasks",
            TASKS_BACK,
            source_page=page.name,
            target_pages=("feed_home",),
            reason="任务与兑换都完成，退回信息流准备退出社区",
        )

    def _start_task(self, key: str, page) -> CommunityAction:
        """点这一行的「去完成」，并把脚本从头排上。"""
        self.active_task = key
        self.task_step = 0
        self.like_reswipes = 0
        self.pending_verify = ""
        self._verify_frames = 0
        label = TASK_LABELS.get(key, key)
        return CommunityAction(
            "start_task",
            (TASKS_BUTTON_X, TASK_BUTTON_Y[key]),
            source_page=page.name if page is not None else "tasks_page",
            target_pages=("feed_home",),
            reason=f"任务「{label}」还没完成，点它那行的「去完成」",
        )

    def _reconcile_task(self, rows, page) -> Optional[CommunityAction]:
        """回到「我的任务」时给刚跑完的那条任务**对账**。

        返回 ``None`` 表示这条已经了结（做成了 / 判定今天做不成），调用方接着挑下一条；
        返回一个动作表示「还没做成，原地再来一遍」。
        """
        key = self.active_task
        if key is None:  # pragma: no cover - 调用方已经判过
            return None
        row = next((item for item in rows if item.key == key), None)
        label = row.label if row is not None else TASK_LABELS.get(key, key)
        self.active_task = None
        self.task_step = 0
        self.pending_verify = ""
        self._verify_frames = 0
        if row is not None and row.is_done:
            self.task_attempts.pop(key, None)
            self.last_reason = f"任务「{label}」做成了，计数已推进"
            return None
        attempts = self.task_attempts.get(key, 0) + 1
        self.task_attempts[key] = attempts
        if attempts >= TASK_ATTEMPT_LIMIT:
            self.stuck_tasks.add(key)
            self.last_reason = (
                f"任务「{label}」连着 {attempts} 遍做完、这一行始终没变成「已完成」，"
                "判定今天做不成，跳过它继续跑别的"
            )
            return None
        self.last_reason = (
            f"任务「{label}」做完第 {attempts} 遍，这一行还没变成「已完成」，再来一遍"
        )
        return self._start_task(key, page)

    def _drive_task(self, screen: np.ndarray, page) -> Optional[CommunityAction]:
        """按脚本推一条每日任务（信息流 / 帖子详情 / 分享面板三页共用）。

        ⚠️ 脚本每一步都写着「必须停在哪一页」。对不上就说明中间某一下没点中 ——
        这时**不许硬点**（拿错页的坐标点下去正是 2026-10-05 竞技场入口那种事故的形状），
        本遍作废、原路退回「我的任务」交给对账去判。

        ## 出口验收分两类，别混（``TRANSITION_CONTRACTS.md``）

        - **换页的一步** ⇒ ``target_pages=(step.next_page, …)``，**不含本页**。
          ⚠️ 把本页写进去 = 验收永远通过 = 分不出「点了没生效」和「点了生效了」
          （2026-10-07 实跑：退回信息流那一步把本页 ``post_detail`` 写进目标集合，
          于是**点空了也判完成**；真退回 ``feed_home`` 时又因集合里没有它而被判
          「转场超时」⇒ 任务做成了、整条路线却失败）。
        - **不换页的一步**（滑动 / 点赞）⇒ ``in_page_evidence=step.evidence``。
          其中点赞还要**真的读到「变绿」**才准推进（``step.verify``）——
          那颗 👍 是开关，重复点会把赞取消，所以只点一次、之后只等结果。

        ⚠️ ``screen`` 是为了 ``tap_like`` 那一步**点之前读颜色**、点之后**读结果**用的。
        """
        key = self.active_task
        if key is None:  # pragma: no cover - 调用方已经判过
            return None
        label = TASK_LABELS.get(key, key)
        script = TASK_SCRIPT.get(key, ())
        # ⚠️ 这里**不清** ``active_task`` —— 「回我的任务对账」那一步要靠它认出
        # 「刚跑的是哪一条」。清早了 `_on_tasks` 就会把任务当新的重排一遍，
        # 计数永远对不上账（2026-10-07 写这一版时踩过）。清空只在 `_reconcile_task` 里做。
        if self.task_step >= len(script):
            return self._return_to_tasks(page, f"任务「{label}」动作做完，回去核对计数")
        step = script[self.task_step]
        if page.name != step.page:
            return self._return_to_tasks(
                page,
                f"任务「{label}」第 {self.task_step + 1} 步该在「{step.page}」动手，"
                f"实际停在「{page.name}」——中间那一下没点中",
            )
        # 上一步已经出手、但业务结果还没看到 ⇒ 先核对，**绝不出手第二次**。
        if self.pending_verify:
            return self._await_step_result(screen, page, step, label)
        if step.kind == "tap_like":
            already = card_like_is_on(screen)
            if already is None:
                # 认不出就说认不出 —— 拿「也许没点过」当答案就是盲点，而盲点的后果是
                # 把别人的赞取消掉。
                return self._return_to_tasks(
                    page, f"任务「{label}」读不出那颗 👍 的颜色，不敢盲点，本遍作废"
                )
            if already:
                # 这一张我已经点过了 ⇒ 再滑一次，让**下一张**卡片进到同一个位置。
                if self.like_reswipes >= LIKE_RESWIPE_LIMIT:
                    return self._return_to_tasks(
                        page,
                        f"任务「{label}」连滑 {self.like_reswipes} 次，卡片全是我点过的，"
                        "本遍作废",
                    )
                self.like_reswipes += 1
                return self._step_action(
                    "task_like_reswipe",
                    TaskStep(
                        "swipe",
                        "feed_home",
                        FEED_TASK_SCROLL_START,
                        "",
                        evidence="信息流再滚动一屏，换一张没点过的卡片（本页不变）",
                        end=FEED_TASK_SCROLL_END,
                    ),
                    page,
                    reason=(
                        f"任务「{label}」：这颗 👍 已经是绿的（点下去会取消点赞），"
                        f"再往下滑一次换一张卡片（第 {self.like_reswipes}/{LIKE_RESWIPE_LIMIT} 次）"
                    ),
                )
            self.like_reswipes = 0
        self.task_step += 1
        action = self._step_action(
            f"task_{key}_{self.task_step}", step, page, reason=f"任务「{label}」：{step.note}"
        )
        if step.verify:
            # 记下「等什么」，下一帧先核对再推进 —— 声明归声明，结果要真读到。
            self.pending_verify = step.verify
            self._verify_frames = 0
        return action

    def _step_action(
        self,
        name: str,
        step: "TaskStep",
        page,
        *,
        reason: str,
    ) -> CommunityAction:
        """把脚本里的一步包装成带出口验收的动作。

        ⚠️ 换页的一步只写 ``next_page``，另外两个是**全局异常态**（签到弹窗可能迟到
        一分多钟、网络异常页会把 H5 弄死）；它们出现时状态机会优先处理，
        所以必须让这一步的验收放行，否则会卡在「页面既不是来源也不是目标」的缝里。
        """
        if step.next_page:
            evidence = {
                "target_pages": (step.next_page, "signin_done", "network_error"),
            }
        else:
            evidence = {"in_page_evidence": step.evidence}
        if step.kind == "swipe":
            return CommunityAction(
                name,
                step.point,
                swipe_end=step.end,
                source_page=page.name,
                reason=reason,
                **evidence,
            )
        return CommunityAction(
            name, step.point, source_page=page.name, reason=reason, **evidence
        )

    def _await_step_result(
        self, screen: np.ndarray, page, step: "TaskStep", label: str
    ) -> Optional[CommunityAction]:
        """上一步已经出手，等它的业务结果。

        ⚠️ **绝不出手第二次**：那颗 👍 是开关，第一次其实生效了而我们没读到时
        再点一次会把赞**取消**掉。所以这里只等、不对就作废本遍 —— 交给「我的任务」
        对账去判要不要再来一遍（计数才是权威）。
        """
        if self._evidence_seen(screen, self.pending_verify):
            self.pending_verify = ""
            self._verify_frames = 0
            self.last_reason = f"任务「{label}」：已看到「{step.evidence}」，这一步做成了"
            return self._return_to_tasks(page, f"任务「{label}」动作做完，回去核对计数")
        self._verify_frames += 1
        if self._verify_frames >= _VERIFY_FRAME_LIMIT:
            self.pending_verify = ""
            self._verify_frames = 0
            return self._return_to_tasks(
                page,
                f"任务「{label}」出手之后等了 {_VERIFY_FRAME_LIMIT} 帧也没看到"
                f"「{step.evidence}」，本遍作废（不重复点，怕点反）",
            )
        self.last_reason = (
            f"任务「{label}」已出手，等看到「{step.evidence}」"
            f"（第 {self._verify_frames}/{_VERIFY_FRAME_LIMIT} 帧）"
        )
        return None

    @staticmethod
    def _evidence_seen(screen: np.ndarray, verify: str) -> bool:
        """``verify`` 这一项在当前帧上成立了吗。

        ⚠️ 只认有实测依据的检查项。没有检查项（``verify=""``）意味着这一步的验收
        靠换页或下一帧重判画面，这里不拦 ⇒ 返回 True。
        """
        if verify == _VERIFY_LIKE_ON:
            return card_like_is_on(screen) is True
        return True

    def _return_to_tasks(self, page, reason: str) -> CommunityAction:
        """从任意一页把路线带回「我的任务」。

        路径是**信息流 → 兑换中心 →「获取积分卡」→ 我的任务**。⚠️ 底栏那个「我的」
        不是我的任务，是社区个人主页（2026-10-07 实测：点过去得到一张认不出的页面）。
        """
        if page.name == "feed_home":
            self.via_exchange = True
            return CommunityAction(
                "back_to_tasks_via_exchange",
                FEED_ICON_EXCHANGE,
                source_page=page.name,
                target_pages=("exchange_center", "exchange_empty"),
                reason=f"{reason}；经兑换中心回我的任务",
            )
        if page.name == "post_detail":
            return CommunityAction(
                "back_to_tasks_from_post",
                POST_BACK,
                source_page=page.name,
                target_pages=("feed_home",),
                reason=f"{reason}；先退回信息流",
            )
        return CommunityAction(
            "back_to_tasks_dismiss_sheet",
            SHARE_CANCEL,
            source_page=page.name,
            target_pages=("post_detail", "feed_home"),
            reason=f"{reason}；先收掉分享面板",
        )

    def _on_feed(self, screen: np.ndarray, page) -> Optional[CommunityAction]:
        self.state = CommunityState.FEED
        if self.active_task is not None:
            return self._drive_task(screen, page)
        if self.stop_reason or self._finishing():
            # 两条路都走「关掉社区 → 转回横屏 → 再收工」：
            # ① 清单兑满（正常完成）；② 积分不够（资源耗尽，退出码 2）。
            # 后者要在横屏那一帧才抛（见 ``_on_landscape``），所以在竖屏页面上
            # 两条路的动作完全一样。
            again = "积分不够，不再兑换" if self.stop_reason else "任务与兑换都完成"
            again += self._stuck_note()
            self.state = CommunityState.CLOSING
            return CommunityAction(
                "close_community",
                FEED_CLOSE,
                source_page=page.name,
                target_pages=("web_activity_list",),
                reason=f"{again}，点信息流右上角的 X 退出社区",
            )
        state = feed_signin_state(screen)
        self.progress.signed_in = state == "done"
        if state == "unknown":
            self.last_reason = (
                "信息流上「每日签到」那块读不出颜色（出界，或画面被弹窗压暗）"
            )
            raise CommunityDataMissing(
                "信息流上「每日签到」图标那块读不出颜色，说不出今天签没签。"
                "**不猜**：猜「已签」会漏签，猜「未签」会白点一下。"
            )
        if state == "todo":
            if not self.signin_clicked:
                self.signin_clicked = True
                return CommunityAction(
                    "tap_signin",
                    FEED_SIGNIN_CLICK,
                    source_page=page.name,
                    target_pages=("signin_done", "feed_home"),
                    reason=(
                        "「每日签到」图标是彩色的（今天还没签），点它签到；"
                        "点完弹窗可能要等一分多钟才出（2026-10-07 实测最慢 74 秒），"
                        "这期间画面不变，不是点空了"
                    ),
                )
            self.last_reason = (
                "已点过「每日签到」，等签到弹窗出现（2026-10-07 实测最慢 74 秒）"
            )
            return None
        # 今天已经签过 ⇒ 去「我的任务」。⚠️ 底栏那个「我的」不是它（见 `_return_to_tasks`）。
        self.via_exchange = True
        return CommunityAction(
            "goto_tasks_via_exchange",
            FEED_ICON_EXCHANGE,
            source_page=page.name,
            target_pages=("exchange_center", "exchange_empty"),
            reason="今天已签到，走「兑换」图标 → 兑换中心 →「获取积分卡」进我的任务",
        )

    def _on_signin_done(self, screen: np.ndarray, page) -> CommunityAction:
        """「签到成功！」弹窗：点绿「关闭」收起。

        ⚠️ 这一步**必须有**：弹窗是**模态**的，不关掉的话后面点的每一处都被它吃掉。
        2026-10-07 实测：弹窗帧被判成 ``feed_home``（判据缺这一层）⇒ 路线照常去点底栏，
        两下点击全部无反应，而日志里看不出为什么。
        """
        self.state = CommunityState.SIGNIN_DONE
        return CommunityAction(
            "ack_signin_done",
            SIGNIN_POPUP_CLOSE,
            source_page=page.name,
            target_pages=("feed_home",),
            reason="签到成功弹窗，点「关闭」收起（坐标由颜色连通域量出，别照渲染图目测）",
        )

    def _on_post_detail(self, screen: np.ndarray, page) -> CommunityAction:
        self.state = CommunityState.POST_DETAIL
        if self.active_task is not None:
            return self._drive_task(screen, page)
        # 不在任务流程里却停在帖子详情 ⇒ 退回信息流，不在这里乱点。
        self.last_reason = "不在任何任务流程里却停在帖子详情，退回信息流"
        return CommunityAction(
            "post_detail_back",
            POST_BACK,
            source_page=page.name,
            target_pages=("feed_home",),
            reason=self.last_reason,
        )

    def _on_share_sheet(self, screen: np.ndarray, page) -> CommunityAction:
        self.state = CommunityState.SHARE_SHEET
        if self.active_task is not None:
            return self._drive_task(screen, page)
        # 分享任务由 `TASK_SCRIPT` 驱动（帖子详情 → 分享 → 复制链接）。
        # 走到这里说明是**流程外**跑到了分享面板 ⇒ 收掉它。
        self.last_reason = "不在任务流程里却停在分享面板，点「取消」收掉"
        return CommunityAction(
            "cancel_share_sheet",
            SHARE_CANCEL,
            source_page=page.name,
            target_pages=("post_detail", "feed_home"),
            reason=self.last_reason,
        )

    def _redeem_finished(self) -> bool:
        """清单是否已经全部兑满（用最近一次读到的限购次数判断）。"""
        if not self.progress.redeemed:
            return False
        for target in self.plan:
            current = self.progress.redeemed.get(target.card)
            if current is None or current < target.daily_limit:
                return False
        return True

    def _tasks_settled(self) -> bool:
        """三条任务是不是都「有结论」了：**做成了**，或者判定**今天做不成**。

        ⚠️ 为什么不沿用 ``progress.tasks_all_done()``（三条全 done）：那会让路线
        在「有一条今天就是做不成」时**永远出不去** —— 收尾条件永远不满足，于是
        在信息流与我的任务之间来回转到超时。判定做不成的（``stuck_tasks``）也算「有结论」，
        但**会写进收尾日志**（`_on_feed` 把它们的名字串进 reason），不做无声跳过。
        """
        if not self.progress.tasks:
            return False
        for key, state in self.progress.tasks.items():
            if state == "done" or key in self.stuck_tasks:
                continue
            return False
        return True

    def _finishing(self) -> bool:
        """这条路线的事是不是都做完了（三条任务 + 清单兑换）。"""
        return self._tasks_settled() and self._redeem_finished()

    def _stuck_note(self) -> str:
        """今天做不成的任务，拼成一句给人看的话（空串表示没有）。"""
        if not self.stuck_tasks:
            return ""
        labels = "、".join(
            TASK_LABELS.get(key, key) for key in sorted(self.stuck_tasks)
        )
        return f"（今天做不成的任务：{labels}）"

    def _finish(self, reason: str) -> None:
        """收官：轮次 +1，主循环据此在 ``max_cycles`` 满足时收工并回大厅。

        ⚠️ 只能在**没有任何动作要发**的那一帧调它。主循环的次序是
        「先发动作、再看轮次有没有推进」——两者同帧发生时动作会被跳过，
        表现为「明明该点的那一下没点，整条路线却报完成」。
        """
        self.state = CommunityState.DONE
        self.completed_cycles += 1
        self.last_reason = reason


class UnrecognizedCommunityScreen(RuntimeError):
    """社区竖屏画面认不出。与项目里 ``UnrecognizedScreen`` 同义，单独一个名字便于日志区分。"""


class RedeemBudgetExhausted(ResourceExhausted):
    """积分不够继续兑换 —— **正常业务退出**，不是故障（对应退出码 2）。

    ⚠️ 必须继承 ``ResourceExhausted`` 而不是 ``RuntimeError``：主循环靠
    「是不是 ``ResourceExhausted``」决定退出码。挂在 ``RuntimeError`` 下会被
    当成「画面认不出」去等超时，最后报**退出码 1**（故障）—— 明明只是没分了。
    """

    stop_label = "积分不足"


# ── 实跑许可 ──────────────────────────────────────────────────────────────────

#: 竖屏段要用的真机数据是否已经采齐。没齐就**不许实跑**（干跑照常）。
#
# ⚠️ 它由 ``modes._preflight_community`` 在**调用时**读（不是 import 期绑一份名字）——
# 项目里同形的刷书签闸门踩过这个坑：import 期绑名字之后测试 patch 不动，
# 闸门会悄悄退化成空转。
#: 2026-10-07 真机采齐：签到两态（彩色/灰）、签到入口与弹窗关闭、三条任务的
#: 执行脚本与脚本要用的坐标、「去完成」落点、帖子详情与分享面板的处理。
#: 因此翻成 ``True`` —— 实跑闸门放行，改由状态机自己的判据把关。
LIVE_RUN_READY = True

#: 还**只**有单次样本、没被第二天真机复验过的地方。闸门放行之后它只当注释用；
#: 一旦哪天要重新关上闸门（改判据 / 客户端改版），把这句话抄进 ``MISSING_LIVE_DATA``
#: 就能立刻恢复成「干跑照常、实跑拦住」。
#:
#: ⚠️ 2026-10-07 更新：横屏段那两个判据**已跨天复验**（活动页选中态换成白字模板，
#: 跨两天 0.8924~1.0000；未选中态跨两天 0.9145/0.991）。剩下的缺口是：
#: ① 三条每日任务的执行坐标只有 10-07 单日样本；
#: ② 行动力**第二次**兑换的链路没有真机帧（`REDEMPTION_PLAN` 定的是每日限购 2）。
MISSING_LIVE_DATA = (
    "三条每日任务的执行脚本（信息流第一张帖子卡 / 卡片 👍）只在 2026-10-07 单日样本上"
    "验证过一遍；行动力每日限购 2、但只有第一次兑换的真机帧，第二次的"
    "「兑换成功 → 回商品详情 → 再兑一次」链路没有样本"
)


def build_screen_reader(template_root: Path):
    """一次把判页模板与数字字模都加载好（两个都 fail-closed）。"""
    from auto_game_unified.games.epic7.community_numbers import load_digit_glyphs

    return pages.build_page_templates(template_root), load_digit_glyphs(template_root)


# ── 双通道：把竖屏链路接进横屏 Runtime ───────────────────────────────────────


class ChannelSwitch:
    """这条路线当前该走横屏通道还是竖屏通道。

    ## 方向由「路线自己的意图」决定，不是每帧去问窗口

    问一次方向要跑 ``ldconsole list2``（约 100ms 的子进程），每帧都问等于给主循环
    平白加一份开销。所以这里只在**换向的那几秒**里轮询：状态机点了「游戏社区」就
    ``expect_portrait()``，点了「退出社区」就 ``expect_landscape()``；轮询看到窗口
    真的转过去了就锁定，之后一帧都不再问。

    ## 换向途中「还没转过去」时，为什么不能回横屏

    转屏是**带动画的**：窗口渲染尺寸会在中途变化，横屏那套 ``capture()`` 会直接抛
    「LDPlayer render size changed」。所以「已点入口、还没转过去」这段时间照样交给
    竖屏通道 —— 它自己会**等**（``wait_for_portrait``，默认最长 20 秒），等到真的
    竖过来才取图。等不到就说明那一下没点中，由 ``attach_dual_channel`` 退回横屏
    让状态机重点一次。
    """

    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    PENDING_PORTRAIT = "pending_portrait"
    PENDING_LANDSCAPE = "pending_landscape"

    def __init__(
        self,
        portrait: PortraitChannel,
        *,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.portrait = portrait
        self.state = self.LANDSCAPE
        # 问过多少次方向。测试用它钉「锁定之后不再问」。
        self.probes = 0
        # 「开关与真实方向不一致」这类纠正必须**出声**：它是记录与现实脱节的唯一
        # 证据，不出声就又变成一次「静默走错通道」。
        self._log = log if log is not None else (lambda _message: None)

    def expect(self, target: str) -> None:
        if target == "portrait":
            self.state = self.PENDING_PORTRAIT
        else:
            self.state = self.PENDING_LANDSCAPE

    def use_portrait(self) -> bool:
        """本帧该走竖屏通道吗（换向中会问一次窗口方向）。

        ## ⚠️⚠️ 已锁定的状态也必须**核对真实方向**（2026-10-07 修，用户点 2 的真根）

        这个开关的设计是「只在换向的那几秒里问窗口方向，之后锁定、一帧都不再问」
        （省掉每帧一次 ``GetClientRect``）。**但它只被两个时机更新**：
        点完「游戏社区」拨成 ``PENDING_PORTRAIT``、点完「退出社区」拨成
        ``PENDING_LANDSCAPE``。于是会出现一个要命的错位：

        **开关说「横屏」，而窗口真的已经是竖屏** —— 实测就是这么撞上的：
        ``switch.state=landscape`` 而 ``is_portrait()=True``，
        于是 ``capture`` 走横屏那一套，横屏模板撞上竖屏画面 ⇒
        ``RuntimeError: LDPlayer render size changed: 1023x1820; expected 1920x1080``
        ⇒ 异常冒到主循环 ⇒ **失败收尾把刚打开的社区关掉**
        （用户原话：「进入社区之后又会退回来」）。

        错位是怎么来的：收尾那一段会把开关拨成「等横屏」，可**人还在竖屏里**；
        下一轮取图就按「横屏」去拿，直接崩。**记录与现实不一致，而代码从不核对。**

        ⇒ 所以 ``LANDSCAPE`` 这一支也问一次窗口方向，**不一致就纠正并记一笔**。
        代价是每帧一次 ``GetClientRect``（微秒级，比一次 ``screencap`` 便宜几个数量级），
        换来的是「开关永远不会把人带进错误的通道」。
        """
        if self.state == self.PORTRAIT:
            return True
        if self.state == self.LANDSCAPE:
            # ⚠️ 已锁定横屏，但**先核对真实方向**（见上面 docstring 的「用户点 2」）。
            self.probes += 1
            if not self.portrait.is_portrait():
                return False
            self.state = self.PENDING_PORTRAIT
            self._log(
                "竖屏通道 方向=开关说是横屏、实际已是竖屏 "
                "处理=纠正为竖屏 原因=窗口真实方向与通道记录不一致；"
                "继续按横屏取图会撞「render size changed」并触发失败收尾关掉社区"
            )
            return True
        self.probes += 1
        portrait_now = self.portrait.is_portrait()
        if self.state == self.PENDING_PORTRAIT:
            if portrait_now:
                self.state = self.PORTRAIT
            return True
        # PENDING_LANDSCAPE
        if not portrait_now:
            self.state = self.LANDSCAPE
            return False
        return True

    def demote_to_landscape(self) -> None:
        """等转屏失败 ⇒ 回到横屏判断（让状态机重新点一次入口）。"""
        self.state = self.LANDSCAPE


def attach_dual_channel(runtime: Runtime, portrait: PortraitChannel) -> ChannelSwitch:
    """把竖屏通道接进 ``Runtime`` —— **保留 Runtime 原本的每一层语义**。

    ## 为什么换掉它的四个「原始通道」，而不是在外面垫一层壳

    ``Runtime.capture / click / swipe / back`` 各自还做三件事：查停止请求
    （P 键 / 界面上的 stop 文件）、写运行日志、取图那条再叠一层全局弹窗判据
    （``set_capture_guard``）。在外面垫壳就必须把这些**再实现一遍** —— 那就是
    「同一个行为两份实现」，以后 ``Runtime`` 改了这一份不会跟着改（项目里因为
    「同一事实抄两处」漂移过多次）。所以这里只替换最底下的四个通道，上面每一层照旧。

    ## 代价与防线

    它要写 ``Runtime`` 的四个私有属性，所以：

    ① 先 ``hasattr`` 探一遍 —— 属性被改名会在**开跑前**当场报错，不会静默失效；
    ② 只替换这四个，不新增也不删除任何属性；
    ③ 干跑**完全不接**（`capture` 直接走原实现）：干跑不该去碰 adb、也不该让模拟器转屏；
    ④ 每个替换点先把原实现存下来，横屏段原样转发。

    ⚠️ 只适用于**雷电模拟器后端**（``PortraitChannel`` 走 adb）。PC 后端由
    ``CommunityRunner`` 在装配前拦下。
    """
    names = ("_capture", "_click", "_swipe", "_back")
    missing = [name for name in names if not hasattr(runtime, name)]
    if missing:
        raise RuntimeError(
            f"Runtime 少了这些通道属性：{missing}。"
            "社区路线的竖屏接入依赖它们，Runtime 改名了就要跟着改"
            "（见 community.attach_dual_channel）。"
        )
    landscape_capture: Callable[[], np.ndarray] = runtime._capture
    landscape_click: Callable[[tuple[int, int]], None] = runtime._click
    landscape_swipe: Callable[[tuple[int, int], tuple[int, int], int], None] = (
        runtime._swipe
    )
    landscape_back: Callable[[], None] = runtime._back
    switch = ChannelSwitch(portrait, log=runtime.log)

    def _fallback_to_landscape(reason: str) -> np.ndarray:
        """竖屏取图失败后的退路 —— 但**先确认窗口真的已经是横屏**。

        ## ⚠️⚠️ 为什么必须先问方向（2026-10-07 修，用户点 2 的另一半）

        旧代码在 ``portrait.capture()`` 抛错后**无条件**退回横屏，理由写在注释里是
        「此刻窗口多半仍是横屏，横屏取图安全」。实跑打脸了这个假设：

        -12:45:02 点「游戏社区」→ 12:45:05 就「收尾=人还在社区竖屏页面里」。

        也就是说那一刻窗口**已经是竖屏**（``is_portrait()`` 为真，所以收尾才说要
        退出社区）。此时 ``landscape_capture()`` 会撞上
        ``RuntimeError: render size changed``（横屏模板基准1920x1080 vs 竖屏画面），
        异常一路冒到主循环 → **失败收尾把刚打开的社区又关掉** ——
        正是用户说的「进入社区之后又会退回来」。

        代价还不止崩这一下：``demote_to_landscape()`` 把通道改回横屏，
        而窗口真的是竖屏 ⇒ 后面每一帧都在拿竖屏画面撞横屏模板。

        ⇒ 所以退路改成**先问方向**（``is_portrait()`` 只是一次 ``GetClientRect``，
        微秒级，不值得为省它冒崩整条路线的风险）：

        - **窗口已是竖屏** ⇒ 说明社区**真的打开了**，只是画面还没稳定。
          此时**不能**退回横屏（会把刚打开的社区关掉），应当**留在竖屏**继续等 ——
          也就是把这一帧的失败交回上层，让它按「转场中、只等不判失败」处理。
        - **窗口确实还是横屏** ⇒ 老逻辑成立，退回横屏让状态机再点一次入口。
        """
        if portrait.is_portrait():
            runtime.log(
                f"竖屏通道 方向=已是竖屏 处理=不退回横屏、留在竖屏继续等 "
                f"原因={reason} 后果=退回横屏会拿竖屏画面撞横屏模板、"
                f"并触发失败收尾把社区关掉"
            )
            # 仍按竖屏再取一帧：多数情况下这一帧画幅已经跟上了（``core/portrait.py``
            # 内部已有有界等待，这里是最后一道）。
            #
            # ⚠️ 2026-10-07 补：这一下**救得回来一部分**，但不能指望它 ——
            # 它再失败时抛出的异常在这一层**没人兜**（发生在 except 块里，
            # 不会被同一个 try 接住），会一路冒到主循环取图那一行（在 try 之外）
            # ⇒ 整条路线秒失败、把刚打开的社区关掉（一天 8 次，连诊断帧都没有）。
            # 所以兜底放在 ``CommunityRunner._capture_frame``：那里按
            # 「转场中、只等」有界重试，等满才允许失败，且期间会说清在等什么。
            return portrait.capture()
        switch.demote_to_landscape()
        runtime.log(
            f"竖屏通道 方向=社区未真正打开 处理=退回横屏重试入口点击 原因={reason}"
        )
        return landscape_capture()

    def capture() -> np.ndarray:
        if runtime.dry_run or not switch.use_portrait():
            return landscape_capture()
        try:
            return portrait.capture()
        except OrientationError as error:
            # 等满 20 秒还没转过去（``wait_for_portrait`` 超时）**或**转过去了但
            # 截图尺寸还不是 1080x1920（转屏动画中间帧）⇒ 这两种都可能是
            # 「社区还没真正打开」。到底是哪种，由 ``_fallback_to_landscape``
            # **问窗口方向**来分辨，不再假设。
            #
            # ⚠️ 2026-10-07 修：原先 ``portrait.capture()`` 在「尺寸不对」时抛的是
            # **裸 ``RuntimeError``**，漏过这个 ``except`` 一路冒到主循环 ——
            # 实跑表现为「点完 2 秒就崩」，而方向其实已经变了。现在
            # ``core/portrait.py`` 把那一支也改成抛 ``OrientationError``。
            return _fallback_to_landscape(str(error))
        except RuntimeError as error:
            # ⚠️ **兜底的兜底**（2026-10-07 加，见 ``tests/test_community.py``
            # ``test_wrong_canvas_size_also_falls_back_instead_of_crashing``）。
            #
            # 为什么不靠上面那一行就够：``portrait`` 是**注进来的**（测试用替身、
            # 将来还可能换实现），它抛什么类型不归这一层管。而这里的失败代价
            # **不对称** —— 兜住的后果是「退回横屏重试一次」，漏掉的后果是
            # 「整条路线崩掉、模拟器被留在竖屏」（10:51 实跑的原样）。
            #
            # ⚠️ 只兜「取图」这一层，且只在**已经准备退回横屏**的方向状态下 ——
            # 横屏段（``use_portrait()`` 为假）根本走不到这里，所以不会把
            # 横屏自己的真实故障一起吞掉。
            return _fallback_to_landscape(f"{type(error).__name__}: {error}")

    def click(point: tuple[int, int]) -> None:
        if runtime.dry_run:
            return
        if switch.use_portrait():
            portrait.click(point)
            return
        landscape_click(point)

    def swipe(start: tuple[int, int], end: tuple[int, int], duration_ms: int) -> None:
        if runtime.dry_run:
            return
        if switch.use_portrait():
            portrait.swipe(start, end, duration_ms)
            return
        landscape_swipe(start, end, duration_ms)

    def back() -> None:
        if runtime.dry_run:
            return
        if switch.use_portrait():
            portrait.back()
            return
        landscape_back()

    runtime._capture = capture
    runtime._click = click
    runtime._swipe = swipe
    runtime._back = back
    return switch


# ── Runner ────────────────────────────────────────────────────────────────────


class CommunityRunner(ModeRunnerBase):
    """社区签到路线（横屏导航 + 竖屏社区）的 Runner。

    ⚠️ 打开 ``_REQUIRE_TRANSITION_CONTRACT``：每个动作都要在发出前通过
    「source_page + 出口验收」的机器校验（含空跑）。

    ## 与基类的两条约定

    - **不覆写 ``_stable_next_action`` 的主流程**，只在 ``super()`` 之后补一条
      **等待心跳**（见类里的 ``_stable_next_action``）—— 覆写必须把基类的实现调回去，
      否则「结论门槛」会被绕过（``modes._base_conclusion_gate_protected`` 会拦下来）。
    - **覆写 ``run()`` 只为了装配两条通道**，主循环照旧委托给基类，所以
      「收尾回首页」与结论门槛都还在。

    ## ⚠️ 这条路线跑得比较久（正常，不是卡住）

    两段正常的长等待：**等签到弹窗**（实测最慢 74 秒）与**等兑换结果**（实测 3~40 秒）。
    两段都「不出手、不打分、不报警」，所以配了一条 10 秒心跳，日志不会空着。
    """

    _MODE_LABEL = "社区签到"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        CommunityState.WEB_ENTRY: 90,
        # 转屏实测 3 秒内完成；给 60 秒是因为竖屏通道自己会先等满 20 秒
        # （等不到就退回横屏重试一次），这一档要罩得住那几轮。
        CommunityState.ENTERING: 120,
        # ⚠️ 这一档要罩住「点完签到、等签到弹窗出来」那段 —— 2026-10-07 实测最慢
        # 74 秒才出（点后 3 秒 / 9 秒看都还是原样，画面一直不动）。
        # 给 60 秒的话，一次正常的慢签到就会被判成「画面无动作超时」。
        CommunityState.FEED: 150,
        CommunityState.POST_DETAIL: 45,
        CommunityState.SHARE_SHEET: 45,
        CommunityState.TASKS: 60,
        CommunityState.EXCHANGE: 60,
        CommunityState.ITEM_DETAIL: 45,
        # ⚠️ 这一档**必须**比「等兑换结果」的实测上限宽：按钮点完要 3~40 秒才出结果，
        # 这期间按钮是禁用态（颜色定位找不到）⇒ ``next_action`` 一直返回 None。
        # 给 45 秒的话，一次 40 秒的正常等待就会被判成「画面无动作超时」。
        CommunityState.ORDER_CONFIRM: 150,
        CommunityState.REDEEM_DONE: 45,
        CommunityState.SIGNIN_DONE: 45,
        CommunityState.CLOSING: 90,
        CommunityState.BLOCKED: 45,
        CommunityState.DONE: 45,
    }
    # 这条路线不打架，没有「已承诺战斗」环节。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 默认 45 秒是给「换页」定的。这几个动作点完**立刻**能看出生效没有
    # （弹窗收起来 / 面板关掉 / 退回上一页），45 秒纯属白等。
    _QUICK_ACTIONS = frozenset(
        {
            "ack_redeem_done",
            "ack_signin_done",
            "cancel_share_sheet",
            "post_detail_back",
            "back_to_tasks_from_post",
            "back_to_tasks_dismiss_sheet",
            "leave_empty_exchange",
            "leave_exchange",
            "leave_tasks",
            "close_community",
            "logout_community",
        }
    )
    _QUICK_RETRY_SECONDS = 8.0
    # ⚠️ 入口那一下的重试间隔**必须比竖屏通道的等待更宽**（默认等满 20 秒才认输），
    # 否则会在转屏动画还没走完时又点一次 —— 那时的横屏坐标已经不可信了。
    _ENTRY_RETRY_SECONDS = 25.0
    _WAIT_HEARTBEAT_SECONDS = 10.0
    #: 换向窗口里「取不到图」的最长等待。给 30 秒是因为竖屏通道自己已经先等了
    #: 20 秒方向，再留一段给安卓侧 rotation 生效；等满还不行才准判失败。
    _CAPTURE_SETTLE_SECONDS = 30.0
    #: 这段等待里每隔多久说一句在等什么（否则日志又是一片空白）。
    _CAPTURE_SETTLE_LOG_SECONDS = 5.0

    def __init__(
        self,
        machine: CommunityStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        portrait: Optional[PortraitChannel] = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )
        self.machine = machine
        # 竖屏通道可以在测试里注入（免得真去连模拟器）。
        self._portrait = portrait
        self._switch: Optional[ChannelSwitch] = None
        self._wait_frame_saved = False
        self._last_wait_log_at: Optional[float] = None

    # ---- 装配 ----

    def run(self, max_cycles: Optional[int] = None) -> int:
        self._attach_channels()
        stopped = False
        try:
            # 主循环委托给基类：收尾（``_close_out``）与结论门槛都在那边。
            return super().run(max_cycles=max_cycles)
        except ManualStop:
            # 用户按 P 喊停 ⇒ 一个字都不动游戏（全线统一口径）。所以下面那段
            # 兜底收尾**不能**在这里跑。
            stopped = True
            raise
        finally:
            # 失败路径的兜底：人可能还停在社区的竖屏页面里，而 ``main`` 的
            # 「异常也回家」要拿横屏通道取图，竖屏下会直接抛「render size changed」。
            # 正常路径用不到它（状态机在横屏那一帧才收工），且它是幂等的。
            if not stopped:
                self._leave_portrait_if_needed()

    def _attach_channels(self) -> None:
        if self.runtime.dry_run:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 竖屏通道=干跑不接 "
                "原因=干跑不碰 adb，也不该让模拟器转屏"
            )
            return
        window = self._landscape_window()
        if window is not None and not isinstance(window, Epic7Window):
            # 不拦的后果是**静默点错客户端**：`PortraitChannel` 自己会去找雷电窗口，
            # 要是机器上恰好在跑雷电，它就会去操作那一个 —— 画面看着没问题，点的是别人。
            raise RuntimeError(
                "社区签到路线的竖屏段只有雷电模拟器有（走 adb）；"
                f"当前横屏通道是 {type(window).__name__}，请改用默认的模拟器后端"
            )
        portrait = self._portrait or PortraitChannel(window=window)
        self._portrait = portrait
        # ⚠️ 竖屏通道自己的诊断日志（等转屏、画幅没跟上）必须接到运行日志上。
        # 不接的后果：入口段失败时日志**一片空白**——它到底在等什么、等了多久，
        # 一行都看不到，2026-10-07 一天 8 次「点完入口 2 秒就收尾」就是这么查不出原因的。
        portrait.set_event_sink(self.runtime.log)
        self._switch = attach_dual_channel(self.runtime, portrait)
        self.runtime.log(
            f"模式={self._MODE_LABEL} 竖屏通道=已接入 "
            f"画布={PORTRAIT_CANVAS[0]}x{PORTRAIT_CANVAS[1]} "
            "分工=横屏走窗口链路，点进社区后按方向切到 adb 链路"
        )

    def _landscape_window(self) -> Any:
        """横屏那条通道用的窗口对象（从 runtime 的取图实现上取；取不到返回 None）。

        ⚠️ 只读一次、取不到就放过：不把「读不到」升级成「跑不了」——测试与替身
        本来就没有这个属性（例如传个 ``lambda`` 进去）。真跑时它一定是
        ``Epic7Window.capture`` 这个**绑定方法**，于是 ``__self__`` 就是那个窗口。
        """
        capture = getattr(self.runtime, "_capture", None)
        return getattr(capture, "__self__", None)

    # ---- 基类钩子 ----

    def _state_label(self, state: CommunityState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name == "enter_community":
            return self._ENTRY_RETRY_SECONDS
        # 任务脚本那几步（点开帖子 / 返回 / 点赞 / 复制链接 / 再滑一次）点完**立刻**
        # 能看出生效没有，按 45 秒等就是白等 —— 一天三条任务各来几遍，时间全耗在这。
        if action_name in self._QUICK_ACTIONS or action_name.startswith("task_"):
            return self._QUICK_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _perform_action(self, action: Any) -> None:
        """滑动的那几步走 ``runtime.swipe``，其余照旧点击。

        ⚠️ 为什么必须覆写：主循环（``runner_base``）只会 ``runtime.click``，而社区
        那两条脚本里的「往下滑一次」是**状态机产出的动作**、没法像商店刷新那样
        自己绕开主循环去调 ``swipe``。不换发的话，滑动会变成「在起点点一下」——
        点在信息流中部会**点开一张帖子**，于是下一步要求的页对不上、本遍作废，
        一天三次机会就这么白烧掉（2026-10-07 实测）。
        """
        end = getattr(action, "swipe_end", ())
        if not end:
            super()._perform_action(action)
            return
        self.runtime.swipe(
            action.point,
            end,
            FEED_TASK_SCROLL_MS,
            action.name,
        )

    def _capture_frame(self) -> np.ndarray:
        """取一帧；**换向那一两秒里取不到图属于转场中，不是失败**。

        ## 为什么这一条社区路线必须自己兜

        主循环取图那一行在 ``try`` 之外 ⇒ 取图一旦抛异常，整条路线**立刻**失败收尾，
        而那时社区**其实已经打开了** ⇒ 收尾把刚打开的社区又关掉，且一张诊断帧都留不下。
        2026-10-07 一天 8 次都是这个形状（点完入口 2~3 秒就「收尾=人还在社区竖屏页面里」）。

        转屏是**分两步**的：先转窗口、再由安卓 ``rotation`` 生效。中间那一瞬
        ``screencap`` 拿到的还是旧尺寸 ⇒ 竖屏通道报错。按转场契约
        「来源已离开、目标未稳定 ⇒ **只等待**，禁止重复旧动作」—— 这里就该等。

        ⚠️ **有界**：等满 ``_CAPTURE_SETTLE_SECONDS`` 仍不成，说明社区确实没打开，
        那时才允许失败（日志会把「在等什么、等了多久」写清楚）。
        ⚠️ **只兜方向类异常**：``ManualStop`` / 截图命令真失败都不是 OrientationError，
        不会被这里吞掉。
        """
        if self.runtime.dry_run or self._switch is None:
            return self.runtime.capture()
        try:
            return self.runtime.capture()
        except OrientationError as error:
            reason = str(error)
        started = self.now()
        logged_at = 0.0
        while True:
            elapsed = self.now() - started
            if elapsed >= self._CAPTURE_SETTLE_SECONDS:
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 取图=转场中等满 "
                    f"已等={elapsed:.0f}秒 原因={reason} "
                    "处理=按失败收尾（社区多半没真正打开）"
                )
                raise OrientationError(reason)
            if elapsed - logged_at >= self._CAPTURE_SETTLE_LOG_SECONDS:
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 取图=转场中，等画面就绪 "
                    f"已等={elapsed:.0f}秒/{self._CAPTURE_SETTLE_SECONDS:.0f}秒 "
                    f"原因={reason}"
                )
                logged_at = elapsed
            self.sleep(self.poll_seconds)
            try:
                return self.runtime.capture()
            except OrientationError as error:
                reason = str(error)

    def _after_action_click(self, action: Any) -> None:
        """点完「进/出社区」之后把通道方向预期拨过去。

        为什么必须在这里拨：这两下点击是**唯一**会改变屏幕方向的动作，而方向一变，
        取图/点击的坐标系就整个换了（横屏 1982x1132 vs 竖屏 1080x1920）。
        拨晚了会拿错坐标系点一下，拨早了会在转屏动画中途取图。
        """
        if self._switch is None:
            return
        name = getattr(action, "name", "")
        if name == "enter_community":
            self._switch.expect("portrait")
        elif name in ("close_community", "logout_community"):
            self._switch.expect("landscape")

    def _stable_next_action(self, screen: np.ndarray, stable: Any):
        """基类流程 + 一条**等待心跳**。

        ⚠️ 必须 ``super()`` 进去 —— 「结论门槛」接在基类里，绕过去等于
        「一帧就能宣布收工 / 一帧认不出就去点屏幕中间」。

        ⚠️ 为什么要有心跳：这条路线有两处**正常的长等待**（等转屏、等兑换结果），
        不出手、不打分、不报警，日志会一直空到超时 —— 2026-10-04 那次就是这么
        事后翻现场帧才知道卡在哪的。这里每 10 秒吐一行，带上「当前页面 + 为什么没出手」，
        判据沉默 10 秒内就能看出来。
        """
        result = super()._stable_next_action(screen, stable)
        if result is NOT_STABLE or result is not None:
            self._last_wait_log_at = None
            return result
        now = self.now()
        if not self._wait_frame_saved:
            self._save_wait_frame(screen)
        if self._last_wait_log_at is None or (
            now - self._last_wait_log_at >= self._WAIT_HEARTBEAT_SECONDS
        ):
            self.runtime.log(
                f"模式={self._MODE_LABEL} 等待=无动作 "
                f"页面={self._state_label(self.machine.state)} "
                f"依据={getattr(self.machine, 'last_reason', '') or '未说明'} "
                f"通道={'竖屏' if self._switch and self._switch.use_portrait() else '横屏'}"
            )
            self._last_wait_log_at = now
        return result

    def _save_wait_frame(self, screen: np.ndarray) -> None:
        """判据沉默时留一张现场帧（只留第一张）。

        为什么必须留：沉默的形态是「什么都不做」，一张图都不会走到超时分支 ——
        事后再想查就只剩一张空白日志。⚠️ 诊断**绝不许**打断主循环，所以整个包在
        ``try/except`` 里：存不下就记一笔，照常跑。
        """
        self._wait_frame_saved = True
        if self.runtime.diagnostic_dir is None:
            return
        try:
            self.runtime.save_diagnostic("community_wait_silent", screen)
        except Exception as error:  # noqa: BLE001 - 诊断失败绝不打断主循环
            self.runtime.log(
                f"模式={self._MODE_LABEL} 等待现场帧保存失败（已忽略） 原因={error}"
            )

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} "
            f"结论={getattr(self.machine, 'last_reason', '') or '已走完出口'}"
        )

    def _close_out(self) -> None:
        """收尾：先把社区页关掉、等模拟器转回横屏，再交给基类做「回首页」。

        ⚠️ 为什么需要：**异常路径**（缺数据 / 认不出 / 判据 blocked）也会走到这里，
        而那时人可能还停在社区的竖屏页面里。基类的收尾要拿横屏通道去取图
        （``return_home``），在竖屏下会直接抛「render size changed」——
        于是「异常也回家」这条规矩在这条路线上**实际做不到**，模拟器还会被留在竖屏。

        正常路径用不到它（状态机会在横屏那一帧才收工）。契约与基类一致：
        **绝不抛异常** —— 关不掉就记一笔，让基类那步照常失败并留下原因。
        """
        self._leave_portrait_if_needed()
        super()._close_out()

    def _leave_portrait_if_needed(self) -> None:
        """人还停在社区竖屏页面里 ⇒ 先退出社区、**等模拟器真的转回横屏**。

        ⚠️⚠️ 2026-10-07 修的正是「等」这个字。旧版点完 X 与两下返回键就
        ``return``，方向**转没转完不管** ⇒ ``super()._close_out()`` 紧接着
        调 ``return_home`` 取图，而那一刻窗口往往**还在竖屏** ⇒
        横屏模板被喂了竖屏画面 ⇒ ``RuntimeError: 画面宽高比与模板基准不一致``
        ⇒「异常也回家」这条项目统一的规矩在这条路线上**实际做不到**
        （10:51 实跑日志：10:51:23 收尾声称「已尝试退出社区」，10:51:36
        回家就以那条错失败）。

        ⇒ 现在点完之后**有界等待**转回横屏（``wait_for_landscape``），
        等到了再让基类接手；等不到就把「当前仍是竖屏」这件事如实记进日志，
        让基类那步照常失败并留下原因（**绝不抛异常** —— 收尾失败不改退出码）。
        """
        switch = self._switch
        if switch is None or self.runtime.dry_run:
            return
        try:
            if not switch.portrait.is_portrait():
                return
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=人还在社区竖屏页面里 "
                "动作=先退出社区，等转回横屏再回首页"
            )
            # 竖屏段对返回键的响应不一致（任务页按了没反应），所以先点信息流
            # 右上角的 X，再补两下返回键；每一步都看一眼方向，转过去了就收手。
            portrait = switch.portrait
            portrait.click(FEED_CLOSE)
            for _ in range(2):
                if not portrait.is_portrait():
                    break
                portrait.back()
            # ⚠️ 关键的一步：点完**必须等方向真的回来**再交棒。
            # 少了它，基类会在转屏动画中途取图，拿到竖屏帧喂给横屏模板。
            portrait.wait_for_landscape(timeout=_EXIT_ROTATION_WAIT_SECONDS)
        except Exception as error:  # noqa: BLE001 - 收尾绝不外抛
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=退出社区失败（已忽略） 原因={error}"
            )
            return
        # ⚠️ 等完之后**再确认一次方向**，而不是假定「没抛异常就等于转回来了」。
        # 两种失败长得不一样，但对基类的后果是同一件（回家那步会失败）：
        #   - ``wait_for_landscape`` 抛超时 ⇒ 走上面那个 except；
        #   - 它没抛但方向仍在竖屏 ⇒ 落到这里，**必须说清楚**。
        # 旧代码在这里无条件打「已尝试退出社区」，日志上看不出「其实没转回来」，
        # 10:51 那次就是这样：日志说已退出，13 秒后回家失败，看不出因果。
        still_portrait = switch.portrait.is_portrait()
        if still_portrait:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=等回横屏超时，当前仍在竖屏 "
                f"已等={_EXIT_ROTATION_WAIT_SECONDS:.0f}秒 "
                "影响=随后的回首页大概率失败（横屏通道取不到竖屏画面）"
                "处理=已忽略，不改本次运行结论"
            )
            return
        self.runtime.log(
            f"模式={self._MODE_LABEL} 收尾=已退出社区且方向已转回横屏 "
            f"已等回横屏≤{_EXIT_ROTATION_WAIT_SECONDS:.0f}秒"
        )


def build_community_machine(
    template_root: Path, state: str
) -> CommunityStateMachine:
    """``modes.MODE_SPECS`` 用的工厂：把判页模板与数字字模都加载好（fail-closed）。"""
    templates, glyphs = build_screen_reader(template_root / "community")
    return CommunityStateMachine(templates, glyphs, state=CommunityState(state))
