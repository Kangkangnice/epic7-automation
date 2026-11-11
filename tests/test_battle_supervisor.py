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
from auto_game_unified.core.recovery import RecoveryGate
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
    gate = RecoveryGate()
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
    def observe(screen, previous):
        return next(iterator)
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


def test_pre_battle_business_first_frame_freezes_stable_background_action():
    normal = BattleObservation(
        True,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        allowed_action=("battle-start", (1258, 1043)),
    )
    popup = replace(normal, pre_battle_business_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [normal, normal, popup, popup],
        config_overrides={"allowed_action_retry_seconds": 1},
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.PRE_BATTLE_BUSINESS
    assert clicks == [((1258, 1043), "battle-start")]
    assert any(
        "业务弹窗首帧已识别" in line and "冻结背景操作" in line
        for line in logs
    )
    assert diagnostics == []


def test_transient_pre_battle_business_resets_background_action_stability():
    normal = BattleObservation(
        True,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        allowed_action=("battle-start", (1258, 1043)),
    )
    popup = replace(normal, pre_battle_business_visible=True)
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [normal, popup, normal, auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.RESULT_REACHED
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


def test_four_failed_auto_clicks_stop_clicking_but_keep_supervising():
    """4 次拨不动只是停手，不再把整条路线判失败；画面恢复后这一场仍能打完。

    2026-11-11 模拟器竞技场第 2 轮：卡在 VS 入场演出，图标擦着门槛被判手动，
    连点 4 次开关没确认就整条路线报错。战斗本身没坏，不该判死刑。
    """
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual] * 8 + [auto, auto, result, result],
        config_overrides={
            "allowed_action_retry_seconds": 1,
            "allowed_action_failure_seconds": 2,
        },
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert len(clicks) == 4, "停手之后不许再拨第 5 次"
    assert diagnostics == []


def test_persisted_manual_state_is_still_bounded_by_the_watchdog():
    """画面一直不恢复时，仍然由看门狗有界收尾，不是无限等、也不是冒充成功。"""
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual] * 40,
        config_overrides={
            "allowed_action_retry_seconds": 1,
            "allowed_action_failure_seconds": 2,
            "no_business_progress_seconds": 30,
        },
    )

    with pytest.raises(RuntimeError) as error:
        supervisor.run(observe, cycle=2)
    assert "点击4次后仍为手动战斗" not in str(error.value)
    assert len(clicks) == 4
    assert "auto_not_confirmed" not in diagnostics
    assert any("停手继续监督" in line for line in logs)


def test_auto_click_log_names_the_evidence_that_triggered_it():
    """只记「依据=连续2帧」不够用：下次要能一眼看出是布局还是右上角图标说的。"""
    manual = BattleObservation(
        False,
        True,
        False,
        True,
        AutoBattleState.MANUAL,
        (900, 80),
        auto_evidence="布局=transition 自动关图标=0.9321 来源=右上角自动关闭图标",
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual, auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert any(
        "动作=开启自动战斗" in line
        and "证据=布局=transition 自动关图标=0.9321" in line
        for line in logs
    )


def test_repeated_auto_recovery_stops_interfering_with_the_toggle():
    """自动被反复关掉时，不能整场都在拨开关——拨够次数就停手并说明原因。

    现象（2026-09-18 实跑）：一场战斗里 9 轮「点开→说已开启→又被关掉」，
    每轮 2 下点击，因为「已开启」会把计数清零，4 次上限永远触发不了。
    """
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (900, 80)
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual, auto, auto] * 3 + [manual, manual, result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert clicks == [((900, 80), "enable-auto-battle")] * 3
    assert any(
        "状态=自动战斗反复被关闭" in line and "累计=3次" in line for line in logs
    )
    assert diagnostics == []


def test_business_progress_does_not_falsely_confirm_unknown_auto_state():
    unknown = BattleObservation(
        False,
        True,
        False,
        True,
        AutoBattleState.UNKNOWN,
        business_progress=True,
    )
    result = replace(unknown, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [unknown] * 8 + [result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert not any("状态=自动战斗已开启" in line for line in logs)
    assert diagnostics == []


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


def test_auto_source_disappears_then_enemy_actions_do_not_timeout():
    manual = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, (1693, 93)
    )
    unknown = replace(
        manual,
        auto_state=AutoBattleState.UNKNOWN,
        auto_point=None,
        business_progress=True,
    )
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual] + [unknown] * 6 + [auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert clicks == [((1693, 93), "enable-auto-battle")]
    assert any(
        "来源=自动关闭已离开 目标=人物头像待确认" in line
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
        [unknown] * 30
    )

    with pytest.raises(RuntimeError, match="战斗业务无进展超时"):
        supervisor.run(observe, cycle=5)
    assert clicks == []
    assert diagnostics == ["battle_no_business_progress"]
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


def test_the_battle_lock_is_engaged_while_observing():
    """战斗中**每一帧**都必须是锁上的 —— 这就是「不许有任何东西打断这一局」。

    ⚠️ 2026-09-26 之前这里叫 ``test_recovery_request_is_blocked_during_observation``：
    那时锁的作用是「挡住回大厅恢复的回调」。用户拍板「回家就是结束」之后那条通道
    整段删除（连 ``recover()`` 一起）⇒ 锁成了**唯一**还活着的那一半，
    这条改成直接盯锁本身：观察期间它必须一直是锁着的。
    """
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, base_observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, result, result]
    )
    observed_locked: list[bool] = []

    def observe(screen, previous):
        observed_locked.append(gate.locked)
        return base_observe(screen, previous)

    assert supervisor.run(observe, cycle=12) is BattleOutcome.RESULT_REACHED
    assert observed_locked, "观察器一次都没被调到，这条用例就没测到东西"
    assert all(observed_locked), "战斗中闸门松了 —— 这一局随时可能被打断"
    # 认出结算页之后必须解锁，否则下一局永远动不了。
    assert gate.locked is False


