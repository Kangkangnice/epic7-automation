# PC Click and Worker Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC clicks use a real press duration and persist enough desktop worker evidence to diagnose every child-process exit.

**Architecture:** Keep input timing inside `Epic7PcWindow` and process-lifecycle evidence inside `WorkerController`. Preserve all arena thresholds, coordinates, transition contracts, GUI events, and CLI exit semantics.

**Tech Stack:** Python, ctypes/Win32 SendInput, subprocess, pytest

---

### Task 1: PC mouse press duration

**Files:**
- Modify: `core/pc_window.py`
- Test: `tests/test_pc_window.py`

- [ ] **Step 1: Write the failing test**

Add a test that supplies a recording `SendInput` function and recording sleep function, calls `_send_click`, and asserts three calls in the order move/down/up with one `0.08` second wait between down and up.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_pc_window.py -k send_click`

Expected: FAIL because the current implementation sends all three events in one call and performs no wait.

- [ ] **Step 3: Write minimal implementation**

Inject an optional sleep callable into `Epic7PcWindow`, add a helper that checks one `SendInput` result, then send move, down, sleep for `0.08`, and send up.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_pc_window.py -k send_click`

Expected: PASS.

### Task 2: Persistent desktop worker lifecycle evidence

**Files:**
- Modify: `desktop/worker.py`
- Test: `tests/test_desktop_worker.py`

- [ ] **Step 1: Write the failing tests**

Add tests using `tmp_path` that assert `runtime_logs/desktop_worker.log` records the child PID and, on completion, the exit code, stop-request flag, and final output line. Add an abnormal exit case with a nonstandard exit code.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_desktop_worker.py`

Expected: FAIL because no persistent worker lifecycle log exists.

- [ ] **Step 3: Write minimal implementation**

Track the last output line and whether stop was requested. Append one timestamped UTF-8 line at start, stop request, and finish. Keep the existing `WorkerEvent` stream unchanged except that an abnormal finish message includes its numeric exit code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_desktop_worker.py`

Expected: PASS.

### Task 3: Regression verification

**Files:**
- No production changes

- [ ] **Step 1: Run focused regression tests**

Run: `pytest -q tests/test_pc_window.py tests/test_desktop_worker.py tests/test_epic7_arena.py tests/test_arena_runner.py`

Expected: all tests PASS.

- [ ] **Step 2: Inspect the precise diff**

Run: `git diff -- core/pc_window.py desktop/worker.py tests/test_pc_window.py tests/test_desktop_worker.py`

Expected: only the approved PC click timing and worker evidence changes appear.
