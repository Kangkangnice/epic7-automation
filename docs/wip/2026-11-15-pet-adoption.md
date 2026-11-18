---
route: pet_adoption
status: in-progress
owner: WorkBuddy
started: 2026-11-15
next_step: 免费态 / 亮态购入 / 购买确认框均已接线；剩余 PC 迁移、「买满 3 次后转灰」收尾形态，以及 2026-11-17 购买确认框修复的实机复验
---

# 交接单：宠物领养路线首版，缺免费态素材

> 进行中的临时凭证，合并进 main 后删除。

## 一、现在做到哪一步

已按新增路线清单完成登记：状态机、证据层、10 张模板、8 张实机夹具、
23 条离线用例、导航链、界面分组与两个购入开关、维护手册。
离线整轮回放通过（宠物小屋 → 领养弹窗付费态 → 关弹窗 → 进商店 →
滑到底 → 收工），全库反向验证新模板无跨页误命中。
**实机闭环已过**：`--live --confirm RUN --max-cycles 1` 完整链路退出码 0；
停在半路开局接力命中并收尾回大厅退出码 0；
`--max-cycles 2` 两轮连续退出码 0（轮次=2、正常收尾）。
免费领养这一步今天无法验证（额度已用完）。

## 二、已经改了什么

| 文件 | 改了什么 / 为什么 |
|---|---|
| `games/epic7/pet_adoption.py` | 新建状态机 + Runner + 接力探针。付费态用券图标正向判定；认不出两态就安全停止，绝不点领养按钮 |
| `games/epic7/evidence/pet_adoption.py` | 新建判据、区域、阈值、页面组合、三行冷却逐行检出 |
| `games/epic7/templates/pet_adoption/*.png` | 10 张模板，全部避开会变内容（FPS / 红点 / 倒计时数字 / 券余额） |
| `games/epic7/templates/navigation/pet_house_entry.png` | 快捷菜单第 2 行中间「宠物小屋」入口图标 |
| `tests/fixtures/epic7_pet_adoption/*.png` | 8 张 2026-11-15 模拟器真机整屏帧 |
| `tests/test_pet_adoption.py` | 23 条护栏：页面识别、整轮动作顺序、计数幂等、安全停止、接力 |
| `games/epic7/modes.py` | 注册 `ModeSpec`、构建器、导航链、购入开关翻译钩子 |
| `games/epic7/navigation.py` | 新增页面身份 `pet_house`、入口锚点、区域、加载与 `observe()` 分支 |
| `games/epic7/route_options.py` | `buy_food` / `buy_toys` 两个开关，默认均「不购买」 |
| `desktop/catalog.py` | `ROUTES` 增「宠物领养」（每日组）、每日组说明补名单；**未**加进 `PC_READY_ROUTES` |
| `games/epic7/daily_tasks.py` | 按用户 2026-11-15 要求加进默认连打清单末尾（明知可能失败也要能测到，报错后按诊断帧采图） |
| `tools/check.py` | 路线关键字登记 |
| 护栏测试五份 + 文档 | 名单同步；手册、`README`、`STATUS`、`TODO`、`SAFETY_MATRIX`、`RESUME_COVERAGE`、`TRANSITION_CONTRACTS` |

## 三、没做完的是什么

- [x] 采「免费领养」按钮与「领养结果弹窗」整帧（2026-11-16，免费额度刷新当天）；
      三张模板入 `templates/pet_adoption/`，判据见状态机 docstring。
- [x] 加 `free_adopt_text` / `free_adopt_hint` / `adopt_result_title` 三个原子与
      `pet_adoption.adopt_result` 页面组合；结果页的关闭复用 `adopt_modal_close`。
- [x] `_at_adopt_popup` 改成三条证据（免费二字 / 提示条 / 券图标）的判定，
      新增 `adopt-free` 与 `dismiss-result` 两个动作；顺手纠正「券图标 = 已领完」的旧判据。
- [x] 采宠物用品「可购买」亮态整屏帧 + 购买确认框 + 购买后回列表（2026-11-16）。
      商品名两张模板（`supply_food_name` / `supply_toy_name`）、按行记账防回购，
      `open-purchase` / `confirm-purchase` 两个动作已接进转场契约；实机跑通「开框 → 确认 → 回列表
      → 收工」（退出码 0，购入一般饲料 1 件）。
