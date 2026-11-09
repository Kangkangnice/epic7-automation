# 参与贡献

欢迎提交 Issue 和 Pull Request。本项目是**个人维护的免费开源工具**，评审以「长期能不能维护」为准，不以「功能多不多」为准。

## 先读这三份

| 想做什么 | 先读 |
|---|---|
| 新增一条自动化路线 | [docs/EXTENDING.md](docs/EXTENDING.md) |
| 修改识别、点击、导航、重试逻辑 | [AGENTS.md](AGENTS.md) 与 [docs/TRANSITION_CONTRACTS.md](docs/TRANSITION_CONTRACTS.md) |
| 只是使用、遇到报错 | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 与 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## 本项目接受什么

- 修复某条路线在真实游戏画面上认不出 / 点错 / 卡住的问题（**必须附现场帧**）；
- 新增一条「每天都要做、很枯燥」的 PVE 日常路线；
- 游戏改版后的模板更新与判据修复；
- 桌面界面、日志、诊断、文档的改进。

## 本项目不接受什么

- **PVP 自动对战**。本项目定位是 PVE 视觉辅助；
- 读取游戏内存、修改客户端文件、改网络数据包、反检测或绕过游戏安全机制；
- 自动购买钻石 / 人民币等付费货币的路径（现有路线里凡是涉及付费货币的分支都是**永久禁止**或**只取消不购买**）；
- 上传日志、截图、遥测到任何服务器的功能（本项目默认完全本地运行）；
- 「顺便重构一下」的大范围改动。评审会要求拆成可独立验证的小步。

## 本地环境

- Windows 64 位；
- Python 3.10 及以上；
- 仓库目录必须叫 `auto_game_unified`，并且**从它的父目录**运行：

```powershell
cd D:\AI\codex\auto_game
python -m pip install -r auto_game_unified\requirements-dev.txt
python -u -m auto_game_unified.desktop
```

直接跑 `auto_game_unified/main.py` 会因为包导入路径失败，这是预期行为，不是 bug。

## 跑测试

```powershell
cd D:\AI\codex\auto_game
python -m pytest -q auto_game_unified/tests
python -m compileall -q auto_game_unified
python -m ruff check auto_game_unified
python -m mypy --config-file auto_game_unified/pyproject.toml
```

⚠️ 这四条与 CI（`.github/workflows/tests.yml`）**逐字一致**：mypy 的 `files` 路径按仓库父目录
解析，进到包目录里再跑 `python -m mypy` 会读错配置（见 `pyproject.toml` 的注释）。

提交门禁是仓库自带的 `tools/check.py`，它按**改动范围**决定跑什么：

| 改了什么 | 跑什么 | 大约多久 |
|---|---|---|
| 只有文档 / `.github/` / 图片 | 只做编译检查 | 几秒 |
| 单条路线的模块与它的测试 | 该路线的测试 | 1~2 分钟 |
| **共享模块**（`core/`、`desktop/`、`main.py`、`modes.py`、`navigation.py` 等） | **定向测试**（按文件 stem 映射；映射不到只提示） | 1~2 分钟 |

装钩子（每个 clone 各装一次）：

```powershell
python auto_game_unified/tools/check.py --install-hook
```

**提交那一次由钩子跑，不要手工先跑一遍再提交** —— 同一份暂存内容、同一套测试，会白等一次全量。手工跑 `check.py` 只用于开发中途想看结果。

`git commit --no-verify` **默认禁止**：钩子是这套流程里唯一的强制关卡。

### 几个容易踩的细节（2026-11-08 从 `AGENTS.md` 移来）

- **手工跑完只要又改了文件，那次结论就作废**，以钩子的结论为准
  （钩子正因此兜住了 2026-09-29 那次「跑完门禁之后又改了文档」）。
- **别把 `check.py --vs HEAD` 当日常姿势**：它取的是「工作区相对 HEAD 的**全部**改动」，
  上一轮没提交的东西也算进去，会把测试面放大，跟这次改了多少无关。
  2026-09-25 实测：只想验竞技场一行改动，因为上一轮的 `main.py` 还躺在工作区，
  连续两次全量 408s / 457s，而局部只要 28.7 秒。⇒ **把旧改动提交掉**，范围自然收窄。
- **改共享模块最费时间**（按文件名映射会带出很多路线的测试）：把这类改动**攒在一起、
  一次提交**，别拆成好几次各跑一遍。先例是批次 2~5 合并成一次。
