# 第七史诗自动助手桌面 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重写六条业务路线的前提下，交付可从源码直接启动的中文桌面界面，支持环境检测、路线/次数选择、独立进程运行、安全停止、实时日志和诊断导出。

**Architecture:** 新增 `desktop/` 产品外壳，目录中的纯模型、环境检测、Worker 控制器和诊断导出均可脱离 Tk 测试；Tkinter 界面只做绑定和定时轮询。Worker 继续调用现有 `auto_game_unified.main`，通过临时停止文件接入 `Runtime.stop_requested`，不绕过任何 Runner 或英雄合成保护。

**Tech Stack:** Python 3.10+、Tkinter/ttk、subprocess、threading、queue、zipfile、pytest、现有 OpenCV/LDPlayer 窗口层。

---

## 本阶段边界

本计划交付“源码桌面 MVP”，用于维护者日常运行和验证交互。以下内容由后续独立计划处理：PyInstaller、Inno Setup、`%LOCALAPPDATA%` 数据迁移、GitHub Actions 构建、Release、更新检查和 MIT `LICENSE` 文件。拆分原因是桌面运行闭环和分发供应链可以独立验收，先稳定前者可避免把业务问题与打包问题混在一起。

## 文件结构

- Create: `desktop/__init__.py` — 桌面包说明。
- Create: `desktop/catalog.py` — 六路线展示信息和正式/实验状态。
- Create: `desktop/preflight.py` — 无点击的模拟器、截图和模板检查。
- Create: `desktop/worker.py` — 子进程启动、日志队列、停止文件和退出结果。
- Create: `desktop/diagnostics.py` — 当前路线诊断 ZIP 导出和文本脱敏。
- Create: `desktop/app.py` — Tkinter 界面和定时轮询。
- Create: `desktop.py` — `python -m auto_game_unified.desktop` 入口。
- Modify: `main.py` — 增加内部 `--stop-file` 参数并与 P 键组合。
- Modify: `README.md` — 增加源码 GUI 启动方式和路线状态说明。
- Test: `tests/test_desktop_catalog.py`
- Test: `tests/test_desktop_preflight.py`
- Test: `tests/test_desktop_worker.py`
- Test: `tests/test_desktop_diagnostics.py`
- Test: `tests/test_desktop_app.py`
- Modify: `tests/test_main_story.py`

### Task 1: 六路线桌面目录

**Files:**
- Create: `desktop/__init__.py`
- Create: `desktop/catalog.py`
- Test: `tests/test_desktop_catalog.py`

- [ ] **Step 1: 写失败测试，固定产品名称和路线状态**

```python
from auto_game_unified.desktop.catalog import PRODUCT_NAME, ROUTES, route_by_name


def test_catalog_has_one_formal_route_and_five_experimental_routes():
    assert PRODUCT_NAME == "第七史诗自动助手"
    assert [route.mode for route in ROUTES] == [
        "hero_synthesis", "story", "arena", "expedition", "fodder", "assist_auto"
    ]
    assert route_by_name("hero_synthesis").status == "正式功能"
    assert sum(route.experimental for route in ROUTES) == 5


def test_hero_synthesis_is_fixed_to_one_cycle():
    hero = route_by_name("hero_synthesis")
    assert hero.default_cycles == 1
    assert hero.cycles_editable is False
```

- [ ] **Step 2: 运行测试确认模块尚不存在**

Run: `python -m pytest tests/test_desktop_catalog.py -q`

Expected: FAIL with `ModuleNotFoundError: auto_game_unified.desktop`.

- [ ] **Step 3: 实现不可变路线目录**

