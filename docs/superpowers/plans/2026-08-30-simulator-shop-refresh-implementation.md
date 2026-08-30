# Simulator Shop Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为《第七史诗自动助手》增加只支持雷电模拟器的实验版刷书签路线，安全购买誓约书签和神秘书签，并只保留本轮统计。

**Architecture:** 新增独立 `ShopRefreshRunner`，由纯视觉 `ShopRefreshObserver` 产出页面与商品行观察结果，Runner 按“顶部扫描—滚动—底部扫描—刷新”的事务状态推进。购买确认与刷新确认都只允许点击一次，统计只在目标退出和业务完成证据成立后提交。

**Tech Stack:** Python 3、OpenCV 模板匹配、现有 `Runtime`/`Epic7Navigator`/`EvidenceProfile`、pytest。

---

## 文件边界

- 新增 `games/epic7/shop_refresh.py`：领域枚举、观察结果、本轮统计、状态机和 Runner。
- 新增 `games/epic7/evidence/shop_refresh.py`：模板、区域、阈值、商品同行判断和页面观察。
- 新增 `games/epic7/templates/shop_refresh/*.png`：仅来自当前客户端或经当前客户端 fixture 验证的目标模板。
- 修改 `core/runtime.py`、`core/window.py`：增加模拟器安全滑动能力。
- 修改 `games/epic7/navigation.py`：大厅到秘密商店的可验证导航。
- 修改 `games/epic7/modes.py`、`main.py`、`desktop/catalog.py`：注册模拟器实验路线并拒绝 PC 后端。
- 新增 `tests/test_shop_refresh_evidence.py`、`tests/test_shop_refresh_runner.py`；小范围修改既有注册、导航、Runtime 测试。
- 修改 `README.md`、`docs/TRANSITION_CONTRACTS.md`、`docs/USER_GUIDE.md`、`docs/TODO.md`：写清实验状态和本轮统计口径。

### Task 1: 固化当前客户端 fixture 与安全滑动接口

**Files:**
- Modify: `core/runtime.py`
- Modify: `core/window.py`
- Modify: `main.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_window_capture.py`

- [ ] **Step 1: 写 Runtime 滑动失败测试**

```python
def test_runtime_swipe_logs_and_calls_backend_once():
    swipes = []
    runtime = Runtime(screen, click, swipe=swipes.append, emit=logs.append)
    runtime.swipe((1300, 850), (1300, 220), 500, "shop-scroll-bottom")
    assert swipes == [((1300, 850), (1300, 220), 500)]
    assert "动作=shop-scroll-bottom" in logs[-1]
```

- [ ] **Step 2: 运行测试并确认因 `swipe` 参数不存在而失败**

Run: `python -m pytest tests/test_runtime.py -k swipe -q`

Expected: FAIL，错误包含 `unexpected keyword argument 'swipe'`。

- [ ] **Step 3: 最小实现 Runtime 和雷电实例滑动**

```python
def swipe(self, start, end, duration_ms, action):
    self._stop_if_requested()
    self.log(f"执行滑动 动作={action} 起点={start} 终点={end} 时长={duration_ms}ms")
    if not self.dry_run:
        if self._swipe is None:
            raise RuntimeError("未配置滑动动作")
        self._swipe(start, end, duration_ms)
```

`Epic7Window.swipe()` 必须把 legacy y 坐标减去 52，并通过当前实例的 `ldconsole adb --command "shell input swipe 1300 798 1300 168 500"` 形式发送；不得使用全局鼠标。

- [ ] **Step 4: 将 `game_window.swipe` 只注入模拟器 Runtime，运行专项测试**

Run: `python -m pytest tests/test_runtime.py tests/test_window_capture.py -q`

Expected: PASS。

### Task 2: 实现集中视觉证据与商品同行分类

**Files:**
- Create: `games/epic7/evidence/shop_refresh.py`
- Create: `games/epic7/templates/shop_refresh/*.png`
- Create: `tests/test_shop_refresh_evidence.py`
- Use: `tests/fixtures/epic7_shop_refresh/*.png`

- [ ] **Step 1: 从当前 fixture 裁剪页面结构模板**

使用 `tools/crop_template.py` 或一次性 OpenCV 裁剪命令，从已采集 fixture 生成 `shop_title`、`refresh_button_3`、`buy_button`、`purchase_title`、`refresh_prompt`、`popup_cancel`、`popup_confirm`。目标商品模板先用外部开源项目候选图，必须对当前目标 fixture 离线验证后才能设为 required。

- [ ] **Step 2: 写页面和商品分类失败测试**

