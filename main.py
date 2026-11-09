import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import numpy as np

from auto_game_unified.core.data_paths import data_root
from auto_game_unified.core.matcher import set_active_backend
from auto_game_unified.core.hotkey import WindowsPStopHotkey
from auto_game_unified.core.qqbot import send_qqbot_c2c
from auto_game_unified.core.recovery import RecoveryGate
from auto_game_unified.core.runtime import ManualStop, Runtime
from auto_game_unified.core.window import Epic7Window
from auto_game_unified.core.pc_window import (
    PC_INPUT_ENV,
    PC_INPUT_FOREGROUND,
    PC_INPUT_MODES,
    Epic7PcWindow,
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
from auto_game_unified.games.epic7.template_paths import (
    is_pc,
    resolve_template_dir,
)
from auto_game_unified.games.epic7.route_metadata import (
    assert_route_metadata_consistent,
)
from auto_game_unified.games.epic7.modes import (
    MODE_LABELS,
    MODE_SPECS,
    ModeSpec,
    ResumePoint,
    ResumeProbe,
    get_mode,
)
from auto_game_unified.games.epic7.navigation import Epic7Navigator, build_navigation_templates
from auto_game_unified.games.epic7.global_popups import (
    Epic7GlobalPopupGuard,
    load_account_rank_up_templates,
    load_arena_rank_reward_templates,
    load_battle_record_templates,
    load_weekly_rank_start_templates,
    load_friend_request_templates,
    load_friendship_points_templates,
    load_gift_claim_templates,
    load_gift_support_templates,
    load_intimacy_level_up_templates,
    load_knights_growth_rank_templates,
    load_knights_signin_templates,
    load_knights_weekly_reward_templates,
    load_uncontrollable_templates,
    load_tutorial_skip_templates,
    load_tutorial_unlock_templates,
    load_date_change_templates,
    load_knights_activity_templates,
    load_login_reward_templates,
    load_network_reconnect_templates,
    load_pet_gift_templates,
    load_reward_notice_templates,
    load_side_story_notice_templates,
    load_web_network_error_templates,
    load_worldboss_support_reward_templates,
)
# PC 专属弹窗扩展：新判据与模板全在这个模块里，模拟器分支不会 import 之后
# 调用它的注入函数（见下面 run_mode 里的 is_pc 判断）。
from auto_game_unified.games.epic7.global_popups_pc import install_pc_only_popups


ROOT = Path(__file__).resolve().parent
# 运行产物（日志、诊断）的根目录。源码运行时与 ROOT 是同一个目录；
# 打包安装后变成 %LOCALAPPDATA%\Epic7AutoAssistant（安装目录只读，写不进去）。
# 规则见 core/data_paths.py。
DATA_ROOT = data_root()
# 中文名从 ``modes.MODE_SPECS`` 派生（那边是唯一来源），本模块不再自己写一份。
# 以前这里是第二张表，与 ``navigation.MODE_LABELS`` 各自维护 ⇒ 实测漂移过
# （survivor 一处有、一处没有）。


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
            f"诊断目录：{DATA_ROOT / 'runtime_diagnostics' / f'epic7_{mode}'}"
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
        # 输入通道：默认前台；后台需本机探针实测通过后由界面/命令行显式开启。
        game_window.set_input_mode(
            os.environ.get(PC_INPUT_ENV, PC_INPUT_FOREGROUND)
        )
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
        # 滑动：模拟器走 adb 注入；PC 端 2026-11-02 起也实现了（SendInput 拖拽），
        # 刷书签 / 骑士团捐赠 / 迷宫强化石 / 幸存者 四条路线因此才可能移植。
        swipe=(
            game_window.swipe
            if getattr(game_window, "swipe", None) is not None
            else None
        ),
        wake=game_window.wake,
        back=game_window.back,
        dry_run=dry_run,
        diagnostic_dir=DATA_ROOT / "runtime_diagnostics" / f"epic7_{mode}",
        log_path=DATA_ROOT / "runtime_logs" / f"epic7_{mode}.log",
        stop_requested=None if dry_run else stop_requested,
        # 跑到一半的通道自检（导航「连续点不动」时会调）。干跑与 PC 后端不装配：
        # 干跑不该去动 adb 服务，PC 后端也没有这条通道。
        input_channel_probe=(
            game_window.ensure_input_channel
            if window_backend == "emulator" and not dry_run
            else None
        ),
    )
    # 模拟器窗口也要能往运行日志里说话（例如「最小化已自动还原」）。
    game_window.set_event_sink(runtime.log)
    if not dry_run and window_backend == "emulator":
        # 实跑才需要点击通道，开跑前自检一次：模拟器重启后 host 侧 adb server
        # 常还挂在旧连接上（设备 offline），此时画面看得见、点不动，
        # 上层只会看到「点击验收无效」并把整条路线打挂。
        # ⚠️ 必须放在接上日志出口**之后**：自检过程说的每一句（探了几次、
        # 重启了 adb 还是模拟器）都靠这个出口落盘。放前面时这些话一条都打不出来
        # （2026-10-04 实测全仓库只剩 2 条自检记录，且都不是开跑前那次），
        # 事后只能猜到底发生了什么。
        game_window.ensure_input_channel()
    if calibration is not None:
        runtime.log(
            "模式=PC初始化 "
            f"调整前={calibration.before.width}x{calibration.before.height} "
            "目标=1920x1080 "
            f"调整后={calibration.after.width}x{calibration.after.height} "
            f"是否调整={'是' if calibration.adjusted else '否'} "
            "识别画布=1982x1132 模板来源=templates（PC 专属图优先，缺图回落共享图）"
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
    # 「同一事实抄在多处、只改了一部分」的自查：模式中文名与固定次数。
    #
    # ⚠️ 它**要读磁盘源码**（AST 扫 main.py 里的固定次数），
    # 但比 public_flow_verification 的反向护栏便宜得多（只 parse 两个小文件），
    # 所以放在生产路径上跑 —— 这样「新路线漏改中文名」在实跑启动时就报错，
    # 而不是等用户从另一个入口启动才发现。
    assert_route_metadata_consistent()

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
    # 界面传给**这一条路线**的参数（已经从 ``{路线名: {...}}`` 里按名字取好）。
    # 只有声明了 ``runner_options`` 的路线才拿得到 —— 见下面那一处合并。
    params: Optional[Mapping[str, Any]] = None,
) -> RunResult:
    # 路线级的运行前闸门（比如「刷书签会真花钱，没实证过就不许实跑」）。
    # ⚠️ 必须留在建 runtime **之前**：闸门拦下的路线，不该先开一个窗口再报错。
    # 闸门本体与路线绑在 ``modes.MODE_SPECS`` 里，这里不认识任何具名路线。
    if spec.preflight is not None:
        blocked = spec.preflight(spec.name, dry_run)
        if blocked is not None:
            raise RuntimeError(blocked)
    runtime = _build_runtime(
        spec.name,
        dry_run,
        window_backend=window_backend,
        stop_file=stop_file,
    )
    # ⚠️ 平台差异只在最上游注入一次：往下所有 ``template_root / "story"`` 之类
    # 得到的都是同一个「会按平台挑图」的目录，业务代码不需要知道平台的存在。
    set_active_backend(window_backend)
    template_root = resolve_template_dir(
        ROOT / "games" / "epic7" / "templates", window_backend
    )
    # 先把状态机建好：接力探针要用它的锚点去认画面（只认，不点）。
    machine: Any = spec.build_machine(template_root, start_state)
    navigator = None
    home_return = None
    if not dry_run:
        guard = (
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
                # 「支线故事通知」（新支线解锁时弹一次，盖在结算页上 ⇒ 等待结算 45 秒无进展）。
                side_story_notice_templates=load_side_story_notice_templates(
                    template_root / "global"
                ),
                # 「获得奖励」通知（星星/任务奖励发放时弹一次，盖住关卡入口）。
                # ⚠️ 路线可声明关闭：英雄合成的「传送奖励」层、骑士团捐赠的
                # 「支援成功奖励」层与它是同一套 UI，守卫抢在状态机之前点掉会让
                # 对应动作的 target_pages 永远不成立（4 次重试后提前收工）。
                # 走 spec 字段而不是 ``if spec.name == ...``，新路线只改自己的声明。
                reward_notice_templates=(
                    load_reward_notice_templates(template_root / "global")
                    if spec.reward_notice_guard
                    else None
                ),
                # 「领取支援物品」（骑士团支援资源领取后弹一次，盖住骑士团主页）。
                gift_claim_templates=load_gift_claim_templates(
                    template_root / "global"
                ),
                # 「账号 Rank 提升」（账号升级时弹一次，盖住战斗画面与回家路径）。
                account_rank_up_templates=load_account_rank_up_templates(
                    template_root / "global"
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
                # 「获得每周骑士团点数奖励」弹窗（每周一结算），同放 navigation 下。
                knights_weekly_reward_templates=load_knights_weekly_reward_templates(
                    template_root / "navigation"
                ),
                # 「世界首领辅助队伍奖励」弹窗（同僚团员借了你的辅助队伍并拿到奖励后，
                # 进世界首领战主页时弹出）。与上面三个骑士团弹窗同目录、同形同理由。
                # ⚠️ 2026-10-19 那次「世界首领战 ✗」就是它：弹窗把底页压暗 ⇒ 主页认不出来
                # ⇒ 导航转场 `骑士团主页 → worldboss_home` 一路等到超时。
                worldboss_support_reward_templates=load_worldboss_support_reward_templates(
                    template_root / "navigation"
                ),
                # 「段位升级奖励」弹窗：竞技场打完一局、点掉「段位提升」之后紧接着弹出的
                # 第二层，首次升至某段位才出现一次。与上面那个同目录（都盖在底页上）。
                # ⚠️ 2026-10-20 08:02 那次「竞技场 ✗」就是它：竞技场没有任何判据认它
                # ⇒ 转场一路等到 45 秒上限。放到守卫里，任何路线撞上都能消掉。
                arena_rank_reward_templates=load_arena_rank_reward_templates(
                    template_root / "navigation"
                ),
                # 「战斗记录」弹窗：**进竞技场时就弹**的防守战报 / 段位变动通知
                # （与上面那层「打完一局才弹」的段位奖励不是一件事）。
                # ⚠️ 2026-10-30 18:27 那次「竞技场 ✗」就是它：它盖住对手列表 ⇒
                # 导航判不出页面 ⇒ 只等 129 秒后转场失败；随后回家又栽在快捷菜单上，
                # **整轮每日任务只跑完竞技场一条就中止**，后面 5 条路线一条没跑。
                battle_record_templates=load_battle_record_templates(
                    template_root / "navigation"
                ),
                # 「新的每周排名开始！」：每周结算后进竞技场时一次性弹出的段位重置通知。
                # ⚠️ 2026-11-09 08:52 那次竞技场 ✗ 就是它没登记：守卫认不出 ⇒
                # 导航只等 106 秒后报「竞技场模式选择 → arena_ready 失败」。
                weekly_rank_start_templates=load_weekly_rank_start_templates(
                    template_root / "navigation"
                ),
                # 「骑士团成长Rank提升」弹窗：只在骑士团成长等级提升时出现（低频），
                # 但撞上就必然卡住整条路线 —— 2026-10-30 19:48 世界首领战那次 ✗ 就是它：
                # 从快捷菜单点「骑士团」后被它盖住，导航只等到 2 分钟上限报「转场失败」。
                # 同一层弹窗 10-08 的骑士团捐赠诊断帧里也出现过，一直没登记。
                knights_growth_rank_templates=load_knights_growth_rank_templates(
                    template_root / "navigation"
                ),
                # 宠物小屋礼物角标（快捷菜单页，宠物送礼时挂出的小角标），放 global 下。
                pet_gift_templates=load_pet_gift_templates(template_root / "global"),
                # 「网页网络错误」那条黑底白字的长条（游戏内 WebView 上，横屏）。
                # ⚠️ 放 **navigation** 下，与它管的那两张网页锚点
                # （``web_activity_gate`` / ``web_community``）同目录 ——
                # 它们说的是同一个 WebView 上的事，模板别散到两处去。
                web_network_error_templates=load_web_network_error_templates(
                    template_root / "navigation"
                ),
                # 2026-11-03：游戏按时间自己弹的两条，谁跑都会撞上。
                #   变更日期：把页面强制切回大厅 ⇒ 主线在「等待通关」干等 46 秒超时；
                #   登录奖励：不吃 ESC ⇒ 收尾「连按 2 次 ESC 页面不动」回首页失败。
                # 模板只有 PC 版，模拟器口径下 load 成 None ⇒ 该条整段跳过（行为不变）。
                date_change_templates=load_date_change_templates(
                    template_root / "global"
                ),
                # 「骑士团活动」整屏页（PC 上 ESC 关不掉，会导致回首页失败、整链中止）。
                # 图只在 pc/ 里 ⇒ 模拟器加载成 None ⇒ 整段跳过，行为不变。
                knights_activity_templates=load_knights_activity_templates(
                    template_root / "global"
                ),
                # 「无法控制」剧情弹窗（主线关卡入口页会弹出，整页盖住）。
                # 图只在 pc/ 里 ⇒ 模拟器加载成 None ⇒ 整段跳过。
                uncontrollable_templates=load_uncontrollable_templates(
                    template_root / "global"
                ),
                # 「轻触后解锁」教学遮罩（主线 Episode 4 第 11 关；吞点击也吞 ESC）。
                # 图只在 pc/ 里 ⇒ 模拟器加载成 None ⇒ 整段跳过。
                tutorial_unlock_templates=load_tutorial_unlock_templates(
                    template_root / "global"
                ),
                # 新手账号大厅右上角的「跳过教学 ✕」（把快捷菜单蓝四格顶掉的那块）。
                # 图只在 pc/ 里 ⇒ 模拟器加载成 None ⇒ 整段跳过。
                tutorial_skip_templates=load_tutorial_skip_templates(
                    template_root / "global"
                ),
                login_reward_templates=load_login_reward_templates(
                    template_root / "global"
                ),
            )
        )
        # PC 专属弹窗（「解锁缘分」等）：**只有** PC 分支会注入，模拟器连这一行
        # 都不会执行；守卫的构造参数一字未改，模拟器路径保持原样。
        if is_pc(template_root):
            guard = install_pc_only_popups(guard, template_root / "global")
        runtime.set_capture_guard(guard)
        if spec.needs_navigation:
            navigator = Epic7Navigator(
                build_navigation_templates(template_root),
                runtime,
                template_root=template_root,
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
    # 路线级的额外构造参数（比如竞技场实跑要落两个盘）。同样按注册表取，
    # 这里不认具名路线 —— 新增路线需要专属参数时，在 ``modes.py`` 注册项旁边写。
    if spec.runner_options is not None:
        runner_options.update(spec.runner_options(DATA_ROOT, dry_run, params or {}))
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
        help="跑「每日任务」：把给定的几条路线依次串起来一次跑完（与 --mode 互斥）",
    )
    parser.add_argument(
        "--daily-tasks",
        default="",
        help=(
            "每日任务要跑哪些路线（逗号分隔，**次序即执行顺序**）；"
            "留空=默认清单（" + "、".join(task.mode for task in DAILY_TASKS) + "）。"
            "每条可以带次数，例如 arena:3；不带就用该路线的默认次数。"
            f"可选：{','.join(sorted(MODE_SPECS))}"
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
    parser.add_argument(
        "--pc-input-mode",
        choices=list(PC_INPUT_MODES),
        # ⚠️ 不能给 default=foreground：桌面界面的 Worker 是通过环境变量
        # EPIC7_PC_INPUT_MODE 把用户选的通道传下来的，无条件写默认值会把
        # background 悄悄抹回 foreground（界面勾了「不占用前台」却照样抢前台）。
        # 只有**命令行显式传了**才覆盖环境变量。
        default=None,
        help=(
            "PC 端输入通道：foreground=抢前台（默认，始终可用）；"
            "background=不抢前台（SetCursorPos + PostMessage，需本机实测通过）。"
            "不传则沿用 EPIC7_PC_INPUT_MODE 环境变量"
        ),
    )
    parser.add_argument("--stop-file", help=argparse.SUPPRESS)
    # 界面传下来的路线参数（``{路线名: {参数名: 值}}`` 的 JSON）。
    # 走文件不走命令行：Windows 命令行过一遍引号与编码，中文容易被吃掉。
    # 现在没有任何路线消费它 —— 通道先通，将来加参数不用回头改这里。
    parser.add_argument("--params-file", help=argparse.SUPPRESS)
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
    """把 ``--daily-tasks`` 的逗号分隔串解析成模式名列表；留空 = 默认清单。

    次序**照原样保留**（勾选先后就是执行顺序，见 ``normalize_selection``）。

    每一项可以带次数（``arena:3``）—— **次数在这里被丢掉**，它归
    ``_parse_daily_cycles`` 管。
    """
    if not raw.strip():
        return [task.mode for task in DAILY_TASKS]
    return [name for name, _ in _daily_pieces(raw)]


def _parse_daily_cycles(raw: str) -> dict[str, int]:
    """取出 ``--daily-tasks`` 里**显式写了次数**的那几条（``arena:3``）。

    没写次数的路线不出现在返回值里 ⇒ 执行器照用该路线在 ``MODE_SPECS`` 里的默认次数。
    次数写坏了在命令行入口就报错：静默退回默认值会让「我明明写了 3」变成一个
    没人发现的坑。

    下限以路线的 ``ModeSpec.min_cycles`` 为准（正常 1；「刷书签」是 0 —— 只扫一遍、
    不付费刷新）。界面所有启动都走 ``--daily --daily-tasks``（见 ``desktop/worker.py``），
    所以这条解析**必须**放行 ``shop_refresh:0``，否则界面上那个默认的 0 一按开始就报错。
    """
    overrides: dict[str, int] = {}
    for name, count in _daily_pieces(raw):
        if not count:
            continue
        try:
            value = int(count)
        except ValueError as error:
            raise SystemExit(f"每日任务的次数不是整数：{name}:{count}") from error
        # 认不出的名字取不到规格 ⇒ 退回 1（也就是「必须为正」的老口径），
        # 让 ``normalize_selection`` 照旧报「未知路线」。
        minimum = getattr(MODE_SPECS.get(name), "min_cycles", 1)
        if value < minimum:
            raise SystemExit(
                f"每日任务的次数不能为负数：{name}:{count}"
                if minimum == 0
                else f"每日任务的次数必须是正整数：{name}:{count}"
            )
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
    set_active_backend(window_backend)
    template_root = resolve_template_dir(
        ROOT / "games" / "epic7" / "templates", window_backend
    )
    navigator = Epic7Navigator(
        build_navigation_templates(template_root),
        runtime,
        template_root=template_root,
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
    # ⚠️ **用户手动按停止键 ⇒ 不发通知**（2026-10-30 用户要求）。
    #
    # 那是他自己做的事，人就在电脑前面 —— 再推一条"已手动停止"纯属打扰。
    # 通知只留给**程序自己跑出来的结论**（失败 / 中止 / 完成），
    # 也就是他不在看着的时候才需要手机响一下。
    # 单路线那边早就是这个口径（``ManualStop`` 直接返回 130、不通知），
    # 这里漏了，所以手动停也会推一条。
    if report.stopped_by_user:
        return
    if report.aborted_reason:
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


def _load_params(path: str | None) -> dict[str, dict[str, Any]]:
    """读界面传下来的路线参数（``{路线名: {参数名: 值}}``）。

    读不出来就当没有 —— **参数不该阻断整轮任务**，这与「存档读坏了不许崩」是同一条
    口径（见 ``desktop/session.py`` 的约定 1）。路线名在这里不校验：
    认不出的路线自然不会被任何 ``run_mode`` 取到。
    """
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {name: dict(value) for name, value in payload.items() if isinstance(value, dict)}


def _run_daily(args: argparse.Namespace) -> int:
    """跑「每日任务」编排。退出码沿用单路线那套：0 全成 / 1 有失败 / 130 手动停。"""
    started_at = time.monotonic()
    report = run_daily_tasks(
        selected=_parse_daily_selection(args.daily_tasks),
        cycles_override=_parse_daily_cycles(args.daily_tasks),
        dry_run=not args.live,
        window_backend=args.window_backend,
        stop_file=Path(args.stop_file) if args.stop_file else None,
        params=_load_params(args.params_file),
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


def _apply_fixed_cycles(args: argparse.Namespace) -> None:
    """次数由游戏规则决定的路线（``cycles_editable=False``）直接填上默认次数。

    例：世界首领战每天上限就是 2 次、英雄合成跑完一遍列表就结束 —— 这些路线
    命令行**不必**再传 ``--max-cycles``。

    ⚠️ 次数只在 ``modes.MODE_SPECS`` 里定义一次。以前这里是三条写死的 ``if``
    （各带一个魔数），与交互菜单 / ``desktop/catalog.py`` 三处手工对齐；
    注释虽写着「都被测试钉住」，实际只钉住了 catalog 一处，另两处改漏了没人知道。

    ⚠️ 用 ``.get()`` 而不是 ``get_mode()``：``--mode`` 写了不存在的名字时，要让它
    照旧在后面 ``get_mode()`` 那里报错，不能在这里提前抛 —— 否则会抢在
    「实跑需要 --confirm RUN」等参数校验前面，报错信息变得莫名其妙。
    """
    if args.max_cycles is not None:
        return
    spec = MODE_SPECS.get(args.mode)
    if spec is not None and not spec.cycles_editable:
        args.max_cycles = spec.default_cycles


def _pc_live_precondition(window_backend: str) -> str | None:
    """PC 后端**实跑**前的窗口与权限前置检查，返回阻断原因（``None`` 表示可以跑）。

    为什么放在 CLI 边界而不是 ``run_mode``：``run_mode`` 要能被测试直接调用，
    而这条检查会去枚举真实窗口；放在命令行入口，既只跑一次，也不会拦住单测。

    为什么必须拦：Windows 的 UIPI 规定低权限进程不能往高权限窗口发输入。助手权限低于
    PC 客户端时，键鼠输入会被**静默**拦掉 —— 截图正常、识别正常、日志里每个动作都写
    「已点击」，游戏一动不动。这种故障看起来像模板过期或坐标算错，过去只能靠人猜。

    它不试图「自动提权」：提权要不要弹窗取决于那台机器的 UAC 设置，探不出来也不该猜。
    拦下来 + 给出下一步命令，比让 agent 在错的前提上试十分钟更有用。
    """
    if window_backend != "pc":
        return None
    # 延迟导入：模拟器路线不该为 PC 专用的检查付出启动开销。
    from auto_game_unified.desktop import preflight as preflight_module

    report = preflight_module.run_preflight(window_backend="pc")
    if report.status is preflight_module.PreflightStatus.PASS:
        return None
    return f"PC 后端实跑未就绪：{report.message}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # 输入通道是进程级设置：写进环境供 ``_build_runtime`` 读取（桌面端的子进程
    # 也走同一条路，见 desktop/worker.py）。放在这里统一落，避免两条入口各写一遍。
    # ⚠️ 只在 CLI **显式传参**时写：否则 Worker 设好的 background 会被默认值覆盖。
    if args.pc_input_mode is not None:
        os.environ[PC_INPUT_ENV] = args.pc_input_mode
    if args.daily:
        # `--mode` 此时无意义（它有默认值 "arena"，无法可靠区分「用户显式传了」），
        # 所以不报错、直接忽略 —— 界面与命令行都不会同时传这两个。
        if args.live and args.confirm != "RUN":
            raise SystemExit("实跑模式需要附加参数：--live --confirm RUN")
        return _run_daily(args)
    _apply_fixed_cycles(args)
    if args.live and args.confirm != "RUN":
        raise SystemExit("实跑模式需要附加参数：--live --confirm RUN")
    # 次数下限以路线的 ``min_cycles`` 为准（正常 1；「刷书签」是 0 —— 只扫不刷新）。
    # 用 ``MODE_SPECS.get`` 而不是 ``get_mode``：``--mode`` 写了不存在的名字时，
    # 要让它照旧在后面 ``get_mode()`` 那里报错（同 ``_apply_fixed_cycles`` 的说明）。
    if args.live:
        minimum = getattr(MODE_SPECS.get(args.mode), "min_cycles", 1)
        if args.max_cycles is None or args.max_cycles < minimum:
            raise SystemExit(
                "实跑模式要求 --max-cycles 为正数"
                if minimum > 0
                else "实跑模式的 --max-cycles 不能为负数"
            )
    if args.live and args.start_state is not None:
        raise SystemExit("--start-state 仅在空跑诊断模式可用")
    if args.live:
        blocked = _pc_live_precondition(args.window_backend)
        if blocked is not None:
            raise SystemExit(
                f"{blocked}\n\n"
                "先自检看清楚：python -m auto_game_unified.tools.live_check --backend pc\n"
                "标准做法（怎么提权、怎么判失败）：docs/howto/live_verification.md"
            )
    spec = get_mode(args.mode)
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
    # ⚠️ 控制台编码兜底（2026-09-30 实测踩到）：本机控制台是 GBK，日志里只要混进一个它编不出的
    # 字符（例如 "⇒"），print 就抛 UnicodeEncodeError —— 那不是「少显示一个字」，而是**直接把
    # 实跑打死**（异常从 runtime.log 里穿出来，整条路线报失败）。
    # 这里让 stdout/stderr 遇到编不出的字符用 "?" 顶替。
    # ⚠️ 只放在 __main__ 里：别的模块 import main 时（测试就是）不该动进程的 stdout。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    raise SystemExit(main())
