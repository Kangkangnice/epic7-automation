---
status: superseded
---

# 新增路线的可扩展性审查（2026-09-27）

> 用户诉求：「后续可能会新增路线，希望新增路线的时候可以更少地犯错、更稳健、
> 可扩展性更强；一些已有的经验，有没有变成一个公用的函数或者全局通用的东西，
> 没有哪些目前是缺少的。」
>
> ⚠️ **本页是 2026-09-27 的方案快照，方案已落地，只作追溯、不要照着改。**
> 现行做法见 [`EXTENDING.md`](../EXTENDING.md) 与
> `doc_review --scenario new-route`；下表「已实施进度」记录当时选了哪些、为什么。
>
> **已实施进度**
>
> | 批次 | 内容 | 状态 |
> | --- | --- | --- |
> | 1 | A2 + B2（只加自查，不重构） | ✅ **已交付**（2026-09-27，`36a169e`）—— 见 `games/epic7/route_metadata.py` |
> | 2 | A1 + B1（元数据单一源） | ✅ **已交付**（2026-09-27）—— `ModeSpec.label` / `default_cycles` / `cycles_editable` 成为唯一来源，`main` / `navigation` / `launcher` / `catalog` / `daily_tasks` 全部派生 |
> | 3 | C1（路线级钩子，删 `main.py` 特判） | ✅ **代码完成、未提交**（2026-09-27，同一并发会话阻塞）—— `ModeSpec.preflight` / `ModeSpec.runner_options`，`main.run_mode` 两处 `if spec.name == ...` 已删，并加「`main.py` 不许再有路线特判」防回潮 |
> | 4 | D1 + D2（探针工厂 + 兜底测试） | ✅ **代码完成、未提交**（2026-09-27）—— 7 个 `_probe_*` 收成一个 `_resume_probe` 工厂；D2 兜底断言进了 `test_resume_contracts.py`，并做过变异验证（关掉 `resume_from` ⇒ arena/expedition/story/world_boss 四条当场红） |
> | 5 | E1（工厂合并，需先普查签名） | ✅ **已收敛：只做普查，不做合并**（2026-09-27，用户拍板）—— 普查（第五节末）显示只有 4 条逐字同构、且「传错模板根」实测会**当场**报错 ⇒ 合并只剩「少写 4 个函数」的收益，却要在注册表里引入第二种写法。普查结论已落成 `tests/test_modes.py::TemplateRootConventionTests` |
>
> 批次 1 落地时**顺带修掉了下面第一类的真实漂移**：survivor 在桌面助手里叫
> 「活动」、在命令行与 QQ 通知里叫「幸存者」，用户拍板统一成「活动」。
>
> 批次 2 又抓到**第二处**同形态的真实漂移：`shop_refresh` 在每日任务里叫
> 「商店刷新」、在其余四处叫「刷书签」，用户拍板统一成「刷书签」。
> 它同时把批次 1 的护栏重心改了：固定次数不再是「三处比对」（没有三处了），
> 改成「`main.py` 的源码里不许再写死次数」的**防回潮**检查。
>
> ⚠️ 已知残留：`survivor.py` 的**内部诊断日志**仍硬编码 6 处「模式=幸存者」，
> 留给后续一并收敛（它不是用户界面）。
>
> 批次 3 落地时按第三节 C1 的原始设计做（两个**可选回调**，不是声明式字段）：
> `preflight(mode, dry_run) -> 拒绝文案 | None` 跑在建 runtime **之前**；
> `runner_options(root, dry_run) -> dict` 的返回值合并进 `run_mode` 自己的那套参数。
> 唯一的实现细节坑：刷书签闸门读的 `LIVE_TRANSACTIONS_VERIFIED` 必须**在调用时**
> 从 `evidence.shop_refresh` 的模块属性上取 —— import 期 `from ... import` 绑一份名字，
> 测试再 `patch.object` 就拦不住它，闸门会退化成空转（有测试钉住这一点）。
>
> ⚠️ **后记（本轮 UI 改造）**：`launcher.py`（命令行编号菜单）**已整体删除** ——
> 交互入口只剩桌面助手一个。下面第一、二、三节是 2026-09-27 的**审查快照**，
> 其中出现的 `launcher.py` 与「5 处 / 7 处副本」计数反映的是**当时**的状态；
> 那些方案（收敛成 `ModeSpec` 单一事实源）已经落地，别照着快照去改一个不存在的文件。

