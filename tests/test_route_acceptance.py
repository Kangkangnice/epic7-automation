"""Release evidence must record complete, separate runs for the claimed target.

测试分两层：
- **结构**：路线/后端/客户端/提交必须与发布目标一致，样本门槛照旧；
- **原始材料**：每条运行都要能回到一次启动的边界和可打开的日志行。
  后者是 2026-11-20 复审补的 —— 只填类别、代号、结果和布尔值的台账，
  旧检查器会给 10/10 通过，却无法发现同一启动换名、失败改填中止、终点与日志矛盾。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from auto_game_unified.tools.check_route_acceptance import _route_present, main

REVISION = "a" * 40
ROUTE = "craft_equipment"
CLIENT = "STOVE build A"
LOG_REF = "runtime_logs/epic7_craft_equipment.log"

REPLAY_TESTS = {
    "normal": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_page_recognition_covers_every_stable_page",
    "repeat": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_two_rounds_without_tidy",
    "overlay": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_dark_frame_is_not_a_click",
    "slow_or_frozen": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_sell_path_needs_quick_select_before_selling",
    "unknown": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_extract_path_recognises_its_own_popup",
    "end": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_export_names_follow_the_game",
}

OK_TERMINAL = "模式=craft_equipment 收尾=已回到首页 状态=可以衔接下一个任务"
FAILED_TERMINAL = "模式=craft_equipment 收尾=回首页失败 原因=连按 2 次 ESC 页面都没有变化（停在页面=craft_home）"
MANUAL_STOP = "用户按下 P，正在中断自动化"


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _append_launch(
    log: Path,
    started: datetime,
    *,
    terminal: str = OK_TERMINAL,
    before_terminal: tuple[str, ...] = (),
    manual: bool = False,
    achieved: int = 20,
) -> tuple[str, str, int, int]:
    """写一次启动，返回 (started_at, ended_at, first_line, total_lines)。"""
    lines = [
        f"{_stamp(started)} 模式=装备制作 轮次=1/2 请求=20 件",
        f"{_stamp(started + timedelta(seconds=30))} 模式=装备制作 状态=完成一遍 cycles=2 件数={achieved}",
    ]
    for offset, extra in enumerate(before_terminal, start=1):
        lines.append(f"{_stamp(started + timedelta(seconds=30 + offset))} {extra}")
    if manual:
        lines.append(f"{_stamp(started + timedelta(seconds=45))} 模式=craft_equipment {MANUAL_STOP}")
    else:
        lines.append(f"{_stamp(started + timedelta(seconds=60))} 模式=导航 流程=v2 页面=大厅 状态=已确认")
        lines.append(f"{_stamp(started + timedelta(seconds=60))} {terminal}")
    first = len(log.read_text(encoding="utf-8").splitlines()) + 1 if log.exists() else 1
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    ended = started + timedelta(seconds=61)
    return _stamp(started), _stamp(ended), first, len(lines)


def _run(
    index: int,
    started_at: str,
    ended_at: str,
    first_line: int,
    *,
    account: str = "A",
    environment: str = "setup-1",
    day: str = "2026-11-16",
    scenario: str = "normal",
    outcome: str = "completed",
    work: str = "business",
    target: int | None = 20,
    achieved: int | None = 20,
    terminal_verified: bool = True,
    stop_reason: str = "",
    first_failure: str = "",
    run_id: str | None = None,
) -> dict:
    return {
        "id": run_id or f"run-{index:02d}",
        "launch": {"log": LOG_REF, "started_at": started_at, "ended_at": ended_at},
        "route": ROUTE,
        "backend": "pc",
        "client": CLIENT,
        "revision": REVISION,
        "account": account,
        "environment": environment,
        "day": day,
        "scenario": scenario,
        "work": work,
        "requested": "2 轮 × 10 件，共 20 件",
        "target": target,
        "achieved": achieved,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "first_failure": first_failure,
        "receipt": "结果页「制作完毕」，cycles=2 件数=20",
        "terminal": {"verified": terminal_verified, "evidence": f"{LOG_REF}#L{first_line + 3}"},
        "resources": [{"name": "金币", "spent": 210000}],
        "evidence": [f"{LOG_REF}#L{first_line}-L{first_line + 1}"],
    }


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    """十次独立启动、两个账号、两个环境、跨三天；另加一次预期安全停止。"""
    log = tmp_path / LOG_REF
    log.parent.mkdir(parents=True)
    runs = []
    for index in range(10):
        day_number = 16 + index % 3
        started = datetime(2026, 11, day_number, 10 + index // 3, 0, 0)
        started_at, ended_at, first, _ = _append_launch(log, started)
        runs.append(_run(
            index, started_at, ended_at, first,
            account="A" if index < 5 else "B",
            environment="setup-1" if index < 5 else "setup-2",
            day=f"2026-11-{day_number}",
            scenario="normal" if index < 5 else "alternate",
        ))
    started = datetime(2026, 11, 18, 15, 0, 0)
    started_at, ended_at, first, _ = _append_launch(
        log, started, before_terminal=("模式=装备制作 停止=讨伐材料不足 已完成=10",), achieved=10,
    )
    expected_stop_run = _run(
        10, started_at, ended_at, first, account="B", environment="setup-2", day="2026-11-18",
        scenario="expected_stop", outcome="expected_stop", target=20, achieved=10,
        stop_reason="讨伐材料不足",
    )
    expected_stop_run["terminal"]["evidence"] = f"{LOG_REF}#L{first + 4}"
    runs.append(expected_stop_run)

    replay_dir = tmp_path / "reports" / "replay"
    replay_dir.mkdir(parents=True)
    replay = []
    for case, node in REPLAY_TESTS.items():
        proof = replay_dir / f"{case}.txt"
        proof.write_text(
            f"node={node} revision={REVISION} result=1 passed\n", encoding="utf-8"
        )
        replay.append({"case": case, "test": node, "evidence": f"reports/replay/{case}.txt"})

    report = {
        "schema": 2,
        "route": ROUTE,
        "backend": "pc",
        "client": CLIENT,
        "revision": REVISION,
        "contract": {
            "entry": "大厅 → 快捷菜单 → 钢铁工坊 → 制作装备",
            "settings": "整理关闭、出售与萃取关闭、每轮制作次数 10",
            "goal": "按请求轮次制作装备",
            "unit": "件",
            "receipt": "制作结果页「制作完毕」且累计件数等于请求轮次×10",
            "terminal": "回到大厅",
            "early_stop": ["讨伐材料不足", "金币不足", "装备背包已满", "今日次数已用完"],
            "resources": [{"name": "金币", "cap": 240000}],
        },
        "replay_cases": replay,
        "runs": runs,
    }
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def check(path: Path, *, client: str = CLIENT, route: str = ROUTE) -> int:
    return main([
        str(path), "--route", route, "--backend", "pc",
        "--client", client, "--revision", REVISION,
    ])


# ---------------------------------------------------------------- 正例


def test_complete_evidence_passes(evidence: Path, capsys):
    assert check(evidence) == 0
    out = capsys.readouterr().out
    assert "业务闭环 10/10" in out
    assert "预期安全停止 1" in out
    assert "台账通过，待独立复核" in out


def test_two_independent_starts_in_one_log_are_accepted(evidence: Path):
    """同一日志文件里的两次启动是两个样本；边界不同就不算重报。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 18, 16, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started)
    report["runs"][1] = _run(
        1, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-18", scenario="normal",
    )
    _save(evidence, report)
    assert check(evidence) == 0


