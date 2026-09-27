"""骑士团「捐赠」路线的视觉证据档案。

本模块只放资源、区域、阈值和页面判据；业务决策在 ``games/epic7/knights_donation.py``。

## 这条路线要干什么（用户 2026-09-24 口述的业务流程）

```
骑士团主页
  └ 左侧「骑士团活动」图标 → 点进去（**有没有红点都进**，用户 2026-09-24 更正）
骑士团活动（左侧三个页签：资源支援 / 团员商店 / 每周任务，**只碰 1 和 3**）
  ├ 资源支援页
  │   ├ 右上「请求支援」→ 弹窗选「下级精灵之花」→ 底部「请求支援」→ 每天一次
  │   └ 列表里每行右侧的绿色「支援1个」**依次点完**
  │       ├ 有的行点完**直接**弹「获得奖励（30，今日支援上限 x/200）」
  │       └ 有的行会**先**弹「支援资源 / 确定要支援以下的资源吗?」确认框，
  │          要点它里面那个「支援1个」才算数
  │       ⚠️ 实测（2026-09-24）+ 用户确认：团员要的材料我「持有 0」时，确认框点完
  │          **什么都不发生** —— 行不消失、今日支援上限不涨、也不弹获得奖励；
  │          游戏只在下方**闪一行小字「材料不足」**，一闪就没
  │          （用户原话「很快，然后就没了」）⇒ **那行字不做判据**（每秒一帧 + 两帧稳定
  │          的取帧节奏必然漏检，而「没看到」与「没出现」分不开）。
  │          所以「有没有真的支援成功」只能靠**有没有弹「获得奖励」**判断，
  │          状态机据此把这一行记进跳过表、去点下一行。
  │       ⚠️ 一屏可能同时有**多个**绿按钮（实拍 ``support_page_two_buttons.png`` 就是
  │          两个：0.9360 / 0.9278），而且**上面那个吃不下、下面那个才行** ⇒
  │          挑行必须走 ``find_all_templates`` 把整列都拿出来逐个点；
  │          只用 ``find_best_template``（永远只给最高分那一个）会死磕同一行直到中止。
  └ 每周任务页
      ├ 骑士团点数进度条上**可领的档位**（图标带一个亮点）
      └ 每行右侧的绿色「领取」
```

## 页面互斥的实测依据（2026-09-24，全库 203 张 1982×1132 夹具扫描）

扫描是一次性探针（``runtime_logs/_*knights*.py``，gitignore，随时可能被清理），
但**口径本身是活的**：``tests/test_knights_donation.py::EXPECTATIONS`` 是同一把尺子
的可执行版本。⚠️ 探针里必须把 ``cv2.imread``
的 BGR 翻成 RGB —— ``load_template`` 返回的是 RGB，口径不一致时会拿到假分数，
实测能把支持页页签从 1.0000 压到 0.8195）。

| 锚点 | 本路线最高 | 不该命中的帧里最高 | 余量 |
|---|---|---|---|
| ``activity_entry`` | 1.0000 | 0.3847（gift_support_popup） | +0.6153 |
| ``panel_title`` | 1.0000 | 0.7821（hero/reward_popup） | +0.2179 |
| ``request_support_button`` | 1.0000 | 0.3646（request_popup） | +0.6354 |
| ``support_one_button`` | 1.0000 | 0.5358（weekly_tasks_claimable） | +0.4642 |
| ``points_label`` | 1.0000 | 0.4138（story/skill_animation） | +0.5862 |
| ``claim_button`` | 1.0000 | 0.6650（weekly_tasks_claimed） | +0.3350 |
| ``popup_title`` | 1.0000 | 0.4123（fodder/special_book） | +0.5877 |
| ``flower_cell`` | 1.0000 | 0.8279（**本弹窗的选中态**） | +0.1721 |
| ``flower_cell_selected`` | 1.0000 | 0.7878（**本弹窗的未选中态**） | +0.2122 |
| ``popup_confirm`` | 1.0000 | 0.4162（story/battle_auto_off） | +0.5838 |
| ``reward_title`` | 1.0000 | 0.5446（shop_refresh/covenant_purchase） | +0.4554 |
| ``tab_resource_support`` | 1.0000 | 0.9181（每周任务页——页签文字本来就一直在） | 不排他，见下 |
| ``tab_weekly_tasks`` | 1.0000 | 0.9548（资源支援页，同上） | 不排他，见下 |

### 本路线内部（11 张夹具）的对账 —— 比跨库更严的一把尺子

口径写在 ``tests/test_knights_donation.py::EXPECTATIONS``（**表就是断言**，改一处就红）：
它给每个锚点**显式声明**「必须过阈」和「必须不过阈」的夹具集合，两集合并集必须覆盖
全部 11 张 —— 不留「没表态」的格子。

| 锚点 | 阈值 | 正向最低 | 负向最高 | 余量 |
|---|---|---|---|---|
| ``activity_entry`` | 0.80 | **0.9259（有红点那张）** | 0.1563 | +0.7696 |
| ``request_support_button`` | 0.80 | 0.9578（确认框那一帧——**它没盖住右上角**） | 0.3646 | +0.5932 |
| ``support_one_button`` | 0.80 | 0.9360（两按钮那张里较高那个） | 0.5358 | +0.4002 |
| ``points_label`` | 0.80 | 0.9083 | 0.1694 | +0.7389 |
| ``claim_button`` | 0.80 | 1.0000 | 0.6650 | +0.3350 |
| ``popup_title`` | 0.80 | 1.0000 | 0.1900 | +0.8100 |
| ``flower_cell`` | 0.88 | 1.0000 | 0.8279（自己的选中态） | +0.1721 |
| ``flower_cell_selected`` | 0.85 | 1.0000 | 0.7878（自己的未选中态） | +0.2122 |
| ``popup_confirm`` | 0.80 | 1.0000 | 0.0422 | +0.9578 |
| ``reward_title`` | 0.80 | 1.0000 | 0.3203 | +0.6797 |
| ``support_confirm_title`` | 0.80 | 1.0000 | 0.2079（reward_popup） | +0.7921 |
| ``support_confirm_button`` | 0.80 | 1.0000 | 0.2166（weekly_tasks_claimable） | +0.7834 |

⚠️ **``activity_entry`` 余量最薄的地方是「有红点」那张、不是「无红点」那张**：
红点盖在图标左上角，把分数从 1.0000 压到 **0.9259**（对 0.80 只剩 +0.1259）。
11×11 的角标在 75×73 的模板里占 1.4% 的像素、吃掉 7.4% 的分数是正常的 ——
但以后红点若变大或位置上移，这里会**先顶到阈值**。

### 三张「**故意不排他**」的模板：它们只当点击目标

``panel_title`` 与两张页签在**五个活动子页上全部过阈**（panel_title 0.9764~1.0000、
tab_resource_support 0.8195~1.0000、tab_weekly_tasks 0.8464~1.0000）；
``panel_title`` 在确认框那一帧也过阈（0.9720 —— 确认框只盖住中间，左上角标题没被挡）。

- 同一段文字/标题在三个页签页上**本来就在**（页签只有高亮态不同），「排他」在物理上
  不成立，拿 ``min(正向) - max(负向)`` 算余量会得到负数 —— 那不是缺陷。
- 用途只有两处：``panel_title`` 是「活动界面里页签没认出来」的兜底锚点，两张页签是
  点击目标。**都不进 ``_PAGES``**，所以「在多页上命中」不构成串页风险。
- ⚠️ 两张页签是**低对比度**的（蓝底白字）：夹具里最低的是 ``support_page_two_buttons``
  （**0.8195 / 0.8464**），实拍淡入中途的帧上还会掉到 **0.8112 / 0.8194**
  （对 0.80 只剩 +0.011 / +0.019）。好消息是**匹配中心完全没动**：实拍帧上
  两张页签的中心恒为 ``(255,265)`` / ``(255,465)``，与分数无关 ⇒ 分数低的时候是
  「**不肯点**」（``_required`` 失败关闭、安全停止），不是「点错地方」。
  再加主循环有两帧稳定确认，淡入帧本来就不会被拿来发动作。

### 三个「命中是**对的**、不该当成误报」的特例

1. **``activity_entry`` 在别的路线的骑士团主页上必然命中** —— 骑士团主页在
   ``epic7_world_boss`` 组里也有两张夹具（``knights_home.png`` /
   ``knights_home_after_popup.png``），那是同一个页面。扫描表里把它们算进「本路线」。
2. **``reward_title``（「获得奖励」）是游戏通用对话框** —— ``epic7_hero/reward_popup.png``
   上实测 0.9989。跨路线命中不是误报，是同一种控件；真出现也只是被点掉，无副作用。
3. **``tab_resource_support`` / ``tab_weekly_tasks`` 是点击目标、不是页面锚点** ——
   同一段文字在别的页签页上也存在（只是没高亮），详见上面「故意不排他」那一节。

### 阈值

- 统一 ``0.80``；``panel_title`` 取 **0.85**（它在 ``hero/reward_popup`` 上实测
  0.7821，按 0.80 就只剩 0.018，太薄）。
- ``flower_cell`` 取 **0.88**、``flower_cell_selected`` 取 **0.85** ——
  这两张互为对方最强的干扰源（同一格子的两种状态），必须夹在 0.8279 与 0.7878 之上。
- **没有一处是按「凑一个好看的余量」调过阈值的**，除上面两条外全是默认 0.80。
  实测余量最薄的两处（``flower_cell`` +0.1721、``activity_entry`` 有红点那张 +0.1259）
  都在 0.12 以上。

## 角标（亮点）：**颜色 + 形态**判据，不是模板（2026-09-24 实测，2026-09-26 修订）

本路线只用骑士团活动界面里的角标，**颜色不固定**（实测两种都有）：

| 画面 | 角标中心均值（RGB） | 色 | 尺寸/面积/填充率 |
|---|---|---|---|
| 左栏「每周任务」页签左侧 | ≈(19, 72, 176) | **蓝**（H≈102） | 17×17 / 219 / 0.758 |
| 每周任务「骑士团点数」可领档位左上（``weekly_tasks_claimable.png``，可领 500 分） | 同上 | **蓝** | 17×17 / 219 / 0.758 |
| 同上（现场帧 ``…_at_1500.png``，可领 1500 分，2026-09-26 采） | ≈(175, 71, 20) | **橙**（H≈28） | 17×17 / 219 / 0.758 |

⚠️ **2026-09-26 更正**：本文件上一版写「两处角标都是**蓝色**（H≈110）」—— 那只对了老夹具那一张。
同一条判据在现场帧上认到的角标是**橙的**。判据本来就不看色相，所以结论没受影响，
但描述是错的（当时只有一张正向样本，把偶然当成了规律）。

判据仍然**不看色相**（只看「高饱和 + 高亮」），因为别处已经吃过这个亏：
骑士团主页「骑士团活动」图标左上角那颗角标是**橙红**（H≈11），
只按「暖色 + 饱和」判会把它旁边的暖棕色墙（BGR≈(98,60,34)，V≈98，实测该区域有
**16447** 个暖色高饱和像素）一起框进来 —— 所以掩膜取 ``S ≥ 120 且 V ≥ 190``。
⚠️ 那颗主页角标**已不参与任何决策**（用户 2026-09-24 更正：有没有红点都要进），
这里留着它只为了解释「V 为什么卡 190」，别误以为它还在判。

| 帧 | 「每周任务」页签角标区 (78,432,40,40) | 里程碑带 (672,264,1101,50) |
|---|---|---|
| ``weekly_tasks_claimable.png``（可领，500 分） | 1 块 17×17 / 219 | 角标中心 **(1073,286)** |
| ``weekly_tasks_claimable_at_1500.png``（可领，1500 分，2026-09-26 新增） | 1 块 17×17 / 219 | 角标中心 **(1260,286)** |
| ``weekly_tasks_claimed.png``（已领完） | 0 | None |
| 资源支援页五张（``support_page`` / ``_scrolled`` / ``_two_buttons`` / ``_short_material`` / ``support_limit_full``） | 0 | None |
| 骑士团主页两张 / 弹窗三张 | 0 | None |

⇒ 判据走三步：① 掩膜 ``S≥120 & V≥190``（**不看色相**）→ ② 连通块
**面积 ∈ [60, 900]、宽高 ∈ [8, 32]、不贴 ROI 边界** → ③ **填充率（面积 ÷ 外接矩形）≥ 0.60**。

- **面积下限 60** 是必需的：里程碑领完之后原位置会留下 ``字体/宝箱`` 的碎片
  （实测面积 43 / 22 / 50 / 20），不卡就会把「已领」读成「可领」。
- **填充率 0.60（2026-09-26 新增）**也是必需的，而且**是被放宽搜索区逼出来的**：
  搜索区从写死的 50×50 小方块放宽成整条里程碑带之后，**资源支援页第 1 行的
  「持有: 5,133」会落进带子里** —— 它是**绿字**，同样满足「高饱和 + 高亮」，
  面积/宽高也全都过筛（实测 21×21/85、11×21/66、12×21/67）。掩膜分不开它，
  只有形态分得开：**角标是实心圆点（0.758），文字笔画是细线（0.19~0.33）**。
  同一条判据还顺手挡掉了「可领图标自身产生的亮块」（16×14/84 ⇒ 0.375）和
  已领绿✓（15×9/76 ⇒ 0.563，本来靠「贴 ROI 底边」排除，现在是双保险）。
  实测量见 ``docs/maintenance/knights_donation.md`` 的「里程碑档位」一节。

⚠️ **两个搜索区里，真正接进决策的只有 ``milestone`` 一个**（``_at_weekly_tasks``）。
``weekly_tab`` 那个搜索区目前只被 ``tests/test_knights_donation.py`` 守着，状态机没用它
（它和 ``dot_present()`` 一样是**上一版留下的**，见下）—— 不是判据的一部分。

⚠️ ``dot_present()`` 与 ``DOT_ZONES["weekly_tab"]`` 都是**无人调用的历史遗留**
（上一版按「某处有没有红点」决定分支时写的）。按项目约定「不删与本次需求无关的既有代码」，
这里只如实标注，不动它们。

⚠️ 这条判据的**正向样本仍然只有两张**：``weekly_tasks_claimable.png``（500 分档、
角标在**旧位置**）与 ``weekly_tasks_claimable_at_1500.png``（1500 分档、角标在
**带子右半段**，2026-09-26 补）。两张都是同一台模拟器、同一分辨率。换客户端（PC）
或换分辨率时**必须重新采正向样本**，并且**把 7 个档位的角标各采一次**才敢说「整条带子」成立。

## 实拍图回归（2026-09-24 全屏实拍；2026-09-26 补第 10 张）

当天把 ``runtime_logs/knights/*.png``（临时目录，已被清理）与
``docs/manual_review/knights_donation/*.png``（2026-09-24 入库 **9 张**）里的全屏帧逐张过
``observe_page``：

- **0 张认不出**（没有一帧掉进 ``None``）
- **0 张串页**：资源支援 / 每周任务 / 骑士团主页 / 请求支援弹窗 / 获得奖励弹窗，
  全部落在正确页面

其中有 **2 帧已升格成夹具**（``support_page_two_buttons.png`` / ``support_confirm.png``）——
它们是实跑当天现场抓的原始帧，不是按矩形裁出来的：第一版采图**没遇到**「支援资源」
确认框，是实跑才暴露出来的一整页；「一屏两个绿按钮、上面那个吃了没反应」也是实跑实测。

2026-09-26 又补了第 10 张 ``10_weekly_tasks_claimable_at_1500.png``（用户现场帧，
可领档位是 1500）—— 它也原样升格成了夹具
``tests/fixtures/epic7_knights_donation/weekly_tasks_claimable_at_1500.png``
（两张 md5 相同），理由与上一条一致：**实拍全屏帧才是「页面认得出」的证据**。

⇒ 其余夹具是「我按矩形裁出来的、只能证明**夹具**认得出」；实拍全屏帧才是
「**页面**认得出」的证据。持久证据留在 ``docs/manual_review/knights_donation/``。

⚠️ **``activity_panel``（团员商店兜底）在这些实拍帧里一次都没出现过** —— 游戏每次都是从
「资源支援」页签打开活动界面。这个兜底分支目前**只有构造依据、没有实拍证据**：
成立条件是「``panel_title`` 命中 + ``request_support_button`` 与 ``points_label`` 都不命中」，
而 panel_title 在五个子页上都过阈（见上表），所以只要停在别的页签上就会走到它；
它的动作是「点回资源支援页签」，点错也最多是多切一次页签，无副作用。
"""

