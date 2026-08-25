# Repository Agent Guardrails and Hero Tab Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the visual transition methodology mandatory for every future Agent and fix hero synthesis startup so an ignored information-tab click is retried only while the equipment page remains visually confirmed.

**Architecture:** Add a concise repository-root `AGENTS.md` as the mandatory entry point and keep detailed state-transition semantics in `docs/TRANSITION_CONTRACTS.md`. In navigation, retain the existing page classifiers but replace the one-shot hero-tab flag with an observation-driven retry transaction: stable equipment source, candidate click, post-click grace period, stable source persistence retry, and stable information target confirmation.

**Tech Stack:** Python 3.10+, OpenCV/NumPy visual evidence, `unittest`/pytest regression tests, Markdown repository instructions.

---

## File map

- Create `AGENTS.md` — short, mandatory repository rules and links to the detailed contracts.
- Modify `docs/TRANSITION_CONTRACTS.md` — authoritative source-persistence/source-exit/target-entry retry table.
- Modify `tests/test_navigation.py` — simulator regression for an ignored first click, retry exhaustion, log evidence, and corrected coordinate.
- Modify `tests/test_pc_hero_synthesis_evidence.py` — keep the PC evidence test aligned with the verified information-tab coordinate.
- Modify `games/epic7/hero_synthesis.py` — expose one shared information-tab point so navigation and the hero runner cannot drift.
- Modify `games/epic7/navigation.py` — implement the visual exit/entry retry contract and evidence logs.

### Task 1: Make the methodology mandatory at repository scope

**Files:**
- Create: `AGENTS.md`
- Modify: `docs/TRANSITION_CONTRACTS.md`

- [ ] **Step 1: Create the repository-root Agent rules**

Create `AGENTS.md` with this focused content:

```markdown
# 仓库开发硬约束

## 修改前必须阅读

修改任何视觉识别、点击、导航、重试、事务或路线前，必须阅读：

- `docs/TRANSITION_CONTRACTS.md`
- `docs/HUMAN_AI_WORKFLOW.md`
- 目标路线测试和最新真实失败证据

本规则适用于全部路线、模拟器后端和后续 PC 迁移。

## 不可违反的视觉动作契约

每个改变页面、选择、资源或业务状态的动作都必须定义并验证：

1. 来源进入证据；
2. 候选动作；
3. 来源退出证据；
4. 目标进入证据；
5. 业务完成证据。

点击永远不等于成功。来源退出不等于目标进入，目标进入也不等于业务完成。

点击后：

- 来源仍稳定存在：点击未生效，记录证据并在声明的额度内重试；
- 来源消失但目标尚未稳定：正在转场，只等待，不点击旧坐标；
- 目标稳定出现：转场确认；
- 证据缺失或冲突：记为 `UNKNOWN`，保存诊断并失败关闭。

来源仍被视觉确认时，禁止用一次性“已点击”标志阻止合理重试。不可逆动作的来源一旦消失，禁止再次执行。

## 证据先于代码

- 根据当前日志、完整截图、fixture 和量化数据诊断，不凭推测修改行为。
- 固定坐标必须由当前完整 fixture 验证，同一控件只保留一个共享常量。
- 每个真实故障先增加能复现现场原因的 fixture 回归测试，再改实现。
- 日志必须说明来源证据、尝试次数、来源退出结果、目标证据、关键分数或像素数和最终结论。
- 未知证据不得写成成功。

## 完成规则

运行专项测试、全量测试和编译检查。涉及真实游戏时，在用户完成整个业务闭环前只能报告离线验证结果；局部流程通过不能证明路线已经修复。
```

- [ ] **Step 2: Add the authoritative observation-driven retry table**

Insert a new `## 点击后的观测决策` section in `docs/TRANSITION_CONTRACTS.md` after “基本原则”:

```markdown
## 点击后的观测决策

点击后不能依靠一次性 `clicked=True` 等待超时，必须继续判断来源和目标：

| 稳定观测 | 含义 | 允许动作 |
|---|---|---|
| 来源仍在，目标未到 | 点击未生效 | 记录来源证据，在额度和冷却满足后重试 |
| 来源已离开，目标未稳定 | 正在转场或结果待确认 | 只等待，禁止重复旧动作 |
| 目标稳定进入 | 转场完成 | 记录来源退出和目标进入，进入下一状态 |
| 来源与目标冲突，或两者均无法判断 | `UNKNOWN` | 保存证据并失败关闭或执行契约声明的有限恢复 |

可逆导航动作只在来源仍稳定时重试。不可逆动作在来源消失后不得重试，因为业务可能已经执行而回执尚未出现。来源、目标和业务结果必须分别去抖；一个目标帧不能倒推此前每次点击都成功。
```

- [ ] **Step 3: Verify the instruction files**

Run:

```powershell
rg -n "Non-negotiable visual action contract|A click is never success|entire business loop" AGENTS.md
rg -n "点击后的观测决策|来源仍在|来源已离开|不可逆动作" docs/TRANSITION_CONTRACTS.md
git diff --check
```

Expected: all phrases are found and `git diff --check` prints nothing.

- [ ] **Step 4: Commit the repository rules**

```powershell
git add AGENTS.md docs/TRANSITION_CONTRACTS.md
git commit -m "docs: enforce visual transition contracts for agents"
```

### Task 2: Add regressions for a swallowed information-tab click

**Files:**
- Modify: `tests/test_navigation.py`
- Modify: `tests/test_pc_hero_synthesis_evidence.py`

- [ ] **Step 1: Replace the simple equipment recovery test with a swallowed-click replay**

Replace `test_hero_navigation_logs_equipment_recovery_and_information_entry` in `tests/test_navigation.py` with:

```python
def test_hero_navigation_retries_when_equipment_tab_does_not_exit(self):
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    clock = [0.0]
    equipment = hero_fixture("live_equipment_subpage_20260825")
    information = hero_fixture("list_unfiltered")

    def capture():
        # The lobby click is first. Keep returning equipment after the first
        # information-tab click, then expose information after the retry.
        return equipment if len(clicks) < 3 else information

    def sleep(seconds: float):
        clock[0] += seconds

    runtime = Runtime(
        capture,
        clicks.append,
        emit=logs.append,
        monotonic=lambda: clock[0],
    )
    navigator = Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        runtime,
        sleep=sleep,
        poll_seconds=0.5,
        transition_frames=24,
    )

    navigator.navigate(
        "hero_synthesis", lobby_screen=fixture("lobby_animated_updated")
    )

    self.assertEqual([(65, 200), (65, 200)], clicks[1:])
    expected = [
        "进入标志=英雄装备已确认",
        "动作=切换英雄信息 尝试=1/4",
        "离开标志=未满足 当前子页=英雄装备",
        "动作=切换英雄信息 尝试=2/4",
        "离开标志=英雄装备已离开",
        "进入标志=英雄信息已到达",
        "模式=英雄合成 状态=导航完成 前提=英雄信息页已就绪",
    ]
    positions = [
        next(index for index, log in enumerate(logs) if text in log)
        for text in expected
    ]
    self.assertEqual(sorted(positions), positions)
    self.assertTrue(any("信息蓝=" in log and "装备蓝=" in log for log in logs))
```

- [ ] **Step 2: Add the retry-budget failure test**

Add:

```python
def test_hero_navigation_stops_after_four_information_tab_clicks(self):
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    clock = [0.0]
    equipment = hero_fixture("live_equipment_subpage_20260825")

    def sleep(seconds: float):
        clock[0] += seconds

    runtime = Runtime(
        lambda: equipment,
        clicks.append,
        emit=logs.append,
        monotonic=lambda: clock[0],
    )
    navigator = Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        runtime,
        sleep=sleep,
        poll_seconds=0.5,
        transition_frames=48,
    )

    with self.assertRaisesRegex(RuntimeError, "点击4次后仍未离开"):
        navigator.navigate(
            "hero_synthesis", lobby_screen=fixture("lobby_animated_updated")
        )

    self.assertEqual([(65, 200)] * 4, clicks[1:])
    self.assertTrue(any("尝试=4/4" in log for log in logs))
    self.assertFalse(any("状态=导航完成" in log for log in logs))
```

