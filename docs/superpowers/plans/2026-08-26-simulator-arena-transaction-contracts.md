# Simulator Arena Transaction Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模拟器竞技场按视觉来源/目标证据完成全链路事务，并让所有模拟器战斗路线在快速战斗覆盖普通按钮时安全切回普通战斗。

**Architecture:** 保留竞技场状态机和 Runner，在 `Action` 上声明来源、目标、目标状态与证据，由竞技场 Runner 的事务观察器负责有限重试和延迟提交。新增共享 `pre_battle.py` 识别快速/普通模式，新增共享战斗 HUD 识别并与底部控制状态解耦；PC 模板和 PC 行为不变。

**Tech Stack:** Python 3、OpenCV、NumPy、pytest/unittest、现有 `BattleSupervisor`

---

### Task 1: 固化实机证据并建立快速/普通战前识别

**Files:**
- Create: `games/epic7/pre_battle.py`
- Create: `games/epic7/templates/global/quick_battle_button.png`
- Create: `games/epic7/templates/global/quick_battle_switch.png`
- Create: `tests/test_epic7_pre_battle.py`
- Modify: `tests/test_project_layout.py`

- [ ] **Step 1: 把两张 2026-08-26 实机图加入固定素材清单**

```python
"quick_battle_selected_live_20260826.png",
"normal_battle_ready_live_20260826.png",
```

- [ ] **Step 2: 编写快速/普通互斥识别失败测试**

```python
def test_live_quick_page_requires_button_and_white_switch():
    observation = detector.observe(fixture("quick_battle_selected_live_20260826"))
    assert observation.mode is PreBattleMode.QUICK
    assert observation.switch_point is not None

def test_live_normal_page_uses_route_start_anchor():
    start = arena_machine._locate(fixture("normal_battle_ready_live_20260826"), "battle_start")
    observation = detector.observe(fixture("normal_battle_ready_live_20260826"), normal_start=start)
    assert observation.mode is PreBattleMode.NORMAL

def test_quick_source_loses_classification_when_either_anchor_is_removed():
    # 分别遮掉快速按钮和白底闪电区，均应得到 UNKNOWN。
```

- [ ] **Step 3: 运行测试确认 RED**

Run: `pytest tests/test_epic7_pre_battle.py tests/test_project_layout.py -q`

Expected: FAIL，因为共享识别模块和素材清单尚未实现。

- [ ] **Step 4: 从完整实机图裁取两个稳定模板并实现最小识别器**

```python
class PreBattleMode(Enum):
    NORMAL = "normal"
    QUICK = "quick"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class PreBattleObservation:
    mode: PreBattleMode
    normal_score: float = 0.0
    quick_score: float = 0.0
    switch_score: float = 0.0
    switch_point: tuple[int, int] | None = None

class QuickBattleDetector:
    def observe(self, screen, *, normal_start=None) -> PreBattleObservation:
        quick = self._locate(screen, self.quick_button)
        switch = self._locate(screen, self.quick_switch)
        if normal_start is not None and quick is None and switch is None:
            return PreBattleObservation(PreBattleMode.NORMAL, normal_score=normal_start.score)
        if normal_start is None and quick is not None and switch is not None:
            return PreBattleObservation(
                PreBattleMode.QUICK,
                quick_score=quick.score,
                switch_score=switch.score,
                switch_point=switch.center,
            )
        return PreBattleObservation(PreBattleMode.UNKNOWN)
```

- [ ] **Step 5: 运行聚焦测试确认 GREEN 并提交**

Run: `pytest tests/test_epic7_pre_battle.py tests/test_project_layout.py -q`

Expected: PASS。

Commit: `feat: detect simulator quick battle mode`

### Task 2: 将快速切换接入所有模拟器战斗路线

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/fodder.py`
- Modify: `games/epic7/expedition.py`
- Modify: `games/epic7/assist_auto.py`
- Modify: `tests/test_epic7_arena.py`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_epic7_fodder.py`
- Modify: `tests/test_epic7_expedition.py`
- Modify: `tests/test_assist_auto.py`

- [ ] **Step 1: 为每条路线编写“快速页进入战斗监督、普通页不多点”的失败测试**

```python
observation = machine.observe_battle(quick_fixture, None)
assert observation.pre_battle_visible is True
assert observation.allowed_action == ("switch-to-normal-battle", expected_switch)

normal = machine.observe_battle(route_normal_fixture, None)
assert normal.allowed_action[0] in {"battle-start", "start_mission", "start_battle"}
```

- [ ] **Step 2: 运行五条路线聚焦测试确认 RED**

Run: `pytest tests/test_epic7_arena.py tests/test_epic7_story.py tests/test_epic7_fodder.py tests/test_epic7_expedition.py tests/test_assist_auto.py -q`

Expected: FAIL，因为快速页尚未映射为合法战前动作。

- [ ] **Step 3: 在模拟器模板构造器中加载共享 detector，并映射允许动作**

