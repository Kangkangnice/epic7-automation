# 远征视觉维护

远征视觉证据入口：`games/epic7/evidence/expedition.py`。

模板位于 `games/epic7/templates/expedition/`；共享战斗自动按钮使用 `../story/auto_off.png`。改版时先替换模板，再按键名修改 `REGIONS` 或 `THRESHOLDS`。

难度三是否已选中、传单是否可出发、公开招募和返回主页属于业务事务判断，仍在 `games/epic7/expedition.py`。不因识别分数下降直接放宽难度或出发条件。
