"""幸存者循环的状态机与 Runner 测试。

用假 Runtime + 假观察器跑完整一轮闭环，重点守住三件事：
1. 一轮的动作顺序是「首卡 -> 局内滑动 ->（升级选卡）-> 结算 -> 重新进行」；
2. 结算页的「确认」和升级页的「重新抽取」永远不会被点到；
3. 认不出画面 / 局内超时都失败关闭，而不是盲目继续点。
"""

import itertools
import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.games.epic7.evidence.survivor import (
    CONFIRM_BUTTON_BOX,
    LEVEL_UP_CARDS,
    LEVEL_UP_REDRAW_BOX,
    RESULT_RESTART_BOX,
    WEAPON_CARD_BOX,
    SurvivorObservation,
    build_survivor_observer,
)
from auto_game_unified.games.epic7.survivor import (
    MOVE_DURATION_MS,
    MOVE_PATTERN,
    MOVE_REPEATS_RANGE,
    SurvivorRunner,
    SurvivorState,
    SurvivorStateMachine,
    card_center,
    movement_steps,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "games" / "epic7" / "templates"
FIXTURES = ROOT / "tests" / "fixtures" / "epic7_survivor"

# 假观察器返回的锚点：用真实实测到的按钮中心，好让越界检查有意义。
RESTART_ANCHOR = (789, 1021)
FIRST_CARD_ANCHOR = (945, 589)

WEAPON_CARD = SurvivorObservation("survivor.weapon_card", FIRST_CARD_ANCHOR)
BATTLE = SurvivorObservation("survivor.battle", None)
LEVEL_UP = SurvivorObservation("survivor.level_up", None)
RESULT = SurvivorObservation("survivor.result", RESTART_ANCHOR)
UNKNOWN = SurvivorObservation(None, None)

# 点这些地方等于把循环弄丢：结算页「确认」会回到活动主页，升级页「重新抽取」会烧掉抽取次数。
FORBIDDEN_BOXES = {
    "结算页「确认」": CONFIRM_BUTTON_BOX,
    "升级页「重新抽取」": LEVEL_UP_REDRAW_BOX,
}

CANVAS_HEIGHT = 1132
CANVAS_WIDTH = 1982


def _frame(value: int) -> np.ndarray:
    """纯流程用的占位画面：只有左上角像素携带页面对照表的键。

    故意做得很小——不选卡就不会去采样色相，不需要真实画布尺寸。
    """

    return np.full((120, 200, 3), value, dtype=np.uint8)


def _blue_frame(value: int) -> np.ndarray:
    """整幅蓝卡画面：色相采样要落在卡片标签栏上，所以必须铺满真实画布尺寸。

    RGB(0,0,255) 在 OpenCV 里色相是 120，落在 BLUE_CARD_HUE=(86,128) 内；
    左上角像素的 R 通道留作对照表的键，取值很小，不影响色相判定。
    """

    frame = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
    frame[:, :, 2] = 255
    frame[0, 0, 0] = value
    return frame


def _all_support_frame(value: int) -> np.ndarray:
    """整幅绿卡（辅助武器）画面：三张都不是蓝卡，即用户实测遇到的「三张全绿」。

    RGB(48,208,144) 色相 78，落在蓝卡带 (86,128) 之外；同 `_blue_frame`，左上角像素当键。
    """

    frame = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
    frame[:, :, 0] = 48
    frame[:, :, 1] = 208
    frame[:, :, 2] = 144
    frame[0, 0, 0] = value
    return frame


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Observer:
    def __init__(self, observations: dict[int, SurvivorObservation]) -> None:
        self.observations = observations

    def observe(self, screen: np.ndarray) -> SurvivorObservation:
        return self.observations[int(screen[0, 0, 0])]


class _Harness:
    """假 Runtime + 假观察器，记录每一次点击意图、真实点击和滑动。"""

    # 一次真实滑动占用的墙钟时间：adb 起进程约 225ms + 手势 700ms + 抓帧识别约 180ms。
    # **假时钟只在 `sleep` 时前进，而局内循环是靠真墙钟判超时的**；空等还是 0.25s 的时候
    # 靠它顺带推进，2026-09-16 把空等压到 0 之后就没东西推进了 —— 那局「永不结束」的测试
    # 直接变成死循环，一直往 `swipes` 里塞直到 MemoryError。所以滑动本身必须记账。
    SWIPE_WALL_SECONDS = 1.1

    def __init__(
        self,
        frames,
        observations: dict[int, SurvivorObservation] | None = None,
        *,
        observer=None,
        dry_run: bool = False,
        poll_seconds: float = 0.1,
    ) -> None:
        self.clock = _Clock()
        # actions 记「想点哪里」，backend_clicks 只记干跑之外真正出手的点击。
        self.actions: list[tuple[tuple[int, int], str]] = []
        self.backend_clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple[tuple[int, int], tuple[int, int], int]] = []
        self.logs: list[str] = []
        stream = iter(frames)

        def record_swipe(start, end, duration) -> None:
            self.swipes.append((start, end, duration))
            self.clock.value += self.SWIPE_WALL_SECONDS

        self.runtime = Runtime(
            lambda: next(stream),
            self.backend_clicks.append,
            swipe=record_swipe,
            dry_run=dry_run,
            emit=self.logs.append,
            monotonic=self.clock.now,
        )
        original_click = self.runtime.click

        def named_click(point: tuple[int, int], action: str) -> None:
            self.actions.append((point, action))
            original_click(point, action)

        self.runtime.click = named_click
        self.machine = SurvivorStateMachine()
        self.runner = SurvivorRunner(
            self.machine,
            self.runtime,
            observer=observer or _Observer(observations),
            sleep=self.clock.sleep,
            poll_seconds=poll_seconds,
        )

    def run(self, max_cycles: int = 1) -> int:
        return self.runner.run(max_cycles=max_cycles)

    def action_names(self) -> list[str]:
        return [action for _point, action in self.actions]


