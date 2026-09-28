"""迷宫强化石（``labyrinth_stone``）路线的视觉证据档案。

本模块只放资源、区域、阈值和页面判据；业务决策在 ``games/epic7/labyrinth_stone.py``。

## 这条路线要干什么（用户 2026-09-25 口述 + 当天真机勘探）

```
大厅 → 战斗（一般页）
  └ 「迷宫」卡片 → 迷宫列表 → 「混乱的提雷尔城」 → 迷宫详情页
      ├ 区域列表里确保选中的是**1 区域**（不是就切过去）
      └ 右下绿色「选择队伍」→ 准备战斗页 → 右下绿色「战斗开始」
入场 → 开场剧情（可跳过）→ 十字路口房间
  ├ 左上蓝色菱形开地图 → **拖动**把视野往左上移 → 找到「左下蓝松鼠 / 右下宝箱」的那个出口 pin
  └ 点它 → 弹「传送点 / 确定要消耗3士气」→ 确认（花 3 士气）→ 落到另一个房间
到达房间 → 点左下 **W** 徽记赶路 → 流浪商人（蓝松鼠）的房间
  └ 点**蓝松鼠本体**（点它头顶的「流浪商人」标签没用）→ 商店
      └ 只买类别标签写着「强化石」的行（每行一个绿色「购买」+ 二次确认弹窗）
收工 → 商店返回箭头 → 暂停菜单 → 放弃战斗 → 确认「结束」
  → 落回迷宫详情页 → 右上角蓝色菜单 → 底部**啤酒杯（酒馆）**图标 → 回到大厅
```

## ⚠️ 三条必须记住的实测事实

1. **`battle_scene_visible` 在迷宫房间里会误报成「战斗中」。**
   房间右下角也是「四格蓝色底座 + Skill」，和战斗界面同款 ⇒ `observe_battle_controls()`
   对纯房间帧也返回 `auto_controls`。所以本路线的页面识别**一律不用
   `battle_scene_visible`**，房间的排他锚点是左上角的**士气笑脸**（``morale_smiley``）。
   后果：本路线 ``_BATTLE_ENTRY_ACTION`` 必须是 ``None`` —— 我们只是「进了迷宫」，
   不存在「已承诺战斗」，不能交给战斗监督。

   ⚠️ **房间锚点为什么不是那颗蓝色菱形（``map_button``）**：它看着最像房间的标志，
   但菱形是**半透明**的，模板把背后的墙也拍进去了 ⇒ 换一个暖色调的房间就崩
   （``runtime_logs/_lab_anchor_probe.py``：深色房间 1.0000，暖色房间 0.3021 /
   0.4280 / 0.6482）。士气笑脸不透明，三个房间都是 0.86~1.00、战斗帧 0.0398。
   菱形只留作**点击目标**（开地图），不再参与判页。

2. **商店「买没买过」不能靠模板分数，只能靠亮度。**
   买完那行按钮变灰，但 ``TM_CCOEFF_NORMED`` 对亮度缩放不敏感 —— 灰帧上亮色
   「购买」模板照样得 **0.9531**（能点帧 1.0000）。

   ⚠️⚠️ **2026-09-25 第二次真机事故**：原判据是**相对亮度**（按钮底板 V 均值 ÷
   整幅画面 V 均值，阈值 1.20），真机上它把「已售罄」判成「还能买」，导致
   **对着一行已经写着「0/1」的售罄行连点 4 次、整条路线卡死**。
   根因是**口径本身不成立**：商店一打开背景被压暗，整幅画面平均亮度掉得比按钮快
   ⇒ 灰按钮也能算出 1.25。
   ⇒ 换成 ``button_live_v``：**亮按钮上有纯白 (255) 的「购买」字，灰按钮上没有**。

   实测四个状态（``runtime_logs/_lab_btn_diag.py``）：

   | 帧 | 行 | 按钮区域最亮像素 | 旧口径 平均÷帧均值 |
   |---|---|---|---|
   | ``shop.png`` | 4 行「1/1」全亮 | **255** | 2.76 ~ 2.78 |
   | ``shop_mostly_bought.png`` | 强化拳套「1/1」亮 | **255** | 2.93 |
   | ``shop_mostly_bought.png`` | 4 行「0/1」售罄 | **140 ~ 146** | 1.26 ~ 1.43 |
   | 真机诊断帧 | 5 行「0/1」售罄 | **145 ~ 146** | 1.32 ~ 1.43 |

   ⇒ 阈值 ``BUY_BUTTON_LIVE_V = 200``，两边空档 55~110，且不易受淡入影响
   （淡入不会凭空造出 255 的白字）。**绝对阈值在这里反而是安全的那个** ——
   与本节早先「绝对亮度会被淡入骗」的结论相反；那条结论只在**同一帧内比较各行
   相对高低**时成立（world_boss 那次是比高低，不是判有没有白字）。

3. **地图没有夹紧、坐标绝不能写死。**
   N/E/W/S 四个金色徽记是**固定 HUD**（拖动时纹丝不动），会动的是地图内容。
   实测能把整张图拖出屏幕外 ⇒ 路线只能「搜 → 拖 → 再搜」。正确出口 pin 的判别
   特征是**布局**：目标 pin（传送门形）的**左下有一个蓝松鼠 pin、右下有一个宝箱 pin**，
   实测偏移 = 松鼠 pin 中心 → 目标 pin 中心 ≈ **(+171, −159)**（``MERCHANT_PIN_TO_TARGET``）。
   只认 pin 形状没用 —— 传送门 pin 一屏有好几个，长得一模一样。

   地图**内容区**实测约 x 0~1150 / y 56~1060（``runtime_logs/_lab_probe3_out.txt``
   的差异网格：x≥1188 那一列几乎不动 = 右侧信息栏，y≤56 是顶部 HUD）。开图时视野停在
   右下角 ⇒ 目标 pin 一开始在视口外，必须把**内容往右下拖**（= 视角往左上移）才看得到。
   实测一次拖动让内容位移 (+376, +297)（``_lab_probe2_out.txt``）。

4. **W 徽记（``room_marker_w``）是半透明的，模板尺寸决定生死。**
   同一个徽记在四个房间里实测：142×142 模板只有 0.61~1.00（传送落地那间房只有 0.61），
   换成 **90×90** 之后升到 0.83~1.00（``_lab_probe6_out.txt``）—— 大模板把周围的
   地面一起拍进去，房间换个颜色就崩。它只在**左下角那一块**里搜（区域卡在
   x 60~320 / y 715~965），反例（别的页面）最高只有 0.285。

   ⚠️ 有一间中途房（``redo_W``）**根本没有 W 徽记**（0.31），所以「点不到 W」必须
   当成一条正常的收尾路径，不能当成识别失败。

5. **商店的「类别标签」在购买按钮上方 82 像素，靠这个配对。**
   一屏有多行，两列各自 ``find_all_templates``。实测（OCR 逐行读出商品名后核对，
   两张商店帧共 9 行全部吻合，差 81~83）：类别中心 y = 购买按钮中心 y **− 82**，
   行距 218 ⇒ 配对容差写 60 两边都留得下
   （``BUY_TO_CATEGORY_DY`` / ``BUY_ROW_PAIR_TOLERANCE``）。

   ⚠️ **原来是 +139（写反了符号）**，导致每一行都拿**下一行**的类别来判断自己是什么
   商品，真机上真的把「强化拳套」买了下来 —— 见 ``BUY_TO_CATEGORY_DY`` 的注释。
   **配不上对的行一律不点** —— 认不出是不是「强化石」就不买（现有样本里配不上对的
   正是要跳过的「强化拳套」那几行）。

## 阈值

统一 ``0.80``。**没有一处是按「凑一个好看的余量」调出来的**；``labyrinth_entry`` 单独
取 ``0.85``（它和迷宫详情页右上角那行标题是同一串字，那页已经被更具体的锚点先认走，
但抬高阈值能让「列表页 vs 详情页」这层更干净）。
"""

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .common import AtomEvidence, EvidenceProfile, PageEvidence


