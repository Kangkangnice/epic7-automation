# 主线视觉维护

主线视觉证据入口：`games/epic7/evidence/story.py`。

模板位于 `games/epic7/templates/story/`。改版时按失败诊断中的证据键名替换模板；位置变化改 `REGIONS`，分数变化改 `THRESHOLDS`，可选页面或冲突证据改 `PageEvidence`。

跳过、体力、快速战斗、结算和下一关的业务顺序仍在 `games/epic7/story.py`，视觉迁移不得改变这些状态转移。

失败时原 `*.png` 旁的同名目录包含 `screen.png` 和 `evidence.json`。按 `config`、证据键、`region`、`score` 与 `threshold` 定位问题；低于阈值仍有数值得分，不要把“未命中”直接解释成模板缺失。当前命令行检查器未注册主线，以该证据包和主线 fixture 回归为准。

## 「重复打同一关」：`retry_stage`（2026-10-18 立）

### 这是什么页

打完一关、结算确认之后，游戏有时给的是：

```
无法前往下一个关卡，请选择下方按钮。
[离开]  [大厅]                     [S 20/109]  [重新进行]
```

**左下角是「离开 / 大厅」，右下角是「重新进行」**。用户想「同一关连打 10 次」时，
每一次都会回到这一页 —— 这是常态落点，不是异常分支。

### 以前为什么会整条路线失败

这一页**一个锚点都没有**：`complete` 0.2235 / `next_stage` 0.1411 / `results_confirm` 0.3701，
全部低于阈值 ⇒ `next_action` 抛 `UnrecognizedScreen` ⇒ 静默干等 **45 秒** ⇒ 退出码 1。
10-18 19:50（第 3 章·白色悬崖森林）与 10-14 18:42（另一关）是**两次同形**失败。

> 注意：这不是「偶尔认不出」，是**从未认识过这一页**。凡是「重复打」都会撞上。

### 判据

| 项 | 值 |
| --- | --- |
| 模板 | `templates/story/retry_stage.png`（68×132，只框「重新进行」四个字） |
| 区域 | `RETRY_STAGE_REGION = (1680, 1000, 200, 90)` —— **只框右下角那颗** |
| 阈值 | 0.80（默认档） |
| 实测正例 | 10-18 现场 **1.0000**、10-14 另一关 **0.9870** |
| 实测反例 | 主线其余夹具最像的 `battle_guide_warning` **0.5173**；`complete`/`next_stage`/`results`/`team`/`story` 全部未命中 |

⇒ 门槛 0.80 坐在 `0.5173 ~ 0.9870` 的空档里，两边各留 ≥0.18。用例
`test_the_replay_threshold_sits_in_an_empty_gap` 钉住「两边各 ≥0.10」。

**模板里绝不能带体力数字**（`20/109` 每局都变）。只框那四个字。

### 优先级（用户 2026-10-18 口径）

> 两个都遇到时先走「进行下一个任务」，没有它才点「重新进行」。

代码里就是**位置**：`retry_stage` 的判定放在 `next_action` 的**最后**，
`complete` / `next_stage` / `prepare_battle` 全在它上面。用例
`test_going_forward_always_wins_over_replaying` 用桩把前进判据同时点亮，
断言赢的是 `complete`。

⚠️ 这两颗按钮**在同一个位置上**（都在右下角），所以**造不出「同屏都有」的真实帧** ——
别为了「更真实」去拼一张合成图，那只会验出拼接 bug。

### 轮次记账

- 看到这一页 = 一局刚打完 ⇒ `completed_cycles += 1`。
- **同一屏只记一次**：点歪重试（尝试 2/4、3/4）会再判一次同一屏，
  涨了就会把「打 10 次」变成「打 5 次就收工」（`test_a_failed_retry_click_does_not_count_the_cycle_twice`）。
- 达到 `max_cycles` 时**不点**这一下（`_check_cycle_completed` 在点击之前），
  与狗粮「到目标轮数就停在这一页」一致（`test_the_replay_screen_stops_without_clicking_when_the_target_is_reached`）。

### 点完之后去哪（不是猜的）

