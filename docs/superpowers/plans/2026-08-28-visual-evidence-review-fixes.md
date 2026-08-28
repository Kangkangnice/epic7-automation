# Visual Evidence Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复视觉证据集中化的验收缺口，使检查器与生产页面判断一致、失败分数和维护位置可见、英雄合成真正读取集中配置，并让正式路线的失败出口生成自包含证据包。

**Architecture:** 公共 matcher 新增不按阈值截断的最高分接口，证据检查层据此生成完整观测。复杂页面规则保留为路线证据模块中的普通 Python 判定函数，检查器和状态机共同调用；诊断通过 Runner 的现有失败出口接入，不改变业务动作和状态顺序。

**Tech Stack:** Python 3.11、OpenCV、NumPy、pytest、现有 `Runtime`、`ModeRunnerBase` 和路线状态机。

---

## 工作区约束

- 基线提交为包含修复规格的 `7687c02`。
- 当前 `main` 有与本轮无关的既有未提交修改；执行时从当前 `HEAD` 建独立 worktree，不复制这些修改。
- 不修改 PC、狗粮、助手自动、路线正式状态和既有业务顺序。
- 每个行为先写测试并确认出现预期 RED，再写最小实现。
- 最终合并回本地 `main` 前重新核对原工作区未提交文件仍然存在。

## 文件责任地图

- `core/matcher.py`：返回搜索区域内最高匹配结果，不解释业务阈值。
- `games/epic7/evidence/common.py`：证据定义、观测结构、配置位置、必需/可选模板和页面评估入口。
- `core/evidence_diagnostics.py`：把 profile 转换为量化观测并保存自包含诊断。
- `games/epic7/evidence/pre_battle.py`：普通/快速战斗入口的共享视觉分类。
- `games/epic7/evidence/arena.py`：竞技场页面规则，特别是选中页分数比较和队伍页快速战斗识别。
- `games/epic7/evidence/story.py`、`expedition.py`、`hero_synthesis.py`：完整声明预期模板，不因文件缺失删除证据。
- `games/epic7/hero_synthesis.py`：消费 hero profile 的区域和阈值，不重复保存已迁移数值。
- `games/epic7/runner_base.py`、`arena.py`、`expedition.py`：在现有失败出口调用证据诊断适配器。
- `tools/check_evidence.py`：输出配置文件、区域、分数、阈值、位置和与生产一致的页面状态。

## Task 1: 保留未通过阈值的最高匹配分数

**Files:**
- Modify: `core/matcher.py`
- Modify: `core/evidence_diagnostics.py`
- Modify: `games/epic7/evidence/common.py`
- Modify: `tests/test_matcher.py`
- Modify: `tests/test_evidence_diagnostics.py`

- [ ] **Step 1: 写 matcher 最高分接口的失败测试**

在 `tests/test_matcher.py` 增加：

```python
def test_find_best_template_returns_score_below_business_threshold():
    screen = np.zeros((40, 40, 3), dtype=np.uint8)
    template = np.arange(100, dtype=np.uint8).reshape(10, 10)
    template = np.repeat(template[:, :, None], 3, axis=2)
    screen[10:20, 10:20] = np.clip(template.astype(np.int16) + 25, 0, 255).astype(np.uint8)

    best = find_best_template(screen, template, region=(0, 0, 40, 40))

    assert best is not None
    assert 0.0 <= best.score <= 1.0
    assert find_template(screen, template, best.score + 0.001, region=(0, 0, 40, 40)) is None
```

- [ ] **Step 2: 运行 RED**

Run: `pytest tests/test_matcher.py::test_find_best_template_returns_score_below_business_threshold -q`

Expected: FAIL because `find_best_template` does not exist.

- [ ] **Step 3: 实现不截断分数的公共匹配接口**

在 `core/matcher.py` 提取现有缩放、裁剪和 `cv2.matchTemplate` 逻辑：

```python
def find_best_template(
    screen: np.ndarray,
    template: np.ndarray,
    region: tuple[int, int, int, int] | None = None,
    reference_size: tuple[int, int] | None = None,
) -> Optional[Match]:
    # 沿用 find_template 的缩放和区域语义。
    # 搜索区小于模板时返回 None；否则始终返回最高分 Match。
```

`find_template(...)` 改为调用 `find_best_template(...)`，只负责 `best.score >= threshold` 过滤，保持所有现有调用行为不变。

- [ ] **Step 4: 写诊断低分观测的失败测试**

在 `tests/test_evidence_diagnostics.py` 增加一个模板未达到 `0.999` 的场景，断言：

