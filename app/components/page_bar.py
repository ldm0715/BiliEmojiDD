"""带页码的分页条组件，紧凑水平布局，整体居中。

qfluentwidgets 开源版（1.11.x / fork 1.5.1）不含数字分页组件（数字分页属 Pro 版），
因此用 qfluentwidgets 官方组件按 Fluent 规范排版：当前页实心高亮，其余页扁平按钮，
两端用 ToolButton 箭头翻页。整体以一个紧凑整体居中。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from qfluentwidgets import (
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)

_BTN_H = 32        # 所有按钮统一高度
_BTN_MIN_W = 40    # 页码按钮最小宽度（两位数会自动变宽，避免裁剪）
_NAV_W = 40        # 翻页箭头按钮宽度
_SPACING = 6


class PageBar(QWidget):
    """显示页码的分页条。页码过多时用省略号折叠。"""

    currentPageChanged = Signal(int)

    _MAX_PAGES = 7  # 折叠前的最大页码按钮数

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page_count = 1
        self._current = 1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(_SPACING)
        self._rebuild()

    def sizeHint(self) -> object:
        # 关键：让父布局按内容宽度排列，避免按默认 (100, 30) 挤压导致控件重叠
        return self._layout.sizeHint()

    def set_page_count(self, count: int) -> None:
        """设置总页数，并校正当前页（不触发 currentPageChanged）。"""
        self._page_count = max(1, count)
        self._current = min(self._current, self._page_count)
        self._rebuild()

    def set_current(self, page: int) -> None:
        """切换到指定页（触发 currentPageChanged）。"""
        page = min(max(1, page), self._page_count)
        if page == self._current:
            return
        self._current = page
        self._rebuild()
        self.currentPageChanged.emit(page)

    def _jump(self, page: int) -> None:
        if page < 1 or page > self._page_count or page == self._current:
            return
        self._current = page
        self._rebuild()
        self.currentPageChanged.emit(page)

    def _page_list(self) -> list:
        """返回要展示的页码，None 表示省略号。"""
        n, c = self._page_count, self._current
        if n <= self._MAX_PAGES:
            return list(range(1, n + 1))
        pages = [1]
        if c >= 5:
            pages.append(None)
        pages.extend(range(max(2, c - 1), min(n - 1, c + 1) + 1))
        if c <= n - 4:
            pages.append(None)
        pages.append(n)
        return pages

    def _make_nav(self, icon, tip: str, enabled: bool, target: int) -> ToolButton:
        button = ToolButton(icon, self)
        button.setFixedSize(_NAV_W, _BTN_H)
        button.setIconSize(QSize(18, 18))
        button.setEnabled(enabled)
        button.setToolTip(tip)
        button.clicked.connect(lambda *args: self._jump(target))
        return button

    def _rebuild(self) -> None:
        # 旧控件先脱离父级立即停止绘制，再删除，避免“幽灵按钮”残影
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._layout.addWidget(
            self._make_nav(
                FluentIcon.LEFT_ARROW, "上一页", self._current > 1, self._current - 1
            )
        )

        for page in self._page_list():
            if page is None:
                ellipsis = QLabel("…", self)
                ellipsis.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ellipsis.setFixedSize(_BTN_MIN_W, _BTN_H)
                self._layout.addWidget(ellipsis)
            elif page == self._current:
                # 当前页：实心高亮，不响应点击
                button = PrimaryPushButton(str(page), self)
                button.setMinimumSize(_BTN_MIN_W, _BTN_H)
                button.setFixedHeight(_BTN_H)
                self._layout.addWidget(button)
            else:
                button = PushButton(str(page), self)
                button.setMinimumSize(_BTN_MIN_W, _BTN_H)
                button.setFixedHeight(_BTN_H)
                button.clicked.connect(lambda *args, p=page: self._jump(p))
                self._layout.addWidget(button)

        self._layout.addWidget(
            self._make_nav(
                FluentIcon.RIGHT_ARROW, "下一页", self._current < self._page_count,
                self._current + 1,
            )
        )

        self.adjustSize()
