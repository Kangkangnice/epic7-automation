# 远征视觉维护

远征视觉证据入口：`games/epic7/evidence/expedition.py`。

模板位于 `games/epic7/templates/expedition/`；共享战斗自动按钮使用 `../story/auto_off.png`。改版时先替换模板，再按键名修改 `REGIONS` 或 `THRESHOLDS`。

难度三是否已选中、传单是否可出发、公开招募和返回主页属于业务事务判断，仍在 `games/epic7/expedition.py`。不因识别分数下降直接放宽难度或出发条件。

转场或未知页面超时时，原 `*.png` 旁的同名目录包含 `screen.png` 和 `evidence.json`。按其中 `config`、证据键、`region`、实际 `score` 和 `threshold` 维护；低分仍会量化记录。当前命令行检查器未注册远征，修改后运行远征页面与 Runner 测试。
