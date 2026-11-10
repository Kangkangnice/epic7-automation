# 架构说明

## 目录职责

```text
auto_game_unified/
├─ core/
│  ├─ matcher.py            # 限定区域、缩放感知的 OpenCV 模板匹配
│  ├─ runtime.py            # 截图、点击、中文日志、当前帧和失败诊断
│  ├─ supervisor.py         # 两帧稳定、画面变化、状态轮询和超时监督
│  ├─ battle_supervisor.py  # 战斗监控：心跳、画面变化进展、结算移交
│  ├─ recovery.py           # 战斗锁：已承诺战斗期间禁止打断（只有 lock/unlock）
│  ├─ hotkey.py             # 全局停止键（P）—— 自动化与连点器共用同一个键
│  ├─ autoclicker.py        # 固定点连点器（「实用工具」页；与路线无关，不认画面）
│  ├─ qqbot.py             # 官方 QQ 机器人开放平台 C2C 私聊推送
│  ├─ window.py             # 模拟器窗口捕获与局部坐标点击（雷电 adb 通道）
│  ├─ pc_window.py          # PC 客户端窗口 I/O（BitBlt 后台抓屏、SendInput 点击、ESC、滑动、滚轮）
│  ├─ evidence_diagnostics.py # 失败诊断落盘（screen/source/target/evidence.json）
│  ├─ elevation.py          # UIPI 提权判断（对方窗口权限更高时点击会被静默拦掉）
│  ├─ portrait.py           # 竖屏通道（H5 网页把模拟器切成竖屏时的取图与坐标）
│  └─ data_paths.py         # 运行产物（日志/诊断/导出）目录
├─ games/epic7/
│  ├─ navigation.py         # 从支持页面受控返回大厅并进入目标模式（导航链的**执行器**）
│  ├─ navigation_plan.py    # 导航链的声明式数据（纯 dataclass，不含任何路线知识）
│  ├─ global_popups.py      # 全局弹窗守卫（现行 20+ 类，清单见文件里的 _find_popup）
│  ├─ unknown_screen.py     # 未知画面唤醒（萤火待机等）与安全停止
│  ├─ battle_controls.py    # 战斗内 Auto/加速按钮识别
│  ├─ stamina.py            # 体力弹窗共享：区域、模板、补体力决策
│  ├─ runner_base.py        # 同构模式公共主循环（ModeRunnerBase；点一次→每帧重问状态机）
│  ├─ transactional_runner_base.py  # 事务型公共主循环（目标页连续两帧才提交状态）
│  ├─ template_paths.py     # 平台差异的**唯一入口**：共享图 / pc 同名图覆盖
│  ├─ **其余「一条路线一个模块」**：arena / story / expedition / tower / fodder /
│  │   hero_synthesis / side_story / activity_story / knights_donation / sanctuary /
│  │   labyrinth_stone / moonlight_theater / survivor / community / shop_refresh /
│  │   world_boss / achievement（现行名单以 modes.MODE_SPECS 为准）
│  ├─ daily_tasks.py        # 每日连打的**编排**（不是一条路线，不占 --mode）
│  ├─ modes.py              # 模式注册、默认状态、构建器、准入表态
│  ├─ evidence/             # 各路线视觉证据：模板、区域、阈值和页面组合
│  └─ templates/            # 线上识别使用的局部模板（pc/ 子目录是平台覆盖）
├─ desktop/                 # 与界面无关的业务层：控制器、路线文案、会话、worker、预检
├─ desktop_qt/              # 桌面界面（Qt / Fluent，**唯一交互入口**）
├─ tools/                   # 现状页生成、门禁检查、采图、打包、文档体检等开发工具
├─ tests/
│  ├─ fixtures/             # 当前客户端完整页面回归截图
│  └─ test_*.py             # 页面、动作、循环、超时和反例测试
└─ main.py                  # 通用 CLI、Runtime 和导航器组装
```

## 分层边界

一次操作的数据流为：

```text
游戏窗口截图
  → 路线视觉证据清单（模板、区域、阈值、页面组合）
  → 全局导航或模式状态机
  → 在限定区域匹配当前状态允许的锚点
  → 返回具名动作和窗口局部坐标
  → Runtime 记录日志并点击一次
  → 重新截图并验证目标页面
```

