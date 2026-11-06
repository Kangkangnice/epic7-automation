"""通用「回家」流程（v2）：统一用 ESC 把游戏送回大厅。

用户 2026-09-25 定下的原则，**一句话：新流程一律按 ESC，不点坐标图标。**

> 「我还是坚持我的原则，就是我们新开发的这个一定要都按 ESC 来」

## 为什么要换掉老的 ``navigation.return_home``

老的 ``return_home`` 只有一招：**按 ESC**，外加一个「认不出就点屏幕中央」的妥协。
它在**浅层页面**（大厅 → 支线 → 详情页，两三级）够用，用户的原话是：

> 「我之前用过体验，说实话一般层数多一点的话就不太行了」

层数一深就有两个毛病：

1. **慢**：一层一层按回去，8 次上限很容易耗尽，撞上限就整条路线报错。
2. **有更快的路它不知道**：游戏右上角那颗**蓝色四格**能直接打开快捷菜单，
   里面的**酒馆**就是首页 —— 一步到家，不用一层层退。迷宫强化石就是这么做的
   （实机日志 ``epic7_labyrinth_stone.log`` 2026-09-25 13:42:50：详情页点蓝色四格
   → 酒馆 → 4 秒到大厅）。

所以 v2 是「**能一步到家就一步到家，不能就按 ESC**」，而不是「只会按 ESC」。

## 判定顺序（每一帧，一轮只做一个动作）

| 顺序 | 看到什么 | 做什么 | 为什么排在这里 |
| --- | --- | --- | --- |
| 1 | **大厅** | **收工** ✅ | 必须第一 —— 大厅**也有**蓝色四格 |
| 2 | **快捷菜单已展开** | 点**酒馆** | 一步到家，最优先的捷径 |
| 3 | **在局内**（右上角有 ``‖``） | **按 ESC**，等 4 秒 | 局内的蓝色四格是**灰的**，点不得 |
| 4 | **有蓝色四格** | 点它 → 打开快捷菜单 | 不在局内才安全 |
| 5 | **暂停菜单** | 点「放弃战斗」 | ESC 用过了，只能点按钮 |
| 6 | **放弃确认框** | 点「结束」 | 同上 |
| 7 | 以上都不是 | **按 ESC**，等 4 秒 | 兜底：退一层 |

### ⚠️ 第 3 条是实测逼出来的，不是想出来的

原来的顺序里没有第 3 条，**实测发现它是个真 bug**：

``tests/fixtures/epic7_labyrinth_stone/shop.png``（迷宫商店，**还在局内**）
右上角那颗蓝色四格**照样在**，只是被商店浮层**压暗**了。
模板匹配对亮度缩放**不敏感**（``TM_CCOEFF_NORMED`` 的老毛病），
所以它在这个暗帧上照样得 **0.9053**（阈值 0.82）⇒ 会去点一颗**灰掉的**按钮。

修法：先问「**我在不在局内**」。局内的标志是右上角有 ``‖`` 暂停图标。
实测 12 张帧（``runtime_logs/_probe_home_return_v2.py``）：

| 帧 | ``pause_icon``（‖） |
| --- | --- |
| 迷宫房间 | **1.0000** |
| 迷宫内战斗 | **0.9036** |
| **其余 10 张**（大厅 / 菜单 / 详情页 / 列表 / **商店** / 暂停菜单 / 放弃框 / 准备战斗 / 地图 / 快捷菜单） | 0.2983 ~ **0.5588** |

中间空档 0.5588 → 0.9036（宽 0.34），阈值 0.82 稳稳居中 ⇒ **这是个干净判据。**
商店那个 0.5588 虽然比别的帧高（暗底色下同形），但离 0.82 还差得远。

### 判据互不串门（实测）

``_probe_home_return_v2.py`` 逐帧核对了「这张帧该中哪个判据」与「实际中了哪些」：

| 帧 | 菜单展开 | 蓝四格 | 暂停标题 | 放弃按钮 | 结束按钮 | 大厅主线 | 大厅战斗 | 酒馆 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 大厅 | | 0.8928 ★ | | | | 1.0000 ★ | 1.0000 ★ | |
| 快捷菜单（迷宫） | 1.0000 ★ | | | | | | | 1.0000 ★ |
| 大厅背景+快捷菜单 | 0.9978 ★ | | | | | | | 0.9969 ★ |
| 详情页 | | 1.0000 ★ | | | | | | |
| 暂停菜单 | | | 1.0000 ★ | 1.0000 ★ | | | | |
| 放弃确认框 | | | | | 1.0000 ★ | | | |
| 房间（局内） | | | | | | | | |
| 商店（局内） | | 0.9053 ★ | | | | | | |

**两处「同时中」都是顺序解决掉的，不是靠阈值：**

- 大厅同时中「蓝四格」+「大厅」⇒ **大厅排第 1**，第 4 条轮不到。
- 商店同时中「蓝四格」⇒ **「在局内」排第 3**，第 4 条轮不到。

## 与迷宫强化石的关系

**模板和区域坐标全部直接复用迷宫那条路**（``evidence/labyrinth_stone.py`` 的
``REGIONS``），一个字都没改 —— 那套数字是真机上跑出来的，重调一个都算引入新变量。

**但有一条刻意不学**：迷宫退出局内是**点 ``‖`` 的坐标** ``(1852, 92)``
（实机日志 13:42:35 / 15:00:22 都是 ``动作=open-pause 坐标=(1852, 92)``），
**一次 ESC 都没按过**（全项目 ``games/epic7/`` 只有 ``navigation.py:880`` 那一处
调 ``runtime.back()``）。点死坐标的毛病很明确：换分辨率 / UI 微调就崩。
**用户明确要求新流程一律走 ESC**，所以这里第 3、第 7 条都发键，不点坐标。

## 双上限（沿用老流程的规格）

- **8 次 ESC**：撞上就报 ``RuntimeError("返回首页失败：…8 次后仍未回到大厅")``
- **120 秒观测预算**：撞上就报 ``return_home_timeout``

用户对这两个上限的口径（2026-09-25）：

> 「回家失败相当于是一种最终的报错，说明我们开发的很失败……就是报错嘛。
> 返回首页失败嘛，你用日志来跟其他的报错一样」

⇒ **两者都当普通报错抛，用日志记，跟别的报错一样。** 不做静默降级。

## 出口分类（哪些出口该调它）

| 出口 | 退出码 | 回不回家 | 为什么 |
| --- | --- | --- | --- |
| 正常跑完 | 0 | ✅ | 要衔接下一个任务 |
| 资源耗尽 | 2 | ✅ | 也是正常业务结论 |
| **异常结束** | 1 | ✅ | 用户拍板：「一旦报错，意味着这个代码已经结束了」 |
| **手动停** | 130 | ❌ | 用户喊停，再动游戏是添乱 |

「异常也回家」是 v2 新增的（老流程刻意不接）。接线在 ``main.run_mode``。

## 「有进有出」：每个动作都要回头看（2026-09-25 补）

⚠️ **这一段是实跑翻车换来的，不是设计出来的。**

v2 第一版只做了「看一眼 → 做动作 → 睡一会儿 → 再看一眼」，
**从不回头确认刚那一下有没有用**。实机日志暴露的后果：

    19:25:04 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=1/8
    19:25:06 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=2/8

同一层退了两层，白烧两次返回预算（上限只有 8 次）。

**根因不是「等得不够久」，是「没有眼睛」**：点了酒馆（其实成功了），
0.5 秒后截到的下一帧还在转场、八条分支全对不上，于是走兜底按 ESC ——
**把刚打开的家门又关上了**。等待时间只是掩盖症状，不能代替验收。

所以现在每一处动作都走 ``_ActionVerifier``：**动作前记下页面身份，
动作后等身份确实变了才放行**。判据用的是项目统一口径
（``core/supervisor`` 的页面身份，不是像素差 —— 真帧实测「同一页自己动」
的画面差 0.9004，盖过「真实换页」的下限 0.7840，两个区间完全重叠，
**不看页面名根本分不清换页和同页动画**）。

判「无效」的处理**每处不同、都有依据**：

| 动作 | 无效时怎么办 | 为什么 |
| --- | --- | --- |
| 点酒馆 / 蓝四格 / 放弃 / 确认 | 记日志，交回主循环重新看一眼；**连续两次无效就停用这个动作** | 重看一遍是安全的；但重看**不能变成重试同一招**（见下） |
| **按 ESC** | **不再重复按**，记号后改判当前页 | 重复按 = 同一层退两层，这正是要修的 bug |

### 「重看一遍」≠「重试同一招」（2026-10-19 补）

⚠️ 上面第一行原来说「交回主循环重新看一眼」就完了 —— **那是错的**：
主循环重看之后，条件还成立，于是**又选了同一招**。

真机后果（``desktop_worker.log`` 19:36:51~19:38:20，迷宫商店页）：那颗「蓝色四格」
被商店浮层盖住了但模板照样命中 0.835 ⇒ 每轮点一次、空等 12 秒，
**同一行重复 8 次**，120 秒预算烧光后只报「超过 120 秒仍未回到大厅」。

修法：同一动作在同一页面上**连续两次**验收无效 ⇒ 记入停用表
（``_ActionVerifier.is_retired``），四个点击分支进门先查它 ⇒ 落空即一路下坠到
**⑧ 的 ESC 兜底**。停用时留一行
``状态=停用该动作改走ESC兜底`` 的日志，**不许悄悄换招**。
页面身份一变（哪怕只是 ESC 退成功一层）停用表立刻作废 —— 没用是「这一页上没用」，
不是「永远没用」。

## 降级路径（无导航器时）

``observe`` 是可选的。没有它（或它给不出页面名）时退化为整帧比对 +
固定等待，**但一定会记一行日志说明「验收降级」** ——
不许悄悄跳过，那等于「没测到」冒充「没问题」。
"""

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.battle_supervisor import valid_game_frame
from auto_game_unified.core.matcher import (
    Match,
    load_template,
    locate_with_fallback,
)
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation
from auto_game_unified.games.epic7.evidence.labyrinth_stone import (
    REFERENCE_SIZE,
    REGIONS as LABYRINTH_REGIONS,
)

