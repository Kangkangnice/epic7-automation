# Shared Network Reconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize and retry the recorded network popup during committed battles in story, arena, and expedition, with a strict two-click limit.

**Architecture:** A shared Epic Seven popup detector requires message and retry anchors. Each mode exposes the same allowed battle action, while `BattleSupervisor` owns retry timing, limits, diagnostics, and recovery-lock safety.

**Tech Stack:** Python 3, OpenCV template matching, NumPy, existing battle supervisor, pytest/unittest fixtures.

---

### Task 1: Lock the real popup and shared detector

**Files:**
- Create: `tests/fixtures/epic7_global/network_reconnect.png`
- Create: `games/epic7/templates/global/network_message.png`
- Create: `games/epic7/templates/global/network_retry.png`
- Create: `games/epic7/global_popups.py`
- Create: `tests/test_global_popups.py`
- Modify: `tests/test_project_layout.py`

- [ ] Copy the real diagnostic to the global fixture and crop the two fixed-region templates.
- [ ] Add failing tests requiring both anchors, and rejecting removal of either anchor plus normal game fixtures.
- [ ] Implement `NetworkReconnectTemplates`, `load_network_reconnect_templates()`, and `find_network_retry()` with fixed regions and reference size `(1982, 1132)`.
- [ ] Run `python -m pytest auto_game_unified\tests\test_global_popups.py auto_game_unified\tests\test_project_layout.py -q` and commit.

### Task 2: Add bounded shared retry behavior

**Files:**
- Modify: `core/battle_supervisor.py`
- Modify: `tests/test_battle_supervisor.py`

- [ ] Add failing fake-clock tests proving two clicks maximum, `network_retry_failed` after the second click persists, disappearance resumes battle, and a later new popup resets the allowance.
- [ ] Add `network_retry_interval_seconds=3` and `network_retry_failure_seconds=15` to `BattleConfig`.
- [ ] Special-case only action name `retry-network`; leave existing one-click whitelist semantics unchanged.
- [ ] Run `python -m pytest auto_game_unified\tests\test_battle_supervisor.py -q` and commit.

### Task 3: Wire all three battle adapters

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_epic7_arena.py`
- Modify: `tests/test_epic7_expedition.py`
- Modify: `tests/test_battle_safety_invariants.py`

- [ ] Add failing adapter tests against the same global fixture.
- [ ] Load one `NetworkReconnectTemplates` object in each mode template bundle and check it before mode-specific battle actions.
- [ ] Assert all three return `("retry-network", point)` without claiming result/pre-battle state.
- [ ] Run the three mode suites plus cross-mode invariants and commit.

### Task 4: Full offline verification

**Files:**
- Modify: `README.md`

- [ ] Document bounded network retry and safe stop.
- [ ] Run `python -m pytest auto_game_unified\tests -q`.
- [ ] Run `python -m compileall -q auto_game_unified` and `git -C auto_game_unified diff --check`.
- [ ] Commit documentation and present branch integration options. Do not run the emulator.
