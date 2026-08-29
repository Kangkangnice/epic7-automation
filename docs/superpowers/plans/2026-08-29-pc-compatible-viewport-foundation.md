# PC Compatible Viewport Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PC backend restore a real `1920×1080` game client, feed the business layer the emulator-compatible `1982×1132` padded canvas, and prove that the shared emulator lobby templates work on a real PC lobby frame.

**Architecture:** `Epic7PcWindow` owns the only PC-specific geometry: window calibration, raw capture, legacy padding, and canvas-to-client click translation. `main.py` uses the shared `templates/` root for both backends; later route plans may add evidence-level PC overrides only where real PC fixtures prove they are necessary. This plan is deliberately limited to the viewport/shared-template foundation and lobby proof; route-by-route live migration remains separate so each route stays independently testable.

**Tech Stack:** Python 3, Win32 via `ctypes`, NumPy, PyAutoGUI, OpenCV template matching, pytest/unittest, existing Epic7 state machines.

---

## File map

- Modify `core/pc_window.py`: define the PC render contract, resize/verify the client, pad captures without interpolation, and translate canvas clicks.
- Modify `tests/test_pc_window.py`: unit-test calibration, capture pixels, permission failures, and click boundaries.
- Modify `main.py`: calibrate before runtime use, log actual geometry, and choose shared templates for PC.
- Modify `tests/test_main_story.py`: verify PC runtime calibration and shared-template selection.
- Create `tests/fixtures/epic7_pc_navigation/lobby_1920x1080.png`: the verified real PC lobby raw frame captured on 2026-08-29.
- Create `tests/test_pc_shared_navigation.py`: prove the real PC lobby is recognized by existing emulator templates after padding.
- Modify `docs/PC_TEMPLATE_MIGRATION.md`: replace the bulk-PC-template guidance with shared-first evidence rules.

## Task 1: Lock the PC render and canvas contract

**Files:**
- Modify: `core/pc_window.py`
- Modify: `tests/test_pc_window.py`

- [ ] **Step 1: Add failing capture and click-translation tests**

Add these cases to `PcWindowSafetyTests`:

```python
def test_capture_places_1920x1080_pixels_on_legacy_canvas_without_resizing(self):
    source = np.arange(1080 * 1920 * 3, dtype=np.uint8).reshape(1080, 1920, 3)
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(
            self.game,
            "_validated_rect",
            return_value=WindowRect(10, 20, 1920, 1080),
        ),
        patch("auto_game_unified.core.pc_window.pyautogui.screenshot") as screenshot,
    ):
        screenshot.return_value = _FakeImage(source)
        canvas = self.game.capture()

    self.assertEqual((1132, 1982, 3), canvas.shape)
    np.testing.assert_array_equal(source, canvas[52:, :1920])
    self.assertFalse(canvas[:52].any())
    self.assertFalse(canvas[:, 1920:].any())

def test_click_subtracts_legacy_top_padding_before_sending_input(self):
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(
            self.game,
            "_validated_rect",
            return_value=WindowRect(10, 20, 1920, 1080),
        ),
        patch.object(self.game, "_send_click") as send_click,
    ):
        self.game.click((991, 566))

    send_click.assert_called_once_with((1001, 534))

def test_click_rejects_a_point_in_the_top_padding(self):
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(
            self.game,
            "_validated_rect",
            return_value=WindowRect(10, 20, 1920, 1080),
        ),
        patch.object(self.game, "_send_click") as send_click,
    ):
        with self.assertRaisesRegex(RuntimeError, "PC 游戏渲染区外"):
            self.game.click((100, 51))

    send_click.assert_not_called()
```

Change the existing click mapping assertion from `(1001, 586)` to the new padded-canvas expectation, or replace that test with the named test above. Change the incompatible-aspect test to expect an exact client-size error.

- [ ] **Step 2: Run the focused tests and confirm they fail for the current stretch implementation**

Run:

```powershell
python -m pytest tests/test_pc_window.py -q
```

Expected: the new capture test fails because the current result is a resized `1982×1132` image; the click test fails because the current implementation scales instead of subtracting 52.

- [ ] **Step 3: Implement the minimal render/canvas constants and conversion**

In `core/pc_window.py`, remove the `cv2` import and replace the aspect-ratio contract with explicit geometry:

```python
RENDER_SIZE = (1920, 1080)
REFERENCE_SIZE = (1982, 1132)
LEGACY_TOP = 52
```

Add the same padding helper used conceptually by the emulator backend:

