import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auto_game_unified.core.hotkey import WindowsPStopHotkey
from auto_game_unified.core.pushplus import send_pushplus
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.window import Epic7Window
from auto_game_unified.core.pc_window import Epic7PcWindow
from auto_game_unified.games.epic7.evidence.shop_refresh import (
    LIVE_TRANSACTIONS_VERIFIED,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS, ModeSpec, get_mode
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates
from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_intimacy_level_up_templates,
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
}


@dataclass(frozen=True)
class RunResult:
    completed_cycles: int
    resource_exhausted: bool = False


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
    if error is not None:
        lines.insert(1, f"原因：{error}")
        lines.append(
            f"诊断目录：{ROOT / 'runtime_diagnostics' / f'epic7_{mode}'}"
        )
    try:
        send_pushplus(titles[status], "\n".join(lines))
    except Exception as notification_error:
        print(
            f"PushPlus 通知失败：{type(notification_error).__name__}",
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
    if window_backend == "pc":
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
            )
        )
        if spec.needs_navigation:
            navigator = Epic7Navigator(
                build_navigation_templates(template_root),
                runtime,
                backend=window_backend,
            )
            lobby_screen = navigator.return_home()
            navigator.navigate(spec.name, lobby_screen=lobby_screen)
    machine: Any = spec.build_machine(
        template_root, start_state, window_backend
    )
    runner_options: dict[str, Any] = {}
    if navigator is not None:
        def recover_to_mode() -> None:
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
    runner = spec.runner_type(machine, runtime, **runner_options)
    completed = runner.run(max_cycles=max_cycles)
    return RunResult(
        completed_cycles=completed,
        resource_exhausted=bool(getattr(runner, "resource_exhausted", False)),
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
    )
    print(f"完成 模式={args.mode} 轮次={result.completed_cycles}", flush=True)
    return 2 if result.resource_exhausted else 0


if __name__ == "__main__":
    raise SystemExit(main())
