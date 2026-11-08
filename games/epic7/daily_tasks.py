"""「每日任务」：把勾上的几条路线串起来一次跑完。

用户诉求（2026-09-25）：每天点一下，把该做的日常任务依次跑完。
用户诉求（2026-09-29）改判：**次序不再写死，由界面上的勾选先后决定**；
可勾的也不再限于下面这五条 —— 除了「活动」，其余九条都能串。
``DAILY_TASKS`` 因此退化成**默认清单**：只有「调用方没说要跑哪几条」时
（命令行 ``--daily`` 不带 ``--daily-tasks``）才按它的次序全跑。

**为什么不塞进 ``MODE_SPECS``**：路线是「一个状态机 + 一个 Runner」的固定形状，
而这里是**编排**（循环调用 ``main.run_mode``）。硬塞进去会污染 ``--mode`` 的
枚举、``ROUTES``、接力 ``ResumePoint`` 这些本该只管真路线的机制。

⚠️ 刷书签的 ``cycles`` 是「付费刷新次数」，**花天空石、点了不可撤销**，所以
默认 **0 次**（只进店扫一遍、把自动刷出来的买掉，一次都不刷新）且界面上可改，
别在这里写大数。0 是各路线里唯一合法的「零次」（见 ``ModeSpec.min_cycles``）。

**每段之间「确保在首页」**（用户拍板：先看再拉）：
上一条不管正常结束还是异常结束，本条开跑前先看一眼当前帧 —— 已在大厅就跳过
（大厅上 ``return_home`` 约 1.3 秒、零点击，几乎无感，但省下这一趟）；不在大厅
才调 ``return_home()`` 拉回来。拉不回来就**放弃剩余任务**并在汇总里写明停在哪儿
—— 而不是让下一条去撞同一堵墙（那会连锁失败）。

⚠️ 这里的「段间回大厅」与路线自己的「收尾回首页」是**两件事**：
后者只在正常完成 / 资源耗尽时触发（异常与手动停刻意不回家，怕丢局），
所以不能指望它把异常后的残局收拾干净 —— 那正是本模块存在的理由。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.games.epic7.modes import (
    MODE_SPECS,
    PC_ONLY_ROUTES,
    get_mode,
)


@dataclass(frozen=True)
class DailyTask:
    """每日任务里的一项：跑哪条路线。

    ⚠️ **只存模式名**。中文名与默认次数都从 ``modes.MODE_SPECS`` 取 —— 以前它们是
    本类的字段，等于又抄了一份，实测漂移过（这里写「商店刷新」、别处写「刷书签」）。
    """

    mode: str

    @property
    def label(self) -> str:
        return get_mode(self.mode).label

    @property
    def cycles(self) -> int:
        return get_mode(self.mode).default_cycles


# **默认清单**：调用方没说跑哪几条时按这个次序全跑（命令行 ``--daily`` 的兜底）。
# 界面不读它 —— 界面把用户勾的那几条按勾选先后传下来（见 ``normalize_selection``）。
# 次序本身仍有讲究：世界首领战与骑士团捐赠都从骑士团进、路径相近放一起；
# 刷书签（秘密商店）与迷宫强化石各自独立；竞技场入口不同、最灵活，放最后。
# 圣域收菜与骑士团那两条无关，但它和刷书签一样是「进菜单点几下就出来」的短流程，
# 且入口都在大厅左侧那排菜单上 ⇒ 放在骑士团之后、刷书签之前。
# 次数不写在这儿 —— 它跟着 ``MODE_SPECS`` 的 default_cycles 走（界面上可以改，
# 改的值走 ``run_daily_tasks(cycles_override=...)``）。各路线为什么是那个次数，
# 写在各自的 ModeSpec 上。
#
# ⚠️ **「社区签到」刻意不在这张默认清单里**（它已经在 ``MODE_SPECS`` 与 ``ROUTES``
# 里登记了，界面能勾、命令行能点名，只是不该被默认带上）。理由：它的竖屏段还缺真机
# 数据，实跑被 ``modes._preflight_community`` 拦住 —— 放进来会让**每一次**裸跑
# ``--daily`` 都多出一个必然失败的 ✗，人会很快学会无视那个 ✗。
# 等数据采齐、``community.LIVE_RUN_READY`` 打开之后，再按它该在的位置加进来。
DAILY_TASKS: tuple[DailyTask, ...] = (
    DailyTask(mode="world_boss"),
    DailyTask(mode="knights_donation"),
    DailyTask(mode="sanctuary"),
    DailyTask(mode="shop_refresh"),
    DailyTask(mode="labyrinth_stone"),
    DailyTask(mode="arena"),
    # 月光剧场：**周的**内容、但放在日常里跑（用户 2026-10-17 拍板）。
    # 每天顺手看一眼是有意义的：免费额度是「存量」——别人先领完就没了，
    # 所以越早跑越好。没有额度时它只走「大厅 → 支线故事 → 看见入口没绿 F」，
    # 三秒收工，且出口是 ``ResourceExhausted``（汇总里记成 ``resource``，
    # 不是 ✗ 失败）。有额度时才变成「看几幕剧情」的长流程，所以放整张表的最后。
    DailyTask(mode="moonlight_theater"),
    # 成就领取（2026-11-08）。放最后：它是「有就领、没有就走」的类型，
    # 没新成就时几秒收工，不会拖长整轮。
    # ⚠️ 目前只有 PC 素材 —— 模拟器后端下整条会被跳过（见 ``PC_ONLY_ROUTES``），
    # 汇总里记成 ``skipped`` 并写明原因，不算失败。
    DailyTask(mode="achievement"),
)


@dataclass
class DailyOutcome:
    """一条任务的结局。"""

    mode: str
    label: str
    status: str  # "completed" | "resource" | "failed" | "skipped"
    detail: str = ""

    @property
    def ok(self) -> bool:
        # ``not_supported`` = 「这条路线当前后端没有素材，本轮按设计跳过」。
        # 它不是失败：既没跑、也没出错，只是素材边界（见 ``PC_ONLY_ROUTES``）。
        # ⚠️ 与 ``skipped`` 刻意分开：后者专指「上一段回不到首页，为避免连锁失败
        # 而放弃剩余任务」，那**是**一次失败（``ok`` 必须为 False）。
        return self.status in {"completed", "resource", "not_supported"}


def _short_failure(detail: str, limit: int = 90) -> str:
    """把失败原因压成一句：去掉「已保存诊断 …」那串长路径，再截断。

    ⚠️ 诊断路径动辄 120+ 字符，原样塞进汇总行会把日志和手机通知都撑爆，
    而**路径本身对「为什么失败」没有信息量**（要找诊断，日志里那条
    ``已保存诊断 …`` 已经写全了）。
    """
    text = detail.split("；已保存诊断")[0].split("; 已保存诊断")[0].strip()
    if not text:
        return "原因未记录"
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class DailyReport:
    """整轮每日任务的结果汇总。"""

    outcomes: list[DailyOutcome] = field(default_factory=list)
    aborted_reason: Optional[str] = None
    stopped_by_user: bool = False

    @property
    def any_failed(self) -> bool:
        return any(not outcome.ok for outcome in self.outcomes)

    def summary_line(self) -> str:
        """一行给日志/通知用的汇总，例：``世界首领战 ✓ / 骑士团捐赠 ✗ / 竞技场 ✓``。

        ⚠️ **失败的条目必须带一句原因**（2026-10-24 补）。原先只打一个 ✗ ——
        2026-10-24 月光剧场连续失败三次，日志里全是 ``月光剧场 ✗``，真因
        （静默异常 / 收尾失败）一个字都看不到，只能靠翻子进程日志猜。
        ``detail`` 早就记下来了，只是没打出来。
        """
        marks = {
            "completed": "✓",
            "resource": "✓(资源耗尽)",
            "failed": "✗",
            "skipped": "—",
            "not_supported": "—(当前后端无素材)",
        }
        parts = []
        for outcome in self.outcomes:
            text = f"{outcome.label} {marks.get(outcome.status, '?')}"
            if outcome.status == "failed" and outcome.detail:
                text += f"[{_short_failure(outcome.detail)}]"
            parts.append(text)
        line = " / ".join(parts)
        if self.aborted_reason:
            line += f" ｜ 已中止：{self.aborted_reason}"
        return line


def normalize_selection(selected: object) -> tuple[str, ...]:
    """把界面传来的勾选规整成「有次序、去重、且都是已知路线」的模式名元组。

    - ``None`` ⇒ 默认清单（``DAILY_TASKS``）。这是命令行 ``--daily`` 不带
      ``--daily-tasks`` 时的兜底；界面永远显式传自己勾的那几条。
    - 显式传入 ⇒ **严格按传入顺序保留**：勾选先后就是执行顺序（用户 2026-09-29
      拍板：次序由他定，不再由本模块写死）。同一个模式名出现两次只算第一次。
    - 空 ⇒ 报错（fail-closed）：一条都不勾不该静默变成「全跑」。
    - 认不出的模式名直接报错（fail-closed）：界面/命令行传错名字属于接线问题，
      静默忽略会让「勾了却没跑」变成一个没人发现的坑。
    """
    if selected is None:
        return tuple(task.mode for task in DAILY_TASKS)
    requested: list[str] = []
    for name in selected:
        mode = str(name)
        if mode not in requested:
            requested.append(mode)
    if not requested:
        raise ValueError("至少要勾选一条路线")
    unknown = sorted(set(requested) - set(MODE_SPECS))
    if unknown:
        raise ValueError(f"未知路线：{'、'.join(unknown)}")
    return tuple(requested)


def _observe_lobby(navigator: object, runtime: object) -> str:
    """看一眼当前帧，返回它在导航里的页面名（认不出就是 ``"unknown"``）。"""
    screen = runtime.capture()
    return navigator.observe(screen).name


def ensure_at_lobby(
    *,
    navigator: object,
    runtime: object,
    mode_label: str,
    home_return: Optional[Callable[..., object]] = None,
) -> Optional[str]:
    """确认「人在大厅」；不在就拉回来。返回失败原因，成功（含本来就到了）返回 None。

    ⚠️ 契约（与 ``ModeRunnerBase._close_out`` 一致）：**绝不抛异常** —— 由调用方
    决定怎么处理失败（这里是「放弃剩余任务并汇总」）。失败原因是要给人看的一句话。

    ``home_return`` 是「回大厅」这一步的具体做法（走新流程还是老流程，由
    ``main.HomeReturn`` 按路线白名单决定）。**传 None 就用导航器自带的那套** ——
    这条兜底是给不关心分流的调用方留的，正常串任务时都应该传。
    """
    try:
        if _observe_lobby(navigator, runtime) == "lobby":
            runtime.log(f"模式={mode_label} 段间检查=已在首页 动作=跳过返回")
            return None
        runtime.log(f"模式={mode_label} 段间检查=不在首页 动作=受控返回大厅")
        if home_return is None:
            navigator.return_home()
        else:
            home_return()
        return None
    except Exception as error:  # noqa: BLE001 —— 契约要求绝不外抛
        return f"{type(error).__name__}: {error}"


def run_daily_tasks(
    *,
    selected: object = None,
    cycles_override: Optional[Mapping[str, int]] = None,
    dry_run: bool,
    window_backend: str = "emulator",
    stop_file: Path | None = None,
    # 每条路线的专属参数：``{路线名: {参数名: 值}}``。**按路线名分发**，到这里
    # 只负责把属于这一条的那份递给 ``run_mode`` —— 本模块不解释任何参数内容。
    params: Optional[Mapping[str, Mapping[str, Any]]] = None,
    run_mode: Callable[..., object],
    build_probe: Optional[Callable[[], tuple[object, object]]] = None,
    build_home_return: Optional[
        Callable[[object, object, str], Callable[..., object]]
    ] = None,
) -> DailyReport:
    """把 ``selected`` 里的路线**按它给的次序**逐条跑完，返回汇总。

    ``cycles_override`` 是「这几条不要用默认次数」—— 例如竞技场想连跑 3 场。
    **没写进来的路线一律用 ``MODE_SPECS`` 里的默认次数**，所以它是一张
    稀疏覆盖表，不是必须齐全的对照表。

    参数里的可注入点都是为了可测：

    - ``run_mode``：跑单条路线的函数（就是 ``main.run_mode``）。测试传替身。
    - ``build_probe``：建「段间检查」用的 ``(runtime, navigator)`` 的函数，
      只有实跑（非 dry_run）才会被调用。测试传替身，避免真去连窗口。
    - ``build_home_return``：按「(navigator, runtime, mode)」造出「回大厅」这一步
      怎么做（就是 ``main.HomeReturn``）。**不传就走导航器自带的那套**，
      留给不关心路线分流的调用方。

    ⚠️ 干跑（``dry_run``）下**不做段间回大厅**：干跑本来就不碰游戏，
    没有 navigator 可建，硬做会假报「回不了家」。这与路线收尾的处理一致。
    """
    modes = normalize_selection(selected)
    report = DailyReport()
    # 段间检查只在实跑时才有意义（干跑不碰游戏、也没有 navigator）。
    probe_builder = build_probe if not dry_run else None
    probe: tuple[object, object] | None = None

    def home_return_builder(mode: str) -> Optional[Callable[..., object]]:
        if build_home_return is None or probe is None:
            return None
        navigator, runtime = probe[1], probe[0]
        return build_home_return(navigator, runtime, mode)

    def ensure_probe() -> tuple[object, object] | None:
        nonlocal probe
        if probe_builder is None:
            return None
        if probe is None:
            probe = probe_builder()
        return probe

    overrides = dict(cycles_override or {})

    for mode in modes:
        spec = get_mode(mode)
        label = spec.label
        cycles = overrides.get(mode, spec.default_cycles)

        # 只放 PC 素材的路线在模拟器上必然缺图（构造期 FileNotFoundError）⇒
        # 直接跳过并记一笔，不让一条「素材还没做」的路线把整轮连打打断。
        # ⚠️ 记成 ``skipped`` 而不是失败：这不是故障，是素材边界（见 ``PC_ONLY_ROUTES``）。
        if window_backend != "pc" and mode in PC_ONLY_ROUTES:
            report.outcomes.append(
                DailyOutcome(
                    mode=mode,
                    label=label,
                    status="not_supported",
                    detail="目前只有 PC 客户端版素材，模拟器上跳过；要跑请切到 PC 客户端",
                )
            )
            continue

        # 段间检查：这一段之前先确保人在大厅（第一条不用 —— 开局本来就该在大厅，
        # 且第一条的 _enter_mode 自己会处理）。
        if report.outcomes:
            built = ensure_probe()
            if built is not None:
                probe_runtime, probe_navigator = built
                failure = ensure_at_lobby(
                    navigator=probe_navigator,
                    runtime=probe_runtime,
                    mode_label=label,
                    # 按**即将要跑的那条路线**决定怎么回家：上一段就是被这条路线
                    # 收尾留在半路的，用同一条路线的口径拉回来最合适。
                    home_return=home_return_builder(mode),
                )
                if failure is not None:
                    report.aborted_reason = f"{label} 之前无法回到首页（{failure}）"
                    report.outcomes.append(
                        DailyOutcome(
                            mode=mode,
                            label=label,
                            status="skipped",
                            detail="上一段之后回不到首页，为避免连锁失败未执行",
                        )
                    )
                    break

        try:
            result = run_mode(
                spec=spec,
                dry_run=dry_run,
                max_cycles=cycles,
                start_state=spec.default_state,
                window_backend=window_backend,
                stop_file=stop_file,
                params=(params or {}).get(mode),
            )
        except ManualStop:
            # 用户按了 P：停下来的语义是「别跑了」，整轮到此为止，
            # 但**不改已经跑完那几条的结论**。
            report.stopped_by_user = True
            report.outcomes.append(
                DailyOutcome(
                    mode=mode,
                    label=label,
                    status="skipped",
                    detail="用户手动停止",
                )
            )
            break
        except Exception as error:  # noqa: BLE001 —— 单条失败不该带崩整轮
            report.outcomes.append(
                DailyOutcome(
                    mode=mode,
                    label=label,
                    status="failed",
                    detail=f"{type(error).__name__}: {error}",
                )
            )
            continue

        exhausted = bool(getattr(result, "resource_exhausted", False))
        report.outcomes.append(
            DailyOutcome(
                mode=mode,
                label=label,
                status="resource" if exhausted else "completed",
                detail=(
                    f"轮次={getattr(result, 'completed_cycles', '?')}"
                    + (
                        f" 战绩={result.outcome_summary}"
                        if getattr(result, "outcome_summary", None)
                        else ""
                    )
                ),
            )
        )

    return report
