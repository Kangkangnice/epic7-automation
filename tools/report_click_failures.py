"""统计各路线日志里的「点击验收=无效」，把散落的同一个现象汇到一起看。

背景（2026-10-03）：这个现象一直反复发生（打开快捷菜单 68 次、进入竞技场 15 次、
进入英雄列表 8 次、进入战斗菜单 8 次…），但日志是**按路线各写各的**
（远征写远征、英雄合成写英雄合成），从没人横着比一次 —— 于是它一直被当成
「某条路线失败了」，没被看成**一个独立问题**。

只读，不改任何东西，随时可重跑。

用法（任意目录均可，路径按脚本自身位置推导）：
    D:\\anaconda\\python.exe auto_game_unified/tools/report_click_failures.py
    D:\\anaconda\\python.exe auto_game_unified/tools/report_click_failures.py --top 20
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = PACKAGE_DIR / "runtime_logs"

#: 导航判定「点了一下但页面没变」时写的固定文案（见 navigation 的点击验收分支）。
INVALID_MARKER = "点击验收=无效"

_ACTION_RE = re.compile(r"动作=(\S+)")
_PAGE_RE = re.compile(r"页面=(\S+)")
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _field(pattern: re.Pattern[str], line: str) -> str:
    match = pattern.search(line)
    return match.group(1) if match else "<未知>"


def collect(logs_dir: Path) -> dict[str, object]:
    """扫一遍日志目录，返回各项计数与总次数。"""
    by_action: Counter[str] = Counter()
    by_page: Counter[str] = Counter()
    by_log: Counter[str] = Counter()
    by_date: Counter[str] = Counter()
    total = 0
    for log in sorted(logs_dir.glob("*.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if INVALID_MARKER not in line:
                continue
            total += 1
            by_action[_field(_ACTION_RE, line)] += 1
            by_page[_field(_PAGE_RE, line)] += 1
            by_log[log.name] += 1
            by_date[_field(_DATE_RE, line)] += 1
    return {
        "total": total,
        "logs": len(list(logs_dir.glob("*.log"))),
        "by_action": by_action,
        "by_page": by_page,
        "by_log": by_log,
        "by_date": by_date,
    }


def _report(title: str, counter: Counter[str], top: int) -> None:
    print(f"\n{title}")
    if not counter:
        print("  （无）")
        return
    for name, count in counter.most_common(top):
        print(f"  {count:>5}  {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="点击失灵横向统计（只读）")
    parser.add_argument("--top", type=int, default=15, help="每组最多列几条（默认 15）")
    parser.add_argument("--logs", default=str(LOGS_DIR), help="日志目录")
    args = parser.parse_args()

    logs_dir = Path(args.logs)
    if not logs_dir.is_dir():
        print(f"[click] 日志目录不存在：{logs_dir}")
        return 1

    data = collect(logs_dir)
    print(
        f"[click] 扫描 {data['logs']} 个日志，"
        f"共 {data['total']} 次「{INVALID_MARKER}」"
    )
    if not data["total"]:
        print("[click] 没有记录。若刚清过日志属正常。")
        return 0

    _report(f"按动作 Top {args.top}（点哪儿点不动）", data["by_action"], args.top)
    _report(f"按页面 Top {args.top}（卡在哪个页面）", data["by_page"], args.top)
    _report("按来源日志（哪条路线在踩）", data["by_log"], args.top)
    _report("按日期（最近的在最上）", data["by_date"], args.top)
    print(
        "\n[click] 说明：这里只统计「点了一下但页面没变」。其中一部分可能是"
        "验收判据偏严（覆盖层不改变底层页面身份，典型是快捷菜单），"
        "不全是点击真的没送达 —— 需要配合当时那条 `点击验收=生效` 与诊断图判断。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