```python
# desktop/catalog.py
from dataclasses import dataclass

PRODUCT_NAME = "第七史诗自动助手"
PRODUCT_VERSION = "0.1.0-dev"


@dataclass(frozen=True)
class RouteInfo:
    mode: str
    label: str
    status: str
    description: str
    default_cycles: int = 1
    cycles_editable: bool = True

    @property
    def experimental(self) -> bool:
        return self.status == "实验功能"


ROUTES = (
    RouteInfo("hero_synthesis", "英雄合成", "正式功能", "三星英雄刻印合成和 SSS 副本处理", cycles_editable=False),
    RouteInfo("story", "主线", "实验功能", "主线和刷图循环"),
    RouteInfo("arena", "竞技场", "实验功能", "新手竞技场循环"),
    RouteInfo("expedition", "远征", "实验功能", "三阶段远征循环"),
    RouteInfo("fodder", "狗粮", "实验功能", "特别的时间之书 Episode 3-7"),
    RouteInfo("assist_auto", "助手自动", "实验功能", "接管游戏内置重复战斗"),
)


def route_by_name(mode: str) -> RouteInfo:
    return next(route for route in ROUTES if route.mode == mode)
```

`RouteInfo` 仅保留实际 UI 需要的六个字段，不复制业务层的 `needs_navigation`。

- [ ] **Step 4: 运行目录测试**

Run: `python -m pytest tests/test_desktop_catalog.py -q`

Expected: `2 passed`.

- [ ] **Step 5: 提交路线目录**

```powershell
git add desktop/__init__.py desktop/catalog.py tests/test_desktop_catalog.py
git commit -m "feat(desktop): add route catalog"
```

### Task 2: 无点击环境检测

**Files:**
- Create: `desktop/preflight.py`
- Test: `tests/test_desktop_preflight.py`

- [ ] **Step 1: 写失败测试，覆盖通过和阻止结果**

```python
from pathlib import Path
import numpy as np

from auto_game_unified.desktop.preflight import PreflightStatus, run_preflight


class FakeWindow:
    def capture(self):
        return np.full((1132, 1982, 3), 127, dtype=np.uint8)


def test_preflight_passes_for_valid_capture_and_templates(tmp_path):
    (tmp_path / "marker.png").write_bytes(b"png")
    report = run_preflight(
        mode="story",
        template_root=tmp_path,
        window_factory=FakeWindow,
        template_probe=lambda mode, root: None,
        platform_name="Windows",
    )
    assert report.status is PreflightStatus.PASS
    assert report.can_start is True
    assert report.screen_size == (1982, 1132)


def test_preflight_blocks_when_window_capture_fails(tmp_path):
    def broken_window():
        raise RuntimeError("应恰好找到一个支持的雷电模拟器窗口，实际找到 0 个")

    report = run_preflight(
        mode="story",
        template_root=tmp_path,
        window_factory=broken_window,
        template_probe=lambda mode, root: None,
        platform_name="Windows",
    )
    assert report.status is PreflightStatus.BLOCK
    assert report.can_start is False
    assert "雷电" in report.message


def test_preflight_blocks_non_windows_without_touching_window(tmp_path):
    report = run_preflight(
        mode="story",
        template_root=tmp_path,
        window_factory=lambda: (_ for _ in ()).throw(AssertionError("must not run")),
        template_probe=lambda mode, root: None,
        platform_name="Linux",
    )
    assert report.status is PreflightStatus.BLOCK
    assert "Windows" in report.message
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_desktop_preflight.py -q`

Expected: FAIL because `desktop.preflight` does not exist.

- [ ] **Step 3: 实现检查结果和默认模板探针**

```python
# desktop/preflight.py
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import platform

from auto_game_unified.core.window import Epic7Window
from auto_game_unified.games.epic7.modes import get_mode


class PreflightStatus(str, Enum):
    PASS = "通过"
    BLOCK = "阻止"


@dataclass(frozen=True)
class PreflightReport:
    status: PreflightStatus
    message: str
    screen_size: tuple[int, int] | None = None

    @property
    def can_start(self) -> bool:
        return self.status is PreflightStatus.PASS


def _probe_templates(mode: str, template_root: Path) -> None:
    spec = get_mode(mode)
    spec.build_machine(template_root, spec.default_state)


def run_preflight(
    *,
    mode: str,
    template_root: Path,
    window_factory=Epic7Window,
    template_probe=_probe_templates,
    platform_name: str | None = None,
) -> PreflightReport:
    if (platform_name or platform.system()) != "Windows":
        return PreflightReport(PreflightStatus.BLOCK, "首版仅支持 64 位 Windows")
    try:
        template_probe(mode, template_root)
        screen = window_factory().capture()
        height, width = screen.shape[:2]
        if (width, height) != (1982, 1132):
            raise RuntimeError(f"画布尺寸异常：{width}x{height}，预期 1982x1132")
        if float(screen.std()) < 1.0:
            raise RuntimeError("游戏截图为黑屏或纯色画面")
    except Exception as error:
        return PreflightReport(PreflightStatus.BLOCK, str(error))
    return PreflightReport(PreflightStatus.PASS, "雷电模拟器、截图和路线模板检查通过", (width, height))
```

