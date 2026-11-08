# 英雄合成视觉维护

英雄合成视觉证据入口：`games/epic7/evidence/hero_synthesis.py`。

模板位于 `games/epic7/templates/hero/` 与 `games/epic7/templates/navigation/`。改版时按诊断中的键名替换模板；位置变化改 `REGIONS`，分数变化改 `THRESHOLDS`。

以下内容不能通过修改视觉阈值绕过：SSS 优先级、材料安全、相邻同名副本、合成结果、传送结果和不可逆事务。它们仍由 `games/epic7/hero_synthesis.py` 的业务状态机决定。

运行时的 `rating_sss`、`sss_material`、筛选、SSS 警告、合成结果和传送结果已直接读取上述 profile，不再维护第二套区域或阈值。失败时查看原 `*.png` 同名目录内的 `evidence.json`；低于阈值仍保留实际 `score`，`config` 指向应修改的证据文件。当前命令行检查器未注册英雄合成，修改后运行英雄证据与完整合成回归。

## 英雄刻印已满：底部那条黄条是**业务结论**，不是识别故障（2026-11-08 修）

### 现象

```
模式=英雄合成 刻印页等待（判据没出货） 完整页面=0 绿色按钮=0 槽位结构=1
已填槽位=1 费用非零=0 Up材料=未识别 材料卡=card
```

每 10 秒一行、连续 5 分钟（08:51~08:56），留下 50 多张同状态诊断帧，汇总里一个 `✗`。

### 根因

画面底部一直挂着一条黄条：**「英雄 已达最高献身技能级别，无法继续刻印记忆。」**
意思是这个英雄的献身技能已经满级、**不能再刻印**。而当时两条逃生门都不开：

| 逃生门 | 条件 | 实际 |
|---|---|---|
| 合成 | `绿色按钮存在` + `完整页面` | 绿按钮**不在**（本来就不能合成）⇒ 恒 0 |
| 换英雄 | 绿按钮不在 + **既没有 Up 卡也没有材料卡** | **材料卡认得出**（`材料卡=card`）⇒ 不成立 |

⇒ 只能 `return None` 干等到超时。`_IMPRINT_ADD_NO_PROGRESS_LIMIT` 那条也救不了：
它要求「点了加材料、槽位没变」，而这里**根本没发出点击**。

### 修法：补一颗判据，命中就换下一个英雄

1. `templates/hero/pc/imprint_max_level_notice.png`（545×66），裁自 11-08 08:56 现场帧，
   **只含那句提示文字**（右侧背景按钮「记忆」已排除在裁框外）。
2. `HeroTemplates.imprint_max_level_notice` 是**可选字段**（`hero/pc/` 无图即 None）——
   不能塞进证据画像：`_assert_anchor_templates` 会判「判据锚点缺模板」直接起不来。
3. 在「`IMPRINT_ADD` 且页面不完整」这一支的**最前面**判它，命中就 `back_to_list`。

裁框 `(688, 1010, 545, 66)`、阈值 `0.80`，两者都是状态机常量
（`_MAX_LEVEL_NOTICE_REGION` / `_MAX_LEVEL_NOTICE_THRESHOLD`），来历见下。

### 实测读数（`runtime_logs/_hero_build_notice.py`）

| 项 | 结果 |
|---|---|
| 正例（11-08 那批同状态帧 29 张） | **全部 1.0000** |
| 反例（全库 1483 张，含英雄列表/传送页/其它路线） | **最高 0.4091**，过阈 0 张 |
| 阈值 0.80 两侧余量 | 0.20 / 0.39 |

### 怎么复核 / 重采

```bash
python auto_game_unified/runtime_logs/_hero_build_notice.py
```

它会把模板重新落盘（**同框同阈值**）并打印正例最低分与反例最高分。
换分辨率或换客户端后重跑；分数塌了先看是不是那句话的文案被游戏改了。

### 守它的测试

