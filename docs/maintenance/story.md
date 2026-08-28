# 主线视觉维护

主线视觉证据入口：`games/epic7/evidence/story.py`。

模板位于 `games/epic7/templates/story/`。改版时按失败诊断中的证据键名替换模板；位置变化改 `REGIONS`，分数变化改 `THRESHOLDS`，可选页面或冲突证据改 `PageEvidence`。

跳过、体力、快速战斗、结算和下一关的业务顺序仍在 `games/epic7/story.py`，视觉迁移不得改变这些状态转移。
