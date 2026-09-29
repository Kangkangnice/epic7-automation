from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep as default_sleep
from typing import Callable, TYPE_CHECKING

import cv2
import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template

if TYPE_CHECKING:
    from auto_game_unified.core.runtime import Runtime


@dataclass(frozen=True)
class NetworkReconnectTemplates:
    message: np.ndarray
    retry: np.ndarray
    message_alt: np.ndarray | None = None
    retry_alt: np.ndarray | None = None


@dataclass(frozen=True)
class IntimacyLevelUpTemplates:
    title: np.ndarray
    dismiss: np.ndarray


@dataclass(frozen=True)
class FriendshipPointsTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class FriendRequestTemplates:
    title: np.ndarray
    cancel: np.ndarray


@dataclass(frozen=True)
class KnightsSigninTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class GiftSupportTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class KnightsWeeklyRewardTemplates:
    title: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class PetGiftTemplates:
    """宠物小屋礼物角标（**单锚点**：整个角标就是要点的目标，没有标题/关闭点）。"""

    badge: np.ndarray


_REFERENCE_SIZE = (1982, 1132)
_MESSAGE_REGION = (700, 450, 600, 180)
_RETRY_REGION = (780, 630, 400, 230)
_INTIMACY_TITLE_REGION = (800, 220, 700, 180)
_INTIMACY_DISMISS_REGION = (850, 780, 650, 250)
_FRIENDSHIP_TITLE_REGION = (600, 150, 800, 180)
_FRIENDSHIP_CLOSE_REGION = (750, 840, 450, 190)
_FRIENDSHIP_ANCHOR_THRESHOLD = 0.55
_FRIEND_REQUEST_TITLE_REGION = (650, 240, 700, 160)
_FRIEND_REQUEST_CANCEL_REGION = (550, 720, 500, 230)
# 骑士团签到弹窗：标题在面板上部，「点击关闭」在面板下部（面板会盖住骑士团主页）。
_KNIGHTS_SIGNIN_TITLE_REGION = (700, 260, 600, 90)
_KNIGHTS_SIGNIN_CLOSE_REGION = (860, 810, 280, 70)
# ⚠️ 阈值 0.80 是按「标题锚点」定的，不是按关闭点 —— 关闭点单独不可靠：
# 全库 187 张实测「点击关闭」这四个字在 hero 的 imprint_sss_warning_popup 上能拿
# **0.9986**、imprint_result_popup 0.9908、reward_popup 0.9846、expedition
# victory_popup 0.9355 —— 因为它们用的是同一种「底部居中点击关闭/点击继续」灰字控件。
# 而标题锚点跨页最高只有 **0.3278**（hero/reward_popup），离 0.80 有 0.47 余量。
# ⇒ 必须**双锚点同时命中**才算（见 find_knights_signin_close），
#   只用关闭点会在别的弹窗上乱点。这与项目记忆里「arena/expedition 共用 confirm 锚点」
#   是同一类坑。扫描脚本：runtime_logs/_knights_signin_probe.py。
_KNIGHTS_SIGNIN_THRESHOLD = 0.80
# 「领取支援物品」弹窗（进骑士团时团员赠送的支援资源到账，会盖住骑士团主页）：
# 标题在面板上部（与签到弹窗同一 ROI），「点击关闭」在面板下部。
# 与签到弹窗同理：标题锚点排他、关闭点不排他（hero/reward_popup 上单独 0.9996），
# 必须**双锚点同时命中**。实测弹窗帧 title=1.0000 / close=1.0000；
# 跨页标题最高只有 0.3240，签到弹窗在这张图上标题仅 0.3220 ⇒ 两者互不误触。
_GIFT_SUPPORT_TITLE_REGION = (700, 260, 600, 90)
_GIFT_SUPPORT_CLOSE_REGION = (860, 810, 300, 80)
_GIFT_SUPPORT_THRESHOLD = 0.80
# 「获得每周骑士团点数奖励」弹窗（**每周一结算**时弹出，盖在骑士团主页上）：
# 标题「获得每周骑士团点数奖励」在面板上部（与签到/支援弹窗同一 ROI），
# 「点击关闭」在面板下部。与那两个弹窗同理：标题锚点排他、关闭点单独不排他
# （hero/reward_popup 上「点击关闭」能拿 0.9996），必须**双锚点同时命中**。
# 实测弹窗帧 title=1.0000 / close=1.0000；跨页标题最高只有 **0.3376**
# （恰在签到弹窗上 0.3376、其它都 <0.27），离 0.80 余量极大，互不误触。
# 素材来自 2026-09-28 实跑骑士团捐赠时的原始诊断帧
#（tests/fixtures/epic7_world_boss/knights_weekly_reward_popup.png）。
_KNIGHTS_WEEKLY_REWARD_TITLE_REGION = (700, 260, 600, 90)
_KNIGHTS_WEEKLY_REWARD_CLOSE_REGION = (860, 810, 300, 80)
_KNIGHTS_WEEKLY_REWARD_THRESHOLD = 0.80
# 「宠物小屋礼物角标」：**不是盖住页面的模态弹窗**，而是挂在**快捷菜单页**上的一个小角标
# （就是回家流程点那颗「啤酒杯 → 酒馆」的那一页）。宠物送礼时，宠物小屋图标旁边会挂出
# 一个「紫金礼盒 + 对话气泡」的角标；**点它一下才会领取礼物、角标才消失**，
# 不点就一直挂着，每天回家都会看见。
#
# ⚠️ 这条是**单锚点**（与上面几个弹窗不同）：那个角标没有「标题 + 关闭点」这对东西，
# 整个角标本身就是可点的目标 —— 点它（或它上面任意位置）即可，所以「标题排他 + 关闭点」
# 的结构在这里根本不成立，硬凑第二锚点只会引入无谓的脆弱。排他性改由
# 「区域限定 + 图形本身独特」保证，并已实测：
# 2026-09-28 用 `runtime_logs/_pet_badge_scan.py` 扫全库 213 张夹具 ——
# **自身 1.0000，第二名只有 0.5017**（`epic7_labyrinth_stone/labyrinth_detail.png`），
# 阈值 0.80 的余量 0.30+，比骑士团三个弹窗（第二名 0.32）还宽。
# 若将来真出现误触，再补「宠物小屋图标」当第二锚点即可（它一直在这一页上）。
_PET_GIFT_BADGE_REGION = (1500, 300, 300, 220)
_PET_GIFT_THRESHOLD = 0.80


