# 竞技场视觉维护

## 先看哪里

竞技场视觉证据唯一维护入口：`games/epic7/evidence/arena.py`。

模板文件位于 `games/epic7/templates/`；固定截图和流程回放位于 `tests/fixtures/epic7_arena/` 与现有竞技场测试。

## UI 改版时怎么改

1. 从 legacy PNG 同名目录的 `evidence.json` 找到页面结论和证据键名；`config` 指向本文件对应的代码入口。
2. 先替换对应模板文件。
3. 只有按钮位置变化时，才修改 `REGIONS` 中该键的区域。
4. 只有新旧画面外观造成分数变化时，才修改 `THRESHOLDS`；不得为了通过单张截图盲目降低阈值。
5. 页面组合变化时，修改同文件中的 `PageEvidence`，并同时增加反例测试。
6. 运行：`python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png`。
7. 再运行竞技场专项测试和完整回放。

业务流程和资源安全规则仍在 `games/epic7/arena.py`，不能因为模板失效就先改状态机。

`score` 即使低于 `threshold` 也会保留数值；先比较区域、模板和分差，再决定修改。对手选中页以及普通/快速战斗页使用生产状态机与检查器共享的 evaluator，修改页面组合时两边会同步生效，必须同时跑 fixture 和 Runner 回归。

## 入口锚点：`novice_arena`（2026-10-05 两次踩坑后的定论）

「竞技场模式选择」页底部那个入口按钮，**会变的不止是名字**：

| 变的部位 | 会怎么变 | 处理 |
| --- | --- | --- |
| 按钮**名字** | 新手期「新手竞技场」；脱离新手期后「竞技场」 | 两张候选模板（见下） |
| 按钮**上半截** | 赛季刚开始是「城堡图标 ＋ 全新赛季已开启」；之后换成「段位徽章 ＋ 段位字」（段位字还随段位变） | **绝不裁进模板** |
| 底部固定标题那行**字形** | **每次一模一样** | ← **模板只裁这一块** |

- **候选模板**（`NavigationTemplates.novice_arena`，`tuple[np.ndarray, ...]`）：

  | 账号状态 | 底部标题 | 模板 |
  | --- | --- | --- |
  | 新手期 | 新手竞技场 | `navigation/novice_arena.png`（420×230，**含段位**） |
  | 脱离新手期 | 竞技场 | `navigation/arena_entry.png`（**120×45，只有字形**） |

  语义同 `lobby_shop_entry`：**任一候选过阈即命中、取过阈里最高分**。
  ⚠️ 锚点名沿用历史 `novice_arena`（改名波及面大于收益），它现在指**这个入口按钮**，不特指新手期。

### 两次踩坑（同一个根因：把「会变的那半截」裁进了模板）

1. **第一次（2026-10-05 上午）**：账号脱离新手期后按钮名变成「竞技场」，旧模板只到 **0.7301**
   ⇒ 整页认不出。补了一张**整钮**模板（含城堡图标 +「全新赛季已开启」）。
2. **第二次（同日 15:02 每日任务 ✗）**：补的那张整钮模板在真机上只有 **0.7786** ——
   因为那颗按钮上半截已经换成「段位徽章 ＋ 挑战者V」。
   **上一轮只模拟了「提示那行字消失」，漏了「整个上半截会被换掉」**，模拟的假设本身漏了。

⇒ **定论：模板只裁底部固定标题的字形。** 实测（生产口径 RGB、阈值 0.82）：

| 模板 | 真机·段位态 | 夹具·赛季态 | 夹具·新手期 |
| --- | --- | --- | --- |
| 旧 `novice_arena.png` | 0.8168 | 0.7415 | 1.0000 |
| 整钮（**已废弃**） | **0.7786** | 1.0000 | 0.6092 |
| **纯字形 `arena_entry.png`** | **1.0000** | **0.9986** | 0.9785 |

全库 **219 张**夹具扫描：**> 0.82 的只有竞技场自己在的 2 张**，次高 **0.4054** ⇒ 分离度极大、零误报。

