# Simulator Hero Synthesis Full Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every simulator hero-synthesis click verify its visual source and target, retry only while the source remains, and stop safely after four failed attempts.

**Architecture:** Keep the existing `HeroSynthStateMachine`, `HeroAction`, and shared `ModeRunnerBase`. Extend the transition metadata already proven by the filter flow to list, imprint, synthesis, result, card traversal, and transmit actions; remove optimistic state commits that prevent swallowed-click retries. Simulator-only runner hooks use five-second retries and safe exhaustion while PC behavior remains unchanged.

**Tech Stack:** Python 3.10+, OpenCV, NumPy, unittest/pytest, existing `Runtime`, `StableObservation`, `HeroSynthStateMachine`, and 22 recorded LDPlayer screenshots.

---

### Task 1: Establish page evidence and action-contract test helpers

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing tests for confirmed page labels**

Add `HeroPageEvidenceTests` and assert the exact labels set by representative real fixtures:

```python
class HeroPageEvidenceTests(unittest.TestCase):
    def test_imprint_material_page_sets_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD
        m.next_action(fixture("imprint_up_cards_no_sss"))
        self.assertEqual("刻印加材料", m._confirmed_page)

    def test_synthesis_confirm_sets_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.IMPRINT_ADD
        m.next_action(fixture("synth_confirm"))
        self.assertEqual("合成确认", m._confirmed_page)

    def test_imprint_result_sets_confirmed_page(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("imprint_result_popup"))
        self.assertEqual("合成结果", m._confirmed_page)

    def test_transmit_pages_set_confirmed_page(self):
        m = machine(verify_filter=True)
        m.state = HeroSynthState.TRANSMIT_SELECT
        m.next_action(fixture("transmit_select"))
        self.assertEqual("传送选择", m._confirmed_page)
        m.next_action(fixture("transmit_confirm"))
        self.assertEqual("传送确认", m._confirmed_page)
        m.next_action(fixture("reward_popup"))
        self.assertEqual("传送奖励", m._confirmed_page)
```

- [ ] **Step 2: Run the evidence tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroPageEvidenceTests -q
```

Expected: failures because only simulator filter observations currently maintain `_confirmed_page`.

- [ ] **Step 3: Add one page-confirmation helper and call it only after explicit evidence**

Add:

```python
def _confirm_page(self, label: str) -> None:
    self._confirmed_page = label
```

Call it in the existing branches after their concrete anchors pass:

```python
if self._imprint_result_present(screen):
    self._confirm_page("合成结果")
    ...

if confirm is not None:
    if transmit_ctx or self.state.value.startswith("transmit"):
        self._confirm_page("传送确认")
        ...
    self._confirm_page("合成确认")
    ...

if self.state.value.startswith("transmit") and self._reward_strip_present(screen):
    self._confirm_page("传送奖励")
    ...

if self._locate(screen, "auto_select_label", 0.85):
    self._confirm_page("传送选择")
    ...

if (
    self._sss_material_present(screen)
    and self._green_button_present(screen)
    and self._imprint_slots_present(screen)
):
    self._confirm_page("刻印SSS材料")
elif self._green_button_present(screen) and self._imprint_slots_present(screen):
    self._confirm_page("刻印加材料")
```

Do not assign a label on a partial page that lacks required anchors.

- [ ] **Step 4: Verify page evidence GREEN**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroPageEvidenceTests tests/test_hero_synthesis.py::FilterObservationTests -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit page evidence**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "feat: expose hero synthesis page evidence"
```

### Task 2: Close the hero-list and imprint-entry transition

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing swallowed-click and metadata tests**

Add:

```python
class HeroListTransitionTests(unittest.TestCase):
    def test_open_imprint_retries_while_hero_list_remains(self):
        m = machine(verify_filter=True)
        first = m.next_action(fixture("list_reddot"))
        second = m.next_action(fixture("list_reddot"))
        self.assertEqual("open_imprint", first.name)
        self.assertEqual("open_imprint", second.name)
        self.assertEqual("英雄列表", second.source_page)
        self.assertIn("刻印加材料", second.target_pages)
        self.assertIs(m.state, HeroSynthState.HERO_LIST)

    def test_open_imprint_commits_only_after_imprint_page_appears(self):
        m = machine(verify_filter=True)
        m.next_action(fixture("list_reddot"))
        action = m.next_action(fixture("imprint_up_cards_no_sss"))
        self.assertTrue(action.name.startswith("add_material_"))
        self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)

    def test_next_card_has_source_and_target_contract(self):
        m = machine(verify_filter=True)
        action = settled_next(m, fixture("list_no_reddot"))
        self.assertEqual("英雄列表", action.source_page)
        self.assertEqual(("英雄列表",), action.target_pages)
        self.assertIn("详情指纹", action.reason)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroListTransitionTests -q
```

