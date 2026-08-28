# 竞技场视觉维护

## 先看哪里

竞技场视觉证据唯一维护入口：`games/epic7/evidence/arena.py`。

模板文件位于 `games/epic7/templates/`；固定截图和流程回放位于 `tests/fixtures/epic7_arena/` 与现有竞技场测试。

## UI 改版时怎么改

1. 从失败诊断中的 `key=` 找到证据键名。
2. 先替换对应模板文件。
3. 只有按钮位置变化时，才修改 `REGIONS` 中该键的区域。
4. 只有新旧画面外观造成分数变化时，才修改 `THRESHOLDS`；不得为了通过单张截图盲目降低阈值。
5. 页面组合变化时，修改同文件中的 `PageEvidence`，并同时增加反例测试。
6. 运行：`python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png`。
7. 再运行竞技场专项测试和完整回放。

业务流程和资源安全规则仍在 `games/epic7/arena.py`，不能因为模板失效就先改状态机。