def test_legal_read_only_run_is_reported_separately(evidence: Path, capsys):
    """只读巡检可以成功，但只进只读栏，不进打图分子。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 9, 0, 0)
    started_at, ended_at, first, _ = _append_launch(
        log, started, before_terminal=("模式=支线故事 停止=支线刷新倒计时已读取 已完成=0",), achieved=0,
    )
    read_only = _run(
        11, started_at, ended_at, first, account="A", environment="setup-1", day="2026-11-19",
        scenario="read_only", work="read_only", target=None, achieved=0,
    )
    read_only["receipt"] = "读到「剩余 6 天 2 小时」，完成数 0"
    read_only["terminal"]["evidence"] = f"{LOG_REF}#L{first + 4}"
    report["runs"].append(read_only)
    _save(evidence, report)
    assert check(evidence) == 0
    assert "只读巡检 1" in capsys.readouterr().out


def test_declared_zero_work_end_needs_positive_evidence(evidence: Path, capsys):
    """零工作结束按 expected_stop 记，且必须有「确实为空」的正向证据。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 10, 0, 0)
    started_at, ended_at, first, _ = _append_launch(
        log, started, before_terminal=("模式=装备制作 停止=今日次数已用完 已完成=0",), achieved=0,
    )
    zero = _run(
        12, started_at, ended_at, first, account="A", environment="setup-1", day="2026-11-19",
        scenario="expected_stop", outcome="expected_stop", target=20, achieved=0,
        stop_reason="今日次数已用完",
    )
    zero["zero_work_evidence"] = f"{LOG_REF}#L{first + 2}"
    zero["terminal"]["evidence"] = f"{LOG_REF}#L{first + 4}"
    report["runs"].append(zero)
    _save(evidence, report)
    assert "预期安全停止 2" in _run_and_capture(evidence, capsys)

    zero.pop("zero_work_evidence")
    _save(evidence, report)
    assert check(evidence) == 1


