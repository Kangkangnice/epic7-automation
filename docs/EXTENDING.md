# 新增自动化路线指南

本指南面向后续接手的 Agent。新增路线时保持修改范围最小，不重构已通过实机验证的竞技场和主线模块。

## 0. 视觉证据维护入口

每条路线的模板、搜索区域、阈值和页面组合集中在 `games/epic7/evidence/` 下对应文件；业务状态机仍保留在路线模块中。界面改版时先根据诊断中的证据键名修改证据清单，不要先改状态机。

检查当前完整截图（只读，不会修改模板）：

```powershell
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png
```

证据清单中的搜索区域允许延伸到画面底部或右侧边缘，因为现有 matcher 会裁剪截图；区域起点、宽高和阈值仍会被校验。新增路线应先在 `evidence/<route>.py` 建立原子证据和页面组合，再写业务状态机。

检查器会输出 `config`、`template`、`region`、`reference_size`、`score`、`threshold`、`observed` 和 `center`。未达到阈值也必须保留数值 `score`，不能只显示“未命中”。当前命令行检查器只注册了竞技场；主线、远征和英雄合成通过正式失败出口生成同样字段的证据包。

实跑失败后，先看原 `*.png` 旁边的同名目录：`screen.png` 是当时完整画面，`evidence.json` 是可复查的量化结论。先按其中的 `config` 和证据键定位维护文件，再决定替换模板、移动 `REGIONS` 或调整 `THRESHOLDS`；不得仅凭一次失败降低阈值。

## 1. 先手动走完整流程

记录每个稳定页面、可选页面、加载边界、停止条件和循环完成标志。保存完整游戏窗口截图，不要只保存按钮裁剪。协作过程遵循 [HUMAN_AI_WORKFLOW.md](HUMAN_AI_WORKFLOW.md)，素材规则遵循 [TEMPLATE_CAPTURE.md](TEMPLATE_CAPTURE.md)。编码前为每个改变页面或业务状态的动作填写 [页面转场契约](TRANSITION_CONTRACTS.md)。

必须明确：

- 从哪个页面启动。
- 每一步点击前能识别什么唯一元素。
- 哪些页面可选或可能重复出现。
- 何时开启 Auto，是否会跨波次保持。
- 何时才算一轮完成。
- 资源不足时是正常停止还是故障。
- 哪些证据表示进入来源页，哪些证据表示离开并完成目标页。
- 证据冲突或关键模板缺失时，何时返回 `UNKNOWN` 并失败关闭。

契约至少写明：动作名称、来源页面、进入正向证据、阻断/`UNKNOWN` 条件、点击坐标依据、允许目标页面、业务成功证据、重试条件、失败诊断和循环计数影响。点击成功、转场成功和业务成功必须分开。

## 2. 文件约定

假设新模式名为 `hunt`：

```text
games/epic7/hunt.py
games/epic7/templates/hunt/*.png
tests/fixtures/epic7_hunt/*.png
tests/test_epic7_hunt.py
tests/test_hunt_runner.py
```

`hunt.py` 至少包含：

- `HuntState(Enum)`：稳定页面/等待阶段。
- `HuntAction`：动作名称与全局坐标。
- `HuntTemplates` 和 `build_hunt_templates()`。
- `HuntStateMachine.next_action(screen)`：纯视觉决策，不直接点击。
- `HuntRunner(ModeRunnerBase)`：继承公共主循环，只实现钩子，禁止复制 `run()` 主循环。

## 2.1 Runner 骨架约定

页面流程为“点按钮 → 转场 → 新页面”的同构模式（当前包括主线和狗粮）必须继承 `runner_base.py` 的 `ModeRunnerBase`，只声明差异：

- `_MODE_LABEL`：日志用模式名（中文）。**必须与 `ModeSpec.label` 一致** —— 它是
  唯一无法派生的那处副本（Runner 不能 import `modes`，会成环），由
  `route_metadata.py` 在 import 阶段比对。
- `_TIMEOUT_SECONDS`：每个状态的页面超时表。
- `_BATTLE_ENTRY_ACTION` + `_CLICK_BEFORE_BATTLE`：战斗移交方式。
- `_run_committed_battle(cycle)`：战斗监控实现（`BattleSupervisor` 或自带循环）。
- 需要时覆写 `_after_battle`、`_state_label`、`_on_action_exhausted` 等钩子。

