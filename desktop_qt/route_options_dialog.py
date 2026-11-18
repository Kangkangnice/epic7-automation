"""路线设置：按一处声明生成控件，值交给 controller 统一清洗与保存。

视觉口径与主界面一致（2026-11-17 用户要求）：设置项逐条落在 ``CardWidget`` 里，
标题用 ``StrongBodyLabel``、说明用 ``CaptionLabel``、底部右侧一颗主色按钮；
不另造一套字号与描边。
"""

from __future__ import annotations

from typing import Callable, Mapping

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PillPushButton,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from auto_game_unified.desktop_qt.style import SPIN_BOX_QSS
from auto_game_unified.games.epic7.hero_catalog import (
    ELEMENTS,
    JOBS,
    STARS,
    filter_names,
    hero_meta,
    unclassified_count,
)
from auto_game_unified.games.epic7.route_options import options_for


_TILE_WIDTH = 104
_TILE_HEIGHT = 140
_AVATAR_SIZE = 88
# 头像外框比画面大 8 px：圆环画在格子上、透过头像四角的透明区显出来，
# 若外框与画面同尺寸，圆环在正上/正下这些位置会被 QLabel 自己的矩形裁掉。
_AVATAR_BOX = 96
_COLUMNS = 5
# 五列网格的实宽 + 竖直滚动条 + 内外两层边距。对话框按这个宽度开，
# 否则右列会被卷进横向滚动条里（旧版 560 宽就切掉了第五列）。
_ROSTER_WIDTH = (
    _TILE_WIDTH * _COLUMNS + 6 * (_COLUMNS - 1)  # 网格 548
    + 4  # 网格内边距
    + 16  # 网格卡片内边距
    + 32  # 对话框内边距
    + 12  # 竖直滚动条
    + 4  # 余量
)

# 头像按内切圆显示：源图是方形，四角带界面边框或截图底纹，直接摆出来边角很毛。
_RING_NORMAL = "#E1E3E6"
_RING_CHOSEN = "#0078D7"

# 对话框底色。默认的 QDialog 是系统灰（#F3F3F3），与主界面的白色底不一致，
# 摆在一起会明显像另一套界面。只作用于本对话框自身，不设全局样式。
_DIALOG_QSS = "QDialog { background-color: #FFFFFF; }"

_PIXMAP_CACHE: dict[str, QPixmap | None] = {}


