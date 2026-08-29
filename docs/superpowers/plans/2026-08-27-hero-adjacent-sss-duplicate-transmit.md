# 相邻同名 SSS 副本传送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当且仅当当前无红点副本紧邻同名 SSS 英雄时，安全地进入既有传送事务。

**Architecture:** 在 `HeroSynthStateMachine` 保存只对下一张卡有效的 SSS 名称视觉指纹。稳定读取当前卡后，将上一张上下文与当前评级、红点和名称指纹一起判断；命中时创建当前副本的既有待传送上下文，而不是增加新的传送路径。翻卡未确认、名称不一致或视觉证据未知时维持失败关闭。

**Tech Stack:** Python 3、OpenCV、NumPy、pytest。

---

### Task 1: 先锁定相邻同名业务决策

**Files:**
- Modify: `tests/test_hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py:HeroSynthStateMachine`

- [ ] **Step 1: 写失败测试：同名 SSS 后的无红点副本创建传送事务**

```python
def test_adjacent_same_name_sss_then_no_dot_opens_transmit():
    machine = machine(verify_filter=True)
    sss_name = "hero-abc"
    machine._previous_card_context = (sss_name, SafetyClass.SSS)

    with (
        patch.object(machine, "_hero_identity_fingerprint", return_value=sss_name),
        patch.object(machine, "_classify_current_hero", return_value=SafetyClass.NON_SSS),
        patch.object(machine, "_red_dot_present", return_value=False),
    ):
        action = machine.next_action(fixture("list_no_reddot"))

    assert action.name == "open_transmit_for_current_card"
    assert machine.transmit_phase is TransmitPhase.OPENING
    assert machine.transmit_target_observation == sss_name
```

- [ ] **Step 2: 运行该测试并确认失败**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py -k adjacent_same_name_sss -q`

Expected: FAIL；当前实现会产生 `next_card_*`，因为无红点分支尚未读取上一张 SSS 上下文。

- [ ] **Step 3: 实现最小的只相邻上下文和传送决策**

```python
previous = self._previous_card_context
same_name_after_sss = (
    previous is not None
    and previous[1] is SafetyClass.SSS
    and previous[0] == current_identity
)
if hero_class is SafetyClass.NON_SSS and not red_dot and same_name_after_sss:
    self._previous_card_context = None
    self.transmit_phase = TransmitPhase.OPENING
    self.transmit_target_observation = current_identity
    self.transmit_continuity_intact = True
    return self._simulator_transition_action("open_transmit_for_current_card", ...)
```

仅在当前卡已稳定确认、名称指纹可读且是模拟器路径时执行；复用 `open_transmit_for_current_card` 的现有来源页、目标页和目标卡 SSS 安全检查。

- [ ] **Step 4: 运行该测试并确认通过**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py -k adjacent_same_name_sss -q`

Expected: PASS。

### Task 2: 锁定排除条件和状态清理

**Files:**
- Modify: `tests/test_hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py:HeroSynthStateMachine.next_action`

- [ ] **Step 1: 写失败测试：不同名、无上下文和红点均不能传送**

```python
@pytest.mark.parametrize(
    ("previous", "current", "red_dot"),
    [
        (("hero-abc", SafetyClass.SSS), "hero-def", False),
        (None, "hero-abc", False),
        (("hero-abc", SafetyClass.SSS), "hero-abc", True),
    ],
)
def test_only_adjacent_same_name_no_dot_duplicate_is_transmitted(...):
    ...
    assert action.name != "open_transmit_for_current_card"
```

另加测试：当前稳定卡为 SSS 时上下文被更新；不同名、刻印入口、传送完成、轮次完成和 `preview()` 后上下文均不会遗留。

- [ ] **Step 2: 运行排除测试并确认失败**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py -k "only_adjacent_same_name or previous_card_context" -q`

Expected: FAIL；新增上下文字段尚未在所有分支、`preview()` 快照和轮次重置中处理。

- [ ] **Step 3: 最小实现状态生命周期**

```python
def _clear_previous_card_context(self) -> None:
    self._previous_card_context = None

# 当前 SSS：保存当前名称并走原 next_card。
# 当前非 SSS：读取一次上下文后立即清除；只有满足三项条件时传送。
# 筛选、刻印、传送返回、轮次完成和恢复：清除上下文。
# preview()：把字段纳入 snapshot/restore。
```

不要建立整轮英雄名称列表；不要修改 PC 分支；不要改变有红点刻印或 SSS 材料中止传送逻辑。

- [ ] **Step 4: 运行排除测试并确认通过**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py -k "only_adjacent_same_name or previous_card_context" -q`

Expected: PASS。

### Task 3: 日志与回归验证

**Files:**
- Modify: `games/epic7/hero_synthesis.py:HeroSynthRunner._decision_hint`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 写失败测试：传送原因记录相邻同名 SSS 证据**

```python
assert "上一张=SSS" in action.reason
assert "同名=是" in action.reason
assert "当前无红点副本" in action.reason
```

- [ ] **Step 2: 运行该测试并确认失败**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py -k adjacent_same_name_log -q`

Expected: FAIL；新增决策原因尚未写入动作和 Runner 日志提示。

- [ ] **Step 3: 添加最小可审计日志**

```python
reason = (
    "上一张=SSS，名称指纹同名=是，当前非SSS且无红点副本；"
    "打开传送并复用目标SSS保护"
)
```

只为这条新增决策增加日志；原有跳过、刻印和 SSS 材料日志不改语义。

- [ ] **Step 4: 运行完整相关回归**

Run: `D:\anaconda\python.exe -m pytest auto_game_unified\tests\test_hero_synthesis.py auto_game_unified\tests\test_pc_hero_synthesis_evidence.py auto_game_unified\tests\test_desktop_catalog.py -q`

Expected: PASS，且 PC 英雄合成用例保持原样。

- [ ] **Step 5: 编译和差异检查**

Run: `D:\anaconda\python.exe -m compileall -q auto_game_unified\games\epic7\hero_synthesis.py; git -C auto_game_unified diff --check`

Expected: 两个命令退出码均为 0。
