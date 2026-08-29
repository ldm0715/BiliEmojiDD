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
    CaptionLabel,
    ComboBox,
    ExpandGroupSettingCard,
    ExpandLayout,
    FluentIcon,
    IconWidget,
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

from app.common.config import APP_CONFIG_DIR, APP_VERSION, cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_success, notify_warning
from app.common.proxy import (
    PROXY_SCHEMES,
    build_proxy,
    is_socks,
    parse_proxy,
    pysocks_available,
    split_proxy_auth,
)
from app.common.resource import app_icon
from app.common.signal_bus import signal_bus
from app.common.theme import SECONDARY_TEXT, bind_theme
from app.components.disk_cache import MB, clear_all, total_size
from app.components.download_runner import open_in_explorer
from app.components.proxy_probe import probe_proxy
from app.components.task import run_task

_THEMES = [Theme.AUTO, Theme.LIGHT, Theme.DARK]

_PAGE_MARGIN = 36  # 分组左右留白（与大标题对齐）
_LOGO_SIZE = 64  # 顶部应用图标边长
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

        # 顶部身份区：整体居中，第一行大图标，第二行「应用名 + 版本号」
        self.titleLabel = TitleLabel("BiliEmojiDD", self)
        self.logoIcon = IconWidget(app_icon(), self)
        self.logoIcon.setFixedSize(_LOGO_SIZE, _LOGO_SIZE)
        self.versionLabel = CaptionLabel(f"v{APP_VERSION}", self)
        self.versionLabel.setTextColor(*SECONDARY_TEXT)
        # 缩进/留白走布局边距，不用 setContentsMargins：Label 套了组件库 QSS，
        # QStyleSheetStyle 会用 QSS 盒模型重算 contentsMargins，手动设的被忽略
        header_box = QVBoxLayout()
        header_box.setContentsMargins(_PAGE_MARGIN, 20, _PAGE_MARGIN, 16)
        header_box.setSpacing(6)
        header_box.addWidget(
            self.logoIcon, 0, Qt.AlignmentFlag.AlignHCenter
        )
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(8)
        name_row.addStretch(1)
        name_row.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        # 版本号贴着应用名底部排
        name_row.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignBottom)
        name_row.addStretch(1)
        header_box.addLayout(name_row)
        root.addLayout(header_box)

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
        self._build_cache_group()
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
        # 注意这里选的是**代理自身**说什么协议，不是被代理流量的协议
        self.protoCombo.addItem("HTTP", userData="http")
        self.protoCombo.addItem("HTTPS", userData="https")
        self.protoCombo.addItem("SOCKS5", userData="socks5")
        self.protoCombo.addItem("SOCKS5 (远程 DNS)", userData="socks5h")
        self.protoCombo.setFixedWidth(150)
        self.hostEdit = LineEdit(group)
        self.hostEdit.setPlaceholderText("IP / 域名")
        self.hostEdit.setFixedWidth(150)
        self.portSpin = SpinBox(group)
        self.portSpin.setRange(1, 65535)
        # SpinBox 右侧上下按钮占掉约 64px，宽度给少了数字会被裁没
        self.portSpin.setFixedWidth(130)
        self.proxyTestBtn = PushButton("测试", group)
        self.proxyCard = _WidgetSettingCard(
            FluentIcon.GLOBE,
            "代理",
            "协议指代理自身的协议；留空主机名不使用代理",
            [self.protoCombo, self.hostEdit, self.portSpin, self.proxyTestBtn],
            group,
        )
        self.proxyCard.setToolTip(
            "「协议」选的是代理自身说什么协议，不是被代理流量的协议。\n"
            "B 站接口全是 HTTPS，走 HTTP 代理时要靠 CONNECT 建隧道——\n"
            "只会转发明文 http:// 的代理会报「Tunnel connection failed」，用不了。\n"
            "SOCKS5 (远程 DNS) 把域名解析也交给代理做。\n"
            "「测试」按当前填写的值发一次真实请求——ping 通不代表该端口上有可用代理。"
        )

        # 需要认证的代理：用户名 / 密码拼进地址（scheme://user:pass@host:port），
        # 不填就是匿名代理。密码用 PasswordLineEdit，和 Cookie 一样默认打码。
        self.proxyUserEdit = LineEdit(group)
        self.proxyUserEdit.setPlaceholderText("用户名（可留空）")
        self.proxyUserEdit.setFixedWidth(150)
        self.proxyPassEdit = PasswordLineEdit(group)
        self.proxyPassEdit.setPlaceholderText("密码（可留空）")
        self.proxyPassEdit.setFixedWidth(150)
        self.proxyAuthCard = _WidgetSettingCard(
            FluentIcon.PEOPLE,
            "代理认证",
            "代理要求认证时才填；留空表示匿名代理",
            [self.proxyUserEdit, self.proxyPassEdit],
            group,
        )
        # 组件库风格的提示气泡（原生 tooltip 不跟主题）
        self.proxyCard.installEventFilter(
            ToolTipFilter(self.proxyCard, 500, ToolTipPosition.TOP)
        )

        parts = split_proxy_auth(cfg.proxy.value)
        idx = self.protoCombo.findData(
            parts.scheme if parts.scheme in PROXY_SCHEMES else "http"
        )
        self.protoCombo.setCurrentIndex(max(idx, 0))
        self.hostEdit.setText(parts.host)
        self.portSpin.setValue(parts.port if parts.port > 0 else 7890)
        self.proxyUserEdit.setText(parts.username)
        self.proxyPassEdit.setText(parts.password)

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
            [
                self.dirCard,
                self.proxyCard,
                self.proxyAuthCard,
                self.threadCard,
                self.saveDownloadCard,
            ]
        )
        self.expandLayout.addWidget(group)
        self.downloadGroup = group

        self.browseBtn.clicked.connect(self._on_browse)
        self.openDirBtn.clicked.connect(self._on_open_dir)
        self.downloadSaveBtn.clicked.connect(self._on_save_download)
        self.proxyTestBtn.clicked.connect(self._on_test_proxy)

    def _current_proxy(self) -> str | None:
        """按当前控件值拼代理地址；不合法时弹提示并返回 None。"""
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
            return None
        if host and is_socks(scheme) and not pysocks_available():
            notify_warning(
                "缺少 socks 依赖",
                "socks 代理需要 PySocks，请执行 uv sync 后重启应用；"
                "或先把协议改成 HTTP",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=8000,
            )
            return None
        return build_proxy(
            scheme,
            host,
            self.portSpin.value(),
            self.proxyUserEdit.text().strip(),
            self.proxyPassEdit.text(),
        )  # 主机名为空 -> 不使用代理

    def _on_test_proxy(self) -> None:
        """按当前填写的值发一次真实请求——ping 通不代表那个端口上有代理。"""
        proxy_text = self._current_proxy()
        if proxy_text is None:
            return
        self.proxyTestBtn.setEnabled(False)

        def task():
            return probe_proxy(proxy_text)

        run_task(
            task,
            on_success=self._on_proxy_ok,
            on_error=lambda e: show_bili_error(e, self),
            on_finished=lambda ok: self.proxyTestBtn.setEnabled(True),
        )

    def _on_proxy_ok(self, message: str) -> None:
        notify_success(
            "代理可用",
            message,
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

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
        proxy_text = self._current_proxy()
        if proxy_text is None:  # 校验未过，提示已弹
            return
        qconfig.set(cfg.download_dir, directory)
        qconfig.set(cfg.proxy, proxy_text)
        qconfig.set(cfg.max_workers, self.threadSpin.value())
        signal_bus.configChanged.emit()
        notify_success(
            "已保存",
            "下载目录、代理与线程数已保存到本机配置",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    # ---- 缓存 ----
    def _build_cache_group(self) -> None:
        group = SettingCardGroup("缓存", self.scrollWidget)

        self.cacheSpin = SpinBox(group)
        self.cacheSpin.setRange(64, 8192)
        self.cacheSpin.setSingleStep(64)
        self.cacheSpin.setValue(cfg.cache_limit_mb.value)
        # SpinBox 右侧上下按钮占掉约 64px，四位数要给够宽度否则被裁
        self.cacheSpin.setFixedWidth(140)
        self.cacheLimitCard = _WidgetSettingCard(
            FluentIcon.CLOUD,
            "缓存上限",
            "图片与接口响应最多占用的磁盘空间（64–8192 MB），修改后立即生效",
            [self.cacheSpin],
            group,
        )

        self.clearCacheBtn = PushButton("清除缓存", group)
        self.cacheUsageCard = _WidgetSettingCard(
            FluentIcon.BROOM,
            "缓存占用",
            "统计中…",
            [self.clearCacheBtn],
            group,
        )

        group.addSettingCards([self.cacheLimitCard, self.cacheUsageCard])
        self.expandLayout.addWidget(group)
        self.cacheGroup = group

        self.cacheSpin.valueChanged.connect(self._on_cache_limit_changed)
        self.clearCacheBtn.clicked.connect(self._on_clear_cache)
        self._refresh_cache_usage()

    def _on_cache_limit_changed(self, value: int) -> None:
        # 即时保存（同主题下拉的风格）：下次 put 时现读该值，无需重启
        qconfig.set(cfg.cache_limit_mb, value)
        self._refresh_cache_usage()

    def _refresh_cache_usage(self) -> None:
        """扫目录算占用。文件可能上万，放后台线程，避免卡住主线程。"""
        limit = cfg.cache_limit_mb.value

        def on_ok(used: int) -> None:
            self.cacheUsageCard.setContent(
                f"已用 {used / MB:.1f} MB / 上限 {limit} MB"
            )

        run_task(
            total_size,
            on_success=on_ok,
            on_error=lambda e: self.cacheUsageCard.setContent("缓存占用未知"),
        )

    def _on_clear_cache(self) -> None:
        self.clearCacheBtn.setEnabled(False)
        run_task(
            clear_all,
            on_success=self._on_cache_cleared,
            on_finished=self._on_clear_cache_finished,
        )

    def _on_cache_cleared(self, _result) -> None:
        notify_success(
            "已清除",
            "图片与接口响应缓存已清空",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _on_clear_cache_finished(self, _ok: bool) -> None:
        self.clearCacheBtn.setEnabled(True)
        self._refresh_cache_usage()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_cache_usage()  # 每次进设置页刷新占用

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
