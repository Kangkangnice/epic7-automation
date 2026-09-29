from dataclasses import dataclass
from enum import Enum
from time import monotonic, sleep as default_sleep
from typing import Callable, NoReturn

import numpy as np

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime
from auto_game_unified.core.supervisor import StableObservation, meaningful_change


class AutoBattleState(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class BattleOutcome(Enum):
    RESULT_REACHED = "result_reached"
    PRE_BATTLE_BUSINESS = "pre_battle_business"


@dataclass(frozen=True)
class BattleObservation:
    pre_battle_visible: bool
    battle_visible: bool
    result_visible: bool
    frame_valid: bool
    auto_state: AutoBattleState
    auto_point: tuple[int, int] | None = None
    business_progress: bool = False
    allowed_action: tuple[str, tuple[int, int]] | None = None
    pre_battle_business_visible: bool = False
    # 「这一帧凭什么判定自动/手动」的人话说明（例如「布局=transition 自动关图标=0.9321」）。
    # 只在真的要拨自动开关时写进日志——排查「自动被反复关掉」时，这一行就是全部线索。
    auto_evidence: str = ""


@dataclass(frozen=True)
class BattleConfig:
    mode: str
    mode_label: str = ""
    poll_seconds: float = 1.0
    entry_absolute_seconds: float = 180
    no_activity_seconds: float = 180
    no_business_progress_seconds: float = 900
    absolute_seconds: float = 900
    unrecognized_seconds: float = 45
    black_seconds: float = 45
    allowed_action_retry_seconds: float = 3
    allowed_action_failure_seconds: float = 15
    heartbeat_seconds: float = 30
    # 一场战斗里「自动开关点开之后又被关掉」最多容忍几次。超过就判定是游戏侧行为，
    # 不再拨开关（继续监督到结算），免得整场都在自动/手动之间来回跳。
    auto_recovery_limit: int = 3


BattleObserver = Callable[[np.ndarray, np.ndarray | None], BattleObservation]


def valid_game_frame(screen: np.ndarray) -> bool:
    content = screen[
        round(screen.shape[0] * 0.05) :,
        : round(screen.shape[1] * 0.97),
    ]
    return float(np.mean(content)) >= 3.0 and float(np.std(content)) >= 5.0


class BattleSupervisor:
    def __init__(
        self,
        runtime: Runtime,
        gate: RecoveryGate,
        config: BattleConfig,
        *,
        now: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self.runtime = runtime
        self.gate = gate
        self.config = config
        self.label = config.mode_label or config.mode
        self.now = now
        self.sleep = sleep

    def _fail(self, label: str, message: str, screen: np.ndarray) -> NoReturn:
        """记日志 + 存诊断，然后**一定抛**。

        ⚠️ 返回类型必须是 ``NoReturn``、不能写 ``None``：调用点后面紧接着就用「到这里
        已经确认非 None」的值（例如 ``observation.auto_point``：上面刚判过
        ``is None -> _fail(...)``，下面直接拿它去点击）。写成 ``None`` 的话类型检查器
        不知道这里会终止，会把那次点击标成「可能传入 None」—— 而那正是会崩的写法。
        ``mypy`` 在 2026-09-30 上线时就是这么把这条链揪出来的。
        """
        path = (
            self.runtime.save_diagnostic(label, screen)
            if self.runtime.diagnostic_dir is not None
            else "not-configured"
        )
        self.runtime.log(
            f"模式={self.label} 阶段=战斗 状态=安全停止 "
            f"原因={message} 诊断={path}"
        )
        raise RuntimeError(f"{message}；已保存诊断 {path}")

    def run(self, observe: BattleObserver, *, cycle: int) -> BattleOutcome:
        self.gate.lock(mode=self.config.mode, cycle=cycle)
        started = active_at = business_at = heartbeat = self.now()
        invalid_since = black_since = None
        previous = None
        auto_clicks = 0
        auto_clicked_at: float | None = None
        auto_source_gone_logged = False
        auto_recoveries = 0
        auto_interference_stopped = False
        auto_interference_logged = False
        last_allowed_action = None
        allowed_action_clicks = 0
        allowed_action_clicked_at: float | None = None
        entry_confirmed = False
        auto_confirmed = False
        business_pending_logged = False
        battle_stable = StableObservation(required=2)
        auto_stable = StableObservation(required=2)
        allowed_stable = StableObservation(required=2)
        business_stable = StableObservation(required=2)
        result_stable = StableObservation(required=2)
        try:
            while True:
                screen = self.runtime.capture()
                if self.runtime.diagnostic_dir is not None:
                    self.runtime.save_current_frame(screen)
                observation = observe(screen, previous)
                current = self.now()

                result_signature = "result" if observation.result_visible else "other"
                if (
                    result_stable.update(result_signature)
                    and observation.result_visible
                ):
                    self.runtime.log(
                        f"模式={self.label} 轮次={cycle} 阶段=结算 状态=已确认"
                    )
                    return BattleOutcome.RESULT_REACHED

                business_signature = (
                    "business"
                    if observation.pre_battle_business_visible
                    else "other"
                )
                business_confirmed = business_stable.update(business_signature)
                business_pending = (
                    observation.pre_battle_business_visible and not entry_confirmed
                )
                if business_confirmed and business_pending:
                    self.runtime.log(
                        f"模式={self.label} 轮次={cycle} "
                        "阶段=战前 状态=交还业务处理"
                    )
                    return BattleOutcome.PRE_BATTLE_BUSINESS
                if business_pending:
                    if not business_pending_logged:
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} 阶段=战前 "
                            "状态=业务弹窗首帧已识别 动作=冻结背景操作 "
                            "等待=连续2帧确认"
                        )
                        business_pending_logged = True
                    allowed_stable.reset()
                    last_allowed_action = None
                    allowed_action_clicks = 0
                    allowed_action_clicked_at = None
                else:
                    business_pending_logged = False
                effective_allowed_action = (
                    None if business_pending else observation.allowed_action
                )

                entered = observation.battle_visible or (
                    not observation.pre_battle_visible
                    and observation.allowed_action is None
                    and observation.frame_valid
                    and meaningful_change(previous, screen)
                )
                if (
                    battle_stable.update("battle" if entered else "other")
                    and entered
                    and not entry_confirmed
                ):
                    entry_confirmed = True
                    if last_allowed_action is not None:
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} "
                            f"阶段=战前 转场确认 动作={last_allowed_action[0]} "
                            "目标=战斗"
                        )
                    self.runtime.log(
                        f"模式={self.label} 轮次={cycle} "
                        "阶段=战斗 状态=已进入"
                    )

                if meaningful_change(previous, screen):
                    active_at = current
                if observation.business_progress:
                    business_at = current

                if not observation.frame_valid:
                    black_since = current if black_since is None else black_since
                    if current - black_since >= self.config.black_seconds:
                        self._fail(
                            "battle_black_timeout", "战斗画面持续黑屏超时", screen
                        )
                else:
                    black_since = None

                recognized = (
                    observation.pre_battle_visible
                    or observation.battle_visible
                    or observation.result_visible
                    or observation.allowed_action is not None
                    or observation.pre_battle_business_visible
                )
                if observation.frame_valid and not recognized:
                    invalid_since = current if invalid_since is None else invalid_since
                    if current - invalid_since >= self.config.unrecognized_seconds:
                        self._fail(
                            "battle_unrecognized",
                            "战斗画面持续无法识别超时",
                            screen,
                        )
                else:
                    invalid_since = None

                stable_auto = auto_stable.update(observation.auto_state.value)
                allowed_signature = (
                    "none"
                    if effective_allowed_action is None
                    else (
                        f"{effective_allowed_action[0]}:"
                        f"{effective_allowed_action[1]}"
                    )
                )
                allowed_confirmed = allowed_stable.update(allowed_signature)
                if (
                    effective_allowed_action is not None
                    and effective_allowed_action != last_allowed_action
                ):
                    if last_allowed_action is not None:
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} "
                            f"阶段=战前 转场确认 动作={last_allowed_action[0]} "
                            f"目标动作={effective_allowed_action[0]}"
                        )
                    last_allowed_action = effective_allowed_action
                    allowed_action_clicks = 0
                    allowed_action_clicked_at = None
                if allowed_confirmed and effective_allowed_action is not None:
                    action_name, action_point = effective_allowed_action
                    since_click = (
                        None
                        if allowed_action_clicked_at is None
                        else current - allowed_action_clicked_at
                    )
                    should_click = (
                        allowed_action_clicked_at is None
                        or (
                            allowed_action_clicks < 4
                            and since_click is not None
                            and since_click >= self.config.allowed_action_retry_seconds
                        )
                    )
                    if should_click:
                        allowed_action_clicks += 1
                        phase = "战斗" if entry_confirmed else "战前"
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} "
                            f"阶段={phase} 动作={action_name} "
                            f"尝试={allowed_action_clicks}/4"
                        )
                        self.runtime.click(action_point, action_name)
                        allowed_action_clicked_at = current
                        business_at = current
                    elif (
                        allowed_action_clicks >= 4
                        and since_click is not None
                        and since_click >= self.config.allowed_action_failure_seconds
                    ):
                        self._fail(
                            f"allowed_action_{action_name}_failed",
                            f"允许动作 {action_name} 点击4次后画面未推进",
                            screen,
                        )

                if (
                    stable_auto
                    and observation.auto_state is AutoBattleState.MANUAL
                ):
                    if observation.auto_point is None:
                        self._fail(
                            "auto_point_missing",
                            "手动战斗状态下缺少自动开关坐标",
                            screen,
                        )
                    auto_confirmed = False
                    if auto_interference_stopped and not auto_interference_logged:
                        # 本场已经反复出现「点开 → 又被关掉」：再拨下去只是来回跳。
                        # 停手，交给下面的无进展看门狗兜底，日志留一行说明为什么停手。
                        auto_interference_logged = True
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} 阶段=战斗 "
                            f"状态=自动战斗反复被关闭 累计={auto_recoveries}次 "
                            "判定=游戏侧行为 处理=不再反复拨自动开关，继续监督本场战斗 "
                            f"证据={observation.auto_evidence or '未标注'}"
                        )
                    since_auto_click = (
                        None
                        if auto_clicked_at is None
                        else current - auto_clicked_at
                    )
                    should_click_auto = not auto_interference_stopped and (
                        auto_clicked_at is None
                        or (
                            auto_clicks < 4
                            and since_auto_click is not None
                            and since_auto_click
                            >= self.config.allowed_action_retry_seconds
                        )
                    )
                    if should_click_auto:
                        auto_clicks += 1
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} "
                            f"阶段=战斗 动作=开启自动战斗 "
                            f"尝试={auto_clicks}/4 依据=自动关闭来源连续=2 "
                            f"证据={observation.auto_evidence or '未标注'}"
                        )
                        self.runtime.click(
                            observation.auto_point, "enable-auto-battle"
                        )
                        auto_clicked_at = current
                        auto_source_gone_logged = False
                        auto_stable.reset()
                    elif (
                        auto_clicks >= 4
                        and since_auto_click is not None
                        and since_auto_click
                        >= self.config.allowed_action_failure_seconds
                    ):
                        self._fail(
                            "auto_not_confirmed",
                            "点击4次后仍为手动战斗",
                            screen,
                        )
                elif (
                    stable_auto
                    and observation.auto_state is AutoBattleState.AUTO
                ):
                    if auto_clicked_at is not None:
                        # 上一次是我们拨开的，现在确认自动已开启 ⇒ 这次「补开」有效。
                        # 一场战斗里补开太多次，说明自动是被外面反复关掉的，不再插手。
                        auto_recoveries += 1
                        if auto_recoveries >= self.config.auto_recovery_limit:
                            auto_interference_stopped = True
                    auto_clicks = 0
                    auto_clicked_at = None
                    auto_source_gone_logged = False
                    if not auto_confirmed:
                        auto_confirmed = True
                        self.runtime.log(
                            f"模式={self.label} 轮次={cycle} "
                            "阶段=战斗 状态=自动战斗已开启"
                        )
                elif (
                    observation.auto_state is AutoBattleState.UNKNOWN
                    and auto_clicked_at is not None
                    and not auto_confirmed
                    and not auto_source_gone_logged
                ):
                    auto_source_gone_logged = True
                    self.runtime.log(
                        f"模式={self.label} 轮次={cycle} 阶段=战斗 "
                        "等待确认=自动战斗 来源=自动关闭已离开 "
                        "目标=人物头像待确认"
                    )
                if (
                    not entry_confirmed
                    and current - started >= self.config.entry_absolute_seconds
                ):
                    self._fail(
                        "battle_entry_timeout",
                        "战斗进入未能确认",
                        screen,
                    )
                if current - active_at >= self.config.no_activity_seconds:
                    self._fail(
                        "battle_no_activity",
                        "战斗画面无变化超时",
                        screen,
                    )
                if (
                    current - business_at
                    >= self.config.no_business_progress_seconds
                ):
                    self._fail(
                        "battle_no_business_progress",
                        "战斗业务无进展超时",
                        screen,
                    )
                if current - started >= self.config.absolute_seconds:
                    self._fail(
                        "battle_absolute_timeout",
                        "战斗绝对超时",
                        screen,
                    )
                if current - heartbeat >= self.config.heartbeat_seconds:
                    self.runtime.log(
                        f"模式={self.label} 轮次={cycle} "
                        "阶段=战斗 状态=心跳 "
                        f"已耗时={current - started:.0f}秒 "
                        f"距上次画面变化={current - active_at:.0f}秒 "
                        f"距上次业务进展={current - business_at:.0f}秒"
                    )
                    heartbeat = current

                previous = screen
                self.sleep(self.config.poll_seconds)
        finally:
            self.gate.unlock()
