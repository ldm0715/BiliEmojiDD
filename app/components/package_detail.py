"""表情包详情视图：包信息 + 缩略图网格 + GIF 开关 + 加入下载 + 下载 + 进度条。

供「按 ID 查询」与「全部表情包」两个标签页复用。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CheckBox,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
)

from app.common.config import cfg
from app.common.notify import notify_info, notify_success
from app.components.download_queue import download_queue
from app.components.download_runner import download_package_batch, start_download
from app.components.widgets import EmojiGrid


class PackageDetailView(QWidget):
    """展示一个表情包的完整内容并提供下载。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pkg = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.nameLabel = QLabel("尚未选择表情包", self)
        self.nameLabel.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detailLabel = QLabel("", self)
        self.detailLabel.setStyleSheet("color: gray;")
        layout.addWidget(self.nameLabel)
        layout.addWidget(self.detailLabel)

        layout.addWidget(QLabel("表情预览"))

        self.grid = EmojiGrid(self)
        layout.addWidget(self.grid, 1)

        download_row = QHBoxLayout()
        self.gifCheck = CheckBox("下载动图 (GIF)", self)
        self.gifCheck.setChecked(cfg.default_gif.value)
        self.queueBtn = PushButton("加入下载", self)
        self.queueBtn.setEnabled(False)
        self.downloadBtn = PrimaryPushButton("下载到本地", self)
        self.downloadBtn.setEnabled(False)
        download_row.addWidget(self.gifCheck)
        download_row.addStretch(1)
        download_row.addWidget(self.queueBtn)
        download_row.addWidget(self.downloadBtn)
        layout.addLayout(download_row)

        self.bar = ProgressBar(self)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        layout.addWidget(self.bar)

        self.queueBtn.clicked.connect(self._on_add_to_queue)
        self.downloadBtn.clicked.connect(self._on_download)

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
        self.downloadBtn.setEnabled(True)
        self.queueBtn.setEnabled(True)

    def show_loading(self, name: str) -> None:
        """详情数据拉取中：清空旧内容并提示。"""
        self._pkg = None
        self.nameLabel.setText(f"正在加载「{name or ''}」…")
        self.detailLabel.setText("")
        self.grid.set_emotes([])
        self.downloadBtn.setEnabled(False)
        self.queueBtn.setEnabled(False)

    def clear(self) -> None:
        self._pkg = None
        self.nameLabel.setText("尚未选择表情包")
        self.detailLabel.setText("")
        self.grid.set_emotes([])
        self.downloadBtn.setEnabled(False)
        self.queueBtn.setEnabled(False)

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
        enabled = self._pkg is not None
        self.downloadBtn.setEnabled(enabled)
        self.queueBtn.setEnabled(enabled)