from pathlib import Path

import cv2
import numpy as np

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)

DEFAULT_THRESHOLD = 0.80

REGIONS = {
    # 骑士团主页左侧「骑士团活动」图标。
    "activity_entry": (20, 470, 150, 140),
    # 骑士团活动面板左上角标题（在活动界面里但页签认不出时的兜底锚点）。
    "panel_title": (60, 140, 300, 90),
    # 左栏两个页签（**只当点击目标**，不进 _PAGES，见模块 docstring）。
    "tab_resource_support": (160, 225, 190, 75),
    "tab_weekly_tasks": (160, 420, 190, 90),
    # 资源支援页右上角「请求支援」按钮：本页排他锚点，也是点击点。
    "request_support_button": (1470, 140, 360, 90),
    # 资源支援列表右侧的绿色「支援1个」按钮；搜索区罩住整列（列表会重排，
    # **绝不能按固定行坐标点**，必须每轮重新认）。
    "support_one_button": (1520, 350, 310, 700),
    # 每周任务页的「骑士团点数」标签 + 当前点数：本页排他锚点。
    "points_label": (450, 280, 340, 110),
    # 每周任务右侧的绿色「领取」按钮；搜索区罩住整列（任务行会随完成情况增删）。
    "claim_button": (1490, 380, 340, 620),
    # 「请求支援」弹窗标题。
    "popup_title": (200, 150, 260, 90),
    # 弹窗网格里「下级精灵之花」那一格：未选中态 / 选中态各一张。
    "flower_cell": (1500, 560, 250, 220),
    "flower_cell_selected": (1500, 560, 250, 220),
    # 弹窗底部绿色「请求支援」按钮。
    "popup_confirm": (1310, 900, 420, 110),
    # 游戏通用「获得奖励」弹窗标题（支援成功、每周任务领奖共用）。
    "reward_title": (830, 250, 260, 100),
    # 「支援资源」确认框（2026-09-24 实跑时新发现的一页：点列表里的「支援1个」
    # 之后**不一定**直接支援 —— 实测团员要的是「稀有狙击催化剂」这类材料时，
    # 会先弹一个「确定要支援以下的资源吗?」的确认框，里面还有一个「支援1个」）。
    "support_confirm_title": (830, 290, 260, 90),
    "support_confirm_button": (940, 780, 360, 130),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}
