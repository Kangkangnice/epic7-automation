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

三条每日任务各自是一**轮**：点「去完成」→ 信息流 → **一轮之内连做 N 次**
（浏览 3 篇 / 点赞 3 个 / 分享 1 次，见 ``TASK_ROUND_TIMES``）→ 经兑换中心回
「我的任务」→ **对账**（那一行的按钮有没有变成「已完成」；⚠️ 读的是按钮长相，
不是 ``x/3`` 那个数字）。涨了算数、没涨再来一轮、连 ``TASK_ATTEMPT_LIMIT`` **轮**
都不涨就记一笔「今天做不成」并跳过它继续跑别的 —— **绝不死循环，也绝不无声跳过**
（名字会写进收尾日志）。

⚠️ 粒度必须是「一轮」：每次点「去完成」都重新落在信息流**顶部**（四次实测同一帧），
做一次就回来一趟的话，第二遍又滑回**同一篇** —— 三遍白做、计数永远不涨。

## ⚠️ 还没被第二天复验过的地方（写在这里，别装作不存在）

- **``FEED_FIRST_POST`` 只有单日样本**（信息流顶部第一张帖子卡）：卡片高度由正文长短
  决定 ⇒ **换一天可能对不上**。兜底是「以页面计数为准 + 有上限的重试」，
  所以对不上只会让那条任务被记成「今天做不成」，**不会点坏东西**。
- ✅ **卡片 👍 是开关**，而且**它根本不在一个固定坐标上**（2026-10-07 晚复量）：
  老代码钉的 ``(911, 735)`` 配的读色框，放大看是 tab 栏「骑士团」三个字
  ⇒ 那道「点之前先读颜色」的预检**恒返回「没点过」**，等于不存在；
  而同帧两张卡的 👍 实测能差 558px。现在改成 ``pages.locate_card_like()``
  **现找那颗空心 👍**（模板 ``card_like_off``，已点赞的实心青绿在它下面只到 0.43），
  找不到就下滑一屏再找（``LIKE_RESWIPE_LIMIT`` 封顶）。
  ⇒ **命中即「还没点过」**，不需要第二道读色闸门。
- **签到的弹窗延迟没有复查**：2026-10-07 实测点后 3 秒 / 9 秒看都没变化、
  74 秒后再看已经在了。到底是服务端慢、还是第一次那下其实没生效，
  **没有定论**。所以 ``_TIMEOUT_SECONDS[FEED]`` 给到 150 秒罩住它。
- **订单确认页按钮「禁用」与「不在」分不开**：两者在颜色定位里都是「找不到」，
  目前一律按「等结果」处理。
- ⚠️ **重试账本的粒度是「轮」**（``TASK_ATTEMPT_LIMIT = 3``）：一轮 = N 次，
  正常**第 1 轮**那一行就翻成「已完成」，所以 3 轮是**纯容错**。
  ⚠️ 「一轮没跑完就回来了」**也要记账** —— 不记就是死循环（那一串动作名相邻两两
  都不同，主循环那本「同一动作 4 次」的账记不到它）。
- ⚠️ **对账读的是按钮长相，不是 ``x/3`` 那个数字**（``observe_task_rows`` 判的是
  ``task_todo`` / ``task_done``）。日志里**别写「计数没动」** —— 3 次制的计数每轮都在动，
  只是按钮要到第 3 次才翻成「已完成」。
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
#: 信息流右上角的 X = **关掉整个社区**。⚠️ 它只是社区里**三颗**同义 ⊗ 中的一颗
#: （另两颗在兑换中心与 H5 死掉那屏，位置各不相同）—— 那张表在 ``EXCHANGE_CLOSE`` 上方。
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
#
# ⚠️⚠️ **它不再是点击点 —— 只是「从哪儿开始找」的参照点**（`x` 用它的、`y` 当起点）。
#
# 2026-10-08 连续两次真机实跑里，`(400, 1450)` 都点在了**帖子里的图片**上 ⇒
# 图片被放大成整屏「图片查看器」⇒ 画面认不出 ⇒ 整条路线卡死
# （诊断帧 `runtime_diagnostics/epic7_community/current.png` 就是那张「欧勒毕斯·冒险手册」大图）。
#
# 根因不是「这次点歪了」：**盲坐标在滚动过的信息流里本来就不成立** ——
# 卡片高度由正文长短决定，滚动之后同一个 y 落在哪张卡的哪一块纯属抽签，
# 而这一屏里**唯一不能点的东西**恰好就是图片（点它 = 打开查看器）。
#
# ⇒ 落点改由 `pages.locate_feed_post_tap()` **现找**（找一条「白底 + 有字 + **不是图片**」
# 的正文带），这里的 y 只是那次现找的起点 ⇒ 原来点得对的时候行为不变。
# 同一个坑 2026-10-07 20:39 已经咬过一次（那次点是回程的「兑换」图标），
# 见 `FEED_ICON_ANCHORS` 上方那段。
FEED_FIRST_POST = (400, 1450)
# 卡片右下角那颗 👍。⚠️ **它是开关**：已经点过（实心青绿）时再点会**取消点赞**，
# 计数不涨反掉。10-07 实测 `act01` 就是把一张已绿的卡片点灰了 ⇒ 白花一次额度。
#
# ⚠️⚠️ **这里曾经钉过一个坐标 ``FEED_CARD_LIKE = (911, 735)``（已删）。**
# 2026-10-07 真机复量发现它是错的，两处都错：
#
# 1. **那一块根本不是 👍**。老代码配的读色框是 ``(880, 700, 70, 70)``，
#    放大一看是 tab 栏「骑士团」三个字（纯白，rgb 243.9/244.2/245.4）。
#    于是「点之前先看颜色，只点灰的」这道闸门**从来没读到过 👍** ——
#    ``card_like_is_on()`` 恒返回 ``False``（=「没点过」），等于没有闸门。
# 2. **y 会随卡片高度漂**。卡片高由正文长短决定，同一帧里两张卡的 👍
#    实测分别在 y 756 与 y 1314（差 558px）。钉死一个 y 只在那一次测量的
#    那一屏上成立，换一屏就点空 —— 而点空的下一次落点可能就在 tab 栏上。
#
# ⇒ 现在改成**运行时现找**（用户 2026-10-07 拍板的 C 方案：「不假设位置，直接在
# 信息流里**找**那颗还未点赞的 👍，找不到就继续下滑」）。找的动作在
# ``pages.locate_card_like()``，模板 ``card_like_off``（**空心描边**那颗；
# 已点过的是实心青绿，与它不同形，实测在本模板下只到 0.43）。
# 「去完成」→ 信息流之后走这一次滑动，把卡片 👍 带进视野（10-07 实测）。
# ── 滑动手势的起点列：一律贴左边缘的白边（2026-10-08，用户提的角度）──────────
#
# ⚠️ **滑动起点的 x 一律用这个值，不许再用 540（页面正中）。**
#
# 用户 2026-10-08 的原话：「如果保险点可以从左边的边缘那些地方往下拉，它就不会碰到中间的
# 图片了」。量了一遍，他说得对 —— 6 张真机页面帧（信息流 5 张 + 帖子详情）逐列统计
# **该列的彩色像素占比**（y 240~1760）：
#
# | 列 | x=20 | x=40 | **x=60** | x=80 | x=100 | x=540 |
# | --- | --- | --- | --- | --- | --- | --- |
# | 最低~最高 | 0.000 | 0.000~0.012 | **0.000~0.003** | 0.000~0.003 | 0.000~0.018 | **0.057~0.191** |
#
# 信息流的卡片是通栏白底、插图**居中** ⇒ 中间那一列**确实穿过插图**，左边缘是干净的。
#
# ## 为什么这值得改（不只是「保险点」）
#
# 风险不是「滑一下会点开图」—— 实测 `input swipe` 从插图中间滑过很多次（帖子详情里的
# 浏览下滑）都没打开过查看器。风险在于**这条手势一旦退化成点击**：
# `CommunityRunner._perform_action` 只在 ``swipe_end`` 非空时才发 ``swipe``，
# 那面旗子一丢，主循环就**在起点点一下**（2026-10-07 点赞任务三遍全废正是这个形状）。
# 起点在 x=540 的插图上 ⇒ 打开图片查看器 ⇒ 整条路线卡死；起点在白边上 ⇒ 什么也不会发生。
#
# ⚠️ 只改**滑动**（起点会被降级成点击的那一类）。不动 ``NETWORK_PULL_START``：
# 那一页（H5 报「网络连接异常」）整屏没有插图，而且下拉刷新本来就该从页面中部拉。
SCROLL_GUTTER_X = 60

# 「去完成」→ 信息流之后走这一次滑动，把卡片 👍 带进视野（10-07 实测）。
FEED_TASK_SCROLL_START = (SCROLL_GUTTER_X, 1500)
FEED_TASK_SCROLL_END = (SCROLL_GUTTER_X, 700)
FEED_TASK_SCROLL_MS = 400

# 「往回滚」——方向和上面那对**正好相反**。
#
# ``FEED_TASK_SCROLL_*`` 是「往**下**看」：手指上移、内容上移，去找下面的卡片。
# 这一对要的是「往**回**看」：手指下移、内容下移，把滚上去的信息流顶部
# （四宫格那行）重新拉回视野。回「我的任务」要点的「兑换」图标就在那里。
#
# ⚠️ **2026-10-10 加大行程**（800px → 1390px）：原来只有 700→1500，而这两下
# **主循环对同名动作只给 4 次**（``runner_base`` 的 `action_attempts > 4` ⇒ 一次
# 「换个办法」⇒ 再不行就报错）。实跑里「找 👍」那一步往下滑了 **6 次**（08:06:07~
# 08:06:42，每次 800px），往回滚要是也按 800px 一屏一屏地退，4 次根本退不回顶部。
# 内容区的实际可用范围是 y 250~1750（``community_pages.FEED_TAP_STRIP`` 那条注释：
# 再往上会碰到搜索栏与 tab 行、再往下是底部四格导航栏），所以取 360~1750 接近满行程。
# ⚠️ 起点仍在 ``SCROLL_GUTTER_X`` 那道**左边缘白边**上 —— 万一手势被降级成点击，
# 那一下落在白边上什么也不会发生（这条纪律见 ``SCROLL_GUTTER_X`` 上方那段）。
FEED_ICON_SCROLL_START = (SCROLL_GUTTER_X, 360)
FEED_ICON_SCROLL_END = (SCROLL_GUTTER_X, 1750)

# 「往回滚」最多滚几次。滚到顶之后四宫格必然露出来，再滚也不动 ⇒ 到上限还没
# 看见就说明不是「滚过头」而是**页面真的变了**（活动换皮/入口搬家），
# 那时必须**报错收手**，绝不蒙着点那个坐标（点下去会打开帖子图片 ⇒ 卡死）。
#
# ⚠️ **2026-10-10：3 → 4**。原来的 3 是在「一次滚 800px」的前提下定的；那时
# 3 屏 = 2400px，而实跑里往下滚过 6 屏（≈4800px）⇒ 还没退到顶就先自己报错了。
# 现在一次 1390px、上限 4 ⇒ 最多退 5560px，坐得下。**刻意与主循环的 4 次对齐**：
# 路线的闸门必须**早于或等于**主循环的账本，否则会出现「路线还在滚、主循环已经
# 判它四次未转场」的错位（10-10 实跑就是后者先炸的）。
FEED_ICON_RESWIPE_LIMIT = 4

# 「滚不动了」= **连续**这么多次滑动之后，画面结构（正文带位置表）仍然一点没变。
#
# ⚠️ 这是 2026-10-10 用户拍板的「**滚到顶为止**」那条：不再靠「猜一个够大的次数」
# 来决定什么时候收手，而是**读画面自己说「我到底了」** —— 已经到顶的 H5 再往下拖
# 就是不动，位置表一个像素都不变（``_register_swipe_emission`` 的判据）。
# 取 2 而不是 1：单次「没动」可能只是刚滑完还没落定，连着两次才作数。
FEED_ICON_STUCK_FRAMES = 2

# ⚠️ 2026-10-09 立：上面这两个「滑满 N 屏就放弃」的上限，数的必须是**真的发生了
# 的滑动**，不是「想滑动的帧数」。主循环对**同名动作**有重试节流
# （``CommunityRunner._action_retry_seconds``：同名动作 45 秒内只执行一次，
# 2026-10-09 起这两个手势单独给 3 秒），节流窗口里状态机**每一帧**都会重新
# 「想滑」—— 按帧记账的话，上限几秒就烧穿，实际却一屏都没滑。
# 2026-10-09 13:04 实跑就是这样：日志里只有 1 次「执行滑动」，
# 却报了「往回滚了 3 屋」（原文：往回滚了 3 屏）。
#
# 所以记账看**结构证据**：正文带位置表（``pages.feed_band_tops``）变没变。
# 滚 800px 会整体换一批正文带；头像/动图那种局部动画不会。
SWIPE_MOVE_MIN_PX = 120

# 上一滑一直没生效（节流没放开 / 页面锁滚动）时，最多重发多少帧就如实报错。
# 生产上竖屏一帧约 2 秒，30 帧 ≈ 60 秒 > 重试窗口（3 秒）的十倍余量；
# 真在滚动却账不动的情况由「位置表变了」覆盖，这条只兜「完全没执行」。
SWIPE_UNEXECUTED_FRAME_LIMIT = 30

# 「浏览帖子」浏览**一篇**的完整动作是：点开 → **在帖子详情里往下滑一下** →
# **停一会儿** → 返回。用户 2026-10-07 的口径原话：「点到这个帖子里面，稍微往下滑一下，
# 停留个 5~10 秒，然后退出来，这个就算浏览一次了」。
#
# ⚠️ 这两下（滑 + 停）**不是**可有可无的装饰：不滑不停，游戏多半不记这次浏览，
# 于是那一行永远停在 0/3，跑满上限判「今天做不成」—— 而画面看起来一切正常。
POST_SCROLL_START = (SCROLL_GUTTER_X, 1500)
POST_SCROLL_END = (SCROLL_GUTTER_X, 900)
# 停在区间中位，5~10 秒都合规；取中位是为了两边都留余量（也不是掐着下限走）。
POST_DWELL_SECONDS = 6.0

