"""骑士团支援列表「读数字」判据（``knights_support_digits``）的回归测试。

守四件事：

1. **字模齐备且形状对上**：真模板目录里 0~5 六个都在、都是 18×24 二值；
   缺一个必须**在加载时报错**（不能安静地退回「照旧点」）。
2. **真帧上读得对**：5 行实拍帧（含 2026-09-25 事故帧）的「持有 / 需求 / 结论」逐行对上。
3. **认不出就说不知道**：非数字形状（实心色块）、空区域、字模缺失、非基准分辨率
   —— 四种情形都必须返回「不知道」，**绝不猜一个数字出来**。
   ⚠️ 这条是判据的安全阀：认错会白丢积分，认不出只是帮不上忙。
4. **阈值是量出来的不是调出来的**：正确匹配的最低分要**高于**阈值、错配的最高分要
   **低于**阈值，两边都留余量（把这个余量钉在测试里，改了字模就会报警）。
"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.knights_support_digits import (
    GLYPH_CANVAS,
    GLYPH_MATCH_MIN_SCORE,
    REFERENCE_SIZE,
    REQUIRED_DIGITS,
    RowNumbers,
    glyph_boxes,
    glyph_score,
    green_mask,
    load_digit_glyphs,
    normalize_glyph,
    read_row_numbers,
    white_mask,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "knights_donation"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_knights_donation"

# 实拍帧上的真值：(夹具名, 按钮中心, 持有, 需求, 是否材料不足)。
# 「持有 / 需求」是肉眼从画面上读出来的（复核图：docs/manual_review/knights_donation/）。
REAL_ROWS = (
    # 2026-09-25 事故帧：上面那格持有 1、这一格要 2 ⇒ 不足。当时程序对着它连点 4 次、
    # 整条路线提前收工。
    ("support_page_short_material", (1681, 569), 1, 2, True),
    ("support_page_short_material", (1681, 764), 225, 4, False),
    # 2026-09-24 实拍的两按钮帧：上面那格持有 0、要 1 ⇒ 不足。
    ("support_page_two_buttons", (1681, 569), 0, 1, True),
    ("support_page_two_buttons", (1681, 764), 5133, 1, False),
    ("support_page", (1681, 569), 5133, 1, False),
)


def screen(name: str) -> np.ndarray:
    """夹具按 RGB 读入（与 ``load_template`` / ``runtime.capture()`` 同口径）。"""
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"读不到夹具 {name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def real_glyphs() -> dict[int, np.ndarray]:
    return load_digit_glyphs(TEMPLATES)


class GlyphTemplateTests(unittest.TestCase):
    def test_the_shipped_templates_cover_zero_to_five(self):
        glyphs = real_glyphs()

        self.assertEqual(set(REQUIRED_DIGITS), set(glyphs))
        for digit, glyph in glyphs.items():
            with self.subTest(digit=digit):
                self.assertEqual((GLYPH_CANVAS[1], GLYPH_CANVAS[0]), glyph.shape)
                # 二值：只有 0 与 255。
                self.assertEqual({0, 255}, set(np.unique(glyph).tolist()))

    def test_the_route_templates_carry_the_glyphs(self):
        """判据真的**接在路线上了**：路线自己的模板构建器必须把 0~5 一起带上。

        少了这条护栏，「材料不足就跳过」会安静地退化成「照旧点」—— 本项目最怕的
        「判据没接上」那类失效（它不会让任何测试变红，只会让实跑照样中止）。
        """
        from auto_game_unified.games.epic7.knights_donation import (
            build_knights_donation_templates,
        )

        templates = build_knights_donation_templates(TEMPLATES)

        self.assertEqual(set(REQUIRED_DIGITS), set(templates.digit_glyphs))

    def test_a_missing_glyph_file_fails_at_load_time(self):
        """缺字模必须在**加载时**抛错：安静地退回「照旧点」正是要避免的那类失效。"""
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(FileNotFoundError) as caught:
                load_digit_glyphs(Path(raw))
            self.assertIn("数字字模", str(caught.exception))


class RealFrameTests(unittest.TestCase):
    def test_every_real_row_reads_the_expected_numbers(self):
        glyphs = real_glyphs()

        for name, center, holdings, required, short in REAL_ROWS:
            with self.subTest(row=f"{name}@{center[1]}"):
                numbers = read_row_numbers(screen(name), center, glyphs)
                self.assertEqual(holdings, numbers.holdings)
                self.assertEqual(required, numbers.required)
                self.assertIs(short, numbers.verdict)

    def test_the_accident_frame_is_read_as_short_of_material(self):
        """事故帧上那一格：持有 1 / 需求 2 ⇒ 明确判「不足」（这条判据的全部意义所在）。"""
        numbers = read_row_numbers(screen("support_page_short_material"), (1681, 569), real_glyphs())

        self.assertEqual(RowNumbers(1, 2), numbers)
        self.assertIs(True, numbers.verdict)

    def test_the_two_readable_rows_in_one_frame_are_told_apart(self):
        """同一帧里两格符号相反：上面不足、下面够 —— 判据必须把两格分开，
        而不是给整帧一个结论（这是「按行判」与「按颜色判」的分水岭）。"""
        frame = screen("support_page_short_material")
        glyphs = real_glyphs()

        blocked = read_row_numbers(frame, (1681, 569), glyphs)
        ok = read_row_numbers(frame, (1681, 764), glyphs)

        self.assertIs(True, blocked.verdict)
        self.assertIs(False, ok.verdict)

    def test_the_reading_is_stable_when_asked_twice(self):
        """同一帧读两次结果一样（判据必须是纯函数：主循环每帧都会重问一遍）。"""
        frame = screen("support_page_short_material")
        glyphs = real_glyphs()

        first = read_row_numbers(frame, (1681, 569), glyphs)
        second = read_row_numbers(frame, (1681, 569), glyphs)

        self.assertEqual(first, second)


class UnknownTests(unittest.TestCase):
    """认不出 ⇒ 一律「不知道」（``verdict is None``），调用方据此照旧去点。"""

    def test_no_glyphs_means_unknown(self):
        numbers = read_row_numbers(screen("support_page_short_material"), (1681, 569), {})

        self.assertEqual(RowNumbers(None, None), numbers)
        self.assertIsNone(numbers.verdict)

    def test_a_solid_block_is_not_read_as_a_digit(self):
        """实心色块（「根本不是数字」的形状）不能匹配出任何数字。"""
        mask = np.zeros((30, 30), np.uint8)
        mask[4:26, 8:22] = 255  # 14x22，尺寸与真字形一样，形状完全不像

        boxes = glyph_boxes(mask)
        self.assertEqual(1, len(boxes), "这个尺寸必须能过连通域筛子，否则测的就不是阈值了")

        glyph = normalize_glyph(mask, boxes[0])
        scores = {digit: glyph_score(glyph, template) for digit, template in real_glyphs().items()}
        self.assertLess(max(scores.values()), GLYPH_MATCH_MIN_SCORE, f"实心块的分数：{scores}")

    def test_a_row_without_text_is_unknown(self):
        """按钮中心落到没有文字的地方（例如骑士团主页）⇒ 不知道，不能瞎认。"""
        numbers = read_row_numbers(screen("guild_home_no_dot"), (1681, 569), real_glyphs())

        self.assertEqual(RowNumbers(None, None), numbers)

    def test_another_resolution_abstains_instead_of_guessing(self):
        """非基准分辨率 ⇒ **整条判据弃权**（实测 2 倍下绿色那侧根本读不出来）。

        项目里没有别的分辨率的真帧可验，所以这里刻意不给「缩放后也能读」的承诺 ——
        读错比读不出更糟。换了分辨率要按 ``SIZE_TOLERANCE`` 的注释重新采。
        """
        frame = screen("support_page_short_material")
        glyphs = real_glyphs()

        for scale in (2.0, 0.5):
            big = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            center = (round(1681 * scale), round(569 * scale))
            with self.subTest(scale=scale):
                numbers = read_row_numbers(big, center, glyphs, reference_size=REFERENCE_SIZE)
                self.assertEqual(RowNumbers(None, None), numbers)


class ThresholdTests(unittest.TestCase):
    def test_the_threshold_sits_between_the_correct_and_wrong_scores(self):
        """阈值 0.70 是**量出来的**：正确匹配的最低分在它上面、错配的最高分在它下面。

        真帧上按标注把字形取出来，对每个字模打分：属于它自己的算「正确」，
        其余算「错配」。改了字模或改了归一化，这条会先红 —— 而不是等到实跑误跳过。
        """
        glyphs = real_glyphs()

        from auto_game_unified.games.epic7.knights_support_digits import _patches

        correct: list[tuple[str, float]] = []
        wrong: list[tuple[str, float]] = []
        for name, center, holdings, required, _ in REAL_ROWS:
            frame = screen(name)
            holdings_patch, required_patch = _patches(frame, center)
            for mask, digits in (
                (green_mask(holdings_patch), str(holdings)),
                (white_mask(required_patch), str(required)),
            ):
                # strict=True：框数与位数对不上时必须当场炸，不能让 zip 静默截断
                # 导致「少验了一位」还报绿（这正是本用例要防的）。
                for box, digit in zip(glyph_boxes(mask), digits, strict=True):
                    glyph = normalize_glyph(mask, box)
                    for candidate, template in glyphs.items():
                        score = glyph_score(glyph, template)
                        bucket = correct if str(candidate) == digit else wrong
                        bucket.append((f"{name}@{center[1]} 的 {digit}", score))

        lowest_correct = min(correct, key=lambda item: item[1])
        highest_wrong = max(wrong, key=lambda item: item[1])
        self.assertGreater(
            lowest_correct[1],
            GLYPH_MATCH_MIN_SCORE,
            f"正确匹配的最低分（{lowest_correct}）掉到阈值以下了",
        )
        self.assertLess(
            highest_wrong[1],
            GLYPH_MATCH_MIN_SCORE,
            f"错配的最高分（{highest_wrong}）涨到阈值以上了",
        )


class RowNumbersTests(unittest.TestCase):
    def test_verdict_is_unknown_unless_both_sides_are_read(self):
        self.assertIsNone(RowNumbers(None, 1).verdict)
        self.assertIsNone(RowNumbers(1, None).verdict)
        self.assertIsNone(RowNumbers(None, None).verdict)

    def test_verdict_compares_holdings_with_required(self):
        self.assertIs(True, RowNumbers(1, 2).verdict)
        self.assertIs(False, RowNumbers(2, 2).verdict)
        self.assertIs(False, RowNumbers(3, 2).verdict)

    def test_describe_shows_a_question_mark_for_the_unknown_side(self):
        self.assertEqual("持有 1 / 需求 2", RowNumbers(1, 2).describe())
        self.assertEqual("持有 1 / 需求 ?", RowNumbers(1, None).describe())
        self.assertEqual("持有 ? / 需求 ?", RowNumbers(None, None).describe())


if __name__ == "__main__":
    unittest.main()
