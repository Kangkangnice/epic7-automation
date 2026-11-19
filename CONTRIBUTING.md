# 参与贡献

欢迎提交 Issue 和 Pull Request。先用[当前现状](docs/STATUS.md)确认路线与后端的支持范围，再按下面的入口开始。

| 任务 | 入口 |
| --- | --- |
| 日常使用或报告故障 | [使用手册](docs/USER_GUIDE.md)、[排错手册](docs/TROUBLESHOOTING.md) |
| 新增路线或移植 PC | [新增路线](docs/EXTENDING.md)、[PC 接入](docs/PC_TEMPLATE_MIGRATION.md) |
| 修改识别、导航或点击 | [仓库约束](AGENTS.md)、[转场契约](docs/TRANSITION_CONTRACTS.md)、[实机验收](docs/howto/live_verification.md) |
| 评审、决策或发布 | [项目治理](GOVERNANCE.md)、[发布手册](docs/howto/release.md) |
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

文档、单元测试和离线夹具回放无需登录游戏。先跑能覆盖改动的测试。全量测试与静态检查在父目录运行：

```powershell
& $python -m pytest -q auto_game_unified/tests
& $python -m ruff check auto_game_unified
& $python -m mypy --config-file auto_game_unified/pyproject.toml
& $python -m compileall -q auto_game_unified
```

提交钩子按暂存内容定向验证。同一份暂存内容交给钩子检查，开发中途可直接跑目标测试。
提交含需要复审的修改时，按钩子提示在提交消息加入 `Doc-reviewed:` 和实际复审结果。
在仓库根目录可用 `python tools/doc_review.py --staged` 查看清单。
CI 在活跃分支的 push 上跑编译、静态检查与治理门禁，PR、版本标签、手动和定期运行触发全量组。

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