def test_true_manual_stop_is_accepted(evidence: Path, capsys):
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 11, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started, manual=True, achieved=4)
    stop = _run(
        13, started_at, ended_at, first, account="A", environment="setup-1", day="2026-11-19",
        scenario="normal", outcome="interrupted", achieved=4, terminal_verified=False,
        stop_reason="玩家主动取消（按 P）",
    )
    stop.update({"stopped_at": "2026-11-19 11:00:45", "state_at_stop": "小节列表（第 4 章）"})
    report["runs"].append(stop)
    _save(evidence, report)
    assert check(evidence) == 0
    assert "人工中止 1" in capsys.readouterr().out


def _run_and_capture(path: Path, capsys) -> str:
    assert check(path) == 0
    return capsys.readouterr().out


# ---------------------------------------------------------------- 反例


def test_same_launch_under_a_second_id_is_rejected(evidence: Path, capsys):
    """同一次启动换 ID 重报，会把一个样本凑成两个。"""
    report = _load(evidence)
    duplicate = dict(report["runs"][0])
    duplicate["id"] = "run-99"
    report["runs"].append(duplicate)
    _save(evidence, report)
    assert check(evidence) == 1
    assert "同一次启动" in capsys.readouterr().out


def test_read_only_inspection_cannot_masquerade_as_battle(evidence: Path, capsys):
    """同名同入口的只读巡检，不得填成打图成功。"""
    report = _load(evidence)
    report["runs"][0]["scenario"] = "read_only"
    report["runs"][0]["work"] = "read_only"
    _save(evidence, report)
    assert check(evidence) == 1
    assert "只读" in capsys.readouterr().out


def test_two_requested_rounds_with_one_completed_is_rejected(evidence: Path, capsys):
    report = _load(evidence)
    report["runs"][0]["achieved"] = 10
    _save(evidence, report)
    assert check(evidence) == 1
    assert "实得" in capsys.readouterr().out


def test_business_done_but_closeout_failed_is_rejected(evidence: Path, capsys):
    """做完 20 件但没回到大厅：业务计数成立，整次闭环记失败。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 12, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started, terminal=FAILED_TERMINAL)
    failed_closeout = _run(
        14, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-19", scenario="normal", outcome="completed",
    )
    report["runs"][0] = failed_closeout
    _save(evidence, report)
    assert check(evidence) == 1
    assert "收尾" in capsys.readouterr().out


def test_closeout_unverified_cannot_be_completed(evidence: Path):
    report = _load(evidence)
    report["runs"][0]["terminal"]["verified"] = False
    _save(evidence, report)
    assert check(evidence) == 1


def test_failure_then_manual_stop_cannot_be_recorded_as_interrupted(evidence: Path, capsys):
    """先有故障再按 P，以首个故障分类，不得改填人工中止。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 13, 0, 0)
    started_at, ended_at, first, _ = _append_launch(
        log, started, before_terminal=(FAILED_TERMINAL,), manual=True, achieved=20,
    )
    stop = _run(
        15, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-19", scenario="normal", outcome="interrupted", achieved=20,
        terminal_verified=False, stop_reason="玩家主动取消（按 P）",
        first_failure="收尾=回首页失败",
    )
    stop.update({"stopped_at": "2026-11-19 13:00:45", "state_at_stop": "制作页"})
    report["runs"][0] = stop
    _save(evidence, report)
    assert check(evidence) == 1
    assert "首个故障" in capsys.readouterr().out


