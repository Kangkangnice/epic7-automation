"""Validate the evidence for one route, backend, client and release revision.

检查分两层：

* **结构门槛**：路线/后端/客户端/提交、样本数、账号与环境差异；
* **原始材料**：每条运行能切出一次启动的日志边界，依据引用能打开，
  业务量、资源、终点和停止原因与日志不矛盾。

工具只拒绝它能机器判定的矛盾。通过时输出「台账通过，待独立复核」，
并列出仍需人看画面或对账的事项；工具通过不等于放行。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path
import re
import subprocess
import sys

SCHEMA_VERSION = 2
REPLAY_CASES = frozenset({"normal", "repeat", "overlay", "slow_or_frozen", "unknown", "end"})
SCENARIOS = frozenset({"normal", "alternate", "expected_stop", "read_only"})
OUTCOMES = frozenset({"completed", "expected_stop", "failed", "interrupted", "unsafe"})
WORK_KINDS = frozenset({"business", "read_only"})
MIN_RUNS = 10
MIN_ACCOUNT_RUNS = 2
MIN_DAYS = 3

LAUNCH_FORMAT = "%Y-%m-%d %H:%M:%S"
TERMINAL_MARKER = re.compile(r"(?:^|\s)收尾=已回到首页")
FAILURE_MARKERS = ("收尾=回首页失败", "进入路线失败", "异常收尾=")
MANUAL_MARKERS = ("用户按下 P", "正在中断自动化")
TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ")
ANCHOR = re.compile(r"L(\d+)(?:-L?(\d+))?")
ZERO_WORK = re.compile(r"已完成=0(?:\s|$)")
PASS_RESULT = re.compile(r"\b(?:1 passed|[1-9]\d* passed|passed|PASSED)\b")
FAIL_RESULT = re.compile(r"\b[1-9]\d* failed\b|\bFAILED\b|\bSKIPPED\b|\bERROR\b")

#: 日志只写中文模式名时必须认得的路线别名；跨路线借证仍被拒绝。
ROUTE_LABELS = {
    "craft_equipment": "装备制作",
    "shop_refresh": "刷书签",
    "story_star": "主线补星",
    "pet_adoption": "宠物领养",
    "penguin_purchase": "企鹅批量购买",
    "side_story": "支线故事",
    "hero_synthesis": "英雄合成",
    "world_boss": "世界首领战",
    "knights_donation": "骑士团捐赠",
    "labyrinth_stone": "迷宫强化石",
    "moonlight_theater": "月光剧场",
    "story": "主线",
    "arena": "竞技场",
    "expedition": "远征",
    "tower": "月塔",
    "fodder": "狗粮",
    "survivor": "活动小游戏",
    "activity_story": "活动剧情",
    "community": "社区签到",
    "achievement": "成就领取",
    "sanctuary": "圣域",
}

#: 能从日志读回最终业务计数的字段。多个回合取最后一次累计量。
QUANTITY_FIELDS = {
    "craft_equipment": re.compile(r"(?:^|\s)件数=(\d+)"),
}

_COLLECTION_CACHE: dict[Path, set[str]] = {}


def _route_present(text: str, route: str) -> bool:
    """只认完整模式字段，story 不等于 story_star，主线不等于主线补星。"""
    names = [route]
    label = ROUTE_LABELS.get(route)
    if label:
        names.append(label)
    return any(
        re.search(rf"(?:^|\s)模式={re.escape(name)}(?=\s|$)", text, re.M) is not None
        for name in names
    )


def _collected_nodes(path: Path) -> set[str]:
    """用 pytest 的真实收集结果核准节点；收集不到时 fail-closed。"""
    if path in _COLLECTION_CACHE:
        return _COLLECTION_CACHE[path]
    try:
        relative = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return set()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(relative)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    nodes = set(re.findall(r"^(\S+::\S+)\s*$", result.stdout, re.M))
    _COLLECTION_CACHE[path] = nodes
    return nodes

REPO_ROOT = Path(__file__).resolve().parents[1]

MANUAL_REVIEW = (
    "账号与环境代号是否确属不同实体（代号不能自证）。",
    "业务回执画面与台账文字是否一致，计数单位是否对得上。",
    "危险动作是否同帧确认，是否存在被遮挡或迟到的回执。",
    "终点标记是否对应约定终点，而不是外观相似的页面。",
    "资源上限与界面设置、实际扣费是否一致。",
    "支持每日编排的组合是否另有真实桌面每日入口记录。",
)


def _resolve_ref(reference: object, base: Path) -> tuple[Path | None, int | None, int | None, str | None]:
    """把 ``相对路径#L12-L20`` 解析成可读文件与行号。"""
    if not isinstance(reference, str) or not reference.strip():
        return None, None, None, "依据引用为空。"
    text = reference.strip()
    path_part, separator, anchor = text.partition("#")
    if not path_part or Path(path_part).is_absolute() or ".." in Path(path_part).parts:
        return None, None, None, f"依据引用必须是仓库内相对路径：{text}"
    candidates = (base / path_part, REPO_ROOT / path_part)
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        return None, None, None, f"证据打不开：{path_part}"
    try:
        text_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return None, None, None, f"证据打不开：{path_part}（{error}）"
    if not separator:
        return path, None, None, None
    match = ANCHOR.fullmatch(anchor)
    if match is None:
        return None, None, None, f"行号格式应为 #L12 或 #L12-L20：{text}"
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if not 1 <= start <= end <= len(text_lines):
        return None, None, None, f"证据行号超出文件范围（共 {len(text_lines)} 行）：{text}"
    return path, start, end, None


