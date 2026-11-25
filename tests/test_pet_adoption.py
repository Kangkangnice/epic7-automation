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
        # 2026-11-16 额度刷新后采到的亮态与购买确认框。
        ("shop_bottom_bright", PetAdoptionState.SHOP),
        ("purchase_modal", PetAdoptionState.PURCHASE),
        # 2026-11-23 弹窗改版：标题/问句上移、绿色按钮下移 120px。
        ("purchase_modal_v2", PetAdoptionState.PURCHASE),
        ("adopt_popup_free", PetAdoptionState.ADOPT_POPUP),
        ("adopt_result", PetAdoptionState.ADOPT_RESULT),
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
    """三条证据互相矛盾（只抹掉券图标）：安全停止，绝不点任何领养按钮。"""
    frame = load("adopt_popup_paid").copy()
    frame[935:1003, 565:627] = 0
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen, match="三条证据对不上"):
        m.next_action(frame)
    assert m.adopt_checked is False


def test_mixed_free_evidence_stops_instead_of_guessing(templates):
    """只认出「免费」但提示条没了 ⇒ 证据不齐，安全停止（不点免费也不点关闭）。

    这条守的是"宁可少领一次，也不在两种解释之间猜"：免费窗口一天只有一次，
    猜错就是花券或者白丢。
    """
    frame = load("adopt_popup_free").copy()
    frame[868:920, 700:866] = 0
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen, match="三条证据对不上"):
        m.next_action(frame)


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
    assert "只点底部「点击关闭」" in action.reason


def test_free_state_adopts_without_spending_anything(templates):
    """免费态（券图标也在）：点的是「免费」二字，目标是领养结果，不花券。"""
    m = machine(templates)
    action = m.next_action(load("adopt_popup_free"))
    assert action.name == "adopt-free"
    assert action.target_pages == ("领养结果",)
    assert action.point == (640, 965)
    assert m.adopt_checked is True


def test_result_popup_only_closes_never_adopts_again(templates):
    """结果弹窗只点「点击关闭」；右下「再领养一次」要花券，坐标不在动作里。"""
    m = machine(templates)
    action = m.next_action(load("adopt_result"))
    assert action.name == "dismiss-result"
    # 关掉结果弹窗露出的是下面的领养弹窗（2026-11-16 实跑实测），不是小屋。
    assert action.target_pages == ("领养宠物",)
    assert action.point == (992, 1090)
    assert "再领养一次" in action.reason


def test_bright_row_opens_the_purchase_dialog(templates):
    """亮态 + 开饲料购入 ⇒ 先开确认框；落点由商品名派生，且在画布内。"""
    m = machine(templates, buy_food=True)
    action = m.next_action(load("shop_bottom_bright"))
    assert action.name == "open-purchase"
    assert action.target_pages == ("购买确认",)
    assert 0 <= action.point[0] < 1982 and 0 <= action.point[1] < 1132
    assert "一般饲料" in action.reason
    assert m.pending_buy is not None and m.pending_buy[0] == "food"


def test_purchase_dialog_confirms_on_the_green_button(templates):
    """确认框里点绿「购买」，点完记下这一轮已经买过饲料、清掉待确认标记。"""
    m = machine(templates, buy_food=True)
    m.pending_buy = ("food", 587)
    action = m.next_action(load("purchase_modal"))
    assert action.name == "confirm-purchase"
    assert action.target_pages == ("宠物商店",)
    # 落点必须在绿色「购买」二字里：2026-11-17 真机诊断帧实测中心 (1227, 801)。
    # 旧断言按 y 900..980 写，是自造的坐标，真机按钮根本不在那儿。
    assert 1180 <= action.point[0] <= 1300 and 760 <= action.point[1] <= 850, action.point
    assert m.bought_rows == [("food", 587)]
    assert m.pending_buy is None


def test_redesigned_purchase_dialog_confirms_on_the_moved_button(templates):
    """2026-11-23 弹窗改版：标题/问句上移、绿色「购买」从 y=801 下移到 y=921。

    那一帧上旧模板只有 0.7897 / 0.6048（阈 0.80），按钮又在旧搜索带
    y 740~840 之外 ⇒ 弹窗明明开了却判 UNKNOWN，卡到超时退出码 1。
    候选模板接住判页之后，点击落点也必须跟着按钮走，不能沿用旧坐标。
    """
    m = machine(templates, buy_food=True)
    m.pending_buy = ("food", 587)
    action = m.next_action(load("purchase_modal_v2"))
    assert action.name == "confirm-purchase"
    assert action.target_pages == ("宠物商店",)
    assert 1180 <= action.point[0] <= 1300 and 890 <= action.point[1] <= 950, action.point


