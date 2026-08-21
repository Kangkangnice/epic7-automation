from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    find_friend_request_cancel,
    find_friendship_points_popup_close,
    find_intimacy_level_up_dismiss,
    find_network_retry,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_intimacy_level_up_templates,
    load_network_reconnect_templates,
)
from auto_game_unified.core.runtime import ManualStop, Runtime


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_global"
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"
STORY_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"


def load_screen(name: str = "network_reconnect.png") -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


@pytest.mark.parametrize(
    "fixture_name",
    ["network_reconnect.png", "network_reconnect_navigation.png"],
)
def test_network_retry_requires_message_and_retry_anchors(fixture_name):
    screen = load_screen(fixture_name)
    templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, templates)

    assert match is not None
    assert 875 <= match.center[0] <= 1050
    assert 695 <= match.center[1] <= 785


def test_network_retry_rejects_missing_message_or_retry_anchor():
    screen = load_screen()
    templates = load_network_reconnect_templates(TEMPLATES)
    without_message = screen.copy()
    without_message[490:590, 730:1250] = 0
    without_retry = screen.copy()
    without_retry[660:815, 820:1110] = 0

    assert find_network_retry(without_message, templates) is None
    assert find_network_retry(without_retry, templates) is None


def test_network_retry_rejects_normal_game_frames():
    templates = load_network_reconnect_templates(TEMPLATES)
    normal_paths = [
        ROOT / "tests" / "fixtures" / "epic7_arena" / "battle.png",
        ROOT / "tests" / "fixtures" / "epic7_arena" / "result.png",
        ROOT / "tests" / "fixtures" / "epic7_arena" / "list.png",
    ]

    for path in normal_paths:
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_network_retry(screen, templates) is None


def test_intimacy_level_up_requires_title_and_dismiss_anchors():
    screen = load_screen("intimacy_level_up_live_20260815.png")
    templates = load_intimacy_level_up_templates(TEMPLATES)

    match = find_intimacy_level_up_dismiss(screen, templates)

    assert match is not None
    assert 1040 <= match.center[0] <= 1240
    assert 850 <= match.center[1] <= 970


def test_intimacy_level_up_rejects_missing_title():
    screen = load_screen("intimacy_level_up_live_20260815.png")
    templates = load_intimacy_level_up_templates(TEMPLATES)
    without_title = screen.copy()
    without_title[230:370, 800:1450] = 0

    assert find_intimacy_level_up_dismiss(without_title, templates) is None


