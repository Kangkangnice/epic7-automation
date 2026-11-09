# 远征视觉维护

远征视觉证据入口：`games/epic7/evidence/expedition.py`。

模板位于 `games/epic7/templates/expedition/`；共享战斗自动按钮使用 `../story/auto_off.png`。改版时先替换模板，再按键名修改 `REGIONS` 或 `THRESHOLDS`。

难度三是否已选中、传单是否可出发、公开招募和返回主页属于业务事务判断，仍在 `games/epic7/expedition.py`。不因识别分数下降直接放宽难度或出发条件。

转场或未知页面超时时，原 `*.png` 旁的同名目录包含 `screen.png` 和 `evidence.json`。按其中 `config`、证据键、`region`、实际 `score` 和 `threshold` 维护；低分仍会量化记录。当前命令行检查器未注册远征，修改后运行远征页面与 Runner 测试。

## 「未持有通缉传单」判据：从静默失效到三道关（2026-10-04）

### 事故

传单用完时应该收工（`PostersExhausted`，退出码 2）。这个判据是 `empty_posters`，
而**模板文件从来就没做** —— 它被登记成「可选」，`build_expedition_templates()` 用
`load_optional()` 加载，文件不在就安静地给个 `None`。

后果不是「少认一种画面」，是**收工判据整个失效**：`_posters_action()` 认不出
「没有可用的通缉传单」，于是继续去找那个永远不会出现的出发按钮，一路等到超时。

- **实测发生 6 次**：2026-09-19 ~ 2026-10-03，每次都停在同一个动作
  `open-my-posters`，诊断图 `..._no_transition_open-my-posters.png` 里画面明写
  「未持有通缉传单 / 持有 0/10」。
- **为什么半个月没发现**：测试用假图（`pattern(3)`）顶替这个模板，所以测试全绿；
  而且有一条测试**断言 `templates.empty_posters is None`** —— 把缺陷当成了预期行为。

### 修法

模板从现场帧裁出（`runtime_diagnostics/epic7_expedition/20261003_193135_...`），
只取固定文案「未持有通缉传单。完成讨伐中级以上将有一定几率获得。」——
**零可变内容**，不含「0/10」和倒计时（模板从现场帧只裁固定文案，裁法见 [`TEMPLATE_CAPTURE.md`](../TEMPLATE_CAPTURE.md)）。

三道关（与英雄合成同款）：

| 关 | 位置 | 缺文件时 |
| --- | --- | --- |
| 加载期 | `build_expedition_templates()` 用 `load()` 而非 `load_optional()` | `FileNotFoundError` 点名 |
| 校验期 | 证据画像 `required=True`，`validate_profile()` | 报「模板不存在」 |
| 运行期 | `_locate()` 对**非白名单**的 `None` 抛 `RuntimeError` | 不允许静默返回 `None` |

### 分离度（正负样本全扫）

| | 分数 |
| --- | --- |
| 现场帧（未持有传单） | **1.0000** |
| `posters.png`（**有**传单的列表页） | 0.2379 |
| 全部 16 张远征夹具最高 | 0.2694 |
| 全库 200+ 张夹具过 0.55 的 | **0 张** |

「有传单」只有 0.2379 是重点：证明模板在区分**两种状态**，不是单纯认列表页。

### `defeated_confirm` 已整个删除：**远征没有「输」这回事**（2026-10-04）

⚠️ 这条判据曾经存在，是我的**误判**，现已删除。经过（记下来防复发）：

1. 它登记成「可选模板」，但模板**从来就没做过**，对应动作在真机日志里
   **执行 0 次**（8/30~10/04，3868 行；同期「公开招募结果」走了 36 次）。
2. 我先把它归类为「同一处隐患」，用户当场质疑：「**之前完全没用过呀，也没问题呀**」
   —— 用户是对的。
3. 用户进一步说明机制：**远征打完伤害就直接进结算，没有「输」这回事**，所有情况
   都是同一类，不存在需要单独识别的「战败页」。

⇒ 所以它不是「缺一张图」，是**这条路线上根本没有这个页面**。留着它的代价：
多一个永远为 `None` 的判据、多一处「可选」口子、多一份要维护的假分支。

**删除范围**（一次清干净）：

| 位置 | 处理 |
|---|---|
| `evidence/expedition.py` 的 `REGIONS` / `_TEMPLATE_NAMES` | 删条目 |
| `expedition.py` 的 `ExpeditionTemplates.defeated_confirm` 字段 + 加载 | 删（`load_optional()` 也随之删除，不再需要） |
| `expedition.py::_defeated_action()` | 整个方法删 |
| `expedition.py::next_action()` 开头那 5 行特殊分支 | 删 |
| 三处 `is_in_state()`（OUTCOME / RECRUIT_CONFIRM / RECRUIT_RETURN） | 删 `or` 的那一端 |
| 两处 `_OPTIONAL_TEMPLATES` | **清空**（不是删机制） |

⚠️ **白名单机制保留、内容清空** —— 它是防静默降级的护栏，不能因为没人用就拆掉。
清空之后语义反而更强：**远征一张模板都不许缺席**。测试
`test_every_template_is_now_required` 逐个把模板置 `None`，断言 `_locate` 必须报错
点名（`empty_posters` / `victory_title` / `campfire_idle` 三个锚点轮着来）。

