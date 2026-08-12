# 竞技场段位提升提示兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安全关闭启动或结算期间出现的竞技场段位提升提示。

**Architecture:** 从现场提取固定绿色晋级箭头，并与现有 `rank_confirm` 按钮组成双锚点。竞技场状态机与导航层共享检测函数。

**Tech Stack:** Python 3、OpenCV、NumPy、unittest/pytest

---

### Task 1：现场与红灯测试

- [x] 复制最新失败图为 `tests/fixtures/epic7_arena/rank_promotion_master.png`。
- [x] 裁剪晋级箭头为 `games/epic7/templates/global/arena_rank_promotion_arrow.png`。
- [x] 增加双锚点反例、竞技场状态机和导航启动恢复测试。
- [x] 运行新增测试并确认失败原因是功能尚未实现。

### Task 2：最小实现

- [x] 在 `games/epic7/arena.py` 增加共享双锚点函数。
- [x] 让 `ArenaStateMachine` 的段位确认复用共享函数。
- [x] 让 `Epic7Navigator` 识别并通过现有稳定两帧全局提示入口关闭。
- [x] 运行竞技场与导航专项测试。

### Task 3：离线验收

- [x] 运行所有受影响测试。
- [x] 运行 `python -m pytest -q`。
- [x] 运行 `python -m compileall -q .`。

> 当前目录不是 Git 仓库，因此没有提交步骤。
