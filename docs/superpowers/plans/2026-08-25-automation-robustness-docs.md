# Automation Robustness Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将英雄合成实证得到的进出标志、转场确认和失败留证原则沉淀为仓库级规范、六路线待办和可独立使用的操作手册。

**Architecture:** 本次只建立文档层契约，不改业务状态机。`USER_GUIDE.md` 面向运行者，`TRANSITION_CONTRACTS.md` 面向开发者和 Agent，`TODO.md` 保存按证据分级的后续工作；README 和现有架构文档只负责导航和边界说明。

**Tech Stack:** Markdown、Python CLI、PowerShell、pytest、Git。

---

## 文件结构

- Create: `docs/USER_GUIDE.md` — 安装、六模式运行、后端边界、诊断和退出码。
- Create: `docs/TRANSITION_CONTRACTS.md` — 进入/退出标志、三态分类、事务、日志和验收规范。
- Create: `docs/TODO.md` — 六路线、共享层与 PC 迁移的证据化待办。
- Modify: `README.md` — 修正模式数量，补齐命令并链接详细手册。
- Modify: `docs/ARCHITECTURE.md` — 把转场契约纳入分层架构。
- Modify: `docs/EXTENDING.md` — 新路线必须先填写转场契约。
- Modify: `docs/PC_TEMPLATE_MIGRATION.md` — 链接统一契约和 PC 待办。

### Task 1: 编写统一转场契约

**Files:**
- Create: `docs/TRANSITION_CONTRACTS.md`

- [ ] **Step 1: 写入动作契约的固定字段**

文档必须定义以下可复制模板：

```text
动作名称：
来源页面：
进入正向证据：
阻断证据/UNKNOWN：
点击坐标依据：
允许目标页面：
业务成功证据：
重试条件：
失败诊断：
循环计数影响：
```

- [ ] **Step 2: 写入通用安全规则**

明确记录：点击不等于成功、`SAFE / UNSAFE / UNKNOWN`、缺模板失败关闭、目标事务持续保留、动态证据限定区域、稳定入口才计数、日志不得把候选证据写成业务成功。

- [ ] **Step 3: 写入英雄合成参考实例**

实例必须覆盖翻卡、进入刻印、选择材料、SSS 中止并传送、合成结果关闭与返回英雄列表，且明确英雄动画不能作为材料或转场的单独证据。

- [ ] **Step 4: 检查文档内部结构**

Run:

```powershell
rg -n '^#|动作名称：|SAFE / UNSAFE / UNKNOWN|点击不等于成功' docs/TRANSITION_CONTRACTS.md
```

Expected: 标题、模板、三态分类和点击原则均至少出现一次。

### Task 2: 编写六路线审计待办

**Files:**
- Create: `docs/TODO.md`

- [ ] **Step 1: 建立证据等级和优先级定义**

文档必须区分 `已具备`、`部分具备`、`待实证`，并定义 P0 为安全或支持声明问题、P1 为转场契约和日志问题、P2 为复用与维护性问题。

- [ ] **Step 2: 记录六条路线审计**

每条路线必须包含：当前 Runner 类型、已有证据、缺口、下一步 fixture/测试、实机验收条件。已确认事实包括：

```text
主线/狗粮/辅助自动：继承 ModeRunnerBase，但 Action 只有 name 与 point。
竞技场/远征：独立 Runner，有目标状态检查，但未使用统一来源页/目标页/原因字段。
英雄合成：模拟器已具备专用转场契约并完整实跑一轮；PC 契约仍未启用。
```

- [ ] **Step 3: 记录共享层和 PC 迁移任务**

包括最小公共 `TransitionContract` 可行性评估、独立 Runner 收敛评估、`hero_synthesis.py` 大文件拆分前置条件，以及六路线 PC fixture/干跑/一轮/两轮验收矩阵。

- [ ] **Step 4: 禁止把推测写成故障**

Run:

```powershell
rg -n '已确认故障|必然失败|已经支持 PC' docs/TODO.md
```

Expected: 无输出；未实跑事项统一写作“待实证”或“风险”。

