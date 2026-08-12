# Arena Failed Opponent Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make arena choose a random non-failed opponent from the current three-row list and refresh only when all three rows are visibly failed.

**Architecture:** `ArenaStateMachine` classifies each row from a small background-only HSV region and emits either `select-opponent` or `refresh-opponents`. The current screenshot remains the source of truth; only the selected row is cached long enough to retry a swallowed selection click. `ArenaRunner` verifies selection with the existing `SELECTED` transition and verifies refresh separately by waiting for a stable list containing at least one safe opponent.

**Tech Stack:** Python 3, NumPy, OpenCV HSV masks, existing template matcher/state machine/Runner, pytest and unittest fixtures.

---

Run all commands from `D:\AI\codex\auto_game`. No step may start, stop, click, or control the emulator; real acceptance remains user-owned.

## File map

- Add `tests/fixtures/epic7_arena/failed_first_opponent.png`: immutable copy of the latest real failure list.
- Modify `games/epic7/arena.py`: classify three rows, choose a safe row, recognize the free refresh button, and expose refresh verification.
- Modify `tests/test_epic7_arena.py`: state-machine regressions for safe selection, all-failed refresh, ambiguous rows, retry, and cycle counting.
- Modify `tests/test_arena_runner.py`: refresh transition verification and one-cycle integration behavior.
- Modify `README.md`: document failed-opponent rotation.

### Task 1: Preserve the real failure and lock the visual boundary

**Files:**
- Create: `tests/fixtures/epic7_arena/failed_first_opponent.png`
- Modify: `tests/test_epic7_arena.py`

- [ ] **Step 1: Copy the recorded failure screenshot byte-for-byte**

Run:

```powershell
Copy-Item -LiteralPath `
  auto_game_unified\runtime_diagnostics\epic7_arena\20260812_225658_637530_no_transition_confirming_to_selected.png `
  -Destination auto_game_unified\tests\fixtures\epic7_arena\failed_first_opponent.png
```

Verify both files have the same SHA-256:

```powershell
Get-FileHash auto_game_unified\runtime_diagnostics\epic7_arena\20260812_225658_637530_no_transition_confirming_to_selected.png
Get-FileHash auto_game_unified\tests\fixtures\epic7_arena\failed_first_opponent.png
```

Expected: identical hashes.

- [ ] **Step 2: Add failing row-classification tests**

In `tests/test_epic7_arena.py`, add:

```python
def test_failed_row_classifier_uses_background_color_only(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    failed = machine.opponent_availability(load_fixture("failed_first_opponent"))
    normal = machine.opponent_availability(load_fixture("list"))

    self.assertEqual((False, True, True), failed)
    self.assertEqual((True, True, True), normal)


def test_ambiguous_row_is_not_exposed_as_a_safe_opponent(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES))
    screen = load_fixture("list").copy()
    x, y, width, height = machine._scaled_region(screen, machine._OPPONENT_STATUS_REGIONS[1])
    screen[y : y + height, x : x + width] = np.array([120, 65, 55], dtype=np.uint8)

    availability = machine.opponent_availability(screen)

    self.assertIsNone(availability[1])
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_epic7_arena.py -k "failed_row_classifier or ambiguous_row" -q
```

Expected: FAIL because `opponent_availability`, `_scaled_region`, and `_OPPONENT_STATUS_REGIONS` do not exist.

- [ ] **Step 4: Implement minimal background-only classification**

In `ArenaStateMachine`, add reference-coordinate regions that avoid portraits and hero icons:

```python
_OPPONENT_STATUS_REGIONS = (
    (600, 320, 220, 135),
    (600, 510, 220, 140),
    (600, 705, 220, 140),
)
_FAILED_RED_MIN_RATIO = 0.50
_AVAILABLE_RED_MAX_RATIO = 0.05

@classmethod
def _scaled_region(cls, screen, region):
    scale_x = screen.shape[1] / cls._REFERENCE_SIZE[0]
    scale_y = screen.shape[0] / cls._REFERENCE_SIZE[1]
    x, y, width, height = region
    return (
        round(x * scale_x),
        round(y * scale_y),
        round(width * scale_x),
        round(height * scale_y),
    )

def opponent_availability(self, screen):
    availability = []
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    for region in self._OPPONENT_STATUS_REGIONS:
        x, y, width, height = self._scaled_region(screen, region)
        roi = hsv[y : y + height, x : x + width]
        red = (
            ((roi[:, :, 0] <= 10) | (roi[:, :, 0] >= 170))
            & (roi[:, :, 1] >= 60)
            & (roi[:, :, 2] >= 35)
        )
        ratio = float(np.mean(red))
        availability.append(
            False
            if ratio >= self._FAILED_RED_MIN_RATIO
            else True
            if ratio <= self._AVAILABLE_RED_MAX_RATIO
            else None
        )
    return tuple(availability)
```

Do not inspect the full row, opponent portrait, name, score, or hero icons.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_epic7_arena.py -k "failed_row_classifier or ambiguous_row" -q
```

Expected: both pass.

Commit:

```powershell
git -C auto_game_unified add tests/fixtures/epic7_arena/failed_first_opponent.png tests/test_epic7_arena.py games/epic7/arena.py
git -C auto_game_unified commit -m "recognize failed arena opponent rows"
```

### Task 2: Select only safe opponents and refresh an exhausted list

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_epic7_arena.py`

- [ ] **Step 1: Add failing action-selection tests**

Add these cases to `tests/test_epic7_arena.py`:

```python
def test_failed_first_opponent_selects_from_the_other_two(self):
    choices = []
    machine = ArenaStateMachine(
        build_templates(TEMPLATES),
        choose_opponent=lambda safe: choices.append(tuple(safe)) or safe[-1],
    )

    action = machine.next_action(load_fixture("failed_first_opponent"))

    self.assertEqual("select-opponent", action.name)
    self.assertEqual((1, 2), choices[0])
    self.assertEqual(machine._opponent_point(load_fixture("list"), 2), action.point)
    self.assertEqual(ArenaState.SELECTED, machine.state)


def test_all_failed_opponents_trigger_refresh_without_advancing_state(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES))
    screen = load_fixture("failed_first_opponent").copy()
    first = machine._OPPONENT_STATUS_REGIONS[0]
    first_x, first_y, first_width, first_height = machine._scaled_region(screen, first)
    failed_color = screen[first_y : first_y + first_height, first_x : first_x + first_width].copy()
    for region in machine._OPPONENT_STATUS_REGIONS[1:]:
        x, y, width, height = machine._scaled_region(screen, region)
        screen[y : y + height, x : x + width] = cv2.resize(
            failed_color, (width, height)
        )

    action = machine.next_action(screen)

    self.assertEqual("refresh-opponents", action.name)
    self.assertEqual(ArenaState.LIST, machine.state)
    self.assertEqual(0, machine.completed_cycles)


def test_selected_opponent_retry_uses_the_same_row(self):
    machine = ArenaStateMachine(
        build_templates(TEMPLATES),
        choose_opponent=lambda safe: safe[1],
    )
    screen = load_fixture("list")
    first = machine.next_action(screen)

    retry = machine.next_action(screen)

    self.assertEqual("select-opponent", retry.name)
    self.assertEqual(first.point, retry.point)


def test_confirmed_result_counts_once_before_refresh_decision(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.CONFIRMING)
    screen = make_all_failed_screen(machine)

    action = machine.next_action(screen)

    self.assertEqual("refresh-opponents", action.name)
    self.assertEqual(1, machine.completed_cycles)
    self.assertEqual(ArenaState.LIST, machine.state)
```

