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
三选一 --点「决定装置」(1138,1040)--> 结算页（CLEAR + 第N层 + 右下角按钮）
结算页 --点右下角按钮(1787,1041)--> 约 7 秒回到准备战斗页（层数+1，队伍记住）
                                    └─ 第 25 层时：弹出「征服欧多马顿塔」= 终点，收工
```

⚠️ **点击点一律用常量**（`TowerStateMachine._POINT_*`），不靠 `match.center`
—— 裁剪会带动点击点，判据与点击点必须分离。

⚠️ **一层耗 15 体力**；不允许补充体力；打满 25 层是停止条件
（`FloorsConquered`，`stop_label = "月塔层数已打满"`）。

## ⚠️ 打满 25 层：终点是「征服欧多马顿塔」那一屏（2026-10-09 实机，用户拍板）

### 现场长什么样

用户手动打满 25 层后，**同一趟流程里出现了两处变化**：

1. **第 25 层的结算页，右下角按钮从「下一层」变成「征服」**，左侧体力条（15/1273）消失。
2. 点下去**不是**回到准备战斗页，而是弹出 **「征服欧多马顿塔」叙述屏**：
   居中金色标题 + 三行固定正文 + 底部「点击关闭」。

用户对第 2 屏的定性（原话）：

> 「一碰到这个界面就代表要结束了，就是整个环节的最终的一个终点」

⇒ 实现成：**认出即抛 `FloorsConquered` 收工，一个按钮都不点**。

### 关键测量：两个按钮**同一个槽位**

```
======================  ============================  ==========
结算页                    绿色本体 bbox                 按钮文字
======================  ============================  ==========
普通层                   1483,997 → 1879,1092          「下一层」
第 25 层                 **完全相同**                   「征服」
======================  ============================  ==========
```

绿底 bbox **逐像素一致**（396×95），**只有文字不同**。

⇒ **不为「征服」另做按钮判据**，两条理由：

1. **做了也没用**：征服弹窗是半透明的、**不遮住这个按钮**，同一枚模板会同时命中
   两屏 —— 实测 `result_conquered_floor` 1.0000 / `conquered` **0.9997**，
   间距 **+0.0003**（等于没有）。这条已写进 `evidence/tower.py` 的
   「`conquer_button` 刻意不存在」。
2. **不需要**：两个文字在同一个按钮槽 ⇒ 点哪个都是点**同一个坐标** `(1787, 1041)`。

⇒ 动作照旧（`RESULT` 的 `next-floor`），**判据只加一条标题**：

| 判据 | 判哪一页 | 本页 | 他页最高 | 间距 |
|---|---|---|---|---|
| `conquer_title` | 征服弹窗（标题「征服欧多马顿塔」） | 1.0000 | 0.2810 | **+0.72** |

⚠️ 这是全月塔**分离度最干净**的一条判据。

### `RESULT` 分岔：靠「点完之后落到哪」自己分

```python
target_states=(TowerState.CONQUERED, TowerState.TEAM),   # 终点在前
```

基类逐个检查目标页是否出现。两页实测互斥（征服屏上 `team_battle_start` 只有
0.4323），顺序只是「万一同时成立先认终点」—— **宁可早收工，不可把终点当下一层**。

### 为什么要抛异常，而不是返回 None

`return None` 只会让主循环每拍 `sleep(poll_seconds)` 空转，直到 **60 秒状态超时**
⇒ 报 `RuntimeError`、**退出码 1**（假故障）。而这分明是「正常打满了」（**退出码 2**）。
走 `ResourceExhausted` 那条通道，收尾也会照常回家（基类 `_close_out`）。

⚠️ 抛之前先 `_required(screen, "conquer_title")`：主循环的**结论门槛**要求连续两帧
一致，`_required` 失败会抛 `UnrecognizedScreen`（不采信结论）—— 单帧抖动不该
宣布「打满了」。

### 别把这一屏当「过场页」去点掉它

用户实测点「点击关闭」之后**回到月塔主页**，而那时**进度已经清空**
（主页显示「第5阶段 / 征服 / 已占领层 并领取了奖励」）。
⇒ 再往下走既没有业务，又可能误开新的一轮。**终点就该收手。**

## ⚠️ 查「某个判据在某层失效」之前，先怀疑自己的取图链路（2026-10-09，我踩的）

勘察这趟时我一度报出「`result_clear` 在第 25 层失效（1.0000 → 0.7809）」，
还配了「第 25 层是蓝光、普通层是橙光」的说法。**全是错的，是假警报。**

**根因**：`Epic7Window.capture()` 返回的是 **RGB**
（`window.py` 里 `render[:, :, :3][:, :, ::-1]`），而我拿它**直接 `cv2.imwrite`**
—— cv2 按 BGR 写盘 ⇒ **红蓝对调**。于是「橙金色（R 最大）」被我存成了
「蓝青色（B 最大）」，读回来一看就成了「第 25 层是蓝的」。

```
current.png（程序实存）              B= 33.6 G= 44.3 R= 55.3   ← R 最大（暖）
result.png（老夹具）                 B= 28.4 G= 37.5 R= 47.8   ← R 最大（暖）
result_conquered_floor.png（我存的）  B= 54.3 G= 43.5 R= 33.1   ← B 最大（冷）★反了
```

**修法**：改用程序实跑时自己存的 `runtime_diagnostics/epic7_tower/current.png`
（那份色序是对的）。重验：

| 帧 | `result_clear`（RGB 生产口径） |
|---|---|
| `result.png`（普通层） | 1.0000 |
| `result_conquered_floor.png`（第 25 层，修正后） | **0.9327 ✅ 过阈** |

⇒ **第 25 层的 CLEAR 与普通层没有区别，判据原本就是好的。**

⚠️ **纪律**：报「找不到 X / X 失效」时，**第一嫌疑人是我们自己的取图链路**
（存图转没转色序），不是游戏。用户当场质疑「那个 clear 大家都一样的呀……
你从哪里有这依据」才查出来 —— 与 2026-10-09 上午社区那条同族
（**先问「X 真的不在，还是我没去看那一块 / 拿错了尺子」**）。


## ⚠️ 事故一：转场中途重试 ⇒ 误开战斗（2026-10-09，**改了三轮才收口**）

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

### 真正的根因：**同一个按钮槽，转场后换按钮**

基类的重试语义是「这一下没生效 ⇒ 再按一次**同一个坐标**」。这个语义成立的前提是
**那个坐标上放的还是原来那颗按钮**，而月塔右下角那个绿色按钮槽**转场后会换按钮**：

| 动作 | 落点 | 下一屏同位置的按钮 | 偏差 |
| --- | --- | --- | --- |
| `enter-tower` | (1640, 1055) | 「选择队伍」 | **59 px** |
| `select-team` | (1698, 1044) | 「战斗开始」 | **28 px** |
| `next-floor` | (1787, 1041) | 「战斗开始」 | **61 px** |
| `battle-start` | (1726, 1040) | （下一屏是战斗） | 无害 |

⚠️ 按钮本体宽 **231~242 px**（`.workbuddy/_retry_overlap.py` 实测），28 / 59 / 61 px
全部落在按钮里面 ⇒ **四条动作里三条压住下一屏的按钮**。转场一完成，重试那一下
正好按在下一屏的按钮上。

⚠️⚠️ **踩过的错，别照抄**：旧版本这里写着「`enter-tower` / `battle-start` /
`next-floor` 的落点与别的按钮离得远（不在同一槽位），重按无害」，并用
「两点距离 ≤ 40px」当尺子去选名单 —— 那把尺子**只抓到 28 px 那条**，
**59 px / 61 px 两条全部漏掉**。两句都已改掉。

### 第二轮修法（**对了一半，已废弃**）：关掉这个动作的重试

先在基类加钩子 `_retry_is_safe(action)`（默认 `True`），月塔覆写成
`_RETRY_UNSAFE_ACTIONS = {"select-team"}` 一份名单。**它确实止住了事故**，但方向不对：

* 落点重叠是**布局的普遍属性**，不是那一个槽位的特例（见上表：四条里三条中招）；
* 名单的尺子本身也不好定（≤40px 那把尺子漏了两条）；
* 用户明确否掉了「一律禁止重试」：**那会把「真的没点到」也一起禁掉。**

⇒ 已被第三轮取代，`_RETRY_UNSAFE_ACTIONS` / `_retry_is_safe` **已从代码里删除**。

### 第三轮修法（**最终**）：按「画面冻没冻」判，不列名单

用户当时的原话：**「我觉得你之前说的禁止(重试)，我觉得不太对」**，并给出自己的判据：

> 卡住的话，它是整个界面一动不动，就任何什么光效什么都不动；如果是没点到的话，
> 你点完之后发现，他的整个场面还在动。

⇒ 落成两条规则（`transactional_runner_base._retry_block_reason`）：

* **画面还在动** ⇒ 这一下确实没生效（真没点到）⇒ **允许补点**；
* **画面完全冻结** ⇒ 游戏正忙（转场 / 加载），它不是没收到点击 ⇒ **只等，不补点**
  —— 这时候补的那一下会被游戏**攒着**，等下一屏出来一次性兑现。

判据本体是 `core.supervisor.screens_are_identical`（相邻两帧**逐字节相同**）。
月塔只声明一行就开了闸门（基类默认关，远征 / 竞技场的逐帧行为不变）：

```python
# tower.py / TowerRunner
_RETRY_REQUIRES_MOTION = True
```

#### 为什么判据是「逐字节相同」，不是「画面差多大」

真机录帧（`.workbuddy/_trans_frames/`，286 帧、0.3 秒/帧，楼层列表 → 准备战斗页）：

| 窗口 | 区域平均差 | 逐字节相同 |
| --- | --- | --- |
| 楼层列表**待机** 147 对 | 0.095 ~ 0.862（**全部 < 2.0**） | **0 对** |
| 转场**加载中** 50 对 | 0.000（另 2 对 0.067） | **50 对**（45 帧是同一个 md5） |

⇒ 现成的 `meaningful_change`（阈 2.0）**不能用**：待机那 0.095~0.862 会被**整片判成
「冻住」**，判据恒真；而同一套算法在大厅是 11~45（**跨页差 30 倍**），根本没有能用的
统一阈值。

⚠️ 待机「平均差只有 0.095~0.862」**不等于画面没动**：实测待机两帧之间有
**112 万个像素**在变（占全屏 50%），只是幅度只有 ±1~2 级、被全屏平均摊薄了
⇒ 必须问「**有没有一个像素变过**」，不能问平均值。

#### 这条判据为什么盖得住那两次事故

事故日志里「源页仍在」持续了**十几秒**，远超转场本身：

```
21:03:43 点 select-team (1698,1044)
21:03:48 不重试 动作=select-team 来源=楼层列表仍在     ← +5 秒源页判据还在命中
21:03:54 等待转场 来源=楼层列表已离开                   ← +11 秒才离开
21:03:55 转场确认 select-team 楼层列表 -> 准备战斗
```

源页判据（阈 0.88）在「按下态」的帧上只有 **0.7382**，也就是**根本判不出来**。
⇒ 那 11 秒里判据之所以一直命中，只能是**游戏连按下态都没渲染出来** ——
屏幕上还是那一张**陈旧帧**（模拟器没重绘）。**同一个原因既让 tap 处理不了、
也让画面一动不动**，所以「冻没冻」正好落在危险窗口上。

#### 附带的：帧有效性分诊

`_retry_block_reason` 先问 `valid_game_frame`：全黑帧（窗口被遮挡、`PrintWindow`
拿不到画面）报的是「**这一帧取不到游戏画面**」，而不是「画面冻结」。两者都不补点，
但混成一句话会让复盘误判成「游戏在加载」。

### 护栏（`tests/test_epic7_tower.py::RetrySuppressionTests`，6 条）

**行为测试**：真的跑 `_execute_transition` 的循环、数真点了几次。
假运行时按**给定序列循环回帧**：喂一张 = 模拟器不重绘；喂两张不同的帧 = 页面还在动。

| 用例 | 判据 |
| --- | --- |
| `test_a_frozen_screen_is_never_clicked_twice` | 只看得到同一张帧 ⇒ `select-team` 只能点 **1 次** |
| `test_the_suppression_is_reported_in_the_log` | 「不动手」也要留证据（日志含「不重试」+「冻结」） |
| `test_a_live_screen_still_retries` | ⚠️ 成对：两张不同帧 ⇒ **必须继续补点**（机制还活着） |
| `test_a_single_different_pixel_counts_as_motion` | 零阈值：只差**一个像素**也放行 |
| `test_a_frame_we_cannot_read_is_not_reported_as_frozen` | 全黑帧报「取不到」、不报「冻结」（钩子级） |
| `test_every_recorded_page_is_a_valid_frame` | ⚠️ 另一方向：15 张真机夹具**不许**被判成「取不到画面」，否则闸门退化成「永不重试」 |

判据本体在 `tests/test_supervisor.py` 也钉了两条，其中一条是**成对反证**：
同一对帧上 `meaningful_change` 判「没动」、`screens_are_identical` 判「在动」，
把两条判据的语义分岔写死。

⚠️ **只断言「`_SETTLE_SECONDS` 够大」是空护栏** —— 第一版就是这么写的，
把 settle 从 1.0 加到 3.0 之后实跑照样重试。**必须数点击次数。**

### 反向验证（`auto_game_unified/.workbuddy/_rv_retry.py`）

| 注入 | 结果 |
| --- | --- |
| ① 摘掉 `_RETRY_REQUIRES_MOTION = True` | **3 failed**, 3 passed |
| ② `screens_are_identical` 恒 `False` | **2 failed**, 4 passed |
| ③ `screens_are_identical` 恒 `True` | **2 failed**, 4 passed |
| ④ 基类钩子直接 `return None` | **3 failed**, 3 passed |
| ⑤ 两条原因文案对调 | **2 failed**, 4 passed |

②③ 是**成对**的：只注入「恒真」会漏掉「画面在动就该补点」那半条契约，只注入
「恒假」会漏掉「冻住就不补」那半条。**两个方向都要红，判据才算两头都钉住。**

⚠️ **反向验证脚本自己踩过两个坑**（都记下来）：
1. `TARGET_TESTS` 少了尾逗号 ⇒ 从元组变成**字符串** ⇒ `*TARGET_TESTS` 展开成一个个
   **字符** ⇒ pytest 收到 `a`，报 `file or directory not found` —— **看着像「变红」，
   其实一条用例都没跑**。
2. 「用例有没有跑起来」的判据一开始写成「输出里不含 `not found`」⇒ 被 `assertIn` 的
   失败文案（`'X' not found in 'Y'`）误伤，**把真·变红误报成「没跑起来」**
   （结论碰巧是对的，但那是运气）。现在认的是 pytest 的**结果行**
   （`\d+ (passed|failed)`）。

⇒ 老教训再现：**「变红」不等于「有效」，要先证明用例跑起来了。**

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

## ⚠️ 事故三：战斗打到一半「回退首页」（2026-10-09，用户报「打着打着回退」）

用户原话：**「月塔还是报错，有那么难吗远征也有战斗啊，竞技场也有啊，怎么就会打着打着回退呢」**
—— 这个对比正好指向了根因。

### 现场（`runtime_logs/epic7_tower.log` 13:59 那一段）

```
13:59:10  转场确认  battle-start -> 战斗中，移交战斗监督
13:59:13  「已进入」/「自动战斗已开启」      布局=auto_controls 图标=None
13:59:29  「开启自动战斗 尝试=1/4」          布局=auto_controls 图标=0.8055
13:59:30  「来源=自动关闭已离开」            图标掉下阈
13:59:43  安全停止 原因=手动战斗状态下缺少自动开关坐标     布局=manual_controls 图标=None
```

**同一场战斗（自动其实一直开着），23 秒里判定翻了三次。**

### 根因：**弱证据推翻了强证据**

`tower.py` / `expedition.py` / `arena.py` 里是**同一份复制粘贴**的代码：

```python
auto_state = {AUTO_CONTROLS: AUTO, MANUAL_CONTROLS: MANUAL,
              TRANSITION: UNKNOWN}[controls]
