import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from auto_game_unified.core.evidence_diagnostics import (
    inspect_profile,
    write_evidence_diagnostic,
)
from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    EvidenceState,
    PageEvidence,
)


def _profile(tmp_path: Path) -> EvidenceProfile:
    template = np.arange(100, dtype=np.uint8).reshape(10, 10)
    template_rgb = np.repeat(template[:, :, None], 3, axis=2)
    cv2.imwrite(
        str(tmp_path / "anchor.png"),
        cv2.cvtColor(template_rgb, cv2.COLOR_RGB2BGR),
    )
    return EvidenceProfile(
        atoms={
            "anchor": AtomEvidence(
                "anchor",
                "anchor.png",
                (10, 10, 20, 20),
                0.9,
                reference_size=(40, 40),
            )
        },
        pages=(PageEvidence("sample.page", required=("anchor",)),),
    )


def test_inspect_profile_reports_match_score_and_page_state(tmp_path: Path):
    profile = _profile(tmp_path)
    screen = np.zeros((40, 40, 3), dtype=np.uint8)
    template = np.arange(100, dtype=np.uint8).reshape(10, 10)
    screen[10:20, 10:20] = np.repeat(template[:, :, None], 3, axis=2)

    report = inspect_profile(screen, profile, tmp_path)

    assert report.atoms["anchor"].observed is True
    assert report.atoms["anchor"].score >= 0.9
    assert report.pages["sample.page"] is EvidenceState.SAFE


def test_inspect_profile_keeps_score_below_threshold(tmp_path: Path):
    profile = _profile(tmp_path)
    atom = profile.atom("anchor")
    profile = EvidenceProfile(
        atoms={
            "anchor": AtomEvidence(
                atom.key,
                atom.template_path,
                atom.region,
                0.9999,
                reference_size=atom.reference_size,
            )
        },
        pages=profile.pages,
    )
    template = np.arange(100, dtype=np.uint8).reshape(10, 10)
    changed = template.copy()
    changed[:3, :3] = 0
    screen = np.zeros((40, 40, 3), dtype=np.uint8)
    screen[10:20, 10:20] = np.repeat(changed[:, :, None], 3, axis=2)

    report = inspect_profile(screen, profile, tmp_path)
    observation = report.atoms["anchor"]

    assert observation.observed is False
    assert observation.score is not None
    assert observation.score < observation.threshold


def test_write_evidence_diagnostic_saves_json_and_crops(tmp_path: Path):
    screen = np.zeros((40, 50, 3), dtype=np.uint8)
    output = write_evidence_diagnostic(
        tmp_path / "diagnostic",
        screen,
        mode="竞技场",
        action="challenge",
        source="arena.list",
        targets=("arena.selected",),
        attempt=2,
        evidence={
            "list_ready": {
                "score": 0.91,
                "threshold": 0.88,
                "observed": True,
            }
        },
        conclusion="来源仍在，目标未进入",
        source_region=(0, 0, 20, 20),
        target_region=(20, 20, 20, 20),
    )

    assert output == tmp_path / "diagnostic" / "evidence.json"
    assert (output.parent / "screen.png").is_file()
    assert (output.parent / "source.png").is_file()
    assert (output.parent / "target.png").is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "竞技场"
    assert payload["action"] == "challenge"
    assert payload["attempt"] == 2
    assert payload["evidence"]["list_ready"]["score"] == 0.91
    assert payload["conclusion"] == "来源仍在，目标未进入"


def test_check_evidence_rejects_unknown_mode(capsys):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "check_evidence.py"),
            "--mode",
            "unknown",
            "--screen",
            "missing.png",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "不支持的模式" in result.stdout


def test_check_evidence_prints_maintenance_location_and_region():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "check_evidence.py"),
            "--mode",
            "arena",
            "--screen",
            str(root / "tests" / "fixtures" / "epic7_arena" / "selected.png"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "config=" in result.stdout
    assert "region=" in result.stdout
    assert "reference_size=" in result.stdout
    assert "页面 key=arena.selected 状态=SAFE" in result.stdout
