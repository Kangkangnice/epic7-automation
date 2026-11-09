---
status: superseded
---

# 骑士团 · 世界首领战（`world_boss`）实施方案

> ✅ **现行状态（2026-11-09）**：这条路线已于 **2026-11-03 20:58 在 PC 上打通**并进入
> `PC_READY_ROUTES`，界面上已放行；现行状态看 [STATUS.md](STATUS.md) 与
> [PC 客户端接入指南](PC_TEMPLATE_MIGRATION.md)。
> ⚠️ **下面整份是 2026-09 的施工记录，只作追溯、不要照着做**：其中「尚未实机跑」、
> 「[实验] 角标 / 启动前确认框」、「命令行编号菜单 `launcher.py`」、「次数可改」等说法
> 均已作废（分级 2026-10-20 取消、编号菜单已删、次数固定 2 且不可改）。

2026-09-21 实机走查后编写，同日完成代码落地；2026-09-22 接入助手入口，并补骑士团签到弹窗
与「领取支援物品」弹窗（两个骑士团系统弹窗都进了全局弹窗守卫），同日补战斗画面识别 + 右上角「跳过」。
当时的状态：代码、测试与助手入口已全部就绪，尚未实机跑这一条路线。
当时排的下一步是第九节的步骤 7~9：干跑 → 实跑一轮 → 两轮验证。

## 一、业务目标

骑士团里每天要做的「世界首领战」，一天可打 N 次（见下方次数口径），每次消耗 **20 体力**，
体力不足时用**生命之叶**购买（1 片换 80 体力）。玩家认为枯燥，希望自动化。

## 二、实机走查记录（2026-09-21，模拟器后端）

### 完整路径

```
大厅 → [骑士团图标] → 骑士团主页 → [世界首领战图标] → 世界首领战主页
                                                          ↓ 右下角「选择队伍」
                                                        选择辅助队伍页（默认第一个，不改）
                                                          ↓ 右下角「组成战斗队伍」
                                                        配置队伍页 → 左下角「自动配置」
                                                          ↓ 右下角「战斗开始」
                                                          （体力不足 → 行动力不足弹窗 → 购买）
                                                        战斗入场演出 → 战斗（自动）
                                                          ↓ 结算页
                                                        战斗级别奖励弹窗 →「全部开启」→「确认」
                                                          ↓ 结算页右下角「确认」
                                                        回到世界首领战主页（次数 -1）
```

### 每步实测数据

| 步骤 | 页面 | 动作 | 点击坐标（画布 1982×1132） | 帧差 |
|---|---|---|---|---|
| 1 | 大厅 | 点骑士团图标（盾牌） | **(1235, 1020)** | 65.0 |
| 2 | 骑士团主页 | 点世界首领战图标（骷髅） | **(460, 682)** | 75.9 |
| 3 | 世界首领战主页 | 点「选择队伍」 | **(1781, 1052)** | 42.9 |
| 4 | 选择辅助队伍 | 点「组成战斗队伍」 | **(1631, 1038)** | 36.9 |
| 5 | 配置队伍 | 点「自动配置」 | **(246, 1034)** | 12.7 |
| 6 | 配置队伍 | 点「战斗开始」 | **(1376, 1036)** | 46.1 |
| 7 | 行动力不足弹窗 | 选树叶卡片 | **(770, 620)** | 0.1（本就选中） |
| 8 | 行动力不足弹窗 | 点「购买」 | **(1120, 877)** | 46.1 |
| 9 | 配置队伍 | 点「战斗开始」（再） | **(1376, 1036)** | 140.4 |
| 10 | 战斗入场演出 | 等 | — | — |
| 11 | 结算页 | 等动画结束 | — | — |
| 12 | 战斗级别奖励弹窗 | 点「全部开启」 | **(961, 994)** | 2.9 |
| 13 | 战斗级别奖励弹窗 | 点「确认」 | **(959, 994)** | 60.1 |
| 14 | 结算页 | 点「确认」 | **(1730, 1036)** | 56.4 |

**⚠️ 踩过的坑（实施时必看）：**

1. **骑士团入口图标热区小**：点 (1214,1024)（图标左边缘）和 (1213,1072)（文字上）**都没反应**，
   只有点图标中心 **(1235,1020)** 才进得去。模板匹配取中心即可，手写死坐标必须用中心点。
2. **结算页两个按钮容易点混**：`战斗结果` 在 x 1375~1600（中心 ~1490），`确认` 在 x 1690~1830
   （中心 ~1730）。点 `战斗结果` 会弹出**伤害统计图表**（点图表外任意处可关闭），
   不是前进动作。**前进必须点 `确认`。**
3. **战斗很快**：入场演出约 5 秒，战斗本体不到 10 秒就结束。**用户说的"5~10 秒等待"足够**。

## 三、页面锚点与阈值（已做全库 185 张 1982×1132 夹具的排他性扫描）

> ⚠️ **本节已被实施阶段的两轮实测修正**，修正后的可用锚点表见
> `games/epic7/evidence/world_boss.py` 的模块 docstring。本文只保留历史决策链。

| 页面 | 锚点模板 | 搜索区域 | 本路线分 | 跨路线最高分 | 建议阈值 |
|---|---|---|---|---|---|
| 骑士团主页 | `knights_title.png` | (0,30,500,180) | 1.0000 | 0.6337 | ~~0.80~~ ❌ 见下 |
| 世界首领战主页 | `worldboss_title.png` | (0,30,500,180) | 1.0000 | 0.6223 | ~~0.80~~ ❌ 见下 |
| 选择辅助队伍 | `team_select_title.png` | (0,140,520,140) | 1.0000 | 0.3693 | **0.80** |
| 战斗级别奖励 | `level_reward_title.png` | (600,120,800,160) | 1.0000 | 0.4432 | **0.80** |
| 结算页（排他） | `result_title.png` | (1400,50,400,110) | 1.0000 | **0.3612** | **0.80** ⚠️ 见下 |
| 行动力不足弹窗 | **复用 `story/stamina_popup.png`** | (400,200,1200,700) | 0.9999 | 0.9990（story） | 现有阈值 |
| 结算「确认」按钮 | **不可独占**（fodder 0.9994） | — | — | — | ⚠️ 见下 |

### ⚠️ 实施阶段推翻的两条判据（2026-09-21 实测）

**① 两个「标题」锚点根本不排他 —— 它们在本路线内部就常驻。**

`worldboss_title` 在 `team_select` / `team_config` / `stamina_popup` 上实测
0.9988~0.9991，命中中心全是 `(192,101)`：选择辅助队伍、配置队伍、体力弹窗
**都是世界首领战这一屏的子页面**，顶部那根标题栏一直都在。
所以「主页 = 有 worldboss_title」会把队伍页和弹窗全判成主页。

→ 改用两个**真按钮**当排他锚点（`select_team_button` / `team_config_auto`），
本路线 1.0000 / 0.9161，跨路线最高 0.4192 / 0.3612。

**② `result_title` 在「战斗级别奖励」弹窗上仍有 0.7103。**

弹窗是把结算页**压暗**之后盖上去的，而 `TM_CCOEFF_NORMED` 对亮度缩放不敏感
（项目记忆里「压到 10% 亮度模板分仍 0.9989」的同一现象）。
所以 `world_boss.result` 必须显式 `forbidden=("level_reward_title",)`。

### ⚠️ 已知的共用锚点（踩坑记录）

- **「确认」按钮跨路线通用**：`epic7_fodder/results.png` 0.9994、`epic7_expedition/result.png` 0.9806。
  **绝不能只靠它判"这是世界首领战结算页"** —— 要跟排他的 `result_title.png` 组合使用
  （这正是项目记忆里「arena 与 expedition 结算页共用 confirm 锚点」的同类问题）。
- **体力弹窗是全局共用的**：`epic7_story/stamina_popup_live_*.png` 上 0.9990 命中。
  **这是好消息** —— 说明可以**直接复用 `games/epic7/stamina.py`，零改动、零新模板**。

## 四、次数口径（关键业务逻辑）—— **已与用户确认**

主页右下角 `剩余次数/上限` 的显示。**格式是「剩余 / 上限」，不是「已用 / 上限」**
（2026-09-21 用户明确确认）。

| 状态 | 显示 | 「选择队伍」按钮 | 绿条占比 | 判定 |
|---|---|---|---|---|
| 还能打 | **`1/2`** / `2/2`（青蓝色数字 + 白色亮字） | 可点 | **59.2%** | **继续打** |
| 打完了 | **`0/2`**（灰色数字 + 灰色暗字） | **变灰** | **0.0%** | **停**（退出码 0） |
| 今天已做完（红点消失） | — | — | — | **直接退出，不做任何操作** |

**实测证据**（本轮实机）：
- 打之前：`1/2`，按钮文字区 HSV 平均亮度 **118.8**
- 打之后：`0/2`，同一区域平均亮度 **49.8**（掉一半以上），按钮变灰
- 用户描述：「两次打完之后选择队伍会变灰」——**与实测一致**
- 用户当天已手打过 1 次（所以起步是 `1/2` 而非 `2/2`），AI 打掉最后 1 次 → `0/2`。
  **这条实测串起了整个口径，可信。**

**设计决策：**
- **只看数字，不看程序跑了几次**（用户明确要求：「我们是看那个次数来的，而不是说我运行了几次」）。
- **跑几次：固定 2 次，不给用户选**（2026-09-22 用户要求「不要让我选择次数，默认就是两次」）。
  三处保持一致，都被测试钉住：
  `desktop/catalog.py` 的 `default_cycles=2, cycles_editable=False`（助手界面把输入框置灰）、
  `launcher.py` 跳过次数提示直接取 2、`main.py` 在 `--max-cycles` 缺省时兜底成 2
  （照 `hero_synthesis`「无需指定次数」的既有写法）。
  **只有 1 次可打时不做特殊分支**：打完第 1 场主页就变 `0/2`、按钮变灰 ⇒ 走「次数耗尽」自然结束（退出码 0）。
  用户说「今天有 2 次只打 1 次」现实中几乎不会遇到，所以不值得为它加逻辑。
  ⚠️ 写死 2 的前提是**每日上限就是 2**（主页 `剩余/上限` 的右边那位）。哪天游戏改成 3 次，回来改这一个数（三处）。
- ~~解析方式：OCR（`rapidocr_onnxruntime`，本机已装）~~
  → **已改成按钮亮/灰（颜色）判据，不在运行期引入 OCR**（2026-09-21 用户确认）。
  实测「选择队伍」按钮底板那条绿色高亮带：`1/2` 时绿像素占比 **59.2%**，
  `0/2` 时 **0.0%**，阈值取 **0.10**，离两边都很远。
  判据落地在 `world_boss.select_team_enabled()`，区域 `SELECT_TEAM_BAR`。
