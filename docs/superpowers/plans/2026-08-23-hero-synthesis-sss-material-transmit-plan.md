# 英雄合成 SSS 材料转传送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在模拟器英雄合成流程中发现 SSS 材料时停止合成，传送当前无等级副本，并在传送完成后继续当前轮。

**Architecture:** 扩展 `HeroSynthStateMachine` 的材料页和英雄列表分支。材料页新增 SSS 标记检测；命中后设置待传送标志并点击返回，英雄列表根据标志点击右下角“传送英雄”，复用现有传送选择、确认和结果处理。触发 SSS 材料只作为中止条件，传送目标由进入合成前的当前英雄上下文决定。

**Tech Stack:** Python 3、OpenCV、pytest、LDPlayer 实时截图/点击后端。

---

### Task 1: 固化现场模板和失败测试

**Files:**
- Create: `games/epic7/templates/hero/sss_material.png`
- Create: `tests/fixtures/epic7_hero/imprint_sss_material.png`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 从现场截图裁出仅包含材料卡 SSS 标记的模板**

使用现场截图 `runtime_diagnostics/epic7_hero_synthesis/sss_material_capture.png`，裁剪右侧材料卡上的红色 `SSS` 标记区域；模板不包含整张人物卡。保存到 `games/epic7/templates/hero/sss_material.png`，完整现场画面保存为 `tests/fixtures/epic7_hero/imprint_sss_material.png`。

- [ ] **Step 2: 写失败测试验证模板加载和材料检测**

在 `TemplateTests` 增加 `sss_material` 模板加载断言；在 `ImprintDecisionTests` 增加：

```python
def test_sss_material_aborts_imprint_before_clicking_material(self):
    m = machine()
    m.state = HeroSynthState.IMPRINT_ADD
    action = m.next_action(fixture("imprint_sss_material"))
    self.assertEqual("abort_imprint_to_transmit", action.name)
```

预期当前实现失败，因为 `HeroTemplates` 没有 `sss_material`，且材料页会返回 `add_material_*`。

- [ ] **Step 3: 运行失败测试确认复现**

运行：

```bash
python -m pytest tests/test_hero_synthesis.py::TemplateTests::test_all_templates_load tests/test_hero_synthesis.py::ImprintDecisionTests::test_sss_material_aborts_imprint_before_clicking_material -q
```

预期：失败，原因是模板字段或动作尚未实现。

### Task 2: 实现 SSS 材料中止和当前副本传送入口

**Files:**
- Modify: `games/epic7/hero_synthesis.py`
- Modify: `tests/test_hero_synthesis.py`

- [ ] **Step 1: 扩展模板和状态上下文**

在 `HeroTemplates` 增加 `sss_material`；在 `build_hero_templates` 加载 `hero/sss_material.png`。在状态机增加：

```python
_MATERIAL_SSS_REGION = (1750, 350, 230, 650)
_TRANSMIT_ENTRY_POINT = (1735, 1060)
pending_transmit_target: bool = False
```

`pending_transmit_target` 只表示“当前列表选中的无等级副本待传送”，不保存触发判断的材料卡。

- [ ] **Step 2: 增加 SSS 材料检测函数**

使用 `find_template` 在 `_MATERIAL_SSS_REGION` 内匹配 `sss_material`，阈值从 `0.78` 开始；检测范围只覆盖右侧材料卡区域，避免把左侧当前英雄的评级误判为材料。

```python
def _sss_material_present(self, screen: np.ndarray) -> bool:
    return self._locate(
        screen,
        "sss_material",
        0.78,
        region_override=self._MATERIAL_SSS_REGION,
    ) is not None
```

- [ ] **Step 3: 在材料页优先中止合成**

在 `next_action` 的绿色刻印按钮分支之前增加：

```python
if self.state is HeroSynthState.IMPRINT_ADD and self._sss_material_present(screen):
    self.pending_transmit_target = True
    back = self._back_action(screen)
    if back is None:
        raise UnrecognizedScreen("发现 SSS 材料但刻印页面缺少返回箭头")
    return HeroAction("abort_imprint_to_transmit", back.point)
```

该分支必须先于 `_find_up_card`，确保不会点击 SSS 材料，也不会进入 `start_synthesis`。

- [ ] **Step 4: 在英雄列表增加传送入口动作**

在英雄列表决策中、筛选和普通卡决策之前增加：

```python
if self.pending_transmit_target:
    self.pending_transmit_target = False
    self.state = HeroSynthState.TRANSMIT_SELECT
    return HeroAction(
        "open_transmit_for_current_card",
        self._scaled_point(screen, self._TRANSMIT_ENTRY_POINT),
    )
```

实际运行中进入传送页后，现有 `auto_select_label` 分支继续判断当前副本是否已在传送槽；已选则启动传送，未选则复用右侧高亮卡选择逻辑。

- [ ] **Step 5: 增加动作日志提示并运行专项测试**

在 `_decision_hint` 增加 `abort_imprint_to_transmit` 和 `open_transmit_for_current_card` 的中文说明，运行：

```bash
python -m pytest tests/test_hero_synthesis.py -q
```

预期：原有英雄合成测试和新增中止测试全部通过。

### Task 3: 验证传送后继续本轮

**Files:**
- Modify: `tests/test_hero_synthesis.py`
- Modify: `docs/architecture.md`（仅补充已实现的分支说明）

- [ ] **Step 1: 写状态机回归测试**

增加测试覆盖动作顺序：

```text
imprint_sss_material
-> abort_imprint_to_transmit
-> list_after_abort
-> open_transmit_for_current_card
-> transmit_select/transmit_selected
-> start_transmit
-> transmit_confirm
-> confirm_transmit
-> reward_popup
-> close_reward
-> list_no_reddot
-> next_card_*
```

断言不出现 `add_material_*`、`start_synthesis`，且传送完成后的 `next_card_*` 仍保持 `completed_cycles == 0`。

- [ ] **Step 2: 运行传送和英雄合成专项回归**

运行：

```bash
python -m pytest tests/test_hero_synthesis.py tests/test_navigation.py -q
```

预期：全部通过。

- [ ] **Step 3: 更新架构说明并检查差异**

只在英雄合成流程图中增加“材料出现 SSS -> 当前副本转传送 -> 回列表继续本轮”分支；运行 `git diff --check`。

### Task 4: 全量验证和模拟器实测

**Files:**
- No new source files.

- [ ] **Step 1: 运行全量测试**

运行：

```bash
python -m pytest -q
```

预期：0 failures。

- [ ] **Step 2: 启动单轮模拟器实测**

保持模拟器在酒馆或英雄合成加材料页面，运行：

```bash
python -u -m auto_game_unified.main --mode hero_synthesis --max-cycles 1 --live --confirm RUN --window-backend emulator
```

观察日志必须出现：

```text
发现 SSS 材料 -> 中止当前合成 -> 传送当前无等级副本 -> 传送完成 -> 继续当前轮
```

- [ ] **Step 3: 提交实现**

```bash
git add games/epic7/hero_synthesis.py games/epic7/templates/hero/sss_material.png tests/fixtures/epic7_hero/imprint_sss_material.png tests/test_hero_synthesis.py docs/architecture.md
git commit -m "feat: route hero synthesis duplicates to transmit"
```
