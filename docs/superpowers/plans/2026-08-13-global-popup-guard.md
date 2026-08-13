# Global Popup Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every live Epic Seven screenshot through one bounded network-popup guard before navigation or mode business logic sees it.

**Architecture:** Extend `Runtime` with an optional capture guard and implement the Epic Seven-specific stateful guard in `games/epic7/global_popups.py`. Install it once in `run_mode`; remove battle-mode-specific retry decisions so all phases share one policy.

**Tech Stack:** Python, NumPy, OpenCV template matching, pytest/unittest.

---

### Task 1: Preserve the new live failure as a shared regression sample

**Files:**
- Create: `tests/fixtures/epic7_global/network_reconnect_navigation.png`
- Modify: `tests/test_project_layout.py`
- Modify: `tests/test_global_popups.py`

- [ ] Copy the byte-identical 2026-08-13 20:10 diagnostic into the global fixture directory.
- [ ] Add both network fixtures to the exact project-layout expectation.
- [ ] Add a parameterized recognition test and run it to prove the current detector accepts the navigation frame.

### Task 2: Specify the stateful guard with failing tests

**Files:**
- Modify: `tests/test_global_popups.py`
- Modify: `games/epic7/global_popups.py`

- [ ] Add fake-clock tests proving two stable frames are required before the first click.
- [ ] Add a failing test proving the second click is allowed only after 3 seconds and persistence for 15 more seconds saves `network_retry_failed` and raises.
- [ ] Add a failing test proving disappearance resets the allowance.
- [ ] Implement only the state and timing required by these tests.
- [ ] Run `python -m pytest auto_game_unified/tests/test_global_popups.py -q` from the worktree parent.

### Task 3: Put the guard at the common capture boundary

**Files:**
- Modify: `core/runtime.py`
- Modify: `tests/test_runtime.py`

- [ ] Add a failing Runtime test where raw capture yields two popup frames and then a normal frame; assert callers receive only the normal frame and the guard owns the clicks.
- [ ] Add an optional capture-guard protocol/callback to Runtime while leaving unguarded tests unchanged.
- [ ] Ensure the guard's internal recapture path still checks the P hotkey and updates `_last_screen`.
- [ ] Run runtime and popup tests.

### Task 4: Install one guard for every live mode

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_story.py`

- [ ] Add a failing parameterized test for story, arena, and expedition asserting `run_mode` installs one `Epic7GlobalPopupGuard` on their shared Runtime before navigation and runner construction.
- [ ] Build shared templates once from `games/epic7/templates/global` and install the guard only for live runs.
- [ ] Run main and navigation tests.

### Task 5: Remove battle-only network handling

**Files:**
- Modify: `core/battle_supervisor.py`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_battle_supervisor.py`
- Modify: `tests/test_battle_safety_invariants.py`

- [ ] Replace the old three-mode `retry-network` invariant with a shared-capture invariant.
- [ ] Remove network retry counters and special action handling from BattleSupervisor.
- [ ] Remove network templates and observations from all three mode state machines.
- [ ] Keep story skip and other business allowlists unchanged.
- [ ] Run battle supervisor and all three mode test suites.

### Task 6: Verify and document

**Files:**
- Modify: `README.md`

- [ ] Document that live captures globally consume the known network reconnect popup in all phases.
- [ ] Run `python -m pytest auto_game_unified/tests -q`.
- [ ] Run `python -m compileall -q auto_game_unified` and `git diff --check`.
- [ ] Review the diff for scope, commit the implementation, and report that real-game validation remains with the user.
