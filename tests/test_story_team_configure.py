"""队伍页补人（2026-11-22）：判据链条与停止条件的回归测试。

口径来自用户实跑：
  * 空位 = **闪烁的黄色光圈**，满员后全部变蓝圈 ⇒ 黄圈占比是「还要不要补人」的唯一依据；
  * 补人顺序 = 点左下「管理队伍」→ 点列表顶端加号 → 点空位上的紫加号；
  * 每放上一个人，必须把英雄列表下移一格，否则同一个加号只会回「已配置的英雄」；
  * 黄圈全部消失（占比低于阈值）就停手，改成点「进行任务」。
"""

from pathlib import Path

import numpy as np
import pytest

from auto_game_unified.games.epic7.evidence.story import (
    TEAM_RING_MIN_RATIO,
    TEAM_RING_REGION,
)
from auto_game_unified.games.epic7.story import (
    StoryState,
    StoryStateMachine,
    build_story_templates,
)

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "games" / "epic7" / "templates" / "story"
REFERENCE = (1982, 1132)


@pytest.fixture(scope="module")
def machine() -> StoryStateMachine:
    templates = build_story_templates(TEMPLATE_DIR)
    state = StoryStateMachine(templates, StoryState.TEAM)
    return state


def blank_frame() -> np.ndarray:
    return np.zeros((REFERENCE[1], REFERENCE[0], 3), dtype=np.uint8)


def paint_yellow_rings(frame: np.ndarray, blobs: int = 2) -> None:
    """在阵型区画高亮黄块，模拟「还有空位的黄圈」。"""
    x, y, _, _ = TEAM_RING_REGION
    for index in range(blobs):
        left = x + 40 + index * 90
        top = y + 60 + index * 40
        frame[top : top + 70, left : left + 90] = (255, 220, 20)


def paste(frame: np.ndarray, template: np.ndarray, left: int, top: int) -> None:
    height, width = template.shape[:2]
    frame[top : top + height, left : left + width] = template


def frame_with(
    *,
    ring: bool,
    slot: bool,
    plus: bool,
    manage: bool,
    start: bool = False,
    list_shift: int = 0,
) -> np.ndarray:
    frame = blank_frame()
    if ring:
        paint_yellow_rings(frame)
    templates = build_story_templates(TEMPLATE_DIR)
    if list_shift:
        # 模拟英雄列表被滑动过：行位置整体位移，指纹随之改变。
        # ⚠️ 必须先画列表再贴加号，否则会把加号模板一起擦掉。
        x, y, width, height = (1420, 220, 430, 560)
        frame[y : y + height, x : x + width] = 0
        for row in range(4):
            top = y + 40 + row * 120 + list_shift * 25
            frame[top : top + 80, x + 20 : x + width - 20] = 80 + row * 30
    if slot:
        paste(frame, templates.team_slot_plus, 600, 400)
    if plus:
        paste(frame, templates.team_list_plus, 1400, 400)
    if manage:
        paste(frame, templates.team_manage, 40, 1000)
    if start:
        paste(frame, templates.start_mission, 1500, 980)
    return frame


def test_yellow_ring_ratio_separates_empty_from_full(machine: StoryStateMachine) -> None:
    empty = frame_with(ring=True, slot=False, plus=False, manage=False)
    full = frame_with(ring=False, slot=False, plus=False, manage=False)
    assert machine._team_ring_ratio(empty) >= TEAM_RING_MIN_RATIO
    assert machine._team_ring_ratio(full) < TEAM_RING_MIN_RATIO


def test_full_team_goes_straight_to_start_mission(machine: StoryStateMachine) -> None:
    """黄圈全消失（满员）：一个配队动作都不发，原样点「进行任务」，并留下放行依据。"""
    machine._team_placements = 0
    machine._team_asked = 0
    machine._team_empty_asks = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    frame = frame_with(ring=False, slot=False, plus=True, manage=True)
    assert machine._configure_team(frame) is None
    assert "进场时阵型区没有黄圈" in machine._team_release_reason


