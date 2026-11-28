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

已对齐：四分组勾选（含全选与活动互斥）、序号即执行顺序、次数输入与只读路线、
后端切换、PC 默认后台点击、环境检测、开始前复检（含逐条模板校验）、
安全停止（含 30 秒强杀兜底）、实时日志轮询、会话存档、窗口几何记忆、诊断包导出、
首次使用须知、版本检查、实用工具（连点器）。

刻意**不做**「多套命名配置」（日常 / 活动 / 周末那套保存与切换）：2026-11-09 用户
明确说不需要。勾选与次数已经按会话存档自动记住上次，日常真正用得上的就是那条。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    SubtitleLabel,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    StrongBodyLabel,
    SwitchButton,
    TitleLabel,
    setTheme,
    setThemeColor,
    Theme,
)

from auto_game_unified.core.autoclicker import AutoClicker
from auto_game_unified.core.data_paths import data_root
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
from auto_game_unified.desktop.run_progress import (
    OUTCOME_LABELS,
    elapsed_of,
    extract_run_result,
    parse_result_details,
)
from auto_game_unified.desktop.shutdown import (
    SHUTDOWN_DELAY_SECONDS,
    ShutdownScheduler,
)
from auto_game_unified.desktop.update_check import check_for_update
from auto_game_unified.desktop.worker import WorkerController
from auto_game_unified.desktop_qt import brand
from auto_game_unified.desktop_qt.mascot import ArkyAnimation, ArkyMascot
from auto_game_unified.desktop_qt.route_options_dialog import RouteOptionsDialog
from auto_game_unified.games.epic7.route_options import options_for
from auto_game_unified.desktop_qt.autoclicker import AutoClickerPage
from auto_game_unified.desktop_qt.floating import FloatingRunner
from auto_game_unified.desktop_qt.onboarding import prompt_consent
from auto_game_unified.desktop_qt.style import (
    HEADING,
    PixelBackground,
    PixelCheckBox as CheckBox,
    PixelComboBox as ComboBox,
    PixelPanel,
    apply_pixel_style,
)

ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = ROOT.parent
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
DATA_ROOT = data_root()

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


def _icon_label(name: str, parent: QWidget, size: int = 22) -> QLabel:
    label = QLabel(parent)
    label.setPixmap(brand.icon_pixmap(name, size, device_pixel_ratio=label.devicePixelRatioF()))
    return label


def _panel_title(text: str, parent: QWidget) -> StrongBodyLabel:
    label = StrongBodyLabel(text, parent)
    label.setStyleSheet(f"color: {HEADING};")
    return label


# ── 运行日志页：结论带与结果行的配色 ────────────────────────────────────────
# 与 ``style.py`` 的调色板同源，只是这里要按状态取色，写成表比散落在各处的
# ``setStyleSheet`` 更好核对。
_TONE_COLORS = {
    "success": "#8edb89",
    "warning": "#f3c86d",
    "danger": "#f4aaa4",
    "info": "#a7c4e2",
    "muted": "#8ea2bb",
}
_TONE_ICONS = {
    "success": "check",
    "warning": "warning",
    "danger": "error",
    "info": "running",
    "muted": "pending",
}
# 运行进度里的状态名 → 结果卡用的词。**只保留一套词**：与 ``每日任务结果：``
# 那几行里的状态词一致（完成 / 无剩余内容 / 失败 / 未执行），另外补上只有界面
# 才有的四种（待确认 / 已停止 / 进行中 / 待执行）。
_ROW_WORDS = {
    "success": "完成",
    "resource_exhausted": "无剩余内容",
    "failure": "失败",
    "skipped": "未执行",
    "awaiting_confirmation": "待确认",
    "stopped": "已停止",
    "running": "进行中",
    "pending": "待执行",
}
# 颜色跟**最终显示的那个词**走，不跟进度状态走：两者一旦分开算，就会出现
# 「词写着失败、行是灰的」（2026-11-28 实测：进度漏了某条时，明细说失败，
# 行色却按 pending 上灰）。词与色同源，就没有这种错位。
_WORD_TONES = {
    "完成": "success",
    "无剩余内容": "success",
    "失败": "danger",
    "未执行": "warning",
    "当前环境不支持": "warning",
    "待确认": "warning",
    "已停止": "warning",
    "进行中": "info",
    "待执行": "muted",
}
# 统计行按这个顺序排；顺序固定，用户每次扫一眼都在同一列。
# 失败排在最前：出问题的那一轮，读者要先看到红色那个数。
_STAT_ORDER = ("失败", "已停止", "待确认", "未执行", "完成", "无剩余内容", "进行中", "待执行")
_VERDICT_COLORS = {
    "success": "#8edb89",
    "failure": "#f4aaa4",
    "resource_exhausted": "#8edb89",
    "stopped": "#f3c86d",
    "awaiting_confirmation": "#f3c86d",
    "skipped": "#f3c86d",
}


@dataclass(frozen=True)
class _ResultRow:
    """结果卡里的一行。两种来源（运行进度 / 存档明细）都先变成它再渲染。"""

    index: int
    label: str
    status: str
    tone: str
    meta: str = ""
    note: str = ""
    reason: str = ""
    text: str = ""
    mode: str = ""

    @property
    def detail_text(self) -> str:
        """第二行只放**一句**：原因 > 提醒 > 说明。三句一起摆会折行并被裁。"""
        return self.reason or self.note or self.text

    @property
    def full_text(self) -> str:
        return "；".join(part for part in (self.text, self.note, self.reason) if part)


def _metrics_html(rows: tuple[_ResultRow, ...]) -> str:
    """一行把话说全：各状态条数相加必须等于本轮项数。"""
    if not rows:
        return ""
    parts = []
    for word in _STAT_ORDER:
        count = sum(row.status == word for row in rows)
        if not count:
            continue
        tone = next(row.tone for row in rows if row.status == word)
        parts.append(f"{word} <b style='color:{_TONE_COLORS[tone]}'>{count}</b>")
    return "　　".join(parts)


class _Bridge(QObject):
    """后台线程 → 主线程的唯一通道（PySide6 跨线程 emit 自动走 queued connection）。"""

    check_done = Signal(object)          # PreflightReport 或 Exception
    start_done = Signal(object, object)  # (PreflightReport 或 None, Exception 或 None)
    update_done = Signal(object)         # UpdateInfo 或 None


