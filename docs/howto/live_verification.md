---
topic: live-verification
when: 要跑 --live 实机、要点游戏里的按钮、或出现「截图正常但游戏不动」时
last_verified: 2026-11-08
review_when: 改了 core/elevation.py、core/pc_window.py、desktop/preflight.py、app.STARTUP_HINTS，或换过客户端
---

# 实机闭环验证：让 agent 自己动鼠标

> **什么时候看这份**：你要让 agent **真的点进游戏跑完一个业务闭环**，而不是只看测试通过。
> 这里只写「怎么做、失败了怎么判」。为什么这么定在 `core/elevation.py` 的模块注释里。

## 一、先跑自检，别猜

```powershell
python -m auto_game_unified.tools.live_check            # 两个后端都查
python -m auto_game_unified.tools.live_check --backend pc
```

它只做**只读**检查（不点击、不改窗口），输出三行：权限状态、各后端能不能抓到窗口、结论。
**绝大多数「点不动」在这一步就能定案**，不用去怀疑模板或坐标。

## 二、权限：谁需要提权

| 后端 | 需要管理员？ | 依据 |
|---|---|---|
| 模拟器（雷电） | **不强制** | 但若模拟器是管理员启动的、助手不是，点击会被静默拦掉（见下） |
| PC 客户端 | **必须** | `desktop/preflight.py` 的 PC 分支写明「客户端要求以管理员身份运行助手」，`app.STARTUP_HINTS` 里也是这句 |

**判据不是「大概像」**（摘自 `core/elevation.py`）：Windows 的 UIPI 规定**权限低的进程不能往权限高的窗口发输入**。
所以要读的是目标窗口所属进程令牌里的 `TokenElevation`，不是进程名、也不是用户名。
自己提权了就没问题（同级别之间不拦）。

**典型症状**（认准这三条同时出现）：

- 截图正常、识别正常
- 日志里每个动作都写「已点击」
- 游戏一动不动

看到这三条不要查模板、不要改坐标 —— 先跑 `live_check`。

**怎么提权**（用户不在旁边时也能自己完成）：

```powershell
Start-Process -FilePath python -ArgumentList `
  "-m","auto_game_unified.main","--mode","arena","--live","--confirm","RUN","--max-cycles","1","--window-backend","pc" `
  -Verb RunAs
```

`-Verb RunAs` 会让新进程拿到管理员令牌。**它会不会弹 UAC，取决于这台机器的设置**，见下一节。

（PC 客户端本身也用管理员启动，两边权限级别要**一致**。）

### UAC 到底会不会弹（别猜，看设置）

2026-11-08 实测本机：

```
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System
  EnableLUA                 = 1   （UAC 是开着的）
  ConsentPromptBehaviorAdmin = 0   （0 = 从不通知，静默提权）
  PromptOnSecureDesktop      = 0
```

`ConsentPromptBehaviorAdmin = 0` 意味着**管理员操作直接提升，不弹窗**。所以「请你点一下 UAC」
这句话在这台机器上是错觉 —— 脚本里写着，但从来没弹过，用户也从没点过。

⚠️ **反过来也不能假设「一定不弹」**：换台机器、或把 UAC 调回默认档，`-Verb RunAs` 就会弹窗，
而人在洗澡时它只会等到超时然后失败。所以：

- **唯一可靠的判据是实测** `elevation.current_process_elevated()`，不是「应该会弹/不会弹」；
- 无人值守**不要**设计成「弹个窗等人点」。要么事先把权限对齐（开机就用管理员启动），
  要么用不需要提权的后端（模拟器普通权限）。

### 无人值守时的铁律

用户说「你自己做闭环，我去洗澡了」时，按这三步走，**不要靠试**：

1. `live_check` —— 一次只读检查就能定案；
2. 不匹配就用上面那条 `-Verb RunAs` 命令重跑（本机静默生效，不需要人）；
3. 还是不行就**停下来写清楚**：需要什么权限、当前是什么权限、`live_check` 的原始输出。
   把结论留在日志里，比反复试十次有用。

用户明确抱怨过这种行为：*「试了一下，发现控制不了鼠标，要不然就停下来了，要不然就去各种尝试」*。
瞎试会浪费十几分钟，而且日志里看不出你在试什么。

## 三、一次实机怎么跑

命令行形状（`tools/_run_live_*_elevated.py` 就是这么调的）：

```powershell
python -m auto_game_unified.main --mode arena --live --confirm RUN --max-cycles 1 --window-backend pc
```

