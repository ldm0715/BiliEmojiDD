"""设置页：Cookie / 下载目录 / 主题（Fluent 设置卡片版式）。

版式参照 Win11 / QFluentWidgets Gallery 设置页：大标题 → 分组标题 → 每行一张
「图标 + 标题 / 灰色副标题 + 右侧控件」窄卡片，整页滚动。控件与槽函数沿用改版前
的实现，本文件只负责「控件怎么摆」。
"""
from __future__ import annotations

from pathlib import Path

from biliemoji import Emoji
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    ExpandGroupSettingCard,
    ExpandLayout,
    FluentIcon,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    Theme,
    TitleLabel,
    ToolTipFilter,
    ToolTipPosition,
    qconfig,
    setTheme,
)

from app.common.config import APP_CONFIG_DIR, cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_success, notify_warning
from app.common.proxy import build_proxy, parse_proxy, proxy_env, split_proxy
from app.common.signal_bus import signal_bus
from app.common.theme import bind_theme
from app.components.download_runner import open_in_explorer
from app.components.task import run_task

_THEMES = [Theme.AUTO, Theme.LIGHT, Theme.DARK]

_PAGE_MARGIN = 36  # 分组左右留白（与大标题对齐）
_ROW_H = 60  # 展开区每行高度（addGroupWidget 靠固定高算展开高度）


class _WidgetSettingCard(SettingCard):
    """右侧可挂任意控件的设置行。

    库里只有 `PushSettingCard`（单个原生 QPushButton），这里复用同一套接线：
    `SettingCard.hBoxLayout` 末尾是 `addStretch(1)`，之后加的控件自然靠右排。
    """

    def __init__(self, icon, title, content=None, widgets=(), parent=None) -> None:
        super().__init__(icon, title, content, parent)
        for widget in widgets:
            widget.setParent(self)
            self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
            self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addSpacing(8)


def _expand_row(widgets, parent: QWidget | None = None) -> QWidget:
    """构造 `ExpandGroupSettingCard` 展开区的一行（左缩进对齐标题列）。

    `addGroupWidget` 按 `viewLayout.sizeHint()` 算展开高度，行必须有确定高度。
    """
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(48, 12, 24, 12)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        widget.setParent(row)
        layout.addWidget(widget, 1 if index == 0 else 0)
    row.setFixedHeight(_ROW_H)
    return row


def _button_box(buttons, parent: QWidget | None = None) -> QWidget:
    """把多个按钮包成一个控件。

    `HeaderSettingCard.addWidget` 每次调用都会重新把 `expandButton` 加进布局，
    **只能调一次**，所以多控件必须先包容器。
    """
    box = QWidget(parent)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for button in buttons:
        button.setParent(box)
        layout.addWidget(button)
    return box


class SettingPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titleLabel = TitleLabel("设置", self)
        # 缩进走布局边距，不用 setContentsMargins：Label 套了组件库 QSS，
        # QStyleSheetStyle 会用 QSS 盒模型重算 contentsMargins，手动设的被忽略
        title_box = QHBoxLayout()
        title_box.setContentsMargins(_PAGE_MARGIN, 20, _PAGE_MARGIN, 12)
        title_box.addWidget(self.titleLabel)
        title_box.addStretch(1)
        root.addLayout(title_box)

        self.scrollArea = ScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollWidget.setObjectName("settingScrollWidget")
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.expandLayout.setContentsMargins(_PAGE_MARGIN, 0, _PAGE_MARGIN, 24)
        self.expandLayout.setSpacing(28)
        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # FluentWindow 给 stackedWidget 套了 QSS，页面靠「自己不画背景」透出窗口底色；
        # QScrollArea 是原生控件，不显式透明会在暗色下露出 palette 的 Base 色块。
        # `.QWidget` 类选择器只命中 viewport / scrollWidget 这类纯 QWidget，不级联到卡片。
        self.scrollArea.setStyleSheet(
            "QScrollArea{border:none;background:transparent}"
            ".QWidget{background:transparent}"
        )
        root.addWidget(self.scrollArea, 1)

        self._build_account_group()
        self._build_download_group()
        self._build_theme_group()

    # ---- 账号 ----
    def _build_account_group(self) -> None:
        group = SettingCardGroup("账号", self.scrollWidget)

        self.cookieCard = ExpandGroupSettingCard(
            FluentIcon.VPN,
            "B 站 Cookie",
            "部分功能需要登录；Cookie 仅保存在本机配置中，不会上传",
            group,
        )
        self.cookieEdit = PasswordLineEdit(self.cookieCard)
        self.cookieEdit.setPlaceholderText("SESSDATA=...; bili_jct=...")
        self.cookieEdit.setText(cfg.cookie.value)
        self.saveBtn = PrimaryPushButton("保存", self.cookieCard)
        self.cookieCard.addGroupWidget(_expand_row([self.cookieEdit, self.saveBtn]))

        self.verifyBtn = PushButton("验证", group)
        self.verifyCard = _WidgetSettingCard(
            FluentIcon.CERTIFICATE,
            "访问权限",
            "用当前 Cookie 试拉取全部表情包，确认登录是否有效",
            [self.verifyBtn],
            group,
        )

        self.configCard = SettingCard(
            FluentIcon.DOCUMENT,
            "配置文件",
            str(APP_CONFIG_DIR / "config.json"),
            group,
        )

        group.addSettingCards([self.cookieCard, self.verifyCard, self.configCard])
        self.expandLayout.addWidget(group)
        self.accountGroup = group

        # 还没填 Cookie 时直接展开：首次使用不用先找到那个 ⌄
        if not cfg.cookie.value.strip():
            self.cookieCard.setExpand(True)

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
    def _build_download_group(self) -> None:
        group = SettingCardGroup("下载", self.scrollWidget)

        self.dirCard = ExpandGroupSettingCard(
            FluentIcon.DOWNLOAD,
            "下载目录",
            cfg.download_dir.value,
            group,
        )
        self.dirEdit = LineEdit(self.dirCard)
        self.dirEdit.setText(cfg.download_dir.value)
        self.browseBtn = PushButton("选择文件夹", self.dirCard)
        self.openDirBtn = PushButton("打开下载文件夹", self.dirCard)
        self.dirCard.addWidget(_button_box([self.browseBtn, self.openDirBtn]))
        self.dirCard.addGroupWidget(_expand_row([self.dirEdit]))
        # 副标题跟随路径（纯展示同步，保存逻辑仍读 dirEdit）；
        # ExpandSettingCard 自身没有 setContent，标题行在 .card 上
        self.dirEdit.textChanged.connect(self.dirCard.card.setContent)

        self.protoCombo = ComboBox(group)
        # qfluentwidgets addItem(text, icon, userData)：第二位置参是 icon，userData 须用关键字
        self.protoCombo.addItem("HTTP", userData="http")
        self.protoCombo.addItem("HTTPS", userData="https")
        self.protoCombo.setFixedWidth(105)
        self.hostEdit = LineEdit(group)
        self.hostEdit.setPlaceholderText("IP / 域名")
        self.hostEdit.setFixedWidth(150)
        self.portSpin = SpinBox(group)
        self.portSpin.setRange(1, 65535)
        # SpinBox 右侧上下按钮占掉约 64px，宽度给少了数字会被裁没
        self.portSpin.setFixedWidth(130)
        self.proxyCard = _WidgetSettingCard(
            FluentIcon.GLOBE,
            "代理",
            "留空不使用代理",
            [self.protoCombo, self.hostEdit, self.portSpin],
            group,
        )
        self.proxyCard.setToolTip(
            "代理仅支持 HTTP/HTTPS（socks 未安装 PySocks）；端口 1–65535，"
            "留空主机名表示不使用代理。"
        )
        # 组件库风格的提示气泡（原生 tooltip 不跟主题）
        self.proxyCard.installEventFilter(
            ToolTipFilter(self.proxyCard, 500, ToolTipPosition.TOP)
        )

        scheme, host, port = split_proxy(cfg.proxy.value)
        idx = self.protoCombo.findData(scheme if scheme in ("http", "https") else "http")
        self.protoCombo.setCurrentIndex(max(idx, 0))
        self.hostEdit.setText(host)
        self.portSpin.setValue(port if port > 0 else 7890)

        self.threadSpin = SpinBox(group)
        self.threadSpin.setRange(1, 16)
        self.threadSpin.setValue(cfg.max_workers.value)
        self.threadSpin.setFixedWidth(110)
        self.threadCard = _WidgetSettingCard(
            FluentIcon.SPEED_HIGH,
            "下载线程数",
            "同时下载的文件数（1–16）",
            [self.threadSpin],
            group,
        )

        self.downloadSaveBtn = PrimaryPushButton("保存", group)
        self.saveDownloadCard = _WidgetSettingCard(
            FluentIcon.SAVE,
            "保存下载设置",
            "下载目录、代理与线程数修改后需保存才生效",
            [self.downloadSaveBtn],
            group,
        )

        group.addSettingCards(
            [self.dirCard, self.proxyCard, self.threadCard, self.saveDownloadCard]
        )
        self.expandLayout.addWidget(group)
        self.downloadGroup = group

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
    def _build_theme_group(self) -> None:
        group = SettingCardGroup("外观", self.scrollWidget)

        self.themeCombo = ComboBox(group)
        # qfluentwidgets addItem(text, icon, userData)：图标用组件库 FluentIcon
        self.themeCombo.addItem("跟随系统", FluentIcon.SYNC, userData=Theme.AUTO)
        self.themeCombo.addItem("浅色", FluentIcon.BRIGHTNESS, userData=Theme.LIGHT)
        self.themeCombo.addItem("深色", FluentIcon.CONSTRACT, userData=Theme.DARK)
        self.themeCombo.setMinimumWidth(140)
        try:
            self.themeCombo.setCurrentIndex(_THEMES.index(cfg.theme.value))
        except ValueError:
            self.themeCombo.setCurrentIndex(0)
        self.themeCard = _WidgetSettingCard(
            FluentIcon.BRUSH,
            "应用主题",
            "调整应用的浅色 / 深色外观",
            [self.themeCombo],
            group,
        )

        group.addSettingCard(self.themeCard)
        self.expandLayout.addWidget(group)
        self.themeGroup = group

        self.themeCombo.currentIndexChanged.connect(self._on_theme_changed)
        signal_bus.configChanged.connect(self._sync_theme_combo)
        # ComboBox 闭合态只 setText 不 setIcon（上游行为），须自己补；
        # 且 FluentIcon 按调用瞬间的主题取黑/白 svg，主题切换后要重取
        bind_theme(self, self._sync_theme_icon)

    def _sync_theme_icon(self) -> None:
        """把当前选中项的图标同步到下拉框闭合态（ComboBox 自身不做这件事）。"""
        self.themeCombo.setIconSize(QSize(16, 16))
        self.themeCombo.setIcon(
            self.themeCombo.itemIcon(self.themeCombo.currentIndex())
        )

    def _sync_theme_combo(self) -> None:
        """外部切换主题（侧栏按钮）后同步下拉框显示。"""
        try:
            index = _THEMES.index(cfg.theme.value)
        except ValueError:
            index = 0
        self.themeCombo.blockSignals(True)
        self.themeCombo.setCurrentIndex(index)
        self.themeCombo.blockSignals(False)
        self._sync_theme_icon()  # 信号被屏蔽，图标得手动补

    def _on_theme_changed(self, index: int) -> None:
        theme = self.themeCombo.itemData(index)
        if theme is None:
            return
        # 先 setTheme 再存 cfg.theme：保证保存时 QFluentWidgets.ThemeMode 与应用主题一致
        setTheme(theme)
        qconfig.set(cfg.theme, theme)
        self._sync_theme_icon()