- `Epic7Window` 只负责找到、前置、截图和点击游戏窗口。
- `Runtime` 只负责执行能力、日志、停止键与诊断文件。
- 状态机只根据当前截图决定唯一允许动作，不直接点击。
- `games/epic7/evidence/` 是 UI 易变配置的唯一维护入口；状态机不再重复保存已迁移路线的模板路径、区域和阈值。
- Runner 负责两帧稳定、转场验证、重试、心跳、恢复和超时。
- `Epic7Navigator` 只负责大厅恢复和进入模式，不处理模式内部业务。

这些职责不能混在一起。点击成功不等于页面已经变化；内部状态只能在目标页面得到确认后继续。

## 坐标和窗口

状态机看到的是《第七史诗》窗口的局部 RGB 图像，不是整个桌面。模板和搜索区域以 `1982 x 1132` 为参考尺寸。

- 窗口在桌面移动时，局部坐标不变；点击前再加上最新窗口偏移。
- 窗口等比例缩放时，模板和区域同步缩放。
- 横纵缩放比例不一致时安全停止，防止坐标漂移。
- Windows DPI 感知在导入截图和鼠标库前启用，避免逻辑坐标与物理像素混用。
- Codex、桌面或其他窗口不属于游戏窗口截图，不能成为业务模板来源。

## 观测和动作确认

普通动作需要同一页面和动作连续两帧一致。执行一次点击后，Runner 继续截图，直到目标状态满足稳定条件才算转场完成。

- 动作重试额度由 Runner 明确控制并写入日志；`ModeRunnerBase` 当前上限为四次，独立 Runner 需单独审计。
- 上限用尽后，给路线**一次**原地「换个办法」的机会（`_self_heal_used`）：换成了别的动作就照常点，
  换回来还是同一个动作就直接安全停止。⚠️ 这**不是**点击额度的重置 —— 同一个动作一共只点四次。
- ⚠️ 2026-09-26 用户拍板：**回家就是结束**，程序不会再回大厅重新导航接着跑。
  「首次耗尽 / 状态超时 ⇒ `recovery()`（回大厅重开）⇒ 接着跑」整套已删除，改为直接安全停止
  （回家由 `main` 收尾）。**连带清掉的死零件**：`runner_base` 的 `recovery` 回调与
  `_apply_recovery_state` 钩子（含 6 条路线的覆写）、`main` 的 `recover_to_mode` /
  `report_blocked_recovery` / `runner_options["recovery"]`、`core/recovery.py` 的
  `recover()` / `RecoveryBlocked` / `on_blocked`、`ArenaStateMachine.reset_after_recovery`。
  剩下的那个闸门**只有**「已承诺战斗期间禁止打断」一个职责（见 `core/recovery.py`）。
- 结论门槛：收工 / 认不出画面这类**终止性结论**同样要连续两帧一致才采信，
  不能一帧就宣布整条路线结束（规矩见 [页面转场契约](TRANSITION_CONTRACTS.md)「结论门槛（全局强制）」）。
- 未知页面不能盲点业务按钮。

英雄合成动作已经携带来源页面、允许目标页面、原因和转场类型；**2026-11-09 审计后只剩狗粮**没补齐这些字段（`FodderAction` 仍只有名字与坐标，登记在 `modes.TRANSITION_EXEMPT` 的已知欠债里），其余路线要么已填、要么走各自的事务型基类。后续统一时以 [页面转场契约](TRANSITION_CONTRACTS.md) 为准，审计状态见 [自动化稳健性待办](TODO.md)，不能把当前部分实现写成所有路线已经完整具备。

加载和战斗使用画面变化作为进展信号。战斗每 30 秒输出心跳；HUD 被技能动画临时遮挡时，只要画面仍是有效游戏帧且战斗区域持续变化，就继续监控。

## 循环完成定义

点击最后一个确认按钮不代表完成。只有重新识别到稳定入口时才增加 `completed_cycles`：

- 竞技场：回到对手列表。
- 主线：处理完剧情、奖励、好友申请和结算，重新出现下一关入口。
- 远征：回到远征主页并看到“我的通缉传单”。动态传单角标不参与识别。
- 狗粮：结算确认后重新出现“重新进行”；达到目标轮数时不点击该按钮。
- 英雄合成：模拟器翻卡通过右侧列表的“稳定→定向运动→重新稳定”动态证据确认，因此同名同外观副本也能安全推进；SSS、普通与未知使用三态分类，未知目标不点击。发现 SSS 材料后，传送事务会一直保留当前目标，只有奖励层联合证据稳定出现且返回英雄列表后才清理，防止漏传、误传或重复传送。

