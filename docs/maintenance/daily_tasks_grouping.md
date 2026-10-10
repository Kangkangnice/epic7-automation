# 「每日任务」面板的三分组与批量勾选（2026-10-08）

> 用户诉求（原话）：「就是把这个界面分成这三种，其他的不需要改动啊。然后还有一点
> 就是那个新增一个小按钮，就是说可以批量的全选和可以选择全选（不包括单独的活动）
> 和那个批量的取消选择。」
>
> 三种 = **日常 / 赛季 / 活动**。

## 1. 分组的判据

分组依据是**「这条路线的内容会不会轮换 / 是不是限时」**，不是路线本身的功能：

| 分组 | 判据 | 成员 |
| --- | --- | --- |
| **日常** | **常驻**，天天都在、与赛季无关 | 英雄合成 / 主线 / 竞技场 / 狗粮 / 刷书签 / 世界首领战 / 骑士团捐赠 / 迷宫强化石 / 圣域收菜 / 社区签到 |
| **赛季** | **按赛季轮换**，赛季一换内容与阶段就变 | 远征 / **月塔** |
| **活动** | **限时活动**，随活动开合出现 / 消失 | 活动（survivor） |

归属是用户逐条认的，不是按名字猜的。两个容易搞错的地方：

- **狗粮算日常**（用户明确）—— 虽然叫「特别的时间之书 Episode 3-7」，但它是常驻刷图。
- **月塔算赛季** —— 用户原话「之前我们是不是做过远征……它其实这些都属于赛季，
  就它有时候会轮换」。

## 2. 常量住在哪

全部在 `desktop/catalog.py`：

```
GROUP_DAILY / GROUP_SEASON / GROUP_EVENT   # 三个中文名
GROUPS                                     # 展示顺序（从上到下）
EXCLUDED_FROM_SELECT_ALL                   # 「全选（不含活动）」跳过的组
RouteInfo.group                            # 每条路线挂在哪一组
grouped_routes()                           # ((组名, 该组路线), ...)，滤掉空组
selectable_modes(include_events=...)       # 批量勾选的名单，按**面板顺序**
```

⚠️ **三个名字是「界面分组」，不是路线属性**：

- 它们**不进 `ModeSpec`**。`ModeSpec` 装的是路线的本质属性（模式名 / 次数 /
  状态机 / 导航计划）；「日常还是赛季」是给用户看的话术，换个客户端可能就变。
- 「日常」这个**分组名**与模块 `daily_tasks` **不是一回事**。后者是「把几条串起来
  一次跑完」的**编排**，它读的清单按勾选先后走，与分组无关。
- 分组的**顺序**由 `GROUPS` 定死，**不从 `ROUTES` 的书写顺序派生** —— 否则往
  `ROUTES` 里插一条新路线就可能把面板顺序搅乱。`ROUTES` 的顺序仍然是「组内顺序」。

## 3. 界面怎么渲染（`desktop/app.py`）

- 卡头右端三颗小按钮：**全选 / 全选（不含活动）/ 取消全选**。
  放在**卡头**而不是各组标题旁，是因为「全选（不含活动）」天然是**跨组**动作，
  挂在任何一组下面都名不副实。
- 路线**扁平**排在同一个 grid 上（不是每组套一个子 Frame）。这样各组的格子共用
  同一套列宽，三个分组左边缘对齐，纵向看是一张表；套子 Frame 的话每组各算各的
  列宽，组和组之间会错开。每组的标题占 1 行，格子从下一行起按 `columns` 折行。
- 界面层**不写路线名单、不写中文字面量** —— 只调 `grouped_routes()` 拿到什么画
  什么，插一条新路线只改 `catalog.py`。

## 4. 批量勾选的语义

逻辑在 `DesktopController.select_all` / `clear_selection`。

**为什么是「整体替换」而不是逐条调 `toggle`？**

逐条调有两个毛病：

1. 每点一条都要跑一遍 `standalone_only` 的互斥逻辑，勾到「活动」时前面已勾好的
   会被清空，最终结果取决于**遍历顺序**（纯属巧合）。