REFERENCE_SIZE = (1982, 1132)

DEFAULT_THRESHOLD = 0.80

# 搜索区域一律用**基准画布坐标**（1982x1132）。区域比模板大一圈即可：
# 区域写太松会把别的页面上的同形控件框进来（例：``region_selected_box`` 写满全屏时，
# 会在地图/暂停页上假命中 0.86 —— 见下）。
REGIONS = {
    # ---- 入场段：大厅 → 进迷宫 ----
    # 战斗页「一般」tab 上的四张卡片标题（精灵祭坛 / 讨伐 / 迷宫 / 异界之隙）。
    # 区域罩住整排，容忍卡片横向滚动。
    "labyrinth_card": (150, 290, 1780, 140),
    # 迷宫列表右栏的「混乱的提雷尔城」条目文字。
    "labyrinth_entry": (1400, 190, 582, 940),
    # 迷宫详情页右下角绿色「选择队伍」。这一页的排他锚点。
    "select_team_button": (1350, 960, 632, 172),
    # 区域列表里「1区域」那一行的标签。**只是点击目标**，不进 ``_PAGES``。
    "region_row1_label": (990, 555, 400, 190),
    # 区域列表里的金色圆角选中框（页内证据：判断选中的是不是区域 1）。
    # ⚠️ 区域必须**卡在区域列表这一栏**（x 990~1390 / y 555~1120）：
    # 写满全屏时它会在跳过剧情的帧上、暂停菜单帧上命中 0.8368~0.8618。
    "region_selected_box": (990, 555, 400, 565),
    # 准备战斗页右下角绿色「战斗开始」。这一页的排他锚点。
    "battle_start_button": (1350, 960, 632, 172),
    # 开场剧情右上角「跳过」。
    "skip_button": (1700, 55, 282, 95),
    # ---- 迷宫内 ----
    # 房间左上角那颗**士气笑脸**（不透明、跨房间稳定）。**房间的排他锚点**，
    # 理由见模块 docstring 第 1 条（蓝色菱形在这里站不住）。
    "morale_smiley": (150, 240, 150, 80),
    # 房间左上角蓝色菱形（开地图按钮）。**只是点击目标**，不进 ``_PAGES``：
    # 它半透明、模板连背景一起拍 ⇒ 暖色房间上只有 0.30~0.65（docstring 第 1 条）。
    "map_button": (0, 40, 260, 200),
    # 战斗界面底部的回合条。**只为把「真战斗」从房间里切出来**：房间帧 ≤0.0941、
    # 战斗帧 1.0000（``runtime_logs/_lab_anchor_probe.py``）。
    "battle_turn_bar": (600, 1000, 760, 132),
    # 左下 W 徽记（赶路用）。**模板是 90×90**（docstring 第 4 条）：142×142 会把地面
    # 拍进去，换一间房就掉到 0.61。区域卡死在左下角那一块，反例最高 0.285。
    "room_marker_w": (60, 715, 260, 250),
    # 地图页右下角「关闭」。地图页的排他锚点。
    "map_close_button": (1350, 980, 632, 152),
    # 地图上的「流浪商人」pin。搜索区罩住整个地图区（右侧信息栏留出来）。
    "map_pin_merchant": (0, 0, 1420, 1132),
    # 传送确认弹窗。**两个按钮成对出现**：确定 x=1124 / 取消 x=802，y 都是 796。
    # 取消按钮是「点错了 / 弹窗不是我们叫出来的」时的退路。
    "teleport_title": (700, 300, 600, 200),
    "teleport_confirm_button": (900, 700, 450, 190),
    "teleport_cancel_button": (640, 745, 324, 104),
    # ---- 商人房 + 商店 ----
    # 蓝松鼠头顶的「流浪商人」标签。**商人房的排他锚点**（房间也有 map_button，
    # 所以这一页必须排在 ``room`` 前面）。
    "merchant_label": (800, 280, 400, 270),
    # 蓝松鼠本体。点**身体**才开商店（点标签无效，2026-09-25 用户当场纠正）。
    "merchant_body": (800, 440, 380, 300),
    # 商店页左上角标题「商人」。这一页的排他锚点。
    "shop_title": (95, 55, 200, 95),
    # 左侧类别标签列（召唤 / 强化石 / 强化拳套 …）。一屏可能有多行 ⇒ 用 find_all_templates。
    # ⚠️ 下沿顶到画面底（y=1132）：原来写 950 会把最下面那行的标签切掉一半，
    # 于是那一行「配不上对」被当成强化拳套跳过了。
    "stone_category": (990, 150, 170, 982),
    # 商品名列里的那个「石」字（第二道锁）。区域的 x **只罩商品名那一列**，
    # 不碰左边的类别列；字号与类别标签不同 ⇒ 两者不会互相误命中（实测已验证）。
    "stone_in_name": (1030, 150, 260, 982),
    # 右侧「购买」按钮列。一屏可能有多行 ⇒ 用 find_all_templates。
    "buy_button": (1690, 150, 220, 950),
    # 商店页左下角「向商人购买的商品 每天会更新一次。」—— 翻页用的无副作用落点。
    "shop_footer": (40, 970, 360, 130),
    # 购买二次确认弹窗。
    "buy_dialog_title": (800, 220, 400, 150),
    "buy_dialog_confirm": (880, 740, 490, 140),
    # 弹窗左边的「取消」。**只做退路用**：不是本路线叫出来的购买框一律按它退出去。
    "buy_dialog_cancel": (600, 740, 400, 140),
    # ---- 退出链路 ----
    "pause_title": (850, 270, 240, 130),
    "giveup_button": (700, 400, 500, 140),
    "giveup_dialog_finish": (940, 660, 360, 140),
    # 快捷菜单：右上角那一片图标网格 + 底部那排（日志 / 房子 / 啤酒杯 / 齿轮）。
    "quick_menu_grid_top": (1500, 230, 300, 240),
    # ⚠️ 区域下沿必须过 995：酒馆图标 92x100、中心 y≈945 ⇒ 占到 y 895~995，
    # 写 (1600,850,170,140)（下沿 990）会把图标切掉 5 像素，分数从 1.0 掉到 0.61。
    "quick_menu_tavern": (1590, 860, 230, 200),
    # 大厅右侧的 Episode 菜单。``lobby`` 排最后，它是终态。
    "lobby_episode_menu": (1650, 280, 332, 230),
    # ---- 点击目标（**不进 ``_PAGES``**，它们会在多页上命中）----
    # 战斗页顶部的「一般 / 赛季 / 活动」页签条。
    "tabs_bar": (40, 165, 620, 130),
    # 左上返回箭头（商店、迷宫列表、迷宫里都有）。
    "back_arrow": (10, 40, 140, 120),
    # 迷宫里右上角那排图标最右一个：``‖``（暂停）。
    # ⚠️ 和 ``quick_menu_button`` 位置几乎重合、**图形不同** —— 房间/战斗里最右是 ``‖``，
    # 列表/详情页最右是蓝色四格网格。两页的图标集本来就不一样（已放大比对过）。
    "pause_icon": (1780, 40, 140, 110),
    # 迷宫详情页右上角蓝色四格网格（快捷菜单入口）。
    "quick_menu_button": (1790, 45, 130, 110),
}

