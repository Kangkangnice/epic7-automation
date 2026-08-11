# Repository Cleanup and GitHub Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `auto_game_unified` 整理为文档完整、无旧版和运行产物、验证通过的正式工程，并发布到 `Kangkangnice/epic7-automation` 私有仓库。

**Architecture:** Git 仓库根目录保持为 `auto_game_unified`，只跟踪正式代码、模板、离线回归素材、测试和有效文档。工作区外层的旧工程与临时素材按批准的绝对路径删除；本地工具环境保留但不进入仓库。发布前依次执行敏感信息、大文件、测试和编译检查，首次提交推送到私有仓库 `main` 分支。

**Tech Stack:** Python 3、pytest、OpenCV、PowerShell、Git、GitHub CLI

---

### Task 1: 完善仓库文档和忽略规则

**Files:**
- Modify: `.gitignore`
- Create: `.gitattributes`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/EXTENDING.md`
- Create: `docs/TROUBLESHOOTING.md`
- Create: `docs/TEMPLATE_CAPTURE.md`
- Create: `docs/HUMAN_AI_WORKFLOW.md`

- [ ] **Step 1: 扩展 Git 忽略规则**

将 `.gitignore` 更新为只排除可再生成或本机专属的内容：

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
runtime_logs/
runtime_diagnostics/
.tools/
.workbuddy/
*.log
```

新增 `.gitattributes`，规范文本换行并把视觉素材标记为二进制：

```gitattributes
* text=auto
*.png binary
*.jpg binary
*.jpeg binary
```

- [ ] **Step 2: 重写项目入口说明**

调整 `README.md`，按以下顺序提供准确内容：

1. 项目用途及 `story`、`arena`、`expedition` 三条路线。
2. Windows、雷电模拟器窗口、Python 依赖和 `pip install -r requirements.txt`。
3. 干跑命令和必须提供正整数 `--max-cycles` 的实跑命令。
4. `P` 键停止、终端日志、滚动日志和失败诊断位置。
5. 从大厅开始导航、窗口可移动但比例不可改变的坐标规则。
6. 远征固定三阶段、传单角标不参与计数等当前限制。
7. 测试命令和人机协作手册链接。

不得保留“实跑可以省略 `--max-cycles`”或“实跑允许 `--start-state`”等过期说明。

- [ ] **Step 3: 更新架构与扩展说明**

在 `docs/ARCHITECTURE.md` 中补充：

- `navigation.py` 和 `expedition.py` 的目录职责。
- 三种模式各自的循环完成锚点。
- 两帧稳定、点击后目标页确认、战斗画面变化与心跳。
- 远征萤火唤醒和公开招募后的双层返回。
- `--start-state` 仅用于干跑诊断。

在 `docs/EXTENDING.md` 中引用新的模板采集和人机协作文档，要求所有新增页面先有完整截图回归样本。

- [ ] **Step 4: 编写排错和模板采集文档**

`docs/TROUBLESHOOTING.md` 必须覆盖：

- 如何查看终端、`runtime_logs/epic7_<mode>.log` 和 `runtime_diagnostics/epic7_<mode>/current.png`。
- 退出码 `0`、`1`、`2`、`130` 的含义。
- 页面不识别、点击后不转场、黑屏/遮挡、战斗 HUD 暂时隐藏、P 键停止的处理步骤。
- 提交问题时需要提供的命令、最后 30 行日志、当前帧和失败诊断。

`docs/TEMPLATE_CAPTURE.md` 必须覆盖：

- 保存完整窗口截图作为 fixture，局部裁剪只作为 template。
- 优先选文字、图标、按钮轮廓等稳定前景，排除章节背景、动画和角标数字。
- 搜索区域使用 `1982 x 1132` 窗口局部坐标，窗口移动不影响局部坐标。
- 正例、相似反例、动态背景变体和未知页面安全停止测试。
- 先失败测试、再最小实现、最后全量回归的顺序。

- [ ] **Step 5: 编写人类操作、AI 只读观测手册**

`docs/HUMAN_AI_WORKFLOW.md` 使用可直接复制给后续 AI 的规则，至少包含：

