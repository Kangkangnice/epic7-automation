from pathlib import Path
from datetime import datetime
from typing import Callable

import cv2
import numpy as np


class StaminaExhausted(RuntimeError):
    """Raised when stamina refills are used up; the run stops cleanly."""


class ManualStop(RuntimeError):
    """Raised before the next action when the user presses the stop hotkey."""


class Runtime:
    """One coordinate system for capture, clicks, dry-run logging and diagnostics."""

    def __init__(
        self,
        capture: Callable[[], np.ndarray],
        click: Callable[[tuple[int, int]], None],
        *,
        wake: Callable[[tuple[int, int]], None] | None = None,
        back: Callable[[], None] | None = None,
        dry_run: bool = False,
        diagnostic_dir: Path | None = None,
        log_path: Path | None = None,
        emit: Callable[[str], None] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        diagnostic_limit: int = 30,
        max_log_bytes: int = 5 * 1024 * 1024,
        log_backups: int = 4,
    ) -> None:
        self._capture = capture
        self._click = click
        self._wake = wake
        self._back = back
        self.dry_run = dry_run
        self.diagnostic_dir = diagnostic_dir
        self.log_path = log_path
        self._emit = emit or (lambda message: print(message, flush=True))
        self._stop_requested = stop_requested
        self._last_screen: np.ndarray | None = None
        self.diagnostic_limit = diagnostic_limit
        self.max_log_bytes = max_log_bytes
        self.log_backups = log_backups

    def capture(self) -> np.ndarray:
        self._stop_if_requested()
        screen = self._capture()
        self._last_screen = screen
        return screen

    def click(self, point: tuple[int, int], action: str) -> None:
        self._stop_if_requested()
        prefix = "DRY RUN " if self.dry_run else ""
        self.log(f"{prefix}action={action} point={point}")
        if not self.dry_run:
            if action == "wake-campfire-ui" and self._wake is not None:
                self._wake(point)
            else:
                self._click(point)

    def back(self, action: str = "back") -> None:
        self._stop_if_requested()
        prefix = "DRY RUN " if self.dry_run else ""
        self.log(f"{prefix}action={action} key=ESC")
        if not self.dry_run:
            if self._back is None:
                raise RuntimeError("back action is not configured")
            self._back()

    def _stop_if_requested(self) -> None:
        if self._stop_requested is None or not self._stop_requested():
            return
        message = "用户按下 P，正在中断自动化"
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
            raise RuntimeError("diagnostic_dir is not configured")
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.diagnostic_dir / f"{timestamp}_{label}.png"
        self._write_image(path, self.capture() if screen is None else screen)
        self._prune_diagnostics()
        self.log(f"diagnostic={path}")
        return path

    def save_current_frame(self, screen: np.ndarray | None = None) -> Path:
        if self.diagnostic_dir is None:
            raise RuntimeError("diagnostic_dir is not configured")
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        path = self.diagnostic_dir / "current.png"
        self._write_image(path, self.capture() if screen is None else screen)
        return path

    def _write_image(self, path: Path, screen: np.ndarray) -> None:
        image = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"could not save diagnostic: {path}")

    def _prune_diagnostics(self) -> None:
        if self.diagnostic_dir is None or self.diagnostic_limit < 1:
            return
        paths = sorted(
            (path for path in self.diagnostic_dir.glob("*.png") if path.name != "current.png"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in paths[: -self.diagnostic_limit]:
            path.unlink()

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
