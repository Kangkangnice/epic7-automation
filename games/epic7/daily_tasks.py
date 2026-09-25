"""「每日任务」：把几条路线按固定次序串起来一次跑完。

用户诉求（2026-09-25）：每天点一下，把该做的日常任务依次跑完。
默认串三条 —— 世界首领战 → 骑士团捐赠 → 竞技场；界面上可以只勾其中一两条。

**为什么不塞进 ``MODE_SPECS``**：路线是「一个状态机 + 一个 Runner」的固定形状，
而这里是**编排**（循环调用 ``main.run_mode``）。硬塞进去会污染 ``--mode`` 的
枚举、``ROUTES``、接力 ``ResumePoint`` 这些本该只管真路线的机制。

**为什么次序是写死的、界面上不给排序**：用户明确说「顺序不重要」（= 不想操心
先后）。次序在这里定：骑士团那两条路径相近放一起，竞技场入口不同放最后。
要调整就改 ``DAILY_TASKS``，不必动界面。

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
from typing import Callable, Optional

from auto_game_unified.core.runtime import ManualStop
from auto_game_unified.games.epic7.modes import get_mode


@dataclass(frozen=True)
class DailyTask:
    """每日任务里的一项：跑哪条路线、跑几次。"""

    mode: str
    label: str
    cycles: int


# 次序即执行次序（与 ``mode`` 的字母序无关，别用 sorted 覆盖它）。
# cycles 与各路线在 desktop/catalog.py / main.py 里的「每日默认次数」保持一致：
#   - world_boss 每天固定 2 次（主页「剩余/上限」就是 2）；
#   - knights_donation 请求支援一天只能发一次 ⇒ 1 次；
#   - arena 没有每日上限，先按 1 场走，用户要更多就在界面上改（见 ``cycles_for``）。
DAILY_TASKS: tuple[DailyTask, ...] = (
    DailyTask(mode="world_boss", label="世界首领战", cycles=2),
    DailyTask(mode="knights_donation", label="骑士团捐赠", cycles=1),
    DailyTask(mode="arena", label="竞技场", cycles=1),
)

DAILY_BY_MODE = {task.mode: task for task in DAILY_TASKS}


@dataclass
class DailyOutcome:
    """一条任务的结局。"""

    mode: str
    label: str
    status: str  # "completed" | "resource" | "failed" | "skipped"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"completed", "resource"}


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
        """一行给日志/通知用的汇总，例：``世界首领战 ✓ / 骑士团捐赠 ✗ / 竞技场 ✓``。"""
        marks = {
            "completed": "✓",
            "resource": "✓(资源耗尽)",
            "failed": "✗",
            "skipped": "—",
        }
        parts = [f"{o.label} {marks.get(o.status, '?')}" for o in self.outcomes]
        line = " / ".join(parts)
        if self.aborted_reason:
            line += f" ｜ 已中止：{self.aborted_reason}"
        return line


def normalize_selection(selected: object) -> tuple[str, ...]:
    """把界面传来的勾选规整成「有次序、去重、且都是已知任务」的模式名元组。

    - ``None`` / 空 ⇒ 默认全选（界面初次进入时没有显式勾选，按全部走）。
    - 次序一律按 ``DAILY_TASKS`` 排，**不信调用方给的顺序**（用户说了顺序不重要，
      那就由这里统一，免得界面顺序变化影响执行顺序）。
    - 认不出的模式名直接报错（fail-closed）：界面传错名字属于接线问题，
      静默忽略会让「勾了却没跑」变成一个没人发现的坑。
    """
    if selected is None:
        return tuple(task.mode for task in DAILY_TASKS)
    requested = {str(name) for name in selected}
    if not requested:
        raise ValueError("每日任务至少要勾选一项")
    unknown = sorted(requested - set(DAILY_BY_MODE))
    if unknown:
        raise ValueError(f"每日任务里有未知路线：{'、'.join(unknown)}")
    return tuple(task.mode for task in DAILY_TASKS if task.mode in requested)


def _observe_lobby(navigator: object, runtime: object) -> str:
    """看一眼当前帧，返回它在导航里的页面名（认不出就是 ``"unknown"``）。"""
    screen = runtime.capture()
    return navigator.observe(screen).name


def ensure_at_lobby(
    *,
    navigator: object,
    runtime: object,
    mode_label: str,
) -> Optional[str]:
    """确认「人在大厅」；不在就拉回来。返回失败原因，成功（含本来就到了）返回 None。

    ⚠️ 契约（与 ``ModeRunnerBase._close_out`` 一致）：**绝不抛异常** —— 由调用方
    决定怎么处理失败（这里是「放弃剩余任务并汇总」）。失败原因是要给人看的一句话。
    """
    try:
        if _observe_lobby(navigator, runtime) == "lobby":
            runtime.log(f"模式={mode_label} 段间检查=已在首页 动作=跳过返回")
            return None
        runtime.log(f"模式={mode_label} 段间检查=不在首页 动作=受控返回大厅")
        navigator.return_home()
        return None
    except Exception as error:  # noqa: BLE001 —— 契约要求绝不外抛
        return f"{type(error).__name__}: {error}"


def run_daily_tasks(
    *,
    selected: object = None,
    dry_run: bool,
    window_backend: str = "emulator",
    stop_file: Path | None = None,
    run_mode: Callable[..., object],
    build_probe: Optional[Callable[[], tuple[object, object]]] = None,
) -> DailyReport:
    """按 ``DAILY_TASKS`` 的次序把选中的路线逐条跑完，返回汇总。

    参数里的两个可注入点是为了可测：

    - ``run_mode``：跑单条路线的函数（就是 ``main.run_mode``）。测试传替身。
    - ``build_probe``：建「段间检查」用的 ``(runtime, navigator)`` 的函数，
      只有实跑（非 dry_run）才会被调用。测试传替身，避免真去连窗口。

    ⚠️ 干跑（``dry_run``）下**不做段间回大厅**：干跑本来就不碰游戏，
    没有 navigator 可建，硬做会假报「回不了家」。这与路线收尾的处理一致。
    """
    modes = normalize_selection(selected)
    report = DailyReport()
    # 段间检查只在实跑时才有意义（干跑不碰游戏、也没有 navigator）。
    probe_builder = build_probe if not dry_run else None
    probe: tuple[object, object] | None = None

    def ensure_probe() -> tuple[object, object] | None:
        nonlocal probe
        if probe_builder is None:
            return None
        if probe is None:
            probe = probe_builder()
        return probe

    for mode in modes:
        task = DAILY_BY_MODE[mode]

        # 段间检查：这一段之前先确保人在大厅（第一条不用 —— 开局本来就该在大厅，
        # 且第一条的 _enter_mode 自己会处理）。
        if report.outcomes:
            built = ensure_probe()
            if built is not None:
                probe_runtime, probe_navigator = built
                failure = ensure_at_lobby(
                    navigator=probe_navigator,
                    runtime=probe_runtime,
                    mode_label=task.label,
                )
                if failure is not None:
                    report.aborted_reason = (
                        f"{task.label} 之前无法回到首页（{failure}）"
                    )
                    report.outcomes.append(
                        DailyOutcome(
                            mode=task.mode,
                            label=task.label,
                            status="skipped",
                            detail="上一段之后回不到首页，为避免连锁失败未执行",
                        )
                    )
                    break

        spec = get_mode(task.mode)
        try:
            result = run_mode(
                spec=spec,
                dry_run=dry_run,
                max_cycles=task.cycles,
                start_state=spec.default_state,
                window_backend=window_backend,
                stop_file=stop_file,
            )
        except ManualStop:
            # 用户按了 P：停下来的语义是「别跑了」，整轮到此为止，
            # 但**不改已经跑完那几条的结论**。
            report.stopped_by_user = True
            report.outcomes.append(
                DailyOutcome(
                    mode=task.mode,
                    label=task.label,
                    status="skipped",
                    detail="用户手动停止",
                )
            )
            break
        except Exception as error:  # noqa: BLE001 —— 单条失败不该带崩整轮
            report.outcomes.append(
                DailyOutcome(
                    mode=task.mode,
                    label=task.label,
                    status="failed",
                    detail=f"{type(error).__name__}: {error}",
                )
            )
            continue

        exhausted = bool(getattr(result, "resource_exhausted", False))
        report.outcomes.append(
            DailyOutcome(
                mode=task.mode,
                label=task.label,
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


def cycles_for(mode: str) -> int:
    """这条每日任务默认跑几次（界面初次进来时用来填默认值）。"""
    return DAILY_BY_MODE[mode].cycles