def _hero_pixmap(name: str) -> QPixmap | None:
    """图鉴头像的内切圆版本；缺图返回 None。

    ⚠️ 名字来自图鉴页的 OCR，**不一定对**（同一名英雄在不同帧上可能读成别的字）。
    所以名单里必须把头像一起放出来 —— 用户是照着**长相**认人的，
    只看名字会把「名字读错的那一条」勾成别的英雄。

    ⚠️ 不能直接把方形图交给 QLabel：源图是圆形画面 + 方形画布，四角是截图底纹或
    透明压成的黑色，看着像一排毛边方块。这里按内切圆裁掉四角；描边不画在图里
    （见 ``_HeroTile.paintEvent``），否则每换一次选中态就要多存一张图。
    """

    if name in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[name]
    from auto_game_unified.games.epic7.hero_match import default_library_dir

    source = QPixmap(str(default_library_dir() / f"{name}.png"))
    if source.isNull():
        _PIXMAP_CACHE[name] = None
        return None
    side = _AVATAR_SIZE
    canvas = QPixmap(side, side)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, side, side))
    painter.setClipPath(clip)
    scaled = source.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawPixmap(
        (side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled
    )
    painter.end()
    _PIXMAP_CACHE[name] = canvas
    return canvas


class _HeroTile(QWidget):
    """一个英雄格子：内切圆头像在上、名字在下，点击切换选中。

    ⚠️ 不用列表自带的勾选框：勾选框占掉一整列宽度，五个汉字的名字会被压成
    「一轮孤月…」，而这类前缀名恰恰是同名英雄之间唯一的区别。
    """

    toggled = Signal(str)

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._chosen = False
        self.setFixedSize(_TILE_WIDTH, _TILE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._avatar = QLabel(self)
        self._avatar.setFixedSize(_AVATAR_BOX, _AVATAR_BOX)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignHCenter)

        self._caption = QLabel(self)
        self._caption.setFixedWidth(_TILE_WIDTH)
        self._caption.setFixedHeight(38)
        self._caption.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self._caption.setWordWrap(True)
        self._caption.setText(name)
        layout.addWidget(self._caption, 0, Qt.AlignmentFlag.AlignHCenter)

        meta = hero_meta(name)
        if meta is None:
            self.setToolTip(f"{name} · 未收录分类")
        else:
            self.setToolTip(f"{name} · {meta.job} · {meta.element} · {meta.stars} 星")
        self.set_chosen(False)

    @property
    def name(self) -> str:
        return self._name

    def set_chosen(self, chosen: bool) -> None:
        if chosen != self._chosen:
            self._chosen = chosen
            self.update()
        pixmap = _hero_pixmap(self._name)
        if pixmap is None:
            self._avatar.setPixmap(QPixmap())
            self._avatar.setText("无头像")
        else:
            self._avatar.setText("")
            self._avatar.setPixmap(pixmap)
        if chosen:
            self._caption.setStyleSheet(
                "color: #0078D7; font-size: 12px; font-weight: 600;"
            )
        else:
            self._caption.setStyleSheet("color: #1A1A1A; font-size: 12px;")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        """在头像位置画选中态圆环。

        画在格子上而不是图里：QLabel 的 pixmap 四角是透明的，圆环正好透出来，
        这样一份头像只存一张图，切换选中态不必重新生成。
        """

        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(_RING_CHOSEN if self._chosen else _RING_NORMAL))
        pen.setWidthF(2.0 if self._chosen else 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        left = (self.width() - _AVATAR_BOX) / 2
        ring = QRectF(left, 0, _AVATAR_BOX, _AVATAR_BOX).adjusted(3, 3, -3, -3)
        painter.drawEllipse(ring)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(self._name)
        super().mousePressEvent(event)


def _filter_row(
    parent: QWidget,
    title: str,
    values: tuple[str, ...],
    on_change,
) -> list[PillPushButton]:
    """一行可多选的筛选按钮，行首是「全部」。"""

    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(CaptionLabel(title, parent))
    buttons: list[PillPushButton] = []
    all_button = PillPushButton("全部", parent)
    all_button.setCheckable(True)
    all_button.setChecked(True)
    row.addWidget(all_button)
    buttons.append(all_button)
    for value in values:
        button = PillPushButton(str(value) + ("星" if str(value).isdigit() else ""), parent)
        button.setCheckable(True)
        row.addWidget(button)
        buttons.append(button)
    row.addStretch(1)
    for button in buttons:
        button.clicked.connect(lambda _checked=False: on_change(buttons))
    return buttons


def _chosen_values(buttons: list[PillPushButton]) -> set[str]:
    """勾选集合；「全部」被勾选或一个都没勾，都表示不限制。"""

    if buttons[0].isChecked():
        return set()
    picked = {button.text() for button in buttons[1:] if button.isChecked()}
    return set() if not picked else picked


def _sync_all_button(buttons: list[PillPushButton]) -> None:
    """「全部」与具体项互斥：勾具体项就取消「全部」，全取消则回落到「全部」。"""

    if buttons[0].isChecked() and any(b.isChecked() for b in buttons[1:]):
        buttons[0].setChecked(False)
    if not buttons[0].isChecked() and not any(b.isChecked() for b in buttons[1:]):
        buttons[0].setChecked(True)


def _filter_row(
    parent: QWidget,
    title: str,
    values: tuple[object, ...],
    on_change,
) -> tuple[QHBoxLayout, list[PillPushButton]]:
    """一行可多选的筛选按钮，行首是「全部」。"""

    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(CaptionLabel(title, parent))
    buttons: list[PillPushButton] = []
    all_button = PillPushButton("全部", parent)
    all_button.setCheckable(True)
    all_button.setChecked(True)
    all_button.setProperty("value", None)
    row.addWidget(all_button)
    buttons.append(all_button)
    for value in values:
        label = f"{value}星" if isinstance(value, int) else str(value)
        button = PillPushButton(label, parent)
        button.setCheckable(True)
        button.setProperty("value", value)
        row.addWidget(button)
        buttons.append(button)
    row.addStretch(1)
    for button in buttons:
        button.clicked.connect(
            lambda _checked=False, b=button, group=buttons: on_change(b, group)
        )
    return row, buttons


def _chosen_values(buttons: list[PillPushButton]) -> set[object]:
    """勾选集合；「全部」被勾选或一个都没勾，都表示不限制。"""

    if buttons[0].isChecked():
        return set()
    return {button.property("value") for button in buttons[1:] if button.isChecked()}


def _sync_all_button(clicked: PillPushButton, buttons: list[PillPushButton]) -> None:
    """「全部」与具体项互斥。

    ⚠️ 必须知道**点的是哪一个**：只看「全部是否勾着」无法区分「刚点了全部」
    与「刚点了某项」，会把点全部的那一下自己取消掉，界面出现两处同时高亮。
    """

    others = buttons[1:]
    if clicked is buttons[0]:
        if clicked.isChecked():
            for button in others:
                button.setChecked(False)
        elif not any(button.isChecked() for button in others):
            clicked.setChecked(True)
        return
    if clicked.isChecked():
        buttons[0].setChecked(False)
    elif not any(button.isChecked() for button in others):
        buttons[0].setChecked(True)


class HeroRosterDialog(QDialog):
    """英雄名单：头像格子 + 属性 / 职业 / 星级筛选 + 名字搜索。

    ⚠️ 只列**能认出来**的名字：库里缺图的英雄勾了也不会生效（``HeroMatcher``
    会把它记进日志），与其让人勾一个不存在的名字，不如一开始就不列。

    ⚠️ 每一项都要带**头像**：名字是图鉴页 OCR 出来的，可能读错；用户认的是长相。

    筛选口径与游戏内英雄管理面板一致（属性 5 项、职业 6 项、星级 3/4/5）。
    有搜索词时只按名字过滤、忽略分类条件 —— 否则搜一个「未收录分类」的英雄会得到
    空结果，看起来像库里没有这个人。
    """

    def __init__(self, parent, title: str, names: list[str], selected: list[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(_DIALOG_QSS)
        self.setMinimumWidth(_ROSTER_WIDTH)
        self.resize(_ROSTER_WIDTH, 760)
        self._names = list(names)
        self._chosen = {name for name in selected if name in set(names)}
        self._tiles: dict[str, _HeroTile] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 搜索与分类放在同一张卡片里：与主界面「一类内容一张卡」一致，
        # 也避免四行控件散在灰底上。
        filters = CardWidget(self)
        filters_layout = QVBoxLayout(filters)
        filters_layout.setContentsMargins(14, 12, 14, 12)
        filters_layout.setSpacing(8)

        self._search = LineEdit(filters)
        self._search.setPlaceholderText("搜索英雄名")
        self._search.textChanged.connect(self._refresh)
        filters_layout.addWidget(self._search)

        self._element_row, self._element_buttons = _filter_row(
            filters, "属性", ELEMENTS, self._on_filter
        )
        filters_layout.addLayout(self._element_row)
        self._job_row, self._job_buttons = _filter_row(
            filters, "职业", JOBS, self._on_filter
        )
        filters_layout.addLayout(self._job_row)
        self._star_row, self._star_buttons = _filter_row(
            filters, "星级", STARS, self._on_filter
        )
        filters_layout.addLayout(self._star_row)
        layout.addWidget(filters)

        grid_card = CardWidget(self)
        grid_layout = QVBoxLayout(grid_card)
        grid_layout.setContentsMargins(8, 8, 8, 8)
        grid_layout.setSpacing(0)
        self._canvas = QWidget(grid_card)
        self._grid = QGridLayout(self._canvas)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setSpacing(6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._area = QScrollArea(grid_card)
        self._area.setWidgetResizable(True)
        self._area.setFrameShape(QFrame.Shape.NoFrame)
        self._area.viewport().setAutoFillBackground(False)
        self._area.setWidget(self._canvas)
        # 同上：setWidget() 之后才关得掉内容区自绘的灰底。
        self._canvas.setAutoFillBackground(False)
        grid_layout.addWidget(self._area)
        layout.addWidget(grid_card, 1)

        for name in self._names:
            tile = _HeroTile(name, self._canvas)
            tile.set_chosen(name in self._chosen)
            tile.toggled.connect(self._toggle)
            self._tiles[name] = tile

        self._hint = CaptionLabel(self)
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        clear = PushButton("清空", self)
        clear.clicked.connect(self._clear)
        footer.addWidget(clear)
        footer.addStretch(1)
        confirm = PrimaryPushButton("确定", self)
        confirm.setFixedWidth(120)
        confirm.clicked.connect(self.accept)
        footer.addWidget(confirm)
        layout.addLayout(footer)

        self._refresh()

    # ---- 交互 ----

    def _on_filter(self, clicked: PillPushButton, buttons: list[PillPushButton]) -> None:
        _sync_all_button(clicked, buttons)
        self._refresh()

    def _toggle(self, name: str) -> None:
        """切换一个英雄的选中状态。

        ⚠️ 这里**不重排**：勾完一项就整页重排会让刚点的格子从指尖跳走，
        连续勾选时尤其难用。已选置顶只在打开对话框与改变筛选条件时生效。
        """

        if name in self._chosen:
            self._chosen.discard(name)
            self._tiles[name].set_chosen(False)
        else:
            self._chosen.add(name)
            self._tiles[name].set_chosen(True)
        self._update_hint(self._visible_names())

    def _clear(self) -> None:
        for name in list(self._chosen):
            self._tiles[name].set_chosen(False)
        self._chosen.clear()
        self._refresh()

    # ---- 视图更新 ----

    def _visible_names(self) -> list[str]:
        return filter_names(
            self._names,
            keyword=self._search.text(),
            jobs=_chosen_values(self._job_buttons),
            elements=_chosen_values(self._element_buttons),
            stars=_chosen_values(self._star_buttons),
        )

    def _refresh(self) -> None:
        # 有搜索词时分类条件不生效，把三组按钮置灰：结果与按钮外观不一致会让人
        # 以为筛的是「水」，实际列出的是全部——那比不给筛选还难判断。
        searching = bool(self._search.text().strip())
        for buttons in (self._element_buttons, self._job_buttons, self._star_buttons):
            for button in buttons:
                button.setEnabled(not searching)

        visible = self._visible_names()
        # 已勾选的排在前面：勾完再往下翻时不必滚回顶部确认。
        ordered = [name for name in visible if name in self._chosen] + [
            name for name in visible if name not in self._chosen
        ]
        self._area.setUpdatesEnabled(False)
        try:
            for name in self._names:
                tile = self._tiles[name]
                self._grid.removeWidget(tile)
                tile.hide()
            for index, name in enumerate(ordered):
                row, column = divmod(index, _COLUMNS)
                self._grid.addWidget(self._tiles[name], row, column)
                self._tiles[name].show()
        finally:
            self._area.setUpdatesEnabled(True)
        self._update_hint(ordered)

    def _update_hint(self, visible: list[str]) -> None:
        total = len(self._names)
        missing = unclassified_count(self._names)
        text = f"共 {total} 名可选 · 已选 {len(self._chosen)} 名 · 当前显示 {len(visible)} 名"
        if missing:
            text += f" · {missing} 名未收录分类，可按名字搜索"
        self._hint.setText(text)

    def selected_names(self) -> list[str]:
        return [name for name in self._names if name in self._chosen]


class RouteOptionsDialog(QDialog):
    """声明驱动：下拉与数字框按 ``RouteOption`` 生成，依赖未满足时置灰。

    每个选项一张卡片，卡片内是「标题 + 右侧控件 / 下一行说明」的读法 ——
    与主界面「运行环境」那张卡的层级一致，不再用整页表单。
    """

    _CARD_WIDTH = 520
    _CONTROL_WIDTH = 200

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
        self.setStyleSheet(_DIALOG_QSS)
        self.setMinimumWidth(self._CARD_WIDTH)
        self.resize(self._CARD_WIDTH, 720)
        self._mode = mode
        self._on_accept = on_accept
        self._options = options_for(mode)
        self._controls: dict[str, object] = {}
        self._roster_values: dict[str, list[str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        # 视口默认按系统窗口色（#F3F3F3）自绘，会在白底对话框里留一大块灰。
        area.viewport().setAutoFillBackground(False)
        holder = QWidget(area)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(8)

        for option in self._options:
            column.addWidget(self._build_card(option, values, holder))
        column.addStretch(1)
        area.setWidget(holder)
        # ⚠️ setWidget() 会把内容的 autoFillBackground 重新打开，内容区因此按系统
        # 窗口色自绘成一块灰。必须**在 setWidget 之后**关掉，写在前面对不掉。
        holder.setAutoFillBackground(False)
        layout.addWidget(area, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        confirm = PrimaryPushButton("保存", self)
        confirm.setFixedWidth(120)
        confirm.clicked.connect(self._accept)
        footer.addWidget(confirm)
        layout.addLayout(footer)
        self._sync_enabled()

    def _build_card(
        self, option, values: Mapping[str, object], parent: QWidget
    ) -> CardWidget:
        card = CardWidget(parent)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(StrongBodyLabel(option.label, card), 1)

        if option.kind == "choice":
            control = ComboBox(card)
            for value, text in option.choices:
                control.addItem(text, userData=value)
            index = control.findData(values.get(option.key, option.default))
            control.setCurrentIndex(max(0, index))
            control.setFixedWidth(self._CONTROL_WIDTH)
            control.currentIndexChanged.connect(self._sync_enabled)
        elif option.kind == "roster":
            control = PushButton("选择英雄", card)
            control.setFixedWidth(self._CONTROL_WIDTH)
            picked = list(values.get(option.key, ()) or ())
            control.clicked.connect(
                lambda _checked=False, k=option.key, lbl=option.label, c=control: (
                    self._edit_roster(k, lbl, c)
                )
            )
            self._roster_values[option.key] = picked
            self._refresh_roster_label(option.key, control)
        else:
            control = QSpinBox(card)
            control.setStyleSheet(SPIN_BOX_QSS)
            control.setRange(option.minimum, option.maximum)
            control.setValue(int(values.get(option.key, option.default) or 0))
            control.setFixedWidth(120)
        self._controls[option.key] = control
        head.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addLayout(head)

        note = CaptionLabel(option.note, card)
        note.setWordWrap(True)
        card_layout.addWidget(note)
        return card

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

        ⚠️ 不这样做的话，同一英雄会同时给避战名单和优先名单各加 1，数量永远相等，
        优先名单永远压不过避战名单（除非把「相等」改成按优先处理），等于白勾。
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