def load_network_reconnect_templates(
    template_dir: Path,
) -> NetworkReconnectTemplates:
    alt_message = template_dir / "network_disconnected_message.png"
    alt_retry = template_dir / "network_disconnected_retry.png"
    return NetworkReconnectTemplates(
        message=load_template(str(template_dir / "network_message.png")),
        retry=load_template(str(template_dir / "network_retry.png")),
        message_alt=(load_template(str(alt_message)) if alt_message.exists() else None),
        retry_alt=(load_template(str(alt_retry)) if alt_retry.exists() else None),
    )


def load_intimacy_level_up_templates(
    template_dir: Path,
) -> IntimacyLevelUpTemplates:
    return IntimacyLevelUpTemplates(
        title=load_template(str(template_dir / "intimacy_level_up_title.png")),
        dismiss=load_template(str(template_dir / "intimacy_level_up_dismiss.png")),
    )


def load_friendship_points_templates(
    template_dir: Path,
) -> FriendshipPointsTemplates:
    return FriendshipPointsTemplates(
        title=load_template(str(template_dir / "friendship_points_title.png")),
        close=load_template(str(template_dir / "friendship_points_close.png")),
    )


def load_friend_request_templates(
    template_dir: Path,
) -> FriendRequestTemplates:
    return FriendRequestTemplates(
        title=load_template(str(template_dir / "friend_request_title.png")),
        cancel=load_template(str(template_dir / "friend_request_cancel.png")),
    )


def load_knights_signin_templates(
    template_dir: Path,
) -> KnightsSigninTemplates:
    return KnightsSigninTemplates(
        title=load_template(str(template_dir / "knights_signin_title.png")),
        close=load_template(str(template_dir / "knights_signin_close.png")),
    )


def load_gift_support_templates(
    template_dir: Path,
) -> GiftSupportTemplates:
    return GiftSupportTemplates(
        title=load_template(str(template_dir / "gift_support_title.png")),
        close=load_template(str(template_dir / "gift_support_close.png")),
    )


def load_knights_weekly_reward_templates(
    template_dir: Path,
) -> KnightsWeeklyRewardTemplates:
    return KnightsWeeklyRewardTemplates(
        title=load_template(str(template_dir / "knights_weekly_reward_title.png")),
        close=load_template(str(template_dir / "knights_weekly_reward_close.png")),
    )


