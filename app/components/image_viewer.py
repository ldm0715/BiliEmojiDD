"""详情页图片查看器：窗口内遮罩 lightbox + 左右翻页。

轮播直接复用 qfluentwidgets 的 HorizontalFlipView（自带悬浮左右箭头 / 滚轮翻页 /
平滑滚动动画），遮罩层复用 MaskDialogBase，页码点复用 HorizontalPipsPager。
图片加载复用 thumb_manager + signal_bus.thumbLoaded（详情页给的 URL 本身就是原图，
全尺寸 QPixmap 已缓存在 QPixmapCache，命中即刻返回、未命中自动走后台线程池）。

已知限制：GIF 只显示首帧。FlipView 存的是 QImage，动图需要 QMovie，其 delegate 不支持；
与网格缩略图观感一致（网格本来也是首帧静图）。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    HorizontalFlipView,
    HorizontalPipsPager,
    TransparentToolButton,
)

# MaskDialogBase 未从 qfluentwidgets 顶层导出（dialog_box/__init__.py 只导 5 个类），
# 按项目既有做法（widgets.py 的 ThemeColor）从子模块直接导入。
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

from app.common.signal_bus import signal_bus
from app.components.thumb import thumb_manager

_MAX_W = 900
_MAX_H = 700
_MAX_UPSCALE = 2  # 小图最多放大几倍（表情只有一两百像素，完全不放大会显得过小）
_PREFETCH = 2  # 当前索引前后各预取几张
_MAX_PIPS = 15  # 超过这个数量就不显示页码点（点太多没意义）


def _viewer_item_size(parent: QWidget) -> QSize:
    """按主窗口尺寸算出图片区尺寸。"""
    w = min(int(parent.width() * 0.62), _MAX_W)
    h = min(int(parent.height() * 0.70), _MAX_H)
    return QSize(max(w, 320), max(h, 240))


def _canvas_size(target: QSize, dpr: float) -> QSize:
    return QSize(int(target.width() * dpr), int(target.height() * dpr))


def _placeholder(target: QSize, dpr: float) -> QImage:
    """未加载时的占位画布：极淡的白，用来提示"图片框"位置。"""
    canvas = QImage(_canvas_size(target, dpr), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(255, 255, 255, 18))
    return canvas


def _letterbox(pixmap: QPixmap, target: QSize, dpr: float) -> QImage:
    """等比缩放后居中合成到 target*dpr 的透明画布上。

    画布尺寸恒等于 target*dpr，配合 _ViewerFlipView 的固定 sizeHint，
    使 FlipImageDelegate 里的 image.scaled(size * r, ...) 成为恒等变换 ——
    既不拉伸、DPI 又正确，且图片异步到位时 item 尺寸不变、滚动位置不会跑偏。
    """
    canvas_size = _canvas_size(target, dpr)
    canvas = QImage(canvas_size, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    if pixmap is None or pixmap.isNull():
        return canvas
    # 目标框取「画布尺寸」与「原图尺寸 × 上限倍数」的较小者，避免小图被过度放大糊掉
    box = canvas_size.boundedTo(pixmap.size() * _MAX_UPSCALE)
    scaled = pixmap.toImage().scaled(
        box,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(canvas)
    painter.drawImage(
        (canvas_size.width() - scaled.width()) // 2,
        (canvas_size.height() - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    return canvas


class _ViewerFlipView(HorizontalFlipView):
    """针对 lightbox 调整行为的 FlipView（覆写三处，详见各方法注释）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # FlipView 继承 QListWidget，会吞掉方向键去改 currentRow；交给 dialog 处理
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 保证 viewport 宽度 == 控件宽度 == item 宽度，否则会露出下一张的边缘
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(0, 0, 0, 0)

    def _adjustItemSize(self, item) -> None:
        """所有 item 尺寸恒等于 itemSize。

        上游实现按图片宽高比算 sizeHint，有两个问题：
        1. 图片未加载时 QImage() 高为 0 → KeepAspectRatio 分支除零崩；
        2. 图片异步到位后 sizeHint 变化，而 scrollToIndex 按前序 item 宽度累加算
           滚动量 → 已显示的图会跑偏。
        统一 sizeHint 后两个问题都消失（代价是图片需预先 letterbox）。
        """
        item.setSizeHint(self.itemSize)

    def sync_arrows(self) -> None:
        """按首尾直接设定左右箭头透明度。

        上游只在 hover 时淡入箭头，但遮罩层里没有别的可交互元素，藏起来太难发现，
        这里改成常显。必须先 stop 掉上游 setCurrentIndex/enterEvent 起的淡入淡出动画，
        否则动画会盖掉这里设的值。
        """
        index = self.currentIndex()
        last = self.count() - 1
        for button, visible in (
            (self.preButton, index > 0),
            (self.nextButton, 0 <= index < last),
        ):
            button.opacityAni.stop()
            button.setOpacity(1.0 if visible else 0.0)

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        self.sync_arrows()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)  # 上游会 fadeOut 两个箭头
        self.sync_arrows()  # 立刻改回常显