Extract `make_all_failed_screen(machine)` as a test helper using the same region-copy construction as the earlier test, so production code is not used to manufacture its own positive case.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_epic7_arena.py -k "other_two or all_failed or selected_opponent_retry or counts_once_before_refresh" -q
```

Expected: FAIL because the constructor has no `choose_opponent`, the machine still hard-codes the first row, and no refresh action exists.

- [ ] **Step 3: Implement safe selection with one cached retry row**

Add `import random` and `Sequence` to `games/epic7/arena.py`. Change the constructor to:

```python
def __init__(
    self,
    templates: ArenaTemplates,
    *,
    initial_state: ArenaState = ArenaState.LIST,
    choose_opponent: Callable[[Sequence[int]], int] = random.choice,
) -> None:
    self.templates = templates
    self.state = initial_state
    self.completed_cycles = 0
    self.choose_opponent = choose_opponent
    self._selected_opponent: int | None = None
```

Use anchor-relative points, preserving the proven first-row location:

```python
_OPPONENT_OFFSETS = (
    (-210, -639),
    (-210, -448),
    (-210, -256),
)
_REFRESH_OFFSET = (383, -823)

def _opponent_point(self, screen, index):
    anchor = self._locate(screen, "list_ready")
    if anchor is None:
        raise RuntimeError("list_ready anchor lost while selecting opponent")
    offset = self._OPPONENT_OFFSETS[index]
    return anchor.center[0] + offset[0], anchor.center[1] + offset[1]

def _refresh_point(self, screen):
    anchor = self._locate(screen, "list_ready")
    if anchor is None:
        raise RuntimeError("list_ready anchor lost while refreshing opponents")
    return anchor.center[0] + self._REFRESH_OFFSET[0], anchor.center[1] + self._REFRESH_OFFSET[1]
```

Add one list action helper:

```python
def _list_action(self, screen):
    availability = self.opponent_availability(screen)
    safe = [index for index, value in enumerate(availability) if value is True]
    if safe:
        self._selected_opponent = self.choose_opponent(safe)
        self.state = ArenaState.SELECTED
        return Action("select-opponent", self._opponent_point(screen, self._selected_opponent))
    if all(value is False for value in availability):
        self._selected_opponent = None
        return Action("refresh-opponents", self._refresh_point(screen))
    raise RuntimeError("arena opponent rows could not be classified safely")
```

Apply it in exactly three places:

- `LIST`: return `_list_action(screen)`.
- `CONFIRMING` after `list_ready`: increment `completed_cycles`, set `LIST`, then return `_list_action(screen)`.
- `SELECTED` retry: click `_selected_opponent` again; never choose a new row during the same selection transition.

Update `preview()` to snapshot and restore `_selected_opponent` in addition to state and cycle count. Keep action name generic (`select-opponent`) so repeated preview calls do not become unstable when the injected/default random chooser returns different safe indices.

- [ ] **Step 4: Run state-machine tests and commit**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_epic7_arena.py -q
```

Expected: all pass. Update old expected action names from `select-first-row` to `select-opponent`; do not change their state or cycle expectations.

Commit:

```powershell
git -C auto_game_unified add games/epic7/arena.py tests/test_epic7_arena.py
git -C auto_game_unified commit -m "rotate failed arena opponents"
```

### Task 3: Verify refresh before continuing

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_arena_runner.py`

- [ ] **Step 1: Add failing Runner refresh tests**

In `tests/test_arena_runner.py`, add a focused fake machine with `state=LIST`, `completed_cycles=1`, and:

```python
def test_refresh_waits_for_a_list_with_a_safe_opponent(self):
    machine = MagicMock()
    machine.state = ArenaState.LIST
    machine.completed_cycles = 1
    machine.preview.return_value = (Action("refresh-opponents", (1344, 225)), None)
    machine.next_action.return_value = Action("refresh-opponents", (1344, 225))
    machine.has_safe_opponent.side_effect = [False, True]
    screens = iter([frame(1), frame(2), frame(3), frame(4)])
    clicks = []
    runner = ArenaRunner(
        machine,
        Runtime(lambda: next(screens), clicks.append, emit=lambda line: None),
        sleep=lambda seconds: None,
    )

    runner.run(max_cycles=2)

    self.assertIn((1344, 225), clicks)
    self.assertGreaterEqual(machine.has_safe_opponent.call_count, 2)