- [ ] **Step 4: 运行环境检测测试**

Run: `python -m pytest tests/test_desktop_preflight.py -q`

Expected: `3 passed`.

- [ ] **Step 5: 提交环境检测**

```powershell
git add desktop/preflight.py tests/test_desktop_preflight.py
git commit -m "feat(desktop): add emulator preflight"
```

### Task 3: GUI 协作式停止入口

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: 写失败测试，固定停止文件参数和组合逻辑**

```python
def test_parser_accepts_internal_stop_file():
    args = main_module.parse_args(["--stop-file", r"D:\\temp\\stop.signal"])
    self.assertEqual(r"D:\temp\stop.signal", args.stop_file)


def test_build_runtime_stops_when_gui_stop_file_exists(self):
    with tempfile.TemporaryDirectory() as directory:
        stop_file = Path(directory) / "stop.signal"
        stop_file.touch()
        window = unittest.mock.MagicMock()
        with patch.object(main_module, "Epic7Window", return_value=window):
            runtime = main_module._build_runtime(
                "story", dry_run=False, stop_file=stop_file
            )
        with self.assertRaises(ManualStop):
            runtime.capture()
        window.capture.assert_not_called()
```

- [ ] **Step 2: 运行目标测试确认签名不支持**

Run: `python -m pytest tests/test_main_story.py -q`

Expected: FAIL because `--stop-file` and the `stop_file` keyword on `_build_runtime` do not exist.

- [ ] **Step 3: 实现 P 键与停止文件组合**

在 `main.py` 对现有函数做以下精确改动，其他 Runtime 参数保持原样：

```diff
-def _build_runtime(mode: str, dry_run: bool, window_backend: str = "emulator") -> Runtime:
+def _build_runtime(
+    mode: str,
+    dry_run: bool,
+    window_backend: str = "emulator",
+    stop_file: Path | None = None,
+) -> Runtime:
     if window_backend == "pc":
         game_window = Epic7PcWindow()
         game_window.activate()
     else:
         game_window = Epic7Window()
         game_window.activate()
     stop_hotkey = None if dry_run else WindowsPStopHotkey()

+    def stop_requested() -> bool:
+        return bool(
+            (stop_hotkey is not None and stop_hotkey.pressed())
+            or (stop_file is not None and stop_file.exists())
+        )

     return Runtime(
         capture=game_window.capture,
         click=game_window.click,
         wake=game_window.wake,
         back=game_window.back,
         dry_run=dry_run,
         diagnostic_dir=ROOT / "runtime_diagnostics" / f"epic7_{mode}",
         log_path=ROOT / "runtime_logs" / f"epic7_{mode}.log",
-        stop_requested=None if stop_hotkey is None else stop_hotkey.pressed,
+        stop_requested=None if dry_run else stop_requested,
     )
```

解析器增加：

```python
parser.add_argument("--stop-file", help=argparse.SUPPRESS)
```

`main()` 调用 `run_mode()` 前不改变业务参数；将 `Path(args.stop_file) if args.stop_file else None` 传入 `run_mode` 的 `stop_file` 关键字，再由 `run_mode` 原样传给 `_build_runtime`。同步扩展 `run_mode` 签名，默认值为 `None`，保持所有现有调用兼容。

- [ ] **Step 4: 运行 main 与 Runtime 回归**

