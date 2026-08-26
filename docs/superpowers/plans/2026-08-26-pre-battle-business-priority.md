# Pre-Battle Business Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在购买旗帜弹窗出现的第一帧立即冻结已经稳定的背景“战斗开始”动作，并在连续两帧确认后安全交回竞技场购买流程。

**Architecture:** 竞技场观察层在检测到购买弹窗时不再上报背景白名单动作；共享 `BattleSupervisor` 同时建立执行端不变量，任何未进入战斗的业务弹窗首帧都屏蔽并重置背景动作稳定状态。现有购买报价、不可逆转场和每日限购事务保持不变。

**Tech Stack:** Python 3、NumPy、OpenCV、pytest/unittest。

---

## 文件结构

- Modify: `tests/test_epic7_arena.py` — 真实购买 fixture 不得暴露背景动作。
- Modify: `games/epic7/arena.py` — 购买弹窗优先于普通/快速战斗按钮。
- Modify: `tests/test_battle_supervisor.py` — 已稳定背景动作遇到业务弹窗首帧时不得重试。
- Modify: `core/battle_supervisor.py` — 执行端冻结、稳定重置和首帧日志。
- Modify: `docs/TRANSITION_CONTRACTS.md`、`docs/USER_GUIDE.md` — 记录战前业务弹窗优先级。

### Task 1: 消除竞技场观察层的冲突状态

**Files:**
- Modify: `tests/test_epic7_arena.py`
- Modify: `games/epic7/arena.py:544-605`

- [ ] **Step 1: 写真实购买 fixture 的失败测试**

在 `Epic7ArenaStateMachineTests` 中增加：

```python
def test_ticket_popup_suppresses_background_battle_start_action(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES))

    observation = machine.observe_battle(
        load_fixture("friendship_ticket_offer_live_20260826"),
        None,
    )

    self.assertTrue(observation.pre_battle_business_visible)
    self.assertIsNone(observation.allowed_action)
```

- [ ] **Step 2: 运行测试并确认按预期变红**

Run:

```powershell
pytest tests/test_epic7_arena.py::Epic7ArenaStateMachineTests::test_ticket_popup_suppresses_background_battle_start_action -q
```

Expected: FAIL，实际 `allowed_action` 为 `('battle-start', (1258, 1043))`。

- [ ] **Step 3: 在观察层让购买弹窗优先**

把 `BattleObservation.allowed_action` 改为：

```python
allowed_action=(
    None
    if no_ticket is not None
    else ("switch-to-normal-battle", pre_battle.switch_point)
    if pre_battle.mode is PreBattleMode.QUICK
    and pre_battle.switch_point is not None
    else ("battle-start", start.center)
    if pre_battle.mode is PreBattleMode.NORMAL and start is not None
    else None
),
```

不改变 `pre_battle_business_visible=no_ticket is not None`。

- [ ] **Step 4: 运行状态机专项测试**

Run:

