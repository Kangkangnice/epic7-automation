# Shared Epic7 Battle Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make story and arena share reliable lower-right battle-control recognition and retry a swallowed auto-battle click once before stopping safely.

**Architecture:** Extract the existing story control classifier into a pure Epic7 module, preserve StoryStateMachine's public wrapper, and make ArenaStateMachine map the shared result to `AutoBattleState`. Tighten BattleSupervisor so only stable AUTO observations confirm automation and stable MANUAL observations drive at most two clicks.

**Tech Stack:** Python 3, NumPy, OpenCV, unittest/pytest-compatible tests.

---

### Task 1: Record the arena regression

**Files:**
- Create: `tests/fixtures/epic7_arena/battle_manual_stuck_live_20260814.png`
- Modify: `tests/test_epic7_arena.py`
- Modify: `tests/test_project_layout.py`

- [ ] **Step 1: Copy the latest runtime diagnostic into fixtures**

Copy `runtime_diagnostics/epic7_arena/20260814_083013_268405_battle_absolute_timeout.png` as `battle_manual_stuck_live_20260814.png`.

- [ ] **Step 2: Write the failing adapter test**

```python
def test_live_manual_battle_uses_shared_controls_when_top_template_misses(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES))
    observation = machine.observe_battle(
        load_fixture("battle_manual_stuck_live_20260814"), None
    )
    self.assertEqual(AutoBattleState.MANUAL, observation.auto_state)
    self.assertIsNotNone(observation.auto_point)
```

- [ ] **Step 3: Verify the regression test fails**

Run: `python -m pytest auto_game_unified/tests/test_epic7_arena.py -q`

Expected: the live sample is `UNKNOWN` because the old top-icon template misses.

### Task 2: Extract and integrate the shared classifier

**Files:**
- Create: `games/epic7/battle_controls.py`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/arena.py`
- Test: `tests/test_epic7_story.py`
- Test: `tests/test_epic7_arena.py`

- [ ] **Step 1: Move the enum and classifier into a pure module**

Expose:

```python
class BattleControls(Enum):
    AUTO_CONTROLS = "auto_controls"
    MANUAL_CONTROLS = "manual_controls"
    TRANSITION = "transition"

def observe_battle_controls(screen: np.ndarray) -> BattleControls:
    ...
```

Keep the existing four-auto-control and three-manual-control geometry. Require all three manual circles to align and each manual border brightness ratio to be at least `0.35`, which covers the recorded arena ratios while rejecting the recorded skill-animation frame that has no aligned circles.

- [ ] **Step 2: Preserve the story wrapper and import compatibility**

`StoryStateMachine.observe_battle_controls(screen)` delegates to the shared function, and `BattleControls` remains imported in `story.py` so existing callers and tests keep working.

- [ ] **Step 3: Map arena state from the shared result**

Use the shared classification for `auto_state`. If manual, use the matched top button point when available, otherwise the existing scaled `(1690, 96)` point. Do not infer AUTO from frame motion.

- [ ] **Step 4: Run focused state-machine tests**

Run: `python -m pytest auto_game_unified/tests/test_epic7_story.py auto_game_unified/tests/test_epic7_arena.py -q`

Expected: all tests pass, including the live manual arena regression.

### Task 3: Retry auto activation and require visual confirmation

**Files:**
- Modify: `core/battle_supervisor.py`
- Modify: `tests/test_battle_supervisor.py`

- [ ] **Step 1: Add failing supervisor tests**

Add one sequence where MANUAL persists long enough to cause two clicks and then becomes AUTO, one where MANUAL remains after two clicks and yields `auto_not_confirmed`, and one where `business_progress=True` with UNKNOWN never logs `auto-confirmed`.

- [ ] **Step 2: Replace the one-shot boolean with bounded click tracking**

Track `auto_clicks` and `auto_clicked_at`. A stable manual state clicks at attempt 1, retries attempt 2 after `allowed_action_retry_seconds`, and fails after `allowed_action_failure_seconds` following attempt 2. Log `auto-attempt=1/2` and `auto-attempt=2/2` separately from the runtime's actual click event.

- [ ] **Step 3: Remove motion-based auto confirmation**

Only stable `AutoBattleState.AUTO` clears the confirmation wait and logs `status=auto-confirmed`. `business_progress` continues to update the business watchdog but cannot confirm AUTO.

- [ ] **Step 4: Run focused supervisor tests**

Run: `python -m pytest auto_game_unified/tests/test_battle_supervisor.py -q`

Expected: all supervisor tests pass and the persisted-manual case clicks exactly twice.

### Task 4: Verify and integrate

**Files:**
- Review all files changed above.

- [ ] **Step 1: Run focused battle suites**

Run: `python -m pytest auto_game_unified/tests/test_battle_supervisor.py auto_game_unified/tests/test_epic7_story.py auto_game_unified/tests/test_epic7_arena.py -q`

- [ ] **Step 2: Run the complete offline suite**

Run: `python -m unittest discover -s auto_game_unified/tests -v`

Expected: all 185 or more tests pass with zero failures.

- [ ] **Step 3: Inspect scope and commit**

Run `git diff --check`, inspect `git diff --stat`, commit only the documented files, merge the branch into local `main`, and rerun the focused tests on `main`.
