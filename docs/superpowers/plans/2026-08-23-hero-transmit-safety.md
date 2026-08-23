# Hero Transmit Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make emulator hero synthesis transmit exactly one safe, highlighted non-SSS card, then return to the hero list and continue the normal cycle.

**Architecture:** Keep the existing visual state machine, adding explicit transitional states for aborting imprint and returning after transmit. Narrow the highlighted-card detector to the actual selected blue row, and validate the selected row with the tight SSS material template before any transmit click.

**Tech Stack:** Python, OpenCV, unittest fixtures.

---

### Task 1: Lock the four observed regressions with tests

**Files:**
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Add tests for the highlighted row center, SSS blocking, post-reward return, and imprint-abort settling.**
- [ ] **Step 2: Run the focused tests and confirm each fails for the current implementation.**

### Task 2: Fix transmit targeting and state transitions

**Files:**
- Modify: `games/epic7/hero_synthesis.py`

- [ ] **Step 1: Add explicit transient states and preserve them in preview/recovery/timeouts.**
- [ ] **Step 2: Detect the selected blue row without merging unrelated rows.**
- [ ] **Step 3: Refuse to select or start transmission when the selected row contains SSS.**
- [ ] **Step 4: Wait for the hero-list screen after aborting imprint and after closing transmit reward before continuing.**

### Task 3: Verify and commit

**Files:**
- Modify: `tests/test_hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py`

- [ ] **Step 1: Run focused regression tests.**
- [ ] **Step 2: Run the full test suite.**
- [ ] **Step 3: Inspect the diff and commit the verified changes.**
- [ ] **Step 4: Announce before starting the real emulator test.**

