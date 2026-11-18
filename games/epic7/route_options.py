"""路线可选项：一处声明，界面、存档与执行共用。

2026-11-14 起，竞技场为首个试点。``key`` 同时是运行参数名；``default`` 一律等于
本功能上线前的行为，旧会话存档缺字段时按默认补齐，不改变任何既有路线的结果。

只声明「玩家在不同时期会给出不同答案」的选择。游戏自身写死的规则（友情点旗帜
每日一次、竞技场每日 30 次付费刷新上限、资源单价）只写进 ``note``，不做成选项。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# 名单类选项的长度上限。354 名英雄全勾是「不筛选」，没有意义；
# 封顶同时也防止存档被写成几千项。
ROSTER_MAX = 60


@dataclass(frozen=True)
class RouteOption:
    key: str
    label: str
    kind: str
    default: Any
    note: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int = 0
    maximum: int = 0
    depends_on: tuple[str, str] | None = None


_STAMINA_OPTIONS = (
    RouteOption(
        key="stamina_enabled",
        label="使用生命之叶",
        kind="choice",
        default="yes",
        note="体力不足时使用生命之叶补充。",
        choices=(("yes", "使用"), ("no", "不使用")),
    ),
    RouteOption(
        key="stamina_limit",
        label="生命之叶使用上限",
        kind="count",
        default=0,
        minimum=0,
        maximum=99,
        note="一次运行最多使用几片；0 表示不限。",
        depends_on=("stamina_enabled", "yes"),
    ),
)


ROUTE_OPTIONS: dict[str, tuple[RouteOption, ...]] = {
    "arena": (
        RouteOption(
            key="weekly_reward",
            label="周结算奖励",
            kind="choice",
            default="diamond",
            note="每周结算后进入竞技场时弹出「每周排名选择奖励」，二选一。默认选择钻石，可改为神秘书签。",
            choices=(
                ("diamond", "钻石"),
                ("mystic", "神秘书签"),
            ),
        ),
        RouteOption(
            key="opponent_preference",
            label="对手偏好",
            kind="choice",
            default="none",
            note="按积分高低在可挑战的对手里挑选。积分读不出时不启用。",
            choices=(
                ("none", "不指定"),
                ("highest", "优先积分最高"),
                ("lowest", "优先积分最低"),
            ),
        ),
        RouteOption(
            key="hero_blacklist",
            label="避战名单",
            kind="roster",
            default=(),
            note="对手队伍里出现这些英雄时跳过该场。勾入这份名单的英雄会自动从另一份移出。",
        ),
        RouteOption(
            key="hero_whitelist",
            label="优先名单",
            kind="roster",
            default=(),
            note="含这些英雄的对手优先开战；一个都没有出现时按常规挑选，不是只打这些。勾入这份名单的英雄会自动从另一份移出。",
        ),
        RouteOption(
            key="hero_list_conflict",
            label="两份名单命中数相同时",
            kind="choice",
            default="blacklist",
            note="同一支队伍里避战名单与优先名单的命中数相同时如何处置；命中数不等时以多的一方为准。",
            choices=(
                ("blacklist", "按避战名单处理（跳过）"),
                ("whitelist", "按优先名单处理（优先开战）"),
            ),
        ),
        RouteOption(
            key="refresh_mode",
            label="刷新对手方式",
            kind="choice",
            default="free",
            note="仅等待免费刷新，或允许使用金币刷新。刷新会中断连胜。",
            choices=(
                ("free", "仅等待免费刷新"),
                ("gold", "允许金币刷新"),
            ),
        ),
        RouteOption(
            key="max_gold_refreshes",
            label="金币刷新次数上限",
            kind="count",
            default=0,
            minimum=0,
            maximum=30,
            note="一次运行内使用金币刷新的次数。游戏每日另有 30 次上限。",
            depends_on=("refresh_mode", "gold"),
        ),
        RouteOption(
            key="ticket_mode",
            label="旗帜补充方式",
            kind="choice",
            default="friendship",
            note="仅使用友情点购买，或允许使用天空石购买。友情点每日仅可购买一次。",
            choices=(
                ("friendship", "仅友情点购买"),
                ("skystone", "允许天空石购买"),
            ),
        ),
        RouteOption(
            key="max_skystone_purchases",
            label="天空石购旗次数上限",
            kind="count",
            default=0,
            minimum=0,
            maximum=10,
            note="一次运行内使用天空石购买旗帜的次数。",
            depends_on=("ticket_mode", "skystone"),
        ),
    ),
    "story": _STAMINA_OPTIONS
    + (
        RouteOption(
            key="repeat_after_last",
            label="无后续关卡时重复同一关",
            kind="choice",
            default="yes",
            note="关卡没有下一关时执行「重新进行」，继续刷同一关。",
            choices=(("yes", "重复"), ("no", "不重复")),
        ),
    ),
    "story_star": _STAMINA_OPTIONS,
    "fodder": _STAMINA_OPTIONS,
    "world_boss": _STAMINA_OPTIONS,
    "side_story": _STAMINA_OPTIONS,
    "shop_refresh": (
        RouteOption(
            key="friendship_enabled",
            label="购买友情点数",
            kind="choice",
            default="yes",
            note="扫描到友情点数时购入。誓约书签与神秘书签固定购入。",
            choices=(("yes", "购买"), ("no", "不购买")),
        ),
        RouteOption(
            key="friendship_limit",
            label="友情点数购买上限",
            kind="count",
            default=10,
            minimum=0,
            maximum=99,
            note="一轮最多购买几个。",
            depends_on=("friendship_enabled", "yes"),
        ),
    ),
    "labyrinth_stone": (
        RouteOption(
            key="buy_friendship",
            label="购买友情点数",
            kind="choice",
            default="yes",
            note="商店里出现友情点数时购入。强化石与两类书签固定购入。",
            choices=(("yes", "购买"), ("no", "不购买")),
        ),
    ),
    "community": (
        RouteOption(
            key="redeem_energy",
            label="兑换行动力",
            kind="choice",
            default="yes",
            note="在兑换中心按每日上限兑换行动力。",
            choices=(("yes", "兑换"), ("no", "不兑换")),
        ),
        RouteOption(
            key="redeem_stone",
            label="兑换强化石",
            kind="choice",
            default="yes",
            note="兑换装备强化石与饰品强化石两类。",
            choices=(("yes", "兑换"), ("no", "不兑换")),
        ),
    ),
    "tower": _STAMINA_OPTIONS,
    "pet_adoption": (
        RouteOption(
            key="buy_food",
            label="购买一般饲料",
            kind="choice",
            default="no",
            note="宠物商店底部的一般饲料可购买时购入，每轮最多 1 件。一周可购买 3 次，由游戏内次数决定。",
            choices=(("yes", "购买"), ("no", "不购买")),
        ),
        RouteOption(
            key="buy_toys",
            label="购买宠物玩具",
            kind="choice",
            default="no",
            note="宠物商店底部的两种宠物玩具可购买时各购入 1 件，每轮每种最多 1 件。每种一周可购买 1 次。",
            choices=(("yes", "购买"), ("no", "不购买")),
        ),
    ),
    # 2026-11-17：装备制作。一次运行只做一个「讨伐 × 部位」组合。
    "craft_equipment": (
        RouteOption(
            key="hunt",
            label="讨伐",
            kind="choice",
            default="dragon",
            note="决定消耗哪一种讨伐材料，也决定可制作的套装范围。名称以游戏内钢铁工坊顶行为准。",
            choices=(
                ("dragon", "双足飞龙（龙讨伐）"),
                ("golem", "魔像（木讨伐）"),
                ("banshee", "报丧妖（水讨伐）"),
                ("azimanak", "阿吉玛纳克（暗讨伐）"),
                ("caides", "卡戴斯（光讨伐）"),
            ),
        ),
        RouteOption(
            key="slot",
            label="部位",
            kind="choice",
            default="weapon",
            note="一次运行只做一个部位。左侧为武器、头盔、铠甲，右侧为项链、戒指、鞋子。",
            choices=(
                ("weapon", "武器"),
                ("helmet", "头盔"),
                ("armor", "铠甲"),
                ("necklace", "项链"),
                ("ring", "戒指"),
                ("boots", "鞋子"),
            ),
        ),
        RouteOption(
            key="tidy",
            label="制作后整理",
            kind="choice",
            default="none",
            note="出售与萃取均不可撤销，勾选范围由游戏内「快速选择」的预设规则决定，本助手不判断装备价值。不整理时装备留在背包，轮数多会触发背包已满而提前结束。",
            choices=(
                ("none", "不整理"),
                ("sell", "出售"),
                ("extract", "萃取"),
            ),
        ),
    ),
}


def options_for(mode: str) -> tuple[RouteOption, ...]:
    return ROUTE_OPTIONS.get(mode, ())


def defaults_for(mode: str) -> dict[str, Any]:
    return {option.key: option.default for option in options_for(mode)}


def clean(mode: str, raw: object) -> dict[str, Any]:
    """按声明清洗：未知键丢弃，非法值退回默认，依赖未满足时数值归零。"""
    values = defaults_for(mode)
    if not isinstance(raw, Mapping):
        return values
    for option in options_for(mode):
        value = raw.get(option.key, option.default)
        if option.kind == "choice":
            if value not in {choice[0] for choice in option.choices}:
                continue
        elif option.kind == "roster":
            value = _clean_roster(value)
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            value = max(option.minimum, min(option.maximum, value))
        values[option.key] = value
    for option in options_for(mode):
        if option.depends_on and values.get(option.depends_on[0]) != option.depends_on[1]:
            values[option.key] = option.default
    return values


def _clean_roster(value: object) -> tuple[str, ...]:
    """名单清洗：只留非空字符串，去重保序，长度封顶。

    ⚠️ 这里**不校验英雄是否存在** —— 校验要读图鉴库（几百张图），放在清洗里会让
    每次读存档都扫一遍盘。缺图由 ``HeroMatcher`` 自己报（``missing_names``），
    并且如实写进日志：「点名了却认不出」比「悄悄少认一个」严重得多。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    seen: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        seen.append(name)
        if len(seen) >= ROSTER_MAX:
            break
    return tuple(seen)


def clean_all(raw: object) -> dict[str, dict[str, Any]]:
    """整份参数口袋：只保留已声明的路线，缺失的按默认补齐。"""
    source = raw if isinstance(raw, Mapping) else {}
    return {
        mode: clean(mode, source.get(mode, {}))
        for mode in ROUTE_OPTIONS
    }
