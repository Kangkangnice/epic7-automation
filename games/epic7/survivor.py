"""Survivor activity mini-game: card selection, movement plan and the loop runner.

页面识别在 `evidence/survivor.py`；这里放「怎么打」。

用户需求：人工把游戏推到「选第一张卡」那页，之后 AI 接管，反复循环：
    选第一张卡 -> 局内滑摇杆 ->（升级三选一就选蓝卡）-> 死亡 -> 结算 -> 重新进行 -> 回到首卡页
每次活十几秒即可，但要能一直挂着，明确不要求操作精准。
"""

import random
from dataclasses import dataclass
from enum import Enum
from time import sleep as default_sleep
from typing import Any, Callable

import cv2
import numpy as np

from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation

from auto_game_unified.games.epic7.evidence.survivor import (
    BLUE_CARD_HUE,
    LEVEL_UP_CARDS,
    LEVEL_UP_LABEL_STRIP_Y,
    SurvivorObserver,
)


# --------------------------------------------------------------------------- 选卡
#
# 用户要求升级弹窗出现时优先选蓝色的卡；三张都不是蓝色就随机选一张。实测发现卡面颜色
# 编码的是**武器类别**而不是稀有度：三张「攻击武器」卡（含开局那把，用户明确说是蓝色）
# 标签栏中位色相都是 94，而「辅助武器」卡是 77。所以「蓝色」等价于「攻击武器卡」。

LEVEL_UP_CARD_INDEXES = tuple(range(len(LEVEL_UP_CARDS)))


def card_label_hue(screen: np.ndarray, card: tuple[int, int, int, int]) -> float:
    """取卡片顶部标签栏的中位色相。

    `screen` 必须是 RGB（与 `find_template` 的约定一致）；`card` 是 (x, y, width, height)。
    取中位数是为了对标签栏上的浅色文字免疫——文字只占少数像素。
    """

    x, _, width, _ = card
    y0, y1 = LEVEL_UP_LABEL_STRIP_Y
    strip = screen[y0:y1, x : x + width]
    if strip.size == 0:
        raise ValueError(f"卡片的标签栏取样区为空：{card}")
    return float(np.median(cv2.cvtColor(strip, cv2.COLOR_RGB2HSV)[:, :, 0]))


def is_blue_card(screen: np.ndarray, card: tuple[int, int, int, int]) -> bool:
    low, high = BLUE_CARD_HUE
    return low <= card_label_hue(screen, card) <= high


def choose_level_up_card(screen: np.ndarray, rng: Any = random) -> int:
    """返回要点的卡片序号：优先第一张蓝卡；三张都不是蓝卡就随机选一张。

    随机用的 `rng` 只要有 `choice(seq)` 就行（默认 `random` 模块，测试传 `random.Random`
    拿确定性）。用户实测反馈：偶尔三张全是绿卡（辅助武器），固定点最左边那张没有道理，
    随机一张即可——三张卡位置本来就是固定的，点哪张都点得到。
    """

    for index, card in enumerate(LEVEL_UP_CARDS):
        if is_blue_card(screen, card):
            return index
    return rng.choice(LEVEL_UP_CARD_INDEXES)


def card_center(index: int) -> tuple[int, int]:
    """卡片矩形中心，直接作为点击点。"""

    x, y, width, height = LEVEL_UP_CARDS[index]
    return x + width // 2, y + height // 2


# --------------------------------------------------------------------------- 移动
#
# 用户实测结论（2026-09-16，推翻了「必须按住摇杆」的假设）：adb 的 `input swipe`
# 结束时必然松手，但**不需要一直按住**——每滑一次角色就前进一段，松手后还在继续走，
# 再滑又前进一段。所以靠「重复滑动」就能持续移动。
#
# 距离与时长沿用秘密商店那套（ShopRefreshRunner._SCROLL_*）：630px / 500ms。
#
# **2026-09-16 用户实测反馈「移动太慢、一直被攻击」**：一次滑动里角色只有
# 「手指按住的那段时间」在动——`input swipe` 的 duration 就是这段位移的时长，
# 拖得越久、角色在满偏摇杆下跑得越久，单次滑动的位移就越大。所以把 500ms 提到 700ms
# （几何不变，还是同一段 630px，只是拖得更久）。
#
# 节奏上的浪费在两次滑动之间的空等：原来 `_MOVE_STEP_GAP_SECONDS=0.25` 是纯等待
# （角色已经松手在减速了，什么也没做），压到 0.1s。这样「满速前进」在一轮里的占比
# 从约 50% 提到约 70%，实测日志里两次滑动间隔约 1.0~1.4s 就是这么来的。
MOVE_DISTANCE = 630
MOVE_DURATION_MS = 700