def test_replay_with_only_category_names_is_rejected(evidence: Path, capsys):
    report = _load(evidence)
    report["replay_cases"] = list(REPLAY_TESTS)
    _save(evidence, report)
    assert check(evidence) == 1
    assert "测试节点" in capsys.readouterr().out


def test_missing_evidence_reference_is_rejected(evidence: Path, capsys):
    report = _load(evidence)
    report["runs"][0]["evidence"] = ["runtime_logs/not_there.log#L1-L2"]
    _save(evidence, report)
    assert check(evidence) == 1
    assert "打不开" in capsys.readouterr().out


def test_terminal_evidence_outside_the_launch_window_is_rejected(evidence: Path):
    report = _load(evidence)
    report["runs"][0]["terminal"]["evidence"] = f"{LOG_REF}#L8"
    _save(evidence, report)
    assert check(evidence) == 1


def test_resource_spend_above_the_declared_cap_is_rejected(evidence: Path, capsys):
    report = _load(evidence)
    report["runs"][0]["resources"] = [{"name": "金币", "spent": 999999}]
    _save(evidence, report)
    assert check(evidence) == 1
    assert "上限" in capsys.readouterr().out


def test_replay_node_must_exist_in_the_named_test(evidence: Path):
    report = _load(evidence)
    report["replay_cases"][0]["test"] = "tests/test_epic7_craft_equipment.py::test_does_not_exist"
    _save(evidence, report)
    assert check(evidence) == 1


# ---------------------------------------------------------------- 退回单反例（2026-11-20）

ABNORMAL_TERMINAL = "模式=craft_equipment 异常收尾=已回到首页 状态=可以衔接下一个任务"


def _append_failed(log: Path, started: datetime) -> tuple[str, str, int]:
    started_at, ended_at, first, _ = _append_launch(
        log, started, before_terminal=("模式=装备制作 停止=未识别页面 已完成=0",), achieved=0,
    )
    run = _run(
        20, started_at, ended_at, first, account="A", environment="setup-1",
        day=started.strftime("%Y-%m-%d"), scenario="normal", outcome="failed",
        achieved=0, terminal_verified=False, stop_reason="未识别页面，安全停止",
    )
    return run


def test_one_real_failure_blocks_the_whole_plan(evidence: Path, capsys):
    """同一业务计划出现一次真实失败，就不能声明稳定支持。"""
    report = _load(evidence)
    report["runs"].append(_append_failed(evidence.parent / LOG_REF, datetime(2026, 11, 19, 14, 0, 0)))
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "10/11" in out
    assert "真实失败" in out


def test_expected_stop_in_a_normal_scenario_is_rejected(evidence: Path, capsys):
    """预登记为正常完成，实际记预期停止：按实际结果统计并退回场景冲突。"""
    report = _load(evidence)
    report["runs"][0]["outcome"] = "expected_stop"
    report["runs"][0]["stop_reason"] = "讨伐材料不足"
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "9/9" in out
    assert "预期安全停止 2" in out
    assert "场景" in out