THRESHOLDS["panel_title"] = 0.85
THRESHOLDS["flower_cell"] = 0.88
THRESHOLDS["flower_cell_selected"] = 0.85

# 没有 PC 客户端的实测数据，就不编一个覆盖值：统一用上表。
PC_THRESHOLD_OVERRIDES: dict[str, float] = {}

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

_PAGES = (
    # ⚠️ 本元组的**顺序即「先判谁」的意图声明**（弹窗在前），但它不是判定顺序的
    # 权威 —— 真正决定 ``observe_page`` 走哪条的是 ``games/epic7/knights_donation.py``
    # 的 ``_PAGE_STATES``（两处必须一致）。``EvidenceProfile.pages`` 的消费方
    # （``page()`` / ``evaluate_pages()`` / 诊断报告）都是按 key 查的，与顺序无关。
    # 两个弹窗必须排在最前：它们盖在底页上，而模板匹配对「压暗」不敏感。
    # 实测奖励弹窗开着时，资源支援页的 request_support_button 掉到 0.3646、
    # 每周任务页的 points_label 掉到 0.4138 —— 都不会串页，但顺序上先判弹窗更稳。
    PageEvidence("knights_donation.reward_popup", required=("reward_title",)),
    PageEvidence(
        "knights_donation.request_popup",
        required=("popup_title",),
        # 标题 + 「花朵格子」两态之一：只认标题的话，任何写着「请求支援」四个字的
        # 地方都会命中（资源支援页自己那个按钮就叫这个名字，只是位置不同）。
        any_of=(("flower_cell", "flower_cell_selected"),),
    ),
    # 「支援资源」确认框：盖在资源支援列表上，所以必须排在 resource_support **之前**。
    PageEvidence("knights_donation.support_confirm", required=("support_confirm_title",)),
    PageEvidence("knights_donation.resource_support", required=("request_support_button",)),
    PageEvidence("knights_donation.weekly_tasks", required=("points_label",)),
    # 兜底：活动界面里但页签没认出来（例如停在「团员商店」上）。
    PageEvidence("knights_donation.activity_panel", required=("panel_title",)),
    # 首页放最后：它的锚点在左栏图标上，活动界面的左栏是页签、不是这个图标，
    # 实测活动各页对 activity_entry 只有 0.14~0.16。
    PageEvidence("knights_donation.guild_home", required=("activity_entry",)),
)

