# PC Template Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the launcher test baseline and define evidence-based PC template migration without treating existing PC PNG files as validated.

**Architecture:** The launcher continues to choose a backend before a route; its tests must supply and assert that protocol. PC migration is validated per stable screen: one full PC fixture proves the page, crops come only from visible anchors on that fixture, and a route is accepted only after offline matching plus one controlled live cycle.

**Tech Stack:** Python 3.10, pytest, Markdown, OpenCV template matching.

---

### Task 1: Align launcher tests with the current platform-selection protocol

**Files:**
- Modify: `tests/test_launcher.py:7-106`

- [x] **Step 1: Keep the existing failing reproduction**

Run: `python -m pytest -q tests/test_launcher.py`

Expected: seven failures because old tests provide route input where `run_interactive()` now requests a platform.

- [x] **Step 2: Update test inputs and assertions**

```python
inputs = iter(["1", choice, "3"])
assert calls == [[
    "--mode", mode,
    "--window-backend", "emulator",
    "--max-cycles", "3",
    "--live", "--confirm", "RUN",
]]
```

Add a dedicated PC case with `inputs = iter(["2", "1", "1"])` and assert `--window-backend pc` is passed through.

- [x] **Step 3: Run launcher tests**

Run: `python -m pytest -q tests/test_launcher.py`

Expected: PASS.

### Task 2: Record the PC template acceptance protocol

**Files:**
- Create: `docs/PC_TEMPLATE_MIGRATION.md`

- [x] **Step 1: Document the current baseline and unsafe batch-capture restriction**

State that all six routes are unverified; the existing `templates_pc/` files are candidates only. Do not use `tools/capture_pc_templates.py` batch mode to certify templates because one page group currently includes anchors from different game states.

- [x] **Step 2: Document per-page evidence and acceptance gates**

For every PC state: save a full `1982×1132` fixture, crop only visibly present anchors, add a positive and negative offline matcher assertion, build the mode successfully, run a dry diagnostic, then run one user-observed live cycle. Start with `story`; shared lobby and global popup fixtures become reusable evidence for later routes.

### Task 3: Verify the repository baseline

**Files:**
- Modify: none

- [x] **Step 1: Run the full suite**

Run: `python -m pytest -q`

Expected: PASS with no launcher failures.
