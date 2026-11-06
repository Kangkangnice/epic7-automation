from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auto_game_unified.games.epic7 import global_popups as popups_module
from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    find_arena_rank_reward_close,
    find_battle_record_close,
    find_friend_request_cancel,
    find_friendship_points_popup_close,
    find_gift_support_close,
    find_intimacy_level_up_dismiss,
    find_knights_growth_rank_close,
    find_knights_signin_close,
    find_knights_weekly_reward_close,
    find_date_change_close,
    find_login_reward_close,
    find_network_retry,
    find_account_rank_up_close,
    find_gift_claim_close,
    find_pet_gift_badge,
    find_reward_notice_close,
    find_side_story_notice_close,
    find_tutorial_unlock_skip,
    find_web_network_error_close,
    find_worldboss_support_reward_close,
    load_arena_rank_reward_templates,
    load_battle_record_templates,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_gift_support_templates,
    load_intimacy_level_up_templates,
    load_knights_growth_rank_templates,
    load_knights_signin_templates,
    load_knights_weekly_reward_templates,
    load_date_change_templates,
    load_login_reward_templates,
    load_network_reconnect_templates,
    load_account_rank_up_templates,
    load_gift_claim_templates,
    load_pet_gift_templates,
    load_reward_notice_templates,
    load_side_story_notice_templates,
    load_tutorial_unlock_templates,
    load_web_network_error_templates,
    load_worldboss_support_reward_templates,
)
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.games.epic7.template_paths import TemplateDir


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_global"
STORY_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_story"
WORLD_BOSS_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_world_boss"
ARENA_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_arena"
HERO_FIXTURES = ROOT / "tests" / "fixtures" / "epic7_hero"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"
STORY_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "story"
NAVIGATION_TEMPLATES = ROOT / "games" / "epic7" / "templates" / "navigation"


def load_screen(name: str = "network_reconnect.png") -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


def _centre_of(screen: np.ndarray) -> tuple[int, int]:
    return (screen.shape[1] // 2, screen.shape[0] // 2)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "network_reconnect.png",
        "network_reconnect_navigation.png",
        "network_disconnected.png",
        # 2026-10-04 真机：那一帧是「文案乙 + 按钮甲」的交叉搭配，
        # 老的双锚点判定两组各缺一半 ⇒ 整层弹窗被漏掉，竞技场连点 4 次
        # 「战斗开始」都没反应 ⇒ 那条任务记 ✗。
        "network_disconnected_live_20261004.png",
    ],
)
def test_network_retry_points_at_the_screen_centre(fixture_name):
    """老契约是「文案 + 按钮都在」才出手、并且点的是按钮中心。今天那次事故证明
    这两种画法会**交叉**出现（历史上只见过甲配甲、乙配乙，第一次出现乙配甲就漏了），
    所以现在只看文案，Central click 即可。
    """
    screen = load_screen(fixture_name)
    templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, templates)

    assert match is not None
    assert match.center == _centre_of(screen)
    assert match.score >= 0.88


def test_network_retry_recognizes_the_pc_client_popup():
    """2026-11-01 PC 真机：同一句「网络连接异常，请重新连接。」在 PC 上只有 0.6272
    （阈 0.88）⇒ 断线弹窗一直认不出、压在画面上，路线最后以「未知页」收场。

    修法是 `templates/global/pc/network_message.png`（425×55，与共享模板同尺寸、
    按模板里白字的落点对齐裁）⇒ PC 上 1.0000。

    ⚠️ 2026-11-03 追加：认出来之后**点哪**是另一个坑。PC 上这层弹窗是全屏横带，
    文案在 y≈521、按钮在 y≈702~733，原写法「命中即点屏幕中心」正好点在两者之间
    的空白 ⇒ 竞技场 10:23/18:35、主线 15:37 连点 4~8 次纹丝不动。
    现在补 `templates/global/pc/network_retry_button.png` 只负责定位（中心 (960,731)），
    判定仍然只看文案；模拟器侧没有这张图 ⇒ 仍点屏幕中心，行为不变。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "network_reconnect_pc_live_20261101.png").convert("RGB")
    )
    pc_templates = load_network_reconnect_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.88
    # PC 上必须点在「点击重试 ∨」本体上，不能落在文案与按钮之间的空白。
    assert abs(match.center[0] - 960) <= 6, match.center
    assert abs(match.center[1] - 731) <= 6, match.center
    # 这张 PC 帧在**模拟器口径**下必须仍然认不出：`pc/` 覆盖图不是"两边通用图"，
    # 谁要是把它复制成共享图，这条会立刻红。
    assert find_network_retry(screen, emulator_templates) is None


def test_network_retry_click_point_falls_back_to_centre_without_button_template():
    """没有 `retry_button` 图（模拟器口径）⇒ 必须保持历史行为：点屏幕中心。

    护栏：谁要是把 PC 图挪成共享图、或删掉回落分支，这条立刻红。
    """
    from auto_game_unified.core.matcher import load_template

    screen = np.asarray(
        Image.open(FIXTURES / "network_reconnect_pc_live_20261101.png").convert("RGB")
    )
    message = load_template(str(TEMPLATES / "pc" / "network_message.png"))
    templates = popups_module.NetworkReconnectTemplates(
        message=message, message_alt=None, retry_button=None
    )

    match = find_network_retry(screen, templates)

    assert match is not None
    assert match.center == _centre_of(screen)


def test_gift_claim_notice_is_dismissed_from_its_close_label():
    """骑士团「领取支援物品」弹窗：盖住骑士团主页 ⇒ 世界首领战卡在入口。

    2026-11-02 10:06 PC 实跑。已登记的两类都对不上（``gift_support_title`` 0.4572、
    ``worldboss_support_reward_title`` 0.2150）—— 文案不同，是新的一层。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "gift_claim_pc_live_20261102.png").convert("RGB")
    )
    templates = load_gift_claim_templates(TemplateDir(TEMPLATES, "pc"))

    match = find_gift_claim_close(screen, templates)

    assert match is not None
    assert match.score >= 0.85
    assert 900 <= match.center[0] <= 1030, match.center
    assert 820 <= match.center[1] <= 890, match.center


