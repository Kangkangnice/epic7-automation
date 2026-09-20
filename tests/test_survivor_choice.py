"""升级三选一「优先选蓝色卡」的判据测试。

用户要求：升级弹窗出现时优先选蓝色的卡，没有蓝色就随机选一张。

实测发现卡面颜色编码的是**武器类别**而不是稀有度——三张「攻击武器」卡（含开局那把，
用户明确说是蓝色）标签栏中位色相都是 94，而「辅助武器」卡是 77。所以「蓝色」等价于
「攻击武器卡」，判据落在色相带上。
"""

import random
from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.survivor import (
    BLUE_CARD_HUE,
    LEVEL_UP_CARDS,
    LEVEL_UP_LABEL_STRIP_Y,
    WEAPON_CARD_BOX,
)
from auto_game_unified.games.epic7.survivor import (
    card_center,
    card_label_hue,
    choose_level_up_card,
    is_blue_card,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# 「辅助武器」卡标签栏的实测配色（RGB），用来造「三张都不是蓝卡」的场景。
SUPPORT_CARD_RGB = (48, 208, 144)


class _NoRandom:
    """有蓝卡时必须完全用不到随机；碰了就炸。"""

    def choice(self, sequence):
        raise AssertionError("有蓝卡时不该调用随机选择")


class _FixedRandom:
    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0

    def choice(self, sequence):
        self.calls += 1
        assert self.value in sequence
        return self.value


def _screen(group: str, name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / group / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"缺少 fixture: {group}/{name}"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _all_support_screen() -> np.ndarray:
    """三张卡的标签栏都刷成「辅助武器」绿：这就是用户说的「三张全是绿卡」。"""

    screen = np.zeros((1132, 1982, 3), dtype=np.uint8)
    y0, y1 = LEVEL_UP_LABEL_STRIP_Y
    for x, _, width, _ in LEVEL_UP_CARDS:
        screen[y0:y1, x : x + width] = SUPPORT_CARD_RGB
    return screen


def test_attack_weapon_cards_share_the_opening_card_hue():
    """开局那张卡用户说是蓝色；升级页两张「攻击武器」卡应与它同色。"""

    opening = _screen("epic7_survivor", "first_card_select")
    level_up = _screen("epic7_survivor", "level_up")

    opening_hue = card_label_hue(opening, WEAPON_CARD_BOX)
    assert abs(opening_hue - card_label_hue(level_up, LEVEL_UP_CARDS[0])) <= 2
    assert abs(opening_hue - card_label_hue(level_up, LEVEL_UP_CARDS[2])) <= 2


def test_support_weapon_card_is_not_blue():
    """「辅助武器」卡实测比蓝卡低 17 个色相，必须落在判据外。"""

    level_up = _screen("epic7_survivor", "level_up")

    assert is_blue_card(level_up, LEVEL_UP_CARDS[0])
    assert is_blue_card(level_up, LEVEL_UP_CARDS[2])
    assert not is_blue_card(level_up, LEVEL_UP_CARDS[1])


def test_choose_level_up_card_takes_the_left_attack_weapon_card():
    level_up = _screen("epic7_survivor", "level_up")

    assert choose_level_up_card(level_up, _NoRandom()) == 0
    assert card_center(0) == (516, 570)


def test_choose_level_up_card_picks_randomly_when_no_card_is_blue():
    """用户实测反馈：偶尔三张全是绿卡，这时随机选一张，不要固定点最左边。"""

    screen = _all_support_screen()
    assert not any(is_blue_card(screen, card) for card in LEVEL_UP_CARDS)

    fixed = _FixedRandom(2)
    assert choose_level_up_card(screen, fixed) == 2
    assert fixed.calls == 1

    # 换个种子给出确定的另一张，说明结果确实由 rng 决定。
    assert choose_level_up_card(screen, random.Random(7)) == choose_level_up_card(
        screen, random.Random(7)
    )


def test_random_fallback_can_reach_every_card():
    """随机结果必须覆盖三张卡，且始终是可点的合法序号。"""

    screen = _all_support_screen()
    rng = random.Random(20260916)

    picks = {choose_level_up_card(screen, rng) for _ in range(200)}

    assert picks == set(range(len(LEVEL_UP_CARDS)))


def test_card_center_lands_inside_its_own_card():
    """点击点直接用卡片矩形中心，必须落在卡内才点得到。"""

    for index, (x, y, width, height) in enumerate(LEVEL_UP_CARDS):
        center_x, center_y = card_center(index)
        assert x <= center_x <= x + width
        assert y <= center_y <= y + height


def test_blue_hue_band_excludes_the_support_card_hue():
    support_hue = card_label_hue(
        _screen("epic7_survivor", "level_up"), LEVEL_UP_CARDS[1]
    )

    assert not (BLUE_CARD_HUE[0] <= support_hue <= BLUE_CARD_HUE[1])
