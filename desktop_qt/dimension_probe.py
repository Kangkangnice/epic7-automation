"""「次元探查」页：在助手进程内直接跑内置第三方 chaos 流程。

这一页刻意不是一条路线：不进 ``MODE_SPECS``、不进勾选名单、不进每日任务链。
阶段 / 阵容 / 轮数都在这页填，点「开始」就跑；它认不出的内容会自己停下。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    TextEdit,
)

from auto_game_unified.desktop.chaos_bridge import LINEUPS, STAGES, ChaosBridge
from auto_game_unified.desktop_qt.style import SPIN_BOX_QSS

_REFRESH_MS = 200


class DimensionProbePage(QWidget):
    """``busy_reason`` 是「现在能不能开」的唯一判据；页面不去问 worker。"""

    def __init__(
        self,
        *,
        bridge: ChaosBridge,
        busy_reason: Callable[[], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._busy_reason = busy_reason

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)
        outer.addWidget(StrongBodyLabel("次元探查", self))
        outer.addWidget(self._build_card())
        outer.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(_REFRESH_MS)
        self._refresh()

    def _build_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        intro = BodyLabel(
            "次元探查（三层探查）在助手内直接执行，无需另开程序。"
            "本项不属于每日任务路线，不参与勾选与环境复检。",
            card,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("阶段", card))
        self.stage_combo = ComboBox(card)
        for stage in STAGES:
            self.stage_combo.addItem(f"第 {stage} 阶段", userData=stage)
        row.addWidget(self.stage_combo)
        row.addWidget(BodyLabel("阵容", card))
        self.lineup_combo = ComboBox(card)
        for lineup_id, label in LINEUPS:
            self.lineup_combo.addItem(label, userData=lineup_id)
        row.addWidget(self.lineup_combo)
        row.addWidget(BodyLabel("完成轮数", card))
        self.rounds_spin = QSpinBox(card)
        self.rounds_spin.setStyleSheet(SPIN_BOX_QSS)
        self.rounds_spin.setRange(1, 99)
        self.rounds_spin.setValue(1)
        self.rounds_spin.setFixedWidth(80)
        row.addWidget(self.rounds_spin)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        self.start_button = PrimaryPushButton("开始次元探查", card)
        self.start_button.clicked.connect(self._start)
        self.stop_button = PushButton("停止", card)
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.status_label = BodyLabel("未运行", card)
        layout.addWidget(self.status_label)

        self.log_text = TextEdit(card)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(110)
        self.log_text.document().setMaximumBlockCount(200)
        layout.addWidget(self.log_text)

        for text in (
            "注意：启动时将放弃未完成的探查并结算该局；执行前需确认无进行中的探查。",
            "执行期间将调整游戏窗口尺寸；助手下次启动时自动还原。",
            "执行期间不可关闭助手；关闭窗口等同于中途停止。",
            "阶段与阵容为内置固定配置；账号缺少对应英雄或目标阶段未解锁时，执行将停止。",
        ):
            note = CaptionLabel(text, card)
            note.setWordWrap(True)
            layout.addWidget(note)
        return card

    def _start(self) -> None:
        if self._bridge.running:
            return
        reason = self._busy_reason()
        if reason:
            self._warn("当前无法启动", reason)
            return
        error = self._bridge.start(
            self.stage_combo.currentData(),
            self.lineup_combo.currentData(),
            self.rounds_spin.value(),
        )
        if error:
            self._warn("无法启动", error)
            return
        self._refresh()

    def _stop(self) -> None:
        self._bridge.stop()
        self._refresh()

    def _refresh(self) -> None:
        running = self._bridge.running
        self.stage_combo.setEnabled(not running)
        self.lineup_combo.setEnabled(not running)
        self.rounds_spin.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for line in self._bridge.drain_lines():
            self.log_text.append(line)
        self.status_label.setText(self._bridge.status)

    def _warn(self, title: str, content: str) -> None:
        """InfoBar 的版本间签名有差异；挂了就写进状态行，别让提示把界面弄崩。"""
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
