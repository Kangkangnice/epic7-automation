"""生成「工作区根目录待清理清单」。只读，不删任何东西。

产物：auto_game_unified/docs/WORKSPACE_TIDY.md

用法（任意目录均可，路径按脚本自身位置推导）：
    D:\\anaconda\\python.exe auto_game_unified/tools/report_workspace_tidy.py

清完某批文件后可以重跑，清单会自动更新；跑完不用提交清单的差异也行，
它只是给人看的。
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = PACKAGE_DIR.parent
ROOT = str(WORKSPACE_DIR)
REPO = PACKAGE_DIR.name
REPO_TEMPLATES = str(PACKAGE_DIR / "games" / "epic7" / "templates")
OUT = str(PACKAGE_DIR / "docs" / "WORKSPACE_TIDY.md")


def md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def size_text(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def mtime(path: str) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))


def classify(name: str) -> str:
    """把根目录文件归到清理类别。返回类别名。"""
    if name.startswith(("_ocr", "_fix", "_t__", "_crop", "_debug")):
        return "A1"
    if name.startswith("_") and name.endswith(".py"):
        return "A2"
    if name.startswith("_") and name.endswith((".txt", ".tsv")):
        return "A3"
    if name.startswith("_") and name.endswith(".png"):
        return "A4"
    if name.startswith("_") and name.endswith(".ps1"):
        return "A5"
    if name.startswith("_"):
        return "A6"
    if name.startswith(("tmp_",)) or name in {
        "run_final.py",
        "run_fix.py",
        "run_ocr.py",
        "run_ocr2.py",
        "analyze_assist_auto.py",
        "write_ps1.py",
        ".py",
    }:
        return "C"
    if name.endswith(".md"):
        return "E"
    if (
        name.startswith(("pc_", "roi_"))
        or name in {"current_state.png", "temp_screenshot.png", "hi_strip.png"}
        or name.endswith(".png")
    ):
        return "B"
    return "F"


CATEGORY_META = {
    "A1": ("OCR / 模板调参中间图", "跑 OCR 与模板增强时批量导出的 bw/inv/otsu 版本，全部可再生"),
    "A2": ("一次性探针脚本（`_*.py`）", "为定位某个具体问题临时写的脚本，结论已进入正式代码或文档"),
    "A3": ("探针输出文本（`_*.txt` / `_*.tsv`）", "探针脚本的 stdout 落盘"),
    "A4": ("其他临时图（`_*.png`）", "裁剪/标注用的中间图"),
    "A5": ("临时 PowerShell 脚本（`_*.ps1`）", "调用 Windows OCR 的临时脚本"),
    "A6": ("其他下划线文件", "以 `_` 开头的杂项"),
    "B": ("顶层截图与 ROI 切片", "模拟器/PC 客户端整屏截图与局部切片，体积占大头"),
    "C": ("根目录散落脚本", "没有 `_` 前缀但同样是一次性脚本，位置不对（正式脚本应在 tools/）"),
    "E": ("根目录文档", "一次修复的交接说明，内容可能值得并入 docs/"),
    "F": ("未归类", "需人工看一眼"),
}

DIR_NOTES = {
    ".workbuddy": (
        "⛔ 绝对不要删",
        "WorkBuddy 的项目数据与记忆目录（memory/、skills/ 等）。删掉会丢项目长期记忆与技能，"
        "它不是缓存。",
    ),
    ".tools": (
        "工具缓存（待确认）",
        "24.4 MB，体积最大。疑为外部工具/解释器的缓存目录，删前先确认是谁在用。",
    ),
    ".trae": ("IDE 配置", "外部 IDE（Trae）的工程配置，与自动化项目无关，可留可删看你还用不用。"),
    ".pytest_cache": ("pytest 缓存", "跑测试留下的缓存，可再生。删了下次跑测试会重建。"),
    "_walk": ("空目录", "可直接删。目录名为空，0 个文件。"),
    "docs": ("空目录", "工作区根的 docs/ 是空的；真正的文档目录是 auto_game_unified/docs/。可直接删。"),
    "runtime_logs": (
        "临时输出",
        "排查期间写的临时脚本与输出（工作区根不是仓库，不被 git 跟踪）；"
        "真正的运行日志目录是 auto_game_unified/runtime_logs/。删掉不影响程序。",
    ),
    "templates_backup_20260829_1854": (
        "模板历史快照",
        "19 个条目 / 114 个文件。与仓库当前模板：相同 92、不一致 16、仓库已删 6。",
    ),
    "templates_用户修改版_20260829": (
        "疑似未合并的手工改动",
        "16 张，与仓库版本全部不一致，且与该备份目录里的版本完全一致。",
    ),
    "tools": ("PC 客户端截图工具链", "16 个条目 / 4.8 MB，含正式脚本，见下方专节。"),
}


def collect() -> dict[str, list[tuple[str, int, str]]]:
    buckets: dict[str, list[tuple[str, int, str]]] = {}
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        buckets.setdefault(classify(name), []).append(
            (name, os.path.getsize(path), mtime(path))
        )
    return buckets


def dir_table() -> list[tuple[str, str, int, int]]:
    rows = []
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if not os.path.isdir(path) or name == REPO:
            continue
        count = total = 0
        for cur, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    total += os.path.getsize(os.path.join(cur, fname))
                    count += 1
                except OSError:
                    pass
        rows.append((name, path, count, total))
    return rows


def compare_user_templates() -> list[tuple[str, str, str]]:
    """用户修改版 vs 仓库 vs 备份，逐文件给结论。"""
    user = os.path.join(ROOT, "templates_用户修改版_20260829")
    bak = os.path.join(ROOT, "templates_backup_20260829_1854")
    rows = []
    if not os.path.isdir(user):
        return rows
    for cur, _dirs, files in os.walk(user):
        for fname in sorted(files):
            path = os.path.join(cur, fname)
            rel = os.path.relpath(path, user).replace("\\", "/")
            repo_path = os.path.join(REPO_TEMPLATES, rel.replace("/", os.sep))
            bak_path = os.path.join(bak, rel.replace("/", os.sep))
            same_bak = (
                "是"
                if os.path.exists(bak_path) and md5(path) == md5(bak_path)
                else "否"
            )
            if not os.path.exists(repo_path):
                repo_state = "仓库缺此图"
            elif md5(path) == md5(repo_path):
                repo_state = "一致"
            else:
                repo_state = "不一致"
            rows.append((rel, repo_state, same_bak))
    return rows


def tools_listing() -> list[tuple[str, str, str]]:
    out = []
    tool_dir = os.path.join(ROOT, "tools")
    if not os.path.isdir(tool_dir):
        return out
    for name in sorted(os.listdir(tool_dir)):
        path = os.path.join(tool_dir, name)
        if os.path.isdir(path):
            out.append((name, "<dir>", ""))
        else:
            out.append((name, size_text(os.path.getsize(path)), mtime(path)))
    return out


def render() -> str:
    buckets = collect()
    lines: list[str] = []
    add = lines.append

    total_files = sum(len(v) for v in buckets.values())
    total_bytes = sum(s for v in buckets.values() for _n, s, _m in v)

    add("# 工作区根目录待清理清单")
    add("")
    add("> 本文件由 `tools/report_workspace_tidy.py` 生成，**只读扫描，没有删除或移动任何文件**。")
    add("")
    add(f"- 扫描目录：`D:\\AI\\codex\\auto_game`（工作区根）")
    add(f"- 根目录文件：**{total_files} 个，合计 {size_text(total_bytes)}**")
    add(f"- 根目录子目录：见「子目录」一节")
    add(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M')}")
    add("")
    add("## 先说一句要紧的")
    add("")
    add("工作区根 `D:\\AI\\codex\\auto_game` **不是 git 仓库**，仓库根是 `auto_game_unified/`。")
    add("所以这些文件全都没有版本记录 —— 删掉就真没了，没有 `git checkout` 可以捞回来。")
    add("这也是为什么本清单只清点、不动手。")
    add("")
    add("还有一条要先说：根目录下的 **`.workbuddy/` 绝对不能删**。")
    add("它是项目数据与记忆目录（`memory/`、`skills/` 等），不是缓存；")
    add("删掉会丢项目长期记忆和已沉淀的经验，没有任何办法恢复。")
    add("")
    add("## 风险分级")
    add("")
    add("| 级别 | 对象 | 数量 | 说明 | 建议 |")
    add("| --- | --- | --- | --- | --- |")
    add(
        "| **L0 可删** | 根目录 `_*` 探针脚本与输出（类别 A1–A6） | "
        f"{sum(len(buckets.get(k, [])) for k in ('A1','A2','A3','A4','A5','A6'))} | "
        "为定位具体问题临时产出，结论已进正式代码/文档 | 确认后可整批删 |"
    )
    root_logs_files = 0
    root_logs_dir = os.path.join(ROOT, "runtime_logs")
    if os.path.isdir(root_logs_dir):
        for _dirpath, _dirnames, _filenames in os.walk(root_logs_dir):
            root_logs_files += len(_filenames)
    add(
        "| **L0 可删** | 空目录 + 根 `runtime_logs` | "
        f"{2 + root_logs_files} | `_walk`、`docs` 是空的；根 `runtime_logs` 里有 "
        f"{root_logs_files} 个临时文件（含子目录） | 确认后可删 |"
    )
    add(
        "| **L1 需你确认** | `templates_用户修改版_20260829` | 16 | "
        "与仓库版本**全部不一致**，疑似 08-29 手工改过但没进仓库 | **先看图再决定**，见下 |"
    )
    add(
        "| **L2 需你确认** | `templates_backup_20260829_1854` | 114 | 改版前的模板快照，仓库已有 92 张与它一致 | 可留作回滚点，或移入归档 |"
    )
    add(
        "| **L3 别当垃圾** | 根 `tools/` | 16 | PC 客户端截图工具链，**含正式脚本** | 建议搬进仓库，不是删 |"
    )
    add(
        "| **L4 需你确认** | 顶层截图与 ROI 切片（类别 B）、根目录散落脚本（类别 C） | "
        f"{len(buckets.get('B', [])) + len(buckets.get('C', []))} | "
        "体积占大头；脚本位置不对 | 看一眼再删 |"
    )
    add("")

    add("## L1：那 16 张「用户修改版」模板要紧在哪")
    add("")
    add("`templates_用户修改版_20260829/` 里的 16 张图，与仓库当前版本**一张都不相同**，")
    add("而与同级的 `templates_backup_20260829_1854/` 里的版本**完全一致**。")
    add("仓库里这些图的最后一次提交是 `e07bd9a`（08-21），而这批图的文件时间是 08-29 18:34–18:52。")
    add("")
    add("两种可能，需要你看图判断：")
    add("")
    add("1. **这批手工改动没进仓库** → 那它是有效工作，应该对比后合并，不能删；")
    add("2. **当时试过手工重新抠图，效果不好又退回了原版** → 那它只是过程产物，可以删。")
    add("")
    add("按项目里的视觉锚点经验，手工重新抠的模板很容易丢掉「排他性」，")
    add("所以第二种解释更可能 —— 但这是**推测**，需要你确认。**在你确认之前我不动它。**")
    add("")
    add("| 相对路径 | 与仓库 | 与备份 |")
    add("| --- | --- | --- |")
    for rel, repo_state, same_bak in compare_user_templates():
        add(f"| `{rel}` | {repo_state} | {same_bak} |")
    add("")

    add("## L3：根 `tools/` 里有什么")
    add("")
    add("| 文件 | 体积 | 时间 |")
    add("| --- | --- | --- |")
    for name, size, mtime_text in tools_listing():
        add(f"| `{name}` | {size} | {mtime_text} |")
    add("")
    add("`capture_pc_templates.py`（19.7 KB）是 PC 客户端的模板采集脚本，")
    add("`measure_pc_window.py`、`fill_pc_placeholders.py`、`capture_single.py` 也是正式工具。")
    add(f"仓库内 `{REPO}/tools/` 目前只有 `capture_fixture.py`、`check.py`、`check_evidence.py`、")
    add("`refit_text_anchor.py` 等，**没有 PC 采集这一套**。")
    add("所以建议是搬进仓库并纳入版本管理，而不是删。")
    add("")

    add("## 子目录")
    add("")
    add("| 目录 | 文件数 | 体积 | 性质 | 说明 |")
    add("| --- | --- | --- | --- | --- |")
    for name, _path, count, total in dir_table():
        kind, note = DIR_NOTES.get(name, ("待确认", "未归类，需人工判断"))
        add(f"| `{name}` | {count} | {size_text(total)} | {kind} | {note} |")
    add("")

    add("## 根目录文件明细")
    add("")
    for key in ("A1", "A2", "A3", "A4", "A5", "A6", "B", "C", "E", "F"):
        items = buckets.get(key, [])
        if not items:
            continue
        title, note = CATEGORY_META[key]
        add(f"### {key} · {title}（{len(items)} 个，{size_text(sum(s for _n, s, _m in items))}）")
        add("")
        add(note)
        add("")
        add("| 文件 | 体积 | 时间 |")
        add("| --- | --- | --- |")
        for name, size, mtime_text in items:
            add(f"| `{name}` | {size_text(size)} | {mtime_text} |")
        add("")

    add("## 确认后建议怎么清")
    add("")
    add("按项目里「先备份、再分批、走回收站」的习惯：")
    add("")
    add("1. 先整目录复制一份备份，确认备份可读；")
    add("2. 只处理你确认过的类别，每批不超过 10 个文件；")
    add("3. 走回收站而不是直接删；")
    add("4. 每批做完再验一次仓库 `git status` 与全量测试，确认没误伤。")
    add("")
    add("## 本次没有做的事")
    add("")
    add("- 没有删除、移动、重命名任何文件；")
    add("- 没有改动 `templates_用户修改版_20260829` 与 `templates_backup_20260829_1854`；")
    add("- 没有把根 `tools/` 搬进仓库（搬动会影响脚本里的相对路径，需要单独一轮改）。")
    add("")

    return "\n".join(lines)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render())
    print(f"已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
