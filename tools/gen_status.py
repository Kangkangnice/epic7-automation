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

import subprocess
from pathlib import Path

from auto_game_unified.desktop import catalog
from auto_game_unified.games.epic7 import daily_tasks, modes

#: 本文件所在包目录（``auto_game_unified``）。
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
#: 仓库内 ``docs/STATUS.md`` 的落点。
STATUS_PATH = PACKAGE_ROOT / "docs" / "STATUS.md"

#: 生成物的标题行。测试用它确认「被比对的文件确实是本脚本生成的」。
TITLE = "# 现状速查"


def _tracked_pngs() -> set[str]:
    """git 已跟踪的 png（相对包目录，统一用 ``/``）。

    ⚠️ 不能用 ``rglob`` 数本机文件：本机可能躺着被 ``.gitignore`` 忽略的临时抓帧
    （2026-11-09 就有一张 2 MB 的 ``tests/fixtures/_tmpcheck/_now.png``）。
    那样本机算出 440 张、干净检出只有 439 张 —— **本机和提交钩子全绿，别人 clone
    下来必红**。现状页描述的是仓库现状，唯一可信的口径就是入库清单。

    反过来，``_probe_wb_chest/`` 这种下划线开头的目录是**正式夹具**、确实入库了，
    所以也不能简单「排除下划线目录」。只有问 git 才能分清。

    打包产物不会调用本函数（现状页是开发期生成的静态文档），开发/CI 一定有 git；
    万一没有就 fail-closed 报错，绝不悄悄给一个可能错的数字。
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(PACKAGE_ROOT), "ls-files", "*.png"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "生成现状页需要 git（要读已入库素材清单）。"
            "打包产物不会调用本函数；开发/CI 环境一定有 git。原始错误：" + str(exc)
        ) from exc
    return {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }


def _count_under(directory: str, tracked: set[str]) -> int:
    prefix = directory.rstrip("/") + "/"
    return sum(1 for name in tracked if name.startswith(prefix) and name.endswith(".png"))


def _count_pc_templates(tracked: set[str]) -> int:
    """PC 专用模板的张数。

    注意有**两种**放法并存，不能用 ``**/pc/*.png`` 一个通配符：
    ``templates/<路线>/pc/x.png``（多数）与 ``templates/pc/<路线>/x.png``（早期那批）。
    漏掉后一种会让数字凭空少 9 张 —— 2026-11-08 第一次写就踩了。
    统一按「路径里有名为 pc 的目录段」判。
    """
    prefix = "games/epic7/templates/"
    return sum(
        1
        for name in tracked
        if name.startswith(prefix)
        and name.endswith(".png")
        and "pc" in name[len(prefix) :].split("/")[:-1]
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


#: 模板根不统一（2026-11-08 实测）。按路线名猜目录会给出**误导性的 0**，
#: 所以显式写清，并由 tests/test_status_doc.py 钉住「这两格不许退化成 0」。
#: 值 = (模板目录名, 夹具目录前缀)
ROUTE_DIR_ALIASES = {"hero_synthesis": ("hero", "epic7_hero")}
#: 夹具目录名有前缀包含关系时，显式声明「这些目录属于另一条路线」。
#: `epic7_story_star_pc/` 不能数进 `story`（2026-11-10 合并 main 时撞出：55 应为 45）；
#: 但不能简单加目录边界 —— `epic7_side_story_boss/` 是 `side_story` 自己的变体夹具。
ROUTE_FIXTURE_EXCLUDES: dict[str, tuple[str, ...]] = {
    "story": ("epic7_story_star",),
}
#: 竞技场模板与全局共享图混放在 templates/ 根、templates/pc/ 根，
#: 无法按路线归属 —— 宁可写「共享根」，也不要报一个假的 0。
SHARED_TEMPLATE_ROOT_ROUTES = frozenset({"arena"})


def _route_fact_rows(tracked: set[str]) -> list[str]:
    """按路线的现行事实。

    治理 V2：手册里凡「有几张 PC 图 / 几张模板 / 几张夹具」这类会漂移的数字，
    一律链到本表，不再手抄 —— 素材一入库、重生成本页，数字自己跟上。
    口径与 ``_count_pc_templates`` 一致：PC 图有两种放法
    ``templates/<路线>/pc/`` 与 ``templates/pc/<路线>/``，漏一种就会凭空少几张。
    """
    tmpl = "games/epic7/templates/"
    fixtures = "tests/fixtures/"
    rows = [
        "| 路线 | PC 专用图 | 模板合计 | 现场夹具 | 开局接力 | PC 放行 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for route in catalog.ROUTES:
        mode = route.mode
        directory, fixture_prefix = ROUTE_DIR_ALIASES.get(mode, (mode, f"epic7_{mode}"))
        if mode in SHARED_TEMPLATE_ROOT_ROUTES:
            pc_cell = template_cell = "共享根"
        else:
            in_route = [n for n in tracked if n.startswith(f"{tmpl}{directory}/") and n.endswith(".png")]
            in_pc_root = [n for n in tracked if n.startswith(f"{tmpl}pc/{directory}/") and n.endswith(".png")]
            pc_count = sum(1 for n in in_route if n.startswith(f"{tmpl}{directory}/pc/")) + len(in_pc_root)
            pc_cell = str(pc_count)
            template_cell = str(len(in_route) + len(in_pc_root))
        # 裸前缀能覆盖同路线的变体目录（如 epic7_side_story_boss/），
        # 但必须显式排除名字以它开头的**另一条路线**（story_star）。
        excludes = ROUTE_FIXTURE_EXCLUDES.get(mode, ())
        fixture_count = sum(
            1 for n in tracked
            if n.startswith(f"{fixtures}{fixture_prefix}")
            and n.endswith(".png")
            and not any(
                n.startswith(f"{fixtures}{excluded}") for excluded in excludes
            )
        )
        spec = modes.MODE_SPECS[mode]
        if not spec.needs_navigation:
            resume = "不适用（无导航）"
        elif spec.resume_probe is not None:
            resume = "有探针"
        elif mode in modes.RESUME_EXEMPT:
            resume = "豁免（见 modes.py）"
        else:
            resume = "**未表态**（加载期应拦下）"
        rows.append(
            f"| `{mode}` | {pc_cell} | {template_cell} | {fixture_count} "
            f"| {resume} | {_pc_state(mode)} |"
        )
    return rows


def render() -> str:
    """把当前代码的现状渲染成 Markdown 全文。

    不读磁盘上的 ``STATUS.md``，只读代码、入库素材清单与在制品交接单，
    所以可以反复调用比对，且与干净检出的结果一致。
    """
    tracked = _tracked_pngs()
    templates = _count_under("games/epic7/templates", tracked)
    pc_templates = _count_pc_templates(tracked)
    fixtures = _count_under("tests/fixtures", tracked)

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
        "- **模拟器**：「不可用（仅 PC）」表示这条路线只有 PC 素材；界面勾选时只跳过它自己，",
        "  每日任务连打里记 `not_supported`，都不算失败。",
        "- **PC 客户端**：界面只放行 `desktop/catalog.PC_READY_ROUTES` 里的路线；",
        "  勾到没放行的路线也只跳过那一条、其余照跑（日志会说明），全不可用才报错。",
        "  命令行 `--window-backend pc` 不受这层限制。",
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
        "### 按路线的现行事实（自动生成）",
        "",
        "> 路线手册里**不要再手抄**「有几张 PC 图 / 几张模板 / 几张夹具」，链到本表即可。",
        "> 口径：模板只数 `games/epic7/templates/<路线>/` 与 `templates/pc/<路线>/`；",
        "> 夹具数 `tests/fixtures/epic7_<路线>` 前缀（含 `epic7_<路线>_pc/` 等变体目录）；"
        "若与另一条路线重名前缀，在 `ROUTE_FIXTURE_EXCLUDES` 显式排除。",
        "> `hero_synthesis` 的素材目录叫 `hero`；`arena` 的模板与全局共享图混放在模板根，",
        "> 无法按路线归属，标「共享根」而不是报一个假的 0 —— 别名见 `gen_status.py::ROUTE_DIR_ALIASES`。",
        "> 开局接力读 `MODE_SPECS.resume_probe` 与 `RESUME_EXEMPT`，PC 放行读 `PC_READY_ROUTES`。",
        "",
        *_route_fact_rows(tracked),
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
