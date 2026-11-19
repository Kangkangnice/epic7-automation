"""新增一名英雄：头像与分类一条命令落库。

用法（在 ``auto_game`` 工作区根目录，用项目的虚拟环境）：

    python -m auto_game_unified.tools.add_hero --zh 蕾诺娅 --en Renoa
    python -m auto_game_unified.tools.add_hero --zh 落月 --en Nahkwol --job 射手 --element 火 --stars 5

为什么要这条命令：``refresh_hero_meta`` 只能给**图鉴库里已有头像**的英雄归类，
新英雄上线时图鉴库还没有图，直接跑它只会报「外部库比上次多出 N 名」，然后什么也不做。
本工具把「取头像 → 校验尺寸 → 查重 → 写分类表」并成一条命令；
**中文名仍需人工确认**（官方公告 → 技能特征 → gamekee，顺序见
``docs/maintenance/hero_roster.md``）。

判据与红线：
- 头像只用官方图标：``epic7db.com`` 优先，未收录时用 ``epic7helper.com``
  （两站同源，同一名英雄中心相关实测 0.9962）。
- 查重按**中心区域相关**：同一个库内图重名会是 0.98 以上，同角色不同形态只有
  0.15~0.41（实测安洁莉卡 / 光之天使 / 罪戾的安洁莉卡 0.20~0.31）。
  阈 0.95 且领先第二名 0.05 视为「同一张图已在库里」，默认拒绝写入 ——
  那是别名或错位，不是新英雄。
- 中文名与英文名任一重复一律拒绝，除非 ``--force``。
- 头像文件已存在时同样拒绝覆盖，除非 ``--force``；旧图不会自动进 ``_obsolete/``，
  需要保留就先手动移过去。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.hero_catalog import (
    ELEMENTS,
    JOBS,
    STARS,
    meta_path,
)
from auto_game_unified.games.epic7.hero_match import default_library_dir
from auto_game_unified.tools.refresh_hero_meta import _imread, _open, fetch_catalog

HELPER_ICON = "https://epic7helper.com/img/heroes/{slug}_icon.png"
ICON_SIZE = 112

# 查重判据（2026-11-17 实测）：同一张图相关 0.98 以上，同角色不同形态 0.15~0.41。
DUPLICATE_CORR = 0.95
DUPLICATE_CORR_MARGIN = 0.05


def _slug_candidates(english: str) -> list[str]:
    """英文名到站内缩略图 slug 的候选写法。

    站内规则未公开，实测同一套：小写、空格换 ``-``、去掉撇号与句点，
    例如 ``Aubade Ludwig`` -> ``aubade-ludwig``。``&`` 三种写法都试
    （``and`` / 直接去掉 / 连字符），避免为一个连接符多跑一轮人工排查。
    """

    cleaned = re.sub(r"['’.]", "", english.strip().lower())
    variants = [cleaned.replace("&", " and "), cleaned.replace("&", " ")]
    candidates: list[str] = []
    for text in variants:
        base = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        if not base:
            continue
        candidates.extend([base, base.replace("-", "")])
    return list(dict.fromkeys(candidates))


def _to_icon(raw: bytes) -> np.ndarray:
    """把下载到的图转成与库内一致的 112x112 三通道图标。

    透明区压成黑色：库内 387 张官方图标都是这么来的（实测角点为纯黑），
    这里必须同一口径，否则新图在名单里的四角会与其余英雄不一样。
    """

    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("头像解码失败")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        image = (image[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    height, width = image.shape[:2]
    side = min(height, width)
    if side < 96:
        raise ValueError(f"头像尺寸过小（{width}x{height}），官方图标应为 112x112")
    top = (height - side) // 2
    left = (width - side) // 2
    square = image[top:top + side, left:left + side]
    return cv2.resize(square, (ICON_SIZE, ICON_SIZE), interpolation=cv2.INTER_AREA)


def _download_avatar(english: str, from_catalog: dict | None) -> tuple[bytes, str]:
    """取头像。返回 (字节, 来源说明)。

    先按 slug 直连两份图标地址（一两秒）；都 404 才由调用方去读外部英雄库，
    因为 ``epic7db.com/heroes`` 整页要一分钟左右，能不读就不读。
    """

    if from_catalog and from_catalog.get("avatar"):
        with _open(from_catalog["avatar"], timeout=30) as response:
            return response.read(), "epic7db"
    for slug in _slug_candidates(english):
        for url, label in (
            (f"https://epic7db.com/images/heroes/{slug}.webp", f"epic7db（{slug}）"),
            (HELPER_ICON.format(slug=slug), f"epic7helper（{slug}）"),
        ):
            try:
                with _open(url, timeout=15) as response:
                    return response.read(), label
            except Exception:  # noqa: BLE001 逐个候选试，全部失败才算错
                continue
    raise ValueError(f"两个来源都没有 {english} 的头像")


def _lookup_catalog(english: str) -> dict | None:
    """读外部英雄库找这一名；慢，只在缺分类或直连失败时调用。"""

    print("正在读取外部英雄库（整页约一分钟，仅缺分类或直连失败时需要）")
    try:
        for hero in fetch_catalog("https://epic7db.com/heroes"):
            if hero["name"].strip().lower() == english.lower():
                return hero
    except Exception as error:  # noqa: BLE001 离线时仍允许手动填分类
        print(f"外部英雄库读取失败：{error}")
    return None


def _center_signature(image: np.ndarray, size: int = 64) -> np.ndarray:
    """中心 50% 区域的灰度签名（去均值、单位化），用于查重打分。

    只取中心 50% 是沿用识别层的口径：图标四角是边框或透明压黑，整图相关会被它们拖低
    （同一张图整图相关 0.78、中心 1.0），同角色不同形态则始终在 0.05~0.40。
    """

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    side = int(min(height, width) * 0.5)
    top = (height - side) // 2
    left = (width - side) // 2
    patch = cv2.resize(
        gray[top:top + side, left:left + side], (size, size), interpolation=cv2.INTER_AREA
    ).astype(np.float32)
    patch -= patch.mean()
    return patch / (np.linalg.norm(patch) + 1e-6)


def _find_duplicate(icon: np.ndarray, library: Path) -> tuple[str, float, float] | None:
    """在库内找最像的一张，返回 (名字, 相关, 第二名相关)。"""

    probe = _center_signature(icon)
    scored: list[tuple[float, str]] = []
    for path in sorted(library.glob("*.png")):
        image = _imread(path)
        if image is None:
            continue
        scored.append((float((_center_signature(image) * probe).sum()), path.stem))
    if not scored:
        return None
    scored.sort(reverse=True)
    second = scored[1][0] if len(scored) > 1 else -1.0
    return scored[0][1], scored[0][0], second


def _validate(job: str, element: str, stars: int) -> None:
    if job not in JOBS:
        raise ValueError(f"职业必须是 {'/'.join(JOBS)} 之一")
    if element not in ELEMENTS:
        raise ValueError(f"属性必须是 {'/'.join(ELEMENTS)} 之一")
    if stars not in STARS:
        raise ValueError(f"星级必须是 {'/'.join(str(item) for item in STARS)} 之一")


def merge_entry(
    payload: dict,
    *,
    zh: str,
    en: str,
    job: str,
    element: str,
    stars: int,
    force: bool,
) -> tuple[dict, list[str]]:
    """把一条分类写进分类表（纯函数，不碰磁盘）。

    冲突一律抛 ``ValueError``，只有 ``force`` 才覆盖：
    中文名已指向别的英文名、英文名已挂在别的中文名下、同名条目取值不同。
    """

    heroes = payload.get("heroes")
    if not isinstance(heroes, dict):
        heroes = {}
    entry = {"en": en, "job": job, "element": element, "stars": stars}
    notes: list[str] = []

    for name, value in heroes.items():
        if name == zh or not isinstance(value, dict):
            continue
        if str(value.get("en", "")).strip().lower() == en.lower():
            if not force:
                raise ValueError(f"英文名 {en} 已挂在「{name}」名下；确认是同一人请加 --force")
            notes.append(f"英文名 {en} 原本挂在「{name}」，已按 --force 保留两处")

    existing = heroes.get(zh)
    if existing is not None:
        if existing == entry:
            notes.append("同名条目已存在且取值一致，未改动")
        elif not force:
            raise ValueError(f"「{zh}」已存在且取值不同：{existing}；确认要改请加 --force")
        else:
            notes.append(f"「{zh}」旧条目 {existing} 已被新值覆盖")

    merged = dict(heroes)
    merged[zh] = entry
    result = dict(payload)
    result["heroes"] = dict(sorted(merged.items()))
    result["count"] = len(result["heroes"])
    return result, notes


def _read_payload(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"分类表不存在：{path}；先跑 refresh_hero_meta --write 建表")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("heroes"), dict):
        raise ValueError(f"分类表结构异常：{path}；拒绝在缺 heroes 表的文件上写入")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="新增一名英雄：头像与分类一条命令落库")
    parser.add_argument("--zh", required=True, help="官方中文名（落盘文件名与分类表键）")
    parser.add_argument("--en", required=True, help="英文名（epic7db 用；也写进分类表）")
    parser.add_argument("--job", default="", help="职业；epic7db 未收录时必填")
    parser.add_argument("--element", default="", help="属性；epic7db 未收录时必填")
    parser.add_argument("--stars", type=int, default=0, help="初始星级；epic7db 未收录时必填")
    parser.add_argument(
        "--skip-avatar", action="store_true", help="只写分类表，不下载头像（头像已手动放好）"
    )
    parser.add_argument("--force", action="store_true", help="覆盖同名条目 / 已有头像文件")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 老控制台没有 reconfigure
        pass

    library = default_library_dir()
    if not library.is_dir():
        print(f"图鉴库不存在：{library}")
        return 1

    zh = args.zh.strip()
    en = args.en.strip()
    if not zh or not en:
        print("中文名与英文名都不能为空")
        return 1

    print(f"英文名：{en}")
    need_classification = not (args.job and args.element and args.stars)
    catalog_hero = _lookup_catalog(en) if need_classification else None
    if need_classification and catalog_hero is None:
        print("缺分类参数：加 --job / --element / --stars（取值见 docs/maintenance/hero_roster.md）")
        return 1

    job = args.job or (catalog_hero["job"] if catalog_hero else "")
    element = args.element or (catalog_hero["element"] if catalog_hero else "")
    stars = args.stars or (catalog_hero["stars"] if catalog_hero else 0)
    _validate(job, element, stars)

    # Validate the catalog before mutating its paired portrait.
    meta = meta_path()
    try:
        payload = _read_payload(meta)
        updated, notes = merge_entry(
            payload, zh=zh, en=en, job=job, element=element, stars=stars, force=args.force
        )
    except ValueError as error:
        print(f"分类表未写入：{error}")
        return 1

    target = library / f"{zh}.png"
    if args.skip_avatar:
        if not target.exists():
            print(f"--skip-avatar 已指定，但头像文件不存在：{target}")
            return 1
        print(f"头像沿用现有文件：{target}")
    else:
        if target.exists() and not args.force:
            print(f"头像已存在：{target}；确认要覆盖请加 --force（旧图先移入 _obsolete/）")
            return 1
        raw = b""
        origin = ""
        try:
            raw, origin = _download_avatar(en, catalog_hero)
        except ValueError:
            if catalog_hero is None:
                catalog_hero = _lookup_catalog(en)
            if catalog_hero and catalog_hero.get("avatar"):
                try:
                    raw, origin = _download_avatar(en, catalog_hero)
                except Exception as error:  # noqa: BLE001 下载失败按一条消息报
                    print(f"取头像失败：{error}")
                    return 1
        if not raw:
            print("取头像失败：两个来源都没有该英文名的图标；可手动放图后运行 --skip-avatar")
            return 1
        try:
            icon = _to_icon(raw)
        except ValueError as error:
            print(f"取头像失败：{error}")
            return 1
        print(f"头像来源：{origin}")
        duplicate = _find_duplicate(icon, library)
        if duplicate is not None:
            name, corr, second = duplicate
            print(f"查重：最高「{name}」相关 {corr:.3f}（第二名 {second:.3f}）")
            if corr >= DUPLICATE_CORR and corr - second >= DUPLICATE_CORR_MARGIN:
                if not args.force:
                    print(
                        f"疑似同一张图已在库里：「{name}」相关 {corr:.3f}；"
                        "确认是不同形态请加 --force"
                    )
                    return 1
                print("查重命中但按 --force 继续")
        cv2.imencode(".png", icon)[1].tofile(str(target))
        print(f"头像已写入：{target}（{ICON_SIZE}x{ICON_SIZE}）")

    for note in notes:
        print(f"分类表：{note}")
    meta.write_text(json.dumps(updated, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = " / ".join([job, element, f"{stars} 星", en])
    print(f"分类表：{zh} = {summary}，现 {updated['count']} 条")

    print("下一步：")
    print("  1) python -m auto_game_unified.tools.refresh_hero_meta --check（不应再报新增可归类）")
    print("  2) python -m pytest tests/test_hero_catalog.py tests/test_arena_hero_lists.py -q")
    print("  3) 打开竞技场名单，确认新英雄出现、可勾选、分类筛选能找到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
