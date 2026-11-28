from pathlib import Path
from datetime import datetime
import shutil
from time import monotonic as default_monotonic
from typing import Callable, Protocol

import cv2
import numpy as np

from auto_game_unified.core.failure_history import FailureHistory


class CaptureGuard(Protocol):
    def __call__(
        self, runtime: "Runtime", screen: np.ndarray
    ) -> tuple[np.ndarray, bool]: ...


class ResourceExhausted(RuntimeError):
    """资源/次数不够导致的**正常业务退出**（退出码 2）。

    这条通道的语义是「还能干，但没本钱了」：不是故障、不留失败诊断，
    但也不能装作跑满了 —— 所以单独给一个退出码，通知里一眼能看出来。

    ``stop_label`` 是写进运行日志``停止=``后面的文案，各路线按自己缺的那样东西命名。
    **故意不给一个笼统的默认值**：日志的价值就在于能一眼看出到底缺了什么，
    写「资源耗尽」等于没写。子类只覆盖这一个类属性。
    """

    stop_label = "资源耗尽"


class StaminaExhausted(ResourceExhausted):
    """Raised when stamina refills are used up; the run stops cleanly."""

    stop_label = "生命之叶耗尽"


class EquipmentBagFull(ResourceExhausted):
    """装备背包已满：游戏弹窗明确说「请整理或扩充装备背包后再重试」。

    它不是故障 —— 背包满了本来就不能继续做，所以走资源耗尽通道（退出码 2），
    与「没门票」「红叶不足」同一档。由全局弹窗守卫识别、点掉弹窗后在
    ``Runtime.blocking_popup`` 留一条标记，主循环读到就按这条异常收工。
    """

    stop_label = "装备背包已满"


class ManualStop(RuntimeError):
    """Raised before the next action when the user presses the stop hotkey."""


class PurchaseReceiptUnclear(RuntimeError):
    """不可逆购买已提交一次，游戏回执未明 —— 保留现场、停下对账。

    弹窗还在只说明回执未确认，不是游戏明确拒绝。所有正式入口（单路线、每日编排）
    遇到这条异常都必须**不回大厅、不跑下一条、不做收尾巡检**，否则会移动对账现场。
    退出码按运行失败处理，现场由故障诊断帧与这条例外共同保留。
    """


def _safe_label(label: str) -> str:
    """把标签里的路径分隔符换成下划线，保证它只当**文件名**用。

    ⚠️ 调用方会用 ``"/".join(targets)`` 这类拼法产生**多目标**标签
    （如 ``battle_menu/season_menu``）。这个名字直接拼进文件名后，``/`` 在
    Windows 上会被 ``Path`` 当成**目录分隔符** ⇒ 落点变成**不存在的子目录**
    ⇒ ``cv2.imwrite`` 失败 ⇒ 抛「诊断截图保存失败」。而它是在处理**另一个失败**
    的过程中抛的 ⇒ **把真正的失败原因盖掉**（2026-10-03 远征 21:10:43 实测：
    日志里只剩「诊断截图保存失败」，看不出真正原因是「导航转场失败」）。
    """
    return label.replace("/", "_").replace("\\", "_")


