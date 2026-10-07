"""User-facing route metadata for the desktop application."""

import os
from dataclasses import dataclass
from typing import Mapping

from auto_game_unified.games.epic7.modes import MODE_SPECS


PRODUCT_NAME = "第七史诗自动助手"
PRODUCT_VERSION = "0.1.0-dev"

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

    ⚠️ 只有 ``status`` / ``description`` 是**桌面助手特有的**（界面文案，
    别的入口用不上）。中文名与次数都**从 ``modes.MODE_SPECS`` 读**，不在这里
    再写一份 —— 以前它们是字段，与 CLI / 菜单三处手工对齐，实测漂移过
    （``shop_refresh`` 这里叫「刷书签」、每日任务里叫「商店刷新」）。
    """

    mode: str
    status: str
    description: str

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
    def experimental(self) -> bool:
        return self.status == "实验功能"

    @property
    def standalone_only(self) -> bool:
        """只能单独跑：起点是用户人工摆好的页面，跑起来也不做任何「回家」动作。

        派生自 ``needs_navigation=False`` —— 目前只有「活动」是这样。界面据此
        把这条路线的勾选与其它路线**互斥**：它的前置条件是「人先把游戏停在选卡页」，
        串在别的路线后面时那个前置条件早就被上一段破坏掉了。
        """
        return not MODE_SPECS[self.mode].needs_navigation


ROUTES = (
    RouteInfo(
        "hero_synthesis",
        "正式功能",
        "三星英雄刻印合成和 SSS 副本处理",
    ),
    RouteInfo("story", "正式功能", "主线和刷图循环"),
    RouteInfo("arena", "正式功能", "新手竞技场循环"),
    RouteInfo("expedition", "正式功能", "三阶段远征循环"),
    RouteInfo("fodder", "实验功能", "特别的时间之书 Episode 3-7"),
    RouteInfo(
        "shop_refresh",
        "实验功能",
        "默认 0 次 = 只进店从上到下扫一遍、把想要的买掉，一次都不付费刷新"
        "（秘密商店自己会随时间自动刷新）；填「付费刷新次数」才额外刷；"
        "初始页面也检查；只购买誓约和神秘书签",
    ),
    RouteInfo(
        "survivor",
        "实验功能",
        "活动小游戏（类幸存者）挂机；需先把游戏停在「选第一张卡」页；"
        "每轮自动选卡、走位、结算、重新进行；只支持模拟器",
    ),
    RouteInfo(
        "world_boss",
        "实验功能",
        "骑士团每日世界首领战；从大厅自动导航到骑士团再进首领战，"
        "每次消耗 20 体力（不够时自动用树叶购买，树叶耗尽即停）；"
        "每天固定 2 次，次数打完或红点消失自动结束",
    ),
    RouteInfo(
        "knights_donation",
        "实验功能",
        "骑士团每日捐赠，跑一遍就结束：从大厅自动导航到骑士团，点「骑士团活动」进去；"
        "资源支援页每天请求一次下级精灵之花、"
        "再依次支援团员；每周任务页领骑士团点数档位与已完成任务",
    ),
    RouteInfo(
        "labyrinth_stone",
        "实验功能",
        "迷宫每日强化石采购，跑一遍就结束：从大厅自动导航到战斗菜单 → 迷宫 →"
        "混乱的提雷尔城，确保选中 1 区域后进迷宫；开地图拖到最上方出口传送 →"
        "往西走到流浪商人 → 商店里只买「强化石」这一类（买过的行自动跳过）→"
        "退出商店 → 放弃战斗 → 回大厅",
    ),
    RouteInfo(
        "sanctuary",
        "实验功能",
        "圣域每日收菜，跑一遍就结束：从大厅左侧最上面那个「圣域」入口进去 →"
        "精灵之森，把三行材料（企鹅巢穴 / 精灵之泉 / 魔罗戈拉种植地）里显示"
        "「领取奖励」的行从上到下依次点掉、关掉「领取完成」弹窗 → 回大厅；"
        "没有可领的就直接结束",
    ),
    RouteInfo(
        "community",
        "实验功能",
        "游戏内「游戏社区」的每日任务与积分兑换，跑一遍就结束：从大厅进活动页 →"
        "更多精彩活动 → 网页活动列表，点「游戏社区」；之后模拟器整块变成竖屏，"
        "改用模拟器自己的截图与点击通道识别（签到、三条每日任务、装备强化石等"
        "按每日限购数量兑换）。⚠️ 签到 / 任务 / 兑换各有每日上限，一天内重复跑"
        "什么也领不到，别拿它当冒烟测试反复跑",
    ),
)


def route_by_name(mode: str) -> RouteInfo:
    try:
        return next(route for route in ROUTES if route.mode == mode)
    except StopIteration as error:
        raise ValueError(f"未知路线：{mode}") from error


# ── 「每日任务」：勾选多条、依次跑 ─────────────────────────────────────────
# 界面上的名字。它同时是那块面板的标题与唯一那个启动按钮的文案来源。
DAILY_LABEL = "每日任务"

# 下面这段是**左边那栏量高度的大头**（每行约 23px）⇒ 宁短勿全：
# 只说「怎么选、次数怎么算、错了怎么办」，内部怎么回首页不写在这儿。
DAILY_DESCRIPTION = (
    "勾选要跑的路线，勾选先后就是执行顺序（名字前面的序号会跟着变）；"
    "每条后面填跑几次，灰掉的有每日上限、不能改；"
    "刷书签花天空石、不可逆，次数请按需填；"
    "上一条跑完会自动回首页，再进下一条；"
    "某条失败会跳过它继续跑，最后给一份汇总"
)
