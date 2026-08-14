# Shared Dead Auto Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recognize blue/red mixed automatic-battle controls after party members die and make story, arena, and expedition use the same positive control classifier.

**Architecture:** Extend the existing pure classifier in `games/epic7/battle_controls.py` so each of four fixed auto slots may be blue (alive) or red (dead), while retaining circle geometry and the separate three-button manual classifier. Story and arena already consume it; expedition will map the same shared result instead of inferring AUTO from arbitrary frame motion. The common supervisor keeps its existing two-frame confirmation and bounded TRANSITION behavior.

**Tech Stack:** Python 3, NumPy, OpenCV, Pillow fixtures, pytest/unittest.

---

### Task 1: Record the two death-state regressions

**Files:**
- Create: `tests/fixtures/epic7_arena/battle_auto_dead_one_live_20260814.png`
- Create: `tests/fixtures/epic7_arena/battle_auto_dead_three_live_20260814.png`
- Create: `tests/test_epic7_battle_controls.py`
- Modify: `tests/test_project_layout.py`

- [ ] **Step 1: Copy the saved diagnostics into the fixture set**

Copy:

```text
runtime_diagnostics/epic7_arena/20260814_183923_752589_battle_unrecognized.png
  -> tests/fixtures/epic7_arena/battle_auto_dead_one_live_20260814.png
runtime_diagnostics/epic7_arena/20260814_184821_589185_battle_unrecognized.png
  -> tests/fixtures/epic7_arena/battle_auto_dead_three_live_20260814.png
```

- [ ] **Step 2: Write direct shared-classifier regression tests**

```python
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(group: str, name: str) -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / group / f"{name}.png"
    return np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]


class SharedBattleControlsTests(unittest.TestCase):
    def test_blue_red_mixed_auto_controls_remain_auto(self):
        for name in (
            "battle_auto_dead_one_live_20260814",
            "battle_auto_dead_three_live_20260814",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    BattleControls.AUTO_CONTROLS,
                    observe_battle_controls(load_fixture("epic7_arena", name)),
                )

    def test_skill_animation_is_not_inferred_as_auto(self):
        self.assertEqual(
            BattleControls.TRANSITION,
            observe_battle_controls(
                load_fixture("epic7_story", "skill_animation_live_20260813")
            ),
        )

    def test_existing_story_and_expedition_auto_controls_remain_auto(self):
        for group, name in (
            ("epic7_story", "battle_auto_on_live_20260809"),
            ("epic7_expedition", "battle"),
        ):
            with self.subTest(group=group, name=name):
                self.assertEqual(
                    BattleControls.AUTO_CONTROLS,
                    observe_battle_controls(load_fixture(group, name)),
                )

    def test_each_mode_manual_controls_remain_manual(self):
        for group, name in (
            ("epic7_story", "battle_auto_off_live_20260809"),
            ("epic7_arena", "battle_manual_stuck_live_20260814"),
            ("epic7_expedition", "battle_manual_waiting_live"),
        ):
            with self.subTest(group=group, name=name):
                self.assertEqual(
                    BattleControls.MANUAL_CONTROLS,
                    observe_battle_controls(load_fixture(group, name)),
                )
```

Add both fixture filenames to the exact expected arena set in `tests/test_project_layout.py`.

- [ ] **Step 3: Run the new test and verify the death samples fail**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_battle_controls.py -q
```

Expected: both death samples are `TRANSITION`; animation and existing fixtures retain their current results.

### Task 2: Extend the shared positive AUTO classifier

**Files:**
- Modify: `games/epic7/battle_controls.py`
- Test: `tests/test_epic7_battle_controls.py`
- Test: `tests/test_epic7_story.py`

- [ ] **Step 1: Replace the all-blue condition with per-slot blue-or-red evidence**

For each `_AUTO_CONTROL_CENTERS` slot compute:

```python
blue = (
    (slot[:, :, 0] >= 85)
    & (slot[:, :, 0] <= 135)
    & (slot[:, :, 1] >= 100)
    & (slot[:, :, 2] >= 70)
)
red = (
    ((slot[:, :, 0] <= 10) | (slot[:, :, 0] >= 170))
    & (slot[:, :, 1] >= 100)
    & (slot[:, :, 2] >= 45)
)
auto_bases.append(
    float(np.mean(blue)) >= 0.40 or float(np.mean(red)) >= 0.25
)
```

Require all four color bases and at least three circular controls aligned to the four fixed x positions. Expand only the auto-circle y tolerance enough to cover the recorded normal and lowered positions (`1025..1070`); keep radius limits and the manual classifier unchanged.

- [ ] **Step 2: Run the focused classifier and story suites**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_battle_controls.py auto_game_unified/tests/test_epic7_story.py -q
```

