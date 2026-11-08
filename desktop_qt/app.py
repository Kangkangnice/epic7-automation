"""Qt / Fluent 版桌面界面（可选入口，不替换现有 Tk 界面）。

启动：``python -m auto_game_unified.desktop_qt``
依赖：``python -m pip install -r requirements-qt.txt``

## 为什么要先解耦

``DesktopController`` 是「勾了哪几条、每条几次、用哪个后端、能不能开跑」这套
**与界面无关的业务状态**。它原来住在 ``desktop/app.py`` 里，而那个文件一开头就
import tkinter —— Qt 侧想复用它就得把整个 Tk 拉进来（有些环境根本没装 tkinter）。
2026-11-08 把它搬到 ``desktop/controller.py`` 后，两套界面读的是**同一个类**，
不会出现「换了一套皮，勾选顺序 / 启动准入规则跟着漂移」。

## 本版对齐了什么、还差什么

已对齐：四分组勾选（含整组勾选与活动互斥）、序号即执行顺序、次数输入与只读路线、
后端切换、PC「不占用前台」开关、环境检测、开始前复检（含逐条模板校验）、
安全停止、实时日志轮询、会话存档、窗口几何记忆、诊断包导出。

⚠️ 刻意**没做**（落地切默认之前必须补）：首次使用须知弹窗、更新检查、
多套命名配置（profiles）、打包 spec 与安装包图标。这四样都在 Tk 版里有实现，
切默认入口时逐项对齐，别凭本文件推断「已经有了」。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
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
from auto_game_unified.desktop.preflight import (
    run_preflight,
    template_root_for_backend,
    validate_route_templates,
)
from auto_game_unified.desktop.worker import WorkerController

ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = ROOT.parent
TEMPLATE_ROOT = ROOT / "games" / "epic7" / "templates"
DATA_ROOT = data_root()
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

# 次数输入框改用原生 QSpinBox，而不是 qfluentwidgets 的 SpinBox：
# 后者在 PySide6 6.12 下把内部 QLineEdit 压成 1px 宽（真机实测
# geometry=(0, 1, 1, 31)），文字存在却被整个裁掉；加宽、改只读都无效。
# 这里只给这一个原生控件写浅色令牌，**不设全局 stylesheet** ——
# 上一轮「深底白字」事故就是全局覆盖和组件 QSS 打架造成的。
# 对比度实测（前景/背景，WCAG 2.1）：
#   #1A1A1A / #FFFFFF ≈ 17.4:1   正文（要求 ≥4.5:1）
#   #5B5B5B / #F3F4F6 ≈ 6.2:1   禁用态文字（禁用可豁免，仍做够）
#   #8A8A8A / #FFFFFF ≈ 3.5:1   非文本边框（要求 ≥3:1）
#   #0078D7 / #FFFFFF ≈ 4.6:1   聚焦描边 / 主色
_SPIN_BOX_QSS = """
QSpinBox {
    color: #1A1A1A;
    background-color: #FFFFFF;
    border: 1px solid #8A8A8A;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 14px;
}
QSpinBox:focus { border: 2px solid #0078D7; }
QSpinBox:disabled { color: #5B5B5B; background-color: #F3F4F6; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 20px; border: none; background: transparent;
}
"""


def _position_prefix(index: int) -> str:
    """与 Tk 版 ``DesktopApp._position_prefix`` 同一套展示规则（圈码不够退阿拉伯数字）。"""
    return _CIRCLED[index] if index < len(_CIRCLED) else f"{index + 1}."


class _Bridge(QObject):
    """后台线程 → 主线程的唯一通道（PySide6 跨线程 emit 自动走 queued connection）。"""

    check_done = Signal(object)          # PreflightReport 或 Exception
    start_done = Signal(object, object)  # (PreflightReport 或 None, Exception 或 None)


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
        self._route_checks: dict[str, CheckBox] = {}
        self._route_spins: dict[str, QSpinBox] = {}
        self._group_checks: dict[str, CheckBox] = {}
        self._suspend_events = False
        self._checking = False
        self._last_running = False

        previous = session.load(self._session_path)
        if previous is not None:
            controller.apply_session(previous)

        self._build_task_page()
        self._build_log_page()
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

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(BodyLabel("窗口后端", card))
        self.backend_combo = ComboBox(card)
        for backend in visible_backends():
            self.backend_combo.addItem(BACKEND_LABELS[backend], userData=backend)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        row.addWidget(self.backend_combo)

        row.addSpacing(16)
        row.addWidget(BodyLabel("不占用前台（实验）", card))
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
                spin.setStyleSheet(_SPIN_BOX_QSS)
                spin.setRange(route.min_cycles, 99)
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

    def _build_about_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("aboutView")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel(PRODUCT_NAME, page))
        layout.addWidget(CaptionLabel(f"版本 {PRODUCT_VERSION} · Qt / Fluent 预览版", page))
        about = BodyLabel(
            "基于窗口截图与 OpenCV 模板匹配的 PVE 自动化。"
            "只在认出预期页面时点击；陌生页面、黑屏、遮挡、转场超时一律留证停止。\n\n"
            "默认干跑，实跑必须显式确认；危险按钮与付费购买路径在代码里被禁止。",
            page,
        )
        about.setWordWrap(True)
        layout.addWidget(about)
        note = BodyLabel(
            "⚠️ 本入口仍是预览版：使用须知弹窗、更新检查、多套配置与打包接入尚未对齐 Tk 版。"
            "日常使用请继续用原桌面入口；确认外观后再把它设为默认。",
            page,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.addSubInterface(
            page, FluentIcon.INFO, "关于", NavigationItemPosition.BOTTOM
        )

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
            self.controller.can_start and self.controller.ready and not self._checking
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
                "输入通道=不占用前台（实验）：启用前请先用 "
                "tools/probe_background_input.py 在本机实测；"
                "滑动没法后台做（Raw Input 只认前台），含滑动的路线会短暂把窗口切到前面，"
                "滑完立刻把前台还原；Esc 返回会自动改走前台。"
            )
        else:
            self._append_log("输入通道=抢前台（默认）。")
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
                    for mode, _ in plan:
                        try:
                            validate_route_templates(mode, template_root)
                        except Exception as caught:
                            # 与 Tk 版对齐：报清是哪条路线，别只甩一个裸路径给用户。
                            error = RuntimeError(
                                f"{route_by_name(mode).label}：{caught}"
                            )
                            break
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
            modes = "、".join(route_by_name(mode).label for mode, _ in self.controller.plan())
            self._append_log(f"已启动：{modes}")
        self._refresh_actions()

    def _on_stop_clicked(self) -> None:
        self.controller.stop()
        self._append_log("已发出安全停止请求。")

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
            # Tk 版与 Qt 版共用同一份会话文件，老界面存下来的可能是最大化 /
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