def test_account_rank_up_is_dismissed_from_its_arrow():
    """「账号 Rank 提升」弹窗：盖住战斗画面 ⇒ 战斗判不出、回家按 ESC 也没用。

    2026-11-02 15:35 主线 PC 实跑，一条命犯了两桩：「战斗画面持续无法识别超时」
    +「返回首页失败：连按 2 次 ESC 页面都没有变化」。

    锚「账号Rank提升」半句 + 底部向下箭头：正文「已恢复176点行动力」与徽章
    「RANK UP 45」的**数字每次升级都变**，模板一律不含。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "account_rank_up_pc_live_20261102.png").convert("RGB")
    )
    templates = load_account_rank_up_templates(TemplateDir(TEMPLATES, "pc"))

    match = find_account_rank_up_close(screen, templates)

    assert match is not None
    assert match.score >= 0.85
    assert 900 <= match.center[0] <= 1020, match.center
    assert 1020 <= match.center[1] <= 1110, match.center


def test_account_rank_up_requires_both_anchors():
    screen = np.asarray(
        Image.open(FIXTURES / "account_rank_up_pc_live_20261102.png").convert("RGB")
    )
    templates = load_account_rank_up_templates(TemplateDir(TEMPLATES, "pc"))
    without_title = screen.copy()
    without_title[920:1040, 600:1400] = 0
    without_close = screen.copy()
    without_close[1000:1140, 760:1220] = 0

    assert find_account_rank_up_close(without_title, templates) is None
    assert find_account_rank_up_close(without_close, templates) is None


def test_gift_claim_requires_both_anchors():
    screen = np.asarray(
        Image.open(FIXTURES / "gift_claim_pc_live_20261102.png").convert("RGB")
    )
    templates = load_gift_claim_templates(TemplateDir(TEMPLATES, "pc"))
    without_title = screen.copy()
    without_title[250:370, 760:1220] = 0
    without_close = screen.copy()
    without_close[800:920, 830:1150] = 0

    assert find_gift_claim_close(without_title, templates) is None
    assert find_gift_claim_close(without_close, templates) is None


def test_reward_notice_is_dismissed_from_its_close_label():
    """「获得奖励」通知：点完通关提示后盖住关卡入口，不点掉就「等待通关」45 秒无进展。

    2026-11-01 22:27 主线 PC 实跑（诊断帧 20261101_222757...）。
    同帧上路线自己的 ``bonus_reward`` 只有 0.7724（阈 0.80）—— 差 0.028 就整条卡住。

    只锚标题 + 点击关闭：正文（"获得星星奖励已正常发放。"）与奖励图标随奖励类型变化。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "reward_notice_pc_live_20261101.png").convert("RGB")
    )
    templates = load_reward_notice_templates(TemplateDir(TEMPLATES, "pc"))

    match = find_reward_notice_close(screen, templates)

    assert match is not None
    assert match.score >= 0.85
    assert 900 <= match.center[0] <= 1030, match.center
    assert 800 <= match.center[1] <= 880, match.center


def test_reward_notice_requires_both_anchors():
    screen = np.asarray(
        Image.open(FIXTURES / "reward_notice_pc_live_20261101.png").convert("RGB")
    )
    templates = load_reward_notice_templates(TemplateDir(TEMPLATES, "pc"))
    without_title = screen.copy()
    without_title[240:360, 800:1300] = 0
    without_close = screen.copy()
    without_close[780:900, 830:1150] = 0

    assert find_reward_notice_close(without_title, templates) is None
    assert find_reward_notice_close(without_close, templates) is None


def test_the_two_notice_popups_do_not_recognize_each_other():
    """支线故事通知与获得奖励都是「标题 + 点击关闭」，但标题不同 ⇒ 互不串味。"""
    story_notice = np.asarray(
        Image.open(FIXTURES / "side_story_notice_pc_live_20261101.png").convert("RGB")
    )
    reward_notice = np.asarray(
        Image.open(FIXTURES / "reward_notice_pc_live_20261101.png").convert("RGB")
    )
    story_templates = load_side_story_notice_templates(TemplateDir(TEMPLATES, "pc"))
    reward_templates = load_reward_notice_templates(TemplateDir(TEMPLATES, "pc"))

    assert find_side_story_notice_close(story_notice, story_templates) is not None
    assert find_reward_notice_close(story_notice, reward_templates) is None
    assert find_reward_notice_close(reward_notice, reward_templates) is not None
    assert find_side_story_notice_close(reward_notice, story_templates) is None


