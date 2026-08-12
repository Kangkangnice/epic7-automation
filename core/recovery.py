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
                "recovery blocked during committed battle "
                f"mode={self._lock.mode} cycle={self._lock.cycle} reason={reason}"
            )
            if self._on_blocked is not None:
                self._on_blocked(message)
            raise RecoveryBlocked(message)
        if self._recover is not None:
            self._recover()
