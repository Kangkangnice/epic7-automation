# PC Strict Background Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC capture and already-correct startup checks never foreground the game, while limiting foreground changes to real input and logging whether focus restoration succeeded.

**Architecture:** Keep all behavior inside `Epic7PcWindow`; routes and visual thresholds remain unchanged. `capture()` becomes strict background-only, `ensure_render_size()` reads geometry before deciding whether activation is necessary, and input emits evidence through a small callback attached to `Runtime.log` after runtime construction.

**Tech Stack:** Python 3, ctypes/Win32, NumPy, unittest.mock, pytest

---

### Task 1: Make PC capture strictly background-only

**Files:**
- Modify: `tests/test_pc_window.py:99-214`
- Modify: `core/pc_window.py:301-311`

- [ ] **Step 1: Replace the foreground-fallback test with a failing strict-background test**

```python
def test_capture_stops_without_activation_when_bitblt_fails(self):
    with (
        patch.object(self.game, "_find_window", return_value=123),
        patch.object(
            self.game,
            "_validated_rect",
            return_value=WindowRect(10, 20, 1920, 1080),
        ),
        patch.object(self.game, "_capture_client_bitblt", return_value=None),
        patch.object(self.game, "activate") as activate,
        patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
    ):
        with self.assertRaisesRegex(RuntimeError, "PC 后台截图失败"):
            self.game.capture()

    activate.assert_not_called()
    screenshot.assert_not_called()
```

Delete the now-duplicate `test_capture_does_not_screenshot_when_foreground_confirmation_fails`, because strict capture no longer reaches foreground confirmation.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest -q tests/test_pc_window.py::PcWindowSafetyTests::test_capture_stops_without_activation_when_bitblt_fails`

Expected: FAIL because current `capture()` calls `activate()` and does not raise the strict-background error.

- [ ] **Step 3: Remove the foreground screenshot fallback**

```python
def capture(self) -> np.ndarray:
    hwnd = self._find_window()
    self._validated_rect(hwnd)
    frame = self._capture_client_bitblt(hwnd)
    if frame is None:
        raise RuntimeError(
            "PC 后台截图失败；为避免抢占前台已安全停止。"
            "请保持游戏窗口未最小化后重试"
        )
    return self._legacy_canvas(frame)
```

Do not change emulator capture fallback in `core/window.py`.

- [ ] **Step 4: Run capture tests and verify GREEN**

Run: `pytest -q tests/test_pc_window.py -k "capture"`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the isolated capture change**

```powershell
git add -- core/pc_window.py tests/test_pc_window.py
git commit -m "fix: keep PC capture strictly in background"
```

### Task 2: Avoid activation when render size is already correct

**Files:**
- Modify: `tests/test_pc_window.py:25-97`
- Modify: `core/pc_window.py:249-283`

- [ ] **Step 1: Tighten the exact-size test to prove activation is absent**

```python
def test_ensure_render_size_skips_activation_when_client_is_already_exact(self):
    exact = WindowRect(10, 20, 1920, 1080)
    self.game._user32 = MagicMock()
    with (
        patch.object(self.game, "_find_window", return_value=123),
        patch.object(self.game, "activate") as activate,
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(self.game, "_rect", return_value=exact),
    ):
        result = self.game.ensure_render_size()

    self.assertEqual(pc_window.WindowCalibration(exact, exact, False), result)
    activate.assert_not_called()
    self.game._user32.SetWindowPos.assert_not_called()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/test_pc_window.py::PcWindowSafetyTests::test_ensure_render_size_skips_activation_when_client_is_already_exact`

Expected: FAIL because current `ensure_render_size()` activates before reading the client size.

- [ ] **Step 3: Read geometry before activation and activate only for resizing**

```python
def ensure_render_size(self) -> WindowCalibration:
    hwnd = self._find_window()
    self._ensure_input_allowed(hwnd)
    before = self._rect(hwnd)
    if (before.width, before.height) == RENDER_SIZE:
        return WindowCalibration(before, before, False)

    previous_foreground = self._user32.GetForegroundWindow()
    try:
        hwnd = self.activate()
        outer = self._outer_rect(hwnd)
        target_outer_width = RENDER_SIZE[0] + outer.width - before.width
        target_outer_height = RENDER_SIZE[1] + outer.height - before.height
        if not self._user32.SetWindowPos(
            hwnd,
            0,
            outer.left,
            outer.top,
            target_outer_width,
            target_outer_height,
            _SWP_NOZORDER | _SWP_NOACTIVATE,
        ):
            error = ctypes.get_last_error()
            raise RuntimeError(
                f"PC 游戏窗口调整失败：当前={before.width}x{before.height} "
                f"目标={RENDER_SIZE[0]}x{RENDER_SIZE[1]} Win32错误码={error}"
            )

        after = before
        for _ in range(10):
            sleep(0.1)
            after = self._rect(hwnd)
            if (after.width, after.height) == RENDER_SIZE:
                return WindowCalibration(before, after, True)
        raise RuntimeError(
            f"PC 游戏窗口调整未生效：调整前={before.width}x{before.height} "
            f"目标={RENDER_SIZE[0]}x{RENDER_SIZE[1]} "
            f"调整后实际仍为 {after.width}x{after.height}"
        )
    finally:
        self._restore_foreground(previous_foreground, hwnd)