if auto is not None:
    auto_state = MANUAL            # 无条件信右上角图标
```

这两条证据的强弱**差了两个数量级**：

| 证据 | 实测分离度 | 判据 |
| --- | --- | --- |
| **布局**（强） | 自动开 **0.83/0.85/0.80/0.67**，手动 **0.08/0.18/0.17/0.16** | 底部四格底座蓝色占比 |
| **图标**（弱） | 同一场战斗在 **0.77~0.81 之间抖**，阈值恰好 **0.80** | 共享模板 `story/auto_off.png` |

图标之所以抖：`story/auto_off.png` 是**亮灰底**裁的，叠在月塔的**深色书架背景**上，
`TM_CCOEFF_NORMED` 去均值后被背景吃掉相关系数。
**同一帧换用 `templates/auto_off.png` 是 0.9114，但那张模板负样本能到 1.0000（废的），
多尺度扫描峰值锁死在 scale=1.0 ⇒ 尺寸没错，是背景问题**。

于是 13:59:29 那一击**无中生有**：布局明说自动开着，图标擦着阈值过了 **0.0055** 就去点开关
⇒ 点了个不该点的，还把坐标弄丢了。

### ⭐ 为什么远征/竞技场没事、只有月塔炸

**同一个 bug 抄了三遍，只有月塔那份的背景让图标分数掉进死区。**
远征/竞技场的战斗背景是亮灰（主线口径），图标稳定过阈 ⇒ 即使布局判错也**有坐标可点**，
能自愈；月塔深色背景 ⇒ 图标差 0.03 没过 ⇒ 坐标是 `None` ⇒ 撞上下一环。

### 第二环：`auto_point is None` **一帧就判死**

```python
if observation.auto_point is None:
    self._fail("auto_point_missing", "手动战斗状态下缺少自动开关坐标", screen)
