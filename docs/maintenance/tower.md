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

## ⚠️ 事故一：转场中途重试 ⇒ 误开战斗（2026-10-09，**修了两轮**）

### 现象

真机每日任务跑到 `select-team` 卡住，60 秒后放弃：

```
00:18:57 点 select-team (1698,1044) 尝试=1/4
00:19:00 转场重试 动作=select-team 来源=楼层列表仍在 尝试=2/4   ← 在转场中途又点了一下
00:19:01 等待转场 动作=select-team 来源=楼层列表已离开 目标=准备战斗待稳定
00:19:57 已保存诊断 ..._no_transition_select-team.png           ← 等了 56 秒
```

诊断帧是**战斗进行中**的画面（技能特效、血条、buff 图标）—— 战斗早就打起来了。

### 第一轮修法（**错的，记下来防复发**）：加大 `_SETTLE_SECONDS`

当时的推理：默认 `settle` = `poll_seconds` = **1.0 秒**，而转场要 2~3 秒 ⇒
第一帧截图时源页「当然还在」⇒ 触发重试。于是覆写 `_SETTLE_SECONDS = 3.0`。

**结果：08:16 与 08:21 两次实跑照样重试**，日志几乎一模一样：

```
08:21:12 点 select-team 尝试=1/4
08:21:16 转场重试 尝试=2/4      ← settle 3.0 生效了（间隔 4 秒），但还是重试
08:21:21 转场重试 尝试=3/4
08:21:26 转场重试 尝试=4/4
08:21:33 来源=楼层列表已离开     ← 点完 **21 秒**源页才离开
08:22:12 诊断 ...（又是战斗画面）
```

为什么输：**拿一个固定值去赌转场时长**。参考的是**导航段**的 2~3 秒，
而这个**路线内**转场实测要 **>5 秒**。转场时长还随机器负载波动 ⇒ 赌不赢；
加大还会拖慢「真·点击失效」的发现速度。

对照同一次会话里**安全的** `enter-tower`（月塔主页→楼层列表）：

| 转场 | 耗时 | 结果 |
| --- | --- | --- |
| `enter-tower` | **5 秒** | ✅ 一次过，零重试 |
| `select-team` | **>21 秒** | ❌ 4 次重试后仍未到 |

⇒ 说明**第一下本来就是生效的**，是重试自己把战斗点起来的，属**自伤循环**。

### 真正的根因

基类的重试语义是「这一下没生效 ⇒ 再按一次**同一个坐标**」。这个语义成立的前提是
**那个坐标上放的还是原来那颗按钮**。月塔右下角那个绿色按钮槽**转场后会换按钮**：

| 动作 | 坐标 | 按钮 | 页面 |
| --- | --- | --- | --- |
| `select-team` | (1698, 1044) | 「选择队伍」 | 楼层列表 |
| `battle-start` | (1726, 1040) | 「战斗开始」 | 准备战斗 |

**两点相距只有 28 px**（`test_the_second_click_of_select_team_would_land_on_battle_start` 钉住）。
转场一完成，重试那一下**正好按下「战斗开始」**⇒ 直接开打。

### 第二轮修法（**正确**）：关掉这个动作的重试

基类新增钩子 `TransactionalRunnerBase._retry_is_safe(action)`，**默认 `True`**
（远征 / 竞技场逐帧行为不变）；月塔覆写：

```python
# tower.py / TowerRunner
_RETRY_UNSAFE_ACTIONS = frozenset({"select-team"})

def _retry_is_safe(self, action: TowerAction) -> bool:
    return action.name not in self._RETRY_UNSAFE_ACTIONS
```

转场慢**不是**重试的理由 —— 按转场契约「来源已离开 ⇒ 只等待，禁止重复旧动作」；
真正「点不中」由 **60 秒状态超时**兜底。`_SETTLE_SECONDS = 3.0` 保留，但它
**不再承担安全职责**，只是让第一帧尽量落在转场窗口外、少空转几帧。

⚠️ 目前只有 `select-team` 一条：`enter-tower` / `battle-start` / `next-floor`
的落点与别的按钮离得远（不在同一槽位），重按无害，保持默认。

### 护栏（`tests/test_epic7_tower.py::RetrySuppressionTests`，4 条）

**行为测试**：真的跑 `_execute_transition` 的循环、数真点了几次。

| 用例 | 判据 |
| --- | --- |
| `test_select_team_is_never_clicked_twice_even_when_the_source_stays` | 喂「源页一直可见」的假运行时 ⇒ `select-team` 只能点 **1 次** |
| `test_the_suppression_is_reported_in_the_log` | 「不动手」也要留证据（日志含「不重试」） |
| `test_other_actions_still_retry_normally` | ⚠️ 成对：`enter-tower` 仍应重试（机制还活着） |
| `test_the_declared_unsafe_set_matches_the_two_click_points` | 两点距离 ≤40px **且** 名单独立写死 = `{"select-team"}` |

⚠️ **只断言「`_SETTLE_SECONDS` 够大」是空护栏** —— 第一版就是这么写的，
把 settle 从 1.0 加到 3.0 之后实跑照样重试。**必须数点击次数。**

### 反向验证（`auto_game_unified/.workbuddy/_rv_retry.py`）

| 注入 | 结果 |
| --- | --- |
| ① 清空 `_RETRY_UNSAFE_ACTIONS` | **3 failed**, 1 passed |
| ② 摘掉 `TowerRunner` 的覆写 | **2 failed**, 2 passed |
| ③ 名单改成 `enter-tower` | **4 failed** |

⚠️ **反向验证脚本自己踩了一个坑**：`TARGET_TESTS` 少了尾逗号 ⇒ 从元组变成
**字符串** ⇒ `*TARGET_TESTS` 展开成一个个**字符** ⇒ pytest 收到 `a`，
报 `file or directory not found` 并以非零退出 —— **看着像「变红」，其实一条用例都没跑**。
⇒ 脚本里加了「必须真的跑起来」的判据（输出含 `passed`/`failed` 且不含 `not found`）。
老教训再现：**「变红」不等于「有效」，要先证明用例跑起来了。**

### ⚠️ 走过的另一段弯路：加了一条**假防线**（记下来防复发）

第一版修法还顺手在 `action_source_visible` 里加了「准备战斗页特征已出现就判源页不在」。
它**看起来对**，但反向验证发现**拆掉它测试照样全绿** —— 是空护栏。

原因：`floor_select_team` 在准备战斗页上只有 **0.5576**（阈 0.88），
`is_in_state(FLOOR_LIST)` **本来就返回 False**。那条判据**没有增量**，
只是把一段永远不生效的代码写进生产路径 —— 正违反「判据不许静默失效」。

⇒ **已删除**。保留的是一条**前提护栏**：`floor_select_team` 在准备战斗页上必须不过阈
（`test_select_team_source_page_cannot_survive_the_team_page`，实测 0.5576 / 0.5648）。

### 另外两条护栏

| 用例 | 判据 |
| --- | --- |
| `test_settle_window_outlasts_the_recorded_tower_transitions` | `_SETTLE_SECONDS` 非 `None` 且 ≥ 3.0（阈值独立写死） |
| `test_select_team_source_page_cannot_survive_the_team_page` | 楼层列表帧成立 / 准备战斗帧不成立 + 锚点分数 < 0.88 |

⚠️ 点击常量在 **`TowerStateMachine`** 上（`_POINT_*`），不在 `TowerRunner` ——
写护栏时踩了一次 `AttributeError`。

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