```python
report = inspect_profile(screen, profile, tmp_path)
observation = report.atoms["anchor"]
assert observation.observed is False
assert observation.score is not None
assert observation.score < observation.threshold
```

- [ ] **Step 5: 运行诊断 RED**

Run: `pytest tests/test_evidence_diagnostics.py::test_inspect_profile_keeps_score_below_threshold -q`

Expected: FAIL because current code stores `None` for failed observations.

- [ ] **Step 6: 让检查层使用最高分并验证 GREEN**

`inspect_profile` 使用 `find_best_template`，以 `best is not None and best.score >= atom.threshold` 计算 `observed`，但无论是否通过阈值都保存 `score` 和 `center`。

Run: `pytest tests/test_matcher.py tests/test_evidence_diagnostics.py -q`

Expected: all pass.

- [ ] **Step 7: 提交 Task 1**

```text
git add core/matcher.py core/evidence_diagnostics.py games/epic7/evidence/common.py tests/test_matcher.py tests/test_evidence_diagnostics.py
git diff --cached --check
git commit -m "fix: preserve visual evidence match scores"
```

## Task 2: 让竞技场检查器与生产页面判定共用规则

**Files:**
- Create: `games/epic7/evidence/pre_battle.py`
- Modify: `games/epic7/pre_battle.py`
- Modify: `games/epic7/evidence/common.py`
- Modify: `games/epic7/evidence/arena.py`
- Modify: `games/epic7/arena.py`
- Modify: `core/evidence_diagnostics.py`
- Modify: `tools/check_evidence.py`
- Modify: `tests/test_arena_evidence.py`
- Modify: `tests/test_evidence_diagnostics.py`

- [ ] **Step 1: 写真实 selected fixture 的失败测试**

在 `tests/test_arena_evidence.py` 读取 `tests/fixtures/epic7_arena/selected.png`，按检查器相同规则裁剪游戏画面并断言：

```python
report = inspect_profile(screen, profile, TEMPLATES)
machine = ArenaStateMachine(build_templates(TEMPLATES))
assert machine.is_in_state(screen, ArenaState.SELECTED)
assert report.pages["arena.selected"] is EvidenceState.SAFE
```

- [ ] **Step 2: 写快速战斗队伍页的失败测试**

使用 `quick_battle_selected_live_20260826.png`：

```python
assert machine.is_in_state(screen, ArenaState.TEAM)
assert report.pages["arena.team"] is EvidenceState.SAFE
```

- [ ] **Step 3: 运行两个 RED**

Run: `pytest tests/test_arena_evidence.py -q`

Expected: selected is `UNSAFE`; quick team is `UNKNOWN`.

- [ ] **Step 4: 建立共享的普通/快速战斗视觉分类**

在 `games/epic7/evidence/pre_battle.py` 定义：

```python
class PreBattleEvidenceState(Enum):
    NORMAL = "normal"
    QUICK = "quick"
    UNKNOWN = "unknown"

REFERENCE_SIZE = (1982, 1132)
REGION = (900, 900, 1050, 232)
QUICK_BUTTON_THRESHOLD = 0.88
QUICK_SWITCH_THRESHOLD = 0.90

def classify_pre_battle_scores(
    normal_score: float | None,
    quick_score: float | None,
    switch_score: float | None,
) -> PreBattleEvidenceState:
    # normal 独占 -> NORMAL；quick+switch 且无 normal -> QUICK；其余 UNKNOWN。
```

`games/epic7/pre_battle.py` 的 `QuickBattleDetector` 读取这些常量并调用同一分类函数，再通过 `PreBattleMode(evidence_state.value)` 保持现有 `PreBattleObservation` API。

- [ ] **Step 5: 为 profile 增加路线页面评估入口**

在 `games/epic7/evidence/common.py` 中让 `EvidenceProfile` 接受可选 `page_evaluator`，并提供：

```python
def evaluate_pages(self, observations: Mapping[str, AtomObservation]) -> dict[str, EvidenceState]:
    if self.page_evaluator is not None:
        return dict(self.page_evaluator(observations))
    flags = {key: item.observed for key, item in observations.items()}
    return {page.key: page.evaluate(flags) for page in self.pages}
```

`AtomObservation` 移到 `evidence/common.py`，避免证据模块反向依赖 `core`。

- [ ] **Step 6: 实现竞技场复杂页面判定**

竞技场 profile 增加 `quick_battle_button`、`quick_battle_switch` 原子证据，并由 `evaluate_arena_pages` 使用：