这样可以避免点击未生效、加载卡住或额外弹窗出现时产生虚假计数。

## 同构模式公共骨架

`runner_base.py` 的 `ModeRunnerBase` 统一实现**同构线**的公共主循环。
2026-11-09 核实时它覆盖 12 条：主线 `story` 与它的两个子类（支线故事 / 活动剧情）、狗粮、
英雄合成、骑士团捐赠、圣域收菜、迷宫强化石、月光剧场、世界首领战、成就领取、社区签到。

- 空跑短路、两帧稳定确认、同动作 45 秒转场等待、4 次点击上限。
- 结论门槛（收工 / 认不出画面也要连续两帧一致）。
- 未知画面唤醒、结算等待与绝对超时熔断；动作循环检测与状态超时**直接安全停止**
  （不再「回大厅重新导航一次」）。

各模式只通过钩子注入差异：超时表、战斗移交方式（先点击再移交 / 战斗监督代点 / 停留战斗态直接移交）、战斗监控实现（`BattleSupervisor` 或自带循环）。

**另一族**是事务型的 `TransactionalRunnerBase`：竞技场、远征、月塔。它们的出口验收比
`ModeRunnerBase` 更严 —— 目标页连续两帧才提交，来源/目标契约缺任一直接 raise。
⚠️ 竞技场虽然继承它，但**保留自己的 `run()`**（循环策略与远征有 10 处实质差异），
所以它不走基类里那道「画面冻住就不补点」的闸门。

**完全自带主循环**的是两条：刷书签 `ShopRefreshRunner` 与活动小游戏 `SurvivorRunner`。
它们各自用 `_wait_stable` / `_observe_stable(page, timeout)` 验收，不经过任何基类。

## 全局弹窗守卫

`global_popups.py` 的 `Epic7GlobalPopupGuard` 在各模式轮询间隙统一处理全局弹窗，一次安装全模式共享。
**它早已不是四种弹窗的清单**：2026-11-09 核实时注册了 20 多类（断网、亲密度、友情点数、好友申请是
最早的四类，之后陆续加了支线故事通知、获得奖励、领取支援物品、账号 Rank、骑士团签到 / 支援 /
周奖励 / 成长 Rank、首领战支援奖励、段位升级奖励、战斗记录、新的每周排名、每周排名选择奖励、
宠物礼物、变更日期、登录奖励、网页网络错误、「无法控制」剧情、轻触解锁、跳过教学……）。
**别在这里手抄清单**——现行类别以 `_find_popup()` 里的分支为准，另有一组 PC 专属弹窗由
`install_pc_only_popups()` 挂上去。

下表只列最早那四类，**不是全集**：

| 弹窗 | 识别 | 处理 |
| --- | --- | --- |
| 断网重连 | 重试标题 + 重试按钮 | 点击重试，2 次未消失安全停止 |
| 亲密度提升 | 等级提升标题 + 关闭按钮 | 点击关闭，2 次未消失安全停止 |
| 友情点数 | 标题 + 关闭按钮 | 点击关闭，2 次未消失安全停止 |
| 好友申请 | 标题 + 取消按钮 | 点击取消，2 次未消失安全停止 |

新增全局弹窗时优先扩展守卫处理链，不在单个模式内加本地分支。
⚠️ 有一类**不能**交给守卫抢关：与路线自己同 UI 的通知层（如英雄合成的「传送奖励」、
骑士团捐赠的「支援成功奖励」），守卫抢先点掉会让路线的 `target_pages` 永远不成立 ——
这类用 `ModeSpec.reward_notice_guard` 按路线关掉。
体力不足弹窗是业务弹窗而非全局弹窗，由 `stamina.py` 统一决策（生命之叶补充 → 确认 → 耗尽安全停止）。

## 日志规范

所有日志使用中文键值对格式，从日志可直接判断当前模式和进程阶段：

```text
模式=狗粮 轮次=1/2 页面=结算确认 动作=replay_confirm 尝试=1/2
模式=主线 停止=生命之叶耗尽 详情=生命之叶已耗尽或生命之叶选项不可用
```