def _timestamp(text: str) -> datetime | None:
    match = TIMESTAMP.match(text)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), LAUNCH_FORMAT)
    except ValueError:
        return None


def _launch_slice(path: Path, started: datetime, ended: datetime) -> tuple[list[tuple[int, str]], str | None]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return [], f"启动日志打不开：{path}（{error}）"
    picked = []
    for number, line in enumerate(lines, 1):
        moment = _timestamp(line)
        if moment is not None and started <= moment <= ended:
            picked.append((number, line))
    if not picked:
        return [], "启动边界内没有日志行，起止时间或日志文件有误。"
    return picked, None


def _check_test_node(node: object) -> tuple[str | None, str | None]:
    """核对完整测试节点，返回 (函数名, 错误)。类名不参与核对就会串到同名函数。"""
    if not isinstance(node, str) or "::" not in node:
        return None, "回放测试节点应写成 tests/xxx.py::Class::test_name 或 tests/xxx.py::test_name。"
    path_part, _, rest = node.partition("::")
    path = REPO_ROOT / path_part
    if not path.is_file():
        return None, f"回放测试文件不存在：{path_part}"
    segments = [part.strip() for part in rest.split("::") if part.strip()]
    if not segments or len(segments) > 2:
        return None, f"回放测试节点格式无效：{node}"
    name = segments[-1]
    if node not in _collected_nodes(path):
        return None, f"pytest 收集不到该节点（含类名与所属文件）：{node}"
    return name, None


