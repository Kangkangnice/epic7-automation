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
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert route_by_name("story").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 3


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
