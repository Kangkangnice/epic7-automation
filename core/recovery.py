"""战斗锁：**已承诺战斗期间不许任何东西打断这一局**。

⚠️ 2026-09-26 之前这个文件是「恢复闸门」，它有两个身份：① 战斗中禁止恢复的锁；
② 「回大厅重新导航、然后接着跑」那条恢复通道的闸门。用户当天拍板——

    「回家触发完之后，回到首页，说明这个就结束了，不可能会再回到这个任务」

⇒ **恢复通道整段删除**（``recover()`` / ``RecoveryBlocked`` / ``on_blocked`` 回调
一起删掉），只剩战斗锁这一个身份：

- ``lock()`` / ``unlock()``：``BattleSupervisor`` 在「战斗开始的点击**已验证**」之后
  上锁，直到认出结算锚点（或安全停止）才解锁（见 ``core/battle_supervisor.py``）。
- ``locked``：``UnknownScreenWake`` 读它 —— 战斗中画面认不出时**不许**点唤醒点击，
  点了就是把这一局弄丢。

⚠️ 类名与文件名**保留**（历史名）：改一次名要动十几个模块与测试的 import、还要重渲
架构图，而它们现在要表达的东西没变（「有人占着锁」）。语义以本 docstring 与
``RecoveryGate`` 的 docstring 为准 —— 它**只有**战斗锁这一件事。

⚠️ 谁把「回大厅重来」加回来，会先撞上 ``tests/test_recovery_gate.py`` 里那条
「闸门上不许再有 recover 入口」的钉子。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BattleLock:
    """谁在打这一局：写进日志用（模式 + 轮次）。"""

    mode: str
    cycle: int


class RecoveryGate:
    """**只剩战斗锁**：谁在打这一局（``lock``）谁说了算，别人不许动。

    ⚠️ 名字里的 "Recovery" 是历史遗留（见模块 docstring）：这个类现在**只有**
    「战斗中禁止打断」这一个职责。真正的使用方只有两个：

    - ``BattleSupervisor``：验证过「战斗开始的点击」之后 ``lock()``，
      认到结算锚点（或安全停止）时 ``unlock()``；
    - ``UnknownScreenWake``：读 ``locked`` —— 战斗中不许点唤醒。
    """

    def __init__(self) -> None:
        self._lock: BattleLock | None = None

    @property
    def locked(self) -> bool:
        return self._lock is not None

    def lock(self, *, mode: str, cycle: int) -> None:
        self._lock = BattleLock(mode=mode, cycle=cycle)

    def unlock(self) -> None:
        self._lock = None
