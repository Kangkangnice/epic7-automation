# 第七史诗自动助手

这是一个免费开源、基于窗口截图和 OpenCV 模板匹配的《第七史诗》PVE 前台自动化项目。英雄合成为当前正式功能；其余五种模式仍为实验功能，可能不稳定：

- `story`：主线/刷图循环，处理辅助英雄、剧情跳过、多段战斗、好友申请、奖励和结算。
- `arena`：新手竞技场循环，失败后跳过红色对手并从剩余对手中随机选择；三名对手均失败时执行免费刷新。处理战斗结算、段位提升等弹窗，并禁止危险的钻石购买路径。
- `expedition`：从大厅进入远征队，固定选择三阶段；每张传单只战斗一次，未击退时公开招募。
- `fodder`（狗粮）：固定进入“特别的时间之书”Episode 3-7，结算后通过“重新进行”循环刷图；体力不足时只使用生命之叶。
- `assist_auto`（助手自动）：接管游戏内置重复战斗，监控整组自动战斗并安全衔接下一轮。
- `hero_synthesis`（英雄合成）：逐个检查英雄，优先保护 SSS，安全添加材料或传送已达 SSS 的无用副本。

项目采用失败关闭策略：只在当前截图中识别到预期页面和按钮时点击；未知页面、黑屏、遮挡或转场超时都会保存现场并停止。

## 桌面界面（推荐）

当前源码版已经提供“第七史诗自动助手”中文桌面界面，可选择路线和次数、检测雷电环境、开始/安全停止、查看实时日志并导出诊断包：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.desktop
```

英雄合成在界面中标记为正式功能并固定运行一轮，其他五条路线标记为实验功能并在启动前提醒。桌面 MVP 当前只提供模拟器后端；Windows 安装包和便携版将在后续打包阶段提供。CLI 和中文交互式启动器继续保留给开发调试。

## 文档

- [使用手册](docs/USER_GUIDE.md)
- [架构说明](docs/ARCHITECTURE.md)
- [页面转场契约](docs/TRANSITION_CONTRACTS.md)
- [自动化稳健性待办](docs/TODO.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [截图与模板采集](docs/TEMPLATE_CAPTURE.md)
- [PC 模板迁移与实证流程](docs/PC_TEMPLATE_MIGRATION.md)
- [用户操作、AI 只读观测协作流程](docs/HUMAN_AI_WORKFLOW.md)
- [新增自动化路线](docs/EXTENDING.md)

## 环境要求

- Windows。
- 雷电模拟器中的《第七史诗》，窗口标题为“第七史诗”。
- Python 3.10 或更高版本。
- 当前模板基准画面为 `1982 x 1132`。

建议把仓库克隆为 `auto_game_unified`，并从它的父目录运行模块：

```powershell
cd D:\AI\codex\auto_game
git clone https://github.com/Kangkangnice/epic7-automation.git auto_game_unified
python -m pip install -r auto_game_unified\requirements.txt
```

窗口可以在桌面上移动。程序每次截图和点击前都会重新读取窗口位置，并把窗口局部坐标转换为屏幕坐标。窗口必须保持与模板相同的宽高比；游戏 UI、显示缩放或模拟器尺寸变化后，应先重新校准模板。

## 中文交互式启动

不需要记命令参数，运行下面的命令即可依次选择功能编号和运行次数：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.launcher
```

菜单顺序为：

1. 主线
2. 竞技场
3. 远征
4. 狗粮（特别的时间之书 3-7）
5. 助手自动
6. 英雄合成

选择模拟器或 PC 后端，再输入正整数次数，程序会直接以前台实跑方式启动；英雄合成固定执行一轮。按 `P` 可以随时停止。PC 后端目前仅用于开发和证据采集，六条路线均未完成 PC 实机迁移验收，详见 [PC 模板迁移与实证流程](docs/PC_TEMPLATE_MIGRATION.md)。

助手自动从当前受支持的战斗页面接管，不走大厅导航。英雄合成通过 CLI 实跑时未填写 `--max-cycles` 也会安全默认为 `1`，仍建议显式写出该参数。

## 干跑诊断

默认是不点击鼠标的干跑，只识别并打印当前状态的第一步：

```powershell
cd D:\AI\codex\auto_game
python -u -m auto_game_unified.main --mode story
python -u -m auto_game_unified.main --mode arena
python -u -m auto_game_unified.main --mode expedition
python -u -m auto_game_unified.main --mode fodder
python -u -m auto_game_unified.main --mode assist_auto
python -u -m auto_game_unified.main --mode hero_synthesis
```

`--start-state` 仅用于干跑诊断。状态必须属于对应模式，实跑传入该参数会被拒绝：

```powershell
python -u -m auto_game_unified.main --mode story --start-state active
python -u -m auto_game_unified.main --mode arena --start-state battle
python -u -m auto_game_unified.main --mode expedition --start-state outcome
python -u -m auto_game_unified.main --mode fodder --start-state replay
```

## 前台实跑

实跑必须同时提供：

- `--live`：允许执行鼠标点击。
- `--confirm RUN`：明确确认实跑。
- 正整数 `--max-cycles`：本次最多完成的循环数。

先运行一轮：

```powershell
python -u -m auto_game_unified.main --mode story --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode arena --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode expedition --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode fodder --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode assist_auto --max-cycles 1 --live --confirm RUN
python -u -m auto_game_unified.main --mode hero_synthesis --max-cycles 1 --live --confirm RUN
```

确认一轮稳定后再增加次数：

