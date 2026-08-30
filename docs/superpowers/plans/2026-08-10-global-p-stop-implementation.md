# Global P Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the user to press global `P` during live automation to save the current frame, stop all later actions, log the reason, and exit with code 130.

**Architecture:** Add a small Windows key edge detector in `core/hotkey.py`. Inject its callback into `Runtime`, which checks before captures, clicks, and back actions and raises a dedicated `ManualStop`; `main.py` maps that exception to exit code 130.

**Tech Stack:** Python 3, ctypes Win32, unittest/pytest

**Repository note:** The workspace has no `.git` directory, so verification checkpoints replace commits.

---

### Task 1: Global P key edge detector

**Files:**
- Create: `auto_game_unified/core/hotkey.py`
- Create: `auto_game_unified/tests/test_hotkey.py`

- [ ] **Step 1: Write failing edge-detection tests**

Test injected Win32 states `up -> down -> down -> up -> down` and require results `False, True, False, False, True`. Also assert virtual key `0x50` is queried.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest auto_game_unified/tests/test_hotkey.py -q`

Expected: import error because `core.hotkey` does not exist.

- [ ] **Step 3: Implement the minimal detector**

Create `WindowsPStopHotkey` with an injected `get_key_state` callable defaulting to `ctypes.windll.user32.GetAsyncKeyState`. `pressed()` returns true only on the up-to-down edge of virtual key `0x50`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m pytest auto_game_unified/tests/test_hotkey.py -q`

Expected: all tests pass.

### Task 2: Runtime stop boundary and exit code

**Files:**
- Modify: `auto_game_unified/core/runtime.py`
- Modify: `auto_game_unified/main.py`
- Modify: `auto_game_unified/tests/test_runtime.py`
- Modify: `auto_game_unified/tests/test_main_story.py`

- [ ] **Step 1: Write failing runtime tests**

Add tests proving that a true `stop_requested` callback:

- prevents the next click from reaching the real click callback;
- raises `ManualStop` only once;
- writes `用户按下 P，正在中断自动化`;
- saves the most recently captured frame as a `manual_stop` diagnostic.

- [ ] **Step 2: Write a failing main exit-code test**

Patch `run_mode` to raise `ManualStop` and assert `main([...]) == 130`.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `python -m pytest auto_game_unified/tests/test_runtime.py auto_game_unified/tests/test_main_story.py -q`

Expected: failures because `ManualStop` and `stop_requested` are missing and main does not map exit code 130.

- [ ] **Step 4: Implement runtime stopping**

Add `ManualStop(RuntimeError)`, optional `stop_requested`, and `_last_screen` to `Runtime`. Check the signal before `capture`, `click`, and `back`; on the first signal, log the Chinese reason, save `_last_screen` when available, and raise `ManualStop` before performing the requested action.

- [ ] **Step 5: Wire the live hotkey and exit code**

In `_build_runtime`, construct `WindowsPStopHotkey` for live runs and pass `pressed` as `stop_requested`. In `main`, catch `ManualStop` before the broader `RuntimeError` handler, print the stop reason, and return 130.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python -m pytest auto_game_unified/tests/test_hotkey.py auto_game_unified/tests/test_runtime.py auto_game_unified/tests/test_main_story.py -q`

Expected: all focused tests pass.

### Task 3: Regression and live stop acceptance

**Files:**
- Verify: `auto_game_unified/tests/`
- Verify: `auto_game_unified/runtime_diagnostics/epic7_story/`

- [ ] **Step 1: Run the full offline regression**

Run: `python -m pytest auto_game_unified/tests -q`

Expected: all tests pass.

- [ ] **Step 2: Start a visible one-cycle story run**

Run in a visible PowerShell:

```powershell
cd D:\AI\codex\auto_game
$env:PYTHONUTF8="1"
python -u -m auto_game_unified.main --mode story --max-cycles 1 --live --confirm RUN
```

- [ ] **Step 3: Press P and verify acceptance**

Expected: no later click occurs, the terminal logs `用户按下 P，正在中断自动化`, a `manual_stop` diagnostic exists, and the process exits with code 130.
