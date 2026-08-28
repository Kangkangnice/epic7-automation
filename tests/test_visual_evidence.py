from pathlib import Path

from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    EvidenceState,
    PageEvidence,
    validate_profile,
)


def test_page_evidence_is_safe_only_when_required_and_any_group_match():
    page = PageEvidence(
        key="arena.list",
        required=("list_ready",),
        any_of=(("opponent_row", "opponent_detail"),),
        forbidden=("network_retry",),
    )

    assert page.evaluate({"list_ready": True, "opponent_row": True}) is EvidenceState.SAFE
    assert page.evaluate({"list_ready": True, "opponent_row": False}) is EvidenceState.UNKNOWN
    assert (
        page.evaluate(
            {"list_ready": True, "opponent_row": True, "network_retry": True}
        )
        is EvidenceState.UNSAFE
    )


def test_page_evidence_missing_observation_is_unknown():
    page = PageEvidence(key="arena.team", required=("battle_start",))

    assert page.evaluate({}) is EvidenceState.UNKNOWN
    assert page.evaluate({"battle_start": False}) is EvidenceState.UNKNOWN


def test_validate_evidence_profile_reports_missing_template_bad_threshold_and_unknown_reference(
    tmp_path: Path,
):
    profile = EvidenceProfile(
        atoms={
            "list_ready": AtomEvidence(
                key="list_ready",
                template_path="missing.png",
                region=(0, 0, 10, 10),
                threshold=1.2,
            )
        },
        pages=(PageEvidence("arena.list", required=("missing_atom",)),),
    )

    errors = validate_profile(profile, tmp_path)
    joined = " ".join(errors)
    assert "模板不存在" in joined
    assert "阈值" in joined
    assert "引用不存在" in joined


def test_validate_evidence_profile_accepts_valid_profile(tmp_path: Path):
    (tmp_path / "list_ready.png").write_bytes(b"template")
    profile = EvidenceProfile(
        atoms={
            "list_ready": AtomEvidence(
                key="list_ready",
                template_path="list_ready.png",
                region=(0, 0, 10, 10),
                threshold=0.9,
            )
        },
        pages=(PageEvidence("arena.list", required=("list_ready",)),),
    )

    assert validate_profile(profile, tmp_path) == []
