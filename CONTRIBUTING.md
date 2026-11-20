# 参与贡献

欢迎提交 Issue 和 Pull Request。先用[当前现状](docs/STATUS.md)确认路线与后端的支持范围，再按下面的入口开始。

| 任务 | 入口 |
| --- | --- |
| 日常使用或报告故障 | [使用手册](docs/USER_GUIDE.md)、[排错手册](docs/TROUBLESHOOTING.md) |
| 新增路线或移植 PC | [新增路线](docs/EXTENDING.md)、[PC 接入](docs/PC_TEMPLATE_MIGRATION.md) |
| 修改识别、导航或点击 | [仓库约束](AGENTS.md)、[转场契约](docs/TRANSITION_CONTRACTS.md)、[实机验收](docs/howto/live_verification.md) |
| 评审、决策或发布 | [项目治理](GOVERNANCE.md)、[发布手册](docs/howto/release.md) |
| 游戏更新、维护旧路线或补英雄 | [游戏更新手册](docs/howto/game_update.md)、[英雄图鉴](docs/maintenance/hero_roster.md) |
| 报告安全或隐私问题 | [安全政策](SECURITY.md) |

接受日常路线、识别和输入修复、桌面与诊断改进。改动应能独立说明、验证和回退。
本项目通过窗口画面和输入进行视觉辅助。贡献范围排除游戏内存读取、客户端或数据包修改、反检测、
绕过游戏安全机制、自动 PvP 功能扩展，以及自动上传运行日志和截图。资源动作按
[安全证据矩阵](docs/SAFETY_MATRIX.md)中的权限和路线规则验收。

## 本地开发

在 Windows 64 位上使用 CI 基线 Python 3.11，先 fork 再克隆。仓库目录命名为
`auto_game_unified`。在它的父目录运行 Python 模块和测试。

```powershell
git clone <你的 fork 地址> auto_game_unified
py -3.11 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r auto_game_unified\requirements-dev.txt
& $python auto_game_unified/tools/check.py --install-hook
$env:Path = (Resolve-Path -LiteralPath .\.venv\Scripts).Path + ';' + $env:Path
& $python -m auto_game_unified.main --help
```

## 按改动选测试

从仓库父目录执行。调试失败用例时可以指定一个 pytest 节点，几次小改后用选择器检查完整的受影响范围。

```powershell
& $python -m auto_game_unified.tools.check --plan --files games/epic7/pet_adoption.py
& $python -m pytest -q auto_game_unified/tests/test_pet_adoption.py::test_mixed_free_evidence_stops_instead_of_guessing
```

| 时机或影响 | 执行范围 |
| --- | --- |
| 开发中改一个判据或修一个错误 | 先跑失败用例及最相似反例。需要整条路线反馈时用 `check --files <路径>`。 |
| 本地提交 | 钩子运行静态检查和暂存文件对应的测试。宠物领养逻辑查路线、注册和安全约束；宠物屋标题素材还会查导航。 |
| 普通分支 push | CI 核对编译、静态、治理和图鉴。可在分支上迭代，到准备评审时开 PR。 |
| 只改项目 Markdown、英雄头像或分类、已登记的宠物／企鹅／装备回放 PNG 或相应测试的 PR | 在合并结果上运行治理门禁及所有受影响的测试。转场、接力和界面文案等规范另有对应契约测试。 |
| 只改已核验的独立行为及其回放 | 首个试点是主线补星选卡模块 `games/epic7/story_star_cards.py`、`tests/test_story_star.py` 和 `tests/fixtures/epic7_story_star_pc/` 的直接 PNG。可与文档同改。本地与 PR 都检查补星回放、注册、桌面预检、接力、转场、安全停止和源码边界。 |
| 含补星主循环、其他未登记的运行代码、生产页面模板、共享夹具、依赖、打包、CI 或其他未登记路径的 PR | 在合并结果上运行完整离线套件。多种改动取较严的一档；连续推送取消同一 PR 旧版本的检查。 |
| 版本标签、每周回归、维护者手动触发 | 无条件全量。需要本机复现时用 `& $python -m pytest -q --durations=10 auto_game_unified/tests`。 |

本地预览用 `--plan --files <仓库相对路径>`。已提交的改动可用 `--plan --since origin/main`。
新增未跟踪的文件需显式列出或暂存。暂存区为空时默认读取整个已跟踪工作区，多任务并行时优先显式指定路径。
本地提示未映射时，手工指定覆盖它的测试；PR 选择器对未知路径执行全量。维护者扩大定向范围前应核对直接消费者、
跨路线契约及反例，并给分层选择增加回归测试。具体放行条件见[按玩家行为验收](docs/decisions/0011-behavior-based-regression.md)。路线按行为变化提交目标客户端实机闭环和风险回放。
提交含需要复审的修改时，按钩子提示在提交消息加入 `Doc-reviewed:` 和实际复审结果。
在仓库根目录可用 `python tools/doc_review.py --staged` 查看清单。