---

## 〇、先说结论：这个仓库缺的不是「机制」，是「单一事实源」

必须先讲清楚，因为它决定了优化方向 —— **这个项目的准入护栏已经比绝大多数项目硬**：

| 已有机制 | 位置 | 漏了会怎样 |
| --- | --- | --- |
| 接力表态 | `modes.RESUME_EXEMPT` + `_assert_resume_declared` | **import 阶段报错** |
| 动作验收表态 | `modes.TRANSITION_EXEMPT` + `_assert_transition_stance_declared` | **import 阶段报错** |
| 结论门槛表态 | `modes.CONCLUSION_GATE_DECLARATION` + `_assert_conclusion_gate_declared` | **import 阶段报错** |
| 收尾回家表态 | `finish_home.FINISH_HOME_EXEMPT` + `_assert_finish_home_declared` | **import 阶段报错** |
| 公共流程验收表态 | `public_flow_verification.PUBLIC_FLOW_VERIFICATION` | **import 阶段报错** |
| 公共流程**反向**扫源码 | `assert_module_inventory_matches`（AST 扫） | 测试变红 |

五张表形状统一（一份表 + 一句理由 + 加载期自查），方向都对。**所以「缺少护栏」
不是主要矛盾。**

真正的问题是：**同一个事实被抄在 3~5 个地方，而其中只有一部分被护栏钉住。**
新增路线时，没被钉住的那几处漏改了**不会让任何测试变红** —— 这是最危险的一类。

下面按「危险程度」排序，而不是按「工作量」。

---

## 一、模式中文名抄在 5 处（🔴 最高危，且完全无护栏）

### 现状

同一个 `"竞技场"` 出现在：

| # | 位置 | 行 |
| --- | --- | --- |
| 1 | `games/epic7/arena.py` | `_MODE_LABEL = "竞技场"` |
| 2 | `games/epic7/arena.py` | `BattleConfig(mode="arena", mode_label="竞技场")` |
| 3 | `main.py` | `MODE_LABELS = {"arena": "竞技场", ...}` |
| 4 | `games/epic7/navigation.py` | `MODE_LABELS = {"arena": "竞技场", ...}` |
| 5 | `launcher.py` | `"2": ("竞技场", "arena")` |
| 6 | `desktop/catalog.py` | `RouteInfo("arena", "竞技场", ...)` |
| 7 | `games/epic7/daily_tasks.py` | `DailyTask(mode="arena", label="竞技场", ...)` |

**一共 7 处**。其中 `main.py` 与 `navigation.py` 各有一张**同名同内容的字典**
（`MODE_LABELS`），`launcher.py` / `desktop/catalog.py` / `daily_tasks.py`
则各自把中文名写在自己的数据结构里（菜单项 / `RouteInfo` / `DailyTask`）。
**`main.MODE_LABELS` 与 `navigation.MODE_LABELS` 这两张本该同内容的表，
已经不一致了**（见下）。

### 新增路线时会怎么犯错

- 加一条 `hunt` 路线，改完 1/3/4/5/6 忘了改 7 ⇒ **每日任务的汇总里显示 `hunt`
  而不是中文名**，实跑时才看见，测试不红。
- 或者更隐蔽：`navigation.MODE_LABELS.get(mode, mode)` 有默认值兜底 ⇒
  日志里悄悄退化成英文名，**没有任何报错**。

### ⚠️ 这个漂移**已经发生了**（2026-09-27 实测证据，不是推测）

```python
from auto_game_unified.main import MODE_LABELS as main_labels
from auto_game_unified.games.epic7.navigation import MODE_LABELS as nav_labels

set(main_labels) - set(nav_labels)   # → {'survivor'}   ← main 有、nav 没有
set(nav_labels) - set(main_labels)   # → set()          ← 反向没有
nav_labels.get('survivor', 'survivor')  # → 'survivor'  ← 悄悄退化成英文名
```

