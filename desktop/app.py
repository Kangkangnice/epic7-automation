"""Tkinter desktop interface for running the existing automation safely."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable

from auto_game_unified.desktop.catalog import (
    DAILY_DESCRIPTION,
    DAILY_LABEL,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    ROUTES,
    daily_items,
    route_by_name,
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
from auto_game_unified.games.epic7.daily_tasks import cycles_for


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
    def __init__(self, *, worker: WorkerController) -> None:
        self.worker = worker
        self.selected_mode = "hero_synthesis"
        self.selected_backend = "emulator"
        self.cycles = 1
        self.preflight_report: PreflightReport | None = None
        # 「每日任务」勾选与每条跑几次：默认全勾（按 DAILY_TASKS 的次序）、
        # 次数取各路线自己的每日默认值。它是**独立于** selected_mode 的一套状态
        # —— 单路线单选与每日任务多选互不干扰。
        self.daily_selection: list[str] = [mode for mode, _ in daily_items()]
        self.daily_cycles: dict[str, int] = {
            mode: cycles_for(mode) for mode, _ in daily_items()
        }

    @property
    def route(self):
        return route_by_name(self.selected_mode)

    @property
    def daily_ready(self) -> bool:
        """每日任务能不能开跑：至少勾了一项，且没有任务在跑。"""
        return bool(self.daily_selection) and not self.worker.running

    def toggle_daily_item(self, mode: str, checked: bool) -> None:
        if self.worker.running:
            raise RuntimeError("运行期间不能修改每日任务")
        if mode not in {m for m, _ in daily_items()}:
            raise ValueError(f"每日任务里没有这条路线：{mode}")
        if checked and mode not in self.daily_selection:
            self.daily_selection.append(mode)
        elif not checked and mode in self.daily_selection:
            self.daily_selection.remove(mode)

    def set_daily_cycles(self, mode: str, cycles: int) -> None:
        """改每日任务里某条路线的次数（界面上那个输入框）。

        固定次数的路线（世界首领战每天 2 次、骑士团捐赠每天 1 次）**不接受输入**：
        游戏本身就有每日上限，填个大数字只会在主页空转到「次数已用完」，
        所以直接打回默认值 —— 与单路线面板的 ``set_cycles`` 同一套口径。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能修改每日任务")
        if mode not in self.daily_cycles:
            raise ValueError(f"每日任务里没有这条路线：{mode}")
        if not route_by_name(mode).cycles_editable:
            self.daily_cycles[mode] = cycles_for(mode)
            return
        if cycles <= 0:
            raise ValueError("运行次数必须是正整数")
        self.daily_cycles[mode] = cycles

    def daily_plan(self) -> tuple[tuple[str, int], ...]:
        """这次要跑的「路线 + 次数」—— 界面上看到的那一套，就是它是唯一出处。"""
        return tuple(
            (mode, self.daily_cycles[mode]) for mode in self.daily_selection
        )

    def start_daily(self) -> None:
        if not self.can_start:
            raise RuntimeError("请先完成环境检测")
        plan = self.daily_plan()
        if not plan:
            raise RuntimeError("每日任务至少要勾选一项")
        self.worker.start(
            RunRequest(
                self.selected_mode,
                self.cycles,
                self.selected_backend,
                daily_tasks=tuple(mode for mode, _ in plan),
                daily_cycles=dict(plan),
            )
        )

    @property
    def can_start(self) -> bool:
        return bool(
            self.preflight_report is not None
            and self.preflight_report.can_start
            and not self.worker.running
        )

    @property
    def needs_experimental_confirmation(self) -> bool:
        return self.route.experimental

    def select_route(self, mode: str) -> None:
        if self.worker.running:
            raise RuntimeError("运行期间不能切换路线")
        route = route_by_name(mode)
        self.selected_mode = route.mode
        self.cycles = route.default_cycles

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

    def set_cycles(self, cycles: int) -> None:
        if not self.route.cycles_editable:
            self.cycles = self.route.default_cycles
            return
        if cycles <= 0:
            raise ValueError("运行次数必须是正整数")
        self.cycles = cycles

    def apply_preflight(self, report: PreflightReport) -> None:
        self.preflight_report = report

    def start(self) -> None:
        if not self.can_start:
            raise RuntimeError("请先完成环境检测")
        cycles = self.route.default_cycles if not self.route.cycles_editable else self.cycles
        self.worker.start(
            RunRequest(self.selected_mode, cycles, self.selected_backend)
        )

    def stop(self) -> None:
        self.worker.request_stop()

    def drain_events(self) -> list[WorkerEvent]:
        return self.worker.drain_events()


