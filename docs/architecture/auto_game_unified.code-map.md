# 架构图节点 → 代码对照表

配套图：`docs/architecture/auto_game_unified.html`（由 `auto_game_unified.architecture.json` 渲染）
出处钉版：`8b0aeaadc72fdfdffb64b6fe748dc432f79d58bf`（下称 HEAD）

> 为什么是单独一张表：Archify 支持把每个节点挂到代码行并生成可点链接，
> 但它的校验要派生 `git` 子进程，本机 Node 被禁止创建子进程（详见
> `.workbuddy/memory/topics/env.md`），所以图里只保留了路径文字，精确行号放这里。

## 入口与启动方式

| 节点 | 文件 | HEAD 行 |
| --- | --- | --- |
| 交互入口 | `desktop/app.py` | 162 `DesktopApp` |
| main.py 装配与调度 | `main.py` | 290 `run_mode` |
| 每日任务编排 | `games/epic7/daily_tasks.py` | 147 `run_daily_tasks`、125 `ensure_at_lobby` |

（原先的 `launcher.py` 命令行编号菜单已删除，桌面助手是唯一交互入口。）

## 第七史诗专用 games/epic7/

| 节点 | 文件 | HEAD 行 |
| --- | --- | --- |
| 路线注册表 | `games/epic7/modes.py` | 455 `MODE_SPECS` |
| 6 条共享主循环 | `games/epic7/runner_base.py` | 37 `ModeRunnerBase` |
| 4 条自写循环 | `games/epic7/arena.py` | 1017 `ArenaRunner` |
| 4 条自写循环 | `games/epic7/shop_refresh.py` | 330 `ShopRefreshRunner` |
| 4 条自写循环 | `games/epic7/survivor.py` | 217 `SurvivorRunner` |
| 共用机制 | `games/epic7/navigation.py` | 141 `NavigationTemplates`（导航链的**执行器**） |
| 共用机制 | `games/epic7/navigation_plan.py` | 46 `NavigationPlan`（导航链的**声明式数据**） |
| 共用机制 | `games/epic7/global_popups.py` | 16 `NetworkReconnectTemplates` |
| 共用机制 | `games/epic7/finish_home.py` | 44 `_finish_home_verdict` |
| 战斗看护 | `core/battle_supervisor.py` | 70 `BattleSupervisor` |
| 战斗看护 | `games/epic7/battle_controls.py` | 27 `observe_battle_controls` |
| 视觉判据层 | `games/epic7/evidence/common.py` | 60 `EvidenceProfile` |
| 视觉判据层 | `games/epic7/evidence/knights_donation.py` | 271 `build_knights_donation_evidence` |

⚠️ 两个**还没提交**、因此没被钉进 HEAD 的文件（图里仍以文字提及，但表里不列行号）：
`games/epic7/home_return.py`（回家 v2）、`games/epic7/evidence/labyrinth_stone.py`（迷宫强化石判据）。

## 核心引擎 core/（与具体游戏无关）

| 节点 | 文件 | HEAD 行 |
| --- | --- | --- |
| 截图与识别 | `core/window.py` | 96 `Epic7Window` |
| 截图与识别 | `core/matcher.py` | 22 `load_template` |
| 时钟与稳定观测 | `core/runtime.py` | 41 `Runtime` |
| 时钟与稳定观测 | `core/supervisor.py` | 11 `StableObservation`、32 `Watchdog` |
| 逃生与通知 | `core/recovery.py` | 15 `RecoveryGate` |
| 逃生与通知 | `core/hotkey.py` | 7 `WindowsPStopHotkey` |
| 逃生与通知 | `core/qqbot.py` | 56 `send_qqbot_c2c` |

`python -m pdb` 之外的改动前必读：`core/**` 属共享模块，改完默认按文件名跑定向测试
（如 `core/matcher.py` → `test_matcher.py`）；要一次兜底再跑 `tools/check.py --full`。

## 重新生成这张图

```bash
cd auto_game_unified
node <archify>/bin/archify.mjs validate architecture docs/architecture/auto_game_unified.architecture.json --quality showcase --json
node <archify>/bin/archify.mjs deliver  architecture docs/architecture/auto_game_unified.architecture.json docs/architecture/auto_game_unified.html --quality showcase
```

本机跑不通上面两条（Node 创建子进程被拦），需要用单进程驱动；做法见
`.workbuddy/memory/topics/env.md` 的 Archify 小节。
