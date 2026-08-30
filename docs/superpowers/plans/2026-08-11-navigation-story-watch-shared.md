# Navigation Story Watch Shared Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lobby-to-story navigation recognize Episode 4 story-only pages using the exact same rule as the story state machine.

**Architecture:** Extract the existing white-glyph detector into `find_watch_story_button(screen, template)` in the Epic7 story module. Both `StoryStateMachine` and `Epic7Navigator` call it, so mask parameters, region, threshold, score, and click center cannot drift independently.

**Tech Stack:** Python 3, OpenCV, NumPy, unittest/pytest

---

### Task 1: Add the latest navigation failure as regression evidence

**Files:**
- Create: `tests/fixtures/epic7_navigation/story_watch_ep4.png`
- Modify: `tests/test_navigation.py`

- [ ] Copy `runtime_diagnostics/epic7_story/20260811_102147_051974_navigation_lobby_to_story_ready_failed.png` byte-for-byte to the navigation fixture.
- [ ] Add a test expecting `navigator.observe(story_watch_ep4).name == "story_ready"`.
- [ ] Add a transition test with a lobby source and two stable Episode 4 destination frames; expect `navigate("story")` to return after exactly one lobby click.
- [ ] Run `python -m pytest tests/test_navigation.py -q`; expect both new tests to fail because the navigator still reports `unknown`.

### Task 2: Extract and share the white-glyph detector

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/navigation.py`
- Modify: `tests/test_navigation.py`

- [ ] Move the current watch-story HSV masking body into module function `find_watch_story_button(screen, template)` using region `(1450,930,470,202)`, reference size `(1982,1132)`, saturation `0..90`, value `150..255`, and threshold `0.72`.
- [ ] Make `StoryStateMachine._locate("watch_story")` delegate directly to the shared function.
- [ ] Make `Epic7Navigator.observe()` call the shared function for `story_watch` instead of `_locate(..., 0.80)`.
- [ ] Assert the latest screenshot produces the same score through the shared helper and navigator observation.
- [ ] Run `python -m pytest tests/test_navigation.py tests/test_epic7_story.py -q` and require zero failures.

### Task 3: Offline-only final verification

**Files:**
- No production changes unless a regression is directly caused by Tasks 1–2.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q .` and require exit code `0`.
- [ ] Report the live test command without launching or controlling the emulator.