__all__ = [
    "HomeReturnTemplates",
    "build_home_return_templates",
    "return_home_v2",
]


# ---- 判据 ------------------------------------------------------------------------
#
# ⚠️ **这里曾经有一张「哪些路线走 v2」的白名单（``HOME_RETURN_V2_MODES``），
# 2026-09-26 已整表删除**：用户拍板「肯定要替换的，怎么可能并存呢」，
# 10 条路线现在**一律走 v2**（``navigation.return_home`` 也是 v2 的薄封装）。
# 删除后 `main.HomeReturn` 不再分派，少一处「两套行为并存」的分叉。
#
# 模板名 -> 判定区。区域全部**照抄** ``evidence/labyrinth_stone.py::REGIONS``
# （用 ``LABYRINTH_REGIONS[...]`` 取值，不写字面量），理由见模块 docstring。
_REGIONS = {
    "lobby_story": (1450, 220, 480, 200),       # navigation，不在迷宫 REGIONS 里
    "lobby_arena": (1600, 520, 330, 220),
    "lobby_battle": (1650, 430, 332, 220),
    "quick_menu_button": LABYRINTH_REGIONS["quick_menu_button"],
    "quick_menu_tavern": LABYRINTH_REGIONS["quick_menu_tavern"],
    "pause_icon": LABYRINTH_REGIONS["pause_icon"],
    "pause_title": LABYRINTH_REGIONS["pause_title"],
    "giveup_button": LABYRINTH_REGIONS["giveup_button"],
    "giveup_dialog_finish": LABYRINTH_REGIONS["giveup_dialog_finish"],
}

# 阈值：全部沿用迷宫那套（一律 0.82），**一个都没重调**。
# 大厅主锚点用导航那边的 0.80（``observe()`` 里写死的那个）。
_THRESHOLDS = {name: 0.82 for name in _REGIONS}
_THRESHOLDS["lobby_story"] = 0.80

# 观测预算：与老 ``return_home`` 同规格（transition_frames * 4 帧 × poll_seconds）。
_OBSERVATION_SECONDS = 120.0
_MAX_BACKS = 8