- **不硬编码上限 2**：本判据只回答「按钮还亮不亮」，不解析数字，
  自然也不依赖上限（活动日、加成日改上限都不用动代码）。
- 按钮变灰时：停止并退出码 0（`0/2` 或 `1/2` 都走这条路，只看亮不亮）。

## 五、推荐架构

### Runner 形态：继承 `ModeRunnerBase`（story/fodder 范式）

理由：流程是标准的「点按钮 → 转场 → 新页面 → 战斗 → 结算 → 回到入口」同构循环，
**禁止复制 `run()` 主循环**，只覆写钩子：

```
_MODE_LABEL = "世界首领战"
_TIMEOUT_SECONDS = {各状态}
_BATTLE_ENTRY_ACTION = "战斗开始"
_CLICK_BEFORE_BATTLE = True
_run_committed_battle(...)  # 移交战斗监督
```

### 状态机（`WorldBossState`）

```
HOME            世界首领战主页，读次数
  ↓ 次数>0 且「选择队伍」可点
TEAM_SELECT     选择辅助队伍（默认第一个，直接下一步）
  ↓
TEAM_CONFIG     配置队伍 →「自动配置」→「战斗开始」
  ↓（体力不足走 stamina.py）
BATTLE          已承诺战斗，移交战斗监督
  ↓
RESULT          结算页 →「确认」→ 弹「战斗级别奖励」
  ↓
LEVEL_REWARD    「全部开启」→「确认」
  ↓
RESULT_CONFIRM  结算页「确认」
  ↓
  └→ 回 HOME，次数-1，循环
```

### 导航（`navigation.py` 需新增）✅ 已实现

> ⚠️ **2026-10-04 已改道**：原方案点**大厅底部横排**的骑士团盾牌（`lobby_knights`）。
> 那条横排是**账号自己排的快捷栏**，不同账号位置不同，不可靠 ⇒ 用户要求改走
> **右上蓝四格 → 快捷菜单 → 菜单里的骑士团**（菜单布局固定）。现在的导航链：
>
> ```python
> NavigationStep("lobby", (QUICK_MENU_PAGE,), "lobby_quick_menu_button", "打开快捷菜单")
> NavigationStep(QUICK_MENU_PAGE, (KNIGHTS_GUILD_HOME_PAGE,), "quick_menu_knights", "进入骑士团")
> NavigationStep(KNIGHTS_GUILD_HOME_PAGE, (WORLD_BOSS_ENTRY_PAGE,), "worldboss_entry", "进入世界首领战")
> ```
>
> 实际点击点：(1862,106) → (1617,611) → (449,693)。`lobby_knights` 锚点**仍然保留**
> （别的地方在用），只是不再被本路线当入口。`knights_donation` 同步改道。
> `resume_entries` 不变（`{knights_home, worldboss_home}`）。

原（历史）方案如下，仅作记录：`navigate()` 增加 `world_boss` 分支：
```python
elif mode == "world_boss":
    knights = self._transition("lobby", "knights_home", "lobby_knights", "进入骑士团")
    self._transition("knights_home", "worldboss_home", "worldboss_entry", "进入世界首领战")
```
`_REGIONS`、`PAGE_LABELS`、`MODE_LABELS`、`NavigationTemplates` 都加了：

- `lobby_knights`（大厅底部骑士团盾牌，区域 `(1150,960,420,150)`）——
  **只用来定位点击点，不用来判页**。它其实是**大厅常驻控件**：185 张夹具里每张
  大厅页都在同一位置以 0.86~0.96 命中，压暗到 55% 亮度仍 0.9643。
  也就是说「有骑士团图标」= 「在大厅」，不含任何「在骑士团页」的信息。
  ⚠️ 2026-10-04 起本路线**不再点它**（见上方改道说明）。
- `worldboss_entry`（骑士团主页的「世界首领战」骷髅盾牌，区域 `(380,620,180,140)`，
  模板 62×66）—— **这才是真正的排他锚点**：本页 0.9890，跨页最高 0.4210。
- `lobby_worldboss_select_team` —— 复用 `evidence/world_boss.py` 的
  `select_team_button` 锚点图（不在 navigation 目录下维护第二份同一控件的模板）。

`observe()` 新增两条判定，**都必须排在 `lobby` 判定之前**：

```python
worldboss_entry = self._locate(screen, "worldboss_entry", 0.85)
if worldboss_entry:
    return PageObservation("knights_home", worldboss_entry.score)
select_team = self._locate(screen, "lobby_worldboss_select_team")
if select_team:
    return PageObservation("worldboss_home", select_team.score)
```

⚠️ **骑士团主页与首领战主页的顶部标题完全相同**（实测都是 0.9988~1.0000），
靠标题区分不开，所以两页分别用两个不同的**按钮**当判据。

**实测判定结果**（`runtime_logs/_wb_probe_observe.py`，全库 185 张）：

| 夹具 | 判出页面 | 置信度 |
|---|---|---|
| `lobby_with_knights` | `lobby` | 0.9271 |
| `knights_home` | `knights_home` | 0.9890 |
| `worldboss_home` | `worldboss_home` | 1.0000 |
| `worldboss_home_exhausted` | `worldboss_home` | 0.9161 |
| `team_select` / `team_config` / `battle_result` / `level_reward` / `stamina_popup` | `unknown`（未被误判成主页） | 0.0 |

全库范围内 `knights_home` 只命中 1 张、`worldboss_home` 只命中 2 张，**零误判**。

**开局接力白名单**：`world_boss` → `{knights_home, worldboss_home}`。
停在首领战主页则整条链都不用走；停在骑士团主页则只跳第一跳。
业务页与局内的接力见下面「### 开局接力」一节（2026-09-24 补齐）。

### 体力（零改动复用）

`stamina.py` 的三个模板全部高分命中，**直接复用**：
- `stamina_popup` 0.9999 / `stamina_material` 0.9895 / `stamina_confirm` 1.0000
- 决策链：点树叶卡片 → 点购买。树叶耗尽时 `raise StaminaExhausted` → 退出码 2。

⚠️ **用户明确的资源边界**：只用**生命之叶**买体力（持有 174 片），**绝不用钻石**
（弹窗右侧的钻石选项 30 钻换 60 体力，**永远不点**）。树叶不够就停。

### 开局接力 ✅ 已实现（导航链两级 + 业务页五页 + 局内）—— 2026-09-24 补齐

**导航链两级**：白名单 `{knights_home, worldboss_home}`：
- 停在**世界首领战主页**（`worldboss_home`）→ 整条导航链都不用走，直接开打；
- 停在**骑士团主页**（`knights_home`）→ 只跳「大厅 → 骑士团」第一跳。

**业务页 + 局内**：主页 / 选择辅助队伍 / 配置队伍 / 战斗结算 / 战斗级别奖励 / 战斗中
全部就地接管，判据直接复用状态机自己的 `observe_page`（**与运行期同源**，不另定阈值、不加新锚点），
外加 `at_knights_home(screen)` 认导航链中间站。

⚠️ **这里曾经判断「业务页不开放接力」**，理由是「重来一遍只是多花 20 体力，属安全方向」。
**局内那一页推翻了这个理由**：停在战斗里不接，老流程会按 Back 回大厅 —— 不是多花 20 体力，
是**把已经开打的那一局白打**。所以现在 `BATTLE` 也接：`WorldBossRunner.run()` 先用
`resumed_from` 认出「这一局不是本进程点开的」，把交接交给战斗监督（不按 Back、不重新导航），
跑完再进主循环。业务页既然顺路，就一起接了。

⚠️ **结算页（`RESULT`）有歧义**：同一个画面分两支（点确认弹奖励 / 点确认回主页），
`next_action` 靠 `state is LEVEL_REWARD` 分岔，而接力只看到一帧、拿不到这个上下文
⇒ **保守取「奖励还没领」那一支**。敢这么取的硬前提是：两支点的是**同一个按钮**
（`open-level-reward` = `confirm-result` = (1730,1036)），所以猜错也只多一次无效点击，
下一帧 `observe_page` 认出主页就自己拨正了。**按钮一旦分开，这条推理就不成立。**

**不接的画面**：`RESULT_CONFIRM`（它不是画面，是 `next_action` 由 `state is LEVEL_REWARD`
转出来的内部记号，不在 `_PAGE_STATES` 里）、行动力不足弹窗（点确认要**消耗生命之叶**，不可逆；
而且它是盖在底页上的弹窗，回大厅那一下 Back 会先关掉它、下一帧就在底页接管）、
骑士团两个弹窗与 `lobby_with_knights`。

全库 226 张负例扫描（`runtime_logs/_audit_world_boss_cross_route.py`，输出 `_out.txt`）：
本路线 18 张里 **13 张认得出**（另 5 张是技能演出帧 / 各类弹窗 / 大厅）；跨路线命中 19 张
= **17 张别的路线的战斗帧**（`battle_scene_visible` 本来就认任何一条路线的战斗画面，
story / expedition 的接力同样如此）+ **2 张别的路线的骑士团主页**（同一张真页面，不是误判）。
⇒ **零真实误命中**。

⚠️ 这里有个坑值得记下来：**`lobby_knights` 那个大厅盾牌图标看似能当接力判据，实际不能**。
它是**大厅常驻控件**，185 张夹具里每张大厅页都在同一位置以 0.86~0.96 命中 ——
「有骑士团图标」等价于「在大厅」，不含任何「在骑士团页」的信息。
真正的排他锚点是骑士团主页里的 `worldboss_entry`。

### 骑士团签到弹窗 ✅ 已实现（全局弹窗守卫）—— 2026-09-22 用户实测补充

**现象**：用户实测发现「**每天第一次点进骑士团**会先弹一个签到达成度奖励弹窗」，
面板内容：标题「骑士团签到达成度奖励」+ 昨日签到人数 + 五个奖励图标 + 底部「点击关闭」。

**为什么必须处理**：这个弹窗盖在骑士团主页上。实测它把底页的 `worldboss_entry`
从 **0.9890 压到 0.4477**（低于 0.85 门槛）⇒ **弹窗期间底页根本认不出来**，
整条导航链会卡在「未知画面」。**不能指望穿透弹窗识别底页**，必须先关掉它。

**放在哪里**：`Epic7GlobalPopupGuard`（`games/epic7/global_popups.py`），
与友情点数、亲密度提升同类。理由：
- 它属于「每天第一次进某个页面出现的系统弹窗」，与既有四类弹窗同一性质；
- 放进守卫自动获得其统一待遇：**共享点击预算（`global_popups._MAX_POPUP_CLICKS`）
  + 每 3 秒重试 + 15 秒熔断 + 诊断留证**，不用在导航链和状态机里各写一遍；