`tests/test_hero_synthesis_pc_notice.py`（5 条）：模板在且尺寸对 / 现场帧认得出 /
其它页面不许乱认 / **模拟器没有这颗判据（模板为 None、恒 False）** /
**判到就该发 `back_to_list`**（业务后果层面，防的正是那次空等）。

## 判据模板全部必需（2026-10-03）

**本路线没有「可选模板」。** 17 个判据锚点、**18 张**模板文件（`sss_material` 一锚点两张候选，
见下一节）缺一张就不该跑，三道关同时拦：

- **加载期**：`hero_synthesis.build_hero_templates()` 直接 `load_template`（不再写
  `if path.exists() else None`）⇒ 缺文件当场 `FileNotFoundError`，开跑前起不来。
- **构造期**：`HeroSynthStateMachine._assert_anchor_templates()` ⇒ `ValueError` 并点名锚点。
- **证据校验**：`evidence/common.validate_profile()`，全部 `required=True` ⇒ 报「模板不存在」。
- **护栏测试**：`tests/test_hero_synthesis.py::GuardTests::
  test_every_judgement_anchor_refuses_a_missing_template`，每个锚点轮流置 `None` 都必须被拦。

为什么这么严：其中 9 张**曾经是可选的**，缺一张的后果分三档 ——

| 缺失的模板 | 后果 | 性质 |
| --- | --- | --- |
| `sss_material` | 判 `UNKNOWN`、不点任何卡 | fail-closed，还有救 |
| `filter_attribute_label` / `filter_star3_unselected` | 筛选面板永远认不出，反复点漏斗直到超时 | 卡死（不点错） |
| `sss_material_warning_*` / `imprint_result_*` / `transmit_reward_*` | 覆盖层判据缺失 ⇒ `_xxx_present()` 返回 `False` ⇒「覆盖层必须先关掉」**静默失效** | **fail-open，可能点到覆盖层底下的材料卡** |

最后一档是加严的真正原因：合成**消耗材料、不可逆**，而「判据没了」不会在日志里留下任何异常。

⇒ 加/改模板时，`evidence/hero_synthesis.py` 的 `_TEMPLATE_PATHS` / `REGIONS` / `THRESHOLDS`
与 `hero_synthesis.py::HeroTemplates` 要一起改；**别再加可选模板**。

## 「SSS 材料」徽记：多候选 × 多尺度（2026-10-04）

`sss_material` 是**唯一一个「一锚点、多长相」**的判据，也是**唯一一个需要多尺度扫描**的
判据。两件事解决的是同一类问题：**这枚徽记在页面上不长一个样**。

### 一、多候选：两种画法

候选登记在 `evidence/hero_synthesis.py::SSS_MATERIAL_ALT_TEMPLATES`（机制同大厅
「秘密商店」入口 `lobby_shop_entry` 的 `alt_template_paths`）：

| 画法 | 模板 | 什么时候出现 |
| --- | --- | --- |
| 原尺寸 | `hero/sss_material.png` | 徽记在**前排那张展开的大卡**上 |
| ~90% | `hero/sss_material_behind_card.png` | 徽记在**后排被压暗的小卡**上（整张卡连同徽记一起被缩小） |

判定语义：**任一候选过阈即算命中**，取过阈候选里的最高分。

### 二、多尺度：补模板补不完（2026-10-04 08:36 现场查明的）

⚠️ **曾经以为「两种画法」就是全部、补了候选模板就完事 —— 这是错的。**

同一枚徽记被画成多大，取决于它**排在材料列表第几位**，而列表里有几张材料是动态的。
已实测到的核心宽有三档：

| 徽记核心宽 | 相对模板 | 现场 |
| --- | --- | --- |
| 56 | 1.00 | 展开的大卡（模板原始尺寸） |
| 50 | 0.90 | 后排被压暗的小卡（10-03 / 10-04 07:22） |
| 45 | 0.80 | 列表第三张、最小（10-04 08:36） |

只按 1.00 倍匹配时，45 档量到 **0.5928** —— 又一次「落进 0.55~0.80 死区 ⇒ 判据沉默」：
`next_action()` 返回 None、日志一行不出、**刻印页干等 90 秒超时**（`timeout_imprint_add`）。
10-03 那批的 0.5957 与这次的 0.5928 **不是同一个数**，是**两档不同尺寸**碰巧落进同一条死带。