```python
selected = (
    EvidenceState.SAFE
    if challenge.observed
    and (not list_ready.observed or challenge.score >= list_ready.score)
    else EvidenceState.UNKNOWN
)
team_mode = classify_pre_battle_scores(
    score("battle_start"),
    score("quick_battle_button"),
    score("quick_battle_switch"),
)
team = EvidenceState.UNSAFE if observed("no_ticket") else (
    EvidenceState.SAFE if team_mode is not UNKNOWN else EvidenceState.UNKNOWN
)
```

`ArenaStateMachine.is_in_state` 的 SELECTED 和 TEAM 分支调用同一辅助函数，保留原有含义。

- [ ] **Step 7: 输出维护位置和完整量化字段**

`EvidenceProfile` 增加 `config_path: str = ""` 和 `template_root: Path | None = None`；竞技场 builder 设置为 `str(Path(__file__).resolve())` 和传入的模板根目录。`inspect_profile` 保留显式 `template_root` 参数，并允许诊断适配器在未显式传入时使用 `profile.template_root`。`tools/check_evidence.py` 每条原子证据打印：

```text
key config template region reference_size score threshold observed center
```

- [ ] **Step 8: 运行 GREEN 与回归**

Run:

```text
pytest tests/test_arena_evidence.py tests/test_evidence_diagnostics.py tests/test_epic7_arena.py tests/test_quick_battle_route_integration.py -q
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/selected.png
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/quick_battle_selected_live_20260826.png
```

Expected: selected and quick team both report `SAFE`, and failed atoms retain numeric scores.

- [ ] **Step 9: 提交 Task 2**

```text
git add games/epic7/evidence/pre_battle.py games/epic7/pre_battle.py games/epic7/evidence/common.py games/epic7/evidence/arena.py games/epic7/arena.py core/evidence_diagnostics.py tools/check_evidence.py tests/test_arena_evidence.py tests/test_evidence_diagnostics.py
git diff --cached --check
git commit -m "fix: share arena page evidence with runtime"
```

## Task 3: 修复必需与可选模板校验

**Files:**
- Modify: `games/epic7/evidence/common.py`
- Modify: `games/epic7/evidence/story.py`
- Modify: `games/epic7/evidence/expedition.py`
- Modify: `games/epic7/evidence/hero_synthesis.py`
- Modify: `core/evidence_diagnostics.py`
- Modify: `tests/test_visual_evidence.py`
- Modify: `tests/test_story_evidence.py`
- Modify: `tests/test_expedition_evidence.py`
- Modify: `tests/test_hero_evidence.py`

- [ ] **Step 1: 写空目录下缺失模板的失败测试**

分别构建 story、expedition、hero profile，断言必需证据仍存在且校验包含具体文件：

```python
profile = build_hero_evidence(tmp_path)
assert "rating_sss" in profile.atoms
assert any("rating_sss.png" in error and "模板不存在" in error for error in validate_profile(profile, tmp_path))
```

- [ ] **Step 2: 运行 RED**

Run: `pytest tests/test_story_evidence.py tests/test_expedition_evidence.py tests/test_hero_evidence.py -q`

Expected: FAIL because builders currently omit missing atoms.

- [ ] **Step 3: 增加显式可选模板语义**

`AtomEvidence` 增加 `required: bool = True`。`validate_profile` 仅对 `required=True` 的缺失文件报告错误；`inspect_profile` 对缺失的可选模板记录 `observed=False, score=None, center=None`，不抛异常。

路线 builder 无条件创建 `_TEMPLATE_NAMES`/`_TEMPLATE_PATHS` 中的原子证据。明确标为可选：

- story：`stamina_popup`、`stamina_material`、`stamina_confirm`；
- expedition：`empty_posters`、`defeated_confirm`；
- hero：当前 `HeroTemplates` 中声明为 `Optional[np.ndarray]` 的模拟器辅助模板。

story、expedition、hero builder 同时设置 `config_path` 和 `template_root`，与竞技场 profile 的诊断元数据一致。

- [ ] **Step 4: 运行 GREEN**

Run: `pytest tests/test_visual_evidence.py tests/test_story_evidence.py tests/test_expedition_evidence.py tests/test_hero_evidence.py tests/test_evidence_diagnostics.py -q`

Expected: all pass; required missing templates are named, optional missing templates are inspectable but not configuration errors.

- [ ] **Step 5: 提交 Task 3**