def test_intimacy_level_up_uses_safe_center_when_dismiss_prompt_is_animating():
    screen = load_screen("intimacy_level_up_live_20260815.png")
    templates = load_intimacy_level_up_templates(TEMPLATES)
    without_dismiss = screen.copy()
    without_dismiss[820:980, 900:1400] = 0

    match = find_intimacy_level_up_dismiss(without_dismiss, templates)

    assert match is not None
    assert match.center == (screen.shape[1] // 2, screen.shape[0] // 2)


def test_intimacy_level_up_rejects_normal_result_pages():
    templates = load_intimacy_level_up_templates(TEMPLATES)
    normal_paths = [
        ROOT / "tests" / "fixtures" / "epic7_story" / "results.png",
        ROOT / "tests" / "fixtures" / "epic7_fodder" / "results.png",
    ]

    for path in normal_paths:
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_intimacy_level_up_dismiss(screen, templates) is None


def test_friendship_points_popup_requires_title_and_close_anchor():
    popup = np.asarray(
        Image.open(STORY_FIXTURES / "friendship_points_popup.png").convert("RGB")
    )[:1132, :1982]
    templates = load_friendship_points_templates(TEMPLATES)
    without_title = popup.copy()
    without_title[150:330, 600:1400] = 0
    without_close = popup.copy()
    without_close[840:1030, 750:1200] = 0

    match = find_friendship_points_popup_close(
        popup, templates.title, templates.close
    )

    assert match is not None
    assert 750 <= match.center[0] <= 1200
    assert 840 <= match.center[1] <= 1030
    assert (
        find_friendship_points_popup_close(
            without_title, templates.title, templates.close
        )
        is None
    )
    assert (
        find_friendship_points_popup_close(
            without_close, templates.title, templates.close
        )
        is None
    )


def test_friend_request_requires_title_and_cancel_anchor():
    popup = np.asarray(
        Image.open(STORY_FIXTURES / "friend_request.png").convert("RGB")
    )[:1132, :1982]
    templates = load_friend_request_templates(STORY_TEMPLATES)
    without_title = popup.copy()
    without_title[240:400, 650:1350] = 0
    without_cancel = popup.copy()
    without_cancel[720:950, 550:1050] = 0

    match = find_friend_request_cancel(popup, templates.title, templates.cancel)

    assert match is not None
    assert 650 <= match.center[0] <= 950
    assert 790 <= match.center[1] <= 900
    assert find_friend_request_cancel(without_title, templates.title, templates.cancel) is None
    assert find_friend_request_cancel(without_cancel, templates.title, templates.cancel) is None


def test_global_guard_dismisses_friendship_and_friend_request_popups():
    friendship = np.asarray(
        Image.open(STORY_FIXTURES / "friendship_points_popup.png").convert("RGB")
    )[:1132, :1982]
    friend_request = np.asarray(
        Image.open(STORY_FIXTURES / "friend_request.png").convert("RGB")
    )[:1132, :1982]
    normal = np.asarray(
        Image.open(ROOT / "tests" / "fixtures" / "epic7_story" / "stage.png").convert("RGB")
    )[:1132, :1982]
    screens = iter([friendship, friendship, friend_request, friend_request, normal])
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    clock = FakeClock()
    runtime = Runtime(
        lambda: next(screens),
        clicks.append,
        monotonic=clock.now,
        emit=logs.append,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            friendship_templates=load_friendship_points_templates(TEMPLATES),
            friend_request_templates=load_friend_request_templates(STORY_TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, normal)
    assert len(clicks) == 2
    assert any("动作=close-friendship-points-popup" in line for line in logs)
    assert any("动作=cancel-friend-request" in line for line in logs)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_global_guard_requires_two_frames_then_returns_recovered_screen():
    popup = load_screen("network_reconnect_navigation.png")
    normal = np.asarray(
        Image.open(ROOT / "tests" / "fixtures" / "epic7_story" / "stage.png").convert("RGB")
    )[:1132, :1982]
    screens = iter([popup, popup, normal])
    clicks = []
    clock = FakeClock()
    runtime = Runtime(
        lambda: next(screens),
        clicks.append,
        monotonic=clock.now,
        emit=lambda _: None,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    started = runtime.now()
    received = runtime.capture()

    assert np.array_equal(received, normal)
    assert len(clicks) == 1
    assert runtime.now() == started


def test_global_guard_dismisses_intimacy_popup_before_returning_result_frame():
    popup = load_screen("intimacy_level_up_live_20260815.png")
    normal = np.asarray(
        Image.open(ROOT / "tests" / "fixtures" / "epic7_fodder" / "results.png").convert("RGB")
    )[:1132, :1982]
    screens = iter([popup, popup, normal])
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    clock = FakeClock()
    runtime = Runtime(
        lambda: next(screens),
        clicks.append,
        monotonic=clock.now,
        emit=logs.append,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            intimacy_templates=load_intimacy_level_up_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, normal)
    assert len(clicks) == 1
    assert 1040 <= clicks[0][0] <= 1240
    assert 850 <= clicks[0][1] <= 970
    assert any("动作=dismiss-intimacy-level-up" in line for line in logs)


def test_persistent_intimacy_popup_clicks_four_times_then_safely_stops(tmp_path):
    popup = load_screen("intimacy_level_up_live_20260815.png")
    clock = FakeClock()
    clicks: list[tuple[int, int]] = []
    runtime = Runtime(
        lambda: popup,
        clicks.append,
        monotonic=clock.now,
        diagnostic_dir=tmp_path,
        emit=lambda _: None,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            intimacy_templates=load_intimacy_level_up_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    with pytest.raises(RuntimeError, match="亲密度提升弹窗点击4次后仍未消失"):
        runtime.capture()

    assert len(clicks) == 4
    assert len(list(tmp_path.glob("*_intimacy_level_up_failed.png"))) == 1


def test_global_guard_clicks_four_times_then_safely_stops_if_popup_persists(tmp_path):
    popup = load_screen()
    clock = FakeClock()
    clicks = []
    runtime = Runtime(
        lambda: popup,
        clicks.append,
        monotonic=clock.now,
        diagnostic_dir=tmp_path,
        emit=lambda _: None,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    with pytest.raises(RuntimeError, match="断网重连弹窗点击4次后仍未消失"):
        runtime.capture()

    assert len(clicks) == 4
    assert len(list(tmp_path.glob("*_network_retry_failed.png"))) == 1


def test_global_guard_allowance_resets_after_popup_disappears():
    popup = load_screen()
    normal = np.asarray(
        Image.open(ROOT / "tests" / "fixtures" / "epic7_story" / "stage.png").convert("RGB")
    )[:1132, :1982]
    screens = iter([popup, popup, normal, popup, popup, normal])
    clicks = []
    clock = FakeClock()
    runtime = Runtime(
        lambda: next(screens),
        clicks.append,
        monotonic=clock.now,
        emit=lambda _: None,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    assert np.array_equal(runtime.capture(), normal)
    assert np.array_equal(runtime.capture(), normal)
    assert len(clicks) == 2


def test_global_guard_checks_manual_stop_while_waiting_on_popup():
    popup = load_screen()
    stop_states = iter([False, True])
    runtime = Runtime(
        lambda: popup,
        lambda _: None,
        stop_requested=lambda: next(stop_states),
        emit=lambda _: None,
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            sleep=lambda _: None,
        )
    )

    with pytest.raises(ManualStop):
        runtime.capture()
