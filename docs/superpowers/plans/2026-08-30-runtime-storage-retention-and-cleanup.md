# Runtime Storage Retention And Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound every automatically generated runtime log and failure screenshot, preserve recoverable Git history, and leave the main working directory clean.

**Architecture:** Keep the existing per-route `Runtime` retention unchanged. Add equivalent local retention to `WorkerController`: rotate `desktop_worker.log` at 5 MiB with four backups and prune `runtime_diagnostics/desktop_worker` to the newest 30 PNG files. Runtime artifacts and caches remain ignored and can be deleted safely because the application recreates them.

**Tech Stack:** Python 3, pathlib, pytest, Git worktrees.

---

### Task 1: Preserve current main work

**Files:**
- Commit: existing modified source, tests, documentation, and PC fixture PNG files

- [ ] Run `python -m pytest -q` from the repository parent and require exit code 0.
- [ ] Run `git diff --check` and require no whitespace errors.
- [ ] Commit the existing PC migration changes separately from retention work.

### Task 2: Specify desktop worker retention

**Files:**
- Modify: `tests/test_desktop_worker.py`

- [ ] Add `test_worker_rotates_evidence_log_and_discards_oldest_backup` using a one-byte threshold and two backups; require the fourth message in the current file, third in `.1`, second in `.2`, and first absent.
- [ ] Add `test_worker_keeps_only_latest_failure_snapshots` using a limit of two and three abnormal snapshots; require exactly the latest two PNG files.
- [ ] Run both tests and confirm they fail because `WorkerController` does not yet accept or enforce these limits.

### Task 3: Implement minimal retention

**Files:**
- Modify: `desktop/worker.py`

- [ ] Add constructor defaults `max_log_bytes=5 * 1024 * 1024`, `log_backups=4`, and `snapshot_limit=30`.
- [ ] Before appending a worker evidence line, rotate the log when the next encoded line would exceed the configured size.
- [ ] After copying an abnormal-exit frame, delete older worker PNG files beyond the configured limit.
- [ ] Run `python -m pytest -q auto_game_unified/tests/test_desktop_worker.py` and require exit code 0.

### Task 4: Preserve and remove old worktrees and generated artifacts

**Files:**
- Remove: registered worktree directories under `.worktrees` after saving any dirty state to local Git branches
- Remove: `.pytest_cache`, `__pycache__`, ignored scratch probes, `runtime_logs`, and `runtime_diagnostics`

- [ ] Inspect every registered worktree status.
- [ ] Commit dirty worktree contents to their existing local branch so they remain recoverable.
- [ ] Remove registered worktrees through `git worktree remove`, then run `git worktree prune`.
- [ ] Delete only verified generated or ignored artifacts inside the repository.

### Task 5: Verify and finish main

**Files:**
- Commit: `desktop/worker.py`, `tests/test_desktop_worker.py`, and this plan

- [ ] Run `python -m pytest -q` and require exit code 0 with no failures.
- [ ] Run `git diff --check` and require no whitespace errors.
- [ ] Commit retention and cleanup documentation.
- [ ] Run `git status --short --branch` and require no modified or untracked files on `main`.
