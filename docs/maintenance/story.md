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

