"""返工统计口径的护栏。

这套口径会被拿来判「路线达标没有」，算错就会给出假结论：
把子路线记到父路线、把公共层算成路线、把第 8 天的修复算进 7 天窗口，
或者像 2026-11-24 第一版那样**只数标题带 fix 的提交**（社区签到只算出 2 次，
实际修正 5 次）——每一种都会让数字失去意义。
"""

from __future__ import annotations

from auto_game_unified.tools import report_rework as rr


def _commit(day: str, subject: str, *files: str) -> dict[str, object]:
    return {"hash": subject[:7], "day": day, "subject": subject, "files": list(files)}


def test_story_star_is_not_counted_as_story() -> None:
    assert rr.route_hits("games/epic7/story_star.py") == ["story_star"]
    assert rr.route_hits("games/epic7/story.py") == ["story"]
    assert rr.route_hits("tests/test_story_star.py") == ["story_star"]


def test_shared_layer_is_not_a_route() -> None:
    assert rr.route_hits("core/window.py") == []
    assert rr.route_hits("games/epic7/runner_base.py") == []


def test_rework_counts_fix_batch_and_untyped_but_not_feat_or_refactor() -> None:
    """标题类型决定是否计入，但 fix 不是唯一来源。"""
    assert rr.is_rework("fix(epic7): 滑动账本")
    assert rr.is_rework("chore: 收口 11-21~11-22 实跑改动")
    assert rr.is_rework("社区签到：判页改用页面骨架")
    assert not rr.is_rework("feat(epic7): 新增路线")
    assert not rr.is_rework("refactor(desktop): 界面文案统一")
    assert not rr.is_rework("docs: 文档瘦身")


def test_structural_commits_are_not_rework() -> None:
    """架构整改会改到路线文件，但改的是代码形状，不是失败现场。"""
    assert not rr.is_rework("完成亚卡助手架构整改与独立验收（A–F）")


def test_community_is_not_two_fixes() -> None:
    """用户 2026-11-24 指出的反例：标题只有 2 个 fix，实际修正 5 次。"""
    commits = [
        _commit("2026-10-07", "feat(epic7): 新增社区签到路线", "games/epic7/community.py"),
        _commit("2026-10-10", "fix(epic7): 滑动账本", "games/epic7/community.py"),
        _commit("2026-10-11", "fix(epic7): 摘掉点赞任务", "games/epic7/community.py"),
        _commit("2026-10-20", "社区签到：判页改用页面骨架", "games/epic7/community.py"),
        _commit("2026-11-15", "feat(epic7): 新增企鹅路线，并收口各批改动", "games/epic7/community.py"),
        _commit("2026-11-22", "chore: 收口 11-21~11-22 实跑改动", "games/epic7/community.py"),
    ]
    row = rr.summarise(commits)["community"]
    assert row["rework"] == 5
    assert row["fix_titled"] == 2


def test_seven_day_window_and_budget_are_exclusive_at_the_boundary() -> None:
    """第 7 天的修复计入窗口，第 8 天不计；第 4 次修复即超预算。"""
    commits = [
        _commit("2026-01-01", "feat: add arena", "games/epic7/arena.py"),
        _commit("2026-01-08", "fix: 第 7 天", "games/epic7/arena.py"),
        _commit("2026-01-09", "fix: 第 8 天", "games/epic7/arena.py"),
        _commit("2026-01-10", "fix: 第 9 天", "games/epic7/arena.py"),
        _commit("2026-01-11", "fix: 第 10 天", "games/epic7/arena.py"),
    ]
    row = rr.summarise(commits)["arena"]
    assert row["launch"] == "2026-01-01"
    assert row["rework"] == 4
    assert row["within7"] == 1, "第 8 天的修复不该算进 7 天窗口"
    assert row["first_pass"] is False
    assert row["within_budget"] is False


def test_three_fixes_stay_within_budget() -> None:
    commits = [
        _commit("2026-02-01", "feat: add tower", "games/epic7/tower.py"),
        _commit("2026-02-02", "fix: a", "games/epic7/tower.py"),
        _commit("2026-02-03", "fix: b", "games/epic7/tower.py"),
        _commit("2026-02-04", "fix: c", "games/epic7/tower.py"),
    ]
    row = rr.summarise(commits)["tower"]
    assert row["rework"] == 3
    assert row["within_budget"] is True


def test_a_commit_touching_two_routes_counts_on_both() -> None:
    commits = [
        _commit("2026-03-01", "feat: add arena", "games/epic7/arena.py"),
        _commit("2026-03-02", "feat: add tower", "games/epic7/tower.py"),
        _commit("2026-03-03", "fix: 一起修", "games/epic7/arena.py", "games/epic7/tower.py"),
    ]
    rows = rr.summarise(commits)
    assert rows["arena"]["rework"] == 1
    assert rows["tower"]["rework"] == 1


def test_shared_fix_is_counted_separately() -> None:
    commits = [
        _commit("2026-04-01", "feat: add arena", "games/epic7/arena.py"),
        _commit("2026-04-02", "fix: 公共层", "games/epic7/arena.py", "core/window.py"),
        _commit("2026-04-03", "fix: 只改路线", "games/epic7/arena.py"),
    ]
    row = rr.summarise(commits)["arena"]
    assert row["rework"] == 2
    assert row["shared_fix"] == 1


def test_parse_log_keeps_hash_day_subject_and_files() -> None:
    text = "@@@abc1234\t2026-05-06\tfix: 示例\nM\tcore/window.py\nM\tgames/epic7/arena.py\n"
    commits = rr.parse_log(text)
    assert len(commits) == 1
    assert commits[0]["hash"] == "abc1234"
    assert commits[0]["day"] == "2026-05-06"
    assert commits[0]["subject"] == "fix: 示例"
    assert commits[0]["files"] == ["core/window.py", "games/epic7/arena.py"]


def test_patch_stats_count_hunks_so_one_commit_can_carry_several_changes() -> None:
    """一次提交改了三处，就是三个块，不会被标题压成「一次」。"""
    text = (
        "1\t0\tgames/epic7/arena.py\n"
        "2\t1\tdocs/maintenance/arena.md\n"
        "\n"
        "diff --git a/games/epic7/arena.py b/games/epic7/arena.py\n"
        "--- a/games/epic7/arena.py\n"
        "+++ b/games/epic7/arena.py\n"
        "@@ -1 +1 @@\n"
        "@@ -9,2 +9,3 @@\n"
        "@@ -30 +31 @@\n"
    )
    stats = rr.parse_patch_stats(text)
    assert stats["games/epic7/arena.py"] == (1, 0, 3)
    assert stats["docs/maintenance/arena.md"] == (2, 1, 0)


def test_binary_files_do_not_break_patch_stats() -> None:
    text = (
        "-\t-\tgames/epic7/templates/arena/entry.png\n"
        "\n"
        "diff --git a/games/epic7/templates/arena/entry.png b/games/epic7/templates/arena/entry.png\n"
        "Binary files differ\n"
    )
    assert rr.parse_patch_stats(text)["games/epic7/templates/arena/entry.png"] == (0, 0, 0)


def test_hero_templates_live_under_hero_not_hero_synthesis() -> None:
    """英雄合成的模板目录叫 hero，别名漏了就会把它的图算到别的路线。"""
    assert rr.route_hits("games/epic7/templates/hero/sss_badge.png") == ["hero_synthesis"]
    assert rr.route_hits("tests/fixtures/epic7_hero/list.png") == ["hero_synthesis"]