```text
git add games/epic7/evidence/common.py games/epic7/evidence/story.py games/epic7/evidence/expedition.py games/epic7/evidence/hero_synthesis.py core/evidence_diagnostics.py tests/test_visual_evidence.py tests/test_story_evidence.py tests/test_expedition_evidence.py tests/test_hero_evidence.py tests/test_evidence_diagnostics.py
git diff --cached --check
git commit -m "fix: validate declared visual evidence templates"
```

## Task 4: 让英雄合成消费集中区域和阈值

**Files:**
- Modify: `games/epic7/evidence/hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_evidence.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 写 profile 注入的失败测试**

用 `dataclasses.replace` 构造修改后的 `rating_sss` 和 `sss_material` 原子证据，将 profile 注入 `HeroTemplates`，断言状态机实例读取：

```python
machine = HeroSynthStateMachine(replace(templates, evidence=custom_profile))
assert machine._region("rating_sss") == custom_profile.atom("rating_sss").region
assert machine._threshold("rating_sss") == custom_profile.atom("rating_sss").threshold
assert machine._region("sss_material") == custom_profile.atom("sss_material").region
```

- [ ] **Step 2: 运行 RED**

Run: `pytest tests/test_hero_synthesis.py::test_state_machine_reads_migrated_regions_and_thresholds_from_profile -q`

Expected: FAIL because `_threshold` does not exist and runtime still reads class constants.

- [ ] **Step 3: 添加最小 profile 访问器并替换重复值**

状态机初始化复制 atom 的 regions 和 thresholds，并提供：

```python
def _region(self, key: str) -> tuple[int, int, int, int]:
    return self._REGIONS[key]

def _threshold(self, key: str) -> float:
    return self._THRESHOLDS[key]
```

替换已迁移重复值：

- `_RATING_REGION` / `_RATING_SSS_MIN` -> `rating_sss`；
- `_MATERIAL_SSS_REGION` / `_SSS_MATERIAL_MIN` -> `sss_material`；
- `_FILTER_ATTRIBUTE_MIN` -> `filter_attribute_label`；
- `filter_star3_unselected` 的实际生产阈值写回 profile 并由 `_locate` 默认读取；
- SSS warning、imprint result、transmit result 的 title/close 区域读取对应 evidence key。

小尺寸画面的 `0.75` 特例移动到 evidence 模块的命名常量，保持行为不变。

- [ ] **Step 4: 运行英雄专项 GREEN**

Run:

```text
pytest tests/test_hero_evidence.py tests/test_hero_synthesis.py -q
```

Expected: all existing SSS、材料安全、相邻同名副本和传送事务测试不变且通过。

- [ ] **Step 5: 提交 Task 4**

```text
git add games/epic7/evidence/hero_synthesis.py games/epic7/hero_synthesis.py tests/test_hero_evidence.py tests/test_hero_synthesis.py
git diff --cached --check
git commit -m "fix: consume hero visual evidence profile"
```

## Task 5: 把自包含证据包接入正式路线失败出口

**Files:**
- Modify: `core/evidence_diagnostics.py`
- Modify: `games/epic7/runner_base.py`
- Modify: `games/epic7/arena.py`
- Modify: `games/epic7/expedition.py`
- Modify: `tests/test_evidence_diagnostics.py`
- Modify: `tests/test_story_runner.py`
- Modify: `tests/test_arena_runner.py`
- Modify: `tests/test_expedition_runner.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 写 profile 诊断适配器的失败测试**

在临时诊断目录创建 `Runtime` 和最小 profile，调用期望的：

```python
result = save_runtime_evidence_diagnostic(
    runtime,
    screen,
    profile,
    legacy_path=legacy_png,
    mode="竞技场",
    action="challenge",
    source="arena.list",
    targets=("arena.selected",),
    attempt=2,
    conclusion="目标未进入",
)
assert result is not None
assert (result / "screen.png").is_file()
payload = json.loads((result / "evidence.json").read_text(encoding="utf-8"))
assert payload["evidence"]["list_ready"]["config"]
assert payload["evidence"]["list_ready"]["region"]
assert isinstance(payload["evidence"]["list_ready"]["score"], float)
```

- [ ] **Step 2: 运行 RED**

Run: `pytest tests/test_evidence_diagnostics.py::test_save_runtime_evidence_diagnostic_writes_self_contained_profile_report -q`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: 实现诊断适配器**

`save_runtime_evidence_diagnostic`：

