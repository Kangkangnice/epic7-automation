# 月塔（欧多马顿塔）视觉维护

视觉证据入口：`games/epic7/evidence/tower.py`。
模板位于 `games/epic7/templates/tower/`；共享战斗自动按钮用 `../story/auto_off.png`。

状态机与 Runner 在 `games/epic7/tower.py`（`TowerStateMachine` + `TowerRunner`，
属于 `TransactionalRunnerBase` 那一族：状态驱动、`commit()` 才前进、目标页连续
两帧才算转场成功）。

## 流程与判据

```
大厅 --点「战斗」(1826,532)--> 赛季页          [导航段，用 navigation.py 的判据]
赛季页 --点月塔卡片(1000,420)--> 月塔主页      [fixed_point，不靠模板定位]
月塔主页 --点「入场」(1640,1055)--> 楼层列表
楼层列表 --点「选择队伍」(1698,1044)--> 准备战斗
准备战斗 --点「战斗开始」(1726,1040)--> 战斗
战斗 --打完--> 三选一装置页
三选一 --点中间卡(958,500)--> 该卡高亮，「决定装置」转亮
三选一 --点「决定装置」(1138,1040)--> 结算页（CLEAR + 第N层 + 下一层）
结算页 --点「下一层」(1787,1041)--> 约 7 秒回到准备战斗页（层数+1，队伍记住）
```

⚠️ **点击点一律用常量**（`TowerStateMachine._POINT_*`），不靠 `match.center`
—— 裁剪会带动点击点，判据与点击点必须分离。

⚠️ **一层耗 15 体力**；不允许补充体力；打满 25 层是停止条件
（`FloorsConquered`，`stop_label = "月塔层数已打满"`）。

## ⚠️ 事故一：转场中途重试 ⇒ 误开战斗（2026-10-09）

### 现象

真机每日任务跑到 `select-team` 卡住，56 秒后放弃：

```
00:18:57 点 select-team (1698,1044) 尝试=1/4
00:19:00 转场重试 动作=select-team 来源=楼层列表仍在 尝试=2/4   ← 在转场中途又点了一下
00:19:01 等待转场 动作=select-team 来源=楼层列表已离开 目标=准备战斗待稳定
00:19:57 已保存诊断 ..._no_transition_select-team.png           ← 等了 56 秒
```

诊断帧是**战斗进行中**的画面（技能特效、血条、buff 图标）—— 战斗早就打起来了。

### 根因

| 环节 | 数值 | 说明 |
| --- | --- | --- |
| `settle`（点完先等的时长） | **1.0 秒**（默认 `poll_seconds`） | 月塔没覆写 `_SETTLE_SECONDS` |
| 实测转场时长 | **2.0 ~ 3.1 秒**（同一次日志） | 比 settle 长 |
| 重试判据 | 源页连续 2 帧仍在 | 1.0 + 1.0 = **2.0 秒就触发** |
| `select-team` 与 `battle-start` 的点击点 | **相距 28 px** | (1698,1044) vs (1726,1040) |

结论：**1 秒后截图时转场还没播完，源页「当然还在」⇒ 判「这一下没生效」⇒
重试点击**。而那两个点击点**落在同一颗绿色按钮槽位上**（把两点画在
`team.png` 上，都落在「战斗开始」里）⇒ 转场一完成，重试那一下**正好按下
「战斗开始」** ⇒ 直接开打 ⇒ 状态机还在等「准备战斗」页 ⇒ 白等到超时。

### 修法

```python
# tower.py / TowerRunner
_SETTLE_SECONDS = 3.0   # ≥ 实测转场上界（3.1 秒 → 取 3.0 + 帧间轮询覆盖）
```

竞技场早就遇到过同类问题，它覆写的是 `1.5`；月塔转场更慢（多一段过场动画），
所以取更大值。改完之后第一帧截图就落在转场窗口之外，**重试分支根本不会触发**。

### ⚠️ 走过的弯路：加了一条**假防线**（记下来防复发）

第一版修法在 `action_source_visible` 里加了一条「准备战斗页特征已出现就判源页不在」。
它**看起来对**，但反向验证发现**拆掉它测试照样全绿** —— 是空护栏。

原因：`floor_select_team` 在准备战斗页上只有 **0.5576**（阈 0.88），
`is_in_state(FLOOR_LIST)` **本来就返回 False**。也就是说那条判据**没有增量**，
只是把一段永远不生效的代码写进了生产路径 —— 正违反「判据不许静默失效」。

⇒ **已删除**。真正解决问题的是 `_SETTLE_SECONDS`（等够时间），不是加判据。
保留的是一条**前提护栏**：`floor_select_team` 在准备战斗页上必须不过阈
（`test_select_team_source_page_cannot_survive_the_team_page`）—— 它是「源页仍在」
能在转场后自动变假的基础，这条前提一旦不成立，`_SETTLE_SECONDS` 调多大都没用。

### 护栏（`tests/test_epic7_tower.py`）

| 用例 | 判据 |
| --- | --- |
| `test_settle_window_outlasts_the_recorded_tower_transitions` | `_SETTLE_SECONDS` 非 `None` 且 ≥ 3.0（阈值独立写死） |
| `test_select_team_source_page_cannot_survive_the_team_page` | 楼层列表帧成立、准备战斗帧不成立 + 锚点分数 < 0.88 |
| `test_the_second_click_of_select_team_would_land_on_battle_start` | 两个点击点各轴距离 ≤ 40px（守「重试=误开打」这个前提） |
| `test_other_states_still_report_their_source_page_normally` | 别的动作的源页判据没被顺带改掉 |

反向验证（把 `_SETTLE_SECONDS` 改回 `None`）后第一条立刻变红，确认不是空护栏。

## ⚠️ 事故二：赛季页判据塞了远征卡片 ⇒ 整页认不出（2026-10-08）

跑月塔时点完大厅「战斗」，游戏**已经**停在赛季页，导航器却报 `unknown` ⇒
干等 20 秒、重试 2 轮 ⇒ `RuntimeError: 导航开始前应处于[大厅]`，
**月塔连自己一行代码都没跑到**。

根因不在月塔，在 `navigation.py::observe()` 的赛季页判据（当时是三锚点合取，
第三个是 `expedition_entry` = 「远征队」三字，随赛季换内容失效 0.4734）。
同一帧上月塔自己的 `season_tower_title` 是 **1.0000**。

⇒ 详见 `docs/maintenance/expedition.md`「赛季页判据」节与 `topics/anchors` §15。

## ⚠️ 未修：`battle_general_tab` 名实不符（迷宫，不属月塔）

同场扫描发现 `battle_general_tab` 实际认的是**赛季高亮条**而非「一般」标签，
是 2026-10-04 迷宫卡死 92 秒的真根因。**本轮按用户要求未动**，
详见 `docs/maintenance/expedition.md` 末节。
