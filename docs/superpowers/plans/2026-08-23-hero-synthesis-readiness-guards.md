# Hero Synthesis Readiness Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent emulator hero-synthesis flow from advancing on transient loading frames by requiring content-ready and consecutive absence confirmations.

**Architecture:** Keep the existing `HeroSynthStateMachine` and fixture-driven tests. Add only small observation counters and readiness predicates in `games/epic7/hero_synthesis.py`; reset counters whenever a relevant action or state transition occurs. The existing Runner two-frame action confirmation remains unchanged because it confirms action stability, while the state machine adds semantic readiness confirmation.

**Tech Stack:** Python, OpenCV color/template detection, `unittest`, existing Epic Seven screenshot fixtures.

---

### Task 1: Add failing regression tests for transient absence

**Files:**
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Add tests for imprint loading and absence confirmation**

Add tests that call `next_action` with a synthetic loading frame or a fixture with the material strip temporarily hidden. The first empty observation must return `None`, the second consecutive empty observation must still not start synthesis unless the configured confirmation count is reached, and the existing `imprint_added` fixture must still produce `start_synthesis` after the required confirmations.

- [ ] **Step 2: Add tests for transmit-card loading**

Start from `HeroSynthState.TRANSMIT_SELECT`, use `transmit_select` with the highlighted-card strip erased, and assert the first missing-card observation returns `None` rather than `back_to_list`. The normal `transmit_select` fixture must still produce `start_transmit`.

- [ ] **Step 3: Add a test for list-end stability**

Use `list_end_of_cards` after a state that can advance and assert a single missing-next-card observation does not increment `completed_cycles`; repeated stable observations must still complete exactly one cycle.

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py -k "imprint or transmit or end_of_cards" -q
```

Expected: the new tests fail because the current state machine advances immediately on the first missing observation.

### Task 2: Implement semantic readiness guards

**Files:**
- Modify: `games/epic7/hero_synthesis.py:140-180, 620-730`

- [ ] **Step 1: Add bounded observation counters**

Add private counters initialized in `HeroSynthStateMachine.__init__` for imprint-empty, transmit-card-missing, and list-end observations. Use a small constant of two consecutive semantic observations. Reset the relevant counter whenever the expected content is detected or an action/state transition leaves the screen.

- [ ] **Step 2: Guard imprint completion**

Keep SSS-material detection first. When the green imprint button exists but no Up card is found, increment the imprint-empty counter and return `None` until the counter reaches the confirmation count. Only then set `IMPRINT_CONFIRM` and emit `start_synthesis`. A detected Up card resets the counter and continues to emit the existing `add_material_*` action.

- [ ] **Step 3: Guard transmit missing-card fallback**

When the auto-select label exists but no highlighted card is found, increment the missing-card counter and return `None` until it is confirmed. Do not emit the existing back action on the first missing observation. Reset the counter when a card or filled grid is detected.

- [ ] **Step 4: Guard list completion**

In `_advance_or_finish`, if the below-card zone is absent, require the list’s existing readiness signals to be observed consecutively before incrementing `completed_cycles`. Preserve the current normal next-card action and cycle reset behavior.

### Task 3: Run green focused and full offline verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused hero tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py -q
```

Expected: all hero-synthesis tests pass, including new transient-loading regressions.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit code 0 with no failures.

- [ ] **Step 3: Review the diff and diagnostics**

Run:

```powershell
git diff --check
git status --short
```

Confirm only the approved design/plan, test, and hero state-machine changes are present. Do not launch the emulator.

- [ ] **Step 4: Commit the implementation**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py docs/superpowers/specs/2026-08-23-hero-synthesis-readiness-guards-design.md docs/superpowers/plans/2026-08-23-hero-synthesis-readiness-guards.md
git commit -m "fix: guard hero synthesis readiness transitions"
```