# ⚠️ 这里**故意不放**「页面键 -> 中文名」的对照表：日志用的页面名由
# ``games/epic7/knights_donation.py::STATE_LABELS`` 独家所有，状态机的
# ``source_page`` / ``target_pages`` 全部从它派生（``state_label``）。
# 两处各留一张表迟早会漂移 —— 而主循环的转场对账只做**字符串相等**，
# 一旦漂移就是「转场永远验收不通过」而不是报错。


def build_knights_donation_evidence(template_dir: Path) -> EvidenceProfile:
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


# ---- 角标（红点 / 亮点）：颜色判据 -------------------------------------------------

# 角标（红点 / 亮点）各自的搜索区（基准画布坐标）。
# ⚠️ 骑士团主页「骑士团活动」图标左上角那颗橙红角标**不在表里** —— 用户 2026-09-24 更正
# 「有没有红点都要进」，它已不参与任何决策（实测它 11×11 / 面积 95 @ 中心 (54,510)，
# 只留作 ``activity_entry`` 余量最薄的回归依据，见 ``tests/test_knights_donation.py``）。
DOT_ZONES = {
    # 骑士团活动左栏「每周任务」页签左侧（实测角标 17×17 @ 中心 (97,451)）。
    "weekly_tab": (78, 432, 40, 40),
    # 每周任务页「骑士团点数」进度条上**可领档位的左上角**。
    #
    # ⚠️ 2026-09-26 之前这里是一个写死的 50×50 小方块 ``(1050,264,50,50)``，
    # **只罩得住「500 分」那一档**（角标中心 x≈1073）。用户当天现场帧（1660 分、
    # 可领档位是 **1500**）实测：角标跑到 x=1260，偏出搜索区 160px ⇒ ``find_dot``
    # 返回 None ⇒ 状态机判「每周任务已经没有可领的点数档位」**直接收工**，
    # 1500 那档奖励白丢。现在改成**整条里程碑带**。
    #
    # 左右边界从 7 个档位的角标中心反推（实测方法：量轨道上 7 个白色刻度点的 x =
    # 730/918/1106/1293/1481/1631/1781 → 图标中心 = 刻度 +1 → 角标中心 = 图标中心 − 34）：
    #     697 / 885 / 1073 / 1260 / 1448 / 1598 / 1748
    #   其中第 3 档 1073、第 4 档 1260 有**实测角标**直接对上（老夹具 @500、现场帧 @1500）。
    # ⇒ 左边界 = 697 − 25 = 672，右边界 = 1748 + 25 = 1773（25 = 旧 50 宽方块的半宽余量，同源）。
    # ⚠️ **纵向 (264,50) 不动**：往下扩会把「已领」的绿✓（15×9 / 面积 76 @ y 305~313）
    # 整个框进来 —— 它现在靠「贴 ROI 底边 ⇒ 不算」排除，高度一动这条排除就失效。
    "milestone": (672, 264, 1101, 50),
}

