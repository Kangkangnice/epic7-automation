"""User-facing route metadata for the desktop application."""

import os
from dataclasses import dataclass
from typing import Mapping

from auto_game_unified.games.epic7.modes import MODE_SPECS


PRODUCT_NAME = "第七史诗自动助手"
PRODUCT_VERSION = "0.1.0"

# ── 「每日任务」面板里的四个分组（2026-10-18 用户拍板「按需」单独成组）──────
#
# 分组的依据是**「这条路线该按什么节奏跑」**：
#
# - `GROUP_DAILY`（每日）：**几乎每天都要跑**的常驻日常。天天在，且跑不跑不该犹豫。
# - `GROUP_ONDEMAND`（按需）：**内容常驻、但跑不跑看当下需不需要**。主线 / 狗粮 /
#   英雄合成 / 支线故事 / 月光剧场都属于这档 —— 它们不是限时内容，只是不用天天跑。
# - `GROUP_SEASON`（赛季）：**按赛季轮换**的路线。赛季一换，内容与阶段就变了。
# - `GROUP_EVENT`（活动）：**限时活动**路线，随活动开合出现 / 消失。
#
# ⚠️ 四个名字是**界面分组**，与「路线本身是什么」无关：
#   - 它们**不进** `ModeSpec`（模式名 / 次数 / 状态机才是路线的属性）；
#   - 「每日」这个分组名与模块 `daily_tasks` 不是一回事 —— 后者是「把几条串起来
#     一次跑完」的**编排**，它读的清单仍然按勾选先后走，与分组无关。
#   - ⚠️ 分组的**顺序**就是面板上从上到下的顺序，由 `GROUPS` 定死，
#     不从 `ROUTES` 的书写顺序派生（免得插一条新路线就把面板顺序搅乱）。
GROUP_DAILY = "每日"
GROUP_ONDEMAND = "按需"
GROUP_SEASON = "赛季"
GROUP_EVENT = "活动"

# 面板上从上到下的分组次序。**顺序即展示优先级**。
#
# 「每日」放第一（天天要用的最顺手），「按需」紧随其后（同属常驻内容、
# 只是节奏不同），然后才是按赛季 / 按活动轮换的两组。
#
# ⚠️ 「活动」放最后且**单独一组**是刻意的：`survivor` 的 `needs_navigation=False`
# （起点得由人先把游戏摆好），所以界面上它不能与非活动路线一起勾 —— 见
# `RouteInfo.standalone_only`。把它单独列一组，用户一眼就能看出
# 「这条不能和别的混着选」。
GROUPS: tuple[str, ...] = (GROUP_DAILY, GROUP_ONDEMAND, GROUP_SEASON, GROUP_EVENT)

# ── 界面上露不露面：窗口后端 ───────────────────────────────────────────────────
#
# ⚠️ PC 客户端**默认不在界面上露面**（2026-09-30 用户拍板「把它收起来」）。理由：
#   截止这天，**十一条路线没有一条通过 PC 验收**，而且其中四条（骑士团捐赠 / 迷宫强化石 /
#   刷书签 / 活动）在 PC 上会直接报「未配置滑动动作」—— 用户在界面上选中它，得到的是一次
#   **必然失败**的实跑，而失败原因看起来像程序坏了。
#   采模板 / 开发验证仍然要用 PC 后端，所以留一个开发开关（而不是删掉）。
#
# ⚠️ 收起来的只是**界面按钮**：命令行 `--window-backend pc` 与
#   `DesktopController.select_backend("pc")` 都不受影响（后者被测试用着）。
BASE_BACKENDS: tuple[str, ...] = ("emulator",)
DEV_BACKENDS: tuple[str, ...] = ("pc",)
DEV_BACKEND_ENV = "EPIC7_SHOW_PC_BACKEND"


