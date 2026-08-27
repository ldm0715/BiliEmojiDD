"""可复用组件：表情缩略图网格、表情包卡片网格、收藏集卡片。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CardWidget, FlowLayout, SmoothScrollArea

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


class PackageGrid(QListWidget):
    """表情包卡片网格：每个包一张卡，封面用第一张表情，点击进入包详情。

    只对可视区域的项目提交缩略图请求（懒加载）。
    """

    packageClicked = Signal(object)  # EmotePackage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setIconSize(_PACKAGE_ICON)
        self.setGridSize(_PACKAGE_CELL)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setSpacing(8)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._requested: set[str] = set()
        self._url_items: dict[str, list[QListWidgetItem]] = {}
        self.itemClicked.connect(self._on_item_clicked)
        signal_bus.thumbLoaded.connect(self._on_thumb_loaded)

    def set_packages(self, packages) -> None:
        """packages：EmotePackage 列表。"""
        self._requested.clear()
        self._url_items.clear()
        self.clear()
        for pkg in packages:
            url = _package_cover_url(pkg)
            label = f"{pkg.text or ('#' + str(pkg.id))}\nID: {pkg.id}"
            item = QListWidgetItem(QIcon(), label)
            item.setData(Qt.ItemDataRole.UserRole, url)
            item.setData(Qt.ItemDataRole.UserRole + 1, pkg)
            item.setSizeHint(_PACKAGE_CELL)
            self.addItem(item)
            if url:
                self._url_items.setdefault(url, []).append(item)
        self._update_visible()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        pkg = item.data(Qt.ItemDataRole.UserRole + 1)
        if pkg is not None:
            self.packageClicked.emit(pkg)

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
        for item in self._url_items.get(url, ()):
            item.setIcon(QIcon(pixmap))


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