# 按完 ESC 之后的退避（秒）。
#
# ⚠️ 这个值是**实跑**逼出来的，不是想出来的。原先是 ``sleep(1.0)``，
# 2026-09-25 竞技场实跑日志暴露了后果：
#
#     19:25:04 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=1/8
#     19:25:06 模式=导航 流程=v2 动作=按ESC 原因=兜底 次数=2/8
#
# 只隔 2 秒就按了第二下 —— **同一层退了两层**，白烧两次返回预算
# （上限只有 8 次），层数深的时候可能直接把路线按到报错。
#
# 老流程没有这个问题，因为 ``navigation._BACK_RETRY_SECONDS = 15``：
# 按完返回要等 15 秒才判定下一帧。15 秒对「每层都这么等」太慢，
# 用户 2026-09-25 拍板取折中：**等 3~5 秒**，这里取中值 4 秒。
#
# 为什么不改成「等画面确实变了再走」：那需要为每一种可能的转场各配一份判据，
# 而转场本来就认不出来（认得出就不会走兜底分支了）—— 用一个固定的等待
# 换掉一整套判据，是这里划算的做法。
#
# ⚠️ 2026-09-25 补充：这个「固定等待」**不是**验收的替代品。等待只负责
# 「让画面有机会翻过去」，**「到底翻没翻」由 ``_ActionVerifier`` 单独判**。
# 两者是互补的，缺了后者就会重演「同一层连按两次」。
_ESC_SETTLE_SECONDS = 4.0

# 动作验收窗口（秒）：动作发出去之后，最多等这么久，看页面身份有没有变。
#
# 取 12 秒的由来：转场快的（点酒馆、点蓝四格）1~4 秒就翻过去了；
# 慢的（放弃战斗 → 结算 → 回大厅）实测能到 8~10 秒。
# 12 秒给这两类都留了余量，同时**远小于**老的 ``_BACK_RETRY_SECONDS = 15``
# —— 老流程那个是「等满整个转场窗口」，这里只需要「确认有没有动」。
_VERIFY_TIMEOUT_SECONDS = 12.0

# 「画面是黑的 / 根本不是游戏帧」时最多等多少帧就放弃。
#
# ⚠️ 这是 2026-09-26 从**老流程搬过来**的能力：老 ``return_home`` 对无效画面
# 只等不动手（连续黑屏满 ``transition_frames`` 帧就报错）。v2 原本没有这一段，
# 黑屏会掉进「兜底按 ESC」—— 加载中的黑屏按 ESC 是**瞎按**。
# 规格与老流程一致（90 帧 × poll_seconds）。
_INVALID_FRAME_LIMIT = 90

# 同一个**点击**动作在同一个页面上连续无效几次就停用（改走 ESC 兜底）。
#
# 取 2 与「连按两次 ESC 没反应就报错」同一口径：一次无效可能只是转场慢，
# 两次无效就是这条判据在这一页上不成立。⚠️ 2026-10-19 事故：不设这个上限时，
# 商店页上那颗被浮层盖住的「蓝色四格」被点了 8 次、每次空等 12 秒 ⇒ 120 秒超时。
_MAX_INEFFECTIVE_CLICKS = 2


@dataclass(frozen=True)
class HomeReturnTemplates:
    """v2 要用到的一整套模板（大厅三个 + 迷宫那六个）。"""

    lobby_story: np.ndarray
    lobby_arena: np.ndarray
    lobby_battle: np.ndarray
    quick_menu_button: np.ndarray
    quick_menu_tavern: np.ndarray
    pause_icon: np.ndarray
    pause_title: np.ndarray
    giveup_button: np.ndarray
    giveup_dialog_finish: np.ndarray
    # 2026-11-05：「骑士团活动」整屏页（左上标题 + 底部「✕ 点击关闭」）。
    # 骑士团捐赠跑完停在「每周任务」标签，**PC 上 ESC 关不掉这一页**（它不是弹窗），
    # 收尾连按 2 次 ESC 纹丝不动 ⇒「回首页失败」⇒ 整条每日任务链中止。
    # ⚠️ 只在 pc/ 里有图 ⇒ 模拟器加载成 None ⇒ 这一条整段跳过，行为不变。
    # ⚠️ **不能**放进全局弹窗守卫：骑士团捐赠正常流程就会进这页，会被踢出去。
    knights_activity_title: np.ndarray | None = None
    knights_activity_close: np.ndarray | None = None


def build_home_return_templates(
    template_root: Path, navigator_templates
) -> HomeReturnTemplates:
    """从两个已有来源拼出 v2 的全套模板。

    ``template_root`` 是 ``games/epic7/templates``；``navigator_templates`` 是
    ``navigation.build_navigation_templates`` 的产物（大厅那两个锚点在里面）。

    ⚠️ 迷宫那五个**直接读同一批模板文件**（``templates/labyrinth_stone/``），
    与迷宫路线同源，**不另存第二份** —— 同一个控件维护两份迟早漂移。

    ⚠️ 那块大网格 ``quick_menu_grid_top`` **刻意不在这里加载**：它已经不是判据了
    （判「菜单已展开」改用页面身份 ``quick_menu``），详见 ``return_home_v2`` 第 ③ 段。
    """
    labyrinth = template_root / "labyrinth_stone"

    def labyrinth_template(key: str) -> np.ndarray:
        return load_template(str(labyrinth / f"{key}.png"))

    def global_optional(key: str):
        """``templates/global`` 下的可选图：只有 pc/ 里有 ⇒ 模拟器取到 None。"""
        path = template_root / "global" / f"{key}.png"
        return load_template(str(path)) if path.is_file() else None

    return HomeReturnTemplates(
        lobby_story=navigator_templates.lobby_story,
        lobby_arena=navigator_templates.lobby_arena,
        lobby_battle=navigator_templates.lobby_battle,
        quick_menu_button=labyrinth_template("quick_menu_button"),
        quick_menu_tavern=labyrinth_template("quick_menu_tavern"),
        pause_icon=labyrinth_template("pause_icon"),
        pause_title=labyrinth_template("pause_title"),
        giveup_button=labyrinth_template("giveup_button"),
        giveup_dialog_finish=labyrinth_template("giveup_dialog_finish"),
        knights_activity_title=global_optional("knights_activity_title"),
        knights_activity_close=global_optional("knights_activity_close"),
    )