- 固定键：`模式`、`轮次`、`页面`、`动作`、`阶段`、`状态`、`停止`、`结论`。
- 页面名使用中文画面描述（如“队伍选择”、“结算确认”），不用 Enum 值。
- 停止原因必须写明业务含义（如“生命之叶耗尽”、“页面识别超时”）。
- 新增日志必须遵循同一格式，保证 grep 单个键（如 `模式=`）即可过滤整条链路。

改变页面或业务状态的日志还应区分“动作候选、执行点击、等待确认、转场确认、业务成功”。目标证据出现前不得输出业务成功；具体字段见 [页面转场契约](TRANSITION_CONTRACTS.md)。

## 远征特殊流程

远征固定使用三阶段：

```text
远征主页 → 我的通缉传单 → 卡片内远征队出发
→ 选择三阶段 → 确认 → 准备战斗 → 队伍战斗开始
→ 战斗 → 结果确认
```

首领存活时：

```text
公开招募 → 弹窗确认 → 萤火待机时唤醒 UI
→ 返回远征队列表 → 再返回远征主页 → 完成一轮
```

萤火待机只能点击中央安全区域，并要求真正 UI 出现；仍停留萤火页不算唤醒成功。卡片搜索区域排除右下角“所有远征队出发”，避免危险误点。

## 干跑状态诊断

进程不会持久化内部状态。`--start-state` 只用于干跑诊断，`modes.py` 会验证状态属于对应模式。实跑传入该参数会在截图和点击前拒绝。

正常实跑在开局会先做一次接力探测（见下节「开局接力」）；没命中接力点才通过导航器受控回大厅，再从大厅进入目标模式。尚未明确支持的中途页面不能靠手工状态参数强行实跑。

## 开局接力

`ModeSpec.resume_probe`（可选）给一条路线装上「开局接着往下跑」的能力。现行共 **11 条**接了探针：
`arena` / `story` / `expedition` / `tower` / `side_story` / `shop_refresh` / `world_boss` /
`knights_donation` / `labyrinth_stone` / `sanctuary` / `achievement`（以 `games/epic7/modes.py` 为准，
逐条覆盖矩阵见 [RESUME_COVERAGE.md](RESUME_COVERAGE.md)）；
其余路线 `resume_probe is None`，调用签名与行为完全不变（仍是 `return_home()` + `navigate()`）。

契约：`ResumeProbe = (machine, screen, navigator) -> Optional[ResumePoint]`，其中
`ResumePoint = (page: str, state: Optional[str], entry: Optional[str])` —— `page` 只给日志和诊断看，
`state` 非空时由探针自己 `machine.resume_from(...)` 拨状态机，`entry` 非空表示当前画面已经在导航链的某一级上。

`main._enter_mode` 在实跑开局把探针包成 `_ResumeWatch` 传给 `Epic7Navigator.return_home(stop_probe=...)`：

- 钩子排在页面日志之后、`unknown` 唤醒之前。放在唤醒之后的话，一个没被页面识别命中的支线页面会先被「点屏幕中央」点掉。排在 `lobby` 判定之前是安全的（大厅上各接力锚点都不可见）。
- 钩子只在连续两帧稳定后才被询问，命中就当场 `return`，不再按 `Back`，并把这一帧原样交还调用方。
- 命中 → 跳过 `navigate()`，并把状态机拨到那一步；未命中 → 原样走 `navigate()`，且返回过程中每一页都会再问一次，中途扫到接力点就地接管。
- ``entry`` 非空 → ``navigate(..., already_at=entry)``。**链条与白名单的唯一来源是 ``modes.MODE_SPECS[...].navigation_plan``**（``NavigationPlan.resume_entries``）；``navigation._RESUME_ENTRY_PAGES`` 只是由它派生的**只读视图**，别再往那里手抄页面名。传白名单之外的页面直接 ``ValueError``，不做静默降级。

``navigate()`` 自 2026-09-30 起**不认识任何具名路线**：它以前是一张 ``if mode == "story" / elif mode == "arena" / ...`` 的分派链（约 250 行），每加一条路线都要回去改它。现在链条声明在注册表旁边、执行器只认数据，``tests/test_navigation_plans.py`` 用源码级断言钉住「分派链不许长回来」。

**执行语义**（与原分派链逐字等价）：按 ``already_at`` 命中链条上哪一步，跳过它**以及它前面所有步**，从下一步接着走，并把调用方给的那一帧继续当作来源帧；命中末端就是「导航已完成，一次都不点」。多目标步骤（远征 ``lobby → battle_menu|season_menu``）按「由浅到深」写 ``targets``，顺序即优先级。

