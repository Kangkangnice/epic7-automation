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

from auto_game_unified.games.epic7 import community as cm
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
    # 2026-10-08 真机补的一张：**帖子里的图片被点开放大成全屏**（图片查看器）。
    # 它是 10-08 两次实跑（18:58 / 19:10）卡死的那一屏，也是 10-07 20:39 那一屏。
    # ⚠️ 这一档的判据**不是模板**（见 ``cp.detect_image_viewer``）：上下两条全黑带
    # 占 0.8370、中间只有一张图 ⇒ 所有模板都匹配不上（实测最高分 0.0000），
    # 所以帧名认的是**结构**而不是锚点分数。
    "image_viewer_live_20261008": "image_viewer",
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
        """三批锚点（页面判据 / 任务按钮 / 卡片 👍）里的每一个都要有模板。

        ⚠️ 卡片 👍 也算在里面：它是**判据型**模板（「这一颗还没点过」就是靠它成立的），
        少了它 ``locate_card_like`` 会抛 ``KeyError`` —— 而那是泄漏到主循环里的
        崩溃，不是「没命中」。所以加载器必须 fail-closed 地把它一起读进来。
        """
        expected = sorted(
            a.name
            for a in (
                *cp.ANCHORS,
                *cp.TASK_BUTTON_ANCHORS,
                *cp.CARD_LIKE_ANCHORS,
                *cp.FEED_ICON_ANCHORS,
            )
        )
        self.assertEqual(sorted(self.templates), expected)
        self.assertIn("card_like_off", self.templates)
        self.assertIn("feed_icon_exchange", self.templates)

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
        """两行任务在各排版下的读数都要与肉眼一致。

        ⚠️ **2026-10-11：清单里只剩 browse / share**（「点赞帖子」已摘掉，
        理由见 ``community_pages.TASK_ROWS`` 那段）。所以期望值里**不许再有 like** ——
        不是「它读不出来」，是它**已经不在清单里**、压根不会被读。
        """
        # (夹具, {行: 期望})
        cases = {
            "tasks_one_browse_done_live_20261006": {
                "browse": "todo", "share": "todo",
            },
            "tasks_all_done_live_20261006": {
                "browse": "done", "share": "done",
            },
        }
        for frame_name, expected in cases.items():
            screen = fixture(frame_name)
            rows = {row.key: row.state for row in cp.observe_task_rows(screen, self.templates)}
            with self.subTest(frame=frame_name):
                self.assertEqual(rows, expected)

    def test_task_rows_abstain_when_the_buttons_are_missing(self):
        """按钮位置是空白时每一行都必须认不出 —— 不许默认成「已完成」。"""
        blank = np.full((1920, 1080, 3), 255, np.uint8)
        rows = cp.observe_task_rows(blank, self.templates)
        self.assertEqual([row.state for row in rows], ["unknown"] * len(cp.TASK_ROWS))

    def test_task_rows_cover_the_declared_bands(self):
        """清单里的每一行：**按钮带必须真的框住那行按钮**（不许把按钮切掉）。

        ⚠️ 名字里的「all three」已改（2026-10-11 摘掉点赞后只剩两行）——
        但**断言名单仍然独立写死**，不从 ``cp.TASK_ROWS`` 反推，
        否则「清单少了一行」这种改动它照样绿。
        """
        self.assertEqual([row.key for row in cp.TASK_ROWS], ["browse", "share"])
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

    # ---- 图片查看器：结构性判据（**不是模板**）----

    def test_image_viewer_is_judged_from_its_own_frame(self):
        """把帖子里的图点开放大之后那一屏，必须判成 ``image_viewer``。

        ⚠️ 这一档**没有锚点、没有模板**：帧上上下两条全黑带占 0.8370，中间只有一张图，
        所有模板实测都拿 0.0000 ⇒ ``top_page`` 会返回 ``None``、整页判成 ``unknown``，
        而 ``unknown`` 在这条路线上等于「认不出画面」⇒ 主循环重试到超时、收尾还把
        已经打开的社区也关不掉。2026-10-08 两次实跑（18:58 / 19:10）都是这个形状。
        """
        judgement = cp.judge_page(fixture("image_viewer_live_20261008"), self.templates)
        self.assertEqual(judgement.name, "image_viewer", judgement.describe())
        self.assertIn("图片查看器", judgement.label)

    def test_image_viewer_never_fires_on_any_other_portrait_frame(self):
        """**全量负样本扫描**：``tests/fixtures`` 里除它自己以外的每一张竖屏帧都不许命中。

        只测正向抓不住「判据太松」——一条「黑行占比 ≥ 0.60」要是写松了，
        深色页面（帖子详情长图、兑换中心暗色卡）就可能被误判成查看器，
        后果是**在那个页面上按返回键**（把用户正常的页面退掉）。
        """
        from pathlib import Path as _Path

        fixtures_root = _Path(__file__).resolve().parents[1] / "tests" / "fixtures"
        scanned = 0
        for path in sorted(fixtures_root.rglob("*.png")):
            image = cv2.imread(str(path))
            if image is None or image.shape[:2] != (
                cp.PORTRAIT_CANVAS[1],
                cp.PORTRAIT_CANVAS[0],
            ):
                continue
            scanned += 1
            if path.stem == "image_viewer_live_20261008":
                continue
            with self.subTest(frame=path.stem):
                self.assertIsNone(
                    cp.detect_image_viewer(image),
                    f"{path.stem} 被误判成图片查看器 —— 会在正常页面上按返回键",
                )
        # 别让「一张都没扫到」伪装成绿
        self.assertGreaterEqual(scanned, 15)

    def test_image_viewer_requires_a_content_band_not_touching_the_edges(self):
        """整屏纯黑（加载中的黑屏）不许当查看器 —— 那样会把正常页面按掉。"""
        self.assertIsNone(cp.detect_image_viewer(np.zeros((1920, 1080, 3), np.uint8)))
        # 黑带占 3/4，但内容带**贴着上边缘** ⇒ 不是查看器（查看器上下都有黑带）
        edge = np.zeros((1920, 1080, 3), np.uint8)
        edge[:480] = 200
        self.assertIsNone(cp.detect_image_viewer(edge))

    def test_image_viewer_rejects_a_landscape_frame(self):
        """横屏帧喂进来必须报错，不许「顺手」判成查看器。"""
        with self.assertRaises(ValueError):
            cp.detect_image_viewer(np.zeros((1080, 1920, 3), np.uint8))

    def test_image_viewer_centre_sits_inside_the_content_band(self):
        """兜底点击点必须落在内容带里。

        ⚠️ 这一档的动作本意是**按返回键**（``CommunityAction.press_back``），
        这个点只在返回键那一路没被认出来时兜底。但它不许落在黑带上 ——
        落在 ``(0, 0)`` 或黑边上是最难查的那种失败。
        """
        frame = cp.detect_image_viewer(fixture("image_viewer_live_20261008"))
        self.assertIsNotNone(frame)
        assert frame is not None
        top, bottom = frame.band
        self.assertLess(top, frame.center[1])
        self.assertGreater(bottom, frame.center[1])
        self.assertEqual(frame.center[0], cp.PORTRAIT_CANVAS[0] // 2)

    def test_image_viewer_is_flagged_as_a_global_overlay(self):
        """它盖在整屏上，层序必须在 ``network_error`` 之上（先收查看器再谈别的）。"""
        self.assertEqual(cp.PAGE_STACKS["image_viewer"], "global")
        self.assertIn("image_viewer", cp.STACK_OVERLAYS["feed_home"])
        self.assertLess(cp.LAYER_ORDER["image_viewer"], cp.LAYER_ORDER["network_error"])

    # ---- 信息流正文带：点击点**运行时现找**（治盲坐标）----

    def test_feed_tap_band_accepts_body_text_and_rejects_a_photo(self):
        """三条判据的正负样本：正文通过；照片、空白、彩色块都不通过。

        ⚠️ 边界样本**按实测值构造**，不造极端值。造一坨纯色（``colorful=1.0``）看着更
        「像图片」，但那种样本**怎么放水都挡得住** —— 彩色上限调到 0.99 它照样红，
        护栏就成了摆设。这里按真机那张表来：正文带实测 ≤0.098、图片带 ≥0.147，
        ⇒ 0.15 与 0.09 一个该挡、一个该放，正好夹住 0.12 那道阈值。
        """
        white = np.full((12, 1080, 3), 255, np.uint8)
        # 白底 + 有字（3% 暗像素）
        text = white.copy()
        text[:, 40:400] = 0
        self.assertTrue(cp.feed_tap_band_is_text(text, 0, 12))
        # 纯白（卡片之间的白缝）
        self.assertFalse(cp.feed_tap_band_is_text(white, 0, 12))
        # 彩色照片：够暗但彩色占比高
        photo = np.full((12, 1080, 3), (40, 90, 200), np.uint8)
        self.assertFalse(cp.feed_tap_band_is_text(photo, 0, 12))
        # 黑白照片：彩色占比低、也够暗，但**不白** ⇒ 靠第 3 条挡掉
        gray_photo = np.full((12, 1080, 3), 128, np.uint8)
        self.assertFalse(cp.feed_tap_band_is_text(gray_photo, 0, 12))

        # --- 彩色那一条的**边界**：这是它唯一能单独拦下的形状 ---
        # 白底 + 有字 + 一小片彩色（15%）—— 典型的「白边插图 / 白底图」。
        # 白与暗两条都过得去，**只有彩色这一条能挡**。
        tinted = white.copy()
        tinted[:, :162] = (30, 60, 220)  # 162/1080 = 0.150 彩色
        tinted[:, 800:854] = 0  # 54/1080 = 0.050 暗（有字）
        band = tinted.reshape(-1, 3).astype(np.int16)
        colorful = float(((band.max(axis=1) - band.min(axis=1)) > cp.FEED_TAP_SATURATION).mean())
        self.assertAlmostEqual(colorful, 0.15, places=2)
        self.assertGreater(colorful, cp.FEED_TAP_COLORFUL_MAX)
        self.assertFalse(
            cp.feed_tap_band_is_text(tinted, 0, 12),
            "彩色占比 0.15 的白底图被判成正文 —— 点下去就是图片查看器",
        )
        # 同一形状、彩色降到 0.09（正文带实测上限）⇒ 必须放行，
        # 否则「阈值调得太紧、连正文都不认」这条反向毛病没人守。
        mostly_text = white.copy()
        mostly_text[:, :97] = (30, 60, 220)  # 0.090 彩色
        mostly_text[:, 800:854] = 0
        self.assertTrue(cp.feed_tap_band_is_text(mostly_text, 0, 12))

        # --- 真机那一条真实存在的「彩色过渡带」---
        # 现场帧 y 1714~1726：图片下沿 + 白缝 + 底栏图标顶，实测
        # colorful=0.147 / ink=0.048 / white=0.672 —— 白与暗**都过得去**，
        # 只靠彩色这一条挡住。宁可不要这一条模糊的带。
        live_gap = fixture("feed_list_live_20261006")[1714:1726]
        self.assertFalse(
            cp.feed_tap_band_is_text(live_gap, 0, 12),
            "真机那条贴边过渡带被判成正文 —— 宁可不要它，也不点上去",
        )

    def test_locate_feed_post_tap_moves_off_the_image_on_the_live_frame(self):
        """⚠️ 本文件最重要的一条：在**那次实跑的原帧**上，现找出来的点不许落在图片上。

        现场帧 ``feed_cards_all_todo_live_20261007`` 上，脚本里钉死的 ``(400, 1450)``
        正好落在卡片 2 的**图片带**（y 1360~1630）里 ⇒ 点下去把图放大成全屏查看器，
        整条路线卡死（2026-10-08 18:58 / 19:10 两次，外加 10-07 20:39）。

        现找出来的点必须落在这张图**上面**那条正文带里，并且三条判据都成立。
        """
        screen = fixture("feed_cards_all_todo_live_20261007")
        hint = cm.FEED_FIRST_POST
        # 先钉住**根因**：脚本那个盲坐标在这一帧上确实是「不能点的地方」。
        # 少了这一条，将来布局再变、hint 又变回文字带时，用例会「因为别的原因」变绿，
        # 看上去还在守，其实已经守不住任何东西了。
        self.assertFalse(
            cp.feed_tap_band_is_text(screen, hint[1] - cp.FEED_TAP_SLAB // 2, cp.FEED_TAP_SLAB),
            f"盲坐标 {hint} 在这一帧上居然落在正文带上 —— 这条用例的前提已不成立，"
            "请换一张真机帧当靶子，别直接删",
        )
        found = cp.locate_feed_post_tap(screen, hint)
        self.assertIsNotNone(found, "在这一帧上必须找得到正文带，否则任务直接作废")
        assert found is not None
        x, y = found
        self.assertEqual(x, hint[0], "x 必须原样沿用脚本给的 hint，不许自己另取一个")
        self.assertLess(y, hint[1], "现找必须**往上**避开图片，不许还落在图片上")
        self.assertTrue(
            cp.feed_tap_band_is_text(screen, y - cp.FEED_TAP_SLAB // 2, cp.FEED_TAP_SLAB),
            f"现找出来的 {found} 底下那条带不满足「白底 + 有字 + 不是图片」",
        )

    def test_locate_feed_post_tap_keeps_the_hint_when_it_already_was_text(self):
        """**原来点得对的时候行为不变** —— 现找只在盲坐标落进死区时才改判。"""
        screen = fixture("feed_list_live_20261006")
        hint = cm.FEED_FIRST_POST
        found = cp.locate_feed_post_tap(screen, hint)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertLess(abs(found[1] - hint[1]), cp.FEED_TAP_SLAB * 2)

    def test_locate_feed_post_tap_abstains_on_the_image_viewer(self):
        """查看器那一屏上**一条正文带都没有** ⇒ 必须返回 ``None``。

        ⚠️ ``None`` 的语义是「找不到就收手」，调用方**绝不许退回盲坐标**：
        那正是把一个已经卡死的局面再点一遍。这里是它最容易发生的场合。
        """
        self.assertIsNone(
            cp.locate_feed_post_tap(
                fixture("image_viewer_live_20261008"), cm.FEED_FIRST_POST
            )
        )

    def test_locate_feed_post_tap_rejects_a_landscape_frame(self):
        with self.assertRaises(ValueError):
            cp.locate_feed_post_tap(
                np.zeros((1080, 1920, 3), np.uint8), cm.FEED_FIRST_POST
            )


if __name__ == "__main__":
    unittest.main()
