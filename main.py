import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from auto_game_unified.core.hotkey import WindowsPStopHotkey
from auto_game_unified.core.qqbot import send_qqbot_c2c
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.window import Epic7Window
from auto_game_unified.core.pc_window import Epic7PcWindow
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    LIVE_TRANSACTIONS_VERIFIED,
)
from auto_game_unified.games.epic7.modes import (
    MODE_SPECS,
    ModeSpec,
    ResumePoint,
    ResumeProbe,
    get_mode,
)
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates
from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_gift_support_templates,
    load_intimacy_level_up_templates,
    load_knights_signin_templates,
    load_network_reconnect_templates,
)


ROOT = Path(__file__).resolve().parent
MODE_LABELS = {
    "story": "主线",
    "arena": "竞技场",
    "expedition": "远征",
    "fodder": "狗粮",
    "hero_synthesis": "英雄合成",
    "shop_refresh": "刷书签",
    "survivor": "幸存者",
    "world_boss": "世界首领战",
    "knights_donation": "骑士团捐赠",
}


@dataclass(frozen=True)
class RunResult:
    completed_cycles: int
    resource_exhausted: bool = False
    # 只有竞技场会给：一行「胜 2 / 负 1」的战绩文案；别的路线留 None，通知里就不显示。
    outcome_summary: str | None = None


def _elapsed_seconds(started_at: float) -> int:
    return max(0, round(time.monotonic() - started_at))


def _notify_live(
    *,
    live: bool,
    mode: str,
    status: str,
    elapsed_seconds: int,
    completed_cycles: int | None = None,
    target_cycles: int | None = None,
    outcome_summary: str | None = None,
    error: Exception | None = None,
) -> None:
    if not live:
        return

    label = MODE_LABELS[mode]
    titles = {
        "completed": f"第七史诗：{label}已完成",
        "resource": f"第七史诗：{label}资源不足",
        "failed": f"第七史诗：{label}运行失败",
    }
    lines = [f"模式：{label}", f"耗时：{elapsed_seconds} 秒"]
    if completed_cycles is not None and target_cycles is not None:
        lines.insert(1, f"完成轮数：{completed_cycles}/{target_cycles}")
    if outcome_summary is not None:
        # 紧跟在「完成轮数」后面（没有那一行时就紧跟「模式」），仍在「耗时」之前。
        lines.insert(len(lines) - 1, f"战绩：{outcome_summary}")
    if error is not None:
        lines.insert(1, f"原因：{error}")
        lines.append(
            f"诊断目录：{ROOT / 'runtime_diagnostics' / f'epic7_{mode}'}"
        )
    title = titles[status]
    body = "\n".join(lines)
    # 单一通道：没配就安静跳过，挂了也不影响退出码。
    try:
        send_qqbot_c2c(title, body)
    except Exception as notification_error:
        print(
            f"QQ 通知失败：{type(notification_error).__name__}",
            flush=True,
        )


def _build_runtime(
    mode: str,
    dry_run: bool,
    window_backend: str = "emulator",
    stop_file: Path | None = None,
) -> Runtime:
    calibration = None
    if window_backend == "pc":
        game_window = Epic7PcWindow()
        calibration = game_window.ensure_render_size()
    else:
        game_window = Epic7Window()
        game_window.activate()
    stop_hotkey = None if dry_run else WindowsPStopHotkey()

    def stop_requested() -> bool:
        return bool(
            (stop_hotkey is not None and stop_hotkey.pressed())
            or (stop_file is not None and stop_file.exists())
        )

    runtime = Runtime(
        capture=game_window.capture,
        click=game_window.click,
        swipe=(game_window.swipe if window_backend == "emulator" else None),
        wake=game_window.wake,
        back=game_window.back,
        dry_run=dry_run,
        diagnostic_dir=ROOT / "runtime_diagnostics" / f"epic7_{mode}",
        log_path=ROOT / "runtime_logs" / f"epic7_{mode}.log",
        stop_requested=None if dry_run else stop_requested,
    )
    # 模拟器窗口也要能往运行日志里说话（例如「最小化已自动还原」）。
    game_window.set_event_sink(runtime.log)
    if calibration is not None:
        runtime.log(
            "模式=PC初始化 "
            f"调整前={calibration.before.width}x{calibration.before.height} "
            "目标=1920x1080 "
            f"调整后={calibration.after.width}x{calibration.after.height} "
            f"是否调整={'是' if calibration.adjusted else '否'} "
            "识别画布=1982x1132 模板来源=共享模拟器模板"
        )
    return runtime