- `--live` + `--confirm RUN` 是**双保险**：少一个都只干跑。
- `--max-cycles 1` 先跑一局看闭环，别一上来就跑 10 局。
- `--window-backend pc` 走 PC 客户端；模拟器后端不传这个参数。

**跑完看哪里**：`runtime_logs/epic7_<mode>.log` 是过程；`runtime_diagnostics/epic7_<mode>/` 是
失败时的现场帧。退出码见 `docs/USER_GUIDE.md`。

## 四、`tools/` 下这几个一次性脚本是干什么的

它们都是 `_` 前缀（按项目约定 = 一次性），共同模式是「设好 `sys.argv` → 直接调 `main()` →
把结果写进 `runtime_logs/*.txt`」。留着是因为**当时的现场只有它们能复现**，不是常用入口。

| 脚本 | 用途 |
|---|---|
| `_run_live_hero_elevated.py` | 跑一轮英雄合成实机（PC 后端），结果写 `hero_pc_step.txt` |
| `_run_live_story_elevated.py` | 跑一轮主线实机（PC 后端） |
| `_verify_pc_input_elevated.py` | 验证「点星星 3 星卡」这一下到底有没有生效，连拍 3 张帧 |
| `_verify_hero_tab_elevated.py` | 验证英雄详情页切页签后的画面 |
| `_diagnose_pc_activation_elevated.py` | 诊断「能不能把 PC 窗口切到前台」，输出前台窗口详情 |

要新增场景，**别再加第六个**：优先用第三节那条命令行。

## 五、失败怎么判

| 现象 | 病因 | 下一步 |
|---|---|---|
| 截图正常、日志说已点击、游戏不动 | UIPI 拦输入（权限不对等） | `live_check` → 统一权限级别 |
| `PreflightStatus.BLOCK: 实际找到 0 个窗口` | 游戏/模拟器没开，或标题不匹配 | 把游戏开到大厅再跑 |
| 画布尺寸不是 1982×1132 | 模拟器分辨率被改过 | 恢复 1982×1132 后再跑 |
| 能点但点错位置 | 这才是坐标/模板问题 | 走 `docs/TEMPLATE_CAPTURE.md`，不要动权限 |

## 六、这份文档怎么维护（重要）

**这类知识会以第三种方式过期**：不是代码变了，而是**当时的判断变了**（比如哪天发现不必提权）。
没有 diff、没有报错、没有测试会变红，所以必须靠人主动改。为此定四条：

1. **一个主题只有这一份文件。** 想到更好的做法时，**改这里**，不要另开
   `live_verification_v2.md` / `实机验证新方案.md` —— 两份并存时，下一个人不知道该信哪份，
   而 agent 极可能挑到旧的那份，把你踩过的坑再踩一遍。
   （`docs/howto/` 下每个文件的 frontmatter `topic` 必须唯一，门禁会查。）
2. **改的时候留一行「更改记录」**（见文末表），写清日期、改了什么、依据。
   这样"覆盖"是看得见的，历史也不丢。
3. **旧做法不要直接删，留一行墓碑**，写明「已作废（日期）：原做法 X，因为 Y，现在看 Z」。
   原因很实在：下一个人（或 agent）可能记得旧做法，会去搜那些旧词 ——
   搜到墓碑就知道「这条路走不通了」，而不是搜不到就自己再试一遍。
4. **每条做法都要带「依据」和「怎么复核」**。依据是当时实测的事实（报错原文、日志、数值），
   不是「我觉得」。没有依据的做法会被下一个人当迷信删掉 —— 那也是一种损失。
   能写成命令的就写成命令（例如第一节那个 `live_check`）。**不要写「请定期复核」**，没人执行。

### 更改记录

| 日期 | 改了什么 | 依据 |
|---|---|---|
| 2026-11-08 | 建档。此前这些知识只存在于 `core/elevation.py` 的注释和几次会话里，没有入口 | 用户反馈「同样的问题两三天后被另一个 agent 再问一遍」 |
| 2026-11-08 | 补「UAC 到底会不会弹」与「无人值守铁律」，并把 `Start-Process -Verb RunAs` 写成可复制的命令 | 用户反馈「脚本说要点 UAC，但我从没点过、每次都成功」。查注册表：`ConsentPromptBehaviorAdmin=0`（从不通知，静默提权）—— 那句提示从来没兑现过 |
| 2026-11-08 | 实跑前加闸门：`--live --window-backend pc` 时先查窗口与权限，不通过就拒绝并指向本文件 | 只有 2 条路线配了运行前闸门，其余在权限不对时会跑下去，表现成「日志说已点击、游戏不动」 |