- [ ] **Step 3: Correct the existing PC expectation**

In `tests/test_pc_hero_synthesis_evidence.py`, change:

```python
assert clicks == [(1490, 1045), (65, 150)]
```

to:

```python
assert clicks == [(1490, 1045), (65, 200)]
```

- [ ] **Step 4: Run the tests and verify the current implementation fails for the right reasons**

Run:

```powershell
python -m pytest tests/test_navigation.py -k "hero_navigation" -q
python -m pytest tests/test_pc_hero_synthesis_evidence.py -k "switches_hero_equipment" -q
```

Expected before implementation: the swallowed-click test cannot obtain a second information-tab click, the retry-budget test does not record four controlled attempts, and the PC coordinate assertion reports `(65, 150)` instead of `(65, 200)`.

### Task 3: Implement the source-exit and target-entry retry transaction

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `games/epic7/navigation.py`
- Test: `tests/test_navigation.py`
- Test: `tests/test_pc_hero_synthesis_evidence.py`

- [ ] **Step 1: Define one shared information-tab point**

Near the module constants in `games/epic7/hero_synthesis.py`, add:

```python
HERO_INFORMATION_TAB_POINT = (65, 200)
```

Then replace the class duplicate:

```python
_HERO_INFO_TAB_POINT = HERO_INFORMATION_TAB_POINT
```

- [ ] **Step 2: Import shared evidence and declare retry limits**

Change the hero imports in `games/epic7/navigation.py` to include:

```python
from auto_game_unified.games.epic7.hero_synthesis import (
    HERO_INFORMATION_TAB_POINT,
    hero_equipment_tab_selected,
    hero_information_tab_selected,
    hero_tab_blue_pixel_counts,
    imprint_button_saturation,
)
```

Replace `_HERO_DETAIL_TAB_POINT = (65, 150)` with:

```python
_HERO_DETAIL_TAB_POINT = HERO_INFORMATION_TAB_POINT
_HERO_DETAIL_TAB_MAX_ATTEMPTS = 4
_HERO_DETAIL_TAB_RETRY_SECONDS = 2.0
```

- [ ] **Step 3: Replace the one-shot transition state**

Inside `_transition()`, replace:

```python
hero_detail_tab_switched = False
hero_container_logged = False
```

with:

```python
hero_detail_tab_clicks = 0
hero_detail_last_click_at: Optional[float] = None
hero_detail_wait_logged = False
hero_equipment_seen = False
hero_container_logged = False
```

- [ ] **Step 4: Implement equipment-source persistence and bounded retry**

Replace the current `hero_detail_tab_switched` branch with logic equivalent to:

```python
if (
    is_stable
    and target == "hero_list"
    and observation.name == "hero_equipment"
):
    information_blue, equipment_blue = hero_tab_blue_pixel_counts(screen)
    hero_equipment_seen = True
    if hero_detail_last_click_at is not None:
        remaining = (
            self._HERO_DETAIL_TAB_RETRY_SECONDS
            - (self.now() - hero_detail_last_click_at)
        )
        if remaining > 0:
            if not hero_detail_wait_logged:
                self.runtime.log(
                    "模式=导航 当前子页=英雄装备 "
                    "等待=点击后确认装备页退出 "
                    f"剩余={remaining:.1f}秒 信息蓝={information_blue} "
                    f"装备蓝={equipment_blue}"
                )
                hero_detail_wait_logged = True
            self.sleep(self.poll_seconds)
            continue
        self.runtime.log(
            "模式=导航 离开标志=未满足 当前子页=英雄装备 "
            f"信息蓝={information_blue} 装备蓝={equipment_blue}"
        )
    if hero_detail_tab_clicks >= self._HERO_DETAIL_TAB_MAX_ATTEMPTS:
        diagnostic = self._diagnostic("hero_information_tab_entry_failed")
        raise RuntimeError(
            "英雄装备页点击4次后仍未离开；"
            f"信息蓝={information_blue} 装备蓝={equipment_blue}；"
            f"已保存诊断 {diagnostic}"
        )
    hero_detail_tab_clicks += 1
    self.runtime.log(
        "模式=导航 进入标志=英雄装备已确认 "
        f"信息蓝={information_blue} 装备蓝={equipment_blue} "
        "动作=切换英雄信息 "
        f"尝试={hero_detail_tab_clicks}/"
        f"{self._HERO_DETAIL_TAB_MAX_ATTEMPTS}"
    )
    self.runtime.click(self._HERO_DETAIL_TAB_POINT, "切换英雄信息")
    hero_detail_last_click_at = self.now()
    hero_detail_wait_logged = False
    stable.reset()
    self.sleep(self.poll_seconds)
    continue
```