```

- [ ] **Step 4: Update resize tests to expect activation and restoration only for wrong sizes**

Replace the successful resize test arrangement with:

```python
self.game._user32.GetForegroundWindow.return_value = 999
with (
    patch.object(self.game, "_find_window", return_value=123),
    patch.object(self.game, "activate", return_value=123) as activate,
    patch.object(self.game, "_restore_foreground", return_value=True) as restore,
    patch.object(self.game, "_ensure_input_allowed"),
    patch.object(self.game, "_rect", side_effect=[before, after]),
    patch.object(self.game, "_outer_rect", return_value=outer),
    patch("auto_game_unified.core.pc_window.sleep"),
):
    result = self.game.ensure_render_size()

activate.assert_called_once_with()
restore.assert_called_once_with(999, 123)
```

For the denied-resize test, use this complete call and assertion block after its existing `before` and mocked `SetWindowPos.return_value = 0` setup:

```python
self.game._user32.GetForegroundWindow.return_value = 999
with (
    patch.object(self.game, "_find_window", return_value=123),
    patch.object(self.game, "activate", return_value=123) as activate,
    patch.object(self.game, "_restore_foreground", return_value=True) as restore,
    patch.object(self.game, "_ensure_input_allowed"),
    patch.object(self.game, "_rect", return_value=before),
    patch.object(
        self.game,
        "_outer_rect",
        return_value=WindowRect(139, 236, 1306, 791),
    ),
    patch("auto_game_unified.core.pc_window.ctypes.get_last_error", return_value=5),
):
    with self.assertRaisesRegex(RuntimeError, "Win32错误码=5"):
        self.game.ensure_render_size()

activate.assert_called_once_with()
restore.assert_called_once_with(999, 123)
```

In `test_ensure_render_size_stops_when_resize_does_not_reach_target`, use `_rect` side effect `[before] * 12`, add `patch.object(self.game, "_restore_foreground", return_value=True) as restore`, and assert `restore.assert_called_once_with(999, 123)` after the `assertRaisesRegex` block.

- [ ] **Step 5: Run calibration and preflight tests**

Run: `pytest -q tests/test_pc_window.py -k "ensure_render_size" tests/test_desktop_preflight.py`

Expected: all selected tests pass; PC preflight behavior remains unchanged except that an exact-size client is not foregrounded.

- [ ] **Step 6: Commit the isolated calibration change**

```powershell
git add -- core/pc_window.py tests/test_pc_window.py
git commit -m "fix: avoid PC activation during size checks"
```

### Task 3: Record input foreground and restoration results

**Files:**
- Modify: `tests/test_pc_window.py:233-355`
- Modify: `tests/test_main_story.py:124-158`
- Modify: `core/pc_window.py:109-120,384-448`
- Modify: `main.py:83-118`

- [ ] **Step 1: Add failing tests for evidence and restoration status**

```python
def test_click_logs_successful_focus_restore(self):
    events = []
    game = Epic7PcWindow(event_sink=events.append)
    game._user32 = MagicMock()
    game._user32.GetForegroundWindow.side_effect = [999, 999]
    game._user32.IsWindow.return_value = 1
    game._user32.SetForegroundWindow.return_value = 1
    with (
        patch.object(game, "_find_window", return_value=123),
        patch.object(game, "activate", return_value=123),
        patch.object(game, "_ensure_input_allowed"),
        patch.object(game, "_validated_rect", return_value=WindowRect(10, 20, 1920, 1080)),
        patch.object(game, "_send_click"),
        patch.object(game, "_restore_foreground", return_value=True),
    ):
        game.click((991, 566))

    self.assertIn("类型=点击", events[-1])
    self.assertIn("恢复原窗口=成功", events[-1])