⚠️ **别再把「可选」当成「先这样，以后再补」的口子** —— `empty_posters` 就是这么丢的
（漏判半个月、空等 6 次）。新增锚点必须**同时**补模板文件。


## 赛季页判据摘掉「远征队」卡片：一条锚点不许身兼两职（2026-10-08）

### 事故

跑月塔时点完大厅「战斗」，游戏已经停在赛季页，导航器却报 `unknown` ⇒ 干等 20 秒、
重试 2 轮 ⇒ `RuntimeError: 导航开始前应处于[大厅]`，月塔**没跑到自己一行代码**。

链条在 `navigation.py::observe()` 的赛季页分支上。当时判据是**三锚点合取**：

| 锚点 | 模板内容 | 实测（报错帧） | 角色 |
| --- | --- | --- | --- |
| `expedition_battle_title` | 「← 战斗」 | **0.9997** ✓ | 页面骨架 |
| `expedition_season_active` | 「赛季」高亮条 | **1.0000** ✓ | 页面骨架 |
| `expedition_entry` | **「远征队」三字 + 骷髅图标** | **0.4734** ✗ | **不该在这** |

`expedition_entry` 的本职是「进入远征队」那一跳的**点击目标**（`modes.py` 里
`NavigationStep(anchor="expedition_entry")`），当初被顺手塞进了页面判据。
而**那排卡片的内容随赛季阶段变** —— 2026-10-08 当季卡片已是「暗影情报商人委托」，
模板掉到 0.4734（阈 0.82）⇒ 三缺一 ⇒ 整页认不出。

同一帧上**月塔自己的** `season_tower_title` 是 **1.0000**（它没坏，是被拦在门外的）。

### 修法

**页面判据只由页面骨架构成**；`expedition_entry` **降级为纯点击目标**
（与 `web_activity_gate` 的处理同款：选中态换判据、旧锚点降级但保留）。
「一般」页（`battle_menu`）同理，只用标题 + 「赛季」未选中态。

### 分离度（25 张导航夹具 + 报错实机帧，正负样本全扫）

| 类别 | 帧 | `min(标题, 赛季高亮)` |
| --- | --- | --- |
| 真·赛季页 | `expedition_season_menu` | **1.0000** |
| 真·赛季页 | `expedition_season_menu_live_20260917` | **0.9772** |
| 真·赛季页 | `season_menu_general_tab_20261004` | **0.9772** |
| 真·赛季页 | 月塔报错帧 `20261008_225939` | **0.9997** |
| 最近负样本 | `expedition_battle_menu` | 0.6006 |
| 次近负样本 | `arena_list` | 0.5727 |

最小分离度 **+0.3772**。

### 护栏与它的反向验证

`test_navigation.py`：

| 用例 | 判据 |
| --- | --- |
| `test_season_menu_is_still_recognised_when_the_expedition_card_looks_nothing_alike` | 拿**月塔真机夹具** `season.png` / `season_2.png`：先断言卡片锚点 **< 0.60**（客观事实），再断言整页仍判 `season_menu` ≥ 0.95 |
| `test_season_menu_page_anchors_survive_the_card_row_being_erased` | 涂掉卡片主体（**y 345 起**）后两锚点仍 ≥ 0.95 |
| `test_expedition_entry_still_exists_as_a_click_target` | 模板与区域都还在（点击链没被误删） |

⚠️ **只断言「整页认得出」是抓不住回归的** —— 那样写的话，把卡片重新绑回判据时，
只要帧恰好没换季也照样过。必须**同时**断言「卡片这张帧上确实认不出」。
反向验证（把 `expedition_entry` 塞回判据）后两条 subtest 立刻变红，确认不是空护栏。

⚠️ 涂区域时注意：`expedition_season_active` 区域是 `(250, 140, 500, 200)`，
**纵跨到 y 340**，与卡片行在 y 240~340 重叠 ⇒ 涂 `240:500` 会削掉标签条下沿
（0.9772 → 0.5564）。要涂就涂 **y 345 起**。

### ⚠️ 同场扫描发现的**未修**问题：`battle_general_tab` 认错了对象（已单独立项）

`battle_general_tab`（区域 `(100,165,250,105)`，名字像是「一般」标签）实测在
`season_menu_general_tab_20261004.png` 上拿 **1.0000** —— 但那张帧的标签条是
**「一般」|「赛季」(蓝色高亮)|「活动」**，模板其实是从**赛季高亮条**上裁的。
另一张 `expedition_season_menu.png` 上它是 0.8668。

后果：迷宫在游戏记住上次停在赛季 tab、实际落在赛季页时，`observe()` 因
`expedition_entry` 失效而判成 `battle_menu` ⇒ 迷宫去点「一般」那一栏（实际是「赛季」）
⇒ 点了没反应 ⇒ 干等 92 秒报同一个 `导航开始前应处于[大厅]`（2026-10-04 卡死一次）。
**原注释把根因记成「没有下一步可走」，实为页面判错。**

本轮按用户要求**只修月塔报错，未动它**。下次处理时要：重裁 `battle_general_tab`
为真正的「一般」两字未选中态、修正 `test_general_tab_anchor_only_fires_on_the_season_page`
的注释与断言。