`main.MODE_LABELS` 里有 `survivor: "幸存者"`，而 `navigation.MODE_LABELS`
**整条漏了 `survivor`**。后果目前**很轻**（`survivor` 是 `needs_navigation=False`，
走不到 navigation 那条日志），所以没人发现 —— 但这正是本方案要防的形态：
**漏改一处，不报错、不测试红、后果随机**。

修完之后这两种表现都会变成 import 阶段报错。

### 方案 A1（推荐）：收敛成 `modes.py` 里的单一元数据源

在 `MODE_SPECS` 的每一项上加 `label` 字段（`ModeSpec` 已有 `name`），
其余所有地方从它派生：

```python
# modes.py
class ModeSpec:
    name: str
    label: str          # ← 新增：唯一的中文名来源
    ...

MODE_SPECS = {
    "arena": ModeSpec(name="arena", label="竞技场", ...),
}
MODE_LABELS = {name: spec.label for name, spec in MODE_SPECS.items()}
```

- `main.MODE_LABELS` → `from ...modes import MODE_LABELS`（删掉本地表）
- `navigation.MODE_LABELS` → 同上（**发现这是第二张重复表**，一并删）
- `launcher.py` 菜单 → 从 `MODE_SPECS` 生成
- `desktop/catalog.py` → `label` 从 spec 取（`status`/`description` 仍留在 catalog）
- `daily_tasks.DailyTask.label` → 改成从 spec 派生

**代价**：`modes.py` 是共享模块 ⇒ 必须全量验证（7~8 分钟）。
`launcher.py` / `desktop/**` / `main.py` 都会被牵动。

### 方案 A2（更小、但治标）：只加一条一致性自查

不重构，只加一个加载期自查：遍历 `MODE_SPECS`，要求
`main.MODE_LABELS` / `navigation.MODE_LABELS` / `launcher` 菜单 / `catalog.ROUTES`
里的中文名与派生值**全部一致**，不一致就 import 报错。

- **优点**：不动结构，风险低，改动小（大概率只碰 `modes.py` + 一个测试）。
- **缺点**：中文名还是抄在 5 处，只是漏改会**报错**而不是悄悄退化。
  「改 5 处」这件事本身还在。

**我的建议**：A1。因为「抄 5 处」的长期成本比一次性重构高，而且 A1 顺带
消灭 `navigation.MODE_LABELS` 这张**没人知道的重复表**。

---

## 二、默认轮次抄在 3 处（🟠 高危，靠测试钉但覆盖不全）

### 现状

`world_boss` 默认 2 次这件事写在：

1. `main.py` `if args.mode == "world_boss" and args.max_cycles is None: args.max_cycles = 2`
2. `launcher.py` `elif mode == "world_boss": cycles = 2`
3. `desktop/catalog.py` `default_cycles=2`

三处注释都写着「与另外两处保持一致（都被测试钉住）」。**但实际只钉住了 catalog**：
`tests/test_desktop_catalog.py` 只断言了 catalog 自己的值，**没有任何测试
交叉校验这三个数字相等**。「都被测试钉住」这句注释是**不准确的**。

### 新增路线时会怎么犯错

新加一条「每天固定 N 次」的路线，改了两处、忘了第三处 ⇒
**命令行入口和界面入口行为不一致**（一个跑 2 次、一个跑 3 次），
而且只在你从另一个入口启动时才暴露。

### 方案 B1（推荐）：把「默认次数」也放进元数据，三处派生

在 `ModeSpec` 上加 `default_cycles: int | None` 与 `cycles_editable: bool`，
`main.py` / `launcher.py` / `catalog.py` 全部从它读。

### 方案 B2：只加交叉校验测试

写一条测试断言「`MODE_SPECS[name].default_cycles` == `catalog.route_by_name(name).default_cycles`」，
再让 `main.py` / `launcher.py` 从 `MODE_SPECS` 读。

**我的建议**：B1 与 A1 合并做（同一处元数据，一次全量验证）。如果只做一条，
至少做 B2 —— 它能把那句不准确的注释变成真的。

---

## 三、`main.py::run_mode` 里塞了路线特判（🟠 违背自己定的规矩）

### 现状

