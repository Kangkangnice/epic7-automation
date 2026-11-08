"""生成 ``docs/STATUS.md`` —— 项目现状的**唯一手可查**入口。

用法（在**工作区根**执行，不是包目录）：:

    python -m auto_game_unified.tools.gen_status

为什么要有这个东西
------------------
「文档说 16 条路线、代码已经是 17 条」这类漂移，靠人记是治不住的。这里把能算出来的
事实**全部从代码算**：路线名单、分组、默认次数、PC 放行情况、每日任务顺序、素材规模。
写进 ``docs/STATUS.md`` 之后，由 ``tests/test_status_doc.py`` 逐字比对 —— 谁忘了重生成，
门禁直接红并告诉他跑哪条命令。

维护纪律（重要）
----------------
1. **不要手改 ``docs/STATUS.md``**：它会在下次门禁时被打回。
2. 加了一条路线 / 一张模板 / 一张夹具之后跑一次本脚本，把重生成结果一起提交。
3. 本文件不写时间戳：写了就会每天自我失效，比对将永远失败。

改了本脚本要做的事
------------------
``tests/test_status_doc.py`` 里有一组**反向用例**（桩掉数据源，断言生成结果会跟着变、
且关键段落不会变成空的）。改完请连它一起跑：

    python -m pytest -q auto_game_unified/tests/test_status_doc.py
"""

from __future__ import annotations

from pathlib import Path

from auto_game_unified.desktop import catalog
from auto_game_unified.games.epic7 import daily_tasks, modes

#: 本文件所在包目录（``auto_game_unified``）。
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
#: 仓库内 ``docs/STATUS.md`` 的落点。
STATUS_PATH = PACKAGE_ROOT / "docs" / "STATUS.md"

#: 生成物的标题行。测试用它确认「被比对的文件确实是本脚本生成的」。
TITLE = "# 现状速查"


def _count(pattern: str) -> int:
    return sum(1 for _ in PACKAGE_ROOT.glob(pattern))


def _count_pc_templates() -> int:
    """PC 专用模板的张数。

    注意有**两种**放法并存，不能用 ``**/pc/*.png`` 一个通配符：
    ``templates/<路线>/pc/x.png``（多数）与 ``templates/pc/<路线>/x.png``（早期那批）。
    漏掉后一种会让数字凭空少 9 张 —— 2026-11-08 第一次写就踩了。
    统一按「路径里有名为 pc 的目录段」判。
    """
    root = PACKAGE_ROOT / "games" / "epic7" / "templates"
    return sum(1 for path in root.rglob("*.png") if "pc" in path.relative_to(root).parts)


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


def _cell(value: str) -> str:
    """表格单元里不能出现裸竖线。"""
    return value.replace("|", "/").strip() or "—"


def _wip_rows(directory: Path | None = None) -> list[str]:
    """在制品一节的内容。

    只看 ``started`` 字段、**不看文件 mtime** —— 一次 ``git clone`` 或 ``checkout``
    会把所有 mtime 刷成当下，那样生成结果就不可复现，比对会永远失败。

    ``directory`` 只为测试留口（用临时目录验证「有条目 / 没条目」两种输出），
    正常调用不传。
    """
    if directory is None:
        directory = PACKAGE_ROOT / "docs" / "wip"
    entries = []
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        fields = _frontmatter(text)
        title = next(
            (line[2:].strip() for line in text.splitlines() if line.startswith("# ")),
            path.stem,
        )
        entries.append((path, title, fields))
    if not entries:
        return ["（当前没有未完成的工作）"]
    rows = [
        "| 主题 | 状态 | 开始 | 下一步 |",
        "|---|---|---|---|",
    ]
    for path, title, fields in entries:
        link = f"[{_cell(title)}](wip/{path.name})"
        rows.append(
            f"| {link} | {_cell(fields.get('status', ''))} "
            f"| {_cell(fields.get('started', ''))} "
            f"| {_cell(fields.get('next_step', ''))} |"
        )
    return rows


def _pc_state(mode: str) -> str:
    if mode in catalog.PC_READY_ROUTES:
        return "已放行"
    return "未放行"


def _emulator_state(mode: str) -> str:
    if mode in modes.PC_ONLY_ROUTES:
        return "不可用（仅 PC）"
    return "可用"