```python
pre_battle = detector.observe(screen, normal_start=battle_start)
allowed_action = (
    ("switch-to-normal-battle", pre_battle.switch_point)
    if pre_battle.mode is PreBattleMode.QUICK
    else (route_start_action, battle_start.center)
    if pre_battle.mode is PreBattleMode.NORMAL
    else None
)
```

PC 构造路径传入 `None`，保持现状，不读取模拟器快速战斗模板。

- [ ] **Step 4: 让各路线只在已确认的 TEAM/战前状态把控制权交给监督器**

竞技场、远征等独立 Runner 遇到快速或普通战前观察时都不得先盲点；监督器根据 `allowed_action` 完成切换和开始动作。主线/狗粮/辅助自动沿用公共 Runner 的战斗入口。

- [ ] **Step 5: 运行聚焦测试确认 GREEN 并提交**

Run: `pytest tests/test_epic7_arena.py tests/test_epic7_story.py tests/test_epic7_fodder.py tests/test_epic7_expedition.py tests/test_assist_auto.py -q`

Expected: PASS。

Commit: `feat: switch quick battle to normal across simulator routes`

### Task 3: 将战斗存在性与底部操作控件解耦

**Files:**
- Modify: `games/epic7/battle_controls.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/fodder.py`
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_epic7_battle_controls.py`
- Modify: `tests/test_battle_supervisor.py`

- [ ] **Step 1: 用真实误报图编写失败测试**

```python
def test_arena_skill_animation_keeps_battle_hud_visible():
    screen = live_diagnostic("20260825_215453_457138_battle_unrecognized.png")
    assert observe_battle_controls(screen) is BattleControls.TRANSITION
    assert battle_scene_visible(screen) is True
```

同时以队伍页、结果页和随机有效画面作为反例，必须返回 False。

- [ ] **Step 2: 运行测试确认 RED**

Run: `pytest tests/test_epic7_battle_controls.py -q`

Expected: FAIL，因为 `battle_scene_visible` 尚不存在。

- [ ] **Step 3: 实现共享战斗 HUD 结构识别**

```python
def battle_scene_visible(screen: np.ndarray) -> bool:
    frame = _reference_frame(screen)
    top_hud = _top_health_bar_structure(frame)
    pause = _pause_control_structure(frame)
    turn_order = _left_turn_order_structure(frame)
    return sum((top_hud, pause, turn_order)) >= 2
```

所有阈值必须由现有多路线战斗 fixture 和非战斗反例量化确定，不以角色或技能动画区域作为证据。

- [ ] **Step 4: 各模式 adapter 使用 HUD 决定 `battle_visible`**

```python
BattleObservation(
    battle_visible=battle_scene_visible(screen),
    auto_state=auto_state_from_controls,
    business_progress=battle_scene_visible(screen) and meaningful_change(previous, screen),
)
```

- [ ] **Step 5: 验证技能演出不触发未知超时，运行 GREEN 并提交**

Run: `pytest tests/test_epic7_battle_controls.py tests/test_battle_supervisor.py tests/test_battle_safety_invariants.py -q`

Expected: PASS。

Commit: `fix: keep battle supervision active during skill animations`

### Task 4: 竞技场动作声明来源和目标，状态延迟提交

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_epic7_arena.py`

- [ ] **Step 1: 编写动作不提前推进状态的失败测试**

```python
action = machine.next_action(list_screen)
assert action.source_state is ArenaState.LIST
assert action.target_state is ArenaState.SELECTED
assert machine.state is ArenaState.LIST

machine.commit(action)
assert machine.state is ArenaState.SELECTED
```

对 `challenge`、结果确认、段位确认和旗帜购买分别建立同类测试。

- [ ] **Step 2: 运行状态机测试确认 RED**

Run: `pytest tests/test_epic7_arena.py -q`

Expected: FAIL，因为动作仍在决策时修改状态。

- [ ] **Step 3: 扩展动作合同并移除决策阶段的状态推进**

```python
@dataclass(frozen=True)
class Action:
    name: str
    point: tuple[int, int]
    source_state: ArenaState
    target_states: tuple[ArenaState, ...]
    reason: str
    irreversible: bool = False

def commit(self, action: Action, target: ArenaState) -> None:
    if target not in action.target_states:
        raise RuntimeError("竞技场动作目标状态不在合同中")
    self.state = target
```

- [ ] **Step 4: 将循环计数从结果按钮点击移到列表稳定确认**

新增明确的 `cycle_pending`，只有结算事务之后列表连续稳定才 `completed_cycles += 1`，随后清空标志。

- [ ] **Step 5: 运行 GREEN 并提交**

Run: `pytest tests/test_epic7_arena.py -q`

Expected: PASS。

Commit: `refactor: delay arena state commits until visual confirmation`

### Task 5: 竞技场 Runner 实现来源保留重试和目标稳定确认

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_arena_runner.py`

- [ ] **Step 1: 编写三个事务分支的失败测试**

```python
def test_challenge_retries_when_selected_source_remains():
    runner = runner_with_frames(selected, selected, selected, team, team)
    runner.run(max_cycles=1)
    assert runner.clicked_names[:2] == ["challenge", "challenge"]

