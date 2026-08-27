"""收藏集（装扮）页：关键词搜索 → 两列卡片列表 → 详情预览 → 模式选择下载。"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Dress
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SearchLineEdit,
)

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_success, notify_warning
from app.common.proxy import parse_proxy
from app.components.download_queue import download_queue
from app.components.download_runner import start_download
from app.components.dress_helpers import dlc_ids, is_collection
from app.components.task import run_task
from app.components.widgets import DressDetailGrid, DressGrid

_SEARCH_NUM = 30


class DressPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail = None  # (act_id, lottery_id, summary)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(8)

        self.stacked = QStackedWidget(self)
        self.searchPage = QWidget(self)
        self.detailPage = QWidget(self)
        self.stacked.addWidget(self.searchPage)
        self.stacked.addWidget(self.detailPage)
        root.addWidget(self.stacked, 1)

        self._build_search_page()
        self._build_detail_page()
        self.stacked.setCurrentWidget(self.searchPage)

        self.searchBtn.clicked.connect(self._on_search)
        self.kwEdit.returnPressed.connect(self._on_search)
        self.backBtn.clicked.connect(
            lambda: self.stacked.setCurrentWidget(self.searchPage)
        )
        self.detailBtn.clicked.connect(self._on_detail_download)
        self.multiBtn.toggled.connect(self._set_multi)
        self.addBtn.clicked.connect(self._add_to_queue)
        self.grid.summaryClicked.connect(self._open_detail)
        self.grid.selectionChanged.connect(self._update_select_label)

    # ---- 搜索页 ----
    def _build_search_page(self) -> None:
        layout = QVBoxLayout(self.searchPage)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        self.kwEdit = SearchLineEdit(self.searchPage)
        self.kwEdit.setPlaceholderText("输入收藏集关键词，如 2233")
        self.onlyCollCheck = CheckBox("仅看收藏集", self.searchPage)
        self.multiBtn = CheckBox("多选", self.searchPage)
        self.searchBtn = PrimaryPushButton("搜索", self.searchPage)
        top_row.addWidget(self.kwEdit, 1)
        top_row.addWidget(self.onlyCollCheck)
        top_row.addWidget(self.multiBtn)
        top_row.addWidget(self.searchBtn)
        layout.addLayout(top_row)

        select_row = QHBoxLayout()
        self.selectLabel = QLabel("已选 0 个", self.searchPage)
        self.selectLabel.setStyleSheet("color: gray;")
        self.addBtn = PrimaryPushButton("加入下载", self.searchPage)
        self.addBtn.setVisible(False)
        select_row.addWidget(self.selectLabel)
        select_row.addStretch(1)
        select_row.addWidget(self.addBtn)
        layout.addLayout(select_row)

        self.grid = DressGrid(self.searchPage)
        layout.addWidget(self.grid, 1)

        self.hintLabel = QLabel("搜索 B 站装扮 / 收藏集，点击卡片查看详情", self.searchPage)
        self.hintLabel.setStyleSheet("color: gray;")
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hintLabel)

    # ---- 详情页 ----
    def _build_detail_page(self) -> None:
        layout = QVBoxLayout(self.detailPage)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        self.backBtn = PushButton("返回搜索", self.detailPage)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        self.detailName = QLabel("", self.detailPage)
        self.detailName.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detailInfo = QLabel("", self.detailPage)
        self.detailInfo.setStyleSheet("color: gray;")
        title_layout.addWidget(self.detailName)
        title_layout.addWidget(self.detailInfo)
        top_row.addWidget(self.backBtn)
        top_row.addLayout(title_layout, 1)
        layout.addLayout(top_row)

        layout.addWidget(QLabel("内容预览"))

        self.detailGrid = DressDetailGrid(self.detailPage)
        layout.addWidget(self.detailGrid, 1)

        # 视频区：可折叠（默认收起），点标题展开
        self.videoToggle = QToolButton(self.detailPage)
        self.videoToggle.setText("视频内容")
        self.videoToggle.setArrowType(Qt.ArrowType.RightArrow)
        self.videoToggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.videoToggle.setAutoRaise(True)
        self.videoToggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.videoToggle.setStyleSheet(
            "QToolButton { border: none; font-weight: 600; padding: 2px 4px; }"
        )
        self.videoToggle.clicked.connect(self._toggle_video)
        self.videoToggle.hide()
        layout.addWidget(self.videoToggle)

        self.videoList = QListWidget(self.detailPage)
        self.videoList.setMaximumHeight(150)
        self.videoList.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.videoList.hide()
        layout.addWidget(self.videoList)

        download_row = QHBoxLayout()
        download_row.addWidget(QLabel("下载内容:"))
        self.modeCombo = ComboBox(self.detailPage)
        # 注意：qfluentwidgets ComboBox.addItem(text, icon, userData)，第二位置参是 icon
        self.modeCombo.addItem("静态图片", userData="image")
        self.modeCombo.addItem("动态视频", userData="video")
        self.modeCombo.addItem("图片 + 视频", userData="both")
        self.modeCombo.setCurrentIndex(2)
        self.detailBtn = PrimaryPushButton("下载到本地", self.detailPage)
        self.detailBtn.setEnabled(False)
        download_row.addWidget(self.modeCombo)
        download_row.addStretch(1)
        download_row.addWidget(self.detailBtn)
        layout.addLayout(download_row)

        self.detailBar = ProgressBar(self.detailPage)
        self.detailBar.setFixedHeight(8)
        self.detailBar.hide()
        layout.addWidget(self.detailBar)

    # ---- 搜索 ----
    def _on_search(self) -> None:
        keyword = self.kwEdit.text().strip()
        if not keyword:
            notify_warning(
                "请输入关键词",
                "收藏集搜索需要关键词",
                parent=self.searchPage,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.searchBtn.setEnabled(False)
        self.hintLabel.setText("搜索中…")

        def task():
            return Dress(
                cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
            ).search_dress_typed(_SEARCH_NUM, keyword=keyword)

        run_task(
            task,
            on_success=self._show_results,
            on_error=lambda e: show_bili_error(e, self.searchPage),
            on_finished=lambda ok: self.searchBtn.setEnabled(True),
        )

    def _show_results(self, summaries) -> None:
        if self.onlyCollCheck.isChecked():
            summaries = [s for s in summaries if is_collection(s)]
        self.grid.set_summaries(summaries)
        self.hintLabel.setText(
            "没有符合条件的收藏集" if not summaries else f"共 {len(summaries)} 个结果"
        )

    # ---- 详情 ----
    def _open_detail(self, summary) -> None:
        if not is_collection(summary):
            notify_warning(
                "无收藏集详情",
                "该装扮没有可下载的收藏集",
                parent=self.searchPage,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        act_id, lottery_id = dlc_ids(summary)
        self._detail = (act_id, lottery_id, summary)
        self.detailName.setText(summary.name or "收藏集")
        self.detailInfo.setText("")
        self.detailGrid.set_items([])
        self.videoToggle.hide()
        self.videoToggle.setArrowType(Qt.ArrowType.RightArrow)
        self.videoList.clear()
        self.videoList.hide()
        self.detailBtn.setEnabled(False)
        self.stacked.setCurrentWidget(self.detailPage)

        def task():
            return Dress(
                cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
            ).certain_lottery_typed(act_id, lottery_id)

        run_task(
            task,
            on_success=self._show_detail,
            on_error=lambda e: show_bili_error(e, self.detailPage),
        )

    def _show_detail(self, collection) -> None:
        items = []
        videos = []  # [(card_name, url), ...]
        for item in collection.item_list:
            if item.card_img_download:
                items.append((item.card_name or "", item.card_img_download))
            for url in item.video_list:
                videos.append((item.card_name or "", url))
        # 动态尺寸网格：卡片随视口/数量撑满区域
        self.detailGrid.set_items(items)
        self.videoList.clear()
        for name, url in videos:
            row = QListWidgetItem(f"▶ {name}")
            row.setData(Qt.ItemDataRole.UserRole, url)
            self.videoList.addItem(row)
        if videos:
            self.videoToggle.setText(f"视频内容（{len(videos)} 个）")
            self.videoToggle.setArrowType(Qt.ArrowType.RightArrow)
            self.videoToggle.show()
        else:
            self.videoToggle.hide()
        self.videoList.hide()
        self.detailInfo.setText(
            f"名称: {collection.name or ''} · 图片 {len(items)} 个 · 视频 {len(videos)} 个"
        )
        self.detailBtn.setEnabled(True)

    def _toggle_video(self) -> None:
        show = not self.videoList.isVisible()
        self.videoList.setVisible(show)
        self.videoToggle.setArrowType(
            Qt.ArrowType.DownArrow if show else Qt.ArrowType.RightArrow
        )

    # ---- 多选加入下载队列 ----
    def _set_multi(self, on: bool) -> None:
        self.grid.set_selectable(on)
        self.addBtn.setVisible(on)
        self._update_select_label()

    def _update_select_label(self) -> None:
        n = self.grid.checked_count()
        self.selectLabel.setText(f"已选 {n} 个")
        self.addBtn.setEnabled(n > 0)

    def _add_to_queue(self) -> None:
        summaries = self.grid.checked_summaries()
        if not summaries:
            notify_warning(
                "未选择",
                "请先勾选要加入下载的收藏集",
                parent=self.searchPage,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        added = download_queue.add_many(summaries)
        self.multiBtn.setChecked(False)  # 触发 toggled(False) -> _set_multi(False)
        notify_success(
            "已加入下载队列",
            f"已加入 {added} 个收藏集，可前往「下载」页查看",
            parent=self.searchPage,
            position=InfoBarPosition.TOP_RIGHT,
        )

    # ---- 下载（详情页单包） ----
    def _on_detail_download(self) -> None:
        if self._detail is None:
            return
        act_id, lottery_id, _ = self._detail
        mode = self.modeCombo.currentData()
        self.detailBtn.setEnabled(False)

        def task(on_progress=None):
            return Dress(
                cookie=cfg.cookie.value, proxies=parse_proxy(cfg.proxy.value)
            ).download_collection(
                act_id,
                lottery_id,
                Path(cfg.download_dir.value),
                mode=mode,
                max_workers=cfg.max_workers.value,
                on_progress=on_progress,
            )

        started = start_download(
            task,
            self.detailBar,
            on_finished=lambda: self.detailBtn.setEnabled(True),
            parent=self.detailPage,
        )
        if not started:
            # 目录不可用：start_download 未启动任务、不会触发 finished，手动恢复
            self.detailBtn.setEnabled(True)
