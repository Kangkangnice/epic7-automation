# Visual Evidence Maintainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 集中管理模拟器路线的视觉证据，使普通 E7 UI 改版主要只需替换模板或修改证据配置，不改业务状态机。

**Architecture:** 每条路线维护独立的视觉证据清单，公共层只提供原子证据、页面组合和配置校验。现有业务状态机和 Runner 保持职责不变；迁移先统一视觉查询和诊断，再评估跨路线转场抽象。

**Tech Stack:** Python 3.11, OpenCV, NumPy, pytest, 现有 `Runtime`/`find_template`/状态机。

**Execution status:** Tasks 1–6 implemented; offline verification passed. Real-device acceptance remains a user-owned step per project safety rules.

---

## 工作区与基线约束

- 当前仓库为 `D:\AI\codex\auto_game\auto_game_unified`。
- 工作区已有用户和前序路线的未提交改动，不得 reset、clean、覆盖或顺手整理它们。
- 当前阶段只提交本计划新增或明确迁移的文件；每批提交前用 `git show --name-only --format=oneline HEAD` 检查上一批范围。
- 视觉动作必须遵守 `docs/TRANSITION_CONTRACTS.md` 和 `AGENTS.md`：来源、候选动作、来源退出、目标进入、业务完成分别记录；`UNKNOWN` 不得按成功处理。
- 每个新增行为必须先写一个会失败的测试并运行确认失败，再写最小实现。

## 文件责任地图

### 第一批：竞技场样板

- Create: `games/epic7/evidence/__init__.py` — 证据公共导出。
- Create: `games/epic7/evidence/common.py` — 原子证据、页面证据和配置校验的最小数据结构。
- Create: `games/epic7/evidence/arena.py` — 竞技场证据清单，仅放模板、区域、阈值和页面组合。
- Modify: `games/epic7/arena.py` — 使用竞技场证据清单，不改变状态机业务顺序。
- Create: `tests/test_visual_evidence.py` — 公共结构、三态页面组合和配置校验。
- Create: `tests/test_arena_evidence.py` — 竞技场证据清单与现有模板的回归。

### 第二批：诊断检查

- Create: `core/evidence_diagnostics.py` — 自包含证据诊断数据与裁剪保存。
- Create: `tools/check_evidence.py` — 只读单截图检查命令。
- Create: `tests/test_evidence_diagnostics.py` — JSON、裁剪和只读检查输出。
- Modify: `core/runtime.py` 或各 Runner 的失败路径 — 仅在现有诊断入口能传递证据数据时接入；优先使用最小改动。

### 第三批：主线、远征

- Create: `games/epic7/evidence/story.py`。
- Create: `games/epic7/evidence/expedition.py`。
- Modify: `games/epic7/story.py`、`games/epic7/expedition.py` — 只替换视觉配置读取。
- Create/Modify: 对应已有测试文件，补齐正例、反例和配置诊断断言。

### 第四批：英雄合成

- Create: `games/epic7/evidence/hero_synthesis.py`。
- Modify: `games/epic7/hero_synthesis.py` — 只迁移纯视觉配置，保持 SSS、同名副本、传送事务和动态切换逻辑。
- Modify: `tests/test_hero_synthesis.py` — 增加证据清单回归，不改已有业务断言。

### 第五批：文档与新路线模板

- Modify: `docs/EXTENDING.md` — 增加最小证据清单示例和维护入口说明。
- Create: `docs/maintenance/arena.md`、`docs/maintenance/story.md`、`docs/maintenance/expedition.md`、`docs/maintenance/hero_synthesis.md`。
- Modify: `docs/ARCHITECTURE.md`、`docs/TODO.md`、`README.md` — 只记录已通过测试和实机证据的状态。

## Task 1: 建立公共视觉证据结构

**Files:**
- Create: `tests/test_visual_evidence.py`
- Create: `games/epic7/evidence/__init__.py`
- Create: `games/epic7/evidence/common.py`

- [ ] **Step 1: Write failing tests for evidence definitions and validation**

测试必须覆盖：

```python
def test_page_evidence_is_safe_only_when_all_required_and_one_any_group_match():
    page = PageEvidence(
        key="arena.list",
        required=("list_ready",),
        any_of=(("opponent_row", "opponent_detail"),),
        forbidden=("network_retry",),
    )
    assert page.evaluate({"list_ready": True, "opponent_row": True}) is EvidenceState.SAFE
    assert page.evaluate({"list_ready": True, "opponent_row": False}) is EvidenceState.UNKNOWN
    assert page.evaluate({"list_ready": True, "opponent_row": True, "network_retry": True}) is EvidenceState.UNSAFE

def test_validate_evidence_profile_rejects_missing_template_bad_threshold_and_unknown_reference():
    profile = EvidenceProfile(
        atoms={"list_ready": AtomEvidence("list_ready", "missing.png", (0, 0, 10, 10), 1.2)},
        pages=(PageEvidence("arena.list", ("missing_atom",)),),
    )
    errors = validate_profile(profile, Path("."))
    assert "模板不存在" in " ".join(errors)
    assert "阈值" in " ".join(errors)
    assert "引用不存在" in " ".join(errors)
```