def test_challenge_waits_without_reclick_after_source_disappears():
    runner = runner_with_frames(selected, loading, loading, team, team)
    runner.run(max_cycles=1)
    assert runner.clicked_names.count("challenge") == 1

def test_challenge_commits_team_only_after_two_target_frames():
    runner = runner_with_frames(selected, team, loading, team, team)
    runner.run(max_cycles=1)
    assert runner.commit_history[0] == ArenaState.TEAM
```

同样覆盖选择对手和快速切换；每次重试必须保持原动作坐标。

- [ ] **Step 2: 运行 Runner 测试确认 RED**

Run: `pytest tests/test_arena_runner.py -q`

Expected: FAIL，当前 `_wait_until_in_state` 单帧确认且失败后直接抛错。

- [ ] **Step 3: 实现竞技场事务观察循环**

```python
while not deadline.expired:
    observation = machine.observe_transition(screen, action)
    if target_stable.update(observation.target):
        machine.commit(action, observation.target_state)
        runtime.log(
            f"模式=竞技场 转场确认 动作={action.name} "
            f"目标={state_label(observation.target_state)} 连续=2"
        )
        return
    if observation.source_stable:
        if retry_due and attempts < 4:
            click_same_action()
        continue
    if observation.source_gone:
        runtime.log(
            f"模式=竞技场 等待确认 动作={action.name} "
            "来源=已离开 目标=尚未稳定"
        )
        continue
    fail_unknown_with_diagnostic()
```

- [ ] **Step 4: 删除单帧 `_wait_until_in_state` 路径并修正恢复额度**

每完成一轮或完成一次正常恢复后重新允许下一轮的一次恢复；战斗监督锁定期间仍禁止恢复。

- [ ] **Step 5: 运行 GREEN 并提交**

Run: `pytest tests/test_arena_runner.py tests/test_unknown_screen_runners.py -q`

Expected: PASS。

Commit: `fix: enforce arena source and target transition evidence`

### Task 6: 刷新、旗帜与结算收尾闭环

**Files:**
- Modify: `games/epic7/arena.py`
- Modify: `tests/test_arena_runner.py`
- Modify: `tests/test_ticket_exhaustion.py`

- [ ] **Step 1: 为刷新初次点击失效、免费弹窗持续、购买失效和结果确认失效编写失败测试**

每个测试断言来源仍在时最多四次、来源离开后不再点击、最终目标连续两帧才成功。

- [ ] **Step 2: 运行测试确认 RED**

Run: `pytest tests/test_arena_runner.py tests/test_ticket_exhaustion.py -q`

Expected: FAIL。

- [ ] **Step 3: 用同一事务观察器处理可逆动作**

刷新、免费确认、结果确认和段位确认复用 Task 5 的来源/目标决策；购买旗帜标记为不可逆，来源消失后永不重试。

- [ ] **Step 4: 分离循环完成日志与下一轮动作**

```text
模式=竞技场 轮次=1 业务完成=结算返回对手列表 目标连续=2
模式=竞技场 轮次=2 页面=对手列表 动作候选=select-opponent 来源连续=2
```

- [ ] **Step 5: 运行 GREEN 并提交**

Run: `pytest tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py -q`

Expected: PASS。

Commit: `fix: close arena refresh ticket and result transactions`

### Task 7: 日志、文档与最终离线验证

**Files:**
- Modify: `docs/TRANSITION_CONTRACTS.md`
- Modify: `README.md`
- Modify: `docs/USER_MANUAL.md` if present
- Modify: targeted tests as required by final review

- [ ] **Step 1: 补充竞技场事务示例和快速战斗说明**

文档明确模拟器支持、PC 仍为实验版本；日志示例区分“执行点击、转场确认、业务完成”。

- [ ] **Step 2: 运行计划要求的全部专项测试**

Run: `pytest tests/test_epic7_pre_battle.py tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py tests/test_epic7_battle_controls.py tests/test_battle_supervisor.py tests/test_battle_safety_invariants.py tests/test_navigation.py -q`

Expected: PASS，0 failures。

- [ ] **Step 3: 运行全量测试和编译检查**

Run: `pytest -q`

Expected: PASS，0 failures。

Run: `python -m compileall -q core games desktop main.py`

Expected: exit code 0。

- [ ] **Step 4: 自审需求和 diff**

检查 PC 文件未改、未知画面不新增盲点、每个真实故障有 fixture 测试、循环计数只在完整结算后增加。由于本会话禁止擅自派生子 Agent，执行独立的本地 diff/测试自审代替子 Agent review。

- [ ] **Step 5: 提交最终文档与修正**

Commit: `docs: document simulator arena transaction contracts`

真实模拟器验收由用户随后启动，至少完整跑完一轮；出现问题时保留当前画面和最后日志继续闭环。