- **点击点**：`novice_arena` 没有 `_CLICK_OFFSETS`，点击点 = 命中框中心。纯字形模板的中心落在
  **按钮文字上**（约 `(705, 1057)`），仍在按钮内（按钮纵向约 882~1112）⇒ 不影响点击。
- **加第三种长相 / 换模板时**：按**当前真机帧**裁（`runtime_diagnostics/epic7_arena/` 里就有），
  **不要**拿历史截图当源；**不要**把上半截（图标 / 徽章 / 段位 / 赛季提示）裁进去。
  改完跑 `tests/test_navigation.py -k arena`：
  `test_arena_entry_candidate_ignores_the_changing_upper_half` 钉住「两种长相的分数必须基本一致」，
  一旦把会变的部分裁回去它立刻红；`test_arena_mode_page_is_recognised_in_every_known_entry_look`
  是端到端（三种长相都要认成 `arena_mode`）。
  **不要**动 `_locate()` / `_assert_anchor_templates()`（它们早已支持多候选并拦「整组为空」）。
- ⚠️ **量分数务必走生产口径 RGB**（`Epic7Navigator` 内部口径）；用 `cv2.imread` 的 BGR 直接喂屏会凭空掉分。
- ⚠️ **遗留同类隐患（未修）**：旧 `novice_arena.png`（420×230）里仍焊着段位字（如「金牌II」），
  账号一改段位就会出同样的问题（用户已脱离新手期，暂时不触发）。

## 大厅入口锚点：`lobby_arena`（2026-10-15）

大厅右下那颗「竞技场」入口，**按钮上方会被游戏挂一条蓝色 EVENT 标**（活动期挂、结束撤）。
旧模板 `lobby_arena.png`（210×100）把按钮上方**一片背景**也框了进去，那条标正好压在这片背景上
⇒ 真机 2026-10-15 17:47 / 17:55 两帧只到 **0.7187 / 0.7212**（阈值 0.82）⇒
`RuntimeError: 页面[大厅]缺少导航锚点 lobby_arena`，竞技场路线起不来。
（当天 07:52 同一颗按钮还是 1.0000 —— 说明标是**当天上午之后**才挂上的。）

**改法**：模板改裁 `(0, 25, 210, 75)`（210×75）—— **全宽保留、只去掉上部 25 行**。
模板内分区实测（3x 网格图读数）：**EVENT 标 y 3~21、字形 y 33~63、底纹 y 52~83**。

| 帧 | 改前 210×100 | 改后 210×75 |
| --- | --- | --- |
| 今天 17:47（挂标） | **0.7187** | **0.9927** |
| 今天 17:55（挂标） | 0.7212 | 0.9945 |
| 正常大厅夹具 | 1.0000 | 1.0000 |
| `lobby_animated_updated.png` | 0.8506 | 0.8483 |
| 退出确认弹窗 | 不过阈 | 0.2162 |
| 其余 10 张大厅帧 | 0.957~1.0000 | 0.955~1.0000 |

全库 **248 张**：过阈 **12 → 14**（多出来的正是那两张挂标帧），**无新增误命中**。

⚠️ **不要裁成「只有字形」**：试过 `(62,28,106,36)` 的纯字形 —— 挂标帧能到 0.9995，
但会让 `lobby_animated_updated.png`（底纹更淡；`test_navigation.py` 等多处引用它、
并要求 `observe()` 判 lobby）从 0.8506 掉到 **0.7816 不过阈**。全宽去上部是唯一
「挂标帧 + 动画帧」都过阈的一档（各候选实测见 `runtime_logs/_probe_arena_crop_candidates.py`）。

- **点击点**：`lobby_arena` 没有 `_CLICK_OFFSETS`，点击点 = 命中框中心，
  由 (1795,635) 变到 (1795,647)（下移 12.5px），仍在按钮底纹内（底纹约屏幕 y 637~668）。

## 每局战绩（胜 / 负 / 未知）

用户看到的「战绩：胜 2 / 负 1」来自 `games/epic7/arena.py`：

- **判定**：`ArenaStateMachine.observe_outcome` —— `result_victory`（「VICTORY」横幅）命中即胜；
  `result_defeat`（「DEFEAT」横幅）命中即负；`result_rating`（「积分」面板标题）只作兜底；
  三个都不在记「未知」。