- [x] **购买确认框误用企鹅数量弹窗模板的修复（2026-11-17）**：从默认连打报错的诊断帧重裁
      本路线三张锚点（标题 / 固定问句 / 绿「购买」），页面组合不再依赖遮罩下的商店标题；
      `purchase_modal.png` 夹具同步替换，`test_pet_adoption.py` 全绿。**实机复验待办**。
- [x] 跑 `--live --confirm RUN --max-cycles 1` 一轮与两轮连续实跑（2026-11-15，均退出码 0）。
- [ ] PC 客户端移植（按用户「PC 端 90% 沿用」原则，先采页、再换图）。
- [x] 把 `pet_adoption` 加进 `daily_tasks.DAILY_TASKS`（2026-11-15 用户要求，
      已放清单末尾）。用户口径：先放进默认清单便于实测；报错时按诊断帧采图修复，
      单条失败不会带崩整轮。首版「免费态未采到」已于 2026-11-16 补齐。
- [ ] 补图且 PC 实机通过后，把 `pet_adoption` 加进 `PC_READY_ROUTES`
      （放行需要真机凭据）。

## 四、下一个人第一步该干什么

> 下面两条采图步骤已于 2026-11-16 完成，保留作取证方法备查。当前第一步是
> 实机复验购买确认框修复：进宠物商店 → 开一单行购买 → 看绿「购买」是否被点掉、是否回到商店。

```
# 1) 免费额度刷新后，把游戏停在「领养宠物」弹窗，采整屏帧
python -m auto_game_unified.tools.capture_fixture free_adopt \
  --group epic7_pet_adoption
# 2) 点一次免费领养（这次是安全的：按钮带「免费」标记），采结果弹窗
python -m auto_game_unified.tools.capture_fixture adopt_result \
  --group epic7_pet_adoption
```

采完按「三」的清单接线。判据定阈值前先跑 `runtime_diagnostics/_probe_pet/validate.py`
那套全库反向验证，确认新模板正例过 0.80、跨页最高不过 0.80。
⚠️ 实机操作时**只点带「免费」标记的按钮**；付费态那两颗会消耗宠物领养券。

## 五、坑（试过但没用的）

- 标题模板最初从 x=20 起裁，把模拟器绿色 FPS 数字（会变）裁进去了。
  改成只取 x=100 起的四个中文字，避开 FPS 与返回箭头。
- 「11小时后可购买」如果连数字一起裁，明天小时数一变（11 → 3 / 23）
  模板就失效。改成只取「小时后可购买」固定文字 + 宽区域滑窗。
- 快捷菜单第 4 行「英雄休息室」也是房子图标。靠搜索区域只罩第 2 行
  那一格排除，全库实测那个图标只有 0.5610，形状也不同（爪印 vs 城堡窗）。
- 领养弹窗是半透明遮罩，底下小屋标题实测仍 0.9996。弹窗判定必须排在
  小屋之前，否则会对着被盖住的小屋按钮点。
- 「点击关闭」是全游戏通用控件，跨页同形可到 0.9971，不能拿它判页。
- **收工不要加「本轮已完成」永久锁**。第一版加了 `_finished`，单轮没事，
  `--max-cycles 2` 的第二轮等不到轮次递增、干等 64 秒报「等待画面[宠物商店]超时
  无进展」。主循环每帧先 `preview`（会还原进度）再真正提交一次，本来就不会重复
  计数 —— 按「圣域收菜」的同族写法去掉锁即可。`preview()` 快照仍须覆盖全部进度。
- **「滑到底」判据的搜索区域不能只罩第一次采集时那一行**。第二轮开局列表停在
  略高约 40px 的位置，`shop_supplies_section` 从 1.0000 掉到 0.2797，
  状态机误判「还没到底」又滑 3 次、越滑越偏。把区域放宽到整个商品列表后
  该帧 0.9878、正常底部 1.0000、未滑帧 0.4242，0.80 门槛两侧余量足。
  诊断帧已存为 `shop_bottom_scrolled.png` 回归夹具。
