"""在指定横带里切出每个控件（按列投影分段），用于精确定位模板框。

用法：把 (夹具, y0, y1, 阈值) 列出来，脚本打印每一段的 x 范围与真实 y 范围。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

FIXTURES = ROOT / "tests" / "fixtures" / "epic7_craft_equipment"

BANDS = [
    ("result", 1000, 1075, 150),
    ("tidy", 1010, 1095, 150),
    ("quick_selected", 1010, 1095, 150),
    ("confirm", 820, 880, 170),
    ("sell_confirm", 815, 875, 160),
    ("slot_weapon_10", 760, 830, 150),
    ("slot_weapon_10", 1030, 1075, 150),
    ("tidy", 870, 945, 150),
    ("quick_selected", 870, 945, 150),
]


def segments(image: np.ndarray, y0: int, y1: int, threshold: int) -> list[tuple[int, int]]:
    band = image[y0:y1]
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    cols = (gray > threshold).sum(axis=0)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for x, value in enumerate(cols):
        if value > 0 and start is None:
            start = x
        elif value == 0 and start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= 26:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return [run for run in merged if run[1] - run[0] >= 12]


def main() -> None:
    for fixture, y0, y1, threshold in BANDS:
        image = cv2.imread(str(FIXTURES / f"{fixture}.png"))
        gray = cv2.cvtColor(image[y0:y1], cv2.COLOR_BGR2GRAY)
        print(f"### {fixture} y={y0}..{y1} 阈={threshold}")
        for left, right in segments(image, y0, y1, threshold):
            column = gray[:, left : right + 1]
            rows = np.where((column > threshold).any(axis=1))[0]
            if len(rows) == 0:
                continue
            print(
                f"  x={left:4d}..{right:4d} w={right - left + 1:3d} "
                f"y={y0 + rows.min():4d}..{y0 + rows.max():4d} "
                f"h={rows.max() - rows.min() + 1:3d}"
            )


if __name__ == "__main__":
    main()