```python
# main.py run_mode()
if spec.name == "shop_refresh" and not dry_run and not LIVE_TRANSACTIONS_VERIFIED:
    raise RuntimeError("刷书签目标商品和购买价格尚未通过当前客户端实证...")

runner_options: dict[str, Any] = {}
runner_options["recovery_gate"] = RecoveryGate()
if spec.name == "arena" and not dry_run:
    runner_options["purchase_stamp_path"] = ...
    runner_options["outcome_frame_dir"] = ...
runner = spec.runner_type(machine, runtime, **runner_options)
```

而 `docs/EXTENDING.md` 第 100 行明写：

> **不要在 `main.py` 添加新的条件分支。**

### 新增路线时会怎么犯错

新路线若需要：专属构造参数（如竞技场的 `purchase_stamp_path`）、
或「某条件下禁止实跑」的前置校验（如刷书签的实证门），
**只能在 `main.py` 里再插一个 `if`** —— 直接违反自家文档。
而且这些 `if` 会随路线增长线性膨胀。

### 方案 C1（推荐）：给 `ModeSpec` 加两个可选钩子

```python
class ModeSpec:
    # 路线级的运行前校验（返回错误文案则拒绝运行）
    preflight: Optional[Callable[[str, bool], Optional[str]]] = None
    # 路线级的构造参数（(root, dry_run) -> dict）
    runner_options: Optional[Callable[[Path, bool], dict[str, Any]]] = None
```

`run_mode` 不再认任何具名路线：

```python
if spec.preflight is not None:
    reason = spec.preflight(spec.name, dry_run)
    if reason: raise RuntimeError(reason)
runner_options = spec.runner_options(ROOT, dry_run) if spec.runner_options else {}
```

路线特判全部沉到各自注册项旁边（`modes.py`），**`main.py` 永远不再长 `if`**。

### 方案 C2：只加一条「main.py 不许再出现 spec.name ==」的护栏测试

用 AST 扫 `main.py`，发现新的 `spec.name ==` 分支就报错，把现有两处写进白名单。
**治标**：拦住新人，但现有两处仍在。

**我的建议**：C1。这是「新增路线更少犯错」最直接的收益点之一，
且改动集中在 `main.py` + `modes.py`（都是共享模块，反正要全量）。

---

## 四、7 个接力探针里，5 个是同 5 行（🟡 中危）

### 现状

`modes.py` 里 `_probe_arena_resume` / `_probe_story_resume` /
`_probe_expedition_resume` / `_probe_world_boss_resume` 是**逐字同构**的：

```python
observed = navigator.observe(screen).name if navigator is not None else None
found = detect_resume_point(machine, screen, observed_page=observed)
if found is None: return None
if found.state is not None: machine.resume_from(found.state)
return ResumePoint(page=found.page, state=..., entry=found.entry)
```

（`_probe_knights_donation_resume` / `_probe_labyrinth_stone_resume` 是简化版：
`del navigator` + 无 `resume_from`；`_probe_shop_refresh_resume` 有额外
`mark_resumed_at_shop()`，是真差异。）

### 新增路线时会怎么犯错

手抄这段时**很容易漏掉 `machine.resume_from(found.state)`** ——
漏了之后接力"看起来"能命中（日志会打「开局=接力」），
但状态机没拨过去，**Runner 会原地干等到超时**。
而 `EXTENDING.md` 里明确写过「拨错会让 Runner 原地干等到超时，而不是自愈」。

这个错误**当前不会被任何测试发现**（除非该路线恰好有"停在半路启动"的用例）。

### 方案 D1（推荐）：抽一个探针工厂

```python
def _resume_probe(detect, *, use_navigator=False, on_hit=None) -> ResumeProbe:
    def probe(machine, screen, navigator):
        observed = None
        if use_navigator and navigator is not None:
            observed = navigator.observe(screen).name
        found = detect(machine, screen, observed_page=observed)
        if found is None: return None
        if found.state is not None: machine.resume_from(found.state)
        if on_hit is not None: on_hit(machine)
        return ResumePoint(page=found.page, state=..., entry=found.entry)
    return probe
```

注册处变成一行：

