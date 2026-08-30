# 雷电 14 渲染窗口兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重做模板、不修改雷电设置的前提下，兼容新版雷电窗口并恢复主线 1、3、10 轮实机验收。

**Architecture:** 使用唯一 `dnplayer.exe` 顶层窗口和 `ldconsole list2` 的绑定句柄定位 1920×1080 渲染区。截图在内存中转换为旧版 1982×1132 兼容画布，业务点击从旧画布坐标转换为渲染坐标后通过 `ld.exe input tap` 投递；窗口前置使用条件确认消除错误码 0 的竞态。

**Tech Stack:** Python 3、ctypes Win32、PyGetWindow、PyAutoGUI、NumPy、OpenCV、unittest、雷电 `ldconsole.exe`/`ld.exe`

**Repository note:** 当前工作区没有 `.git`，无法创建 worktree 或提交。每个任务以测试结果和明确文件列表作为检查点。

---

### Task 1: 安全识别新版雷电顶层窗口

**Files:**
- Modify: `auto_game_unified/core/window.py`
- Test: `auto_game_unified/tests/test_window_capture.py`

- [ ] **Step 1: 写入新版标题与进程校验的失败测试**

在 `WindowViewportTests` 增加两个测试：新版标题只在进程为 `dnplayer.exe` 时接受；同名窗口超过一个时拒绝。

```python
def test_updated_ldplayer_title_is_accepted_only_for_dnplayer(self):
    game = Epic7Window()
    window = MagicMock(title="雷电模拟器", isMinimized=False, _hWnd=123)
    with (
        patch("auto_game_unified.core.window.pygetwindow.getAllWindows", return_value=[window]),
        patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
    ):
        self.assertIs(window, game._window())

def test_multiple_supported_ldplayer_windows_are_rejected(self):
    game = Epic7Window()
    windows = [
        MagicMock(title="雷电模拟器", isMinimized=False, _hWnd=123),
        MagicMock(title="雷电模拟器", isMinimized=False, _hWnd=456),
    ]
    with (
        patch("auto_game_unified.core.window.pygetwindow.getAllWindows", return_value=windows),
        patch.object(game, "_window_process_name", return_value="dnplayer.exe"),
    ):
        with self.assertRaisesRegex(RuntimeError, "expected one"):
            game._window()
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture.WindowViewportTests.test_updated_ldplayer_title_is_accepted_only_for_dnplayer auto_game_unified.tests.test_window_capture.WindowViewportTests.test_multiple_supported_ldplayer_windows_are_rejected -v
```

Expected: FAIL/ERROR，因为 `_window_process_name` 和新版标题兼容尚不存在。

- [ ] **Step 3: 实现最小安全窗口筛选**

在 `Epic7Window` 中保留旧标题，并增加支持标题集合与进程名校验：

```python
_SUPPORTED_TITLES = {"第七史诗", "雷电模拟器"}

@staticmethod
def _window_process_name(window) -> str:
    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(window._hWnd, ctypes.byref(process_id))
    return psutil.Process(process_id.value).name().lower()

def _window(self):
    windows = [
        window for window in pygetwindow.getAllWindows()
        if window.title in self._SUPPORTED_TITLES
        and self._window_process_name(window) == "dnplayer.exe"
    ]
    if len(windows) != 1:
        raise RuntimeError(f"expected one supported LDPlayer window, found {len(windows)}")
    if windows[0].isMinimized:
        raise RuntimeError(f"{windows[0].title} window is minimized")
    return windows[0]
```

- [ ] **Step 4: 运行窗口识别测试**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 记录检查点**

记录修改文件 `core/window.py`、`tests/test_window_capture.py` 及测试通过数量；当前无 Git 仓库，不执行提交。

### Task 2: 使用渲染子窗口生成旧版兼容画布

**Files:**
- Modify: `auto_game_unified/core/window.py`
- Test: `auto_game_unified/tests/test_window_capture.py`

- [ ] **Step 1: 写入渲染画布的失败测试**

