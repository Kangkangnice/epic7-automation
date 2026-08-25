# Desktop Preflight and Silent Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one successful environment check reusable across route changes, automatically recheck immediately before a run, document the required startup order, and hide every LDPlayer console subprocess.

**Architecture:** Separate route-independent emulator capture checks from route template validation. Keep the successful environment report in `DesktopController`, perform the environment and selected-route checks asynchronously when Start is clicked, and centralize Windows hidden-process options for `ldconsole.exe` calls.

**Tech Stack:** Python 3, Tkinter, `subprocess`, pytest/unittest, existing Epic7 window and route modules.

---

### Task 1: Reuse preflight state across routes

**Files:**
- Modify: `tests/test_desktop_app.py`
- Modify: `desktop/app.py`

- [ ] **Step 1: Replace the route-invalidation test with a failing preservation test**

```python
def test_selecting_another_route_preserves_successful_preflight():
    controller = DesktopController(worker=FakeWorker())
    controller.apply_preflight(passed_preflight())

    controller.select_route("arena")

    assert controller.can_start is True
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest -q tests/test_desktop_app.py::test_selecting_another_route_preserves_successful_preflight`

Expected: FAIL because `select_route()` currently assigns `None` to `preflight_report`.

- [ ] **Step 3: Preserve the report and stop showing a recheck message on route changes**

Remove `self.preflight_report = None` from `DesktopController.select_route()`. In `DesktopApp._on_route_change()`, leave `environment_var` and its color unchanged; only update cycles, route details, and controls.

- [ ] **Step 4: Run the desktop controller tests and verify GREEN**

Run: `python -m pytest -q tests/test_desktop_app.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- desktop/app.py tests/test_desktop_app.py
git commit -m "fix(desktop): preserve environment check across routes"
```

### Task 2: Split environment and route validation, then recheck before Start

**Files:**
- Modify: `tests/test_desktop_preflight.py`
- Modify: `tests/test_desktop_app.py`
- Modify: `desktop/preflight.py`
- Modify: `desktop/app.py`

- [ ] **Step 1: Write failing tests for independent validators**

Add tests proving `run_preflight()` can validate the emulator without probing route templates and `validate_route_templates()` calls the selected route builder:

```python
def test_preflight_does_not_probe_route_templates(tmp_path):
    report = run_preflight(
        window_factory=lambda: ValidWindow(),
        platform_name="Windows",
    )
    assert report.can_start is True


def test_route_template_validation_uses_selected_mode(tmp_path):
    calls = []
    validate_route_templates("arena", tmp_path, template_probe=lambda mode, root: calls.append((mode, root)))
    assert calls == [("arena", tmp_path)]
```

- [ ] **Step 2: Run the preflight tests and verify RED**

Run: `python -m pytest -q tests/test_desktop_preflight.py`

Expected: FAIL because `run_preflight()` still requires `mode` and `validate_route_templates()` does not exist.

- [ ] **Step 3: Implement the two validators**

Change the public interfaces to:

```python
def validate_route_templates(
    mode: str,
    template_root: Path,
    *,
    template_probe: Callable[[str, Path], None] = _probe_templates,
) -> None:
    template_probe(mode, template_root)


def run_preflight(
    *,
    window_factory: Callable[[], Epic7Window] = Epic7Window,
    platform_name: str | None = None,
) -> PreflightReport:
    # Keep the existing Windows, capture-size, and non-uniform-frame checks.
```

Do not load route assets inside the environment check.

- [ ] **Step 4: Write failing app tests for asynchronous Start validation**

Inject `preflight_runner` and `route_validator` callables into `DesktopApp`. Add tests proving that a failed automatic recheck never calls `worker.start`, and a successful recheck validates the currently selected route before calling it.

- [ ] **Step 5: Run the new app tests and verify RED**

Run: `python -m pytest -q tests/test_desktop_app.py`

Expected: FAIL because Start currently launches immediately and has no injected validators.

- [ ] **Step 6: Implement background Start validation**

Store the injected callables. When Start is clicked, validate cycles and experimental confirmation first, set `_checking`, show `正在复检运行环境……`, disable mutable controls, then run:

```python
report = self._preflight_runner()
if report.can_start:
    self._route_validator(mode, TEMPLATE_ROOT)
```

Return to Tk with `root.after`. On failure, apply/show the failed report or route exception and do not start the worker. On success, apply the fresh report and call a small `_start_worker()` helper that invokes `controller.start()`.

- [ ] **Step 7: Update all existing preflight call sites and tests**

Remove `mode=` and `template_probe=` arguments from environment-only calls. Keep route template assertions under `validate_route_templates()`.

- [ ] **Step 8: Run desktop tests and verify GREEN**

Run: `python -m pytest -q tests/test_desktop_preflight.py tests/test_desktop_app.py`

Expected: all tests pass.

- [ ] **Step 9: Commit**

```powershell
git add -- desktop/preflight.py desktop/app.py tests/test_desktop_preflight.py tests/test_desktop_app.py
git commit -m "fix(desktop): recheck environment before runs"
```

### Task 3: Hide LDPlayer console commands

**Files:**
- Modify: `tests/test_window_capture.py`
- Modify: `core/window.py`

- [ ] **Step 1: Write failing subprocess assertions**

Update the instance-list, render-tap, and Android-back tests to require:

```python
creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
```

Import `subprocess` in the test module if needed.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest -q tests/test_window_capture.py`

Expected: FAIL because the three production `subprocess.run()` calls omit `creationflags`.

- [ ] **Step 3: Add the hidden-process flag to all three calls**

In `_send_render_tap()`, `_instance_channel()`, and `_send_android_back()`, pass:

```python
creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
```

Do not change command arguments, output capture, timeouts, or retry behavior.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest -q tests/test_window_capture.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- core/window.py tests/test_window_capture.py
git commit -m "fix(window): hide LDPlayer console commands"
```

### Task 4: Clarify startup order in UI and docs

**Files:**
- Modify: `desktop/app.py`
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `tests/test_desktop_app.py`

- [ ] **Step 1: Write a failing UI text test**

Define a shared constant and assert its content:

```python
def test_startup_order_mentions_emulator_before_assistant():
    hint = getattr(app_module, "STARTUP_ORDER_HINT", "")
    assert "先启动雷电模拟器" in hint
    assert "进入《第七史诗》" in hint
```

- [ ] **Step 2: Run the text test and verify RED**

Run: `python -m pytest -q tests/test_desktop_app.py::test_startup_order_mentions_emulator_before_assistant`

Expected: FAIL because `STARTUP_ORDER_HINT` does not exist.

- [ ] **Step 3: Add the UI hint and documentation**

Add:

```python
STARTUP_ORDER_HINT = "请先启动雷电模拟器并进入《第七史诗》，再启动本助手并检测环境。"
```

Render it permanently in the environment panel. Add the same startup order to the README desktop usage section and the user guide startup steps.

- [ ] **Step 4: Run desktop tests and documentation checks**

Run: `python -m pytest -q tests/test_desktop_app.py`

Run: `rg -n "先启动雷电模拟器|进入《第七史诗》" desktop/app.py README.md docs/USER_GUIDE.md`

Expected: tests pass and all three user-facing files contain the startup order.

- [ ] **Step 5: Commit**

```powershell
git add -- desktop/app.py README.md docs/USER_GUIDE.md tests/test_desktop_app.py
git commit -m "docs(desktop): clarify emulator startup order"
```

### Task 5: Final verification

**Files:**
- Verify only; no planned production changes.

- [ ] **Step 1: Run formatting and compile checks**

Run: `git diff --check`

Run: `python -m compileall -q desktop core main.py tests`

Expected: both commands exit 0 without output.

- [ ] **Step 2: Run focused regression tests**

Run: `python -m pytest -q tests/test_desktop_app.py tests/test_desktop_preflight.py tests/test_desktop_worker.py tests/test_window_capture.py`

Expected: all tests pass.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`

Expected: all tests and subtests pass.

- [ ] **Step 4: Inspect delivery state**

Run: `git status --short --branch`

Expected: local `main`, no uncommitted files, ahead of `origin/main` until the user requests a push.
