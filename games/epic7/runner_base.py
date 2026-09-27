"""story/fodder 两条同构线的公共 Runner 骨架。

主循环协议在此统一实现：
- 空跑短路（单帧诊断）
- 两帧稳定确认 + 同动作 45 秒转场等待 + 4 次点击上限
- 上限用尽 → 给路线**一次**原地「换个办法」的机会（``_self_heal_used``）；
  换回来的还是同一个动作就直接安全停止
- 未知画面唤醒（UnknownScreenWake）
- 唤醒持续 WAITING（画面变化无法触发唤醒点击）同样受状态超时约束
- 状态超时 / 循环检测 → **直接安全停止**（回家由 ``main`` 收尾）
  ⚠️ 2026-09-26 用户拍板：回家就是结束，程序**不会**再回家重新导航接着跑
  —— 原先那套 ``recovery()``（回大厅重开）已整段删除，见 ``run()`` 里的注释。
- 结算等待超时与绝对超时熔断
各模式仅通过钩子注入差异（战斗移交方式、超时表等）。
"""

from time import sleep as default_sleep
from typing import Any, Callable, Optional

from auto_game_unified.core.battle_supervisor import BattleOutcome
from auto_game_unified.core.evidence_diagnostics import (
    save_runtime_evidence_diagnostic,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, ResourceExhausted, Runtime
from auto_game_unified.core.supervisor import ConclusionGate, StableObservation
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
    # True=每个动作必须声明「来源 + 去处/页内证据」，缺声明直接拒绝发出。
    # 默认 False：现有路线行为完全不变。新路线子类打开，见
    # docs/TRANSITION_CONTRACTS.md「新路线准入（强制）」。
    _REQUIRE_TRANSITION_CONTRACT = False
    # 「收尾回首页」钩子：由 main.run_mode 在 runner.run() 正常返回后注入。
    #
    # ⚠️ 为什么走注入而不是让 Runner 自己 import 导航器：Runner 只认识状态机与
    # Runtime，导航器由 main 装配（`Epic7Navigator` 不在 runner 的依赖里）。
    # 而且干跑根本没有导航器 —— 注入让它天然为 None，省掉一堆 dry_run 特判。
    #
    # 契约：**绝不抛异常**。收尾回首页失败不该改变退出码（任务本身已经成功了），
    # 失败时实现方自己记日志、返回失败原因字符串；成功返回 None。
    # 这条契约由 main.run_mode 装配的那份实现守住，见 main._finish_at_home。
    _finish_home: Optional[Callable[[], Optional[str]]] = None

    def __init__(
        self,
        machine: Any,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        recovery_gate: RecoveryGate | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.now = runtime.now
        self.poll_seconds = poll_seconds
        # ⚠️ 这个闸门现在**只有一个职责**：已承诺战斗期间禁止打断（见
        # ``core.recovery`` 的模块 docstring）。「回大厅恢复」那条通道
        # 2026-09-26 已整段删除（用户拍板「回家就是结束」）。
        self.recovery_gate = recovery_gate or RecoveryGate()
        self.unknown_screen_wake = UnknownScreenWake(
            runtime, recovery_gate=self.recovery_gate
        )
        self.resource_exhausted = False
        # 「下结论」的门槛：收工 / 认不出画面这类终止性结论同样要连续两帧一致，
        # 否则一帧就能结束整条路线（详见 core.supervisor.ConclusionGate）。
        self.conclusion_gate = ConclusionGate()

    # ---- 子类钩子（差异点） ----

    def _state_label(self, state: Any) -> str:
        return str(getattr(state, "value", state))

    def _timeout_for(self, state: Any) -> float:
        return self._TIMEOUT_SECONDS[state]

    def _after_action_click(self, action: Any) -> None:
        """Optional short observation immediately after an action click."""

    def _run_committed_battle(self, *, cycle: int) -> Optional[Any]:
        """移交战斗监督并返回其结果（``BattleOutcome``）。

        主循环需要看结果：``PRE_BATTLE_BUSINESS`` 表示战斗没打起来（战前业务弹窗），
        要走 ``_on_battle_handoff_failed`` 的有界重试，而不是当作「已进入战斗」。
        """
        raise NotImplementedError

    def _on_battle_entry(self, action: Any, state_before: Any, max_cycles: Optional[int]) -> None:
        """战斗移交前的日志等特判（狗粮的“交由战斗监督”日志）。"""

    def _on_battle_handoff_failed(self, action: Any, screen) -> bool:
        """点了「战斗开始」但战斗没开起来时的处理；返回 True 表示已优雅收尾。

        默认直接抛错（安全停止）。子模式可以做成**有界重试** —— 打不起来往往是
        缺资源（体力不足）这类可恢复场景，重试一次比直接失败合理，但绝不能无限重试。
        """
        raise RuntimeError(f"动作 {getattr(action, 'name', '')} 未能进入战斗")

    def _after_battle(self, max_cycles: Optional[int]) -> bool:
        """战斗监控返回后的特判；返回 True 表示应立即结束 run()。"""
        return False

    def _on_battle_started(self) -> None:
        """战斗确实开起来了（监督正常返回结算）：子模式可在此重置重试账本。"""

    def _on_action_exhausted(self, action: Any, screen) -> bool:
        """动作重试 2 次仍无进展时的特判；返回 True 表示已优雅收尾。"""
        return False

    def _check_cycle_completed(self, cycles_before: int, max_cycles: Optional[int]) -> bool:
        """完成一轮后的日志与 max_cycles 提前返回；返回 True 表示结束 run()。"""
        if self.machine.completed_cycles > cycles_before:
            # 真的完成了一轮业务 ⇒ 自救机会重新给一次。
            self._self_heal_used = False
            self._log_cycle_completed()
            if max_cycles is not None and self.machine.completed_cycles >= max_cycles:
                return True
        return False

    def _close_out(self) -> None:
        """收尾回首页。

        ⚠️ **只挂在「正常跑完」这一条路上** —— 下面 ``run()`` 里四处 return 前面
        统一调用它。三类出口**刻意不接**：

        - **``ManualStop``（退出码 130）**：用户喊停，这时候再动游戏是添乱。
        - **异常退出（退出码 1）**：跑到一半挂了，硬按 Back 可能把已承诺的战斗
          弄丢（尤其 world_boss 停在局内时）。安全 > 整齐。
        - **``ResourceExhausted``（退出码 2）**：这是「还能干、但没本钱了」的
          **正常业务退出**，所以**接**（停在购买弹窗/次数用完页上都该回家）。

        ⚠️ 收尾失败**绝不改退出码**：任务本身已经成功了，不能因为「没走回家」
        就报失败。失败由 ``_finish_home`` 实现方记日志并返回原因，这里只记账。
        """
        if self._finish_home is None:
            return
        failure = self._finish_home()
        if failure is not None:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=回首页失败 "
                f"原因={failure} 处理=已忽略（不影响本次运行结论）"
            )

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

    def _save_failure_diagnostic(
        self,
        legacy_path,
        screen,
        *,
        action: Any = None,
        attempt: int = 1,
        conclusion: str,
    ):
        templates = getattr(self.machine, "templates", None)
        profile = getattr(templates, "evidence", None)
        return save_runtime_evidence_diagnostic(
            self.runtime,
            screen,
            profile,
            legacy_path=legacy_path,
            mode=self._MODE_LABEL,
            action=getattr(action, "name", "") or "observe",
            source=(
                getattr(action, "source_page", "")
                or self._state_label(self.machine.state)
            ),
            targets=getattr(action, "target_pages", ()),
            attempt=attempt,
            conclusion=conclusion,
        )

    def _log_state_timeout(self, state: Any, elapsed: float, diagnostic) -> None:
        """状态超时抛错前的补充日志（主线有，其余默认无）。"""

    def _log_settled_timeout(self, state: Any, diagnostic) -> None:
        """结算等待超时抛错前的补充日志（主线有，其余默认无）。"""

    def _log_transition_timeout(
        self, action: Any, screen: Any, confirmed_page: str, diagnostic: Any
    ) -> None:
        """带目标契约的动作超时时，记录实际等待的页面而非内部旧状态。"""
        targets = "/".join(getattr(action, "target_pages", ())) or "未声明"
        self.runtime.log(
            f"模式={self._MODE_LABEL} 转场超时 动作={action.name} "
            f"原页面={getattr(action, 'source_page', '') or '未声明'} "
            f"期望页面={targets} 当前已确认页面={confirmed_page or '无'} "
            f"内部状态={self._state_label(self.machine.state)} 诊断={diagnostic}"
        )

    def _reset_observation(self, stable: StableObservation) -> None:
        """换页 / 恢复 / 黑屏后同时清空「动作」与「结论」两本账。

        只清一本会留下隐患：页面都换了，上一页那个「打完了」的结论还挂在门槛上，
        下一帧再来一次同样的结论就直接凑够两帧 —— 那是**两个不同页面**各看了一帧，
        不是同一页连看两帧。
        """

        stable.reset()
        self.conclusion_gate.reset()

    def _stable_next_action(self, screen, stable: StableObservation):
        """两帧稳定确认后返回 next_action；未稳定时返回 NOT_STABLE。

        ⚠️ **结论也要过这道门槛**。``preview`` 里抛出的终止性异常（收工 / 认不出
        画面）过去是直接穿到主循环的 —— 动作要两帧、结论只要一帧，一帧就能宣布
        整条路线结束。这里先把结论变成签名交给门槛，两帧一致才允许穿出去。
        规矩见 docs/TRANSITION_CONTRACTS.md「结论门槛（全局强制）」。
        """
        try:
            preview_action, outcome = self.machine.preview(screen)
        except ManualStop:
            # 用户按了停止键：不是程序下的结论，不受门槛约束。
            raise
        except RuntimeError as error:
            if not self.conclusion_gate.admit(error):
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 结论待确认={type(error).__name__} "
                    f"依据=需连续两帧一致才采信 详情={error}"
                )
                return NOT_STABLE
            raise
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
                self._reset_observation(stable)
                return NOT_STABLE
            self.runtime.click(committed_action.point, committed_action.name)
            self._reset_observation(stable)
            # 状态由真正 next_action 提交；下一帧重新观察点击结果。
            return NOT_STABLE
        if not stable.update(signature):
            return NOT_STABLE
        return self.machine.next_action(screen)

    def _require_transition_contract(self, action: Any) -> None:
        """新路线准入：``_REQUIRE_TRANSITION_CONTRACT`` 打开时，动作必须带出口验收。

        换页动作声明 ``target_pages``；不换页动作声明 ``in_page_evidence``（页内验收依据）。
        两者皆空 = 这个动作点完不回头看 = 没长眼睛，直接失败关闭（空跑同样会拦）。
        """
        if not self._REQUIRE_TRANSITION_CONTRACT:
            return
        source_page = getattr(action, "source_page", "")
        target_pages = getattr(action, "target_pages", ())
        in_page_evidence = getattr(action, "in_page_evidence", "")
        missing = []
        if not source_page:
            missing.append("source_page（从哪来）")
        if not target_pages and not in_page_evidence:
            missing.append("target_pages（到哪去）或 in_page_evidence（页内验收依据）")
        if missing:
            raise RuntimeError(
                f"动作[{getattr(action, 'name', '')}]缺少转场契约：{'、'.join(missing)}；"
                "请按 docs/TRANSITION_CONTRACTS.md 的契约模板补齐后再运行"
            )

    # ---- 公共主循环 ----

    def _dry_run(self) -> int:
        # 空跑只跑一帧，但**结论不能只看一帧**：撞上终止性结论就再截一帧复核，
        # 两帧一致才采信（规矩同实跑，见 core.supervisor.ConclusionGate）。
        screen = self.runtime.capture()
        action = None
        confirmed: Optional[RuntimeError] = None
        pending: Optional[RuntimeError] = None
        for _ in range(2):
            try:
                action = self.machine.next_action(screen)
                break
            except ManualStop:
                # 空跑也必须能被 P 键/界面停止打断，且不能被下面那条「包装成运行失败」
                # 的分支吞掉（ManualStop 是 RuntimeError 的子类）。
                raise
            except RuntimeError as error:
                pending = error
                if self.conclusion_gate.admit(error):
                    confirmed = error
                    break
                screen = self.runtime.capture()
        if confirmed is None and pending is not None:
            # 两帧结论不一致（多半正卡在转场动画里）：不拿任何一帧下结论，
            # 按「没认出来」报出去，让用户自己看诊断图。
            confirmed = pending
        if confirmed is not None:
            if isinstance(confirmed, ResourceExhausted):
                # 空跑碰上「没本钱了」也是一个正常结论，别被下面那条包装成
                # 「空跑未识别画面」—— 空跑本来就是给用户先看一眼用的，
                # 报「认不出这一页」会把人往错的方向带。
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 空跑 停止={confirmed.stop_label} "
                    f"详情={confirmed}"
                )
                return self.machine.completed_cycles
            diagnostic = self.runtime.save_diagnostic(
                f"dry_run_{self.machine.state.value}", screen
            )
            self._save_failure_diagnostic(
                diagnostic,
                screen,
                conclusion=f"空跑未识别画面：{confirmed}",
            )
            raise RuntimeError(
                f"空跑未识别画面[{self._state_label(self.machine.state)}]；"
                f"已保存诊断 {diagnostic}"
            ) from confirmed
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

        # 「路线自己换个办法」的机会，一条路线一轮只用一次（用完就结束，不再原地打转）。
        self._self_heal_used = False
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
                    self._save_failure_diagnostic(
                        diagnostic,
                        screen,
                        conclusion="黑屏超过允许时间",
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
                self._reset_observation(stable)
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
                len(recent_actions) >= 15
                and len(set(recent_actions[-15:])) == 1
                and recent_actions[-1] == "next_card"
                and self.now() - state_started >= 30.0
            ):
                # 卡在同一个动作上原地打转 ⇒ **结束这条路线**（回家由 main 收尾）。
                #
                # ⚠️ 2026-09-26：以前这里是「回大厅重新导航、然后接着跑」，
                # 用户拍板「回家就是结束，不可能再回来」。
                diagnostic = None
                if self.runtime.diagnostic_dir is not None:
                    diagnostic = self.runtime.save_diagnostic(
                        f"loop_{recent_actions[-1]}", screen
                    )
                self._save_failure_diagnostic(
                    diagnostic,
                    screen,
                    conclusion=f"最近 15 次均为 {recent_actions[-1]}，30 秒未推进",
                )
                self.runtime.log(
                    f"模式={self._MODE_LABEL} "
                    f"页面={self._state_label(self.machine.state)} "
                    f"停止=循环检测（最近 15 次均为 {recent_actions[-1]}，"
                    f"30 秒未推进）现场={diagnostic}"
                )
                raise RuntimeError(
                    f"动作 {recent_actions[-1]} 连续 15 次、30 秒未推进；"
                    f"已保存诊断 {diagnostic}"
                )
            try:
                action = self._stable_next_action(screen, stable)
            except ResourceExhausted as error:
                # 「还能干、但没本钱了」：生命之叶 / 通缉传单 / 挑战次数……
                # 各路线缺的东西不一样，所以「停止=」后面的文案由异常自己带
                # （``stop_label``），这里不写死 —— 日志要能一眼看出缺的是什么。
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 停止={error.stop_label} "
                    f"已完成={self.machine.completed_cycles} 详情={error}"
                )
                self._close_out()
                return self.machine.completed_cycles
            except ManualStop:
                # ⚠️ 必须排在 `except RuntimeError` 前面。`ManualStop` 是 `RuntimeError`
                # 的子类，掉进下面那条分支会被当成「页面没认出来」，只 sleep 一轮就
                # continue —— 主循环回头再 `capture()` 又抛一次，于是按轮询频率刷
                # 「用户按下 P / 已保存诊断」并每秒写一张全屏截图，一直磨到该状态的
                # 超时才停（竞技场列表页 40 秒，战斗监督里最长 900 秒）。
                # 表现就是「用户按了停止，程序却像卡在诊断循环里」。
                raise
            except RuntimeError as error:
                if (
                    isinstance(error, UnrecognizedScreen)
                    and self._ALLOW_UNKNOWN_SCREEN_WAKE
                ):
                    wake_result = self.unknown_screen_wake.handle(
                        screen,
                        context=f"{self._MODE_LABEL}:{self._state_label(self.machine.state)}",
                    )
                    if wake_result is UnknownWakeResult.WAITING:
                        consecutive_waiting += 1
                        # 首次 WAITING 仅记录基准帧；连续等待（画面持续变化，
                        # 认不出是哪一页）超过状态超时则落入下方超时收尾
                        if consecutive_waiting == 1 or (
                            self.now() - state_started
                            < self._timeout_for(self.machine.state)
                        ):
                            self.sleep(self.poll_seconds)
                            continue
                    # 静态画面唤醒耗尽（EXHAUSTED）等情形：落入下方状态超时处理
                elapsed = self.now() - state_started
                if elapsed >= self._timeout_for(self.machine.state):
                    # 认不出这一页、等到超时 ⇒ **结束这条路线**（回家由 main 收尾）。
                    #
                    # ⚠️ 2026-09-26：以前这里是「回大厅重新导航、然后接着跑」，
                    # 用户拍板「回家就是结束，不可能再回来」。
                    diagnostic = self.runtime.save_diagnostic(
                        f"timeout_{self.machine.state.value}", screen
                    )
                    self._save_failure_diagnostic(
                        diagnostic,
                        screen,
                        conclusion=f"页面识别超时：{error}",
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
            self._reset_observation(stable)

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
                self._close_out()
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
                self._reset_observation(stable)
                continue

            # 新路线准入：开了强制开关的路线，动作必须「长眼睛」才允许发出。
            # 放在两个战斗入口之前，任何分支发出的动作都会被拦到。
            if action is not None:
                self._require_transition_contract(action)

            # 入口二：**不点击**直接移交战斗监督。
            #
            # 只有 ``_CLICK_BEFORE_BATTLE=False`` 的模式走这里：它让战斗监督
            # 自己去点开战按钮（狗粮 ``start_battle``）。
            #
            # ⚠️ 别把「我看到战斗画面了」这种**观察动作**做成移交入口。
            # 2026-09-22 试过一次，后果是控制权在**战斗已经开打之后**才交给监督，
            # 而监督要靠「结算页出现」才能正常退出 —— 战斗画面这一帧根本看不到
            # 结算页，于是只能一路磨到绝对超时。正确做法是「点开战按钮时移交」
            # （入口三），战斗画面只作为那个动作的**转场验收依据**。
            if (
                action is not None
                and not self._CLICK_BEFORE_BATTLE
                and action.name == self._BATTLE_ENTRY_ACTION
            ):
                self._on_battle_entry(action, state_before, max_cycles)
                outcome = self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1
                )
                if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
                    # 战斗没开起来：有界重试，绝不无限重交（同入口三）。
                    if self._on_battle_handoff_failed(action, screen):
                        self._close_out()
                        return self.machine.completed_cycles
                else:
                    self._on_battle_started()
                    if self._after_battle(max_cycles):
                        self._close_out()
                        return self.machine.completed_cycles
                state_started = absolute_started = self.now()
                last_action_name = None
                last_action_clicked_at = None
                last_transition_action = None
                retry_wait_logged = False
                action_attempts = 0
                self._reset_observation(stable)
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
                        self._close_out()
                        return self.machine.completed_cycles
                    if not self._self_heal_used:
                        # 路线说自己还有别的办法（例：捐赠支援这一节收工了 ⇒
                        # **原地**切去每周任务）⇒ 不再回大厅重来，让它用新的判据
                        # 重新决策一次。
                        #
                        # ⚠️ 2026-09-26 用户拍板：回家就是结束，「回大厅重新导航
                        # 然后接着跑」这套要删掉 —— 实跑里它表现为「又从头做了一遍」。
                        # ⚠️ 只给**一次**机会：再来一次同样的耗尽就直接结束，
                        # 否则会在原地无限打转。完成一轮业务后机会重置。
                        self._self_heal_used = True
                        self.runtime.log(
                            f"模式={self._MODE_LABEL} 动作={action.name} "
                            "四次点击未转场 ⇒ 交给路线自己换个办法（不回大厅重来），仅此一次"
                        )
                        state_started = self.now()
                        absolute_started = state_started
                        last_transition_action = None
                        retry_wait_logged = False
                        self._reset_observation(stable)
                        recent_actions.clear()
                        # ⚠️ **动作账本刻意不重置**（``last_action_name`` /
                        # ``last_action_clicked_at`` / ``action_attempts``）：
                        # 自救多给的是「**换个办法**」的机会，不是「再点 4 次」的预算。
                        #   ① 换成别的动作 ⇒ ``action.name == last_action_name`` 不成立，
                        #      主循环按新动作自然开一本新账（``action_attempts`` 归 1）、
                        #      照常点，一次不少；
                        #   ② 换回来还是同一个动作 ⇒ 它并没有别的办法，账本仍是
                        #      「已耗尽」⇒ 下一帧直接收手，**一次都不多点**。
                        # 这里若跟着清零，同一个动作会被再点 4 次（实测 4 → 8 次点击，
                        # story 那档每点白等 45 秒转场 ⇒ 多耗约 3 分钟），
                        # 而「4 次之后退回出来」是用户 2026-09-26 明确的口径。
                        continue
                    diagnostic = self.runtime.save_diagnostic(
                        f"retry_exhausted_{action.name}", screen
                    )
                    self._save_failure_diagnostic(
                        diagnostic,
                        screen,
                        action=action,
                        attempt=action_attempts,
                        conclusion="来源页面持续存在，点击四次仍未进入目标页面",
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

                # 入口三：点击后移交战斗监控（例如主线 start_mission）
                if self._CLICK_BEFORE_BATTLE and action.name == self._BATTLE_ENTRY_ACTION:
                    outcome = self._run_committed_battle(
                        cycle=self.machine.completed_cycles + 1
                    )
                    if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
                        # 打不起来（例如体力不足）：**有界重试**，绝不无限重交。
                        # 子模式返回 True 表示已优雅收尾（自己 try 了恢复 / 记了日志）。
                        if self._on_battle_handoff_failed(action, screen):
                            self._close_out()
                            return self.machine.completed_cycles
                        state_started = self.now()
                        absolute_started = state_started
                        last_action_name = None
                        last_action_clicked_at = None
                        last_transition_action = None
                        retry_wait_logged = False
                        action_attempts = 0
                        self._reset_observation(stable)
                        continue
                    self._on_battle_started()
                    if self._after_battle(max_cycles):
                        self._close_out()
                        return self.machine.completed_cycles
                    state_started = self.now()
                    absolute_started = state_started
                    last_action_name = None
                    last_action_clicked_at = None
                    last_transition_action = None
                    retry_wait_logged = False
                    action_attempts = 0
                    self._reset_observation(stable)
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
                timeout_label = (
                    f"transition_{last_transition_action.name}"
                    if last_transition_action is not None
                    else self.machine.state.value
                )
                diagnostic = self.runtime.save_diagnostic(
                    f"timeout_{timeout_label}", screen
                )
                self._save_failure_diagnostic(
                    diagnostic,
                    screen,
                    action=last_transition_action,
                    attempt=action_attempts,
                    conclusion=(
                        "目标页面未出现"
                        if last_transition_action is not None
                        else "当前页面无动作且等待超时"
                    ),
                )
                if last_transition_action is not None:
                    targets = "/".join(last_transition_action.target_pages)
                    self._log_transition_timeout(
                        last_transition_action,
                        screen,
                        confirmed_page,
                        diagnostic,
                    )
                    raise RuntimeError(
                        f"等待动作[{last_transition_action.name}]"
                        f"目标画面[{targets}]超时；"
                        f"已安全停止并保存诊断 {diagnostic}"
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
                self._save_failure_diagnostic(
                    diagnostic,
                    screen,
                    action=last_transition_action,
                    attempt=action_attempts,
                    conclusion="页面停留超过绝对超时",
                )
                raise RuntimeError(
                    f"页面[{self._state_label(self.machine.state)}]绝对超时；"
                    f"已安全停止并保存诊断 {diagnostic}"
                )
            self.sleep(self.poll_seconds)

        # while 条件自然结束（跑满 max_cycles）—— 同属「正常跑完」，照收尾。
        self._close_out()
        return self.machine.completed_cycles