## 路线与素材

先写清入口、页面流、可选弹窗、授权消耗、真实完成点和耗尽后行为。每条路线交付清单和注册步骤以
[新增路线指南](docs/EXTENDING.md)为准。使用真实客户端证据和最相似反例覆盖误判，支付、开战、制作等动作
须明确验证当前允许条件和业务结果。未知画面按转场契约安全停止。

素材与截图须去除账号、昵称、QQ、通知、余额等不必要信息，保留影响判定的证据。把局部模板与完整回归帧分开。
模板取自稳定内容，声明搜索范围，判据型模板缺失应尽早报错。图片暂存后，在仓库根目录用
`python tools/compress_images.py --staged --apply` 无损压缩本次涉及的文件，再重新暂存这些文件。

需要真机时按[实机验收手法](docs/howto/live_verification.md)确认目标、权限、消耗和结果。
需要多会话并行时优先分支与独立工作树。共用工作树时明确各自负责的文件，逐个暂存。
新增架构决策使用 `python -m auto_game_unified.tools.new_decision` 从父目录生成编号。

## 从提交到合并

从最新 `main` 创建主题分支，逐个暂存本次改动。提交采用 `类型(范围): 一句话`，正文写清目标与原因。
推送至有写权限的远端并向主仓库打开 PR。说明变更范围、测试结果，以及实际验证过的后端、分支和业务结果。
保留未验证范围，按[项目治理](GOVERNANCE.md)交接。

仓库的 `main` 通过 PR 合并，必需检查名为 `pytest`。维护者检查 CI、审阅意见和适用的实机证据后决定合并。
打包改动的验收和正式发布见[发布手册](docs/howto/release.md)。

## 打包（改动了打包配置才需要）

**先取第三方代码**（次元探查的内置 chaos 流程）。它**不随 Git 分发**：上游仓库没有
LICENSE 文件，重分发依据未确认，所以仓库里只放清单（`packaging/vendor_lock.json`
记着上游地址、精确 commit 与逐个文件的 SHA-256），构建前按 commit 取回：

```powershell
python tools/fetch_vendor.py            # 取到 ..\vendor\e7auto；已存在就只校验
python tools/fetch_vendor.py --check    # 只校验，不联网
python tools/fetch_vendor.py --source D:\mirrors\E7auto.git   # 内网镜像/离线副本
```

缺文件、摘要不符、清单外文件都会返回非零并逐条列出；脚本**不会覆盖**已存在的目录。
随包只收 `src`、`config`、`assets/templates` 三段，`.git`、测试、文档与缓存都不进产物。

清单校验的是**固定 commit 的 Git blob 原始字节**：取回时用 `git ls-tree` +
`git cat-file --batch` 直接写对象库里的字节，不经过 `git checkout` 或 `git archive`
（这两者会按本机 `core.autocrlf` / `core.eol` 转换行）。所以 `core.autocrlf=true`
与 `false` 取回的字节一致，**不需要改全局 Git 配置**。旧检出如果字节不同（例如早先
用 CRLF 检出过），删掉 `..\vendor\e7auto` 重跑一次取回即可。

```powershell
python packaging/build.py
```

它会先校验源码侧清单 → PyInstaller 目录版打包 → 核对产物里的第三方文件**正好**是
清单那一份（多一个文件、少一个文件、同名文件改一个字节都会停下）→ 跑一次
`Epic7AutoAssistant.exe --self-check`（检查运行产物目录可写、模板在不在、全部路线
能不能加载、第三方模块与配置能不能加载）→ **打 ZIP 前再核对一次**，失败不产出新
ZIP → 打免安装 ZIP 并写 `SHA256SUMS.txt`。`--no-build` 复用旧 dist 时没有源码可验，
但压缩前同样过内容门禁。另有一条 `check_pruned_binaries` 守着 spec 剔掉的
videoio ffmpeg 二进制真没进产物。

⚠️ 直接调 `python -m PyInstaller packaging/epic7_auto_assistant.spec` **不做**清单
校验，缺文件时产物会少一段而不报错；构建请走 `packaging/build.py`。

产物在 `packaging/dist/`（已 gitignore，不进历史）。

`--no-build` 复用已有目录版，只重打 ZIP（仍会校验第三方内容）；`--skip-smoke` 跳过自检。