**排除了「卡片被压暗 / 变灰」这条直觉**（对 10-03 源帧做变换，源帧基线 1.0000）：

| 变换 | 分数 |
| --- | --- |
| 亮度 ×0.45（变暗） | 0.9987 —— 几乎不动 |
| 去饱和 50%（变灰） | 0.9691 |
| **整区缩到 0.80（尺寸）** | **0.2425 —— 就是它** |

`TM_CCOEFF_NORMED` 对**整体乘性亮度**不变，所以「压暗」在数学上不可能解释掉分。

判据因此改成 **候选模板 × 尺度档位**逐对匹配取最高分，档位是
`HeroSynthStateMachine._SSS_TEMPLATE_SCALES = (1.00, 0.95, 0.90, 0.85, 0.80, 0.75)`。
范围**只向下扩**：所有已实测帧的最佳档都 ≤ 1.00，没有更大的画法。

### 三、为什么不做「落死区才展开」的省时优化

2 候选 × 6 档 = 12 次匹配，实测**约 100ms/次**（单尺度 15ms）。主循环是秒级节奏，可以接受。
这是**刻意的取舍**：不做「先按 1.00 倍量一次、落死区才展开多尺度」—— 那样会在
「1.00 倍量到 ≤0.55（判 NON_SSS）、换个尺度其实过阈」时**漏判**，而漏判 NON_SSS 会让
SSS 材料卡被 `_find_up_card` 当成普通材料**点下去**（合成消耗材料，不可逆）。宁可慢，不可漏。

### 四、死区必须出声：刻印页等待心跳

多尺度救的是**已知档位**；万一还有更小的档落进死区，**绝不能再让日志空白 90 秒**。
`_stable_next_action()` 现在对 `IMPRINT_ADD` 页每 **10 秒**打一行
`刻印页等待（判据没出货）… SSS页评级=… SSS最高分=…`。依据由 `_log_imprint_add_evidence()`
统一产出，和「刻印页超时」**共用同一份**，不重复写两遍。

2026-10-04 08:36 现场之所以难查，就是因为 08:34:30 进页到 08:36:02 超时之间**一行都没有** ——
判据落死区后 `next_action()` 返回 None，而 None 在这条路径上**不打分、不报警**。
有了心跳，`SSS页评级=unknown` 10 秒内就能看见，不用事后翻现场帧。

护栏 `test_imprint_add_wait_emits_a_ten_second_heartbeat`：把档位收成 `(1.00,)` 造出死区，
断言依据进了日志 + 10 秒节流。反向验证过 —— 删掉心跳调用它立刻红。

#### 首次进入等待时留一张现场帧（2026-10-04）

心跳解决「**当场看得见**」，但事后复盘还要能**回放**。所以两个等待分支
（`IMPRINT_ADD` / `IMPRINT_ABORTING`）在**首次**进入等待时各存一张：
`imprint_add_judgement_silent` / `imprint_abort_wait_silent`。

为什么必须存：**判据沉默的形态是「什么都不做」** —— 它不会走到任何超时分支，只要沉默
发生在「重试 4 次」的**正常路径**上（如转场验收），就**一张图都不会留**。08:36 那次能挖出
0.593 纯属侥幸，它恰好超时了。`save_diagnostic()` 自带裁剪（`diagnostic_limit`），
只存首帧不会淹掉磁盘。

⚠️ **存帧失败绝不许打断主循环**（`_save_wait_frame()`）：诊断目录没配、写盘失败 ⇒ 记一行日志
跳过。判据沉默本身已经是故障了，不能因为「想留证据」再雪上加霜。
（先例：`_log_card_switch_diagnostics` 里「未配置诊断目录」早退。）

