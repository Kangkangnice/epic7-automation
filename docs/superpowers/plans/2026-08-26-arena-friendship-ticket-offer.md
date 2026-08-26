# Arena Friendship Ticket Offer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模拟器竞技场只在左侧 `100 友情点 → 5 旗帜` 已选中时购买，忽略动态持有余额并永久拒绝右侧钻石方案。

**Architecture:** 保留现有 `ArenaStateMachine`、三锚点校验和 Runner 不可逆转场事务，只替换错误的报价 fixture/template，并把报价搜索区域收紧到左侧固定卡片。完整真实截图负责回归，局部模板只包含绿色友情点图标、固定 `100 → 5` 和黄色选中框，不包含“持有”余额。

**Tech Stack:** Python 3、NumPy、OpenCV 模板匹配、Pillow、unittest/pytest。

---

## 文件结构

- Create: `tests/fixtures/epic7_arena/friendship_ticket_offer_live_20260826.png` — 当前客户端完整购买弹窗。
- Modify: `tests/test_project_layout.py` — 登记新的完整 fixture。
- Modify: `tests/test_epic7_arena.py` — 合法报价、动态余额和钻石反例状态机测试。
- Modify: `tests/test_arena_runner.py` — 购买转场使用合法报价 fixture。
- Modify: `tests/test_ticket_exhaustion.py` — 当天已购买分支使用合法报价 fixture。
- Modify: `games/epic7/templates/friendship_ticket_offer.png` — 不含动态余额的左侧已选中报价模板。
- Modify: `games/epic7/arena.py` — 收紧报价区域并修正日志语义。
- Modify: `docs/TRANSITION_CONTRACTS.md` — 修正资源购买契约。
- Modify: `README.md`、`docs/USER_GUIDE.md` — 说明允许友情点、禁止钻石及余额不参与识别。

### Task 1: 用真实现场建立红色回归测试

**Files:**
- Create: `tests/fixtures/epic7_arena/friendship_ticket_offer_live_20260826.png`
- Modify: `tests/test_project_layout.py:21-42`
- Modify: `tests/test_epic7_arena.py:417-430`
- Modify: `tests/test_arena_runner.py:114-130`
- Modify: `tests/test_ticket_exhaustion.py:16-31`

- [ ] **Step 1: 保存当前完整 fixture 并登记文件名**

复制真实诊断图，不做裁剪：

```powershell
Copy-Item -LiteralPath runtime_diagnostics/epic7_arena/20260826_203947_231098_ticket_exhausted.png -Destination tests/fixtures/epic7_arena/friendship_ticket_offer_live_20260826.png
```

在 `test_epic7_arena_fixture_set_exists` 的集合中加入：

```python
"friendship_ticket_offer_live_20260826.png",
```

- [ ] **Step 2: 把状态机购买测试改成当前合法报价**

在 `tests/test_epic7_arena.py` 中加入并调整测试：

```python
def test_ticket_purchase_accepts_selected_friendship_offer(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)

    action = machine.next_action(load_fixture("friendship_ticket_offer_live_20260826"))

    self.assertEqual("purchase-friendship-ticket", action.name)
    self.assertIn("友情点100换5旗帜", action.reason)

def test_ticket_purchase_does_not_depend_on_dynamic_friendship_balance(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)
    screen = load_fixture("friendship_ticket_offer_live_20260826").copy()
    screen[660:715, 620:920] = 0

    action = machine.next_action(screen)

    self.assertEqual("purchase-friendship-ticket", action.name)

def test_ticket_purchase_rejects_selected_sky_stone_offer(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)

    with self.assertRaisesRegex(TicketExhausted, "100 friendship points"):
        machine.next_action(load_fixture("no_ticket"))

def test_ticket_purchase_rejects_missing_fixed_friendship_offer_evidence(self):
    machine = ArenaStateMachine(build_templates(TEMPLATES), initial_state=ArenaState.BATTLE)
    screen = load_fixture("friendship_ticket_offer_live_20260826").copy()
    screen[508:660, 568:920] = 0

    with self.assertRaises(TicketExhausted):
        machine.next_action(screen)
```

删除旧的 `test_ticket_purchase_requires_title_offer_and_button` 正向断言；保留其他无关测试。

- [ ] **Step 3: 让 Runner 测试改用合法报价 fixture**

在 `tests/test_arena_runner.py` 的购买重试测试和 `tests/test_ticket_exhaustion.py` 的当天限购测试中，把：

```python
fixture("no_ticket")
```

或对应的 `Image.open(FIXTURES / "no_ticket.png")` 改为：

```python
fixture("friendship_ticket_offer_live_20260826")
```

以及：

```python
Image.open(FIXTURES / "friendship_ticket_offer_live_20260826.png")
```

