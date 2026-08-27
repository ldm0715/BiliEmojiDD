"""可复用组件：表情缩略图网格、表情包卡片网格、收藏集卡片。"""
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
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CardWidget, CheckBox, FlowLayout, SmoothScrollArea
from qfluentwidgets.common.style_sheet import ThemeColor

from app.common.signal_bus import signal_bus
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

    def __init__(self, text: str, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.setFixedWidth(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        # 图标：独立区域，固定大小，永不被文字挤占
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(72, 72)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.iconLabel.setStyleSheet("background: rgba(128,128,128,0.12);")
        layout.addWidget(self.iconLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        # 文字：独立区域（图标正下方），按内容自适应高度，超长自动分行，不遮挡图标
        self.textLabel = QLabel(text or "", self)
        self.textLabel.setWordWrap(True)
        self.textLabel.setFixedWidth(96)
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

    def set_emotes(self, items: list[tuple[str, str]]) -> None:
        """items: [(text, url), ...]。url 为 None/空的行被跳过，不报错。"""
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
            card = EmojiCard(text, url)
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


class PackageGrid(QListWidget):
    """表情包卡片网格：QListWidget + setItemWidget 挂载 PackageCard。

    只对可视区域的项目请求缩略图（懒加载）。
    多选态：卡片右上角勾选框 + 选中遮罩，点击切换勾选。
    """

    packageClicked = Signal(object)  # EmotePackage
    selectionChanged = Signal()  # 勾选集合变化

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setGridSize(_PACKAGE_CELL)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._selectable = False
        self._updating = False
        self.setSpacing(8)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._requested: set[str] = set()
        self._url_cards: dict[str, list[PackageCard]] = {}
        signal_bus.thumbLoaded.connect(self._on_thumb_loaded)

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = bool(selectable)
        self._updating = True
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if isinstance(card, PackageCard):
                card.set_selectable(self._selectable)
        self._updating = False
        self.selectionChanged.emit()

    def set_packages(self, packages) -> None:
        """packages：EmotePackage 列表。"""
        self._requested.clear()
        self._url_cards.clear()
        self.clear()
        for pkg in packages:
            url = _package_cover_url(pkg)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, url)
            item.setSizeHint(PackageCard._CELL)
            card = PackageCard(pkg, self)
            card.set_selectable(self._selectable)
            card.clicked.connect(self.packageClicked.emit)
            card.toggled.connect(self._on_card_toggled)
            self.addItem(item)
            self.setItemWidget(item, card)
            if url:
                self._url_cards.setdefault(url, []).append(card)
        self._update_visible()

    def _on_card_toggled(self, pkg, checked: bool) -> None:
        if not self._updating:
            self.selectionChanged.emit()

    # ---- 多选勾选 API ----

    def checked_packages(self) -> list:
        pkgs = []
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if isinstance(card, PackageCard) and card.is_checked():
                pkgs.append(card.pkg)
        return pkgs

    def checked_count(self) -> int:
        n = 0
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if isinstance(card, PackageCard) and card.is_checked():
                n += 1
        return n

    def set_all_checked(self, checked: bool) -> None:
        self._updating = True
        for i in range(self.count()):
            card = self.itemWidget(self.item(i))
            if isinstance(card, PackageCard):
                card.set_checked(checked)
        self._updating = False
        self.selectionChanged.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._update_visible()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
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


class DressCard(CardWidget):
    """收藏集搜索结果卡片。"""

    clicked = Signal(object)

    def __init__(self, summary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary = summary
        self.cover_url = summary.image_cover

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        self.cover = QLabel(self)
        self.cover.setFixedSize(72, 72)
        self.cover.setScaledContents(True)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet("background: rgba(128,128,128,0.15);")
        layout.addWidget(self.cover)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        self.nameLabel = QLabel(summary.name or "(未命名)", self)
        self.nameLabel.setStyleSheet("font-size: 14px; font-weight: 600;")

        price = summary.sale_bp_forever
        price_text = f"{price:.2f} 元" if price is not None else "价格未知"
        meta = QHBoxLayout()
        meta.setSpacing(12)
        self.priceLabel = QLabel(price_text, self)
        self.priceLabel.setStyleSheet("color: gray;")
        self.badgeLabel = QLabel("收藏集" if summary.is_collection else "装扮", self)
        self.badgeLabel.setStyleSheet(
            "color: #f69730; font-weight: 600;"
            if summary.is_collection
            else "color: gray;"
        )
        meta.addWidget(self.priceLabel)
        meta.addWidget(self.badgeLabel)
        meta.addStretch(1)

        text_layout.addWidget(self.nameLabel)
        text_layout.addLayout(meta)
        layout.addLayout(text_layout, 1)

        # 命中缓存则立即显示封面
        if self.cover_url:
            thumb_manager.request(self.cover_url)

    def set_cover(self, pixmap) -> None:
        self.cover.setPixmap(
            pixmap.scaled(
                self.cover.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
