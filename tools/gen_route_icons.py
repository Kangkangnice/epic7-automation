"""生成路线图标（白色单色、矢量渲染、统一视觉重量）。

## 为什么不用游戏原图

2026-10-22 试过：从 `lobby.png` 里切大厅入口图标再转白线稿 —— **做不出来**。
游戏里的图标是彩色 + 发光（金色徽章、光晕），抠图时背景会被当成图案的一部分，
转成白线稿就碎成一堆点（对比图见当时的 `_icons_preview/batch.png`）。
真正可行的是「用游戏里本身就是白色线条的图标」，那需要战斗菜单那一页的截图。

在此之前，用系统符号字体渲染一套**风格统一**的白色图标：矢量、抗锯齿、粗细一致。
它们只是占位，将来换成游戏原图时**位置和尺寸都不用改**。

## 用法

    python tools/gen_route_icons.py            # 生成到 desktop/icons/
    python tools/gen_route_icons.py --size 56  # 换尺寸（默认 56，200% 缩放下显示为 28 逻辑像素）
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "desktop" / "icons"
FONT = Path("C:/Windows/Fonts/seguisym.ttf")

# 路线 → 符号。选的是「一眼能猜到干什么」的形状，不是随便配的：
# 剑=对抗、旗=推进、锚=远航、塔=爬层、菱形=材料、星=剧情、月=剧场，
# 盾=守护（收菜）、花=骑士团、鸟居=迷宫入口、圆环=社区。
SYMBOLS: dict[str, str] = {
    "arena": "⚔",
    "story": "⚑",
    "side_story": "✦",
    "expedition": "⚓",
    "tower": "♜",
    "fodder": "◆",
    "moonlight_theater": "☾",
    "hero_synthesis": "✚",
    "shop_refresh": "▣",
    "survivor": "◉",
    "world_boss": "☠",
    "knights_donation": "⚜",
    "labyrinth_stone": "⛩",
    "sanctuary": "⛨",
    "community": "◎",
}


def render(char: str, size: int) -> Image.Image:
    """一个符号 → 正方形透明底白色图标。

    先在 8 倍画布上画再缩回：直接在小尺寸上画，笔画边缘会有锯齿（用户明确说过
    「描边要细致，不要毛躁」）。8 倍是笔画的抗锯齿余量，再大没必要。
    """
    scale = 8
    big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    font = ImageFont.truetype(str(FONT), int(size * scale * 0.82))
    draw = ImageDraw.Draw(big)
    draw.text(
        (size * scale // 2, size * scale // 2),
        char,
        font=font,
        fill=(255, 255, 255, 255),
        anchor="mm",
    )
    return big.resize((size, size), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成路线符号图标")
    parser.add_argument("--size", type=int, default=56)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    for mode, char in SYMBOLS.items():
        icon = render(char, args.size)
        icon.save(target / f"{mode}.png")
    print(f"已生成 {len(SYMBOLS)} 个图标到 {target}（{args.size}×{args.size}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
