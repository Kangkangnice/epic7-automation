"""路线设置：按一处声明生成控件，值交给 controller 统一清洗与保存。"""

from __future__ import annotations

from typing import Callable, Mapping

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
)

from auto_game_unified.desktop_qt.style import SPIN_BOX_QSS
from auto_game_unified.games.epic7.route_options import options_for


_ICON_SIZE = 44
_ICON_CACHE: dict[str, object] = {}


def _hero_icon(name: str):
    """图鉴头像缩略图；缺图返回 None。

    ⚠️ 名字来自图鉴页的 OCR，**不一定对**（同一名英雄在不同帧上可能读成别的字）。
    所以名单里必须把头像一起放出来 —— 用户是照着**长相**认人的，
    只看名字会把「名字读错的那一条」勾成别的英雄。
    """
    cached = _ICON_CACHE.get(name)
    if cached is not None:
        return cached
    from PySide6.QtGui import QIcon, QPixmap

    from auto_game_unified.games.epic7.hero_match import default_library_dir

    path = default_library_dir() / f"{name}.png"
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    icon = QIcon(
        pixmap.scaled(
            _ICON_SIZE,
            _ICON_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    _ICON_CACHE[name] = icon
    return icon


class HeroRosterDialog(QDialog):
    """英雄名单：头像 + 名字，搜索 + 勾选。

    ⚠️ 只列**能认出来**的名字：库里缺图的英雄勾了也不会生效（``HeroMatcher``
    会把它记进日志），与其让人勾一个不存在的名字，不如一开始就不列。

    ⚠️ 每一项都要带**头像**：名字是图鉴页 OCR 出来的，可能读错；用户认的是长相。
    """

    def __init__(self, parent, title: str, names: list[str], selected: list[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 560)
        layout = QVBoxLayout(self)
        self._search = LineEdit(self)
        self._search.setPlaceholderText("搜索英雄名")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._list = QListWidget(self)
        chosen = set(selected)
        for name in names:
            item = QListWidgetItem(name)
            icon = _hero_icon(name)
            if icon is not None:
                item.setIcon(icon)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked
            )
            item.setToolTip(name)
            self._list.addItem(item)
        self._list.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self._list.setSpacing(2)
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        clear = PushButton("清空", self)
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        row.addStretch(1)
        confirm = PrimaryPushButton("确定", self)
        confirm.clicked.connect(self.accept)
        row.addWidget(confirm)
        layout.addLayout(row)

        self._hint = CaptionLabel(f"共 {len(names)} 名可选", self)
        layout.addWidget(self._hint)

    def _apply_filter(self, text: str) -> None:
        keyword = text.strip()
        visible = 0
        for index in range(self._list.count()):
            item = self._list.item(index)
            hit = not keyword or keyword in item.text()
            item.setHidden(not hit)
            visible += int(hit)
        self._hint.setText(f"匹配 {visible} 名 / 共 {self._list.count()} 名")

    def _clear(self) -> None:
        for index in range(self._list.count()):
            self._list.item(index).setCheckState(Qt.CheckState.Unchecked)

    def selected_names(self) -> list[str]:
        result: list[str] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result


class RouteOptionsDialog(QDialog):
    """声明驱动：下拉与数字框按 ``RouteOption`` 生成，依赖未满足时置灰。"""

    def __init__(
        self,
        parent,
        mode: str,
        label: str,
        values: Mapping[str, object],
        on_accept: Callable[[str, dict[str, object]], None],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{label} · 设置")
        self.setMinimumWidth(440)
        self._mode = mode
        self._on_accept = on_accept
        self._options = options_for(mode)
        self._controls: dict[str, object] = {}
        self._roster_values: dict[str, list[str]] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        for option in self._options:
            if option.kind == "choice":
                control = ComboBox(self)
                for value, text in option.choices:
                    control.addItem(text, userData=value)
                index = control.findData(values.get(option.key, option.default))
                control.setCurrentIndex(max(0, index))
                control.currentIndexChanged.connect(self._sync_enabled)
            elif option.kind == "roster":
                control = PushButton("选择英雄", self)
                picked = list(values.get(option.key, ()) or ())
                control.clicked.connect(
                    lambda _checked=False, k=option.key, lbl=option.label, c=control: (
                        self._edit_roster(k, lbl, c)
                    )
                )
                self._roster_values[option.key] = picked
                self._refresh_roster_label(option.key, control)
            else:
                control = QSpinBox(self)
                control.setStyleSheet(SPIN_BOX_QSS)
                control.setRange(option.minimum, option.maximum)
                control.setValue(int(values.get(option.key, option.default) or 0))
            self._controls[option.key] = control
            form.addRow(BodyLabel(option.label, self), control)
            note = CaptionLabel(option.note, self)
            note.setWordWrap(True)
            form.addRow(QLabel("", self), note)
        layout.addLayout(form)
        confirm = PrimaryPushButton("保存", self)
        confirm.clicked.connect(self._accept)
        layout.addWidget(confirm)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        for option in self._options:
            if option.depends_on is None:
                continue
            key, expected = option.depends_on
            current = self._controls[key].currentData()
            self._controls[option.key].setEnabled(current == expected)

    def _edit_roster(self, key: str, label: str, control) -> None:
        """打开名单选择；确定后只更新这一个键的取值。"""
        from auto_game_unified.games.epic7.hero_match import (
            default_library_dir,
            library_names,
        )

        names = library_names(default_library_dir())
        if not names:
            control.setText("图鉴库缺失")
            control.setEnabled(False)
            return
        dialog = HeroRosterDialog(self, label, names, self._roster_values[key])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            picked = dialog.selected_names()
            self._roster_values[key] = picked
            self._refresh_roster_label(key, control)
            self._drop_overlaps(key, picked)

    def _drop_overlaps(self, key: str, picked: list[str]) -> None:
        """同一名英雄只留在一边：勾进这份名单，就从另一份名单里移出。

        ⚠️ 不这样做的话，同一英雄会同时给黑名单和白名单各加 1，数量永远相等，
        白名单永远压不过黑名单（除非把「相等」改成白优先），等于白勾。
        """
        chosen = set(picked)
        for option in self._options:
            if option.kind != "roster" or option.key == key:
                continue
            kept = [name for name in self._roster_values[option.key] if name not in chosen]
            if len(kept) != len(self._roster_values[option.key]):
                self._roster_values[option.key] = kept
                self._refresh_roster_label(option.key, self._controls[option.key])

    def _refresh_roster_label(self, key: str, control) -> None:
        picked = self._roster_values[key]
        control.setText(f"选择英雄（已选 {len(picked)}）" if picked else "选择英雄")

    def _collect(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for option in self._options:
            if option.kind == "roster":
                result[option.key] = list(self._roster_values[option.key])
                continue
            control = self._controls[option.key]
            result[option.key] = (
                control.currentData()
                if option.kind == "choice"
                else control.value()
            )
        return result

    def _accept(self) -> None:
        self._on_accept(self._mode, self._collect())
        self.accept()
