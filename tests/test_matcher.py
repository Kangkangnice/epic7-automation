import os
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from auto_game_unified.core import matcher
from auto_game_unified.core.matcher import (
    best_match,
    find_all_templates,
    find_best_template,
    find_template,
    load_template,
)


class TemplateMatchingTests(unittest.TestCase):
    def setUp(self):
        self.screen = np.zeros((80, 100, 3), dtype=np.uint8)
        self.template = np.array(
            [
                [[0, 0, 255], [0, 255, 0], [255, 0, 0]],
                [[255, 255, 0], [0, 255, 255], [255, 0, 255]],
            ],
            dtype=np.uint8,
        )
        self.screen[20:22, 40:43] = self.template

    def test_returns_global_center_and_score(self):
        match = find_template(self.screen, self.template, threshold=0.99)

        self.assertIsNotNone(match)
        self.assertEqual((41, 21), match.center)
        self.assertGreaterEqual(match.score, 0.99)

    def test_respects_search_region(self):
        match = find_template(
            self.screen,
            self.template,
            threshold=0.99,
            region=(0, 0, 30, 30),
        )

        self.assertIsNone(match)

    def test_best_match_keeps_score_below_business_threshold(self):
        rng = np.random.default_rng(7)
        template = rng.integers(0, 256, size=(10, 10, 3), dtype=np.uint8)
        changed = template.copy()
        changed[:3, :3] = 0
        screen = np.zeros((40, 40, 3), dtype=np.uint8)
        screen[12:22, 14:24] = changed

        best = find_best_template(screen, template, region=(0, 0, 40, 40))

        self.assertIsNotNone(best)
        self.assertLess(best.score, 0.999)
        self.assertIsNone(
            find_template(screen, template, 0.999, region=(0, 0, 40, 40))
        )


