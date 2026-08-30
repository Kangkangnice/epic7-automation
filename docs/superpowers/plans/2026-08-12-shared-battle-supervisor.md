# Shared Battle Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one shared battle lifecycle supervisor that prevents lobby recovery after battle commitment and centralizes entry confirmation, automatic-battle confirmation, heartbeat, timeouts, diagnostics, and result handoff for expedition, arena, and story.

**Architecture:** Keep each mode's navigation, resource rules, popups, result handling, and cycle counting in its existing state machine. `RecoveryGate` is created once in `main.py`, passed to every Runner, and locked by `BattleSupervisor` from the verified battle-start click until a stable result anchor or safe stop. Each mode exposes only a small `observe_battle(screen, previous_screen)` adapter.

**Tech Stack:** Python 3, pytest/unittest, NumPy, OpenCV, existing `Runtime`, `StableObservation`, template matchers, and synthetic offline frames.

---

Run every command below from `D:\AI\codex\auto_game`. Python imports then resolve the `auto_game_unified` package exactly as they do in the documented manual commands. No task may start, click, stop, or otherwise control the emulator; all verification in this plan is offline.

## File map

- Create `core/recovery.py`: one synchronous recovery gate with lock metadata and a blocked callback.
- Create `core/battle_supervisor.py`: shared battle-session loop and its public observation types.
- Create `tests/test_recovery_gate.py`: recovery-lock unit tests.
- Create `tests/test_battle_supervisor.py`: pure fake-clock lifecycle tests.
- Create `tests/test_battle_safety_invariants.py`: the same safety assertions for all three adapters.
- Modify `main.py`: create one gate around the existing return-home callback and pass it to the Runner.
- Modify `games/epic7/expedition.py`: expedition observation adapter and supervisor delegation.
- Modify `games/epic7/arena.py`: arena observation adapter and supervisor delegation.
- Modify `games/epic7/story.py`: story observation adapter and supervisor delegation.
- Modify `tests/test_main_story.py`, `tests/test_epic7_expedition.py`, `tests/test_expedition_runner.py`, `tests/test_epic7_arena.py`, `tests/test_arena_runner.py`, `tests/test_epic7_story.py`, and `tests/test_story_runner.py`: focused regressions.
- Modify `README.md` and `docs/HUMAN_AI_WORKFLOW.md`: document shared behavior and user-owned live acceptance.

### Task 1: Add and wire the recovery gate

**Files:**
- Create: `core/recovery.py`
- Create: `tests/test_recovery_gate.py`
- Modify: `main.py`
- Modify: `games/epic7/expedition.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/story.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: Write the failing gate tests**

Create `tests/test_recovery_gate.py` with these exact cases:

```python
import pytest

from auto_game_unified.core.recovery import RecoveryBlocked, RecoveryGate


def test_recovery_runs_only_when_gate_is_unlocked():
    calls: list[str] = []
    gate = RecoveryGate(lambda: calls.append("recover"))

    gate.recover("navigation timeout")
    gate.lock(mode="expedition", cycle=1)
    with pytest.raises(RecoveryBlocked, match="committed battle"):
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
        "recovery blocked during committed battle mode=story cycle=4 reason=retry exhausted"
    ]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_recovery_gate.py -q
```

Expected: collection fails with `ModuleNotFoundError: auto_game_unified.core.recovery`.

- [ ] **Step 3: Implement the minimal gate**

Create `core/recovery.py` with this public API and no nesting, queues, or async behavior:

```python
from dataclasses import dataclass
from typing import Callable


class RecoveryBlocked(RuntimeError):
    """Raised when lobby recovery is requested during a committed battle."""


@dataclass(frozen=True)
class BattleLock:
    mode: str
    cycle: int


class RecoveryGate:
    def __init__(
        self,
        recover: Callable[[], None] | None,
        *,
        on_blocked: Callable[[str], None] | None = None,
    ) -> None:
        self._recover = recover
        self._on_blocked = on_blocked
        self._lock: BattleLock | None = None

    @property
    def locked(self) -> bool:
        return self._lock is not None

    def lock(self, *, mode: str, cycle: int) -> None:
        self._lock = BattleLock(mode=mode, cycle=cycle)

    def unlock(self) -> None:
        self._lock = None

    def recover(self, reason: str = "runner recovery") -> None:
        if self._lock is not None:
            message = (
                "recovery blocked during committed battle "
                f"mode={self._lock.mode} cycle={self._lock.cycle} reason={reason}"
            )
            if self._on_blocked is not None:
                self._on_blocked(message)
            raise RecoveryBlocked(message)
        if self._recover is not None:
            self._recover()
