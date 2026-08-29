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
    RouteInfo("assist_auto", "助手自动", "实验功能", "接管游戏内置重复战斗"),
)


def route_by_name(mode: str) -> RouteInfo:
    try:
        return next(route for route in ROUTES if route.mode == mode)
    except StopIteration as error:
        raise ValueError(f"未知路线：{mode}") from error
