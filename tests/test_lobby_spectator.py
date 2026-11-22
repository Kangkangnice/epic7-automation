"""大厅观赏模式兜底：判据 + 有界唤醒（2026-11-22）。

观赏模式 = 大厅静置几秒后切入的整屏英雄立绘动效，左右菜单 / 底部图标 / 顶部 HUD
**全部消失**，导航层所有大厅锚点归零 ⇒ ``observe()`` 报 unknown ⇒ 等大厅那一步
干等到超时。真机帧已固化为夹具 ``lobby_spectator_live_20261122.png``。

本文件守住三条底线：
1. 判据靠「有效帧 + 在动 + 不是战斗」的否定证据，**不认具体背景**（背景随英雄变）；
2. 唤醒有界（与远征营地待机一致 = 2 次），点完不在这里验收，交还正常 observe 链路；
3. 非「等大厅」上下文、干跑、锁定一律不点 —— 2026-09-26 删掉的「认不出就点中间」
   正是在这些护栏缺失时对着赛季卡片误开入口。
"""

from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.unknown_screen import (
    LobbySpectatorWake,
    SpectatorWakeResult,
    is_lobby_spectator,
)


ROOT = Path(__file__).resolve().parents[1]
NAV_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_navigation"


def fixture(name: str, group: str = "epic7_navigation") -> np.ndarray:
    path = ROOT / "tests" / "fixtures" / group / f"{name}.png"
    return np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]


def spectator_frame() -> np.ndarray:
    return fixture("lobby_spectator_live_20261122")


def moving_frame(seed: int = 1) -> np.ndarray:
    """在观赏模式帧的渲染区造一点位移，模拟立绘动画（保留四周黑边）。"""
    base = spectator_frame()
    frame = base.copy()
    frame[200:900, 300:1500] = np.roll(base[200:900, 300:1500], seed, axis=1)
    return frame


def black_frame() -> np.ndarray:
    return np.zeros((1132, 1982, 3), dtype=np.uint8)


# ---- 判据 ------------------------------------------------------------------------


def test_is_lobby_spectator_needs_two_frames():
    """单帧不下结论：首帧只在攒证据，不动手。"""
    assert is_lobby_spectator(spectator_frame(), None) is False
    assert is_lobby_spectator(moving_frame(), spectator_frame()) is True


def test_is_lobby_spectator_rejects_black_and_static():
    assert is_lobby_spectator(black_frame(), black_frame()) is False
    # 同一帧重复 —— 没有「在动」，不成立。
    static = spectator_frame()
    assert is_lobby_spectator(static, static) is False


def test_is_lobby_spectator_rejects_normal_lobby_and_battle():
    """正常大厅（UI 齐全、几乎静止）与战斗页都不能被当成观赏模式。"""
    lobby = fixture("lobby")
    assert is_lobby_spectator(lobby, lobby) is False
    battle = fixture("battle_auto_on_live_20260809", "epic7_story")
    moved = battle.copy()
    moved[200:900, 300:1500] = np.roll(battle[200:900, 300:1500], 8, axis=1)
    assert is_lobby_spectator(moved, battle) is False


# ---- 有界唤醒 --------------------------------------------------------------------


def _runtime(clicks, *, dry_run=False, logs=None):
    return Runtime(
        lambda: moving_frame(),
        clicks.append,
        dry_run=dry_run,
        emit=(logs.append if logs is not None else (lambda _m: None)),
    )


def test_wake_clicks_center_at_most_twice():
    """画面一直在动却始终没恢复 UI ⇒ 最多点 2 次（与远征一致），之后不再点。"""
    clicks: list[tuple[int, int]] = []
    wake = LobbySpectatorWake(_runtime(clicks))
    results = [wake.handle(moving_frame(i), context="等大厅") for i in range(1, 7)]
    assert clicks == [(1000, 600), (1000, 600)]
    assert results[0] is SpectatorWakeResult.WAITING
    assert results.count(SpectatorWakeResult.CLICKED) == 2
    assert results[-1] is SpectatorWakeResult.EXHAUSTED


def test_wake_never_clicks_on_one_shot_without_motion():
    """画面不动 ⇒ 只 WAITING，一个点都不发。"""
    clicks: list[tuple[int, int]] = []
    wake = LobbySpectatorWake(_runtime(clicks))
    static = spectator_frame()
    results = [wake.handle(static, context="等大厅") for _ in range(4)]
    assert clicks == []
    assert all(r is SpectatorWakeResult.WAITING for r in results)


def test_wake_skips_outside_lobby_context():
    """非「等大厅」上下文一律 SKIPPED —— 别的地方认不出时不许点中心。"""
    clicks: list[tuple[int, int]] = []
    wake = LobbySpectatorWake(_runtime(clicks))
    assert wake.handle(moving_frame(1), context="战斗") is SpectatorWakeResult.SKIPPED
    assert wake.handle(moving_frame(2), context="导航:等待竞技场模式选择") is SpectatorWakeResult.SKIPPED
    assert clicks == []


def test_wake_skips_in_dry_run():
    clicks: list[tuple[int, int]] = []
    wake = LobbySpectatorWake(_runtime(clicks, dry_run=True))
    wake.handle(spectator_frame(), context="等大厅")
    assert wake.handle(moving_frame(), context="等大厅") is SpectatorWakeResult.SKIPPED
    assert clicks == []


def test_wake_skips_when_recovery_gate_locked():
    clicks: list[tuple[int, int]] = []
    gate = RecoveryGate()
    gate.lock(mode="arena", cycle=1)
    wake = LobbySpectatorWake(_runtime(clicks), recovery_gate=gate)
    wake.handle(spectator_frame(), context="等大厅")
    assert wake.handle(moving_frame(), context="等大厅") is SpectatorWakeResult.SKIPPED
    assert clicks == []


def test_reset_restores_attempt_budget():
    """换页（调用方 reset）后重新给满 2 次额度。"""
    clicks: list[tuple[int, int]] = []
    wake = LobbySpectatorWake(_runtime(clicks))
    for i in range(1, 5):
        wake.handle(moving_frame(i), context="等大厅")
    assert len(clicks) == 2
    wake.reset()
    wake.handle(moving_frame(7), context="等大厅")
    assert wake.handle(moving_frame(8), context="等大厅") is SpectatorWakeResult.CLICKED
    assert len(clicks) == 3


# ---- 导航层集成：等大厅时从「干等超时」变成「点中心后恢复」------------------------


def test_wait_for_lobby_clicks_center_then_proceeds_on_recovery():
    """真机观赏模式帧：等大厅时点一次中心，画面恢复大厅后导航继续，不超时。"""
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    spectator = [spectator_frame(), moving_frame(1)]  # 两帧不同 = 立绘在动
    lobby = fixture("lobby")
    state = {"clicked": False, "i": 0}

    def capture():
        if state["clicked"]:
            return lobby
        frame = spectator[state["i"] % len(spectator)]
        state["i"] += 1
        return frame

    def click(point):
        clicks.append(point)
        state["clicked"] = True

    from auto_game_unified.games.epic7.navigation import (
        Epic7Navigator,
        build_navigation_templates,
    )

    runtime = Runtime(capture, click, emit=logs.append)
    nav = Epic7Navigator(
        build_navigation_templates(ROOT / "games" / "epic7" / "templates"),
        runtime,
        sleep=lambda _: None,
        transition_frames=12,
    )

    result = nav._wait_for_page("lobby")

    assert clicks == [(1000, 600)]
    assert np.array_equal(result, lobby)
    assert any("观赏模式" in line for line in logs), logs
