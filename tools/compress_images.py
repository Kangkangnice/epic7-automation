"""入库前把截图/模板 **无损** 压一遍 —— 压的是「进 Git 之前」，不是仓库里的存量。

## 为什么需要它

tests/fixtures/ 与 games/epic7/templates/ 全是游戏整屏截图。实测（2026-09-30，
5 张代表性样本）：这些 PNG 用 Pillow 以 optimize=True, compress_level=9 重压，
**像素逐位不变**的前提下能省 18%~26%（整屏 1982x1132 约省 0.3~0.5 MB/张，
3200x2000 的旧夹具约省 1.3 MB/张）。

⚠️ **存量文件不要用本工具「顺手压一遍然后提交」**：那会把压缩后的新 blob 加进
pack，而历史里的旧 blob 一个都不会消失 ⇒ **clone 反而变大**。存量只有走历史重写
（git filter-repo）才有收益。本工具的定位是**把新素材挡在历史之外**。

## 用法

    # 只看报告，不写盘（默认）
    python tools/compress_images.py --staged
    python tools/compress_images.py --paths "tests/fixtures/epic7_sanctuary/*.png"

    # 真压（压完记得重新 git add）
    python tools/compress_images.py --staged --apply
    python tools/compress_images.py --paths "games/epic7/templates/**/*.png" --apply

--staged 取暂存区里新增/修改的图片；--paths 取仓库相对 glob（可多个）。
两者都不给就只打印提示并退出 0（**不会**默认扫全仓、误伤存量）。

## 安全约束（失败关闭）

- **只做无损**：压完必须把两边都解码出来比 np.array_equal，不一致就**丢弃结果、
  保留原文件**并报错退出非 0。绝不「压得动就压」。
- 只处理 Pillow 模式为 RGB / RGBA / L 的 PNG；调色板、16 位等一律跳过
  （跳过是正常结论，不算失败）。
- 收益不足（默认同时要求 >= 4096 字节且 >= 1%）就不动文件 —— 避免为了几十字节
  制造一次全仓 diff。
"""

from __future__ import annotations

import argparse
import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

PACKAGE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_DIR

DEFAULT_MIN_GAIN_BYTES = 4096
DEFAULT_MIN_GAIN_RATIO = 0.01
SUPPORTED_MODES = frozenset({"RGB", "RGBA", "L"})
IMAGE_SUFFIXES = frozenset({".png"})


class UnsupportedImage(RuntimeError):
    """这张图不在「无损重压」的适用范围内（跳过，不是失败）。"""


class LosslessCheckFailed(RuntimeError):
    """重压后像素不一致 —— 绝不允许这种结果落盘。"""


@dataclass(frozen=True)
class CompressResult:
    path: Path
    before: int
    after: int
    changed: bool
    reason: str = ""

    @property
    def saved(self) -> int:
        return max(0, self.before - self.after)


def recompress_png(data: bytes) -> bytes:
    """把一份 PNG 字节流无损重压；不适用时抛 UnsupportedImage。"""
    with Image.open(io.BytesIO(data)) as image:
        if image.mode not in SUPPORTED_MODES:
            raise UnsupportedImage(f"暂不支持无损重压的图片模式：{image.mode}")
        image.load()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True, compress_level=9)
    return buffer.getvalue()