def test_empty_slot_places_topmost_purple_plus(machine: StoryStateMachine) -> None:
    """紫加号在：点最上面那一颗（用户口径：从上到下依次放人）。"""
    machine._team_placements = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=True, plus=True, manage=True)
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_slot_plus"
    assert action.point == (600 + 69 // 2, 400 + 71 // 2)


def test_without_purple_plus_opens_the_list_first(machine: StoryStateMachine) -> None:
    """紫加号不在、列表顶端加号在：先点加号，不要直接点空位。"""
    machine._team_placements = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_list_plus"


def test_after_placing_one_the_list_must_scroll(machine: StoryStateMachine) -> None:
    """刚放完一个人 + 紫加号已消失：必须先把列表下移一格换英雄。"""
    machine._team_placements = 0
    machine._team_last_action = "team_slot_plus"
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_scroll"
    assert machine._team_placements == 1


def test_manage_team_is_the_last_resort(machine: StoryStateMachine) -> None:
    """列表还没展开（只有管理队伍）：先点它进编队。"""
    machine._team_placements = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=False, plus=False, manage=True)
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_manage"


def test_purple_plus_wins_over_low_yellow_ratio(machine: StoryStateMachine) -> None:
    """紫加号在就必须放人，哪怕黄圈占比算出来低于阈值（闪烁会让占比忽高忽低）。"""
    machine._team_placements = 0
    machine._team_asked = 3
    machine._team_empty_asks = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    # 只画很少的黄（低于阈值），但紫加号在
    frame = frame_with(ring=False, slot=True, plus=True, manage=True)
    assert machine._team_ring_ratio(frame) < TEAM_RING_MIN_RATIO
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_slot_plus"


def test_empty_ask_scrolls_to_the_next_hero_instead_of_repeating(
    machine: StoryStateMachine,
) -> None:
    """问了没紫加号：换下一个英雄，不许对同一颗加号连点。"""
    machine._team_placements = 0
    machine._team_asked = 1
    machine._team_empty_asks = 0
    machine._team_last_action = "team_list_plus"
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    action = machine._configure_team(frame)
    assert action is not None
    assert action.name == "team_scroll"
    assert machine._team_empty_asks == 1


def test_two_empty_asks_release_the_team_with_a_reason(
    machine: StoryStateMachine,
) -> None:
    """换过英雄后再问仍没有紫加号 ⇒ 这才是满员证据，放行并写下依据。"""
    machine._team_placements = 0
    machine._team_asked = 2
    machine._team_empty_asks = 1
    machine._team_last_action = "team_list_plus"
    machine._team_same_count = 0
    machine._team_list_fp = None
    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    assert machine._configure_team(frame) is None
    assert "换过英雄后" in machine._team_release_reason


def test_same_manage_action_three_times_in_a_row_stops(
    machine: StoryStateMachine,
) -> None:
    """「管理队伍」连续第 3 次仍被要求发出 ⇒ 点了进不去编队，停手。"""
    machine._team_placements = 0
    machine._team_asked = 0
    machine._team_empty_asks = 0
    machine._team_last_action = "team_manage"
    machine._team_same_count = 2
    frame = frame_with(ring=True, slot=False, plus=False, manage=True)
    assert machine._configure_team(frame) is None


def test_preview_never_leaks_team_counters(machine: StoryStateMachine) -> None:
    """预览那一遍的配队副作用必须原样回滚。

    2026-11-22 10:00 实跑：`preview()` 先跑一遍 `next_action()`，快照没盖住配队计数
    ⇒ 「第 3 次点顶端加号」下一帧变「第 6 次」，且 `_team_last_action` 被清空，
    导致永远走「点顶端加号」分支、再也不滚动换英雄，对着列表顶端连点到 4 次未转场。
    """
    machine._team_placements = 0
    machine._team_asked = 0
    machine._team_empty_asks = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    frame = frame_with(ring=True, slot=False, plus=True, manage=True, start=True)

    action, _outcome = machine.preview(frame)

    assert action is not None and action.name == "team_list_plus"
    assert machine._team_asked == 0
    assert machine._team_empty_asks == 0
    assert machine._team_last_action == ""
    assert machine._team_release_reason == ""