# 掩膜：只看「高饱和 + 高亮」，**不看色相**（橙红与蓝两种角标都要认）。
DOT_SATURATION_MIN = 120
DOT_VALUE_MIN = 190
DOT_MIN_AREA = 60
DOT_MAX_AREA = 900
DOT_MIN_SIZE = 8
DOT_MAX_SIZE = 32
# 形态判据：角标是**实心圆点**，至少要占满外接矩形的一半以上。
# 2026-09-26 放宽搜索区后**必须**加这一条：资源支援页第 1 行的「持有: N」是**绿字**
# （同样高饱和 + 高亮，掩膜分不开），它正好落进里程碑带、面积/宽高也全都过筛。
# 实测（全库 13 张夹具 + 5 张实拍帧，见 docs/maintenance/knights_donation.md）：
#     真角标        17×17 / 面积 219 ⇒ 填充率 **0.758**（两处角标、两张正向样本都是这个值）
#     持有绿字      21×21 / 85 ⇒ 0.193；11×21 / 66 ⇒ 0.286；12×21 / 67 ⇒ 0.266
#     可领图标碎片  16×14 / 84 ⇒ 0.375（角标正下方那一档图标自己的亮块）
#     已领绿✓       15× 9 / 76 ⇒ 0.563（本来靠「贴 ROI 底边」排除，这里是双保险）
# ⇒ 取 0.60：卡在实测最高反例 0.563 与实测正例 0.758 之间（正例余量 +0.158）。
DOT_MIN_FILL_RATIO = 0.60

