# Story Watch Next Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize Episode 4 story-only next stages without confusing battle buttons and count the completed stage before advancing.

**Architecture:** Keep the existing local search region but match only the stable white `观看故事` glyph mask. Add one state-aware count transition when `watch_story` is observed from `WAIT_NEXT_STAGE`; the Runner's existing count gate prevents clicking when the requested total is reached.

**Tech Stack:** Python 3, OpenCV, NumPy, unittest/pytest

---

### Task 1: Lock the real failure and false-positive boundary

**Files:**
- Create: `tests/fixtures/epic7_story/story_watch_next_ep4.png`
- Modify: `tests/test_project_layout.py`
- Modify: `tests/test_epic7_story.py`

- [ ] Copy `runtime_diagnostics/epic7_story/20260811_082347_712523_timeout_wait_next_stage.png` byte-for-byte to the fixture path and register it in the exact fixture inventory.
- [ ] Add a test starting from `WAIT_NEXT_STAGE` that expects `watch_story`, `WAIT_SKIP_CONFIRM`, and `completed_cycles == 1`.
- [ ] Add a test starting from `STAGE` that expects `watch_story` while `completed_cycles` remains `0`.
- [ ] Assert `_locate(..., "watch_story")` returns `None` for `stage_battle_ready_updated`, `stage`, `next_stage`, `team`, `results`, and a black frame.
- [ ] Run `python -m pytest tests/test_epic7_story.py -q`; expect the Episode 4 test to fail with an unrecognized `WAIT_NEXT_STAGE` screen.

### Task 2: Implement white-glyph matching and state-aware counting

**Files:**
- Modify: `games/epic7/story.py`

- [ ] Add a `watch_story` branch in `_locate` that converts the fixed search region and template to HSV, masks saturation `0..90` and value `150..255`, and calls `find_template` with threshold `0.72`.
- [ ] Convert the returned regional match center back to the full game-local canvas.
- [ ] In the existing action loop, capture the previous state; when `name == "watch_story"` and the previous state is `WAIT_NEXT_STAGE`, increment `completed_cycles` exactly once before setting `WAIT_SKIP_CONFIRM`.
- [ ] Run `python -m pytest tests/test_epic7_story.py -q` and require zero failures.

### Task 3: Verify Runner count gating

**Files:**
- Modify: `tests/test_story_runner.py`

- [ ] Add a Runner test with two stable Episode 4 frames, `WAIT_NEXT_STAGE`, and `max_cycles=1`; expect completion `1` and zero clicks.
- [ ] Replace the final `next_stage` frame of the recorded two-cycle replay with `story_watch_next_ep4`; expect two completed cycles and the existing click count unchanged.
- [ ] Run `python -m pytest tests/test_epic7_story.py tests/test_story_runner.py -q` and require zero failures.

### Task 4: Offline-only final verification

**Files:**
- No production changes unless a regression is directly caused by Tasks 1–3.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q .` and require exit code `0`.
- [ ] Report the live command to the user without launching the emulator.
