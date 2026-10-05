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

实跑时每局结算画面会落一张盘：`docs/manual_review/arena/<时间戳>_<win|lose|unknown>_r<轮次>.png`
（文件名保持 ASCII —— `cv2.imwrite` 写不了中文路径）。判定和画面对不上的时候，
这就是第一手证据。

**只留最近 `OUTCOME_FRAME_KEEP`（10）张**，多出来的从最旧开始删（`ArenaRunner._prune_outcome_frames`）——
落盘目录在仓库里、会被 git 跟踪，一张全屏 PNG 1~3 MB，不裁会把仓库撑大。裁剪按**文件名**
排序（命名以时间戳开头 ⇒ 字典序即新旧序），所以改命名格式时要一起看；删不掉（用户正在看图）
只跳过、不中断跑图。

换 `arena_result_victory.png` / `arena_result_defeat.png` / `arena_result_rating.png` 时，
除了跑既有回归，**还要跑 `tests/test_arena_outcome.py`** —— 它是唯一守住
「VICTORY 锚点在赢帧上、DEFEAT 锚点在输帧上真的命中」以及「两个横幅互不误命中」的测试。
接力用的 `arena.result_arena` 页是「rating **或** victory **或** defeat」，
单靠它分不出是哪个坏了。

