from auto_game_unified.desktop.catalog import PRODUCT_NAME, ROUTES, route_by_name


def test_catalog_has_one_formal_route_and_five_experimental_routes():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis",
        "story",
        "arena",
        "expedition",
        "fodder",
        "assist_auto",
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 5


def test_hero_synthesis_is_fixed_to_one_cycle():
    hero = route_by_name("hero_synthesis")
    assert hero.default_cycles == 1
    assert hero.cycles_editable is False