- **累计**：`ArenaRunner._record_outcome`，每局在战斗监督宣布到结算页之后读一帧，恰好一次。
- **汇报**：`ArenaRunner.outcome_summary` → `main._notify_live` 的通知行与结束行。

两个横幅（VICTORY / DEFEAT）**占同一块区域**，共用 `ARENA_RESULT_BANNER_REGION` ——
区域一致，两个锚点才是同一把尺子。

⚠️ **两个锚点的依据强度不一样，别当成一回事**：

| 判定 | 依据 | 状态 |
| --- | --- | --- |
| 胜 | `arena_result_victory.png`：`epic7_arena/result.png` 上 1.0000，其余 438 张图最高 0.2724 | **实测过** |
| 负 | `arena_result_defeat.png`：真机输局帧 0.9871~1.0000，赢局帧只有 0.1090~0.1129，全库 227 张夹具最高 0.3828 | **2026-09-25 起实测过** |
| 兜底 | `result_rating`：只在**旧基准夹具**上有效（1.0000），真机 5 张全部 0.3815~0.3899 | ⚠️ **真机上已失效**，只兜「横幅还在淡入」那几帧 |

⚠️ **`result_rating` 在真机上失效这件事，是 2026-09-25 才发现的**：那天实跑 5 局
（3 胜 2 输），报出来是「胜 3（未知 2）」—— 因为「负」当时只有这条推理链，而它断在这里。
那两张被判成「未知」的帧现在就是 `result_defeat` 锚点的素材来源
（模板裁自 `..._unknown_r4.png`，回归夹具用 `..._unknown_r1.png`，**故意不取同一张**）。

认不出时仍然**单列「未知」，绝不并入「负」** —— 宁可显示「未知 1」，
也不报一个没把握的比分（远征结算页、空白帧都走这条路）。

**每局的结算画面不再落盘**（2026-11-08 用户要求取消）：旧做法是每局存一张全屏 PNG 到
`docs/manual_review/arena/`、只留最近 10 张。问题是文件名带时间戳、永不重复，**每跑一轮
就在 git 历史里加约 10 张 / 21 MB**，累积到 103 张 / 211 MB —— 那是仓库变胖的主要来源之一。

现在只在**认不出 / 超时 / 手动停止**这类真故障时，由 `Runtime.save_diagnostic` 存诊断帧到
`runtime_diagnostics/epic7_arena/`（带原因标签，`_prune_diagnostics` 会自动轮转）。
战绩本身照旧记进汇总与通知；需要复盘某一局时看诊断帧。

⚠️ `result_defeat` 的素材来源就是当年那批落盘图（`..._unknown_r4.png`）。删功能不影响
已入库的模板，但**以后想重裁「负」的判据图，只能靠实跑撞到输局时的诊断帧**——
撞到了就把帧留下。

换 `arena_result_victory.png` / `arena_result_defeat.png` / `arena_result_rating.png` 时，
除了跑既有回归，**还要跑 `tests/test_arena_outcome.py`** —— 它是唯一守住
「VICTORY 锚点在赢帧上、DEFEAT 锚点在输帧上真的命中」以及「两个横幅互不误命中」的测试。
接力用的 `arena.result_arena` 页是「rating **或** victory **或** defeat」，
单靠它分不出是哪个坏了。


## 「段位升级奖励」弹窗：竞技场的**第二层**弹窗（2026-10-20）

打满一局、点「确认」之后出现的是一条**两层**的弹窗链：

```
战斗结果 ──点「确认」──▶ 段位提升（= 竞技场 `结果确认中` 那一页，判据 = 箭头 + 确认）
                              └──点掉它──▶ 升级奖励（本节的这一层）
                                              └──点「点击关闭」──▶ 对手列表
```

第二层只在**首次升至某个段位**时出现一次（「段位升级奖励只会在首次升至各段位时发放1次」），
所以它一直没被撞见、也就一直没有判据。2026-10-20 08:02 那天撞上了：

