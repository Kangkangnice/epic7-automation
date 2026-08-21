from dataclasses import dataclass
from typing import Callable


class RecoveryBlocked(RuntimeError):
    """Raised when lobby recovery is requested during a committed battle."""


@dataclass(frozen=True)
class BattleLock:
    mode: str
    cycle: int


class RecoveryGate:
    def __init__(
        self,
        recover: Callable[[], None] | None,
        *,
        on_blocked: Callable[[str], None] | None = None,
    ) -> None:
        self._recover = recover
        self._on_blocked = on_blocked
        self._lock: BattleLock | None = None

    @property
    def locked(self) -> bool:
        return self._lock is not None

    def lock(self, *, mode: str, cycle: int) -> None:
        self._lock = BattleLock(mode=mode, cycle=cycle)

    def unlock(self) -> None:
        self._lock = None

    def recover(self, reason: str = "runner recovery") -> None:
        if self._lock is not None:
            message = (
                "战斗进行中禁止回大厅恢复 "
                f"模式={self._lock.mode} 轮次={self._lock.cycle} 原因={reason}"
            )
            if self._on_blocked is not None:
                self._on_blocked(message)
            raise RecoveryBlocked(message)
        if self._recover is not None:
            self._recover()
