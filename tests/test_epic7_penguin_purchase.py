# -*- coding: utf-8 -*-
"""企鹅批量购买：页面判据、动作顺序与购买安全护栏（2026-11-15 模拟器真机帧）。

## 这组测试守什么

1. 一轮 = 购入 50 只（不是 1 只），默认 10 轮 = 500 只；轮数可调。
2. 数量不是 50/50 先点「最多」补齐；第二轮起数量沿用 50/50，不再补点。
3. 每轮「购买」只发一次，完成弹窗「关闭」只点一次，点被吞掉也不重发扣费动作。
4. 报价与数量必须配对：1/50 认 102，50/50 认 5,100，任一不符即安全停止。
5. 同名不同义的对象不能串页：宠物商店的绿色「购买」、精灵之森里的「企鹅巢穴」行、
   成长祭坛里 170 / 850 / 4,250 的其它商品按钮。
6. 认不出的页面立即安全停止并留诊断，不猜坐标、不等超时。
"""

from pathlib import Path

import numpy as np
import pytest

from auto_game_unified.core.matcher import find_template
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.common import validate_profile
from auto_game_unified.games.epic7.evidence.penguin_purchase import (
    build_penguin_purchase_evidence,
)
from auto_game_unified.games.epic7.penguin_purchase import (
    DEFAULT_CYCLES,
    PENGUINS_PER_CYCLE,
    Observation,
    PenguinPage,
    PenguinPurchaseRunner,
    PenguinPurchaseStateMachine,
    SANCTUARY_HOME_PAGE,
    build_penguin_purchase_templates,
    detect_resume_point,
)
from auto_game_unified.games.epic7.unknown_screen import UnrecognizedScreen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_penguin_purchase"
TEMPLATES = ROOT / "games" / "epic7" / "templates"


def load(name: str) -> np.ndarray:
    """读一张整屏夹具；走 imdecode 绕开 conftest 的图像缓存。"""
    import cv2

    data = (FIXTURES / f"{name}.png").read_bytes()
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)[:1132, :1982]


@pytest.fixture(scope="module")
def templates():
    return build_penguin_purchase_templates(TEMPLATES)


def machine(templates, cycles: int = 1) -> PenguinPurchaseStateMachine:
    return PenguinPurchaseStateMachine(templates, cycles=cycles)


def drive(m, fixtures):
    """按主循环口径回放：每帧先试算（进度还原），再真正提交一次。"""
    actions = []
    for name in fixtures:
        frame = load(name)
        m.preview(frame)
        actions.append(m.next_action(frame))
    return actions


def names(actions):
    return [action.name if action is not None else None for action in actions]


# ── 判据文件与页面识别 ──────────────────────────────────────────────────────


def test_every_required_template_is_a_real_file(templates):
    folder = TEMPLATES / "penguin_purchase"
    errors = validate_profile(build_penguin_purchase_evidence(folder), folder)
    assert errors == []
    for key in build_penguin_purchase_evidence(folder).atoms:
        assert getattr(templates, key) is not None


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("sanctuary_home", PenguinPage.HOME),
        ("forest_with_altar", PenguinPage.FOREST),
        ("altar_popup", PenguinPage.ALTAR),
        ("negative_other_prices", PenguinPage.ALTAR),
        ("quantity_initial", PenguinPage.QUANTITY),
        ("quantity_max", PenguinPage.QUANTITY),
        ("quantity_second_round", PenguinPage.QUANTITY),
        ("complete_popup", PenguinPage.COMPLETE),
    ],
)
def test_recognizes_its_own_pages(templates, fixture, expected):
    assert machine(templates).observe_page(load(fixture)) is expected


@pytest.mark.parametrize("fixture", ["lobby", "negative_pet_shop_purchase"])
def test_other_pages_are_not_mistaken_for_route_pages(templates, fixture):
    assert machine(templates).observe_page(load(fixture)) is None


def test_complete_popup_wins_over_the_altar_underneath(templates):
    """半透明遮罩下成长祭坛标题实测仍 0.86，完成弹窗必须排在前面。"""
    assert machine(templates).observe_page(load("complete_popup")) is PenguinPage.COMPLETE


def test_other_prices_are_not_a_buy_target(templates):
    """后三列 170 / 850 / 4,250 的绿色按钮不能变成点击落点。"""
    match = find_template(
        load("negative_other_prices"),
        templates.nest_buy_button,
        0.80,
        region=(100, 790, 1800, 130),
    )
    assert match is not None
    assert match.center[0] < 500, "购买落点必须落在第一列企鹅蛋"


# ── 数量与报价 ──────────────────────────────────────────────────────────────