```python
@staticmethod
def _legacy_canvas(render: np.ndarray) -> np.ndarray:
    if render.shape[:2] != (RENDER_SIZE[1], RENDER_SIZE[0]):
        raise RuntimeError(
            f"PC 游戏截图尺寸异常：{render.shape[1]}x{render.shape[0]}；"
            f"预期 {RENDER_SIZE[0]}x{RENDER_SIZE[1]}"
        )
    canvas = np.zeros((REFERENCE_SIZE[1], REFERENCE_SIZE[0], 3), dtype=np.uint8)
    canvas[LEGACY_TOP:, : RENDER_SIZE[0]] = render
    return canvas
```

Make `_validated_rect()` require exactly `1920×1080`, with an error containing both actual and expected sizes. Update `capture()` to return `_legacy_canvas(frame)` and never resize.

Replace click scaling with exact translation and bounds checking:

```python
render_point = point[0], point[1] - LEGACY_TOP
if not (
    0 <= render_point[0] < RENDER_SIZE[0]
    and 0 <= render_point[1] < RENDER_SIZE[1]
):
    raise RuntimeError(f"拒绝在 PC 游戏渲染区外点击：{point}")
self._send_click((rect.left + render_point[0], rect.top + render_point[1]))
```

- [ ] **Step 4: Run the focused tests and confirm the canvas contract passes**

Run:

```powershell
python -m pytest tests/test_pc_window.py -q
```

Expected: all tests in `test_pc_window.py` pass.

- [ ] **Step 5: Commit only the render/canvas changes**

```powershell
git add core/pc_window.py tests/test_pc_window.py
git commit -m "fix: align PC capture with emulator canvas"
```

## Task 2: Restore and verify the real PC client size

**Files:**
- Modify: `core/pc_window.py`
- Modify: `tests/test_pc_window.py`

- [ ] **Step 1: Add failing calibration tests**

Import `WindowCalibration` after it is introduced by the implementation step, and add tests equivalent to:

```python
def test_ensure_render_size_skips_resize_when_client_is_already_exact(self):
    exact = WindowRect(10, 20, 1920, 1080)
    self.game._user32 = MagicMock()
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(self.game, "_rect", return_value=exact),
    ):
        result = self.game.ensure_render_size()

    self.assertEqual(WindowCalibration(exact, exact, False), result)
    self.game._user32.SetWindowPos.assert_not_called()

def test_ensure_render_size_resizes_outer_window_and_verifies_client(self):
    before = WindowRect(152, 294, 1280, 720)
    after = WindowRect(152, 294, 1920, 1080)
    outer = WindowRect(139, 236, 1306, 791)
    self.game._user32 = MagicMock()
    self.game._user32.SetWindowPos.return_value = 1
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(self.game, "_rect", side_effect=[before, after]),
        patch.object(self.game, "_outer_rect", return_value=outer),
        patch("auto_game_unified.core.pc_window.sleep"),
    ):
        result = self.game.ensure_render_size()

    self.assertEqual(WindowCalibration(before, after, True), result)
    self.game._user32.SetWindowPos.assert_called_once_with(
        123, 0, 139, 236, 1946, 1151, 0x0014
    )

def test_ensure_render_size_stops_when_resize_does_not_reach_target(self):
    before = WindowRect(152, 294, 1280, 720)
    self.game._user32 = MagicMock()
    self.game._user32.SetWindowPos.return_value = 1
    with (
        patch.object(self.game, "activate", return_value=123),
        patch.object(self.game, "_ensure_input_allowed"),
        patch.object(self.game, "_rect", side_effect=[before] * 12),
        patch.object(
            self.game,
            "_outer_rect",
            return_value=WindowRect(139, 236, 1306, 791),
        ),
        patch("auto_game_unified.core.pc_window.sleep"),
    ):
        with self.assertRaisesRegex(RuntimeError, "调整后实际仍为 1280x720"):
            self.game.ensure_render_size()
```

- [ ] **Step 2: Run the new tests and confirm the calibration API is missing**

Run:

```powershell
python -m pytest tests/test_pc_window.py -q
```

Expected: FAIL because `WindowCalibration`, `_outer_rect()`, and `ensure_render_size()` do not exist.

- [ ] **Step 3: Implement exact client calibration**

Add:

```python
@dataclass(frozen=True)
class WindowCalibration:
    before: WindowRect
    after: WindowRect
    adjusted: bool
```

Add `_outer_rect()` using `GetWindowRect`. Implement `ensure_render_size()` with this sequence:

```python
def ensure_render_size(self) -> WindowCalibration:
    hwnd = self.activate()
    self._ensure_input_allowed(hwnd)
    before = self._rect(hwnd)
    if (before.width, before.height) == RENDER_SIZE:
        return WindowCalibration(before, before, False)

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
        0x0014,
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
```

Keep the permission check before `SetWindowPos`; the existing error already tells the user to run the automation at the same privilege level as the game.

