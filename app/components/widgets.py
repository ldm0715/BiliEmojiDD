"""可复用组件：表情缩略图网格、表情包卡片网格、收藏集卡片、下载队列卡片。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CheckBox, FlowLayout, SmoothScrollArea
from qfluentwidgets.common.style_sheet import ThemeColor

from app.common.signal_bus import signal_bus
from app.components.download_queue import item_kind
from app.components.dress_helpers import category_name, is_collection
from app.components.thumb import thumb_manager

_PACKAGE_CELL = QSize(160, 160)
_PACKAGE_ICON = QSize(96, 96)


def _package_cover_url(pkg):
    """包封面：优先包内第一张表情（动图优先），其次包封面。"""
    if pkg.emote:
        first = pkg.emote[0]
        if first.gif_url:
            return first.gif_url
        if first.url:
            return first.url
    return pkg.url


class EmojiCard(QWidget):
    """单个表情卡片：图标（固定大小）+ 全名（独立文字组件，超长分行并滚动，不遮挡图标）。"""

    def __init__(
        self,
        text: str,
        url: str,
        parent: QWidget | None = None,
        *,
        icon_size: QSize | None = None,
        width: int = 104,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.setFixedWidth(width)
        icon_size = icon_size if icon_size is not None else QSize(72, 72)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        # 图标：独立区域，固定大小，永不被文字挤占
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(icon_size)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.iconLabel.setStyleSheet("background: rgba(128,128,128,0.12);")
        layout.addWidget(self.iconLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        # 文字：独立区域（图标正下方），按内容自适应高度，超长自动分行，不遮挡图标
        self.textLabel = QLabel(text or "", self)
        self.textLabel.setWordWrap(True)
        self.textLabel.setFixedWidth(width - 8)
        self.textLabel.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.textLabel.setStyleSheet("font-size: 12px; color: #909090;")
        # 无文字时不占高度，卡片更紧凑
        if not (text or "").strip():
            self.textLabel.hide()
        layout.addWidget(self.textLabel, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_pixmap(self, pixmap) -> None:
        self.iconLabel.setPixmap(
            pixmap.scaled(
                self.iconLabel.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class EmojiGrid(SmoothScrollArea):
    """表情流式网格：每个表情一张卡片（图标 + 全名，超长自动换行）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget(self)
        self._flow = FlowLayout(self._container, needAni=False)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setVerticalSpacing(4)
        self._flow.setHorizontalSpacing(4)
        self._container.setLayout(self._flow)
        self.setWidget(self._container)
        self._url_cards: dict[str, list[EmojiCard]] = {}
        signal_bus.thumbLoaded.connect(self._on_thumb_loaded)

    def set_emotes(
        self,
        items: list[tuple[str, str]],
        *,
        icon_size: QSize | None = None,
        width: int = 104,
    ) -> None:
        """items: [(text, url), ...]。url 为 None/空的行被跳过，不报错。

        详情等场景可用 icon_size / width 放大卡片。
        """
        icon_size = icon_size if icon_size is not None else QSize(72, 72)
        # FlowLayout.takeAt(index) 直接返回 widget
        while self._flow.count():
            widget = self._flow.takeAt(0)
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._url_cards.clear()
        for text, url in items:
            if not url:
                continue
            card = EmojiCard(text, url, icon_size=icon_size, width=width)
            self._flow.addWidget(card)
            self._url_cards.setdefault(url, []).append(card)
            thumb_manager.request(url)

    def _on_thumb_loaded(self, url: str, pixmap) -> None:
        for card in self._url_cards.get(url, ()):
            card.set_pixmap(pixmap)


