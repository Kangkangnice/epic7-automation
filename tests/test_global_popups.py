from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    find_friend_request_cancel,
    find_friendship_points_popup_close,
    find_gift_support_close,
    find_intimacy_level_up_dismiss,
    find_knights_signin_close,
    find_knights_weekly_reward_close,
    find_network_retry,
    find_pet_gift_badge,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_gift_support_templates,
    load_intimacy_level_up_templates,
    load_knights_signin_templates,
    load_knights_weekly_reward_templates,
    load_network_reconnect_templates,
    load_pet_gift_templates,
)
from auto_game_unified.core.runtime import ManualStop, Runtime


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_global"
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
WORLD_BOSS_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_world_boss"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"
STORY_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"
NAVIGATION_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "navigation"


def load_screen(name: str = "network_reconnect.png") -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "network_reconnect.png",
        "network_reconnect_navigation.png",
        "network_disconnected.png",
    ],
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


def test_pc_friendship_points_popup_is_recognized_from_both_anchors():
    popup = load_screen("friendship_points_pc_20260830.png")
    templates = load_friendship_points_templates(TEMPLATES)

    match = find_friendship_points_popup_close(
        popup, templates.title, templates.close
    )

    assert match is not None
    assert 900 <= match.center[0] <= 1020
    assert 900 <= match.center[1] <= 1000


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


def _world_boss_screen(name: str) -> np.ndarray:
    return np.asarray(Image.open(WORLD_BOSS_FIXTURES / name).convert("RGB"))


def test_knights_signin_popup_is_recognized_from_both_anchors():
    popup = _world_boss_screen("knights_signin_popup.png")
    templates = load_knights_signin_templates(NAVIGATION_TEMPLATES)

    match = find_knights_signin_close(
        popup, templates.title, templates.close
    )

    assert match is not None
    # 「点击关闭」实测中心 (961, 847)。
    assert 900 <= match.center[0] <= 1020
    assert 820 <= match.center[1] <= 875


def test_knights_signin_popup_requires_title_and_close_anchor():
    popup = _world_boss_screen("knights_signin_popup.png")
    templates = load_knights_signin_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[260:350, 700:1300] = 0
    without_close = popup.copy()
    without_close[810:880, 860:1140] = 0

    assert find_knights_signin_close(
        without_title, templates.title, templates.close
    ) is None
    assert find_knights_signin_close(
        without_close, templates.title, templates.close
    ) is None


def test_knights_signin_popup_rejects_the_page_underneath_it():
    """点掉弹窗后的骑士团主页不能还被当成弹窗（否则会无限点下去）。"""
    templates = load_knights_signin_templates(NAVIGATION_TEMPLATES)

    assert find_knights_signin_close(
        _world_boss_screen("knights_home.png"), templates.title, templates.close
    ) is None
    assert find_knights_signin_close(
        _world_boss_screen("knights_home_after_popup.png"),
        templates.title,
        templates.close,
    ) is None
    assert find_knights_signin_close(
        _world_boss_screen("worldboss_home.png"), templates.title, templates.close
    ) is None


def test_knights_signin_popup_rejects_unrelated_global_popups():
    """别的全局弹窗不能被误判成骑士团签到，否则会在错的位置点「点击关闭」。"""
    templates = load_knights_signin_templates(NAVIGATION_TEMPLATES)
    others = [
        STORY_FIXTURES / "friendship_points_popup.png",
        STORY_FIXTURES / "friend_request.png",
        STORY_FIXTURES / "stamina_popup_live_20260809.png",
        FIXTURES / "network_disconnected.png",
        FIXTURES / "intimacy_level_up_live_20260815.png",
    ]

    for path in others:
        if not path.is_file():
            continue
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_knights_signin_close(
            screen, templates.title, templates.close
        ) is None, path.name


def test_global_guard_dismisses_knights_signin_popup():
    """守卫必须能消费掉签到弹窗，然后露出骑士团主页。"""
    popup = _world_boss_screen("knights_signin_popup.png")
    knights_home = _world_boss_screen("knights_home_after_popup.png")
    screens = iter([popup, popup, knights_home])
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
            knights_signin_templates=load_knights_signin_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, knights_home)
    assert len(clicks) == 1
    assert clicks[0] == (961, 847)
    assert any("动作=close-knights-signin" in line for line in logs)


