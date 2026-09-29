"""Tkinter desktop interface for running the existing automation safely."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable

from auto_game_unified.desktop import theme
from auto_game_unified.desktop.catalog import (
    DAILY_DESCRIPTION,
    DAILY_LABEL,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    ROUTES,
    route_by_name,
    visible_backends,
)
from auto_game_unified.desktop.diagnostics import export_diagnostics
from auto_game_unified.desktop.preflight import (
    PreflightReport,
    run_preflight,
    validate_route_templates,
)
from auto_game_unified.desktop.worker import (
    RunRequest,
    WorkerController,
    WorkerEvent,
)


ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = ROOT.parent
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
STARTUP_ORDER_HINT = (
    "请先启动雷电模拟器并进入《第七史诗》，再启动本助手并检测环境。"
)
STARTUP_HINTS = {
    "emulator": STARTUP_ORDER_HINT,
    "pc": "请先启动《第七史诗》PC 客户端，再以管理员身份启动本助手并检测环境。",
}
BACKEND_LABELS = {
    "emulator": "模拟器（雷电）",
    "pc": "PC 客户端",
}
# 点了「安全停止」之后的宽限期：过了还不退，就强行结束这个卡住的运行。
#
# 依据（2026-08-31 ~ 2026-09-28 的 ``desktop_worker.log``）：88 次正常停止**全部**
# 在 1~2 秒内以退出码 130 结束，只有 2 次「停止请求之后没有任何结束」——都是运行卡在
# 一次底层调用里（见 ``docs/TROUBLESHOOTING.md``）。所以 30 秒 = 正常路径的十几倍。
# ⚠️ **别调小**：万一停止正好落在一次**正常收尾**的动作里，强行结束会让它跳过回家流程
# （游戏停在半路）。宁可多等，也不误杀。
STOP_GRACE_SECONDS = 30.0
# 宽限期内的轮询间隔 —— 只决定「多久发现它其实已经退了」，不是超时精度。
STOP_POLL_SECONDS = 0.5


def fit_window_size(
    *,
    requested: tuple[int, int],
    screen: tuple[int, int],
) -> tuple[int, int]:
    max_width = max(800, screen[0] - 80)
    max_height = max(600, screen[1] - 80)
    width = min(max(1080, requested[0] + 40), max_width)
    height = min(max(760, requested[1] + 40), max_height)
    return width, height


class DesktopController:
    """界面状态：勾了哪几条路线、每条跑几次。

    ⚠️ 「勾选」是**有序**的 —— 用户 2026-09-29 拍板「按勾选先后确定顺序」，
    所以这里用 ``list`` 而不是 ``set``。取消再重新勾 = 排到最后。
    """

    def __init__(self, *, worker: WorkerController) -> None:
        self.worker = worker
        self.selected_backend = "emulator"
        self.preflight_report: PreflightReport | None = None
        # 默认**一条都不勾**（用户 2026-09-29 拍板）：每次自己挑。顺带当一道
        # 「点开始前先想一下」的确认 —— 世界首领战会花体力、刷书签会花天空石。
        self.selection: list[str] = []
        # 每条路线跑几次。默认取各路线自己的默认值；界面上能改的那几条可变，
        # 游戏本身有每日上限的（世界首领战、骑士团捐赠、迷宫强化石、英雄合成）改不动。
        self.cycles: dict[str, int] = {
            route.mode: route.default_cycles for route in ROUTES
        }

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

    @property
    def needs_experimental_confirmation(self) -> bool:
        """勾选里有没有仍处于实验阶段的路线。"""
        return any(route_by_name(mode).experimental for mode in self.selection)

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

    def start(self) -> None:
        if not self.can_start:
            raise RuntimeError("请先完成环境检测")
        plan = self.plan()
        if not plan:
            raise RuntimeError("至少要勾选一条路线")
        self.worker.start(
            RunRequest(
                modes=tuple(mode for mode, _ in plan),
                cycles=dict(plan),
                backend=self.selected_backend,
            )
        )

    def select_backend(self, backend: str) -> None:
        if self.worker.running:
            raise RuntimeError("运行期间不能切换窗口后端")
        if backend not in STARTUP_HINTS:
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


class DesktopApp:
    """整个界面。排布是「上下三段」（用户 2026-09-29 拍板）：

    ```
    ┌ 状态带：产品名 / 环境状态 + 启动提示 / 后端选择 + 检测环境 ┐
    ├ 任务卡：每日任务 —— 勾选项按列铺开，列数随屏幕与路线数自动算 ┤
    ├ 控制条：开始任务 · 安全停止       打开日志/诊断/导出诊断包    ┤
    └ 日志卡：吃掉窗口剩下的全部高度                              ┘
    ```

    ⚠️ **不要在这里写色值 / 字号 / 间距**，一律引用 `desktop.theme` 的语义令牌。
    2026-09-29 审计发现旧版散落 10 个硬编码色值、10 个间距取值（含 10/14/20 这类
    非梯度值），而且每块内容各占一整块、谁都不让 —— 这才是「空了很多」与
    「挤在一块」的直接成因。
    """

    # 勾选位次的序号。用户 2026-09-29 拍板：勾选先后决定执行顺序，界面上要看得见。
    _CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: DesktopController,
        project_root: Path = ROOT,
        preflight_runner: Callable[..., PreflightReport] = run_preflight,
        route_validator: Callable[[str, Path], None] = validate_route_templates,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root
        self.controller = controller
        self.project_root = project_root
        self.template_root = TEMPLATE_ROOT
        self._preflight_runner = preflight_runner
        self._route_validator = route_validator
        self._thread_factory = thread_factory
        self._stop_grace_seconds = stop_grace_seconds
        self._clock = clock
        self._sleep = sleep
        # 第几次「开始运行」。停止兜底带着它一起等：等完之后这个号变了，就说明用户
        # 已经开了新的一次运行，兜底必须**放弃**，绝不能误杀新进程。
        self._run_generation = 0
        # 一条路线一个勾选框（``mode`` → 控件）。勾选是**有序**的，位次直接写在
        # 勾选框文字里的序号上（见 ``_route_text``）。
        self._route_buttons: dict[str, ttk.Checkbutton] = {}
        self._cycle_inputs: dict[str, ttk.Spinbox] = {}
        self.route_vars: dict[str, tk.BooleanVar] = {}
        self.cycle_vars: dict[str, tk.StringVar] = {}
        self._backend_buttons: list[ttk.Radiobutton] = []
        self._checking = False

        # 令牌 + ttk 样式一次性装好，之后的排布只引用语义名。
        self.theme = theme.build(self.root)
        # 任务网格排几列：按屏幕宽度与路线数算，**不写死** ——
        # 用户 2026-09-29 明说「以后还有很多路线」，加路线不该再回来改排布。
        self._route_columns_count = theme.route_columns(
            route_count=len(ROUTES),
            screen_logical_width=self.root.winfo_screenwidth() / self.theme.scale,
        )

        self.root.title(f"{PRODUCT_NAME} {PRODUCT_VERSION}")
        self.root.configure(background=self.theme.palette.bg)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_layout()
        self._refresh_route_details()
        self._refresh_controls()
        self._fit_initial_window()
        self.root.after(100, self._poll_worker)

    def _fit_initial_window(self) -> None:
        self.root.update_idletasks()
        width, height = fit_window_size(
            requested=(self.root.winfo_reqwidth(), self.root.winfo_reqheight()),
            screen=(self.root.winfo_screenwidth(), self.root.winfo_screenheight()),
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)

    def _build_layout(self) -> None:
        """上下三段的骨架。间距全部走令牌，**没有裸数字**。"""
        px = self.theme.px
        outer = ttk.Frame(self.root, style="App.TFrame", padding=px(theme.SPACE_XL))
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        # 只有**日志**那一行吃掉多余高度 ⇒ 窗口拉高时长大的是日志，不是留白。
        outer.rowconfigure(3, weight=1)

        gap = px(theme.SPACE_LG)
        self._build_status_bar(outer).grid(row=0, column=0, sticky="ew")
        self._build_task_panel(outer).grid(row=1, column=0, sticky="ew", pady=(gap, 0))
        self._build_action_bar(outer).grid(row=2, column=0, sticky="ew", pady=(gap, 0))
        self._build_log_panel(outer).grid(row=3, column=0, sticky="nsew", pady=(gap, 0))

    def _build_status_bar(self, parent: ttk.Frame) -> ttk.Frame:
        """状态带：产品名 / 环境状态 + 启动提示 / 后端选择 + 检测环境。

        三块横着摊开，中间那块吃伸缩 ⇒ 宽度变化时不会留下一段空白。
        后端选择紧贴「检测环境」——它们本来就是同一件事（换后端必须重新检测）。
        """
        px = self.theme.px
        palette = self.theme.palette
        pad = px(theme.SPACE_LG)
        bar = ttk.Frame(parent, style="Card.TFrame", padding=(pad, px(theme.SPACE_MD)))
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text=PRODUCT_NAME, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            bar,
            text="免费开源 · 非官方 · PVE 视觉自动化工具",
            style="Caption.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(px(theme.SPACE_XS), 0))

        self.environment_var = tk.StringVar(value="尚未检测。请点击“检测环境”。")
        self.environment_label = tk.Label(
            bar,
            textvariable=self.environment_var,
            background=palette.surface,
            foreground=palette.text_secondary,
            font=self.theme.font(theme.TYPE_BODY, bold=True),
            anchor="w",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        # 横向摊满中间那一栏：检测结果可能是一整句话（失败时更长），
        # 让它在本栏内换行，而不是把窗口顶宽。
        self.environment_label.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(px(theme.SPACE_XL), px(theme.SPACE_LG)),
        )
        self.environment_label.bind("<Configure>", self._wrap_at_own_width)
        self.startup_hint_label = ttk.Label(
            bar,
            text=STARTUP_HINTS[self.controller.selected_backend],
            style="Caption.TLabel",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        self.startup_hint_label.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(px(theme.SPACE_XL), px(theme.SPACE_LG)),
            pady=(px(theme.SPACE_XS), 0),
        )
        self.startup_hint_label.bind("<Configure>", self._wrap_at_own_width)

        backend_row = ttk.Frame(bar, style="Bar.TFrame")
        backend_row.grid(row=0, column=2, sticky="e")
        self.backend_var = tk.StringVar(value=self.controller.selected_backend)
        # ⚠️ 只画 visible_backends() 里的后端：PC 客户端默认不露面（理由见
        # catalog.visible_backends）。收起来的只是按钮 —— 控制器与命令行照旧接受它。
        for backend in visible_backends():
            label = BACKEND_LABELS[backend]
            button = ttk.Radiobutton(
                backend_row,
                text=label,
                value=backend,
                variable=self.backend_var,
                command=self._on_backend_change,
                style="Route.TRadiobutton",
            )
            button.pack(side=tk.LEFT, padx=(0, px(theme.SPACE_LG)))
            self._backend_buttons.append(button)
        # 「开始任务」才是这一屏的主行动，这里用次行动样式。
        self.check_button = ttk.Button(
            bar, text="检测环境", command=self._check_environment
        )
        self.check_button.grid(row=1, column=2, sticky="e", pady=(px(theme.SPACE_SM), 0))
        return bar

    def _build_task_panel(self, parent: ttk.Frame) -> ttk.Frame:
        """「每日任务」区块：勾选要跑的路线 + 每条跑几次。

        勾选是**多选且有序**的：勾上的先后就是执行顺序，名字前面的序号（①②③…）
        实时反映它现在排第几。取消勾选后面的序号自动顺移；取消再重新勾 = 排到最后。

        排布要点（2026-09-29 改版）：
        - 列数由 `theme.route_columns()` 算出来，加路线不用改这里；
        - 一条路线一格，**格内紧贴、格间留白**：`weight=1` 让每格平均吃伸缩 ⇒
          格子摊满整张卡（不再「内容缩在左边、右边空一片」），而富余宽度落在
          「组」的外面 ⇒ 次数框离它自己的名字最近，不会读成下一条路线的；
        - 说明文字挪到标题右边同行，用宽度换高度（旧版把它压在卡片底部一条窄栏里，
          折成很多行、右边全空）。
        """
        px = self.theme.px
        pad = px(theme.SPACE_LG)
        panel = ttk.Frame(parent, style="Card.TFrame", padding=pad)
        columns = self._route_columns_count

        head = ttk.Frame(panel, style="Card.TFrame")
        head.grid(row=0, column=0, columnspan=columns, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text=DAILY_LABEL, style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        # 说明文字放标题**右边同行**：旧版把它压在卡片底部一条窄栏里，行数很多、
        # 右边一大片空白。同行之后它摊满标题右侧那段宽度，两行内说完。
        hint = ttk.Label(
            head,
            text=DAILY_DESCRIPTION,
            style="Body.TLabel",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        hint.grid(row=0, column=1, sticky="ew", padx=(px(theme.SPACE_XL), 0))
        hint.bind("<Configure>", self._wrap_at_own_width)

        for index, route in enumerate(ROUTES):
            row, column = divmod(index, self._route_columns_count)
            # 每条路线是一个**紧贴的组**（勾选框 + 次数框 + 「次」），组内用 pack
            # 贴着排；富余宽度留在组**外面**（格子的右边距 + 整列拉伸）。
            # 这样「格内间距 < 组间距」，一眼能看出次数属于哪条路线 ——
            # 反过来（富余塞进组内）会让次数框离下一条路线更近，读错。
            cell = ttk.Frame(panel, style="Card.TFrame")
            cell.grid(
                row=row + 1,
                column=column,
                sticky="ew",
                padx=(0, px(theme.SPACE_XL)),
                pady=px(theme.SPACE_SM),
            )
            var = tk.BooleanVar(value=route.mode in self.controller.selection)
            self.route_vars[route.mode] = var
            checkbox = ttk.Checkbutton(
                cell,
                text=self._route_text(route.mode),
                variable=var,
                command=lambda mode=route.mode: self._on_toggle(mode),
                style="Route.TCheckbutton",
            )
            checkbox.pack(side=tk.LEFT)
            self._route_buttons[route.mode] = checkbox

            count_var = tk.StringVar(value=str(self.controller.cycles[route.mode]))
            self.cycle_vars[route.mode] = count_var
            spinbox = ttk.Spinbox(
                cell,
                # 箭头能落到的最小值跟着路线走（正常 1；「刷书签」是 0 —— 只扫不刷新），
                # 否则默认 0 那条路线会「框里写着 0、往上点一下变 1、再往下按不回 0」。
                from_=route.min_cycles,
                to=999,
                width=4,
                textvariable=count_var,
                style="Route.TSpinbox",
            )
            spinbox.pack(side=tk.LEFT, padx=(px(theme.SPACE_SM), px(theme.SPACE_XS)))
            self._cycle_inputs[route.mode] = spinbox
            ttk.Label(cell, text="次", style="Body.TLabel").pack(side=tk.LEFT)
        # 每格平均吃伸缩：窗口拉宽时组间距一起变大，而不是全挤在末尾。
        for column in range(self._route_columns_count):
            panel.grid_columnconfigure(column, weight=1)

        rows = -(-len(ROUTES) // self._route_columns_count)
        self.route_description_var = tk.StringVar()
        description = ttk.Label(
            panel,
            textvariable=self.route_description_var,
            style="Body.TLabel",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        description.grid(
            row=rows + 1,
            column=0,
            columnspan=columns,
            sticky="ew",
            pady=(px(theme.SPACE_MD), 0),
        )
        description.bind("<Configure>", self._wrap_at_own_width)
        return panel

    def _wrap_at_own_width(self, event: tk.Event) -> None:
        """说明文字按**自己那一格的宽度**换行。

        各处说明文字能用的宽度不一样（标题右边那段要扣掉标题、卡片底部那条是整个
        宽度），所以不去算「可用宽度」，直接跟着控件自己的实际宽度走。宽度没变就
        不动，免得反复触发布局。
        """
        if int(event.widget.cget("wraplength")) != event.width:
            event.widget.configure(wraplength=event.width)

    def _route_text(self, mode: str) -> str:
        """勾选框上的文字：``序号 名字 [正式/实验]``。

        没勾选时用全角空格占位，勾上之后文字不会整体右移。
        """
        route = route_by_name(mode)
        marker = "正式" if not route.experimental else "实验"
        if mode in self.controller.selection:
            prefix = self._CIRCLED[self.controller.selection.index(mode)]
        else:
            prefix = "　"
        text = f"{prefix} {route.label}  [{marker}]"
        if route.standalone_only:
            text += " · 单独跑"
        return text

    def _refresh_task_rows(self) -> None:
        """把 controller 里的勾选真值刷回界面：勾选状态 + 序号 + 那条路线的说明。"""
        for mode, button in self._route_buttons.items():
            self.route_vars[mode].set(mode in self.controller.selection)
            button.configure(text=self._route_text(mode))

    def _build_action_bar(self, parent: ttk.Frame) -> ttk.Frame:
        """控制条：左边主行动、右边工具，两组**贴住两端**。

        旧版把这几颗按钮摊在一张 668px 宽的卡片里悬空摆着，两边都是空的；
        贴边之后中间那段留白是「分组间隔」，不是死空间。
        """
        px = self.theme.px
        bar = ttk.Frame(
            parent, style="Card.TFrame", padding=(px(theme.SPACE_LG), px(theme.SPACE_MD))
        )
        bar.columnconfigure(1, weight=1)

        actions = ttk.Frame(bar, style="Bar.TFrame")
        actions.grid(row=0, column=0, sticky="w")
        # 这里是**唯一**的启动入口：勾一条就是跑一条，勾三条就是依次跑三条。
        # 次数不在这儿填 —— 它跟着每条路线走（见 ``_build_task_panel``）。
        self.start_button = ttk.Button(
            actions, text="开始任务", style="Accent.TButton", command=self._start
        )
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(actions, text="安全停止", command=self._stop)
        self.stop_button.pack(side=tk.LEFT, padx=(px(theme.SPACE_SM), 0))

        utilities = ttk.Frame(bar, style="Bar.TFrame")
        utilities.grid(row=0, column=2, sticky="e")
        for index, (text, command) in enumerate(
            (
                ("打开日志", self._open_logs),
                ("打开诊断", self._open_diagnostics),
                ("导出诊断包", self._export),
            )
        ):
            ttk.Button(utilities, text=text, style="Tool.TButton", command=command).pack(
                side=tk.LEFT, padx=(px(theme.SPACE_SM) if index else 0, 0)
            )
        return bar

    def _build_log_panel(self, parent: ttk.Frame) -> ttk.Frame:
        """日志卡：整窗唯一吃剩余高度的地方，所以要够高（有下限）。"""
        px = self.theme.px
        palette = self.theme.palette
        pad = px(theme.SPACE_LG)
        panel = ttk.Frame(parent, style="Card.TFrame", padding=pad)
        panel.rowconfigure(1, weight=1, minsize=px(theme.LOG_MIN_HEIGHT))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="实时日志", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, px(theme.SPACE_MD))
        )
        self.log_text = scrolledtext.ScrolledText(
            panel,
            width=40,
            height=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background=palette.log_bg,
            foreground=palette.log_text,
            insertbackground=palette.log_text,
            selectbackground=palette.primary,
            font=self.theme.font(theme.TYPE_CAPTION, mono=True),
            relief=tk.FLAT,
            padx=px(theme.SPACE_MD),
            pady=px(theme.SPACE_MD),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self._append_log(
            f"准备就绪。{STARTUP_HINTS[self.controller.selected_backend]}"
        )
        return panel

    def _on_toggle(self, mode: str) -> None:
        """勾选框被点。勾上的先后由 ``controller.toggle`` 记着，这里只负责刷新界面。"""
        var = self.route_vars[mode]
        try:
            self.controller.toggle(mode, var.get())
        except Exception as error:
            messagebox.showerror("无法修改任务", str(error), parent=self.root)
            self._refresh_task_rows()
            return
        # 互斥（勾「活动」会清掉别的、勾别的会清掉「活动」）⇒ 必须整块重刷，
        # 不能只改被点的那一行。
        self._refresh_task_rows()
        self._refresh_route_details()
        self._refresh_controls()

    def _collect_cycles(self) -> bool:
        """把界面上填的次数收进 controller；填坏了就弹框并返回 False。

        只收**勾选了的**那几条 —— 没勾的那行填了什么都不该挡住启动。收完再回显一次：
        固定次数的路线会被打回默认值，不回显就会在框里留一个不会生效的数字。
        """
        for mode in self.controller.selection:
            var = self.cycle_vars[mode]
            try:
                self.controller.set_cycles(mode, int(var.get()))
            except (TypeError, ValueError) as error:
                messagebox.showerror("运行次数无效", str(error), parent=self.root)
                var.set(str(self.controller.cycles[mode]))
                return False
            var.set(str(self.controller.cycles[mode]))
        return True

    def _on_backend_change(self) -> None:
        try:
            self.controller.select_backend(self.backend_var.get())
        except Exception as error:
            messagebox.showerror("无法切换窗口后端", str(error), parent=self.root)
            self.backend_var.set(self.controller.selected_backend)
            return
        self.startup_hint_label.configure(
            text=STARTUP_HINTS[self.controller.selected_backend]
        )
        self.environment_var.set("尚未检测。请点击“检测环境”。")
        self.environment_label.configure(foreground=self.theme.palette.text_secondary)
        self._append_log(
            f"窗口后端已切换为{BACKEND_LABELS[self.controller.selected_backend]}，请重新检测环境。"
        )
        self._refresh_controls()

    def _checking_message(self) -> str:
        if self.controller.selected_backend == "pc":
            return "正在检测 PC 客户端、窗口尺寸和权限……"
        return "正在检测雷电模拟器和截图……"

    def _refresh_route_details(self) -> None:
        """说明区显示**最后勾的那条**路线的说明。

        界面不再有「当前路线」这个概念（勾选是多项的），所以取最后勾的那条 ——
        正好是用户刚点过、最可能想确认的那条。一条都没勾就留空。
        """
        if not self.controller.selection:
            self.route_description_var.set("")
            return
        route = route_by_name(self.controller.selection[-1])
        status_text = "正式功能" if not route.experimental else "实验功能，可能不稳定"
        self.route_description_var.set(
            f"【{route.label}】{status_text}\n{route.description}"
        )

    def _check_environment(self) -> None:
        if self._checking or self.controller.worker.running:
            return
        self._checking = True
        self.environment_var.set(self._checking_message())
        self.environment_label.configure(foreground=self.theme.palette.primary)
        self._refresh_controls()
        def check() -> None:
            report = self._preflight_runner(
                window_backend=self.controller.selected_backend
            )
            self.root.after(0, lambda: self._finish_environment_check(report))

        self._thread_factory(
            target=check,
            name="epic7-preflight",
            daemon=True,
        ).start()

    def _finish_environment_check(self, report: PreflightReport) -> None:
        self._checking = False
        self.controller.apply_preflight(report)
        self.environment_var.set(report.message)
        self.environment_label.configure(
            foreground=self.theme.palette.success if report.can_start else self.theme.palette.error
        )
        self._append_log(f"环境检测：{report.message}")
        self._refresh_controls()

    def _start(self) -> None:
        """唯一的启动入口：勾了哪几条就跑哪几条，按勾选先后依次跑。

        流程与原来「单路线」那条通道逐字同形：收次数 → 实验功能提醒 → 复检环境 →
        逐条查模板 → 启动。两条通道合并之后，以后改这里只有一处。
        """
        if not self.controller.selection:
            messagebox.showwarning(
                DAILY_LABEL, "至少要勾选一条路线再开始。", parent=self.root
            )
            return
        if not self._collect_cycles():
            return
        # 勾选里含实验功能路线（世界首领战 / 骑士团捐赠 / 迷宫强化石等都是）就提醒一次。
        if self.controller.needs_experimental_confirmation:
            confirmed = messagebox.askyesno(
                "实验功能提醒",
                "勾选的任务里有仍处于实验阶段的路线，可能不稳定。\n\n是否继续运行？",
                parent=self.root,
            )
            if not confirmed:
                return
        self._checking = True
        self.environment_var.set("正在复检运行环境……")
        self.environment_label.configure(foreground=self.theme.palette.primary)
        self._refresh_controls()
        # 快照「路线 + 次数」：复检期间用户改了这个快照里的任何一样，这次启动就作废。
        plan = self.controller.plan()

        def check() -> None:
            report = self._preflight_runner(
                window_backend=self.controller.selected_backend
            )
            route_error: Exception | None = None
            if report.can_start:
                # **每一条**都查一遍模板：勾几条就可能缺几套，提前发现比跑到一半失败好。
                for mode, _ in plan:
                    try:
                        self._route_validator(mode, self.template_root)
                    except Exception as error:  # noqa: BLE001 —— 报清是哪条缺
                        route_error = RuntimeError(
                            f"{route_by_name(mode).label}：{error}"
                        )
                        break
            self.root.after(
                0,
                lambda: self._finish_start_check(plan, report, route_error),
            )

        self._thread_factory(
            target=check,
            name="epic7-start-check",
            daemon=True,
        ).start()

    def _finish_start_check(
        self,
        plan: tuple[tuple[str, int], ...],
        report: PreflightReport,
        route_error: Exception | None,
    ) -> None:
        self._checking = False
        self.controller.apply_preflight(report)
        if not report.can_start:
            self.environment_var.set(report.message)
            self.environment_label.configure(foreground=self.theme.palette.error)
            self._append_log(f"运行前复检失败：{report.message}")
            self._refresh_controls()
            return
        if route_error is not None:
            message = f"路线资源检查失败：{route_error}"
            self.environment_var.set(message)
            self.environment_label.configure(foreground=self.theme.palette.error)
            self._append_log(message)
            self._refresh_controls()
            return
        if self.controller.plan() != plan:
            self.environment_var.set("任务的勾选或次数已变化，本次启动已取消。")
            self.environment_label.configure(foreground=self.theme.palette.error)
            self._refresh_controls()
            return
        self.environment_var.set(report.message)
        self.environment_label.configure(foreground=self.theme.palette.success)
        try:
            self.controller.start()
        except Exception as error:
            messagebox.showerror("无法开始", str(error), parent=self.root)
            self._refresh_controls()
            return
        self._run_generation += 1
        self._append_log(
            "开始任务："
            + "、".join(
                f"{route_by_name(mode).label} {count} 次" for mode, count in plan
            )
        )
        self._refresh_controls()

    def _stop(self) -> None:
        self.controller.stop()
        self._append_log("已请求安全停止，等待当前检查点退出……")
        self.stop_button.configure(state=tk.DISABLED)
        self._arm_force_stop_watchdog()

    def _arm_force_stop_watchdog(self) -> None:
        """点过「安全停止」之后再加一道兜底：宽限期内不退就强行结束。

        为什么必须有（2026-09-28 实机取证）：停止是「在两次动作**之间**查一次信号
        文件」，而工作进程有可能**卡在一次底层调用的内部**（等一次点击的回执）——
        卡在里面就永远轮不到下一次检查，信号写了也白写。原先这里只做「写信号 ＋
        把按钮变灰」，没有第二手，界面就只能一直等下去。
        ⚠️ 它**在后台线程里等**，不会冻住界面；时间来源是注入的，测试里不用真等。
        """
        generation = self._run_generation

        def watch() -> None:
            self._watch_stop(generation)

        self._thread_factory(
            target=watch,
            name="epic7-stop-watchdog",
            daemon=True,
        ).start()

    def _watch_stop(self, generation: int) -> None:
        if self._wait_for_exit(self._stop_grace_seconds):
            return
        if generation != self._run_generation:
            return
        # 收界面状态必须回主线程（Tk 不是线程安全的）。
        self.root.after(0, self._force_stop_worker)

    def _wait_for_exit(self, timeout: float) -> bool:
        """等它自己退出：等到了返回 ``True``，超时还没退返回 ``False``。"""
        deadline = self._clock() + timeout
        while True:
            if not self.controller.worker.running:
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(STOP_POLL_SECONDS)

    def _force_stop_worker(self) -> None:
        if not self.controller.worker.running:
            return
        seconds = self._stop_grace_seconds
        if self.controller.worker.force_stop():
            self._append_log(
                f"等待 {seconds:.0f} 秒仍无响应，已强行结束这个卡住的运行。"
                "它卡在一次底层调用里读不到停止信号，这次走不完回家流程，"
                "游戏可能停在半路；重新开始前请先确认模拟器运行正常。"
            )
        else:
            self._append_log(
                f"等待 {seconds:.0f} 秒仍无响应，并且无法结束这个运行；"
                "请在任务管理器中手动结束助手进程。"
            )
        # 强行结束时读输出的线程可能还卡在那条阻塞的管道上（``事件=结束`` 不会来），
        # 所以这里必须自己把按钮状态收回来，不能等 ``finished`` 事件。
        self._refresh_controls()

    def _poll_worker(self) -> None:
        for event in self.controller.drain_events():
            if event.kind == "log":
                self._append_log(event.message)
            else:
                self._append_log(f"[{event.message}]")
            if event.kind == "finished":
                self._refresh_controls()
        self.root.after(100, self._poll_worker)

    def _refresh_controls(self) -> None:
        running = self.controller.worker.running
        route_state = tk.DISABLED if running or self._checking else tk.NORMAL
        for button in self._route_buttons.values():
            button.configure(state=route_state)
        for button in self._backend_buttons:
            button.configure(state=route_state)
        self.check_button.configure(
            state=tk.DISABLED if running or self._checking else tk.NORMAL
        )
        # 「开始任务」：要勾了至少一条、且完成过环境检测、且当前没在跑。
        self.start_button.configure(
            state=(
                tk.NORMAL
                if self.controller.ready
                and self.controller.can_start
                and not self._checking
                else tk.DISABLED
            )
        )
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        for mode, spinbox in self._cycle_inputs.items():
            spinbox.configure(
                state=(
                    tk.NORMAL
                    if route_by_name(mode).cycles_editable and not running and not self._checking
                    else tk.DISABLED
                )
            )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_logs(self) -> None:
        self._open_directory(self.project_root / "runtime_logs")

    def _primary_mode(self) -> str:
        """诊断相关操作用哪条路线 —— 取勾选的第一条（没勾就取列表第一条）。

        界面不再有「当前路线」这个概念，所以给一个确定的默认值：勾了多条时至少
        能对上其中一条，而不是随机挑一条。
        """
        if self.controller.selection:
            return self.controller.selection[0]
        return ROUTES[0].mode

    def _open_diagnostics(self) -> None:
        self._open_directory(
            self.project_root
            / "runtime_diagnostics"
            / f"epic7_{self._primary_mode()}"
        )

    def _open_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _export(self) -> None:
        selected = filedialog.askdirectory(
            title="选择诊断包保存目录",
            parent=self.root,
        )
        if not selected:
            return
        try:
            path = export_diagnostics(
                self._primary_mode(),
                root=self.project_root,
                output_dir=Path(selected),
            )
        except Exception as error:
            messagebox.showerror("导出失败", str(error), parent=self.root)
            return
        messagebox.showinfo(
            "导出完成",
            f"诊断包已保存：\n{path}\n\n其中可能包含游戏画面和玩家昵称，上传前请自行检查。",
            parent=self.root,
        )

    def _on_close(self) -> None:
        if self.controller.worker.running:
            messagebox.showwarning(
                "任务仍在运行",
                "请先点击“安全停止”，等待任务结束后再关闭窗口。",
                parent=self.root,
            )
            return
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    worker = WorkerController(repo_parent=REPO_PARENT)
    controller = DesktopController(worker=worker)
    DesktopApp(root, controller=controller)
    root.mainloop()
    return 0
