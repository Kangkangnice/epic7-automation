"""Keep the five captures leading up to an unresolved failure."""

from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING
from zipfile import ZipFile

from auto_game_unified.core.account import ACCOUNT_ENV

if TYPE_CHECKING:
    import numpy as np
    from auto_game_unified.core.runtime import Runtime


FAILURE_WINDOW_ENV = "EPIC7_FAILURE_WINDOW"
MAX_FRAMES = 5


class FailureHistory:
    def __init__(self) -> None:
        self._recent: deque[tuple[str, np.ndarray]] = deque(maxlen=MAX_FRAMES)
        self._before_retry: tuple[tuple[str, np.ndarray], ...] | None = None
        self.reason = ""
        self._detail = ""
        self.evidence_frame: Path | None = None

    def observe(self, screen: "np.ndarray") -> None:
        self.evidence_frame = None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._recent.append((stamp, screen.copy()))

    def freeze(self, reason: str, detail: str = "") -> None:
        if not self.reason:
            self.reason = reason
            self._detail = detail
            self._before_retry = tuple(self._recent)

    def recovered(self, reason: str) -> None:
        if self.reason == reason:
            self.reason = ""
            self._detail = ""
            self._before_retry = None

    def save(self, directory: Path, error: str, log_path: Path | None = None) -> None:
        import cv2

        session_file = os.environ.get(FAILURE_WINDOW_ENV)
        destination = Path(session_file) if session_file else directory / "last_failure.zip"
        # Daily routes run sequentially in the worker. Later failures share this destination.
        if session_file and destination.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
            staging = Path(tmp.name)
        try:
            with ZipFile(staging, "w") as archive:
                archive.writestr("incident.json", json.dumps({
                    "route": directory.name.removeprefix("epic7_"),
                    "error": error,
                    "reason": self._detail or self.reason or "路线抛出异常",
                    "worker_account": os.environ.get(ACCOUNT_ENV, "") if session_file else "",
                    "evidence_dir": self.evidence_frame.stem if self.evidence_frame else "",
                }, ensure_ascii=False))
                frames = self._recent if self._before_retry is None else self._before_retry
                for index, (stamp, rgb) in enumerate(frames, 1):
                    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                    if not ok:
                        raise OSError("诊断帧编码失败")
                    archive.writestr(f"frames/{index:02d}_{stamp}.png", encoded.tobytes())
                if log_path is not None:
                    for path in (log_path, Path(f"{log_path}.1")):
                        if path.is_file():
                            archive.write(path, f"logs/{path.name}")
                if self.evidence_frame:
                    for name in ("evidence.json", "source.png", "target.png"):
                        path = self.evidence_frame.with_suffix("") / name
                        if path.is_file():
                            archive.write(path, f"evidence/{name}")
            staging.replace(destination)
        finally:
            staging.unlink(missing_ok=True)


def freeze_before_retry(runtime: "Runtime", reason: str, detail: str = "") -> None:
    history = getattr(runtime, "failure_history", None)
    if isinstance(history, FailureHistory):
        history.freeze(reason, detail)


def retry_recovered(runtime: "Runtime", reason: str) -> None:
    history = getattr(runtime, "failure_history", None)
    if isinstance(history, FailureHistory):
        history.recovered(reason)
