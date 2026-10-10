import pytest

from auto_game_unified.desktop import catalog
from auto_game_unified.desktop.catalog import (
    DEV_BACKEND_ENV,
    PRODUCT_NAME,
    ROUTES,
    route_by_name,
    visible_backends,
)


def test_pc_backend_is_hidden_from_the_ui_by_default():
    """PC 客户端默认不在界面上露面。

    露出来的代价是：用户能一键选中一次**必然失败**的实跑 —— 截止 2026-09-30，十一条路线
    没有一条通过 PC 验收，其中四条还会直接报「未配置滑动动作」，而失败原因看起来像程序坏了。
    """
    assert visible_backends({}) == ("emulator",)


def test_the_dev_switch_reveals_the_pc_backend():
    """采模板 / 开发验证仍然要用它 —— 所以是「收起来」而不是「删掉」。"""
    assert visible_backends({DEV_BACKEND_ENV: "1"}) == ("emulator", "pc")


def test_only_the_exact_switch_value_reveals_it():
    """只有 "1" 算数：写成 "true" / "yes" 不该悄悄把未验收的后端露出来。"""
    for value in ("", "0", "true", "yes", "2", "on"):
        assert visible_backends({DEV_BACKEND_ENV: value}) == ("emulator",)


def test_catalog_lists_every_route_in_menu_order():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis",
        "story",
        "arena",
        "expedition",
        "tower",
        "fodder",
        "shop_refresh",
        "survivor",
        "world_boss",
        "knights_donation",
        "labyrinth_stone",
        "sanctuary",
        "community",
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert route_by_name("story").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 9


def test_community_is_experimental_and_warns_about_daily_limits():
    """社区签到：界面上必须写清两件事。

    ① 这条路线有一半在**竖屏**（用户得知道点下去画面会转过去）；
    ② 它点的东西**多数一天只能点一次**（签到 / 三条任务 / 三样兑换各有每日上限），
       所以**不能拿它当冒烟测试反复跑** —— 重复跑不报错、但什么也领不到，
       用户会以为程序坏了。界面上得先把这个预期讲明白。

    （2026-10-07 之前这条断言写的是「必须说明现在只能空跑」，
    那天真机数据采齐、实跑闸门放开，断言随之改成上面的两句。）
    """
    community = route_by_name("community")

    assert community.label == "社区签到"
    assert community.experimental
    assert community.cycles_editable is False
    assert "竖屏" in community.description
    assert "每日上限" in community.description


def test_survivor_is_experimental_and_explains_the_manual_entry_page():
    survivor = route_by_name("survivor")

    assert survivor.label == "活动"
    assert survivor.experimental
    assert survivor.status == "实验功能"
    # 起点是用户人工停好的页面，必须写在界面上让人看得见。
    assert "选第一张卡" in survivor.description
    assert "模拟器" in survivor.description


def test_shop_refresh_is_experimental_and_explains_cycle_semantics():
    shop = route_by_name("shop_refresh")

    assert shop.experimental
    # 用户 2026-09-29 拍板：默认 **0 次** —— 秘密商店自己会随时间自动刷新，
    # 每天进店扫一遍、把自动刷出来的买掉就行，0 次不花天空石。
    assert shop.default_cycles == 0
    assert shop.min_cycles == 0
    assert "付费刷新" in shop.description
    assert "初始页面" in shop.description
    # 「0 次」这条口子只开给刷书签，别的路线照样必须为正。
    for route in ROUTES:
        if route.mode != "shop_refresh":
            assert route.min_cycles == 1, f"{route.mode} 的次数下限不该被改动"


def test_hero_synthesis_is_fixed_to_one_cycle():
    hero = route_by_name("hero_synthesis")
    assert hero.default_cycles == 1
    assert hero.cycles_editable is False


def test_arena_is_a_formal_feature():
    arena = route_by_name("arena")
    assert arena.status == "正式功能"
    assert not arena.experimental


def test_expedition_is_a_formal_feature():
    expedition = route_by_name("expedition")
    assert expedition.status == "正式功能"
    assert not expedition.experimental


def test_world_boss_is_experimental_and_explains_the_resource_boundary():
    world_boss = route_by_name("world_boss")

    assert world_boss.label == "世界首领战"
    # 一次实机都没跑过，先按实验功能放进助手。
    assert world_boss.experimental
    # 「每次 20 体力」和「不会用钻石」是用户定的红线，必须写在界面上让人看得见。
    assert "20 体力" in world_boss.description
    assert "树叶" in world_boss.description


def test_world_boss_is_fixed_to_two_cycles():
    """每天就 2 次，用户明确要求「不要让我选择次数」。"""
    world_boss = route_by_name("world_boss")

    assert world_boss.default_cycles == 2
    assert world_boss.cycles_editable is False
    # 用户看得见的说明里要写清「每天 2 次」，否则置灰的输入框会被当成坏了。
    assert "2 次" in world_boss.description


