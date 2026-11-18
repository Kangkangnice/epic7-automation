"""装备制作判据模板的跨页分离度矩阵（一次性探针）。

对每张模板，在**它的生产 ROI** 里打所有夹具，打印命中它的页面。
用途：定阈值、看有没有跨页串味。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from auto_game_unified.core.matcher import find_template, load_template  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "epic7_craft_equipment"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "craft_equipment"

REGIONS: dict[str, tuple[int, int, int, int]] = {
    "home_hint": (600, 980, 400, 90),
    "craft_button": (1620, 1000, 330, 120),
    "qty_10_selected": (1790, 750, 110, 90),
    "qty_1_selected": (1720, 750, 110, 90),
    "confirm_hint": (650, 410, 700, 80),
    "confirm_craft_button": (1130, 800, 190, 100),
    "result_title": (820, 170, 280, 100),
    "again_button_plain": (1140, 990, 220, 90),
    "tidy_button": (1500, 860, 300, 100),
    "quick_select_button": (100, 1000, 250, 100),
    "sell_button": (520, 1000, 180, 90),
    "extract_button": (840, 1000, 180, 90),
    "again_button_tidy": (1590, 1000, 220, 90),
    "sell_confirm_hint": (740, 410, 320, 80),
    "popup_confirm_button": (1030, 800, 180, 90),
    "slot_weapon": (690, 310, 150, 150),
    "slot_helmet": (450, 440, 150, 150),
    "slot_armor": (450, 690, 150, 150),
    "slot_necklace": (910, 440, 150, 150),
    "slot_ring": (910, 690, 150, 150),
    "slot_boots": (680, 830, 150, 150),
}


def main() -> None:
    frames = {path.stem: cv2.imread(str(path)) for path in FIXTURES.glob("*.png")}
    for name, region in REGIONS.items():
        template = load_template(str(TEMPLATES / f"{name}.png"))
        scores = []
        for key, frame in frames.items():
            match = find_template(
                frame, template, 0.0, region=region, reference_size=(1982, 1132)
            )
            if match is not None:
                scores.append((match.score, key))
        scores.sort(reverse=True)
        top = "  ".join(f"{key}={score:.4f}" for score, key in scores[:3])
        print(f"{name:24s} {top}")


if __name__ == "__main__":
    main()
