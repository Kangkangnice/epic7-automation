from pathlib import Path

import numpy as np
from PIL import Image

from auto_game_unified.games.epic7.global_popups import (
    find_network_retry,
    load_network_reconnect_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "epic7_global" / "network_reconnect.png"
TEMPLATES = ROOT / "games" / "epic7" / "templates" / "global"


def load_screen() -> np.ndarray:
    return np.asarray(Image.open(FIXTURE).convert("RGB"))


def test_network_retry_requires_message_and_retry_anchors():
    screen = load_screen()
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