THRESHOLDS = {key: DEFAULT_THRESHOLD for key in REGIONS}
# 「混乱的提雷尔城」这串字在迷宫详情页右上角也有（那页已被 select_team_button 先认走），
# 抬到 0.85 让两页这层更干净。
THRESHOLDS["labyrinth_entry"] = 0.85

_TEMPLATE_PATHS = {key: f"{key}.png" for key in REGIONS}

# 页面键 -> 判定顺序（**顺序即意图**）。下面几条是刻意的：
#   - 三个弹窗排最前：它们盖在底页上，而模板匹配对「压暗」不敏感；
#   - ``quick_menu`` 排在 ``lobby`` 前面：快捷菜单展开时大厅右侧那套 Episode 菜单
#     照样可见（实测 exit_bluemenu 帧），排后面会被当成「已回到大厅」提前收工；
#   - ``merchant_room`` 排在 ``room`` 前面：商人房里 ``map_button`` 也在；
#   - ``map`` 排在 ``room`` 前面：地图页左上角那颗蓝菱形**还看得见**（实测 step09_diamond）；
#   - ``team`` / ``labyrinth_detail`` 排在 ``labyrinth_list`` 前面：详情页右上角
#     也写着「混乱的提雷尔城」，和列表条目是同一串字。
_PAGES = (
    PageEvidence("labyrinth_stone.buy_confirm", required=("buy_dialog_title",)),
    PageEvidence("labyrinth_stone.teleport_confirm", required=("teleport_title",)),
    # 认不出标题的**双按钮弹窗**（实测帧 ``merchant_go``）：底下是谁不知道，
    # 但确定/取消两个按钮都在 ⇒ 一律按取消走，别去猜「确定」会干什么。
    # ⚠️ 必须排在 ``teleport_confirm`` 后面 —— 传送弹窗也有这两个按钮。
    PageEvidence(
        "labyrinth_stone.unknown_dialog",
        required=("teleport_confirm_button", "teleport_cancel_button"),
    ),
    PageEvidence("labyrinth_stone.giveup_confirm", required=("giveup_dialog_finish",)),
    PageEvidence("labyrinth_stone.pause", required=("pause_title",)),
    PageEvidence(
        "labyrinth_stone.shop",
        required=("shop_title",),
        any_of=(("buy_button", "stone_category"),),
    ),
    PageEvidence("labyrinth_stone.quick_menu", required=("quick_menu_grid_top",)),
    PageEvidence("labyrinth_stone.merchant_room", required=("merchant_label",)),
    # ⚠️ ``battle`` 必须排在 ``room`` 前面：战斗画面左上角同样挂着士气笑脸
    # （房间与战斗的差别只在底部那条回合条上）。顺序反了会把真战斗读成房间。
    PageEvidence("labyrinth_stone.battle", required=("battle_turn_bar",)),
    PageEvidence("labyrinth_stone.map", required=("map_close_button",)),
    PageEvidence("labyrinth_stone.room", required=("morale_smiley",)),
    PageEvidence("labyrinth_stone.story", required=("skip_button",)),
    PageEvidence("labyrinth_stone.team", required=("battle_start_button",)),
    PageEvidence("labyrinth_stone.labyrinth_detail", required=("select_team_button",)),
    PageEvidence("labyrinth_stone.labyrinth_list", required=("labyrinth_entry",)),
    PageEvidence("labyrinth_stone.battle_menu", required=("labyrinth_card",)),
    PageEvidence("labyrinth_stone.lobby", required=("lobby_episode_menu",)),
)

