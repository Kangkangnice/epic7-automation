# Hero Synthesis Visual Transition Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make simulator hero synthesis advance only after explicit visual entry, departure, and success evidence, including identical-copy hero switching, safe SSS classification, and exactly-once transmit completion.

**Architecture:** Keep the existing `HeroSynthStateMachine` as the page/action decision owner and add one small pure OpenCV module for high-frequency list-motion evidence. Extend the existing action contract only where same-page changes need dedicated evidence, and represent transmission as an explicit transaction phase that is cleared only after reward confirmation and return to the hero list.

**Tech Stack:** Python 3.11, OpenCV, NumPy, `unittest`/pytest, existing `ModeRunnerBase` and screenshot fixtures.

---

## File map

- Create `games/epic7/hero_transition.py`: pure list-motion detector and safety classification enums; no runtime clicking or state-machine decisions.
- Modify `games/epic7/runner_base.py`: add a no-op post-click hook so the hero runner can sample the short animation without changing other modes.
- Modify `games/epic7/hero_synthesis.py`: integrate motion evidence, frame-scoped page evidence, tri-state classification, material-change contracts, and transmit transaction phases.
- Create `games/epic7/templates/hero/transmit_reward_title.png`: tight crop of the simulator “获得奖励” heading.
- Create `games/epic7/templates/hero/transmit_reward_close.png`: tight crop of the simulator reward close hint and chevron.
- Modify `tests/test_hero_synthesis.py`: add red/green tests for every new contract and update assertions that intentionally depended on sticky page evidence.
- Modify `docs/ARCHITECTURE.md`: record that simulator hero switching uses temporal motion and that transmission is reward-confirmed exactly once.

The PC branch must remain behaviorally unchanged. No production code may import anything from `tests/`.

### Task 1: Add a pure right-list motion observer

**Files:**
- Create: `games/epic7/hero_transition.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing tests for coherent vertical motion and settling**

Add these imports and tests to `tests/test_hero_synthesis.py`:

```python
from auto_game_unified.games.epic7.hero_transition import (
    CardSwitchMotionObserver,
    MotionPhase,
)


class CardSwitchMotionObserverTests(unittest.TestCase):
    def test_vertical_list_motion_then_settling_confirms_switch(self):
        base = fixture("list_reddot")
        observer = CardSwitchMotionObserver(base)
        moving_1 = np.roll(base, -8, axis=0)
        moving_2 = np.roll(base, -16, axis=0)

        self.assertFalse(observer.update(moving_1))
        self.assertFalse(observer.update(moving_2))
        self.assertFalse(observer.update(moving_2.copy()))
        self.assertFalse(observer.update(moving_2.copy()))
        self.assertTrue(observer.update(moving_2.copy()))
        self.assertIs(observer.phase, MotionPhase.SETTLED)

    def test_static_identical_copy_never_confirms_switch(self):
        base = fixture("list_reddot")
        observer = CardSwitchMotionObserver(base)

        for _ in range(6):
            self.assertFalse(observer.update(base.copy()))

        self.assertIs(observer.phase, MotionPhase.WAITING_DEPARTURE)

    def test_central_portrait_animation_is_outside_motion_roi(self):
        base = fixture("list_reddot")
        animated = base.copy()
        animated[250:900, 650:1350] = np.roll(
            animated[250:900, 650:1350], 20, axis=0
        )
        observer = CardSwitchMotionObserver(base)

        for _ in range(6):
            self.assertFalse(observer.update(animated))

        self.assertIs(observer.phase, MotionPhase.WAITING_DEPARTURE)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::CardSwitchMotionObserverTests -q
```

Expected: collection fails because `auto_game_unified.games.epic7.hero_transition` does not exist.

- [ ] **Step 3: Implement the minimal pure observer**

Create `games/epic7/hero_transition.py` with this public shape:

```python
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np


