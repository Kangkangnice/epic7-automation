from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.core.battle_supervisor import AutoBattleState
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
        return spec.runner_type(machine, runtime)

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
    runner = runner_case(mode)
    assert runner.battle_supervisor.gate is runner.recovery_gate


@pytest.mark.parametrize("mode", ["story", "arena", "expedition", "fodder"])
def test_a_committed_battle_has_no_channel_that_can_leave_it(mode, runner_case):
    """已承诺战斗期间：锁必须锁上，而且 runner 上**没有任何**「恢复」入口。

    2026-09-26 之前这条是「锁住各模式的恢复回调」；用户拍板「回家就是结束」之后，
    回调本身已整段删除（``recover()`` / ``RecoveryBlocked``）⇒ 断言换成
    「锁还在 + 那条通道不存在」。这条是跨路线的：四条路线一起守，谁单独加回来都会红。
    """
    runner = runner_case(mode)

    runner.recovery_gate.lock(mode=mode, cycle=1)

    assert runner.recovery_gate.locked is True
    for absent in ("recovery", "recover"):
        assert not hasattr(runner, absent), f"{mode} 又多了一条离开战斗的通道：{absent}"
