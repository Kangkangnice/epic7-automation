from dataclasses import dataclass
from pathlib import Path

import numpy as np

from auto_game_unified.core.matcher import Match, find_template, load_template


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