- [ ] **Step 2: Run the focused tests and verify the expected RED failure**

Run: `pytest tests/test_visual_evidence.py -q`

Expected: FAIL because `games.epic7.evidence.common` and its types do not yet exist.

- [ ] **Step 3: Implement the minimal immutable structures**

Implement only:

```python
class EvidenceState(Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class AtomEvidence:
    key: str
    template_path: str
    region: tuple[int, int, int, int]
    threshold: float
    description: str = ""

@dataclass(frozen=True)
class PageEvidence:
    key: str
    required: tuple[str, ...] = ()
    any_of: tuple[tuple[str, ...], ...] = ()
    forbidden: tuple[str, ...] = ()

    def evaluate(self, observations: Mapping[str, bool]) -> EvidenceState:
        if any(observations.get(key, False) for key in self.forbidden):
            return EvidenceState.UNSAFE
        if not all(observations.get(key, False) for key in self.required):
            return EvidenceState.UNKNOWN
        if not all(any(observations.get(key, False) for key in group) for group in self.any_of):
            return EvidenceState.UNKNOWN
        return EvidenceState.SAFE
```

`validate_profile(profile, root)` must return human-readable errors and never mutate the profile. Reject missing templates, threshold outside `[0, 1]`, non-positive regions or regions whose starting point is outside the reference frame, duplicate keys and references to unknown atoms. Regions may extend past the bottom or right edge because the existing matcher clips NumPy slices at the live screenshot boundary.

- [ ] **Step 4: Run focused tests and all existing unit tests touching imports**

Run: `pytest tests/test_visual_evidence.py tests/test_matcher.py -q`

Expected: all pass.

- [ ] **Step 5: Commit the isolated public structure**

```text
git add games/epic7/evidence tests/test_visual_evidence.py
git commit -m "feat: add visual evidence profile primitives"
```

## Task 2: Migrate arena visual configuration

**Files:**
- Create: `games/epic7/evidence/arena.py`
- Create: `tests/test_arena_evidence.py`
- Modify: `games/epic7/arena.py` only where `_REGIONS`, `_THRESHOLDS`, template loading, and page evidence are read.

- [ ] **Step 1: Add failing tests proving the registry contains current arena evidence**

```python
def test_arena_profile_declares_existing_templates_and_regions():
    profile = build_arena_evidence(TEMPLATES)
    errors = validate_profile(profile, TEMPLATES.parent)
    assert errors == []
    assert profile.atom("list_ready").threshold == 0.88
    assert profile.atom("battle_start").region == (900, 930, 550, 202)

def test_arena_page_evidence_marks_popup_conflict_unknown_or_unsafe():
    profile = build_arena_evidence(TEMPLATES)
    page = profile.page("arena.team")
    assert page.evaluate({"battle_start": True}) is EvidenceState.SAFE
    assert page.evaluate({"battle_start": True, "no_ticket": True}) is EvidenceState.UNSAFE
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `pytest tests/test_arena_evidence.py -q`

Expected: FAIL because the arena profile module and adapter do not exist.

- [ ] **Step 3: Move only current arena constants into `evidence/arena.py`**

The profile must preserve these current values exactly: reference size `(1982, 1132)`, current `_REGIONS`, current `_THRESHOLDS`, and current template filenames. Page keys must cover list, selected, team, battle, result, ticket popup, friendship offer, and refresh confirmation. Do not change thresholds while moving them.

- [ ] **Step 4: Adapt `ArenaTemplates` and `_locate` to read the profile**

Keep `ArenaTemplates` API compatible for existing tests. `build_templates()` may load the profile and expose it as a frozen field. `_locate()` must obtain the threshold and region from the profile while returning the same `Match` values. No state transition, click point, retry limit, or business decision may change in this task.

- [ ] **Step 5: Run arena tests and compare behavior**

Run: `pytest tests/test_arena_evidence.py tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_quick_battle_route_integration.py -q`

Expected: all pass with no changed action sequence in existing tests.

- [ ] **Step 6: Commit arena migration**

```text
git add games/epic7/evidence/arena.py tests/test_arena_evidence.py games/epic7/arena.py
git commit -m "refactor: centralize arena visual evidence"
```

## Task 3: Add self-contained evidence diagnostics and read-only checker

**Files:**
- Create: `core/evidence_diagnostics.py`
- Create: `tools/check_evidence.py`
- Create: `tests/test_evidence_diagnostics.py`

- [ ] **Step 1: Write failing tests for diagnostic JSON and crop output**

The test must call real production functions and assert that the output contains `mode`, `action`, `source`, `targets`, `attempt`, `evidence`, `score`, `threshold`, and `conclusion`, plus `screen.png`, `source.png`, and `target.png` when regions are supplied.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_evidence_diagnostics.py -q`

