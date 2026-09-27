"""User-facing route metadata for the desktop application."""

from dataclasses import dataclass


PRODUCT_NAME = "第七史诗自动助手"
PRODUCT_VERSION = "0.1.0-dev"


@dataclass(frozen=True)
class RouteInfo:
    mode: str
    label: str
    status: str
    description: str
    default_cycles: int = 1
    cycles_editable: bool = True

    @property
    def experimental(self) -> bool:
        return self.status == "实验功能"


ROUTES = (
    RouteInfo(
        "hero_synthesis",
        "英雄合成",
        "正式功能",
        "三星英雄刻印合成和 SSS 副本处理",
        cycles_editable=False,
    ),
    RouteInfo("story", "主线", "正式功能", "主线和刷图循环"),
    RouteInfo("arena", "竞技场", "正式功能", "新手竞技场循环"),
    RouteInfo("expedition", "远征", "正式功能", "三阶段远征循环"),
    RouteInfo("fodder", "狗粮", "实验功能", "特别的时间之书 Episode 3-7"),
    RouteInfo(
        "shop_refresh",
        "刷书签",
        "实验功能",
        "输入付费刷新次数；初始页面也检查；只购买誓约和神秘书签",
    ),
    RouteInfo(
        "survivor",
        "活动",
        "实验功能",
        "活动小游戏（类幸存者）挂机；需先把游戏停在「选第一张卡」页；"
        "每轮自动选卡、走位、结算、重新进行；只支持模拟器",
        default_cycles=3,
    ),
    RouteInfo(
        "world_boss",
        "世界首领战",
        "实验功能",
        "骑士团每日世界首领战；从大厅自动导航到骑士团再进首领战，"
        "每次消耗 20 体力（不够时自动用树叶购买，树叶耗尽即停）；"
        "每天固定 2 次，次数打完或红点消失自动结束",
        # 每日上限就是 2 次（主页「剩余/上限」），用户明确要求「不要让我选择次数」：
        # 默认 2 且不可编辑 —— 界面会把输入框置灰、开跑时直接采用 default_cycles。
        # 只有 1 次可用时不用特殊处理：打完第 1 场主页就变 0/2，循环自然结束。
        default_cycles=2,
        cycles_editable=False,
    ),
    RouteInfo(
        "knights_donation",
        "骑士团捐赠",
        "实验功能",
        "骑士团每日捐赠，跑一遍就结束：从大厅自动导航到骑士团，点「骑士团活动」进去；"
        "资源支援页每天请求一次下级精灵之花、"
        "再依次支援团员；每周任务页领骑士团点数档位与已完成任务",
        # 这条路线没有「次数」概念：请求支援一天只能发一次、红点领完就没了。
        # 与 launcher.py / main.py 的兜底保持一致（都被测试钉住）。
        default_cycles=1,
        cycles_editable=False,
    ),
    RouteInfo(
        "labyrinth_stone",
        "迷宫强化石",
        "实验功能",
        "迷宫每日强化石采购，跑一遍就结束：从大厅自动导航到战斗菜单 → 迷宫 →"
        "混乱的提雷尔城，确保选中 1 区域后进迷宫；开地图拖到最上方出口传送 →"
        "往西走到流浪商人 → 商店里只买「强化石」这一类（买过的行自动跳过）→"
        "退出商店 → 放弃战斗 → 回大厅",
        default_cycles=1,
        cycles_editable=False,
    ),
)


def route_by_name(mode: str) -> RouteInfo:
    try:
        return next(route for route in ROUTES if route.mode == mode)
    except StopIteration as error:
        raise ValueError(f"未知路线：{mode}") from error


# ── 「每日任务」：多选，不是单路线 ──────────────────────────────────────────
# 刻意**不放进 ROUTES**：ROUTES 是「选一条路线」的单选面板数据源（形状是
# 「一条路线 = 一个状态机 + 一个 Runner」），而每日任务是**编排**（把几条串起来）。
# 塞进去会让 ROUTES 的语义变浑、连测试钉住的顺序也失去意义。所以单独一组。
DAILY_GROUP_ID = "__daily__"
DAILY_LABEL = "每日任务"
# 这段字是**左边那栏目测高度的大头**（每行约 23px）⇒ 宁短勿全：
# 只留「跑哪些、跑几次、错了怎么办」，内部怎么回首页不写在这儿。
DAILY_DESCRIPTION = (
    "按固定次序把勾上的依次跑完"
    "（世界首领战 → 骑士团捐赠 → 商店刷新 → 迷宫强化石 → 竞技场）；"
    "每条后面填跑几次，灰掉的有每日上限、不能改；"
    "商店刷新花天空石、不可逆，次数请按需填；"
    "某条失败会跳过它继续跑，最后给一份汇总"
)


def daily_items() -> tuple[tuple[str, str], ...]:
    """每日任务的勾选项 ``(mode, label)``，次序与执行次序一致。

    直接从 ``games/epic7/daily_tasks.DAILY_TASKS`` 派生 —— 只有一处定义，
    界面不会跟执行器各说各话。
    """
    from auto_game_unified.games.epic7.daily_tasks import DAILY_TASKS

    return tuple((task.mode, task.label) for task in DAILY_TASKS)