def test_knights_donation_is_experimental_and_fixed_to_one_pass():
    """每天跑一遍就够，用户明确要求「不要让我选择次数」。"""
    donation = route_by_name("knights_donation")

    assert donation.label == "骑士团捐赠"
    # 一次实机都没跑过，先按实验功能放进助手。
    assert donation.experimental
    assert donation.default_cycles == 1
    assert donation.cycles_editable is False
    # 界面上要能看见「怎么进来的」和「怎么结束的」，否则用户不知道它会自己收工。
    assert "骑士团活动" in donation.description
    # ⚠️ 用户 2026-09-24 更正：有没有红点都要进 ⇒ 界面上不许再写「没红点就结束」。
    assert "红点" not in donation.description
    # 一天只能请求一次支援是用户定的红线，必须写在界面上。
    assert "每天请求一次" in donation.description


# --------------------------------------------------------------------------
# 「每日任务」面板的三分组 + 批量勾选（用户 2026-10-08 拍板）
# --------------------------------------------------------------------------


def test_groups_are_defined_in_display_order():
    """三个分组名与它们的展示顺序。

    ⚠️ 这里**写死**中文名与顺序，不从实现里读 —— 否则改实现时断言跟着改，
    等于没护栏。分组的顺序就是面板上从上到下的顺序。
    """
    assert catalog.GROUP_DAILY == "日常"
    assert catalog.GROUP_SEASON == "赛季"
    assert catalog.GROUP_EVENT == "活动"
    assert catalog.GROUPS == ("日常", "赛季", "活动")


def test_every_route_belongs_to_exactly_one_known_group():
    for route in ROUTES:
        assert route.group in catalog.GROUPS, f"{route.mode} 的分组 {route.group!r} 不认识"


def test_group_membership_is_what_the_user_asked_for():
    """分组归属：**写死一份真值表**，不遍历实现。

    依据用户 2026-10-08 的原话：
      - 「这些都属于赛季，就它有时候会轮换」⇒ 远征 + 月塔；
      - 「狗粮算日常」；
      - 「活动单独一组」⇒ survivor。
    """
    expected = {
        catalog.GROUP_DAILY: [
            "hero_synthesis",
            "story",
            "arena",
            "fodder",
            "shop_refresh",
            "world_boss",
            "knights_donation",
            "labyrinth_stone",
            "sanctuary",
            "community",
        ],
        catalog.GROUP_SEASON: ["expedition", "tower"],
        catalog.GROUP_EVENT: ["survivor"],
    }
    for group, modes in expected.items():
        assert [route.mode for route in catalog.routes_in_group(group)] == modes


def test_grouped_routes_returns_display_order_and_skips_empty_groups():
    grouped = catalog.grouped_routes()

    assert [group for group, _ in grouped] == ["日常", "赛季", "活动"]
    # 三组摊平之后必须一条不漏、一条不重。
    #
    # ⚠️ 断言的是**集合**相等，不是「等于 `ROUTES` 的书写顺序」—— 两者本就
    # **故意不同**：分组渲染会把「赛季」那两条提到「日常」全组之后，
    # 而 `ROUTES` 里 `expedition` 写在 `fodder` 前面。要求顺序一致等于
    # 要求「分组不起作用」，是自相矛盾的。
    flattened = [route.mode for _group, routes in grouped for route in routes]
    assert sorted(flattened) == sorted(route.mode for route in ROUTES)
    assert len(flattened) == len(set(flattened)), "有路线被重复渲染了"
    # 组内顺序仍沿用 `ROUTES` 的书写顺序（组内不许被打乱）。
    for group, routes in grouped:
        write_order = [
            route.mode for route in ROUTES if route.group == group
        ]
        assert [route.mode for route in routes] == write_order


def test_routes_in_group_rejects_an_unknown_group():
    with pytest.raises(ValueError):
        catalog.routes_in_group("不存在的分组")


def test_select_all_covers_every_route():
    """「全选」条数对得上，且**顺序 = 面板顺序**（这是批量勾选后的执行顺序）。"""
    modes = catalog.selectable_modes()

    assert sorted(modes) == sorted(route.mode for route in ROUTES)
    assert modes == tuple(
        route.mode
        for _group, routes in catalog.grouped_routes()
        for route in routes
    )


def test_select_all_without_events_skips_exactly_the_event_group():
    """「全选（不含活动）」= 全量减去「活动」那一组。

    ⚠️ 这里**独立算**出「该少哪些」再比对，不是拿 `EXCLUDED_FROM_SELECT_ALL`
    去验证它自己（那是循环论证）。
    """
    everything = catalog.selectable_modes()
    without_events = catalog.selectable_modes(include_events=False)

    event_modes = {route.mode for route in catalog.routes_in_group(catalog.GROUP_EVENT)}
    assert event_modes == {"survivor"}
    assert set(everything) - set(without_events) == event_modes
    # 顺序也要保持面板顺序（批量勾选后「执行顺序 = 看到的顺序」）。
    assert list(without_events) == [
        mode for mode in everything if mode not in event_modes
    ]


def test_only_the_event_group_is_excluded_from_select_all():
    assert catalog.EXCLUDED_FROM_SELECT_ALL == frozenset({"活动"})