Run: `python -m pytest tests/test_main_story.py tests/test_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: 提交停止入口**

```powershell
git add main.py tests/test_main_story.py
git commit -m "feat(desktop): add cooperative stop signal"
```

### Task 4: Worker 子进程与实时日志

**Files:**
- Create: `desktop/worker.py`
- Test: `tests/test_desktop_worker.py`

- [ ] **Step 1: 写失败测试，固定命令、日志和停止行为**

```python
from pathlib import Path
from auto_game_unified.desktop.worker import RunRequest, WorkerController, WorkerEvent


class FakeProcess:
    def __init__(self):
        self.stdout = iter(["第一行\n", "第二行\n"])
        self.returncode = None

    def wait(self):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode


def test_worker_builds_existing_live_cli_and_streams_logs(tmp_path):
    calls = []
    worker = WorkerController(
        repo_parent=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs)) or FakeProcess(),
    )
    worker.start(RunRequest("story", 3))
    worker.join_reader(timeout=1)
    events = worker.drain_events()
    command = calls[0][0]
    assert "auto_game_unified.main" in command
    assert command[-2:] != []
    assert [event.message for event in events if event.kind == "log"] == ["第一行", "第二行"]
    assert events[-1] == WorkerEvent("finished", "运行完成", exit_code=0)


def test_worker_stop_creates_signal_file(tmp_path):
    worker = WorkerController(repo_parent=tmp_path, popen=lambda *a, **k: FakeProcess())
    worker.start(RunRequest("hero_synthesis", 1))
    worker.request_stop()
    assert worker.stop_file is not None
    assert worker.stop_file.exists()
```

- [ ] **Step 2: 运行测试确认模块不存在**

Run: `python -m pytest tests/test_desktop_worker.py -q`

Expected: FAIL because `desktop.worker` does not exist.

- [ ] **Step 3: 实现 WorkerController**

实现不可变 `RunRequest(mode, cycles)` 和 `WorkerEvent(kind, message, exit_code=None)`。`WorkerController.start()` 必须：

- 拒绝同时启动第二个进程；
- 用 `tempfile.TemporaryDirectory` 创建本次停止文件路径，但启动时不创建文件；
- 按请求构建命令；例如主线三轮为 `sys.executable -u -m auto_game_unified.main --mode story --window-backend emulator --max-cycles 3 --live --confirm RUN --stop-file <本次临时文件绝对路径>`；
- `cwd` 使用仓库父目录；
- `stdout=PIPE`、`stderr=STDOUT`、`text=True`、`encoding="utf-8"`、`errors="replace"`；
- 后台 daemon 线程逐行写入 `queue.Queue[WorkerEvent]`；
- 结束时按退出码写入 `finished` 事件：`0=运行完成`、`1=运行失败`、`2=资源耗尽`、`130=用户停止`、其他值为 `工作进程异常结束`。

核心方法签名固定为 `start(request: RunRequest) -> None`、`request_stop() -> None`、`drain_events() -> list[WorkerEvent]`、`join_reader(timeout: float | None = None) -> None`，并提供只读属性 `running -> bool`。

`request_stop()` 只写停止文件，不调用 `terminate()`。`finished` 后清理临时目录；测试需要在结束前检查停止文件时，FakeProcess 的读取线程通过事件或 join 控制，避免竞态。

- [ ] **Step 4: 运行 Worker 测试**

Run: `python -m pytest tests/test_desktop_worker.py -q`

Expected: all tests pass.

- [ ] **Step 5: 提交 Worker**

```powershell
git add desktop/worker.py tests/test_desktop_worker.py
git commit -m "feat(desktop): run automation in worker process"
```

### Task 5: 诊断 ZIP 导出

**Files:**
- Create: `desktop/diagnostics.py`
- Test: `tests/test_desktop_diagnostics.py`

- [ ] **Step 1: 写失败测试，固定包含范围和脱敏**

```python
import json
from zipfile import ZipFile
from auto_game_unified.desktop.diagnostics import export_diagnostics