```

判据各自都会抖，单帧结论本来就不可信 —— 拿它当死刑判决，整条路线当场放弃本层回首页。

### 修法（两处，互补）

**A. 收口成一份实现**（治根）—— 新增 `battle_controls.resolve_auto_state()`：

```python
def resolve_auto_state(controls, auto_icon_hit):
    if controls is BattleControls.TRANSITION and auto_icon_hit:
        return BattleControls.MANUAL_CONTROLS
    return controls
```

**图标只在布局看不出长相（`TRANSITION`）时才作数**；布局已给结论时图标不改判。
`TRANSITION` 兜底**必须保留** —— 否则那一帧停在「未知」，而「未知」按安全设计不许点自动，
战斗只能干等到超时。三条路线**全部改调这个共享函数**。

**B. 「缺坐标」从致命错改成有界等待**（兜底）—— 新增
`BattleConfig.auto_point_grace_seconds = 12.0`：拿不到坐标就等判据抖回来
（下一帧布局认回 auto、或图标过阈给出坐标），等满 12 秒才收手。

### ⚠️ 修 A 时我自己踩的坑：`continue` = 忙循环

第一版在有界等待那一支写了 `continue`，而 `self.sleep(self.config.poll_seconds)`
在**循环最末尾** ⇒ 那一支跳过 sleep，变成**每秒成百上千次截图**的忙循环 ——
真机上比原 bug 更糟（截图是最贵的操作）。
**单测里看不出来**：假 clock 的 `sleep` 是空操作，跑得飞快、测试全绿。

⇒ 改用 `if/else` 包住后续逻辑，并补了一条**源码结构护栏**
`TestNoBusyLoop::test_the_observation_loop_never_continues_past_the_sleep`
（AST 扫 `while True` 循环体内有无 `continue`）。

### 护栏

| 用例 | 判据 |
| --- | --- |
| `ResolveAutoStateTests`（6 条，`test_epic7_battle_controls.py`） | 6 种「布局 × 图标」组合真值表，期望值**独立写死**；含 `transition` 兜底必须仍在 |
| `test_the_live_tower_incident_frame_is_manual` | 真机事故帧（已存夹具 `epic7_tower/battle_manual_auto_icon_dead_zone.png`）必须判 manual |
| `test_manual_without_a_toggle_point_waits_instead_of_failing_at_once` | 缺坐标 3 帧后抖回来 ⇒ **不失败**，且正常点开自动 |
| `test_manual_without_a_toggle_point_still_fails_after_the_grace_window` | **成对**：一直抖不回来 ⇒ 必须收手，不许无限干等 |
| `TestNoBusyLoop::...continues_past_the_sleep` | 主循环不许有 `continue`（AST） |

### 反向验证（`.workbuddy/_rv_autopoint.py`）

| 注入 | 结果 |
| --- | --- |
| ① `resolve_auto_state` 改回「无条件信图标」 | **1 failed** ✅ |
| ② 等待窗口改成 0（退回一帧判死） | **1 failed** ✅ |
| ③ 主循环塞一个 `continue` | **8 failed** ✅ |

### 复现取证用的命令（下次直接抄）

```bash
# 图标在真机帧上的实际分数分布（阈值 0.80 卡在死区）
# 布局判据的底座颜色分离度
# 多尺度扫描确认峰值是否锁在 scale=1.0（排除尺寸问题，锁定背景问题）
```

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

## ⚠️ 事故四：战力差警告（「战斗指南」）盖在准备战斗页上（2026-10-31）

（编号沿用历史，不严格按时间排：一是 10-09 重试自伤、二是 10-08 赛季页、三是 10-09 回退首页、
四是本节 10-31 战斗指南。读的时候按日期看更准。）

### 现象

第 20 层，`业务完成 cycles=2` 之后停在「准备战斗」页，点 `battle-start` **连续 4 次**
都没进战斗（日志 `来源=准备战斗仍在`），最后报
`动作[battle-start]未稳定进入[战斗中]`，退出码 1。收尾也回不了大厅（剧情/弹窗上 ESC 无效）。

### 现场

诊断帧（已存夹具 `battle_guide.png`）上根本不是战斗页，而是 **「战斗指南」弹窗**：

> 登场的敌方战斗力比我方队伍高出许多。要继续进行吗？
> [取消] [确认]

敌方战力 **1,071,000** vs 我方 **799,626** —— 战力差到一定倍数，游戏就弹这个警告，
**点「确认」才开打**。月塔越往上越容易撞上。

### 为什么旧逻辑一定失败

弹窗是**半透明**的，底下那一页原样可见：

| 判据 | 在这一帧上 |
|---|---|
| `team_battle_start`（右下「战斗开始」） | 命中 |
| `prepare_title`（左上「准备战斗」） | 命中 |
| `battle_guide_title`（弹窗标题） | **0.9956** |

⇒ `is_in_state(TEAM)` 成立 ⇒ 状态永远是 TEAM ⇒ 每帧都发 `battle-start`，
而点的是弹窗压住的位置，**一次都不会生效**。这跟「判据不够灵敏」是两回事：
判据全都对，是**少了一个页面**。

### 修法

1. 新增原子 `battle_guide_title`（**复用 `story/battle_guide_title.png`** —— 同一后端、
   同一套渲染；实测本帧 0.9956、其余帧最高 0.38）。为此 `evidence/tower.py` 增加了
   `_TEMPLATE_PATHS` 覆盖表，支持 `../story/...` 这样的跨目录复用。
2. `next_action` 的 `TEAM` 分支**先认弹窗**：命中就发 `confirm-battle-guide`，
   点 `(1122, 794)`（弹窗「确认」，与「确认重置阶段」同一个弹窗布局、同一位置，
   但**常量分开写**：两个业务，将来挪一个不该连带另一个）。
3. `action_source_visible` 对这条动作**按弹窗判**，不按 `TEAM` 判 ——
   弹窗关掉后底下仍是准备战斗页，按 TEAM 判会被当成「没点动」而反复重试。
4. `target_states = (BATTLE, TEAM)`：确认后正常直接进战斗；若游戏退回准备战斗页，
   下一帧重新判，不会空等 60 秒超时。

### 为什么不用主线那套 `find_battle_guide_dont_show`

主线要求**两个锚点**（标题 + 「不再显示」勾选项）。月塔这个弹窗**没有「不再显示」**
（实测该模板在这一帧只有 **0.3791**），套上去整条判据恒假。⇒ 只能自己按「标题」判。

## ⚠️ 接线补全：打不过（FAILED 结算页）= 正常业务退出 + 开局接力（2026-11-01）

### 现象（2026-10-31 第 22 层实跑，`battle_unrecognized` 假故障）

战斗失败落在 **FAILED 结算页**（居中「FAILED」大字 + 左下「大厅」按钮）：
那一帧上 `battle_scene_visible` 为 **False**、三选一锚点不命中 ⇒ 监督的
「打完」两判据全 False ⇒ 干等 45 秒报 `battle_unrecognized`（**退出码 1 假故障**）。
诊断帧已存 `tests/fixtures/epic7_tower/battle_failed.png`
（源：`runtime_diagnostics/epic7_tower/20261031_154715_049198_battle_unrecognized.png`）。

判据本体（`battle_failed`，白掩膜，2026-10-31 就已入库：本帧 **1.0000**、
其余夹具帧最高 0.5556）**一直没人消费** —— 模板在、`FloorTooHard` 异常类也在
（`_POINT_HOME_AFTER_DEFEAT` 都量好了），就是没接线。

### 接线（四处）

1. **`observe_battle`**：FAILED 页并入 `result_visible` ⇒ 监督在失败页**收手**
   （否则永远等不到「打完」）；
2. **`CARD` 分支先判 FAILED**：监督把「打完」的落点一律拨到 `_RESULT_STATE=CARD`，
   而失败的那层**没有三选一页** —— 不先判就会撞 `_required(card_decide)` 报「认不出」。
   命中 ⇒ `_required` 复核 ⇒ 抛 `FloorTooHard`（退出码 2，「月塔这一层打不过」）；
3. **`BATTLE` 分支同样接住**（监督收手瞬间画面已翻页的边缘路径，与征服屏同一对）；
4. **开局接力**（`detect_resume_point` 状态循环**之前**显式判）：人停在 FAILED 屏
   启动月塔 ⇒ 拨到 CARD ⇒ 下一拍立刻正常收工。那一帧上状态循环一个状态都认不出，
   不显式接就会「回大厅 → 重进塔 → 重打同一层 → 再输一遍」。

### 语义（用户 2026-11-01 口径）

- **打不过 ≠ 打满**：打满是完成；打不过是队伍强度不够 —— 但对主循环**都是正常
  业务退出**（退出码 2），不许报成故障。
- **不点「大厅」、不重打**：重打只会再输一遍；收尾由基类 `_close_out` 统一回家。
- 月塔每个小环节（主页/楼层列表/准备战斗/战斗中/三选一两态/结算/征服屏/FAILED 屏）
  现在全部可开局接力；**唯一还缺的是「阶段选择」屏**（每月首次进场弹一次，
  判据素材没拍到，用户拍板「按游戏默认选中的阶段直接确认」—— 等下一次弹这一屏
  时取帧补上）。

### 护栏（`tests/test_epic7_tower.py`，5 条）

| 用例 | 判据 |
| --- | --- |
| `test_the_failed_screen_is_a_normal_business_stop` | CARD 落点 + FAILED 帧 ⇒ `FloorTooHard`，`stop_label=月塔这一层打不过` |
| `test_the_failed_screen_is_reachable_from_the_battle_state_too` | 成对：`BATTLE` 状态也接得住（同征服屏那对） |
| `test_the_failed_screen_wins_the_resume_order` | 接力：FAILED 帧 ⇒ 落点 `战斗失败`/`CARD`/无 entry |
| `test_battle_adapter_hands_control_back_on_the_failed_screen` | 监督在 FAILED 页 `result_visible=True` 收手 |
| `test_the_failed_screen_never_fires_on_a_business_page` | 业务页上 FAILED 判据恒不响（误响 = 打断正常层） |
| `JUDGE_OWNERS["battle_failed"]` | 夹具入库后判据分离度纳入全量扫描（本帧 1.0000 / 其余最高 0.5556） |

## PC 客户端（2026-11-03 放行）

平台差异**只落在图片**：`templates/tower/pc/` 下**9 张**同名覆盖图，阈值与业务代码一行没改。

| 覆盖图 | 为什么需要 | 共享图 → 补图后 |
|---|---|---|
| `home_enter` | 「入场」两字在 PC 上偏软 | 0.8157 → 1.0000 |
| `reset_confirm_title` | 阶段重置确认框标题 | 认不出 → 1.0000 |
| `floor_select_team` | 楼层列表「选择队伍」 | 0.5648 级 → 1.0000 |
| `prepare_title` | 准备战斗标题 | 0.9397 差一点 → 1.0000 |
| `team_battle_start` | 「战斗开始」 | 0.9078 差一点 → 1.0000 |
| `card_hint` | 三选一提示语 | 0.5581 → 1.0000 |
| **`card_decide`** | 「决定装置」按钮 | **0.8668** → **1.0000** |

另有两张是同期一起补的、不在上表：`floor_team_edit`（楼层列表的「编辑队伍」）与
`tower_home_title`（月塔主页标题）。它们没有单独的踩坑记录，补图时按同一套口径裁的。

### ⚠️ 2026-11-03 23:44：`card_decide` 只差 0.0132，把整条每日任务拖死了

**症状**：月塔打完一层 → `battle_unrecognized`（45 秒看门狗）→ 回家流程在这页连按
ESC 无效 → `返回首页失败` → 每日任务「已中止：竞技场 之前无法回到首页」，退出码 1。

**现场长什么样**：三选一装置页（`runtime_diagnostics/epic7_tower/20261103_234451_*.png`），
底部「返回 / 打开装置背包 / 决定装置」，右侧「10/3 下一层」。

**机理**：`observe_battle` 的 `result_visible` 要求「`card_decide` **且** `card_hint`」同时命中
（月塔的「打完」不是结算页 CLEAR，而是这页三选一）。PC 上 `card_hint` 有覆盖图（0.9998），
`card_decide` 没有 ⇒ 判据恒 False ⇒ 监督永远看不到「打完了」。

**为什么一眼看不出是识别问题**：0.8668 离 0.88 只差 0.0132，日志只说「战斗画面持续
无法识别」，看起来像战斗画面本身的问题，实际是**战斗之后那一页**认不出。

**修法**：按同几何从现场帧裁 `tower/pc/card_decide.png`（340×66，中心 (1138,1041)，
正好等于 `_POINT_DECIDE`）。补图后两张现场帧都是 1.0000；同批 20 张 PC 诊断帧里
**最高只有 0.3965**（都是别的页），分离度干净。
按钮「选中 / 未选中」两态不用担心：模拟器实测 1.0000 vs 0.9753，`TM_CCOEFF_NORMED`
把整体亮度差归一化掉了。

**夹具为什么不放 `tests/fixtures/epic7_tower/`**：那是**模拟器基线**目录，
`test_every_fixture_matches_exactly_one_page` 与
`test_every_judge_clears_its_threshold_with_a_wide_margin`（他页 < 0.88 且余量 > 0.30）
会把「同一页的另一个平台渲染」判成噪声，混进去只能靠放宽门槛过测试。
⇒ PC 帧单独放 `tests/fixtures/epic7_tower_pc/`，正反两向断言见 `test_tower_evidence.py`。

**还没被真机走过的**：这一页之后的 `结算页（CLEAR）→ 下一层 → 准备战斗`。
`result_clear` 在 PC 上尚无现场帧可验（两次实跑都死在三选一），下次跑通才能确认。
间接证据偏乐观：主线的同款「CLEAR」大字母在 PC 上**没有覆盖图也能过**（当时 `templates/story/pc/` 只有 `complete` / `friend_request_title` / `stamina_popup` 三张，现行共 **9 张**，清单见 `tests/test_epic7_story_pc.py`），
说明 PC 压得狠的是**中文小字**，大号拉丁字母不受影响。

## UI 尺寸漂移：这一条路线最先踩到（2026-11-04）

**症状**：`动作[select-team]未稳定进入[准备战斗]`。诊断帧看着明明就是准备战斗页。

**机理**：PC 客户端两次启动之间会把同一套 UI 画小一点。实测「战斗开始」按钮
**476×69 → 461×67**（×0.9685）。`TM_CCOEFF_NORMED` 不归一化尺度 ⇒
`team_battle_start` 在 08:06 帧是 1.0000、在 00:05 帧只有 **0.8643**（阈 0.88）。

**为什么补图救不了**：同一颗 `card_hint` 在 23:44 帧要 ×1.00（0.9998）、
在 00:12 帧要 ×0.98（0.9404）—— **没有任何单一尺寸能同时服务两档**
（×0.99 是 0.8576 / 0.7738，两边都不过阈）。

**修法**：`core/matcher.py` 的 `SCALE_FALLBACK_ANCHORS`（模板缩放兜底），
月塔登记了 6 颗：`team_battle_start` / `prepare_title` / `card_hint` / `card_decide` /
`battle_failed` / `conquer_title` / `season_tower_title`（见 §2.4b 的
`docs/PC_TEMPLATE_MIGRATION.md`）。

**已实测的四帧**（`tests/fixtures/epic7_tower_pc/` 里都有）：

| 帧 | 页面 | 关键锚点 | 原样 | 兜底后 |
| --- | --- | --- | --- | --- |
| `prepare_pc_live_20261103`（08:06） | `tower.team` | `team_battle_start` | 0.9601 | —（过阈，不扫） |
| `prepare_pc_live_small_20261104`（00:05） | `tower.team` | `team_battle_start` | 0.9373 | —（过阈，不扫） |
| `card_pc_live_20261103`（23:44） | `tower.card` | `card_hint` | 0.9998 | —（过阈，不扫） |
| `card_pc_live_small_20261104`（00:12） | `tower.card` | `card_hint` | **0.6448** | ×0.98 **0.9404** |

⚠️ 同页 `prepare_title` / `team_battle_start` 现在两档都能过阈值，但余量只有 0.06~0.08。
只要客户端再漂 1%，靠的就是兜底而不是余量 —— 别因为「现在过了」把它们从名单里删掉。
