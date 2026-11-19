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
跨路线契约及反例，并给分层选择增加回归测试。具体放行条件见[按玩家行为验收](docs/decisions/0011-behavior-based-regression.md)。路线实机与多账号验收仍按行为变化执行。
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

提交即表示同意用 [MIT License](LICENSE) 授权有权提交的原创贡献。游戏画面和第三方组件的权利边界见
[素材声明](NOTICE.md)。协作按[行为准则](CODE_OF_CONDUCT.md)进行。