# 「可领档位」图标相对角标中心的偏移（实测：角标中心 (1073,286) → 图标中心 (1107,318)）。
MILESTONE_ICON_OFFSET = (34, 32)


def _dot_mask(patch: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    return (((hsv[:, :, 1] >= DOT_SATURATION_MIN) & (hsv[:, :, 2] >= DOT_VALUE_MIN)) * 255).astype(
        np.uint8
    )


def find_dot(
    screen: np.ndarray,
    zone: str,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> tuple[int, int] | None:
    """在 ``zone`` 里找角标，返回**角标中心**的画布坐标；没有则 None。

    ``screen`` 必须是 RGB（与 ``runtime.capture()`` / ``load_template`` 同口径）。
    """
    x, y, width, height = DOT_ZONES[zone]
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    x, y = round(x * scale_x), round(y * scale_y)
    width, height = round(width * scale_x), round(height * scale_y)
    patch = screen[y : y + height, x : x + width]
    if patch.size == 0:
        return None
    mask = _dot_mask(patch)
    labels_count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, labels_count):
        blob_x, blob_y, blob_w, blob_h, area = stats[index]
        if not (DOT_MIN_AREA <= area <= DOT_MAX_AREA):
            continue
        if not (DOT_MIN_SIZE <= blob_w <= DOT_MAX_SIZE and DOT_MIN_SIZE <= blob_h <= DOT_MAX_SIZE):
            continue
        # 实心圆点才算法角标：文字笔画是细线，填充率只有 0.19~0.38（见 DOT_MIN_FILL_RATIO）。
        if area / float(blob_w * blob_h) < DOT_MIN_FILL_RATIO:
            continue
        # 贴边的块不算：ROI 边缘切出来的半个块不具备「圆点」的形状证据。
        if blob_x <= 0 or blob_y <= 0:
            continue
        if blob_x + blob_w >= width or blob_y + blob_h >= height:
            continue
        center_x = round(x + centroids[index][0])
        center_y = round(y + centroids[index][1])
        return (center_x, center_y)
    return None


def dot_present(
    screen: np.ndarray,
    zone: str,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> bool:
    return find_dot(screen, zone, reference_size=reference_size) is not None


def milestone_claim_point(dot_center: tuple[int, int]) -> tuple[int, int]:
    """由角标中心推出「可领档位」图标的点击点。

    角标在图标左上角、**不重叠**（角标 x 到 1082 就结束，图标从 1085 起），
    所以直接点角标是点不到图标的 —— 必须按实测偏移挪到图标中心。
    """
    return (
        dot_center[0] + MILESTONE_ICON_OFFSET[0],
        dot_center[1] + MILESTONE_ICON_OFFSET[1],
    )
