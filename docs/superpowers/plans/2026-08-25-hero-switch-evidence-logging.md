# Hero Switch Evidence Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make simulator hero-switch logs preserve the exact visual and numeric evidence behind a transition decision without changing the current thresholds.

**Architecture:** Extend the pure `CardSwitchMotionObserver` with immutable per-frame samples and four key frames. Let `HeroSynthRunner` format concise normal summaries and persist detailed evidence only for unconfirmed or same-identity outcomes. Keep final business success reporting separate from motion-candidate reporting.

**Tech Stack:** Python 3.11, dataclasses, NumPy, OpenCV, unittest/pytest, existing `Runtime.save_diagnostic`.

---

### Task 1: Record deterministic motion evidence

**Files:**
- Modify: `games/epic7/hero_transition.py`
- Test: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write the failing observer evidence test**

Add a test that drives a known shifted-list sequence and asserts that `observer.samples` contains frame number, phase before/after, `dx`, `dy`, response, adjacent-frame difference, baseline difference, accumulated shift and settle count. Assert that `departure_screen`, `peak_screen`, and `last_screen` are retained.

```python
def test_motion_observer_records_decision_metrics_and_key_frames(self):
    base = fixture("list_reddot")
    moved = shifted_list(base, -16)
    observer = CardSwitchMotionObserver(base)

    self.assertFalse(observer.update(moved))
    for _ in range(3):
        observer.update(moved.copy())

    sample = observer.samples[0]
    self.assertEqual(1, sample.frame)
    self.assertIs(sample.phase_before, MotionPhase.WAITING_DEPARTURE)
    self.assertIs(sample.phase_after, MotionPhase.MOVING)
    self.assertGreaterEqual(abs(sample.dy), observer.min_vertical_shift)
    self.assertGreater(sample.baseline_difference, 0)
    self.assertIsNotNone(observer.departure_screen)
    self.assertIsNotNone(observer.peak_screen)
    self.assertTrue(np.array_equal(moved, observer.last_screen))
```

- [ ] **Step 2: Run the test and verify RED**

Run: `D:\anaconda\python.exe -m pytest tests/test_hero_synthesis.py::CardSwitchMotionObserverTests::test_motion_observer_records_decision_metrics_and_key_frames -q`

Expected: FAIL because `samples` and key-frame attributes do not exist.

- [ ] **Step 3: Implement the minimal evidence model**

Add a frozen `MotionSample` dataclass and populate it once per `update`. Keep copies of the first departure frame, the frame with the greatest decision score, and the last frame.

```python
@dataclass(frozen=True)
class MotionSample:
    frame: int
    phase_before: MotionPhase
    phase_after: MotionPhase
    dx: float
    dy: float
    response: float
    difference: float
    baseline_difference: float
    accumulated_shift: float
    settle_frames: int
    vertical: bool
    departed: bool
```

The decision score is `max(abs(dy) / min_vertical_shift, difference / departure_difference)` and is used only to choose the peak screenshot, never to alter the decision.

- [ ] **Step 4: Run observer tests and verify GREEN**

Run: `D:\anaconda\python.exe -m pytest tests/test_hero_synthesis.py::CardSwitchMotionObserverTests -q`

Expected: all observer tests PASS.

- [ ] **Step 5: Commit the observer evidence change**

```text
git add games/epic7/hero_transition.py tests/test_hero_synthesis.py
git commit -m "feat(epic7): record hero switch motion evidence"
```

### Task 2: Persist suspicious switch evidence and detailed logs

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Test: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing runner tests**

Add one test with a same-identity motion sequence and a temporary diagnostic directory. Assert that logs contain `切换开始`, `动态证据=候选`, threshold/actual values, every recorded frame, `静态身份=未变化`, and saved `switch_before`, `switch_departure`, `switch_peak`, `switch_final` paths. Add a second test with an identity-changing final frame and assert that no detailed frame logs or suspicious screenshots are written.

