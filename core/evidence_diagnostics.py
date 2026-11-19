"""Generic, read-only diagnostics writer for visual evidence.

⚠️ 这里**只放与游戏无关的写盘逻辑**（图 + JSON）。Epic7 的「证据画像」检查
（``inspect_profile`` / ``save_runtime_evidence_diagnostic``）在
``games/epic7/evidence/diagnostics.py`` —— core 不反向依赖 games（审查 D，
见 ``tests/test_core_import_boundary.py``）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


def _write_rgb_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)):
        raise OSError(f"无法写入诊断图片: {path}")


def _crop(
    screen: np.ndarray,
    region: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, width, height = region
    x1 = max(0, min(screen.shape[1], x))
    y1 = max(0, min(screen.shape[0], y))
    x2 = max(x1, min(screen.shape[1], x + width))
    y2 = max(y1, min(screen.shape[0], y + height))
    return screen[y1:y2, x1:x2]


def write_evidence_diagnostic(
    directory: Path,
    screen: np.ndarray,
    *,
    mode: str,
    action: str,
    source: str,
    targets: Sequence[str],
    attempt: int,
    evidence: Mapping[str, Mapping[str, Any]],
    conclusion: str,
    source_region: tuple[int, int, int, int] | None = None,
    target_region: tuple[int, int, int, int] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _write_rgb_png(directory / "screen.png", screen)
    if source_region is not None:
        _write_rgb_png(directory / "source.png", _crop(screen, source_region))
    if target_region is not None:
        _write_rgb_png(directory / "target.png", _crop(screen, target_region))

    payload = {
        "mode": mode,
        "action": action,
        "source": source,
        "targets": list(targets),
        "attempt": attempt,
        "evidence": evidence,
        "conclusion": conclusion,
    }
    output = directory / "evidence.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output