Expected: `open_imprint` advances to `IMPRINT_ADD` before target evidence, the second action is `None`, and list actions lack metadata.

- [ ] **Step 3: Remove the optimistic imprint state commit**

In both list branches, return `open_imprint` without assigning `IMPRINT_ADD`:

```python
return HeroAction(
    "open_imprint",
    best.center,
    source_page="英雄列表",
    target_pages=("刻印加材料", "刻印SSS材料"),
    reason="当前英雄非SSS且刻印按钮红点存在",
)
```

When a complete imprint page is later recognized, assign `IMPRINT_ADD` before
choosing its material action. This recognition must not depend on the previous
state, so an immediately visible SSS material target is handled safely:

```python
if self._green_button_present(screen) and self._imprint_slots_present(screen):
    self.state = HeroSynthState.IMPRINT_ADD
    if self._sss_material_present(screen):
        self._confirm_page("刻印SSS材料")
    else:
        self._confirm_page("刻印加材料")
```

For the fallback button coordinate, use the same metadata and only change `point`.

- [ ] **Step 4: Add card-traversal metadata without changing its fingerprint algorithm**

Return:

```python
return HeroAction(
    f"next_card_{sig}",
    point,
    source_page="英雄列表",
    target_pages=("英雄列表",),
    reason=f"当前英雄无需合成，详情指纹={fp}，等待下一英雄或列表末尾",
)
```

- [ ] **Step 5: Run list, scale, and full-flow tests**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::HeroListTransitionTests tests/test_hero_synthesis.py::HeroListDecisionTests tests/test_hero_synthesis.py::GuardTests::test_scaled_window_keeps_actions_and_points tests/test_hero_synthesis.py::RunnerFlowTests::test_multi_card_sequence_completes_one_simulator_cycle tests/test_hero_synthesis.py::RunnerFlowTests::test_full_synthesis_flow -q
```

Expected: all selected tests pass and existing click points stay unchanged.

- [ ] **Step 6: Commit list transitions**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify entry into hero imprint"
```

### Task 3: Close material-add, synthesis, result, and return transitions

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing start-synthesis swallowed-click test**

Add:

```python
def test_start_synthesis_retries_while_ready_material_page_remains(self):
    m = machine(verify_filter=True)
    m.state = HeroSynthState.IMPRINT_ADD
    ready = fixture("imprint_added")
    self.assertIsNone(m.next_action(ready))
    first = m.next_action(ready)
    second = m.next_action(ready)
    self.assertEqual("start_synthesis", first.name)
    self.assertEqual("start_synthesis", second.name)
    self.assertIs(m.state, HeroSynthState.IMPRINT_ADD)
    self.assertEqual("刻印加材料", second.source_page)
    self.assertEqual(("合成确认", "合成结果"), second.target_pages)
```

- [ ] **Step 2: Write failing contract tests for all normal synthesis actions**

Add one table-driven test:

```python
def test_normal_synthesis_actions_publish_transition_contracts(self):
    cases = [
        ("imprint_up_cards_no_sss", HeroSynthState.IMPRINT_ADD, "add_material_", "刻印加材料"),
        ("synth_confirm", HeroSynthState.IMPRINT_ADD, "confirm_synthesis", "合成确认"),
        ("imprint_result_popup", HeroSynthState.IMPRINT_CONFIRM, "close_imprint_result", "合成结果"),
        ("imprint_after_synth", HeroSynthState.IMPRINT_REWARD, "back_to_list", "合成后刻印页"),
    ]
    for fixture_name, state, prefix, source in cases:
        with self.subTest(fixture=fixture_name):
            m = machine(verify_filter=True)
            m.state = state
            action = m.next_action(fixture(fixture_name))
            self.assertTrue(action.name.startswith(prefix))
            self.assertEqual(source, action.source_page)
            self.assertTrue(action.target_pages)
            self.assertTrue(action.reason)
```

