"""骑士团捐赠开局接力：认出人停在骑士团哪一页就就地接管。

覆盖四件事：

1. **判据** —— 骑士团主页 / 资源支援列表 / 每周任务三页命中；
   三个弹窗、活动界面兜底页、大厅都不命中。
2. **判据与运行期同源** —— 抹掉该页的专属锚点就认不出，证明不是巧合命中。
3. **接线** —— ModeSpec 挂上探针；导航层接受「已在骑士团主页」这个落点、一次点击都不发。
4. **不拨状态** —— 本状态机每帧重判页面，接力不该动它。

⚠️ 三个弹窗不接力有**三条不同**的理由（不可逆 / 判据不排他 / 没有正例），写在
`knights_donation._RESUMABLE_STATES` 上方。全库跨路线负例扫描单独放
`runtime_logs/_audit_knights_cross_route.py`：单测只留代表帧，免得每次跑测试都读
几百张大图跟实跑抢内存。
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.knights_donation import REGIONS
from auto_game_unified.games.epic7.knights_donation import (
    KNIGHTS_GUILD_HOME_PAGE,
    KnightsDonationStateMachine,
    detect_resume_point,
)
from auto_game_unified.games.epic7.modes import (
    _probe_knights_donation_resume,
    get_mode,
)
from auto_game_unified.games.epic7.navigation import (
    _RESUME_ENTRY_PAGES,
    Epic7Navigator,
    build_navigation_templates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEMPLATES = ROOT / "games" / "epic7" / "templates"
KNIGHTS_TEMPLATES = TEMPLATES / "knights_donation"

ALL_KNIGHTS_FIXTURES = (
    "guild_home_no_dot",
    "guild_home_with_dot",
    "request_popup",
    "request_popup_selected",
    "reward_popup",
    "support_confirm",
    "support_page",
    "support_page_scrolled",
    "support_page_two_buttons",
    "weekly_tasks_claimable",
    "weekly_tasks_claimed",
)


REFERENCE_WIDTH, REFERENCE_HEIGHT = 1982, 1132


def _screen(group: str, name: str) -> np.ndarray:
    """夹具读成 RGB，并裁到基准尺寸。

    - **RGB**：模板是 ``load_template`` 解出来的 RGB，色序必须一致。
    - **裁到基准**：``epic7_story/bonus_reward.png`` 是 3200×2000 的老夹具，
      宽高比 1.600 与基准 1.751 不符，原样丢给匹配层会抛
      「画面宽高比与模板基准不一致」。项目里复核夹具的探针脚本都是这么裁的
      （见 `.workbuddy/memory/topics/resume.md`）。
    """
    bgr = cv2.imread(str(FIXTURES / group / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None, f"夹具不存在：{group}/{name}.png"
    bgr = bgr[:REFERENCE_HEIGHT, :REFERENCE_WIDTH]
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _knights(name: str) -> np.ndarray:
    return _screen("epic7_knights_donation", name)


def _machine() -> KnightsDonationStateMachine:
    return KnightsDonationStateMachine(KNIGHTS_TEMPLATES)


# ---- 1. 判据 ----


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("guild_home_no_dot", "骑士团主页"),
        ("guild_home_with_dot", "骑士团主页"),
        ("support_page", "骑士团活动·资源支援"),
        ("support_page_scrolled", "骑士团活动·资源支援"),
        ("support_page_two_buttons", "骑士团活动·资源支援"),
        ("weekly_tasks_claimable", "骑士团活动·每周任务"),
        ("weekly_tasks_claimed", "骑士团活动·每周任务"),
    ),
)
def test_the_three_business_pages_are_resume_points(name: str, expected: str):
    """三页都能落脚 —— **有没有红点都一样**（红点已不是任何判据的一部分）。"""

    found = detect_resume_point(_machine(), _knights(name))

    assert found is not None, f"{name} 认不出是哪一页"
    assert found.page == expected


def test_only_the_guild_home_point_carries_a_navigation_entry():
    """业务链里的两页已经在导航终点之后，不该再让导航走一趟。

    骑士团主页不一样：它在导航链上（大厅 → 骑士团主页），带 ``entry`` 能省掉
    一次「进入骑士团」的点击。
    """

    home = detect_resume_point(_machine(), _knights("guild_home_no_dot"))

    assert home is not None
    assert home.entry == KNIGHTS_GUILD_HOME_PAGE

    for name in ("support_page", "weekly_tasks_claimable"):
        found = detect_resume_point(_machine(), _knights(name))

        assert found is not None
        assert found.entry is None, f"{name} 不该让导航再走一趟"


def test_the_resume_never_touches_the_machine_state():
    """本状态机每帧都从画面重判页面 —— 接力拨了状态下一帧就被覆盖，只会制造假象。"""

    for name in ALL_KNIGHTS_FIXTURES:
        found = detect_resume_point(_machine(), _knights(name))

        if found is not None:
            assert found.state is None, f"{name} 的落点不该带状态"


# ---- 2. 刻意不接力的页面 ----


def test_irreversible_confirmations_are_not_resume_points():
    """点下去就消耗材料 / 花掉当天唯一额度的页面不接力。

    接力到这一页 = **助手替你按下不可逆的确认**。竞技场的「买票弹窗压住的队伍页」
    就是这么用 ``no_ticket`` 显式排除的。
    """

    for name in ("support_confirm", "request_popup", "request_popup_selected"):
        found = detect_resume_point(_machine(), _knights(name))

        assert found is None, f"{name} 是不可逆确认页，不该当接力落点"


def test_the_reward_popup_is_refused_because_its_evidence_is_not_exclusive():
    """「获得奖励」弹窗可逆，但判据 ``reward_title`` **不排他**。

    2026-09-24 全库 226 张扫描实测：别条路线的同类弹窗也能让这个判据成立。
    所以这里把那些**真实骗过它的帧**一起钉进来 —— 就算画面被判成奖励弹窗，
    接力也必须拒绝，否则会按骑士团弹窗的坐标点到别人的弹窗上。
    """

    for group, name in (
        ("epic7_knights_donation", "reward_popup"),
        ("epic7_hero", "reward_popup"),
        ("epic7_story", "bonus_reward"),
    ):
        found = detect_resume_point(_machine(), _screen(group, name))

        assert found is None, f"{group}/{name} 不该当接力落点"


def test_no_fixture_resumes_into_the_activity_panel_fallback():
    """活动界面兜底页（``activity_panel``）没有正例 —— 判据没在真帧上验证过就不接。

    自家的 11 张夹具没有一张判成它（都能被更具体的页认出来），全库扫描里也没有
    跨路线误命中。停在那一页只是多走一趟大厅，不会出错。
    """

    for name in ALL_KNIGHTS_FIXTURES:
        found = detect_resume_point(_machine(), _knights(name))

        if found is not None:
            assert found.page != "骑士团活动（页签未识别）", name


def test_the_lobby_is_not_a_resume_point():
    """停在大厅上照旧走「回大厅 → 进骑士团」—— 与接力挂上之前完全一致。"""

    assert detect_resume_point(_machine(), _screen("epic7_navigation", "lobby")) is None


# ---- 3. 判据与运行期同源 ----


def test_the_judgement_is_the_same_anchors_the_runtime_uses():
    """抹掉该页的专属锚点就认不出 —— 证明接力点不是巧合命中。

    夹具都是基准尺寸（1982×1132），所以 ``REGIONS`` 的坐标可以直接用、不需要换算。
    """

    for name, atom in (
        ("guild_home_no_dot", "activity_entry"),
        ("support_page", "request_support_button"),
        ("weekly_tasks_claimable", "points_label"),
    ):
        screen = _knights(name)
        assert detect_resume_point(_machine(), screen) is not None, name

        x, y, width, height = REGIONS[atom]
        broken = screen.copy()
        broken[y : y + height, x : x + width] = 0

        assert detect_resume_point(_machine(), broken) is None, (
            f"抹掉 {atom} 后仍被判成接力点，说明判据不是这个锚点决定的"
        )


# ---- 4. 接线 ----


def test_knights_donation_exposes_a_resume_probe():
    """从「一律回大厅」改成「先看停在骑士团哪一页」。"""

    assert get_mode("knights_donation").resume_probe is _probe_knights_donation_resume


def test_the_probe_reports_the_point_in_the_modes_shape():
    point = _probe_knights_donation_resume(
        _machine(),
        _knights("support_page"),
        None,
    )

    assert point is not None
    assert point.page == "骑士团活动·资源支援"
    assert point.state is None
    assert point.entry is None


def test_the_probe_misses_on_a_foreign_page():
    assert (
        _probe_knights_donation_resume(
            _machine(),
            _screen("epic7_navigation", "lobby"),
            None,
        )
        is None
    )


def test_navigation_accepts_the_guild_home_entry_without_clicking_anything():
    """已经在骑士团主页上：一次点击都不该有，尤其不能发 Back。"""

    clicks: list[tuple[int, int]] = []
    navigator = Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: _knights("guild_home_no_dot"), clicks.append),
        sleep=lambda _seconds: None,
        transition_frames=8,
    )

    navigator.navigate(
        "knights_donation",
        lobby_screen=_knights("guild_home_no_dot"),
        already_at=KNIGHTS_GUILD_HOME_PAGE,
    )

    assert clicks == []


def test_other_modes_reject_the_guild_home_page():
    """``already_at`` 是**按模式**校验的，不做静默降级。

    ⚠️ ``world_boss`` 不在名单独测里 —— 它**也**从骑士团主页进，两边登记的是同一个
    入口页（见下一条用例）。
    """

    navigator = Epic7Navigator(
        build_navigation_templates(TEMPLATES),
        Runtime(lambda: _knights("guild_home_no_dot"), lambda _point: None),
        sleep=lambda _seconds: None,
        transition_frames=8,
    )

    for mode in ("arena", "story", "expedition", "shop_refresh"):
        with pytest.raises(ValueError):
            navigator.navigate(
                mode,
                lobby_screen=_knights("guild_home_no_dot"),
                already_at=KNIGHTS_GUILD_HOME_PAGE,
            )


def test_world_boss_shares_the_guild_home_entry():
    """世界首领战也从骑士团主页进 —— 它登记过同一个入口页，两次接力语义一致。"""

    assert KNIGHTS_GUILD_HOME_PAGE in _RESUME_ENTRY_PAGES["world_boss"]
    assert KNIGHTS_GUILD_HOME_PAGE in _RESUME_ENTRY_PAGES["knights_donation"]