class MatchModeTests(unittest.TestCase):
    """``white_mask`` 口径：把「控件」从「背景」里抠出来再比。

    背景无关这件事**只能用分数证明** —— 同一枚图标贴在两种完全不同的底图上，
    原样比会掉下去、白掩膜比必须都站得住。下面的合成画面就是干这个的：
    一枚白十字画在中灰底上（模板的来源场景），再画到深色底上（换一条路线）。
    """

    #: 合成块边长；「图标」= 块里的一枚白色十字。
    SIZE = 20
    #: 两个场景的整体亮度，以及各自纹理的振幅。
    LIGHT = 150
    DARK = 40
    AMPLITUDE = 40

    def _scene(self, seed: int, background: int) -> np.ndarray:
        """有纹理的场景底图。

        ⚠️ 底图必须是**有结构的**，不能是纯色：``TM_CCOEFF_NORMED`` 减均值、
        除标准差 —— 纯色底换成另一个纯色底（150 → 40）分数**一点都不会掉**
        （实测 1.0000）。真实场景伤到判据的地方是底图的**纹理**，不是亮度。
        """
        rng = np.random.default_rng(seed)
        return rng.integers(
            max(0, background - self.AMPLITUDE),
            background + self.AMPLITUDE,
            (self.SIZE * 3, self.SIZE * 3, 3),
            dtype=np.uint8,
        )

    def _draw_cross(self, frame: np.ndarray, top: int, left: int) -> np.ndarray:
        frame[top + 4 : top + 16, left + 9 : left + 11] = 255
        frame[top + 9 : top + 11, left + 4 : left + 16] = 255
        return frame

    def _template(self) -> np.ndarray:
        """「生在中灰场景里的那张模板」：一块中灰纹理 + 白十字。"""
        start = self.SIZE
        block = self._scene(1, self.LIGHT)[
            start : start + self.SIZE, start : start + self.SIZE
        ].copy()
        return self._draw_cross(block, 0, 0)

    def test_the_same_icon_matches_on_a_completely_different_background(self):
        template = self._template()
        # 同一个场景（纹理逐像素一致）—— 原样比满分。
        same = self._draw_cross(self._scene(1, self.LIGHT), self.SIZE, self.SIZE)
        # 另一条路线的场景：图标画法一样，底图纹理完全不同。
        other = self._draw_cross(self._scene(2, self.DARK), self.SIZE, self.SIZE)

        raw_same = matcher.find_best_template(same, template, mode="raw").score
        raw_other = matcher.find_best_template(other, template, mode="raw").score
        masked_same = matcher.find_best_template(
            same, template, mode="white_mask"
        ).score
        masked_other = matcher.find_best_template(
            other, template, mode="white_mask"
        ).score

        # 原样比：底图的纹理一换，分数就掉 ——
        # 这正是「判据在别的场景里悄悄失效」的样子。
        # （量级也和真机对得上：月塔事故帧原样比 0.7492~0.7704。）
        self.assertGreater(raw_same, 0.99)
        self.assertLess(raw_other, 0.85)
        # 白掩膜比：两个场景都是满分，因为掩膜里只剩图标的形状。
        self.assertGreater(masked_same, 0.99)
        self.assertGreater(masked_other, 0.99)
        self.assertAlmostEqual(masked_same, masked_other, places=6)

    def test_the_mask_survives_a_light_grey_background_too(self):
        """⚠️ 白色下界是 200，不是「灰度 > 180」那种松口径。

        亮灰底（180~199）在松口径下会整片变成白色，掩膜糊成一整块 ⇒ 图标反而
        认不出来（实测 ``epic7_expedition/battle.png`` 的浅灰天空：180 只剩
        0.4085、200 有 0.8347）。这条用例把「底下那一片亮灰必须留在掩膜外」钉死。
        """
        light_grey = 190
        frame = self._draw_cross(self._scene(3, light_grey), self.SIZE, self.SIZE)

        mask = matcher.white_mask(frame)

        # 底图的亮灰不算白 ⇒ 掩膜里只有十字，占全帧很小一块。
        self.assertLess(float(np.mean(mask > 0)), 0.20)
        # 而同一帧里那块「亮灰的图标区」整体不该被算成白 —— 只有十字是白的。
        self.assertEqual(
            matcher.WHITE_PIXEL_THRESHOLD,
            200,
            "白色下界被改动了：换这个数必须重扫全库真阳性/真阴性，不是随手调",
        )

    def test_the_default_mode_is_still_the_original_ruler(self):
        template = self._template()
        other = self._draw_cross(self._scene(2, self.DARK), self.SIZE, self.SIZE)

        default = matcher.find_best_template(other, template)
        raw = matcher.find_best_template(other, template, mode="raw")
        masked = matcher.find_best_template(other, template, mode="white_mask")

        self.assertEqual("raw", matcher.MATCH_MODE_RAW)
        self.assertEqual(raw, default, "默认口径被动过：既有 2000+ 条调用方的行为会一起变")
        self.assertNotEqual(default, masked)

    def test_an_unknown_mode_raises_instead_of_falling_back(self):
        """写错口径必须**出声**：静默退回原样比的话，阈值还是新口径的数字，
        判据会变成永假 —— 属于「判据不许静默降级」那一类。"""
        screen = self._draw_cross(self._scene(1, self.LIGHT), self.SIZE, self.SIZE)
        template = self._template()

        for call in (
            lambda: matcher.find_best_template(screen, template, mode="白掩膜"),
            lambda: find_template(screen, template, 0.5, mode="white"),
            lambda: best_match(screen, template, mode=""),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_the_cache_never_serves_one_mode_an_answer_meant_for_another(self):
        """两种口径的答案不能互相串 —— 串了就是「分数看着合理、其实换了把尺子」。"""
        remember = matcher.MATCH_CACHE_ENABLED
        matcher.MATCH_CACHE_ENABLED = True
        matcher._MATCH_CACHE.clear()
        try:
            template = self._template()
            other = self._draw_cross(self._scene(2, self.DARK), self.SIZE, self.SIZE)

            with mock.patch.object(
                matcher.cv2, "matchTemplate", wraps=matcher.cv2.matchTemplate
            ) as spy:
                raw = matcher.find_best_template(other, template, mode="raw")
                masked = matcher.find_best_template(
                    other, template, mode="white_mask"
                )

            self.assertEqual(2, spy.call_count, "换口径却吃了另一个口径的缓存答案")
            self.assertNotEqual(raw.score, masked.score)
        finally:
            matcher.MATCH_CACHE_ENABLED = remember
            matcher._MATCH_CACHE.clear()

    def test_the_smooth_mode_rescues_a_button_the_other_client_drew_softly(self):
        """同一个按钮被另一个客户端「画得更柔」时，原样比会掉分、低通口径能救回来。

        造法：把模板那块图案先轻微柔化再贴回画面 —— 模拟 PC 与模拟器在抗锯齿上的
        差别（实测差异就集中在笔画那一圈薄边上）。
        """
        template = self._template()
        scene = self._scene(1, self.LIGHT)
        sharp = self._draw_cross(scene, self.SIZE, self.SIZE)

        height, width = template.shape[:2]
        soft_template = cv2.GaussianBlur(template, (0, 0), 0.6)
        scene2 = self._scene(1, self.LIGHT)
        center_y, center_x = scene2.shape[0] // 2, scene2.shape[1] // 2
        scene2[
            center_y - height // 2 : center_y - height // 2 + height,
            center_x - width // 2 : center_x - width // 2 + width,
        ] = soft_template
        # 让「柔化」这一处成为画面上唯一的差异来源
        scene2 = cv2.GaussianBlur(scene2, (0, 0), 0.35)

        raw = matcher.find_best_template(scene2, template, mode="raw")
        smooth = matcher.find_best_template(scene2, template, mode="smooth")

        self.assertIsNotNone(raw)
        self.assertIsNotNone(smooth)
        self.assertGreater(
            smooth.score,
            raw.score,
            "低通口径没能把「换了画法」的同一块 UI 救回来",
        )
        # 原样那一侧必须一个字节不变
        self.assertEqual(
            matcher.find_best_template(sharp, template, mode="raw"),
            matcher.find_best_template(sharp, template),
        )

    def test_the_smooth_mode_is_registered_so_the_guard_rails_see_it(self):
        """登记进 ``MATCH_MODES`` ⇒ 证据层会自动校验它，写错也会出声。"""
        self.assertIn(matcher.MATCH_MODE_SMOOTH, matcher.MATCH_MODES)
        self.assertEqual("smooth", matcher.MATCH_MODE_SMOOTH)

    def test_white_mask_is_a_single_channel_zero_or_255_image(self):
        image = np.array(
            [
                [[255, 255, 255], [200, 199, 200]],
                [[0, 0, 0], [255, 255, 254]],
            ],
            dtype=np.uint8,
        )

        mask = matcher.white_mask(image)

        # 三通道**都**要过界：[200, 199, 200] 里 199 不够白 ⇒ 出局。
        np.testing.assert_array_equal(
            np.array([[255, 0], [0, 255]], dtype=np.uint8), mask
        )
        self.assertEqual(2, mask.ndim)
        # 单通道输入（调用方自己先裁好的掩膜）也要能收。
        np.testing.assert_array_equal(mask, matcher.white_mask(mask))


class FindAllTemplatesTests(unittest.TestCase):
    """``find_all_templates``：同一个模板在一屏里出现多次时，**全部**都要拿到。

    实际用途就是骑士团捐赠的支援列表 —— 每一行右侧都有一个一模一样的绿色「支援1个」，
    而业务要逐个点过去；``find_best_template`` 永远只给最高分那一个，会死磕同一行。
    """

    #: 四个矩形的**左上角**（彼此相距 120 以上，远大于下面用的 min_gap）。
    CORNERS = ((20, 30), (140, 30), (260, 30), (20, 200))

    def _four_instances(self) -> tuple[np.ndarray, np.ndarray, set[tuple[int, int]]]:
        rng = np.random.default_rng(11)
        template = rng.integers(0, 256, size=(20, 20, 3), dtype=np.uint8)
        screen = np.zeros((300, 340, 3), dtype=np.uint8)
        for x, y in self.CORNERS:
            screen[y : y + 20, x : x + 20] = template
        return screen, template, {(x + 10, y + 10) for x, y in self.CORNERS}

    def test_returns_every_instance_instead_of_only_the_best(self):
        screen, template, expected = self._four_instances()

        found = find_all_templates(screen, template, 0.95, min_gap=40)

        self.assertEqual(4, len(found))
        self.assertEqual(expected, {match.center for match in found})
        # 分数降序 —— 调用方按「先点最有把握那个」的顺序取。
        self.assertEqual(
            sorted((match.score for match in found), reverse=True),
            [match.score for match in found],
        )

    def test_the_same_instance_is_not_reported_twice(self):
        """非极大值抑制半径之内只留一个峰（否则同一个按钮会被沿边缘报两次）。"""
        screen, template, _ = self._four_instances()

        tight = find_all_templates(screen, template, 0.95, min_gap=40)
        loose = find_all_templates(screen, template, 0.95, min_gap=400)

        self.assertEqual(4, len(tight))
        self.assertEqual(1, len(loose))

    def test_threshold_and_region_both_apply(self):
        screen, template, _ = self._four_instances()

        self.assertEqual([], find_all_templates(screen, template, 1.01, min_gap=40))
        in_region = find_all_templates(
            screen, template, 0.95, region=(130, 0, 60, 80), min_gap=40
        )

        self.assertEqual([(150, 40)], [match.center for match in in_region])

    def test_scaled_screen_keeps_the_aspect_ratio_contract(self):
        """``reference_size`` 与画面不一致时按比例缩放；宽高比不符就抛错。"""
        screen, template, expected = self._four_instances()
        scaled = cv2.resize(screen, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

        found = find_all_templates(
            scaled, template, 0.90, reference_size=(340, 300), min_gap=40
        )

        self.assertEqual(
            {(x // 2, y // 2) for x, y in expected},
            {match.center for match in found},
        )

        with self.assertRaises(RuntimeError):
            find_all_templates(
                scaled, template, 0.90, reference_size=(340, 200), min_gap=40
            )


class TemplateLoadingTests(unittest.TestCase):
    """load_template 会缓存解码结果，缓存不能改变「读到的内容」。"""

    def test_matches_a_direct_decode_on_every_call(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "t.png")
            cv2.imwrite(path, np.array([[[0, 0, 255], [0, 255, 0]]], dtype=np.uint8))

            for _ in range(3):
                expected = cv2.cvtColor(
                    cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
                )
                np.testing.assert_array_equal(expected, load_template(path))

    def test_reloads_when_the_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "t.png")
            cv2.imwrite(path, np.full((2, 2, 3), 10, dtype=np.uint8))
            self.assertEqual((2, 2, 3), load_template(path).shape)

            cv2.imwrite(path, np.full((5, 5, 3), 200, dtype=np.uint8))
            np.testing.assert_array_equal(
                np.full((5, 5, 3), 200, dtype=np.uint8), load_template(path)
            )

    def test_missing_file_still_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                load_template(os.path.join(folder, "missing.png"))


class MatchCacheTests(unittest.TestCase):
    """匹配结果缓存的护栏：它**只能**省时间，绝不能改变任何答案。

    这一层最容易出的错是**键取得不够** —— 少喂了形状、少喂了一块像素，缓存就会把上一次
    的答案发给这一次，而且看上去完全正常（分数是个合理数字、坐标也像样）。
    所以这里逐条钉住：重复查询不重算、改了画面或模板必须重算、关掉缓存答案一样。
    """

    def setUp(self):
        # 记下**conftest 给的值**，最后一条用例要拿它验接线。
        self._suite_value = matcher.MATCH_CACHE_ENABLED
        self._size = matcher.MATCH_CACHE_SIZE
        matcher.MATCH_CACHE_ENABLED = True
        matcher._MATCH_CACHE.clear()
        rng = np.random.default_rng(23)
        self.screen = rng.integers(0, 256, size=(60, 80, 3), dtype=np.uint8)
        self.template = self.screen[10:26, 20:44].copy()

    def tearDown(self):
        matcher.MATCH_CACHE_ENABLED = self._suite_value
        matcher.MATCH_CACHE_SIZE = self._size
        matcher._MATCH_CACHE.clear()

    def _spy_on_matcher(self):
        """数一数「真正落回匹配引擎」的次数。"""
        return mock.patch.object(
            matcher.cv2, "matchTemplate", wraps=matcher.cv2.matchTemplate
        )

    def test_a_repeated_query_is_answered_from_the_cache(self):
        with self._spy_on_matcher() as spy:
            first = find_best_template(self.screen, self.template)
            second = find_best_template(self.screen, self.template)

        self.assertEqual(first, second)
        # 第二次必须**没有**再落回匹配引擎 —— 否则这条缓存等于没接上。
        self.assertEqual(1, spy.call_count)

    def test_a_changed_screen_is_never_answered_from_the_cache(self):
        changed = self.screen.copy()
        changed[5, 5, 0] = int(changed[5, 5, 0]) ^ 255

        with self._spy_on_matcher() as spy:
            find_best_template(self.screen, self.template)
            got = find_best_template(changed, self.template)

        self.assertEqual(2, spy.call_count, "画面变了却还吃缓存 = 会返回过期答案")
        # 拿掉缓存重算一次，逐个字段比 —— 缓存的答案必须与它**完全**一致。
        matcher._MATCH_CACHE.clear()
        self.assertEqual(find_best_template(changed, self.template), got)

    def test_a_changed_template_is_never_answered_from_the_cache(self):
        other = self.template.copy()
        other[0, 0, 0] = int(other[0, 0, 0]) ^ 255

        with self._spy_on_matcher() as spy:
            find_best_template(self.screen, self.template)
            got = find_best_template(self.screen, other)

        self.assertEqual(2, spy.call_count, "模板变了却还吃缓存 = 会返回过期答案")
        matcher._MATCH_CACHE.clear()
        self.assertEqual(find_best_template(self.screen, other), got)

    def test_two_templates_on_one_screen_do_not_share_an_answer(self):
        other = self.screen[40:56, 4:28].copy()

        with self._spy_on_matcher() as spy:
            first = find_best_template(self.screen, self.template)
            second = find_best_template(self.screen, other)

        self.assertEqual(2, spy.call_count)
        self.assertNotEqual(first, second)

    def test_the_digest_carries_the_shape_not_just_the_bytes(self):
        """``2x3`` 与 ``3x2`` 的字节完全一样 —— 指纹必须把它们分开，否则会互相串答案。"""
        flat = np.arange(6, dtype=np.uint8)
        wide = flat.reshape(2, 3)
        tall = flat.reshape(3, 2)

        self.assertNotEqual(
            matcher._match_key(wide, self.template),
            matcher._match_key(tall, self.template),
        )

    def test_a_disabled_cache_still_answers_correctly(self):
        with self._spy_on_matcher() as spy:
            first = find_best_template(self.screen, self.template)
            matcher.MATCH_CACHE_ENABLED = False
            matcher._MATCH_CACHE.clear()
            second = find_best_template(self.screen, self.template)

        self.assertEqual(first, second)
        self.assertEqual(2, spy.call_count, "关掉之后就不该再走缓存")

    def test_the_cache_is_bounded(self):
        matcher.MATCH_CACHE_SIZE = 5

        for index in range(8):
            template = self.template.copy()
            template[0, 0, 0] = index
            best_match(self.screen, template)

        self.assertLessEqual(len(matcher._MATCH_CACHE), 5)

    def test_the_suite_really_turns_it_on(self):
        """conftest 必须真的打开它 —— 否则全量会**悄悄**慢回去，没有任何报错。"""
        if os.environ.get("EPIC7_MATCH_CACHE", "1") == "0":
            self.skipTest("本次按环境变量关掉了匹配缓存")
        self.assertTrue(
            self._suite_value,
            "tests/conftest.py 没有打开 matcher.MATCH_CACHE_ENABLED",
        )


if __name__ == "__main__":
    unittest.main()
