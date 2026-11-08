# 文档索引

> **只需要先读两页**：本页 + [`STATUS.md`](STATUS.md)（现状速查，自动生成）。
> 其余一律按「你现在要干什么」去查，不需要通读。

---

## 一、按你要做的事找

| 你想干什么 | 读哪份 | 性质 |
|---|---|---|
| 知道现在支持哪些路线、哪些放行了 | [`STATUS.md`](STATUS.md) | **自动生成**，唯一事实源 |
| 装起来用、界面怎么点 | [`USER_GUIDE.md`](USER_GUIDE.md) | 长期 |
| 看懂代码怎么分层 | [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`architecture/auto_game_unified.code-map.md`](architecture/auto_game_unified.code-map.md) | 长期 |
| 新增一条自动化路线 | [`EXTENDING.md`](EXTENDING.md) · [`maintenance/route_extensibility_review.md`](maintenance/route_extensibility_review.md) | 长期 |
| 采一张新截图 / 做一颗新模板 | [`TEMPLATE_CAPTURE.md`](TEMPLATE_CAPTURE.md) · [`maintenance/template_dynamic_content_review.md`](maintenance/template_dynamic_content_review.md) | 长期 |
| 改状态机、加动作 | [`TRANSITION_CONTRACTS.md`](TRANSITION_CONTRACTS.md) | **契约**，改前必读 |
| 开局停在半路，想知道能不能接上 | [`RESUME_COVERAGE.md`](RESUME_COVERAGE.md) · [`maintenance/route_finish_points.md`](maintenance/route_finish_points.md) | 长期 |
| 跑挂了要排查 | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | 长期 |
| 在 PC 客户端上跑（移植 / 放行 / 踩坑） | [`PC_TEMPLATE_MIGRATION.md`](PC_TEMPLATE_MIGRATION.md) · [`maintenance/pc_page_capture_checklist.md`](maintenance/pc_page_capture_checklist.md) | **PC 结论唯一权威** |
| 每日任务的分组与执行顺序 | [`maintenance/daily_tasks_grouping.md`](maintenance/daily_tasks_grouping.md) | 长期 |
| 看还有哪些没做完 | [`TODO.md`](TODO.md) | 滚动更新 |
| 看这次改了什么 | [`../CHANGELOG.md`](../CHANGELOG.md) | 一次性记录 |
| 和 AI 协作时的分工 | [`HUMAN_AI_WORKFLOW.md`](HUMAN_AI_WORKFLOW.md) | 长期 |
| 竞品做到了哪些我们没做 | [`COMPETITOR_FEATURES.md`](COMPETITOR_FEATURES.md) | 参考 |
| 世界首领战的设计取舍 | [`WORLD_BOSS_DESIGN.md`](WORLD_BOSS_DESIGN.md) | 设计稿 |
| 全局「每个动作都要有验收」的加固方案 | [`maintenance/action_verification_plan.md`](maintenance/action_verification_plan.md) | 方案 |

---

## 二、每条路线怎么维护

一条路线出问题、要改判据、要补图，看它自己那本手册。**这里没有的路线就是还没有手册**，
按「新增路线」那一行处理。

| 路线 | 手册 |
|---|---|
| 主线 `story` | [`maintenance/story.md`](maintenance/story.md) |
| 竞技场 `arena` | [`maintenance/arena.md`](maintenance/arena.md) |
| 支线故事 `side_story` | [`maintenance/side_story.md`](maintenance/side_story.md) |
| 月塔 `tower` | [`maintenance/tower.md`](maintenance/tower.md) |
| 月光剧场 `moonlight_theater` | [`maintenance/moonlight_theater.md`](maintenance/moonlight_theater.md) |
| 英雄合成 `hero_synthesis` | [`maintenance/hero_synthesis.md`](maintenance/hero_synthesis.md) |
| 骑士团捐赠 `knights_donation` | [`maintenance/knights_donation.md`](maintenance/knights_donation.md) |
| 迷宫强化石 `labyrinth_stone` | [`maintenance/labyrinth_stone.md`](maintenance/labyrinth_stone.md) |
| 圣域收菜 `sanctuary` | [`maintenance/sanctuary.md`](maintenance/sanctuary.md) |
| 远征 `expedition` | [`maintenance/expedition.md`](maintenance/expedition.md) |
| 社区签到 `community` | [`maintenance/community_checkin.md`](maintenance/community_checkin.md) |
| 成就领取 `achievement` | [`maintenance/achievement.md`](maintenance/achievement.md) |

---

## 三、决策记录（为什么当初这么定）

代码告诉你**现在是什么样**，这一层告诉**为什么是这样**，以及**哪些做法已经被推翻**。

| 编号 | 决策 |
|---|---|
| [0001](decisions/0001-pc-changes-behind-single-switch.md) | PC 相关的改动一律走单点开关，模拟器一个字节都不许变 |
| [0002](decisions/0002-criteria-must-be-falsifiable.md) | 判据必须能证伪，不是「分数够高」 |
| [0003](decisions/0003-arena-outcome-frames-not-saved.md) | 竞技场结算画面不再落盘 |
| [0004](decisions/0004-four-channels-for-docs.md) | 文档分四个通道，交接说明不进仓库 |

写新决策：复制 [`decisions/_TEMPLATE.md`](decisions/_TEMPLATE.md)，编号接着往后排。

---

## 四、写文档的规矩（对人和 agent 同样有效）

### 先判断这是哪一类，再决定写在哪

| 类型 | 回答什么 | 放哪 | 寿命 |
|---|---|---|---|
| **现状** | 系统现在是什么样 | `docs/STATUS.md`（生成）/ `USER_GUIDE` / `maintenance/<路线>` | 永远准确 |
| **决策** | 当初为什么这么定 | `docs/decisions/NNNN-*.md` | 永久，只增不改，被推翻标 superseded |
| **过程** | 这次改了什么、怎么改的 | 提交信息 + `CHANGELOG.md` | 一次性 |
| **记忆** | 踩过什么坑、查过什么 | `.workbuddy/memory/` | 30 天后蒸馏进 `MEMORY.md` |

**「交接说明」「施工计划」「设计稿」不进仓库。** 它们的信息当场拆进上面三处：为什么进决策、
改了什么进 CHANGELOG、怎么改进提交信息。这一条是为了根治「交接文档越堆越多、没人知道哪份还有效」。

### 三条会被门禁拦下的规矩

1. **不许手改 `STATUS.md`** —— `tests/test_status_doc.py` 会逐字比对代码算出来的结果。
   改了就跑 `python -m auto_game_unified.tools.gen_status` 重生成。
2. **新增任何 `.md` 必须登记在本页** —— `tests/test_docs_index.py` 会检查
   `docs/` 下每个文档都能从本页点到。没登记的文档等于不存在，门禁直接红。
3. **不许写死会漂移的数字** —— 想说「现在有多少条路线」，去链 `STATUS.md`，不要抄数字。
   首页（`README.md` 与本页）有专门的门禁盯着这一条。

### 存档

只供追溯，**不要照着做**（里面的接口可能已经删了）：

- [`superpowers/specs/2026-08-25-epic7-auto-assistant-productization-design.md`](superpowers/specs/2026-08-25-epic7-auto-assistant-productization-design.md)
  —— 产品化命名与视觉约束，`NOTICE.md` 引用其第 9 节
- [`REFERENCE.md`](REFERENCE.md) —— 旧版 README 全文（343 行逐条说明），保留是因为写得比新 README 细