**验证冻结版的 worker 交接**（离线，不需要游戏、不发任何输入）：

```powershell
python tools\verify_frozen_worker.py --exe packaging\dist\Epic7AutoAssistant\Epic7AutoAssistant.exe
```

它用桌面端同一条 `WorkerController.start()` 启动产物，子进程跑隐藏参数
`--offline-probe`：只观察停止信号，**不装配路线、不截图、不点击**，即使游戏已经打开
也不会碰它。期望两次结果：到点正常结束（退出码 0）；父进程写 `stop.signal` 后，
子进程读到并退出 130。同时核对只有 `Epic7AutoAssistant.exe` 一个子进程、命令行带
`--worker`、没有窗口、输出能回传父进程。

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

## 人和 AI 怎么配合做新路线

（原 `docs/HUMAN_AI_WORKFLOW.md` 里仍然有效的约定并入本节。那份文档开头的
「用户操作、AI 只读观测」是**已作废**的历史分工，别照着做；实机权限以
[`docs/howto/live_verification.md`](docs/howto/live_verification.md) 为准。）

- **先把业务说清楚，再动手**：由用户用自然语言说明「从大厅怎么进、正常流程的页面顺序、
  可能出现的剧情 / 奖励 / 确认 / 断线弹窗、哪些资源允许消耗、哪些购买路径需明确授权、
  一轮完成的真正锚点、资源耗尽时停还是恢复」。先整理成页面清单，明确哪些页面还没采集，
  **不要一上来猜坐标**。
- **一次只确认一个页面**：把游戏停在那一页，采一张现场帧、写一条用例，确认后再翻下一页。
- **碰到这些必须停下来问，不要自己拍板**：同一种现象试了很多次仍解释不了；画面可能是
  待机 / 动画 / 账号差异；下一步涉及资源购买、放弃战斗或不可逆选择；当前证据分不清
  两个相似页面；**需要改变已经锁定的业务流程或安全边界**。提问时写清「现在看到什么、
  最后一步做了什么、有几种解释、要用户确认哪一件事」，别只说「卡住了」。
- **交接给下一位**：先读 `docs/README.md`、实机手法、架构、排错与目标路线的测试，
  再看最近日志与夹具，分清哪些页面来自当前客户端、哪些还没采到。

需求可直接按这几项填写：路线名称 / 大厅入口 / 主流程 / 可选弹窗 / 允许消耗的资源 /
需明确授权的按钮 / 战斗与加载预期时长 / 一轮完成页面 / 资源耗尽行为 / 已知未覆盖页面。

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
git add -- games/epic7/arena.py      # 精确加文件，不要用 git add -A
git commit -m "fix(arena): 队伍页误判讨伐准备页"
git push -u origin HEAD
gh pr create --base main --fill
# 等 CI 的 pytest 变绿（PR 跑哪一档见上文「按改动选测试」）
gh pr merge --squash
```

每次提交由本机钩子跑定向测试；push 后由 CI 跑编译、静态检查与治理门禁。PR 执行哪一档
按上文「按改动选测试」判定 —— 只改已核验的独立行为走定向，含共享模块、未登记路径或发布配置的
改动走完整离线套件。发版标签、每周回归与手动触发无条件全量。

⚠️ 单人仓库的「强审」= 必须开 PR + CI 必绿 + 禁止直推 / 强推 / 删分支 +
所有 review 对话必须解决。审批人数目前是 **0**：GitHub 不允许 PR 作者批准自己的 PR，
设成 1 会把你自己锁死。等有第二个账号或协作者，再把它调成 1。

⚠️ 改共享模块时本机钩子只跑定向；不要拆成多次提交各跑一遍，攒在一起提交。

## 提交 PR 前自检

- [ ] 没有提交 `runtime_logs/`、`runtime_diagnostics/` 里的运行产物；
- [ ] 没有提交包含个人信息的截图（昵称、QQ、角色名）；
- [ ] 没有把环境变量、Token、AppSecret 写进代码或文档；
- [ ] 没有删除 `tests/fixtures/` 里被其它测试引用的图；
- [ ] 改了共享模块的话，知道这次提交默认跑定向测试（`--full` 才跑全量）；
- [ ] 文档跟着代码一起改（README / 用户手册 / 路线矩阵）。

## 许可证与协作准则

提交即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
注意：MIT 只覆盖原创代码，**不覆盖游戏画面与从中裁切的模板**，详见 [NOTICE.md](NOTICE.md)。
协作按[行为准则](CODE_OF_CONDUCT.md)进行。