def return_home_v2(
    *,
    templates: HomeReturnTemplates,
    runtime: Runtime,
    observe: Optional[Callable[[np.ndarray], str]] = None,
    dismiss: Optional[Callable[[np.ndarray], bool]] = None,
    invalid_frame_limit: int = _INVALID_FRAME_LIMIT,
    stop_probe: Optional[Callable[[np.ndarray], bool]] = None,
    sleep: Callable[[float], None] = default_sleep,
    poll_seconds: float = 0.5,
) -> np.ndarray:
    """把游戏送回大厅（v2）。

    与老 ``navigation.return_home`` 的接口差别：老流程依赖整个 navigator，
    这里只吃 ``templates + runtime + observe``，所以它也能被没有导航器的场景复用。

    ``observe`` 是**「长眼睛」的入口**：给一张画面，返回一个**页面身份字符串**
    （就是 ``navigator.observe(screen).name``）。它有两个用途：

    1. 动作验收 —— 动作前记身份、动作后等身份变了才放行（见模块 docstring）；
    2. 按 ESC 判「无效」时，能说清「我按完还停在哪个页面上」。

    ⚠️ **它是可选参数，但传与不传行为不同**：不传时退化为整帧比对 + 固定等待，
    并记一行「验收降级」日志。``main.HomeReturn`` 一定会传（它手上有 navigator），
    可选是为了让没导航器的场景（以及老测试）还能用。

    ``dismiss`` 是「清路障」钩子：给一张画面，返回 True 表示**刚刚处理掉一个挡路的
    东西**（系统弹窗 / 退出确认框 / 剧情演出），本帧就此打住、重新观察。

    ⚠️ 为什么不由 v2 自己认这些：它们是**各路线共享的系统弹窗**，模板和判据长在导航层
    （``navigation``），v2 只认识「回家」这一件事。让调用方注入，和 ``observe`` 一个
    道理 —— 一套判据全项目只该有一处，抄第二份迟早漂移。**退出确认框尤其要交给它**：
    那种框上按 ESC 等于「确认退出」，会把游戏真的退掉。

    ``stop_probe`` 是「接力」钩子，语义与老流程**完全一致**（每确认一帧稳定画面
    就问一次，返回 True 就当场停下、把这一帧交还调用方）。它必须排在**所有动作之前**
    —— 排在后面的话，一个认不出页面的接力点会被 ESC 先按掉。

    返回「到家」的那一帧（或者接力命中的那一帧）。
    """
    runtime.log("模式=导航 目标=大厅 流程=v2 状态=开始")
    back_count = 0
    invalid_count = 0
    # 只为了让「120 秒超时」那条报错说清**最后停在哪一页** —— 没有这个，
    # 事故报告里就只剩「超过 120 秒」五个字，跟 8 行一模一样的动作日志对不上。
    last_observed = ""
    started_at = runtime.now()
    stable = StableObservation(required=2)
    verifier = _ActionVerifier(runtime, observe, sleep, poll_seconds)

    def _observe_page(screen: np.ndarray) -> str:
        """取页面身份字符串（与导航层 ``observe`` 同一套口径）。

        有 ``observe`` 时直接用它的页面名；没有（降级场景）时用模板 ``_at_lobby``
        认大厅、其余记为非大厅 —— 这样降级也走「页面名两帧」的稳定约定，
        不再退化到像素比对。
        """
        if observe is None:
            return "lobby" if _at_lobby(screen, templates) else "unknown"
        try:
            return observe(screen) or ""
        except Exception:
            return ""

    while True:
        if runtime.now() - started_at >= _OBSERVATION_SECONDS:
            diagnostic = _save(runtime, "return_home_v2_timeout")
            raise RuntimeError(
                f"返回首页失败：超过 {_OBSERVATION_SECONDS:.0f} 秒仍未回到大厅"
                f"（最后一帧认作页面={last_observed or '未知'}）；"
                f"已保存诊断 {diagnostic}"
            )
        screen = runtime.capture()
        if runtime.diagnostic_dir is not None:
            runtime.save_current_frame(screen)

        # ⓪ 黑屏 / 不是游戏帧：**什么都不做，只等**。
        #
        # ⚠️ 这段是从老流程搬过来的（v2 原本没有）：黑屏通常是加载中，
        # 而 v2 的所有判据在黑屏上都命中不了 ⇒ 会掉进「兜底按 ESC」，
        # 那就是对着加载画面瞎按键。一直黑着就报错。
        #
        # 判据直接用 ``valid_game_frame``（与导航层同一个口径），**不再多问一次
        # 页面识别**：每帧问几次页面识别是有约定的（替身、验收都按它对齐），
        # 多问一次会让「前两帧真、之后假」这类替身提前失效。
        if not valid_game_frame(screen):
            invalid_count += 1
            if invalid_count >= invalid_frame_limit:
                diagnostic = _save(runtime, "return_home_v2_black_screen")
                raise RuntimeError(
                    f"返回首页失败：画面持续黑屏或非游戏帧"
                    f"（连续 {invalid_count} 帧）；已保存诊断 {diagnostic}"
                )
            sleep(poll_seconds)
            continue
        invalid_count = 0

        observed = _observe_page(screen)
        last_observed = observed
        is_stable = stable.update(observed)

        # ① 大厅 —— **必须第一个问**。大厅右上角也有蓝色四格，晚一步就会去点它。
        #
        # ⚠️ 到家**也要问一次接力探针**（答案必然是「不命中」）—— 不是为了结果，
        # 是为了接口形状与老流程一致：`main._enter_mode` 有一条接线检查
        # （「挂了探针却一次没问过 ⇒ 接线断了」），那是骑士团捐赠两次事故后立的规矩。
        # 这里图省事提前返回的话，那条检查会在「开局就在大厅」这个最常见的情况下误报，
        # 逼着人放松检查 —— 那是拿掉护栏换方便，不划算。
        #
        # ⚠️ 返回条件：**连续两帧稳定认出「大厅」页面名才返回**（与导航层
        # ``StableObservation(required=2)`` 同一套）。「第一帧认出大厅就返回」是
        # 之前那个孤例 —— 会把还在动画的过渡大厅帧交出去，导航层认不到左侧入口就 ✗。
        if observed == "lobby" and is_stable:
            if stop_probe is not None:
                stop_probe(screen)
            runtime.log("模式=导航 流程=v2 页面=大厅 状态=已确认")
            return screen

        # ①-补 **等画面稳定**（排在大厅判定之后）：页面身份还在变时先等，
        # 别对着「还在动」的页面误判/误点。
        #
        # ⚠️ 稳定判据已**统一到全局的** ``StableObservation(required=2)``（**按页面名**
        # 两帧），与导航层 ``_wait_for_page`` / ``_transition`` 同一套 —— 不再用像素比对
        # （旧 ``_StableTwo`` 那种）。动画大厅页名永远是「大厅」⇒ 秒稳、不慢；
        # 且「过渡大厅帧」交给导航层方案 A 兜底（认不到 ``lobby_shop_entry`` 就重等稳定来源页）。
        # 「回家」全程只有这一处稳定判据，和全项目口径一致，好维护、好扩展。
        if not is_stable:
            runtime.log("模式=导航 流程=v2 状态=等画面稳定 原因=页面身份还在变")
            sleep(poll_seconds)
            continue

        # ② 清路障：系统弹窗 / 退出确认框 / 剧情演出（能力由调用方注入，见 docstring）。
        #    排在接力**之前** —— 弹窗挡着的时候，接力点根本认不出来。
        if dismiss is not None and dismiss(screen):
            stable.reset()
            sleep(poll_seconds)
            continue

        # ③ 接力：命中就把这一帧交还调用方（口径与老流程一致）。
        if stop_probe is not None and stop_probe(screen):
            runtime.log("模式=导航 流程=v2 动作=接力点命中 状态=停止返回大厅")
            return screen

        # ③ 快捷菜单已展开 ⇒ 点酒馆（一步到家）。
        #
        # ⚠️ 四个点击分支都带 ``is_retired`` 闸门：同一个动作在同一页上连续两次
        # 验收无效，就**不许再选它**，让流程落到 ⑧ 的 ESC 兜底。没有这道闸门，
        # 2026-10-19 那次就在商店页上把「打开快捷菜单」点了 8 次、空耗 120 秒。
        # ⚠️ 「菜单是否已展开」**不在这里自己判**，直接用 ``observe`` 给出的页面身份
        # ``quick_menu`` —— 导航层那份判据是两颗菜单专属图标
        # （``quick_menu_hero`` / ``quick_menu_knights``：菜单帧 0.997+，全库次高 0.41）。
        #
        # 旧写法要求 ``quick_menu_grid_top``（迷宫那块大网格）与酒杯**同时**命中，
        # 2026-10-30 18:31 实跑就栽在这里：竞技场页上那块网格只有 **0.7977**、门槛 0.82，
        # 差 0.0023 没过 ⇒ 酒杯明明 0.9979（满分）也点不了 ⇒ 只能 ESC 关菜单 →
        # 回到竞技场 → 再开菜单，8 轮耗掉 120 秒，**后面 5 条路线全部没跑**。
        # 那块网格罩住整片菜单底图，对底页不同 / 节日装饰敏感（`navigation` 里两处注释
        # 早已写明「刻意不用」，只有这条回家路径漏改）。
        tavern = _locate(screen, templates.quick_menu_tavern, "quick_menu_tavern")
        if (
            observed == "quick_menu"
            and tavern is not None
            and not verifier.is_retired("点酒馆", observed)
        ):
            runtime.log(
                f"模式=导航 流程=v2 页面=快捷菜单 动作=点酒馆 "
                f"置信度={tavern.score:.3f} 坐标={tavern.center}"
            )
            verifier.act(
                "点酒馆",
                lambda: runtime.click(tavern.center, "go-tavern"),  # noqa: B023
                screen,
            )
            stable.reset()
            sleep(poll_seconds)
            continue

        # ④ 在局内（右上角有 ‖）⇒ 按 ESC。
        #    ⚠️ 必须在「蓝色四格」**前面**：局内那颗四格是灰的，但亮度变化骗不过
        #    模板匹配（商店帧实测 0.9053）⇒ 不先挡住就会去点灰按钮。
        if _locate(screen, templates.pause_icon, "pause_icon") is not None:
            back_count = verifier.press_esc(back_count, observed, screen, "局内")
            stable.reset()
            continue

        # ⑤ 有蓝色四格 ⇒ 点它打开快捷菜单。
        #
        # ⚠️ 这一条是 2026-10-19 事故的正主：商店页上那颗四格**被浮层盖住了**，
        # 但模板匹配对压暗不敏感 ⇒ 照样 0.835（阈值 0.80）。点下去无效 ✓ 由
        # ``is_retired`` 兜住，两次之后就改走 ESC。
        blue_grid = _locate(
            screen, templates.quick_menu_button, "quick_menu_button"
        )
        if blue_grid is not None and not verifier.is_retired("打开快捷菜单", observed):
            runtime.log(
                f"模式=导航 流程=v2 动作=打开快捷菜单 "
                f"置信度={blue_grid.score:.3f} 坐标={blue_grid.center}"
            )
            verifier.act(
                "打开快捷菜单",
                lambda: runtime.click(blue_grid.center, "open-quick-menu"),  # noqa: B023
                screen,
            )
            stable.reset()
            sleep(poll_seconds)
            continue

        # ⑥ 暂停菜单 ⇒ 点「放弃战斗」。
        if (
            _locate(screen, templates.pause_title, "pause_title") is not None
            and not verifier.is_retired("放弃战斗", observed)
        ):
            give_up = _locate(screen, templates.giveup_button, "giveup_button")
            if give_up is None:
                raise RuntimeError("返回首页失败：暂停菜单里找不到「放弃战斗」按钮")
            runtime.log(
                f"模式=导航 流程=v2 页面=暂停菜单 动作=放弃战斗 "
                f"置信度={give_up.score:.3f} 坐标={give_up.center}"
            )
            verifier.act(
                "放弃战斗",
                lambda: runtime.click(give_up.center, "give-up"),  # noqa: B023
                screen,
            )
            stable.reset()
            sleep(poll_seconds)
            continue

        # ⑦ 放弃确认框 ⇒ 点「结束」。
        finish = _locate(
            screen, templates.giveup_dialog_finish, "giveup_dialog_finish"
        )
        if finish is not None and not verifier.is_retired(
            "结束（放弃战斗）", observed
        ):
            runtime.log(
                f"模式=导航 流程=v2 页面=放弃战斗确认框 动作=结束 "
                f"置信度={finish.score:.3f} 坐标={finish.center}"
            )
            verifier.act(
                "结束（放弃战斗）",
                lambda: runtime.click(finish.center, "confirm-give-up"),  # noqa: B023
                screen,
            )
            stable.reset()
            sleep(poll_seconds)
            continue

        # ⑦.5 「骑士团活动」整屏页 ⇒ 点底部「✕ 点击关闭」（PC 专属，模拟器整段跳过）。
        if not verifier.is_retired("关闭骑士团活动", observed):
            activity_close = _activity_close_point(screen, templates)
            if activity_close is not None:
                runtime.log(
                    f"模式=导航 流程=v2 页面=骑士团活动 动作=点击关闭 "
                    f"置信度={activity_close.score:.3f} 坐标={activity_close.center}"
                )
                verifier.act(
                    "关闭骑士团活动",
                    lambda center=activity_close.center: runtime.click(
                        center, "close-knights-activity"
                    ),
                    screen,
                )
                stable.reset()
                sleep(poll_seconds)
                continue

        # ⑧ 都不是 ⇒ 按 ESC 退一层。
        back_count = verifier.press_esc(back_count, observed, screen, "兜底")
        stable.reset()