Expected: death, all-blue, obscured-auto, manual, and skill-animation cases all pass.

### Task 3: Make expedition consume the shared classifier

**Files:**
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_epic7_expedition.py`
- Test: `tests/test_battle_safety_invariants.py`

- [ ] **Step 1: Add failing expedition mapping assertions**

Extend the existing adapter test:

```python
automatic = machine.observe_battle(recorded_screen("battle"), None)
self.assertEqual(AutoBattleState.AUTO, automatic.auto_state)
self.assertTrue(automatic.battle_visible)
```

Change the random-frame test to require `AutoBattleState.UNKNOWN` while retaining `business_progress=True`; random motion must not prove AUTO.

- [ ] **Step 2: Map shared controls in `observe_battle`**

Import `BattleControls` and `observe_battle_controls`, then map:

```python
controls = observe_battle_controls(screen)
auto_state = {
    BattleControls.AUTO_CONTROLS: AutoBattleState.AUTO,
    BattleControls.MANUAL_CONTROLS: AutoBattleState.MANUAL,
    BattleControls.TRANSITION: AutoBattleState.UNKNOWN,
}[controls]
```

Keep template matching only for the safe auto click point, battle anchor, and result. Keep `meaningful_change` only as `business_progress`; do not use it to set `auto_state`. Treat shared AUTO/MANUAL controls or the existing battle anchor as battle-visible evidence.

- [ ] **Step 3: Run expedition and cross-mode safety tests**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_epic7_expedition.py auto_game_unified/tests/test_expedition_runner.py auto_game_unified/tests/test_battle_safety_invariants.py -q
```

Expected: all pass, including the static recorded expedition AUTO fixture and dynamic-random UNKNOWN case.

### Task 4: Lock the bounded animation behavior

**Files:**
- Modify: `tests/test_battle_supervisor.py`

- [ ] **Step 1: Add a supervisor sequence characterization**

```python
def test_confirmed_auto_tolerates_short_transition_and_resumes():
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    transition = BattleObservation(
        False, False, False, True, AutoBattleState.UNKNOWN
    )
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [auto, auto] + [transition] * 5 + [auto, auto, result, result],
        config_overrides={"unrecognized_seconds": 8},
    )
    assert supervisor.run(observe, cycle=13) is BattleOutcome.RESULT_REACHED
    assert clicks == []
    assert diagnostics == []
```

This is a characterization test: it should pass without changing supervisor production code. It proves that a short missing-controls animation neither clicks nor clears the confirmed auto state.

- [ ] **Step 2: Run the supervisor suite**

Run:

```powershell
python -m pytest auto_game_unified/tests/test_battle_supervisor.py -q
```

Expected: all tests pass; the existing 45-second unknown safety stop remains intact.

### Task 5: Verify, review, and integrate

**Files:**
- Review every file changed in Tasks 1-4.

- [ ] **Step 1: Run focused cross-mode tests**

```powershell
python -m pytest auto_game_unified/tests/test_epic7_battle_controls.py auto_game_unified/tests/test_epic7_story.py auto_game_unified/tests/test_epic7_arena.py auto_game_unified/tests/test_epic7_expedition.py auto_game_unified/tests/test_battle_supervisor.py auto_game_unified/tests/test_battle_safety_invariants.py -q
```

- [ ] **Step 2: Run the complete offline suite**

```powershell
python -m pytest -q
```

Expected: at least 227 tests and 29 subtests pass with zero failures.

- [ ] **Step 3: Review scope and commit**

Run `git diff --check`, inspect `git diff --stat`, confirm no emulator process was controlled, then commit the documented production files, fixtures, and tests. Keep live verification for the user.