禁止在新模式中复制粘贴主循环代码（两帧稳定、45 秒转场等待、4 次点击上限、战斗锁、超时熔断均已由基类实现）。只有交互模型根本不同时（如竞技场、远征的自定义流程）才允许独立 Runner，且状态轮询应复用 `core/supervisor.py` 的 `wait_until_target`。独立 Runner 必须自行声明重试额度，并保证日志分母和实际额度一致。

## 3. 先写截图流程测试

用完整实测截图按真实顺序驱动状态机。测试至少断言：

- 动作名称和坐标顺序准确。
- 未知全黑图不会产生点击。
- 可选页面出现和不出现都能继续。
- 两轮连续流程只在入口重新出现时计数两次。
- 正常资源耗尽不会执行购买动作。

如果修复某个实机失败，必须把失败截图加入 `tests/fixtures`，先写一个会失败的回归测试，再改模板或状态机。

完整 fixture 是复现证据，局部 template 是识别输入，两者不能互相替代。新增页面没有当前客户端完整截图时，保持安全停止并写入限制清单。

## 4. 注册模式

在 `games/epic7/modes.py` 中增加一项 `ModeSpec`：

```python
"hunt": ModeSpec(
    name="hunt",
    label="狩猎",              # 中文名 —— 全项目唯一来源（见下）
    default_state=HuntState.ENTRY.value,
    states=frozenset(state.value for state in HuntState),
    build_machine=_build_hunt,
    runner_type=HuntRunner,
    # 次数由游戏规则决定、不给用户选时：填 default_cycles 并把 cycles_editable 设 False。
    # 用户自己填次数的路线不用写这两项（默认 1 / 可编辑）。
    # 开局接力：认出人停在本路线哪一步就就地接管。没有它就必须进 RESUME_EXEMPT 并写明理由。
    # ⚠️ 探针本体**不要手写** —— 用工厂 `modes._resume_probe`（它会把「认落点 →
    # 拨状态机 → 回填 ResumePoint」一次做对；手抄最容易漏掉拨状态，而漏了之后
    # 接力看起来是命中的，Runner 却会原地干等到超时）。
    #   落点包含**导航链中间站**（判据要看导航器认出的页名）时：加 use_navigator=True；
    #   命中后还要做本路线专属动作时：加 on_hit=（如刷书签的 mark_resumed_at_shop）。
    resume_probe=_resume_probe(detect_hunt_resume_point),
    # 导航链：大厅 → 本路线入口的每一步。**必填**（有导航却漏声明，加载期直接报错）。
    # 声明之后 navigation.py 就再也不用改了 —— 它是执行器，只认这份数据。
    navigation_plan=NavigationPlan(
        mode="hunt",
        steps=(
            NavigationStep("lobby", ("hunt_home",), "lobby_hunt", "进入狩猎"),
        ),
        # 允许 navigate(already_at=...) 的页面；必须是上面某个 targets 里的页面。
        resume_entries=frozenset({"hunt_home"}),
        resume_action="跳过回大厅与进入狩猎",
        resume_state_done="已在狩猎主页",
    ),
),
```

构建器只负责载入模板和把字符串转换为该模式的 Enum。不要在 `main.py` 添加新的条件分支。

⚠️ **路线专属的校验、路线专属的构造参数，走 `ModeSpec` 的两个可选钩子** ——
2026-09-27 起 `main.run_mode` 只认「注册项上有没有钩子」，不认识任何具名路线；
`route_metadata.py` 会扫 `main.py`，再冒出 `if spec.name == "hunt"` 这种分叉就报错。

```python
"hunt": ModeSpec(
    ...
    # 实跑前校验：(路线名, 是否干跑) -> 拒绝文案 | None。
    # 会真花钱 / 不可逆的路线用它拦住实跑；干跑放不放行由钩子自己决定。
    preflight=_preflight_hunt,
    # 实跑才需要的构造参数：(仓库根, 是否干跑) -> 传给 Runner 构造函数的关键字。
    # 落盘位置这类参数走这里 —— 干跑不该落盘，就别在干跑分支里返回它。
    runner_options=_hunt_runner_options,
),
```

- `preflight` 跑在**建 runtime 之前**（被拦下的路线不该先开一个窗口），
  返回文案即拒绝运行、文案原样进异常；返回 `None` 才放行。
- `runner_options` 的返回值会**合并进** `run_mode` 自己那套参数（`recovery_gate` 等），
  同名键会被钩子覆盖 —— 别拿它改公共参数。
- 没有专属需求的路线**不要挂钩子**（挂个空转的配置只会让读的人以为它有含义）。

