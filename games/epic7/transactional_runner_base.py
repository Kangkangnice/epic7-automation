"""「事务型主循环」的公共骨架（``arena`` / ``expedition`` 这一族）。

与 ``runner_base.ModeRunnerBase`` 的差别是**两种模型**，不是「同一个东西抄了两遍」：

- ``ModeRunnerBase``（story / fodder / hero_synthesis / world_boss / knights_donation /
  迷宫强化石）：点一次 → **每帧重新问状态机**「现在该点哪」→ 同一个动作要等满
  ``_ACTION_RETRY_SECONDS`` 秒才允许再点（上限 4 次）→ 靠
  ``machine._confirmed_page ∈ action.target_pages`` 判「转场完成」。
- **本基类**：点一次 → 每隔一拍看一眼 → **目标页面连续两帧**出现才
  ``machine.commit()`` → 源页面还在就再点（上限 4 次）→ 可选「画面长时间没变化
  就收手存档」。

为什么要有这一族、而不是把两条并进 ``ModeRunnerBase``（2026-09-26 评估结论）：
两条路线的状态机是 ``state-driven`` —— ``self.state`` 只在显式 ``commit()`` 里前进，
主循环不调 ``commit()`` 就一步都走不动；而且它们对「转场成功」的定义（目标页连续两帧）
与基类（动作签名两帧 + 页面名对账）不同，那套定义是有实测用例守着的
（``tests/test_arena_runner.py`` 15 条）。硬并会换掉一整批判据。

⚠️ 2026-09-26 之前，竞技场与远征**各抄了一份**这套东西（约 750 行重复），
且已经开始各改各的（超时口径 40/40/60/60/120/45 对 45 秒一刀切、
失败诊断一个叫 ``_save_failure_diagnostic`` 一个叫 ``_diagnostic``）。
本文件就是把那份重复收成一处 —— 只收**两边真的一样**的东西。

路线特例仍然留在各自文件里，通过钩子注入：买票「今天买过就不点」、刷新对手后
等「含安全对手的列表」、战绩入账、收尾前关掉购买弹窗…… 见各类的覆写点。

⚠️ 与 ``ModeRunnerBase`` 的关系：**刻意不继承它**。它是另一套主循环，继承过来会
把「跳过了结论门槛」「主循环没接转场契约」两道加载期自查认反（``modes.py`` 里
``_base_conclusion_gate_protected`` / ``_assert_transition_stance_declared`` 按
``issubclass(ModeRunnerBase)`` 判定）。这一族的表态方式见
``modes.CONCLUSION_GATE_DECLARATION`` 与 ``modes.TRANSITION_EXEMPT``。
"""

from time import sleep as default_sleep
from typing import Any, Callable, Optional

import numpy as np

from auto_game_unified.core.battle_supervisor import (
    BattleConfig,
    BattleOutcome,
    BattleSupervisor,
)
from auto_game_unified.core.evidence_diagnostics import (
    save_runtime_evidence_diagnostic,
)
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, ResourceExhausted, Runtime
from auto_game_unified.core.supervisor import (
    ConclusionGate,
    StableObservation,
    meaningful_change,
)
from auto_game_unified.games.epic7.unknown_screen import (
    UnrecognizedScreen,
    UnknownScreenWake,
    UnknownWakeResult,
)