class MotionPhase(Enum):
    WAITING_DEPARTURE = "waiting_departure"
    MOVING = "moving"
    SETTLING = "settling"
    SETTLED = "settled"


class SafetyClass(Enum):
    SSS = "sss"
    NON_SSS = "non_sss"
    UNKNOWN = "unknown"


@dataclass
class CardSwitchMotionObserver:
    first_screen: np.ndarray
    min_vertical_shift: float = 1.5
    min_phase_response: float = 0.08
    min_accumulated_shift: float = 8.0
    settle_difference: float = 2.5
    required_settle_frames: int = 3

    _LIST_ZONE = (1450, 200, 532, 780)
    _REFERENCE_SIZE = (1982, 1132)

    def __post_init__(self) -> None:
        self.phase = MotionPhase.WAITING_DEPARTURE
        self.accumulated_shift = 0.0
        self.settle_frames = 0
        self.previous = self._gray(self.first_screen)

    def _gray(self, screen: np.ndarray) -> np.ndarray:
        x, y, w, h = self._LIST_ZONE
        scale_x = screen.shape[1] / self._REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / self._REFERENCE_SIZE[1]
        x, y, w, h = (
            round(x * scale_x), round(y * scale_y),
            round(w * scale_x), round(h * scale_y),
        )
        crop = screen[y : y + h, x : x + w]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def update(self, screen: np.ndarray) -> bool:
        current = self._gray(screen)
        (dx, dy), response = cv2.phaseCorrelate(
            self.previous.astype(np.float32), current.astype(np.float32)
        )
        difference = float(cv2.absdiff(self.previous, current).mean())
        vertical = (
            response >= self.min_phase_response
            and abs(dy) >= self.min_vertical_shift
            and abs(dy) > abs(dx) * 1.5
        )

        if vertical:
            self.phase = MotionPhase.MOVING
            self.accumulated_shift += abs(dy)
            self.settle_frames = 0
        elif self.phase in (MotionPhase.MOVING, MotionPhase.SETTLING):
            self.phase = MotionPhase.SETTLING
            self.settle_frames = (
                self.settle_frames + 1
                if difference <= self.settle_difference
                else 0
            )
            if (
                self.accumulated_shift >= self.min_accumulated_shift
                and self.settle_frames >= self.required_settle_frames
            ):
                self.phase = MotionPhase.SETTLED
                self.previous = current
                return True

        self.previous = current
        return False
```

Do not add a sign check to `dy`: the production requirement is coherent vertical movement, and the click target already constrains the requested direction.

- [ ] **Step 4: Run the observer tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::CardSwitchMotionObserverTests -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the pure observer**

```powershell
git add games/epic7/hero_transition.py tests/test_hero_synthesis.py
git commit -m "feat: detect simulator hero list motion"
```

### Task 2: Sample the switch animation immediately after clicking

**Files:**
- Modify: `games/epic7/runner_base.py:70-80,538-543`
- Modify: `games/epic7/hero_synthesis.py:1433-1571`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing Runner tests for identical-copy motion**

Add tests that drive the real post-click hook without a live device:

```python
def shifted_list(screen, pixels):
    shifted = screen.copy()
    x, y, w, h = HeroSynthStateMachine._LIST_FP_ZONE
    shifted[y : y + h, x : x + w] = np.roll(
        screen[y : y + h, x : x + w], pixels, axis=0
    )
    return shifted


