# PC Window Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Epic Seven PC window backend fail closed when the target window is not foreground or its client area cannot preserve the reference coordinate system.

**Architecture:** Keep all game state machines and template matching unchanged. `Epic7PcWindow` becomes responsible for foreground confirmation before every desktop screenshot, mouse click, and Escape key action; it rejects client areas whose aspect ratio is incompatible with the `1982×1132` reference frame.

**Tech Stack:** Python 3.10, ctypes/User32, PyAutoGUI, NumPy, unittest/pytest.

---

### Task 1: Characterize the PC backend safety boundary

**Files:**
- Create: `tests/test_pc_window.py`
- Modify: none

- [x] **Step 1: Write the failing tests**

```python
def test_capture_does_not_screenshot_when_foreground_confirmation_fails(self):
    with patch.object(game, "activate", side_effect=RuntimeError("PC 游戏窗口未能置前")):
        with self.assertRaisesRegex(RuntimeError, "未能置前"):
            game.capture()

def test_click_does_not_send_desktop_input_when_foreground_confirmation_fails(self):
    with patch.object(game, "activate", side_effect=RuntimeError("PC 游戏窗口未能置前")):
        with self.assertRaisesRegex(RuntimeError, "未能置前"):
            game.click((991, 566))
    click.assert_not_called()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q tests/test_pc_window.py`

Expected: FAIL because the current `capture()` and `click()` bypass foreground confirmation.

### Task 2: Enforce foreground and geometry checks in the PC adapter

**Files:**
- Modify: `core/pc_window.py:124-173`
- Test: `tests/test_pc_window.py`

- [x] **Step 1: Implement the smallest adapter-only change**

```python
def activate(self) -> int:
    hwnd = self._find_window()
    if self._user32.GetForegroundWindow() == hwnd:
        return hwnd
    self._user32.ShowWindow(hwnd, 9)
    self._user32.SetForegroundWindow(hwnd)
    for _ in range(10):
        if self._user32.GetForegroundWindow() == hwnd:
            return hwnd
        sleep(0.05)
    raise RuntimeError("PC 游戏窗口未能置前，已拒绝截图或输入")
```

Call `activate()` before `capture()`, `click()`, and `back()`. Reject a non-positive client area or an aspect-ratio deviation above `_ASPECT_TOLERANCE` before resizing a screenshot.

- [x] **Step 2: Run PC adapter tests**

Run: `python -m pytest -q tests/test_pc_window.py`

Expected: PASS.

### Task 3: Run bounded regression checks

**Files:**
- Modify: none

- [x] **Step 1: Run related window and command tests**

Run: `python -m pytest -q tests/test_pc_window.py tests/test_window_capture.py tests/test_main_story.py`

Expected: PC and emulator window tests pass; only the pre-existing launcher test failures remain outside this command.

- [x] **Step 2: Run the full suite and document the baseline exception**

Run: `python -m pytest -q --ignore tests/test_launcher.py` plus `python -m pytest -q tests/test_launcher.py`

Expected: no new failures; the known seven `tests/test_launcher.py` failures remain until the launcher migration slice is handled separately.
