# Story Battle Guide Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize the recorded story battle-guide power warning and safely click “不再显示” only after story battle entry has been committed.

**Architecture:** Add two story-local bright-foreground templates and a two-anchor finder in `story.py`. Expose the verified button through the existing `BattleObservation.allowed_action`; the shared `BattleSupervisor` keeps responsibility for two-frame stability, retry limits, diagnostics, and safe stopping.

**Tech Stack:** Python 3, OpenCV/NumPy template matching, Pillow fixtures, pytest, existing battle supervisor.

---

### Task 1: Freeze the live evidence and add two-anchor recognition

**Files:**
- Create: `tests/fixtures/epic7_story/battle_guide_warning_live_20260815.png`
- Create: `games/epic7/templates/story/battle_guide_title.png`
- Create: `games/epic7/templates/story/battle_guide_dont_show.png`
- Modify: `games/epic7/story.py`
- Modify: `tests/test_epic7_story.py`

- [ ] Copy `runtime_diagnostics/epic7_story/20260815_125141_336906_manual_stop.png` byte-for-byte into the fixture path. Crop the title from reference rectangle `(850, 305, 230, 80)` and “不再显示” from `(1160, 815, 220, 80)` into the two template files; preserve the reference resolution `1982×1132` in matcher configuration.
- [ ] Add a failing test that calls a new `find_battle_guide_dont_show()` with the real fixture and loaded templates. Assert a match near `(1270, 855)`, then zero the title region and button region separately and assert both variants return `None`. Assert `team`, `battle_auto_on_live_20260809`, and `results` are negative fixtures.
- [ ] Run `python -m pytest auto_game_unified\tests\test_epic7_story.py -q` from `D:\AI\codex\auto_game` and confirm RED because the finder and template fields do not exist.
- [ ] Add `battle_guide_title` and `battle_guide_dont_show` to `StoryTemplates` and `build_story_templates()`. Implement `find_battle_guide_dont_show()` with fixed search regions `(780, 250, 420, 180)` and `(1080, 760, 420, 190)`, HSV bright-foreground mask `S≤100, V≥150`, threshold `0.85`, and return the button match only when both anchors exist.
- [ ] Re-run the focused story suite and confirm GREEN.
- [ ] Commit with `git commit -m "feat: recognize story battle guide warning"`.

### Task 2: Hand the verified action to the shared battle supervisor

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `tests/test_epic7_story.py`

- [ ] Add a failing observation test using `battle_guide_warning_live_20260815`. Assert `allowed_action == ("dismiss-battle-guide-warning", point)`, `battle_visible is False`, and `result_visible is False`.
- [ ] Run the single test and confirm RED because `observe_battle()` does not yet consult the new finder.
- [ ] In `StoryStateMachine.observe_battle()`, check the two-anchor warning before the existing `skip_confirm`, `skip`, and `watch_story` actions. Set only `allowed_action`; do not mark battle entry or mutate story state.
- [ ] Run `tests/test_epic7_story.py` and `tests/test_battle_supervisor.py`. Confirm the new observation passes and the existing generic tests still prove two stable frames, one retry, and `allowed_action_<name>_failed` diagnostics.
- [ ] Commit with `git commit -m "fix: dismiss story battle guide warning"`.

### Task 3: Full offline verification

**Files:**
- Verify only; do not start or control the simulator.

- [ ] Run `python -m pytest auto_game_unified\tests -q` from `D:\AI\codex\auto_game`; expect zero failures.
- [ ] Run `python -m compileall -q auto_game_unified`; expect exit code `0`.
- [ ] Run `git diff --check`, inspect `git diff --stat origin/main...HEAD`, and verify the worktree is clean with only the approved fixture, two templates, story code, tests, design, and plan.
