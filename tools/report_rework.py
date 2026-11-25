"""按路线统计返工次数、改动量与热点函数（只读）。

为什么要这个工具
----------------
2026-11-24 复核 418 个提交时发现：返工讨论一直停在「这条路线又坏了」，
没人横着算过 **每条路线被改了几轮、改了多少、改在哪个函数**。
没有数就没有约束力，规范里的「一次跑通 90%」「单条路线小修不超过 3 次」
只能靠印象判断。

三层计量，标题只作索引
----------------------
1. **提交**：标题只用来判「这条算不算修正」，不算改动量。
   一次提交可能改五处，标题只写其中一处，所以标题不能当计量单位。
2. **改动量与改动块**：解析每个提交的 `--numstat -p --unified=0`，
   得到每条路线被改了多少行、多少个 `@@` 块。一次收口里改了三处就是三个块，
   不再被压成「一次」。
3. **函数归因**（`--hot`）：对当前代码做 `git blame`，再按 AST 的函数区间聚合，
   看每个函数被多少个不同提交改过。这条完全不用标题，能指出真正的热点，
   例如英雄合成的 `next_action` 被 32 个提交改过。

口径
----
- **路线归属**：按改动路径判定（`games/epic7/<name>.py`、`templates/<name>/`、
  `tests/fixtures/epic7_<name>*`、`tests/test_*<name>*`、`docs/maintenance/<name>.md`）。
  前缀包含时取最长名，`story_star` 不会被记进 `story`。
- **上线日**：第一次改动 `games/epic7/<name>.py` 的提交日期。返工只算严格晚于上线日的提交。
- **修正类提交**：标题以 `fix` 开头；标题含「收口」；没有类型前缀。
  排除 `feat`、`refactor` / `docs` / `test` / `chore`（非收口）/ `ci`，
  以及标题写明「架构 / 整改 / 重构 / 文案 / 命名 / 格式 / 瘦身 / 整理」的结构性改动。
- **一次跑通**：上线后 7 天内该路线零修正类提交。
- **预算**：修正类提交不超过 3 次。

已知局限
--------
批量收口把多次修复压进一个提交时，**提交数**会低估，但**改动块数**能补回来；
结构性改动混在收口里会被算进来（高估）；未提交的工作看不到（末行会列出被改动的路线）。

用法（仓库父目录）：

    python -m auto_game_unified.tools.report_rework
    python -m auto_game_unified.tools.report_rework --hot
    python -m auto_game_unified.tools.report_rework --json
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: 路线名到中文名。归属按最长匹配，避免 story 吃掉 story_star。
ROUTE_LABELS = {
    "arena": "竞技场", "story": "主线", "expedition": "远征", "tower": "月塔",
    "fodder": "狗粮", "side_story": "支线故事", "moonlight_theater": "月光剧场",
    "hero_synthesis": "英雄合成", "shop_refresh": "刷书签", "survivor": "活动",
    "activity_story": "活动剧情", "world_boss": "世界首领战",
    "knights_donation": "骑士团捐赠", "labyrinth_stone": "迷宫强化石",
    "sanctuary": "圣域收菜", "achievement": "成就领取",
    "pet_adoption": "宠物领养", "penguin_purchase": "企鹅批量购买",
    "craft_equipment": "装备制作", "story_star": "主线补星", "community": "社区签到",
}

#: 路线模板目录名与注册名不一致的，写在这里。
TEMPLATE_ALIASES = {"hero_synthesis": "hero"}

SHARED_PREFIXES = (
    "core/", "main.py", "games/epic7/runner_base.py",
    "games/epic7/transactional_runner_base.py", "games/epic7/global_popups",
    "games/epic7/navigation.py", "games/epic7/modes.py", "games/epic7/stamina.py",
    "games/epic7/pre_battle.py",
)

#: 结构性改动的关键词：改的是代码形状，不是失败现场。
STRUCTURAL_MARKERS = ("架构", "整改", "重构", "文案", "命名", "格式", "瘦身", "整理")

BUDGET = 3
FIRST_PASS_WINDOW = 7


def route_hits(path: str) -> list[str]:
    """一个文件路径归属到哪些路线。前缀包含时只留最长的那个。"""
    p = path.replace("\\", "/")
    hits = []
    for name in ROUTE_LABELS:
        template = TEMPLATE_ALIASES.get(name, name)
        markers = (
            f"games/epic7/{name}.py",
            f"games/epic7/{name}_",
            f"templates/{template}/",
            f"templates/pc/{template}/",
            f"fixtures/epic7_{template}",
            f"test_epic7_{name}",
            f"test_{name}",
            f"maintenance/{name}.md",
        )
        if any(marker in p for marker in markers):
            hits.append(name)
    if not hits:
        return []
    longest = max(len(hit) for hit in hits)
    return [hit for hit in hits if len(hit) == longest]


def commit_routes(files: list[str]) -> set[str]:
    routes: set[str] = set()
    for path in files:
        routes.update(route_hits(path))
    return routes


def is_rework(subject: str) -> bool:
    """这条提交算不算一次修正。判断顺序即文档里的口径。"""
    text = subject.strip()
    if text.startswith("fix"):
        return True
    if "收口" in text:
        return True
    if text.startswith(("feat", "refactor", "docs", "test", "chore", "ci")):
        return False
    if any(marker in text for marker in STRUCTURAL_MARKERS):
        return False
    return True


def parse_log(text: str) -> list[dict[str, Any]]:
    """解析 ``git log --pretty=format:@@@%h\\t%ad\\t%s --date=short --name-status``。"""
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("@@@"):
            if current is not None:
                commits.append(current)
            parts = line[3:].split("\t", 2)
            hash_ = parts[0] if parts else ""
            day = parts[1] if len(parts) > 1 else ""
            subject = parts[2] if len(parts) > 2 else ""
            current = {"hash": hash_.strip(), "day": day.strip(),
                       "subject": subject.strip(), "files": []}
        elif line.strip() and current is not None:
            parts = line.split("\t")
            if len(parts) >= 2:
                current["files"].append(parts[-1].strip())
    if current is not None:
        commits.append(current)
    return commits


def parse_patch_stats(text: str) -> dict[str, tuple[int, int, int]]:
    """从 ``git show --numstat -p --unified=0`` 输出里取每个文件的 (增, 删, 改动块)。"""
    stats: dict[str, list[int]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("diff --git"):
            current = None
            continue
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("@@"):
            if current is not None and current in stats:
                stats[current][2] += 1
            continue
        if current is None and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 3 and (parts[0].isdigit() or parts[0] == "-"):
                added = int(parts[0]) if parts[0].isdigit() else 0
                deleted = int(parts[1]) if parts[1].isdigit() else 0
                stats[parts[-1].strip()] = [added, deleted, 0]
    return {path: (values[0], values[1], values[2]) for path, values in stats.items()}


def _to_date(text: str) -> date | None:
    try:
        year, month, day = (int(part) for part in text.split("-"))
    except (ValueError, TypeError):
        return None
    return date(year, month, day)


def behaviour_prefixes(name: str) -> tuple[str, ...]:
    template = TEMPLATE_ALIASES.get(name, name)
    return (
        f"games/epic7/{name}.py",
        f"games/epic7/{name}_",
        f"games/epic7/templates/{template}/",
        f"games/epic7/templates/pc/{template}/",
    )


def summarise(commits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按路线汇总计数。纯函数，测试直接喂假数据。"""
    rows: dict[str, dict[str, Any]] = {
        name: {"label": label, "total": 0, "feat": 0, "rework": 0, "fix_titled": 0,
               "launch": "", "within7": 0, "shared_fix": 0, "rework_hashes": [],
               "first_pass": False, "within_budget": False}
        for name, label in ROUTE_LABELS.items()
    }
    for name in ROUTE_LABELS:
        prefixes = behaviour_prefixes(name)
        touched = [c for c in commits
                   if any(str(p).replace("\\", "/").startswith(prefixes) for p in c["files"])]
        if not touched:
            continue
        row = rows[name]
        row["total"] = len(touched)
        row["feat"] = sum(1 for c in touched if str(c["subject"]).startswith("feat"))
        touched.sort(key=lambda c: str(c["day"]))
        launch = str(touched[0]["day"])
        row["launch"] = launch
        start = _to_date(launch)
        after = [c for c in touched if str(c["day"]) > launch]
        rework = [c for c in after if is_rework(str(c["subject"]))]
        row["rework"] = len(rework)
        row["rework_hashes"] = [str(c["hash"]) for c in rework]
        row["fix_titled"] = sum(1 for c in rework if str(c["subject"]).startswith("fix"))
        row["shared_fix"] = sum(
            1 for c in rework
            if any(str(p).replace("\\", "/").startswith(SHARED_PREFIXES) for p in c["files"])
        )
        row["within7"] = sum(
            1 for c in rework
            if start is not None and _to_date(str(c["day"])) is not None
            and (_to_date(str(c["day"])) - start).days <= FIRST_PASS_WINDOW  # type: ignore[operator]
        )
        row["first_pass"] = row["within7"] == 0
        row["within_budget"] = row["rework"] <= BUDGET
    return rows


