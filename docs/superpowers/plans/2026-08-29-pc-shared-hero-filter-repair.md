# PC Shared Hero Filter Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除旧 `templates_pc` 资产体系，并让 PC 与模拟器在统一画布上可靠识别英雄筛选面板且不再反复开关。

**Architecture:** PC 差异只保留在 `Epic7PcWindow` 的截图补边和点击坐标换算中，英雄状态机继续使用共享模板、统一坐标和统一转场契约。筛选面板使用“级别 + 属性 + 三星状态”组合证据，只校准这三个低风险局部证据，不改变 3S、材料和传送安全阈值。

**Tech Stack:** Python 3、OpenCV、pytest、Git；参考画布 `1982x1132`。

---

## 文件结构与修改边界

- Modify: `games/epic7/evidence/hero_synthesis.py` — 只保存筛选证据区域与门槛。
- Modify: `games/epic7/hero_synthesis.py` — 组合筛选证据、动作原因日志、移除模板目录名对业务模式的控制。
- Modify: `tests/test_hero_synthesis.py` — 模拟器回归、PC 正反样本和日志断言。
- Create: `tests/fixtures/epic7_hero/pc_filter_open_unselected_20260829.png` — 当前兼容画布的筛选打开正样本。
- Create: `tests/fixtures/epic7_hero/pc_filter_closed_20260829.png` — 当前兼容画布的筛选关闭负样本。
- Delete: `games/epic7/templates_pc/` — 70 个旧 PC 模板文件。
- Delete: `tests/test_pc_hero_synthesis_evidence.py` — 旧 PC 原始坐标与旧模板测试。
- Delete: `tests/test_pc_story_evidence.py` — 旧 PC 原始坐标与旧模板测试。
- Delete: `tests/test_pc_battle_controls.py` — 依赖旧 PC 模板的测试。
- Modify: `tests/test_quick_battle_route_integration.py` — 删除只验证旧 `templates_pc` 的用例，保留共享路线测试。
- Modify: `docs/PC_TEMPLATE_MIGRATION.md` — 记录单模板目录和逐证据校准规则。
- Modify: `docs/USER_GUIDE.md` — 删除“可能存在 templates_pc”的说明。
- Modify: `docs/TODO.md` — 把其他 PC 路线记录为待用共享模板重新取证，而不是依赖旧目录。

历史 `docs/superpowers/specs/` 和 `docs/superpowers/plans/` 中的 `templates_pc` 文字保留，因为它们记录当时的设计，不是当前操作手册。

### Task 1: 固化本次真实 PC 故障为正反回归样本

**Files:**
- Create: `tests/fixtures/epic7_hero/pc_filter_open_unselected_20260829.png`
- Create: `tests/fixtures/epic7_hero/pc_filter_closed_20260829.png`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 复制已保存的真实画面，不重新截图**

Run:

```powershell
Copy-Item -LiteralPath 'runtime_diagnostics\epic7_hero_synthesis\20260829_185635_098904_manual_stop.png' -Destination 'tests\fixtures\epic7_hero\pc_filter_open_unselected_20260829.png'
Copy-Item -LiteralPath 'runtime_diagnostics\epic7_hero_synthesis\20260829_174936_287634_retry_exhausted_open_filter.png' -Destination 'tests\fixtures\epic7_hero\pc_filter_closed_20260829.png'
```

Expected: 两张 fixture 都是 `1982x1132`，第一张可见筛选面板，第二张为英雄列表。

- [ ] **Step 2: 为 PC 正反画面添加失败测试**

在 `tests/test_hero_synthesis.py` 的筛选测试组中加入：

```python
def test_current_pc_filter_open_is_recognized_as_unselected():
    m = machine()
    screen = fixture("pc_filter_open_unselected_20260829")

    observation = m._observe_filter(screen)
    action = m.next_action(screen)

    self.assertIs(
        FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
        observation,
    )
    self.assertEqual("select_star3", action.name)
    self.assertEqual((1110, 636), action.point)


def test_current_pc_filter_closed_is_not_misread_as_open():
    m = machine()
    screen = fixture("pc_filter_closed_20260829")

    observation = m._observe_filter(screen)

    self.assertNotIn(
        observation,
        {
            FilterObservation.FILTER_OPEN_STAR3_SELECTED,
            FilterObservation.FILTER_OPEN_STAR3_UNSELECTED,
        },
    )
```

