"""只读实机自检的输出判定：真通过的检查不能被打成 FAIL。

回归点（2026-11-26）：``PreflightStatus`` 是 ``str, Enum``，``str(成员)`` 给的是
``"PreflightStatus.PASS"``。旧实现按「状态字符串以 OK 开头」判通过，于是模拟器
那一行印成「FAIL PreflightStatus.PASS」，结论永远说两个后端都没就绪、退出码恒为 1。
需要它出结论的实机验收因此拿不到可信输出 —— 这一组用例就是钉住那个判定。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_game_unified.desktop import preflight
from auto_game_unified.tools import live_check

ROOT = Path(__file__).resolve().parents[1]


def _report(status: preflight.PreflightStatus, message: str):
    return preflight.PreflightReport(status=status, message=message)


def test_a_passing_backend_is_reported_as_ready(monkeypatch, capsys):
    monkeypatch.setattr(
        live_check.preflight,
        "run_preflight",
        lambda window_backend: _report(
            preflight.PreflightStatus.PASS, "模拟器和截图检查通过"
        ),
    )

    assert live_check.main(["--backend", "emulator"]) == 0

    out = capsys.readouterr().out
    assert "【emulator】OK" in out
    assert "FAIL" not in out
    assert "emulator 就绪" in out


def test_a_blocked_backend_returns_non_zero_and_says_why(monkeypatch, capsys):
    monkeypatch.setattr(
        live_check.preflight,
        "run_preflight",
        lambda window_backend: _report(
            preflight.PreflightStatus.BLOCK, "实际找到 0 个窗口"
        ),
    )

    assert live_check.main(["--backend", "pc"]) == 1

    out = capsys.readouterr().out
    assert "【pc】FAIL" in out
    assert "实际找到 0 个窗口" in out
    assert "没有可用的后端" in out


def test_one_ready_backend_is_enough_to_call_it_ready(monkeypatch, capsys):
    """组合只跑模拟器时，PC 没开不该把结论拖成「都没就绪」。"""

    def fake_run(window_backend: str):
        if window_backend == "emulator":
            return _report(preflight.PreflightStatus.PASS, "模拟器和截图检查通过")
        return _report(preflight.PreflightStatus.BLOCK, "实际找到 0 个窗口")

    monkeypatch.setattr(live_check.preflight, "run_preflight", fake_run)

    assert live_check.main([]) == 0

    out = capsys.readouterr().out
    assert "【emulator】OK" in out
    assert "【pc】FAIL" in out
    assert "emulator 就绪" in out


def test_a_raised_error_is_not_reported_as_a_pass(monkeypatch, capsys):
    def explode(window_backend: str):
        raise RuntimeError("模拟器没开")

    monkeypatch.setattr(live_check.preflight, "run_preflight", explode)

    assert live_check.main(["--backend", "emulator"]) == 1

    out = capsys.readouterr().out
    assert "【emulator】FAIL" in out
    assert "模拟器没开" in out


def test_the_ready_conclusion_points_at_a_doc_that_exists(monkeypatch, capsys):
    """输出里指的那份文档必须真的在 —— 旧文案指向 docs/maintenance/ 下，早已搬走。"""
    monkeypatch.setattr(
        live_check.preflight,
        "run_preflight",
        lambda window_backend: _report(preflight.PreflightStatus.PASS, "通过"),
    )

    live_check.main(["--backend", "emulator"])

    out = capsys.readouterr().out
    assert "docs/howto/live_verification.md" in out
    assert (ROOT / "docs" / "howto" / "live_verification.md").is_file()


@pytest.mark.parametrize("backend", ["pc", "emulator"])
def test_no_backend_is_reported_ready_when_its_check_blocks(monkeypatch, backend):
    """反向验证：状态是「阻止」时绝不能印 OK。"""
    monkeypatch.setattr(
        live_check.preflight,
        "run_preflight",
        lambda window_backend: _report(preflight.PreflightStatus.BLOCK, "阻止"),
    )

    result = live_check.run_check(backend)

    assert result.ok is False
    assert result.status == preflight.PreflightStatus.BLOCK.value