class CardSwitchRunnerTests(unittest.TestCase):
    def test_identical_final_card_completes_after_motion_sequence(self):
        base = fixture("list_reddot")
        frames = iter(
            [shifted_list(base, -8), shifted_list(base, -16)]
            + [shifted_list(base, -16)] * 3
        )
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: next(frames), lambda *_: None),
            sleep=lambda _: None,
        )
        action = HeroAction(
            "next_card_same",
            (1800, 591),
            source_page="英雄列表",
            target_pages=("英雄列表",),
            source_observation="same-copy",
            transition_kind="card_change",
        )
        runner.machine._last_screen = base

        runner._after_action_click(action)

        self.assertTrue(runner._card_transition_completed(action, action))

    def test_no_motion_does_not_complete_even_if_static_fingerprint_changes(self):
        base = fixture("list_reddot")
        frames = iter([base.copy()] * 36)
        runner = HeroSynthRunner(
            machine(verify_filter=True),
            Runtime(lambda: next(frames), lambda *_: None),
            sleep=lambda _: None,
        )
        previous = HeroAction(
            "next_card_old", (0, 0), source_observation="old",
            transition_kind="card_change",
        )
        current = HeroAction("next_card_new", (0, 0), source_observation="new")
        runner.machine._last_screen = base

        runner._after_action_click(previous)

        self.assertFalse(runner._card_transition_completed(previous, current))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::CardSwitchRunnerTests -q
```

Expected: FAIL because `_after_action_click` and motion-gated completion do not exist.

- [ ] **Step 3: Add the no-op base hook**

Add to `ModeRunnerBase`:

```python
def _after_action_click(self, action: Any) -> None:
    """Optional short observation immediately after an action click."""
```

Immediately after `self.runtime.click(action.point, action.name)` call:

```python
self._after_action_click(action)
```

The default method has no body beyond the docstring, so all other runners keep their current timing and behavior.

- [ ] **Step 4: Integrate the 12 FPS, 3-second hero observer**

Import `CardSwitchMotionObserver` in `hero_synthesis.py`. Initialize:

```python
self._card_switch_motion_confirmed = False
```

Override the hook in `HeroSynthRunner`:

```python
def _after_action_click(self, action: HeroAction) -> None:
    if (
        self.machine.templates.pc_client
        or action.transition_kind != "card_change"
        or self.machine._last_screen is None
    ):
        return
    observer = CardSwitchMotionObserver(self.machine._last_screen)
    self._card_switch_motion_confirmed = False
    for _ in range(36):
        self.sleep(1 / 12)
        if observer.update(self.runtime.capture()):
            self._card_switch_motion_confirmed = True
            self.runtime.log(
                "模式=英雄合成 切换阶段=MOVING->SETTLED 结果=已确认"
            )
            return
    self.runtime.log("模式=英雄合成 切换阶段=WAITING_DEPARTURE 结果=未确认")
```

Change `_card_transition_completed` to return the captured motion result, not static fingerprint inequality. Consume the result after success so it cannot leak into the next click:

```python
completed = self._card_switch_motion_confirmed
if completed:
    self._card_switch_motion_confirmed = False
return completed
```

Change the success detail to allow `same -> same`, and change the retry reason to “未观察到右侧列表移动并重新稳定”. Set `_NEXT_CARD_RETRY_SECONDS = 1`; the 3-second observer already provides the post-click wait.

- [ ] **Step 5: Run focused and neighboring Runner tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::CardSwitchRunnerTests tests/test_hero_synthesis.py::HeroListTransitionTests tests/test_hero_synthesis.py::RunnerFlowTests -q
```

Expected: all selected tests pass. Update the existing retry-window assertion from `10` to `1`; do not weaken unrelated assertions.

- [ ] **Step 6: Verify other mode runners were not changed**

Run:

```powershell
python -m pytest tests/test_story_runner.py tests/test_fodder_runner.py tests/test_arena_runner.py tests/test_expedition_runner.py tests/test_assist_auto.py -q
```

Expected: all tests pass with no new post-click delay.

- [ ] **Step 7: Commit motion integration**

```powershell
git add games/epic7/runner_base.py games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify identical hero card switches by motion"
```

### Task 3: Replace absence-based SSS decisions with three-state safety classification

**Files:**
- Modify: `games/epic7/hero_synthesis.py:188-255,432-616,1264-1389`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing classifier tests**

Import `SafetyClass` and add:

```python
class HeroSafetyClassificationTests(unittest.TestCase):
    def test_current_sss_is_positive_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_grey_3s")
            ),
            SafetyClass.SSS,
        )

    def test_blue_imprint_button_is_positive_non_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_reddot")
            ),
            SafetyClass.NON_SSS,
        )

    def test_no_reddot_blue_button_is_positive_non_sss(self):
        self.assertIs(
            machine(verify_filter=True)._classify_current_hero(
                fixture("list_no_reddot")
            ),
            SafetyClass.NON_SSS,
        )

    def test_ambiguous_grey_without_sss_is_unknown(self):
        m = machine(verify_filter=True)
        screen = fixture("list_grey_3s").copy()
        x, y, w, h = m._RATING_REGION
        screen[y : y + h, x : x + w] = 0

        self.assertIs(m._classify_current_hero(screen), SafetyClass.UNKNOWN)

    def test_material_score_margin_has_unknown_band(self):
        m = machine()
        row = m._up_badge_rows(fixture("imprint_up_cards_no_sss"))[0]
        with patch.object(m, "_material_sss_score", return_value=0.70):
            self.assertIs(
                m._classify_material_row(fixture("imprint_up_cards_no_sss"), row),
                SafetyClass.UNKNOWN,
            )

    def test_transmit_target_score_margin_has_unknown_band(self):
        m = machine()
        card = m._transmit_target_card(fixture("transmit_select"))
        with patch.object(m, "_material_sss_score", return_value=0.70):
            self.assertIs(
                m._classify_transmit_target(fixture("transmit_select"), card),
                SafetyClass.UNKNOWN,
            )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroSafetyClassificationTests -q
```

Expected: FAIL because the classifier methods do not exist.

- [ ] **Step 3: Implement current-hero three-state classification**

Use the existing positive SSS template and positive blue-button saturation:

```python
_NON_SSS_BUTTON_SATURATION_MIN = 90.0

def _classify_current_hero(self, screen: np.ndarray) -> SafetyClass:
    if self.templates.assume_non_max_rating:
        return SafetyClass.NON_SSS
    if self._is_max_rating(screen):
        return SafetyClass.SSS
    if imprint_button_saturation(screen) >= self._NON_SSS_BUTTON_SATURATION_MIN:
        return SafetyClass.NON_SSS
    return SafetyClass.UNKNOWN
```

Update both hero-list decision branches to switch on this result. `UNKNOWN` returns `None`; it must never fall through to red-dot or next-card actions.

- [ ] **Step 4: Implement a score margin for each material row**

Use `find_template` with threshold `-1.0` on the tight row region to expose the best SSS score. Add the exact helper and classify with two thresholds:

```python
_SSS_MATERIAL_MIN = 0.80
_SSS_MATERIAL_CLEAR_MAX = 0.55

def _material_sss_score(self, screen, row) -> float:
    start, end = row
    region = (
        self._MATERIAL_SSS_REGION[0],
        max(self._MATERIAL_SSS_REGION[1], start - 45),
        self._MATERIAL_SSS_REGION[2],
        min(self._MATERIAL_SSS_REGION[3], end - start + 90),
    )
    match = find_template(
        screen,
        self.templates.sss_material,
        -1.0,
        region=region,
        reference_size=self._REFERENCE_SIZE,
    )
    return match.score if match is not None else -1.0

def _classify_material_row(self, screen, row) -> SafetyClass:
    score = self._material_sss_score(screen, row)
    if score >= self._SSS_MATERIAL_MIN:
        return SafetyClass.SSS
    if score <= self._SSS_MATERIAL_CLEAR_MAX:
        return SafetyClass.NON_SSS
    return SafetyClass.UNKNOWN
```

`_find_up_card` may return only rows classified `NON_SSS`. If any Up row is `UNKNOWN`, the state machine waits and may not start synthesis or enter transmission. A row classified `SSS` is never clicked.