```

- [ ] **Step 4: Add a failing main wiring test**

In `tests/test_main_story.py`, import `replace` from `dataclasses` and `RecoveryGate`, then add:

```python
def test_live_run_passes_one_recovery_gate_to_the_runner(self):
    runtime = unittest.mock.MagicMock()
    runner_type = unittest.mock.MagicMock()
    runner_type.return_value.run.return_value = 0
    spec = replace(get_mode("story"), runner_type=runner_type)

    with (
        patch.object(main_module, "_build_runtime", return_value=runtime),
        patch.object(main_module, "Epic7Navigator"),
    ):
        main_module.run_mode(
            spec=spec,
            dry_run=False,
            max_cycles=1,
            start_state="stage",
        )

    options = runner_type.call_args.kwargs
    self.assertIsInstance(options["recovery_gate"], RecoveryGate)
    self.assertEqual(options["recovery"], options["recovery_gate"].recover)
```

Run:

```powershell
python -m pytest auto_game_unified/tests/test_main_story.py::MainStoryTests::test_live_run_passes_one_recovery_gate_to_the_runner -q
```

Expected: FAIL because `recovery_gate` is not passed.

- [ ] **Step 5: Wire the gate without changing current mode behavior**

In `main.py`, build the gate only for live navigation. Its blocked callback must log and save a diagnostic:

```python
def recover_to_mode() -> None:
    lobby_screen = navigator.return_home()
    navigator.navigate(spec.name, lobby_screen=lobby_screen)

def report_blocked_recovery(message: str) -> None:
    runtime.log(message)
    runtime.save_diagnostic("recovery_blocked")

recovery_gate = RecoveryGate(
    recover_to_mode,
    on_blocked=report_blocked_recovery,
)
runner_options["recovery"] = recovery_gate.recover
runner_options["recovery_gate"] = recovery_gate
```

Add an optional `recovery_gate: RecoveryGate | None = None` keyword to all three Runner constructors. Store it as:

```python
self.recovery_gate = recovery_gate or RecoveryGate(recovery)
self.recovery = self.recovery_gate.recover if recovery is not None else None
```

This is only interface wiring: no Runner locks the gate until its migration task.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_recovery_gate.py auto_game_unified/tests/test_main_story.py auto_game_unified/tests/test_story_runner.py auto_game_unified/tests/test_arena_runner.py auto_game_unified/tests/test_expedition_runner.py -q
```

Expected: all pass.

Commit:

```powershell
git -C auto_game_unified add core/recovery.py tests/test_recovery_gate.py tests/test_main_story.py main.py games/epic7/story.py games/epic7/arena.py games/epic7/expedition.py
git -C auto_game_unified commit -m "add committed battle recovery gate"
```

### Task 2: Build the shared battle supervisor

**Files:**
- Create: `core/battle_supervisor.py`
- Create: `tests/test_battle_supervisor.py`

- [ ] **Step 1: Write deterministic lifecycle tests**

Create `tests/test_battle_supervisor.py`. Use this fixture so every test is independent of templates and real time:

```python
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


def make_supervisor(observations, *, changing_frames=True):
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
    runtime.save_diagnostic = lambda label, screen=None: diagnostics.append(label) or label
    gate = RecoveryGate(lambda: None)
    iterator = iter(observations)
    supervisor = BattleSupervisor(
        runtime,
        gate,
        BattleConfig(
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
        ),
        now=clock.now,
        sleep=clock.sleep,
    )
    return supervisor, gate, lambda screen, previous: next(iterator), clicks, logs, diagnostics
```

Add these complete behavioral assertions:

```python
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


def test_manual_auto_state_clicks_once_and_requires_confirmation():
    manual = BattleObservation(False, True, False, True, AutoBattleState.MANUAL, (900, 80))
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual, auto, auto, result, result]
    )
    assert supervisor.run(observe, cycle=2) is BattleOutcome.RESULT_REACHED
    assert clicks == [((900, 80), "enable-auto-battle")]


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
    assert any("status=entry-confirmed" in line for line in logs)
    assert diagnostics == []


def test_unknown_auto_state_never_clicks_and_safely_stops():
    unknown = BattleObservation(False, True, False, True, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([unknown] * 10)
    with pytest.raises(RuntimeError, match="auto battle was not confirmed"):
        supervisor.run(observe, cycle=5)
    assert clicks == []
    assert diagnostics == ["auto_not_confirmed"]
    assert gate.locked is False


def test_valid_but_unrecognized_frame_safely_stops_without_recovery():
    unknown = BattleObservation(False, False, False, True, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([unknown] * 10)
    with pytest.raises(RuntimeError, match="unrecognized battle frame"):
        supervisor.run(observe, cycle=6)
    assert diagnostics == ["battle_unrecognized"]
    assert gate.locked is False


def test_black_transition_uses_first_black_frame_timeout():
    black = BattleObservation(False, False, False, False, AutoBattleState.UNKNOWN)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([black] * 10)
    with pytest.raises(RuntimeError, match="black frame timeout"):
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
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO, business_progress=True)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto, auto, auto, result, result]
    )
    supervisor.run(observe, cycle=9)
    assert any("status=heartbeat" in line for line in logs)


def test_static_valid_battle_stops_on_no_activity_without_recovery():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto] * 10, changing_frames=False
    )
    with pytest.raises(RuntimeError, match="no activity"):
        supervisor.run(observe, cycle=10)
    assert diagnostics == ["battle_no_activity"]


def test_dynamic_battle_still_has_an_absolute_limit():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO, business_progress=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor([auto] * 30)
    with pytest.raises(RuntimeError, match="absolute timeout"):
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
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_battle_supervisor.py -q
```

