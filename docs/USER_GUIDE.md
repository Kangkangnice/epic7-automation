# 使用手册

本手册面向日常运行和故障留证。默认支持基线是 Windows 上的雷电模拟器前台窗口；`pc` 后端目前用于采集和开发验证，六条路线都尚未完成 PC 实机验收。

## 1. 安装与运行前检查

要求：

- Windows；
- Python 3.10 或更高版本；
- 已安装 `requirements.txt` 中的依赖；
- 模拟器中的《第七史诗》窗口标题为“第七史诗”；
- 模板基准画面为 `1982 x 1132`，窗口宽高比、游戏 UI 和显示缩放没有在采集模板后改变；
- 游戏窗口处于前台，运行期间不被其他窗口遮挡。

建议从仓库父目录安装和启动：

```powershell
cd D:\AI\codex\auto_game
python -m pip install -r auto_game_unified\requirements.txt
python -m auto_game_unified.main --help
```

第一次运行或游戏更新后，先执行干跑。只有识别结果与当前页面一致时才进行一轮实跑。

## 2. 桌面界面（推荐）

先启动雷电模拟器并进入《第七史诗》，再从仓库父目录启动中文桌面界面：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.desktop
```

桌面界面提供：环境检测、六路线选择、运行次数、开始/安全停止、实时日志、打开日志/诊断目录和一键导出诊断 ZIP。英雄合成、主线、竞技场与远征为正式功能；英雄合成固定运行一轮。狗粮和助手自动为实验功能，启动前会提醒可能不稳定。

进入界面后点击一次“检测环境”。检测通过后切换功能不会要求重复检测；点击“开始运行”时，助手会在后台自动快速复检模拟器和截图，并校验所选路线资源。复检失败时不会启动自动化。

当前是源码桌面 MVP，仍需要先安装 Python 依赖；Windows 安装包和便携版属于下一阶段。GUI 只显示已经验收的雷电模拟器后端，不提供 PC 客户端入口。开始按钮在环境检测通过前保持禁用。

## 3. 六种模式

| 模式参数 | 中文名称 | 作用 | 轮次含义 |
|---|---|---|---|
| `story` | 主线 | 主线/刷图循环和相关弹窗处理 | 完成结算并重新看到下一关入口 |
| `arena` | 竞技场 | 选择对手、战斗、失败轮换与免费刷新 | 完成一次挑战并回到对手列表 |
| `expedition` | 远征 | 进入远征、选择三阶段、战斗和公开招募 | 回到远征主页并看到“我的通缉传单” |
| `fodder` | 狗粮 | “特别的时间之书”Episode 3-7 重复刷图 | 结算后稳定看到“重新进行” |
| `assist_auto` | 助手自动 | 从当前受支持战斗页面接管自动战斗流程 | 由该模式的战斗完成条件确认 |
| `hero_synthesis` | 英雄合成 | 逐个检查英雄，安全合成或处理已达 SSS 的副本 | 一次完整的英雄处理事务 |

英雄合成启动器固定执行一轮完整扫描；其他模式由用户输入正整数轮次。

## 4. 交互式启动

最简单的方式是运行中文启动器：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.launcher
```

依次选择：

1. 模式（主线、竞技场、远征、狗粮、助手自动或英雄合成）；
2. 窗口后端（模拟器或 PC）；
3. 运行次数（英雄合成除外，固定为一轮）。

启动器会以前台实跑方式执行。运行期间不要操作鼠标键盘或覆盖游戏窗口，随时按 `P` 安全停止。

## 5. 干跑诊断