def _inside(point: tuple[int, int], box: tuple[int, int, int, int]) -> bool:
    x, y, width, height = box
    return x <= point[0] < x + width and y <= point[1] < y + height


def _assert_no_forbidden_click(actions: list[tuple[tuple[int, int], str]]) -> None:
    for point, action in actions:
        for label, box in FORBIDDEN_BOXES.items():
            assert not _inside(point, box), (
                f"点了{label}：动作={action} 坐标={point} 禁区={box}"
            )


def _direction_counts(steps: tuple) -> tuple[int, ...]:
    """把一串移动步骤折算成「每个方向各滑了几次」。"""

    return tuple(
        len(list(group))
        for _, group in itertools.groupby(steps, key=lambda step: step.name)
    )


def test_battle_timeout_only_exists_to_catch_a_stuck_run():
    """这活动按击杀算分，**长局是好事**，所以局内上限不能当「打得久就报错」用。

    2026-09-16 22:06 实测：移动改成 7 次 / 700ms 之后角色活到游戏计时 04:13（分数 3360），
    被原来的 300s 上限掐掉、退出码 1。上限的定位改成「抓真卡死」，至少要留够 15 分钟。
    """

    assert SurvivorRunner._BATTLE_TIMEOUT_SECONDS >= 900


# ------------------------------------------------------------------ 状态机守卫


def test_state_machine_rejects_illegal_transitions():
    machine = SurvivorStateMachine()

    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.enter_level_up()
    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.restart()
    # 首卡页还没进局，谈不上结算。
    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.finish_battle()

    machine.start_battle()
    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.start_battle()
    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.restart()

    machine.enter_level_up()
    with pytest.raises(RuntimeError, match="状态不允许"):
        machine.start_battle()

    machine.resume_battle(blue=True)
    assert machine.state is SurvivorState.BATTLE
    assert (machine.level_up_popups, machine.blue_cards_picked) == (1, 1)

    machine.finish_battle()
    assert machine.state is SurvivorState.RESULT
    machine.restart()
    assert machine.state is SurvivorState.CARD
    assert machine.completed_cycles == 1


def test_level_up_popup_can_be_replaced_by_result_without_deadlock():
    """结算页把升级弹窗顶掉时也要能收尾，不能把循环卡死在升级态。"""

    machine = SurvivorStateMachine()
    machine.start_battle()
    machine.enter_level_up()

    machine.finish_battle()

    assert machine.state is SurvivorState.RESULT


def test_non_blue_pick_does_not_inflate_blue_counter():
    machine = SurvivorStateMachine()
    machine.start_battle()
    machine.enter_level_up()

    machine.resume_battle(blue=False)

    assert (machine.level_up_popups, machine.blue_cards_picked) == (1, 0)


# ------------------------------------------------------------------ 单轮闭环


def test_one_cycle_clicks_first_card_then_restart_only():
    harness = _Harness(
        [_frame(1)] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 3: RESULT},
    )

    assert harness.run(max_cycles=1) == 1

    assert harness.action_names() == ["survivor-first-card", "survivor-restart"]
    assert harness.actions[0][0] == FIRST_CARD_ANCHOR
    assert harness.actions[1][0] == RESTART_ANCHOR
    assert harness.machine.state is SurvivorState.CARD
    assert harness.machine.completed_cycles == 1
    assert harness.machine.stop_reason is None
    _assert_no_forbidden_click(harness.actions)


