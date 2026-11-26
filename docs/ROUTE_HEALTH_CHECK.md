# 路线体检报告（基准日 2026-11-25）

> 历史审计快照。重新体检时，按[现行评分规则](howto/route_change.md#5-agent-体检与评分)固定提交和支持组合并复核证据；本页保留当时的分数、工作区状态和整改建议供追溯。

这份报告按当前规范对全部路线做同一口径体检，供后续 Agent 按分数从高到低施工。
它是**施工输入**，不是放行声明：文中的「试用」「历史放行」只描述现有证据层级，
不等于对外可宣称稳定。

取证方式为只读：读 `docs/README.md` 的规范入口、`docs/howto/route_change.md`、
`docs/howto/route_acceptance.md`、`docs/TRANSITION_CONTRACTS.md`、`docs/ROUTE_CONTRACT.md`、
`docs/SAFETY_MATRIX.md`、`docs/TODO.md`、`docs/STATUS.md`，以及各路线维护手册、实现与测试；
返工数用 `python -m auto_game_unified.tools.report_rework` 复核（扫描 431 个提交）；
工作区状态用 `git status` / `git diff` 单独核对。本次未改任何路线代码、判据、阈值、次数或默认设置。

## 一、评分总表（分数越高，风险越大）

| 维度 | 满分 | 量的是什么 |
|---|---:|---|
| 声明缺口 | 10 | 五项契约与安全矩阵危险动作行是否齐 |
| 动作闭环/回执 | 20 | 来源、目标、两帧证据、有界失败是否齐 |
| 反例与素材 | 20 | 关键反例、变体矩阵、真机素材是否齐 |
| 实机验收 | 25 | 是否正常闭环、重复启动、PC 证据、台账 |
| 危险动作 | 10 | 不可逆或付费分支是否有实机证明 |
| 返工与未收口 | 15 | 修正类提交、一次跑通、工作区未提交改动 |
| **合计** | **100** | 0 = 已稳定，100 = 风险最高 |

| 排名 | 路线 | 声明 | 动作 | 反例 | 实机 | 危险 | 返工 | 总分 | 当前结论 | 修正类提交 / 预算 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 狗粮 `fodder` | 10 | 20 | 20 | 20 | 3 | 0 | **73** | 不可声称稳定 | 2 / 预算内 |
| 2 | 刷书签 `shop_refresh` | 0 | 10 | 10 | 15 | 10 | 12 | **57** | 不可声称稳定 | 12 / 超预算 |
| 3 | 远征 `expedition` | 0 | 10 | 15 | 20 | 3 | 8 | **56** | 不可声称稳定 | 9 / 超预算 |
| 4 | 竞技场 `arena` | 0 | 10 | 10 | 10 | 10 | 15 | **55** | 待收口 | 21 / 超预算 |
| 5 | 迷宫强化石 `labyrinth_stone` | 0 | 10 | 15 | 10 | 6 | 12 | **53** | 不可声称稳定 | 12 / 超预算 |
| 6 | 主线补星 `story_star` | 0 | 15 | 5 | 15 | 10 | 8 | **53** | 不可声称稳定 | 5 / 超预算 |
| 7 | 活动 `survivor` | 4 | 15 | 15 | 10 | 6 | 0 | **50** | 试用 | 0 / 预算内 |
| 8 | 世界首领战 `world_boss` | 3 | 10 | 10 | 10 | 6 | 10 | **49** | 待收口 | 8 / 超预算 |
| 9 | 宠物领养 `pet_adoption` | 0 | 10 | 5 | 15 | 6 | 10 | **46** | 待收口 | 2 / 预算内（口径差异见下） |
| 10 | 活动剧情 `activity_story` | 5 | 10 | 10 | 10 | 6 | 4 | **45** | 试用 | 2 / 预算内 |
| 11 | 社区签到 `community` | 0 | 10 | 5 | 10 | 10 | 10 | **45** | 待收口 | 5 / 超预算 |
| 12 | 月塔 `tower` | 0 | 5 | 10 | 15 | 3 | 8 | **41** | 试用 | 7 / 超预算 |
| 13 | 月光剧场 `moonlight_theater` | 0 | 5 | 10 | 10 | 6 | 8 | **39** | 试用 | 6 / 超预算 |
| 14 | 骑士团捐赠 `knights_donation` | 0 | 10 | 5 | 10 | 6 | 8 | **39** | 不可声称稳定 | 8 / 超预算 |
| 15 | 英雄合成 `hero_synthesis` | 0 | 0 | 5 | 10 | 6 | 15 | **36** | 不可声称稳定 | 56 / 超预算 |
| 16 | 支线故事 `side_story` | 0 | 5 | 15 | 5 | 3 | 8 | **36** | 试用 | 7 / 超预算 |
| 17 | 装备制作 `craft_equipment` | 3 | 10 | 5 | 10 | 3 | 4 | **35** | 试用 | 0 / 预算内 |
| 18 | 主线 `story` | 0 | 5 | 5 | 5 | 0 | 15 | **30** | 历史放行 | 24 / 超预算 |
| 19 | 成就领取 `achievement` | 0 | 5 | 10 | 5 | 3 | 4 | **27** | 试用 | 3 / 预算内 |
| 20 | 企鹅批量购买 `penguin_purchase` | 0 | 5 | 5 | 5 | 3 | 4 | **22** | 试用 | 0 / 预算内 |
| 21 | 圣域收菜 `sanctuary` | 0 | 5 | 5 | 5 | 3 | 0 | **18** | 试用 | 3 / 预算内 |

**结论分布**：不可声称稳定 7 条、待收口 4 条、试用 9 条、历史放行 1 条。**无一条满足公开稳定**。

**口径说明**：修正类提交数与预算一律以 `report_rework` 为准（7 天窗口 + 预算列），
已逐条复算 21 条路线。审计组按 git log 累计提交把 `pet_adoption` 记为 4 次超预算、
把 `survivor` 记为 2 次，与工具口径（分别为 2 次预算内、0 次预算内）不同，
以工具为准；两条的返工维度分数均已计入一次跑通与否及未收口改动。
工具口径的一次跑通共 7 条：`tower`、`side_story`、`sanctuary`、`fodder`、`survivor`、
`penguin_purchase`、`craft_equipment`。英雄合成 56 次为全库最高，虽然总分因声明与动作维度
证据完整而未排到第一，但返工维度已给满分并单独标「不可声称稳定」，不以总分掩盖。

## 二、全局共性问题（影响全部路线）

1. **无验收台账**：全仓 `acceptance.json` 只出现在 `.pytest_tmp/` 与 `runtime_logs/_basetemp_verify/`
   的 `test_*` 目录，是 pytest 临时产物，不是真实运行沉淀的台账。按
   `docs/howto/route_acceptance.md` 第 5 节，无台账即不能进入公开稳定。
2. **四条路线有未收口改动**：竞技场、世界首领战、宠物领养、社区签到的工作区改动
   改变判据或收工语义，一律记「待收口」，返工维度各 +2，不计入已达标。
3. **返工普遍超预算**：全库 192 个修正类提交（标题带 fix 仅 85 个），一次跑通 7/21 = 33%，
   小修在预算内 8/21 = 38%。超预算路线按 `docs/howto/route_change.md` 第 4 节只能标试用，
   需出熔断重做计划。
4. **两份维护手册缺失**：`docs/maintenance/fodder.md` 与 `docs/maintenance/world_boss.md`
   不存在，`world_boss` 代码引用的 `docs/WORLD_BOSS_DESIGN.md` 也不存在。
5. **两处声明与代码不一致**（施工前先订正，避免后续 Agent 依据错文档）：
   - `craft_equipment`：安全矩阵第 28 行把 `test_safety_fail_closed.py` 列为对应测试，
     但该文件的 `RESOURCE_ROUTES` 不含 `craft_equipment`，两道跨路线护栏对本路线未生效。
   - `activity_story`：安全矩阵第 34 行写「无花资源动作」，但代码 `_handle_stamina` 会买生命之叶。
6. **PC 放行口径冲突**：`activity_story` 在 `docs/STATUS.md` 列为 PC 已放行，
   在 `docs/SAFETY_MATRIX.md` 写 PC 未放行，需统一后再决定 PC 取证范围。
7. **干跑记录口径冲突**：安全矩阵第 105 行称「除成就外没有一条路线留下干跑记录」，
   但第 101 行 `story_star` 也标了「11-10 干跑（退出码 0）」。两条不能同时成立，
   施工前先核原始日志确认归属。

## 三、逐路线体检

### 1. 狗粮 `fodder` — 73 / 不可声称稳定

- **已具备**：写了五项契约文字（`terminal=assistant`、空覆盖层）且安全矩阵第 24 行有危险行；体力判定复用主线 `stamina.next_stamina_decision`，叶子不可用即 `StaminaExhausted`；有 11 张夹具与 `tests/test_epic7_fodder.py`、`tests/test_fodder_runner.py`；修正类 2 次且一次跑通。
- **不符合/缺证据**：`FodderAction` 构造只传 name/point，来源、目标、回执全空，主循环当「此动作不需验收」照跑（`games/epic7/fodder.py:70-77`、`modes.py:745-748`）；`docs/maintenance/fodder.md` 不存在；1 轮/2 轮/异常恢复全为警告，整链未验、无收尾字段；`fodder/replay.png` 被 `battle_scene_visible` 误判为局内，接力豁免且无反例（`modes.py:671-676`）；无反例登记；PC 未放行；危险护栏无实机证明。
- **给后续 Agent 的下一步**：给每个动作填 `source_page`/`target_pages` 并用真状态机过契约；新建 `docs/maintenance/fodder.md` 六节；采「关卡地图→队伍→战斗→结算→重新进行」各段正反夹具，先补 `replay.png` 反例；跑一条真实正常闭环建台账；关闭豁免前不扩大 PC 支持范围。
- **出处**：`games/epic7/fodder.py:70-77,200-303`；`games/epic7/modes.py:671-676,745-748,1049-1057`；`docs/SAFETY_MATRIX.md:24,85,326`；`docs/STATUS.md:18,98`；`docs/TODO.md:71`；`docs/TRANSITION_CONTRACTS.md:170,395`。

### 2. 刷书签 `shop_refresh` — 57 / 不可声称稳定

- **已具备**：契约五项齐、默认 0 次付费刷新为安全默认；购买与刷新各一道单击闩锁且有「第二次返回假」断言；两种真实购买事务回放 + 价格校验 + 同行约束 + 已购行 0/1 黄掩膜、售罄行白掩膜；真机闸门 `LIVE_TRANSACTIONS_VERIFIED` 未置位时拦实跑，PC 与模拟器都跑过（`modes.py:525-534`）。
- **不符合/缺证据**：两笔各 18,000 金币扣款未对账，一笔「指令已发出、回执未明」，一笔「程序记成功、账户流水未核」（安全矩阵第 146、208-209、263-264、359-361 行）；已知鼠标压住 `0/1`、焦点空格提示盖住 `0/1` 导致「钱花了却判结果不明确」；售罄与已购两条购买链待复跑；金币不足与天空石不足夹具缺；2 轮实机缺失；账号未记录。
- **给后续 Agent 的下一步**：先对账两笔扣款的实际账户流水并分别下结论；复跑两条购买链并补遮挡、鼠标压住反例帧；采两种资源不足夹具验证 UNKNOWN 安全停止；补同一提交下的两轮台账；复算返工计数。
- **出处**：`docs/SAFETY_MATRIX.md:21,87,146,208-209,263-264,359-361`；`docs/TODO.md:12`；`games/epic7/modes.py:525-534,1207-1211,1236-1246`；`tests/test_shop_refresh_runner.py`、`tests/test_shop_refresh_evidence.py`。

### 3. 远征 `expedition` — 56 / 不可声称稳定

- **已具备**：契约五项齐（空覆盖层显式、空态 POSTERS）；`ExpeditionAction.source_page`/`target_pages` 加基类 `_execute_transition` 两帧验收，缺任一字段直接抛；`empty_posters` 固定文案零可变内容、缺模板 fail loud、`PostersExhausted` 退出码 2；结论门槛接在事务型基类 `run()`。
- **不符合/缺证据**：唯一「1 轮实机」仍是离线回放，正常字段未逐段对业务，无正常业务闭环；`battle_general_tab` 模板裁自赛季高亮条，赛季页签被判「一般」导致点不动；难度一/二未采帧，缺三态选中对照；冻结帧护栏未启用待用户拍板；多轮日志未整理、无台账；PC 未放行；危险护栏无实机证明。
- **给后续 Agent 的下一步**：采难度一/二与难度三选中对照整帧并建三态落点测试；重裁 `battle_general_tab` 为真「一般」未选中态并补赛季页签串判反例；补一条真实正常闭环台账；整理多轮日志；冻结帧护栏是否启用先请用户拍板，不擅自改重试语义。
- **出处**：`games/epic7/modes.py:921-931,724-729,2008-2013`；`docs/SAFETY_MATRIX.md:22,69-72,83,324`；`docs/maintenance/expedition.md:27-34`；`docs/TODO.md:17,35,71`；`docs/STATUS.md:16`。

### 4. 竞技场 `arena` — 55 / 待收口

- **已具备**：契约五项齐（`terminal=LIST`、5 类 overlays、`transition_contract`）；动作来源/目标缺任一即抛、目标连续两帧；反例具体（入口多候选、EVENT 标裁法、周奖卡片交叉分 0.3273、ORB 中心相关 0.80、结算三锚点连读三帧）；买票弹窗冻结背景、红点连续两帧消失才置「已检查」、不连点。
- **不符合/缺证据**：买票护栏行为改动未提交（删 `purchase_stamp_path` 等，新增 `_purchase_refused`）；导航页签修复与手册同步段未提交；11-18 08:43 断网遮罩把周奖红点压成 0，误判「已领完」而实际未入账，全库亮度未标定、未修；第二轮卡在 VS 入场演出帧待复跑；周奖「已选中亮态」、天空石报价、稳定结果帧缺；PC 正常闭环未见字段；`result_rating` 真机判据已失效，战绩只靠胜负横幅；21 次修正超预算。
- **给后续 Agent 的下一步**：先收口买票护栏与页签修复两处未提交改动并跑 `tests/test_arena_*.py` 与 `test_navigation.py` 留证；复跑第二轮逐帧盯 VS 入场演出；采断网遮罩整帧并跑全库亮度标定（是否加第二维须用户拍板）；补周奖亮态与 PC 升级奖励弹窗真机帧；按验收文档第 5 节为模拟器与 PC 各建一条独立启动台账。
- **出处**：`games/epic7/modes.py:805-823`；`docs/SAFETY_MATRIX.md:20,82,323`；`docs/maintenance/arena.md:29-66,120-159`；`docs/TODO.md:9,11,34,62`；`docs/TRANSITION_CONTRACTS.md:385`；`git diff -- games/epic7/arena.py`、`git diff -- games/epic7/navigation.py`。

### 5. 迷宫强化石 `labyrinth_stone` — 53 / 不可声称稳定

- **已具备**：契约五项齐；第三个打开机器强制转场的路线，57 处来源/出口判据声明，`test_action_and_its_declared_exit` 与 Runner 级拒绝测试双层覆盖；买东西三道锁（类别 + 石字 + 白字）缺一不可、`buy_armed` 只对自家确认框放行，误买强化拳套有回归；「没看见」永不作放弃理由；1 区域完成探险有位置判据与三条反向测试。
- **不符合/缺证据**：「切到区域 1」只有正例，缺「选中的是别的区」反例；「商店一行都买不到」只有模拟帧；模拟器缺 `region1_completed.png`（只有 PC 图），该判据在模拟器恒为假；区域标签与选中框反例、商店无可购买行、地图 pin 布局、房间淡入、其他购买确认框均缺；2 轮实机仅 11-06 批量、历史放行（单轮）；无台账；12 次修正超预算并触发熔断线；危险动作有历史误点痕迹，模拟器确认框护栏未真机验证。
- **给后续 Agent 的下一步**：补模拟器 1 区域绿色完成探险帧并验证 `|dx|≤120、0≤dy≤70`；补「选中的是别的区」反例并把测试升级为带负例；采无可购买行、pin 布局、房间淡入与其他确认框后验证确认框限定；补 2 轮独立启动并建台账；对 12 次超预算做熔断重做计划并登记待办。
- **出处**：`games/epic7/modes.py:1509-1518`；`games/epic7/labyrinth_stone.py` 判据与危险边界节；`tests/test_labyrinth_stone.py`；`docs/TRANSITION_CONTRACTS.md`；`docs/TODO.md`；`docs/SAFETY_MATRIX.md:37`。

### 6. 主线补星 `story_star` — 53 / 不可声称稳定

- **已具备**：契约五项齐（`terminal=episode`）；动作判据登记齐，换页用 source/target、滚动与小节用 in_page_evidence，开跑强制回最外层并选第 1 项、归位有界；关键反例测试齐（越界落点、非战斗页不报战斗、两种绿勾尺寸、满星取消开打、体力弹窗）；11-10 干跑退出码 0，连续 4 关「打完→结算→回列表→继续」跑通。
- **不符合/缺证据**：六章完整扫完收工、换章与右滚到底、体力购买、资源耗尽均未真机跑到，只有离线用例；29 次 PC 初始化中正常回首页 0、异常后回首页 15、收尾失败 1、按 P 5、无终止标记 8，日志最高到第 4 章；12:21 与 18:43「外层判未满、小节判全满」判据矛盾未定论，20:33 疑似满星小节进战斗未定论；换章只按前 6 个固定坐标，无「当前选中第几项」画面判据，接力不恢复遍历进度；仅 PC、模拟器故意 fail-closed；无 PC 版本与账号记录、无台账。
- **给后续 Agent 的下一步**：从「换章→归位→第二章全满星→第三章」分段实跑，先补一次连续六章扫完收工；在篇章面板留整帧，同帧核对 `chapter_is_full` 与 `stage_checks` 读数，给两处判据矛盾定论；复验体力购买两段式并核 `StaminaExhausted` 退出码 2；补左列选中态模板或如实登记缺口；建台账并复算返工计数。
- **出处**：`games/epic7/modes.py:1780-1787`；`docs/SAFETY_MATRIX.md:29,101,147,314-316`；`docs/maintenance/story_star.md:32-53,159-163,187-240`；`docs/TODO.md:37`；`tests/test_story_star.py:115,137,331,505,612`。

### 7. 活动 `survivor` — 50 / 试用

- **已具备**：契约五项已声明且明确标注「已知欠债」而非假装有效；升级三选一按色相选蓝卡（攻击武器 hue 94 对辅助 77），三条都非蓝卡时随机选；升级弹窗期间不滑摇杆、重开锚点不落「确认」、认不出 30 秒不动作、锚点缺失即停；工具口径 0 次修正类提交、一次跑通（全库 7 条一次跑通路线之一）。
- **不符合/缺证据**：首卡、重新进行、升级三选一三个动作点完都不回头验证，1800 秒超时只是安全网（`games/epic7/survivor.py:296-302,379-387`）；仅 6 张夹具，缺长存活、连续三选一、重新进行回首卡与连续两轮样本；PC 摇杆滑动 duration 未标定、未放行；实机无收尾字段；契约 `action_evidence="无"` 属实质缺声明。
- **给后续 Agent 的下一步**：为三个动作补出口回执的落点声明（只补验收，不动业务规则）；采长存活与连续三选一真机帧；完成 PC 摇杆 duration 标定并跑整链；补带账号与客户端版本的连续两轮台账；复跑 `tests/test_survivor_runner.py` 确认不回归。
- **出处**：`games/epic7/modes.py:1262-1271,740-744`；`docs/TRANSITION_CONTRACTS.md:394`；`games/epic7/survivor.py:227,296-302,379-387`；`docs/SAFETY_MATRIX.md:33,88,329`；`docs/TODO.md:48,70`。

### 8. 世界首领战 `world_boss` — 49 / 待收口

- **已具备**：契约五项齐（`terminal=HOME`、6 类 overlays）；10 个动作全部带来源/出口判据，`WorldBossTransitionContractTests` 逐个走真状态机；次数耗尽走 `AttemptsExhausted`（退出码 2）不点购买，宝箱先扫后收工并留扫描日志；结论门槛两帧拦下一帧误判收工。
- **不符合/缺证据**：未提交改动把 `worldboss_home_manage_support_team` 从 REFUSED 移到 RESUMABLE 并新增按按钮变体抛 `AttemptsExhausted`，改变收工语义（`games/epic7/world_boss.py:1141`）；`docs/maintenance/world_boss.md` 与代码引用的 `docs/WORLD_BOSS_DESIGN.md` 均不存在；2 轮实机仅 11-03 PC 单轮，缺结算后领奖证据；已提交代码缺 `support_reward_popup` 反例（压暗弹窗帧上 `manage_support_team` 得 0.9997 仍判主页），护栏只在工作区；无台账；8 次修正超预算；借用辅助队伍不可撤回缺实机通过证据。
- **给后续 Agent 的下一步**：提交或回退工作区改动后重跑 manage_support_team 与 resume 用例；补 `docs/maintenance/world_boss.md` 六节并在索引登记；补 2 轮独立启动与结算后领奖证据并建台账；采 `support_reward_popup` 反例夹具跑全库负例扫描；对 8 次超预算出熔断重做计划。
- **出处**：`games/epic7/modes.py:1349-1365`；`games/epic7/world_boss.py:1141`；`tests/test_world_boss_resume.py`、`tests/test_world_boss_runner.py`、`tests/test_world_boss_evidence.py`；`git diff`；`docs/SAFETY_MATRIX.md:35`；`docs/TODO.md` PC 迁移矩阵。

### 9. 宠物领养 `pet_adoption` — 46 / 待收口

- **已具备**：契约五项齐（`terminal=shop`）且安全矩阵第 26 行逐动作写明判据；免费态靠「免费」与「可免费领养！」双锚点，券图标明确不能单独当「今日已领完」证据；关键反例测试齐（`test_unknown_adopt_popup_stops_without_any_click` 等）；商店三道护栏与三锚点确认框。
- **不符合/缺证据**：购买确认框无一次实机成功记录，且 11-23 弹窗改版（绿按钮 y 从 801 到 921）的 `confirm_*_v2` 与 `purchase_modal_v2.png` 全部未提交；商店与结果页分支 6 次失败未复现修复（3 次 `timeout_shop`、1 次结果页关闭超时、2 次开框后四次未转场）；缺可购买行实跑「开框→确认→回商店」、已购灰态与可用按钮正向帧；确认框排他锚点 `shop_title` 曾于 11-16 被摘掉，本轮刚恢复但仅 479 帧离线复扫、未提交未实机；PC 未放行。
- **给后续 Agent 的下一步**：提交 v2 弹窗改版代码与两张候选模板，附复扫与排他锚点分数；复跑可购买行全链并留整屏帧与退出码；复现并修复开框后四次未转场，补 `timeout_shop` 回归用例；采集已购灰态与买满三次灰行收尾帧；重生成现状页并复算返工计数。
- **出处**：`games/epic7/modes.py:1648-1655`；`docs/SAFETY_MATRIX.md:26,98,145,171-199,356-358`；`docs/maintenance/pet_adoption.md:67-78,97-107,126-132`；`tests/test_pet_adoption.py:165,194,286,300`；`git diff -- games/epic7/evidence/pet_adoption.py`。

### 10. 活动剧情 `activity_story` — 45 / 试用

- **已具备**：契约五项齐并打开转场开关；观看故事页判据排他（`watch_story_title` 白掩膜本页 1.0000、全库天花板 0.6710），票券徽章只作辅助；战斗 CLEAR 复用支线模板并接入 `observe_battle`，有区分剧情关 CLEAR 的反向护栏；体力弹窗优先于页面判断并补齐落点。
- **不符合/缺证据**：主判据 `ticket_free` 模板未采到，终点靠「连续两次点完没往前走」启发式，该兜底被实跑改过两次；仅 3 张夹具，无完整收尾样本；安全矩阵第 34 行「无花资源动作」与代码 `_handle_stamina` 买生命之叶矛盾（`games/epic7/activity_story.py:425-438`）；契约 `overlays=()` 但体力弹窗线上多次挡路，口径待统一；PC 放行口径在现状页与安全矩阵冲突；非一次跑通。
- **给后续 Agent 的下一步**：采 `ticket_free` 正例帧（`run` 已在正常收工存 `activity_story_finished` 诊断）裁模板替换启发式终点判据；补带账号与客户端版本的完整收尾台账；统一 PC 放行口径；订正安全矩阵的危险动作行；复跑 `tests/test_epic7_activity_story.py` 全套。
- **出处**：`games/epic7/activity_story.py:25,37-52,200-204,425-438`；`games/epic7/modes.py:1291-1300`；`docs/SAFETY_MATRIX.md:34,95,330`；`docs/STATUS.md:22,102`；`docs/TODO.md:69`。

### 11. 社区签到 `community` — 45 / 待收口

- **已具备**：契约五项齐（`terminal=CLOSING`、`overlays={"web_network_error"}`）；竖屏层序、叠层优先级、数字字形读法、陌生页有界逃生梯有设计与测试；黑帧与未知页不点击、每动作出口验收、兑换灰按钮不蒙点等反例齐；11-24 08:09–08:14 有一次完整闭环（退出码 0，签到 + 两条任务 + 4 件兑换）。
- **不符合/缺证据**：11-23/24 大批修复仍是未提交工作区改动（`community.py` +421 行、`community_pages.py` +79、测试 +245、`core/portrait.py` +36、新增图片），只能记待收口；竖屏取图曾走 `shell screencap -p` 加 `adb pull`，Windows 路径被 `shlex.split` 吃掉反斜杠，程序长期读旧截图、日志描述不存在的页面，11-24 才改 `exec-out`，11-22 那条「实跑」因此不成立；跨天坐标、滑动距离与兑换落点未复验；延迟签到弹窗、确认按钮禁用或不存在、空白或加载页真机帧缺；PC 未放行、开局接力只登记不实现。
- **给后续 Agent 的下一步**：提交取图与签到、退场链修复并附回归用例；在修复后的代码上重跑完整闭环，留签到、两条任务、4 件兑换与回大厅原始帧；跨天复验任务坐标、滑动距离与兑换落点；补延迟弹窗与按钮禁用真机帧；建台账并复算返工计数。
- **出处**：`games/epic7/modes.py:1897-1905,683-692`；`docs/SAFETY_MATRIX.md:40,96,335`；`docs/maintenance/community_checkin.md:11,29-44,52`；`docs/TODO.md:45`；`git diff -- core/portrait.py`、`git diff -- games/epic7/community.py`。

### 12. 月塔 `tower` — 41 / 试用

- **已具备**：契约五项齐（`terminal=CONQUERED`、空覆盖层显式）；冻结不补点护栏成对反向验证；终点只认标题、自动战斗强弱证据收口、体力三颗 AND、FAILED 并入「打完」均有反例理由；1 轮打通一层（PC 11-03）且一次跑通。
- **不符合/缺证据**：25 层未跑满、连续两轮未跑，只有部分闭环；阶段选择屏缺判据（每月首次进场那页认不出）；体力不足入口变化帧与 PC 顶层 `result_clear` 缺；原「19 次正常闭环」已撤回（正常 3、异常 16、收尾失败 13、按 P 17）；含赛季文案入口模板待复核；体力购买护栏仅离线用例；7 次修正超预算；无逐启动台账。
- **给后续 Agent 的下一步**：采阶段选择屏、体力入口变化帧与 PC `result_clear` 整帧补判据反例；跑满 25 层一轮加连续两轮并记台账；对赛季文案入口模板做全库反扫；用带运行 ID 的日志重算收尾字段，不复用已撤回闭环；为体力购买补一条独立实机证据。
- **出处**：`games/epic7/modes.py:1000-1011`；`docs/SAFETY_MATRIX.md:25,67,84,325`；`docs/maintenance/tower.md:27,33-44`；`docs/TODO.md:41`；`tests/test_epic7_tower.py`。

### 13. 月光剧场 `moonlight_theater` — 39 / 试用

- **已具备**：契约五项齐、手册六节齐全，危险边界写明金币购票明令禁止、花券允许；12 个动作带来源/目标，`TransitionExitTests` 反向验证落点写全；三道购票防线、两个门票弹窗靠标题区分、购买弹窗只点取消；判据可证伪（进行观览走白掩膜、橙点模板或 HSV 双判据、战斗 HUD 三锚投票）。
- **不符合/缺证据**：金币购票弹窗整帧（报价、滑杆、购买按钮）缺真机素材，危险分支只有离线测试；6 次修正超预算且非一次跑通；实机仅第 1 幕，收尾失败 7 次，原「22 次正常闭环」已撤回；第 1 幕以外关卡与结算、PC 三选一、票耗尽页缺；战斗判据三锚含血量数字与角色头像等会变内容，换队伍可能只剩一票；干跑记录为警告。
- **给后续 Agent 的下一步**：采金币购票弹窗整帧并验证「只点取消」在同帧成立；采第 1 幕以外关卡、结算与票耗尽页真机帧；补不同队伍战斗 HUD 样本，收敛到固定 UI 锚点；在 PC 上跑三选一与完整一幕闭环并记台账；复验「往右换不动」终点判据的真机回执。
- **出处**：`games/epic7/modes.py:1143-1152`；`docs/SAFETY_MATRIX.md:32,93,336`；`docs/TODO.md:18,67`；`tests/test_moonlight_theater.py`；`docs/maintenance/moonlight_theater.md:46`。

### 14. 骑士团捐赠 `knights_donation` — 39 / 不可声称稳定

- **已具备**：契约五项齐；第一条打开机器强制转场的路线，12 个动作逐条对账表写在模块 docstring，`test_every_reachable_action_carries_the_transition_contract` 与 Runner 级盲点拒绝测试双向钉住；不可逆护栏完整（持有不足跳过、本人行靠 `required is None` 识别、请求支援每天一次、支援上限读整串、认不出 fail-open）；全局守卫抢奖励弹窗事故已修为关本路线开关并有反向测试。
- **不符合/缺证据**：`activity_panel` 兜底分支仅离线用例、无实拍证据；PC「花格被选中」帧缺，里程碑档位、薄弱数字、同串对照帧缺；2 轮实机仅 11-02 一天额度、历史放行（单轮）；无台账；8 次修正超预算，`_at_resource_support` 被 8 个提交改过；支援送材料不可撤回缺 PC 真机同帧确认证据；历史上两次事故都发生在状态机与主循环之间，Runner 护栏曾失效。
- **给后续 Agent 的下一步**：采 PC `flower_cell_selected` 帧校验匹配分后归档并复验降级分支；补里程碑档位、薄弱数字与同串对照帧跑反扫；为 `activity_panel` 补实拍正例并升级为现场帧回放；补 2 轮独立启动并建台账；对 8 次超预算出熔断重做计划。
- **出处**：`games/epic7/modes.py:1380-1441`；`games/epic7/knights_donation.py`；`tests/test_knights_donation.py`；`docs/SAFETY_MATRIX.md:36`；`docs/TODO.md`；`docs/maintenance/knights_donation.md:31-49`。

### 15. 英雄合成 `hero_synthesis` — 36 / 不可声称稳定

- **已具备**：契约五项齐且欠债名单为空；转场契约开关加 AST 静态守与 `TransitionContractSwitchTests`，12 个同页动作用 `in_page_evidence`（槽位数与材料行，纯色块统计）；危险护栏成体系（SSS 多候选多尺度保护、覆盖层盖住材料宁可不点、`TransmitPhase` 单向推进、判据沉默打心跳）；34 张夹具与静帧、两像素抖动、中心人像动画不确认切换等反向反例。
- **不符合/缺证据**：56 次修正远超 3 次预算且非一次跑通，为全库最高；传送奖励层与合成结果覆盖层模拟器真机帧缺（11-06 曾因守卫 3 秒点掉传送奖励层致 47 秒超时）；实机仅历史单轮、收尾失败 9 次、PC 免安装版未验；多轮同外观副本切换与退出 SSS 传送未验证。
- **给后续 Agent 的下一步**：采集模拟器侧传送奖励层与合成结果覆盖层真机帧并归入夹具；复验 SSS 副本多轮切换与退出 SSS 传送事务回执；补含客户端版本、账号代号、两帧回执与终点的台账；在 PC 免安装版跑一轮合成加传送闭环；再跑 `report_rework` 确认返工计数未增长。
- **出处**：`games/epic7/modes.py:1161-1167,1190-1198`；`docs/SAFETY_MATRIX.md:19,327`；`docs/TODO.md:47,65`；`tests/test_hero_synthesis.py`；`docs/howto/route_change.md:19,225-226`。

### 16. 支线故事 `side_story` — 36 / 试用

- **已具备**：契约五项齐；7 个自有动作加主线动作全带来源/目标，有 `SideStoryBattleObservationTests` 与 `SideStoryClearRulerTests`；CLEAR 字标带加白掩膜间隔 0.77、据点与普通场景靠状态制、活动与普通条目靠横坐标分；11-12 模拟器整条连打一轮且一次跑通。
- **不符合/缺证据**：PC 特殊链路未走到（期次主页、BOSS 难度、两据点、刷新倒计时帧）；场景页接力中据点与普通场景外观相同、依赖 `_segment` 可能把局部结束当全路线结束；场景页气泡与次数自证证据缺；地图容差、拖动量与 BOSS 中级行选中态待复验；`lobby_side_story.png` 焊了会变的 EVENT 标，11-22 白字候选已撤回且仍无无标真实大厅帧；正常字段未逐段对业务、无台账；7 次修正超预算。
- **给后续 Agent 的下一步**：采场景页气泡与次数整帧替代 `_segment` 作段位自证并补反例；PC 按顺序复验期次主页到 BOSS、难度与两据点并采倒计时回归帧；补无 EVENT 标大厅真机帧并全库反扫；按验收文档第 5 节建一条正常闭环台账；把地图容差、拖动量与 BOSS 中级行选中态做成可失败回归用例。
- **出处**：`games/epic7/modes.py:1099-1107`；`docs/SAFETY_MATRIX.md:31,94,133,328`；`docs/maintenance/side_story.md:51-91`；`docs/TODO.md:38,39,66`；`docs/TRANSITION_CONTRACTS.md:39,330,391`；`tests/test_epic7_side_story.py:285,386`。

### 17. 装备制作 `craft_equipment` — 35 / 试用

- **已具备**：契约五项齐，含 `overlays=frozenset({"equipment_bag_full"})`；三道闩锁与两种确认弹窗靠正文区分（出售蓝「确认」与萃取绿「萃取」同位置）；11-17 多分支多轮实机（不整理 2 轮 20 件、出售 2 轮、萃取 2 轮、10 轮 100 件两次、20 轮 200 件），多数退出码 0；背包已满走全局弹窗与 `EquipmentBagFull`（退出码 2），11-18 按真机帧重做并实跑通过。
- **不符合/缺证据**：11-17 22:01:32 完成 20 件并出售后连按两次 ESC 仍停在 `craft_home`，未复现修复、无回归用例；安全矩阵第 28 行的测试引用不成立——`tests/test_safety_fail_closed.py` 的 `RESOURCE_ROUTES` 不含本路线，黑帧不点击与缺模板装配失败两道跨路线护栏未生效；金币不足与材料不足无真机帧；离线护栏仅 6 条，无闩锁二次点击与收尾失败专门用例；8 次独立启动中 1 次入场异常、1 次收尾失败，集中在同一天同环境；PC 未放行、无台账。
- **给后续 Agent 的下一步**：复现 22:01:32 收尾失败，按帧核对输入通道并补回归用例；把 `craft_equipment` 加入 `test_safety_fail_closed.py` 的 `RESOURCE_ROUTES`，或订正安全矩阵的测试引用；采金币不足与材料不足整帧并补反向用例；补 PC 正式入口与整理、出售、萃取分支取证；建台账并复跑一次完整闭环。
- **出处**：`games/epic7/modes.py:1737-1744`；`docs/SAFETY_MATRIX.md:28,100,144,154-169,353-355`；`docs/maintenance/craft_equipment.md:64-79,111-121`；`tests/test_epic7_craft_equipment.py:36-133`；`tests/test_safety_fail_closed.py:48-70`；`docs/TODO.md:22-23`。

### 18. 主线 `story` — 30 / 历史放行

- **已具备**：契约五项齐（`terminal=STAGE`、6 类 overlays）；`StoryAction.source_page`/`target_pages` 无默认值必填、漏填直接 `TypeError`；关键判据走白掩膜找形状、PC 差异单独留口不改公共层，有双锚点与反向护栏；1 轮 11-01 PC 完整、2 轮 11-06 批量、异常恢复均有记录。
- **不符合/缺证据**：24 次修正超预算；无逐启动台账（正常 18、异常 29、收尾失败 23、按 P 596，正常字段未逐段对业务，按 P 不能当成功样本）；变体全局通知窗真机正例缺；PC 批量与 Episode 4 第 11 关解锁弹窗未复验；多轮闭环与日志轮次一致性待核；跳过剧情改自有结构性判据，需确认反例覆盖；`tests/test_main_story.py` 有 1 行未提交注释改动。
- **给后续 Agent 的下一步**：补一条模拟器与一条 PC 的独立启动台账（含回执行号、消耗、终点）；采变体全局通知窗真机正例并跑全库反扫；复跑 PC 每日批量逐段核对 Episode 4 弹窗；用带运行 ID 的日志核对来源、目标、转场与轮次一致性并重算闭环分母；先提交注释改动恢复干净工作区。
- **出处**：`games/epic7/modes.py:853-871,749-753`；`docs/SAFETY_MATRIX.md:23,81,322`；`docs/maintenance/story.md:29-35`；`docs/TODO.md:36,61`；`docs/TRANSITION_CONTRACTS.md:389`。

### 19. 成就领取 `achievement` — 27 / 试用

- **已具备**：契约五项齐并打开转场开关，`claim-all`、`claim-effect-upgrade`、`switch-class` 分别声明允许页面或 in_page_evidence；逐分类确认口径有决策记录 0007 与三条测试；弹窗先于成就页判、亮灰靠绿像素占比（亮 0.2643、灰 0.0000）、全黑帧 fail-closed；唯一有干跑记录（11-09）的路线，1 轮与 2 轮均有记录。
- **不符合/缺证据**：模拟器缺 `effect_upgrade` 金色按钮与 `popup_close_effect` 效果升级弹窗正例，共享层临时使用 PC 图；无台账，正常字段 28 未逐段对业务与后端，账号未记录；3 次修正虽在预算内但非一次跑通；收工靠帧键 MD5 缓存与分类清单，属自有机制而非基类转场验收；效果升级到剧情淡入有 2 至 3 秒 `observe_page` 返回 None、日志打 `UnrecognizedScreen`，靠两帧机制吸收；独立启动边界未记录。
- **给后续 Agent 的下一步**：在模拟器采 `effect_upgrade` 与 `popup_close_effect` 正例替换临时 PC 图并补反向护栏；补 2 轮独立启动边界记录与台账；为效果升级分支补实机回执（跳过剧情、关升级弹窗、回成就页）；记录账号代号与客户端版本；复核 3 次修正落点确认未触及同一锚点第二次修补。
- **出处**：`games/epic7/achievement.py` 模块 docstring 与 `build_achievement_templates:101-121`；`games/epic7/modes.py:1601-1610`；`tests/test_achievement.py`；`docs/SAFETY_MATRIX.md:39`；`docs/decisions/0007-achievement-done-per-class.md`。

### 20. 企鹅批量购买 `penguin_purchase` — 22 / 试用

- **已具备**：契约五项齐（`terminal=成长祭坛`、`finish_at_home=True`）；购买四锚点加数量与报价配对（1/50 认 102、50/50 认 5100），后三列与宠物商店反例帧齐；11-15 完整一轮与连续两轮实机退出码 0，含半路接力；购买与关闭各一道单击闩锁、接力不落扣费页。
- **不符合/缺证据**：红叶不足与「购买货币」提示无真机帧，按未登记页面安全停止；PC 未放行、无 PC 页面帧；无台账，账号与客户端版本未记录；11-15 的 20 轮实跑曾因轮数上限写在状态机（10）与次数框（20）两处而提前收工并 45 秒超时，已修但说明上限曾不自洽；独立启动仅正常 4、异常后回首页 1，且跨提交未归并。
- **给后续 Agent 的下一步**：采红叶不足与购买货币提示整帧并补反向用例；补 PC 页面取证与实机验收，或维持未放行；建台账写明客户端版本、账号代号与每次启动边界；复跑一轮 50/50 扣费并核对红叶流水 5100；保持返工在预算内，避免再出现轮数双上限。
- **出处**：`games/epic7/modes.py:1690-1697,1672-1673`；`docs/SAFETY_MATRIX.md:27,99,338,340-346`；`docs/maintenance/penguin_purchase.md:37-46,70-90`；`tests/test_epic7_penguin_purchase.py:114,206,211,224,247,261,279`。

### 21. 圣域收菜 `sanctuary` — 18 / 试用

- **已具备**：契约五项齐；4 个动作逐条对账表，`claim-row` 用领取完成弹窗出现当出口证据、点不动 4 次后响亮失败，`care` 走 in_page_evidence 并有下一帧重判兜底；判据反例齐且有量化余量（灰态照料不点、绝对亮度误判、行按 y 排序、弹窗先判）；弹窗不自消必须自己点掉有测试钉住；3 次修正、一次跑通、在预算内。
- **不符合/缺证据**：`care` 的「按钮由亮转灰」机器未单独验证，靠下一帧重判代替；只覆盖精灵之森一行，其余圣域页面、第三材料行可领奖、白天冷却、更多亮态照料帧缺；PC 领奖完成弹窗支路无实跑；无台账，「连跑三轮」是同一次启动内的业务轮次，按口径只算一个独立样本；「点照料没有弹窗」是用户判断、尚未实点；大厅入口带红点帧缺。
- **给后续 Agent 的下一步**：补 PC 领奖弹窗支路实跑并建台账；采大厅入口带红点、第三材料行可领奖与白天冷却帧扩变体矩阵；实点核对照料是否弹窗并记录；为 `care` 亮转灰补一条独立反向断言（灰帧不得产生点击）；把连跑三轮拆成多次独立启动，按启动边界重算闭环样本。
- **出处**：`games/epic7/sanctuary.py:40-66`；`games/epic7/modes.py:1555-1564`；`tests/test_sanctuary.py`；`docs/SAFETY_MATRIX.md:38`；`docs/TODO.md`。

## 四、给后续 Agent 的施工顺序

1. **先收口四条待收口路线**：竞技场、世界首领战、宠物领养、社区签到。它们的改动改变判据或收工语义，先提交或回退，重跑对应用例，再谈其他补证。
2. **再处理七条不可声称稳定**：优先狗粮（动作完全无回执、手册缺失）、刷书签（付费扣款未对账）、远征（无正常闭环）、迷宫强化石与主线补星（关键反例与危险支路缺证）、骑士团捐赠、英雄合成。
3. **然后处理九条试用**：每条先补台账与独立启动边界，再按各自缺口补真机帧与 PC 证据。
4. **最后统一全局项**：建真实台账目录与格式、订正两处声明与代码不一致、统一 `activity_story` 的 PC 口径、补两份缺失手册。
5. 每条路线施工前先跑 `python -m auto_game_unified.tools.report_rework` 复算预算；
   超预算路线按 `docs/howto/route_change.md` 第 4 节出熔断重做计划，未经用户拍板不改业务规则、判据与阈值。
