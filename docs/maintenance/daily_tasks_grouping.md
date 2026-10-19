# 「每日任务」面板的四分组与整组勾选

> **2026-10-18 改版**（取代 2026-10-08 的三分组 + 三颗批量按钮）。
> 用户原话：「最终就是四类：每日、按需、赛季、活动」；
> 「把这个全选和取消全选都给关掉……我需要的是在每一个分类里面，左边有一个打勾的，
> 打勾之后我就可以把这一类所有都放进去，取消也可以取消全选某一类」。
>
> 四类 = **每日 / 按需 / 赛季 / 活动**。

## 1. 分组的判据

分组依据是**「这条路线该按什么节奏跑」**，不是路线本身的功能：

| 分组 | 判据 | 成员 |
| --- | --- | --- |
| **每日** | **几乎每天都要跑**，天天在、跑不跑不该犹豫 | 竞技场 / 刷书签 / 世界首领战 / 骑士团捐赠 / 迷宫强化石 / 圣域收菜 / 社区签到 |
| **按需** | **内容常驻、但跑不跑看当下需不需要** | 英雄合成 / 主线 / 狗粮 / 支线故事 / 月光剧场 |
| **赛季** | **按赛季轮换**，赛季一换内容与阶段就变 | 远征 / 月塔 |
| **活动** | **限时活动**，随活动开合出现 / 消失 | 活动（survivor） |

⚠️ **「按需」与「每日」的差别是「跑不跑」，不是「内容在不在」** —— 这是 2026-10-18
新增这一组时唯一要守住的分界。主线 / 狗粮 / 支线故事 / 月光剧场都是**长期存在**的内容，
不是限时活动；它们只是不需要天天跑。所以这一组**不能**叫「临时」（那容易读成
「快下线了」，与「活动」撞车），也不能并进「每日」（那样每日那栏会膨胀到 12 条，
真正每天必跑的那 7 条反而被淹掉）。

两个历史上容易搞错、结论没变的归属：

- **狗粮算「按需」** —— 2026-10-08 用户说「狗粮算日常」，2026-10-18 明确改口归按需。
- **月塔算赛季** —— 用户原话「之前我们是不是做过远征……它其实这些都属于赛季，
  就它有时候会轮换」。

## 2. 常量住在哪

全部在 `desktop/catalog.py`：

```
GROUP_DAILY / GROUP_ONDEMAND / GROUP_SEASON / GROUP_EVENT   # 四个中文名
GROUPS                                       # 展示顺序（从上到下）
RouteInfo.group                              # 每条路线挂在哪一组
routes_in_group(group)                       # 某一组的路线，按书写顺序
grouped_routes()                             # ((组名, 该组路线), ...)，滤掉空组
```

⚠️ **四个名字是「界面分组」，不是路线属性**：

- 它们**不进 `ModeSpec`**。`ModeSpec` 装的是路线的本质属性（模式名 / 次数 /
  状态机 / 导航计划）；「每日还是按需」是给用户看的话术，换个客户端可能就变。
- 「每日」这个**分组名**与模块 `daily_tasks` **不是一回事**。后者是「把几条串起来
  一次跑完」的**编排**，它读的清单按勾选先后走，与分组无关。
- 分组的**顺序**由 `GROUPS` 定死，**不从 `ROUTES` 的书写顺序派生** —— 否则往
  `ROUTES` 里插一条新路线就可能把面板顺序搅乱。`ROUTES` 的顺序仍然是「组内顺序」。

## 3. 界面怎么渲染（`desktop/app.py`）

- **组标题本身就是勾选框**（`_build_group_header`）：点一下整组勾上、再点一下整组取消。
- **面板没有卡头**（2026-10-18 用户划掉整条要求删）：原来那里是一行「每日任务 + 操作
  说明」，实测是整块面板里最占地方的一处 —— 删掉之后 `reqheight` 从 1819 降到
  **1743** 设备像素（约 38 逻辑像素的两行文字），窗口高度才敢压到 88%。
  ⚠️ 代价：**「点分组名可以整组勾选」没有任何界面提示了**，只能靠分组名左边那个
  勾选框自己暗示。想让用户知道这条，只能在这份文档 / USER_GUIDE 里写，
  **别偷偷把它加回一行提示** —— 那等于把刚省下的高度又还回去。
- 路线**扁平**排在同一个 grid 上（不是每组套一个子 Frame）。这样各组的格子共用
  同一套列宽，四个分组左边缘对齐，纵向看是一张表；套子 Frame 的话每组各算各的
  列宽，组和组之间会错开。每组的标题占 1 行（**从第 0 行起**），格子从下一行起按
  `columns` 折行。
- 界面层**不写路线名单、不写中文字面量** —— 只调 `grouped_routes()` 拿到什么画
  什么，插一条新路线只改 `catalog.py`。

## 4. 整组勾选的语义

逻辑在 `DesktopController.select_group` / `clear_group`，界面入口在
`DesktopApp._on_group_toggle`。

### 4.1 勾上 = **追加到末尾**，不是整体替换

用户拍板的语义是「**勾选先后就是执行顺序**」（2026-09-29）。点某一组的勾选框，
等于**现在才开始勾这一组** ⇒ 它们排到已勾内容的后面。

⚠️ 这一点和 2026-10-08 的「全选」（整体替换成面板顺序）**不一样，是刻意改的**：
整体替换会把用户先前手挑的顺序抹掉，而「先勾主线、再整组勾每日」是完全合理的用法。

`test_group_selection_appends_after_what_is_already_ticked` 钉住。