def _route_table() -> list[str]:
    rows = [
        "| # | 路线 | 界面名称 | 分组 | 默认次数 | 次数可改 | 有导航 | 模拟器 | PC 客户端 |",
        "|---|------|---------|------|---------|---------|-------|-------|----------|",
    ]
    specs = modes.MODE_SPECS
    for index, route in enumerate(catalog.ROUTES, start=1):
        spec = specs[route.mode]
        cycles = spec.default_cycles if spec.default_cycles is not None else "—"
        editable = "是" if spec.cycles_editable else "否"
        navigation = "是" if spec.needs_navigation else "否"
        rows.append(
            f"| {index} | `{route.mode}` | {spec.label} | {route.group} | {cycles} "
            f"| {editable} | {navigation} | {_emulator_state(route.mode)} "
            f"| {_pc_state(route.mode)} |"
        )
    return rows


def _daily_lines() -> list[str]:
    lines = []
    for index, task in enumerate(daily_tasks.DAILY_TASKS, start=1):
        label = modes.MODE_SPECS[task.mode].label
        lines.append(f"{index}. {label}（`{task.mode}`）")
    return lines


def _pc_only_lines() -> list[str]:
    if not modes.PC_ONLY_ROUTES:
        return ["（目前没有仅 PC 的路线）"]
    return [
        f"- {modes.MODE_SPECS[mode].label}（`{mode}`）"
        for mode in sorted(modes.PC_ONLY_ROUTES)
    ]


def render() -> str:
    """把当前代码的现状渲染成 Markdown 全文。

    纯函数：不读磁盘上的 ``STATUS.md``，只读代码与素材目录，所以可以反复调用比对。
    """
    templates = _count("games/epic7/templates/**/*.png")
    pc_templates = _count_pc_templates()
    fixtures = _count("tests/fixtures/**/*.png")

    parts: list[str] = [
        TITLE,
        "",
        "> 本页由 `python -m auto_game_unified.tools.gen_status` 从代码生成，**不要手改**。",
        "> 门禁 `tests/test_status_doc.py` 会逐字比对：与代码不一致就直接报红。",
        "> 想知道「现在到底支持哪些、哪些放行了」，只看这一页就够。",
        "",
        f"**产品**：{catalog.PRODUCT_NAME} v{catalog.PRODUCT_VERSION}",
        "",
        f"## 一、路线总览（共 {len(catalog.ROUTES)} 条）",
        "",
        *_route_table(),
        "",
        "图例与口径：",
        "",
        "- **模拟器**：「不可用（仅 PC）」表示这条路线只有 PC 素材，模拟器后端下整条跳过，",
        "  汇总里记 `not_supported`，不算失败。",
        "- **PC 客户端**：只有 `desktop/catalog.PC_READY_ROUTES` 里的路线才会出现在界面上；",
        "  其余路线选了会被拦下并说明原因。命令行 `--window-backend pc` 不受这层限制。",
        "- **默认次数**：界面上预填的值，`-` 表示该路线没有次数概念。",
        "",
        "## 二、在制品（进行中）",
        "",
        "> 这一节一旦有条目，说明**有工作没做完**。每份交接单在 [`docs/wip/`](wip/)，",
        "> 合并进 main 之后要删掉。开工做到一半要停时，复制",
        "> [`wip/_TEMPLATE.md`](wip/_TEMPLATE.md) 建一份 —— 见 `AGENTS.md`「做到一半要停」。",
        "",
        *_wip_rows(),
        "",
        f"## 三、每日任务的执行顺序（共 {len(daily_tasks.DAILY_TASKS)} 条）",
        "",
        "界面上「每日」分组按下表从上到下执行；每段之间会先确认回到大厅再开下一条。",
        "",
        *_daily_lines(),
        "",
        "## 四、仅 PC 的路线",
        "",
        *_pc_only_lines(),
        "",
        "## 五、素材与测试规模",
        "",
        f"- 识别模板 **{templates}** 张，其中 PC 专用 **{pc_templates}** 张",
        f"- 现场夹具 **{fixtures}** 张（`tests/fixtures/`，跑测试用的真实截图）",
        "",
        "注意：这两个数字**加一张图就要重生成一次**。这是有意的 —— 素材入库本来就要在",
        "`tests/test_template_paths.py` 登记，多跑一次生成器只是同一步的延续。",
        "测试文件个数刻意不写在这里：它每天都在变，写进来只会让这一页天天过期。",
        "",
        "## 六、这一页之外去哪找",
        "",
        "- 文档索引与「我该看哪一份」：[`docs/README.md`](README.md)",
        "- 为什么当初这么定：[`docs/decisions/`](decisions/)",
        "- 每条路线怎么维护：[`docs/maintenance/`](maintenance/)",
        "- 改了什么：[`CHANGELOG.md`](../CHANGELOG.md)",
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    text = render()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 统一用 LF 写盘：CRLF 会让「同一份内容」在不同机器上比对失败。
    STATUS_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"已生成 {STATUS_PATH}")
    print(f"路线 {len(catalog.ROUTES)} 条，每日任务 {len(daily_tasks.DAILY_TASKS)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
