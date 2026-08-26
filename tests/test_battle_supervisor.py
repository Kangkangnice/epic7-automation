from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
)
from auto_game_unified.core.recovery import RecoveryBlocked, RecoveryGate
from auto_game_unified.core.runtime import Runtime


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def make_supervisor(observations, *, changing_frames=True, config_overrides=None):
    clock = FakeClock()
    frames = iter(
        np.full(
            (720, 1280, 3),
            index * 7 % 255 if changing_frames else 30,
            dtype=np.uint8,
        )
        for index in range(50)
    )
    clicks: list[tuple[tuple[int, int], str]] = []
    logs: list[str] = []
    diagnostics: list[str] = []
    runtime = Runtime(
        capture=lambda: next(frames),
        click=lambda point: None,
        diagnostic_dir=Path("diagnostics"),
        emit=logs.append,
    )
    runtime.click = lambda point, action: clicks.append((point, action))
    runtime.save_current_frame = lambda screen=None: Path("current.png")
    runtime.save_diagnostic = (
        lambda label, screen=None: diagnostics.append(label) or label
    )
    gate = RecoveryGate(lambda: None)
    iterator = iter(observations)
    config = BattleConfig(
        mode="test",
        poll_seconds=1,
        entry_absolute_seconds=5,
        no_activity_seconds=5,
        no_business_progress_seconds=15,
        absolute_seconds=20,
        unrecognized_seconds=3,
        black_seconds=3,
        auto_confirm_seconds=3,
        heartbeat_seconds=2,
    )
    if config_overrides:
        config = replace(config, **config_overrides)
    supervisor = BattleSupervisor(
        runtime,
        gate,
        config,
        now=clock.now,
        sleep=clock.sleep,
    )
    observe = lambda screen, previous: next(iterator)
    return supervisor, gate, observe, clicks, logs, diagnostics


def test_committed_battle_locks_recovery_until_stable_result():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.RESULT_REACHED
    assert gate.locked is False
    assert clicks == []
    assert diagnostics == []


def test_known_pre_battle_business_popup_returns_control_without_clicking():
    popup = BattleObservation(
        False,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        pre_battle_business_visible=True,
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [popup, popup]
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.PRE_BATTLE_BUSINESS
    assert gate.locked is False
    assert clicks == []
    assert diagnostics == []


def test_manual_auto_state_clicks_once_and_requires_confirmation():
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual, auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert clicks == [((900, 80), "enable-auto-battle")]


def test_manual_auto_state_retries_once_when_first_click_is_swallowed():
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual] * 5 + [auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert clicks == [
        ((900, 80), "enable-auto-battle"),
        ((900, 80), "enable-auto-battle"),
    ]
    assert diagnostics == []


def test_persisted_manual_auto_state_stops_after_four_clicks():
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual] * 40,
        config_overrides={
            "auto_confirm_seconds": 20,
            "allowed_action_retry_seconds": 1,
            "allowed_action_failure_seconds": 2,
            "no_business_progress_seconds": 30,
        },
    )

    with pytest.raises(RuntimeError, match="点击4次后仍为手动战斗"):
        supervisor.run(observe, cycle=2)
    assert clicks == [
        ((900, 80), "enable-auto-battle"),
        ((900, 80), "enable-auto-battle"),
        ((900, 80), "enable-auto-battle"),
        ((900, 80), "enable-auto-battle"),
    ]
    assert diagnostics == ["auto_not_confirmed"]


def test_business_progress_does_not_confirm_unknown_auto_state():
    unknown = BattleObservation(
        False,
        True,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [unknown] * 30
    )

    with pytest.raises(RuntimeError, match="自动战斗开启未能确认"):
        supervisor.run(observe, cycle=2)
    assert not any("状态=自动战斗已开启" in line for line in logs)
    assert diagnostics == ["auto_not_confirmed"]


def test_mode_whitelist_action_is_clicked_once_until_it_disappears():
    story = BattleObservation(
        False,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
        allowed_action=("skip", (640, 80)),
    )
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [story, story, auto, auto, result, result]
    )

    supervisor.run(observe, cycle=3)
    assert clicks == [((640, 80), "skip")]


def test_persisted_allowed_action_is_retried_once_before_result():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    story = BattleObservation(
        False,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
        allowed_action=("skip_confirm", (640, 500)),
    )
    result = BattleObservation(
        False, False, True, True, AutoBattleState.UNKNOWN
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto] + [story] * 6 + [result, result],
        config_overrides={"entry_absolute_seconds": 12},
    )

    assert supervisor.run(observe, cycle=3) is BattleOutcome.RESULT_REACHED
    assert clicks == [
        ((640, 500), "skip_confirm"),
        ((640, 500), "skip_confirm"),
    ]
    assert diagnostics == []


def test_persisted_allowed_action_stops_after_four_failed_clicks():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    story = BattleObservation(
        False,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
        allowed_action=("skip_confirm", (640, 500)),
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto] + [story] * 40,
        config_overrides={
            "entry_absolute_seconds": 20,
            "allowed_action_retry_seconds": 1,
            "allowed_action_failure_seconds": 2,
            "absolute_seconds": 40,
        },
    )

    with pytest.raises(RuntimeError, match="允许动作 skip_confirm 点击4次后画面未推进"):
        supervisor.run(observe, cycle=3)
    assert clicks == [
        ((640, 500), "skip_confirm"),
        ((640, 500), "skip_confirm"),
        ((640, 500), "skip_confirm"),
        ((640, 500), "skip_confirm"),
    ]
    assert diagnostics == ["allowed_action_skip_confirm_failed"]