# 每条任务**一轮**要做几次 —— 一轮之内**连续做完**，做完才回「我的任务」对账**一次**。
#
# ⚠️ 2026-10-07 用户拍板改掉旧粒度。旧粒度是「做一次 → 绕回我的任务对账 → 再做一次」，
# 而**每次点「去完成」都重新落在信息流顶部**（10-07 四次实测同一帧）⇒ 第二遍
# 「下滑一次」又滑到**同一张卡 / 同一篇帖**：浏览等于白做，点赞则是对一颗**已经绿了**
# 的 👍 再点一下、把赞**取消**掉。旧代码里那个「已绿就再滑一次」的补偿只是在打地鼠。
#
# 次数依据：任务页那五张进度字形模板的命名（``strings/tasks/`` 的
# ``0_1 / 0_3 / 1_1 / 1_3 / 3_3``）⇒ 浏览与点赞是 ``x/3``，分享是 ``x/1``。
TASK_ROUND_TIMES: dict[str, int] = {"browse": 3, "share": 1}
# ⚠️ 原为 ``{"browse": 3, "like": 3, "share": 1}`` —— **2026-10-11 摘掉 "like"**
# （用户拍板）。原因见 ``community_pages.TASK_ROWS`` 那段：点赞状态被服务端永久记住
# ⇒ 越翻越找不到可点的 👍 ⇒ 死循环。
#
# ⚠️⚠️ **``"like": 3`` 这个值本身仍然有效**，只是不在生产清单里了：
# ``_LIKE_ONE`` / ``LIKE_RESWIPE_LIMIT`` / ``pages.locate_card_like`` / ``_VERIFY_LIKE_ON``
# 这些**代码与机制一律保留**（用户拍板「保留代码」），护栏在 ``test_community.py`` 里
# 用 ``patch.dict`` 临时把 "like" 注册回来跑。要真正恢复点赞，把这一项加回来即可。

# 一条任务最多跑几**轮** —— **绝不死循环**（账本要记的是「跑了几轮」，而不是
# 「试到成功为止」，后者会在判据失灵时无声转到底）。
#
# ⚠️ 语义与旧版完全不同：旧版一轮 = 1 次，所以上限必须**大于**要求的次数
# （6 = 3 次 + 3 次容错），否则点空一次就等于判死。现在一轮 = N 次，
# **正常情况第 1 轮那一行就翻成「已完成」**（3 次都在这一轮里做完了），
# 所以 3 是**纯容错**：留两整轮给「某一下没生效」。
TASK_ATTEMPT_LIMIT = 3

# ⚠️ ``TASK_SCRIPT`` / ``TASK_LABELS`` 排在**所有坐标都定义之后**（文件下面那一块）：
# 脚本里要按名字引用 `POST_BACK` / `POST_SHARE` / `SHARE_COPY_LINK`，
# 放在坐标区中间会 `NameError`（2026-10-07 踩过）。
# 「这一屏**找不到**还没点过的 👍 ⇒ 再往下滑一次换一屏」的次数上限。
#
# ⚠️ 语义（2026-10-07 改）：老版是「读到那颗 👍 已经是绿的才滑」，而那次读数
# 读的是 tab 栏（见 ``FEED_FIRST_POST`` 上方那段）—— 也就是说这个补偿机制
# **从来没被触发过正确的输入**。现在触发条件是字面意义上的「没找到」：
# 模板在整条卡片带里都没过阈（这一屏没有卡片 / 卡片全点过了）。
#
# ⚠️ 必须有上限，否则「一路都是已点过的卡片」会变成死循环（项目红线：绝不死循环）。
# 计的是**连着**滑了几次都没找到，一旦找到并点下去就归零。
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

# 社区这几页上有**三颗**长得像的 ⊗，位置与外径都不一样，而它们的语义是**同一件事**：
# **关掉整个社区**（点完模拟器转回横屏，回到网页活动列表）。
#
# ⚠️ 这张表是 2026-10-09 用真机一步步量出来的，别照图目测、更别假设「同一个按钮」：
#   - 信息流右上 X ：外径 44，圆环中心 (937,  92)  ← 最早认的就是它（``FEED_CLOSE``）
#   - 兑换中心右上 ✕：外径 48，圆环中心 (989, 123)
#   - H5 死掉那屏   ：外径 33，圆环中心 (1000, 78)  ← 「网络连接异常，下拉刷新」页
# 三个外径 33/44/48 互不相等 ⇒ 是**三颗不同的钮**（各页自己画自己的头），
# **不是同一颗挪了位置**。所以「按判页挑对的那一颗」是必须的，不能拿一颗顶三颗。
#
# ## 为什么收工走这里，而不是左上角的 `<`
#
# 2026-10-09 真机实跑（19:49）把 `<` 钉死了：它是 **H5 历史返回**，而兑换中心是从
# 「我的任务」点「去兑换」进来的 ⇒ 点 `<` 回到的是**「我的任务」**，不是信息流。
# 更糟的是「我的任务」的 `<` 又指回兑换中心 —— 两页**互为历史上一页**，
# 靠返回键**永远回不到信息流**（19:49:50 兑换中心 --(36,121)--> 我的任务，
# 19:49:56 我的任务 --(35,130)--> 兑换中心，来回打转，两次各干等 150 秒超时才停）。
#
# ## ⚠️⚠️ 2026-10-09 20:2x 探针复量：兑换中心这颗 ✕ **关的是整个社区**
#
# 19:58 那次实跑点了它之后卡死（150 秒超时）。当时的猜测是「它只关掉兑换中心这一层、
# 回信息流，所以要接着点信息流的 X」—— **猜错了**。真机探针
# （``.workbuddy/_probe_exchange_close_layer.py``）逐步判页走到底：
#
#     信息流判页=feed_home → 点「兑换」→ 判页=exchange_center
#     → 点 (989,123) → **3 秒后 ``is_portrait()`` 已经是 False、客户区 1920x1080**
#     → 8 秒后仍是横屏，画面就是**网页活动列表**
#
# 也就是说：**在兑换中心点一下 ✕，社区就整个关掉了，一次点击直达横屏，中间没有信息流。**
# 同一个结论还有第二条独立证据：H5 死掉那屏（「网络连接异常，下拉刷新」）点它自己那颗
# ⊗ (1000,78)，窗口同样在 4 秒内从 1023x1820 变回 1920x1080。
#
# ⇒ 收工从兑换中心**一步到位**，「先回信息流再点 X」那一段**根本不需要**，
# 而且它建立在「✕ 只关一层」这个错误前提上 —— 这正是 19:58 那次卡死的原因：
# 社区已经关了，状态机却停在 ``FEED`` 等一页**永远不会出现**的竖屏信息流。
EXCHANGE_BACK = (36, 121)
#: 兑换中心右上角的 ✕：**关掉整个社区**（不是「关掉这一层浮层」）。
#: 点完模拟器转回横屏、落在网页活动列表 ⇒ 收工那一步的动作与 ``close_community`` 同形。
EXCHANGE_CLOSE = (989, 123)
#: H5 整页死掉那一屏（白底 +「网络连接异常，下拉刷新」）右上角那颗 ⊗ —— 它**同样关掉整个社区**
#: （真机实测：点完 4 秒内 ``1023x1820`` → ``1920x1080``）。收尾扫地出门时要试到它。
NETWORK_PAGE_CLOSE = (1000, 78)