def test_export_contains_selected_mode_only_and_redacts_home(tmp_path):
    root = tmp_path / "repo"
    (root / "runtime_logs").mkdir(parents=True)
    (root / "runtime_diagnostics" / "epic7_story").mkdir(parents=True)
    home = tmp_path / "User Name"
    (root / "runtime_logs" / "epic7_story.log").write_text(
        f"诊断={home / 'secret.png'}\n", encoding="utf-8"
    )
    (root / "runtime_logs" / "epic7_arena.log").write_text("other", encoding="utf-8")
    (root / "runtime_diagnostics" / "epic7_story" / "current.png").write_bytes(b"png")

    output = export_diagnostics("story", root=root, output_dir=tmp_path / "exports", user_home=home)
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert "logs/epic7_story.log" in names
        assert "diagnostics/current.png" in names
        assert all("arena" not in name for name in names)
        assert "%USERPROFILE%" in archive.read("logs/epic7_story.log").decode("utf-8")
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["mode"] == "story"
```

- [ ] **Step 2: 运行测试确认模块不存在**

Run: `python -m pytest tests/test_desktop_diagnostics.py -q`

Expected: FAIL because `desktop.diagnostics` does not exist.

- [ ] **Step 3: 实现限定路线的导出器**

`export_diagnostics(mode, *, root, output_dir, user_home=Path.home()) -> Path`：

- 创建带时间戳的 ZIP；
- 写入 `metadata.json`，字段为产品版本、模式、导出时间、Python 版本和平台；
- 收集 `runtime_logs/epic7_<mode>.log` 及 `.1` 到 `.4`；
- 收集 `runtime_diagnostics/epic7_<mode>/*.png`；
- 文本日志把用户主目录替换为 `%USERPROFILE%`；
- 不遍历环境变量，不读取其他路线目录；
- 文件不存在时仍生成仅含 metadata 的有效 ZIP；
- ZIP 内路径固定为 `logs/` 和 `diagnostics/`，不泄露本机绝对路径。

- [ ] **Step 4: 运行诊断测试**

Run: `python -m pytest tests/test_desktop_diagnostics.py -q`

Expected: all tests pass.

- [ ] **Step 5: 提交诊断导出**

```powershell
git add desktop/diagnostics.py tests/test_desktop_diagnostics.py
git commit -m "feat(desktop): export local diagnostics"
```

### Task 6: Tkinter 界面和控制器

**Files:**
- Create: `desktop/app.py`
- Create: `desktop.py`
- Test: `tests/test_desktop_app.py`

- [ ] **Step 1: 写失败测试，固定 UI 状态规则而不依赖真实窗口**

```python
from auto_game_unified.desktop.app import DesktopController
from auto_game_unified.desktop.catalog import route_by_name
from auto_game_unified.desktop.preflight import PreflightReport, PreflightStatus


class FakeWorker:
    running = False
    def start(self, request): self.request = request; self.running = True
    def request_stop(self): self.stopped = True
    def drain_events(self): return []


def test_controller_requires_successful_preflight_before_start():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("story")
    assert controller.can_start is False
    controller.apply_preflight(PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132)))
    assert controller.can_start is True


def test_controller_forces_hero_synthesis_to_one_cycle():
    worker = FakeWorker()
    controller = DesktopController(worker=worker)
    controller.select_route("hero_synthesis")
    controller.set_cycles(99)
    controller.apply_preflight(PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132)))
    controller.start()
    assert worker.request.cycles == 1


def test_experimental_route_requires_confirmation():
    controller = DesktopController(worker=FakeWorker())
    controller.select_route("story")
    controller.apply_preflight(PreflightReport(PreflightStatus.PASS, "通过", (1982, 1132)))
    assert controller.needs_experimental_confirmation is True
```

- [ ] **Step 2: 运行测试确认界面模块不存在**

Run: `python -m pytest tests/test_desktop_app.py -q`

Expected: FAIL because `desktop.app` does not exist.

- [ ] **Step 3: 实现无 Tk 依赖的 DesktopController**

`DesktopController` 保存选中路线、次数、最近环境检测和 Worker。规则：

- 默认选择英雄合成；
- 切换路线后清除旧环境检测，必须重新检测；
- 次数必须是正整数；
- 英雄合成始终运行一次且次数输入不可编辑；
- Worker 运行时不能再次启动或切换路线；
- 实验路线暴露 `needs_experimental_confirmation=True`；
- `start()` 只构造 `RunRequest` 并调用 Worker，不接触 Tk；
- `stop()` 调用 `request_stop()`。

- [ ] **Step 4: 实现 Tkinter App**

窗口标题为 `第七史诗自动助手 0.1.0-dev`，布局分四区：

1. 顶部环境状态和“检测环境”；
2. 左侧六路线单选、正式/实验文字；
3. 右侧次数、开始、停止、打开日志、打开诊断、导出诊断；
4. 底部只读滚动日志。

实现要求：

- 环境检测在线程中运行，通过 `root.after()` 回主线程更新控件；
- 每 100 ms 调用 `worker.drain_events()`，逐行追加日志；
- 收到 `finished` 后恢复路线、检测和开始控件；
- 实验路线开始前使用 `messagebox.askyesno`；
- “停止”立即禁用自身并显示“正在安全停止”；
- 打开目录使用 `os.startfile`；
- 导出使用 `filedialog.askdirectory` 选择目标目录，成功后显示路径；
- 关闭窗口时若 Worker 正在运行，提示先停止，不直接销毁运行进程；
- 所有 Tk 控件只在主线程操作。

`desktop.py`：

```python
from auto_game_unified.desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

从仓库父目录运行：

```powershell
python -u -m auto_game_unified.desktop
```

- [ ] **Step 5: 运行控制器测试与导入烟雾测试**

Run:

```powershell
python -m pytest tests/test_desktop_app.py -q
python -c "from auto_game_unified.desktop.app import DesktopApp; print('desktop import ok')"
```

Expected: tests pass and output contains `desktop import ok`.

- [ ] **Step 6: 提交桌面界面**

```powershell
git add desktop/app.py desktop.py tests/test_desktop_app.py
git commit -m "feat(desktop): add interactive automation UI"
```

### Task 7: 文档、全量验证和本机验收

**Files:**
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: 更新使用入口**

README 和用户手册增加：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.desktop
```

明确桌面 MVP 当前仍从源码启动；英雄合成为正式功能，其他五条为实验功能；PC 后端不会出现在 GUI 中；安装包由下一阶段交付。

- [ ] **Step 2: 检查计划内测试**

Run:

```powershell
python -m pytest tests/test_desktop_catalog.py tests/test_desktop_preflight.py tests/test_desktop_worker.py tests/test_desktop_diagnostics.py tests/test_desktop_app.py tests/test_main_story.py tests/test_runtime.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: 运行编译和全量回归**

Run:

```powershell
python -m compileall -q .
python -m pytest -q
```

Expected: compile exit code 0；全量测试不少于基线 `548 passed, 71 subtests passed` 且无失败。

- [ ] **Step 4: 本机 GUI 只读验收**

从仓库父目录启动 `python -u -m auto_game_unified.desktop`，验证：

- 中文窗口可见且没有终端异常；
- 六条路线和状态正确；
- 英雄合成次数固定为 1；
- 其他路线次数可编辑；
- 环境检测能够显示当前雷电结果；
- 日志和诊断目录按钮可用；
- 不点击“开始”，关闭窗口不会控制游戏。

- [ ] **Step 5: 用户明确允许后执行一轮 GUI 实跑验收**

用户将游戏停在首页并明确允许实跑后：选择英雄合成 → 检测环境 → 开始 → 观察实时日志 → 使用 GUI 停止或等待完成 → 导出诊断。验收期间发现的业务问题按既有截图回归流程单独修复，不在 UI 中增加猜测性绕过。

- [ ] **Step 6: 提交文档和最终整理**

```powershell
git add README.md docs/USER_GUIDE.md
git commit -m "docs: add desktop MVP guide"
```

- [ ] **Step 7: 确认本地 main 状态**

Run:

```powershell
git status --short --branch
git log -8 --oneline
```

Expected: 工作区干净；当前分支为 `main`；桌面 MVP 各批提交均存在。不得 push，除非用户另行要求。