- [ ] **Step 3: 运行测试并确认正样本稳定失败、负样本通过**

Run:

```powershell
python -m pytest -q auto_game_unified/tests/test_hero_synthesis.py -k 'current_pc_filter'
```

Expected: `test_current_pc_filter_open_is_recognized_as_unselected` FAIL，实际为 `FilterObservation.UNKNOWN`；关闭页测试 PASS。

### Task 2: 只校准筛选组合证据并输出真实分数

**Files:**
- Modify: `games/epic7/evidence/hero_synthesis.py`
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 添加阈值范围保护测试**

在 `tests/test_hero_synthesis.py` 加入：

```python
def test_only_filter_panel_thresholds_are_relaxed():
    self.assertEqual(0.75, HeroSynthStateMachine._THRESHOLDS["filter_level_label"])
    self.assertEqual(0.75, HeroSynthStateMachine._THRESHOLDS["filter_attribute_label"])
    self.assertEqual(0.86, HeroSynthStateMachine._THRESHOLDS["filter_star3_unselected"])
    self.assertEqual(0.90, HeroSynthStateMachine._THRESHOLDS["rating_sss"])
    self.assertEqual(0.80, HeroSynthStateMachine._THRESHOLDS["sss_material"])
    self.assertEqual(0.90, HeroSynthStateMachine._THRESHOLDS["transmit_reward_title"])
```

- [ ] **Step 2: 运行阈值测试并确认失败**

Run:

```powershell
python -m pytest -q auto_game_unified/tests/test_hero_synthesis.py -k 'only_filter_panel_thresholds'
```

Expected: FAIL，显示筛选阈值仍为 `0.80/0.82/0.90`。

- [ ] **Step 3: 修改集中证据配置中的三个门槛**

将 `games/epic7/evidence/hero_synthesis.py` 中以下三行精确替换：

```python
"filter_level_label": 0.75,
"filter_attribute_label": 0.75,
"filter_star3_unselected": 0.86,
```

不要修改同一字典中的其他条目。

这三个值分别给当前 PC 正样本 `0.795/0.789/0.898` 留出余量；关闭负样本只有 `0.182/0.151/0.153`。必须同时满足面板锚点和一种三星状态，因此不把单个低分当成页面成立。

- [ ] **Step 4: 记录筛选证据分数并写入动作原因**

在 `HeroSynthStateMachine.__init__` 初始化：

```python
self._last_filter_scores: dict[str, float] = {}
```

在 `_observe_filter()` 中对以下四项以 `threshold=0.0` 读取最高分并保存，然后用集中配置门槛比较：

```python
keys = (
    "filter_level_label",
    "filter_attribute_label",
    "filter_star3_selected",
    "filter_star3_unselected",
)
self._last_filter_scores = {
    key: (
        match.score
        if (match := self._locate(screen, key, 0.0)) is not None
        else -1.0
    )
    for key in keys
}
```

新增格式化方法：

```python
def _filter_evidence_summary(self) -> str:
    def item(label: str, key: str) -> str:
        return (
            f"{label}={self._last_filter_scores.get(key, -1.0):.3f}/"
            f"{self._threshold(key):.2f}"
        )

    return " ".join(
        (
            item("级别", "filter_level_label"),
            item("属性", "filter_attribute_label"),
            item("三星已选", "filter_star3_selected"),
            item("三星未选", "filter_star3_unselected"),
        )
    )
```

`select_star3`、`close_filter` 和 `open_filter` 的 `reason` 都附加该摘要，使日志能区分点击未生效和目标证据不足。

- [ ] **Step 5: 添加日志断言**

在 `tests/test_hero_synthesis.py` 加入：

```python
def test_current_pc_filter_action_reason_contains_scores():
    action = machine().next_action(fixture("pc_filter_open_unselected_20260829"))

    self.assertIn("级别=", action.reason)
    self.assertIn("属性=", action.reason)
    self.assertIn("三星未选=", action.reason)
    self.assertIn("/0.75", action.reason)
    self.assertIn("/0.86", action.reason)
```

