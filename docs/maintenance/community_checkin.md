# 社区签到（`community`）—— 维护手册

> 改这条路线之前先看这一份。**判据的实测依据都写在代码注释里**  
> （`community.py` / `community_pages.py` / `community_numbers.py` 的模块 docstring 是主力），  
> 这份文档只负责「它特殊在哪、改哪里、缺口在哪、怎么验」。
>
> ⚠️ 这条路线是**第一条横跨两种屏幕方向**的路线（横屏走大厅、竖屏走社区 H5），  
> 也是第一条**竖屏 adb 链路**。它与横屏那套（`navigation.py` / `Epic7Window`）是  
> **两套独立坐标口径**，不要互相套用。

## 这条路线要干什么（2026-10-06 新增）

每天一次，进游戏内的社区做签到 + 三条每日任务，再把积分按固定清单兑换掉：

```
大厅
  └ 左侧竖排菜单的「活动」入口
游戏内活动页
  └ 右下角「更多精彩活动」（游戏**记得**上次选没选它）
网页活动列表（横屏，网页）
  └ 右上角「游戏社区」入口            ← 点下去，模拟器整块转成竖屏
社区 H5（竖屏 1080x1920，android 网页）
  ├ 首页信息流：签到
  ├ 底栏「我的」→ 我的任务：浏览帖子 / 分享帖子（各一次）
  │     ⚠️ **2026-10-11 起「点赞帖子」已摘掉**（见下面那节）
  └ 兑换中心：按固定清单兑换
       行动力*30           20 积分 / 每日限购 2
       下级万能装备强化石   50 积分 / 每日限购 1
       下级万能饰品强化石   50 积分 / 每日限购 1
       （金币卡 15 积分的**刻意不兑**）
  └ 右上角 X 退出社区                 ← 再转回横屏
大厅（收工）
```

用户原话（2026-10-06）：「这个社区还要签到……三条任务分别是浏览帖子、点赞帖子、  
分享帖子」。兑换那条被当场纠正过一次：**不是每件各兑一次，而是兑到「每日限购」的上限**  
——「行动力 1/2」表示还差一次，要兑到 2/2 才算完（见 `REDEMPTION_PLAN` 的  
`daily_limit` 与 `plan_redeem()`）。

## ⚠️⚠️ 2026-10-11：点赞任务摘掉 —— 它会**死循环**（用户拍板）

### 现场

用户真机实跑，08:45~08:47 卡在一个循环里，手动按停（日志里 `start_task`
（点「去完成」）在这段出现 **26 次**）：

```
任务「点赞帖子」：这一屏没有还没点过的 👍，往下滑一屏再找（第 1/3 次）
…（第 2/3 次）…（第 3/3 次）
任务「点赞帖子」连滑 3 屏都没找到一颗还没点过的 👍，本遍作废
→ 经兑换中心回我的任务 → 点「去完成」→ 又是这三屏 → 本遍作废 → …
```

### 根因（用户自己指出来的，是对的）

**点赞状态是游戏服务端永久记住的。** 我们点过的帖子，那颗 👍 会**永远变成实心**
（已点赞）；而判据 `pages.locate_card_like` 只认「**空心** = 还没点过」。
⇒ **翻得越久、能点的越少**，最后滑遍全屏也找不到一颗 ⇒ 那一遍必然作废。

⚠️ 这跟「尺子错了」「账本错了」都不一样：**判据和账本都是对的，是这个任务本身
随时间不可再完成**（同一篇帖子不能赞两次）。

### 处置（用户拍板「只保留分享+浏览」）

| 改了什么 | 说明 |
| --- | --- |
| `pages.TASK_ROWS` | 摘掉 `like` 行 ⇒ 只读「浏览 / 分享」两行 |
| `TASK_SCRIPT` / `TASK_ROUND_TIMES` | 摘掉 `"like"` 项 |
| 点赞的**代码与机制** | **一律保留**（用户拍板）：`_LIKE_ONE` / `LIKE_RESWIPE_LIMIT` / `locate_card_like` / `_VERIFY_LIKE_ON` 全在 |
| 点赞的护栏 | 用 `unittest.mock.patch.dict` 临时把 `"like"` 注册回 `TASK_SCRIPT` 再跑 ⇒ **机制照旧被罩住**，生产代码零改动 |
| 模板 / 夹具 | `card_like_off.png` 与三张信息流夹具**保留**（不删） |

⇒ **要真正恢复点赞，把 `TASK_ROWS` 与 `TASK_SCRIPT` 那两行加回去即可**，
测试不用改（它自己会 `patch.dict`）。

### ⚠️ 副作用：少拿一份积分

兑换清单总共要 **140 积分**（20×2 + 50 + 50）。少做一条任务就少一份积分，
**「够不够」目前没有实测数据**（日志里没有兑换决策那帧的余额读数）。
⚠️ 但**不会卡死**：`plan_redeem()` 余额不够时返回 `insufficient` 并如实报
「余额 X 不够换 Y」，属正常收手。**下次实跑要看一眼日志里兑换那几行。**

### ⚠️ 顺带发现（**没修**，需要单独决策）

「一个任务连着 3 轮做不成 ⇒ 跳过它」这道闸，**在本次现场里没拦住循环**：
日志明明判了「本遍作废」，回去对账后却又重排同一任务。
⇒ 怀疑「已浪费几轮」的账本在**回「我的任务」对账时被重置**，
所以永远达不到 `TASK_ATTEMPT_LIMIT`。**这是独立于点赞的缺陷**
（分享/浏览哪天做不成也会撞上），但**本轮没动**（用户只要求先摘掉点赞）。


## ⚠️ 先知道这一件事：这条路线的每个坐标属于哪条通道

| 段                 | 通道                                      | 画面口径                              | 坐标是不是点击坐标    |
| ----------------- | --------------------------------------- | --------------------------------- | ------------ |
| 大厅 → 网页活动列表       | 横屏 `Epic7Window`                        | **1982x1132**（兼容画布；客户区 1920x1080） | 不是，要窗口局部换算   |
| 社区 H5（点进「游戏社区」之后） | 竖屏 `core/portrait.PortraitChannel`（adb） | **1080x1920**                     | ✅ **就是**点击坐标 |

两根轴上的东西**绝不能混**。混了不会报错，只会静默点空：  
`WEB_COMMUNITY_ENTRY = (1740, 260)` 是**横屏**坐标（它是 `navigation` 里  
`web_community` 锚点 `(1540,180,400,160)` 的中心），而 `FEED_CLOSE = (937, 92)` 是  
**竖屏**坐标。`community.py` 的模块头把这条写在了 `WEB_COMMUNITY_ENTRY` 上方。

### ⚠️ 采集口径：竖屏帧有两套尺寸，别混着比

采到的帧里有两种尺寸，**不是同一个坐标系**：

- `adb screencap` 出来的 **1080x1920** —— 这才是竖屏判据/读数认的口径，  
  `is_portrait_frame()` 只认**严格等于**这个尺寸的帧；
- 雷电**窗口客户区**截图 **1103x1899**（带雷电自己的边框）—— 例如  
  `tests/fixtures/epic7_community/tasks_fresh_live_20261006.png`。

⇒ 拿 1103x1899 的帧去对竖屏锚点量分数**没有意义**（memory：「比几何前先确认两样本  
同口径」）。这类帧只用来做读数（数字）的样本。`test_community_pages.py` 里有一条  
`test_all_page_fixtures_are_at_the_portrait_canvas` 把这条口径钉住了。

## 页面判据（`community_pages.py`）

### 社区 H5 是「叠层」的 —— 这是本路线判据的核心难点

实测（2026-10-06 真机帧池）兑换流程是叠上去的：

```
商品详情（栈根）
  └─ 订单确认页：几乎盖住整屏，只露底部一条**被压暗**的上一页
       └─ 兑换成功弹窗：x 260..820, y 731..997
```

**下层元素在上层依然可见（只是压暗），而 `TM_CCOEFF_NORMED` 对整体压暗几乎免疫**  
（项目里早有记录「×0.45 只掉到 0.9987」）。真机实测：

| 判据          | 来源页分数  | 在下层暴露处                    |
| ----------- | ------ | ------------------------- |
| 底部「立即兑换」按钮  | 1.0000 | **0.9587**（订单确认页 / 成功弹窗页） |
| 弹窗内「确认兑换」按钮 | 1.0000 | **1.0000**（成功弹窗页，它就在下面）   |

⇒ **「立即兑换 / 确认兑换」这类只差两个字的同形按钮，怎么调阈值都落在死区，  
不能当判据。** 正确做法是**只取「上层会盖住」的那块区域**：

- `order_confirm` —— 取成功弹窗**未来会出现**的位置（那里是**固定免责提示文字**）；
- `redeem_done` —— 取弹窗本体。

两者**同一块坐标、内容完全不同**，所以天然互斥（来源帧 1.0000、对手 0.23~0.41）。

### 锚点表（区域是竖屏 1080x1920 坐标，模板只在同一块区域里搜）

| 锚点                | 区域 (x,y,w,h)       | 表达什么                | 备注                  |
| ----------------- | ------------------ | ------------------- | ------------------- |
| `feed_home`       | (125,1738,65,100)  | 底栏「首页」页签**激活态**（青绿） | 栈根兜底用，见下            |
| `exchange_center` | (410,96,260,68)    | 居中标题「兑换中心」          | 也是商品详情的栈根判据         |
| `exchange_empty`  | (360,1220,320,70)  | 「暂时还没有商品哦」          | 空列表态；**必须比兑换中心更优先** |
| `tasks_page`      | (390,96,190,68)    | 居中标题「我的任务」          |                     |
| `item_detail`     | (140,1730,800,110) | 底部「立即兑换」（叠层那一条）     | 栈根兜底用               |
| `order_confirm`   | (270,745,540,240)  | 订单确认页·固定免责提示        | 与 `redeem_done` 同坐标 |
| `redeem_done`     | (265,736,550,256)  | 「兑换成功」弹窗本体          |                     |
| `share_sheet`     | (330,1570,420,220) | 分享面板「复制链接」          |                     |
| `post_detail`     | (560,1790,440,90)  | 帖子底部操作栏             |                     |
| `network_error`   | (280,880,520,260)  | 「网络连接异常，下拉刷新」       | 全局态，优先级最高           |

阈值统一 **0.82**（`THRESHOLD`）：9 个锚点在来源帧上都是 1.0000、对手 ≤0.41，  
0.82 落在很宽的空档里。全库 105 张竖屏帧扫下来**零可疑命中**  
（明细见 `runtime_logs/_make_community_anchors.py` 的报告与  
`docs/manual_review/community/_anchors_report.txt`）。

### ✅ 可选用的，与 ❌ 不许当判据的

- ❌ **底栏四格导航**（首页 / 攻略 / 投稿 / 我的）与**左上角放大镜**都是**共享控件**  
  ——放大镜实测 6 页里 5 页**逐像素完全相同**。拿它们当页面判据必然误判。
- ❌ 底部「立即兑换 / 确认兑换」按钮：同形叠层，见上。
- ✅ 能用的都是**该页专有**且**每次一模一样**的东西：居中标题、免责提示、弹窗本体、  
  空列表文案、网络异常文案。

### 两个「栈根页」没有专有正向特征 ⇒ 只能做兜底态

- `feed_home`（首页列表）：底栏四格与放大镜都是共享控件；底栏「首页」的青绿激活态  
  判的是「在首页这个 Tab 的导航栈里」，帖子详情页底下那个页签**也还在**。
- `item_detail`（商品详情）：被订单确认页盖得只剩底部那条压暗的按钮。

⇒ 这两页**不设正向锚点**，由 `resolve_stack_root()` 用「栈根判据命中 + 该栈盖层一个都  
没命中」推出来（`PageJudgement.fallback=True`，日志里会写「兜底」）。  
**不要**为了「有个正向判据」去调阈值硬凑 —— 那正是 2026-10-05 竞技场入口事故的形状。

### 叠层优先级 `LAYER_ORDER`：判「当前页」**先看层序、再看分数**

只按分数挑是错的：下层页面在上层被压暗后照样能拿高分（见叠层那张表）。  
数字越小越靠上：`network_error`(0) > `redeem_done`(1) > `order_confirm`(2) >  
`share_sheet`(3) > `post_detail`(4) > `exchange_empty`(5) > 兑换中心/任务/首页(6) >  
`item_detail`(7)。

⚠️ `exchange_empty` 必须排在 `exchange_center` **上面**：它是兑换中心的**子状态**  
（标题还在），排下面就会被判成「正常兑换中心」，路线接着去点**不存在的商品卡**。

## 数字读数（`community_numbers.py`）

### 为什么不用 OCR

项目只依赖 6 个包（numpy / opencv / Pillow / PyAutoGUI / PyGetWindow / psutil），  
不引 OCR。社区页的数字来自**固定字体的网页文本**，字形模板足够，而且**离线可复核**  
（模板是文件，变了看得见）。理由与 `knights_support_digits.py` 同源。

### 用户 2026-10-06 二次拍板：三处数字**统一走字形读法**

| 位置               | 取值         | 读法                           |
| ---------------- | ---------- | ---------------------------- |
| 积分余额             | 开放（任何非负整数） | 字形逐字（`read_digits`）          |
| 任务进度 `x/3` `x/1` | 封闭         | 字形逐字（`read_pair`，认第 1、3 个组件） |
| 每日限购 `x/y`       | 封闭         | 同上                           |

**为什么最后没用「整串模板」**（原方案是用整串读 `x/y`，实测后改掉）：

整串模板是「把 `3/3` 整串裁一张原尺寸小图，在区域里逐像素比」。问题是社区页本质是  
**网页**，同一串字在不同帧里会因排版位置的**半像素**差异被重新栅格化 —— 实测同一串  
`3/3` 在 A 帧 0.97~~1.00、在 B 帧只有 0.74~~0.80，**跨帧整串 11/13 挂 2 个**；  
而字形读法先按**高度归一化**再比，天然免疫，同一批样本 **19/19 全中**。

⇒ 整串那套（`read_string` / `load_string_templates` + `templates/community/strings/`）  
**保留但不在生产路径上**。`strings/` 目录里的模板**不是判据**，别当判据用。

### 三个必须记住的实现细节（踩过）

1. **字形画布高度必须 ≥ 源字高**（`GLYPH_CANVAS = (22, 30)`）。社区数字最大 26px；  
   早期用 24 高（=**下采样**）时跨帧只有 0.60~0.70，改成 30 高（=**上采样**）后  
   同批样本全部 ≥0.73。下采样会把笔画宽度的亚像素差异放大成整像素差异。
2. **缩放用 `INTER_AREA`，不是 `INTER_NEAREST`**（骑士团那套用的是 NEAREST，**别照抄**）。  
   这里是上采样，最近邻会把笔画边缘的半像素差放大成整像素台阶；换 `INTER_AREA` 后  
   同批样本 0.60~~0.66 → 0.73~~0.82。
3. **连通域筛子要挡住「每日限购」四个汉字**（宽上限 30）与**括号**（高上限 34，  
   放进来会让「切出 3 个」变「切出 5 个」，读数直接弃权）。

### 三态，绝不猜

读不出就返回 `None`（"不知道"），**不返回猜的值**。理由同骑士团：「认错比认不出更糟」  
—— 认错的数字会直接变成业务动作（**兑错东西 / 少兑一件 / 重复兑换**），  
认不出只是这一轮不报数。字模缺失时 `load_digit_glyphs()` **直接抛**：字模是判据的一部分，  
缺了会让「积分够不够」安静地失效（2026-10-03 判据静默降级的同款教训）。

## 双通道接入（`attach_dual_channel` / `ChannelSwitch`）—— 这是本路线最不常规的一处

### 为什么换掉 `Runtime` 的四个「原始通道」，而不是在外面垫一层壳

