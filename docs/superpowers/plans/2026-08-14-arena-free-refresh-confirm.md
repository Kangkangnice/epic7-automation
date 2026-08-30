# Arena Free Refresh Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安全确认竞技场免费刷新弹窗，并继续等待新的可挑战对手列表。

**Architecture:** 在竞技场状态机中增加只返回三锚点联合匹配结果的识别函数；刷新等待器调用该函数并限制最多两次点击。现有列表判断、超时和诊断路径保持不变。

**Tech Stack:** Python、OpenCV、unittest/pytest

---

### Task 1: 现场样本与三锚点识别

**Files:**
- Create: `tests/fixtures/epic7_arena/free_refresh_confirm_live_20260814.png`
- Modify: `tests/test_epic7_arena.py`
- Modify: `games/epic7/arena.py`

- [ ] 复制现场失败截图到固定回归样本。
- [ ] 编写真实弹窗匹配以及缺少任一锚点时拒绝匹配的测试。
- [ ] 运行聚焦测试并确认旧代码因缺少识别接口而失败。
- [ ] 从现场图裁取三个稳定模板，实现联合匹配函数。
- [ ] 重新运行聚焦测试并确认通过。

### Task 2: 刷新等待器处理确认弹窗

**Files:**
- Modify: `tests/test_arena_runner.py`
- Modify: `games/epic7/arena.py`

- [ ] 编写等待器确认免费刷新后继续等列表的测试。
- [ ] 编写同一确认框最多点击两次的测试。
- [ ] 运行测试并确认旧代码失败。
- [ ] 在 `_wait_until_safe_list` 中加入稳定确认、两次点击限制和日志。
- [ ] 运行竞技场聚焦测试并确认通过。

### Task 3: 验证与集成

**Files:**
- Modify: `tests/test_project_layout.py`

- [ ] 更新固定样本清单。
- [ ] 运行 `python -m pytest tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_project_layout.py -q`。
- [ ] 运行 `python -m pytest tests -q`。
- [ ] 提交修复、快进合并到本地 `main`，并从 `main` 重新运行全量测试。
