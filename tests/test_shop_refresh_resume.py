"""刷书签开局接力：认出「人已经停在秘密商店页」就就地接管。

覆盖三件事：

1. **判据** —— 商店页（顶部 / 滚动中 / 底部）命中；大厅入口、刷新弹窗、购买弹窗，
   以及别条路线的页面都不命中。
2. **接线** —— ModeSpec 挂上探针；命中后给状态机打 ``resumed_at_shop()`` 记号，
   而且**不拨 phase**（这条路线的 phase 是内部阶段，起始恒为 SCAN_TOP）。
3. **失败关闭** —— 没有观察器就认不出来，退回「回大厅 → 重新导航」。

全库夹具的跨路线负例扫描单独放 `runtime_logs/_audit_shop_resume.py`（只读脚本）：
单测只留每种页面的代表帧，免得每次跑测试都读几百张大图跟实跑抢内存。

接力准备（列表回到顶部）在 `tests/test_shop_refresh_runner.py` 里测，那边有现成的
假 Runtime / 假观察器脚手架。
"""

from pathlib import Path

import cv2
import numpy as np

from auto_game_unified.games.epic7.evidence.shop_refresh import (
    build_shop_refresh_observer,
)
from auto_game_unified.games.epic7.modes import _probe_shop_refresh_resume, get_mode
from auto_game_unified.games.epic7.shop_refresh import (
    ShopPhase,
    ShopRefreshStateMachine,
    detect_resume_point,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures"


def _screen(group: str, name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / group / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _machine() -> ShopRefreshStateMachine:
    return ShopRefreshStateMachine(
        1,
        observer=build_shop_refresh_observer(TEMPLATES),
    )


def _probe(machine: ShopRefreshStateMachine, group: str, name: str):
    return detect_resume_point(machine, _screen(group, name))


def test_shop_page_is_a_resume_point():
    """人停在秘密商店页（顶部 / 滚动中 / 底部 / 某一行在售）都能接上。"""

    for name in (
        "shop_top_live",
        "shop_scroll_peak_live_20260914_a",
        "shop_scroll_bottom_live_20260914_c",
        "mystic_row_live_20260831",
    ):
        machine = _machine()
        found = _probe(machine, "epic7_shop_refresh", name)

        assert found is not None, f"{name} 认不出是秘密商店页"
        assert found.page == "秘密商店"
        assert found.state is None, "phase 是内部阶段，接力不能拨状态"
        assert found.entry is None, "已经在业务入口，不需要再走导航"
        assert machine.resumed_at_shop is False, "判据本身不该动状态机（打记号是探针的事）"


def test_lobby_entry_and_popups_are_not_resume_points():
    """大厅入口按钮、刷新弹窗、购买弹窗都不算接力点。

    弹窗故意不接力：`return_home` 的那一下 Back 会先关掉它，下一帧扫到商店页
    就地接管，没必要为弹窗单独建判据。
    """

    machine = _machine()

    for name in (
        "lobby_shop_entry",
        "lobby_shop_entry_low_score_20260831",
        "refresh_confirm_live",
        "purchase_confirm_other_live",
        "mystic_purchase_confirm_live_20260831",
    ):
        found = _probe(machine, "epic7_shop_refresh", name)

        assert found is None, f"{name} 不该被当成秘密商店页"


def test_other_routes_pages_are_not_shop_resume_points():
    """别条路线的页面不能被商店判据吃掉（跨路线负例的代表帧）。"""

    machine = _machine()
    others = (
        ("epic7_navigation", "lobby"),
        ("epic7_navigation", "lobby_fodder"),
        ("epic7_arena", "normal_battle_ready_live_20260826"),
        ("epic7_arena", "failed_first_opponent"),
        ("epic7_story", "team_live_20260809"),
        ("epic7_expedition", "home"),
        ("epic7_fodder", "replay"),
        ("epic7_hero", "list_reddot"),
        ("epic7_survivor", "result"),
        ("epic7_global", "network_reconnect"),
        ("epic7_pc_story", "battle_hud"),
    )

    for group, name in others:
        found = _probe(machine, group, name)

        assert found is None, f"{group}/{name} 被误判成秘密商店页"


def test_shop_page_judgement_is_the_same_three_anchors_as_navigation():
    """判据与导航器同源：三个锚点缺一个就不是商店页。"""

    machine = _machine()
    screen = _screen("epic7_shop_refresh", "shop_top_live")
    assert detect_resume_point(machine, screen) is not None

    for atom, box in (
        ("shop_title", (0, 52, 500, 130)),
        ("refresh_button_3", (0, 930, 650, 202)),
        ("buy_button", (1500, 140, 420, 992)),
    ):
        x, y, width, height = box
        broken = screen.copy()
        broken[y : y + height, x : x + width] = 0

        assert detect_resume_point(machine, broken) is None, (
            f"抹掉 {atom} 后仍被判成商店页，说明判据不是三锚点合取"
        )


def test_mode_probe_marks_the_machine_without_touching_the_phase():
    machine = _machine()

    point = _probe_shop_refresh_resume(
        machine,
        _screen("epic7_shop_refresh", "shop_top_live"),
        None,
    )

    assert point is not None
    assert point.page == "秘密商店"
    assert point.state is None
    assert point.entry is None
    assert machine.resumed_at_shop is True
    assert machine.phase is ShopPhase.SCAN_TOP


def test_mode_probe_misses_on_a_foreign_page():
    machine = _machine()

    point = _probe_shop_refresh_resume(
        machine,
        _screen("epic7_navigation", "lobby"),
        None,
    )

    assert point is None
    assert machine.resumed_at_shop is False


def test_shop_refresh_exposes_a_resume_probe():
    """刷书签从「一律回大厅」改成「先看是不是已经停在商店页」。"""

    assert get_mode("shop_refresh").resume_probe is _probe_shop_refresh_resume
    assert get_mode("survivor").resume_probe is None
    assert get_mode("fodder").resume_probe is None
    assert get_mode("hero_synthesis").resume_probe is None


def test_probe_without_an_observer_fails_closed():
    """没有观察器就认不出来 —— 失败关闭，退回「回大厅 → 重新导航」。"""

    machine = ShopRefreshStateMachine(1)

    assert machine.observer is None
    assert (
        detect_resume_point(machine, _screen("epic7_shop_refresh", "shop_top_live"))
        is None
    )