def test_cycle_moves_inside_the_battle_with_the_agreed_swipe_pattern():
    harness = _Harness(
        [_frame(1)] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 3: RESULT},
    )

    harness.run(max_cycles=1)

    first = movement_steps()[0]
    assert harness.swipes == [(first.start, first.end, MOVE_DURATION_MS)]
    assert harness.clock.value > 0


def test_movement_rolls_a_random_repeat_count_per_direction():
    """次数是随机 3~8（用户 2026-09-16 要求）：一轮内每个方向连滑同一段，换方向才重新掷。

    同一个种子必须给出同一串次数，否则这条测试自己就不确定。
    """

    low, high = MOVE_REPEATS_RANGE
    steps = movement_steps(rng=random.Random(20260916))

    groups = [list(group) for _, group in itertools.groupby(steps, key=lambda step: step.name)]
    assert [group[0].name for group in groups] == ["上", "右", "下", "左"]
    for group in groups:
        assert low <= len(group) <= high
        # 同一个方向重复滑的是同一段：起点终点不变，不是每滑一次挪一点。
        assert len(set(group)) == 1
    assert _direction_counts(steps) == _direction_counts(
        movement_steps(rng=random.Random(20260916))
    )


def test_movement_counts_differ_between_rolls():
    """随机的意义就是走位不可预测；如果每次掷出来都一样，等于没随。"""

    low, high = MOVE_REPEATS_RANGE
    rolls = {
        _direction_counts(movement_steps(rng=random.Random(seed))) for seed in range(20)
    }

    assert len(rolls) > 1
    for roll in rolls:
        assert len(roll) == len(MOVE_PATTERN)
        assert all(low <= count <= high for count in roll)


def test_two_cycles_take_two_round_trips_through_the_loop():
    harness = _Harness(
        ([_frame(1)] * 2 + [_frame(2)] + [_frame(3)] * 4) * 2,
        {1: WEAPON_CARD, 2: BATTLE, 3: RESULT},
    )

    assert harness.run(max_cycles=2) == 2

    assert harness.action_names() == [
        "survivor-first-card",
        "survivor-restart",
        "survivor-first-card",
        "survivor-restart",
    ]
    assert harness.machine.completed_cycles == 2
    _assert_no_forbidden_click(harness.actions)


def test_level_up_popup_picks_a_card_and_returns_to_battle():
    level_up = _blue_frame(4)
    harness = _Harness(
        [_frame(1)] * 2 + [_frame(2)] + [level_up] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 4: LEVEL_UP, 3: RESULT},
    )

    harness.run(max_cycles=1)

    assert harness.action_names() == [
        "survivor-first-card",
        "survivor-level-up-0",
        "survivor-restart",
    ]
    assert harness.actions[1][0] == card_center(0)
    assert (harness.machine.level_up_popups, harness.machine.blue_cards_picked) == (1, 1)
    assert harness.machine.completed_cycles == 1
    _assert_no_forbidden_click(harness.actions)


def test_level_up_with_three_support_cards_still_clicks_a_card():
    """用户实测：偶尔三张全是绿卡，没有蓝卡可挑时也要选一张点下去，不能停在弹窗上。

    点哪张无所谓，但必须落在三张卡片的中心之一——不能靠「碰巧」点到别处。
    """

    level_up = _all_support_frame(4)
    harness = _Harness(
        [_frame(1)] * 2 + [level_up] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 4: LEVEL_UP, 3: RESULT},
    )

    harness.run(max_cycles=1)

    card_centres = {card_center(index) for index in range(len(LEVEL_UP_CARDS))}
    assert harness.actions[1][0] in card_centres
    assert harness.actions[1][1].startswith("survivor-level-up-")
    assert (harness.machine.level_up_popups, harness.machine.blue_cards_picked) == (1, 0)
    assert harness.machine.completed_cycles == 1
    _assert_no_forbidden_click(harness.actions)


def test_battle_is_not_moved_while_the_level_up_popup_is_up():
    """弹窗期间滑动会误触卡片，所以这一段必须一次都不滑。"""

    level_up = _blue_frame(4)
    harness = _Harness(
        [_frame(1)] * 2 + [level_up] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 4: LEVEL_UP, 3: RESULT},
    )

    harness.run(max_cycles=1)

    # 整轮只应该在「回到局内」那一段滑过一次，升级弹窗两帧里一次都没滑。
    assert len(harness.swipes) == 1
    assert harness.swipes[0][0] == movement_steps()[0].start


