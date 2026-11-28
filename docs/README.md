# 项目文档阅读路线

全量评审从第一部分读到第六部分。每部分按列出的顺序阅读。日常使用读第一部分，管理项目先读第一、第二和第五部分，开发路线从第三、第四部分开始。模板和当前交接放在最后。

## 第一部分 用户能做什么

1. **项目首页**。了解项目用途、运行环境和下载入口。[项目首页](../README.md)
2. **使用手册**。走一遍安装、选路线、设置资源、运行和安全停止。[使用手册](USER_GUIDE.md)
3. **现状速查**。查每条路线能在哪个端启动、能否接力、验到了哪里。[现状速查](STATUS.md)
4. **故障排查**。从玩家看到的症状查怎么处理和反馈。[故障排查](TROUBLESHOOTING.md)
5. **QQ 消息通知**。配置自己的 QQ 机器人接收任务结果。[QQ 消息通知配置教程](QQ_NOTIFICATION.md)

## 第二部分 项目如何管理与验收

1. **项目治理**。看谁定范围和优先级、谁审核和放行、每类资料应该写到哪里。[项目治理](../GOVERNANCE.md)
2. **路线开发与验收**。看业务起点、资源授权、动作前后证据、完成条件、离线与实机分工，以及发布门槛。[路线开发与验收](howto/route_change.md)
3. **待办与缺口**。对照现状速查分辨当前阻断、证据缺口和可继续的工作。[待办与缺口](TODO.md)

## 第三部分 项目如何开发

### 一、按你要做的事找

| 顺序 | 该读什么 | 读完应知道什么 |
| --- | --- | --- |
| 1 | [仓库开发硬约束](../AGENTS.md) | 修改前必须遵守的工程门槛。 |
| 2 | [架构说明](ARCHITECTURE.md) | 桌面入口、任务编排、路线与平台适配的职责。 |
| 3 | [贡献指南](../CONTRIBUTING.md) | 如何启动开发环境、选择测试、提交 PR 和打包。 |
| 4 | [路线通用契约](ROUTE_CONTRACT.md) | 路线如何声明终点、覆盖层、空态、回执和危险动作。 |
| 5 | [页面转场契约](TRANSITION_CONTRACTS.md) | 如何确认动作来源、出口、业务结果及异常预算。 |
| 6 | [工程安全矩阵](SAFETY_MATRIX.md) | 各路线的风险与工程护栏，如何找到相应回归。 |
| 7 | [新增路线指南](EXTENDING.md) | 如何接线、复用共享能力并完成技术交付。 |
| 8 | [截图与模板采集](TEMPLATE_CAPTURE.md) | 怎么采集正反例、排除误判、脱敏和入库。 |
| 9 | [PC 接入指南](PC_TEMPLATE_MIGRATION.md) | 哪些逻辑共享，如何验证 PC 渲染、权限和输入差异。 |
| 10 | [PC 页面采集清单](maintenance/pc_page_capture_checklist.md) | 接手一条 PC 路线时需要哪些页面样本。 |
| 11 | [开局接力覆盖面](RESUME_COVERAGE.md) | 每条路线哪些页面已有接力回放，哪些起点要限制。 |
| 12 | [路线终点与回大厅](maintenance/route_finish_points.md) | 路线何时可以交给公共收尾，异常时保留哪些现场。 |
| 13 | [界面文案规范](UI_COPY_STYLE.md) | 如何让界面提示与实际结果一致。 |

## 第四部分 各条路线如何维护

### 二、每条路线怎么维护

从第一行顺读，核对业务流程、页面判据、资源边界和收尾。短路线的入口、分支和终点集中写在路线终点页。