def run(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def patch_stats_all() -> dict[str, dict[str, tuple[int, int, int]]]:
    """一次取回全部提交的改动量，避免每个提交都起一个 git 进程。"""
    text = run("log", "--numstat", "-p", "--unified=0", "--format=@@@%h", "--", "*.py")
    result: dict[str, dict[str, tuple[int, int, int]]] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("@@@"):
            if current is not None:
                result[current] = parse_patch_stats("\n".join(buffer))
            current = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        result[current] = parse_patch_stats("\n".join(buffer))
    return result


def volume_for(name: str, row: dict[str, Any],
               stats: dict[str, dict[str, tuple[int, int, int]]]) -> tuple[int, int, int]:
    """这条路线在全部修正提交里被改了多少行、多少个块。"""
    prefixes = behaviour_prefixes(name)
    added = deleted = hunks = 0
    for hash_ in row["rework_hashes"]:
        for path, (add, delete, hunk) in stats.get(hash_, {}).items():
            if path.replace("\\", "/").startswith(prefixes):
                added += add
                deleted += delete
                hunks += hunk
    return added, deleted, hunks


def function_hotspots(module: str, top: int = 3) -> list[tuple[str, int, int]]:
    """按当前代码的函数区间做 blame 归因，返回 (函数名, 行数, 改动提交数) 前几项。"""
    source = run("show", f"HEAD:{module}")
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append((f"{prefix}{child.name}", child.lineno,
                              child.end_lineno or child.lineno))
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree)

    blame = run("blame", "HEAD", "--line-porcelain", "--", module)
    line_commit: dict[int, str] = {}
    for line in blame.splitlines():
        parts = line.split()
        if len(parts) >= 4 and len(parts[0]) == 40 and parts[1].isdigit() and parts[2].isdigit():
            start = int(parts[2])
            count = int(parts[3])
            for offset in range(count):
                line_commit[start + offset] = parts[0]

    hot: list[tuple[str, int, int]] = []
    for name, start, end in spans:
        commits = {line_commit.get(line) for line in range(start, end + 1)}
        commits.discard(None)
        if len(commits) >= 2:
            hot.append((name, end - start + 1, len(commits)))
    hot.sort(key=lambda item: (-item[2], -item[1]))
    return hot[:top]