Reuse the same `0.80 / 0.55` score margin in `_classify_transmit_target`, but pass the highlighted transmit row region instead of an Up row region. The transmit selection branch may proceed only for `NON_SSS`; `SSS` safely exits and `UNKNOWN` waits without clicking.

- [ ] **Step 5: Run classifier and existing SSS tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroSafetyClassificationTests tests/test_hero_synthesis.py::HeroListDecisionTests tests/test_hero_synthesis.py::ImprintDecisionTests tests/test_hero_synthesis.py::TransmitDecisionTests -q
```

Expected: all selected tests pass. Existing SSS fixtures remain `SSS`; existing ordinary material fixtures remain `NON_SSS`.

- [ ] **Step 6: Commit safety classification**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: classify hero synthesis targets safely"
```

### Task 4: Make current-frame and same-page material evidence explicit

**Files:**
- Modify: `games/epic7/hero_synthesis.py:286-309,971-1192,1392-1430,1537-1571`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing tests for stale page evidence and material progress**

Add:

```python
class FrameScopedEvidenceTests(unittest.TestCase):
    def test_unknown_frame_clears_simulator_confirmed_page(self):
        m = machine(verify_filter=True)
        m._confirmed_page = "刻印加材料"
        unknown = np.full_like(fixture("imprint_added"), 30)

        self.assertIsNone(m.next_action(unknown))
        self.assertEqual("", m._confirmed_page)

    def test_material_action_requires_slot_or_row_change(self):
        runner = HeroSynthRunner(
            machine(), Runtime(lambda: None, lambda *_: None), sleep=lambda _: None
        )
        previous = HeroAction(
            "add_material_0_2", (0, 0), source_observation="slots=0;rows=450,600",
            transition_kind="material_change",
        )
        unchanged = HeroAction(
            "add_material_0_2", (0, 0), source_observation="slots=0;rows=450,600",
        )
        changed = HeroAction(
            "add_material_1_1", (0, 0), source_observation="slots=1;rows=600",
        )

        self.assertFalse(runner._material_transition_completed(previous, unchanged))
        self.assertTrue(runner._material_transition_completed(previous, changed))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FrameScopedEvidenceTests -q
```

Expected: FAIL because page evidence is sticky and material-change completion does not exist.

- [ ] **Step 3: Clear simulator page evidence at the start of each committed observation**

At the beginning of `next_action`:

```python
self._last_screen = screen
if not self.templates.pc_client:
    self._confirmed_page = ""
```

Keep `preview()` snapshot/restore behavior. Update the old partial-page test to expect an empty current-frame label rather than the previous label.

- [ ] **Step 4: Publish and verify material observations**

Format material observations in one helper:

```python
def _material_observation(self, filled_slots, rows):
    centers = ",".join(str((start + end) // 2) for start, end in rows)
    return f"slots={filled_slots};rows={centers}"
```

Set `source_observation` and `transition_kind="material_change"` on `add_material_*` actions. In `HeroSynthRunner`, parse both observations and return success only when filled slots increase or the exact target row disappears. Route `material_change` through `_transition_completed` before the generic page contract.

- [ ] **Step 5: Run material, transition, and flow tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FrameScopedEvidenceTests tests/test_hero_synthesis.py::ImprintDecisionTests tests/test_hero_synthesis.py::RunnerFlowTests -q
```

Expected: all selected tests pass and same-page partial frames no longer complete a material click.

- [ ] **Step 6: Commit frame-scoped evidence**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify hero material placement progress"
```

### Task 5: Represent transmission as an explicit, persistent transaction

**Files:**
- Modify: `games/epic7/hero_synthesis.py:27-58,257-291,1025-1075,1125-1137,1268-1284`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing transaction-state tests**

Add:

```python
class TransmitTransactionTests(unittest.TestCase):
    def test_target_persists_until_reward_is_confirmed(self):
        m = machine(verify_filter=True)
        m._active_card_observation = "card-copy-7"
        m.state = HeroSynthState.IMPRINT_ADD

        m.next_action(sss_only_material_page())
        self.assertIs(m.transmit_phase, TransmitPhase.PENDING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

        m.next_action(fixture("list_reddot"))
        m.next_action(fixture("transmit_select"))
        self.assertIsNot(m.transmit_phase, TransmitPhase.NONE)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_entering_transmit_page_does_not_mark_target_transmitted(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.OPENING
        m.transmit_target_observation = "card-copy-7"

        m.next_action(fixture("transmit_select"))

        self.assertIs(m.transmit_phase, TransmitPhase.SELECTING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_recovery_does_not_clear_unfinished_transmit_target(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING
        m.transmit_target_observation = "card-copy-7"
        runner = HeroSynthRunner(m, Runtime(lambda: None, lambda *_: None))

        runner._apply_recovery_state()

        self.assertIs(m.transmit_phase, TransmitPhase.CONFIRMING)
        self.assertEqual("card-copy-7", m.transmit_target_observation)

    def test_saved_target_must_still_be_selected_before_opening_transmit(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.PENDING
        m.transmit_target_observation = "different-card"

        self.assertIsNone(m.next_action(fixture("list_reddot")))
        self.assertIs(m.transmit_phase, TransmitPhase.PENDING)

    def test_auto_select_label_alone_is_not_complete_transmit_page(self):
        m = machine(verify_filter=True)
        incomplete = fixture("transmit_select").copy()
        x, y, w, h = m._TRANSMIT_GRID_ZONE
        incomplete[y : y + h, x : x + w] = 0

        self.assertFalse(m._transmit_page_ready(incomplete))


def test_sss_material_transmit_returns_once_and_continues_cycle(self):
    sequence = (
        [fixture("list_reddot")] * 2
        + [fixture("filter_open")] * 2
        + [fixture("list_reddot")] * 2
        + [sss_only_material_page()] * 2
        + [fixture("list_reddot")] * 2
        + [fixture("transmit_select")] * 2
        + [fixture("transmit_confirm")] * 2
        + [fixture("reward_popup")] * 2
        + [fixture("transmit_select")] * 2
        + [fixture("list_end_of_cards")] * 4
    )
    screens = iter(sequence)
    clicks = []
    logs = []
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: next(screens), clicks.append, emit=logs.append),
        sleep=lambda _: None,
    )

    completed = runner.run(max_cycles=1)

    names = [
        line.split("动作=")[1].split()[0]
        for line in logs
        if "执行点击" in line and "动作=" in line
    ]
    self.assertEqual(1, completed)
    self.assertEqual(1, names.count("confirm_transmit"))
    self.assertEqual(1, names.count("close_reward"))
    self.assertIn("back_to_list", names)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TransmitTransactionTests tests/test_hero_synthesis.py::test_sss_material_transmit_returns_once_and_continues_cycle -q
```

Expected: FAIL because `TransmitPhase` and persistent target identity do not exist; the full flow also repeats or clears transmission too early.

- [ ] **Step 3: Add transaction phases and compatibility property**

Add:

```python
class TransmitPhase(Enum):
    NONE = "none"
    PENDING = "pending"
    OPENING = "opening"
    SELECTING = "selecting"
    CONFIRMING = "confirming"
    TRANSMITTED = "transmitted"
    RETURNING = "returning"
```

Initialize `transmit_phase`, `transmit_target_observation`, and `_active_card_observation`. Keep existing tests and callers readable with:

```python
@property
def pending_transmit_target(self) -> bool:
    return self.transmit_phase is not TransmitPhase.NONE

@pending_transmit_target.setter
def pending_transmit_target(self, value: bool) -> None:
    if value and self.transmit_phase is TransmitPhase.NONE:
        self.transmit_phase = TransmitPhase.PENDING
    elif not value:
        self.transmit_phase = TransmitPhase.NONE
        self.transmit_target_observation = None
```

