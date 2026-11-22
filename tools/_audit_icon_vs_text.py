"""只读审计：列出全部路线证据画像的锚点、模板尺寸与比对口径。

用途：判断哪些锚点**只用了图标**、而同一控件上其实还有文字可用。
本脚本不改任何东西，只打印一张表（可选 `--csv` 落盘）。

用法（仓库根 `D:\\AI\\codex\\auto_game`）：
    python -m auto_game_unified.tools._audit_icon_vs_text
    python -m auto_game_unified.tools._audit_icon_vs_text --csv runtime_logs/anchors.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from auto_game_unified.games.epic7.evidence.achievement import (
    build_achievement_evidence,
)
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.craft_equipment import (
    build_craft_equipment_evidence,
)
from auto_game_unified.games.epic7.evidence.expedition import (
    build_expedition_evidence,
)
from auto_game_unified.games.epic7.evidence.hero_synthesis import (
    build_hero_evidence,
)
from auto_game_unified.games.epic7.evidence.knights_donation import (
    build_knights_donation_evidence,
)
from auto_game_unified.games.epic7.evidence.labyrinth_stone import (
    build_labyrinth_stone_evidence,
)
from auto_game_unified.games.epic7.evidence.moonlight_theater import (
    build_moonlight_evidence,
)
from auto_game_unified.games.epic7.evidence.penguin_purchase import (
    build_penguin_purchase_evidence,
)
from auto_game_unified.games.epic7.evidence.pet_adoption import (
    build_pet_adoption_evidence,
)
from auto_game_unified.games.epic7.evidence.sanctuary import (
    build_sanctuary_evidence,
)
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    build_shop_refresh_evidence,
)
from auto_game_unified.games.epic7.evidence.story import build_story_evidence
from auto_game_unified.games.epic7.evidence.story_star import (
    build_story_star_evidence,
)
from auto_game_unified.games.epic7.evidence.survivor import build_survivor_evidence
from auto_game_unified.games.epic7.evidence.tower import build_tower_evidence
from auto_game_unified.games.epic7.evidence.world_boss import (
    build_world_boss_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"

# 路线名 -> (构建函数, 模板根候选)；候选按顺序试，取「缺图」最少的那个
BUILDERS = {
    "achievement": (build_achievement_evidence, ("achievement",)),
    "arena": (build_arena_evidence, ("",)),
    "craft_equipment": (build_craft_equipment_evidence, ("craft_equipment",)),
    "expedition": (build_expedition_evidence, ("expedition",)),
    "hero_synthesis": (build_hero_evidence, ("", "hero")),
    "knights_donation": (build_knights_donation_evidence, ("knights_donation",)),
    "labyrinth_stone": (build_labyrinth_stone_evidence, ("labyrinth_stone",)),
    "moonlight_theater": (build_moonlight_evidence, ("moonlight_theater",)),
    "penguin_purchase": (build_penguin_purchase_evidence, ("penguin_purchase",)),
    "pet_adoption": (build_pet_adoption_evidence, ("pet_adoption",)),
    "sanctuary": (build_sanctuary_evidence, ("sanctuary",)),
    "shop_refresh": (build_shop_refresh_evidence, ("",)),
    "story": (build_story_evidence, ("story",)),
    "story_star": (build_story_star_evidence, ("story_star", "story_star/pc")),
    "survivor": (build_survivor_evidence, ("", "survivor")),
    "tower": (build_tower_evidence, ("tower",)),
    "world_boss": (build_world_boss_evidence, ("world_boss",)),
}


def _white_ratio(image: np.ndarray) -> float:
    """三通道都 >= 200 的像素占比（与 matcher.white_mask 同口径）。"""
    mask = np.all(image >= 200, axis=2)
    return float(mask.mean()) if mask.size else 0.0


def _missing(profile, root: Path) -> list[str]:
    """只看「模板不存在」这一类；「引用不存在」是 PC-only 原子的正常现象。"""
    return [e for e in validate_profile(profile, root) if "模板不存在" in e]


def _classify(width: int, height: int) -> str:
    """粗筛：单行文字 / 疑似图标 / 大块混合。"""
    aspect = width / max(height, 1)
    if height <= 48 and aspect >= 1.6:
        return "文字单行?"
    if aspect <= 1.3 and height >= 45:
        return "图标?"
    return "混合?"


def _resolve(builder, roots: tuple[str, ...]):
    best = None
    for suffix in roots:
        root = TEMPLATES / suffix if suffix else TEMPLATES
        profile = builder(root)
        missing = _missing(profile, root)
        if best is None or len(missing) < best[2]:
            best = (root, profile, len(missing))
        if not missing:
            break
    return best[0], best[1], best[2]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    csv_path = None
    if argv and "--csv" in argv:
        csv_path = Path(argv[argv.index("--csv") + 1])

    rows = []
    for route, (builder, roots) in BUILDERS.items():
        root, profile, missing = _resolve(builder, roots)
        if missing:
            print(f"[警告] {route}: 仍有 {missing} 张模板找不到（根={root.name or 'templates'}）")
        for key, atom in profile.atoms.items():
            path = root / atom.template_path
            x, y, w, h = atom.region
            if not path.is_file():
                rows.append([route, key, str(atom.template_path), 0, 0, 0.0, atom.threshold, atom.match_mode, "缺图", x, y, w, h])
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            th, tw = rgb.shape[:2]
            rows.append([route, key, str(atom.template_path), tw, th, round(_white_ratio(rgb), 3), atom.threshold, atom.match_mode, _classify(tw, th), x, y, w, h])

    head = ["路线", "锚点", "模板", "宽", "高", "白占比", "阈值", "口径", "形态", "区域x", "区域y", "区域w", "区域h"]
    print("，".join(head[:9]))
    for row in rows:
        print(f"{row[0]:<18}{row[1]:<30}{row[2]:<42}{row[3]:>5}{row[4]:>5}{row[5]:>7}{row[6]:>7}  {row[7]:<10}{row[8]}")
    print(f"\n合计 {len(rows)} 个锚点 / {len(BUILDERS)} 条路线")

    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(head)
            writer.writerows(rows)
        print(f"已写 {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