```powershell
pytest tests/test_epic7_arena.py -q -k "ticket or pre_battle"
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交观察层修复**

```powershell
git add tests/test_epic7_arena.py games/epic7/arena.py
git commit -m "fix: suppress arena background action under ticket popup"
```

### Task 2: 在共享监督器冻结业务弹窗后的背景动作

**Files:**
- Modify: `tests/test_battle_supervisor.py`
- Modify: `core/battle_supervisor.py:93-258`

- [ ] **Step 1: 写已稳定动作遇到购买框首帧的失败测试**

在 `tests/test_battle_supervisor.py` 中增加：

```python
def test_pre_battle_business_first_frame_freezes_stable_background_action():
    normal = BattleObservation(
        True,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        allowed_action=("battle-start", (1258, 1043)),
    )
    popup = replace(normal, pre_battle_business_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [normal, normal, popup, popup],
        config_overrides={"allowed_action_retry_seconds": 1},
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.PRE_BATTLE_BUSINESS
    assert clicks == [((1258, 1043), "battle-start")]
    assert any("业务弹窗首帧已识别" in line and "冻结背景操作" in line for line in logs)
    assert diagnostics == []
```

同时增加单帧闪现后必须重新稳定背景动作的测试：

```python
def test_transient_pre_battle_business_resets_background_action_stability():
    normal = BattleObservation(
        True,
        False,
        False,
        True,
        AutoBattleState.UNKNOWN,
        allowed_action=("battle-start", (1258, 1043)),
    )
    popup = replace(normal, pre_battle_business_visible=True)
    auto = BattleObservation(False, True, False, True, AutoBattleState.AUTO)
    result = replace(auto, battle_visible=False, result_visible=True)
    supervisor, gate, observe, clicks, logs, diagnostics = make_supervisor(
        [normal, popup, normal, auto, auto, result, result]
    )

    assert supervisor.run(observe, cycle=1) is BattleOutcome.RESULT_REACHED
    assert clicks == []
    assert diagnostics == []
```

- [ ] **Step 2: 运行测试并确认按预期变红**

Run:

```powershell
pytest tests/test_battle_supervisor.py::test_pre_battle_business_first_frame_freezes_stable_background_action -q
```

Expected: FAIL；旧监督器在 `popup` 第一帧再次点击 `battle-start`，点击列表有两项，且没有冻结日志。

- [ ] **Step 3: 实现共享冻结不变量**

在 `run()` 的局部状态中增加：

```python
business_pending_logged = False
```

业务弹窗稳定判断之后建立：

```python
business_pending = (
    observation.pre_battle_business_visible and not entry_confirmed
)
if business_pending:
    if not business_pending_logged:
        self.runtime.log(
            f"模式={self.label} 轮次={cycle} 阶段=战前 "
            "状态=业务弹窗首帧已识别 动作=冻结背景操作 "
            "等待=连续2帧确认"
        )
        business_pending_logged = True
    allowed_stable.reset()
    last_allowed_action = None
    allowed_action_clicks = 0
    allowed_action_clicked_at = None
else:
    business_pending_logged = False

effective_allowed_action = (
    None if business_pending else observation.allowed_action
)
```

在后续 `allowed_signature`、动作变化和点击分支中统一使用 `effective_allowed_action`，不再直接使用 `observation.allowed_action`。识别有效性仍把 `pre_battle_business_visible` 视为已识别页面。

- [ ] **Step 4: 运行共享监督器测试**

Run:

```powershell
pytest tests/test_battle_supervisor.py -q
```

Expected: 全部 PASS；新测试只保留弹窗出现前的一次 `battle-start` 点击。

- [ ] **Step 5: 提交共享保护**

```powershell
git add tests/test_battle_supervisor.py core/battle_supervisor.py
git commit -m "fix: prioritize pre-battle business popups"
```

### Task 3: 文档与完整验证

**Files:**
- Modify: `docs/TRANSITION_CONTRACTS.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: 补充可复用事务约束**

在共享战斗和竞技场购买说明中加入：

```text
战前业务弹窗一旦出现首帧，立即冻结背景白名单动作；连续两帧后才交回路线处理。首轮无票和中途耗尽共用同一购买事务。
```

- [ ] **Step 2: 运行相关专项测试**

Run:

```powershell
pytest tests/test_battle_supervisor.py tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py tests/test_battle_safety_invariants.py -q
```

Expected: 全部 PASS。

- [ ] **Step 3: 运行完整验证**

Run:

```powershell
pytest -q
python -m compileall -q core games desktop main.py
git diff --check
```

Expected: 测试零失败，编译与差异检查退出码均为 `0`。

- [ ] **Step 4: 提交文档并推送**

```powershell
git add docs/TRANSITION_CONTRACTS.md docs/USER_GUIDE.md
git commit -m "docs: document pre-battle popup priority"
git push origin main
```

- [ ] **Step 5: 核对远端与实机边界**

```powershell
git status -sb
git rev-parse HEAD
git rev-parse origin/main
```

Expected: 本地与远端哈希一致；只报告离线验证完成，真实首轮无票闭环由用户验收。