def _check_replay_result(path: Path, name: str, node: str, revision: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"回放结果打不开：{path}（{error}）"
    if revision not in text:
        return f"回放结果未写明待验提交 {revision}。"
    own_lines = [
        line for line in text.splitlines()
        if re.search(rf"(?:^|\s)node={re.escape(node)}(?=\s|$)", line) is not None
    ]
    if not own_lines:
        return f"回放结果未指向该测试节点：{node}"
    if any(FAIL_RESULT.search(line) for line in own_lines):
        return f"回放节点自身的结果不是通过，没有该节点的通过记录：{node}"
    if not any(PASS_RESULT.search(line) for line in own_lines):
        return f"回放结果没有该节点的通过记录：{node}"
    return None


def _check_contract(contract: object) -> tuple[dict[str, object], list[str]]:
    problems: list[str] = []
    if not isinstance(contract, dict):
        return {}, ["缺少验收合同：entry / settings / goal / unit / receipt / terminal / early_stop / resources。"]
    for field in ("entry", "settings", "goal", "unit", "receipt", "terminal"):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"验收合同缺少 {field}。")
    early_stop = contract.get("early_stop")
    if not isinstance(early_stop, list) or not early_stop or not all(
        isinstance(item, str) and item.strip() for item in early_stop
    ):
        problems.append("验收合同须逐条列出允许提前停止的条件（early_stop）。")
    resources = contract.get("resources")
    if not isinstance(resources, list):
        problems.append("验收合同须列出资源与上限（resources，可为空列表）。")
    else:
        names = []
        for index, item in enumerate(resources, 1):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                problems.append(f"合同资源第 {index} 项缺少名称。")
                continue
            cap = item.get("cap")
            if isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < 0:
                problems.append(f"合同资源「{item['name']}」的上限应为非负数。")
                continue
            names.append(item["name"].strip())
        if len(names) != len(set(names)):
            problems.append("合同资源名称重复。")
    marker = contract.get("terminal_marker")
    if marker is not None and (not isinstance(marker, str) or not marker.strip()):
        problems.append("terminal_marker 应为非空字符串或省略。")
    return contract, problems


