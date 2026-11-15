# -*- coding: utf-8 -*-
"""宠物领养路线的判据与决策护栏（2026-11-15 模拟器实机帧）。

## 这组测试守什么

1. **只点带「免费」标记的领养** —— 今天采到的是「已领完」的付费态。
   认不出状态的领养弹窗必须安全停止并留证，绝不产生任何点击坐标。
   这是用户反复强调的红线：没有免费标记的那颗按钮会消耗宠物领养券。
2. **弹窗优先于小屋** —— 领养弹窗是半透明遮罩，底下小屋标题实测 0.9996。
3. **业务流程不因「今天不买」而跳过** —— 默认不买也要进商店、滑到底、
   确认三件用品状态，再收工。
4. **一轮只记一次**，preview 试算不能推进业务进度。
5. **两态判据互不串页** —— 全库反向验证里，标题类跨页最高 0.6472，
   券图标跨页最高 0.1572，0.80 门槛两侧都有余量。
"""

from pathlib import Path

import numpy as np
import pytest

from auto_game_unified.games.epic7.pet_adoption import (
    PetAdoptionState,
    PetAdoptionStateMachine,
    build_pet_adoption_templates,
    detect_resume_point,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_pet_adoption"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def load(name: str) -> np.ndarray:
    """读一张整屏夹具；走 imdecode 绕开 conftest 的图像缓存。"""
    import cv2

    data = (FIXTURES / f"{name}.png").read_bytes()
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)[:1132, :1982]


@pytest.fixture(scope="module")
def templates():
    return build_pet_adoption_templates(TEMPLATES)


def machine(templates, **kwargs) -> PetAdoptionStateMachine:
    return PetAdoptionStateMachine(templates, **kwargs)


# ── 页面识别 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("house", PetAdoptionState.HOUSE),
        ("house_after_adopt", PetAdoptionState.HOUSE),
        ("adopt_popup_paid", PetAdoptionState.ADOPT_POPUP),
        ("shop_top", PetAdoptionState.SHOP),
        ("shop_bottom", PetAdoptionState.SHOP),
        ("shop_bottom_still", PetAdoptionState.SHOP),
        # 两轮连跑时列表停在略有不同的滚动位置（2026-11-15 实跑超时帧）。
        ("shop_bottom_scrolled", PetAdoptionState.SHOP),
    ],
)
def test_recognizes_its_own_pages(templates, fixture, expected):
    assert machine(templates).observe_page(load(fixture)) is expected


@pytest.mark.parametrize("fixture", ["lobby", "quick_menu"])
def test_other_pages_are_not_mistaken_for_route_pages(templates, fixture):
    assert machine(templates).observe_page(load(fixture)) is None


def test_adopt_popup_wins_over_the_house_underneath(templates):
    """半透明遮罩下 house_title 实测仍 0.9996，弹窗必须排在前面。"""
    assert machine(templates).observe_page(load("adopt_popup_paid")) is (
        PetAdoptionState.ADOPT_POPUP
    )


# ── 一整轮动作顺序 ──────────────────────────────────────────────────────────


def test_full_round_action_sequence_and_points(templates):
    m = machine(templates)
    sequence = [
        "house",
        "adopt_popup_paid",
        "house_after_adopt",
        "shop_top",
        "shop_bottom",
    ]
    actions = []
    for name in sequence:
        action = m.next_action(load(name))
        actions.append(None if action is None else (action.name, action.point))
    assert actions == [
        ("open-adopt", (1341, 1056)),
        ("close-adopt", (992, 1090)),
        ("open-shop", (205, 1051)),
        ("scroll-shop", (700, 1030)),
        None,
    ]
    assert m.completed_cycles == 1
    assert m.adopt_checked is True
    assert m.shop_scrolls == 1


def test_scrolled_shop_still_ends_the_round_without_extra_scrolls(templates):
    """实跑事故回归：列表滚动位置偏移时，不许再盲目下滑。

    2026-11-15 两轮连跑，第二轮开局停在商店底部但滚动位置比夹具高约 40px，
    窄搜索区把「已经到底」判成「还没到底」，连滑 3 次后状态超时（退出码 1）。
    宽区域把这帧从 0.2797 救到 0.9878，且未滑帧仍只有 0.4242。
    """
    m = machine(templates)
    m.adopt_checked = True
    action = m.next_action(load("shop_bottom_scrolled"))
    assert action is None
    assert m.shop_scrolls == 0
    assert m.completed_cycles == 1
    assert "3/3" in m.finish_reason


