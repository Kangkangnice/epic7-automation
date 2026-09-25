# 骑士团捐赠视觉维护

## 先看哪里

| 东西 | 位置 |
| --- | --- |
| 业务闭环与两条判据的完整说明 | `games/epic7/knights_donation.py` 模块 docstring |
| 「材料不足就跳过」判据本体 | `games/epic7/knights_support_digits.py` |
| 「请求支援今天用过了 ⇒ 灰了」判据 | `games/epic7/knights_donation.py`（`request_button_relative_v`） |
| 模板（含数字字模 `digits/`） | `games/epic7/templates/knights_donation/` |
| 锚点区域 `REGIONS` | `games/epic7/evidence/knights_donation.py` |
| 回归夹具 | `tests/fixtures/epic7_knights_donation/` |
| 给肉眼看的实拍标注帧 | `docs/manual_review/knights_donation/` |

## 「这一格能不能支援」的两道判据：改哪个要看改的是什么

「这一格能不能支援」有两道判据，**先看数字、再看结果**：

1. **点之前（前置，2026-09-25 补）**：读每行的「持有：N」与按钮上的「支援 M 个」，
   `N < M` 就跳过这一格、连点都不点。判据本体是 `knights_support_digits.py` 里的
   模块级 `read_row_numbers`（不是类），由 `knights_donation.py` 的
   `KnightsDonationStateMachine._row_numbers` 接进来。⇒ 改它是改前者。
2. **点之后（兜底）**：点完有没有弹「获得奖励」。没弹 ⇒ 记进 `skipped_rows`、换下一格。
   改它是改 `knights_donation.py` 的 `_at_resource_support` / `_at_support_confirm`。

⚠️ **认不出必须退回「照旧点」**：前置判据读不全时返回 `None`，调用方照旧点一次 ——
退回今天的行为，而不是误判成「不足」白丢积分。

⚠️ 游戏其实会闪一行小字「材料不足」，但那是**一闪而过的浮字**，主循环每秒取一帧必然漏检，
且「没看到」和「没出现」在画面上分不开 ⇒ **它不做判据**。前置判据用的「持有 / 需求」是
**静态**数字（一直在画面上），两者能分开，这正是 2026-09-25 敢拿数字做判据的原因。

## 「请求支援」今天已经用过 ⇒ 按钮变灰（2026-09-25 加）

每天只能请求一次。当天第二次运行时额度已用掉、右上「请求支援」**变灰**，但——

⚠️ **模板分认不出来**：`TM_CCOEFF_NORMED` 对亮度缩放不敏感，而变灰只是文字亮度变了、
字形一模一样 ⇒ 灰帧上模板仍得 **0.9846**（能点帧 1.0000，只差 0.015）。
所以「加一张灰按钮模板、比谁分高」这条路**走不通**（记下来免得再试）。
照点的后果：白等 `REQUEST_POPUP` 的 42 秒转场超时 ×4 ⇒ 整条路线提前收工（用户当天实跑现场）。

判据是 `request_button_relative_v`（在 `games/epic7/knights_donation.py`）：
**按钮区域 V 的 99.9 分位 ÷ 整幅画面 V 的均值**，阈值 `REQUEST_BUTTON_ALIVE_RATIO = 1.70`。

| 统计量 | 能点（5 张） | 已灰（4 张） | 能用吗 |
| --- | --- | --- | --- |
| 区域**均值** ÷ 整幅 | 0.524 | 0.597 | ❌ **方向是反的**（灰按钮的底板反而更亮） |
| 区域最大 ÷ 整幅 | 2.357 | 1.219 | 可以，但单像素易被噪点顶起来 |
| **区域 p99.9 ÷ 整幅** | **2.321 ~ 2.347** | **1.195 ~ 1.215** | ✅ 判据用它 |

- **必须用相对亮度**：绝对阈值会被**页面淡入**骗（world_boss 2026-09-23 已踩过 —— 绝对
  阈值在整屏压暗到 50% 时自己塌掉，把「还有次数」误判成「次数用完」）。把同一帧乘亮度
  系数 1.0/0.8/0.6/0.5/0.4/0.3 复现淡入，读数几乎不动。
- **底色不是判据**：能点的帧里有**褐底**（`support_page.png`，悬浮高亮）与**深蓝底**
  （`manual_review/02_*`）两种外观，读数一致 ⇒ 只看亮度、不看颜色。