```python
def test_render_frame_is_embedded_in_the_legacy_canvas(self):
    render = np.full((1080, 1920, 3), 127, dtype=np.uint8)

    canvas = Epic7Window._legacy_canvas(render)

    self.assertEqual((1132, 1982, 3), canvas.shape)
    self.assertTrue(np.all(canvas[52:, :1920] == 127))
    self.assertTrue(np.all(canvas[:52] == 0))
    self.assertTrue(np.all(canvas[:, 1920:] == 0))

def test_render_frame_rejects_an_unexpected_size(self):
    with self.assertRaisesRegex(RuntimeError, "1920x1080"):
        Epic7Window._legacy_canvas(np.zeros((720, 1280, 3), dtype=np.uint8))
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture.WindowViewportTests.test_render_frame_is_embedded_in_the_legacy_canvas auto_game_unified.tests.test_window_capture.WindowViewportTests.test_render_frame_rejects_an_unexpected_size -v
```

Expected: ERROR，因为 `_legacy_canvas` 尚不存在。

- [ ] **Step 3: 实现渲染截图与兼容画布**

```python
_RENDER_SIZE = (1920, 1080)
_LEGACY_SIZE = (1982, 1132)
_LEGACY_RENDER_OFFSET = (0, 52)

@staticmethod
def _legacy_canvas(render: np.ndarray) -> np.ndarray:
    if render.shape[:2] != (1080, 1920):
        raise RuntimeError(
            f"LDPlayer render size changed: {render.shape[1]}x{render.shape[0]}; expected 1920x1080"
        )
    canvas = np.zeros((1132, 1982, 3), dtype=np.uint8)
    canvas[52:1132, 0:1920] = render
    return canvas

def capture(self) -> np.ndarray:
    self.activate()
    _, _, bind_handle = self._instance_channel()
    rect = self._window_rect_from_handle(bind_handle)
    image = pyautogui.screenshot(region=(rect.left, rect.top, rect.width, rect.height))
    return self._legacy_canvas(np.asarray(image.convert("RGB")))
```

- [ ] **Step 4: 调整现有截图测试并运行**

测试必须确认 `pyautogui.screenshot` 接收渲染子窗口区域，而不是顶层外框。

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 记录检查点**

保存一次新版模拟器基准诊断图，确认输出画布为 1982×1132 且游戏内容位于旧坐标区域。

### Task 3: 将旧画布点击转换为雷电渲染坐标

**Files:**
- Modify: `auto_game_unified/core/window.py`
- Test: `auto_game_unified/tests/test_window_capture.py`

- [ ] **Step 1: 写入点击换算和越界拒绝的失败测试**

```python
def test_legacy_click_is_converted_to_render_coordinates(self):
    game = Epic7Window()
    with patch.object(game, "_send_render_tap") as tap:
        game._click_legacy((1790, 326))
    tap.assert_called_once_with((1790, 274))

def test_legacy_click_rejects_chrome_coordinates(self):
    game = Epic7Window()
    for point in [(10, 20), (1950, 500)]:
        with self.subTest(point=point):
            with self.assertRaisesRegex(RuntimeError, "render area"):
                game._click_legacy(point)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture.WindowViewportTests.test_legacy_click_is_converted_to_render_coordinates auto_game_unified.tests.test_window_capture.WindowViewportTests.test_legacy_click_rejects_chrome_coordinates -v
```

Expected: ERROR，因为 `_click_legacy` 和 `_send_render_tap` 尚不存在。

- [ ] **Step 3: 实现最小坐标转换**

```python
def _click_legacy(self, point: tuple[int, int]) -> None:
    render_point = point[0], point[1] - 52
    if not (0 <= render_point[0] < 1920 and 0 <= render_point[1] < 1080):
        raise RuntimeError(f"refusing click outside Android render area: {point}")
    self._send_render_tap(render_point)

def _send_render_tap(self, point: tuple[int, int]) -> None:
    console_path, _, _ = self._instance_channel()
    subprocess.run(
        [str(console_path.with_name("ld.exe")), "input", "tap", str(point[0]), str(point[1])],
        check=True,
        capture_output=True,
        timeout=10,
    )

def click(self, point: tuple[int, int]) -> None:
    self.activate()
    self._click_legacy(point)
```

- [ ] **Step 4: 运行窗口点击测试**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture -v
```

Expected: 全部 PASS，且测试不调用 Windows 鼠标点击。

- [ ] **Step 5: 记录检查点**

记录点击转换样例 `(1790,326) → (1790,274)` 和越界拒绝结果。

### Task 4: 消除窗口前置错误码 0 的竞态

**Files:**
- Modify: `auto_game_unified/core/window.py`
- Test: `auto_game_unified/tests/test_window_capture.py`

- [ ] **Step 1: 写入延迟取得前台的失败测试**

```python
def test_activate_waits_for_delayed_foreground_confirmation(self):
    game = Epic7Window()
    window = MagicMock(isActive=False, _hWnd=123)
    window.activate.side_effect = pygetwindow.PyGetWindowException("Error code from Windows: 0")
    with (
        patch.object(game, "_window", return_value=window),
        patch(
            "auto_game_unified.core.window.ctypes.windll.user32.GetForegroundWindow",
            side_effect=[999, 999, 123],
        ),
        patch("auto_game_unified.core.window.sleep") as wait,
    ):
        game.activate()
    self.assertGreaterEqual(wait.call_count, 2)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture.WindowViewportTests.test_activate_waits_for_delayed_foreground_confirmation -v
