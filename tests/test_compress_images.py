"""tools/compress_images.py 的护栏：**只做无损**，收益不足不动文件。

守的是 2026-09-30 定的规矩：新素材入库前先无损压一遍（实测省 18%~26%），
但压缩**必须**逐位验证像素；而且存量不靠它瘦身（那要靠历史重写，见该工具 docstring）。

⚠️ 这里最容易悄悄退化的一条是「校验还在不在」：把 np.array_equal 删掉、只留
Pillow 重存，测试全绿而素材已经**有损**了（视觉上看不出来，模板匹配分数会慢慢漂）。
所以除了行为用例，另加一条源码级断言 + 一条「校验真的会拦」的用例。
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from auto_game_unified.tools import compress_images
from auto_game_unified.tools.compress_images import (
    LosslessCheckFailed,
    UnsupportedImage,
    compress_bytes,
    compress_file,
    decode_pixels,
    recompress_png,
)

COMPRESS_SOURCE = (
    Path(__file__).resolve().parents[1] / "tools" / "compress_images.py"
).read_text(encoding="utf-8")


def png_bytes(array: np.ndarray, level: int = 1) -> bytes:
    """把像素数组存成一张**未优化**的 PNG（模拟「刚截下来的图」）。"""
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG", compress_level=level)
    return buffer.getvalue()


def ui_like_rgb(width: int = 640, height: int = 400, seed: int = 3) -> np.ndarray:
    """一张「像游戏界面」的合成图：纯色底 + 横条 + 块状色斑。

    选它是因为**收益要真的过得了默认门槛**（>= 4096 字节且 >= 1%）：实测
    level1 13989 字节 -> level9 9407 字节，省 32.8% / 4582 字节。
    纯噪声图反而压不动（zlib 对不可压数据无能为力），会把用例变成空断言。
    """
    rng = np.random.default_rng(seed)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (26, 28, 40)
    for index in range(height // 30):
        y = 10 + index * 30
        image[y : y + 20, 24 : width - 24] = (58 + index * 5, 74, 96)
    block = 16
    small = rng.integers(
        0, 256, size=(height // block, width // block, 3), dtype=np.uint8
    )
    tint = np.kron(small, np.ones((block, block, 1), dtype=np.uint8))
    return ((image.astype(np.int32) + tint.astype(np.int32) // 6).clip(0, 255)).astype(
        np.uint8
    )


class RecompressTests(unittest.TestCase):
    def test_recompressed_png_keeps_pixels_bit_for_bit(self):
        original = png_bytes(ui_like_rgb())

        optimized = recompress_png(original)

        self.assertLess(len(optimized), len(original))
        self.assertTrue(np.array_equal(decode_pixels(original), decode_pixels(optimized)))

    def test_compress_bytes_accepts_a_true_lossless_round_trip(self):
        original = png_bytes(ui_like_rgb())

        self.assertTrue(
            np.array_equal(
                decode_pixels(original), decode_pixels(compress_bytes(original))
            )
        )

    def test_a_pixel_changing_result_is_rejected(self):
        # 把重压实现换成「转灰度」—— 像素必然变了，校验必须拦住它。
        original = png_bytes(ui_like_rgb())
        with Image.open(io.BytesIO(original)) as image:
            greyscale = io.BytesIO()
            image.convert("L").convert("RGB").save(greyscale, format="PNG")

        with mock.patch.object(
            compress_images, "recompress_png", return_value=greyscale.getvalue()
        ):
            with self.assertRaises(LosslessCheckFailed):
                compress_bytes(original)

    def test_unsupported_mode_is_reported_not_forced(self):
        palette = Image.fromarray(ui_like_rgb(64, 64)).convert("P")
        buffer = io.BytesIO()
        palette.save(buffer, format="PNG")

        with self.assertRaises(UnsupportedImage):
            recompress_png(buffer.getvalue())

    def test_the_lossless_check_is_actually_on_the_code_path(self):
        # 只断言「函数还在」不够：留着函数却把调用删掉，素材就已经悄悄有损了。
        self.assertIn("np.array_equal", COMPRESS_SOURCE)
        self.assertIn("if not np.array_equal", COMPRESS_SOURCE)
        self.assertIn("raise LosslessCheckFailed", COMPRESS_SOURCE)


class CompressFileTests(unittest.TestCase):
    def test_preview_does_not_touch_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shot.png"
            original = png_bytes(ui_like_rgb())
            path.write_bytes(original)

            result = compress_file(path)

            self.assertTrue(result.changed)
            self.assertEqual(original, path.read_bytes())

    def test_apply_rewrites_and_shrinks_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shot.png"
            original = png_bytes(ui_like_rgb())
            path.write_bytes(original)

            result = compress_file(path, apply=True)

            self.assertTrue(result.changed)
            self.assertLess(path.stat().st_size, len(original))
            self.assertTrue(
                np.array_equal(decode_pixels(original), decode_pixels(path.read_bytes()))
            )

    def test_a_tiny_gain_is_left_alone(self):
        # 8x8 纯色图本来就压到底了：收益不足 ⇒ 不许为了几十字节制造一次全仓 diff。
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flat.png"
            original = png_bytes(np.zeros((8, 8, 3), dtype=np.uint8))
            path.write_bytes(original)

            result = compress_file(path, apply=True)

            self.assertFalse(result.changed)
            self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
