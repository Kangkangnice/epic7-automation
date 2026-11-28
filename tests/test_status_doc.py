"""面向使用者的路线总览及其生成保护。"""

from __future__ import annotations

import re
from unittest import mock

from auto_game_unified.desktop import catalog
from auto_game_unified.games.epic7 import modes
from auto_game_unified.tools import gen_status, route_compliance


def _rows(text: str) -> dict[str, list[str]]:
    table = text.split("## 二、哪些能力共用", 1)[0]
    rows = [line.strip("|").split("|") for line in table.splitlines() if line.startswith("| ")]
    parsed = [[cell.strip() for cell in row] for row in rows[2:]]
    return {row[0]: row[1:] for row in parsed}


def test_the_status_page_matches_the_generator() -> None:
    actual = gen_status.STATUS_PATH.read_text(encoding="utf-8")
    assert actual == gen_status.render(), (
        "从仓库父目录运行 python -m auto_game_unified.tools.gen_status 更新现状页"
    )


def test_one_row_per_route_has_a_resume_status_and_a_business_verdict() -> None:
    text = gen_status.render()
    rows = _rows(text)
    assert list(rows) == [route.display_label for route in catalog.ROUTES]
    assert len(rows) == len(set(route.display_label for route in catalog.ROUTES))
    assert f"（共 {len(rows)} 条）" in text
    assert set(gen_status.ACCEPTANCE) == set(modes.MODE_SPECS)
    for route in catalog.ROUTES:
        row = rows[route.display_label]
        assert len(row) == 7 and all(row), route.mode
        spec = modes.MODE_SPECS[route.mode]
        if not spec.needs_navigation:
            assert row[4] == "无，需停在指定页面"
        elif spec.resume_probe is None:
            assert row[4] == "无，从入口开始"
        else:
            assert row[4] == "支持部分页面"


def test_regional_availability_and_count_policy_match_the_desktop() -> None:
    rows = _rows(gen_status.render())
    assert rows["活动（已过期）"][2:4] == ["活动已过期", "活动已过期"]
    assert "仅国服模拟器" in rows["社区签到（国服）"][3]
    assert rows["社区签到（国服）"][1] == "固定 1 次"
    assert rows["世界首领战"][1] == "固定 2 次"
    assert rows["主线补星"][2] == "不可用（仅 PC）"
    for label in ("支线故事", "活动剧情", "月光剧场"):
        assert rows[label][1] == "自动跑完"
    assert rows["刷书签"][1] == "可调 · 默认 只扫不刷新"


def test_the_status_page_keeps_business_facts_and_shared_capabilities() -> None:
    text = gen_status.render()
    assert "主流程实机通过" in _rows(text)["竞技场"][5]
    assert "每日主流程实机通过" in _rows(text)["社区签到（国服）"][5]
    assert "积分余额" in _rows(text)["社区签到（国服）"][6]
    assert "还差什么" in text
    assert "远征与月塔" in text and "圣域收菜与企鹅购买" in text
    for removed in ("在制品", "每日任务的执行顺序", "仅 PC 的路线",
                    "素材与测试规模", "按路线的现行事实", "这一页之外去哪找"):
        assert removed not in text
    assert "`" not in text
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", text)


def test_the_page_follows_catalog_changes_without_repeating_rows() -> None:
    removed = catalog.ROUTES[0].display_label
    with mock.patch.object(catalog, "ROUTES", catalog.ROUTES[1:]):
        text = gen_status.render()
        assert removed not in _rows(text)
        assert len(_rows(text)) == len(catalog.ROUTES)
    assert gen_status.render() == gen_status.render()


def test_the_engineering_safety_matrix_covers_all_routes() -> None:
    rows = route_compliance._safety_rows()
    for mode, spec in modes.MODE_SPECS.items():
        assert route_compliance._has_safety_row(mode, spec.label, rows), mode