def test_abnormal_closeout_cannot_prove_completion(evidence: Path, capsys):
    """异常收尾即使回到了大厅，也不是正常终点。"""
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 15, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started, terminal=ABNORMAL_TERMINAL)
    report["runs"][0] = _run(
        0, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-19", scenario="normal", outcome="completed",
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "异常收尾" in capsys.readouterr().out


def test_copied_launch_with_shifted_start_is_not_ten_samples(evidence: Path, capsys):
    """同一启动复制十份、只把开始时间往前挪，不算十个独立样本。"""
    report = _load(evidence)
    base = report["runs"][0]
    copies = []
    for index in range(10):
        item = json.loads(json.dumps(base))
        item["id"] = f"copy-{index}"
        start = datetime.strptime(base["launch"]["started_at"], "%Y-%m-%d %H:%M:%S") - timedelta(seconds=index)
        item["launch"]["started_at"] = _stamp(start)
        item["launch"]["ended_at"] = _stamp(start + timedelta(seconds=61))
        copies.append(item)
    report["runs"] = copies
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "重复" in out or "重叠" in out


def test_cross_route_log_cannot_prove_work(evidence: Path, capsys):
    """拿支线倒计时的日志充当装备制作 20 件的业务依据，应识别路线矛盾。"""
    report = _load(evidence)
    side = evidence.parent / "runtime_logs" / "epic7_side_story.log"
    side.write_text(
        "2026-11-20 08:21:40 模式=side_story 停止=支线刷新倒计时已读取 已完成=0\n"
        "2026-11-20 08:21:55 模式=side_story 收尾=已回到首页 状态=可以衔接下一个任务\n",
        encoding="utf-8",
    )
    report["runs"][0]["launch"] = {
        "log": "runtime_logs/epic7_side_story.log",
        "started_at": "2026-11-20 08:21:40",
        "ended_at": "2026-11-20 08:21:56",
    }
    report["runs"][0]["day"] = "2026-11-20"
    report["runs"][0]["evidence"] = ["runtime_logs/epic7_side_story.log#L1-L2"]
    report["runs"][0]["terminal"] = {
        "verified": True, "evidence": "runtime_logs/epic7_side_story.log#L2",
    }
    _save(evidence, report)
    assert check(evidence) == 1
    assert "路线" in capsys.readouterr().out


def test_achieved_cannot_exceed_the_requested_quantity(evidence: Path, capsys):
    report = _load(evidence)
    report["runs"][0]["achieved"] = 40
    _save(evidence, report)
    assert check(evidence) == 1
    assert "实得" in capsys.readouterr().out


def test_duplicate_resource_rows_are_summed(evidence: Path, capsys):
    """同一启动列两条各 210,000，合计已超过 240,000 上限。"""
    report = _load(evidence)
    report["runs"][0]["resources"] = [
        {"name": "金币", "spent": 210000},
        {"name": "金币", "spent": 210000},
    ]
    _save(evidence, report)
    assert check(evidence) == 1
    assert "上限" in capsys.readouterr().out


def test_manual_stop_time_must_fall_inside_the_launch(evidence: Path, capsys):
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 16, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started, manual=True, achieved=4)
    stop = _run(
        21, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-19", scenario="normal", outcome="interrupted", achieved=4,
        terminal_verified=False, stop_reason="玩家主动取消（按 P）",
    )
    stop.update({"stopped_at": "2019-01-01 00:00:00", "state_at_stop": "小节列表"})
    report["runs"].append(stop)
    _save(evidence, report)
    assert check(evidence) == 1
    assert "不在本次启动边界内" in capsys.readouterr().out


def test_interrupted_run_still_checks_resource_caps(evidence: Path, capsys):
    report = _load(evidence)
    log = evidence.parent / LOG_REF
    started = datetime(2026, 11, 19, 17, 0, 0)
    started_at, ended_at, first, _ = _append_launch(log, started, manual=True, achieved=4)
    stop = _run(
        22, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-19", scenario="normal", outcome="interrupted", achieved=4,
        terminal_verified=False, stop_reason="玩家主动取消（按 P）",
    )
    stop.update({
        "stopped_at": _stamp(started + timedelta(seconds=45)),
        "state_at_stop": "小节列表",
        "resources": [{"name": "金币", "spent": 1000000}],
    })
    report["runs"].append(stop)
    _save(evidence, report)
    assert check(evidence) == 1
    assert "上限" in capsys.readouterr().out


