"""英雄分类：职业 / 属性 / 星级。

数据来源：``templates/arena/heroes_pokedex/meta.json``（2026-11-17 建立）。
建立方式：按公开英雄库的角色表取出职业、属性、星级，再用头像与图鉴库逐一比对
确认是同一名英雄，不按名字匹配 —— 图鉴库的名字来自图鉴页识别，存在错字
（例：库里名为「岚」的头像实际是 Ken，「亚敏」实际是 Aki），按名字对齐会串行。

表里没有的名字视为「未收录分类」：界面照常列出、可勾选，只是不参与分类筛选。
未收录不会被隐藏，也不会被猜一个分类。

这张表是**快照**，不会自己更新：
- 新英雄上线：用 ``tools/add_hero.py`` 补头像并写入这一条（步骤见
  ``docs/maintenance/hero_roster.md`` 第二节）；
- 批量复核 / 看外部库新增了谁：用 ``tools/refresh_hero_meta.py --check``，
  确认报告后加 ``--write`` 落盘。
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from auto_game_unified.games.epic7.hero_match import default_library_dir

# 顺序与游戏内英雄管理的筛选面板一致，界面直接按此顺序生成按钮。
JOBS = ("战士", "骑士", "盗贼", "射手", "魔导士", "精灵师")
ELEMENTS = ("火", "水", "木", "光", "暗")
STARS = (5, 4, 3)

META_FILENAME = "meta.json"


@dataclass(frozen=True)
class HeroMeta:
    """一名英雄的分类。``stars`` 是初始星级（3 / 4 / 5）。"""

    job: str
    element: str
    stars: int


def meta_path() -> Path:
    return default_library_dir() / META_FILENAME


@lru_cache(maxsize=1)
def _load(path_text: str) -> dict[str, HeroMeta]:
    """读表并按取值白名单过滤。

    ⚠️ 非法取值一律丢弃而不是原样透传：分类会被当作筛选键，脏值只会让那名英雄
    在任何一组筛选下都消失 —— 那正是「悄悄少一个」的形态。丢弃后它按未收录处理，
    界面上仍然看得到。
    """

    path = Path(path_text)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = payload.get("heroes") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    table: dict[str, HeroMeta] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        job = value.get("job")
        element = value.get("element")
        stars = value.get("stars")
        if job not in JOBS or element not in ELEMENTS:
            continue
        if isinstance(stars, bool) or not isinstance(stars, int) or stars not in STARS:
            continue
        table[name] = HeroMeta(job=job, element=element, stars=stars)
    return table


def meta_table() -> dict[str, HeroMeta]:
    return _load(str(meta_path()))


def hero_meta(name: str) -> HeroMeta | None:
    return meta_table().get(name)


def unclassified_count(names: list[str]) -> int:
    table = meta_table()
    return sum(1 for name in names if name not in table)


def filter_names(
    names: list[str],
    *,
    keyword: str = "",
    jobs: Collection[object] = (),
    elements: Collection[object] = (),
    stars: Collection[object] = (),
) -> list[str]:
    """按名字或分类挑出一批候选。

    ⚠️ 有搜索词时**只按名字过滤、忽略全部分类条件**。否则「筛了某职业 + 搜一个
    未收录分类的英雄」会得到空列表 —— 使用者会以为那名英雄不在库里。

    没有搜索词时按分类取交集；三组都为空即不筛选，原样返回（含未收录分类的英雄）。
    未收录分类的英雄在任何一组分类条件生效时都不出现，因为它们没有可匹配的值。
    """

    text = keyword.strip()
    if text:
        return [name for name in names if text in name]
    table = meta_table()
    chosen_jobs = set(jobs)
    chosen_elements = set(elements)
    chosen_stars = set(stars)
    if not (chosen_jobs or chosen_elements or chosen_stars):
        return list(names)
    result: list[str] = []
    for name in names:
        meta = table.get(name)
        if meta is None:
            continue
        if chosen_jobs and meta.job not in chosen_jobs:
            continue
        if chosen_elements and meta.element not in chosen_elements:
            continue
        if chosen_stars and meta.stars not in chosen_stars:
            continue
        result.append(name)
    return result
