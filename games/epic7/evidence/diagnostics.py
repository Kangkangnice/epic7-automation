"""Epic7 视觉证据诊断：把「证据画像」打到当前帧上，产出可独立阅读的诊断包。

审查 D：这部分直接依赖 Epic7 的证据模型（``evidence.common``），原先放在
``core.evidence_diagnostics`` 里，和 ``pyproject.toml`` 的「core 不依赖 games」
约定相反。通用的写图/写 JSON 留在 core；这里只放游戏侧的画像检查与调用。

⚠️ 诊断失败**绝不能**取代业务失败原因：调用方用 ``try/except`` 包住，
出错只记一行日志（见 ``save_runtime_evidence_diagnostic``）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from auto_game_unified.core.evidence_diagnostics import write_evidence_diagnostic
from auto_game_unified.core.matcher import Match, best_match_with_fallback, load_template
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
        # 等于骗人。口径由证据画像声明，这里**只转发**。
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
