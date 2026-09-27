# 全局加固方案：「每个动作都要长眼睛」改动清单

> 状态：**阶段 1 已实施**（2026-09-25 拟定，同日实施完成）；阶段 3/4 待排期
> 起因：`home_return_v2` 重写时丢了老流程的「按一次验收一次」，实跑连按两次 ESC、
> 烧掉返回预算。用户拍板：**不该只补这一处，全局所有模拟器操作都应该有这套**。

---

## 一、先说结论：不需要改 41 处，真正要补的只有 5~10 处

全项目逐处盘点（41 处动作调用点），实际状况**比预想好得多**：

| 分类 | 数量 | 说明 |
| --- | --- | --- |
| **已有页面身份 + 已有验收**（标杆，不用动） | ~26 | `runner_base` 主循环、`navigation._transition`、`arena`、`expedition`、`shop_refresh` 等 |
| **有验收但口径含像素兜底** | ~6 | `navigation.return_home` 系列 —— ⚠️ **实测后决定不动**（见阶段 2） |
| **完全没眼睛**（要补） | 5 | `home_return.py` 的 5 处 ← **本次主战场** |
| **有身份但缺逐击验收**（要补） | ~4 | `survivor` 3 处、`global_popups` 1 处 |
| **拿不到页面名**（要定降级办法） | 2 | `unknown_screen.py:112`、`home_return.py:388`（无导航器时） |

**⇒ 主体的验收机制已经存在**，本次是「给没眼睛的补上」，不是推倒重来。

### 各阶段状态一览

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| **1** | 给 `home_return_v2` 补眼睛 | ✅ **已完成**（见第七节） |
| **2** | 统一 `navigation.return_home` 的口径 | ❌ **实测否掉，撤销** |
| **3** | 补齐 `survivor` / `global_popups` 的缺验收 | ⏸️ 待排期 |
| **4** | 定义「拿不到页名」的降级依据 | ⏸️ 随阶段 1/3 一起做 |

---

## 二、口径：统一到「页面身份」，不用像素差

**这是本次的核心决定，且已被实测锁定。**

### 为什么不能用像素差

真帧实测（`frac_gt8` = 差 > 8 的像素占比）：

| 情况 | 数值 |
| --- | --- |
| **同一页**（迷宫同一个房间，镜头朝向不同） | **0.9004** |
| **同一页**（大厅 vs 大厅动画版） | **0.8232** |
| **同一页**（大厅 vs 狗粮大厅） | **0.8136** |
| 真实换页（最低） | 0.7840 |

⇒ **同一页的变化盖过了真实换页的下限，两个区间完全重叠。**
**不告诉页面名、只看画面，分不清「换页了」和「同一页自己动了」。**

反查确认那几个样本**确实是同一页**（`room`/`room_west`/`room_entering` 三个都判「局内」；
`lobby`/`lobby_fodder`/`lobby_animated` 三个都判「大厅」）。

### 统一到哪个判据

| 判据 | 定义 | 定位 |
| --- | --- | --- |
| **`StableObservation(required=2)`** | 按**页面名**连续 2 帧一致 | ✅ **本次统一口径**，项目已用 20+ 处 |
| `left_page(prev, cur)` | 页面名变了即生效 | ✅ 严格判据，`_transition` 在用 |
| `page_or_picture_changed` | 换页 **或** 像素差 | ⚠️ 含像素兜底，**要收紧** |
| `meaningful_change` | 纯像素差 | ❌ **不可用于验收动作生效** |

**⇒ 统一到 `StableObservation` / `left_page`（纯页面身份）。**

---

## 三、改动清单（按优先级）

### 阶段 1：给 `home_return_v2` 补眼睛（✅ **唯一确定要做的**，本次翻车处）

**现状**：5 处动作（`305` 点酒馆 / `329` 点蓝四格 / `343` 点放弃 / `357` 点确认 / `388` 按 ESC）
**全部零验收**，只靠 `_StableTwo`（整帧比对）+ 固定 `sleep`。

**根因回顾**：它「看一眼 → 认不出 → 按 ESC → 再看一眼」，**从不回头确认刚那一下有没有用**。
所以会出现：点了酒馆（其实成功了）→ 0.5 秒后画面还在切 → 认不出 → 兜底按 ESC。
那两次 ESC 是白按的，还差点把刚打开的家门关上。