护栏 `test_silent_wait_saves_a_frame_once_and_survives_a_disk_failure`：跨多轮等待只留
**一**张；诊断目录未配时静默跳过。**反向验证两半都做过** —— 去掉存帧 ⇒ 红在「实际 []」；
去掉容错 ⇒ 红在 `RuntimeError` 穿透。

### 五、夹具与回归测试

现场夹具都在 `tests/fixtures/epic7_hero/`：

- `imprint_sss_material_behind_card_20261003.png` —— 候选模板**源**帧（50 档）
- `imprint_sss_material_behind_card_20261004.png` —— **跨帧验收**帧（50 档）
- `imprint_sss_material_small_card_20261004.png` —— 45 档现场（08:36 卡死那次）

| 测试 | 锁的是什么 |
| --- | --- |
| `test_small_card_sss_material_is_recognized_by_multiscale` | 现场复现；**同时断言「1.00 倍确实量不到」**，否则退化回单尺度它照样绿 |
| `test_every_known_badge_size_is_recognized` | 全部已知档位（56 / 50 / 45）一起兜底 |
| `test_multiscale_does_not_push_negative_pages_into_sss` | 材料页 6 张负样本 + **传送页生产口径**都不许被推进 SSS |
| `GuardTests::test_an_emptied_scale_set_stops_recognizing_the_small_badge` | 把档位收成 `(1.00,)` ⇒ 必须量不到（证明「能认**是因为**多尺度」） |
| `GuardTests::test_sss_template_scales_cover_the_base_size_and_stay_in_range` | 档位非空、含 1.00、落在 (0,1]、从大到小 |

⚠️ 断言必须写到**依据**（分数 / 分类）：这条路径**降级时照样返回 None 而不报错**，只断言
「动作对不对」抓不住它。做过反向验证：把 `_SSS_TEMPLATE_SCALES` 收成 `(1.00,)`，测试精确红在
**0.5928**（就是现场日志里那个 0.593），并点出是哪个档位掉的。

### 六、候选模板同样必需

候选模板与主模板**同等必需**，四道关都盯它：

- 加载期 `load_template` 缺文件即 `FileNotFoundError`（带完整路径）；
- 构造期 `value is None or (isinstance(value, tuple) and not value)` ⇒ **空元组也拦**
  （护栏 `GuardTests::test_sss_material_candidate_group_refuses_an_empty_tuple`）；
- `validate_profile()` **会**检查 `alt_template_paths` —— 2026-10-04 补的：此前只查主模板，
  候选模板被删时它一声不吭（`tests/test_hero_evidence.py::
  test_hero_profile_reports_a_missing_candidate_template`）；
- 口径一致由 `TemplateTests::test_sss_material_candidates_match_the_evidence_profile`
  钉住（数量 + 文件名 + 像素三重比对），防「画像说两张、加载器只读一张」。

### 七、⚠️ 验证传送页的两个坑

传送页 `_classify_transmit_target()` 走的是**同一个** `_material_sss_score`，只是区域换成
`(1500, y-70, 480, 140)`：

1. **必须走生产口径**（`_transmit_target_card()` 定出的真实卡片 y）。本次两张传送夹具的
   真实 `card_y` 都是 498 ⇒ 多尺度后 `transmit_select` 0.4124 / `transmit_selected` 0.3982，
   仍是 NON_SSS，**零误判**。
2. **别用「穷举 y」的最坏情况扫描下结论**：那会把区域挪到能蹭到别处内容的位置，量出
   `transmit_select` 0.9388 / `transmit_selected` 0.9602 的**假误判**。实测确认过：
   `transmit_select` 上 y=674 处**确实有一枚真徽记**（不是蹭分），但它不在当前高亮行内 ——
   生产设计本来就「只检查当前高亮行，禁止把其它列表卡的 SSS 当成目标」，所以不受影响。

### 八、转场验收不许依赖「这一帧认出动作」（2026-10-04）

#### 原来错在哪

`_material_transition_completed()` 判「材料进槽了没有」，比的是点击**前后**的
`slots=N;rows=…`。问题在**值从哪来** —— 它只从**动作对象**（`current_action.source_observation`）取。