`Runtime.capture / click / swipe / back` 各自还做三件事：查停止请求（P 键 / 界面上的  
stop 文件）、写运行日志、取图那条再叠一层全局弹窗判据（`set_capture_guard`）。  
在外面垫壳就必须把这些**再实现一遍** —— 那就是「同一个行为两份实现」，以后 `Runtime`  
改了这一份不会跟着改（项目里因为「同一事实抄两处」漂移过多次）。  
**所以只替换最底下的四个通道（`_capture/_click/_swipe/_back`），上面每一层照旧。**

### 代价与四条防线

它要写 `Runtime` 的四个**私有**属性，所以配了四条防线：

1. 先 `hasattr` 探一遍 —— 属性被改名会在**开跑前**当场报错，不会静默失效；
2. 只替换这四个，**不新增也不删除**任何属性；
3. **干跑完全不接**（`capture` 直接走原实现）：干跑不该碰 adb，也不该让模拟器转屏；
4. 每个替换点先把原实现**存下来**，横屏段原样转发。

⚠️ 只适用于**雷电模拟器后端**（`PortraitChannel` 走 adb）。PC 后端由 `CommunityRunner`  
在装配前**拦下**（不拦的后果是**静默点错客户端**：`PortraitChannel` 自己会去找雷电窗口，  
机器上恰好在跑雷电它就去操作那一个 —— 画面看着没问题，点的是别人）。

### 方向由「路线自己的意图」决定，不是每帧去问窗口

问一次方向要跑 `ldconsole list2`（约 100ms 的子进程），每帧都问等于给主循环平白加开销。  
所以只在**换向的那几秒**里轮询：状态机点了「游戏社区」就 `expect("portrait")`，  
点了「退出社区」/「关社区重进」就 `expect("landscape")`；轮询看到窗口真转过去了就**锁定**，  
之后一帧都不再问（测试用 `switch.probes` 钉「锁定后不再问」）。

⚠️ **换向途中「还没转过去」时不能回横屏**：转屏是**带动画**的，窗口渲染尺寸会在中途变化，  
横屏那套 `capture()` 会直接抛「LDPlayer render size changed」。所以「已点入口、还没转过去」  
这段时间照样交给竖屏通道 —— 它自己会等（`wait_for_portrait`，默认最长 20 秒）。  
等不到就说明那一下**没点中**，`attach_dual_channel` 退回横屏让状态机**重点一次**  
（`_ENTRY_RETRY_SECONDS = 25s` **必须比那段等待更宽**，否则会在转屏动画没走完时又点一次，  
那时的横屏坐标已经不可信了）。

## ⚠️ 收官次序：**关在竖屏，收工在横屏**（最容易写错的地方）

社区页在竖屏，而 `main` 的「异常也回家」与「正常回大厅」都拿**横屏**通道去取图  
（`Epic7Window.capture`）。⇒ **人还在竖屏时绝不能抛任何结论、也绝不能收工**，  
否则取图直接抛「render size changed」，一个正常结论会变成看不懂的失败，  
而且模拟器被留在竖屏（下一个任务连大厅都回不去）。

于是收敛顺序被固定成三段，**三段必须在三个不同的帧上**：

```
信息流/我的任务  ──点「退出社区」X──▶  CLOSING（等转屏）
CLOSING 且仍是竖屏 ──不出手，等──▶
CLOSING 且已成横屏 ──▶ _finish()（正常完成）
                   └─▶ 或 stop_reason 非空时 raise RedeemBudgetExhausted（积分不足）
```

三条硬规矩：

1. **`CLOSING` 不判页面。** 点完 X 之后画面在消失、窗口在旋转，拿半截画面去认锚点只会  
   认出一堆 `unknown` 并抛「认不出」。`next_action()` 里 **`CLOSING` 分支排在  
   「是不是竖屏」的页面判定之前**，只看方向。
2. **结论只出现在横屏那一帧**（`_on_landscape` / `_finish_closing`）。  
   从「决定收工」到「真的收工」中间**一定要有一次点击**（`close_community`）与**一次等转屏**。
3. **动作与结论不许同帧。** 主循环次序是「先发动作、再看轮次有没有推进」——两者同帧时  
   动作会被**跳过**，表现是「明明该点的那一下没点，整条路线却报完成」。  
   所以 `_on_tasks` 的收尾态返回 `leave_tasks`（动作），`_on_feed` 返回 `close_community`  
   （动作），真 `_finish()` 只在 `_on_landscape`/`_finish_closing` 里调（**那一帧没有动作**）。  
   `_finish()` 的 docstring 把这条写死了。

### 积分不够 = **正常业务退出**（退出码 2），不是故障

`RedeemBudgetExhausted` **必须继承 `ResourceExhausted`**：主循环靠「是不是  
`ResourceExhausted`」决定退出码。挂在 `RuntimeError` 下会被当成「画面认不出」去等超时，  
最后报**退出码 1**（故障）—— 明明只是没分了。⚠️ 这个 raise 也**只在横屏那一帧**发生，  
所以 `_on_exchange_center` 的 `insufficient` 分支只是**记下 `stop_reason` 并退回信息流**，  
不直接抛（直接抛就违反了上面第 2 条）。

### 失败路径的兜底：`_close_out` / `_leave_portrait_if_needed`

异常路径（缺数据 / 认不出 / blocked）也会走 `_close_out`，那时人可能还停在竖屏。  
所以 `_close_out` **先** `_leave_portrait_if_needed()`（⚠️ 2026-10-09 起改成**挨个试三颗 ⊗**——
信息流 `(937,92)` / 兑换中心 `(989,123)` / H5 死掉那屏 `(1000,78)`，三颗外径 33/44/48 **互不相等**、
不是同一颗挪位置；谁把窗口转回横屏算谁赢，每颗最多等 5 秒。只点信息流那一颗在别的页面上**等于点空**。  
再补两下返回键），**再**交给基类做「回首页」。  
`CommunityRunner.run()` 外面还包了一层 `try/finally`：非 `ManualStop` 的异常也兜一次。  
两处都是**幂等**的、都**绝不外抛**（关不掉就记一笔，让基类那步照常失败并留下原因）。

⚠️ `ManualStop`（用户按 P）**一个字都不动游戏** ⇒ 那条路径上兜底收尾**不跑**。

### ⚠️⚠️ 终点契约：这条路的终点是**首页（大厅）**，不是「退出社区」

用户 2026-10-09 补充：「这条路线它的终点有点特殊，它一定要回到首页，因为不然的话，
它很多按键都没有掉了」—— `web_activity_list`（网页活动列表）上**没有大厅那套按钮**，
停在那儿下一个任务接不上。所以**「退出社区」只是中途**，收尾还有一棒：通用回家流程。

完整链路四棒，**缺一棒都到不了终点**：

```
状态机 DONE ──▶ 基类主循环 _close_out() ──▶ CommunityRunner._close_out()
                                              （退社区 + 等转回横屏）
                                              └─▶ super()._close_out()
                                                  ──▶ _finish_home()（main 装的钩子）
                                                  ──▶ home_return() ──▶ 大厅
```

最后一棒走的是**兜底按 ESC**（网页活动列表吃 ESC，两次就到大厅）。
2026-10-09 20:01 那次实跑的日志：

```
20:01:40 流程=v2 动作=按ESC 原因=兜底 次数=1/8
20:01:46 流程=v2 动作=按ESC 点击验收=生效 从=web_activity_list 到=activity_web_promo 耗时=0.9秒
20:01:48 流程=v2 动作=按ESC 原因=兜底 次数=2/8
20:01:55 流程=v2 动作=按ESC 点击验收=生效 从=activity_web_promo 到=unknown 耗时=1.8秒
20:01:57 流程=v2 页面=大厅 状态=已确认
20:01:57 模式=community 异常收尾=已回到首页 状态=可以衔接下一个任务
```

⚠️ **两个容易误判的地方**：

1. **收尾失败不改退出码**（回家是「顺手收拾」，任务跑完了就报成功）。
   ⇒ 想知道终点到没到，**只看日志有没有这句**：`收尾=已回到首页 状态=可以衔接下一个任务`。
   只有 `收尾=回首页失败 原因=...` 才说明人没到家（这才需要人工）。
2. **基类在「没装回家钩子」时是静默 `return` 的**（一行日志都没有）⇒ 终点契约会**悄悄失效**。
   所以 `CommunityRunner._close_out()` 里加了一条**出声**的判断：实跑下没装钩子就记
   `收尾=没有可用的「回首页」钩子 影响=退出社区后只会停在网页活动列表（横屏），到不了大厅`。

### 这条契约的护栏（`CommunityEndpointMustBeHomeTests`）

| 断言 | 反向验证（注入 → 必须红） |
| --- | --- |
| `community` 不在 `finish_home.FINISH_HOME_EXEMPT` 里 | 把它塞进豁免名单 ⇒ `test_the_route_is_not_exempt_from_going_home` 红 |
| 真跑一轮（按「积分不够」收）⇒ `_finish_home` **被调到** | 删掉 `_close_out` 里的 `super()._close_out()` ⇒ `test_a_finished_run_walks_all_the_way_home` 红 |

⚠️ 静态那条（`CommunityRunnerTests.test_the_run_loop_is_delegated_to_the_base_class`：
覆写了 `run()` 有没有 `super().run(`）**不能替代**上面第二条 —— 它能拦住「没委托」，
拦不住「委托了、但回家钩子没装 / 被跳过」。

## 两处正常的长等待与等待心跳

这条路线有两段**长得离谱的正常等待**：等转屏（`ENTERING`，给 120 秒）与  
**等兑换结果**（`ORDER_CONFIRM`，给 **150 秒** —— 按钮点完要**实测 3~40 秒**才出结果，  
这期间按钮是禁用态、颜色定位找不到 ⇒ `next_action` 一直返回 `None`）。  
⚠️ 那一档**必须**比 40 秒宽：给 45 秒的话，一次 40 秒的正常等待就会被判成「画面无动作超时」。

这期间**不出手、不打分、不报警**，日志会一直空到超时 —— 2026-10-04 那次就是这么事后  
翻现场帧才知道卡在哪的。所以 `CommunityRunner._stable_next_action()` 在 `super()` 之后  
补一条 **10 秒心跳**（带上「当前页面 + 为什么没出手 + 走哪条通道」），并在判据沉默时  
**留一张现场帧**（`_save_wait_frame`，只留第一张，整段包在 `try/except` 里 ——  
**诊断绝不许打断主循环**）。

⚠️ `_stable_next_action` **必须 `super()` 进去**：结论门槛接在基类里，绕过去等于  
「一帧就能宣布收工 / 一帧认不出就去点屏幕中间」（`modes._base_conclusion_gate_protected`  
会拦下来）。同理 `run()` 只做装配，主循环**委托给基类**。

## 转场契约 / 接力 / 实跑闸门

### 转场契约 `_REQUIRE_TRANSITION_CONTRACT = True`（本项目第六条）

和 knights_donation / world_boss / labyrinth_stone / sanctuary / hero_synthesis 同款：  
每个动作发出前都要通过「`source_page` + 出口验收」的机器校验（含空跑）。  
所以状态机里每个 `CommunityAction` 都带 `source_page` 与 `target_pages` 或  
`in_page_evidence`（`test_every_action_carries_an_exit_check` 钉着这一点）。

### 接力：在 `RESUME_EXEMPT` 里，**必须写明理由**

判据其实够用（活动页三态与网页活动列表都有专有锚点），缺的是**更前一步**：  
这条路线有一半时间在竖屏，而人停在社区里时，开局那一步 `home_return()` 拿的是**横屏**  
通道（`Epic7Window.capture`），竖屏下它会直接抛「render size changed」——**起步就失败**，  
连探针都轮不到跑。⇒ 要争取接力，得先把「起步时若模拟器是竖屏，就先退出社区」放到  
`_enter_mode` **之前** —— 那是 `main.py` 的活，属于另一件事。  
（理由全文见 `modes.RESUME_EXEMPT["community"]`。）

### 实跑闸门：`LIVE_RUN_READY`（**2026-10-06 立项时是 `False`，2026-10-07 翻成 `True`**）

> ⚠️ **本节记的是「闸门为什么存在 + 怎么用」，不是当前取值。**  
> 现在的取值见 `games/epic7/community.py::LIVE_RUN_READY`（= `True`，实跑已放行），  
> 闸门**本身没拆** —— 客户端改版、或哪天要重新验证时，把它翻回 `False` 即可拦住实跑，  
> 干跑照常。


```python
# games/epic7/community.py（立项时）
LIVE_RUN_READY = False
MISSING_LIVE_DATA = ("信息流里三条每日任务的执行坐标（点开第几条帖子 / 卡片上的点赞按钮 / 滚动量），"
                     "以及信息流「签到」未完成态的长相")
```

`modes._preflight_community` 在**调用时**从 `community` 的**模块属性**上读这个标志  
（不是 `from ... import LIVE_RUN_READY` 在 import 期绑一份 —— 绑了之后测试  
`patch.object(community, "LIVE_RUN_READY", True)` 就拦不住它，闸门会**悄悄退化成空转**，  
这是刷书签那道闸门踩过的坑）。

**为什么这条路线当初要比别人多一道闸门**：它的第一阶段（三条每日任务）**根本写不出来**  
—— 信息流里「点开第几条帖子 / 点赞按钮在哪 / 滚多远」一个坐标都没量过，  
「签到未完成」那一态也没有样本。缺数据时状态机会明确抛 `CommunityDataMissing`  
（不猜、不硬点），所以如实跑，用户得到的是一次**必然失败**的运行，而失败原因看起来像  
程序坏了。理由与「PC 后端被收起来」同源。（2026-10-07 真机采齐，这些数据现在都有了；  
闸门留着当「重新验证」的开关。）

## 登记在哪几处

| 处         | 文件                                              | 内容                                                                                                                                                            |
| --------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ① 模式注册表   | `games/epic7/modes.py::MODE_SPECS["community"]` | `label` / `default_state=web_entry` / `states`（**不含 `DONE`**）/ `build_machine` / `runner_type` / `cycles_editable=False` / `preflight` / 3 步 `NavigationPlan` |
| ② 桌面助手目录  | `desktop/catalog.py::ROUTES`                    | `RouteInfo("community", "实验功能", …)`，分类「实验功能」                                                                                                                  |
| ③ 每日任务    | `games/epic7/daily_tasks.py::DAILY_TASKS`       | **刻意不在默认清单里**（否则每次 `--daily` 都必然 ✗）；judgement 写在 `DAILY_TASKS` 上方的注释里                                                                                         |
| ④ 本地门禁路线表 | `tools/check.py::ROUTE_KEYWORDS`                | `"community"` / `"community_pages"` / `"community_numbers"` 三个键（按**文件 stem** 匹配）                                                                              |
| ⑤ 用户文档    | `README.md` 的路线列表                               | 一句话说明（跑法 + ⚠️「一天只能点一次，别当冒烟测试反复跑」）；另有两处写死路线条数的地方（首段实验功能清单、桌面界面那段的「十二条路线」）也要跟着改                                                                                 |
| ⑥ 转场契约登记表 | `docs/TRANSITION_CONTRACTS.md` §路线判据现状登记        | 一行（判据载体 / 进入 / 出去 / 缺口），见上表                                                                                                                                   |
| ⑦ 接力覆盖文档  | `docs/RESUME_COVERAGE.md`                       | 覆盖矩阵一行 + 「社区签到 — 0 / 13」小节（本路线在 `RESUME_EXEMPT` 里，接力那半**只登记不实现**）                                                                                             |

⚠️ **⑤⑥⑦ 这三处（尤其 ⑥⑦ 两份文档）只有跑全量门槛才会红** —— 针对性测试不查它们。  
2026-10-07 就踩过：代码四处登记齐了、单测全绿，全量却挂两条，全是文档登记表没跟上。

