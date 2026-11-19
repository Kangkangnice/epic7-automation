# 第七史诗自动助手

Windows 上的非官方《第七史诗》视觉自动化工具。通过游戏窗口截图定位页面和控件，在确认页面、动作和资源条件后执行输入，并验证实际结果。

[使用手册](docs/USER_GUIDE.md) · [支持范围](docs/STATUS.md) · [故障排查](docs/TROUBLESHOOTING.md) · [参与贡献](CONTRIBUTING.md)

![桌面界面示意](docs/images/app-preview.svg)

## 快速开始

需要 Windows 64 位、简体中文游戏界面，以及雷电模拟器或《第七史诗》PC 客户端。请按 [支持范围](docs/STATUS.md) 选择对应后端已放行的路线。

如 [GitHub Releases](https://github.com/Kangkangnice/epic7-automation/releases) 有维护者发布的免安装 ZIP，解压后运行 `Epic7AutoAssistant.exe`。从源码开始时使用 Windows Python，CI 的完整测试基线为 Python 3.11。

```powershell
git clone https://github.com/Kangkangnice/epic7-automation.git auto_game_unified
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r auto_game_unified\requirements.txt
.\.venv\Scripts\python.exe -u -m auto_game_unified.desktop
```

命令从检出目录 `auto_game_unified` 的父目录执行。打开游戏后，在助手里选择后端，检测环境，勾选路线并开始。界面操作和停止方法见 [使用手册](docs/USER_GUIDE.md)。

## 安全与反馈

命令行默认干跑。需要真实操作时明确启用实跑，并按路线设置核对次数和资源选项。涉及购买、补充、制作或整理等动作的具体开关和证据见 [安全矩阵](docs/SAFETY_MATRIX.md)。

诊断截图和日志默认留在本机。公开报告前应移除昵称、账号、私密路径和凭据。更新检查会查询 GitHub，配置 QQ 通知时会发送运行摘要。渠道与数据说明见 [安全政策](SECURITY.md)。

欢迎使用 [GitHub Issue 表单](https://github.com/Kangkangnice/epic7-automation/issues/new/choose) 提交复现步骤、客户端和脱敏日志。代码和文档贡献从 [贡献指南](CONTRIBUTING.md) 开始。维护职责见 [项目治理](GOVERNANCE.md)，其他资料见 [文档索引](docs/README.md)。

## 许可

原创代码按 [MIT](LICENSE) 授权。游戏素材和第三方组件的权利范围见 [NOTICE](NOTICE.md)。本项目与游戏运营方无关联，使用前请核对适用的游戏规则。

[版本记录](CHANGELOG.md)
