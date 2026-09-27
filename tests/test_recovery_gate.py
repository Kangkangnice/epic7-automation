"""战斗锁 ``RecoveryGate`` 的钉子。

⚠️ 这个类在 2026-09-26 之前叫「恢复闸门」—— 除了锁，它还是「回大厅重新导航、
然后接着跑」那条通道的入口（``recover()``）。用户当天拍板

    「回家触发完之后，回到首页，说明这个就结束了，不可能会再回到这个任务」

⇒ 那条通道整段删除，只剩「已承诺战斗期间禁止打断」这一个职责（见 ``core/recovery.py``
的模块 docstring）。所以这里守两件事：

1. 锁本身照旧工作：``lock()`` 之后 ``locked`` 为真、``unlock()`` 之后为假；
2. **那条通道不许被加回来** —— 加回来的实跑表现就是「任务又从头做了一遍」。
"""

from auto_game_unified.core.recovery import RecoveryGate


def test_the_gate_toggles_with_lock_and_unlock():
    gate = RecoveryGate()

    assert gate.locked is False
    gate.lock(mode="expedition", cycle=1)
    assert gate.locked is True
    gate.unlock()
    assert gate.locked is False


def test_relocking_keeps_the_gate_locked():
    """连打两局时锁要「一直锁着」，不能因为第二次 lock 就松掉。"""
    gate = RecoveryGate()

    gate.lock(mode="story", cycle=1)
    gate.lock(mode="story", cycle=2)

    assert gate.locked is True


def test_the_gate_no_longer_has_a_way_back_to_the_lobby():
    """⚠️ 这条就是「别把回大厅重来加回来」的钉子。

    ``recover()`` 一旦复活，主循环又会多出「卡住 ⇒ 回大厅重新导航 ⇒ 接着跑」那条路
    （实跑表现：任务从头又做了一遍）。它连带删掉的还有 ``RecoveryBlocked``
    （只由 ``recover()`` 抛出）与 ``on_blocked`` 回调。
    """
    gate = RecoveryGate()

    assert not hasattr(gate, "recover")
    assert not hasattr(gate, "on_blocked")
