"""桌面助手的业务状态：勾了哪几条、每条几次、用哪个后端、能不能开跑。

2026-11-08 从 Tk 界面（``desktop/app.py``，2026-11-09 已整个删除）搬出来。
**类体一字未改**（唯一替换是把 ``STARTUP_HINTS`` 换成 ``catalog.BACKENDS``：
两者键集合相同，但前者当时定义在界面文件里，搬走后会形成循环导入）。

这里是**纯逻辑**，不 import 任何界面库 —— 界面从这里拿判据，避免
「换了一层皮，勾选 / 准入规则跟着漂移」。

⚠️ 改本文件等于改公共层：提交前必须跑全量门禁（见 AGENTS.md）。
"""

from __future__ import annotations

from auto_game_unified.core.pc_window import (
    PC_INPUT_BACKGROUND,
    PC_INPUT_FOREGROUND,
    PC_INPUT_MODES,
)
from auto_game_unified.desktop import session
from auto_game_unified.desktop.catalog import (
    BACKENDS,
    PC_ONLY_ROUTES,
    PC_READY_ROUTES,
    ROUTES,
    route_by_name,
    routes_in_group,
)
from auto_game_unified.desktop.preflight import PreflightReport
from auto_game_unified.desktop.worker import (
    RunRequest,
    WorkerController,
    WorkerEvent,
)
from auto_game_unified.games.epic7.modes import MODE_SPECS