- 所有路线共用，别的路线误入骑士团也能被兜住。

**判据（⚠️ 双锚点必需，别只看关闭点）**：

| 锚点 | 位置 | 本页 | 跨页最高 |
|---|---|---|---|
| `knights_signin_title`（标题） | `(700,260,600,90)` | 1.0000 | **0.3278**（hero/reward_popup） |
| `knights_signin_close`（点击关闭） | `(860,810,280,70)` | 1.0000 | **0.9986**（hero/imprint_sss_warning_popup） |

**「点击关闭」这四个字单独看完全不可靠** —— 全库 187 张实测它在 hero 的
`imprint_sss_warning_popup` 上拿 **0.9986**、`imprint_result_popup` 0.9908、
`reward_popup` 0.9846、expedition `victory_popup` 0.9355，因为它们共用同一种
「底部居中点击关闭」灰字控件。**只用它当判据会在别的弹窗上乱点。**
反过来标题锚点跨页最高才 0.3278，离阈值 0.80 有 0.47 余量。
⇒ 阈值 0.80 是**按标题锚点定的**，两个都命中才算。
这与项目记忆里「arena / expedition 共用 confirm 锚点」是同一类坑，这次提前避开了。

**`observe()` 里的位置**：必须排在 `worldboss_entry` 判定**之前**（签到弹窗优先级更高），
命中后返回页面名 `knights_signin_popup`，交给守卫点掉，下一帧就能正常认出骑士团主页。
`PAGE_LABELS` 加「骑士团签到弹窗」。

**全库回归（187 张）**：判成 `knights_signin_popup` 的**只有 1 张**（弹窗本身）；
`knights_home` 仍 2 张正常命中（0.9890 / 0.9994）、`worldboss_home` 2 张、
`lobby` 7 张，判页分布与加判定前**完全一致**，零误伤。
扫描脚本：`runtime_logs/_knights_signin_probe.py`（双锚点排他性）与
`runtime_logs/_knights_signin_observe.py`（全库判页对照）。

### 「领取支援物品」弹窗（团员赠送的支援资源到账）✅ 已实现 —— 2026-09-22 用户实测补充

**现象**：用户实测反馈「进骑士团时有时会弹一个**别人赠送我物资**的弹窗」。
面板内容：标题「领取支援物品」+ 副标题「已领取骑士团同伴支援的资源。」+
三个支援团员头像 + 收到资源「3/4」+ 底部「点击关闭」。

**为什么必须处理**：与签到弹窗**同一性质** —— 盖在骑士团主页上、压暗底页锚点，
弹窗期间认不出底页。**实测（20:45 那次 world_boss 实跑）**：点「进入骑士团」后
画面直接掉进「未知画面」，兜底逻辑连点屏幕中央 4 次（`wake-unknown-screen`）
都唤醒失败，导航直接失败。⇒ 必须先认出并关掉它。

**放在哪里**：同样进 `Epic7GlobalPopupGuard`，复用既有的
**共享点击预算（`global_popups._MAX_POPUP_CLICKS`）+ 每 3 秒重试 + 15 秒熔断 + 诊断留证**。
`observe()` 里排在 `worldboss_entry` 判定之前，命中返回 `gift_support_popup`。
`PAGE_LABELS` 加「领取支援物品弹窗」。

**判据（⚠️ 双锚点必需，且与签到弹窗共用同一块标题 ROI）**：

| 锚点 | 位置 | 本页 | 跨页最高 |
|---|---|---|---|
| `gift_support_title`（标题「领取支援物品」） | `(700,260,600,90)` | 1.0000 | **0.4119**（story/friendship_points_popup） |
| `gift_support_close`（点击关闭） | `(860,810,300,80)` | 1.0000 | **0.9996**（hero/reward_popup） |

⚠️ **两个弹窗标题的 ROI 完全相同**（都在面板上部 `(700,260,600,90)`），靠标题**文字**
互相区分：在这张弹窗帧上签到弹窗的标题只拿 **0.3220**、反过来拿 **0.1862**，
都远低于 0.80 ⇒ **互不误触**（`test_gift_support_popup_rejects_the_signin_popup` 守住）。
关闭点同样**单独不排他**（hero/reward_popup 上 0.9996），所以仍坚持双锚点。

**全库回归（190 张）**：判成 `gift_support_popup` 的**只有 1 张**（弹窗本身）；
`knights_home` 仍 2 张、`worldboss_home` 2 张、`lobby` 7 张、
`knights_signin_popup` 仍 1 张，判页分布与加判定前**完全一致**，零误伤。
扫描脚本：`runtime_logs/_gift_support_probe.py`（排他性 + 全库判页对照一体）。

### 「世界首领辅助队伍奖励」弹窗（同僚团员借了你的辅助队伍）✅ 已实现 —— 2026-10-19 每日任务实跑暴露

**现象**：`08:11:12 点击验收=生效 从=骑士团主页 到=无效画面` → `08:11:17 unknown_screen_unresolved`
→ `08:12:44 模式=导航 转场 骑士团主页 → worldboss_home 失败`，每日任务里「世界首领战 ✗」。

**那一帧长什么样**（诊断图已升为夹具
`tests/fixtures/epic7_world_boss/worldboss_support_reward_live_20261019.png`）：
标题「世界首领辅助队伍奖励」+ 说明「同僚团员与我的辅助队伍并肩战斗，获得了以下奖励。」+
「使用次数：1」+ 货币「指挥官的袖章 ×5」+ 底部「点击关闭」。
它盖在**世界首领战主页**上并把底页压暗 ⇒ 右下角那颗「选择队伍」
（`lobby_worldboss_select_team`）认不出来 ⇒ 整页 `unknown`。

**放在哪里**：同骑士团那三个弹窗 —— `Epic7GlobalPopupGuard`，复用共享点击预算
（`global_popups._MAX_POPUP_CLICKS`）+ 每 3 秒重试 + 15 秒熔断 + 诊断留证。
守卫装在 `runtime.capture` 上（见 `main.py`），所以**导航链与状态机两条路径都被兜住**，
不必在导航里再写一遍关弹窗。

**判据（双锚点，与骑士团那三个同形）**：

| 锚点 | 位置 | 本页 | 跨页最高 |
|---|---|---|---|
| `worldboss_support_reward_title`（标题） | `(700,262,520,80)` | 1.0000 | **0.3320**（knights_signin_popup） |
| `worldboss_support_reward_close`（点击关闭） | `(860,770,300,90)` | 1.0000 | **0.8993**（hero/reward_popup） |

⚠️ 「点击关闭」照旧**单独不排他**（`popup_spring` / `popup_penguin_*` 都在 0.8991），
必须靠标题兜住。点击点实测 **(960, 813)**。

⚠️ 那行灰字**峰值亮度只有 171** ⇒ **不能走 `MATCH_MODE_WHITE_MASK`**（白像素下界 200）：
模板会被整片抹成 0，常量模板在 `TM_CCOEFF_NORMED` 下退化成「处处 1.0000」
（实测世界首领主页十几张帧全变 1.0）。这条与 `lobby_battle` 那种「白字黑底」正好相反。

**`observe()` 里的位置**：排在 `worldboss_entry` / `lobby_worldboss_select_team` 判定
**之前**（弹窗期间底页认不出来），命中返回 `worldboss_support_reward_popup`，
`PAGE_LABELS` 加「世界首领辅助队伍奖励弹窗」。

**全库回归（280 张）**：判成 `worldboss_support_reward_popup` 的**只有 1 张**（弹窗本身），
其余 `knights_home` / `worldboss_home` / `lobby` 判页分布与加判定前完全一致，零误伤。
标题在两个骑士团弹窗上分别只有 0.2x/0.3x ⇒ 与它们互不误触
（`test_worldboss_support_reward_title_is_exclusive_against_sibling_popups` 守住）。

**回归防线**：`tests/test_global_popups.py` 5 条（双锚点 / 缺一不可 / 不认底页 /
同类弹窗排他 / 守卫点掉它）+ `tests/test_navigation.py` 2 条（`observe()` 报页名、
**端到端转场**「守卫点掉弹窗 → 认出 worldboss_home → 转场确认」）。
扫描脚本：`runtime_logs/_probe_worldboss_support_reward.py`（两个锚点的跨页最高 +
全库判页 + 守卫复演，一条命令可重跑）。

### ⚠️ 配置队伍页要分两阶段 + 动作必须声明转场契约 ✅ 已修正 —— 2026-09-22 首次实跑暴露

**现象**：用户实跑反馈「选好辅助队伍之后选择自己的队伍没有成功进行自动配置」。
日志显示 09:42:38 点「组成战斗队伍」进入配置队伍页，**同一秒**就点了「战斗开始」，
45 秒后战斗画面认不出、安全停止。

**根因（两层，不是识别失败）**：

1. **动作没有出处与去处**。`WorldBossAction` 当时只有 `name` + `point`，
   而 story / expedition / hero 的动作都带 `source_page` + `target_pages`。
   没有这两个字段，主循环**点完不回头验收**，只能靠「最后画面认不出」兜底
   —— 表现就是「秒点」，中间该不该先点自动配置、点了生效没有，程序毫无概念。

2. **`_confirmed_page` 从未被赋值**。`world_boss.py` 里这个字段只在 `__init__`
   初始化成空串，之后没有任何地方写它（story 有 `_confirm_page()`）。
   于是 `runner_base._transition_completed` 第一句就返回 False，
   **就算填了 `target_pages` 也是空转**。

3. 直接诱因：`CLICK_POINTS["auto-configure"]` 登记了坐标，但 `next_action()`
   的 TEAM_CONFIG 分支**从未引用它**，进页就直奔 `battle-start`。
   队伍三队战斗力全是 0、底座全空，战斗自然开不起来。

**修正**：

- `WorldBossAction` 补齐 `source_page` / `target_pages` / `reason`，对齐 `StoryAction`；
  所有动作统一经 `_action()` 构造，里面调 `_confirm_page(source_page)`。

  > **2026-09-24 再补**：又加了 `in_page_evidence` 字段，并打开
  > `WorldBossRunner._REQUIRE_TRANSITION_CONTRACT`（机器强制）。补之前这条路线处在
  > 「动作看起来都带判据、机器却问不出来」的状态：5 个同页动作的验收依据写在
  > `next_action` 的代码里、**没登记成字段**，而校验规则是「`target_pages` **或**
  > `in_page_evidence`」—— 规则里那个备选项根本不存在，所以一开开关这 5 个全被拦。
  > ⚠️ 这件事**靠静态印象判断不出来**（我当时看「`source_page` 全有、换页动作都带
  > `target_pages`」就以为打开只是纯加固），是用只读探针跑了一遍真状态机才发现。
  > 详见 `docs/TRANSITION_CONTRACTS.md`「已按本约定实现的参考路线」。
