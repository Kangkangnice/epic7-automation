# Unknown Screen Wake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded, shared two-click center-screen recovery before existing safe failure handling for static unknown Epic Seven screens.

**Architecture:** `games/epic7/unknown_screen.py` owns the game-specific safety policy and the dedicated `UnrecognizedScreen` exception. Navigation and the four live runners call it only outside `BattleSupervisor`; state machines mark only their final unrecognized-state failure with the dedicated exception.

**Tech Stack:** Python 3, NumPy, OpenCV, pytest, existing Runtime/RecoveryGate/BattleControls.

---

### Task 1: Shared unknown-screen policy

**Files:**
- Create: `games/epic7/unknown_screen.py`
- Create: `tests/test_unknown_screen.py`

- [ ] **Step 1: Write failing tests** for a static valid screen returning `WAITING`, `CLICKED`, and finally `EXHAUSTED`, with exactly two center clicks; also cover black frames, dynamic frames, visible battle controls, locked recovery, reset, and diagnostics.
- [ ] **Step 2: Run** `python -m pytest auto_game_unified/tests/test_unknown_screen.py -q` from the worktree parent and confirm import/behavior failures.
- [ ] **Step 3: Implement** `UnknownWakeResult`, `UnrecognizedScreen`, and `UnknownScreenWake.handle/reset` with two-frame stability, `valid_game_frame`, `meaningful_change`, `observe_battle_controls`, relative center coordinates, diagnostics, logging, and a two-click budget.
- [ ] **Step 4: Re-run** the focused test and confirm it passes.

### Task 2: Navigation integration

**Files:**
- Modify: `games/epic7/navigation.py`
- Modify: `tests/test_navigation.py`

- [ ] **Step 1: Change the existing unknown-page test** to hold the page long enough to assert two center clicks occur before one controlled Back, and add a reset assertion for the next unknown page.
- [ ] **Step 2: Run** `python -m pytest auto_game_unified/tests/test_navigation.py -q` and confirm the new expectation fails.
- [ ] **Step 3: Add** one `UnknownScreenWake` instance to `Epic7Navigator`; invoke it only for `unknown` after existing post-Back waiting and before Back, reset it on known pages and after Back.
- [ ] **Step 4: Re-run** navigation tests and confirm they pass.

### Task 3: Mode runner integration

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/expedition.py`
- Modify: `games/epic7/fodder.py`
- Create: `tests/test_unknown_screen_runners.py`

- [ ] **Step 1: Write a parameterized failing test** whose fake machine raises `UnrecognizedScreen` for each runner; assert exactly two center clicks before its existing safe timeout path.
- [ ] **Step 2: Run** `python -m pytest auto_game_unified/tests/test_unknown_screen_runners.py -q` and confirm all four cases fail before integration.
- [ ] **Step 3: Replace only each state machine's final unrecognized-page `RuntimeError`** with `UnrecognizedScreen`; construct a shared wake handler in each runner, call it from the generic exception path only for that subtype, reset on recognized previews, and refresh the state timeout only after an actual wake click.
- [ ] **Step 4: Re-run** runner-focused tests and the existing runner suites.

### Task 4: Verification and integration

**Files:**
- Modify only files created by the preceding tasks.

- [ ] **Step 1: Run** `python -m pytest -q` from the worktree parent and require zero failures.
- [ ] **Step 2: Inspect** `git diff --check`, `git status --short`, and the final diff for scope and accidental changes.
- [ ] **Step 3: Commit** the implementation on `fix/unknown-screen-wake`.
- [ ] **Step 4: Merge** into local `main`, re-run the full suite on merged `main`, then push `main` to `origin` as explicitly requested.