- [ ] **Step 3: Run synthesis contract tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::ImprintDecisionTests::test_start_synthesis_retries_while_ready_material_page_remains tests/test_hero_synthesis.py::ImprintDecisionTests::test_normal_synthesis_actions_publish_transition_contracts -q
```

Expected: `start_synthesis` changes state optimistically and subsequent recognition raises `UnrecognizedScreen`; other actions lack metadata.

- [ ] **Step 4: Keep start context until its target appears**

Change the ready-to-start branch to leave state at `IMPRINT_ADD`. Keep the
readiness counter at its confirmed threshold until a target page appears, so a
swallowed click immediately returns the same action instead of waiting for two
new source observations:

```python
self._imprint_empty_observations = max(
    self._imprint_empty_observations,
    self._READINESS_OBSERVATIONS,
)
return HeroAction(
    "start_synthesis",
    point,
    source_page="刻印加材料",
    target_pages=("合成确认", "合成结果"),
    reason=f"Up材料已清空，已填槽位={filled_slots}，费用非零，连续确认=2",
)
```

The confirmation-popup observer commits `IMPRINT_CONFIRM` and resets
`_imprint_empty_observations`; the result observer commits `IMPRINT_REWARD` and
also resets it.

- [ ] **Step 5: Add exact contracts to material and normal result actions**

Use these contracts:

```python
HeroAction(
    f"add_material_{filled_slots}_{tag}", point,
    source_page="刻印加材料",
    target_pages=("刻印加材料", "刻印SSS材料"),
    reason=f"发现普通Up材料，已填槽位={filled_slots}，目标={tag}",
)
HeroAction(
    "confirm_synthesis", point,
    source_page="合成确认",
    target_pages=("合成结果",),
    reason="蓝色确认按钮带与金色内容带同时存在",
)
HeroAction(
    "close_imprint_result", point,
    source_page="合成结果",
    target_pages=("合成后刻印页",),
    reason="结果标题与关闭控件同时存在",
)
HeroAction(
    "back_to_list", point,
    source_page="合成后刻印页",
    target_pages=("英雄列表",),
    reason="结果覆盖层消失且刻印页返回箭头存在",
)
```

Set `_confirmed_page="合成后刻印页"` only after the result overlay is absent and the imprint green button plus back arrow are present.

- [ ] **Step 6: Run imprint and full-flow regressions**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::ImprintDecisionTests tests/test_hero_synthesis.py::RunnerFlowTests -q
```

Expected: all selected tests pass, including the existing incomplete-result safety guard.

- [ ] **Step 7: Commit normal synthesis transitions**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify simulator synthesis transitions"
```

### Task 4: Close the SSS abort and transmit branch

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing SSS abort retry test**

Add:

```python
def test_sss_abort_retries_while_same_imprint_page_remains(self):
    m = machine(verify_filter=True)
    m.state = HeroSynthState.IMPRINT_ADD
    first = m.next_action(fixture("imprint_sss_material"))
    second = m.next_action(fixture("imprint_sss_material"))
    self.assertEqual("abort_imprint_to_transmit", first.name)
    self.assertEqual("abort_imprint_to_transmit", second.name)
    self.assertTrue(m.pending_transmit_target)
    self.assertEqual("刻印SSS材料", second.source_page)
    self.assertEqual(("英雄列表",), second.target_pages)
```

- [ ] **Step 2: Write failing transmit contract matrix**

Build actions from the real fixtures and assert these exact contracts:

```python
expected = {
    "open_transmit_for_current_card": ("英雄列表", ("传送选择",)),
    "select_transmit_card_": ("传送选择", ("传送选择",)),
    "start_transmit": ("传送选择", ("传送确认",)),
    "confirm_transmit": ("传送确认", ("传送奖励",)),
    "close_reward": ("传送奖励", ("传送选择", "英雄列表")),
    "abort_transmit_sss_target": ("传送选择", ("英雄列表",)),
}
```

For prefix actions, use `startswith`; assert non-empty `reason` for every action.

- [ ] **Step 3: Run transmit contract tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::ImprintDecisionTests tests/test_hero_synthesis.py::TransmitDecisionTests -q
```

Expected: the repeated SSS source returns `None` and transmit actions have no transition metadata.

- [ ] **Step 4: Reissue the SSS abort while its source remains**

In `IMPRINT_ABORTING`, replace the unconditional wait on a still-recognized SSS material page with:

```python
if self._sss_material_present(screen) and self._green_button_present(screen):
    self._confirm_page("刻印SSS材料")
    back = self._back_action(screen)
    if back is None:
        raise UnrecognizedScreen("发现SSS材料但刻印页面缺少返回箭头")
    return HeroAction(
        "abort_imprint_to_transmit", back.point,
        source_page="刻印SSS材料",
        target_pages=("英雄列表",),
        reason="右侧材料区匹配SSS标记，禁止加入材料",
    )
```

When the list is observed, retain `pending_transmit_target=True` until the transmit page target appears.

- [ ] **Step 5: Add transmit contracts without changing selection rules**

