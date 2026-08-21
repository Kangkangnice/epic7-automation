import pytest

from auto_game_unified.core.recovery import RecoveryBlocked, RecoveryGate


def test_recovery_runs_only_when_gate_is_unlocked():
    calls: list[str] = []
    gate = RecoveryGate(lambda: calls.append("recover"))

    gate.recover("navigation timeout")
    gate.lock(mode="expedition", cycle=1)
    with pytest.raises(RecoveryBlocked, match="战斗进行中禁止回大厅恢复"):
        gate.recover("unknown battle frame")
    gate.unlock()
    gate.recover("result timeout")

    assert calls == ["recover", "recover"]


def test_blocked_recovery_reports_lock_metadata_without_running_callback():
    calls: list[str] = []
    blocked: list[str] = []
    gate = RecoveryGate(
        lambda: calls.append("recover"),
        on_blocked=blocked.append,
    )

    gate.lock(mode="story", cycle=4)
    with pytest.raises(RecoveryBlocked):
        gate.recover("retry exhausted")

    assert calls == []
    assert blocked == [
        "战斗进行中禁止回大厅恢复 模式=story 轮次=4 原因=retry exhausted"
    ]
