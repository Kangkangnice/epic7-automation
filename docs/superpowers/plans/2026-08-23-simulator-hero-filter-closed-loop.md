# Simulator Hero Filter Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the simulator hero-synthesis filter flow verify its source and target screens around every click, with tight reusable templates, product-readable logs, and a no-click 60-second black-screen stop.

**Architecture:** Add a simulator-only `FilterObservation` classifier to the existing screenshot-driven state machine and attach source/target metadata to filter actions. Keep the shared Runner, but teach it to render transition metadata and provide an opt-in black-screen guard; only `HeroSynthRunner` enables the guard and disables unknown-screen wake clicks. Preserve the existing PC filter branch unchanged by loading the new visual assets only from the simulator template profile.

**Tech Stack:** Python 3.10+, OpenCV, NumPy, unittest/pytest, existing `Runtime`, `ModeRunnerBase`, and real `1982×1132` LDPlayer screenshots.

---

### Task 1: Record and validate minimal simulator visual evidence

**Files:**
- Create: `tests/fixtures/epic7_hero/filter_open_star3_unselected.png`
- Create: `games/epic7/templates/hero/filter_attribute_label.png`
- Create: `games/epic7/templates/hero/filter_star3_unselected.png`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Verify the preserved full live screenshot**

Read `tests/fixtures/epic7_hero/filter_open_star3_unselected.png` without altering it. Verify dimensions are `(1132, 1982, 3)` and SHA-256 is `F364DEC84F5651918F7997185B9DF4096910330DD9C2A4534F8668131A9E7827`.

- [ ] **Step 2: Generate only tight, background-independent template crops**

Use the real unselected fixture and these exact source rectangles:

```python
screen = cv2.imread(str(FIXTURES / "filter_open_star3_unselected.png"))
cv2.imwrite(
    str(TEMPLATES / "hero" / "filter_attribute_label.png"),
    screen[265:313, 657:747],
)
cv2.imwrite(
    str(TEMPLATES / "hero" / "filter_star3_unselected.png"),
    screen[600:672, 1072:1148],
)
```

The resulting dimensions must be exactly `90×48` for “属性” and `76×72` for the dark `★3` button. Neither crop may include hero portrait, hero name, rating, list card, or any region outside the filter panel control itself.

- [ ] **Step 3: Write failing template-contract tests**

Add tests that expect `HeroTemplates` to expose `filter_attribute_label` and `filter_star3_unselected`, and assert exact crop sizes:

```python
def test_filter_templates_are_tight_control_only_crops(self):
    templates = build_hero_templates(TEMPLATES)
    self.assertEqual((48, 90), templates.filter_attribute_label.shape[:2])
    self.assertEqual((72, 76), templates.filter_star3_selected.shape[:2])
    self.assertEqual((72, 76), templates.filter_star3_unselected.shape[:2])
```

Add a score-matrix test using `_locate()`:

```python
def test_selected_and_unselected_templates_do_not_cross_match(self):
    m = machine()
    selected = fixture("filter_open")
    unselected = fixture("filter_open_star3_unselected")
    self.assertIsNotNone(m._locate(selected, "filter_star3_selected", 0.90))
    self.assertIsNone(m._locate(selected, "filter_star3_unselected", 0.90))
    self.assertIsNotNone(m._locate(unselected, "filter_star3_unselected", 0.90))
    self.assertIsNone(m._locate(unselected, "filter_star3_selected", 0.90))
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TemplateTests -q
```

Expected: FAIL because the two new fields are not yet part of `HeroTemplates`/`build_hero_templates()`.

- [ ] **Step 5: Load simulator-only templates with PC-safe optionals**

Add the fields after the required templates:

```python
filter_attribute_label: Optional[np.ndarray] = None
filter_star3_unselected: Optional[np.ndarray] = None
```

