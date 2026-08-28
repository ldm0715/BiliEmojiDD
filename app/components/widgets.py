"""可复用组件：表情缩略图网格、表情包卡片网格、收藏集卡片、下载队列卡片。"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    InfoBadge,
    ListWidget,
    StrongBodyLabel,
    ToolTipFilter,
    ToolTipPosition,
)
from qfluentwidgets.common.style_sheet import ThemeColor

from app.common.signal_bus import signal_bus
from app.common.theme import ORANGE_TEXT, SECONDARY_TEXT, bind_theme
from app.components.download_queue import item_kind
from app.components.download_runner import (
    collection_download_dir,
    downloaded_exists,
    package_download_dir,
)
from app.components.dress_helpers import category_name, is_collection
from app.components.thumb import thumb_manager

_PACKAGE_CELL = QSize(160, 160)
_PACKAGE_ICON = QSize(96, 96)
_CARD_GUTTER = 8  # 单元格宽度预留量，保证整行不换行溢出
_SEL_INSET = 4  # 选中高亮相对卡片边缘的内缩，相邻卡片之间由此形成间隙
_BADGE_MARGIN = 6  # 「已下载」徽标距卡片右上角的边距


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
    """单个表情卡片：图标（随单元格缩放）+ 全名（独立文字组件，超长分行，不遮挡图标）。

    复用 _CardGridBase 契约：整卡可点（clicked 载荷为卡片自身），供详情页打开图片查看器。
    """

    clicked = Signal(object)  # EmojiCard 自身
    toggled = Signal(object, bool)  # 契约占位：表情不支持多选，永不触发

    def __init__(self, item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        text, url = item
        self.url = url
        self.item = item  # (text, url)
        self.index = -1  # 由网格基类填充，用于定位查看器初始图片
        self.setFixedWidth(104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        # 图标：独立区域，随单元格缩放，永不被文字挤占
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(72, 72)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.iconLabel.setStyleSheet("background: rgba(128,128,128,0.12);")
        layout.addWidget(self.iconLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        # 文字：独立区域（图标正下方），按内容自适应高度，超长自动分行，不遮挡图标
        self.textLabel = CaptionLabel(text or "", self)
        self.textLabel.setTextColor(*SECONDARY_TEXT)
        self.textLabel.setWordWrap(True)
        self.textLabel.setFixedWidth(96)
        self.textLabel.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        # 无文字时不占高度，卡片更紧凑
        if not (text or "").strip():
            self.textLabel.hide()
        layout.addWidget(self.textLabel, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_cell(self, size: QSize) -> None:
        """按单元格尺寸重排：图标撑宽，文字宽度对齐。"""
        self.setFixedSize(size)
        icon = max(24, size.width() - 8)
        self.iconLabel.setFixedSize(icon, icon)
        self.textLabel.setFixedWidth(size.width() - 8)

    def set_selectable(self, selectable: bool) -> None:
        """契约占位：表情不支持多选。"""

    def set_checked(self, checked: bool) -> None:
        pass

    def is_checked(self) -> bool:
        return False

    def set_pixmap(self, pixmap) -> None:
        self.iconLabel.setPixmap(
            pixmap.scaled(
                self.iconLabel.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
            return
        super().mousePressEvent(event)


class PackageCard(QWidget):
    """表情包卡片：图片按钮（撑满）+ 居中文字 + 右上角勾选框 + 选中背景。

    用布局自适应单元格尺寸；图片用 QPushButton(setFlat=True) 点击整图触发勾选；
    勾选框 setGeometry 钉在图片左上角 + raise_()（右上角是「已下载」徽标）；toggled 同步整卡背景色。
    点击卡片：多选态切换勾选，非多选态发 clicked。
    """

    clicked = Signal(object)  # EmotePackage
    toggled = Signal(object, bool)  # (pkg, checked)

    _TEXT_H = 42  # 底部文字区估算高度
    _CHECK_SIZE = 20

    def __init__(self, pkg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pkg = pkg
        self.item = pkg  # 网格基类约定：payload 统一叫 .item
        self._selectable = False
        self._last_pixmap = None
        self.setFixedSize(160, 160)
        # 普通 QWidget 需此属性才会绘制 stylesheet 的 background-color（选中背景）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)

        # 图片按钮：flat、透明、撑满剩余空间，点击整图触发
        # 注意：QPushButton 垂直 size policy 默认 Fixed，stretch 拉不撑，必须显式 Expanding
        self.imageBtn = QPushButton(self)
        self.imageBtn.setFlat(True)
        self.imageBtn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.imageBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.imageBtn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
        )
        self.imageBtn.clicked.connect(self._on_image_clicked)
        layout.addWidget(self.imageBtn, 1)

        # 文字：居中，宽度对齐图片
        self.textLabel = CaptionLabel(self)
        self.textLabel.setTextColor(*SECONDARY_TEXT)
        self.textLabel.setWordWrap(True)
        self.textLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.textLabel.setText(f"{pkg.text or ('#' + str(pkg.id))}\nID: {pkg.id}")
        self.textLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.textLabel, 0)

        # 勾选框：图片右上角，置顶
        self.checkBox = CheckBox(self)
        self.checkBox.setFixedSize(self._CHECK_SIZE, self._CHECK_SIZE)
        self.checkBox.setVisible(False)
        self.checkBox.toggled.connect(self._on_toggled)
        self.checkBox.raise_()

        # 「已下载」徽标：钉右上角，勾选框在左上角，两者可同时显示
        self._downloaded = downloaded_exists(package_download_dir(pkg))
        self.downloadedBadge = InfoBadge.success("已下载", self)
        self.downloadedBadge.setVisible(self._downloaded)

        self._accent = ThemeColor.PRIMARY.color()
        self._apply_bg(False)
        bind_theme(self, self._apply_theme)
        self._pin_checkbox()

    def _pin_badge(self) -> None:
        b = self.downloadedBadge
        b.adjustSize()
        b.move(self.width() - b.width() - _BADGE_MARGIN, _BADGE_MARGIN)
        b.raise_()

    def refresh_downloaded(self) -> None:
        """重新检查目标目录（下载完成后调用）。"""
        self._downloaded = downloaded_exists(package_download_dir(self.pkg))
        self.downloadedBadge.setVisible(self._downloaded)
        self._pin_badge()

    def _pin_checkbox(self) -> None:
        # 钉在图片左上角：右上角留给「已下载」徽标，两者同时显示不打架
        img = self.imageBtn.geometry()
        self.checkBox.setGeometry(
            img.left() + 4,
            img.top() + 4,
            self._CHECK_SIZE,
            self._CHECK_SIZE,
        )
        self.checkBox.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._pin_checkbox()
        self._pin_badge()
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

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

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

    def _on_image_clicked(self) -> None:
        if self._selectable:
            self.checkBox.setChecked(not self.checkBox.isChecked())
        else:
            self.clicked.emit(self.pkg)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_bg(checked)
        self.toggled.emit(self.pkg, checked)

    def _apply_theme(self) -> None:
        self._accent = ThemeColor.PRIMARY.color()
        self._apply_bg(self.checkBox.isChecked())

    def _apply_bg(self, checked: bool) -> None:
        # 类选择器限定自身：避免通用 * 规则把背景级联到子 label（文字区整块上色）
        # margin 让高亮从卡片边缘内缩：QListView 在 gridSize 模式下把首列卡片右移
        # 一格、其余列不移，卡片自身留不出均匀间隙，只能内缩背景来分隔相邻卡片
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"PackageCard {{ background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
                f" margin: {_SEL_INSET}px; border-radius: 6px; }}"
            )
        else:
            self.setStyleSheet(
                f"PackageCard {{ background-color: transparent;"
                f" margin: {_SEL_INSET}px; }}"
            )

    def mousePressEvent(self, event) -> None:
        # 图片区由 imageBtn 处理；文字区点击同样切换
        if event.button() == Qt.MouseButton.LeftButton:
            if self._selectable:
                self.checkBox.setChecked(not self.checkBox.isChecked())
            else:
                self.clicked.emit(self.pkg)
            return
        super().mousePressEvent(event)


class _CardGridBase(ListWidget):
    """qfluentwidgets ListWidget + setItemWidget 网格基类：懒加载缩略图 + 多选 API + 动态单元格。

    基类用组件库的 `ListWidget`（不是裸 QListWidget）：它在 `ListBase.__init__` 里
    `FluentStyleSheet.LIST_VIEW.apply(self)` 把自己注册进 styleSheetManager，
    每次 setTheme 都会被 updateStyleSheet 重刷 QSS —— 容器与滚动条自动跟随主题。

    子类约定：
      _card_class     卡片类，构造签名 (item, parent)，暴露 .item / set_selectable /
                      set_checked / is_checked / set_pixmap / set_cell /
                      clicked(object) / toggled(object, bool)
      _cover_url(item) 返回封面缩略图 URL（可 None）
      _cell_size()     返回当前单元格 QSize
      _min_cell        最小单元格 QSize
    点击统一走 self.itemClicked(object)（载荷为 item）与 self.itemClickedAt(int, object)
    （附带下标），子类在 __init__ 转发到公开信号。
    """

    itemClicked = Signal(object)  # 载荷为卡片对应的 item
    itemClickedAt = Signal(int, object)  # (下标, item)：内容重复时也能定位
    selectionChanged = Signal()  # 勾选集合变化

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # spacing 在 gridSize 模式下只把第 0 项右移一格间距、步进却仍是
        # gridSize.width() —— 头两列会贴死。间隙改由 _CARD_GUTTER 直接做进单元格。
        self.setSpacing(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._selectable = False
        self._updating = False
        self._requested: set[str] = set()
        self._url_cards: dict[str, list] = {}
        self._items: list = []
        self._last_cell: QSize | None = None
        signal_bus.thumbLoaded.connect(self._on_thumb_loaded)
        # 垂直滚动条出现/消失会收窄视口，双列网格（QueueList）需随之重排，防横向溢出
        self.verticalScrollBar().rangeChanged.connect(lambda *_: self._layout_items())

    # ---- 数据填充 ----

    def set_cards(self, items) -> None:
        """items：与 _card_class 构造签名匹配的载荷对象列表。"""
        self._requested.clear()
        self._url_cards.clear()
        self.clear()
        self._items = list(items)
        for index, it in enumerate(self._items):
            url = self._cover_url(it)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, url)
            card = self._card_class(it, self)
            card.set_selectable(self._selectable)
            # 用建卡时的下标做闭包：不能靠 item 身份反查，内容相同的载荷（如
            # (name, url) 元组字面量）会被 CPython 常量折叠成同一个对象
            card.clicked.connect(partial(self._emit_clicked, index))
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

    def _emit_clicked(self, index: int, it) -> None:
        self.itemClicked.emit(it)
        self.itemClickedAt.emit(index, it)

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
    """表情包卡片网格（旧 API 包装）：ListWidget + setItemWidget 挂载 PackageCard。

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
        # 与 DressGrid 同款：按视口算列数（上限 8），正方形卡片填满整行
        # 注意：setGridSize 生效后 QListView 忽略 spacing()，步进就是 gridSize.width()，
        # 所以这里按 vw // n 均分整行；卡片自身的 contentsMargins 充当间隙。
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width() * 5
        n = min(8, max(1, vw // (self._min_cell.width() + _CARD_GUTTER)))
        w = max(self._min_cell.width(), (vw - _CARD_GUTTER) // n)
        return QSize(w, w)

    def set_packages(self, packages) -> None:
        """packages：EmotePackage 列表。"""
        self.set_cards(packages)

    def checked_packages(self) -> list:
        return self.checked_items()


class EmojiGrid(_CardGridBase):
    """表情网格：复用 _CardGridBase，卡片随视口宽度响应式填满（与收藏集网格一致）。

    点击任一卡片发 imageClicked(index)，索引对应 items() 返回的 (text, url) 列表。
    """

    imageClicked = Signal(int)

    _card_class = EmojiCard
    _min_cell = QSize(72, 96)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self.itemClickedAt.connect(self._emit_image)

    @staticmethod
    def _cover_url(item):
        return item[1] if isinstance(item, tuple) else item.url

    def _cell_size(self) -> QSize:
        # 与 DressGrid 同款：按视口算列数（上限 8），正方形图标 + 底部文字，填满整行
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width() * 6
        n = min(8, max(1, vw // (self._min_cell.width() + _CARD_GUTTER)))
        w = max(self._min_cell.width(), (vw - _CARD_GUTTER) // n)
        return QSize(w, w + 36)

    def items(self) -> list[tuple[str, str]]:
        """实际建卡的 (text, url) 列表（已过滤空 url），与 imageClicked 索引一致。"""
        return list(self._items)

    def set_emotes(self, items) -> None:
        """items: [(text, url), ...]。url 为 None/空的行被跳过，不报错。"""
        self._items = [(text or "", url) for text, url in items if url]
        self.set_cards(self._items)

    def _emit_image(self, index: int, _card) -> None:
        self.imageClicked.emit(index)


class DressCard(QWidget):
    """收藏集搜索结果竖版卡片：封面(上, 3:4 等比) + 名称 + 分类徽标 + 右上角勾选框。

    纯 QWidget（不用 CardWidget：其基类 mouseReleaseEvent 只发 0 参数 clicked，
    与 Signal(object) 冲突导致点击无反应）。
    多选态：整图/文字区点击切换勾选，选中高亮背景；非多选态点击发 clicked(summary)。
    """

    clicked = Signal(object)  # DressCollectionSummary
    toggled = Signal(object, bool)

    _NAME_H = 40  # 名称区固定两行高（StrongBodyLabel 14pt 行高约 20）
    _TEXT_H = 76  # 名称两行 + 徽标 + 边距 + 间距 的估算高度
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

        self.nameLabel = StrongBodyLabel(summary.name or "未命名", self)
        # 长名换行（最多两行），并挂 tooltip 兜底完整名称——不换行的 QLabel 会把
        # 超长文字直接裁掉且不加省略号，用户根本看不到原文
        self.nameLabel.setWordWrap(True)
        self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nameLabel.setFixedHeight(self._NAME_H)
        self.nameLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip(summary.name or "未命名")
        self.installEventFilter(ToolTipFilter(self, 500, ToolTipPosition.TOP))
        layout.addWidget(self.nameLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        self.badgeLabel = CaptionLabel(category_name(summary), self)
        self.badgeLabel.setTextColor(
            *(ORANGE_TEXT if is_collection(summary) else SECONDARY_TEXT)
        )
        self.badgeLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badgeLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.badgeLabel, 0, Qt.AlignmentFlag.AlignHCenter)

        self.checkBox = CheckBox(self)
        self.checkBox.setFixedSize(self._CHECK_SIZE, self._CHECK_SIZE)
        self.checkBox.setVisible(False)
        self.checkBox.toggled.connect(self._on_toggled)
        self.checkBox.raise_()

        # 「已下载」徽标：钉右上角，勾选框在左上角，两者可同时显示
        self._downloaded = downloaded_exists(collection_download_dir(summary))
        self.downloadedBadge = InfoBadge.success("已下载", self)
        self.downloadedBadge.setVisible(self._downloaded)

        bind_theme(self, self._apply_theme)

    def _pin_badge(self) -> None:
        b = self.downloadedBadge
        b.adjustSize()
        b.move(self.width() - b.width() - _BADGE_MARGIN, _BADGE_MARGIN)
        b.raise_()

    def refresh_downloaded(self) -> None:
        """重新检查目标目录（下载完成后调用）。"""
        self._downloaded = downloaded_exists(collection_download_dir(self.summary))
        self.downloadedBadge.setVisible(self._downloaded)
        self._pin_badge()

    # ---- 主题 ----

    def _apply_theme(self) -> None:
        self.badgeLabel.setTextColor(
            *(ORANGE_TEXT if is_collection(self.summary) else SECONDARY_TEXT)
        )
        self._accent = ThemeColor.PRIMARY.color()
        self._apply_bg(self.checkBox.isChecked())

    # ---- 尺寸 ----

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 勾选框钉在卡片左上角：右上角留给「已下载」徽标，两者同时显示不打架
        self.checkBox.setGeometry(
            8,
            8,
            self._CHECK_SIZE,
            self._CHECK_SIZE,
        )
        self.checkBox.raise_()
        self._pin_badge()
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
        # 类选择器限定自身：避免通用 * 规则把背景级联到子 label（文字区整块上色）
        # margin 让高亮从卡片边缘内缩：QListView 在 gridSize 模式下把首列卡片右移
        # 一格、其余列不移，卡片自身留不出均匀间隙，只能内缩背景来分隔相邻卡片
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"DressCard {{ background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
                f" margin: {_SEL_INSET}px; border-radius: 6px; }}"
            )
        else:
            self.setStyleSheet(
                f"DressCard {{ background-color: transparent;"
                f" margin: {_SEL_INSET}px; }}"
            )

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
        # 恰好 4 列：单元格宽 = 视口宽 // 4（gridSize 生效后 spacing 不参与步进）
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width() * 4
        w = max(self._min_cell.width(), (vw - _CARD_GUTTER) // 4)
        h = round(w * DressCard._POSTER_RATIO) + DressCard._TEXT_H
        return QSize(w, h)

    def set_summaries(self, summaries) -> None:
        self.set_cards(summaries)

    def checked_summaries(self) -> list:
        return self.checked_items()


class DetailCard(QWidget):
    """收藏集详情卡片：竖版图片（等比）+ 名称。尺寸由网格 set_cell 动态给定。

    整卡可点（clicked 载荷为 (name, url) 元组），供详情页打开图片查看器。
    """

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
        self.imageBtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.imageBtn.setStyleSheet(
            "QPushButton { background: rgba(128,128,128,0.12); border: none; }"
        )
        self.imageBtn.clicked.connect(self._on_image_clicked)
        layout.addWidget(self.imageBtn, 1)

        self.nameLabel = CaptionLabel(name or "", self)
        self.nameLabel.setTextColor(*SECONDARY_TEXT)
        self.nameLabel.setWordWrap(True)
        self.nameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nameLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.nameLabel, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_cell(self, size: QSize) -> None:
        self.setFixedSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_pixmap()

    def _on_image_clicked(self) -> None:
        self.clicked.emit(self.item)

    def mousePressEvent(self, event) -> None:
        # 图片区由 imageBtn 处理；文字区点击同样触发
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
            return
        super().mousePressEvent(event)

    # 网格基类契约：详情只展示，无需多选
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
    点击任一卡片发 imageClicked(index)，索引对应 set_items 传入的列表。
    """

    imageClicked = Signal(int)

    _card_class = DetailCard
    _min_cell = QSize(130, 200)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemClickedAt.connect(lambda i, _: self.imageClicked.emit(i))

    @staticmethod
    def _cover_url(item):
        # item = (name, url)
        if isinstance(item, tuple):
            return item[1] if len(item) > 1 else None
        return None

    def _cell_size(self) -> QSize:
        # 选「能塞进视口、图片最大」的列数，单元格再按整行均分铺满。
        # 两个关键点：
        #  1. setGridSize 生效后 QListView 忽略 spacing()，步进即 gridSize.width()，
        #     且换行判据是 c*cellW > vw-1，所以按 (vw-1)/c 均分；
        #  2. 图片受高度限制被压窄时，单元格仍取满整份宽度——多出来的宽度变成每张
        #     图两侧的均匀留白（QPushButton 居中画图标），而不是全堆在最右侧。
        vw = self.viewport().width()
        vh = self.viewport().height()
        n = self.count()
        if vw <= 0 or n <= 0:
            return self._min_cell
        # 列数上限放开到「视口最多塞下几个最小卡」，卡死 8 列会在右侧留下大片空白
        max_cols = min(n, max(1, vw // self._min_cell.width()))
        best = None
        for c in range(1, max_cols + 1):
            rows = (n + c - 1) // c
            share_w = (vw - _CARD_GUTTER) / c  # 该列数下每格能分到的宽度
            icon_h = vh / rows - DetailCard._TEXT_H
            if icon_h <= 0:
                continue
            # 竖版 4:3（高/宽）→ 图片宽 = 高 * 3/4，再受每格宽度上限
            img_w = min(share_w, icon_h * (3 / 4))
            img_h = img_w * (4 / 3)
            if img_w < self._min_cell.width():
                continue
            cell_h = img_h + DetailCard._TEXT_H
            if cell_h < self._min_cell.height():
                continue
            area = img_w * img_h  # 以「图片」面积评分，不含填充留白
            # >= 让并列面积时取更多列（同样大小下把整行铺得更满）
            if best is None or area >= best[2]:
                best = (share_w, cell_h, area)
        if best is None:
            return self._min_cell
        return QSize(int(best[0]), int(best[1]))

    def set_items(self, items) -> None:
        """items: [(name, url), ...]"""
        self.set_cards(items)


class QueueCard(QWidget):
    """下载队列横向卡片：自适应封面框(方块) + 名称 + 类别徽标 + ID/数量 + 右上角勾选框。

    整卡可点：多选态切换勾选 + 选中高亮；横向布局，宽度随 set_cell 自动伸展。
    名称可换行（防截断），信息区右侧预留勾选框空间防遮挡。
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
        # 右侧预留勾选框区域，长名换行也不跑到勾选框下面
        info.setContentsMargins(0, 0, 24, 0)
        self.nameLabel = StrongBodyLabel("", self)
        self.nameLabel.setWordWrap(True)
        self.badgeLabel = CaptionLabel("", self)
        self.metaLabel = CaptionLabel("", self)
        self.metaLabel.setTextColor(*SECONDARY_TEXT)
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
        bind_theme(self, self._apply_theme)

    def _refresh_text(self) -> None:
        kind = item_kind(self.item)
        if kind == "package":
            pkg = self.item
            self.nameLabel.setText(pkg.text or ("#" + str(pkg.id)))
            self.badgeLabel.setText("GIF 动图包" if pkg.is_gif else "表情包")
            self.metaLabel.setText(f"ID: {pkg.id}")
        else:
            s = self.item
            self.nameLabel.setText(s.name or "未命名")
            self.badgeLabel.setText(category_name(s))
            raw = s.raw or {}
            iid = raw.get("item_id") or raw.get("id") or "-"
            price = s.sale_bp_forever
            price_text = f"{price:.2f} 元" if price is not None else "价格未知"
            self.metaLabel.setText(f"ID: {iid} · {price_text}")

    # ---- 主题 ----

    def _refresh_badge(self) -> None:
        """徽标颜色：表情包 / 装扮用次要色，收藏集用品牌橙（两主题均可读）。"""
        if item_kind(self.item) == "package":
            colors = SECONDARY_TEXT
        else:
            colors = ORANGE_TEXT if is_collection(self.item) else SECONDARY_TEXT
        self.badgeLabel.setTextColor(*colors)

    def _apply_theme(self) -> None:
        self._refresh_badge()
        self._accent = ThemeColor.PRIMARY.color()
        self._apply_bg(self.checkBox.isChecked())

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
        # 封面随卡宽/高自适应方块；值未变化时不动，避免 setFixedSize 触发递归布局
        img = max(72, min(self.height() - 16, round(self.width() * 0.28)))
        if self.imageBtn.width() != img:
            self.imageBtn.setFixedSize(img, img)
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
        # 类选择器限定自身：避免通用 * 规则把背景级联到子 label（文字区整块上色）
        # margin 让高亮从卡片边缘内缩：QListView 在 gridSize 模式下把首列卡片右移
        # 一格、其余列不移，卡片自身留不出均匀间隙，只能内缩背景来分隔相邻卡片
        if self._selectable and checked:
            a = self._accent
            self.setStyleSheet(
                f"QueueCard {{ background-color: rgba({a.red()}, {a.green()}, {a.blue()}, 70);"
                f" margin: {_SEL_INSET}px; border-radius: 6px; }}"
            )
        else:
            self.setStyleSheet(
                f"QueueCard {{ background-color: transparent;"
                f" margin: {_SEL_INSET}px; }}"
            )

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
    """下载队列网格（混合表情包 / 收藏集）：宽视口两列、窄视口单列，随窗口缩放实时切换。"""

    queueClicked = Signal(object)

    _card_class = QueueCard
    _min_cell = QSize(300, 112)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.itemClicked.connect(self.queueClicked.emit)

    @staticmethod
    def _cover_url(item):
        if item_kind(item) == "collection":
            return item.image_cover
        return _package_cover_url(item)

    def _cell_size(self) -> QSize:
        # 响应式列数：可用宽度放得下两列（各至少 _min_cell 宽）→ 两列，否则单列铺满。
        # setGridSize 生效后 QListView 忽略 spacing()，步进即 gridSize.width()，
        # 所以直接均分视口宽：两列 vw//2、单列 vw，数学上不横向溢出。
        vw = self.viewport().width()
        if vw <= 0:
            vw = self._min_cell.width() * 2
        if vw >= 2 * self._min_cell.width():
            w = (vw - _CARD_GUTTER) // 2
        else:
            w = vw - _CARD_GUTTER
        return QSize(max(1, w), self._min_cell.height())

    def set_items(self, items) -> None:
        self.set_cards(items)
