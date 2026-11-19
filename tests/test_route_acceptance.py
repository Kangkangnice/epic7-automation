"""Release evidence must record complete, separate runs for the claimed target."""

import json
from pathlib import Path

import pytest

from auto_game_unified.tools.check_route_acceptance import main

REVISION = "a" * 40


@pytest.fixture
def evidence() -> dict:
    return {
        "route": "craft_equipment",
        "backend": "pc",
        "client": "STOVE build A",
        "revision": REVISION,
        "replay_cases": [
            "normal", "repeat", "overlay", "slow_or_frozen", "unknown", "end",
        ],
        "runs": [
            {
                "id": f"run-{index}",
                "route": "craft_equipment",
                "backend": "pc",
                "client": "STOVE build A",
                "revision": REVISION,
                "account": "A" if index < 6 else "B",
                "environment": "setup-1" if index < 6 else "setup-2",
                "day": f"2026-11-{16 + index % 3}",
                "scenario": "normal" if index < 6 else "alternate",
                "outcome": "completed",
                "terminal_verified": True,
            }
            for index in range(10)
        ] + [{
            "id": "known-end",
            "route": "craft_equipment",
            "backend": "pc",
            "client": "STOVE build A",
            "revision": REVISION,
            "account": "B",
            "environment": "setup-2",
            "day": "2026-11-18",
            "scenario": "expected_stop",
            "outcome": "expected_stop",
            "terminal_verified": True,
        }],
    }


def check(tmp_path: Path, evidence: dict, *, client: str = "STOVE build A") -> int:
    report = tmp_path / "acceptance.json"
    report.write_text(json.dumps(evidence), encoding="utf-8")
    return main([
        str(report), "--route", "craft_equipment", "--backend", "pc",
        "--client", client, "--revision", REVISION,
    ])


def test_complete_evidence_passes(tmp_path, evidence, capsys):
    assert check(tmp_path, evidence) == 0
    assert "业务闭环 10/10，预期安全停止 1，人工中止 0" in capsys.readouterr().out


def test_one_development_smoke_does_not_qualify(tmp_path, evidence):
    evidence["runs"] = evidence["runs"][:1]
    assert check(tmp_path, evidence) == 1


@pytest.mark.parametrize("change", [
    {"id": "run-0"},
    {"outcome": "failed"},
    {"terminal_verified": False},
    {"outcome": "expected_stop"},
    {"day": "2026-11-32"},
    {"account": None},
])
def test_missing_or_failed_attempt_is_rejected(tmp_path, evidence, change):
    evidence["runs"][1].update(change)
    assert check(tmp_path, evidence) == 1


def test_interrupted_attempt_neither_passes_nor_adds_a_failure(tmp_path, evidence, capsys):
    evidence["runs"].append({
        **evidence["runs"][0], "id": "manual-stop", "outcome": "interrupted",
        "terminal_verified": False,
    })
    assert check(tmp_path, evidence) == 0
    assert "10/10" in capsys.readouterr().out


@pytest.mark.parametrize("field", ["account", "environment", "day", "scenario"])
def test_same_conditions_do_not_prove_compatibility(tmp_path, evidence, field):
    for run in evidence["runs"][:10]:
        run[field] = evidence["runs"][0][field]
    assert check(tmp_path, evidence) == 1


def test_expected_stop_needs_live_evidence_and_replay(tmp_path, evidence):
    evidence["runs"][-1]["terminal_verified"] = False
    assert check(tmp_path, evidence) == 1
    evidence["runs"][-1]["terminal_verified"] = True
    evidence["replay_cases"].remove("slow_or_frozen")
    assert check(tmp_path, evidence) == 1


def test_unsafe_action_blocks_even_an_expected_stop_scenario(tmp_path, evidence):
    evidence["runs"][-1]["outcome"] = "unsafe"
    assert check(tmp_path, evidence) == 1


def test_steam_cannot_inherit_stove_evidence(tmp_path, evidence):
    assert check(tmp_path, evidence, client="Steam build A") == 1


@pytest.mark.parametrize(("field", "value"), [
    ("route", "pet_adoption"),
    ("backend", "emulator"),
    ("client", "Steam build A"),
    ("revision", "b" * 40),
    ("client", None),
])
def test_mixed_targets_cannot_share_a_single_report(tmp_path, evidence, field, value):
    evidence["runs"][1][field] = value
    assert check(tmp_path, evidence) == 1
