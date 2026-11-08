"""文档治理门禁：索引即白名单、不许断链、决策记录要有元数据。

为什么这三条要写成测试而不是写进文档
------------------------------------
「新增文档要登记」这种约定，靠人记是记不住的，AI agent 更是每次从零开始。
唯一可靠的办法是让它**做不到**：没登记就红，红的时候报错信息直接告诉他该改哪个文件。

另外两条是配套的：断链检查防「删了文件忘了改链接」，
决策记录元数据检查防「一堆没有状态、不知道还算不算数的记录」——
后者正是这次清理掉的 108 份旧文档的病根。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"

#: 索引里必须覆盖到的文档：``docs/`` 下所有 ``.md``，除了索引自己与 ``_`` 开头的模板。
_SKIP_NAMES = {"README.md"}

#: 交接单目录：不进索引白名单，改由 ``docs/STATUS.md`` 的「在制品」一节兜底。
WIP_DIR = DOCS / "wip"

#: 交接单允许的状态（与 ``wip/_TEMPLATE.md`` 一致）。``done`` 不在其中是故意的：
#: 做完了就该删掉这份交接单，而不是把它标成完成继续留着。
WIP_STATUS = {"in-progress", "blocked", "abandoned"}

#: 决策记录允许的状态（与 ``_TEMPLATE.md`` 里写的一致）。
ALLOWED_STATUS = {"proposed", "accepted", "superseded", "deprecated", "rejected"}

_LINK = re.compile(r"\]\(([^)]+)\)")


def _markdown_links(text: str) -> list[str]:
    """抽出 Markdown 里的相对链接目标（丢掉外链、纯锚点、非 md）。"""
    targets = []
    for raw in _LINK.findall(text):
        target = raw.split(" ", 1)[0].strip()
        if not target or target.startswith("#"):
            continue
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        targets.append(target.split("#", 1)[0])
    return targets


def _indexed_paths(index_text: str) -> set[Path]:
    """索引里点到的文件，全部解析成绝对路径。"""
    resolved = set()
    for target in _markdown_links(index_text):
        # 索引里只关心文档；图片之类也一并解析，不存在同样该报。
        resolved.add((INDEX.parent / target).resolve())
    return resolved


def _required_docs() -> list[Path]:
    """需要登记在索引里的文档。

    排除三类：索引自己、``_`` 开头的模板、以及 ``docs/wip/`` 下的交接单 ——
    交接单是临时凭证，它的归宿是 `docs/STATUS.md` 的「在制品」一节（自动生成），
    不该因为开一份活就要去改索引、干完再改回来。
    """
    return sorted(
        path
        for path in DOCS.rglob("*.md")
        if path.name not in _SKIP_NAMES
        and not path.name.startswith("_")
        and WIP_DIR not in path.parents
    )


def _unindexed(files: list[Path], index_text: str) -> list[str]:
    """哪些文档没被索引点到。抽成函数是为了能拿假数据做反向验证。"""
    covered = _indexed_paths(index_text)
    return [str(path.relative_to(ROOT)) for path in files if path.resolve() not in covered]


def _broken_links(source: Path) -> list[str]:
    """某个文档里指向不存在的本地文件的链接。"""
    broken = []
    for target in _markdown_links(source.read_text(encoding="utf-8")):
        if (source.parent / target).resolve().exists():
            continue
        broken.append(f"{source.relative_to(ROOT)} -> {target}")
    return broken


# ---------------------------------------------------------------- 索引即白名单


def test_every_doc_is_reachable_from_the_index() -> None:
    """``docs/`` 下每个文档都必须能在 ``docs/README.md`` 里点到。

    这条就是「新增文档必须表态」的执行机构。红了的处理办法只有一个：
    在索引里给它找一行，而找行的过程必然要回答「这是哪一类文档」。
    """
    missing = _unindexed(_required_docs(), INDEX.read_text(encoding="utf-8"))
    assert not missing, (
        "下面这些文档没有登记在 docs/README.md 里：\n  "
        + "\n  ".join(missing)
        + "\n\n请打开 docs/README.md，判断它属于哪一类（现状 / 决策 / 过程 / 存档），"
        "然后在对应表格里加一行链接。\n"
        "如果它其实是一次性的交接说明或施工计划 —— 不要登记，直接删掉，"
        "把信息拆进提交信息、CHANGELOG 或 docs/decisions/。"
    )


def test_the_index_has_no_broken_links() -> None:
    """索引里点到的文件必须真的存在（防止删了文件忘了改链接）。"""
    broken = _broken_links(INDEX)
    assert not broken, (
        "docs/README.md 里这些链接指向不存在的文件：\n  " + "\n  ".join(broken)
    )


def test_no_doc_points_at_a_missing_file() -> None:
    """所有文档的相对链接都要能落地。

    只查仓库内的相对链接；外链（http/https）不查 —— 那种检查需要联网，
    会让门禁变得不稳定，而它要防的「删了文件忘了改链接」本地就能查。
    """
    problems: list[str] = []
    for path in [INDEX, *sorted(DOCS.rglob("*.md")), ROOT / "AGENTS.md"]:
        if not path.exists():
            continue
        problems.extend(_broken_links(path))
    assert not problems, (
        "这些相对链接指向不存在的文件：\n  " + "\n  ".join(sorted(set(problems)))
    )


def test_the_whitelist_would_catch_a_stray_doc() -> None:
    """反向验证：塞一个没登记的文档进列表，检查必须报出来。

    没有这条，一个永远返回空列表的 ``_unindexed`` 也能让上面全绿。
    """
    stray = DOCS / "decisions" / "9999-not-registered.md"
    index_text = INDEX.read_text(encoding="utf-8")
    caught = _unindexed([*_required_docs(), stray], index_text)
    assert any("9999-not-registered" in item for item in caught), (
        "反向验证失败：一个没登记的文件没有被 _unindexed 报出来，"
        "说明白名单检查是空转的。"
    )


# ---------------------------------------------------------------- 决策记录


def _decision_files() -> list[Path]:
    return sorted(
        path
        for path in (DOCS / "decisions").glob("*.md")
        if not path.name.startswith("_")
    )


def _frontmatter(text: str) -> dict[str, str]:
    """解析极简 YAML frontmatter（只支持 ``key: value`` 单行）。"""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def test_decision_records_carry_metadata() -> None:
    """每份决策记录都要有 status 与 date，且状态在允许集合里。

    为什么必须是机器检查：这次清理掉的 108 份旧文档，病根就是「没人知道还算不算数」。
    状态字段就是回答这个问题的。
    """
    problems = []
    for path in _decision_files():
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT)
        if not fields:
            problems.append(f"{relative}: 缺 frontmatter（应以 --- 开头写 status / date）")
            continue
        status = fields.get("status", "")
        if status not in ALLOWED_STATUS:
            problems.append(
                f"{relative}: status={status!r} 不合法，只能是 {sorted(ALLOWED_STATUS)}"
            )
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields.get("date", "")):
            problems.append(f"{relative}: date 缺失或不是 YYYY-MM-DD")
    assert not problems, (
        "决策记录元数据有问题：\n  " + "\n  ".join(problems) + "\n\n"
        "照 docs/decisions/_TEMPLATE.md 补齐即可。"
    )


def test_decision_files_are_numbered_in_order() -> None:
    """文件名必须是 ``NNNN-英文短名.md``，编号不重复。"""
    seen: dict[str, Path] = {}
    problems = []
    for path in _decision_files():
        match = re.fullmatch(r"(\d{4})-([a-z0-9-]+)\.md", path.name)
        if not match:
            problems.append(f"{path.name}: 文件名应为 0001-some-slug.md（小写英文与连字符）")
            continue
        number = match.group(1)
        if number in seen:
            problems.append(f"编号 {number} 重复：{seen[number].name} 与 {path.name}")
        seen[number] = path
    assert not problems, "\n".join(problems)


def test_superseded_records_point_somewhere() -> None:
    """标了 ``superseded`` 的记录必须写清被谁取代，否则等于没交代。"""
    problems = []
    for path in _decision_files():
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        if fields.get("status") != "superseded":
            continue
        if not fields.get("superseded_by"):
            problems.append(f"{path.name}: status 是 superseded，但 superseded_by 是空的")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------- 首页不许抄数字

#: 只盯这两个「人一进来就看」的页面。其余文档里的历史表述（带日期的「当时十五条」）
#: 是正当的，不该被这条规则误伤。
_FRONT_PAGES = (ROOT / "README.md", DOCS / "README.md")

#: 「N 条路线」「共 **N 条**」这两种写法。数字写死就一定会过期。
_ROUTE_COUNT = re.compile(r"\d+\s*条路线|共\s*\*\*\d+\s*条\*\*")


def test_the_front_pages_do_not_hardcode_route_counts() -> None:
    """首页不许抄路线条数，一律链 ``STATUS.md``。

    这是本次治理前真实踩过的坑：README 写着「共 17 条 / 13 条放行」，
    而代码里随时会变成 18 条。首页是最多人看的地方，也是过期代价最高的地方。
    允许的写法：「具体条数与 PC 放行名单见 STATUS.md」。
    """
    problems = []
    for page in _FRONT_PAGES:
        if not page.exists():
            continue
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            match = _ROUTE_COUNT.search(line)
            if match:
                problems.append(f"{page.relative_to(ROOT)}:{number}  {match.group(0)!r}")
    assert not problems, (
        "首页写死了路线条数，这些数字一定会过期：\n  " + "\n  ".join(problems) + "\n\n"
        "改成「具体条数与 PC 放行名单见 docs/STATUS.md」这种写法 —— "
        "那一页由代码生成，永远不会过期。"
    )


# ---------------------------------------------------------------- 在制品交接单


def _wip_files(directory: Path | None = None) -> list[Path]:
    directory = WIP_DIR if directory is None else directory
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.md") if not path.name.startswith("_"))


def _metadata_problems(files: list[Path]) -> list[str]:
    """交接单元数据的问题清单。抽成函数是为了能拿临时目录做反向验证。"""
    problems = []
    for path in files:
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        if not fields:
            problems.append(f"{path.name}: 缺 frontmatter")
            continue
        missing = [
            key
            for key in ("route", "status", "owner", "started", "next_step")
            if not fields.get(key)
        ]
        if missing:
            problems.append(f"{path.name}: 缺字段 {missing}")
        if fields.get("status") and fields["status"] not in WIP_STATUS:
            problems.append(
                f"{path.name}: status={fields['status']!r} 不合法，"
                f"只能是 {sorted(WIP_STATUS)}"
            )
        if fields.get("started") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields["started"]):
            problems.append(f"{path.name}: started 不是 YYYY-MM-DD")
    return problems


def test_handover_notes_carry_metadata() -> None:
    """每份交接单都要写清「谁 / 什么状态 / 什么时候开始 / 下一步」。

    这不是形式主义：交接单的唯一用途就是让**下一个人**接手，
    而这四项缺任何一项，接手的人都得先去问一圈。
    """
    problems = _metadata_problems(_wip_files())
    assert not problems, (
        "交接单元数据有问题：\n  " + "\n  ".join(problems) + "\n\n"
        "照 docs/wip/_TEMPLATE.md 补齐即可。做完的工作请直接删掉交接单，"
        "不要标成 done 留着。"
    )


def test_a_half_filled_handover_is_caught(tmp_path: Path) -> None:
    """反向验证：缺 ``next_step`` 或状态写错的交接单必须被报出来。

    没有这条，上面那条在「还没有交接单」时是空转的 —— 等第一次真有人用到，
    才会发现规则根本没生效。
    """
    (tmp_path / "2026-11-08-bad.md").write_text(
        "---\nroute: 演示\nstatus: done\nstarted: 2026/11/08\n---\n\n# 坏例子\n",
        encoding="utf-8",
    )

    problems = _metadata_problems(_wip_files(tmp_path))

    assert any("缺字段" in item for item in problems), f"没报出缺字段：{problems}"
    assert any("不合法" in item for item in problems), f"没报出非法状态：{problems}"
    assert any("started" in item for item in problems), f"没报出日期格式：{problems}"


def test_handover_file_names_start_with_a_date() -> None:
    """文件名必须是 ``YYYY-MM-DD-英文短名.md``，按名字就能看出先后。"""
    problems = []
    for path in _wip_files():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", path.name):
            problems.append(path.name)
    assert not problems, (
        "这些交接单的文件名不合规（应为 2026-11-08-some-task.md）：\n  "
        + "\n  ".join(problems)
    )
