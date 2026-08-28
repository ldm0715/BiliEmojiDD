"""收藏集（装扮）页：关键词搜索 → 两列卡片列表 → 详情预览 → 模式选择下载。"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Dress
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    InfoBadge,
    InfoBarPosition,
    ListWidget,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SearchLineEdit,
    SimpleCardWidget,
    SubtitleLabel,
    TransparentPushButton,
)

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_info, notify_success, notify_warning
from app.common.proxy import parse_proxy
from app.common.theme import SECONDARY_TEXT
from app.components.content_meta import collection_meta, content_meta
from app.components.download_queue import download_queue
from app.components.download_runner import (
    collection_download_dir,
    download_collection_batch,
    downloaded_exists,
    start_download,
)
from app.components.dress_helpers import dlc_ids, is_collection
from app.components.image_viewer import show_image_viewer
from app.components.page_scaffold import (
    PAGE_BOTTOM,
    PAGE_MARGIN,
    SECTION_SPACING,
    CommandCard,
    SectionCard,
    page_title,
    title_row,
)
from app.components.task import run_task
from app.components.widgets import DressDetailGrid, DressGrid

_SEARCH_NUM = 30


class DressPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail = None  # (act_id, lottery_id, summary)
        self._detail_summary = None  # 详情当前收藏集（入队按钮状态依据，避免魔法下标）
        self._last_summaries = None  # 最近一次搜索结果原始列表（勾选框实时过滤用）
        self._detail_items: list[tuple[str, str]] = []  # 详情图片 (name, url)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titleLabel = page_title("收藏集", self)
        root.addLayout(title_row(self.titleLabel))

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
        self.backBtn.clicked.connect(self._go_back)
        self.detailBtn.clicked.connect(self._on_detail_download)
        self.queueBtn.clicked.connect(self._on_detail_add_to_queue)
        self.multiBtn.toggled.connect(self._set_multi)
        self.addBtn.clicked.connect(self._add_to_queue)
        self.onlyCollCheck.toggled.connect(self._apply_filter)
        self.grid.summaryClicked.connect(self._open_detail)
        self.grid.selectionChanged.connect(self._update_select_label)
        self.detailGrid.imageClicked.connect(self._open_image_viewer)
        # 队列变化时同步详情页按钮状态（加入/删除/清空后即时刷新）
        download_queue.changed.connect(self._sync_queue_btn)

    # ---- 搜索页 ----
    def _build_search_page(self) -> None:
        layout = QVBoxLayout(self.searchPage)
        layout.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        layout.setSpacing(SECTION_SPACING)

        self.searchCard = CommandCard(self.searchPage)
        top_row = self.searchCard.add_row()
        self.kwEdit = SearchLineEdit(self.searchCard)
        self.kwEdit.setPlaceholderText("输入收藏集关键词，如 2233")
        self.onlyCollCheck = CheckBox("仅看收藏集", self.searchCard)
        self.onlyCollCheck.setChecked(True)  # 默认只看收藏集（装扮无法下载）
        self.multiBtn = CheckBox("多选", self.searchCard)
        self.searchBtn = PrimaryPushButton("搜索", self.searchCard)
        top_row.addWidget(self.kwEdit, 1)
        top_row.addWidget(self.onlyCollCheck)
        top_row.addWidget(self.multiBtn)
        top_row.addWidget(self.searchBtn)

        # 多选行：只在多选态显示，隐藏时命令卡自动收缩一行
        self.selectRow, select_row = self.searchCard.add_row_widget()
        self.selectLabel = CaptionLabel("已选 0 个", self.selectRow)
        self.selectLabel.setTextColor(*SECONDARY_TEXT)
        self.addBtn = PrimaryPushButton("加入下载", self.selectRow)
        self.addBtn.setVisible(False)
        select_row.addWidget(self.selectLabel)
        select_row.addStretch(1)
        select_row.addWidget(self.addBtn)
        self.selectRow.setVisible(False)
        layout.addWidget(self.searchCard)

        self.grid = DressGrid(self.searchPage)
        layout.addWidget(self.grid, 1)

        self.hintLabel = BodyLabel("搜索 B 站装扮 / 收藏集，点击卡片查看详情", self.searchPage)
        self.hintLabel.setTextColor(*SECONDARY_TEXT)
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hintLabel)

    # ---- 详情页 ----
    def _build_detail_page(self) -> None:
        layout = QVBoxLayout(self.detailPage)
        layout.setContentsMargins(PAGE_MARGIN, 0, PAGE_MARGIN, PAGE_BOTTOM)
        layout.setSpacing(SECTION_SPACING)

        # 头部卡：返回 + 名称 / 信息 + 徽标 + 下载模式 + 按钮 + 进度条
        self.headerCard = CommandCard(self.detailPage)
        title_line = self.headerCard.add_row()
        self.backBtn = TransparentPushButton(
            FluentIcon.LEFT_ARROW, "返回搜索", self.headerCard
        )
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        self.detailName = SubtitleLabel("", self.headerCard)
        self.detailInfo = CaptionLabel("", self.headerCard)
        self.detailInfo.setTextColor(*SECONDARY_TEXT)
        # 换行：QLabel 不换行时最小宽度就是整串文字宽度，长收藏集名会顶得整页缩不下去
        self.detailName.setWordWrap(True)
        self.detailInfo.setWordWrap(True)
        title_box.addWidget(self.detailName)
        title_box.addWidget(self.detailInfo)
        self.downloadedLabel = InfoBadge.success("已下载", self.headerCard)
        self.downloadedLabel.hide()
        self.queueBtn = PushButton("加入下载", self.headerCard)
        self.queueBtn.setEnabled(False)
        self.detailBtn = PrimaryPushButton("下载到本地", self.headerCard)
        self.detailBtn.setEnabled(False)
        title_line.addWidget(self.backBtn, 0, Qt.AlignmentFlag.AlignVCenter)
        title_line.addLayout(title_box, 1)
        for w in (self.downloadedLabel, self.queueBtn, self.detailBtn):
            title_line.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

        mode_row = self.headerCard.add_row()
        self.modeCombo = ComboBox(self.headerCard)
        # 注意：qfluentwidgets ComboBox.addItem(text, icon, userData)，第二位置参是 icon
        self.modeCombo.addItem("静态图片", userData="image")
        self.modeCombo.addItem("动态视频", userData="video")
        self.modeCombo.addItem("图片 + 视频", userData="both")
        self.modeCombo.setCurrentIndex(2)
        self.modeCombo.setMinimumWidth(140)
        mode_row.addStretch(1)
        mode_row.addWidget(BodyLabel("下载内容:", self.headerCard))
        mode_row.addWidget(self.modeCombo)

        self.detailBar = ProgressBar(self.headerCard)
        self.detailBar.setFixedHeight(8)
        self.detailBar.hide()
        self.headerCard.add_widget(self.detailBar)
        layout.addWidget(self.headerCard)

        # 预览卡：图片网格
        self.previewCard = SectionCard("内容预览", self.detailPage)
        self.detailGrid = DressDetailGrid(self.previewCard)
        self.previewCard.add_widget(self.detailGrid)
        layout.addWidget(self.previewCard, 1)

        # 视频卡：折叠标题（默认收起）+ 列表，无视频时整卡隐藏
        self.videoCard = SimpleCardWidget(self.detailPage)
        video_box = QVBoxLayout(self.videoCard)
        video_box.setContentsMargins(12, 8, 12, 12)
        video_box.setSpacing(8)
        self.videoToggle = TransparentPushButton(
            FluentIcon.CHEVRON_RIGHT, "视频内容", self.videoCard
        )
        self.videoToggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.videoToggle.clicked.connect(self._toggle_video)
        self.videoToggle.hide()
        video_box.addWidget(self.videoToggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.videoList = ListWidget(self.videoCard)
        self.videoList.setMaximumHeight(150)
        self.videoList.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.videoList.hide()
        video_box.addWidget(self.videoList)
        self.videoCard.hide()
        layout.addWidget(self.videoCard)

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
        self._last_summaries = list(summaries)
        if self.onlyCollCheck.isChecked():
            summaries = [s for s in summaries if is_collection(s)]
        self.grid.set_summaries(summaries)
        self.hintLabel.setText(
            "没有符合条件的收藏集" if not summaries else f"共 {len(summaries)} 个结果"
        )

    def _apply_filter(self) -> None:
        """「仅看收藏集」勾选框实时过滤当前结果，无需重新搜索。"""
        if self._last_summaries is None:
            return
        self._show_results(self._last_summaries)

    def _go_back(self) -> None:
        self._detail_summary = None
        self._sync_queue_btn()
        self.stacked.setCurrentWidget(self.searchPage)

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
        self._detail_summary = summary
        # 重置入队按钮（不继承上一个详情页状态），拉取成功后由 _show_detail 重新同步
        self.queueBtn.setText("加入下载")
        self.queueBtn.setEnabled(False)
        self.downloadedLabel.hide()
        self.detailName.setText(summary.name or "收藏集")
        self.detailInfo.setText("")
        self._detail_items = []
        self.detailGrid.set_items([])
        self.videoToggle.hide()
        self.videoToggle.setIcon(FluentIcon.CHEVRON_RIGHT)
        self.videoList.clear()
        self.videoList.hide()
        self.videoCard.hide()  # 视频卡随 videoToggle 一起显隐
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
        self._detail_items = items
        self.detailGrid.set_items(items)
        self.videoList.clear()
        for name, url in videos:
            row = QListWidgetItem(f"▶ {name}")
            row.setData(Qt.ItemDataRole.UserRole, url)
            self.videoList.addItem(row)
        if videos:
            self.videoToggle.setText(f"视频内容（{len(videos)} 个）")
            self.videoToggle.setIcon(FluentIcon.CHEVRON_RIGHT)
            self.videoToggle.show()
        else:
            self.videoToggle.hide()
        self.videoCard.setVisible(bool(videos))  # 无视频时整卡隐藏
        self.videoList.hide()
        self.detailInfo.setText(
            f"名称: {collection.name or ''} · 图片 {len(items)} 个 · 视频 {len(videos)} 个"
        )
        # 队列页要显示内容数量，这里顺手喂缓存，省掉它再拉一次收藏集详情
        # （数量走 collection_meta：视频按「有视频的项数」算，与实际下载文件数一致）
        if self._detail_summary is not None:
            content_meta.remember(self._detail_summary, collection_meta(collection))
        self.detailBtn.setEnabled(True)
        self._sync_queue_btn()
        self._refresh_downloaded(collection)

    def _refresh_downloaded(self, collection=None) -> None:
        """已下载判定：新下载按 summary 名建目录（与卡片徽标一致），
        旧版本按 certain_lottery_typed 取回的收藏集名建目录，两者都认。"""
        folders = []
        if self._detail_summary is not None:
            folders.append(collection_download_dir(self._detail_summary))
        if collection is not None:
            folders.append(collection_download_dir(collection))
        self.downloadedLabel.setVisible(any(downloaded_exists(f) for f in folders))

    def _toggle_video(self) -> None:
        show = not self.videoList.isVisible()
        self.videoList.setVisible(show)
        self.videoToggle.setIcon(
            FluentIcon.CHEVRON_DOWN_MED if show else FluentIcon.CHEVRON_RIGHT
        )

    # ---- 图片查看器 ----
    def _open_image_viewer(self, index: int) -> None:
        if index < 0 or not self._detail_items:
            return
        show_image_viewer(self._detail_items, index, self.window())

    # ---- 多选加入下载队列 ----
    def _set_multi(self, on: bool) -> None:
        self.grid.set_selectable(on)
        self.addBtn.setVisible(on)
        self.selectRow.setVisible(on)  # 整行随多选态显隐
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
    def _sync_queue_btn(self) -> None:
        """入队按钮状态单一同步源：无详情或已在队列 → 「已加入」禁用，否则可点。"""
        s = self._detail_summary
        if s is None or download_queue.contains(s):
            self.queueBtn.setText("已加入")
            self.queueBtn.setEnabled(False)
        else:
            self.queueBtn.setText("加入下载")
            self.queueBtn.setEnabled(True)

    def _on_detail_add_to_queue(self) -> None:
        if self._detail_summary is None:
            return
        summary = self._detail_summary
        name = summary.name or "收藏集"
        if download_queue.add(summary):
            # add() 会发 changed → _sync_queue_btn 把按钮置「已加入」禁用
            notify_success(
                "已加入下载队列",
                f"「{name}」已加入，可前往「下载」页查看",
                parent=self.detailPage,
                position=InfoBarPosition.TOP_RIGHT,
            )
        else:
            notify_info(
                "已在下载队列",
                f"「{name}」已在队列中",
                parent=self.detailPage,
                position=InfoBarPosition.TOP_RIGHT,
            )

    def _on_detail_download(self) -> None:
        summary = self._detail_summary
        if summary is None:
            return
        mode = self.modeCombo.currentData()
        self.detailBtn.setEnabled(False)

        # 走 download_collection_batch 而不是 Dress.download_collection：
        # 目录名与批量下载/卡片徽标统一（summary 名），且显式传 proxies
        def task(on_progress=None):
            return download_collection_batch(
                [summary],
                Path(cfg.download_dir.value),
                mode=mode,
                max_workers=cfg.max_workers.value,
                on_progress=on_progress,
            )

        started = start_download(
            task,
            self.detailBar,
            on_finished=self._on_detail_download_finished,
            parent=self.detailPage,
        )
        if not started:
            # 目录不可用：start_download 未启动任务、不会触发 finished，手动恢复
            self._on_detail_download_finished()

    def _on_detail_download_finished(self) -> None:
        self.detailBtn.setEnabled(True)
        self._refresh_downloaded()
