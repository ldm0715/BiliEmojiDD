"""页面版式底座：统一页边距、页面大标题与卡片容器。

四个页面共用同一套 Fluent 版式：大标题 → 命令卡（工具栏）→ 内容（网格 / 带标题的内容卡）。
卡片一律用组件库的 `SimpleCardWidget` / `HeaderCardWidget`——它们构造时
`FluentStyleSheet.CARD_WIDGET.apply(self)` 且连了 `qconfig.themeChanged`，主题切换自动重绘。
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget, SimpleCardWidget, TitleLabel

PAGE_MARGIN = 36  # 页面左右边距（四页统一，含设置页）
PAGE_TOP = 20  # 大标题上方留白
PAGE_BOTTOM = 24  # 页面底部留白
SECTION_SPACING = 12  # 卡片 / 内容块之间的间距


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
