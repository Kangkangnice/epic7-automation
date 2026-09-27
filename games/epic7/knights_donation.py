"""骑士团「捐赠」一次性路线（每天跑一次）。

## 业务闭环（用户 2026-09-24 口述，实机走查确认）

```
骑士团主页
  └ 左侧「骑士团活动」图标 → **直接点进去**（有没有红点都进）
骑士团活动（左栏三个页签：资源支援 / 团员商店 / 每周任务 —— **只做 1 和 3**）
  ├ 资源支援页
  │   ├ 右上「请求支援」→ 弹窗选「下级精灵之花」→ 底部「请求支援」 （**每天只能请求一次**）
  │   └ 列表里每行右侧的绿色「支援1个」依次点完：
  │       ├ 有的行直接弹「获得奖励（30，今日支援上限 x/200）」→ 关掉再找下一行
  │       └ 有的行**先**弹「支援资源 / 确定要支援以下的资源吗?」确认框 → 点它里面的「支援1个」
  └ 每周任务页
      ├ 骑士团点数进度条上可领的档位（图标左上角带亮点）
      └ 每行右侧的绿色「领取」
```

## 「这一格能不能支援」有两道判据：**先看数字，再看结果**

### 一、点之前（前置判据，2026-09-25 补）：读「持有 vs 需求」

材料不够的那一格，绿色按钮**不会变灰**，点下去什么都不发生。2026-09-25 实跑因此出了事故：

- 程序点完「没看到任何变化」⇒ 当成「没点到」⇒ 对**同一格**连点 4 次（每次隔 8 秒）；
- 第 4 次后它判定「这个按钮坏了」，`停止=动作[support-one]连续 4 次未生效`，
  **整条路线提前收工**（后面的每周任务领奖也没做）。

而同一帧里其实还有另一个能支援的绿按钮 —— 只是轮不到它。

路线里本来就有「吃不下就换下一格」的跳过表，但它**从来没生效过**：主循环的转场重试
（``runner_base.py`` 第 539~562 行）会把状态机刚挑好的那一行**顶替回旧坐标**再点一次
（`_source_observation_matches` 对没有该字段的动作恒真）。所以正确的做法是
**点之前就知道**：读每行的「持有：N」与按钮上的「支援 M 个」，``N < M`` 就跳过这一格、
连点都不点。判据本体、字模来源与覆盖范围见 ``knights_support_digits.py``。

⚠️ **认不出就退回去点**：只要有一边读不出（数字不在字模里、区域没框到），
``RowNumbers.verdict`` 就返回 ``None``，这里**照旧去点** —— 也就是回到下面那道兜底判据。
读不出只会「帮不上忙」，不会比现在更坏。

### 二、点之后（兜底判据）：有没有弹「获得奖励」

实跑第一次就卡在这里：点列表里的「支援1个」之后不是马上支援，**先弹了一个确认框**
（我采图那天没遇到，所以第一版不认识它、整条路线中止）。更关键的是第二次实测：
团员要的材料我**持有 0** 时，确认框里点「支援1个」**什么都不发生** —— 行不消失、
「今日支援上限」也不涨（对照实验：换成持有充足的那一行，点完立刻弹「获得奖励」、
上限从 30/200 变成 60/200，该行按钮变成灰勾）。

#### ⚠️ 游戏**会**提示「材料不足」，但那行小字仍然不做判据（2026-09-24 确认）

用户原话：材料为零时点完「**下面会有个小字说材料不足，但很快，然后就没了**」，
而奖励确实没有任何变化。也就是说游戏确实给了提示，但它是个**一闪而过的浮字**：

- 主循环是**每秒取一帧**、还要**两帧稳定**才肯发动作 ⇒ 这种一闪而过的提示**必然漏检**；
- 更致命的是「没看到」和「没出现」在画面上**分不开** —— 拿它当判据会把「漏检」读成
  「支援成功了」，正是要避免的那类错误。

⇒ 那行小字**只当背景知识**。前置判据用的是**静态**的「持有 / 需求」数字
（它一直在画面上、不会一闪而过）—— 两者能分开，正是 2026-09-25 敢拿数字做判据的原因。

兜底判据是「**有没有看到获得奖励弹窗**」：

- 挑行时记下按钮中心 y 到 ``pending_support_y``；
- 看到「获得奖励」⇒ 作数，清空待结算；
- **回到列表页而没看到奖励** ⇒ 这一行吃不下，把它的 y 记进 ``skipped_rows``，
  下一轮挑**别的**绿按钮；
- ⚠️ 跳过表的键是**绝对 y**，只在「列表没动过」时有效：支援成功（列表重排）与
  下滑（整列位移）都会让旧 y 指到别人头上 ⇒ 这两种情况一发生就**清空**跳过表。

跳过表是**两条来路共用**的：① 前置判据说「材料不足」（这一格没点），
② 点过但没等到「获得奖励」。没有它对①，`find_best_template` 每轮都会挑回同一个按钮；
对②，则会在那行上白转 4 次然后整条路线中止 —— 永远轮不到下面那个真的能支援的人。
所以挑行用的是 ``find_all_templates``（整列找**所有**绿按钮）而不是只找最高分那个。

## 「请求支援」今天已经用过 ⇒ 按钮变灰，别点（2026-09-25 用户实跑撞上）

额度用完时按钮**变灰**，但形状没变 ⇒ ``TM_CCOEFF_NORMED`` 照样命中（灰帧 **0.9846**，
与能点帧 1.0000 只差 0.015）⇒ 照点就白等 ``REQUEST_POPUP`` 的 42 秒转场超时 ×4，
``停止=动作[request-support]连续 4 次未生效``，整条路线提前收工。

**变灰只体现在亮度上**，所以判据是 ``request_button_relative_v``
（按钮区域 V 的 99.9 分位 ÷ **整幅画面** V 的均值）：能点 ≈**2.32**、已灰 ≈**1.20**。
用**相对**亮度而不是绝对阈值，是因为绝对亮度会被页面淡入骗 —— 见
``REQUEST_BUTTON_ALIVE_RATIO`` 的注释（world_boss 2026-09-23 的教训）。

⚠️ 跳过请求**不影响支援别人**：列表里的绿按钮跟这个额度无关，当天第二次运行照样有人
可以支援（用户那次现场就是这样：Alefa / Cattails 两行还是绿的）。
⚠️ 量不出来（区域裁不出 / 整幅全黑）一律**当作还亮着**照旧点 —— 宁可退回今天的行为，
也不要因为量不到就白丢当天唯一一次请求。

## ⚠️ 两个「不能按固定坐标点」的实测事实

1. **支援列表每支援一次就重排**（2026-09-24 实测：``Lo3w`` 被支援后从第 2 行掉到
   第 3 行，``广东瀚鹏`` 升上来）。所以「支援1个」按钮**每轮都要重新认**，
   点击点取模板匹配的中心，不查表。
2. **每周任务的行会随完成情况增删**（领完一行之后它从列表消失、下面补一行上来），
   「领取」按钮同理每轮重新认。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``，本路线是第一条开的）

新路线准入要求每个动作都声明「从哪来 + 到哪去 / 页内验收依据」。逐条对账表：

| 动作 | source_page | 出口验收 |
|---|---|---|
| ``open-activity`` | 骑士团主页 | ``target_pages`` = 资源支援 / 每周任务 / 活动界面兜底（**三个都是合法落点**） |
| ``open-resource-tab`` | 活动界面兜底 | ``target_pages`` = 资源支援 |
| ``request-support`` | 资源支援 | ``target_pages`` = 请求支援弹窗 |
| ``select-flower`` | 请求支援弹窗 | ``in_page_evidence`` = 该格出现金色选中框（``flower_cell_selected`` 命中） |
| ``confirm-request`` | 请求支援弹窗 | ``target_pages`` = 资源支援 / 获得奖励弹窗 |
| ``support-one`` | 资源支援 | ``target_pages`` = 支援资源确认框 / 获得奖励弹窗（**两种落点都真实存在**） |
| ``confirm-support`` | 支援资源确认框 | ``target_pages`` = 获得奖励弹窗（生效）/ 资源支援（**没生效**，由跳过表接手） |
| ``scroll-support`` | 资源支援 | ``in_page_evidence`` = 列表整体上移（按钮行的 y 变小 / 出现新行） |
| ``open-weekly-tab`` | 资源支援 | ``target_pages`` = 每周任务 |
| ``dismiss-reward`` | 获得奖励弹窗 | ``target_pages`` = 资源支援 / 每周任务（取决于从哪来） |
| ``claim-milestone`` | 每周任务 | ``in_page_evidence`` = 该档位角标消失（图标变绿勾） |
| ``claim-task`` | 每周任务 | ``target_pages`` = 获得奖励弹窗 |

⚠️ **``in_page_evidence`` 是真验收、不是装饰**：本状态机**每帧都从画面重新判**，
例：``select-flower`` 的下一帧如果还看到「未选中」的花格子，就说明这一下没生效，
状态机仍会返回 ``select-flower``（按短窗口重试）；看到选中态才返回 ``confirm-request``。
``claim-milestone`` 同理：角标还在就再点，角标没了才往下走。

### 为什么不写 ``target_pages=(本页,)``

``runner_base._transition_completed`` 只要求「已确认页面 ∈ target_pages」。
把本页写进去 ⇒ 点完永远验收通过 ⇒ 分不出「点了没生效」和「点了生效了」。
所以同页动作（``select-flower`` / ``scroll-support`` / ``claim-milestone``）
一律走 ``in_page_evidence``，靠「下一帧画面变了没有」验收。

## ⚠️ 这一条路线**只有负样本是全的**

本路线只用**一处**角标判据：每周任务页那两颗蓝角标（``points_label`` 可领档位 +
「每周任务」页签，正向样本 ``weekly_tasks_claimable.png``）。
骑士团主页那颗橙红角标**不参与任何决策** —— 用户 2026-09-24 更正：有没有红点都要进去
（原先按红点决定进不进，已拿掉）。``guild_home_with_dot.png`` 仍然留着，用途变成
``activity_entry`` 余量最薄的回归依据（红点盖住图标左上角 ⇒ 0.9259）。

**「支援到上限」这一路已经跑到了（2026-09-25 晚实跑，2026-09-26 补齐判据）** ——
⚠️ 原先这里写着「上限一旦到达，列表里的绿色按钮会自己变灰，状态机找不到绿按钮就自然收尾」，
**这条假设是错的**：上限满了之后列表里的绿按钮**照样是绿的**、点下去连提示都不弹
（用户描述的「已经到了资源上限」那行小字在实跑里也没等到）。
现在上限由右上角「今日支援上限 N/200」**整串**判据直接读出来
（``support_limit_full``，命中 ``200/200`` = 满了 ⇒ 一个支援按钮都不点、直接切每周任务）；
判据没读到数字时才退回「连点 4 次推不动」那条老路（见 ``support_closed``）。

**换客户端（PC）或换分辨率时，角标判据与上限判据都要重采正向样本**。
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, NamedTuple, Optional

import numpy as np

from auto_game_unified.core.matcher import (
    Match,
    find_all_templates,
    find_template,
    load_template,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.knights_donation import (
    REFERENCE_SIZE,
    build_knights_donation_evidence,
    find_dot,
    milestone_claim_point,
)
from auto_game_unified.games.epic7.knights_support_digits import (
    RowNumbers,
    load_digit_glyphs,
    read_row_numbers,
)
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class KnightsDonationState(Enum):
    GUILD_HOME = "guild_home"
    ACTIVITY_PANEL = "activity_panel"
    RESOURCE_SUPPORT = "resource_support"
    REQUEST_POPUP = "request_popup"
    SUPPORT_CONFIRM = "support_confirm"
    REWARD_POPUP = "reward_popup"
    WEEKLY_TASKS = "weekly_tasks"
    FINISHED = "finished"


# 日志用画面名
STATE_LABELS = {
    KnightsDonationState.GUILD_HOME: "骑士团主页",
    KnightsDonationState.ACTIVITY_PANEL: "骑士团活动（页签未识别）",
    KnightsDonationState.RESOURCE_SUPPORT: "骑士团活动·资源支援",
    KnightsDonationState.REQUEST_POPUP: "请求支援弹窗",
    KnightsDonationState.SUPPORT_CONFIRM: "支援资源确认框",
    KnightsDonationState.REWARD_POPUP: "获得奖励弹窗",
    KnightsDonationState.WEEKLY_TASKS: "骑士团活动·每周任务",
    KnightsDonationState.FINISHED: "本轮已结束",
}

# evidence 页面键 -> 状态。判定顺序就是这个元组的顺序（弹窗优先）。
_PAGE_STATES = (
    ("knights_donation.reward_popup", KnightsDonationState.REWARD_POPUP),
    ("knights_donation.request_popup", KnightsDonationState.REQUEST_POPUP),
    # 确认框盖在资源支援列表上 ⇒ 必须排在 resource_support 之前，否则会被当成列表页。
    ("knights_donation.support_confirm", KnightsDonationState.SUPPORT_CONFIRM),
    ("knights_donation.resource_support", KnightsDonationState.RESOURCE_SUPPORT),
    ("knights_donation.weekly_tasks", KnightsDonationState.WEEKLY_TASKS),
    ("knights_donation.activity_panel", KnightsDonationState.ACTIVITY_PANEL),
    ("knights_donation.guild_home", KnightsDonationState.GUILD_HOME),
)

# 骑士团主页在**导航链**上的页面名（= `Epic7Navigator.observe().name`）。
# 站在这一页说明已经在骑士团里了，只差「点骑士团活动」一步 —— 从这里接着导航
# 可以省掉一次「进入骑士团」的点击。
KNIGHTS_GUILD_HOME_PAGE = "knights_home"

# 开局接力能落脚的页面。
#
# ⚠️ 另外四处**刻意不接力**，理由分三种：
#   1. ``support_confirm``（支援资源确认框）/ ``request_popup``（请求支援）点下去
#      **不可逆** —— 前者消耗材料、后者花掉当天唯一一次请求额度。接力到那一页
#      等于**助手替你按下不可逆的确认**。``arena`` 的「买票弹窗压住的队伍页」就是这么
#      用 ``no_ticket`` 显式排除的（见 docs/RESUME_COVERAGE.md）。
#   2. ``reward_popup``（获得奖励）虽然可逆，但它的判据 ``reward_title`` **不排他**：
#      2026-09-24 全库 226 张扫描实测，``epic7_hero/reward_popup.png`` 与
#      ``epic7_story/bonus_reward.png`` 都能让它命中 ⇒ 接力过去会在**别的路线的弹窗上**
#      按骑士团弹窗的坐标点一下。要接它得先补排他锚点、重跑扫描。
#   3. ``activity_panel``（活动界面兜底页）没有**正例**：同一次扫描里自家 11 张夹具
#      没有一张判成它（因为它们都能被更具体的页认出来）。判据没在真帧上验证过就不接。
#
# ⚠️ 而弹窗**本来也不需要接力**：返回大厅那一下 Back 会先关掉它（=取消），下一帧
# 人就落在底页上，探针在那一刻就地接管 —— 效果一样，还更安全。
_RESUMABLE_STATES = (
    KnightsDonationState.GUILD_HOME,
    KnightsDonationState.RESOURCE_SUPPORT,
    KnightsDonationState.WEEKLY_TASKS,
)

# 支援列表「一屏放不下」时的下滑手势（实机验证过会产生位移）。
SUPPORT_SWIPE_START = (1036, 900)
SUPPORT_SWIPE_END = (1036, 600)
SUPPORT_SWIPE_DURATION_MS = 400
# 下滑次数上限。列表把「还能支援的人」排在前面（实测：被支援过的人会往下沉），
# 所以正常一次都不用滑；留 2 次只为了兜「一屏真的放不下」。
MAX_SUPPORT_SCROLLS = 2

# 每周任务里「可领档位」的点击点已经由 evidence 模块的实测偏移给出，
# 这里只放关闭「获得奖励」弹窗时的纵向偏移（弹窗任意位置都能关，取标题下方一点）。
REWARD_DISMISS_DY = 120

# 支援列表一屏可能有多个「支援1个」：找全部匹配时的非极大值抑制半径。
# 实测行距约 195、按钮自身 266×70 ⇒ 60 既不会把同一按钮报两次，也不会把相邻行并成一个。
SUPPORT_PEAK_MIN_GAP = 60
# 「已经被判定吃不下的行」的纵向匹配容差：新挑到的按钮中心离它这么近就视为同一行。
SUPPORT_ROW_SKIP_TOLERANCE = 40

# ---- 「请求支援」今天已经用过 ⇒ 按钮变灰（2026-09-25 用户实跑撞上）----
#
# 事故：当天第二次运行时「请求支援」已经用掉了、按钮**变灰**，但——
# ⚠️ **模板分认不出来**：``TM_CCOEFF_NORMED`` 对亮度缩放不敏感，而变灰只是文字亮度变了、
# 字形一模一样 ⇒ 灰帧上模板仍得 **0.9846**（能点帧 1.0000，只差 0.015）。
# 于是程序照点，页面当然不变 ⇒ 每次白等 ``REQUEST_POPUP`` 的 42 秒转场超时 × 4 次
# ⇒ ``停止=动作[request-support]连续 4 次未生效``，整条路线提前收工。
#
# 所以判据只能看**亮度**；而**绝对亮度会被页面淡入骗**（world_boss 2026-09-23 已踩过：
# 绝对阈值 ``V>=90`` 在整屏压暗到 50% 时自己塌掉，把「还有次数」误判成「次数用完」）
# ⇒ 这里用**相对亮度**：按钮区域 V 的 99.9 分位 ÷ **整幅画面** V 的均值。
#
# 实测（``runtime_logs/_probe_request_fade.py``，9 张真帧；并把同一帧乘亮度系数
# 1.0/0.8/0.6/0.5/0.4/0.3 模拟淡入，全程几乎不动）：
# - **能点**（5 张，褐底与深蓝底两种外观）：**2.321 ~ 2.347**
# - **已灰**（4 张，含用户当天实跑帧）：**1.195 ~ 1.215**
# 两侧差 1.9 倍 ⇒ 阈值 1.70，两边各留约 40% 余量。**改这个数前先重跑那个探针。**
#
# ⚠️ 另一条死路（记下来免得再试）：比「能点模板」与「灰模板」谁分高 —— 两者形状相同，
# CCOEFF 把亮度差归一化掉了，分数几乎一样，分不开。
REQUEST_BUTTON_ALIVE_RATIO = 1.70


def request_button_relative_v(
    screen: np.ndarray, region: tuple[int, int, int, int]
) -> float:
    """量「请求支援」按钮**相对整幅画面**的亮度：能点时 ≈2.3（亮白字）、已灰时 ≈1.2。

    用比值而不是绝对亮度：整幅画面被压暗（页面淡入）时两边一起降、比值不变 ——
    与 ``world_boss.weekly_chest_brightness_ratio`` 同一个思路。

    取 V 的 **99.9 分位**而不是均值或最大值：
    - 区域**均值**分不开（已灰那几张的底板反而更亮：0.597 vs 0.524，方向是反的）；
    - **最大值**是单像素，容易被一个噪点顶起来；
    - 99.9 分位落在「亮白文字」那一小撮上（约 30 个像素），既稳又有信号。

    V 直接用 ``max(R,G,B)`` 算（HSV 的定义，实测与 ``cv2.cvtColor(..., HSV)[:, :, 2]``
    **逐像素相同**）：这里只要亮度，不值得为它把整幅画面转一遍三通道 HSV。
    """
    scale_x = screen.shape[1] / REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / REFERENCE_SIZE[1]
    x, y, width, height = region
    patch = screen[
        round(y * scale_y) : round(y * scale_y) + round(height * scale_y),
        round(x * scale_x) : round(x * scale_x) + round(width * scale_x),
    ]
    if patch.size == 0:
        return 0.0
    frame_v = float(screen.max(axis=2).mean())
    if frame_v <= 0.0:
        return 0.0
    return float(np.percentile(patch.max(axis=2), 99.9)) / frame_v


# ---- 「今日支援上限」满没满（2026-09-26 补的**画面判据**）----
#
# 以前这条只能靠「``support-one`` 连点 4 次推不动」倒推，日志里写的是**推测**：
# 「多半是今日支援上限已满」。两处代价（2026-09-25 实跑都撞上了）：
#   ① 一天里第二次跑捐赠，又要白点 4 次、再恢复导航一次，才得出同一结论；
#   ② 「没推进」也可能是别的原因（点丢了 / 那一行真的吃不下），却一律写成「上限满了」。
#
# 现在直接读右上角那一行「今日支援上限 N/200」的**数字本身**：
# 整串当一张模板匹配（用户 2026-09-26 定的做法），命中「200/200」= 满了。
#
# 模板来源：2026-09-25 21:38 那次实跑的现场帧
# （``runtime_diagnostics/epic7_knights_donation/20260925_213803_468044_knights_support-one_stuck.png``，
# 就是 support-one 推不动的那一帧，右上角正是 200/200）。裁框由字形探针定位：
# 7 个字形落在画布 x 1244..1350、y 199..221。
SUPPORT_LIMIT_BOX = (1242, 197, 110, 27)
# 搜索区：套住右上角那一整行、不越到别的区域（左侧的进度图标留在框外，
# 图标在不同帧里会变颜色，把它包进来只会平白多一个变量）。
SUPPORT_LIMIT_REGION = (1150, 175, 280, 70)
#
# 阈值 0.90 由**全库实测**定（``runtime_logs/_kd_limit_build_assets.py``，
# 257 张基准尺寸夹具）：
# - 正例（``support_limit_full``，200/200）：**1.0000**
# - 最高干扰：**0.8167** —— ``support_page_short_material``（同页但是 **90/200**）；
#   同页 30/200 的四张 0.7792~0.7895（整串与「200/200」共享 ``0/200`` 尾巴，
#   所以同页干扰天然就高，这也是不能把阈值往 0.85 以下放的原因）
# - 其它路线最高只有 **0.2720**（英雄页的转送按钮）
# ⇒ 阈值 0.90：对「没满」余量 0.083、对正例余量 0.10。**改它之前重跑那个探针。**
SUPPORT_LIMIT_FULL_THRESHOLD = 0.90


def support_limit_full(
    screen: np.ndarray,
    template: np.ndarray,
    *,
    region: tuple[int, int, int, int] = SUPPORT_LIMIT_REGION,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> Optional[Match]:
    """右上角「今日支援上限」是不是已经满了（整串 ``200/200`` 命中）。命中返回 Match。

    认不出/读不到（框被弹窗盖住、页面淡入到看不见字、分辨率不符）⇒ 返回 ``None``
    = **当作没满**，照旧去点支援按钮。这个方向是刻意选的：判成「已满」会跳过整个
    支援环节，而这一天的支援机会不可能补回来；判成「没满」最坏也就是退回今天的行为
    （点不动 ⇒ 4 次之后 ``support_closed`` 兜底）。
    """
    return find_template(
        screen,
        template,
        SUPPORT_LIMIT_FULL_THRESHOLD,
        region=region,
        reference_size=reference_size,
    )


def state_label(state: KnightsDonationState) -> str:
    return STATE_LABELS.get(state, state.value)


@dataclass(frozen=True)
class KnightsDonationAction:
    """一个动作，**必须声明出处与出口验收**（新路线准入，见模块 docstring 对账表）。

    ``target_pages``（换页动作）与 ``in_page_evidence``（同页动作）**至少填一个**，
    两个都空会被 ``ModeRunnerBase._require_transition_contract`` 直接拒发。
    """

    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    in_page_evidence: str = ""
    reason: str = ""


@dataclass(frozen=True)
class KnightsDonationTemplates:
    activity_entry: np.ndarray
    panel_title: np.ndarray
    tab_resource_support: np.ndarray
    tab_weekly_tasks: np.ndarray
    request_support_button: np.ndarray
    support_one_button: np.ndarray
    points_label: np.ndarray
    claim_button: np.ndarray
    popup_title: np.ndarray
    flower_cell: np.ndarray
    flower_cell_selected: np.ndarray
    popup_confirm: np.ndarray
    reward_title: np.ndarray
    support_confirm_title: np.ndarray
    support_confirm_button: np.ndarray
    # 右上角「今日支援上限 200/200」的**整串**外观：命中 = 今天支援到顶了。
    # 判据见 ``support_limit_full``（含全库实测的阈值依据）。
    support_limit_full: np.ndarray
    # 数字字模（0~5），前置判据「材料不足就跳过」用；见 ``knights_support_digits.py``。
    # ⚠️ 刻意**不给默认值**：字模是判据的一部分，漏了就会安静地退回「照旧点」，
    # 属本项目最怕的「判据没接上」那类。要动它就得显式改这里。
    digit_glyphs: dict[int, np.ndarray]
    evidence: object = None


def build_knights_donation_templates(template_dir: Path) -> KnightsDonationTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    return KnightsDonationTemplates(
        activity_entry=load("activity_entry"),
        panel_title=load("panel_title"),
        tab_resource_support=load("tab_resource_support"),
        tab_weekly_tasks=load("tab_weekly_tasks"),
        request_support_button=load("request_support_button"),
        support_one_button=load("support_one_button"),
        points_label=load("points_label"),
        claim_button=load("claim_button"),
        popup_title=load("popup_title"),
        flower_cell=load("flower_cell"),
        flower_cell_selected=load("flower_cell_selected"),
        popup_confirm=load("popup_confirm"),
        reward_title=load("reward_title"),
        support_confirm_title=load("support_confirm_title"),
        support_confirm_button=load("support_confirm_button"),
        support_limit_full=load("support_limit_full"),
        # 缺任何一个数字字模都会在这里直接抛错 —— 宁可加载不动，也不要安静地
        # 退回「点完没反应就重试」那条老路。
        digit_glyphs=load_digit_glyphs(template_dir),
        evidence=build_knights_donation_evidence(template_dir),
    )


class KnightsDonationStateMachine:
    """骑士团捐赠一轮的纯视觉决策。

    与 world_boss 同构：页面识别统一走 ``evidence/knights_donation.py`` 的页面组合，
    状态机不自己写「靠上下文猜这是哪一页」的判据。**每一帧都重新判页面**，
    所以状态不会「拨错之后卡到超时」—— 唯一的例外是 ``_request_done`` /
    ``_support_scrolls`` 两个业务进度标志，它们表达的是「这一次进程里做过什么」，
    画面里看不出来。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    def __init__(
        self,
        templates: KnightsDonationTemplates | Path,
        *,
        initial_state: KnightsDonationState = KnightsDonationState.RESOURCE_SUPPORT,
        backend: str = "emulator",
    ) -> None:
        self.backend = backend
        self.templates = (
            build_knights_donation_templates(templates)
            if isinstance(templates, Path)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        # 「今天这一次请求支援已经发出去了」。每天只能请求一次 ⇒ 同一次运行里只做一次。
        self.request_done = False
        # 支援列表下滑次数账本（每支援成功一次清零）。
        self.support_scrolls = 0
        # ⚠️ 「这一格别再点了」的跳过表（记按钮中心的 y）。**两条来路共用**：
        #   ① **点之前**读出「持有 < 需求」（材料不足，2026-09-25 补的前置判据）⇒ 没点；
        #   ② 点过但回到列表页没等到「获得奖励」⇒ 那一下没生效。
        # 实测（用户 2026-09-24 确认）：团员要的材料我持有不足时，确认框点完行不会消失、
        # 点数也不涨 —— 游戏只在下方**闪一行小字「材料不足」**，一闪就没（做不成判据，
        # 详见模块 docstring）⇒
        # 必须记住这一行、下一次挑**别的**绿按钮，否则会一直挑到同一行、
        # 四次之后整条路线中止，永远轮不到下面那个能支援的人。
        # ⚠️ **键是绝对 y、只在「列表没动过」时才有效**：支援成功会重排、下滑会
        # 整体移位 —— 这两种情况一发生，旧的 y 就指到**别人**头上了，必须清空
        # （见 ``_at_reward_popup`` 与 `_at_resource_support` 的第 3 步）。
        self.skipped_rows: set[int] = set()
        # 本轮已经点下去、还在等结果的支援（按钮中心的 y）。它表达的是
        # 「这一下到底生效没有」的待结算状态，画面里看不出来。
        self.pending_support_y: Optional[int] = None
        # 「支援这一节到此为止」：``support-one`` 连点 4 次都没推进时由 Runner 置上
        # （见 ``_on_action_exhausted``）。置上之后**一个支援按钮都不点**，
        # 进到资源支援页直接切「每周任务」—— 用户 2026-09-25 的要求：
        # 「碰到了捐赠上限，那就跳过这个环节，那就直接到下一步那个每周任务」。
        #
        # ⚠️ 2026-09-26 更正：原注释写「画面里看不出上限满了，只能靠推不动推出来」——
        # 前半句只对了一半：**列表里的绿按钮**确实看不出（照样是绿的、点下去连提示都不弹），
        # 但右上角那一行「今日支援上限 N/200」是清清楚楚的。现在有画面判据
        # ``support_limit_full``，这条标志退化成**兜底**（判据没读到数字时才用得上）。
        self.support_closed = False
        # 收工理由（写进运行日志的「结论=」，认页面时不出来，只在 _finish 里写）。
        self.finish_reason = ""
        self._confirmed_page = ""

    # ---- 视觉判据 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        return find_template(
            screen,
            getattr(self.templates, name),
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
        )

    def _required(self, screen: np.ndarray, name: str) -> Match:
        """拿不到就失败关闭：**绝不猜坐标**。"""
        match = self._locate(screen, name)
        if match is None:
            raise UnrecognizedScreen(
                f"骑士团捐赠画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def observe_page(self, screen: np.ndarray) -> Optional[KnightsDonationState]:
        """按 evidence 页面组合认出当前是哪一页；认不出返回 None。

        判定顺序即 ``_PAGE_STATES``（弹窗在前）。互斥性实测表见
        ``evidence/knights_donation.py`` 的模块 docstring。
        """
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    # ---- 动作构造 ----

    def _confirm_page(self, page: str) -> None:
        """登记「视觉确认我现在站在哪一页」，供主循环对账转场契约。

        ⚠️ **只在 ``next_action`` 开头、按 ``observe_page`` 的结果写**，
        不在 ``_action`` 里写。区别在「本帧没有动作」的分支上（例：每周任务
        已经没得领了 → 直接收工）。那种分支不会调用 ``_action``，如果靠
        ``_action`` 来写，页面标识就会**停在上一个动作的来源页**，主循环于是
        认为「上一个转场没成功」，把同一个动作再点一遍。
        """
        self._confirmed_page = page

    def _action(
        self,
        name: str,
        *,
        point: tuple[int, int],
        source_page: str,
        reason: str,
        target_pages: tuple[str, ...] = (),
        in_page_evidence: str = "",
    ) -> KnightsDonationAction:
        return KnightsDonationAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    # ---- 各页决策 ----

    def _at_guild_home(self, screen: np.ndarray):
        # ⚠️ **不看红点**（用户 2026-09-24 更正）：有没有红点都进。
        # 原先这里以「图标有没有红点」决定进不进、没红点就整条路线结束 —— 已拿掉。
        # 于是「今天其实没事可做」这天也会整条走完：请求支援（若当天还没发）、
        # 支援列表找不到人、下滑两轮、切到每周任务发现没得领，然后正常收工。
        entry = self._required(screen, "activity_entry")
        return self._action(
            "open-activity",
            point=entry.center,
            source_page=state_label(KnightsDonationState.GUILD_HOME),
            # 三个落点都是合法的：活动界面上次停在哪一页，这次就还停在哪一页。
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.WEEKLY_TASKS),
                state_label(KnightsDonationState.ACTIVITY_PANEL),
            ),
            reason=f"骑士团主页「骑士团活动」图标（中心={entry.center}），有没有红点都进去",
        )

    def _at_activity_panel(self, screen: np.ndarray):
        tab = self._required(screen, "tab_resource_support")
        return self._action(
            "open-resource-tab",
            point=tab.center,
            source_page=state_label(KnightsDonationState.ACTIVITY_PANEL),
            target_pages=(state_label(KnightsDonationState.RESOURCE_SUPPORT),),
            reason="在骑士团活动界面但页签没认出来，先切到「资源支援」",
        )

    def _support_candidates(self, screen: np.ndarray) -> list[Match]:
        """整列里**所有**绿色「支援1个」按钮，按分数从高到低。

        为什么不能只取最高分那个：一屏可能有多个一模一样的按钮，而业务要逐个点过去。
        """
        atom = self.templates.evidence.atom("support_one_button")
        return find_all_templates(
            screen,
            self.templates.support_one_button,
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
            min_gap=SUPPORT_PEAK_MIN_GAP,
        )

    def _is_skipped(self, y: int) -> bool:
        return any(
            abs(y - skipped) <= SUPPORT_ROW_SKIP_TOLERANCE for skipped in self.skipped_rows
        )

    def _request_button_still_alive(self, screen: np.ndarray) -> bool:
        """右上「请求支援」现在还是亮的（= 今天还没请求过）吗？

        ⚠️ **拿不准一律当作「还亮着」**（fail-open ⇒ 照旧去点）：只有明确量到
        「暗了一大截」才跳过这一步。反过来误判成「已灰」会白丢当天唯一一次请求，
        而且用户从画面上很难察觉 —— 所以不确定时宁可退回今天的行为。
        """
        region = self.templates.evidence.atom("request_support_button").region
        ratio = request_button_relative_v(screen, region)
        if ratio <= 0.0:  # 区域裁不出来 / 整幅全黑 ⇒ 量不到，别下结论
            return True
        return ratio >= REQUEST_BUTTON_ALIVE_RATIO

    def _at_resource_support(self, screen: np.ndarray):
        # 0') 支援这一节已经收工 ⇒ **一个按钮都不点**，直接切「每周任务」。
        #
        #    触发场景（2026-09-25 晚实跑）：右上角「今日支援上限 200/200」满了，
        #    列表里的绿按钮却**照样是绿的**、点下去什么都不发生 ⇒ ``support-one``
        #    连点 4 次推不动 ⇒ Runner 置上 ``support_closed``，主循环**原地**重新
        #    决策一次（不再回大厅重新导航）。重新决策落到这一页时就在这里掉头：
        #    支援不做了，但**每周任务照做**（这正是用户要的「跳过这一节，走下一步」；
        #    改了之前会整条路线收工、把每周任务一起丢掉）。
        #    ② 另外一路**不进这页**也能收工：右上角「今日支援上限 200/200」是**看得见的**
        #    画面证据（2026-09-26 补的判据 ``support_limit_full``）。它比「推不动」更早、
        #    也更准 —— 后者只是症状，前者是原因。两条来路在日志里**分开写**，不混。
        limit = support_limit_full(screen, self.templates.support_limit_full)
        if self.support_closed or limit is not None:
            tab = self._required(screen, "tab_weekly_tasks")
            if limit is not None:
                evidence = (
                    f"右上角「今日支援上限」已经满（整串 200/200，得分 {limit.score:.4f}"
                    f" @{limit.center}）"
                )
            else:
                evidence = "本轮的支援按钮连点 4 次都没推进过（当时没读到上限数字）"
            return self._action(
                "open-weekly-tab",
                point=tab.center,
                source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                target_pages=(state_label(KnightsDonationState.WEEKLY_TASKS),),
                reason=(
                    f"支援这一节收工：{evidence} ⇒ 不再点任何支援按钮，直接去做每周任务"
                ),
            )
        # 0) 先结算上一轮：**回到列表页就说明没等到「获得奖励」** ⇒ 那一下没生效，
        #    把那一行记进跳过表（实测 + 用户确认：材料不足时游戏只闪一行小字
        #    「材料不足」，行不消失、点数不涨、也不弹奖励 ⇒ 就是「吃不下」）。
        #    代价说明：万一那一下是**点击丢了**（不是吃不下），也会被记进跳过表 ⇒
        #    这一次运行会漏掉这个团员。宁可漏一个人，也不要在一行上白转 4 次
        #    让整条路线中止 —— 而误判在一次成功的支援之后就会自动失效（列表重排 ⇒ 清空）。
        if self.pending_support_y is not None:
            self.skipped_rows.add(self.pending_support_y)
            self.pending_support_y = None
        # 1) 每天一次的「请求支援」。同一次运行里只做一次。
        #
        #    ⚠️ 还要看**今天是不是已经请求过了**（2026-09-25 用户实跑撞上）：额度用完
        #    按钮会**变灰**，但形状没变 ⇒ 模板照样命中（灰帧 0.9846）⇒ 照点的话页面不变、
        #    每次白等 42 秒转场超时 × 4 次、整条路线提前收工。变灰只体现在**亮度**上，
        #    判据见 ``request_button_relative_v``。
        #    这一步跳过时**不影响**「支援别人」—— 列表里的绿按钮跟这个额度无关，
        #    当天第二个运行照样有人可以支援（用户那次现场就是这样）。
        request_note = ""
        if not self.request_done:
            button = self._locate(screen, "request_support_button")
            if button is not None:
                if self._request_button_still_alive(screen):
                    return self._action(
                        "request-support",
                        point=button.center,
                        source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                        target_pages=(state_label(KnightsDonationState.REQUEST_POPUP),),
                        reason="资源支援页右上角「请求支援」，每天只能发一次",
                    )
                # 今天已经请求过了 ⇒ 只把账记上、往下走去支援别人，**绝不点它**。
                self.request_done = True
                request_note = "；今天已经请求过支援了（右上「请求支援」是灰的），跳过请求这一步"
        # 2) 支援别人。列表会重排，所以每轮都在整列里重新认绿色按钮；
        #    已经判定「吃不下」的行跳过，去点下一个。
        #
        #    前置判据（2026-09-25 补）：**点之前**先读这一行的「持有：N」与按钮上的
        #    「支援 M 个」。``N < M`` 就是材料不足 —— 游戏不会让按钮变灰，点下去
        #    什么都不发生，主循环会当成「没点到」重试 4 次然后把整条路线收工
        #    （2026-09-25 实跑现场）。所以这一格**连点都不点**，直接记进跳过表。
        #    ⚠️ 读不出（``verdict is None``）就照旧点 —— 退回下面那道兜底判据。
        short_rows: list[str] = []
        for candidate in self._support_candidates(screen):
            if self._is_skipped(candidate.center[1]):
                continue
            numbers = self._row_numbers(screen, candidate.center)
            if numbers.verdict is True:
                self.skipped_rows.add(candidate.center[1])
                short_rows.append(numbers.describe())
                continue
            self.pending_support_y = candidate.center[1]
            return self._action(
                "support-one",
                point=candidate.center,
                source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                # 两种落点都合法：有的行直接弹「获得奖励」，有的行先弹确认框。
                target_pages=(
                    state_label(KnightsDonationState.SUPPORT_CONFIRM),
                    state_label(KnightsDonationState.REWARD_POPUP),
                ),
                reason=(
                    f"列表里有可支援的成员（绿色按钮@{candidate.center}，"
                    f"{numbers.describe()}）{self._skipped_note(short_rows)}{request_note}"
                ),
            )
        # 3) 视口内没有可点的 ⇒ 可能一屏放不下，下滑再看（有界）。
        if self.support_scrolls < MAX_SUPPORT_SCROLLS:
            self.support_scrolls += 1
            # 滑动手势会让整列位移 ⇒ 跳过表里的 y 键失效，必须清空（否则会误跳过
            # 刚滑上来的那几行）。
            self.skipped_rows.clear()
            tab = self._required(screen, "tab_resource_support")
            return self._action(
                "scroll-support",
                # ⚠️ 这个坐标是**空点**：主循环只认「点击」，滑动由 Runner 的
                # `_after_action_click` 补发。点在「当前已选中的资源支援页签」上，
                # 是这一页里唯一一个点下去一定没有副作用的落点。
                point=tab.center,
                source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
                in_page_evidence="列表整体上移（按钮行的 y 坐标变小 / 出现此前不可见的新行）",
                reason=(
                    f"视口内没有可支援的成员，下滑第 {self.support_scrolls}/{MAX_SUPPORT_SCROLLS} 次"
                    f"{self._skipped_note(short_rows)}{request_note}"
                ),
            )
        # 4) 支援收尾 ⇒ 去做每周任务。
        tab = self._required(screen, "tab_weekly_tasks")
        return self._action(
            "open-weekly-tab",
            point=tab.center,
            source_page=state_label(KnightsDonationState.RESOURCE_SUPPORT),
            target_pages=(state_label(KnightsDonationState.WEEKLY_TASKS),),
            reason=f"已经没有可支援的成员了，切到「每周任务」{self._skipped_note(short_rows)}{request_note}",
        )

    def _row_numbers(self, screen: np.ndarray, button_center: tuple[int, int]) -> RowNumbers:
        """读这一行的「持有：N」与按钮「支援 M 个」（读不出时两侧是 None）。"""
        glyphs = self.templates.digit_glyphs
        if not glyphs:
            # 字模没接上：**不要猜**，一律当「不知道」⇒ 调用方照旧点。
            return RowNumbers(None, None)
        return read_row_numbers(screen, button_center, glyphs, reference_size=REFERENCE_SIZE)

    @staticmethod
    def _skipped_note(short_rows: list[str]) -> str:
        """把「这一帧因为材料不足跳过了哪几格」写进动作理由，日志里看得见。"""
        if not short_rows:
            return ""
        return f"；已跳过 {len(short_rows)} 格材料不足（{'、'.join(short_rows)}），没点它们"

    def _at_support_confirm(self, screen: np.ndarray):
        """「支援资源 / 确定要支援以下的资源吗?」确认框：点它里面的「支援1个」。

        ⚠️ 这里**不做「按钮是不是灰的」判断**（没有可靠判据）：确认之后到底生效没有，
        靠**有没有弹「获得奖励」**来结算 —— 没弹就说明这一行吃不下，
        ``_at_resource_support`` 的第 0 步会把它记进跳过表。
        所以 ``target_pages`` 两个落点都写上了，它们都真实存在。
        ⚠️ 「材料不足」那行小字游戏**会**给（用户 2026-09-24 确认），但它一闪就没、
        漏检和没出现分不开 ⇒ 不拿它做判据（理由见模块 docstring）。
        ⚠️ 材料不足的格子**本该在挑行时就被拦下**（``_at_resource_support`` 的前置判据），
        走到这里就说明那一行的数字**没读出来** ⇒ 照旧点、按上面的方式结算。
        """
        button = self._required(screen, "support_confirm_button")
        return self._action(
            "confirm-support",
            point=button.center,
            source_page=state_label(KnightsDonationState.SUPPORT_CONFIRM),
            target_pages=(
                state_label(KnightsDonationState.REWARD_POPUP),
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
            ),
            reason="「支援资源」确认框里的「支援1个」，点完才算真的支援",
        )

    def _at_request_popup(self, screen: np.ndarray):
        if self._locate(screen, "flower_cell_selected") is None:
            flower = self._required(screen, "flower_cell")
            return self._action(
                "select-flower",
                point=flower.center,
                source_page=state_label(KnightsDonationState.REQUEST_POPUP),
                in_page_evidence="该格变成金色选中框（flower_cell_selected 由不命中变命中）",
                reason="在弹窗里选「下级精灵之花」（每天固定选它，永远不会缺）",
            )
        confirm = self._required(screen, "popup_confirm")
        self.request_done = True
        return self._action(
            "confirm-request",
            point=confirm.center,
            source_page=state_label(KnightsDonationState.REQUEST_POPUP),
            # 正常关窗回资源支援页；万一游戏顺手弹了「获得奖励」，也算合法落点。
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.REWARD_POPUP),
            ),
            reason="弹窗底部「请求支援」，发出即消耗今天的唯一一次额度",
        )

    def _at_reward_popup(self, screen: np.ndarray):
        title = self._required(screen, "reward_title")
        # 支援链路完成一次 ⇒ 下滑次数账本清零（下一段还能重新往下找）。
        self.support_scrolls = 0
        # 看到「获得奖励」就说明刚才那一下**真的生效了** ⇒ 待结算的支援作数，
        # 不要把它记进跳过表（第 0 步只在「回到列表且没弹奖励」时才会记）。
        self.pending_support_y = None
        # 支持成功 ⇒ 这个团员在列表里变成灰勾、整列**重排**（实测）⇒ 跳过表里
        # 那些按 y 记的键全都指到别人头上了，必须清空，否则会误跳过能支援的人。
        self.skipped_rows.clear()
        return self._action(
            "dismiss-reward",
            point=(title.center[0], title.center[1] + REWARD_DISMISS_DY),
            source_page=state_label(KnightsDonationState.REWARD_POPUP),
            target_pages=(
                state_label(KnightsDonationState.RESOURCE_SUPPORT),
                state_label(KnightsDonationState.WEEKLY_TASKS),
            ),
            reason="「获得奖励」弹窗（实机确认点弹窗内任意位置都能关）",
        )

    def _at_weekly_tasks(self, screen: np.ndarray):
        dot = find_dot(screen, "milestone", reference_size=self._REFERENCE_SIZE)
        if dot is not None:
            point = milestone_claim_point(dot)
            return self._action(
                "claim-milestone",
                point=point,
                source_page=state_label(KnightsDonationState.WEEKLY_TASKS),
                in_page_evidence="该档位的角标消失（图标原地变成绿勾，弹窗不出现）",
                reason=f"骑士团点数有可领档位（角标中心={dot}，图标中心={point}）",
            )
        claim = self._locate(screen, "claim_button")
        if claim is not None:
            return self._action(
                "claim-task",
                point=claim.center,
                source_page=state_label(KnightsDonationState.WEEKLY_TASKS),
                target_pages=(state_label(KnightsDonationState.REWARD_POPUP),),
                reason=f"有已完成的每周任务可领（绿色「领取」@{claim.center}）",
            )
        self._finish("每周任务已经没有可领的点数档位和可领的任务了")
        return None

    def _finish(self, reason: str) -> None:
        """一轮走完：轮次 +1，主循环据此在 ``max_cycles`` 满足时收工。"""
        self.state = KnightsDonationState.FINISHED
        self.completed_cycles += 1
        self.finish_reason = reason

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[KnightsDonationAction]:
        page = self.observe_page(screen)
        if page is None:
            # 认不出就不点：把「已确认页面」作废，免得主循环拿过期页面去对账转场契约。
            self._confirmed_page = ""
            raise UnrecognizedScreen(
                f"骑士团捐赠画面[{state_label(self.state)}]未识别"
            )
        self.state = page
        # 「视觉确认我现在站在哪一页」——每帧重写一次（理由见 _confirm_page 的 docstring）。
        self._confirm_page(state_label(page))
        handler = {
            KnightsDonationState.GUILD_HOME: self._at_guild_home,
            KnightsDonationState.ACTIVITY_PANEL: self._at_activity_panel,
            KnightsDonationState.RESOURCE_SUPPORT: self._at_resource_support,
            KnightsDonationState.REQUEST_POPUP: self._at_request_popup,
            KnightsDonationState.SUPPORT_CONFIRM: self._at_support_confirm,
            KnightsDonationState.REWARD_POPUP: self._at_reward_popup,
            KnightsDonationState.WEEKLY_TASKS: self._at_weekly_tasks,
        }[page]
        return handler(screen)

    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        ``next_action`` 会推进 ``request_done`` / ``support_scrolls`` / ``completed_cycles``，
        主循环每帧都会先调 preview 做两帧稳定确认，不还原就会把「一次点击」记成两次。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self.request_done,
            self.support_scrolls,
            self.finish_reason,
            self._confirmed_page,
            set(self.skipped_rows),
            self.pending_support_y,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.request_done,
                self.support_scrolls,
                self.finish_reason,
                self._confirmed_page,
                self.skipped_rows,
                self.pending_support_y,
            ) = snapshot