```python
def test_current_shop_fixtures_are_safe_shop_pages():
    observer = build_shop_refresh_observer(TEMPLATES)
    assert observer.observe(load_fixture("shop_top_live")).page is ShopPage.SHOP
    assert observer.observe(load_fixture("shop_bottom_live")).page is ShopPage.SHOP

def test_refresh_confirmation_requires_prompt_and_both_buttons():
    observer = build_shop_refresh_observer(TEMPLATES)
    result = observer.observe(load_fixture("refresh_confirm_live"))
    assert result.page is ShopPage.REFRESH_CONFIRM
    assert result.confirm_point is not None
    assert result.cancel_point is not None

def test_other_purchase_popup_is_not_a_bookmark_popup():
    observer = build_shop_refresh_observer(TEMPLATES)
    result = observer.observe(load_fixture("purchase_confirm_other_live"))
    assert result.page is ShopPage.PURCHASE_CONFIRM
    assert result.purchase_kind is ShopItemKind.OTHER

def test_row_requires_item_and_buy_button_in_same_vertical_band():
    assert same_shop_row(item_y=300, buy_y=330)
    assert not same_shop_row(item_y=300, buy_y=540)

def test_close_scores_return_unknown_instead_of_guessing():
    assert classify_item_scores(0.82, 0.80) is ShopItemKind.UNKNOWN
```

- [ ] **Step 3: 运行测试并确认模块尚不存在**

Run: `python -m pytest tests/test_shop_refresh_evidence.py -q`

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 4: 最小实现证据类型和观察器**

```python
class ShopItemKind(Enum):
    COVENANT = "covenant"
    MYSTIC = "mystic"
    OTHER = "other"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class ShopRowObservation:
    kind: ShopItemKind
    item_center: tuple[int, int] | None
    buy_point: tuple[int, int] | None
    item_score: float
    alternate_score: float
    row_key: str
```

观察器只返回证据，不点击。两种目标分数差小于声明 margin、目标低于阈值、购买按钮不在同一行时返回 `UNKNOWN`。

- [ ] **Step 5: 运行证据测试与配置校验**

Run: `python -m pytest tests/test_shop_refresh_evidence.py tests/test_visual_evidence.py -q`

Expected: PASS。

### Task 3: 实现本轮统计和纯事务状态机

**Files:**
- Create: `games/epic7/shop_refresh.py`
- Create: `tests/test_shop_refresh_runner.py`

- [ ] **Step 1: 写统计口径失败测试**

```python
def test_initial_purchases_do_not_enter_paid_hit_rate():
    stats = ShopRunStats(target_refreshes=2)
    stats.commit_purchase(ShopItemKind.COVENANT)
    assert stats.initial_covenant == 1
    assert stats.paid_covenant == 0
    assert stats.covenant_hit_rate == 0.0

def test_paid_covenant_and_mystic_are_counted_separately():
    stats = ShopRunStats(target_refreshes=2)
    stats.commit_refresh()
    stats.commit_purchase(ShopItemKind.COVENANT)
    stats.commit_purchase(ShopItemKind.MYSTIC)
    assert (stats.paid_covenant, stats.paid_mystic) == (1, 1)
    assert (stats.covenant_gold, stats.mystic_gold) == (184000, 280000)

def test_refresh_is_committed_only_after_business_completion():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_refresh()
    assert machine.stats.completed_refreshes == 0
    machine.complete_refresh()
    assert machine.stats.completed_refreshes == 1

def test_last_refreshed_batch_is_scanned_before_completion():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_refresh()
    machine.complete_refresh()
    assert machine.phase is ShopPhase.SCAN_TOP
    machine.complete_top_scan()
    machine.complete_bottom_scan()
    assert machine.phase is ShopPhase.COMPLETE
```

- [ ] **Step 2: 运行测试并确认统计类尚不存在**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k stats -q`

Expected: FAIL。

- [ ] **Step 3: 实现最小 `ShopRunStats`**

```python
@dataclass
class ShopRunStats:
    target_refreshes: int
    completed_refreshes: int = 0
    initial_covenant: int = 0
    initial_mystic: int = 0
    paid_covenant: int = 0
    paid_mystic: int = 0
    covenant_gold: int = 0
    mystic_gold: int = 0
```

`commit_purchase()` 根据 `completed_refreshes == 0` 区分初始页和付费页；`commit_refresh()` 单独提交 3 钻；汇总不得写文件。

- [ ] **Step 4: 实现 phase 推进并验证 `N + 1` 批次**

状态只允许：`SCAN_TOP → WAIT_BOTTOM → SCAN_BOTTOM → WAIT_REFRESH_CONFIRM/COMPLETE → WAIT_REFRESH_RESULT → SCAN_TOP`。达到 `N` 后必须先完成当前底部扫描，再进入 `COMPLETE`。

- [ ] **Step 5: 运行统计和状态机测试**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k "stats or phase or last" -q`