class _ActionVerifier:
    """「动作发出去之后，回头看这一下到底生效没有」。

    这是 v2 的**眼睛**。2026-09-25 之前它不存在，于是实跑出现「同一层连按两次 ESC」
    —— 详见模块 docstring。

    ## 判据：页面身份，不是像素差

    生效的定义是「**页面身份变了**」（``observe`` 给的字符串），不是「画面像素变了」。
    真帧实测（``frac_gt8``）：同一页自己动可以到 0.9004，真实换页最低 0.7840
    —— **两个区间完全重叠**，不看页面名分不出「换页」和「同页动画」。
    这个结论已经写进项目统一口径（``core/supervisor.left_page``）。

    ## 降级：没有 ``observe`` 时不装死

    ``observe is None``（或它给不出页面名）时，本对象**明确记一行日志说验收降级了**，
    然后按「画面有没有变」粗判。降级必须看得见 ——
    悄悄跳过等于「没测到」冒充「没问题」。
    """

    def __init__(
        self,
        runtime: Runtime,
        observe: Optional[Callable[[np.ndarray], str]],
        sleep: Callable[[float], None],
        poll_seconds: float,
    ) -> None:
        self._runtime = runtime
        self._observe = observe
        self._sleep = sleep
        self._poll_seconds = poll_seconds
        # 降级日志只记一次：每次动作都刷屏会把真正的日志淹掉。
        self._downgrade_logged = False
        # 「按了 ESC 但页面没动」的连续次数：用来给重复按止损。
        self._esc_ineffective = 0
        # 「点了按钮但页面没动」的连续次数，按动作名分开记。
        self._click_ineffective: dict[str, int] = {}
        # 已被证明「在这个页面上点了没用」的动作 ⇒ 动作名 -> 当时的页面身份。
        # 页面身份一变就重新放开（见 ``is_retired``）。
        self._retired_clicks: dict[str, str] = {}

    # ---- 动作 ----------------------------------------------------------------

    def act(
        self,
        action: str,
        perform: Callable[[], None],
        before_screen: np.ndarray,
    ) -> bool:
        """做一个动作，然后验收。返回「这一下生效了吗」。

        ``before_screen`` 是**动作前**那一帧（调用方刚截的）。
        生效判「页面身份变了」；降级时判「画面明显变了」。

        ⚠️ ``return_home_v2`` 里有 4 处 ``verifier.act(..., lambda: ...)`` 带
        ``# noqa: B023``：那些 lambda 定义在 ``while`` 循环里、引用当轮才赋值的局部
        变量，而 ``perform()`` 就在本方法里**当场同步调用**（见下面那行），取不到下一轮的
        值 —— ruff 只能看语法、判不出调用时机，是误报。**人工核过**才标的 noqa；
        哪天 ``act`` 改成延迟/批量执行，这 4 处就会变成真 bug（届时要改成
        ``lambda x=x:`` 把值绑进闭包）。
        """
        before = self._page_of(before_screen)
        self._runtime.log(
            f"模式=导航 流程=v2 动作={action} 状态=已发出 动作前页面={before or '未知'}"
        )
        perform()
        changed = self._wait_for_change(action, before, before_screen)
        self._record_click_verdict(action, changed, before)
        return changed

    # ---- 「点了没用」的止损 -----------------------------------------------------

    def _record_click_verdict(self, action: str, changed: bool, page: str) -> None:
        """记一次点击验收结果，连续无效就把这个动作**停用**。

        ⚠️ 2026-10-19 真机事故：``return_home_v2`` 在迷宫的**商店页**（对导航层是
        ``unknown``）上认出了「蓝色四格」（0.835，阈值 0.80 —— 那颗按钮其实被商店
        浮层盖住了），于是点它。点一次无效、再点、再点……每一轮都要等满
        ``_VERIFY_TIMEOUT_SECONDS``(12 秒)，**整整耗掉 120 秒预算**才报超时。
        日志里 8 轮长得一模一样，事后完全看不出「它到底想干什么」。

        止损口径与「连按两次 ESC 没反应就报错」同源：**同一个动作在同一个页面上
        连续两次证明没用，就不许再选它**，让主循环落到 ESC 兜底那一档
        （「未登记页必须有有界逃生门」）。
        """
        if changed:
            self._click_ineffective.pop(action, None)
            self._retired_clicks.pop(action, None)
            return
        count = self._click_ineffective.get(action, 0) + 1
        self._click_ineffective[action] = count
        if count < _MAX_INEFFECTIVE_CLICKS:
            return
        self._retired_clicks[action] = page
        self._runtime.log(
            f"模式=导航 流程=v2 动作={action} 连续无效={count} "
            f"页面={page or '未知'} 状态=停用该动作改走ESC兜底"
        )

    def is_retired(self, action: str, page: str) -> bool:
        """这个动作在**当前页面**上是否已被证明没用？页面一变就重新放开。

        为什么要跟着页面身份走：动作没用是「这一页上没用」，不是「永远没用」。
        卡在同一个 ``unknown`` 上时它一直停用（正是我们要的），一旦换了页
        （哪怕只是 ESC 退成功一层），旧结论立刻作废、动作重新可用。
        """
        retired_on = self._retired_clicks.get(action)
        if retired_on is None:
            return False
        if retired_on != page:
            self._retired_clicks.pop(action, None)
            self._click_ineffective.pop(action, None)
            return False
        return True

    def press_esc(
        self,
        back_count: int,
        before_page: str,
        before_screen: np.ndarray,
        reason: str,
    ) -> int:
        """按一次 ESC 并验收。返回新的计数。

        ``before_page`` 是**按 ESC 之前那一帧的页面名**（由主循环算好传进来），
        不要在这里再对画面调一次 ``observe`` 重算 —— 那是同一帧，结果必一致，
        重算只是白调一次识别；而且「点击验收」的判据对「识别被调了几次」是敏感的
        （``test_the_verdict_follows_the_page_identity_not_the_pixels`` 就靠这个钉死）。
        「按之前 vs 按之后」的页面名对比在 ``_wait_for_change`` 里做（那是**不同**的两帧，
        必须各认一次）。``before_screen`` 只留给降级分支做像素比对，正常路径不用它。

        ⚠️ **验收判「无效」时，不重复按同一个 ESC** —— 那正是本次要修的 bug。
        无效时把控制权交回主循环（它下一轮会重新识别当前页面，该走别的分支就走），
        同时立「连续无效」的止损：

        - 第 1 次无效：记日志，继续。可能只是转场慢，主循环重看一遍就知道了。
        - 连续第 2 次无效：说明 ESC 在这个页面上**根本不管用**（比如卡在某个
          不吃 ESC 的浮层上），再按下去只是烧预算 ⇒ **报错并留诊断**。

        为什么止损点选「2」而不是 8（上限）：8 次是留给「层数深、每层退一次」
        这种正常情况的；**同一条 ESC 连按两次都没反应是另一种故障**，
        跟层数无关。硬撑到 8 次只会把预算全烧在同一个死页面上，
        最后还是报错 —— 但那时日志里已经分不清是哪一次出的问题了。
        """
        back_count += 1
        if back_count > _MAX_BACKS:
            diagnostic = _save(self._runtime, "return_home_v2_failed")
            raise RuntimeError(
                f"返回首页失败：按 ESC {_MAX_BACKS} 次后仍未回到大厅；"
                f"已保存诊断 {diagnostic}"
            )
        self._runtime.log(
            f"模式=导航 流程=v2 动作=按ESC 原因={reason} "
            f"次数={back_count}/{_MAX_BACKS}"
        )
        before = before_page
        self._runtime.back("受控返回大厅")
        self._sleep(_ESC_SETTLE_SECONDS)
        if self._wait_for_change("按ESC", before, before_screen):
            self._esc_ineffective = 0
            return back_count

        self._esc_ineffective += 1
        self._runtime.log(
            f"模式=导航 流程=v2 动作=按ESC 原因={reason} 返回验收=无效 "
            f"动作前页面={before or '未知'} 连续无效={self._esc_ineffective} "
            "状态=不重复按同一个ESC"
        )
        if self._esc_ineffective >= 2:
            # ⚠️ 连续两次 ESC 都纹丝不动 ⇒ **先确认模拟器输入通道还在不在**。
            #
            # 2026-10-30 22:40 月塔那次就是这样收尾的：从「战斗开始」开始，
            # 之后「打开快捷菜单」×2、「ESC」×2 **全部**无效 —— 说明不是某个按钮
            # 点歪了，而是整条输入通道断了（画面本身完全正常，两张诊断图都能看清）。
            # 当时日志里看不出这一点，只能事后翻诊断图猜。
            # 与导航那边同一个口径（``navigation`` 在「连点两次纹丝不动」时也调这个）。
            self._runtime.ensure_input_channel()
            diagnostic = _save(self._runtime, "return_home_v2_esc_no_effect")
            raise RuntimeError(
                f"返回首页失败：连按 {self._esc_ineffective} 次 ESC 页面都没有变化"
                f"（停在页面={before or '未知'}）；已保存诊断 {diagnostic}"
            )
        return back_count

    # ---- 内部 ----------------------------------------------------------------

    def _wait_for_change(
        self, action: str, before: str, before_screen: np.ndarray
    ) -> bool:
        """等页面身份确实变了才放行；超时就判「没生效」。"""
        if self._observe is not None and before:
            started = self._runtime.now()
            while True:
                screen = self._runtime.capture()
                if self._runtime.diagnostic_dir is not None:
                    self._runtime.save_current_frame(screen)
                current = self._page_of(screen)
                if current and current != before:
                    self._runtime.log(
                        f"模式=导航 流程=v2 动作={action} 点击验收=生效 "
                        f"从={before} 到={current} "
                        f"耗时={self._runtime.now() - started:.1f}秒"
                    )
                    return True
                if self._runtime.now() - started >= _VERIFY_TIMEOUT_SECONDS:
                    self._runtime.log(
                        f"模式=导航 流程=v2 动作={action} 点击验收=无效 "
                        f"页面={before} 已等={_VERIFY_TIMEOUT_SECONDS:.0f}秒"
                    )
                    return False
                self._sleep(self._poll_seconds)

        self._log_downgrade_once()
        return _StableTwo.sees_change(before_screen, self._runtime.capture())

    def _page_of(self, screen: np.ndarray) -> str:
        observe = self._observe
        if observe is None:
            return ""
        try:
            return observe(screen) or ""
        except Exception as error:  # noqa: BLE001 —— 认不出不等于流程该崩
            # ``observe`` 认不出来时会返回 ``unknown``/``invalid``，正常；
            # 真抛异常说明识别链路本身坏了 —— 不该让回家流程跟着崩，
            # 但**必须留痕**，否则又是「悄悄降级」。
            self._runtime.log(
                f"模式=导航 流程=v2 状态=页面识别异常 错误={error!r} 验收=降级"
            )
            return ""

    def _log_downgrade_once(self) -> None:
        if self._downgrade_logged:
            return
        self._downgrade_logged = True
        self._runtime.log(
            "模式=导航 流程=v2 状态=验收降级 "
            "原因=没有页面识别能力(observe 未接入) "
            "替代判据=整帧比对 说明=这不是正常路径，只是不让老调用方崩掉"
        )