- 配置队伍页按 **「三队槽位是否真的配好」**分两阶段，判据用**槽位区画面细节量**
  （拉普拉斯方差 `team_detail`），**不用按钮颜色**：

  | 状态 | `team_detail`（槽位区拉普拉斯方差） | 动作 |
  |---|---|---|
  | 未配置（空槽位，画面平滑） | < 700（实测 347~451） | `auto-configure` (246,1034) |
  | 已配置（英雄头像，细节密集） | ≥ 700（实测 1181） | `battle-start` (1376,1036) |

  > **⚠️ 判据演变**：初版（2026-09-21）用「自动配置」按钮底板**色相**（橙 hue≈11 / 蓝 hue≈109），
  > 2026-09-22 第二次实跑被**证伪**——色相翻转与队伍是否真填满**无关**：同一张空队伍页，
  > 15:04 判成蓝、15:11 判成橙，连取 9 帧稳定 ⇒ 非动画。结果空队伍被判「已配置」→ 跳过自动配置
  > → 点 `battle-start` 开空队 → 战斗不开 → 45 秒「战斗画面持续无法识别超时」。
  > 改用具象画面细节量后，空/满两侧余量 249/481，彻底分开（`TEAM_CONFIGURED_DETAIL=700`）。

- 「点自动配置」**不换页**，`target_pages` **留空**（默认值 `()`）。

  ⚠️ **第一版把它写成「目标页 = 配置队伍页自身」，是错的，已推翻**：本页永远落在
  `target_pages` 里 ⇒ `_transition_completed` **永远返回 True** ⇒ 验收形同虚设，
  反而退回「点了不回头验收」。实测该写法下要么直接移交战斗（没点 `battle-start`），
  要么橙帧多时把自动配置**重复点两次**（(246,1034) 出现两次）。

  正确做法是「不声明就不进转场账本」（主循环 `last_transition_action = action if
  target_pages else None`），验收交给**页面内状态证据**：`team_configured(screen)` 为 False
  （槽位还是空、细节量 < 700）⇒ `next_action` 仍返回 `auto-configure`，按
  `_ACTION_RETRY_SECONDS`（45 秒）窗口有界重试；填满了（细节量 ≥ 700）⇒ 自然推进到
  `battle-start`。这才是「按一次、验收一次」，也正是用户要的「进出的标识」——
  **出口不由页面切换表达，而由同一页上的状态变化表达**。

  ⚠️ 同一个坑在测试里也踩了一次：`battle-start` 在真 Runner 里**不由主循环点击**
  （`_CLICK_BEFORE_BATTLE = False`，整个交给 `BattleSupervisor`），只断言主循环的
  点击记录会看不到它。回归测试要给监督注入 mock 并把它的点击也记进同一个列表。

  > **2026-09-22 二次修正（见下节）**：`_CLICK_BEFORE_BATTLE` 已改回 `True`，
  > 与竞技场同构。上面这条测试经验仍成立（要同时记两路点击），但入口分支变了。

**全库回归（187 张）**：判定为配置队伍页的只有 `team_config.png` 一张；
`stamina_popup.png` 虽命中 `team_config_auto` 锚点 0.9995，但整页被弹窗压暗、槽位区细节量极低，
`observe_page()` 拿到 TEAM_CONFIG 的前提是体力弹窗不在
（该页有 `forbidden=("stamina_popup",)`），所以走到 `team_configured()` 时弹窗必已关闭，安全。
扫描脚本：`runtime_logs/_wb_autocfg_probe.py`。

**新增证据**：`tests/fixtures/epic7_world_boss/team_config_configured.png`
（三队已填满、细节量 1181 的实跑帧，与 `team_config.png` 构成空/满一组）。

**新增 fixture（2 张）**：`knights_signin_popup.png`（弹窗帧）、
`knights_home_after_popup.png`（点掉后的骑士团主页，用来守住「关掉后能认回主页」）。

### ⚠️ 战斗「进出口标志」：战斗画面是**转场验收依据**，不是移交入口 ✅ 已修正 —— 2026-09-22

用户要求「世界首领战和竞技场主线一样有完善的进入进出标志，**不要盲目点击**」。
第一版做错了两处，都已推翻：

**错误一：`battle-start` 交给战斗监督去点**（`_CLICK_BEFORE_BATTLE = False`）。
主循环点完「组成战斗队伍」进配置页，随即把整局交给监督，监督自己去点「战斗开始」——
**主循环没有出口验收**。监督发现打不起来（比如体力弹窗挡着）就把控制权交还，
主循环拿到动作又移交、监督又交还……**实测一次跑了 199 次**，停不下来。

修正：`_CLICK_BEFORE_BATTLE = True`，与 `ArenaRunner` 同构 ——
**主循环自己点 `battle-start`，点完立刻移交监督**，监督负责跟到结算页。
「点了没生效」由转场契约 `target_pages=(战斗中,)` 兜住（见下）。

**错误二：把「我看到战斗画面了」做成移交入口**。
为了做出「出口标志」，加过一个 `observe-battle` 动作（`observe_page` 认出战斗画面
就报出它，主循环据此移交监督）。这看起来符合直觉，实则**把移交点推到了战斗开打之后**：
监督要靠「结算页出现」才能正常退出，而战斗画面这一帧根本看不到结算页
⇒ 只能一路磨到 `absolute_seconds=900` 绝对超时。
实测现象：战斗都打完了（敌方血条已空），程序还在原地按 1 秒一次轮询，
直到 900 秒才报「战斗绝对超时」。

修正：**删掉 `observe-battle` 动作**。战斗画面只在 `next_action()` 里置状态、
返回 `None`（供接力/干跑识别「这是战斗中」），不再参与移交。
真正的移交点仍是「点 `battle-start` 的那一瞬」。

**最终形态（两条标志各归其位）**：

| 标志 | 表达方式 | 谁消费 |
|---|---|---|
| **入口标志** | 配置队伍页槽位**空 → 满**（拉普拉斯方差 `team_configured()`，同页状态变化） | `next_action()` 决定该报 `auto-configure` 还是 `battle-start` |
| **出口标志** | `battle-start.target_pages=(战斗中,)`，战斗画面由 `battle_scene_visible` 认出 | 主循环 `_transition_completed` 验收转场 |

两条都不需要「在战斗画面上点任何东西」，因此**没有任何盲点**。

**有界重试**（`_MAX_BATTLE_ATTEMPTS = 2`）：监督交还 `PRE_BATTLE_BUSINESS` 时不无限重交，
最多重来 2 次，超限则存诊断 + `RuntimeError` 安全停止。

### 测试基建：假时钟 + 帧节奏（本轮踩的坑）

`ModeRunnerBase` 的时间源是 `runtime.now`（默认 `time.monotonic`）。测试里如果让
`sleep` 只瞬间推进帧下标、真时间几乎不动，「45 秒重试窗口」和「45 秒状态超时」
**永远到不了** ⇒ `capture` 一帧帧喂同一张图 ⇒ **主循环无限循环**
（实测挂死 8 分钟以上）。回归测试必须注入假时钟。

⚠️ 但**不能顺手把 `_ACTION_RETRY_SECONDS` 清零**：那正是本组要验的行为。
清零后重试间隔恒为 0，4 次尝试会在 4 帧内烧光，等不到「画面第三次变蓝」。
正确写法见 `tests/test_world_boss_runner.py::_FakeClock`：
一次 `sleep` = 前进一帧，`hold={下标: 轮询次数}` 让某个画面多停几个周期
（橙色页停满一个 45 秒窗口，才能观察到「重试了一次」）。

## 六、资源与安全边界

| 项目 | 值 |
|---|---|
| 每次战斗体力消耗 | **20** |
| 体力不足处理 | 用**生命之叶**（1 片 → 80 体力），**绝不用钻石** |
| 树叶耗尽 | 停止（`StaminaExhausted`，退出码 2） |
| 购买弹窗默认选中项 | **树叶**（实测本就选中，无需额外切换） |
| 危险按钮 | 钻石购买选项、任何「买次数」类按钮 |
| 次数耗尽 | 主页显示 `0/2`，按钮变灰 → 停止（退出码 0） |
| 红点缺失（今天已做完） | **直接退出，不做任何操作** |

## 七、待采集/待确认

| 项 | 状态 |
|---|---|
| 次数口径的准确含义 | ✅ **已确认**：`剩余/上限`（见第四节） |
| 骑士团签到弹窗 | ✅ **已实现**（全局弹窗守卫，双锚点判据，见第五节） |
| 「领取支援物品」弹窗（团员支援到账） | ✅ **已实现**（全局弹窗守卫，双锚点判据，见第五节） |
| 每周贡献度宝箱 #1（27,500,000，可领状态） | ✅ **已实现**（2026-09-23 用户实拍可领截图，见第十三节） |
| 每周贡献度宝箱 #2（44,000,000） | ✅ **已实现**（2026-09-25 补齐「可领（发光）」样本，`weekly_chest2_lit.png` + `WEEKLY_CHEST2_REGION`，见第十三节） |
| 点完宝箱之后是什么页面 | ✅ **已确认**（2026-09-23 用户补第二张图）：**原地变绿色对勾，不弹窗、不换页**。所以验收仍是「宝箱不再发光」= 模板不再命中；绿勾那一态本身只有 0.7085 ⇒ 不会「领完还一直点」。一轮的终点在下一轮判次数：`0/2` ⇒ `AttemptsExhausted`（退出码 2） |
| 战斗内「跳过」按钮 | ✅ **已实现**（2026-09-22，用户补了两张实机截图，见第十节）—— 右上角 `跳过 ›`，既是「在战斗中」的锚点，也是把这一局推向结算的动作 |
| 重打第 2 次 | **未采** —— 本轮 `1/2` 起步，一场后变 `0/2`，没有第二场的机会 |

## 八、已固化的证据

### fixture（`tests/fixtures/epic7_world_boss/`，18 张）

