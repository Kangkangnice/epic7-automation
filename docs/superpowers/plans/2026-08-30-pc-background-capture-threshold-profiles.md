# PC Background Capture and Threshold Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the PC client capture valid live frames while covered, minimize focus stealing during input, and isolate PC visual thresholds without changing emulator defaults or duplicating business logic.

**Architecture:** `Epic7PcWindow` will use client-DC `BitBlt` first and retain the current foreground desktop screenshot as a fallback. Formal Epic7 evidence builders will merge stable emulator defaults with sparse PC overrides selected by an explicit backend propagated from `main.py`; state machines, coordinates, templates, and transitions stay shared.

**Tech Stack:** Python 3.10, ctypes/User32/GDI32, NumPy, OpenCV, pytest.

---

### Task 1: PC background capture and focus restoration

**Files:**
- Modify: `core/pc_window.py`
- Test: `tests/test_pc_window.py`

- [ ] **Step 1: Write failing tests for capture selection**

Add tests that patch `_capture_client_bitblt()` to return a real `1920x1080` NumPy frame. Assert `capture()` calls `_find_window()` and `_validated_rect()` but never calls `activate()` or `pyautogui.screenshot`. Add a second test returning `None`; assert it activates once and uses the existing desktop screenshot fallback.

```python
def test_capture_uses_background_bitblt_without_activation(self):
    frame = np.full((1080, 1920, 3), 127, dtype=np.uint8)
    with patch.object(self.game, "_find_window", return_value=123), \
         patch.object(self.game, "_validated_rect", return_value=WindowRect(10, 20, 1920, 1080)), \
         patch.object(self.game, "_capture_client_bitblt", return_value=frame), \
         patch.object(self.game, "activate") as activate, \
         patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot:
        canvas = self.game.capture()
    activate.assert_not_called()
    screenshot.assert_not_called()
    np.testing.assert_array_equal(frame, canvas[52:, :1920])
```

- [ ] **Step 2: Run the new capture tests and verify RED**

Run: `pytest -q tests/test_pc_window.py -k "background_bitblt or falls_back"`

Expected: FAIL because `_capture_client_bitblt` does not exist and `capture()` always activates.

- [ ] **Step 3: Implement the minimal BitBlt path**

Add `_capture_client_bitblt(hwnd) -> np.ndarray | None` using `GetDC`, `CreateCompatibleDC`, `CreateCompatibleBitmap`, `BitBlt(SRCCOPY | CAPTUREBLT)`, and `GetDIBits`. Release every GDI object in `finally`. Return RGB pixels only when the API succeeds and `std >= 1.0`; otherwise return `None`.

Update `capture()`:

```python
hwnd = self._find_window()
self._validated_rect(hwnd)
frame = self._capture_client_bitblt(hwnd)
if frame is None:
    hwnd = self.activate()
    rect = self._validated_rect(hwnd)
    frame = np.asarray(pyautogui.screenshot(region=(...)).convert("RGB"))
return self._legacy_canvas(frame)
```

- [ ] **Step 4: Write and verify RED focus-restoration tests**

For `click()` and `back()`, make `GetForegroundWindow()` initially return `999`, patch `activate()` to return game handle `123`, and assert `SetForegroundWindow(999)` occurs after `_send_click()` or `pyautogui.press("esc")`. Add cases where the initial foreground is already `123` and assert no restoration call.

Run: `pytest -q tests/test_pc_window.py -k "restore"`

Expected: FAIL because current input leaves the game in front.

- [ ] **Step 5: Implement focus restoration and run PC adapter tests**

Add a best-effort helper that restores only a nonzero, non-game, still-valid previous handle. Wrap click/back input in `try/finally`; restoration must never repeat the game input or hide an input exception.

Run: `pytest -q tests/test_pc_window.py tests/test_desktop_preflight.py`

Expected: PASS.

### Task 2: Split stable defaults from PC threshold overrides