class PackageCard(QWidget):
    """表情包卡片：图片按钮 + 居中文字 + 右上角勾选框 + 选中背景。

    容器不设 Layout；图片用 QPushButton(setFlat=True) 以便点击整图触发勾选；
    文字 QLabel 居中且宽度对齐图片；勾选框 setGeometry 钉在右上角 + raise_()；
    toggled 信号同步整卡背景色（半透明主题色）。点击卡片：多选态切换勾选，非多选态发 clicked。
    """

    clicked = Signal(object)  # EmotePackage
    toggled = Signal(object, bool)  # (pkg, checked)

    _CELL = QSize(160, 160)
    _IMG = QRect(0, 0, 160, 116)
    _TXT = QRect(0, 118, 160, 40)
    _CHECK_SIZE = 20

    def __init__(self, pkg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pkg = pkg
        self.item = pkg  # 网格基类约定：payload 统一叫 .item
        self._selectable = False
        self.setFixedSize(self._CELL)
        # 普通 QWidget 需此属性才会绘制 stylesheet 的 background-color（选中背景）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        # 图片按钮：flat、透明，点击整图触发
        self.imageBtn = QPushButton(self)
        self.imageBtn.setGeometry(self._IMG)
        self.imageBtn.setFlat(True)
        self.imageBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.imageBtn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
        )
        self.imageBtn.clicked.connect(self._on_image_clicked)

        # 文字：居中，宽度对齐图片
        self.textLabel = QLabel(self)
        self.textLabel.setGeometry(self._TXT)
        self.textLabel.setWordWrap(True)
        self.textLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.textLabel.setStyleSheet(
            "color: gray; font-size: 12px; background: transparent; border: none;"
        )
        self.textLabel.setText(f"{pkg.text or ('#' + str(pkg.id))}\nID: {pkg.id}")
        self.textLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 勾选框：右上角，置顶
        self.checkBox = CheckBox(self)
        self.checkBox.setFixedSize(self._CHECK_SIZE, self._CHECK_SIZE)
        self.checkBox.setGeometry(
            self._IMG.right() - self._CHECK_SIZE - 4,
            self._IMG.top() + 4,
            self._CHECK_SIZE,
            self._CHECK_SIZE,
        )
        self.checkBox.raise_()  # 置于图片按钮/文字之上
        self.checkBox.setVisible(False)
        self.checkBox.toggled.connect(self._on_toggled)

        self._accent = ThemeColor.PRIMARY.color()
        self._apply_bg(False)

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = bool(selectable)
        self.checkBox.setVisible(self._selectable)
        if not self._selectable:
            self.checkBox.setChecked(False)
        self._apply_bg(self.checkBox.isChecked())

    def set_checked(self, checked: bool) -> None:
        self.checkBox.setChecked(bool(checked))

    def is_checked(self) -> bool:
        return self.checkBox.isChecked()

    def set_cell(self, size: QSize) -> None:
        # PackageGrid 固定单元格，尺寸在 __init__ 已固定
        pass

    def set_pixmap(self, pixmap) -> None:
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                self._IMG.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.imageBtn.setIcon(QIcon(scaled))
            self.imageBtn.setIconSize(scaled.size())

    def _on_image_clicked(self) -> None:
        if self._selectable:
            self.checkBox.setChecked(not self.checkBox.isChecked())
        else:
            self.clicked.emit(self.pkg)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_bg(checked)
        self.toggled.emit(self.pkg, checked)

    def _apply_bg(self, checked: bool) -> None:
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
            )
        else:
            self.setStyleSheet("background-color: transparent;")

    def mousePressEvent(self, event) -> None:
        # 图片区由 imageBtn 处理；文字区点击同样切换
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selectable:
                self.checkBox.setChecked(not self.checkBox.isChecked())
            else:
                self.clicked.emit(self.pkg)
            return
        super().mousePressEvent(event)