- `runtime.diagnostic_dir is None` 或 `profile is None` 时返回 `None`；
- 使用 `legacy_path.with_suffix("")` 作为自包含目录，避免改变原日志中的 PNG 路径；
- 调用 `inspect_profile`，序列化每个 atom 的 config、template、region、reference_size、score、threshold、observed、center；
- 调用现有 `write_evidence_diagnostic`；
- 捕获诊断自身异常，使用 `runtime.log` 追加“视觉证据诊断失败”，不得覆盖原业务异常。

- [ ] **Step 4: 在公共 Runner 建立单一保存钩子**

`ModeRunnerBase` 增加 `_save_failure_diagnostic(label, screen, *, action=None, source="", targets=(), attempt=0, conclusion="UNKNOWN")`：先调用 `runtime.save_diagnostic`，再从 `self.machine.templates.evidence` 调用适配器。把公共 Runner 的 dry-run 失败、黑屏超时、状态超时、转场超时和绝对超时改用该钩子。

- [ ] **Step 5: 接入竞技场和远征的现有包装方法**

- ArenaRunner 新增同名 `_save_failure_diagnostic`，只替换它自己的 timeout、no-transition、refresh failure 诊断调用。
- ExpeditionRunner 复用现有 `_diagnostic` 方法，在保存 legacy PNG 后追加 profile 诊断。
- StoryRunner 与 HeroSynthesisRunner 通过 `ModeRunnerBase` 自动获得，不分别复制实现。

- [ ] **Step 6: 写四条路线接入回归并运行**

测试只触发已有超时出口，断言 legacy PNG 和同名目录内 `evidence.json` 同时存在；不改变异常消息和点击序列。

Run:

```text
pytest tests/test_evidence_diagnostics.py tests/test_story_runner.py tests/test_arena_runner.py tests/test_expedition_runner.py tests/test_hero_synthesis.py -q
```

Expected: all pass.

- [ ] **Step 7: 提交 Task 5**

```text
git add core/evidence_diagnostics.py games/epic7/runner_base.py games/epic7/arena.py games/epic7/expedition.py tests/test_evidence_diagnostics.py tests/test_story_runner.py tests/test_arena_runner.py tests/test_expedition_runner.py tests/test_hero_synthesis.py
git diff --cached --check
git commit -m "feat: save route visual evidence diagnostics"
```

## Task 6: 文档校正与最终验收

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/EXTENDING.md`
- Modify: `docs/maintenance/arena.md`
- Modify: `docs/maintenance/story.md`
- Modify: `docs/maintenance/expedition.md`
- Modify: `docs/maintenance/hero_synthesis.md`
- Modify: `docs/superpowers/plans/2026-08-28-visual-evidence-review-fixes.md`

- [ ] **Step 1: 更新维护说明**

明确：

- 低于阈值仍会显示数值分数；
- `config` 指向应修改的证据文件；
- 复杂页面由 route evaluator 与生产状态机共用；
- 自包含目录和 legacy PNG 的对应关系；
- checker 当前命令支持竞技场，其他路线通过真实失败诊断使用 profile。

- [ ] **Step 2: 运行专项与全量验证**

Run:

```text
pytest tests/test_visual_evidence.py tests/test_matcher.py tests/test_arena_evidence.py tests/test_story_evidence.py tests/test_expedition_evidence.py tests/test_hero_evidence.py tests/test_evidence_diagnostics.py -q
pytest -q
python -m compileall -q core desktop games tests tools
git diff --check
```

Expected: all pass, compile exit 0, diff check exit 0.

- [ ] **Step 3: 用真实 fixture 验证检查器**

Run:

```text
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/selected.png
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/quick_battle_selected_live_20260826.png
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png
```

Expected:

- selected fixture：`arena.selected=SAFE`；
- quick fixture：`arena.team=SAFE`；
- list fixture：未通过的 atoms 仍输出数字分数；
- 每行包含 config、region、score、threshold。

- [ ] **Step 4: 检查提交和原工作区保护**

```text
git log --oneline --decorate -8
git status --short
git diff --name-only 7687c02..HEAD
```

确认只包含本计划文件；原 `main` 工作区中的既有未提交文件没有被删除或覆盖。

- [ ] **Step 5: 提交文档**

```text
git add docs/ARCHITECTURE.md docs/EXTENDING.md docs/maintenance docs/superpowers/plans/2026-08-28-visual-evidence-review-fixes.md
git diff --cached --check
git commit -m "docs: explain visual evidence failure maintenance"
```

## 实机验收边界

本计划完成后只能声明离线修复通过。四条正式路线仍需用户各执行一轮完整模拟器流程，检查失败时是否同时生成 legacy PNG 和自包含证据目录；没有实机日志时不得声明真实游戏闭环已经重新验收。