Expected: PASS。

### Task 4: 实现购买事务闭环

**Files:**
- Modify: `games/epic7/shop_refresh.py`
- Modify: `tests/test_shop_refresh_runner.py`

- [ ] **Step 1: 写不可逆购买失败测试**

```python
def test_open_purchase_retries_only_while_original_row_remains():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(covenant_row())
    assert machine.can_retry_open_purchase(covenant_row())
    assert not machine.can_retry_open_purchase(mystic_row())

def test_purchase_popup_must_match_pending_item_and_price():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(covenant_row())
    assert machine.validate_purchase_popup(ShopItemKind.COVENANT, 184000)
    assert not machine.validate_purchase_popup(ShopItemKind.MYSTIC, 280000)

def test_confirm_purchase_is_clicked_exactly_once():
    runner, clicks = scripted_purchase_runner()
    runner.run(max_cycles=1)
    assert [name for name, _point in clicks].count("confirm_purchase") == 1

def test_popup_exit_without_row_disappearance_does_not_commit():
    machine = ShopRefreshStateMachine(target_refreshes=1)
    machine.begin_purchase(covenant_row())
    machine.mark_purchase_confirm_clicked()
    assert not machine.complete_purchase(target_row_still_visible=True)
    assert machine.stats.initial_covenant == 0

def test_gold_shortage_stops_route_without_purchase_commit():
    runner, _clicks = scripted_gold_shortage_runner()
    runner.run(max_cycles=1)
    assert runner.resource_exhausted
    assert runner.machine.stats.initial_covenant == 0
```

- [ ] **Step 2: 运行并确认失败原因是事务逻辑缺失**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k purchase -q`

Expected: FAIL。

- [ ] **Step 3: 实现 pending purchase 与单击闩锁**

`PendingPurchase` 保存 kind、row_key、price、来源列表指纹和 `confirm_clicked`。打开购买框属于可逆动作；确认购买后立即设置闩锁，后续只观察。确认框退出、原行目标消失且商店连续两帧稳定才调用 `stats.commit_purchase()`。

- [ ] **Step 4: 资源不足与未知结果失败关闭**

金币不足设置 `resource_exhausted=True`、stop_reason，并输出汇总。确认点击后结果未知时保存来源、最终帧和集中证据诊断，禁止 RecoveryGate 重新导航后再次购买。

- [ ] **Step 5: 运行购买事务测试**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k purchase -q`

Expected: PASS，且确认点击调用次数为 1。

### Task 5: 实现滚动和刷新事务闭环

**Files:**
- Modify: `games/epic7/shop_refresh.py`
- Modify: `tests/test_shop_refresh_runner.py`

- [ ] **Step 1: 写滚动与刷新失败测试**

```python
def test_scroll_retries_only_when_shop_source_remains_static():
    tracker = ScrollTransition(before=frame(0))
    assert tracker.observe(frame(0)) is TransitionResult.SOURCE_STILL
    assert tracker.retry_allowed

def test_scroll_motion_then_stable_enters_bottom_scan():
    tracker = ScrollTransition(before=frame(0))
    tracker.observe(frame(30))
    tracker.observe(frame(10))
    assert tracker.observe(frame(10)) is TransitionResult.COMPLETE

def test_refresh_popup_requires_source_price_three():
    transaction = RefreshTransaction(source_price=3)
    assert transaction.can_confirm(prompt=True, cancel=True, confirm=True)
    assert not RefreshTransaction(source_price=None).can_confirm(
        prompt=True, cancel=True, confirm=True
    )

def test_confirm_refresh_is_clicked_exactly_once():
    runner, clicks = scripted_refresh_runner(final_frame=frame(10))
    runner.run(max_cycles=1)
    assert [name for name, _point in clicks].count("confirm_refresh") == 1

def test_refresh_without_motion_or_fingerprint_change_is_unknown():
    tracker = RefreshTransition(before=frame(10))
    assert tracker.observe(frame(10), shop_stable=True) is TransitionResult.UNKNOWN

def test_same_final_list_can_succeed_when_full_transition_motion_exists():
    tracker = RefreshTransition(before=frame(10))
    tracker.observe(frame(80), shop_stable=False)
    assert tracker.observe(frame(10), shop_stable=True) is TransitionResult.COMPLETE

def test_skystone_shortage_stops_without_refresh_commit():
    runner = scripted_skystone_shortage_runner()
    runner.run(max_cycles=1)
    assert runner.resource_exhausted
    assert runner.machine.stats.completed_refreshes == 0
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k "scroll or refresh or skystone" -q`