class TransactionalRunnerBase:
    """事务型 Runner 的公共主循环；子类通过钩子注入差异。"""

    # 日志用模式名（如 "远征" / "竞技场"），子类必填。
    _MODE_LABEL = ""

    # ---- 时限 ----
    # 状态超时：**单档**（远征：一个 45 秒走天下）或**分档**
    # （竞技场：按页面 40/40/60/60/120/45）。两张都给，分档表非空时优先。
    _STATE_TIMEOUT_SECONDS = 45
    _TIMEOUT_SECONDS: dict[Any, int] = {}

    # 点击后**第一帧**之前先静置多久（跳过点击后的动画帧）。
    # ``None`` = 用 ``poll_seconds``：等价于「点完先睡一轮再截第一帧」。
    _SETTLE_SECONDS: Optional[float] = None

    # ---- 战斗移交 ----
    # 状态枚举由子类填（基类不认识具体游戏的状态）。
    _BATTLE_STATE = None
    _RESULT_STATE = None
    # 无动作且停在该状态 ⇒ 直接移交战斗监督（局内接力的入口）。
    _SETTLED_BATTLE_STATE = None
    # 转场确认**落到 _BATTLE_STATE** 且动作名在此集合 ⇒ 移交战斗监督。
    _HANDOFF_AFTER_TRANSITION_ACTIONS: frozenset[str] = frozenset()

    # ---- 收尾 ----
    # 「收尾回首页」钩子：由 ``main.run_mode`` 在 ``runner.run()`` 返回前注入。
    #
    # ⚠️ 为什么走注入而不是让 Runner 自己 import 导航器：Runner 只认识状态机与
    # Runtime，导航器由 main 装配（``Epic7Navigator`` 不在 runner 的依赖里）。
    # 而且干跑根本没有导航器 —— 注入让它天然为 None，省掉一堆 dry_run 特判。
    #
    # ⚠️ 名字是 ``finish_home``（``ModeRunnerBase`` 那边叫 ``_finish_home``），
    # 这里刻意**不改名**：``main._install_finish_home`` 按名字分两路注入，
    # 改名要连着动那段「实例级 ``hasattr``」的判断，属独立一次重构，本轮没动。
    # 类属性给了默认值、``__init__`` 里再赋一次，两处都留着：
    # 前者让 ``hasattr``（实例查询）恒为真、后者保证每个实例各有一份。
    #
    # 契约：**绝不抛异常**。收尾回首页失败不该改变退出码（任务本身已经成功了），
    # 失败时实现方自己记日志、返回失败原因字符串；成功返回 None。
    finish_home: Optional[Callable[[], Optional[str]]] = None

    def __init__(
        self,
        machine: Any,
        runtime: Runtime,
        *,
        sleep: Callable[[float], None] = default_sleep,
        poll_seconds: float = 1.0,
        now: Callable[[], float] | None = None,
        recovery_gate: RecoveryGate | None = None,
        battle_supervisor: BattleSupervisor | None = None,
    ) -> None:
        self.machine = machine
        self.runtime = runtime
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.now = now or runtime.now
        # ⚠️ 这个闸门**只有**一个职责：已承诺战斗期间禁止打断（见 ``core.recovery``
        # 的模块 docstring）。「回大厅恢复」那条通道 2026-09-26 已整段删除
        # （用户拍板「回家就是结束」），所以这里不再接任何 ``recovery`` 回调。
        self.recovery_gate = recovery_gate or RecoveryGate()
        self.unknown_screen_wake = UnknownScreenWake(
            runtime, recovery_gate=self.recovery_gate
        )
        self.resource_exhausted = False
        self.finish_home = None
        self.battle_supervisor = battle_supervisor or BattleSupervisor(
            runtime,
            self.recovery_gate,
            self._battle_config(),
            now=self.now,
            sleep=sleep,
        )

    # ---- 子类钩子（差异点） ----

    def _battle_config(self) -> BattleConfig:
        """本路线的战斗看护配置（默认只有模式名，时长用 ``BattleConfig`` 的默认值）。"""
        return BattleConfig(mode=self._MODE_LABEL)

    def _state_label(self, state: Any) -> str:
        """状态 → 日志里那个中文页面名。子类通常换成自己的 ``state_label``。"""
        return str(getattr(state, "value", state))

    def _timeout_for(self, state: Any) -> float:
        if self._TIMEOUT_SECONDS:
            return self._TIMEOUT_SECONDS[state]
        return self._STATE_TIMEOUT_SECONDS

    def _transition_budget(self, action: Any) -> tuple[float, float]:
        """转场验收的两条时限：``(绝对上限, 无进展上限)``，单位秒。

        默认两档都取「当前状态超时」（远征口径：一个 45 秒走天下）。

        ⚠️ 无进展上限**不小于**绝对上限时，主循环**不做**「画面有没有在动」的跟踪
        —— 那条判据是给「分档 + 长时间转场」的路线（竞技场）准备的，默认关掉是为了
        让默认行为与抽取之前**逐帧一致**（抽取不允许顺手改行为）。
        """
        limit = self._timeout_for(self.machine.state)
        return limit, limit

    def _action_source_page(self, action: Any) -> str:
        """动作的「从哪来」—— 优先用页面名字符串，没有就用来源状态的标签。

        ⚠️ 用 ``hasattr`` 而不是 ``getattr(..., "")`` 判空：两种动作对象一个带
        ``source_page``（远征）、一个只带 ``source_state``（竞技场），
        「有字段但写着空串」与「压根没这个字段」要分开对待。
        """
        if action is None:
            return ""
        if hasattr(action, "source_page"):
            return getattr(action, "source_page", "")
        source_state = getattr(action, "source_state", None)
        return self._state_label(source_state) if source_state is not None else ""

    def _action_target_pages(self, action: Any) -> tuple[str, ...]:
        """动作的「到哪去」—— 同上，页面名优先，其次由目标状态推出。"""
        if action is None:
            return ()
        if hasattr(action, "target_pages"):
            return tuple(getattr(action, "target_pages", ()))
        return tuple(
            self._state_label(state)
            for state in getattr(action, "target_states", ())
        )

    def _transition_failure_message(
        self, action: Any, attempts: int, diagnostic: Any
    ) -> Optional[str]:
        """转场验收失败时的处置：返回文案 ⇒ 抛 ``RuntimeError``；返回 None ⇒ 不抛。

        默认抛错（远征口径：没到位就是故障，安全停止）。
        竞技场那边只记诊断不抛（它靠下一步的状态超时兜），迁移时覆写本方法返回 None。
        """
        targets = "/".join(self._action_target_pages(action))
        return (
            f"动作[{action.name}]未稳定进入[{targets}]；已保存诊断 {diagnostic}"
        )

    def _after_result_state(self, *, cycle: int) -> None:
        """战斗监督正常打到结算页、状态已拨到 ``_RESULT_STATE`` 之后（竞技场记战绩用）。"""

    # ---- 公共工具 ----

    def _save_frame(self, screen: np.ndarray) -> None:
        """诊断目录开着时，把这一帧写成 ``current.png``（实跑排查现场用）。"""
        if self.runtime.diagnostic_dir is not None:
            self.runtime.save_current_frame(screen)

    def _save_failure_diagnostic(
        self,
        label: str,
        screen: Optional[np.ndarray],
        *,
        action: Any = None,
        attempt: int = 1,
        conclusion: str = "页面识别失败",
    ) -> str:
        """落盘「诊断帧 + 证据档案」，返回诊断路径。

        ⚠️ 入参是 **label（标签）**，不是已经存好的路径 —— 落盘这一步由本方法自己做。
        历史上两条路线一个收 label（远征 ``_diagnostic``）、一个收路径
        （竞技场 ``_save_failure_diagnostic``），是同一件事的两个签名。

        未配置诊断目录时返回 ``"not-configured"`` 而不是抛错：这个返回值会被
        嵌进抛给用户的错误文案里，说清「诊断没落盘」比直接崩掉有用。
        """
        if self.runtime.diagnostic_dir is None:
            return "not-configured"
        diagnostic = self.runtime.save_diagnostic(label, screen)
        templates = getattr(self.machine, "templates", None)
        save_runtime_evidence_diagnostic(
            self.runtime,
            screen,
            getattr(templates, "evidence", None),
            legacy_path=diagnostic,
            mode=self._MODE_LABEL,
            action=getattr(action, "name", "") or "observe",
            source=(
                self._action_source_page(action)
                or self._state_label(self.machine.state)
            ),
            targets=self._action_target_pages(action),
            attempt=attempt,
            conclusion=conclusion,
        )
        return diagnostic

    def _close_out(self) -> None:
        """收尾回首页。

        ⚠️ **只挂在「正常跑完」这一条路上** —— ``run()`` 里四处 return 前面统一调用它。
        三类出口**刻意不接**：

        - **``ManualStop``（退出码 130）**：用户喊停，这时候再动游戏是添乱。
        - **异常退出（退出码 1）**：跑到一半挂了，硬按 Back 可能把已承诺的战斗弄丢。
          安全 > 整齐。
        - 干跑（``runtime.dry_run``）：``run()`` 在**调用本方法之前**就 return 了
          （只观察一帧的诊断路径，不点任何东西，也就不该动游戏）。

        ``ResourceExhausted``（退出码 2）**接**：那是「还能干、但没本钱了」的
        正常业务退出，停在购买弹窗/次数用完页上都该回家。

        ⚠️ 收尾失败**绝不改退出码**：任务本身已经成功了，不能因为「没走回家」
        就报失败。失败由 ``finish_home`` 实现方记日志并返回原因，这里只记账。
        """
        if self.finish_home is None:
            return
        failure = self.finish_home()
        if failure is not None:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 收尾=回首页失败 原因={failure} "
                "处理=已忽略（不影响本次运行结论）"
            )

    # ---- 战斗移交 ----

    def _run_committed_battle(self, *, cycle: int) -> None:
        """移交战斗监督并等它打完；把状态拨到「战斗中」或「战斗结果」。

        ⚠️ 只有 ``RESULT_REACHED`` 才算正常打完。``PRE_BATTLE_BUSINESS`` 是
        「战斗没打起来」（典型是买票 / 体力弹窗压住了队伍页）—— 状态照样拨到
        ``_BATTLE_STATE``，好让下一步的 ``next_action`` 在那一页上认出该点哪。
        """
        outcome = self.battle_supervisor.run(
            self.machine.observe_battle,
            cycle=cycle,
        )
        if outcome is BattleOutcome.PRE_BATTLE_BUSINESS:
            self.machine.state = self._BATTLE_STATE
            return
        if outcome is not BattleOutcome.RESULT_REACHED:
            raise RuntimeError(f"{self._MODE_LABEL}战斗出现意外结果：{outcome.value}")
        self.machine.state = self._RESULT_STATE
        self._after_result_state(cycle=cycle)

    # ---- 转场验收 ----

    def _log_transition_start(self, action: Any) -> None:
        """点击**之前**的两行日志。

        默认是远征口径（「当前页面 + 判断依据」＋「执行点击 …」）。
        竞技场覆写成空：它在自己的主循环里已经每轮记过一行
        「轮次/页面/动作候选/依据」，再来两行只是噪声（2026-09-26 抽取时**刻意**
        保留这个差异 —— 抽取不允许顺手改日志）。
        """
        self.runtime.log(
            f"模式={self._MODE_LABEL} 当前页面={self._action_source_page(action)} "
            f"判断依据={action.reason}"
        )
        self.runtime.log(
            f"模式={self._MODE_LABEL} 执行点击 动作={action.name} 尝试=1/4 "
            f"坐标={action.point} "
            f"目标页面={'/'.join(self._action_target_pages(action))}"
        )

    def _transition_diagnostic_label(self, action: Any) -> str:
        """转场失败那张诊断图的**标签**。

        默认远征口径：``no_transition_<动作名>``。
        竞技场覆写成 ``no_transition_<来源状态>_to_<目标状态…>`` —— 它按页面命名。
        ⚠️ 这个差异**刻意保留**：仓库里现存的竞技场现场诊断图就是按那个格式命名的，
        改名会让「照着日志去找那张图」的操作失效。
        """
        return f"no_transition_{action.name}"

    def _log_transition_failed(
        self, action: Any, attempts: int, diagnostic: Any
    ) -> None:
        """转场失败、抛错**之前**额外记的一行日志。默认不记（远征口径）。

        竞技场覆写成它自己那句「状态=转场失败 …」。
        """
        del action, attempts, diagnostic

    def _execute_transition(self, action: Any) -> None:
        """点击 + 等到目标页面稳定，确认后才 ``commit()`` 状态前进。

        这是本族的**核心**，验收口径有两条硬规矩：

        1. **目标页面必须连续两帧出现**才提交 —— 单帧命中多半是转场动画路过；
        2. **源页面还在就说明这一下没生效** ⇒ 重试，但**上限 4 次**（别把
           「再试一次」变成无限重试）。⚠️ **源页面离开过又回来**就不再点：
           那已经不在「这一下没生效」的讨论里了，交给外层超时收尾。

        失败处置交给 ``_transition_failure_message``（默认抛错，可覆写成只记诊断）。

        ⚠️ **两处时钟刻意错开**（2026-09-26 抽取，为的是让两条路线都**逐字**保持原样）：
        ``started``（绝对上限）从**点击前**起算 —— 远征原本就是这么算的；
        ``progressed``（画面多久没动）从**静置完之后**起算 —— 竞技场原本就是这么算的。
        远征的 ``no_progress`` 与 ``absolute`` 相等，这块计时对它根本不生效
        （见 ``_transition_budget``），所以错开不改变远征任何行为。
        """
        if action.source_state is None or not action.target_states:
            raise RuntimeError(
                f"{self._MODE_LABEL}动作[{action.name}]缺少来源/目标合同"
            )
        source_page = self._action_source_page(action)
        target_pages = self._action_target_pages(action)
        attempts = 1
        source_stable = StableObservation(required=2)
        target_stable = StableObservation(required=2)
        source_left = False
        started = self.now()
        absolute, no_progress = self._transition_budget(action)
        settle = (
            self._SETTLE_SECONDS
            if self._SETTLE_SECONDS is not None
            else self.poll_seconds
        )
        self._log_transition_start(action)
        self.runtime.click(action.point, action.name)
        # 点完先静置一轮，跳过「下一屏还没渲染出来」那一帧。
        # ⚠️ 睡在**这里**（不是循环头上），下面重试分支才能各自睡够同样的时长。
        self.sleep(settle)
        progressed = self.now()
        screen: Optional[np.ndarray] = None
        previous: Optional[np.ndarray] = None
        while self.now() - started < absolute:
            screen = self.runtime.capture()
            self._save_frame(screen)
            target = self.machine.action_target_state(screen, action)
            if (
                target_stable.update(target.value if target is not None else "other")
                and target is not None
            ):
                self.machine.commit(action, target)
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 转场确认 动作={action.name} "
                    f"从={source_page} 到={self._state_label(target)} 目标连续=2"
                )
                return
            source_visible = self.machine.action_source_visible(screen, action)
            if (
                source_stable.update("source" if source_visible else "other")
                and source_visible
            ):
                # ⚠️ ``source_left`` 也在这里判 —— **不要**写成
                # 「``if source_left: continue``」：那会连下面「画面有没有在动」
                # 的计时一起跳过，正好是竞技场那条会生效的判据。
                if not source_left and attempts < 4:
                    attempts += 1
                    self.runtime.log(
                        f"模式={self._MODE_LABEL} 转场重试 动作={action.name} "
                        f"来源={source_page}仍在 尝试={attempts}/4 坐标={action.point}"
                    )
                    self.runtime.click(action.point, action.name)
                    source_stable.reset()
                    self.sleep(settle)
                    continue
            elif not source_visible and not source_left:
                source_left = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 等待转场 动作={action.name} "
                    f"来源={source_page}已离开 "
                    f"目标={'/'.join(target_pages)}待稳定"
                )
            # 「画面一动不动」判据只在它**严于**绝对上限时才生效（见
            # ``_transition_budget``）：远征两档相等 ⇒ 这条分支根本不跑，
            # 行为与抽取之前**逐帧一致**；竞技场 ``no_progress`` 更短，才真的在兜底。
            if no_progress < absolute:
                if meaningful_change(previous, screen):
                    progressed = self.now()
                previous = screen
                if self.now() - progressed >= no_progress:
                    break
            self.sleep(self.poll_seconds)
        diagnostic = self._save_failure_diagnostic(
            self._transition_diagnostic_label(action),
            screen,
            action=action,
            attempt=attempts,
            conclusion="来源页面未退出或目标页面未稳定出现",
        )
        self._log_transition_failed(action, attempts, diagnostic)
        message = self._transition_failure_message(action, attempts, diagnostic)
        if message is not None:
            raise RuntimeError(message)

    # ---- 主循环 ----

    def _dry_run(self) -> int:
        """空跑：只观察一帧，**不点任何东西**。

        与 ``ModeRunnerBase._dry_run`` 不同 —— 那边会真的点一下并在撞上结论时
        复核两帧，因为它要回答「这一步会点哪」；本族的事务验收在干跑里没法验收
        （点完要等到目标页稳定，而干跑不点），所以只报「下一步动作是什么」。
        """
        screen = self.runtime.capture()
        action = self.machine.next_action(screen)
        if action is not None:
            self.runtime.log(
                f"模式={self._MODE_LABEL} 动作={action.name} 状态=诊断"
            )
        return self.machine.completed_cycles

    def run(self, max_cycles: int | None = None) -> int:
        if self.runtime.dry_run:
            return self._dry_run()

        stable = StableObservation(required=2)
        conclusion_gate = ConclusionGate()
        state_started = self.now()
        while max_cycles is None or self.machine.completed_cycles < max_cycles:
            screen = self.runtime.capture()
            self._save_frame(screen)
            state_before = self.machine.state
            cycles_before = self.machine.completed_cycles
            try:
                try:
                    preview, _ = self.machine.preview(screen)
                except RuntimeError as error:
                    # 结论也要两帧：单帧就宣布「传单没了 / 认不出画面」会提前收工。
                    if not conclusion_gate.admit(error):
                        self.runtime.log(
                            f"模式={self._MODE_LABEL} 结论待确认={type(error).__name__} "
                            f"依据=需连续两帧一致才采信 详情={error}"
                        )
                        self.sleep(self.poll_seconds)
                        continue
                    raise
                signature = (
                    preview.name
                    if preview is not None
                    else f"settled:{state_before.value}"
                )
                if not stable.update(signature):
                    self.sleep(self.poll_seconds)
                    continue
                action = self.machine.next_action(screen)
                stable.reset()
                conclusion_gate.reset()
            except ManualStop:
                # ⚠️ 必须排在下面几条前面。``ManualStop`` 是 ``RuntimeError`` 的
                # 子类，掉进「认不出画面」那条分支会被当成页面没认出来 ——
                # 一次停止会变成按轮询频率刷屏 + 每秒一张全屏诊断图。
                # （``ConclusionGate.admit`` 对它是立即放行的，所以上面那层拦不住。）
                raise
            except ResourceExhausted as error:
                # 「还能干、但没本钱了」（生命之叶 / 通缉传单……）：正常业务退出，
                # 退出码 2，照样收尾回首页。缺的是什么由异常自己的 ``stop_label`` 带。
                self.resource_exhausted = True
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 停止={error.stop_label} 详情={error}"
                )
                self._close_out()
                return self.machine.completed_cycles
            except UnrecognizedScreen as error:
                wake = self.unknown_screen_wake.handle(
                    screen, context=f"{self._MODE_LABEL}:{self._state_label(state_before)}"
                )
                if wake is UnknownWakeResult.WAITING:
                    self.sleep(self.poll_seconds)
                    continue
                if self.now() - state_started < self._timeout_for(state_before):
                    self.sleep(self.poll_seconds)
                    continue
                diagnostic = self._save_failure_diagnostic(
                    f"timeout_{state_before.value}",
                    screen,
                    conclusion=f"未知页面持续超时：{error}",
                )
                raise RuntimeError(
                    f"{self._MODE_LABEL}未知页面：{error}；已保存诊断 {diagnostic}"
                ) from error
            if action is None:
                if self.machine.state is self._SETTLED_BATTLE_STATE:
                    # 停在局内且状态机没有别的活要干 ⇒ 这一局交给战斗监督等结算。
                    self._run_committed_battle(
                        cycle=self.machine.completed_cycles + 1
                    )
                    state_started = self.now()
                    continue
                self.sleep(self.poll_seconds)
                continue
            self._execute_transition(action)
            state_started = self.now()
            # 只要转场把状态落到了「战斗中」，就交给战斗监督 —— 不再只认某一个
            # 动作名：``prepare-battle`` 也可能**直接**落到战斗页，漏了这一步会让
            # 状态卡在 BATTLE 却没人驱动，白等到状态超时。
            if (
                action.name in self._HANDOFF_AFTER_TRANSITION_ACTIONS
                and self.machine.state is self._BATTLE_STATE
            ):
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 动作={action.name} "
                    "状态=直接进入战斗，移交战斗监督"
                )
                self._run_committed_battle(
                    cycle=self.machine.completed_cycles + 1
                )
                state_started = self.now()
            if self.machine.completed_cycles > cycles_before:
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 业务完成 cycles={self.machine.completed_cycles}"
                )
                if (
                    max_cycles is not None
                    and self.machine.completed_cycles >= max_cycles
                ):
                    self._close_out()
                    return self.machine.completed_cycles
            timeout = self._timeout_for(state_before)
            if self.now() - state_started >= timeout:
                # 这一段等太久 ⇒ **结束这条路线**（回家由 main 收尾）。
                # ⚠️ 2026-09-26：以前这里是「回大厅重新导航、然后接着跑」，
                # 用户拍板「回家就是结束，不可能再回来」。
                self.runtime.log(
                    f"模式={self._MODE_LABEL} 页面={self._state_label(state_before)} "
                    f"停止=该段超过 {timeout:.0f} 秒未推进"
                )
                raise RuntimeError(
                    f"{self._MODE_LABEL}在 {self._state_label(state_before)} "
                    f"超时未推进（{timeout:.0f} 秒）"
                )
        self._close_out()
        return self.machine.completed_cycles