class _CardGridBase(QListWidget):
    """QListWidget + setItemWidget 网格基类：懒加载缩略图 + 多选 API + 动态单元格。

    子类约定：
      _card_class     卡片类，构造签名 (item, parent)，暴露 .item / set_selectable /
                      set_checked / is_checked / set_pixmap / set_cell /
                      clicked(object) / toggled(object, bool)
      _cover_url(item) 返回封面缩略图 URL（可 None）
      _cell_size()     返回当前单元格 QSize
      _min_cell        最小单元格 QSize
    点击统一走 self.itemClicked(object)（载荷为 item），子类在 __init__ 转发到公开信号。
    """

    itemClicked = Signal(object)  # 载荷为卡片对应的 item
    selectionChanged = Signal()  # 勾选集合变化

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setSpacing(8)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._selectable = False
        self._updating = False
        self._requested: set[str] = set()
        self._url_cards: dict[str, list] = {}
        self._last_cell: QSize | None = None
        signal_bus.thumbLoaded.connect(self._on_thumb_loaded)

    # ---- 数据填充 ----

    def set_cards(self, items) -> None:
        """items：与 _card_class 构造签名匹配的载荷对象列表。"""
        self._requested.clear()
        self._url_cards.clear()
        self.clear()
        for it in items:
            url = self._cover_url(it)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, url)
            card = self._card_class(it, self)
            card.set_selectable(self._selectable)
            card.clicked.connect(self._emit_clicked)
            card.toggled.connect(self._on_card_toggled)
            self.addItem(item)
            self.setItemWidget(item, card)
            if url:
                self._url_cards.setdefault(url, []).append(card)
        self._last_cell = None  # 强制首次重排
        self._layout_items()
        self._update_visible()

    # ---- 卡片尺寸 ----

    def _cell_size(self) -> QSize:
        raise NotImplementedError

    def _layout_items(self) -> None:
        cell = self._cell_size()
        if cell is None or cell == self._last_cell:
            return
        self._last_cell = cell
        self.setGridSize(cell)
        for i in range(self.count()):
            item = self.item(i)
            item.setSizeHint(cell)
            w = self.itemWidget(item)
            if w is not None:
                set_cell = getattr(w, "set_cell", None)
                if callable(set_cell):
                    set_cell(cell)
                else:
                    w.setFixedSize(cell)

    # ---- 信号转发 ----

    def _emit_clicked(self, it) -> None:
        self.itemClicked.emit(it)

    def _on_card_toggled(self, it, checked: bool) -> None:
        if not self._updating:
            self.selectionChanged.emit()

    # ---- 多选 API ----

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = bool(selectable)
        self._updating = True
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if card is not None and hasattr(card, "set_selectable"):
                card.set_selectable(self._selectable)
        self._updating = False
        self.selectionChanged.emit()

    def checked_items(self) -> list:
        out = []
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if card is not None and card.is_checked():
                out.append(card.item)
        return out

    def checked_count(self) -> int:
        n = 0
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if card is not None and card.is_checked():
                n += 1
        return n

    def set_all_checked(self, checked: bool) -> None:
        self._updating = True
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if card is not None and hasattr(card, "set_checked"):
                card.set_checked(checked)
        self._updating = False
        self.selectionChanged.emit()

    # ---- 懒加载缩略图 ----

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._update_visible()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_items()
        self._update_visible()

    def _update_visible(self) -> None:
        viewport = self.viewport().rect()
        for i in range(self.count()):
            item = self.item(i)
            if not self.visualItemRect(item).intersects(viewport):
                continue
            url = item.data(Qt.ItemDataRole.UserRole)
            if url and url not in self._requested:
                self._requested.add(url)
                thumb_manager.request(url)

    def _on_thumb_loaded(self, url: str, pixmap) -> None:
        for card in self._url_cards.get(url, ()):
            card.set_pixmap(pixmap)


class PackageGrid(_CardGridBase):
    """表情包卡片网格（旧 API 包装）：QListWidget + setItemWidget 挂载 PackageCard。

    只对可视区域的项目请求缩略图（懒加载）。
    多选态：卡片右上角勾选框 + 选中遮罩，点击切换勾选。
    """

    packageClicked = Signal(object)  # EmotePackage

    _card_class = PackageCard
    _min_cell = _PACKAGE_CELL

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemClicked.connect(self.packageClicked.emit)

    @staticmethod
    def _cover_url(pkg):
        return _package_cover_url(pkg)

    def _cell_size(self) -> QSize:
        return _PACKAGE_CELL

    def set_packages(self, packages) -> None:
        """packages：EmotePackage 列表。"""
        self.set_cards(packages)

    def checked_packages(self) -> list:
        return self.checked_items()


