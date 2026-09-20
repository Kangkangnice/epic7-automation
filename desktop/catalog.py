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
)


def route_by_name(mode: str) -> RouteInfo:
    try:
        return next(route for route in ROUTES if route.mode == mode)
    except StopIteration as error:
        raise ValueError(f"未知路线：{mode}") from error