`route_module_names()`（`public_flow_verification.py`）从 `MODE_SPECS[*].runner_type.__module__`  
**推导**路线模块清单，不再硬编码 —— 这样新路线漏登记会在 import 期被反向守卫抓到，  
而不是把新路线误判成「带动作但没登记」。`RESUME_EXEMPT` / `TRANSITION_EXEMPT` /  
`CONCLUSION_GATE_DECLARATION` 这些**半表**（必须带理由）在模块加载时自查。

## 改哪里

| 想改的东西                      | 文件                                                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 竖屏页面判据、区域、层序、任务行搜索带        | `games/epic7/community_pages.py`                                                                                               |
| 数字读数（字模、画布、筛子、阈值）          | `games/epic7/community_numbers.py`                                                                                             |
| 竖屏状态机、动作、固定兑换清单、双通道、Runner | `games/epic7/community.py`                                                                                                     |
| 竖屏链路本体（adb 截图/点击/转屏检测）     | `core/portrait.py`                                                                                                             |
| 横屏那四个导航锚点 + 活动页三态          | `games/epic7/navigation.py`（`_REGIONS` / `observe()`）；锚点图在 `templates/navigation/`                                             |
| **发送层**（滑动换发 / 换向取图兜底） | `games/epic7/runner_base.py` 的两个钩子（`_perform_action` / `_capture_frame`）+ `community.py` 的覆写。⚠️ 共享模块，改了要跑全量 |
| 固定坐标点击（光球按钮那一步） | `games/epic7/navigation_plan.py::NavigationStep.fixed_point`；取值声明在 `modes.py` |
| 导航链与接力白名单                  | **不在 `navigation.py`**：链条声明在 `modes.py::MODE_SPECS["community"].navigation_plan`（数据）                                           |
| 模板                         | `templates/community/`（`pages/` 判页 12 + `digits/` 10 + `strings/` 备用 8）与 `templates/navigation/` 4 张                           |
| 测试                         | `tests/test_community.py` / `test_community_pages.py` / `test_community_numbers.py`；夹具 `tests/fixtures/epic7_community/`（12 张） |

判据/读数的生成与复核脚本（`runtime_logs/`，gitignore 的，需要时重建）：  
`_make_community_anchors.py`（判页锚点 + 全库扫描报告）、`_make_community_digits.py`、  
`_tune_community_numbers.py`、`_probe_community_numbers.py`、  
`_sheets_community_frames.py`（把帧拼成索引图看多样性）。  
人工复核产物在 `docs/manual_review/community/`。

## 2026-10-07 晚复盘：三个 P0（已修，每条都配了反向验证过的护栏）

用户放测后一天跑了约 10 次，**只有一次真的进了社区，且那次最后也失败收工**。
三个根因都**不在「动作字段写得对不对」**，全坏在**发送层 / 验收层的接线**上。

### P0-1 滑动被当成点击发出去 ⇒ 点赞任务三遍全废

`TASK_SCRIPT["like"]` 第一步是 `swipe`，动作字段 `swipe_end` 也写对了；但
**主循环只会 `runtime.click`**（`runner_base` 没有滑动通道，别的要滑动的路线都是
自己绕开动作循环去调 `runtime.swipe`）。于是这一下变成「在信息流中部点一下」⇒
**点开一张帖子** ⇒ 下一步要求 `feed_home` 对不上 ⇒ 本遍作废，三遍机会全废。

⇒ 修法：`runner_base` 抽出 `_perform_action()` 钩子（默认就是 `runtime.click`），
`CommunityRunner` 覆写它、认 `swipe_end` 就换发 `runtime.swipe`。
**教训：给动作脚本加「动作类型」时，必须同时确认执行层真有这条通道** ——
否则类型只是个没人读的字符串。

### P0-2 出口验收清单里含了本页 ⇒ 点空了也算完成

`_step_action` 一度把**来源页**也写进 `target_pages`。后果是双向的：
① 含来源页 ⇒ **点空了也判完成**（14:57 白等 33 秒）；
② 不含真目标页 ⇒ **真做成了反判转场超时**（15:00 任务已做成、整条路线却失败）。
成熟路线（sanctuary / hero_synthesis）一律只写「点了之后会到哪」。

⇒ 修法：`target_pages=(step.next_page, "signin_done", "network_error")`。后两个是
**全局异常态**（签到弹窗会迟到、网络异常会把 H5 弄死），必须放行 —— 不放行会卡在
「页面既不是来源也不是目标」的缝里。护栏
`test_the_return_step_does_not_accept_its_own_page_as_an_exit` 钉住它。

### P0-3 换向那 2~3 秒取不到图 ⇒ 秒失败收尾（一天 8 次）

`portrait.capture()` 里「窗口已竖屏、安卓截图尺寸还没跟上」只有约 3 秒余量；
耗尽后抛错，而 `_fallback_to_landscape` 在「窗口已是竖屏」那一支**又调一次
`portrait.capture()`** —— 必然再抛，且这次**没人兜**（发生在 except 块里），
一路冒到主循环取图那一行（**在 `try` 之外**）⇒ 整条路线立刻失败收尾、
把刚打开的社区关掉、一张诊断帧都不留。

⇒ 修法三处：
① `core/portrait.py` 尺寸不对那一支改抛 `OrientationError`（原来抛裸 `RuntimeError`，
   会被上层的 `except OrientationError` 漏过）；
② `attach_dual_channel` 的退路**先问窗口方向**（已是竖屏就不退回）；
③ **兜底落在 `CommunityRunner._capture_frame()`**：按「转场中、只等」有界重试
   （`_CAPTURE_SETTLE_SECONDS=30`，每 5 秒说一句在等什么），等满才允许失败。
   `runner_base` 相应地抽出 `_capture_frame()` 钩子（默认 `runtime.capture()`）。

⚠️ 派生两条硬教训：**兜底分支里再调一次同样的函数等于没兜**；
**主循环取图那一行不在 `try` 里** ⇒ 任何取图异常 = 路线秒失败。

### 顺带修掉的两处

- **`web_activity_gate` 也不能当点击目标**：那颗「前往活动页」按钮上有一颗来回
  滑动的光球，跨天 1.0000→0.7282 ⇒ 过不了 0.82 ⇒ 抛「缺少导航锚点」，**连点都没点**，
  整条路线进不去（13:37 / 14:55 两次）。⇒ `NavigationStep` 新增 `fixed_point`
  （固定坐标点击，画布 1982x1132），导航第 3 步写成 `fixed_point=(1722, 985)`。
  **页面身份这道眼睛没有少**：本步的 `source` / `targets` 验收照旧。
- **`PortraitChannel.set_event_sink` 从没被调用**（竖屏通道「等转屏 / 画幅没跟上」的
  诊断一行都看不到，入口段失败因此事后查不出原因）⇒ `_attach_channels` 把它接到
  `runtime.log` 上。

### 这一轮的护栏（全部**反向验证过**：注入违规立刻变红）

| 护栏 | 钉的「依据」 | 注入的违规 |
| --- | --- | --- |
| `test_a_swipe_step_is_sent_through_the_swipe_channel_not_as_a_click` | 脚本 → 动作 → 真的走 `runtime.swipe`（且不经 click） | `_perform_action` 一律 `super()` |
| `test_a_plain_step_still_goes_out_as_a_click` | 换发只对滑动那几步生效 | —— |
| `test_the_return_step_does_not_accept_its_own_page_as_an_exit` | 出口集合不含来源页、含真目标 | `_step_action` 把 `step.page` 塞回去 |
| `test_capture_waits_out_a_rotation_instead_of_failing_the_route` | 前两帧方向错、第三帧好 ⇒ 正常返回 | `_capture_frame` 不做兜底 |
| `test_capture_fails_only_after_the_settle_budget_is_spent` | 等满 30 秒才失败、且说清在等什么 | 同上 |
| `test_capture_does_not_swallow_a_manual_stop` | 兜底只接 `OrientationError`，不吞 `ManualStop` | 两处 `except` 都放宽成 `Exception` |
| `test_the_gate_step_declares_a_fixed_point_instead_of_hunting_the_glow` | 导航第 3 步声明了 `fixed_point` | `modes.py` 改回 `None` |
| `test_a_fixed_point_step_clicks_it_without_the_template` | 光球滑走那帧不给固定坐标必抛；给了就点得下去 | `navigation.py` 忽略 `fixed_point` |

## 2026-10-07 真机实跑复盘：又抓两个 P0（已修，护栏全部反向验证过）

20:22 / 20:30 / 20:36 / 20:58 连着跑了四遍真机（最后一遍是**修完之后**跑的）。
**只有 20:36 那一遍真正跑到点赞段** —— 也正是那一遍把「一轮 N 次」和「回任务页」
这两处照了出来。

⚠️ **四遍的分布本身就是个结论**：**2 遍败在「活动页 → 网页活动列表」这个网页入口**
（20:22、20:58，现场都是**转圈加载中**、最后判转场失败）、1 遍败在社区 H5 自己报
「网络连接异常」。这一跳是社区线的**必经入口**，弱网下极不稳定 —— **不是本路线的代码问题**。
⚠️ **别靠「加大超时」去治**：20:22 那次转了**两分多钟**最后弹「网络错误」，
那是**加载失败**、不是「慢」，多等只是多等。

剩下那几遍**都败在外部**，与本路线代码无关，记在这里免得下次误判：

- **20:22 网页活动列表加载失败**。诊断帧里页面其实**已经切过去了**
  （右侧「礼包码兑换」在），只是上面盖着「网络错误」、或者还在转圈。
  判据 `web_community`（模板是「游戏社区」四个字，区域 `1540,180,400,160`）
  在三张帧上都只有 **0.45** —— 因为**「游戏社区」入口压根没渲染出来**。
  ⇒ 判据是对的，它正确地拒绝了认页。重试 3 次后按「转场失败」收手。
- **20:30 社区 H5 自己报「网络连接异常，下拉刷新」**。代码里早有
  `CommunityState.BLOCKED` + 「退出去重进」的处理，它正确耗尽重试并 fail-closed
  收手（现场帧 `20261007_203326_943958_timeout_web_entry.png`）。

  ⚠️ 排查网络时**别拿 114.114.114.114 当靶子**：这台机器上它 ping 不通
  （宿主机也通不了），但模拟器 ping 网关（4.2ms）和 `www.baidu.com`（5ms）
  都是通的 —— 照 ICMP 判会得出「模拟器断网」的错误结论。

### P0-4 一轮只做了第 1 次：验收通过就掉头回对账

真机日志（20:36:54 → 20:36:59）：

```
动作=task_like_1  依据=任务「点赞帖子」：现找出来的 👍 在 (904, 760)（空心 = 还没点过），点它
执行点击 坐标=(904, 760)
动作=back_to_tasks_via_exchange  依据=任务「点赞帖子」动作做完，回去核对计数
```

**没有 `task_like_2` / `task_like_3`** —— 而 `TASK_SCRIPT["like"]` 是
`_round_script(_LIKE_ONE, TASK_ROUND_TIMES["like"])` = **3 步**。

根因在 `_await_step_result`：它读到「那颗 👍 变绿了」之后**自己**
`return self._return_to_tasks(...)`。而验收通过只说明**这一步**做成了，
本轮剩下的次数**一次都没做**。

⚠️ 更糟的是它会**互相咬住**：回到「我的任务」时 `task_step = 1 < len(script) = 3`，
`_tasks_action` 判「这一轮没跑完就回来了」⇒ 记一笔、重排一轮 ⇒ 又只点 1 个 ……
直到 `TASK_ATTEMPT_LIMIT` 轮全烧光，而用户看到的是「任务没做成」。

⇒ 改法：验收通过时**返回 `None`**（同时清 `pending_verify`），
`_drive_task` 靠「`pending_verify` 是否还非空」区分「还在等」与「已通过」；
已通过就**落回主流程**接着推下一步，脚本真走完了自会由
`task_step >= len(script)` 回对账。

护栏：`test_a_like_round_keeps_going_after_the_verify_passes`。
构造「验收通过」的办法：把 `like_point` 指到 `feed_cards_mixed` 里
**已经点过**的那颗（y≈780，实心青绿），颜色判据就会认「变绿了」。

### P0-5 回「我的任务」把「兑换」图标的坐标钉死了

紧跟着 P0-4 的第二条（20:36:59）：

```
操作=back_to_tasks_via_exchange 坐标=(438, 538)
20:37:01 结论待确认=UnrecognizedCommunityScreen 详情=社区画面认不出（最高分 0.0000）
20:39:30 已保存诊断 ..._timeout_feed.png
```

诊断帧里是**一张图片查看器**（「平衡性调整公告」大图，上下黑边）——
(438,538) 底下根本不是「兑换」图标，而是**帖子里的图片**。
点下去把图片放大打开了，画面认不出，卡到超时。

为什么：回程路径是**信息流 → 兑换图标 → 兑换中心 → 获取积分卡 → 我的任务**，
而那颗「兑换」图标长在**信息流顶部的四宫格**里（每日签到 / 兑换 / 周年福利 /
战绩查询）。**往下滑过之后整行就滚出视野了** —— 而任务做完时信息流必然滑过
（点赞要下滑找 👍、浏览要点开帖子）。

⇒ 改法和点赞同款：**别假设它在**。新增 `feed_icon_exchange` 模板
（钱袋图标 80x94，**只当存在性判据、不产出点击点**，点击点仍用实测有效的
`FEED_ICON_EXCHANGE = (438, 538)` ⇒ 裁剪不会带动点击点），
搜索带 `FEED_ICON_STRIP`（**2026-10-09 已从 `(360, 380, 160, 300)` 改成
`(330, 200, 200, 500)`**，原因见下节）：
**看不见就「往回滚一屏」再问**，滚满 `FEED_ICON_RESWIPE_LIMIT`（4）屏、**或者画面连着
2 次纹丝不动**（已经滚到顶了）还看不见，就抛 `CommunityDataMissing` 收手 ——
**绝不蒙着点**（那一按不可逆）。
「往回滚」用的是 `FEED_ICON_SCROLL_*`（**2026-10-10 起**起点 `(60,360)` → 终点
`(60,1750)`，单次约 1390px），和 `FEED_TASK_SCROLL_*`「往下看」的方向**正好相反**。
起点列用 `SCROLL_GUTTER_X=60`（左边缘白边，退化成点击时无害 —— 10-08 的规矩）。

分离度（真机帧，**2026-10-09 重测**）：四宫格在视野里 **0.9998~1.0000**
（含未滚动 y=532 与滚回顶部 y=275 两个落点）；四宫格真滚走 **0.7080**；
其余竖屏页 **≤0.6049**。唯一「过阈」的是 `signin_success`
（0.9998）—— 那是签到成功弹窗盖在信息流上、四宫格作为背景仍在，语义上确实在；
而那条路会先被 `signin_done` 判据接走，走不到这里。

护栏：`test_the_exchange_icon_is_visible_only_before_the_feed_is_scrolled` /
`test_the_exchange_icon_search_strip_reaches_both_grid_positions`（10-09 新）/
`test_the_exchange_icon_strip_stays_clear_of_a_scrolled_away_grid`（10-09 新）/
`test_returning_to_tasks_rolls_back_when_the_exchange_icon_is_off_screen` /
`test_returning_to_tasks_clicks_once_the_exchange_icon_is_back` /
`test_returning_to_tasks_gives_up_instead_of_rolling_forever`。

### ⚠️ 2026-10-09：搜索带只认一个落点 ⇒ 判据恒假、滚 3 次全白滚

**用户报**：「社区签到也报错……向下滑动的时候那个兑换按钮也滑下去了，然后它就找不到了」。

现场（`runtime_logs/epic7_community.log` 00:15:22~00:15:33）：