class DressCard(QWidget):
    """收藏集搜索结果竖版卡片：封面(上, 3:4 等比) + 名称 + 分类徽标 + 右上角勾选框。

    纯 QWidget（不用 CardWidget：其基类 mouseReleaseEvent 只发 0 参数 clicked，
    与 Signal(object) 冲突导致点击无反应）。
    多选态：整图/文字区点击切换勾选，选中高亮背景；非多选态点击发 clicked(summary)。
    """

    clicked = Signal(object)  # DressCollectionSummary
    toggled = Signal(object, bool)

    _TEXT_H = 56  # 名称+徽标+边距+间距 的估算高度
    _POSTER_RATIO = 4 / 3  # 海报 高/宽 = 4/3（3:4 竖版）
    _CHECK_SIZE = 20
    _MIN_WIDTH = 120

    def __init__(self, summary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary = summary
        self.item = summary  # 网格基类约定
        self.cover_url = summary.image_cover
        self._selectable = False
        self._last_pixmap = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._accent = ThemeColor.PRIMARY.color()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        self.imageBtn = QPushButton(self)  # 海报区：点击整图触发
        self.imageBtn.setFlat(True)
        # QPushButton 垂直 size policy 默认 Fixed，布局无法拉伸 → 海报被压成 12px。
        # 设 Expanding 让它填满卡片上方区域。
        self.imageBtn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.imageBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.imageBtn.setStyleSheet(
            "QPushButton { background: rgba(128,128,128,0.12); border: none; }"
        )
        self.imageBtn.clicked.connect(self._on_image_clicked)
        layout.addWidget(self.imageBtn, 1)

        self.nameLabel = QLabel(summary.name or "未命名", self)
        self.nameLabel.setWordWrap(False)
        self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nameLabel.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #444;"
            "background: transparent; border: none;"
        )
        self.nameLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.nameLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        is_coll = is_collection(summary)
        self.badgeLabel = QLabel(category_name(summary), self)
        self.badgeLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badgeLabel.setStyleSheet(
            "color: #f69730; font-weight: 600; background: transparent; border: none;"
            if is_coll
            else "color: gray; background: transparent; border: none;"
        )
        self.badgeLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.badgeLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        self.checkBox = CheckBox(self)
        self.checkBox.setFixedSize(self._CHECK_SIZE, self._CHECK_SIZE)
        self.checkBox.setVisible(False)
        self.checkBox.toggled.connect(self._on_toggled)
        self.checkBox.raise_()

        self._apply_bg(False)

    # ---- 尺寸 ----

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 勾选框钉在卡片右上角（海报区右上）
        self.checkBox.setGeometry(
            self.width() - self._CHECK_SIZE - 8,
            8,
            self._CHECK_SIZE,
            self._CHECK_SIZE,
        )
        self.checkBox.raise_()
        self._apply_pixmap()

    # ---- 多选 API ----

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = bool(selectable)
        self.checkBox.setVisible(self._selectable)
        if not self._selectable:
            self.checkBox.setChecked(False)
        self._apply_bg(self.checkBox.isChecked())

    def set_checked(self, checked: bool) -> None:
        self.checkBox.setChecked(bool(checked))

    def is_checked(self) -> bool:
        return self.checkBox.isChecked()

    def _on_image_clicked(self) -> None:
        if self._selectable:
            self.checkBox.setChecked(not self.checkBox.isChecked())
        else:
            self.clicked.emit(self.summary)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_bg(checked)
        self.toggled.emit(self.summary, checked)

    def _apply_bg(self, checked: bool) -> None:
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
            )
        else:
            self.setStyleSheet("background-color: transparent;")

    def mousePressEvent(self, event) -> None:
        # 图片区由 imageBtn 处理；文字/空白区点击同样切换
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selectable:
                self.checkBox.setChecked(not self.checkBox.isChecked())
            else:
                self.clicked.emit(self.summary)
            return
        super().mousePressEvent(event)

    # ---- 缩略图 ----

    def set_pixmap(self, pixmap) -> None:
        self._last_pixmap = pixmap
        self._apply_pixmap()

    def _apply_pixmap(self) -> None:
        pm = self._last_pixmap
        if pm is None or pm.isNull():
            return
        rect = self.imageBtn.rect()
        if rect.isEmpty():
            return
        scaled = pm.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.imageBtn.setIcon(QIcon(scaled))
        self.imageBtn.setIconSize(scaled.size())


