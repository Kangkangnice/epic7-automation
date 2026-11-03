# 每日路线移植状态（2026-11-02 凌晨）

> 目标：把「每日」分组里剩下的六条路线移植到 PC 端。
> 主线（`story`）与竞技场（`arena`）已于 2026-11-01 移植完成并放行到界面。

## 一、现状矩阵

| 路线 | 业务滑动 | PC 模板可加载 | 可移植性判断 | 今晚进展 |
|---|---|---|---|---|
| `world_boss` 世界首领战 | 0 处 | ✅ 构建通过 | **可移植**：判据以颜色/几何为主（绿条比例、宝箱亮度），无紧阈值锚点 | 家底 + 离线构建已过，**待实跑** |
| `sanctuary` 圣域收菜 | 0 处 | ✅ 构建通过 | **可移植**：同上 | 家底 + 离线构建已过，**待实跑** |
| `shop_refresh` 刷书签 | 2 处 | — | 依赖 PC 滑动 | 滑动已实现（见下），**待实跑** |
| `knights_donation` 骑士团捐赠 | 1 处 | — | 依赖 PC 滑动 | 同上 |
| `labyrinth_stone` 迷宫强化石 | 2 处 | — | 依赖 PC 滑动 | 同上 |
| `community` 社区签到 | 108 处 | — | **不建议移植**：游戏内 H5 网页，画面是竖屏 1080×1920，判据与横屏完全不同（`community_pages` 那套）；PC 客户端里这层 WebView 是否可用、分辨率如何，都还没有实机证据 | 仅记录风险 |

## 二、今晚已经做完的

1. **PC 端补上了「滑动」**（此前是硬缺口：`main.py` 给 Runtime 传的是 `swipe=None`，
   四条路线一走到滑动就抛「未配置滑动动作」）。
   - 实现在窗口层 `core/pc_window.py`：`swipe()` + `_send_swipe()`
     （SendInput 按下 → 按 16ms 步长插值移动 → 抬起；中途不抬键，否则就成点击了）。
   - `main.py` 改成按窗口对象是否提供 `swipe` 来接线，不再硬编码平台判断。
   - 单测 3 条：坐标换算（画布 → 客户区要减顶部 52 补边）、顶部补边区拒绝、
     轨迹序列（按下/多次移动/抬起，中途不许出现抬起）。
   - ⚠️ **只做了离线验证，没有实机验收**（见第三节）。
2. `world_boss` / `sanctuary` 两条路线在 **PC 后端**下模板全部可加载（验收门槛第 1 条）。
3. 六条路线的家底：滑动调用点、模板目录、判据形态（见上表）。

## 三、唯一的阻塞点：实跑验收需要一次 UAC

- PC 客户端由 STOVE 启动器拉起，`STOVE.exe` 清单是 `requireAdministrator`
  ⇒ 游戏进程在**高完整性级别**运行。
- 本机自动化进程是普通权限 ⇒ Windows UIPI 会拦截键鼠注入
  ⇒ `Epic7PcWindow.ensure_render_size()` 直接拒绝运行（这是设计内的保护，不是 bug）。
- 解决方式只有一个：**以管理员身份启动自动化**（用户亲手点一次"是"）。
  桌面上的「第七史诗自动助手」快捷方式本身带 `RunAsUser` 标记，双击即提权；
  从命令行起则需要 `Start-Process -Verb RunAs`。

## 四、醒来后的三步（每条路线约 10 分钟）

```powershell
# 1) 起一条有界实跑（会弹一次 UAC）
Start-Process -FilePath 'D:\anaconda\python.exe' `
  -ArgumentList '-m auto_game_unified.main --mode sanctuary --window-backend pc --live --confirm RUN --max-cycles 1' `
  -WorkingDirectory 'D:\AI\codex\auto_game' -Verb RunAs -Wait

# 2) 卡住就看诊断帧 + 量分数（与实跑同一把尺）
python <技能>\scripts\score_atoms.py --route sanctuary --frame <诊断帧.png>

# 3) 按「修复决策树」处理：先看判据形态 → 落点名单 → 弹窗 → 才考虑补图
```

放行到界面（`desktop/catalog.py` 的 `PC_READY_ROUTES`）只在**两轮连续实跑通过**之后做，
并按 `docs/PC_TEMPLATE_MIGRATION.md` 第 3 节的验收门槛留证据。

## 五、调试口径与主线不同（预先看，省时间）

这两条路线的动作契约用的是**状态标签**，不是主线的页面名：

```python
target_pages=(state_label(WorldBossState.HOME), ...)     # world_boss
target_pages=(state_label(SanctuaryState.CLAIM_POPUP), ...)  # sanctuary
```

`world_boss` 的动作与落点：

| 动作 | 落点 |
|---|---|
| `open-all-chests` / `confirm-result` | HOME |
| `open-level-reward` | LEVEL_REWARD |
| `build-team` / `open-team-select` | TEAM_CONFIG / TEAM_SELECT |
| `auto-configure` / `battle-start` | BATTLE |

`sanctuary`：`open-forest`→FOREST、`claim-row`→CLAIM_POPUP、`dismiss-claim`→FOREST。

⇒ 实跑时若出现 `转场超时 动作=X 当前已确认页面=Y`，先看**Y 是不是某个 `state_label`
的中文名**，再回来看该动作的 `target_pages` 里有没有它。分诊逻辑与主线一致
（playbook §1④），只是"页面名"换成了"状态标签"。

判据侧风险较低：两条路线阈值都是 0.80，且文档记录了双向余量
（sanctuary：正例最低 0.9744 / 负例最高 0.5498），不是主线那种 0.88 的紧阈值。