def test_quantity_and_price_are_judged_as_a_pair(templates):
    m = machine(templates)
    assert m.observation(load("quantity_initial")) == Observation(
        PenguinPage.QUANTITY,
        quantity_is_max=False,
        max_button_visible=True,
        price_is_expected=True,
    )
    assert m.observation(load("quantity_max")) == Observation(
        PenguinPage.QUANTITY,
        quantity_is_max=True,
        max_button_visible=True,
        price_is_expected=True,
    )
    assert m.observation(load("quantity_second_round")) == Observation(
        PenguinPage.QUANTITY,
        quantity_is_max=True,
        max_button_visible=True,
        price_is_expected=True,
    )


# ── 整轮动作顺序 ────────────────────────────────────────────────────────────


ONE_ROUND = [
    "sanctuary_home",
    "forest_with_altar",
    "altar_popup",
    "quantity_initial",
    "quantity_max",
    "complete_popup",
    "altar_popup",
]


def test_one_round_buys_fifty_penguins(templates):
    m = machine(templates, cycles=1)
    actions = drive(m, ONE_ROUND)
    assert names(actions) == [
        "open-forest",
        "open-altar",
        "open-quantity",
        "set-max",
        "buy",
        "close-complete",
        None,
    ]
    assert m.completed_cycles == 1
    assert m.total_penguins == PENGUINS_PER_CYCLE == 50


def test_second_round_skips_max_and_buys_another_fifty(templates):
    m = machine(templates, cycles=2)
    second_round = ["quantity_max", "complete_popup", "altar_popup"]
    actions = drive(m, ONE_ROUND + second_round)
    assert names(actions) == [
        "open-forest",
        "open-altar",
        "open-quantity",
        "set-max",
        "buy",
        "close-complete",
        "open-quantity",
        "buy",
        "close-complete",
        None,
    ]
    assert m.completed_cycles == 2
    assert m.total_penguins == 100


def test_default_is_ten_rounds_of_fifty_each():
    assert DEFAULT_CYCLES == 10
    assert DEFAULT_CYCLES * PENGUINS_PER_CYCLE == 500


def test_buy_is_never_repeated_when_the_transition_is_not_seen(templates):
    m = machine(templates)
    assert names(drive(m, ["quantity_max", "quantity_max"])) == ["buy", None]


def test_close_is_never_repeated(templates):
    m = machine(templates)
    assert names(
        drive(m, ["quantity_max", "complete_popup", "complete_popup"])
    ) == ["buy", "close-complete", None]


def test_unknown_page_stops_bounded_without_any_click(templates):
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen):
        m.next_action(load("lobby"))


def test_pet_shop_purchase_button_never_produces_an_action(templates):
    m = machine(templates)
    with pytest.raises(UnrecognizedScreen):
        m.next_action(load("negative_pet_shop_purchase"))


def test_every_action_declares_its_transition_contract(templates):
    m = machine(templates, cycles=2)
    for action in drive(m, ONE_ROUND):
        if action is None:
            continue
        assert action.source_page
        assert action.target_pages or action.in_page_evidence
        assert 0 <= action.point[0] < 1982 and 0 <= action.point[1] < 1132


def test_runner_requires_the_transition_contract():
    assert PenguinPurchaseRunner._REQUIRE_TRANSITION_CONTRACT is True


# ── 开局接力 ────────────────────────────────────────────────────────────────


def test_resume_only_on_pages_that_cannot_spend_red_leaves(templates):
    m = machine(templates)
    point = detect_resume_point(m, load("sanctuary_home"))
    assert point is not None and point.entry == SANCTUARY_HOME_PAGE
    assert detect_resume_point(m, load("forest_with_altar")) is not None
    assert detect_resume_point(m, load("altar_popup")) is not None
    # 数量弹窗与完成弹窗都紧邻扣费，不接力；让人从大厅重新导航更安全。
    assert detect_resume_point(m, load("quantity_max")) is None
    assert detect_resume_point(m, load("complete_popup")) is None


# ── 轮数上限（2026-11-15 20 轮实跑事故）────────────────────────────────────


def test_runner_uses_the_requested_cycle_limit(templates):
    """界面填 20 轮时，状态机的上限必须跟着变。

    事故：状态机按默认 10 轮返回「收工」，主循环仍在等 20 轮，
    画面停在成长祭坛干等 45 秒后报状态超时。
    """
    m = machine(templates, cycles=DEFAULT_CYCLES)
    runtime = Runtime(
        lambda: load("altar_popup"),
        lambda *args: None,
        dry_run=True,
        emit=lambda line: None,
    )
    runner = PenguinPurchaseRunner(m, runtime)
    runner.run(max_cycles=20)
    assert m.cycles == 20


def test_machine_keeps_buying_past_the_default_ten_rounds(templates):
    """上限设为 20 后，跑满 10 轮不应提前收工，第 11 轮仍要继续购入。"""
    m = machine(templates, cycles=20)
    frames = ["sanctuary_home", "forest_with_altar"]
    frames += ["altar_popup", "quantity_max", "complete_popup"] * 10
    frames += ["altar_popup"]
    actions = drive(m, frames)
    assert names(actions)[-1] == "open-quantity"
    assert m.completed_cycles == 10
    assert m.total_penguins == 500
