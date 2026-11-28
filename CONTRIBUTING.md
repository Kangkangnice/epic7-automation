# 参与贡献

欢迎提交 Issue 和 Pull Request。全部阅读顺序见[文档索引](docs/README.md)。

接受日常路线、识别和输入修复、桌面与诊断改进。改动应能独立说明、验证和回退。
本项目通过窗口画面和输入进行视觉辅助。贡献范围排除游戏内存读取、客户端或数据包修改、反检测、
绕过游戏安全机制、自动 PvP 功能扩展，以及自动上传运行日志和截图。资源动作按
[路线开发与验收](docs/howto/route_change.md)的业务规则验收，工程护栏见[安全矩阵](docs/SAFETY_MATRIX.md)。

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
& $python -u -m auto_game_unified.desktop
```

如需开发联调 QQ 通知，在同一启动环境设置 `EPIC7_QQBOT_APP_ID`、`EPIC7_QQBOT_CLIENT_SECRET` 和 `EPIC7_QQBOT_USER_OPENID`。个人 OpenID 来自机器人收到的私聊事件；凭据只存本机。通知失败不改变任务结果。[通知实现](core/qqbot.py)

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
| 版本标签、每周回归、维护者手动触发 | 无条件全量。本机使用[手工全量测试](#手工全量测试)中的命令。 |

本地预览用 `--plan --files <仓库相对路径>`。已提交的改动可用 `--plan --since origin/main`。
新增未跟踪的文件需显式列出或暂存。暂存区为空时默认读取整个已跟踪工作区，多任务并行时优先显式指定路径。
本地提示未映射时，手工指定覆盖它的测试；PR 选择器对未知路径执行全量。维护者扩大定向范围前应核对直接消费者、
跨路线契约及反例，并给分层选择增加回归测试。具体放行条件见[按玩家行为验收](docs/decisions/0011-behavior-based-regression.md)。路线按行为变化提交目标客户端实机闭环和风险回放。
提交含需要复审的修改时，按钩子提示在提交消息加入 `Doc-reviewed:` 和实际复审结果。
在仓库根目录可用 `python tools/doc_review.py --staged` 查看清单。

### 手工全量测试

从仓库父目录运行。每次给 pytest 一个尚未创建的临时目录。直接使用系统默认目录时，pytest 会在退出时清理以前的运行目录，可能触发 WorkBuddy 的 `safe-delete` 批量删除保护。复用已有的 `--basetemp` 也会触发清理，只是发生在用例准备阶段。

```powershell
$python = '.\.venv\Scripts\python.exe'
$pytestRoot = Join-Path (Get-Location).Path 'auto_game_unified/runtime_logs'
if (-not (Test-Path -LiteralPath $pytestRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $pytestRoot -Force | Out-Null
}
$pytestTemp = Join-Path $pytestRoot "_pytest_full_$([guid]::NewGuid().ToString('N'))"
& $python -m pytest -q --durations=10 --basetemp $pytestTemp auto_game_unified/tests
```

只创建父目录，由 pytest 创建本次目录。临时文件留在 Git 忽略的 `runtime_logs/`。保留完整测试汇总和 Python 的实际退出码。历史日志若只有汇总后的 `cleanup_numbered_dir` 删除拦截，记录为退出清理受阻。用例内的 `FAILED` 或 `ERROR` 分开处理。

## 路线与素材

业务范围和通过条件见[路线开发与验收](docs/howto/route_change.md)，注册和实现见[新增路线指南](docs/EXTENDING.md)。截图与模板的取材、脱敏和入库压缩见[截图与模板采集](docs/TEMPLATE_CAPTURE.md)。跨会话协作优先用独立分支和工作树，共用工作树时按负责人精确暂存。

从仓库父目录用 `python -m auto_game_unified.tools.new_decision` 编号并建立决策草稿。决策与交接的记录位置见[项目治理](GOVERNANCE.md#资料放在哪里)。

## 从提交到合并

从最新 `main` 建主题分支，逐个暂存本次改动，使用 `类型(范围): 一句话` 提交，正文写明原因。推送后开 PR，说明变更、实际验证、证据及尚待复核的范围。合并前通过名为 `pytest` 的必需检查并处理评审意见。职责和发布权限见[项目治理](GOVERNANCE.md)，字段见[PR 模板](.github/PULL_REQUEST_TEMPLATE.md)。

```powershell
git switch -c fix/arena-team-page
git add -- games/epic7/arena.py
git commit -m "fix(arena): 修复队伍页识别"
git push -u origin HEAD
gh pr create --base main --fill
```

## 打包（改动了打包配置才需要）

```powershell
python packaging/build.py
```

它会跑 PyInstaller 目录版打包 → 跑一次
`ArkyAssistant.exe --self-check`（检查运行产物目录可写、模板在不在、全部路线
能不能加载）→ 打免安装 ZIP 并写 `SHA256SUMS.txt`。另有一条 `check_pruned_binaries`
守着 spec 剔掉的 videoio ffmpeg 二进制真没进产物。构建请走 `packaging/build.py`，
它统一了产物目录、自检与 ZIP 文件名的规则。

产物在 `packaging/dist/`（已 gitignore，不进历史）。

`--no-build` 复用已有目录版，只重打 ZIP；`--skip-smoke` 跳过自检。

**验证冻结版的 worker 交接**（离线，不需要游戏、不发任何输入）：

```powershell
python tools\verify_frozen_worker.py --exe packaging\dist\ArkyAssistant\ArkyAssistant.exe
```

它用桌面端同一条 `WorkerController.start()` 启动产物，子进程跑隐藏参数
`--offline-probe`：只观察停止信号，**不装配路线、不截图、不点击**，即使游戏已经打开
也不会碰它。期望两次结果：到点正常结束（退出码 0）；父进程写 `stop.signal` 后，
子进程读到并退出 130。同时核对只有 `ArkyAssistant.exe` 一个子进程、命令行带
`--worker`、没有窗口、输出能回传父进程。

**默认只出免安装版**。用户解压 ZIP、双击 `ArkyAssistant.exe`
就能跑。想要安装包再加 `--installer`。这一步需要 **Inno Setup 6**，缺少时脚本会跳过。公开发布与回退按[发布手册](docs/howto/release.md)。

四个容易踩的点：

- 打包版的运行产物写在 `%LOCALAPPDATA%\ArkyAssistant`，源码运行仍写在仓库目录 ——
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
  `%LOCALAPPDATA%\Programs\ArkyAssistant`，全程不弹 UAC，非管理员账户也能装。
  想装到 `Program Files` 得显式传 `/ALLUSERS`；
- **卸载保留用户数据**：`%LOCALAPPDATA%\ArkyAssistant` 下的日志与诊断不删，
  那是用户自己的运行记录；
- 打完包至少走一遍「装 → 跑 `--self-check` → 卸」，别只看 ISCC 返回 0 就当成能用。

## 许可证与协作准则

提交即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
注意：MIT 只覆盖原创代码，**不覆盖游戏画面与从中裁切的模板**，详见 [NOTICE.md](NOTICE.md)。
协作按[行为准则](CODE_OF_CONDUCT.md)进行。
