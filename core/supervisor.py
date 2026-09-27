"""Small observation helpers shared by live game runners."""

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Optional

import numpy as np


@dataclass
class StableObservation:
    """Accept a page/action only after it is seen in consecutive frames."""

    required: int = 2
    _value: Optional[str] = field(default=None, init=False)
    _count: int = field(default=0, init=False)

    def update(self, value: str) -> bool:
        if value != self._value:
            self._value = value
            self._count = 1
            return self.required <= 1
        self._count += 1
        return self._count >= self.required

    def reset(self) -> None:
        self._value = None
        self._count = 0


@dataclass
class ConclusionGate:
    """「下结论」也要两帧：单帧不许收工、不许宣布认不出画面。

    ⚠️ 为什么它不是可选项（2026-09-25 实跑的两条事故，都是**一帧**惹的祸）：

    - 世界首领战：``next_action`` 里「今天没场次了」的异常从 ``preview()``
      **直接穿到主循环**，早于两帧稳定确认 ⇒ 一帧就宣布整条路线收工，
      宝箱还没看、就先说打完了；
    - 通用：``UnrecognizedScreen`` 同样一帧穿出去 ⇒ 一帧没认出画面就去点屏幕
      中间（用户看到的就是「眼睛瞎了一直点中间」）。

    动作要两帧、结论却只要一帧，等于门槛只把门掩了一半 —— 真正会终止路线的
    恰恰是这些结论，它们反而最宽松。所以结论必须走同一道门槛。

    用法：主循环捕获到终止性异常时先问 ``admit(error)``；返回 False 就当这一帧
    没看见（继续观察），返回 True 才允许按结论处理（收工 / 唤醒 / 报错）。

    ``ManualStop`` 是唯一的例外：那是**用户按了停止键**，不是程序下的结论，
    必须立刻响应，等两帧会让停止键迟钝。
    """

    _stable: StableObservation = field(
        default_factory=lambda: StableObservation(required=2)
    )
    # 按类型名判断而不是 import 具体类：core 不该认识 games 层的异常，
    # 也不用担心和 core.runtime 形成循环导入。
    _immediate_names: frozenset[str] = frozenset({"ManualStop"})

    def admit(self, error: BaseException) -> bool:
        if type(error).__name__ in self._immediate_names:
            return True
        return self._stable.update(self.signature(error))

    @staticmethod
    def signature(error: BaseException) -> str:
        """结论签名：类型 + ``stop_label``（缺什么），不同结论不互相背书。"""

        label = getattr(error, "stop_label", "")
        return f"conclusion:{type(error).__name__}:{label}"

    def reset(self) -> None:
        self._stable.reset()


@dataclass
class Watchdog:
    """Track both a no-progress timeout and an absolute operation deadline."""

    no_progress_seconds: float
    absolute_seconds: float
    now: Callable[[], float] = monotonic
    _started: float = field(init=False)
    _progressed: float = field(init=False)

    def __post_init__(self) -> None:
        self._started = self._progressed = self.now()

    def progress(self) -> None:
        self._progressed = self.now()

    def expired_reason(self) -> Optional[str]:
        current = self.now()
        if current - self._started >= self.absolute_seconds:
            return "absolute"
        if current - self._progressed >= self.no_progress_seconds:
            return "no_progress"
        return None


def meaningful_change(before: Optional[np.ndarray], after: np.ndarray) -> bool:
    """Detect useful animation/loading progress while ignoring the static HUD."""

    if before is None or before.shape != after.shape:
        return False
    height, width = after.shape[:2]
    y1, y2 = round(height * 0.16), round(height * 0.78)
    x1, x2 = round(width * 0.06), round(width * 0.94)
    previous = before[y1:y2, x1:x2]
    current = after[y1:y2, x1:x2]
    difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
    return float(np.mean(difference)) >= 2.0


def left_page(previous_page: str, current_page: str) -> bool:
    """「点一次、验收一次」的严格判据：只有页面身份变了才算这一下生效。

    ⚠️ **不要用 ``meaningful_change`` 兜底**。实测（``runtime_logs/_probe_click_verify.py``）：
    同一页面的不同帧平均差 11.10 / 12.95 / 45.03，而真实转场的相邻帧可以低到 **0.00**
    —— 两个区间完全重叠，画面差区分不了「原地在动」和「换页」。大厅这类自带待机动画
    的页面上，画面兜底会把每一次点击都判成「生效」，机制等于没加。
    """
    return previous_page != current_page


def page_or_picture_changed(
    previous_page: str,
    previous_screen: Optional[np.ndarray],
    current_page: str,
    current_screen: np.ndarray,
) -> bool:
    """「按一次、验收一次」的宽松判据：换页，或同页但画面明显变化，都算生效。

    用于 ``return_home`` 的返回验收：那里误判「生效」的代价只是多等一轮，而误判
    「无效」会把动作换成页内返回箭头（行为更激进），所以宁松勿紧。
    """
    if previous_page != current_page:
        return True
    return meaningful_change(previous_screen, current_screen)


def wait_until_target(
    *,
    capture: Callable[[], np.ndarray],
    save_frame: Callable[[np.ndarray], None],
    is_target: Callable[[np.ndarray], bool],
    absolute_seconds: float,
    no_progress_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None],
    now: Callable[[], float],
    settle_seconds: float = 0.0,
    two_frame: bool = False,
) -> bool:
    """轮询直到画面进入目标状态。

    返回 True 表示确认进入目标状态；绝对超时或无进展超时返回 False。
    two_frame=True 时要求目标状态连续两帧出现（避免转场动画误判）。
    """
    if settle_seconds:
        sleep(settle_seconds)
    started = progressed = now()
    previous: Optional[np.ndarray] = None
    stable = StableObservation(required=2) if two_frame else None
    while now() - started < absolute_seconds:
        screen = capture()
        save_frame(screen)
        reached = is_target(screen)
        if stable is not None:
            if stable.update("target" if reached else "other") and reached:
                return True
        elif reached:
            return True
        if meaningful_change(previous, screen):
            progressed = now()
        previous = screen
        if now() - progressed >= no_progress_seconds:
            return False
        sleep(poll_seconds)
    return False