# 屏幕正中央（画布坐标）。画布 1982x1132 里安卓渲染区从 y=52 开始，
# 所以渲染区中心是 (960, 52 + 540) = (960, 592)。
CANVAS_CENTER = (960, 592)

# 「上 右 下 左」循环：让角色绕圈跑，怪会追着你在后面绕，生存久一点同时还能打到人。
MOVE_PATTERN = (("上", 0, -1), ("右", 1, 0), ("下", 0, 1), ("左", -1, 0))

# 每个方向连滑几次再换方向。次数由用户实测调出来：2 太短 → 5 还不够 → 7。
# **2026-09-16 用户要求改成随机数 3~8**：固定次数走久了就是一条可预测的固定路径，
# 改成每次换方向现掷一次，路线才有变化。
MOVE_REPEATS_RANGE = (3, 8)


def swipe_segment(
    dx: int, dy: int, distance: int = MOVE_DISTANCE
) -> tuple[tuple[int, int], tuple[int, int]]:
    """把位移段以屏幕正中央为中心摆开，保证两端都落在渲染区内。

    `Epic7Window.swipe` 会拒绝越界的滑动，630px 从中心单向拉出去会出界，
    所以起点终点各退一半。
    """

    half = distance // 2
    start = (CANVAS_CENTER[0] - dx * half, CANVAS_CENTER[1] - dy * half)
    end = (CANVAS_CENTER[0] + dx * half, CANVAS_CENTER[1] + dy * half)
    return start, end


@dataclass(frozen=True)
class MoveStep:
    name: str
    start: tuple[int, int]
    end: tuple[int, int]

    def __str__(self) -> str:
        return f"{self.name} {self.start}->{self.end}"


def movement_steps(
    distance: int = MOVE_DISTANCE, rng: Any = random
) -> tuple[MoveStep, ...]:
    """一轮完整的移动步骤：每个方向连滑 `MOVE_REPEATS_RANGE` 内随机次，按上右下左循环。

    `rng` 只要有 `randint(a, b)` 就行（默认 `random` 模块，测试传 `random.Random` 拿确定性）。
    同一个方向内部重复滑的是**同一段**（起点终点不变），换方向时才重新掷次数。
    """

    steps: list[MoveStep] = []
    for name, dx, dy in MOVE_PATTERN:
        start, end = swipe_segment(dx, dy, distance)
        for _ in range(rng.randint(*MOVE_REPEATS_RANGE)):
            steps.append(MoveStep(name, start, end))
    return tuple(steps)


# ----------------------------------------------------------------------- 状态机


class SurvivorState(Enum):
    CARD = "card"
    BATTLE = "battle"
    LEVEL_UP = "level_up"
    RESULT = "result"


class SurvivorStateMachine:
    def __init__(self, *, observer: SurvivorObserver | None = None) -> None:
        self.state = SurvivorState.CARD
        self.observer = observer
        self.completed_cycles = 0
        self.level_up_popups = 0
        self.blue_cards_picked = 0
        self.stop_reason: str | None = None

    def _require(self, *states: SurvivorState) -> None:
        if self.state not in states:
            expected = "/".join(state.value for state in states)
            raise RuntimeError(f"状态不允许：当前={self.state.value} 期望={expected}")

    def start_battle(self) -> None:
        self._require(SurvivorState.CARD)
        self.state = SurvivorState.BATTLE

    def enter_level_up(self) -> None:
        self._require(SurvivorState.BATTLE)
        self.state = SurvivorState.LEVEL_UP
        self.level_up_popups += 1

    def resume_battle(self, *, blue: bool) -> None:
        self._require(SurvivorState.LEVEL_UP)
        self.state = SurvivorState.BATTLE
        if blue:
            self.blue_cards_picked += 1

    def finish_battle(self) -> None:
        # 允许从升级状态直接进结算：万一结算页把升级弹窗顶掉了也不该把循环卡死。
        self._require(SurvivorState.BATTLE, SurvivorState.LEVEL_UP)
        self.state = SurvivorState.RESULT

    def restart(self) -> None:
        self._require(SurvivorState.RESULT)
        self.completed_cycles += 1
        self.state = SurvivorState.CARD

    def stop(self, reason: str) -> None:
        self.stop_reason = reason

    def summary(self) -> str:
        return (
            f"完成={self.completed_cycles} 轮 "
            f"升级弹窗={self.level_up_popups} 次 其中蓝卡={self.blue_cards_picked} 次 "
            f"停止原因={self.stop_reason or '正常完成'}"
        )


