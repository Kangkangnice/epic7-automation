"""单路线与每日任务共用同一道 PC 实跑预检（审查 B）。

规则：PC 实跑在进入业务编排/建 runtime 之前先拒绝；干跑、模拟器、离线探针
不触发 PC 专用预检。预检通过时只分发一次。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from auto_game_unified import main as cli


DAILY_PC_LIVE = [
    "--daily",
    "--daily-tasks",
    "arena:1",
    "--window-backend",
    "pc",
    "--live",
    "--confirm",
    "RUN",
]
SINGLE_PC_LIVE = [
    "--mode",
    "arena",
    "--max-cycles",
    "1",
    "--window-backend",
    "pc",
    "--live",
    "--confirm",
    "RUN",
]


def _drive(monkeypatch, argv, *, precheck):
    calls = {"precheck": 0, "daily": 0, "mode": 0}

    def fake_precheck(backend: str) -> str | None:
        calls["precheck"] += 1
        return precheck

    def fake_daily(args) -> int:
        calls["daily"] += 1
        return 0

    def fake_run_mode(**kwargs):
        calls["mode"] += 1
        return SimpleNamespace(
            resource_exhausted=False,
            completed_cycles=1,
            outcome_summary=None,
            closeout_warning=None,
            stopped_during_closeout=False,
        )

    monkeypatch.setattr(cli, "_pc_live_precondition", fake_precheck)
    monkeypatch.setattr(cli, "_run_daily", fake_daily)
    monkeypatch.setattr(cli, "run_mode", fake_run_mode)
    monkeypatch.setattr(cli, "_notify_live", lambda **kwargs: None)

    try:
        code = cli.main(argv)
        error = None
    except SystemExit as exc:
        code = None
        error = str(exc)
    return code, error, calls


@pytest.mark.parametrize("argv", [DAILY_PC_LIVE, SINGLE_PC_LIVE], ids=["daily", "single"])
def test_pc_live_rejects_before_any_business(monkeypatch, argv):
    code, error, calls = _drive(monkeypatch, argv, precheck="测试拒绝：PC 窗口未就绪")

    assert code is None
    assert "测试拒绝：PC 窗口未就绪" in (error or "")
    assert calls == {"precheck": 1, "daily": 0, "mode": 0}


@pytest.mark.parametrize("argv", [DAILY_PC_LIVE, SINGLE_PC_LIVE], ids=["daily", "single"])
def test_pc_live_passes_and_dispatches_once(monkeypatch, argv):
    code, error, calls = _drive(monkeypatch, argv, precheck=None)

    assert (code, error) == (0, None)
    assert calls["precheck"] == 1
    assert calls["daily"] + calls["mode"] == 1


@pytest.mark.parametrize(
    "argv,entry",
    [
        (DAILY_PC_LIVE, "daily"),
        (SINGLE_PC_LIVE, "mode"),
    ],
    ids=["daily", "single"],
)
@pytest.mark.parametrize("confirm", [[], ["--confirm", "YES"]], ids=["missing", "wrong"])
def test_bad_run_confirmation_rejects_without_precheck(monkeypatch, argv, entry, confirm):
    broken = list(argv)
    if confirm:
        broken[broken.index("RUN")] = confirm[1]
    else:
        index = broken.index("--confirm")
        del broken[index : index + 2]

    code, error, calls = _drive(monkeypatch, broken, precheck="预检不该被调用")

    assert code is None
    assert "实跑模式需要附加参数：--live --confirm RUN" in (error or "")
    assert calls["precheck"] == 0
    assert calls["daily"] == 0 and calls["mode"] == 0


@pytest.mark.parametrize(
    "extra, expected",
    [
        (["--max-cycles", "0"], "实跑模式要求 --max-cycles 为正数"),
        (
            ["--max-cycles", "1", "--start-state", "lobby"],
            "--start-state 仅在空跑诊断模式可用",
        ),
    ],
    ids=["max-cycles-zero", "start-state-on-live"],
)
def test_bad_live_arguments_are_reported_before_the_pc_precheck(
    monkeypatch, extra, expected
):
    """参数本身不合法时先报参数错：修好 PC 环境也救不了这条命令（审查 B 复验）。"""

    argv = [
        "--mode",
        "arena",
        "--window-backend",
        "pc",
        "--live",
        "--confirm",
        "RUN",
        *extra,
    ]

    code, error, calls = _drive(monkeypatch, argv, precheck="PC 未就绪")

    assert code is None
    assert expected in (error or "")
    assert "PC 未就绪" not in (error or ""), "不许把参数错误报成环境错误"
    assert calls["precheck"] == 0
    assert calls["daily"] == 0 and calls["mode"] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["--daily", "--daily-tasks", "arena:1", "--window-backend", "pc"],
        [
            "--daily", "--daily-tasks", "arena:1",
            "--window-backend", "emulator", "--live", "--confirm", "RUN",
        ],
        ["--daily", "--daily-tasks", "arena:1", "--window-backend", "emulator"],
        ["--mode", "arena", "--max-cycles", "1", "--window-backend", "pc"],
        ["--mode", "arena", "--window-backend", "emulator"],
        [
            "--mode", "arena", "--max-cycles", "1",
            "--window-backend", "emulator", "--live", "--confirm", "RUN",
        ],
    ],
    ids=[
        "daily-pc-dry",
        "daily-emulator-live",
        "daily-emulator-dry",
        "single-pc-dry",
        "single-emulator-dry",
        "single-emulator-live",
    ],
)
def test_non_pc_live_paths_never_touch_the_pc_precheck(monkeypatch, argv):
    code, error, calls = _drive(monkeypatch, argv, precheck="预检不该被调用")

    assert (code, error) == (0, None)
    assert calls["precheck"] == 0
    assert calls["daily"] + calls["mode"] == 1


def test_offline_probe_does_not_touch_the_pc_precheck(monkeypatch):
    def forbidden(backend: str) -> str | None:
        pytest.fail("离线探针不该调用 PC 实跑预检")

    monkeypatch.setattr(cli, "_pc_live_precondition", forbidden)

    assert cli.main(["--offline-probe", "0.01"]) == 0
