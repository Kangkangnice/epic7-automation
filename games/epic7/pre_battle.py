from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template
from auto_game_unified.games.epic7.evidence.pre_battle import (
    QUICK_BUTTON_THRESHOLD,
    QUICK_SWITCH_THRESHOLD,
    REFERENCE_SIZE,
    REGION,
    PreBattleEvidenceState,
    classify_pre_battle_evidence,
)


class PreBattleMode(Enum):
    NORMAL = "normal"
    QUICK = "quick"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuickBattleTemplates:
    quick_button: np.ndarray
    quick_switch: np.ndarray


@dataclass(frozen=True)
class PreBattleObservation:
    mode: PreBattleMode
    normal_score: float = 0.0
    quick_score: float = 0.0
    switch_score: float = 0.0
    switch_point: tuple[int, int] | None = None


def load_quick_battle_templates(template_dir: Path) -> QuickBattleTemplates:
    return QuickBattleTemplates(
        quick_button=load_template(str(template_dir / "quick_battle_button.png")),
        quick_switch=load_template(str(template_dir / "quick_battle_switch.png")),
    )


def load_simulator_quick_battle_detector(
    template_dir: Path,
) -> "QuickBattleDetector | None":
    template_root = (
        template_dir.parent
        if template_dir.name in {"story", "fodder", "expedition"}
        else template_dir
    )
    if template_root.name != "templates":
        return None
    return QuickBattleDetector(
        load_quick_battle_templates(template_root / "global")
    )


class QuickBattleDetector:
    """Classify a simulator pre-battle page without inspecting animated heroes."""

    _REFERENCE_SIZE = REFERENCE_SIZE
    _REGION = REGION
    _BUTTON_THRESHOLD = QUICK_BUTTON_THRESHOLD
    _SWITCH_THRESHOLD = QUICK_SWITCH_THRESHOLD

    def __init__(self, templates: QuickBattleTemplates) -> None:
        self.templates = templates

    def _locate(self, screen: np.ndarray, template: np.ndarray, threshold: float):
        return find_template(
            screen,
            template,
            threshold,
            region=self._REGION,
            reference_size=self._REFERENCE_SIZE,
        )

    def observe(
        self,
        screen: np.ndarray,
        *,
        normal_start: Match | None,
    ) -> PreBattleObservation:
        quick = self._locate(
            screen,
            self.templates.quick_button,
            self._BUTTON_THRESHOLD,
        )
        switch = self._locate(
            screen,
            self.templates.quick_switch,
            self._SWITCH_THRESHOLD,
        )
        state = classify_pre_battle_evidence(
            normal_observed=normal_start is not None,
            quick_observed=quick is not None,
            switch_observed=switch is not None,
        )
        if state is PreBattleEvidenceState.NORMAL:
            return PreBattleObservation(
                PreBattleMode.NORMAL,
                normal_score=normal_start.score,
            )
        if state is PreBattleEvidenceState.QUICK:
            return PreBattleObservation(
                PreBattleMode.QUICK,
                quick_score=quick.score,
                switch_score=switch.score,
                switch_point=switch.center,
            )
        return PreBattleObservation(PreBattleMode.UNKNOWN)


def observe_pre_battle(
    detector: QuickBattleDetector | None,
    screen: np.ndarray,
    *,
    normal_start: Match | None,
) -> PreBattleObservation:
    if detector is not None:
        return detector.observe(screen, normal_start=normal_start)
    if normal_start is not None:
        return PreBattleObservation(
            PreBattleMode.NORMAL,
            normal_score=normal_start.score,
        )
    return PreBattleObservation(PreBattleMode.UNKNOWN)