- [ ] **Step 6: 运行筛选回归测试**

Run:

```powershell
python -m pytest -q auto_game_unified/tests/test_hero_synthesis.py -k 'filter or current_pc'
```

Expected: 全部 PASS；现有模拟器 `filter_open.png` 和 `filter_open_star3_unselected.png` 仍得到原动作。

- [ ] **Step 7: 提交筛选闭环修复**

```powershell
git add -- games/epic7/evidence/hero_synthesis.py games/epic7/hero_synthesis.py tests/test_hero_synthesis.py tests/fixtures/epic7_hero/pc_filter_open_unselected_20260829.png tests/fixtures/epic7_hero/pc_filter_closed_20260829.png
git commit -m "fix: recognize shared PC hero filter evidence"
```

### Task 3: 解除模板目录名与旧 PC 业务分支的绑定

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: 添加共享业务坐标测试**

在 `tests/test_hero_synthesis.py` 加入：

```python
def test_shared_templates_never_activate_legacy_pc_business_coordinates():
    templates = build_hero_templates(TEMPLATES)
    m = HeroSynthStateMachine(templates)

    action = m.next_action(fixture("list_reddot"))

    self.assertFalse(templates.pc_client)
    self.assertEqual("open_filter", action.name)
    self.assertEqual((1540, 191), action.point)
```

扩充 `tests/test_main_story.py::test_pc_run_uses_shared_template_root`：除了断言目录名为 `templates`，还断言 `build_machine` 没收到会切换旧业务坐标的额外参数。

- [ ] **Step 2: 删除目录名推断**

在 `build_hero_templates()` 中删除：

```python
is_pc = template_root.name == "templates_pc"
```

所有存在于共享目录的可选证据按文件是否存在加载；返回对象固定为统一业务语义：

```python
filter_attribute_label=(
    load_template(str(filter_attribute)) if filter_attribute.exists() else None
),
filter_star3_unselected=(
    load_template(str(filter_star3_unselected))
    if filter_star3_unselected.exists()
    else None
),
pc_client=False,
assume_non_max_rating=False,
```

其他可选模板同样只检查文件存在性，不再检查目录名称。

- [ ] **Step 3: 运行构建与启动链路测试**

Run:

```powershell
python -m pytest -q auto_game_unified/tests/test_hero_synthesis.py -k 'shared_templates_never' auto_game_unified/tests/test_main_story.py -k 'pc_run_uses_shared_template_root'
```

Expected: PASS；PC 后端仍使用共享模板，英雄动作仍为 `(1540,191)`。

- [ ] **Step 4: 提交目录解耦**

```powershell
git add -- games/epic7/hero_synthesis.py tests/test_hero_synthesis.py tests/test_main_story.py
git commit -m "refactor: decouple hero logic from template directory names"
```

### Task 4: 删除旧 templates_pc 与虚假兼容测试

**Files:**
- Delete: `games/epic7/templates_pc/`
- Delete: `tests/test_pc_hero_synthesis_evidence.py`
- Delete: `tests/test_pc_story_evidence.py`
- Delete: `tests/test_pc_battle_controls.py`
- Modify: `tests/test_quick_battle_route_integration.py`
- Modify: `docs/PC_TEMPLATE_MIGRATION.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/TODO.md`

- [ ] **Step 1: 删除前验证精确目标**

Run:

```powershell
Resolve-Path -LiteralPath 'games\epic7\templates_pc'
git ls-files games/epic7/templates_pc | Measure-Object
```

Expected: 解析结果严格位于当前仓库的 `games\epic7\templates_pc`，Git 跟踪文件数为 `70`。

- [ ] **Step 2: 删除旧模板和只验证旧坐标体系的测试**

Run:

```powershell
git rm -r -- games/epic7/templates_pc
git rm -- tests/test_pc_hero_synthesis_evidence.py tests/test_pc_story_evidence.py tests/test_pc_battle_controls.py
```

