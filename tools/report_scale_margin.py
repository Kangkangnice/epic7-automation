"""量每条已放行路线的每颗锚点「对 UI 尺寸漂移有多脆」。

用法：
    python -m auto_game_unified.tools.report_scale_margin [backend]

背景（2026-11-04 彻夜实跑踩到）：同一个 PC 客户端**两次启动之间**会把自己那套 UI
画得不一样大（``战斗开始`` 476x69 → 461x67，×0.9685），而 ``TM_CCOEFF_NORMED``
只归一化亮度、**不归一化尺度** —— 2% 的偏差足以把 1.0000 打到 0.6448。

本工具对每颗锚点，在「它自己那条路线里最能代表它」的一帧上，扫一遍模板尺寸，
量出「阈值以上有多宽」这个平台宽度：

* 平台半宽 ≥ 0.03 ⇒ 稳（±3% 漂移都还能认出来）
* 平台半宽 < 0.02 ⇒ 脆（本次实测的 `card_hint` 就是这一类）

脆的锚点才需要考虑加进 ``core.matcher.SCALE_FALLBACK_ANCHORS``。加之前必须跑
``python -m auto_game_unified.tools.audit_scale_fallback`` 证明不放冒牌。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

from auto_game_unified.core.matcher import find_best_template
from auto_game_unified.games.epic7.evidence import (
    hero_synthesis,
    labyrinth_stone,
    moonlight_theater,
    sanctuary,
    shop_refresh,
    story,
    tower,
    world_boss,
)
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7.template_paths import resolve_template_dir

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures"

SCALES = tuple(round(0.94 + 0.01 * i, 2) for i in range(13))

# 路线 -> (证据构造器, 夹具目录名)
ROUTES = {
    "tower": (tower.build_tower_evidence, "epic7_tower"),
    "arena": (build_arena_evidence, "epic7_arena"),
    "story": (story.build_story_evidence, "epic7_story"),
    "sanctuary": (sanctuary.build_sanctuary_evidence, "epic7_sanctuary"),
    "labyrinth_stone": (labyrinth_stone.build_labyrinth_stone_evidence, "epic7_labyrinth_stone"),
    "moonlight_theater": (moonlight_theater.build_moonlight_evidence, "epic7_moonlight_theater"),
    "shop_refresh": (shop_refresh.build_shop_refresh_evidence, "epic7_shop_refresh"),
    "world_boss": (world_boss.build_world_boss_evidence, "epic7_world_boss"),
    "hero_synthesis": (hero_synthesis.build_hero_evidence, "epic7_hero_synthesis"),
}


def load_rgb(path: Path):
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def fits_reference(screen, reference_size) -> bool:
    """宽高比与基准对不上的帧直接跳过 —— ``find_best_template`` 对它们会抛错，
    而实跑里这种帧到不了判据这一步（抓帧层就先拒了）。"""
    if reference_size is None:
        return True
    return (
        abs(screen.shape[1] / reference_size[0] - screen.shape[0] / reference_size[1])
        <= 0.02
    )


def plateau(atom, template, screen) -> tuple[float, float]:
    """返回 (最高分, 阈值以上的最大连续半宽)。"""
    scores = []
    for scale in SCALES:
        match = find_best_template(
            screen,
            template,
            region=atom.region,
            reference_size=atom.reference_size,
            mode=atom.match_mode,
            template_scale=scale,
        )
        scores.append((scale, match.score if match is not None else -1.0))
    best_scale, best = max(scores, key=lambda kv: kv[1])
    # 以最佳档为中心往两边走，只要还过阈就继续。
    half_width = 0.0
    step = 0.01
    left = best_scale
    while left - step >= SCALES[0] and dict(scores)[round(left - step, 2)] >= atom.threshold:
        left = round(left - step, 2)
        half_width = max(half_width, best_scale - left)
    right = best_scale
    while right + step <= SCALES[-1] and dict(scores)[round(right + step, 2)] >= atom.threshold:
        right = round(right + step, 2)
        half_width = max(half_width, right - best_scale)
    return best, half_width


def main(argv: list[str]) -> int:
    backend = argv[1] if len(argv) > 1 else "pc"
    root = resolve_template_dir(TEMPLATES, backend)
    fragile: list[tuple[str, str, float, float, float]] = []

    for route, (builder, fixture_dir) in ROUTES.items():
        route_dir = root / route
        try:
            profile = builder(route_dir)
        except Exception as error:  # 某条路线的画像构造器签名可能不同
            print(f"[跳过] {route}: 画象构造失败 {error}")
            continue
        frames = sorted((FIXTURES / fixture_dir).glob("*.png"))
        if not frames:
            print(f"[跳过] {route}: 没有夹具")
            continue
        print(f"\n=== {route}（{len(frames)} 帧夹具）===")
        for name, atom in sorted(profile.atoms.items()):
            template_path = route_dir / atom.template_path
            if not template_path.is_file():
                continue
            template = load_rgb(template_path)
            if template is None:
                continue
            # 挑「最能代表它」的一帧：最高分那一帧。
            best_frame = None
            best_score = -1.0
            for frame in frames:
                screen = load_rgb(frame)
                if screen is None or not fits_reference(screen, atom.reference_size):
                    continue
                match = find_best_template(
                    screen,
                    template,
                    region=atom.region,
                    reference_size=atom.reference_size,
                    mode=atom.match_mode,
                )
                if match is not None and match.score > best_score:
                    best_score = match.score
                    best_frame = screen
            if best_frame is None or best_score < atom.threshold:
                continue
            top, half = plateau(atom, template, best_frame)
            flag = "脆" if half < 0.02 else ("偏脆" if half < 0.03 else "稳")
            print(
                f"  {flag:3s} {name:26s} 阈{atom.threshold:.2f} 最高{top:.4f} "
                f"平台半宽±{half:.2f}"
            )
            if half < 0.02:
                fragile.append((route, name, atom.threshold, top, half))

    print("\n=== 平台半宽 < 0.02（±2% 漂移就可能认不出）===")
    for route, name, threshold, top, half in fragile:
        print(f"  {route:20s} {name:26s} 阈{threshold:.2f} 最高{top:.4f} ±{half:.2f}")
    if not fragile:
        print("  无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