class DesktopController:
    """界面状态：勾了哪几条路线、每条跑几次。

    ⚠️ 「勾选」是**有序**的 —— 用户 2026-09-29 拍板「按勾选先后确定顺序」，
    所以这里用 ``list`` 而不是 ``set``。取消再重新勾 = 排到最后。
    """

    def __init__(self, *, worker: WorkerController) -> None:
        self.worker = worker
        self.selected_backend = "emulator"
        # PC 端输入通道。默认后台（2026-11-09 用户拍板，后台点击已实跑正常）。
        # 模拟器后端下这个值原样保留（用户切回 PC 还在），但不生效。
        self.pc_input_mode = PC_INPUT_BACKGROUND
        self.preflight_report: PreflightReport | None = None
        # 默认**一条都不勾**（用户 2026-09-29 拍板）：每次自己挑。顺带当一道
        # 「点开始前先想一下」的确认 —— 世界首领战会花体力、刷书签会花天空石。
        self.selection: list[str] = []
        # 每条路线跑几次。默认取各路线自己的默认值；界面上能改的那几条可变，
        # 游戏本身有每日上限的（世界首领战、骑士团捐赠、迷宫强化石、英雄合成）改不动。
        self.cycles: dict[str, int] = {
            route.mode: route.default_cycles for route in ROUTES
        }

    def apply_session(self, state: session.SessionState) -> None:
        """把上次的勾选 / 次数 / 后端套回来（界面打开时调一次）。

        非法值已经在 ``session.load`` 里挡掉了（未知路线、越界次数、只读路线被改）。
        这里只再守一条**界面自己的规矩**：「活动」这类只能单独跑的路线不能和别的共存
        —— 文件可能是旧版本存的，也可能是路线后来才改成 ``standalone_only`` 的。
        """
        if self.worker.running:
            return
        names = [mode for mode in state.selection if mode in MODE_SPECS]
        standalone = [mode for mode in names if route_by_name(mode).standalone_only]
        self.selection = standalone[:1] if standalone else names
        for mode, cycles in state.cycles.items():
            if mode in MODE_SPECS:
                self.cycles[mode] = cycles
        if state.backend in BACKENDS:
            self.selected_backend = state.backend
        if state.pc_input_mode in PC_INPUT_MODES:
            self.pc_input_mode = state.pc_input_mode

    @property
    def can_start(self) -> bool:
        return bool(
            self.preflight_report is not None
            and self.preflight_report.can_start
            and not self.worker.running
        )

    @property
    def ready(self) -> bool:
        """能不能开跑：至少勾了一条，且没有任务在跑。"""
        return bool(self.selection) and not self.worker.running

    def toggle(self, mode: str, checked: bool) -> None:
        """勾上/取消一条路线。**勾上的时机就是它的执行位次。**

        「活动」这类只能单独跑的路线（``standalone_only``）与其它路线互斥：
        它的起点是用户人工摆好的页面，串在别的路线后面时那个起点早被破坏了。
        互斥是双向的 —— 勾活动会清掉别的，勾别的也会清掉活动。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        route = route_by_name(mode)  # 未知路线在这里就报错
        if not checked:
            if mode in self.selection:
                self.selection.remove(mode)
            return
        if mode in self.selection:
            return
        if route.standalone_only:
            self.selection.clear()
        else:
            self.selection = [
                name
                for name in self.selection
                if not route_by_name(name).standalone_only
            ]
        self.selection.append(mode)

    def select_group(self, group: str) -> None:
        """整组勾上：把该组每一条都加进选择，**已勾的跳过、新来的排在末尾**。

        这是界面上「点分类名 = 整组勾上」的唯一实现（2026-10-18 取代了原来卡头那
        三颗「全选 / 全选（不含活动）/ 取消全选」按钮）。

        ⚠️ 为什么是「追加到末尾」而不是像旧的 ``select_all`` 那样整体替换：用户拍板
        的语义是「勾选先后就是执行顺序」。用户点某一组的勾选框，等于**现在才开始勾
        这一组** ⇒ 它们排到已勾的后面。整体替换会把用户先前手挑的顺序抹掉。

        ⚠️ ``standalone_only``（活动组）互斥仍然成立，且是**双向**的：
        - 这一组里只要有一条只能单独跑 ⇒ 结果**就只剩这一组**，组外的全清；
          但组内**也只能留一条** —— 活动组现在有「活动小游戏」和「活动剧情」，
          两条都要求人先把游戏停在各自那一页，串着跑时第二条的起点早被第一条
          破坏了 ⇒ 组勾选只勾**该组的第一条**（要跑另一条就单独点它的勾选框，
          那条走 ``toggle``，会把这一条清掉）。
        - 这一组没有这种路线 ⇒ 先把 selection 里那条「只能单独跑」的踢掉，再追加。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        routes = routes_in_group(group)
        if not routes:
            return
        if any(route.standalone_only for route in routes):
            self.selection = [
                route.mode for route in routes if route.standalone_only
            ][:1]
            return
        self.selection = [
            name for name in self.selection if not route_by_name(name).standalone_only
        ]
        for route in routes:
            if route.mode not in self.selection:
                self.selection.append(route.mode)

    def clear_group(self, group: str) -> None:
        """整组取消：只把这一组的路线从选择里拿掉，**别组的一条都不动**。"""
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        dropping = {route.mode for route in routes_in_group(group)}
        self.selection = [name for name in self.selection if name not in dropping]

    def set_cycles(self, mode: str, cycles: int) -> None:
        """改某条路线的次数（界面上那个输入框）。

        固定次数的路线（世界首领战每天 2 次、骑士团捐赠 / 迷宫强化石 / 英雄合成
        跑一遍就结束）**不接受输入**：游戏本身就有每日上限，填个大数字只会在主页
        空转到「次数已用完」，所以直接打回默认值。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        route = route_by_name(mode)  # 未知路线在这里就报错
        if not route.cycles_editable:
            self.cycles[mode] = route.default_cycles
            return
        if cycles < route.min_cycles:
            raise ValueError(
                "运行次数不能为负数"
                if route.min_cycles == 0
                else "运行次数必须是正整数"
            )
        self.cycles[mode] = cycles

    def plan(self) -> tuple[tuple[str, int], ...]:
        """这次要跑的「路线 + 次数」—— 界面上看到的那一套，就是它的唯一出处。"""
        return tuple((mode, self.cycles[mode]) for mode in self.selection)

    def resolve_plan(
        self,
    ) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
        """按当前后端筛掉**用不了**的路线，返回 ``(要跑的, 被跳过的)``。

        **新路线只影响它自己**：某条路线在当前后端没素材 / 没放行时，跳过那一条，
        其余勾选照常跑。这与 ``games/epic7/daily_tasks.py`` 里
        ``not_supported`` 的口径一致 —— 不能让一条路线把整批老路线一起拦下。
        **全被筛掉仍要报错**，不许「什么都没跑」冒充成功。
        """
        plan = self.plan()
        if not plan:
            raise RuntimeError("至少要勾选一条路线")

        if self.selected_backend == "pc":
            # PC 后端只放行通过验收的路线；没放行的在 PC 上必然失败，
            # 而失败原因看起来像程序坏了。（命令行开发验证不受此限。）
            unsupported = [mode for mode, _ in plan if mode not in PC_READY_ROUTES]
            reason = "还没有在 PC 客户端上通过验收"
        else:
            # 反过来：只有 PC 素材的路线在模拟器上构造期就缺图。
            unsupported = [mode for mode, _ in plan if mode in PC_ONLY_ROUTES]
            reason = "目前只有 PC 客户端版素材，模拟器上还没有图"

        skipped = tuple(unsupported)
        runnable = tuple((mode, cycles) for mode, cycles in plan if mode not in skipped)
        if not runnable:
            names = "、".join(route_by_name(mode).label for mode in skipped)
            raise RuntimeError(
                f"所选路线在当前窗口后端都不可用：{names}（{reason}）；"
                "请切换窗口后端，或改勾别的路线。"
            )
        return runnable, skipped

    def start(self) -> None:
        if not self.can_start:
            raise RuntimeError("请先完成环境检测")
        plan, skipped = self.resolve_plan()
        if skipped:
            names = "、".join(route_by_name(mode).label for mode in skipped)
            self.worker.notice(
                f"已跳过 {len(skipped)} 条当前后端不可用的路线：{names}"
                "（其余勾选照常运行；要跑它们请切换窗口后端）。"
            )
        self.worker.start(
            RunRequest(
                modes=tuple(mode for mode, _ in plan),
                cycles=dict(plan),
                backend=self.selected_backend,
                # 只有 PC 后端才有「输入通道」这回事；模拟器一律走原来的路径。
                pc_input_mode=(
                    self.pc_input_mode
                    if self.selected_backend == "pc"
                    else PC_INPUT_FOREGROUND
                ),
            )
        )

    def select_pc_input_mode(self, mode: str) -> None:
        """切换 PC 输入通道（界面上的「不占用前台」开关）。

        和 ``select_backend`` 同一套规矩：运行期间不许切、非法值直接拒绝。
        不因为切到模拟器就清掉选择 —— 用户切回 PC 时还想要它。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能切换输入通道")
        if mode not in PC_INPUT_MODES:
            raise ValueError(f"未知 PC 输入通道：{mode!r}")
        self.pc_input_mode = mode

    def select_backend(self, backend: str) -> None:
        if self.worker.running:
            raise RuntimeError("运行期间不能切换窗口后端")
        if backend not in BACKENDS:
            raise ValueError(f"未知窗口后端：{backend}")
        if backend == self.selected_backend:
            return
        self.selected_backend = backend
        # 检测结果属于上一个后端，切换后必须重新检测。
        self.preflight_report = None

    def apply_preflight(self, report: PreflightReport) -> None:
        self.preflight_report = report

    def stop(self) -> None:
        self.worker.request_stop()

    def drain_events(self) -> list[WorkerEvent]:
        return self.worker.drain_events()