class _RouteTitle(QPushButton):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; padding: 0; }"
            "QPushButton:focus { border-color: #f2c76d; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        self.caption = QLabel(self)
        font = self.caption.font()
        font.setPixelSize(13)
        font.setBold(True)
        self.caption.setFont(font)
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setStyleSheet("QLabel { color: #f1f5ff; background: transparent; }")
        self.caption.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.caption)
        self.set_label(text)

    def set_label(self, text: str) -> None:
        self.caption.setText(text)
        self.setAccessibleName(text)


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
        self._route_option_buttons: dict[str, QPushButton] = {}
        self._route_tiles: dict[str, PixelPanel] = {}
        self._route_tile_controls: dict[str, tuple[QLabel, _RouteTitle, QLabel]] = {}
        self._route_counts: dict[str, QWidget] = {}
        self._route_params: dict[str, QWidget] = {}
        self._route_setting_cells: dict[str, QWidget] = {}
        self._route_grids: dict[str, QGridLayout] = {}
        self._list_heads: list[QWidget] = []
        self._list_view = True
        self._route_columns = 3
        self._shown_rows: tuple[_ResultRow, ...] = ()
        # 最近一轮的逐条明细（``ResultLine``）：行渲染与首屏还原都从这里取。
        self._detail_rows: tuple = ()
        self._detail_by_label: dict[str, object] = {}
        # 日志卡的展开状态与高度上下限（上下限由窗口高度决定，见 _apply_compact_layout）。
        self._log_expanded = True
        self._log_min_height = 250
        self._log_max_height = 285
        # 说明卡当前显示的是哪条路线（None = 显示的是分组说明）。
        # 切窗口后端时要靠它重算标题下面那行「这条能不能跑」。
        self._detail_mode: str | None = None
        self._detail_group: str | None = None
        self._suspend_events = False
        self._checking = False
        self._closing = False
        self._last_running = False
        # 「使用须知」确认状态。判定与落盘都在 desktop/onboarding.py（产品条款），
        # 这里只管「没同意就别让开始任务亮起来」。
        self.consented = has_consent(self.data_root)
        self._update_info = None
        # 连点器是**独立于路线**的通用工具：一个后台线程 + 一组固定坐标，
        # 业务状态全在 core/autoclicker.py。这里只持有它，好让两件事互斥：
        # 每日任务在跑时不许开连点，连点在跑时不许开始任务。
        self.autoclicker = AutoClicker()
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
        self._stopped_route = ""
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

        strip_pos = None
        if previous is not None and previous.ball_pos is not None:
            try:
                strip_pos = (int(previous.ball_pos["x"]), int(previous.ball_pos["y"]))
            except (KeyError, TypeError, ValueError):
                pass
        self.run_animation = ArkyAnimation(self)
        self.floating = FloatingRunner(strip_pos, animation=self.run_animation)
        self._build_task_page()
        self._build_log_page()
        self._build_tools_page()
        self._build_about_page()
        self._build_sidebar()
        self.floating.position_changed.connect(self._save_strip_position)
        self.floating.open_main_requested.connect(self._return_to_main_window)
        self.floating.stop_clicked.connect(self._on_stop_clicked)
        self.floating.presentation_changed.connect(self._render_run)
        self._sync_from_controller()
        self._render_run()
        self._show_group_detail(grouped_routes()[0][0])
        # 上次跑完的结算留在存档里：打开软件就能看到，不用先跑一轮。
        if previous is not None and previous.last_run is not None:
            self._show_run_result(
                previous.last_run.at,
                previous.last_run.summary,
                previous.last_run.details,
                previous.last_run.exit_code,
            )

        self.setWindowTitle(f"{brand.APP_NAME}  {PRODUCT_VERSION}")
        self.setWindowIcon(brand.app_icon())
        # 禁用原生透明效果后直接画底色，避免首次显示时标题栏还使用透明背景。
        self.setMicaEffectEnabled(False)
        window_color = QColor("#152640")
        self.setCustomBackgroundColor(window_color, window_color)
        self.backgroundColorAni.stop()
        self.setBackgroundColor(window_color)
        self.navigationInterface.setExpandWidth(164)
        self.navigationInterface.setMinimumExpandWidth(860)
        self.navigationInterface.setCollapsible(False)
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.setIndicatorAnimationEnabled(False)
        self.navigationInterface.panel.layout().setContentsMargins(6, 47, 6, 9)
        self.widgetLayout.setContentsMargins(0, 36, 0, 0)
        self.titleBar.setFixedHeight(36)
        self.stackedWidget.setAnimationEnabled(False)
        # 首屏默认只占可用屏幕的一半左右，用户自己拖大；不要一开就铺满。
        # ⚠️ 不能写死像素：4K 与 1080p 上「1180x800」的含义完全不同。
        self.setMinimumSize(860, 560)
        self.resize(*self._initial_size())
        self._restore_geometry(previous)
        self.navigationInterface.expand(useAni=False)
        apply_pixel_style(self)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_worker)
        self._poll_timer.start(120)

        # 先让主界面画出来再弹须知：反过来的话，对话框后面是一片空白，
        # 用户会以为自己只打开了对话框、根本没装上东西（Tk 版当年同一条理由）。
        QTimer.singleShot(150, self._ensure_consent)
        # 版本检查排在须知之后、且更晚：先把该看到的画出来，再在后台悄悄问一次。
        # 它没有任何阻塞行为，慢也不会影响使用。
        QTimer.singleShot(400, self._start_update_check)
    # ── 构建界面 ────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        panel = self.navigationInterface.panel
        header = QWidget(panel)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 2, 0, 22)
        header_layout.setSpacing(1)
        self.sidebar_mascot = ArkyMascot(header, height=94)
        header_layout.addWidget(self.sidebar_mascot)
        name = SubtitleLabel(brand.APP_NAME, header)
        name.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(name)
        subtitle = CaptionLabel("ARKY ASSISTANT", header)
        subtitle.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(subtitle)
        divider = QFrame(header)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #3a5878;")
        header_layout.addSpacing(13)
        header_layout.addWidget(divider)
        panel.layout().insertWidget(0, header)
        self.sidebar_landscape = PixelBackground("sidebar", panel)
        self.sidebar_landscape.setFixedHeight(94)
        panel.bottomLayout.insertWidget(0, self.sidebar_landscape)
        version = CaptionLabel("V6.14 · PIXEL", panel)
        version.setAlignment(Qt.AlignCenter)
        panel.bottomLayout.addWidget(version)

    def _build_task_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("taskView")
        outer = self.task_content_layout = QVBoxLayout(page)
        outer.setContentsMargins(17, 4, 17, 14)
        outer.setSpacing(8)

        heading = QHBoxLayout()
        heading.addWidget(_icon_label("nav-tasks", page, 24))
        heading.addWidget(TitleLabel("任务中心", page))
        heading.addStretch(1)
        heading.addWidget(CaptionLabel(brand.APP_SUBTITLE, page))
        outer.addLayout(heading)
        self.task_banner = PixelBackground("banner", page)
        self.task_banner.setFixedHeight(78)
        outer.addWidget(self.task_banner)
        outer.addWidget(self._build_status_card())
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_route_scroll(), 5)
        side = QVBoxLayout()
        side.setSpacing(10)
        self.plan_card = self._build_plan_card()
        side.addWidget(self.plan_card)
        side.addWidget(self._build_detail_card(), 1)
        middle.addLayout(side, 3)
        outer.addLayout(middle, 1)
        actions = PixelPanel(page)
        actions.setLayout(self._build_action_bar())
        outer.addWidget(actions)
        self.addSubInterface(page, brand.icon("nav-tasks"), "任务中心", isTransparent=True)

    def _build_status_card(self) -> PixelPanel:
        card = PixelPanel(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.addWidget(_icon_label("monitor", card, 18))
        title_row.addWidget(_panel_title("运行环境", card))
        title_row.addSpacing(6)
        title_row.addWidget(BodyLabel("游戏窗口", card))
        self.backend_combo = ComboBox(card)
        self.backend_combo.setAccessibleName("游戏窗口")
        for backend in visible_backends():
            self.backend_combo.addItem(BACKEND_LABELS[backend], userData=backend)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        title_row.addWidget(self.backend_combo)

        self.status_label = BodyLabel("尚未执行环境检测。", card)
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(self.status_label, 1)
        self.check_button = PushButton(brand.icon("refresh"), "检测环境", card)
        self.check_button.clicked.connect(self._on_check_clicked)
        title_row.addWidget(self.check_button)
        layout.addLayout(title_row)
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

        return card

    def _build_route_scroll(self) -> QWidget:
        page = PixelPanel(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(_panel_title("任务清单", page))
        self.route_total = CaptionLabel("", page)
        heading.addWidget(self.route_total)
        heading.addStretch()
        self.only_selected = CheckBox("仅已选", page)
        self.only_selected.toggled.connect(self._reflow_routes)
        heading.addWidget(self.only_selected)
        self.layout_button = PushButton("卡片视图", page)
        self.layout_button.setCheckable(True)
        self.layout_button.setChecked(True)
        self.layout_button.toggled.connect(self._set_route_view)
        heading.addWidget(self.layout_button)
        layout.addLayout(heading)

        tabs = self.route_tabs = SegmentedWidget(page)
        tabs.hBoxLayout.setSpacing(4)
        layout.addWidget(tabs)
        stack = QStackedWidget(page)
        layout.addWidget(stack, 1)

        groups = grouped_routes()
        group_indexes = {group: index for index, (group, _) in enumerate(groups)}
        for group, routes in groups:
            group_page = QWidget(stack)
            group_layout = QVBoxLayout(group_page)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            group_box = CheckBox("全选", group_page)
            group_box.toggled.connect(lambda checked, g=group: self._on_group_toggled(g, checked))
            self._group_checks[group] = group_box
            group_header = QHBoxLayout()
            group_header.addWidget(group_box)
            group_header.addStretch()
            group_header.addWidget(CaptionLabel("点击任务查看说明", group_page))
            group_layout.addLayout(group_header)
            scroll = QScrollArea(group_page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            holder = QWidget(scroll)
            column = QVBoxLayout(holder)
            column.setContentsMargins(0, 0, 0, 2)
            column.setSpacing(0)
            list_head = QWidget(holder)
            list_head.setStyleSheet("background-color: #152d49;")
            list_head.setFixedHeight(22)
            header = QGridLayout(list_head)
            header.setContentsMargins(6, 0, 6, 0)
            header.addWidget(QWidget(list_head), 0, 0)
            header.addWidget(QWidget(list_head), 0, 1)
            header.addWidget(CaptionLabel("路线名称", list_head), 0, 2)
            header.addWidget(CaptionLabel("执行参数", list_head), 0, 3, Qt.AlignCenter)
            header.addWidget(CaptionLabel("设置", list_head), 0, 4, Qt.AlignCenter)
            self._list_heads.append(list_head)
            column.addWidget(list_head)
            grid = QGridLayout()
            grid.setSpacing(6)
            self._route_grids[group] = grid
            column.addLayout(grid)
            for route in routes:
                self._make_route_tile(route.mode, holder)
            column.addStretch()
            scroll.setWidget(holder)
            group_layout.addWidget(scroll, 1)
            stack.addWidget(group_page)
            tabs.addItem(group, group)
            tabs.widget(group).setAccessibleName(group)

        def show_group(group: str) -> None:
            stack.setCurrentIndex(group_indexes[group])
            self._show_group_detail(group)

        tabs.setCurrentItem(groups[0][0])
        tabs.currentItemChanged.connect(show_group)
        self._set_route_view(True)
        return page

    def _make_route_tile(self, mode: str, parent: QWidget) -> None:
        route = route_by_name(mode)
        card = PixelPanel(parent, tone="tile")
        card.setToolTip(route.description)
        tile = QGridLayout(card)
        tile.setContentsMargins(5, 4, 5, 5)
        tile.setSpacing(2)
        box = CheckBox("", card)
        box.setAccessibleName(route.display_label)
        box.toggled.connect(lambda checked: self._on_route_toggled(mode, checked))
        box.clicked.connect(lambda: self._show_route_detail(mode))
        icon = brand.route_emblem(mode, card, size=27)
        title = _RouteTitle(route.display_label, card)
        title.clicked.connect(lambda: self._show_route_detail(mode))
        counts = QWidget(card)
        counts_layout = QHBoxLayout(counts)
        counts_layout.setContentsMargins(0, 0, 0, 0)
        counts_layout.setSpacing(5)
        param = QWidget(counts)
        param_layout = QHBoxLayout(param)
        param_layout.setContentsMargins(0, 0, 0, 0)
        param_layout.setSpacing(4)
        if route.cycles_editable:
            spin = QSpinBox(param)
            style = QStyleFactory.create("Fusion")
            style.setParent(spin)
            spin.setStyle(style)
            palette = spin.palette()
            palette.setColor(QPalette.Base, QColor("#101e34"))
            palette.setColor(QPalette.Text, QColor("#f1f5ff"))
            spin.setPalette(palette)
            spin.setRange(route.min_cycles, 999)
            spin.setButtonSymbols(QSpinBox.NoButtons)
            editor = spin.findChild(QLineEdit)
            editor.setStyleSheet(
                "QLineEdit { color: #f1f5ff; background-color: #101e34;"
                " border: 1px solid #6586aa; border-radius: 0; padding: 0 3px; font-size: 12px; }"
                "QLineEdit:focus { border-color: #f3c86d; }"
                "QLineEdit:disabled { color: #adbed4; }"
            )
            spin.setFixedSize(44, 24)
            spin.setAccessibleName(f"{route.display_label}次数")
            spin.valueChanged.connect(lambda value: self._on_cycles_changed(mode, value))
            if mode == "shop_refresh":
                spin.setToolTip("填 0 仍会扫描当前货架，只关闭付费刷新。")
            self._route_spins[mode] = spin
            param_layout.addWidget(spin)
            count_unit = CaptionLabel("刷新" if mode == "shop_refresh" else "次", param)
        else:
            count_unit = CaptionLabel("自动执行", param)
            count_unit.setAlignment(Qt.AlignCenter)
            count_unit.setStyleSheet("color: #d3e1f1; background: #162d49; border: 1px solid #4b6e91;")
            count_unit.setFixedSize(64, 24)
        param_layout.addWidget(count_unit, 1, Qt.AlignCenter if not route.cycles_editable else Qt.Alignment())
        counts_layout.addWidget(param)
        settings: QWidget
        if options_for(mode):
            settings = QPushButton(brand.icon("settings"), "设置", counts)
            settings.setStyleSheet("QPushButton { padding: 0 3px; font-size: 11px; }")
            settings.setProperty("pixelRole", "settings")
            settings.setContentsMargins(0, 0, 0, 0)
            settings.setAccessibleName(f"{route.display_label}设置")
            settings.setToolTip(f"{route.display_label}设置")
            settings.clicked.connect(lambda: self._on_route_options_clicked(mode))
            self._route_option_buttons[mode] = settings
        else:
            settings = CaptionLabel("—", counts)
            settings.setAlignment(Qt.AlignCenter)
        counts_layout.addWidget(settings)
        self._route_tiles[mode] = card
        self._route_tile_controls[mode] = (icon, title, count_unit)
        self._route_checks[mode] = box
        self._route_counts[mode] = counts
        self._route_params[mode] = param
        self._route_setting_cells[mode] = settings

    def _set_route_view(self, list_view: bool) -> None:
        self._list_view = list_view
        self.layout_button.setText("卡片视图" if list_view else "列表视图")
        compact = self.width() <= 1000
        self._route_columns = 2 if compact else 3
        box_width = 16 if compact else 18
        icon_width = 24
        param_width, settings_width = ((64, 51) if compact else (79, 68)) if list_view else (69, 58)
        gap = 3 if compact else 5
        for header in self._list_heads:
            layout = header.layout()
            layout.setHorizontalSpacing(gap)
            for column, width in enumerate((box_width, icon_width, 0, param_width, settings_width)):
                layout.setColumnMinimumWidth(column, width)
            layout.setColumnStretch(2, 1)
            header.setVisible(list_view)
        for mode, card in self._route_tiles.items():
            layout = card.layout()
            while layout.count():
                layout.takeAt(0)
            icon, title, _unit = self._route_tile_controls[mode]
            font = title.caption.font()
            font.setPixelSize(12 if compact else 13)
            title.caption.setFont(font)
            box = self._route_checks[mode]
            counts = self._route_counts[mode]
            param, settings = self._route_params[mode], self._route_setting_cells[mode]
            field = self._route_spins.get(mode)
            if field is not None:
                field.setFixedWidth(44 if list_view and not compact else 35)
            param.setFixedWidth(param_width)
            settings.setFixedSize(settings_width, 24 if list_view else 26)
            if isinstance(settings, QPushButton):
                settings.setIconSize(QSize(13, 13) if compact else QSize(17, 17))
            counts.layout().setSpacing(gap)
            box.setFixedWidth(box_width)
            layout.setHorizontalSpacing(gap)
            layout.setColumnStretch(2, int(list_view))
            layout.setColumnStretch(1, int(not list_view))
            if list_view:
                icon.set_icon_size(icon_width)
                card.setFixedHeight(32)
                layout.setColumnMinimumWidth(2, 0)
                layout.setContentsMargins(6, 0, 6, 0)
                layout.addWidget(box, 0, 0, Qt.AlignVCenter)
                layout.addWidget(icon, 0, 1)
                title.caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                layout.addWidget(title, 0, 2)
                layout.addWidget(counts, 0, 3)
            else:
                icon.set_icon_size(36)
                card.setFixedHeight(105 if compact else 104)
                layout.setContentsMargins(6, 5, 6, 5)
                layout.addWidget(icon, 0, 1, Qt.AlignCenter)
                layout.addWidget(box, 0, 0, Qt.AlignLeft | Qt.AlignTop)
                title.caption.setAlignment(Qt.AlignCenter)
                layout.addWidget(title, 1, 0, 1, 3, Qt.AlignVCenter)
                layout.addWidget(counts, 2, 0, 1, 3, Qt.AlignCenter)
                layout.setColumnMinimumWidth(2, box_width)
            self._set_route_order(mode)
        self._reflow_routes()

    def _set_route_order(self, mode: str) -> None:
        selection = self.controller.selection
        index = selection.index(mode) if mode in selection else -1
        order = f"{index + 1:02}" if index >= 0 else "—"
        title = self._route_tile_controls[mode][1]
        label = route_by_name(mode).display_label
        title.set_label(f"{order}  {label}" if not self._list_view and index >= 0 else label)

    def _reflow_routes(self) -> None:
        columns = 1 if self._list_view else self._route_columns
        for group, routes in grouped_routes():
            grid = self._route_grids[group]
            grid.setSpacing(2 if self._list_view else (6 if self.width() <= 1000 else 8))
            for col in range(3):
                grid.setColumnStretch(col, int(col < columns))
            index = 0
            for route in routes:
                card = self._route_tiles[route.mode]
                grid.removeWidget(card)
                visible = route.visible_on(self.controller.selected_backend) and (
                    not self.only_selected.isChecked() or route.mode in self.controller.selection
                )
                card.setVisible(visible)
                if visible:
                    selected = route.mode in self.controller.selection
                    if self._list_view:
                        tone = "listrow-selected" if selected else ("listrow-alt" if index % 2 else "listrow")
                    else:
                        tone = "selected" if selected else "tile"
                    card.set_tone(tone)
                    grid.addWidget(card, *divmod(index, columns))
                    index += 1

    def _build_plan_card(self) -> PixelPanel:
        card = PixelPanel(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(11, 8, 11, 8)
        title = QHBoxLayout()
        title.addWidget(_icon_label("nav-logs", card, 15))
        title.addWidget(_panel_title("本次执行计划", card), 1)
        self.clear_plan_button = PushButton("清空", card)
        self.clear_plan_button.clicked.connect(self._clear_plan)
        title.addWidget(self.clear_plan_button)
        layout.addLayout(title)
        self.selection_summary = CaptionLabel("", card)
        self.selection_summary.setWordWrap(True)
        layout.addWidget(self.selection_summary)
        self.plan_list = self._list_widget(card)
        self.plan_list.itemClicked.connect(lambda item: self._show_route_detail(item.data(Qt.UserRole)))
        layout.addWidget(self.plan_list, 1)
        self.plan_empty = QWidget(card)
        empty = QHBoxLayout(self.plan_empty)
        empty.setContentsMargins(0, 0, 0, 0)
        empty.setSpacing(8)
        empty.addStretch()
        self.plan_empty_art = ArkyMascot(self.plan_empty, height=56, pose="waiting")
        self.plan_empty_art.setFixedWidth(56)
        empty.addWidget(self.plan_empty_art)
        hint = CaptionLabel("从左侧勾选任务", self.plan_empty)
        hint.setAlignment(Qt.AlignCenter)
        empty.addWidget(hint)
        empty.addStretch()
        layout.addWidget(self.plan_empty, 1)
        return card

    @staticmethod
    def _list_widget(parent: QWidget) -> QListWidget:
        widget = QListWidget(parent)
        widget.setFrameShape(QFrame.NoFrame)
        widget.setIconSize(QSize(22, 22))
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget.setWordWrap(True)
        widget.setResizeMode(QListWidget.Adjust)
        widget.setTextElideMode(Qt.ElideNone)
        return widget

    def _build_detail_card(self) -> PixelPanel:
        card = PixelPanel(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        heading.addWidget(_panel_title("任务说明", card), 1)
        self.detail_art = ArkyMascot(card, height=58, pose="reading")
        self.detail_art.setFixedWidth(58)
        heading.addWidget(self.detail_art)
        layout.addLayout(heading)
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
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignTop)
        scroller.setWidget(self.detail_body)
        layout.addWidget(scroller, 1)
        return card

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(7)
        followup = QVBoxLayout()
        followup.setSpacing(0)
        self.run_state_label = CaptionLabel("待执行", self)
        followup.addWidget(self.run_state_label)
        # 「完成后关机」是本次运行之后做什么，和「开始任务」放在一起，
        # 点开始前一眼能看见；不放进上面的环境卡（那张卡说的是怎么连游戏）。
        shutdown_row = QHBoxLayout()
        shutdown_row.setSpacing(5)
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
        shutdown_row.addWidget(self.shutdown_switch)
        shutdown_row.addWidget(BodyLabel("完成后关机", self))
        shutdown_row.addStretch()
        followup.addLayout(shutdown_row)
        bar.addLayout(followup)
        bar.addStretch(1)
        # 排定关机之后才出现：给还在电脑前的用户一个明确的撤销入口，
        # 而不是让他去命令行记 shutdown /a。
        self.cancel_shutdown_button = PushButton("取消关机", self)
        self.cancel_shutdown_button.clicked.connect(self._on_cancel_shutdown_clicked)
        self.cancel_shutdown_button.setVisible(False)
        bar.addWidget(self.cancel_shutdown_button)
        self.export_button = PushButton(brand.icon("export"), "导出诊断包", self)
        self.export_button.clicked.connect(self._on_export_clicked)
        bar.addWidget(self.export_button)
        self.stop_button = PushButton(brand.icon("stop"), "安全停止", self)
        self.stop_button.setProperty("pixelRole", "danger")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        bar.addWidget(self.stop_button)
        self.start_button = PrimaryPushButton(brand.icon("play"), "开始任务", self)
        self.start_button.clicked.connect(self._on_start_clicked)
        bar.addWidget(self.start_button)
        return bar

    def _build_log_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("logView")
        self.log_page = page
        layout = self.logs_content_layout = QVBoxLayout(page)
        layout.setContentsMargins(17, 4, 17, 14)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        heading.addWidget(_icon_label("nav-logs", page, 24))
        heading.addWidget(TitleLabel("运行日志", page), 1)
        self.log_cancel_shutdown_button = PushButton("取消关机", page)
        self.log_cancel_shutdown_button.clicked.connect(self._on_cancel_shutdown_clicked)
        self.log_cancel_shutdown_button.hide()
        heading.addWidget(self.log_cancel_shutdown_button)
        self.floating_button = PushButton(brand.icon("collapse"), "缩为浮窗", page)
        self.floating_button.clicked.connect(self._enter_floating_mode_again)
        heading.addWidget(self.floating_button)
        self.log_stop_button = PushButton(brand.icon("stop"), "安全停止", page)
        self.log_stop_button.setProperty("pixelRole", "danger")
        self.log_stop_button.clicked.connect(self._on_stop_clicked)
        heading.addWidget(self.log_stop_button)
        layout.addLayout(heading)

        # ── 块一：结论带 ────────────────────────────────────────────────────
        # 完结后第一眼只要两个答案：成了没有、卡在哪。状态词 + 一句原因 + 时间与
        # 用时；进度条与百分比**只在运行中出现** —— 已经结束了还留着 50% 的进度条，
        # 会让人以为没跑完（原来的状态卡就是这样）。
        status = self.verdict_panel = PixelPanel(page)
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(11, 7, 12, 7)
        self.result_mascot = ArkyMascot(status, height=58, animation=self.run_animation, pose="travel")
        self.result_mascot.setFixedWidth(60)
        status_layout.addWidget(self.result_mascot)
        status_text = QVBoxLayout()
        status_text.setSpacing(2)
        title_row = QHBoxLayout()
        self.run_title = SubtitleLabel("尚无运行结果", status)
        title_row.addWidget(self.run_title, 1)
        self.run_meta = CaptionLabel("", status)
        title_row.addWidget(self.run_meta)
        self.run_percent = _panel_title("0%", status)
        title_row.addWidget(self.run_percent)
        status_text.addLayout(title_row)
        self.run_title.setWordWrap(True)
        # 结论那一句原因：运行中不占位置，完结后由结果数据回填。
        self.run_reason = BodyLabel("", status)
        self.run_reason.setWordWrap(True)
        self.run_reason.hide()
        status_text.addWidget(self.run_reason)
        self.run_count = CaptionLabel("已处理 0 / 0 项", status)
        self.run_count.setWordWrap(True)
        self.run_count.setToolTip("按路线数计算")
        status_text.addWidget(self.run_count)
        self.run_progress_bar = QProgressBar(status)
        self.run_progress_bar.setRange(0, 100)
        self.run_progress_bar.setTextVisible(False)
        self.run_progress_bar.setFixedHeight(13)
        self.run_progress_bar.setAccessibleName("路线处理进度")
        status_text.addWidget(self.run_progress_bar)
        status_layout.addLayout(status_text, 1)
        layout.addWidget(status)

        # ── 块二：结果明细 ──────────────────────────────────────────────────
        # 一条路线一行（状态、轮次、用时、原因），不再是把整轮塞成一段话；
        # 统计行的各项相加等于本轮项数 —— 待确认 / 无剩余内容 / 未执行以前不进
        # 统计，10 项只交代得出 6 项。
        self.result_card = PixelPanel(page)
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setContentsMargins(11, 6, 11, 7)
        result_layout.setSpacing(6)
        result_heading = QHBoxLayout()
        self.result_title = _panel_title("本次运行结果", self.result_card)
        result_heading.addWidget(self.result_title, 1)
        self.result_count = CaptionLabel("0/0 项", self.result_card)
        result_heading.addWidget(self.result_count)
        result_layout.addLayout(result_heading)
        self.result_metrics = BodyLabel("", self.result_card)
        self.result_metrics.setWordWrap(True)
        result_layout.addWidget(self.result_metrics)
        # 拆不出逐条结构时（旧存档、旧格式、词表对不上）才回落成整段文本。
        # 平时不出现，所以不需要固定高度 —— 真用得上的时候要能看清。
        self.result_scroll = QScrollArea(self.result_card)
        self.result_scroll.setFrameShape(QFrame.NoFrame)
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setMaximumHeight(120)
        self.result_text = CaptionLabel("", self.result_scroll)
        self.result_text.setWordWrap(True)
        self.result_text.setAlignment(Qt.AlignTop)
        self.result_scroll.setWidget(self.result_text)
        self.result_scroll.hide()
        result_layout.addWidget(self.result_scroll)
        self.run_routes = self._list_widget(self.result_card)
        self.run_routes.setAccessibleName("本次路线进度")
        result_layout.addWidget(self.run_routes, 1)

        # 诊断包操作条：贴在结果卡底部，不再单独成卡 —— 它只在要提交时才用得上，
        # 单独一张卡会跟「本轮结果」抢同一层注意力。也没有「关闭」：关掉就等于
        # 把这两个按钮一起收走，要等下轮失败才能再拿到。
        self.report_strip = QFrame(self.result_card)
        self.report_strip.setObjectName("reportStrip")
        self.report_strip.setStyleSheet(
            "QFrame#reportStrip { background: #192f4a; border: 1px solid #4b6d91; }"
        )
        strip_layout = QVBoxLayout(self.report_strip)
        strip_layout.setContentsMargins(9, 6, 9, 6)
        strip_layout.setSpacing(3)
        strip_row = QHBoxLayout()
        strip_row.setSpacing(7)
        strip_row.addWidget(_icon_label("export", self.report_strip, 16))
        self.report_file = BodyLabel("", self.report_strip)
        strip_row.addWidget(self.report_file)
        self.report_code = CaptionLabel("", self.report_strip)
        strip_row.addWidget(self.report_code)
        strip_row.addStretch(1)
        self.report_open_button = PushButton(
            brand.icon("export"), "打开文件夹", self.report_strip
        )
        self.report_open_button.clicked.connect(self._open_report_folder)
        strip_row.addWidget(self.report_open_button)
        self.report_copy_button = PushButton(brand.icon("copy"), "复制提交说明", self.report_strip)
        self.report_copy_button.clicked.connect(self._copy_report_note)
        strip_row.addWidget(self.report_copy_button)
        strip_layout.addLayout(strip_row)
        self.report_note = CaptionLabel(
            "提交时附上这个文件，并写明失败前的操作与界面最后显示的内容。",
            self.report_strip,
        )
        self.report_note.setWordWrap(True)
        strip_layout.addWidget(self.report_note)
        self.report_strip.setVisible(False)
        result_layout.addWidget(self.report_strip)
        layout.addWidget(self.result_card, 1)

        # ── 块三：实时日志（可收起）─────────────────────────────────────────
        # 运行中默认展开（过程有用），完结后收起：日志是档案，不该跟结论抢版面。
        log_card = self.live_log_card = PixelPanel(page)
        log_layout = self.log_content_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(11, 8, 11, 8)
        row = QHBoxLayout()
        row.addWidget(_panel_title("实时日志", log_card))
        self.log_caption = CaptionLabel("· 最近记录 / 可滚动", log_card)
        row.addWidget(self.log_caption, 1)
        self.log_clear_button = PushButton("清空显示", log_card)
        row.addWidget(self.log_clear_button)
        self.log_toggle_button = PushButton("收起", log_card)
        self.log_toggle_button.clicked.connect(
            lambda: self._set_log_expanded(not self._log_expanded)
        )
        row.addWidget(self.log_toggle_button)
        log_layout.addLayout(row)
        self.log_text = QPlainTextEdit(log_card)
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(2000)
        self.log_clear_button.clicked.connect(self.log_text.clear)
        log_layout.addWidget(self.log_text, 1)
        layout.addWidget(log_card, 1)
        self.addSubInterface(page, brand.icon("nav-logs"), "运行日志", isTransparent=True)

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
        self.addSubInterface(page, brand.icon("nav-tools"), "实用工具", isTransparent=True)

    def _autoclick_block_reason(self) -> str | None:
        """现在能不能开连点器：不能就返回一句人话，能就返回 ``None``。

        ⚠️ 两套点击同时发会互相干扰 —— 每日任务的点击是「认画面 → 点这一个点」，
        中间被连点器抢走鼠标就会点到别的地方。宁可直接拒绝，也不要「大概能跑」。
        """
        if self.worker.running:
            return "每日任务正在运行。先停下它再开连点器，两套点击同时发会互相干扰。"
        if self._checking:
            return "环境检测或启动复检期间，连点器暂不可用。"
        return None

    def _build_about_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("aboutView")
        layout = self.about_content_layout = QVBoxLayout(page)
        layout.setContentsMargins(17, 4, 17, 14)
        layout.setSpacing(10)
        layout.addWidget(TitleLabel("关于亚卡助手", page))
        identity = PixelPanel(page)
        identity_layout = QHBoxLayout(identity)
        identity_layout.setContentsMargins(13, 6, 13, 6)
        mascot = ArkyMascot(identity, height=84, pose="about")
        mascot.setFixedWidth(90)
        identity_layout.addWidget(mascot)
        info = QVBoxLayout()
        logo = QLabel(identity)
        logo.setPixmap(brand.logo_pixmap(64))
        logo.setFixedSize(64, 64)
        logo.setScaledContents(False)
        logo.setAccessibleName("亚卡助手 Logo")
        info.addWidget(logo)
        info.addWidget(TitleLabel(brand.APP_NAME, identity))
        info.addWidget(BodyLabel(brand.APP_SUBTITLE, identity))
        info.addWidget(CaptionLabel(f"产品版本 {PRODUCT_VERSION} · V6.14", identity))
        identity_layout.addLayout(info, 1)
        layout.addWidget(identity)
        self.about_landscape = PixelBackground("about", page)
        self.about_landscape.setFixedHeight(168)
        layout.addWidget(self.about_landscape)
        project = PixelPanel(page)
        project_layout = QVBoxLayout(project)
        project_layout.setContentsMargins(13, 10, 13, 10)
        project_layout.addWidget(_panel_title("开源项目", project))
        about = BodyLabel(
            "本助手用于《第七史诗》单人 PVE 内容的自动化执行。"
            "仅在确认游戏处于预期环节时执行下一步；页面无法确认、画面被遮挡或"
            "转场未完成时，保留现场并停止。\n\n"
            "默认执行干跑，实跑需显式确认。涉及付费购买与不可逆操作的路径不予执行。",
            project,
        )
        about.setWordWrap(True)
        project_layout.addWidget(about)
        note = BodyLabel(
            "「任务中心」按勾选顺序依次跑选中的路线；「实用工具」里是与路线无关的"
            "小工具（目前是固定点连点器）。两者不能同时开 —— 两套点击会互相干扰。",
            project,
        )
        note.setWordWrap(True)
        project_layout.addWidget(note)
        art_credit = CaptionLabel(
            '亚卡属于《第七史诗》。素材参考'
            '<a style="color:#a6d9ff" href="https://www.bilibili.com/video/BV1WT421e7xG/">官方周年短片</a>和'
            '<a style="color:#a6d9ff" href="https://czn.gg/event-notice-on-the-chaos-zero-nightmare-x-epic-seven-collaboration-event/">'
            '联动贴纸</a>。本助手由社区维护。',
            project,
        )
        art_credit.setWordWrap(True)
        art_credit.setOpenExternalLinks(True)
        project_layout.addWidget(art_credit)
        row = QHBoxLayout()
        self.consent_button = PushButton("重新查看使用须知", page)
        self.consent_button.clicked.connect(self._show_consent)
        row.addWidget(self.consent_button)
        row.addStretch(1)
        project_layout.addLayout(row)
        layout.addWidget(project)
        layout.addStretch(1)
        self.addSubInterface(
            page, brand.icon("nav-about"), "关于", NavigationItemPosition.BOTTOM,
            isTransparent=True,
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
            backend = self.controller.selected_backend
            for mode, box in self._route_checks.items():
                self._set_route_order(mode)
                box.setChecked(mode in selection)
            total = 0
            for group, box in self._group_checks.items():
                routes = routes_in_group(group, backend)
                selected = sum(route.mode in selection for route in routes)
                self.route_tabs.widget(group).setText(f"{group} {selected}/{len(routes)}")
                box.setChecked(bool(routes) and selected == len(routes))
                total += len(routes)
            self.route_total.setText(f"· {total} 条")
            for mode, spin in self._route_spins.items():
                spin.setValue(self.controller.cycles[mode])
            target = self.backend_combo.findData(backend)
            if target >= 0:
                self.backend_combo.setCurrentIndex(target)
            self.hint_label.setText(STARTUP_HINTS.get(backend, ""))
            if self._detail_mode is not None:
                route = route_by_name(self._detail_mode)
                if route.visible_on(backend):
                    self._update_pc_note(route.mode)
                else:
                    self._show_group_detail(route.group)
            elif self._detail_group is not None:
                self._show_group_detail(self._detail_group)
            self._refresh_plan()
            self._reflow_routes()
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
        can_stop = running and not self._stop_requested_by_user and self.floating.outcome != "stopping"
        self.stop_button.setEnabled(can_stop)
        self.log_stop_button.setEnabled(can_stop)
        # 完结后把这颗红色按钮从标题栏撤掉：留着只能点（实为灰）的「安全停止」，
        # 等于让读者先去找它、再去读日志。
        self.log_stop_button.setVisible(running)
        self.floating_button.setEnabled(bool(self.floating.progress.total_count))
        self.check_button.setEnabled(not running and not self._checking)
        editable = not running and not self._checking
        self.backend_combo.setEnabled(editable)
        # 运行期间锁定本次选择与次数。
        self.shutdown_switch.setEnabled(editable)
        self.clear_plan_button.setEnabled(editable and bool(self.controller.selection))
        for box in (*self._route_checks.values(), *self._group_checks.values()):
            box.setEnabled(editable)
        for spin in self._route_spins.values():
            spin.setEnabled(editable)
        for button in self._route_option_buttons.values():
            button.setEnabled(editable)
        self.run_state_label.setText(
            "进行中" if running else
            f"已选 {len(self.controller.selection)} 项 · "
            "按勾选顺序执行"
        )

    def _refresh_plan(self) -> None:
        plan = self.controller.plan()
        try:
            runnable, skipped = self.controller.resolve_plan() if plan else ((), ())
        except RuntimeError:
            runnable, skipped = (), tuple(mode for mode, _ in plan)
        self.selection_summary.setText(
            f"已选 {len(plan)} 项 · 可执行 {len(runnable)} · 跳过 {len(skipped)}"
        )
        self.plan_list.clear()
        for index, (mode, count) in enumerate(plan, 1):
            route = route_by_name(mode)
            ending = "跳过" if mode in skipped else route.count_text(count)
            item = QListWidgetItem(brand.icon(mode), f"{index}. {route.display_label}   {ending}")
            item.setData(Qt.UserRole, mode)
            item.setToolTip(unavailable_note(mode, self.controller.selected_backend) or item.text())
            self.plan_list.addItem(item)
        self.plan_list.setVisible(bool(plan))
        self.plan_empty.setVisible(not plan)

    def _clear_plan(self) -> None:
        if self.worker.running or self._checking:
            return
        for mode in tuple(self.controller.selection):
            self.controller.toggle(mode, False)
        self._sync_from_controller()
        self._save_session()

    def _render_run(self) -> None:
        progress = self.floating.progress
        done, total = progress.processed_count, progress.total_count
        outcome = self.floating.outcome
        finished = outcome not in {"idle", "running", "stopping"}
        if total:
            self.run_title.setText(self.floating.status_text)
        elif not self._detail_rows:
            # 首屏还原了上次结果时不覆盖标题 —— 那行是存档里的结论，不是「尚无结果」。
            self.run_title.setText("尚无运行结果")
        # 结论词按状态着色：失败红、完成绿、停止与待确认金、运行中不着色。
        self.run_title.setStyleSheet(
            f"color: {_VERDICT_COLORS[outcome]};" if outcome in _VERDICT_COLORS else ""
        )
        self.run_count.setText(f"已处理 {done} / {total} 项" if total else "")
        # 完结后不再显示「已处理 N / M」：结果卡标题右侧已经有同一个数，
        # 而且进度若没收到汇总（崩溃早退），这里会与结果卡的统计对不上。
        self.run_count.setVisible(bool(total) and not finished)
        percent = round(100 * done / total) if total else 0
        self.run_progress_bar.setValue(percent)
        # 完结后进度条与百分比一起撤掉：停在一半的进度条等于在说「还没跑完」。
        self.run_progress_bar.setVisible(bool(total) and not finished)
        self.run_percent.setText(f"{percent}%")
        self.run_percent.setVisible(bool(total) and not finished)
        self.result_count.setText(f"已处理 {done} / {total} 项" if total else "")
        self.result_count.setToolTip("按路线数计算；未执行的路线不计入已处理")
        # 运行中只在结论带上显示这个数（挨着进度条），结果卡右侧留白；
        # 完结后结论带收起来，这里再补上「十项里处理了几项」。
        self.result_count.setVisible(finished and bool(total))
        rows = self._compose_rows()
        self.result_metrics.setText(_metrics_html(rows))
        if rows != self._shown_rows:
            self.run_routes.clear()
            for row in rows:
                self._append_run_result(row)
            self._shown_rows = rows
        self._refresh_actions()

    def _compose_rows(self) -> tuple[_ResultRow, ...]:
        """结果卡的行：本轮跑过就用进度，首屏还原时用存档里的逐条明细。

        两种来源先变成同一种 ``_ResultRow`` 再交给渲染，序号与配色只有一处实现。
        """
        items = tuple(
            replace(item, status="stopped")
            if self.floating.outcome == "stopped"
            and item.mode == self._stopped_route
            and item.status in {"running", "pending", "awaiting_confirmation"}
            else item
            for item in self.floating.progress.result_items
        )
        if items:
            rows = []
            for index, item in enumerate(items, 1):
                route = route_by_name(item.mode)
                detail = self._detail_by_label.get(route.label)
                status = detail.status if detail else _ROW_WORDS.get(item.status, "待执行")
                rows.append(
                    _ResultRow(
                        index=index,
                        label=route.display_label,
                        status=status,
                        tone=_WORD_TONES.get(status, "muted"),
                        meta=detail.meta if detail else "",
                        note=detail.note if detail else "",
                        reason=detail.reason if detail else "",
                        text=detail.text if detail else "",
                        mode=item.mode,
                    )
                )
            return tuple(rows)
        return tuple(
            _ResultRow(
                index=index,
                label=line.label,
                status=line.status,
                tone=_WORD_TONES.get(line.status, "muted"),
                meta=line.meta,
                note=line.note,
                reason=line.reason,
                text=line.text,
            )
            for index, line in enumerate(self._detail_rows, 1)
        )

    def _append_run_result(self, row: _ResultRow) -> None:
        color = _TONE_COLORS[row.tone]
        failure = row.tone == "danger"
        widget = QWidget(self.run_routes)
        widget.setObjectName("routeResult")
        widget.setAttribute(Qt.WA_StyledBackground)
        widget.setStyleSheet(
            "QWidget#routeResult { background: %s; border-left: %s;"
            " border-bottom: 1px solid #416183; }"
            % ("#3a2a35" if failure else "#142940", f"2px solid {color}" if failure else "0")
        )
        # 用网格而不是横排：状态列与轮次/用时列各自定宽右对齐，十行一起扫的时候
        # 数字落在同一竖线上。横排（QHBoxLayout）里 trailing 控件随文字宽度浮动，
        # 「完成 2/2 轮」和「待执行」会一左一右，看着就是「杂」。
        grid = QGridLayout(widget)
        grid.setContentsMargins(8, 2, 8, 3)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(1)
        order = CaptionLabel(f"{row.index:02}", widget)
        order.setFixedWidth(22)
        grid.addWidget(order, 0, 0)
        column = 1
        if row.mode:
            grid.addWidget(_icon_label(row.mode, widget, 22), 0, column)
            column += 1
        grid.addWidget(_icon_label(_TONE_ICONS[row.tone], widget, 15), 0, column)
        column += 1
        name = BodyLabel(row.label, widget)
        if row.tone == "muted":
            name.setStyleSheet(f"color: {_TONE_COLORS['muted']};")
        grid.addWidget(name, 0, column)
        grid.setColumnStretch(column, 1)
        column += 1
        status = CaptionLabel(row.status, widget)
        status.setStyleSheet(f"color: {color};")
        status.setMinimumWidth(78)
        status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(status, 0, column)
        column += 1
        # 轮次与用时只放能对成列的短字段（解析时已经把成句的说明分到第二行）。
        meta = CaptionLabel(row.meta, widget)
        meta.setStyleSheet(f"color: {_TONE_COLORS['info']};")
        meta.setMinimumWidth(132)
        meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(meta, 0, column)
        if row.detail_text:
            sub = CaptionLabel(row.detail_text, widget)
            sub.setWordWrap(True)
            # 与名称左边缘对齐：有路线图标时是 88px，还原存档的行没有图标，是 59px。
            sub.setContentsMargins(80 if row.mode else 51, 0, 0, 0)
            sub.setStyleSheet(
                f"color: {color};" if row.tone in {"danger", "warning"} else f"color: {_TONE_COLORS['info']};"
            )
            grid.addWidget(sub, 1, 0, 1, column + 1)
        entry = QListWidgetItem(f"{row.index:02}   {row.label}   ·   {row.status}")
        entry.setToolTip(" ".join(filter(None, (row.meta, row.full_text))))
        # 带副标题的行给 48px（主行 + 一句副标题）；副标题只有一句，正常宽度下不折行。
        entry.setSizeHint(QSize(0, 48 if row.detail_text else 31))
        self.run_routes.addItem(entry)
        self.run_routes.setItemWidget(entry, widget)

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
            self._notify("error", "无法全选", str(error))
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
        self._refresh_plan()
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
            route_by_name(mode).display_label,
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
        if self._checking or self.worker.running:
            return
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
        if not self._cancel_shutdown():
            self._notify("error", "无法开始任务", "已排定自动关机。取消后可开始任务。")
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
        try:
            if self._closing:
                return
            if error is not None:
                self.status_label.setText(f"环境复检失败：{error}")
                self._notify("error", "无法开始执行", str(error))
                return
            self.controller.apply_preflight(report)
            self.status_label.setText(report.message)
            if not report.can_start:
                self._notify("error", "环境不允许实跑", report.message)
                return
            runnable, _skipped = self.controller.resolve_plan()
            if self.autoclicker.running:
                self._notify("warning", "连点器正在运行", "先停止连点器，再开始任务。")
                return
            if report.warning:
                self._append_log(report.warning)
            if self._stop_timer is not None:
                self._stop_timer.stop()
            self._stop_requested_by_user = False
            self.controller.start()
            modes = "、".join(route_by_name(mode).display_label for mode, _ in runnable)
            self._append_log(f"已启动：{modes}")
            self._enter_floating_mode(
                tuple((mode, route_by_name(mode).label) for mode, _ in runnable)
            )
        except Exception as caught:
            self._notify("error", "无法启动", str(caught))
        finally:
            self._checking = False
            if not self._closing:
                self._refresh_actions()

    def _enter_floating_mode(self, routes: tuple[tuple[str, str], ...]) -> None:
        self.switchTo(self.log_page)
        self._stopped_route = ""
        self.floating.start_run(routes)
        self.hide()
        self.floating.show_strip()

    def _return_to_main_window(self) -> None:
        self.floating.hide_all()
        self.switchTo(self.log_page)
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _enter_floating_mode_again(self) -> None:
        if not self.floating.progress.total_count:
            return
        self.switchTo(self.log_page)
        self.hide()
        self.floating.show_strip()

    def _save_strip_position(self, pos: object) -> None:
        """沿用已有会话的位置字段，使升级后仍能找到窗口。"""
        if not (isinstance(pos, tuple) and len(pos) == 2):
            return
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError):
            return
        previous = session.load(self._session_path) or session.SessionState()
        session.save(self._session_path, replace(previous, ball_pos={"x": x, "y": y}))

    def _on_stop_clicked(self) -> None:
        if not self.worker.running or self._stop_requested_by_user:
            return
        self._stop_requested_by_user = True
        self._stopped_route = self.floating.progress.active_mode
        self.controller.stop()
        self.floating.stop_requested()
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
            self.floating.finish(130)
        else:
            self._append_log(
                f"等待 {seconds:.0f} 秒仍无响应且无法结束本次运行；"
                "需在任务管理器中手动结束助手进程。"
            )
        # 强行结束时读输出的线程可能还卡在那条阻塞的管道上（``事件=结束`` 不会来），
        # 所以这里必须自己把按钮状态收回来，不能等 finished 事件。
        self._refresh_actions()

    def _show_report_card(self, path: str) -> None:
        """失败后展示诊断包：文件名、短码、两个动作，贴在结果卡底部。

        文件名必须露出来 —— 用户要提交的是**这个压缩包**，短码只是给维护者对暗号用。
        """

        self._report_path = Path(path)
        self.report_file.setText(self._report_path.name)
        self.report_file.setToolTip(str(self._report_path))
        self.report_code.setText(f"短码 {short_code_of(self._report_path)}")
        self.report_strip.setVisible(True)
        self._append_log(f"诊断包已生成：{path}")

    def _hide_report_card(self) -> None:
        self.report_strip.setVisible(False)
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
        self._detail_group = group
        self.detail_title.setText(f"{group} · 分组说明")
        self.detail_body.setText(group_description(group, self.controller.selected_backend))
        self._update_pc_note()

    def _show_route_detail(self, mode: str) -> None:
        route = route_by_name(mode)
        # 记下当前在看哪一条：切换窗口后端时要重算标题下面那行「能不能跑」，
        # 否则会把上一个后端的结论留在屏幕上（切换后不点别的路线就会看到假提示）。
        self._detail_mode = mode
        self.detail_title.setText(route.display_label)
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
        self.log_text.appendPlainText(line)
        if self.floating.outcome in {"running", "stopping"}:
            self.floating.append_log(line)

    def _poll_worker(self) -> None:
        for event in self.worker.drain_events():
            if event.kind == "log":
                self._append_log(event.message)
                self.floating.note_line(event.message)
            elif event.kind == "started":
                # 新一轮开跑：先把上一次的结果收起来，免得两轮结论叠在一起。
                self.result_title.setText("本次运行进度")
                self.result_text.clear()
                self.result_scroll.hide()
                self._detail_rows = ()
                self._detail_by_label = {}
                self.run_meta.clear()
                self.run_meta.hide()
                self.run_reason.clear()
                self.run_reason.hide()
                self._hide_report_card()
                self._set_log_expanded(True)
                self._append_log("自动化已启动。")
            elif event.kind == "report":
                self._show_report_card(event.message)
            elif event.kind == "stopping":
                self._append_log("正在安全停止……")
                self.floating.stop_requested()
            elif event.kind == "finished":
                if self._stop_timer is not None:
                    self._stop_timer.stop()
                self._append_log(f"运行结束（退出码 {event.exit_code}）。")
                exit_code = 130 if self._stop_requested_by_user else event.exit_code
                if exit_code == 130 and not self._stopped_route:
                    self._stopped_route = self.floating.progress.active_mode
                self.floating.note_line(event.message or f"运行结束（退出码 {event.exit_code}）。")
                self.floating.finish(exit_code)
                self._save_last_run(event.exit_code)
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
        self._show_run_result(at, summary, details, exit_code)

    def _show_run_result(
        self,
        at: str,
        summary: str,
        details: str,
        exit_code: int | None = None,
    ) -> None:
        """有逐条明细就排成行；拆不出来（旧存档、旧格式）就回落成整段文本。

        ``exit_code`` 只在首屏还原时用得上：那次没有 ``floating`` 状态可读，
        结论词只能从存档里的退出码推。
        """
        text = details.strip() or summary.strip()
        if not text:
            return
        text = text.replace("企鹅批量购买", route_by_name("penguin_purchase").label)
        self.result_title.setText(f"本次运行结果 · {at}" if at else "本次运行结果")
        rows, headline, extra = parse_result_details(text.splitlines())
        self._detail_rows = rows
        self._detail_by_label = {row.label: row for row in rows}
        if rows:
            self.result_scroll.hide()
        else:
            # 一行都拆不出来：整段照旧显示，一个字都不丢。
            self.result_text.setText(text)
            self.result_scroll.show()
        # 详情晚于行到达，必须让行重建一次才能带上轮次、用时与原因。
        self._shown_rows = ()
        self._render_run()
        self._show_verdict(at, headline, extra, exit_code)
        # 完结后日志收起：它是档案，不该跟结论抢版面。
        self._set_log_expanded(False)

    def _show_verdict(
        self,
        at: str,
        headline: str,
        extra: tuple[str, ...],
        exit_code: int | None,
    ) -> None:
        """结论带只写两件事：这轮成没成、第一处卡在哪。"""
        text, color = self._verdict_style(exit_code)
        self.run_title.setText(text)
        self.run_title.setStyleSheet(f"color: {color};")
        clock = at.split(" ")[-1] if at else ""
        elapsed = elapsed_of(headline)
        parts = [part for part in (clock, f"用时 {elapsed}" if elapsed else "") if part]
        self.run_meta.setText(" · ".join(parts))
        self.run_meta.setVisible(bool(parts))
        culprit = next(
            (row for row in self._shown_rows if row.tone == "danger" and row.reason), None
        )
        if culprit is None:
            culprit = next((row for row in self._shown_rows if row.reason), None)
        reason = f"{culprit.label}：{culprit.reason}" if culprit is not None else ""
        if not reason:
            aborted = next((line for line in extra if line.startswith("已中止")), "")
            reason = aborted.partition("：")[2]
        self.run_reason.setText(reason)
        self.run_reason.setVisible(bool(reason))

    def _verdict_style(self, exit_code: int | None) -> tuple[str, str]:
        outcome = self.floating.outcome
        if outcome in _VERDICT_COLORS:
            return OUTCOME_LABELS[outcome], _VERDICT_COLORS[outcome]
        key = {0: "success", 2: "resource_exhausted", 130: "stopped"}.get(exit_code, "failure")
        return OUTCOME_LABELS[key], _VERDICT_COLORS[key]

    def _set_log_expanded(self, expanded: bool) -> None:
        """日志展开 / 收起。

        ⚠️ 三处一起改，缺一处收起后就会留一大块空白（2026-11-28 真实截图发现）：
        ① 文本框隐藏；② 文本框的**最大高度压到 0** —— 它是 Expanding，即使隐藏、
        stretch 归零，布局仍把剩余高度分给它（实测 250px 的卡片里 229px 给了它）；
        ③ 卡片自身在页面布局里的 stretch 与高度上下限（``_apply_log_height``）。
        """
        self._log_expanded = expanded
        self.log_text.setVisible(expanded)
        self.log_text.setMaximumHeight(16777215 if expanded else 0)
        self.log_caption.setText("· 最近记录 / 可滚动" if expanded else "· 已收起")
        self.log_toggle_button.setText("收起" if expanded else "展开")
        self.log_clear_button.setVisible(expanded)
        self.log_content_layout.setStretchFactor(self.log_text, 1 if expanded else 0)
        self.logs_content_layout.setStretchFactor(self.live_log_card, 1 if expanded else 0)
        self._apply_log_height()

    def _apply_log_height(self) -> None:
        """收起时撤掉卡片的高度上下限，否则它仍按展开时的 250~285 占着位置。"""
        if self._log_expanded:
            self.live_log_card.setMinimumHeight(self._log_min_height)
            self.live_log_card.setMaximumHeight(self._log_max_height)
            return
        self.live_log_card.setMinimumHeight(0)
        self.live_log_card.setMaximumHeight(16777215)

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
            self._show_shutdown_status("等待模拟器退出后关机")
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
            self._show_shutdown_status("")
            self._append_log("自动关机未排定（关机命令执行失败），设备保持开机。")
            return
        self._show_shutdown_status("已排定自动关机")
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
        self._show_shutdown_status("")

    def _show_shutdown_status(self, message: str) -> None:
        self.cancel_shutdown_button.setVisible(bool(message))
        self.log_cancel_shutdown_button.setVisible(bool(message))
        self.floating.set_status_notice(message)

    def _on_cancel_shutdown_clicked(self) -> None:
        if self._cancel_shutdown():
            self._notify("success", "自动关机已取消", "设备保持开机。")
        else:
            self._notify("error", "取消自动关机失败", "需手动撤销已排定的关机。")

    def _cancel_shutdown(self) -> bool:
        """撤销排定的关机；返回「现在确实没有待执行的关机」。

        没排定过就什么都不做（不执行 ``shutdown /a``），返回 ``True``。
        """
        # 还在等模拟器退出时也要能叫停：停掉轮询就不会再排定关机。
        # 但已经发出去的 quitall 收不回来 —— 模拟器仍会关，日志要说清楚。
        if self._shutdown_wait_timer is not None:
            if self._shutdown_wait_timer.isActive():
                self._append_log("已停止等待关机；已经发出的模拟器关闭请求收不回来。")
            self._shutdown_wait_timer.stop()
        if self.shutdown.scheduled:
            if not self.shutdown.cancel():
                self._append_log("取消自动关机未成功；需手动执行 shutdown /a。")
                return False
            self._append_log("已取消自动关机，设备保持开机。")
        if self._shutdown_timer is not None:
            self._shutdown_timer.stop()
        self._show_shutdown_status("")
        return True

    def _initial_size(self) -> tuple[int, int]:
        """尽量使用设计稿尺寸，同时适应当前工作区。"""
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None or available.isEmpty():
            return 1180, 800
        width = min(max(int(available.width() * 0.76), 880), 1440)
        height = min(max(int(available.height() * 0.86), 600), 900)
        return min(width, available.width()), min(height, available.height())

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        # The page scrolls vertically. Windows must not use the wrapped content's
        # preferred height as the top-level window's minimum tracking height.
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not getattr(self, "_route_grids", None):
            return
        compact = self.width() <= 1000
        columns = 2 if compact else 3
        if columns != self._route_columns:
            self._route_columns = columns
            self._set_route_view(self._list_view)
        nav_width = 140 if compact else 164
        navigation = self.navigationInterface
        navigation.setExpandWidth(nav_width)
        navigation.panel.setFixedWidth(nav_width)
        navigation.setFixedWidth(nav_width)
        for name in ("taskView", "logView", "toolsView", "aboutView"):
            item = navigation.widget(name)
            item.setFixedSize(nav_width - 22, 43)
            item.itemWidget.setFixedSize(nav_width - 22, 43)
        short = self.height() <= 720
        margin = 11 if compact else 17
        if hasattr(self, "task_banner"):
            self.task_banner.setVisible(not short)
        if hasattr(self, "plan_empty_art"):
            for layout in (self.task_content_layout, self.logs_content_layout, self.about_content_layout):
                layout.setContentsMargins(margin, 11 if short else 15, margin, 11 if short else 14)
            self.plan_card.setFixedHeight(108 if short else 146)
            self.plan_empty_art.setFixedSize(41 if short else 56, 41 if short else 56)
            self.detail_art.setFixedSize(42 if short else 58, 42 if short else 58)
            self.sidebar_mascot.setFixedHeight(74 if short else 94)
            self.sidebar_landscape.setFixedHeight(70 if short else 94)
            self.about_landscape.setFixedHeight(133 if short else 168)
            self._log_min_height = 162 if short else 250
            self._log_max_height = 205 if short else 285
            self._apply_log_height()

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
        if self.worker.running:
            # 当前任务继续运行，关闭主窗口时保留停止入口。
            event.ignore()
            self._append_log("窗口已收至运行横条，任务继续运行；退出前需先执行「安全停止」。")
            self._enter_floating_mode_again()
            return
        self.floating.hide_all()
        self.run_animation.stop()
        self._closing = True
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
            font = QFont(name)
            font.setPixelSize(13)
            app.setFont(font)
            return


def configure_qt() -> None:
    """必须在 QApplication 实例化**之前**调用（参考项目同位置）。"""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def apply_theme(app: QApplication) -> None:
    """Fluent 控件和原生窗口使用相同的深色背景。"""
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    app.setApplicationDisplayName(brand.APP_NAME)
    app.setWindowIcon(brand.app_icon())
    _apply_cjk_font(app)
    setTheme(Theme.DARK)
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
