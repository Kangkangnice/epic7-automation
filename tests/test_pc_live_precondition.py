"""PC 后端实跑前的权限闸门。

为什么要专门守这条
------------------
权限不对时点击会被 Windows 静默拦掉：截图正常、识别正常、日志里每个动作都写「已点击」，
游戏一动不动。过去 agent 遇到这种情况会「各种尝试」十几分钟 —— 用户原话：
「要不然就停下来了，要不然就去各种尝试」。

闸门的职责不是自动提权（要不要弹 UAC 取决于那台机器的设置，探不出来也不该猜），
而是**当场拦下并给出下一步命令**，不让 agent 在错的前提上瞎试。
"""

from __future__ import annotations

import pytest

from auto_game_unified.desktop import preflight
from auto_game_unified import main as main_module


def _report(status: preflight.PreflightStatus, message: str) -> preflight.PreflightReport:
    return preflight.PreflightReport(status=status, message=message)


# ---------------------------------------------------------------- 单元：前置检查


def test_emulator_backend_is_never_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟器后端不该为 PC 专用的检查付出代价（也不该被它拦住）。"""

    def explode(*_args, **_kwargs):
        raise AssertionError("模拟器后端不该去枚举 PC 窗口")

    monkeypatch.setattr(preflight, "run_preflight", explode)
    assert main_module._pc_live_precondition("emulator") is None


def test_a_blocking_report_becomes_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "run_preflight",
        lambda **_kwargs: _report(preflight.PreflightStatus.BLOCK, "权限不一致"),
    )
    reason = main_module._pc_live_precondition("pc")
    assert reason is not None and "权限不一致" in reason


def test_a_passing_report_lets_it_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "run_preflight",
        lambda **_kwargs: _report(preflight.PreflightStatus.PASS, "就绪"),
    )
    assert main_module._pc_live_precondition("pc") is None


# ---------------------------------------------------------------- 接线：命令行


def test_a_live_pc_run_is_refused_with_the_doc_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """被拦下时必须告诉人「去看哪份文档」，否则拦了也白拦。"""
    monkeypatch.setattr(main_module, "_pc_live_precondition", lambda _b: "PC 未就绪")

    with pytest.raises(SystemExit) as captured:
        main_module.main(
            ["--mode", "arena", "--live", "--confirm", "RUN", "--max-cycles", "1",
             "--window-backend", "pc"]
        )

    message = str(captured.value)
    assert "PC 未就绪" in message
    assert "docs/howto/live_verification.md" in message, "被拦却不说去哪看，等于没帮上忙"
    assert "live_check" in message, "要给出可执行的自检命令"


def test_a_dry_run_never_touches_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """干跑不点任何东西，不该被权限闸门拦住（否则离线调试全废）。"""

    def fail_if_called(_backend: str) -> None:
        pytest.fail("干跑不该触发 PC 权限闸门")

    def stop_after_gate(**_kwargs):
        raise SystemExit(42)  # SystemExit 不会被 main 的 except 吞掉

    monkeypatch.setattr(main_module, "_pc_live_precondition", fail_if_called)
    monkeypatch.setattr(main_module, "run_mode", stop_after_gate)

    with pytest.raises(SystemExit) as captured:
        main_module.main(["--mode", "arena", "--window-backend", "pc"])

    assert captured.value.code == 42, "没能走到 run_mode，说明中途被别的东西拦了"