# ⚠️ 这里**故意不放**「页面键 -> 中文名」的对照表：日志用的页面名由
# ``games/epic7/labyrinth_stone.py::STATE_LABELS`` 独家所有，状态机的
# ``source_page`` / ``target_pages`` 全部从它派生（``state_label``）。
# 两处各留一张表迟早会漂移 —— 而主循环的转场对账只做**字符串相等**，
# 一旦漂移就是「转场永远验收不通过」而不是报错。


def build_labyrinth_stone_evidence(template_dir: Path) -> EvidenceProfile:
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


# ---- 「这一行还买得到吗」：相对亮度判据 -------------------------------------------
#
# 见模块 docstring 第 2 条。判据放在 evidence 模块是因为它和阈值一样属于「口径」，
# 业务代码只调用、不自己算。

# 购买按钮底板的半径（相对按钮模板中心）。实测口径：中心 ±(80, 32)。
BUY_PAD_HALF = (80, 32)

# ⚠️⚠️ 2026-09-25 第二次真机事故：**相对亮度在真机上会把「已售罄」判成「还能买」**。
#
# 原因不是阈值调得不好，而是**口径本身不成立**：`button_relative_v` 是「按钮底板区域
# 的平均亮度 ÷ 整幅画面的平均亮度」。这个比值成立的前提是「亮按钮的那块地方比
# 整个画面亮」。真机上商店一打开、背景被压暗 ⇒ 整幅画面平均亮度掉得比按钮更快，
# 于是**一块已经灰掉的按钮也能算出 1.25**（阈值 1.20 ⇒ 判定为「还亮着」）。
# 表现就是你看到的那样：**按钮旁已经写着「0/1」（售罄），代码还在点它，
# 点完没反应 ⇒ 重试 4 次 ⇒ 整条路线卡死**。
#
# 实测四个状态（`runtime_logs/_lab_btn_diag.py`，同一套口径）：
#
# | 帧 | 行 | 按钮区域**最亮像素** | 平均值 ÷ 帧均值 |
# |---|---|---|---|
# | shop.png | 4 行「1/1」全亮 | **255** | 2.76 ~ 2.78 |
# | shop_mostly_bought.png | 强化拳套「1/1」亮 | **255** | 2.93 |
# | shop_mostly_bought.png | 4 行「0/1」已售罄 | **140 ~ 146** | 1.26 ~ 1.43 |
# | 真机诊断帧(manual_stop) | 5 行「0/1」已售罄 | **145 ~ 146** | 1.32 ~ 1.43 |
#
# ⇒ 换用**绝对**判据：亮按钮上有**纯白 (255,255,255) 的「购买」文字**，灰按钮上没有。
# 「画面淡入」会把整幅一起调暗，但它**不会凭空造出 255 的白字** —— 所以这次
# 绝对阈值反而是安全的那个（相对亮度才是被淡入/背景压暗骗的那个，与 docstring
# 第 2 条的原始结论相反；那条结论只在**同一帧内比较各行的相对高低**时成立）。
#
# 取「最亮像素」不用平均值：平均值会被底板花纹、边框、相邻行蹭到；
# 最亮像素只问一件事 ——「这块地方有没有白字」。
BUY_BUTTON_LIVE_V = 200