def test_manual_without_a_toggle_point_waits_instead_of_failing_at_once():
    """★ 2026-10-09 月塔事故：一帧「判成手动又给不出坐标」就 _fail 是错的。

    判据各自都会在真假之间跳：布局靠底座颜色数活人（技能特效会盖住底座），
    图标是共享模板（背景一换分数就掉进死区）。单帧的结论本来就不可信 ——
    旧代码却拿它当死刑判决，于是整条路线当场回首页、白打一层。

    这里喂「手动但没坐标」只持续 3 帧，然后判据抖回来（给出坐标并能点开）。
    期望：**不失败**，且等抖回来之后正常把自动点开。
    """
    manual_no_point = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, None
    )
    manual = replace(manual_no_point, auto_point=(900, 80))
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual_no_point] * 3 + [manual] * 2 + [auto, auto, result, result],
        config_overrides={"auto_point_grace_seconds": 12},
    )

    assert supervisor.run(observe, cycle=3) is BattleOutcome.RESULT_REACHED
    assert diagnostics == [], f"不该判失败，却存了诊断：{diagnostics}"
    assert clicks == [((900, 80), "enable-auto-battle")], clicks
    assert any("缺开关坐标" in line for line in logs), logs


def test_manual_without_a_toggle_point_still_fails_after_the_grace_window():
    """成对：判据一直抖不回来时，**必须**在窗口用完后收手，不能无限干等。

    没有这一条，把上面那条"修"成「永远不判死」也照样绿 —— 而那样会在
    真正拿不到开关的场景里一路空转到整场超时，比立刻停下更糟。
    """
    manual_no_point = BattleObservation(
        False, True, False, True, AutoBattleState.MANUAL, None
    )
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual_no_point] * 10,
        config_overrides={
            "auto_point_grace_seconds": 4,
            "no_business_progress_seconds": 300,
            "absolute_seconds": 300,
            "no_activity_seconds": 300,
        },
    )

    with pytest.raises(RuntimeError, match="缺少自动开关坐标"):
        supervisor.run(observe, cycle=4)
    assert diagnostics == ["auto_point_missing"]
    assert clicks == [], "拿不到坐标时一次都不许点"


class TestNoBusyLoop:
    """主循环里不许出现绕过 ``sleep`` 的 ``continue``。

    ⚠️ 2026-10-09 我自己踩的：给 ``auto_point is None`` 加「有界等待」时图省事写了
    ``continue``，而 ``self.sleep(self.config.poll_seconds)`` 在**循环最末尾**
    ⇒ 那一支会跳过 sleep，变成**每秒成百上千次截图**的忙循环。
    真机上这比原来的 bug 更糟（截图是最贵的操作），而单测里看不出来 ——
    假 clock 的 ``sleep`` 是空操作，跑得飞快，测试全绿。

    判据落在**源码结构**上：``BattleSupervisor.run`` 的 ``while True`` 循环体内
    不得出现 ``continue``。这条不依赖运行时行为，所以拦得住上面那种「测试照绿」的写法。
    """

    def test_the_observation_loop_never_continues_past_the_sleep(self):
        import ast
        import inspect
        import textwrap

        from auto_game_unified.core import battle_supervisor as module

        source = textwrap.dedent(inspect.getsource(module.BattleSupervisor.run))
        tree = ast.parse(source)

        offenders: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant):
                if node.test.value is True:
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Continue):
                            offenders.append(inner.lineno)

        assert offenders == [], (
            "主循环里出现 continue —— 会跳过末尾的 sleep 变成忙循环；"
            "改用 if/else 包住后续逻辑"
        )
