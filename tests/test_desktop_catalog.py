from auto_game_unified.desktop.catalog import PRODUCT_NAME, ROUTES, route_by_name


def test_catalog_has_four_formal_routes_and_three_experimental_routes():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis",
        "story",
        "arena",
        "expedition",
        "fodder",
        "assist_auto",
        "shop_refresh",
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert route_by_name("story").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 3


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