def test_replay_class_must_exist(evidence: Path, capsys):
    report = _load(evidence)
    report["replay_cases"][0]["test"] = (
        "tests/test_epic7_craft_equipment.py::NoSuchClass::test_page_recognition_covers_every_stable_page"
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "类" in capsys.readouterr().out


def test_replay_evidence_must_record_a_pass(evidence: Path, capsys):
    report = _load(evidence)
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(
        f"node={REPLAY_TESTS['normal']} revision={REVISION} result=1 failed\n", encoding="utf-8"
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "失败" in capsys.readouterr().out


def test_replay_evidence_must_name_the_revision(evidence: Path, capsys):
    report = _load(evidence)
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(
        f"node={REPLAY_TESTS['normal']} result=1 passed\n", encoding="utf-8"
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "提交" in capsys.readouterr().out


def test_missing_resource_cap_returns_a_message_not_a_traceback(evidence: Path, capsys):
    report = _load(evidence)
    del report["contract"]["resources"][0]["cap"]
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "上限" in out
    assert "Traceback" not in out


# ---------------------------------------------------------------- 87293c4 复验反例


def _write_craft_segment(path: Path, *, items: int, terminal: str) -> tuple[str, str, int]:
    lines = [
        "2026-11-17 22:20:31 模式=装备制作 轮次=1/1 请求中间帧",
        f"2026-11-17 22:20:35 模式=装备制作 状态=完成一遍 cycles={items // 10} 件数={items}",
        f"2026-11-17 22:21:30 模式=craft_equipment {terminal}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "2026-11-17 22:20:31", "2026-11-17 22:21:31", 1


def test_ledger_must_match_the_logs_final_business_count(evidence: Path, capsys):
    """同一段日志写 1 轮 10 件，台账不能申报请求 20、实得 20。"""
    report = _load(evidence)
    segment = evidence.parent / "runtime_logs" / "craft_actual.log"
    started_at, ended_at, first = _write_craft_segment(
        segment, items=10, terminal="收尾=已回到首页 状态=可以衔接下一个任务"
    )
    run = _run(
        0, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-17", scenario="normal", outcome="completed", target=20, achieved=20,
    )
    run["launch"]["log"] = "runtime_logs/craft_actual.log"
    run["terminal"] = {"verified": True, "evidence": "runtime_logs/craft_actual.log#L3"}
    run["evidence"] = ["runtime_logs/craft_actual.log#L1-L2"]
    report["runs"][0] = run
    _save(evidence, report)
    assert check(evidence) == 1
    assert "实得" in capsys.readouterr().out


def test_the_same_segment_is_valid_with_the_real_count(evidence: Path):
    """真实请求 10、实得 10 的同一段证据可以成立。"""
    report = _load(evidence)
    segment = evidence.parent / "runtime_logs" / "craft_actual.log"
    started_at, ended_at, first = _write_craft_segment(
        segment, items=10, terminal="收尾=已回到首页 状态=可以衔接下一个任务"
    )
    run = _run(
        0, started_at, ended_at, first, account="A", environment="setup-1",
        day="2026-11-17", scenario="normal", outcome="completed", target=10, achieved=10,
    )
    run["launch"]["log"] = "runtime_logs/craft_actual.log"
    run["terminal"] = {"verified": True, "evidence": "runtime_logs/craft_actual.log#L3"}
    run["evidence"] = ["runtime_logs/craft_actual.log#L1-L2"]
    report["runs"][0] = run
    _save(evidence, report)
    assert check(evidence) == 0


def test_chinese_route_label_keeps_a_real_failure_in_the_denominator(evidence: Path, capsys):
    """装备制作日志只写中文模式名；真实失败须计入分母，不得误报跨路线。"""
    report = _load(evidence)
    log = evidence.parent / "runtime_logs" / "craft_cn.log"
    log.write_text(
        "2026-11-17 21:59:30 模式=装备制作 轮次=2/2 请求中间帧\n"
        "2026-11-17 22:00:25 模式=装备制作 状态=完成一遍 cycles=2 件数=20\n"
        "2026-11-17 22:01:32 模式=装备制作 收尾=回首页失败 原因=连按两次 ESC 页面都没有变化\n",
        encoding="utf-8",
    )
    failed = _run(
        20, "2026-11-17 21:59:30", "2026-11-17 22:01:33", 1,
        account="A", environment="setup-1", day="2026-11-17", scenario="normal",
        outcome="failed", target=20, achieved=20, terminal_verified=False,
        stop_reason="业务完成但收尾失败", first_failure="收尾=回首页失败",
    )
    failed["launch"]["log"] = "runtime_logs/craft_cn.log"
    failed["evidence"] = ["runtime_logs/craft_cn.log#L1-L2"]
    report["runs"].append(failed)
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "10/11" in out
    assert "失败 1" in out
    assert "路线" not in out


def test_replay_node_result_must_belong_to_that_node(evidence: Path, capsys):
    """目标节点 SKIPPED、别的节点 PASSED，不得算目标节点通过。"""
    report = _load(evidence)
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(
        f"node={REPLAY_TESTS['normal']} revision={REVISION} result=SKIPPED\n"
        f"node={REPLAY_TESTS['repeat']} revision={REVISION} result=1 passed\n",
        encoding="utf-8",
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "通过记录" in capsys.readouterr().out


def test_replay_node_cannot_drop_the_class_of_a_method(evidence: Path, capsys):
    """真实节点是类方法；去掉类名后 pytest 无法收集该节点。"""
    report = _load(evidence)
    node = REPLAY_TESTS["normal"]
    report["replay_cases"][0]["test"] = (
        "tests/test_epic7_craft_equipment.py::test_page_recognition_covers_every_stable_page"
    )
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(
        f"node={node} revision={REVISION} result=1 passed\n", encoding="utf-8"
    )
    _save(evidence, report)
    assert check(evidence) == 1
    assert "类名" in capsys.readouterr().out


def test_overlapping_stop_cannot_satisfy_the_required_coverage(evidence: Path, capsys):
    """待核的预期停止不贡献覆盖项，不能凑必做安全停止。"""
    report = _load(evidence)
    stop = report["runs"][-1]
    earlier = datetime.strptime(report["runs"][8]["launch"]["started_at"], "%Y-%m-%d %H:%M:%S")
    stop["launch"]["started_at"] = _stamp(earlier - timedelta(seconds=1))
    stop["launch"]["ended_at"] = report["runs"][8]["launch"]["ended_at"]
    _save(evidence, report)
    assert check(evidence) == 1
    out = capsys.readouterr().out
    assert "待复核" in out
    assert "预期安全停止" in out


@pytest.mark.parametrize("field", ["account", "environment"])
def test_blank_identity_cannot_meet_the_second_variant(evidence: Path, capsys, field):
    report = _load(evidence)
    for run in report["runs"][5:10]:
        run[field] = "   "
    _save(evidence, report)
    assert check(evidence) == 1
    assert "空白" in capsys.readouterr().out


# ---------------------------------------------------------------- e8971e3 复验反例


def test_route_field_must_match_the_complete_mode_token(evidence: Path, capsys):
    """story_star 与中文「主线补星」都不能为 story 贡献样本。"""
    report = _load(evidence)
    other = evidence.parent / "runtime_logs" / "story_star_only.log"
    other.write_text(
        "2026-11-10 20:48:28 模式=story_star 开局\n"
        "2026-11-10 20:53:11 模式=主线补星 动作=按 P\n"
        "2026-11-10 20:53:12 模式=story_star 收尾=已回到首页 状态=可以衔接下一个任务\n",
        encoding="utf-8",
    )
    for run in report["runs"]:
        run["route"] = "story"
    first = report["runs"][0]
    first["launch"] = {
        "log": "runtime_logs/story_star_only.log",
        "started_at": "2026-11-10 20:48:28",
        "ended_at": "2026-11-10 20:53:13",
    }
    first["day"] = "2026-11-10"
    first["evidence"] = ["runtime_logs/story_star_only.log#L1-L2"]
    first["terminal"]["evidence"] = "runtime_logs/story_star_only.log#L3"
    report["route"] = "story"
    _save(evidence, report)
    assert check(evidence, route="story") == 1
    assert "路线" in capsys.readouterr().out


def test_route_presence_accepts_its_own_english_and_chinese_fields():
    assert _route_present("2026-11-16 模式=story 状态=转场确认", "story")
    assert _route_present("2026-11-16 模式=主线 状态=完成", "story")
    assert not _route_present("2026-11-10 模式=story_star 状态=开始", "story")
    assert not _route_present("2026-11-10 模式=主线补星 状态=开始", "story")
    assert _route_present("2026-11-17 模式=装备制作 状态=完成一遍", "craft_equipment")


def test_module_level_replay_node_is_collectible(evidence: Path):
    node = "tests/test_shop_refresh_runner.py::test_initial_purchases_do_not_enter_paid_hit_rate"
    report = _load(evidence)
    report["replay_cases"][0]["test"] = node
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(f"node={node} revision={REVISION} result=1 passed\n", encoding="utf-8")
    _save(evidence, report)
    assert check(evidence) == 0


def test_replay_node_must_belong_to_the_named_class(evidence: Path, capsys):
    node = (
        "tests/test_epic7_side_story_resume.py::SideStoryEventHomeResumeTests::"
        "test_each_recorded_page_lands_on_the_right_state"
    )
    report = _load(evidence)
    report["replay_cases"][0]["test"] = node
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(f"node={node} revision={REVISION} result=1 passed\n", encoding="utf-8")
    _save(evidence, report)
    assert check(evidence) == 1
    assert "收集" in capsys.readouterr().out


def test_replay_result_must_name_the_exact_node(evidence: Path, capsys):
    node = REPLAY_TESTS["normal"]
    report = _load(evidence)
    proof = evidence.parent / "reports" / "replay" / "normal.txt"
    proof.write_text(f"node={node}_other revision={REVISION} result=1 passed\n", encoding="utf-8")
    _save(evidence, report)
    assert check(evidence) == 1
    assert "未指向该测试节点" in capsys.readouterr().out


# ---------------------------------------------------------------- 历史台账


def test_legacy_report_is_history_only(capsys):
    """旧格式台账保留为历史证据，但不能作为稳定版准入。"""
    legacy = Path(__file__).parent / "fixtures" / "acceptance" / "legacy_v1_synthetic.json"
    assert check(legacy) == 1
    assert "旧格式" in capsys.readouterr().out


# ---------------------------------------------------------------- 原有结构门槛


def test_one_development_smoke_does_not_qualify(evidence: Path):
    report = _load(evidence)
    report["runs"] = report["runs"][:1]
    _save(evidence, report)
    assert check(evidence) == 1


@pytest.mark.parametrize("change", [
    {"id": "run-00"},
    {"outcome": "failed"},
    {"terminal": {"verified": False, "evidence": f"{LOG_REF}#L4"}},
    {"outcome": "expected_stop"},
    {"day": "2026-11-32"},
    {"account": None},
])
def test_missing_or_failed_attempt_is_rejected(evidence: Path, change):
    report = _load(evidence)
    report["runs"][1].update(change)
    _save(evidence, report)
    assert check(evidence) == 1


def test_expected_stop_needs_live_evidence_and_replay(evidence: Path):
    report = _load(evidence)
    report["runs"][-1]["terminal"]["verified"] = False
    _save(evidence, report)
    assert check(evidence) == 1
    report = _load(evidence)
    report["runs"][-1]["terminal"]["verified"] = True
    report["replay_cases"].pop()
    _save(evidence, report)
    assert check(evidence) == 1


def test_unsafe_action_blocks_even_an_expected_stop_scenario(evidence: Path):
    report = _load(evidence)
    report["runs"][-1]["outcome"] = "unsafe"
    report["runs"][-1]["stop_reason"] = "误点购买按钮"
    _save(evidence, report)
    assert check(evidence) == 1


def test_steam_cannot_inherit_stove_evidence(evidence: Path):
    assert check(evidence, client="Steam build A") == 1


@pytest.mark.parametrize(("field", "value"), [
    ("route", "pet_adoption"),
    ("backend", "emulator"),
    ("client", "Steam build A"),
    ("revision", "b" * 40),
    ("client", None),
])
def test_mixed_targets_cannot_share_a_single_report(evidence: Path, field, value):
    report = _load(evidence)
    report["runs"][1][field] = value
    _save(evidence, report)
    assert check(evidence) == 1


@pytest.mark.parametrize("field", ["account", "environment", "day", "scenario"])
def test_same_conditions_do_not_prove_compatibility(evidence: Path, field):
    report = _load(evidence)
    for run in report["runs"][:10]:
        run[field] = report["runs"][0][field]
    _save(evidence, report)
    assert check(evidence) == 1