```text
默认权限：用户操作模拟器；AI只读截图、读日志、改代码和跑离线测试。
页面协议：AI一次只请求一个页面；用户准备好后回复“好了”。
采集协议：AI保存完整页面、裁剪稳定锚点、记录来源/目标/动作/禁止区域。
开发协议：先写失败测试，再写最少实现；未知页面先问，不重复盲试。
验收协议：AI完成离线回归，用户执行实跑；失败现场先保存再修复。
例外权限：AI只有在用户针对当前操作明确授权后，才可以控制模拟器。
```

同时提供“新路线信息模板”，字段为入口、主流程、可选弹窗、资源规则、禁止点击、完成锚点、超时预期和未采集页面。

- [ ] **Step 6: 检查文档一致性**

Run:

```powershell
rg -n "省略.*max-cycles|start-state.*live|difficulty [123]|两条路线" README.md docs
rg -n "HUMAN_AI_WORKFLOW|TEMPLATE_CAPTURE|TROUBLESHOOTING" README.md docs\EXTENDING.md
```

Expected: 第一条无过期说明；第二条能找到新文档链接。

- [ ] **Step 7: 提交文档**

```powershell
git add -- .gitignore .gitattributes README.md docs/ARCHITECTURE.md docs/EXTENDING.md docs/TROUBLESHOOTING.md docs/TEMPLATE_CAPTURE.md docs/HUMAN_AI_WORKFLOW.md
git diff --cached --check
git commit -m "document setup troubleshooting and AI workflow"
```

Expected: 只提交列出的文档和仓库规则。

### Task 2: 精确删除已批准的旧版和临时材料

**Files:**
- Delete outside repository: approved paths under `D:\AI\codex\auto_game`
- Delete ignored repository artifacts: `.pytest_cache/`, `__pycache__/`, `runtime_logs/`, `runtime_diagnostics/`

- [ ] **Step 1: 解析并验证所有删除目标**

使用以下显式列表，不使用递归通配符：

```powershell
$workspace = (Resolve-Path 'D:\AI\codex\auto_game').Path
$targets = @(
  'D:\AI\codex\auto_game\.pytest_cache',
  'D:\AI\codex\auto_game\arena_cycle_frames',
  'D:\AI\codex\auto_game\docs',
  'D:\AI\codex\auto_game\epic7_-master',
  'D:\AI\codex\auto_game\pytest-cache-files-a_dghcr2',
  'D:\AI\codex\auto_game\YYS-master',
  'D:\AI\codex\auto_game\__pycache__',
  'D:\AI\codex\auto_game\arena_after_auto_wait.png',
  'D:\AI\codex\auto_game\arena_after_battle_start.png',
  'D:\AI\codex\auto_game\arena_after_challenge.png',
  'D:\AI\codex\auto_game\arena_auto_enabled.png',
  'D:\AI\codex\auto_game\arena_cycle_complete.png',
  'D:\AI\codex\auto_game\arena_desktop_probe.png',
  'D:\AI\codex\auto_game\arena_game_probe.png',
  'D:\AI\codex\auto_game\arena_opponent_selected.png',
  'D:\AI\codex\auto_game\arena_pyautogui_coordinates.png',
  'D:\AI\codex\auto_game\arena_team_setup_focused.png',
  'D:\AI\codex\auto_game\arena_team_setup_pyautogui.png',
  'D:\AI\codex\auto_game\arena_window_foreground.png',
  'D:\AI\codex\auto_game\arena_window_probe.png',
  'D:\AI\codex\auto_game\_probe_arena.py',
  'D:\AI\codex\auto_game\auto_game_unified\.pytest_cache',
  'D:\AI\codex\auto_game\auto_game_unified\__pycache__',
  'D:\AI\codex\auto_game\auto_game_unified\runtime_logs',
  'D:\AI\codex\auto_game\auto_game_unified\runtime_diagnostics'
)
$resolved = foreach ($target in $targets) {
  if (Test-Path -LiteralPath $target) {
    $path = (Resolve-Path -LiteralPath $target).Path
    if (-not $path.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing path outside workspace: $path"
    }
    $path
  }
}
$resolved
```

