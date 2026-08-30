"""下载加速设置卡：选择镜像 + 测速 + 管理自定义源（增删改 + 拖动排序）。

版式是 `ExpandGroupSettingCard`：收起时是一行普通设置卡（标题 + 生效值 + 下拉 + 测速按钮），
展开后每个加速源一行，右边挂**三色状态胶囊**（绿=良好 / 橙=一般 / 红=错误），
最后一行是「添加自定义源」。

行为：

- **顺序可拖**。顺序不只��好看——`auto` 模式就是按这个顺序依次尝试的（`updater.mirror_chain`），
  测完速把快的拖到前面是有实际效果的。内置源也能排，只是不能改地址、不能删。
- **自定义源可改可删**。改地址走**原地编辑**（行内换成输入框），保持它在顺序里的位置。

三个上游 / Qt 约束决定了这里的写法：

1. **`HeaderSettingCard.addWidget` 只能调一次**（每次都会把 `expandButton` 重新塞进布局），
   所以下拉与测速按钮先包进一个容器再挂。
2. **`addGroupWidget` 也只调一次**，塞进去的是本文件自己管的面板。逐行 `addGroupWidget`
   的话，加删改排全得去动上游的 `viewLayout`（里面还夹着它自己插的分隔线），
   不如自己管一个容器，改完调 `_adjustViewSize()` 重算展开高度。
3. **`ExpandSettingCard` 没有 `setContent`**（它是 `QScrollArea` 子类），副标题在 `.card` 上。

拖动是手写的而不是用 `QListWidget` 的 `InternalMove`：后者在 `setItemWidget` 的场景下
会在移动时把 item widget 弄丢。行高固定，目标下标就是一次除法，反倒更简单可控。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    IconWidget,
    InfoLevel,
    LineEdit,
    PushButton,
    ToolTipFilter,
    ToolTipPosition,
    TransparentToolButton,
    qconfig,
)

from app.common.config import GH_MIRROR_AUTO, GH_MIRRORS, cfg
from app.common.theme import SECONDARY_TEXT
from app.components.page_scaffold import BusyPushButton, status_badge
from app.components.task import run_task
from app.components.updater import (
    LATENCY_GOOD_MS,
    PROBE_TARGET,
    TIER_ERROR,
    TIER_FAIR,
    TIER_GOOD,
    MirrorSpeed,
    add_custom_mirror,
    all_mirrors,
    is_custom,
    orderable_mirrors,
    probe_mirrors,
    remove_custom_mirror,
    set_mirror_order,
    update_custom_mirror,
)

# 测速三档 → 组件库的三种语义色。`InfoLevel` 决定语义，颜色显式给一对 (亮色, 暗色)：
# 上游暗色主题下 WARNING / ERROR 用的是浅底（#fff4ce / #ff99a4），而 qss 把文字钉成白色，
# 白字压浅底看不清。两个主题都用深底 + 白字，对比度才稳（见 page_scaffold.status_badge）。
_TIER_LEVEL = {
    TIER_GOOD: InfoLevel.SUCCESS,
    TIER_FAIR: InfoLevel.WARNING,
    TIER_ERROR: InfoLevel.ERROR,
}
_TIER_COLORS = {
    TIER_GOOD: ("#0f7b0f", "#1c8c23"),   # 绿
    TIER_FAIR: ("#9d5d00", "#b26e0c"),   # 橙
    TIER_ERROR: ("#c42b1c", "#d03e30"),  # 红
}
_TESTING_COLORS = ("#8a8a8a", "#9d9d9d")  # 测速中：中性灰

_ROW_H = 56  # 展开区行高（addGroupWidget 按 sizeHint 算展开高度，必须固定）
_ROW_MARGIN = (20, 8, 24, 8)  # 左边留给拖动手柄
_HANDLE_W = 24
_DRAG_START = 6  # 按下后移动多少像素才算开始拖


class _MirrorRow(QWidget):
    """展开区的一行：拖动手柄 + 名称/地址 + 状态胶囊 + 编辑 / 删除。

    自定义源才有编辑与删除按钮；内置源只能排序。
    """

    removeRequested = Signal(str)
    editRequested = Signal(str, str)  # (旧地址, 新地址)
    dragStarted = Signal(object, QPoint)
    dragMoved = Signal(QPoint)
    dragFinished = Signal()

    def __init__(self, label: str, value: str, editable: bool, draggable: bool, parent=None) -> None:
        super().__init__(parent)
        self.value = value
        self.draggable = draggable
        self._badge = None
        self._press_pos: QPoint | None = None
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(*_ROW_MARGIN)
        layout.setSpacing(8)

        self.handle = IconWidget(FluentIcon.MENU, self)
        self.handle.setFixedSize(14, 14)
        self.handle.setVisible(draggable)
        self.handle.setToolTip("按住拖动可调整顺序（「自动」模式按这个顺序依次尝试）")
        holder = QWidget(self)
        holder.setFixedWidth(_HANDLE_W)
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.handle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(holder)

        # 常态（名称 + 地址）与编辑态（输入框）叠在一起换
        self.stack = QStackedWidget(self)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        view = QWidget(self.stack)
        text = QVBoxLayout(view)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        self.nameLabel = BodyLabel(label, view)
        self.addrLabel = CaptionLabel(value or "直连 github.com，不经任何中转", view)
        self.addrLabel.setTextColor(*SECONDARY_TEXT)
        text.addWidget(self.nameLabel)
        text.addWidget(self.addrLabel)
        self.stack.addWidget(view)

        editor = QWidget(self.stack)
        el = QHBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        self.edit = LineEdit(editor)
        self.edit.setPlaceholderText("https://ghproxy.example/")
        el.addWidget(self.edit, 1)
        self.stack.addWidget(editor)
        layout.addWidget(self.stack, 1)

        self.badgeHolder = QWidget(self)
        self.badgeHolder.setFixedWidth(120)
        self._badgeLayout = QHBoxLayout(self.badgeHolder)
        self._badgeLayout.setContentsMargins(0, 0, 0, 0)
        self._badgeLayout.addStretch(1)
        layout.addWidget(self.badgeHolder, 0, Qt.AlignmentFlag.AlignVCenter)

        # 常态按钮：编辑 / 删除；编辑态按钮：确定 / 取消。共用同一块位置
        self.editBtn = TransparentToolButton(FluentIcon.EDIT, self)
        self.editBtn.setToolTip("修改这个加速源的地址")
        self.removeBtn = TransparentToolButton(FluentIcon.DELETE, self)
        self.removeBtn.setToolTip("删除这个自定义加速源")
        self.okBtn = TransparentToolButton(FluentIcon.ACCEPT, self)
        self.okBtn.setToolTip("保存")
        self.cancelBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.cancelBtn.setToolTip("取消")
        for btn in (self.editBtn, self.removeBtn, self.okBtn, self.cancelBtn):
            btn.setFixedSize(30, 30)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        if not editable:
            # 内置源不给改也不给删，但留出等宽占位让各行右边缘对齐
            for btn in (self.editBtn, self.removeBtn):
                btn.hide()
            spacer = QWidget(self)
            spacer.setFixedWidth(60)
            layout.addWidget(spacer)
        self.okBtn.hide()
        self.cancelBtn.hide()

        self.editBtn.clicked.connect(self.begin_edit)
        self.cancelBtn.clicked.connect(self.cancel_edit)
        self.okBtn.clicked.connect(self._commit)
        self.edit.returnPressed.connect(self._commit)
        self.removeBtn.clicked.connect(lambda: self.removeRequested.emit(self.value))

        self.setFixedHeight(_ROW_H)

    # ---- 编辑 ----

    def begin_edit(self) -> None:
        self.edit.setText(self.value)
        self.stack.setCurrentIndex(1)
        self.editBtn.hide()
        self.removeBtn.hide()
        self.badgeHolder.hide()
        self.okBtn.show()
        self.cancelBtn.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def cancel_edit(self) -> None:
        self.stack.setCurrentIndex(0)
        self.okBtn.hide()
        self.cancelBtn.hide()
        self.badgeHolder.show()
        self.editBtn.show()
        self.removeBtn.show()

    def is_editing(self) -> bool:
        return self.stack.currentIndex() == 1

    def _commit(self) -> None:
        self.editRequested.emit(self.value, self.edit.text().strip())

    # ---- 状态胶囊 ----

    def set_speed(self, speed: MirrorSpeed | None) -> None:
        """挂上（或清掉）状态胶囊。None = 未测。"""
        self._clear_badge()
        if speed is None:
            return
        self._show_badge(
            speed.text,
            _TIER_LEVEL.get(speed.tier, InfoLevel.ERROR),
            _TIER_COLORS.get(speed.tier, _TIER_COLORS[TIER_ERROR]),
        )

    def set_testing(self) -> None:
        self._clear_badge()
        self._show_badge("测速中…", InfoLevel.INFOAMTION, _TESTING_COLORS)

    def _clear_badge(self) -> None:
        if self._badge is None:
            return
        self._badgeLayout.removeWidget(self._badge)
        self._badge.deleteLater()
        self._badge = None

    def _show_badge(self, text: str, level: InfoLevel, colors) -> None:
        self._badge = status_badge(text, level, self.badgeHolder, colors)
        self._badgeLayout.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self._badge.show()

    # ---- 拖动 ----

    def mousePressEvent(self, event) -> None:
        if (
            self.draggable
            and not self.is_editing()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None and not self._dragging:
            moved = (event.position().toPoint() - self._press_pos).manhattanLength()
            if moved >= _DRAG_START:
                self._dragging = True
                self.dragStarted.emit(self, self._press_pos)
        if self._dragging:
            self.dragMoved.emit(self.mapToParent(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.dragFinished.emit()
        self._press_pos = None
        super().mouseReleaseEvent(event)


class _AddRow(QWidget):
    """展开区最后一行：输入地址 + 添加。"""

    submitted = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(_ROW_MARGIN[0] + _HANDLE_W + 8, 8, _ROW_MARGIN[2], 8)
        layout.setSpacing(8)

        self.edit = LineEdit(self)
        self.edit.setPlaceholderText("添加自定义加速源，如 https://ghproxy.example/")
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.addBtn = PushButton("添加", self)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.addBtn, 0)

        self.addBtn.clicked.connect(self._submit)
        self.edit.returnPressed.connect(self._submit)
        self.setFixedHeight(_ROW_H)

    def _submit(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.submitted.emit(text)

    def clear(self) -> None:
        self.edit.clear()


class MirrorSettingCard(ExpandGroupSettingCard):
    """「下载加速」设置卡。

    对外只有两个东西要知道：`combo`（当前选择，即时写 `cfg.gh_mirror`）与
    `notify`（页面注入的提示函数，签名 `(kind, title, content)`）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(
            FluentIcon.SPEED_HIGH,
            "下载加速",
            "直连 GitHub 慢时，用镜像下载安装包",
            parent,
        )
        self.notify = None  # 由页面注入，见 SettingPage._build_about_group
        self._rows: list[_MirrorRow] = []
        self._speeds: dict[str, MirrorSpeed] = {}
        self._drag_row: _MirrorRow | None = None
        self._drag_grab = QPoint()
        self._placeholder: QWidget | None = None

        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(200)
        self.testBtn = BusyPushButton("测速", self)
        self.testBtn.reserve_busy("测速中")
        # HeaderSettingCard.addWidget 只能调一次，多控件先包容器
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.combo)
        row.addWidget(self.testBtn)
        self.addWidget(holder)

        # 展开区：整块交给自己管的面板，加删改排时只动这里再重算高度
        self.panel = QWidget(self.view)
        self.panelLayout = QVBoxLayout(self.panel)
        self.panelLayout.setContentsMargins(0, 0, 0, 0)
        self.panelLayout.setSpacing(0)
        self.addRow = _AddRow(self.panel)
        self.panelLayout.addWidget(self.addRow)
        self.addGroupWidget(self.panel)

        # 提示挂 .card 而不是 self：self 是整个 QScrollArea（含展开区），
        # 悬停在哪都弹一个大气泡很吵；标题行才是该解释的地方
        self.card.setToolTip(
            "加速源是 URL 前缀式反代：把原始地址整个接在它后面，形如\n"
            "    https://gh-proxy.com/https://github.com/.../setup.exe\n"
            "与「下载 → 代理」是两套独立机制（那边改的是 requests 的 proxies），\n"
            "可以同时使用。\n"
            "\n"
            f"「测速」经每个源访问 {PROBE_TARGET} 并计时，只取响应头不下正文；\n"
            f"低于 {LATENCY_GOOD_MS} ms 记「良好」，通了但更慢记「一般」，连不上记「错误」。\n"
            "展开后可拖动排序——「自动」模式就是按这个顺序依次尝试的。\n"
            "\n"
            "安装包的 SHA-256 校验和始终**直连** GitHub 获取——用镜像给的校验和\n"
            "去校验镜像给的文件等于没校验。校验不通过的文件会被删除且不会运行。"
        )
        self.card.installEventFilter(ToolTipFilter(self.card, 500, ToolTipPosition.TOP))

        self.combo.currentIndexChanged.connect(self._on_selected)
        self.testBtn.clicked.connect(self.start_test)
        self.addRow.submitted.connect(self._on_add)
        self.reload()

    # ---- 列表 ----

    def reload(self) -> None:
        """按当前配置重建下拉与展开区（加删改排之后调用）。"""
        self._reload_combo()
        self._reload_rows()
        self._refresh_content()

    def _reload_combo(self) -> None:
        current = cfg.gh_mirror.value
        items = all_mirrors()
        self.combo.blockSignals(True)
        self.combo.clear()
        for text, value in items:
            # 第二个位置参数是 icon 不是 userData，必须写关键字
            self.combo.addItem(text, userData=value)
        values = [value for _, value in items]
        self.combo.setCurrentIndex(values.index(current) if current in values else 0)
        self.combo.blockSignals(False)

    def _reload_rows(self) -> None:
        for row in self._rows:
            self.panelLayout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        labels = {value: text for text, value in GH_MIRRORS}
        # 直连排第一且不参与排序：它本来就是「不经中转」，谈不上顺序
        entries = [("不使用（直连 GitHub）", "", False, False)]
        entries += [
            (labels.get(v) or v.split("://", 1)[-1].strip("/"), v, is_custom(v), True)
            for v in orderable_mirrors()
        ]
        for label, value, editable, draggable in entries:
            row = _MirrorRow(label, value, editable, draggable, self.panel)
            row.removeRequested.connect(self._on_remove)
            row.editRequested.connect(self._on_edit)
            row.dragStarted.connect(self._on_drag_start)
            row.dragMoved.connect(self._on_drag_move)
            row.dragFinished.connect(self._on_drag_finish)
            row.set_speed(self._speeds.get(value))
            self.panelLayout.insertWidget(len(self._rows), row)  # 「添加」行永远在最后
            self._rows.append(row)
        self._adjustViewSize()

    def _refresh_content(self) -> None:
        """副标题显示**当前生效**的选择（读 cfg，不是读下拉）。

        写 `self.card.setContent` 而不是 `self.setContent`：`ExpandSettingCard` 是
        `QScrollArea` 子类，压根没有 `setContent`，标题行在 `.card`（`HeaderSettingCard`）上。
        """
        value = cfg.gh_mirror.value
        if not value:
            self.card.setContent("未启用：安装包直接从 GitHub 下载")
        elif value == GH_MIRROR_AUTO:
            self.card.setContent("自动：按下方顺序依次尝试")
        else:
            self.card.setContent(f"当前使用：{value}")

    # ---- 交互 ----

    def _on_selected(self, index: int) -> None:
        value = self.combo.itemData(index)
        if value is None:
            return
        qconfig.set(cfg.gh_mirror, value)
        self._refresh_content()

    def _on_add(self, text: str) -> None:
        try:
            value = add_custom_mirror(text)
        except ValueError as exc:
            self._notify("warning", "添加失败", str(exc))
            return
        self.addRow.clear()
        self.reload()
        self._notify("success", "已添加", f"{value}\n可以点「测速」看看它通不通")
        self.setExpand(True)

    def _on_edit(self, old: str, text: str) -> None:
        try:
            value = update_custom_mirror(old, text)
        except ValueError as exc:
            self._notify("warning", "修改失败", str(exc))
            return
        self._speeds.pop(old, None)  # 换了地址，旧的测速结果不作数
        self.reload()
        if value != old:
            self._notify("success", "已修改", f"{old}\n→ {value}")

    def _on_remove(self, value: str) -> None:
        remove_custom_mirror(value)
        self._speeds.pop(value, None)
        self.reload()
        self._notify("success", "已删除", value)

    def _notify(self, kind: str, title: str, content: str) -> None:
        if self.notify is not None:
            self.notify(kind, title, content)

    # ---- 拖动排序 ----

    def _on_drag_start(self, row: _MirrorRow, grab: QPoint) -> None:
        """把被拖的行从布局里摘出来浮在上面，原位插一个等高占位。

        摘出来（`removeWidget`）是关键：留在布局里的话每次重新布局都会把
        `move()` 的结果覆盖掉，行根本跟不了鼠标。
        """
        index = self._rows.index(row)
        self._drag_row = row
        self._drag_grab = grab
        self._placeholder = QWidget(self.panel)
        self._placeholder.setFixedHeight(row.height())
        self.panelLayout.removeWidget(row)
        self.panelLayout.insertWidget(index, self._placeholder)
        row.setParent(self.panel)
        row.raise_()
        row.show()
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)

    def _on_drag_move(self, pos: QPoint) -> None:
        if self._drag_row is None or self._placeholder is None:
            return
        top = pos.y() - self._drag_grab.y()
        self._drag_row.move(self._drag_row.x(), top)
        # 目标下标 = 当前中心落在第几行。直连那行钉在最前，不能被越过
        center = top + self._drag_row.height() // 2
        target = max(1, min(len(self._rows) - 1, center // max(1, _ROW_H)))
        if self.panelLayout.indexOf(self._placeholder) != target:
            self.panelLayout.removeWidget(self._placeholder)
            self.panelLayout.insertWidget(target, self._placeholder)

    def _on_drag_finish(self) -> None:
        if self._drag_row is None or self._placeholder is None:
            return
        QApplication.restoreOverrideCursor()
        target = self.panelLayout.indexOf(self._placeholder)
        self.panelLayout.removeWidget(self._placeholder)
        self._placeholder.deleteLater()
        self._placeholder = None
        row, self._drag_row = self._drag_row, None

        values = [r.value for r in self._rows if r is not row]
        values.insert(max(0, min(len(values), target)), row.value)
        set_mirror_order([v for v in values if v])  # 直连（空串）不进顺序表
        self.reload()  # 重建即归位，不用手动挪控件

    # ---- 测速 ----

    def start_test(self) -> None:
        """并发测所有源（含直连），每测完一行就点亮一行。"""
        targets = [row.value for row in self._rows]
        if not targets:
            return
        self._speeds.clear()
        for row in self._rows:
            row.set_testing()
        self.setExpand(True)  # 结果在展开区里，不展开等于白测
        self.testBtn.set_busy(True)
        run_task(
            probe_mirrors,
            targets,
            needs_progress=True,
            on_progress=self._on_probe_progress,
            on_finished=lambda ok: self.testBtn.set_busy(False),
        )

    def _on_probe_progress(self, _done: int, _total: int, speed) -> None:
        if not isinstance(speed, MirrorSpeed):
            return
        self._speeds[speed.mirror] = speed
        for row in self._rows:
            if row.value == speed.mirror:
                row.set_speed(speed)
                break
