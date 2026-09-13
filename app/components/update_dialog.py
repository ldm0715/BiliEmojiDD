"""更新弹窗：展示渲染后的更新说明，下载并运行安装程序。

版式是 `MessageBoxBase`（窗口内遮罩对话框）：标题 → 元信息 → **markdown 渲染的更新
说明** → 进度条 → 状态行，底部「发布页 / 下载并安装 / 稍后」。

三个必须这么写的地方：

1. **`yesButton` 要先 `disconnect()`**。上游 `MessageBoxBase.__onYesButtonClicked` 直接
   `accept()` 关窗，不断开的话点「下载并安装」弹窗当场消失，进度条根本没机会露面。
2. **更新说明用组件库的 `TextEdit`**（不是裸 `QTextEdit`）：它构造时
   `FluentStyleSheet.LINE_EDIT.apply(self)` 注册进了 `styleSheetManager`，主题与字体
   自动跟随；裸控件在暗色下是白底黑字。`QTextEdit.setMarkdown` 走 GitHub 方言，
   标题 / 列表 / 表格 / 代码块都认。
3. **关应用走 `window.close()` 而不是 `QApplication.quit()`**：后者不触发 `closeEvent`，
   `video_cache.cleanup()` 的临时目录就漏在磁盘上了。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    HyperlinkButton,
    MessageBoxBase,
    ProgressBar,
    SubtitleLabel,
    TextEdit,
)

from app.common.config import APP_VERSION, cfg
from app.common.exception import cause_hint
from app.common.notify import NEVER_DISMISS, notify_error
from app.common.theme import SECONDARY_TEXT
from app.components.task import run_task
from app.components.updater import (
    ChecksumMismatch,
    ReleaseInfo,
    UpdateError,
    download_asset,
)

_DIALOG_W = 560
_NOTES_H = 260


def _failure_detail(exc: Exception) -> str:
    """失败详情那一行：**`updater` 自己的异常直接用它的消息**，其余才走 `cause_hint`。

    `cause_hint` 是给 biliemoji 那类「外层消息无用、真因埋在 `__cause__` 里」的异常
    准备的（见 `app/common/exception.py` 模块注释）。`updater` 抛的每条消息却已经是
    写给用户看的，而它多半带 `from exc` 的异常链——让 `cause_hint` 顺链翻到底层的
    `ConnectTimeout`，就会用「连接超时。请检查网络；若走了代理，确认代理可用。」
    盖掉真正该说的那句，而这里的失败多半出在加速源上，指向完全错了。
    """
    if isinstance(exc, UpdateError):
        return str(exc) or type(exc).__name__
    return cause_hint(exc) or str(exc) or type(exc).__name__


class UpdateDialog(MessageBoxBase):
    """「发现新版本」对话框。parent 传主窗口（遮罩铺满它）。"""

    def __init__(self, info: ReleaseInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._info = info
        self._window = parent.window() if parent is not None else None

        self.titleLabel = SubtitleLabel(f"发现新版本 {info.tag}", self)
        self.titleLabel.setWordWrap(True)
        self.metaLabel = CaptionLabel(self._meta_text(), self)
        self.metaLabel.setTextColor(*SECONDARY_TEXT)
        self.metaLabel.setWordWrap(True)

        self.notesEdit = TextEdit(self)
        self.notesEdit.setReadOnly(True)
        self.notesEdit.setMinimumHeight(_NOTES_H)
        self.notesEdit.setMarkdown(info.notes or "（本次发布没有填写更新说明）")

        self.progressBar = ProgressBar(self)
        self.progressBar.setRange(0, 100)
        self.progressBar.hide()
        self.statusLabel = CaptionLabel("", self)
        self.statusLabel.setTextColor(*SECONDARY_TEXT)
        self.statusLabel.setWordWrap(True)
        self.statusLabel.hide()

        for widget in (
            self.titleLabel,
            self.metaLabel,
            self.notesEdit,
            self.progressBar,
            self.statusLabel,
        ):
            self.viewLayout.addWidget(widget)

        self.linkBtn = HyperlinkButton(
            info.html_url, "发布页", self.buttonGroup, FluentIcon.LINK
        )
        self.buttonLayout.insertWidget(0, self.linkBtn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cancelButton.setText("稍后")
        self.yesButton.setText("下载并安装" if info.has_installer else "打开发布页")
        # 上游已把 yesButton 连到 accept()，不断开就是「一点就关窗」
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._on_yes)

        self.widget.setMinimumWidth(_DIALOG_W)

    # ---- 展示 ----

    def _meta_text(self) -> str:
        parts = [f"当前 v{APP_VERSION}"]
        if self._info.published:
            parts.append(f"发布于 {self._info.published}")
        if self._info.size_text:
            parts.append(f"{self._info.asset_name} · {self._info.size_text}")
        return " · ".join(parts)

    def _set_status(self, text: str) -> None:
        self.statusLabel.setText(text)
        self.statusLabel.setVisible(bool(text))

    # ---- 下载 ----

    def _on_yes(self) -> None:
        if not self._info.has_installer:  # 只发了便携 zip / 没有资产
            QDesktopServices.openUrl(self._info.html_url)
            return
        self.yesButton.setEnabled(False)
        self.progressBar.setValue(0)
        self.progressBar.show()
        self._set_status("正在下载安装包…")
        run_task(
            download_asset,
            self._info,
            needs_progress=True,
            on_progress=self._on_progress,
            on_success=self._on_downloaded,
            on_error=self._on_failed,
        )

    def _on_progress(self, done: int, total: int, _result) -> None:
        if total > 0:
            self.progressBar.setValue(round(done * 100 / total))
        self._set_status(
            f"正在下载安装包… {done / (1024 * 1024):.1f} MB"
            + (f" / {total / (1024 * 1024):.1f} MB" if total > 0 else "")
        )

    def _on_downloaded(self, path) -> None:
        self.progressBar.setValue(100)
        self._set_status("下载完成，即将关闭 BiliEmojiDD 并启动安装程序")
        os.startfile(str(path))  # Windows only，与 download_runner 同
        self.accept()
        if self._window is not None:
            # 关窗要走 closeEvent（video_cache 的临时目录在那里清），
            # 所以是 close() 不是 QApplication.quit()
            QTimer.singleShot(0, self._window.close)

    def _on_failed(self, exc: Exception) -> None:
        self.progressBar.hide()
        self.yesButton.setEnabled(True)
        if isinstance(exc, ChecksumMismatch):
            self._set_status("校验失败，安装包已丢弃")
            notify_error(
                "安装包校验失败",
                f"{exc}\n文件已删除，未运行。请改用直连或换一个加速镜像后重试。",
                parent=self._window,
                duration=NEVER_DISMISS,
            )
            return
        self._set_status("下载失败")
        lines = [_failure_detail(exc)]
        if not cfg.gh_mirror.value:
            lines.append("直连 GitHub 慢或不通时，可在「设置 → 关于 → 下载加速」选一个镜像后重试。")
        else:
            lines.append("可在「设置 → 关于 → 下载加速」测速后调整加速源与顺序，再试一次。")
        notify_error(
            "下载失败",
            "\n".join(lines),
            parent=self._window,
            duration=NEVER_DISMISS,
        )


def show_update_dialog(info: ReleaseInfo, parent: QWidget | None = None) -> UpdateDialog:
    """建好并显示更新弹窗。用 `show()` 不用 `exec()`——下载是异步的，不能阻塞事件循环。"""
    dialog = UpdateDialog(info, parent)
    dialog.show()
    return dialog