# 旧口径保留：仅用于「同一帧内哪一行刚买过」的**相对**比较（阈值不参与购买决策）。
BUY_BUTTON_ALIVE_RATIO = 1.20


def button_live_v(
    screen: np.ndarray,
    center: tuple[int, int],
    half: tuple[int, int] = BUY_PAD_HALF,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> float:
    """量一块区域里的**最亮像素**：还能买的按钮有纯白「购买」字（255）≈ 255；
    已售罄的按钮整块发灰 ⇒ 实测 140~146。

    判据是「有没有白字」，与画面整体明暗无关 ⇒ **不会被淡入/背景压暗骗**。
    """
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    center_x, center_y = center
    half_w, half_h = half
    x0 = round((center_x - half_w) * scale_x)
    x1 = round((center_x + half_w) * scale_x)
    y0 = round((center_y - half_h) * scale_y)
    y1 = round((center_y + half_h) * scale_y)
    patch = screen[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)]
    if patch.size == 0:
        return 0.0
    # V = max(R,G,B)，与 HSV 的 V 逐像素相同（见 button_relative_v 的注释）。
    return float(patch.max(axis=2).max())


def button_relative_v(
    screen: np.ndarray,
    center: tuple[int, int],
    half: tuple[int, int] = BUY_PAD_HALF,
    *,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
) -> float:
    """量一块区域**相对整幅画面**的亮度（旧口径，**别拿它决定买不买**）。

    ⚠️ 真机上它会把「已售罄」判成「还能买」：商店打开时背景被压暗，整幅画面
    平均亮度掉得比按钮快 ⇒ 灰按钮也能算出 1.25。决定买不买请用 ``button_live_v``。
    """
    scale_x = screen.shape[1] / reference_size[0]
    scale_y = screen.shape[0] / reference_size[1]
    center_x, center_y = center
    half_w, half_h = half
    x0 = round((center_x - half_w) * scale_x)
    x1 = round((center_x + half_w) * scale_x)
    y0 = round((center_y - half_h) * scale_y)
    y1 = round((center_y + half_h) * scale_y)
    patch = screen[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)]
    if patch.size == 0:
        return 0.0
    frame_v = float(screen.max(axis=2).mean())
    if frame_v <= 0.0:
        return 0.0
    return float(patch.max(axis=2).mean()) / frame_v