def test_gift_support_popup_is_recognized_from_both_anchors():
    popup = _world_boss_screen("gift_support_popup.png")
    templates = load_gift_support_templates(NAVIGATION_TEMPLATES)

    match = find_gift_support_close(popup, templates.title, templates.close)

    assert match is not None
    # 「点击关闭」实测中心约 (959, 855)。
    assert 900 <= match.center[0] <= 1020
    assert 830 <= match.center[1] <= 880


def test_gift_support_popup_requires_title_and_close_anchor():
    popup = _world_boss_screen("gift_support_popup.png")
    templates = load_gift_support_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[260:350, 700:1300] = 0
    without_close = popup.copy()
    without_close[810:890, 860:1160] = 0

    assert find_gift_support_close(
        without_title, templates.title, templates.close
    ) is None
    assert find_gift_support_close(
        without_close, templates.title, templates.close
    ) is None


def test_gift_support_popup_rejects_the_page_underneath_it():
    """点掉弹窗后的骑士团主页不能还被当成弹窗（否则会无限点下去）。"""
    templates = load_gift_support_templates(NAVIGATION_TEMPLATES)

    for name in ("knights_home.png", "knights_home_after_popup.png", "worldboss_home.png"):
        assert find_gift_support_close(
            _world_boss_screen(name), templates.title, templates.close
        ) is None, name


def test_gift_support_popup_rejects_the_signin_popup():
    """两个弹窗标题共用同一块 ROI，必须靠标题文字互相区分开。"""
    templates = load_gift_support_templates(NAVIGATION_TEMPLATES)

    assert find_gift_support_close(
        _world_boss_screen("knights_signin_popup.png"),
        templates.title,
        templates.close,
    ) is None


def test_gift_support_popup_rejects_unrelated_global_popups():
    """别的全局弹窗不能被误判成领取支援弹窗，否则会在错的位置点「点击关闭」。"""
    templates = load_gift_support_templates(NAVIGATION_TEMPLATES)
    others = [
        STORY_FIXTURES / "friendship_points_popup.png",
        STORY_FIXTURES / "friend_request.png",
        STORY_FIXTURES / "stamina_popup_live_20260809.png",
        FIXTURES / "network_disconnected.png",
        FIXTURES / "intimacy_level_up_live_20260815.png",
    ]

    for path in others:
        if not path.is_file():
            continue
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_gift_support_close(
            screen, templates.title, templates.close
        ) is None, path.name


def test_global_guard_dismisses_gift_support_popup():
    """守卫必须能消费掉领取支援弹窗，然后露出骑士团主页。"""
    popup = _world_boss_screen("gift_support_popup.png")
    knights_home = _world_boss_screen("knights_home_after_popup.png")
    screens = iter([popup, popup, knights_home])
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
            gift_support_templates=load_gift_support_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, knights_home)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 830 <= clicks[0][1] <= 880
    assert any("动作=close-gift-support" in line for line in logs)


def test_knights_weekly_reward_popup_is_recognized_from_both_anchors():
    popup = _world_boss_screen("knights_weekly_reward_popup.png")
    templates = load_knights_weekly_reward_templates(NAVIGATION_TEMPLATES)

    match = find_knights_weekly_reward_close(popup, templates.title, templates.close)

    assert match is not None
    # 「点击关闭」实测中心 (959, 843)。
    assert 900 <= match.center[0] <= 1020
    assert 820 <= match.center[1] <= 875


def test_knights_weekly_reward_popup_requires_title_and_close_anchor():
    popup = _world_boss_screen("knights_weekly_reward_popup.png")
    templates = load_knights_weekly_reward_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[260:350, 700:1300] = 0
    without_close = popup.copy()
    without_close[810:890, 860:1160] = 0

    assert find_knights_weekly_reward_close(
        without_title, templates.title, templates.close
    ) is None
    assert find_knights_weekly_reward_close(
        without_close, templates.title, templates.close
    ) is None


def test_knights_weekly_reward_popup_rejects_the_page_underneath_it():
    """点掉弹窗后的骑士团主页不能还被当成弹窗（否则会无限点下去）。"""
    templates = load_knights_weekly_reward_templates(NAVIGATION_TEMPLATES)

    for name in ("knights_home.png", "knights_home_after_popup.png", "worldboss_home.png"):
        assert find_knights_weekly_reward_close(
            _world_boss_screen(name), templates.title, templates.close
        ) is None, name


def test_knights_weekly_reward_popup_rejects_other_knights_popups():
    """两个弹窗标题共用同一块 ROI，必须靠标题文字互相区分开。"""
    templates = load_knights_weekly_reward_templates(NAVIGATION_TEMPLATES)

    assert find_knights_weekly_reward_close(
        _world_boss_screen("knights_signin_popup.png"),
        templates.title,
        templates.close,
    ) is None
    assert find_knights_weekly_reward_close(
        _world_boss_screen("gift_support_popup.png"),
        templates.title,
        templates.close,
    ) is None