def test_side_story_notice_is_dismissed_from_its_close_label():
    """新支线解锁通知：盖在结算页上，不点掉就「等待结算」45 秒无进展。

    2026-11-01 22:05 主线 PC 实跑就是这么挂的（诊断帧
    `20261101_220554_360858_timeout_wait_results.png`）。

    判据只认**标题 + 点击关闭**两颗：正文与插画随解锁的支线变化
    （"支线故事「被选中的女巫」已解锁"），不能拿它当锚点。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "side_story_notice_pc_live_20261101.png").convert("RGB")
    )
    templates = load_side_story_notice_templates(TemplateDir(TEMPLATES, "pc"))

    match = find_side_story_notice_close(screen, templates)

    assert match is not None
    assert match.score >= 0.85
    # 点在「点击关闭」上（不是标题、也不是插画）
    assert 900 <= match.center[0] <= 1030, match.center
    assert 850 <= match.center[1] <= 920, match.center


def test_side_story_notice_requires_both_anchors():
    """缺标题或缺关闭标签都不算 —— 「点击关闭」这四个字在好几个弹窗上都有。"""
    screen = np.asarray(
        Image.open(FIXTURES / "side_story_notice_pc_live_20261101.png").convert("RGB")
    )
    templates = load_side_story_notice_templates(TemplateDir(TEMPLATES, "pc"))
    without_title = screen.copy()
    without_title[240:360, 760:1220] = 0
    without_close = screen.copy()
    without_close[840:960, 830:1150] = 0

    assert find_side_story_notice_close(without_title, templates) is None
    assert find_side_story_notice_close(without_close, templates) is None


def test_side_story_notice_rejects_normal_game_frames():
    """别的页面上一律不得命中（关卡入口、结算页+好友弹窗两张 PC 真机帧当反例）。"""
    templates = load_side_story_notice_templates(TemplateDir(TEMPLATES, "pc"))
    for name in ("stage_pc_live_20261101.png", "friend_request_pc_live_20261101.png"):
        screen = np.asarray(Image.open(STORY_FIXTURES / name).convert("RGB"))
        assert find_side_story_notice_close(screen, templates) is None, name


def test_network_retry_only_needs_the_message_anchor():
    """按钮不再参与判定：**抹掉按钮照样要认出来**（这正是今天漏掉的那一步）。"""
    screen = load_screen()
    templates = load_network_reconnect_templates(TEMPLATES)
    without_message = screen.copy()
    without_message[490:590, 730:1250] = 0
    without_retry = screen.copy()
    without_retry[660:815, 820:1110] = 0

    assert find_network_retry(without_message, templates) is None
    assert find_network_retry(without_retry, templates) is not None


def test_network_retry_catches_the_pairing_that_used_to_slip_through():
    """今天那张帧四个锚点的实测分数（扫描脚本 runtime_logs/_probe_network_popup.py）：

    message 0.5001（不过阈）/ retry 0.9854 / message_alt 0.9992 / retry_alt 0.4196
    ⇒ 旧的两两配对两组都不成立。这条把**那张真机帧**钉住，防止再退回去。
    """
    screen = load_screen("network_disconnected_live_20261004.png")
    templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, templates)

    assert match is not None
    assert round(match.score, 3) == 0.999
    assert match.center == _centre_of(screen)


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


# ──⚠️⚠️ 竖屏画面必须放行（2026-10-07 修，用户点 2 的真凶）─────────────────
#
# 这一层所有判据都是**横屏**控件（基准 1982x1132），定位时按画面尺寸缩放，
# 并有宽高比守卫（``evidence/sanctuary._scale_region``：横向与纵向缩放比例
# 相差超过 2% 就抛「画面宽高比与模板基准不一致」）。
#
# 社区路线点进「游戏社区」后画面是 1080x1920 ⇒ 横向缩放 0.545、纵向 1.696
# ⇒ 守卫**必然抛错**，异常从 ``Runtime.capture`` 冒到主循环（它不在主循环的
# ``try`` 里）⇒ **失败收尾把刚打开的社区关掉**。实跑原文：
#   14:50:10 执行点击 enter_community
#   14:50:13 收尾=人还在社区竖屏页面里
#   运行失败 模式=community 原因=画面宽高比与模板基准不一致


def _portrait_screen(height: int = 1920, width: int = 1080) -> np.ndarray:
    return np.zeros((height, width, 3), np.uint8)


def test_portrait_frame_passes_straight_through_the_landscape_popup_guard():
    """竖屏帧**原样返回、不点任何东西、不报错**。"""
    portrait = _portrait_screen()
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    runtime = Runtime(lambda: portrait, clicks.append, emit=logs.append)
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            friendship_templates=load_friendship_points_templates(TEMPLATES),
            friend_request_templates=load_friend_request_templates(STORY_TEMPLATES),
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, portrait), "竖屏帧必须原样放行"
    assert clicks == [], "竖屏段不该点横屏弹窗的关闭按钮"
    assert not any("宽高比" in line for line in logs)


def test_landscape_frame_still_goes_through_the_guard():
    """⚠️ 反向守卫：横屏帧**仍然**要走判据（别把这条写成永远放行）。

    用「骑士团签到弹窗」那张真横屏夹具：守卫应当认出来并点掉。
    """
    popup = _world_boss_screen("knights_signin_popup.png")[:1132, :1982]
    assert popup.shape[:2] == (1132, 1982)
    normal = np.asarray(
        Image.open(ROOT / "tests" / "fixtures" / "epic7_story" / "stage.png").convert("RGB")
    )[:1132, :1982]
    screens = iter([popup, popup, normal])
    clicks: list[tuple[int, int]] = []
    logs: list[str] = []
    clock = FakeClock()
    runtime = Runtime(
        lambda: next(screens), clicks.append, monotonic=clock.now, emit=logs.append
    )
    runtime.set_capture_guard(
        Epic7GlobalPopupGuard(
            load_network_reconnect_templates(TEMPLATES),
            knights_signin_templates=load_knights_signin_templates(NAVIGATION_TEMPLATES),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    runtime.capture()

    assert clicks, "横屏帧仍该点掉骑士团签到弹窗（别把竖屏放行写成永远放行）"
    assert any("close-knights-signin" in line for line in logs), logs


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


def test_worldboss_support_reward_popup_is_recognized_from_both_anchors():
    """「世界首领辅助队伍奖励」弹窗：标题 + 「点击关闭」双锚点都要命中。

    现场帧是 2026-10-19 08:11 那次「世界首领战 ✗」的诊断图 —— 它盖在**世界首领战
    主页**上，把右下角「选择队伍」压得认不出来，导航转场一路等到超时。
    """
    popup = _world_boss_screen("worldboss_support_reward_live_20261019.png")
    templates = load_worldboss_support_reward_templates(NAVIGATION_TEMPLATES)

    match = find_worldboss_support_reward_close(
        popup, templates.title, templates.close
    )

    assert match is not None
    # 底部「点击关闭」实测中心 (960, 813)。
    assert 900 <= match.center[0] <= 1020
    assert 780 <= match.center[1] <= 850


def test_worldboss_support_reward_popup_requires_title_and_close_anchor():
    """两个锚点缺一不可：标题挡住「点击关闭」的乱命中，关闭点给出点击位置。"""
    popup = _world_boss_screen("worldboss_support_reward_live_20261019.png")
    templates = load_worldboss_support_reward_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[262:342, 700:1220] = 0
    without_close = popup.copy()
    without_close[770:860, 860:1160] = 0

    assert (
        find_worldboss_support_reward_close(
            without_title, templates.title, templates.close
        )
        is None
    )
    assert (
        find_worldboss_support_reward_close(
            without_close, templates.title, templates.close
        )
        is None
    )


def test_worldboss_support_reward_popup_rejects_the_page_underneath_it():
    """点掉弹窗后的世界首领战主页不能还被当成弹窗（否则会一直点下去）。"""
    templates = load_worldboss_support_reward_templates(NAVIGATION_TEMPLATES)

    for name in (
        "worldboss_home.png",
        "worldboss_home_chest_claimable.png",
        "worldboss_home_exhausted.png",
        "knights_home_after_popup.png",
    ):
        assert (
            find_worldboss_support_reward_close(
                _world_boss_screen(name), templates.title, templates.close
            )
            is None
        ), name


def test_worldboss_support_reward_title_is_exclusive_against_sibling_popups():
    """标题必须在**同类**弹窗之间也能分开 —— 它们共用同一块标题 ROI。

    全库 280 张横屏帧实测：标题跨页最高 **0.3320**（骑士团签到弹窗），
    门槛 0.80 的余量 0.47；而「点击关闭」那行灰字在 `reward_popup` 上就有
    **0.8993** ⇒ 那一个点**绝不能单独当判据**（这里一并钉住）。
    """
    templates = load_worldboss_support_reward_templates(NAVIGATION_TEMPLATES)

    for name in (
        "knights_signin_popup.png",
        "gift_support_popup.png",
        "knights_weekly_reward_popup.png",
    ):
        assert (
            find_worldboss_support_reward_close(
                _world_boss_screen(name), templates.title, templates.close
            )
            is None
        ), name

    reward_popup = np.asarray(
        Image.open(
            ROOT / "tests" / "fixtures" / "epic7_hero" / "reward_popup.png"
        ).convert("RGB")
    )[:1132, :1982]
    assert (
        find_worldboss_support_reward_close(
            reward_popup, templates.title, templates.close
        )
        is None
    ), "「点击关闭」在别的领奖弹窗上分数很高，标题必须把它挡住"


def test_global_guard_dismisses_worldboss_support_reward_popup():
    """守卫必须能把这一层消费掉，露出世界首领战主页（10-19 那次失败的现场）。"""
    popup = _world_boss_screen("worldboss_support_reward_live_20261019.png")
    home = _world_boss_screen("worldboss_home_chest_claimable.png")
    screens = iter([popup, popup, home])
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
            worldboss_support_reward_templates=(
                load_worldboss_support_reward_templates(NAVIGATION_TEMPLATES)
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, home)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 780 <= clicks[0][1] <= 850
    assert any("动作=close-worldboss-support-reward" in line for line in logs)


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

    with pytest.raises(
        RuntimeError,
        match=f"亲密度提升弹窗点击{popups_module._MAX_POPUP_CLICKS}次后仍未消失",
    ):
        runtime.capture()

    assert len(clicks) == popups_module._MAX_POPUP_CLICKS
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

    with pytest.raises(
        RuntimeError,
        match=f"断网重连弹窗点击{popups_module._MAX_POPUP_CLICKS}次后仍未消失",
    ):
        runtime.capture()

    assert len(clicks) == popups_module._MAX_POPUP_CLICKS
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


# ---- 游戏内网页「网络错误」长条（横屏 WebView，2026-10-07 新接的第九个）---------
#
# ⚠️ 这条与上面那条「断线重连弹窗」是**两种不同的网络失败**，别并成一条：
#   断线弹窗是**模态**的 —— 点画面任何位置都会触发重试，所以命中就点屏幕中央；
#   这条长条**没有按钮** —— 唯一能消掉它的是网页容器右上角那颗圆钮 X。
# 下面专门用一组测试把「两者各认各的」钉死（混为一条的代价：网页报错时会去点
# 屏幕中央，那儿什么都没有，白白烧光点击预算）。
#
# 实测余量（2026-10-07，生产口径 `load_template` + `find_template`）：
#   长条正例 1.0000 ×2（相隔 40 分钟两张真机帧）；「还在转圈」0.2455/0.2450；
#   正常网页列表 0.2161；**全库 227 张横屏夹具最高 0.4908**（阈值 0.80）。
#   圆钮正例 1.0000，但在**正常网页帧**上也有 0.9970/0.9739 ⇒ 它单独**不能当判据**，
#   只能当「点哪儿」—— 这就是这里必须双锚点的原因。

# 实测裁剪框（与 `global_popups.py` 的 `_WEB_NETWORK_MESSAGE_REGION` /
# `_WEB_ERROR_CLOSE_REGION` 对应）。⚠️ 这里**独立写死**，绝不从被测函数里取：
# 否则函数挪到哪儿、断言就跟着挪到哪儿，反向注入违规会纹丝不动（已踩过）。
WEB_BAR_BOX = (624, 550, 672, 84)
WEB_CLOSE_BOX = (1852, 66, 54, 54)


def _erase(screen: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    erased = screen.copy()
    x, y, w, h = box
    erased[y : y + h, x : x + w] = 0
    return erased


def test_web_network_error_is_dismissed_from_the_top_right_close():
    screen = load_screen("web_network_error_live_20261007.png")
    templates = load_web_network_error_templates(NAVIGATION_TEMPLATES)

    match = find_web_network_error_close(screen, templates)

    assert match is not None
    # 圆钮实测中心 (1879, 93)。
    assert 1860 <= match.center[0] <= 1900
    assert 75 <= match.center[1] <= 110
    assert match.score >= 0.99


def test_web_network_error_requires_the_message_bar():
    """判据是那条**黑底白字长条**：抹掉它就不许再命中（哪怕 X 还挂在那儿）。"""
    screen = load_screen("web_network_error_live_20261007.png")
    templates = load_web_network_error_templates(NAVIGATION_TEMPLATES)

    assert find_web_network_error_close(screen, templates) is not None
    assert find_web_network_error_close(_erase(screen, WEB_BAR_BOX), templates) is None


def test_web_network_error_requires_the_close_button():
    """⚠️ 反向：抹掉 X 也必须不命中 —— 专门盯住「长条在、X 却定位不到」那一支。

    那一支**必须返回 None**，不许退回一个猜的坐标：旁边就是屏幕右边缘，
    点偏了没有第二次机会（保守不动手，让上层照旧失败并留诊断帧）。
    """
    screen = load_screen("web_network_error_live_20261007.png")
    templates = load_web_network_error_templates(NAVIGATION_TEMPLATES)

    assert find_web_network_error_close(screen, templates) is not None
    assert find_web_network_error_close(_erase(screen, WEB_CLOSE_BOX), templates) is None


def test_web_network_error_rejects_unrelated_landscape_frames():
    """别的画面不能被误判成网页报错 —— 否则会在屏幕右上角乱点（那儿是返回/关闭）。"""
    templates = load_web_network_error_templates(NAVIGATION_TEMPLATES)
    others = [
        FIXTURES / "network_reconnect.png",
        FIXTURES / "network_reconnect_navigation.png",
        FIXTURES / "network_disconnected.png",
        FIXTURES / "network_disconnected_live_20261004.png",
        FIXTURES / "intimacy_level_up_live_20260815.png",
        FIXTURES / "pet_gift_live_20260928.png",
        WORLD_BOSS_FIXTURES / "knights_home.png",
        STORY_FIXTURES / "stage.png",
    ]

    for path in others:
        if not path.is_file():
            continue
        screen = np.asarray(Image.open(path).convert("RGB"))[:1132, :1982]
        assert find_web_network_error_close(screen, templates) is None, path.name


def test_the_two_network_failures_do_not_recognize_each_other():
    """两种网络失败**各认各的**：网页报错帧上认不出断线弹窗，断线弹窗帧上也认不出长条。

    这是「别把它们并成一条」的机器守门 —— 并了的后果是网页报错时去点屏幕中央
    （那里什么都没有），点满 4 次才熔断，社区那一轮全废。
    """
    reconnect = load_network_reconnect_templates(TEMPLATES)
    web = load_web_network_error_templates(NAVIGATION_TEMPLATES)

    web_error_frame = load_screen("web_network_error_live_20261007.png")
    assert find_network_retry(web_error_frame, reconnect) is None

    for name in ("network_reconnect.png", "network_disconnected.png"):
        assert find_web_network_error_close(load_screen(name), web) is None, name


def test_global_guard_dismisses_web_network_error():
    """守卫必须能消费掉这条长条，然后交回「长条已消失」的那一帧。"""
    with_error = load_screen("web_network_error_live_20261007.png")
    recovered = _erase(with_error, WEB_BAR_BOX)
    screens = iter([with_error, with_error, recovered])
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
            web_network_error_templates=load_web_network_error_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, recovered)
    assert len(clicks) == 1
    assert 1860 <= clicks[0][0] <= 1900
    assert 75 <= clicks[0][1] <= 110
    assert any("动作=dismiss-web-network-error" in line for line in logs)


# ── 第 11 个全局弹窗：竞技场「段位升级奖励」（2026-10-20）────────────────────
#
# 它是竞技场「段位提升」的**下一层**：点掉段位提升之后马上弹出来，只在首次升至
# 某段位时出现一次。2026-10-20 08:02 那次它把底页压暗、竞技场一条判据都认不出它
# ⇒ 转场一路等到 45 秒上限、整条竞技场记 ✗（当天唯一失败的路线）。


def _global_screen(name: str) -> np.ndarray:
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


def _arena_screen(name: str) -> np.ndarray:
    return np.asarray(Image.open(ARENA_FIXTURES / name).convert("RGB"))


def _hero_screen(name: str) -> np.ndarray:
    return np.asarray(Image.open(HERO_FIXTURES / name).convert("RGB"))


def test_arena_rank_reward_popup_is_recognized_from_both_anchors():
    """标题「升级奖励」+ 底部「点击关闭」，两个锚点都命中才算。

    夹具就是那次失败帧：`20261020_080245_283281_no_transition_confirming_to_list.png`。
    """
    popup = _global_screen("arena_rank_reward_live_20261020.png")
    templates = load_arena_rank_reward_templates(NAVIGATION_TEMPLATES)

    match = find_arena_rank_reward_close(popup, templates.title, templates.close)

    assert match is not None
    # 「点击关闭」实测中心 (961, 832)。
    assert 900 <= match.center[0] <= 1020
    assert 800 <= match.center[1] <= 865


def test_arena_rank_reward_popup_requires_title_and_close_anchor():
    """两个锚点缺一不可：标题挡乱命中，关闭点给点击位置。"""
    popup = _global_screen("arena_rank_reward_live_20261020.png")
    templates = load_arena_rank_reward_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[285:365, 820:1180] = 0
    without_close = popup.copy()
    without_close[795:905, 860:1140] = 0

    assert (
        find_arena_rank_reward_close(
            without_title, templates.title, templates.close
        )
        is None
    )
    assert (
        find_arena_rank_reward_close(
            without_close, templates.title, templates.close
        )
        is None
    )


def test_arena_rank_reward_close_alone_is_not_exclusive():
    """⚠️ 这条钉住「为什么必须双锚点」，别把标题那半拆掉。

    底部「点击关闭」是游戏里**通用**的一行灰字：在「刻印结果」弹窗上它单独就有
    0.95+，比任何合理阈值都高。所以它是**点击点**，不是判据 —— 判据是标题。
    这条测试同时证明两件事：那张图上「关闭点」确实很高分，而**整个判据仍然返回 None**。
    """
    from auto_game_unified.core.matcher import find_template

    other = _hero_screen("imprint_result_popup.png")
    templates = load_arena_rank_reward_templates(NAVIGATION_TEMPLATES)

    close_only = find_template(
        other,
        templates.close,
        popups_module._ARENA_RANK_REWARD_THRESHOLD,
        region=popups_module._ARENA_RANK_REWARD_CLOSE_REGION,
        reference_size=(1982, 1132),
    )
    assert close_only is not None, "这行灰字在别的弹窗上应当仍然像"
    assert close_only.score > 0.90

    assert find_arena_rank_reward_close(other, templates.title, templates.close) is None


def test_arena_rank_reward_popup_rejects_the_pages_around_it():
    """弹窗出现前那一页（段位提升）与消失后那一页（对手列表/详情）都不能命中。

    否则守卫会在这两页上反复点、把流程顶住 —— 比不认更糟。

    ⚠️ 只用 1982x1132 的帧：``list.png`` / ``rank_confirm.png`` 是 3200x2000
    （另一条采集通道），喂进来会先撞 ``matcher`` 的宽高比守卫，
    测不到判据本身，等于白测。
    """
    templates = load_arena_rank_reward_templates(NAVIGATION_TEMPLATES)

    for name in (
        "rank_promotion_master.png",
        "selected.png",
        "result_defeat_live_20260925.png",
    ):
        assert (
            find_arena_rank_reward_close(
                _arena_screen(name), templates.title, templates.close
            )
            is None
        ), name


def test_guard_dismisses_the_arena_rank_reward_popup():
    popup = _global_screen("arena_rank_reward_live_20261020.png")
    # 弹窗消掉之后落回的「对手详情/列表」那一页（1982x1132，见上一条的尺寸说明）。
    recovered = _arena_screen("selected.png")
    screens = iter([popup, popup, recovered])
    clicks = []
    logs = []
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
            arena_rank_reward_templates=load_arena_rank_reward_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, recovered)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 800 <= clicks[0][1] <= 865
    assert any("动作=close-arena-rank-reward" in line for line in logs)


# ── 第 12 个全局弹窗：竞技场「战斗记录」（2026-10-30）────────────────────────
#
# 与上面那层「段位升级奖励」**不是一件事**：那个是打完一局后的流程内弹窗，
# 这个是**进竞技场时就弹**的防守战报 / 段位变动通知（「根据防御队的战斗结果和
# 排名变动，段位变更如下。」）。
#
# 2026-10-30 18:27 现场：点「进入竞技场」后它盖住对手列表 ⇒ 竞技场一条判据都认不出它
# ⇒ 导航"只等"到 129 秒报「转场失败」；随后回家又栽在快捷菜单上（另一处），
# 整轮每日任务**只跑完竞技场一条就中止**，后面 5 条路线一条没跑。


def test_battle_record_popup_is_recognized_from_both_anchors():
    """标题「战斗记录」+ 底部「点击关闭」，两个锚点都命中才算。

    夹具就是那次失败帧：`20261030_182911_007868_navigation_arena_mode_to_arena_ready_failed.png`。
    """
    popup = _global_screen("battle_record_live_20261030.png")
    templates = load_battle_record_templates(NAVIGATION_TEMPLATES)

    match = find_battle_record_close(popup, templates.title, templates.close)

    assert match is not None
    # 「点击关闭」实测中心 (961, 879)。
    assert 900 <= match.center[0] <= 1020
    assert 845 <= match.center[1] <= 915


def test_battle_record_popup_requires_title_and_close_anchor():
    """两个锚点缺一不可：标题挡乱命中，关闭点给点击位置。"""
    popup = _global_screen("battle_record_live_20261030.png")
    templates = load_battle_record_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[226:306, 820:1180] = 0
    without_close = popup.copy()
    without_close[795:905, 860:1140] = 0

    assert (
        find_battle_record_close(without_title, templates.title, templates.close)
        is None
    )
    assert (
        find_battle_record_close(without_close, templates.title, templates.close)
        is None
    )


def test_battle_record_popup_rejects_the_pages_around_it():
    """弹窗出现前后那几页都不能命中 —— 否则守卫会反复点、把流程顶住。

    最贴近现场的那张是 ``quick_menu_over_arena_live_20261030``：同一次事故里
    弹窗消掉之后、回家卡住的那一帧（快捷菜单展开在竞技场页上）。
    """
    templates = load_battle_record_templates(NAVIGATION_TEMPLATES)

    for frame in (
        np.asarray(
            Image.open(
                ROOT
                / "tests"
                / "fixtures"
                / "epic7_navigation"
                / "quick_menu_over_arena_live_20261030.png"
            ).convert("RGB")
        ),
        _arena_screen("selected.png"),
        _arena_screen("result_defeat_live_20260925.png"),
    ):
        assert find_battle_record_close(frame, templates.title, templates.close) is None


def test_guard_dismisses_the_battle_record_popup():
    popup = _global_screen("battle_record_live_20261030.png")
    # 弹窗消掉之后落回的「对手详情」那一页。
    recovered = _arena_screen("selected.png")
    screens = iter([popup, popup, recovered])
    clicks = []
    logs = []
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
            battle_record_templates=load_battle_record_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, recovered)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 845 <= clicks[0][1] <= 915
    assert any("动作=close-battle-record" in line for line in logs)


# ── 第 13 个全局弹窗：骑士团「成长Rank提升」（2026-10-30）────────────────────
#
# 骑士团那一族（签到 / 领取支援 / 每周点数奖励）的第 5 个。只在骑士团成长等级提升时出现，
# 但撞上就必然卡住整条路线：2026-10-30 19:48 世界首领战从快捷菜单点「骑士团」之后，
# 它盖住骑士团主页 ⇒ 导航只等到 2 分钟上限，报「导航转场 快捷菜单 → knights_home 失败」。
# 同一层弹窗在 2026-10-08 的骑士团捐赠诊断帧里也出现过，一直没登记。


def test_knights_growth_rank_popup_is_recognized_from_both_anchors():
    """标题「骑士团成长Rank提升」+ 底部「点击关闭」，两个锚点都命中才算。"""
    popup = _global_screen("knights_growth_rank_live_20261030.png")
    templates = load_knights_growth_rank_templates(NAVIGATION_TEMPLATES)

    match = find_knights_growth_rank_close(popup, templates.title, templates.close)

    assert match is not None
    # 「点击关闭」实测中心 (960, 1034)。它比段位奖励那层（y≈879）低得多 ——
    # 这层弹窗更高，所以关闭点在更下面。
    assert 900 <= match.center[0] <= 1020
    assert 1000 <= match.center[1] <= 1070


def test_knights_growth_rank_popup_requires_title_and_close_anchor():
    """两个锚点缺一不可。"""
    popup = _global_screen("knights_growth_rank_live_20261030.png")
    templates = load_knights_growth_rank_templates(NAVIGATION_TEMPLATES)
    without_title = popup.copy()
    without_title[160:250, 720:1220] = 0
    without_close = popup.copy()
    without_close[995:1085, 880:1100] = 0

    assert (
        find_knights_growth_rank_close(without_title, templates.title, templates.close)
        is None
    )
    assert (
        find_knights_growth_rank_close(without_close, templates.title, templates.close)
        is None
    )


def test_knights_growth_rank_popup_rejects_the_pages_around_it():
    """弹窗背后的骑士团主页 / 快捷菜单 / 大厅都不能命中。"""
    templates = load_knights_growth_rank_templates(NAVIGATION_TEMPLATES)

    for name in ("quick_menu_over_lobby", "lobby"):
        frame = np.asarray(
            Image.open(
                ROOT / "tests" / "fixtures" / "epic7_navigation" / f"{name}.png"
            ).convert("RGB")
        )
        assert (
            find_knights_growth_rank_close(frame, templates.title, templates.close)
            is None
        ), name


def test_guard_dismisses_the_knights_growth_rank_popup():
    popup = _global_screen("knights_growth_rank_live_20261030.png")
    # 弹窗消掉之后落回的大厅那一页。
    recovered = np.asarray(
        Image.open(
            ROOT / "tests" / "fixtures" / "epic7_navigation" / "lobby.png"
        ).convert("RGB")
    )
    screens = iter([popup, popup, recovered])
    clicks = []
    logs = []
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
            knights_growth_rank_templates=load_knights_growth_rank_templates(
                NAVIGATION_TEMPLATES
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, recovered)
    assert len(clicks) == 1
    assert 900 <= clicks[0][0] <= 1020
    assert 1000 <= clicks[0][1] <= 1070
    assert any("动作=close-knights-growth-rank" in line for line in logs)


def test_date_change_popup_is_dismissed_from_its_close_label():
    """2026-11-03 PC 真机：游戏内「日期变更，将前往大厅。」通知。

    它会把画面**强制切回大厅**：主线正在「等待通关」时撞上 ⇒ 干等 46 秒无进展
    ⇒ 超时放弃（当天 18:00:42 那次）。页面一直没登记，guard 每帧过也看不见。

    判据沿用既有口径：标题排他（「变更日期」208x49，全库 364 张最高 0.5517，阈 0.82）
    + 底部「点击关闭」（138x30，中心 (961,770)）只负责定位。
    ⚠️ 「点击关闭」是游戏里通用灰字控件，**不能单独当判据**。

    模拟器口径没有 `pc/` 图 ⇒ 两个字段都是 None ⇒ 这条整段跳过，行为与历史一致。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "date_change_pc_live_20261103.png").convert("RGB")
    )
    pc_templates = load_date_change_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_date_change_templates(TEMPLATES)

    match = find_date_change_close(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.82
    assert abs(match.center[0] - 961) <= 8, match.center
    assert abs(match.center[1] - 770) <= 8, match.center

    # 模拟器口径：没有覆盖图 ⇒ 整条跳过（这条不该改变模拟器行为）。
    assert emulator_templates.title is None
    assert emulator_templates.close is None
    assert find_date_change_close(screen, emulator_templates) is None

    # 互斥：断线帧上不得命中（两种"网络/系统弹窗"不能串味）。
    other = np.asarray(
        Image.open(FIXTURES / "network_reconnect_pc_live_20261101.png").convert("RGB")
    )
    assert find_date_change_close(other, pc_templates) is None


def test_login_reward_popup_is_dismissed_from_its_close_label():
    """2026-11-03 PC 真机：每日「获得登录奖励」（6 格奖励）。

    这层**不吃 ESC**：收尾连按 2 次 ESC 页面毫无变化 ⇒「回首页失败」
    （当天 18:01:57 那次；同一帧上还有日期变更的收尾余波）。

    判据：标题「获得登录奖励」304x49 排他（全库最高 0.5703，阈 0.82）
    + 最底部「点击关闭」111x24（中心 (979,1093)）只负责定位。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "login_reward_pc_live_20261103.png").convert("RGB")
    )
    pc_templates = load_login_reward_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_login_reward_templates(TEMPLATES)

    match = find_login_reward_close(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.82
    assert abs(match.center[0] - 979) <= 8, match.center
    assert abs(match.center[1] - 1093) <= 8, match.center

    assert emulator_templates.title is None
    assert emulator_templates.close is None
    assert find_login_reward_close(screen, emulator_templates) is None

    # 互斥：不得在「变更日期」帧上命中（两个标题各认各的）。
    other = np.asarray(
        Image.open(FIXTURES / "date_change_pc_live_20261103.png").convert("RGB")
    )
    assert find_login_reward_close(other, pc_templates) is None


def test_network_retry_recognizes_the_smaller_rendering_of_the_same_message():
    """同一句「网络连接异常，请重新连接。」在 PC 上还有**小一号**的画法。

    2026-11-05 00:37 真机主线：战斗中掉线，弹窗盖住战场 43 秒，战斗监督报
    ``battle_unrecognized``。11-01 那张 PC 模板打这一帧只有 **0.6882**（阈 0.88）。

    证伪「是不是换了句话」：把 11-01 模板缩到 0.97 再打同一帧 ⇒ **0.9335**
    ⇒ 差异是纯缩放（字高 26 vs 25、字宽 361 vs 346），不是新文案。

    所以补的是 `global/pc/network_reconnect_message.png`（同句、小一号），
    **不动阈值、不动共享模板**：0.6882 离 0.88 差的是 0.19，压阈值就是拿判据换分数。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "network_reconnect_pc_story_20261105.png").convert("RGB")
    )
    pc_templates = load_network_reconnect_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.88
    # 点的是「点击重试 ∨」本体（实测按钮中心 (937,728)），不是文案与按钮之间的空白。
    assert abs(match.center[0] - 937) <= 8, match.center
    assert abs(match.center[1] - 728) <= 8, match.center
    # 模拟器口径必须仍认不出：小号模板只存在于 pc/，不许被复制成共享图。
    assert find_network_retry(screen, emulator_templates) is None


