"""设置页：Cookie / 下载目录 / 主题。"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Emoji
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    Theme,
    qconfig,
    setTheme,
)

from app.common.config import APP_CONFIG_DIR, cfg
from app.common.exception import show_bili_error
from app.common.signal_bus import signal_bus
from app.components.task import run_task

_THEMES = [Theme.AUTO, Theme.LIGHT, Theme.DARK]


class SettingPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(16)

        self._build_account_card(layout)
        self._build_download_card(layout)
        self._build_theme_card(layout)
        layout.addStretch(1)

    # ---- 账号 ----
    def _build_account_card(self, layout: QVBoxLayout) -> None:
        card = CardWidget(self)
        v = QVBoxLayout(card)
        v.setSpacing(8)

        title = QLabel("账号（Cookie）", card)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        desc = QLabel(
            "部分功能（全部表情包、收藏集下载）需要登录。Cookie 仅保存在本机"
            "配置中，不会上传。",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: gray;")

        self.cookieEdit = PasswordLineEdit(card)
        self.cookieEdit.setPlaceholderText("SESSDATA=...; bili_jct=...")
        self.cookieEdit.setText(cfg.cookie.value)

        row = QHBoxLayout()
        self.saveBtn = PrimaryPushButton("保存 Cookie", card)
        self.verifyBtn = PushButton("验证表情包访问权限", card)
        row.addWidget(self.saveBtn)
        row.addWidget(self.verifyBtn)
        row.addStretch(1)

        hint = QLabel(
            f"配置保存在：{APP_CONFIG_DIR / 'config.json'}",
            card,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 12px;")

        v.addWidget(title)
        v.addWidget(desc)
        v.addWidget(self.cookieEdit)
        v.addLayout(row)
        v.addWidget(hint)

        layout.addWidget(card)

        self.saveBtn.clicked.connect(self._on_save)
        self.verifyBtn.clicked.connect(self._on_verify)

    def _on_save(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        directory = self.dirEdit.text().strip()
        if not directory:
            InfoBar.warning(
                "下载目录为空",
                "请选择下载目录",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        qconfig.set(cfg.cookie, cookie)
        qconfig.set(cfg.download_dir, directory)
        signal_bus.configChanged.emit()
        InfoBar.success(
            "已保存",
            "Cookie 与下载目录已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_verify(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        if not cookie:
            InfoBar.warning(
                "未填写 Cookie",
                "请先填写 Cookie 再验证",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.verifyBtn.setEnabled(False)

        # 以 biliemoji 2.0.0 实际 API 为准：all_packages() 会校验 cookie 并可能拉取全量
        def task():
            return Emoji(cookie=cookie).all_packages()

        run_task(
            task,
            on_success=self._on_verify_ok,
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.verifyBtn.setEnabled(True),
        )

    def _on_verify_ok(self, packages) -> None:
        InfoBar.success(
            "验证通过",
            f"表情包访问权限有效，共 {len(packages)} 个表情包",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    # ---- 下载目录 ----
    def _build_download_card(self, layout: QVBoxLayout) -> None:
        card = CardWidget(self)
        v = QVBoxLayout(card)
        v.setSpacing(8)

        title = QLabel("下载目录", card)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")

        row = QHBoxLayout()
        self.dirEdit = LineEdit(card)
        self.dirEdit.setText(cfg.download_dir.value)
        self.browseBtn = PushButton("浏览…", card)
        row.addWidget(self.dirEdit, 1)
        row.addWidget(self.browseBtn)
        v.addWidget(title)
        v.addLayout(row)

        layout.addWidget(card)

        self.browseBtn.clicked.connect(self._on_browse)

    def _on_browse(self) -> None:
        start = self.dirEdit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择下载目录", start)
        if directory:
            self.dirEdit.setText(directory)

    # ---- 主题 ----
    def _build_theme_card(self, layout: QVBoxLayout) -> None:
        card = CardWidget(self)
        v = QVBoxLayout(card)
        v.setSpacing(8)

        title = QLabel("外观", card)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")

        row = QHBoxLayout()
        row.addWidget(QLabel("主题", card))
        self.themeCombo = ComboBox(card)
        self.themeCombo.addItem("跟随系统", Theme.AUTO)
        self.themeCombo.addItem("浅色", Theme.LIGHT)
        self.themeCombo.addItem("深色", Theme.DARK)
        try:
            self.themeCombo.setCurrentIndex(_THEMES.index(cfg.theme.value))
        except ValueError:
            self.themeCombo.setCurrentIndex(0)
        row.addWidget(self.themeCombo)
        row.addStretch(1)
        v.addWidget(title)
        v.addLayout(row)

        layout.addWidget(card)

        self.themeCombo.currentIndexChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self, index: int) -> None:
        theme = self.themeCombo.itemData(index)
        if theme is None:
            return
        qconfig.set(cfg.theme, theme)
        setTheme(theme)