def visible_backends(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """界面上应该出现哪些窗口后端。

    默认只有雷电模拟器；设 `EPIC7_SHOW_PC_BACKEND=1` 才把 PC 客户端一起露出来
    （采集模板 / 开发验证时用）。`environ` 只为测试注入，正常调用不传。
    """
    env = os.environ if environ is None else environ
    if env.get(DEV_BACKEND_ENV, "") == "1":
        return BASE_BACKENDS + DEV_BACKENDS
    return BASE_BACKENDS


@dataclass(frozen=True)
class RouteInfo:
    """桌面助手视角下的一条路线。

    ⚠️ 只有 ``description`` / ``group`` 是**桌面助手特有的**（界面文案，
    别的入口用不上）。中文名与次数都**从 ``modes.MODE_SPECS`` 读**，不在这里
    再写一份 —— 以前它们是字段，与 CLI / 菜单三处手工对齐，实测漂移过
    （``shop_refresh`` 这里叫「刷书签」、每日任务里叫「商店刷新」）。

    ⚠️ **路线之间不再分「正式 / 实验」**（2026-10-20 用户拍板：十五条路线他都
    实机验证过了，界面上那个 ``[正式]`` / ``[实验]`` 角标与启动前的「实验功能提醒」
    一起删掉）。以前这里有个 ``status`` 字段加 ``experimental`` 属性，删掉时**没有**
    留下一个恒为 ``"正式功能"`` 的哑字段 —— 留着它，下一个人就会以为这里还有一道分级。
    以后真要重新引入分级，请先想清楚「谁来看、看到之后做什么」，别只加一个字符串。
    """

    mode: str
    description: str
    # 「每日任务」面板里的分组（见 `docs/maintenance/daily_tasks_grouping.md`）。
    # ⚠️ 这个字段是**界面分组**，不是路线本身的属性 —— 所以留在 catalog，
    # 不进 `ModeSpec`（模式名 / 次数 / 状态机那些才是路线的属性）。
    group: str = GROUP_DAILY

    @property
    def label(self) -> str:
        return MODE_SPECS[self.mode].label

    @property
    def default_cycles(self) -> int:
        return MODE_SPECS[self.mode].default_cycles

    @property
    def cycles_editable(self) -> bool:
        return MODE_SPECS[self.mode].cycles_editable

    @property
    def min_cycles(self) -> int:
        """次数框允许的最小值（正常是 1；「刷书签」是 0 —— 只扫一遍、不付费刷新）。"""
        return MODE_SPECS[self.mode].min_cycles

    @property
    def standalone_only(self) -> bool:
        """只能单独跑：起点是用户人工摆好的页面，跑起来也不做任何「回家」动作。

        派生自 ``needs_navigation=False`` —— 目前只有「活动」是这样。界面据此
        把这条路线的勾选与其它路线**互斥**：它的前置条件是「人先把游戏停在选卡页」，
        串在别的路线后面时那个前置条件早就被上一段破坏掉了。
        """
        return not MODE_SPECS[self.mode].needs_navigation


# 每条 ``description`` 的写法（2026-10-20 用户：「写得太简略了，至少几行，
# 让人一看就知道这条路线是干什么的、有什么要注意的」）：
#
#   ┌ 第 1 段：它到底替你干什么（一句人话，不带术语）
#   ├ 第 2 段：跑一轮算到哪儿 / 默认次数（界面上的次数框就是这个）
#   └ 第 3 段：「注意：」开头 —— 消耗什么资源、什么绝不买、什么前提必须满足
#
# ⚠️ 三条硬规矩：
#   1. **不许写 Markdown**。这段文字直接进 tk 的 Label，写 ``**重点**`` 会原样
#      显示成星号（2026-10-19 与 20 日各踩过一次），强调只能靠分句和措辞。
#   2. **只写能验证的事实**。每条都对着 ``docs/maintenance/<路线>.md`` 与对应
#      ``games/epic7/<路线>.py`` 核过；「所有竞技场都支持」这类说法代码里没有分支
#      支撑，就不许写（详见 `docs/maintenance/arena.md` 的入口锚点一节）。
#   3. **换行是真换行**（``\n``）：说明区那个 Label 会按自己的宽度自动折行，
#      这里只负责分段，别手动塞空格去对位置。
ROUTES = (
    RouteInfo(
        "hero_synthesis",
        "把 3 星英雄从上到下过一遍：已经 SSS 的跳过；有红点的进刻印界面、"
        "把材料加满做合成；其余不动。\n"
        "跑一轮 = 扫完整个英雄列表，次数不可调。\n"
        "注意：合成和传送都不可撤销；这条不支持中途接着跑，停了只能从头再来。",
        group=GROUP_ONDEMAND,
    ),
    RouteInfo(
        "story",
        "自动打主线：进关 → 选队伍或辅助英雄 → 跳过剧情 → 自动战斗 → 收结算 → 下一关，"
        "顺手点掉好友申请、友情点这类弹窗。\n"
        "跑一轮 = 打完一关并回到下一关入口，默认 1 轮（可改）。\n"
        "注意：消耗体力，不够时用生命之叶补，叶子用完就停，不会拿钻石去买。",
        group=GROUP_ONDEMAND,
    ),
    RouteInfo(
        "arena",
        # 2026-10-20 用户指出「不只是新手竞技场」——旧文案写着「新手竞技场循环」，
        # 那只是**入口锚点**文件名叫 novice_arena 留下的印象。实际入口锚点有两张
        # 候选（新手期「新手竞技场」/ 脱离新手期「竞技场」），段位提升、段位升级
        # 奖励弹窗都能处理。但代码里**没有按竞技场种类分支**，所以这里不写
        # 「支持所有竞技场」那种话 —— 见 `docs/maintenance/arena.md`。
        "自动打竞技场：从对手列表挑能打的对手 → 挑战 → 战斗 → 结算 → 回列表；"
        "三个对手都打不了就免费刷新再挑。\n"
        "跑一轮 = 打完一场（输赢都算）回到对手列表，默认 10 场（可改，"
        "差不多是每天的免费场次）。\n"
        "注意：消耗挑战旗帜；旗帜用完只买左侧「100 友情点 → 5 旗帜」那一档"
        "（每天一次），右侧「30 钻石 → 5」永远不买。",
    ),
    RouteInfo(
        "expedition",
        "自动打远征的通缉传单：进远征 → 选一张传单 → 固定第 3 难度 → 战斗 →"
        "没击退就点公开招募。\n"
        "跑一轮 = 打完一张传单并回到远征主页，默认 1 轮（可改）；没传单了正常收工。\n"
        "注意：消耗通缉传单；难度固定第 3 档，暂时不能选。",
        group=GROUP_SEASON,
    ),
    RouteInfo(
        "tower",
        "自动爬欧多马顿塔（月塔）：入场 → 选队伍 → 战斗开始 → 打完的三选一装置"
        "固定点中间那张 → 决定装置 → 结算 → 下一层。\n"
        "跑一轮 = 打完一层并进到下一层的准备战斗页，默认 25 层（可改，差不多一座塔）。\n"
        "注意：每层 15 体力，体力不够时只识别、不购买也不补叶子，直接收工；只支持模拟器。",
        group=GROUP_SEASON,
    ),
    RouteInfo(
        "fodder",
        "在「特别的时间之书」Episode 3-7 反复刷同一关：打完点「重新进行」接着打，"
        "用来练级/刷狗粮。\n"
        "跑一轮 = 结算完并回到「重新进行」页，默认 1 轮（可改）。\n"
        "注意：消耗体力，不够时只用生命之叶补，叶子耗尽就停；关卡固定 3-7，不能换别的。",
        group=GROUP_ONDEMAND,
    ),
    RouteInfo(
        "side_story",
        "把本期支线故事的关卡从第一关连着打到最后一关：靠角色身上那枚发光徽记"
        "找到当前关，打完点场景页那个闪烁的蓝色三箭头进下一关。\n"
        "跑一轮 = 场景页上再也找不到蓝色箭头，说明这期打完了；次数不可调。\n"
        "注意：关卡位置每期都会变，所以不能指定关卡；只支持模拟器。",
        group=GROUP_ONDEMAND,
    ),
    RouteInfo(
        "shop_refresh",
        "进秘密商店从上到下扫一遍，只买誓约书签和神秘书签，别的一律不买。\n"
        "跑一轮 = 把初始页面扫一遍；填了付费刷新次数就再多扫 N 遍"
        "（默认 0 次 = 只扫不刷，不花钱，商店自己会随时间刷新）；一次付费刷新 3 天空石。\n"
        "注意：金币或天空石不足就停；只支持模拟器。",
    ),
    RouteInfo(
        "survivor",
        "活动小游戏挂机：选卡 → 局内走位 → 升级三选一 → 死亡结算 →"
        "点「重新进行」再来一局。\n"
        "跑一轮 = 从「选第一张卡」页出发、再回到这一页，默认 3 轮（可改）。\n"
        "注意：要你先手动把游戏停到「选第一张卡」页，而且这条只能单独勾、"
        "不能和别的路线一起跑；「确认」「重新抽取」永不点；只支持模拟器。",
        group=GROUP_EVENT,
    ),
    RouteInfo(
        "world_boss",
        "打骑士团的世界首领战：自动配队 → 战斗里点右上角跳过 → 结算 → "
        "领每周贡献度宝箱。\n"
        "跑一轮 = 打完一场并把能领的每周宝箱领掉；每天固定 2 次（每天上限），"
        "次数不可调，主页显示 0/2 时直接收工。\n"
        "注意：每场 20 体力，不够时只用树叶（1 片换 80 体力），树叶耗尽即停，"
        "绝不用钻石；要先加入骑士团。",
    ),
    RouteInfo(
        "knights_donation",
        "骑士团日常：资源支援页每天请求一次下级精灵之花，再逐行支援团员；"
        "然后切到每周任务页领点数档位和已完成的任务。\n"
        "跑一遍就结束，每天一次，次数不可调。\n"
        "注意：支援会消耗你持有的材料，持有不够的行自动跳过；不花任何货币；"
        "要先加入骑士团。",
    ),
    RouteInfo(
        "labyrinth_stone",
        "每天进一次迷宫「混乱的提雷尔城」1 区域：开地图传送到流浪商人，"
        "商店里只买强化石，然后退出商店、放弃战斗回大厅。\n"
        "跑一遍就结束，每天一次，次数不可调。\n"
        "注意：买强化石花金币，传送消耗 3 点士气；拳套、友情点这类商品一律不买。",
    ),
    RouteInfo(
        "sanctuary",
        "收「精灵之森」的三行材料：把显示「领取奖励」的行从上到下点掉，"
        "第三行右下那颗「照料」亮着也顺手点一下。\n"
        "跑一遍就结束，每天一次；三行都没东西可领就直接回大厅。\n"
        "注意：只做精灵之森，圣域里别的建筑完全不碰；这条只领取、不花费。",
    ),
    RouteInfo(
        "community",
        "进游戏内的「游戏社区」（模拟器会整块转成竖屏）：签到 → 做每日任务"
        "（浏览、分享）→ 在兑换中心按每日上限换行动力、装备强化石、饰品强化石 →"
        "退出回大厅。\n"
        "跑一遍就结束，每天一次。\n"
        "注意：签到、任务、兑换各有每日上限，一天里重复跑不会报错、但什么也领不到，"
        "别拿它当冒烟测试；只支持模拟器，也不要在社区竖屏里启动。",
    ),
    RouteInfo(
        "moonlight_theater",
        "把月光剧场本周的免费观览挨个看完：入口卡片左上角有绿色 F 才进 →"
        "逐个剧场看「当前剧场」有没有 Free 角标 → 入场 → 看剧情（不能跳过，"
        "靠点字幕推进）→ 领观览奖励 → 返回换下一个剧场。\n"
        "跑一轮 = 右边没海报可点了、当前剧场也没 Free，说明本周结束；次数不可调。\n"
        "注意：门票不足时会弹「50 万金币购买」，这里只会点取消，永不花金币；"
        "只支持模拟器。",
        group=GROUP_ONDEMAND,
    ),
)


def route_by_name(mode: str) -> RouteInfo:
    try:
        return next(route for route in ROUTES if route.mode == mode)
    except StopIteration as error:
        raise ValueError(f"未知路线：{mode}") from error


def routes_in_group(group: str) -> tuple[RouteInfo, ...]:
    """按分组取路线，顺序沿用 `ROUTES` 的书写顺序（= 界面上的顺序）。

    ⚠️ 分组名从 `GROUPS` 里取，**不许在调用处写中文字面量** —— 界面与
    「全选 / 全选（不含活动）/ 取消全选」三个按钮读的是同一份常量。
    """
    if group not in GROUPS:
        raise ValueError(f"未知分组：{group}")
    return tuple(route for route in ROUTES if route.group == group)


def grouped_routes() -> tuple[tuple[str, tuple[RouteInfo, ...]], ...]:
    """面板从上到下的分组内容：``((分组名, 该组路线), ...)``。

    ⚠️ **空组不返回**。目前三个分组都非空，但「活动」是随活动开合出现的 ——
    哪天 `survivor` 撤了，界面上不该留一个光秃秃的「活动」标题。
    这个过滤放在这里（而不是界面层写 `if routes:`），是为了让「面板渲染什么」
    只有一处来源；界面层拿到什么就画什么。
    """
    return tuple(
        (group, routes)
        for group in GROUPS
        if (routes := routes_in_group(group))
    )


# ── 「每日任务」：勾选多条、依次跑 ─────────────────────────────────────────
# 界面上的名字。它同时是那块面板的标题与唯一那个启动按钮的文案来源。
#
# ⚠️ 2026-10-18：面板**卡头整条去掉了**（用户划掉那两行文字要求删），所以
# `DAILY_LABEL` 现在只剩一个引用点 —— 「一条都没勾就点开始」时那个提示框的标题。
# 原来那句操作说明 `DAILY_DESCRIPTION` 也随之删除（它没有别的引用者）。
# 说明文字本身没丢：`docs/maintenance/daily_tasks_grouping.md` 与 USER_GUIDE 里都有。
DAILY_LABEL = "每日任务"
