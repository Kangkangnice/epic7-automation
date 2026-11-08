"""ADR 编号分配器的护栏。

核心只有一条：**两个 agent 同时要号，不能拿到同一个**。
2026-11-08 就是这么撞的 —— 各自「接着往后排」，都写成 0006，门禁报重复。

所以这里既验纯函数（算号、slug），也验「原子占位」这个关键行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_game_unified.tools import new_decision

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 算号


def test_the_first_number_is_one(tmp_path: Path) -> None:
    assert new_decision.next_number(tmp_path) == 1


def test_the_next_number_follows_the_largest_not_the_first_gap(tmp_path: Path) -> None:
    """取「最大值 + 1」，不复用空号。

    复用空号会让历史里的引用（"见 0006"）在下一个 0006 出现时指向另一件事 ——
    这种错误几乎不可能被后人发现。
    """
    for name in ("0001-a.md", "0002-b.md", "0005-e.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert new_decision.next_number(tmp_path) == 6


def test_the_template_is_not_counted(tmp_path: Path) -> None:
    (tmp_path / "_TEMPLATE.md").write_text("x", encoding="utf-8")
    assert new_decision.next_number(tmp_path) == 1


# ---------------------------------------------------------------- 原子占位


def test_two_allocations_get_two_different_numbers(tmp_path: Path) -> None:
    """连着要两次号必须是两个号 —— 这是并行开发不撞号的最小保证。"""
    first = new_decision.allocate(tmp_path, title="甲", slug="first")
    second = new_decision.allocate(tmp_path, title="乙", slug="first")
    assert first.name.startswith("0001")
    assert second.name.startswith("0002")


def test_an_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    """已经有人占了这个号，就顺延，绝不覆盖别人写好的内容。"""
    taken = tmp_path / "0001-taken.md"
    taken.write_text("别人的决策\n", encoding="utf-8")

    created = new_decision.allocate(tmp_path, title="我的", slug="taken")

    assert created.name.startswith("0002")
    assert taken.read_text(encoding="utf-8") == "别人的决策\n"


def test_a_bad_slug_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        new_decision.allocate(tmp_path, title="中文标题", slug="中文-slug")


# ---------------------------------------------------------------- 生成物


def test_the_skeleton_carries_the_fields_the_gate_requires(tmp_path: Path) -> None:
    """生成的骨架必须直接能过 docs 门禁的元数据检查（status / date）。"""
    path = new_decision.allocate(
        tmp_path, title="示例决定", slug="example", date="2026-11-08"
    )
    text = path.read_text(encoding="utf-8")

    assert text.startswith("---\n"), "缺 frontmatter"
    assert "status: proposed" in text
    assert "date: 2026-11-08" in text
    assert "# 0001. 示例决定" in text
    for section in ("## 背景", "## 决定", "## 后果", "## 考虑过但被否掉的方案"):
        assert section in text, f"骨架缺「{section}」"


def test_the_title_reaches_the_heading_verbatim(tmp_path: Path) -> None:
    """标题里带中文和标点也要原样进标题行。"""
    title = "PC 滑动必须抢前台（不然滚动检测拿不到峰值）"
    path = new_decision.allocate(tmp_path, title=title, slug="pc-slide")
    assert title in path.read_text(encoding="utf-8")


def test_slug_can_be_derived_from_an_english_title() -> None:
    """抽前 6 个英文词拼 slug，避免文件名过长。"""
    assert new_decision.slug_from_title("Arena refresh mask must not fail open") == (
        "arena-refresh-mask-must-not-fail"
    )


def test_a_pure_chinese_title_yields_no_slug() -> None:
    """抽不出英文词时返回空串，由调用方要求显式 --slug（别生成一串乱码文件名）。"""
    assert new_decision.slug_from_title("竞技场刷新遮罩必须失败关闭") == ""
