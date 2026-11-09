"""Qt 界面的样式常量。

⚠️ 这里**只放控件级的 QSS**，不放全局 stylesheet：2026-11-08 那次「深底白字」
事故就是全局覆盖和 qfluentwidgets 的 QSS 打架造成的（详见 ``apply_theme``）。
每个控件的样式都必须是局部的、只作用在它自己身上。
"""

from __future__ import annotations

# 次数 / 坐标这类数字输入框用原生 QSpinBox，而不是 qfluentwidgets 的 SpinBox：
# 后者在 PySide6 6.12 下把内部 QLineEdit 压成 1px 宽（真机实测
# geometry=(0, 1, 1, 31)），文字存在却被整个裁掉；加宽、改只读都无效。
# 这里只给原生 QSpinBox 写浅色令牌，不设全局 stylesheet。
# 对比度实测（前景/背景，WCAG 2.1）：
#   #1A1A1A / #FFFFFF ≈ 17.4:1   正文（要求 ≥4.5:1）
#   #5B5B5B / #F3F4F6 ≈ 6.2:1   禁用态文字（禁用可豁免，仍做够）
#   #8A8A8A / #FFFFFF ≈ 3.5:1   非文本边框（要求 ≥3:1）
#   #0078D7 / #FFFFFF ≈ 4.6:1   聚焦描边 / 主色
SPIN_BOX_QSS = """
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