Expected: FAIL because the diagnostic module does not exist.

- [ ] **Step 3: Implement `write_evidence_diagnostic(...)`**

The function writes one JSON file and optional RGB crops under a caller-provided directory. It must create directories, preserve numeric values, and never infer success. Do not alter the existing `Runtime.save_diagnostic` format in this task.

- [ ] **Step 4: Implement the checker CLI**

`tools/check_evidence.py` accepts `--mode arena --screen tests/fixtures/epic7_arena/list.png`, loads the corresponding profile, evaluates every atom in its declared region, and prints key, score, threshold, location, and page states. It is read-only and exits non-zero for missing files or invalid profiles. It must not lower thresholds or write templates.

- [ ] **Step 5: Run focused tests and a real fixture check**

Run:

```text
pytest tests/test_evidence_diagnostics.py -q
python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png
```

Expected: tests pass; checker prints evidence rows and no files outside its explicit output (none by default).

- [ ] **Step 6: Commit diagnostics**

```text
git add core/evidence_diagnostics.py tools/check_evidence.py tests/test_evidence_diagnostics.py
git commit -m "feat: add visual evidence diagnostics checker"
```

## Task 4: Migrate story and expedition profiles

**Files:**
- Create: `games/epic7/evidence/story.py`
- Create: `games/epic7/evidence/expedition.py`
- Modify: `games/epic7/story.py`, `games/epic7/expedition.py` only for visual profile reads.
- Modify: existing `tests/test_epic7_story.py`, `tests/test_epic7_expedition.py`, `tests/test_story_runner.py`, `tests/test_expedition_runner.py`.

- [ ] **Step 1: Add profile validation and page-combination tests using existing template paths**
- [ ] **Step 2: Run those focused tests and confirm RED**
- [ ] **Step 3: Move current regions, thresholds and page combinations without changing state transitions**
- [ ] **Step 4: Run route-specific tests and verify action sequences are unchanged**
- [ ] **Step 5: Commit story and expedition separately**

Use commits `refactor: centralize story visual evidence` and `refactor: centralize expedition visual evidence`; never combine the two routes in one commit.

## Task 5: Migrate hero synthesis visual configuration

**Files:**
- Create: `games/epic7/evidence/hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py` only for pure template/region/threshold reads.
- Modify: `tests/test_hero_synthesis.py` with profile regression tests.

- [ ] **Step 1: Add a registry test for current simulator templates and high-risk evidence**
- [ ] **Step 2: Run RED**
- [ ] **Step 3: Move pure visual constants only**
- [ ] **Step 4: Verify SSS priority, adjacent same-name duplicate handling, material safety and transmit transaction tests unchanged**
- [ ] **Step 5: Run the complete hero synthesis suite and commit**

Do not split the 2500-line module in this task. Do not change PC behavior or enable PC transition contracts.

## Task 6: Document maintenance and new-route extension

**Files:**
- Create: `docs/maintenance/arena.md`, `docs/maintenance/story.md`, `docs/maintenance/expedition.md`, `docs/maintenance/hero_synthesis.md`
- Modify: `docs/EXTENDING.md`, `docs/ARCHITECTURE.md`, `docs/TODO.md`, `README.md`

- [ ] **Step 1: Write maintenance docs that point to the exact evidence file and checker command**
- [ ] **Step 2: Add a minimal new-route evidence example to `docs/EXTENDING.md`**
- [ ] **Step 3: Update architecture and TODO only for completed migrations**
- [ ] **Step 4: Run documentation link/path checks and the full test suite**
- [ ] **Step 5: Commit documentation separately**

## Final verification and handoff

- [ ] Run route-specific suites after each route.
- [ ] Run `pytest -q` from repository root.
- [ ] Run `python -m compileall core desktop games tests tools`.
- [ ] Run `git diff --check`.
- [ ] Inspect each plan commit with `git show --name-only --format=oneline HEAD`; confirm the listed files are limited to that task before starting the next task.
- [ ] Run the checker against at least one valid and one invalid arena fixture.
- [ ] For real-game claims, require the user to complete one full simulator loop per migrated route; offline tests alone do not prove real-device support.
- [ ] Report remaining dirty files from before the plan separately; do not include them in this work's completion claim.