```powershell
python -u -m auto_game_unified.main --mode story --max-cycles 10 --live --confirm RUN
python -u -m auto_game_unified.main --mode fodder --max-cycles 10 --live --confirm RUN
```

自动化期间游戏独占前台，不要操作鼠标键盘或覆盖模拟器窗口。随时按 `P` 键可以手动停止，退出码为 `130`。

## 启动和循环完成规则

实跑会先从已支持页面受控返回大厅，再进入目标路线。状态必须连续两帧稳定后才允许操作；点击后还要重新识别目标页面，不能以“已经点击”代替“转场成功”。

三条路线共用同一套战斗安全边界：

- 模式自己的“战斗开始”点击一经执行，立即进入已承诺战斗阶段。
- 稳定识别到结算锚点以前，禁止返回大厅和执行 `Back`，恢复流程也会被统一恢复锁拒绝。
- 只有明确识别为 `MANUAL` 时才会点击一次自动战斗；`UNKNOWN` 永远不会触发自动战斗点击。
- 战斗中每 30 秒输出一次心跳。黑屏、未知画面、无活动或绝对超时会保存失败诊断并以退出码 `1` 安全停止。
- 导航、队伍、剧情、战斗或结算出现已知“网络连接异常”弹窗时，统一截图守卫会在连续两帧确认后最多点击两次重试；处理期间暂停业务超时。第二次后弹窗仍持续 15 秒则保存 `network_retry_failed` 诊断并以退出码 `1` 停止，不盲目返回大厅。

循环只在重新看到稳定入口时计数：

- 主线：结算和插入弹窗全部处理完，重新看到下一关入口。
- 竞技场：完成一次挑战并重新回到对手列表；胜利和失败都计一次，刷新对手列表不计数。
- 远征：重新回到远征主页并看到右下角“我的通缉传单”。传单角标数字可能动态增加，不参与计数。
- 狗粮：结算确认后稳定看到“重新进行”。达到目标次数时停在该页面，不再开启下一轮。
- 助手自动：完成游戏内置的一整组重复战斗并重新进入受监控的自动战斗流程。
- 英雄合成：完成一个英雄的合成或 SSS 副本处理事务；点击、动画和页面进入本身都不计为业务完成。

## 日志、截图和退出码

- 终端会即时输出中文动作日志。
- 文件日志：`runtime_logs/epic7_<mode>.log`。
- 当前监控帧：`runtime_diagnostics/epic7_<mode>/current.png`。
- 失败诊断：`runtime_diagnostics/epic7_<mode>/` 下带原因和时间的截图。

退出码：

- `0`：达到目标循环数。
- `1`：未知页面、超时或运行故障。
- `2`：已允许的资源耗尽停止。
- `130`：用户按 `P` 手动停止。

运行日志和诊断图属于本机产物，已被 Git 忽略；离线回归使用的 `tests/fixtures/` 不能删除。

## 安卓结束通知（PushPlus）

实跑达到目标次数、因允许的资源耗尽停止或发生运行故障时，可以通过 PushPlus 向微信发送一条通知。离线诊断和按 `P` 手动停止不会通知。

1. 登录 PushPlus，完成实名认证并取得用户 Token 或消息 Token。
2. 仅对当前 PowerShell 窗口启用：

   ```powershell
   $env:EPIC7_PUSHPLUS_TOKEN = "你的 Token"
   ```

3. 永久保存到当前 Windows 用户环境变量：

   ```powershell
   setx EPIC7_PUSHPLUS_TOKEN "你的 Token"
   ```

   `setx` 后需要关闭并重新打开终端才会生效。

Token 不要写进仓库文件、日志或聊天记录。未配置 Token 时，自动化仍会正常运行，终端会提示通知未启用。PushPlus 接口返回成功只代表平台接受了异步发送请求；手机最终投递仍取决于 PushPlus、微信和当前网络。

## 测试

在仓库目录执行：

```powershell
python -m pytest -q
python -m compileall -q .
```

测试覆盖状态流、循环计数、慢转场、重复帧、剧情与奖励插入、自动战斗识别、弹窗处理、资源反例、萤火待机唤醒和公开招募后的双层返回。

真实模拟器验收全部由用户启动、观察和停止。AI 只运行离线测试，并根据用户提供的日志和截图分析问题；每次修复前先增加能够复现现场的离线回归测试。

## 当前限制

- 不支持后台运行，自动化期间游戏必须保持前台。
- 远征首版固定选择三阶段，没有难度参数。
- 远征“传单耗尽”和“首领已击退”页面尚未取得当前客户端素材；遇到时会安全留证停止，不能用旧客户端图片冒充支持。
- 狗粮首版固定为“特别的时间之书”Episode 3-7，不提供其他关卡参数；入口要求客户端已保留该 Episode 的 3-7 选择状态。
- PC 后端与候选模板尚未达到路线支持标准；必须逐路线完成固定样本、干跑、一轮和两轮实机验收。
- 游戏更新后 UI 可能改变。新增页面必须先保存现场、加入离线回归，再修改识别逻辑。
- 不承诺未来版本的绝对识别率；交付标准是已采集页面零盲点、失败关闭和可重复离线回归。

## 安全原则

- 所有点击必须由当前截图的预期元素触发。
- 每个模板都有搜索区域，禁止在整屏盲找相似按钮。
- 未确认资源类型和价格时禁止购买。
- 未知页面只允许受控恢复或保存诊断停止。
- 看不懂真实页面时先询问用户，不重复猜测或连续试点。
