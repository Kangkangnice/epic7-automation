# Story Friend Request Cancel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cancel every post-battle friend request safely before the existing story result flow continues.

**Architecture:** Add two tightly-scoped templates for the fixed popup title and the left cancel button. `StoryStateMachine` exposes one dual-anchor detector and places its action before all existing result actions without changing the current story state.

**Tech Stack:** Python 3, OpenCV, NumPy, Pillow, unittest/pytest

---

### Task 1: Add the recorded failure as a regression sample

**Files:**
- Create: `tests/fixtures/epic7_story/friend_request.png`
- Modify: `tests/test_epic7_story.py`

- [ ] Copy `runtime_diagnostics/epic7_story/20260810_230620_045976_timeout_wait_results.png` byte-for-byte to the fixture path.
- [ ] Add `test_friend_request_requires_title_and_cancel_button` that calls `find_friend_request_cancel`, asserts the full screenshot returns a point inside `x=650..950, y=790..900`, and asserts removing either anchor returns `None`.
- [ ] Add `test_friend_request_cancel_has_priority_without_changing_result_state` that starts in `WAIT_RESULTS`, expects `cancel_friend_request`, and expects the state to remain `WAIT_RESULTS`.
- [ ] Run `python -m pytest tests/test_epic7_story.py -q` and confirm failure because `find_friend_request_cancel` is absent.

### Task 2: Add minimal fixed-UI templates and dual-anchor detection

**Files:**
- Create: `games/epic7/templates/story/friend_request_title.png`
- Create: `games/epic7/templates/story/friend_request_cancel.png`
- Modify: `games/epic7/story.py`

- [ ] Crop only the title from reference coordinates `(780, 275, 420, 80)` and only the cancel button from `(650, 790, 300, 105)`.
- [ ] Add both arrays to `StoryTemplates` and load them in `build_story_templates`.
- [ ] Add regions `friend_request_title=(650,240,700,160)` and `friend_request_cancel=(550,720,500,230)` with a `0.82` threshold.
- [ ] Implement `find_friend_request_cancel(screen)` to return the cancel match only when both templates match the same frame.
- [ ] Insert `cancel_friend_request` before `reward` in `next_action`, returning the cancel center without changing `self.state`.
- [ ] Run `python -m pytest tests/test_epic7_story.py -q` and require all tests to pass.

### Task 3: Prove the popup integrates with the complete story sequence

**Files:**
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_story_runner.py`

- [ ] Insert `friend_request` between `clear` and `results` in the recorded one-cycle state-machine test and expect one `cancel_friend_request` action.
- [ ] Add the same insertion to the runner replay and assert the log contains one `action=cancel_friend_request` per inserted popup.
- [ ] Run `python -m pytest tests/test_epic7_story.py tests/test_story_runner.py -q` and require zero failures.

### Task 4: Offline-only final verification

**Files:**
- No production changes unless a regression is caused by Tasks 1–3.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q .` and require exit code `0`.
- [ ] Report the manual live command and expected `action=cancel_friend_request` log; do not start the emulator.
