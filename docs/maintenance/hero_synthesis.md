# 英雄合成视觉维护

英雄合成视觉证据入口：`games/epic7/evidence/hero_synthesis.py`。

模板位于 `games/epic7/templates/hero/` 与 `games/epic7/templates/navigation/`。改版时按诊断中的键名替换模板；位置变化改 `REGIONS`，分数变化改 `THRESHOLDS`。

以下内容不能通过修改视觉阈值绕过：SSS 优先级、材料安全、相邻同名副本、合成结果、传送结果和不可逆事务。它们仍由 `games/epic7/hero_synthesis.py` 的业务状态机决定。