#: 收尾「扫地出门」时**按序试**的三颗 ⊗。⚠️ 只给 ``_leave_portrait_if_needed`` 用 ——
#: 主流程**不许**这样试，必须按判页挑对的那一颗（三颗外径 33/44/48，不是同一颗挪位置）。
_EXIT_CLOSE_POINTS = (FEED_CLOSE, EXCHANGE_CLOSE, NETWORK_PAGE_CLOSE)
#: 收尾里**每一颗** ⊗ 的等转屏预算。三颗全试满也才 15 秒（原来的总预算 8 秒一个都不够试）；
#: 正常情况第一颗就该成功（转屏实测 1~3 秒），所以这个数只对「试错了」那一档有意义。
_EXIT_CLOSE_ATTEMPT_SECONDS = 5.0
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

    ## 入口标志 ``enter``：动手**之前**必须看到什么

    ``page`` 只说「必须停在哪一页」，但「在信息流这一页」**不等于**「该点第二篇了」——
    浏览第二篇时，信息流必须已经**往下滑过一次**，否则点下去还是第一篇。
    这句人话就是补上这个缺口的：它和 ``note`` / ``evidence`` 一样先当**文档**，
    等哪一项有了机器可读的判据，就提到 ``verify`` 上去真读。
    （2026-10-07 用户要求：每个动作都要有**输入和输出**两个标志。输入 = ``page`` +
    ``enter``；输出 = ``next_page`` 或 ``evidence`` + ``verify``。）
    """

    kind: str                       # tap / tap_post / tap_like / swipe
    page: str                       # 这一步必须在哪一页动手
    # 点击点；滑动时是**起点**。
    # ⚠️ ``None`` = 「**位置运行时现找**」，``tap_like`` 与 ``tap_post`` 允许这么写：
    #
    # - ``tap_like`` ⇒ ``pages.locate_card_like``：那颗 👍 的 y 随卡片高度漂
    #   （同帧实测能差 558px），钉死坐标就是点空、点空之后可能落在 tab 栏上。
    # - ``tap_post`` ⇒ ``pages.locate_feed_post_tap``：钉死的 y 会落到**帖子里的图片**上
    #   ⇒ 图片被放大成全屏查看器 ⇒ 画面认不出、整条路线卡死（2026-10-08 连续两次实跑）。
    #
    # 两个都是「**找不到就不许动手**」：现找返回 ``None`` 时调用方只许报错收手或再滑一屏。
    # ``_step_action`` 拿到 ``None`` 且调用方没给替代点时会**当场抛**，不会静默点 (0,0)。
    point: Optional[tuple[int, int]]
    note: str                       # 日志用的人话
    enter: str = ""                 # 入口标志：动手前必须看到什么（见类文档）
    next_page: str = ""             # 换页：这一步做完应该在哪一页
    evidence: str = ""              # 不换页：靠页面内什么变化验收（给人 + 给契约看）
    verify: str = ""                # 不换页：``_evidence_seen`` 真去读的检查项
    end: tuple[int, int] = ()       # 滑动的终点（只有 ``swipe`` 用）
    # 出手之后**再停几秒**（0 = 不停）。浏览那一篇要用：滑一下之后得停 5~10 秒，
    # 游戏才认这次浏览（用户 2026-10-07 口径）。睡眠由 Runner 去做 ——
    # 状态机「不碰 sleep」，只声明意图（同 ``swipe_end`` 的分工）。
    dwell_seconds: float = 0.0


# 不换页那一步的验收检查项。值就是 ``TaskStep.verify`` 的取值。
_VERIFY_LIKE_ON = "like_on"        # 卡片 👍 由灰转绿

# 出手之后最多等几帧看业务结果（主循环约一秒一帧 ⇒ 这里约 8 秒）。
# ⚠️ 等不到就**作废本遍**，绝不重复出手 —— 那颗 👍 是开关，点第二次会把赞取消。
_VERIFY_FRAME_LIMIT = 8

# ── 一轮的脚本 ────────────────────────────────────────────────────────────────
#
# 粒度是**一轮**：轮内**连续做完** ``TASK_ROUND_TIMES`` 次，做完才回「我的任务」对账一次。
# 每条任务写成「一个单元 × N 次」，中间夹一次「换下一个」的动作（只有浏览需要）。

# 浏览**一篇**：点开 → 在详情里往下滑一下并停留 → 返回。
_BROWSE_ONE: tuple[TaskStep, ...] = (
    TaskStep(
        "tap_post",
        "feed_home",
        None,  # 位置**现找**：见 pages.locate_feed_post_tap 与 FEED_FIRST_POST 那段
        "点开一张帖子（落点现找，绝不在图片上下手）",
        enter="在信息流，这一篇还没点过（本轮还没为它滑过）",
        next_page="post_detail",
    ),
    TaskStep(
        "swipe",
        "post_detail",
        POST_SCROLL_START,
        "在帖子里往下滑一下，再停一会儿",
        enter="在帖子详情（刚点进来）",
        evidence="帖子详情往上滚了一小段，并停够 5~10 秒（本页不变）",
        end=POST_SCROLL_END,
        dwell_seconds=POST_DWELL_SECONDS,
    ),
    TaskStep(
        "tap",
        "post_detail",
        POST_BACK,
        "看完退回信息流",
        enter="在帖子详情，已经滑过、停够了",
        next_page="feed_home",
    ),
)

# 回到信息流之后要**往下滑一次**才换得到下一篇 —— 不滑的话点下去还是同一篇
# （返回信息流时滚动位置不会自己往前走）。
# ⚠️ 「滑一次 = 往前一篇」用的是 10-07 实测的位移，**跨天没复验**；位移动了就要重标。
_BROWSE_NEXT_POST = TaskStep(
    "swipe",
    "feed_home",
    FEED_TASK_SCROLL_START,
    "往下滑一次，把下一篇帖子带上来",
    enter="在信息流，下一篇还没上来",
    evidence="信息流滚动了一屏（本页不变）",
    end=FEED_TASK_SCROLL_END,
)

# 点赞**一个**：**先找再点**（用户拍板的 C 方案）。位置不写死 —— 见 ``TaskStep.point``。
#
# ⚠️ 这一单元**只有一步**，是刻意的：
#
# - 老写法是「先滑一次 → 再点固定坐标」，而滑动是**无条件**发的 ⇒ 只要这一屏
#   已经有一颗没点过的 👍 露在外面，这一滑就把它推走了，白白多点一屏。
#   现在的顺序反过来：**先找，找不到才滑**（滑动那个补偿动作在 ``_drive_task`` 里，
#   由 ``LIKE_RESWIPE_LIMIT`` 封顶）。
# - 「点之前先确认这颗还没点过」**由模板本身承担**：``card_like_off`` 只收
#   **空心描边**那颗，已点过的实心青绿在它下面只到 0.43 ⇒ 「命中」即「还没点过」。
#   不需要再补一道读色闸门（补了也是跑不到的分支，而跑不到的分支比没有更糟）。
_LIKE_ONE: tuple[TaskStep, ...] = (
    TaskStep(
        "tap_like",
        "feed_home",
        None,  # 位置现找：见 TaskStep.point 与 pages.locate_card_like
        "找一颗还没点过的 👍 点下去",
        enter="在信息流，这一屏还有一颗没点过的 👍（没有就先往下滑，见 _drive_task）",
        evidence="那颗 👍 由空心描边变成实心青绿",
        verify=_VERIFY_LIKE_ON,
    ),
)

# 分享**一次**：本来就是一次做完，不重复。
_SHARE_ROUND: tuple[TaskStep, ...] = (
    TaskStep(
        "tap_post",
        "feed_home",
        None,  # 位置**现找**（同上）
        "点开一张帖子（落点现找，绝不在图片上下手）",
        enter="在信息流",
        next_page="post_detail",
    ),
    TaskStep(
        "tap",
        "post_detail",
        POST_SHARE,
        "点帖子底部的分享",
        enter="在帖子详情",
        next_page="share_sheet",
    ),
    TaskStep(
        "tap",
        "share_sheet",
        SHARE_COPY_LINK,
        "点「复制链接」",
        enter="在分享面板",
        next_page="post_detail",
    ),
    TaskStep(
        "tap",
        "post_detail",
        POST_BACK,
        "返回信息流",
        enter="在帖子详情（分享面板已收起）",
        next_page="feed_home",
    ),
)


def _round_script(
    unit: tuple[TaskStep, ...],
    times: int,
    *,
    between: TaskStep | None = None,
) -> tuple[TaskStep, ...]:
    """把「一个单元」重复 ``times`` 次拼成一**轮**；``between`` 夹在两次之间。

    为什么要拼而不是手抄：浏览一轮是 11 步，手抄很容易把中间那次下滑多写一次或
    少写一次 —— 多滑一次会**跳过一篇**（少浏览一次），少滑一次会**重复浏览同一篇**。
    两种错都只在真机上才看得出来，所以在源头消掉。
    """
    steps: list[TaskStep] = []
    for index in range(times):
        steps.extend(unit)
        if between is not None and index + 1 < times:
            steps.append(between)
    return tuple(steps)


TASK_SCRIPT: dict[str, tuple[TaskStep, ...]] = {
    "browse": _round_script(
        _BROWSE_ONE, TASK_ROUND_TIMES["browse"], between=_BROWSE_NEXT_POST
    ),
    "share": _SHARE_ROUND,
}

# 任务 key → 中文名（日志用；与「我的任务」页面上的字一一对应）。
TASK_LABELS = {row.key: row.label for row in pages.TASK_ROWS}

# ── 「网络连接异常，下拉刷新」：**照它要求的做 —— 下拉刷新** ────────────────────
#
# 2026-10-07 用户拍板改掉旧做法（旧的是「退出去重进」），原话：
# 「你就是应该按照他的要求下拉刷新」。两条理由：
#
#  ① 这一页**自己写了出路**，就照它写的做。退出重进的代价是「大厅 → 活动页 →
#     网页活动列表 → 转竖屏」整条链重来（实跑一轮 90 秒以上），而重进之后落在
#     信息流顶部，已经做完的任务进度全要重新对账。
#  ② 旧做法在真机上**压根没生效**。实跑日志 20:31:35 点「兑换」→ 20:32:00
#     连记 3 次「网络异常」，中间**一条 ``执行点击 动作=logout_community`` 都没有**：
#     那个动作被主循环当成「转场中的杂音」丢掉了（见 ``CommunityRunner._transition_completed``
#     的覆写）。而且它点的 ``FEED_CLOSE``=(937,92) 也**不是这一页的 X** ——
#     这一页的 X 实测在 (1000, 78)（暗色连通域外接框 (984,62,33,33)，
#     夹具 ``network_error_live_20261006``），(937,92) 落在空白上。
#
# 手势：从画面中上部**往下拖**（手指下移 = 内容下拉复位）。时长取 800ms 是刻意的 ——
# 下拉刷新手势要**慢**，快甩会被当成惯性滑动，不会触发刷新。
NETWORK_PULL_START = (540, 560)
NETWORK_PULL_END = (540, 1560)
NETWORK_PULL_MS = 800

# 一次运行内**总共**拉活几次就不再试。按「页面刚死」那一次记一笔，**不是按帧** ——
# 按帧记的话计数器几秒就穿（实跑证据：旧计数器 21 秒内涨了 3）。
#
# ⚠️ 上限的作用与旧写法**不同**，别照旧注释理解：旧写法每次换一个动作名
# （``logout_community`` / ``enter_community``），主循环那本「同一动作 4 次」的账
# **记不到它**，所以才要自己记一笔账防乒乓。现在动作名**固定**
# （``refresh_community_page``），同一页反复拉活由主循环那本账兜住（4 次即失败关闭）；
# 这道闸门管的是另一件事 —— 「拉活 → 活过来 → 干两下 → 又死」这种**跨页面**的反复横跳。
NETWORK_REFRESH_LIMIT = 3


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
    REFRESHING = "refreshing"    # 已发出「下拉刷新」，等 H5 活过来
    IMAGE_VIEWER = "image_viewer"  # 图片被点开放大成全屏，已按返回键，等它消失
    #: **陌生页**：判页认不出、也不在任何已知浮层里。走「逃生门」（返回键），
    #: 不再原地干等 —— 见 ``_on_stranger_page`` 与 ``STRANGER_RECOVER_STEPS``。
    RECOVERING = "recovering"
    BLOCKED = "blocked"          # 网络异常，连着拉活也没活过来，停
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
    CommunityState.IMAGE_VIEWER: "图片被放大成全屏，已按返回键等它消失",
    CommunityState.REFRESHING: "已下拉刷新，等 H5 活过来",
    CommunityState.RECOVERING: "陌生页，正在按返回键退出它",
    CommunityState.BLOCKED: "网络异常（拉活没成功）",
    CommunityState.DONE: "已收工",
}


def state_label(state: CommunityState) -> str:
    return STATE_LABELS.get(state, state.value)


# 「正在转场 / 加载，页面还没稳」的状态。这几档里 ``observe`` 判不出页面**不算故障**，
# 正确反应是**只等**（转场契约：来源已离开、目标未稳 ⇒ 只等待）。
#
# ⚠️ 只放真的**在转场**的那几档。竖屏段别的状态认不出仍然是硬错误 —— 那时页面早该在了，
# 认不出就是真出问题了，不该拿「可能是加载中」当借口。
_SETTLING_STATES = frozenset(
    {
        CommunityState.ENTERING,    # 点完「游戏社区」：等模拟器转竖屏 + H5 画出首帧
        CommunityState.REFRESHING,  # 发完下拉刷新：等 H5 重新画出来
        # 按完返回键关查看器：那一刻 H5 正在收这个覆盖层，会有几帧谁也认不出。
        # 不放进这里的话，那几帧会走「认不出 ⇒ 硬错误」⇒ 刚修好的路又断在这儿。
        CommunityState.IMAGE_VIEWER,
    }
)

# ── 陌生页逃生门（2026-10-18 立）─────────────────────────────────────────────
#
# ## 它治的是什么 —— 先把「根」说清楚
#
# 之前的约定是：**认不出这一页 ⇒ 抛错、等状态超时（150 秒）⇒ 整条路线失败**。
# 这条约定默认了一个前提：**程序只会在已登记的那 11 页之间移动**。
# 而社区是个 H5，页面是**开放集合**（账号主页 / 话题页 / 转发页 / 举报页 / 活动页…），
# 这个前提根本不成立。
#
# 于是每一次"点歪了一点点"都变成一次整条路线失败。11 天里同样的失败 **15 次**
# （``runtime_logs/epic7_community.log`` 里 ``UnrecognizedCommunityScreen`` 那 15 行），
# 每一次都长得一模一样：``最高分 0.0000；已知观察=[]``。
#
# ## 为什么「再补一页判据」不是办法
#
# 那是**用穷举去对抗一个开放集合**。已经补过：图片查看器、兑换图标、正文带、四宫格两个落点…
# 每补一个，H5 那边还有下一个。补不完。
#
# ## 所以改成：陌生页是一等公民的**可恢复状态**
#
# 不认识的页面,**先退出去**再说。退出去之后回到已登记页 —— 判页立刻重新接上。
# 「返回」是这一族 H5 页面**唯一通用的逃生门**：账号主页、话题页、图片查看器、
# 分享面板、帖子详情，按返回都回到上一层。
#
# ## 动作阶梯（**有界**，绝不死循环）
#
# | 序 | 动作 | 为什么 |
# | --- | --- | --- |
# | 1 | 系统返回键 | `portrait.back()` = `adb shell input keyevent 4`，通道现成（图片查看器在用） |
# | 2 | 系统返回键（再来一次） | 有的页第一下只关掉一层浮层；也可能是按早了没吃到 |
# | 3 | 点**左上角返回箭头** | ⚠️ 实测「我的任务」页对系统返回键**完全没反应**（`core/portrait.py::back` 的 docstring），只靠返回键会漏这一页 |
#
# 三步都走完还是认不出 ⇒ 抛错收手（走原有的失败路径）。
#
# ## 两条不许省的保险
#
# - **按一次 → 判一次**：每按完必须等 ``STRANGER_WAIT_FRAMES`` 帧重新判页，判到已知页立刻停。
#   连按会把社区**整个退出去**（代价是重进 90 秒），比现在的错还贵。
# - **先等两帧再动手**：点完页面那一两秒 H5 可能正在画下一屏，那时整个画面本来就认不出。
#   不等就直接按返回，会把一次**正常的转场**当成陌生页处理掉。
STRANGER_RECOVER_STEPS: tuple[str, ...] = ("back", "back", "back_arrow")

#: 每一级动作之间**先等几帧再判**。
#:
#: ⚠️ 取 4 而不是 2，是有实测依据的：日志里「点击 → 目标页确认」的间隔
#: （18:30:20→25 / 25→29 / 29→33 / 33→37）一直是 **4~5 秒**。
#: 等得比它短 ⇒ 会把一次**正常的换页转场**当成陌生页、按返回把它按掉 ——
#: 那比"晚几秒恢复"贵得多。等得比它长也只是多等一两秒。
#: 上限：3 级 × (4 帧确认 + 1 次动作) ≈ 15 帧，压在 ``RECOVERING`` 的 60 秒里。
STRANGER_WAIT_FRAMES = 4

#: 第 3 级那条路用的点：**左上角的返回箭头**。
#:
#: 之所以要钉一个点，是因为对一个**不认识的**页面没法现找锚点（认得出就不用逃生门了）。
#: 账号主页（``20261018_183328_870617_timeout_feed.png``）的 ‹ 实测在 (43, 70) 附近；
#: 帖子详情是 (154, 97)、我的任务是 (35, 130) —— 三者都在左上这块 200x160 里，
#: 所以取它们的中间值，落在这块区域的任何一个箭头热区上都仍然算"按到了箭头那一块"。
STRANGER_BACK_ARROW = (60, 95)

#: 逃生门产出的动作名。``_transition_completed`` 靠它认「这一下是去退陌生页的」，
#: 从而把上一个动作的出口验收**作废**（不然那个等不来的目标会一直在等）。
STRANGER_ACTIONS = frozenset({"stranger_back", "stranger_back_arrow"})


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
    #: 出手之后**再停几秒**（0 = 不停）。浏览那一篇要用。睡眠由 Runner 去做 ——
    #: 与 ``swipe_end`` 同一条分工：状态机只声明意图，不碰 ``sleep``。
    dwell_seconds: float = 0.0
    #: 这一步按**返回键**而不是点击（``point`` 只是兜底落点）。
    #:
    #: 目前只有「图片查看器」用它：那一屏上**没有任何可点的控件** —— 实测上下两条
    #: 全黑带占 83%、中间只有一张帖子里的图，连返回箭头都没有，能消掉它的只有
    #: 系统返回键（``runtime._back``，竖屏段走 ``portrait.back()``，
    #: 与收尾那步用的是同一条通道）。
    #:
    #: ⚠️ 仍然要填 ``point``（``RouteAction`` 的契约，没有默认值）—— 填的是**图片正中**：
    #: 万一这面旗子没被认出来，落在图片上（有可能顺手关掉查看器）也比落在 ``(0, 0)``
    #: 强得多 ——「静默点 (0,0)」正是本文件明确要避免的那种最难查的失败。
    press_back: bool = False


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


def card_like_is_on(screen: np.ndarray, point: tuple[int, int]) -> Optional[bool]:
    """``point`` 那颗 👍 现在是不是**已经点过**（实心青绿）。

    读不出来（出界 / 画面尺寸不对）返回 ``None``。

    ## ⚠️ 必须给「哪一颗」

    老签名是 ``card_like_is_on(screen)``，读的是一个**写死的框**
    ``FEED_CARD_LIKE_BOX = (880, 700, 70, 70)``。2026-10-07 真机复量：那一块是
    tab 栏「骑士团」三个字，纯白 ⇒ 这个函数**恒返回 False**（=「没点过」），
    两道用它做的判断（点之前别点已绿的、点之后要读到变绿）**两边都失效**。
    现在框由 ``pages.card_like_reading_box(point)`` 按**实际点下去的那个点**现算，
    所以这道读数终于落在真正要读的那颗 👍 上。

    为什么必须读一下再点：那颗 👍 是**开关**。已绿的再点一次会把点赞**取消**，
    计数不但不涨还会倒扣（2026-10-07 实测 `act01` 把一张已绿的卡片点灰、白花一次额度）。
    """
    patch = _box_patch(screen, pages.card_like_reading_box(point))
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
        # 这一次运行里**拉活 H5**（下加拉活）了几次。按「页面刚死」那一次记一笔，
        # 不是按帧 —— 按帧记的话计数器几秒就穿（旧写法实跑 21 秒涨了 3）。
        self._network_refreshes = 0
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
        # 「点赞」那一步因为**这一屏找不到没点过的 👍** 而**临时再滑一屏**的次数。
        # 没有它，一屏全是已点过的卡片就能把主循环卡在信息流里空转。
        # 计的是**连着**几次都没找到；一找到并点下去就归零。
        self.like_reswipes = 0
        # 最近一次「点赞」**实际点下去的那个点**（``pages.locate_card_like`` 现找出来的）。
        # 两个用处：① 出手之后按**这个点**去读「变绿了没有」—— 老代码读的是写死的
        # 框（实际是 tab 栏），于是那道验收永远读成「没变」；② 日志里报得出到底点了哪。
        # ``None`` 表示还没点过任何一颗。
        self.like_point: Optional[tuple[int, int]] = None
        # 「回我的任务」那一步因为**这一屏看不见信息流顶部的「兑换」图标**而
        # **往回滚一屏**的次数。原因见 ``_return_to_tasks``：任务做完时信息流多半
        # 已经滑过好几屏，四宫格早滚出视野，钉死的那个坐标底下是帖子图片。
        # 计的是**连着**几次都没看见；看见并点下去就归零。
        self.feed_icon_reswipes = 0
        # ⚠️ 2026-10-09：滑动手势的「账本证据」。上面两个 reswipe 计数器数的必须是
        # **真的执行了的滑动**，而主循环对同名动作有重试节流 —— 节流窗口里每个帧
        # 都会重新「想滑」。这里记着「上一次发出的是哪个滑动手势 + 发出时的正文带
        # 位置表」：位置表变了 = 上一滑真的执行了 = 下一次发出才准记账。
        # 详见 ``_register_swipe_emission`` 与 ``SWIPE_UNEXECUTED_FRAME_LIMIT``。
        self._pending_swipe_name: Optional[str] = None
        self._pending_swipe_tops: Optional[list[int]] = None
        self._pending_swipe_streak = 0
        # 每条任务试过几遍、哪几条已经判定「今天做不成」。
        self.task_attempts: dict[str, int] = {}
        self.stuck_tasks: set[str] = set()
        # 上一次在「我的任务」页读到的三行状态（用来判「刚跑完的那条涨没涨」）。
        self._tasks_before: dict[str, str] = {}
        # ── 陌生页逃生门的三本账（2026-10-18 立，见 ``STRANGER_RECOVER_STEPS``）──
        # ① 这一趟陌生页已经发过几级动作（决定下一级是返回键还是左上角箭头）；
        # ② 发完动作之后等了几帧（「按一次判一次」用的：等满才准发下一级）；
        # ③ 进陌生页那一刻跑的是哪条任务的第几步 —— 逃生成功后要**退回那一步重做**，
        #    否则 ``task_step`` 已经翻过去，下一帧会拿"下一步该在帖子详情"去核信息流，
        #    误判成"中间那一下没点中"把整轮作废。
        self._stranger_attempts = 0
        self._stranger_waits = 0
        self._stranger_task: Optional[str] = None
        self._stranger_step = 0
        #: 已经为哪一步回退过一次（同一步只准回退一次，否则就是死循环）。
        self._stranger_rewound_for: Optional[int] = None
        #: 「刚从陌生页退回来」这件事的一次性日志文案（由 Runner 取走并打进日志）。
        #: 为什么不在状态机里直接打：状态机是**纯决策**，不认识 Runtime。
        #: 为什么不在 ``_on_recovered`` 里塞进 ``last_reason``：下一步的处理函数会
        #: 立刻覆盖它（任务文案），那句话就永远看不见了。
        self._recover_note = ""

    # ---- 观察 ----

    def observe(self, screen: np.ndarray) -> pages.PageJudgement:
        """判当前在哪一页。认不出时**返回 unknown**，不抛（上层据此等待/告警）。

        ⚠️⚠️ **只许委托 ``pages.judge_page`` —— 不许在这里另抄一份判页逻辑。**

        2026-10-08 亲手踩到：这个方法原先自己抄了一遍
        「``observe_pages`` → ``top_page`` → 栈根兜底」，
        于是往 ``judge_page`` 里新加的「图片查看器」判据**生产路径根本走不到** ——
        单独跑 ``test_community_pages.py`` 全绿，真机却照旧认不出查看器、
        照旧卡 150 秒。两份实现的代价就是这样：**测试守住了 A，生产跑的是 B**。

        判据只留一份（与「判据不许静默降级」是同一条道理）。
        ``test_community.py::test_the_machine_and_judge_page_agree_on_every_frame``
        逐帧核两边结论一致，防止再分家。
        """
        return pages.judge_page(screen, self.templates)

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
        # **已点过入口 / 已发下拉刷新、画面还认不出 ⇒ 返回 None（只等）**，
        # 由主循环的「认不出画面 → 等/唤醒」通道处理，够久才超时。
        # ⚠️ 只放真的**在转场**的那几档（``_SETTLING_STATES``）：竖屏段别的状态认不出
        #    仍然是硬错误 —— 那时页面早该在了，认不出就是真出问题了，
        #    不该拿「可能是加载中」当借口。
        if self.state in _SETTLING_STATES and page.name == "unknown":
            self.last_reason = {
                CommunityState.ENTERING: "已转成竖屏但社区页面还没加载出来（转场中），只等不判失败",
                CommunityState.REFRESHING: "已发出下拉刷新、H5 还没画出来，只等不判失败",
                CommunityState.IMAGE_VIEWER: "已按返回键关图片查看器、H5 还没画回来，只等不判失败",
            }.get(self.state, "转场中，只等不判失败")
            return None
        # 认不出这一页 ⇒ **不再原地干等到超时**，走逃生门（见 ``STRANGER_RECOVER_STEPS``）。
        if page.name == "unknown":
            return self._on_stranger_page(page)
        if self.state is CommunityState.RECOVERING:
            self._on_recovered(page)
        handler = {
            "network_error": self._on_network_error,
            "image_viewer": self._on_image_viewer,
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
            # ⚠️ 走到这里说明**判据认得这一页、但状态机没给它接线**（``ANCHORS`` 里加了
            # 一页却忘了在 ``handler`` 表里加处理函数）。这是**接线 bug**，不是"认不出"——
            # 真正的"认不出"（``unknown``）在上面就被 ``_on_stranger_page`` 接走了。
            self.last_reason = f"「{page.label}」这一页有判据但状态机没接线"
            raise RuntimeError(
                f"社区页面「{page.name}」（{page.label}）有判据、判出来了，"
                "但 next_action 的 handler 表里没有它：新加一页时漏了接线"
            )
        return handler(screen, page)

    # ---- 陌生页逃生门 ----

    def _stranger_report(self, page) -> str:
        """陌生页的诊断文案：**最像的三页 + 真实分数**。

        ⚠️ 这是整套修复里最便宜、也最重要的一条：2026-10-18 之前，这里写的是
        ``最高分 {page.confidence:.4f}``，而 ``unknown`` 的 ``confidence`` 是
        ``PageJudgement("unknown", 0.0, ...)`` 里**写死的 0**。于是 11 天 15 次失败，
        日志里全是同一行 ``最高分 0.0000；已知观察=[]`` —— 事后连"差多少"都看不见。
        现在把 ``page.scores``（全部锚点的真实分）里最靠前的三页写出来。
        """
        if not page.scores:
            return "最像的三页=无（连一个锚点都没算出分）"
        tops = "、".join(item.describe() for item in page.scores[:3])
        return f"最像的三页={tops}"

    def _on_stranger_page(self, page) -> Optional[CommunityAction]:
        """判页认不出 ⇒ **先退出去**，而不是原地等到超时。

        见 ``STRANGER_RECOVER_STEPS``（为什么是返回键、为什么必须有 3 级、
        为什么"按一次判一次"）。这里的职责只有三件：

        1. 第一次进来时记住「当时在跑哪条任务的第几步」（逃生成功后要退回去重做）；
        2. 每级动作之间**等够帧数再判**（排除"转场画到一半"）；
        3. 阶梯用尽 ⇒ 抛错收手，走原有的失败路径（不无限按）。
        """
        self.state = CommunityState.RECOVERING
        report = self._stranger_report(page)
        if self._stranger_attempts == 0 and self._stranger_waits == 0:
            # 只记一次：这一趟陌生页是从哪条任务的第几步掉进去的。
            self._stranger_task = self.active_task
            self._stranger_step = self.task_step
        total = len(STRANGER_RECOVER_STEPS)
        if self._stranger_waits < STRANGER_WAIT_FRAMES:
            self._stranger_waits += 1
            self.last_reason = (
                f"陌生页（{report}）：先等 {self._stranger_waits}/{STRANGER_WAIT_FRAMES} 帧，"
                "排除「转场画到一半」再动手"
            )
            return None
        if self._stranger_attempts >= total:
            self.last_reason = (
                f"陌生页（{report}）：返回键 ×2 与左上角箭头都试过，还没退出这一页"
            )
            raise UnrecognizedCommunityScreen(
                f"社区画面认不出（{report}）；"
                f"已按返回键/箭头共 {total} 次都没能退出这一页，"
                "判定为「退不出去的陌生页」，停止并留诊断"
            )
        step = STRANGER_RECOVER_STEPS[self._stranger_attempts]
        self._stranger_attempts += 1
        self._stranger_waits = 0
        index = f"第 {self._stranger_attempts}/{total} 级"
        if step == "back":
            self.last_reason = (
                f"陌生页（{report}）：{index} —— 按系统返回键，把它退掉回到上一层"
            )
            return CommunityAction(
                "stranger_back",
                STRANGER_BACK_ARROW,
                press_back=True,
                source_page="unknown",
                in_page_evidence="按系统返回键离开这个陌生页（画面结构应发生变化）",
                reason=self.last_reason,
            )
        self.last_reason = (
            f"陌生页（{report}）：{index} —— 系统返回键没推动，改点左上角的返回箭头"
        )
        return CommunityAction(
            "stranger_back_arrow",
            STRANGER_BACK_ARROW,
            source_page="unknown",
            in_page_evidence="点左上角的返回箭头离开这个陌生页（画面结构应发生变化）",
            reason=self.last_reason,
        )

    def _on_recovered(self, page) -> None:
        """从陌生页退回来了（这一帧已经判出了已知页）。

        两件事：
        - **把刚才那一步退回来重做**（``task_step -= 1``）：出手那一帧 ``task_step``
          已经翻过去了，不退回来的话下一帧会拿"下一步该在帖子详情"去核信息流 ⇒
          误判成"中间那一下没点中" ⇒ 整轮任务作废。**同一步只准退一次**，
          否则点歪 + 退回来会变成死循环。
        - 账本清零：下一次遇到的是**新的**陌生页，阶梯从头走。
        """
        rewound = False
        if (
            self._stranger_task is not None
            and self._stranger_task == self.active_task
            and self._stranger_step == self.task_step
            and self.task_step > 0
            and self._stranger_rewound_for != self.task_step - 1
        ):
            self._stranger_rewound_for = self.task_step - 1
            self.task_step -= 1
            self.pending_verify = ""
            self._verify_frames = 0
            rewound = True
        self.last_reason = f"陌生页已经退出来了，回到「{page.label}」" + (
            "；刚才那一步退回来重做（同一个位置不会再点第二次）" if rewound else ""
        )
        self._recover_note = (
            f"陌生页已退出（按返回第 {self._stranger_attempts} 级生效），"
            f"回到「{page.label}」"
            + ("；那一步退回来重做" if rewound else "")
        )
        self._stranger_attempts = 0
        self._stranger_waits = 0
        self._stranger_task = None
        self._stranger_step = 0

    def take_recovered_note(self) -> str:
        """取走「刚从陌生页退回来」的日志文案（取一次就清空）。

        ⚠️ 必须**取一次就清**：主循环每帧会先 ``preview`` 再真跑，不清的话同一句会打两遍。
        （``preview`` 会 ``_snapshot`` / ``_restore``，所以试算那一次留下的文案会被还原掉，
        真正被取走的是真跑那一次 —— 与 ``_pending_swipe_*`` 同一套道理。）
        """
        note = self._recover_note
        self._recover_note = ""
        return note

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
        if self.state is CommunityState.RECOVERING:
            # 逃生门把社区**整个退出去**了（返回键按过头 / 那一页恰好是 H5 的首屏）。
            # 不猜、也不重进（用户 2026-09-26 拍板「回家就是结束」）——
            # 只说清为什么，等状态超时收尾。返回 None 是为了让 10 秒心跳持续吐出这句，
            # 不至于又变成一片空白。
            self.last_reason = (
                "陌生页逃生按返回按过头了：社区已经被退到横屏（网页活动列表）。"
                "这一轮做不下去了，等超时收尾"
            )
            return None
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

        ⚠️ **2026-10-10 又踩了一次同一句话**：``_register_swipe_emission`` 的账本
        （``_pending_swipe_*``）是 10-09 新加的字段，当时**没同步进来**。后果不是
        「记成两次」而是更隐蔽的**「一次也不记」** —— 见 ``_register_swipe_emission``
        的 docstring：主循环每帧先 ``preview`` 再真跑，两次都拿**同一帧**算账，
        真跑那次永远比到「刚刚试算时留下的基线」⇒ 恒判「页面没动」
        ⇒ ``like_reswipes`` / ``feed_icon_reswipes`` 永远停在 0
        ⇒ 两条「滑了 N 屏就收手」的闸门**同时失效**（10-10 实跑就是这么炸的：
        日志里全是「仍在等第 0 屏生效」，一次「第 2/3 次」都没有）。
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
            self._network_refreshes,
            self._confirmed_page,
            self.signin_clicked,
            self.via_exchange,
            self.active_task,
            self.task_step,
            self.pending_verify,
            self._verify_frames,
            self.like_reswipes,
            self.like_point,
            self.feed_icon_reswipes,
            dict(self.task_attempts),
            set(self.stuck_tasks),
            dict(self._tasks_before),
            # 滑动手势的账本（2026-10-10 补）。三个都要 ——
            # 少了 name ⇒ 真跑那次以为「换了手势」，白记一笔；
            # 少了 tops ⇒ 真跑那次拿试算的基线比自己，恒判没动（本次事故）；
            # 少了 streak ⇒ 试算也把它 +1，30 帧的上限提前一半烧穿。
            self._pending_swipe_name,
            None if self._pending_swipe_tops is None else list(self._pending_swipe_tops),
            self._pending_swipe_streak,
            # 陌生页逃生门的三本账（2026-10-18 补）。漏一个的后果都是"逃生门按帧重复计"：
            # 少 ``_stranger_attempts`` ⇒ 试算也 +1，3 级阶梯在真跑那一帧只剩 2 级；
            # 少 ``_stranger_waits`` ⇒ 试算吃掉确认帧，"先等两帧"直接失效；
            # 少 ``_stranger_step`` ⇒ 逃生成功后回退到错的那一步。
            self._stranger_attempts,
            self._stranger_waits,
            self._stranger_task,
            self._stranger_step,
            self._stranger_rewound_for,
            self._recover_note,
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
            self._network_refreshes,
            self._confirmed_page,
            self.signin_clicked,
            self.via_exchange,
            self.active_task,
            self.task_step,
            self.pending_verify,
            self._verify_frames,
            self.like_reswipes,
            self.like_point,
            self.feed_icon_reswipes,
            self.task_attempts,
            self.stuck_tasks,
            self._tasks_before,
            # 滑动手势的账本（2026-10-10 补，理由见 ``_snapshot``）。
            # ``_pending_swipe_tops`` 直接收下那份拷贝：它只会被**整体重新绑定**，
            # 代码里没有任何一处 mutate 它的元素。
            self._pending_swipe_name,
            self._pending_swipe_tops,
            self._pending_swipe_streak,
            # 陌生页逃生门的三本账（2026-10-18 补，理由见 ``_snapshot``）。
            self._stranger_attempts,
            self._stranger_waits,
            self._stranger_task,
            self._stranger_step,
            self._stranger_rewound_for,
            self._recover_note,
        ) = snapshot

    # ---- 各页的处理 ----

    def _on_network_error(self, screen: np.ndarray, page) -> CommunityAction:
        """H5 死了（整页「网络连接异常，下拉刷新」）⇒ **照它要求的做：下拉刷新**。

        ## 为什么不是「退出去重进」（2026-10-07 用户拍板改掉）

        用户原话：「你就是应该按照他的要求下拉刷新」。理由与真机证据见常量
        ``NETWORK_PULL_START`` 上方那一段 —— 简洁版：① 页面自己写了出路就照它做，
        退出重进的代价是整条入口链重来（90 秒起）且进度要重新对账；
        ② 旧做法在真机上**连点都没点上**（动作被主循环丢掉 + 点的坐标也不是这页的 X）。

        ## 两道闸门（都不许省）

        - **同行**: 同一页连着几帧都报异常 ⇒ 只记**一次**账（按帧记的话计数器几秒就穿）。
        - **跨页**: 一次运行里总共只拉活 ``NETWORK_REFRESH_LIMIT`` 次；
          同一页反复拉活另由主循环那本「同一动作 4 次」的账兜住（动作名固定了，
          记得到它 —— 这正是改掉旧写法顺带修好的一个洞）。

        ⚠️ 发出去之后状态置 ``REFRESHING``：刷新期间 H5 会白屏一会儿，
        ``observe`` 必然判 ``unknown``，那一档必须**只等**（见 ``_SETTLING_STATES``），
        否则每一次正常的刷新都会被判成「认不出画面」。
        """
        if self.state is not CommunityState.REFRESHING:
            self._network_refreshes += 1
        if self._network_refreshes > NETWORK_REFRESH_LIMIT:
            self.state = CommunityState.BLOCKED
            raise RuntimeError(
                f"社区网页这次运行里已经拉了 {self._network_refreshes - 1} 次活，"
                "每次还是「网络连接异常」；H5 起不来了（网络断了 / 活动页维护中），"
                "停止并留诊断"
            )
        self.state = CommunityState.REFRESHING
        return CommunityAction(
            "refresh_community_page",
            NETWORK_PULL_START,
            swipe_end=NETWORK_PULL_END,
            source_page=page.name,
            in_page_evidence="「网络连接异常，下拉刷新」这一页消失（刷新后落回社区页面）",
            reason=(
                "H5 报「网络连接异常，下拉刷新」，照它要求的做：往下拖一屏触发刷新"
                f"（第 {self._network_refreshes}/{NETWORK_REFRESH_LIMIT} 次）"
            ),
        )

    def _on_image_viewer(self, screen: np.ndarray, page) -> CommunityAction:
        """有人把帖子里的图片**点开放大**了 ⇒ 按**返回键**关掉它，接着走。

        ## 为什么值得单独立一档，而不是「认不出就报错」

        这个坑一天咬了三次（2026-10-08 18:58 / 19:10，外加 2026-10-07 20:39 同形）。
        每一次的代价都不只是「这一遍白跑」：人一直卡在查看器里 ⇒ **收尾那步连社区都关不掉**
        （「退出社区」点的是信息流右上角，那一块正被查看器盖着）⇒ 模拟器留在竖屏 ⇒
        回家那步报「画面宽高比与模板基准不一致」。2026-10-08 18:58 那次的日志原文：

            19:00:48 收尾=人还在社区竖屏页面里 动作=先退出社区，等转回横屏再回首页
            19:00:59 收尾=退出社区失败（已忽略） 原因=等待模拟器切成横屏超时（已等 8.0 秒）
            19:01:02 异常收尾=回首页失败 原因=RuntimeError: 画面宽高比与模板基准不一致

        ## 为什么是返回键，而不是点某个控件

        实测那一屏上**没有任何可点的控件**：上下两条纯黑带占 83%（全黑行占比
        0.828~0.837），中间只剩一张帖子里的图，**连返回箭头都没有**。
        能消掉它的只有系统返回键 —— 竖屏段走 ``portrait.back()``，
        与收尾那步用的是同一条通道。

        ## 为什么出口只写 ``in_page_evidence``

        查看器是从哪一页点开的**并不固定**（信息流、帖子详情都可能），关掉之后落回
        哪一页也就不固定 ⇒ 这里**不能**声明 ``target_pages``，交给下一帧重新判页。
        """
        viewer = pages.detect_image_viewer(screen)
        point = (
            viewer.center
            if viewer is not None
            else (screen.shape[1] // 2, screen.shape[0] // 2)
        )
        self.state = CommunityState.IMAGE_VIEWER
        return CommunityAction(
            "dismiss_image_viewer",
            point,
            press_back=True,
            source_page=page.name,
            in_page_evidence="图片查看器消失（退回社区页面）",
            reason="整屏只剩一张帖子里的图（上下都是纯黑），按返回键关掉这个查看器",
        )

    def _on_redeem_done(self, screen: np.ndarray, page) -> CommunityAction:
        """「兑换成功！」弹窗 ⇒ 点「确认」收起。

        ⚠️⚠️ **出口目标曾被写错，代价是整条兑换流程卡死一次再失败**（2026-10-07 真机抓到）。

        原来只声明 ``target_pages=("item_detail",)``。真机实测**收回的落点是兑换中心**：
        「确认」一点，H5 是**一次退回两级**（订单确认 + 商品详情）落到兑换中心，
        不是退回商品详情页。两轮实跑都在同一处转场超时，日志原文：

            ack_redeem_done 原页面=redeem_done 期望页面=item_detail
            当前已确认页面=exchange_center 内部状态=兑换中心

        现场帧 ``runtime_diagnostics/epic7_community/20261007_212358_801234_timeout_transition_ack_redeem_done.png``
        就是兑换中心本体（四张卡都在、行动力已经是「每日限购 2/2」）。

        ⚠️ 为什么「目标写错」会**卡到超时**、而不是点不动就重试 —— 这一点必须写下来，
        否则下次还会照同样的方式踩：主循环对「已发出、还没验收的换页动作」有一条规矩，
        ``confirmed_page`` 既不是来源页也不是目标页时，**把状态机这一帧给出的动作丢掉**
        （``runner_base`` 里 `elif last_transition_action is not None` 那一段）。
        于是状态机明明已经认出「我在兑换中心、下一件该兑强化石」并给出了 ``open_item``，
        那一下**根本没发出去** ⇒ 干等到状态超时（``EXCHANGE`` 60 秒）才报失败。

        ⇒ 目标补上实测落点。两个都留着：兑的是最后一件时同样落回兑换中心，
        而 ``item_detail`` 是这条流程上真实存在的一页，接受它不会让动作变错
        （状态机每帧重新判页，落在哪一页就走哪一页的处理）。
        """
        self.state = CommunityState.REDEEM_DONE
        return CommunityAction(
            "ack_redeem_done",
            REDEEM_CONFIRM,
            source_page=page.name,
            target_pages=("exchange_center", "item_detail"),
            reason="兑换成功弹窗，点「确认」收起（收起后一次退两级，落回兑换中心）",
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
            # 所以先按正常出口退出社区、等转回横屏，到横屏那一帧再抛
            # （抛的时机在 ``_finish_closing``）。
            self.stop_reason = step.reason
            self.state = CommunityState.CLOSING
            return CommunityAction(
                "leave_exchange",
                EXCHANGE_CLOSE,
                source_page=page.name,
                target_pages=("web_activity_list",),
                reason=(
                    f"{step.reason}；点兑换中心右上角 ✕ 退出社区"
                    "（真机实测：这一下关的是**整个社区**，一步回到横屏）"
                ),
            )
        if step.kind == "done":
            # ⚠️ 与 ``_on_feed`` 里那句 ``close_community`` **同形**（``CLOSING`` +
            # 目标 ``web_activity_list``）：两处都是「关掉整个社区」，只是那一颗 ✕
            # 长在信息流右上角、这一颗长在兑换中心右上角。同一种语义就只该有一种写法。
            self.state = CommunityState.CLOSING
            return CommunityAction(
                "leave_exchange",
                EXCHANGE_CLOSE,
                source_page=page.name,
                target_pages=("web_activity_list",),
                reason="兑换清单已跑满，点兑换中心右上角 ✕ 退出社区（一步回横屏）",
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

        ## 循环的骨架（粒度是**一轮**，不是一次）

        ```
        我的任务 --点「去完成」--> 信息流 --一轮里连做 N 次--> (兑换中心 → 获取积分卡)
             ^                    （浏览 3 篇 / 点赞 3 个 / 分享 1 次）          |
             +---------- 回来对账：那一行变成「已完成」了吗？ ------------------+
        ```

        ⚠️ **一轮之内连续做完**，中途不回这一页。原因见 ``TASK_ROUND_TIMES``：
        每次点「去完成」都重新落在信息流顶部，做一次就回来一趟的话，第二遍
        「下滑一次」又滑到同一张卡/同一篇帖 —— 重复浏览，甚至把已点赞的赞取消掉。

        ⚠️ 正常情况**第 1 轮**那一行就翻成「已完成」（3 次都是在这一轮里做完的），
        ``TASK_ATTEMPT_LIMIT`` 留的两轮是纯容错。

        ⚠️ 为什么必须**回来对账**：这三条任务的成败只有页面上那个按钮说得准 ——
        脚本跑完不等于这一行变成「已完成」（2026-10-07 实测：同一套动作，一次涨、一次没涨）。
        「已完成」是唯一权威，脚本只是手段。所以每条任务「跑完一轮 → 回来看这一行」，
        成了才算数，没成再来一轮，连着 ``TASK_ATTEMPT_LIMIT`` **轮**都没成
        就**记一笔、跳过它继续跑别的**（绝不死循环，也绝不无声跳过）。
        ⚠️ 「一轮没跑完就回来了」也要记一笔 —— 不记就是死循环（那一串动作名相邻
        两两都不同，主循环那本「同一动作 4 次」的账记不到它）。

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
            key = self.active_task
            script = TASK_SCRIPT.get(key, ())
            why = ""
            if self.task_step < len(script):
                if self.task_step == 0:
                    # **一步都没走完**就回到了这一页 ⇒ 那一下「去完成」没点中。
                    # 再点一次即可，**不记账** —— 一步都没做就记一轮，会把三次机会
                    # 白白烧在「点击没生效」上（2026-10-07 写这一版时踩过）。
                    # 一直点不动由主循环那本「同一动作 4 次」的账兜住：那几下
                    # **动作名完全一样**（都是 ``start_task``），账记得上。
                    return self._start_task(key, page)
                # ⚠️ 走了一半作废 ⇒ **必须记账**，否则是**死循环**：
                # 「作废 → 回任务页 → 重排 → 又作废」那一串动作名相邻两两都不同
                # （``start_task`` / ``task_xx_1`` / ``back_to_tasks_via_exchange`` /
                # ``goto_tasks_card``）⇒ 主循环那本「同一动作 4 次」的账**记不到它**，
                # 而每次点击都会刷新 ``absolute_started``、绝对超时也兜不住。
                # 项目红线：绝不死循环。
                why = (
                    f"任务「{TASK_LABELS.get(key, key)}」这一轮没跑完就回来了"
                    "（中途那一下没生效）"
                )
            retry = self._reconcile_task(rows, page, why=why)
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
        # ⚠️ 已经决定不再兑换时（``stop_reason`` = 积分不够）**不许再去**：
        # 「我的任务」与「兑换中心」互为历史上一页（两页的 `<` 各指对方），
        # 少了这个条件就是**原地打转**（项目红线：绝不死循环）。
        # 现在正常路径不会退到这一页（兑换中心那边是一步退出社区），
        # 但**这道闸门得留着** —— 状态机可能从任意一帧被重新判页唤醒。
        if not self._redeem_finished() and not self.stop_reason:
            return CommunityAction(
                "goto_exchange",
                TASKS_GOTO_EXCHANGE,
                source_page=page.name,
                target_pages=("exchange_center", "exchange_empty"),
                reason="三条任务都有结论了，走「去兑换」进兑换中心",
            )
        # 任务与兑换都完成 ⇒ 收工（先退回兑换中心，那里右上角的 ✕ 能**一步退出社区**）。
        # ⚠️ 不在这里直接 `_finish()`：收工前必须把社区页关掉、让模拟器转回横屏，
        # 否则收尾「回大厅」那一步拿着横屏通道去取竖屏画面，会直接抛
        # 「render size changed」——任务明明做完了，却报一个看不懂的失败。
        #
        # ⚠️⚠️ 2026-10-09 真机：这一页的 `<` **回不到信息流**，它回到的是**兑换中心**
        # （上一层）。原来这里写 ``("feed_home",)`` ⇒ 转场永远等不到 ⇒ 干等 150 秒超时
        # （实跑日志 19:49:56 点 (35,130)，19:52:31「转场超时 … 当前已确认页面=exchange_center」，
        # 诊断帧就是**兑换中心**那一屏）。所以这里如实写成**回兑换中心**，
        # 到了那边点右上角 ✕ 就**一步退出社区**（见 ``EXCHANGE_CLOSE``）—— 收尾不再绕信息流。
        return CommunityAction(
            "leave_tasks",
            TASKS_BACK,
            source_page=page.name,
            target_pages=("exchange_center",),
            reason="任务与兑换都完成，退回兑换中心，再由那边点 ✕ 退出社区",
        )

    def _start_task(self, key: str, page) -> CommunityAction:
        """点这一行的「去完成」，并把**这一轮**的脚本从头排上。

        ⚠️ 一轮 = 把 ``TASK_ROUND_TIMES`` 次连续做完（见 ``TASK_SCRIPT``）。
        所以这里排上的是整轮的动作序列，中途**不回**「我的任务」。
        """
        self.active_task = key
        self.task_step = 0
        self.like_reswipes = 0
        self.like_point = None
        self.feed_icon_reswipes = 0
        self.pending_verify = ""
        self._verify_frames = 0
        # 新一轮从头排脚本 ⇒ 上一轮的滑动手势账本证据全部作废。
        self._pending_swipe_name = None
        self._pending_swipe_tops = None
        self._pending_swipe_streak = 0
        label = TASK_LABELS.get(key, key)
        return CommunityAction(
            "start_task",
            (TASKS_BUTTON_X, TASK_BUTTON_Y[key]),
            source_page=page.name if page is not None else "tasks_page",
            target_pages=("feed_home",),
            reason=f"任务「{label}」还没完成，点它那行的「去完成」",
        )

    def _reconcile_task(
        self, rows, page, *, why: str = ""
    ) -> Optional[CommunityAction]:
        """回到「我的任务」时给刚跑完的那条任务**对账**（一轮一次）。

        返回 ``None`` 表示这条已经了结（做成了 / 判定今天做不成），调用方接着挑下一条；
        返回一个动作表示「还没做成，原地再来一轮」。

        ``why`` 非空表示这一轮**没跑完就回来了**（中途作废）—— 这种也要记账，
        消息里要如实说清楚，别让它看起来像「跑完一整轮仍然没成」。
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
        self.feed_icon_reswipes = 0
        # 对账 = 这一轮了结 ⇒ 滑动手势的账本证据一并作废（下一轮重新立基线）。
        self._pending_swipe_name = None
        self._pending_swipe_tops = None
        self._pending_swipe_streak = 0
        # ⚠️ 顺序要紧：先清 ``pending_verify`` 再清 ``like_point``。
        # 反过来的话，万一中间有一帧接着跑，``_evidence_seen`` 会因为
        # 「要验变绿、却没点过」而抛 —— 那是接线自检，不该在对账路径上响。
        self.like_point = None
        lead = f"{why}；" if why else ""
        if row is not None and row.is_done:
            self.task_attempts.pop(key, None)
            self.last_reason = f"{lead}任务「{label}」做成了，计数已推进"
            return None
        attempts = self.task_attempts.get(key, 0) + 1
        self.task_attempts[key] = attempts
        if attempts >= TASK_ATTEMPT_LIMIT:
            self.stuck_tasks.add(key)
            self.last_reason = (
                f"{lead}任务「{label}」连着 {attempts} 轮都没让这一行变成「已完成」，"
                "判定今天做不成，跳过它继续跑别的"
            )
            return None
        self.last_reason = (
            f"{lead}任务「{label}」第 {attempts} 轮结束，这一行还没变成「已完成」，"
            "再来一轮"
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
        # ⚠️ 这一段必须在 ``task_step >= len(script)`` **之前**。
        #
        # 出手那一帧 ``task_step`` 就已经 +1 ⇒ 只要这一步正好是脚本最后一步，
        # 写在后面就**永远够不到**：验真一次都没跑过，声明了却没人读。
        # 2026-10-07 实测正是这样（点赞单元的「点 👍」是最后一步）——
        # 点完立刻回「我的任务」，``pending_verify`` 一直挂着没人清。
        #
        # 用 ``script[task_step - 1]`` 取回**刚出手的那一步**，而不是 ``script[task_step]``
        # （那是下一步，它的 evidence 文案会被拿错去等）。
        if self.pending_verify:
            issued = script[self.task_step - 1] if self.task_step else None
            if issued is None:  # pragma: no cover - pending_verify 只由出手那一帧设置
                self.pending_verify = ""
            else:
                verdict = self._await_step_result(screen, page, issued, label)
                if verdict is not None:
                    return verdict
                # ⚠️ 走到这里 = 验收函数返回了 ``None``，它有两种含义，靠
                # ``pending_verify`` 是不是空的来区分（2026-10-07 实跑抓到的 P0）：
                #   非空 ⇒ **还在等**结果，本帧不出手，下一帧再读；
                #   已清空 ⇒ **验收通过** ⇒ **落回下面的主流程**，接着推本轮的下一步。
                #
                # 旧写法让 ``_await_step_result`` 在验收通过时**自己**
                # ``return self._return_to_tasks(...)``，于是「一轮 N 次」永远只做第 1 次 ——
                # 真机实测：点赞一轮只点了 1 个（日志里只有 ``task_like_1``，没有 ``_2``/``_3``），
                # 回到任务页又因 ``task_step < len(script)`` 被判「这一轮没跑完就回来了」，
                # 于是重排一轮、再点 1 个 …… 直到 ``TASK_ATTEMPT_LIMIT`` 轮烧完。
                if self.pending_verify:
                    return None
        if self.task_step >= len(script):
            return self._return_to_tasks(
                screen, page, f"任务「{label}」一轮动作做完，回去核对计数"
            )
        step = script[self.task_step]
        if page.name != step.page:
            return self._return_to_tasks(
                screen,
                page,
                f"任务「{label}」第 {self.task_step + 1} 步该在「{step.page}」动手，"
                f"实际停在「{page.name}」——中间那一下没点中",
            )
        # 「位置运行时现找」那一步找出来的点；别的步保持 ``None``（用脚本里写的）。
        located: Optional[tuple[int, int]] = None
        if step.kind == "tap_like":
            found = pages.locate_card_like(screen, self.templates)
            if found is None:
                # 这一屏**找不到**一颗还没点过的 👍（没卡片 / 卡片全点过了）。
                # ⇒ 往下滑一屏再看（用户拍板的 C 方案原话：「找不到就继续下滑」）。
                #
                # ⚠️ 这里的 ``None`` 是「没找到」，**绝不能**当成「随便点一个」：
                # 那颗 👍 是开关，点错一颗会把别人的赞取消掉。所以只有两条出路 ——
                # 再滑一屏，或者滑满上限作废本遍回对账。
                #
                # ⚠️ 2026-10-09：账本按**执行了**记（``_register_swipe_emission``）——
                # 主循环对同名动作有重试节流，按帧记的话上限几秒就烧穿，
                # 实际却一屏都没滑（与 ``feed_scroll_back_for_exchange`` 同病）。
                counted = self._register_swipe_emission(
                    "task_like_reswipe", pages.feed_band_tops(screen)
                )
                if counted:
                    if self.like_reswipes >= LIKE_RESWIPE_LIMIT:
                        return self._return_to_tasks(
                            screen,
                            page,
                            f"任务「{label}」连滑 {self.like_reswipes} 屏都没找到一颗"
                            "还没点过的 👍，本遍作废",
                        )
                    self.like_reswipes += 1
                    note = f"（第 {self.like_reswipes}/{LIKE_RESWIPE_LIMIT} 次）"
                else:
                    note = (
                        f"（仍在等第 {self.like_reswipes} 屏生效："
                        "上一滑还没执行，主循环同名动作节流中，不重复记账）"
                    )
                return self._step_action(
                    "task_like_reswipe",
                    TaskStep(
                        "swipe",
                        "feed_home",
                        FEED_TASK_SCROLL_START,
                        "",
                        evidence="信息流再滚动一屏，换一屏卡片（本页不变）",
                        end=FEED_TASK_SCROLL_END,
                    ),
                    page,
                    reason=(
                        f"任务「{label}」：这一屏没有还没点过的 👍，"
                        f"往下滑一屏再找{note}"
                    ),
                )
            self.like_reswipes = 0
            self._pending_swipe_name = None
            self._pending_swipe_tops = None
            self._pending_swipe_streak = 0
            self.like_point = found
            located = found
        elif step.kind == "tap_post":
            # 点开一篇帖子：落点**现找**一段「通栏正文段落」。
            #
            # ⚠️ 2026-10-18 之前这里是「白底 + 有字 + 不是图片」，**作者名行也满足**
            # ⇒ 点下去打开的是作者账号主页（一个没登记过的页面）⇒ 认不出 ⇒ 卡死 150 秒。
            # 现在必须**同时通栏**（``pages.FEED_TAP_SPAN_MIN``）：实测只有正文段落通栏，
            # 作者名 / 标题 / 标签都只有一小条。判据见 ``page.feed_tap_band_is_post_body``。
            #
            # ⚠️ 找不到就**收手**（本遍作废回「我的任务」），**绝不退回盲坐标**：
            # 盲坐标正是 2026-10-08 两次实跑点到帖子图片、图片被放大成查看器、
            # 整条路线卡死收场的原因（见 ``FEED_FIRST_POST`` 那段）。
            # 这里没有「再滑一屏再找」的补偿：信息流往下滑只会换一批卡，
            # 一屏里连一段通栏正文都没有说明**页本身不对**，再滑只是白花时间。
            found = pages.locate_feed_post_tap(screen, FEED_FIRST_POST)
            if found is None:
                return self._return_to_tasks(
                    screen,
                    page,
                    f"任务「{label}」在信息流里找不到一段可以安全点开的通栏正文"
                    "（整屏只有图片 / 只有标题 / 空白），不蒙着点，本遍作废",
                )
            located = found
        self.task_step += 1
        if located is not None:
            # 现找出来的点要**把依据写进 reason**：日志里只看到坐标的话，
            # 下次再出问题就分不清「现找算错了」还是「点没生效」。
            if step.kind == "tap_post":
                why = (
                    f"任务「{label}」：现找出来的正文段落带在 {located}"
                    f"（通栏 ≥{pages.FEED_TAP_SPAN_MIN}px + 白底 + 有字 + 不是图片），点它"
                )
            else:
                why = f"任务「{label}」：现找出来的 👍 在 {located}（空心 = 还没点过），点它"
        else:
            why = f"任务「{label}」：{step.note}"
        action = self._step_action(
            f"task_{key}_{self.task_step}",
            step,
            page,
            reason=why,
            # ⚠️ 位置是**现找出来的**，不是脚本里写死的 ⇒ 用 ``point`` 覆盖传下去。
            # 脚本那一步的 ``point`` 是 ``None``（见 ``TaskStep.point``）。
            point=located,
        )
        if step.verify:
            # 记下「等什么」，下一帧先核对再推进 —— 声明归声明，结果要真读到。
            #
            # ⚠️ 这一段**必须在 ``tap_like`` 那条路也走到**。它原先只挂在通用尾巴上，
            # 而点赞分支是**提前 return** 的 ⇒ ``pending_verify`` 一直是空的、
            # 「那颗 👍 变绿了没有」这道验收**一次都没跑过**（2026-10-07 写这一版时
            # 被 ``test_like_step_clicks_the_point_it_just_located`` 当场抓住）。
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
        point: Optional[tuple[int, int]] = None,
    ) -> CommunityAction:
        """把脚本里的一步包装成带出口验收的动作。

        ``point`` 给「位置运行时现找」的那些步用（``TaskStep.point is None``）：
        调用方先把位置找出来，再从这里覆盖进去。⚠️ 两边都没给就**当场抛** ——
        静默退回 ``(0, 0)`` 会在屏幕左上角点一下，那种失败最难查。

        ⚠️ 换页的一步只写 ``next_page``，另外两个是**全局异常态**（签到弹窗可能迟到
        一分多钟、网络异常页会把 H5 弄死）；它们出现时状态机会优先处理，
        所以必须让这一步的验收放行，否则会卡在「页面既不是来源也不是目标」的缝里。
        """
        target = point if point is not None else step.point
        if target is None:
            raise RuntimeError(
                f"任务脚本里第 {self.task_step} 步（{name}）没有点击点："
                "脚本写的是「位置运行时现找」，但调用方没把找出来的点传进来"
            )
        if step.next_page:
            evidence = {
                "target_pages": (step.next_page, "signin_done", "network_error"),
            }
        else:
            evidence = {"in_page_evidence": step.evidence}
        if step.kind == "swipe":
            return CommunityAction(
                name,
                target,
                swipe_end=step.end,
                dwell_seconds=step.dwell_seconds,
                source_page=page.name,
                reason=reason,
                **evidence,
            )
        return CommunityAction(
            name,
            target,
            dwell_seconds=step.dwell_seconds,
            source_page=page.name,
            reason=reason,
            **evidence,
        )

    def _await_step_result(
        self, screen: np.ndarray, page, step: "TaskStep", label: str
    ) -> Optional[CommunityAction]:
        """上一步已经出手，等它的业务结果。

        ⚠️ **绝不出手第二次**：那颗 👍 是开关，第一次其实生效了而我们没读到时
        再点一次会把赞**取消**掉。所以这里只等、不对就作废本遍 —— 交给「我的任务」
        对账去判要不要再来一遍（计数才是权威）。

        返回值只有两种：
        * ``None``  —— 要么「还在等」（``pending_verify`` 仍非空），
          要么「**这一步做成了**」（已清空）。调用方靠 ``pending_verify`` 区分，
          看到清空就**接着推本轮的下一步**。
        * ``CommunityAction`` —— 等超了帧数上限，本遍作废回「我的任务」对账。
        """
        if self._evidence_seen(screen, self.pending_verify):
            self.pending_verify = ""
            self._verify_frames = 0
            self.last_reason = f"任务「{label}」：已看到「{step.evidence}」，这一步做成了"
            # ⚠️ **不要在这里回「我的任务」**（2026-10-07 真机实跑抓到的 P0）：
            # 本轮是把 ``TASK_ROUND_TIMES`` 次拼起来的，验收通过只说明**这一步**做成了。
            # 这里回 ``None``，让 ``_drive_task`` 接着推本轮的下一步；脚本真走完了，
            # 那里自会用 ``task_step >= len(script)`` 回对账。
            return None
        self._verify_frames += 1
        if self._verify_frames >= _VERIFY_FRAME_LIMIT:
            self.pending_verify = ""
            self._verify_frames = 0
            return self._return_to_tasks(
                screen,
                page,
                f"任务「{label}」出手之后等了 {_VERIFY_FRAME_LIMIT} 帧也没看到"
                f"「{step.evidence}」，本遍作废（不重复点，怕点反）",
            )
        self.last_reason = (
            f"任务「{label}」已出手，等看到「{step.evidence}」"
            f"（第 {self._verify_frames}/{_VERIFY_FRAME_LIMIT} 帧）"
        )
        return None

    def _evidence_seen(self, screen: np.ndarray, verify: str) -> bool:
        """``verify`` 这一项在当前帧上成立了吗。

        ⚠️ 只认有实测依据的检查项。没有检查项（``verify=""``）意味着这一步的验收
        靠换页或下一帧重判画面，这里不拦 ⇒ 返回 True。

        ⚠️ 是**实例方法**（不再是 ``staticmethod``）：「变绿了没有」必须读
        **刚点下去的那一颗**（``self.like_point``）。老写法读的是写死的框，
        而那一块是 tab 栏 ⇒ 这道验收恒为「没变」，每遍都会白等 8 帧再作废。
        """
        if verify == _VERIFY_LIKE_ON:
            if self.like_point is None:
                # 没点过任何一颗却要验「变绿了」⇒ 接线断了（只有出手那一帧会设它）。
                # 报错而不是猜：猜「绿了」会把没做的事记成做成了。
                raise RuntimeError(
                    "要验收「👍 变绿了」，但这一轮一次都没点过（like_point 为空）；"
                    "接线断了（见 _drive_task 的 tap_like 分支）"
                )
            return card_like_is_on(screen, self.like_point) is True
        return True

    def _register_swipe_emission(self, name: str, tops: list[int]) -> bool:
        """发出滑动手势前对账：这一滑**要不要在「已滑 N 屏」的账本上记一笔**。

        ⚠️ 只在「上一滑**真的执行了**」时才准记 —— 主循环对**同名动作**有重试节流
        （默认 45 秒内只执行一次），节流窗口里状态机**每一帧**都会重新想滑；
        按帧记账的话，上限几秒就烧穿，实际却一屏都没滑。2026-10-09 13:04 实跑：
        日志里只有 **1** 次「执行滑动」，却报了「往回滚了 3 屏」。

        「真的执行了」的证据是**页面结构动了**：正文带位置表
        （``pages.feed_band_tops``，与生产点帖判据同一套实现）变了。
        滚 800px 会整体换一批正文带；头像/动图那种局部动画不会。

        返回 ``True`` = 记账；``False`` = 上一滑还没生效，只重发、不记账。
        连 ``SWIPE_UNEXECUTED_FRAME_LIMIT`` 帧都没看到页面动 ⇒ 如实报错
        （是「手势没被执行/页面锁滚动」，**不是**「滚了几屏没找到」—— 两回事）。

        ⚠️⚠️ **它碰的三个字段必须留在 ``_snapshot`` / ``_restore`` 里**（2026-10-10，
        上线一小时就被真机抓到）：主循环**每帧先 ``preview`` 再真跑 ``next_action``，
        两次喂的是同一帧画面**（``transactional_runner_base.run``）。preview 会把基线
        设成本帧、再回滚 —— 只要账本**没被回滚**，真跑那次就是拿「刚刚试算时写下的
        基线」跟「同一帧」比，**恒等 ⇒ 恒判「页面没动」**。症状极具误导性：
        日志里全是「上一滑还没执行」和「仍在等第 0 屏生效」，
        而实际上页面滚得好好的（同一段日志里点赞点坐标一直在变、也拿回过四宫格）。
        ⇒ 凡是「跨帧对比」的账本，进了 ``next_action`` 就必须进快照；
        护栏见 ``tests/test_community.py`` 的 ``PreviewKeepsSwipeLedgerTests``。
        """
        if self._pending_swipe_name != name or self._pending_swipe_tops is None:
            # 第一滑（或上一个手势已被别的动作打断）⇒ 记账并立基线。
            self._pending_swipe_name = name
            self._pending_swipe_tops = tops
            self._pending_swipe_streak = 0
            return True
        prev = self._pending_swipe_tops
        # ``strict=False``：长度不等那一支由前面的 ``or`` 短路包住了，走到 ``zip`` 时
        # 两条带子必然等长；显式声明只是别让 zip 静默截断（ruff B905）。
        moved = len(prev) != len(tops) or any(
            abs(a - b) >= SWIPE_MOVE_MIN_PX for a, b in zip(prev, tops, strict=False)
        )
        if moved:
            # 上一滑执行了 ⇒ 记账，拿当前帧当新基线。
            self._pending_swipe_tops = tops
            self._pending_swipe_streak = 0
            return True
        self._pending_swipe_streak += 1
        if self._pending_swipe_streak > SWIPE_UNEXECUTED_FRAME_LIMIT:
            raise RuntimeError(
                f"动作 {name} 连发 {self._pending_swipe_streak} 帧都没看到页面滚动："
                "滑动手势一直没被执行（主循环节流没放开 / 页面锁滚动），"
                "停止并留诊断——这与「滚了几屏没找到目标」是两回事"
            )
        return False

    def _return_to_tasks(self, screen: np.ndarray, page, reason: str) -> CommunityAction:
        """从任意一页把路线带回「我的任务」。

        路径是**信息流 → 兑换中心 →「获取积分卡」→ 我的任务**。⚠️ 底栏那个「我的」
        不是我的任务，是社区个人主页（2026-10-07 实测：点过去得到一张认不出的页面）。

        ⚠️ **2026-10-07 真机实跑加的一道闸门**：``FEED_ICON_EXCHANGE`` 那个点击点
        只在**未滚动的信息流**上成立。而任务做完时信息流多半已经滑过好几屏
        （点赞要下滑找 👍、浏览要点开帖子）⇒ 四宫格早滚出视野，那个坐标底下已经是
        **帖子里的图片**：点下去打开了图片查看器、画面认不出、整条路线卡到超时
        （20:39 实跑现场帧 ``..._timeout_feed.png`` 就是那张「平衡性调整公告」大图）。

        所以先问一句 ``pages.feed_exchange_icon_visible``：看不见就**往回滚**再问一次；
        真滚满 ``FEED_ICON_RESWIPE_LIMIT`` 次、或者**画面连着几次纹丝不动**（滚到顶了）
        还看不见，就报错收手 —— **绝不蒙着点**（那一按的代价是不可逆的：
        图片查看器一旦打开就卡死）。

        ⚠️ **2026-10-09**：「滚了几屏」的账本改按**执行了**记（``_register_swipe_emission``）。
        旧写法按帧记，主循环节流窗口里几秒就烧穿 —— 实跑只滑 1 屏就报「滚了 3 屏」。

        ⚠️⚠️ **2026-10-10 收口（用户拍板「滚到顶为止」）**：一天之内这里修了两处，
        别把它们当成一回事 ——

        ① **账本被自己污染**：``_pending_swipe_*`` 没进 ``_snapshot`` ⇒ 主循环
           「先试算再真跑、两次同一帧」让真跑**恒判「画面没动」** ⇒ 计数永远是 0
           ⇒ 下面那两条闸门**根本没生效过**（症状：日志满屏「上一滑还没执行」，
           而画面明明在滚）。修法与护栏见 ``_snapshot``。
        ② **闸门即使生效也不够宽**：一次滚 800px、上限 3 ⇒ 最多退 2400px，
           而实跑里任务段往下滚过 6 屏（≈4800px）。⇒ 行程加大到 ~1390px、
           上限提到 4（与主循环的 4 次对齐，别让它先炸）；
           并且**不再只靠次数**：加了「滚不动了」这条判据
           （``FEED_ICON_STUCK_FRAMES``）—— 到顶的页面再往下拖就是不动。
        """
        if page.name == "feed_home":
            if not pages.feed_exchange_icon_visible(screen, self.templates):
                counted = self._register_swipe_emission(
                    "feed_scroll_back_for_exchange", pages.feed_band_tops(screen)
                )
                if counted:
                    if self.feed_icon_reswipes >= FEED_ICON_RESWIPE_LIMIT:
                        raise CommunityDataMissing(
                            f"往回滚了 {self.feed_icon_reswipes} 次，信息流顶部还是看不见"
                            "「兑换」图标，没法经兑换中心回我的任务（入口可能搬家了）"
                        )
                    self.feed_icon_reswipes += 1
                    note = f"（第 {self.feed_icon_reswipes}/{FEED_ICON_RESWIPE_LIMIT} 次）"
                else:
                    # 走到这里 = 上一次滑动**没有让画面动**（真跑那一遍；
                    # 试算造成的假「没动」已在 2026-10-10 由 ``_snapshot`` 修掉）。
                    #
                    # ⚠️ 必须把「滚到顶了」和「手势根本没执行」分开（两者画面都不动，
                    # 但一个是正常到底、一个是通道/节流故障）：
                    #   * ``feed_icon_reswipes >= 2`` = **画面确实滚动过**
                    #     （第 1 笔是立基线、不算「动过」，所以 2 才是「至少动过一次」）
                    #     ⇒ 手势是好的，现在不动只能是**到底了**；
                    #   * 一直只停在 1 ⇒ 从头到尾没动过 ⇒ 不在这里报，
                    #     交给 ``_register_swipe_emission`` 的 30 帧上限如实报
                    #     「滑动手势一直没被执行」。
                    if (
                        self.feed_icon_reswipes >= 2
                        and self._pending_swipe_streak >= FEED_ICON_STUCK_FRAMES
                    ):
                        raise CommunityDataMissing(
                            f"往回滚了 {self.feed_icon_reswipes} 次，画面上又连着 "
                            f"{self._pending_swipe_streak} 次纹丝不动（已经滚到顶了），"
                            "信息流顶部还是看不见「兑换」图标，没法经兑换中心回我的任务"
                            "（入口可能搬家了）"
                        )
                    note = (
                        f"（第 {self.feed_icon_reswipes} 次滑出去之后画面还没落定，"
                        "再滚一次看）"
                    )
                return CommunityAction(
                    "feed_scroll_back_for_exchange",
                    FEED_ICON_SCROLL_START,
                    swipe_end=FEED_ICON_SCROLL_END,
                    source_page=page.name,
                    in_page_evidence="信息流往回滚一屏，把顶部四宫格露出来（本页不变）",
                    reason=(
                        f"{reason}；这一屏看不见「兑换」图标（八成滚下去了），"
                        f"先往回滚一屏再问{note}"
                    ),
                )
            self.feed_icon_reswipes = 0
            self._pending_swipe_name = None
            self._pending_swipe_tops = None
            self._pending_swipe_streak = 0
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
    "三条每日任务的执行脚本里，`FEED_FIRST_POST`（信息流第一张帖子卡）与"
    "`FEED_TASK_SCROLL_*`（滑一次的位移量）只在 2026-10-07 单日样本上验证过；"
    "点赞那颗 👍 已改成模板定位（`card_like_off`，离线分离度 1.0000 vs 0.43、"
    "全库零误报），但**还没在真机上跑完一整轮**；行动力每日限购 2、"
    "但只有第一次兑换的真机帧，第二次的「兑换成功 → 回商品详情 → 再兑一次」链路没有样本"
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
        # 下拉刷新之后 H5 要重新拉数据、重画首帧；给足一屏时间。
        # ⚠️ 这一档只在「拉完刷新之后一帧都没动作」时才用得上；正常情况下状态机会
        # 继续发 ``refresh_community_page``（同一页还在报异常），那本账由主循环记。
        CommunityState.REFRESHING: 60,
        CommunityState.BLOCKED: 45,
        # 陌生页逃生门：3 级 × (2 帧确认 + 1 次动作) ≈ 15 秒就该走完。
        # 给 60 秒是给"返回键按下去 H5 过一会儿才响应"留余量；正常 3 秒内就恢复了。
        # ⚠️ 这一档同时也是"按返回按过头、社区被退掉"那一档的上限（见 ``_on_landscape``）。
        CommunityState.RECOVERING: 60,
        # 图片查看器：返回键按下去，那一屏要么没了、要么还在（实测 H5 立刻响应）。
        # 45 秒纯属「别让状态机卡死」的上限 —— 正常一两帧就换页了。
        # ⚠️ 真要点满 45 秒，说明返回键没生效（例如点开的其实是游戏原生全屏预览、
        # 不吃 keyevent 4），那时日志里会留下「已按返回键关图片查看器」而画面不动。
        CommunityState.IMAGE_VIEWER: 45,
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
            # 下拉刷新的效果看得很快：手势一松，要么页面消失、要么还是那一页。
            # 按默认 45 秒等，白白把「拉活→再看一眼」的循环拖成一分钟一次。
            "refresh_community_page",
            # 关图片查看器同理：返回键按下去，那一屏要么没了、要么还在。
            "dismiss_image_viewer",
            # 陌生页逃生门的两级动作：返回键按下去，要么退回上一层、要么没动。
            # 按默认 45 秒等，一轮逃生要拖成两分多钟，而它总共只有 3 级。
            "stranger_back",
            "stranger_back_arrow",
        }
    )
    _QUICK_RETRY_SECONDS = 8.0
    # ⚠️ 2026-10-09：滑动手势（`task_like_reswipe` / `feed_scroll_back_for_exchange`）
    # 的重试窗口给 **3 秒**。默认 45 秒是给「换页点击」定的；手势的效果**下一帧**
    # 就看得见（页面滚没滚），45 秒纯是把「滚回去找入口」拖成一分钟一屏 ——
    # 2026-10-09 13:04 实跑里 3 屏预算只来得及执行 1 屏，就是被它卡住的。
    # 「账记得诚实」由状态机的「页面动了才算数」（``_register_swipe_emission``）保证，
    # 不靠这个窗口；这里只管节奏。3 秒 ≥ 两帧竖屏采集的间隔，不会连着帧连滑。
    _SWIPE_RETRY_SECONDS = 3.0
    _SWIPE_ACTIONS = frozenset({"task_like_reswipe", "feed_scroll_back_for_exchange"})
    #: 盖住整屏、**可能出现在任何一步之后**的浮层页。
    #:
    #: 判据是「这一页在 ``next_action`` 里**有收场动作**」——三个都有：
    #: ``image_viewer`` 按返回键、``network_error`` 下拉刷新、``signin_done`` 点「关闭」。
    #: 它们一旦出现，上一动作的出口验收就此作废（见 ``_transition_completed``）。
    #:
    #: ⚠️ 往里加人之前先问「它那一页真能推得动吗」：放行一个推不动的页等于把死锁
    #: 从主循环搬到状态机里，更难查。``test_community.py`` 有一条用例拿 ``handler``
    #: 那张表逐个核。
    _GLOBAL_OVERLAY_PAGES = frozenset({"image_viewer", "network_error", "signin_done"})
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
        if action_name in self._SWIPE_ACTIONS:
            return self._SWIPE_RETRY_SECONDS
        if action_name in self._QUICK_ACTIONS or action_name.startswith("task_"):
            return self._QUICK_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _perform_action(self, action: Any) -> None:
        """按 ``action`` 的三面旗子分派：**返回键 / 滑动 / 点击**。

        ⚠️ 为什么必须覆写：主循环（``runner_base``）只会 ``runtime.click``，而社区
        那两条脚本里的「往下滑一次」是**状态机产出的动作**、没法像商店刷新那样
        自己绕开主循环去调 ``swipe``。不换发的话，滑动会变成「在起点点一下」——
        点在信息流中部会**点开一张帖子**，于是下一步要求的页对不上、本遍作废，
        一天三次机会就这么白烧掉（2026-10-07 实测）。

        ## 三条路各治什么

        - ``press_back`` —— **图片查看器**。那一屏上下两条全黑带占 83%、中间只有一张
          帖子里的图、**连返回箭头都没有**，能消掉它的只有系统返回键。不换发的话
          会去点 ``point``（图片正中），运气好顺手关掉、运气不好**再放大一层**，
          而这一屏的判据已经命中 ⇒ 状态机会一直等一个不会发生的变化。
          判定**放在最前**：``swipe_end`` 与 ``point`` 都不该在这次里生效。
        - ``swipe_end`` —— 信息流里上下滑。
        - 其余 —— 照旧点击（``super()._perform_action``）。
        """
        if getattr(action, "press_back", False):
            # 走 ``runtime.back`` 而不是 ``_back``：前者会 ``_stop_if_requested()``
            # 并把这一下写进日志（「安全停止」要能在等待期间生效），后者是裸通道。
            # 竖屏段由 ``_install_dual_channel`` 打的补丁自动转成 ``portrait.back()``
            # （keyevent 4），与收尾那步用的是同一条通道。
            #
            # ⚠️ 这里 **return**：``press_back`` 与「滑动 + 停留」是互斥的两条路。
            # 不断开的话，后面 ``else`` 分支会补一次点击（点在图片正中），
            # 等于刚按完返回又去点那一屏 —— 正好把要关的东西再打开。
            self.runtime.back(action.name)
            return
        end = getattr(action, "swipe_end", ())
        if end:
            self.runtime.swipe(
                action.point,
                end,
                FEED_TASK_SCROLL_MS,
                action.name,
            )
        else:
            super()._perform_action(action)
        dwell = getattr(action, "dwell_seconds", 0.0)
        if dwell > 0:
            # 「浏览」那一篇：滑完要**停一会儿**，游戏才认这次浏览（用户口径 5~10 秒）。
            # 睡眠放在发完动作之后；状态机只声明意图（``TaskStep.dwell_seconds``），
            # 睡多久归这一层管 —— 与 ``swipe_end`` 同一条分工。
            self.runtime.log(
                f"模式={self._MODE_LABEL} 动作={action.name} 停留={dwell:.0f}秒 "
                "处理=浏览帖子要在详情里停住一会儿才算一次"
            )
            self.sleep(dwell)

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

        为什么必须在这里拨：这几下点击是**唯一**会改变屏幕方向的动作，而方向一变，
        取图/点击的坐标系就整个换了（横屏 1982x1132 vs 竖屏 1080x1920）。
        拨晚了会拿错坐标系点一下，拨早了会在转屏动画中途取图。

        ⚠️ 2026-10-09 补 ``leave_exchange``：兑换中心右上角那颗 ✕ 真机实测**关的是
        整个社区**（点完 3 秒内窗口就回 1920x1080）。漏了它，通道记录会一直停在
        竖屏 —— 19:58 那次实跑就是这么白等 20 秒「等待切换为竖屏」的：
        窗口明明已经横屏，代码却拿竖屏链路去取图。
        """
        if self._switch is None:
            return
        name = getattr(action, "name", "")
        if name == "enter_community":
            self._switch.expect("portrait")
        elif name in ("close_community", "logout_community", "leave_exchange"):
            self._switch.expect("landscape")

    def _transition_completed(
        self, previous_action: Any, current_action: Any, confirmed_page: str
    ) -> bool:
        """把**盖住整屏的全局浮层**当成一个**转场终止**处理（2026-10-07 立，10-08 扩）。

        ## 为什么必须在这里动手

        主循环对「已经发出、还没验收的换页动作」有一条规矩：``confirmed_page``
        **既不是来源页也不是目标页**时，就把状态机这一帧给出的**新动作丢掉**
        （``runner_base`` 里 `elif last_transition_action is not None` 那一段，
        注释写的是「有目标契约的动作遇到短暂未知帧时保留同一重试账本」）。

        平时它是对的（转场动画中途认出的杂乱页面不该当真），但这几层浮层出现时它是错的：
        等着的那个目标**永远不会到**，而被丢掉的正是唯一能收场的动作。

        ## 两次实跑各自留下的证据

        ① **``network_error``（2026-10-07 20:31）**：点完 ``goto_tasks_via_exchange``
        网页就死了，状态机连记 3 次「网络异常」，日志里**一条
        ``执行点击 动作=logout_community`` 都没有** —— 补救动作全被丢掉，最后只能干等到
        状态超时（现场帧 ``20261007_203326_943958_timeout_web_entry.png``）。
        改成下拉刷新之后同样如此：不在这里放行，刷新动作一样发不出去。

        ② **``image_viewer``（2026-10-08 18:58 / 19:10）**：任务「浏览帖子」那一指点在
        帖子的图片上 ⇒ 图被放大成全屏查看器 ⇒ 状态机认出来了、也给出了
        ``dismiss_image_viewer``（按返回键），但那一下同样被丢掉 ⇒ 干等 150 秒
        （``FEED`` 那档）⇒ 收尾时人还卡在查看器里，**连社区都关不掉**
        （``RuntimeError: 画面宽高比与模板基准不一致``）。
        日志形状：``结论待确认=UnrecognizedCommunityScreen`` 之后再无一条日志。

        ⇒ 浮层一出现就宣布「这个转场到此为止」，把账清掉
        （基类那一支会顺手 ``last_transition_action = None``），让收场动作真的发得出去。
        代价是日志里会多一行 `完成=<动作> 目标页面=<浮层>` —— 那**不是**「本步做成了」，
        所以 ``_transition_success_detail`` 补一句说明，别被它误导。

        ⚠️ 名单在 ``_GLOBAL_OVERLAY_PAGES``。往里加人之前先确认那一页**真能推得动**
        （``next_action`` 里有收场动作），否则只是把死锁从主循环搬到状态机里。
        """
        if confirmed_page in self._GLOBAL_OVERLAY_PAGES:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 转场作废={previous_action.name} "
                f"原因=被「{confirmed_page}」这层盖住了落点，先收掉它再重来"
            )
            return True
        # ⚠️ 2026-10-18：**陌生页也要在这里放行**。
        # 场景：``task_browse_5``（点了「点开一篇帖子」，期望 post_detail）点歪进了作者主页
        # ⇒ 判页 ``unknown`` ⇒ 状态机给出 ``stranger_back``。此时 ``confirmed_page``
        # 既不是来源页也不是目标页，基类会把**这一下逃生动词直接丢掉** ——
        # 正是 ``network_error`` / ``image_viewer`` 踩过的同一个坑（见本方法上面的两段）。
        # 丢掉之后就是干等 150 秒。
        if getattr(current_action, "name", "") in STRANGER_ACTIONS:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 转场作废={previous_action.name} "
                "原因=落点上是个认不出的陌生页，先按返回把它退掉再重来"
            )
            return True
        return super()._transition_completed(
            previous_action, current_action, confirmed_page
        )

    def _transition_success_detail(
        self, previous_action: Any, current_action: Any
    ) -> str:
        if getattr(current_action, "source_page", "") == "network_error":
            return "（实为 H5 报「网络连接异常」：这个转场作废，改走下加拉活）"
        if getattr(current_action, "source_page", "") == "image_viewer":
            return "（实为帖子图片被放大成查看器：这个转场作废，改走按返回键）"
        if getattr(current_action, "name", "") in STRANGER_ACTIONS:
            return "（实为落到了一个认不出的陌生页：这个转场作废，改走返回键退出它）"
        return super()._transition_success_detail(previous_action, current_action)

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
        # ⚠️ 2026-10-18：**恢复成功要有自己的一行日志**。
        # 状态机是纯决策（不认识 Runtime），它只能把这件事写进 ``last_reason``，
        # 而下一步的处理函数会立刻把 ``last_reason`` 覆盖成「任务第 N 步」之类的文案
        # ⇒ "陌生页退出来了"这句话**永远进不了日志**。
        # 于是走到这里由 Runner 取一次、记一次。
        # ⚠️ ``getattr`` 是为了离线桩（有些用例拿一个只实现 ``next_action`` 的假机器跑收尾流程）。
        taker = getattr(self.machine, "take_recovered_note", None)
        recovered = taker() if callable(taker) else ""
        if recovered:
            self.runtime.log(f"模式={self._MODE_LABEL} 恢复={recovered}")
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

        ⚠️⚠️ **本路线的终点契约 = 大厅（首页）**（用户 2026-10-09 明确补充：
        「这条路线它的终点有点特殊，它一定要回到首页，因为不然的话，它很多按键
        都没有掉了」）⇒ **「退出社区」只是中途，不是终点**：社区（尤其 H5 网页
        活动列表）上没有大厅那套按钮，停在那儿下一个任务接不上。

        完整链路四棒，缺一棒都到不了终点：

            状态机 DONE → 基类主循环 ``_close_out()`` → 本方法（退社区 + 等转回横屏）
                        → ``super()._close_out()`` → ``_finish_home()``
                        → ``home_return()`` → 大厅

        最后一棒是**通用回家流程**（横屏通道）：从网页活动列表按两次 ESC
        （``web_activity_list`` → ``activity_web_promo`` → 大厅）。2026-10-09 20:01
        那次实跑日志就是这么到家的 —— 20:01:40 / 20:01:48 两次「按ESC 点击验收=生效」，
        20:01:57「页面=大厅 状态=已确认」，紧接着「异常收尾=已回到首页」。

        ⚠️ 为什么需要本方法：**异常路径**（缺数据 / 认不出 / 判据 blocked）也会走到
        这里，而那时人可能还停在社区的竖屏页面里。基类的收尾要拿横屏通道去取图
        （``return_home``），在竖屏下会直接抛「render size changed」——
        于是「异常也回家」这条规矩在这条路线上**实际做不到**，模拟器还会被留在竖屏。

        正常路径下本方法**只做中途那一棒**（状态机会在横屏那一帧才收工），
        终点仍由 ``super()._close_out()`` 那一棒决定 —— 见上面那张链路图。

        契约与基类一致：**绝不抛异常** —— 关不掉就记一笔，让基类那步照常失败并留下原因。
        """
        if self._finish_home is None and not self.runtime.dry_run:
            # ⚠️ 基类 ``_close_out`` 在钩子缺失时是**静默 return**（一行日志都没有）
            # ⇒「终点保证是首页」这条契约会**悄悄失效**，日志上看不出任何异常。
            # 本路线既然把终点写进了契约（见 docstring），就在这里出声。
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=没有可用的「回首页」钩子 "
                "影响=退出社区后只会停在网页活动列表（横屏），到不了大厅 "
                "原因=钩子没装（只挂在能导航且非干跑的运行上）"
            )
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

        ⚠️⚠️ 2026-10-09 补：**确认已经横屏之后，通道记录也要跟着拨回横屏**
        （``demote_to_landscape``）。旧版只等方向、不动记录 ⇒ 记录停在
        ``PENDING_PORTRAIT``（异常收尾时没人点过「退出社区」，没人拨它）⇒
        紧接着基类回首页取图，``use_portrait()`` 在 ``PENDING_PORTRAIT`` 这一支上
        「还没转成竖屏也返回 True」（它本意是把等待委托给竖屏通道），
        于是先白等 20 秒竖屏超时、再由 ``_fallback_to_landscape`` 退回横屏。
        日志形态：13:07:54「收尾=已退出社区且方向已转回横屏」，13:08:18
        「竖屏通道 方向=等待切换为竖屏 … 超时」—— 中间那 24 秒全耗在
        等一次**不可能发生**的转屏上。**方向对了，记录没跟上。**
        """
        switch = self._switch
        if switch is None or self.runtime.dry_run:
            return
        try:
            if not switch.portrait.is_portrait():
                # 已经是横屏 ⇒ 只把通道记录拨回来（见上面那段 2026-10-09 的说明）。
                switch.demote_to_landscape()
                return
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=人还在社区竖屏页面里 "
                "动作=先退出社区，等转回横屏再回首页"
            )
            # 竖屏段对返回键的响应不一致（任务页按了没反应），所以先点右上角的 ⊗，
            # 再补两下返回键；每一步都看一眼方向，转过去了就收手。
            #
            # ⚠️⚠️ 2026-10-09：社区里那几颗 ⊗ **位置各不相同**（信息流 (937,92)、
            # 兑换中心 (989,123)、H5 死掉那屏 (1000,78)，见 ``EXCHANGE_CLOSE`` 上方那张表），
            # 所以旧写法「只点信息流那一颗」在别的页面上**等于点空** ⇒ 收尾关不掉 ⇒
            # 模拟器留在竖屏 ⇒ 紧接着基类回家取图报「画面宽高比与模板基准不一致」
            # （10-07 / 10-08 连撞多次的就是这条链）。
            #
            # 这里**挨个试**，谁把窗口转回横屏就算谁赢。这是**收尾的扫地出门**，
            # 与主流程的纪律相反 —— 主流程必须按判页挑对的那一颗（三颗外径 33/44/48
            # 互不相等，不是同一颗挪了位置），**不许**这样试。
            portrait = switch.portrait
            for index, point in enumerate(
                (FEED_CLOSE, EXCHANGE_CLOSE, NETWORK_PAGE_CLOSE), 1
            ):
                portrait.click(point)
                try:
                    portrait.wait_for_landscape(timeout=_EXIT_CLOSE_ATTEMPT_SECONDS)
                    break
                except OrientationError as error:
                    if index == len(_EXIT_CLOSE_POINTS):
                        raise
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 收尾=第 {index}/"
                        f"{len(_EXIT_CLOSE_POINTS)} 颗 ⊗ {point} 没关掉这一屏，"
                        f"换下一颗 原因={error}"
                    )
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
        switch.demote_to_landscape()
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
