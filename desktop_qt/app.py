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

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
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
    PC_READY_ROUTES,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    STARTUP_HINTS,
    group_description,
    grouped_routes,
    route_by_name,
    routes_in_group,
    visible_backends,
)
from auto_game_unified.desktop.controller import DesktopController
from auto_game_unified.desktop.diagnostics import export_diagnostics
from auto_game_unified.desktop.onboarding import has_consent, record_consent
from auto_game_unified.desktop.preflight import (
    run_preflight,
    template_root_for_backend,
    validate_start_plan,
)
from auto_game_unified.desktop.update_check import check_for_update
from auto_game_unified.desktop.worker import WorkerController
from auto_game_unified.desktop_qt.autoclicker import AutoClickerPage
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
        # 停止兜底的计时器（见 _start_stop_watchdog）。第一次点停止时才建。
        self._stop_timer: QTimer | None = None
        self._stop_deadline = 0.0

        previous = session.load(self._session_path)
        if previous is not None:
            controller.apply_session(previous)

        self._build_task_page()
        self._build_log_page()
        self._build_tools_page()
        self._build_about_page()
        self._sync_from_controller()
        self._show_group_detail(grouped_routes()[0][0])

        self.setWindowTitle(f"{PRODUCT_NAME}  {PRODUCT_VERSION}")
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

    # ── 构建界面 ────────────────────────────────────────────────────────────

    def _build_task_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("taskView")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_status_card())
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_route_scroll(), 3)
        middle.addWidget(self._build_detail_card(), 2)
        outer.addLayout(middle, 1)
        outer.addLayout(self._build_action_bar())
        self.addSubInterface(page, FluentIcon.HOME, "每日任务")

    def _build_status_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("运行环境", card))

        self.status_label = BodyLabel("尚未检测。请点击「检测环境」。", card)
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
        row.addWidget(BodyLabel("窗口后端", card))
        self.backend_combo = ComboBox(card)
        for backend in visible_backends():
            self.backend_combo.addItem(BACKEND_LABELS[backend], userData=backend)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        row.addWidget(self.backend_combo)

        row.addSpacing(16)
        row.addWidget(BodyLabel("不占用前台", card))
        self.background_switch = SwitchButton(card)
        self.background_switch.checkedChanged.connect(self._on_background_changed)
        row.addWidget(self.background_switch)
        row.addStretch(1)

        self.check_button = PushButton(FluentIcon.SYNC, "检测环境", card)
        self.check_button.clicked.connect(self._on_check_clicked)
        row.addWidget(self.check_button)
        layout.addLayout(row)
        return card

    def _build_route_scroll(self) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget(scroll)
        holder.setObjectName("routeHolder")
        column = QVBoxLayout(holder)
        column.setContentsMargins(4, 4, 12, 4)
        column.setSpacing(12)

        for group, routes in grouped_routes():
            card = CardWidget(holder)
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
                spin.setFixedWidth(112)
                # 次数固定 = 标准「禁用」态。我们自己的 QSS 把禁用文字写成
                # #5B5B5B on #F3F4F6（6.2:1），数字照样看得见；
                # 不用 readOnly + NoButtons —— 那个组合在 Qt 6.12 下会让文字消失。
                spin.setEnabled(route.cycles_editable)
                spin.valueChanged.connect(
                    lambda value, m=route.mode: self._on_cycles_changed(m, value)
                )
                self._route_spins[route.mode] = spin
                line.addWidget(spin)
                card_layout.addLayout(line)

                box.clicked.connect(
                    lambda _checked=False, m=route.mode: self._show_route_detail(m)
                )

            column.addWidget(card)
        column.addStretch(1)
        scroll.setWidget(holder)
        return scroll

    def _build_detail_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.detail_title = StrongBodyLabel("", card)
        layout.addWidget(self.detail_title)
        self.detail_body = BodyLabel("", card)
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignTop)
        layout.addWidget(self.detail_body, 1)
        self.pc_note = CaptionLabel("", card)
        self.pc_note.setWordWrap(True)
        layout.addWidget(self.pc_note)
        return card

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.run_state_label = CaptionLabel("准备就绪", self)
        bar.addWidget(self.run_state_label)
        bar.addStretch(1)
        self.export_button = PushButton(FluentIcon.SAVE, "导出诊断包", self)
        self.export_button.clicked.connect(self._on_export_clicked)
        bar.addWidget(self.export_button)
        self.stop_button = PushButton(FluentIcon.PAUSE, "安全停止", self)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        bar.addWidget(self.stop_button)
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "开始任务", self)
        self.start_button.clicked.connect(self._on_start_clicked)
        bar.addWidget(self.start_button)
        return bar

    def _build_log_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("logView")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel("实时日志", page))
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

    def _build_about_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("aboutView")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel(PRODUCT_NAME, page))
        layout.addWidget(CaptionLabel(f"版本 {PRODUCT_VERSION}", page))
        about = BodyLabel(
            "基于窗口截图与 OpenCV 模板匹配的 PVE 自动化。"
            "只在认出预期页面时点击；陌生页面、黑屏、遮挡、转场超时一律留证停止。\n\n"
            "默认干跑，实跑必须显式确认；危险按钮与付费购买路径在代码里被禁止。",
            page,
        )
        about.setWordWrap(True)
        layout.addWidget(about)
        note = BodyLabel(
            "「每日任务」按勾选顺序依次跑选中的路线；「实用工具」里是与路线无关的"
            "小工具（目前是固定点连点器）。两者不能同时开 —— 两套点击会互相干扰。",
            page,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
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
        self.check_button.setEnabled(not running and not self._checking)
        self.backend_combo.setEnabled(not running)
        self.background_switch.setEnabled(
            not running and self.controller.selected_backend == "pc"
        )
        for box in self._route_checks.values():
            box.setEnabled(not running)
        for mode, spin in self._route_spins.items():
            spin.setEnabled(not running and route_by_name(mode).cycles_editable)
        self.run_state_label.setText(
            "正在运行…" if running else
            f"已勾选 {len(self.controller.selection)} 条 · "
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
                "想重新阅读请点「关于」页里的「重新查看使用须知」。"
            )
            return
        self.consented = True
        if not record_consent(self.data_root):
            # 落盘失败**照样放行**：用户刚刚确实点了同意，写不进去是这个目录的问题。
            self._append_log(
                f"提示：无法保存确认记录（{self.data_root} 不可写），下次启动会再问一次。"
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
            f'<a href="{info.url}">点这里查看</a>'
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

    def _on_backend_changed(self, index: int) -> None:
        if self._suspend_events or index < 0:
            return
        backend = self.backend_combo.itemData(index)
        try:
            self.controller.select_backend(backend)
        except Exception as error:
            self._notify("error", "无法切换窗口后端", str(error))
            self._sync_from_controller()
            return
        self.status_label.setText("尚未检测。请点击「检测环境」。")
        self._append_log(f"窗口后端已切换为 {BACKEND_LABELS.get(backend, backend)}。")
        self._sync_from_controller()
        self._save_session()

    def _on_background_changed(self, checked: bool) -> None:
        if self._suspend_events:
            return
        mode = PC_INPUT_BACKGROUND if checked else PC_INPUT_FOREGROUND
        try:
            self.controller.select_pc_input_mode(mode)
        except Exception as error:
            self._notify("error", "无法切换输入通道", str(error))
            self._sync_from_controller()
            return
        if checked:
            self._append_log(
                "输入通道=不占用前台：点击走后台，不抢前台；"
                "滑动没法后台做（Raw Input 只认前台），含滑动的路线会短暂把窗口切到前面，"
                "滑完立刻把前台还原；Esc 返回会自动改走前台。"
            )
        else:
            self._append_log("输入通道=抢前台。")
        self._sync_from_controller()
        self._save_session()

    def _on_check_clicked(self) -> None:
        if self._checking or self.worker.running:
            return
        self._checking = True
        self.status_label.setText("正在检测环境……")
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
            self.status_label.setText(f"检测失败：{result}")
            self._notify("error", "环境检测失败", str(result))
            self._refresh_actions()
            return
        self.controller.apply_preflight(result)
        self.status_label.setText(result.message)
        self._append_log(f"环境检测：{result.message}")
        if result.warning:
            self._notify("warning", "能跑，但可能点不动", result.warning)
        else:
            self._notify("success", "检测通过", result.message)
        self._refresh_actions()

    def _on_start_clicked(self) -> None:
        if self.autoclicker.running:
            self._notify(
                "warning",
                "连点器还开着",
                "先到「实用工具」里停止连点，再开始任务 —— 两套点击同时发会互相干扰。",
            )
            return
        if not self.consented:
            # 按钮本来就该是灰的（见 _refresh_actions）。走到这里只可能是
            # 事件顺序异常，仍然守住这条线。
            self._notify("warning", "使用须知", "请先阅读并同意《使用须知》再开始。")
            return
        if not self.controller.can_start:
            self._notify("warning", "请先完成环境检测", "点右上角「检测环境」后再开始。")
            return
        plan = self.controller.plan()
        if not plan:
            self._notify("warning", "还没有勾选路线", "至少勾一条再开始。")
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
            self.status_label.setText(f"复检失败：{error}")
            self._notify("error", "未能开始", str(error))
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
        self._refresh_actions()

    def _on_stop_clicked(self) -> None:
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
        # 所以这里必须自己把按钮状态收回来，不能等 finished 事件。
        self._refresh_actions()

    def _on_export_clicked(self) -> None:
        selection = self.controller.selection
        if not selection:
            self._notify("warning", "没有可导出的路线", "先勾一条路线。")
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
        self.detail_title.setText(f"{group} · 整组说明")
        self.detail_body.setText(group_description(group))
        self._update_pc_note()

    def _show_route_detail(self, mode: str) -> None:
        route = route_by_name(mode)
        self.detail_title.setText(route.label)
        self.detail_body.setText(route.description)
        self._update_pc_note(mode)

    def _update_pc_note(self, mode: str | None = None) -> None:
        if self.controller.selected_backend != "pc":
            self.pc_note.setText("")
            return
        if mode is not None and mode not in PC_READY_ROUTES:
            self.pc_note.setText(
                "⚠️ 这条路线还没在 PC 客户端上通过验收，界面会拦下它；请切回模拟器。"
            )
        else:
            self.pc_note.setText("PC 客户端：界面只放行已通过验收的路线。")

    def _append_log(self, line: str) -> None:
        # 行数上限由 QTextDocument.setMaximumBlockCount(2000) 兜住，这里只管追加。
        self.log_text.append(line)

    def _poll_worker(self) -> None:
        for event in self.worker.drain_events():
            if event.kind == "log":
                self._append_log(event.message)
            elif event.kind == "started":
                self._append_log("自动化已启动。")
            elif event.kind == "stopping":
                self._append_log("正在安全停止……")
            elif event.kind == "finished":
                self._append_log(f"运行结束（退出码 {event.exit_code}）。")
                self._save_last_run(event.exit_code)
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
            ),
        )

    def _save_last_run(self, exit_code: int | None) -> None:
        from datetime import datetime

        previous = session.load(self._session_path) or session.SessionState()
        summary = next(
            (
                line.split("：", 1)[1].strip()
                for line in reversed(self.worker.recent_output)
                if line.startswith("每日任务汇总：")
            ),
            None,
        )
        if summary is None:
            return
        session.save(
            self._session_path,
            replace(
                previous,
                last_run=session.LastRun(
                    at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    summary=summary,
                    exit_code=exit_code,
                ),
            ),
        )

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


