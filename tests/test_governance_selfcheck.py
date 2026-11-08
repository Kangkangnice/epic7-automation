"""治理机制自己的护栏：防止「规矩还写在文档里、实现却被改回去」。

为什么需要这一层
----------------
2026-11-09 验收发现，文档治理 v1 写得挺完整，却没有任何测试在盯：
生成器会不会被本机临时文件骗、钩子是不是真的会拦、游标是不是又回来了。
规矩一旦被悄悄改回去，其余门禁照样全绿 —— 这是最危险的一种失效。

本文件只做一件事：**每条治理规矩都要能证明「拆掉它就会变红」**。
"""

from __future__ import annotations

from pathlib import Path

from auto_game_unified.tools import doc_review

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 现状页口径


def test_the_status_page_counts_only_tracked_assets() -> None:
    """不许再退回「数本机目录」—— 那会让本机绿、干净检出红。"""
    src = _text("tools/gen_status.py")
    assert "ls-files" in src, "生成器没有问 git 要入库清单"
    assert "def _tracked_pngs" in src
    assert "tracked = _tracked_pngs()" in src, "render() 没有走入库口径"
    assert "def _count(pattern" not in src, "旧的 rglob 计数函数又回来了"


# ---------------------------------------------------------------- 绕不过去


def test_the_pre_commit_hook_fails_closed() -> None:
    """找不到解释器时拒绝提交，不许静默放行。"""
    src = _text("tools/githooks/pre-commit")
    assert "exit 1" in src
    assert "找不到 python" in src
    assert "跳过检查（不影响提交）" not in src, "fail-open 的老写法又回来了"


def test_check_py_refuses_when_no_test_interpreter() -> None:
    src = _text("tools/check.py")
    assert "拒绝提交：本机找不到装了 pytest 的解释器" in src
    assert "return 1" in src


def test_the_commit_msg_hook_requires_a_review_note() -> None:
    hook = ROOT / "tools" / "githooks" / "commit-msg"
    assert hook.exists(), "提交信息钩子不见了，复审留痕就没人查了"
    src = hook.read_text(encoding="utf-8")
    assert "--require-note" in src
    assert "--staged" in src


def test_ci_has_a_separate_governance_gate() -> None:
    """本地 --no-verify 能跳，干净检出的 CI 不能。"""
    src = _text(".github/workflows/tests.yml")
    assert "Governance gate" in src
    assert "test_governance_selfcheck.py" in src


# ---------------------------------------------------------------- 复审即时化


def test_no_cursor_came_back() -> None:
    """游标是「要人记得推进的状态」，不许复活。"""
    src = _text("tools/doc_review.py")
    assert "CURSOR_PATH" not in src
    assert "read_cursor" not in src
    assert "def staged_files" in src
    assert not (ROOT / "docs" / "doc-review-cursor.txt").exists()


def test_the_review_note_is_actually_enforced(monkeypatch, tmp_path: Path) -> None:
    """行为验证：命中规则的提交，没留痕必须被拒、补上才放行。"""
    monkeypatch.setattr(doc_review, "staged_files", lambda: ["core/pc_window.py"])
    message = tmp_path / "COMMIT_EDITMSG"

    message.write_text("修一个窗口问题\n", encoding="utf-8")
    assert doc_review.main(["--staged", "--require-note", str(message)]) == 1

    message.write_text("修一个窗口问题\n\nDoc-reviewed: 无变化\n", encoding="utf-8")
    assert doc_review.main(["--staged", "--require-note", str(message)]) == 0


# ---------------------------------------------------------------- 分类边界


def test_the_index_explains_the_two_new_boundaries() -> None:
    """「决策草稿期」与「已知缺口」这两类边界不许被删掉。"""
    src = _text("docs/README.md")
    assert "Doc-reviewed:" in src
    assert "已知缺口" in src
    assert "草稿期可改正文" in src
    template = _text("docs/decisions/_TEMPLATE.md")
    assert "草稿期" in template
