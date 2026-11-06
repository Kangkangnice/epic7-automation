"""支线故事：把当前这一期的每一关从头打到尾。

## 这条路线在做什么

支线故事每两周刷新一期，每期要「跑图 + 重复打关卡领奖励」。一期的关卡串在一张
**关卡地图**上（虚线路径 + 若干节点），当前所在节点由角色身上的一枚**发光徽记**
（金色准星环 + 中间青色菱形闪光）标出来。打完一关回到**场景页**，页面上有个
**闪烁的蓝色三箭头**指向下一关；**箭头没了就说明这一期到头了**。

## 复用优先（用户 2026-10-15 明确的开发纪律）

队伍选择 / 准备战斗 / 剧情播放与跳过 / 结算确认 / 通关提示 / 体力弹窗 / 自动战斗
这一段**与主线同页、同长相**，实测分数印证了（`select_team` 0.9639、
`start_mission` 0.9544、`results_confirm` 0.9786）—— 所以整套沿用
`StoryStateMachine` 与 `StoryAction`，本类只在它前面插几种它不认识的页面。

## 独有页面与判据

| 页面 | 判据 | 实测 |
|---|---|---|
| 支线故事页「快速入场」 | 模板 `quick_entry` | 本页 1.0000，其他页面最高 0.4286 |
| Episode 详情页「冒险」 | 模板 `adventure` | 本页 1.0000，其他页面最高 0.5760 |
| 关卡地图 | 模板 `map_panel` | 本页 1.0000，其他页面最高 0.4079 |
| 场景页 | 模板 `replay`（「重新进行」） | 本页 0.8574~1.0000，其他页面最高 0.5475 |
| 场景页的蓝色三箭头 | 区域青色像素量 | 本页 7489~16413；支线故事列表页 1190（低于阈值 3500），其余页面 0 |
| 战斗关 CLEAR | 模板 `battle_clear`（**CLEAR 字标带**）+ **白掩膜口径** + 位置过滤 | 本页 0.9754~1.0000（6 帧、4 种底图）；剧情关 CLEAR 0.2138、其余一切 ≤0.3036 |
| 剧情关 CLEAR | 别名 `story_clear` → 主线 `clear` | 本页 0.9354（同一张模板、同一个区域与阈值、同一个命中点） |
| 「完成故事」弹窗 | 模板 `complete_popup` | 本页 1.0000 / 0.9995 / 0.9995，其余页面最高 0.3204 |

⚠️ 后两条判据**本身都不排他**（表格里那两个非目标命中就是证据），安全性来自
「页面锚点排他 + 决策顺序」：`_arrow_pixels` 只在 `replay` 命中时才读、
`_cursor_point` 只在 `map_panel` 命中时才读。改动决策顺序前先看
`tests/test_epic7_side_story.py::SideStoryJudgementTests`。

## 战斗关 CLEAR 的判据：为什么既换模板、又换口径（2026-10-15 第三次实跑）

**症状**：同一屏（战斗关 CLEAR 页）第二次实跑能认、第三次实跑认不出。两张诊断帧
的分数是 **0.9304** 与 **0.9115**，阈值为 **0.92** —— 差 0.0085 被拒。判据不是
「坏了」，是**间歇的**。

**第一层原因 · 口径**：原来是原样 RGB 比（`TM_CCOEFF_NORMED`），把模板的**底图**
一起算进相似度。CLEAR 横幅的**发光是脉冲动画**，于是同一页在同一台机器上、不同
帧的分数在 0.9115~1.0000 之间漂，阈值正好夹在中间。作者当年把阈值往**上**调到
0.92 去躲「场景页 0.8429 的旁命中」，方向与真阳性相反。

**第二层原因 · 模板**：只换口径还不够 —— 原来的模板裁的是横幅那团**发光**
（330×100 @(665,360)），而发光区**分不开真 CLEAR 与剧情关 CLEAR**：白掩膜下
真 CLEAR 0.9946、剧情 CLEAR 0.9554，只差 0.04。而剧情关 CLEAR 是**必须挡住**的
邻居（`_side_decision` 里 `battle_clear` 判在 `story_clear` 前面）。

⇒ **两样都换**，换成一个可解释的判据：**「CLEAR」字标带**
（装饰线 + 两端小菱形 + 五个字母，345×80 @(795,440)）＋ **白掩膜口径**。
字标才是这张横幅唯一的**静态语义标识**；发光只是动画，底图只是场景。

实测（`_probe_battle_clear_ruler2.py`，全库 456 张）：

| 这一族 | 原样 RGB | **白掩膜** |
|---|---|---|
| 真·战斗结算横幅（13 帧，≥4 种底图） | 0.8197~1.0000 | **0.9398~1.0000** |
| **剧情关 CLEAR**（4 帧，必须挡住） | 0.4614~0.4630 | **0.2133~0.2138** |
| 真实战斗帧 / 技能演出（11 帧） | 0.1523~0.4489 | **0.0000~0.2747** |
| 其余 430 张的天花板 | 0.5353 | **0.3036** |

⇒ 真阳性地板与其余天花板的间隔从 0.28 拉到 **0.64**，且与底图、与发光相位无关。
阈值 0.80 是**在这把新尺子上重扫全库**定出来的（离天花板 0.496、离地板 0.140）。

**这不是新发明**：`core/matcher.py` 顶部的 `MATCH_MODE_WHITE_MASK` 就是为这个病
准备的，月塔的 `auto_off`（`evidence/tower.py`）已经用同一套药方治好过同一个病
（0.7492 → 0.9214）。这里照抄那份写法：口径逐锚点声明，`_locate` 只转发。

## 「完成故事」弹窗：它同时是**判据**和**落点**（2026-10-15 实跑补）

用户实跑死在第一关：CLEAR 点完之后干等 45 秒，报「转场超时 动作=clear
当前已确认页面=完成故事」。诊断帧上 `complete_popup` 命中 0.9995、`next_action`
也正确返回 `close_complete_popup` —— **判据没问题，是契约漏了这个落点**。

`runner_base` 的转场验收是**白名单**（`_confirmed_page ∈ target_pages`），而契约不成立时
主循环**不是**「继续做当前动作」，而是把当前动作置成 `None` 整个丢弃
（`elif last_transition_action is not None:` 那一段）。于是：
弹窗认出来了 → 没人去关 → 等到 `WAIT_RESULTS` 超时 → 退出码 1。

⇒ 两个 CLEAR 动作的落点白名单必须含「完成故事」（`_CLEAR_TARGET_PAGES`）。
⇒ 剧情关 CLEAR 因此**自己接管**（判据仍整个复用主线，只有契约自有）——
把「完成故事」加进**主线**的 `clear` 只会把风险摊到已验证的主线上，收益却一样。


狗粮走的是「特别的时间之书」那颗入口，与本期这条路的「快速入场」不是同一个按钮；
狗粮的 `episode_adventure` 在本期详情页上只有 0.2380（本期按钮左侧多一个卷轴图标、
按钮更宽）⇒ 详情页必须有自己的锚点。

## 两处动态元素为什么不用模板

- **当前角色的光标**：那枚徽记叠在**角色立绘**上，而立绘每个角色、每一期都不同
  ⇒ 模板必然含「会变的内容」。改用**颜色**定位徽记中心那枚**青色菱形**
  （实测 H≈90、S≈136、V=255），它与角色无关 —— 角色蓝甲实测 H≥119、V≈181，
  落不进判据区间；在地图区域内它也是唯一的细长候选（area=288 @ (1180,489)）。
- **蓝色三箭头**：闪烁让亮度大幅波动（同一位置实测从 V=245 掉到 V=70，CLEAR 页
  整幅压暗时只有 V≈73）⇒ 模板匹配会跟着掉分，只能改用**区域青色像素量**。

## 终点

用户 2026-10-15 拍板：「到了本该出现蓝色三箭头的地方，**箭头没了、只剩下重新进行**，
就说明关卡已经到头了」。所以本路线的终止结论是「场景页连续若干帧看不到箭头」。

⚠️ 必须**连续多帧**：箭头是闪烁的，单帧看不见不等于打完了（见 `_ARROW_MISS_LIMIT`）。

⚠️ 而且这几帧的账**只在「提交路径」上记**（`preview` 会还原，见 `_scene_action`）——
所以「认识但这一帧没动作」必须由 `next_action` 自己返回 `None`，
不能推给主线的 `UnrecognizedScreen`，否则主循环不会再提交、这笔账永远数不到 12。

## 开局接力（2026-10-31）

用户原话：「有活动的时候，首页那个入口会被活动顶替掉，所以这条路线不是每次都能导航进去
⇒ 我到时候会自己把故事点进去、停在准备战斗之类的地方，你要能接力」。

### 为什么以前被列为「不能接力」，现在可以了

`RESUME_EXEMPT["side_story"]` 当年写的是：**场景页会被 `battle_scene_visible` 判成「局内」**
（实测 `True`），而 `StoryRunner` 那支「接力落在局内」会**跳过状态机**、直接把这局交给
战斗监督 ⇒ 停在场景页启动就一路磨到绝对超时。

⇒ 解法不是改那个会影响全部 14 条路线的判据，而是**顺序**：本路线的六条自有判据
（含 `replay` 场景页）**全部排在 `battle_scene_visible` 之前**。场景页先被 `replay` 认走，
就永远走不到「局内」那一条。2026-10-31 实测复核：
`scene.png` / `scene_without_arrow.png` 上 `battle_scene_visible=True` 依旧成立（陷阱还在），
而 `replay` 两张都命中；四张真实战斗帧（`epic7_story/battle*.png`）上**当时十二个接力锚点全不命中**
（如今是十四个，新增两颗是 PC-only，模拟器下恒不命中）⇒ 两条路互不遮蔽。

### 落点与状态

顺序见 `_SIDE_RESUME_ORDER`，落点状态**必须拨对**（不能指望第一帧自愈）：
``prepare_battle`` 在 `WAIT_COMPLETE/WAIT_NEXT_STAGE` 下只记轮次不点击；
``_scene_action`` 用「状态不是 `WAIT_NEXT_STAGE`」当「刚打完一关」的闸门 ——
停在场景页接力时正好靠这一条把用户手动打完的那一关计进去（与竞技场的计数口径同源）。

### 刻意不接的页

`通关提示` / `奖励结算` / `额外奖励` / `下一关入口`：它们由主线动作处理，而主线那些动作的
落点白名单写的是**主线**的下一页。本路线在结算之后落到的是场景页 —— 接上去只会把
「落点对不上」这个坑搬进接力。这几页认不出就返回 `None`，回退到
「一路 Back 回大厅再重新导航」，与加接力之前完全一致（失败关闭）。

### 2026-11-06 补：PC 的「期次主页」中间层

12:45 那轮批量里支线故事独立 ✗，12:58:21 日志是
`操作=enter_quick_entry 目标页面=Episode详情/关卡地图` → 12:59:23
`页面=关卡入口 状态=超时无进展`。诊断帧不是这两页中的任何一页，而是
「秘密校兔篇」**期次主页**（左侧本期徽章、右侧「故事 / 奖励 / PV」三颗标签）——
PC 客户端从「快速入场」进来比模拟器多一层中间页。旧代码里：

1. **运行期**：本路线各判据在这页全 `None` ⇒ `UnrecognizedScreen` ⇒ 干等 60 秒超时；
2. **接力**：`detect_resume_point` 的十二个锚点同样全 `None` ⇒ 人手动停在这页启动会退回大厅重走。

两者是**同一个洞**（少认一页），一次补齐：新增两颗 PC-only 可选判据
（`event_home_reward` / `event_home_pv`），既进 `_side_decision` 点「故事」继续前进，
也进 `_SIDE_RESUME_ORDER` 作为接力落点；同时把 `enter_quick_entry` 的 `target_pages`
补上「期次主页」，否则点完「快速入场」明明落对了页，转场契约却判「目标页面未出现」。

⚠️ **PC-only 隔离**：两张图只放 `templates/side_story/pc/`，共享目录里没有同名图。
模拟器下 builder 得到空元组 ⇒ 原子恒 `None` ⇒ 运行期分支与接力落点都不启用，
模拟器行为零改动。这是「平台差异只落在图片上」那条总原则的又一次应用。

⚠️ **未真机复验的两件事**：①点「故事」之后究竟落到哪一页（白名单按前进页列了
4 个，落错会在 4 次重试后带诊断包失败关闭）；②这一页目前只有一张真机帧，
下一期换皮后两颗图还认不认得出。两条都写进 `docs/PC_TEMPLATE_MIGRATION.md` 欠账。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import sleep as default_sleep
from typing import Any, Callable, Optional

import cv2
import numpy as np

from auto_game_unified.core.battle_supervisor import (
    BattleConfig,
    BattleObservation,
    BattleSupervisor,
)
from auto_game_unified.core.matcher import (
    MATCH_MODE_RAW,
    MATCH_MODE_WHITE_MASK,
    Match,
    find_template,
    load_template,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.games.epic7.battle_controls import battle_scene_visible
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.story import (
    StoryAction,
    StoryRunner,
    StoryState,
    StoryStateMachine,
    StoryTemplates,
    build_story_templates,
    state_label,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen


class SideStoryCleared(StaminaExhausted):
    """本期支线故事的关卡已经全部打完。

    与月塔的 ``FloorsConquered`` 同族（都继承 ``StaminaExhausted``，退出码 2「跑完了但
    没得跑了」）：对用户来说这不是失败，是「这一期已经通到底」。走这条出口会让基类
    顺手把游戏带回首页（``_close_out``），不用人工收拾。
    """


# ── 关卡地图上「当前角色的光标」───────────────────────────────────────────────
# 只在地图上找（区域刻意切掉顶部资源栏与底部按钮条，那是 UI 最密集的两条带）。
_CURSOR_REGION = (0, 120, 1982, 840)
# 青色菱形的颜色区间。V 取 230 是因为徽记是「发光」的（实测菱形只有 12x31 像素
# 落在饱和区，外围是浅金色描边）。
_CURSOR_LO = (85, 60, 230)
_CURSOR_HI = (112, 255, 255)
_CURSOR_AREA_MIN = 150
# 菱形是**竖长**的（实测 w/h = 0.55，即 18x33）。这条比例是把它与地图上其他青色
# 小块分开的关键：唯一另一个候选 (1107,274) 实测 28x16、比例 1.75，是横的。
_CURSOR_ASPECT = (0.25, 0.85)
_CURSOR_HEIGHT = (18, 60)

# 菱形中心 → 紫色双剑图标（= 真正要点的位置）的固定下移量。
# 实测 06_map_wait.png：菱形中心 (1180,489)、紫剑中心 (1182,605)，差 (2,116)。
#
# ⚠️ 用户 2026-10-15 明确要求**不要**把紫色双剑放进判据（「这紫色不一定有，你就忽略
# 吧」）—— 所以这里是「往下固定像素」，不是「找到紫剑再点它」。
_CURSOR_CLICK_DY = 116

# ── 场景页的蓝色三箭头 ──────────────────────────────────────────────────────
_ARROW_REGION = (1600, 600, 382, 340)
# 场景页的箭头是亮青白色（实测 HSV≈(90,49,245)）。这里的 S/V 下限刻意低于实测值，
# 是为了容忍它闪烁到偏暗的那几帧（实测最低 41_scene5.png 只有 7489 像素）。
_ARROW_LO = (85, 40, 200)
_ARROW_HI = (100, 255, 255)
_ARROW_PIXELS_MIN = 3500
# 箭头闪烁：单帧看不见不算数。连续这么多帧都看不见才承认「本期打完了」。
# 帧间隔 = Runner 的 poll_seconds(1.0s)，12 帧约 12 秒，足够跨过若干个闪烁周期。
_ARROW_MISS_LIMIT = 12
# 箭头位置在所有场景页上几乎不动（实测 1840/1774/1897，y 749~751）。点它的中心。
_ARROW_CLICK_POINT = (1820, 750)

# 命中中心必须落在这个 x 之后才算数。目前只有 ``battle_clear`` 需要它：
# 旧尺子（横幅发光区 + 原样 RGB）下，场景页也能拿 0.8427（25_after_confirm2.png），
# 而真 CLEAR 页的命中恒在 **(830,410)**、那一处旁命中在 (579,374) —— 横坐标是当时
# 唯一分得开两者的一维（旧阈值 0.92 比那处旁命中高，但比真 CLEAR 里最弱的一张
# 0.8223 也高，两头都夹着，判据是间歇的）。
#
# ⚠️ 换尺子之后（字标带 + 白掩膜，见 `_SIDE_MATCH_MODES`）这一条**不再是防线**：
# 新模板的命中恒在 **(967,480)**，而非 CLEAR 帧的全库天花板只有 0.3036，阈值
# 0.80 自己就挡住了。留着它是第二道 —— 这个判据的误判代价是「在非 CLEAR 页上
# 点 (1820,750)」。**别**因为「阈值已经够了」就删掉它。
_LOCATE_MIN_X = {"battle_clear": 700}

_SIDE_TEMPLATE_NAMES = (
    "quick_entry",
    "adventure",
    "map_panel",
    "replay",
    "battle_clear",
    "complete_popup",
    "next_difficulty",
    "entry_exhausted",
    # ③ 据点：队伍页「可完成1次。」（区分据点队伍页与①/BOSS队伍页）+ 场景页「离开」按钮。
    "outpost_team",
    "outpost_leave",
    # ── 连打链路（2026-11-01）：①→②→③ 一条龙，不再接力 ──
    # 地图节点图标（点了让角色走过去）。「boss_node」= 骷髅徽章（BOSS 独有，城堡+标签
    # 都不能进模板：标签横幅所有节点同形，实测混出 0.60 假阳性）。
    "boss_node",
    "goblin_node",
    # morola 是**双候选**（清晰态 + 雾态），见 SideStoryTemplates 字段注释。
    "morola_node",
    # 地图右下「准备战斗」绿按钮。⚠️ 它**常显**（角色永远站在某个节点上、那节点永远
    # 选中）——只能「点了节点且画面稳定后」点它，见 `_map_navigation_action`。
    "prepare_battle_map",
    # 队伍/辅助英雄准备页左上「返回」（复用主线 navigation/story_back.png，实测 0.999）。
    "story_back",
    # BOSS 首进场：选择辅助英雄页左下「变更」+ 难度列表「中级行」+「选择队伍」。
    # ⚠️ 名字**不能**叫 `select_team` —— 主线已有同名模板（① 选队判据），重名会整条遮蔽。
    "helper_change",
    "diff_mid",
    "boss_select_team",
    # ── 期次主页「故事/奖励/PV」（2026-11-06，PC 专属、可选）──
    # 点了「快速入场」后**先**落到这一页，右侧是三颗标签，不是关卡地图也不是
    # Episode 详情。两张图都是「只放 pc/」的可选模板：模拟器解析不到 ⇒ 空元组
    # ⇒ `_locate` 恒 None，运行期与接力都完全走改动前的路径。
    # 用**两颗**而不是一颗：它们是两枚不同形状的功能标签，本期美术换皮时
    # 只要还有一颗长得一样就能接上；单颗一旦换皮就整页认不出。
    "event_home_reward",
    "event_home_pv",
)

# 判据（模板 + 区域 + 阈值）**整个复用主线那一份**的别名 → 主线锚点名。
#
# 目前只有一项：**剧情关的 CLEAR**。它跟主线是同一页、同一张模板、同一个区域与阈值
# （实测 0.9354），连点击点都一样（命中的中心）。不同的只有**动作契约** ——
# 主线那份只声明「结算确认/通关提示」，而这条支线每关打完都会先弹「完成故事」，
# 落点必须把弹窗页也算进去（见 `_side_decision` 里那段注释）。
#
# ⚠️ 刻意**不**把区域与阈值抄进 `_SIDE_REGIONS` / `_SIDE_THRESHOLDS`：主线那两张表在
# ``__init__`` 里会被**按证据画像重建**（`templates.evidence.atoms`），值跟我们看到的
# 常量未必一致 ⇒ 抄一份就是两个数源，迟早漂。走主线的 `_locate` 永远同步。
_MAINLINE_TEMPLATE_ALIASES = {"story_clear": "clear"}

# 两个 CLEAR 动作共用的落点白名单：「完成故事」弹窗 → 结算确认 → 通关提示。
#
# ⚠️ **少了「完成故事」这一项，整条路线会挂**（2026-10-15 实跑就是这么死的）：
# 主循环的转场验收是 `_transition_completed`（`_confirmed_page` 必须在
# `target_pages` 里），契约不成立时它**不是**「继续做当前动作」，而是
# `runner_base.run()` 里那一段：
#     elif last_transition_action is not None:
#         action = (旧动作 if 已确认页面 == 旧动作来源页 else None)
# 这条支线打完一关先弹「完成故事」⇒ 已确认页面 =「完成故事」≠ 来源页「通关结算」
# ⇒ 当前动作（明明是刚认出来的 `close_complete_popup`）被置成 `None` 整个丢弃，
# 于是弹窗没人关，一路等到 `WAIT_RESULTS` 的 45 秒超时，退出码 1。
# 实测证据：诊断帧上 `complete_popup` 命中 **0.9995**、`next_action` 也返回
# `close_complete_popup`，但日志里从 CLEAR 点击到超时之间**一个动作都没有**。
_CLEAR_TARGET_PAGES = ("完成故事", "结算确认", "通关提示")

# 「完成故事」弹窗里「点击关闭」那一行所在的位置（实测 14/23/31 三张弹窗帧一致）。
# 弹窗是模态遮罩，点它身上任何地方都会关掉，取这一行只是为了让日志里的坐标有出处。
_POPUP_CLOSE_POINT = (990, 790)

# 期次主页「故事」金色相框的**文字中心**（2026-11-06 12:59 真机帧实测）。
# 相框本体约 x 1580~1920 / y 250~700，点文字中心一定落在按钮里；不用 `_locate`
# 的命中点，是因为两张判据图裁的是「奖励」「PV」，不是这颗「故事」按钮。
_EVENT_HOME_STORY_POINT = (1710, 440)

# 「故事」点下去的落点白名单。**刻意不含「期次主页」与「支线故事」**：
# 含前者会让「点了没反应」被当成转场成功（静默降级）；含后者会在
# 期次主页 ↔ hub 页之间来回点，直到 99 轮耗尽。真落在没登记的前进页上，
# 转场契约会在 4 次重试后带诊断包失败关闭 —— 比 60 秒无声超时好排查。
_EVENT_HOME_TARGET_PAGES = (
    "Episode详情",
    "关卡地图",
    "关卡入口",
    "剧情关卡入口",
)

# 本路线独有的区域 / 阈值（早期六条自有页 + 连打链路 + PC 期次主页）。
# 提成模块常量而不是直接写在类体里，是因为
# ``__init__`` 还要再用一次（理由见那里）。
_SIDE_REGIONS = {
    "quick_entry": (100, 950, 520, 182),
    "adventure": (1340, 950, 642, 182),
    "map_panel": (1740, 220, 242, 372),
    "replay": (1600, 960, 382, 172),
    "battle_clear": (400, 200, 1000, 500),
    "complete_popup": (600, 150, 800, 400),
    # 「下一个难度」在右下角按钮条里（实测命中中心 (1767,943)）。区域罩住整条右下按钮带。
    "next_difficulty": (1500, 860, 482, 170),
    # 「可入场次数已全部耗尽。」气泡：右下角白色圆角条，实测命中中心 (1672,930)。
    # 区域罩住整条右下按钮带上方那一段（含数字「0/5」与句子）。
    "entry_exhausted": (1450, 870, 490, 130),
    # ③ 据点队伍页「可完成1次。」白气泡：战斗开始按钮上方，实测命中中心 (1660,934)。
    # 区域罩住右下按钮带上方那一段（不含左侧任务栏、不含顶部敌人栏）。
    "outpost_team": (1400, 850, 582, 282),
    # ③ 据点场景页「离开」按钮：左下棕色圆角按钮（左箭头+「离开」），实测命中中心 (170,1047)。
    # 区域罩住整条左下按钮带（离开/大厅）。⚠️ ①/BOSS 场景页也有「离开」按钮、同一位置也会命中，
    # 但本判据只在 `_in_outpost` 模式下使用（见 `_side_decision`），不会误触①。
    "outpost_leave": (40, 960, 320, 172),
    # ── 连打链路 ── 地图节点区域 = 整个地图视野（不含顶部 HUD y<90 与右侧任务栏 x>1740）。
    # ⚠️ 必须给大区域：视角会平移（相机跟角色走），节点可能出现在视野任何位置；
    #    默认视角下 goblin 中心 y≈62、大半被顶部 HUD 挡住 ⇒ 平移后才能匹配到。
    "boss_node": (0, 90, 1740, 900),
    "goblin_node": (0, 90, 1740, 900),
    "morola_node": (0, 90, 1740, 900),
    # 地图右下「准备战斗」绿按钮，固定位命中中心 (1572,1035)。
    "prepare_battle_map": (1400, 980, 560, 152),
    # 「返回」左上角，实测命中中心 (56,98)。
    "story_back": (0, 30, 260, 150),
    # 「变更」在两个页面位置都出现（helper 视图左下 (155,1070) / 列表视图中下 (1207,1068)）
    # ⇒ 区域罩整条底部按钮带；用命中点的 x 坐标区分是哪个视图（<400 = helper 视图）。
    "helper_change": (0, 1000, 1982, 132),
    # 难度列表左侧四行的「盾牌+档位名」文字区（中级行实测命中中心 (164,547)）。
    "diff_mid": (40, 250, 320, 860),
    # 难度列表/helper 页右下「选择队伍」绿按钮，实测命中中心 (1695,1070)。
    "boss_select_team": (1400, 1000, 560, 132),
    # ── 期次主页右侧标签栏（2026-11-06 12:59 真机帧）──
    # 两颗各自罩住自己那一枚标签的**常驻位置**，刻意不共用一大片搜索区：
    # 共用 (1380,640,602,400) 时「奖励」纸带能滑到别页的白色横条上，
    # 全库负例天花板从 0.4285 抬到 0.5808（outpost_scene.png），余量白白丢掉 0.15。
    "event_home_reward": (1380, 640, 602, 220),
    "event_home_pv": (1380, 780, 602, 220),
}
_SIDE_THRESHOLDS = {
    "quick_entry": 0.82,
    "adventure": 0.82,
    "map_panel": 0.82,
    "replay": 0.82,
    # ⚠️ 0.80 是**在新尺子上重新扫全库**定出来的（`_probe_battle_clear_ruler2.py`，
    # 全库 456 张），不是把旧值搬过来 —— 旧值 0.92 在两个意义上都是错的：
    #   * 它比真阳性里最弱的一张（0.9115，第三次实跑诊断帧）还高 ⇒ 判据间歇失效；
    #   * 它配的那张模板（横幅发光区）根本**分不开**真 CLEAR 与剧情关 CLEAR。
    # 实测（新模板 = 字标带 + 白掩膜口径）：
    #   * 真·战斗结算横幅（13 帧，跨 4 种以上底图）…………… 0.9398 ~ 1.0000
    #       · 本路线自己那 6 帧更稳：0.9754 ~ 1.0000
    #   * **剧情关 CLEAR**（必须挡住，`_side_decision` 里它排在后面）… 0.2133 ~ 0.2138
    #   * 真实战斗帧 / 技能演出帧 …………………………………… 0.0000 ~ 0.2747
    #   * 其余 400+ 张全库画面的天花板 …………………………… 0.3036（月塔楼层列表）
    # ⇒ 0.80 离天花板 0.496、离真阳性地板 0.140，两边都宽。偏向命中侧取低：
    #   这里漏判的代价是整条路线卡死 45 秒，误判的代价是点错一次 —— 前者大得多。
    "battle_clear": 0.80,
    # 弹窗标题在 3 张实拍帧上是 1.0000 / 0.9995 / 0.9995，其余页面最高 0.3204。
    "complete_popup": 0.82,
    # 白掩膜口径：本页 1.0000，负例最高 0.4262（普通场景页 / 无箭头场景页 / 地图 /
    # 支线故事页 / 战斗 CLEAR）。0.60 离负例 0.17、离真阳性 0.40。
    "next_difficulty": 0.60,
    # 「可入场次数已全部耗尽。」：原样 RGB 口径（白底深字，气泡本身高对比，足够特异）。
    # 真阳性 1.0000（摩罗戈拉 0/1 自匹配）/ 0.945（用户地狱级 0/5 截图，跨来源一致）；
    # 负例全库最高 < 0.5（可打态队伍页 / BOSS 各页 / 普通场景页 / 地图 / 据点场景页
    # 全部 no-match@0.5）。0.60 离负例 0.10、离真阳性 0.35。② BOSS 地狱级终点与
    # ③ 据点终点**通用**：这一句出现即「次数用尽」，本路线收工。
    "entry_exhausted": 0.60,
    # ③ 据点队伍页「可完成1次。」：原样 RGB。真阳性 1.0000（哥布林据点队伍页 03_team_ready）；
    # 负例 ① 队伍页 team.png / 选择队伍页 02_team 均 no-match@0.6。0.70 离天花板余量充足
    # （已知负例全 < 0.6）。⚠️ 阈值 0.70 先按经验填，未跑全库负例扫描复核。
    "outpost_team": 0.70,
    # ③ 据点场景页「离开」按钮：原样 RGB。真阳性 1.0000（哥布林据点场景页 05_after_confirm）；
    # ① 场景页 scene.png 同样命中 0.9577（同一按钮、同一位置，符合预期），
    # 但本判据只在 `_in_outpost` 模式下使用，故 ① 误触不构成风险。0.70 余量充足。
    "outpost_leave": 0.70,
    # ── 连打链路（2026-11-01，全库 828 帧扫描定阈，D:/anaconda 跑 `_scan_nodes.py`）──
    # boss_node（骷髅徽章 56x74）：正例 13 张地图帧全 ≥0.969（含角色站节点上的遮挡态
    # 0.973 —— 角色站左、徽章在右，不挡）；定向负例（哥布林节点位置）<0.4。
    # 0.80 离地板 0.169、离天花板 0.4+。⚠️ 只在 map_panel 已确认 + 非①段时使用（双门控）。
    "boss_node": 0.80,
    # goblin_node（90x90）：清晰态 0.942~1.000；负例全库 ≤0.71（月塔/社区 0.638、
    # 旧支线帧 0.699）。0.80 离地板 0.142、离天花板 0.09。
    "goblin_node": 0.80,
    # morola_node（双候选，任一过阈即可）：清晰态候选在雾态帧只有 0.574（负例天花板
    # 0.638 反超 ⇒ 单候选不可行）；补雾态候选（裁自 14_map）后 13 张地图帧全 0.965~1.000。
    # 0.80 离地板 0.165。
    "morola_node": 0.80,
    # prepare_battle_map（285x80）：13 张地图帧 0.939~1.000，固定位 (1572,1035)。
    # ⚠️ 它**常显**，阈值高不高都不解决「什么时候该点」——那由 `_node_clicked`+画面
    # 稳定门控负责；0.85 只是把「别把别的绿按钮当它」兜住（team 页 no-match）。
    "prepare_battle_map": 0.85,
    # story_back（复用主线 navigation/story_back.png）：队伍准备/辅助英雄/次数用尽准备页
    # 全 0.999 @ (56,98)。0.85 余量充足。
    "story_back": 0.85,
    # helper_change（250x90）：helper 视图 1.000、列表视图 0.948~0.986；team 页 no-match。
    "helper_change": 0.85,
    # diff_mid（中级行文字区 170x75）：难度列表页 0.991~1.000（初级选中态/中级选中态都验过）；
    # helper 页左中「中级」大字误中 0.858 ⇒ 阈值 0.90 隔开，且行点击只在列表子状态触发（双保险）。
    "diff_mid": 0.90,
    # boss_select_team（500x90）：列表页 0.970~1.000、helper 页 0.948；team 页/地图 no-match。
    "boss_select_team": 0.85,
    # ── 期次主页两颗标签（2026-11-06，原样 RGB）──
    # 全库负例扫描 `runtime_logs/_probe_event_home_anchor.py`（366 张可判帧，
    # 含 **5 张同期美术的支线故事 hub 页** —— 同一套立绘/背景、右侧却是菜单，
    # 是这套判据最硬的负例）：
    #   event_home_reward（420x105 白色「奖励」纸带）…… 正例 1.0000 / 负例 Top1 0.4285
    #   event_home_pv（220x130 黑色「PV」胶片条）……… 正例 1.0000 / 负例 Top1 0.5288
    #   同期 hub 页天花板：0.3668 / 0.3629（证明靠的是标签控件，不是本期背景）
    # 0.80 离负例天花板 0.27、离正例 0.20，两边都留得下。
    # ⚠️ 这一页目前**只有一张真机帧**（12:59 timeout_stage），单帧的自匹配 1.0000
    # 不等于跨帧稳健；两张图来自同一帧，能否扛住下一期换皮尚未验证。认不出是
    # **失败关闭**（返回 None ⇒ 回大厅重新导航），不会瞎点。
    "event_home_reward": 0.80,
    "event_home_pv": 0.80,
}

# 判据 → 比对口径。只有 `battle_clear` 走背景无关口径；其余锚点仍是原样 RGB。
#
# 为什么要给它换尺子（2026-10-15 第三次实跑）：原样 RGB 比（`TM_CCOEFF_NORMED`）
# 把模板的**底图**一起算进相似度，而 CLEAR 横幅的**发光是脉冲动画** —— 同一页在
# 同一台机器上，不同帧的分数能从 0.9115 漂到 1.0000，阈值正好夹在中间 ⇒ 判据
# **间歇失效**（第二次实跑认出、第三次认不出，同一屏）。
#
# 白掩膜口径（两侧先二值化成「哪些像素是白的」再比）把底图与发光一起抹平。
# **同一套药方月塔已经吃过一次**（`evidence/tower.py` 的 `auto_off`：0.7492 → 0.9214），
# 这里沿用，不再另造。
#
# 实测（`_probe_battle_clear_ruler2.py`，全库 456 张；模板 = 字标带）：
#
#   ==============================  ==============  ===========
#   这一族                           原样 RGB        白掩膜
#   ==============================  ==============  ===========
#   真·战斗结算横幅（13 帧）           0.8197~1.0000   0.9398~1.0000
#   **剧情关 CLEAR**（4 帧）          0.4614~0.4630   0.2133~0.2138
#   真实战斗帧 / 技能演出（11 帧）      0.1523~0.4489   0.0000~0.2747
#   其余 430 张的天花板               0.5353          0.3036
#   ==============================  ==============  ===========
#
# 白掩膜把「真阳性地板 / 其余天花板」的间隔从 0.28 拉到 **0.64**，而且与底图无关。
# ⚠️ 这一份**同时**是 `SideStoryStateMachine._MATCH_MODES` 指的对象（同一份，不是
# 抄一份）—— 判据只有一处实现，诊断脚本与真机走的是同一把尺子。
# ⚠️ 换口径**必须同时重定阈值**（见 `_SIDE_THRESHOLDS` 里那一档的来历）。
# ⚠️ 口径与模板是**一对**：旧模板（横幅发光区）配白掩膜也分不开剧情关 CLEAR
# （实测 0.9946 对 0.9554），换口径不换模板只解决了一半问题。
_SIDE_MATCH_MODES: dict[str, str] = {
    "battle_clear": MATCH_MODE_WHITE_MASK,
    "next_difficulty": MATCH_MODE_WHITE_MASK,
}


# ── 连打链路的段落账本（2026-11-01）─────────────────────────────────────────
# 用户口径：①正常关卡打完 → ②BOSS 难度阶梯（地狱级 ×5）→ ③两个一次性据点 → 收工，
# **一条运行内连起来**，段与段之间不再要求用户手动导航。
#
# 段的推进点（全部发生在「有明确证据的动作」上，不靠猜）：
#   ①→②  场景页连续 12 帧无箭头（= ① 打完）⇒ 点「离开」回地图，段落切到 _SEG_BOSS；
#   ②→③  队伍准备页「可入场次数已全部耗尽。」⇒ 点「返回」→ 地狱级场景页点「离开」，
#         段落切到 _SEG_OUTPOST_1（不再就地收工——这是对旧语义的**有意更改**）；
#   ③a→③b 据点场景页点「离开」⇒ 段落切到 _SEG_OUTPOST_2；
#   ③b→收工 最后一个据点点「离开」回地图 ⇒ ``SideStoryCleared``。
_SEG_NORMAL = 0
_SEG_BOSS = 1
_SEG_OUTPOST_1 = 2
_SEG_OUTPOST_2 = 3
_SEG_LABELS = {
    _SEG_NORMAL: "①正常关卡",
    _SEG_BOSS: "②BOSS阶梯",
    _SEG_OUTPOST_1: "③哥布林据点",
    _SEG_OUTPOST_2: "③摩罗戈拉据点",
}
# 段 → 地图上要点的节点图标模板。
_NODE_TEMPLATES = {
    _SEG_BOSS: "boss_node",
    _SEG_OUTPOST_1: "goblin_node",
    _SEG_OUTPOST_2: "morola_node",
}
# 视角平移扫寻序列（找不到目标节点时的拖动增量，手指拖动方向 = 内容跟随方向：
# 往下拖 (+y) 露出上面的地图）。整轮净位移为 0，扫完回到出发点附近；
# 上限 _PAN_LIMIT 次，找不到大不了原地等状态超时兜底（fail-closed，绝不瞎点）。
_PAN_SWEEPS: tuple[tuple[int, int], ...] = (
    (0, 340),    # 往下拖 → 露出上方（goblin 在默认视角被顶部 HUD 挡住，最先试这个）
    (0, -680),   # 拉回并越过
    (420, 0),    # 往右拖 → 露出左侧（morola 偏左）
    (-840, 0),   # 拉回并越过
    (0, 680),
    (0, -340),
)
_PAN_LIMIT = 6
_PAN_START = (990, 560)     # 滑动起点（屏幕中部地图区）
_PAN_DURATION_MS = 600
# 「走路结束」判定：地图中部内容区连续 2 帧几乎不变（角色/旗帜的待机动画按容忍度豁免）。
_SETTLE_REGION = (400, 200, 1100, 600)
_SETTLE_CHANGED_MAX = (_SETTLE_REGION[2] * _SETTLE_REGION[3]) // 10
_SETTLE_STREAK_NEED = 2


@dataclass(frozen=True)
class SideStoryTemplates:
    """支线故事模板：主线那一整套 + 本路线自己的五张。

    ⚠️ 主线模板**按对象复用**而不是重新加载一遍：``StoryTemplates`` 里带着
    ``quick_battle`` 检测器与证据画像，重建一份等于把那套东西再预热一次，
    还可能悄悄分叉。
    """

    story: StoryTemplates
    quick_entry: np.ndarray
    adventure: np.ndarray
    map_panel: np.ndarray
    replay: np.ndarray
    # ⚠️ 裁的是 **「CLEAR」字标带**（装饰线 + 两端小菱形 + 五个字母，345x80 @(795,440)），
    # **不是**横幅那团发光。原先把整个「发光区」当模板，等于把两样会变的东西装进判据：
    # ① 场景底图；② 发光脉冲动画的相位。字标才是这张横幅唯一**静态**的语义标识。
    battle_clear: np.ndarray
    complete_popup: np.ndarray
    # BOSS 打完那一屏的「下一个难度」。**必须排在 `replay` 之前判**：
    # 那一页同时有「重新进行」且没有蓝箭头，先判 replay 会走成「本期打完」（见模块头）。
    next_difficulty: np.ndarray
    # 「可入场次数已全部耗尽。」气泡（队伍准备页，次数用尽时）。
    # ② BOSS 地狱级打满、③ 据点次数用完，都会出现这一句 —— 出现即本路线收工。
    entry_exhausted: np.ndarray
    # ③ 据点：队伍页「可完成1次。」白气泡（区分据点队伍页与①/BOSS队伍页）。
    outpost_team: np.ndarray
    # ③ 据点：场景页左下「离开」按钮（打完后离开回地图，不进箭头逻辑/不误判收工）。
    outpost_leave: np.ndarray
    # ── 连打链路 ──
    # BOSS 节点的**骷髅徽章**（56x74）。⚠️ 只裁徽章：城堡主体会被角色遮挡（实测掉到
    # 0.60），红标签横幅所有节点同形（混出 0.60 假阳性）；徽章 BOSS 独有、遮挡态仍 0.973。
    boss_node: np.ndarray
    # 哥布林据点节点图标（营地图标 90x90）。
    goblin_node: np.ndarray
    # 摩罗戈拉据点节点图标，**双候选**：清晰态（probe 帧）+ 雾态（14_map 帧）。
    # 单候选跨帧只有 0.574、被负例 0.638 反超；双候选后 13 张地图帧全 0.965~1.000。
    morola_node: tuple[np.ndarray, ...]
    # 地图右下「准备战斗」绿按钮。**常显**（角色永远站在某节点上），只在
    # 「已点目标节点 + 画面稳定」后由 `_map_navigation_action` 使用。
    prepare_battle_map: np.ndarray
    # 准备页左上「返回」（复用主线 navigation/story_back.png，不复制文件）。
    story_back: np.ndarray
    # BOSS 首进场三件套：helper 页左下「变更」/ 难度列表「中级行」/ 右下「选择队伍」。
    helper_change: np.ndarray
    diff_mid: np.ndarray
    boss_select_team: np.ndarray
    # ── 期次主页（2026-11-06，PC 专属可选）──
    # 空元组 = 模拟器（共享目录里没有这两张图）⇒ `_locate` 直接返回 None，
    # 运行期动作与接力落点都自动不启用，模拟器行为一个字节不变。
    # 两张都是**固定功能标签**：白色「奖励」纸带（420x105）、黑色「PV」胶片条
    # （220x130）。不裁「秘密校兔篇」徽章 / 期间日期 / 玩家上电视的跑马灯 ——
    # 那些每期、每时每刻都变，装进模板等于把会变的内容写进判据。
    event_home_reward: tuple[np.ndarray, ...]
    event_home_pv: tuple[np.ndarray, ...]


def build_side_story_templates(template_dir: Path) -> SideStoryTemplates:
    """构建支线故事模板。

    ``template_dir`` 是 ``templates/side_story``；主线模板在它的兄弟目录
    ``templates/story``（与 ``build_fodder_templates`` 同一形状）。
    """

    root = template_dir.parent

    def load_optional(name: str) -> tuple[np.ndarray, ...]:
        """PC 专属可选图：文件不在就返回空元组，不抛 FileNotFoundError。

        与 `labyrinth_stone.build_labyrinth_stone_templates` 同一套写法 ——
        模拟器传的是普通 `Path`（或 `TemplateDir(..., "emulator")`），
        `pc/` 里的图解析不到，这一族判据必须整个缺席而不是崩在加载期。
        """
        path = template_dir / f"{name}.png"
        return (load_template(str(path)),) if Path(path).is_file() else ()

    return SideStoryTemplates(
        story=build_story_templates(root / "story"),
        quick_entry=load_template(str(template_dir / "quick_entry.png")),
        adventure=load_template(str(template_dir / "adventure.png")),
        map_panel=load_template(str(template_dir / "map_panel.png")),
        replay=load_template(str(template_dir / "replay.png")),
        battle_clear=load_template(str(template_dir / "battle_clear.png")),
        complete_popup=load_template(str(template_dir / "complete_popup.png")),
        next_difficulty=load_template(str(template_dir / "next_difficulty.png")),
        entry_exhausted=load_template(str(template_dir / "entry_exhausted.png")),
        outpost_team=load_template(str(template_dir / "outpost_team.png")),
        outpost_leave=load_template(str(template_dir / "outpost_leave.png")),
        boss_node=load_template(str(template_dir / "boss_node.png")),
        goblin_node=load_template(str(template_dir / "goblin_node.png")),
        morola_node=(
            load_template(str(template_dir / "morola_node.png")),
            load_template(str(template_dir / "morola_node_foggy.png")),
        ),
        prepare_battle_map=load_template(str(template_dir / "prepare_battle_map.png")),
        # 返回键**复用主线 navigation 的模板文件**（实测 0.999），不复制第二份。
        story_back=load_template(str(root / "navigation" / "story_back.png")),
        helper_change=load_template(str(template_dir / "helper_change.png")),
        diff_mid=load_template(str(template_dir / "diff_mid.png")),
        boss_select_team=load_template(str(template_dir / "boss_select_team.png")),
        event_home_reward=load_optional("event_home_reward"),
        event_home_pv=load_optional("event_home_pv"),
    )


def _cyan_components(
    screen: np.ndarray,
    region: tuple[int, int, int, int],
    lo: tuple[int, int, int],
    hi: tuple[int, int, int],
    area_min: int,
) -> list[tuple[int, tuple[int, int], tuple[int, int, int, int]]]:
    """在区域里找青色连通域，返回 (面积, 中心, 外接框)，按面积降序。

    ``screen`` 是 **RGB**（与 ``core.window`` 的取图约定一致），本函数自己转 HSV。
    区域是**参考尺寸**下的坐标，按画面实际大小缩放（与 ``_locate`` 同一套换算）。
    """

    scale_x = screen.shape[1] / 1982
    scale_y = screen.shape[0] / 1132
    ref_x, ref_y, ref_width, ref_height = region
    x = round(ref_x * scale_x)
    y = round(ref_y * scale_y)
    width = round(ref_width * scale_x)
    height = round(ref_height * scale_y)
    hsv = cv2.cvtColor(screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    found = []
    for index in range(1, count):
        area = int(stats[index, 4])
        if area < area_min:
            continue
        box = tuple(int(value) for value in stats[index, :4])
        center = (int(centroids[index][0]) + x, int(centroids[index][1]) + y)
        found.append((area, center, (box[0] + x, box[1] + y, box[2], box[3])))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


class SideStoryStateMachine(StoryStateMachine):
    """支线故事：在主线状态机前面补上三种它不认识的页面。

    继承而不是重写，是因为除了下面这三个页面，其余每一步（队伍选择 / 准备战斗 /
    剧情 / 结算 / 通关提示 / 体力）都与主线**同页同长相**，重写一遍就是重新造轮子。
    """

    # 主线的区域/阈值表 + 本路线自己的六条。类属性这份只为「类级别看一眼」，
    # 真正生效的是 ``__init__`` 里合并出来的实例属性（理由见那里）。
    _REGIONS = {**StoryStateMachine._REGIONS, **_SIDE_REGIONS}
    _THRESHOLDS = {**StoryStateMachine._THRESHOLDS, **_SIDE_THRESHOLDS}
    # 比对口径表。它不是「合并」出来的 —— 主线的 `_locate` 自己查自己的表，
    # 这张只在**本路线自己那六条**上生效，所以直接引用同一份模块常量。
    _MATCH_MODES = _SIDE_MATCH_MODES

    def __init__(
        self,
        templates: SideStoryTemplates,
        initial_state: StoryState = StoryState.STAGE,
    ) -> None:
        super().__init__(templates.story, initial_state=initial_state)
        self.side = templates
        # ⚠️ 主线状态机的 ``__init__`` 会把 ``_REGIONS`` / ``_THRESHOLDS`` **换成实例属性**
        # （它要按证据画像重建一份），于是类属性上合并进去的那六条在实例上根本看不见 ——
        # 不在这里再合并一次，``_locate("complete_popup")`` 会直接 KeyError。
        # 两边都写在 ``_SIDE_REGIONS`` / ``_SIDE_THRESHOLDS`` 这一份来源上，不会漂。
        self._REGIONS = {**self._REGIONS, **_SIDE_REGIONS}
        self._THRESHOLDS = {**self._THRESHOLDS, **_SIDE_THRESHOLDS}
        # 「连着多少帧没看到蓝箭头」的账本。只在场景页上累加（见 ``_scene_action``），
        # 离开场景页立刻清零 —— 否则跨关卡会把两次无关的缺失连成一次收工。
        self._arrow_misses = 0
        # ── BOSS 难度阶梯账本（②）──
        # ``_boss_advances``：已经点过几次「下一个难度」。中级→上级→地狱级最多推进
        # 2 次（中级是第 1 次进场就打的那一档，不算推进），到 2 即站上地狱级。
        # 之后地狱级场景页改走「重新进行」，终点由 ``entry_exhausted`` 文案判定
        # （见 ``_side_decision``），不在这里数次数。普通关卡（①）永远停在 0，
        # 不会污染 ① 的箭头收工逻辑。
        self._boss_advances = 0
        # ── 据点（③）状态账本 ──
        # ``_in_outpost``：当前是否处在「据点战斗中」（由据点队伍页的「可完成1次。」
        # 置位）。据点场景页与普通①「打完」场景页**长得一模一样**（都有离开/大厅/
        # 重新进行、都没箭头、都没「下一个难度」），纯页面识别分不出两者 ⇒ 必须靠
        # 这个状态位：置位后场景页才点「离开」回地图，否则走①的箭头收工逻辑。
        self._in_outpost = False
        # ── 连打链路账本（①→②→③ 一条龙）──
        # ``_segment``：当前跑到哪一段（见模块常量 ``_SEG_*``），决定地图上要点哪个
        # 节点、终点怎么判。只在「有明确证据的动作」上推进，不靠猜。
        self._segment = _SEG_NORMAL
        # ``_leaving``：场景页已点「离开」、正在等回地图（①打完 / BOSS打满 / 据点通用）。
        self._leaving = False
        # ``_boss_done``：② 已打满（entry_exhausted 命中），正走在「返回 → 场景页
        # 「离开」→ 地图」的退场路上；回到地图即切 ③。
        self._boss_done = False
        # ``_final_leave``：最后一个据点已点「离开」，回地图即抛 SideStoryCleared。
        self._final_leave = False
        # ``_node_clicked``：已点目标节点图标，角色正在走过去；期间**绝不点
        # 「准备战斗」**（它常显、指向的还是旧节点）。
        self._node_clicked = False
        # ``_pan_attempts``：视角平移扫寻已用次数（有界，见 _PAN_SWEEPS）。
        self._pan_attempts = 0
        # ``_boss_entered``：② 首进场的难度选择（变更→中级行→选择队伍）是否已完成；
        # 完成后 helper 页交还主线（粘性档位已被「下一个难度」推到正确档）。
        self._boss_entered = False
        # ``_boss_row_clicked``：难度列表里中级行已点过（同页停留，下一拍点「选择队伍」）。
        self._boss_row_clicked = False
        # ``_prev_screen`` / ``_settle_streak``：走路结束判定（连续稳定帧）用的上一帧。
        self._prev_screen: np.ndarray | None = None
        self._settle_streak = 0

    # ── 判据 ────────────────────────────────────────────────────────────────

    def _locate(self, screen: np.ndarray, name: str, threshold: float | None = None):
        """支线模板走自己的表（支持多条候选 + 位置过滤），其余原样交给主线。"""

        alias = _MAINLINE_TEMPLATE_ALIASES.get(name)
        if alias is not None:
            # 判据整个复用主线那一份（模板 / 区域 / 阈值 / 命中点）。这里**不能**多传
            # threshold —— 主线的 `_locate` 没有这个形参。理由见上面的常量注释。
            return super()._locate(screen, alias)
        if name in _SIDE_TEMPLATE_NAMES:
            templates = getattr(self.side, name)
            if isinstance(templates, np.ndarray):
                templates = (templates,)
            need = threshold or self._THRESHOLDS[name]
            min_x = _LOCATE_MIN_X.get(name, 0)
            # 比对口径逐锚点声明（`battle_clear` 是背景无关的白掩膜，其余是原样 RGB）。
            # 这里**只转发**，不在路线里复刻预处理 —— 复刻就是把同一个判据抄成两份，
            # 而「判据被人抄了第二份、改的那份生产走不到」正是这个项目的典型死法。
            mode = self._MATCH_MODES.get(name, MATCH_MODE_RAW)
            best = None
            for template in templates:
                match = find_template(
                    screen,
                    template,
                    need,
                    region=self._REGIONS[name],
                    reference_size=self._REFERENCE_SIZE,
                    mode=mode,
                )
                if match is None or match.center[0] < min_x:
                    continue
                if best is None or match.score > best.score:
                    best = match
            return best
        # ⚠️ 主线的 ``_locate`` 签名是 ``(screen, name)``，**没有** threshold 形参
        # （它自己按 ``_THRESHOLDS`` 查表）。多传一个会 TypeError，而那些帧正好是
        # 队伍/剧情/结算这些「委托给主线」的页面 —— 整条路线会在第一关之后就散架。
        return super()._locate(screen, name)

    def _cursor_point(self, screen: np.ndarray) -> Optional[tuple[int, int]]:
        """关卡地图上「当前角色的光标」——返回**要点的位置**（不是光标本身）。

        只在**竖长**的青色候选里挑（见 ``_CURSOR_ASPECT``），命中后往下推
        ``_CURSOR_CLICK_DY`` 像素：那里是这颗节点上的紫色双剑图标，
        也就是用户说的「点光标下方」。
        """

        for _area, center, box in _cyan_components(
            screen, _CURSOR_REGION, _CURSOR_LO, _CURSOR_HI, _CURSOR_AREA_MIN
        ):
            width, height = box[2], box[3]
            if height <= 0:
                continue
            ratio = width / height
            if not (_CURSOR_ASPECT[0] <= ratio <= _CURSOR_ASPECT[1]):
                continue
            if not (_CURSOR_HEIGHT[0] <= height <= _CURSOR_HEIGHT[1]):
                continue
            return (center[0], center[1] + _CURSOR_CLICK_DY)
        return None

    def _arrow_pixels(self, screen: np.ndarray) -> int:
        """场景页右下角那三支蓝色箭头占多少像素（0 = 这一帧没看见箭头）。"""

        components = _cyan_components(
            screen, _ARROW_REGION, _ARROW_LO, _ARROW_HI, 1
        )
        return sum(area for area, _center, _box in components)

    # ── 战斗监督 ────────────────────────────────────────────────────────────

    def observe_battle(
        self, screen: np.ndarray, previous_screen: np.ndarray | None
    ) -> BattleObservation:
        """交给战斗监督的「这一屏我认得吗」—— 名单里**必须含战斗关 CLEAR**。

        ⚠️ 主线那份 `result_visible` 的名单是
        `("reward", "clear", "results_confirm")`，其中 `clear` 是**剧情关** CLEAR 的
        模板；战斗关 CLEAR 是另一页（见模块头部判据表）。

        2026-10-15 第二次实跑就死在这里：第一个战斗关打完，屏幕停在战斗关 CLEAR 页，
        监督那五项判据**全 False** ⇒ 判成「未知画面」⇒ 干等 45 秒报
        `battle_unrecognized` ⇒ 退出码 1。状态机明明认得这一页
        （`dismiss_battle_clear`），**却连上场的机会都没有** ——
        只要监督不认为「战斗结束了」，控制权就永远交不回状态机。

        ⇒ 判据复用本路线自己的 `battle_clear`（模板 / 区域 / 口径 / 位置过滤都在
        `_locate` 里），只把结论并进 `result_visible`。狗粮同属「战斗关刷图」，
        它的名单里就有自己的 `clear`（`fodder.py:217`），这里是补上同样的那一手。

        ⚠️ **2026-10-15 第三次实跑证明「接进名单」还不够** —— 名单接对了，但那把
        尺子是坏的：`battle_clear` 当时走原样 RGB 口径、阈值 0.92，而那一帧量出来
        只有 0.9115 ⇒ 补判跑了，结论却是 False，监督照旧干等 45 秒。修的是
        **模板与口径**（见 `_SIDE_MATCH_MODES` 与模块头部那一节），不是这一处名单。
        **教训**：把某页接进「认得吗」的名单时，必须同时验一遍「接进去之后那把尺子
        在这一帧上量得准不准」—— 只看 `_locate(...) is not None` 的写法查不出这种错。

        两条**故意**的收紧：

        1. `battle_visible` 为真时不补判 —— 监督正认为「在战斗中」，不该在这一帧
           被判成「战斗结束」；
        2. 只有两项都为假才跑这次匹配 ⇒ **真实战斗画面上一帧额外判据都不跑**。

        安全前置（`_probe_battle_clear_ruler2.py`，全库 456 张，字标带 + 白掩膜）：
        `battle_clear` 只在本路线 CLEAR 页、狗粮 CLEAR 页与**月塔结算页**
        （0.9398~1.0000，后两者支线永远走不到）上过阈；**真实战斗画面最高 0.2747**
        （`18_battle2`），技能演出帧更低 —— 误收手的余量 0.53。**剧情关 CLEAR 页
        0.2138**，也就是说不存在「把队友的 CLEAR 页当成自己的」这种交叉误判。
        """

        observation = super().observe_battle(screen, previous_screen)
        if observation.result_visible or observation.battle_visible:
            return observation
        if self._locate(screen, "battle_clear") is None:
            return observation
        return replace(observation, result_visible=True)

    # ── 决策 ────────────────────────────────────────────────────────────────

    def next_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        """支线独有页面优先，其余原样委托给主线状态机。

        ``_side_decision`` 返回 ``(是否归我管, 动作)``。**必须**把「这一页我认识、
        但这一帧没有要做的动作」与「压根不是我的页面」分开：
        前者要返回 ``None``（主循环继续轮询、并按状态超时兜底），后者才委托主线。
        若把前者也塞进委托分支，`super().next_action` 会抛 ``UnrecognizedScreen`` ——
        而那是一位**已经被我认出来的**页面（场景页没箭头、地图刚进场没画完），
        走「认不出画面」那条路会让日志刷「结论待确认」、并且一旦唤醒开关打开
        就会去瞎点屏幕；真正的终点（箭头一直不出现）也会被拖到 60 秒状态超时才报，
        而不是按 ``SideStoryCleared`` 优雅收工。
        """

        handled, action = self._side_decision(screen)
        if handled:
            return action
        try:
            return super().next_action(screen)
        except UnrecognizedScreen as error:
            raise UnrecognizedScreen(
                f"支线故事画面[{state_label(self.state)}]未识别"
            ) from error

    def _side_decision(
        self, screen: np.ndarray
    ) -> tuple[bool, Optional[StoryAction]]:
        """本路线判据，按优先级排。返回 ``(是否归我管, 动作)``。

        顺序**不能改**（后一条都会压在前一条上）：
        「完成故事」弹窗是模态遮罩 → 场景页 → 战斗关 CLEAR → 剧情关 CLEAR →
        关卡地图 → Episode 详情页 → 期次主页（PC）→ 支线故事页。
        都不命中才返回 ``(False, None)``。
        """

        # ③ 据点模式探活（**副作用，不返回**）：据点队伍页有「可完成1次。」白气泡，
        # ①/BOSS 队伍页都没有 ⇒ 命中即确认「当前在据点里」，置位 ``_in_outpost``。
        # 据点场景页与普通①「打完」场景页**长得一模一样**（都有离开/大厅/重新进行、
        # 都没箭头、都没「下一个难度」），纯页面识别分不出两者，只能靠这个状态位：
        # 置位后场景页改点「离开」回地图，否则会走①的箭头收工逻辑（见下方 replay 分支）。
        # 置位后一直保持，直到「离开」回地图（见地图分支重置）。
        if self._locate(screen, "outpost_team") is not None:
            self._in_outpost = True

        # ⓪ 「完成故事」弹窗，**必须最先判**。它每关通关都会弹一次（实测第 1~4 关全弹），
        #    是一层模态遮罩，压在被遮住的结算页上。留着它不点，下面每条判据都会被
        #    遮罩压低 —— 实测结算页的 results_confirm 在遮罩下从 0.9786 掉到 0.4857，
        #    整条路线会卡在这里干等到状态超时。
        popup = self._locate(screen, "complete_popup")
        if popup is not None:
            return True, self._action(
                "close_complete_popup",
                self._scaled_point(screen, _POPUP_CLOSE_POINT),
                source_page="完成故事",
                target_pages=("结算确认", "通关提示"),
                reason="完成故事弹窗已识别",
                target_states=(StoryState.WAIT_RESULTS, StoryState.WAIT_COMPLETE),
            )

        # ⓪a 「可入场次数已全部耗尽。」——**段落感知的终点**（2026-11-01 语义更改）。
        # 这一句出现 = 「当前这一段打不了了」。在连打链路下它的含义由 `_segment` 决定：
        #   * `_SEG_BOSS`：地狱级打满 ⇒ **不再收工**，点「返回」退场接 ③（用户明确要求
        #     ①→②→③ 连起来）。回程两条路都接得住：落到地狱级场景页 → `_boss_done`
        #     分支点「离开」；直接落回地图 → 地图分支的 `_boss_done` 兜底切 ③。
        #   * 其他段（③ 据点次数用尽 / ① 不可能出现）：维持旧语义 = 本路线收工
        #     （退出码 2）。⚠️ 已知局限：中途重跑且据点①已用尽时，会在这里收工而跳过
        #     据点②——「从耗尽的据点准备页一路退回地图再导航下一个」需要更多退场机制，
        #     本期不做，文档已记。
        exhausted = self._locate(screen, "entry_exhausted")
        if exhausted is not None:
            if self._segment == _SEG_BOSS:
                self._boss_done = True
                back = self._locate(screen, "story_back")
                if back is not None:
                    return True, self._action(
                        "boss_done_back",
                        back.center,
                        source_page="队伍准备",
                        target_pages=("地狱级场景页", "助手选择", "队伍准备", "关卡地图"),
                        reason="② BOSS 次数用尽：点「返回」退场接③据点（不再就地收工）",
                        target_states=(StoryState.STAGE, StoryState.TEAM),
                    )
                # 「返回」这一帧还没认出来，先等（下一帧会再进这个分支）。
                return True, None
            raise SideStoryCleared(
                "次数已用尽（可入场次数已全部耗尽），支线故事本路线完成"
            )

        # ⓪b BOSS 打完那一屏：右下角有「下一个难度」。**必须排在 `replay` 之前** ——
        # 那一页同时有「重新进行」、且蓝箭头为 0，先判 replay 会在 12 帧后判「本期打完」
        # （2026-11-01 实测：replay 0.9699 / 箭头像素 0）。
        #
        # ⚠️ 「下一个难度」不是无脑点：它只负责把档位从中级推到地狱级（最多 2 次推进）。
        # 推满之后再遇到这一屏，必须交给下方 `replay` 分支走「重新进行」把地狱级打满，
        # 否则会一直点「下一个难度」空转（地狱级已是最高档，点了游戏侧大概率无反应，
        # 这一屏又没箭头，最终会被箭头缺失逻辑误判成「本期打完」提前收工）。
        next_difficulty = self._locate(screen, "next_difficulty")
        if next_difficulty is not None and self._boss_advances < 2:
            self._boss_advances += 1
            return True, self._action(
                "next_difficulty",
                next_difficulty.center,
                source_page="难度场景页",
                target_pages=("选择辅助英雄", "队伍准备"),
                reason=f"BOSS 场景页「下一个难度」已识别（推进第 {self._boss_advances} 档）",
                target_states=(StoryState.STAGE, StoryState.TEAM),
            )

        # ⓪c BOSS **首次进场**的难度选择（2026-11-01，连打链路新增）。
        # 链路自动点到骷髅节点 → 准备战斗 → 落在「选择辅助英雄」页，此时粘性档位是
        # 上一次的遗留（可能是初级/上一期的地狱级），**不能**交给主线直接确认。
        # 只在 ② 段且 `_boss_entered` 未置位时接管，三拍走完：变更 → 中级行 → 选择队伍；
        # 完成后交还主线 —— 之后每档由「下一个难度」把粘性档位推上去，主线直接确认即可。
        if self._segment == _SEG_BOSS and not self._boss_entered:
            change = self._locate(screen, "helper_change")
            if change is not None:
                # 这页归我管（连等待也返回 (True, None)，不给主线误点「选择队伍」的机会）。
                return True, self._boss_first_entry_action(screen, change)

        # ① 场景页：点箭头进下一关；箭头连着多帧不见 ⇒ **不再收工**，接力去 ②。
        # ③ 在据点模式里，这同一页是「据点场景页」，必须改点「离开」回地图，
        #    绝不能走箭头逻辑（据点场景页没有箭头，会误判整期结束）。
        # ② 打满退场（`_boss_done`）落回地狱级场景页时，同样改点「离开」。
        replay = self._locate(screen, "replay")
        if replay is not None:
            if self._in_outpost:
                return True, self._outpost_scene_action(screen)
            if self._boss_done:
                return True, self._boss_done_scene_action(screen)
            return True, self._scene_action(screen, replay)

        # ② 战斗关的 CLEAR（判据 = CLEAR 字标带 + 白掩膜，见 `_SIDE_MATCH_MODES`；
        #     6 帧实测过：12_battle_later / 13_clear / 30_battle3 / 38_battle4b /
        #     以及第三次实跑的那张诊断帧）。
        #
        # ⚠️ 点的是右下角那支箭头，不是屏幕中央：CLEAR 画面整幅被压暗，箭头颜色
        # 塌到 HSV≈(90,28,73)，**颜色判据在这里无效**，所以直接给固定点 ——
        # 实测两张战斗关 CLEAR 的箭头都在 (1690~1900, 665~850) 这一带。
        #
        # ⚠️ ``target_pages`` **必须含「完成故事」**：这一关打完之后先弹「完成故事」
        # 弹窗（实测每关都弹），然后才是结算页。少写这一个落点，主循环会把
        # 「去关弹窗」这个动作整个吞掉 —— 详见 ``_CLEAR_TARGET_PAGES`` 的注释。
        #
        # ⚠️ 这一条**必须**判在 ②b（剧情关 CLEAR）前面：两页都由「CLEAR 字标」定性，
        # 只是落点不同。真 CLEAR 的字标在 y≈480，剧情关那张在 y≈750（在区域之外），
        # 所以两者互不命中（实测剧情关 CLEAR 在这张模板上只有 0.2138）——
        # 但顺序仍然不能反：反了就得靠分数而非语义来分，那是脆的。
        clear = self._locate(screen, "battle_clear")
        if clear is not None:
            return True, self._action(
                "dismiss_battle_clear",
                self._scaled_point(screen, _ARROW_CLICK_POINT),
                source_page="通关结算",
                target_pages=_CLEAR_TARGET_PAGES,
                reason="战斗关卡的通关结算画面已识别",
                target_states=(StoryState.WAIT_RESULTS, StoryState.WAIT_COMPLETE),
            )

        # ②b 剧情关的 CLEAR。判据与主线**完全同一份**（走 `story_clear` 别名），
        #     自己写的只有契约。
        #
        # ⚠️ 为什么要自己接这一手，而不是像原来那样委托给主线的 ``clear``：
        #     主线的 ``clear`` 把 ``target_pages`` 写死成「结算确认/通关提示」，
        #     而这条支线的实际落点是「完成故事」弹窗 —— 契约不成立时主循环的行为是
        #     「把当前动作置成 None 继续干等」（`runner_base` 里那段
        #     `elif last_transition_action is not None: action = ... else None`），
        #     于是弹窗明明认出来了（实测 0.9995）却没人去关它，一路等到
        #     `WAIT_RESULTS` 的 45 秒超时，整条路线以退出码 1 收场。
        #     ⇒ 判据复用、契约自有，是这个项目里已经用过的办法（同 `battle_clear`）。
        story_clear = self._locate(screen, "story_clear")
        if story_clear is not None:
            return True, self._action(
                "dismiss_story_clear",
                story_clear.center,
                source_page="通关结算",
                target_pages=_CLEAR_TARGET_PAGES,
                reason="剧情关卡的通关结算画面已识别",
                target_states=(StoryState.WAIT_RESULTS, StoryState.WAIT_COMPLETE),
            )

        # 关卡地图（决策序③）：按段落导航。
        panel = self._locate(screen, "map_panel")
        if panel is not None:
            # 回到地图 = 不在任何据点里、「离开」已完成。
            self._in_outpost = False
            self._leaving = False
            # ② 打满后若「返回」直接落回地图（没经过地狱级场景页），在这里兜底切 ③。
            if self._boss_done:
                self._boss_done = False
                self._segment = _SEG_OUTPOST_1
            # 最后一个据点点完「离开」回地图 ⇒ 全程完成，收工（退出码 2）。
            if self._final_leave:
                raise SideStoryCleared(
                    "两个据点均已打完并离开回地图，支线故事①②③全程完成"
                )
            if self._segment == _SEG_NORMAL:
                # ① 段：按光标走（原逻辑不动）。
                point = self._cursor_point(screen)
                if point is None:
                    # 转场途中（地图刚进场还没画完）或本期地图的光标长得不一样。
                    # 返回 None = 「这一帧没有要做的动作」，让主循环继续轮询，
                    # 而不是抛「未识别」把整条路线判死。
                    return True, None
                self._arrow_misses = 0
                return True, self._action(
                    "pick_stage",
                    point,
                    source_page="关卡地图",
                    target_pages=("助手选择", "队伍准备", "关卡入口"),
                    reason="关卡地图上当前角色的光标已定位（青色菱形下移固定像素）",
                    target_states=(StoryState.TEAM, StoryState.STAGE),
                )
            # ②③ 段：在地图上找目标节点图标 → 点它 → 等走路结束 → 点「准备战斗」。
            return True, self._map_navigation_action(screen)

        # ④ Episode 详情页。
        adventure = self._locate(screen, "adventure")
        if adventure is not None:
            return True, self._action(
                "enter_adventure",
                adventure.center,
                source_page="Episode详情",
                target_pages=("关卡地图",),
                reason="Episode 详情页的冒险按钮已识别",
                target_states=(StoryState.STAGE,),
            )

        # ⑤ 期次主页（PC 专属，2026-11-06）：点了「快速入场」后先落在这里。
        # 右侧「故事 / 奖励 / PV」三颗标签，不是 Episode 详情也不是关卡地图 ——
        # 12:59 那轮真机就是在这页 `UnrecognizedScreen` 干等 60 秒超时。
        # 判据两颗任一命中即可（模拟器都是空元组 ⇒ 两支都 False，行为零改动）。
        event_home = self._locate(screen, "event_home_reward")
        if event_home is None:
            event_home = self._locate(screen, "event_home_pv")
        if event_home is not None:
            return True, self._action(
                "enter_event_story",
                self._scaled_point(screen, _EVENT_HOME_STORY_POINT),
                source_page="期次主页",
                target_pages=_EVENT_HOME_TARGET_PAGES,
                reason="期次主页的「故事」入口已识别",
                target_states=(StoryState.STAGE,),
            )

        # ⑥ 支线故事页。⚠️ 它的落点白名单必须含「期次主页」：PC 上「快速入场」
        # 点下去先到的是上面那一页，不是 Episode 详情（2026-11-06 12:58 真机日志）。
        entry = self._locate(screen, "quick_entry")
        if entry is not None:
            return True, self._action(
                "enter_quick_entry",
                entry.center,
                source_page="支线故事",
                target_pages=("Episode详情", "关卡地图", "期次主页"),
                reason="支线故事页的快速入场按钮已识别",
                target_states=(StoryState.STAGE,),
            )

        # 七条判据都不命中 ⇒ 这一页不归我管，交给主线状态机。
        return False, None

    def _scene_action(self, screen: np.ndarray, replay: Match) -> Optional[StoryAction]:
        """场景页（打完一关站着的那个场景）上的决策。

        箭头在 ⇒ 点它进下一关；箭头连着 ``_ARROW_MISS_LIMIT`` 帧不在 ⇒ 这一期到头了。

        ⚠️ **``_arrow_misses`` 只在「提交路径」上累加**（``preview`` 会把它还原，
        见 ``preview``）：主循环每轮先 ``preview`` 再决定是否 ``next_action`` 提交，
        不还原就会同一帧数两次、把 12 帧的门槛砍成 6 秒。代价是**这一页必须靠
        `next_action` 每轮被调一次才能记账** —— 所以 `_side_decision` 返回
        ``(True, None)``（认识但无动作）而不是 ``(False, None)``：前者主循环会继续
        轮询并再次提交，后者会去委托主线、被 ``UnrecognizedScreen`` 打断记账。

        ⚠️ **BOSS 地狱级场景页优先于此处的箭头逻辑**：地狱级场景页既没有蓝箭头、
        也没有「下一个难度」可推进（``_boss_advances`` 已到 2），唯一能做的就是
        「重新进行」把地狱级打满。必须先认这一支，否则会掉进下面的「箭头缺失 12 帧
        ⇒ 本期打完」把整条路线提前收工（2026-11-01 实测 BOSS 场景页箭头像素恒为 0）。
        """

        # BOSS 地狱级：靠「重新进行」打满，不走箭头收工。
        # ⚠️ 终点**不在这里数次数**：重新进行回到队伍准备页后，若地狱级已打满，
        # 那一页会出现「可入场次数已全部耗尽。」（见 `_side_decision` 的 entry_exhausted
        # 分支），由那一支判定收工 —— 那是游戏自身的真相源，比数 5 次更稳。
        # 这里只负责「站在地狱级场景页就点重新进行」。
        if self._boss_advances >= 2:
            return self._action(
                "replay",
                replay.center,
                source_page="地狱级场景页",
                # ⚠️ 「重新进行」点下去的落点待实测确认（2026-11-01：点过一次没生效，
                # 可能进队伍页、也可能直接开打）。先把两条都列上，主线动作落白名单
                # 不匹配时会回退到「一路 Back 回大厅」失败关闭，不会瞎点。
                target_pages=("队伍准备", "助手选择", "关卡入口"),
                reason="BOSS 地狱级，重新进行（终点由 entry_exhausted 判定）",
                target_states=(StoryState.TEAM, StoryState.STAGE),
            )

        pixels = self._arrow_pixels(screen)
        if pixels < _ARROW_PIXELS_MIN:
            self._arrow_misses += 1
            if self._arrow_misses >= _ARROW_MISS_LIMIT:
                # ① 正常关卡打完 ⇒ **不再收工**（2026-11-01 语义更改）：点「离开」
                # 回地图，段落切到 ②，由地图导航去点骷髅节点。场景页这一帧还没有
                # 「离开」命中就先等（``_arrow_misses`` 会继续累加，本分支每帧重进）。
                leave = self._locate(screen, "outpost_leave")
                if leave is None:
                    return None
                self._segment = _SEG_BOSS
                self._leaving = True
                self._arrow_misses = 0
                return self._action(
                    "scene_leave",
                    leave.center,
                    source_page="下一关入口",
                    target_pages=("关卡地图",),
                    reason="① 正常关卡打完（连续12帧无箭头）：点「离开」回地图接② BOSS",
                    target_states=(StoryState.STAGE,),
                )
            return None

        self._arrow_misses = 0
        # 累计完成轮次。用状态做闸门：只有「刚打完一关回到场景页」才算一轮，
        # 否则同一页停留几帧就会被重复计数（狗粮的 ``replay`` 分支同一手法）。
        if self.state is not StoryState.WAIT_NEXT_STAGE:
            self.completed_cycles += 1
            self.state = StoryState.WAIT_NEXT_STAGE
        return self._action(
            "advance_stage",
            self._scaled_point(screen, _ARROW_CLICK_POINT),
            source_page="下一关入口",
            target_pages=("助手选择", "队伍准备", "关卡地图"),
            reason="场景页的蓝色三箭头已识别",
            target_states=(StoryState.TEAM, StoryState.STAGE, StoryState.WAIT_NEXT_STAGE),
        )

    # ── 连打链路的新方法（②③ 段导航 / 退场 / BOSS 首进场）────────────────────

    def _boss_first_entry_action(
        self, screen: np.ndarray, change: Match
    ) -> Optional[StoryAction]:
        """BOSS 首进场三拍：变更 → 中级行 → 选择队伍（同页推进，靠子状态防重按）。

        ⚠️ 「变更」在 helper 视图（左下）与列表视图（中下）都会命中 —— 用命中点
        x 坐标区分（<400 = helper 视图）。中级行点完会**同页停留**，靠
        ``_boss_row_clicked`` 防止下一帧又点行；点「选择队伍」后置 ``_boss_entered``，
        之后的 helper 页（上级/地狱级进场）交还主线（粘性档位已被「下一个难度」推好）。
        ⚠️ 已知薄弱点：若「中级行」那一击被吃掉，这里会在下一拍直接点「选择队伍」，
        确认的就是当时高亮的那一行 —— 行点击失败属罕见路径，真跑若复现再加选中态复核。
        """

        if change.center[0] < 400:
            # helper 视图：点「变更」展开难度列表（落点仍在 helper 页族）。
            return self._action(
                "boss_open_difficulty",
                change.center,
                source_page="选择辅助英雄",
                target_pages=("选择辅助英雄", "选择难度"),
                reason="BOSS 首进场：点「变更」展开难度列表",
                target_states=(StoryState.TEAM,),
            )
        row = self._locate(screen, "diff_mid")
        if row is not None and not self._boss_row_clicked:
            self._boss_row_clicked = True
            return self._action(
                "boss_pick_mid",
                row.center,
                source_page="选择难度",
                target_pages=("选择难度",),
                reason="BOSS 首进场：点中级行（同页停留，下一拍点「选择队伍」）",
                target_states=(StoryState.TEAM,),
            )
        if self._boss_row_clicked:
            confirm = self._locate(screen, "boss_select_team")
            if confirm is not None:
                self._boss_entered = True
                return self._action(
                    "boss_confirm_team",
                    confirm.center,
                    source_page="选择难度",
                    target_pages=("队伍准备", "助手选择"),
                    reason="BOSS 首进场：点「选择队伍」进队伍准备（中级）",
                    target_states=(StoryState.TEAM,),
                )
        # 列表视图但行/确认键这一帧没认出来：等。
        return None

    def _outpost_scene_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        """据点场景页：点「离开」回地图并推进段落（③a→③b→收工）。"""

        if self._leaving:
            # 已点过「离开」、正在等回地图：这一屏先不做事，让主循环轮询。
            return None
        leave = self._locate(screen, "outpost_leave")
        if leave is None:
            # 「离开」按钮这帧还没认出来，先等。
            return None
        if self._segment == _SEG_OUTPOST_1:
            self._segment = _SEG_OUTPOST_2
            reason = "据点①（哥布林）打完，点「离开」回地图接摩罗戈拉据点"
        else:
            self._final_leave = True
            reason = "据点②（摩罗戈拉）打完，点「离开」回地图收工"
        self._leaving = True
        return self._action(
            "outpost_leave",
            leave.center,
            source_page="据点场景页",
            target_pages=("关卡地图",),
            reason=reason,
            target_states=(StoryState.STAGE,),
        )

    def _boss_done_scene_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        """② 打满退场：地狱级场景页点「离开」回地图，段落切 ③。"""

        if self._leaving:
            return None
        leave = self._locate(screen, "outpost_leave")
        if leave is None:
            return None
        self._boss_done = False
        self._segment = _SEG_OUTPOST_1
        self._leaving = True
        return self._action(
            "boss_scene_leave",
            leave.center,
            source_page="地狱级场景页",
            target_pages=("关卡地图",),
            reason="② BOSS 打满：点「离开」回地图接③据点",
            target_states=(StoryState.STAGE,),
        )

    def _map_navigation_action(self, screen: np.ndarray) -> Optional[StoryAction]:
        """②③ 段的地图导航：找目标节点 → 点它 → 等走路结束 → 点「准备战斗」。

        三条规矩（全部来自 2026-11-01 的帧证据）：
        1. **「准备战斗」是常显按钮**（角色永远站在某个节点上），它指向的是
           「当前站的节点」⇒ 点了目标节点、角色还在走路时点它 = 进错关卡。
           必须等画面稳定（`_map_settled`，连续 2 帧地图内容区几乎不变）再点。
        2. **目标节点可能不在视野内**（相机跟角色走；默认视角下 goblin 大半被
           顶部 HUD 挡住）⇒ 找不到就按 `_PAN_SWEEPS` 平移视角扫寻，有界重试，
           找不到大不了原地等状态超时兜底，绝不瞎点。
        3. 节点点击动作的落点是**同一张地图**（走路不换页）⇒ ``target_pages``
           填「关卡地图」：下一帧地图分支返回 ``None``（``_node_clicked`` 门控），
           转场验收看到「确认页 ∈ 目标页 且 无新动作」即完成，**不会重发点击**
           （重发会打断走路）。
        """

        if self._node_clicked:
            settled = self._map_settled(screen)
            if not settled:
                return None
            prep = self._locate(screen, "prepare_battle_map")
            if prep is None:
                return None
            self._node_clicked = False
            self._pan_attempts = 0
            return self._action(
                "enter_selected_node",
                prep.center,
                source_page="关卡地图",
                target_pages=("选择辅助英雄", "助手选择", "队伍准备", "选择难度"),
                reason="角色已走到目标节点且画面稳定：点「准备战斗」进出场流程",
                target_states=(StoryState.TEAM, StoryState.STAGE),
            )
        target_name = _NODE_TEMPLATES[self._segment]
        hit = self._locate(screen, target_name)
        if hit is not None:
            self._node_clicked = True
            self._pan_attempts = 0
            self._settle_streak = 0
            # ⚠️ 必须存副本：若取图层复用缓冲区，存引用会让「上一帧」跟着变，
            # 稳定判定永远为真 ⇒ 走路中途就点「准备战斗」→ 进错节点。
            self._prev_screen = screen.copy()
            return self._action(
                f"pick_node_{target_name}",
                hit.center,
                source_page="关卡地图",
                target_pages=("关卡地图",),
                reason=f"已定位{_SEG_LABELS[self._segment]}节点图标，点击让角色走过去",
                target_states=(StoryState.STAGE,),
            )
        # 没找到：有界平移扫寻。动作名带上次数 —— 同名动作会被主循环判「转场未完成
        # 且还在来源页」而**重发**，那会原地反复拖动；不同名才能逐次推进。
        self._pan_attempts += 1
        if self._pan_attempts > _PAN_LIMIT:
            return None
        delta = _PAN_SWEEPS[(self._pan_attempts - 1) % len(_PAN_SWEEPS)]
        end = (_PAN_START[0] + delta[0], _PAN_START[1] + delta[1])
        return self._action(
            f"pan_map_{self._pan_attempts}",
            end,
            source_page="关卡地图",
            target_pages=("关卡地图",),
            reason=(
                f"目标节点不在视野内，平移视角扫寻（第 {self._pan_attempts}/{_PAN_LIMIT} 次，"
                f"拖动增量 {delta}）"
            ),
            target_states=(StoryState.STAGE,),
        )

    def _map_settled(self, screen: np.ndarray) -> bool:
        """走路结束判定：地图中部内容区连续 ``_SETTLE_STREAK_NEED`` 帧几乎不变。

        比对区域刻意避开固定 UI（顶栏/底栏/右侧任务栏）——那些永远不变、比对它们
        等于自欺。容忍度 1/10：角色待机动画、旗帜飘动约占区域像素的一成以下；
        走路时相机移动会让内容区大面积变化，轻松越过。⒊ 阈值是真跑要盯的第一个
        旋钮（过松 = 还在走就点准备战斗 → 进错节点；过紧 = 待机动画被判成走路 → 干等）。
        """

        prev = self._prev_screen
        self._prev_screen = screen.copy()
        if prev is None or prev.shape != screen.shape:
            self._settle_streak = 0
            return False
        x, y, width, height = _SETTLE_REGION
        diff = cv2.absdiff(screen[y : y + height, x : x + width], prev[y : y + height, x : x + width])
        changed = int((diff.max(axis=2) > 24).sum())
        if changed <= _SETTLE_CHANGED_MAX:
            self._settle_streak += 1
        else:
            self._settle_streak = 0
        return self._settle_streak >= _SETTLE_STREAK_NEED

    def preview(self, screen: np.ndarray):
        """观察一帧但不留下痕迹（含本路线自己的账本）。"""

        saved = (
            self._arrow_misses,
            self._in_outpost,
            self._segment,
            self._leaving,
            self._boss_done,
            self._final_leave,
            self._node_clicked,
            self._pan_attempts,
            self._boss_entered,
            self._boss_row_clicked,
            self._settle_streak,
            self._prev_screen,
        )
        try:
            return super().preview(screen)
        finally:
            (
                self._arrow_misses,
                self._in_outpost,
                self._segment,
                self._leaving,
                self._boss_done,
                self._final_leave,
                self._node_clicked,
                self._pan_attempts,
                self._boss_entered,
                self._boss_row_clicked,
                self._settle_streak,
                self._prev_screen,
            ) = saved


# ── 开局接力 ────────────────────────────────────────────────────────────────
#
# 顺序**不能改**，两条硬约束：
#   ① 完成故事弹窗是模态遮罩，压在被它盖住的结算页上（实测 results_confirm 从
#      0.9786 掉到 0.4857）⇒ 必须最先判，否则整页都认不准。
#   ② `replay`（场景页）必须排在 `battle_scene_visible` 之前 —— 那一页的白色结构
#      会撞上战斗画面判据（实测 `True`），排后面就会被当成「局内」交给战斗监督，
#      一路磨到绝对超时。见模块头「开局接力」。
#
# 不放进来的：`通关提示` / `奖励结算` / `额外奖励` / `下一关入口` —— 它们由主线动作
# 处理，而主线动作的落点白名单写的是主线的下一页，接上去只会把「落点对不上」搬进接力。
#
# 2026-11-06 补「期次主页」：PC 上「快速入场」多出这一层中间页。两颗标签是**两个
# 独立的原子**，都落在同一页/同一状态 —— 任一命中都能接上（跨期换皮时的冗余）。
# 排在本来就该在它前面的弹窗/场景/地图/Episode详情之后、支线故事 hub 之前：
# 这页与那 12 个锚点互斥（12:59 真机帧上全 None），顺序只为读起来跟导航链一致。
_SIDE_RESUME_ORDER: tuple[tuple[str, StoryState, str], ...] = (
    ("complete_popup", StoryState.WAIT_RESULTS, "完成故事"),
    ("replay", StoryState.STAGE, "场景页"),
    ("battle_clear", StoryState.WAIT_RESULTS, "通关结算"),
    ("story_clear", StoryState.WAIT_RESULTS, "通关结算"),
    ("map_panel", StoryState.STAGE, "关卡地图"),
    ("adventure", StoryState.STAGE, "Episode详情"),
    ("event_home_reward", StoryState.STAGE, "期次主页"),
    ("event_home_pv", StoryState.STAGE, "期次主页"),
    ("quick_entry", StoryState.STAGE, "支线故事"),
    ("start_mission", StoryState.TEAM, "队伍准备"),
    ("select_team", StoryState.TEAM, "助手选择"),
    ("skip_confirm", StoryState.WAIT_SKIP_CONFIRM, "跳过确认"),
    ("skip", StoryState.ACTIVE, "剧情播放"),
    ("results_confirm", StoryState.WAIT_RESULTS, "结算确认"),
)


def detect_resume_point(
    machine: SideStoryStateMachine, screen: np.ndarray
) -> Optional[ResumePoint]:
    """开局接力：认出用户停在支线的一环里的哪一页。

    认不出返回 ``None`` ⇒ 调用方照旧「回大厅 → 从支线故事页重新导航」
    （失败关闭，与加接力之前完全一致）。

    接力用的一帧**没有运行期上下文**，所以这里只认页面上真有专属锚点的页；
    落点状态按 `_SIDE_RESUME_ORDER` 逐条写好，理由见模块头。
    """

    for name, state, label in _SIDE_RESUME_ORDER:
        if machine._locate(screen, name) is not None:
            return ResumePoint(label, state)
    # ⚠️ 局内**排在最后**：本路线有页面会被这条判成局内（见模块头），
    # 前面十四个锚点先认完，剩下还像战斗的才当「用户停在战斗里」交给战斗监督。
    if battle_scene_visible(screen):
        return ResumePoint("战斗中", StoryState.WAIT_BATTLE)
    return None


class SideStoryRunner(StoryRunner):
    """支线故事 Runner：主循环协议与主线完全相同，只换名字与超时额度。

    ⚠️ 刻意**不重写** ``run`` / ``_stable_next_action`` / ``_execute_transition`` ——
    转场契约的强制开关（``_REQUIRE_TRANSITION_CONTRACT``）读取点就在基类那几段里，
    重写等于把「点了之后回头看」这道门绕过去。本路线打开这个开关，所以每个动作
    都必须带 ``source_page`` + ``target_pages``（``SideStoryStateMachine`` 里那条
    ``super().next_action`` 返回的主线动作本来就带）。
    """

    _MODE_LABEL = "支线故事"
    _REQUIRE_TRANSITION_CONTRACT = True
    _TIMEOUT_SECONDS = {
        StoryState.STAGE: 60,          # 关卡地图要等角色跑动/转场
        StoryState.TEAM: 45,
        StoryState.WAIT_SKIP_CONFIRM: 45,
        StoryState.WAIT_BATTLE: 60,
        StoryState.ACTIVE: 120,
        StoryState.WAIT_RESULTS: 45,
        StoryState.WAIT_COMPLETE: 45,
        StoryState.WAIT_NEXT_STAGE: 60,
    }

    def _perform_action(self, action: Any) -> None:
        """把动作发出去；``pan_map_*`` 走 ``runtime.swipe``（主循环没有滑动通道）。

        动作字段里 ``point`` 装的是**滑动终点**（起点 = ``_PAN_START``），这与基类
        「point = 点击点」的约定不同，所以**必须**在这里拦下换发 —— 否则视角平移
        会被当成「在终点点一下」（2026-10-07 社区点赞三遍全废就是这一类错）。
        """

        if action.name.startswith("pan_map_"):
            self.runtime.swipe(
                _PAN_START, action.point, _PAN_DURATION_MS, action.name
            )
            return
        super()._perform_action(action)

    def __init__(
        self,
        machine: SideStoryStateMachine,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        super().__init__(
            machine,
            runtime,
            sleep=sleep,
            poll_seconds=poll_seconds,
            recovery_gate=recovery_gate,
            battle_supervisor=battle_supervisor,
        )
        if battle_supervisor is None:
            # 只换掉名字：兵线/自理逻辑原样用主线的，只是日志与诊断目录该按本路线落。
            # ⚠️ 复用 ``self.recovery_gate`` 与 ``self.now``，**不要**在这里再造一个
            # ``RecoveryGate()`` —— 两个 gate 会让「自救预算」按两本账各记一遍。
            self.battle_supervisor = BattleSupervisor(
                runtime,
                self.recovery_gate,
                BattleConfig(mode="side_story", mode_label="支线故事"),
                now=self.now,
                sleep=sleep,
            )

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式=支线故事 状态=完成一轮 累计通关="
            f"{self.machine.completed_cycles}关"
        )

    def _log_state_timeout(self, state: StoryState, elapsed: float, diagnostic) -> None:
        self.runtime.log(
            f"模式=支线故事 页面={state_label(state)} "
            f"状态=超时无进展 已耗时={elapsed:.1f}秒 诊断={diagnostic}"
        )

    def _log_settled_timeout(self, state: StoryState, diagnostic) -> None:
        self.runtime.log(
            f"模式=支线故事 页面={state_label(state)} "
            f"状态=等待超时无进展 诊断={diagnostic}"
        )


def build_side_story_machine(
    template_dir: Path,
    state: str = StoryState.STAGE.value,
) -> SideStoryStateMachine:
    """装配入口：``template_dir`` 是 ``templates/side_story``。"""

    return SideStoryStateMachine(
        build_side_story_templates(template_dir),
        initial_state=StoryState(state),
    )


# 供 ``modes.ModeSpec`` 与测试引用，避免两边各写一遍取值。
MODE_LABEL = "支线故事"
DEFAULT_STATE = StoryState.STAGE.value
