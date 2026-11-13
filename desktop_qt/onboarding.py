"""首次启动的风险确认（Qt 版）。

## 为什么这里只有「画一遍」

条款文字与「同不同意」的落盘逻辑都在 ``desktop/onboarding.py`` —— 那是产品条款，
不是外观。2026-11-09 删掉 Tk 界面时，只把**绘制**搬到这里，条款一个字都没动：
``RISK_POINTS`` / ``SETUP_POINTS`` 仍是唯一文案来源，别在本文件里另抄一份。

那条文件里的四条规矩在这里同样成立，尤其是这两条：

* **「开始使用」本身就是同意**，没有「我已阅读」勾选框，按钮也不会因为没勾而置灰
  （2026-10-20 用户明确要求，别再把这个勾选框加回来）。
* **关窗 / 点「暂不使用」都等于不同意**，调用方据此保持「开始任务」禁用。
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, StrongBodyLabel

from auto_game_unified.desktop.onboarding import DIALOG_WIDTH, RISK_POINTS, SETUP_POINTS

# 宽度（**逻辑像素**）只有一处来源 —— 跟条款一起放在 desktop/onboarding.py，
# 测试也照着那个数守「别再把窗口调宽」。
MIN_WIDTH = DIALOG_WIDTH


class ConsentDialog(QDialog):
    """使用须知对话框。**不做任何判定**（不读盘、不写盘）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("使用须知")
        self.setModal(True)
        self.setMinimumWidth(MIN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel("使用前须知", self))

        for point in RISK_POINTS:
            label = BodyLabel(point, self)
            label.setWordWrap(True)
            layout.addWidget(label)

        layout.addSpacing(4)
        layout.addWidget(StrongBodyLabel("运行条件", self))
        for index, point in enumerate(SETUP_POINTS, start=1):
            label = BodyLabel(f"{index}. {point}", self)
            label.setWordWrap(True)
            layout.addWidget(label)

        layout.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch(1)
        self.decline_button = PushButton("暂不使用", self)
        self.decline_button.clicked.connect(self.reject)
        row.addWidget(self.decline_button)
        self.accept_button = PrimaryPushButton("开始使用", self)
        self.accept_button.clicked.connect(self.accept)
        row.addWidget(self.accept_button)
        layout.addLayout(row)


def prompt_consent(parent: QWidget | None = None) -> bool:
    """弹出一次确认，用户点了「开始使用」才返回 ``True``。"""
    return ConsentDialog(parent).exec() == QDialog.DialogCode.Accepted