```python
with tempfile.TemporaryDirectory() as tmp:
    logs = []
    runtime = Runtime(
        lambda: next(frames),
        lambda _: None,
        diagnostic_dir=Path(tmp),
        emit=logs.append,
    )
    runner = HeroSynthRunner(machine(verify_filter=True), runtime, sleep=lambda _: None)
    runner.machine._last_screen = base
    runner._after_action_click(action)

    output = "\n".join(logs)
    self.assertIn("切换开始", output)
    self.assertIn("动态证据=候选", output)
    self.assertIn("静态身份=未变化", output)
    self.assertIn("证据帧=1", output)
    self.assertEqual(4, len(list(Path(tmp).glob("*switch_*.png"))))
```

- [ ] **Step 2: Run the tests and verify RED**

Run the two new `CardSwitchRunnerTests` directly with pytest.

Expected: FAIL because logs, evidence formatting and suspicious image persistence do not exist.

- [ ] **Step 3: Implement runner evidence handling**

In `_after_action_click`, log the old identity and click coordinate before observing. Retain the observer on the runner, summarize its actual maxima and thresholds, and call a focused `_save_card_switch_evidence` helper when motion is unconfirmed or the final fingerprint is empty/equal to the source fingerprint. The helper saves only available key frames and replays `observer.samples` into structured log lines.

Use these message meanings:

```text
切换开始 旧身份=... 点击=(...)
动态证据=候选（尚未判定业务成功） ...
动态证据=未确认 ...
切换诊断 静态身份=未变化/无法读取 ...
切换证据帧=... phase=... dy=... response=... frame_diff=... baseline_diff=... accumulated=... settle=...
```

- [ ] **Step 4: Run runner tests and verify GREEN**

Run: `D:\anaconda\python.exe -m pytest tests/test_hero_synthesis.py::CardSwitchRunnerTests -q`

Expected: all runner tests PASS.

- [ ] **Step 5: Commit runner diagnostics**

```text
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix(epic7): preserve suspicious hero switch evidence"
```

### Task 3: Make business-result logs truthful and verify the suite

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Test: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write the failing success-log assertions**

Assert that `_transition_success_detail` says `业务切换成功` only after `_transition_completed`, includes both old and new identity, and labels same-identity motion as `静态身份相同，仅由动态证据确认`. Assert that `_after_action_click` contains no `结果=已确认` or `切换成功` message.

- [ ] **Step 2: Run the focused tests and verify RED**

Run the new success-log tests directly.

Expected: FAIL because current messages conflate motion and business success.

- [ ] **Step 3: Implement truthful final wording**

Change only the card-transition detail path:

```python
if observation and observation != previous_action.source_observation:
    evidence = "静态身份变化并连续稳定"
else:
    evidence = "静态身份相同，仅由动态证据确认"
return (
    f"业务切换成功 证据={evidence}；"
    f"旧身份={previous_action.source_observation} 新身份={observation}"
)
```

- [ ] **Step 4: Run focused and full verification**

Run:

```text
D:\anaconda\python.exe -m pytest tests/test_hero_synthesis.py -q
D:\anaconda\python.exe -m pytest tests/test_pc_hero_synthesis_evidence.py -q
D:\anaconda\python.exe -m pytest -q
git diff --check
```

Expected: all tests PASS and `git diff --check` prints nothing.

- [ ] **Step 5: Commit the final logging change**

```text
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix(epic7): separate motion evidence from switch success"
```

### Task 4: Gather real evidence before changing recognition

**Files:**
- Inspect: `runtime_diagnostics/epic7_hero_synthesis/`
- Inspect: runtime log configured by the launcher

- [ ] **Step 1: Restart the launcher worker so it loads the committed code**

Use the existing safe stop control and launcher flow; do not run a second automation worker concurrently.

- [ ] **Step 2: Run one complete hero-synthesis cycle**

Do not stop after a sample of heroes. Monitor until the runner reports one completed cycle or emits a concrete failure.

- [ ] **Step 3: If a switch is suspicious, inspect its evidence bundle**

Identify the exact first crossing frame, metric and region from the saved images and structured lines. Form one root-cause hypothesis from that evidence.

- [ ] **Step 4: Add a regression test before any recognition change**

Use the captured sequence or a minimal deterministic reproduction. Verify the test fails against the current predicate, then make one recognition change and replay both failed and successful transitions.

- [ ] **Step 5: Re-run the complete cycle and commit only after verification**

The final handoff must distinguish “logging fixed” from any separately proven recognition fix and include the full-cycle outcome.