# ---- 开地图：只认「左上角那坨蓝色的按钮」，不认图案 --------------------------------
#
# ⚠️ 2026-09-25 真机翻车换来的教训。原来只用模板匹配那颗半透明蓝菱形
# （阈值 0.80），而**走路 / 淡入期间它只有 0.34~0.49**，进迷宫 1.2 秒就走完了，
# 我却在第 0.3 秒那一帧上判「认不出」⇒ 直接放弃战斗。两个错：
#   1. 菱形半透明，模板连背景一起拍 ⇒ 走路/淡入/换房间都会掉分；
#   2. 「没看见某个东西」被当成了**放弃（不可逆）**的理由 —— 没长眼睛。
#
# 现在的口径：**看见了才动手**。菱形是迷宫里唯一的蓝色方块，位置固定在左上角，
# 所以问「这一块地方有没有一坨蓝色、它的重心在哪」，比问「像不像模板」稳得多：
#   走路第 1 帧 0.2008 / 站定 0.2684~0.2846 / 全黑过场 0.0000。
# 两条判据取**或**：任一条成立就点（余量比单条都厚）。

# 模板匹配的兜底线：房间类实测最低 0.337（走路第一帧）与 0.396（另一间房），
# 而会走到这条分支的帧里没有更低的 ⇒ 0.30 刚好兜住。
MAP_BUTTON_MIN_SCORE = 0.30

# 蓝色块的口径：只看色相和饱和度，**不看亮度** —— 淡入时 V 会整体压低，
# 带上亮度门槛又会被淡入骗一次（骑士团捐赠那条老教训）。
# 房间类最低 0.1422（那间房蓝色很淡，靠模板那条兜）、走路 0.20、站定 0.27~0.28。
MAP_BUTTON_BLUE_RATIO = 0.15

# OpenCV HSV 里 H 是 0~179，蓝≈120。区间取 95~135，与项目里其它蓝色判据一致。
MAP_BUTTON_BLUE_HUE = (95, 135)
MAP_BUTTON_BLUE_SAT = 60