- [ ] **Step 4: Run calibration and safety tests**

Run:

```powershell
python -m pytest tests/test_pc_window.py -q
```

Expected: all tests pass, including activation, permission, exact-size, padding, click, and back safety cases.

- [ ] **Step 5: Commit the calibration behavior**

```powershell
git add core/pc_window.py tests/test_pc_window.py
git commit -m "feat: restore PC game client resolution"
```

## Task 3: Calibrate at startup and use shared templates

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: Add failing runtime and template-root tests**

Add a test that patches `Epic7PcWindow` and asserts calibration happens once and is logged:

```python
def test_pc_runtime_calibrates_window_and_logs_actual_geometry(self):
    window = unittest.mock.MagicMock()
    window.ensure_render_size.return_value = unittest.mock.MagicMock(
        before=unittest.mock.MagicMock(width=1280, height=720),
        after=unittest.mock.MagicMock(width=1920, height=1080),
        adjusted=True,
    )
    with patch.object(main_module, "Epic7PcWindow", return_value=window):
        runtime = main_module._build_runtime(
            "story", dry_run=True, window_backend="pc"
        )

    window.ensure_render_size.assert_called_once_with()
    self.assertIs(runtime._capture, window.capture)
```

Add a dry-run dispatch test that captures the template root passed to the machine:

```python
def test_pc_run_uses_shared_template_root(self):
    runtime = unittest.mock.MagicMock()
    machine = object()
    build_machine = unittest.mock.MagicMock(return_value=machine)
    runner_type = unittest.mock.MagicMock()
    runner_type.return_value.run.return_value = 0
    spec = replace(
        get_mode("story"),
        build_machine=build_machine,
        runner_type=runner_type,
    )
    with patch.object(main_module, "_build_runtime", return_value=runtime):
        main_module.run_mode(
            spec=spec,
            dry_run=True,
            max_cycles=1,
            start_state=spec.default_state,
            window_backend="pc",
        )

    template_root = build_machine.call_args.args[0]
    self.assertEqual("templates", template_root.name)
```

- [ ] **Step 2: Run the focused tests and confirm current PC startup/root selection fails**

Run:

```powershell
python -m pytest tests/test_main_story.py -q
```

Expected: the calibration test fails because `_build_runtime()` only calls `activate()`, and the template-root test reports `templates_pc`.

- [ ] **Step 3: Implement startup calibration and shared-first selection**

In `_build_runtime()`, replace the PC-only `activate()` call with `ensure_render_size()`. Construct the `Runtime`, then log a single evidence-rich line:

```python
calibration = None
if window_backend == "pc":
    game_window = Epic7PcWindow()
    calibration = game_window.ensure_render_size()
else:
    game_window = Epic7Window()
    game_window.activate()

# construct runtime as today

if calibration is not None:
    runtime.log(
        "模式=PC初始化 "
        f"调整前={calibration.before.width}x{calibration.before.height} "
        f"目标=1920x1080 "
        f"调整后={calibration.after.width}x{calibration.after.height} "
        f"是否调整={'是' if calibration.adjusted else '否'} "
        "识别画布=1982x1132 模板来源=共享模拟器模板"
    )
```

In `run_mode()`, remove the backend-dependent `template_subdir` branch and always set:

```python
template_root = ROOT / "games" / "epic7" / "templates"
```

Remove the obsolete error that requires the whole `templates_pc` directory. Do not delete `templates_pc` itself.

- [ ] **Step 4: Run runtime and existing main tests**

Run:

```powershell
python -m pytest tests/test_main_story.py -q
```

Expected: all tests pass and the PC backend passes the shared root to the selected mode.

- [ ] **Step 5: Commit startup and root selection**

```powershell
git add main.py tests/test_main_story.py
git commit -m "feat: initialize PC runs on shared visual evidence"
```

## Task 4: Add the real-PC lobby compatibility regression

**Files:**
- Create: `tests/fixtures/epic7_pc_navigation/lobby_1920x1080.png`
- Create: `tests/test_pc_shared_navigation.py`

- [ ] **Step 1: Copy only the verified raw PC lobby frame into the fixture directory**

Source captured during the approved probe:

```text
D:\Cache\Temp\epic7_pc_lobby_1920x1080.png
```

Destination:

```text
tests/fixtures/epic7_pc_navigation/lobby_1920x1080.png
```

Verify with Pillow that the destination is exactly `(1920, 1080)` before using it.

- [ ] **Step 2: Add the shared-template lobby regression**

Create `tests/test_pc_shared_navigation.py`:

```python
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.core.pc_window import Epic7PcWindow
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.navigation import (
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
SHARED_TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURE = ROOT / "tests" / "fixtures" / "epic7_pc_navigation" / "lobby_1920x1080.png"


def _load_raw_pc_lobby() -> np.ndarray:
    image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
    assert image is not None
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _navigator(screen: np.ndarray) -> Epic7Navigator:
    return Epic7Navigator(
        build_navigation_templates(SHARED_TEMPLATES),
        Runtime(lambda: screen, lambda _point: None),
    )


def test_real_pc_lobby_is_recognized_with_shared_emulator_templates():
    screen = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())
    observation = _navigator(screen).observe(screen)
    assert observation.name == "lobby"
    assert observation.confidence >= 0.82


def test_real_pc_lobby_shared_anchor_centers_keep_emulator_geometry():
    screen = Epic7PcWindow._legacy_canvas(_load_raw_pc_lobby())
    navigator = _navigator(screen)
    expected = {
        "lobby_story": (1724, 316),
        "lobby_arena": (1793, 636),
        "lobby_battle": (1826, 532),
        "lobby_hero": (1475, 1037),
    }
    for name, center in expected.items():
        match = navigator._locate(screen, name, 0.80)
        assert match is not None, name
        assert match.center == center


def test_black_pc_frame_is_not_recognized_as_lobby():
    screen = Epic7PcWindow._legacy_canvas(
        np.zeros((1080, 1920, 3), dtype=np.uint8)
    )
    assert _navigator(screen).observe(screen).name == "invalid"
```

- [ ] **Step 3: Run the new compatibility regression**

Run:

```powershell
python -m pytest tests/test_pc_shared_navigation.py -q
```

Expected: 3 tests pass. If an exact center differs by one pixel because of library version, inspect the saved frame and update only the asserted observed center; do not weaken the recognition thresholds.

- [ ] **Step 4: Run the PC and navigation regression set**

Run:

```powershell
python -m pytest tests/test_pc_window.py tests/test_pc_shared_navigation.py tests/test_navigation.py tests/test_main_story.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the fixture and regression**

```powershell
git add tests/fixtures/epic7_pc_navigation/lobby_1920x1080.png tests/test_pc_shared_navigation.py
git commit -m "test: prove shared lobby evidence on PC"
```

## Task 5: Update migration guidance and run final validation

**Files:**
- Modify: `docs/PC_TEMPLATE_MIGRATION.md`

- [ ] **Step 1: Replace the outdated PC-template-first guidance**

Document these exact rules:

```markdown
- PC 客户区必须先恢复并验证为 `1920×1080`。
- PC 原图使用与模拟器相同的顶部 52、右侧 62 补边，禁止拉伸。
- 每个页面先运行共享 `templates/`；只有真实 PC 正反例证明失败的单个证据才允许放入 `templates_pc/`。
- `templates_pc/` 是证据级覆盖仓库，不再是每条 PC 路线的完整镜像。
- 路线验收仍要求离线 fixture、干跑、一轮人工观察和两轮连续实跑。
```

Keep the existing warnings against fake batch capture and full-screen templates.

- [ ] **Step 2: Run whitespace and focused verification**

Run:

```powershell
git diff --check
python -m pytest tests/test_pc_window.py tests/test_pc_shared_navigation.py tests/test_navigation.py tests/test_main_story.py -q
```

Expected: no diff errors and all focused tests pass.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
python -m pytest -q
```

Expected: the complete suite passes. Existing unrelated working-tree changes must not be staged or reverted.

- [ ] **Step 4: Perform a read-only live PC dry probe**

With the PC client open and the helper running at the same privilege level, capture one frame through `Epic7PcWindow.capture()` and print:

```text
raw_client=1920x1080 canvas=1982x1132 page=<observed page> template_source=shared
```

Do not click or start a route in this foundation step. Save a diagnostic only if the frame is invalid or recognition fails.

- [ ] **Step 5: Commit documentation and any final minimal corrections**

```powershell
git add docs/PC_TEMPLATE_MIGRATION.md
git commit -m "docs: adopt shared-first PC evidence migration"
```

## Self-review result

- Spec coverage: client calibration, permission failure, no-interpolation canvas, click translation, shared-first templates, lobby proof, logging, safety stop, documentation, and staged route rollout are covered.
- Deliberate split: mainline/arena/expedition/hero full live migrations are not bundled here; each will receive its own plan after this foundation passes, preventing one failed route from invalidating the viewport work.
- Placeholder scan: every implementation step names concrete code, commands, errors, and expected results.
- Type consistency: `WindowRect`, `WindowCalibration`, `ensure_render_size()`, `_legacy_canvas()`, and the `1920×1080`/`1982×1132` constants are used consistently across tasks.