class Runtime:
    """One coordinate system for capture, clicks, dry-run logging and diagnostics."""

    def __init__(
        self,
        capture: Callable[[], np.ndarray],
        click: Callable[[tuple[int, int]], None],
        *,
        swipe: Callable[
            [tuple[int, int], tuple[int, int], int], None
        ]
        | None = None,
        wheel: Callable[[tuple[int, int], int], None] | None = None,
        wake: Callable[[tuple[int, int]], None] | None = None,
        back: Callable[[], None] | None = None,
        dry_run: bool = False,
        diagnostic_dir: Path | None = None,
        log_path: Path | None = None,
        emit: Callable[[str], None] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        input_channel_probe: Callable[[], None] | None = None,
        diagnostic_limit: int = 30,
        max_log_bytes: int = 5 * 1024 * 1024,
        log_backups: int = 4,
        monotonic: Callable[[], float] = default_monotonic,
    ) -> None:
        self._capture = capture
        self._click = click
        self._swipe = swipe
        self._wheel = wheel
        self._wake = wake
        self._back = back
        self.dry_run = dry_run
        self.diagnostic_dir = diagnostic_dir
        self.failure_history = FailureHistory() if diagnostic_dir is not None else None
        self.log_path = log_path
        self._emit = emit or (lambda message: print(message, flush=True))
        self._stop_requested = stop_requested
        self._input_channel_probe = input_channel_probe
        self._last_screen: np.ndarray | None = None
        # 全局弹窗守卫认出「这条弹窗意味着不能再继续」时写下的一句话。
        # 主循环读到它就把这一轮按 ``ResourceExhausted`` 正常收工。
        # 空串 = 没有阻断。
        self.blocking_popup: str = ""
        # 本次运行点过几次「断网重连」弹窗的重试按钮（守卫每次点击时累加）。
        # 用途只有一个：失败文案要如实带上「这次到底有没有断过网」这个**已经发生
        # 的事实**，而不是让用户对着一张诊断图自己猜（2026-11-21 竞技场实跑：
        # 中途点了 5 次 retry-network 没恢复，最终却只报「连按 2 次 ESC 没反应」）。
        # ⚠️ 只记事实、不改判据：不参与任何验收/重试决策，失败时读它拼文案而已。
        self.network_popup_clicks: int = 0
        self.diagnostic_limit = diagnostic_limit
        self.max_log_bytes = max_log_bytes
        self.log_backups = log_backups
        self._monotonic = monotonic
        self._paused_seconds = 0.0
        self._capture_guard: CaptureGuard | None = None
        # 停止请求可能来自 **边沿**（P 键按一次）也可能是 **电平**（桌面界面的
        # stop.signal 文件一旦写出就一直在）。日志和诊断图只在第一次报一次，
        # 否则一次停止会按轮询频率刷屏、每秒写一张 1.4MB 的截图。
        self._stop_reported = False

    def capture(self) -> np.ndarray:
        screen = self.capture_unguarded()
        if self._capture_guard is None:
            return screen
        started = self._monotonic()
        screen, paused = self._capture_guard(self, screen)
        self._last_screen = screen
        if paused:
            self._paused_seconds += self._monotonic() - started
        return screen

    def capture_unguarded(self) -> np.ndarray:
        self._stop_if_requested()
        screen = self._capture()
        if self.failure_history is not None:
            self.failure_history.observe(screen)
        self._last_screen = screen
        return screen

    def last_frame(self) -> np.ndarray | None:
        """最近一次**成功**取到的画面；还没取过就是 ``None``。

        ⚠️ 只读访问器，**不触发取图**。给「取图本身失败、但要留下最后可用证据」的
        路径用 —— 那种时候再调 ``capture()``（或 ``save_diagnostic(..., screen=None)``，
        它内部就是 ``self.capture()``）只会再失败一次，把真正的错因盖掉。
        """
        return self._last_screen

    def set_capture_guard(self, guard: CaptureGuard) -> None:
        self._capture_guard = guard

    def try_dismiss_unknown_popup(self, screen: np.ndarray) -> bool:
        """卡死兜底：让全局守卫试着点掉画面上没登记过的「点击关闭」弹窗。

        只有装配了支持该能力的守卫（``Epic7GlobalPopupGuard``）才会真正动手；
        测试替身 / 别的守卫没有这个方法 ⇒ 原样返回 False，行为不变。
        ⚠️ 调用方必须自己保证「已认不出画面、即将失败」且一条路线只调一次；
        Runtime 不持有任何状态，也不参与判据。
        """
        guard = self._capture_guard
        method = getattr(guard, "try_dismiss_unknown_popup", None)
        if not callable(method):
            return False
        return bool(method(self, screen))

    def note_blocking_popup(self, label: str) -> None:
        """记下「这条弹窗出现后不能继续」的事实，由主循环转成正常收工。"""
        self.blocking_popup = label

    def note_network_popup(self) -> None:
        """记下「本次运行又点了一次断网弹窗重试」的事实（只用于失败文案）。"""
        self.network_popup_clicks += 1

    def network_popup_note(self) -> str:
        """给失败文案用的事实句：本次运行有没有断过网、点了几次重试。

        返回空串表示没有装配守卫/没断过网（老行为不变）。有则以「；」开头，
        直接拼到既有报错后面，且用「可确认/未确认」陈述事实，不写推测。
        """
        if self.network_popup_clicks <= 0:
            return ""
        return (
            f"；本次已断网、自动重试 {self.network_popup_clicks} 次"
            "（网络问题可确认，需恢复后重跑）"
        )

    def consume_blocking_popup(self) -> str:
        """取一次就清空：一条路线的阻断不该传染给下一条。"""
        label = self.blocking_popup
        self.blocking_popup = ""
        return label

    def now(self) -> float:
        return self._monotonic() - self._paused_seconds

    def click(self, point: tuple[int, int], action: str) -> None:
        self._stop_if_requested()
        prefix = "空跑 " if self.dry_run else ""
        self.log(f"{prefix}执行点击 动作={action} 坐标={point}")
        if not self.dry_run:
            if action == "wake-campfire-ui" and self._wake is not None:
                self._wake(point)
            else:
                self._click(point)

    def ensure_input_channel(self) -> None:
        """确认模拟器输入通道还活着；没装配探针就静默跳过。

        ⚠️ 为什么不能只在开跑前自检一次：``Epic7Window.ensure_input_channel``
        目前只由 ``main._build_runtime`` 调一次。跑到一半通道坏掉（模拟器重启、
        adb 连接掉了），就没人再检查 —— 上层只看到「点击验收无效」，重试到上限后
        报「导航转场失败」，**分不清「通道断了」还是「游戏没响应」**。
        2026-10-03 实测正是这种局面：连点 8 次无效，诊断图却是完好的大厅画面，
        光看日志无法定论。

        导航在「连续点不动」时会调这里，让日志里留下通道的真实状态。
        干跑不装配探针（干跑不该去动 adb 服务）⇒ 这里静默返回，行为与改动前一致。
        """
        if self._input_channel_probe is None:
            return
        self._input_channel_probe()

    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_ms: int,
        action: str,
    ) -> None:
        self._stop_if_requested()
        prefix = "空跑 " if self.dry_run else ""
        self.log(
            f"{prefix}执行滑动 动作={action} 起点={start} 终点={end} "
            f"时长={duration_ms}ms"
        )
        if self.dry_run:
            return
        if self._swipe is None:
            raise RuntimeError("未配置滑动动作")
        self._swipe(start, end, duration_ms)

    def wheel(self, point: tuple[int, int], notches: int, action: str) -> None:
        """在画布坐标 ``point`` 处滚动鼠标滚轮（正数向上、负数向下）。"""
        self._stop_if_requested()
        prefix = "空跑 " if self.dry_run else ""
        self.log(f"{prefix}执行滚轮 动作={action} 点={point} 格数={notches}")
        if self.dry_run:
            return
        if self._wheel is None:
            raise RuntimeError("未配置滚轮动作")
        self._wheel(point, notches)

    def back(self, action: str = "back") -> None:
        self._stop_if_requested()
        prefix = "空跑 " if self.dry_run else ""
        self.log(f"{prefix}执行返回 动作={action} 按键=ESC")
        if not self.dry_run:
            if self._back is None:
                raise RuntimeError("未配置返回键动作")
            self._back()

    def _stop_if_requested(self) -> None:
        """有停止请求就抛 ``ManualStop``；**报告只做一次**。

        每次调用仍然照抛（停止请求是电平信号时必须一直生效，不能被漏掉一次就
        永远丢掉），但日志与 ``manual_stop`` 诊断图只在第一次落地 —— 报告重复的
        代价是刷屏加每秒一张全屏截图，而收益是零。
        """
        if self._stop_requested is None or not self._stop_requested():
            return
        message = "用户按下 P，正在中断自动化"
        if not self._stop_reported:
            self._stop_reported = True
            self.log(message)
            if self.diagnostic_dir is not None and self._last_screen is not None:
                self.save_diagnostic("manual_stop", self._last_screen)
        raise ManualStop(message)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} {message}"
        self._emit(line)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            encoded_size = len((line + "\n").encode("utf-8"))
            if self.log_path.exists() and self.log_path.stat().st_size + encoded_size > self.max_log_bytes:
                self._rotate_logs()
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def save_diagnostic(self, label: str, screen: np.ndarray | None = None) -> Path:
        if self.diagnostic_dir is None:
            raise RuntimeError("未配置诊断截图目录")
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.diagnostic_dir / f"{timestamp}_{_safe_label(label)}.png"
        screen = self.capture() if screen is None else screen
        self._write_image(path, screen)
        if self.failure_history is not None and screen is self._last_screen:
            self.failure_history.evidence_frame = path
        self._prune_diagnostics()
        self.log(f"已保存诊断 {path}")
        return path

    def record_failure(self, error: BaseException) -> None:
        if self.failure_history is None or self.diagnostic_dir is None:
            return
        try:
            self.failure_history.save(
                self.diagnostic_dir, f"{type(error).__name__}: {error}", self.log_path
            )
        except Exception as diagnostic_error:
            # Even when the disk is full the original route exception must survive.
            self._emit(f"故障截图留存失败：{diagnostic_error}")

    def save_current_frame(self, screen: np.ndarray | None = None) -> Path:
        if self.diagnostic_dir is None:
            raise RuntimeError("未配置诊断截图目录")
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        path = self.diagnostic_dir / "current.png"
        self._write_image(path, self.capture() if screen is None else screen)
        return path

    def _write_image(self, path: Path, screen: np.ndarray) -> None:
        image = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"诊断截图保存失败：{path}")

    def _prune_diagnostics(self) -> None:
        if self.diagnostic_dir is None or self.diagnostic_limit < 1:
            return
        paths = sorted(
            (path for path in self.diagnostic_dir.glob("*.png") if path.name != "current.png"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in paths[: -self.diagnostic_limit]:
            path.unlink()
            evidence_directory = path.with_suffix("")
            if evidence_directory.is_symlink():
                evidence_directory.unlink()
            elif evidence_directory.is_dir():
                shutil.rmtree(evidence_directory)

    def _rotate_logs(self) -> None:
        if self.log_path is None:
            return
        oldest = Path(f"{self.log_path}.{self.log_backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.log_backups - 1, 0, -1):
            source = Path(f"{self.log_path}.{index}")
            if source.exists():
                source.replace(Path(f"{self.log_path}.{index + 1}"))
        if self.log_path.exists():
            self.log_path.replace(Path(f"{self.log_path}.1"))