干跑只截图、识别并输出当前状态的第一步，不执行点击，也不需要 `--live`：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.main --mode story
python -u -m auto_game_unified.main --mode arena
python -u -m auto_game_unified.main --mode expedition
python -u -m auto_game_unified.main --mode fodder
python -u -m auto_game_unified.main --mode assist_auto
python -u -m auto_game_unified.main --mode hero_synthesis
```

`--start-state` 只用于离线/干跑诊断，必须是对应模式允许的状态。实跑时传入该参数会被拒绝。

## 6. 模拟器前台实跑

实跑必须同时提供 `--live`、`--confirm RUN` 和正整数 `--max-cycles`。先从一轮开始：

```powershell
python -u -m auto_game_unified.main --mode story --window-backend emulator --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode arena --window-backend emulator --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode expedition --window-backend emulator --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode fodder --window-backend emulator --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode assist_auto --window-backend emulator --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode hero_synthesis --window-backend emulator --max-cycles 1 --live --confirm RUN
```

一轮完整通过后，再增加 `--max-cycles`。不要用“连续点击了多次”判断完成轮次；程序只在对应业务闭环证据成立后计数。

模拟器战前页出现系统赠送的“快速战斗”时，不需要手动处理。主线、竞技场、远征、狗粮和助手自动会先确认快速按钮与白底切换键，再切回普通战斗并继续。该处理目前不适用于仍在开发中的 PC 后端。

## 7. PC 后端（开发中）

`--window-backend pc` 已提供窗口接入能力，`templates_pc` 也可能包含候选模板或样本，但这两点都不代表路线已经支持 PC。当前六种模式均未完成 PC 固定样本、dry-run、1 轮和 2 轮实机验收。

只在采集/验证场景使用 PC 干跑：

```powershell
python -u -m auto_game_unified.main --mode story --window-backend pc
python -u -m auto_game_unified.main --mode hero_synthesis --window-backend pc
```

在 [PC 模板迁移清单](PC_TEMPLATE_MIGRATION.md) 对应路线全部通过前，不建议执行 PC `--live`。候选模板不能代替真实 PC 截图证据。

## 8. 运行期间如何判断是否正常

正常的动作日志应体现以下顺序：

```text
动作候选 → 执行点击 → 等待确认 → 转场确认 → 业务成功
```

点击后暂时没有反应时，程序应保留原目标进行受限重试；只有目标页面或业务结果证据出现后才会记录成功。动态立绘、呼吸动画和局部粒子变化不能单独证明英雄已经切换。

竞技场会在原页面连续存在时用同一坐标最多尝试四次；一旦确认原页面已经离开，就只等待目标页面，不再点击旧坐标。对手详情、队伍页、刷新后的安全列表和结算返回列表都需要连续两帧才能提交状态。

竞技场无论第一轮就没有旗帜，还是运行中途耗尽，都会在点击“战斗开始”后处理同一个购买弹窗。购买框出现第一帧时程序立即冻结背景“战斗开始”，连续两帧确认后才进入购买判断，不会透过半透明遮罩重复点击旧按钮。

竞技场旗帜不足时，只允许左侧已选中的 `100 友情点 → 5 旗帜`。程序不识别会变化的“持有”余额；右侧 `30 钻石 → 5` 永久禁止。合法弹窗证据不完整时会保存现场并按资源不足停止，不会猜测购买。

进入战斗后不需要等到我方获得行动回合。模拟器版会根据右上角“自动关闭”图标请求开启自动，右下角人物头像稳定出现后才确认成功。敌方连续行动或技能动画导致头像暂时不可见时，日志会记录“来源已离开、人物头像待确认”并继续等待，不会再因 15 秒内看不到我方技能而报错。

如果页面证据不足，正确行为是记录 `UNKNOWN`、保存诊断并安全停止，而不是继续猜测点击。详细判定规范见 [页面转场契约](TRANSITION_CONTRACTS.md)。

## 9. 停止、退出码与通知

- 按 `P`：用户手动停止，退出码 `130`；
- `0`：达到目标轮次；
- `1`：未知页面、转场超时或运行故障；
- `2`：允许的资源耗尽停止。

可选 PushPlus 通知通过环境变量启用：

```powershell
$env:EPIC7_PUSHPLUS_TOKEN = "你的 Token"
```

不要把 Token 写入仓库、日志或聊天记录。返回码 `905` 表示 PushPlus 账户未完成实名认证；它不会改变自动化本身的运行结果，需要在 PushPlus 侧完成认证或停用通知。

## 10. 日志与诊断文件

- 文件日志：`runtime_logs/epic7_<mode>.log`；
- 当前监控帧：`runtime_diagnostics/epic7_<mode>/current.png`；
- 失败诊断：`runtime_diagnostics/epic7_<mode>/` 下带时间和原因的截图；
- 离线回归样本：`tests/fixtures/`，这些文件属于测试证据，不要当作运行垃圾删除。

反馈故障时，请至少保留：完整错误前后日志、最终诊断截图、运行模式、窗口后端、当时肉眼看到的页面和是否发生过真实点击/消耗。

## 11. 常见问题

### 点击切换英雄后没有反应

先看日志是否出现“等待确认”和受限重试。如果日志直接写成功但页面没变，应保留完整日志和诊断；这是转场证据与日志语义需要审计的信号。不要连续手动点击干扰现场。

### 两个英雄副本长得完全一样

不能依赖立绘差异。识别应观察点击后的动态过程、中心选中框/列表状态以及切换完成后的稳定页面；动态区域只提供辅助证据，不能单独确认成功。

### 识别到 SSS 后为什么退出

SSS 表示目标英雄已经达到最高合成等级。正确业务分支是退出合成，并在后续页面对无用副本执行受保护的传送流程；材料选择前必须优先完成 SSS 安全判断。

### 游戏更新或分辨率改变后大量 UNKNOWN

停止实跑，先保存现场并执行干跑。按 [截图与模板采集](TEMPLATE_CAPTURE.md) 重新采集模板，为新页面补固定样本和回归测试，不要降低阈值后直接实跑。

### 战斗开始按钮变成快速战斗

这是系统赠送快速战斗次数覆盖了普通按钮。模拟器版会自动点击右侧切换键回到普通战斗；日志应依次出现 `switch-to-normal-battle`、普通战斗开始动作和战斗监管。若没有切换，保留当前截图与完整日志，不要手动连续点击。

### PushPlus 通知失败但流程已经结束

通知属于附加能力，不参与业务成功判断。根据终端退出码和自动化日志判断流程结果，再单独处理 PushPlus 账户或网络问题。

更多故障定位步骤见 [故障排查](TROUBLESHOOTING.md)，后续路线审计项见 [自动化稳健性待办](TODO.md)。

## 12. 安全边界

- 所有点击必须由当前截图中的预期页面和元素触发；
- 关键模板缺失、证据冲突或状态未知时危险动作失败关闭；
- 不确认资源类型和价格时不购买；
- 已确认的不可逆动作不因回执识别失败而盲目重复；
- 实机控制必须由用户明确授权，且游戏窗口保持前台；
- 修改识别逻辑前，先用现场截图建立可复现回归测试。
