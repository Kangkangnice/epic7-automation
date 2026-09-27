from enum import Enum

import numpy as np

from auto_game_unified.core.battle_supervisor import valid_game_frame
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import meaningful_change
from auto_game_unified.games.epic7.battle_controls import (
    BattleControls,
    observe_battle_controls,
)


_CANVAS_SIZE = (1132, 1982)
_RENDER_TOP = 52
_RENDER_RIGHT = 1920


def _valid_render_canvas(screen: np.ndarray) -> bool:
    if screen.shape[:2] != _CANVAS_SIZE:
        return False
    return (
        float(np.mean(screen[:_RENDER_TOP])) <= 2.0
        and float(np.mean(screen[:, _RENDER_RIGHT:])) <= 2.0
    )


class UnrecognizedScreen(RuntimeError):
    """The current mode cannot recognize the page required by its state."""


class UnknownWakeResult(Enum):
    WAITING = "waiting"
    SKIPPED = "skipped"
    EXHAUSTED = "exhausted"
    # ⚠️ 这里原来有一个 ``CLICKED``（认不出画面就去点屏幕中央），2026-09-26 删掉了。
    # 用户当场抓包的现象就是「眼睛瞎了一直点中间」—— 点中央既没有判据、也常常
    # 落在列表空白处，纯粹是瞎猜。认不出画面现在只等、到点交给上层超时收尾。


class UnknownScreenWake:
    """认不出的静止画面：**只观察、不动手**，把结论交还上层。

    ⚠️ 2026-09-26 起不再「点屏幕中央试着唤醒」了（用户抓包的「眼睛瞎了一直点中间」）：
    点中央没有判据、常常落在列表空白处，是瞎猜不是处理。现在只做三件事 ——
    ① 画面还在变 ⇒ WAITING 等它稳定；② 变化超过 ``max_waiting_frames`` ⇒ 按「带动画的
    未知页」交还上层；③ 画面静止但仍认不出 ⇒ 记一张诊断图 + 一条日志，然后交还上层
    （由上层按超时收尾，回家由 ``main`` 负责）。
    """

    def __init__(
        self,
        runtime: Runtime,
        *,
        recovery_gate: RecoveryGate | None = None,
        max_waiting_frames: int = 15,
    ) -> None:
        self.runtime = runtime
        self.recovery_gate = recovery_gate
        # 带动画的页面（如英雄详情立绘）画面永远在变，若无限等待 WAITING
        # 会卡死上层循环；超过该帧数按未知画面交给上层按超时收尾。
        self.max_waiting_frames = max_waiting_frames
        self.reset()

    def reset(self) -> None:
        self._context: str | None = None
        self._previous: np.ndarray | None = None
        self._waiting_frames = 0
        self._exhausted_reported = False

    def handle(self, screen: np.ndarray, *, context: str) -> UnknownWakeResult:
        if context != self._context:
            self.reset()
            self._context = context

        if (
            self.runtime.dry_run
            or (self.recovery_gate is not None and self.recovery_gate.locked)
            or not _valid_render_canvas(screen)
            or not valid_game_frame(screen)
            or observe_battle_controls(screen) is not BattleControls.TRANSITION
        ):
            self._previous = None
            self._waiting_frames = 0
            return UnknownWakeResult.SKIPPED

        if self._previous is None:
            self._previous = screen.copy()
            return self._waiting(screen)

        if self._previous.shape != screen.shape or meaningful_change(
            self._previous, screen
        ):
            self._previous = screen.copy()
            return self._waiting(screen)

        # 画面静止了、还是认不出这是哪一页 ⇒ **不点任何地方**，直接交还上层
        # （上层会按「这一页认不出来」超时收尾，回家由 main 负责）。
        # ⚠️ 2026-09-26：以前这里会去点屏幕中央最多 4 次，已删，理由见
        # ``UnknownWakeResult`` 与类 docstring。
        # 刻意**不清空账本**：一旦判定「认不出」就一直保持 EXHAUSTED，否则下一帧又会
        # 从头记基准 ⇒ 表现为 WAITING / EXHAUSTED 来回横跳。上层换页时会调 ``reset()``。
        if not self._exhausted_reported:
            self._save_diagnostic("unknown_screen_unresolved", screen)
            self.runtime.log(
                f"页面={context} 状态=画面已静止但仍认不出是哪一页 "
                "动作=不点任何地方，交给上层超时收尾"
            )
            self._exhausted_reported = True
        return UnknownWakeResult.EXHAUSTED

    def _waiting(self, screen: np.ndarray) -> UnknownWakeResult:
        """画面仍在变化：先等待稳定，超过上限则放弃等待（页面本身带动画）。

        EXHAUSTED 后保持状态不重置，让上层一直报 EXHAUSTED，由上层按超时收尾。
        """
        self._waiting_frames += 1
        if self._waiting_frames < self.max_waiting_frames:
            return UnknownWakeResult.WAITING
        if not self._exhausted_reported:
            self._save_diagnostic("unknown_animated_page", screen)
            self.runtime.log(
                f"页面={self._context} 画面持续变化超过{self.max_waiting_frames}帧"
                "=按未知画面交给上层按超时收尾"
            )
            self._exhausted_reported = True
        return UnknownWakeResult.EXHAUSTED

    def _save_diagnostic(self, label: str, screen: np.ndarray) -> None:
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_diagnostic(label, screen)