class _ResumeWatch:
    """「回大厅」途中的接力观察窗。

    每确认一帧稳定画面就被问一次；一旦探针认出本路线的接力点，记下落点并返回 True，
    让 ``return_home`` 当场停止返回。只认第一次命中，之后一律 True（探针本身要跑模板
    匹配，不重复烧算力）。

    ``asked`` 记「探针**真的被执行过**多少帧」。``_enter_mode`` 靠它验证接线真的通：
    探针挂上了、但启动流程忘了把它交给 ``return_home``，静态看一切正常，只有跑一遍
    才现形。计数写在调用**之前**：探针抛异常时也该算问过（那属于判据的毛病，
    不是接线的毛病，别把两种故障混成一条报错）。
    """

    def __init__(
        self,
        probe: ResumeProbe,
        machine: Any,
        navigator: Epic7Navigator,
    ) -> None:
        self._probe = probe
        self._machine = machine
        self._navigator = navigator
        self.point: Optional[ResumePoint] = None
        self.asked = 0

    def __call__(self, screen: np.ndarray) -> bool:
        if self.point is not None:
            return True
        self.asked += 1
        found = self._probe(self._machine, screen, self._navigator)
        if found is None:
            return False
        self.point = found
        return True


def _enter_mode(
    spec: ModeSpec,
    machine: Any,
    navigator: Epic7Navigator,
    runtime: Runtime,
) -> None:
    """把游戏送进本路线的起始位置。

    默认行为是「一路返回大厅 → 按路线重新导航进去」。带接力探针的路线改成边走边看：
    第一帧就落在接力点上就直接从那一步接着跑（停在准备战斗就继续打，不再退回对手列表重选）；
    落在别的支线页面上就照旧一路返回，而且**每返回一页都再看一眼**，中途扫到接力点就地接管，
    否则一直返回到大厅再走老流程。
    """
    if spec.resume_probe is None:
        lobby_screen = navigator.return_home()
        navigator.navigate(spec.name, lobby_screen=lobby_screen)
        return
    watch = _ResumeWatch(spec.resume_probe, machine, navigator)
    resume_screen = navigator.return_home(stop_probe=watch)
    # 接线检查：`return_home` 的两条正常返回路径都在问过探针**之后**，
    # 所以「返回了却没问过」只可能是接线断了（比如 stop_probe 忘了传）。
    # 这时候探针等于白写 —— 人停在半路照样退回大厅重走，而日志里一片祥和。
    if watch.asked == 0:
        raise RuntimeError(
            f"路线 {spec.name} 挂了接力探针，但「回大厅」途中一次都没问过它；"
            "接线断了（见 main._enter_mode）。"
        )
    point = watch.point
    if point is None:
        navigator.navigate(spec.name, lobby_screen=resume_screen)
        return
    runtime.log(
        f"模式={spec.name} 开局=接力 页面={point.page} "
        f"落点状态={point.state or '保持'} "
        "动作=跳过回大厅与路线导航 状态=从当前这一步接着往下跑"
    )
    runtime.save_diagnostic("resume_point", resume_screen)
    if point.entry is not None:
        # 接力点还在导航链中间（比如竞技场模式选择页）→ 从这里接着导航进去。
        navigator.navigate(
            spec.name,
            lobby_screen=resume_screen,
            already_at=point.entry,
        )