Attach the expected source/target pairs from Step 2 to the existing actions. Use reasons based only on current evidence:

```python
reason="当前副本待传送且英雄列表已恢复"
reason="自动选择标签与右侧高亮目标存在，目标尚未入槽"
reason="自动选择标签、已填传送槽和绿色按钮同时存在"
reason="传送上下文中的蓝色确认按钮带与金色内容带同时存在"
reason="传送状态中识别到奖励条"
reason="右侧高亮传送目标评级为SSS，禁止传送"
```

- [ ] **Step 6: Add a swallowed-click sequence test for every transmit action**

For each stable source fixture, call `next_action()` twice and assert the action name remains the same. For `close_reward`, reset to `TRANSMIT_REWARD` before each independent source probe so tests do not share state.

- [ ] **Step 7: Run the complete SSS path and commit**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py -q
```

Expected: the existing full synthesis flow and SSS-to-transmit flow pass with the new retry assertions.

Commit:

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: verify simulator hero transmit transitions"
```

### Task 5: Apply simulator retry timing and safe exhaustion to all closed-loop actions

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`
- Modify: `tests/test_pc_hero_synthesis_evidence.py`

- [ ] **Step 1: Write failing simulator retry-policy tests**

Add:

```python
def test_all_simulator_transition_actions_retry_after_five_seconds(self):
    runner = HeroSynthRunner(
        machine(), Runtime(lambda: fixture("list_unfiltered"), lambda _: None),
        sleep=lambda _: None,
    )
    names = {
        "open_imprint", "add_material_0_2", "start_synthesis",
        "confirm_synthesis", "close_imprint_result", "back_to_list",
        "abort_imprint_to_transmit", "open_transmit_for_current_card",
        "select_transmit_card_0", "start_transmit", "confirm_transmit",
        "close_reward", "abort_transmit_sss_target",
    }
    self.assertEqual({5}, {runner._action_retry_seconds(name) for name in names})
    self.assertEqual(10, runner._action_retry_seconds("next_card_XN12345678"))
```

- [ ] **Step 2: Write a failing four-click safe-stop test**

Use `FakeClock`, a repeated `list_reddot` source, a recovery spy, and diagnostic-capable `Runtime`. Assert exactly four clicks, zero recovery calls, and an error containing the action, source, target, and saved diagnostic path.

```python
self.assertEqual(4, len(clicks))
self.assertEqual([], recoveries)
self.assertIn("open_imprint", str(error.exception))
self.assertIn("英雄列表", str(error.exception))
self.assertIn("刻印加材料", str(error.exception))
```

- [ ] **Step 3: Run retry tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py::RunnerFlowTests::test_all_simulator_transition_actions_retry_after_five_seconds tests/test_hero_synthesis.py::RunnerFlowTests::test_four_failed_simulator_transition_clicks_stop_without_recovery tests/test_pc_hero_synthesis_evidence.py::test_pc_runner_keeps_legacy_filter_retry_interval tests/test_pc_hero_synthesis_evidence.py::test_pc_close_filter_remains_an_instant_action -q
```

Expected: normal simulator actions still use 45 seconds and exhausted actions attempt recovery.

- [ ] **Step 4: Define the simulator closed-loop action set**

Add:

```python
_SIMULATOR_CLOSED_LOOP_ACTIONS = {
    "open_filter", "select_star3", "close_filter", "open_imprint",
    "start_synthesis", "confirm_synthesis", "close_imprint_result",
    "back_to_list", "abort_imprint_to_transmit",
    "open_transmit_for_current_card", "start_transmit", "confirm_transmit",
    "close_reward", "abort_transmit_sss_target",
}
```

In `_action_retry_seconds`, use five seconds for this set and the `add_material_` / `select_transmit_card_` prefixes only when `pc_client` is false. Keep `next_card_*` at ten seconds and keep every PC value unchanged.

- [ ] **Step 5: Override action exhaustion for simulator hero mode**

Implement:

```python
def _on_action_exhausted(self, action: HeroAction, screen) -> bool:
    if self.machine.templates.pc_client:
        return False
    diagnostic = self.runtime.save_diagnostic(
        f"retry_exhausted_{action.name}", screen
    )
    targets = "/".join(action.target_pages) or "未声明"
    raise RuntimeError(
        f"动作{action.name}点击4次后仍停在{action.source_page or self._state_label(self.machine.state)}；"
        f"未到达{targets}；程序已安全停止并保存诊断 {diagnostic}"
    )
```