def decode_pixels(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return np.asarray(image)


def compress_bytes(data: bytes) -> bytes:
    """重压并校验像素逐位一致；不一致直接抛错（调用方据此保留原文件）。"""
    optimized = recompress_png(data)
    if not np.array_equal(decode_pixels(data), decode_pixels(optimized)):
        raise LosslessCheckFailed("重压后像素不一致")
    return optimized


def compress_file(
    path: Path,
    *,
    apply: bool = False,
    min_gain_bytes: int = DEFAULT_MIN_GAIN_BYTES,
    min_gain_ratio: float = DEFAULT_MIN_GAIN_RATIO,
) -> CompressResult:
    """报告（并在 apply 时执行）单个文件的无损重压。"""
    original = path.read_bytes()
    before = len(original)
    try:
        optimized = compress_bytes(original)
    except UnsupportedImage as error:
        return CompressResult(path, before, before, False, str(error))
    after = len(optimized)
    saved = before - after
    if saved < min_gain_bytes or saved < before * min_gain_ratio:
        return CompressResult(
            path,
            before,
            after,
            False,
            f"收益不足（省 {saved} 字节），保持原文件",
        )
    if apply:
        # 先写临时文件再原子替换：中途失败不会留下半张图。
        temporary = path.with_name(path.name + ".compress-tmp")
        temporary.write_bytes(optimized)
        temporary.replace(path)
    return CompressResult(path, before, after, True, "已重压" if apply else "可重压")


def _expand_paths(patterns: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        if any(character in pattern for character in "*?["):
            found.extend(sorted(REPO_ROOT.glob(pattern)))
        else:
            found.append(REPO_ROOT / pattern)
    unique = {path.resolve(): path for path in found if path.is_file()}
    return [unique[key] for key in sorted(unique)]


def _staged_images() -> list[Path]:
    """暂存区里新增/修改的图片（--diff-filter=ACM）。"""
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "读取暂存区失败："
            + completed.stderr.decode("utf-8", "replace").strip()
        )
    names = [
        name
        for name in completed.stdout.decode("utf-8", "replace").split("\0")
        if name
    ]
    return [
        REPO_ROOT / name
        for name in names
        if Path(name).suffix.lower() in IMAGE_SUFFIXES
        and (REPO_ROOT / name).is_file()
    ]


def _format_report(results: Sequence[CompressResult], *, apply: bool) -> str:
    lines: list[str] = []
    changed = [item for item in results if item.changed]
    skipped = [item for item in results if not item.changed]
    for item in results:
        relative = item.path.relative_to(REPO_ROOT)
        if item.changed:
            ratio = (1 - item.after / item.before) * 100 if item.before else 0.0
            lines.append(
                f"{'重压' if apply else '可压'} {relative} "
                f"{item.before / 1024:.0f}KB -> {item.after / 1024:.0f}KB "
                f"（省 {ratio:.1f}%）"
            )
        else:
            lines.append(f"跳过 {relative} 原因={item.reason}")
    total_before = sum(item.before for item in changed)
    total_after = sum(item.after for item in changed)
    saved = total_before - total_after
    ratio = (saved / total_before * 100) if total_before else 0.0
    verb = "已重压" if apply else "可重压"
    lines.append(
        f"合计：候选 {len(results)} 张、{verb} {len(changed)} 张、"
        f"跳过 {len(skipped)} 张；"
        f"{total_before / 1024:.0f}KB -> {total_after / 1024:.0f}KB"
        f"（省 {saved / 1024:.0f}KB / {ratio:.1f}%）"
    )
    if changed and not apply:
        lines.append("这是预览（没有写盘）。确认无误后加 --apply 重跑，然后重新 git add。")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="入库前把截图/模板无损重压（压完记得重新 git add）"
    )
    parser.add_argument("--staged", action="store_true", help="处理暂存区里的图片")
    parser.add_argument(
        "--paths", nargs="*", default=[], help="仓库相对路径或 glob（空格分隔）"
    )
    parser.add_argument("--apply", action="store_true", help="真正写盘；缺省只打印预览")
    parser.add_argument(
        "--min-gain-bytes",
        type=int,
        default=DEFAULT_MIN_GAIN_BYTES,
        help=f"低于这个节省量就不动文件（默认 {DEFAULT_MIN_GAIN_BYTES}）",
    )
    parser.add_argument(
        "--min-gain-ratio",
        type=float,
        default=DEFAULT_MIN_GAIN_RATIO,
        help=f"低于这个节省比例就不动文件（默认 {DEFAULT_MIN_GAIN_RATIO}）",
    )
    args = parser.parse_args(argv)

    targets: list[Path] = []
    if args.staged:
        targets.extend(_staged_images())
    if args.paths:
        targets.extend(_expand_paths(args.paths))
    unique = {path.resolve(): path for path in targets}
    targets = [unique[key] for key in sorted(unique)]
    targets = [path for path in targets if path.suffix.lower() in IMAGE_SUFFIXES]

    if not targets:
        print(
            "没有要处理的图片。给 --staged 或 --paths（本工具**不会**默认扫全仓）。",
            flush=True,
        )
        return 0

    results: list[CompressResult] = []
    for path in targets:
        try:
            results.append(
                compress_file(
                    path,
                    apply=args.apply,
                    min_gain_bytes=args.min_gain_bytes,
                    min_gain_ratio=args.min_gain_ratio,
                )
            )
        except LosslessCheckFailed as error:
            print(f"失败 {path}: {error}（原文件未改动）", flush=True)
            return 1
    print(_format_report(results, apply=args.apply), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