Expected: FAIL。

- [ ] **Step 3: 实现滚动转场证据**

Runner 保存滑动前商品区域帧；来源仍稳定且无运动时最多重试声明次数。观察到方向无关的有效列表运动后停止点击，等待连续稳定帧，再进入底部扫描。

- [ ] **Step 4: 实现刷新单击与动态三帧证据**

刷新确认保存 `before`、动态峰值差和最终列表指纹。确认按钮只点击一次；只有弹窗退出且“稳定→明显变化→稳定商店”成立才提交刷新。既无运动又无指纹变化时安全停止。

- [ ] **Step 5: 运行刷新专项测试**

Run: `python -m pytest tests/test_shop_refresh_runner.py -k "scroll or refresh or skystone" -q`

Expected: PASS。

### Task 6: 注册导航、CLI 和桌面实验入口

**Files:**
- Modify: `games/epic7/navigation.py`
- Modify: `games/epic7/modes.py`
- Modify: `main.py`
- Modify: `desktop/catalog.py`
- Modify: `tests/test_navigation.py`
- Modify: `tests/test_modes.py`
- Modify: `tests/test_desktop_catalog.py`
- Modify: `tests/test_main_story.py`

- [ ] **Step 1: 写注册和后端限制失败测试**

```python
def test_shop_refresh_is_registered_as_experimental():
    assert get_mode("shop_refresh").default_state == "scan_top"
    assert route_by_name("shop_refresh").experimental

def test_shop_refresh_rejects_pc_backend_before_window_creation():
    with pytest.raises(ValueError, match="仅支持模拟器"):
        get_mode("shop_refresh").validate_backend("pc")

def test_shop_navigation_requires_lobby_exit_and_shop_entry():
    navigator, clicks = scripted_shop_navigator()
    navigator.navigate("shop_refresh", lobby_screen=fixture("lobby"))
    assert len(clicks) == 1
    assert navigator.observe(shop_fixture("shop_top_live")).name == "shop_refresh"

def test_shop_cycles_mean_paid_refresh_count():
    result = run_scripted_shop_mode(max_cycles=3)
    assert result.completed_cycles == 3
    assert result.checked_batches == 4
```

- [ ] **Step 2: 运行并确认模式尚未注册**

Run: `python -m pytest tests/test_modes.py tests/test_desktop_catalog.py tests/test_navigation.py -k shop -q`

Expected: FAIL。

- [ ] **Step 3: 实现导航联合锚点和模式注册**

大厅入口模板来自 `lobby_shop_entry.png`；点击后必须看到大厅证据退出和 `shop_title + refresh_button_3 + buy_button` 连续稳定。`ModeSpec` 增加最小后端允许集合，刷书签只允许 `emulator`。

- [ ] **Step 4: 桌面展示“刷书签（实验）”和刷新次数语义**

复用现有次数输入，不增加历史统计或新配置页。描述明确“输入为付费刷新次数；初始页面也会检查”。

- [ ] **Step 5: 运行注册、导航和桌面测试**

Run: `python -m pytest tests/test_modes.py tests/test_desktop_catalog.py tests/test_navigation.py tests/test_desktop_app.py tests/test_desktop_worker.py -q`

Expected: PASS。

### Task 7: 文档、完整验证和实验交付

**Files:**
- Modify: `README.md`
- Modify: `docs/TRANSITION_CONTRACTS.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/TODO.md`

- [ ] **Step 1: 写明实验限制和用户实机步骤**

文档必须写明：仅雷电模拟器；只买誓约和神秘；初始页加 N 次刷新；金币/钻石不足立即停止；当前统计不保留历史；用户完整实跑前不转正式。

- [ ] **Step 2: 运行静态与专项验证**

Run: `python -m compileall core games desktop main.py`

Run: `python -m pytest tests/test_shop_refresh_evidence.py tests/test_shop_refresh_runner.py tests/test_navigation.py tests/test_modes.py tests/test_desktop_catalog.py -q`

Expected: 全部 PASS。

- [ ] **Step 3: 运行全量回归**

Run: `python -m pytest -q`

Expected: 不少于基线 `670 passed, 1 skipped`，无新增失败。

- [ ] **Step 4: 检查变更边界**

Run: `git diff --check`

Run: `git status --short`

确认未修改通用模板阈值、现有正式路线业务行为，未新增历史文件存储。

- [ ] **Step 5: 提交并交给用户实机闭环**

先做空跑识别，再由用户实跑 1 次刷新、分别命中两类书签、运行 10 次核对统计。离线完成只能称“开发完成，待实机验收”，不能宣称路线已跑通。