```

Use the file's existing helpers/import style. The fake should return a normal selection action after `has_safe_opponent` becomes true so `run()` can stop at the next controlled checkpoint; do not use real time.

Add a direct failure-path test:

```python
def test_refresh_that_never_produces_a_safe_opponent_stops_with_diagnostic(self):
    ...
    runner._TIMEOUT_SECONDS = {**runner._TIMEOUT_SECONDS, ArenaState.LIST: 0}
    with self.assertRaisesRegex(RuntimeError, "refresh did not produce"):
        runner.run(max_cycles=2)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_arena_runner.py -k "refresh_waits or refresh_that_never" -q
```

Expected: FAIL because refresh currently uses generic `LIST` recognition and can accept the unchanged all-red screen.

- [ ] **Step 3: Add a dedicated refresh waiter**

In `ArenaStateMachine`, add:

```python
def has_safe_opponent(self, screen: np.ndarray) -> bool:
    return any(value is True for value in self.opponent_availability(screen))
```

In `ArenaRunner`, add `_wait_until_safe_list()` using the same absolute/no-progress structure as `_wait_until_in_state`, but succeed only when both conditions hold:

```python
self.machine.is_in_state(screen, ArenaState.LIST)
and self.machine.has_safe_opponent(screen)
```

Immediately after clicking `refresh-opponents`, call this waiter. On failure save `refresh_opponents_failed`, log the diagnostic, and raise:

```python
RuntimeError(f"refresh did not produce a safe opponent list; saved {diagnostic}")
```

On success keep `machine.state = ArenaState.LIST`, reset stability, reset `state_started`, and continue. Do not call `_wait_until_in_state(SELECTED)` for refresh, and do not increment `completed_cycles`.

- [ ] **Step 4: Run arena integration tests and commit**

Run:

```powershell
python -m pytest auto_game_unified\tests\test_epic7_arena.py auto_game_unified\tests\test_arena_runner.py auto_game_unified\tests\test_ticket_exhaustion.py auto_game_unified\tests\test_navigation.py -q
```

Expected: all pass.

Commit:

```powershell
git -C auto_game_unified add games/epic7/arena.py tests/test_arena_runner.py
git -C auto_game_unified commit -m "verify arena opponent refresh"
```

### Task 4: Document and verify the complete change

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document arena rotation**

Update the arena route description to state:

```markdown
- `arena`：新手竞技场循环，失败后跳过红色对手并从剩余对手中随机选择；三名对手均失败时先确认并执行免费刷新。处理战斗结算、段位提升等弹窗，并禁止危险的钻石购买路径。
```

Also state under cycle rules that a completed challenge counts once whether it wins or loses, while refresh does not count.

- [ ] **Step 2: Run full offline verification**

Run:

```powershell
python -m pytest auto_game_unified\tests -q
python -m compileall -q auto_game_unified
git -C auto_game_unified diff --check
```

Expected: all tests pass, compile exits `0`, and diff check prints no errors. No emulator process is started.

- [ ] **Step 3: Commit documentation**

```powershell
git -C auto_game_unified add README.md
git -C auto_game_unified commit -m "document arena opponent rotation"
```

## User-owned live acceptance

After the offline implementation is merged, the user runs:

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.main --mode arena --max-cycles 5 --live --confirm RUN
```

Acceptance evidence:

- A red failed row is never clicked again.
- With one red row, only rows two or three are selected.
- With two red rows, the remaining row is selected.
- With three red rows, `refresh-opponents` is logged once, a safe refreshed list is confirmed, and refresh does not increase the cycle count.
- Any ambiguous row state or ineffective refresh saves a diagnostic and stops instead of blind clicking.
