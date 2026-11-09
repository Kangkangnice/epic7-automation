# 权利边界与素材声明

本文件说明本项目**哪些部分是 MIT 许可覆盖的、哪些不是**。发布前请连同 [LICENSE](LICENSE) 一起读。

## 属于本项目、适用 MIT 的部分

`core/`、`desktop/`、`games/`、`tests/`、`tools/`、`main.py` 中的原创源代码，以及 `docs/` 中的原创文字。

## 不属于本项目、MIT 不构成再授权的部分

- 《第七史诗》（Epic Seven）的名称、商标、角色形象、界面设计与美术资源；
- `games/epic7/templates/` 与 `tests/fixtures/` 中**从游戏画面裁切或整屏截取**的图片；
- 上述内容归 Smilegate / Super Creative / STOVE 等各自权利人所有。

这些素材在本仓库中仅用于**离线识别测试与模板匹配**这一技术目的，不随 MIT 许可对外授权，也不构成对权利人的任何主张。

## 第三方组件

- `packaging/languages/ChineseSimplified.isl` —— Inno Setup 安装界面的简体中文消息文件，
  取自 [jrsoftware/issrc](https://github.com/jrsoftware/issrc) 的 `Files/Languages/Unofficial/`
  目录（维护者 Zhenghan Yang，另见 https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation）。
  该文件按 Inno Setup 自身的许可随官方源码一同分发，本项目原样收录，未作修改。
  它只影响安装向导的界面文字，不参与任何运行逻辑。

## 移除请求

若你是权利人，认为本仓库中某项素材不应被收录，请通过以下任一渠道联系，我们会**在确认后删除**：

- 提交一个标题以 `[素材移除]` 开头的 Issue；
- 或按 [SECURITY.md](SECURITY.md) 中的私密渠道联系维护者。

请尽量指明具体文件路径，我们会优先处理。

## 与游戏运营方的关系

本项目是**非官方**的第三方工具，与 Smilegate、Super Creative、STOVE 均无关联，未获其授权或认可。

**不使用官方图标、不使用容易让人误认为官方产品的名称与视觉，是本项目的明确约束**；
也不得宣传「官方允许」「绝对不会封号」。本项目是免费、开源、非商业的 PVE 视觉辅助工具，
仅通过窗口截图做识别并模拟普通鼠标点击，不读取或修改游戏内存、网络数据与客户端文件，
不包含反检测或绕过安全机制的功能。使用者应自行阅读并遵守游戏服务条款，
自行承担使用第三方工具可能带来的账号与资源风险。