```
动作=feed_scroll_back_for_exchange ... 这一屏看不见「兑换」图标，先往回滚一屏再问（第 1/3 次）
执行滑动 起点=(60, 700) 终点=(60, 1500)
结论待确认=CommunityDataMissing 依据=往回滚了 3 屏，信息流顶部还是看不见「兑换」图标
```

现场帧 `20261009_001753_968326_timeout_feed.png` 里，**四宫格整整齐齐在屏幕上**、
「兑换」就在 `(426, 275)` —— 而程序说它「看不见」。

**根因**：老搜索带 `(360, 380, 160, 300)` 只搜 y 380~680，注释写「四宫格未滚动时
落在 y 488~620」。它把「四宫格只在未滚动那个高度」**写死了** —— 而实测四宫格有
**两个**落点，模板**都是满分 1.0000**：

| 落点 | 场景 | 分数 |
| --- | --- | --- |
| y=**532** | 正常进入信息流 | 1.0000 |
| y=**275** | **往回滚到真正的顶部**之后（本次现场帧） | 1.0000 |

老带子上沿 380 比 275 **低 105px** ⇒ 图标在屏幕上、分数却是 **0.0**
⇒ `feed_exchange_icon_visible()` **恒返回 False** ⇒ 往回滚 3 次**全白滚**。

⚠️ **滚动逻辑一直是对的**（3 屏 × 800px 足够覆盖下滚的 1600px），
**错的是「看不看得见」那把尺子**。⇒ 报「找不到 X」时先问：
**「X 真的不在，还是我没去看那一块」**——量「目标在帧里的实际坐标」vs「判据搜的框」。

**修法**：`FEED_ICON_STRIP` → `(330, 200, 200, 500)`（y 200~700）。
两条新护栏把「跨两个落点」与「别放太宽变成永远为真」**成对**钉住
（断言里的 y 与阈值**独立写死**，不从常量反推）。
新夹具 `feed_grid_at_top_live_20261009.png`（那个 y=275 的落点，**唯一物证**），
并已登记进 `test_project_layout.py` 的整目录集合断言。
反向验证：`.workbuddy/_reverse_verify_exchange_strip.py`（3 个注入点全红）。

## 2026-10-07 深夜复盘：兑换只兑一次就干等 + 两种「网络失败」分开收治

用户真机实跑反馈：*「体力兑换完之后识别不出来，就停在那边，只兑换一次就卡住了，
后面慢慢就自动报错了」*。查日志后**三个问题**，一起修掉。

### P0-6 兑换只兑一次 ⇒ 干等 60 秒 ⇒ 报失败

日志原文（21:14:21，21:22:52 再来一遍）：

```
操作=ack_redeem_done ... 目标页面=item_detail
（静默 66 秒）
转场超时 动作=ack_redeem_done 原页面=redeem_done 期望页面=item_detail
         当前已确认页面=exchange_center 内部状态=兑换中心
```

诊断帧 `20261007_212358_801234_timeout_transition_ack_redeem_done.png` 是**兑换中心**，
而**行动力已经是「每日限购 2/2」** —— 第一次兑换**真的成功了**，卡住的是第二次。
整份日志的统计印证：`完成=open_item 目标页面=item_detail` **2 次**、
`完成=confirm_redeem 目标页面=redeem_done` **2 次**（每跑一次各一条）⇒ **每次跑只兑一件**。

**机制（⚠️ 这条是本路线最阴的一处）**：`_on_redeem_done` 的 `target_pages` 只写了
`("item_detail",)`，而那层「兑换成功」弹窗点掉「确认」后**一次退两级、落回兑换中心**。
落点不在 `target_pages` 里 ⇒ 基类 `_transition_completed` **永远为假** ⇒
主循环（`runner_base` ~646）**把状态机这一帧给的 `open_item` 直接丢掉** ⇒
下一件永远兑不成，干等到 `EXCHANGE` 的 60 秒超时。**状态机一句话都没说错，是转场契约判它失配。**

⇒ 修：`target_pages=("exchange_center", "item_detail")`（两个都收）。
之后的链路是**自然**接上的：page 派发表按页名分发 ⇒ 落回兑换中心就跑 `_on_exchange_center`
⇒ `read_exchange` 每帧重读限购、`plan_redeem` **无状态**重新规划 ⇒
行动力 1/2 → 2/2 → 装备强化石 → 饰品强化石 → `done` → 按正常出口收工。
`REDEMPTION_PLAN` 的顺序本来就与用户预期一致（行动力×2 → 装备强化石×1 → 饰品强化石×1）。

### 三种「网络失败」不是一回事 —— 别再混为一谈

| # | 形态 | 画幅 | 收治方式 | 判据 |
| --- | --- | --- | --- | --- |
| ① | 游戏客户端「与服务器的连接已中断 / 点击重试」 | 横屏 1982×1132，**模态** | 命中即点**屏幕中央**（点哪儿都触发重试） | `find_network_retry`（只看文案，阈值 0.88） |
| ② | 社区 H5 **整页**「网络连接异常，下拉刷新」 | 竖屏 1080×1920 | **按页面要求下拉刷新** | `community.py` 的 `_on_network_error` |
| ③ | 黑底白字「网络错误」长条 + 网页容器右上角 ✕ | 横屏 1982×1132（盖在游戏内 WebView 上） | 点**右上角那颗 ✕** | 第 9 条全局弹窗 `web_network_error` |

②③ 都长在网页上，但**是两个东西**：② 是社区 H5 自己的整页错误（本路线竖屏段的事），
③ 是游戏内 WebView 层的错误（`navigation` 那批、横屏）。

#### ② 改成下拉刷新（原来那套「退出重进」是错的）

页面自己写着「下拉刷新」，就该照做，而不是退出去重进（一次 90 秒起，而且**从来没真的点出去过** ——
见下面 ③ 那条「主循环会丢动作」）。

```python
NETWORK_PULL_START = (540, 560)      # 竖屏：从页面中部起手
NETWORK_PULL_END   = (540, 1560)     # 往下拖一屏
NETWORK_PULL_MS    = 800
NETWORK_REFRESH_LIMIT = 3            # 这一趟运行里最多拉 3 次活
```

新增状态 `REFRESHING`（已发出下拉、等 H5 活过来），`BLOCKED` 语义收窄成
「连着拉活也没活过来，停」。**两处必须记住**：

1. **计数要按「次」不要按「帧」**。原先 `_network_retries += 1` 写在判据命中处 ⇒
   实测 **21 秒涨了 3**（每帧一条都是「网络异常」）。现在加 `state is not REFRESHING` 的
   守卫：同一次刷新只记一笔。
2. **转场中不许判失败**。`_SETTLING_STATES = {ENTERING, REFRESHING}`，这两档里
   `observe` 判不出页面**不算故障** ⇒ 只等、不计失败（原来只对 `ENTERING` 开，刷新那几秒
   会被误判成「认不出页面」）。

#### ③ 新接第 9 条全局弹窗，但它的分工与别的弹窗**反着来**

模板：`navigation/web_network_message.png`（672×84）+ `navigation/web_error_close.png`（54×54），
点击点实测 **(1879, 93)**。放 `navigation/` 的理由：它和 `web_activity_gate` / `web_community`
同一个 WebView（不是 `global/` 那批游戏主界面弹窗）。

⚠️ **`WebNetworkErrorTemplates` 的注释里写清了这条反例，别照抄别的弹窗**：

- `message`（黑底白字长条）= **排他判据**，阈值 `_WEB_NETWORK_THRESHOLD = 0.80`
  （比 0.82/0.88 松一点，**故意的不对称代价**：漏认要去点屏幕中央、白烧点击预算）。
- `close`（右上角圆钮 ✕）= **定位点击点**，阈值 `_WEB_ERROR_CLOSE_THRESHOLD = 0.85`。
  ⚠️ **它单独不能当判据** —— 实测它在**正常网页帧**上也有 **0.9970 / 0.9739**（网页本来就有这颗钮）。

分离度（2026-10-07，生产口径 `load_template` + `find_template`）：
长条正例 **1.0000 ×2**（相隔 40 分钟两张真机帧）；「还在转圈」**0.2455 / 0.2450**；
正常网页列表 **0.2161**；**全库 227 张横屏夹具最高 0.4908**（阈值 0.80）。
新定位器全库跑一遍：**228 张里只命中 1 张 —— 就是新加的那张夹具本身，零误报**。
交叉验证：`find_network_retry` 在两张 ③ 的正例上都是 `None`，`find_web_network_error_close`
在 ① 的帧上也是 `None` ⇒ **两种失败确实互不命中**。

#### ⚠️ 让「下拉刷新」真能发出去：主循环会丢掉转场里的新动作

修 ② 时发现旧的「退出重进」**一次都没执行过**：20:31:35 → 20:32:00 连着 3 条「网络异常」，
日志里**一条 `执行点击 动作=logout_community` 都没有**。原因与 P0-6 同一个：
主循环（`runner_base` ~646）拿 `confirmed_page` 比上一个动作的 `source_page` / `target_pages`，
对不上就把状态机这一帧的动作置 `None`。

⇒ 在 `CommunityRunner` 里覆写两个钩子（**这是修 ② 能不能生效的关键，不是附属品**）：

```python
def _transition_completed(self, previous_action, current_action, confirmed_page) -> bool:
    if confirmed_page == "network_error":
        return True      # 网页死了 = 这个转场作废，改走下加拉活
    return super()._transition_completed(previous_action, current_action, confirmed_page)

def _transition_success_detail(self, previous_action, current_action) -> str:
    if getattr(current_action, "source_page", "") == "network_error":
        return "（实为 H5 报「网络连接异常」：这个转场作废，改走下加拉活）"
    return super()._transition_success_detail(previous_action, current_action)
```

### 这一轮的护栏（全部**反向验证过**）

| 文件 | 新增 |
| --- | --- |
| `tests/test_community.py` | 下拉刷新 4 条（**就地**拉活而不是退出 / 手势**往下**拖 / **不按帧计数** / 预算用完才 `BLOCKED`）+ `test_ack_redeem_done_accepts_landing_back_on_the_exchange_center` + runner 2 条（`test_the_web_dying_ends_the_pending_transition` / `test_the_transition_abort_logs_why_it_was_abandoned`） |
| `tests/test_global_popups.py` | 6 条：能认出并给出 ✕ 点击点 / 抹掉长条不命中 / 抹掉 ✕ 不命中（**不许退回猜的坐标**）/ 别的横屏帧不命中 / **两种网络失败互不命中** / 守卫端到端消费掉它 |
| `tests/test_project_layout.py` | 两张新模板 + 一张新夹具登记 |

反向验证（`.workbuddy/_reverse_verify.py`，跑完自动还原）**4 个注入点全部真红**：

| 注入 | 点红的护栏 |
| --- | --- |
| 长条没了也当命中 | `test_web_network_error_requires_the_message_bar` |
| 下拉方向写反（往上拖） | `test_the_refresh_gesture_drags_downwards` |
| 撤掉 runner 的「网页死了=转场作废」覆写 | `test_the_web_dying_ends_the_pending_transition` |
| `target_pages` 退回只有 `item_detail` | `test_ack_redeem_done_accepts_landing_back_on_the_exchange_center` |

⚠️ 反向验证脚本**显式判 `returncode == 5`** —— 那表示「一条都没跑到」（`-k` 当单个 argv 传的坑），
**看着全红其实没验**，绝不能只看「非零退出」。

**门槛**：`tools/check.py --files …` **绿** —— 编译 + ruff（`All checks passed!`）+
mypy（`no issues found in 13 source files`）+ **1844 passed / 1 skipped / 714 subtests**（10 分 06 秒）。
⚠️ 它**自动升了全量**（原因写得很清楚：`改了共享模块 games/epic7/global_popups.py -> 全量`）
—— `--files` 拦不住共享模块，这一点下次别再指望。

### ⚠️ 还没做：真机重跑

三个修都**只过了离线护栏**。用户要的四连兑（行动力 2/2 → 装备强化石 → 饰品强化石 → 收工）
**还没在真机上走过一遍**。

## 已知缺口（写在这里，别装作不存在）

> **2026-10-07 更新**：下面头两行（三条任务的执行段、签到未完成态）**已经采齐并实现**  
> （见本文件末尾「2026-10-07 真机采集纪要」）。`LIVE_RUN_READY` 已翻成 `True`。

| 缺口                                   | 影响                                                                                                  | 补法                                                                           |
| ------------------------------------ | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| ✅ ~~三条每日任务的「执行段」全缺~~                 | 2026-10-07 采齐：`TASK_SCRIPT` 三条脚本 + `FEED_FIRST_POST` / 分享链；点赞那颗 👍 10-07 晚改成**模板定位**（不再用坐标，见 `### 7`）                       | 已实现；`FEED_FIRST_POST` **仍只有单日样本**，跨天要复验（见下）                                                  |
| ✅ ~~「签到未完成」那一态没有样本~~                 | 2026-10-07 采齐：未签到 = 图标**彩色**（含红点）、已签到 = **全灰**，平均饱和度 49.1 vs 0.0                                    | 已实现（`feed_signin_state`）；两态夹具 `feed_before_signin_*` / `feed_after_signin_*` |
| **三条任务的坐标只有 2026-10-07 单日样本**        | 卡片高度由正文长短决定 ⇒ 换一天 `FEED_FIRST_POST` 可能对不上。**后果可控**：对不上只会让那条任务被记成「今天做不成」，不会点坏东西。⚠️ **点赞那颗 👍 已不再依赖坐标**（2026-10-07 晚改成模板定位，见 `### 7`）   | 第二天再采一次 `FEED_FIRST_POST` 对一遍；若漂移，改成模板定位帖子卡（而不是死坐标）                                        |
| ✅ ~~卡片 👍 是开关，但脚本没在点之前读颜色~~            | 2026-10-07 晚已修，而且发现**原来的读色闸门读的是 tab 栏**（等于不存在）。现在改成**找**空心 👍（`card_like_off`），点完再按**刚点的那个点**读一次颜色确认变绿   | 已实现（见 `### 7`）；护栏 8 条，全部反向验证过 |
| **「一轮 N 次」与「回任务页」都还没在真机完整跑通** | 2026-10-07 20:36 已真的跑到点赞段：定位器现找出 👍 在 `(904,760)` 并点中 ✅，但**随即**暴露 P0-4 / P0-5（一轮只做 1 次、回程点死坐标）。两条都已修、护栏全部反向验证过，**但还没在真机上重跑确认**。真机上「点完计数真的涨到 `3/3`」也仍缺一次确认 | 再跑一轮点赞任务，看「我的任务」那一行从 `0/3` 变 `3/3`、且中途**不**回对账；同时留一帧「点完之后那颗 👍 确实变绿」的现场帧 |
| **`FEED_ICON_EXCHANGE` 仍是钉死的点击点** | 判据（模板）已经会告诉调用方「图标在不在」，但**点的位置仍是常量**。那颗图标属于周年庆活动的四宫格 ⇒ 活动换皮后即使判据说「在」，也可能点偏 | 等下一次活动改版采帧时，把点击点也改成「由模板中心 + 偏移」产出，那时再补一张新模板作候选 |
| **`FEED_FIRST_POST` 与 `FEED_TASK_SCROLL_*` 的位移量没复验** | 「滑一次 = 往前一篇」用的是 10-07 的位移量，**跨天/跨卡片高度没验过**。滑多了会跳过一篇（少浏览一次），滑少了会重复浏览同一篇   | 真机上连滑 5 次，每滑一次存一帧，量出「一次滑动的位移」与「卡片高度分布」 |
| **签到弹窗的延迟没有定论**                      | 10-07 实测点后 3 秒 / 9 秒都没反应、74 秒后再看弹窗已经在了。**是服务端慢还是第一下没生效，没查出来**                                       | 下次真机采样时专门盯一次：点完连拍 10 帧看有没有中间态（loading / toast）                               |
| **订单确认页按钮「禁用」与「不在」分不开**              | 两者在颜色定位里都是「找不到」⇒ 目前一律按「等结果」处理。若按钮其实**没出现**（页面没到），会白等到 150 秒超时才报错                                    | 采一帧「订单确认页刚打开、按钮还没出现」的画面；有样本后可以给「已点过」加一条旁证（例如页面上另一处固定提示）                      |
| **`tasks_fresh` 是 1103x1899 的另一口径帧** | 它不能给判页用（尺寸不同），只能做读数样本 ⇒ 「三个任务都未完成」这一格**没有竖屏口径的帧**                                                   | 补一张 1080x1920 的「三个任务都未完成」信息流/任务页帧，替换它                                        |
| **数字 4 / 6 / 7 缺「同一串字对照」的确认**        | 字模是从真实帧切的，但 4/6/7 这三个字在社区三处数字里**出现次数少** ⇒ 单字命中余量只验过一遍                                               | 采几帧含 4/6/7 的余额/限购（如 `4/4`、`6/…`、`7/…`）后再跑一遍 `_probe_community_numbers.py`    |
| **行动力只兑过一次，缺「第二次兑换」的帧**              | `REDEMPTION_PLAN` 把行动力定成**每日限购 2** ⇒ 路线会兑两次。⚠️ **2026-10-07 深夜查明「只兑一次」不是缺帧，是 P0-6：`target_pages` 写错 ⇒ 第二次的动作被主循环丢掉**（已修，见上一节）。链路本身的**帧**仍然只有第一次的 | 采一帧「行动力 1/2」时的兑换中心（验证 `plan_redeem` 真会指向卡 1 第二遍）以及第二遍的成功链                    |
| **`exchange_center` 的命名会骗人**         | 文件名 `exchange_center_live_20261006` 其实是**空列表态**，`exchange_after_redeem` 才是正常兑换中心 ⇒ 照名字理解会搞反「哪个是正常态」 | 不改文件（改要动测试与模板来源注释），在 `test_project_layout.py` 的夹具表注释里点明了                     |
| **`tasks_one_browse_done` 的名字与画面不符** | 实测读出来是**第 2 行（点赞）已完成**、第 1/3 行未完成 ⇒ 照名字推内容会推错                                                       | 同上，已在夹具表注释与 `test_community_pages` 的期望里写明                                    |
| **`strings/` 那 8 张整串模板不在生产路径上**      | 它们不是判据，删了不影响判页/读数（但会让「备用路径」失效）                                                                      | 不需要修；真要修整串读法时才动                                                              |
| **不做接力**                             | 人停在社区（竖屏）里启动，会**起步就失败**（见 `RESUME_EXEMPT`）                                                          | 要做得先改 `main.py` 的 `_enter_mode`：起步时若模拟器是竖屏就先退出社区                             |

