# 狗粮模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增固定刷“特别的时间之书”Episode 3-7 的 `fodder` 模式，按指定次数循环并在体力不足时只使用生命之叶。

**Architecture:** 大厅到 3-7 由 `Epic7Navigator` 逐页验证；3-7 内部由新的 `FodderStateMachine` 与 `FodderRunner` 管理。战斗复用共享 `BattleSupervisor`、自动战斗控件分类、恢复锁、全局网络弹窗和 Runtime。

**Tech Stack:** Python 3、OpenCV、NumPy、pytest、Windows LDPlayer 窗口捕获。

---

### Task 1: 固化实机素材

**Files:**
- Create: `tests/fixtures/epic7_fodder/*.png`
- Create: `games/epic7/templates/fodder/*.png`
- Modify: `tests/test_project_layout.py`

- [ ] **Step 1: 复制完整实机页面**

把 `runtime_diagnostics/fodder_capture/01_side_story.png` 至 `11_replay_team.png` 中的稳定页面复制为：`side_story.png`、`special_book.png`、`episode_detail.png`、`stage_3_7.png`、`assistant.png`、`team.png`、`battle.png`、`clear.png`、`results.png`、`replay.png`、`replay_assistant.png`。

- [ ] **Step 2: 写 fixture 集合失败测试**

在 `test_project_layout.py` 断言上述文件集合精确存在，运行：

```powershell
python -m pytest auto_game_unified/tests/test_project_layout.py -q
```

预期：因 `epic7_fodder` fixture 尚未进入测试工作区而失败。

- [ ] **Step 3: 复制 fixture 并裁剪最小模板**

模板只裁固定文字/图标：大厅“支线故事”、支线页“特别的时间之书”、书页 `Episode`、详情页“冒险”、3-7 标题、准备战斗、选择队伍、战斗开始、CLEAR、确认、重新进行。运行布局测试预期通过。

### Task 2: 导航到 3-7

**Files:**
- Modify: `games/epic7/navigation.py`
- Test: `tests/test_navigation.py`

- [ ] **Step 1: 写失败的入口顺序测试**

用 `side_story → special_book → episode_detail → stage_3_7` 两帧序列驱动 `navigator.navigate("fodder")`，断言点击顺序为：

```python
[
    "进入支线故事",
    "进入特别的时间之书",
    "进入Episode",
    "进入冒险地图",
]
```

同时断言 `stage_3_7` 只有“3-7”标题和“准备战斗”同时存在时成立。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
python -m pytest auto_game_unified/tests/test_navigation.py -q
```

预期：`fodder` 尚不受支持或缺少模板字段。

- [ ] **Step 3: 实现最小导航**

扩展 `NavigationTemplates`、区域和 `observe()`；在 `navigate()` 增加四段 `_transition()`。允许从已记忆的后继页面继续，但每一步仍需目标页两帧稳定。

- [ ] **Step 4: 运行导航测试确认 GREEN**

```powershell
python -m pytest auto_game_unified/tests/test_navigation.py -q
```

### Task 3: 狗粮状态机与资源规则

**Files:**
- Create: `games/epic7/fodder.py`
- Test: `tests/test_epic7_fodder.py`

- [ ] **Step 1: 写状态机失败测试**

定义期望 API：`FodderState`、`FodderAction`、`build_fodder_templates()`、`FodderStateMachine.next_action()`。用实机 fixture 断言：

```text
stage_3_7 → prepare_battle
assistant → select_team
team → start_battle
clear → dismiss_clear
results → confirm_results
replay → settled（completed_cycles + 1，不点击）
replay_assistant（点击 replay 后）→ select_team
```

并断言黑屏、错误关卡和未知页不会返回动作。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
python -m pytest auto_game_unified/tests/test_epic7_fodder.py -q
```

预期：`fodder.py` 不存在。

- [ ] **Step 3: 实现最小状态机**

状态机只根据当前截图返回动作；`preview()` 回滚状态。复用 `observe_battle_controls()` 生成 `BattleObservation`，CLEAR/结算属于 `result_visible`。复用主线生命之叶模板和三锚点逻辑；未验证生命之叶时抛出 `StaminaExhausted`，不提供天空石点击点。

- [ ] **Step 4: 运行状态机测试确认 GREEN**

```powershell
python -m pytest auto_game_unified/tests/test_epic7_fodder.py -q
```

### Task 4: Runner、循环计数与战斗锁

**Files:**
- Modify: `games/epic7/fodder.py`
- Create: `tests/test_fodder_runner.py`
- Modify: `tests/test_battle_safety_invariants.py`

- [ ] **Step 1: 写 Runner 失败测试**

用 fake Runtime 和 fixture 序列断言两轮只在 `replay` 稳定出现时计数；达到 `max_cycles` 后不点击 replay；未达目标时点击 replay 并继续到 start_battle；start_battle 后调用共享 `BattleSupervisor`；恢复锁在结算前拒绝导航恢复；生命之叶耗尽设置 `resource_exhausted=True`。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
python -m pytest auto_game_unified/tests/test_fodder_runner.py auto_game_unified/tests/test_battle_safety_invariants.py -q
```

- [ ] **Step 3: 实现 Runner**

沿用两帧稳定、45 秒普通动作重试、两次点击、每轮一次恢复和 180 秒普通绝对上限；战斗超时完全交给 `BattleSupervisor(BattleConfig(mode="fodder"))`。日志模式显示“狗粮”。

- [ ] **Step 4: 运行测试确认 GREEN**

运行上一步命令，预期全部通过。

### Task 5: 注册 CLI 与文档

**Files:**
- Modify: `games/epic7/modes.py`
- Modify: `tests/test_modes.py`
- Modify: `tests/test_main_story.py`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: 写注册失败测试**

断言 `MODE_SPECS` 包含 `fodder`、默认状态正确、CLI 能分发该 Runner、实跑仍要求正整数 cycles 且禁止 start-state。

- [ ] **Step 2: 运行确认 RED**

```powershell
python -m pytest auto_game_unified/tests/test_modes.py auto_game_unified/tests/test_main_story.py -q
```

- [ ] **Step 3: 注册模式并更新命令**

在 `modes.py` 构建 `FodderStateMachine`；README 增加狗粮说明和实跑命令；架构说明增加 `fodder.py` 和循环完成定义。

- [ ] **Step 4: 运行确认 GREEN**

运行上一步测试命令，预期全部通过。

### Task 6: 离线与最小实机验收

**Files:**
- Modify only when a failing regression requires it

- [ ] **Step 1: 运行专项测试**

```powershell
python -m pytest auto_game_unified/tests/test_epic7_fodder.py auto_game_unified/tests/test_fodder_runner.py auto_game_unified/tests/test_navigation.py auto_game_unified/tests/test_battle_safety_invariants.py -q
```

- [ ] **Step 2: 运行全量测试和编译**

```powershell
python -m pytest -q
python -m compileall -q auto_game_unified
```

- [ ] **Step 3: 实机最小验收**

从大厅运行：

```powershell
python -u -m auto_game_unified.main --mode fodder --max-cycles 1 --live --confirm RUN
```

每 10 至 15 秒查看 `runtime_logs/epic7_fodder.log` 与 `runtime_diagnostics/epic7_fodder/current.png`。只在完整一轮成功后提交实现；出现未知页面先补 fixture 和失败测试。

