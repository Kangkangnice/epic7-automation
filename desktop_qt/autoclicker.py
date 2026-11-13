"""「实用工具 · 连点器」页。

业务逻辑全在 ``core/autoclicker.py``（可单测、不依赖 Qt），这里只做三件事：
把坐标和间隔收进来、把启停按钮接上、把「已经点了多少次」显示出来。

⚠️ 两个刻意的取舍：

* **开始必须点按钮，急停键只能停不能开**。如果按 P 也能启动，用户在别的页面误按
  一下就会开始在屏幕上乱点；而停止必须有键盘出口，因为运行期间鼠标被按在
  目标点上、点不到按钮。这条非对称是安全设计，不是漏做。
* **没有「点多少次就停」**。用户的原话是「一直点」，加次数上限只是多一个要
  解释的输入框；要停就按 P 或点停止。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from auto_game_unified.core.autoclicker import (
    MAX_INTERVAL_MS,
    MIN_INTERVAL_MS,
    AutoClicker,
    ClickPlan,
    cursor_position,
)
from auto_game_unified.desktop_qt.style import SPIN_BOX_QSS

# 取点倒计时：给用户时间把鼠标移到目标上。3 秒是「来得及、又不至于等烦」的值。
PICK_COUNTDOWN_SECONDS = 3
# 状态刷新间隔。连点次数是给人看个大概，200 毫秒够用，也不占 CPU。
_REFRESH_MS = 200
# 坐标框的范围。副屏可能在主屏左边/上边（负数），所以要允许负值；
# 上下限给得比任何真实桌面都宽，具体越界由系统自己钳制。
_COORD_LIMIT = 100_000
_DEFAULT_INTERVAL_MS = 500


class AutoClickerPage(QWidget):
    """连点器页面。

    ``busy_reason`` 是「现在能不能开」的唯一判据：返回非空字符串就拒绝启动，
    那句话直接显示给用户。页面不去问 worker —— 两套点击同时发会互相干扰，
    但「谁在跑」这件事只有主窗口知道。
    """

    def __init__(
        self,
        *,
        clicker: AutoClicker,
        busy_reason: Callable[[], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._clicker = clicker
        self._busy_reason = busy_reason
        # 没取过点就不许开始：默认坐标是 (0, 0)，也就是屏幕左上角，
        # 手一抖点下去就会去点开始菜单。
        self._has_position = False
        self._countdown = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)
        outer.addWidget(StrongBodyLabel("实用工具 · 连点器", self))
        outer.addWidget(self._build_target_card())
        outer.addWidget(self._build_interval_card())
        outer.addWidget(self._build_control_card())
        outer.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(_REFRESH_MS)
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.timeout.connect(self._tick_countdown)

        self._refresh()

    # ── 界面 ────────────────────────────────────────────────────────────────

    def _make_spin(self, low: int, high: int, value: int, *, width: int) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setStyleSheet(SPIN_BOX_QSS)
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setFixedWidth(width)
        return spin

    def _build_target_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("点哪里", card))
        hint = CaptionLabel(
            "将光标移至目标位置后执行「拾取位置」；倒计时结束时记录该坐标。",
            card,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel("X", card))
        self.x_spin = self._make_spin(-_COORD_LIMIT, _COORD_LIMIT, 0, width=110)
        self.x_spin.valueChanged.connect(self._on_position_edited)
        row.addWidget(self.x_spin)
        row.addSpacing(8)
        row.addWidget(BodyLabel("Y", card))
        self.y_spin = self._make_spin(-_COORD_LIMIT, _COORD_LIMIT, 0, width=110)
        self.y_spin.valueChanged.connect(self._on_position_edited)
        row.addWidget(self.y_spin)
        row.addSpacing(12)
        self.pick_button = PushButton("拾取位置", card)
        self.pick_button.clicked.connect(self._begin_pick)
        row.addWidget(self.pick_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.position_note = CaptionLabel("尚未取点：需执行「拾取位置」或填写坐标。", card)
        self.position_note.setWordWrap(True)
        layout.addWidget(self.position_note)
        return card

    def _build_interval_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("多久点一次", card))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel("间隔", card))
        self.interval_spin = self._make_spin(
            MIN_INTERVAL_MS, MAX_INTERVAL_MS, _DEFAULT_INTERVAL_MS, width=140
        )
        self.interval_spin.setSingleStep(10)
        self.interval_spin.valueChanged.connect(self._on_interval_edited)
        row.addWidget(self.interval_spin)
        row.addWidget(BodyLabel("毫秒", card))
        row.addStretch(1)
        layout.addLayout(row)

        self.interval_note = CaptionLabel("", card)
        self.interval_note.setWordWrap(True)
        layout.addWidget(self.interval_note)
        self._on_interval_edited(self.interval_spin.value())
        return card

    def _build_control_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.start_button = PrimaryPushButton("开始连点", card)
        self.start_button.clicked.connect(self._start)
        row.addWidget(self.start_button)
        self.stop_button = PushButton("停止", card)
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.status_label = BodyLabel("已停止", card)
        layout.addWidget(self.status_label)

        note = CaptionLabel(
            "执行期间按 P 可立即停止，该方式不依赖鼠标操作。"
            "连点将持续执行直至手动停止；执行前需确认目标位置。",
            card,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return card

    # ── 取点 ────────────────────────────────────────────────────────────────

    def _begin_pick(self) -> None:
        if self._clicker.running or self._countdown > 0:
            return
        self._countdown = PICK_COUNTDOWN_SECONDS
        self.pick_button.setEnabled(False)
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self._countdown <= 0:
            self._finish_pick()
            return
        self.pick_button.setText(f"{self._countdown} 秒后取点…")
        self._countdown -= 1
        self._pick_timer.start(1000)

    def _finish_pick(self) -> None:
        self.pick_button.setText("拾取位置")
        try:
            x, y = cursor_position()
        except Exception as error:  # noqa: BLE001 —— 取点失败只是这一次没取到
            self.position_note.setText(f"取点失败：{error}")
            self._refresh()
            return
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        self._has_position = True
        self.position_note.setText(f"已取点：（{x}, {y}）")
        self._refresh()

    def _on_position_edited(self, _value: int) -> None:
        """手改坐标也算「取过点」——否则用户明知坐标、却还得空等一下倒计时。"""
        if not self._has_position:
            self._has_position = True
            self.position_note.setText("已手动填写坐标。")
        self._refresh()

    def _on_interval_edited(self, value: int) -> None:
        self.interval_note.setText(
            f"执行间隔 {value / 1000:.2f} 秒（约每秒 {1000 / value:.1f} 次）。"
            f"最小间隔 {MIN_INTERVAL_MS} 毫秒。"
        )

    # ── 启停 ────────────────────────────────────────────────────────────────

    def _start(self) -> None:
        if self._clicker.running:
            return
        reason = self._busy_reason()
        if reason:
            self._warn("当前无法启动连点器", reason)
            return
        if not self._has_position:
            self._warn("尚未取点", "需执行「拾取位置」或填写 X / Y 坐标。")
            return
        try:
            plan = ClickPlan(
                x=self.x_spin.value(),
                y=self.y_spin.value(),
                interval_ms=self.interval_spin.value(),
            )
            self._clicker.start(plan)
        except Exception as error:  # noqa: BLE001 —— 报进状态行，别静默失败
            self._warn("无法启动连点", str(error))
            return
        self.status_label.setText("连点执行中 · 已执行 0 次（按 P 停止）")
        self._refresh()

    def _stop(self) -> None:
        self._clicker.stop()
        self.status_label.setText("正在停止……")

    # ── 状态 ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        running = self._clicker.running
        self.x_spin.setEnabled(not running)
        self.y_spin.setEnabled(not running)
        self.interval_spin.setEnabled(not running)
        self.start_button.setEnabled(not running and self._has_position)
        self.stop_button.setEnabled(running)
        # 倒计时期间按钮由倒计时自己管，别在这里抢回来。
        if self._countdown == 0:
            self.pick_button.setEnabled(not running)
        if running:
            self.status_label.setText(
                f"连点执行中 · 已执行 {self._clicker.count} 次（按 P 停止）"
            )
        elif self._clicker.last_error:
            self.status_label.setText(f"已停止：{self._clicker.last_error}")
        else:
            self.status_label.setText("已停止")

    def _warn(self, title: str, content: str) -> None:
        """InfoBar 的版本间签名有差异；挂了就写进状态行，绝不让提示把界面弄崩。"""
        try:
            InfoBar.warning(
                title=title,
                content=content,
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP,
            )
        except Exception:  # noqa: BLE001
            self.status_label.setText(f"{title}：{content}")