**Files:**
- Modify: `games/epic7/evidence/story.py`
- Modify: `games/epic7/evidence/arena.py`
- Modify: `games/epic7/evidence/expedition.py`
- Modify: `games/epic7/evidence/hero_synthesis.py`
- Test: `tests/test_story_evidence.py`
- Test: `tests/test_arena_evidence.py`
- Test: `tests/test_hero_synthesis.py`
- Test: `tests/test_epic7_expedition.py`

- [ ] **Step 1: Write failing profile tests**

For each formal route, construct the profile twice and assert the default/emulator values remain the stable pre-PC values while PC receives sparse overrides. Required examples:

```python
assert build_story_evidence(TEMPLATES).atom("skip").threshold == 0.65
assert build_story_evidence(TEMPLATES, backend="pc").atom("skip").threshold == 0.55
assert build_arena_evidence(TEMPLATES).atom("battle_start").threshold == 0.85
assert build_arena_evidence(TEMPLATES, backend="pc").atom("battle_start").threshold == 0.70
assert build_hero_evidence(TEMPLATES).atom("filter_level_label").threshold == 0.75
assert build_hero_evidence(TEMPLATES, backend="pc").atom("filter_level_label").threshold == 0.65
```

Expedition must accept `backend="pc"` but initially produce the same values because there is no confirmed PC override.

- [ ] **Step 2: Run profile tests and verify RED**

Run: `pytest -q tests/test_story_evidence.py tests/test_arena_evidence.py tests/test_hero_synthesis.py tests/test_epic7_expedition.py -k "threshold or profile"`

Expected: FAIL because story/hero builders have no backend and their shared defaults are currently PC-lowered.

- [ ] **Step 3: Implement per-backend threshold merging**

In every evidence module, retain `THRESHOLDS` as the emulator baseline, add `PC_THRESHOLD_OVERRIDES`, and merge through one small local function:

```python
def thresholds_for(backend: str) -> dict[str, float]:
    values = dict(THRESHOLDS)
    if backend == "pc":
        values.update(PC_THRESHOLD_OVERRIDES)
    return values
```

Restore simulator defaults from the last committed baseline. Put only the already recorded PC-lowered values into PC overrides. Keep `rating_sss` and `sss_material` at their current safety values on both platforms.

The profile values to preserve are explicit:

```python
# story
PC_THRESHOLD_OVERRIDES = {
    "watch_story": 0.70,
    "prepare_battle": 0.80,
    "skip": 0.55,
    "skip_confirm": 0.70,
    "battle_guide_title": 0.75,
    "battle_guide_dont_show": 0.75,
    "auto_off": 0.70,
    "auto_on": 0.70,
    "select_team": 0.65,
}
PC_DEFAULT_THRESHOLD = 0.70

# arena
PC_THRESHOLD_OVERRIDES = {
    "list_ready": 0.75,
    "challenge": 0.85,
    "battle_start": 0.70,
    "auto_off": 0.80,
    "confirm": 0.85,
    "no_ticket": 0.85,
    "friendship_ticket_offer": 0.87,
    "ticket_purchase_button": 0.87,
}

# hero synthesis
PC_THRESHOLD_OVERRIDES = {
    "filter_button": 0.70,
    "filter_level_label": 0.65,
    "filter_attribute_label": 0.65,
    "filter_star3_selected": 0.80,
    "filter_star3_unselected": 0.76,
    "auto_select_label": 0.65,
    "story_back": 0.80,
    "sss_material_warning_title": 0.72,
    "sss_material_warning_close": 0.72,
    "imprint_result_title": 0.72,
    "imprint_result_close": 0.68,
    "transmit_reward_title": 0.80,
    "transmit_reward_close": 0.70,
}
PC_DEFAULT_THRESHOLD = 0.70
```