class DressGrid(_CardGridBase):
    """收藏集搜索结果网格：恰好两列，竖版海报卡片。"""

    summaryClicked = Signal(object)  # DressCollectionSummary

    _card_class = DressCard
    _min_cell = QSize(120, 160)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemClicked.connect(self.summaryClicked.emit)

    @staticmethod
    def _cover_url(summary):
        return summary.image_cover

    def _cell_size(self) -> QSize:
        # 恰好 4 列：单元格宽 = (视口宽 - 3*间距) // 4
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width() * 4
        w = max(self._min_cell.width(), (vw - self.spacing() * 3) // 4)
        h = round(w * DressCard._POSTER_RATIO) + DressCard._TEXT_H
        return QSize(w, h)

    def set_summaries(self, summaries) -> None:
        self.set_cards(summaries)

    def checked_summaries(self) -> list:
        return self.checked_items()


class DetailCard(QWidget):
    """收藏集详情卡片：竖版图片（等比）+ 名称。尺寸由网格 set_cell 动态给定。"""

    clicked = Signal(object)
    toggled = Signal(object, bool)

    _TEXT_H = 26  # 名称区高度估算（单行 + 边距）

    def __init__(self, item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item  # (name, url)
        name, self.url = item
        self._last_pixmap = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        self.imageBtn = QPushButton(self)
        self.imageBtn.setFlat(True)
        # QPushButton 垂直 size policy 默认 Fixed，无法被布局拉伸 → 设 Expanding
        self.imageBtn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.imageBtn.setStyleSheet(
            "QPushButton { background: rgba(128,128,128,0.12); border: none; }"
        )
        layout.addWidget(self.imageBtn, 1)

        self.nameLabel = QLabel(name or "", self)
        self.nameLabel.setWordWrap(True)
        self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nameLabel.setStyleSheet(
            "font-size: 12px; color: #909090; background: transparent; border: none;"
        )
        self.nameLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.nameLabel, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_pixmap()

    # 网格基类契约：详情只展示，无需多选/点击
    def set_selectable(self, on: bool) -> None:
        pass

    def set_checked(self, on: bool) -> None:
        pass

    def is_checked(self) -> bool:
        return False

    def set_pixmap(self, pixmap) -> None:
        self._last_pixmap = pixmap
        self._apply_pixmap()

    def _apply_pixmap(self) -> None:
        pm = self._last_pixmap
        if pm is None or pm.isNull():
            return
        rect = self.imageBtn.rect()
        if rect.isEmpty():
            return
        scaled = pm.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.imageBtn.setIcon(QIcon(scaled))
        self.imageBtn.setIconSize(scaled.size())


class DressDetailGrid(_CardGridBase):
    """收藏集详情网格：竖版图片，卡片尺寸随视口/数量动态变化，尽量撑满区域。

    项目少时卡片放大填满，项目多时自动缩小；窗口缩放时 resizeEvent 重新计算。
    """

    _card_class = DetailCard
    _min_cell = QSize(130, 200)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    @staticmethod
    def _cover_url(item):
        # item = (name, url)
        if isinstance(item, tuple):
            return item[1] if len(item) > 1 else None
        return None

    def _cell_size(self) -> QSize:
        # 选「能塞进视口、面积最大」的列数：填满区域且尽量大
        vw = self.viewport().width()
        vh = self.viewport().height()
        n = self.count()
        if vw <= 0 or n <= 0:
            return self._min_cell
        best = None
        for c in range(1, min(n, 8) + 1):
            rows = (n + c - 1) // c
            cell_w = (vw - self.spacing() * (c - 1)) / c
            icon_h = (vh - self.spacing() * (rows - 1)) / rows - DetailCard._TEXT_H
            if icon_h <= 0:
                continue
            # 竖版 4:3（高/宽）→ 图标宽 = 高 * 3/4
            icon_w = icon_h * (3 / 4)
            cell_w = min(cell_w, icon_w)
            cell_h = cell_w * (4 / 3) + DetailCard._TEXT_H
            if cell_w < self._min_cell.width() or cell_h < self._min_cell.height():
                continue
            area = cell_w * cell_h
            if best is None or area > best[2]:
                best = (cell_w, cell_h, area)
        if best is None:
            return self._min_cell
        return QSize(int(best[0]), int(best[1]))

    def set_items(self, items) -> None:
        """items: [(name, url), ...]"""
        self.set_cards(items)


class QueueCard(QWidget):
    """下载队列横向卡片：固定封面框(72×72 等比) + 名称 + 类别徽标 + ID/数量 + 右上角勾选框。

    整卡可点：多选态切换勾选 + 选中高亮；横向布局，宽度随 set_cell 自动伸展。
    """

    clicked = Signal(object)
    toggled = Signal(object, bool)

    _CHECK_SIZE = 20

    def __init__(self, item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._selectable = False
        self._last_pixmap = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._accent = ThemeColor.PRIMARY.color()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        self.imageBtn = QPushButton(self)  # 固定封面框：横/竖封面都等比适配
        self.imageBtn.setFixedSize(72, 72)
        self.imageBtn.setFlat(True)
        self.imageBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.imageBtn.setStyleSheet(
            "QPushButton { background: rgba(128,128,128,0.12); border: none; }"
        )
        self.imageBtn.clicked.connect(self._on_image_clicked)
        layout.addWidget(self.imageBtn)

        info = QVBoxLayout()
        info.setSpacing(4)
        self.nameLabel = QLabel("", self)
        self.nameLabel.setWordWrap(False)
        self.badgeLabel = QLabel("", self)
        self.metaLabel = QLabel("", self)
        for lbl in (self.nameLabel, self.badgeLabel, self.metaLabel):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info.addWidget(self.nameLabel)
        info.addWidget(self.badgeLabel)
        info.addWidget(self.metaLabel)
        layout.addLayout(info, 1)

        self.checkBox = CheckBox(self)
        self.checkBox.setFixedSize(self._CHECK_SIZE, self._CHECK_SIZE)
        self.checkBox.setVisible(False)
        self.checkBox.toggled.connect(self._on_toggled)
        self.checkBox.raise_()

        self._refresh_text()
        self._apply_bg(False)

    def _refresh_text(self) -> None:
        kind = item_kind(self.item)
        if kind == "package":
            pkg = self.item
            self.nameLabel.setText(pkg.text or ("#" + str(pkg.id)))
            self.badgeLabel.setText("GIF 动图包" if pkg.is_gif else "表情包")
            self.badgeLabel.setStyleSheet(
                "color: gray; background: transparent; border: none;"
            )
            self.metaLabel.setText(f"ID: {pkg.id}")
        else:
            s = self.item
            self.nameLabel.setText(s.name or "未命名")
            self.badgeLabel.setText(category_name(s))
            is_coll = is_collection(s)
            self.badgeLabel.setStyleSheet(
                "color: #f69730; font-weight: 600; background: transparent; border: none;"
                if is_coll
                else "color: gray; background: transparent; border: none;"
            )
            raw = s.raw or {}
            iid = raw.get("item_id") or raw.get("id") or "-"
            price = s.sale_bp_forever
            price_text = f"{price:.2f} 元" if price is not None else "价格未知"
            self.metaLabel.setText(f"ID: {iid} · {price_text}")

    # ---- 尺寸 / 多选 API ----

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.checkBox.setGeometry(
            self.width() - self._CHECK_SIZE - 8,
            8,
            self._CHECK_SIZE,
            self._CHECK_SIZE,
        )
        self.checkBox.raise_()
        self._apply_pixmap()

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = bool(selectable)
        self.checkBox.setVisible(self._selectable)
        if not self._selectable:
            self.checkBox.setChecked(False)
        self._apply_bg(self.checkBox.isChecked())

    def set_checked(self, checked: bool) -> None:
        self.checkBox.setChecked(bool(checked))

    def is_checked(self) -> bool:
        return self.checkBox.isChecked()

    def _on_image_clicked(self) -> None:
        if self._selectable:
            self.checkBox.setChecked(not self.checkBox.isChecked())
        else:
            self.clicked.emit(self.item)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_bg(checked)
        self.toggled.emit(self.item, checked)

    def _apply_bg(self, checked: bool) -> None:
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
            )
        else:
            self.setStyleSheet("background-color: transparent;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selectable:
                self.checkBox.setChecked(not self.checkBox.isChecked())
            else:
                self.clicked.emit(self.item)
            return
        super().mousePressEvent(event)

    # ---- 缩略图 ----

    def set_pixmap(self, pixmap) -> None:
        self._last_pixmap = pixmap
        self._apply_pixmap()

    def _apply_pixmap(self) -> None:
        pm = self._last_pixmap
        if pm is None or pm.isNull():
            return
        rect = self.imageBtn.rect()
        if rect.isEmpty():
            return
        scaled = pm.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.imageBtn.setIcon(QIcon(scaled))
        self.imageBtn.setIconSize(scaled.size())


class QueueList(_CardGridBase):
    """下载队列整行列表：一行一张横向卡片，宽度铺满视口（混合表情包 / 收藏集）。"""

    queueClicked = Signal(object)

    _card_class = QueueCard
    _min_cell = QSize(320, 88)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemClicked.connect(self.queueClicked.emit)

    @staticmethod
    def _cover_url(item):
        if item_kind(item) == "collection":
            return item.image_cover
        return _package_cover_url(item)

    def _cell_size(self) -> QSize:
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width()
        w = max(self._min_cell.width(), vw - self.spacing())
        return QSize(w, self._min_cell.height())

    def set_items(self, items) -> None:
        self.set_cards(items)