## 怎么验

```bash
# 只改这条路线时（约 1~2 分钟）
D:\anaconda\python.exe auto_game_unified\tools\check.py --files games/epic7/community.py

# 改了 modes.py / navigation.py / daily_tasks.py / desktop/** / core/** 这些共享模块 ⇒ 全量
D:\anaconda\python.exe auto_game_unified\tools\check.py --full
```

⚠️ 下面几条是**真 Runner 级 / 契约级**的 —— 它们是唯一能守住「判据真的接进主循环」的防线，  
别为了变绿去改：

- `test_every_action_carries_an_exit_check`（每个动作都带出口验收）
- `test_action_points_stay_inside_the_portrait_canvas`（竖屏点击点不许越出 1080x1920）
- `test_closing_finishes_only_after_the_screen_turned_back`（转回横屏才收工）
- `test_finished_route_leaves_the_community_before_finishing`（收工前一定先关社区）
- `test_order_confirm_waits_instead_of_failing_when_the_button_is_disabled`  
  （按钮禁用是**正常等待**，不是失败）
- `test_runner_*` / `test_dual_channel` 那一组（转屏、退回横屏、干跑不接 adb、非模拟器拒绝）
- `test_the_run_loop_is_delegated_to_the_base_class`（`run()` 不许绕过基类）
- `test_a_swipe_step_is_sent_through_the_swipe_channel_not_as_a_click`（滑动真走滑动通道）
- `test_the_return_step_does_not_accept_its_own_page_as_an_exit`（出口集合不含来源页）
- `test_capture_waits_out_a_rotation_instead_of_failing_the_route` 与  
  `test_capture_fails_only_after_the_settle_budget_is_spent`（换向取图 = 有界等待，不是秒失败）
- `test_capture_does_not_swallow_a_manual_stop`（兜底只接方向异常，不吞「停止」）
- `test_a_fixed_point_step_clicks_it_without_the_template` 与  
  `test_the_gate_step_declares_a_fixed_point_instead_of_hunting_the_glow`（光球按钮走固定坐标）

### 竖屏判据怎么复核（改判据时）

1. `runtime_logs/_make_community_anchors.py` 重跑 → 出全库扫描报告；  
   看「9 个锚点零可疑命中」是否还成立（**同栈内**命中是正常的，**跨栈**命中才是事故）。
2. 用 `docs/manual_review/community/` 里的索引图肉眼对一遍「帧名 vs 实际页面」。
3. 改数字读数时跑 `_probe_community_numbers.py`，看 19 个验证点是否仍全中。

### 实跑验收（`LIVE_RUN_READY=True`，可以跑了）

1. 把游戏停在**大厅**，跑  
   `python -m auto_game_unified.main --mode community --live --confirm RUN --max-cycles 1`。
2. 看日志是否依次出现：导航完成（`ready_note=网页活动列表已就绪`）→ `完成=enter_community`  
   → 竖屏「签到（`tap_signin` → `ack_signin_done`）/ 我的任务 / 兑换中心」各步  
   → `完成=close_community` → `状态=完成一遍`。
3. 检查收尾：模拟器**转回横屏**、回到大厅；若积分不够，退出码应是 **2**（不是 1）。
4. 若某条任务一直对不上账，日志里会出现「连着 N 遍做完、计数都没动，判定今天做不成」——  
   那句就是**诊断入口**：先看 `runtime_logs/epic7_community.log` 里那几步的坐标，  
   再看当天真机帧的卡片位置是不是漂了（见上面「已知缺口」里的单日样本一条）。

### 采样清单（下一次真机要补的，按优先级）

1. **实跑一轮点赞任务**：看「我的任务」那一行 `0/3 → 3/3`，同时留一帧
   「点完之后那颗 👍 确实变绿」的现场帧（新定位器目前只有离线证据）。
2. **量「滑一次的位移量」与卡片高度分布**：连滑 5 次、每滑一次存一帧 ——
   钉住 `FEED_FIRST_POST` / `FEED_TASK_SCROLL_*` 跨天/跨卡片高度是否还成立
   （滑多了会跳过一篇、滑少了会重复浏览同一篇）。
3. **跨天复验 `FEED_FIRST_POST`**（点赞那颗已改成模板定位，不用再复验坐标）。
4. **含 4 / 6 / 7 的余额或限购**几帧（补字模对照；10-07 采到的是 920 / 0-2 / 0-1 / 0-1，都没有 4/6/7）。
5. **行动力第二次兑换**的链路帧（兑换中心 1/2 → 商品详情 → 订单确认 → 成功）。
6. **订单确认页「按钮还没出现」**&#x90A3;一瞬的帧（把「禁用」与「不在」分开）。
7. **签到点完到弹窗出现之间**连拍 10 帧——确认那段等待里有没有中间态（loading / toast）。
8. ~~**一屏有多颗未点赞 👍 时**再采一张~~ —— **2026-10-11 作废**：
   点赞任务已摘出清单（服务端永久记住点赞状态 ⇒ 翻不到可点的 ⇒ 死循环），
   这一项**不需要再采**。原需求留在这里只为说明「为什么当时觉得需要」：
   一轮要点 3 颗，而 `feed_cards_all_todo` 只有两颗，怀疑点完一颗后另一颗的 y 会变。

## 2026-10-07 真机采集纪要（这一天采到了什么、判据跟着怎么改）

> 工具：`runtime_logs/_sample.py`（点前点后各留一帧 + `actions.log` 记坐标与意图）。  
> 产物：`runtime_logs/_sample/20261007/`（115 张竖屏帧）。  
> 因为这条路线**很多东西一天只能点一次**，采样台的立身之本就是「凡点过必留痕」。

### 1. 「今天签没签」怎么读 —— 看**颜色**，不是看形状

同一块「每日签到」图标：

| 态   | 长相                      | 这一块（`SIGNIN_ICON_BOX`）的平均饱和度 |
| --- | ----------------------- | ---------------------------- |
| 未签到 | 黄墨水瓶 + 棕羽毛笔，右上角一个**红点** | **49.1**                     |
| 已签到 | **整块变灰**（其余三个图标照样彩色）    | **0.0**                      |

阈值 `SIGNIN_ICON_SATURATION = 20`，落在 0 与 49 正中间。另配一道**亮度闸门**  
（`SIGNIN_ICON_MIN_VALUE = 120`）：签到成功弹窗的压暗背板会把彩色图标也压成 0 饱和度，  
少了它，弹窗那一帧会被读成「今天已签」⇒ **当天直接漏签**。

### 2. 签到入口与弹窗

- 入口就是信息流图标行第一格 `FEED_SIGNIN_CLICK = (240, 538)`，**点它即签到**。
- ⚠️ **点完不会立刻出弹窗**：点后 3 秒、9 秒各抓一帧都没变化，74 秒后再看已经在了。  
  ⇒ `_TIMEOUT_SECONDS[FEED]` 给到 150 秒，并且**点了就等、不重复点**。
- 弹窗「签到成功！」的表头（✅ + 那行字）是固定内容 ⇒ 新锚点 `signin_done`  
  （区域 `(271,628,539,103)`，弹窗帧 1.0000、全库次高 0.1419）。  
  弹窗本体里「获得 行动力*50 / 同时经验+55、积分+40」**逐次不同**，不能当判据。
- 关掉它的绿按钮是 `SIGNIN_POPUP_CLOSE = (539, 1212)`。  
  ⚠️ **别照渲染图目测** —— 我第一次目测成 `(561,1283)`，点了两下全无反应；  
  用颜色连通域量出来的中心才对得上。

### 3. `post_detail` 判据为什么坏过、怎么修的

原区域 `(560,1790,440,90)` 把**评论数**罩了进去，而评论数逐帖不同  
（10-06 那帖「221」、10-07 那帖「165」）⇒ 今天只拿到 **0.7706**，落在死区里，  
整页读成 `unknown`（表现是「帖子详情认不出」）。  
改裁成只取右侧那颗**分享箭头**：区域 `(790,1790,110,85)`。  
全库 54 张唯一竖屏帧扫描：13 张帖子详情帧全 1.0000，其余最高 0.3x，**零误命中**。

这是「**模板里不放会变化的内容**」那条铁律的又一次实例，只是这次变化的东西是**数字**。

### 4. 三条每日任务怎么跑（2026-10-07 **晚**已改粒度，见 `### 7`）

点「去完成」之后落在**信息流首页顶部**（四次实测都是同一帧）。粒度是**一轮**：

- **浏览帖子**：一轮 **11 步** = 3 × 「点开帖子 → 帖内下滑并停 6 秒 → 退回信息流」，
  两篇之间夹一次下滑。
- **点赞帖子**：一轮 **3 步** = 3 × 「**找**一颗还没点过的 👍 并点它」。
- **分享帖子**：一轮 **4 步** = 点开帖子 → 底部 ↗ → 分享面板「复制链接」→ 返回。

⚠️ **计数是唯一权威**：每跑完一轮就回「我的任务」对账（那一行的 `x/3` 涨没涨），
涨了才算数、没涨再来一轮、连试 `TASK_ATTEMPT_LIMIT=3` **轮**都不涨就记一笔
「今天做不成」并跳过它继续跑别的。脚本只是手段，计数才是验收。

⚠️ 「一轮没跑完就回来了」（中途那一下没生效）**也记一笔**。不记就是**死循环**：
那一串动作名相邻两两都不同（`start_task` / `task_xx_1` / `back_to_tasks_via_exchange`
/ `goto_tasks_card`）⇒ 主循环那本「同一动作 4 次」的账记不到它，而每次点击都会刷新
`absolute_started`、绝对超时也兜不住。项目红线：绝不死循环。

### 5. 去「我的任务」的路怎么走（底栏那个「我的」是**错的**）

实测：信息流底栏「我的」`(925,1790)` → 社区**个人主页**（判不出页面）。  
正确的是：**信息流「兑换」图标 `(438,538)` → 兑换中心 → 「获取积分卡」`(800,270)` → 我的任务**。  
状态机里用 `via_exchange` 表达「到兑换中心只是路过」，路过的那一帧**不做兑换决策**。

### 6. 当天的真机事实（复核用）

- 09:00 进社区时：积分 880、经验 1255/1550、浏览 0/3、点赞 0/3、分享 0/1、兑换全 0/…。
- 09:22 签到成功：获得 行动力*50，经验 **+55**、积分 **+40**（积分 880 → 920）。
- 09:12 采到的兑换中心：积分 **920**、行动力 0/2、装备石 0/1、金币 0/1、饰品石 0/1  
  ⇒ `plan_redeem` 会先挑卡 1（行动力），完全对得上清单。

### 7. 点赞那颗 👍：写死的坐标是错的（2026-10-07 **晚**复量，用户拍板改成「找」）

老写法是 `FEED_CARD_LIKE = (911, 735)` + 读色框 `FEED_CARD_LIKE_BOX = (880, 700, 70, 70)`。
**两处都错**，而且第一处错得毫无声息：

1. **那一块不是 👍**。放大看是 tab 栏「骑士团」三个字（纯白，rgb 243.9/244.2/245.4）；
   盘上三张信息流夹具那一块**完全相同**。于是「点之前先看颜色、只点灰的」这道闸门
   **从来没读到过 👍** —— `card_like_is_on()` 恒返回 `False`（=「没点过」），等于没有闸门；
   同理，「点完之后要读到变绿」那道验收也**永远读成「没变」**，每轮白等 8 帧再作废。
2. **y 随卡片高度漂**。卡片高由正文长短决定；同一帧里两张卡的 👍 实测分别在
   y 756 与 y 1314（**差 558px**）。钉死一个 y 只在那一次测量的那一屏上成立，
   换一屏就点空 —— 而点空之后下一次落点可能就落在 tab 栏上。

**量出来的事实**（2026-10-07 19:39 现场，连滚 6 屏采的帧）：

| 事实 | 数值 |
| --- | --- |
| 空心 👍 的 x | **恒为 883..925**（43 宽）；只有 y 漂 |
| 出现过的 y | 330 / 490 / 863 / 1143 / 1314 / 1523 / 1674 |
| 已点赞那颗（实心青绿）在模板下的分 | **0.43**（离 0.82 很远） |
| 真命中（6 帧里的空心 👍） | **1.0000** |
| 全库竖屏夹具误报 | **0 张** |
| 单帧一次全带搜索耗时 | **约 11 ms** |

⇒ 新模板 `community/pages/card_like_off.png`（47×43，**对称边距 2** ⇒ 点击点仍是字形中心），
搜索带 `CARD_LIKE_STRIP = (860, 240, 120, 1520)`。
「模板命中」**本身就是**「这颗还没点过」的证据 ⇒ 不需要再补一道读色闸门
（补了也是跑不到的分支，而跑不到的分支比没有更糟）。

**两处必须一起改的东西**（漏一处就白改）：

- `TaskStep.point` 允许写 `None`（= 位置运行时现找）。`_step_action` 拿到 `None`
  且调用方没给替代点 ⇒ **当场抛**，绝不静默点 `(0,0)`。
- 出手之后的那道验收要读**刚点的那个点**（`self.like_point`）⇒ 老写法读死框，
  两边都读错。`_evidence_seen` 因此从 `staticmethod` 变成实例方法。