In `build_hero_templates()`, load them when the files exist. The PC profile receives `None`; do not add files under `templates_pc/hero/`.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::TemplateTests -q
```

Expected: all `TemplateTests` pass.

- [ ] **Step 7: Commit the evidence slice**

```powershell
git add tests/fixtures/epic7_hero/filter_open_star3_unselected.png games/epic7/templates/hero/filter_attribute_label.png games/epic7/templates/hero/filter_star3_unselected.png games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "test: add real simulator filter evidence"
```

### Task 2: Classify exact filter-page observations

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing observer tests**

Import `FilterObservation` and add:

```python
class FilterObservationTests(unittest.TestCase):
    def test_closed_hero_list_requires_list_anchors_and_no_panel_anchors(self):
        m = machine()
        self.assertIs(
            FilterObservation.HERO_LIST_FILTER_CLOSED,
            m._observe_filter(fixture("list_unfiltered")),
        )

    def test_real_selected_panel_is_selected(self):
        m = machine()
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            m._observe_filter(fixture("filter_open")),
        )

    def test_real_unselected_panel_is_unselected(self):
        m = machine()
        self.assertIs(
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
            m._observe_filter(fixture("filter_open_star3_unselected")),
        )

    def test_panel_missing_either_permanent_anchor_is_unknown(self):
        m = machine()
        screen = fixture("filter_open_star3_unselected").copy()
        screen[265:313, 657:747] = 0
        self.assertIs(FilterObservation.UNKNOWN, m._observe_filter(screen))
```

- [ ] **Step 2: Run observer tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FilterObservationTests -q
```

Expected: collection or assertion failure because `FilterObservation` and `_observe_filter()` do not exist.

- [ ] **Step 3: Implement the minimal observer**

Add:

```python
class FilterObservation(Enum):
    HERO_LIST_FILTER_CLOSED = "hero_list_filter_closed"
    FILTER_OPEN_STAR3_SELECTED = "filter_open_star3_selected"
    FILTER_OPEN_STAR3_UNSELECTED = "filter_open_star3_unselected"
    UNKNOWN = "unknown"
```

Extend `_REGIONS`:

```python
"filter_attribute_label": (630, 250, 220, 90),
"filter_star3_unselected": (1050, 590, 180, 90),
```

Implement `_observe_filter()` with this precedence:

```python
def _observe_filter(self, screen: np.ndarray) -> FilterObservation:
    level = self._locate(screen, "filter_level_label", 0.80)
    attribute = self._locate(screen, "filter_attribute_label", 0.82)
    panel_open = level is not None and attribute is not None
    if panel_open:
        if self._locate(screen, "filter_star3_selected", 0.90) is not None:
            return FilterObservation.FILTER_OPEN_STAR3_SELECTED
        if self._locate(screen, "filter_star3_unselected", 0.90) is not None:
            return FilterObservation.FILTER_OPEN_STAR3_UNSELECTED
        return FilterObservation.UNKNOWN
    if level is not None or attribute is not None:
        return FilterObservation.UNKNOWN
    if (
        self._locate(screen, "filter_button", 0.80) is not None
        and self._hero_list_ready(screen)
    ):
        return FilterObservation.HERO_LIST_FILTER_CLOSED
    return FilterObservation.UNKNOWN
```

Call this method only for simulator templates where both new assets are present. PC continues through the current filter logic.

