"""英雄分类数据与筛选口径（2026-11-17）。

两层：

1. **数据表**（``templates/arena/heroes_pokedex/meta.json``）：按头像比对建立，
   表里没有的名字视为「未收录分类」。这里只校验取值落在白名单内、覆盖率不离谱 ——
   新英雄上线后未收录数量增加是正常状态，界面会如实显示，不该让测试变红。
2. **筛选口径**（``hero_catalog.filter_names``）：纯函数，界面与测试共用。
   这一组用假表，不依赖具体英雄属于哪个职业，免得数据更新后测试跟着红。
"""

import unittest
from unittest.mock import patch

from auto_game_unified.games.epic7.hero_catalog import (
    ELEMENTS,
    JOBS,
    STARS,
    HeroMeta,
    filter_names,
    hero_meta,
    meta_table,
    unclassified_count,
)
from auto_game_unified.games.epic7.hero_match import default_library_dir, library_names

FAKE = {
    "甲": HeroMeta(job="战士", element="火", stars=5),
    "乙": HeroMeta(job="精灵师", element="水", stars=4),
    "丙": HeroMeta(job="战士", element="水", stars=3),
}
NAMES = ["甲", "乙", "丙", "未收录丁"]


class MetaTableTests(unittest.TestCase):
    def test_values_are_in_the_allowed_sets(self):
        table = meta_table()
        self.assertGreater(len(table), 300)
        for name, meta in table.items():
            self.assertIn(meta.job, JOBS, name)
            self.assertIn(meta.element, ELEMENTS, name)
            self.assertIn(meta.stars, STARS, name)

    def test_unknown_name_is_reported_as_missing_instead_of_guessed(self):
        self.assertIsNone(hero_meta("这个英雄不存在"))

    def test_table_covers_most_of_the_library(self):
        names = library_names(default_library_dir())
        self.assertTrue(names, "缺少图鉴库，无法核对覆盖率")
        self.assertLessEqual(
            unclassified_count(names),
            60,
            "未收录分类的英雄数量异常增长，检查 meta.json 是否被截断",
        )

    def test_entry_carries_three_fields(self):
        meta = hero_meta(next(iter(meta_table())))
        assert meta is not None
        self.assertIsInstance(meta.job, str)
        self.assertIsInstance(meta.element, str)
        self.assertIn(meta.stars, STARS)


@patch(
    "auto_game_unified.games.epic7.hero_catalog.meta_table",
    new=lambda: dict(FAKE),
)
class FilterNamesTests(unittest.TestCase):
    def test_no_condition_returns_everything(self):
        self.assertEqual(NAMES, filter_names(NAMES))

    def test_single_job_keeps_only_that_job(self):
        self.assertEqual(["甲", "丙"], filter_names(NAMES, jobs={"战士"}))

    def test_multiple_values_in_one_group_are_a_union(self):
        self.assertEqual(["甲", "丙"], filter_names(NAMES, jobs={"战士", "圣骑士"}))

    def test_groups_are_combined_as_an_intersection(self):
        self.assertEqual(["甲"], filter_names(NAMES, jobs={"战士"}, elements={"火"}))
        self.assertEqual(
            ["丙"], filter_names(NAMES, jobs={"战士"}, elements={"水"}, stars={3})
        )

    def test_unclassified_names_disappear_once_a_condition_is_applied(self):
        self.assertIn("未收录丁", filter_names(NAMES))
        self.assertNotIn("未收录丁", filter_names(NAMES, jobs={"战士"}))

    def test_search_ignores_the_classification_conditions(self):
        """⚠️ 核心行为：搜索时分类条件不生效。

        否则搜一个未收录分类的英雄、而分类按钮还停在某个职业上时，结果会是空的，
        看起来像库里没有这个人。
        """
        self.assertEqual(
            ["乙"], filter_names(NAMES, keyword="乙", jobs={"战士"}, stars={5})
        )
        self.assertEqual(["未收录丁"], filter_names(NAMES, keyword="未收录", jobs={"战士"}))

    def test_blank_search_falls_back_to_the_conditions(self):
        self.assertEqual(["甲"], filter_names(NAMES, keyword="   ", jobs={"战士"}, elements={"火"}))


if __name__ == "__main__":
    unittest.main()
