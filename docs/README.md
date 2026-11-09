# 文档索引

> **只需要先读两页**：本页 + [`STATUS.md`](STATUS.md)（现状速查，自动生成）。
> 其余一律按「你现在要干什么」去查，不需要通读。

---

## 一、按你要做的事找

| 你想干什么 | 读哪份 | 性质 |
|---|---|---|
| 知道现在支持哪些路线、哪些放行了 | [`STATUS.md`](STATUS.md) | **自动生成**，唯一事实源 |
| **让 agent 真的进游戏点鼠标做实机闭环** | [`howto/live_verification.md`](howto/live_verification.md) | **手法**，判断变了就要改 |
| 接手别人做到一半的活 | 先看 [`STATUS.md`](STATUS.md) 的「在制品」一节，再点开里面链到的交接单 | 临时 |
| 装起来用、界面怎么点 | [`USER_GUIDE.md`](USER_GUIDE.md) | 长期 |
| 看懂代码怎么分层 | [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`architecture/auto_game_unified.code-map.md`](architecture/auto_game_unified.code-map.md) | 长期 |
| 新增一条自动化路线 | [`EXTENDING.md`](EXTENDING.md) · [`maintenance/route_extensibility_review.md`](maintenance/route_extensibility_review.md) | 长期 |
| 采一张新截图 / 做一颗新模板 | [`TEMPLATE_CAPTURE.md`](TEMPLATE_CAPTURE.md) · [`maintenance/template_dynamic_content_review.md`](maintenance/template_dynamic_content_review.md) | 长期 |
| 改状态机、加动作 | [`TRANSITION_CONTRACTS.md`](TRANSITION_CONTRACTS.md) | **契约**，改前必读 |
| 开局停在半路，想知道能不能接上 | [`RESUME_COVERAGE.md`](RESUME_COVERAGE.md) · [`maintenance/route_finish_points.md`](maintenance/route_finish_points.md) | 长期 |
| 跑挂了要排查 | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | 长期 |
| 想知道哪些动作会花资源、靠什么拦住误点；每条路线到底有哪些实机证据 | [`SAFETY_MATRIX.md`](SAFETY_MATRIX.md) | 长期 |
| 在 PC 客户端上跑（移植 / 放行 / 踩坑） | [`PC_TEMPLATE_MIGRATION.md`](PC_TEMPLATE_MIGRATION.md) · [`maintenance/pc_page_capture_checklist.md`](maintenance/pc_page_capture_checklist.md) | **PC 结论唯一权威** |
| 每日任务的分组与执行顺序 | [`maintenance/daily_tasks_grouping.md`](maintenance/daily_tasks_grouping.md) | 长期 |
| 突然冒出个想法，先记下来 / 以后想挑个活干 | [`BACKLOG.md`](BACKLOG.md) | 滚动更新 · 未评估的想法 |
| 看还有哪些没做完 | [`TODO.md`](TODO.md) | 滚动更新 |
| 看这次改了什么 | [`../CHANGELOG.md`](../CHANGELOG.md) | 一次性记录 |
| 和 AI 协作时的分工（历史做法；实机权限看上面 howto 那份） | [`HUMAN_AI_WORKFLOW.md`](HUMAN_AI_WORKFLOW.md) | 历史存档 |
| 竞品做到了哪些我们没做 | [`COMPETITOR_FEATURES.md`](COMPETITOR_FEATURES.md) | 参考 |
| 世界首领战的设计取舍 | [`WORLD_BOSS_DESIGN.md`](WORLD_BOSS_DESIGN.md) | 设计稿 |
| 全局「每个动作都要有验收」的加固方案 | [`maintenance/action_verification_plan.md`](maintenance/action_verification_plan.md) | 方案 |

### 规范都放在哪（含仓库外的）

有些规矩**不在本仓库**：工作区的 `.workbuddy/memory/topics/`（按主题分册，
装的是本机坐标、实测分数、逐次实跑复盘）和用户级技能 `~/.workbuddy/skills/`
不进 Git、不受本页门禁管。所以在这里把两边都登记，免得下次又「找不着、或者照旧文档踩坑」。