```

Expected: ERROR，因为现有实现只立即检查一次。

- [ ] **Step 3: 实现短时条件确认**

```python
def _wait_until_foreground(self, handle: int, attempts: int = 10) -> bool:
    for _ in range(attempts):
        if ctypes.windll.user32.GetForegroundWindow() == handle:
            return True
        sleep(0.05)
    return False

def activate(self) -> None:
    window = self._window()
    if window.isActive:
        return
    try:
        window.activate()
    except pygetwindow.PyGetWindowException:
        if self._wait_until_foreground(window._hWnd):
            return
        raise
    if not self._wait_until_foreground(window._hWnd):
        raise RuntimeError(f"could not activate {window.title}")
```

- [ ] **Step 4: 运行全部窗口测试**

Run:

```powershell
python -m unittest auto_game_unified.tests.test_window_capture -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 记录检查点**

保存测试输出，确认错误码 0 只有在随后观察到目标 HWND 时才被接受。

### Task 5: 离线回归与新版模拟器底座验收

**Files:**
- Verify: `auto_game_unified/tests/`
- Update: `auto_game_unified/docs/2026-08-09-story-stabilization-handoff.md`

- [ ] **Step 1: 运行完整离线回归**

Run:

```powershell
python -m unittest discover -s auto_game_unified\tests -v
```

Expected: 原 74 项及本计划新增测试全部 PASS。

- [ ] **Step 2: 连续执行 100 次前置与截图**

使用 `Epic7Window.capture()` 连续运行 100 次，每次验证：

```python
assert screen.shape == (1132, 1982, 3)
assert float(screen[52:, :1920].std()) >= 5.0
```

Expected: 100/100 成功，无 `PyGetWindowException`、黑屏或尺寸变化。

- [ ] **Step 3: 保存底座验收日志和当前帧**

日志记录成功次数、窗口句柄、渲染句柄、渲染尺寸以及失败原因；只覆盖一张监控帧。

- [ ] **Step 4: 更新阶段记录**

在交接文档中记录新版雷电路径、标题、外框尺寸、渲染尺寸、离线测试数量和 100 次底座测试结果。

### Task 6: 主线导航与完整实机验收

**Files:**
- Verify: `auto_game_unified/runtime_logs/`
- Verify: `auto_game_unified/runtime_diagnostics/epic7_story/current.png`
- Update: `auto_game_unified/docs/2026-08-09-story-stabilization-handoff.md`

- [ ] **Step 1: 验证大厅到主线任务页并返回大厅**

只执行一次导航往返；每次点击后必须连续两帧确认目标页。失败时保存现场并停止，不进入战斗。

- [ ] **Step 2: 运行正式主线 1 轮**

Run:

```powershell
python -u -m auto_game_unified.main --mode story --max-cycles 1 --live --confirm RUN
```

Expected: 退出码 0；日志包含 `complete-story cycles=1`。自动战斗必须先出现 `action=enable_auto`，随后当前帧识别为开启态并持续发生战斗区域变化。

- [ ] **Step 3: 运行正式主线 3 轮**

Run:

```powershell
python -u -m auto_game_unified.main --mode story --max-cycles 3 --live --confirm RUN
```

Expected: 退出码 0；日志包含 `complete-story cycles=3`，中途无未知页面、重复误点或窗口异常。

- [ ] **Step 4: 运行正式主线 10 轮**

Run:

```powershell
python -u -m auto_game_unified.main --mode story --max-cycles 10 --live --confirm RUN
```

Expected: 退出码 0；日志包含 `complete-story cycles=10`。任何故障都清零连续计数，保存现场，修复并重新从 1 轮开始。

- [ ] **Step 5: 写入最终验收结论**

记录每次命令、开始/结束时间、退出码、完成轮数、自动战斗确认帧及所有恢复次数。只有 1、3、10 全部通过才把主线标记为已验收。
