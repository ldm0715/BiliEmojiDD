"""下载队列页：展示队列、全选/删除/清空、批量下载（单进度条）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
)

from app.common.config import cfg
from app.common.notify import notify_warning
from app.common.theme import SECONDARY_TEXT
from app.components.download_queue import download_queue, item_key
from app.components.download_runner import download_mixed_batch, start_download
from app.components.widgets import QueueList


class DownloadPage(QWidget):
    """会话级下载队列：多选操作 + 批量下载。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._downloading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.countLabel = CaptionLabel("共 0 个内容", self)
        self.countLabel.setTextColor(*SECONDARY_TEXT)
        self.selectAllBtn = PushButton("全选", self)
        self.deleteBtn = PushButton("删除选中", self)
        self.clearBtn = PushButton("清空", self)
        self.downloadBtn = PrimaryPushButton("下载选中", self)
        header.addWidget(self.countLabel)
        header.addStretch(1)
        header.addWidget(self.selectAllBtn)
        header.addWidget(self.deleteBtn)
        header.addWidget(self.clearBtn)
        header.addWidget(self.downloadBtn)
        layout.addLayout(header)

        self.grid = QueueList(self)
        self.grid.set_selectable(True)  # 队列页常开多选
        layout.addWidget(self.grid, 1)

        self.emptyLabel = BodyLabel(
            "队列为空\n可在「表情包」「收藏集」页多选后加入，或从包详情页点击「加入下载」", self
        )
        self.emptyLabel.setTextColor(*SECONDARY_TEXT)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.emptyLabel, 1)

        self.statusLabel = BodyLabel("", self)
        self.statusLabel.setTextColor(*SECONDARY_TEXT)
        self.statusLabel.hide()
        layout.addWidget(self.statusLabel)

        self.bar = ProgressBar(self)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        layout.addWidget(self.bar)

        self.selectAllBtn.clicked.connect(self._select_all)
        self.deleteBtn.clicked.connect(self._remove_selected)
        self.clearBtn.clicked.connect(self._clear_all)
        self.downloadBtn.clicked.connect(self._download_selected)
        self.grid.selectionChanged.connect(self._update_ui)
        download_queue.changed.connect(self._rebuild)

        self._rebuild()

    # ---- 队列刷新与 UI 状态 ----

    def _rebuild(self) -> None:
        items = download_queue.items()
        self.grid.set_items(items)
        self.countLabel.setText(f"共 {len(items)} 个内容")
        has = bool(items)
        self.grid.setVisible(has)
        self.emptyLabel.setVisible(not has)
        self._update_ui()

    def _update_ui(self) -> None:
        n = self.grid.checked_count()
        has = bool(download_queue.items())
        busy = self._downloading
        self.selectAllBtn.setEnabled(has and not busy)
        self.deleteBtn.setEnabled(n > 0 and not busy)
        self.clearBtn.setEnabled(has and not busy)
        self.downloadBtn.setEnabled(n > 0 and not busy)

    def _selected_items(self) -> list:
        return self.grid.checked_items()

    # ---- 操作 ----

    def _select_all(self) -> None:
        self.grid.set_all_checked(True)

    def _remove_selected(self) -> None:
        items = self._selected_items()
        if not items:
            notify_warning(
                "未选择",
                "请先选择要删除的表情包 / 收藏集",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        download_queue.remove(item_key(it) for it in items)

    def _clear_all(self) -> None:
        if not download_queue.items():
            return
        download_queue.clear()

    def _download_selected(self) -> None:
        if self._downloading:
            return
        items = self._selected_items()
        if not items:
            notify_warning(
                "未选择",
                "请先选择要下载的表情包 / 收藏集",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self._downloading = True
        self._update_ui()

        def task(on_progress=None):
            return download_mixed_batch(
                items,
                Path(cfg.download_dir.value),
                gif=None,
                mode="both",
                max_workers=cfg.max_workers.value,
                on_progress=on_progress,
            )

        started = start_download(
            task,
            self.bar,
            on_finished=self._on_download_finished,
            status_label=self.statusLabel,
            parent=self,
        )
        if not started:
            # 目录不可用：start_download 未启动任务、不会触发 finished，手动恢复一次
            self._on_download_finished()

    def _on_download_finished(self) -> None:
        # 幂等：任务异常 / 完成 / 未启动三条路径只恢复一次 UI
        self._downloading = False
        self._update_ui()