### 4.2 组标题的勾是**回算**的，不是「上次按了什么」

组勾选框的语义是「**这一组是否全部勾上了**」（`app._all_selected`），每次
`_refresh_task_rows` 都按真实勾选重算：

- 手动取消组内一条 ⇒ 组标题的勾**自动消失**（此时它是"部分选中"）；
- 这时再点组标题 ⇒ **整组重新勾上**（把少的那条补回末尾），不是"清空"。

这样「点一下全选、再点一下全不选」这个来回始终成立。

⚠️ 为什么不做成 Tk 的三态（`alternate`）：vista 主题下三态**没有可靠的视觉反馈**，
用户会以为是画错了。回算两态 + 「再点一下是重勾」是更稳的组合。
`test_unticking_one_route_drops_the_group_box` 钉住。

### 4.3 取消只取消**这一组**

`clear_group` 只把该组的路线从 `selection` 里拿掉，别组一条都不动 —— 这正是用户
说的「取消全选某一类」。旧的「取消全选」会把**所有组**一起清空，做不到这一点。
`test_a_group_header_untickes_the_whole_group_and_leaves_others_alone` 钉住。

### 4.4 互斥仍然成立

`survivor`（活动）的 `needs_navigation=False` ⇒ `RouteInfo.standalone_only`
为真，**只能单独跑**（起点得由人先把游戏停在选卡页，串在别的路线后面时那个
前置条件早被破坏）。所以：

- 勾「活动」组 ⇒ 结果**只剩它**，其余组全被清掉（界面上那些组的勾也跟着灭）；
- 先勾了活动、再勾别的组 ⇒ 活动被踢掉。

`test_the_event_group_replaces_other_selections` 钉住。

## 5. 踩过的坑

### 5.1 序号圈码用尽（真 bug，被新测试当场抓出）

`_CIRCLED` 只有 10 个圈码（①②…⑩），而「每日 + 按需」一次能勾 **12 条**。

```
IndexError: string index out of range
  app.py: prefix = self._CIRCLED[self.controller.selection.index(mode)]
```

**用户一点那颗按钮，整个界面就崩。** 修法：加 `_position_prefix(index)` 统一出口
—— 头 10 位圈码，之后用 `11.` `12.`。序号的**语义**是「你排第几」，不是
「必须画个圈」，所以超出的部分退回阿拉伯数字是合理的，不该往 `_CIRCLED` 里硬塞字符。

`test_group_numbers_reflect_panel_order` 钉住它，且断言里**独立**算出
期望前缀（不调 `_position_prefix`），并显式要求选中数 > 10 —— 否则这条测试
永远碰不到那个坎。

### 5.2 「视觉顺序」不能靠遍历

`_task_panel_descendants()` 是深度不限的遍历，**兄弟控件的先后取决于遍历策略**
（用栈是后进先出 ⇒ 拿到的顺序是反的）。测试里要「从上到下」就必须按
`grid_info()["row"]` 排序，不能拿遍历顺序当视觉顺序。

### 5.3 组标题从 Label 换成 Checkbutton，样式名要跟着换

`Group.TLabel` 已随旧标题删除，现在是 `Group.TCheckbutton`（`desktop/theme.py`）。
字号与字重不变，只是多了一个系统绘制的勾选框。**别留着 `Group.TLabel` 不删** ——
它没有引用者，会让后来的人以为还有地方用 Label 画组标题。

### 5.4 运行期间点组标题：要**把勾撤回去**

`_on_group_toggle` 在 `controller.worker.running` 时弹提示并 `return`。此时
Checkbutton 已经把变量翻过去了 —— 不重刷界面的话，勾选框会停在「已勾」上骗人，
而实际上一条都没勾。所以拒绝分支里必须补一次 `_refresh_task_rows()`。

## 6. 护栏一览

| 测试 | 钉住什么 |
| --- | --- |
| `test_groups_are_defined_in_display_order` | 四个中文名与展示顺序（**写死**，不读实现） |
| `test_group_membership_is_what_the_user_asked_for` | 逐条归属真值表（15 条覆盖满） |
| `test_grouped_routes_returns_display_order_and_skips_empty_groups` | 不漏不重；组内仍按书写顺序 |
| `test_task_panel_renders_a_group_header_per_group` | 四个组标题（Checkbutton）按行号递增，且各自排在自己那组路线**之前** |
| `test_the_old_bulk_buttons_are_gone` | 三颗批量按钮**真的删掉了** |
| `test_a_group_header_ticks_the_whole_group` | 点「每日」= 那 7 条全上，别组一条不动 |
| `test_a_group_header_untickes_the_whole_group_and_leaves_others_alone` | 再点一下只清这一组，别组保留 |
| `test_unticking_one_route_drops_the_group_box` | 取消一条 ⇒ 组勾自动消失；再点组标题是**重勾** |
| `test_group_selection_appends_after_what_is_already_ticked` | 顺序语义 = 追加到末尾 |
| `test_the_event_group_replaces_other_selections` | 活动组互斥 = 只剩 survivor，别组勾选框跟着灭 |
| `test_group_numbers_reflect_panel_order` | 序号按面板顺序，跨过第 10 位 |
| `test_group_toggle_is_refused_while_running` | 运行期间拒绝，且**把勾撤回去** |
| `test_task_panel_columns_are_derived_from_the_screen_budget` | 列数仍由屏幕预算算；**第一组标题坐在第 0 行**（卡头已删），逐组行号按「标题1行 + 格子折行」独立推算 |
