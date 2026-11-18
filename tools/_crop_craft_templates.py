"""装备制作路线的判据模板裁剪（坐标已按投影测量，不是目测缩略图）。

只裁「文字/按钮/图标本体」，不裁会变的内容（金币金额、成品名、件数、装备网格）。
跑完打印每张在来源帧上的最佳分数，作为「框有没有裁歪」的最低自检。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from auto_game_unified.core.matcher import best_match  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "epic7_craft_equipment"
OUT = ROOT / "games" / "epic7" / "templates" / "craft_equipment"

# name -> (fixture, x, y, w, h)
BOXES: dict[str, tuple[str, int, int, int, int]] = {
    "home_hint": ("home", 637, 1016, 249, 32),
    "result_title": ("result", 862, 193, 194, 53),
    "confirm_hint": ("confirm", 702, 435, 264, 35),
    "sell_confirm_hint": ("sell_confirm", 783, 433, 215, 36),
    "craft_button": ("qty_10", 1704, 1023, 90, 64),
    "confirm_craft_button": ("confirm", 1175, 818, 95, 60),
    "again_button_plain": ("result", 1170, 1007, 149, 49),
    "again_button_tidy": ("tidy", 1627, 1021, 144, 47),
    "popup_confirm_button": ("sell_confirm", 1072, 820, 96, 47),
    "qty_10_selected": ("qty_10", 1820, 769, 72, 56),
    "qty_1_selected": ("qty_1", 1743, 769, 75, 56),
    "quick_select_button": ("tidy", 138, 1026, 124, 58),
    "sell_button": ("quick_selected", 557, 1022, 95, 47),
    "extract_button": ("quick_selected", 877, 1023, 96, 47),
    "tidy_button": ("result", 1547, 880, 210, 57),
    "extract_confirm_hint": ("extract_confirm", 765, 433, 392, 35),
    "extract_confirm_button": ("extract_confirm", 1072, 820, 96, 47),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    runtime_logs = ROOT / "runtime_logs"
    if not (FIXTURES / "qty_10.png").exists():
        shutil.copyfile(runtime_logs / "_qty_10.png", FIXTURES / "qty_10.png")
    stale = FIXTURES / "slot_weapon_10.png"
    if stale.exists():
        stale.unlink()

    for name, (fixture, x, y, w, h) in BOXES.items():
        frame = cv2.imread(str(FIXTURES / f"{fixture}.png"))
        if frame is None:
            raise SystemExit(f"夹具读不到：{fixture}")
        crop = frame[y : y + h, x : x + w]
        cv2.imwrite(str(OUT / f"{name}.png"), crop)
        score, _ = best_match(frame, crop)
        print(f"{name:24s} {w:3d}x{h:3d} @({x},{y}) 本帧={score:.4f}")


if __name__ == "__main__":
    main()