Expected: 每一项都位于 `D:\AI\codex\auto_game\` 下；不包含 `.tools`、`.workbuddy`、`auto_game_unified\.git`、`tests` 或 `games`。

- [ ] **Step 2: 删除经过验证的精确目标**

只有 Step 1 输出满足预期时才运行：

```powershell
foreach ($path in $resolved) {
  Remove-Item -LiteralPath $path -Recurse -Force
}
```

这些删除为永久删除，恢复方式只有外部备份；用户已明确批准该范围。

- [ ] **Step 3: 验证保留与删除结果**

```powershell
$targets | ForEach-Object { if (Test-Path -LiteralPath $_) { throw "Still exists: $_" } }
@(
  'D:\AI\codex\auto_game\.tools',
  'D:\AI\codex\auto_game\.workbuddy',
  'D:\AI\codex\auto_game\auto_game_unified\.git',
  'D:\AI\codex\auto_game\auto_game_unified\games',
  'D:\AI\codex\auto_game\auto_game_unified\tests'
) | ForEach-Object { if (-not (Test-Path -LiteralPath $_)) { throw "Required path missing: $_" } }
```

Expected: 批准目标全部不存在，五个保留目标全部存在。

### Task 3: 仓库安全检查和全量验证

**Files:**
- Inspect: all files that will be tracked

- [ ] **Step 1: 扫描敏感信息**

```powershell
$secretHits = rg -l -i '(api[_-]?key|access[_-]?token|client[_-]?secret|password\s*[:=]|ghp_[A-Za-z0-9]{20,}|github_pat_)' . --glob '!.git/**'
if ($secretHits) { $secretHits; throw 'Potential secrets found' }
```

Expected: 无文件命中。命令不得输出任何凭据正文。

- [ ] **Step 2: 检查 GitHub 大文件限制**

```powershell
$tooLarge = Get-ChildItem -Recurse -File -Force |
  Where-Object { $_.FullName -notlike '*\.git\*' -and $_.Length -ge 90MB }
if ($tooLarge) { $tooLarge | Select-Object Length,FullName; throw 'Files too large for normal Git' }
```

Expected: 无单文件达到 90 MB；不需要 Git LFS。

- [ ] **Step 3: 运行全量测试**

```powershell
python -m pytest -q
```

Expected: exit code 0，所有测试通过，无 traceback。

- [ ] **Step 4: 运行编译检查**

```powershell
python -m compileall -q .
```

Expected: exit code 0。

- [ ] **Step 5: 清理验证产生的缓存并检查忽略规则**

```powershell
if (Test-Path -LiteralPath '.pytest_cache') { Remove-Item -LiteralPath '.pytest_cache' -Recurse -Force }
Get-ChildItem -Recurse -Directory -Filter __pycache__ |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
git status --ignored --short
```

Expected: 不出现 runtime 日志、诊断、Python 缓存或本地工具文件作为待提交内容。

### Task 4: 提交正式工程并创建私有 GitHub 仓库

**Files:**
- Track: all non-ignored files under `auto_game_unified`

- [ ] **Step 1: 审查完整提交范围**

```powershell
git status -sb
git add -- .gitignore .gitattributes README.md __init__.py main.py requirements.txt core docs games tests
git diff --cached --stat
git diff --cached --check
```

Expected: 暂存内容只来自正式工程；不包含 `runtime_logs`、`runtime_diagnostics`、缓存或外层旧项目。

- [ ] **Step 2: 提交正式工程**

```powershell
git commit -m "publish Epic Seven automation"
```

Expected: commit 成功，包含代码、模板、fixture、测试和文档。

- [ ] **Step 3: 确认 GitHub 登录和仓库名未占用**

```powershell
gh auth status
gh repo view Kangkangnice/epic7-automation --json nameWithOwner,isPrivate 2>$null
```

Expected: 登录账号为 `Kangkangnice`；目标仓库不存在。若已存在则停止，不覆盖或推送到未知仓库。

- [ ] **Step 4: 创建私有仓库并推送 main**

```powershell
gh repo create Kangkangnice/epic7-automation --private --source . --remote origin --push
```

Expected: 创建成功，`main` 已跟踪 `origin/main`。

- [ ] **Step 5: 验证远程状态和可见性**

```powershell
gh repo view Kangkangnice/epic7-automation --json nameWithOwner,isPrivate,defaultBranchRef,url
git remote -v
git status -sb
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Expected: `isPrivate` 为 `true`，默认分支为 `main`，本地 HEAD 与远程 `main` SHA 相同，工作区干净。
