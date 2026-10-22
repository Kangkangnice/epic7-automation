"""把游戏截图里的一块，切成统一风格的图标（透明底 + 白色线稿或剪影）。

## 为什么需要它

界面要的图标必须是**从游戏里截的真实图标**。竞品那套（齿轮 / 脚印 / 龙 / 骷髅）
在它自己的 APK 里一张都找不到 —— 2026-10-22 把 20 个界面定义、743 张资源包图片、
APK 的 361 张图全查过，都没有。所以只能自己从游戏画面取。

取完必须**统一成同一种风格**：游戏图标是彩色的、底色各异，直接摆上去会比不放更乱。
这里统一成白线稿（或白剪影）+ 透明底，和暗色界面同一套语言。

## 用法

    python tools/icon_forge.py --image shot.png --name arena --box 120,340,72,72
    python tools/icon_forge.py --image shot.png --name arena --box 120,340,72,72 --style solid

`--box` 是截图里的像素框（x,y,w,h）。`--style outline` 出白色线条（默认），
`--style solid` 出白色实心剪影（细节太碎、线稿糊成一团时用它）。

输出到 `auto_game_unified/desktop/icons/<name>.png`，28×28 RGBA。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "desktop" / "icons"


def _foreground_mask(rgb: np.ndarray) -> np.ndarray:
    """把「图标像素」从背景里分出来。

    背景色取**四角的中位数** —— 游戏图标几乎都贴在纯色或渐变的深底上，
    四角基本就是底色。比固定阈值稳，换一张截图不用重调。
    """
    height, width = rgb.shape[:2]
    strip = max(2, min(6, height // 12, width // 12))
    corners = np.concatenate(
        [
            rgb[:strip, :strip].reshape(-1, 3),
            rgb[:strip, -strip:].reshape(-1, 3),
            rgb[-strip:, :strip].reshape(-1, 3),
            rgb[-strip:, -strip:].reshape(-1, 3),
        ]
    )
    background = np.median(corners, axis=0)
    distance = np.abs(rgb.astype(np.int16) - background).sum(axis=2)
    return distance > 60


def _clean(mask: Image.Image) -> Image.Image:
    """去掉零星噪点、补上小洞 —— 游戏截图有抗锯齿和压缩噪点。"""
    mask = mask.filter(ImageFilter.MedianFilter(3))
    return mask.filter(ImageFilter.MedianFilter(3))


def build(crop: Image.Image, *, style: str, size: int, supersample: int = 4) -> Image.Image:
    """切成统一风格的图标。

    ⚠️ **必须在放大图上做形态学，最后才缩回 28**（``supersample``，默认 4×）。
    直接在小图上腐蚀/膨胀，边缘只有 1 像素可操作，缩回后一定是毛刺状 ——
    这就是「粗糙感」的来源。放大 4 倍再缩回，等于自带抗锯齿。
    """
    work = crop.convert("RGB")
    if supersample > 1:
        work = work.resize(
            (work.width * supersample, work.height * supersample), Image.LANCZOS
        )

    mask = Image.fromarray((_foreground_mask(np.asarray(work)) * 255).astype(np.uint8))
    mask = _clean(mask)

    if style == "solid":
        shape = mask
    else:
        # 线稿 = 原形状减掉「腐蚀一圈」的形状；再膨胀一圈把线加粗。
        # 在 4× 图上这一来一回 ≈ 缩回后 1 像素线宽，正好是「细致」而不是「糊」。
        eroded = mask.filter(ImageFilter.MinFilter(3))
        edge = np.clip(
            np.asarray(mask).astype(np.int16) - np.asarray(eroded).astype(np.int16),
            0,
            255,
        )
        shape = Image.fromarray(edge.astype(np.uint8)).filter(ImageFilter.MaxFilter(3))

    box = shape.getbbox()
    if box is None:
        raise ValueError("这个框里没有可识别的前景（整块都是背景色）")
    shape = shape.crop(box)

    # 塞进正方形再缩放，避免不同图标宽高比不同导致大小不一。
    side = max(shape.size)
    canvas = Image.new("L", (side, side), 0)
    canvas.paste(shape, ((side - shape.width) // 2, (side - shape.height) // 2))
    canvas = canvas.resize((size, size), Image.LANCZOS)

    icon = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    icon.paste(white, (0, 0), canvas)
    return icon


def main() -> int:
    parser = argparse.ArgumentParser(description="游戏截图 → 统一风格图标")
    parser.add_argument("--image", required=True, help="游戏截图路径")
    parser.add_argument("--name", required=True, help="图标名（输出文件名）")
    parser.add_argument("--box", required=True, help="x,y,w,h")
    parser.add_argument("--style", choices=("outline", "solid"), default="outline")
    parser.add_argument("--size", type=int, default=28)
    # 放大几倍做形态学。4 已经够细；调到 1 会明显毛躁（对比用）。
    parser.add_argument("--supersample", type=int, default=4)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    x, y, w, h = (int(part) for part in args.box.split(","))
    with Image.open(args.image) as shot:
        crop = shot.convert("RGB").crop((x, y, x + w, y + h))
    icon = build(
        crop,
        style=args.style,
        size=args.size,
        supersample=max(1, args.supersample),
    )

    target = Path(args.out) / f"{args.name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    icon.save(target)
    print(f"已生成 {target}（{icon.size[0]}×{icon.size[1]}，{args.style}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
