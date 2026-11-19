# 文档索引

## 一、按你要做的事找

| 你要做什么 | 从这里开始 |
|---|---|
| 安装、启动、选择任务、使用连点器 | [使用手册](USER_GUIDE.md) |
| 确认路线、默认次数、PC 放行和每日顺序 | [现状速查](STATUS.md)（由代码生成） |
| 排查识别、点击、黑屏、退出码 | [故障排查](TROUBLESHOOTING.md) |
| 了解资源消耗的护栏和逐路线实机证据 | [安全与支持证据矩阵](SAFETY_MATRIX.md) |
| 报告问题或提议功能 | [贡献指南](../CONTRIBUTING.md)、[安全政策](../SECURITY.md) |
| 维护 Issues、PR、分支和版本 | [项目治理](../GOVERNANCE.md)、[发布流程](howto/release.md) |
| 看懂代码分层、运行时和诊断 | [架构说明](ARCHITECTURE.md)、[架构图代码对照](architecture/auto_game_unified.code-map.md) |
| 新增路线 | [新增路线指南](EXTENDING.md) |
| 修改视觉判据、动作、重试或转场 | [页面转场契约](TRANSITION_CONTRACTS.md)、[截图与模板采集](TEMPLATE_CAPTURE.md) |
| 排查开局接力或回大厅收尾 | [开局接力覆盖面](RESUME_COVERAGE.md)、[路线终点](maintenance/route_finish_points.md) |
| 针对 PC 客户端移植、抓帧或排障 | [PC 接入指南](PC_TEMPLATE_MIGRATION.md)、[PC 页面采集清单](maintenance/pc_page_capture_checklist.md) |
| 实机验证 | [实机闭环验证](howto/live_verification.md) |
| 更新图鉴数据或界面文案 | [英雄图鉴维护](maintenance/hero_roster.md)、[界面文案规范](UI_COPY_STYLE.md) |
| 查看缺失的证据、未解决的缺陷或未评估提案 | [待办](TODO.md)、[想法池](BACKLOG.md) |
| 查看版本变化与素材权利 | [变更日志](../CHANGELOG.md)、[素材声明](../NOTICE.md) |

## 二、每条路线怎么维护

手册记录页面链路、判据的设计理由和资源边界。路线当前能否运行查 [现状速查](STATUS.md)，还缺什么证据查 [待办](TODO.md)。

| 路线 | 手册 |
|---|---|
| 主线 `story` | [主线](maintenance/story.md) |
| 竞技场 `arena` | [竞技场](maintenance/arena.md) |
| 远征 `expedition` | [远征](maintenance/expedition.md) |
| 月塔 `tower` | [月塔](maintenance/tower.md) |
| 英雄合成 `hero_synthesis` | [英雄合成](maintenance/hero_synthesis.md) |
| 支线故事 `side_story` | [支线故事](maintenance/side_story.md) |
| 月光剧场 `moonlight_theater` | [月光剧场](maintenance/moonlight_theater.md) |
| 骑士团捐赠 `knights_donation` | [骑士团捐赠](maintenance/knights_donation.md) |
| 迷宫强化石 `labyrinth_stone` | [迷宫强化石](maintenance/labyrinth_stone.md) |
| 圣域收菜 `sanctuary` | [圣域收菜](maintenance/sanctuary.md) |
| 社区签到 `community` | [社区签到](maintenance/community_checkin.md) |
| 成就领取 `achievement` | [成就领取](maintenance/achievement.md) |
| 主线补星 `story_star` | [主线补星](maintenance/story_star.md) |
| 宠物领养 `pet_adoption` | [宠物领养](maintenance/pet_adoption.md) |
| 企鹅批量购买 `penguin_purchase` | [企鹅批量购买](maintenance/penguin_purchase.md) |
| 装备制作 `craft_equipment` | [装备制作](maintenance/craft_equipment.md) |

## 三、决策记录

- [0002 视觉判据必须能证伪](decisions/0002-criteria-must-be-falsifiable.md)
- [0003 竞技场结算画面不落盘](decisions/0003-arena-outcome-frames-not-saved.md)
- [0004 文档分工](decisions/0004-four-channels-for-docs.md)
- [0005 进行中的实机交接](decisions/0005-handover-lives-in-docs-wip.md)
- [0006 PC 滑动使用前台](decisions/0006-pc-slide-must-foreground.md)
- [0007 逐分类确认成就领取](decisions/0007-achievement-done-per-class.md)
- [0008 一个主题维护一份指南](decisions/0008-one-guide-per-topic.md)
- [0009 共享视觉证据契约](decisions/0009-universal-vision-contract.md)
- [0010 开源项目治理](decisions/0010-open-source-governance.md)

## 四、写文档的规矩

- 路线名单、次数、放行和素材统计统一引用 [现状速查](STATUS.md)。从仓库父目录运行 `python -m auto_game_unified.tools.gen_status` 更新生成页。
- 新增长期文档时在本页登记相对链接。同一主题更新现有指南，用 [操作指南模板](howto/_TEMPLATE.md) 建立还没有指南的主题。
- 已知缺口登记在 [待办](TODO.md)，公开讨论和排期使用 GitHub Issues，代码变更及验证记录使用 PR。需要跨会话接续实机验证时，用 [交接模板](wip/_TEMPLATE.md) 在 `docs/wip/` 记录脱敏结论和下一步，合并后删除交接单。
- 改变长期技术决策时，从仓库父目录运行 `python -m auto_game_unified.tools.new_decision --title "一句话" --slug english-name`，按 [决策模板](decisions/_TEMPLATE.md) 填写。草稿期可改正文，取代已有决策时将旧记录标为 `status: superseded` 并登记 `superseded_by`。
- 检查本次影响的文档时，从仓库父目录运行 `python -m auto_game_unified.tools.doc_review --staged`。新增路线可用 `--scenario new-route` 先查相关章节。映射命中时，本机提交钩子要求在提交信息写 `Doc-reviewed:`，说明更新了哪份或为何无需更新。CI 在干净检出中检查索引、生成页和复审映射。

### 存档

- [0001 在单点处理 PC 差异](decisions/0001-pc-changes-behind-single-switch.md)，现行判断依据见 0009。

历史过程可查 Git 记录。需要保留的历史文档标为 `status: superseded` 并登记在本节，以便从复审目标中移除。
