"""页面版式底座：统一页边距、页面大标题与卡片容器。

四个页面共用同一套 Fluent 版式：大标题 → 命令卡（工具栏）→ 内容（网格 / 带标题的内容卡）。
卡片一律用组件库的 `SimpleCardWidget` / `HeaderCardWidget`——它们构造时
`FluentStyleSheet.CARD_WIDGET.apply(self)` 且连了 `qconfig.themeChanged`，主题切换自动重绘。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    HeaderCardWidget,
    IndeterminateProgressRing,
    InfoBadge,
    InfoLevel,
    PushButton,
    SimpleCardWidget,
    TitleLabel,
)

PAGE_MARGIN = 36  # 页面左右边距（四页统一，含设置页）
PAGE_TOP = 20  # 大标题上方留白
PAGE_BOTTOM = 24  # 页面底部留白
SECTION_SPACING = 12  # 卡片 / 内容块之间的间距

_RING_SIZE = 14  # 按钮内加载环直径
_RING_GAP = 10  # 加载环与文字之间的空隙
_BTN_PAD = 28  # 按钮左右内边距估值，用于预留忙碌态宽度


class BusyPushButton(PushButton):
    """带加载环的按钮：忙碌时文字前面转圈，明示「正在跑」。

    组件库没有 loading 态按钮，这里自己拼：`IndeterminateProgressRing` 当子控件，
    忙碌时给文字前面塞若干空格腾位置，再把环挪到文字左边（按钮文字是居中画的，
    所以位置得按 `fontMetrics` 现算）。**空格数按空格实际宽度算而不是写死**——
    换字体空格宽度就变（Segoe UI 7px / LXGW 等宽 10px），写死会导致环压在文字上。

    **不覆写 `__init__`**：`PushButton.__init__` 是库自实现的 `singledispatchmethod`，
    `(text, parent)` 那个重载内部会**再调一次** `self.__init__(parent=parent)`，
    子类若加必填位置参数会直接 TypeError。初始化一律走库留的 `_postInit()` 钩子
    ——注意它在 `setText` 之前执行，所以空闲文案只能等 `reserve_busy()` 时再记。
    """

    def _postInit(self) -> None:
        self._ring = IndeterminateProgressRing(self, start=False)
        self._ring.setFixedSize(_RING_SIZE, _RING_SIZE)
        self._ring.setStrokeWidth(3)
        # 点击穿透：环盖在按钮上，不能吃掉点击
        self._ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ring.hide()
        self._idle_text = ""
        self._busy_text = ""

    def _busy_prefix(self) -> str:
        """够放下加载环 + 空隙的空格数（向上取整）。"""
        space = max(1, self.fontMetrics().horizontalAdvance(" "))
        return " " * -(-(_RING_SIZE + _RING_GAP) // space)

    def reserve_busy(self, busy_text: str) -> None:
        """按忙碌态的文字把宽度定死——否则一转圈按钮就变宽，整行跟着跳。"""
        self._idle_text = self.text()
        self._busy_text = busy_text
        width = self.fontMetrics().horizontalAdvance(
            self._busy_prefix() + busy_text
        ) + _BTN_PAD
        self.setFixedWidth(max(self.sizeHint().width(), width))

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.setText(self._busy_prefix() + (self._busy_text or self._idle_text))
            self._ring.show()
            self._ring.start()
        else:
            self._ring.stop()
            self._ring.hide()
            if self._idle_text:
                self.setText(self._idle_text)
        self.setEnabled(not busy)
        self._place_ring()

    def is_busy(self) -> bool:
        return not self._ring.isHidden()

    def _place_ring(self) -> None:
        # 判据用 isHidden 而非 isVisible：按钮尚未 show() 时子控件 isVisible() 恒为 False
        if self._ring.isHidden():
            return
        text_w = self.fontMetrics().horizontalAdvance(self.text())
        left = max(6, (self.width() - text_w) // 2)
        self._ring.move(left, (self.height() - _RING_SIZE) // 2)
        self._ring.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_ring()


class _PillBadge(InfoBadge):
    """把 `InfoBadge` 撑成看得清的胶囊。

    上游 qss 只给了 `padding: 1px 3px`，`v0.1.0` 这种字串会贴着圆角边缘。补留白有两条路，
    这里选覆写 `sizeHint`：**不能用 `setStyleSheet`**——`InfoBadge` 构造时
    `FluentStyleSheet.INFO_BADGE.apply(self)` 已把自己注册进 `styleSheetManager`，
    每次切主题都会重刷 qss 把样式表冲掉（`VideoWidget` 黑背景踩过同一个坑）。

    **不覆写 `__init__`**：`InfoBadge.__init__` 是 `singledispatchmethod`，`(text, parent,
    level)` 那个重载内部会**再调一次** `self.__init__(parent, level)`，子类若加必填位置参数
    直接 TypeError（与 `PushButton` 那个坑同源）。
    """

    _PAD_X = 10  # 左右各补的像素
    _PAD_Y = 4  # 上下各补的像素

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        return QSize(size.width() + self._PAD_X * 2, size.height() + self._PAD_Y * 2)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def version_badge(
    version: str, parent: QWidget | None = None, *, level=InfoLevel.ATTENTION
) -> InfoBadge:
    """版本号胶囊（应用名旁边那颗）。

    `InfoLevel.ATTENTION` 取的是主题色，随亮暗主题自动换色；想要低调的灰色传
    `InfoLevel.INFOAMTION`。文字必须居中——`sizeHint` 补出来的留白不居中就会偏左。
    """
    badge = _PillBadge(f"v{version}", parent, level)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.adjustSize()
    return badge


def status_badge(
    text: str,
    level: InfoLevel,
    parent: QWidget | None = None,
    colors: tuple[str, str] | None = None,
) -> InfoBadge:
    """状态胶囊：同一套外观，颜色由 `InfoLevel`（或显式 `colors`）决定。

    组件库自带三档配色（`InfoBadge._backgroundColor`）：`SUCCESS` 绿 / `WARNING` 橙 /
    `ERROR` 红——但**暗色主题下它给的是浅色背景**（WARNING 是 `#fff4ce`、ERROR 是
    `#ff99a4`），而 qss 把文字钉死成 `color: white`，白字压浅底根本看不清。所以需要
    自定颜色时传 `colors=(亮色, 暗色)`，走 `setCustomBackgroundColor`——它在
    `_backgroundColor()` 里优先级最高，且每次 `paintEvent` 现算，主题切换自动跟上
    （**不能用 `setStyleSheet` 兜**：`InfoBadge` 已注册进 `styleSheetManager`，切主题会重刷）。
    """
    badge = _PillBadge(text, parent, level)
    if colors is not None:
        badge.setCustomBackgroundColor(*colors)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.adjustSize()
    return badge


def page_title(text: str, parent: QWidget | None = None) -> TitleLabel:
    """页面大标题（四页统一字号）。"""
    return TitleLabel(text, parent)


def title_row(label: TitleLabel) -> QHBoxLayout:
    """标题行：缩进走布局边距。

    组件库 Label 注册了 QSS，`QStyleSheetStyle` 会按 QSS 盒模型重算 contentsMargins，
    直接给 Label `setContentsMargins` 不生效（设置页踩过）。
    """
    row = QHBoxLayout()
    row.setContentsMargins(PAGE_MARGIN, PAGE_TOP, PAGE_MARGIN, SECTION_SPACING)
    row.addWidget(label)
    row.addStretch(1)
    return row


class CommandCard(SimpleCardWidget):
    """页面顶部命令卡：装搜索框、过滤、主操作按钮等。

    `add_row()` 追加一行控件；`add_row_widget()` 把一行包成独立控件，
    方便整行 `setVisible`（如多选态才显示的「已选 N 个 / 加入下载」）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(16, 12, 16, 12)
        self.vBoxLayout.setSpacing(8)

    def add_row(self, *, spacing: int = 8) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(spacing)
        self.vBoxLayout.addLayout(row)
        return row

    def add_row_widget(self, *, spacing: int = 8) -> tuple[QWidget, QHBoxLayout]:
        """返回 (整行容器, 该行布局)——容器可整体显隐。"""
        holder = QWidget(self)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        self.vBoxLayout.addWidget(holder)
        return holder, layout

    def add_widget(self, widget: QWidget) -> None:
        """整行占一个控件（进度条、状态文字等）。"""
        widget.setParent(self)
        self.vBoxLayout.addWidget(widget)


class SectionCard(HeaderCardWidget):
    """带标题栏的内容卡：用来包住详情页的预览网格。

    库里默认内容区边距 24 太厚，收紧到 (12, 4, 12, 12) 给网格让出空间。
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self.headerView.setFixedHeight(40)
        self.viewLayout.setContentsMargins(12, 4, 12, 12)
        self.viewLayout.setSpacing(0)

    def add_widget(self, widget: QWidget) -> None:
        widget.setParent(self.view)
        self.viewLayout.addWidget(widget)

    def add_header_widget(self, widget: QWidget) -> None:
        """把控件挂到卡头右侧（如内容分页的 Pivot）。

        `HeaderCardWidget.headerLayout` 里只有 `headerLabel`，先撑开再追加即靠右排。
        卡头高度恢复成库里默认的 48：本类为省空间收到了 40，`PivotItem` 放不下。
        """
        widget.setParent(self.headerView)
        self.headerView.setFixedHeight(48)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(widget)
