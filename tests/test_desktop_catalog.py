from auto_game_unified.desktop.catalog import PRODUCT_NAME, ROUTES, route_by_name


def test_catalog_lists_every_route_in_menu_order():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis",
        "story",
        "arena",
        "expedition",
        "fodder",
        "shop_refresh",
        "survivor",
        "world_boss",
        "knights_donation",
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert route_by_name("story").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 5


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
    assert shop.default_cycles == 1
    assert "付费刷新" in shop.description
    assert "初始页面" in shop.description


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
    assert "没有红点" in donation.description
    # 一天只能请求一次支援是用户定的红线，必须写在界面上。
    assert "每天请求一次" in donation.description