| 时间 | 发生了什么 |
| --- | --- |
| 08:02:05 | `confirm-rank` 点掉「段位提升」 |
| 08:02:07 | 来源页判「已离开」（箭头没了 ⇒ `arena.rank_promotion` 不成立） |
| 08:02:45 | 等「对手列表」40 秒仍不出现 ⇒ 转场失败 ⇒ 异常收尾回大厅，整条竞技场记 ✗ |

失败帧上的真实分数（`runtime_diagnostics/epic7_arena/20261020_080245_283281_*`）：
`rank_promotion_arrow` 0.354、`list_ready` 0.640、`confirm` 0.103 —— **全灭**，
只剩那颗被压暗的「确认」按钮还是 0.999，而它被弹窗盖住了、点了没用。

### 为什么修在「全局弹窗守卫」里，而不是在竞技场里加一页

它是**模态通知窗**，点画面任意位置都能关掉，与骑士团那三个「标题 + 点击关闭」同形；
而守卫挂在 `runtime.capture` 上，**每一帧都要过它** —— 包括竞技场那个「等待转场」循环。
放在守卫里，任何路线撞上都能自愈；放进竞技场状态机，其它路线撞上照样卡住。

### 两个锚点（**必须两个都中**）

| 锚点 | 模板 | 角色 | 全库 305 张 1982x1132 负样本 |
| --- | --- | --- | --- |
| 标题「升级奖励」 | `navigation/arena_rank_reward_title.png` | **判据**（排他） | 最高 0.4675（`support_confirm.png`） |
| 底部「点击关闭」 | `navigation/arena_rank_reward_close.png` | **点击点**（不排他） | 单独最高 **0.9852**（`reward_popup.png` 一类领奖弹窗） |

阈值 0.88；双锚点取 `min` 后负样本天花板 **0.2993** ⇒ 地板余量 +0.12、天花板余量 +0.58。
取证脚本：`python -m auto_game_unified.runtime_logs._probe_arena_rank_reward`。

⚠️ **别把「点击关闭」那半拆掉当单锚点** —— 那行灰字是游戏里通用的控件，
0.9852 的四五张帧全是别的领奖弹窗。`test_arena_rank_reward_close_alone_is_not_exclusive`
就是钉这件事的：它在 `imprint_result_popup.png` 上单独拿 0.9548，但整个判据**必须**返回 None。

### 改的时候动哪里

1. 模板两张：`games/epic7/templates/navigation/arena_rank_reward_{title,close}.png`
2. 判据 + 守卫分支：`games/epic7/global_popups.py`（`find_arena_rank_reward_close`、
   `Epic7GlobalPopupGuard._find_popup`）
3. 导航页名：`games/epic7/navigation.py`（`arena_rank_reward_popup`）
4. 装配：`main.py`
5. 护栏：`tests/test_global_popups.py`（5 条）、`tests/test_navigation.py`、
   `tests/test_project_layout.py`、`tests/test_main_story.py`

⚠️ 这类弹窗**一次性**，改完没法用实跑复现 ⇒ 回归全靠夹具
`tests/fixtures/epic7_global/arena_rank_reward_live_20261020.png`。
别因为「跑一遍没再出现」就以为修好了或没问题了。

## 「购买旗帜」弹窗的 PC 覆盖图（2026-11-01）

PC 实跑打到第 5 轮旗帜耗尽，点「开始战斗」弹出「购买旗帜」弹窗（100 心力→5 面 /
30 天空石→5 面）。共享模板在 PC 上认不出它：`no_ticket` 0.7671、
`arena_purchase_title` 0.7341、`arena_purchase_cancel` 0.7750（阈全是 0.90）——
于是监督循环收不到「交还业务处理」信号（`BattleOutcome.PRE_BATTLE_BUSINESS`），
一直重按「开始战斗」到 4 次熔断（`allowed_action_battle-start_failed`）。

**为什么不走低通/白掩膜（实测数据，别再试一遍）**：
低通 σ=2.0 能把 PC 帧拉到 0.914，但会把迷宫「购买确认」和商店四张「购买确认」
弹窗一起抬过阈（0.91+）——标题同为"购买"字样、语义不同，是**真冒牌**，否掉；
白掩膜全库零翻转但 PC 帧只有 0.684，救不动。

