"""「次元探查」：在助手进程内直接跑第三方 chaos 流程。

第三方代码原样放在 ``<workspace>/vendor/e7auto``，不进 ``MODE_SPECS``、
不进每日任务链。这里只做三件事：挂上它的源码目录、装配一次运行、
把停止与进度接回来。业务逻辑不依赖 Qt，方便单测。
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable

__all__ = ["ChaosBridge", "STAGES", "LINEUPS", "vendor_root"]

STAGES = (1, 2, 3, 4, 5)
LINEUPS = (("dark_twins", "暗双子队（默认）"), ("budget", "平民替换队"))
_LINEUP_IDS = frozenset(item[0] for item in LINEUPS)
_MAX_ROUNDS = 99


def vendor_root() -> Path:
    """源码模式在工作区根；打包模式在 PyInstaller 的解压目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "vendor" / "e7auto"
    return Path(__file__).resolve().parents[2] / "vendor" / "e7auto"


class _Overlay:
    """它自己的悬浮窗由本助手界面替代；这里只满足接口，不画任何东西。"""

    def position(self, client_bounds: object, offset: object = None) -> bool:
        return True


class _Logger:
    """只把关键事件转成一行人话；异常现场帧暂不落盘。"""

    _KEYS = frozenset(
        {"run_stopped", "internal_error", "startup_rejected", "chaos_saved_exploration"}
    )

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit

    def event(self, event: str, **fields: object) -> None:
        if event not in self._KEYS:
            return
        detail = fields.get("reason") or fields.get("phase") or fields.get("error")
        self._emit(f"{event}" + (f"：{detail}" if detail else ""))

    def save_stop_snapshot(
        self, cached: object, *, stop_reason: str, stopped_monotonic: float
    ) -> None:
        self._emit(f"运行结束（原因 {stop_reason}）；异常现场帧未落盘")

    def close(self) -> None:
        return None


class ChaosBridge:
    """持有一次 chaos 运行的会话；``start`` 不阻塞界面。"""

    def __init__(self, vendor: Path | None = None) -> None:
        self._vendor = Path(vendor) if vendor is not None else vendor_root()
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=200)
        self._status = "未运行"
        self._rounds_done = 0
        self._rounds_target = 0
        self._session: object | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def drain_lines(self) -> list[str]:
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
        return lines

    def _log(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def _set_status(self, text: str) -> None:
        with self._lock:
            self._status = text

    @staticmethod
    def validate(stage: int, lineup_id: str, rounds: int) -> str:
        """能不能开：返回一句人话的原因，空串表示可以。"""
        if type(stage) is not int or stage not in STAGES:
            return "阶段只能选 1~5。"
        if lineup_id not in _LINEUP_IDS:
            return "阵容不认识。"
        if type(rounds) is not int or not 1 <= rounds <= _MAX_ROUNDS:
            return f"完成轮数要填 1~{_MAX_ROUNDS} 的整数。"
        return ""

    def _modules(self):
        src = self._vendor / "src"
        if not src.is_dir():
            raise FileNotFoundError(f"缺少第三方代码目录：{src}")
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from e7auto.bootstrap import create_production_session
        from e7auto.configuration.loader import load_config
        from e7auto.features.chaos.configuration import with_chaos_config

        return load_config, with_chaos_config, create_production_session

    def start(self, stage: int, lineup_id: str, rounds: int) -> str:
        """返回空串表示已开始；否则一句人话的原因。"""
        if self.running:
            return "次元探查已经在运行了。"
        error = self.validate(stage, lineup_id, rounds)
        if error:
            return error
        try:
            load_config, with_chaos_config, create_session = self._modules()
            config = load_config(
                self._vendor / "config" / "internal.yaml", template_profile="chaos"
            )
            config = with_chaos_config(
                config, target_stage=stage, lineup_id=lineup_id
            )
            session = create_session(
                config, "chaos", _Overlay(), _Logger(self._log), self._on_snapshot
            )
        except Exception as exc:  # noqa: BLE001 —— 装配失败要给人话，别让界面崩
            return f"启动失败：{type(exc).__name__}: {exc}"
        self._session = session
        self._rounds_target = rounds
        self._rounds_done = 0
        self._set_status(f"正在运行 · 完成 0/{rounds} 轮")
        self._log(
            f"开始次元探查：第 {stage} 阶段、{dict(LINEUPS)[lineup_id]}、目标 {rounds} 轮"
        )
        self._thread = threading.Thread(
            target=self._run, args=(rounds,), name="epic7-chaos", daemon=True
        )
        self._thread.start()
        return ""

    def _on_snapshot(self, snapshot: object) -> None:
        done = int(getattr(snapshot, "rounds_completed", self._rounds_done) or 0)
        target = int(getattr(snapshot, "round_limit", self._rounds_target) or 0)
        label = getattr(getattr(snapshot, "overlay_status", None), "value", "运行中")
        self._rounds_done = done
        self._set_status(f"{label} · 完成 {done}/{target} 轮")

    def _run(self, rounds: int) -> None:
        reasons = {
            "game_window_not_found": (
                "未找到 PC 客户端窗口。此项仅支持 STOVE / Steam 版《第七史诗》"
                "（窗口标题「第七史诗」，进程 EpicSeven.exe），模拟器窗口不适用；"
                "需先启动 PC 客户端、登录并回到游戏主界面。"
            ),
            "multiple_game_windows": "找到多个《第七史诗》窗口，需只保留一个再开始。",
            "permission_required": (
                "权限不足：需以「以管理员身份运行」方式启动本助手。"
            ),
            "unsupported_display_resolution": "桌面分辨率不足 1920×1080，或显示缩放异常。",
            "window_abnormal": "游戏窗口状态异常（最小化 / 被改动 / 已关闭）。",
            "chaos_unsupported_stage": "账号上没有这个阶段，或该阶段尚未解锁。",
        }
        session = self._session
        try:
            snapshot = session.run_chaos(rounds)
            reason = getattr(getattr(snapshot, "stop_reason", None), "value", None)
            text = reasons.get(reason, reason or "已结束")
            self._log(f"运行结束：{text}")
            self._set_status(f"已结束 · {text}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"运行异常：{type(exc).__name__}: {exc}")
            self._set_status("运行异常结束")
        finally:
            self._session = None

    def stop(self) -> bool:
        """请求停止；返回是否真的停了一次在跑的运行。"""
        session = self._session
        if session is None or not self.running:
            return False
        session.request_stop()
        self._log("已请求停止，等当前这一步收尾……")
        return True