Expected: collection fails because `core.battle_supervisor` does not exist.

- [ ] **Step 3: Define the exact public types**

Create `core/battle_supervisor.py` with these types:

```python
from dataclasses import dataclass
from enum import Enum
from time import monotonic, sleep as default_sleep
from typing import Callable

import numpy as np

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation, meaningful_change


class AutoBattleState(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class BattleOutcome(Enum):
    RESULT_REACHED = "result_reached"


@dataclass(frozen=True)
class BattleObservation:
    pre_battle_visible: bool
    battle_visible: bool
    result_visible: bool
    frame_valid: bool
    auto_state: AutoBattleState
    auto_point: tuple[int, int] | None = None
    business_progress: bool = False
    allowed_action: tuple[str, tuple[int, int]] | None = None


@dataclass(frozen=True)
class BattleConfig:
    mode: str
    poll_seconds: float = 1.0
    entry_absolute_seconds: float = 180
    no_activity_seconds: float = 180
    no_business_progress_seconds: float = 900
    absolute_seconds: float = 900
    unrecognized_seconds: float = 45
    black_seconds: float = 45
    auto_confirm_seconds: float = 15
    heartbeat_seconds: float = 30


BattleObserver = Callable[[np.ndarray, np.ndarray | None], BattleObservation]


def valid_game_frame(screen: np.ndarray) -> bool:
    content = screen[
        round(screen.shape[0] * 0.05) :,
        : round(screen.shape[1] * 0.97),
    ]
    return float(np.mean(content)) >= 3.0 and float(np.std(content)) >= 5.0
```

- [ ] **Step 4: Implement the monitoring loop with one terminal path**

Implement this constructor and failure helper:

```python
class BattleSupervisor:
    def __init__(
        self,
        runtime: Runtime,
        gate: RecoveryGate,
        config: BattleConfig,
        *,
        now: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self.runtime = runtime
        self.gate = gate
        self.config = config
        self.now = now
        self.sleep = sleep

    def _fail(self, label: str, message: str, screen: np.ndarray) -> None:
        path = (
            self.runtime.save_diagnostic(label, screen)
            if self.runtime.diagnostic_dir is not None
            else "not-configured"
        )
        self.runtime.log(
            f"mode={self.config.mode} phase=battle status=safe-stop reason={message} diagnostic={path}"
        )
        raise RuntimeError(f"{message}; saved {path}")
```

Then implement `run(observe, *, cycle)` using these exact rules:

```python
def run(self, observe: BattleObserver, *, cycle: int) -> BattleOutcome:
    self.gate.lock(mode=self.config.mode, cycle=cycle)
    started = active_at = business_at = heartbeat = self.now()
    invalid_since = black_since = auto_wait_since = None
    previous = None
    auto_clicked = False
    last_allowed_action = None
    entry_confirmed = False
    auto_confirmed = False
    battle_stable = StableObservation(required=2)
    auto_stable = StableObservation(required=2)
    allowed_stable = StableObservation(required=2)
    result_stable = StableObservation(required=2)
    try:
        while True:
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)
            observation = observe(screen, previous)
            current = self.now()

            if result_stable.update("result" if observation.result_visible else "other") and observation.result_visible:
                self.runtime.log(
                    f"mode={self.config.mode} cycle={cycle} phase=result status=confirmed"
                )
                return BattleOutcome.RESULT_REACHED

            entered = observation.battle_visible or (
                not observation.pre_battle_visible
                and observation.allowed_action is None
                and observation.frame_valid
                and meaningful_change(previous, screen)
            )
            if (
                battle_stable.update("battle" if entered else "other")
                and entered
                and not entry_confirmed
            ):
                entry_confirmed = True
                self.runtime.log(
                    f"mode={self.config.mode} cycle={cycle} phase=battle status=entry-confirmed"
                )

            if meaningful_change(previous, screen):
                active_at = current
            if observation.business_progress:
                business_at = current

            if not observation.frame_valid:
                black_since = current if black_since is None else black_since
                if current - black_since >= self.config.black_seconds:
                    self._fail("battle_black_timeout", "black frame timeout", screen)
            else:
                black_since = None

            recognized = (
                observation.pre_battle_visible
                or observation.battle_visible
                or observation.result_visible
                or observation.allowed_action is not None
            )
            if observation.frame_valid and not recognized:
                invalid_since = current if invalid_since is None else invalid_since
                if current - invalid_since >= self.config.unrecognized_seconds:
                    self._fail("battle_unrecognized", "unrecognized battle frame timeout", screen)
            else:
                invalid_since = None

            stable_auto = auto_stable.update(observation.auto_state.value)
            allowed_signature = (
                "none"
                if observation.allowed_action is None
                else f"{observation.allowed_action[0]}:{observation.allowed_action[1]}"
            )
            allowed_confirmed = allowed_stable.update(allowed_signature)
            if observation.allowed_action is None:
                last_allowed_action = None
            elif allowed_confirmed and observation.allowed_action != last_allowed_action:
                action_name, action_point = observation.allowed_action
                self.runtime.click(action_point, action_name)
                last_allowed_action = observation.allowed_action
                business_at = current
            if (
                stable_auto
                and observation.auto_state is AutoBattleState.MANUAL
                and not auto_clicked
            ):
                if observation.auto_point is None:
                    self._fail("auto_point_missing", "manual state had no auto point", screen)
                self.runtime.click(observation.auto_point, "enable-auto-battle")
                auto_clicked = True
                auto_wait_since = current
                auto_stable.reset()
            elif (
                stable_auto and observation.auto_state is AutoBattleState.AUTO
            ) or observation.business_progress:
                auto_wait_since = None
                if not auto_confirmed:
                    auto_confirmed = True
                    self.runtime.log(
                        f"mode={self.config.mode} cycle={cycle} phase=battle status=auto-confirmed"
                    )
            elif entry_confirmed and not auto_confirmed and auto_wait_since is None:
                auto_wait_since = current

            if auto_wait_since is not None and current - auto_wait_since >= self.config.auto_confirm_seconds:
                self._fail("auto_not_confirmed", "auto battle was not confirmed", screen)
            if not entry_confirmed and current - started >= self.config.entry_absolute_seconds:
                self._fail("battle_entry_timeout", "battle entry was not confirmed", screen)
            if current - active_at >= self.config.no_activity_seconds:
                self._fail("battle_no_activity", "battle screen had no activity", screen)
            if current - business_at >= self.config.no_business_progress_seconds:
                self._fail("battle_no_business_progress", "battle made no business progress", screen)
            if current - started >= self.config.absolute_seconds:
                self._fail("battle_absolute_timeout", "battle absolute timeout", screen)
            if current - heartbeat >= self.config.heartbeat_seconds:
                self.runtime.log(
                    f"mode={self.config.mode} cycle={cycle} phase=battle status=heartbeat "
                    f"elapsed={current - started:.0f}s activity_age={current - active_at:.0f}s "
                    f"business_age={current - business_at:.0f}s"
                )
                heartbeat = current

            previous = screen
            self.sleep(self.config.poll_seconds)
    finally:
        self.gate.unlock()
```

`_fail(label, message, screen)` must save exactly one diagnostic, log its path, and raise `RuntimeError(f"{message}; saved {path}")`. Do not call recovery or `Runtime.back()` anywhere in this module. `allowed_action` is a mode-supplied whitelist: the supervisor may execute only the returned name/point, once until that observation disappears. It must never manufacture navigation, Back, resource-purchase, or result-handling actions.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_battle_supervisor.py auto_game_unified/tests/test_recovery_gate.py -q
```

Expected: all pass.

Commit:

```powershell
git -C auto_game_unified add core/battle_supervisor.py tests/test_battle_supervisor.py
git -C auto_game_unified commit -m "add shared battle lifecycle supervisor"
```

### Task 3: Migrate expedition first

**Files:**
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_epic7_expedition.py`
- Modify: `tests/test_expedition_runner.py`

- [ ] **Step 1: Add failing adapter tests**

In `tests/test_epic7_expedition.py`, use existing fixtures and assert exact fields:

```python
def test_expedition_battle_adapter_maps_team_manual_and_result(self):
    machine = self.machine(ExpeditionState.TEAM)
    team = machine.observe_battle(recorded_screen("team"), None)
    manual = machine.observe_battle(recorded_screen("battle_manual_waiting_live"), None)
    result = machine.observe_battle(recorded_screen("result"), None)

    self.assertTrue(team.pre_battle_visible)
    self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
    self.assertIsNotNone(manual.auto_point)
    self.assertTrue(result.result_visible)
```

In `tests/test_expedition_runner.py`, add a fake supervisor and prove only the committed interval is delegated:

```python
def test_battle_start_delegates_to_supervisor_and_returns_to_result_handling(self):
    machine = unittest.mock.MagicMock()
    machine.state = ExpeditionState.BATTLE
    supervisor = unittest.mock.MagicMock()
    supervisor.run.return_value = BattleOutcome.RESULT_REACHED
    runner = ExpeditionRunner(
        machine,
        Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), lambda point: None),
        battle_supervisor=supervisor,
        sleep=lambda seconds: None,
    )

    runner._run_committed_battle(cycle=1)

    supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
    self.assertEqual(ExpeditionState.RESULT, machine.state)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_expedition.py auto_game_unified/tests/test_expedition_runner.py -q
```

Expected: FAIL because `observe_battle`, `battle_supervisor`, and `_run_committed_battle` do not exist.

- [ ] **Step 3: Add the expedition adapter**

Add these imports to `games/epic7/expedition.py`:

```python
from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.recovery import RecoveryGate
```

Add this method to `ExpeditionStateMachine`, reusing existing matchers and the current frame-validity rule:

```python
def observe_battle(
    self,
    screen: np.ndarray,
    previous_screen: np.ndarray | None,
) -> BattleObservation:
    auto = self._locate(screen, "auto_off")
    battle = self._locate(screen, "battle_anchor")
    result = self._locate(screen, "result_confirm")
    return BattleObservation(
        pre_battle_visible=self._locate(screen, "battle_start") is not None,
        battle_visible=battle is not None or auto is not None,
        result_visible=result is not None,
        frame_valid=valid_game_frame(screen),
        auto_state=(
            AutoBattleState.MANUAL
            if auto is not None
            else AutoBattleState.AUTO
            if battle is not None and meaningful_change(previous_screen, screen)
            else AutoBattleState.UNKNOWN
        ),
        auto_point=None if auto is None else auto.center,
        business_progress=battle is not None and meaningful_change(previous_screen, screen),
    )
```

- [ ] **Step 4: Delegate only after `battle-start` is clicked**

Add `battle_supervisor: BattleSupervisor | None = None` to `ExpeditionRunner.__init__`, then initialize it with the same gate and injected clock:

```python
self.battle_supervisor = battle_supervisor or BattleSupervisor(
    runtime,
    self.recovery_gate,
    BattleConfig(
        mode="expedition",
        absolute_seconds=20 * 60,
        no_business_progress_seconds=20 * 60,
    ),
    now=now,
    sleep=sleep,
)
```

Add:

```python
def _run_committed_battle(self, *, cycle: int) -> None:
    outcome = self.battle_supervisor.run(self.machine.observe_battle, cycle=cycle)
    if outcome is not BattleOutcome.RESULT_REACHED:
        raise RuntimeError(f"unexpected expedition battle outcome: {outcome.value}")
    self.machine.state = ExpeditionState.RESULT
```

In the existing action block, immediately after `self.runtime.click(action.point, action.name)`, add:

```python
if action.name == "battle-start":
    self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
    state_started = self.now()
    failed_action = None
    action_attempts = 0
    stable.reset()
    continue
```

This branch must appear before the generic `_wait_until_in_state` call because entry confirmation now belongs to the locked supervisor. Keep `confirm-result`, victory, defeated/public recruitment, campfire wake, and return-home handling in the existing loop. Delete only expedition-local battle heartbeat, battle-frame, battle-unrecognized, no-progress, and absolute battle timeout fields after the focused tests pass.

- [ ] **Step 5: Verify expedition and commit**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_expedition.py auto_game_unified/tests/test_expedition_runner.py auto_game_unified/tests/test_navigation.py -q
```

Expected: all pass; no emulator process starts.

Commit:

```powershell
git -C auto_game_unified add games/epic7/expedition.py tests/test_epic7_expedition.py tests/test_expedition_runner.py
git -C auto_game_unified commit -m "migrate expedition to shared battle supervisor"
```

### Task 4: Migrate arena

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_epic7_arena.py`
- Modify: `tests/test_arena_runner.py`

- [ ] **Step 1: Add failing arena adapter and delegation tests**

In `tests/test_epic7_arena.py`, add:

```python
def test_arena_battle_adapter_maps_team_manual_and_result(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.TEAM)
    team = machine.observe_battle(load_fixture("team"), None)
    manual = machine.observe_battle(load_fixture("battle"), None)
    result = machine.observe_battle(load_fixture("result"), None)

    self.assertTrue(team.pre_battle_visible)
    self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
    self.assertIsNotNone(manual.auto_point)
    self.assertTrue(result.result_visible)
```

In `tests/test_arena_runner.py`, add:

```python
def test_arena_committed_battle_returns_control_to_result_state(self):
    machine = unittest.mock.MagicMock()
    machine.state = ArenaState.BATTLE
    supervisor = unittest.mock.MagicMock()
    supervisor.run.return_value = BattleOutcome.RESULT_REACHED
    runner = ArenaRunner(
        machine,
        Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), lambda point: None),
        battle_supervisor=supervisor,
        sleep=lambda seconds: None,
    )

    runner._run_committed_battle(cycle=1)

    supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
    self.assertEqual(ArenaState.RESULT, machine.state)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_arena.py auto_game_unified/tests/test_arena_runner.py -q
```

Expected: FAIL because the arena adapter and delegation method do not exist.

- [ ] **Step 3: Add the arena adapter**

Add these imports to `games/epic7/arena.py`:

```python
from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.recovery import RecoveryGate
```

Add this adapter to `ArenaStateMachine`:

```python
def observe_battle(
    self,
    screen: np.ndarray,
    previous_screen: np.ndarray | None,
) -> BattleObservation:
    start = self._locate(screen, "battle_start")
    manual = self._locate(screen, "auto_off")
    result = self._locate(screen, "confirm")
    progressing = valid_game_frame(screen) and meaningful_change(previous_screen, screen)
    return BattleObservation(
        pre_battle_visible=start is not None,
        battle_visible=manual is not None or progressing,
        result_visible=result is not None,
        frame_valid=valid_game_frame(screen),
        auto_state=(
            AutoBattleState.MANUAL
            if manual is not None
            else AutoBattleState.AUTO
            if progressing
            else AutoBattleState.UNKNOWN
        ),
        auto_point=None if manual is None else manual.center,
        business_progress=progressing,
    )
```

- [ ] **Step 4: Delegate the committed interval**

Add `battle_supervisor: BattleSupervisor | None = None` to `ArenaRunner.__init__`, then initialize:

```python
self.battle_supervisor = battle_supervisor or BattleSupervisor(
    runtime,
    self.recovery_gate,
    BattleConfig(mode="arena"),
    now=lambda: monotonic(),
    sleep=sleep,
)
```

Add:

```python
def _run_committed_battle(self, *, cycle: int) -> None:
    outcome = self.battle_supervisor.run(self.machine.observe_battle, cycle=cycle)
    if outcome is not BattleOutcome.RESULT_REACHED:
        raise RuntimeError(f"unexpected arena battle outcome: {outcome.value}")
    self.machine.state = ArenaState.RESULT
```

In the existing action block, immediately after `self.runtime.click(action.point, action.name)`, add:

```python
if action.name == "battle-start":
    self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
    state_started = monotonic()
    stable.reset()
    continue
```

This branch must appear before `_wait_until_in_state`; entry confirmation now belongs to the locked supervisor.

Do not move friendship-ticket validation, the daily purchase stamp, result confirmation, rank promotion, or opponent selection. Delete only the `ArenaState.RESULT` 900-second battle wait and its heartbeat after the focused tests pass; `ArenaState.RESULT` must now mean post-battle result handling only.

- [ ] **Step 5: Verify arena and commit**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_arena.py auto_game_unified/tests/test_arena_runner.py auto_game_unified/tests/test_navigation.py auto_game_unified/tests/test_ticket_exhaustion.py -q
```

Expected: all pass, including friendship-points purchase counterexamples.

Commit:

```powershell
git -C auto_game_unified add games/epic7/arena.py tests/test_epic7_arena.py tests/test_arena_runner.py
git -C auto_game_unified commit -m "migrate arena to shared battle supervisor"
```

### Task 5: Migrate story

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_story_runner.py`

- [ ] **Step 1: Add failing story adapter and delegation tests**

In `tests/test_epic7_story.py`, add:

```python
def test_story_adapter_uses_background_independent_control_classifier(self):
    machine = StoryStateMachine(build_story_templates(TEMPLATES))
    manual = machine.observe_battle(load_fixture("battle_auto_off_live_20260809"), None)
    auto = machine.observe_battle(load_fixture("battle_auto_on_live_20260809"), None)
    result = machine.observe_battle(load_fixture("results"), None)

    self.assertEqual(AutoBattleState.MANUAL, manual.auto_state)
    self.assertIsNotNone(manual.auto_point)
    self.assertEqual(AutoBattleState.AUTO, auto.auto_state)
    self.assertTrue(result.result_visible)


def test_story_adapter_whitelists_post_start_story_actions(self):
    machine = StoryStateMachine(build_story_templates(TEMPLATES))
    story = machine.observe_battle(load_fixture("story"), None)
    skip_confirm = machine.observe_battle(load_fixture("skip_confirm"), None)

    self.assertEqual("skip", story.allowed_action[0])
    self.assertEqual("skip_confirm", skip_confirm.allowed_action[0])
```

In `tests/test_story_runner.py`, add:

```python
def test_story_committed_battle_returns_control_to_results_state(self):
    machine = unittest.mock.MagicMock()
    machine.state = StoryState.WAIT_BATTLE
    supervisor = unittest.mock.MagicMock()
    supervisor.run.return_value = BattleOutcome.RESULT_REACHED
    runner = StoryRunner(
        machine,
        Runtime(lambda: np.zeros((60, 100, 3), dtype=np.uint8), lambda point: None),
        battle_supervisor=supervisor,
        sleep=lambda seconds: None,
    )

    runner._run_committed_battle(cycle=1)

    supervisor.run.assert_called_once_with(machine.observe_battle, cycle=1)
    self.assertEqual(StoryState.WAIT_RESULTS, machine.state)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_story.py auto_game_unified/tests/test_story_runner.py -q
```

Expected: FAIL because the story adapter and delegation method do not exist.

- [ ] **Step 3: Translate the existing story classifier**

Add these imports to `games/epic7/story.py`:

```python
from auto_game_unified.core.battle_supervisor import (
    AutoBattleState,
    BattleConfig,
    BattleObservation,
    BattleOutcome,
    BattleSupervisor,
    valid_game_frame,
)
from auto_game_unified.core.recovery import RecoveryGate
```

Add `observe_battle(screen, previous_screen)` to `StoryStateMachine`. Keep `observe_battle_controls` unchanged and translate it as follows:

```python
controls = self.observe_battle_controls(screen)
auto_state = {
    BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
    BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
    BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
}[controls]
auto_match = self._locate(screen, "auto_off")
allowed_action = None
for action_name in ("skip_confirm", "skip", "watch_story"):
    match = self._locate(screen, action_name)
    if match is not None:
        allowed_action = (action_name, match.center)
        break
return BattleObservation(
    pre_battle_visible=self._locate(screen, "start_mission") is not None,
    battle_visible=controls is not BattleControls.TRANSITION,
    result_visible=any(
        self._locate(screen, name) is not None
        for name in ("reward", "clear", "results_confirm")
    ),
    frame_valid=valid_game_frame(screen),
    auto_state=auto_state,
    auto_point=(
        auto_match.center
        if auto_match is not None
        else self._scaled_point(screen, self._AUTO_CLICK_POINT)
        if auto_state is AutoBattleState.MANUAL
        else None
    ),
    business_progress=(
        auto_state is AutoBattleState.AUTO
        and meaningful_change(previous_screen, screen)
    ),
    allowed_action=allowed_action,
)
```

- [ ] **Step 4: Delegate only the active battle interval**

Add `battle_supervisor: BattleSupervisor | None = None` to `StoryRunner.__init__`, then initialize:

```python
self.battle_supervisor = battle_supervisor or BattleSupervisor(
    runtime,
    self.recovery_gate,
    BattleConfig(mode="story"),
    now=lambda: monotonic(),
    sleep=sleep,
)
```

Add:

```python
def _run_committed_battle(self, *, cycle: int) -> None:
    outcome = self.battle_supervisor.run(self.machine.observe_battle, cycle=cycle)
    if outcome is not BattleOutcome.RESULT_REACHED:
        raise RuntimeError(f"unexpected story battle outcome: {outcome.value}")
    self.machine.state = StoryState.WAIT_RESULTS
```

In the existing action block, immediately after `self.runtime.click(action.point, action.name)`, add:

```python
if action.name == "start_mission":
    self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
    state_started = monotonic()
    absolute_started = state_started
    last_action_name = None
    last_action_clicked_at = None
    action_attempts = 0
    stable.reset()
    continue
```

This ensures the gate locks in the same Runner iteration as the click.

The adapter whitelist above preserves the post-start story/skip/skip-confirm branch while the recovery lock remains held. Keep pre-start story handling, stamina leaf refill, friend request cancellation, friendship popup, bonus reward, completion, and next-stage cycle counting unchanged. Delete only story-local active-frame heartbeat, automatic confirmation timeout, battle no-progress handling, and 900-second active-battle timeout after focused tests pass.

- [ ] **Step 5: Verify story and commit**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_story.py auto_game_unified/tests/test_story_runner.py auto_game_unified/tests/test_navigation.py -q
```

Expected: all pass, including the background-independent four-avatar regression and all story popup fixtures.

Commit:

```powershell
git -C auto_game_unified add games/epic7/story.py tests/test_epic7_story.py tests/test_story_runner.py
git -C auto_game_unified commit -m "migrate story to shared battle supervisor"
```

### Task 6: Add cross-mode safety invariants and documentation

**Files:**
- Create: `tests/test_battle_safety_invariants.py`
- Modify: `README.md`
- Modify: `docs/HUMAN_AI_WORKFLOW.md`

- [ ] **Step 1: Add cross-mode invariant tests**

Create `tests/test_battle_safety_invariants.py` with a parameterized factory for the three real state machines and their existing fixtures. For each mode, run these exact assertions:

```python
@pytest.mark.parametrize("mode", ["story", "arena", "expedition"])
def test_unknown_auto_state_never_exposes_a_click_point(mode, adapter_case):
    machine, screen = adapter_case(mode, "unknown")
    observation = machine.observe_battle(screen, None)
    assert observation.auto_state is AutoBattleState.UNKNOWN
    assert observation.auto_point is None


