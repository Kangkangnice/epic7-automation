"""Verify the distributed hero roster locally, without the external catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from auto_game_unified.games.epic7.hero_catalog import ELEMENTS, JOBS, META_FILENAME, STARS
from auto_game_unified.games.epic7.hero_match import default_library_dir, library_names


def inspect_roster(library: Path) -> list[str]:
    """Return actionable issues in the same set of portraits the picker lists."""
    metadata = library / META_FILENAME
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"分类表无法读取：{error}"]
    if not isinstance(payload, dict) or not isinstance(payload.get("heroes"), dict):
        return ["分类表缺少 heroes 对象"]

    heroes = payload["heroes"]
    names = set(library_names(library))
    errors: list[str] = []
    if not names:
        errors.append("图鉴库中没有可选的英雄头像")
    if type(payload.get("count")) is not int or payload["count"] != len(heroes):
        errors.append("分类表 count 与 heroes 条目数不一致")
    errors.extend(f"「{name}」缺少分类" for name in sorted(names - heroes.keys()))
    errors.extend(f"「{name}」缺少可用头像" for name in sorted(heroes.keys() - names))

    for name, entry in heroes.items():
        if not isinstance(entry, dict) or (
            entry.get("job") not in JOBS
            or entry.get("element") not in ELEMENTS
            or type(entry.get("stars")) is not int
            or entry["stars"] not in STARS
            or not isinstance(entry.get("en"), str)
            or not entry["en"].strip()
        ):
            errors.append(f"「{name}」的英文名或分类无效")
    for name in sorted(names):
        path = library / f"{name}.png"
        try:
            with path.open("rb") as source, Image.open(source) as portrait:
                if portrait.format != "PNG" or portrait.mode != "RGB" or portrait.size != (112, 112):
                    errors.append(f"「{name}」的头像应为 112×112 RGB PNG")
                else:
                    portrait.load()
        except (OSError, ValueError) as error:
            errors.append(f"「{name}」的头像无法解码：{error}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线检查竞技场图鉴资产与分类的一致性")
    parser.add_argument("--library", type=Path, default=default_library_dir())
    issues = inspect_roster(parser.parse_args(argv).library)
    if issues:
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("图鉴头像和分类表一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
