"""文档漂移审查工具的护栏。

分两半：
- **纯函数**（``affected_docs`` / ``review_note_missing``）：不碰 git 不碰磁盘，拿假数据验；
- **接线**（映射表里的文档是否还存在、关键路径有没有规则）：这类错误不会自己冒出来，
  必须有人守着 —— 比如某份维护手册改了名，映射表还指着旧名字，工具就静默少提醒一份。
"""

from __future__ import annotations

from pathlib import Path

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


def test_pc_changes_remind_you_of_the_pc_guide() -> None:
    """反向验证：PC 主文档自称唯一权威，改了窗口层就必须提醒复审它。

    2026-11-08 治理时发现映射表 0 条指向它 —— 也就是说这份 666 行文档
    当时没有任何机制会让人回头看。守卫的就是「补了规则又悄悄删掉」。
    """
    for changed in (
        "core/pc_window.py",
        "games/epic7/template_paths.py",
        "games/epic7/templates/story/home.png",
        "desktop/catalog.py",
        "main.py",
    ):
        docs = doc_review.affected_docs([changed])
        assert "docs/PC_TEMPLATE_MIGRATION.md" in docs, (
            f"改了 {changed} 却没提醒复审 PC 客户端接入指南：{docs}"
        )


def test_shared_templates_remind_you_of_both_backends() -> None:
    """PC 会回落共享模板，改共享图必须同时看采集规范与 PC 结论。"""
    docs = doc_review.affected_docs(["games/epic7/templates/story/home.png"])
    assert "docs/TEMPLATE_CAPTURE.md" in docs
    assert "docs/PC_TEMPLATE_MIGRATION.md" in docs


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


# ---------------------------------------------------------------- 映射覆盖率


def test_every_critical_path_has_a_review_target() -> None:
    """映射表不许漏掉关键路径。

    守的是「新加了一个模块 / 改了某条通道，映射表却没登记」—— 工具不会报错，
    只会静默少提醒一份文档。2026-11-09 就漏过 ``core/pc_window.py``。
    """
    missing = [path for path in doc_review.MUST_MAP if not doc_review.affected_docs([path])]
    assert not missing, (
        "这些关键改动路径没有任何复审规则：\n  "
        + "\n  ".join(missing)
        + "\n请在 doc_review.DOC_RULES 补一条，别靠人记得。"
    )


def test_staged_mode_reads_the_index_not_a_cursor(monkeypatch) -> None:
    """复审只看本次改动，不再依赖任何「上次审到哪」的状态。"""
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        return "core/pc_window.py\n"

    monkeypatch.setattr(doc_review, "_git", fake_git)
    assert doc_review.staged_files() == ["core/pc_window.py"]
    assert calls[0][:2] == ("diff", "--cached")


# ---------------------------------------------------------------- 提交留痕


def test_a_commit_that_changes_mapped_code_needs_a_note(tmp_path: Path) -> None:
    """命中规则的提交，没写复审留痕就该被拦。"""
    docs = doc_review.affected_docs(["core/pc_window.py"])
    assert docs, "前提不成立：这条路径本来就该命中规则"
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("修一个窗口问题\n", encoding="utf-8")
    assert doc_review.review_note_missing(message, docs)


def test_a_commit_with_the_note_passes(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "修一个窗口问题\n\nDoc-reviewed: PC 主文档现行结论未变\n",
        encoding="utf-8",
    )
    assert not doc_review.review_note_missing(message, ["docs/PC_TEMPLATE_MIGRATION.md"])


def test_a_commit_that_touches_nothing_mapped_needs_no_note(tmp_path: Path) -> None:
    """没命中规则就不该逼人写标记，否则大家会学会无脑复制。"""
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("只改了测试\n", encoding="utf-8")
    assert not doc_review.review_note_missing(message, [])
    assert doc_review.affected_docs(["tests/test_arena.py"]) == []


def test_an_unreadable_commit_message_is_rejected(tmp_path: Path) -> None:
    """读不到提交信息时 fail-closed，别当成「审过了」。"""
    assert doc_review.review_note_missing(tmp_path / "missing", ["docs/STATUS.md"])


def test_the_note_marker_is_exact(tmp_path: Path) -> None:
    """大小写/别名不算留痕，避免随手一句「看过文档」就蒙混过去。"""
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("doc-reviewed: 看过了\n", encoding="utf-8")
    assert doc_review.review_note_missing(message, ["docs/STATUS.md"])