> **判断标准**：换台机器、clone 一份仓库、换个 agent 还必须知道的 → **必须写进仓库**并登记在本页；
> 只是这台机的坐标、分数、某次实跑复盘 → 留在记忆通道，别搬进来（搬进来只会让仓库天天过期）。
> 发现记忆里躺着一条**规矩**而不是案例 → 上收到下表对应的仓内文档，并在本表改指向。

| 主题 | 仓内权威（跨机器必须知道） | 仓库外补充（本机案例，按需翻） |
|---|---|---|
| 现状：路线名单 / PC 放行 / 每日顺序 | [`STATUS.md`](STATUS.md)（代码生成） | — |
| 安全：危险按钮 / 干跑默认 / 退出码 / 回家 | [`../AGENTS.md`](../AGENTS.md) · [`EXTENDING.md`](EXTENDING.md) 第 5 节 | `.workbuddy/memory/topics/safety.md` |
| 转场五段证据 / 判据唯一 / 陌生页可恢复 | [`TRANSITION_CONTRACTS.md`](TRANSITION_CONTRACTS.md) | `topics/transitions.md` · `lessons.md` |
| 模板采集 / 判据纪律 / 锚点 / 夹具 / 反向验证 | [`TEMPLATE_CAPTURE.md`](TEMPLATE_CAPTURE.md) · [`../AGENTS.md`](../AGENTS.md) | `topics/discipline.md` · `anchors.md` · `hazards.md` · `fixtures.md` |
| 全局弹窗（新弹窗的 10 个接触点） | [`TRANSITION_CONTRACTS.md`](TRANSITION_CONTRACTS.md) + 下方逐路线手册 | `topics/global_popups.md` |
| 新增路线 / 登记四处 / 两道准入关 | [`EXTENDING.md`](EXTENDING.md) · [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | `topics/route_admission.md` · `route_metadata.md` |
| 主循环 / 点击通道 / 战斗移交 / 时间源 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | `topics/runner_loop.md` · `click_channel.md` · `battle_auto_flip.md` |
| 开局接力 / 断点恢复 | [`RESUME_COVERAGE.md`](RESUME_COVERAGE.md) · [`TRANSITION_CONTRACTS.md`](TRANSITION_CONTRACTS.md) | `topics/resume.md` |
| 实机权限 / 鼠标 / 截图 / 失败判定 | [`howto/live_verification.md`](howto/live_verification.md) | `topics/env.md` |
| **PC 移植**（结论 + 作业流水线） | [`PC_TEMPLATE_MIGRATION.md`](PC_TEMPLATE_MIGRATION.md) · [`maintenance/pc_page_capture_checklist.md`](maintenance/pc_page_capture_checklist.md) | 技能 `~/.workbuddy/skills/epic7-pc-route-port/` · `topics/pc_templates.md` · `pc_port_pitfalls.md` |
| 验证门槛 / 提交钩子 / 打包 / 并发协作 | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) · [`../AGENTS.md`](../AGENTS.md) · 本页第三、四节 | `topics/engineering_gate.md` · `env.md` |
| 桌面界面 / 通知 / 快捷方式 | [`USER_GUIDE.md`](USER_GUIDE.md) | `topics/desktop.md` · `notify.md` |
| 逐路线细节 | 下一节那张表 | `topics/side_story.md` · `tower_retry.md` · `arena_outcome.md` · `survivor.md` · `routes_entry.md` |
| 为什么当初这么定 | [`decisions/`](decisions/) | — |

⚠️ 仓库外的两份**不是可选阅读**：要移植一条 PC 路线时，作业顺序以技能里的七阶段流水线为准；
遇到「点不动 / 认不出」先在 `topics/` 搜该坐标或页面名（上一次很可能已经查到同样深度）。
但它们会随这台机器变，**结论冲突时一律以仓内文档为准**。

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
| [0005](decisions/0005-handover-lives-in-docs-wip.md) | 进行中的交接单放 `docs/wip/`，合并即删（补 0004 的遗漏） |
| [0006](decisions/0006-pc-slide-must-foreground.md) | PC 滑动必须抢前台，抓帧不怕遮挡，最小化自动还原 |
| [0007](decisions/0007-achievement-done-per-class.md) | 成就收工改成逐个分类确认，不再看角标红点 |
| [0008](decisions/0008-one-guide-per-topic.md) | 手法类文档一个主题只许一份，新做法覆盖旧做法 |