**关键有利条件**：`main.HomeReturn` 构造时**就持有 `navigator`**（`main.py:454`），
而 `navigator.observe(screen)` 返回 `PageObservation(name, confidence)` ——
**页面身份信息已经在手边，只是没接进 `return_home_v2`。**

#### 具体改法

**① 接口（`games/epic7/home_return.py`）**

```python
def return_home_v2(
    *,
    templates: HomeReturnTemplates,
    runtime: Runtime,
    observe: Callable[[np.ndarray], str] | None = None,   # ← 新增，返回页面名
    stop_probe: ... = None,
    sleep: ... = default_sleep,
    poll_seconds: float = 0.5,
) -> np.ndarray:
```

`main.HomeReturn.__call__` 传入 `observe=lambda screen: self._navigator.observe(screen).name`。
**（`HomeReturn` 已有 `self._navigator`，不用改构造）**

**② 验收动作（照搬老流程的形态，但用统一口径）**

每处动作后，等到「页面身份确实变了」才放行：

| 动作 | 动作前记 | 验收条件 |
| --- | --- | --- |
| 点酒馆（305） | `before = observe(screen)` | `observe(...)` != `before`（或 `_at_lobby` 命中） |
| 点蓝四格（329） | 同上 | 同上 |
| 点放弃（343） | 同上 | 同上 |
| 点确认（357） | 同上 | 同上 |
| **按 ESC（388）** | 同上 | 同上 —— **关键：没变就不再按，改换路或报错** |

**③ `_press_esc` 的「无效」处理（这是治「连按两次」的核心）**

```
按 ESC 后等窗口 → 页面身份变了？
  ├─ 变了 → 正常继续（back_count 重置/继续）
  └─ 没变 → 记「返回验收=无效」，**不再重复按同一个 ESC**
             → 换路：尝试点页内返回箭头（若识别得到）
             → 换不了路就报错并留诊断（不硬撑到 8 次）
```

**④ 降级路径（无导航器场景）**

`observe is None` 时退化为现有的 `_StableTwo` + 固定等待，
**但必须记一行日志明确说明「无页面识别，验收降级」** —— 不许悄悄跳过。

#### 阶段 1 的验证

| 项 | 要求 |
| --- | --- |
| 单元测试 | 真 Runner 级（2026-09-25 骑士团两次事故的教训：判据对但没接进主循环 = 白做） |
| 变异验证 | 把验收代码拿掉 ⇒ 测试必须变红 |
| 「连按两次」回归 | 造一个「按了 ESC 但画面没变」的夹具，断言**不会连按第二次** |
| 门槛 | **全量**（动 `home_return.py` + `main.py`） |
| 实跑 | 竞技场跑 2 轮，确认收尾日志不再出现「同一层连按」 |

### 阶段 2：统一 `navigation.return_home` 的验收口径 —— ❌ **实测数据否掉了，不要做**

**原计划**：把 `navigation.py:811` 的 `page_or_picture_changed`（含像素兜底）
换成 `left_page`（纯页面身份），与其他地方统一。

**实测数据（历史日志 `runtime_logs/*.log` 全量统计）**：

```
返回验收=生效  出现 13 次
返回验收=无效  出现  0 次
```

再看这 13 次"生效"的**页面跨度**：

| 次数 | 从 | 到 | 页面名变了吗 |
| --- | --- | --- | --- |
| **5** | 骑士团主页 | 骑士团主页 | ❌ **没变** |
| **1** | 未知画面 | 未知画面 | ❌ **没变** |
| 4 | 世界首领战主页 | 骑士团主页 | ✅ 变了 |
| 2 | 竞技场入口 | 竞技场模式选择 | ✅ 变了 |
| 1 | 未知画面 | 骑士团主页 | ✅ 变了 |

⇒ **13 次里有 6 次（46%）是「页面名没变」、纯靠像素兜底才判成「生效」的。**

**如果把口径收紧成 `left_page`，这 6 次会从「生效」翻成「无效」**，
从而触发那支有副作用的激进分支（改成点页内返回箭头，或直接报错）。
**这是往系统里引入新故障，不是加固。**

