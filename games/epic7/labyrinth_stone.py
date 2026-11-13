"""迷宫强化石（``labyrinth_stone``）路线：每天一次的迷宫强化石采购。

## 这一轮要走的完整链路

```
大厅 → 战斗菜单（一般页）→ 迷宫卡片 → 迷宫列表「混乱的提雷尔城」→ 迷宫详情页
  ├ 确保区域列表选中的是 **1 区域**（不是就切过去）
  └ 「选择队伍」→ 准备战斗页 → 「战斗开始」
进迷宫 → 开场剧情（可跳过）→ 十字路口房间
  ├ 开地图 → 把视野拖到左上 → 找「左下蓝松鼠 / 右下宝箱」那个出口 pin → 传送（3 士气）
  ├ 落地房 → 点左下 **W** 徽记赶路（最多 3 次）→ 流浪商人（蓝松鼠）的房间
  └ 点**蓝松鼠本体** → 商店 → 买强化石，以及友情点数 / 圣约书签 / 神秘书签（买完那行变灰）
收工 → 商店返回箭头 → 暂停菜单 → 放弃战斗 → 确认「结束」
  → 落回迷宫详情页 → 右上角蓝色菜单 → 酒馆 → 大厅
```

## 什么时候才能「放弃」（2026-09-25 真机翻车后立的规矩）

进迷宫有**两段走路**：进场走到第一个十字路口、传送落地后往西走到流浪商人。走路期间
画面一直在变，控件还在淡入 —— 翻车那次就是在第一段走路的第 0.3 秒放弃的。

**「还没到」和「做不成」是两件事，判据必须分开**（用户原话）：

> 我们正常人为什么放弃？至少得先到流浪商人那边，进商店，发现里面的强化石都卖光了，
> 才收工。**跟那个菱形有什么关系？**

于是：

| 情形 | 属于 | 处理 |
| --- | --- | --- |
| 走路 / 过场 / 控件淡入期间认不出锚点 | **还没到** | 抛 ``UnrecognizedScreen`` **等**，绝不放弃 |
| 商店确认没有可买的强化石了 | **做成了**（唯一正当收工） | 正常放弃回家，算完成 |
| 地图拖 3 次仍找不到出口 / 往西走 3 间房还没到商人 | **做不成**（有界重试走完） | 放弃回家，**记真实原因**，Runner 报错（退出码 1） |

⚠️ **「没看见某个东西」永远不能当放弃的理由** —— 那等于闭着眼睛按不可逆按钮。
放弃只能由**看见了的事实**（商店卖光）或**有界重试真的走完了**触发。
迷宫不消耗门票（用户 2026-09-25 确认），所以「白跑一趟」的代价只是时间。

⚠️ 整条链走完人已经回到**大厅**，所以 main 注入的「收尾回首页」是空转 ——
这是刻意的：中途停在迷宫里时 ``return_home`` 只会反复按 ESC 在暂停菜单上进退。

## 六条决定了写法的实测事实

细节与实测数据都在 ``games/epic7/evidence/labyrinth_stone.py`` 的 docstring 里，这里只留结论：

1. **迷宫房间会被 ``battle_scene_visible`` 误报成战斗中**，所以本路线
   ``_BATTLE_ENTRY_ACTION = None``：我们只是「进了迷宫」，不存在已承诺战斗。
   房间与真战斗靠 ``morale_smiley`` / ``battle_turn_bar`` 分开。
2. **迷宫详情页会来两次**（进场前 / 放弃后），画面上一模一样、下一步却完全不同
   ⇒ 用 ``entered`` 这个跨帧进度标记区分。它是唯一一个画面里看不出来的状态。
3. **区域列表选中的是哪一区，只能靠「选中框和 1 区域标签的纵向落差」读**：
   实测选中时落差 69，行高就有 141 ⇒ 容差 90 两边都留得下。
4. **地图没有夹紧**，开图时视野停在右下角 ⇒ 只能「搜 → 拖 → 再搜」，正确出口 pin
   靠**布局**认（目标 pin 的左下是蓝松鼠 pin、右下是宝箱 pin，偏移 (+171, −159)）。
5. **商店买什么，要过两道锁**（2026-09-25 真机买错东西换来的，缺一不可）：
   ① 这一行的**类别标签**写着「强化石」—— 类别中心 y = 购买按钮中心 y **−82**
      （⚠️ 原来写成 **+139**，方向反了 ⇒ 每一行都拿下一行的类别判断自己是什么，
      于是「强化拳套」18,000 被当成强化石**真的买了**）；
   ② 这一行的**商品名里有一个「石」字**（强化石 0.94~1.00 / 强化拳套 0.51）。
   再加**按钮相对亮度 ≥1.20** 认出「这一行买过了没」。认不出就**一律不点**。
6. **左上角那颗地图按钮是半透明蓝菱形，模板分数在走路/淡入期间只有 0.34~0.49**
   （站定才 1.000），所以开地图改判「左上角有没有一坨蓝色、重心在哪」：
   模板 ≥0.30 **或** 蓝色占比 ≥0.15，两条取或。走路帧实测蓝色 0.20、站定 0.27~0.28。

## 转场契约（``_REQUIRE_TRANSITION_CONTRACT = True``）

| 动作 | source_page | 出口验收 |
|---|---|---|
| ``open-labyrinth`` | 战斗菜单·一般页 | 迷宫列表 |
| ``open-labyrinth-entry`` | 迷宫列表 | 迷宫详情页 |
| ``select-region-1`` | 迷宫详情页（1 区域**还能选**） | 页内：1 区域那一行出现金色选中框 |
| ``open-team`` | 迷宫详情页 | 准备战斗页 |
| ``start-battle`` | 准备战斗页 | 迷宫房间 / 开场剧情 / 迷宫内战斗 |
| ``skip-story`` | 开场剧情 | 迷宫房间 |
| ``open-map`` | 迷宫房间 | 地图页 |
| ``pan-map`` | 地图页 | 页内：地图内容整体右下移（商人 pin 进入视口） |
| ``use-exit-pin`` | 地图页 | 传送确认弹窗 |
| ``confirm-teleport`` | 传送确认弹窗 | 迷宫房间 |
| ``cancel-teleport`` | 传送确认弹窗 | 地图页 / 迷宫房间（弹窗不是本路线叫出来的） |
| ``cancel-unknown-dialog`` | 认不出标题的双按钮弹窗 | 地图页 / 迷宫房间 / 商人房 / 商店页 |
| ``close-map`` | 地图页 | 迷宫房间（拖 3 次仍找不到出口 ⇒ 收工） |
| ``walk-west`` | 迷宫房间 | 页内：走进另一个房间（画面整体换掉 / 出现「流浪商人」标签） |
| ``open-shop`` | 商人房 | 商店页 |
| ``buy-stone`` | 商店页 | 购买确认弹窗 |
| ``confirm-buy`` | 购买确认弹窗（**本路线刚点过「购买」**） | 商店页 |
| ``cancel-buy`` | 购买确认弹窗（不是本路线叫出来的） | 商店页 |
| ``scroll-shop`` | 商店页 | 页内：列表整体上移（出现新的「购买」行） |
| ``leave-shop`` | 商店页 | 商人房 |
| ``open-pause`` | 迷宫房间 / 迷宫内战斗 / 商人房 | 暂停菜单 |
| ``give-up`` | 暂停菜单 | 放弃战斗确认框 |
| ``confirm-give-up`` | 放弃战斗确认框 | 迷宫详情页 |
| ``open-quick-menu`` | 迷宫详情页（**已进过迷宫**，或 1 区域已「✓完成探险」） | 右上角快捷菜单 |
| ``go-tavern`` | 右上角快捷菜单 | 大厅 |

⚠️ 后一种 ``open-quick-menu`` 是 2026-11-04 加的**正常收工门**：1 区域写着
「✓完成探险」时那一行不可点，四次 ``select-region-1`` 全是无效点击（14:18 真机）。
判据是「绿字状态 + 必须贴在 1 区域标签下方」两维，回家后 ``_at_lobby`` 写一条
专门的收工理由，不谎报「商店里没有可买的强化石」。
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable, Optional

import numpy as np

from auto_game_unified.core.matcher import (
    Match,
    find_all_templates,
    find_best_template,
    load_template,
    locate_with_fallback,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import EvidenceState
from auto_game_unified.games.epic7.evidence.labyrinth_stone import (
    BUY_BUTTON_WHITE_PIXELS,
    BUY_ROW_PAIR_TOLERANCE,
    BUY_TO_CATEGORY_DY,
    STONE_NAME_TOLERANCE,
    STONE_NAME_TO_BUY_DY,
    MAP_BUTTON_BLUE_RATIO,
    MAP_BUTTON_MIN_SCORE,
    MAP_CANVAS,
    MERCHANT_PIN_TO_TARGET,
    REFERENCE_SIZE,
    build_labyrinth_stone_evidence,
    button_white_pixels,
    map_button_blue_blob,
)
from auto_game_unified.games.epic7.resume_probe import ResumePoint
from auto_game_unified.games.epic7.route_action import RouteAction
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen
from auto_game_unified.games.epic7.template_paths import is_pc, is_template_root


class LabyrinthStoneState(Enum):
    BATTLE_MENU = "battle_menu"
    LABYRINTH_LIST = "labyrinth_list"
    LABYRINTH_DETAIL = "labyrinth_detail"
    TEAM = "team"
    STORY = "story"
    ROOM = "room"
    MAP = "map"
    TELEPORT_CONFIRM = "teleport_confirm"
    UNKNOWN_DIALOG = "unknown_dialog"
    MERCHANT_ROOM = "merchant_room"
    SHOP = "shop"
    BUY_CONFIRM = "buy_confirm"
    BATTLE = "battle"
    PAUSE = "pause"
    GIVEUP = "giveup"
    QUICK_MENU = "quick_menu"
    LOBBY = "lobby"
    FINISHED = "finished"


STATE_LABELS = {
    LabyrinthStoneState.BATTLE_MENU: "战斗菜单·一般页",
    LabyrinthStoneState.LABYRINTH_LIST: "迷宫列表",
    LabyrinthStoneState.LABYRINTH_DETAIL: "迷宫详情页",
    LabyrinthStoneState.TEAM: "准备战斗页",
    LabyrinthStoneState.STORY: "开场剧情",
    LabyrinthStoneState.ROOM: "迷宫房间",
    LabyrinthStoneState.MAP: "地图页",
    LabyrinthStoneState.TELEPORT_CONFIRM: "传送确认弹窗",
    LabyrinthStoneState.UNKNOWN_DIALOG: "认不出标题的双按钮弹窗",
    LabyrinthStoneState.MERCHANT_ROOM: "商人房",
    LabyrinthStoneState.SHOP: "商店页",
    LabyrinthStoneState.BUY_CONFIRM: "购买确认弹窗",
    LabyrinthStoneState.BATTLE: "迷宫内战斗（本路线不该出现）",
    LabyrinthStoneState.PAUSE: "暂停菜单",
    LabyrinthStoneState.GIVEUP: "放弃战斗确认框",
    LabyrinthStoneState.QUICK_MENU: "右上角快捷菜单",
    LabyrinthStoneState.LOBBY: "大厅",
    LabyrinthStoneState.FINISHED: "本轮已结束",
}

# evidence 页面键 -> 状态。顺序即判定意图（弹窗在前）。
_PAGE_STATES = (
    ("labyrinth_stone.buy_confirm", LabyrinthStoneState.BUY_CONFIRM),
    ("labyrinth_stone.teleport_confirm", LabyrinthStoneState.TELEPORT_CONFIRM),
    # 认不出标题的双按钮弹窗：必须排在传送弹窗**后面**（传送框也有这两个按钮）。
    ("labyrinth_stone.unknown_dialog", LabyrinthStoneState.UNKNOWN_DIALOG),
    ("labyrinth_stone.giveup_confirm", LabyrinthStoneState.GIVEUP),
    ("labyrinth_stone.pause", LabyrinthStoneState.PAUSE),
    # 快捷菜单是盖在迷宫详情页上的浮层，底下那页的锚点照样可见 ⇒ 必须排在详情页前面。
    ("labyrinth_stone.quick_menu", LabyrinthStoneState.QUICK_MENU),
    # 商店也是盖在商人房上的浮层 ⇒ 排在商人房前面。
    ("labyrinth_stone.shop", LabyrinthStoneState.SHOP),
    ("labyrinth_stone.merchant_room", LabyrinthStoneState.MERCHANT_ROOM),
    # 战斗也必须排在房间前面：战斗画面左上角同样挂着士气笑脸，
    # 两页唯一的差别是底部那条回合条。顺序反了会把真战斗读成房间。
    ("labyrinth_stone.battle", LabyrinthStoneState.BATTLE),
    ("labyrinth_stone.map", LabyrinthStoneState.MAP),
    ("labyrinth_stone.room", LabyrinthStoneState.ROOM),
    ("labyrinth_stone.story", LabyrinthStoneState.STORY),
    ("labyrinth_stone.team", LabyrinthStoneState.TEAM),
    ("labyrinth_stone.labyrinth_detail", LabyrinthStoneState.LABYRINTH_DETAIL),
    ("labyrinth_stone.labyrinth_list", LabyrinthStoneState.LABYRINTH_LIST),
    ("labyrinth_stone.battle_menu", LabyrinthStoneState.BATTLE_MENU),
    ("labyrinth_stone.lobby", LabyrinthStoneState.LOBBY),
)

# 开局接力能落脚的页面：**除了大厅、终态、购买确认框，其余都接**。
#
# ⚠️ 本路线只把**一个**弹窗排除在外 —— 购买确认框。它一旦点下去就花钱，
# 而接力看到的是「停在某个购买框上」这一帧，**认不出这一行买的是什么**：
# 万一是你自己手动点的「强化拳套」，接上去就是替你按了确认。宁可回大厅重走一遍。
# （放弃战斗确认框不在此列：放弃本来就是这条路线自己要做的事，没有额外代价。）
#
# ⚠️ 传送确认框**接**，但接上去一律按取消（见 ``_at_teleport_confirm``）：
# 没有 ``teleport_armed`` 就不是本路线叫出来的传送，而传送要花 3 士气。
#
# ⚠️ ``entered`` 的拨法见 ``mark_entered``：进过迷宫之后再落到详情页，
# 下一步是「回大厅」而不是「再进一次迷宫」。
_RESUMABLE_STATES = tuple(
    state
    for state in LabyrinthStoneState
    if state
    not in (
        LabyrinthStoneState.LOBBY,
        LabyrinthStoneState.FINISHED,
        LabyrinthStoneState.BUY_CONFIRM,
    )
)

# 「已经进过迷宫了」的分界线：站在这几页上说明迷宫已经进去了。
_AFTER_ENTRY_STATES = frozenset(
    {
        LabyrinthStoneState.ROOM,
        LabyrinthStoneState.MAP,
        LabyrinthStoneState.TELEPORT_CONFIRM,
        LabyrinthStoneState.UNKNOWN_DIALOG,
        LabyrinthStoneState.MERCHANT_ROOM,
        LabyrinthStoneState.SHOP,
        LabyrinthStoneState.BUY_CONFIRM,
        LabyrinthStoneState.BATTLE,
        LabyrinthStoneState.PAUSE,
        LabyrinthStoneState.GIVEUP,
        LabyrinthStoneState.QUICK_MENU,
    }
)

# 区域 1 是否被选中：金色选中框中心 y 与「1 区域」标签中心 y 的落差上限。
# 实测选中时落差 69，而一行本身就有 141 高 ⇒ 选中别的区时落差必然 ≥210。
REGION_ROW_TOLERANCE = 90

# 「✓完成探险」相对「1 区域」标签的位置容差（2026-11-04 14:18 真机实测）：
# 标签中心 (1080,467)，状态文字中心 (1100,503) ⇒ dx=+20 / dy=+36。
# 第二行的状态文字在 y≈691（dy≈224），所以 dy 上限 70 能把「2 区域也完成了」
# 这种情况挡在外面 —— 这一维是判据**能证伪**的关键，光靠文字模板不够。
REGION1_COMPLETED_MAX_DX = 120
REGION1_COMPLETED_MAX_DY = 70

# ---- 有界重试的上限 -----------------------------------------------------------
#
# ⚠️ 一律 **不超过 3**：主循环对「同名动作连点」的账本上限是 4 次（``action_attempts > 4``
# 之后先有一次**原地**「换个办法」的机会，再不行就直接安全停止；2026-09-26 之前是
# 触发「回大厅重新导航」，等于这一趟迷宫从头再来）。把上限压在 3 下面是刻意的 ——
# 「搜不到就收工」比「整条路线重跑一遍」便宜得多（迷宫不消耗门票，代价只是时间）。

MAX_MAP_DRAGS = 3  # 地图最多拖几次还看不到目标 pin
MAX_PIN_CLICKS = 2  # 同一个出口 pin 最多点几次
MAX_WEST_WALKS = 3  # 落地之后最多往西走几间房
MAX_SHOP_SCROLLS = 3  # 商店最多下滑几次

# ---- 拖动 / 滑动的手势 ---------------------------------------------------------
#
# 实测（``runtime_logs/_lab_probe2_out.txt``）：一次 ``(376, +297)`` 的拖动把商人 pin
# 从视口外拖进来了。地图开图时视野停在**右下角** ⇒ 内容要往右下拖（= 视角往左上移）。
#
# ⚠️ 手势只能放在 Runner 的 ``_after_action_click`` 里：主循环的动作通道只有
# ``runtime.click``，而状态机每帧都会被 ``preview()`` 重放一遍（放这儿会连发几十次）。
# 于是动作自己带一个**没有副作用的落点**，真正的手势由 Runner 补发。
MAP_PAN_TAP = (300, 620)  # 空点：拖动起点，落在地图内容区里（实测内容区 x0~1150 / y56~1060）
MAP_PAN_START = (300, 620)
MAP_PAN_END = (676, 917)
MAP_PAN_DURATION_MS = 600

# 商店列表下滑：起点在「类别列」和「购买列」中间那条商品区里。
SHOP_SCROLL_START = (1400, 880)
SHOP_SCROLL_END = (1400, 580)
SHOP_SCROLL_DURATION_MS = 500


def state_label(state: LabyrinthStoneState) -> str:
    return STATE_LABELS.get(state, state.value)


def _inside_map_canvas(point: tuple[int, int]) -> bool:
    """目标点落在地图内容区里吗？外面一律不点（那儿可能是别的东西）。"""
    x, y = point
    left, top, width, height = MAP_CANVAS
    return left <= x <= left + width and top <= y <= top + height

@dataclass(frozen=True)
class LabyrinthStoneAction(RouteAction):
    """一个动作，**必须声明出处与出口验收**（新路线准入，见模块 docstring 对账表）。"""
    reason: str = ""


@dataclass(frozen=True)
class LabyrinthStoneTemplates:
    labyrinth_card: np.ndarray
    labyrinth_entry: np.ndarray
    # 2026-11-06：迷宫列表卡片「混乱的提雷尔城」的**第二种画法**。
    # PC 专属（图只在 `pc/`），模拟器载入为 None。
    labyrinth_entry_alt: np.ndarray | None
    select_team_button: np.ndarray
    region_row1_label: np.ndarray
    region_selected_box: np.ndarray
    # 「1 区域」下方那行绿色「✓完成探险」。**只是业务状态判据**，不进页面判据表。
    # PC 专属：图只放在 ``labyrinth_stone/pc/``，模拟器载入为 None。
    region1_completed: np.ndarray | None
    battle_start_button: np.ndarray
    skip_button: np.ndarray
    morale_smiley: np.ndarray
    map_button: np.ndarray
    battle_turn_bar: np.ndarray
    room_marker_w: np.ndarray
    map_close_button: np.ndarray
    map_pin_merchant: np.ndarray
    teleport_title: np.ndarray
    teleport_confirm_button: np.ndarray
    teleport_cancel_button: np.ndarray
    merchant_label: np.ndarray
    merchant_body: np.ndarray
    shop_title: np.ndarray
    stone_category: np.ndarray
    stone_in_name: np.ndarray
    # 除强化石外，目标商品一律认**图标**（2026-11-07 起三种）：
    # 友情点数（绿心）/ 圣约书签（蓝星）/ 神秘书签（橙花）。
    # ⚠️ 三张图全部与秘密商店**共用同一份**（`shop_refresh/`）：同一个商品、
    # 同一个图标，另存第二份迟早漂移；类别标签反而会随商店变，不能当判据。
    covenant_candidate: np.ndarray
    mystic_candidate: np.ndarray
    friendship_candidate: np.ndarray
    buy_button: np.ndarray
    shop_footer: np.ndarray
    buy_dialog_title: np.ndarray
    buy_dialog_confirm: np.ndarray
    buy_dialog_cancel: np.ndarray
    pause_title: np.ndarray
    giveup_button: np.ndarray
    giveup_dialog_finish: np.ndarray
    quick_menu_grid_top: np.ndarray
    quick_menu_tavern: np.ndarray
    lobby_episode_menu: np.ndarray
    tabs_bar: np.ndarray
    back_arrow: np.ndarray
    pause_icon: np.ndarray
    quick_menu_button: np.ndarray
    evidence: object = None
    # PC 专属新增判据只在这项为真时启用；模拟器走改动前的判定路径。
    pc: bool = False


def build_labyrinth_stone_templates(template_dir: Path) -> LabyrinthStoneTemplates:
    def load(name: str) -> np.ndarray:
        return load_template(str(template_dir / f"{name}.png"))

    def load_optional(name: str) -> np.ndarray | None:
        path = template_dir / f"{name}.png"
        return load_template(str(path)) if Path(path).is_file() else None

    def load_shared(name: str) -> np.ndarray:
        """秘密商店里同款商品的图标，跨目录借用（同 tower.py 借 story/auto_off.png）。"""
        return load_template(str(template_dir.parent / "shop_refresh" / f"{name}.png"))

    return LabyrinthStoneTemplates(
        labyrinth_card=load("labyrinth_card"),
        labyrinth_entry=load("labyrinth_entry"),
        # 备选画法：用 `load_optional` —— 模拟器没有这张图，必须拿到 None 而不是抛错。
        labyrinth_entry_alt=load_optional("labyrinth_entry_alt"),
        select_team_button=load("select_team_button"),
        region_row1_label=load("region_row1_label"),
        region_selected_box=load("region_selected_box"),
        region1_completed=load_optional("region1_completed"),
        battle_start_button=load("battle_start_button"),
        skip_button=load("skip_button"),
        morale_smiley=load("morale_smiley"),
        map_button=load("map_button"),
        battle_turn_bar=load("battle_turn_bar"),
        room_marker_w=load("room_marker_w"),
        map_close_button=load("map_close_button"),
        map_pin_merchant=load("map_pin_merchant"),
        teleport_title=load("teleport_title"),
        teleport_confirm_button=load("teleport_confirm_button"),
        teleport_cancel_button=load("teleport_cancel_button"),
        merchant_label=load("merchant_label"),
        merchant_body=load("merchant_body"),
        shop_title=load("shop_title"),
        stone_category=load("stone_category"),
        stone_in_name=load("stone_in_name"),
        covenant_candidate=load_shared("covenant_candidate"),
        mystic_candidate=load_shared("mystic_candidate"),
        friendship_candidate=load_shared("friendship_candidate"),
        buy_button=load("buy_button"),
        shop_footer=load("shop_footer"),
        buy_dialog_title=load("buy_dialog_title"),
        buy_dialog_confirm=load("buy_dialog_confirm"),
        buy_dialog_cancel=load("buy_dialog_cancel"),
        pause_title=load("pause_title"),
        giveup_button=load("giveup_button"),
        giveup_dialog_finish=load("giveup_dialog_finish"),
        quick_menu_grid_top=load("quick_menu_grid_top"),
        quick_menu_tavern=load("quick_menu_tavern"),
        lobby_episode_menu=load("lobby_episode_menu"),
        tabs_bar=load("tabs_bar"),
        back_arrow=load("back_arrow"),
        pause_icon=load("pause_icon"),
        quick_menu_button=load("quick_menu_button"),
        evidence=build_labyrinth_stone_evidence(template_dir),
        pc=is_pc(template_dir),
    )


class LabyrinthStoneStateMachine:
    """迷宫强化石一轮的纯视觉决策：**每一帧都从画面重新判页面**。

    跨帧进度只有四个，全都**画面上看不出来**，所以必须记在状态机上：

    - ``entered``：已经点过「战斗开始」了吗（迷宫详情页会来两次）；
    - ``teleported``：这一趟的传送用掉了没有（决定房间里是「开地图」还是「赶路」）；
    - ``shop_done``：商店逛完了没有（否则离开商店会又被商人房塞回去）；
    - ``map_done``：地图这一段认输了没有（找不到出口就别再开地图了）。

    其余的（拖了几次 / 点了几次 pin / 走了几间房 / 下滑了几次）只是**有界重试的账本**。
    """

    _REFERENCE_SIZE = REFERENCE_SIZE

    def __init__(
        self,
        templates: LabyrinthStoneTemplates | Path,
        *,
        initial_state: LabyrinthStoneState = LabyrinthStoneState.BATTLE_MENU,
    ) -> None:
        self.templates = (
            build_labyrinth_stone_templates(templates)
            if is_template_root(templates)
            else templates
        )
        self.state = initial_state
        self.completed_cycles = 0
        # 「已经点过战斗开始、人在迷宫里了」。见类 docstring。
        self.entered = False
        self.teleported = False
        self.shop_done = False
        self.map_done = False
        # 这一趟买到手的强化石数量（只用于收尾时汇报，不参与任何决策）。
        # ⚠️ 恢复重进迷宫时**不清零**：它是这一轮的成绩单，不是重试账本。
        self.bought = 0
        # 每一笔买的是商店里哪一行（类别标签的 y，用来在收尾时汇报「买了哪几行」）。
        self.purchase_rows: list[int] = []
        # 「刚才那个购买确认框是不是本路线点出来的」：不是就按取消，
        # 绝不在认不出买的是什么的情况下替人按「确定」（花的是真金白银）。
        self.buy_armed = False
        # 刚点的那一行（购买按钮中心 y），确认框确认后记进 ``purchase_rows``。
        self.pending_row: int | None = None
        # 有界重试账本（上限见模块常量）。
        self.map_drags = 0
        self.pin_clicks = 0
        self.walks = 0
        self.shop_scrolls = 0
        # 「刚才那一下是不是本路线叫出来的传送」：拖地图时万一空点戳到别的 pin，
        # 弹出来的传送框会因为没有这个标记而被**取消**掉。
        self.teleport_armed = False
        self.finish_reason = ""
        # 「中途做不下去了」的**真实原因**。非空 = 这一趟不算完成，回家后 Runner 报错。
        # ⚠️ 它与 ``finish_reason`` 是两回事：后者是「正常走完一遍」的结论。
        self.blocked_reason = ""
        # 「进详情页就看到 1 区域写着『✓完成探险』」= 今天这趟已经打过，不用再进。
        # 与 ``blocked_reason`` 不同：这是**正常收工**（每日任务记 ✓），不是故障。
        # 它只在详情页被拨一次，之后一路走快捷菜单回大厅，``_at_lobby`` 用它写
        # 一条不会谎报「买了几块石头」的收工理由。
        self.already_explored = False
        self._confirmed_page = ""
        # 迷宫列表点的是哪一颗候选（主图 / PC 备选），写进动作依据便于复盘。
        self._last_entry_candidate = ""

    # ---- 视觉判据 ----

    def _locate(self, screen: np.ndarray, name: str) -> Optional[Match]:
        atom = self.templates.evidence.atom(name)
        # 走 ``locate_with_fallback``（与导航层、视觉诊断**同一把尺子**）：原样先比，
        # 不过阈才按 ``SMOOTH_FALLBACK_ANCHORS`` / ``SCALE_FALLBACK_ANCHORS`` 补一次。
        return locate_with_fallback(
            name,
            screen,
            getattr(self.templates, name),
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
            mode=atom.match_mode,
        )

    def _best(self, screen: np.ndarray, name: str) -> Optional[Match]:
        """不打分的「最高分」：拿不到阈值也要看它到底几分（判淡入/过场用）。"""
        atom = self.templates.evidence.atom(name)
        return find_best_template(
            screen,
            getattr(self.templates, name),
            region=atom.region,
            reference_size=atom.reference_size,
        )

    def _locate_all(self, screen: np.ndarray, name: str) -> list[Match]:
        """一屏里有多个同款控件时用这个（商店每一行都有一个「购买」）。"""
        atom = self.templates.evidence.atom(name)
        return find_all_templates(
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
                f"迷宫强化石画面[{state_label(self.state)}]里找不到锚点 {name}；"
                "为避免点到不知名的位置，已安全停止"
            )
        return match

    def _required_any(self, screen: np.ndarray, names: tuple[str, ...]) -> Match:
        """页面判据走 ``any_of`` 认出来了，点击点就必须走**同一组候选**。

        2026-11-06 17:28 实跑：``observe_page`` 已判成「迷宫列表」
        （``labyrinth_entry_alt`` 1.0000），可 ``_at_labyrinth_list`` 还写死
        ``_required("labyrinth_entry")``（那一帧主图为 None）⇒ 报「找不到锚点」。
        判据与点击点用两把尺子，等于把已认出的页面又判成认不出。

        模拟器下 ``labyrinth_entry_alt`` 是 None，且证据画像根本不登记这个原子，
        所以这里先按模板字段跳过它，**整条候选链退化成原来的单图**，行为零改动。
        """
        best: Optional[Match] = None
        best_name = ""
        for name in names:
            if getattr(self.templates, name, None) is None:
                continue
            match = self._locate(screen, name)
            if match is not None and (best is None or match.score > best.score):
                best, best_name = match, name
        if best is None:
            raise UnrecognizedScreen(
                f"迷宫强化石画面[{state_label(self.state)}]里找不到锚点 "
                f"{'/'.join(names)}；为避免点到不知名的位置，已安全停止"
            )
        self._last_entry_candidate = best_name
        return best

    def observe_page(self, screen: np.ndarray) -> Optional[LabyrinthStoneState]:
        profile = self.templates.evidence
        flags = {key: self._locate(screen, key) is not None for key in profile.atoms}
        for page_key, state in _PAGE_STATES:
            if profile.page(page_key).evaluate(flags) is EvidenceState.SAFE:
                return state
        return None

    def _region1_selected(self, screen: np.ndarray) -> bool:
        """区域列表现在选中的是 1 区域吗？

        ⚠️ **量不出来就当「没选中」**，去点一下「1 区域」。点已经选中的那一行
        没有任何副作用，而反过来（量不出来就当选中）会默默进错区域 ——
        那是本项目最不能接受的一类错（静默做错事）。真的一直量不出来，
        主循环四次之后会停下并留诊断，不会无限点。
        """
        box = self._locate(screen, "region_selected_box")
        label = self._locate(screen, "region_row1_label")
        if box is None or label is None:
            return False
        return abs(box.center[1] - label.center[1]) <= REGION_ROW_TOLERANCE

    def _region1_completed(self, screen: np.ndarray) -> bool:
        """1 区域是不是已经「✓完成探险」（今天这一区打过了、这一行点不动了）。

        2026-11-04 14:18 真机：详情页上 1 区域写着绿字「✓完成探险」，金色选中框
        停在 2 区域，``select-region-1`` 连点 4 次 ``(1080,467)`` 画面纹丝不动，
        最后报「四次点击未转场」把整条每日任务记 ✗。**这一行不是没认出来，是它
        本来就不能点**，再去补「1 区域」模板或调阈值只会重复这一轮。

        判据两维缺一不可（第二维负责证伪）：
        1. 第一行状态文字区里命中 ``region1_completed``（只裁绿勾 +「完成探险」）；
        2. 它必须紧贴在 ``region_row1_label`` 下方 -- 真机 dx=+20 / dy=+36；
           第二行状态在 dy≈224，超出 ``REGION1_COMPLETED_MAX_DY`` 一律不认。

        全库 520 帧扫描：3 张真·完成探险帧 1.0000，非目标页最高 0.2995
        （阈值 0.80），「1 区域还可选」的模拟器详情页 0.2321。
        """
        # PC 上才观察到的新状态；模拟器不进这条分支，保持改动前的判定路径。
        if not self.templates.pc or self.templates.region1_completed is None:
            return False
        done = self._locate(screen, "region1_completed")
        label = self._locate(screen, "region_row1_label")
        if done is None or label is None:
            return False
        dx = done.center[0] - label.center[0]
        dy = done.center[1] - label.center[1]
        return (
            abs(dx) <= REGION1_COMPLETED_MAX_DX
            and 0 <= dy <= REGION1_COMPLETED_MAX_DY
        )

    # ---- 商店：哪一行还能买 -----------------------------------------------------

    def _buyable_row(self, screen: np.ndarray):
        """从上往下找第一个**三道锁都过**的行。

        返回 ``(匹配, 白字像素数)``，没有就 None。

        ⚠️ **两条认商品的路 + 一道共同的锁**：

        - **图标路**：这一行的商品图标是友情点数 / 圣约书签 / 神秘书签之一
          （三张图借用 ``shop_refresh/``，与秘密商店同一个商品、同一张图）。
        - **文字路**（只管强化石）：① 这一行的**类别标签**写着「强化石」
          （``stone_category``，位置见 ``BUY_TO_CATEGORY_DY``）；② 这一行的
          **商品名里有一个「石」字**（``stone_in_name``）。
        - **共同锁**：这一行的**按钮上有一片白字**（``button_white_pixels`` ≥
          ``BUY_BUTTON_WHITE_PIXELS``）。

        为什么这些非强化石商品走图标：它们的类别标签会随商店变（友情点数在迷宫写
        「召唤」、在秘密商店写「货币」），**图标不变**。两种书签实测真行 0.9815 / 0.966，
        迷宫现有帧最高只有 0.559 / 0.391（阈 0.80）⇒ 不会把拳套之类认成书签。

        为什么文字路要有两道：2026-09-25 第一次事故是类别那道单独失灵（偏移写反 ⇒
        每一行都拿下一行的类别来判断自己），于是「强化拳套」被当成强化石买了。另一道
        问的是完全不同的一件事（商品名里有没有「石」），两者不会一起错。

        为什么共同锁是「数白字」而不是「取最亮一颗」：
        - 2026-09-25 第二次事故：「相对亮度」在真机上把**已售罄**（0/1）判成「还能买」，
          于是对着售罄行连点 4 次、整条路线卡死。
        - 2026-10-19 第三次事故：「最亮一颗」被**一颗**游离白像素骗过 —— 底边被裁那行
          的按钮块里混进了邻行天头的白字碎片（239 > 200），结果又对着售罄行点了 4 次。
        现在的口径：窗口收进模板 footprint，且要求**一片**白字（亮行 800 多颗 /
        售罄行 0~3 颗）。详见 ``button_white_pixels``。

        认不出就**一律不点** —— 花的是真金白银，宁可少买一次。
        """
        categories = self._locate_all(screen, "stone_category")
        stones = self._locate_all(screen, "stone_in_name")
        # 图标路：三张图共用同一个搜索区、同一把尺子，命中任意一个就算目标商品。
        icons = [
            match
            for name in (
                "covenant_candidate",
                "mystic_candidate",
                "friendship_candidate",
            )
            for match in self._locate_all(screen, name)
        ]
        buttons = self._locate_all(screen, "buy_button")
        for button in sorted(buttons, key=lambda match: match.center[1]):
            icon_ok = any(
                abs(icon.center[1] - button.center[1])
                <= BUY_ROW_PAIR_TOLERANCE
                for icon in icons
            )
            category_ok = any(
                abs(category.center[1] - (button.center[1] + BUY_TO_CATEGORY_DY))
                <= BUY_ROW_PAIR_TOLERANCE
                for category in categories
            )
            name_ok = any(
                abs(stone.center[1] - (button.center[1] + STONE_NAME_TO_BUY_DY))
                <= STONE_NAME_TOLERANCE
                for stone in stones
            )
            if not (icon_ok or (category_ok and name_ok)):
                continue
            live = button_white_pixels(screen, button.center)
            if live < BUY_BUTTON_WHITE_PIXELS:
                continue  # 这一行已经卖完了（按钮旁写着 0/1，按钮上没有白字）
            return button, live
        return None

    # ---- 动作构造 ----

    def _confirm_page(self, page: str) -> None:
        """登记「视觉确认我现在站在哪一页」，供主循环对账转场契约。

        ⚠️ 只在 ``next_action`` 开头按 ``observe_page`` 的结果写，不在 ``_action`` 里写：
        「本帧没有动作」的分支（大厅收工）不会走到 ``_action``，靠它写会让页面
        标识停在上一个动作的来源页，主循环于是认为上一个转场没成功、再点一遍。
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
    ) -> LabyrinthStoneAction:
        return LabyrinthStoneAction(
            name=name,
            point=point,
            source_page=source_page,
            target_pages=target_pages,
            in_page_evidence=in_page_evidence,
            reason=reason,
        )

    def _open_pause(self, screen: np.ndarray, page: str) -> LabyrinthStoneAction:
        """迷宫里所有「这一段到此为止」的分支，最后都汇到这儿：开暂停菜单。

        ⚠️ **只有两个地方可以调它**（2026-09-25 真机翻车后立下的规矩）：

        1. **商店里确认买不到强化石了** —— 这是本路线唯一正当的收工理由，
           也是正常人理解的「这一趟做完了」。
        2. **中途卡死了要撤** —— 只能由 ``_give_up_because`` 发起，它会把
           **真实原因**记下来，回家之后 Runner 照样报错（退出码 1）。
           绝不能像翻车那次一样：刚进迷宫就放弃，日志却写「商店没有可买的强化石」。

        「走路还没走完 / 控件还在淡入」这种**还没到**的情况**不许走这里** ——
        那属于等待，见 ``_at_room`` 里抛的 ``UnrecognizedScreen``。
        """
        icon = self._required(screen, "pause_icon")
        return self._action(
            "open-pause",
            point=icon.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.PAUSE),),
            reason=f"打开暂停菜单准备放弃这一趟（右上角暂停图标@{icon.center}）",
        )

    def _give_up_because(self, screen: np.ndarray, page: str, why: str):
        """中途撤出：记下**真实**原因再去开暂停菜单。

        回家之后 Runner 会拿 ``blocked_reason`` 报错，所以这一趟不会算「完成」。
        """
        self.blocked_reason = why
        action = self._open_pause(screen, page)
        return self._action(
            action.name,
            point=action.point,
            source_page=action.source_page,
            target_pages=action.target_pages,
            reason=f"这一趟到此为止：{why}（先回家，随后报错，不算完成）",
        )

    # ---- 各页决策 ----

    def _at_battle_menu(self, screen: np.ndarray):
        card = self._required(screen, "labyrinth_card")
        return self._action(
            "open-labyrinth",
            point=card.center,
            source_page=state_label(LabyrinthStoneState.BATTLE_MENU),
            # ⚠️ PC 客户端上点「迷宫」卡片**直接进迷宫详情页**，中间那个「迷宫列表」
            # 只在某些情况下出现（模拟器上是列表 → 再点条目才进详情）。
            # 落点少写一项的后果与主线那几次一模一样：主循环判「没点成功」→ 丢掉动作
            # → 干等 45 秒 → 报「迷宫列表未识别」（2026-11-03 08:48 实测）。
            target_pages=(
                state_label(LabyrinthStoneState.LABYRINTH_LIST),
                state_label(LabyrinthStoneState.LABYRINTH_DETAIL),
            ),
            reason=f"战斗菜单「一般」页上的迷宫卡片（中心={card.center}）",
        )

    def _at_labyrinth_list(self, screen: np.ndarray):
        # 页面判据是 any_of(labyrinth_entry, labyrinth_entry_alt)，点击点必须同组：
        # 只认主图时，PC 那一帧「页面认得出、入口找不到」，白等 60 秒后报故障。
        entry = self._required_any(
            screen, ("labyrinth_entry", "labyrinth_entry_alt")
        )
        return self._action(
            "open-labyrinth-entry",
            point=entry.center,
            source_page=state_label(LabyrinthStoneState.LABYRINTH_LIST),
            target_pages=(state_label(LabyrinthStoneState.LABYRINTH_DETAIL),),
            reason=f"迷宫列表里的「混乱的提雷尔城」（候选={self._last_entry_candidate} "
            f"分数={entry.score:.4f} 中心={entry.center}）",
        )

    def _at_labyrinth_detail(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.LABYRINTH_DETAIL)
        if not self.entered:
            # 1 区域今天已经「完成探险」：这一行不可点，再点 4 次也不会把选中框
            # 挪过去（2026-11-04 14:18 真机四连点全无效）。**不许把它当故障**，
            # 也不许为了「完成」硬去打 2 区域（地图出口布局是按 1 区域量的）。
            # ⇒ 记一个正常收工标记，走跟「放弃战斗之后」同一条快捷菜单回大厅。
            if self._region1_completed(screen):
                self.already_explored = True
                menu = self._required(screen, "quick_menu_button")
                return self._action(
                    "open-quick-menu",
                    point=menu.center,
                    source_page=page,
                    target_pages=(state_label(LabyrinthStoneState.QUICK_MENU),),
                    reason="1 区域已显示「完成探险」，今天这趟不用再进迷宫；"
                    f"从右上角快捷菜单回大厅（中心={menu.center}）",
                )
            if not self._region1_selected(screen):
                label = self._required(screen, "region_row1_label")
                return self._action(
                    "select-region-1",
                    point=label.center,
                    source_page=page,
                    in_page_evidence=(
                        "「1 区域」那一行出现金色选中框（region_selected_box 与 "
                        "region_row1_label 的纵向落差 ≤90 像素；实测选中时落差 69）"
                    ),
                    reason=f"区域列表当前选中的不是 1 区域，先切过去（点「1 区域」@{label.center}）",
                )
            button = self._required(screen, "select_team_button")
            return self._action(
                "open-team",
                point=button.center,
                source_page=page,
                target_pages=(state_label(LabyrinthStoneState.TEAM),),
                reason=f"区域 1 已选中，点右下绿色「选择队伍」（中心={button.center}）",
            )
        # 已经进过迷宫 ⇒ 是放弃战斗后落回这一页，下一步是从快捷菜单回大厅。
        menu = self._required(screen, "quick_menu_button")
        return self._action(
            "open-quick-menu",
            point=menu.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.QUICK_MENU),),
            reason=f"迷宫这一趟已经走完，从详情页右上角蓝色菜单回大厅（中心={menu.center}）",
        )

    def _at_team(self, screen: np.ndarray):
        button = self._required(screen, "battle_start_button")
        # ⚠️ 进迷宫是一次性的：**点下去的这一帧就把 entered 记上**。
        # 放在这里而不是等看到房间，是因为详情页会来两次 —— 等看到房间再记，
        # 中途一旦被恢复打断就会把「放弃后落回详情页」读成「还没进场」。
        self.entered = True
        return self._action(
            "start-battle",
            point=button.center,
            source_page=state_label(LabyrinthStoneState.TEAM),
            target_pages=(
                state_label(LabyrinthStoneState.ROOM),
                state_label(LabyrinthStoneState.STORY),
                state_label(LabyrinthStoneState.BATTLE),
            ),
            reason=f"准备战斗页右下绿色「战斗开始」（中心={button.center}）",
        )

    def _at_story(self, screen: np.ndarray):
        skip = self._required(screen, "skip_button")
        return self._action(
            "skip-story",
            point=skip.center,
            source_page=state_label(LabyrinthStoneState.STORY),
            target_pages=(state_label(LabyrinthStoneState.ROOM),),
            reason=f"开场剧情右上角「跳过」（中心={skip.center}）",
        )

    def _at_battle(self, screen: np.ndarray):
        """迷宫里撞上了战斗：本路线不打仗（``_BATTLE_ENTRY_ACTION = None``）。

        ⚠️ 撤出的依据是**看见了的事实**（底部那条回合条 ⇒ 这是真战斗，站着打不起来、
        也走不动），不是「没看见某个东西」。所以这里可以撤 —— 但必须记原因，
        回家后 Runner 报错（退出码 1），绝不能写成「商店没有可买的强化石」。
        """
        page = state_label(LabyrinthStoneState.BATTLE)
        return self._give_up_because(screen, page, "迷宫里撞上了战斗，本路线不打战斗")

    def _at_room(self, screen: np.ndarray):
        page = state_label(self.state)
        # 商店逛完了（唯一正当的收工理由）⇒ 回家。
        if self.shop_done:
            return self._open_pause(screen, page)
        # 地图那段已经认输 ⇒ 带着真实原因回家（Runner 随后报错，不算完成）。
        if self.map_done:
            return self._give_up_because(
                screen, page, self.blocked_reason or "迷宫里走不下去了"
            )
        if self.teleported:
            # 已经传送过了 ⇒ 人在去商人房的路上：点左下 W 徽记往西赶路。
            marker = self._locate(screen, "room_marker_w")
            # ⚠️ W 徽记认不出来 = **还在走路 / 还在淡入**，不是「这一趟做不成」。
            # 翻车那次就是在这里直接放弃的 —— 现在改成**等**：抛未识别，让主循环
            # 等画面稳定再说。真的一直等不到，由页面超时兜住（响亮失败，不静默放弃）。
            if marker is None:
                raise UnrecognizedScreen(
                    f"迷宫房间[{page}]还在赶路（左下 W 徽记没出现）：等画面站稳，不放弃"
                )
            if self.walks >= MAX_WEST_WALKS:
                # 走满上限还是一间房一间房地有 W 徽记 ⇒ **真到不了**，记原因回家报错。
                return self._give_up_because(
                    screen,
                    page,
                    f"传送落地后往西走了 {MAX_WEST_WALKS} 间房还没走到流浪商人",
                )
            self.walks += 1
            return self._action(
                "walk-west",
                point=marker.center,
                source_page=page,
                in_page_evidence=(
                    "走进另一个房间：画面整体换掉（士气笑脸还在、背景与 W 徽记变了）"
                    " / 出现「流浪商人」标签"
                ),
                reason=(
                    f"传送落地房里点左下 W 徽记往西赶路"
                    f"（第 {self.walks}/{MAX_WEST_WALKS} 次，中心={marker.center}）"
                ),
            )
        # 还没传送 ⇒ 要开地图找出口。判据是**看见了才动手**，两条取或：
        #   ① 模板匹配过 0.30（走路/淡入帧实测 0.337，站定 1.000）
        #   ② 左上角那坨蓝色占比过 0.15（走路帧 0.20，站定 0.27~0.28）
        best = self._best(screen, "map_button")
        ratio, centroid = map_button_blue_blob(screen)
        if best is not None and best.score >= MAP_BUTTON_MIN_SCORE:
            point = best.center
            how = f"模板 {best.score:.2f}"
        elif ratio >= MAP_BUTTON_BLUE_RATIO and centroid is not None:
            point = centroid
            how = f"蓝色块占比 {ratio:.2f} 重心{centroid}"
        else:
            # ⚠️ 同样只是**还没到**（走路/过场/淡入），不是做不成 ⇒ 等，不放弃。
            raise UnrecognizedScreen(
                f"迷宫房间[{page}]还没站稳（地图按钮没出现：模板"
                f"{best.score if best else 0:.2f}、蓝色 {ratio:.2f}）：等画面，不放弃"
            )
        return self._action(
            "open-map",
            point=point,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.MAP),),
            reason=f"十字路口房间左上角开地图（{how} -> 点 {point}）",
        )

    def _at_map(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.MAP)
        pin = self._locate(screen, "map_pin_merchant")
        if pin is not None and self.pin_clicks < MAX_PIN_CLICKS:
            target = (
                pin.center[0] + MERCHANT_PIN_TO_TARGET[0],
                pin.center[1] + MERCHANT_PIN_TO_TARGET[1],
            )
            if _inside_map_canvas(target):
                self.pin_clicks += 1
                # 拨上「是我叫出来的」：万一这个框其实是别的 pin 弹的，下一帧会被取消。
                self.teleport_armed = True
                return self._action(
                    "use-exit-pin",
                    point=target,
                    source_page=page,
                    target_pages=(state_label(LabyrinthStoneState.TELEPORT_CONFIRM),),
                    reason=(
                        f"按布局算出来的出口 pin：蓝松鼠 pin@{pin.center} "
                        f"{MERCHANT_PIN_TO_TARGET} -> 点 {target}"
                    ),
                )
        if self.map_drags < MAX_MAP_DRAGS:
            self.map_drags += 1
            return self._action(
                "pan-map",
                point=MAP_PAN_TAP,
                source_page=page,
                in_page_evidence=(
                    "地图内容整体往右下移（实测一次位移 +376/+297）："
                    "流浪商人 pin 进入视口"
                ),
                reason=(
                    f"视口里还没有流浪商人 pin，把地图往左上拖"
                    f"（第 {self.map_drags}/{MAX_MAP_DRAGS} 次）"
                ),
            )
        # 拖到上限还找不到出口 ⇒ 这一趟真做不成了：关掉地图回去撤。
        # ⚠️ 走的是「记真实原因 + 回家后报错」那条路，**不是**「当作买完了正常收工」。
        self.map_done = True
        self.blocked_reason = f"地图拖了 {MAX_MAP_DRAGS} 次仍找不到通往流浪商人的出口"
        close = self._required(screen, "map_close_button")
        return self._action(
            "close-map",
            point=close.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.ROOM),),
            reason=f"{self.blocked_reason}，先关地图（关闭@{close.center}）",
        )

    def _at_teleport_confirm(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.TELEPORT_CONFIRM)
        if self.teleport_armed:
            self.teleport_armed = False
            self.teleported = True
            button = self._required(screen, "teleport_confirm_button")
            return self._action(
                "confirm-teleport",
                point=button.center,
                source_page=page,
                target_pages=(state_label(LabyrinthStoneState.ROOM),),
                reason=f"传送确认框「确定」（消耗 3 士气，中心={button.center}）",
            )
        # 没点过出口 pin 却冒出传送框 ⇒ 多半是拖地图那一下空点戳到了别的 pin。
        # 按取消退回地图，绝不替它确认（传送到不知道哪儿去是最贵的错）。
        self.teleport_armed = False
        cancel = self._required(screen, "teleport_cancel_button")
        return self._action(
            "cancel-teleport",
            point=cancel.center,
            source_page=page,
            target_pages=(
                state_label(LabyrinthStoneState.MAP),
                state_label(LabyrinthStoneState.ROOM),
            ),
            reason=f"这个传送框不是本路线叫出来的，按取消（中心={cancel.center}）",
        )

    def _at_unknown_dialog(self, screen: np.ndarray):
        """认不出标题的双按钮弹窗：底下是谁不知道，一律按取消。"""
        page = state_label(LabyrinthStoneState.UNKNOWN_DIALOG)
        cancel = self._required(screen, "teleport_cancel_button")
        return self._action(
            "cancel-unknown-dialog",
            point=cancel.center,
            source_page=page,
            target_pages=(
                state_label(LabyrinthStoneState.MAP),
                state_label(LabyrinthStoneState.ROOM),
                state_label(LabyrinthStoneState.MERCHANT_ROOM),
                state_label(LabyrinthStoneState.SHOP),
            ),
            reason=f"认不出标题的双按钮弹窗，一律按取消，不猜「确定」会干什么（中心={cancel.center}）",
        )

    def _at_merchant_room(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.MERCHANT_ROOM)
        if self.shop_done:
            return self._open_pause(screen, page)
        body = self._required(screen, "merchant_body")
        return self._action(
            "open-shop",
            point=body.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.SHOP),),
            reason=f"点蓝松鼠本体开商店（点它头顶的「流浪商人」标签没用，中心={body.center}）",
        )

    def _at_shop(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.SHOP)
        row = self._buyable_row(screen)
        if row is not None:
            button, live = row
            # 拨上「是我叫出来的」：下一帧的购买确认框才允许确认。
            self.buy_armed = True
            self.pending_row = button.center[1]
            return self._action(
                "buy-stone",
                point=button.center,
                source_page=page,
                target_pages=(state_label(LabyrinthStoneState.BUY_CONFIRM),),
                reason=(
                    "这一行是目标商品（强化石 / 友情点数 / 书签）、"
                    f"按钮上有 {live} 颗白字像素"
                    f"（≥ {BUY_BUTTON_WHITE_PIXELS}，说明还没卖完），点「购买」@{button.center}"
                ),
            )
        sold_out = self._sold_out_stone_rows(screen)
        if self.shop_scrolls < MAX_SHOP_SCROLLS:
            self.shop_scrolls += 1
            footer = self._required(screen, "shop_footer")
            return self._action(
                "scroll-shop",
                # ⚠️ 这个坐标是**空点**：点在商店左下角那行说明文字上，
                # 真正的下滑由 Runner 的 ``_after_action_click`` 补发。
                point=footer.center,
                source_page=page,
                in_page_evidence="列表整体上移：出现此前不在视口里的新「购买」行",
                reason=(
                    "视口里没有可买的目标商品了，下滑第 "
                    f"{self.shop_scrolls}/{MAX_SHOP_SCROLLS} 次"
                    + (
                        f"（认出来 {len(sold_out)} 行是强化石但已经卖完）"
                        if sold_out
                        else ""
                    )
                ),
            )
        self.shop_done = True
        arrow = self._required(screen, "back_arrow")
        return self._action(
            "leave-shop",
            point=arrow.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.MERCHANT_ROOM),),
            reason=(
                "全部翻完了，没有可买的目标商品"
                + (f"（{len(sold_out)} 行强化石都已售罄）" if sold_out else "")
                + f"，点左上角返回箭头收工（中心={arrow.center}）"
            ),
        )

    def _sold_out_stone_rows(self, screen: np.ndarray) -> list[tuple[int, int]]:
        """列出**类别与名字都判定是强化石、但按钮已经卖完**的行（返回按钮中心）。

        只用来写日志与「什么时候可以走了」的判断：能让用户一眼看出
        「这几行我认出来了、只是卖完了」，而不是「我没认出来」。
        """
        categories = self._locate_all(screen, "stone_category")
        stones = self._locate_all(screen, "stone_in_name")
        buttons = self._locate_all(screen, "buy_button")
        sold: list[tuple[int, int]] = []
        for button in sorted(buttons, key=lambda match: match.center[1]):
            category_ok = any(
                abs(category.center[1] - (button.center[1] + BUY_TO_CATEGORY_DY))
                <= BUY_ROW_PAIR_TOLERANCE
                for category in categories
            )
            name_ok = any(
                abs(stone.center[1] - (button.center[1] + STONE_NAME_TO_BUY_DY))
                <= STONE_NAME_TOLERANCE
                for stone in stones
            )
            if not (category_ok and name_ok):
                continue
            if button_white_pixels(screen, button.center) < BUY_BUTTON_WHITE_PIXELS:
                sold.append(button.center)
        return sold

    def _at_buy_confirm(self, screen: np.ndarray):
        page = state_label(LabyrinthStoneState.BUY_CONFIRM)
        if not self.buy_armed:
            # 没点过「购买」却冒出确认框 ⇒ 不是本路线叫出来的（多半是你自己手动点的）。
            # 认不出这一行买的是什么，就**绝不替人按确定** —— 花的是真金白银。
            cancel = self._required(screen, "buy_dialog_cancel")
            return self._action(
                "cancel-buy",
                point=cancel.center,
                source_page=page,
                target_pages=(state_label(LabyrinthStoneState.SHOP),),
                reason=f"这个购买框不是本路线点出来的，按取消（中心={cancel.center}）",
            )
        self.buy_armed = False
        button = self._required(screen, "buy_dialog_confirm")
        self.bought += 1
        if self.pending_row is not None:
            self.purchase_rows.append(self.pending_row)
            self.pending_row = None
        return self._action(
            "confirm-buy",
            point=button.center,
            source_page=page,
            target_pages=(state_label(LabyrinthStoneState.SHOP),),
            reason=(
                f"购买二次确认框「确定」（第 {self.bought} 块，"
                f"商店第 {self.purchase_rows[-1] if self.purchase_rows else '?'} 行，"
                f"中心={button.center}）"
            ),
        )

    def _at_pause(self, screen: np.ndarray):
        button = self._required(screen, "giveup_button")
        return self._action(
            "give-up",
            point=button.center,
            source_page=state_label(LabyrinthStoneState.PAUSE),
            target_pages=(state_label(LabyrinthStoneState.GIVEUP),),
            reason=f"暂停菜单里的「放弃战斗」（中心={button.center}）",
        )

    def _at_giveup(self, screen: np.ndarray):
        finish = self._required(screen, "giveup_dialog_finish")
        return self._action(
            "confirm-give-up",
            point=finish.center,
            source_page=state_label(LabyrinthStoneState.GIVEUP),
            target_pages=(state_label(LabyrinthStoneState.LABYRINTH_DETAIL),),
            reason=f"放弃确认框里的「结束」（中心={finish.center}）",
        )

    def _at_quick_menu(self, screen: np.ndarray):
        tavern = self._required(screen, "quick_menu_tavern")
        return self._action(
            "go-tavern",
            point=tavern.center,
            source_page=state_label(LabyrinthStoneState.QUICK_MENU),
            target_pages=(state_label(LabyrinthStoneState.LOBBY),),
            reason=f"快捷菜单底部的酒馆图标回首页（中心={tavern.center}）",
        )

    def _at_lobby(self, screen: np.ndarray):
        if self.blocked_reason:
            # ⚠️ 这一趟**没做成**，只是平安回家了。Runner 会拿 ``blocked_reason``
            # 报错（退出码 1），绝不写「已完成一遍」。
            self._finish(f"已回到大厅，但这一趟没做成：{self.blocked_reason}")
            return None
        if self.already_explored:
            # 正常收工，但**不许**套用 ``_purchase_tally()`` 那句「一块没买」——
            # 那会让人误以为今天进过商店、只是石头卖光了。真实情况是压根没进场。
            self._finish("已回到大厅：1 区域已完成探险，今天这趟无需再进迷宫")
            return None
        tally = self._purchase_tally()
        self._finish(f"已回到大厅，本轮结束{tally}")
        return None

    def _purchase_tally(self) -> str:
        """收尾汇报用的**账单**：买了几件、分别是商店里哪几行。

        ⚠️ 现在只报「几件 + 哪几行」，**报不出金额也分不出品类**（读价格要另做
        数字字模，见 ``docs/maintenance/labyrinth_stone.md`` 的已知缺口）。
        """
        if not self.bought:
            return "（目标商品都买过了 / 商店里没有可买的强化石、友情点数或书签，一件没买）"
        rows = "、".join(f"第 {row} 行" for row in self.purchase_rows)
        return f"，买了 {self.bought} 件目标商品（强化石 / 友情点数 / 书签，{rows}）"

    def _finish(self, reason: str) -> None:
        self.state = LabyrinthStoneState.FINISHED
        self.completed_cycles += 1
        self.finish_reason = reason

    # ---- 开局接力（把「已经进过迷宫」这个跨帧进度拨对）----

    def mark_entered(self) -> None:
        """接力到「人已经在迷宫里」的那几页时调用：详情页的下一步才是回大厅。"""
        self.entered = True

    # ---- 主循环接口 ----

    def next_action(self, screen: np.ndarray) -> Optional[LabyrinthStoneAction]:
        page = self.observe_page(screen)
        if page is None:
            self._confirmed_page = ""
            raise UnrecognizedScreen(f"迷宫强化石画面[{state_label(self.state)}]未识别")
        self.state = page
        self._confirm_page(state_label(page))
        if page is LabyrinthStoneState.LOBBY:
            return self._at_lobby(screen)
        handler = {
            LabyrinthStoneState.BATTLE_MENU: self._at_battle_menu,
            LabyrinthStoneState.LABYRINTH_LIST: self._at_labyrinth_list,
            LabyrinthStoneState.LABYRINTH_DETAIL: self._at_labyrinth_detail,
            LabyrinthStoneState.TEAM: self._at_team,
            LabyrinthStoneState.STORY: self._at_story,
            LabyrinthStoneState.ROOM: self._at_room,
            LabyrinthStoneState.BATTLE: self._at_battle,
            LabyrinthStoneState.MAP: self._at_map,
            LabyrinthStoneState.TELEPORT_CONFIRM: self._at_teleport_confirm,
            LabyrinthStoneState.UNKNOWN_DIALOG: self._at_unknown_dialog,
            LabyrinthStoneState.MERCHANT_ROOM: self._at_merchant_room,
            LabyrinthStoneState.SHOP: self._at_shop,
            LabyrinthStoneState.BUY_CONFIRM: self._at_buy_confirm,
            LabyrinthStoneState.PAUSE: self._at_pause,
            LabyrinthStoneState.GIVEUP: self._at_giveup,
            LabyrinthStoneState.QUICK_MENU: self._at_quick_menu,
        }[page]
        return handler(screen)

    def preview(self, screen: np.ndarray):
        """稳定确认用的「试算」入口：算完把业务进度**原样还回去**。

        ``next_action`` 会推进 ``entered`` / 计数账本 / ``completed_cycles``，主循环每帧
        都先调 preview 做两帧稳定确认，不还原就会把「一次点击」记成两次。
        """
        snapshot = (
            self.state,
            self.completed_cycles,
            self.entered,
            self.teleported,
            self.shop_done,
            self.map_done,
            self.bought,
            self.map_drags,
            self.pin_clicks,
            self.walks,
            self.shop_scrolls,
            self.teleport_armed,
            self.finish_reason,
            self.blocked_reason,
            self.already_explored,
            self._confirmed_page,
            list(self.purchase_rows),
            self.pending_row,
            self.buy_armed,
        )
        try:
            action = self.next_action(screen)
            return action, (self.state, self.completed_cycles)
        finally:
            (
                self.state,
                self.completed_cycles,
                self.entered,
                self.teleported,
                self.shop_done,
                self.map_done,
                self.bought,
                self.map_drags,
                self.pin_clicks,
                self.walks,
                self.shop_scrolls,
                self.teleport_armed,
                self.finish_reason,
                self.blocked_reason,
                self.already_explored,
                self._confirmed_page,
                self.purchase_rows,
                self.pending_row,
                self.buy_armed,
            ) = snapshot