**接力点顺序即优先级**，每条路线各有一张自带注释的常量表：

- `arena`：判定顺序 **竞技场模式选择（`observed_page == arena_mode`）→ `SELECTED` → `TEAM` → `LIST` → `RESULT` → `CONFIRMING` → 战斗中（`battle_scene_visible`）**。`SELECTED` 必须排在 `LIST` 前面 —— 选中对手时列表锚点仍然可见，只有 `challenge` 反超 `list_ready` 才能区分出「已选中」。`TEAM` 那一步还会用 `no_ticket` 二次排除买票弹窗压住的假队伍页。
  后两步（结果页 / 段位弹窗）没有放进 `_ARENA_RESUME_ORDER` 循环，而是走 `arena.result_arena` 与 `arena.rank_promotion` 两个证据页判定：`is_in_state(RESULT)` 用的是运行期的松判据（只要 `confirm` 可见），开局时屏幕上可能是任何路线，不能拿它当接力判据。顺序上追加在后面是安全的 —— 实测这两页上前三页的锚点全部远低于阈值（结果页上 `list_ready` 0.2722 / `challenge` 0.2624；段位弹窗上 0.6425 / 0.6857），不会互相遮蔽；两步之间也互斥（结果页 `confirm`=1.0000 而晋级箭头不可见，段位弹窗上箭头 0.9993 而 `confirm` 只有 0.1484）。
- `story._STORY_RESUME_ORDER`：先判 `battle_scene_visible()`，再判关卡入口，然后按 `prepare_battle / watch_story / start_mission / select_team / skip_confirm / skip / complete / bonus_reward / results_confirm / clear / reward / next_stage` 逐页判。顺序上有三处硬约束：战斗必须排在所有锚点之前；`prepare_battle`/`watch_story` 必须排在 `next_stage` 之前（同页可见）；`complete` 必须排在 `next_stage` 之前（实测 `complete`=1.0000、`next_stage`=0.9780）。
- `expedition._EXPEDITION_RESUME_ORDER`：先收战斗菜单/赛季菜单（只有导航器认得出来，靠 `observe().name`），再收局内，然后按 `HOME → RETURNING → POSTERS → DIFFICULTY_CONFIRM → DIFFICULTY → OUTCOME → RECRUIT_CONFIRM → READY → RECRUIT_RETURN → TEAM → RESULT → BATTLE` 逐状态判。`HOME` 必须排在 `RETURNING` 前（后者的第一判据就是主页可见）；`OUTCOME` 必须排在 `READY` 前（否则会丢掉还没领的招募）。

**状态机必须拨准，不能指望第一帧自愈**：主线 `next_action` 里有两支依赖进来时的状态才肯点击（`prepare_battle` 在 `WAIT_COMPLETE`/`WAIT_NEXT_STAGE` 下只记轮次不点；战斗控件分支只在 `WAIT_SKIP_CONFIRM`/`WAIT_BATTLE`/`ACTIVE` 下跑），远征 `next_action` 则是纯状态驱动的，拨错会走到 `_required` 失败或点错按钮。
`<Route>StateMachine.resume_from()` 只做一件事：把「保留当前进度」这一个语义记下来
（2026-09-26 之前的另一半 `reset_after_recovery()`「退回重开一轮」已随恢复通道删除）。

**局内接力**：三条路线都支持，且都不按 `Back`、不重新导航，而是把这一局直接交给战斗监督等结算。
竞技场和主线各有一个 `_resume_into_committed_battle()`（由 Runner 在 `resumed_from is <BATTLE 态>` 时调用），原因是 `next_action(BATTLE)` 那条路靠 `auto_off` 图标定位，而**自动战斗开着时这个图标根本不可见**，硬走会抛未识别并在超时后安全停止 —— 等于在已经承诺的战斗里按 `Back`（2026-09-26 之前那次超时会去「回大厅重新导航」，现在不会了）。
远征复用主循环既有的「无动作 + 状态是 `BATTLE` → 交战斗监督」分支
（`TransactionalRunnerBase._SETTLED_BATTLE_STATE`；2026-09-26 之前这段在 `ExpeditionRunner.run()` 里），无需额外代码。

