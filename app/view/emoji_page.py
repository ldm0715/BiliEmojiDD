"""表情包页：Pivot 两个标签（按 ID 查询 / 全部表情包）。

两级导航：先展示表情包（大类）卡片列表，点击进入包详情查看全部表情并下载。
「全部表情包」列表使用分页，避免一次性加载太多。
"""
from __future__ import annotations

import math

from biliemoji import Emoji
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    InfoBar,
    InfoBarPosition,
    Pivot,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
)

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.components.cache import load_all_packages_cache, save_all_packages_cache
from app.components.package_detail import PackageDetailView
from app.components.page_bar import PageBar
from app.components.task import run_task
from app.components.widgets import PackageGrid

_PAGE_SIZE = 20  # 全部表情包每页数量


class _IdQueryTab(QWidget):
    """按包 ID 查询：输入 ID 直接打开该包的详情。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        search_row = QHBoxLayout()
        self.idEdit = SearchLineEdit(self)
        self.idEdit.setPlaceholderText("输入表情包 ID，如 53")
        self.idEdit.setFixedWidth(260)
        self.queryBtn = PrimaryPushButton("查询", self)
        search_row.addWidget(self.idEdit)
        search_row.addWidget(self.queryBtn)
        search_row.addStretch(1)
        layout.addLayout(search_row)

        self.detail = PackageDetailView(self)
        layout.addWidget(self.detail, 1)

        self.queryBtn.clicked.connect(self._on_query)
        self.idEdit.returnPressed.connect(self._on_query)

    def _on_query(self) -> None:
        text = self.idEdit.text().strip()
        if not text.isdigit():
            InfoBar.warning(
                "无效 ID",
                "请输入数字形式的表情包 ID",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        pid = int(text)
        self.queryBtn.setEnabled(False)
        self.detail.show_loading(text)

        def task():
            return Emoji(cookie=cfg.cookie.value).certain_emoji_typed(pid)

        run_task(
            task,
            on_success=self.detail.set_package,
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.queryBtn.setEnabled(True),
        )


class _AllPackagesTab(QWidget):
    """登录后拉取全部表情包：分页卡片网格 → 点击进入包详情。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all: tuple = ()
        self._filtered: list = []

        self.stacked = QStackedWidget(self)
        self.listPage = QWidget(self)
        self.detailPage = QWidget(self)
        self.stacked.addWidget(self.listPage)
        self.stacked.addWidget(self.detailPage)
        self.stacked.setCurrentWidget(self.listPage)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stacked)

        self._build_list_page()
        self._build_detail_page()

        self.fetchBtn.clicked.connect(self._on_fetch)
        self.refreshBtn.clicked.connect(self._on_refresh)
        self.filterEdit.textChanged.connect(self._repopulate)
        self.backBtn.clicked.connect(
            lambda: self.stacked.setCurrentWidget(self.listPage)
        )

    def _build_list_page(self) -> None:
        layout = QVBoxLayout(self.listPage)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self.fetchBtn = PrimaryPushButton("拉取全部表情包", self.listPage)
        self.refreshBtn = PushButton("强制刷新", self.listPage)
        self.refreshBtn.setEnabled(False)
        self.filterEdit = SearchLineEdit(self.listPage)
        self.filterEdit.setPlaceholderText("输入关键词过滤（包名或 ID）")
        self.filterEdit.setEnabled(False)
        self.countLabel = QLabel("", self.listPage)
        self.countLabel.setStyleSheet("color: gray;")
        top_row.addWidget(self.fetchBtn)
        top_row.addWidget(self.refreshBtn)
        top_row.addWidget(self.filterEdit, 1)
        top_row.addWidget(self.countLabel)
        layout.addLayout(top_row)

        self.grid = PackageGrid(self.listPage)
        self.grid.packageClicked.connect(self._open_detail)
        layout.addWidget(self.grid, 1)

        self.pager = PageBar(self.listPage)
        self.pager.set_page_count(1)
        self.pager.currentPageChanged.connect(self._show_page)
        layout.addWidget(self.pager, 0, Qt.AlignmentFlag.AlignHCenter)

    def _build_detail_page(self) -> None:
        layout = QVBoxLayout(self.detailPage)
        layout.setSpacing(8)

        back_row = QHBoxLayout()
        self.backBtn = PushButton("返回列表", self.detailPage)
        back_row.addWidget(self.backBtn)
        back_row.addStretch(1)
        layout.addLayout(back_row)

        self.detail = PackageDetailView(self.detailPage)
        layout.addWidget(self.detail, 1)

    def _open_detail(self, pkg) -> None:
        # all_packages 只返回包元信息（不含完整 emote），需单独拉完整包详情
        self.stacked.setCurrentWidget(self.detailPage)
        self.detail.show_loading(pkg.text or f"#{pkg.id}")

        def task():
            return Emoji(cookie=cfg.cookie.value).certain_emoji_typed(pkg.id)

        run_task(
            task,
            on_success=self.detail.set_package,
            on_error=lambda e: show_bili_error(e, self.detailPage),
        )

    def _on_fetch(self) -> None:
        # 优先使用本地缓存，避免每次拉取都请求 B 站接口
        cookie = cfg.cookie.value
        cached = load_all_packages_cache(cookie)
        if cached:
            self._set_packages(cached)
            self.refreshBtn.setEnabled(True)
            InfoBar.info(
                "已使用本地缓存",
                f"共 {len(cached)} 个表情包（24 小时内有效，可「强制刷新」重新拉取）",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )
            return
        self._request_all(cookie)

    def _request_all(self, cookie: str) -> None:
        self.fetchBtn.setEnabled(False)
        self.refreshBtn.setEnabled(False)

        def task():
            return Emoji(cookie=cookie).all_packages()

        run_task(
            task,
            on_success=self._on_fetched,
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.fetchBtn.setEnabled(True),
        )

    def _on_fetched(self, packages) -> None:
        save_all_packages_cache(cfg.cookie.value, packages)
        self._set_packages(packages)
        self.refreshBtn.setEnabled(True)

    def _on_refresh(self) -> None:
        # 强制重新拉取，覆盖旧缓存
        self._request_all(cfg.cookie.value)

    def _set_packages(self, packages) -> None:
        self._all = tuple(packages)
        self.filterEdit.setEnabled(True)
        self._repopulate(self.filterEdit.text())

    def _repopulate(self, text: str) -> None:
        keyword = text.strip()
        self._filtered = [
            pkg
            for pkg in self._all
            if not keyword or keyword in pkg.text or keyword in str(pkg.id)
        ]
        self.countLabel.setText(
            f"共 {len(self._all)} 个表情包 · 匹配 {len(self._filtered)} 个"
        )
        total_pages = max(1, math.ceil(len(self._filtered) / _PAGE_SIZE))
        self.pager.set_page_count(total_pages)
        self.pager.set_current(1)
        self._show_page(1)  # 保证页码未变化时也能刷新第一页

    def _show_page(self, page: int) -> None:
        start = (page - 1) * _PAGE_SIZE
        self.grid.set_packages(self._filtered[start : start + _PAGE_SIZE])


class EmojiPage(QWidget):
    """表情包主页面。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pivot = Pivot(self)
        self.stackedWidget = QStackedWidget(self)
        self.idTab = _IdQueryTab(self)
        self.allTab = _AllPackagesTab(self)
        self.stackedWidget.addWidget(self.idTab)
        self.stackedWidget.addWidget(self.allTab)
        self.pivot.addItem(
            routeKey="byId",
            text="按 ID 查询",
            onClick=lambda: self.stackedWidget.setCurrentWidget(self.idTab),
        )
        self.pivot.addItem(
            routeKey="all",
            text="全部表情包",
            onClick=lambda: self.stackedWidget.setCurrentWidget(self.allTab),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self.pivot)
        layout.addWidget(self.stackedWidget, 1)

        self.pivot.setCurrentItem("byId")
        self.stackedWidget.setCurrentWidget(self.idTab)