**新夹具两张 —— 不可拆，一起才说明问题**：

- `feed_cards_mixed_live_20261007`：同屏 1 颗已点赞（y≈780）+ 1 颗没点过（y≈1333）。
  没有它，「模板只认没点过那颗」就是一句空话。
- `feed_cards_all_todo_live_20261007`：同屏 2 颗都没点过（y≈880 / y≈1690）。
  钉住「多个候选取最靠上」以及「y 漂 810px」这件事本身。

**护栏**（全部**反向注入验证过会红**）：`test_the_locator_finds_the_unliked_thumb_and_not_the_liked_one`、
`test_the_locator_does_not_match_an_already_liked_thumb`、
`test_the_locator_returns_nothing_when_no_thumb_is_on_screen`、
`test_like_step_clicks_the_point_it_just_located`、
`test_the_like_verify_reads_the_box_it_actually_clicked`、
`test_the_like_verify_runs_even_when_the_click_was_the_last_step`、
`test_card_like_reading_box_is_centred_on_the_point_it_was_given`、
`test_a_step_with_no_point_and_no_locator_result_refuses_to_click`。

⚠️ 写这类护栏时踩到两个**假绿**，都记在这儿：

1. **自证式断言**：用例调被测函数本身去算「该涂哪一块」，函数挪到哪儿涂色就跟着挪到哪儿
   ⇒ 恒成立，注入违规纹丝不动。涂色框必须**独立算**（拿点 + 常量）。
2. **`pytest -k` 传参**：把 `-k 名字` 当成**一个** argv 传进去 ⇒ pytest 收不到 `-k`、
   「没选到任何用例」并以 **5** 退出 —— 看起来是红的，其实是**假红**。
   反向验证脚本必须显式判 `returncode == 5` / `no tests ran` 并**报错**。

## 2026-10-08 复盘：点中插图 → 图片查看器 → 整条路线卡死（**第三次**，这次连根拔）

### 现场：两次实跑败在同一处

| 时间 | 现场形状 |
| --- | --- |
| 18:58 | `task_browse_5` 点 `(400, 1450)` → `UnrecognizedCommunityScreen` → **干等 150 秒** |
| 19:10 | 同上，逐字一致 |

收尾也一起挂了：`RuntimeError: 画面宽高比与模板基准不一致` —— 那时窗口还在竖屏，拿横屏模板去套，
于是**连刚打开的社区都关不掉**。同一个坑 10-07 20:39 已经咬过一次 —— **这是第三次**。

### 根因（两层，只补一层下次照样卡）

1. **盲坐标落在内容上**。`FEED_FIRST_POST = (400, 1450)`：

   | 帧 | 同一个 y=1450 落在哪 |
   | --- | --- |
   | `feed_cards_all_todo_live_20261007` | 卡片 2 的**插图带**（y 1360~1630） |
   | `feed_list_live_20261006` | **正文** |

   ⇒「写死一个 y 去点帖子」这件事**本身就不成立**（卡片高由正文长短决定），不是这次运气不好。
   视觉复核：旧点（红圈 y1450）正落在插图「欧勒毕斯 冒险手册」上，新点（绿圈 y1336）落在其上方正文。

2. **认不出、也退不出**。真进了那一屏：判页没有这一类；而 `runner_base` 的转场校验发现
   `confirmed_page` 既不是上一动作的 `source_page` 也不在 `target_pages` 里 ⇒ 把状态机刚给的
   `action` 置 `None` ⇒ **没人发得出「按返回键」**，只能干等超时。

### 修法（五处：一层治根 + 三层兜底 + 一处采纳用户建议）

#### ① 治根：现找「正文带」，不是换一个盲坐标

`community_pages.locate_feed_post_tap(screen, hint)` 以 `hint[1]` 为中心**先往上再往下**找一条
「白底 + 有字 + 不是图片」的带；**x 原样沿用 hint[0]**（保点击点不横向漂），返回
`(hint[0], top + slab // 2)`；找不到返回 `None`。

`feed_tap_band_is_text(screen, top, height)` 三条**同时**成立才算正文：

| 判据 | 阈值 | 正文带实测（150 条） | 图片带实测 |
| --- | --- | --- | --- |
| 彩色占比（max−min > `FEED_TAP_SATURATION`=35） | ≤ `FEED_TAP_COLORFUL_MAX`=0.12 | 0.000~0.098 | **≥ 0.147** |
| 暗像素占比（< 阈值） | ≥ `FEED_TAP_INK_MIN`=0.03 | 0.030~0.239 | — |
| 纯白占比 | ≥ `FEED_TAP_WHITE_MIN`=0.65 | 0.655~0.960 | — |

搜索带 `FEED_TAP_STRIP = (0, 250, 1080, 1500)`（整宽 —— 正文带要找得宽，**起点列**才要窄）。
`_drive_task` 的 `tap_post` 分支拿到 `None` ⇒ **当场收手去 `_return_to_tasks`，绝不退回盲坐标**。

#### ② 兜底：万一还是进了那一屏，要**认得出**

`community_pages.detect_image_viewer(screen)` —— **结构性判据，不是模板**：上下两条全黑带
（单行 ≥98% 像素 max 通道 < 40）夹一条不贴边、高 ≥60 的内容带。

| 帧类 | 黑行占比 | 张数 |
| --- | --- | --- |
| 图片查看器 | **0.8276 ~ 0.8370** | 5 |
| 其余竖屏帧 | **0.0000** | 35 |

⇒ 阈值 `IMAGE_VIEWER_MIN_BLACK_FRACTION = 0.60` 坐在 `0.0000 ↔ 0.8276` 这个宽空档正中。
`judge_page` 里**先判查看器、命中即短路**（它盖住整屏，别的判据都不该有机会），并进
`LAYER_ORDER["image_viewer"] = -1`。定位 `ImageViewerFrame.band` + `.center` 属性（供诊断用）。

#### ③ 兜底：这一类屏要能**退得出**

新状态 `CommunityState.IMAGE_VIEWER` + 动作 `dismiss_image_viewer`（`press_back=True`）
⇒ `_perform_action` 走 `runtime.back()`。超时表补 `IMAGE_VIEWER: 45`。

`_GLOBAL_OVERLAY_PAGES = frozenset({"image_viewer", "network_error", "signin_done"})`：
**盖住整屏的全局浮层页**出现即宣布「这次转场作废、先收掉它再重来」——
这条是绕开根因 2 那个 `action → None` 的唯一出口。

#### ④ 血泪：`observe` 只许委托 `judge_page`（**判据只能有一份实现**）

`CommunityStateMachine.observe` 原本**自己抄了一份**判页逻辑 ⇒ 新加的查看器判据**真机走不到** ——
**单测全绿，实跑照旧卡 150 秒**。已收口成一行：

```python
def observe(self, screen):
    return pages.judge_page(screen, self.templates)
```

并留护栏 `test_the_machine_and_judge_page_agree_on_every_frame`（扫盘上全部竖屏帧，两边结论必须逐帧一致）。

#### ⑤ 采纳用户建议：所有**滑动起点列**移到左边缘

用户原话：「如果保险点可以从左边的边缘那些地方往下拉，它就不会碰到中间的图片了」。
量了一遍，**成立**（y 240~1760，该列彩色像素占比）：

| 列 | x=20 | x=40 | **x=60** | x=80 | x=100 | x=540 |
| --- | --- | --- | --- | --- | --- | --- |
| 最低~最高 | 0.000 | 0.000~0.012 | **0.000~0.003** | 0.000~0.003 | 0.000~0.018 | **0.057~0.191** |

信息流卡片通栏白底、插图**居中** ⇒ 中间那一列**确实穿过插图**，左边缘是干净的。
`SCROLL_GUTTER_X = 60`，三对滑动常量（`FEED_TASK_SCROLL_*` / `FEED_ICON_SCROLL_*` / `POST_SCROLL_*`）
的 x 全用它。

⚠️ **为什么这不只是「保险点」**：`_perform_action` 只在 `swipe_end` 非空时才发 `swipe` ——
**那面旗子一丢，主循环就在起点点一下**（10-07 点赞任务三遍全废正是这个形状）。起点在 x=540 的
插图上 ⇒ 打开图片查看器 ⇒ 整条路线卡死；起点在白边上 ⇒ 什么也不会发生。

⚠️ **刻意不动** `NETWORK_PULL_START/END`（仍是 x=540）：那一页（H5 报「网络连接异常」）整屏没有插图，
而且下拉刷新本来就该从页面中部拉。

### 这一轮的护栏（全部**反向注入验证过会红**）

`test_image_viewer_never_fires_on_any_other_portrait_frame`、
`test_image_viewer_requires_a_content_band_not_touching_the_edges`、
`test_abstains_instead_of_guessing`、
`test_locate_feed_post_tap_abstains_on_the_image_viewer`、
`test_feed_tap_band_accepts_body_text_and_rejects_a_photo`（**0.15 挡 / 0.09 放**边界样本
＋真机 y=1714 过渡带）、
`test_the_machine_sees_the_image_viewer`、
`test_the_image_viewer_is_dismissed_with_the_back_key`、
`test_the_image_viewer_ends_the_pending_transition_too`、
`test_every_overlay_page_has_a_way_out`、
`test_the_browse_tap_never_falls_back_to_the_blind_point`、
`test_every_scroll_gesture_starts_in_the_left_gutter`。

反向验证脚本：`auto_game_unified/.workbuddy/_reverse_verify_viewer.py`（11 个注入点，
跑法 `D:/anaconda/python.exe auto_game_unified/.workbuddy/_reverse_verify_viewer.py`）。

⚠️ 这一轮反向验证又抓出 **2 条空护栏**，形状都记在 `MEMORY.md` 的「教训」里：
① 边界样本不能造极端值（纯色 1.0 那张「怎么放水都挡得住」）；
② **不许拿被测常量当断言输入**（`for page in sorted(_GLOBAL_OVERLAY_PAGES)`）。

### 还是没做：真机重跑

代码侧改完了，**实跑要用户自己走一遍**（本仓库规矩：实跑由用户执行）。
验收点：`task_browse_*` 出手的 y 应该在正文带上；万一又进了查看器，日志里要出现
「转场作废 ... 被「image_viewer」这层盖住了」，并**在 45 秒内**自己按返回键退出来。

## 2026-10-08 第二轮：活动页「记得上次选的那个」⇒ 那一行被挤出视野

### 现场（用户原话）

> 「如果我点进去那个活动页面，因为它会记录我之前是从什么地方点进去的……那后面再进去的话，
> 也是那个位置。然后那个位置很可能看不到那个**更多精彩活动**……需要**往上拉一下**才能看到。
> 所以你需要做这样一个兜底：如果你进入活动页面，找不到这个更多精彩活动那个按钮和文字的话，
> …往上拉，拉完之后再去看。」

### 为什么这条兜底**必须有**（不是保险，是刚需）

活动页左列表**会记住上次点的是哪一个** ⇒ 再进来还停在那个位置。而导航第 2 步要点的
「更多精彩活动」**在列表较下方**（实测位置本来就随上方活动行数漂：10-06 落 y=484、
10-07 落 y=710，差 226px）。累积几行活动之后它就**滚出了视野**。

### ⚠️ 本轮差点又踩同一个坑：兜底挂在**走不到的分支**上

这是本次最重要的发现。`activity_menu` 这个页面的**判页锚点就是 `activity_more`**
（`observe()` 里直接由它认出）⇒ 那一行被挤出视野时，画面**不是**「页面认得出、
锚点找不到」，而是**整页判 `unknown`**：

```
observe(pushed) = unknown          # pushed = 那一行被挤出视野的合成帧
locate(activity_more) = None
_wait_for_page("activity_menu") -> RuntimeError: 导航开始前应处于[活动页（未选推广）]
```

⇒ 如果在「`_locate()` 返回 `None`」那一支补滚动，真机上**永远走不到** ——
`_transition` 开头那句 `_wait_for_page(source)` 已经先抛了。**判据写好了、生产走不到**，
与 10-08 第一轮 `observe` 抄双份是同一个病。

⇒ 所以兜底挂在**两个位置**（`_wait_for_page_with_scroll` + `_locate` 那一支），
用同一个 `scroll_before_retry` 声明。反向验证专门有一条给它：把「等来源页」那一支
摘掉之后，`test_the_scroll_happens_before_the_page_wait_gives_up` **必须变红**
（第一版它没红，说明当时那条用例在测一个生产走不到的分支 —— 已改成走生产路径）。

### 怎么实现的（新文件 + 三个声明点）

| 位置 | 内容 |
| --- | --- |
| `games/epic7/activity_column.py`（**新**） | 左列滚动的全部参数：`ACTIVITY_SCROLL_X=90` / `START_Y=900` / `END_Y=774` / `STEP=126` / `MS=400` + 为什么这么取的长注释 |
| `NavigationStep.scroll_before_retry`（新字段） | 「重试前先滚一屏」的**声明**（数据，不写逻辑） |
| `Epic7Navigator._scroll_<名字>` | 具名方法 `_scroll_activity_column`（`runtime.swipe`） |
| `modes.py` 第 2 / 3 步 | 各声明 `scroll_before_retry="activity_column"` |

⚠️ **为什么声明在 `NavigationStep` 上而不是写死进 `_transition`**：`_transition` 是
**所有路线共用**的，不能认识「活动页左列」这种东西。计划里只声明「重试前先滚一下」，
怎么滚由导航器自己的具名方法实现（钩子名 ↔ 方法名有一条构造期对账护栏）。

### 三个参数怎么定的（都是量出来的）

- **起点 x=90** —— 用户拍板「左列文字上」。⚠️ 与竖屏信息流那条 `SCROLL_GUTTER_X=60`
  **取向不同**：左列**没有**一条干净的白边可躲（实测 x=15/30/60/90/120 的彩色占比
  都是 0.17~0.24，整列橙底加装饰）。所以选择的标准不是「躲到干净的地方」，而是
  **退化成点击时点到什么** —— x=90 落在**活动名那一行文字**上，点中的效果只是切换
  选中项，无害且可恢复；落到右侧则会打开别的东西。
- **滚动量 126px（一行半）** —— 不取一整屏：左列一屏 8~10 行，滚一屏可能正好把
  目标行从视野上沿滑过去。一行半保证**任何一行都不会被跳过**。
- **上限 3 次** —— ⚠️ 与社区那条 `FEED_ICON_RESWIPE_LIMIT` **已经不同口径**了：
  社区在 2026-10-10 提到 **4**（它要滚的距离更长），活动栏这边仍是 3，**没跟着改**。
  判据相同：滚到底还没有就说明不是「滚过头」而是活动页真改版了，**报错收手，绝不蒙着点**。

**有效性实测**（一次性探针 `_verify_activity_scroll.py`，用真机帧合成「被挤出视野」；
量完即弃，不留在仓库里）：

| 被挤出视野的量 | 滚几次找回 |
| --- | --- |
| 400px | 1 次 |
| 500px | 1 次 |
| 600px | **2 次** |

### 这一轮的护栏（全部**反向注入验证过会红**）

`test_the_select_step_asks_for_a_scroll_before_giving_up`（钉**声明**）、
`test_the_declared_scroll_hook_actually_exists_on_the_navigator`（全路线对账
「声明的钩子名 ↔ 导航器上的方法名」，名字写错在真机上才炸）、
`test_the_scroll_retry_is_bounded_and_never_guesses`（滚满上限就报错收手）、
`test_the_scroll_happens_before_the_page_wait_gives_up`（**走生产路径**：滚动发生在
「等来源页失败」之前，且落点在恢复后那一行上 —— 期望值独立算）、
`test_the_scroll_reveals_the_row_that_was_pushed_off_screen`（兜底真的有用）、
`test_the_activity_scroll_starts_on_the_left_column_text`（起点列 + 方向）。

