"""``docs/STATUS.md`` 与代码的一致性门禁。

这个文件只干一件事：**保证「现状速查」这一页永远等于代码**。

为什么值得为它单开一个测试文件
------------------------------
项目吃过三次同样的亏：文档里写「十六条路线」而代码已经是十七条、写「PC 放行 9 条」
而实际 13 条。这类漂移不会让任何测试变红，只会让读文档的人（尤其是 AI agent）
照着过期的事实干活 —— 而 agent 没有「那是三个月前」的时间感，它会把过期文档
当成现行规则执行。

治它的办法只有一个：**把事实从代码算出来，再逐字比对**。本文件就是那道比对。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from auto_game_unified.desktop import catalog
from auto_game_unified.games.epic7 import daily_tasks, modes
from auto_game_unified.tools import gen_status

ROOT = Path(__file__).resolve().parents[1]

REGENERATE_HINT = (
    "docs/STATUS.md 与代码不一致。请在**工作区根**（不是 auto_game_unified 目录）执行：\n"
    "    python -m auto_game_unified.tools.gen_status\n"
    "然后把它一起提交。不要手改这个文件 —— 手改会在下一次门禁被打回。"
)


def _on_disk() -> str:
    return gen_status.STATUS_PATH.read_text(encoding="utf-8")


def test_the_status_page_matches_the_code() -> None:
    """核心门禁：磁盘上的内容必须等于此刻代码渲染出来的内容。"""
    expected = gen_status.render()
    actual = _on_disk()
    if expected == actual:
        return
    # 给出最小可用的差异，而不是让人自己 diff 全文。
    expected_lines = expected.splitlines()
    actual_lines = actual.splitlines()
    for index, (want, got) in enumerate(
        zip(expected_lines, actual_lines, strict=False), start=1
    ):
        if want != got:
            raise AssertionError(
                f"{REGENERATE_HINT}\n\n"
                f"第一处不同在第 {index} 行：\n"
                f"  文档里： {got}\n"
                f"  代码算出来： {want}"
            )
    raise AssertionError(
        f"{REGENERATE_HINT}\n\n行数不同：文档 {len(actual_lines)} 行，"
        f"代码算出来 {len(expected_lines)} 行。"
    )


def test_the_page_lists_every_route_exactly_once() -> None:
    """每条路线都要在表里出现，且只出现一次。

    守的是生成器的**静默漏行**：比如某天有人把 catalog.ROUTES 换成生成器，
    恰好在中间抛异常被吞掉，表就短了一截，而「与代码一致」那条比对
    在「重生成过一次」之后照样通过。
    """
    text = _on_disk()
    # 只看第一节「路线总览」：STATUS 后来又加了一张「按路线的现行事实」表，
    # 全文计数会把两张表都算进去，误报成「重复了一行」。
    first_table = text.split("## 二、在制品")[0]
    for mode in modes.MODE_SPECS:
        occurrences = first_table.count(f"| `{mode}` |")
        assert occurrences == 1, (
            f"路线 {mode} 在 docs/STATUS.md 第一节表格里出现了 {occurrences} 次，应当恰好 1 次。"
            f"要么是生成器漏了它，要么是重复了一行。请跑生成器后人工确认。"
        )


def test_the_route_count_matches_the_registry() -> None:
    """标题里那个数字必须等于真实路线数（这是最容易写的那个谎）。"""
    text = _on_disk()
    expected = f"（共 {len(catalog.ROUTES)} 条）"
    assert expected in text, (
        f"docs/STATUS.md 里找不到「路线总览{expected}」。"
        f"当前 catalog.ROUTES 是 {len(catalog.ROUTES)} 条，"
        f"若表格上方写着别的数字，说明这一页过期了。{REGENERATE_HINT}"
    )


def test_the_daily_section_follows_the_real_execution_order() -> None:
    """每日任务的顺序是业务规则，文档必须与 DAILY_TASKS 同序。"""
    text = _on_disk()
    positions = []
    for task in daily_tasks.DAILY_TASKS:
        marker = f"（`{task.mode}`）"
        found = text.find(marker)
        assert found >= 0, (
            f"每日任务 {task.mode} 没有出现在 docs/STATUS.md 里。{REGENERATE_HINT}"
        )
        positions.append(found)
    assert positions == sorted(positions), (
        "docs/STATUS.md 里每日任务的顺序与 daily_tasks.DAILY_TASKS 不一致。"
        "顺序本身是业务规则（谁都可能被调整），文档必须跟着代码走。"
    )


def test_the_page_carries_no_timestamp() -> None:
    """除「在制品」一节外，生成物里不许写日期。

    写了就会「今天生成、明天过期」，比对将每天失败一次 —— 那是最劝退的设计，
    一旦发生，人就会开始习惯性手改文档，整套机制立刻失效。

    **在制品一节是例外**：那里显示的是交接单作者手写的 `started`，
    是内容而不是生成时间戳。真实的坑：第一版规则不区分，交接单一进目录就撞红。
    """
    text = _on_disk()
    start = text.find("## 二、在制品")
    end = text.find("## 三、")
    if start >= 0 and end > start:
        text = text[:start] + text[end:]
    for year in ("2025-", "2026-", "2027-"):
        assert year not in text, (
            f"docs/STATUS.md（「在制品」一节之外）出现了日期（{year}...）。"
            "这一页必须与时间无关，否则每天都会变成「过期状态」。"
            "需要写日期的地方是 CHANGELOG、docs/decisions/ 与交接单的 started 字段。"
        )


def test_rendering_twice_gives_the_same_text() -> None:
    """幂等：同一份代码渲染两次必须完全一致，否则比对无意义。"""
    assert gen_status.render() == gen_status.render()


def test_the_comparison_is_not_vacuous() -> None:
    """反向验证：把数据源换掉，渲染结果必须跟着变。

    没有这条，一个「永远返回同一个常量」的生成器也能让上面所有用例变绿。
    """
    baseline = gen_status.render()
    subset = catalog.ROUTES[:2]
    with mock.patch.object(catalog, "ROUTES", subset):
        shortened = gen_status.render()
    assert shortened != baseline, (
        "把 catalog.ROUTES 砍到 2 条之后，生成结果居然没变。"
        "说明 render() 没有真的读数据源 —— 一致性门禁变成了空转。"
    )


def test_a_route_dropped_from_the_registry_disappears_from_the_page() -> None:
    """反向验证（更具体）：少一条路线，表里就必须少那一行。"""
    dropped = catalog.ROUTES[0].mode
    with mock.patch.object(catalog, "ROUTES", catalog.ROUTES[1:]):
        text = gen_status.render()
    assert f"| `{dropped}` |" not in text, (
        f"从 catalog.ROUTES 里去掉 {dropped} 之后，生成结果里还留着它那一行。"
    )


def test_pc_only_routes_are_marked_unavailable_on_emulator() -> None:
    """仅 PC 的路线必须在「模拟器」一列写明不可用，不能写成可用。"""
    if not modes.PC_ONLY_ROUTES:
        pytest.skip("当前没有仅 PC 的路线")
    text = _on_disk()
    for mode in modes.PC_ONLY_ROUTES:
        line = next(
            (row for row in text.splitlines() if f"| `{mode}` |" in row), None
        )
        assert line is not None, f"{mode} 不在表格里。{REGENERATE_HINT}"
        assert "不可用（仅 PC）" in line, (
            f"{mode} 的表格行没有标「不可用（仅 PC）」：\n{line}\n"
            "仅 PC 的路线在模拟器后端下会被整条跳过，文档必须说清楚。"
        )


# ---------------------------------------------------------------- 在制品


def test_the_page_has_an_in_progress_section() -> None:
    """现状页必须有一节专门回答「有没有活没干完」。

    没有这一节时，STATUS 只能反映**已经合入代码的事实** —— 做到一半被中断的工作
    在页面上完全隐形，接手的人只能去翻未提交的 diff。
    """
    text = _on_disk()
    assert "## 二、在制品（进行中）" in text, (
        "docs/STATUS.md 里没有「在制品」一节。"
        "这一节是「进行中的工作」唯一的可见入口，不能被生成器漏掉。"
    )
    if not gen_status._wip_rows() or gen_status._wip_rows() == ["（当前没有未完成的工作）"]:
        assert "（当前没有未完成的工作）" in text, (
            "当前没有交接单，但现状页里既没列条目也没写「当前没有未完成的工作」，"
            f"读的人会以为这一节坏了。{REGENERATE_HINT}"
        )


def test_the_in_progress_section_lists_a_handover(tmp_path: Path) -> None:
    """反向验证：放进一份交接单，生成结果必须列出标题、状态与下一步。

    守的是「在制品」变成摆设：没有这条，一个永远输出「当前没有」的生成器
    也能让上面那条用例变绿。
    """
    note = tmp_path / "2026-11-08-demo-task.md"
    note.write_text(
        "---\n"
        "route: 演示\n"
        "status: in-progress\n"
        "owner: 测试\n"
        "started: 2026-11-08\n"
        "next_step: 先跑一轮竞技场看退出码\n"
        "---\n"
        "\n"
        "# 演示用交接单\n",
        encoding="utf-8",
    )

    joined = "\n".join(gen_status._wip_rows(tmp_path))

    assert "演示用交接单" in joined, "交接单的标题没有出现在「在制品」一节里"
    assert "in-progress" in joined, "交接单的状态没有出现"
    assert "先跑一轮竞技场看退出码" in joined, "下一步没有出现，接手的人不知道从哪开始"
    assert "2026-11-08-demo-task.md" in joined, "没有链到交接单本身"


def test_an_empty_in_progress_directory_says_so(tmp_path: Path) -> None:
    assert gen_status._wip_rows(tmp_path) == ["（当前没有未完成的工作）"]


def test_the_template_is_not_treated_as_a_handover(tmp_path: Path) -> None:
    """``_TEMPLATE.md`` 只是模板，不能被当成「有一份活的交接单」。"""
    (tmp_path / "_TEMPLATE.md").write_text(
        "---\nstatus: proposed\n---\n\n# 模板\n", encoding="utf-8"
    )
    assert gen_status._wip_rows(tmp_path) == ["（当前没有未完成的工作）"]


def test_an_untracked_local_frame_cannot_change_the_page(monkeypatch) -> None:
    """反向验证：本机多一张没入库的图，现状页不许跟着变。

    2026-11-09 真实事故：一张被 ``.gitignore`` 忽略的 2 MB 临时抓帧被数进现状页，
    本机 440 张 / 干净检出 439 张 —— 本机与提交钩子全绿，别人 clone 下来必红。
    """
    baseline = gen_status.render()
    probe_dir = ROOT / "tests" / "fixtures" / "_governance_probe"
    probe = probe_dir / "probe.png"
    probe_dir.mkdir(exist_ok=True)
    probe.write_bytes(b"not a real png")
    try:
        assert gen_status.render() == baseline, (
            "本机多一张未入库的图，现状页就变了 —— 假绿又回来了"
        )
    finally:
        probe.unlink(missing_ok=True)
        probe_dir.rmdir()

    # 反向：把它算进入库清单，数字必须变，否则上面那条是空转的。
    tracked = gen_status._tracked_pngs()
    monkeypatch.setattr(
        gen_status,
        "_tracked_pngs",
        lambda: tracked | {"tests/fixtures/_governance_probe/probe.png"},
    )
    assert gen_status.render() != baseline, (
        "入库清单多一张图，现状页却没变 —— 计数根本没在读入库清单"
    )


def test_the_fixture_number_is_independently_the_tracked_count() -> None:
    """用另一条 git 命令独立算一遍，防止生成器悄悄改回「数本机文件」。"""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "tests/fixtures/*.png"],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = len([name for name in result.stdout.splitlines() if name.strip()])
    assert f"现场夹具 **{expected}** 张" in _on_disk(), (
        "现状页的夹具数与 git 入库清单对不上 —— "
        "注意这一页只能描述仓库现状，不能描述本机目录"
    )


# ---------------------------------------------------------------- 按路线事实表


def _fact_cell(text: str, mode: str, column: int) -> str:
    """取按路线事实表某行某列：1=PC 图，2=模板合计，3=现场夹具。

    第一节表格行是 ``| 2 | `story` | ...``，不会与这里 ``| `story` |`` 开头混淆。
    """
    for line in text.splitlines():
        if line.startswith(f"| `{mode}` |"):
            return [cell.strip() for cell in line.split("|")][column + 1]
    raise AssertionError(f"按路线事实表里没有 {mode}")


def test_the_route_fact_table_lists_every_route() -> None:
    """手册要链这张表，就必须覆盖全部路线，不能静默少一行。"""
    text = _on_disk()
    section = text.split("### 按路线的现行事实")[1].split("## 六、")[0]
    for mode in modes.MODE_SPECS:
        assert f"| `{mode}` |" in section, f"按路线事实表漏了 {mode}"


def test_routes_with_nonstandard_template_roots_do_not_report_a_fake_zero() -> None:
    """`hero` 目录与「共享根」两处最容易按路线名猜出误导性的 0。

    2026-11-09 第一版就报了 arena 0 张 PC 图 —— 实际它有 8 张，只是混放在模板根。
    宁可写「共享根」，也不能给一个看起来精确、其实错的数字。
    """
    text = _on_disk()
    assert _fact_cell(text, "hero_synthesis", 1) != "0"
    assert _fact_cell(text, "hero_synthesis", 2) != "0"
    assert int(_fact_cell(text, "hero_synthesis", 3)) > 0
    assert _fact_cell(text, "arena", 1) == "共享根"
    assert int(_fact_cell(text, "arena", 3)) > 0


def test_the_route_pc_count_follows_the_tracked_images(monkeypatch) -> None:
    """加一张 PC 图，表里那条路线的数字自己 +1 —— 证明不是人抄的。"""
    baseline = gen_status.render()
    tracked = gen_status._tracked_pngs()
    extra = "games/epic7/templates/story/pc/__governance_probe.png"
    monkeypatch.setattr(gen_status, "_tracked_pngs", lambda: tracked | {extra})
    changed = gen_status.render()
    assert int(_fact_cell(changed, "story", 1)) == int(_fact_cell(baseline, "story", 1)) + 1


def test_overlapping_fixture_prefixes_go_to_the_right_route() -> None:
    """`epic7_story` 前缀既吞得到补星（别的路线），也吞得到 side_story 的变体。"""
    text = _on_disk()
    tracked = gen_status._tracked_pngs()
    story = sum(
        1
        for n in tracked
        if n.startswith("tests/fixtures/epic7_story")
        and not n.startswith("tests/fixtures/epic7_story_star")
        and n.endswith(".png")
    )
    star = sum(
        1
        for n in tracked
        if n.startswith("tests/fixtures/epic7_story_star") and n.endswith(".png")
    )
    side = sum(
        1
        for n in tracked
        if n.startswith("tests/fixtures/epic7_side_story") and n.endswith(".png")
    )
    assert star > 0
    assert int(_fact_cell(text, "story", 3)) == story
    assert int(_fact_cell(text, "story_star", 3)) == star
    assert int(_fact_cell(text, "side_story", 3)) == side
    # 反向：不排除会把补星数进主线；盲目加目录边界又会漏掉 side_story_boss。
    assert story != sum(
        1
        for n in tracked
        if n.startswith("tests/fixtures/epic7_story") and n.endswith(".png")
    )
    assert any(
        n.startswith("tests/fixtures/epic7_side_story_boss/") for n in tracked
    )

