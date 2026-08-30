# Story Auto Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the animated upper-right Auto icon state check with a background-independent lower-right battle-control classifier and guarantee at most one Auto click per stage.

**Architecture:** `StoryStateMachine` classifies the lower-right HUD as automatic, manual, or transition from fixed control geometry in the game-local reference canvas. `StoryRunner` supplies the existing two-frame stability gate and fails closed when a one-time Auto click is not confirmed; the upper-right coordinate remains only the click target.

**Tech Stack:** Python 3, OpenCV, NumPy, unittest/pytest

---

### Task 1: Lock the classifier contract with offline tests

**Files:**
- Modify: `tests/test_epic7_story.py`

- [ ] Add tests asserting the current live Auto frame is `AUTO_CONTROLS`, the current live manual frame is `MANUAL_CONTROLS`, and an unrelated/occluded frame is `TRANSITION`.
- [ ] Add in-memory composites that replace everything outside the fixed control shapes and assert the classifications remain unchanged.
- [ ] Run `python -m pytest tests/test_epic7_story.py -v` and confirm the new tests fail because `BattleControls` and `observe_battle_controls` do not exist.

### Task 2: Implement the minimal lower-right structural classifier

**Files:**
- Modify: `games/epic7/story.py`

- [ ] Add `BattleControls` with `AUTO_CONTROLS`, `MANUAL_CONTROLS`, and `TRANSITION`.
- [ ] Normalize only the lower-right game-local ROI to the `1982x1132` reference canvas.
- [ ] Detect Auto only when all four expected slots have saturated blue lower bases and four aligned portrait-sized circular frames.
- [ ] Detect manual only when three aligned skill-sized circular frames are found and the Auto condition is absent; otherwise return transition.
- [ ] Run `python -m pytest tests/test_epic7_story.py -v` and confirm the classifier tests pass.

### Task 3: Enforce one Auto click per stage

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_story_runner.py`

- [ ] Add a failing state-machine test showing repeated manual frames yield only one `enable_auto` action.
- [ ] Reset the one-click guard only when a new mission starts; retain it through waves and mid-battle story.
- [ ] Use the lower-right classification for state decisions; use the scaled upper-right point only as the click target.
- [ ] Add a failing runner test showing an unconfirmed Auto click saves a diagnostic and stops without invoking lobby recovery.
- [ ] Implement the confirmation timeout and run the two story test modules until green.

### Task 4: Offline regression verification and handoff

**Files:**
- No production changes unless a regression directly caused by Tasks 1–3 is found.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run a focused offline two-cycle replay and confirm exactly one `enable_auto` action per stage.
- [ ] Provide the existing live command to the user; do not launch or control the emulator. Ask the user to return the visible log plus the saved current/failure frame if real testing fails.
