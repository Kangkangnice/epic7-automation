"""社区 H5 页面判据的离线验收。

判据是**判出来的页 == 这一帧肉眼看到的那一页**，不是「能判出个名字」——
判错的后果直接落在业务上（会在错的页面上点下去）。

⚠️ 这组用例刻意包含**反向断言**：每个锚点在自己的帧上必须命中，
同时在**其它页的帧**上必须不命中。只验正向的话，「共享控件当判据」那种事故
（2026-10-05 竞技场入口）照样能全绿。
"""

from __future__ import annotations

from pathlib import Path
import unittest
import unittest.mock

import cv2
import numpy as np

from auto_game_unified.games.epic7 import community_pages as cp


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_community"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "community"

# 夹具 -> 这一帧**肉眼看到**的是哪一页（含叠层：帧名说的是当前顶层）。
#
# ⚠️ **只收 1080x1920 的标准竖屏帧**（= ``core.portrait.PORTRAIT_CANVAS``，也就是
# ``adb screencap`` 出来的那一套坐标）。刻意**不收** ``tasks_fresh_live_20261006.png``：
# 它是 1103x1899 的**窗口客户区**截图（另一个采集通道、带雷电自己的边框），
# 与本判据的坐标系不同口径 —— 拿它对分数没有意义（memory：「比几何前先确认两样本同口径」）。
# 下面 ``test_all_page_fixtures_are_at_the_portrait_canvas`` 会把这条口径钉住。
PAGE_FRAMES = {
    "feed_list_live_20261006": "feed_home",
    "exchange_center_live_20261006": "exchange_empty",
    "exchange_after_redeem_live_20261006": "exchange_center",
    "tasks_one_browse_done_live_20261006": "tasks_page",
    "tasks_all_done_live_20261006": "tasks_page",
    "item_detail_live_20261006": "item_detail",
    "order_confirm_live_20261006": "order_confirm",
    "redeem_success_live_20261006": "redeem_done",
    "share_sheet_live_20261006": "share_sheet",
    "post_detail_live_20261006": "post_detail",
    "network_error_live_20261006": "network_error",
    # 2026-10-07 真机补的三张：
    # `feed_before_signin` 是**未签到**的信息流（「每日签到」图标彩色 + 右上红点），
    # `feed_after_signin` 是**签到之后**的同一页（那块变灰），
    # `signin_success` 是「签到成功！」弹窗。前两张喂 `feed_signin_state` 的
    # 正负样本，第三张喂 `signin_done` 锚点。
    "feed_before_signin_live_20261007": "feed_home",
    "feed_after_signin_live_20261007": "feed_home",
    "signin_success_live_20261007": "signin_done",
}