class LabyrinthStoneRunner(ModeRunnerBase):
    """迷宫强化石 Runner（主循环协议见 ``ModeRunnerBase``）。"""

    _MODE_LABEL = "迷宫强化石"
    # 新路线准入：动作缺声明直接拒发（含空跑）。
    _REQUIRE_TRANSITION_CONTRACT = True
    # 进迷宫有一段加载 + 开场剧情，180 秒的默认值不够 ⇒ 放宽到 300。
    _ABSOLUTE_TIMEOUT_SECONDS = 300
    _TIMEOUT_SECONDS = {
        LabyrinthStoneState.BATTLE_MENU: 60,
        LabyrinthStoneState.LABYRINTH_LIST: 60,
        LabyrinthStoneState.LABYRINTH_DETAIL: 60,
        LabyrinthStoneState.TEAM: 60,
        LabyrinthStoneState.STORY: 60,
        LabyrinthStoneState.ROOM: 60,
        LabyrinthStoneState.MAP: 60,
        LabyrinthStoneState.TELEPORT_CONFIRM: 45,
        LabyrinthStoneState.UNKNOWN_DIALOG: 45,
        LabyrinthStoneState.MERCHANT_ROOM: 60,
        # 商店要逐行买（每行一次二次确认），比别的页面给得宽。
        LabyrinthStoneState.SHOP: 120,
        LabyrinthStoneState.BUY_CONFIRM: 45,
        LabyrinthStoneState.BATTLE: 60,
        LabyrinthStoneState.PAUSE: 45,
        LabyrinthStoneState.GIVEUP: 45,
        LabyrinthStoneState.QUICK_MENU: 45,
        LabyrinthStoneState.LOBBY: 45,
        LabyrinthStoneState.FINISHED: 45,
    }
    # 这条路线不打架：只是「进了迷宫」，没有已承诺战斗可移交。
    _BATTLE_ENTRY_ACTION = None
    _SETTLED_BATTLE_STATE = None
    # 这几个动作点完原地就能看出动没动，等 45 秒纯属白等：切区域、拖地图、
    # 商店下滑、往西赶路 —— 再加上「点蓝松鼠本体开店」。
    #
    # ⚠️ 为什么 open-shop 也得进短重试：走到商人房有一小段**入场过场遮罩**，
    # 蓝松鼠本体在遮罩下仍能匹配到（于是稳定两帧、点击照常发出），但那一瞬间的
    # tap 被遮罩吃掉 ⇒ 画面仍是商人房 ⇒ 主循环因同名动作进入 45 秒重试门 ⇒
    # 体感就是「一直点不到、过好一会又能点到」。被遮罩吃掉属于「点了没生效」，
    # 应当 8 秒就重点，而不是干等 45 秒（遮罩一两秒就散，散了再点必中）。
    # 8 秒也远小于商人房 60 秒状态超时，不会误触发超时失败。
    _SHORT_RETRY_ACTIONS = frozenset(
        {"select-region-1", "pan-map", "scroll-shop", "walk-west", "open-shop"}
    )
    _SHORT_RETRY_SECONDS = 8.0

    def __init__(
        self,
        machine: LabyrinthStoneStateMachine,
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

    def _state_label(self, state: LabyrinthStoneState) -> str:
        return state_label(state)

    def _action_retry_seconds(self, action_name: str) -> float:
        if action_name in self._SHORT_RETRY_ACTIONS:
            return self._SHORT_RETRY_SECONDS
        return super()._action_retry_seconds(action_name)

    def _after_action_click(self, action: LabyrinthStoneAction) -> None:
        """``pan-map`` / ``scroll-shop`` 的点击是**空点**，真正的手势在这里补发。

        为什么不让状态机直接滑：主循环的动作通道只有 ``runtime.click``，
        状态机里做 I/O 又会被 ``preview()`` 每帧重放一遍（滑动会连发几十次）。
        所以走「动作带一个没有副作用的落点 + 这里补手势」。
        """
        if action.name == "pan-map":
            self.runtime.swipe(
                MAP_PAN_START,
                MAP_PAN_END,
                MAP_PAN_DURATION_MS,
                "labyrinth-map-pan",
            )
            return
        if action.name == "scroll-shop":
            self.runtime.swipe(
                SHOP_SCROLL_START,
                SHOP_SCROLL_END,
                SHOP_SCROLL_DURATION_MS,
                "labyrinth-shop-scroll",
            )

    def _check_cycle_completed(
        self, cycles_before: int, max_cycles: Optional[int]
    ) -> bool:
        """回大厅之后对账：**这一趟有没有真的做成**。

        ⚠️ 翻车那次的症状是「刚进迷宫就放弃，日志却写『已完成一遍』」。根因是
        「放弃」这个不可逆动作被**没看见某个锚点**触发了。现在放弃只有三种由头，
        每一种都会把**真实原因**写进 ``blocked_reason``（见 ``_open_pause`` 的规矩），
        这里只要发现它非空就直接报错 —— **回家不等于完成**。
        """
        finished = self.machine.completed_cycles > cycles_before
        done = super()._check_cycle_completed(cycles_before, max_cycles)
        blocked = getattr(self.machine, "blocked_reason", "")
        # ⚠️ 必须等**人真的到家了**才报错：记下原因的那一刻人还在迷宫里，
        # 那时候报错等于把人丢在迷宫里不管（``_close_out`` 也不会跑）。
        if blocked and finished:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 状态=这一趟没做成 原因={blocked} "
                f"已买={self.machine.bought} 处理=报错退出（不算完成）"
            )
            raise RuntimeError(
                f"迷宫强化石这一趟没做成：{blocked}"
                f"（人已回到大厅，买到 {self.machine.bought} 件目标商品）"
            )
        return done

    def route_note(self) -> str:
        """给每日任务结算用的一句话收获：复用收尾账单里现成的件数与行号。"""
        if self.runtime.dry_run:
            return ""
        if getattr(self.machine, "already_explored", False):
            return "1 区域今天已经探险过，无需再进迷宫"
        if not self.machine.bought:
            return "这趟没买到目标商品（都买过了 / 商店里没有可买的）"
        rows = "、".join(f"第 {row} 行" for row in self.machine.purchase_rows)
        return f"买到 {self.machine.bought} 件目标商品（强化石 / 友情点数 / 书签，{rows}）"

    def _log_cycle_completed(self) -> None:
        reason = getattr(self.machine, "finish_reason", "")
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一遍 "
            f"cycles={self.machine.completed_cycles} 结论={reason or '已走完出口'}"
        )