Whenever a stable hero-list decision is made, assign `_active_card_observation = _detail_fingerprint(screen)`. When an SSS-only material page starts the transaction, copy `_active_card_observation` to `transmit_target_observation`; if it is missing, raise `UnrecognizedScreen` instead of opening transmission.

- [ ] **Step 4: Advance phases only from observed target pages**

Apply these exact transitions:

```text
SSS-only material page observed  -> PENDING (save _active_card_observation)
stable hero list whose observation equals the saved target -> OPENING
complete transmit page observed  -> SELECTING
confirm popup observed           -> CONFIRMING
strong reward layer observed     -> TRANSMITTED
reward close action emitted      -> RETURNING
stable hero list observed        -> NONE (clear target)
```

Do not clear the transaction upon seeing `auto_select_label`. In `_apply_recovery_state`, leave non-`NONE` phases and target identity unchanged; if navigation cannot restore the target, later state logic must stop rather than transmit a substitute.

Add `_transmit_page_ready(screen)` and require all four simulator anchors before moving to `SELECTING`: `auto_select_label`, a highlighted target row, the grid structure, and the green-button region. A filled grid is not required at entry; it becomes the success evidence for `select_transmit_card_*`.

- [ ] **Step 5: Add missing source/target contracts**

Use `_simulator_transition_action` for:

```python
"abort_imprint_to_transmit": ("刻印SSS材料", ("英雄列表",))
"select_transmit_card_*": ("传送选择", ("传送选择",))
"start_transmit": ("传送选择", ("传送确认",))
"confirm_transmit": ("传送确认", ("传送奖励",))
"close_reward": ("传送奖励", ("传送选择",))
"back_to_list": ("传送选择", ("英雄列表",))
"abort_transmit_sss_target": ("传送选择", ("英雄列表",))
```

Set `transition_kind="transmit_selection"` on the same-page selection action and complete it only when `_transmit_grid_filled` changes from false to true. The abort-imprint action must be reissued while its SSS source page remains, rather than returning `None` until timeout.

- [ ] **Step 6: Run transaction and existing transmit tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TransmitTransactionTests tests/test_hero_synthesis.py::test_sss_material_transmit_returns_once_and_continues_cycle tests/test_hero_synthesis.py::TransmitDecisionTests tests/test_hero_synthesis.py::ImprintDecisionTests -q
```

Expected: all selected tests pass; no target is cleared before reward confirmation.

- [ ] **Step 7: Commit persistent transmission state**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: preserve hero transmit transaction state"
```

### Task 6: Require strong reward evidence and exactly-once return

**Files:**
- Create: `games/epic7/templates/hero/transmit_reward_title.png`
- Create: `games/epic7/templates/hero/transmit_reward_close.png`
- Modify: `games/epic7/hero_synthesis.py:96-163,207-218,691-695,1019-1047`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing reward-evidence tests**

Add:

```python
class TransmitRewardEvidenceTests(unittest.TestCase):
    def test_full_reward_popup_marks_transmitted(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING

        action = m.next_action(fixture("reward_popup"))

        self.assertEqual("close_reward", action.name)
        self.assertIs(m.transmit_phase, TransmitPhase.RETURNING)
        self.assertTrue(m._transmit_reward_confirmed)

    def test_bright_strip_without_title_items_and_close_hint_is_not_reward(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.CONFIRMING
        weak = np.zeros_like(fixture("reward_popup"))
        x, y, w, h = m._REWARD_STRIP_ZONE
        weak[y : y + h, x : x + w] = 180

        self.assertIsNone(m.next_action(weak))
        self.assertFalse(m._transmit_reward_confirmed)

    def test_returning_phase_never_selects_or_transmits_again(self):
        m = machine(verify_filter=True)
        m.transmit_phase = TransmitPhase.RETURNING
        m._transmit_reward_confirmed = True

        action = m.next_action(fixture("transmit_select"))

        self.assertEqual("back_to_list", action.name)
        self.assertNotIn("transmit", action.name)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TransmitRewardEvidenceTests -q
```

