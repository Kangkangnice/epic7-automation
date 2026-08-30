from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
from auto_game_unified.core.recovery import RecoveryBlocked
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.modes import get_mode


ROOT = Path(__file__).resolve().parents[1]
RESULT_FIXTURES = {
    "story": "tests/fixtures/epic7_story/results.png",
    "arena": "tests/fixtures/epic7_arena/result.png",
    "expedition": "tests/fixtures/epic7_expedition/result.png",
    "fodder": "tests/fixtures/epic7_fodder/results.png",
}


@pytest.fixture
def adapter_case():
    def build(mode: str, case: str):
        template_root = ROOT / "games" / "epic7" / "templates"
        spec = get_mode(mode)
        machine = spec.build_machine(template_root, spec.default_state)
        if case == "result":
            path = ROOT / RESULT_FIXTURES[mode]
            image = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        else:
            image = np.zeros((1132, 1982, 3), dtype=np.uint8)
        return machine, image

    return build


@pytest.fixture
def runner_case(tmp_path):
    def build(mode: str):
        template_root = ROOT / "games" / "epic7" / "templates"
        spec = get_mode(mode)
        machine = spec.build_machine(template_root, spec.default_state)
        runtime = Runtime(
            lambda: np.zeros((1132, 1982, 3), dtype=np.uint8),
            lambda point: None,
            diagnostic_dir=tmp_path / mode,
            emit=lambda line: None,
        )
        recoveries: list[str] = []
        runner = spec.runner_type(
            machine,
            runtime,
            recovery=lambda: recoveries.append("recover"),
        )
        return runner, recoveries

    return build


@pytest.mark.parametrize("mode", ["story", "arena", "expedition", "fodder"])
def test_unknown_auto_state_never_exposes_a_click_point(mode, adapter_case):
    machine, screen = adapter_case(mode, "unknown")
    observation = machine.observe_battle(screen, None)
    assert observation.auto_state is AutoBattleState.UNKNOWN
    assert observation.auto_point is None


@pytest.mark.parametrize("mode", ["story", "arena", "expedition", "fodder"])
def test_result_anchor_is_outside_the_committed_battle(mode, adapter_case):
    machine, screen = adapter_case(mode, "result")
    observation = machine.observe_battle(screen, None)
    assert observation.result_visible is True
    assert observation.pre_battle_visible is False


@pytest.mark.parametrize("mode", ["story", "arena", "expedition", "fodder"])
def test_runner_uses_the_same_recovery_gate_as_its_supervisor(mode, runner_case):
    runner, _ = runner_case(mode)
    assert runner.battle_supervisor.gate is runner.recovery_gate


@pytest.mark.parametrize("mode", ["story", "arena", "expedition", "fodder"])
def test_committed_battle_blocks_every_mode_recovery_callback(mode, runner_case):
    runner, recoveries = runner_case(mode)
    runner.recovery_gate.lock(mode=mode, cycle=1)
    with pytest.raises(RecoveryBlocked):
        runner.recovery("cross-mode invariant")
    runner.recovery_gate.unlock()
    assert recoveries == []