写新决策：跑 `python -m auto_game_unified.tools.new_decision --title "一句话说清" --slug 英文短名`
占号并生成骨架。**不要手动取号** —— 两个 agent 并行时各自「接着往后排」必然撞号
（2026-11-08 撞过一次，两边都写成 0006）。工具用原子创建文件占位，同时跑也只会拿到两个号。

---

## 四、写文档的规矩（对人和 agent 同样有效）

### 先判断这是哪一类，再决定写在哪

| 类型 | 回答什么 | 放哪 | 寿命 |
|---|---|---|---|
| **现状** | 系统现在是什么样 | `docs/STATUS.md`（生成）/ `USER_GUIDE` / `maintenance/<路线>` | 永远准确 |
| **手法** | 具体怎么操作、失败了怎么判 | `docs/howto/<主题>.md`（带 `last_verified` / `review_when`） | 长期，**判断变了就要改** |
| **决策** | 当初为什么这么定 | `docs/decisions/NNNN-*.md` | 永久；**草稿期可改正文**，入库后只增不改，被推翻标 superseded |
| **已知缺口** | 还欠哪一步证据 / 待验证项 | [`TODO.md`](TODO.md)（滚动）；正在处理则 `docs/wip/` | 补完就划掉，**不许只埋在路线手册里** |
| **想法池** | 未评估、不排期的点子 | [`BACKLOG.md`](BACKLOG.md) | 不承诺做；选中开工才挪进 TODO / `docs/wip/` |
| **在制品** | 这次做到哪、下一步是什么 | `docs/wip/<日期>-<主题>.md` | **合并即删**，不是文档 |
| **过程** | 这次改了什么、怎么改的 | 提交信息 + `CHANGELOG.md` | 一次性 |
| **记忆** | 踩过什么坑、查过什么 | `.workbuddy/memory/` | 30 天后蒸馏进 `MEMORY.md` |

写到 `docs/howto/` 时**直接复制 [`howto/_TEMPLATE.md`](howto/_TEMPLATE.md)** —— 结构是固定的
（自检 → 标准做法 → 失败判定 → 依据与作废条件 → 墓碑 → 更改记录），别自己发明一套。
`docs/howto/` 下的文件**必须**登记到本页，否则门禁会拦下。

⚠️ **「手法」这一类最容易悄悄过期** —— 不是代码变了，是**当初的判断变了**
（比如后来发现不必提权）。没有 diff、没有报错、没有测试会变红。所以 `docs/howto/` 下的文档
**必须**带 `last_verified` 与 `review_when` 两个字段（`tests/test_docs_index.py` 会查），
并且每条做法都要写清「依据 / 怎么复核 / 什么时候作废」。这是唯一能让人主动回头看的办法。

**「交接说明」「施工计划」「设计稿」不进仓库。** 它们的信息当场拆进上面三处：为什么进决策、
改了什么进 CHANGELOG、怎么改进提交信息。这一条是为了根治「交接文档越堆越多、没人知道哪份还有效」。

⚠️ **唯一例外是「正在干、还没干完」的交接** —— 它必须进 `docs/wip/`，否则下一个人
和 `STATUS.md` 都看不见「有活没干完」。规矩：
复制 [`wip/_TEMPLATE.md`](wip/_TEMPLATE.md) → 填四样（`route` / `status` / `started` / `next_step`）
→ 它会自动出现在 `STATUS.md` 的「在制品」一节 → **合并进 main 后删掉**。
`docs/wip/` 下的文件**不需要**登记到本索引（它是临时凭证，门禁另行校验元数据）。

### 三条会被门禁拦下的规矩

1. **不许手改 `STATUS.md`** —— `tests/test_status_doc.py` 会逐字比对代码算出来的结果。
   改了就跑 `python -m auto_game_unified.tools.gen_status` 重生成。
2. **新增任何 `.md` 必须登记在本页** —— `tests/test_docs_index.py` 会检查
   `docs/` 下每个文档都能从本页点到。没登记的文档等于不存在，门禁直接红。
3. **不许写死会漂移的数字** —— 想说「现在有多少条路线」，去链 `STATUS.md`，不要抄数字。
   首页（`README.md` 与本页）有专门的门禁盯着这一条。

