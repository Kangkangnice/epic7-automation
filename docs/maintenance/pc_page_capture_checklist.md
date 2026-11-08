# PC 端页面画面采集清单

> **用途**：把这些页面一次停到位、一次抓完，就能**提前算出每一页在 PC 上会不会卡**，
> 不用「跑一次挂一颗、补一颗」。
>
> 判定的逻辑是死的：只要给我**某一页的一张 PC 画面**，我就能算出这一页上
> 每一颗判据过不过阈值。缺的不是模板图，是**各页面的 PC 画面**。

## 怎么给我

两种方式都行，**推荐第一种**（我能自己抓，你不用截图）：

1. **你把游戏停到那一页，我来抓**：告诉我在哪一页，我跑一次抓帧脚本。
   页面静止 1 秒即可，不用做任何动作。
2. **你自己截图**：存成 PNG，放到 `runtime_diagnostics/pc_pages/<路线>.<页面>.png`。
   ⚠️ 必须是 **1920×1080 的客户区原图**（别缩放、别整屏拉伸 —— 见
   [PC 客户端接入指南](../PC_TEMPLATE_MIGRATION.md) 第 1.2 节）。

## 优先级

- **P0（先做）**：每条路线的**主流程页面** —— 决定这条路线能不能跑通。
- **P1（可后补）**：弹窗类（体力弹窗、奖励弹窗、购买确认……）—— 运行中会自己出现，
  不强求先采；哪次跑的时候存到了就用哪次的。
- **P2（最后）**：需要**消耗资源**才能到的页面（战斗中、结算页）—— 只有真打一场才有。

---

## 一、所有路线共用的导航页（P0）

这些是所有路线进门之前都要认的，先采最划算。

| 页面 | 说明 |
|---|---|
| `lobby` | 大厅（首页） |
| `quick_menu` | 快捷菜单（点右上角展开） |
| `battle_menu` | 战斗菜单 |
| `battle_other_menu` | 战斗菜单·其它标签页 |
| `season_menu` | 赛季菜单 |
| `story_ready` | 主线入口 |
| `arena_mode` | 竞技场模式选择 |
| `arena_ready` | 竞技场入口（对手列表） |
| `expedition_home` | 远征主页 |
| `tower_home` | 月塔主页 |
| `shop_refresh` | 秘密商店 |
| `knights_home` | 骑士团主页 |
| `worldboss_home` | 世界首领战主页 |
| `sanctuary_home` | 圣域主页 |
| `hero_list` | 英雄列表 |
| `hero_equipment` | 英雄装备子页 |
| `activity_menu` | 活动页 |
| `web_activity_list` | 网页活动列表 |
| `fodder_episode_detail` | 支线详情 |

## 二、竞技场（9 页）

| 页面 | 关键判据 | 优先 | 状态 |
|---|---|---|---|
| `arena.list` 对手列表（未选对手） | `list_ready` | P0 | ✅ 已有 |
| `arena.selected` 已选中对手（挑战按钮亮） | `challenge` | P0 | ✅ 已有 |
| `arena.team` 队伍选择（战斗开始） | `battle_start` | P0 | ✅ 已有 |
| `arena.battle` 战斗中（自动开着） | `auto_off` | P2 | ❌ 缺 |
| `arena.result` 结算页 | `confirm` | P2 | ❌ 缺 |
| `arena.rank_promotion` 段位晋升弹窗 | `rank_confirm` / 箭头 | P1 | ✅ 已有（2026-11-03 从 PC 实拍帧裁 `templates/pc/rank_confirm.png`） |
| `arena.friendship_ticket_offer` 友情门票弹窗 | 双锚点 | P1 | ✅ 已有（2026-11-02 采，`templates/pc/` 两张） |
| `arena.refresh_confirmation` 刷新确认 | 三锚点 | P1 | ❌ 缺 |

## 三、主线（9 页）

| 页面 | 关键判据 | 优先 |
|---|---|---|
| `story.stage` 关卡页 | `start_mission` | P0 |
| `story.team` 选择队伍 | `select_team` | P0 |
| `story.battle` 战斗中（自动开着） | `auto_on` | P2 |
| `story.results` 结算 | `results_confirm` | P2 |
| `story.complete` 通关 | `complete` | P2 |
| `story.next_stage` 下一关 | `next_stage` | P1 |
| `story.retry` 重试 | `retry_stage` | P1 |
| `story.skip_confirm` 跳过剧情确认 | `skip_confirm` | P1 |
| `story.stamina` 体力弹窗 | `stamina_popup` | P1 |