The story PC default applies to atoms that currently inherit `0.70` such as `prepare_battle_updated`, `start_mission`, result and stamina anchors. The hero PC default applies only where the current implementation inherited `0.70`. Non-template visual limits changed during PC tuning must also be split: hero button structure uses emulator `0.50` and PC `0.40`; the small attribute anchor uses emulator `0.75` and PC `0.65`. Arena helper-mask matching uses emulator `0.90` and PC `0.85`, and the generic template default uses emulator `0.98` and PC `0.93`.

- [ ] **Step 4: Run profile tests and verify GREEN**

Run the same command as Step 2.

Expected: PASS.

### Task 3: Propagate backend without enabling old PC business branches

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/expedition.py`
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `games/epic7/navigation.py`
- Modify: `games/epic7/modes.py`
- Modify: `main.py`
- Test: `tests/test_main_story.py`
- Test: `tests/test_navigation.py`
- Test: `tests/test_quick_battle_route_integration.py`
- Test: `tests/test_hero_synthesis.py`

- [ ] **Step 1: Write failing construction tests**

Assert that `MODE_SPECS[mode].build_machine(..., "pc")` installs PC evidence thresholds for story, arena, expedition, and hero synthesis. For hero synthesis also assert `machine.templates.pc_client is False`, proving backend selection does not reactivate obsolete coordinates.

Add a navigator construction test asserting PC navigation passes the PC story/arena helper thresholds while emulator keeps its defaults.

- [ ] **Step 2: Run construction tests and verify RED**

Run: `pytest -q tests/test_main_story.py tests/test_navigation.py tests/test_quick_battle_route_integration.py tests/test_hero_synthesis.py -k "backend or threshold or pc_client"`

Expected: FAIL for story/hero/expedition profile propagation and navigation helper thresholds.

- [ ] **Step 3: Thread explicit backend through builders**

Add `backend="emulator"` to the four template/evidence builders and formal state machines where needed. `main.py` already supplies `window_backend` to the mode factory; extend navigator creation to receive the same backend.

Change story and arena shared helper functions to accept an optional explicit threshold. State machines and navigator pass the selected profile value rather than relying on a globally lowered literal.

For hero synthesis call `build_hero_templates(template_root, backend=backend)` but keep `pc_client=False`; backend only selects evidence thresholds.

- [ ] **Step 4: Run formal route integration tests**

Run: `pytest -q tests/test_main_story.py tests/test_navigation.py tests/test_epic7_story.py tests/test_epic7_arena.py tests/test_epic7_expedition.py tests/test_hero_synthesis.py tests/test_quick_battle_route_integration.py`

Expected: PASS.

### Task 4: Evidence matrix, live probe, and complete regression

**Files:**
- Modify only if a failing test identifies a defect directly caused by Tasks 1-3.
- Update: `docs/PC_TEMPLATE_MIGRATION.md`

- [ ] **Step 1: Verify PC foreground/background capture equivalence**

With the PC client open at a stable page, capture once in front and once while covered. Feed both compatible canvases to `Epic7Navigator.observe()` and record page/confidence. Both must classify the same page; current lobby baseline is approximately `0.874-0.875`.

- [ ] **Step 2: Run dual-platform fixture regression**

Run: `pytest -q tests/test_pc_window.py tests/test_story_evidence.py tests/test_arena_evidence.py tests/test_epic7_arena.py tests/test_epic7_story.py tests/test_epic7_expedition.py tests/test_hero_synthesis.py tests/test_navigation.py tests/test_quick_battle_route_integration.py`

Expected: PASS, including the PC arena team fixture and emulator route fixtures.

- [ ] **Step 3: Run the complete suite**

Run: `pytest -q`

Expected: no failures. Record the exact passed/skipped/subtest counts.

- [ ] **Step 4: Update migration documentation**

Record the proven capture matrix (`PrintWindow` failed, BitBlt succeeded in foreground/background, `PostMessage` input failed), the sparse override rule, and the remaining requirement for one administrator-level PC live route run.

- [ ] **Step 5: Commit only the files belonging to this implementation**

Review `git diff --check`, stage the exact implementation/test/document files, and do not stage unrelated existing work.
