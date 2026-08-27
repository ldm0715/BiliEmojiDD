"""收藏集（装扮）页：关键词搜索 → 卡片列表 → 详情预览 → 模式选择下载。"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Dress
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
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
    SmoothScrollArea,
)

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_warning
from app.common.proxy import parse_proxy
from app.common.signal_bus import signal_bus
from app.components.download_runner import start_download
from app.components.task import run_task
from app.components.widgets import DressCard, EmojiGrid

_SEARCH_NUM = 30


class DressPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[DressCard] = []
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
        signal_bus.thumbLoaded.connect(self._on_thumb)

    # ---- 搜索页 ----
    def _build_search_page(self) -> None:
        layout = QVBoxLayout(self.searchPage)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        self.kwEdit = SearchLineEdit(self.searchPage)
        self.kwEdit.setPlaceholderText("输入收藏集关键词，如 2233")
        self.onlyCollCheck = CheckBox("仅看收藏集", self.searchPage)
        self.searchBtn = PrimaryPushButton("搜索", self.searchPage)
        top_row.addWidget(self.kwEdit, 1)
        top_row.addWidget(self.onlyCollCheck)
        top_row.addWidget(self.searchBtn)
        layout.addLayout(top_row)

        self.scroll = SmoothScrollArea(self.searchPage)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget(self.scroll)
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vbox.setSpacing(8)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

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

        self.detailGrid = EmojiGrid(self.detailPage)
        layout.addWidget(self.detailGrid, 1)

        download_row = QHBoxLayout()
        download_row.addWidget(QLabel("下载内容:"))
        self.modeCombo = ComboBox(self.detailPage)
        self.modeCombo.addItem("静态图片", "image")
        self.modeCombo.addItem("动态视频", "video")
        self.modeCombo.addItem("图片 + 视频", "both")
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
        self._clear_cards()
        if self.onlyCollCheck.isChecked():
            summaries = [s for s in summaries if s.is_collection]
        if not summaries:
            self.hintLabel.setText("没有符合条件的收藏集")
            return
        for s in summaries:
            card = DressCard(s, self.container)
            card.clicked.connect(lambda c=card: self._on_card_clicked(c))
            self.vbox.addWidget(card)
            self._cards.append(card)
        self.hintLabel.setText(f"共 {len(summaries)} 个结果")

    def _clear_cards(self) -> None:
        while self.vbox.count():
            item = self.vbox.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()

    # ---- 详情 ----
    def _on_card_clicked(self, card: DressCard) -> None:
        summary = card.summary
        if not summary.is_collection:
            notify_warning(
                "无收藏集详情",
                "该装扮没有可下载的收藏集",
                parent=self.searchPage,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self._detail = (summary.dlc_act_id, summary.dlc_lottery_id, summary)
        self.detailName.setText(summary.name or "收藏集")
        price = summary.sale_bp_forever
        price_text = f"{price:.2f} 元" if price is not None else "价格未知"
        self.detailInfo.setText(f"ID: {summary.id or '-'} · {price_text}")
        self.detailGrid.set_emotes([])
        self.detailBtn.setEnabled(False)
        self.stacked.setCurrentWidget(self.detailPage)

        act_id, lottery_id, _ = self._detail

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
        video_count = 0
        for item in collection.item_list:
            if item.card_img_download:
                items.append((item.card_name or "", item.card_img_download))
            video_count += len(item.video_list)
        self.detailGrid.set_emotes(items)
        self.detailInfo.setText(
            f"名称: {collection.name or ''} · 图片 {len(items)} 个 · 视频 {video_count} 个"
        )
        self.detailBtn.setEnabled(True)

    # ---- 下载 ----
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

    # ---- 封面缩略图回填 ----
    def _on_thumb(self, url: str, pixmap) -> None:
        for card in self._cards:
            if card.cover_url == url:
                card.set_cover(pixmap)
