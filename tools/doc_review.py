"""文档漂移审查：按「上次审到哪个提交」算出这次该复审哪几份文档。

用法（在**工作区根**执行）：:

    python -m auto_game_unified.tools.doc_review              # 列出待审文档
    python -m auto_game_unified.tools.doc_review --check      # 落后太多就退出码 1
    python -m auto_game_unified.tools.doc_review --mark       # 审完了，把游标推到 HEAD

为什么需要它
------------
`docs/STATUS.md` 那套只能保证**结构化事实**（路线数、放行名单）不与代码脱节。
剩下的文档 —— 架构说明、每路线维护手册、用户手册、转场契约 —— 谁也没法自动判断
「里面那句话还成不成立」。业界能做的只有一件事：**把复审变得便宜**。
做法来自社区 skill `doc-maintenance`（paperclipai）：用一个游标记住「上次审到哪个提交」，
下次只从那里往后看，并且按改动文件映射出「该看哪几份文档」，而不是重读整个 docs/。

什么时候跑
----------
- 每轮较大的改动合进来之后；
- 发版前（`--check` 落后超过阈值会返回非零，可以接进发布脚本）；
- 用户问「文档还准吗」的时候。

它不阻断每次提交 —— 语义漂移本来就不可能靠提交门禁发现，硬拦只会让人开始习惯性绕过。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
#: git 仓库根就是包目录本身（工作区根 `auto_game` 不是仓库）。
REPO_ROOT = PACKAGE_ROOT
CURSOR_PATH = PACKAGE_ROOT / "docs" / "doc-review-cursor.txt"

#: 落后多少个提交就提示「该审一遍了」。不是硬性正确性，是催办阈值。
STALE_THRESHOLD = 30

#: 改动路径 → 需要复审的文档。按前缀匹配，**所有命中的规则都会叠加**
#: （具体规则给「这条路线的维护手册」，通用规则 ``games/epic7/`` 再补一份 STATUS）。
#: 只写「改了这个文件，哪份文档里的话可能就不成立了」，不追求完备：
#: 漏掉的代价是「下次看别的文档时会顺带发现」，错报的代价是白读几页。
DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("games/epic7/templates/", ("docs/TEMPLATE_CAPTURE.md", "docs/STATUS.md")),
    ("games/epic7/evidence/", ("docs/STATUS.md", "docs/TRANSITION_CONTRACTS.md")),
    ("games/epic7/modes.py", ("docs/STATUS.md", "docs/EXTENDING.md")),
    ("games/epic7/daily_tasks.py", ("docs/STATUS.md", "docs/maintenance/daily_tasks_grouping.md")),
    ("games/epic7/navigation.py", ("docs/STATUS.md", "docs/TRANSITION_CONTRACTS.md")),
    ("games/epic7/hero_synthesis.py", ("docs/maintenance/hero_synthesis.md",)),
    ("games/epic7/arena.py", ("docs/maintenance/arena.md",)),
    ("games/epic7/story.py", ("docs/maintenance/story.md",)),
    ("games/epic7/side_story.py", ("docs/maintenance/side_story.md",)),
    ("games/epic7/tower.py", ("docs/maintenance/tower.md",)),
    ("games/epic7/expedition.py", ("docs/maintenance/expedition.md",)),
    ("games/epic7/community.py", ("docs/maintenance/community_checkin.md",)),
    ("games/epic7/knights_donation.py", ("docs/maintenance/knights_donation.md",)),
    ("games/epic7/labyrinth_stone.py", ("docs/maintenance/labyrinth_stone.md",)),
    ("games/epic7/moonlight_theater.py", ("docs/maintenance/moonlight_theater.md",)),
    ("games/epic7/sanctuary.py", ("docs/maintenance/sanctuary.md",)),
    ("games/epic7/achievement.py", ("docs/maintenance/achievement.md",)),
    ("games/epic7/", ("docs/STATUS.md",)),
    ("core/", ("docs/ARCHITECTURE.md", "docs/TRANSITION_CONTRACTS.md")),
    ("desktop_qt/", ("docs/USER_GUIDE.md",)),
    ("desktop/", ("docs/USER_GUIDE.md",)),
    ("main.py", ("docs/USER_GUIDE.md", "docs/ARCHITECTURE.md")),
    ("packaging/", ("CONTRIBUTING.md",)),
    (".github/", ("CONTRIBUTING.md",)),
)

#: 这些路径的改动**不会**让任何文档过期（改了它们不必复审）。
IGNORED_PREFIXES = (
    "tests/",
    "tools/",
    "runtime_logs/",
    "runtime_diagnostics/",
)


def affected_docs(changed: list[str]) -> list[str]:
    """改动文件清单 → 需要复审的文档（去重、排序）。

    纯函数：不碰 git、不碰磁盘，方便直接拿假数据验。
    """
    docs: set[str] = set()
    for path in changed:
        normalised = path.strip().replace("\\", "/")
        if not normalised:
            continue
        if normalised.startswith(IGNORED_PREFIXES):
            continue
        if normalised.startswith("docs/"):
            # 文档自己改了，就不用「提醒你去看它」了。
            continue
        for prefix, targets in DOC_RULES:
            if normalised.startswith(prefix):
                docs.update(targets)
    return sorted(docs)


def is_stale(commits_behind: int, threshold: int = STALE_THRESHOLD) -> bool:
    """落后这么多提交，算不算该复审了。纯函数，便于测边界。"""
    return commits_behind > threshold


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def _valid_commit(rev: str) -> bool:
    """这个字符串是不是一个真实存在的提交。游标坏了要能说清楚，别抛 git 的原始错误。"""
    result = subprocess.run(
        ["git", "cat-file", "-t", rev],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "commit"


def read_cursor() -> str:
    """读游标；文件不存在或全是空白就当没设过。"""
    if not CURSOR_PATH.exists():
        return ""
    for line in CURSOR_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line.strip()
    return ""


def write_cursor(sha: str) -> None:
    CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_PATH.write_text(f"{sha}\n", encoding="utf-8", newline="\n")


def _base_rev(cursor: str) -> str:
    """起点提交。没有游标时退化成「最近 20 个提交」，避免首次使用就比全历史。"""
    if cursor:
        return cursor
    total = int(_git("rev-list", "--count", "HEAD").strip() or "0")
    if total <= 1:
        return "HEAD"
    return f"HEAD~{min(20, total - 1)}"


def _commits_since(base: str) -> list[tuple[str, str]]:
    """返回 ``[(sha, subject), ...]``，不含合并提交。"""
    output = _git("log", f"{base}..HEAD", "--no-merges", "--pretty=format:%H%x09%s")
    rows = []
    for line in output.splitlines():
        if "\t" not in line:
            continue
        sha, subject = line.split("\t", 1)
        rows.append((sha, subject))
    return rows


def _changed_files(base: str) -> list[str]:
    output = _git("diff", "--name-only", f"{base}..HEAD")
    return [line for line in output.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按游标算出这次该复审哪几份文档")
    parser.add_argument("--check", action="store_true", help="落后超过阈值时返回 1")
    parser.add_argument("--mark", action="store_true", help="把游标推到当前 HEAD")
    parser.add_argument("--since", default="", help="临时指定起点提交（首次使用时用）")
    args = parser.parse_args(argv)

    head = _git("rev-parse", "HEAD").strip()

    if args.mark:
        write_cursor(head)
        print(f"游标已推进到 {head[:7]}")
        print("记得把 docs/doc-review-cursor.txt 一起提交。")
        return 0

    cursor = args.since or read_cursor()
    if cursor and not _valid_commit(cursor):
        print(f"游标 {cursor!r} 不是一个提交，请用 --since 或 --mark 重置。")
        return 2

    base = _base_rev(cursor)
    commits = _commits_since(base)
    docs = affected_docs(_changed_files(base))

    start = cursor[:7] if cursor else f"{base}（最近 20 个提交）"
    print(f"上次审到 {start}，之后有 {len(commits)} 个提交")
    if commits:
        for sha, subject in commits[:10]:
            print(f"  {sha[:7]} {subject}")
        if len(commits) > 10:
            print(f"  …… 另有 {len(commits) - 10} 个")

    if not docs:
        print("这段时间的改动不影响任何文档。")
    else:
        print(f"\n需要复审 {len(docs)} 份文档：")
        for doc in docs:
            exists = "" if (REPO_ROOT / doc).exists() else "  （文件不存在，考虑清理规则或补写）"
            print(f"  {doc}{exists}")
        print("\n看完没问题就跑：python -m auto_game_unified.tools.doc_review --mark")

    if args.check and is_stale(len(commits)):
        print(f"\n注意：已经落后 {len(commits)} 个提交（阈值 {STALE_THRESHOLD}），该审一遍了。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
