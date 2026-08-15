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


@dataclass(frozen=True)
class IntimacyLevelUpTemplates:
    title: np.ndarray
    dismiss: np.ndarray


_REFERENCE_SIZE = (1982, 1132)
_MESSAGE_REGION = (700, 450, 600, 180)
_RETRY_REGION = (780, 630, 400, 230)
_INTIMACY_TITLE_REGION = (800, 220, 700, 180)
_INTIMACY_DISMISS_REGION = (850, 780, 650, 250)


def load_network_reconnect_templates(
    template_dir: Path,
) -> NetworkReconnectTemplates:
    return NetworkReconnectTemplates(
        message=load_template(str(template_dir / "network_message.png")),
        retry=load_template(str(template_dir / "network_retry.png")),
    )


def load_intimacy_level_up_templates(
    template_dir: Path,
) -> IntimacyLevelUpTemplates:
    return IntimacyLevelUpTemplates(
        title=load_template(str(template_dir / "intimacy_level_up_title.png")),
        dismiss=load_template(str(template_dir / "intimacy_level_up_dismiss.png")),
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
    dismiss = locate(templates.dismiss, _INTIMACY_DISMISS_REGION)
    if title is None or dismiss is None:
        return None
    return Match(dismiss.center, min(title.score, dismiss.score))


def find_network_retry(
    screen: np.ndarray,
    templates: NetworkReconnectTemplates,
) -> Match | None:
    message = find_template(
        screen,
        templates.message,
        0.88,
        region=_MESSAGE_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if message is None:
        return None
    retry = find_template(
        screen,
        templates.retry,
        0.88,
        region=_RETRY_REGION,
        reference_size=_REFERENCE_SIZE,
    )
    if retry is None:
        return None
    return Match(retry.center, min(message.score, retry.score))


class Epic7GlobalPopupGuard:
    """Consume known system popups before business state machines see them."""

    def __init__(
        self,
        templates: NetworkReconnectTemplates,
        *,
        intimacy_templates: IntimacyLevelUpTemplates | None = None,
        sleep: Callable[[float], None] = default_sleep,
        now: Callable[[], float] = monotonic,
        poll_seconds: float = 1.0,
        retry_interval_seconds: float = 3.0,
        failure_seconds: float = 15.0,
    ) -> None:
        self.templates = templates
        self.intimacy_templates = intimacy_templates
        self.sleep = sleep
        self.now = now
        self.poll_seconds = poll_seconds
        self.retry_interval_seconds = retry_interval_seconds
        self.failure_seconds = failure_seconds

    def __call__(
        self, runtime: "Runtime", screen: np.ndarray
    ) -> tuple[np.ndarray, bool]:
        stable_frames = 0
        clicks = 0
        last_click_at: float | None = None
        handled = False
        active_popup: str | None = None
        while True:
            match = find_network_retry(screen, self.templates)
            popup = "network"
            action = "retry-network"
            diagnostic_label = "network_retry_failed"
            failure_message = "network retry popup persisted after 2 attempts"
            if match is None and self.intimacy_templates is not None:
                match = find_intimacy_level_up_dismiss(
                    screen,
                    self.intimacy_templates,
                )
                popup = "intimacy"
                action = "dismiss-intimacy-level-up"
                diagnostic_label = "intimacy_level_up_failed"
                failure_message = "intimacy level-up popup persisted after 2 attempts"
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
                if clicks == 0 or (
                    clicks == 1
                    and last_click_at is not None
                    and current - last_click_at >= self.retry_interval_seconds
                ):
                    runtime.click(match.center, action)
                    clicks += 1
                    last_click_at = current
                elif (
                    clicks >= 2
                    and last_click_at is not None
                    and current - last_click_at >= self.failure_seconds
                ):
                    path = (
                        runtime.save_diagnostic(diagnostic_label, screen)
                        if runtime.diagnostic_dir is not None
                        else "not-configured"
                    )
                    raise RuntimeError(
                        f"{failure_message}; saved {path}"
                    )
            self.sleep(self.poll_seconds)
            screen = runtime.capture_unguarded()
