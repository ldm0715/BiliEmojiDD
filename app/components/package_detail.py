"""表情包详情视图：头部卡（信息 + 操作 + 进度）+ 预览卡（缩略图网格）。

供「按 ID 查询」与「全部表情包」两个标签页复用。「全部表情包」还会通过
`add_leading_widget` 把「返回列表」按钮塞进头部卡左侧。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    InfoBadge,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
)

from app.common.config import cfg
from app.common.notify import notify_info, notify_success
from app.common.theme import SECONDARY_TEXT
from app.components.content_meta import ContentMeta, content_meta
from app.components.download_queue import download_queue
from app.components.download_runner import (
    download_package_batch,
    downloaded_exists,
    package_download_dir,
    start_download,
)
from app.components.image_viewer import show_image_viewer
from app.components.page_scaffold import SECTION_SPACING, CommandCard, SectionCard
from app.components.widgets import EmojiGrid


class PackageDetailView(QWidget):
    """展示一个表情包的完整内容并提供下载。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pkg = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_SPACING)

        # ---- 头部卡：名称 / 元信息 / 徽标 / 操作按钮 / 进度条 ----
        self.headerCard = CommandCard(self)
        self._titleRow = self.headerCard.add_row()

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        self.nameLabel = SubtitleLabel("尚未选择表情包", self.headerCard)
        self.detailLabel = CaptionLabel("", self.headerCard)
        self.detailLabel.setTextColor(*SECONDARY_TEXT)
        # 换行：QLabel 不换行时最小宽度就是整串文字宽度，长包名会顶得整页缩不下去
        self.nameLabel.setWordWrap(True)
        self.detailLabel.setWordWrap(True)
        title_box.addWidget(self.nameLabel)
        title_box.addWidget(self.detailLabel)
        self._titleRow.addLayout(title_box, 1)

        self.downloadedLabel = InfoBadge.success("已下载", self.headerCard)
        self.downloadedLabel.hide()
        self.queueBtn = PushButton("加入下载", self.headerCard)
        self.queueBtn.setEnabled(False)
        self.downloadBtn = PrimaryPushButton("下载到本地", self.headerCard)
        self.downloadBtn.setEnabled(False)
        for w in (self.downloadedLabel, self.queueBtn, self.downloadBtn):
            self._titleRow.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

        # 下载选项行：整行显隐（包里没有任何 gif_url 时隐藏，勾了也只会回退 PNG）
        self.gifRow, option_row = self.headerCard.add_row_widget()
        self.gifCheck = CheckBox("下载动图 (GIF)", self.gifRow)
        self.gifCheck.setChecked(cfg.default_gif.value)
        option_row.addStretch(1)
        option_row.addWidget(self.gifCheck)
        self.gifRow.setVisible(False)

        self.bar = ProgressBar(self.headerCard)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        self.headerCard.add_widget(self.bar)
        layout.addWidget(self.headerCard)

        # ---- 预览卡：表情网格 ----
        self.previewCard = SectionCard("表情预览", self)
        self.grid = EmojiGrid(self.previewCard)
        self.previewCard.add_widget(self.grid)
        layout.addWidget(self.previewCard, 1)

        self.queueBtn.clicked.connect(self._on_add_to_queue)
        self.downloadBtn.clicked.connect(self._on_download)
        self.grid.imageClicked.connect(self._open_image_viewer)
        # 队列变化时同步「加入下载/已加入」按钮状态
        download_queue.changed.connect(self._sync_queue_btn)

    def add_leading_widget(self, widget: QWidget) -> None:
        """把控件（如「返回列表」按钮）插到头部卡标题行最左侧。"""
        widget.setParent(self.headerCard)
        self._titleRow.insertWidget(0, widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def _open_image_viewer(self, index: int) -> None:
        items = self.grid.items()
        if index < 0 or not items:
            return
        show_image_viewer(items, index, self.window())

    def set_package(self, pkg) -> None:
        """填充包信息与表情网格（pkg 需已含完整 emote 列表）。"""
        self._pkg = pkg
        self.nameLabel.setText(pkg.text or f"表情包 #{pkg.id}")
        badge = "GIF 动图包" if pkg.is_gif else "静态包"
        self.detailLabel.setText(
            f"ID: {pkg.id} · {len(pkg.emote)} 个表情 · {badge}"
        )
        items = []
        for em in pkg.emote:
            url = em.gif_url or em.url
            if url:
                items.append((em.text or "", url))
        self.grid.set_emotes(items)
        # GIF 选项按「包里真的有没有 gif_url」显隐：pkg.is_gif 只看 meta.label_text，
        # 与 download_package_batch 里 `if use_gif and em.gif_url` 的实际取用不同步
        has_gif = any(em.gif_url for em in pkg.emote)
        self.gifRow.setVisible(has_gif)
        self.gifCheck.setChecked(has_gif and cfg.default_gif.value)
        # 队列页要显示「多少张图片」，这里顺手喂缓存，省掉它再拉一次详情
        content_meta.remember(pkg, ContentMeta(len(items), 0))
        self.downloadBtn.setEnabled(True)
        self._sync_queue_btn()
        self._refresh_downloaded()

    def show_loading(self, name: str) -> None:
        """详情数据拉取中：清空旧内容并提示。"""
        self._pkg = None
        self.nameLabel.setText(f"正在加载「{name or ''}」…")
        self.detailLabel.setText("")
        self.grid.set_emotes([])
        self.gifRow.setVisible(False)
        self.downloadBtn.setEnabled(False)
        self.queueBtn.setText("加入下载")
        self.queueBtn.setEnabled(False)
        self.downloadedLabel.hide()

    def clear(self) -> None:
        self._pkg = None
        self.nameLabel.setText("尚未选择表情包")
        self.detailLabel.setText("")
        self.grid.set_emotes([])
        self.gifRow.setVisible(False)
        self.downloadBtn.setEnabled(False)
        self.queueBtn.setText("加入下载")
        self.queueBtn.setEnabled(False)
        self.downloadedLabel.hide()

    def _on_add_to_queue(self) -> None:
        if self._pkg is None:
            return
        name = self._pkg.text or f"#{self._pkg.id}"
        if download_queue.add(self._pkg):
            notify_success(
                "已加入下载队列",
                f"「{name}」已加入，可前往「下载」页查看",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
        else:
            notify_info(
                "已在下载队列",
                f"「{name}」已在队列中",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )

    def _on_download(self) -> None:
        if self._pkg is None:
            return
        pkg = self._pkg
        self.downloadBtn.setEnabled(False)
        self.queueBtn.setEnabled(False)

        def task(on_progress=None):
            return download_package_batch(
                [pkg.id],
                Path(cfg.download_dir.value),
                gif=self.gifCheck.isChecked(),
                max_workers=cfg.max_workers.value,
                on_progress=on_progress,
            )

        started = start_download(
            task,
            self.bar,
            on_finished=self._restore_buttons,
            parent=self,
        )
        if not started:
            # 目录不可用：start_download 未启动任务、不会触发 finished，需手动恢复
            self._restore_buttons()

    def _restore_buttons(self) -> None:
        self.downloadBtn.setEnabled(self._pkg is not None)
        self._sync_queue_btn()
        self._refresh_downloaded()

    def _sync_queue_btn(self) -> None:
        """「加入下载 / 已加入」状态单一同步源：无包或已在队列 → 「已加入」禁用。"""
        pkg = self._pkg
        if pkg is None:
            self.queueBtn.setText("加入下载")
            self.queueBtn.setEnabled(False)
        elif download_queue.contains(pkg):
            self.queueBtn.setText("已加入")
            self.queueBtn.setEnabled(False)
        else:
            self.queueBtn.setText("加入下载")
            self.queueBtn.setEnabled(True)

    def _refresh_downloaded(self) -> None:
        """已下载状态：目标目录存在且非空即显示「已下载过」。"""
        pkg = self._pkg
        self.downloadedLabel.setVisible(
            pkg is not None and downloaded_exists(package_download_dir(pkg))
        )