def test_two_rounds_each_count_once(templates):
    """主循环每帧先 preview（还原）、再真正提交一次 ⇒ 一轮只 +1。

    状态机自身**不加永久收工锁**：加了会让 ``--max-cycles 2`` 的第二轮
    等不到轮次递增、干等到状态超时（2026-11-15 实跑复现）。
    """
    m = machine(templates)
    m.adopt_checked = True
    m.shop_scrolls = 1
    for expected in (1, 2):
        action, _ = m.preview(load("shop_bottom"))
        assert action is None
        assert m.completed_cycles == expected - 1
        assert m.next_action(load("shop_bottom")) is None
        assert m.completed_cycles == expected


def test_preview_does_not_advance_progress(templates):
    m = machine(templates)
    for _ in range(3):
        action, _state = m.preview(load("house"))
        assert action.name == "open-adopt"
        assert m.adopt_checked is False
        assert m.completed_cycles == 0


# ── 安全边界 ────────────────────────────────────────────────────────────────


def test_unknown_adopt_popup_stops_without_any_click(templates):
    """认不出免费 / 付费两态：安全停止，绝不点任何领养按钮。

    把券图标涂黑，模拟明天免费额度刷新后（免费标记尚未登记）的画面。
    """
    frame = load("adopt_popup_paid").copy()
    frame[935:1003, 565:627] = 0
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen, match="免费领养判据尚未登记"):
        m.next_action(frame)
    assert m.adopt_checked is False


def test_black_frame_does_not_produce_a_click(templates):
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen):
        m.next_action(np.zeros((1132, 1982, 3), dtype=np.uint8))


def test_paid_state_never_clicks_a_ticket_button(templates):
    """付费态只允许点「点击关闭」；免费领养按钮坐标不在动作里。"""
    m = machine(templates)
    action = m.next_action(load("adopt_popup_paid"))
    assert action.name == "close-adopt"
    assert action.point == (992, 1090)
    assert "不碰任何领养按钮" in action.reason


def test_buy_options_enabled_on_bright_rows_stops_safely(templates):
    """开启购入但出现亮态（今天未采到判据）：停下留证，不猜坐标。"""
    frame = load("shop_bottom").copy()
    # 抹掉三行冷却文字，模拟「有可购买行」。
    for top in (540, 760, 980):
        frame[top : top + 60, 730:1030] = 0
    m = machine(templates, buy_food=True, buy_toys=True)
    with pytest.raises(UnrecognizedScreen, match="亮态购买判据尚未登记"):
        m.next_action(frame)


def test_scroll_is_bounded(templates):
    """滑到底判据一直不出现时不许无限下滑。"""
    m = machine(templates)
    m.shop_scrolls = 3
    with pytest.raises(UnrecognizedScreen, match="仍未看到三件宠物用品"):
        m.next_action(load("shop_top"))


def test_every_action_declares_an_exit_contract(templates):
    """新增路线准入：换页动作带 target_pages，同页动作带 in_page_evidence。"""
    m = machine(templates)
    seen = []
    for name in ["house", "adopt_popup_paid", "house_after_adopt", "shop_top"]:
        action = m.next_action(load(name))
        assert action.source_page
        assert bool(action.target_pages) ^ bool(action.in_page_evidence)
        seen.append(action.name)
    assert seen == ["open-adopt", "close-adopt", "open-shop", "scroll-shop"]


# ── 开局接力 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fixture", "expected_entry"),
    [
        ("house", "pet_house"),
        ("house_after_adopt", "pet_house"),
        ("adopt_popup_paid", None),
        ("shop_bottom", None),
    ],
)
def test_resume_probe_uses_runtime_criteria(templates, fixture, expected_entry):
    m = machine(templates)
    point = detect_resume_point(m, load(fixture))
    assert point is not None
    assert point.entry == expected_entry


def test_resume_probe_rejects_unrelated_pages(templates):
    assert detect_resume_point(machine(templates), load("lobby")) is None
    assert detect_resume_point(machine(templates), load("quick_menu")) is None