- ⚠️ **多个 Agent 并行时怎么不打架**（2026-11-09 定）：
  - **首选**：一个 Agent 一个独立工作区（`git worktree`）或独立分支，各自提交、合并时解冲突。
    规范里**不允许**两个会话共用一个工作区改同一批文件 —— 编号撞车、索引重复行、
    变更记录混流、按行号编辑失效，都是这么来的。
  - **确实只能共用一个工作区时**：`git add` 只加自己这次的文件，**绝不 `git add -A`**；
    共享文件（`CHANGELOG.md`、`docs/README.md`、`docs/STATUS.md`、`AGENTS.md`、
    `docs/decisions/` 编号）要么**指定单一写入者**，要么用追加式分区，别两边同时重写。
    共改过同一份文件时，提交前先确认对方的内容还在 —— 那次提交会**整份**带走双方改动，
    于是可能出现「变更记录说做了 5 件事、仓库里只落地 1 件」。
  - 决策编号一律走 `python -m auto_game_unified.tools.new_decision`，不要手取号。
  - 提交信息里若本次改动命中了复审规则，要加一行 `Doc-reviewed:`（钩子会提示清单）。
- **默认不跑全量**（2026-10-25 用户拍板）：`--full` 只在 PR 合并、发布前或明确要兜底时用；
  CI 的全量也只在这些环节跑，平时 push 不再重复一遍（见下面「日常怎么改代码」）。
- 静态检查（ruff + mypy）每次都跑，几秒钟；没装会大声跳过，装了就必须过。
  规则范围在 `pyproject.toml`，mypy 目前**只覆盖 `core/` 与导航链数据模块**。
  2026-09-30 上线第一次跑就抓到 `core/window.py` 里一个真 bug
  （`@staticmethod` 里用 `self`，NameError 被静默吞掉，「尽力还原窗口」一次都没执行过）。

## 打包（改动了打包配置才需要）

```powershell
python packaging/build.py
```

它会做四件事：PyInstaller 目录版打包 → 确认 spec 剔掉的 videoio ffmpeg 二进制
真没进产物 → 跑一次 `Epic7AutoAssistant.exe --self-check`（检查产物目录可写、
模板在不在、全部路线能不能加载 —— 条数以 `desktop/catalog.ROUTES` 为准）→ 打免安装 ZIP 并写 `SHA256SUMS.txt`。
产物在 `packaging/dist/`（已 gitignore，不进历史）。

`--no-build` 复用已有目录版，只重打 ZIP；`--skip-smoke` 跳过自检。