class ImageViewer(MaskDialogBase):
    """遮罩图片查看器：居中大图 + 左右翻页 + 名称/页码/页码点。

    关闭方式：Esc、点击遮罩空白处、右上角关闭按钮。
    翻页方式：悬浮左右箭头、方向键、鼠标滚轮。
    """

    def __init__(self, items, index: int, parent: QWidget) -> None:
        super().__init__(parent=parent)
        self._items = list(items)
        self._syncing = False
        self._requested: set[str] = set()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # setMaskColor 有上游 bug：rgba(red, blue, green, alpha) —— B/G 写反了。
        # 用纯黑正好绕过（R=G=B=0），不要改成其他彩色遮罩。
        self.setMaskColor(QColor(0, 0, 0, 180))

        # 上游 MaskDialogBase 把 self.widget 无对齐地塞进 _hBoxLayout → 铺满整个 dialog，
        # 「点击遮罩空白处关闭」就永远判不出来。按 MessageBoxBase 的做法重新居中添加。
        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(self.widget, 1, Qt.AlignmentFlag.AlignCenter)
        self.widget.setGraphicsEffect(None)  # 透明容器上的投影只会糊在子控件周围
        self.widget.setStyleSheet("background: transparent;")

        self._item_size = _viewer_item_size(parent)
        self._dpr = self.devicePixelRatioF()

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.flipView = _ViewerFlipView(self.widget)
        self.flipView.setItemSize(self._item_size)
        self.flipView.setFixedSize(self._item_size)
        self.flipView.setBorderRadius(8)
        layout.addWidget(self.flipView, 0, Qt.AlignmentFlag.AlignHCenter)

        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.nameLabel = CaptionLabel("", self.widget)
        self.nameLabel.setStyleSheet("color: white; background: transparent;")
        self.countLabel = CaptionLabel("", self.widget)
        self.countLabel.setStyleSheet(
            "color: rgba(255, 255, 255, 0.6); background: transparent;"
        )
        info_row.addStretch(1)
        info_row.addWidget(self.nameLabel)
        info_row.addWidget(self.countLabel)
        info_row.addStretch(1)
        layout.addLayout(info_row)

        self.pips = HorizontalPipsPager(self.widget)
        self.pips.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 别抢走方向键
        self.pips.setPageNumber(len(self._items))
        self.pips.setVisibleNumber(min(len(self._items), 10))
        self.pips.setVisible(1 < len(self._items) <= _MAX_PIPS)
        layout.addWidget(self.pips, 0, Qt.AlignmentFlag.AlignHCenter)

        self.closeBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeBtn.setFixedSize(36, 36)
        self.closeBtn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.closeBtn.clicked.connect(self.reject)
        # 基类 __init__ 里已 setGeometry 过，之后未必再触发 resizeEvent → 主动摆一次
        self._place_close_button()

        # 先建满 n 项：placeholder 给出「图片框」占位，同时避开上游的空图除零
        placeholder = _placeholder(self._item_size, self._dpr)
        self.flipView.addImages([placeholder] * len(self._items))

        # 必须先 connect 再 request：request() 命中 QPixmapCache 时是同步 emit
        signal_bus.thumbLoaded.connect(self._on_thumb)
        self.finished.connect(self._on_finished)

        self.flipView.currentIndexChanged.connect(self._on_index_changed)
        # pips 已 setPageNumber 完（它内部 setCurrentIndex(0) 会发信号），此时才接线
        self.pips.currentIndexChanged.connect(self.flipView.setCurrentIndex)

        index = max(0, min(index, len(self._items) - 1))
        self.flipView.setCurrentIndex(index)
        # FlipView.setCurrentIndex 在 index == currentIndex() 时早退不发信号，
        # 而 addImages 已把 _currentIndex 置为 0 → 初始 index 为 0 时须手动同步一次
        self._sync_ui(index)
        self._prefetch(index)

    # ---- 图片加载 ----

    def _prefetch(self, index: int) -> None:
        """只取当前索引 ±_PREFETCH：一次性请求几十张会占满缩略图池、拖慢背后网格。"""
        lo = max(0, index - _PREFETCH)
        hi = min(len(self._items), index + _PREFETCH + 1)
        for i in range(lo, hi):
            url = self._items[i][1]
            if url and url not in self._requested:
                self._requested.add(url)
                thumb_manager.request(url)

    def _on_thumb(self, url: str, pixmap) -> None:
        image = None
        for i, (_, item_url) in enumerate(self._items):
            if item_url != url:
                continue
            if image is None:  # 同一 URL 多处复用时只合成一次
                image = _letterbox(pixmap, self._item_size, self._dpr)
            self.flipView.setItemImage(i, image)

    def _on_finished(self) -> None:
        try:
            signal_bus.thumbLoaded.disconnect(self._on_thumb)
        except (RuntimeError, TypeError):
            pass

    # ---- 索引同步 ----

    def _on_index_changed(self, index: int) -> None:
        self._sync_ui(index)
        self._prefetch(index)

    def _sync_ui(self, index: int) -> None:
        if self._syncing:
            return
        # pips.setCurrentIndex 会回发 currentIndexChanged → flipView，这里加 guard 防回环
        self._syncing = True
        try:
            name = self._items[index][0] if self._items else ""
            self.nameLabel.setText(name or "")
            self.nameLabel.setVisible(bool(name))
            self.countLabel.setText(f"{index + 1} / {len(self._items)}")
            self.pips.setCurrentIndex(index)
            self.flipView.sync_arrows()
        finally:
            self._syncing = False

    # ---- 交互 ----

    def keyPressEvent(self, e) -> None:
        key = e.key()
        if key == Qt.Key.Key_Left:
            self.flipView.scrollPrevious()
            return
        if key == Qt.Key.Key_Right:
            self.flipView.scrollNext()
            return
        super().keyPressEvent(e)  # Esc 由 QDialog 默认处理成 reject

    def mousePressEvent(self, e) -> None:
        # 点击居中内容区之外的遮罩 → 关闭
        if not self.widget.geometry().contains(e.pos()):
            self.reject()
            return
        super().mousePressEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_close_button()

    def _place_close_button(self) -> None:
        self.closeBtn.move(self.width() - self.closeBtn.width() - 16, 16)
        self.closeBtn.raise_()


def show_image_viewer(items, index: int, parent: QWidget) -> None:
    """弹出图片查看器。

    items: [(name, url), ...]；index: 初始显示的下标；parent: 传 page.window()。
    """
    if not items or parent is None:
        return
    ImageViewer(items, index, parent).exec()
