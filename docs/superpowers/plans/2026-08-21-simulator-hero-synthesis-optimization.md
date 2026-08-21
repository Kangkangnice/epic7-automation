# Simulator Hero Synthesis Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the simulator hero-synthesis mode safely finish one complete filtered three-star list traversal.

**Architecture:** Keep the existing pure screenshot-driven state machine and shared `ModeRunnerBase`. Add a simulator-only synthesis-result overlay branch, strengthen the card action fingerprint, and prove the full sequence with fixture-driven tests before any live run.

**Tech Stack:** Python 3.10+, OpenCV, unittest/pytest, existing `Runtime` and `ModeRunnerBase`.

---

### Task 1: Reproduce the synthesis-result overlay

**Files:**
- Create: `tests/fixtures/epic7_hero/imprint_result_popup.png` from the existing local diagnostic `runtime_diagnostics/epic7_hero_synthesis/20260819_110126_995590_unknown_before_wake.png`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Add the recorded popup fixture and a failing behavior test.**

  Assert that a machine in `IMPRINT_CONFIRM` returns a named result-popup close action instead of `back_to_list` when given the recorded result overlay.

- [ ] **Step 2: Run the focused test and verify it fails for the missing behavior.**

  Run: `python -m pytest tests/test_hero_synthesis.py -q`

  Expected: the new assertion fails because the current machine has no result-popup action.

### Task 2: Add the simulator result-popup state and close action

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`
- Modify: `games/epic7/templates/hero/` with the popup close/title crop from the recorded fixture

- [ ] **Step 1: Add the minimal simulator template field and optional PC loading.**

  Load the new simulator result-popup anchor only when the template exists; PC template construction must continue to work without it.

- [ ] **Step 2: Add the result-popup state and detection before `_back_action`.**

  When the result popup is visible, return `close_imprint_result` and never return `back_to_list`. After the click, keep the machine in the result state until the overlay is gone and the existing back arrow is visible.

- [ ] **Step 3: Run the focused popup test and the existing hero tests.**

  Run: `python -m pytest tests/test_hero_synthesis.py -q`

  Expected: all hero tests pass, including the new popup regression.

### Task 3: Strengthen consecutive-card progress detection

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Add a regression assertion for two different recorded cards that currently share the coarse fingerprint bucket.**

  The test must prove that the generated `next_card_` action signatures are different for the two fixtures, without changing the click point.

- [ ] **Step 2: Run the new test and verify it fails with the current `mean // 16` fingerprint.**

  Run: `python -m pytest tests/test_hero_synthesis.py -q`

  Expected: the fingerprint-collision assertion fails before implementation.

- [ ] **Step 3: Replace the coarse brightness bucket with a compact stable multi-feature fingerprint.**

  Use the existing detail crop and stable selected-card area; retain a short deterministic string in the action name and keep the `next_card_` prefix unchanged.

- [ ] **Step 4: Run the focused tests and verify the collision regression passes.**

  Run: `python -m pytest tests/test_hero_synthesis.py -q`

  Expected: all focused hero tests pass.

### Task 4: Prove the complete simulator one-round sequence

**Files:**
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Add a fixture-driven multi-card runner sequence.**

  Include filter entry, a normal card, an SSS card, a red-dot non-SSS card, material selection, synthesis confirmation, result-popup close, result detail back, and end-of-list. Assert the exact click action order and `completed_cycles == 1`.

- [ ] **Step 2: Run the sequence test and verify it fails before the result-overlay and fingerprint changes are present.**

  Run: `python -m pytest tests/test_hero_synthesis.py::RunnerFlowTests -q`

  Expected: the old sequence cannot pass through the recorded result popup.

- [ ] **Step 3: Run all hero and navigation tests.**

  Run: `python -m pytest tests/test_hero_synthesis.py tests/test_navigation.py -q`

  Expected: all focused tests pass.

### Task 5: Full verification and live handoff

**Files:**
- No additional production files unless a focused regression exposes a directly related defect.

- [ ] **Step 1: Run the full offline suite and compile check.**

  Run: `python -m pytest -q` and `python -m compileall -q .`

- [ ] **Step 2: Review the final diff and commit the implementation.**

  Run: `git diff --check`, `git status --short`, then commit the simulator hero-synthesis changes.

- [ ] **Step 3: Ask the user to open the simulator for one controlled live cycle.**

  The user starts from the game lobby with the simulator at the existing `1982 x 1132` template geometry, does not touch input during the run, and sends the resulting log/diagnostic if the run stops.
