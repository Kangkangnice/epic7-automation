"""全库扫描：证明 `SCALE_FALLBACK_ANCHORS` 里的每颗锚点「不漏真页、不放冒牌」。

用法：
    python -m auto_game_unified.tools.audit_scale_fallback [backend]

为什么需要这个工具：``SCALE_FALLBACK_STEPS`` 是**多试几个假设取最高分**，
它一定会把某些画面的分数往上抬一点。抬上去的是不是「同一页的另一档尺寸」，
还是「外观相似的别的页」，光看分数看不出来 —— 必须逐帧人工归类。
本工具把「被抬过阈」的帧全部列出来，供人对着图判一遍，并把结论写死进
护栏测试（``tests/test_navigation.py`` / ``tests/test_tower_evidence.py``）。

判据口径与 ``locate_with_fallback`` **完全一致**（同一个 ``find_best_template``、
同一套阈值/区域/口径），否则审计结论对实跑无意义。

「漏掉真页」在结构上必然是 0：扫尺寸取的是 ``max(原样, 各档)``，只会升不会降，
且原样过阈时直接提前返回。所以本工具只可能报出「放进冒牌」。
"""

from __future__ import annotations

from dataclasses import dataclass

import sys
from pathlib import Path

import cv2

from auto_game_unified.core.matcher import (
    SCALE_FALLBACK_ANCHORS,
    SCALE_FALLBACK_STEPS,
    find_best_template,
)
from auto_game_unified.games.epic7.evidence import (
    labyrinth_stone,
    moonlight_theater,
    story,
    tower,
    world_boss,
)
from auto_game_unified.games.epic7.evidence.arena import build_arena_evidence
from auto_game_unified.games.epic7.template_paths import resolve_template_dir

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures"

# 锚点 -> 证据构造器所在路线（名单里每个名字都必须在这里能查到）
BUILDERS = {
    "tower": tower.build_tower_evidence,
    "arena": build_arena_evidence,
    "story": story.build_story_evidence,
    "labyrinth_stone": labyrinth_stone.build_labyrinth_stone_evidence,
    "moonlight_theater": moonlight_theater.build_moonlight_evidence,
    "world_boss": world_boss.build_world_boss_evidence,
}
# 同名锚点在多条路线里出现时（`auto_off`），按这个顺序取第一条命中的定义。
ORDER = ("tower", "arena", "story", "labyrinth_stone", "moonlight_theater", "world_boss")
# 导航层的锚点不在任何路线证据画像里，单独登记：(区域, 阈值) 与
# ``Epic7Navigator._REGIONS`` / ``observe`` 里写死的那两处**逐字一致**。
NAVIGATION_ANCHORS = {
    "lobby_story": ((1450, 220, 480, 200), 0.80),
}


def load_rgb(path: Path):
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def fixture_frames() -> list[Path]:
    """全库夹具。宽高比对不上的帧剔掉（``find_best_template`` 会直接抛错，
    而实跑里这种帧到不了判据这一步）。"""
    kept: list[Path] = []
    for path in sorted(p for p in FIXTURES.rglob("*.png") if p.is_file()):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]
        if abs(width / height - 1982 / 1132) > 0.02:
            continue
        kept.append(path)
    return kept


def resolve_atom(profile, route_dir: Path, name: str, root: Path):
    """找到锚点的（模板文件, 原子）。路径可能相对路线目录，也可能相对模板根。"""
    atom = profile.atoms[name]
    for base in (route_dir, root):
        candidate = base / atom.template_path
        if candidate.is_file():
            return candidate, atom
    return None, atom


@dataclass(frozen=True)
class _NavAnchor:
    """给导航层锚点用的最小「原子」替身（字段名与 ``AtomEvidence`` 对齐）。"""

    region: tuple[int, int, int, int]
    threshold: float
    match_mode: str = "raw"
    reference_size: tuple[int, int] = (1982, 1132)


def resolve_all(root: Path, profiles: dict) -> dict[str, tuple[str, Path, object]]:
    """名单里的每个名字 -> (来源标签, 模板文件, 原子)。查不到的不放进结果。"""
    resolved: dict[str, tuple[str, Path, object]] = {}
    for name in sorted(SCALE_FALLBACK_ANCHORS):
        nav = NAVIGATION_ANCHORS.get(name)
        if nav is not None:
            region, threshold = nav
            path = root / "navigation" / f"{name}.png"
            if path.is_file():
                resolved[name] = ("navigation", path, _NavAnchor(region, threshold))
                continue
        for route in ORDER:
            profile = profiles[route]
            if name not in profile.atoms:
                continue
            path, atom = resolve_atom(profile, root / route, name, root)
            if path is not None:
                resolved[name] = (route, path, atom)
                break
    return resolved


def main(argv: list[str]) -> int:
    backend = argv[1] if len(argv) > 1 else "pc"
    root = resolve_template_dir(TEMPLATES, backend)
    frames = fixture_frames()
    print(f"夹具 {len(frames)} 张，后端 {backend}，档位 {SCALE_FALLBACK_STEPS}\n")

    profiles = {route: builder(root / route) for route, builder in BUILDERS.items()}
    resolved = resolve_all(root, profiles)
    total_flips = 0
    unresolved = sorted(SCALE_FALLBACK_ANCHORS - set(resolved))

    for name, (route, template_path, atom) in resolved.items():
        template = load_rgb(template_path)
        if template is None:
            unresolved.append(name)
            continue
        raw_hits = 0
        flips: list[tuple[str, float, float, float]] = []
        for frame in frames:
            screen = load_rgb(frame)
            if screen is None:
                continue
            raw = find_best_template(
                screen,
                template,
                region=atom.region,
                reference_size=atom.reference_size,
                mode=atom.match_mode,
            )
            if raw is not None and raw.score >= atom.threshold:
                raw_hits += 1
                continue
            best_score = raw.score if raw is not None else -1.0
            best_scale = 1.0
            for scale in SCALE_FALLBACK_STEPS:
                cand = find_best_template(
                    screen,
                    template,
                    region=atom.region,
                    reference_size=atom.reference_size,
                    mode=atom.match_mode,
                    template_scale=scale,
                )
                if cand is not None and cand.score > best_score:
                    best_score = cand.score
                    best_scale = scale
            if best_score >= atom.threshold:
                flips.append(
                    (
                        frame.relative_to(FIXTURES).as_posix(),
                        best_score,
                        raw.score if raw is not None else -1.0,
                        best_scale,
                    )
                )
        print(f"=== {name}  ← {route}  阈 {atom.threshold:.2f}  口径 {atom.match_mode} ===")
        print(f"  原样口径就过阈的帧: {raw_hits}")
        print(f"  被扫尺寸抬过阈的帧: {len(flips)}")
        for rel, score, raw_score, scale in flips:
            print(f"    {rel}  原样 {raw_score:.4f} -> ×{scale:.2f} {score:.4f}")
        total_flips += len(flips)
        print()

    if unresolved:
        print(f"[警告] 解析不到模板的锚点（名单里写了但证据里没这张图？）: {unresolved}")
    print(f"合计被抬过阈 {total_flips} 帧 —— 逐帧归类后把结论写进护栏测试")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