```python
"world_boss": ModeSpec(..., resume_probe=_resume_probe(detect_world_boss_resume_point)),
"shop_refresh": ModeSpec(..., resume_probe=_resume_probe(
    detect_shop_resume_point, use_navigator=False, on_hit=lambda m: m.mark_resumed_at_shop())),
```

**收益**：「接力必须拨状态」这条经验变成**代码**而不是**每个人的记忆**，
新路线不可能再漏。

### 方案 D2：只补一条「接力后状态确实变了」的测试

让 `test_resume_contracts.py` 对**每条挂了探针的路线**都跑一遍：
拿该路线自己的夹具 → 跑探针 → 断言「若 `ResumePoint.state is not None`，
则 `machine.state.value == ResumePoint.state`」。

**代价**：不改结构，只加测试。但每条路线需要的夹具形态不同，可能有的路线
凑不出「能命中接力点」的夹具 ⇒ 覆盖会不全。

**我的建议**：D1 + D2 都做。D1 是根治，D2 是兜底（万一某条路线自己的
`detect_resume_point` 有特殊逻辑）。

---

## 五、10 个 `build_machine` 工厂同构，且模板根两种写法并存（🟡 中危）

### 现状

```python
def _build_world_boss(root, state, backend):
    return WorldBossStateMachine(root / "world_boss", initial_state=WorldBossState(state), backend=backend)
```

10 个几乎一样。且**模板根到底是 `template_root` 还是 `template_root / "xxx"` 两种写法并存**
（`_build_arena` 用根、`_build_labyrinth_stone` 用子目录），
`_build_labyrinth_stone` 专门留了注释警告这个坑：

> 模板子目录是 templates/labyrinth_stone；工厂必须把它当根，不能当 templates 根。

### 新增路线时会怎么犯错

新路线的模板放在 `templates/hunt/` 下，工厂里**传错了根** ⇒
所有模板路径错一级 ⇒ 干跑立刻"认不出画面"。
这个错误**会在第一次空跑就暴露**（不会漏到实跑），所以危险等级比上面几条低。
但它每次都要靠人肉试错一次。

### 方案 E1：工厂签名收进 `ModeSpec`，用模板子目录名派生

不写 10 个 `_build_xxx`，改成注册表项声明
`machine_cls` + `state_enum` + `template_subdir`，由一个通用工厂构造：

```python
def _build_machine(machine_cls, state_enum, subdir, needs_backend):
    def build(root, state, backend):
        target = root / subdir if subdir else root
        return machine_cls(target, initial_state=state_enum(state), backend=backend)
    return build
```

**收益**：模板根只有一个规则（`subdir` 字段），不可能再传错。
**风险**：需要确认 10 个状态机的构造签名真的同构（`expedition` /
`labyrinth_stone` / `world_boss` 看起来是 `(root, initial_state=, backend=)`，
但 `shop_refresh` / `survivor` 是 observer 型，**不同构**，必须留特例）。

**我的建议**：E1，但**先做一次签名普查**（我可以先跑一个只读检查列出 10 个
构造签名，确认哪些能合并、哪些必须留特例）。这条建议**排在其他四条之后**，
因为它收益最小（错误会在空跑暴露）。

### 普查结果（2026-09-27，已做，只读）

**10 个工厂的签名普查**：

| 形状 | 路线 | 构造方式 |
| --- | --- | --- |
| A：`(Path, initial_state=, backend=)` | expedition / world_boss / labyrinth_stone / knights_donation | **逐字同构**，只有类名/Enum/子目录名不同（模板根都是 `root / "<路线名>"`） |
| B：`(模板对象, initial_state=, backend=)` | arena（`build_templates(root)`）/ hero_synthesis（`build_hero_templates(root)`）/ story（`build_story_templates(root/"story")`） | 模板由各自的 `build_*_templates` 造；**模板根两种写法都有**（arena/hero_synthesis 用根，story 用子目录） |
| C：`(模板对象, initial_state=)` | fodder（`build_fodder_templates(root/"fodder")`） | **不接受 backend** |
| D：observer 型 | shop_refresh（`(1, observer=...)`）/ survivor（`(observer=...)`） | 与上面三种都不同构 |

**两个结论（都实测过）**：

