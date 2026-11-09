# 仓库开发硬约束

> 只放**每次动手都必须知道**的硬约束（100 行内，太长会掉遵循率）；细节与真实案例在 `docs/`，每节末尾有链接。

## 文档与现状（先看这两页，别靠数代码猜）

- **现状**：`docs/STATUS.md` —— 路线名单 / PC 放行 / 每日任务顺序，**由代码生成**。
  想知道「现在支持哪些」看它，别数 `catalog.py`、也别信旧文档里的数字。
- **索引**：`docs/README.md` —— 「我要做 X 该看哪份」+ 文档各通道 + 写文档的规矩。

三条会被门禁拦下的硬规矩（不是建议，是测试）：

1. **不许手改 `docs/STATUS.md`**。它与代码不一致时 `tests/test_status_doc.py` 直接报红，
   报错里写着该跑哪条命令（`python -m auto_game_unified.tools.gen_status`）。
2. **新增任何 `.md` 必须登记在 `docs/README.md`**。`tests/test_docs_index.py` 检查
   `docs/` 下每个文档都能从索引点到 —— 没登记的文档等于不存在。
3. **「交接说明」「施工计划」「设计稿」不进仓库**。信息当场拆进提交信息 /
   `CHANGELOG.md` / `docs/decisions/`。理由见 `docs/decisions/0004-four-channels-for-docs.md`。

## 修改前必须阅读

修改任何视觉识别、点击、导航、重试、事务或路线前，必须阅读（适用于全部路线、模拟器与 PC 迁移）：

- `docs/TRANSITION_CONTRACTS.md`
- `docs/HUMAN_AI_WORKFLOW.md`
- **新增路线或新增动作**时读 `docs/EXTENDING.md`；**移植 PC / 改 PC 后端**时读 [`docs/PC_TEMPLATE_MIGRATION.md`](docs/PC_TEMPLATE_MIGRATION.md)
- **要实机跑闭环**时，读 `docs/howto/live_verification.md`（权限 / 点不动 / 失败判定）
- 目标路线测试和最新真实失败证据

## 做到一半要停（超时 / 被叫停 / 上下文用尽）

**先建交接单：复制 `docs/wip/_TEMPLATE.md` 到 `docs/wip/<日期>-<主题>.md`，填完再停。**

它会自动出现在 `docs/STATUS.md` 的「在制品」一节 —— 下一个人（或你换个会话）打开现状页
就知道有活没干完、做到哪、下一步做什么。**合并进 main 之后删掉它**，结论进提交信息 /
`CHANGELOG.md` / `docs/decisions/` / `docs/maintenance/<路线>.md`。

## 不可违反的视觉动作契约

每个改变页面、选择、资源或业务状态的动作都必须定义并验证**五段证据**：
来源进入 → 候选动作 → 来源退出 → 目标进入 → 业务完成。

点击永远不等于成功。来源退出不等于目标进入，目标进入也不等于业务完成。

点击后：

- 来源仍稳定存在：点击未生效，记录证据并在声明的额度内重试；
- 来源消失但目标尚未稳定：正在转场，只等待，不点击旧坐标；
- 目标稳定出现：转场确认；
- 证据缺失或冲突：记为 `UNKNOWN`，保存诊断并失败关闭。

来源仍被视觉确认时，禁止用一次性"已点击"标志阻止合理重试。不可逆动作的来源一旦消失，禁止再次执行。

## 证据先于代码

- 根据当前日志、完整截图、fixture 和量化数据诊断，不凭推测修改行为。
- 固定坐标必须由当前完整 fixture 验证，同一控件只保留一个共享常量。
- 每个真实故障先增加能复现现场原因的 fixture 回归测试，再改实现。
- 日志必须说明来源证据、尝试次数、来源退出结果、目标证据、关键分数或像素数和最终结论。
- 未知证据不得写成成功。

### 判据型模板不许静默降级

用来**判页 / 判危险 / 判覆盖层**的模板，**没有「可选」这一档** —— `if path.exists() else None`
会让判据在模板被删后悄悄消失（合成 / 传送消耗资源、不可逆）。

一条规矩要三样齐，缺一样当没做：**文档写清 + 代码门槛（构造期直接报错）+ 护栏测试**，
而且要用 AST 静态守 —— 真出问题的分支跑夹具到不了。

⚠️ 七个真实案例（远征 `empty_posters` 空等 6 次、多候选模板、多尺度死区三步法、
转场开关「挂着不等于生效」……）见
[`docs/TEMPLATE_CAPTURE.md`](docs/TEMPLATE_CAPTURE.md#判据型模板不许静默降级)，改判据前必读。

## 素材体积：入库前先压

新增或替换 `tests/fixtures/**` / `games/epic7/templates/**` 的图片，`git add` 之后、提交之前跑：

```powershell
python tools/compress_images.py --staged --apply && git add <刚压过的文件>
```

它是**无损**的（压完逐位比对像素，不一致就报错、不落盘）。⚠️ **不要拿它压存量再提交** ——
只会把新 blob 加进 pack，历史里旧 blob 一个不少。存量瘦身见
[`docs/TEMPLATE_CAPTURE.md`](docs/TEMPLATE_CAPTURE.md#入库前无损压缩体积门槛)。

## 完成规则

运行编译检查和**按改动范围选定的测试**；涉及真实游戏时，业务闭环没走完只能报离线结果
（局部通过不等于路线修好）。

## 验证门槛：改多少验多少，**同一次提交只跑一遍**

**提交那一次由钩子跑（`tools/githooks/pre-commit` → `tools/check.py`），不要再手工跑一遍。**
开发中途想看结果才手工跑：`python tools/check.py --files a.py b.py`（约 1~2 分钟）。
`--no-verify` **默认禁止**（钩子是唯一的强制关卡）；`--full` 只在 PR 合并 / 发布前用；
改共享模块最费时间，这类改动**攒在一起一次提交**，别拆成几次各跑一遍。

⚠️ 五个坑（`--vs HEAD` 会把上一轮未提交的改动算进来、手工跑完又改文件那次作废、
并发会话共用工作区时别 `git add -A`……）见
[`CONTRIBUTING.md`](CONTRIBUTING.md#几个容易踩的细节2026-11-08-从-agentsmd-移来)。
