"""文档漂移审查：**按本次改动**列出该复审哪几份文档。

用法（在**工作区根**执行）：:

    python -m auto_game_unified.tools.doc_review            # 工作区相对 HEAD 的改动
    python -m auto_game_unified.tools.doc_review --staged   # 只看暂存区

提交钩子会另外带 ``--staged --require-note <提交信息文件>`` 调用本脚本。

为什么不再用游标
----------------
`docs/STATUS.md` 那套只能保证**结构化事实**（路线数、放行名单）不与代码脱节。
剩下的文档 —— 架构说明、每路线维护手册、用户手册、转场契约 —— 谁也没法自动判断
「里面那句话还成不成立」。业界能做的只有一件事：**把复审变得便宜**。

初版借社区 skill `doc-maintenance` 的游标记「上次审到哪个提交」。2026-11-09 验收发现
它天生有洞：游标是**要人记得推进的状态**，一忙就落后 7 个提交；而且它只看两个提交
之间的 diff，**工作区里未提交的改动完全看不见**。现在改成按「本次暂存区 / 本次工作区」
即时判定，没有任何需要记忆的状态。

复审留痕
--------
命中规则的提交必须在提交信息里写一行 ``Doc-reviewed:``。机器只能验证「有没有留痕」，
不能验证「有没有真读」—— 但它把「审文档」从可跳过的自觉动作，变成提交时必然碰到的一问。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
#: git 仓库根就是包目录本身（工作区根 `auto_game` 不是仓库）。
REPO_ROOT = PACKAGE_ROOT

#: 关键改动路径：每一条都必须能映射到至少一份文档。
#: 守的是「新增/改动了某个模块，映射表却没登记」这类静默漏提醒
#: （2026-11-09 就漏过 core/pc_window.py）。反向护栏在 tests/test_doc_review.py。
MUST_MAP: tuple[str, ...] = (
    "core/pc_window.py",
    "core/matcher.py",
    "main.py",
    "games/epic7/arena.py",
    "games/epic7/templates/story/home.png",
    "desktop/catalog.py",
    "desktop/preflight.py",
    "desktop_qt/app.py",
    "tools/live_check.py",
    "packaging/epic7_auto_assistant.spec",
    ".github/workflows/tests.yml",
)

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
    # PC 移植这条线（2026-11-08 补）：主文档自称「PC 结论唯一权威」，但此前
    # DOC_RULES 里 0 条指向它 —— 改了窗口层、补了 pc 图都不会提醒复审那份 666 行文档。
    ("core/pc_window.py", ("docs/PC_TEMPLATE_MIGRATION.md", "docs/howto/live_verification.md")),
    ("games/epic7/template_paths.py", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("games/epic7/templates/", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("desktop/catalog.py", ("docs/STATUS.md", "docs/PC_TEMPLATE_MIGRATION.md")),
    ("main.py", ("docs/PC_TEMPLATE_MIGRATION.md",)),
    ("core/", ("docs/ARCHITECTURE.md", "docs/TRANSITION_CONTRACTS.md")),
    # 权限/实机这条线：知识与代码是「判断」，改了就一定要回头读那份手册。
    ("core/elevation.py", ("docs/howto/live_verification.md",)),
    ("desktop/preflight.py", ("docs/howto/live_verification.md", "docs/USER_GUIDE.md")),
    ("tools/live_check.py", ("docs/howto/live_verification.md",)),
    ("tools/_run_live", ("docs/howto/live_verification.md",)),
    ("tools/_verify_", ("docs/howto/live_verification.md",)),
    ("tools/_diagnose_", ("docs/howto/live_verification.md",)),
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

    判定顺序：**先看规则，再看忽略名单** —— 否则 ``tools/`` 整体被忽略之后，
    ``tools/live_check.py`` 这种「本来就该提醒复审手册」的路径永远轮不到。
    """
    docs: set[str] = set()
    for path in changed:
        normalised = path.strip().replace("\\", "/")
        if not normalised:
            continue
        if normalised.startswith("docs/"):
            # 文档自己改了，就不用「提醒你去看它」了。
            continue
        matched = False
        for prefix, targets in DOC_RULES:
            if normalised.startswith(prefix):
                docs.update(targets)
                matched = True
        if matched:
            continue
        if normalised.startswith(IGNORED_PREFIXES):
            continue
    return sorted(docs)


#: 提交信息里的复审留痕标记。大小写敏感，写错等于没留。
REVIEW_NOTE = "Doc-reviewed:"


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


def staged_files() -> list[str]:
    """本次暂存区改了哪些文件。提交钩子用它 —— 天然包含还没提交的改动。"""
    return [line for line in _git("diff", "--cached", "--name-only").splitlines() if line.strip()]


def working_files() -> list[str]:
    """工作区相对 HEAD 的全部改动（含未暂存），日常自查用。"""
    return [line for line in _git("diff", "--name-only", "HEAD").splitlines() if line.strip()]


def review_note_missing(message_path: Path, docs: list[str]) -> bool:
    """命中了复审规则、但提交信息没留痕 ⇒ 返回 True（应当拒绝提交）。

    只验证「有没有留痕」，不假装能验证「有没有真读」—— 后者是人的判断。
    """
    if not docs:
        return False
    try:
        message = Path(message_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return REVIEW_NOTE not in message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按本次改动列出该复审的文档")
    parser.add_argument("--staged", action="store_true", help="只看暂存区（提交钩子用）")
    parser.add_argument(
        "--require-note", default="", help="提交信息文件路径；命中规则却没留痕就返回 1"
    )
    args = parser.parse_args(argv)

    changed = staged_files() if args.staged else working_files()
    docs = affected_docs(changed)

    if args.require_note:
        if review_note_missing(args.require_note, docs):
            print("[doc-review] 本次改动命中了文档复审规则，但提交信息里没有留痕。", file=sys.stderr)
            print("[doc-review] 该复审：", file=sys.stderr)
            for doc in docs:
                print(f"  - {doc}", file=sys.stderr)
            print(
                f"[doc-review] 看过之后在提交信息里加一行「{REVIEW_NOTE} 看过了哪几份」"
                "（确实没有变化就写「无变化」）。",
                file=sys.stderr,
            )
            print("[doc-review] 这是唯一能证明「审过」的痕迹；CI 会再查一遍。", file=sys.stderr)
            return 1
        print(f"[doc-review] 复审留痕已确认（{len(docs)} 份）。")
        return 0

    source = "暂存区" if args.staged else "工作区相对 HEAD"
    if not docs:
        print(f"{source}的改动不影响任何文档。")
    else:
        print(f"{source}的改动需要复审 {len(docs)} 份文档：")
        for doc in docs:
            exists = "" if (REPO_ROOT / doc).exists() else "  （文件不存在，考虑清理规则或补写）"
            print(f"  {doc}{exists}")
        print(f"\n看完在提交信息里加一行 {REVIEW_NOTE} 说明看过哪几份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