def _install_finish_home(
    runner: Any,
    navigator: Optional[Epic7Navigator],
    runtime: Runtime,
    *,
    mode: str,
) -> None:
    """给路线装上「收尾回首页」钩子。

    契约（由 Runner 侧声明，见 ``ModeRunnerBase._close_out``）：**绝不抛异常**，
    失败返回原因字符串、成功返回 ``None``；调用方把它写进日志但**不改退出码**。

    为什么不能直接让 ``return_home()`` 抛到外面：任务本身已经成功了（跑满轮次 /
    资源耗尽都算正常结论），不能因为「没走回家」就让整次运行报失败 —— 用户看到的
    会是「运行失败」，而实际上该干的活都干完了。

    ⚠️ 干跑 / 不需要导航的路线（``survivor``）传进来的 ``navigator`` 是 ``None``，
    这里直接不装 —— 少了钩子，Runner 那边就是「零行为」，不需要各处加 dry_run 特判。
    """
    if navigator is None:
        return

    def finish_at_home() -> Optional[str]:
        try:
            navigator.return_home()
        except ManualStop:
            # 用户在收尾阶段按了 P：这不是「回不了家」，是「别动了」。
            # 照实记一笔就收手，既不重试也不改结论。
            runtime.log(f"模式={mode} 收尾=回首页被手动停止 处理=放弃收尾")
            return "用户手动停止"
        except Exception as error:  # noqa: BLE001 —— 契约要求绝不外抛
            return f"{type(error).__name__}: {error}"
        runtime.log(f"模式={mode} 收尾=已回到首页 状态=可以衔接下一个任务")
        return None

    # 基类路线读类属性 `_finish_home`，竞技场读实例属性 `finish_home`（它是裸定义）。
    # 两个都设：设错的那个不会有人读，比按 runner_type 分支判断更抗改。
    runner._finish_home = finish_at_home
    if hasattr(runner, "finish_home"):
        runner.finish_home = finish_at_home


