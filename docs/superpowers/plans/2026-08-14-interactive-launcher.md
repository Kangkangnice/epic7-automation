# 中文交互式启动菜单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个中文终端菜单，让用户先选择现有模式编号，再输入运行次数，并调用原有实跑入口。

**Architecture:** 新建独立的 `launcher.py`，用固定映射展示四个模式、校验两段输入并组装现有 CLI 参数。`main.py` 和四个模式的业务实现不修改；测试注入输入、输出和入口函数，保证全程离线。

**Tech Stack:** Python 3、标准库、pytest/unittest、现有 `auto_game_unified.main`

以下测试命令从仓库父目录运行；Git 命令从仓库根目录运行。

---

### Task 1: 中文菜单与输入校验

**Files:**
- Create: `launcher.py`
- Create: `tests/test_launcher.py`

- [ ] **Step 1: 编写四项映射和合法输入的失败测试**

```python
def test_selects_mode_then_cycles_and_calls_existing_live_entry():
    inputs = iter(["4", "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 2,
    )

    assert exit_code == 2
    assert calls == [[
        "--mode", "fodder", "--max-cycles", "3", "--live", "--confirm", "RUN"
    ]]
    assert any("1. 主线" in line for line in output)
    assert any("4. 狗粮（特别的时间之书 3-7）" in line for line in output)
    assert any("即将运行：狗粮，共 3 次" in line for line in output)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `python -m pytest auto_game_unified/tests/test_launcher.py -q`

Expected: FAIL，提示无法导入 `auto_game_unified.launcher`。

- [ ] **Step 3: 编写无效编号和次数只重试当前问题的失败测试**

```python
def test_invalid_values_are_reprompted_in_chinese():
    inputs = iter(["x", "5", "2", "0", "abc", "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [[
        "--mode", "arena", "--max-cycles", "3", "--live", "--confirm", "RUN"
    ]]
    assert output.count("请输入 1 到 4 之间的功能编号。") == 2
    assert output.count("运行次数必须是正整数。") == 2
```

- [ ] **Step 4: 实现最小菜单模块**

```python
from collections.abc import Callable

from auto_game_unified import main as main_module


MENU_OPTIONS = {
    "1": ("主线", "story"),
    "2": ("竞技场", "arena"),
    "3": ("远征", "expedition"),
    "4": ("狗粮", "fodder"),
}

MENU_LINES = (
    "请选择功能：",
    "1. 主线",
    "2. 竞技场",
    "3. 远征",
    "4. 狗粮（特别的时间之书 3-7）",
)


def run_interactive(
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    run_main: Callable[[list[str]], int] | None = None,
) -> int:
    for line in MENU_LINES:
        output(line)
    while True:
        selected = input_fn("请输入功能编号：").strip()
        if selected in MENU_OPTIONS:
            break
        output("请输入 1 到 4 之间的功能编号。")
    while True:
        raw_cycles = input_fn("请输入运行次数：").strip()
        try:
            cycles = int(raw_cycles)
        except ValueError:
            cycles = 0
        if cycles > 0:
            break
        output("运行次数必须是正整数。")
    label, mode = MENU_OPTIONS[selected]
    output(f"即将运行：{label}，共 {cycles} 次")
    output("按 P 可随时停止。")
    entry = run_main or main_module.main
    return entry([
        "--mode", mode,
        "--max-cycles", str(cycles),
        "--live", "--confirm", "RUN",
    ])


def main() -> int:
    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 运行菜单专项测试并确认通过**

Run: `python -m pytest auto_game_unified/tests/test_launcher.py -q`

Expected: `2 passed`。

- [ ] **Step 6: 提交菜单实现**

```powershell
git add launcher.py tests/test_launcher.py
git commit -m "feat: add interactive launcher"
```

### Task 2: 使用说明

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README 添加交互式启动命令和菜单顺序**

````markdown
## 中文交互式启动

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.launcher
```

程序会依次询问功能编号和正整数运行次数；确认后直接以前台实跑方式启动。原有命令行启动方式仍然保留。
````

- [ ] **Step 2: 运行文档与布局相关测试**

Run: `python -m pytest auto_game_unified/tests/test_project_layout.py auto_game_unified/tests/test_launcher.py -q`

Expected: PASS。

- [ ] **Step 3: 提交文档**

```powershell
git add README.md
git commit -m "docs: document interactive launcher"
```

### Task 3: 离线回归与收尾

**Files:**
- Verify only; no production changes expected.

- [ ] **Step 1: 运行代码编译检查**

Run: `python -m compileall -q auto_game_unified`

Expected: exit code 0。

- [ ] **Step 2: 运行全量离线测试**

Run: `python -m pytest -q`

Expected: 所有测试通过，且不启动模拟器。

- [ ] **Step 3: 检查提交范围**

Run: `git status --short --branch; git diff --check`

Expected: 工作区干净且无空白错误。