狗粮路线 2026-09-13 的实跑日志：点 `replay`（1762,1050）后 **4 秒**落到「准备战斗」页，
再选队、开战。所以主线的契约声明为
`target_pages=("关卡入口", "剧情关卡入口", "助手选择", "队伍准备")`、`target_states=(STAGE, TEAM)`，
落地后由现有的 `prepare_battle → select_team → start_mission` 接回去。

2026-10-18 21:19 的实测链路（`runtime_logs/_verify_story_retry.py` 打出来的）：

```
结算确认 (1745,1040) → 无法前往下一关 → 重新进行 (1770,1044)
                     → 选择辅助英雄（select_team 1.0000，点 1675,1045）
                     → 队伍准备（start_mission，点 1675,1045）
                     → 战斗
```

### ⚠️⚠️ 结算确认的**第四种**落点：漏声明会把动作整个吞掉

2026-10-18 21:14 实跑报的是「转场超时 动作=results_confirm 期望页面=通关提示/额外奖励/下一关入口
当前已确认页面=无法前往下一关」，**看起来像「点了没反应」，其实不是**。

主循环的转场逻辑（`runner_base` 里那段 `elif`）：

```python
action = (last_transition_action
          if confirmed_page == last_transition_action.source_page ...
          else None)          # ← 新页面既不在目标里、又不等于来源页 ⇒ 动作被丢掉
```

于是状态机明明已经算出 `retry_stage`，主循环却把它**换成 None**，什么都不点，
干等 45 秒后按「转场超时」收尾。**根因是契约漏了一个落点，不是判据的问题。**

⇒ `results_confirm` 的 `target_pages` 必须包含 `"无法前往下一关"`。
改完之后同一条链路才会出现 `完成=results_confirm 目标页面=无法前往下一关`，
那一下 `retry_stage` 才会真的点出去。

**怎么快速分诊这一类**：日志里看到 `转场超时` + `当前已确认页面=X`，
先去查「上一个动作的 `target_pages` 里有没有 X」。有 ⇒ 才是真没转场；
没有 ⇒ 是契约漏了，补声明就完事，别去动判据和阈值。

### 别再做回去

- **不要**把 `retry_stage` 放到前进判据前面 —— 有路可走时先走路。
- **不要**把区域放大到包含「离开 / 大厅」：语义完全相反，点错就退出关卡。
- **不要**删掉 10-14 那张夹具。只剩一张就是「记住了一张图」，泛化能力没有证据。


## PC 客户端（2026-11-01 移植，第一轮验收通过）

**一句话结论：主线不需要任何 PC 专属图，业务代码零改动。** 只动了窗口层的一个常量
（`core/pc_window.py` 的抓帧重试预算）。

### 为什么不用补图（实测，别再重复调研）

主线的关键判据全是**白掩膜找形状**（`find_prepare_battle_button` / `find_watch_story_button` /
`find_story_skip_button` / `find_battle_guide_dont_show`），掩膜把底图抹平，
所以「客户端换了渲染方式」对分数几乎没影响。PC 现场帧实测：

| 判据 | PC 分数 | 阈值 | 备注 |
|---|---|---|---|
| `prepare_battle`（关卡入口） | **1.0000** | 0.90 | `prepare_battle_updated` 0.9997 也过 |
| `skip_confirm`（跳过确认） | **0.9196** | 0.80 | 剧情战斗里多次出现 |
| `skip`（跳过） | **0.7075** | 0.65 | 同上 |
| `auto_off`（自动关闭图标） | 0.73（自动开时）/ 0.82~0.96（自动关时） | 0.80 | **语义正确**：只在自动真的关着时才过阈 |

`auto_off` 这两个档位不是噪声，是它本来就该有的两种状态；认不出时状态机会退回
「右下角按钮布局」（`battle_controls.py` 的霍夫圆，几何判据，两边逐像素一致），
所以不会卡住。**不要为了让它更"稳"去补 PC 图或调阈值** —— 那会把「手动/自动」判反。

### 唯一的真问题：抓帧重试太短（已修）

第一轮实跑（`20:40`）点完「进入主线」后，连续 3 次抓不到画面 ⇒
`RuntimeError: PC 后台截图失败` ⇒ 整轮中止。