def test_quick_battle_switch_retries_then_confirms_normal_start_action():
    quick = BattleObservation(
        True,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        allowed_action=("switch-to-normal-battle", (1435, 1045)),
    )
    normal = replace(
        quick,
        allowed_action=("battle-start", (1258, 1043)),
    )
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [quick] * 5 + [normal, normal, auto, auto, result, result],
        config_overrides={"entry_absolute_seconds": 15},
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.RESULT_REACHED
    assert clicks == [
        ((1435, 1045), "switch-to-normal-battle"),
        ((1435, 1045), "switch-to-normal-battle"),
        ((1258, 1043), "battle-start"),
    ]
    assert any(
        "阶段=战前 动作=switch-to-normal-battle 尝试=2/4" in line
        for line in logs
    )
    assert any(
        "阶段=战前 转场确认 动作=switch-to-normal-battle "
        "目标动作=battle-start" in line
        for line in logs
    )
    assert diagnostics == []


def test_two_dynamic_valid_frames_confirm_entry_after_prep_disappears():
    transition = BattleObservation(
        False,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
    )
    result = replace(transition, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [transition, transition, result, result]
    )

    assert supervisor.run(observe, cycle=4) is BattleOutcome.RESULT_REACHED
    assert any("阶段=战斗 状态=已进入" in line for line in logs)
    assert diagnostics == []


def test_unknown_auto_state_never_clicks_and_safely_stops():
    unknown = BattleObservation(False, True, False, True, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [unknown] * 10
    )

    with pytest.raises(RuntimeError, match="自动战斗开启未能确认"):
        supervisor.run(observe, cycle=5)
    assert clicks == []
    assert diagnostics == ["auto_not_confirmed"]
    assert gate.locked is False


def test_skill_animation_does_not_start_auto_click_confirmation_timeout():
    transition = BattleObservation(
        False, False, False, True, AutoBattleState.UNKNOWN
    )
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [transition] * 5 + [auto, auto, result, result],
        config_overrides={
            "auto_confirm_seconds": 3,
            "unrecognized_seconds": 10,
            "entry_absolute_seconds": 10,
        },
    )

    assert supervisor.run(observe, cycle=5) is BattleOutcome.RESULT_REACHED
    assert clicks == []
    assert diagnostics == []


def test_confirmed_auto_tolerates_short_transition_and_resumes():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    transition = BattleObservation(
        False, False, False, True, AutoBattleState.UNKNOWN
    )
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto] + [transition] * 5 + [auto, auto, result, result],
        config_overrides={"unrecognized_seconds": 8},
    )

    assert supervisor.run(observe, cycle=13) is BattleOutcome.RESULT_REACHED
    assert clicks == []
    assert diagnostics == []


def test_valid_but_unrecognized_frame_safely_stops_without_recovery():
    unknown = BattleObservation(False, False, False, True, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [unknown] * 10
    )

    with pytest.raises(RuntimeError, match="战斗画面持续无法识别超时"):
        supervisor.run(observe, cycle=6)
    assert diagnostics == ["battle_unrecognized"]
    assert gate.locked is False


def test_black_transition_uses_first_black_frame_timeout():
    black = BattleObservation(False, False, False, False, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([black] * 10)

    with pytest.raises(RuntimeError, match="战斗画面持续黑屏超时"):
        supervisor.run(observe, cycle=7)
    assert diagnostics == ["battle_black_timeout"]


def test_brief_black_transition_can_reach_result():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    black = BattleObservation(False, False, False, False, AutoBattleState.UNKNOWN)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, black, black, result, result]
    )

    assert supervisor.run(observe, cycle=8) is BattleOutcome.RESULT_REACHED
    assert diagnostics == []


def test_heartbeat_is_emitted_while_battle_progresses():
    auto = BattleObservation(
        False, True, False, True, AutoBattleState.AUTO, business_progress=True
    )
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, auto, auto, result, result]
    )

    supervisor.run(observe, cycle=9)
    assert any("状态=心跳" in line for line in logs)


def test_static_valid_battle_stops_on_no_activity_without_recovery():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto] * 10, changing_frames=False
    )

    with pytest.raises(RuntimeError, match="战斗画面无变化超时"):
        supervisor.run(observe, cycle=10)
    assert diagnostics == ["battle_no_activity"]


def test_dynamic_battle_still_has_an_absolute_limit():
    auto = BattleObservation(
        False, True, False, True, AutoBattleState.AUTO, business_progress=True
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([auto] * 30)

    with pytest.raises(RuntimeError, match="战斗绝对超时"):
        supervisor.run(observe, cycle=11)
    assert diagnostics == ["battle_absolute_timeout"]


def test_recovery_request_is_blocked_during_observation():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, base_observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, result, result]
    )
    blocked: list[bool] = []

    def observe(screen, previous):
        if not blocked:
            with pytest.raises(RecoveryBlocked):
                gate.recover("test probe")
            blocked.append(True)
        return base_observe(screen, previous)

    assert supervisor.run(observe, cycle=12) is BattleOutcome.RESULT_REACHED
    assert blocked == [True]
