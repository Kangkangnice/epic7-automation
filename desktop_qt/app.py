"""桌面界面（Qt / Fluent）。

启动：``python -m auto_game_unified.desktop_qt``（``desktop`` 那个入口也转发到这里）
依赖：``python -m pip install -r requirements.txt``

⚠️ 2026-11-09 起这是**唯一**的界面。原来那套 Tk 界面（``desktop/app.py``、
``desktop/theme.py``、``desktop/launch_hidden.py``）已按用户要求整体删除；
``EPIC7_UI=qt`` 这个环境变量开关也一并删掉 —— 只有一条路就不需要开关。

## 业务状态在哪

``DesktopController`` 是「勾了哪几条、每条几次、用哪个后端、能不能开跑」这套
**与界面无关的业务状态**，住在 ``desktop/controller.py``，不 import 任何界面库。
界面只负责把它的真相画出来、把用户的操作喂回去。

## 已对齐 / 还欠什么

已对齐：四分组勾选（含整组勾选与活动互斥）、序号即执行顺序、次数输入与只读路线、
后端切换、PC「不占用前台」开关、环境检测、开始前复检（含逐条模板校验）、
安全停止（含 30 秒强杀兜底）、实时日志轮询、会话存档、窗口几何记忆、诊断包导出、
首次使用须知、版本检查、实用工具（连点器）。

刻意**不做**「多套命名配置」（日常 / 活动 / 周末那套保存与切换）：2026-11-09 用户
明确说不需要。勾选与次数已经按会话存档自动记住上次，日常真正用得上的就是那条。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    SubtitleLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    StrongBodyLabel,
    SwitchButton,
    TextEdit,
    TitleLabel,
    setTheme,
    setThemeColor,
    Theme,
)

from auto_game_unified.core.autoclicker import AutoClicker
from auto_game_unified.core.data_paths import data_root
from auto_game_unified.core.pc_window import (
    PC_INPUT_BACKGROUND,
    PC_INPUT_FOREGROUND,
)
from auto_game_unified.desktop import session
from auto_game_unified.desktop.catalog import (
    BACKEND_LABELS,
    PRODUCT_VERSION,
    STARTUP_HINTS,
    group_description,
    grouped_routes,
    route_by_name,
    routes_in_group,
    unavailable_note,
    visible_backends,
)
from auto_game_unified.desktop.chaos_bridge import ChaosBridge, bundled as e7auto_bundled
from auto_game_unified.desktop.controller import DesktopController
from auto_game_unified.desktop.diagnostics import export_diagnostics
from auto_game_unified.desktop.report import short_code_of
from auto_game_unified.desktop.graceful_exit import EmulatorQuitGate
from auto_game_unified.desktop.onboarding import has_consent, record_consent
from auto_game_unified.desktop.preflight import (
    run_preflight,
    template_root_for_backend,
    validate_start_plan,
)
from auto_game_unified.desktop.run_progress import extract_run_result
from auto_game_unified.desktop.shutdown import (
    SHUTDOWN_DELAY_SECONDS,
    ShutdownScheduler,
)
from auto_game_unified.desktop.update_check import check_for_update
from auto_game_unified.desktop.worker import WorkerController
from auto_game_unified.desktop_qt import brand
from auto_game_unified.desktop_qt.mascot import ArkyMascot
from auto_game_unified.desktop_qt.route_options_dialog import RouteOptionsDialog
from auto_game_unified.games.epic7.route_options import options_for
from auto_game_unified.desktop_qt.autoclicker import AutoClickerPage
from auto_game_unified.desktop_qt.dimension_probe import DimensionProbePage
from auto_game_unified.desktop_qt.floating import FloatingRunner
from auto_game_unified.desktop_qt.onboarding import prompt_consent
from auto_game_unified.desktop_qt.style import SPIN_BOX_QSS

ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = ROOT.parent
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
DATA_ROOT = data_root()
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

# 点了「安全停止」之后的宽限期：过了还不退，就强行结束这个卡住的运行。
#
# 依据（2026-08-31 ~ 2026-09-28 的 ``desktop_worker.log``）：88 次正常停止**全部**
# 在 1~2 秒内以退出码 130 结束，只有 2 次「停止请求之后没有任何结束」——都是运行
# 卡在**一次底层调用内部**（等一次点击的回执），永远轮不到「动作之间查停止信号」。
# 所以 30 秒 = 正常路径的十几倍。
# ⚠️ **别调小**：万一停止正好落在一次**正常收尾**的动作里，强行结束会让它跳过回家
# 流程（游戏停在半路）。宁可多等，也不误杀。
STOP_GRACE_MS = 30_000
# 宽限期内的轮询间隔 —— 只决定「多久发现它其实已经退了」，不是超时精度。
STOP_POLL_MS = 500


def _position_prefix(index: int) -> str:
    """序号前缀：头 10 位用圈码，之后退成 `11.`（版面放不下第 11 个圈码）。"""
    return _CIRCLED[index] if index < len(_CIRCLED) else f"{index + 1}."


class _Bridge(QObject):
    """后台线程 → 主线程的唯一通道（PySide6 跨线程 emit 自动走 queued connection）。"""

    check_done = Signal(object)          # PreflightReport 或 Exception
    start_done = Signal(object, object)  # (PreflightReport 或 None, Exception 或 None)
    update_done = Signal(object)         # UpdateInfo 或 None


class QtDesktopWindow(FluentWindow):
    """Fluent 风格主窗口：左导航（任务 / 日志 / 关于），业务状态全交给 controller。"""

    def __init__(
        self,
        *,
        controller: DesktopController,
        worker: WorkerController,
        data_root: Path,
        template_root: Path,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.worker = worker
        self.data_root = Path(data_root)
        self.template_root = Path(template_root)
        self._session_path = session.session_path(self.data_root)
        self._bridge = _Bridge()
        self._bridge.check_done.connect(self._on_check_done)
        self._bridge.start_done.connect(self._on_start_done)
        self._bridge.update_done.connect(self._on_update_done)
        self._route_checks: dict[str, CheckBox] = {}
        self._route_spins: dict[str, QSpinBox] = {}
        self._group_checks: dict[str, CheckBox] = {}
        # 只给声明了可选项的路线建「设置」入口。
        self._route_option_buttons: dict[str, PushButton] = {}
        # 说明卡当前显示的是哪条路线（None = 显示的是分组说明）。
        # 切窗口后端时要靠它重算标题下面那行「这条能不能跑」。
        self._detail_mode: str | None = None
        self._suspend_events = False
        self._checking = False
        self._last_running = False
        # 「使用须知」确认状态。判定与落盘都在 desktop/onboarding.py（产品条款），
        # 这里只管「没同意就别让开始任务亮起来」。
        self.consented = has_consent(self.data_root)
        self._update_info = None
        # 连点器是**独立于路线**的通用工具：一个后台线程 + 一组固定坐标，
        # 业务状态全在 core/autoclicker.py。这里只持有它，好让两件事互斥：
        # 每日任务在跑时不许开连点，连点在跑时不许开始任务。
        self.autoclicker = AutoClicker()
        # 次元探查：第三方 chaos 流程内置在同进程里跑，不进路线名单。
        # 这里持有运行控制器，好让三方互斥（每日任务 / 连点器 / 次元探查）。
        self.dimension = ChaosBridge()
        # 「跑完自动关机」：默认关闭，而且**不写进会话存档** —— 关机是不可逆操作，
        # 「上次开着」不该让下一次也开着（用户 2026-11-12 要求「默认是关闭的」）。
        # 每次打开助手都是关的，要关机的那个晚上自己拨一下。
        self.shutdown = ShutdownScheduler()
        # 关机前先把模拟器请出去（2026-11-14 事故：模拟器还开着就被 shutdown，
        # 强关留下半截的驱动状态，次日开机进「启动修复」）。
        self.emulator_quit = EmulatorQuitGate()
        # 用户点过「安全停止」⇒ 这一轮不是「跑完」，不触发关机。
        # 单独记标记而不是只看退出码：卡死被强杀时退出码是 1（与「运行失败」同码），
        # 光看退出码会把「我按了停止」误判成「它自己跑失败了」。
        self._stop_requested_by_user = False
        # 本次失败生成的诊断包路径。失败卡片的两个动作都从这里取，避免再解析文本。
        self._report_path: Path | None = None
        # 关机倒计时的收尾计时器（到点就把「取消关机」按钮收起来）。第一次排定才建。
        self._shutdown_timer: QTimer | None = None
        # 等模拟器退出的轮询计时器（每秒问一次）。第一次用到才建。
        self._shutdown_wait_timer: QTimer | None = None
        # 停止兜底的计时器（见 _start_stop_watchdog）。第一次点停止时才建。
        self._stop_timer: QTimer | None = None
        self._stop_deadline = 0.0

        previous = session.load(self._session_path)
        if previous is not None:
            controller.apply_session(previous)

        self._build_task_page()
        self._build_log_page()
        self._build_tools_page()
        self._build_dimension_page()
        self._build_about_page()
        self._sync_from_controller()
        self._show_group_detail(grouped_routes()[0][0])
        # 上次跑完的结算留在存档里：打开软件就能看到，不用先跑一轮。
        if previous is not None and previous.last_run is not None:
            self._show_run_result(
                previous.last_run.at,
                previous.last_run.summary,
                previous.last_run.details,
            )

        self.setWindowTitle(f"{brand.APP_NAME}  {PRODUCT_VERSION}")
        self.setWindowIcon(brand.app_icon())
        # 禁用原生透明效果后直接画底色，避免首次显示时标题栏还使用透明背景。
        self.setMicaEffectEnabled(False)
        window_color = QColor("#F1F8FC")
        self.setCustomBackgroundColor(window_color, window_color)
        self.backgroundColorAni.stop()
        self.setBackgroundColor(window_color)
        self.navigationInterface.setExpandWidth(145)
        self.navigationInterface.setMinimumExpandWidth(960)
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.panel.layout().setContentsMargins(0, 48, 0, 0)
        # 首屏默认只占可用屏幕的一半左右，用户自己拖大；不要一开就铺满。
        # ⚠️ 不能写死像素：4K 与 1080p 上「1180x800」的含义完全不同。
        self.setMinimumSize(860, 560)
        self.resize(*self._initial_size())
        self._restore_geometry(previous)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_worker)
        self._poll_timer.start(120)

        # 先让主界面画出来再弹须知：反过来的话，对话框后面是一片空白，
        # 用户会以为自己只打开了对话框、根本没装上东西（Tk 版当年同一条理由）。
        QTimer.singleShot(150, self._ensure_consent)
        # 版本检查排在须知之后、且更晚：先把该看到的画出来，再在后台悄悄问一次。
        # 它没有任何阻塞行为，慢也不会影响使用。
        QTimer.singleShot(400, self._start_update_check)
        # 开始任务后收成悬浮球；便签与球的停放位置都沿用会话存档。
        ball_pos = None
        if previous is not None and previous.ball_pos is not None:
            try:
                ball_pos = (int(previous.ball_pos["x"]), int(previous.ball_pos["y"]))
            except (KeyError, TypeError, ValueError):
                ball_pos = None
        self.floating = FloatingRunner(
            previous.todos if previous is not None else ("",),
            ball_pos,
        )
        self.floating.todos_changed.connect(self._save_todos)
        self.floating.ball_moved.connect(self._save_ball_pos)
        self.floating.open_main_requested.connect(self._return_to_main_window)

    # ── 构建界面 ────────────────────────────────────────────────────────────

    def _build_task_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("taskView")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 12, 24, 12)
        outer.setSpacing(8)

        heading = QHBoxLayout()
        heading.addWidget(SubtitleLabel("任务中心", page))
        heading.addStretch(1)
        heading.addWidget(CaptionLabel(brand.APP_SUBTITLE, page))
        outer.addLayout(heading)
        outer.addWidget(self._build_status_card())
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_route_scroll(), 3)
        middle.addWidget(self._build_detail_card(), 2)
        outer.addLayout(middle, 1)
        outer.addLayout(self._build_action_bar())
        self.addSubInterface(page, FluentIcon.HOME, "任务中心")

    def _build_status_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setBorderRadius(12)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)
        layout.addWidget(StrongBodyLabel("运行环境", card))

        self.status_label = BodyLabel("尚未执行环境检测。", card)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.hint_label = CaptionLabel("", card)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        # 「发现新版本」那一行。默认收起（hidden），有新版才露面。
        # 用自带链接的 QLabel：点了交给系统浏览器，**不下载、不替换任何文件**。
        self.update_label = CaptionLabel("", card)
        self.update_label.setWordWrap(True)
        self.update_label.setOpenExternalLinks(True)
        self.update_label.setVisible(False)
        layout.addWidget(self.update_label)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(BodyLabel("游戏窗口", card))
        self.backend_combo = ComboBox(card)
        for backend in visible_backends():
            self.backend_combo.addItem(BACKEND_LABELS[backend], userData=backend)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        row.addWidget(self.backend_combo)

        row.addSpacing(16)
        row.addWidget(BodyLabel("不占用前台", card))
        self.background_switch = SwitchButton(card)
        self.background_switch.setOnText("")
        self.background_switch.setOffText("")
        self.background_switch.setAccessibleName("不占用前台")
        self.background_switch.checkedChanged.connect(self._on_background_changed)
        row.addWidget(self.background_switch)
        row.addStretch(1)

        self.check_button = PushButton(FluentIcon.SYNC, "检测环境", card)
        self.check_button.clicked.connect(self._on_check_clicked)
        row.addWidget(self.check_button)
        layout.addLayout(row)
        return card

    def _build_route_scroll(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(StrongBodyLabel("任务清单", page))

        tabs = SegmentedWidget(page)
        layout.addWidget(tabs)
        stack = QStackedWidget(page)
        layout.addWidget(stack, 1)

        groups = grouped_routes()
        group_indexes = {group: index for index, (group, _) in enumerate(groups)}
        for group, routes in groups:
            scroll = QScrollArea(stack)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            scroll.viewport().setAutoFillBackground(False)
            holder = QWidget(scroll)
            column = QVBoxLayout(holder)
            column.setContentsMargins(0, 0, 4, 4)
            card = CardWidget(holder)
            card.setBorderRadius(10)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            card_layout.setSpacing(4)

            group_box = CheckBox(f"{group}  ·  整组勾选", card)
            group_box.toggled.connect(
                lambda checked, g=group: self._on_group_toggled(g, checked)
            )
            self._group_checks[group] = group_box
            card_layout.addWidget(group_box)

            for route in routes:
                line = QHBoxLayout()
                line.setSpacing(8)
                line.addWidget(brand.route_emblem(route.mode, card))
                box = CheckBox(route.label, card)
                box.toggled.connect(
                    lambda checked, m=route.mode: self._on_route_toggled(m, checked)
                )
                box.setToolTip(route.description)
                self._route_checks[route.mode] = box
                line.addWidget(box, 1)

                spin = QSpinBox(card)
                spin.setStyleSheet(SPIN_BOX_QSS)
                # 上限给到三位数：刷书签这类路线一轮只扫一次，半天下来要上百轮。
                spin.setRange(route.min_cycles, 999)
                spin.setFixedWidth(88)
                # 次数固定 = 标准「禁用」态。我们自己的 QSS 把禁用文字写成
                # #5B5B5B on #F3F4F6（6.2:1），数字照样看得见；
                # 不用 readOnly + NoButtons —— 那个组合在 Qt 6.12 下会让文字消失。
                spin.setEnabled(route.cycles_editable)
                spin.valueChanged.connect(
                    lambda value, m=route.mode: self._on_cycles_changed(m, value)
                )
                self._route_spins[route.mode] = spin
                line.addWidget(spin)
                if options_for(route.mode):
                    settings = PushButton("设置", card)
                    settings.setFixedWidth(64)
                    settings.clicked.connect(
                        lambda _checked=False, m=route.mode: self._on_route_options_clicked(m)
                    )
                    self._route_option_buttons[route.mode] = settings
                    line.addWidget(settings)
                else:
                    line.addSpacing(72)
                card_layout.addLayout(line)

                box.clicked.connect(
                    lambda _checked=False, m=route.mode: self._show_route_detail(m)
                )

            column.addWidget(card)
            column.addStretch(1)
            scroll.setWidget(holder)
            stack.addWidget(scroll)
            tabs.addItem(group, group)
            tabs.widget(group).setAccessibleName(group)

        def show_group(group: str) -> None:
            stack.setCurrentIndex(group_indexes[group])
            self._show_group_detail(group)

        tabs.setCurrentItem(groups[0][0])
        tabs.currentItemChanged.connect(show_group)
        return page

    def _build_detail_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setBorderRadius(12)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(ArkyMascot(card, height=112))
        self.detail_title = StrongBodyLabel("", card)
        layout.addWidget(self.detail_title)
        # 「这条路线在当前后端跑不了」放在**标题正下方**，不放到卡片最底下 ——
        # 说明正文现在写的是业务动作，读者看完才知道会被跳过就已经点过开始任务了。
        # 没有这行提示时整块隐藏，免得留一条空白把标题与正文撑开。
        self.pc_note = CaptionLabel("", card)
        self.pc_note.setWordWrap(True)
        self.pc_note.setVisible(False)
        layout.addWidget(self.pc_note)
        scroller = QScrollArea(card)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidgetResizable(True)
        scroller.setStyleSheet("QScrollArea { background: transparent; }")
        scroller.viewport().setAutoFillBackground(False)
        self.detail_body = BodyLabel("", scroller)
        self.detail_body.setAutoFillBackground(False)
        self.detail_body.setStyleSheet("QLabel { background: transparent; color: #172F46; }")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignTop)
        scroller.setWidget(self.detail_body)
        layout.addWidget(scroller, 1)
        self.selection_summary = CaptionLabel("", card)
        self.selection_summary.setWordWrap(True)
        self.selection_summary.setStyleSheet(
            "QLabel { background: #E9F5FC; color: #21577E; border-radius: 6px; padding: 6px; }"
        )
        layout.addWidget(self.selection_summary)
        return card

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.run_state_label = CaptionLabel("待执行", self)
        bar.addWidget(self.run_state_label)
        bar.addSpacing(16)
        # 「完成后关机」是本次运行之后做什么，和「开始任务」放在一起，
        # 点开始前一眼能看见；不放进上面的环境卡（那张卡说的是怎么连游戏）。
        bar.addWidget(BodyLabel("完成后关机", self))
        self.shutdown_switch = SwitchButton(self)
        self.shutdown_switch.setOnText("")
        self.shutdown_switch.setOffText("")
        self.shutdown_switch.setAccessibleName("完成后关机")
        self.shutdown_switch.setToolTip(
            "每日任务结束后执行自动关机（倒计时 "
            f"{SHUTDOWN_DELAY_SECONDS} 秒，期间可取消）。"
            "关机前会先让模拟器自己退出，退干净再关。"
            "主动执行「安全停止」时不触发。"
        )
        self.shutdown_switch.checkedChanged.connect(self._on_shutdown_toggled)
        bar.addWidget(self.shutdown_switch)
        bar.addStretch(1)
        # 排定关机之后才出现：给还在电脑前的用户一个明确的撤销入口，
        # 而不是让他去命令行记 shutdown /a。
        self.cancel_shutdown_button = PushButton("取消关机", self)
        self.cancel_shutdown_button.clicked.connect(self._on_cancel_shutdown_clicked)
        self.cancel_shutdown_button.setVisible(False)
        bar.addWidget(self.cancel_shutdown_button)
        self.export_button = PushButton(FluentIcon.SAVE, "导出诊断包", self)
        self.export_button.clicked.connect(self._on_export_clicked)
        bar.addWidget(self.export_button)
        self.stop_button = PushButton(FluentIcon.CLOSE, "安全停止", self)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        bar.addWidget(self.stop_button)
        # 只在运行中出现：从主界面回到那颗球（球会保持拖动后的位置）。
        self.floating_button = PushButton("到悬浮球", self)
        self.floating_button.clicked.connect(self._enter_floating_mode_again)
        self.floating_button.setVisible(False)
        bar.addWidget(self.floating_button)
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "开始任务", self)
        self.start_button.clicked.connect(self._on_start_clicked)
        bar.addWidget(self.start_button)
        return bar

    def _build_log_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("logView")
        self.log_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel("实时日志", page))

        # 没有结果时收起结果卡；成功完成后在此显示本轮庆祝。
        self.result_card = CardWidget(page)
        self.result_card.setBorderRadius(12)
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setContentsMargins(16, 12, 16, 12)
        result_layout.setSpacing(6)
        result_header = QHBoxLayout()
        self.result_title = StrongBodyLabel("运行结果", self.result_card)
        result_header.addWidget(self.result_title, 1)
        self.result_mascot = ArkyMascot(self.result_card, height=76)
        self.result_mascot.setFixedWidth(104)
        self.result_mascot.hide()
        result_header.addWidget(self.result_mascot)
        result_layout.addLayout(result_header)
        self.result_text = BodyLabel("", self.result_card)
        self.result_text.setWordWrap(True)
        result_layout.addWidget(self.result_text)
        self.result_card.setVisible(False)
        layout.addWidget(self.result_card)

        # 失败诊断包卡片：只在退出码 1 之后出现。两个动作是这条链路的关键 ——
        # 目标用户不一定会找目录，也不一定能写清版本与短码。
        self.report_card = CardWidget(page)
        self.report_card.setBorderRadius(12)
        report_layout = QVBoxLayout(self.report_card)
        report_layout.setContentsMargins(16, 12, 16, 12)
        report_layout.setSpacing(6)
        report_header = QHBoxLayout()
        self.report_title = StrongBodyLabel(
            "本次运行失败，诊断包已生成", self.report_card
        )
        report_header.addWidget(self.report_title, 1)
        report_close = PushButton("关闭", self.report_card)
        report_close.clicked.connect(self._hide_report_card)
        report_header.addWidget(report_close)
        report_layout.addLayout(report_header)
        self.report_text = BodyLabel("", self.report_card)
        self.report_text.setWordWrap(True)
        report_layout.addWidget(self.report_text)
        report_actions = QHBoxLayout()
        self.report_open_button = PushButton(
            FluentIcon.FOLDER, "打开所在文件夹", self.report_card
        )
        self.report_open_button.clicked.connect(self._open_report_folder)
        report_actions.addWidget(self.report_open_button)
        self.report_copy_button = PushButton("复制提交说明", self.report_card)
        self.report_copy_button.clicked.connect(self._copy_report_note)
        report_actions.addWidget(self.report_copy_button)
        report_actions.addStretch(1)
        report_layout.addLayout(report_actions)
        self.report_card.setVisible(False)
        layout.addWidget(self.report_card)

        self.log_text = TextEdit(page)
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(2000)
        layout.addWidget(self.log_text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        clear = PushButton("清空日志", page)
        clear.clicked.connect(self.log_text.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        self.addSubInterface(page, FluentIcon.DOCUMENT, "运行日志")

    def _build_tools_page(self) -> None:
        """「实用工具」：与游戏路线无关的通用小工具，第一个是连点器。

        位置就是导航栏第三项（``关于`` 在 BOTTOM，不算主功能）——
        用户 2026-11-09 要求「放最后」，即「运行日志」之后。
        """
        page = AutoClickerPage(
            clicker=self.autoclicker,
            busy_reason=self._autoclick_block_reason,
            parent=self,
        )
        page.setObjectName("toolsView")
        self.addSubInterface(page, FluentIcon.DEVELOPER_TOOLS, "实用工具")

    def _autoclick_block_reason(self) -> str | None:
        """现在能不能开连点器：不能就返回一句人话，能就返回 ``None``。

        ⚠️ 两套点击同时发会互相干扰 —— 每日任务的点击是「认画面 → 点这一个点」，
        中间被连点器抢走鼠标就会点到别的地方。宁可直接拒绝，也不要「大概能跑」。
        """
        if self.worker.running:
            return "每日任务正在运行。先停下它再开连点器，两套点击同时发会互相干扰。"
        return None

    def _build_dimension_page(self) -> None:
        """「次元探查」：内置第三方 chaos 流程，不进路线名单（见 chaos_bridge.py）。

        ⚠️ 公开候选按 NOTICE 的约束**不含** E7auto（``vendor/`` 下有
        ``NO_E7AUTO.txt`` 标记）⇒ 这一页整页不出现。**不能**保留入口再靠点击时报错：
        用户看不到入口才是「如实显示本发行版不含它」，而自检会单独记一行构成说明。
        """
        if not e7auto_bundled():
            return
        page = DimensionProbePage(
            bridge=self.dimension,
            busy_reason=self._dimension_block_reason,
            parent=self,
        )
        page.setObjectName("dimensionView")
        self.addSubInterface(page, FluentIcon.PLAY, "次元探查")

    def _dimension_block_reason(self) -> str | None:
        """两套点击会抢同一个游戏窗口，谁在跑都不许再开另一套。"""
        if self.worker.running:
            return "每日任务正在运行。先停下它再开次元探查，两套点击会互相干扰。"
        if self.autoclicker.running:
            return "连点器还开着。先到「实用工具」里停止连点，再开次元探查。"
        return None

    def _build_about_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("aboutView")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel(brand.APP_NAME, page))
        layout.addWidget(BodyLabel(brand.APP_SUBTITLE, page))
        layout.addWidget(CaptionLabel(f"版本 {PRODUCT_VERSION}", page))
        layout.addWidget(
            CaptionLabel(
                "发行版构成：含「次元探查」（E7auto）"
                if e7auto_bundled()
                else "发行版构成：不含「次元探查」（E7auto 未随包分发）",
                page,
            )
        )
        about = BodyLabel(
            "本助手用于《第七史诗》单人 PVE 内容的自动化执行。"
            "仅在确认游戏处于预期环节时执行下一步；页面无法确认、画面被遮挡或"
            "转场未完成时，保留现场并停止。\n\n"
            "默认执行干跑，实跑需显式确认。涉及付费购买与不可逆操作的路径不予执行。",
            page,
        )
        about.setWordWrap(True)
        layout.addWidget(about)
        note = BodyLabel(
            "「任务中心」按勾选顺序依次跑选中的路线；「实用工具」里是与路线无关的"
            "小工具（目前是固定点连点器）。两者不能同时开 —— 两套点击会互相干扰。",
            page,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        art_credit = CaptionLabel(
            '亚卡属于《第七史诗》。素材参考'
            '<a href="https://www.bilibili.com/video/BV1WT421e7xG/">官方周年短片</a>和'
            '<a href="https://czn.gg/event-notice-on-the-chaos-zero-nightmare-x-epic-seven-collaboration-event/">'
            '联动贴纸</a>。本助手由社区维护。',
            page,
        )
        art_credit.setWordWrap(True)
        art_credit.setOpenExternalLinks(True)
        layout.addWidget(art_credit)
        row = QHBoxLayout()
        self.consent_button = PushButton("重新查看使用须知", page)
        self.consent_button.clicked.connect(self._show_consent)
        row.addWidget(self.consent_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.addSubInterface(
            page, FluentIcon.INFO, "关于", NavigationItemPosition.BOTTOM
        )

    def _show_consent(self) -> None:
        """重看条款。**已经同意过的只是重看，不因为这次点了「暂不使用」而收回。**"""
        prompt_consent(self)

    # ── 状态同步 ────────────────────────────────────────────────────────────

    def _sync_from_controller(self) -> None:
        """把 controller 的真相一次性画回控件（阻塞信号，避免 setChecked 反向触发）。"""
        self._suspend_events = True
        try:
            selection = self.controller.selection
            for mode, box in self._route_checks.items():
                index = selection.index(mode) if mode in selection else -1
                label = route_by_name(mode).label
                box.setText(f"{_position_prefix(index)}  {label}" if index >= 0 else label)
                box.setChecked(index >= 0)
            for group, box in self._group_checks.items():
                routes = routes_in_group(group)
                box.setChecked(
                    bool(routes) and all(r.mode in selection for r in routes)
                )
            names = [route_by_name(mode).label for mode in selection]
            preview = " → ".join(names[:3])
            if len(names) > 3:
                preview += f" 等 {len(names)} 项"
            self.selection_summary.setText(f"执行顺序 · {preview}" if preview else "")
            self.selection_summary.setVisible(bool(preview))
            for mode, spin in self._route_spins.items():
                spin.setValue(self.controller.cycles[mode])
            backend = self.controller.selected_backend
            target = self.backend_combo.findData(backend)
            if target >= 0:
                self.backend_combo.setCurrentIndex(target)
            self.background_switch.setChecked(
                self.controller.pc_input_mode == PC_INPUT_BACKGROUND
            )
            self.background_switch.setEnabled(backend == "pc")
            self.hint_label.setText(STARTUP_HINTS.get(backend, ""))
            if self._detail_mode is not None:
                self._update_pc_note(self._detail_mode)
            self._refresh_actions()
        finally:
            self._suspend_events = False

    def _refresh_actions(self) -> None:
        running = self.worker.running
        self.start_button.setEnabled(
            self.controller.can_start
            and self.controller.ready
            and not self._checking
            and self.consented
        )
        self.stop_button.setEnabled(running)
        self.floating_button.setVisible(running)
        self.check_button.setEnabled(not running and not self._checking)
        self.backend_combo.setEnabled(not running)
        self.background_switch.setEnabled(
            not running and self.controller.selected_backend == "pc"
        )
        # 运行期间锁定本次选择与次数。
        self.shutdown_switch.setEnabled(not running)
        for box in self._route_checks.values():
            box.setEnabled(not running)
        for mode, spin in self._route_spins.items():
            spin.setEnabled(not running and route_by_name(mode).cycles_editable)
        for button in self._route_option_buttons.values():
            button.setEnabled(not running)
        self.run_state_label.setText(
            "进行中" if running else
            f"已选 {len(self.controller.selection)} 项 · "
            "按勾选顺序执行"
        )

    # ── 使用须知 / 版本检查 ─────────────────────────────────────────────────

    def _ensure_consent(self) -> None:
        """首次启动（或条款改版后）确认一次使用须知。

        拒绝不弹第二个窗、不拦着关窗口，只在日志里说明「开始任务」为什么点不动 ——
        它本来就该由**按钮状态**表达，而不是一串弹窗。
        """
        if self.consented:
            return
        if not prompt_consent(self):
            self._append_log(
                "尚未确认使用须知，「开始任务」保持禁用。"
                "如需重新阅读，可在「关于」页执行「重新查看使用须知」。"
            )
            return
        self.consented = True
        if not record_consent(self.data_root):
            # 落盘失败**照样放行**：用户刚刚确实点了同意，写不进去是这个目录的问题。
            self._append_log(
                f"确认记录未保存（{self.data_root} 不可写）；下次启动时将再次显示使用须知。"
            )
        self._refresh_actions()

    def _start_update_check(self) -> None:
        """后台问一次有没有新版。**查不到什么都不做** —— 不报错、不弹窗。"""

        def job() -> None:
            try:
                info = check_for_update(PRODUCT_VERSION, self.data_root)
            except Exception:  # noqa: BLE001 —— 版本检查失败不该影响任何别的事
                info = None
            self._bridge.update_done.emit(info)

        threading.Thread(
            target=job, name="epic7-qt-update-check", daemon=True
        ).start()

    def _on_update_done(self, info: object) -> None:
        """有新版就在状态卡留一行；没有就什么都不做（那一行本来就是收起的）。"""
        if info is None:
            return
        self._update_info = info
        self.update_label.setText(
            f'发现新版本 {info.latest}（当前 {info.current}），'
            f'<a href="{info.url}">查看更新说明</a>'
        )
        self.update_label.setVisible(True)
        self._append_log(f"发现新版本 {info.latest}（当前 {info.current}）：{info.url}")

    # ── 用户操作 ────────────────────────────────────────────────────────────

    def _on_route_toggled(self, mode: str, checked: bool) -> None:
        if self._suspend_events:
            return
        try:
            self.controller.toggle(mode, checked)
        except Exception as error:
            self._notify("error", "无法修改任务", str(error))
        self._sync_from_controller()
        self._save_session()

    def _on_group_toggled(self, group: str, checked: bool) -> None:
        if self._suspend_events:
            return
        try:
            if checked:
                self.controller.select_group(group)
            else:
                self.controller.clear_group(group)
        except Exception as error:
            self._notify("error", "无法勾选整组", str(error))
        self._show_group_detail(group)
        self._sync_from_controller()
        self._save_session()

    def _on_cycles_changed(self, mode: str, value: int) -> None:
        if self._suspend_events:
            return
        try:
            self.controller.set_cycles(mode, value)
        except Exception as error:
            self._notify("error", "运行次数无效", str(error))
            self._sync_from_controller()
            return
        self._save_session()

    def _on_route_options_clicked(self, mode: str) -> None:
        """打开单条路线的设置；保存时由 controller 清洗并写入会话存档。"""

        def save(target: str, values: dict[str, object]) -> None:
            try:
                self.controller.set_options(target, values)
            except Exception as error:
                self._notify("error", "无法保存设置", str(error))
                return
            self._save_session()

        RouteOptionsDialog(
            self,
            mode,
            route_by_name(mode).label,
            self.controller.options[mode],
            save,
        ).exec()

    def _on_backend_changed(self, index: int) -> None:
        if self._suspend_events or index < 0:
            return
        backend = self.backend_combo.itemData(index)
        try:
            self.controller.select_backend(backend)
        except Exception as error:
            self._notify("error", "无法切换运行环境", str(error))
            self._sync_from_controller()
            return
        self.status_label.setText("尚未执行环境检测。")
        self._append_log(f"运行环境已切换为 {BACKEND_LABELS.get(backend, backend)}。")
        self._sync_from_controller()
        self._save_session()

    def _on_background_changed(self, checked: bool) -> None:
        if self._suspend_events:
            return
        mode = PC_INPUT_BACKGROUND if checked else PC_INPUT_FOREGROUND
        try:
            self.controller.select_pc_input_mode(mode)
        except Exception as error:
            self._notify("error", "无法切换前台占用模式", str(error))
            self._sync_from_controller()
            return
        if checked:
            self._append_log(
                "前台占用=不占用：常规点击不切换窗口；涉及滑动或返回键的环节"
                "临时切换窗口，完成后还原。"
            )
        else:
            self._append_log("前台占用=占用：全部操作在前台执行。")
        self._sync_from_controller()
        self._save_session()

    def _on_check_clicked(self) -> None:
        if self._checking or self.worker.running:
            return
        self._checking = True
        self.status_label.setText("正在执行环境检测……")
        self._refresh_actions()
        backend = self.controller.selected_backend

        def job() -> None:
            try:
                result: object = run_preflight(window_backend=backend)
            except Exception as error:  # noqa: BLE001 —— 报进界面，不让线程静默死掉
                result = error
            self._bridge.check_done.emit(result)

        threading.Thread(target=job, name="epic7-qt-preflight", daemon=True).start()

    def _on_check_done(self, result: object) -> None:
        self._checking = False
        if isinstance(result, Exception):
            self.status_label.setText(f"环境检测失败：{result}")
            self._notify("error", "环境检测失败", str(result))
            self._refresh_actions()
            return
        self.controller.apply_preflight(result)
        self.status_label.setText(result.message)
        self._append_log(f"环境检测：{result.message}")
        if result.warning:
            self._notify("warning", "可执行，但输入通道可能无效", result.warning)
        else:
            self._notify("success", "检测通过", result.message)
        self._refresh_actions()

    def _on_start_clicked(self) -> None:
        # 正在请模拟器退出：这时开跑会跟它抢，而且模拟器马上就要没了。
        # 拦在这里、并且**不撤销**等待流程，让它按自己的节奏收尾。
        if (
            self._shutdown_wait_timer is not None
            and self._shutdown_wait_timer.isActive()
        ):
            self._append_log("正在关闭模拟器，等它退出后再开始新任务。")
            self._notify(
                "warning",
                "正在关闭模拟器",
                "等模拟器退出后再开始新任务，否则两边会互相干扰。",
            )
            return
        # 人已经在点「开始任务」了 ⇒ 先把上一轮排定的关机撤掉，否则跑到一半电脑会关。
        # 放在最前面：后面任何一步不通过（没勾路线、复检失败）也照样撤销 ——
        # 只要有人坐在这儿操作，就不该倒计时关机。跑完仍按开关重新排定。
        self._cancel_shutdown()
        if self.dimension.running:
            self._notify(
                "warning",
                "次元探查正在运行",
                "先到「次元探查」页停止它，再开始任务 —— 两个程序会抢同一个游戏窗口。",
            )
            return
        if self.autoclicker.running:
            self._notify(
                "warning",
                "连点器正在运行",
                "先到「实用工具」里停止连点，再开始任务 —— 两套点击同时发会互相干扰。",
            )
            return
        if not self.consented:
            # 按钮本来就该是灰的（见 _refresh_actions）。走到这里只可能是
            # 事件顺序异常，仍然守住这条线。
            self._notify("warning", "使用须知", "需先阅读并同意《使用须知》后方可执行。")
            return
        if not self.controller.can_start:
            self._notify("warning", "尚未执行环境检测", "需先执行环境检测。")
            return
        plan = self.controller.plan()
        if not plan:
            self._notify("warning", "未选择路线", "至少选择一项后方可执行。")
            return
        self._checking = True
        self.status_label.setText("正在复检运行环境……")
        self._refresh_actions()
        backend = self.controller.selected_backend
        # 复检与实跑必须看同一套图（见 preflight.template_root_for_backend）：
        # 普通 Path 会让只有 PC 素材的成就领取被误判成缺图。
        template_root = template_root_for_backend(self.template_root, backend)

        def job() -> None:
            report = None
            error = None
            try:
                report = run_preflight(window_backend=backend)
                if report.can_start:
                    # 只验真正要跑的路线；被后端筛掉的不许挡住其余勾选。
                    validate_start_plan(self.controller, template_root)
            except Exception as caught:  # noqa: BLE001
                error = caught
            self._bridge.start_done.emit(report, error)

        threading.Thread(target=job, name="epic7-qt-start-check", daemon=True).start()

    def _on_start_done(self, report: object, error: object) -> None:
        self._checking = False
        if error is not None:
            self.status_label.setText(f"环境复检失败：{error}")
            self._notify("error", "无法开始执行", str(error))
            self._refresh_actions()
            return
        self.controller.apply_preflight(report)
        if not report.can_start:
            self.status_label.setText(report.message)
            self._notify("error", "环境不允许实跑", report.message)
            self._refresh_actions()
            return
        try:
            self.controller.start()
        except Exception as caught:
            self._notify("error", "无法启动", str(caught))
        else:
            runnable, _skipped = self.controller.resolve_plan()
            modes = "、".join(route_by_name(mode).label for mode, _ in runnable)
            self._append_log(f"已启动：{modes}")
            self._enter_floating_mode(
                tuple((mode, route_by_name(mode).label) for mode, _ in runnable)
            )
        self._refresh_actions()

    def _enter_floating_mode(self, routes: tuple[tuple[str, str], ...]) -> None:
        """开始成功后：主窗口收起，**先展开便签面板**（能看进度和日志）；
        点面板上的「收起」才变成右上角那颗球。

        ⚠️ 顺序不能倒：`start_run` 只负责把球摆好、把面板清空，真正的显示交给
        `expand()`。先 `hide()` 主窗口再展开，避免两个窗口同框闪一下。
        """
        self.switchTo(self.log_page)
        self.floating.start_run(routes)
        self.hide()
        self.floating.expand()

    def _return_to_main_window(self) -> None:
        """点面板「主界面」：只收面板，球留在原地，随时能再点回来。"""
        self.floating.collapse()
        self.switchTo(self.log_page)
        self.showNormal()

    def _enter_floating_mode_again(self) -> None:
        """主界面点「到悬浮球」：主窗口再收起，球保持原来的位置。"""
        self.switchTo(self.log_page)
        self.floating.show_ball()
        self.hide()

    def _save_todos(self, todos: object) -> None:
        """便签改了就落盘；存档读坏时按 session 的规矩回落到默认值。"""
        previous = session.load(self._session_path) or session.SessionState()
        session.save(
            self._session_path,
            replace(previous, todos=session.clean_todos(todos)),
        )

    def _save_ball_pos(self, pos: object) -> None:
        """拖动结束后记住球的落点，下次打开还在同一个地方。"""
        if not (isinstance(pos, tuple) and len(pos) == 2):
            return
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError):
            return
        previous = session.load(self._session_path) or session.SessionState()
        session.save(self._session_path, replace(previous, ball_pos={"x": x, "y": y}))

    def _on_stop_clicked(self) -> None:
        if self.worker.running:
            # 「我让它停的」⇒ 结束后不自动关机（见 _maybe_schedule_shutdown）。
            self._stop_requested_by_user = True
        self.controller.stop()
        self._append_log("已发出安全停止请求。")
        self._start_stop_watchdog()

    def _start_stop_watchdog(self) -> None:
        """停止请求之后再加一道兜底：宽限期内不退就强行结束。

        为什么必须有（2026-09-28 实机取证）：停止是「在两次动作**之间**查一次信号
        文件」，而工作进程有可能**卡在一次底层调用的内部**（等一次点击的回执）——
        卡在里面就永远轮不到下一次检查，信号写了也白写。只写信号、只把按钮变灰，
        界面就只能一直等下去。

        ⚠️ 用 QTimer 而不是后台线程：这是纯计时 + 一次 force_stop，主线程足够，
        也省掉「跨线程收界面状态」那一步。
        """
        self._stop_deadline = time.monotonic() + STOP_GRACE_MS / 1000
        if self._stop_timer is None:
            self._stop_timer = QTimer(self)
            self._stop_timer.timeout.connect(self._watch_stop)
        self._stop_timer.start(STOP_POLL_MS)

    def _watch_stop(self) -> None:
        if self._stop_timer is not None and not self.worker.running:
            self._stop_timer.stop()
            return
        if time.monotonic() < self._stop_deadline:
            return
        if self._stop_timer is not None:
            self._stop_timer.stop()
        seconds = STOP_GRACE_MS / 1000
        if self.worker.force_stop():
            self._append_log(
                f"等待 {seconds:.0f} 秒仍无响应，已强制结束本次运行。"
                "本次未执行收尾回大厅流程，游戏可能停留在中途；"
                "重新执行前需确认模拟器运行状态。"
            )
        else:
            self._append_log(
                f"等待 {seconds:.0f} 秒仍无响应且无法结束本次运行；"
                "需在任务管理器中手动结束助手进程。"
            )
        # 强行结束时读输出的线程可能还卡在那条阻塞的管道上（``事件=结束`` 不会来），
        # 所以这里必须自己把按钮状态收回来，不能等 finished 事件。
        self._refresh_actions()

    def _show_report_card(self, path: str) -> None:
        """失败后展示诊断包。只陈述事实与提交条件。"""

        self._report_path = Path(path)
        code = short_code_of(self._report_path)
        self.report_text.setText(
            f"短码 {code}。提交时需附上压缩包，并说明失败前的操作与"
            "界面最后显示的内容。"
        )
        self.report_card.setVisible(True)
        self._append_log(f"诊断包已生成：{path}")

    def _hide_report_card(self) -> None:
        self.report_card.setVisible(False)
        self._report_path = None

    def _open_report_folder(self) -> None:
        if self._report_path is None:
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._report_path.parent))
        )

    def _copy_report_note(self) -> None:
        path = self._report_path
        if path is None:
            return
        QApplication.clipboard().setText(
            "\n".join(
                (
                    f"诊断包：{path.name}",
                    f"短码：{short_code_of(path)}",
                    f"版本：{PRODUCT_VERSION}",
                    "现象：",
                )
            )
        )
        self._notify("success", "提交说明已复制", "含包名、短码与版本。")

    def _on_export_clicked(self) -> None:
        selection = self.controller.selection
        if not selection:
            self._notify("warning", "无可导出的路线", "需先选择一项路线。")
            return
        try:
            path = export_diagnostics(
                selection[0],
                root=self.data_root,
                output_dir=self.data_root / "diagnostics",
            )
        except Exception as error:
            self._notify("error", "导出失败", str(error))
            return
        self._append_log(f"诊断包已导出：{path}")
        self._notify("success", "诊断包已导出", str(path))

    # ── 说明区 / 日志 / 会话 ────────────────────────────────────────────────

    def _show_group_detail(self, group: str) -> None:
        self._detail_mode = None
        self.detail_title.setText(f"{group} · 整组说明")
        self.detail_body.setText(group_description(group))
        self._update_pc_note()

    def _show_route_detail(self, mode: str) -> None:
        route = route_by_name(mode)
        # 记下当前在看哪一条：切换窗口后端时要重算标题下面那行「能不能跑」，
        # 否则会把上一个后端的结论留在屏幕上（切换后不点别的路线就会看到假提示）。
        self._detail_mode = mode
        self.detail_title.setText(route.label)
        self.detail_body.setText(route.description)
        self._update_pc_note(mode)

    def _update_pc_note(self, mode: str | None = None) -> None:
        """路线标题下面那行「这条能不能在当前后端跑」。

        ⚠️ 2026-11-13 起由 ``catalog.unavailable_note()`` 按名单算，**不再写死
        在任何一条路线的说明里** —— 写死的那些句子在 PC 放行新路线后必然过期，
        用户照说明勾上、跑起来才发现被跳过。这里只负责显示。
        """
        backend = self.controller.selected_backend
        note = unavailable_note(mode, backend) if mode is not None else ""
        if note:
            self.pc_note.setText(note)
        elif backend == "pc":
            self.pc_note.setText("PC 客户端：运行计划仅包含已通过验收的路线。")
        else:
            self.pc_note.setText("")
        self.pc_note.setVisible(bool(self.pc_note.text()))

    def _append_log(self, line: str) -> None:
        # 行数上限由 QTextDocument.setMaximumBlockCount(2000) 兜住，这里只管追加。
        self.log_text.append(line)

    def _poll_worker(self) -> None:
        for event in self.worker.drain_events():
            if event.kind == "log":
                self._append_log(event.message)
                self.floating.note_line(event.message)
            elif event.kind == "started":
                # 新一轮开跑：先把上一次的结果收起来，免得两轮结论叠在一起。
                self.result_card.setVisible(False)
                self._hide_report_card()
                # 上一轮的「手动停止」标记不带到这一轮来。
                self._stop_requested_by_user = False
                self._append_log("自动化已启动。")
            elif event.kind == "report":
                self._show_report_card(event.message)
            elif event.kind == "stopping":
                self._append_log("正在安全停止……")
                self.floating.stop_requested()
            elif event.kind == "finished":
                self._append_log(f"运行结束（退出码 {event.exit_code}）。")
                exit_code = 130 if self._stop_requested_by_user else event.exit_code
                self.floating.finish(exit_code)
                self._save_last_run(event.exit_code)
                show_completion = exit_code == 0 and self.result_card.isVisibleTo(self.log_page)
                self.result_mascot.setVisible(show_completion)
                if show_completion:
                    self.result_mascot.set_phase("complete")
                # 跑完就不留球了：收干净，主窗口回到日志页。
                self.floating.hide_all()
                self.switchTo(self.log_page)
                self.showNormal()
                self._maybe_schedule_shutdown(event.exit_code)
        running = self.worker.running
        if running != self._last_running:
            self._last_running = running
            self._refresh_actions()

    def _save_session(self) -> None:
        previous = session.load(self._session_path) or session.SessionState()
        session.save(
            self._session_path,
            replace(
                previous,
                selection=tuple(self.controller.selection),
                cycles=dict(self.controller.cycles),
                backend=self.controller.selected_backend,
                pc_input_mode=self.controller.pc_input_mode,
                params={
                    mode: dict(values)
                    for mode, values in self.controller.options.items()
                },
            ),
        )

    def _save_last_run(self, exit_code: int | None) -> None:
        from datetime import datetime

        previous = session.load(self._session_path) or session.SessionState()
        summary, detail_lines = extract_run_result(self.worker.recent_output)
        if summary is None:
            return
        details = "\n".join(detail_lines)
        at = datetime.now().strftime("%Y-%m-%d %H:%M")
        session.save(
            self._session_path,
            replace(
                previous,
                last_run=session.LastRun(
                    at=at,
                    summary=summary,
                    exit_code=exit_code,
                    details=details,
                ),
            ),
        )
        self._show_run_result(at, summary, details)

    def _show_run_result(self, at: str, summary: str, details: str) -> None:
        """有逐条明细就用明细，没有就回落成摘要。"""
        text = details.strip() or summary.strip()
        if not text:
            return
        self.result_title.setText(f"运行结果 · {at}" if at else "运行结果")
        self.result_text.setText(text)
        self.result_card.setVisible(True)

    # ── 跑完自动关机 ────────────────────────────────────────────────────────

    def _on_shutdown_toggled(self, checked: bool) -> None:
        if self._suspend_events:
            return
        if checked:
            self._append_log(
                f"已启用「跑完自动关机」：本次任务结束后 {SHUTDOWN_DELAY_SECONDS} 秒"
                "执行关机，期间可通过「取消关机」撤销。"
            )
            return
        self._append_log("已关闭「跑完自动关机」。")
        # 跑完之后回来把开关关掉：顺手撤销已经排定的关机，别让它偷偷关。
        self._cancel_shutdown()

    def _maybe_schedule_shutdown(self, exit_code: int | None) -> None:
        """这一轮跑完了，按开关决定要不要关机。

        只有**用户没插手**的结束才排定（2026-11-12 用户拍板）：
        正常完成、某条路线失败、资源耗尽都算「跑完了」—— 夜里挂着没有任何收益，
        第二天打开助手就能在「运行结果」卡里看到跑到哪、错在哪；
        但自己点过「安全停止」的不算，那说明人就在电脑前。
        """
        if not self.shutdown_switch.isChecked():
            return
        if exit_code == 130 or self._stop_requested_by_user:
            self._append_log("本次为手动停止，不执行自动关机。")
            return
        # 2026-11-14 事故：模拟器还开着就关机，它被强行结束后驱动状态留在半截，
        # 次日开机 Windows 进「启动修复」。所以先请它自己退出，退干净再关。
        action = self.emulator_quit.begin()
        if action == "waiting":
            self._append_log("关机前等待模拟器自行退出，退出后进入关机倒计时。")
            self._start_shutdown_wait_timer()
            return
        if action == "quit_failed":
            self._append_log(
                "未能请求模拟器退出（未找到模拟器或退出指令执行失败），按原流程关机。"
            )
        self._schedule_shutdown_now()

    def _schedule_shutdown_now(self) -> None:
        """模拟器已退（或本来就没开）：排定关机并开始倒计时。"""
        if not self.shutdown.schedule():
            self._append_log("自动关机未排定（关机命令执行失败），设备保持开机。")
            return
        self.cancel_shutdown_button.setVisible(True)
        self._start_shutdown_timer()
        self._append_log(
            f"每日任务已结束，{SHUTDOWN_DELAY_SECONDS} 秒后执行自动关机；"
            "期间可通过「取消关机」撤销。"
        )
        self._notify(
            "warning",
            "任务已结束",
            f"{SHUTDOWN_DELAY_SECONDS} 秒后执行自动关机。"
            "如需取消，可使用「取消关机」。",
        )

    def _start_shutdown_wait_timer(self) -> None:
        if self._shutdown_wait_timer is None:
            self._shutdown_wait_timer = QTimer(self)
            self._shutdown_wait_timer.setInterval(1000)
            self._shutdown_wait_timer.timeout.connect(self._on_shutdown_wait_tick)
        self._shutdown_wait_timer.start()

    def _on_shutdown_wait_tick(self) -> None:
        state = self.emulator_quit.poll()
        if state == "waiting":
            return
        assert self._shutdown_wait_timer is not None
        self._shutdown_wait_timer.stop()
        if state == "timeout":
            self._append_log(
                f"模拟器 {int(self.emulator_quit.timeout_seconds)} 秒内未退出，"
                "仍按原流程关机 —— 本次可能不干净；"
                "下次开机若进入修复界面，按 Enter 选择继续启动即可。"
            )
        else:
            self._append_log("模拟器已退出。")
        self._schedule_shutdown_now()

    def _start_shutdown_timer(self) -> None:
        if self._shutdown_timer is None:
            self._shutdown_timer = QTimer(self)
            self._shutdown_timer.setSingleShot(True)
            self._shutdown_timer.timeout.connect(self._on_shutdown_deadline)
        self._shutdown_timer.start(SHUTDOWN_DELAY_SECONDS * 1000)

    def _on_shutdown_deadline(self) -> None:
        """到点了：电脑马上要关，按钮留着只会让人误会还来得及。"""
        self.shutdown.scheduled = False
        self.cancel_shutdown_button.setVisible(False)

    def _on_cancel_shutdown_clicked(self) -> None:
        if self._cancel_shutdown():
            self._notify("success", "自动关机已取消", "设备保持开机。")
        else:
            self._notify("error", "取消自动关机失败", "需手动撤销已排定的关机。")

    def _cancel_shutdown(self) -> bool:
        """撤销排定的关机；返回「现在确实没有待执行的关机」。

        没排定过就什么都不做（不执行 ``shutdown /a``），返回 ``True``。
        """
        if self._shutdown_timer is not None:
            self._shutdown_timer.stop()
        # 还在等模拟器退出时也要能叫停：停掉轮询就不会再排定关机。
        # 但已经发出去的 quitall 收不回来 —— 模拟器仍会关，日志要说清楚。
        if self._shutdown_wait_timer is not None:
            if self._shutdown_wait_timer.isActive():
                self._append_log("已停止等待关机；已经发出的模拟器关闭请求收不回来。")
            self._shutdown_wait_timer.stop()
        self.cancel_shutdown_button.setVisible(False)
        if not self.shutdown.scheduled:
            return True
        if self.shutdown.cancel():
            self._append_log("已取消自动关机，设备保持开机。")
            return True
        self._append_log("取消自动关机未成功；需手动执行 shutdown /a。")
        return False

    def _initial_size(self) -> tuple[int, int]:
        """首屏尺寸：可用屏幕的一半左右，用户自己再拖大。

        写死 1180x800 在 1080p 上是「挺大」、在 4K 上又太小，所以按比例算。
        下限保住路线清单 + 说明卡不挤，上限避免 4K 上一开就半面墙。
        """
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None or available.isEmpty():
            return 1180, 800
        width = min(max(int(available.width() * 0.5), 880), 1280)
        height = min(max(int(available.height() * 0.6), 600), 900)
        return min(width, available.width()), min(height, available.height())

    def _restore_geometry(self, previous: session.SessionState | None) -> None:
        if previous is None or previous.window is None:
            return
        window = previous.window
        try:
            x, y = int(window["x"]), int(window["y"])
            w, h = int(window["w"]), int(window["h"])
        except (KeyError, TypeError, ValueError):
            return
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            # 会话文件是跨版本共用的，以前那套界面存下来的可能是最大化 /
            # 接近全屏的几何，直接继承就会「一打开非常大」。超过可用区 85%
            # 一律不认，回退到上面按屏幕比例算的首屏尺寸。
            if w > available.width() * 0.85 or h > available.height() * 0.85:
                return
            # 换显示器 / 拔副屏后坐标可能落在屏幕外，夹回可见范围。
            x = max(available.left(), min(x, available.right() - w))
            y = max(available.top(), min(y, available.bottom() - h))
        self.move(x, y)
        self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))

    def _notify(self, kind: str, title: str, content: str) -> None:
        """InfoBar 的版本间签名有差异；挂了就退回日志，绝不让提示把界面弄崩。"""
        try:
            getattr(InfoBar, kind)(
                title=title,
                content=content,
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP,
            )
        except Exception:
            self._append_log(f"[{kind}] {title}：{content}")

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 的回调名
        # 关窗口必须先把连点线程停掉：它是 daemon，进程退出时也会消失，
        # 但「点完 Close 到进程真正退出」之间还有几百毫秒，这期间鼠标不该还在点。
        self.autoclicker.stop()
        if self.dimension.running:
            # 次元探查就在本进程里：关窗口会直接把它的线程带走，游戏停在半路。
            self._notify(
                "warning",
                "次元探查正在运行",
                "先到「次元探查」页点停止，再关闭窗口。",
            )
            event.ignore()
            return
        if self.worker.running:
            # 任务还在跑：关窗口不能顺手把任务带走，收成球留在桌面上。
            event.ignore()
            self._append_log("窗口已收至悬浮球，任务继续运行；退出前需先执行「安全停止」。")
            self._enter_floating_mode_again()
            return
        # 悬浮球 / 窄条是独立窗口，主窗口关了它们不会自动消失。
        self.floating.hide_all()
        self._save_session()
        geometry = self.geometry()
        previous = session.load(self._session_path) or session.SessionState()
        session.save(
            self._session_path,
            replace(
                previous,
                window={
                    "x": geometry.x(),
                    "y": geometry.y(),
                    "w": geometry.width(),
                    "h": geometry.height(),
                },
            ),
        )
        super().closeEvent(event)


def _apply_cjk_font(app: QApplication) -> None:
    """显式挑一个**这台机器上真有**的中文字体。

    qfluentwidgets 的默认字体族写着「Microsoft YaHei UI」，在精简环境、部分
    Linux/容器以及 Qt 的 offscreen 平台里并不存在 —— 那时中文全渲染成方块，
    而界面代码一点错都没有。宁可退到 Noto / 宋体，也不要方块。
    """
    families = set(QFontDatabase.families())
    for name in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "SimHei",
        "SimSun",
    ):
        if name in families:
            app.setFont(QFont(name, 10))
            return


def configure_qt() -> None:
    """必须在 QApplication 实例化**之前**调用（参考项目同位置）。"""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def apply_theme(app: QApplication) -> None:
    """设置亚卡的品牌色，保留 Fluent 的浅色控件样式和原生控件调色板。"""
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    app.setApplicationDisplayName(brand.APP_NAME)
    app.setWindowIcon(brand.app_icon())
    _apply_cjk_font(app)
    setTheme(Theme.LIGHT)
    try:
        setThemeColor(brand.BLUE)
    except Exception:
        pass


def main() -> int:
    configure_qt()
    app = QApplication(sys.argv)
    apply_theme(app)
    worker = WorkerController(repo_parent=REPO_PARENT, data_root=DATA_ROOT)
    controller = DesktopController(worker=worker)
    window = QtDesktopWindow(
        controller=controller,
        worker=worker,
        data_root=DATA_ROOT,
        template_root=TEMPLATE_ROOT,
    )
    window.show()
    return app.exec()
