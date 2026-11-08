"""分配一个决策记录（ADR）编号并建好骨架文件。

用法（在**工作区根**执行）：:

    python -m auto_game_unified.tools.new_decision --title "手法类文档一个主题只许一份" --slug one-guide-per-topic
    python -m auto_game_unified.tools.new_decision --title "PC 滑动必须抢前台"          # slug 省略时用 --title 里的英文词

为什么需要它
------------
2026-11-08 两个 agent 并行开发，各自「接着往后排」写决策记录，**都写成了 0006**，
门禁当场报重复。这不是谁粗心 —— 没有占号动作时，撞号是必然的。

所以本工具的关键不是「算下一个号」，而是**原子占位**：用 ``open(path, "x")``
（``O_CREAT | O_EXCL``）创建文件，同一瞬间只有一个人能成功；失败就 +1 重试。
两个 agent 同时跑，拿到的也是两个不同的号。

它只建骨架，不写内容 —— 内容得人（或 agent）想清楚。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_DIR = PACKAGE_ROOT / "docs" / "decisions"

#: 已有记录的命名形状。只认这个才能正确算出「下一个号」。
_NUMBERED = re.compile(r"^(\d{4})-([a-z0-9-]+)\.md$")

#: slug 只允许小写英文、数字、连字符（文件名要能一眼看出是什么事）。
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_ALLOWED_STATUS = ("proposed", "accepted", "superseded", "deprecated", "rejected")


def existing_numbers(directory: Path) -> list[int]:
    """目录里已占用的编号（``_TEMPLATE.md`` 之类不算）。"""
    numbers = []
    if not directory.exists():
        return numbers
    for path in directory.iterdir():
        match = _NUMBERED.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def next_number(directory: Path) -> int:
    """下一个可用编号。取「最大值 + 1」而不是「第一个空号」——
    复用空号会让历史里的引用（"见 0006"）指向另一件事。"""
    numbers = existing_numbers(directory)
    return (max(numbers) if numbers else 0) + 1


def slug_from_title(title: str) -> str:
    """从标题里抽英文词当 slug；抽不出来就报错让人显式给。"""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", title)
    slug = "-".join(word.lower() for word in words[:6])
    return slug


def render(number: int, title: str, date: str) -> str:
    return (
        "---\n"
        "status: proposed\n"
        f"date: {date}\n"
        "deciders: 填名字\n"
        "supersedes:\n"
        "superseded_by:\n"
        "---\n"
        "\n"
        f"# {number:04d}. {title}\n"
        "\n"
        "## 背景\n"
        "\n"
        "当时遇到了什么问题、有什么约束。写事实，不写感想。\n"
        "\n"
        "## 决定\n"
        "\n"
        "我们决定做什么。一句话讲完，再用列表写清边界。\n"
        "\n"
        "## 后果\n"
        "\n"
        "代价与收益，**包括接受了的缺点**。\n"
        "\n"
        "## 考虑过但被否掉的方案\n"
        "\n"
        "| 方案 | 为什么没选 |\n"
        "|---|---|\n"
        "| | |\n"
    )


def allocate(
    directory: Path,
    *,
    title: str,
    slug: str,
    date: str | None = None,
) -> Path:
    """占一个编号并写入骨架，返回新建的文件路径。

    用 ``"x"`` 模式创建 → 原子；已被别人占掉就顺延，绝不覆盖。
    """
    if not _SLUG.match(slug):
        raise ValueError(
            f"slug {slug!r} 不合规：只能用小写英文、数字与连字符，例如 one-guide-per-topic"
        )

    directory.mkdir(parents=True, exist_ok=True)
    stamp = date or dt.date.today().isoformat()
    number = next_number(directory)
    for _ in range(200):  # 有界重试：正常最多让一两次
        path = directory / f"{number:04d}-{slug}.md"
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as stream:
                stream.write(render(number, title, stamp))
        except FileExistsError:
            number += 1
            continue
        return path
    raise RuntimeError("连续 200 个编号都被占了，检查 docs/decisions/ 是不是出了问题")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分配 ADR 编号并建骨架")
    parser.add_argument("--title", required=True, help="一句话说清这个决定（用祈使句）")
    parser.add_argument(
        "--slug",
        default="",
        help="英文短名（小写+连字符）。省略时从 --title 里抽英文词，抽不到会报错",
    )
    parser.add_argument("--date", default="", help="覆盖日期（默认今天，YYYY-MM-DD）")
    parser.add_argument("--status", default="proposed", help=f"初始状态：{_ALLOWED_STATUS}")
    args = parser.parse_args(argv)

    if args.status not in _ALLOWED_STATUS:
        print(f"status 只能是 {_ALLOWED_STATUS}")
        return 2

    slug = args.slug.strip() or slug_from_title(args.title)
    if not slug:
        print("标题里没有英文词，抽不出 slug。请显式给一个，例如 --slug arena-refresh-mask")
        return 2

    try:
        path = allocate(
            DECISIONS_DIR,
            title=args.title,
            slug=slug,
            date=args.date.strip() or None,
        )
    except (ValueError, RuntimeError) as error:
        print(str(error))
        return 2

    if args.status != "proposed":
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", f"status: {args.status}", 1
        )
        path.write_text(text, encoding="utf-8", newline="\n")

    relative = path.relative_to(PACKAGE_ROOT).as_posix()
    # 索引 `docs/README.md` 在 docs/ 里面，链接要用相对 docs/ 的路径。
    link_target = path.relative_to(PACKAGE_ROOT / "docs").as_posix()
    number = path.name[:4]
    print(f"已占号并创建：{relative}")
    print()
    print("接下来三件事：")
    print(f"  1. 填内容（背景 / 决定 / 后果 / 否掉的方案）：{relative}")
    print("  2. 在 docs/README.md 的「决策记录」表里加一行，否则门禁会红：")
    print(f"     | [{number}]({link_target}) | {args.title} |")
    print("  3. 跑一次：python -m pytest -q tests/test_docs_index.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