⚠️ **「导航链」也是注册模式的必填项**：有导航的路线必须挂 ``navigation_plan``
（数据结构见 ``games/epic7/navigation_plan.py``），否则加载期直接报错
（``_assert_navigation_declared``）。三个硬约束：

- **单目标也要写成元组** ``("hunt_home",)``：执行器按长度决定传给 ``_transition`` 的是
  ``str`` 还是 ``tuple``，而那里有 ``target == "hero_list"`` 这类身份比较，形状不能变。
- ``resume_entries`` 里的页面**必须真的出现在某个 ``targets`` 里**（声明「能从那一页接力」
  就等于声明「导航到得了那一页」），``NavigationPlan.__post_init__`` 在构造时就拦。
- **顺序即优先级**：多目标步骤（远征 ``lobby → battle_menu|season_menu``）按「由浅到深」写。

⚠️ 2026-09-30 之前这张链是 ``navigation.Epic7Navigator.navigate()`` 里一张
``if mode == "story" / elif mode == "arena" / ...`` 的分派链（约 250 行）—— 新增路线必须回去改
共享方法，漏一条还要等实跑开局才现形。现在 ``tests/test_navigation_plans.py`` 用源码级断言
钉住「分派链不许长回来」，**新增路线不需要动 ``navigation.py``**。

⚠️ **中文名只在 `ModeSpec.label` 里写一次**。CLI 输出、QQ 通知、导航日志、桌面助手全都从它派生（2026-09-27 收敛）。以前这些地方各有一份，实测漂移过
（同一路线在界面叫「活动」、在通知里叫「幸存者」）—— **别在别处再抄一份名字表**，
`games/epic7/route_metadata.py` 会在 import 阶段比对，抄漏了直接报错。

⚠️ **默认次数同理**：只在 `ModeSpec.default_cycles` 定义一次，`main.py` / `desktop/**`
里**不许**再出现 `if args.mode == "hunt": args.max_cycles = 3` 这种写法（同样会被
`route_metadata.py` 拦下）。

⚠️ **「接力」是注册模式的必填项**：新路线要么挂 `resume_probe`，要么进 `RESUME_EXEMPT` 并写明
「为什么不做」—— **两者都缺的话 `modes.py` 在 import 阶段直接抛错**（`_assert_resume_declared()`），
启动都到不了。`needs_navigation=False` 的路线自动豁免（起点本来就是人工推进到活动内部再启动）。

⚠️ **「动作靠什么验收」同样是注册模式的必填项**：新的 Runner 要么打开
`_REQUIRE_TRANSITION_CONTRACT = True`，要么进 `TRANSITION_EXEMPT` 并写明「用自己的什么机制验收」
—— 两者都缺的话同样在 import 阶段抛错（`_assert_transition_stance_declared()`）。
两类表态形状相同、理由写法相同，放在 `modes.py` 里相邻的两份名单中。
⚠️ 注意：**只有继承 `ModeRunnerBase` 的 Runner 才走得到那段校验**（读开关的代码在
`ModeRunnerBase.run()` 里）。另外两类 Runner 的开关**没人读**，打开是**摆设**，
必须进豁免名单并在理由里写清「用自己的哪套机制验收」：

- 自带独立主循环的裸定义（`class XxxRunner:`，`super()` 0 次）：`shop_refresh` / `survivor`；
- 继承**事务型**主循环基类 `TransactionalRunnerBase`（它**不是** `ModeRunnerBase` 的子类）的：
  `arena` / `expedition`（`expedition` 2026-09-26 从裸定义搬过去，`arena` 同日迁完）。

⚠️ 判定规则只有一条：**打开开关 ⇄ 进豁免名单，二选一**（`_assert_transition_stance_declared`）。
别把「它的动作没有 `target_pages`」直接推成「打开开关会抛错」—— 还要问一句
「它的 runner 走得到那段代码吗」（2026-09-24 踩过这个坑，护栏测试有专门一条钉住它）。

写一条路线的接力要动哪些文件、「什么算可停靠环节」，见
[TRANSITION_CONTRACTS.md](TRANSITION_CONTRACTS.md)「接力契约」；判据准不准由
`tests/test_resume_contracts.py` 在门槛里把住 —— 它拿该路线**自己的夹具**跑真的探针，
「挂上了」不等于「认得出」。覆盖面登记在 [RESUME_COVERAGE.md](RESUME_COVERAGE.md)。

## 5. 安全验收顺序