**⇒ 结论：阶段 2 撤销。老流程的「宽松」不是偷懒，是有实测支撑的设计。**
- `navigation.return_home` 的验收**保持现状**。
- **统一口径的范围限定为「新装/要补的地方」，不回溯改造老流程。**
- 若将来仍想统一，前置条件是：先搞清那 6 次「同页但返回确实推动了流程」的机制
  （很可能是**同一页的列表滚动/内容刷新**，页面名本来就该一样）——
  那说明 `left_page` 对这种场景**天生不适用**，而不是老流程写错了。

⚠️ **这条要记牢**：老流程里的「不一致」往往是有原因的。**统一口径之前先问
「它当初为什么这么写」，别把有依据的差异当成技术债清掉。**

### 阶段 3：补齐无验收的动作点

| 序号 | 位置 | 现状 | 改法 |
| --- | --- | --- | --- |
| 3.1 | `survivor.py:302` | 点首卡后不确认 | 点后确认离开 `survivor.weapon_card` |
| 3.2 | `survivor.py:387` | 点「重新进行」后不确认 | 点后确认离开 `survivor.result` |
| 3.3 | `survivor.py:313` | 摇杆滑动，**无页名** | 页名从调用方传入（调用处有 `observation.page == "survivor.battle"`） |
| 3.4 | `survivor.py:326` | 点升级卡，**无页名** | 同上（调用处有 `observation.page == "survivor.level_up"`） |
| 3.5 | `global_popups.py:499` | 有弹窗身份 + 双帧，口径接近 | 评估是否统一 |

### 阶段 4：处理「真拿不到页面名」的 2 处 —— **必须有明确降级依据**

| 位置 | 为什么拿不到 | 处理原则 |
| --- | --- | --- |
| `unknown_screen.py:112` | **页面名恰恰是「unknown」**（认不出来才走这里） | 保留现有像素判据，但**在文档里写明这是唯一例外及理由** |
| `home_return.py:388` | 无导航器场景下的兜底 | 由 1.5 的降级路径覆盖 |

⚠️ **降级必须显式、有理由、可追溯**，不能悄悄跳过 —— 否则就是「没测到」冒充「没问题」。

---

## 四、验证门槛

| 改动 | 门槛 |
| --- | --- |
| 阶段 1（动 `home_return.py` + `main.py`） | **全量**（共享模块） |
| 阶段 2（动 `navigation.py`） | **全量** |
| 阶段 3（动 `survivor.py` / `global_popups.py`） | 定向 + 受影响路线测试 |

**每条改动必须配「真 Runner 级」测试**（2026-09-25 骑士团捐赠两次事故的教训：
判据对、但没接进主循环 = 白做）。且要做**变异验证**（把代码改回错的，测试必须变红）。

---

## 五、与现有机制的关系（不重复造轮子）

| 已有机制 | 本次如何处理 |
| --- | --- |
| `_REQUIRE_TRANSITION_CONTRACT`（路线准入硬开关） | **不动**。它管路线主循环的动作，与本次的公共流程互补 |
| `TRANSITION_EXEMPT`（豁免名单） | **不动** |
| `core/supervisor.py` 的判据函数 | **复用**（`StableObservation` / `left_page`），不新造 |

---

## 六、相关文件

- `games/epic7/home_return.py` —— 本次翻车处，阶段 1 主战场
- `main.py::HomeReturn` —— 分派器，阶段 1 要在这里把 `observe` 接进去
- `games/epic7/navigation.py::return_home` —— 老流程，眼睛的原型（阶段 2 参考）
- `core/supervisor.py` —— 判据工具箱（`StableObservation` / `left_page` / `page_or_picture_changed`）
- `games/epic7/runner_base.py::_require_transition_contract` —— 路线侧的同类机制（**不动**）

---

## 七、阶段 1 实施记录（2026-09-25 完成）

### 落地了什么