def test_click_logs_failed_focus_restore(self):
    events = []
    game = Epic7PcWindow(event_sink=events.append)
    game._user32 = MagicMock()
    game._user32.GetForegroundWindow.return_value = 999
    with (
        patch.object(game, "_find_window", return_value=123),
        patch.object(game, "activate", return_value=123),
        patch.object(game, "_ensure_input_allowed"),
        patch.object(game, "_validated_rect", return_value=WindowRect(10, 20, 1920, 1080)),
        patch.object(game, "_send_click"),
        patch.object(game, "_restore_foreground", return_value=False),
    ):
        game.click((991, 566))

    self.assertIn("类型=点击", events[-1])
    self.assertIn("恢复原窗口=失败", events[-1])


def test_back_logs_successful_focus_restore(self):
    events = []
    game = Epic7PcWindow(event_sink=events.append)
    game._user32 = MagicMock()
    game._user32.GetForegroundWindow.return_value = 999
    with (
        patch.object(game, "_find_window", return_value=123),
        patch.object(game, "activate", return_value=123),
        patch.object(game, "_ensure_input_allowed"),
        patch.object(game, "_restore_foreground", return_value=True),
        patch("auto_game_unified.core.pc_window.pyautogui.press"),
    ):
        game.back()

    self.assertIn("类型=返回", events[-1])
    self.assertIn("恢复原窗口=成功", events[-1])
```

- [ ] **Step 2: Run the new logging tests and verify RED**

Run: `pytest -q tests/test_pc_window.py -k "logs_successful_focus_restore or logs_failed_focus_restore"`

Expected: FAIL because `event_sink` and restoration-result logging do not exist.

- [ ] **Step 3: Add a minimal event callback and make restoration return evidence**

```python
def __init__(
    self,
    reference_size: tuple[int, int] = REFERENCE_SIZE,
    sleep_fn: Callable[[float], None] = sleep,
    event_sink: Callable[[str], None] | None = None,
) -> None:
    self.reference_size = reference_size
    self._sleep = sleep_fn
    self._event_sink = event_sink
    self._user32 = ctypes.WinDLL("user32", use_last_error=True)

def set_event_sink(self, sink: Callable[[str], None] | None) -> None:
    self._event_sink = sink

def _emit(self, message: str) -> None:
    if self._event_sink is not None:
        self._event_sink(message)

def _restore_foreground(self, previous_hwnd, game_hwnd) -> bool:
    if not previous_hwnd or previous_hwnd == game_hwnd:
        return True
    if not self._user32.IsWindow(previous_hwnd):
        return False
    try:
        return bool(self._user32.SetForegroundWindow(previous_hwnd))
    except Exception:
        return False
```

Replace `click()` with this evidence pattern:

```python
previous_foreground = self._user32.GetForegroundWindow()
hwnd = self._find_window()
succeeded = False
restore_label = "无需" if previous_foreground == hwnd else "失败"
try:
    self.activate()
    self._ensure_input_allowed(hwnd)
    rect = self._validated_rect(hwnd)
    render_point = point[0], point[1] - LEGACY_TOP
    if not (
        0 <= render_point[0] < RENDER_SIZE[0]
        and 0 <= render_point[1] < RENDER_SIZE[1]
    ):
        raise RuntimeError(f"拒绝在 PC 游戏渲染区外点击：{point}")
    self._send_click((rect.left + render_point[0], rect.top + render_point[1]))
    succeeded = True
