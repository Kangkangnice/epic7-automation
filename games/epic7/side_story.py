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
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

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

# 本路线独有的六条区域 / 阈值。提成模块常量而不是直接写在类体里，是因为
# ``__init__`` 还要再用一次（理由见那里）。
_SIDE_REGIONS = {
    "quick_entry": (100, 950, 520, 182),
    "adventure": (1340, 950, 642, 182),
    "map_panel": (1740, 220, 242, 372),
    "replay": (1600, 960, 382, 172),
    "battle_clear": (400, 200, 1000, 500),
    "complete_popup": (600, 150, 800, 400),
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
_SIDE_MATCH_MODES: dict[str, str] = {"battle_clear": MATCH_MODE_WHITE_MASK}


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


def build_side_story_templates(template_dir: Path) -> SideStoryTemplates:
    """构建支线故事模板。

    ``template_dir`` 是 ``templates/side_story``；主线模板在它的兄弟目录
    ``templates/story``（与 ``build_fodder_templates`` 同一形状）。
    """

    root = template_dir.parent
    return SideStoryTemplates(
        story=build_story_templates(root / "story"),
        quick_entry=load_template(str(template_dir / "quick_entry.png")),
        adventure=load_template(str(template_dir / "adventure.png")),
        map_panel=load_template(str(template_dir / "map_panel.png")),
        replay=load_template(str(template_dir / "replay.png")),
        battle_clear=load_template(str(template_dir / "battle_clear.png")),
        complete_popup=load_template(str(template_dir / "complete_popup.png")),
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
        """本路线六条判据，按优先级排。返回 ``(是否归我管, 动作)``。

        顺序**不能改**（后一条都会压在前一条上）：
        「完成故事」弹窗是模态遮罩 → 场景页 → 战斗关 CLEAR → 剧情关 CLEAR →
        关卡地图 → Episode 详情页 → 支线故事页。都不命中才返回 ``(False, None)``。
        """

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

        # ① 场景页：点箭头进下一关；箭头连着多帧不见就收工。
        replay = self._locate(screen, "replay")
        if replay is not None:
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

        # ③ 关卡地图：定位光标 → 点它下方。
        panel = self._locate(screen, "map_panel")
        if panel is not None:
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

        # ⑤ 支线故事页。
        entry = self._locate(screen, "quick_entry")
        if entry is not None:
            return True, self._action(
                "enter_quick_entry",
                entry.center,
                source_page="支线故事",
                target_pages=("Episode详情", "关卡地图"),
                reason="支线故事页的快速入场按钮已识别",
                target_states=(StoryState.STAGE,),
            )

        # 六条判据都不命中 ⇒ 这一页不归我管，交给主线状态机。
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
        """

        pixels = self._arrow_pixels(screen)
        if pixels < _ARROW_PIXELS_MIN:
            self._arrow_misses += 1
            if self._arrow_misses >= _ARROW_MISS_LIMIT:
                # 走 ``StaminaExhausted`` 家族 ⇒ 主循环按「资源耗尽」优雅收工：
                # 记日志、``_close_out()`` 回首页、退出码 2。与月塔打满同族。
                raise SideStoryCleared(
                    "本期支线故事已到头：场景页连续 "
                    f"{self._arrow_misses} 帧看不到蓝色三箭头，只剩重新进行"
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

    def preview(self, screen: np.ndarray):
        """观察一帧但不留下痕迹（含本路线自己的账本）。"""

        arrow_misses = self._arrow_misses
        try:
            return super().preview(screen)
        finally:
            self._arrow_misses = arrow_misses


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