- ⚠️ **拿不准就当作「还亮着」照旧点**（fail-open）：区域裁不出来 / 整幅全黑时返回
  「能点」。误判成「已灰」会白丢当天唯一一次请求，而用户从画面上几乎看不出来 ——
  所以不确定时宁可退回今天的行为。
- 跳过请求**不影响支援别人**（列表里的绿按钮跟这个额度无关）。

### 怎么复核 / 重采

```
D:/anaconda/python.exe auto_game_unified/runtime_logs/_probe_request_fade.py
D:/anaconda/python.exe auto_game_unified/runtime_logs/_probe_request_verdict.py
```

前者量各统计量与淡入稳定性，后者用**生产函数**验收分类并端到端看状态机动作（都是只读）。
改了 `request_support_button` 的**区域**、或换了那个模板，**必须重跑上面两个探针**，
再跑文末的测试 —— 其中 `test_the_threshold_sits_between_the_alive_and_grey_scores`
会把「两侧余量还剩多少」直接算给你看（余量掉到 25% 以下就该重采样本了）。

## 数字字模（`templates/knights_donation/digits/`）

### 覆盖范围：只有 0~5 六个，别当成万能

| 情况 | 结果 |
| --- | --- |
| 需求 ∈ 1~5 且 持有 ∈ 0~4 | 能判（实测需求只出现过 1 / 2 / 4） |
| 任一侧含 6~9 | 读不出 ⇒ `None` ⇒ **照旧点** |
| 非基准画布（1982×1132） | 整条判据弃权 ⇒ 照旧点 |

字模是**单通道二值 18×24**，按「字形高度」归一化后与掩膜切出的字形做
`TM_CCOEFF_NORMED`，阈值 `GLYPH_MATCH_MIN_SCORE = 0.70`。

### 字模从哪来：3 张实拍帧 / 5 行

| 帧 | 来源 | 按钮中心 y | 持有 | 需求 |
| --- | --- | --- | --- | --- |
| A `runtime_logs/_stuck_frame.png` | 2026-09-25 **实跑诊断帧** | 569 | 1 | **2** |
| A | 同上 | 764 | 225 | **4** |
| B `fixtures/.../support_page_two_buttons.png` | 手采 | 569 | 0 | 1 |
| B | 同上 | 764 | 5133 | 1 |
| C `fixtures/.../support_page.png` | 手采 | 569 | 5133 | 1 |

A 帧**原样**存成了夹具 `tests/fixtures/epic7_knights_donation/support_page_short_material.png`
（二者 md5 相同，是同一张）—— 事故的回归依据和字模的实拍来源是同一张图。

「持有」是绿色的（绿掩膜：色相 30~80、饱和 ≥120、明度 ≥140），按钮上的「支援 M 个」是白字
（白掩膜：饱和 ≤60、明度 ≥200）。**同一套字模跨两个样式用**，靠的就是按高度归一化。

### 每个数字的样本数（绿=持有侧 / 白=需求侧）

| 数字 | 样本数 | 来源 |
| --- | --- | --- |
| 0 | 1 | B@569 持有 |
| 1 | 6 | A@569 持有；B@569 需求；B@764 持有+需求；C@569 持有+需求 |
| 2 | 3 | A@569 需求（白）；A@764 持有 ×2（绿） |
| 3 | 4 | B@764 持有 ×2；C@569 持有 ×2 |
| 4 | 1 | A@764 需求（白） |
| 5 | 3 | A@764 持有；B@764 持有；C@569 持有 |

⚠️ **两个已知的薄弱处，改之前先想清楚**：

- `3` 和 `5` 的样本**全部来自「持有」侧（绿色）**，它们从没在「需求」侧出现过；
  真帧里也没出现过「需求 = 3 或 5」的格子。归一化跨样式的互认在留一验证里是 17/17，
  但**这个具体组合没有真帧为证** —— 遇到时按「读不出 ⇒ 照旧点」处理即可。
- `0` 与 `4` 各只有 1 个样本（来自 A 帧），要重采时优先找这两张的更多实例。

### 什么时候必须重采

- 游戏改 UI（字号、文字颜色、按钮大小、行高变化）⇒ 先跑复核图与测试，不对就重采；
- **换客户端 / 换分辨率**：实测把基准帧放大到 2 倍之后绿色那一侧就读不出来了
  （重采样把字缘色相拉走、掩膜碎掉）⇒ 尺寸偏离基准超过 `SIZE_TOLERANCE = 0.02` 时
  **整条判据弃权**。这不是 bug、是刻意 fail-open，别为了「让它能跑」去放宽这个数。