**默认只出免安装版**（2026-10-20 起，用户拍板）：用户解压 ZIP、双击 `Epic7AutoAssistant.exe`
就能跑。想要安装包再加 `--installer`，那一步要 **Inno Setup 6**，没装就自动跳过。单独编也可以：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "/DMyAppVersion=0.1.0" packaging\installer.iss
```

在 Git Bash 里调 ISCC 必须加 `MSYS2_ARG_CONV_EXCL='*'`，否则 `/D...` 会被当成路径转换，
报 `You may not specify more than one script filename`。

四个容易踩的点：

- 打包版的运行产物写在 `%LOCALAPPDATA%\Epic7AutoAssistant`，源码运行仍写在仓库目录 ——
  规则在 `core/data_paths.py`，别在别处再写一份；
- `modes.py` 的加载期自查要用 `inspect.getsource` 读源码，所以 spec 里
  `module_collection_mode={"auto_game_unified": "py"}` **不能改成压 pyc**，
  否则打包版一启动就 `OSError: could not get source code`；
- `installer.iss` 必须是 **UTF-8 带 BOM**，否则 Inno 按 ANSI 读，中文全乱码；
- `packaging/languages/ChineseSimplified.isl` **不要删**。Inno 官方发行版不带简体中文，
  这份是从 issrc 的 `Files/Languages/Unofficial/` 取的第三方翻译，`installer.iss`
  的 `[Languages]` 直接引它。删了脚本编不过。

安装版的行为（改 `installer.iss` 前先确认这几点仍然成立）：

- **按用户安装、不提权**：`PrivilegesRequired=lowest` 时 `{autopf}` 自动展开成
  `%LOCALAPPDATA%\Programs\Epic7AutoAssistant`，全程不弹 UAC，非管理员账户也能装。
  想装到 `Program Files` 得显式传 `/ALLUSERS`；
- **卸载保留用户数据**：`%LOCALAPPDATA%\Epic7AutoAssistant` 下的日志与诊断不删，
  那是用户自己的运行记录；
- 打完包至少走一遍「装 → 跑 `--self-check` → 卸」，别只看 ISCC 返回 0 就当成能用。

## 新增一条路线的准入条件

缺任何一样都算没做完：

1. **模板**：放进 `games/epic7/templates/<路线>/`，从当前客户端真实画面裁切，基准画布 `1982 x 1132`；
2. **区域**：每个模板都必须有搜索区域，禁止整屏盲找；
3. **判据**：能证伪 —— 要说得清「靠哪一维把外观相似、语义不同的页面/按钮分开」，不是把阈值调小一点；
4. **夹具**：真机帧放进 `tests/fixtures/epic7_<路线>/`，每个页面至少一张正样本，另附能区分相邻页面的负样本；
5. **状态机与 Runner**：优先复用 `runner_base` / `transactional_runner_base` / `battle_controls` / `pre_battle` / `global_popups`，不要自己再造一套；
6. **测试**：覆盖页面唯一性、转场契约、资源耗尽与失败关闭；
7. **登记**：`modes.py::MODE_SPECS`、`desktop/catalog.py::ROUTES`、`daily_tasks.py::DAILY_TASKS`（进默认清单才需要）、`tools/check.py::ROUTE_KEYWORDS`。**导航链不再改 `navigation.py`** —— 链条与接力白名单声明在 `MODE_SPECS["<路线>"].navigation_plan` 这份数据里，`navigation.py` 只留执行器。

**失败关闭是底线**：认不出的页面不许猜、不许连点、不许「等超时算过」。认不出就保存诊断并停下，退出码 `1`。

## 素材规范

- 模板**不许包含会变的内容**：玩家昵称、体力数值、金币钻石余额、时间、随机角色名；
- 判据型模板**没有「可选」这一档** —— 文件缺失必须让程序在加载期就报错，不能静默降级；
- 新增或替换图片，`git add` 之后、提交之前跑一次无损压缩：

```powershell
python tools/compress_images.py --staged --apply
git add <刚压过的文件>
```

不要拿它「顺手压一遍存量」：历史里的旧 blob 一个不少，`git clone` 反而更大。

## 提交信息

采用 `类型(范围): 一句话`，正文用中文写清「为什么改」：

```
fix(epic7): 战斗菜单判页按「哪个标签被选中」分三页 —— 修迷宫强化石误判
feat(desktop): 每日任务面板三分组 + 批量勾选
docs(chore): 竞技场实跑记录更新；README 与手册同步
```

## 日常怎么改代码（必须走 PR）

`main` 受保护，**不能直接 push**。一次改动走这四步：

```powershell
git checkout -b fix/arena-team-page
# 改代码；提交时钩子会自动跑定向测试，不用手工再跑一遍
git add -- games/epic7/arena.py      # 精确加文件，别用 git add -A
git commit -m "fix(arena): 队伍页误判讨伐准备页"
git push -u origin HEAD
gh pr create --base main --fill
# 等 CI 的 pytest 变绿（PR 会跑一次全量，约 17 分钟）
gh pr merge --squash
```

三层检查各自负责什么：

| 什么时候 | 跑什么 | 谁在跑 |
|---|---|---|
| 每次 `git commit` | 按改动范围的定向测试（几秒~2 分钟） | 本机提交钩子 |
| 每次 `git push`（含功能分支） | 编译、静态检查、文档治理门禁 | CI，几分钟 |
| PR 合进 `main` 前 | **全量测试** | CI，约 17 分钟 |
| 发版打 `v*` tag / 手动触发 / 每周一 | 全量测试（兜底） | CI |

⚠️ 单人仓库的「强审」= 必须开 PR + CI 必绿 + 禁止直推 / 强推 / 删分支 +
所有 review 对话必须解决。审批人数目前是 **0**：GitHub 不允许 PR 作者批准自己的 PR，
设成 1 会把你自己锁死。等有第二个账号或协作者，再把它调成 1。

⚠️ 改共享模块时本机钩子只跑定向；别拆成好几次提交各跑一遍，攒一起提交。

## 提交 PR 前自检

- [ ] 没有提交 `runtime_logs/`、`runtime_diagnostics/` 里的运行产物；
- [ ] 没有提交包含个人信息的截图（昵称、QQ、角色名）；
- [ ] 没有把环境变量、Token、AppSecret 写进代码或文档；
- [ ] 没有删除 `tests/fixtures/` 里被其它测试引用的图；
- [ ] 改了共享模块的话，知道这次提交默认跑定向测试（`--full` 才跑全量）；
- [ ] 文档跟着代码一起改（README / 用户手册 / 路线矩阵）。

## 许可证

提交即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
注意：MIT 只覆盖原创代码，**不覆盖游戏画面与从中裁切的模板**，详见 [NOTICE.md](NOTICE.md)。