## 四、远征（10 页）

`expedition.home` `expedition.posters` `expedition.difficulty` `expedition.prepare`
`expedition.team` —— 这 5 页 P0（不消耗就能停到）；
`expedition.battle` `expedition.result` —— P2（要打一场）；
`expedition.public_recruit` `expedition.campfire` —— P1。

## 五、英雄合成（4 页）

`hero.list`（P0）· `hero.detail`（P0）· `hero.synthesis_result`（P1）·
`hero.transmit_result`（P1，需消耗一次传送）。

## 六、骑士团捐赠（7 页）

`knights_donation.guild_home` `knights_donation.weekly_tasks` `knights_donation.activity_panel`
—— P0；其余 4 个弹窗类（奖励 / 请求 / 支援确认 / 资源支援）—— P1。

## 七、迷宫强化石（17 页）

`labyrinth_stone.lobby` `labyrinth_stone.battle_menu` `labyrinth_stone.labyrinth_list`
`labyrinth_stone.labyrinth_detail` `labyrinth_stone.team` `labyrinth_stone.map`
—— P0；`labyrinth_stone.battle` `labyrinth_stone.room` `labyrinth_stone.merchant_room`
—— P2（进场后才有）；其余弹窗/商店类 —— P1。

## 八、月光剧场（9 页）

`moonlight.entry` `moonlight.list` `moonlight.episode` —— P0；
`moonlight.story` `moonlight.clear` —— P2；购买 / 使用券 / 引导 / 奖励 —— P1。

## 九、圣域（3 页）

`sanctuary.home`（P0）· `sanctuary.forest`（P0）· `sanctuary.claim_popup`（P1）。

## 十、刷书签（3 页）

`shop_refresh.shop`（P0）· `shop_refresh.purchase_confirm`（P1）·
`shop_refresh.refresh_confirm`（P1）。

## 十一、活动小游戏（4 页）

`survivor.weapon_card`（P0，进游戏前选卡页）· `survivor.battle`（P2）·
`survivor.result`（P2）· `survivor.level_up`（P1）。

## 十二、月塔（7 页）

`tower.home` `tower.floor_list` `tower.team` `tower.season` —— P0；
`tower.card` `tower.result` —— P2；`tower.conquered` —— P1（打满才出现）。

## 十三、世界首领战（6 页）✅ 2026-11-03 已通

`world_boss.knights_home` ✅ `world_boss.home` ✅ `world_boss.team_select` ✅
`world_boss.team_config` ✅ —— P0；`world_boss.result` ✅ `world_boss.level_reward` ✅ —— P1/P2。

**没有走本清单设想的「口径兜底」路线**，改成了直接补七张 `templates/world_boss/pc/` 同名图。
原因是同页存在**图形锚点**（骷髅盾牌入口 `worldboss_entry`）在 PC 上 0.9936~
0.9940 纹丝不动，说明差异只集中在字形栅格化；而低通口径会把跨页分一并抬高约 0.2
（`result_title` 在奖励弹窗上 0.7103→0.9305），拿余量换分数不划算。
完整对照与决策依据见 `docs/PC_TEMPLATE_MIGRATION.md` §2.7。

补的七张：`knights_title` / `select_team_button` / `team_select_title` /
`team_config_auto` / `battle_skip` / `result_title` / `level_reward_title`。
实跑验证：导航链一次通过（0.994 / 0.976），接力落点可用，战斗可识别并点掉「跳过」，
结算与奖励弹窗均可判页；当日 2/2 次数用完后**干净收场回大厅**。

---

## 采完之后会发生什么

1. 我对每一页跑一次体检，列出「原样不过阈、低通能救」的判据；
2. 对每一颗候选，用全库 308 张夹具验证**翻转数必须为 0**（模拟器结论一字不变）；
3. 一次性把这一批名字加进 `core/matcher.SMOOTH_FALLBACK_ANCHORS`，跑全量测试；
4. 之后这条路线在 PC 上跑，不再需要「挂一颗补一颗」。

合计（**2026-11-06 的采集快照，不是现行名单**）：当时 12 条路线、98 个页面，
其中 P0（不消耗资源就能停到）约 45 页。**现行路线与 PC 放行名单看 [STATUS.md](../STATUS.md)**。