Keep the existing container-entry log, but ensure it runs before this branch so the log first states which subpage was entered.

- [ ] **Step 5: Log source exit and stable target entry before returning**

In the stable target branch, replace the current hero-information confirmation log with:

```python
if target == "hero_list" and observation.name == "hero_list":
    information_blue, equipment_blue = hero_tab_blue_pixel_counts(screen)
    if hero_equipment_seen:
        self.runtime.log(
            "模式=导航 离开标志=英雄装备已离开 "
            f"信息蓝={information_blue} 装备蓝={equipment_blue}"
        )
    self.runtime.log(
        "模式=导航 进入标志=英雄信息已到达 连续=2 "
        f"信息蓝={information_blue} 装备蓝={equipment_blue}"
    )
```

Only after these logs should the existing `状态=转场确认` return the target screen and allow `状态=导航完成`.

- [ ] **Step 6: Run the focused regressions**

Run:

```powershell
python -m pytest tests/test_navigation.py -k "hero_navigation" -q
python -m pytest tests/test_pc_hero_synthesis_evidence.py -k "hero_equipment" -q
```

Expected: all selected tests pass; the first swallowed click produces two `(65, 200)` attempts, and four persistent-source attempts fail without a navigation-complete log.

- [ ] **Step 7: Run all hero and navigation tests**

Run:

```powershell
python -m pytest tests/test_navigation.py tests/test_hero_synthesis.py tests/test_pc_hero_synthesis_evidence.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit the tested fix**

```powershell
git add games/epic7/hero_synthesis.py games/epic7/navigation.py tests/test_navigation.py tests/test_pc_hero_synthesis_evidence.py
git commit -m "fix(hero): verify equipment tab exit before continuing"
```

### Task 4: Run repository-wide verification

**Files:**
- Verify only; no expected source changes.

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Compile all Python modules**

Run:

```powershell
python -m compileall -q .
```

Expected: exit code `0` and no output.

- [ ] **Step 3: Verify documentation and working tree integrity**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intentionally uncommitted user files may appear. Do not modify unrelated files.

### Task 5: Perform the user-controlled full-loop acceptance

**Files:**
- Runtime evidence only: `runtime_logs/epic7_hero_synthesis.log`
- Runtime evidence only: `runtime_diagnostics/epic7_hero_synthesis/current.png`

- [ ] **Step 1: Start from the exact failure source**

The user opens the hero equipment subpage, starts one hero-synthesis run from the desktop UI, and leaves the game unobstructed. The AI does not control the simulator.

- [ ] **Step 2: Verify the transition contract from live logs**

Required log sequence:

```text
进入标志=英雄装备已确认
执行点击 动作=切换英雄信息 坐标=(65, 200)
离开标志=未满足 ... 尝试下一次       # only when a click is swallowed
离开标志=英雄装备已离开
进入标志=英雄信息已到达 连续=2
状态=导航完成 前提=英雄信息页已就绪
```

There must be no navigation-complete message while the equipment tab remains selected.

- [ ] **Step 3: Monitor the entire hero-synthesis business loop**

Continue reading the live log and current frame until the run reaches its declared one-round completion or a saved failure diagnostic. Passing navigation or several heroes is not acceptance.

- [ ] **Step 4: Record the truthful result**

- If the complete round finishes, report the entry/exit evidence and final business-completion log.
- If it fails, preserve the latest screenshot and relevant log segment, add them as the next regression input, and report the exact unfulfilled contract field.
- Do not report the real workflow as fixed based only on offline tests.