而这一帧若判据沉默（SSS 徽记落死区 ⇒ `next_action()` 返回 `None`），就**生不出动作** ⇒
值取不到 ⇒ `_parse_material_observation(None)` 返回 `None` ⇒ **转场永远判不出成功** ⇒
一路重试到超时。**这是 2026-10-04 07:22 那次卡死的另一半原因**（第一半是多尺度修掉的判据沉默）。

#### 其他路线为什么没这个问题

`runner_base._transition_completed()` 的**默认实现根本不看动作对象** —— 它只比
**页面身份**（`confirmed_page ∈ target_pages`）：

```python
if not confirmed_page or confirmed_page not in previous_action.target_pages:
    return False          # 停在哪一页，跟「认出什么动作」无关
```

只有英雄合成绕了一道，因为「材料进槽」不是翻页、是**同页内容变化**，所以它需要另找依据。
方向没错，错在**取值的通道绑在了动作对象上**。

#### 修法：机器每帧现算，与判据解耦

- `next_action()` 第 6 段（`if complete_imprint_page:` 进段后**立刻**）把当前帧的观察值
  写进 `self._current_material_observation`，**不管后面走哪个分支**（含各条 `return None`）。
- `_material_transition_completed()`：**优先取动作对象**（正常路径口径一字不改），
  取不到才回落到 `self.machine._current_material_observation`。
- 两条通道解析走**同一个** `_parse_observation_text()`，防口径漂移。

⚠️ 之所以能这么修：`_imprint_filled_slot_count()` / `_ordinary_up_rows()` 是**纯色块统计，
不依赖任何判据模板** —— 判据全沉默时它照样算得出真值。真机夹具实测（12 张 `imprint*.png`）：

| 夹具 | 现算观察值 | 判据 |
| --- | --- | --- |
| `imprint_sss_material_small_card_20261004`（08:36 沉默现场） | `slots=0;rows=` | `sss` |
| `imprint_sss_material` | `slots=0;rows=578` | `sss` |
| `imprint_added`（材料已进槽） | `slots=1;rows=` | `non_sss` |
| `imprint_up_cards_no_sss` | `slots=0;rows=473,579` | `non_sss` |

判据与观察值**两条独立通道都能出货**，这正是修复成立的前提。

#### 测试（含反向验证）

- `test_material_transition_survives_a_silent_next_frame`：`current_action=None` 下四种情形
  —— 没算出来 ⇒ 判不出；槽位 0→1 ⇒ 必须成功；槽位没变 ⇒ 判不出；旧行消失 ⇒ 成功。
- `test_material_transition_does_not_downgrade_when_action_is_present`：动作对象在时
  **仍以它为准**（现算值说变了、动作对象说没变 ⇒ 必须判不出），防新兜底把口径放宽。
- **反向验证**：移除兜底分支 ⇒ `survives_a_silent` 精确红在「槽位变了却判不出」。恢复后全绿。

### 九、打开转场契约开关（2026-10-04 第五个）

#### 为什么不能「直接打开」

`HeroSynthRunner._REQUIRE_TRANSITION_CONTRACT` 读的是基类 `RouteAction.in_page_evidence`，
而英雄合成的同页证据当时叫**自造的** `source_observation`。**名字不齐时，开关开着也管不到
那 12 个 `material_change` 同页动作** —— 它们的 `target_pages` 里塞了当前页（`刻印加材料`），
检查「`target_pages` 或 `in_page_evidence`」时被前者满足 ⇒ **形式合规、实质没用**：
本页永远在集合里，分不出「点了没生效」和「点了生效了」。这正是「先对齐字段、再开开关」
必须分两步的原因。

#### 字段对齐（第一步）

