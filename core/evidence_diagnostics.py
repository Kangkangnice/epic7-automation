"""Read-only inspection and self-contained diagnostics for visual evidence."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from .matcher import Match, find_best_template, load_template
from auto_game_unified.games.epic7.evidence.common import (
    AtomObservation,
    EvidenceProfile,
    EvidenceState,
    validate_profile,
)


@dataclass(frozen=True)
class ProfileInspection:
    atoms: dict[str, AtomObservation]
    pages: dict[str, EvidenceState]


def inspect_profile(
    screen: np.ndarray,
    profile: EvidenceProfile,
    template_root: Path,
) -> ProfileInspection:
    observations: dict[str, AtomObservation] = {}
    for key, atom in profile.atoms.items():
        template_path = template_root / atom.template_path
        if not template_path.is_file() and not atom.required:
            observations[key] = AtomObservation(
                key=key,
                template=str(template_path),
                config=profile.config_path,
                region=atom.region,
                reference_size=atom.reference_size,
                threshold=atom.threshold,
                observed=False,
                score=None,
                center=None,
            )
            continue
        template = load_template(str(template_path))
        match: Match | None = find_best_template(
            screen,
            template,
            region=atom.region,
            reference_size=atom.reference_size,
        )
        observed = match is not None and match.score >= atom.threshold
        observations[key] = AtomObservation(
            key=key,
            template=str(template_path),
            config=profile.config_path,
            region=atom.region,
            reference_size=atom.reference_size,
            threshold=atom.threshold,
            observed=observed,
            score=match.score if match is not None else None,
            center=match.center if match is not None else None,
        )
    pages = profile.evaluate_pages(observations)
    return ProfileInspection(atoms=observations, pages=pages)


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
