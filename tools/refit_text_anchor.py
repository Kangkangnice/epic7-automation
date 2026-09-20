"""把文字类锚点重裁成「只有字形」的紧凑模板。

为什么需要它：`TM_CCOEFF_NORMED` 对模板里混进多少背景很敏感。如果锚点压在
**半透明面板**上（活动小游戏的「升级」标题就是），面板透出背后的局内画面，
背景一变相似度就掉。2026-09-16 的实测数据（同一块区域）：

    「升级」标题  109x65（外围留白） → 报错帧 0.8662
                   89x45（裁到字形） → 报错帧 0.9171，且负例最高分反而从 0.4567 降到 0.3310
    「重新抽取」  132x47            → 报错帧 0.9134
                  112x27            → 报错帧 0.9874，负例最高分 0.4567 → 0.1867

也就是说「裁掉背景」同时把正例拉高、负例压低，是一笔稳赚的改动。

用法：
    python -m auto_game_unified.tools.refit_text_anchor \
        --source-frame <用来裁图的帧.png> \
        --rect 905,89,109,65 \
        --output auto_game_unified/games/epic7/templates/survivor/level_up_title.png \
        [--invert] [--pad 0]

`--rect` 是现有的取样矩形（模板左上角 = 模板宽高的一半），`--invert` 表示字比底板深
（暗字亮底，例如绿色按钮上的文字）。裁完会打印 ASCII 亮度图确认字形取全了。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def load_rgb(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"读不出图: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def glyph_box(crop: np.ndarray, invert: bool, open_kernel: int = 2) -> tuple[int, int, int, int]:
    """Otsu 分出字形，返回其包围盒 (x, y, w, h)。"""

    grey = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert:
        mask = 255 - mask
    kernel = np.ones((open_kernel, open_kernel), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        raise SystemExit("Otsu 没分出字形，检查 --rect 是否取错位置")
    return (
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )


def ascii_map(image: np.ndarray, cols: int = 30, rows: int = 10) -> str:
    grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    height, width = grey.shape
    block_h = max(1, height // rows)
    block_w = max(1, width // cols)
    lines = []
    for r in range(rows):
        row = []
        for c in range(cols):
            block = grey[r * block_h : (r + 1) * block_h, c * block_w : (c + 1) * block_w]
            value = 0.0 if block.size == 0 else block.mean() / 255.0
            row.append(" .:-=+*#%@"[min(9, int(value * 10))])
        lines.append("".join(row))
    return "\n".join(lines)


def parse_rect(text: str) -> tuple[int, int, int, int]:
    parts = [int(value) for value in text.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise SystemExit("--rect 需要 x,y,width,height 四个整数")
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-frame", required=True)
    parser.add_argument("--rect", required=True, help="x,y,width,height（现有取样框）")
    parser.add_argument("--output", required=True)
    parser.add_argument("--invert", action="store_true", help="暗字亮底")
    parser.add_argument("--pad", type=int, default=0, help="字形外留几像素（默认 0）")
    args = parser.parse_args(argv)

    x, y, width, height = parse_rect(args.rect)
    frame = load_rgb(Path(args.source_frame))
    crop = frame[y : y + height, x : x + width]
    if crop.shape[0] != height or crop.shape[1] != width:
        raise SystemExit(f"取样框超出画面: {args.rect} 画面={frame.shape[1]}x{frame.shape[0]}")

    gx, gy, gw, gh = glyph_box(crop, args.invert)
    pad = max(0, args.pad)
    left = max(0, gx - pad)
    top = max(0, gy - pad)
    tight = crop[top : min(height, gy + gh + pad), left : min(width, gx + gw + pad)]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cv2.cvtColor(tight, cv2.COLOR_RGB2BGR))

    print(f"取样框 {width}x{height} @({x},{y})  →  紧凑模板 "
          f"{tight.shape[1]}x{tight.shape[0]} @({x + left},{y + top})")
    print(f"裁掉面积 {100 * (1 - (tight.shape[0] * tight.shape[1]) / (width * height)):.0f}%"
          f"  已写入 {output}")
    print("--- 紧凑模板 ASCII（确认字形取全） ---")
    print(ascii_map(tight))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