| 位置 | 改动 |
| --- | --- |
| `hero_synthesis.py::HeroAction` | **删掉** `source_observation` 字段，改用基类 `RouteAction.in_page_evidence` |
| `hero_synthesis.py::_simulator_transition_action` | 参数名 `source_observation` → `in_page_evidence`（工厂统一入口） |
| `hero_synthesis.py` 全文 | 34 处引用改名（两行历史说明注释保留原字面，供追溯） |
| `runner_base.py::_source_observation_matches` | → `_in_page_evidence_matches`（**共享模块**，场外调用点同步） |
| `test_hero_synthesis.py` | 33 处（`=` / `.` / `"..."` 三种形态） |
| `test_route_actions.py` | 断言反转：自造字段只剩 `transition_kind` |

#### 打开开关（第二步）

```python
class HeroSynthRunner(ModeRunnerBase):
    _REQUIRE_TRANSITION_CONTRACT = True
```

同时 `modes.TRANSITION_EXEMPT` **删掉 `hero_synthesis` 整条** —— 开关与豁免是二选一，
两边都留着，加载期自查 `_assert_transition_stance_declared()` 会报「既没打开也不在豁免里」以外的
矛盾（留着豁免则等于声称「用自己的机制验收」，与事实不符）。

#### 三道关 + 反向验证

| 关 | 位置 | 反向验证结果 |
| --- | --- | --- |
| 加载期表态 | `modes._assert_transition_stance_declared()`，import 时执行 | 把开关改回 `False`（豁免已删）⇒ **连测试都收集不起来**，import 直接点名报「既没有打开 `_REQUIRE_TRANSITION_CONTRACT`，也不在 `TRANSITION_EXEMPT` 里」 |
| 发出前校验 | `ModeRunnerBase.run()` 里逐个动作校验 | 缺 `source_page` / `target_pages`+`in_page_evidence` 皆空 ⇒ 点名拒绝 |
| 护栏测试 | `test_hero_synthesis.py::TransitionContractSwitchTests` | 删掉一处同页动作的 `in_page_evidence=` ⇒ `test_material_actions_now_carry_in_page_evidence_on_real_fixtures` **精确点名** `add_material_0_2 是同页动作却没有 in_page_evidence`，12 个 subtest 红 |

**真机夹具实测**（对齐前后对比）：
- 对齐前：12 个同页动作 `in_page_evidence=''`（空）—— 全靠在 `target_pages` 里塞本页过检查。
- 对齐后：全部带 `in_page_evidence='slots=0;rows=473,579'` 这种真实依据 —— 从「形式合规」
  变成「真有依据」。

#### 一句话规矩

**打开某条路线的开关之前，先确认「路线自造的证据字段名」和「开关读的字段名」是不是同一个。**
不看这一步，开关只是变好看，拦不住任何东西。

---

## 英雄列表「刻印记忆」红点在 PC 静止态被漏判（2026-11-08 16:41）

### 现象

用户截图里「刻印记忆」按钮左上角那颗橙红点明明在，程序却直接翻卡了。同一轮日志：

```text
16:41:26 判断依据=当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=fb4cfee2
16:41:30 判断依据=当前英雄非SSS但刻印按钮无红点，跳过，详情指纹=d1051d78
16:41:34 判断依据=当前英雄非SSS且刻印按钮红点存在 → open_imprint（并成功合成）
```

「有时认得、有时不认」不是随机，也不是整条路线不会合成。

### 病因：几何口径按模拟器收紧，PC 的红点画得更大更靠外

`HeroVisionMixin._red_dot_present` 的口径（**按模拟器用户标框收紧**）：
`_REDDOT_ZONE=(1030,942,32,35)` + `is_centered_dot` 要求色块四周各留 3px、尺寸 10~28。

| 帧 | zone 内橙红 blob | 触框边 | 判据 |
| --- | --- | --- | --- |
| 模拟器 `list_reddot.png` | `(1038,949,18,19)` | 无 | **True** |
| PC `switch_before / final`（静止） | `(1030,942,26~29,26)` | 左 15~17 / 上 24~25 | **False** |
| PC `switch_departure`（动画） | `(1038,949,18,19)` | 无 | **True** |
| 用户 11-08 截图 | `(1030,942,25,28)` | 左 20 / 上 23 | **False** |