# ---- 开局接力 ----
# 契约与卡点见 docs/TRANSITION_CONTRACTS.md「接力契约」那一节。





def detect_resume_point(
    machine: "LabyrinthStoneStateMachine",
    screen: np.ndarray,
) -> Optional[ResumePoint]:
    """迷宫强化石开局接力：认出人停在哪一页就就地接管。

    **判据与运行期同源** —— 直接调状态机自己的 ``observe_page``，不另定阈值、不加新锚点。

    ⚠️ 停在**已经进过迷宫**的那几页（房间 / 地图 / 传送框 / 商人房 / 商店 /
    战斗 / 暂停 / 放弃确认 / 快捷菜单）时，必须调 ``mark_entered()``：否则回到迷宫详情页
    会被当成「还没进场」，又点一次「选择队伍」把人送进迷宫 —— 与接力「就地接着做」的本意相反。

    ⚠️ 停在大厅上返回 None：那一页是本路线的**终点**也是所有路线的起点，
    认不出才对（否则每次开跑都会跳过导航）。

    ⚠️ 停在**购买确认框**上也返回 None（理由见 ``_RESUMABLE_STATES``）：认不出这一行
    买的是什么，就不能替人按那个「确定」。代价只是回大厅重走一遍。
    """
    page = machine.observe_page(screen)
    if page is None or page not in _RESUMABLE_STATES:
        return None
    if page in _AFTER_ENTRY_STATES:
        machine.mark_entered()
    return ResumePoint(page=state_label(page))