### 复审：按本次改动即时判定，提交时留痕

`STATUS.md` 保证的是**结构化事实**（路线数、放行名单）。其余文档里那句话还成不成立，
机器判断不了 —— 架构说明、每路线维护手册、用户手册，只能人读一遍。为了让它变便宜，
工具按**本次改动的文件**映射出「该看哪几份」，而不是重读整个 `docs/`：

```powershell
python -m auto_game_unified.tools.doc_review           # 工作区相对 HEAD 的改动
python -m auto_game_unified.tools.doc_review --staged  # 只看暂存区
```

映射规则在 `tools/doc_review.py::DOC_RULES`；关键路径不许漏登记，反向护栏在
`tests/test_doc_review.py`。

⚠️ **2026-11-09 起不再有游标**。初版用 `doc-review-cursor.txt` 记住「上次审到哪个提交」，
验收时抓到两个洞：游标是**要人记得推进的状态**（一忙就落后 7 个提交），而且只看两个提交
之间的 diff，**工作区里没提交的改动完全看不见**。现在没有任何需要记忆的状态。

留痕规则：本次改动命中了规则，提交信息里就必须有一行 `Doc-reviewed:`，写清看过哪几份
（确实没有变化就写「无变化」）。`tools/githooks/commit-msg` 会拦下没留痕的提交。
机器只能验证「有没有留痕」，**不能验证「有没有真读」** —— 但它把「审文档」从可跳过的
自觉动作，变成提交时必然会碰到的一问。本地 `--no-verify` 能跳，服务端跳不过：
CI 的 `Governance gate` 会在干净检出上再跑一遍治理门禁。

### 存档

只供追溯，**不要照着做**（里面的接口可能已经删了）：

- [`superpowers/specs/2026-08-25-epic7-auto-assistant-productization-design.md`](superpowers/specs/2026-08-25-epic7-auto-assistant-productization-design.md)
  —— 产品化命名与视觉约束，`NOTICE.md` 引用其第 9 节
- [`REFERENCE.md`](REFERENCE.md) —— 旧版 README 全文（343 行逐条说明），保留是因为写得比新 README 细

---

## 五、这套机制还在运转吗（自检清单）

**每轮较大的改动合进来之后，或者你接手别人的活之前，跑这五条。** 前四条机器判定，
第五条要靠眼睛。

| # | 检查什么 | 怎么查 | 通过标准 |
|---|---|---|---|
| 1 | 结构化事实与代码是否一致 | `python -m pytest -q tests/test_status_doc.py` | 全绿（红就说明有人手改了 STATUS，或忘了重生成） |
| 2 | 有没有没登记的文档、断链、ADR 元数据缺失 | `python -m pytest -q tests/test_docs_index.py` | 全绿 |
| 3 | 本次改动该复审的文档有没有留痕 | `python -m auto_game_unified.tools.doc_review` + 看提交信息 | 命中规则的提交信息里有一行 `Doc-reviewed:` |
| 4 | 有没有交接单遗留 | 看 [`STATUS.md`](STATUS.md) 的「在制品」一节 | 该在的在（还在干），做完的已经删掉 |
| 5 | 提交信息说得清"为什么"吗 | `git log --oneline -10` | 能看懂改了什么、以及**为什么**改（不是只写「修复」） |

### 机器查不了的三件事（要靠人看）

1. **文档进错通道**：一件事该进 `docs/decisions/`（决策），却写进了
   `docs/maintenance/<路线>.md`（维护手册）—— 白名单只保证"有登记"，管不了"分对类"。
2. **交接单是"填完就删"还是"堆着"**：`STATUS.md` 里如果排着一串两周前的 `in-progress`，
   说明有人开了活没收回。
3. **门禁被绕过**：本地 `--no-verify` 能跳钩子，但 CI 的 `Governance gate` 会再跑一遍；
   看 CI 绿不绿、以及提交信息里有没有该有的 `Doc-reviewed:`。

> 这套东西的验收标准不是「文档写得多」，而是**漂移多久能被发现**：
> 结构化事实 0 天、半成品 0 天、语义漂移取决于每次提交有没有认真写那条 `Doc-reviewed:`。