日志：`20:40:20`/`20:40:21` 各失败一次，第三次失败即抛；紧接着的诊断抓帧第 2 次就成功了。
⇒ 失败窗口约 **0.6~0.8 秒**，恰好比「3 次 × 0.2 秒 = 0.4 秒」长一点。
主线「大厅 → 主线入口」这种**带加载的转场**比竞技场那些页面切换更吃时间。

修法：`CAPTURE_ATTEMPTS 3 → 6`、`CAPTURE_RETRY_DELAY 0.2 → 0.3`（上限 1.8 秒）。
仍是有界重试，只在真抓不到时才等；`tests/test_pc_window.py` 里那条「试满就报错」
的断言改成引用常量（原来写死"3 次"）。

### 跑通的链路（113 秒一轮）

```
大厅 →(进入主线)→ 主线入口 →(prepare_battle)→ 助手选择 →(select_team)→ 队伍准备
     →(start_mission)→ 战前剧情 skip ⇄ skip_confirm → 战斗（自动战斗）
     →(clear)→ 结算确认 →(results_confirm)→ 通关提示 →(complete)→ 关卡入口
     →(导航)→ 快捷菜单 → 酒馆 → 大厅
```

剧情战斗里 `skip ⇄ skip_confirm` 会来回几次（每段过场各一次），这是**真的**：
现场帧上 `skip_confirm` 0.9196、`skip` 0.7075，两次都真有那个控件，不是误判。

### 接力（开局发现已经在战斗里）

`21:08` 那轮开局时游戏停在战斗中，接力探针判成「战斗中 / wait_battle」，
直接交由战斗监督等结算，没有乱按 Back —— 这条路径也走通了。

### 回归靠什么

- `tests/test_epic7_story_pc.py`：PC 关卡入口帧上「准备战斗」必须过阈、
  后续页面锚点一律不得命中、且 `templates/story/pc/` **不存在**（有人补图就红）。
- 夹具：`tests/fixtures/epic7_story/stage_pc_live_20261101.png`。
- **还没做的**：第二轮连续实跑。第 5 步验收由用户在界面自测补上
  （`catalog.PC_READY_ROUTES` 已含 `story`）。别因为"跑一遍没出事"就当验收齐了。

### 「行动力不足」弹窗：PC 上认出标题、却够不到购买按钮（2026-11-01 21:23 实跑）

**现象**：体力见底时点「战斗开始」，弹出「行动力不足」。路线没把它当弹窗处理，
回头继续点「战斗开始」——连点 4 次、心跳里"距上次业务进展"一路涨到 29 秒，
最后用户手动停。

**量出来的分数**（现场帧 `20261101_212424_885564_manual_stop.png`）：

| 判据 | 修复前 | 阈值 | 原因 |
|---|---|---|---|
| `stamina_popup`（标题 行动力不足） | 0.7623 | 0.80 | PC 把同一句标题渲染得略大（白字 bbox PC 229×45 / 模板 221×43） |
| `stamina_material`（生命之叶） | 0.9997 | 0.80 | 本来就认得出 |
| `stamina_confirm`（购买） | 0.4886 | 0.80 | **购买按钮根本没进搜索框**，详见下 |

**两处根因，两种修法（都在 PC 迁移的设计内）**：

1. **标题**：补 `templates/story/pc/stamina_popup.png`（310×75，从 PC 真帧裁，
   白字落点与共享模板对齐）⇒ PC 1.0000，代码零改动。
2. **购买按钮**：这版弹窗底部改成**三颗按钮**（取消 / 购买 / 礼包），购买被挤到
   `x=807~1105`；旧搜索框 `(850,750,650,250)` 从 850 起，325 宽的模板在框内
   摆不到按钮真正的落点上，只能退到礼包那边（0.4886）。
   ⇒ `STAMINA_REGIONS["stamina_confirm"]` 左扩到 `(760,750,740,250)`
   （`stamina.py` 与 `evidence/story.py` 两处必须一起改），修后 **0.9148**。

**这不是 PC 独有的**：老夹具 `stamina_popup_live_20260809` 里只有**两颗**按钮
（购买在 x=972），说明是**游戏 UI 改版**，模拟器同样会遇到 —— 只是体力耗尽不常发生，
一直没暴露。所以第 2 条修的是共享几何，不是“给 PC 开小灶”。