Expected: FAIL because the old reward detector accepts only a brightness strip and no confirmation flag exists.

- [ ] **Step 3: Create tight reward templates from the recorded simulator fixture**

Run this one-off crop command; it copies pixels without resampling:

```powershell
python -c "import cv2; from pathlib import Path; src=cv2.imread('tests/fixtures/epic7_hero/reward_popup.png'); out=Path('games/epic7/templates/hero'); cv2.imwrite(str(out/'transmit_reward_title.png'), src[260:350,850:1150]); cv2.imwrite(str(out/'transmit_reward_close.png'), src[790:930,840:1140])"
```

Expected: both PNG files exist; their shapes are `(90, 300)` and `(140, 300)`.

- [ ] **Step 4: Load templates and implement three independent reward checks**

Add optional `transmit_reward_title` and `transmit_reward_close` fields to `HeroTemplates`, load both files for the simulator, and add regions:

```python
_REWARD_TITLE_REGION = (760, 220, 460, 170)
_REWARD_CLOSE_REGION = (760, 740, 460, 230)

def _transmit_reward_present(self, screen: np.ndarray) -> bool:
    if self.templates.pc_client:
        return self._reward_strip_present(screen)
    title = self._locate(
        screen, "transmit_reward_title", 0.90,
        region_override=self._REWARD_TITLE_REGION,
    )
    close = self._locate(
        screen, "transmit_reward_close", 0.92,
        region_override=self._REWARD_CLOSE_REGION,
    )
    return title is not None and close is not None and self._reward_strip_present(screen)
```

Record `_transmit_reward_confirmed = True` before emitting `close_reward`; then enter `RETURNING`. Clear the flag only after stable hero-list return. Add template-shape and non-cross-match assertions to `TemplateTests`.

- [ ] **Step 5: Run reward and transmit tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TransmitRewardEvidenceTests tests/test_hero_synthesis.py::TransmitDecisionTests tests/test_hero_synthesis.py::HeroPageEvidenceTests -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit strong completion evidence**

```powershell
git add games/epic7/hero_synthesis.py games/epic7/templates/hero/transmit_reward_title.png games/epic7/templates/hero/transmit_reward_close.png tests/test_hero_synthesis.py
git commit -m "fix: confirm hero transmission exactly once"
```

### Task 7: Document and verify the complete closed loop

**Files:**
- Modify: `docs/ARCHITECTURE.md:88`

- [ ] **Step 1: Update architecture documentation**

Replace the hero-synthesis bullet in `docs/ARCHITECTURE.md` with:

```markdown
- 英雄合成：模拟器翻卡通过右侧列表的“稳定→定向运动→重新稳定”动态证据确认，因此同名同外观副本也能安全推进；SSS、普通与未知使用三态分类，未知目标不点击。发现 SSS 材料后，传送事务会一直保留当前目标，只有奖励层联合证据稳定出现且返回英雄列表后才清理，防止漏传、误传或重复传送。
```

- [ ] **Step 2: Run all hero and PC-preservation tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py tests/test_navigation.py tests/test_runtime_logging.py -q
```

Expected: all tests pass. PC evidence tests must retain their previous actions, points, retry timing, and lack of simulator-only motion sampling.

- [ ] **Step 3: Run the complete project suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit code 0 with zero failures.

- [ ] **Step 4: Inspect the final diff against scope**

Run:

```powershell
git diff --check
git status --short
git diff --stat HEAD~5..HEAD
```

Expected: no whitespace errors; only the files listed in this plan and the approved design/plan documents changed. Do not clean unrelated user files.

- [ ] **Step 5: Commit final documentation**

```powershell
git add docs/ARCHITECTURE.md
git commit -m "docs: describe hero synthesis visual closed loop"
```