- [ ] **Step 4: 运行测试并确认按预期变红**

Run:

```powershell
pytest tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py tests/test_project_layout.py -q
```

Expected: 合法当前报价因旧模板不匹配而失败；旧 `no_ticket.png` 因旧逻辑错误接受钻石报价而没有抛出异常。失败原因必须来自报价识别，不得是 fixture 缺失或语法错误。

- [ ] **Step 5: 提交红色测试和真实 fixture**

```powershell
git add tests/fixtures/epic7_arena/friendship_ticket_offer_live_20260826.png tests/test_project_layout.py tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py
git commit -m "test: capture safe arena friendship offer"
```

### Task 2: 替换固定报价证据并通过专项测试

**Files:**
- Modify: `games/epic7/templates/friendship_ticket_offer.png`
- Modify: `games/epic7/arena.py:259-288,607-622`
- Test: `tests/test_epic7_arena.py`
- Test: `tests/test_arena_runner.py`
- Test: `tests/test_ticket_exhaustion.py`

- [ ] **Step 1: 从当前 fixture 裁取不含余额的左侧已选中报价**

使用 Pillow 从基准尺寸完整 fixture 裁取 `(568, 508, 920, 660)`；该范围包含黄色选中框上边和两侧、绿色友情点图标、`100`、箭头、旗帜图标和 `5`，在 `y=660` 前结束，因此排除下方“持有：11916”：

```powershell
python -c "from pathlib import Path; from PIL import Image; root=Path('.'); src=root/'tests/fixtures/epic7_arena/friendship_ticket_offer_live_20260826.png'; dst=root/'games/epic7/templates/friendship_ticket_offer.png'; Image.open(src).convert('RGB').crop((568,508,920,660)).save(dst)"
```

- [ ] **Step 2: 收紧报价搜索区域并修正业务文字**

在 `ArenaStateMachine._REGIONS` 中把报价范围改为只覆盖左侧卡片：

```python
"friendship_ticket_offer": (540, 470, 440, 230),
```

把 `next_action` 的拒绝原因改为：

```python
raise TicketExhausted(
    "ticket popup did not match the selected 100 friendship points -> 5 flags offer"
)
```

把动作依据改为：

```python
"资源=友情点 报价=100 获得旗帜=5 选择=左侧已确认",
```

不要读取或输出余额数字，不改购买按钮和目标队伍页的识别。

- [ ] **Step 3: 运行状态机专项测试直到变绿**

Run:

```powershell
pytest tests/test_epic7_arena.py -q -k "ticket_purchase"
```

Expected: 合法报价、余额变化、钻石反例和证据缺失测试全部 PASS。

- [ ] **Step 4: 运行购买 Runner 测试**

Run:

```powershell
pytest tests/test_arena_runner.py tests/test_ticket_exhaustion.py -q
```

Expected: 购买来源存在时有限重试、来源离开后等待队伍页、当天已购买不点击等测试全部 PASS。

- [ ] **Step 5: 提交最小实现**

```powershell
git add games/epic7/templates/friendship_ticket_offer.png games/epic7/arena.py
git commit -m "fix: recognize safe arena friendship offer"
```

### Task 3: 更新安全契约并执行完整验证

**Files:**
- Modify: `docs/TRANSITION_CONTRACTS.md:156-161`
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: 修正文档中的资源边界**

把竞技场旗帜购买说明统一为：

```text
只允许左侧已选中的“100 友情点换 5 旗帜”；动态持有余额不参与识别；右侧“30 钻石换 5 旗帜”永久禁止。购买弹窗仍在才允许重试，弹窗离开后不重复不可逆点击，队伍页稳定后才写入当天购买记录。
```

- [ ] **Step 2: 运行竞技场和安全专项回归**

Run:

```powershell
pytest tests/test_epic7_arena.py tests/test_arena_runner.py tests/test_ticket_exhaustion.py tests/test_battle_safety_invariants.py tests/test_project_layout.py -q
```

Expected: 全部 PASS，旧钻石截图仍被拒绝。

- [ ] **Step 3: 运行完整测试和编译检查**

Run:

```powershell
pytest -q
python -m compileall -q core games desktop main.py
git diff --check
```

Expected: 测试零失败，编译和差异检查退出码均为 `0`。

- [ ] **Step 4: 提交文档**

```powershell
git add README.md docs/USER_GUIDE.md docs/TRANSITION_CONTRACTS.md
git commit -m "docs: clarify arena friendship purchase safety"
```

- [ ] **Step 5: 推送并核对远端**

```powershell
git push origin main
git status -sb
git rev-parse HEAD
git rev-parse origin/main
```

Expected: `main` 与 `origin/main` 无领先或落后，两个提交哈希完全一致；真实模拟器闭环仍由用户执行。
