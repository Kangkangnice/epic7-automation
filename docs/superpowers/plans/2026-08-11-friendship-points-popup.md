# “辅助英雄友情点数抵达”提示兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让主线状态机与导航安全关闭“辅助英雄友情点数抵达”提示并继续原流程。

**Architecture:** 从现场图提取标题和关闭文字两个模板，通过共享双锚点函数识别。主线返回无状态变更的关闭动作；导航在返回大厅、转场和等待页面的稳定两帧处理点中关闭提示。

**Tech Stack:** Python 3、OpenCV、NumPy、unittest/pytest

---

### Task 1：固化现场与红灯测试

**Files:**
- Create: `tests/fixtures/epic7_story/friendship_points_popup.png`
- Create: `games/epic7/templates/global/friendship_points_title.png`
- Create: `games/epic7/templates/global/friendship_points_close.png`
- Modify: `tests/test_epic7_story.py`
- Modify: `tests/test_navigation.py`
- Modify: `tests/test_project_layout.py`

- [x] 将 `runtime_diagnostics/epic7_story/20260811_155337_415438_return_home_failed.png` 原样复制为 fixture。
- [x] 从 fixture 裁剪标题 `(700,180)-(1280,275)` 和关闭区 `(870,885)-(1050,1010)` 为生产模板。
- [x] 增加双锚点缺一不可、主线状态不变、导航识别与关闭后继续大厅的测试。
- [x] 运行新增测试，确认因缺少共享识别和处理代码而失败。

### Task 2：实现共享双锚点识别

**Files:**
- Modify: `games/epic7/story.py`
- Modify: `games/epic7/navigation.py`

- [x] 增加 `find_friendship_points_popup_close(screen, title_template, close_template)`，仅搜索标题 `(600,150,800,180)` 和关闭区 `(750,840,450,190)`，两者都达到阈值才返回关闭锚点。
- [x] 在 `StoryTemplates` 和 `NavigationTemplates` 中加载同一组 `templates/global` 模板。
- [x] 在 `StoryStateMachine.next_action()` 最前方返回 `close_friendship_points_popup`，不修改状态和轮次。
- [x] 在导航的返回大厅、转场和等待页面循环中，仅在提示连续稳定两帧后点击关闭锚点并重置稳定观察。
- [x] 运行主线与导航专项测试，要求零失败。

### Task 3：离线验收

**Files:**
- No production changes unless a regression is directly caused by Task 2.

- [x] 运行 `python -m pytest -q`，要求零失败。
- [x] 运行 `python -m compileall -q .`，要求退出码 `0`。
- [x] 汇报结果和用户实测方式，不启动或控制模拟器。

> 当前目录不是 Git 仓库，因此没有提交步骤。