def test_real_frame_places_then_scrolls_then_releases(machine: StoryStateMachine) -> None:
    """真实帧重放完整一轮：加号 → 紫加号 → 换人（指纹确认动过）→ 再问 → 放行。"""
    machine._team_placements = 0
    machine._team_asked = 0
    machine._team_empty_asks = 0
    machine._team_last_action = ""
    machine._team_same_count = 0
    machine._team_list_fp = None

    first = frame_with(ring=True, slot=False, plus=True, manage=True)
    assert machine._configure_team(first).name == "team_list_plus"

    machine._team_last_action = "team_list_plus"
    second = frame_with(ring=True, slot=True, plus=True, manage=True)
    assert machine._configure_team(second).name == "team_slot_plus"

    machine._team_last_action = "team_slot_plus"
    third = frame_with(ring=True, slot=False, plus=True, manage=True)
    assert machine._configure_team(third).name == "team_scroll"
    assert machine._team_placements == 1
    assert machine._team_list_fp is not None

    # 滑动生效：列表整体位移，指纹变化 ⇒ 允许继续问
    machine._team_last_action = "team_scroll"
    moved = frame_with(ring=True, slot=False, plus=True, manage=True, list_shift=1)
    assert machine._configure_team(moved).name == "team_list_plus"
    assert machine._team_list_fp is None

    machine._team_last_action = "team_list_plus"
    assert machine._configure_team(moved).name == "team_scroll"
    assert machine._team_empty_asks == 1

    machine._team_last_action = "team_scroll"
    moved_again = frame_with(
        ring=True, slot=False, plus=True, manage=True, list_shift=2
    )
    assert machine._configure_team(moved_again).name == "team_list_plus"

    machine._team_last_action = "team_list_plus"
    assert machine._configure_team(moved_again) is None
    assert "换过英雄后" in machine._team_release_reason


def test_scroll_that_moves_nothing_stops_instead_of_spinning(
    machine: StoryStateMachine,
) -> None:
    """滑动之后列表指纹没变（滚到底/滑空）：立刻收手，不许对着顶端加号反复点。"""
    machine._team_placements = 0
    machine._team_asked = 1
    machine._team_empty_asks = 0
    machine._team_last_action = "team_slot_plus"
    machine._team_same_count = 0
    machine._team_list_fp = None

    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    assert machine._configure_team(frame).name == "team_scroll"

    # 同一张画面回来 = 列表一个像素都没动
    machine._team_last_action = "team_scroll"
    assert machine._configure_team(frame) is None
    assert "指纹未变化" in machine._team_release_reason


def test_reaching_list_bottom_with_rings_left_refuses_to_start(
    machine: StoryStateMachine,
) -> None:
    """列表到底却仍有黄圈 ⇒ 配不满，不给「进行任务」放行。"""
    machine._team_placements = 1
    machine._team_asked = 2
    machine._team_empty_asks = 0
    machine._team_last_action = "team_slot_plus"
    machine._team_same_count = 0
    machine._team_list_fp = None

    frame = frame_with(ring=True, slot=False, plus=True, manage=True)
    assert machine._configure_team(frame).name == "team_scroll"

    machine._team_last_action = "team_scroll"
    assert machine._configure_team(frame) is None
    assert "拒绝开打" in machine._team_release_reason


def test_rings_gone_after_placing_releases_without_asking_again(
    machine: StoryStateMachine,
) -> None:
    """补完第 3 个人黄圈已全蓝：立刻放行，不许再点第 4 次加号。

    2026-11-22 10:15 实跑：占比已经掉到 0.17%（全蓝），却因为「已经问过 3 次加号」
    这个多余条件不放行，继续点第 4 次、第 5 次。黄圈归零是满员终态，必须无条件生效。
    """
    machine._team_placements = 3
    machine._team_asked = 3
    machine._team_empty_asks = 0
    machine._team_last_action = "team_scroll"
    machine._team_same_count = 0
    machine._team_list_fp = None

    frame = frame_with(ring=False, slot=False, plus=True, manage=True)
    assert machine._configure_team(frame) is None
    assert "补完 3 人后黄圈已全部消失" in machine._team_release_reason
    # 放行后计数清零（给下一关重新从零问起），不是"又点了一次加号"
    assert machine._team_asked == 0


def test_pc_rules_never_place_heroes(machine: StoryStateMachine) -> None:
    """PC 队伍页布局未验证：PC 规则下整段配队不启用。"""
    pc_machine = StoryStateMachine(
        build_story_templates(TEMPLATE_DIR), StoryState.TEAM, pc_rules=True
    )
    frame = frame_with(ring=True, slot=True, plus=True, manage=True)
    assert pc_machine._configure_team(frame) is None
