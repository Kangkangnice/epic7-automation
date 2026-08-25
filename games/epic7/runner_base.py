"""story/fodder/assist_auto 三条同构线的公共 Runner 骨架。

主循环协议在此统一实现：
- 空跑短路（单帧诊断）
- 两帧稳定确认 + 同动作 45 秒转场等待 + 2 次点击上限
- 未知画面唤醒（UnknownScreenWake）
- 唤醒持续 WAITING（画面变化无法触发唤醒点击）同样受状态超时约束
- 状态超时 → 恢复一次（回大厅重新导航）→ 仍超时则安全停止
- 结算等待超时与绝对超时熔断
各模式仅通过钩子注入差异（战斗移交方式、恢复落点、超时表等）。
"""

from time import sleep as default_sleep
from typing import Any, Callable, Optional

from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import Runtime, StaminaExhausted
from auto_game_unified.core.supervisor import StableObservation
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)


class _NotStable:
    """两帧未稳定，本轮跳过的哨兵值。"""


NOT_STABLE = _NotStable()


class ModeRunnerBase:
    """同构模式 Runner 的公共主循环；子类通过钩子注入差异。"""

    _MODE_LABEL = ""  # 日志用模式名（如 "狗粮"），子类必填
    _ACTION_RETRY_SECONDS = 45
    _ABSOLUTE_TIMEOUT_SECONDS: Optional[int] = 180  # None 表示无绝对超时
    _TIMEOUT_SECONDS: dict[Any, int] = {}
    _BATTLE_ENTRY_ACTION: Optional[str] = None  # 触发战斗移交的动作名
    _CLICK_BEFORE_BATTLE = True  # True=先点击再移交；False=不点击直接移交（战斗监督代点）
    _SETTLED_BATTLE_STATE = None  # 停在该状态且无动作时直接移交战斗（狗粮 BATTLE）
    _BLACK_SCREEN_TIMEOUT_SECONDS: Optional[float] = None
    _BLACK_SCREEN_LOG_INTERVAL_SECONDS = 10.0
    _ALLOW_UNKNOWN_SCREEN_WAKE = True

    def __init__(
        self,
        machine: Any,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery: Callable[[], None] | None = None,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        self.recovery_gate = recovery_gate or RecoveryGate(recovery)
        self.recovery = self.recovery_gate.recover if recovery is not None else None
        self.unknown_screen_wake = UnknownScreenWake(
            runtime, recovery_gate=self.recovery_gate
        )
        self.resource_exhausted = False

    # ---- 子类钩子（差异点） ----

    def _state_label(self, state: Any) -> str:
        return str(getattr(state, "value", state))

    def _timeout_for(self, state: Any) -> float:
        return self._TIMEOUT_SECONDS[state]

    def _apply_recovery_state(self) -> None:
        """恢复导航后设置落点状态（含业务标志重置）。"""

    def _after_action_click(self, action: Any) -> None:
        """Optional short observation immediately after an action click."""

    def _run_committed_battle(self, *, cycle: int) -> None:
        raise NotImplementedError

    def _on_battle_entry(self, action: Any, state_before: Any, max_cycles: Optional[int]) -> None:
        """战斗移交前的日志等特判（狗粮的“交由战斗监督”日志）。"""

    def _after_battle(self, max_cycles: Optional[int]) -> bool:
        """战斗监控返回后的特判；返回 True 表示应立即结束 run()。"""
        return False

    def _on_action_exhausted(self, action: Any, screen) -> bool:
        """动作重试 2 次仍无进展时的特判；返回 True 表示已优雅收尾。"""
        return False

    def _check_cycle_completed(self, cycles_before: int, max_cycles: Optional[int]) -> bool:
        """完成一轮后的日志与 max_cycles 提前返回；返回 True 表示结束 run()。"""
        if self.machine.completed_cycles > cycles_before:
            self._recovered = False
            self._log_cycle_completed()
            if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                return True
        return False

    def _decision_hint(self, action_name: str, state: Any) -> str:
        """子模式可在覆写里给当前动作附加决策原因摘要。"""
        return ""

    def _transition_completed(
        self, previous_action: Any, current_action: Any, confirmed_page: str
    ) -> bool:
        """判断上一个带目标契约的动作是否已看到目标证据。"""
        if (
            not confirmed_page
            or confirmed_page not in getattr(previous_action, "target_pages", ())
        ):
            return False
        return (
            current_action is None
            or current_action.name != previous_action.name
        )

    def _transition_retry_reason(self, previous_action: Any, current_action: Any) -> str:
        return "原页面仍存在且目标页面未出现"

    def _transition_success_detail(
        self, previous_action: Any, current_action: Any
    ) -> str:
        return ""

    @staticmethod
    def _source_observation_matches(
        previous_action: Any, current_action: Any
    ) -> bool:
        previous = getattr(previous_action, "source_observation", "")
        if not previous:
            return True
        return bool(
            current_action is not None
            and getattr(current_action, "source_observation", "") == previous
        )

    def _is_instant_action(self, action_name: Optional[str]) -> bool:
        """返回 True 表示该动作不需要 stable 2 帧确认（一次性副作用，必须立刻发）。"""
        return False

    def _stable_action_signature(self, preview_action: Any, outcome: Any) -> str:
        if preview_action is not None:
            return preview_action.name
        return f"settled:{outcome[0].value}:{outcome[1]}"

    def _is_black_screen(self, screen) -> bool:
        """子模式可选择启用独立黑屏保护；默认不改变现有模式行为。"""
        return False

    def _stall_timeout_seconds(self) -> float:
        """连续发出相同动作名超过此时长未进展则触发恢复。"""
        return 45.0

    def _action_retry_seconds(self, action_name: str) -> float:
        """返回同一动作再次尝试前的等待时间。"""
        return self._ACTION_RETRY_SECONDS

    def _log_cycle_completed(self) -> None:
        self.runtime.log(
            f"模式={self._MODE_LABEL} 状态=完成一轮 cycles={self.machine.completed_cycles}"
        )

    def _timeout_error_message(self, error: Exception, diagnostic) -> str:
        return f"页面无进展：{error}；已安全停止并保存诊断 {diagnostic}"

    def _log_state_timeout(self, state: Any, elapsed: float, diagnostic) -> None:
        """状态超时抛错前的补充日志（主线有，其余默认无）。"""

    def _log_settled_timeout(self, state: Any, diagnostic) -> None:
        """结算等待超时抛错前的补充日志（主线有，其余默认无）。"""

    def _stable_next_action(self, screen, stable: StableObservation):
        """两帧稳定确认后返回 next_action；未稳定时返回 NOT_STABLE。"""
        preview_action, outcome = self.machine.preview(screen)
        self.unknown_screen_wake.reset()
        signature = self._stable_action_signature(preview_action, outcome)
        # 一次性副作用动作：直接 click 跳过 stable——这种动作的副作用必须
        # 立即生效（如 close_filter），否则会被动画过渡帧打断。
        if preview_action is not None and self._is_instant_action(preview_action.name):
            committed_action = self.machine.next_action(screen)
            if (
                committed_action is None
                or committed_action.name != preview_action.name
            ):
                stable.reset()
                return NOT_STABLE
            self.runtime.click(committed_action.point, committed_action.name)
            stable.reset()
            # 状态由真正 next_action 提交；下一帧重新观察点击结果。
            return NOT_STABLE
        if not stable.update(signature):
            return NOT_STABLE
        return self.machine.next_action(screen)

    # ---- 公共主循环 ----

    def _dry_run(self) -> int:
        screen = self.runtime.capture()
        try:
            action = self.machine.next_action(screen)
        except RuntimeError as error:
            diagnostic = self.runtime.save_diagnostic(
                f"dry_run_{self.machine.state.value}", screen
            )
            raise RuntimeError(
                f"空跑未识别画面[{self._state_label(self.machine.state)}]；"
                f"已保存诊断 {diagnostic}"
            ) from error
        if action is not None:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 页面={self._state_label(self.machine.state)} "
                f"动作={action.name} 状态=诊断"
            )
            self.runtime.click(action.point, action.name)
        return self.machine.completed_cycles

    def _reset_action_tracking(self) -> tuple[Optional[str], Optional[float], bool, int]:
        return None, None, False, 0

    def run(self, max_cycles: Optional[int] = None) -> int:
        if self.runtime.dry_run:
            return self._dry_run()

        self._recovered = False
        state_started = self.now()
        absolute_started = state_started
        stable = StableObservation(required=2)
        consecutive_waiting = 0
        last_action_name: Optional[str] = None
        last_action_clicked_at: Optional[float] = None
        last_transition_action: Any = None
        last_progress_at: float = self.now()  # 任意新动作发出即刷新
        retry_wait_logged = False
        action_attempts = 0
        black_started: Optional[float] = None
        last_black_log_at: Optional[float] = None
        # 动作循环检测：只统计上一次已确认转场之后发出的动作。
        recent_actions: list[str] = []

        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            state_before = self.machine.state
            cycles_before = self.machine.completed_cycles
            screen = self.runtime.capture()
            if self.runtime.diagnostic_dir is not None:
                self.runtime.save_current_frame(screen)

            black_timeout = self._BLACK_SCREEN_TIMEOUT_SECONDS
            if black_timeout is not None and self._is_black_screen(screen):
                current = self.now()
                if black_started is None:
                    black_started = current
                    last_black_log_at = current
                    last_confirmed_page = (
                        getattr(self.machine, "_confirmed_page", "")
                        or self._state_label(self.machine.state)
                    )
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} "
                        f"最后确认页面={last_confirmed_page} "
                        f"黑屏=等待画面恢复 最长等待={black_timeout:.0f}秒"
                    )
                elapsed = current - black_started
                if elapsed >= black_timeout:
                    diagnostic = self.runtime.save_diagnostic(
                        "black_screen_timeout", screen
                    )
                    message = (
                        f"黑屏时间过长（{black_timeout:.0f}秒），程序已安全停止；"
                        f"已保存诊断 {diagnostic}"
                    )
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 停止=黑屏时间过长 "
                        f"已等待={elapsed:.0f}秒"
                    )
                    raise RuntimeError(message)
                if (
                    last_black_log_at is not None
                    and current - last_black_log_at
                    >= self._BLACK_SCREEN_LOG_INTERVAL_SECONDS
                ):
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 黑屏=继续等待 "
                        f"已等待={elapsed:.0f}秒/{black_timeout:.0f}秒"
                    )
                    last_black_log_at = current
                stable.reset()
                self.sleep(self.poll_seconds)
                continue

            if black_started is not None:
                black_duration = self.now() - black_started
                state_started += black_duration
                absolute_started += black_duration
                if last_action_clicked_at is not None:
                    last_action_clicked_at += black_duration
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 黑屏已恢复 "
                    f"持续={black_duration:.0f}秒 重新识别当前页面"
                )
                black_started = None
                last_black_log_at = None

            # 动作循环检测：最近 15 次只发出 next_card 一种动作，
            # 但状态和 cycle 都没推进 → 切卡动画中同位置反复点击，
            # 触发回收（受主循环 4 次 retry 机制覆盖不到的场景）。
            if (
                not self._recovered
                and len(recent_actions) >= 15
                and len(set(recent_actions[-15:])) == 1
                and recent_actions[-1] == "next_card"
                and self.recovery is not None
                and self.now() - state_started >= 30.0
            ):
                self._recovered = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} "
                    f"页面={self._state_label(self.machine.state)} "
                    f"循环检测=最近 15 次均为 {recent_actions[-1]} 且 30 秒未推进，"
                    "回大厅重新导航"
                )
                diagnostic = None
                if self.runtime.diagnostic_dir is not None:
                    diagnostic = self.runtime.save_diagnostic(
                        f"loop_{recent_actions[-1]}", screen
                    )
                self.recovery()
                self._apply_recovery_state()
                state_started = self.now()
                absolute_started = state_started
                last_action_name = None
                last_action_clicked_at = None
                last_transition_action = None
                retry_wait_logged = False
                action_attempts = 0
                stable.reset()
                recent_actions.clear()
                continue
            try:
                action = self._stable_next_action(screen, stable)
            except StaminaExhausted as error:
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 停止=生命之叶耗尽 详情={error}"
                )
                return self.machine.completed_cycles
            except RuntimeError as error:
                if (
                    isinstance(error, UnrecognizedScreen)
                    and self._ALLOW_UNKNOWN_SCREEN_WAKE
                ):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"{self._MODE_LABEL}:{self._state_label(self.machine.state)}",
                    )
                    if wake_result is UnknownWakeResult.CLICKED:
                        consecutive_waiting = 0
                        state_started = self.now()
                        self.sleep(self.poll_seconds)
                        continue
                    if wake_result is UnknownWakeResult.WAITING:
                        consecutive_waiting += 1
                        # 首次 WAITING 仅记录基准帧；连续等待（画面持续变化，
                        # 唤醒点击无法触发）超过状态超时则落入下方恢复/熔断
                        if consecutive_waiting == 1 or (
                            self.now() - state_started
                            < self._timeout_for(self.machine.state)
                        ):
                            self.sleep(self.poll_seconds)
                            continue
                    # 静态画面唤醒耗尽（EXHAUSTED）等情形：落入下方状态超时处理
                elapsed = self.now() - state_started
                if elapsed >= self._timeout_for(self.machine.state):
                    if self.recovery is not None and not self._recovered:
                        self._recovered = True
                        self.runtime.log(
                            f"模式={self._MODE_LABEL} "
                            f"页面={self._state_label(self.machine.state)} "
                            "恢复=回大厅重新导航"
                        )
                        self.recovery()
                        self._apply_recovery_state()
                        state_started = self.now()
                        absolute_started = state_started
                        last_action_name = None
                        last_action_clicked_at = None
                        last_transition_action = None
                        retry_wait_logged = False
                        action_attempts = 0
                        stable.reset()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
                    )
                    self._log_state_timeout(self.machine.state, elapsed, diagnostic)
                    raise RuntimeError(
                        self._timeout_error_message(error, diagnostic)
                    ) from error
                self.sleep(self.poll_seconds)
                continue
            if action is NOT_STABLE:
                self.sleep(self.poll_seconds)
                continue
            consecutive_waiting = 0
            stable.reset()

            confirmed_page = getattr(self.machine, "_confirmed_page", "")
            if last_transition_action is not None and self._transition_completed(
                last_transition_action, action, confirmed_page
            ):
                detail = self._transition_success_detail(
                    last_transition_action, action
                )
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 完成={last_transition_action.name} "
                    f"目标页面={confirmed_page}"
                    + (f" {detail}" if detail else "")
                )
                last_transition_action = None
                recent_actions.clear()
            elif last_transition_action is not None:
                source_page = getattr(last_transition_action, "source_page", "")
                action = (
                    last_transition_action
                    if source_page
                    and confirmed_page == source_page
                    and self._source_observation_matches(
                        last_transition_action, action
                    )
                    else None
                )

            if self._check_cycle_completed(cycles_before, max_cycles):
                return self.machine.completed_cycles
            state_started = self.now() if self.machine.completed_cycles > cycles_before else state_started

            # 入口一：无动作但停在战斗态（狗粮 BATTLE）→ 直接移交战斗监督
            if action is None and self._SETTLED_BATTLE_STATE is not None and self.machine.state == self._SETTLED_BATTLE_STATE:
                self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
                state_started = absolute_started = self.now()
                last_action_name = None
                last_action_clicked_at = None
                last_transition_action = None
                retry_wait_logged = False
                action_attempts = 0
                stable.reset()
                continue

            # 入口二：不点击直接移交战斗监督（狗粮 start_battle 由监督代点）
            if (
                action is not None
                and not self._CLICK_BEFORE_BATTLE
                and action.name == self._BATTLE_ENTRY_ACTION
            ):
                self._on_battle_entry(action, state_before, max_cycles)
                self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
                state_started = absolute_started = self.now()
                last_action_name = None
                last_action_clicked_at = None
                last_transition_action = None
                retry_wait_logged = False
                action_attempts = 0
                stable.reset()
                continue

            if action is not None:
                if action.name == last_action_name:
                    since_click = (
                        self.now() - last_action_clicked_at
                        if last_action_clicked_at is not None
                        else self._action_retry_seconds(action.name)
                    )
                    retry_seconds = self._action_retry_seconds(action.name)
                    if since_click < retry_seconds:
                        if not retry_wait_logged:
                            remaining = retry_seconds - since_click
                            target_pages = getattr(action, "target_pages", ())
                            target_text = (
                                f" 目标页面={'/'.join(target_pages)}"
                                if target_pages
                                else ""
                            )
                            self.runtime.log(
                                f"模式={self._MODE_LABEL} "
                                f"轮次={self.machine.completed_cycles + 1}/"
                                f"{max_cycles or '?'} 动作={action.name} "
                                f"等待=点击后确认转场{target_text} "
                                f"剩余={remaining:.1f}秒"
                            )
                            retry_wait_logged = True
                        self.sleep(self.poll_seconds)
                        continue
                    action_attempts += 1
                else:
                    last_action_name = action.name
                    action_attempts = 1

                if action_attempts > 4:
                    if self._on_action_exhausted(action, screen):
                        return self.machine.completed_cycles
                    if self.recovery is not None and not self._recovered:
                        self._recovered = True
                        self.runtime.log(
                            f"模式={self._MODE_LABEL} 动作={action.name} "
                            "恢复=四次点击未转场，回大厅重新导航"
                        )
                        self.recovery()
                        self._apply_recovery_state()
                        state_started = self.now()
                        absolute_started = state_started
                        last_action_name = None
                        last_action_clicked_at = None
                        last_transition_action = None
                        retry_wait_logged = False
                        action_attempts = 0
                        stable.reset()
                        recent_actions.clear()
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"retry_exhausted_{action.name}", screen
                    )
                    raise RuntimeError(
                        f"动作 {action.name} 点击4次后画面未推进；已保存诊断 {diagnostic}"
                    )

                self.runtime.log(
                    f"模式={self._MODE_LABEL} "
                    f"轮次={self.machine.completed_cycles + 1}/{max_cycles or '?'} "
                    f"页面={self._state_label(state_before)} "
                    f"动作={action.name} 尝试={action_attempts}/4"
                )
                source_page = getattr(action, "source_page", "")
                target_pages = getattr(action, "target_pages", ())
                reason = getattr(action, "reason", "")
                if source_page:
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 当前页面={source_page} "
                        f"判断依据={reason}"
                    )
                if target_pages:
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 操作={action.name} "
                        f"坐标={action.point} 目标页面={'/'.join(target_pages)}"
                    )
                if action_attempts > 1 and source_page:
                    retry_reason = self._transition_retry_reason(
                        last_transition_action, action
                    )
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 重试={action.name} "
                        f"原因={retry_reason} "
                        f"尝试={action_attempts}/4"
                    )
                # 子模式进度提示：让外部能从日志看到当前决策原因
                decision_hint = self._decision_hint(action.name, state_before)
                if decision_hint:
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 决策={decision_hint}"
                    )
                self.runtime.click(action.point, action.name)
                self._after_action_click(action)
                last_transition_action = action if target_pages else None
                last_action_clicked_at = self.now()
                state_started = last_action_clicked_at
                absolute_started = last_action_clicked_at
                retry_wait_logged = False
                # 记录最近动作（仅记动作前缀，去掉指纹尾缀避免 next_card_4/5 看作不同）
                name_prefix = action.name.rsplit("_", 1)[0] if action.name.startswith("next_card") else action.name
                recent_actions.append(name_prefix)
                if len(recent_actions) > 20:
                    recent_actions.pop(0)

                # 入口三：点击后移交战斗监控（主线 start_mission / 辅助自动 start_battle）
                if self._CLICK_BEFORE_BATTLE and action.name == self._BATTLE_ENTRY_ACTION:
                    self._run_committed_battle(cycle=self.machine.completed_cycles + 1)
                    if self._after_battle(max_cycles):
                        return self.machine.completed_cycles
                    state_started = self.now()
                    absolute_started = state_started
                    last_action_name = None
                    last_action_clicked_at = None
                    last_transition_action = None
                    retry_wait_logged = False
                    action_attempts = 0
                    stable.reset()
                    continue
            else:
                # 有目标契约的动作遇到短暂未知帧时保留同一重试账本；
                # 只有目标已确认（上方已清空契约）或普通无动作状态才重置。
                if last_transition_action is None:
                    last_action_name = None
                    last_action_clicked_at = None
                    retry_wait_logged = False
                    action_attempts = 0

            if (
                action is None
                and self.now() - state_started >= self._timeout_for(self.machine.state)
            ):
                diagnostic = self.runtime.save_diagnostic(
                    f"timeout_{self.machine.state.value}", screen
                )
                self._log_settled_timeout(self.machine.state, diagnostic)
                raise RuntimeError(
                    f"等待画面[{self._state_label(self.machine.state)}]超时无进展；"
                    f"已安全停止并保存诊断 {diagnostic}"
                )

            if self.machine.state != state_before:
                state_started = self.now()
                absolute_started = state_started
            if (
                self._ABSOLUTE_TIMEOUT_SECONDS is not None
                and self.now() - absolute_started >= self._ABSOLUTE_TIMEOUT_SECONDS
            ):
                diagnostic = self.runtime.save_diagnostic(
                    f"absolute_{self.machine.state.value}", screen
                )
                raise RuntimeError(
                    f"页面[{self._state_label(self.machine.state)}]绝对超时；"
                    f"已安全停止并保存诊断 {diagnostic}"
                )
            self.sleep(self.poll_seconds)

        return self.machine.completed_cycles
