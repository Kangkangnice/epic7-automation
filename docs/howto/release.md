---
topic: release
when: 维护者准备 GitHub Release 或复核发布工件时
last_verified: 2026-11-19
review_when: 发布权限、桌面版本来源、打包入口、工件内容或第三方依赖变化
---

# 发布手册

维护者从 `main` 上已通过 PR 检查的提交准备发行，并确认候选版本通过完整回归。GitHub tag 标记代码版本，GitHub Release 提供 ZIP 附件，桌面更新检查读取 Release。[项目治理](../../GOVERNANCE.md)

## 准备版本和内容

1. 更新桌面版本号，核对现状页与用户手册。对照待发布提交与上一个发布标签之间的 Git 记录，在 GitHub Release 草稿汇总用户可见的变化、适用范围和升级须知。每个公开版本使用唯一的 `v<版本>` tag，首次发布以候选提交的实际功能和限制为准。[版本号](../../desktop/catalog.py) · [现状页](../STATUS.md) · [用户手册](../USER_GUIDE.md)
2. 从待发布提交独立检出，目录命名为 `auto_game_unified`。安装开发依赖，执行全量检查。[本地开发](../../CONTRIBUTING.md#本地开发) · [手工全量测试](../../CONTRIBUTING.md#手工全量测试)
3. 按候选版本逐项核对公开支持范围。稳定组合须满足业务验收标准，待验组合写明试用范围和限制，存在安全阻断的组合按业务标准暂停放行。保存脱敏验收汇总和原始证据索引。[路线开发与验收](route_change.md#6-什么时候可以稳定发布) · [路线验收记录](route_acceptance.md)
4. 声明达到共享视觉迁移目标时，在 PR 和发行说明中列出发布范围内的模拟器路线、PC 完整通过数、使用默认策略通过数和已登记的例外。默认策略占比以发布范围内的全部模拟器路线作分母。[共享视觉迁移目标](../decisions/0009-universal-vision-contract.md)
5. 对照实际工件，逐项核对游戏图像、截图、第三方库与外部扩展的授权和分发条件，包括 Fluent Widgets。人工核对许可文件已随包，以及随包 ICU 库有无与系统同名。本机诊断、个人数据、令牌、Git 元数据和未经核对的外部源码与工件分开。[项目许可](../../LICENSE) · [权利声明](../../NOTICE.md) · [Windows ICU 文档](https://learn.microsoft.com/en-us/windows/win32/intl/international-components-for-unicode--icu-) · [Fluent Widgets 上游许可](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)

## 本地生成与验收

在同一个 Windows Python 环境安装 PyInstaller，按贡献指南生成免安装版，按需加做安装版。记下构建的提交、Python 与 PyInstaller 版本。[打包命令与安装版](../../CONTRIBUTING.md#打包改动了打包配置才需要)

确认产物的无窗口自检通过，解压 ZIP 核对顶层目录并实际启动桌面界面。用候选工件验证本次变更影响的桌面入口和目标路线，按业务标准复用未受影响范围的已有证据。发布附件来自同一次验收的产物，保留随包的 SHA256 校验文件并核对哈希。[实机验证](live_verification.md)

工作区的运行只覆盖记录中能辨认的入口、设置与业务结果。候选放行时把游戏及客户端版本、输入通道、助手修订和工件校验值一并关联到验收记录。未知项继续待核。[台账适用范围及现有证据](route_acceptance.md#1-台账按适用范围填写)

## 发布和回退

维护者在 GitHub 创建 Release 草稿，使用目标提交和对应 tag，附版本说明、已验收的平台与限制、ZIP 和校验文件。复核下载的附件后再公开发布。

发现回归时，在 Release 说明标注受影响范围。用小范围 PR 修复或回退后发布新的修订版本。
涉及隐私或资源误操作时，先按安全政策处理，保留只供维护者审阅的现场证据。[安全政策](../../SECURITY.md)