1. 运行全量离线测试。
2. 停在路线入口，运行默认干跑，确认只打印第一步。
3. `--live --confirm RUN --max-cycles 1` 验证一轮。
4. **停在路线半中间的某一页再启动**，确认就地接管（日志里应出现
   `模式=导航 动作=接力点命中` 与 `开局=接力`），而不是一路退回大厅重走。
5. 保存遇到的新页面并补回归测试。
6. 至少实跑两轮，验证循环衔接。
7. 主动验证资源不足或结束条件。

实跑期间用后台进程运行，并按 10 至 15 秒查看日志；不要用几十秒的前台固定等待。状态超时时先看诊断截图，不要直接放宽全局阈值。

## 6. 代码检查表

- 同构模式继承 `ModeRunnerBase`，没有复制 `run()` 主循环。
- 全局弹窗走 `Epic7GlobalPopupGuard`，没有在模式内加本地弹窗分支。
- 体力弹窗委托 `stamina.py` 决策，没有自建补体力流程。
- 日志使用中文键值对格式（`模式=`、`页面=`、`动作=`），页面名可读。
- 模板搜索都有限定区域。
- 点击坐标不位于头像、购买或其他高风险控件。
- 动作名称可从日志直接理解。
- 动作定义包含来源、允许目标和业务成功证据；重试保留原事务目标。
- **对「动作验收方式」表了态**：新的 Runner 要么打开
  `_REQUIRE_TRANSITION_CONTRACT = True`，要么进 `TRANSITION_EXEMPT` 写明「用自己的什么机制验收」；
  `tests/test_transition_contracts.py` 过（含「每条路线都表了态」「开开关的路线必须真的走得到那段校验」）。
  同页动作填 `in_page_evidence`（换页动作填 `target_pages`，二选一）。
  ⚠️ **打开之前先跑一遍那个检查函数再决定**：字段名对不上（例如英雄合成用
  `source_observation`）会让**所有**同页动作一起被拦，靠看代码看不出来 ——
  现成范本见 `runtime_logs/_probe_world_boss_contract_switch.py`。
- 日志不会在目标证据出现前写“成功”。
- 每个状态有合理超时。
- 干跑未知页面立即失败并保存截图。
- 正式失败出口同时保留 legacy PNG 与同名目录内的 `evidence.json`；诊断失败不能覆盖原业务异常。
- 模式恢复状态只接受本模式 Enum。
- **对「接力」表了态**：有导航的路线要么挂 `resume_probe`，要么进 `RESUME_EXEMPT` 写明理由；
  `tests/test_resume_contracts.py` 过（含「接线真通」与「拿自己的夹具跑真探针」两条）。
- **接力的落点判据与运行期同源** —— 复用状态机自己的页面判据，不另定阈值、不加新锚点。
  哪些画面**不该**接（弹窗通例 / 不可逆动作页 / 终态）见 [TRANSITION_CONTRACTS.md](TRANSITION_CONTRACTS.md)。
- 接力覆盖面已登记进 [RESUME_COVERAGE.md](RESUME_COVERAGE.md)。
- **桌面助手的分组表了态**：`desktop/catalog.py` 的 `RouteInfo` 里填了 `group`
  （`GROUP_DAILY` / `GROUP_ONDEMAND` / `GROUP_SEASON` / `GROUP_EVENT`）。
  ⚠️ **默认值是「每日」**，所以忘填不会报错 —— 但**按需**的（主线 / 狗粮 / 支线故事 /
  月光剧场 / 英雄合成那类：内容常驻、只是不用天天跑）、赛季轮换的（远征那类）
  或限时活动的路线**必须显式标出来**，否则用户在一堆「每日」里找不到它，
  也不会知道它会被轮换掉。三个非默认值的分界见
  [每日任务分组维护](maintenance/daily_tasks_grouping.md)（那里有一条判据：
  「按需」与「每日」的差别是**跑不跑**，不是内容在不在）。
- README 补充新模式命令和实机验证边界。
- `docs/TODO.md` 和 PC 迁移矩阵同步更新，不把候选模板写成已支持。

## 7. 远征路线的当前边界

- 首版固定选择三阶段，没有 `--difficulty` 参数。
- 一张传单只战斗一次；首领存活时公开招募，不重复挑战。
- 萤火待机页只点击中央安全区域唤醒，并验证真正 UI 出现；最多尝试两次。
- 公开招募后先返回远征队列表，再返回远征主页。
- 通缉传单角标不参与判断；只有远征主页锚点稳定出现才增加循环计数。
- 当前版本尚未采集传单耗尽和首领已击退页面，遇到未知画面时安全留证停止，拿到当前客户端截图后再补回归模板。