反向验证脚本：`auto_game_unified/.workbuddy/_reverse_verify_activity.py`（6 个注入点）。

⚠️ 又抓出 **1 条空护栏**：`test_the_scroll_retry_is_bounded_and_never_guesses` 原来
传了 `source_screen` ⇒ 绕开了「等来源页」那一支 ⇒ 给它注入违规**纹丝不动**。
⇒ **凡测「兜底/恢复」的用例，都必须从生产入口（不传帧）走一遍** —— 这是
「判据写好了、生产走不到」这个病的第三种形状了（前两种：抄双份实现、空护栏）。

### 门槛（2026-10-08 收尾）

`check.py --files`（6 个文件：`activity_column.py` / `navigation.py` / `navigation_plan.py` /
`modes.py` / `test_navigation.py` / `test_community.py`）**全绿**：

| 项 | 结果 |
| --- | --- |
| ruff | `All checks passed!` |
| mypy | `Success: no issues found in 13 source files` |
| pytest | `748 passed / 263 subtests` + `645 passed / 259 subtests` + `562 passed, 1 skipped / 360 subtests` |

中间红过两次，**两次都是操作失误、不是代码缺陷**，各记一条：

1. **断言消息里写了 `⇒`** —— `tests/test_community.py:1688/1740` 的断言消息带 `⇒`，
   被 `ConsoleEncodingTests` 的 AST 扫描挑中（它**会挑中新加的断言消息**）。
   ⇒ 已改成括号表述。**新写断言消息时不要用 `⇒` / `⚠️`。**
2. **反向验证与门禁并发** —— 门槛在后台跑时我去跑了 `_reverse_verify_activity.py`，
   而它**会往工作区写注入后的源码**（`_SCROLL_RETRY_LIMIT = 0` 等），只在 `finally` 还原
   ⇒ 门槛读到注入源码 ⇒ 两条用例假红（`3 != 0`）。**脚本比手改更隐蔽，因为它看起来只是在跑测试。**
   ⇒ 规矩升级为「**别在门禁跑的时候动工作区**」，两者**必须串行**。


## 2026-10-09 收尾复盘：一次实跑里的三处「记录与现实脱节」

用户真机实跑（13:04）走到最后一步「任务做完 → 回「我的任务」对账」时失败，
报「往回滚了 3 屏，信息流顶部还是看不见「兑换」图标」。同一份日志
（`runtime_logs/epic7_community.log`）里其实藏着**三处**同一类毛病：
**手上的记录 / 尺子，跟屏幕上的现实对不上。** 三处一起收掉。

### ① 尺子只量一个位置（已在上节详述）

搜索带把「四宫格只在未滚动那个高度」写死，而四宫格有 y=532 与 y=275 两个落点
⇒ 判据恒假、往回滚 3 次全白滚。修法与护栏见上面
`### ⚠️ 2026-10-09：搜索带只认一个落点` 那一节。
**滚动逻辑一直是对的，错的是「看不看得见」那把尺子。**

### ② 滑动账本按「帧」记 ⇒ 只滑了 1 屏，却报「滚了 3 屏」

`feed_scroll_back_for_exchange` / `task_like_reswipe` 这类动作，主循环对它
**同名动作有重试节流**（默认 45 秒内只执行一次）。而状态机**每一帧**都重新想滑一次
⇒ 按帧记账的话，「往回滚 3 屏」这个上限几秒钟就烧穿，实际一屏都没滑出去。
13:04 的日志就是这么说的：只有 **1 次**「执行滑动」，却报「往回滚了 3 屏」——
**报的是一句假话**，排错时会把方向完全带偏。

⇒ 改按「**手势真的执行了**」记账，证据是**页面结构动了**：正文带位置表
（`pages.feed_band_tops`，与生产点帖判据**同一套实现**）变了。滚 800px 会整体换一批
正文带；头像/动图那种局部动画不会。同一帧反复喂 ⇒ 只记第 1 屏的账。
连 `SWIPE_UNEXECUTED_FRAME_LIMIT` 帧都没看到页面动 ⇒ 报的是
「**手势没被执行**（节流没放开 / 页面锁滚动）」，**不是**「滚了几屏没找到」——
这两件事以前被混成一句话，是查不出原因的重要原因。

同时把这类动作的重试间隔从默认 45 秒压到 `_QUICK_RETRY_SECONDS`（8 秒）：
点完**立刻**能看出生效没有的动作，等 45 秒纯属白等（三屏预算全耗在等待里）。

护栏：`test_the_reswipes_are_counted_only_after_the_page_really_moved` /
`test_the_swipe_accounting_stops_when_the_page_never_moves`（报「手势没被执行」）。

### ③ 收尾：方向回来了，**记录**没跟上 ⇒ 回家白等 24 秒

异常收尾（缺数据 / 认不出）时，人还停在社区竖屏页面里，`_leave_portrait_if_needed`
负责点退出、并**等模拟器真的转回横屏**（这一步 10-07 就修好了）。
但它只等**方向**、不动**通道记录**：

- 异常收尾时**没人点过「退出社区」**，所以没人把记录拨成 `PENDING_LANDSCAPE`，
  它一直停在 `PENDING_PORTRAIT`；
- 紧接着基类要回首页，取图时 `use_portrait()` 走 `PENDING_PORTRAIT` 那一支 ——
  而那一支**「还没转成竖屏也返回 True」**（它本意是把等待委托给竖屏通道）
  ⇒ 先白等 20 秒竖屏超时、再由 `_fallback_to_landscape` 退回横屏。

日志形态一目了然：

```
13:07:52 收尾=人还在社区竖屏页面里 动作=先退出社区，等转回横屏再回首页
13:07:54 收尾=已退出社区且方向已转回横屏 已等回横屏≤8秒
13:07:54 模式=导航 目标=大厅 状态=开始
13:07:54 竖屏通道 方向=等待切换为竖屏 当前客户区=1920x1080 最长等待=20秒
13:08:18 竖屏通道 方向=社区未真正打开 原因=等待模拟器切成竖屏超时（已等 20.0 秒）
```

13:07:54 到 13:08:18 那 **24 秒**，全耗在等一次**不可能发生**的转屏上。

⇒ 修法：**确认已经是横屏之后，把通道记录也拨回横屏**（`demote_to_landscape`）——
成功等回横屏那一步、以及「人已经不在竖屏里」那条 early return，两处都补。
⚠️ **等不到转回横屏时不许拨** —— 那种情况下记录保持竖屏才是诚实的，
拨过去会让下一步又走错通道。

护栏：`test_closing_out_hands_the_landscape_record_to_the_next_step` /
`test_closing_out_also_winds_the_record_back_when_already_landscape` /
`test_closing_out_does_not_pretend_landscape_when_it_is_still_portrait`。
反向验证：`auto_game_unified/.workbuddy/_reverse_verify_portrait_record.py`
（2 个注入点全红）。⚠️ 该脚本注入的是 `community.py`，那份文件是 **CRLF**，
所以它按文件实际换行符适配、还原走 `shutil.copyfile`（字节级）——
**用 `read_text`/`write_text` 裸读写会把 CRLF 悄悄改成 LF**。

### 这一轮的门槛（2026-10-09）

| 项 | 结果 |
| --- | --- |
| `check.py --files community.py test_community.py` | ruff / mypy / 编译全绿，**160 passed / 267 subtests** |
| `check.py --full` | ruff / mypy / 编译全绿，**1982 passed, 1 skipped / 890 subtests** |

⚠️ 顺手修掉一处 ruff `B905`（`_register_swipe_emission` 里的 `zip()` 没写
`strict=`）—— 它会让 `--files` 门槛**卡在静态检查这步、根本走不到测试**，
看着像「测试挂了」，其实是格式问题。补 `strict=False`（长度不等那支已被
前面的 `or` 短路包住，走到 `zip` 时两条带子必然等长）。

### ⚠️ 还没做：真机重跑

上面三条都只有**离线护栏**背书，**没有一次「从头跑完一整轮」的真机记录**。
下次真机验收要看的顺序：
进社区 → 签到（或「今天已签」）→ 三条任务 → 兑换 → 回信息流 → 关社区 →
转回横屏 → 回首页，**全程无需人工干预**，且日志里
**不该再出现「等待切换为竖屏」**（出现即说明 ③ 又漏了）。

## 2026-10-10：滚动账本被试算污染；往回滚改成「滚到顶为止」

### 现场（08:03~08:07 实跑）

任务做完要回「我的任务」，先得往回滚把信息流顶部的「兑换」图标滚出来。日志里
`feed_scroll_back_for_exchange` 连续 4 次全报「上一滑还没执行 / 仍在等第 0 屏生效」，
最后以 `retry_exhausted` 收场。而**同一段日志里点赞点坐标一直在变、四宫格也真被滚回来过**
—— 页面明明在动。

### 根因：跨帧对比的账本没进快照

主循环 `transactional_runner_base.run` **每帧先 `preview`（试算）再真跑 `next_action`，
两次喂同一帧**。`_register_swipe_emission` 的三个账本字段
（`_pending_swipe_name` / `_pending_swipe_tops` / `_pending_swipe_streak`）是 10-09 新加的，
**没同步进 `_snapshot()` / `_restore()`** ⇒ 试算把基线设成本帧、回滚时只回滚了计数器
⇒ 真跑拿「刚刚试算写下的基线」跟同一帧比 ⇒ **恒判「页面没动」**
⇒ `like_reswipes` / `feed_icon_reswipes` **永远停在 0** ⇒ 两条「滑 N 屏就收手」的闸门
**同时失效**。

⇒ **凡是「跨帧对比」的账本，只要进了 `next_action`，就必须进快照。**
护栏 `PreviewKeepsSwipeLedgerTests`（4 条；反向验证：撤掉修复 4 条全红）。

### 顺带：闸门即使生效也不够宽 —— 改成「滚到顶为止」

实跑里任务段往下滑了 6 次（每次 800px、共约 4800px），而往回滚最多给 4 次 × 800px
= 3200px。修好记账只让报错变清楚，路线仍跑不通。改成：

| 项 | 之前 | 现在 |
| --- | --- | --- |
| `FEED_ICON_SCROLL_START/END` | `(60,700)`→`(60,1500)`，800px | `(60,360)`→`(60,1750)`，约 1390px |
| `FEED_ICON_RESWIPE_LIMIT` | 3 | 4（与主循环的 4 次对齐）|
| `FEED_ICON_STUCK_FRAMES` | — | 2（画面连续不动即判「到底了」）|

⚠️ 把「**滚到顶了**」（正常到底）与「**手势一直没执行**」（通道 / 节流故障）拆成
两种报错 —— 两者画面都不动，但一个是正常、一个是故障。混成一个错误，等于把既有护栏
`test_a_swipe_that_never_executes_is_reported_honestly` 拆掉（第一版就是这么被顶红的）。

判据：`feed_icon_reswipes >= 2`（第 1 笔是立基线、不算「动过」）**且**连续不动 ≥ 2 帧
⇒ 报「已经滚到顶了」；一直只停在 1 ⇒ 留给 `SWIPE_UNEXECUTED_FRAME_LIMIT` 如实报
「没看到页面滚动」。

护栏：`test_scrolling_stops_when_the_page_says_it_is_already_at_the_top`（10-10 新）。

### ⚠️ 「闸门失灵」和「闸门够不够宽」是两件事

本轮同一天踩了这两个，而且会互相掩盖：修好记账会**掩盖**宽度不够（原来报
`retry_exhausted`，修好后改成报 `CommunityDataMissing`）；只加宽会**掩盖**记账没生效
（计数恒 0，加多宽都白搭）。⇒ **两件事分别验证**：账本看护栏，宽度看实跑。






## 2026-10-18 第三轮：**判据不再靠位置** —— 骨架判页 + 页内双向扫描

### 用户把旧方案判死了

> 「但是你要认识到一个问题，就是说这个活动我点进去，它可能在任何位置都有可能，有可能这个
> 页面还没有这个网页活动呢，可能还要上滑下滑，对不对？这种情况下要怎么样才能稳定呢」

这一句问的是「稳定」，而旧方案给的是「再放大一点」。两者的区别是本质的：
**区域是固定的，位置是没有上界的**。第三次漂移就是证据：

| 日期 | 「更多精彩活动」落点 | 谁把它推走的 |
| --- | --- | --- |
| 10-06 | y=425 | 正常 |
| 10-07 | y=460 → **686** | 上方多出两行回归活动，把它挤下去 |
| 10-18 | **258** | 列表顶部变空，它往上漂，比当时的上界 300 还高 |

10-18 那天整页判 `unknown`、12:17 重试 4 次全败、社区签到进不去 —— 而模板分数是
**0.9959**。判据没错、模板没错，是**框够不着**。

### 结论：判页必须是页面骨架，不能是「那一步要点的东西」

这是本项目第三次踩同一条：

| 年份 | 锚点 | 它本职是什么 | 结果 |
| --- | --- | --- | --- |
| 10-07 | `web_activity_gate` | 「前往活动页」的点击目标 | 光球滑过 ⇒ 1.0000→0.7282 |
| 10-08 | `expedition_entry` | 「进入远征队」的点击目标 | 赛季卡片换内容 ⇒ 0.4734 |
| 10-18 | `activity_more` | 第 2 步的点击目标 | 列表滚动 ⇒ 位置没有上界 |

⇒ 现在 `activity_menu` / `activity_web_promo` **只靠 `activity_page_shell` 认页**
（横幅底部那一条，与列表滚动、与选中项都无关）。`activity_more` 降级为**纯点击目标**
（仍留作快路径：它只在活动页存在，是最精确的证据，但不再是唯一证据）。

### 骨架锚点是怎么选的（不是猜的，是扫出来的）

`_probe_activity_shell3.py` 在全库 **340 张 1982×1132 横屏帧**上比了 6 个候选，
按「正样本最低分 − 负样本最高分」排序：

| 候选 | 正样本最低 | 负样本最高 | 分离度 |
| --- | --- | --- | --- |
| **横幅底部条 `(0,130)-(380,175)`** | **0.9659** | **0.6496** | **+0.3163** |
| 横幅整体（不含右侧） | 0.9520 | 0.7578 | +0.1942 |
| 横幅左半（含标题） | 0.9380 | 0.7990 | +0.1481 |
| 旗帜右段 | 0.9968 | 0.8756 | +0.1212 |
| 箭头 + 左侧装饰 | 0.9827 | 0.9365 | +0.0462 |
| 顶部细条 | 1.0000 | 0.9659 | +0.0341 |

被淘汰的两个是**有理由的**，别再把它们加回来：

- **标题文字不行** —— 同一条横幅上的标题从「活动」改成了「事件」（10-06 vs 10-18）。
- **左上角返回箭头不行** —— 实测它在战斗三页 / 赛季页 / 竞技场页上**全是 1.0000**。
  箭头是「所有子页都有」的东西，天生不能当判据。

阈值取 **0.90**（正样本 0.9659 起跳、负样本 0.6496 封顶，两边都有余量）。
失效方式是可预期的：**活动换皮换了横幅** ⇒ 认不出活动页 ⇒ 导航第一步报
「应处于[活动页]」收手，**不会瞎点**。

### 找入口：上下扫，不猜位置

`_scan_activity_column`（`Epic7Navigator`）的形态：

```
先在当前帧找 → 找不到就滑一屏 → 每滑一屏重新认一次
    阶段 1  回列表头方向  × ACTIVITY_SCROLL_LIMIT_PER_DIRECTION (3)
    阶段 2  反方向        × 2 × 3 = 6
```

**为什么阶段 2 给双倍**：手势的物理方向**没有在真机上单独验证过**（`shop_refresh` 与
`community` 两处注释都说「往下拖＝回到顶部」，但这属于未复验的假设）。如果方向猜反了，
阶段 1 会把列表往反方向推 3 屏，阶段 2 先用 3 屏抵消、再用剩下 3 屏往另一头扫 ——
**方向猜错不影响正确性，只多花几下**。这是这次设计的核心取舍：正确性不依赖未验证的假设。