# 参考项目「一条龙」的浅色口径，三处源码交叉确认：
#   src/zzz_od/gui/app.py::main            —— 启动前设 HighDPI PassThrough、setTheme(配置主题)
#   src/one_dragon_qt/services/theme_manager.py —— 默认主题色 (0, 120, 215) = #0078D7
#   src/one_dragon_qt/windows/window.py::PhosWindow —— 浅色窗口底 QColor(248, 249, 252)
# 默认主题是 AUTO（跟随系统）；用户明确要「通体白的、浅色模式」，这里钉死 LIGHT。
THEME_COLOR = "#0078D7"


def configure_qt() -> None:
    """必须在 QApplication 实例化**之前**调用（参考项目同位置）。"""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def apply_theme(app: QApplication) -> None:
    """统一浅色 Fluent 主题：真实界面和预览脚本**只能**走这里。

    ⚠️ 不要再动 QPalette / app.setStyleSheet / 控件 lineEdit 的颜色：
    之前为了离屏预览补过一层「深底白字」，真实 Windows 下 qfluentwidgets 的
    QSS 与原生 Qt 控件默认配色打架，出现白字落在深色/浅色框里看不见。
    浅色主题 + 零覆盖，让 qfluentwidgets 自己把每个控件画成白底黑字，才不会漂。
    """
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    _apply_cjk_font(app)
    setTheme(Theme.LIGHT)
    try:
        setThemeColor(THEME_COLOR)
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
    try:
        window.setMicaEffectEnabled(False)
    except Exception:
        pass
    window.show()
    return app.exec()