这些删除可通过 Git 历史恢复；不要删除 `tests/fixtures/epic7_pc_hero`、`tests/fixtures/epic7_pc_story` 或本次新增兼容画布 fixture。

- [ ] **Step 3: 删除快速战斗测试中的旧目录用例**

从 `tests/test_quick_battle_route_integration.py` 只删除：

```python
def test_pc_story_templates_do_not_require_simulator_quick_battle_assets():
    templates = build_story_templates(
        ROOT / "games" / "epic7" / "templates_pc" / "story"
    )

    assert templates.quick_battle is None
```

保留同文件所有共享模板和业务集成测试。

- [ ] **Step 4: 更新当前文档**

`docs/PC_TEMPLATE_MIGRATION.md` 明确：

```markdown
仓库只维护 `games/epic7/templates/`。PC 和模拟器都先进入统一兼容画布，再使用同一套业务证据与坐标。某个 PC 页面不兼容时，先保存完整正反画面并改进共享证据；不得恢复整套 `templates_pc` 镜像。
```

`docs/USER_GUIDE.md` 删除“`templates_pc` 也可能包含候选模板或样本”，改为“共享模板存在不代表路线已通过 PC 实机验收”。

`docs/TODO.md` 把 PC 待办改为“各路线使用共享模板逐页补当前兼容画布正反样本并完成实跑”。

- [ ] **Step 5: 确认当前代码和操作文档不再引用旧目录**

Run:

```powershell
rg -n "templates_pc" games tests docs/PC_TEMPLATE_MIGRATION.md docs/USER_GUIDE.md docs/TODO.md
```

Expected: 无输出。历史设计文档不在本命令检查范围内。

- [ ] **Step 6: 提交旧资产删除**

```powershell
git add -- tests/test_quick_battle_route_integration.py docs/PC_TEMPLATE_MIGRATION.md docs/USER_GUIDE.md docs/TODO.md
git commit -m "chore: remove legacy PC template mirror"
```

### Task 5: 自动回归与实机烟雾验证

**Files:**
- Test only; no production files unless a test exposes an in-scope defect.

- [ ] **Step 1: 运行英雄合成与启动链路测试**

Run:

```powershell
python -m pytest -q auto_game_unified/tests/test_hero_synthesis.py auto_game_unified/tests/test_main_story.py auto_game_unified/tests/test_pc_shared_navigation.py
```

Expected: PASS，无筛选、3S、材料或传送回归。

- [ ] **Step 2: 运行完整测试**

Run:

```powershell
python -m pytest -q auto_game_unified/tests
```

Expected: PASS。若存在实施前就已出现且属于其他未提交改动的失败，保存完整测试名和输出，不修改无关路线来掩盖失败。

- [ ] **Step 3: 检查改动边界**

Run:

```powershell
git diff --check
git status --short
git diff --name-status HEAD~3..HEAD
```

Expected: 没有空白错误；本次提交只包含本计划列出的文件。工作区中原有的竞技场、远征、主线和桌面未提交改动保持原状。

- [ ] **Step 4: PC 实机验证第一段闭环**

前提：PC 客户端停在大厅，窗口客户区为 `1920x1080`。从桌面界面选择“PC 客户端 → 英雄合成 → 1 轮”运行并观察到：

1. 进入英雄信息页；
2. 只点击一次漏斗打开筛选；
3. 日志输出级别、属性、三星已选/未选的实际分数；
4. 未选中时点击三星；
5. 看到三星已选中后关闭筛选；
6. 返回英雄列表并开始首张英雄判断，没有再次执行 `open_filter`。

Expected: 以上六项全部成立。若在后续合成/传送环节出现新 PC 问题，保存为独立诊断，不把它误归为本次筛选修复成功条件。

- [ ] **Step 5: 提交仅在实机验证中发现的筛选范围修正**

只有当失败仍属于本计划定义的筛选进入/退出证据时才修改并提交：

```powershell
git add -- games/epic7/evidence/hero_synthesis.py games/epic7/hero_synthesis.py tests/test_hero_synthesis.py
git commit -m "fix: finalize shared hero filter transition evidence"
```

如果没有额外修改，不创建空提交。