| 文件 | 改动 |
| --- | --- |
| `games/epic7/home_return.py` | 新增 `_ActionVerifier` 类（+ `_StableTwo.sees_change`）；`return_home_v2` 新增 `observe` 形参；5 处动作全部改走验收器；新增 `_VERIFY_TIMEOUT_SECONDS = 12.0` |
| `main.py::HomeReturn.__call__` | 传入 `observe=lambda screen: self._navigator.observe(screen).name` |
| `tests/test_home_return_failure.py` | 新增 5 条真 Runner 级测试 |
| `tests/test_public_flow_verification.py` | 断言从「关键词」升级为「AST 符号 + 调用次数」 |
| `games/epic7/public_flow_verification.py` | 表态文案对齐真实符号名 |

### 两个「判定方式」的取舍（都写进代码注释了）

**① 判「无效」时为什么是「交回主循环」而不是「就地重试」**

主循环下一轮会**重新截帧、重新判定**（`_at_lobby` / 快捷菜单 / 局内 / 蓝四格…），
这本身就是一次「换个角度看」。就地重试等于用同一个视角再赌一次，没有新信息。

**② 止损点为什么选「连续 2 次无效」而不是 8（上限）**

8 次是留给「层数深、每层退一次」的正常情况的。
**同一条 ESC 连按两次都没反应是另一种故障**（卡在不吃 ESC 的浮层上），跟层数无关。
硬撑到 8 次只会把预算全烧在同一个死页面上，最后还是报错 ——
但那时日志里已经分不清是哪一次出的问题了。

### 测试：三条断言全部做过变异验证

「加了测试」不等于「测试有用」。下面三条**每一条都拿变异验过**，
记录在案（因为前两次尝试都逃掉了变异，见下）：

| 测试 | 守什么 | 变异 | 结果 |
| --- | --- | --- | --- |
| `test_repeated_esc_on_a_page_that_does_not_move_is_stopped` | 同页不重复按 ESC（按 ≤3 次，不是 8 次） | `press_esc` 里删掉 `_wait_for_change` 判定 | ✅ 红：`8 not less than or equal to 3` |
| `test_the_verdict_follows_the_page_identity_not_the_pixels` | 判据是页面身份，不是像素 | `_wait_for_change` 页面身份分支改 `if False` | ✅ 红：日志里只剩「点击验收=无效」+「验收降级」 |
| `test_the_page_identity_path_is_not_a_downgrade` | 接了 `observe` 就不许走降级 | 同上 | ✅ 红：日志出现「验收降级」 |
| `test_home_return_declares_the_observe_mechanism` | 5 处动作确实经过验收器 | 拿掉一处 `verifier.act` | ✅ 红：`4 != 3` |

### ⚠️ 两次「测试写了但没用」的实录（这是本节最该记住的部分）

**第一次：关键词断言被注释骗过。**
原断言是 `assertIn("_verify_action", source)` —— 它在**文档字符串里**就能满足。
当时的真实类名是 `_ActionVerifier`，代码一行验收都没有，测试照样绿。

**第二次：改成集合断言仍然被逃掉。**
改成收集 `verifier.X` 的方法名集合、断言等于 `{"act", "press_esc"}` ——
**拿掉一处 `verifier.act(...)` 之后集合没变**，少的那一次没被看见。

⇒ 现在断言的是**调用次数**（`act` 必须正好 4 次、`press_esc` 必须正好 2 次）。

**教训：写「代码里有没有某个东西」的测试时，关键词和集合都不够 ——
要数次数，或者直接用 AST 认真实符号。而且必须做变异验证，
否则「测试全绿」和「测试有效」是两件不同的事。**

### 还没做的

- **`started_at` 参数已从 `press_esc` 移除**（改用验收后它没用了；
  按用户「精准修改」的规矩，自己改动产生的无用参数由自己清理）。
- 阶段 3（`survivor` 3 处 + `global_popups` 1 处）待排期。
- 阶段 4（`unknown_screen` 的豁免已写进表态表，理由备查）。
- **竞技场实跑验收**尚未做（确认收尾日志不再出现「同一层连按」）。
- ⚠️ **发现但未处理**：`modes._assert_resume_declared()` 与
  `_assert_transition_stance_declared()` **生产代码从未调用**，只在测试里跑 ——
  文档承诺的「import 阶段就报错」没有兑现。这超出本次范围，**已单独记下**。
  （新写的 `public_flow_verification.assert_*` 同样需要确认接线，
  否则会重蹈覆辙。）