def test_dry_run_logs_the_intent_without_pressing_anything():
    harness = _Harness(
        [_frame(1)] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {1: WEAPON_CARD, 2: BATTLE, 3: RESULT},
        dry_run=True,
    )

    harness.run(max_cycles=1)

    assert harness.action_names() == ["survivor-first-card", "survivor-restart"]
    assert harness.backend_clicks == []
    assert harness.swipes == []


# ------------------------------------------------------------------ 失败关闭


def test_missing_restart_anchor_stops_instead_of_clicking_blindly():
    harness = _Harness(
        [_frame(1)] * 2 + [_frame(2)] + [_frame(3)] * 4,
        {
            1: WEAPON_CARD,
            2: BATTLE,
            3: SurvivorObservation("survivor.result", None),
        },
    )

    with pytest.raises(RuntimeError, match="锚点没找到"):
        harness.run(max_cycles=1)

    assert harness.machine.stop_reason is not None
    assert harness.action_names() == ["survivor-first-card"]
    assert harness.machine.completed_cycles == 0


def test_missing_first_card_anchor_stops_before_entering_the_battle():
    harness = _Harness(
        [_frame(1)] * 4,
        {1: SurvivorObservation("survivor.weapon_card", None)},
    )

    with pytest.raises(RuntimeError, match="锚点没找到"):
        harness.run(max_cycles=1)

    assert harness.actions == []
    assert harness.swipes == []


def test_unknown_battle_screen_never_moves_and_times_out():
    """认不出画面时宁可站着不动，也不要在不清楚的画面上滑摇杆。

    2026-09-16 的实测故障就是反面：三选一弹窗没被认出来，状态机把它当成了
    「认不出的局内」，于是继续上下左右滑，正是用户看到并反馈的问题。
    """

    # 循环总是从首卡页开始，所以先喂两帧首卡页把它推进局内，再无限喂认不出的画面。
    harness = _Harness(
        itertools.chain([_frame(1)] * 2, itertools.repeat(_frame(9))),
        {1: WEAPON_CARD, 9: UNKNOWN},
    )

    with pytest.raises(RuntimeError, match="认不出画面"):
        harness.run(max_cycles=1)

    assert harness.action_names() == ["survivor-first-card"]
    assert harness.swipes == []
    assert harness.machine.stop_reason is not None


def test_level_up_popup_misread_as_first_card_page_never_moves():
    """三选一弹窗左卡标签和首卡页一样，判定顺序一旦失效就会落到 weapon_card 上。

    这时也绝对不能滑：滑杆会在选卡画面上乱划。
    """

    harness = _Harness(
        itertools.chain([_frame(1)] * 2, itertools.repeat(_frame(5))),
        {1: WEAPON_CARD, 5: WEAPON_CARD},
    )

    with pytest.raises(RuntimeError, match="认不出画面"):
        harness.run(max_cycles=1)

    assert harness.action_names() == ["survivor-first-card"]
    assert harness.swipes == []


def test_endless_battle_times_out_fail_closed():
    harness = _Harness(
        itertools.chain([_frame(1)] * 2, itertools.repeat(_frame(2))),
        {1: WEAPON_CARD, 2: BATTLE},
    )

    with pytest.raises(RuntimeError, match="仍未出现结算页"):
        harness.run(max_cycles=1)

    assert harness.action_names() == ["survivor-first-card"]
    assert harness.machine.completed_cycles == 0
    assert harness.machine.stop_reason is not None


def test_first_card_page_never_appearing_times_out():
    harness = _Harness(itertools.repeat(_frame(2)), {2: BATTLE}, poll_seconds=1.0)

    with pytest.raises(RuntimeError, match="等待页面超时"):
        harness.run(max_cycles=1)

    assert harness.actions == []


def test_summary_reports_stop_reason_and_counters():
    machine = SurvivorStateMachine()
    machine.start_battle()
    machine.enter_level_up()
    machine.resume_battle(blue=True)
    machine.finish_battle()
    machine.restart()
    machine.stop("局内超时仍未出现结算页")

    summary = machine.summary()

    assert "完成=1 轮" in summary
    assert "升级弹窗=1 次" in summary
    assert "其中蓝卡=1 次" in summary
    assert "局内超时仍未出现结算页" in summary


# ------------------------------------------------------- 真实模板 + 真实画面


