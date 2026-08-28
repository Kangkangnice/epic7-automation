import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from auto_game_unified.core.evidence_diagnostics import (
    save_runtime_evidence_diagnostic,
)
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.arena import ArenaRunner, ArenaState
from auto_game_unified.games.epic7.evidence.common import (
    AtomEvidence,
    EvidenceProfile,
    PageEvidence,
)
from auto_game_unified.games.epic7.expedition import ExpeditionRunner, ExpeditionState
from auto_game_unified.games.epic7.hero_synthesis import HeroSynthRunner
from auto_game_unified.games.epic7.runner_base import ModeRunnerBase
from auto_game_unified.games.epic7.story import StoryRunner


class FakeRuntime:
    def __init__(self, diagnostic_dir: Path):
        self.diagnostic_dir = diagnostic_dir
        self.messages = []

    def log(self, message: str) -> None:
        self.messages.append(message)

    def save_diagnostic(self, label: str, screen: np.ndarray) -> Path:
        path = self.diagnostic_dir / f"{label}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(screen, cv2.COLOR_RGB2BGR))
        return path


def _profile(tmp_path: Path) -> tuple[EvidenceProfile, np.ndarray]:
    template = np.arange(100, dtype=np.uint8).reshape(10, 10)
    template_rgb = np.repeat(template[:, :, None], 3, axis=2)
    cv2.imwrite(
        str(tmp_path / "anchor.png"),
        cv2.cvtColor(template_rgb, cv2.COLOR_RGB2BGR),
    )
    screen = np.zeros((40, 40, 3), dtype=np.uint8)
    screen[10:20, 10:20] = template_rgb
    profile = EvidenceProfile(
        atoms={
            "anchor": AtomEvidence(
                "anchor",
                "anchor.png",
                (10, 10, 20, 20),
                0.90,
                reference_size=(40, 40),
            )
        },
        pages=(PageEvidence("sample.page", required=("anchor",)),),
        config_path="games/epic7/evidence/sample.py",
        template_root=tmp_path,
    )
    return profile, screen


def test_runtime_evidence_diagnostic_writes_self_contained_profile_report(tmp_path):
    profile, screen = _profile(tmp_path)
    runtime = FakeRuntime(tmp_path / "diagnostics")
    legacy = runtime.save_diagnostic("timeout_list", screen)

    output = save_runtime_evidence_diagnostic(
        runtime,
        screen,
        profile,
        legacy_path=legacy,
        mode="主线",
        action="start_mission",
        source="story.ready",
        targets=("story.battle",),
        attempt=4,
        conclusion="目标页面未出现",
    )

    assert output == legacy.with_suffix("") / "evidence.json"
    assert (output.parent / "screen.png").is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["evidence"]["profile"]["config"] == profile.config_path
    assert payload["evidence"]["atoms"]["anchor"]["region"] == [10, 10, 20, 20]
    assert payload["evidence"]["atoms"]["anchor"]["score"] >= 0.90
    assert payload["evidence"]["pages"]["sample.page"]["state"] == "SAFE"


def test_runtime_evidence_diagnostic_resolves_relative_legacy_path_under_runtime_dir(
    tmp_path, monkeypatch
):
    profile, screen = _profile(tmp_path)
    runtime = FakeRuntime(tmp_path / "diagnostics")
    monkeypatch.chdir(tmp_path)
    runtime.save_diagnostic("relative", screen)

    output = save_runtime_evidence_diagnostic(
        runtime,
        screen,
        profile,
        legacy_path=Path("relative.png"),
        mode="竞技场",
        action="refresh-opponents",
        source="arena.list",
        targets=("arena.list",),
        attempt=1,
        conclusion="目标页面未出现",
    )

    assert output == runtime.diagnostic_dir / "relative" / "evidence.json"


def test_runtime_prunes_evidence_directory_with_legacy_png(tmp_path):
    profile, screen = _profile(tmp_path)
    diagnostic_dir = tmp_path / "diagnostics"
    runtime = Runtime(
        lambda: screen,
        lambda point: None,
        diagnostic_dir=diagnostic_dir,
        diagnostic_limit=2,
    )
    saved = []
    for index in range(3):
        legacy = runtime.save_diagnostic(f"failure_{index}", screen)
        output = save_runtime_evidence_diagnostic(
            runtime,
            screen,
            profile,
            legacy_path=legacy,
            mode="主线",
            action="observe",
            source="story.page",
            targets=(),
            attempt=1,
            conclusion="页面失败",
        )
        assert output is not None
        saved.append((legacy, output.parent))

    assert not saved[0][0].exists()
    assert not saved[0][1].exists()
    assert all(path.exists() and directory.exists() for path, directory in saved[1:])


def test_runtime_evidence_diagnostic_never_raises_when_failure_log_also_fails(
    tmp_path,
):
    profile, screen = _profile(tmp_path)
    missing_profile = EvidenceProfile(
        atoms={
            "missing": AtomEvidence(
                "missing", "missing.png", (0, 0, 10, 10), 0.90
            )
        },
        config_path=profile.config_path,
        template_root=tmp_path,
    )
    runtime = FakeRuntime(tmp_path / "diagnostics")
    legacy = runtime.save_diagnostic("missing_template", screen)
    runtime.log = lambda message: (_ for _ in ()).throw(RuntimeError("log failed"))

    output = save_runtime_evidence_diagnostic(
        runtime,
        screen,
        missing_profile,
        legacy_path=legacy,
        mode="远征",
        action="observe",
        source="expedition.page",
        targets=(),
        attempt=1,
        conclusion="页面失败",
    )

    assert output is None


def test_formal_route_failure_entry_points_write_evidence_packs(tmp_path):
    profile, screen = _profile(tmp_path)
    runtime = FakeRuntime(tmp_path / "diagnostics")
    machine = SimpleNamespace(
        templates=SimpleNamespace(evidence=profile),
        state=SimpleNamespace(value="list"),
    )

    base = object.__new__(ModeRunnerBase)
    base.machine = machine
    base.runtime = runtime
    base._MODE_LABEL = "主线"
    legacy = runtime.save_diagnostic("story_timeout", screen)
    story_output = base._save_failure_diagnostic(
        legacy, screen, action=None, attempt=1, conclusion="页面超时"
    )

    arena = object.__new__(ArenaRunner)
    arena.machine = SimpleNamespace(
        templates=SimpleNamespace(evidence=profile),
        state=ArenaState.LIST,
    )
    arena.runtime = runtime
    legacy = runtime.save_diagnostic("arena_timeout", screen)
    arena_output = arena._save_failure_diagnostic(
        legacy, screen, action=None, attempt=1, conclusion="页面超时"
    )

    expedition = object.__new__(ExpeditionRunner)
    expedition.machine = SimpleNamespace(
        templates=SimpleNamespace(evidence=profile),
        state=ExpeditionState.HOME,
    )
    expedition.runtime = runtime
    expedition._diagnostic("expedition_timeout", screen)

    assert story_output.is_file()
    assert arena_output.is_file()
    assert (runtime.diagnostic_dir / "expedition_timeout" / "evidence.json").is_file()
    assert issubclass(StoryRunner, ModeRunnerBase)
    assert issubclass(HeroSynthRunner, ModeRunnerBase)