class KnightsDonationRunner(ModeRunnerBase):
    """骑士团捐赠一次性 Runner（主循环协议见 ``ModeRunnerBase``）。

    ⚠️ 本路线是**第一条**打开 ``_REQUIRE_TRANSITION_CONTRACT`` 的路线：每个动作
    都必须在发出前通过「source_page + 出口验收」的机器校验。
    """

    _MODE_LABEL = "骑士团捐赠"
    # 新路线准入：动作缺声明直接拒发（含空跑）。
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        KnightsDonationState.GUILD_HOME: 45,
        KnightsDonationState.ACTIVITY_PANEL: 45,
        KnightsDonationState.RESOURCE_SUPPORT: 60,
        KnightsDonationState.REQUEST_POPUP: 45,
        KnightsDonationState.SUPPORT_CONFIRM: 45,
        KnightsDonationState.REWARD_POPUP: 45,
        KnightsDonationState.WEEKLY_TASKS: 60,
        KnightsDonationState.FINISHED: 45,
    }
    # 这条路线不打架，没有「已承诺战斗」环节。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 动作重试窗口。默认 45 秒是给「换页」定的；本路线这几个动作要么是**弹窗内的一步**
    # （点完立刻能看出生效没有），要么是**同页领奖**（点完原地变灰），
    # 用 45 秒纯属白等 —— 这正是 world_boss 记过的「领奖干等 40 多秒」那一类。
    _SHORT_RETRY_ACTIONS = frozenset(
        {
            "select-flower",
            "confirm-request",
            "support-one",
            "confirm-support",
            "claim-milestone",
            "claim-task",
            # 下滑是**同一个动作名连发两次**（账本上限 2 次），第二次点击会走「同名动作
            # 等待重试窗口」那条路；用默认 45 秒就是白等 45 秒。它没有「点了没生效」
            # 的补救动作（滑不动也会照账本往下走），所以短窗口没有副作用。
            "scroll-support",
        }
    )
    _SHORT_RETRY_SECONDS = 8.0

    def __init__(
        self,
        machine: KnightsDonationStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
        )

    def _state_label(self, state: KnightsDonationState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _after_action_click(self, action: KnightsDonationAction) -> None:
        """``scroll-support`` 的点击是**空点**，真正的下滑在这里补发。

        为什么不让状态机直接滑：主循环的动作通道只有 ``runtime.click``，
        状态机里做 I/O 又会被 ``preview()`` 每帧重放一遍（滑动会连发几十次）。
        所以走「动作带一个没有副作用的落点 + 这里补手势」。
        """
        if action.name != "scroll-support":
            return
        self.runtime.swipe(
            SUPPORT_SWIPE_START,
            SUPPORT_SWIPE_END,
            SUPPORT_SWIPE_DURATION_MS,
            "knights-support-scroll",
        )

    def _on_action_exhausted(self, action: KnightsDonationAction, screen) -> bool:
        """点 4 次都推不动：**支援这一节与别的动作处理不同**。

        ⚠️ 原注释写着「支撑到上限时列表里的绿按钮会自己变灰（同一玩家一天只能支援
        一次），所以绿色按钮一直点不动 = 真的出了问题」—— 这条假设 **2026-09-25 晚
        被实跑证伪**：那时右上角「今日支援上限 200/200」已经满了，而列表里的绿按钮
        **照样是绿的**、点下去什么都不发生（游戏连提示都不弹）。
        旧行为是返回 True 就地收尾 ⇒ **整条路线提前结束**，后面的「每周任务」领奖
        跟着一起丢掉。

        所以 ``support-one`` 推不动时：置上「支援这一节收工」，返回 False 交给
        ``run()`` 去给一次「换个办法」的机会 —— 主循环**原地**重新决策一次，
        状态机在资源支援页看到那个标志就把流程推进到「每周任务」。
        代价为零（不用再回大厅重新导航那二十几秒），
        换回的是「这一天的每周任务照做」。

        ⚠️ 2026-09-26 更正：这段注释原来写的是「返回 False 放行走**恢复导航**
        （回大厅重新导航再回来）」。用户当天拍板「回家就是结束，不可能再回到
        这个任务」⇒ ``runner_base`` 那条「回大厅重新导航然后接着跑」整段删掉，
        改成**原地**让路线重新决策一次。这条路线要的语义没变，只是少绕一趟大厅。

        ⚠️ 「换个办法」**只给一次**（``runner_base._self_heal_used``）：重新决策
        如果还是 ``support-one`` 本身，主循环立刻收手，**不会**再多点 4 次。

        其它动作推不动 ⇒ 维持原样（优雅收尾）：那才是真的出了问题。
        """
        if action.name == "support-one":
            self.machine.support_closed = True
            self.runtime.log(
                f"模式={self._MODE_LABEL} 支援=连点 4 次没能推进"
                " ⇒ 结束支援这一节，接下来直接去做每周任务（不再点任何支援按钮）"
            )
            return False
        diagnostic = self.runtime.save_diagnostic(f"knights_{action.name}_stuck", screen)
        self._save_failure_diagnostic(
            diagnostic,
            screen,
            action=action,
            attempt=4,
            conclusion=f"动作 {action.name} 连续 4 次未能看到出口证据",
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 停止=动作[{action.name}]连续 4 次未生效 "
            f"现场={diagnostic}"
        )
        return True

    def _log_cycle_completed(self) -> None:
        reason = getattr(self.machine, "finish_reason", "")
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} 结论={reason or '已走完出口'}"
        )

    def _decision_hint(self, action_name: str, state: KnightsDonationState) -> str:
        return ""