def test_knights_weekly_reward_popup_rejects_unrelated_global_popups():
    """别的全局弹窗不能被误判成周结算奖励弹窗，否则会在错的位置点「点击关闭」。"""
    templates = load_knights_weekly_reward_templates(NAVIGATION_TEMPLATES)
    others = [
        STORY_FIXTURES / "friendship_points_popup.png",
        STORY_FIXTURES / "friend_request.png",
        STORY_FIXTURES / "stamina_popup_live_20260809.png",
        FIXTURES / "network_disconnected.png",
        FIXTURES / "intimacy_level_up_live_20260815.png",
    ]

    for path in others:
        if not path.is_file():
            continue
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_knights_weekly_reward_close(
            screen, templates.title, templates.close
        ) is None, path.name


def test_global_guard_dismisses_knights_weekly_reward_popup():
    """守卫必须能消费掉周结算奖励弹窗，然后露出骑士团主页。"""
    popup = _world_boss_screen("knights_weekly_reward_popup.png")
    knights_home = _world_boss_screen("knights_home_after_popup.png")
    screens = iter([popup, popup, knights_home])
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
            knights_weekly_reward_templates=load_knights_weekly_reward_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, knights_home)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 820 <= clicks[0][1] <= 875
    assert any("动作=close-knights-weekly-reward" in line for line in logs)


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


# ---- 宠物小屋礼物角标（快捷菜单页，宠物送礼时挂出） --------------------------
#
# ⚠️ 它是本文件里**唯一一条单锚点**判据：那个角标没有「标题 + 关闭点」，
# 整个角标就是要点的目标（理由见 global_popups.py 的 _PET_GIFT_BADGE_REGION 注释）。
# 排他性由「区域限定 + 图形独特」保证，实测余量见那里的注释。

PET_BADGE_BOX = (1630, 338, 96, 94)  # x, y, w, h —— 与模板裁剪一致


def test_pet_gift_badge_is_recognized_on_the_quick_menu():
    screen = load_screen("pet_gift_live_20260928.png")
    templates = load_pet_gift_templates(TEMPLATES)

    match = find_pet_gift_badge(screen, templates.badge)

    assert match is not None
    # 实测角标中心约 (1678, 385)。
    assert 1600 <= match.center[0] <= 1760
    assert 330 <= match.center[1] <= 435
    assert match.score >= 0.95


def test_pet_gift_badge_requires_the_badge_itself():
    """把角标抹掉后就不能再命中（否则会把没有礼物的菜单页也点一下）。"""
    screen = load_screen("pet_gift_live_20260928.png")
    templates = load_pet_gift_templates(TEMPLATES)
    x, y, w, h = PET_BADGE_BOX
    erased = screen.copy()
    erased[y : y + h, x : x + w] = 0

    assert find_pet_gift_badge(screen, templates.badge) is not None
    assert find_pet_gift_badge(erased, templates.badge) is None


def test_pet_gift_badge_rejects_unrelated_frames():
    """别的页面不能被误判成宠物礼物角标，否则会在菜单页以外乱点。"""
    templates = load_pet_gift_templates(TEMPLATES)
    others = [
        STORY_FIXTURES / "friendship_points_popup.png",
        STORY_FIXTURES / "stamina_popup_live_20260809.png",
        FIXTURES / "network_disconnected.png",
        FIXTURES / "intimacy_level_up_live_20260815.png",
        WORLD_BOSS_FIXTURES / "knights_home.png",
    ]

    for path in others:
        if not path.is_file():
            continue
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_pet_gift_badge(screen, templates.badge) is None, path.name


def test_global_guard_dismisses_pet_gift_badge():
    """守卫必须能消费掉礼物角标，然后交回「角标已消失」的那一帧。"""
    with_badge = load_screen("pet_gift_live_20260928.png")
    without = with_badge.copy()
    x, y, w, h = PET_BADGE_BOX
    without[y : y + h, x : x + w] = 0
    screens = iter([with_badge, with_badge, without])
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
            pet_gift_templates=load_pet_gift_templates(TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, without)
    assert len(clicks) == 1
    assert 1600 <= clicks[0][0] <= 1760
    assert 330 <= clicks[0][1] <= 435
    assert any("动作=claim-pet-gift" in line for line in logs)


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