**竞技场「战斗结果页」的排他判据**：结算页底部那条「战斗结果 / 确认」是竞技场和远征**共用**的通用结算条（实测竞技场 `result.png` 上 `confirm`=1.0000，远征 `result.png` 上也有 0.9448，都过了 0.90 阈值），光靠它分不出这是哪条路线的结算。所以加了三个竞技场专有内容锚点：`result_rating`（「积分」面板标题，**胜负都会出现**）、`result_victory`（「VICTORY」横幅，只有赢才有）、`result_defeat`（「DEFEAT」横幅，只有输才有）。它们在 `arena.result_arena` 页里与 `confirm` 组成合取判据，阈值 0.80。⚠️ 2026-09-25 真机复测修正了依据：`result_rating` 在真机帧上只有 0.38（只在旧基准夹具上有效），真正在干活的是两个横幅 —— victory 在赢帧 0.8761~0.8816、defeat 在输帧 0.9871~1.0000，而全库 227 张夹具里除结果页外 victory 最高 0.2724、defeat 最高 0.3828。
两个模板是 `games/epic7/templates/arena_result_rating.png`（73×41 @922,657）与 `arena_result_victory.png`（558×83 @683,378），2026-09-16 从 `tests/fixtures/epic7_arena/result.png` 按证据档案里的矩形实裁。

**不相容的画面不接力**：买票弹窗压住的队伍页（`no_ticket` 显式排除）。局内不在 `detect_resume_state` 里认，改由 `detect_resume_point` 用 `battle_scene_visible` 兜住（4 张局内实时帧只有 1 张能靠 `auto_off` 认出来，按锚点判会误触发「回大厅」）。
**探针只挂在开局那一次「回大厅」上**：`_enter_mode` 用 `home_return(stop_probe=...)` 起步，
「回家」途中每确认一帧稳定画面就问一次探针，人在那儿就**就地接管**。2026-09-26 之前另有一条
「恢复导航」（退回已知起点重开），它**刻意不带探针**—— 半路接管会跟它打架；那条路已随用户
「回家就是结束」的拍板整段删除。

## 模板和回归素材

- `tests/fixtures/` 保存完整游戏窗口，是问题的可重放证据。
- `games/epic7/templates/` 保存局部稳定锚点，是线上识别输入。
- 模板优先使用文字、图标和按钮轮廓，避免章节背景、角色立绘、动画和动态角标。
- 竞技场、主线、远征和英雄合成的视觉证据分别维护在 `games/epic7/evidence/`。当前 `tools/check_evidence.py` 支持竞技场离线检查；其他正式路线从实跑失败证据包定位失效键名。
- 背景变化大的控件使用专用颜色、边缘或区域算法，并配正例、变体和反例测试。
- 当前客户端未采集的页面应安全停止，不能拿旧客户端素材冒充支持。

详细采集规则见 [TEMPLATE_CAPTURE.md](TEMPLATE_CAPTURE.md)。

## 视觉证据诊断

正式路线失败时保留原有 `时间戳_原因.png`，并在同名无扩展名目录中追加：

```text
时间戳_原因.png
时间戳_原因/
├─ screen.png           # 最终全屏（与外面那张同源）
├─ source.png           # 来源页裁剪（有来源区域时才有）
├─ target.png           # 目标页裁剪（有目标区域时才有）
└─ evidence.json        # 动作 / 来源 / 目标 / 尝试次数 / 逐锚点分数 / 结论
```

`evidence.json` 记录证据配置文件、模板路径、搜索区域、参考尺寸、实际分数、阈值、是否命中、中心点和页面结论。低于阈值的模板仍保留数值分数，便于区分“差一点”“区域错误”和“模板完全失效”；只有可选模板文件不存在时分数才是 `null`。`config` 字段就是 UI 改版时应优先修改的位置。

复杂页面不能在检查器和生产状态机中各写一套规则。竞技场的对手选中页及普通/快速战斗页通过共享 evaluator 分类；改判定时必须同时回归生产状态机和检查器输出。

## 日志、资源和故障

终端和滚动文件日志记录模式、轮次、页面、动作、重试、等待、恢复和停止原因。只保留当前监控帧，失败诊断按上限轮换，避免内存和磁盘无限增长。

已定义的资源耗尽返回退出码 `2`；未知页面、黑屏、转场失败或绝对超时返回 `1`；P 键停止返回 `130`。故障定位流程见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
