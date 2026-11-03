"""Read-only inspection and self-contained diagnostics for visual evidence."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from .matcher import (
    Match,
    best_match_with_fallback,
    load_template,
)
from auto_game_unified.games.epic7.evidence.common import (
    AtomObservation,
    EvidenceProfile,
    EvidenceState,
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
        # ⚠️ 必须跟路线走同一个口径与同一套兜底：诊断包里的分数要与实跑判定出自
        # 同一把尺子，否则工具报「0.841 未过阈」而实跑已经用低通/扫尺寸兜底过了，
        # 等于骗人。口径由证据画像声明，这里**只转发**（从前非原样口径的那一支
        # 直连 `find_best_template`，兜底对它不生效 —— 与路线层同一个坑）。
        match: Match | None = best_match_with_fallback(
            key,
            screen,
            template,
            atom.threshold,
            region=atom.region,
            reference_size=atom.reference_size,
            mode=atom.match_mode,
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
            scale=match.scale if match is not None else None,
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


def save_runtime_evidence_diagnostic(
    runtime: Any,
    screen: np.ndarray,
    profile: EvidenceProfile | None,
    *,
    legacy_path: Path,
    mode: str,
    action: str,
    source: str,
    targets: Sequence[str],
    attempt: int,
    conclusion: str,
) -> Path | None:
    """Add a self-contained evidence pack beside an existing diagnostic PNG.

    This is deliberately best-effort: evidence collection must never replace
    the original route failure with a secondary diagnostics error.
    """
    if (
        getattr(runtime, "diagnostic_dir", None) is None
        or profile is None
        or profile.template_root is None
    ):
        return None
    try:
        diagnostic_root = Path(runtime.diagnostic_dir)
        if legacy_path.is_absolute():
            resolved_legacy = legacy_path
        elif legacy_path.is_file():
            resolved_legacy = legacy_path.resolve()
        else:
            resolved_legacy = diagnostic_root / legacy_path
        if not resolved_legacy.is_file():
            return None
        inspection = inspect_profile(screen, profile, profile.template_root)
        # 显式标注：三个键的值类型不同（str / dict[str, Any] / dict[str, str]），不标的话
        # mypy 会推成 dict[str, object]，与 write_evidence_diagnostic 的参数类型对不上。
        evidence: dict[str, Mapping[str, Any]] = {
            "profile": {
                "config": profile.config_path,
                "template_root": str(profile.template_root),
            },
            "atoms": {
                key: asdict(observation)
                for key, observation in inspection.atoms.items()
            },
            "pages": {
                key: {"state": state.value}
                for key, state in inspection.pages.items()
            },
        }
        output = write_evidence_diagnostic(
            resolved_legacy.with_suffix(""),
            screen,
            mode=mode,
            action=action,
            source=source,
            targets=targets,
            attempt=attempt,
            evidence=evidence,
            conclusion=conclusion,
        )
        runtime.log(f"已保存视觉证据包 {output}")
        return output
    except Exception as error:  # diagnostics must not mask the business failure
        try:
            runtime.log(f"视觉证据诊断失败：{error}")
        except Exception:
            pass
        return None