@pytest.mark.parametrize("mode", ["story", "arena", "expedition"])
def test_result_anchor_is_outside_the_committed_battle(mode, adapter_case):
    machine, screen = adapter_case(mode, "result")
    observation = machine.observe_battle(screen, None)
    assert observation.result_visible is True
    assert observation.pre_battle_visible is False


@pytest.mark.parametrize("mode", ["story", "arena", "expedition"])
def test_runner_uses_the_same_recovery_gate_as_its_supervisor(mode, runner_case):
    runner, recoveries = runner_case(mode)
    assert runner.battle_supervisor.gate is runner.recovery_gate


@pytest.mark.parametrize("mode", ["story", "arena", "expedition"])
def test_committed_battle_blocks_every_mode_recovery_callback(mode, runner_case):
    runner, recoveries = runner_case(mode)
    runner.recovery_gate.lock(mode=mode, cycle=1)
    with pytest.raises(RecoveryBlocked):
        runner.recovery("cross-mode invariant")
    runner.recovery_gate.unlock()
    assert recoveries == []
```

Define the fixtures with these concrete mappings:

```python
RESULT_FIXTURES = {
    "story": "tests/fixtures/epic7_story/results.png",
    "arena": "tests/fixtures/epic7_arena/result.png",
    "expedition": "tests/fixtures/epic7_expedition/result.png",
}
@pytest.fixture
def adapter_case():
    def build(mode: str, case: str):
        template_root = ROOT / "games" / "epic7" / "templates"
        spec = get_mode(mode)
        machine = spec.build_machine(template_root, spec.default_state)
        if case == "result":
            path = ROOT / RESULT_FIXTURES[mode]
            image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        else:
            image = np.zeros((1132, 1982, 3), dtype=np.uint8)
        return machine, image
    return build


@pytest.fixture
def runner_case(tmp_path):
    def build(mode: str):
        template_root = ROOT / "games" / "epic7" / "templates"
        spec = get_mode(mode)
        machine = spec.build_machine(template_root, spec.default_state)
        runtime = Runtime(
            lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
            lambda point: None,
            diagnostic_dir=tmp_path / mode,
            emit=lambda line: None,
        )
        recoveries: list[str] = []
        runner = spec.runner_type(
            machine,
            runtime,
            recovery=lambda: recoveries.append("recover"),
        )
        return runner, recoveries
    return build
```

Import `cv2`, `numpy as np`, `pytest`, `Path`, `Runtime`, `AutoBattleState`, `RecoveryBlocked`, and `get_mode`; set `ROOT = Path(__file__).resolve().parents[1]`. Do not generate or capture emulator screenshots in this test.

- [ ] **Step 2: Run invariant and full offline tests**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_battle_safety_invariants.py -q
python -m pytest auto_game_unified/tests -q
python -m compileall -q auto_game_unified
git -C auto_game_unified diff --check
```

Expected: all tests pass, compile exits 0, and diff check is clean.

- [ ] **Step 3: Document the shared boundary**

Update `README.md` and `docs/HUMAN_AI_WORKFLOW.md` with these explicit statements:

- Battle commitment starts immediately after the mode-specific battle-start click is verified.
- Until a stable result anchor appears, recovery-to-lobby and Back are forbidden.
- Automatic battle is clicked only for `MANUAL`, once per battle; `UNKNOWN` never causes a click.
- Heartbeats appear every 30 seconds; terminal uncertainty saves a diagnostic and exits with code 1.
- All live emulator runs are started, observed, and stopped by the user. The AI performs offline tests only, then analyzes user-reported logs and screenshots and adds a regression test before any fix.

- [ ] **Step 4: Commit and push**

Run:

```powershell
git -C auto_game_unified add tests/test_battle_safety_invariants.py README.md docs/HUMAN_AI_WORKFLOW.md
git -C auto_game_unified commit -m "document and verify shared battle safety"
git -C auto_game_unified push origin main
```

Expected: push succeeds and `git -C auto_game_unified status --short` is empty.

## User-owned live acceptance

After offline delivery, the user manually runs one command at a time:

```powershell
python -u -m auto_game_unified.main --mode expedition --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode arena --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode story --max-cycles 1 --live --confirm RUN
```

The AI does not start, click, stop, or control the emulator. If the user reports a failure, inspect `runtime_logs` and `runtime_diagnostics`, write a failing offline regression first, implement the smallest fix, and rerun the focused plus full offline suites.