1. **能合并的只有 A 那 4 条**。B/C/D 要并进同一个工厂，就得引入
   `needs_backend` / `templates_loader` / `observer` 之类开关 —— 那正是本项目
   在别处明确拒绝的做法（见第六节 F2/F3：「只抽逐字相同的部分」）。合完还会让
   注册表出现**两种写法**（工厂 + 手写建造器），可读性反而下降。
2. ⚠️ **E1 的安全收益比原估计更低**：实测传错一层模板根会**当场
   `FileNotFoundError`**（`templates/world_boss/world_boss/knights_title.png` 读不到），
   **不是静默失效**；而且每条路线自己的测试本来就会在真模板根上构造一次。
   ⇒ 它防的那个错**已经有更早、更响的暴露点**了。

普查已经把 A 组「模板根不能传错」这条性质落成门槛测试（`tests/test_modes.py`
的 `TemplateRootConventionTests`，同时补齐了 fodder / shop_refresh / survivor /
labyrinth_stone 这 4 条原先没直接构造过的缺口）。

**⇒ E1 的「合并」本身降级为可选项**（收益只剩少写 4 个函数）。
**2026-09-27 用户拍板：不合并** —— 普查的收益（「模板根不能传错」这条性质有了门槛测试、
10 条路线都验过一遍）已经拿到，不值得为此在注册表里引入「工厂 + 手写建造器」两种写法。
以后真觉得照着写 4 行麻烦时再回头看这一段。

---

## 六、次要项（列出但不建议现在做）

| # | 项 | 为什么不建议现在做 |
| --- | --- | --- |
| F1 | `public_flow_verification.ACTION_BEARING_MODULES` 里的路线名写死 10 个 | 它只查**公共流程**，路线名那份 `routes` 集合漏加**不会让护栏失效**（新路线不在 `routes` 里 ⇒ 会被当成公共流程扫，反而更严）。**当前是安全的**，只是冗余 |
| F2 | `shop_refresh` / `survivor` 两族裸主循环 | 已知刻意保留（交互模型真不同）。**不要为了统一而合并** —— 会换掉一批评据 |
| F3 | `ModeRunnerBase.run()` 930 行单一主循环 | 长，但内部有清晰的段落注释与契约说明。拆分会打断可读性，**不建议动** |

---

## 七、建议的实施顺序（如果要全做）

按「收益 / 风险」排序，且**每批独立提交 + 全量验证**：

| 批次 | 内容 | 碰到共享模块 | 需全量 |
| --- | --- | --- | --- |
| 1 | A2 + B2（只加自查，不重构） | `modes.py` + 测试 | ✅ |
| 2 | A1 + B1（元数据单一源） | `modes.py` `main.py` `launcher.py` `desktop/**` `navigation.py` `daily_tasks.py` | ✅ |
| 3 | C1（路线级钩子，删 `main.py` 特判） | `modes.py` `main.py` + 竞技场/刷书签注册 | ✅ |
| 4 | D1 + D2（探针工厂 + 兜底测试） | `modes.py` + 测试 | ✅ |
| 5 | E1（工厂合并，需先普查签名） | `modes.py` + 10 条路线 | ✅ |

⚠️ 每一批都会碰 `modes.py`（共享模块）⇒ **每批都要全量**。
如果希望减少验证次数，可以把 1~4 合并成一次大改，但**风险集中在一处**
（出问题时不好二分定位）。**我倾向分批**。

---

## 八、这些方案能防住的错（汇总）

| 错误 | 现在会不会被发现 | 改完之后 |
| --- | --- | --- |
| 新增路线忘改中文名 → 日志/菜单显示英文 | ❌ 不报错，静默退化 | ✅ import 报错 |
| 新增路线默认次数三处不一致 | ❌ 只钉了 catalog 一处 | ✅ import 报错 |
| 在 `main.py` 加路线特判 | ❌ 无任何机制 | ✅ import/测试报错 |
| 接力探针漏 `resume_from` | ❌ 只在实跑原地超时 | ✅ 不可能漏（工厂内建） |
| 工厂传错模板根 | ⚠️ 空跑会暴露 | ✅ 只有一个规则 |