finally:
    if previous_foreground != hwnd:
        restore_label = (
            "成功" if self._restore_foreground(previous_foreground, hwnd) else "失败"
        )
    self._emit(
        f"模式=PC输入 类型=点击 原前台={previous_foreground} "
        f"游戏窗口={hwnd} 结果={'成功' if succeeded else '失败'} "
        f"恢复原窗口={restore_label}"
    )
```

Replace `back()` with:

```python
def back(self) -> None:
    previous_foreground = self._user32.GetForegroundWindow()
    hwnd = self._find_window()
    succeeded = False
    restore_label = "无需" if previous_foreground == hwnd else "失败"
    try:
        self.activate()
        self._ensure_input_allowed(hwnd)
        pyautogui.press("esc")
        succeeded = True
    finally:
        if previous_foreground != hwnd:
            restore_label = (
                "成功"
                if self._restore_foreground(previous_foreground, hwnd)
                else "失败"
            )
        self._emit(
            f"模式=PC输入 类型=返回 原前台={previous_foreground} "
            f"游戏窗口={hwnd} 结果={'成功' if succeeded else '失败'} "
            f"恢复原窗口={restore_label}"
        )
```

The `finally` blocks preserve and re-raise the original activation/input exceptions.

- [ ] **Step 4: Attach the PC input event sink to route logging**

Immediately after `Runtime(...)` construction in `_build_runtime`:

```python
if window_backend == "pc":
    game_window.set_event_sink(runtime.log)
```

Extend `test_build_runtime_selects_pc_window_and_calibrates_it` to assert `set_event_sink` is called with `runtime.log`.

- [ ] **Step 5: Run PC window and runtime-construction tests**

Run: `pytest -q tests/test_pc_window.py tests/test_main_story.py tests/test_desktop_preflight.py`

Expected: all tests pass.

- [ ] **Step 6: Commit input evidence wiring**

```powershell
git add -- core/pc_window.py main.py tests/test_pc_window.py tests/test_main_story.py
git commit -m "feat: log PC foreground input transitions"
```

### Task 4: Update maintenance documentation and verify regressions

**Files:**
- Modify: `docs/PC_TEMPLATE_MIGRATION.md:1-195`
- Test: `tests/test_pc_window.py`
- Test: `tests/test_desktop_preflight.py`
- Test: full `tests/`

- [ ] **Step 1: Update the operator-facing behavior contract**

Document these exact statements in `docs/PC_TEMPLATE_MIGRATION.md`:

```markdown
- PC 窗口可以被其他窗口覆盖，但不要最小化。
- 截图永不前置；后台截图失败会安全停止。
- 客户区已经是 1920×1080 时，检测环境和启动任务不前置。
- 点击和 Esc 会短暂前置；日志会记录恢复原窗口是否成功。
```

Remove the obsolete statement that capture falls back to foreground desktop screenshots.

- [ ] **Step 2: Run focused regression tests**

Run: `pytest -q tests/test_pc_window.py tests/test_desktop_preflight.py tests/test_main_story.py`

Expected: all tests pass.

- [ ] **Step 3: Run formal-route regression tests**

Run: `pytest -q tests/test_main_story.py tests/test_navigation.py tests/test_epic7_story.py tests/test_epic7_arena.py tests/test_epic7_expedition.py tests/test_hero_synthesis.py tests/test_quick_battle_route_integration.py tests/test_modes.py`

Expected: all tests pass; no platform threshold or business-state regressions.

- [ ] **Step 4: Run the full suite and diff validation**

Run: `pytest -q`

Expected: zero failures.

Run: `git diff --check`

Expected: exit code `0`; line-ending warnings are acceptable, whitespace errors are not.

- [ ] **Step 5: Perform the short PC live validation when the user reopens PC**

Record the foreground HWND before and after each probe:

1. Put another application in front of the non-minimized PC game.
2. Call `capture()` five times; every frame must be non-black and the foreground HWND must remain unchanged.
3. Run one allowed click from the desktop assistant; log must show `类型=点击` and `恢复原窗口=成功` or an explicit failure.
4. Confirm the original application regains focus after the click.

Do not claim PC foreground behavior is fully validated until this live step is complete.

- [ ] **Step 6: Commit documentation after verification**

```powershell
git add -- docs/PC_TEMPLATE_MIGRATION.md
git commit -m "docs: explain PC background operation limits"
```