- [ ] **Step 6: Verify simulator and PC policies**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py -q
```

Expected: all pass; PC retains 45-second legacy filter retries and instant close behavior.

- [ ] **Step 7: Commit runner policy**

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py
git commit -m "fix: stop exhausted simulator hero transitions safely"
```

### Task 6: Complete product logs and end-to-end offline flows

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Write failing log coverage tests**

Drive the normal synthesis fixtures through a `HeroSynthRunner` with `FakeClock` and assert the combined output includes:

```python
for text in (
    "当前页面=英雄列表",
    "操作=open_imprint",
    "目标页面=刻印加材料/刻印SSS材料",
    "当前页面=刻印加材料",
    "操作=start_synthesis",
    "目标页面=合成确认/合成结果",
    "当前页面=合成确认",
    "目标页面=合成结果",
    "当前页面=合成结果",
    "目标页面=合成后刻印页",
    "目标页面=英雄列表",
):
    self.assertIn(text, output)
```

Drive the SSS transmit path and require page/action/target entries for SSS abort, transmit selection, confirmation, reward, and return.

- [ ] **Step 2: Run log tests and verify RED**

Expected: filter logs pass but non-filter actions are missing source/target lines.

- [ ] **Step 3: Fill only missing decision hints**

Extend `_decision_hint` for material and transmit actions:

```python
if action_name.startswith("add_material"):
    return "识别到普通Up材料 → 加入下一个空槽"
if action_name.startswith("select_transmit_card"):
    return "传送目标高亮但尚未入槽 → 选择当前副本"
if action_name == "start_transmit":
    return "传送目标已入槽且绿色按钮可用 → 打开传送确认"
if action_name == "confirm_transmit":
    return "传送确认弹窗证据完整 → 确认传送"
if action_name == "close_reward":
    return "传送奖励已出现 → 关闭奖励并返回"
```

Do not duplicate source/target text already emitted from `HeroAction` metadata.

- [ ] **Step 4: Add one normal and one SSS end-to-end transition assertion**

Keep the existing fixture order, but additionally assert every emitted action has non-empty `source_page`, `target_pages`, and `reason`, except a final no-action cycle completion.

- [ ] **Step 5: Update architecture documentation**

In the hero synthesis section of `docs/ARCHITECTURE.md`, document:

```text
模拟器英雄合成的筛选、刻印、合成、遍历和传送动作均使用来源/目标视觉契约。
只有目标截图出现才推进；来源仍在才重试；未知帧不点击；四次失败或黑屏60秒安全停止。
PC 保持独立模板与既有动作节奏。
```

- [ ] **Step 6: Run focused regression and commit**

Run:

```powershell
python -m pytest tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py tests/test_runtime_logging.py -q
git diff --check
```

Expected: all selected tests pass and diff check is clean.

Commit:

```powershell
git add games/epic7/hero_synthesis.py tests/test_hero_synthesis.py docs/ARCHITECTURE.md
git commit -m "feat: explain full simulator hero transitions"
```

### Task 7: Independent review and final verification

**Files:**
- Review: `games/epic7/hero_synthesis.py`
- Review: `games/epic7/runner_base.py`
- Review: `tests/test_hero_synthesis.py`
- Review: `tests/test_pc_hero_synthesis_evidence.py`
- Review: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Run the full test suite**

```powershell
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run static and repository checks**

```powershell
python -m compileall -q .
git diff --check main...HEAD
git status --short
```

Expected: compile and diff checks exit zero; status is empty.

- [ ] **Step 3: Verify asset and PC boundaries**

```powershell
git diff --name-only main...HEAD -- games/epic7/templates_pc
python -c "from pathlib import Path; import cv2; p=Path('games/epic7/templates/hero'); print({n: cv2.imread(str(p/n)).shape[:2] for n in ['filter_attribute_label.png','filter_star3_selected.png','filter_star3_unselected.png','sss_material.png']})"
```

Expected: PC template diff is empty; simulator templates remain tight crops.

- [ ] **Step 4: Request independent code review**

Review against the design spec with priority on:

- optimistic state commits after clicks;
- actions that can disappear instead of retrying when their source remains;
- unknown frames accidentally resetting the retry ledger;
- simulator policy leaking into PC;
- irreversible synthesis/transmit actions lacking two independent visual anchors;
- logs that claim completion before target evidence.

- [ ] **Step 5: Reproduce and fix every accepted review finding with TDD**

For each accepted finding: add a focused failing regression, verify RED, implement the minimum fix, verify GREEN, and commit. Do not change unrelated modes.

- [ ] **Step 6: Repeat final verification after review fixes**

Re-run Step 1 through Step 3. Record exact pass counts and final commit IDs. Do not run `--live` and do not control the emulator.