**审计**：全库 312 张夹具，新搜索框相对旧框 **0 新增命中、0 漏掉**（过阈集合完全一致）。

**回归**：`tests/test_epic7_story_pc.py`
（`test_pc_stamina_popup_is_fully_actionable` 正例、
`test_pc_story_page_does_not_trigger_the_stamina_popup` 反例、
`test_pc_overrides_are_only_what_the_pc_really_needs` 防乱加覆盖图）；
夹具 `tests/fixtures/epic7_story/stamina_popup_pc_live_20261101.png`。

### 战后「给予协助的朋友」弹窗：标题差一点，整个弹窗就关不掉（2026-11-01 21:21）

⚠️ **先纠正一个容易看错的事实**：21:21 那次「转场超时」的现场帧，**不是单纯的结算页**，
而是「结算页 + 给予协助的朋友弹窗」两层叠着。光看日志「当前已确认页面=结算确认」
会以为只是落点没写，其实弹窗才是主角 —— 它一直压在最上面，连收尾的 ESC 都被它吃掉。

**判据是"两颗都要中"**：`find_friend_request_cancel` 要求标题与「取消」同时命中（阈 0.82）。
PC 现场帧上：**标题 0.6084 不过**、取消 0.9014 过 ⇒ 整体返回 None ⇒ 守卫不认。

**标题为什么低**：PC 把同一句中文标题渲染得略大（白字 PC 328×45 / 模板 314×44），
和「行动力不足」那条是同一类（阈值 0.82 对这种 4% 的尺寸差没有余量）。

**修法**：`templates/story/pc/friend_request_title.png`（420×80，按模板里白字的落点对齐裁）
⇒ PC 上 0.9014 命中，守卫点「取消」。

**为什么这个坑很隐蔽**：弹窗盖在结算页上时，背景那颗「确认」按钮仍然露着并命中
（`results_confirm` 0.8600），所以页面判定看起来完全正常、`observed=True`；
真点下去却打在弹窗的死区上 —— 表现是「认得出这一页、就是点不动」。
这类"页面认得对、但被模态弹窗压着"只能靠守卫先把弹窗吃掉，
**别去调页面判据**。

**回归**：`tests/test_epic7_story_pc.py::test_pc_friend_request_popup_is_recognized`
（同时钉住「模拟器口径仍解析共享模板」），夹具
`tests/fixtures/epic7_story/friend_request_pc_live_20261101.png`。

### 「跳过剧情」的转场判定不再穷举落点（2026-11-01 22:02，同一类第二次）

**一夜两次，同一个动作、不同的落点**：

| 时间 | 点完「跳过确认」落在 | 落点名单里有吗 | 后果 |
|---|---|---|---|
| 21:21 | 结算确认 | ❌ | 干等 45 秒 → 回首页 ESC 无效 → 退出码 1 |
| 22:02 | 通关结算 | ❌ | 同上 |

根因不是判据，是 `target_pages` 这份**穷举名单**：跳完落到哪一页取决于
「这一下战斗打没打完」——打完了给战果（通关结算 / 结算确认）、没打完回战斗中、
纯剧情回剧情播放。**穷举这条路已经被证明走不完**：加一格只能挡住今天这一格。

⇒ 改成结构性判据（`StoryRunner._transition_completed` 覆写，只作用于
`skip` / `skip_confirm` 两个动作）：

```
页面离开了来源页（不再是「跳过确认」） 且 状态机对当前页算得出下一步  ⇒ 算转场完成
```

仍然 fail-closed：**还停在「跳过确认」页一律不算完成**（点击没生效时不许蒙混）。
其它动作（结算确认、通关提示……）保持原判据——落点必须在名单里，这条有测试钉住。

名单本身保留（日志里“目标页面=…”仍然可读），但它不再是跳过类动作的唯一凭据。

**回归**：`tests/test_epic7_story.py::StorySkipTransitionTests`
（任意落点算完成 / 停在原地不算 / 非跳过类动作仍要名单）。

### 新支线解锁通知（2026-11-01 22:05，全局弹窗第 14 个）