三个出口，没有一个靠猜：

| 出口 | 行为 |
| --- | --- |
| 命中 `activity_more` | 点**命中框中心**（位置随行浮动不影响点击） |
| 只命中 `activity_more_selected` | 目标态已经在了 ⇒ **不点**（点一下会取消选中） |
| 两个方向扫满仍没有 | 存诊断图 `activity_entry_missing` + 报错收手 |

⚠️ 第二条是新判据带来的**新风险**的护栏：骨架分不出「未选中 / 选中」两态（同一块横幅），
行滚走时行模板也看不见 ⇒ 唯一的分辨机会就在扫描里。

### 步长 400 的硬约束：**必须小于搜索带高度**

搜索带 y 180~1120 = **940px**，步长 400 ⇒ 相邻两次取景重叠 540px，**任何一行都不会
从带子上沿滑过去**。这条约束比「滚得远」重要得多 —— 步长一旦 ≥ 带高，就会造出
「滑两次都没看见」的漏行，而漏行在真机上表现成「入口不见了」。

### 拆掉的东西（别再把它们加回来）

- **`_wait_for_page_with_scroll`** —— 整层删除。它治的是「判据长了腿」这个症状；
  判页换成骨架之后，「页面认不出」不再能靠滚动解决（真认不出就是真认不出）。
- **`_scroll_retry` / `_scroll_<名字>` 钩子** —— 改名 `_scan_<名字>`。只会滚、不会认的
  方法已经不够用了：现在每一步滑动之后**都要重新认一次**。
- **第 3 步的 `scroll_before_retry`** —— 那一步用固定坐标点右侧按钮，且上一步的扫描
  已经保证「那一行看得见、选中态已成立」⇒ 声明是死的。

### 护栏（`tests/test_navigation.py`）

| 用例 | 钉住什么 |
| --- | --- |
| `test_the_row_off_the_top_is_still_the_activity_page` | **地基**：那一行滚出画面后，页面仍判 `activity_menu`（骨架），且 `activity_more` 确实找不着 |
| `test_the_shell_anchor_tells_the_activity_page_apart` | 骨架只在活动页过阈（大厅 / 赛季 / 竞技场 / 战斗第三页都不过） |
| `test_the_page_scan_is_bounded_and_never_guesses` | 扫满预算 ⇒ 一下都不点 + 文案点名扫过几屏 |
| `test_the_scan_finds_the_row_after_one_scroll` | 扫完真的点在被找回的那一行上（落点独立算） |
| `test_the_scan_skips_the_click_when_the_row_is_already_selected` | 认出选中态 ⇒ 跳过点击；目标不是那一态时**不许**谎报已达成 |
| `test_the_activity_scroll_gestures_stay_inside_the_column` | 两个方向都落在左列文字上、都在可见区内、且方向相反 |
| `test_the_declared_scan_hook_actually_exists_on_the_navigator` | 计划里声明的钩子名 ↔ 方法名对账 |

### ⚠️ 合成帧的坑：`np.roll` 会把滚走的行**从底部卷回来**

第一版合成帧用 `np.roll(band, -520)` 模拟「那一行跑到屏幕上方之外」，结果那一行
**又出现在 y=702**（roll 是环形移位，顶上被推出去的从底部回来了）⇒ 用例以为自己
复现了事故，其实那一行一直在画面里，`assertIsNone` 变成一句空话。

正确做法：整体上移 + **底部补最后一行**（`shifted[-offset:] = band[-1]`）。
另外**只滚列表区 `y 180~1120`，不滚顶栏** —— 真机上列表滚动时顶栏一动不动，
而骨架锚点就在顶栏里；把整条左列一起滚，等于连判据一起滚掉了。

---

# ⚠️⚠️ 2026-10-18：点歪进「作者账号主页」卡死 150 秒 —— 改成「陌生页可恢复」

这是本路线**第 15 次**同形失败（`runtime_logs/epic7_community.log` 里
`UnrecognizedCommunityScreen` 共 15 条，10-07 起）。前 14 次都在「补一页判据」，
这一次换了方向：**不再试图认识所有页面，而是让"不认识"变得可恢复**。

## 现场（决定性证据：同一轮、同一坐标、24 秒内一成一败）

| 时间 | 动作 | 坐标 | 结果 |
| --- | --- | --- | --- |
| 18:30:33 | `task_browse_1` | **(400, 1444)** | `完成=post_detail` ✅ |
| 18:30:52 | `task_browse_4` | 下滑 800px | — |
| 18:30:57 | `task_browse_5` | **(400, 1444)** | `UnrecognizedCommunityScreen` ❌ |
| 18:33:28 | 超时诊断 | — | 人停在**「第七史诗」官方账号主页** |

诊断帧 `runtime_diagnostics/epic7_community/20261018_183328_870617_timeout_feed.png`
与 14:17 那张 **md5 完全相同**（`bece8364…`）⇒ 稳定复现，不是偶发。
已存成夹具 `tests/fixtures/epic7_community/stranger_account_page_live_20261018.png`。

## 根因分两层，缺一条都解释不通

### 第一层：判据**没有区分力**（点歪）

`feed_tap_band_is_text` 的三条（白底 / 有字 / 不是图片）描述的是「**像不像文字**」。
而信息流的卡片里，**像文字的东西有一大堆**：

```
┌────────────────────────────────┐
│ (头像) 第七史诗 ✓   06-08   ⋯ │ ← 作者行（点它 = 打开作者主页！）
│ E7三周年！｜三周年狂欢庆典… │ ← 标题行
│ 亲爱的继承者：三周年庆典即将… │ ← 正文段落（点它 = 打开这篇帖子）
│ 亲爱的继承者：本次将开启…     │ ← 正文段落
│ ┌────────全宽大图────────┐ │
│ 酒馆闲聊              👍 4 │ ← 标签行
└────────────────────────────────┘
```

作者名行与正文段落**外观同类**（白底黑字、都不是图片）。前三条判据把它们
**一起放行** ⇒ 坐标落在哪一行就纯看运气。

⚠️ 这一层**不可能靠调阈值解决**：再多调几次也只是改概率，不是改对错。

### 第二层：认不出 ⇒ **静默干等 150 秒**（小失误变大事故）

`UnrecognizedCommunityScreen` 直接继承 `RuntimeError`，**不是** `UnrecognizedScreen`
的子类 ⇒ 主循环那条 `isinstance(..., UnrecognizedScreen)` 的「未知页只等/唤醒」
分支**跳过它** ⇒ 落进「状态超时」的 `sleep + continue`
⇒ **18:30:59 → 18:33:28 共 149 秒一行日志都没有**。

（顺带：就算接上了也没用 —— `UnknownScreenWake.handle` 第一行
`_valid_render_canvas` 只吃 1982x1132 的横屏画布，竖屏帧一律 `SKIPPED`。）

### 第三层（为什么"改了这么多次还是错"）：诊断退化

日志里那句 `最高分 0.0000；已知观察=[]`：

- `0.0000` **不是量出来的** —— 是 `PageJudgement("unknown", 0.0, ...)` 里写死的；
- `[]` 只列**过阈**的观察，而 `unknown` 意味着一条都没过阈。

⇒ 15 次失败日志**字字相同**。事后连「是陌生页，还是差 0.01 没过阈」都分不出来，
每次修都只能猜。**这才是"改了很多次还不对"的直接原因。**

## 修法（四条，按落地顺序）

### ① 判据：新增「通栏」这一维，让可点的东西**唯一**

`pages.feed_tap_band_is_post_body` = 前三条 **且** `feed_tap_band_span ≥ FEED_TAP_SPAN_MIN`。

`span` = 这一行**暗像素的横向跨度**。卡片里只有正文段落通栏，作者名/标题/标签都只有一小条。
全库 6 张信息流帧、y 250~1750 逐 12px 扫（**179 条被前三条放行的 slab**）：

| 跨度 | 条数 | 是什么 |
| --- | --- | --- |
| 120 ~ 399 | 63 | 作者名（251±2）/ 标题 / 标签 / 时间戳 / 点赞数 |
| **400 ~ 549** | **0** | **空档（150px 宽，一条都没有）** |
| 569 ~ 842 | 116 | 正文段落 |

门槛 **500**：左余量 101px、右余量 69px。护栏 `test_the_span_threshold_sits_in_an_empty_gap_on_every_fixture`
会重新扫一遍并断言两边各留够 50px —— **门槛被改到别处会立刻红**。

⚠️ `feed_band_tops`（滚动证据）**仍然用** `feed_tap_band_is_text`，这是故意的：
那里要灵敏度（带子越多，滚动越容易看出来），点击要唯一性。两者共用同一个底层判据。

### ② 陌生页：`RECOVERING` 状态 + 三级逃生门

`STRANGER_RECOVER_STEPS = ("back", "back", "back_arrow")`

| 序 | 动作 | 为什么 |
| --- | --- | --- |
| 1 | 系统返回键 | `portrait.back()` = `adb shell input keyevent 4`，通道现成 |
| 2 | 系统返回键（再来一次） | 有的页第一下只关掉一层浮层 |
| 3 | 点**左上角返回箭头** `(60,95)` | ⚠️ 实测「我的任务」页对系统返回键**完全没反应**，只靠返回键会漏 |

两条不许省的保险：

- **先等 2 帧再动手**（`STRANGER_WAIT_FRAMES`）：点完页面那一两秒 H5 正在画下一屏，
  那时整个画面本来就认不出。不等就按返回，会把一次**正常转场**按掉。
- **按一次 → 判一次**：每按完重新判页，判到已知页立刻停。连按会把社区**整个退出去**
  （代价是重进 90 秒）。

### ③ 恢复之后**把那一步退回来重做**（`task_step -= 1`）

出手那一帧 `task_step` 就 +1 了。不退的话下一帧会拿「下一步该在帖子详情」去核信息流
⇒ `_drive_task` 判「中间那一下没点中」⇒ **整轮作废**（一天只有三次机会）。
**同一步只准退一次**（`_stranger_rewound_for`），否则「点歪 → 退回 → 再点歪」会成死循环。

### ④ 诊断：失败那一刻就把真实分数写进日志

`PageJudgement.scores` = 全部锚点的真实分（`observe_pages(collect_all=True)`，
**同一趟匹配顺带留下，没有多跑**）。日志现在长这样：

```
陌生页（最像的三页=「暂时还没有商品哦」0.2285、网络连接异常 0.1517、订单确认 0.1463）：
第 1/3 级 —— 按系统返回键，把它退掉回到上一层
```

## ⚠️ 别再把这几件事做回去

- **不要给「账号主页」立判据**。H5 是开放页面集（话题页 / 转发页 / 举报页 / 活动页…），
  补不完；补了也只是把下一次失败往后推。出路是「能自己退出来」，不是「认识得更多」。
- **不要为了提高命中率再把前三条件放宽**。那三条的职责只是「挡图片、挡空白」，
  它们**天生分不出作者行和正文**。
- **不要用「多个候选里挑最像的」**。那不是唯一性。判据必须能**证伪**：
  作者行、标题、标签要被**排除**掉，而不是"分数低一点"。
- **不要把 `FEED_TAP_SPAN_MIN` 调到 600 以上**：正文最小实测 569，会误伤。

## 变异验证（拆掉修复必须变红，4/4 全红）

脚本 `auto_game_unified/runtime_logs/_mutate_community_stranger.py`：

| 变异 | 结果 |
| --- | --- |
| M1 `FEED_TAP_SPAN_MIN = 0`（取消通栏） | 6 failed ✅ |
| M2 `FEED_TAP_SPAN_MIN = 900`（正文也挡掉） | 2 failed ✅ |
| M3 `STRANGER_WAIT_FRAMES = 0`（不等确认） | 1 failed ✅ |
| M4 去掉 `task_step -= 1` | 1 failed ✅ |

## 新增 / 改动的护栏

`tests/test_community_pages.py::FeedPostTapRulerTests`

| 用例 | 钉住什么 |
| --- | --- |
| `test_the_author_row_is_not_clickable_even_though_it_is_text` | 现场帧作者行 y≈912~936 **旧判据全过、新判据必须拦** |
| `test_the_body_paragraph_right_below_is_clickable` | 同一张卡往下几十像素的正文**必须仍然可点**（防止把阈值调过头） |
| `test_the_span_threshold_sits_in_an_empty_gap_on_every_fixture` | 门槛在空档里、两边各留 ≥50px |

`tests/test_community.py`

| 用例 | 钉住什么 |
| --- | --- |
| `test_an_unrecognized_page_is_left_by_pressing_back_not_by_clicking` | 确认期（`STRANGER_WAIT_FRAMES`，现为 4 帧 ≈ 4~5 秒）内**一帧都不许动**，期满才按返回；既不盲点、也不干等 |
| `test_the_escape_ladder_is_bounded_then_fails_loudly` | 阶梯恰好是 back/back/back_arrow，用尽必须抛错并带真实分数 |
| `test_coming_back_to_the_feed_rewinds_the_failed_step` | 退回已知页后重做刚才那一步 |
| `test_the_same_step_is_never_rewound_twice` | 同一步只退一次（防死循环） |
| `test_an_unrecognized_frame_still_reports_how_close_each_page_was` | `scores` 不许再是空 / 不许再写死 0 |

⚠️ 原来那条 `test_unrecognized_screen_raises_instead_of_clicking`（用纯灰帧断言第一帧就抛）
**已按新契约改写** —— 新契约是「确认期 → 走逃生门 → 用尽才抛」。它删掉的那半个意思
（**绝不点屏幕中央**）由新用例第 ① 条继续守着。

⚠️ 用例里**不许写死确认帧数**（`for _ in range(2)` 这类）。`STRANGER_WAIT_FRAMES` 从 2 改到 4
时，写死 2 的那条用例当场漏了一帧，报的错是 `'NoneType' object has no attribute 'name'`
（看着像状态机坏了，其实只是用例过期）。一律写成 `range(cm.STRANGER_WAIT_FRAMES)`。
变异脚本同理，别写死 `STRANGER_WAIT_FRAMES = 2` 这种原文匹配 —— 已改成正则，
且「定位不到」现在算**失败**而不是跳过（否则门槛数字一改，变异会静默变假绿）。

## 已知未做：空白 / 加载中帧（缺一张真实帧，先记数据）

**风险**：H5 加载慢时可能连着几帧全白。那种帧判不出页 ⇒ 会走陌生页逃生门 ⇒ 按返回。
按一次通常无害（退回信息流、那一步重做），但**不该把它当成"陌生页"**。

**为什么没做**：手上**没有任何一张社区 H5 的真实加载中帧**。项目纪律要求判据出自真实帧，
拿一张合成灰图定出来的阈值，等于又造一个凭推断的判据。

**已有的测量**（`tests/fixtures/epic7_community/` 全 20 张，画布 10%~92% 行带；
「平坦行占比」= 行内 `max-min < 6` 的行数占比；「对比度」= 该带 `std`）：

| 帧 | 平坦行占比 | 对比度 std |
| --- | --- | --- |
| 最像空白的真实页 `network_error` | 0.8266 | 4.36 |
| `image_viewer` | 0.8005 | 46.23 |
| `exchange_center` | 0.7681 | 8.87 |
| 真实内容页（信息流 / 账号主页等） | 0.00 ~ 0.05 | 48 ~ 82 |
| 合成纯灰 / 纯白 | ≈1.0 | ≈0 |

⇒ **空档很窄**：只有 `flat > 0.9 且 std < 3` 才分得开，而 `network_error` 已经吃到 0.8266。
以后真要加这一档，**先抓一张真机加载帧存成夹具**，再定阈值、再做变异 —— 顺序不能反。