### 怎么重采

1. 采帧：目标分辨率 1982×1132（跟其它路线同一口径），一屏里要有**材料不足**与**材料充足**
   两种行；不足那种要能看清「持有：N」。
2. 把帧放到 `runtime_logs/`（`cv2.imread` 走不了中文路径，文件名用 ASCII）。
3. 跑生成器（本地探针，**被 `.gitignore` 排除**，与
   `runtime_logs/_wb_chest_build_assets.py` 同惯例）：

   ```
   D:/anaconda/python.exe auto_game_unified/runtime_logs/_make_support_digits.py
   ```

   脚本里 `FRAMES` 是帧、`LABELS` 是**肉眼读出来的**「持有 / 需求」真值。
   它自己会断言「切出的字形个数 == 标注位数」，对不上就报错 —— 所以标注错了一定会被拦下。
4. 换新帧时同步改 `FRAMES` / `LABELS`，并把新帧补进 `tests/fixtures/`（见下节登记）。
5. **肉眼复核**产物：`docs/manual_review/knights_donation/support_digits_sheet.png`
   （六个字模放大 5 倍拼图），确认是清晰的 `0 1 2 3 4 5`。
6. 跑测试（见文末）。

⚠️ 生成器在 `runtime_logs/` 里、不进仓库 ⇒ **全新克隆里没有这个脚本**，
届时要按上表（帧 / 行 y / 持有 / 需求）手工重建，或照 `_make_support_digits.py` 的
思路重写一遍（它只复用了生产常量与 `glyph_boxes` / `normalize_glyph` / `green_mask` / `white_mask`，
没有自己的私有逻辑）。

## 改模板 / 加夹具时别忘了登记

1. `tests/test_project_layout.py::test_epic7_knights_donation_fixture_set_exists`
   断言这个路线夹具的**精确文件集** ⇒ 加/删夹具必须同步改，否则测试红。
2. `tools/check.py::ROUTE_KEYWORDS` 按**文件名 stem** 认路线 ⇒ 新增
   `games/epic7/*.py` 必须登记，否则定向判定会安静地退回全量跑
   （`knights_support_digits` 已登记）。
3. 加**新路线**（不是新文件）还要动 `games/epic7/modes.py`、`desktop/catalog.py`、
   `launcher.py` 三处 —— 见 `AGENTS`/项目记忆里的「新增路线登记四处」。

## 守这两条判据的测试

```
D:/anaconda/python.exe -m pytest auto_game_unified/tests/test_knights_support_digits.py \
    auto_game_unified/tests/test_knights_donation.py -q
```

- `test_knights_support_digits.py`：字模齐备（缺一个就在加载期报错）、5 行真帧逐行读数、
  事故帧被判「不足」、同帧两个可读行分得开、识别稳定（问两次同结果）、
  认不出返回 `None`（无字模 / 实心色块 / 无文字区域 / 非基准分辨率弃权）、
  **阈值坐在「正确匹配最低分」与「错配最高分」之间**、三态语义。
- `test_knights_donation.py` · 材料判据：四个分支（不足不点 / 真帧跳格 / 读不出照旧点 /
  全不足就下滑）。
- `test_knights_donation.py` · 请求支援灰按钮：灰了不点且照常往下走 / 还亮着照旧请求 /
  量不出来当作还亮着 / **整屏压暗到 30% 仍分得开** / **阈值坐在两组之间且两侧余量 >25%** /
  两种底色读数一致。
- **两条「真 Runner 级」用例**（各一个）：
  `test_the_short_material_row_is_never_clicked_by_the_real_runner` 与
  `test_the_greyed_request_button_is_never_clicked_by_the_real_runner`。
  它们是**唯一**守住「判据真的接进了主循环」的测试：2026-09-25 那两次事故都发生在
  **状态机与主循环之间**，单测状态机抓不到。改路由 / 改主循环相关的东西，**必须**跑过。
- 换 `templates/knights_donation/` 下的模板、`digits/` 字模或 `REGIONS` 里的区域，
  除上面两个文件外还要跑路线级夹具回归（`test_knights_donation_resume.py`）。
