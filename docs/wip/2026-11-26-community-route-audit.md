---
route: community
status: in-progress
owner: 待认领
started: 2026-11-26
next_step: 归集正常批次的原始证据并绑定待发版本，核对兑换前后积分余额，复核稳定支持
---

# 交接单：社区签到组合体检与整改（模拟器桌面每日入口）

> 合并进 main 后删除这份交接单。实施过程写进提交信息或 PR，仍适用的结论写回维护手册。

认领与关闭条件见[社区签到待办](../TODO.md#社区签到)，由维护者在[待办评审](../../GOVERNANCE.md#从-issue-到发布)分派。长期结论、原始日志定位和保管线索见[社区验收证据](../maintenance/community_checkin.md#验收证据)。

## 一、现在做到哪一步

固定组合：`community / emulator / 模拟器桌面每日入口 / 待验工作区 / 默认设置分支`。

- 基线提交：`4f6d598da1661bb0240e46b7a9322537574b7497`（`main`）。
- 首个故障（14:21）已修：`feed_home` 底栏图标相对旧模板偏 `(1,2)`px，固定窗口 0.5659 < 阈 0.82，被判陌生页并按 ESC 退出社区。现场帧已入夹具，首页判据只对该锚点增加 4px 位移容差，阈值与模板未改。
- 2026-11-26 16:57 执行一次授权的桌面每日入口等价命令：
  `python -m auto_game_unified.main --daily --daily-tasks community:1 --live --confirm RUN`。
  签到成功且首页分支修复已生效；但帖子详情与兑换成功回执出现同类漂移，被判陌生页；兑换确认因此提交两次，实机结论为 `unsafe`。进程被人工终止，随后只做安全退场，最终已回到大厅。
- 同类漂移已离线补齐：帖子详情与兑换成功两颗锚点各加 4px 位移容差，阈值不动；补了现场/反例/状态机回归。社区相关离线测试：`189 passed, 290 subtests passed`。
- 2026-11-27 早上已从正式模拟器桌面每日编排完成正常主流程。该次结果和当前待验项见第八、九节。
- 2026-11-26 晚做完整离线事务整改（用户要求「修到可以安全复跑」）：确认兑换发出后**先等这一笔回执**，
  每笔只提交一次；等不到就停在原地待人工对账。两条旧失败路径用真执行器复现并锁进回归，
  修前 14 失败 / 修后 10 通过。**本轮没有启动实机兑换**。
- 独立复核补上四个失败场景：成功弹窗后限购读数未更新、全局弹窗守卫仍可能发输入、确认发送超时、没有商品来源的订单确认页。正常对照改用 `0/2 → 1/2 → 2/2` 的真实兑换中心帧，覆盖收起成功弹窗后落到商品详情再返回核对，以及收到桌面停止文件后原地停止。

## 二、验收合同（整改后补记，不能追溯为开工前合同）

| 项 | 内容 |
| --- | --- |
| 玩家入口与设置 | 模拟器桌面每日入口；等价命令为 `--daily --daily-tasks community:1 --live --confirm RUN`；默认设置分支；PC 不在本轮范围 |
| 业务目标与数量 | 每日签到 1 次；完成现有两项任务（浏览帖子、分享帖子）；按固定清单把商品兑到每日限购上限 |
| 资源与上限 | 只使用社区积分；行动力*30 每次 20 分、上限 2 次；下级万能强化石两类各 1 次；金币卡不兑；不消耗天空石 |
| 业务回执 | 签到成功弹窗/图标变灰；任务行进度变化或领奖回执；兑换成功弹窗 + 限购计数变化；最终余额与商品上限可核对 |
| 合法终点 | 竖屏点关闭社区 → 转回横屏网页活动列表 → 确认回到大厅首页 |
| 允许提前停止 | 已签到（图标灰/任务日历角标消失）；两项任务均已完成；商品已达每日限购；积分不足且确认键不可用；每条都要有正向画面 |

## 三、11 月 26 日离线整改时的评分

这份评分对应实机复跑前的交接状态。新一轮实机证据见第八节。通过记 0，缺证或不通过记 10。

| 项 | 整改前 | 整改后 | 证据与理由 |
| --- | --- | --- | --- |
| 1. 范围与合同 | 缺证 10 | 缺证 10 | 组合由用户指定、维护手册存在；六项合同在开工后才补记，不能追溯满足开工前要求 |
| 2. 状态与变体 | 不通过 10 | 缺证 10 | 首页/帖子/回执三处漂移现场；首页与帖子已有整帧夹具和全库反例；兑换成功漂移只有日志分数 0.6156，缺真机帧 |
| 3. 动作前证据 | 不通过 10 | 缺证 10 | 已修误判后的来源/目标断言；实机仍出现限购读数与详情页状态不符，需新帧复核 |
| 4. 动作后证据 | 不通过 10 | 通过 0 | 拿到成功弹窗且该商品限购计数加 1 后才可继续；离线断言实际点击序列，确认页停住、陌生页、通道超时和旧限购读数均不会再次提交 |
| 5. 等待与恢复 | 不通过 10 | 通过 0 | 实机出现反复打开商品与返回，旧版离线复现无界；修后限制重开次数，回执与限购核对超时能原地停机 |
| 6. 资源与授权 | 不通过 10 | 缺证 10 | 两次确认已发生；离线断言不再产生 `confirm_redeem`，但积分逐笔变化未对账 |
| 7. 业务与终点 | 不通过 10 | 缺证 10 | 签到成功；浏览/分享未完成；商品已到上限；终点靠人工退场后补验，非一次授权闭环 |
| 8. 离线回归 | 缺证 10 | 通过 0 | 独立复核全量 3463 passed / 1 skipped / 1327 subtests，退出码 0 |
| 9. 实机闭环 | 不通过 10 | 缺证 10 | 14:21 `failed`；16:57 `unsafe`（重复提交确认）；当前候选未完成实机闭环 |
| 10. 放行与复核 | 缺证 10 | 缺证 10 | 独立离线复核已通过，等待当前候选正常主链的实机复核 |
| **总分** | **100** | **70** | 按两列逐项相加。待当前候选完成一次授权的模拟器正常主链和兑换对账 |

## 四、已经改了什么

| 文件 | 改了什么 / 为什么 |
| --- | --- |
| `games/epic7/community_pages.py` | `PageAnchor` 增加 `pad`；只对 `feed_home`、`post_detail`、`redeem_done` 设 4px；阈值与模板不变；命中区域回读真实坐标 |
| `tests/fixtures/epic7_community/feed_home_shifted_live_20261126.png` | 14:21 首页现场帧，旧判据 0.5659 |
| `tests/fixtures/epic7_community/post_detail_shifted_live_20261126.png` | 16:58 帖子详情现场帧，旧判据 0.5123 |
| `tests/test_community_pages.py` | 两帧入 `PAGE_FRAMES`；新增位移容差、相似页反例、回执边界断言；`_score` 按锚点 `pad` 取区域 |
| `tests/test_community.py` | 新增首页/帖子详情现场帧状态机回放，兑换回执连续帧不得重复提交 |
| `games/epic7/community.py` | 新增兑换事务：`redeem_pending` 在途标记（在途期间任何一页都只等、不出手）、`REDEEM_OPEN_ATTEMPT_LIMIT` 有界恢复、`PurchaseReceiptUnclear` 停机 + 保留现场；`confirm_redeem` 转场在途时判「作废」以阻止主循环原样重发；`_capture_frame` 把「读回执时截图超时」按对账处理 |
| `games/epic7/runner_base.py` | 主循环在 `except RuntimeError` 之前单列 `except PurchaseReceiptUnclear: raise` —— 原先它会被当成「页面认不出」再跑一轮，等于再生成一次提交动作 |
| `tests/test_community_redeem_receipt.py` | 新增 10 条离线回归：两条旧失败路径、截图超时、正常回执连兑第二笔、有界恢复、正式停止入口、每日编排停整轮、状态机在途闸门 |
| `docs/maintenance/community_checkin.md` | 补「位移容差只给已取证锚点、不降阈值」与「确认兑换只提交一次、回执未明停机对账」两条长期口径 |
| `docs/TODO.md` | 社区签到条目改写为当前阻断事实与待验条件 |

## 五、首个故障与实机现场

### 14:21 首个入口故障（已修）

- 日志：`runtime_logs/epic7_community.log:22431–22458`。
- 首帧：`runtime_diagnostics/epic7_community/20261126_142128_920813_community_wait_silent.png`。
- 事实：画面已是竖屏社区首页，可见每日签到红点和兑换入口；`feed_home` 0.5659 < 0.82，判 unknown；4 帧确认后 ESC，退到横屏网页活动列表并超时。
- 量化：固定窗口 0.5659；4px 邻域 0.9981，命中 `(126,1740,65,100)`；帖子详情/网络提示/分享面板反例均低于阈值。

### 16:57 授权实机（阻断）

- 日志边界：`runtime_logs/epic7_community.log:22459–22831`，16:57:10 至 17:07:59；命令退出码 127（人工终止）。
- 已完成：16:57:51 `feed_home` 确认并 `tap_signin`；16:57:57 识别 `signin_done` 并确认；16:58:12 进入任务页；16:57:40 前完成大厅→活动→网页活动列表→竖屏社区。
- 首个新故障：16:58:23 现场帧保存，帖子详情分享箭头 0.5123 < 0.82，判 unknown；浏览与分享各反复作废，未取得任务回执。
- 危险动作：17:03:48 `confirm_redeem` 第 1 次；17:03:53 回执 `redeem_done` 只有 0.6156，判 unknown；17:04:11 按返回；17:04:20 第 2 次 `confirm_redeem`；17:04:25 再次未认出回执。
- 实得：签到完成；商品「行动力*30」达到 `每日限购2/2`、按钮「已达到购买上限」；终止时余额 930。日志能证明发了两次确认输入，起始余额与每次扣点没有逐笔记录。
- 人工止损：先尝试 P 停止键无效，按命令行定位并终止 PID 13448/25456；随后只用标准退场动作：关闭社区 → 网页活动列表 → 活动页 → 大厅。终点帧：`runtime_diagnostics/epic7_community/20261126_171800_manual_lobby2.png`（已确认大厅）。

## 六、旧失败 / 新通过测试节点

| 用途 | 完整节点与结果 |
| --- | --- |
| 旧失败（首页） | `tests/test_community_pages.py::CommunityPageTests::test_judges_every_page_from_its_own_frame`，加入 `feed_home_shifted_live_20261126` 后修复前报 `AssertionError: 'unknown' != 'feed_home'`，`SUBFAILED(frame='feed_home_shifted_live_20261126')` |
| 旧失败（帖子） | 现场帧在 `pad=0` 下 `cp.judge_page(...)` 返回 `unknown`，`post_detail` 固定窗口 0.5123；对应日志 16:58:23 |
| 旧失败（回执） | 实机日志 17:03:53 / 17:04:25：`兑换成功 0.6156` 被判陌生页，随后重复提交确认 |
| 新通过（判据） | `CommunityPageTests::test_shifted_feed_home_uses_anchor_padding_not_a_lower_threshold`、`test_feed_home_padding_still_rejects_similar_and_loading_frames`、`test_shifted_post_detail_and_redeem_receipt_keep_their_boundary` |
| 新通过（状态机） | `CommunityStateMachineTests::test_live_shifted_feed_enters_the_signin_branch_from_the_real_entry`、`test_live_shifted_feed_does_not_escape_when_already_in_feed_state`、`test_live_shifted_post_detail_continues_the_task_instead_of_escaping`、`test_shifted_redeem_receipt_is_acknowledged_and_never_reconfirmed` |
| 汇总（判据轮） | `python -m pytest -q auto_game_unified/tests/test_community_pages.py auto_game_unified/tests/test_community.py` → `189 passed, 290 subtests passed in 31.84s` |

### 兑换事务整改（2026-11-26 晚，离线；**未启动实机兑换**）

先按用户要求用**真 `CommunityRunner` + 真 `Runtime` + 假窗口**复现旧路径，再改代码。
「修前」数据是把 `games/epic7/community.py`、`games/epic7/runner_base.py` 临时还原到基线
`4f6d598` 后跑同一组用例得到的。

| 用途 | 完整节点与结果 |
| --- | --- |
| 旧失败（原地重复确认） | `test_community_redeem_receipt.py::FrozenConfirmPageTests::test_a_frozen_confirm_page_is_submitted_once_and_then_held_for_reconciliation`：修前 `RuntimeError: 动作 confirm_redeem 点击4次后画面未推进`，即同一点被点 **4 次**；修后实际点击序列 `[开单, 进入确认页, 确认]` 各一次 |
| 旧失败（陌生页后重开单） | 同文件 `StrangerAfterConfirmTests::test_a_stranger_page_after_submit_is_not_dismissed_nor_reordered`：修前假窗口 120 帧耗尽仍没停（把帧放到 400 帧时 `confirm_redeem` 累计 **25 次**、按返回 25 次）；修后只提交一次、按返回 0 次 |
| 旧失败（截图超时） | `FrozenConfirmPageTests::test_a_capture_timeout_after_submit_is_also_receipt_unclear`：修前 `subprocess.TimeoutExpired` 原样穿出路线入口（它不是 `RuntimeError`，会落到 main 的通用异常收尾 ⇒ 回大厅抹掉现场）；修后转成 `PurchaseReceiptUnclear`，`__cause__` 保留原始超时 |
| 旧失败（循环无上界） | `BoundedRecoveryTests::test_the_open_item_stranger_loop_stops_within_the_attempt_limit`：修前 120 帧内开单 8 次仍在转；修后第 5 次（`REDEEM_OPEN_ATTEMPT_LIMIT`）收手并留诊断 |
| 旧失败（每日编排不停） | `DailyBatchStopsTests::test_the_daily_batch_stops_at_community_and_does_not_start_the_next_route`：修前 `['community', 'arena']`（**跑了下一条**）；修后只剩 `['community']`，`aborted_reason` 写明「保留对账现场」 |
| 新通过（正常回执） | `TrustedReceiptTests::test_each_purchase_is_submitted_once_and_a_trusted_receipt_unlocks_the_next`：两笔的输入序列都是 `[开单, 进入确认页, 确认, 收起回执]`，确认共 2 次 |
| 新通过（停止入口） | `StopRequestTests::test_a_stop_request_while_waiting_for_the_receipt_sends_nothing_more`：`Runtime(stop_requested=...)` 置真后抛 `ManualStop`，点击停在 3 次、返回 0 次、竖屏通道一次没被调用 |
| 新通过（状态机闸门） | `PendingDecisionTests`：在途期间 7 张已知/陌生帧全部返回 `None`；只有 `redeem_done` 能收场；`preview` 快照往返不丢在途标记 |
| 基线对照 | 同一批用例在基线代码上 `14 failed, 3 passed in 74.10s`；修复后 `10 passed, 7 subtests passed in 28.88s` |
| 汇总（本轮） | `python -m pytest -q auto_game_unified/tests/test_community_redeem_receipt.py auto_game_unified/tests/test_community.py auto_game_unified/tests/test_community_pages.py` → `199 passed, 297 subtests passed in 60.87s` |
| 全量 | `python -m pytest -q auto_game_unified/tests --basetemp=D:/Cache/Temp/pytest_redeem/run` → `3459 passed, 1 skipped, 1327 subtests passed in 591.43s`（改的是共享主循环 `runner_base`，按规矩跑全量；进程退出码被 `safe-delete` 批量删除保护拦下，与用例结果无关） |
| 独立复核全量 | `python tools/check.py --full`，两片共 `3463 passed, 1 skipped, 1327 subtests`，退出码 `0`。编译、Ruff 和 mypy 均通过。关键四条反例修前均失败，修后全量通过。 |

## 七、离线回放类别

| 类别 | 覆盖节点 |
| --- | --- |
| `normal` | 首页现场帧从入口进入签到；帖子详情现场帧继续 browse/share 脚本 |
| `repeat` | 登录/兑换重复帧与连续帧不重复确认；`CommunityStateMachineTests` 的 preview/snapshot 一组；确认页停住 / 陌生页 / 截图超时三种「看起来没进展」都只提交一次 |
| `overlay` | 分享面板、签到弹窗、图片查看器、网络异常、帖子详情与兑换成功互斥边界 |
| `slow_or_frozen` | 空白竖屏帧有界等待；未执行滑动记账；兑换结果等待窗口；确认页冻住 → 等满 90 秒按回执未明停机并留现场 |
| `unknown` | 陌生页三级逃生、真实分数留痕 |
| `end` | 兑换清单满、兑不了、退出社区后横屏收工 |
| `safe_stop` | 积分不足、商品已达上限、任务全部有结论后转兑换；**等待回执期间**收到正式停止请求不再发输入 |

## 八、正常每日入口实机复核

2026-11-27 桌面模拟器批次为 07:55:12–08:34:22，社区段 08:27:44–08:31:51。主工作进程退出码为 0，随后启动了成就领取。工作区运行日志未写明可对照的发行候选提交和游戏版本。

| 核对项 | 原始依据 |
| --- | --- |
| 日常签到 | `runtime_logs/epic7_community.log:22848–22855` 显示签到成功、收起确认。 |
| 浏览、分享 | 同日志第 22869–22974 行。各自回到任务页核对后一次推进，未进入补做；接着进入兑换中心。 |
| 兑换 | 同日志第 22978–23065 行。实际提交 4 次，成功回执 4 次。行动力两笔，限购 0/2 → 1/2 → 满额；两类强化石各一笔，最终确认兑换清单已满。按日志显示的单价计算共 140 积分。 |
| 收尾与交接 | 同日志第 23066–23079 行确认回横屏及大厅。`runtime_logs/epic7_daily_probe.log:2758` 确认下一项在大厅接手。 |

首次进入兑换中心经历短暂加载，等待后正常识别，期间未发送返回键。四笔回执等待中没有第二次确认输入。现状记为国服模拟器每日正常主流程实机通过。

## 九、待收口证据

- 核对兑换前后的积分余额。若从签到前开始核对，同时记下签到和任务获得的积分。已有报价、成交回执与限购变化可用于对账。
- 稳定放行时绑定实际客户端及版本、待发提交或工件与验证记录。正常入口这一次的证据已取得。漂移、迟到回执和截图超时按现有离线回放复核。
- 已保存的兑换前加载帧可用于补页面正反例。入库前按图片规范做无损压缩。

## 十、坑（试过但没用的）

- 全局 P 停止键通过 `keybd_event` 发送后未生效，程序继续重复兑换；最终按命令行特征定位并终止进程。下次优先使用界面停止或 `--stop-file`，不要依赖合成按键。
- 终止时模拟器物理画布仍是 1080×1920，但 screencap 是 1920×1080 拉伸帧；按截图像素直接点 X 不生效。按物理坐标反算后才退出社区。
- 多张诊断帧逐字节相同时先怀疑取图通道；这次取图正常，漂移是模板位置/页面变体问题。