def map_button_blue_blob(
    screen: np.ndarray,
    *,
    region: tuple[int, int, int, int] = REGIONS["map_button"],
) -> tuple[float, Optional[tuple[int, int]]]:
    """左上角那坨蓝色的**占比**与**重心**（全画布坐标）。

    返回 ``(占比, 重心)``；一个蓝色像素都没有时重心是 ``None``。
    重心可以直接当点击点用 —— 站定帧量出来 (98,130)，与菱形模板中心 (102,137)
    差不到 7 像素，而按钮本身有 156×142 那么大。
    """
    x, y, w, h = region
    scale_x = screen.shape[1] / REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / REFERENCE_SIZE[1]
    x0, y0 = round(x * scale_x), round(y * scale_y)
    x1, y1 = round((x + w) * scale_x), round((y + h) * scale_y)
    crop = screen[max(y0, 0) : y1, max(x0, 0) : x1]
    if crop.size == 0:
        return 0.0, None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    hue, sat = hsv[:, :, 0], hsv[:, :, 1]
    mask = (
        (hue >= MAP_BUTTON_BLUE_HUE[0])
        & (hue <= MAP_BUTTON_BLUE_HUE[1])
        & (sat >= MAP_BUTTON_BLUE_SAT)
    )
    ratio = float(mask.mean())
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return ratio, None
    return ratio, (int(xs.mean()) + x0, int(ys.mean()) + y0)


# ---- 地图 pin 的布局判据 ----------------------------------------------------------

# 蓝松鼠 pin 中心 -> 目标（出口传送门）pin 中心的实测偏移（基准画布像素）。
# 实测帧：``runtime_logs/_lab_capture_redo_pan1_after.png``
# 松鼠 pin 中心 (528, 289)、目标 pin 中心 (699, 130)。
MERCHANT_PIN_TO_TARGET = (171, -159)

# 地图内容区的实测范围（docstring 第 3 条）。算出来的目标 pin 落在外面就不点。
MAP_CANVAS = (0, 56, 1150, 1060)

# ---- 商店行的配对口径（docstring 第 5 条）----------------------------------------
#
# ⚠️⚠️ 2026-09-25 真机事故：这里原来是 **+139**，而实测关系是**类别在按钮上方 82**
# ⇒ 每一行都拿**下一行**的类别标签来判断自己是什么商品。因为强化石常常连着几行，
# 错位后大部分行仍然「看起来对」，只有边界那几行露馅 —— 结果「强化拳套」（18,000）
# 被当成强化石**真的买了**。
#
# 实测（OCR 逐行读出商品名后核对，两张商店帧共 9 行全部吻合，差 81~83）：
#   行1 类别「召唤」y=212 / 按钮 y=293   行2 类别「强化石」y=429 / 按钮 y=512
#   行3 类别「强化石」y=647 / 按钮 y=729   行4 类别「强化石」y=865 / 按钮 y=946
# ⇒ **类别中心 y = 购买按钮中心 y − 82**。
BUY_TO_CATEGORY_DY = -82

# 行距 218 ⇒ 容差 60 两边各留 130+ 像素空档（相邻行的类别在 ±218 处）。
BUY_ROW_PAIR_TOLERANCE = 60

# ---- 第二道锁：商品名里必须有一个「石」字 --------------------------------------
#
# ⚠️ 光靠「类别标签」这一条不够 —— 上面那次事故就是它单独失灵的结果。
# 商品名（下级装备强化石 / 传说神器强化石）里都有「石」，而强化拳套、友情点数没有。
# 于是再问一句「这一行的商品名里有没有『石』」，两条都成立才买。
#
# 实测区分度（阈值 0.80）：
#   强化石商品名 0.943~1.000 / 强化拳套 0.508 / 友情点数 0.459
# ⇒ 中间隔着 0.44，比类别标签那条（0.90 vs 0.74，只隔 0.16）厚得多。
#
# 商品名中心 y = 类别中心 y + 48 = 购买按钮中心 y − 34（两张帧实测 −34~−39）。
STONE_NAME_TO_BUY_DY = -34
# 行距 218 ⇒ 容差 30 两边各留 180+ 像素空档；同时刚好把类别行那个「石」
# （在 −82 处，距目标 48）排除在外。
STONE_NAME_TOLERANCE = 30
