# Auto Battle Source Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模拟器战斗在敌方连续行动、我方技能尚未出现时，仍能根据右上角“自动关闭”证据及时开启自动，并取消 15 秒未知状态误报。

**Architecture:** 路线观察器负责把右上角 `auto_off` 模板解释为明确的 `MANUAL` 来源，并提供模板中心作为点击点；公共 `BattleSupervisor` 只在明确来源持续时重试。来源消失而右下角人物头像尚未稳定时保持 `UNKNOWN` 等待，由现有战斗活动、业务进展和绝对时限继续保护。

**Tech Stack:** Python 3、OpenCV、NumPy、pytest、现有 `BattleSupervisor`

---

### Task 1: 固化实机失败证据并验证右上角来源

**Files:**
- Create: `tests/fixtures/epic7_arena/battle_auto_off_enemy_turn_live_20260826.png`
- Modify: `tests/test_epic7_arena.py`
- Modify: `tests/test_project_layout.py`

- [ ] **Step 1: 保存最新 `auto_not_confirmed` 诊断图为回归素材**

复制 `runtime_diagnostics/epic7_arena/20260826_191102_098312_auto_not_confirmed.png`，保留原始像素，不裁剪完整 fixture。

- [ ] **Step 2: 编写失败测试**

```python
def test_enemy_turn_auto_off_icon_is_manual_source_before_skills_are_available(self):
    screen = load_fixture("battle_auto_off_enemy_turn_live_20260826")
    observation = machine.observe_battle(screen, None)
    assert observe_battle_controls(screen) is BattleControls.TRANSITION
    assert observation.auto_state is AutoBattleState.MANUAL
    assert observation.auto_point == (1693, 93)
```

- [ ] **Step 3: 运行 RED**

Run: `pytest tests/test_epic7_arena.py -q -k enemy_turn_auto_off`

Expected: FAIL，当前观察结果为 `UNKNOWN`。

### Task 2: 让来源消失后的未知动画只等待

**Files:**
- Modify: `tests/test_battle_supervisor.py`
- Modify: `core/battle_supervisor.py`

- [ ] **Step 1: 编写点击后长时间 UNKNOWN 的失败测试**

```python
def test_auto_source_disappears_then_enemy_actions_do_not_timeout():
    manual = BattleObservation(False, True, False, True, AutoBattleState.MANUAL, (1693, 93))
    unknown = replace(manual, auto_state=AutoBattleState.UNKNOWN, auto_point=None, business_progress=True)
    auto = replace(manual, auto_state=AutoBattleState.AUTO, auto_point=None)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [manual, manual] + [unknown] * 8 + [auto, auto, result, result]
    )
    assert supervisor.run(observe, cycle=1) is BattleOutcome.RESULT_REACHED
    assert clicks == [((1693, 93), "enable-auto-battle")]
```

- [ ] **Step 2: 运行 RED**

Run: `pytest tests/test_battle_supervisor.py -q -k "source_disappears_then_enemy"`

Expected: FAIL，旧代码以 `auto_not_confirmed` 在 15 秒窗口内停止。

- [ ] **Step 3: 删除 UNKNOWN 自动确认倒计时**

删除 `auto_wait_since` 及其 `auto_confirm_seconds` 失败分支。保留两条已有规则：稳定 `MANUAL` 来源最多点击四次；稳定 `AUTO` 人物头像连续两帧后记录已开启。

- [ ] **Step 4: 更新旧测试语义并运行 GREEN**

Run: `pytest tests/test_battle_supervisor.py -q`

Expected: PASS；持续 `UNKNOWN` 由战斗绝对/业务时限停止，不再生成 `auto_not_confirmed`。

### Task 3: 路线观察器优先使用明确的 auto_off 来源

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/expedition.py`
- Modify: route tests as required

- [ ] **Step 1: 在三个已有 `auto_off` 模板的观察器中覆盖状态**

```python
auto_match = self._locate(screen, "auto_off")
if auto_match is not None:
    auto_state = AutoBattleState.MANUAL
```

点击点使用 `auto_match.center`。底部三技能仅保留为模板漏检时的兼容回退；底部四人物头像仍是 `AUTO` 目标证据。

- [ ] **Step 2: 运行路线专项**

Run: `pytest tests/test_epic7_arena.py tests/test_epic7_story.py tests/test_epic7_expedition.py tests/test_epic7_battle_controls.py -q`

Expected: PASS。

- [ ] **Step 3: 提交功能修复**

```bash
git add core/battle_supervisor.py games/epic7/arena.py games/epic7/story.py games/epic7/expedition.py tests
git commit -m "fix: enable auto from explicit battle toggle evidence"
```

### Task 4: 最终验证与文档

**Files:**
- Modify: `docs/TRANSITION_CONTRACTS.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: 补充自动开启日志与等待语义**

明确右上角来源、四人物头像目标、来源消失后不重试，以及敌方动画期间不会再触发 15 秒误报。

- [ ] **Step 2: 运行专项与全量验证**

Run: `pytest tests/test_battle_supervisor.py tests/test_epic7_arena.py tests/test_epic7_story.py tests/test_epic7_expedition.py tests/test_epic7_battle_controls.py -q`

Expected: PASS。

Run: `pytest -q`

Expected: PASS，0 failures。

Run: `python -m compileall -q core games desktop main.py`

Expected: exit code 0。

- [ ] **Step 3: 自审并提交文档**

确认 `templates_pc` 和 PC 行为未改，最新真实故障有固定 fixture，工作区无未提交文件。

Commit: `docs: document auto battle source evidence`
