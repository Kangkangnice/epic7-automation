import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

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
from auto_game_unified.games.epic7.daily_tasks import (
    DAILY_TASKS,
    DailyReport,
    run_daily_tasks,
)
from auto_game_unified.games.epic7.finish_home import _assert_finish_home_declared
from auto_game_unified.games.epic7.public_flow_verification import (
    assert_public_flow_verification_declared,
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
    "labyrinth_stone": "迷宫强化石",
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


class HomeReturn:
    """"回大厅"这一步的统一入口：**10 条路线一律走 v2**。

    ⚠️ 这里原本是「这条路线走新流程还是老流程」的分派器（一张 ``HOME_RETURN_V2_MODES``
    白名单 + 一段 ``if``）。2026-09-26 用户拍板「肯定要替换的，怎么可能并存呢」，
    白名单整表删除、**老流程整段删除**，所以现在**没有分叉了**：本对象只是把调用
    转给 ``Epic7Navigator.return_home``（它自己就是 v2 的薄封装）。

    为什么要继续留这么一个对象，而不是让 4 个调用点直接 ``navigator.return_home()``：

    - **可替换**。「回大厅」是条慢路径（真跑要走好几个页面），测试想拿假实现顶掉
      它来单测别的逻辑时，替换这一个对象就行，不用去动 ``Epic7Navigator``
      身上那套真实能力。
    - **日志/调试**：``repr`` 里带路线名，出问题时一眼能看出是谁在回家。

    接口与导航器同形：``(*, stop_probe=None)``，返回「到家」的那一帧。
    """

    def __init__(
        self,
        navigator: Epic7Navigator,
        runtime: Runtime,
        *,
        mode: str,
    ) -> None:
        self._navigator = navigator
        self._runtime = runtime
        self._mode = mode

    def __call__(
        self, *, stop_probe: Optional[Callable[[np.ndarray], bool]] = None
    ) -> np.ndarray:
        return self._navigator.return_home(stop_probe=stop_probe)

    def __repr__(self) -> str:  # pragma: no cover - 只为人看日志/调试
        return f"<HomeReturn mode={self._mode} flow=v2>"


def _try_return_home_after_failure(
    home_return: HomeReturn,
    runtime: Runtime,
    *,
    mode: str,
) -> None:
    """异常退出前，尽力把游戏带回大厅。

    与收尾（``_install_finish_home``）的差别：**失败一律吞掉**。异常已经在往外抛了，
    这里再抛一个只会把真正的错因盖掉，用户看到的还是「回不了家」而不是「为什么挂」。

    另外**不再问用户**、也不重试 —— 异常现场已经存档（diagnostic），回家只是顺手
    收拾一下，不是纠错。
    """
    try:
        home_return()
    except ManualStop:
        runtime.log(f"模式={mode} 异常收尾=回首页被手动停止 处理=放弃收尾")
    except Exception as error:  # noqa: BLE001 —— 绝不能盖掉真正的错因
        runtime.log(
            f"模式={mode} 异常收尾=回首页失败 "
            f"原因={type(error).__name__}: {error} 处理=已忽略（原异常照旧抛出）"
        )
    else:
        runtime.log(f"模式={mode} 异常收尾=已回到首页 状态=可以衔接下一个任务")


def _enter_mode(
    spec: ModeSpec,
    machine: Any,
    navigator: Epic7Navigator,
    runtime: Runtime,
    home_return: HomeReturn,
) -> None:
    """把游戏送进本路线的起始位置。

    默认行为是「一路返回大厅 → 按路线重新导航进去」。带接力探针的路线改成边走边看：
    第一帧就落在接力点上就直接从那一步接着跑（停在准备战斗就继续打，不再退回对手列表重选）；
    落在别的支线页面上就照旧一路返回，而且**每返回一页都再看一眼**，中途扫到接力点就地接管，
    否则一直返回到大厅再走老流程。
    """
    if spec.resume_probe is None:
        lobby_screen = home_return()
        navigator.navigate(spec.name, lobby_screen=lobby_screen)
        return
    watch = _ResumeWatch(spec.resume_probe, machine, navigator)
    resume_screen = home_return(stop_probe=watch)
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
    home_return: Optional[HomeReturn],
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

    ⚠️ **还没接「收尾回首页」的路线**（``games/epic7/finish_home.FINISH_HOME_EXEMPT``）：
    目前只有 ``survivor`` 一条，理由与取舍见那张表。**其余 9 条全部已接**（2026-09-25 完成）。

    ⚠️ 干跑 / 不需要导航的路线传进来的 ``home_return`` 是 ``None``，这里直接不装 ——
    少了钩子，Runner 那边就是「零行为」，不需要各处加 dry_run 特判。
    """
    # 「每条路线都得对收尾表态」的自查在这里触发（import 阶段就报错，不会拖到串任务时）。
    # 放在本函数里是为了让它跟着「收尾回首页」这一整套规矩走，且不必动 modes.py。
    _assert_finish_home_declared()
    # 「每个公共流程都得对『动作验收』表态」的自查，同样在这里触发。
    #
    # ⚠️ **这一行是补上去的，原因值得记一笔**：`public_flow_verification` 那两个
    # `assert_*` 刚写出来时**只有测试在调**，生产代码一处都没有 ——
    # 也就是说文档承诺的「加载期报错」跟 `modes._assert_resume_declared` 一样
    # 是句空话。用户 2026-09-25 的原话是「我希望以后这些这个东西可以避免
    # **以文档和代码的形式严格遵循**」——「只在测试里跑」不算代码约束。
    #
    # 反向护栏（扫源码的 `assert_module_inventory_matches`）**不在这里调**：
    # 它要读磁盘源码，是开发期的检查，放在 `tests/test_public_flow_verification.py`
    # 里每次跑测试都过一遍就够，不该让每次实跑都去扫一遍文件。
    assert_public_flow_verification_declared()

    if home_return is None:
        return

    def finish_at_home() -> Optional[str]:
        try:
            home_return()
        except ManualStop:
            # 用户在收尾阶段按了 P：这不是「回不了家」，是「别动了」。
            # 照实记一笔就收手，既不重试也不改结论。
            runtime.log(f"模式={mode} 收尾=回首页被手动停止 处理=放弃收尾")
            return "用户手动停止"
        except Exception as error:  # noqa: BLE001 —— 契约要求绝不外抛
            return f"{type(error).__name__}: {error}"
        runtime.log(f"模式={mode} 收尾=已回到首页 状态=可以衔接下一个任务")
        return None

    # ⚠️ **必须是实例级 hasattr，不能查类**：`finish_home` 是在 ``__init__`` 里赋值的
    # 实例属性，`hasattr(ArenaRunner, "finish_home")` 恒为 False（类上看不到）。
    # `_finish_home` 是基类类属性，两种路线都能设（不读它的路线设了等于没设）。
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
    home_return = None
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
            # 「回大厅」走新流程还是老流程，由这一个对象说了算（口径见 HomeReturn）。
            home_return = HomeReturn(navigator, runtime, mode=spec.name)
            try:
                _enter_mode(spec, machine, navigator, runtime, home_return)
            except BaseException as error:
                # ⚠️ ``_enter_mode``（含里面的 ``navigator.navigate``）跑在下面
                # 「业务主循环」的 try 之外 —— 这里一旦炸，原本会直接逃出 ``run_mode``，
                # 每日任务只收到一个无声的 ``✗``，连原因都没有（2026-09-26 刷书签
                # 那次就是这么漏掉的）。所以这里先把原因记进日志、留一张诊断，
                # 再原样抛出让上层照常判定「本路线失败」。
                runtime.log(
                    f"模式={spec.name} 进入路线失败 "
                    f"原因={type(error).__name__}: {error}"
                )
                if runtime.diagnostic_dir is not None:
                    runtime.save_diagnostic(f"enter_mode_failed_{spec.name}")
                raise
    runner_options: dict[str, Any] = {}
    # ⚠️ 这里**只**给闸门，不给任何「恢复」回调：2026-09-26 用户拍板
    # 「回家触发完之后，回到首页，说明这个就结束了，不可能会再回到这个任务」⇒
    # 「回大厅重新导航、然后接着跑」整段删除（连带 ``recover_to_mode`` /
    # ``report_blocked_recovery``）。闸门现在只剩「战斗中禁止打断」一个职责，
    # 由 battle_supervisor 上锁/解锁、unknown_screen 读它（见 core/recovery.py）。
    runner_options["recovery_gate"] = RecoveryGate()
    if spec.name == "arena" and not dry_run:
        runner_options["purchase_stamp_path"] = ROOT / "runtime_logs" / "arena_ticket_purchase.txt"
        # 每局结算画面留一张盘，给「胜负判得对不对」留可回看的证据（见 ArenaRunner）。
        runner_options["outcome_frame_dir"] = ROOT / "docs" / "manual_review" / "arena"
    runner = spec.runner_type(machine, runtime, **runner_options)
    _install_finish_home(runner, home_return, runtime, mode=spec.name)
    try:
        completed = runner.run(max_cycles=max_cycles)
    except ManualStop:
        # 用户按 P 喊停 ⇒ 一个字都不动游戏（这是全线统一口径，见 runner_base._close_out）。
        raise
    except BaseException:
        # 异常也回家（**所有路线**，2026-09-26 起不再有白名单分叉）。
        # 用户 2026-09-25 拍板——「异常了也该走回大厅，包括战斗里，直接放弃这一局」。
        # 以前不回家的理由是「硬按 Back 可能把已承诺的战斗弄丢」，而 v2 处理这个问题
        # 的办法是**显式放弃**（暂停 → 放弃战斗 → 放弃确认），比撒手不管更干净。
        # ⚠️ 回家本身**绝不改退出码**：回到家也照旧往外抛，结论还是「运行失败」。
        if home_return is not None:
            _try_return_home_after_failure(home_return, runtime, mode=spec.name)
        raise
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
    parser.add_argument(
        "--daily",
        action="store_true",
        help="跑「每日任务」：把几条路线按固定次序串起来一次跑完（与 --mode 互斥）",
    )
    parser.add_argument(
        "--daily-tasks",
        default="",
        help=(
            "每日任务要跑哪些路线（逗号分隔）；留空=全部。"
            "每条可以带次数，例如 arena:3；不带就用该路线的每日默认次数。"
            f"可选：{','.join(task.mode for task in DAILY_TASKS)}"
        ),
    )
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


def _daily_pieces(raw: str) -> list[tuple[str, str]]:
    """把 ``--daily-tasks`` 切成 ``(路线名, 次数原文)``；次数没写就是空串。

    这一层只做切分与去空白，**不校验名字、也不解析次数** —— 那分别归
    ``normalize_selection``（会报成一句人话）与 ``_parse_daily_cycles``。
    """
    pieces: list[tuple[str, str]] = []
    for piece in raw.split(","):
        name, _, count = piece.partition(":")
        name, count = name.strip(), count.strip()
        if name:
            pieces.append((name, count))
    return pieces


def _parse_daily_selection(raw: str) -> list[str]:
    """把 ``--daily-tasks`` 的逗号分隔串解析成模式名列表；留空 = 全部。

    每一项可以带次数（``arena:3``）—— **次数在这里被丢掉**，它归
    ``_parse_daily_cycles`` 管。
    """
    if not raw.strip():
        return [task.mode for task in DAILY_TASKS]
    return [name for name, _ in _daily_pieces(raw)]


def _parse_daily_cycles(raw: str) -> dict[str, int]:
    """取出 ``--daily-tasks`` 里**显式写了次数**的那几条（``arena:3``）。

    没写次数的路线不出现在返回值里 ⇒ 执行器照用 ``DAILY_TASKS`` 的默认次数。
    次数写坏了（不是正整数）在命令行入口就报错：静默退回默认值会让
    「我明明写了 3」变成一个没人发现的坑。
    """
    overrides: dict[str, int] = {}
    for name, count in _daily_pieces(raw):
        if not count:
            continue
        try:
            value = int(count)
        except ValueError as error:
            raise SystemExit(f"每日任务的次数不是整数：{name}:{count}") from error
        if value <= 0:
            raise SystemExit(f"每日任务的次数必须是正整数：{name}:{count}")
        overrides[name] = value
    return overrides


def _build_daily_probe(
    *,
    window_backend: str,
    stop_file: Path | None,
) -> tuple[Runtime, Epic7Navigator]:
    """建「段间检查」用的 ``(runtime, navigator)``。

    段间检查只做两件事：截一帧看是不是大厅、不在就 ``return_home()``。所以这里
    只需要一个能截图/点返回的 runtime 加一个能认页面的 navigator，不必带状态机。
    诊断/日志单独归到 ``epic7_daily_probe`` 名下，不跟任何一条路线的日志混。
    """
    runtime = _build_runtime(
        "daily_probe",
        dry_run=False,
        window_backend=window_backend,
        stop_file=stop_file,
    )
    template_root = ROOT / "games" / "epic7" / "templates"
    navigator = Epic7Navigator(
        build_navigation_templates(template_root),
        runtime,
        backend=window_backend,
    )
    return runtime, navigator


def _notify_daily(
    *,
    live: bool,
    report: DailyReport,
    elapsed_seconds: int,
) -> None:
    """每日任务整轮的通知（与单路线分开，标题/内容都是汇总口径）。"""
    if not live:
        return
    if report.stopped_by_user:
        title = "第七史诗：每日任务已手动停止"
    elif report.aborted_reason:
        title = "第七史诗：每日任务中途中止"
    elif report.any_failed:
        title = "第七史诗：每日任务完成（有失败）"
    else:
        title = "第七史诗：每日任务已完成"
    lines = [f"耗时：{elapsed_seconds} 秒"]
    for outcome in report.outcomes:
        mark = "✓" if outcome.ok else "✗"
        detail = f"（{outcome.detail}）" if outcome.detail else ""
        lines.append(f"{outcome.label} {mark}{detail}")
    if report.aborted_reason:
        lines.append(f"中止原因：{report.aborted_reason}")
    try:
        send_qqbot_c2c(title, "\n".join(lines))
    except Exception as notification_error:  # noqa: BLE001 —— 通知挂了不改结论
        print(f"QQ 通知失败：{type(notification_error).__name__}", flush=True)


def _run_daily(args: argparse.Namespace) -> int:
    """跑「每日任务」编排。退出码沿用单路线那套：0 全成 / 1 有失败 / 130 手动停。"""
    started_at = time.monotonic()
    report = run_daily_tasks(
        selected=_parse_daily_selection(args.daily_tasks),
        cycles_override=_parse_daily_cycles(args.daily_tasks),
        dry_run=not args.live,
        window_backend=args.window_backend,
        stop_file=Path(args.stop_file) if args.stop_file else None,
        run_mode=run_mode,
        build_probe=lambda: _build_daily_probe(
            window_backend=args.window_backend,
            stop_file=Path(args.stop_file) if args.stop_file else None,
        ),
        # 段间回大厅也走「按路线分流」这条口径（见 HomeReturn）。
        build_home_return=lambda navigator, runtime, mode: HomeReturn(
            navigator, runtime, mode=mode
        ),
    )
    elapsed = _elapsed_seconds(started_at)
    _notify_daily(live=args.live, report=report, elapsed_seconds=elapsed)
    print(f"每日任务汇总：{report.summary_line()}", flush=True)
    if report.stopped_by_user:
        return 130
    if report.aborted_reason or report.any_failed:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.daily:
        # `--mode` 此时无意义（它有默认值 "arena"，无法可靠区分「用户显式传了」），
        # 所以不报错、直接忽略 —— 界面与命令行都不会同时传这两个。
        if args.live and args.confirm != "RUN":
            raise SystemExit("实跑模式需要附加参数：--live --confirm RUN")
        return _run_daily(args)
    if args.mode == "hero_synthesis" and args.max_cycles is None:
        # 英雄合成固定跑一遍列表，无需指定次数
        args.max_cycles = 1
    if args.mode == "world_boss" and args.max_cycles is None:
        # 世界首领战每天固定 2 次（主页「剩余/上限」就是 2），无需指定次数。
        # 与 launcher.py / desktop/catalog.py 三处保持一致（都被测试钉住）。
        args.max_cycles = 2
    if args.mode in ("knights_donation", "labyrinth_stone") and args.max_cycles is None:
        # 骑士团捐赠每天跑一遍就够：请求支援一天只能发一次、红点领完就没了。
        # 迷宫强化石同理：迷宫采购一天一次。
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