def test_network_retry_recognizes_the_pc_rendering_of_the_disconnected_message():
    """另一句文案「与服务器的连接已中断。」在 PC 上被**横向拉宽**，不是等比缩放。

    2026-11-03 21:37 英雄合成：点完「确认合成」掉线。共享模板打这一帧只有 0.6300
    （阈 0.88）；把模板按 1.04 倍重采样峰值也只到 **0.8629**，仍不过阈 ——
    因为 PC 上这句是**字形变宽**（文字宽 303、高 26，共享模板 291 x 27），
    高度几乎没变，等比缩放救不了它。

    后果：守卫看不见这层半透明横带 ⇒ 状态机把遮罩下的返回箭头当成
    「合成结果覆盖层未完整识别」⇒ 整条路线失败；同一晚另外几帧「回首页连按 ESC
    无反应」也是同一形状。

    所以补的是 `global/pc/network_disconnected_message.png`（同句、PC 版），
    **不动阈值、不动共享模板**：0.6300 离 0.88 差 0.25，压阈值就是拿判据换分数。
    """
    screen = np.asarray(
        Image.open(FIXTURES / "network_disconnected_pc_hero_20261103.png").convert("RGB")
    )
    pc_templates = load_network_reconnect_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_network_reconnect_templates(TEMPLATES)

    match = find_network_retry(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.88
    # 点的是「点击重试 ∨」本体（实测按钮中心 (960,731)）；这层是横带，
    # 屏幕中心落在文案与按钮之间的空白，点了没反应。
    assert abs(match.center[0] - 960) <= 8, match.center
    assert abs(match.center[1] - 731) <= 8, match.center
    # 模拟器口径必须仍认不出：新图只存在于 pc/，不许被复制成共享图。
    assert find_network_retry(screen, emulator_templates) is None


# ---- 「轻触后解锁」教学遮罩（2026-11-06 主线 Episode 4 第 11 关） ------------


def test_tutorial_unlock_is_recognised_on_pc_and_points_at_the_skip_button():
    """12:29 真机：主线第 10 关通关后，第 11 关一进「关卡入口」就盖上这层教学
    遮罩。它把「准备战斗」和 ESC 一起吞掉 ⇒ prepare_battle 点 4 次不转场、
    收尾连按 2 次 ESC 页面不动 ⇒ 主线 ✗ + 每日任务「已中止」，后面 8 条全没跑。

    判据只裁黑框**左半**（蓝色左框角 +「轻触后解锁」），不含会变的角色名：
    4 张真机帧 0.9999~1.0000，全库 360 张反例最高 0.4323（阈 0.82）。
    点击点是右上角「跳过教学 ✕」中心 (1762,100) —— 明确退出教学、不触发解锁。
    """
    screen = load_screen("tutorial_unlock_pc_live_20261106.png")
    pc_templates = load_tutorial_unlock_templates(TemplateDir(TEMPLATES, "pc"))
    emulator_templates = load_tutorial_unlock_templates(TEMPLATES)

    match = find_tutorial_unlock_skip(screen, pc_templates)

    assert match is not None
    assert match.score >= 0.99
    assert abs(match.center[0] - 1762) <= 8, match.center
    assert abs(match.center[1] - 100) <= 8, match.center
    # 模拟器口径：三张图都只在 pc/，一张都加载不到 ⇒ 整段跳过、行为零改动。
    assert (
        emulator_templates.title is None
        and emulator_templates.skip is None
        and emulator_templates.highlight is None
    )
    assert find_tutorial_unlock_skip(screen, emulator_templates) is None


def test_tutorial_unlock_does_not_fire_on_other_global_popups():
    """排他回归：别的全局弹窗 / 正常页面不许被认成这层教学遮罩。"""
    pc_templates = load_tutorial_unlock_templates(TemplateDir(TEMPLATES, "pc"))
    for name in (
        "arena_rank_reward_live_20261020.png",
        "date_change_pc_live_20261103.png",
        "login_reward_pc_live_20261103.png",
        "network_reconnect.png",
        "friendship_points_pc_20260830.png",
    ):
        assert find_tutorial_unlock_skip(load_screen(name), pc_templates) is None, name


def test_global_guard_dismisses_the_tutorial_unlock_overlay():
    """守卫复演：这层遮罩在 ``runtime.capture`` 上被点掉，返回恢复后的正常帧。

    钉住的不只是「finder 认得出」，而是**守卫真的会出手** —— 少接一个 kwarg、
    少一条 ``_find_popup`` 分支，这里就会原样返回教学层帧。
    """
    popup = load_screen("tutorial_unlock_pc_live_20261106.png")
    normal = np.asarray(
        Image.open(STORY_FIXTURES / "stage.png").convert("RGB")
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
            tutorial_unlock_templates=load_tutorial_unlock_templates(
                TemplateDir(TEMPLATES, "pc")
            ),
            sleep=clock.sleep,
            now=clock.now,
        )
    )

    received = runtime.capture()

    assert np.array_equal(received, normal)
    assert len(clicks) == 1
    assert abs(clicks[0][0] - 1762) <= 8, clicks
    assert abs(clicks[0][1] - 100) <= 8, clicks
    assert any("动作=dismiss-tutorial-unlock" in line for line in logs)