| 文件 | 内容 |
|---|---|
| `lobby_with_knights.png` | 大厅（含骑士团图标） |
| `knights_home.png` | 骑士团主页 |
| `knights_signin_popup.png` | 骑士团签到弹窗（每天第一次进骑士团） |
| `knights_home_after_popup.png` | 点掉签到弹窗后的骑士团主页 |
| `gift_support_popup.png` | 「领取支援物品」弹窗（团员支援资源到账） |
| `worldboss_home.png` | 世界首领战主页（次数 `1/2`，可打） |
| `worldboss_home_exhausted.png` | 同上（次数 `0/2`，按钮变灰） |
| `team_select.png` | 选择辅助队伍页 |
| `team_config.png` | 配置队伍页（三队槽位**空**，细节量 ~451 = 尚未配置） |
| `team_config_configured.png` | 同上，三队**已填满**，细节量 ~1181，实跑抓取帧 |
| `stamina_popup.png` | 行动力不足弹窗 |
| `battle_result.png` | 战斗结算页 |
| `level_reward.png` | 战斗级别奖励弹窗（SS+ 评级、7 个宝箱） |
| `battle.png` | 战斗画面（`battle_scene_visible=True`）—— ⚠️ **不是首领战的战斗布局**：这是 4 格列阵（竞技场/远征）布局，右上只有 `? / A / 聊天 / 暂停` 四个图标、**没有跳过** |
| **`battle_live_skip.png`** | **首领战真实战斗帧**（团本布局）—— 右上角有 `跳过 ›`。用户实机截图按 `canvas = (render_x, render_y + 52)` 重建成 1982×1132。此帧 `battle_scene_visible=False`，仅靠旧判据认不出（`skip` 命中 0.9086） |
| **`battle_skill_anim.png`** | **首领战 boss 技能演出帧** —— 整块 UI 被演出盖住，**故意设计为认不出**（`skip` 仅 0.2529）。守「演出期间认不出是预期，不是故障」 |
| **`worldboss_home_chest_claimable.png`** | 主页**同一画面**，但「每周贡献度」宝箱 #1（27,500,000）**发光 = 可领**。⚠️ 这张图上次数是 **`0/2`**（按钮已灰）—— 所以它同时是「**先领宝箱、再判次数**」这条顺序的回归依据（顺序反了会在次数用完那一刻直接收摊，宝箱永远领不到） |
| **`worldboss_home_chest_claimed.png`** | 同一天的第二次实拍：**点完宝箱之后**的样子 —— 箱子原地变成**绿色对勾**，不弹窗、不换页，次数仍是 `0/2`。这是「**领完不会重复点**」的回归依据（绿勾那一态对可领模板只有 0.7085 < 阈值 0.80），也是「领完宝箱 ⇒ 判次数 ⇒ 干净收场」这条链路的终点证据 |

### 模板（`games/epic7/templates/world_boss/`，9 张）

`knights_title.png` / `worldboss_title.png` / `team_select_title.png` /
`level_reward_title.png` / `result_title.png` /
**`select_team_button.png`**（37×303，主页右下「选择队伍」，实施阶段补）/
**`team_config_auto.png`**（110×300，配置页左下「自动配置」，实施阶段补）/
**`battle_skip.png`**（117×48，战斗画面右上「跳过 ›」，2026-09-22 补）/
**`weekly_chest_lit.png`**（126×128，主页「每周贡献度」宝箱 #1 的**可领（发光）**外观，2026-09-23 补）

> 实施阶段才发现：前两个「标题」锚点在本路线内部**常驻**（见第三节 ①），
> 真正能用的排他锚点是后补的这两个按钮。另外 `select_team_button.png` 还被
> `navigation.py` 借去当 `lobby_worldboss_select_team`（跨目录共用同一份模板，
> 不重复维护）。

### 导航模板（`games/epic7/templates/navigation/`，新增 6 张）

- `lobby_knights.png`（74×70）—— 大厅底部骑士团盾牌，**只定位点击点**
- `worldboss_entry.png`（62×66）—— 骑士团主页的「世界首领战」骷髅盾牌，排他锚点
- `knights_signin_title.png`（46×460）—— 签到弹窗标题，排他锚点（跨页最高 0.3278）
- `knights_signin_close.png`（30×118）—— 签到弹窗「点击关闭」，
  **单独不可靠**（跨页最高 0.9986），只作为双锚点的第二半
- `gift_support_title.png`（48×278）—— 领取支援弹窗标题，排他锚点（跨页最高 0.4119）
- `gift_support_close.png`（29×114）—— 领取支援弹窗「点击关闭」，
  **单独不可靠**（跨页最高 0.9996），只作为双锚点的第二半

## 九、实施顺序（按 `EXTENDING.md` 安全验收顺序）

1. ✅ `tests/test_project_layout.py` 登记 `epic7_world_boss` 的精确文件集
2. ✅ 写**失败测试**（识别各页面锚点、阈值边界、负例拒绝）
3. ✅ 实现 `evidence/world_boss.py`（原子证据 + 页面组合）
4. ✅ 实现 `world_boss.py`（状态机 + Runner）
5. ✅ `modes.py` 注册 `ModeSpec`（含 `_build_world_boss` 工厂）
6. ✅ `navigation.py` 加导航链（含 `observe()` 两条判定 + 接力白名单）
6b. ✅ 助手入口接入（2026-09-22）：`desktop/catalog.py` 第 8 项 + `launcher.py` 第 7 项
6c. ✅ 骑士团系统弹窗接入全局弹窗守卫（2026-09-22，用户实测补充）：
  签到弹窗 + 「领取支援物品」弹窗，两条都是双锚点判据
6d. ✅ 战斗画面识别 + 右上角「跳过」（2026-09-22，实跑报错后用户补实机截图）：
  `battle_scene_visible` 在团本布局上恒 False ⇒ 补「跳过」锚点，见第十节
6e. ✅ 运行次数固定为 2、不再询问用户（2026-09-22，用户要求「不要让我选择次数」）：
  `desktop/catalog.py` + `launcher.py` + `main.py` 三处一致，见第四节「设计决策」
7. ⬜ 停在路线入口**干跑**
8. ⬜ `--live --confirm RUN --max-cycles 1` 实跑一轮
9. ⬜ 至少两轮实跑 + 资源不足场景验证

### 步骤 5/6 的验证口径

- `tests/test_modes.py`：注册表含 `world_boss`、默认状态 `home`、
  工厂从 `templates/world_boss` 建机器、六个页面键齐全。
- `tests/test_navigation.py::WorldBossNavigationTests`（11 个用例）：
  两页互不混淆、`lobby_with_knights` 仍判大厅、三页都**不**判大厅、
  两跳导航的点击坐标、从骑士团页接力和从首领战页接力各自跳过的跳数、
  未列出的页面接力被拒、别的路线不能接力进这两页、
  **签到弹窗被判成 `knights_signin_popup` 而不是 `unknown`**、
  **领取支援弹窗被判成 `gift_support_popup` 而不是 `unknown`**、
  **弹窗点掉后能重新认出骑士团主页**。
- 只读探针 `runtime_logs/_wb_probe_nav.py`（排他性矩阵）与
  `runtime_logs/_wb_probe_observe.py`（全库判页对照）。

### 步骤 6c 的验证口径（骑士团系统弹窗：签到 + 领取支援）

- `tests/test_global_popups.py` 每个弹窗各 5~6 个用例：
  双锚点都能命中、缺任一个锚点就拒绝、
  **点掉弹窗后的骑士团主页不再被判成弹窗**（否则会无限点）、
  其它五类全局弹窗（友情点数 / 好友申请 / 体力 / 断网 / 亲密度）都不误判、
  守卫能消费掉弹窗并点中「点击关闭」（签到 (961,847) / 领取支援 (959,855)）；
  领取支援多一条 **「不能把签到弹窗误判成领取支援弹窗」**（两者标题同 ROI）。
- `tests/test_main_story.py` 的守卫装配断言补 `knights_signin_templates` 与
  `gift_support_templates`（原来只断言 4 个模板，每加一个都会失败 —— 这类
  「参数个数写死」的断言在扩展共享组件时必须同步）。
- 全库排他性与判页对照：签到弹窗见 `_knights_signin_probe.py` /
  `_knights_signin_observe.py`，领取支援弹窗见 `_gift_support_probe.py`（190 张零误伤）。

### 步骤 6d 的验证口径（战斗画面识别 + 右上角「跳过」）

`tests/test_world_boss_runner.py::WorldBossBattleScreenTests`（8 个用例）：

- 真实战斗帧被判成 `BATTLE` 页；**同一帧用旧判据 `battle_scene_visible` 必须判 False**
  （锁住「为什么非加这条判据不可」，防止以后有人删掉锚点还能全绿）。
- 点击中心 = **(1631, 97)**，容差 ±3 px。
- `observe_battle` 在战斗帧上给出 `allowed_action=("skip-battle", (1631,97))`。
- 技能演出帧**故意认不出**（`skip` 0.2529 < 0.80）。
- 本路线另外 13 张页面帧都不被判成战斗页（含 `battle.png` 这个异布局帧）。
- 真监督 + 假时钟串演一遍：点跳过 → 结算页出现 → `RESULT_REACHED`，
  且**点击序列恰好是 `[(1631, 97)]`**（不多点）。
- 搜索窗口必须**完整落在 x<1760**（`x + width <= 1760`）且能把 SKIP_POINT 框住 ——
  把「窗口宽度本身就是锚点的一部分」这条实测结论固化下来。

全库排他性：`runtime_logs/_wb_battle_anchor_probe.py`，扫 192 张 1982×1132 夹具
（22 张尺寸不符跳过）：

| 口径 | 结果 |
|---|---|
| 真实战斗帧 | **0.9086** ✅ |
| 技能演出帧 | 0.2529（预期不命中） |
| 本路线其它页最高 | 0.3607（`knights_signin_popup`） |
| 跨路线最高 | 0.3815（`navigation/story_playing_live`） |
| 仅靠「跳过」（排除 `battle_scene_visible`）命中 | **只有** `battle_live_skip.png` |
| `world_boss_battle_visible=True` | 20 张，其中本路线 2 张（`battle.png` + `battle_live_skip.png`），其余是别的路线战斗帧被旧判据认成 True（预期） |

> 阈值 0.80：下方余量 0.44、上方余量 0.11。

### 步骤 6e 的验证口径（次数固定为 2）

三处都有测试钉住，改一处漏一处会红：

- `test_desktop_catalog.py::test_world_boss_is_fixed_to_two_cycles`：
  `default_cycles == 2`、`cycles_editable is False`、说明文字里有「2 次」
  （置灰的输入框必须能自解释，否则用户会以为控件坏了）。
- `test_launcher.py::test_world_boss_skips_count_prompt_and_runs_twice`：
  **断言「请输入运行次数：」没有出现**，且参数是 `--max-cycles 2`。
- `test_main_story.py::test_world_boss_defaults_to_two_cycles_without_the_flag`：
  不给 `--max-cycles` 时兜底成 2（而不是报「实跑模式要求 --max-cycles 为正数」）。