- [ ] **Step 4: Verify observer GREEN and negative fixture matrix**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FilterObservationTests tests/test_hero_synthesis.py::TemplateTests -q
```

Expected: all selected tests pass. Also iterate all `tests/fixtures/epic7_hero/*.png`; only the two filter fixtures may classify as an open filter panel.

- [ ] **Step 5: Commit the observer**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "feat: classify simulator hero filter screens"
```

### Task 3: Make filter actions closed-loop transitions

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing swallowed-click and completion tests**

Replace the synthetic blacked-out unselected test with the real fixture. Add independent tests:

```python
def test_open_filter_keeps_same_action_when_click_is_swallowed(self):
    m = machine()
    first = m.next_action(fixture("list_unfiltered"))
    second = m.next_action(fixture("list_unfiltered"))
    self.assertEqual("open_filter", first.name)
    self.assertEqual("open_filter", second.name)
    self.assertFalse(m.filter_verified)

def test_select_star3_keeps_same_action_when_click_is_swallowed(self):
    m = machine()
    first = m.next_action(fixture("filter_open_star3_unselected"))
    second = m.next_action(fixture("filter_open_star3_unselected"))
    self.assertEqual("select_star3", first.name)
    self.assertEqual("select_star3", second.name)
    self.assertFalse(m.filter_verified)

def test_close_filter_keeps_same_action_when_click_is_swallowed(self):
    m = machine()
    first = m.next_action(fixture("filter_open"))
    second = m.next_action(fixture("filter_open"))
    self.assertEqual("close_filter", first.name)
    self.assertEqual("close_filter", second.name)
    self.assertFalse(m.filter_verified)

def test_filter_is_committed_only_after_closed_list_is_stable(self):
    m = machine()
    m.next_action(fixture("filter_open"))
    preview, outcome = m.preview(fixture("list_unfiltered"))
    self.assertIsNone(preview)
    self.assertIs(outcome[0], HeroSynthState.HERO_LIST)
    self.assertFalse(m.filter_verified)
    committed = m.next_action(fixture("list_unfiltered"))
    self.assertIsNone(committed)
    self.assertTrue(m.filter_verified)
```

- [ ] **Step 2: Run the transition tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FilterDecisionTests -q
```

Expected: failures show `close_filter` commits verification before the target page appears and the unchanged selected panel does not keep the same action.

- [ ] **Step 3: Add reusable action transition metadata**

Extend `HeroAction` without changing existing call sites:

```python
@dataclass(frozen=True)
class HeroAction:
    name: str
    point: tuple[int, int]
    source_page: str = ""
    target_pages: tuple[str, ...] = ()
    reason: str = ""
```

Simulator filter actions populate these fields with Chinese product labels. For example:

```python
HeroAction(
    "select_star3",
    self._scaled_point(screen, self._STAR3_POINT),
    source_page="筛选面板（三星未选中）",
    target_pages=("筛选面板（三星已选中）",),
    reason="级别与属性锚点存在，三星深色按钮存在",
)
```

- [ ] **Step 4: Replace optimistic simulator filter flags with target confirmation**

Add `_filter_close_pending = False` and `_confirmed_page = ""`. Implement `_next_simulator_filter_action()` returning `(handled, action)`:

```python
def _next_simulator_filter_action(
    self, screen: np.ndarray
) -> tuple[bool, Optional[HeroAction]]:
    observation = self._observe_filter(screen)
    labels = {
        FilterObservation.HERO_LIST_FILTER_CLOSED: "英雄列表",
        FilterObservation.FILTER_OPEN_STAR3_SELECTED: "筛选面板（三星已选中）",
        FilterObservation.FILTER_OPEN_STAR3_UNSELECTED: "筛选面板（三星未选中）",
    }
    self._confirmed_page = labels.get(observation, "")

    if observation is FilterObservation.FILTER_OPEN_STAR3_UNSELECTED:
        self.state = HeroSynthState.FILTER
        return True, HeroAction(
            "select_star3",
            self._scaled_point(screen, self._STAR3_POINT),
            "筛选面板（三星未选中）",
            ("筛选面板（三星已选中）",),
            "两个面板锚点存在，三星深色按钮存在",
        )
    if observation is FilterObservation.FILTER_OPEN_STAR3_SELECTED:
        self.state = HeroSynthState.FILTER
        self._filter_close_pending = True
        return True, HeroAction(
            "close_filter",
            self._scaled_point(screen, self._FUNNEL_POINT),
            "筛选面板（三星已选中）",
            ("英雄列表",),
            "两个面板锚点和三星白底按钮均存在",
        )
    if observation is FilterObservation.HERO_LIST_FILTER_CLOSED:
        if self._filter_close_pending:
            self._filter_close_pending = False
            self.filter_verified = True
            self._filter_session_done = True
            self.state = HeroSynthState.HERO_LIST
            return True, None
        if not self.filter_verified:
            return True, HeroAction(
                "open_filter",
                self._scaled_point(screen, self._FUNNEL_POINT),
                "英雄列表",
                ("筛选面板（三星已选中）", "筛选面板（三星未选中）"),
                "漏斗和刻印按钮存在，筛选面板两个锚点均消失",
            )
        return False, None
    if self.state is HeroSynthState.FILTER or self._filter_close_pending:
        return True, None
    return False, None
```

Use `_point()` for PC/simulator coordinate selection where required by the existing code style. Snapshot and restore `_filter_close_pending` and `_confirmed_page` in `preview()`. Keep the old `_awaiting_star3_confirmation` branch exclusively for `templates.pc_client`.

- [ ] **Step 5: Run transition tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::FilterDecisionTests tests/test_hero_synthesis.py::GuardTests -q
```

Expected: all selected tests pass; unchanged source screenshots always return the same action and `filter_verified` remains false until the closed list is committed.

- [ ] **Step 6: Commit the closed loop**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify simulator hero filter transitions"
```

### Task 4: Put filter actions through one retry ledger and product logs

**Files:**
- Modify: `games/epic7/runner_base.py`
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing Runner behavior tests**

Import `StableObservation` and `NOT_STABLE`. Add a test proving `close_filter` no longer clicks inside the stability helper:

```python
def test_close_filter_uses_normal_stability_path(self):
    clicks = []
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: fixture("filter_open"), clicks.append),
        sleep=lambda _: None,
    )
    stable = StableObservation(required=2)
    first = runner._stable_next_action(fixture("filter_open"), stable)
    second = runner._stable_next_action(fixture("filter_open"), stable)
    self.assertIs(first, NOT_STABLE)
    self.assertEqual("close_filter", second.name)
    self.assertEqual([], clicks)

def test_filter_retry_interval_is_five_seconds(self):
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: fixture("list_unfiltered"), lambda _: None),
        sleep=lambda _: None,
    )
    for name in ("open_filter", "select_star3", "close_filter"):
        self.assertEqual(5, runner._action_retry_seconds(name))
```

For the retry ledger, add this deterministic clock and keep returning the unchanged selected panel until the four-attempt guard stops the run:

```python
class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds

def test_unchanged_selected_panel_clicks_close_exactly_four_times(self):
    clock = FakeClock()
    clicks = []
    with TemporaryDirectory() as tmp:
        runtime = Runtime(
            lambda: fixture("filter_open"),
            lambda point: clicks.append(point),
            emit=lambda _: None,
            diagnostic_dir=Path(tmp),
            monotonic=clock,
        )
        runner = HeroSynthRunner(machine(), runtime, sleep=clock.sleep)
        with self.assertRaisesRegex(RuntimeError, "点击4次"):
            runner.run(max_cycles=1)
    self.assertEqual(4, len(clicks))
```

Do not mock `next_action()`. Before the fix, the instant-action bypass keeps clicking outside the ledger and the expected four-attempt error is not produced.

Add a log test that checks these substrings after a swallowed click and later target success:

```python
self.assertLogContains("当前页面=筛选面板（三星已选中）")
self.assertLogContains("目标页面=英雄列表")
self.assertLogContains("重试=close_filter 原因=原页面仍存在且目标页面未出现")
self.assertLogContains("完成=close_filter 目标页面=英雄列表")
```

- [ ] **Step 2: Run Runner tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::RunnerFlowTests -q
```

Expected: failures show `close_filter` still bypasses the normal retry ledger, uses the default retry interval, and does not emit source/target completion logs.

- [ ] **Step 3: Remove the `close_filter` instant-action bypass**

Change `HeroSynthRunner._is_instant_action()` to return `False`. Add:

```python
_FILTER_ACTIONS = {"open_filter", "select_star3", "close_filter"}

def _action_retry_seconds(self, action_name: str) -> float:
    if action_name in self._FILTER_ACTIONS:
        return 5
    if action_name.startswith("add_material"):
        return self._MATERIAL_RETRY_SECONDS
    if action_name.startswith("next_card"):
        return self._NEXT_CARD_RETRY_SECONDS
    return super()._action_retry_seconds(action_name)
```

- [ ] **Step 4: Render transition metadata in the shared Runner**

Track the last clicked action object in addition to `last_action_name`. Before each click, when metadata is present, log:

```python
targets = "/".join(action.target_pages)
self.runtime.log(
    f"模式={self._MODE_LABEL} 当前页面={action.source_page} "
    f"判断依据={action.reason}"
)
self.runtime.log(
    f"模式={self._MODE_LABEL} 操作={action.name} 坐标={action.point} "
    f"目标页面={targets}"
)
```

When the same action returns after its 5-second wait, log:

```python
f"重试={action.name} 原因=原页面仍存在且目标页面未出现 尝试={action_attempts}/4"
```

When `machine._confirmed_page` belongs to the previous action's `target_pages` and the returned action name has changed or become `None`, log:

```python
f"完成={previous.name} 目标页面={machine._confirmed_page}"
```

All modes whose actions lack metadata retain their existing logs and behavior.

- [ ] **Step 5: Run Runner tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::RunnerFlowTests tests/test_runtime_logging.py -q
```

Expected: filter actions use stable two-frame confirmation, five-second retry intervals, one four-attempt ledger, and readable source/target logs; existing runtime logs remain compatible.

- [ ] **Step 6: Commit retry and logging behavior**

```powershell
git add games/epic7/runner_base.py games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "feat: log and retry hero filter transitions"
```

### Task 5: Add the simulator hero black-screen safety guard

**Files:**
- Modify: `games/epic7/runner_base.py`
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing black classifier tests**

Add:

```python
def test_simulator_black_classifier_ignores_legacy_top_padding(self):
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )
    black = np.zeros((1132, 1982, 3), dtype=np.uint8)
    self.assertTrue(runner._is_black_screen(black))

def test_every_recorded_hero_fixture_is_not_black(self):
    runner = HeroSynthRunner(
        machine(),
        Runtime(lambda: None, lambda _: None),
        sleep=lambda _: None,
    )
    for path in FIXTURES.glob("*.png"):
        self.assertFalse(runner._is_black_screen(fixture(path.stem)), path.name)
```

- [ ] **Step 2: Write failing 60-second integration test**

Use a mutable fake clock whose `sleep(seconds)` advances time. Feed only black frames, configure a temporary diagnostic directory, and assert:

```python
with self.assertRaisesRegex(RuntimeError, "黑屏时间过长（60秒）"):
    runner.run(max_cycles=1)
self.assertEqual([], clicks)
self.assertEqual([], wakes)
self.assertEqual([], recoveries)
self.assertTrue(any(tmp_path.glob("*_black_screen_timeout.png")))
```

Add a recovery-within-60-seconds sequence and assert the elapsed black time does not consume the filter action retry timer.

- [ ] **Step 3: Run black tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py -k "black" -q
```

Expected: failure because `HeroSynthRunner` has no black classifier and `ModeRunnerBase` routes black/unknown screens through wake or state recovery.

- [ ] **Step 4: Add opt-in shared Runner hooks**

Add defaults to `ModeRunnerBase`:

```python
_BLACK_SCREEN_TIMEOUT_SECONDS: Optional[float] = None
_BLACK_SCREEN_LOG_INTERVAL_SECONDS = 10.0
_ALLOW_UNKNOWN_SCREEN_WAKE = True

def _is_black_screen(self, screen) -> bool:
    return False
```

At the top of the run loop after capture, handle black before loop detection and state-machine observation. Track `black_started` and `last_black_log_at`. While black:

- reset stable observation;
- never call `_stable_next_action()`, `UnknownScreenWake`, `recovery`, `Runtime.click()`, or `Runtime.back()`;
- log first detection and every 10 elapsed seconds;
- at 60 seconds save `black_screen_timeout` and raise `RuntimeError("黑屏时间过长（60秒），程序已安全停止；已保存诊断 ...")`.

When the image recovers, add the black duration to `state_started`, `absolute_started`, and `last_action_clicked_at` when non-null, then log recovery. Gate the existing `UnknownScreenWake.handle()` call behind `_ALLOW_UNKNOWN_SCREEN_WAKE`.

- [ ] **Step 5: Enable the policy only for simulator hero synthesis**

Add to `HeroSynthRunner`:

```python
_BLACK_SCREEN_TIMEOUT_SECONDS = 60.0
_ALLOW_UNKNOWN_SCREEN_WAKE = False

def _is_black_screen(self, screen: np.ndarray) -> bool:
    if self.machine.templates.pc_client:
        return False
    render = screen[52:] if screen.shape[:2] == (1132, 1982) else screen
    gray = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY)
    return float(gray.mean()) <= 8.0 and float((gray <= 12).mean()) >= 0.985
```

- [ ] **Step 6: Run black tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py -k "black" -q
```

Expected: all black tests pass; no click, wake, or recovery occurs before the explicit 60-second stop.

- [ ] **Step 7: Commit black-screen safety**

```powershell
git add games/epic7/runner_base.py games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: stop simulator hero mode after prolonged black screen"
```

### Task 6: Full offline verification and controlled live handoff

**Files:**
- Modify only directly related files if a regression exposes a defect caused by Tasks 1–5.

- [ ] **Step 1: Run focused hero, PC evidence, Runner, and runtime tests**

```powershell
python -m pytest tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py tests/test_runtime.py tests/test_runtime_logging.py -q
```

Expected: all focused tests pass with zero failures.

- [ ] **Step 2: Run the complete offline suite and compile check**

```powershell
python -m pytest -q
python -m compileall -q .
```

Expected: both commands exit `0`.

- [ ] **Step 3: Review visual-template boundaries and code diff**

Verify the two new crops at original resolution. Run:

```powershell
git diff --check
git status --short
git diff --stat HEAD~4..HEAD
```

Expected: no whitespace errors, no files under `games/epic7/templates_pc/hero/`, and no unrelated changes.

- [ ] **Step 4: Controlled simulator test with irreversible branch disabled**

Start from the simulator hero list. Observe only:

```text
英雄列表 → 打开筛选 → 选择三星 → 关闭筛选 → 确认英雄列表恢复
```

Stop before imprint or transmit actions if the live environment cannot disable them independently. The live log must show source page, reason, action, target, and completion. A swallowed click must repeat only the same action; a black screen must produce no input.