def test_other_routes_purchase_dialog_is_not_a_pet_purchase(templates):
    """企鹅数量弹窗与新版宠物购买弹窗是同款皮肤，不能串到这条路线来。

    那一帧上 v2 标题/问句和绿「购买」都是 1.0000 —— 唯一能证伪的是底页
    「宠物商店」标题：宠物弹窗 0.9998、企鹅 0.4741（阈 0.80）。
    判据若把这个排他锚点摘掉，本路线就会在别人的弹窗上点绿色「购买」。
    """
    import cv2

    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "epic7_penguin_purchase"
        / "quantity_initial.png"
    )
    data = path.read_bytes()
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)[:1132, :1982]
    assert machine(templates).observe_page(frame) is None


def test_purchase_dialog_without_a_pending_buy_stops(templates):
    """不是本路线发起的确认框：两颗按钮都不许点。"""
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen, match="并没有发起购买"):
        m.next_action(load("purchase_modal"))


def test_grey_rows_never_buy_even_with_options_on(templates):
    """三行全灰（0/3、0/1、0/1）⇒ 开了购入也不买，正常收工。"""
    m = machine(templates, buy_food=True, buy_toys=True)
    assert m.next_action(load("shop_bottom")) is None
    assert m.completed_cycles == 1


def test_weekly_cooldown_rows_never_buy(templates):
    """周额度用尽的「3天后可购买」帧同样三行全灰，开了购入也不点灰按钮。

    2026-11-19 实跑报错根因：旧模板只认「N小时后可购买」，周用尽变体「N天后」
    漏检 ⇒ 三行被误判亮态 ⇒ 对着灰按钮连点 4 次不推进。模板改裁两态共有的
    「后可购买」后，本帧三行必须全部识别为冷却并正常收工。
    """
    m = machine(templates, buy_food=True, buy_toys=True)
    assert m.next_action(load("shop_bottom_weekly_cooldown")) is None
    assert m.completed_cycles == 1
    assert m.pending_buy is None


def test_switches_off_means_no_click_on_bright_rows(templates):
    """亮态但两个开关都关着 ⇒ 一个点击都不发。"""
    m = machine(templates)
    assert m.next_action(load("shop_bottom_bright")) is None
    assert m.pending_buy is None


def test_same_row_is_never_bought_twice_in_one_cycle(templates):
    """同一行一轮只买一次：饲料买完仍是 2/3 亮态，不许在同一行回购。"""
    m = machine(templates, buy_food=True)
    m.bought_rows.append(("food", 587))
    assert m.next_action(load("shop_bottom_bright")) is None


def test_both_toy_rows_get_their_own_purchase(templates):
    """两行宠物玩具是两种商品：买掉第一行之后，第二行照样要买。"""
    m = machine(templates, buy_toys=True)
    m.bought_rows.append(("toys", 805))
    action = m.next_action(load("shop_bottom_bright"))
    assert action.name == "open-purchase"
    # 第二行玩具的按钮在画面更下方（名字 1023 + 40）。
    assert abs(action.point[1] - 1063) <= 8, action.point


def test_toys_buy_the_topmost_bright_row(templates):
    """玩具有两行：一轮只买最上面那行，点的是它自己的购买按钮（名字 +531/+40）。"""
    m = machine(templates, buy_toys=True)
    action = m.next_action(load("shop_bottom_bright"))
    assert action.name == "open-purchase"
    assert m.pending_buy == ("toys", 805)
    assert abs(action.point[0] - 1651) <= 6 and abs(action.point[1] - 845) <= 6, action.point


def test_row_still_looks_buyable_after_one_purchase(templates):
    """买过一次的饲料行仍是亮态（2/3）—— 挡住回购的是按行记账，不是冷却文字。

    这张帧（2026-11-16 08:00 真机，确认购买后 1 秒）就是证据：次数从 3/3 变 2/3，
    行还是绿的、还是可点的。所以「一轮只买一次」必须落在账本上。
    """
    m = machine(templates, buy_food=True)
    assert m.observe_page(load("purchase_done")) is PetAdoptionState.SHOP
    assert m.next_action(load("purchase_done")).name == "open-purchase"


def test_preview_does_not_mark_the_row_as_bought(templates):
    """试算两帧稳定确认不许把「已购买」提前记上，否则真跑就不买了。"""
    m = machine(templates, buy_food=True)
    m.preview(load("shop_bottom_bright"))
    assert m.pending_buy is None and m.bought_rows == []
    assert m.next_action(load("shop_bottom_bright")).name == "open-purchase"


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