2. 顺序由遍历决定，而「**勾选先后就是执行顺序**」是用户 2026-09-29 拍板的语义
   —— 批量勾完的顺序必须是**面板上看到的顺序**。

⇒ 所以 `selectable_modes()` 按 `grouped_routes()` 摊平返回，直接替换整个
`selection`，不逐条走 `toggle`。

⚠️ **按面板顺序而不是 `ROUTES` 书写顺序**，这一点有实际差别：分组之后
`expedition`（赛季）排到了 `fodder`（日常）**前面**，两者不再一致。若用书写顺序，
界面上写着「11. 远征」而实际第 4 位就跑了远征 —— 序号是骗人的。
`tests/test_desktop_catalog.py::test_select_all_covers_every_route` 钉住这件事。

### 互斥仍然成立

`survivor`（活动）的 `needs_navigation=False` ⇒ `RouteInfo.standalone_only`
为真，**只能单独跑**（起点得由人先把游戏停在选卡页，串在别的路线后面时那个
前置条件早被破坏）。所以：

- 「全选（不含活动）」把它排除在外 —— 这是最常用的那颗。
- 「全选」把它一起勾上时，结果就是**只勾活动这一条**。这不是特例，是
  `toggle` 里那条互斥规则在批量语境下的自然结论（活动组**只有一条**）。

## 5. 踩过的坑

### 5.1 序号圈码用尽（真 bug，被新测试当场抓出）

`_CIRCLED` 只有 10 个圈码（①②…⑩），而「全选（不含活动）」一次能勾 **12 条**。

```
IndexError: string index out of range
  app.py: prefix = self._CIRCLED[self.controller.selection.index(mode)]
```

**用户一点那颗按钮，整个界面就崩。** 修法：加 `_position_prefix(index)` 统一出口
—— 头 10 位圈码，之后用 `11.` `12.`。序号的**语义**是「你排第几」，不是
「必须画个圈」，所以超出的部分退回阿拉伯数字是合理的，不该往 `_CIRCLED` 里硬塞字符。

`test_bulk_selection_numbers_reflect_panel_order` 钉住它，且断言里**独立**算出
期望前缀（不调 `_position_prefix`），并显式要求选中数 > 10 —— 否则这条测试
永远碰不到那个坎。

### 5.2 「视觉顺序」不能靠遍历

`_task_panel_descendants()` 是深度不限的遍历，**兄弟控件的先后取决于遍历策略**
（用栈是后进先出 ⇒ 拿到的顺序是反的）。测试里要「从上到下」就必须按
`grid_info()["row"]` 排序，不能拿遍历顺序当视觉顺序。

## 6. 护栏一览

| 测试 | 钉住什么 |
| --- | --- |
| `test_groups_are_defined_in_display_order` | 三个中文名与展示顺序（**写死**，不读实现） |
| `test_group_membership_is_what_the_user_asked_for` | 逐条归属真值表 |
| `test_grouped_routes_returns_display_order_and_skips_empty_groups` | 不漏不重；组内仍按书写顺序 |
| `test_select_all_without_events_skips_exactly_the_event_group` | 「不含活动」= 全量 − 活动组（独立算出，不用 `EXCLUDED_FROM_SELECT_ALL` 自证） |
| `test_task_panel_renders_a_titled_section_per_group` | 三个标题按行号递增，且各自排在自己那组路线**之前** |
| `test_bulk_buttons_exist_with_the_three_labels` | 三颗按钮存在 |
| `test_select_all_ticks_every_route_in_panel_order` | 「全选」的互斥结论 = 只勾 survivor |
| `test_select_all_without_events_ticks_the_daily_and_season_routes` | 12 条、顺序 = 面板顺序、survivor 不在 |
| `test_bulk_clear_untickes_everything` | 取消全选后勾选、各 checkbox、底部说明全清 |
| `test_bulk_selection_numbers_reflect_panel_order` | 序号按面板顺序，跨过第 10 位 |
| `test_bulk_selection_is_refused_while_running` | 运行期间三个入口都拒（各弹一次错） |
| `test_task_panel_columns_are_derived_from_the_screen_budget` | 列数仍由屏幕预算算；**标题占行**已计入行号 |