class DesktopApp:
    # 「选择功能」排几列。十条路线一字排开会把窗口顶得很长（用户 2026-09-25 反馈
    # 「UI 有点太长了」），所以摊成两列、把高度换宽度。
    _ROUTE_COLUMNS = 2
    # 卡片里的说明文字多宽换行 —— 这个值直接决定左栏高度。实测（Tk 里一行中文
    # 约 23px 宽、39px 高）：每日任务那段说明 152 字，按 340 换行要 15 行、564px 高，
    # 占了整栏一多半；放到跟「选择功能」两列网格同宽（≈540）后只要 6 行，
    # 整窗自然高度从 2000 掉到 ~1540。**别再往小调。**
    _WRAP_LENGTH = 540
    _BACKGROUND = "#f4f4f5"
    _SURFACE = "#ffffff"
    _TEXT = "#18181b"
    _TEXT_SECONDARY = "#52525b"
    _PRIMARY = "#2563eb"
    _SUCCESS = "#15803d"
    _WARNING = "#b45309"
    _ERROR = "#b91c1c"

    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: DesktopController,
        project_root: Path = ROOT,
        preflight_runner: Callable[..., PreflightReport] = run_preflight,
        route_validator: Callable[[str, Path], None] = validate_route_templates,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.root = root
        self.controller = controller
        self.project_root = project_root
        self.template_root = TEMPLATE_ROOT
        self._preflight_runner = preflight_runner
        self._route_validator = route_validator
        self._thread_factory = thread_factory
        self._route_buttons: list[ttk.Radiobutton] = []
        self._backend_buttons: list[ttk.Radiobutton] = []
        self._daily_buttons: list[ttk.Checkbutton] = []
        self._checking = False

        self.root.title(f"{PRODUCT_NAME} {PRODUCT_VERSION}")
        self.root.configure(background=self._BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_styles()
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

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("App.TFrame", background=self._BACKGROUND)
        style.configure("Card.TFrame", background=self._SURFACE)
        style.configure(
            "Title.TLabel",
            background=self._BACKGROUND,
            foreground=self._TEXT,
            font=("Microsoft YaHei UI", 20, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=self._BACKGROUND,
            foreground=self._TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background=self._SURFACE,
            foreground=self._TEXT,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=self._SURFACE,
            foreground=self._TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure("TButton", padding=(12, 8), font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", padding=(16, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Route.TRadiobutton", background=self._SURFACE, font=("Microsoft YaHei UI", 10))

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=20)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, text=PRODUCT_NAME, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            outer,
            text="免费开源 · 非官方 · PVE 视觉自动化工具",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        self._build_preflight_panel(outer)
        content = ttk.Frame(outer, style="App.TFrame")
        content.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
        content.columnconfigure(1, weight=1)
        content.rowconfigure(1, weight=1)
        self._build_route_panel(content)
        self._build_daily_panel(content)
        self._build_action_panel(content)
        self._build_log_panel(content)

    def _build_preflight_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        panel.grid(row=2, column=0, sticky="ew")
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="运行环境", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        backend_row = ttk.Frame(panel, style="Card.TFrame")
        backend_row.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.backend_var = tk.StringVar(value=self.controller.selected_backend)
        for backend, label in BACKEND_LABELS.items():
            button = ttk.Radiobutton(
                backend_row,
                text=label,
                value=backend,
                variable=self.backend_var,
                command=self._on_backend_change,
                style="Route.TRadiobutton",
            )
            button.pack(side=tk.LEFT, padx=(0, 14))
            self._backend_buttons.append(button)
        self.startup_hint_label = ttk.Label(
            panel,
            text=STARTUP_HINTS[self.controller.selected_backend],
            style="Body.TLabel",
            wraplength=560,
        )
        self.startup_hint_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.environment_var = tk.StringVar(value="尚未检测。请点击“检测环境”。")
        self.environment_label = tk.Label(
            panel,
            textvariable=self.environment_var,
            background=self._SURFACE,
            foreground=self._TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        )
        self.environment_label.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.check_button = ttk.Button(
            panel, text="检测环境", command=self._check_environment
        )
        self.check_button.grid(row=0, column=1, rowspan=4, padx=(16, 0))

    def _build_route_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        panel.grid(row=0, column=0, sticky="new", padx=(0, 14))
        ttk.Label(panel, text="选择功能", style="Section.TLabel").grid(
            row=0, column=0, columnspan=self._ROUTE_COLUMNS, sticky="w", pady=(0, 8)
        )
        self.route_var = tk.StringVar(value=self.controller.selected_mode)
        for index, route in enumerate(ROUTES):
            row, column = divmod(index, self._ROUTE_COLUMNS)
            marker = "正式" if not route.experimental else "实验"
            button = ttk.Radiobutton(
                panel,
                text=f"{route.label}  [{marker}]",
                value=route.mode,
                variable=self.route_var,
                command=self._on_route_change,
                style="Route.TRadiobutton",
            )
            button.grid(row=row + 1, column=column, sticky="w", pady=5, padx=(0, 18))
            self._route_buttons.append(button)
        self.route_description_var = tk.StringVar()
        rows = -(-len(ROUTES) // self._ROUTE_COLUMNS)
        ttk.Label(
            panel,
            textvariable=self.route_description_var,
            style="Body.TLabel",
            wraplength=self._WRAP_LENGTH,
        ).grid(
            row=rows + 1,
            column=0,
            columnspan=self._ROUTE_COLUMNS,
            sticky="w",
            pady=(14, 0),
        )

    def _build_daily_panel(self, parent: ttk.Frame) -> None:
        """「每日任务」区块：多选 + 独立启动按钮。

        ⚠️ 与上面的单路线单选面板**是两套独立的东西**：上面选「跑哪一条」，
        这里选「日常串哪几条、各跑几次」。所以它有自己的启动按钮，不复用「开始运行」，
        免得两种模式互相干扰（各自的勾选/次数语义完全不同）。

        每条后面那个次数框就是「默认值 + 可选值」：默认填各路线自己的每日次数，
        想多跑就自己改（竞技场这类没有每日上限的）。有每日上限的路线（世界首领战、
        骑士团捐赠）框是灰的 —— 见 ``DesktopController.set_daily_cycles``。
        """
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        panel.grid(row=1, column=0, sticky="new", padx=(0, 14), pady=(14, 0))
        ttk.Label(panel, text=DAILY_LABEL, style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.daily_vars: dict[str, tk.BooleanVar] = {}
        self.daily_cycle_vars: dict[str, tk.StringVar] = {}
        self._daily_cycle_inputs: dict[str, ttk.Spinbox] = {}
        row_index = 1
        for mode, label in daily_items():
            var = tk.BooleanVar(value=mode in self.controller.daily_selection)
            self.daily_vars[mode] = var
            checkbox = ttk.Checkbutton(
                panel,
                text=label,
                variable=var,
                command=lambda m=mode: self._on_daily_toggle(m),
            )
            checkbox.grid(row=row_index, column=0, sticky="w", pady=3)
            self._daily_buttons.append(checkbox)

            count_var = tk.StringVar(value=str(self.controller.daily_cycles[mode]))
            self.daily_cycle_vars[mode] = count_var
            spinbox = ttk.Spinbox(
                panel, from_=1, to=999, width=5, textvariable=count_var
            )
            spinbox.grid(row=row_index, column=1, sticky="w", padx=(10, 4), pady=3)
            self._daily_cycle_inputs[mode] = spinbox
            ttk.Label(panel, text="次", style="Body.TLabel").grid(
                row=row_index, column=2, sticky="w", pady=3
            )
            row_index += 1
        ttk.Label(
            panel,
            text=DAILY_DESCRIPTION,
            style="Body.TLabel",
            wraplength=self._WRAP_LENGTH,
        ).grid(row=row_index, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.daily_button = ttk.Button(
            panel,
            text="开始每日任务",
            style="Accent.TButton",
            command=self._start_daily,
        )
        self.daily_button.grid(
            row=row_index + 1, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )

    def _build_action_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        panel.grid(row=0, column=1, sticky="ew")
        panel.columnconfigure(4, weight=1)
        ttk.Label(panel, text="运行控制", style="Section.TLabel").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 10)
        )
        ttk.Label(panel, text="运行次数", style="Body.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.cycles_var = tk.StringVar(value="1")
        self.cycles_input = ttk.Spinbox(
            panel,
            from_=1,
            to=999,
            width=7,
            textvariable=self.cycles_var,
        )
        self.cycles_input.grid(row=1, column=1, padx=(8, 14))
        self.start_button = ttk.Button(
            panel,
            text="开始运行",
            style="Accent.TButton",
            command=self._start,
        )
        self.start_button.grid(row=1, column=2, padx=(0, 8))
        self.stop_button = ttk.Button(panel, text="安全停止", command=self._stop)
        self.stop_button.grid(row=1, column=3)

        utility = ttk.Frame(panel, style="Card.TFrame")
        utility.grid(row=2, column=0, columnspan=5, sticky="w", pady=(12, 0))
        ttk.Button(utility, text="打开日志", command=self._open_logs).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(utility, text="打开诊断", command=self._open_diagnostics).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(utility, text="导出诊断包", command=self._export).grid(
            row=0, column=2
        )

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        panel.grid(row=1, column=1, sticky="nsew", pady=(14, 0))
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="实时日志", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.log_text = scrolledtext.ScrolledText(
            panel,
            height=18,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#18181b",
            foreground="#f4f4f5",
            insertbackground="#f4f4f5",
            selectbackground=self._PRIMARY,
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self._append_log(
            f"准备就绪。{STARTUP_HINTS[self.controller.selected_backend]}"
        )

    def _on_route_change(self) -> None:
        try:
            self.controller.select_route(self.route_var.get())
        except Exception as error:
            messagebox.showerror("无法切换功能", str(error), parent=self.root)
            self.route_var.set(self.controller.selected_mode)
            return
        self.cycles_var.set(str(self.controller.cycles))
        self._refresh_route_details()
        self._refresh_controls()

    def _on_daily_toggle(self, mode: str) -> None:
        var = self.daily_vars[mode]
        try:
            self.controller.toggle_daily_item(mode, var.get())
        except Exception as error:
            messagebox.showerror("无法修改每日任务", str(error), parent=self.root)
            var.set(mode in self.controller.daily_selection)
            return
        self._refresh_controls()

    def _collect_daily_cycles(self) -> bool:
        """把界面上填的次数收进 controller；填坏了就弹框并返回 False。

        只收**勾选了的**那几条 —— 没勾的那行填了什么都不该挡住启动。收完再回显一次：
        固定次数的路线会被打回默认值，不回显就会在框里留一个不会生效的数字。
        """
        for mode in self.controller.daily_selection:
            var = self.daily_cycle_vars[mode]
            try:
                self.controller.set_daily_cycles(mode, int(var.get()))
            except (TypeError, ValueError) as error:
                messagebox.showerror("运行次数无效", str(error), parent=self.root)
                var.set(str(self.controller.daily_cycles[mode]))
                return False
            var.set(str(self.controller.daily_cycles[mode]))
        return True

    def _start_daily(self) -> None:
        """启动每日任务：与单路线共用同一套「先复检环境」的前置流程。"""
        if not self.controller.daily_selection:
            messagebox.showwarning(
                "每日任务", "至少要勾选一项再开始。", parent=self.root
            )
            return
        if not self._collect_daily_cycles():
            return
        # 每日任务里含实验功能路线（世界首领战/骑士团捐赠都是），照单路线那样提醒一次。
        confirmed = messagebox.askyesno(
            "实验功能提醒",
            "每日任务里有仍处于实验阶段的路线，可能不稳定。\n\n是否继续运行？",
            parent=self.root,
        )
        if not confirmed:
            return
        self._checking = True
        self.environment_var.set("正在复检运行环境……")
        self.environment_label.configure(foreground=self._PRIMARY)
        self._refresh_controls()
        # 快照「路线 + 次数」：复检期间用户改了这个快照里的任何一样，这次启动就作废。
        plan = self.controller.daily_plan()

        def check() -> None:
            report = self._preflight_runner(
                window_backend=self.controller.selected_backend
            )
            self.root.after(
                0,
                lambda: self._finish_daily_start_check(plan, report),
            )

        self._thread_factory(
            target=check,
            name="epic7-daily-start-check",
            daemon=True,
        ).start()

    def _finish_daily_start_check(
        self,
        plan: tuple[tuple[str, int], ...],
        report: PreflightReport,
    ) -> None:
        self._checking = False
        self.controller.apply_preflight(report)
        if not report.can_start:
            self.environment_var.set(report.message)
            self.environment_label.configure(foreground=self._ERROR)
            self._append_log(f"运行前复检失败：{report.message}")
            self._refresh_controls()
            return
        if self.controller.daily_plan() != plan:
            self.environment_var.set("每日任务的勾选或次数已变化，本次启动已取消。")
            self.environment_label.configure(foreground=self._ERROR)
            self._refresh_controls()
            return
        self.environment_var.set(report.message)
        self.environment_label.configure(foreground=self._SUCCESS)
        try:
            self.controller.start_daily()
        except Exception as error:
            messagebox.showerror("无法开始", str(error), parent=self.root)
            self._refresh_controls()
            return
        labels = dict(daily_items())
        self._append_log(
            "开始每日任务："
            + "、".join(f"{labels[mode]} {count} 次" for mode, count in plan)
        )
        self._refresh_controls()

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
        self.environment_label.configure(foreground=self._TEXT_SECONDARY)
        self._append_log(
            f"窗口后端已切换为{BACKEND_LABELS[self.controller.selected_backend]}，请重新检测环境。"
        )
        self._refresh_controls()

    def _checking_message(self) -> str:
        if self.controller.selected_backend == "pc":
            return "正在检测 PC 客户端、窗口尺寸和权限……"
        return "正在检测雷电模拟器和截图……"

    def _refresh_route_details(self) -> None:
        route = self.controller.route
        status_text = "正式功能" if not route.experimental else "实验功能，可能不稳定"
        self.route_description_var.set(
            f"{status_text}\n{route.description}"
        )
        self.cycles_var.set(str(self.controller.cycles))
        self.cycles_input.configure(
            state=tk.NORMAL if route.cycles_editable else tk.DISABLED
        )

    def _check_environment(self) -> None:
        if self._checking or self.controller.worker.running:
            return
        self._checking = True
        self.environment_var.set(self._checking_message())
        self.environment_label.configure(foreground=self._PRIMARY)
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
            foreground=self._SUCCESS if report.can_start else self._ERROR
        )
        self._append_log(f"环境检测：{report.message}")
        self._refresh_controls()

    def _start(self) -> None:
        try:
            self.controller.set_cycles(int(self.cycles_var.get()))
        except (TypeError, ValueError) as error:
            messagebox.showerror("运行次数无效", str(error), parent=self.root)
            return
        if self.controller.needs_experimental_confirmation:
            confirmed = messagebox.askyesno(
                "实验功能提醒",
                f"{self.controller.route.label}仍处于实验阶段，可能不稳定。\n\n是否继续运行？",
                parent=self.root,
            )
            if not confirmed:
                return
        self._checking = True
        self.environment_var.set("正在复检运行环境……")
        self.environment_label.configure(foreground=self._PRIMARY)
        self._refresh_controls()
        mode = self.controller.selected_mode

        def check() -> None:
            report = self._preflight_runner(
                window_backend=self.controller.selected_backend
            )
            route_error: Exception | None = None
            if report.can_start:
                try:
                    self._route_validator(mode, self.template_root)
                except Exception as error:
                    route_error = error
            self.root.after(
                0,
                lambda: self._finish_start_check(mode, report, route_error),
            )

        self._thread_factory(
            target=check,
            name="epic7-start-check",
            daemon=True,
        ).start()

    def _finish_start_check(
        self,
        mode: str,
        report: PreflightReport,
        route_error: Exception | None,
    ) -> None:
        self._checking = False
        self.controller.apply_preflight(report)
        if not report.can_start:
            self.environment_var.set(report.message)
            self.environment_label.configure(foreground=self._ERROR)
            self._append_log(f"运行前复检失败：{report.message}")
            self._refresh_controls()
            return
        if route_error is not None:
            message = f"路线资源检查失败：{route_error}"
            self.environment_var.set(message)
            self.environment_label.configure(foreground=self._ERROR)
            self._append_log(message)
            self._refresh_controls()
            return
        if mode != self.controller.selected_mode:
            self.environment_var.set("功能已变化，本次启动已取消。")
            self.environment_label.configure(foreground=self._ERROR)
            self._refresh_controls()
            return
        self.environment_var.set(report.message)
        self.environment_label.configure(foreground=self._SUCCESS)
        try:
            self.controller.start()
        except Exception as error:
            messagebox.showerror("无法开始", str(error), parent=self.root)
            self._refresh_controls()
            return
        self._append_log(
            f"开始运行：{self.controller.route.label}，次数={self.controller.cycles}"
        )
        self._refresh_controls()

    def _stop(self) -> None:
        self.controller.stop()
        self._append_log("已请求安全停止，等待当前检查点退出……")
        self.stop_button.configure(state=tk.DISABLED)

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
        for button in self._route_buttons + self._backend_buttons + self._daily_buttons:
            button.configure(state=route_state)
        self.check_button.configure(
            state=tk.DISABLED if running or self._checking else tk.NORMAL
        )
        self.start_button.configure(
            state=(
                tk.NORMAL
                if self.controller.can_start and not self._checking
                else tk.DISABLED
            )
        )
        # 每日任务按钮：要勾了至少一项、且完成过环境检测、且当前没在跑。
        self.daily_button.configure(
            state=(
                tk.NORMAL
                if self.controller.daily_ready
                and self.controller.can_start
                and not self._checking
                else tk.DISABLED
            )
        )
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        if running:
            self.cycles_input.configure(state=tk.DISABLED)
        else:
            self.cycles_input.configure(
                state=tk.NORMAL if self.controller.route.cycles_editable else tk.DISABLED
            )
        for mode, spinbox in self._daily_cycle_inputs.items():
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

    def _open_diagnostics(self) -> None:
        self._open_directory(
            self.project_root
            / "runtime_diagnostics"
            / f"epic7_{self.controller.selected_mode}"
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
                self.controller.selected_mode,
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
