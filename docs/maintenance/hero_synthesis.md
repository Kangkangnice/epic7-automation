# 英雄合成视觉维护

英雄合成视觉证据入口：`games/epic7/evidence/hero_synthesis.py`。

模板位于 `games/epic7/templates/hero/` 与 `games/epic7/templates/navigation/`。改版时按诊断中的键名替换模板；位置变化改 `REGIONS`，分数变化改 `THRESHOLDS`。

以下内容不能通过修改视觉阈值绕过：SSS 优先级、材料安全、相邻同名副本、合成结果、传送结果和不可逆事务。它们仍由 `games/epic7/hero_synthesis.py` 的业务状态机决定。

运行时的 `rating_sss`、`sss_material`、筛选、SSS 警告、合成结果和传送结果已直接读取上述 profile，不再维护第二套区域或阈值。失败时查看原 `*.png` 同名目录内的 `evidence.json`；低于阈值仍保留实际 `score`，`config` 指向应修改的证据文件。当前命令行检查器未注册英雄合成，修改后运行英雄证据与完整合成回归。