**现象**：战斗打完、结算页正要确认时，「支线故事通知」盖上来；路线在 `等待结算`
状态 45 秒无进展，最后回首页也失败（诊断帧 `20261101_220554_..._timeout_wait_results.png`）。

**判据**：弹窗的**正文与插画每次都不同**（"支线故事「被选中的女巫」已解锁"），
只有两处固定 —— 标题「支线故事通知」和底部「点击关闭」。所以：

- `templates/global/side_story_notice_title.png`（302×68）
- `templates/global/side_story_notice_close.png`（141×55）
- `find_side_story_notice_close`：**两锚点同时命中才算**（「点击关闭」这四个字在
  骑士团签到等弹窗上也出现过，单锚会串味），阈 0.85，点关闭标签中心 (960,885)。

**接线**：守卫新增 `side_story_notice_templates` 参数 + `_find_popup` 分支；
`main.py` 装配处传 `load_side_story_notice_templates(template_root / "global")`。

**实测**：弹窗帧 1.0000 命中、守卫分派 `side_story_notice / dismiss-side-story-notice`；
关卡入口与「结算页+好友弹窗」两张真机帧上均不命中（反例）。

**回归**：`tests/test_global_popups.py` 三条（正例 / 两锚点缺一不认 / 别的页面不认）+
夹具 `tests/fixtures/epic7_global/side_story_notice_pc_live_20261101.png`。

### 「获得奖励」通知（2026-11-01 22:27，全局弹窗第 15 个）

**现象**：点完「通关提示」回到关卡入口，弹出「获得奖励 / 获得星星奖励已正常发放。」
+「点击关闭」；路线在 `等待通关` 45 秒无进展（诊断帧 `20261101_222757...`）。

**同帧分数**：路线自己的 `bonus_reward` **0.7724**（阈 0.80）—— 差 0.028，
`next_stage` 0.7721 也差一点 ⇒ 状态机判「等待通关 未识别」，
底下的 `prepare_battle_updated` 倒是 0.9993（说明关卡入口本身认得出来，是被这层盖住了）。

**判据**：正文与奖励图标随奖励类型变化 ⇒ 只锚标题「获得奖励」+ 底部「点击关闭」，
两锚点同时命中才算（阈 0.85），点 (960,843)。

- 模板：`templates/global/reward_notice_title.png`（213×69）、`reward_notice_close.png`（142×55）
- 守卫新增 `reward_notice_templates` 参数 + `_find_popup` 分支（第 15 类）
- `main.py` 装配 `load_reward_notice_templates(template_root / "global")`

**实测**：弹窗帧 1.0000、守卫分派 `reward_notice / dismiss-reward-notice`；
关卡入口帧与支线通知帧上均不命中；与「支线故事通知」互不串味（标题不同）。

**回归**：`tests/test_global_popups.py` 三条（正例 / 两锚点缺一不认 / 两种通知互不串味）+
夹具 `tests/fixtures/epic7_global/reward_notice_pc_live_20261101.png`。

### 战果链上的三下点击都可能接「战后过场」（2026-11-01 22:55）

**现象**：点完「奖励结算」后落到「剧情播放」（剧情关卡会放战后过场，不是直接进战果），
`reward` 的落点名单只有「通关结算 / 结算确认」⇒ 主循环判「没点成功」→ 丢掉动作 →
45 秒 → `timeout_transition_reward`。

**同类的落点缺口，今晚一共三次**：

| 动作 | 实际落点 | 原名单 |
|---|---|---|
| `skip_confirm` | 结算确认（21:21） | ❌ |
| `skip_confirm` | 通关结算（22:02） | ❌ |
| `reward` | 剧情播放（22:55） | ❌ |

**修法（最小声明式，无图片、无逻辑改动）**：战果链上的三下点击
（`reward` / `clear` / `results_confirm`）的落点都补「剧情播放」，
`target_states` 相应补 `ACTIVE`（剧情播放↔ACTIVE，见 `_STORY_RESUME_ORDER`）。

**回归**：`tests/test_epic7_story.py::test_results_actions_allow_a_post_battle_cutscene`
（三颗动作都必须允许「剧情播放」）。
