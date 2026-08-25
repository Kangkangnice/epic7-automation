# Hero Information Subpage Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the hero equipment subpage from completing hero-synthesis navigation, switch it to the hero information subpage, and log every entry and recovery boundary clearly.

**Architecture:** Move the existing blue-tab pixel classification into shared pure functions in `hero_synthesis.py`, reuse them in both navigation and the hero synthesis state machine, and make navigation require the information tab before accepting `hero_list`. Preserve the Runner fallback but remove its obsolete filter-template prerequisite.

**Tech Stack:** Python 3, OpenCV/NumPy, existing navigation and hero synthesis state machines, pytest/unittest, recorded runtime PNG evidence.

---

### Task 1: Add the live failure frame as regression evidence

**Files:**
- Create: `tests/fixtures/epic7_hero_synthesis/live_equipment_subpage_20260825.png`
- Modify: `tests/test_hero_synthesis.py`

- [ ] Copy the existing immutable diagnostic frame `runtime_diagnostics/epic7_hero_synthesis/20260825_215843_037557_manual_stop.png` into the hero synthesis fixture directory with the new evidence name.
- [ ] Add a failing test asserting the frame has equipment selected, hero information not selected, and `next_action()` returns `select_hero_info_tab`.
- [ ] Run the focused test and confirm it fails because the current action is `None`.
- [ ] Commit the fixture and failing regression test together after the production fix in Task 2 turns it green.

### Task 2: Share subpage classification and recover without the filter template

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] Extract reference-scaled blue-pixel helpers `hero_information_tab_selected(screen)` and `hero_equipment_tab_selected(screen)` using the existing tab zones and threshold.
- [ ] Keep `HeroSynthStateMachine._equipment_tab_selected()` and `_hero_info_tab_selected()` as thin delegates so existing tests and call sites remain stable.
- [ ] When the equipment tab is selected and `_hero_list_ready(screen)` confirms the hero-management family, return `select_hero_info_tab` without requiring `filter_button` to match.
- [ ] Set the action reason to `英雄装备标签为蓝色选中，先切回英雄信息页再开始筛选`.
- [ ] Run the live-frame test and all `tests/test_hero_synthesis.py` tests; confirm they pass.
- [ ] Commit with `fix(hero): recover from equipment subpage`.

### Task 3: Make navigation classify and leave the equipment subpage

**Files:**
- Modify: `games/epic7/navigation.py`
- Modify: `tests/test_navigation.py`

- [ ] Add a failing navigation observation test using the live frame and assert `observe()` returns `hero_equipment` before generic hero-list matching.
- [ ] Add a failing navigation transition test asserting the log order includes container entry, equipment subpage, switch action, information confirmation, and navigation completion.
- [ ] Import the shared tab functions and classify `hero_equipment` when equipment is selected and hero-management button structure is present.
- [ ] Classify `hero_list` only when the hero information tab is selected; keep the legacy grey/normal imprint evidence inside that guard.
- [ ] Update the hero-synthesis transition logs to distinguish `英雄列表容器`, `英雄装备`, and `英雄信息`.
- [ ] Run `tests/test_navigation.py` and related hero navigation tests; confirm they pass.
- [ ] Commit with `fix(navigation): require hero information subpage`.

### Task 4: Add non-silent Runner diagnostics

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] Add a failing test proving repeated no-action observations on a hero-management subpage emit a throttled log containing both tab blue-pixel counts and the current subpage classification.
- [ ] Log the first observation immediately and then at the existing waiting-log interval; do not log every capture loop.
- [ ] When opening the filter from a confirmed information page, set the reason to `英雄信息页已确认，打开三星筛选` so the existing action log explains the precondition.
- [ ] Run hero synthesis tests and confirm the new log test and existing action tests pass.
- [ ] Commit with `fix(hero): log information page readiness`.

### Task 5: Final verification and handoff

**Files:**
- Verify only.

- [ ] Run `git diff --check` and `python -m compileall -q games desktop core main.py tests`.
- [ ] Run focused tests: `python -m pytest -q tests/test_hero_synthesis.py tests/test_navigation.py tests/test_main_story.py`.
- [ ] Run the complete suite: `python -m pytest -q`.
- [ ] Confirm local `main` is clean and contains all commits.
- [ ] Restart only the desktop GUI so the user can perform the live run; do not click Start.