def fixture(name: str) -> np.ndarray:
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    if image is None:
        raise AssertionError(f"缺夹具 {name}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


class CommunityPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = cp.build_page_templates(TEMPLATES)

    # ---- 模板与区域 ----

    def test_every_anchor_has_a_template(self):
        expected = sorted(a.name for a in (*cp.ANCHORS, *cp.TASK_BUTTON_ANCHORS))
        self.assertEqual(sorted(self.templates), expected)

    def test_missing_page_template_fails_closed(self):
        """缺一张判据模板必须当场炸，不许「没有就当它没命中」式静默降级。"""
        with self.assertRaises(FileNotFoundError) as ctx:
            cp.build_page_templates(ROOT / "tests" / "fixtures" / "_no_such_templates")
        message = str(ctx.exception)
        self.assertIn("缺社区页面判据模板", message)
        # 报错要点名是哪一张，否则真机上只能靠猜
        self.assertIn("exchange_center", message)

    def test_anchor_regions_must_stay_inside_the_canvas(self):
        bad = cp.PageAnchor("bogus", (1000, 1900, 200, 200), "越界")
        with unittest.mock.patch.object(cp, "ANCHORS", (*cp.ANCHORS, bad)):
            with self.assertRaises(ValueError) as ctx:
                cp.assert_anchor_regions_inside_canvas()
        self.assertIn("bogus", str(ctx.exception))

    def test_landscape_frame_is_rejected(self):
        """横屏帧喂进来必须报错，不许判出个名字。"""
        with self.assertRaises(ValueError):
            cp.observe_pages(np.zeros((1080, 1920, 3), np.uint8), self.templates)

    def test_region_is_read_from_the_dataclass_not_hardcoded(self):
        """区域的**唯一来源**是 ``ANCHORS``；改区域只需改一处。"""
        for anchor in cp.ANCHORS:
            with self.subTest(anchor=anchor.name):
                self.assertIn(anchor.name, cp.PAGE_LABELS)

    # ---- 判页：正向 ----

    def test_judges_every_page_from_its_own_frame(self):
        for name, expected in PAGE_FRAMES.items():
            with self.subTest(frame=name):
                judgement = cp.judge_page(fixture(name), self.templates)
                self.assertEqual(judgement.name, expected, judgement.describe())

    def test_every_page_has_at_least_one_frame(self):
        """每个锚点都得有真机帧验过，否则「已验证」是空话。"""
        covered = set(PAGE_FRAMES.values())
        for anchor in cp.ANCHORS:
            if anchor.name in cp.TASK_ROW_ANCHORS:
                continue
            if anchor.name in cp.STACK_ROOT_FALLBACKS:
                continue
            with self.subTest(anchor=anchor.name):
                self.assertIn(anchor.name, covered)

    # ---- 判页：反向（防「共享控件当判据」） ----

    def test_page_anchors_do_not_fire_across_stacks(self):
        """锚点不许**跨栈**命中。

        这条是事故防线：底部四格导航、左上角放大镜都曾是「看着像判据」的共享控件，
        逐像素相同地出现在好几页上。

        ⚠️ **同栈内**的下层锚点命中上层页面是正常的（弹窗是叠上去的、下层还在，
        见模块头那张叠层表）—— 例如兑换成功页上「确认兑换」按钮实测仍是 1.0000。
        所以这里只禁跨栈，栈内的顺序由 ``test_redeem_dialog_wins_over_the_page_beneath_it``
        那组用例管。
        """
        for frame_name, expected in PAGE_FRAMES.items():
            screen = fixture(frame_name)
            expected_stack = cp.PAGE_STACKS[expected]
            for anchor in cp.ANCHORS:
                if cp.PAGE_STACKS[anchor.name] in (expected_stack, "global"):
                    continue
                with self.subTest(frame=frame_name, anchor=anchor.name):
                    score = self._score(screen, anchor)
                    self.assertLess(
                        score, cp.THRESHOLD,
                        f"{frame_name}（{expected_stack} 栈）上 {anchor.name}"
                        f"（{cp.PAGE_STACKS[anchor.name]} 栈）拿到 {score:.4f} —— 跨栈命中",
                    )

    def test_every_page_anchor_has_a_stack(self):
        for anchor in cp.ANCHORS:
            with self.subTest(anchor=anchor.name):
                self.assertIn(anchor.name, cp.PAGE_STACKS)

    # ---- 任务行（三态：未完成 / 已完成 / 认不出） ----

    def test_reads_task_rows_on_every_known_layout(self):
        """三行任务在各排版下的读数都要与肉眼一致。"""
        # (夹具, {行: 期望})
        cases = {
            "tasks_one_browse_done_live_20261006": {
                "browse": "todo", "like": "done", "share": "todo",
            },
            "tasks_all_done_live_20261006": {
                "browse": "done", "like": "done", "share": "done",
            },
        }
        for frame_name, expected in cases.items():
            screen = fixture(frame_name)
            rows = {row.key: row.state for row in cp.observe_task_rows(screen, self.templates)}
            with self.subTest(frame=frame_name):
                self.assertEqual(rows, expected)

    def test_task_rows_abstain_when_the_buttons_are_missing(self):
        """按钮位置是空白时三行都必须认不出 —— 不许默认成「已完成」。"""
        blank = np.full((1920, 1080, 3), 255, np.uint8)
        rows = cp.observe_task_rows(blank, self.templates)
        self.assertEqual([row.state for row in rows], ["unknown"] * 3)

    def test_task_rows_cover_all_three_bands(self):
        self.assertEqual([row.key for row in cp.TASK_ROWS], ["browse", "like", "share"])
        for row in cp.TASK_ROWS:
            with self.subTest(row=row.key):
                x, y, w, h = row.band
                # 按钮实测都在 x 927..1049 / 高 55，带的边界不许把它们切掉
                self.assertLessEqual(x, 927)
                self.assertGreaterEqual(x + w, 1049)
                self.assertGreaterEqual(h, 55)

    def _score(self, screen: np.ndarray, anchor: cp.PageAnchor) -> float:
        from auto_game_unified.core.matcher import best_match

        template = self.templates[anchor.name]
        x, y, w, h = anchor.region
        patch = screen[y : y + h, x : x + w]
        score, _ = best_match(patch.astype(np.float32), template.astype(np.float32))
        return float(score)

    # ---- 叠层优先级 ----

    def test_redeem_dialog_wins_over_the_page_beneath_it(self):
        """成功弹窗盖在订单确认页上时，必须报「兑换成功」而不是「订单确认」。

        ⚠️ 这是叠层的核心：下层元素在上层被压暗后照样能拿高分
        （「确认兑换」按钮在成功弹窗页上实测仍是 1.0000），所以**光看分数会判错**，
        必须靠叠层次序。
        """
        screen = fixture("redeem_success_live_20261006")
        observations = cp.observe_pages(screen, self.templates)
        names = {o.name for o in observations}
        self.assertIn("redeem_done", names, "成功弹窗本身该命中")
        top = cp.top_page(observations)
        self.assertIsNotNone(top)
        self.assertEqual(top.name, "redeem_done")

    def test_layer_order_covers_every_page_anchor(self):
        for anchor in cp.ANCHORS:
            if anchor.name in cp.TASK_ROW_ANCHORS:
                continue  # 任务行判据不表达「在哪一页」，不进叠层表
            with self.subTest(anchor=anchor.name):
                self.assertIn(anchor.name, cp.LAYER_ORDER)

    def test_all_page_fixtures_are_at_the_portrait_canvas(self):
        """判页用的夹具必须是标准竖屏画布尺寸。

        ⚠️ 这条不是洁癖：不同采集通道（``adb screencap`` vs 窗口客户区截图）出来的帧
        **不是同一套坐标**（实测有 1103x1899 的），拿它对分数、量几何都没有意义。
        ``tasks_fresh_live_20261006.png`` 就是这样一个例外，它仍被读数测试引用，
        但**不参与判页**。
        """
        for name in PAGE_FRAMES:
            with self.subTest(frame=name):
                image = fixture(name)
                self.assertEqual(
                    (image.shape[1], image.shape[0]),
                    (cp.PORTRAIT_CANVAS[0], cp.PORTRAIT_CANVAS[1]),
                    f"{name} 不是标准竖屏画布，不能用来对判据分数",
                )

    def test_task_row_anchors_are_not_pages(self):
        """任务行判据不参与「当前在哪一页」——它表达的是「这一行做没做」。"""
        self.assertEqual(cp.top_page([cp.Observation("task_todo", 1.0, (0, 0, 1, 1))]), None)
        self.assertEqual(cp.top_page([cp.Observation("task_done", 1.0, (0, 0, 1, 1))]), None)

    # ---- 认不出就说不知道 ----

    def test_abstains_instead_of_guessing(self):
        """啥都不像的画面必须判 unknown —— 认错比认不出更糟。"""
        blank = np.full((1920, 1080, 3), 128, np.uint8)
        judgement = cp.judge_page(blank, self.templates)
        self.assertEqual(judgement.name, "unknown")
        self.assertEqual(judgement.observations, ())

    # ---- 栈根兜底 ----

    def test_stack_root_fallback_needs_the_root_anchor(self):
        """栈根兜底：栈根判据不在 ⇒ 不许兜底。"""
        self.assertIsNone(cp.resolve_stack_root([], "feed_home"))
        self.assertIsNone(cp.resolve_stack_root([], "item_detail"))

    def test_stack_root_fallback_is_blocked_by_overlays(self):
        """栈根判据在、但盖层也在 ⇒ 不许兜底（否则会把帖子详情判成首页列表）。"""
        root = cp.Observation("feed_home", 0.95, (125, 1738, 65, 100))
        self.assertIsNotNone(cp.resolve_stack_root([root], "feed_home"))
        blocked = cp.resolve_stack_root(
            [root, cp.Observation("post_detail", 0.99, (560, 1790, 440, 90))], "feed_home"
        )
        self.assertIsNone(blocked)

    def test_feed_frame_resolves_to_the_feed_stack_root(self):
        """首页列表帧上「没有正向判据」，但栈根兜底必须能认出来。"""
        observations = cp.observe_pages(fixture("feed_list_live_20261006"), self.templates)
        judgement = cp.resolve_stack_root(observations, "feed_home")
        self.assertIsNotNone(judgement)
        self.assertTrue(judgement.fallback)
        self.assertEqual(judgement.name, "feed_home")
        self.assertIn("兜底", judgement.describe())

    def test_post_detail_frame_does_not_resolve_to_the_feed_list(self):
        """帖子详情也带着「首页」青绿页签 —— 它判的是「在首页这个 Tab 栈里」，
        不是「在列表页」，所以盖层在时必须否掉兜底。"""
        observations = cp.observe_pages(fixture("post_detail_live_20261006"), self.templates)
        self.assertIn("post_detail", {o.name for o in observations})
        self.assertIsNone(cp.resolve_stack_root(observations, "feed_home"))

    def test_unknown_stack_root_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            cp.resolve_stack_root([], "exchange_center")


if __name__ == "__main__":
    unittest.main()