def _at_lobby(screen: np.ndarray, templates: HomeReturnTemplates) -> bool:
    """大厅判定：**双锚点组合**，与 ``navigation.observe()`` 同一套口径。

    单靠 ``lobby_story`` 不够 —— 它在大厅上 1.0000，但别的地方也可能像。
    要求「主线入口」与（「竞技场」或「战斗」）**同时**命中，取两者的低分。
    """
    story = _locate(screen, templates.lobby_story, "lobby_story")
    if story is None:
        return False
    for name in ("lobby_arena", "lobby_battle"):
        template = getattr(templates, name, None)
        if template is None:
            continue
        secondary = _locate(screen, template, name)
        if secondary is not None:
            return True
    return False


# 「骑士团活动」整屏页（PC 专属）。区域照那两张图的实测包围盒留余量：
# 标题 bbox (103,152) 215x42；「点击关闭」bbox (933,1082) 92x21。
_ACTIVITY_TITLE_REGION = (60, 120, 340, 110)
_ACTIVITY_CLOSE_REGION = (820, 1040, 400, 80)
_ACTIVITY_TITLE_THRESHOLD = 0.82
_ACTIVITY_CLOSE_THRESHOLD = 0.85


def _activity_close_point(
    screen: np.ndarray, templates: "HomeReturnTemplates"
) -> Optional[Match]:
    """「骑士团活动」页底部「点击关闭」。

    两张图任一缺失（模拟器就是这样）⇒ 直接 None，整段跳过，行为与历史一致。
    标题不成立 ⇒ 也返回 None —— **不许**只凭「有个关闭按钮」就点。
    """
    if (
        templates.knights_activity_title is None
        or templates.knights_activity_close is None
    ):
        return None
    title = locate_with_fallback(
        "knights_activity_title",
        screen,
        templates.knights_activity_title,
        _ACTIVITY_TITLE_THRESHOLD,
        region=_ACTIVITY_TITLE_REGION,
        reference_size=REFERENCE_SIZE,
    )
    if title is None:
        return None
    return locate_with_fallback(
        "knights_activity_close",
        screen,
        templates.knights_activity_close,
        _ACTIVITY_CLOSE_THRESHOLD,
        region=_ACTIVITY_CLOSE_REGION,
        reference_size=REFERENCE_SIZE,
    )