def _fixture(name: str) -> np.ndarray:
    bgr = cv2.imread(str(FIXTURES / f"{name}.png"), cv2.IMREAD_COLOR)
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def test_real_observer_closes_one_cycle_on_captured_screens():
    """不接假观察器：用真模板匹配真画面，验证点下去的坐标就是真按钮。"""

    first = _fixture("first_card_select")
    battle = _fixture("battle_live_probe")
    result = _fixture("result")
    harness = _Harness(
        [first, first, battle, result, result, result, result],
        observer=build_survivor_observer(TEMPLATES),
    )

    assert harness.run(max_cycles=1) == 1

    assert harness.action_names() == ["survivor-first-card", "survivor-restart"]
    first_point, restart_point = harness.actions[0][0], harness.actions[1][0]
    assert _inside(first_point, WEAPON_CARD_BOX)
    assert _inside(restart_point, RESULT_RESTART_BOX)
    assert not _inside(restart_point, CONFIRM_BUTTON_BOX)
    assert harness.swipes == [
        (movement_steps()[0].start, movement_steps()[0].end, MOVE_DURATION_MS)
    ]
    _assert_no_forbidden_click(harness.actions)


def test_real_level_up_screen_is_driven_back_into_the_battle():
    first = _fixture("first_card_select")
    battle = _fixture("battle_live_probe")
    level_up = _fixture("level_up")
    result = _fixture("result")
    harness = _Harness(
        [first, first, battle, level_up, level_up, battle, result, result, result, result],
        observer=build_survivor_observer(TEMPLATES),
    )

    assert harness.run(max_cycles=1) == 1

    assert harness.action_names() == [
        "survivor-first-card",
        "survivor-level-up-0",
        "survivor-restart",
    ]
    # 升级页实际画面里第一张是「攻击武器」（蓝卡），所以选它。
    assert harness.actions[1][0] == card_center(0)
    assert (harness.machine.level_up_popups, harness.machine.blue_cards_picked) == (1, 1)
    _assert_no_forbidden_click(harness.actions)


def test_real_live_level_up_frame_is_recognised_and_stops_the_movement():
    """2026-09-16 那次实跑就是死在这张画面上：三选一没被认出来，于是继续滑摇杆。

    这张实时帧是当时留下的诊断图。它必须被认成三选一、并且弹出期间一次都不滑。
    """

    first = _fixture("first_card_select")
    battle = _fixture("battle_live_probe")
    live_level_up = _fixture("level_up_live_20260916")
    result = _fixture("result")
    harness = _Harness(
        [
            first,
            first,
            battle,
            live_level_up,
            live_level_up,
            battle,
            result,
            result,
            result,
            result,
        ],
        observer=build_survivor_observer(TEMPLATES),
    )

    assert harness.run(max_cycles=1) == 1

    assert harness.action_names() == [
        "survivor-first-card",
        "survivor-level-up-0",
        "survivor-restart",
    ]
    assert (harness.machine.level_up_popups, harness.machine.blue_cards_picked) == (1, 1)
    # 进入局内一次、选完卡回局内一次：弹窗那两帧一次都没滑。
    assert len(harness.swipes) == 2
    _assert_no_forbidden_click(harness.actions)


def test_real_late_level_up_frame_is_driven_back_into_the_battle():
    """2026-09-16 21:29 的第二次失败：这张三选一上「升级」标题只有 0.8662。

    背景变暗的半透明面板把标题拖下了 0.90 门槛，而「重新抽取」又被模拟器键位浮层
    咬掉一角、只剩 0.9134，两个锚点同时不达标 → 整页认不出来 → 局内连续 30s
    认不出画面，退出码 1。修法是把两个模板都裁到只剩字形，并把这一页改成
    「任一锚点命中即可」。这张实时帧是当时留下的诊断图。
    """

    first = _fixture("first_card_select")
    battle = _fixture("battle_live_probe")
    live_level_up = _fixture("level_up_live_20260916_2129")
    result = _fixture("result")
    harness = _Harness(
        [
            first,
            first,
            battle,
            live_level_up,
            live_level_up,
            battle,
            result,
            result,
            result,
            result,
        ],
        observer=build_survivor_observer(TEMPLATES),
    )

    assert harness.run(max_cycles=1) == 1

    assert harness.action_names() == [
        "survivor-first-card",
        "survivor-level-up-0",
        "survivor-restart",
    ]
    assert (harness.machine.level_up_popups, harness.machine.blue_cards_picked) == (1, 1)
    # 弹窗那两帧一次都没滑：认不出弹窗就会在选卡画面上乱滑，正是当年那个 bug。
    assert len(harness.swipes) == 2
    _assert_no_forbidden_click(harness.actions)
