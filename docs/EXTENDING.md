# 新增自动化路线指南

本指南面向后续接手的 Agent。新增路线时保持修改范围最小，不重构已通过实机验证的竞技场和主线模块。

## 1. 先手动走完整流程

记录每个稳定页面、可选页面、加载边界、停止条件和循环完成标志。保存完整游戏窗口截图，不要只保存按钮裁剪。协作过程遵循 [HUMAN_AI_WORKFLOW.md](HUMAN_AI_WORKFLOW.md)，素材规则遵循 [TEMPLATE_CAPTURE.md](TEMPLATE_CAPTURE.md)。

必须明确：

- 从哪个页面启动。
- 每一步点击前能识别什么唯一元素。
- 哪些页面可选或可能重复出现。
- 何时开启 Auto，是否会跨波次保持。
- 何时才算一轮完成。
- 资源不足时是正常停止还是故障。

## 2. 文件约定

假设新模式名为 `hunt`：

```text
games/epic7/hunt.py
games/epic7/templates/hunt/*.png
tests/fixtures/epic7_hunt/*.png
tests/test_epic7_hunt.py
tests/test_hunt_runner.py
```

`hunt.py` 至少包含：

- `HuntState(Enum)`：稳定页面/等待阶段。
- `HuntAction`：动作名称与全局坐标。
- `HuntTemplates` 和 `build_hunt_templates()`。
- `HuntStateMachine.next_action(screen)`：纯视觉决策，不直接点击。
- `HuntRunner.run(max_cycles)`：轮询、超时、日志和安全停止。

## 3. 先写截图流程测试

用完整实测截图按真实顺序驱动状态机。测试至少断言：

- 动作名称和坐标顺序准确。
- 未知全黑图不会产生点击。
- 可选页面出现和不出现都能继续。
- 两轮连续流程只在入口重新出现时计数两次。
- 正常资源耗尽不会执行购买动作。

如果修复某个实机失败，必须把失败截图加入 `tests/fixtures`，先写一个会失败的回归测试，再改模板或状态机。

完整 fixture 是复现证据，局部 template 是识别输入，两者不能互相替代。新增页面没有当前客户端完整截图时，保持安全停止并写入限制清单。

## 4. 注册模式

在 `games/epic7/modes.py` 中增加一项 `ModeSpec`：

```python
"hunt": ModeSpec(
    name="hunt",
    default_state=HuntState.ENTRY.value,
    states=frozenset(state.value for state in HuntState),
    build_machine=_build_hunt,
    runner_type=HuntRunner,
),
```

构建器只负责载入模板和把字符串转换为该模式的 Enum。不要在 `main.py` 添加新的条件分支。

## 5. 安全验收顺序

1. 运行全量离线测试。
2. 停在路线入口，运行默认干跑，确认只打印第一步。
3. `--live --confirm RUN --max-cycles 1` 验证一轮。
4. 保存遇到的新页面并补回归测试。
5. 至少实跑两轮，验证循环衔接。
6. 主动验证资源不足或结束条件。

实跑期间用后台进程运行，并按 10 至 15 秒查看日志；不要用几十秒的前台固定等待。状态超时时先看诊断截图，不要直接放宽全局阈值。

## 6. 代码检查表

- 模板搜索都有限定区域。
- 点击坐标不位于头像、购买或其他高风险控件。
- 动作名称可从日志直接理解。
- 每个状态有合理超时。
- 干跑未知页面立即失败并保存截图。
- 模式恢复状态只接受本模式 Enum。
- README 补充新模式命令和实机验证边界。

## 7. 远征路线的当前边界

- 首版固定选择三阶段，没有 `--difficulty` 参数。
- 一张传单只战斗一次；首领存活时公开招募，不重复挑战。
- 萤火待机页只点击中央安全区域唤醒，并验证真正 UI 出现；最多尝试两次。
- 公开招募后先返回远征队列表，再返回远征主页。
- 通缉传单角标不参与判断；只有远征主页锚点稳定出现才增加循环计数。
- 当前版本尚未采集传单耗尽和首领已击退页面，遇到未知画面时安全留证停止，拿到当前客户端截图后再补回归模板。