**落法**（PC 迁移文档 §3 的设计内动作，代码零改动）：
`templates/pc/{no_ticket,arena_purchase_title,arena_purchase_cancel}.png`，
均从 PC 现场帧（`ticket_purchase_popup_pc_live_20261101`）裁剪。
弹窗帧上三颗 1.0；手头 5 张 PC 反例帧最高 0.497，零误命中。

**修好后的完整链路**（与模拟器一字不差）：
`no_ticket` 命中 → 监督循环冻结背景点击、交还业务 → 正文用友情点买 5 面旗
（`purchase-friendship-ticket`，左侧报价）→ 继续打；若走收尾，则双锚点点「取消」回家。

**回归全靠夹具**：正例 `tests/fixtures/epic7_arena/ticket_purchase_popup_pc_live_20261101.png`、
反例 `result_victory_pc_live_20261101.png`；测试在 `tests/test_arena_evidence.py`
（`test_pc_ticket_popup_uses_pc_override_templates`）。这类弹窗只在旗帜打满时出现，
实跑没法随复现，别因为"跑一遍没再出现"就以为没事。

## 「更新交战对手」确认窗：认不出 + 被遮罩骗（2026-11-07）

**现象**：点「刷新对手」后连点 4 次 `select-opponent` 全是「来源=仍在」，
`点击 select-opponent 后画面未稳定进入[对手详情]`，整条竞技场记 ✗。
诊断帧 `20261107_075618_707374_no_transition_list_to_selected.png`（已存夹具
`free_refresh_confirm_pc_live_20261107.png`）就是这层弹窗本身。

**两层根因，必须一起修**：

1. **认不出**。三个锚点都是模拟器字形，PC 帧上 `refresh_title` 0.6374 /
   `refresh_free` 0.7967 / `refresh_confirm` 0.7273，阈全是 0.90 ⇒ 三锚点缺一不可
   所以 `free_refresh_confirm` 恒返回 None、确认永远不点。
   按口径决策树先试了两步都救不动：掩膜阈值放宽（V≥140→80、S≤110→220）最高 0.7126；
   掩膜 + 扫尺寸 ±4% 最高 0.84 —— **换了字形，不是参数问题**。
2. **遮罩把判据反转**（这一条才是重点）。它是**半透明**模态框，底下的对手行被压暗，
   而 `opponent_availability` 判「这个对手能不能打」靠的是行内**红色**像素占比：
   压暗后红色掉到 0.0000 / 0.0000 / 0.0387（阈值 ≤0.05 即判「可挑战」）⇒
   三名**均不可挑战**的对手全被判成可打（刷新前的日志明写「三名对手均不可挑战」）。
   而 `_wait_until_safe_list` 的 safe 判定排在弹窗处理**之前** ⇒ 两帧一致即
   `return True` ⇒ 弹窗永远轮不到点。

**修法**：

- 三张 PC 覆盖图 `templates/pc/arena_refresh_{title,free,confirm}.png`（自诊断帧裁剪，
  237×82 / 122×61 / 146×62），本帧各 **1.0000**、点击点 (1231,800) 落在「确认」上；
  反例集最高 0.7536（`skip_confirm.png`），余量 0.146。
- `_wait_until_safe_list` 加一维否证：**`refresh_confirm is None` 才算 safe_list**，
  弹窗在场时不论底下列表长什么样都不作数。

⚠️ **这是新的失败形态，别归到「补图」那一类**：不是「认不出」，是「认出了一个错的
结论」。通用化的一条：凡是判据依赖**会被遮罩盖住的那块画面**（红/绿状态色、血条、
数量角标），都要问一句「这层遮罩压上来它会变成什么」。补图只能解决 1，解决不了 2。

**回归**：`test_pc_backend_picks_up_free_refresh_pc_templates`（三锚点缺一不认）+
`test_safe_list_waiter_rejects_list_hidden_under_free_refresh_popup`
（先断言这一帧上「裸判」确实会误判成有安全对手，再断言等待器不再采信）。