def _check_replay(cases: object, base: Path, revision: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(cases, list):
        return ["replay_cases 应列出已通过的用例类别、测试节点和依据。"]
    seen: set[str] = set()
    for index, item in enumerate(cases, 1):
        if not isinstance(item, dict):
            problems.append(f"回放第 {index} 项只有类别名；须写测试节点与依据。")
            continue
        case = item.get("case")
        if case not in REPLAY_CASES:
            problems.append(f"回放第 {index} 项的类别无效：{case!r}。")
            continue
        seen.add(case)
        name, problem = _check_test_node(item.get("test"))
        if problem:
            problems.append(f"回放 {case}：{problem}")
        evidence_path, _, _, error = _resolve_ref(item.get("evidence"), base)
        if error:
            problems.append(f"回放 {case}：{error}")
        elif name is not None:
            assert evidence_path is not None
            error = _check_replay_result(evidence_path, name, item["test"], revision)
            if error:
                problems.append(f"回放 {case}：{error}")
    missing = REPLAY_CASES.difference(seen)
    if missing:
        problems.append("缺少离线回归类别：" + ", ".join(sorted(missing)))
    return problems


def check_report(
    report: object,
    target: dict[str, str],
    base: Path | None = None,
    notes: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Return the observed count and any reasons to withhold stable support."""
    if not isinstance(report, dict):
        return "", ["验收记录应是 JSON 对象。"]
    if report.get("schema") != SCHEMA_VERSION:
        return "", [
            "旧格式或不支持的台账版本：旧台账仅作历史证据，不能作为稳定版准入；"
            "请按现行规范补登 schema 2、验收合同、启动边界与依据。"
        ]
    if any(report.get(key) != value for key, value in target.items()):
        return "", ["路线、后端、客户端版本和提交必须与发布目标一致。"]

    base = base or REPO_ROOT
    problems: list[str] = []
    contract, contract_problems = _check_contract(report.get("contract"))
    problems.extend(contract_problems)
    problems.extend(_check_replay(report.get("replay_cases"), base, target["revision"]))

    runs = report.get("runs")
    if not isinstance(runs, list):
        return "", [*problems, "runs 应为独立实机运行列表。"]

    run_ids: set[str] = set()
    launches: set[tuple[str, str]] = set()
    terminal_refs: set[tuple[str, int | None, int | None]] = set()
    evidence_keys: set[tuple[tuple[str, int | None, int | None], ...]] = set()
    windows_by_log: dict[str, list[tuple[datetime, datetime, str]]] = {}
    accounts: Counter[str] = Counter()
    dates: set[str] = set()
    environments: set[str] = set()
    covered: set[str] = set()
    planned = safe_stops = interrupted = read_only_ok = failed = 0
    read_only_failed = 0

    for index, run in enumerate(runs, 1):
        label = f"第 {index} 次运行"
        if not isinstance(run, dict):
            problems.append(f"{label}不是对象。")
            continue
        required = (
            "id", "route", "backend", "client", "revision", "account", "environment",
            "day", "scenario", "work", "outcome", "requested", "receipt", "stop_reason",
        )
        missing = [field for field in required if not isinstance(run.get(field), str)]
        if missing:
            problems.append(f"{label}缺少字符串字段：" + ", ".join(missing) + "。")
            continue
        if not run["id"].strip() or not run["requested"].strip():
            problems.append(f"{label}的编号或请求量为空。")
            continue
        if not run["account"].strip() or not run["environment"].strip():
            problems.append(f"{label}的账号或环境代号为空白，不能充当第二个变体。")
            continue
        if any(run.get(key) != value for key, value in target.items()):
            problems.append(f"{label}与发布目标不一致。")
            continue

        run_id = run["id"].strip()
        if run_id in run_ids:
            problems.append(f"{label}重复登记运行编号 {run_id}。")
            continue
        run_ids.add(run_id)

        scenario, work, outcome = run["scenario"], run["work"], run["outcome"]
        if scenario not in SCENARIOS:
            problems.append(f"{label}的场景无效：{scenario!r}。")
            continue
        if outcome not in OUTCOMES:
            problems.append(f"{label}的结果无效：{outcome!r}。")
            continue
        if work not in WORK_KINDS:
            problems.append(f"{label}的 work 应为 business 或 read_only。")
            continue
        if (work == "read_only") != (scenario == "read_only"):
            problems.append(
                f"{label}把只读巡检与打图混填：work={work}、scenario={scenario}；"
                "只读运行须单列 read_only，且不得计入业务闭环。"
            )
            continue

        day = run["day"]
        try:
            valid_day = date.fromisoformat(day).isoformat() == day
        except ValueError:
            valid_day = False
        if not valid_day:
            problems.append(f"{label}的日期无效：{day!r}。")
            continue

        target_quantity = run.get("target")
        achieved = run.get("achieved")
        if target_quantity is not None and (
            isinstance(target_quantity, bool)
            or not isinstance(target_quantity, (int, float))
            or target_quantity <= 0
        ):
            problems.append(f"{label}的 target 应为正数或 null。")
            continue
        if achieved is not None and (
            isinstance(achieved, bool) or not isinstance(achieved, (int, float)) or achieved < 0
        ):
            problems.append(f"{label}的 achieved 应为非负数或 null。")
            continue

        first_failure = run.get("first_failure", "")
        if not isinstance(first_failure, str):
            problems.append(f"{label}的 first_failure 应为字符串。")
            continue
        terminal = run.get("terminal")
        if (
            not isinstance(terminal, dict)
            or type(terminal.get("verified")) is not bool
            or not isinstance(terminal.get("evidence"), str)
        ):
            problems.append(f"{label}缺少 terminal.verified 或 terminal.evidence。")
            continue

        launch = run.get("launch")
        if not isinstance(launch, dict) or not isinstance(launch.get("log"), str):
            problems.append(f"{label}缺少 launch.log / started_at / ended_at。")
            continue
        try:
            started = datetime.strptime(launch.get("started_at", ""), LAUNCH_FORMAT)
            ended = datetime.strptime(launch.get("ended_at", ""), LAUNCH_FORMAT)
        except (TypeError, ValueError):
            problems.append(f"{label}的启动起止时间应为 YYYY-MM-DD HH:MM:SS。")
            continue
        if ended <= started:
            problems.append(f"{label}的启动结束时间不晚于开始时间。")
            continue
        if day != started.strftime("%Y-%m-%d"):
            problems.append(f"{label}的日期与启动时间不一致：day={day}，启动={started}。")
            continue

        log_path, _, _, log_error = _resolve_ref(launch["log"], base)
        if log_error or log_path is None:
            problems.append(f"{label}：{log_error or '日志路径无效'}")
            continue
        identity = (str(log_path.resolve()), started.strftime(LAUNCH_FORMAT))
        if identity in launches:
            problems.append(
                f"{label}与已有记录是同一次启动（同一日志、同一开始时间）："
                "换编号重报会把一个样本凑成两个。"
            )
            continue
        launches.add(identity)

        log_key = str(log_path.resolve())
        overlap = next(
            (
                other_id for other_start, other_end, other_id in windows_by_log.get(log_key, [])
                if started < other_end and ended > other_start
            ),
            None,
        )
        if overlap:
            message = (
                f"{label}与 {overlap} 的启动边界重叠，不能可靠区分为独立样本；"
                "待人工核对，本次不计入业务闭环。"
            )
            if notes is None:
                problems.append(message)
            else:
                notes.append(message)
        else:
            windows_by_log.setdefault(log_key, []).append((started, ended, run_id))
        countable = overlap is None

        slice_lines, slice_error = _launch_slice(log_path, started, ended)
        if slice_error:
            problems.append(f"{label}：{slice_error}")
            continue
        slice_text = "\n".join(line for _, line in slice_lines)
        if not _route_present(slice_text, run["route"]):
            problems.append(
                f"{ROUTE_LABELS.get(run['route'], run['route'])} 的日志边界内没有该路线的完整模式字段，"
                "不能借其他路线的业务或终点充当本次证据。"
            )
            continue
        pattern = QUANTITY_FIELDS.get(run["route"])
        if pattern is not None:
            final_counts = [
                int(match.group(1))
                for _, line in slice_lines
                for match in pattern.finditer(line)
            ]
            if final_counts and achieved is not None and final_counts[-1] != achieved:
                problems.append(
                    f"{label}本次启动日志的最终业务计数为 {final_counts[-1]}，"
                    f"台账申报实得 {achieved}；应以最后一次累计量核对。"
                )
                continue
        if ZERO_WORK.search(slice_text) and (achieved or 0) > 0:
            problems.append(f"{label}的日志写明已完成=0，却申报实得 {achieved}。")
            continue

        evidence = run.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            problems.append(f"{label}没有业务依据引用。")
            continue
        resolved: list[tuple[str, int | None, int | None]] = []
        duplicate = False
        for reference in evidence:
            path, start_line, end_line, error = _resolve_ref(reference, base)
            if error or path is None:
                problems.append(f"{label}：{error or '依据路径无效'}")
                duplicate = True
                break
            resolved.append((str(path.resolve()), start_line, end_line))
        evidence_key = tuple(sorted(resolved))
        if not duplicate and evidence_key in evidence_keys:
            problems.append(f"{label}重复引用了已有运行的同一份业务依据。")
            duplicate = True
        if not duplicate:
            evidence_keys.add(evidence_key)
        if duplicate:
            continue

        if terminal["verified"]:
            terminal_path, term_start, term_end, terminal_error = _resolve_ref(
                terminal["evidence"], base
            )
            if terminal_error or terminal_path is None:
                problems.append(f"{label}的终点依据{terminal_error or '路径无效'}")
                continue
            terminal_key = (str(terminal_path.resolve()), term_start, term_end)
            if terminal_key in terminal_refs:
                problems.append(f"{label}重复引用了已有运行的同一条终点证据。")
                continue
            terminal_refs.add(terminal_key)

        if outcome == "unsafe":
            problems.append(f"{label}发生误操作，阻止该组合稳定放行。")
            continue

        if first_failure.strip() and outcome != "failed":
            problems.append(
                f"{label}已记录首个故障，却填成 {outcome}；"
                "应先按故障记 failed（或 unsafe），不得改填达标或人工中止。"
            )
            continue

        if (scenario in {"normal", "alternate"} and outcome == "expected_stop") or (
            scenario == "expected_stop" and outcome != "expected_stop"
        ):
            problems.append(
                f"{label}的场景与结果不一致：预登记 {scenario}，实际 {outcome}；"
                "请保留两者差异并说明理由，不得抹去预登记场景。"
            )
        if not run["stop_reason"].strip() and outcome in {"expected_stop", "failed"} and not first_failure.strip():
            problems.append(f"{label}记 {outcome} 但未写停止原因或首个故障。")
            continue

        # 越权与首个故障必须先于主动停止分类核对。
        error = _check_resources(run, contract, outcome)
        if error:
            problems.append(f"{label}：{error}")
            continue

        if outcome == "interrupted":
            error = _check_interrupted(run, slice_lines, started, ended)
            if error:
                problems.append(f"{label}：{error}")
                continue
            interrupted += 1
            continue

        if outcome == "completed":
            error = _check_completed(run, contract, slice_lines, slice_text, log_path, base)
            if error:
                problems.append(f"{label}：{error}")
                continue
        elif outcome == "expected_stop":
            error = _check_expected_stop(run, contract, slice_lines, slice_text, log_path, base)
            if error:
                problems.append(f"{label}：{error}")
                continue
        else:  # failed
            if work == "business":
                failed += 1
                problems.append(
                    f"{label}发生真实失败：当前业务计划不能声明稳定支持，失败保留在分母中。"
                )
            else:
                read_only_failed += 1
            continue

        if not countable:
            continue
        covered.add(scenario)
        if outcome == "expected_stop":
            safe_stops += 1
        elif work == "read_only":
            read_only_ok += 1
        else:
            planned += 1
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
    if {"normal", "alternate", "expected_stop"}.difference(covered):
        problems.append("须覆盖默认流程、账号变体及预期安全停止。")

    summary = (
        f"业务闭环 {completed}/{planned + failed}，预期安全停止 {safe_stops}，"
        f"只读巡检 {read_only_ok}，人工中止 {interrupted}，失败 {failed}"
    )
    if read_only_failed:
        summary += f"，只读失败 {read_only_failed}"
    return summary, problems


def _check_interrupted(
    run: dict,
    slice_lines: list[tuple[int, str]],
    started: datetime,
    ended: datetime,
) -> str | None:
    if not run["stop_reason"].strip():
        return "人工中止未写停止原因。"
    stopped_at = run.get("stopped_at")
    if not isinstance(stopped_at, str):
        return "人工中止未写停止时间（YYYY-MM-DD HH:MM:SS）。"
    try:
        stopped = datetime.strptime(stopped_at, LAUNCH_FORMAT)
    except (TypeError, ValueError):
        return "人工中止未写停止时间（YYYY-MM-DD HH:MM:SS）。"
    if not started <= stopped <= ended:
        return f"人工中止时间 {stopped_at} 不在本次启动边界内。"
    if not isinstance(run.get("state_at_stop"), str) or not run["state_at_stop"].strip():
        return "人工中止未写当时页面状态。"
    manual_at = next(
        (number for number, line in slice_lines if any(marker in line for marker in MANUAL_MARKERS)),
        None,
    )
    if manual_at is None:
        return "日志里没有玩家按下停止键的记录，不能记 interrupted。"
    for number, line in slice_lines:
        if number >= manual_at:
            break
        if any(marker in line for marker in FAILURE_MARKERS):
            return "停止键之前已有故障记录，应以首个故障分类，不得记 interrupted。"
    return None


def _terminal_error(
    run: dict,
    contract: dict,
    slice_lines: list[tuple[int, str]],
    slice_text: str,
    log_path: Path,
    base: Path,
) -> str | None:
    terminal = run["terminal"]
    if terminal["verified"] is not True:
        return "未确认约定终点。"
    evidence_path, start, end, error = _resolve_ref(terminal["evidence"], base)
    if error:
        return f"终点依据{error}"
    if evidence_path is None or evidence_path.resolve() != log_path.resolve():
        return "终点依据必须指向本次启动的日志。"
    lines_by_number = dict(slice_lines)
    if start is None or start not in lines_by_number or (end is not None and end not in lines_by_number):
        return "终点依据不在本次启动的日志边界内。"
    if any(marker_text in slice_text for marker_text in FAILURE_MARKERS):
        return "日志显示收尾失败、异常收尾或进入路线失败，不能记 completed / expected_stop。"
    marked = contract.get("terminal_marker")
    if isinstance(marked, str) and marked.strip():
        ok = all(marked in lines_by_number[number] for number in range(start, (end or start) + 1))
        shown = marked
    else:
        ok = all(
            TERMINAL_MARKER.search(lines_by_number[number]) is not None
            for number in range(start, (end or start) + 1)
        )
        shown = "收尾=已回到首页"
    if not ok:
        return f"终点所引用的行没有精确的约定终点标记「{shown}」。"
    return None


def _check_completed(
    run: dict,
    contract: dict,
    slice_lines: list[tuple[int, str]],
    slice_text: str,
    log_path: Path,
    base: Path,
) -> str | None:
    error = _terminal_error(run, contract, slice_lines, slice_text, log_path, base)
    if error:
        return error
    if run["work"] == "read_only":
        if run.get("target") is not None:
            return "只读巡检不应设置数量目标。"
        if not run["receipt"].strip():
            return "只读巡检未写读到的值和原文。"
        return None
    achieved = run.get("achieved")
    if achieved is None or achieved <= 0:
        return "业务运行没有实得数量，不能记 completed；零工作请按 expected_stop 记录。"
    target_quantity = run.get("target")
    if target_quantity is not None:
        if abs(achieved - target_quantity) > 1e-9:
            return (
                f"请求目标 {target_quantity}，实得 {achieved}；"
                "固定数量须与请求量一致，多出或不足都不能记 completed。"
            )
    else:
        _, _, _, error = _resolve_ref(run.get("end_evidence"), base)
        if error:
            return f"自然终点流程缺少可证伪的结束依据：{error}"
    if not run["receipt"].strip():
        return "业务运行未写可观察的业务回执。"
    return None


def _check_expected_stop(
    run: dict,
    contract: dict,
    slice_lines: list[tuple[int, str]],
    slice_text: str,
    log_path: Path,
    base: Path,
) -> str | None:
    reason = run["stop_reason"].strip()
    if not reason:
        return "预期安全停止未写停止原因。"
    declared = [item for item in contract.get("early_stop", []) if isinstance(item, str)]
    if not any(item in reason or reason in item for item in declared):
        return f"停止原因「{reason}」不在合同声明的提前停止条件内。"
    error = _terminal_error(run, contract, slice_lines, slice_text, log_path, base)
    if error:
        return error
    if run.get("achieved") == 0:
        _, _, _, error = _resolve_ref(run.get("zero_work_evidence"), base)
        if error:
            return f"零工作结束缺少「确实为空」的正向证据：{error}"
    if run["work"] == "business" and not run["receipt"].strip() and run.get("achieved"):
        return "有完成量但未写业务回执。"
    return None


def _check_resources(run: dict, contract: dict, outcome: str) -> str | None:
    declared = {
        item["name"].strip(): item["cap"]
        for item in contract.get("resources", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("cap"), (int, float))
        and not isinstance(item.get("cap"), bool)
    }
    resources = run.get("resources")
    if not isinstance(resources, list):
        return "缺少资源消耗核对（resources，可为空列表）。"
    spent: dict[str, float] = {}
    for index, item in enumerate(resources, 1):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return f"资源核对第 {index} 项缺少名称。"
        name = item["name"].strip()
        value = item.get("spent")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return f"资源「{name}」的消耗应为非负数。"
        if name not in declared:
            return f"消耗了合同未声明的资源「{name}」，按越权扣费处理。"
        spent[name] = spent.get(name, 0) + value
        if spent[name] > declared[name]:
            return (
                f"资源「{name}」本次启动合计消耗 {spent[name]} "
                f"超出声明上限 {declared[name]}。"
            )
    if outcome in {"completed", "expected_stop"} and run["work"] == "business":
        missing = set(declared).difference(spent)
        if missing:
            return "未核对合同资源：" + "、".join(sorted(missing)) + "。"
    return None


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
    notes: list[str] = []
    summary, problems = check_report(report, target, base=args.evidence.parent, notes=notes)
    if summary:
        print(summary)
    for problem in problems:
        print(f"- {problem}")
    if notes:
        print("待复核（不计入独立样本）：")
        for note in notes:
            print(f"- {note}")
    if problems:
        print("稳定版证据未通过。")
        return 1
    print("台账通过，待独立复核。以下事项工具无法判定：")
    for item in MANUAL_REVIEW:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