PC 静止态红点左边还有一条**同色橙棕斜带**（立绘边框装饰）与它连成一片，
把 boundingRect 撑到判据窗左上边界 ⇒ `local_x=0/local_y=0` ⇒ 3px 内缩规则否决。
翻卡动画中间那一瞬斜带分离、圆点缩回模拟器尺寸，才「碰巧」命中 ——
这就是日志里时好时坏的完整解释。

颜色**完全合格**：H 7~22 / S 120~255 / V 120~237，zone 内 364~503 个橙红像素。
所以这不是「PC 识别不稳定」，更不是业务逻辑变化；**是同一颗红点被模拟器的小窗口裁掉了**。

### 为什么不能靠调宽 zone / 加像素阈值

全库 2983 帧 HSV 审计：战斗、剧情、大厅页在同一坐标有整片暖色 UI
（zone 内橙红像素 900~1120），单纯加一条「像素够多就当有红点」必然误报；
放宽 zone 后斜带会一直跟着延伸（`(1024,936,44,47)` 时 blob 变成 `(1024,936,33,34)`，
仍然贴边），几何规则救不回来。

模板匹配才是能证伪的图形锚点。全库 2830 帧（生产宽高比）分数审计：

| 类别 | 分数 |
| --- | --- |
| PC 静止态正例（6 张真机 `switch_before/final`） | **0.9177 ~ 0.9525** |
| 用户截图（模板来源） | **1.0000** |
| PC 动画帧（原判据本来就认得，会短路） | 0.7665 ~ 0.8460 |
| 模拟器尺寸红点 / PC 观察帧真红点 | 0.6718 ~ 0.8063 |
| 非红点最高（其它路线帧） | 约 **0.5105** |

阈 **0.80**：正例余量 0.12，负例余量 0.29。

### 修法：PC-only，公共业务文件一个字节都不改

| 接触点 | 内容 |
| --- | --- |
| `games/epic7/hero_vision_pc.py` | **新增** PC-only 模块：加载判据图、包装状态机实例的 `_red_dot_present` |
| `games/epic7/templates/hero/pc/imprint_red_dot.png` | **新增** 28x28，裁自用户截图 `(1027,939,28,28)` |
| `games/epic7/modes.py::_build_hero_synthesis` | **唯一装配口**：`if is_pc(template_root): install_pc_red_dot_vision(machine, template_root)` |
| `tests/test_hero_synthesis_pc_reddot.py` | **新增** 18 条 + 12 subtest |
| `tests/test_template_paths.py` | PC 图白名单 +1 |
| `tests/fixtures/epic7_hero_pc/` | 3 张 PC 夹具（用户截图还原 / 真机 `switch_before` / 同轮刻印页负例） |

**没碰**：`hero_synthesis.py`、`hero_vision.py`、`_REDDOT_ZONE`、HSV 区间、
`is_centered_dot`、`build_hero_templates`、任何模拟器分支。

包装的是 `_red_dot_present` 而不是 `next_action`：两帧稳定确认、页面判定、SSS 保护、
动作契约全部原样复用。原判据为真时**直接短路**，PC 图只补漏。
判据图缺失直接抛 `FileNotFoundError`（fail closed），绝不静默降级成「没红点」。

### 取证与回归

- 可重跑探针：`runtime_logs/_probe_1108_reddot*.py`、`_probe_1108_reddot_audit.out`、
  `_probe_1108_reddot_template_audit.out`。
- 端到端基线：真机 `switch_before` 帧修复前 `next_card_*`、修复后 `open_imprint`。
- 反向验证（都还原真实旧行为，不是恒等式）：
  ① 把判据图换成无关图 ⇒ 6 条识别/端到端测试变红；
  ② 把 `if is_pc(...)` 改成 `if True:` ⇒ 模拟器隔离测试变红；恢复后全绿。
- 相关测试 **262 passed + 66 subtests**；按用户要求**没跑全量**。

### 还没过的两道门

代码跑通 ≠ 用户能用上：这次没重新打包、没改界面名单。英雄合成是既有 PC 路线，
要让新判据在免安装版里生效，还需要重新出打包产物。



