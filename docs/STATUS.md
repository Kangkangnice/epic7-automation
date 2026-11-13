# 现状速查

> 本页由 `python -m auto_game_unified.tools.gen_status` 从代码生成，**不要手改**。
> 门禁 `tests/test_status_doc.py` 会逐字比对：与代码不一致就直接报红。
> 想知道「现在到底支持哪些、哪些放行了」，只看这一页就够。

**产品**：第七史诗自动助手 v0.1.0

## 一、路线总览（共 18 条）

| # | 路线 | 界面名称 | 分组 | 默认次数 | 次数可改 | 有导航 | 模拟器 | PC 客户端 |
|---|------|---------|------|---------|---------|-------|-------|----------|
| 1 | `hero_synthesis` | 英雄合成 | 按需 | 1 | 否 | 是 | 可用 | 已放行 |
| 2 | `story` | 主线 | 按需 | 1 | 是 | 是 | 可用 | 已放行 |
| 3 | `arena` | 竞技场 | 每日 | 10 | 是 | 是 | 可用 | 已放行 |
| 4 | `expedition` | 远征 | 赛季 | 1 | 是 | 是 | 可用 | 未放行 |
| 5 | `tower` | 月塔 | 赛季 | 25 | 是 | 是 | 可用 | 已放行 |
| 6 | `fodder` | 狗粮 | 按需 | 1 | 是 | 是 | 可用 | 未放行 |
| 7 | `side_story` | 支线故事 | 按需 | 99 | 否 | 是 | 可用 | 已放行 |
| 8 | `shop_refresh` | 刷书签 | 每日 | 0 | 是 | 是 | 可用 | 已放行 |
| 9 | `survivor` | 活动 | 活动 | 3 | 是 | 否 | 可用 | 未放行 |
| 10 | `activity_story` | 活动剧情 | 活动 | 99 | 否 | 否 | 可用 | 已放行 |
| 11 | `world_boss` | 世界首领战 | 每日 | 2 | 否 | 是 | 可用 | 已放行 |
| 12 | `knights_donation` | 骑士团捐赠 | 每日 | 1 | 否 | 是 | 可用 | 已放行 |
| 13 | `labyrinth_stone` | 迷宫强化石 | 每日 | 1 | 否 | 是 | 可用 | 已放行 |
| 14 | `sanctuary` | 圣域收菜 | 每日 | 1 | 否 | 是 | 可用 | 已放行 |
| 15 | `community` | 社区签到 | 每日 | 1 | 否 | 是 | 可用 | 未放行 |
| 16 | `moonlight_theater` | 月光剧场 | 按需 | 99 | 否 | 是 | 可用 | 已放行 |
| 17 | `achievement` | 成就领取 | 每日 | 1 | 否 | 是 | 可用 | 已放行 |
| 18 | `story_star` | 主线补星 | 按需 | 1 | 否 | 是 | 不可用（仅 PC） | 已放行 |

图例与口径：

- **模拟器**：「不可用（仅 PC）」表示这条路线只有 PC 素材；界面勾选时只跳过它自己，
  每日任务连打里记 `not_supported`，都不算失败。
- **PC 客户端**：界面只放行 `desktop/catalog.PC_READY_ROUTES` 里的路线；
  勾到没放行的路线也只跳过那一条、其余照跑（日志会说明），全不可用才报错。
  命令行 `--window-backend pc` 不受这层限制。
- **默认次数**：界面上预填的值，`-` 表示该路线没有次数概念。

## 二、在制品（进行中）

> 这一节一旦有条目，说明**有工作没做完**。每份交接单在 [`docs/wip/`](wip/)，
> 合并进 main 之后要删掉。开工做到一半要停时，复制
> [`wip/_TEMPLATE.md`](wip/_TEMPLATE.md) 建一份 —— 见 `AGENTS.md`「做到一半要停」。

（当前没有未完成的工作）

## 三、每日任务的执行顺序（共 8 条）

界面上「每日」分组按下表从上到下执行；每段之间会先确认回到大厅再开下一条。

