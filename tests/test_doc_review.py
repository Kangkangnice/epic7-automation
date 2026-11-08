"""文档漂移审查工具的护栏。

分两半：
- **纯函数**（``affected_docs`` / ``is_stale``）：不碰 git 不碰磁盘，直接拿假数据验；
- **接线**（游标文件、映射表里的文档是否还存在）：这类错误不会自己冒出来，
  必须有人守着 —— 比如某份维护手册改了名，映射表还指着旧名字，工具就静默少提醒一份。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_game_unified.tools import doc_review

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 映射规则


def test_a_route_module_points_at_its_own_manual_and_the_status_page() -> None:
    docs = doc_review.affected_docs(["games/epic7/arena.py"])
    assert "docs/maintenance/arena.md" in docs, "改竞技场模块却没提醒去看竞技场手册"
    assert "docs/STATUS.md" in docs, "改路线模块不会影响放行名单吗？至少该看一眼 STATUS"


def test_tests_and_tools_do_not_require_a_doc_review() -> None:
    """改测试和工具不该惊动文档 —— 否则每天都在提醒，人就学会无视它了。"""
    docs = doc_review.affected_docs(
        ["tests/test_arena.py", "tools/check.py", "runtime_logs/a.py"]
    )
    assert docs == [], f"这些路径不该映射到文档，却给出 {docs}"


def test_docs_do_not_remind_you_to_read_themselves() -> None:
    """改文档本身不需要「提醒你去复审文档」。"""
    assert doc_review.affected_docs(["docs/ARCHITECTURE.md"]) == []


def test_shared_modules_pull_in_the_contract_docs() -> None:
    docs = doc_review.affected_docs(["core/matcher.py"])
    assert "docs/ARCHITECTURE.md" in docs
    assert "docs/TRANSITION_CONTRACTS.md" in docs


def test_duplicates_are_collapsed() -> None:
    """多个模块映射到同一份文档时只出现一次。"""
    docs = doc_review.affected_docs(["games/epic7/arena.py", "games/epic7/arena.py"])
    assert docs.count("docs/STATUS.md") == 1


def test_windows_separators_are_handled() -> None:
    """git 在 Windows 上可能给反斜杠，别因此漏掉规则。"""
    assert doc_review.affected_docs(["games\\epic7\\arena.py"]) == doc_review.affected_docs(
        ["games/epic7/arena.py"]
    )


def test_every_mapped_document_really_exists() -> None:
    """映射表里点到的文档必须真的存在。

    守的是「手册改名 / 搬家之后，映射表还指着旧路径」——那种情况工具不会报错，
    只会静默少提醒一份文档，正是这次治理要防的那类失效。
    """
    missing = []
    for _prefix, targets in doc_review.DOC_RULES:
        for doc in targets:
            if not (ROOT / doc).exists():
                missing.append(doc)
    assert not missing, (
        "doc_review.DOC_RULES 里这些文档不存在（改名了？）：\n  "
        + "\n  ".join(sorted(set(missing)))
        + "\n请同步修正映射表，否则复审时会静默漏掉它们。"
    )


# ---------------------------------------------------------------- 阈值


@pytest.mark.parametrize(
    ("behind", "expected"),
    [(0, False), (1, False), (29, False), (30, False), (31, True), (200, True)],
)
def test_the_stale_threshold_is_inclusive_of_the_boundary(behind: int, expected: bool) -> None:
    """正好等于阈值不算落后，超过才算 —— 边界写死，避免以后改动时悄悄挪。"""
    assert doc_review.is_stale(behind) is expected


# ---------------------------------------------------------------- 游标


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def test_the_cursor_file_holds_a_real_commit() -> None:
    """游标必须是一个当前仓库里真实存在的提交，否则工具会直接报错退出。"""
    cursor = doc_review.read_cursor()
    if not cursor:
        pytest.skip("还没设过游标（首次使用请跑 doc_review --mark）")
    assert _git("cat-file", "-t", cursor) == "commit", (
        f"docs/doc-review-cursor.txt 里的 {cursor!r} 不是一个提交。"
        "常见原因：改写过历史、或者从别的分支抄了 SHA。跑 --mark 重置即可。"
    )


def test_the_cursor_is_an_ancestor_of_head() -> None:
    """游标必须是 HEAD 的祖先 —— 否则「之后有多少提交」这个数就没有意义了。"""
    cursor = doc_review.read_cursor()
    if not cursor:
        pytest.skip("还没设过游标")
    if _git("cat-file", "-t", cursor) != "commit":
        pytest.skip("游标不是提交，由上一条用例报错")
    code = subprocess.run(
        ["git", "merge-base", "--is-ancestor", cursor, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    ).returncode
    assert code == 0, (
        f"游标 {cursor[:7]} 不是 HEAD 的祖先（可能改写过历史）。跑 --mark 重置。"
    )
