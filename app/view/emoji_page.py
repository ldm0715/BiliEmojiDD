"""表情包页：Pivot 两个标签（按 ID 查询 / 全部表情包）。

两级导航：先展示表情包（大类）卡片列表，点击进入包详情查看全部表情并下载。
「全部表情包」列表使用分页，避免一次性加载太多。
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    FluentIcon,
    InfoBarPosition,
    Pivot,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    TransparentPushButton,
)

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.common.net import make_emoji
from app.common.notify import notify_info, notify_success, notify_warning
from app.common.theme import SECONDARY_TEXT
from app.components import api_cache
from app.components.cache import load_all_packages_cache, save_all_packages_cache
from app.components.download_queue import download_queue
from app.components.package_detail import PackageDetailView
from app.components.page_bar import PageBar
from app.components.page_scaffold import (
    PAGE_BOTTOM,
    PAGE_MARGIN,
    SECTION_SPACING,
    CommandCard,
    page_title,
    title_row,
)
from app.components.search_history import SearchHistoryPanel
from app.components.task import run_task
from app.components.widgets import PackageGrid

_PAGE_SIZE = 20  # 全部表情包每页数量


class _IdQueryTab(QWidget):
    """按包 ID 查询：输入 ID 直接打开该包的详情。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        layout.setSpacing(SECTION_SPACING)

        self.searchCard = CommandCard(self)
        search_row = self.searchCard.add_row()
        self.idEdit = SearchLineEdit(self.searchCard)
        self.idEdit.setPlaceholderText("输入表情包 ID，如 53")
        self.idEdit.setFixedWidth(260)
        self.queryBtn = PrimaryPushButton("查询", self.searchCard)
        search_row.addWidget(self.idEdit)
        search_row.addWidget(self.queryBtn)
        search_row.addStretch(1)

        # 查询记录：浮层面板，点搜索框才下拉，不占命令卡版面
        self.historyPanel = SearchHistoryPanel(self.idEdit, "emoji_id")
        layout.addWidget(self.searchCard)

        self.detail = PackageDetailView(self)
        layout.addWidget(self.detail, 1)

        self.queryBtn.clicked.connect(self._on_query)
        self.idEdit.returnPressed.connect(self._on_query)
        # 放大镜按钮走 searchSignal（SearchLineEdit 内部只把它连到自己的 search()），
        # 不接的话点图标毫无反应
        self.idEdit.searchSignal.connect(self._on_query)
        self.historyPanel.activated.connect(self._on_history_activated)

    def _on_history_activated(self, text: str) -> None:
        """点历史胶囊 = 回填 ID 并立即查（命中缓存时几乎瞬时）。"""
        self.idEdit.setText(text)
        self._on_query()

    def query(self, text: str) -> None:
        """外部入口（主页「最近搜索」）：回填 ID 并立即查询。"""
        self._on_history_activated(text)

    def _on_query(self) -> None:
        text = self.idEdit.text().strip()
        if not text.isdigit():
            notify_warning(
                "无效 ID",
                "请输入数字形式的表情包 ID",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        pid = int(text)
        self.queryBtn.setEnabled(False)
        self.detail.show_loading(text)
        self.historyPanel.record(text)

        def task():
            return api_cache.emoji_package(pid)

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
        self._multi = False

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
        # 过滤只在回车 / 点放大镜时触发——每敲一个字就重排整页太吵，
        # 与收藏集搜索的交互保持一致；点 × 清空则立刻恢复全部
        self.filterEdit.returnPressed.connect(self._on_filter)
        self.filterEdit.searchSignal.connect(self._on_filter)
        self.filterEdit.clearSignal.connect(self._on_filter_cleared)
        self.historyPanel.activated.connect(self._on_history_activated)
        self.backBtn.clicked.connect(
            lambda: self.stacked.setCurrentWidget(self.listPage)
        )
        self.multiBtn.toggled.connect(self._set_multi)
        self.addBtn.clicked.connect(self._add_to_queue)
        self.grid.selectionChanged.connect(self._update_select_label)

    def _on_filter(self) -> None:
        keyword = self.filterEdit.text().strip()
        if keyword:
            self.historyPanel.record(keyword)
        self._repopulate(keyword)

    def _on_filter_cleared(self) -> None:
        self.filterEdit.clear()
        self._repopulate("")

    def _on_history_activated(self, keyword: str) -> None:
        """点历史胶囊 = 回填关键词并立即过滤。"""
        self.filterEdit.setText(keyword)
        self._on_filter()

    def filter_by(self, keyword: str) -> None:
        """外部入口（主页「最近搜索」）：回填关键词。

        只有已经拉过全量列表时才真的过滤——没拉过就悄悄发起一次需要 Cookie 的
        网络请求太突兀，先把词填好，用户点「拉取全部表情包」后自然生效。
        """
        self.filterEdit.setText(keyword)
        if self._all:
            self._on_filter()

    def _build_list_page(self) -> None:
        layout = QVBoxLayout(self.listPage)
        layout.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        layout.setSpacing(SECTION_SPACING)

        self.commandCard = CommandCard(self.listPage)
        top_row = self.commandCard.add_row()
        self.fetchBtn = PrimaryPushButton("拉取全部表情包", self.commandCard)
        self.refreshBtn = PushButton("强制刷新", self.commandCard)
        self.refreshBtn.setEnabled(False)
        self.filterEdit = SearchLineEdit(self.commandCard)
        self.filterEdit.setPlaceholderText("输入关键词过滤（包名或 ID）")
        self.filterEdit.setEnabled(False)
        self.countLabel = CaptionLabel("", self.commandCard)
        self.countLabel.setTextColor(*SECONDARY_TEXT)
        self.multiBtn = CheckBox("多选", self.commandCard)
        top_row.addWidget(self.fetchBtn)
        top_row.addWidget(self.refreshBtn)
        top_row.addWidget(self.multiBtn)
        top_row.addWidget(self.filterEdit, 1)
        top_row.addWidget(self.countLabel)

        # 过滤记录：浮层面板，点过滤框才下拉，不占命令卡版面
        self.historyPanel = SearchHistoryPanel(self.filterEdit, "emoji_filter")

        # 多选行：只在多选态显示，隐藏时命令卡自动收缩一行
        self.selectRow, select_row = self.commandCard.add_row_widget()
        self.selectLabel = CaptionLabel("已选 0 个", self.selectRow)
        self.selectLabel.setTextColor(*SECONDARY_TEXT)
        self.addBtn = PrimaryPushButton("加入下载", self.selectRow)
        self.addBtn.setVisible(False)
        select_row.addWidget(self.selectLabel)
        select_row.addStretch(1)
        select_row.addWidget(self.addBtn)
        self.selectRow.setVisible(False)
        layout.addWidget(self.commandCard)

        self.grid = PackageGrid(self.listPage)
        self.grid.packageClicked.connect(self._open_detail)
        layout.addWidget(self.grid, 1)

        self.pager = PageBar(self.listPage)
        self.pager.set_page_count(1)
        self.pager.currentPageChanged.connect(self._show_page)
        layout.addWidget(self.pager, 0, Qt.AlignmentFlag.AlignHCenter)

    def _build_detail_page(self) -> None:
        layout = QVBoxLayout(self.detailPage)
        layout.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        layout.setSpacing(SECTION_SPACING)

        self.detail = PackageDetailView(self.detailPage)
        # 「返回列表」放进详情头部卡左侧，省掉单独一行
        self.backBtn = TransparentPushButton(
            FluentIcon.LEFT_ARROW, "返回列表", self.detailPage
        )
        self.detail.add_leading_widget(self.backBtn)
        layout.addWidget(self.detail, 1)

    def _open_detail(self, pkg) -> None:
        # all_packages 只返回包元信息（不含完整 emote），需单独拉完整包详情
        self.stacked.setCurrentWidget(self.detailPage)
        self.detail.show_loading(pkg.text or f"#{pkg.id}")

        def task():
            return api_cache.emoji_package(pkg.id)

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
            notify_info(
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
            return make_emoji(cookie=cookie).all_packages()

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

    # ---- 多选加入下载队列 ----

    def _set_multi(self, on: bool) -> None:
        self._multi = bool(on)
        self.grid.set_selectable(self._multi)
        self.addBtn.setVisible(self._multi)
        self.selectRow.setVisible(self._multi)  # 整行随多选态显隐
        self._update_select_label()

    def _update_select_label(self) -> None:
        n = self.grid.checked_count()
        self.selectLabel.setText(f"已选 {n} 个")
        self.addBtn.setEnabled(n > 0)

    def _add_to_queue(self) -> None:
        pkgs = self.grid.checked_packages()
        if not pkgs:
            return
        added = download_queue.add_many(pkgs)
        self.multiBtn.setChecked(False)  # 触发 toggled(False) -> _set_multi(False)
        notify_success(
            "已加入下载队列",
            f"已加入 {added} 个表情包，可前往「下载」页查看",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )


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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.titleLabel = page_title("表情包", self)
        layout.addLayout(title_row(self.titleLabel))

        pivot_row = QHBoxLayout()
        pivot_row.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, SECTION_SPACING)
        pivot_row.addWidget(self.pivot)
        pivot_row.addStretch(1)
        layout.addLayout(pivot_row)

        layout.addWidget(self.stackedWidget, 1)

        self.pivot.setCurrentItem("byId")
        self.stackedWidget.setCurrentWidget(self.idTab)

    # ---- 外部入口（主页「最近搜索」跳转带参） ----

    def query_package_id(self, text: str) -> None:
        """切到「按 ID 查询」标签并立即查询该 ID。"""
        # setCurrentItem 不触发 onClick、onClick 也不移动指示条，两句都要写
        self.pivot.setCurrentItem("byId")
        self.stackedWidget.setCurrentWidget(self.idTab)
        self.idTab.query(text)

    def filter_packages(self, keyword: str) -> None:
        """切到「全部表情包」标签并回填过滤关键词。"""
        self.pivot.setCurrentItem("all")
        self.stackedWidget.setCurrentWidget(self.allTab)
        self.allTab.filter_by(keyword)