1. 世界首领战（`world_boss`）
2. 骑士团捐赠（`knights_donation`）
3. 圣域收菜（`sanctuary`）
4. 刷书签（`shop_refresh`）
5. 迷宫强化石（`labyrinth_stone`）
6. 竞技场（`arena`）
7. 月光剧场（`moonlight_theater`）
8. 成就领取（`achievement`）

## 四、仅 PC 的路线

- 主线补星（`story_star`）

## 五、素材与测试规模

- 识别模板 **500** 张，其中 PC 专用 **148** 张
- 现场夹具 **457** 张（`tests/fixtures/`，跑测试用的真实截图）

注意：这两个数字**加一张图就要重生成一次**。这是有意的 —— 素材入库本来就要在
`tests/test_template_paths.py` 登记，多跑一次生成器只是同一步的延续。
测试文件个数刻意不写在这里：它每天都在变，写进来只会让这一页天天过期。

### 按路线的现行事实（自动生成）

> 路线手册里**不要再手抄**「有几张 PC 图 / 几张模板 / 几张夹具」，链到本表即可。
> 口径：模板只数 `games/epic7/templates/<路线>/` 与 `templates/pc/<路线>/`；
> 夹具数 `tests/fixtures/epic7_<路线>` 前缀（含 `epic7_<路线>_pc/` 等变体目录）；若与另一条路线重名前缀，在 `ROUTE_FIXTURE_EXCLUDES` 显式排除。
> `hero_synthesis` 的素材目录叫 `hero`；`arena` 的模板与全局共享图混放在模板根，
> 无法按路线归属，标「共享根」而不是报一个假的 0 —— 别名见 `gen_status.py::ROUTE_DIR_ALIASES`。
> 开局接力读 `MODE_SPECS.resume_probe` 与 `RESUME_EXEMPT`，PC 放行读 `PC_READY_ROUTES`。

| 路线 | PC 专用图 | 模板合计 | 现场夹具 | 开局接力 | PC 放行 |
|---|---:|---:|---:|---|---|
| `hero_synthesis` | 11 | 28 | 34 | 豁免（见 modes.py） | 已放行 |
| `story` | 9 | 34 | 45 | 有探针 | 已放行 |
| `arena` | 共享根 | 共享根 | 28 | 有探针 | 已放行 |
| `expedition` | 0 | 19 | 17 | 有探针 | 未放行 |
| `tower` | 9 | 21 | 29 | 有探针 | 已放行 |
| `fodder` | 0 | 6 | 11 | 豁免（见 modes.py） | 未放行 |
| `side_story` | 5 | 31 | 31 | 有探针 | 已放行 |
| `shop_refresh` | 8 | 26 | 32 | 有探针 | 已放行 |
| `survivor` | 0 | 6 | 6 | 不适用（无导航） | 未放行 |
| `activity_story` | 1 | 3 | 3 | 不适用（无导航） | 已放行 |
| `world_boss` | 7 | 18 | 30 | 有探针 | 已放行 |
| `knights_donation` | 12 | 34 | 16 | 有探针 | 已放行 |
| `labyrinth_stone` | 14 | 50 | 30 | 有探针 | 已放行 |
| `sanctuary` | 4 | 9 | 19 | 有探针 | 已放行 |
| `community` | 0 | 33 | 21 | 豁免（见 modes.py） | 未放行 |
| `moonlight_theater` | 4 | 23 | 26 | 豁免（见 modes.py） | 已放行 |
| `achievement` | 6 | 12 | 11 | 有探针 | 已放行 |
| `story_star` | 9 | 9 | 10 | 有探针 | 已放行 |

## 六、这一页之外去哪找

- 文档索引与「我该看哪一份」：[`docs/README.md`](README.md)
- 为什么当初这么定：[`docs/decisions/`](decisions/)
- 每条路线怎么维护：[`docs/maintenance/`](maintenance/)
- 改了什么：[`CHANGELOG.md`](../CHANGELOG.md)
