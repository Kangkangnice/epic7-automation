"""装备制作判据的**跨路线**排他扫描（一次性探针）。

在每条**别的路线**的夹具上，按生产 ROI 打每一张模板，打印最高分。
阈值 0.90：任何一条别的路线拿到 ≥0.90 都说明这个判据会把那条路线认成装备制作。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from auto_game_unified.core.matcher import find_template, load_template  # noqa: E402
from auto_game_unified.games.epic7.evidence.craft_equipment import (  # noqa: E402
    REGIONS,
    THRESHOLDS,
)

FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "craft_equipment"


def main() -> None:
    own = FIXTURES / "epic7_craft_equipment"
    frames = [
        path
        for path in FIXTURES.rglob("*.png")
        if own not in path.parents and path.stem not in {"home", "result", "tidy"}
    ]
    print(f"跨路线夹具 {len(frames)} 张")
    worst: list[tuple[float, str, str]] = []
    for name, region in REGIONS.items():
        template = load_template(str(TEMPLATES / f"{name}.png"))
        best = (0.0, "", "")
        for path in frames:
            image = cv2.imread(str(path))
            if image is None:
                continue
            # 竖屏夹具（社区那批）走的是另一条链路，横屏判据够不到它。
            if abs(image.shape[1] / image.shape[0] - 1982 / 1132) > 0.02:
                continue
            match = find_template(
                image, template, 0.0, region=region, reference_size=(1982, 1132)
            )
            if match is not None and match.score > best[0]:
                best = (match.score, str(path.relative_to(FIXTURES)), "")
        worst.append((best[0], name, best[1]))
        flag = "⚠️" if best[0] >= THRESHOLDS[name] else "  "
        print(f"{flag} {name:24s} 最高={best[0]:.4f} 阈={THRESHOLDS[name]:.2f}  {best[1]}")

    worst.sort(reverse=True)
    print("\n最接近阈值的三条：")
    for score, name, where in worst[:3]:
        print(f"  {name:24s} {score:.4f}  {where}")


if __name__ == "__main__":
    main()
