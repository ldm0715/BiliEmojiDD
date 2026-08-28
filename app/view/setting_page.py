"""设置页：Cookie / 下载目录 / 主题。"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Emoji
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    Theme,
    qconfig,
    setTheme,
)

from app.common.config import APP_CONFIG_DIR, cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_success, notify_warning
from app.common.proxy import build_proxy, parse_proxy, proxy_env, split_proxy
from app.common.signal_bus import signal_bus
from app.components.download_runner import open_in_explorer
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

        title = StrongBodyLabel("账号（Cookie）", card)
        self.descLabel = BodyLabel(
            "部分功能（全部表情包、收藏集下载）需要登录。Cookie 仅保存在本机"
            "配置中，不会上传。",
            card,
        )
        self.descLabel.setWordWrap(True)

        self.cookieEdit = PasswordLineEdit(card)
        self.cookieEdit.setPlaceholderText("SESSDATA=...; bili_jct=...")
        self.cookieEdit.setText(cfg.cookie.value)

        row = QHBoxLayout()
        self.saveBtn = PrimaryPushButton("保存 Cookie", card)
        self.verifyBtn = PushButton("验证表情包访问权限", card)
        row.addWidget(self.saveBtn)
        row.addWidget(self.verifyBtn)
        row.addStretch(1)

        self.configHintLabel = CaptionLabel(
            f"配置保存在：{APP_CONFIG_DIR / 'config.json'}",
            card,
        )
        self.configHintLabel.setWordWrap(True)

        v.addWidget(title)
        v.addWidget(self.descLabel)
        v.addWidget(self.cookieEdit)
        v.addLayout(row)
        v.addWidget(self.configHintLabel)

        layout.addWidget(card)

        self.saveBtn.clicked.connect(self._on_save)
        self.verifyBtn.clicked.connect(self._on_verify)

    def _on_save(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        qconfig.set(cfg.cookie, cookie)
        signal_bus.configChanged.emit()
        notify_success(
            "已保存",
            "Cookie 已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_verify(self) -> None:
        cookie = self.cookieEdit.text().strip().strip('"\'')
        if not cookie:
            notify_warning(
                "未填写 Cookie",
                "请先填写 Cookie 再验证",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.verifyBtn.setEnabled(False)

        # 以 biliemoji 2.0.0 实际 API 为准：all_packages() 会校验 cookie 并可能拉取全量
        def task():
            return Emoji(
                cookie=cookie, proxies=parse_proxy(cfg.proxy.value)
            ).all_packages()

        run_task(
            task,
            on_success=self._on_verify_ok,
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.verifyBtn.setEnabled(True),
        )

    def _on_verify_ok(self, packages) -> None:
        notify_success(
            "验证通过",
            f"表情包访问权限有效，共 {len(packages)} 个表情包",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    # ---- 下载 ----
    def _build_download_card(self, layout: QVBoxLayout) -> None:
        card = CardWidget(self)
        v = QVBoxLayout(card)
        v.setSpacing(8)

        title = StrongBodyLabel("下载", card)

        dir_row = QHBoxLayout()
        dir_row.addWidget(BodyLabel("下载目录", card))
        self.dirEdit = LineEdit(card)
        self.dirEdit.setText(cfg.download_dir.value)
        self.browseBtn = PushButton("浏览…", card)
        self.openDirBtn = PushButton("打开下载文件夹", card)
        dir_row.addWidget(self.dirEdit, 1)
        dir_row.addWidget(self.browseBtn)
        dir_row.addWidget(self.openDirBtn)

        proxy_row = QHBoxLayout()
        proxy_row.addWidget(BodyLabel("代理地址", card))
        self.protoCombo = ComboBox(card)
        # qfluentwidgets addItem(text, icon, userData)：第二位置参是 icon，userData 须用关键字
        self.protoCombo.addItem("HTTP", userData="http")
        self.protoCombo.addItem("HTTPS", userData="https")
        self.hostEdit = LineEdit(card)
        self.hostEdit.setPlaceholderText("IP / 域名")
        self.hostEdit.setFixedWidth(180)
        self.portSpin = SpinBox(card)
        self.portSpin.setRange(1, 65535)
        proxy_row.addWidget(self.protoCombo)
        proxy_row.addWidget(self.hostEdit)
        proxy_row.addWidget(self.portSpin)
        proxy_row.addStretch(1)

        scheme, host, port = split_proxy(cfg.proxy.value)
        idx = self.protoCombo.findData(scheme if scheme in ("http", "https") else "http")
        self.protoCombo.setCurrentIndex(max(idx, 0))
        self.hostEdit.setText(host)
        self.portSpin.setValue(port if port > 0 else 7890)

        thread_row = QHBoxLayout()
        thread_row.addWidget(BodyLabel("下载线程数", card))
        self.threadSpin = SpinBox(card)
        self.threadSpin.setRange(1, 16)
        self.threadSpin.setValue(cfg.max_workers.value)
        thread_row.addWidget(self.threadSpin)
        thread_row.addStretch(1)

        self.downloadSaveBtn = PrimaryPushButton("保存下载设置", card)
        self.downloadHintLabel = CaptionLabel(
            "代理仅支持 HTTP/HTTPS（socks 未安装 PySocks）；端口 1–65535，留空主机名表示不使用代理。",
            card,
        )
        self.downloadHintLabel.setWordWrap(True)

        v.addWidget(title)
        v.addLayout(dir_row)
        v.addLayout(proxy_row)
        v.addLayout(thread_row)
        v.addWidget(self.downloadSaveBtn, 0, Qt.AlignmentFlag.AlignRight)
        v.addWidget(self.downloadHintLabel)

        layout.addWidget(card)

        self.browseBtn.clicked.connect(self._on_browse)
        self.openDirBtn.clicked.connect(self._on_open_dir)
        self.downloadSaveBtn.clicked.connect(self._on_save_download)

    def _on_browse(self) -> None:
        start = self.dirEdit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择下载目录", start)
        if directory:
            self.dirEdit.setText(directory)

    def _on_open_dir(self) -> None:
        path = Path(self.dirEdit.text().strip() or cfg.download_dir.value)
        path.mkdir(parents=True, exist_ok=True)
        open_in_explorer(path, self)

    def _on_save_download(self) -> None:
        directory = self.dirEdit.text().strip()
        if not directory:
            notify_warning(
                "下载目录为空",
                "请选择下载目录",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        scheme = self.protoCombo.currentData() or "http"
        host = self.hostEdit.text().strip()
        if host and ("://" in host or " " in host):
            notify_warning(
                "无效主机名",
                "主机名不能包含协议前缀或空格，请分别填写协议 / IP / 端口",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )
            return
        port = self.portSpin.value()
        proxy_text = build_proxy(scheme, host, port)  # 主机名为空 -> 不使用代理
        qconfig.set(cfg.download_dir, directory)
        qconfig.set(cfg.proxy, proxy_text)
        qconfig.set(cfg.max_workers, self.threadSpin.value())
        proxy_env.apply(proxy_text)
        signal_bus.configChanged.emit()
        notify_success(
            "已保存",
            "下载目录、代理与线程数已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    # ---- 主题 ----
    def _build_theme_card(self, layout: QVBoxLayout) -> None:
        card = CardWidget(self)
        v = QVBoxLayout(card)
        v.setSpacing(8)

        title = StrongBodyLabel("外观", card)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("主题", card))
        self.themeCombo = ComboBox(card)
        # qfluentwidgets addItem(text, icon, userData)：图标用组件库 FluentIcon
        self.themeCombo.addItem("跟随系统", FluentIcon.SYNC, userData=Theme.AUTO)
        self.themeCombo.addItem("浅色", FluentIcon.BRIGHTNESS, userData=Theme.LIGHT)
        self.themeCombo.addItem("深色", FluentIcon.CONSTRACT, userData=Theme.DARK)
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
        signal_bus.configChanged.connect(self._sync_theme_combo)

    def _sync_theme_combo(self) -> None:
        """外部切换主题（侧栏按钮）后同步下拉框显示。"""
        try:
            index = _THEMES.index(cfg.theme.value)
        except ValueError:
            index = 0
        self.themeCombo.blockSignals(True)
        self.themeCombo.setCurrentIndex(index)
        self.themeCombo.blockSignals(False)

    def _on_theme_changed(self, index: int) -> None:
        theme = self.themeCombo.itemData(index)
        if theme is None:
            return
        # 先 setTheme 再存 cfg.theme：保证保存时 QFluentWidgets.ThemeMode 与应用主题一致
        setTheme(theme)
        qconfig.set(cfg.theme, theme)
