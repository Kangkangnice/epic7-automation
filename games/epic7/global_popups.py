from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep as default_sleep
from typing import Callable, TYPE_CHECKING

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template

if TYPE_CHECKING:
    from auto_game_unified.core.runtime import Runtime


@dataclass(frozen=True)
class NetworkReconnectTemplates:
    message: np.ndarray
    retry: np.ndarray


_REFERENCE_SIZE = (1982, 1132)
_MESSAGE_REGION = (700, 450, 600, 180)
_RETRY_REGION = (780, 630, 400, 230)


def load_network_reconnect_templates(
    template_dir: Path,
) -> NetworkReconnectTemplates:
    return NetworkReconnectTemplates(
        message=load_template(str(template_dir / "network_message.png")),
        retry=load_template(str(template_dir / "network_retry.png")),
    )


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
        sleep: Callable[[float], None] = default_sleep,
        now: Callable[[], float] = monotonic,
        poll_seconds: float = 1.0,
        retry_interval_seconds: float = 3.0,
        failure_seconds: float = 15.0,
    ) -> None:
        self.templates = templates
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
        while True:
            retry = find_network_retry(screen, self.templates)
            if retry is None:
                return screen, handled
            handled = True
            stable_frames += 1
            current = self.now()
            if stable_frames >= 2:
                if clicks == 0 or (
                    clicks == 1
                    and last_click_at is not None
                    and current - last_click_at >= self.retry_interval_seconds
                ):
                    runtime.click(retry.center, "retry-network")
                    clicks += 1
                    last_click_at = current
                elif (
                    clicks >= 2
                    and last_click_at is not None
                    and current - last_click_at >= self.failure_seconds
                ):
                    path = (
                        runtime.save_diagnostic("network_retry_failed", screen)
                        if runtime.diagnostic_dir is not None
                        else "not-configured"
                    )
                    raise RuntimeError(
                        "network retry popup persisted after 2 attempts; "
                        f"saved {path}"
                    )
            self.sleep(self.poll_seconds)
            screen = runtime.capture_unguarded()
