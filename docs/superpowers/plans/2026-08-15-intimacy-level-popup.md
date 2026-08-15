# Intimacy Level Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize and dismiss the captured Epic Seven hero intimacy-level-up overlay in the shared global popup layer.

**Architecture:** Add a dedicated two-anchor template set and finder to `global_popups.py`, then let the existing capture guard handle either network retry or intimacy dismissal with the same stable-frame and two-click safety limits. `main.py` loads both global template sets once for every live mode.

**Tech Stack:** Python 3, OpenCV/NumPy template matching, pytest, existing Runtime capture guard.

---

### Task 1: Capture assets and recognition

**Files:**
- Create: `tests/fixtures/epic7_global/intimacy_level_up_live_20260815.png`
- Create: `games/epic7/templates/global/intimacy_level_up_title.png`
- Create: `games/epic7/templates/global/intimacy_level_up_dismiss.png`
- Modify: `games/epic7/global_popups.py`
- Modify: `tests/test_global_popups.py`

- [ ] Add tests that load `IntimacyLevelUpTemplates`, recognize the real fixture, reject removal of either anchor, and reject normal story/fodder result pages.
- [ ] Run `python -m pytest auto_game_unified/tests/test_global_popups.py -q` from the worktree parent and confirm the missing API/templates produce RED.
- [ ] Crop only the stable title and dismissal glyphs from the captured fixture, then implement `load_intimacy_level_up_templates()` and `find_intimacy_level_up_dismiss()` using bright foreground masks and fixed reference regions.
- [ ] Re-run the focused recognition tests and confirm GREEN.

### Task 2: Shared guard integration

**Files:**
- Modify: `games/epic7/global_popups.py`
- Modify: `main.py`
- Modify: `tests/test_global_popups.py`
- Modify: `tests/test_main_story.py`

- [ ] Add a failing guard test with two popup frames followed by a normal result frame; assert one click at the dismissal hint and `dismiss-intimacy-level-up` in logs.
- [ ] Extend the guard constructor with the intimacy templates and select the known popup action on every loop while preserving the existing stable-frame, retry interval, diagnostic, and manual-stop behavior.
- [ ] Pass the new template set from `run_mode()` and update wiring assertions.
- [ ] Run global popup and main wiring suites, then the complete offline suite.

### Task 3: Finish

**Files:**
- Only the files above and the approved design/plan documents.

- [ ] Run `git diff --check`, inspect the final diff, and run `python -m pytest -q` with zero failures.
- [ ] Commit on `fix/intimacy-level-popup`, fast-forward local `main`, re-run the full suite on merged `main`, and push `origin/main`.