⚠️ **`test_launcher.py` 的参数化用例必须同时摘掉 world_boss**：
`test_selects_mode_then_cycles_and_calls_existing_live_entry` 是给「会问次数」的路线用的，
它按 `["平台", "编号", "次数"]` 喂输入。世界首领战不再问次数后，第三个输入没人消费、
`共 3 次` 的断言必红。**同类风险**：以后任何路线改成「不问次数」，都要把它从那个列表里摘掉，
并补一条「不问次数」的独立用例。

### 步骤 6b 的验证口径（助手入口）

桌面助手 `desktop/catalog.py` 的 `ROUTES` 是**独立维护的用户可见清单**，不会自动跟随
`modes.py` 的注册表增长 —— 新路线必须在两处都登记才会出现在界面上。

- `desktop/catalog.py`：新增 `RouteInfo("world_boss", "世界首领战", "实验功能", …)`，
  `default_cycles=1`、`cycles_editable=True`。
  **标「实验功能」而不是「正式功能」**：界面上标实验会在点「开始运行」时弹一次确认框
  （`DesktopController.needs_experimental_confirmation`），对一条还没实机跑过的路线正是需要的提醒。
  实机跑通两轮后再考虑提为正式。
- 说明文字必须写清两条红线：每场 20 体力、不够时**只用树叶**。界面是用户唯一的安全提示位。
- `desktop/app.py`：路线说明标签原本写死 `row=8`，第 8 条路线会把它压住 → 改成
  `row=len(ROUTES) + 1` 动态排。
- `launcher.py`：命令行菜单加第 7 项（**排在末尾**，不打乱既有 1~6 编号），
  提示语同步改为「请输入 1 到 7 之间的功能编号。」
- 测试：`test_desktop_catalog.py` 清单顺序 + 新增 `world_boss` 说明/状态断言；
  `test_launcher.py` 参数化用例加 `("7", "world_boss", "世界首领战")`。
  ⚠️ `test_invalid_values_are_reprompted_in_chinese` 原来用 `"7"` 当非法编号，
  加菜单项后 `"7"` 变合法 → 改用 `"9"` 守住「编号超出范围会重新询问」这条行为。
- ⚠️ **2026-09-22 后续：次数固定后这个参数化用例要摘掉 world_boss**。
  `test_selects_mode_then_cycles_and_calls_existing_live_entry` 是「会问次数」的路线才适用的，
  用例输入 `["1", "7", "3"]` 并断言 `共 3 次`；世界首领战改成不问次数后，
  第三个输入没人消费、断言必红。已按 `hero_synthesis` 的先例改成独立的
  `test_world_boss_skips_count_prompt_and_runs_twice`（断言「没有次数提示」+ `共 2 次`）。
  **同类教训**见 `topics/lessons.md`「扩展共享组件参数时『参数个数写死』的断言会成片红」——
  同一个家族：**测试把某个签名/分支写死，改实现就会连带红**，修法是补用例而不是放宽断言。
- 验证：`check.py --vs HEAD`（因动了共享模块 `desktop/app.py` 走全量）
  **949 passed / 1 skipped / 255 subtests**。

## 十、战斗画面：「跳过」锚点（2026-09-22）

### 起因：实跑报错其实是「战斗画面认不出来」

第一次实跑走到「点完开战按钮」就停了，日志是
`battle_unrecognized`（战斗画面持续 45 秒无法识别）安全停止。

当时的判断链是：`observe_page` 判战斗页只靠 `battle_scene_visible`（`battle_controls.py`，
4 格列阵 + 左侧行动顺序 + 右上暂停控件三条结构判据）。但**世界首领战是团本布局**：

| | 4 格列阵（竞技场/远征） | 世界首领战（团本） |
|---|---|---|
| 底部 | 4 个己方底座 | 4 个己方底座（同样有） |
| 右上 | `? / A / 聊天 / 暂停` | **`跳过 ›` / 聊天 / 暂停** |
| 右侧 | — | 12 个头像的得分列 |
| 左上 | — | boss 名 + 血条 |

实测这一帧上：`observe_battle_controls=TRANSITION`、圆只有 2/4、
`pause_controls=0.1048`、`turn_order=0.0466` ⇒ `battle_scene_visible=False`。
**整场战斗都认不出**，监督自然以 45 秒超时收场。

顺带纠一个先前的误判：`tests/fixtures/epic7_world_boss/battle.png` 是**4 格列阵**布局，
它上面 `battle_scene_visible=True`。当时据此认为「战斗页认得出、不需要跳过」，
是因为**那份夹具根本不是首领战的战斗画面**。团本布局的帧后来才由用户补上。

### 锚点参数（都已在 `world_boss.py` 里写成常量）

| 项 | 值 |
|---|---|
| 亮像素包围盒 | x=[1581,1682] y=[81,113]（102×33） |
| 模板 | `templates/world_boss/battle_skip.png`（117×48，含 8px 余量） |
| 搜索区 | `BATTLE_SKIP_REGION = (1500, 55, 260, 110)` |
| 阈值 | `BATTLE_SKIP_THRESHOLD = 0.80` |
| 点击中心 | **(1631, 97)** |

坐标怎么来的：用户给的是模拟器窗口截图（1920×1080 客户区），
`Epic7Window.capture()` 的画布是 1982×1132，映射关系
`canvas = (render_x, render_y + 52)`（`core/window.py::_legacy_canvas` 把 1920×1080 贴到 `[52:, :1920]`）。
**X 不需要缩放，Y 加 52**。点击换算由 `_click_legacy` 反向做 `(x, y-52)`。
以后从用户截图量坐标一律按这个换算，别自己猜缩放比。

### 三条硬约束（改这个锚点前必读）

1. **搜索窗口的宽度本身就是锚点的一部分**。
   「跳过」这个图形与剧情播放页的**是同一个**，区别只在位置：
   首领战 x≈1581~1682、剧情播放页 x≈1769~1886。
   窗口原来开 `(1400,52,582,150)`（为了放宽），剧情页拿到 **0.8585**，
   而正例 0.9086 —— 只差 0.05，几乎压线。
   收到 `(1500,55,260,110)`（右边界 1760）后剧情页掉到 **0.2803**，正例仍是 0.9086，
   间距 **0.63**。所以 `test_skip_anchor_window_stays_left_of_the_story_skip_button`
   断言 `x + width <= 1760` —— **别为了「稳一点」再把窗口开宽**。
2. **boss 技能演出期间认不出是预期，不是故障**。
   演出会把整块 UI 盖住，那一帧 `skip` 只有 0.2529。
   这正是 `battle_supervisor` 的 45 秒窗口存在的意义：单帧认不出不触发安全停止，
   连续 45 秒认不出才停。别为了让「每一帧都认得出」去调低阈值。
3. **「跳过」是战斗内动作，走 `allowed_action` 通道，不要在观察函数里直接点**。
   `allowed_action` 由监督记账（最多 4 次、点完要有进展），观察函数没有账本，
   自己点会变成无界重试。
   同时 `WorldBossRunner` 必须把监督的尺子改宽：
   默认 `allowed_action_retry_seconds=3 / failure=15` 是给**战前弹窗**定的
   （弹窗点了没反应就该判失败），而战斗本来要打几十秒。
   这里用 **retry=5 / failure=90**：跳过没生效也得让这场战斗自然走到结算页。

> 另一条相关红线（在 `runner_base.py`，非本路线专属）：
> **别把「我看到战斗画面了」做成移交入口**。那会把移交点推到战斗开打之后，
> 而监督要靠「结算页出现」才退出 ⇒ 战斗打完了程序还在轮询，磨到绝对超时 900 秒。
> 战斗画面只能当**转场验收依据**（`battle_visible`），不能当移交条件。

### 修正后的实跑流程

```
世界首领战主页
  → 「选择队伍」
  → 配置队伍页（认「队伍已配置」→ 已配置就跳过自动配置）
  → 点开战按钮（主循环自己点，不移交）
      ⇒ 一旦点下即「已承诺战斗」：见结算页之前禁回大厅
  → 战斗画面（跳过 0.9086 命中 ⇒ BATTLE）
      ├ allowed_action=("skip-battle", (1631,97)) ⇒ 监督点掉
      └ 技能演出帧认不出 ⇒ 不动作，继续轮询（45 秒窗口兜底）
  → 结算页**或**「战斗级别奖励」弹窗（两者任一命中，连续 2 帧稳定）
      ⇒ RESULT_REACHED，监督退出
  → 点「确认」→ 战斗级别奖励弹窗 → 领奖励
  → 回主页看次数（0/2 ⇒ 正常结束；红点缺失 ⇒ 直接退出）
```

**「打完了没有」永远是靠结算页认出来的**，不靠看战斗动画。
跳过只是把「等战斗演完」的时间缩短，即使跳过一直不生效，流程也能靠结算页收场。

⚠️ **2026-09-23 补**：点完「跳过」游戏会**直接**弹出奖励弹窗（结算页只是短暂闪现，
1 秒一帧的轮询可能抓不到），所以「战斗结束」的判据必须是
**结算页 or 奖励弹窗**，不能只认结算页 —— 详见下一节。

## 十一、「跳过之后认不出奖励弹窗」（2026-09-23 实跑）

### 现象

跳过动画确实生效了，但紧接着 45 秒报 `battle_unrecognized` 安全停止，
「级别奖励」一步都没走到。

### 时间线（`epic7_world_boss.log` 2026-09-23）

```
18:24:19  动作=skip-battle 尝试=1/4        ← 监督点掉「跳过」
18:24:30  （画面变成奖励弹窗，此后不动）  ← 距上次画面变化 36 秒
18:25:15  状态=安全停止 原因=battle_unrecognized
```

诊断帧 `20260923_182515_306884_battle_unrecognized.png` = 「战斗级别奖励」弹窗
（标题 + 8 个宝箱 + 「全部开启」，右侧背景能看到结算页的「战斗结果」「确认」和伤害 7,063,227）。

### 真因：`result_visible` 把奖励弹窗**主动排除了**

`games/epic7/world_boss.py::observe_battle()` 原写法：

```python
result_visible = (
    self._locate(screen, "result_title") is not None
    and self._locate(screen, "level_reward_title") is None   # ← 问题在这
)
```

那半截排他是从 `evidence/world_boss.py` 的
`PageEvidence("world_boss.result", forbidden=("level_reward_title",))` 抄来的。
**那个 `forbidden` 是「页面身份」需求**（奖励弹窗是压暗的结算页，
`result_title` 在它上面还有 0.7103 ⇒ 两页不许互相串判）；
抄到「这一局的战斗结束了没有」这条判据上，就变成把奖励弹窗**排除在「结束」之外**。

于是弹窗帧上监督五条判据全假：