| 路线 | 专项手册 |
|---|---|
| 主线 | [主线](maintenance/story.md) |
| 竞技场 | [竞技场](maintenance/arena.md) |
| 远征 | [远征](maintenance/expedition.md) |
| 月塔 | [月塔](maintenance/tower.md) |
| 狗粮 | [狗粮路线规则](maintenance/route_finish_points.md#狗粮) |
| 英雄合成 | [英雄合成](maintenance/hero_synthesis.md) |
| 支线故事 | [支线故事](maintenance/side_story.md) |
| 刷书签 | [刷书签](maintenance/shop_refresh.md) |
| 活动（已过期） | [活动小游戏路线规则](maintenance/route_finish_points.md#活动小游戏) |
| 活动剧情 | [活动剧情路线规则](maintenance/route_finish_points.md#活动剧情) |
| 世界首领战 | [世界首领战路线规则](maintenance/route_finish_points.md#世界首领战) |
| 月光剧场 | [月光剧场](maintenance/moonlight_theater.md) |
| 骑士团捐赠 | [骑士团捐赠](maintenance/knights_donation.md) |
| 迷宫强化石 | [迷宫强化石](maintenance/labyrinth_stone.md) |
| 圣域收菜 | [圣域收菜](maintenance/sanctuary.md) |
| 社区签到（国服） | [社区签到](maintenance/community_checkin.md) |
| 成就领取 | [成就领取](maintenance/achievement.md) |
| 主线补星 | [主线补星](maintenance/story_star.md) |
| 宠物领养 | [宠物领养](maintenance/pet_adoption.md) |
| 企鹅批量购买 | [企鹅批量购买](maintenance/penguin_purchase.md) |
| 装备制作 | [装备制作](maintenance/craft_equipment.md) |

维护英雄图鉴时接着读[英雄数据维护](maintenance/hero_roster.md)。刷书签采图时核对[素材来源](../games/epic7/templates/shop_refresh/SOURCES.md)。

## 第五部分 如何应对更新、故障与发布

1. **游戏更新与多人维护**。改版时怎样定影响范围、分派工作与复验。[游戏更新与多人维护](howto/game_update.md)
2. **失败诊断包与排查流程**。怎样从现场、日志和分数找到第一个故障。[失败诊断包与排查流程](INCIDENT_TRIAGE.md)
3. **实机闭环验证**。如何确认环境、权限与可用资源，跑一轮并留证。[实机闭环验证](howto/live_verification.md)
4. **路线验收记录与自检**。怎样填写业务结果、链接原始证据并核对适用范围。[路线验收记录与自检](howto/route_acceptance.md)
5. **发布手册**。怎样核对候选版本、支持声明、工件及回退。[发布手册](howto/release.md)
6. **安全、许可与协作**。依次读[安全政策](../SECURITY.md)、[项目许可](../LICENSE)、[素材与商标声明](../NOTICE.md)、[社区行为准则](../CODE_OF_CONDUCT.md)。

## 第六部分 架构决策与参考材料

| 顺序 | 主题 | 阅读顺序 |
| --- | --- | --- |
| 1 | 共享视觉与行为回归 | [0009 共享视觉证据](decisions/0009-universal-vision-contract.md) → [0002 视觉判据必须能证伪](decisions/0002-criteria-must-be-falsifiable.md) → [0011 按玩家行为分层验收](decisions/0011-behavior-based-regression.md) |
| 2 | 背景、菜单与图标变体 | [0012 背景变体补同锚点候选](decisions/0012-background-proof-candidate-not-mode-switch.md) → [0013 左侧菜单带与白字候选](decisions/0013-left-menu-band-scan.md) → [0014 图标与文字锚点](decisions/0014-icon-vs-text-anchors.md) |
| 3 | PC 输入与路线专项决策 | [0006 PC 滑动使用前台](decisions/0006-pc-slide-must-foreground.md) → [0003 竞技场结算画面保存规则](decisions/0003-arena-outcome-frames-not-saved.md) → [0007 逐分类确认成就领取](decisions/0007-achievement-done-per-class.md) |

| 用在哪里 | 模板和材料 |
| --- | --- |
| GitHub 反馈 | [故障报告](../.github/ISSUE_TEMPLATE/bug_report.yml) · [功能建议](../.github/ISSUE_TEMPLATE/feature_request.yml) · [游戏更新](../.github/ISSUE_TEMPLATE/game_update.yml) · [私下联系](../.github/ISSUE_TEMPLATE/private_contact.yml) · [反馈入口配置](../.github/ISSUE_TEMPLATE/config.yml) |
| 提交评审 | [PR 模板](../.github/PULL_REQUEST_TEMPLATE.md) |
| 添加指南、记录决策、交接现场 | [指南模板](howto/_TEMPLATE.md) · [决策模板](decisions/_TEMPLATE.md) · [交接模板](wip/_TEMPLATE.md) |
| 核对已留存的页面样本与当前交接 | [页面复核图片](manual_review/) · [进行中的交接目录](wip/) |

新增长期文档在本页相应部分登记。资料归属、已知缺口和决策草稿期可改正文的规则见项目治理，提交前按贡献指南留下 `Doc-reviewed:`。