def run_mode(
    *,
    spec: ModeSpec,
    dry_run: bool,
    max_cycles: int | None,
    start_state: str,
    window_backend: str = "emulator",
    stop_file: Path | None = None,
) -> RunResult:
    spec.validate_backend(window_backend)
    if (
        spec.name == "shop_refresh"
        and not dry_run
        and not LIVE_TRANSACTIONS_VERIFIED
    ):
        raise RuntimeError(
            "刷书签目标商品和购买价格尚未通过当前客户端实证，"
            "当前只允许空跑采样"
        )
    runtime = _build_runtime(
        spec.name,
        dry_run,
        window_backend=window_backend,
        stop_file=stop_file,
    )
    template_root = ROOT / "games" / "epic7" / "templates"
    # 先把状态机建好：接力探针要用它的锚点去认画面（只认，不点）。
    machine: Any = spec.build_machine(
        template_root, start_state, window_backend
    )
    navigator = None
    if not dry_run:
        runtime.set_capture_guard(
            Epic7GlobalPopupGuard(
                load_network_reconnect_templates(template_root / "global"),
                intimacy_templates=load_intimacy_level_up_templates(
                    template_root / "global"
                ),
                friendship_templates=load_friendship_points_templates(
                    template_root / "global"
                ),
                friend_request_templates=load_friend_request_templates(
                    template_root / "story"
                ),
                # 骑士团签到弹窗（每天第一次进骑士团出现），模板放在 navigation 下，
                # 与骑士团/世界首领战那两个导航锚点同目录。
                knights_signin_templates=load_knights_signin_templates(
                    template_root / "navigation"
                ),
                # 「领取支援物品」弹窗（进骑士团时团员支援到账），同放 navigation 下。
                gift_support_templates=load_gift_support_templates(
                    template_root / "navigation"
                ),
            )
        )
        if spec.needs_navigation:
            navigator = Epic7Navigator(
                build_navigation_templates(template_root),
                runtime,
                backend=window_backend,
            )
            _enter_mode(spec, machine, navigator, runtime)
    runner_options: dict[str, Any] = {}
    if navigator is not None:
        def recover_to_mode() -> None:
            # 恢复**不带**接力探针：恢复的语义是「退回本路线的已知起点重开」，
            # 调用方紧接着就会 reset_after_recovery()，半路接管会跟它打架。
            lobby_screen = navigator.return_home()
            navigator.navigate(spec.name, lobby_screen=lobby_screen)

        def report_blocked_recovery(message: str) -> None:
            runtime.log(message)
            runtime.save_diagnostic("recovery_blocked")

        recovery_gate = RecoveryGate(
            recover_to_mode,
            on_blocked=report_blocked_recovery,
        )
        runner_options["recovery"] = recovery_gate.recover
        runner_options["recovery_gate"] = recovery_gate
    if spec.name == "arena" and not dry_run:
        runner_options["purchase_stamp_path"] = ROOT / "runtime_logs" / "arena_ticket_purchase.txt"
        # 每局结算画面留一张盘，给「胜负判得对不对」留可回看的证据（见 ArenaRunner）。
        runner_options["outcome_frame_dir"] = ROOT / "docs" / "manual_review" / "arena"
    runner = spec.runner_type(machine, runtime, **runner_options)
    _install_finish_home(runner, navigator, runtime, mode=spec.name)
    completed = runner.run(max_cycles=max_cycles)
    # 战绩文案只有竞技场会给；别的路线拿不到这个方法，就留 None（通知里不显示）。
    summary = getattr(runner, "outcome_summary", None)
    return RunResult(
        completed_cycles=completed,
        resource_exhausted=bool(getattr(runner, "resource_exhausted", False)),
        outcome_summary=summary() if summary is not None else None,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified game automation")
    parser.add_argument("--game", choices=["epic7"], default="epic7")
    parser.add_argument("--mode", choices=sorted(MODE_SPECS), default="arena")
    parser.add_argument("--live", action="store_true", help="allow mouse clicks")
    parser.add_argument("--confirm", default="", help="must be RUN when --live is used")
    parser.add_argument("--max-cycles", type=int, help="stop after this many completed cycles")
    parser.add_argument("--start-state", help="resume state; valid values depend on --mode")
    parser.add_argument(
        "--window-backend",
        choices=["emulator", "pc"],
        default="emulator",
        help="capture/input backend: emulator (LDPlayer) or pc (Epic Seven PC client)",
    )
    parser.add_argument("--stop-file", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "hero_synthesis" and args.max_cycles is None:
        # 英雄合成固定跑一遍列表，无需指定次数
        args.max_cycles = 1
    if args.mode == "world_boss" and args.max_cycles is None:
        # 世界首领战每天固定 2 次（主页「剩余/上限」就是 2），无需指定次数。
        # 与 launcher.py / desktop/catalog.py 三处保持一致（都被测试钉住）。
        args.max_cycles = 2
    if args.mode == "knights_donation" and args.max_cycles is None:
        # 骑士团捐赠每天跑一遍就够：请求支援一天只能发一次、红点领完就没了。
        # 同上，与 launcher.py / desktop/catalog.py 三处保持一致。
        args.max_cycles = 1
    if args.live and args.confirm != "RUN":
        raise SystemExit("实跑模式需要附加参数：--live --confirm RUN")
    if args.live and (args.max_cycles is None or args.max_cycles <= 0):
        raise SystemExit("实跑模式要求 --max-cycles 为正数")
    if args.live and args.start_state is not None:
        raise SystemExit("--start-state 仅在空跑诊断模式可用")
    spec = get_mode(args.mode)
    try:
        spec.validate_backend(args.window_backend)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    try:
        start_state = spec.resolve_state(args.start_state)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    started_at = time.monotonic()
    try:
        result = run_mode(
            spec=spec,
            dry_run=not args.live,
            max_cycles=args.max_cycles,
            start_state=start_state,
            window_backend=args.window_backend,
            stop_file=Path(args.stop_file) if args.stop_file else None,
        )
    except ManualStop as error:
        print(f"手动停止 模式={args.mode} 原因={error}", flush=True)
        return 130
    except RuntimeError as error:
        _notify_live(
            live=args.live,
            mode=args.mode,
            status="failed",
            elapsed_seconds=_elapsed_seconds(started_at),
            error=error,
        )
        print(f"运行失败 模式={args.mode} 原因={error}", flush=True)
        return 1
    except Exception as error:
        _notify_live(
            live=args.live,
            mode=args.mode,
            status="failed",
            elapsed_seconds=_elapsed_seconds(started_at),
            error=error,
        )
        raise

    status = "resource" if result.resource_exhausted else "completed"
    _notify_live(
        live=args.live,
        mode=args.mode,
        status=status,
        elapsed_seconds=_elapsed_seconds(started_at),
        completed_cycles=result.completed_cycles,
        target_cycles=args.max_cycles,
        outcome_summary=result.outcome_summary,
    )
    record = f" 战绩=({result.outcome_summary})" if result.outcome_summary else ""
    print(
        f"完成 模式={args.mode} 轮次={result.completed_cycles}{record}",
        flush=True,
    )
    return 2 if result.resource_exhausted else 0


if __name__ == "__main__":
    raise SystemExit(main())
