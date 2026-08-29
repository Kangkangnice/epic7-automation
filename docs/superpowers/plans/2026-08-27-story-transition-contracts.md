# 主线转场事务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模拟器主线仅在可观察的页面转场与业务完成证据成立后推进状态。

**Architecture:** `StoryStateMachine` 负责从单帧生成带来源/目标契约的候选动作；既有 `ModeRunnerBase` 负责连续两帧目标确认、来源仍在时有限重试和诊断。主线禁用未知画面唤醒点击，保证来源离开后仅等待；战斗阶段继续复用 `BattleSupervisor`，不修改公共 Runner 或其他路线。

**Tech Stack:** Python、OpenCV 模板匹配、unittest、pytest。

---

### Task 1: 固化提前推进缺陷

**Files:**
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_story_runner.py`

- [ ] 写入失败用例：`prepare_battle` 被识别时，候选动作的来源仍为关卡入口，未确认队伍页前机器状态不变。
- [ ] 运行该用例，预期失败，因为当前 `next_action()` 会立即写入 `StoryState.TEAM`。
- [ ] 写入失败用例：来源离开但目标尚未稳定时，Runner 不会再次点击旧坐标。
- [ ] 运行该用例，预期失败，因为当前主线依赖通用 Runner 的动作重试。

### Task 2: 页面观察与动作契约

**Files:**
- Modify: `games/epic7/story.py`
- Test: `tests/test_epic7_story.py`

- [ ] 为 `StoryAction` 增加 `source_page`、`target_pages` 与 `reason`。
- [ ] 增加仅使用现有模板的主线页面观察；页面不明或冲突时不给点击候选。
- [ ] 增加 `commit(action, target_page)`，仅允许声明的来源和目标组合提交。
- [ ] 将准备战斗、助手选择、快速战斗切换、开始任务、结算关闭和奖励关闭改为候选动作，移除点击前的状态推进。
- [ ] 运行 Task 1 和页面识别测试，预期通过。

### Task 3: 主线事务接入既有 Runner

**Files:**
- Modify: `games/epic7/story.py`
- Test: `tests/test_story_runner.py`

- [ ] 让 `StoryAction` 的来源页、目标页接入 `ModeRunnerBase` 的两帧 `StableObservation`。
- [ ] 禁用主线的未知画面唤醒点击，保证来源离开、目标未稳定时只等待；保留来源仍在时最多四次点击。
- [ ] 在目标未确认、冲突和超时时记录动作、来源、允许目标、尝试次数和诊断路径。
- [ ] 保留 `BattleSupervisor` 作为战斗后的唯一监督器。
- [ ] 运行事务回放测试，预期通过。

### Task 4: 业务完成与体力安全

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_story_runner.py`

- [ ] 写入失败用例：结算未退出前不得增加 `completed_cycles`。
- [ ] 写入失败用例：体力确认点击前不得增加 `stamina_replenished`。
- [ ] 在下一关入口连续两帧确认后增加循环计数；在体力确认的允许目标出现后增加次数。
- [ ] 运行相关用例，预期通过。

### Task 5: 回归验证与文档

**Files:**
- Modify: `docs/TODO.md`
- Test: `tests/test_epic7_story.py`
- Test: `tests/test_story_runner.py`
- Test: `tests/test_quick_battle_route_integration.py`

- [ ] 运行主线识别、Runner、快速战斗集成与入口测试。
- [ ] 执行编译和差异检查。
- [ ] 更新待办中的主线证据状态，记录待用户完成的一轮、两轮实机验收。