# ----------------------------------------------------------------------- Runner


class SurvivorRunner:
    """一轮闭环：首卡 -> 局内 ->（升级）-> 结算 -> 重新进行。"""

    # 等某一页出现的最长时间（点完卡片、点完重新进行之后等下一屏）。
    _ENTRY_TIMEOUT_SECONDS = 30.0
    # 局内最长允许时长。这活动是「越强活得越久」，所以这个上限的定位是**抓真卡死**，
    # 而不是「嫌这一局打太久」——用户要的恰恰是长局（按击杀算分）。
    # 2026-09-16 22:06 实测：移动改成 7 次 / 700ms 之后角色活到游戏计时 04:13、
    # 分数 3360，还被原来的 300s 上限掐掉了（那局是真正的第 6 轮，不是认不出画面）。
    # 放宽到 30 分钟，够覆盖任何一局正常的长局；真要立刻停随时按 P。
    _BATTLE_TIMEOUT_SECONDS = 1800.0
    # 局内连续认不出画面最多容忍多久（转场瞬间是正常的）。
    _UNKNOWN_TIMEOUT_SECONDS = 30.0
    # 每滑一次之后的空等。角色松手后自己会继续滑行，这段时间不推进什么。
    # 0.25s → 0.1s → **0.0**（2026-09-16 用户要求「间隔短一些、移动更连贯」）：
    # 实测一轮 1.2s 的构成是 滑动 700ms + adb 起进程 225ms + 抓帧 165ms + 空等 + 识别 13ms，
    # 所以空等直接清零；抓帧本身已经天然隔开两条手势约 180ms，不需要再手动等。
    _MOVE_STEP_GAP_SECONDS = 0.0
    # 同一页要连续两帧都认出来才算数。
    _STABLE_FRAMES = 2

    def __init__(
        self,
        machine: SurvivorStateMachine,
        runtime: Runtime,
        *,
        observer: SurvivorObserver | None = None,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 0.5,
        recovery_gate=None,
    ) -> None:
        # 本路线没有战斗（整轮都在活动小游戏内部）⇒ 用不上战斗锁；
        # main 统一注入的选项在这里显式丢弃。
        del recovery_gate
        self.machine = machine
        self.runtime = runtime
        self.observer = observer or machine.observer
        if self.observer is None:
            raise ValueError("SurvivorRunner 需要视觉观察器")
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.now = runtime.now
        self.resource_exhausted = False
        self._steps = movement_steps()
        self._step_index = 0

    def _failure(self, message: str, screen: np.ndarray | None = None) -> RuntimeError:
        self.machine.stop(message)
        if self.runtime.diagnostic_dir is not None:
            diagnostic = self.runtime.save_diagnostic("survivor_unknown", screen)
            message = f"{message}；已保存诊断 {diagnostic}"
        self.runtime.log(f"模式=幸存者 结论=UNKNOWN 原因={message}")
        return RuntimeError(message)

    def _observe_stable(
        self, page: str, *, timeout: float
    ) -> tuple[np.ndarray, tuple[int, int] | None]:
        """等某一页连续两帧稳定出现，返回该帧与可点锚点中心。"""

        deadline = self.now() + timeout
        stable = StableObservation(required=self._STABLE_FRAMES)
        while True:
            if self.now() > deadline:
                raise self._failure(f"等待页面超时：{page}（{timeout:.0f}s）")
            screen = self.runtime.capture()
            observation = self.observer.observe(screen)
            if observation.page != page:
                stable.reset()
            elif stable.update(page):
                return screen, observation.anchor
            self.sleep(self.poll_seconds)

    def _require_anchor(
        self, anchor: tuple[int, int] | None, page: str, hint: str
    ) -> tuple[int, int]:
        if anchor is None:
            raise self._failure(f"{page} 认出来了，但{hint}的锚点没找到")
        return anchor

    def _open_with_first_card(self) -> None:
        _, anchor = self._observe_stable(
            "survivor.weapon_card", timeout=self._ENTRY_TIMEOUT_SECONDS
        )
        point = self._require_anchor(anchor, "首卡页", "「攻击武器」")
        self.runtime.click(point, "survivor-first-card")
        self.machine.start_battle()

    def _move_once(self) -> None:
        # 走完一轮（上右下左各若干次）就重新掷一次各方向的次数：每轮都用新节奏，
        # 不然「随机了但每轮一模一样」，走位还是可预测的。
        if self._step_index >= len(self._steps):
            self._steps = movement_steps()
            self._step_index = 0
        step = self._steps[self._step_index]
        self._step_index += 1
        self.runtime.swipe(
            step.start, step.end, MOVE_DURATION_MS, f"survivor-move-{step.name}"
        )
        self.sleep(self._MOVE_STEP_GAP_SECONDS)

    def _pick_level_up_card(self, screen: np.ndarray) -> None:
        index = choose_level_up_card(screen)
        blue = is_blue_card(screen, LEVEL_UP_CARDS[index])
        centre = card_center(index)
        self.machine.enter_level_up()
        self.runtime.log(
            f"模式=幸存者 升级三选一 选中卡={index} 蓝色={'是' if blue else '否'} 坐标={centre}"
        )
        self.runtime.click(centre, f"survivor-level-up-{index}")
        self.machine.resume_battle(blue=blue)

    def _play_battle(self) -> float:
        """滑摇杆直到结算页出现，返回这一轮的局内时长（秒）。"""

        started = self.now()
        unknown_since: float | None = None
        level_up_stable = StableObservation(required=self._STABLE_FRAMES)
        result_stable = StableObservation(required=self._STABLE_FRAMES)

        while True:
            elapsed = self.now() - started
            if elapsed > self._BATTLE_TIMEOUT_SECONDS:
                raise self._failure(f"局内 {elapsed:.0f}s 仍未出现结算页")
            screen = self.runtime.capture()
            observation = self.observer.observe(screen)

            # 结算页是静止的，没有倒计时；稳定两帧后即认定这一轮结束。
            if observation.page == "survivor.result":
                if result_stable.update("survivor.result"):
                    self.machine.finish_battle()
                    self.runtime.log(f"模式=幸存者 局内结束 存活={elapsed:.1f}s")
                    return elapsed
                self.sleep(self.poll_seconds)
                continue
            result_stable.reset()

            # 升级弹窗期间绝对不要再滑，避免误触；选完继续打。
            if observation.page == "survivor.level_up":
                if level_up_stable.update("survivor.level_up"):
                    self._pick_level_up_card(screen)
                    level_up_stable.reset()
                    unknown_since = None
                self.sleep(self.poll_seconds)
                continue
            level_up_stable.reset()

            # **只有确认在局内才滑摇杆**。认不出来的画面、以及三选一左卡标签造成的
            # 「首卡页」误判，一律不动手——用户实测反馈的就是这个：升级三选一画面出现时
            # 还在上下左右滑。宁可站着不动等识别，也不要在选卡画面上乱滑。
            if observation.page == "survivor.battle":
                unknown_since = None
                self._move_once()
                continue

            if unknown_since is None:
                unknown_since = self.now()
            elif self.now() - unknown_since > self._UNKNOWN_TIMEOUT_SECONDS:
                raise self._failure(
                    f"局内连续 {self._UNKNOWN_TIMEOUT_SECONDS:.0f}s 认不出画面", screen
                )
            self.sleep(self.poll_seconds)

    def _restart(self) -> None:
        _, anchor = self._observe_stable(
            "survivor.result", timeout=self._ENTRY_TIMEOUT_SECONDS
        )
        point = self._require_anchor(anchor, "结算页", "「重新进行」")
        # 「确认」就在右边 346 像素处，误点会回到活动页面（一大堆未知状态），
        # 所以只点锚点命中中心——搜索区域已收紧到左半边，确认按钮进不了搜索范围。
        self.runtime.click(point, "survivor-restart")
        self.machine.restart()

    def run(self, max_cycles: int | None = None) -> int:
        target = "无限" if max_cycles is None else max_cycles
        self.runtime.log(f"模式=幸存者 启动 目标轮数={target}")
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            self._open_with_first_card()
            survived = self._play_battle()
            self._restart()
            self.runtime.log(
                f"模式=幸存者 第 {self.machine.completed_cycles} 轮完成 "
                f"局内={survived:.1f}s"
            )
        self.runtime.log(f"模式=幸存者 结束 {self.machine.summary()}")
        return self.machine.completed_cycles