def dirty_routes() -> list[str]:
    """工作区里被改动、但还没进历史的路线（统计看不到它们）。"""
    status = run("status", "--short")
    found: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        for name in commit_routes([line[3:].strip()]):
            label = ROUTE_LABELS[name]
            if label not in found:
                found.append(label)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="按路线统计返工、改动量与热点函数（只读）")
    parser.add_argument("--json", action="store_true", help="输出 JSON，供脚本复核")
    parser.add_argument("--hot", action="store_true", help="额外统计每条路线的热点函数（较慢）")
    args = parser.parse_args()

    text = run("log", "--pretty=format:@@@%h\t%ad\t%s", "--date=short", "--name-status")
    if not text.strip():
        print("[rework] 读不到 git 历史（当前目录不是仓库，或还没有提交）")
        return 1

    commits = parse_log(text)
    rows = summarise(commits)
    active = {name: row for name, row in rows.items() if row["total"]}
    dirty = dirty_routes()

    cache = patch_stats_all()
    volumes: dict[str, tuple[int, int, int]] = {}
    for name, row in active.items():
        volumes[name] = volume_for(name, row, cache)

    if args.json:
        print(json.dumps({"routes": active, "volumes": volumes, "budget": BUDGET,
                          "window": FIRST_PASS_WINDOW, "dirty": dirty},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"[rework] 扫描 {len(commits)} 个提交，命中 {len(active)} 条路线"
          f"（预算 ≤{BUDGET} 次，一次跑通窗口 {FIRST_PASS_WINDOW} 天）\n")
    print("路线\t业务提交\t修正类\t其中fix\t改动块\t增删行\t7天内\t一次跑通\t预算")
    for name, row in sorted(active.items(), key=lambda kv: -int(kv[1]["rework"])):
        added, deleted, hunks = volumes[name]
        print(f"{row['label']}\t{row['total']}\t{row['rework']}\t{row['fix_titled']}"
              f"\t{hunks}\t{added}+{deleted}"
              f"\t{row['within7']}\t{'是' if row['first_pass'] else '否'}"
              f"\t{'在预算内' if row['within_budget'] else '超预算'}")

    total = len(active)
    first_pass = sum(1 for row in active.values() if row["first_pass"])
    in_budget = sum(1 for row in active.values() if row["within_budget"])
    rework_total = sum(int(row["rework"]) for row in active.values())
    fix_total = sum(int(row["fix_titled"]) for row in active.values())
    hunk_total = sum(value[2] for value in volumes.values())
    print(f"\n[rework] 修正类提交 {rework_total} 个（标题带 fix {fix_total} 个，"
          f"{fix_total / max(rework_total, 1) * 100:.0f}%），改动块合计 {hunk_total}")
    print(f"[rework] 一次跑通 {first_pass}/{total} = {first_pass / total * 100:.0f}%")
    print(f"[rework] 小修在预算内 {in_budget}/{total} = {in_budget / total * 100:.0f}%")
    if dirty:
        print(f"[rework] 工作区还有未提交的路线改动，不计入：{'、'.join(dirty)}")

    if args.hot:
        print("\n[rework] 热点函数（按被多少个提交改过排序，不受提交标题影响）")
        for name, row in sorted(active.items(), key=lambda kv: -int(kv[1]["rework"]))[:8]:
            module = f"games/epic7/{name}.py"
            hot = function_hotspots(module)
            if not hot:
                continue
            formatted = "、".join(f"{func}({count} 个提交/{lines} 行)"
                                  for func, lines, count in hot)
            print(f"  {row['label']}: {formatted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
