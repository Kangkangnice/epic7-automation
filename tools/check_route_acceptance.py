"""Validate the evidence for one route, backend, client and release revision."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re

REPLAY_CASES = frozenset({"normal", "repeat", "overlay", "slow_or_frozen", "unknown", "end"})
SCENARIOS = {"normal", "alternate", "expected_stop"}
OUTCOMES = {"completed", "expected_stop", "failed", "interrupted", "unsafe"}
MIN_RUNS = 10
MIN_ACCOUNT_RUNS = 2
MIN_DAYS = 3


def check_report(report: object, target: dict[str, str]) -> tuple[str, list[str]]:
    """Return the observed count and any reasons to withhold stable support."""
    if not isinstance(report, dict):
        return "", ["验收记录应是 JSON 对象。"]
    if any(report.get(key) != value for key, value in target.items()):
        return "", ["路线、后端、客户端版本和提交必须与发布目标一致。"]

    problems: list[str] = []
    cases = report.get("replay_cases")
    if not isinstance(cases, list) or not all(isinstance(case, str) for case in cases):
        problems.append("replay_cases 应列出已通过的用例类别。")
    else:
        missing = REPLAY_CASES.difference(cases)
        if missing:
            problems.append("缺少离线回归类别：" + ", ".join(sorted(missing)))

    runs = report.get("runs")
    if not isinstance(runs, list):
        return "", [*problems, "runs 应为独立实机运行列表。"]

    run_ids: set[str] = set()
    accounts: Counter[str] = Counter()
    dates: set[str] = set()
    environments: set[str] = set()
    covered: set[str] = set()
    planned = safe_stops = interrupted = 0
    for index, run in enumerate(runs, 1):
        if not isinstance(run, dict) or any(
            not isinstance(run.get(field), str) or not run[field].strip()
            for field in ("id", "account", "environment", "day", "scenario", "outcome")
        ) or type(run.get("terminal_verified")) is not bool:
            problems.append(f"第 {index} 次运行的必填字段缺失或类型有误。")
            continue
        run_id = run["id"].strip()
        if run_id in run_ids:
            problems.append(f"第 {index} 次运行重复登记。")
            continue
        run_ids.add(run_id)
        if any(run.get(key) != value for key, value in target.items()):
            problems.append(f"第 {index} 次运行与发布目标不一致。")
            continue
        day, scenario, outcome = run["day"], run["scenario"], run["outcome"]
        try:
            valid_day = date.fromisoformat(day).isoformat() == day
        except ValueError:
            valid_day = False
        if not valid_day or scenario not in SCENARIOS or outcome not in OUTCOMES:
            problems.append(f"第 {index} 次运行的日期、场景或结果无效。")
            continue
        if outcome == "interrupted":
            interrupted += 1
            continue
        if scenario != "expected_stop":
            planned += 1
        if outcome == "unsafe":
            problems.append(f"第 {index} 次运行发生误操作，阻止放行。")
            continue

        expected = "expected_stop" if scenario == "expected_stop" else "completed"
        if outcome != expected or not run["terminal_verified"]:
            problems.append(f"第 {index} 次运行未取得预期业务结果或未确认终点。")
            continue

        covered.add(scenario)
        if scenario == "expected_stop":
            safe_stops += 1
        else:
            accounts[run["account"].strip().casefold()] += 1
            dates.add(day)
            environments.add(run["environment"].strip().casefold())

    completed = sum(accounts.values())
    if completed < MIN_RUNS:
        problems.append(f"独立业务闭环至少需要 {MIN_RUNS} 次。")
    if sum(count >= MIN_ACCOUNT_RUNS for count in accounts.values()) < 2:
        problems.append(f"至少两个不同账号各完成 {MIN_ACCOUNT_RUNS} 次。")
    if len(dates) < MIN_DAYS or len(environments) < 2:
        problems.append(f"业务闭环须跨至少 {MIN_DAYS} 天、两个使用环境。")
    if SCENARIOS.difference(covered):
        problems.append("须覆盖默认流程、账号变体及预期安全停止。")
    summary = f"业务闭环 {completed}/{planned}，预期安全停止 {safe_stops}，人工中止 {interrupted}"
    return summary, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="本机脱敏验收记录 JSON")
    parser.add_argument("--route", required=True)
    parser.add_argument("--backend", choices=("emulator", "pc"), required=True)
    parser.add_argument("--client", required=True, help="客户端系列和版本")
    parser.add_argument("--revision", required=True, help="完整提交 SHA")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision 需要完整的 40 位小写 Git SHA")
    try:
        report = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"无法读取验收记录：{error}")
        return 1

    target = {key: getattr(args, key) for key in ("route", "backend", "client", "revision")}
    summary, problems = check_report(report, target)
    if summary:
        print(summary)
    for problem in problems:
        print(f"- {problem}")
    print("通过稳定版证据检查。" if not problems else "稳定版证据未通过。")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