def load_pet_gift_templates(template_dir: Path) -> PetGiftTemplates:
    return PetGiftTemplates(
        badge=load_template(str(template_dir / "pet_gift_badge.png")),
    )


def find_intimacy_level_up_dismiss(
    screen: np.ndarray,
    templates: IntimacyLevelUpTemplates,
) -> Match | None:
    lower = np.array([0, 0, 100])
    upper = np.array([179, 100, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        ref_x, ref_y, ref_width, ref_height = region
        scale_x = screen.shape[1] / _REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _REFERENCE_SIZE[1]
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width],
            cv2.COLOR_RGB2HSV,
        )
        template_hsv = cv2.cvtColor(
            template,
            cv2.COLOR_RGB2HSV,
        )
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            0.82,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(templates.title, _INTIMACY_TITLE_REGION)
    if title is None:
        return None
    dismiss = locate(templates.dismiss, _INTIMACY_DISMISS_REGION)
    if dismiss is None:
        return Match((screen.shape[1] // 2, screen.shape[0] // 2), title.score)
    return Match(dismiss.center, min(title.score, dismiss.score))


def find_network_retry(
    screen: np.ndarray,
    templates: NetworkReconnectTemplates,
) -> Match | None:
    for message_template, retry_template in (
        (templates.message, templates.retry),
        (templates.message_alt, templates.retry_alt),
    ):
        if message_template is None or retry_template is None:
            continue
        message = find_template(
            screen,
            message_template,
            0.88,
            region=_MESSAGE_REGION,
            reference_size=_REFERENCE_SIZE,
        )
        if message is None:
            continue
        retry = find_template(
            screen,
            retry_template,
            0.88,
            region=_RETRY_REGION,
            reference_size=_REFERENCE_SIZE,
        )
        if retry is not None:
            return Match(retry.center, min(message.score, retry.score))
    return None


def find_friendship_points_popup_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both friendship-popup anchors exist."""
    lower = np.array([0, 0, 120])
    upper = np.array([179, 110, 255])

    def locate(template: np.ndarray, region: tuple[int, int, int, int]):
        scale_x = screen.shape[1] / _REFERENCE_SIZE[0]
        scale_y = screen.shape[0] / _REFERENCE_SIZE[1]
        ref_x, ref_y, ref_width, ref_height = region
        x, y, width, height = (
            round(ref_x * scale_x),
            round(ref_y * scale_y),
            round(ref_width * scale_x),
            round(ref_height * scale_y),
        )
        search_hsv = cv2.cvtColor(
            screen[y : y + height, x : x + width], cv2.COLOR_RGB2HSV
        )
        template_hsv = cv2.cvtColor(template, cv2.COLOR_RGB2HSV)
        match = find_template(
            cv2.inRange(search_hsv, lower, upper),
            cv2.inRange(template_hsv, lower, upper),
            _FRIENDSHIP_ANCHOR_THRESHOLD,
            reference_size=(ref_width, ref_height),
        )
        if match is None:
            return None
        return Match((x + match.center[0], y + match.center[1]), match.score)

    title = locate(title_template, _FRIENDSHIP_TITLE_REGION)
    close = locate(close_template, _FRIENDSHIP_CLOSE_REGION)
    if title is None or close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_friend_request_cancel(
    screen: np.ndarray,
    title_template: np.ndarray,
    cancel_template: np.ndarray,
) -> Match | None:
    """Return Cancel only when both friend-request popup anchors are present."""
    title = find_template(
        screen,
        title_template,
        0.82,
        region=_FRIEND_REQUEST_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    cancel = find_template(
        screen,
        cancel_template,
        0.82,
        region=_FRIEND_REQUEST_CANCEL_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if cancel is None:
        return None
    return Match(cancel.center, min(title.score, cancel.score))


def find_knights_signin_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both knights-signin popup anchors exist.

    这是「每天第一次进骑士团」的签到达成度奖励弹窗。它盖在骑士团主页上，
    把底页的 ``worldboss_entry`` 锚点从 0.9890 压到 0.4477（低于 0.85 门槛），
    所以弹窗期间页面识别必然失败 —— 必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算，避免「点击关闭」这四个字在别的弹窗上撞车。
    实测弹窗帧上双锚点都是 1.0000，弹窗关闭后标题掉到 0.1799、关闭点掉到 0.3012。
    """
    title = find_template(
        screen,
        title_template,
        _KNIGHTS_SIGNIN_THRESHOLD,
        region=_KNIGHTS_SIGNIN_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _KNIGHTS_SIGNIN_THRESHOLD,
        region=_KNIGHTS_SIGNIN_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_gift_support_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both gift-support popup anchors exist.

    这是「进骑士团时团员赠送的支援资源到账」弹窗（标题「领取支援物品」）。
    它和签到弹窗一样盖在骑士团主页上，会把底页锚点压暗 ⇒ 弹窗期间页面识别必然失败，
    必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算：标题锚点排他（跨页最高 0.3240），
    但「点击关闭」这四个字单独不排他（hero/reward_popup 上 0.9996），
    所以必须靠标题把「点击关闭」的乱命中挡掉。
    实测弹窗帧双锚点都是 1.0000。
    """
    title = find_template(
        screen,
        title_template,
        _GIFT_SUPPORT_THRESHOLD,
        region=_GIFT_SUPPORT_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _GIFT_SUPPORT_THRESHOLD,
        region=_GIFT_SUPPORT_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_knights_weekly_reward_close(
    screen: np.ndarray,
    title_template: np.ndarray,
    close_template: np.ndarray,
) -> Match | None:
    """Return the close anchor only when both weekly-reward popup anchors exist.

    这是「每周一骑士团点数结算」弹窗（标题「获得每周骑士团点数奖励」）。
    它和签到/支援弹窗一样盖在骑士团主页上，会把底页锚点压暗 ⇒ 弹窗期间页面
    识别必然失败，必须先关掉它再识别，不能指望穿透。

    两个锚点都命中才算：标题锚点排他（跨页最高 0.3376），
    但「点击关闭」这四个字单独不排他（hero/reward_popup 上 0.9996），
    所以必须靠标题把「点击关闭」的乱命中挡掉。实测弹窗帧双锚点都是 1.0000。
    """
    title = find_template(
        screen,
        title_template,
        _KNIGHTS_WEEKLY_REWARD_THRESHOLD,
        region=_KNIGHTS_WEEKLY_REWARD_TITLE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if title is None:
        return None
    close = find_template(
        screen,
        close_template,
        _KNIGHTS_WEEKLY_REWARD_THRESHOLD,
        region=_KNIGHTS_WEEKLY_REWARD_CLOSE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if close is None:
        return None
    return Match(close.center, min(title.score, close.score))


def find_pet_gift_badge(
    screen: np.ndarray,
    badge_template: np.ndarray,
) -> Match | None:
    """认「宠物小屋礼物角标」，返回点击点（角标中心）。

    与上面几个弹窗不同，这是**单锚点**：那个角标没有「标题 + 关闭点」，
    整个角标本身就是要点掉的目标（理由与实测余量见
    ``_PET_GIFT_BADGE_REGION`` 上方的注释）。
    点它一下 → 礼物领取、角标消失；不点则一直挂着，每天回家都会看见。
    """
    return find_template(
        screen,
        badge_template,
        _PET_GIFT_THRESHOLD,
        region=_PET_GIFT_BADGE_REGION,
        reference_size=_REFERENCE_SIZE,
    )


class Epic7GlobalPopupGuard:
    """Consume known system popups before business state machines see them."""

    def __init__(
        self,
        templates: NetworkReconnectTemplates,
        *,
        intimacy_templates: IntimacyLevelUpTemplates | None = None,
        friendship_templates: FriendshipPointsTemplates | None = None,
        friend_request_templates: FriendRequestTemplates | None = None,
        knights_signin_templates: KnightsSigninTemplates | None = None,
        gift_support_templates: GiftSupportTemplates | None = None,
        knights_weekly_reward_templates: KnightsWeeklyRewardTemplates | None = None,
        pet_gift_templates: PetGiftTemplates | None = None,
        sleep: Callable[[float], None] = default_sleep,
        now: Callable[[], float] = monotonic,
        poll_seconds: float = 1.0,
        retry_interval_seconds: float = 3.0,
        failure_seconds: float = 15.0,
    ) -> None:
        self.templates = templates
        self.intimacy_templates = intimacy_templates
        self.friendship_templates = friendship_templates
        self.friend_request_templates = friend_request_templates
        self.knights_signin_templates = knights_signin_templates
        self.gift_support_templates = gift_support_templates
        self.knights_weekly_reward_templates = knights_weekly_reward_templates
        self.pet_gift_templates = pet_gift_templates
        self.sleep = sleep
        self.now = now
        self.poll_seconds = poll_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.failure_seconds = failure_seconds

    def _find_popup(
        self, screen: np.ndarray
    ) -> tuple[Match | None, str | None, str | None, str | None, str | None]:
        """按优先级返回首个命中的弹窗（匹配点, 标识, 动作, 诊断标签, 失败文案）。"""
        match = find_network_retry(screen, self.templates)
        if match is not None:
            return (
                match,
                "network",
                "retry-network",
                "network_retry_failed",
                "断网重连弹窗点击4次后仍未消失",
            )
        if self.intimacy_templates is not None:
            match = find_intimacy_level_up_dismiss(screen, self.intimacy_templates)
            if match is not None:
                return (
                    match,
                    "intimacy",
                    "dismiss-intimacy-level-up",
                    "intimacy_level_up_failed",
                    "亲密度提升弹窗点击4次后仍未消失",
                )
        if self.friendship_templates is not None:
            match = find_friendship_points_popup_close(
                screen,
                self.friendship_templates.title,
                self.friendship_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "friendship_points",
                    "close-friendship-points-popup",
                    "friendship_points_failed",
                    "友情点数弹窗点击4次后仍未消失",
                )
        if self.friend_request_templates is not None:
            match = find_friend_request_cancel(
                screen,
                self.friend_request_templates.title,
                self.friend_request_templates.cancel,
            )
            if match is not None:
                return (
                    match,
                    "friend_request",
                    "cancel-friend-request",
                    "friend_request_failed",
                    "好友申请弹窗点击4次后仍未消失",
                )
        if self.knights_signin_templates is not None:
            match = find_knights_signin_close(
                screen,
                self.knights_signin_templates.title,
                self.knights_signin_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "knights_signin",
                    "close-knights-signin",
                    "knights_signin_failed",
                    "骑士团签到弹窗点击4次后仍未消失",
                )
        if self.gift_support_templates is not None:
            match = find_gift_support_close(
                screen,
                self.gift_support_templates.title,
                self.gift_support_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "gift_support",
                    "close-gift-support",
                    "gift_support_failed",
                    "领取支援物品弹窗点击4次后仍未消失",
                )
        if self.knights_weekly_reward_templates is not None:
            match = find_knights_weekly_reward_close(
                screen,
                self.knights_weekly_reward_templates.title,
                self.knights_weekly_reward_templates.close,
            )
            if match is not None:
                return (
                    match,
                    "knights_weekly_reward",
                    "close-knights-weekly-reward",
                    "knights_weekly_reward_failed",
                    "骑士团周结算奖励弹窗点击4次后仍未消失",
                )
        if self.pet_gift_templates is not None:
            match = find_pet_gift_badge(screen, self.pet_gift_templates.badge)
            if match is not None:
                return (
                    match,
                    "pet_gift",
                    "claim-pet-gift",
                    "pet_gift_failed",
                    "宠物小屋礼物角标点击4次后仍未消失",
                )
        return None, None, None, None, None

    def __call__(
        self, runtime: "Runtime", screen: np.ndarray
    ) -> tuple[np.ndarray, bool]:
        stable_frames = 0
        clicks = 0
        last_click_at: float | None = None
        handled = False
        active_popup: str | None = None
        while True:
            match, popup, action, diagnostic_label, failure_message = self._find_popup(screen)
            if match is None:
                return screen, handled
            handled = True
            if popup != active_popup:
                active_popup = popup
                stable_frames = 1
                clicks = 0
                last_click_at = None
            else:
                stable_frames += 1
            current = self.now()
            if stable_frames >= 2:
                # 点击预算 4 次，间隔 3 秒；模拟器卡顿会吞掉转场期间的输入，
                # 多给几次机会。末次点击后 15 秒仍无改善才判定熔断。
                if (
                    last_click_at is None
                    or (
                        clicks < 4
                        and current - last_click_at >= self.retry_interval_seconds
                    )
                ):
                    runtime.click(match.center, action)
                    clicks += 1
                    last_click_at = current
                elif (
                    clicks >= 4
                    and last_click_at is not None
                    and current - last_click_at >= self.failure_seconds
                ):
                    path = (
                        runtime.save_diagnostic(diagnostic_label, screen)
                        if runtime.diagnostic_dir is not None
                        else "not-configured"
                    )
                    raise RuntimeError(
                        f"{failure_message}；已保存诊断 {path}"
                    )
            self.sleep(self.poll_seconds)
            screen = runtime.capture_unguarded()