| 判据 | 弹窗帧取值 | 为什么 |
|---|---|---|
| `result_visible` | False | `level_reward_title` 命中 ⇒ 被排他掉 |
| `battle_visible` | False | 跳过按钮已经没了 |
| `allowed_action` | None | 跳过按钮没了 ⇒ 无可点动作 |
| `pre_battle_visible` | False | 不是队伍页 |
| `pre_battle_business_visible` | False | 不是体力弹窗 |

⇒ `recognized` 全假 ⇒ 45 秒看门狗安全停止，而状态机里
`LEVEL_REWARD → open-all-chests` 那条分支一直没人来调。

### 修法（一行 + 两条回归）

```python
result_visible = (
    self._locate(screen, "result_title") is not None
    or self._locate(screen, "level_reward_title") is not None
)
```

**判据命名对照**：判「是不是 A 页」要排他（不是 B 才算 A）；
判「A 阶段结束了没有」要合并（B 出现恰恰是 A 结束的另一种表现）。
同一个锚点在两种判据里极性可以相反，抄之前先问「我要回答的是『哪一页』还是『还在不在』」。

### 验证（不是「改完就绿」）

只读探针 `runtime_logs/_wb_predicate_probe.py`（不碰模拟器）把两版判据并排量出来：

| 夹具 | `result_title` | `level_reward_title` | 旧判据 | 新判据 |
|---|---|---|---|---|
| `battle_live_skip` | 0.0000 | 0.0000 | False | False |
| `battle_result` | 1.0000 | 0.0000 | True | True |
| `level_reward` | 0.0000 | **1.0000** | **False** | **True** |

⇒ 修之前这条判据在 `level_reward` 上确实是红的，且战斗帧不会被误判成「已结束」。

回归用例（`tests/test_world_boss_runner.py::WorldBossBattleScreenTests`，+4）：
1. `test_level_reward_popup_counts_as_the_battle_being_over` —— 弹窗帧 `result_visible=True`
2. `test_result_page_alone_still_counts_as_the_battle_being_over` —— 纯结算页不回退
3. `test_battle_frame_is_not_reported_as_battle_over` —— 战斗帧不许判成结束（防提前交还）
4. `test_skip_then_level_reward_popup_hands_the_business_back` —— 端到端：真监督 + 假时钟，
   帧序列「战斗×2 → 弹窗×2」⇒ `RESULT_REACHED` + 恰好点一次跳过 + 状态机接着给出
   `open-all-chests`（这是实跑里断掉的那一环）

门槛：`check.py --vs HEAD` ⇒ **994 passed / 1 skipped / 272 subtests / 0 failed / 0 error**
（`world_boss.py` 认不出路线 ⇒ 走了全量）。

### 顺带修掉「领奖白等 45 秒」

`open-all-chests` 点完按钮原地变「确认」，页面**还是** `LEVEL_REWARD`，
所以 `next_action` 会再返回一次 `open-all-chests` —— 而主循环对同名动作要等
`_ACTION_RETRY_SECONDS = 45` 秒才允许再点。流程本来能走通（第二下正好落在「确认」上，
两点只差 2px：(961,994) vs (959,994)），但中间白等 45 秒。

**修法**：`WorldBossRunner` 给这个动作单独一把短尺子。

```python
_OPEN_ALL_CHESTS_RETRY_SECONDS = 5.0        # 默认 _ACTION_RETRY_SECONDS = 45

def _action_retry_seconds(self, action_name: str) -> float:
    if action_name == "open-all-chests":
        return self._OPEN_ALL_CHESTS_RETRY_SECONDS
    return super()._action_retry_seconds(action_name)
```

**回归**（`WorldBossRunnerTests::test_reward_claim_second_click_waits_only_the_short_window`）：
假时钟量「两次点击之间的间隔」—— 实测 **6.0 秒**（配置 5 秒 + 主循环「两帧稳定」
那道门占去的一帧，轮询 1 秒/帧），修之前是 **45 秒**。
断言写成「≥ 配置窗口 且 ≤ 10 秒」而不是等值断言：干等 45 秒会被挡住，
但不会把「多一帧稳定期」这种实现细节焊死。

> 还留着的粗糙处（**没改**）：这一步靠「同一个坐标点两次」推进，不是靠独立判据
> （`CLICK_POINTS` 里 `confirm-level-reward` 至今没有任何判据引用它）。
> 要做干净，得先有「确认」按钮那一态的锚点模板 —— 现有诊断帧只有「全部开启」那一态。

---

## 十二、「0/2 了还在一直点」——判据写好了却没接上（2026-09-23 实跑）

### 现象

用户实跑反馈：游戏里次数已经显示 `0/2`、按钮已经变灰，程序**还在点「选择队伍」**，
打完这一轮也不停。

### 真因：**不是判据不准，是判据从来没被调用过**

第一反应都是「判据在实机上失效了」，所以先跑只读探针量（`runtime_logs/_wb_chest_probe.py`）：

| 画面 | 「选择队伍」底板的绿占比 | 判据结论 |
|---|---|---|
| 用户实拍截图（`0/2`） | **0.0000** | 已变灰 ✅ 正确 |
| `worldboss_home.png`（`1/2`） | 0.5924 | 可点 ✅ 正确 |
| `worldboss_home_exhausted.png`（`0/2`） | 0.0000 | 已变灰 ✅ 正确 |

判据本身**完全正确**。真正的问题在另一边：一次 grep 就定性了 ——
`select_team_enabled` 只出现在**单元测试和本文档**里，`next_action` **从来没调用过它**（死代码）。

于是主页在 `0/2` 时照样返回 `open-team-select`：
**灰按钮点不动 → 45 秒转场超时 → 重试 4 次 → 回大厅恢复 → 再点……**
用户看到的「一直在点」就是这条环路。
（⚠️ 这是当时的事故链路：那会儿还有「回大厅恢复」这一步，2026-09-26 已整段删除 ——
现在重试 4 次之后是**直接安全停止**。）

> 通用教训：「判据不准」和「判据没接上」是两类 bug，**先量判据取值、再看它有没有进决策路径**，
> 比直接改阈值快得多。已写进 `topics/lessons.md`。

### 修法

1. `core/runtime.py`：抽出 `ResourceExhausted(RuntimeError)` 基类（带类属性 `stop_label`），
   `StaminaExhausted` 改成它的子类 —— 「没本钱了」这条通道从「生命之叶专用」变成通用。
2. `runner_base`：主循环与空跑的 `except StaminaExhausted` 都改成 `except ResourceExhausted`，
   日志文案改成 `停止={error.stop_label}`（**不再写死**「生命之叶」）。
3. `world_boss.py`：新增 `AttemptsExhausted(ResourceExhausted)`（`stop_label = "今日次数已用完"`），
   `HOME` 分支**先判次数，再决定要不要发「选择队伍」**。

```python
if page is WorldBossState.HOME:
    self.state = WorldBossState.HOME
    if not select_team_enabled(screen):
        raise AttemptsExhausted("主页「选择队伍」已变灰（今天次数已用完）")
    return self._action("open-team-select", ...)
```

走的是项目既有的资源退出通道（**退出码 2**，与竞技场「门票耗尽」同构）：
还能干、但没本钱了 —— 不是故障，也不能装作跑满了要求的轮数。

### ⚠️ 接上判据时暴露的破坏性风险（**必须一起堵**）

判据原本没生效，所以「它准不准」从没被实跑检验过。接上之后立刻冒出反方向的问题：
判据是 HSV 的**绝对**亮度（`V >= 90`），而页面识别用的 `TM_CCOEFF_NORMED`
**对亮度缩放不敏感**。两者一凑，**页面淡入的暗帧**会同时满足「认得出是主页」+「绿条判灰」
⇒ **还有次数却提前退出**。这比原来的「一直点」更伤，所以必须一起改掉。

只读探针实测（`runtime_logs/_wb_fade_probe.py`，把夹具按比例压暗）：

| 量 | 亮度 1.0 | 0.7 | 0.5 | 0.1 |
|---|---|---|---|---|
| `1/2` 绿占比（**绝对**判据） | 0.5924 | 0.2287 | **0.0102** ← 穿过 0.10 阈值 | 0.0000 |
| `1/2` 绿条亮度 ÷ 整幅亮度（**相对**） | **1.900** | 1.909 | 1.907 | **1.952** |
| `0/2` 绿条亮度 ÷ 整幅亮度（**相对**） | **0.615** | 0.610 | 0.611 | 0.568 |

**相对量在压暗 10 倍的全过程几乎不动**（1.90~1.95），而「真变灰」只有 0.57~0.62 ——
两侧差 3 倍，阈值 `SELECT_TEAM_BAR_RELATIVE_V = 1.2` 取在中间，余量很大。
页面识别在压暗到 50% 时**仍然判成主页**（测量表里那一列），所以「模板匹配能抗、颜色判据不能抗」
不是理论担忧，是这张表上就有的事。

**落地形状：两道判据取或。**

```python
def select_team_enabled(screen) -> bool:
    if select_team_green_ratio(screen) >= SELECT_TEAM_ENABLED_GREEN_RATIO:
        return True   # 绿得明显（含轻微压暗）⇒ 直接放行，省一次整幅 HSV
    return select_team_bar_relative_v(screen) >= SELECT_TEAM_BAR_RELATIVE_V
```

⚠️ **不能改成「且」**：那样淡入暗帧照样掉在第一道外面 ⇒ 误判「次数用完」⇒ 提前退出，白绕一圈。

### 回归（6 条）

| 用例 | 守什么 |
|---|---|
| `test_faded_home_with_attempts_left_is_not_read_as_exhausted` | 淡入暗帧上**旧判据确实会塌**（先钉住），新判据不上当 |
| `test_faded_exhausted_home_is_still_read_as_exhausted` | 反向：压暗不能把**真灰**洗成可点 |
| `test_exhausted_home_stops_instead_of_asking_for_the_team_button` | `next_action` 必须**抛 `AttemptsExhausted`**（守的是接线） |
| `test_faded_home_with_attempts_left_is_still_asked_for_the_team_button` | 淡入帧仍要正常报 `open-team-select` |
| `test_exhausted_home_ends_the_run_without_a_single_click` | 真状态机 + 真 Runner：正常收场、`resource_exhausted=True`、**一次都不点** |
| 既有 3 条 `WorldBossCountTests` | 判据本身的取值不回退 |

`test_exhausted_home_ends_the_run_without_a_single_click` 的最后一行断言
（`self.assertEqual([], clicks)`）才是「一直在点」的**可测形式** ——
前面几条只证明判据对、接线对，这条证明**行为对**。

### 验证

