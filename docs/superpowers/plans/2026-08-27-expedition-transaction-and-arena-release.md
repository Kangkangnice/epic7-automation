# Expedition Transaction and Arena Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Expedition commit page state only after stable target evidence, skip an already-selected stage three click, and publish Arena as a formal simulator feature.

**Architecture:** Expedition keeps its existing templates and battle supervisor. Its actions become explicit source/target contracts, and its runner owns the short per-action transition observer used by Arena rather than advancing state inside `next_action`. The catalog remains the sole source of formal/experimental UI status.

**Tech Stack:** Python 3.13, unittest, OpenCV template matching, desktop Tk application.

---

### Task 1: Capture the two regressions in tests

**Files:**
- Modify: `tests/test_epic7_expedition.py`
- Modify: `tests/test_expedition_runner.py`

- [ ] **Step 1: Write the failing stage-three test**

```python
machine = self.machine(ExpeditionState.DIFFICULTY)
action = machine.next_action(recorded_screen("difficulty_3_selected"))
self.assertEqual("confirm-difficulty-3", action.name)
self.assertEqual(ExpeditionState.DIFFICULTY, machine.state)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_epic7_expedition.ExpeditionStateMachineTests.test_selected_stage_three_confirms_without_toggling -v`

Expected: fails because the current action is `select-difficulty-3` and/or state advances before transition confirmation.

- [ ] **Step 3: Write the failing poster transaction test**

Use the recorded `20260826_234916_645673_unknown_before_wake.png` as the source page after `open-my-posters`; assert the runner emits `select-first-poster`, retries it when the same source frame persists, and never invokes `wake-unknown-screen`.

- [ ] **Step 4: Run the test and verify RED**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_expedition_runner.ExpeditionRunnerTests.test_poster_departure_is_not_discarded_while_previous_transition_is_pending -v`

Expected: fails because the current runner discards `select-first-poster` after seeing a speculative `难度选择` label.

### Task 2: Make the Expedition state machine declarative

**Files:**
- Modify: `games/epic7/expedition.py`
- Test: `tests/test_epic7_expedition.py`

- [ ] **Step 1: Extend actions with state contracts**

```python
@dataclass(frozen=True)
class ExpeditionAction:
    name: str
    point: tuple[int, int]
    source_state: ExpeditionState | None = None
    target_states: tuple[ExpeditionState, ...] = ()
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    reason: str = ""
```

- [ ] **Step 2: Stop page actions from mutating state**

Return the action with its current `source_state` and allowed `target_states`; add `commit(action, target)` to validate the contract, move state, and only increment `completed_cycles` after the stable home target of a completed expedition transaction.

- [ ] **Step 3: Encode stage-three idempotence**

When difficulty title, selected stage-three marker and confirmation button coexist, return only `confirm-difficulty-3`. Otherwise return `select-difficulty-3` and allow only the selected/confirm state as its target.

- [ ] **Step 4: Run the state-machine regression tests and verify GREEN**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_epic7_expedition -v`

Expected: all Expedition state-machine tests pass.

### Task 3: Add a local transition observer to ExpeditionRunner

**Files:**
- Modify: `games/epic7/expedition.py`
- Test: `tests/test_expedition_runner.py`

- [ ] **Step 1: Implement `_execute_transition(action)`**

Click once, then use two stable observations to query whether the action source remains visible or one declared target is visible. Retry only while the source remains visible; wait if the source has left; call `machine.commit(action, target)` only after a target is stable twice. Save diagnostics and raise if no target becomes stable within the route timeout.

- [ ] **Step 2: Route every non-battle page action through that observer**

Do not let `ModeRunnerBase` infer confirmation from `_confirmed_page` for Expedition actions. Keep the shared battle supervisor unchanged and enter it only after the `battle-start` target has been confirmed.

- [ ] **Step 3: Run runner tests and verify GREEN**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_expedition_runner -v`

Expected: the new poster test and existing runner tests pass.

### Task 4: Publish Arena as formal and document the corrected Expedition status

**Files:**
- Modify: `desktop/catalog.py`
- Modify: `tests/test_desktop_catalog.py`
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/TODO.md`

- [ ] **Step 1: Write the failing catalog assertion**

```python
assert route_by_name("arena").status == "正式功能"
assert not route_by_name("arena").experimental
```

- [ ] **Step 2: Run the catalog test and verify RED**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_desktop_catalog -v`

Expected: fails because Arena is still marked `实验功能`.

- [ ] **Step 3: Apply the smallest catalog and wording changes**

Set only Arena's catalog status to `正式功能`; update README and user guide to call Hero Synthesis and Arena formal simulator features, while the remaining routes and every PC route remain experimental. Keep Expedition experimental pending the user-run live cycle.

- [ ] **Step 4: Run the catalog test and verify GREEN**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_desktop_catalog -v`

Expected: all catalog tests pass.

### Task 5: Verify and commit

**Files:**
- Verify: all files above

- [ ] **Step 1: Run focused tests**

Run: `D:\anaconda\python.exe -m unittest auto_game_unified.tests.test_epic7_expedition auto_game_unified.tests.test_expedition_runner auto_game_unified.tests.test_desktop_catalog -v`

Expected: zero failures.

- [ ] **Step 2: Run the full suite and compile check**

Run: `D:\anaconda\python.exe -m unittest discover -s auto_game_unified/tests -p "test_*.py" -v` and `D:\anaconda\python.exe -m compileall auto_game_unified`.

Expected: zero test failures and zero compilation failures.

- [ ] **Step 3: Review and commit**

Run: `git diff --check`, inspect `git diff`, then commit only the Expedition, desktop catalog, tests and documentation changes with `git commit -m "fix: commit expedition transitions after confirmation"`.

- [ ] **Step 4: Request user-run live verification**

Ask the user to run one Expedition cycle from the desktop UI or `python -u -m auto_game_unified.main --mode expedition --window-backend emulator --max-cycles 1 --live --confirm RUN`; state that this is a real-game validation and must be user initiated.