def _locate(
    screen: np.ndarray, template: np.ndarray, name: str
) -> Optional[Match]:
    # 走 ``locate_with_fallback``（与导航层、视觉诊断**同一把尺子**）：原样先比，
    # 不过阈才按 ``SMOOTH_FALLBACK_ANCHORS`` / ``SCALE_FALLBACK_ANCHORS`` 补一次。
    # 名字不在任何名单里时，这里的判定与从前逐字节一致。
    #
    # ⚠️ 2026-11-04 00:09 那场事故就是在这里漏的：`lobby_story` 在 PC 上只有
    # 0.7937（阈 0.80），直连 `find_template` 时兜底对它不生效 ⇒ 认不出「已经到家」
    # ⇒ 点四格 → 判快捷菜单 → 找不到酒馆 → ESC → 又 `unknown`，死循环 120 秒。
    return locate_with_fallback(
        name,
        screen,
        template,
        _THRESHOLDS[name],
        region=_REGIONS[name],
        reference_size=REFERENCE_SIZE,
    )


def _save(runtime: Runtime, label: str) -> str:
    if runtime.diagnostic_dir is None:
        return "not-configured"
    return runtime.save_diagnostic(label)


class _StableTwo:
    """像素级两帧比对 —— **仅作降级用**。

    ⚠️ 不复用 ``core.supervisor.StableObservation`` 那边按**页面名**比对的版本 ——
    这里没有页面名，只能按**画面本身**比。按图片比对会让「淡入中的同一页」
    被判成不稳定而白等，所以这里比的是「前后两帧是否几乎一样」。

    ⚠️ 2026-09-26：**回家主循环已不再用本类**。`return_home_v2` 的稳定判据
    统一改成了全局的 ``StableObservation(required=2)``（页面名两帧，与导航层
    ``_wait_for_page`` 同一套）。本类的 ``update`` / ``reset`` 现在**完全没被调用**，
    只保留 ``sees_change`` 给 ``_ActionVerifier`` 当「没有 observe 时的降级比对」
    （没有页面身份时只能退而求其次看像素差）。
    """

    _TOLERANCE = 3.0

    def __init__(self) -> None:
        self._previous: Optional[np.ndarray] = None

    def update(self, screen: np.ndarray) -> bool:
        previous = self._previous
        self._previous = screen
        if previous is None or previous.shape != screen.shape:
            return False
        difference = np.abs(
            screen.astype(np.int16) - previous.astype(np.int16)
        )
        return float(difference.mean()) <= self._TOLERANCE

    def reset(self) -> None:
        self._previous = None

    @classmethod
    def sees_change(cls, before: np.ndarray, after: np.ndarray) -> bool:
        """两帧「差得够明显吗」—— **只用于没有页面识别时的降级判据**。

        ⚠️ 别拿它当正常的验收判据：真帧实测同一页自己动也能差很多
        （``frac_gt8`` 到 0.9004），它会漏掉「页面没换但画面在动」，
        也会把「转场动画」误判成生效。正常路径一律走页面身份。
        """
        if before.shape != after.shape:
            return True
        difference = np.abs(
            after.astype(np.int16) - before.astype(np.int16)
        )
        return float(difference.mean()) > cls._TOLERANCE