### Task 3: 编写使用手册

**Files:**
- Create: `docs/USER_GUIDE.md`
- Reference: `main.py`
- Reference: `launcher.py`
- Reference: `games/epic7/modes.py`

- [ ] **Step 1: 写入安装与运行前检查**

包含 Windows、Python、依赖安装、窗口前台、基准分辨率、运行目录、模拟器标题和禁止覆盖窗口。

- [ ] **Step 2: 写入六模式说明与启动命令**

列出 `story`、`arena`、`expedition`、`fodder`、`assist_auto`、`hero_synthesis`；包含启动器、干跑、模拟器一轮实跑和 `--window-backend pc` 示例。PC 示例必须标注为采集/开发用途，不得声明六路线已完成迁移。

- [ ] **Step 3: 写入运行闭环与停止规则**

说明运行前页面、日志中的当前页面/动作/目标页面、`P` 停止、完整一轮完成标志，以及 `0/1/2/130` 退出码。

- [ ] **Step 4: 写入诊断和常见问题**

包含日志路径、`current.png`、时间戳诊断图、点击未生效、未知页面、模板变化、PushPlus 905、PC 模板候选不等于支持。

- [ ] **Step 5: 静态核对 CLI 参数**

Run:

```powershell
python -m auto_game_unified.main --help
```

Workdir: repository parent.

Expected: 帮助中包含六个 mode、`--window-backend`、`--live`、`--confirm` 和 `--max-cycles`。

### Task 4: 更新文档入口与过时描述

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/EXTENDING.md`
- Modify: `docs/PC_TEMPLATE_MIGRATION.md`

- [ ] **Step 1: 修正 README 模式列表和启动器菜单**

README 顶部改为六条路线，补充 `assist_auto` 和 `hero_synthesis`；启动器菜单改为六项；详细操作链接到 `docs/USER_GUIDE.md`。

- [ ] **Step 2: 补齐 README 命令**

干跑和实跑示例均覆盖六种 mode。英雄合成说明默认 `max_cycles=1` 的安全边界，辅助自动说明从已支持队伍页面启动且不走大厅导航。

- [ ] **Step 3: 更新架构与扩展指南**

`ARCHITECTURE.md` 链接 `TRANSITION_CONTRACTS.md`；`EXTENDING.md` 在编码前清单中要求来源页面、进入证据、目标页面、成功证据和失败诊断。

- [ ] **Step 4: 更新 PC 迁移入口**

`PC_TEMPLATE_MIGRATION.md` 链接 `TRANSITION_CONTRACTS.md` 和 `TODO.md`，强调同一业务流程在 PC 上必须重新取得进入/退出证据。

### Task 5: 一致性、测试与提交

**Files:**
- Verify: all modified Markdown files
- Verify: entire repository

- [ ] **Step 1: 检查 Markdown 相对链接**

Run a read-only PowerShell link checker over all tracked Markdown files.

Expected: 本次新增或修改文档中的本地相对链接全部存在；外部 URL 跳过。

- [ ] **Step 2: 检查差异格式**

Run:

```powershell
git diff --check
git status --short
```

Expected: `git diff --check` 无输出；状态只包含计划内 Markdown 文件。

- [ ] **Step 3: 运行编译检查**

Run:

```powershell
python -m compileall -q .
```

Expected: exit code 0，无输出。

- [ ] **Step 4: 运行全量测试**

Run:

```powershell
python -m pytest -q
```

Expected: exit code 0，测试总数不低于基线 `548 passed, 71 subtests passed`。

- [ ] **Step 5: 提交文档整理**

Run:

```powershell
git add README.md docs/USER_GUIDE.md docs/TRANSITION_CONTRACTS.md docs/TODO.md docs/ARCHITECTURE.md docs/EXTENDING.md docs/PC_TEMPLATE_MIGRATION.md docs/superpowers/plans/2026-08-25-automation-robustness-docs.md
git commit -m "docs: add automation robustness handbook"
```

Expected: commit succeeds on local `main` and `git status --short` is empty.