# ---- 开局接力 ----
# 契约与三道卡点见 docs/TRANSITION_CONTRACTS.md「接力契约」那一节。


class KnightsDonationResumePoint(NamedTuple):
    """骑士团捐赠开局接力的落点（``modes.ResumePoint`` 的路线本地版）。"""

    page: str                       # 中文页面名，给日志和诊断看
    state: Optional[str] = None     # 恒为 None：本路线每帧重判页面，不需要拨状态
    entry: Optional[str] = None     # 非空 = 已经在导航链的某一级上，从这里接着导航


def detect_resume_point(
    machine: "KnightsDonationStateMachine",
    screen: np.ndarray,
) -> Optional[KnightsDonationResumePoint]:
    """骑士团捐赠开局接力：认出人停在哪一页就就地接管。

    **判据与运行期同源** —— 直接调状态机自己的 ``observe_page``，不另定一套阈值、
    不加新锚点。这条路线的页面识别是**纯锚点**（`evidence` 页面组合，不依赖状态机
    上下文），所以开局只有一帧也判得出来；这正是它比 `hero_synthesis` 好做的地方
    （后者要靠 `transmit_phase` 这类上下文分页，而接力只有一帧）。

    **不拨状态**（``state`` 恒为 None，照 `shop_refresh` 的做法）：本状态机**每一帧都从
    画面重判页面**（见 `KnightsDonationStateMachine` 的类 docstring），拨了下一帧就被覆盖，
    留着只会制造「日志说拨到了 A、实际画面是 B」的假象。

    落在**骑士团主页**时额外给 ``entry``：那一页在导航链上（大厅 → 骑士团主页），
    从这里接着导航能省掉一次「进入骑士团」的点击。

    ⚠️ 人停在**大厅**上时返回 None（``activity_entry`` 在骑士团主页上，大厅上不成立）⇒
    照旧走「回大厅 → 进骑士团」，与接力挂上之前的行为完全一致。
    """
    page = machine.observe_page(screen)
    if page is None:
        return None
    if page is KnightsDonationState.GUILD_HOME:
        return KnightsDonationResumePoint(
            page=state_label(page),
            entry=KNIGHTS_GUILD_HOME_PAGE,
        )
    if page in _RESUMABLE_STATES:
        return KnightsDonationResumePoint(page=state_label(page))
    return None
