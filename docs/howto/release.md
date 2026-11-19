---
topic: release
when: 维护者准备 GitHub Release 或复核发布工件时
last_verified: 2026-11-19
review_when: 发布权限、桌面版本来源、打包入口、工件内容或第三方依赖变化
---

# 发布手册

发布维护者从 `main` 上已通过 PR 检查的提交准备发行，并确认候选版本通过完整回归。源码安装和本地构建都可以独立验证。
GitHub 的 tag 标记代码版本，带 ZIP 的 GitHub Release 提供用户可下载的文件。桌面检查更新读取后者。

## 准备版本和内容

1. 更新 [`desktop/catalog.py`](../../desktop/catalog.py) 中的 `PRODUCT_VERSION` 和
   [`CHANGELOG.md`](../../CHANGELOG.md) 的版本说明。核对 [生成的现状页](../STATUS.md) 和用户手册。
   每个公开版本使用唯一的 `v<版本>` tag。已存在的 tag 和工件保留原记录，修复以新版本发布。
2. 从待发布提交独立检出，目录命名为 `auto_game_unified`。安装贡献指南里的依赖并通过全量检查。
   PC 或模拟器的新增支持以对应实机证据为准。软件无窗口自检覆盖桌面依赖和模板加载，桌面启动和
   游戏业务支持由各自的实机验收覆盖。
   新增或行为受影响的稳定支持须按[路线稳定版验收](route_acceptance.md)提交多账号证据，
   并保存本地校验输出。尚在试用的组合在发布说明里注明范围。
   游戏改版引起的变化按[维护手册](game_update.md)记录适用客户端版本、已验路线和待复核范围。
   声明达到[共享视觉迁移目标](../decisions/0009-universal-vision-contract.md)时，在 PR 和发行说明列出
   该版本发布范围内的模拟器路线、PC 完整通过数、使用默认策略数和已登记例外。默认策略占比按
   默认策略通过数除以上述模拟器路线数计算。无实机闭环的路线不能从分母移除。
3. 核对 [LICENSE](../../LICENSE)、[NOTICE](../../NOTICE.md) 和实际工件清单。游戏图像、截图、
   第三方库与外部扩展分别核对授权与发布条件。检查 Fluent Widgets 等组件的上游许可及随包文件。
   当前构建不自动把 `LICENSE` / `NOTICE.md` 复制到可执行文件目录，也不过滤与系统同名的 ICU 库，
   这两项须在发布前人工确认；自动化方案登记在[待办](../TODO.md)的打包条目。
   E7auto 按 `packaging/vendor_lock.json` 逐文件校验后，随工件分发 `src` / `config` /
   `assets/templates` 三段。**维护者尚未确认该组件可公开分发**，确认前不得对外发布含它的工件；
   是否继续随包分发由维护者决定，结论出来前三个位置（`NOTICE.md`、本手册、spec）按同一事实表述。
   本机诊断、个人数据、令牌、Git 元数据和未经核对的外部源码与工件隔离。
   [Windows ICU 文档](https://learn.microsoft.com/en-us/windows/win32/intl/international-components-for-unicode--icu-)
   [GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) ·
   [Fluent Widgets 上游许可](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)

## 本地生成与验收

从 `auto_game_unified` 的父目录执行。保持同一个 Windows Python 环境。

```powershell
python -m pip install -r auto_game_unified/requirements-dev.txt
python -m pip install PyInstaller
python auto_game_unified/packaging/build.py
```

记下实际构建的提交、Python 与 PyInstaller 版本。确认默认产物的自检通过，解压 ZIP 核对顶层目录与
`vendor/e7auto` 三段是否与本次分发决定一致，再验证界面启动，
再按照 [实机验证](live_verification.md) 覆盖此次声明的路线。发布附件来自同一次验收的
`packaging/dist/`，可选安装版由 `--installer` 生成。保留 `SHA256SUMS.txt`，核对文件与哈希一致。

## 发布和回退

在 GitHub 创建 Release 草稿，使用目标提交和对应 tag，附版本说明、已验收的平台与限制、ZIP 和校验文件。
复核下载后再公开发布。准备工作、推送评审分支和公开发行是不同的操作。

发现回归时，在 Release 说明标注受影响范围。用小范围 PR 修复或回退后发布新的修订版本。
涉及隐私或资源误操作时，先按[安全政策](../../SECURITY.md)处理，保留只供维护者审阅的现场证据。

### 更改记录

| 日期 | 改了什么 | 依据 |
| --- | --- | --- |
| 2026-11-19 | 建立版本、打包、发行和回退流程 | 审计默认构建、GitHub 发行状态和仓库分支检查 |
