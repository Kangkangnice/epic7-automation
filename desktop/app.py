"""Tkinter desktop interface for running the existing automation safely."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable

from auto_game_unified.core.data_paths import data_root
from auto_game_unified.desktop import theme
from auto_game_unified.desktop.catalog import (
    DAILY_DESCRIPTION,
    DAILY_LABEL,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    ROUTES,
    RouteInfo,
    grouped_routes,
    route_by_name,
    selectable_modes,
    visible_backends,
)
from auto_game_unified.desktop.diagnostics import export_diagnostics
from auto_game_unified.desktop.onboarding import (
    has_consent,
    prompt_consent,
    record_consent,
)
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
# 运行产物写到哪：源码运行时就是 ROOT，打包安装后是 %LOCALAPPDATA%\Epic7AutoAssistant。
DATA_ROOT = data_root()
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


# 窗口尺寸的上下限（**逻辑像素**，``theme.scale`` 会再乘一次）。
#
# ⚠️ 2026-10-09 用户反馈：「不能自由地调节分辨率，拖动现在太大了，日志都看不清」。
# 两个毛病都在下面 ``initial_window_size`` 里 —— 见那段注释。
#
# 最小可用尺寸：够放得下任务卡头 + 至少 3 行日志。**它只用来挡「拖到不可用」**，
# 不是「推荐尺寸」。窗口的初始尺寸是另一回事（``initial_window_size``）。
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600
# 初始尺寸的上限：**不跟着屏幕撑满**。屏幕再大也别一上来就糊住整个桌面。
# 依据：用户要的是「日志看得清」而不是「窗口尽量大」——宽度超过约 1280 之后，
# 任务卡与日志区都不再受益（日志行本身是短文本），反而挤掉旁边能开的别的窗口。
INITIAL_MAX_WIDTH = 1280
# 初始尺寸占屏幕的上限比例：**宽高分开**。
#
# ⚠️ 为什么不做成同一个比例（2026-10-09 调）：用户的诉求是「日志看得清」，
# 而日志**只吃高度**、不吃宽度。宽度压低能让旁边开别的窗口（用户在看日志时
# 多半要对照游戏/编辑器），高度压低却直接把日志挤到最小值 160px。
# ⇒ 宽度压到 85%（且不超过 ``INITIAL_MAX_WIDTH``），高度给到 92% 让日志有地方长。
INITIAL_SCREEN_RATIO_WIDTH = 0.85
INITIAL_SCREEN_RATIO_HEIGHT = 0.92


def fit_window_size(
    *,
    requested: tuple[int, int],
    screen: tuple[int, int],
    minimum: tuple[int, int] = (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
    max_width: int = INITIAL_MAX_WIDTH,
) -> tuple[int, int]:
    """窗口的**初始**尺寸：够放内容，但**不**撑满屏幕，也**不**小于最小可用尺寸。

    ⚠️ **所有参数与返回值都是「设备像素」**（``winfo_*`` 的原生口径）。
    ``MIN_WINDOW_*`` / ``INITIAL_MAX_WIDTH`` 是**逻辑像素**常量，调用方负责先用
    ``theme.px`` 换算好再传进来（见 ``_fit_initial_window``）。

    ``requested`` 是界面自然需要的尺寸（``winfo_reqwidth/reqheight``），
    ``screen`` 是屏幕尺寸。

    ⚠️ 2026-10-09 用户反馈「不能自由地调节这个分辨率，拖动现在太大了，我的那个
    日志都看不清了」，**这条函数与 ``minsize`` 一起**是病根：

    * 旧版把窗口顶到 ``屏幕-80``（1600x1000 的屏上就是 1520x920）—— 几乎铺满整屏；
    * 旧版随后又用**同一个尺寸**当 ``minsize`` ⇒ 窗口**只能放大、一点拖不小**。

    现在：初始尺寸 = 内容需要 + 一点余量，再被「屏幕比例」和 ``max_width``
    双双压住（**宽度比高度压得更狠**，因为日志只吃高度）；**下限**用 ``minimum``
    （只在 ``_fit_initial_window`` 里设 ``minsize``），两者彻底分开。
    """
    floor_width, floor_height = minimum
    # ① 内容优先：请求尺寸 + 一点余量。
    width = requested[0] + 40
    height = requested[1] + 40
    # ② 别超过屏幕的可视范围（留 40px 给标题栏/任务栏，与旧版口径一致）。
    width = min(width, max(floor_width, screen[0] - 40))
    height = min(height, max(floor_height, screen[1] - 40))
    # ③ 别一上来就铺满 —— 这是「太大了」那一条的正解。
    # ⚠️ 高度比例比宽度宽松（见上面两个常量的注释）：日志只吃高度。
    width = min(width, int(screen[0] * INITIAL_SCREEN_RATIO_WIDTH), max_width)
    height = min(height, int(screen[1] * INITIAL_SCREEN_RATIO_HEIGHT))
    # ④ 再兜一次下限（屏幕极小时 ①~③ 可能把它压到不可用）。
    return max(width, floor_width), max(height, floor_height)


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

    def select_all(self, *, include_events: bool = True) -> None:
        """三个批量按钮的**唯一实现**：把 ``selection`` 换成一整批。

        批量动作用 ``toggle`` 逐条点会有两个毛病：① 每点一条都要跑一遍
        ``standalone_only`` 的互斥逻辑，勾到「活动」时前面已勾好的会被清空，
        最终结果取决于**遍历顺序**（纯属巧合）；② 顺序由遍历决定，而「勾选先后
        就是执行顺序」是用户拍板的语义 —— 批量勾完的顺序应当就是**面板上看到的
        顺序**，不能听遍历的。

        所以这里**整体替换**：直接给出一份有序清单 —— `catalog.selectable_modes`
        **按面板顺序**排好（分组顺序 + 组内书写顺序），正好就是用户看到的那份，
        不逐条走 `toggle`。

        ⚠️ 互斥仍然成立：「全选（不含活动）」本来就把活动排除在外；而
        「全选」把活动一起勾上时，`standalone_only` 的路线与其它路线谁都不能共存 ——
        由于活动组**只有一条**，此时结果就是「只勾活动这一条」。这不是特例，是
        `toggle` 里那条互斥规则在批量语境下的自然结论。
        """
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        wanted = selectable_modes(include_events=include_events)
        if any(route_by_name(mode).standalone_only for mode in wanted):
            # 批里有只能单独跑的（活动）：它与非活动路线互斥 ⇒ 只留它自己。
            wanted = tuple(
                mode for mode in wanted if route_by_name(mode).standalone_only
            )
        self.selection = list(wanted)

    def clear_selection(self) -> None:
        """「取消全选」：一条都不勾，回到「每次自己挑」的初始状态。"""
        if self.worker.running:
            raise RuntimeError("运行期间不能修改任务")
        self.selection.clear()

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
    #
    # ⚠️ 2026-10-08：这里**只有 1~10**。加了「全选（不含活动）」之后一次能勾 12 条，
    # 第 11 位起就没有圈码可用了（`_CIRCLED[10]` 直接 IndexError，整个界面崩）。
    # 圈码不够就退回 `11.` `12.` 这种阿拉伯数字 —— 序号的**语义**是「你排第几」，
    # 不是「必须画个圈」，所以用 `_position_prefix()` 统一出口，不要在这里加字符。
    _CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

    @classmethod
    def _position_prefix(cls, index: int) -> str:
        """第 ``index``（0 起）位的序号前缀：头 10 位用圈码，之后用 `11.` 这类。"""
        if index < len(cls._CIRCLED):
            return cls._CIRCLED[index]
        return f"{index + 1}."

    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: DesktopController,
        project_root: Path = ROOT,
        data_root: Path | None = None,
        preflight_runner: Callable[..., PreflightReport] = run_preflight,
        route_validator: Callable[[str, Path], None] = validate_route_templates,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        consent_required: bool = False,
        consent_probe: Callable[[Path], bool] = has_consent,
        consent_prompt: Callable[[tk.Misc, theme.Theme], bool] = prompt_consent,
    ) -> None:
        self.root = root
        self.controller = controller
        self.project_root = project_root
        # 运行产物（日志 / 诊断 / 诊断包）的根目录。打包安装后与 project_root 不是同一个：
        # 安装目录可能只读，产物必须落到 %LOCALAPPDATA%。见 core/data_paths.py。
        self.data_root = data_root or project_root
        # 「使用须知」确认状态。``consent_required`` 默认 False —— **只有真正的入口
        # （``main()``，也就是用户双击打开的那条路）才把它打开**。测试与嵌入式调用
        # 不该因为没点过同意就被挡在门外，也不该凭空弹一个 grab 住的窗口。
        #
        # ⚠️ 别把默认值改成 True：那样每个构造 `DesktopApp` 的地方都会弹出模态窗，
        # 而现有 GUI 测试正是这么构造它的（见 tests/test_desktop_app.py）。
        self._consent_required = consent_required
        self._consent_probe = consent_probe
        self._consent_prompt = consent_prompt
        self.consented = (not consent_required) or consent_probe(self.data_root)
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
        # 「每日任务」那张卡。`_task_panel_descendants()`（测试导航用）与折叠
        # （``_set_task_panel_collapsed``）都拿它当根 —— 但**只用来 grid /
        # grid_remove**，别拿它去算任何尺寸（尺寸一律走令牌与 grid 权重）。
        self._task_panel: ttk.Frame | None = None
        # 「任务清单」是不是收起来了。
        #
        # ⚠️ 用户 2026-10-09 的诉求：跑起来之后日志只剩 6 行，最后一行还被切掉。
        # 实测（截图量像素）：窗口 1844px 高，日志区**只有 171px、占 9.3%** ——
        # 连它自己的下限（``theme.LOG_MIN_HEIGHT`` = 160 逻辑像素 = 320 物理像素）
        # 都没保住，因为上方那张清单一直完整展开、把高度吃光了。
        # 收起之后省下来的高度全部落到日志区（它是唯一 ``weight=1`` 的行）。
        self._task_collapsed = False

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
        # 主窗口先画出来再弹须知：反过来的话，模态窗后面是一片空白，
        # 用户会以为自己只打开了对话框、根本没装上东西。
        self.root.after(150, self._ensure_consent)
        self.root.after(100, self._poll_worker)

    def _fit_initial_window(self) -> None:
        """摆好窗口的初始尺寸，并把**最小尺寸与它分开**。

        ⚠️ 2026-10-09 之前这里写的是 ``self.root.minsize(width, height)`` ——
        拿**初始尺寸**当最小尺寸，等于把窗口**锁死**：用户拖不小（用户原话
        「不能自由地调节这个分辨率，拖动现在太大了，我的那个日志都看不清了」）。

        现在两件事分开：
        * 初始尺寸交给 ``fit_window_size``（够用即可，不铺满屏幕）；
        * 最小尺寸固定为 ``MIN_WINDOW_*``（只防「拖到没法用」，挡不住用户缩小）。

        ⚠️ ``winfo_*`` 给的是**设备像素**，而 ``MIN_WINDOW_*`` 是**逻辑像素**
        —— 这里统一成设备像素再交给 ``fit_window_size``，``minsize`` 也走
        ``theme.px``。高 DPI 屏上不换算会让下限偏小一半。
        """
        self.root.update_idletasks()
        floor = (
            self.theme.px(MIN_WINDOW_WIDTH),
            self.theme.px(MIN_WINDOW_HEIGHT),
        )
        width, height = fit_window_size(
            requested=(self.root.winfo_reqwidth(), self.root.winfo_reqheight()),
            screen=(self.root.winfo_screenwidth(), self.root.winfo_screenheight()),
            minimum=floor,
            max_width=self.theme.px(INITIAL_MAX_WIDTH),
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(*floor)

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
        self._task_panel = self._build_task_panel(outer)
        self._task_panel.grid(row=1, column=0, sticky="ew", pady=(gap, 0))
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

        # 第三行：「能跑、但大概率点不动」的提示（目前只有一种 —— 模拟器权限比我们高，
        # 点击会被 UIPI 拦掉）。平时用 grid_remove 收起，既不留空行也不占高度。
        self.warning_var = tk.StringVar(value="")
        self.warning_label = tk.Label(
            bar,
            textvariable=self.warning_var,
            background=palette.surface,
            foreground=palette.error,
            font=self.theme.font(theme.TYPE_CAPTION, bold=True),
            anchor="w",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        self.warning_label.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(px(theme.SPACE_XL), px(theme.SPACE_LG)),
            pady=(px(theme.SPACE_XS), 0),
        )
        self.warning_label.bind("<Configure>", self._wrap_at_own_width)
        self.warning_label.grid_remove()


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

        排布要点（2026-10-08 分组改版）：
        - 路线按 `catalog.GROUPS` 分成 **日常 / 赛季 / 活动** 三段，每段一个
          小标题；分组的**内容与次序**都从 catalog 读，这里不写中文字面量、
          也不自己遍历 `ROUTES`（插一条新路线只改 catalog）；
        - 卡头右侧那三个小按钮是**批量勾选**（全选 / 全选（不含活动）/ 取消全选），
          逻辑在 `DesktopController.select_all` / `clear_selection`；
        - 每段内部：列数由 `theme.route_columns()` 算出来，一条路线一格，
          **格内紧贴、格间留白**（`weight=1` 让每格平均吃伸缩）⇒ 富余宽度落在
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
        # 右边一大片空白。同行之后它摊满标题右侧那段空白，两行内说完。
        hint = ttk.Label(
            head,
            text=DAILY_DESCRIPTION,
            style="Body.TLabel",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        hint.grid(row=0, column=1, sticky="ew", padx=(px(theme.SPACE_XL), 0))
        hint.bind("<Configure>", self._wrap_at_own_width)
        # 三个批量按钮紧贴卡头右端。放在**卡头**而不是各组标题旁，是因为
        # 「全选（不含活动）」天然是跨组的动作 —— 挂在任何一组下面都名不副实。
        self._build_bulk_buttons(head).grid(row=0, column=2, sticky="e")

        # 分组渲染：`grouped_routes()` 已按展示顺序排好、且滤掉空组。
        row = 1
        for group, routes in grouped_routes():
            ttk.Label(panel, text=group, style="Group.TLabel").grid(
                row=row,
                column=0,
                columnspan=columns,
                sticky="w",
                # 组标题上方留得比组内行距大 ⇒ 一眼看出「标题属于下面那一堆」，
                # 而不是浮在上一组的尾巴上。
                pady=(px(theme.SPACE_LG), px(theme.SPACE_XS)),
            )
            row += 1
            self._build_group_grid(panel, routes, first_row=row)
            row += -(-len(routes) // columns)

        # 每格平均吃伸缩：窗口拉宽时组间距一起变大，而不是全挤在末尾。
        for column in range(columns):
            panel.grid_columnconfigure(column, weight=1)

        self.route_description_var = tk.StringVar()
        description = ttk.Label(
            panel,
            textvariable=self.route_description_var,
            style="Body.TLabel",
            justify="left",
            wraplength=px(theme.WRAP_MIN_WIDTH),
        )
        description.grid(
            row=row,
            column=0,
            columnspan=columns,
            sticky="ew",
            pady=(px(theme.SPACE_MD), 0),
        )
        description.bind("<Configure>", self._wrap_at_own_width)
        return panel

    def _build_bulk_buttons(self, parent: ttk.Frame) -> ttk.Frame:
        """卡头右端那三个批量勾选按钮。

        ⚠️ 三颗按钮的**文案与动作成对**写死在这里，但「勾哪些」一律问
        `catalog.selectable_modes` —— 界面层不写路线名单。
        「不含活动」的语义由 `include_events=False` 表达，不是这里再减一遍。
        """
        px = self.theme.px
        bar = ttk.Frame(parent, style="Card.TFrame")
        for text, command in (
            ("全选", lambda: self._bulk_select(include_events=True)),
            ("全选（不含活动）", lambda: self._bulk_select(include_events=False)),
            ("取消全选", self._bulk_clear),
        ):
            ttk.Button(bar, text=text, style="Tool.TButton", command=command).pack(
                side=tk.LEFT, padx=(px(theme.SPACE_SM), 0)
            )
        return bar

    def _build_group_grid(
        self,
        panel: ttk.Frame,
        routes: tuple[RouteInfo, ...],
        *,
        first_row: int,
    ) -> None:
        """把某一组的路线铺进 `panel` 的网格里（从 `first_row` 往下）。

        路线是**扁平**地排在同一个 grid 上的（不是每组套一个子 Frame）——
        这样各组的格子共用同一套列宽，三个分组左边缘对齐，纵向看是一张表；
        套子 Frame 的话每组各算各的列宽，组和组之间会错开。
        """
        px = self.theme.px
        for offset, route in enumerate(routes):
            row, column = divmod(offset, self._route_columns_count)
            # 每条路线是一个**紧贴的组**（勾选框 + 次数框 + 「次」），组内用 pack
            # 贴着排；富余宽度留在组**外面**（格子的右边距 + 整列拉伸）。
            # 这样「格内间距 < 组间距」，一眼能看出次数属于哪条路线 ——
            # 反过来（富余塞进组内）会让次数框离下一条路线更近，读错。
            cell = ttk.Frame(panel, style="Card.TFrame")
            cell.grid(
                row=row + first_row,
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

    def _wrap_at_own_width(self, event: tk.Event) -> None:
        """说明文字按**自己那一格的宽度**换行。

        各处说明文字能用的宽度不一样（标题右边那段要扣掉标题、卡片底部那条是整个
        宽度），所以不去算「可用宽度」，直接跟着控件自己的实际宽度走。宽度没变就
        不动，免得反复触发布局。
        """
        if int(event.widget.cget("wraplength")) != event.width:
            event.widget.configure(wraplength=event.width)

    def _task_panel_descendants(self) -> tuple[tk.Misc, ...]:
        """「每日任务」那张卡里的全部子控件（**不含**面板自己），深度不限。

        给测试用：分组标题 / 批量按钮散在网格的各个行列上，没有稳定的控件名，
        测试要能找到它们。⚠️ 这不是「界面逻辑」——生产代码不调它，
        也不靠它做任何判断（那种「遍历自己的控件来决定行为」的写法会让
        改布局就改行为）。
        """
        if self._task_panel is None:  # pragma: no cover - 构造期不会这样
            return ()
        found: list[tk.Misc] = []
        pending = list(self._task_panel.winfo_children())
        while pending:
            widget = pending.pop()
            found.append(widget)
            pending.extend(widget.winfo_children())
        return tuple(found)

    def _route_text(self, mode: str) -> str:
        """勾选框上的文字：``序号 名字 [正式/实验]``。

        没勾选时用全角空格占位，勾上之后文字不会整体右移。
        """
        route = route_by_name(mode)
        marker = "正式" if not route.experimental else "实验"
        if mode in self.controller.selection:
            prefix = self._position_prefix(self.controller.selection.index(mode))
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
        # 收起任务清单 = 把高度让给日志（见 ``_set_task_panel_collapsed``）。
        # 按钮放在**这一条**上而不是清单卡头里：清单收起来之后卡头也没了，
        # 按钮搁在里头就没人能再把它展开。
        self.collapse_button = ttk.Button(
            actions,
            text="收起清单",
            style="Tool.TButton",
            command=self._toggle_task_panel,
        )
        self.collapse_button.pack(side=tk.LEFT, padx=(px(theme.SPACE_MD), 0))

        # 中间那一栏原本是纯留白（``columnconfigure(1, weight=1)``）。清单收起后
        # 计划就从界面上消失了，所以这一栏用来放一行摘要 —— 它是「收起」能不让人
        # 心里没底的前提，不是额外的功能。
        self.plan_summary_var = tk.StringVar(value="")
        self.plan_summary_label = ttk.Label(
            bar, textvariable=self.plan_summary_var, style="Caption.TLabel"
        )
        self.plan_summary_label.grid(
            row=0, column=1, sticky="w", padx=(px(theme.SPACE_XL), px(theme.SPACE_LG))
        )

        utilities = ttk.Frame(bar, style="Bar.TFrame")
        utilities.grid(row=0, column=2, sticky="e")
        for index, (text, command) in enumerate(
            (
                ("使用须知", self._show_onboarding),
                ("打开日志", self._open_logs),
                ("打开诊断", self._open_diagnostics),
                ("导出诊断包", self._export),
            )
        ):
            ttk.Button(utilities, text=text, style="Tool.TButton", command=command).pack(
                side=tk.LEFT, padx=(px(theme.SPACE_SM) if index else 0, 0)
            )
        return bar

    def _toggle_task_panel(self) -> None:
        self._set_task_panel_collapsed(not self._task_collapsed)

    def _set_task_panel_collapsed(self, collapsed: bool) -> None:
        """收起／展开「任务清单」那一整块，把省下的高度全部让给日志区。

        日志区是整窗**唯一** ``weight=1`` 的那一行（``_build_layout``），所以清单一
        收起，省下的高度自动全归它 —— 窗口再拖大时也跟着一起长。

        ⚠️ 用 ``grid_remove`` 而不是 ``grid_forget``：前者**记住**原来的 grid 参数，
        展开时一句无参 ``grid()`` 就回原位。用 forget 就得把
        ``row / column / sticky / pady`` 再抄一遍 —— 同一件事写两处，以后改了这里
        忘了那里（``_build_layout`` 里那几个参数）。
        """
        if self._task_panel is None or collapsed == self._task_collapsed:
            return
        self._task_collapsed = collapsed
        if collapsed:
            self._task_panel.grid_remove()
        else:
            self._task_panel.grid()
        self.collapse_button.configure(text="展开清单" if collapsed else "收起清单")
        self._refresh_plan_summary()

    def _refresh_plan_summary(self) -> None:
        """收起时在操作条中间写「这次要跑什么」；展开时清空（信息本来就在眼前）。"""
        if not self._task_collapsed:
            self.plan_summary_var.set("")
            return
        chosen = list(self.controller.selection)
        if not chosen:
            self.plan_summary_var.set("（没有勾选任何路线）")
            return
        names = "、".join(route_by_name(mode).label for mode in chosen)
        self.plan_summary_var.set(f"本次依次运行 {len(chosen)} 条：{names}")

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

    def _bulk_select(self, *, include_events: bool) -> None:
        """「全选」/「全选（不含活动）」。勾选顺序 = 面板顺序（见 `select_all`）。"""
        try:
            self.controller.select_all(include_events=include_events)
        except Exception as error:
            messagebox.showerror("无法修改任务", str(error), parent=self.root)
            return
        self._after_bulk_change()

    def _bulk_clear(self) -> None:
        """「取消全选」：一条都不勾（= 出厂状态，每次自己挑）。"""
        try:
            self.controller.clear_selection()
        except Exception as error:
            messagebox.showerror("无法修改任务", str(error), parent=self.root)
            return
        self._after_bulk_change()

    def _after_bulk_change(self) -> None:
        """批量改完勾选后的统一收尾 —— 和单条 `_on_toggle` 走同一套刷新。

        ⚠️ 三处刷新一个都不能少：勾选状态与序号（`_refresh_task_rows`）、
        底部说明（`_refresh_route_details`，它读的是「最后勾的那条」）、
        以及「开始任务」按钮的可用性（`_refresh_controls`）。
        """
        self._refresh_task_rows()
        self._refresh_route_details()
        self._refresh_controls()

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
            self._refresh_plan_summary()
            return
        route = route_by_name(self.controller.selection[-1])
        status_text = "正式功能" if not route.experimental else "实验功能，可能不稳定"
        self.route_description_var.set(
            f"【{route.label}】{status_text}\n{route.description}"
        )
        # 收起状态下摘要就摆在操作条上，勾选一变它得跟着变。
        self._refresh_plan_summary()

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
        self._show_warning(report.warning)
        self._append_log(f"环境检测：{report.message}")
        self._refresh_controls()

    def _show_warning(self, warning: str | None) -> None:
        """状态带第三行：只在「能跑、但大概率点不动」时出现，没有就收起。

        ⚠️ 不要把它塞进 `environment_var` 同一个 label：那一行是「检测结果」，
        用绿/红表示通过与否；把提示拼进去会让「通过」变绿的同时挂着一段红字。
        """
        if not warning:
            self.warning_label.grid_remove()
            return
        self.warning_var.set(warning)
        self.warning_label.grid()
        self._append_log(f"注意：{warning}")

    def _start(self) -> None:
        """唯一的启动入口：勾了哪几条就跑哪几条，按勾选先后依次跑。

        流程与原来「单路线」那条通道逐字同形：收次数 → 实验功能提醒 → 复检环境 →
        逐条查模板 → 启动。两条通道合并之后，以后改这里只有一处。
        """
        if not self.consented:
            # 按钮本来就该是灰的（见 ``_refresh_controls``）。走到这里只可能是
            # 有人绕过了按钮状态（脚本调用 / 事件顺序异常），仍然守住这条线。
            messagebox.showwarning(
                "使用须知", "请先阅读并同意《使用须知》再开始。", parent=self.root
            )
            return
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
        # 跑起来之后清单就没用了 —— 收起它，把高度让给日志（跑完自动展开，见
        # ``_poll_worker``）。放在真正 start 成功之后：复检失败提前返回时清单照旧。
        self._set_task_panel_collapsed(True)
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
                # 跑完了，清单该回来 —— 下次要改勾选和次数就在那张卡上。
                self._set_task_panel_collapsed(False)
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
        # 「开始任务」：要勾了至少一条、且完成过环境检测、且当前没在跑、且确认过使用须知。
        self.start_button.configure(
            state=(
                tk.NORMAL
                if self.controller.ready
                and self.controller.can_start
                and self.consented
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

    def _ensure_consent(self) -> None:
        """首次启动（或条款改版后）确认一次使用须知。

        拒绝不弹第二个窗、不拦着关窗口，只在日志里说明「开始任务」为什么点不动、
        去哪里能重新看 —— 它本来就该由**按钮状态**表达，而不是一串弹窗。
        """
        if self.consented or not self._consent_required:
            return
        if not self._consent_prompt(self.root, self.theme):
            self._append_log(
                "尚未确认使用须知，「开始任务」保持禁用。"
                "想阅读时点控制条右侧的「使用须知」。"
            )
            return
        self._grant_consent()
        # 新手确认完的下一步几乎一定是「现在能不能跑」——直接替他点一次检测，
        # 省掉「还得自己找到检测按钮」。检测本来就只读，跑失败也只是给出一句原因。
        self._check_environment()

    def _grant_consent(self) -> None:
        """记下「已同意」，并把按钮状态刷回来。

        ⚠️ 落盘失败**照样放行**：用户刚刚确实点了同意，写不进去是这个目录的问题
        （`core/data_paths.py` 的自检会报），不是让他在门口再走一遍的理由。
        代价只是下次启动再问一次，可以接受。
        """
        self.consented = True
        if not record_consent(self.data_root):
            self._append_log(
                f"提示：无法保存确认记录（{self.data_root} 不可写），下次启动会再问一次。"
            )
        self._refresh_controls()

    def _show_onboarding(self) -> None:
        """控制条上的「使用须知」：已同意过的只是重看，未同意的走一次完整确认。"""
        if self.consented:
            self._consent_prompt(self.root, self.theme)
            return
        self._ensure_consent()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_logs(self) -> None:
        self._open_directory(self.data_root / "runtime_logs")

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
            self.data_root
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
                root=self.data_root,
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
    worker = WorkerController(repo_parent=REPO_PARENT, data_root=DATA_ROOT)
    controller = DesktopController(worker=worker)
    # 这里是**用户双击打开**的那条路，也是全项目唯一开 `consent_required` 的地方。
    DesktopApp(
        root, controller=controller, data_root=DATA_ROOT, consent_required=True
    )
    root.mainloop()
    return 0