- 定向：`test_world_boss_runner.py` → `41 passed, 27 subtests passed`。
- 全量门槛（动了 `core/runtime.py` + `runner_base.py` ⇒ 判全量）：
  `check.py --vs HEAD` → **1001 passed / 1 skipped / 0 error**（9 分 00 秒）。

---

## 十三、「每周贡献度」宝箱先领再开下一把（2026-09-23 用户实拍补充）

### 业务口径（用户 2026-09-23 明确）

> 「在进行第二把之前，要看一下有没有宝箱可以领。相当于就是**领完宝箱之后，才是一轮结束**。」

主页右上角「每周贡献度」进度条上按累计贡献解锁两档宝箱，**每周最多两个**；够量的会**发光**。

| 档位 | 门槛 | 位置 | 状态 |
|---|---|---|---|
| #1 | `27,500,000` | 进度条**左侧** | ✅ 已实现 |
| #2 | `44,000,000` | 进度条**右侧** | ✅ **已实现**（2026-09-25 补样本；⚠️ #2 **不能**复用 #1 的模板 —— 实测只有 0.5161，两档外观不是同一个东西，各用一份模板 + 各管一段搜索区） |

### ⚠️ 顺序：**先领宝箱，再判次数**

用户的实拍截图正是「次数 `0/2`（按钮已灰）+ 宝箱 #1 可领」这个状态。
第十三节这个顺序要是写反了，程序会在「次数用完」那一刻**直接收摊走人**，
宝箱永远领不到 —— 而这恰恰是用户最关心的那一帧。所以 `HOME` 分支的判断次序是：

```python
chest = find_weekly_chest(screen, self.templates.weekly_chest)
if chest is not None:                      # ① 先领宝箱
    return self._action("claim-weekly-chest", source_page="世界首领战主页",
                        point=chest.center, reason=f"...得分 {chest.score:.4f}")
if not select_team_enabled(screen):        # ② 再看次数
    raise AttemptsExhausted(...)
return self._action("open-team-select", ...)
```

宝箱是**同页动作**（点完箱子不发光、页面不变）⇒ `target_pages` 留空，
验收靠**页面内状态证据**「宝箱模板不再命中」，与「自动配置」按钮橙→蓝同构。

### ⚠️ 「没找到宝箱」也是一条结论：必须带实测数字进日志（2026-09-26 加）

2026-09-25 23:01 那次实跑：机器人进到主页两秒后就以「今日次数已用完」收摊，
而日志里**一句关于宝箱的话都没有** —— 事后拿着日志根本分不清
「当时确实没有可领的宝箱」和「判据漏了、本来该领没领」。用户当天就把这条点出来了。

⇒ 现在只要停在主页、没找到可领宝箱，`_chest_scan_report()` 会把**两个槽位的实测数字**
写进结论里（形状最高分 + 亮度比 + 门槛），并且这个结论会跟着后面那一步一起进日志：

```
… 判断依据=主页点「选择队伍」进辅助队伍页；宝箱扫描=#1 形状0.66/亮度比1.02，#
  2 形状0.26/亮度比0.98（可领门槛：形状≥0.80 且 亮度比≥1.50）⇒ 这一屏没有可领的宝箱
```

数字的作用是让人**一眼看出「差得远」还是「差一点」**—— 后者意味着判据要修。
所以**不许**只写「没有宝箱」四个字，也**不许**用「多半是…」这种推测充当结论。

### 判据：模板匹配，**不是**颜色

一开始试的是「暖金色掩膜」（`runtime_logs/_wb_chest_gold_probe.py`），**不可用**：

- **没点亮**的宝箱本身也带暖色内容（箱体内那团橙红光效）；
- `team_config` / `lobby_with_knights` / `battle` 等页面在**同一区域**有面积大得多的金色块
  （最大 25019 px）⇒ 完全不排他。

改用模板匹配后，同一个位置、同一个模板：

| 画面 | 面板内最高分 |
|---|---|
| 可领（正例） | **1.0000** |
| **已领 = 绿勾**（`worldboss_home_chest_claimed.png`） | 0.7085 |
| 未点亮，`1/2`（`worldboss_home.png`） | 0.6559 |
| 未点亮，`0/2`（`worldboss_home_exhausted.png`） | 0.6559 |
| **全库 194 张**里其它路线最高（`epic7_pc_story/story_skip.png`） | 0.4878 |

⇒ `WEEKLY_CHEST_THRESHOLD = 0.80`：对「已领」**下方余量 0.09**、对「未点亮」下方余量 0.14。
⚠️ 「已领」的余量比「未点亮」薄 —— 因为绿勾底下还架着宝箱本体，明暗结构和可领态更近。
**改阈值前重跑 `runtime_logs/_wb_chest_build_assets.py`**：阈值 0.80 下全库只命中「可领」那 1 张。

能分开的原因不是「有没有金色」，而是「亮箱体 / 暗箱体」的**明暗结构**差异 ——
这也解释了为什么颜色掩膜不行而模板匹配行。

**搜索窗口就是锚点的一部分**（同第十节「跳过」的教训）：
`WEEKLY_CHEST_REGION = (1535,250,250,250)` 右边界收在 1785，**故意不盖到进度条右侧的宝箱 #2**。

这条线的承重性现在有实测数字了（`runtime_logs/_wb_chest_after_claim_probe.py`）：
宝箱 #2 **未到档**时（用户贡献度 37,952,979 < 44,000,000）它的外观对本模板得 **0.7833** ——
离阈值只差 **0.017**。之所以今天不会误触发，全靠**匹配中心落在 x=1825、在搜索区右边界之外**
（在区内做模板匹配，中心最多只能到 1722）。
⇒ **谁要把这个搜索区往右放宽，先看这条**；补宝箱 #2 时必须给它**自己的搜索区**，
不能靠放宽 #1 的窗口。

### 资产怎么来的

两张样本都来自用户 1920×1080 实拍截图，按
`core/window.py::_legacy_canvas` 的 `(x, y+52)` 偏移还原成 1982×1132 画布
（**与 `battle_live_skip.png` / `battle_skill_anim.png` 同一套做法**）：

| 资产 | 来源 |
|---|---|
| 模板 `weekly_chest_lit.png` = 画布 `(1594,308,126,128)` | 第一次实拍（宝箱**发光**） |
| 夹具 `worldboss_home_chest_claimable.png` = 整张画布 | 第一次实拍（发光 + `0/2`） |
| 夹具 `worldboss_home_chest_claimed.png` = 整张画布 | 第二次实拍（**绿勾** + `0/2`） |

- 生成 + 全库排他扫描：`runtime_logs/_wb_chest_build_assets.py`（可重复跑，已复跑验过
  前两个资产的哈希不变）
- 三态对照 + 宝箱 #2 定点测量：`runtime_logs/_wb_chest_after_claim_probe.py`

> ⚠️ **正例得分 1.0000 是循环论证**（模板就是从这张图裁的），**不能当证据**。
> 真正的证据是**负例方向的余量**（未点亮两个主页 0.6559 / 已领 0.7085）和
> **全库排他**（其它路线最高 0.4878）。
> 第一次实跑时留意日志里 `claim-weekly-chest` 那条的得分，那才是真实余量。

### 回归（8 条 `WorldBossWeeklyChestTests` + 2 条 Runner 级）

| 用例 | 守什么 |
|---|---|
| `test_claimable_chest_is_found_at_the_measured_centre` | 正例能认出来、中心落在实测点 `(1657,372)` |
| `test_unlit_chest_is_not_reported_as_claimable` | 未点亮不许判可领，**并断言离阈值 ≥ 0.10 的余量**（只断言 `is None` 的话，阈值调到 0.10 也能过） |
| `test_claimed_chest_is_not_reported_as_claimable` | **已领（绿勾）不许判可领** —— 判错的后果就是「领完还一直点」。余量只有 0.09，所以这一条卡 0.05 而不是 0.10 |
| `test_no_other_world_boss_page_looks_claimable` | 本路线 18 张里**只有正例**命中 |
| `test_home_with_a_claimable_chest_claims_before_judging_attempts` | **顺序**：`0/2` + 有宝箱 ⇒ 必须出 `claim-weekly-chest`，而不是抛 `AttemptsExhausted` |
| `test_home_without_a_chest_still_reports_the_team_button` | 反向：没宝箱时不许冒出领宝箱动作 |
| `test_home_after_claiming_ends_the_cycle_instead_of_clicking_again` | **链路终点**：绿勾 + `0/2` ⇒ 直接抛 `AttemptsExhausted`，不回头再点绿勾、也不点灰按钮 |
| `test_chest_box_matches_the_template_size` | 裁框与模板同尺寸（换模板忘了改框 ⇒ 得分莫名变低） |
| `WorldBossRunnerTests::test_claiming_a_chest_that_never_goes_away_stops_after_bounded_tries` | 点了不消失 ⇒ **有界**（恰好 4 次点击后收场），不会变成新的「一直点」 |
| `WorldBossRunnerTests::test_claiming_the_chest_then_running_out_of_attempts_ends_the_cycle` | **整条链路跑真 Runner**：发光 `0/2` → 点掉 → 绿勾 `0/2` ⇒ 退出码口径 2、**整轮只点宝箱**（一次都不能碰灰掉的「选择队伍」） |

后两条 Runner 级用例还有副作用价值：它们用**真实**的
`_WEEKLY_CHEST_RETRY_SECONDS = 3.0` 与假时钟 —— 窗口若退回默认的 45 秒，
帧预算内根本走不到第 5 次尝试，终局错误会变成状态超时，断言那句错误文案时就会红。
所以它们顺带守住了「短窗口」。

### ✅ 点完宝箱之后是什么页面：已确认（2026-09-23 用户补第二张图）

**原地变绿色对勾，不弹窗、不换页。** 因此：

- **成功路径的验收**仍然是「宝箱模板不再命中」——够用，不需要额外的正面模板：
  绿勾那一态本身只有 0.7085，**认不出来**，所以下一轮必然走到判次数那一步。
- 为什么**没有**为此新增一个「绿勾」模板做正面确认：那会引入一个**新的失败分支** ——
  领取动画中间帧若两个模板都不命中，就只能靠「重试还是放行」二选一，
  而「重试」会在游戏已经领完的情况下白点、「放行」就等于现在的行为
  （等于白加一层）。按「简单优先」，不为了好看引入这个分支。
  真要正面确认时，绿勾模板可用性已经量过：自匹配 1.0000、在「发光」图上 0.7081，
  余量 0.29，**随时可以补**。
- 「绿勾」这个状态顺便给了人眼一个复核点：日志里 `每周贡献度宝箱发光（得分 …）= 可领`
  出现过、之后不再出现，就说明领到了。
